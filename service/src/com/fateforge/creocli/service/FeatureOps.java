package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** feature.list, feature.show and feature.delete: the model tree, read and pruned. */
final class FeatureOps {

    private FeatureOps() {
    }

    /** The model tree in regeneration order; internal features only when asked for. */
    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        boolean internal = Json.bool(request, "include_internal", false);
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        List<Object> rows = new ArrayList<>();
        com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            if (internal || visible == null || visible.contains(f.GetId())) {
                rows.add(Creo.featureRow(f, visible));
            }
        }
        return Json.map("model", Creo.fileName((Model) solid), "features", rows);
    }

    /**
     * One feature in full: its dimensions with the values Creo holds, its parents and
     * children, and what its sections contain. {@code dump_tree} writes the element tree to
     * a file -- a development aid for learning how Creo builds a kind of feature.
     */
    static Map<String, Object> show(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        Feature feature = Creo.feature(solid, Json.string(request, "feature"));
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        Map<String, Object> out = Creo.featureRow(feature, visible);
        out.put("parents", rows(feature.ListParents(), visible));
        out.put("children", rows(feature.ListChildren(), visible));
        List<Object> dimensions = new ArrayList<>();
        try {
            com.ptc.pfc.pfcModelItem.ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
            for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
                com.ptc.pfc.pfcDimension.BaseDimension dim = (com.ptc.pfc.pfcDimension.BaseDimension) dims.get(i);
                dimensions.add(Json.map("name", dim.GetSymbol(), "value", dim.GetDimValue(),
                        "type", Creo.enumName(dim.GetDimType())));
            }
        } catch (Throwable failure) {
            dimensions.add(Json.map("error", Failures.error(failure)));
        }
        out.put("dimensions", dimensions);
        Map<String, Object> machining = MachiningReadback.read(feature);
        if (machining == null) {
            machining = RevolvedReadback.read(feature);
        }
        if (machining == null) {
            machining = PrismaticReadback.definition(feature);
            if (machining == null) machining = DraftReadback.definition(feature);
            if (machining == null) machining = RibReadback.definition(feature);
            if (machining != null) out.put("native_solid_geometry", PrismaticReadback.geometry(solid));
        }
        if (machining != null) {
            out.put("native_definition", machining);
        }
        String featureType = Creo.enumName(feature.GetFeatType());
        out.put("native_definition_status", machining == null
                ? ("FEATTYPE_COORD_SYS".equals(featureType) || "FEATTYPE_COMPONENT".equals(featureType)
                    ? "not_applicable" : "unsupported")
                : Boolean.TRUE.equals(machining.get("complete")) && machining.get("error") == null ? "success" : "failure");
        out.put("native_tree_observation", machining != null && machining.get("tree_observation") != null
                ? machining.get("tree_observation") : DefinitionObservation.read(feature));
        Map<String, Object> auxiliaryDatums = RibReadback.auxiliaryDatums(solid, feature);
        if (auxiliaryDatums != null) out.put("native_auxiliary_datums", auxiliaryDatums);
        List<Object> sections = new ArrayList<>();
        if (feature instanceof WFeature) {
            try {
                com.ptc.wfc.wfcSection.Sections found = ((WFeature) feature).GetSections();
                for (int i = 0; found != null && i < found.getarraysize(); i++) {
                    sections.add(Sketches.describe(found.get(i)));
                }
            } catch (Throwable failure) {
                sections.add(Json.map("error", Failures.error(failure)));
            }
            String target = Json.string(request, "dump_tree", null);
            if (target != null) {
                try {
                    ((WFeature) feature).GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS)
                            .WriteElementTreeToFile(com.ptc.wfc.wfcElementTree.ElementTreeFormat.ELEMTREE_XML, target);
                    out.put("tree_file", target);
                } catch (Throwable failure) {
                    out.put("tree_error", Failures.error(failure));
                }
            }
        }
        out.put("sections", sections);
        if (!sections.isEmpty()) {
            SketchPlan.Read nativeRead = SketchPlan.read(solid, feature);
            out.put("native_section_readback", nativeRead.observation);
            out.put("held_together", nativeRead.held);
        }
        return out;
    }

    /**
     * Delete a feature together with every feature that depends on it. Left in place, the
     * children would fail regeneration, which PTC warns about; so they go too, and the reply
     * lists them -- found here, transitively, before anything is deleted, which is also what
     * the preview showed -- and says which, if any, are still there afterwards.
     */
    static Map<String, Object> delete(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        Feature feature = Creo.feature(solid, Json.string(request, "feature"));
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        Map<Integer, Feature> doomed = new LinkedHashMap<>();
        collect(feature, doomed);
        List<Object> removed = new ArrayList<>();
        for (Feature f : doomed.values()) {
            removed.add(Creo.featureRow(f, visible));
        }
        Double before = Creo.volumeOf(Creo.measure(solid));
        Creo.deleteFeatures(solid, feature.GetId());
        Creo.repaint(session);
        List<Object> survivors = new ArrayList<>();
        for (Integer id : doomed.keySet()) {
            try {
                if (solid.GetFeatureById(id) != null) {
                    survivors.add(id);
                }
            } catch (Throwable gone) {
                // Absent, as intended.
            }
        }
        Set<Integer> remaining = Creo.visibleFeatureIds(solid);
        Double after = Creo.volumeOf(Creo.measure(solid));
        return Json.map("model", Creo.fileName((Model) solid), "deleted", removed, "still_present", survivors,
                "feature_count", remaining == null ? null : remaining.size(),
                "volume", Json.map("before", before, "after", after,
                        "change", before == null || after == null ? null : after - before));
    }

    private static void collect(Feature feature, Map<Integer, Feature> into) throws jxthrowable {
        if (into.containsKey(feature.GetId())) {
            return;
        }
        into.put(feature.GetId(), feature);
        com.ptc.pfc.pfcFeature.Features children = feature.ListChildren();
        for (int i = 0; children != null && i < children.getarraysize(); i++) {
            collect(children.get(i), into);
        }
    }

    private static List<Object> rows(com.ptc.pfc.pfcFeature.Features features, Set<Integer> visible) throws jxthrowable {
        List<Object> out = new ArrayList<>();
        for (int i = 0; features != null && i < features.getarraysize(); i++) {
            Feature f = features.get(i);
            out.add(Json.map("id", f.GetId(), "name", f.GetName(), "type", Creo.enumName(f.GetFeatType()),
                    "visible", visible == null ? null : visible.contains(f.GetId())));
        }
        return out;
    }

    /**
     * Suppress a feature and every feature that depends on it, as the model tree's Suppress
     * does. Suppressed features stay in the model and come back with feature.resume.
     */
    static Map<String, Object> suppress(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        Feature feature = Creo.feature(solid, Json.string(request, "feature"));
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        Map<Integer, Feature> affected = new LinkedHashMap<>();
        collect(feature, affected);
        Double before = Creo.volumeOf(Creo.measure(solid));
        com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
        ids.append(feature.GetId());
        com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions options =
                com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions.create();
        options.append(com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOption.FEAT_SUPP_OR_DEL_CLIP);
        ((com.ptc.wfc.wfcSolid.WSolid) solid).SuppressFeatures(ids, options,
                com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions.WRegenInstructions_Create());
        Creo.repaint(session);
        return statusReply(solid, affected.values(), visible, before);
    }

    /** Resume a suppressed feature, with the parents it needs, as the model tree's Resume does. */
    static Map<String, Object> resume(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        Feature feature = Creo.feature(solid, Json.string(request, "feature"));
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        Double before = Creo.volumeOf(Creo.measure(solid));
        com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
        ids.append(feature.GetId());
        com.ptc.wfc.wfcFeatureInstructions.FeatResumeOptions options =
                com.ptc.wfc.wfcFeatureInstructions.FeatResumeOptions.create();
        options.append(com.ptc.wfc.wfcFeatureInstructions.FeatResumeOption.FEAT_RESUME_INCLUDE_PARENTS);
        ((com.ptc.wfc.wfcSolid.WSolid) solid).ResumeFeatures(ids, options,
                com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions.WRegenInstructions_Create());
        Creo.repaint(session);
        List<Feature> one = new ArrayList<>();
        one.add(solid.GetFeatureById(feature.GetId()));
        return statusReply(solid, one, visible, before);
    }

    private static Map<String, Object> statusReply(Solid solid, java.util.Collection<Feature> features,
                                                   Set<Integer> visible, Double before) throws jxthrowable {
        List<Object> rows = new ArrayList<>();
        for (Feature f : features) {
            rows.add(Creo.featureRow(solid.GetFeatureById(f.GetId()), visible));
        }
        Double after = Creo.volumeOf(Creo.measure(solid));
        return Json.map("model", Creo.fileName((Model) solid), "features", rows,
                "volume", Json.map("before", before, "after", after,
                        "change", before == null || after == null ? null : after - before));
    }

    /** Give a feature the name a person would type in the model tree. */
    static Map<String, Object> rename(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        Feature feature = Creo.feature(solid, Json.string(request, "feature"));
        String name = Json.string(request, "name");
        com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature other = all.get(i);
            if (other.GetId() != feature.GetId() && name.equalsIgnoreCase(String.valueOf(other.GetName()))) {
                throw new Failures.Refusal("E_CONFLICT", "feature " + other.GetId() + " is already named " + name);
            }
        }
        String before = feature.GetName();
        feature.SetName(name);
        return Json.map("model", Creo.fileName((Model) solid), "before", before,
                "feature", Creo.featureRow(solid.GetFeatureById(feature.GetId()), Creo.visibleFeatureIds(solid)));
    }
}
