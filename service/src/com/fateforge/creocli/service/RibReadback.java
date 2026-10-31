package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcDimension.DimensionType;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.Features;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcDimension.WDimension;
import com.ptc.wfc.wfcSection.Section;
import com.ptc.wfc.wfcSection.SectionDimIds;
import com.ptc.wfc.wfcSection.Sections;
import java.lang.ref.Reference;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Independent rib tree and driving-thickness observations; never uses a creation request. */
final class RibReadback {
    private RibReadback() { }

    static Map<String, Object> definition(Feature feature) {
        List<Object> owners = new ArrayList<>();
        Map<String, Object> dimensionInventory = Json.map("complete", false,
                "source", "native dimension type/accessibility/owner/reference/relation and section-ID getters");
        owners.add(feature);
        try {
            if (!"FEATTYPE_RIB".equals(Creo.enumName(feature.GetFeatType()))) return null;
            ElementTree tree = ((WFeature) feature).GetElementTree(null,
                    FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            if (tree == null) throw incomplete("rib tree is unavailable");
            owners.add(tree);
            Elements elements = tree.ListTreeElements();
            owners.add(elements);
            int form = integer(elements, Ptc.PRO_E_FEATURE_FORM, owners);
            double thickness = value(elements, Ptc.PRO_E_RIB_THICKNESS, owners).GetDoubleValue();
            if (!Double.isFinite(thickness) || thickness <= 0)
                throw incomplete("native rib thickness is not finite and positive");
            int side = integer(elements, Ptc.PRO_E_RIB_SIDE_OPTS, owners);
            Elements body = children(elements, Ptc.PRO_E_BODY, owners);
            int bodyUse = integer(body, Ptc.PRO_E_BODY_USE, owners);
            ModelItem selectedBody = selected(body, Ptc.PRO_E_BODY_SELECT, owners);
            if (selectedBody.GetType().getValue() != ModelItemType._ITEM_BODY)
                throw incomplete("native rib body selection does not identify a body");
            Elements ribSection = children(elements, Ptc.PRO_E_RIB_SECTION_COMP, owners);
            int fill = integer(ribSection, Ptc.PRO_E_STD_MATRLSIDE, owners);
            Elements section = children(ribSection, Ptc.PRO_E_STD_SECTION, owners);
            Elements setup = children(section, Ptc.PRO_E_STD_SEC_SETUP_PLANE, owners);
            String plane = Geometry.ref(selected(setup, Ptc.PRO_E_STD_SEC_PLANE, owners));
            String orientRef = Geometry.ref(selected(setup, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_REF, owners));
            int planeViewDir = integer(setup, Ptc.PRO_E_STD_SEC_PLANE_VIEW_DIR, owners);
            int orientDir = integer(setup, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_DIR, owners);
            return Json.map("complete", true, "kind", "rib",
                    "form", form == Ptc.PRO_EXTRUDE ? "extrude" : "other",
                    "body_use", bodyUse == Ptc.PRO_BODY_USE_SELECTED ? "selected" : "other",
                    "body_id", selectedBody.GetId(), "thickness", thickness,
                    "side", side == Ptc.PRO_RIB_SYMMETRIC ? "symmetric"
                            : side == Ptc.PRO_RIB_SIDE_ONE ? "one"
                            : side == Ptc.PRO_RIB_SIDE_TWO ? "two" : "other",
                    "fill", fill == Ptc.PRO_RIB_SEC_SIDE_ONE ? "right"
                            : fill == Ptc.PRO_RIB_SEC_SIDE_TWO ? "left" : "other",
                    "plane", plane, "orient_ref", orientRef,
                    "plane_view_dir", planeViewDir, "orient", orientation(orientDir),
                    "orient_dir", orientDir,
                    "thickness_dimension", thicknessDimension(feature, thickness, owners, dimensionInventory),
                    "thickness_dimension_inventory", dimensionInventory,
                    "source", "independent held WFeature rib tree, native selections and driving dimension; no creation request used");
        } catch (Throwable failure) {
            return Json.map("complete", false, "kind", "rib", "source", "native rib tree and driving dimension",
                    "error", Failures.error(failure), "thickness_dimension_inventory", dimensionInventory);
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    private static Map<String, Object> thicknessDimension(Feature feature, double thickness,
                                                         List<Object> owners,
                                                         Map<String, Object> inspection) throws Exception {
        // Not every scalar feature element publishes an element-to-dimension mapping.
        // PTC's UtilFeats.c explicitly allows E_NOT_FOUND from that mapping getter.
        // Identify the unique actual model-owned non-sketch linear dimension first;
        // its value is a subsequent cross-check, never a way to pick a candidate.
        inspection.put("stage", "native_sections");
        Set<Integer> sketched = sketchDimensionIds(feature, owners, inspection);
        inspection.put("stage", "feature_dimension_inventory");
        ModelItems dimensions = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        owners.add(dimensions);
        if (dimensions == null || dimensions.getarraysize() > 256)
            throw incomplete("rib driving dimension inventory is unavailable");
        int count = dimensions.getarraysize();
        inspection.put("native_dimension_count", count);
        List<Object> entries = new ArrayList<>();
        List<Object> candidates = new ArrayList<>();
        inspection.put("entries", entries);
        inspection.put("candidate_ids", candidates);
        Set<Integer> observedIds = new HashSet<>();
        BaseDimension found = null;
        for (int i = 0; i < count; i++) {
            ModelItem item = dimensions.get(i);
            if (!(item instanceof BaseDimension) || !(item instanceof WDimension))
                throw incomplete("native rib dimension lacks required read-only dimension interfaces");
            BaseDimension dimension = (BaseDimension) item;
            WDimension nativeDimension = (WDimension) item;
            owners.add(dimension);
            Map<String, Object> row = Json.map("index", i);
            entries.add(row);
            inspection.put("stage", "dimension_identity");
            int id = dimension.GetId();
            row.put("id", id);
            if (id < 0 || !observedIds.add(id)
                    || dimension.GetType().getValue() != ModelItemType._ITEM_DIMENSION)
                throw incomplete("native rib dimension identity is invalid or repeated");
            inspection.put("stage", "dimension_type_and_accessibility");
            DimensionType type = dimension.GetDimType();
            row.put("type", Creo.enumName(type));
            row.put("java_dimension_type_null", type == null);
            row.put("java_dimension_type_value", type == null ? null : type.getValue());
            // OTK Java uses 0..3 for its four known types; zero is LINEAR. Its
            // FromInt adapter maps nil and unknown numbers to null, so a null
            // result cannot identify the underlying C enum. Never infer UNKNOWN
            // or a placeholder type from the public list's display filtering.
            if (type != null && type.getValue() != DimensionType._DIM_LINEAR
                    && type.getValue() != DimensionType._DIM_RADIAL
                    && type.getValue() != DimensionType._DIM_DIAMETER
                    && type.getValue() != DimensionType._DIM_ANGULAR)
                throw incomplete("unrecognized native Java dimension type cannot be classified");
            boolean accessible = nativeDimension.IsAccessibleInModel();
            row.put("accessible_in_model", accessible);
            row.put("in_sketch", sketched.contains(id));
            if (type == null && !accessible) {
                row.put("classification", "explicitly_not_owned_by_model_type_unresolved");
                row.put("exclusion_basis", "successful IsAccessibleInModel=false; no raw C type inferred from Java null");
                row.put("remaining_getters", "not queried for an entry independently proven inaccessible in model");
                continue;
            }
            if (type == null || !accessible)
                throw incomplete("native rib dimension type and model accessibility are inconsistent");
            inspection.put("stage", "dimension_owner");
            Feature owner = nativeDimension.GetOwnerFeature();
            owners.add(owner);
            if (owner == null || owner.GetId() != feature.GetId())
                throw incomplete("native rib dimension owner does not identify this rib");
            row.put("owner_feature_id", owner.GetId());
            row.put("owner_feature_type", Creo.enumName(owner.GetFeatType()));
            if (!"FEATTYPE_RIB".equals(row.get("owner_feature_type")))
                throw incomplete("native rib dimension owner has another feature type");
            inspection.put("stage", "dimension_reference_and_relation");
            boolean reference = nativeDimension.IsReference();
            boolean related = dimension.GetIsRelationDriven();
            row.put("reference", reference);
            row.put("relation_driven", related);
            if (sketched.contains(id)) row.put("classification", "native_section_dimension");
            else if (reference) row.put("classification", "native_reference_dimension");
            else if (related) row.put("classification", "native_relation_driven_dimension");
            else if (type.getValue() != DimensionType._DIM_LINEAR)
                row.put("classification", "native_non_linear_dimension");
            else {
                row.put("classification", "structural_thickness_candidate");
                candidates.add(id);
                found = dimension;
            }
        }
        inspection.put("enumerated_dimension_count", observedIds.size());
        inspection.put("candidate_count", candidates.size());
        inspection.put("stage", "unique_structural_candidate");
        if (candidates.size() != 1 || found == null)
            throw incomplete("exactly one native model-owned non-sketch free linear rib dimension is required");
        inspection.put("stage", "selected_dimension_tree_cross_check");
        double selectedValue = found.GetDimValue();
        inspection.put("selected_value", selectedValue);
        if (!Double.isFinite(selectedValue)
                || Math.abs(selectedValue - thickness) > Math.max(1e-10, Math.abs(thickness) * 1e-10))
            throw incomplete("independently selected rib thickness dimension contradicts the native feature tree");
        String name = found.GetSymbol();
        if (name == null || name.isEmpty()) throw incomplete("native rib thickness dimension has no symbol");
        inspection.put("selected_dimension_id", found.GetId());
        inspection.put("complete", true);
        inspection.put("stage", "complete");
        return Json.map("id", found.GetId(), "name", name, "value", selectedValue,
                "type", "DIM_LINEAR", "owner_feature_id", feature.GetId(),
                "accessible_in_model", true, "reference", false, "relation_driven", false,
                "in_sketch", false, "source",
                "complete native feature dimension inventory; unique accessible owner-bound non-reference non-relation non-sketch linear candidate, then tree-value cross-check; no element mapping or IsDriving call");
    }

    private static Set<Integer> sketchDimensionIds(Feature feature, List<Object> owners,
                                                   Map<String, Object> inspection) throws Exception {
        Sections sections = ((WFeature) feature).GetSections();
        owners.add(sections);
        if (sections == null || sections.getarraysize() != 1)
            throw incomplete("one complete native rib section is required for dimension ownership");
        inspection.put("section_count", sections.getarraysize());
        Set<Integer> ids = new HashSet<>();
        List<Object> pairs = new ArrayList<>();
        inspection.put("section_dimension_pairs", pairs);
        Section section = sections.get(0);
        owners.add(section);
        SectionDimIds dimensions = section.GetSectionDimensions();
        owners.add(dimensions);
        if (dimensions == null) throw incomplete("native rib section dimension mapping is unavailable");
        com.ptc.cipjava.intseq solidIds = dimensions.GetSolidIds();
        com.ptc.cipjava.intseq sectionIds = dimensions.GetSectionIds();
        owners.add(solidIds);
        owners.add(sectionIds);
        if (solidIds == null || sectionIds == null || solidIds.getarraysize() == 0
                || solidIds.getarraysize() > 256 || solidIds.getarraysize() != sectionIds.getarraysize())
            throw incomplete("complete paired native rib section/model dimension identities are required");
        Set<Integer> sectionSeen = new HashSet<>();
        for (int i = 0; i < solidIds.getarraysize(); i++) {
            int modelId = solidIds.get(i), sectionId = sectionIds.get(i);
            if (modelId < 0 || sectionId < 0 || !ids.add(modelId) || !sectionSeen.add(sectionId))
                throw incomplete("native rib section dimension identities are invalid or repeated");
            pairs.add(Json.map("section_id", sectionId, "model_id", modelId));
        }
        List<Integer> orderedIds = new ArrayList<>(ids);
        java.util.Collections.sort(orderedIds);
        inspection.put("native_sketch_dimension_ids", orderedIds);
        return ids;
    }

    /** Native construction side effects identified by dependency and geometry, not containment. */
    static Map<String, Object> auxiliaryDatums(Solid solid, Feature rib) {
        List<Object> owners = new ArrayList<>();
        List<Object> items = new ArrayList<>();
        owners.add(solid);
        owners.add(rib);
        try {
            if (!"FEATTYPE_RIB".equals(Creo.enumName(rib.GetFeatType()))) return null;
            Features datums = solid.ListFeaturesByType(Boolean.FALSE,
                    com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_DATUM_PLANE);
            owners.add(datums);
            Set<Integer> visibleIds = Creo.visibleFeatureIds(solid);
            if (visibleIds == null) throw incomplete("native visible feature inventory is unavailable");
            if (datums == null || datums.getarraysize() > 4096)
                throw incomplete("native datum dependency inventory is unavailable");
            for (int i = 0; i < datums.getarraysize(); i++) {
                Feature datum = datums.get(i);
                owners.add(datum);
                boolean visible = visibleIds.contains(datum.GetId());
                if (visible) continue;
                Features children = datum.ListChildren();
                owners.add(children);
                List<Object> childIds = featureIds(children, owners);
                if (!childIds.contains(rib.GetId())) continue;
                Features parents = datum.ListParents();
                owners.add(parents);
                List<Object> parentIds = featureIds(parents, owners);
                ModelItems surfaces = datum.ListSubItems(ModelItemType.ITEM_SURFACE);
                owners.add(surfaces);
                if (surfaces == null || surfaces.getarraysize() != 1)
                    throw incomplete("auxiliary datum must have exactly one readable native surface");
                Surface surface = (Surface) surfaces.get(0);
                owners.add(surface);
                Map<String, Object> geometry = Geometry.surface(surface, true);
                if (!"plane".equals(geometry.get("type"))
                        || geometry.get("normal") == null || geometry.get("origin") == null)
                    throw incomplete("auxiliary datum plane geometry is unavailable");
                items.add(Json.map("id", datum.GetId(), "name", datum.GetName(),
                        "type", Creo.enumName(datum.GetFeatType()),
                        "status", Creo.enumName(datum.GetStatus()), "visible", visible,
                        "parents", parentIds, "children", childIds,
                        "surface", Json.map("id", surface.GetId(), "ref", "surface:" + surface.GetId(),
                                "type", geometry.get("type"), "normal", geometry.get("normal"),
                                "origin", geometry.get("origin"))));
            }
            return Json.map("complete", true, "kind", "rib_auxiliary_datum_dependencies",
                    "rib_id", rib.GetId(), "items", items, "source",
                    "actual hidden datum ListChildren includes rib; native parents/children and plane geometry; not a container-owner assertion");
        } catch (Throwable failure) {
            return Json.map("complete", false, "kind", "rib_auxiliary_datum_dependencies",
                    "items", items, "error", Failures.error(failure),
                    "source", "native hidden datum dependency and geometry getters; no container ownership inferred");
        } finally {
            Reference.reachabilityFence(owners);
        }
    }

    private static List<Object> featureIds(Features features, List<Object> owners) throws Exception {
        List<Object> ids = new ArrayList<>();
        // A successfully returned nullable native feature sequence means no dependencies.
        if (features == null) return ids;
        if (features.getarraysize() > 4096) throw incomplete("datum dependency list exceeds reader bound");
        for (int i = 0; i < features.getarraysize(); i++) {
            Feature feature = features.get(i);
            if (feature == null) throw incomplete("native datum dependency identity is missing");
            owners.add(feature);
            int id = feature.GetId();
            if (ids.contains(id)) throw incomplete("native datum dependency identities are repeated");
            ids.add(id);
        }
        return ids;
    }

    private static String orientation(int value) {
        if (value == Ptc.PRO_SEC_ORIENT_DIR_RIGHT) return "right";
        if (value == Ptc.PRO_SEC_ORIENT_DIR_LEFT) return "left";
        if (value == Ptc.PRO_SEC_ORIENT_DIR_UP) return "up";
        if (value == Ptc.PRO_SEC_ORIENT_DIR_DOWN) return "down";
        return "other";
    }

    private static Elements children(Elements elements, int id, List<Object> owners) throws Exception {
        Elements children = one(elements, id, owners).GetChildren();
        if (children == null) throw incomplete("missing rib tree children " + id);
        owners.add(children);
        return children;
    }

    private static Element one(Elements elements, int id, List<Object> owners) throws Exception {
        if (elements == null || elements.getarraysize() > 4096) throw incomplete("rib tree inventory unavailable");
        Element found = null;
        for (int i = 0; i < elements.getarraysize(); i++) {
            Element element = elements.get(i);
            owners.add(element);
            if (element.GetId() == id) {
                if (found != null) throw incomplete("ambiguous rib tree element " + id);
                found = element;
            }
        }
        if (found == null) throw incomplete("missing rib tree element " + id);
        return found;
    }

    private static ArgValue value(Elements elements, int id, List<Object> owners) throws Exception {
        ArgValue value = one(elements, id, owners).GetValue();
        if (value == null) throw incomplete("missing rib tree value " + id);
        owners.add(value);
        return value;
    }

    private static int integer(Elements elements, int id, List<Object> owners) throws Exception {
        return value(elements, id, owners).GetIntValue();
    }

    private static ModelItem selected(Elements elements, int id, List<Object> owners) throws Exception {
        Selection selected = value(elements, id, owners).GetSelectionValue();
        if (selected == null) throw incomplete("missing rib reference " + id);
        owners.add(selected);
        ModelItem item = selected.GetSelItem();
        if (item == null) throw incomplete("missing rib selected item " + id);
        owners.add(item);
        return item;
    }

    private static Failures.Refusal incomplete(String message) {
        return new Failures.Refusal("E_VERIFY_INCOMPLETE", message);
    }
}
