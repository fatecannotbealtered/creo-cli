package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.Distance;
import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.ptc.cipjava.jxthrowable;
import com.ptc.cipjava.stringseq;
import com.ptc.pfc.pfcAssembly.Assembly;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Vector3D;
import com.ptc.pfc.pfcComponentFeat.ComponentFeat;
import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcDimension.DimToleranceLimits;
import com.ptc.pfc.pfcDimension.DimToleranceType;
import com.ptc.pfc.pfcDimension.DimensionType;
import com.ptc.pfc.pfcDimension.pfcDimension;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.FeatureType;
import com.ptc.pfc.pfcFeature.Features;
import com.ptc.pfc.pfcGeometry.Edge;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.TransformedSurface;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcModelItem.ParamValue;
import com.ptc.pfc.pfcModelItem.ParamValueType;
import com.ptc.pfc.pfcModelItem.Parameter;
import com.ptc.pfc.pfcModelItem.Parameters;
import com.ptc.pfc.pfcModelItem.RelationOwner;
import com.ptc.pfc.pfcModelItem.pfcModelItem;
import com.ptc.pfc.pfcPart.Material;
import com.ptc.pfc.pfcPart.Materials;
import com.ptc.pfc.pfcPart.Part;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.MassProperty;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.WRegenInstructions;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The domain commands (contract/commands.json): read, preview, apply and read_back. A write
 * builds one plan -- its targets, its changes and the work -- for both preview and apply, so
 * what the person confirmed is what runs. Lengths cross in millimetres and are converted to
 * the model's units here. Everything runs on Creo's main thread.
 */
final class Ops {
    private static final Pattern FEATURE_NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_]{0,30}");
    private static final Pattern WITH_UNIT = Pattern.compile("^\\s*([-+]?[0-9]*\\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\\s*([A-Za-z]+)\\s*$");
    private static final double DPI = 100.0;

    private final Docs docs;

    Ops(Docs docs) {
        this.docs = docs;
    }

    /** One write, as preview shows it and apply does it. */
    private interface Work {
        Map<String, Object> run() throws Exception;
    }

    private static final class Plan {
        String action;
        final List<Map<String, Object>> targets = new ArrayList<>();
        final List<Map<String, Object>> changes = new ArrayList<>();
        final List<String> blocked = new ArrayList<>();
        /** Knowledge entries that tell what to do about a blocked change (DSKL-124). */
        final List<String> knowledge = new ArrayList<>();
        Work work;
        String docId;
        boolean records = true;

        void block(String reason, String entry) {
            blocked.add(reason);
            if (entry != null && !knowledge.contains(entry)) {
                knowledge.add(entry);
            }
        }

        void target(String key, String kind, String label) {
            Map<String, Object> t = Json.map("key", key, "kind", kind);
            if (label != null) {
                t.put("label", label);
            }
            targets.add(t);
        }

        void change(String key, String field, Object before, Object after) {
            changes.add(Json.map("target", key, "field", field, "before", before, "after", after));
        }
    }

    // ------------------------------------------------------------------ read

    Map<String, Object> read(Map<String, Object> params) throws Exception {
        String command = Json.string(params, "command", "");
        Map<String, Object> in = Json.object(params, "inputs");
        Model model = docs.model(Json.string(params, "document", null));
        Object result;
        switch (command) {
            case "model get": result = modelGet(model); break;
            case "feature list": result = items(featureList(Creo.solid(model))); break;
            case "feature get": result = featureGet(Creo.solid(model), required(in, "id")); break;
            case "geometry list": result = items(geometryList(Creo.solid(model), Json.string(in, "kind", null), Json.string(in, "feature", null))); break;
            case "distance get": result = distance(Creo.solid(model), required(in, "from"), required(in, "to")); break;
            case "dimension list": result = items(dimensionList(Creo.solid(model), Json.string(in, "feature", null))); break;
            case "parameter list": result = items(parameterList(model)); break;
            case "relation list": result = items(relations(model)); break;
            case "material list": result = items(materials(model, Json.string(in, "query", null))); break;
            case "component list": result = items(components(model)); break;
            default: throw new HostError(HostError.UNSUPPORTED, "The host has no read for " + command + ".");
        }
        return Json.map("result", result);
    }

    private static Map<String, Object> items(List<Map<String, Object>> items) {
        return Json.map("items", items);
    }

    private static String required(Map<String, Object> in, String key) {
        String value = Json.string(in, key, null);
        if (value == null || value.trim().isEmpty()) {
            throw new HostError(HostError.VALIDATION, "--" + key.replace('_', '-') + " is required.");
        }
        return value.trim();
    }

    // ------------------------------------------------------------------ preview, apply, read_back

    Map<String, Object> preview(Map<String, Object> params) throws Exception {
        String command = Json.string(params, "command", "");
        if ("doc save".equals(command)) {
            return savePreview(docs.model(Json.string(params, "document", null)));
        }
        Plan plan = plan(params);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("action", plan.action);
        out.put("targets", plan.targets);
        out.put("changes", plan.changes);
        out.put("can_apply", plan.blocked.isEmpty());
        if (!plan.blocked.isEmpty()) {
            out.put("blocked_by", plan.blocked);
            if (!plan.knowledge.isEmpty()) {
                out.put("knowledge", plan.knowledge);
            }
        }
        return out;
    }

    Map<String, Object> apply(Map<String, Object> params) throws Exception {
        Plan plan = plan(params);
        if (!plan.blocked.isEmpty()) {
            HostError refused = new HostError(HostError.VALIDATION, String.join(" ", plan.blocked));
            throw plan.knowledge.isEmpty() ? refused : refused.with("knowledge", plan.knowledge);
        }
        Map<String, Object> facts;
        docs.writing(true);
        try {
            facts = plan.work.run();
        } finally {
            docs.writing(false);
        }
        if (plan.records && plan.docId != null) {
            docs.recordToolChanges(plan.docId, plan.changes);
        }
        return facts;
    }

    Map<String, Object> readBack(Map<String, Object> params) throws Exception {
        Model model = docs.model(Json.string(params, "document", null));
        String docKey = docs.key(model);
        Map<String, Object> observed = new LinkedHashMap<>();
        List<Object> unreadable = new ArrayList<>();
        Object rawTargets = params.get("targets");
        List<?> targets = rawTargets instanceof List ? (List<?>) rawTargets : new ArrayList<>();
        for (Object t : targets) {
            String key = String.valueOf(t);
            if (key.equals(docKey)) {
                // doc save: Creo reads a saved file again only after the model is erased and
                // retrieved, so the fields come from the model and `saved` says that the save
                // wrote a new version file, which is still on disk (DCLI-057).
                observed.put(key, Json.map("saved", docs.savedToDisk(model)));
                continue;
            }
            if (!key.startsWith(docKey + "#")) {
                unreadable.add(key);
                continue;
            }
            String path = key.substring(docKey.length() + 1);
            try {
                observed.put(key, readObject(model, path));
            } catch (HostError gone) {
                observed.put(key, Json.map("exists", false));
            }
        }
        Map<String, Object> out = Json.map("observed", observed);
        if (!unreadable.isEmpty()) {
            out.put("unreadable", unreadable);
        }
        return out;
    }

    /** The fields of one object, named as the preview's changes name them. */
    private Map<String, Object> readObject(Model model, String path) throws Exception {
        if (path.startsWith("/dimensions/")) {
            Solid solid = Creo.solid(model);
            BaseDimension dim = (BaseDimension) Creo.dimension(solid, path.substring("/dimensions/".length()))[0];
            Map<String, Object> out = new LinkedHashMap<>();
            double f = Units.mmPerUnit(model);
            boolean angle = angular(dim);
            if (angle) {
                out.put("value_deg", clean(dim.GetDimValue()));
            } else {
                out.put("value_mm", clean(dim.GetDimValue() * f));
            }
            Map<String, Object> tol = tolerance(dim, angle ? 1.0 : f, angle);
            out.put("tolerance_type", tol.get("type"));
            for (String k : new String[] {"plus_mm", "minus_mm", "upper_mm", "lower_mm", "plus_deg", "minus_deg",
                    "upper_deg", "lower_deg", "fit"}) {
                if (tol.containsKey(k)) {
                    out.put(k, tol.get(k));
                }
            }
            return out;
        }
        if (path.startsWith("/parameters/")) {
            Parameter p = parameter(model, path.substring("/parameters/".length()));
            return Json.map("value", plain(p.GetValue()));
        }
        if (path.startsWith("/features/")) {
            Feature f = Creo.feature(Creo.solid(model), path.substring("/features/".length()));
            return Json.map("status", Creo.shortName(f.GetStatus(), "FEAT_"), "name", f.GetName());
        }
        throw new HostError(HostError.NOT_FOUND, "Nothing at " + path + ".");
    }

    private Map<String, Object> savePreview(Model model) throws jxthrowable {
        String id = Creo.fileName(model);
        String key = docs.key(model);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("action", "Save " + id + "; Creo writes a new numbered version of it.");
        out.put("targets", Arrays.asList(Json.map("key", key, "kind", "document")));
        List<Map<String, Object>> changes = new ArrayList<>();
        for (Map<String, Object> c : docs.toolChangesSinceSave(id)) {
            Map<String, Object> copy = new LinkedHashMap<>(c);
            copy.put("origin", "tool");
            changes.add(copy);
        }
        out.put("changes", changes);
        List<Map<String, Object>> outside = new ArrayList<>();
        if (docs.changedOutside(id)) {
            outside.add(Json.map("target", key, "before", null, "after", null, "origin", "external"));
        }
        out.put("external_changes", outside);
        out.put("can_apply", true);
        return out;
    }

    private Plan plan(Map<String, Object> params) throws Exception {
        String command = Json.string(params, "command", "");
        Map<String, Object> in = Json.object(params, "inputs");
        Model model = docs.model(Json.string(params, "document", null));
        Plan plan = new Plan();
        plan.docId = Creo.fileName(model);
        switch (command) {
            case "dimension update": dimensionUpdate(plan, model, in); break;
            case "parameter update": parameterUpdate(plan, model, in); break;
            case "feature update": featureUpdate(plan, model, in); break;
            case "model export": export(plan, model, in); break;
            case "model render": render(plan, model, in); break;
            default: throw new HostError(HostError.UNSUPPORTED, "The host has no write for " + command + ".");
        }
        return plan;
    }

    // ------------------------------------------------------------------ model get

    private Map<String, Object> modelGet(Model model) throws Exception {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("name", Creo.fileName(model));
        out.put("kind", Creo.kind(model));
        if (!(model instanceof Solid)) {
            out.put("units", Json.map());
            out.put("material", null);
            out.put("feature_count", null);
            return out;
        }
        Solid solid = (Solid) model;
        double f = Units.mmPerUnit(model);
        out.put("units", Json.map("length", Units.lengthName(model), "mass", Units.massName(model)));
        String material = null;
        if (model instanceof Part) {
            try {
                Material m = ((Part) model).GetCurrentMaterial();
                material = m == null ? null : m.GetName();
            } catch (Throwable none) {
                material = null;
            }
        }
        out.put("material", material);
        MassProperty mass = null;
        boolean density = true;
        try {
            mass = solid.GetMassProperty(null);
        } catch (Throwable noDensity) {
            density = false;
            mass = solid.GetMassPropertyWithDensity(null, com.ptc.pfc.pfcSolid.MPDensityUse.MP_DENSITY_USE_IF_MISSING, 1.0);
        }
        double volume = mass.GetVolume() * f * f * f;
        out.put("volume_mm3", clean(volume));
        out.put("surface_area_mm2", clean(mass.GetSurfaceArea() * f * f));
        Double kg = Units.kgPerUnit(model);
        Double massKg = density && kg != null ? clean(mass.GetMass() * kg) : null;
        out.put("mass_kg", massKg);
        Point3D cog = mass.GetGravityCenter();
        out.put("center_of_mass_mm", cog == null ? null : point(cog, f));
        try {
            com.ptc.pfc.pfcBase.Outline3D box = solid.GetGeomOutline();
            out.put("bounding_box_mm", Json.map("min", point(box.get(0), f), "max", point(box.get(1), f)));
        } catch (Throwable none) {
            out.put("bounding_box_mm", null);
        }
        out.put("feature_count", Creo.visibleFeatureIds(solid).size());
        return out;
    }

    // ------------------------------------------------------------------ features

    private List<Map<String, Object>> featureList(Solid solid) throws jxthrowable {
        Set<Integer> visible = Creo.visibleFeatureIds(solid);
        List<Map<String, Object>> rows = new ArrayList<>();
        Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            if (visible.contains(all.get(i).GetId())) {
                rows.add(Creo.featureRow(all.get(i)));
            }
        }
        return rows;
    }

    private Map<String, Object> featureGet(Solid solid, String id) throws Exception {
        Feature feature = Creo.feature(solid, id);
        Map<String, Object> out = Creo.featureRow(feature);
        double f = Units.mmPerUnit((Model) solid);
        List<Map<String, Object>> dims = new ArrayList<>();
        ModelItems items = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            dims.add(dimensionRow((BaseDimension) items.get(i), feature, f));
        }
        out.put("dimensions", dims);
        out.put("parents", relatives(feature.ListParents()));
        out.put("children", relatives(feature.ListChildren()));
        return out;
    }

    private static List<Map<String, Object>> relatives(Features features) throws jxthrowable {
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; features != null && i < features.getarraysize(); i++) {
            Feature f = features.get(i);
            out.add(Json.map("id", f.GetId(), "name", f.GetName(), "type", Creo.shortName(f.GetFeatType(), "FEATTYPE_")));
        }
        return out;
    }

    private void featureUpdate(Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        Feature feature = Creo.feature(solid, required(in, "id"));
        String status = Json.string(in, "status", null);
        String name = Json.string(in, "name", null);
        if (status == null && name == null) {
            throw new HostError(HostError.VALIDATION, "Give --status, --name or both.");
        }
        if (status != null && !status.equals("suppressed") && !status.equals("active")) {
            throw new HostError(HostError.VALIDATION, "--status is suppressed or active, not " + status + ".");
        }
        String docKey = docs.key(model);
        int id = feature.GetId();
        String key = docKey + "#/features/" + id;
        plan.target(key, "feature", feature.GetName());
        StringBuilder action = new StringBuilder();
        List<Feature> alongWith = new ArrayList<>();
        if (status != null) {
            String now = Creo.shortName(feature.GetStatus(), "FEAT_");
            plan.change(key, "status", now, status);
            if ("suppressed".equals(status)) {
                Map<Integer, Feature> children = new LinkedHashMap<>();
                collect(feature, children, true);
                children.remove(id);
                for (Feature child : children.values()) {
                    String was = Creo.shortName(child.GetStatus(), "FEAT_");
                    if ("active".equals(was)) {
                        alongWith.add(child);
                        plan.change(docKey + "#/features/" + child.GetId(), "status", was, "suppressed");
                    }
                }
                action.append("Suppress feature ").append(id);
                if (!alongWith.isEmpty()) {
                    action.append(" and the ").append(alongWith.size()).append(" features that depend on it");
                }
            } else {
                Map<Integer, Feature> parents = new LinkedHashMap<>();
                collect(feature, parents, false);
                parents.remove(id);
                for (Feature parent : parents.values()) {
                    String was = Creo.shortName(parent.GetStatus(), "FEAT_");
                    if ("suppressed".equals(was)) {
                        alongWith.add(parent);
                        plan.change(docKey + "#/features/" + parent.GetId(), "status", was, "active");
                    }
                }
                action.append("Resume feature ").append(id);
                if (!alongWith.isEmpty()) {
                    action.append(" with the ").append(alongWith.size()).append(" suppressed features it needs");
                }
            }
        }
        if (name != null) {
            if (!FEATURE_NAME.matcher(name).matches()) {
                throw new HostError(HostError.VALIDATION, "A feature name is a letter, then letters, digits or _, 31 at most; "
                        + name + " is not one.");
            }
            Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                if (all.get(i).GetId() != id && name.equalsIgnoreCase(String.valueOf(all.get(i).GetName()))) {
                    plan.blocked.add("Feature " + all.get(i).GetId() + " is already named " + name);
                }
            }
            plan.change(key, "name", feature.GetName(), name.toUpperCase(Locale.ROOT));
            action.append(action.length() == 0 ? "Rename feature " + id : "; rename it").append(" to ").append(name.toUpperCase(Locale.ROOT));
        }
        plan.action = action + ".";
        plan.work = () -> {
            WSolid w = (WSolid) solid;
            if ("suppressed".equals(status) && !"suppressed".equals(Creo.shortName(feature.GetStatus(), "FEAT_"))) {
                com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
                ids.append(id);
                com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions options =
                        com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions.create();
                options.append(com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOption.FEAT_SUPP_OR_DEL_CLIP);
                try {
                    w.SuppressFeatures(ids, options, wfcSolidInstructions.WRegenInstructions_Create());
                } catch (jxthrowable refused) {
                    throw new HostError(HostError.NATIVE, "Creo did not suppress feature " + id + ".", "dispatched")
                            .nativeMessage(refused.toString());
                }
            } else if ("active".equals(status) && !"active".equals(Creo.shortName(feature.GetStatus(), "FEAT_"))) {
                com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
                ids.append(id);
                com.ptc.wfc.wfcFeatureInstructions.FeatResumeOptions options =
                        com.ptc.wfc.wfcFeatureInstructions.FeatResumeOptions.create();
                options.append(com.ptc.wfc.wfcFeatureInstructions.FeatResumeOption.FEAT_RESUME_INCLUDE_PARENTS);
                try {
                    w.ResumeFeatures(ids, options, wfcSolidInstructions.WRegenInstructions_Create());
                } catch (jxthrowable refused) {
                    throw new HostError(HostError.NATIVE, "Creo did not resume feature " + id + ".", "dispatched")
                            .nativeMessage(refused.toString());
                }
            }
            if (name != null) {
                try {
                    solid.GetFeatureById(id).SetName(name);
                } catch (jxthrowable refused) {
                    throw new HostError(HostError.NATIVE, "Creo did not rename feature " + id + ".", "dispatched")
                            .nativeMessage(refused.toString());
                }
            }
            repaint();
            return Docs.facts("dispatched", "applied", Json.map("result", Creo.featureRow(solid.GetFeatureById(id))));
        };
    }

    private static void collect(Feature feature, Map<Integer, Feature> into, boolean children) throws jxthrowable {
        if (into.containsKey(feature.GetId())) {
            return;
        }
        into.put(feature.GetId(), feature);
        Features next = children ? feature.ListChildren() : feature.ListParents();
        for (int i = 0; next != null && i < next.getarraysize(); i++) {
            collect(next.get(i), into, children);
        }
    }

    // ------------------------------------------------------------------ geometry

    private List<Map<String, Object>> geometryList(Solid solid, String kind, String featureRef) throws Exception {
        if (kind != null && !Arrays.asList("surface", "edge", "axis", "datum-plane", "coordinate-system").contains(kind)) {
            throw new HostError(HostError.VALIDATION, "--kind is surface, edge, axis, datum-plane or coordinate-system, not " + kind + ".");
        }
        Integer only = featureRef == null ? null : Creo.feature(solid, featureRef).GetId();
        double f = Units.mmPerUnit((Model) solid);
        List<Map<String, Object>> items = new ArrayList<>();
        List<Surface> surfaces = surfaces(solid);
        if (kind == null || "surface".equals(kind)) {
            for (Surface s : surfaces) {
                if (owned(s.GetFeature(), only)) {
                    items.add(surface(s, "surface", "surface:" + s.GetId(), f));
                }
            }
        }
        if (kind == null || "datum-plane".equals(kind)) {
            Features planes = solid.ListFeaturesByType(Boolean.TRUE, FeatureType.FEATTYPE_DATUM_PLANE);
            for (int i = 0; planes != null && i < planes.getarraysize(); i++) {
                Feature plane = planes.get(i);
                ModelItems own = plane.ListSubItems(ModelItemType.ITEM_SURFACE);
                if (own != null && own.getarraysize() > 0 && owned(plane, only)) {
                    Map<String, Object> row = surface((Surface) own.get(0), "datum-plane", plane.GetName(), f);
                    row.put("name", plane.GetName());
                    items.add(row);
                }
            }
        }
        if (kind == null || "edge".equals(kind)) {
            Set<Integer> seen = new LinkedHashSet<>();
            for (Surface s : surfaces) {
                com.ptc.pfc.pfcGeometry.Contours loops = s.ListContours();
                for (int c = 0; loops != null && c < loops.getarraysize(); c++) {
                    com.ptc.pfc.pfcGeometry.Edges edges = loops.get(c).ListElements();
                    for (int k = 0; edges != null && k < edges.getarraysize(); k++) {
                        Edge e = edges.get(k);
                        if (seen.add(e.GetId()) && owned(e.GetFeature(), only)) {
                            items.add(Json.map("reference", "edge:" + e.GetId(), "kind", "edge",
                                    "shape", curveShape(e), "feature_id", featureId(e.GetFeature()),
                                    "name", null, "length_mm", clean(e.EvalLength() * f)));
                        }
                    }
                }
            }
        }
        if (kind == null || "axis".equals(kind)) {
            ModelItems axes = solid.ListItems(ModelItemType.ITEM_AXIS);
            for (int i = 0; axes != null && i < axes.getarraysize(); i++) {
                com.ptc.pfc.pfcGeometry.Axis a = (com.ptc.pfc.pfcGeometry.Axis) axes.get(i);
                if (owned(a.GetFeature(), only)) {
                    String name = a.GetName();
                    items.add(Json.map("reference", name == null || name.isEmpty() ? "axis:" + a.GetId() : name,
                            "kind", "axis", "shape", "line", "feature_id", featureId(a.GetFeature()), "name", name));
                }
            }
        }
        if (kind == null || "coordinate-system".equals(kind)) {
            ModelItems systems = solid.ListItems(ModelItemType.ITEM_COORD_SYS);
            for (int i = 0; systems != null && i < systems.getarraysize(); i++) {
                com.ptc.pfc.pfcGeometry.CoordSystem c = (com.ptc.pfc.pfcGeometry.CoordSystem) systems.get(i);
                if (owned(c.GetFeature(), only)) {
                    items.add(Json.map("reference", c.GetName(), "kind", "coordinate-system", "shape", null,
                            "feature_id", featureId(c.GetFeature()), "name", c.GetName(),
                            "origin_mm", point(c.GetCoordSys().GetOrigin(), f)));
                }
            }
        }
        return items;
    }

    private static Map<String, Object> surface(Surface s, String kind, String reference, double f) throws jxthrowable {
        Map<String, Object> row = Json.map("reference", reference, "kind", kind,
                "shape", Creo.shortName(s.GetSurfaceType(), "SURFACE_"), "feature_id", featureId(s.GetFeature()), "name", null);
        if (s instanceof TransformedSurface) {
            com.ptc.pfc.pfcBase.Transform3D frame = ((TransformedSurface) s).GetCoordSys();
            int type = s.GetSurfaceType().getValue();
            if (type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_PLANE) {
                row.put("normal", vector(frame.GetZAxis()));
                row.put("origin_mm", point(frame.GetOrigin(), f));
            } else if (type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_CYLINDER
                    && s instanceof com.ptc.pfc.pfcGeometry.Cylinder) {
                row.put("axis_direction", vector(frame.GetZAxis()));
                row.put("axis_origin_mm", point(frame.GetOrigin(), f));
                row.put("radius_mm", clean(((com.ptc.pfc.pfcGeometry.Cylinder) s).GetRadius() * f));
            }
        }
        return row;
    }

    /** Every face of the solid; a part of several bodies is read body by body. */
    private static List<Surface> surfaces(Solid solid) throws jxthrowable {
        List<Surface> out = new ArrayList<>();
        try {
            ModelItems all = solid.ListItems(ModelItemType.ITEM_SURFACE);
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                out.add((Surface) all.get(i));
            }
            return out;
        } catch (com.ptc.pfc.pfcExceptions.XToolkitMultibodyUnsupported severalBodies) {
            Set<Integer> seen = new LinkedHashSet<>();
            ModelItems bodies = solid.ListItems(ModelItemType.ITEM_BODY);
            for (int b = 0; bodies != null && b < bodies.getarraysize(); b++) {
                com.ptc.pfc.pfcGeometry.Surfaces own = ((com.ptc.pfc.pfcSolid.SolidBody) bodies.get(b)).ListSurfaces();
                for (int i = 0; own != null && i < own.getarraysize(); i++) {
                    if (seen.add(own.get(i).GetId())) {
                        out.add(own.get(i));
                    }
                }
            }
            return out;
        }
    }

    private static String curveShape(Edge e) {
        try {
            return Creo.shortName(e.GetCurveDescriptor().GetCurveType(), "CURVE_");
        } catch (Throwable unreadable) {
            return null;
        }
    }

    private static boolean owned(Feature feature, Integer only) throws jxthrowable {
        return only == null || (feature != null && feature.GetId() == only);
    }

    private static Integer featureId(Feature feature) throws jxthrowable {
        return feature == null ? null : feature.GetId();
    }

    /**
     * Creo's clearance for solid geometry; for datums, which it does not measure (it answers
     * about 1e9, measured on Creo 13.4), the distance between the datums' own planes, lines
     * and points (core.Distance).
     */
    private Map<String, Object> distance(Solid solid, String from, String to) throws Exception {
        double f = Units.mmPerUnit((Model) solid);
        ModelItem a = item(solid, from);
        ModelItem b = item(solid, to);
        double measured;
        try {
            measured = com.ptc.pfc.pfcInterference.pfcInterference.CreateSelectionEvaluator(
                    pfcSelect.SelectionPair_Create(pfcSelect.CreateModelItemSelection(a, null),
                            pfcSelect.CreateModelItemSelection(b, null))).ComputeClearance().GetDistance();
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, "Creo could not measure from " + from + " to " + to + ".")
                    .nativeMessage(refused.toString());
        }
        if (!(measured < NO_CLEARANCE)) {
            Distance.Shape first = shape(a);
            Distance.Shape second = shape(b);
            if (first == null || second == null) {
                throw new HostError(HostError.UNSUPPORTED, "Creo measures no distance from " + from + " to " + to
                        + ". Measure between faces, edges, datum planes, axes or coordinate systems.");
            }
            measured = Distance.between(first, second);
        }
        return Json.map("from", from, "to", to, "distance_mm", clean(measured * f));
    }

    /** What Creo's clearance answers where it measured nothing, in model units. */
    private static final double NO_CLEARANCE = 1e8;

    /** A datum as core.Distance takes it: a plane, an axis as a line, a coordinate system as its origin. */
    private static Distance.Shape shape(ModelItem item) throws jxthrowable {
        if (item instanceof TransformedSurface
                && ((Surface) item).GetSurfaceType().getValue() == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_PLANE) {
            com.ptc.pfc.pfcBase.Transform3D frame = ((TransformedSurface) item).GetCoordSys();
            return Distance.Shape.plane(xyz(frame.GetOrigin()), xyz(frame.GetZAxis()));
        }
        if (item instanceof com.ptc.wfc.wfcGeometry.WAxis) {
            com.ptc.pfc.pfcGeometry.CurveDescriptor data = ((com.ptc.wfc.wfcGeometry.WAxis) item).GetAxisData();
            if (data instanceof com.ptc.pfc.pfcGeometry.LineDescriptor) {
                double[] start = xyz(((com.ptc.pfc.pfcGeometry.LineDescriptor) data).GetEnd1());
                double[] end = xyz(((com.ptc.pfc.pfcGeometry.LineDescriptor) data).GetEnd2());
                return Distance.Shape.line(start, new double[] {end[0] - start[0], end[1] - start[1], end[2] - start[2]});
            }
        }
        if (item instanceof com.ptc.pfc.pfcGeometry.CoordSystem) {
            return Distance.Shape.point(xyz(((com.ptc.pfc.pfcGeometry.CoordSystem) item).GetCoordSys().GetOrigin()));
        }
        return null;
    }

    private static double[] xyz(com.ptc.pfc.pfcBase.Point3D p) throws jxthrowable {
        return new double[] {p.get(0), p.get(1), p.get(2)};
    }

    private static double[] xyz(com.ptc.pfc.pfcBase.Vector3D v) throws jxthrowable {
        return new double[] {v.get(0), v.get(1), v.get(2)};
    }

    /** surface:41, edge:57, axis:12, or the name of a datum plane, axis or coordinate system. */
    private static ModelItem item(Solid solid, String ref) throws jxthrowable {
        Matcher typed = Pattern.compile("^(surface|edge|axis):([0-9]+)$").matcher(ref.toLowerCase(Locale.ROOT));
        if (typed.matches()) {
            ModelItemType type = "surface".equals(typed.group(1)) ? ModelItemType.ITEM_SURFACE
                    : "edge".equals(typed.group(1)) ? ModelItemType.ITEM_EDGE : ModelItemType.ITEM_AXIS;
            ModelItem item;
            try {
                item = solid.GetItemById(type, Integer.parseInt(typed.group(2)));
            } catch (Throwable absent) {
                item = null;
            }
            if (item == null) {
                throw new HostError(HostError.NOT_FOUND, "There is no " + ref + " in " + Creo.fileName((Model) solid) + ".");
            }
            return item;
        }
        Features planes = solid.ListFeaturesByType(Boolean.FALSE, FeatureType.FEATTYPE_DATUM_PLANE);
        for (int i = 0; planes != null && i < planes.getarraysize(); i++) {
            if (ref.equalsIgnoreCase(String.valueOf(planes.get(i).GetName()))) {
                ModelItems own = planes.get(i).ListSubItems(ModelItemType.ITEM_SURFACE);
                if (own != null && own.getarraysize() > 0) {
                    return own.get(0);
                }
            }
        }
        for (ModelItemType type : new ModelItemType[] {ModelItemType.ITEM_AXIS, ModelItemType.ITEM_COORD_SYS}) {
            ModelItems named = solid.ListItems(type);
            for (int i = 0; named != null && i < named.getarraysize(); i++) {
                if (ref.equalsIgnoreCase(String.valueOf(named.get(i).GetName()))) {
                    return named.get(i);
                }
            }
        }
        throw new HostError(HostError.NOT_FOUND, "No geometry is called " + ref + " in " + Creo.fileName((Model) solid)
                + "; geometry list shows the references.");
    }

    // ------------------------------------------------------------------ dimensions

    private List<Map<String, Object>> dimensionList(Solid solid, String featureRef) throws Exception {
        double f = Units.mmPerUnit((Model) solid);
        List<Map<String, Object>> rows = new ArrayList<>();
        List<Feature> features = new ArrayList<>();
        if (featureRef != null) {
            features.add(Creo.feature(solid, featureRef));
        } else {
            Set<Integer> visible = Creo.visibleFeatureIds(solid);
            Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                if (visible.contains(all.get(i).GetId())) {
                    features.add(all.get(i));
                }
            }
        }
        for (Feature feature : features) {
            ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
            for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
                rows.add(dimensionRow((BaseDimension) dims.get(i), feature, f));
            }
        }
        return rows;
    }

    private static boolean angular(BaseDimension dim) throws jxthrowable {
        return dim.GetDimType() != null && dim.GetDimType().getValue() == DimensionType._DIM_ANGULAR;
    }

    private static Map<String, Object> dimensionRow(BaseDimension dim, Feature owner, double f) throws jxthrowable {
        int type = dim.GetDimType() == null ? -1 : dim.GetDimType().getValue();
        String kind = type == DimensionType._DIM_RADIAL ? "radius" : type == DimensionType._DIM_DIAMETER ? "diameter"
                : type == DimensionType._DIM_ANGULAR ? "angle" : "linear";
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", dim.GetSymbol());
        row.put("name", dim.GetSymbol());
        row.put("kind", kind);
        row.put("feature_id", owner == null ? null : owner.GetId());
        if ("angle".equals(kind)) {
            row.put("value_deg", clean(dim.GetDimValue()));
        } else {
            row.put("value_mm", clean(dim.GetDimValue() * f));
        }
        boolean driven = false;
        try {
            driven = dim.GetIsRelationDriven();
        } catch (Throwable unreadable) {
            driven = false;
        }
        row.put("driven_by_relation", driven);
        boolean reference = dim instanceof com.ptc.pfc.pfcDimension.Dimension && ((com.ptc.pfc.pfcDimension.Dimension) dim).IsReference();
        row.put("reference", reference);
        row.put("tolerance", reference ? null : tolerance(dim, "angle".equals(kind) ? 1.0 : f, "angle".equals(kind)));
        return row;
    }

    /**
     * A dimension's tolerance as a person reads it; deviations come back as Creo holds them,
     * +upper / -lower. An angular dimension's are in degrees ({@code _deg}) and not scaled.
     */
    private static Map<String, Object> tolerance(BaseDimension base, double f, boolean angle) {
        String u = angle ? "_deg" : "_mm";
        try {
            if (!(base instanceof com.ptc.pfc.pfcDimension.Dimension)) {
                return Json.map("type", "nominal");
            }
            com.ptc.pfc.pfcDimension.Dimension dim = (com.ptc.pfc.pfcDimension.Dimension) base;
            if (dim instanceof com.ptc.wfc.wfcDimension.WDimension && ((com.ptc.wfc.wfcDimension.WDimension) dim).IsBasic()) {
                return Json.map("type", "basic");
            }
            double value = dim.GetDimValue();
            String fit = fitOf(dim);
            double plus = 0;
            double minus = 0;
            DimToleranceLimits limits = dim.GetToleranceLimits();
            if (limits != null) {
                plus = limits.GetUpperLimit();
                minus = limits.GetLowerLimit();
            }
            DimToleranceType type = dim.GetToleranceType();
            int shown = type == null ? -1 : type.getValue();
            if (fit != null) {
                return Json.map("type", "fit", "fit", fit, "plus" + u, clean(plus * f), "minus" + u, clean(minus * f));
            }
            if (shown == -1) {
                return Json.map("type", "nominal");
            }
            if (shown == DimToleranceType._DIMTOL_PLUS_MINUS) {
                return Json.map("type", "plus_minus", "plus" + u, clean(plus * f), "minus" + u, clean(minus * f));
            }
            if (shown == DimToleranceType._DIMTOL_SYMMETRIC || shown == DimToleranceType._DIMTOL_SYMMETRIC_SUPERSCRIPT) {
                return Json.map("type", "symmetric", "plus" + u, clean(plus * f), "minus" + u, clean(plus * f));
            }
            if (shown == DimToleranceType._DIMTOL_LIMITS) {
                return Json.map("type", "limits", "upper" + u, clean((value + plus) * f), "lower" + u, clean((value - minus) * f));
            }
            return Json.map("type", Creo.shortName(type, "DIMTOL_"));
        } catch (Throwable unreadable) {
            return Json.map("type", null);
        }
    }

    /** "H7" when the dimension carries an ISO hole or shaft class; null otherwise, or in ANSI. */
    private static String fitOf(com.ptc.pfc.pfcDimension.Dimension dim) {
        try {
            com.ptc.pfc.pfcDimension.DimToleranceTable table = dim.GetToleranceTable();
            if (table == null) {
                return null;
            }
            int kind = table.GetTolTableType().getValue();
            if (kind != com.ptc.pfc.pfcDimension.ToleranceTableType._TOLTABLE_HOLES
                    && kind != com.ptc.pfc.pfcDimension.ToleranceTableType._TOLTABLE_SHAFTS) {
                return null;
            }
            return table.GetTableName() + table.GetTableColumn();
        } catch (Throwable ansi) {
            return null;
        }
    }

    private void dimensionUpdate(Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        Object[] found = Creo.dimension(solid, required(in, "id"));
        BaseDimension dim = (BaseDimension) found[0];
        Feature owner = (Feature) found[1];
        double f = Units.mmPerUnit(model);
        Double length = Json.number(in, "length_mm");
        Double angle = Json.number(in, "angle_deg");
        Double plus = Json.number(in, "plus_mm");
        Double minus = Json.number(in, "minus_mm");
        Double symmetric = Json.number(in, "symmetric_mm");
        Double upper = Json.number(in, "upper_mm");
        Double lower = Json.number(in, "lower_mm");
        String fit = Json.string(in, "fit", null);
        boolean basic = Boolean.TRUE.equals(Json.bool(in, "basic"));
        boolean nominal = Boolean.TRUE.equals(Json.bool(in, "nominal"));
        int kinds = (plus != null || minus != null ? 1 : 0) + (symmetric != null ? 1 : 0)
                + (upper != null || lower != null ? 1 : 0) + (fit != null ? 1 : 0) + (basic ? 1 : 0) + (nominal ? 1 : 0);
        if (length != null && angle != null) {
            throw new HostError(HostError.VALIDATION, "Give --length or --angle, not both.");
        }
        if (kinds > 1) {
            throw new HostError(HostError.VALIDATION, "Give one kind of tolerance: --plus with --minus, --symmetric, "
                    + "--upper with --lower, --fit, --basic or --nominal.");
        }
        if ((plus == null) != (minus == null) || (upper == null) != (lower == null)) {
            throw new HostError(HostError.VALIDATION, "--plus goes with --minus, and --upper with --lower.");
        }
        if (length == null && angle == null && kinds == 0) {
            throw new HostError(HostError.VALIDATION, "Give a new value (--length or --angle) or a tolerance.");
        }
        Map<String, Object> before = dimensionRow(dim, owner, f);
        String symbol = dim.GetSymbol();
        String key = docs.key(model) + "#/dimensions/" + symbol;
        plan.target(key, "dimension", symbol);
        boolean isAngle = angular(dim);
        if (Boolean.TRUE.equals(before.get("reference"))) {
            plan.block("Dimension " + symbol + " is a reference dimension: it reports geometry and cannot be changed",
                    "creo-relations-and-dimensions");
        }
        Double newValue = null;
        if (length != null || angle != null) {
            if (isAngle && length != null) {
                throw new HostError(HostError.VALIDATION, "Dimension " + symbol + " is an angle; give --angle.");
            }
            if (!isAngle && angle != null) {
                throw new HostError(HostError.VALIDATION, "Dimension " + symbol + " is a length; give --length.");
            }
            if (length != null && length < 0) {
                // Creo stores no negative length: it flips the feature to the other side and keeps
                // the positive value (measured on Creo 13.4 with an offset datum plane).
                throw new HostError(HostError.VALIDATION, "Creo stores no negative length: a negative value flips the feature to "
                        + "the other side of its reference; give a positive length.").with("knowledge", java.util.List.of("creo-relations-and-dimensions"));
            }
            if (Boolean.TRUE.equals(before.get("driven_by_relation"))) {
                plan.block("Dimension " + symbol + " is driven by " + drivenBy(model, symbol)
                        + ", which sets its value at every regeneration; change the relation instead", "creo-relations-and-dimensions");
            }
            if (isAngle) {
                newValue = angle;
                plan.change(key, "value_deg", before.get("value_deg"), clean(angle));
            } else {
                newValue = length / f;
                plan.change(key, "value_mm", before.get("value_mm"), clean(length));
            }
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> tolBefore = before.get("tolerance") instanceof Map ? (Map<String, Object>) before.get("tolerance") : Json.map();
        String tolType = null;
        if (kinds == 1) {
            if (isAngle && !basic && !nominal) {
                throw new HostError(HostError.UNSUPPORTED, "creo-cli 1.0 sets numeric tolerances on length dimensions only.");
            }
            if (!(dim instanceof com.ptc.pfc.pfcDimension.Dimension)) {
                throw new HostError(HostError.VALIDATION, "Dimension " + symbol + " takes no tolerance.");
            }
            tolType = plus != null ? "plus_minus" : symmetric != null ? "symmetric" : upper != null ? "limits"
                    : fit != null ? "fit" : basic ? "basic" : "nominal";
            plan.change(key, "tolerance_type", tolBefore.get("type"), tolType);
            if (plus != null) {
                plan.change(key, "plus_mm", tolBefore.get("plus_mm"), clean(plus));
                plan.change(key, "minus_mm", tolBefore.get("minus_mm"), clean(minus));
            } else if (symmetric != null) {
                plan.change(key, "plus_mm", tolBefore.get("plus_mm"), clean(symmetric));
                plan.change(key, "minus_mm", tolBefore.get("minus_mm"), clean(symmetric));
            } else if (upper != null) {
                plan.change(key, "upper_mm", tolBefore.get("upper_mm"), clean(upper));
                plan.change(key, "lower_mm", tolBefore.get("lower_mm"), clean(lower));
            } else if (fit != null) {
                checkFit(fit);
                plan.change(key, "fit", tolBefore.get("fit"), fit);
            }
        }
        plan.action = "Change dimension " + symbol + " of " + plan.docId
                + (newValue != null ? " to " + (isAngle ? clean(angle) + " deg" : clean(length) + " mm") : "")
                + (tolType != null ? (newValue != null ? " and" : "") + " set its tolerance (" + tolType + ")" : "")
                + ", then regenerate.";
        final Double value = newValue;
        final String type = tolType;
        plan.work = () -> {
            if (value != null) {
                setValue(solid, dim, value);
            }
            if (type != null) {
                setTolerance(solid, (com.ptc.pfc.pfcDimension.Dimension) dim, type, plus, minus, symmetric, upper, lower, fit, f);
            }
            repaint();
            return Docs.facts("dispatched", "applied", Json.map("result", dimensionRow(dim, owner, Units.mmPerUnit(model))));
        };
    }

    private static void checkFit(String fit) {
        Matcher m = Pattern.compile("^([A-Za-z]{1,2})([0-9]{1,2})$").matcher(fit);
        if (!m.matches() || !(m.group(1).equals(m.group(1).toUpperCase(Locale.ROOT))
                || m.group(1).equals(m.group(1).toLowerCase(Locale.ROOT)))) {
            throw new HostError(HostError.VALIDATION, "A fit is a hole class in capitals or a shaft class in small letters, "
                    + "and a grade: H7, g6, JS9.");
        }
    }

    /** Set one value and regenerate; Creo undoes a regeneration that fails, and the old value is put back. */
    private static void setValue(Solid solid, BaseDimension dim, double value) throws Exception {
        double old = dim.GetDimValue();
        try {
            dim.SetDimValue(value);
        } catch (jxthrowable refused) {
            // Creo took nothing: it refuses the value before any regeneration (0.01 mm for a
            // depth, measured on Creo 13.4).
            throw new HostError(HostError.VALIDATION, "Creo does not accept that value for dimension " + dim.GetSymbol()
                    + "; nothing changed.", "dispatched").nativeMessage(refused.toString());
        }
        WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
        regen.SetUndoIfFail(true);
        regen.SetNoResolveMode(true);
        String failure = null;
        try {
            ((WSolid) solid).WRegenerate(regen);
        } catch (jxthrowable refused) {
            failure = refused.toString();
        }
        if (failure == null && !failedFeatures(solid).isEmpty()) {
            failure = "features failed to regenerate: " + failedFeatures(solid);
        }
        if (failure != null) {
            try {
                if (dim.GetDimValue() != old) {
                    dim.SetDimValue(old);
                    WRegenInstructions back = wfcSolidInstructions.WRegenInstructions_Create();
                    back.SetNoResolveMode(true);
                    ((WSolid) solid).WRegenerate(back);
                }
            } catch (Throwable ignored) {
                throw new HostError(HostError.NATIVE, "The model did not regenerate with the new value, and putting the "
                        + "old value back failed too.", "unknown").nativeMessage(failure);
            }
            throw new HostError(HostError.NATIVE, "The model does not regenerate with that value; the old value is back.",
                    "dispatched").nativeMessage(failure);
        }
    }

    private static List<Integer> failedFeatures(Solid solid) throws jxthrowable {
        List<Integer> failed = new ArrayList<>();
        Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature feature = all.get(i);
            if (feature instanceof com.ptc.wfc.wfcFeature.WFeature) {
                com.ptc.wfc.wfcFeature.FeatureStatusFlag flag = ((com.ptc.wfc.wfcFeature.WFeature) feature).GetStatusFlag();
                if (flag != null && (flag.GetIsFailed() || flag.GetIsChildOfFailed())) {
                    failed.add(feature.GetId());
                }
            }
        }
        return failed;
    }

    private static void setTolerance(Solid solid, com.ptc.pfc.pfcDimension.Dimension dim, String type, Double plus,
                                     Double minus, Double symmetric, Double upper, Double lower, String fit, double f)
            throws Exception {
        try {
            if (!"fit".equals(type) && fitOf(dim) != null) {
                dim.SetToleranceTable(pfcDimension.DimToleranceTable_Create(
                        com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_GENERAL, "", 0));
            }
            if (dim instanceof com.ptc.wfc.wfcDimension.WDimension && ((com.ptc.wfc.wfcDimension.WDimension) dim).IsBasic()
                    && !"basic".equals(type)) {
                ((com.ptc.wfc.wfcDimension.WDimension) dim).SetAsBasic(false);
            }
            switch (type) {
                case "nominal":
                    dim.SetTolerance(null);
                    break;
                case "basic":
                    dim.SetTolerance(null);
                    if (!(dim instanceof com.ptc.wfc.wfcDimension.WDimension)) {
                        throw new HostError(HostError.UNSUPPORTED, "This dimension cannot be made basic.");
                    }
                    ((com.ptc.wfc.wfcDimension.WDimension) dim).SetAsBasic(true);
                    break;
                case "plus_minus":
                    dim.SetToleranceType(DimToleranceType.DIMTOL_PLUS_MINUS);
                    dim.SetToleranceLimits(pfcDimension.DimToleranceLimits_Create(plus / f, minus / f));
                    break;
                case "symmetric":
                    dim.SetToleranceType(DimToleranceType.DIMTOL_SYMMETRIC);
                    dim.SetToleranceLimits(pfcDimension.DimToleranceLimits_Create(symmetric / f, symmetric / f));
                    break;
                case "limits": {
                    double value = dim.GetDimValue();
                    dim.SetToleranceType(DimToleranceType.DIMTOL_LIMITS);
                    dim.SetToleranceLimits(pfcDimension.DimToleranceLimits_Create(upper / f - value, value - lower / f));
                    break;
                }
                case "fit": {
                    Matcher m = Pattern.compile("^([A-Za-z]{1,2})([0-9]{1,2})$").matcher(fit);
                    m.matches();
                    String name = m.group(1);
                    boolean hole = name.equals(name.toUpperCase(Locale.ROOT));
                    com.ptc.pfc.pfcDimension.DimTolerance iso = pfcDimension.DimTolISODIN_Create(
                            hole ? com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_HOLES
                                    : com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_SHAFTS,
                            name, Integer.parseInt(m.group(2)));
                    try {
                        dim.SetTolerance(iso);
                    } catch (com.ptc.pfc.pfcExceptions.XToolkitCantAccess notLoaded) {
                        ((WSolid) solid).LoadToleranceClass(name);
                        dim.SetTolerance(iso);
                    } catch (com.ptc.pfc.pfcExceptions.XToolkitBadContext wrongStandard) {
                        throw new HostError(HostError.VALIDATION, "ISO fits need a model in the ISO/DIN tolerance standard.",
                                "dispatched");
                    }
                    break;
                }
                default:
                    throw new HostError(HostError.VALIDATION, "Unknown tolerance kind " + type + ".");
            }
            solid.Regenerate(com.ptc.pfc.pfcSolid.pfcSolid.RegenInstructions_Create(false, false, null));
        } catch (HostError refused) {
            throw refused;
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, "Creo did not take the tolerance.", "dispatched").nativeMessage(refused.toString());
        }
    }

    // ------------------------------------------------------------------ parameters and relations

    private List<Map<String, Object>> parameterList(Model model) throws jxthrowable {
        List<Map<String, Object>> rows = new ArrayList<>();
        Parameters all = model.ListParams();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            rows.add(parameterRow(all.get(i)));
        }
        return rows;
    }

    private static Map<String, Object> parameterRow(Parameter p) throws jxthrowable {
        String unit = null;
        Double mm = null;
        try {
            com.ptc.pfc.pfcUnits.Unit own = p.GetUnits();
            unit = own == null ? null : own.GetName();
            mm = own == null ? null : Units.mmPer(own);
        } catch (Throwable none) {
            unit = null;
        }
        boolean driven = false;
        try {
            driven = p.GetIsRelationDriven();
        } catch (Throwable unreadable) {
            driven = false;
        }
        Object value = plain(p.GetValue());
        Map<String, Object> row = Json.map("id", p.GetName(), "name", p.GetName(), "type", type(p.GetValue()),
                "value", value, "unit", unit, "driven_by_relation", driven);
        if (mm != null && value instanceof Number) {
            // A length parameter also in millimetres, the unit creo-cli speaks (DCLI-081).
            row.put("value_mm", clean(((Number) value).doubleValue() * mm));
        }
        return row;
    }

    private static Parameter parameter(Model model, String name) throws jxthrowable {
        Parameter p = null;
        try {
            p = model.GetParam(name);
        } catch (Throwable absent) {
            p = null;
        }
        if (p == null) {
            throw new HostError(HostError.NOT_FOUND, "No parameter is named " + name + " in " + Creo.fileName(model)
                    + "; parameter list shows them.");
        }
        return p;
    }

    private static String type(ParamValue value) throws jxthrowable {
        if (value == null) {
            return null;
        }
        int d = value.Getdiscr().getValue();
        return d == ParamValueType._PARAM_STRING ? "string" : d == ParamValueType._PARAM_INTEGER ? "integer"
                : d == ParamValueType._PARAM_BOOLEAN ? "boolean" : d == ParamValueType._PARAM_DOUBLE ? "real"
                : d == ParamValueType._PARAM_NOTE ? "note" : Creo.shortName(value.Getdiscr(), "PARAM_");
    }

    private static Object plain(ParamValue value) throws jxthrowable {
        if (value == null) {
            return null;
        }
        int d = value.Getdiscr().getValue();
        return d == ParamValueType._PARAM_STRING ? value.GetStringValue()
                : d == ParamValueType._PARAM_INTEGER ? (Object) (long) value.GetIntValue()
                : d == ParamValueType._PARAM_BOOLEAN ? (Object) value.GetBoolValue()
                : d == ParamValueType._PARAM_DOUBLE ? (Object) value.GetDoubleValue()
                : d == ParamValueType._PARAM_NOTE ? (Object) (long) value.GetNoteId() : null;
    }

    private void parameterUpdate(Plan plan, Model model, Map<String, Object> in) throws Exception {
        Parameter p = parameter(model, required(in, "id"));
        String text = Json.string(in, "value", null);
        if (text == null) {
            throw new HostError(HostError.VALIDATION, "--value is required.");
        }
        Map<String, Object> before = parameterRow(p);
        String type = (String) before.get("type");
        Object after;
        ParamValue value;
        switch (type == null ? "" : type) {
            case "string":
                if (text.indexOf('\n') >= 0 || text.indexOf('\r') >= 0) {
                    throw new HostError(HostError.VALIDATION, "A string parameter holds one line; Creo refuses a line break.");
                }
                if (text.codePoints().anyMatch(c -> c > 0xFFFF)) {
                    // Measured on Creo 13.4: such a value is stored as an empty string.
                    throw new HostError(HostError.VALIDATION, "Creo cannot store characters such as emoji in a parameter "
                            + "(it would store an empty value); leave them out.");
                }
                if (text.length() > 79) {
                    throw new HostError(HostError.VALIDATION, "A string parameter holds at most 79 characters.");
                }
                after = text;
                value = pfcModelItem.CreateStringParamValue(text);
                break;
            case "integer":
                if (!text.trim().matches("[-+]?[0-9]{1,9}")) {
                    throw new HostError(HostError.VALIDATION, "Parameter " + before.get("name") + " is an integer; " + text + " is not one.");
                }
                after = Long.parseLong(text.trim().replace("+", ""));
                value = pfcModelItem.CreateIntParamValue(Integer.parseInt(text.trim().replace("+", "")));
                break;
            case "boolean":
                if (!text.trim().equalsIgnoreCase("true") && !text.trim().equalsIgnoreCase("false")) {
                    throw new HostError(HostError.VALIDATION, "Parameter " + before.get("name") + " is a boolean: give true or false.");
                }
                after = Boolean.parseBoolean(text.trim().toLowerCase(Locale.ROOT));
                value = pfcModelItem.CreateBoolParamValue((Boolean) after);
                break;
            case "real": {
                double number = realValue(p, text, (String) before.get("unit"));
                after = number;
                value = pfcModelItem.CreateDoubleParamValue(number);
                break;
            }
            default:
                throw new HostError(HostError.UNSUPPORTED, "Parameter " + before.get("name") + " is of type " + type
                        + ", which creo-cli does not change.");
        }
        String name = p.GetName();
        String key = docs.key(model) + "#/parameters/" + name;
        plan.target(key, "parameter", name);
        if (Boolean.TRUE.equals(before.get("driven_by_relation"))) {
            plan.block("Parameter " + name + " is driven by " + drivenBy(model, name)
                    + ", which sets it at every regeneration; change the relation instead", "creo-relations-and-dimensions");
        }
        plan.change(key, "value", before.get("value"), after);
        plan.action = "Set parameter " + name + " of " + plan.docId + " to " + after + ".";
        plan.work = () -> {
            try {
                p.SetValue(value);
            } catch (jxthrowable refused) {
                throw new HostError(HostError.NATIVE, "Creo did not take the value.").nativeMessage(refused.toString());
            }
            return Docs.facts("dispatched", "applied", Json.map("result", parameterRow(p)));
        };
    }

    /**
     * A real value. A parameter with a length unit takes the value with a unit (12.5mm, 0.5in),
     * converted to the parameter's unit; one without a unit takes a plain number.
     */
    private static double realValue(Parameter p, String text, String unitName) throws jxthrowable {
        Matcher withUnit = WITH_UNIT.matcher(text);
        if (unitName == null || unitName.isEmpty()) {
            try {
                return Double.parseDouble(text.trim());
            } catch (NumberFormatException bad) {
                throw new HostError(HostError.VALIDATION, "Parameter " + p.GetName() + " is a number without a unit; "
                        + text + " is not a number.").with("knowledge", java.util.List.of("creo-units"));
            }
        }
        if (!withUnit.matches()) {
            throw new HostError(HostError.VALIDATION, "Parameter " + p.GetName() + " has the unit " + unitName
                    + ": give the value with a unit, such as 12.5mm.").with("knowledge", java.util.List.of("creo-units"));
        }
        double number = Double.parseDouble(withUnit.group(1));
        String given = withUnit.group(2);
        if (given.equalsIgnoreCase(unitName)) {
            return number;
        }
        Double from = Units.mmPer(given);
        Double to = Units.mmPer(p.GetUnits());
        if (from == null || to == null) {
            throw new HostError(HostError.VALIDATION, "Parameter " + p.GetName() + " is in " + unitName
                    + "; give the value in " + unitName + ".").with("knowledge", java.util.List.of("creo-units"));
        }
        return number * from / to;
    }

    /** "the relation NAME = ..." when a relation of the model sets this name, else "a relation". */
    private static String drivenBy(Model model, String name) {
        try {
            stringseq all = ((RelationOwner) model).GetRelations();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                String line = all.get(i);
                int equals = line == null ? -1 : line.indexOf('=');
                if (equals > 0 && line.substring(0, equals).trim().equalsIgnoreCase(name)) {
                    return "the relation " + line.trim();
                }
            }
        } catch (Throwable unreadable) {
            // Fall back to the general words.
        }
        return "a relation";
    }

    /** The relations, one item per line in Creo's order, numbered from 1 as Tools > Relations shows them. */
    private List<Map<String, Object>> relations(Model model) throws jxthrowable {
        List<Map<String, Object>> out = new ArrayList<>();
        stringseq all = ((RelationOwner) model).GetRelations();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            out.add(Json.map("number", i + 1, "text", all.get(i)));
        }
        return out;
    }

    // ------------------------------------------------------------------ materials and components

    private List<Map<String, Object>> materials(Model model, String query) throws Exception {
        String assigned = null;
        List<Map<String, Object>> rows = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        if (model instanceof Part) {
            Part part = (Part) model;
            try {
                Material current = part.GetCurrentMaterial();
                assigned = current == null ? null : current.GetName();
            } catch (Throwable none) {
                assigned = null;
            }
            Materials own = part.ListMaterials();
            for (int i = 0; own != null && i < own.getarraysize(); i++) {
                String name = own.get(i).GetName();
                if (seen.add(name.toLowerCase(Locale.ROOT)) && matches(name, query)) {
                    rows.add(Json.map("name", name, "source", "model", "assigned", name.equalsIgnoreCase(assigned)));
                }
            }
        }
        File library = library(Creo.session());
        List<File> files = new ArrayList<>();
        walk(library, files, 0);
        files.sort(Comparator.comparing(file -> file.getName().toLowerCase(Locale.ROOT)));
        for (File file : files) {
            String name = file.getName().substring(0, file.getName().length() - 4);
            if (seen.add(name.toLowerCase(Locale.ROOT)) && matches(name, query)) {
                rows.add(Json.map("name", name, "source", "library", "assigned", name.equalsIgnoreCase(assigned)));
            }
        }
        return rows;
    }

    private static boolean matches(String name, String query) {
        return query == null || name.toLowerCase(Locale.ROOT).contains(query.toLowerCase(Locale.ROOT));
    }

    private static File library(Session session) throws jxthrowable {
        String configured = session.GetConfigOption("pro_material_dir");
        if (configured != null && !configured.trim().isEmpty() && new File(configured.trim()).isDirectory()) {
            return new File(configured.trim());
        }
        return new File(new File(commonFiles(), "text"), "materials-library");
    }

    /** Creo's Common Files directory, from where otk.jar was loaded. */
    static File commonFiles() {
        String env = System.getenv("PRO_DIRECTORY");
        if (env != null && new File(env, "text").isDirectory()) {
            return new File(env);
        }
        try {
            java.net.URL jar = com.ptc.pfc.pfcGlobal.pfcGlobal.class.getProtectionDomain().getCodeSource().getLocation();
            return new File(jar.toURI()).getParentFile().getParentFile().getParentFile();
        } catch (Exception unknown) {
            throw new HostError(HostError.UNSUPPORTED, "The Creo installation cannot be found from inside the session.");
        }
    }

    private static void walk(File dir, List<File> out, int depth) {
        File[] children = dir.listFiles();
        if (children == null || depth > 6) {
            return;
        }
        for (File child : children) {
            if (child.isDirectory()) {
                walk(child, out, depth + 1);
            } else if (child.getName().toLowerCase(Locale.ROOT).endsWith(".mtl")) {
                out.add(child);
            }
        }
    }

    private List<Map<String, Object>> components(Model model) throws Exception {
        if (!(model instanceof Assembly)) {
            throw new HostError(HostError.VALIDATION, Creo.fileName(model) + " is a " + Creo.kind(model)
                    + "; component list works on assemblies.");
        }
        double f = Units.mmPerUnit(model);
        List<Map<String, Object>> rows = new ArrayList<>();
        Features found = ((Solid) model).ListFeaturesByType(Boolean.TRUE, FeatureType.FEATTYPE_COMPONENT);
        for (int i = 0; found != null && i < found.getarraysize(); i++) {
            ComponentFeat c = (ComponentFeat) found.get(i);
            String placed = null;
            String kind = null;
            try {
                placed = c.GetModelDescr().GetFileName().replaceFirst("<[^>]*>", "").toLowerCase(Locale.ROOT);
                kind = c.GetModelDescr().GetType().getValue() == ModelType._MDL_ASSEMBLY ? "assembly" : "part";
            } catch (Throwable unreadable) {
                placed = null;
            }
            List<Object> origin = null;
            try {
                origin = point(c.GetPosition().GetOrigin(), f);
            } catch (Throwable unplaced) {
                origin = null;
            }
            rows.add(Json.map("id", c.GetId(), "model", placed, "kind", kind,
                    "status", Creo.shortName(c.GetStatus(), "FEAT_"), "origin_mm", origin));
        }
        return rows;
    }

    // ------------------------------------------------------------------ export and render

    private void export(Plan plan, Model model, Map<String, Object> in) throws Exception {
        File out = new File(required(in, "output")).getAbsoluteFile();
        String ext = extension(out);
        boolean drawing = model.GetType().getValue() == ModelType._MDL_DRAWING;
        String format;
        switch (ext) {
            case "stp":
            case "step":
                format = "step";
                break;
            case "igs":
            case "iges":
                format = "iges";
                break;
            case "stl":
                format = "stl";
                break;
            case "pdf":
                format = "pdf";
                break;
            default:
                throw new HostError(HostError.VALIDATION, "The output's extension picks the format: .stp, .step, .igs, "
                        + ".iges, .stl or .pdf; " + out.getName() + " has none of them.");
        }
        if (drawing != "pdf".equals(format)) {
            throw new HostError(HostError.VALIDATION, drawing ? Creo.fileName(model) + " is a drawing: export it to .pdf."
                    : "PDF is for drawings; export a part or assembly to .stp, .igs or .stl.");
        }
        if (out.getParentFile() == null || !out.getParentFile().isDirectory()) {
            throw new HostError(HostError.VALIDATION, "The folder " + out.getParent() + " does not exist.");
        }
        String key = Docs.fileKey(out.getPath());
        plan.records = false;
        plan.target(key, "file", out.getPath());
        plan.change(key, "exists", out.exists(), true);
        plan.action = "Export " + plan.docId + " to " + format.toUpperCase(Locale.ROOT) + " at " + out.getPath() + ".";
        plan.work = () -> {
            Path temp = Files.createTempDirectory("creo-cli-export");
            try {
                File target = new File(temp.toFile(), "export." + ext);
                try {
                    switch (format) {
                        case "step":
                            model.ExportIntf3D(target.getPath(), com.ptc.pfc.pfcModel.ExportType.EXPORT_STEP, null);
                            break;
                        case "iges": {
                            com.ptc.pfc.pfcExport.GeometryFlags flags = com.ptc.pfc.pfcExport.pfcExport.GeometryFlags_Create();
                            flags.SetAsSolids(true);
                            model.Export(target.getPath(), com.ptc.pfc.pfcExport.pfcExport.IGES3DNewExportInstructions_Create(
                                    com.ptc.pfc.pfcExport.AssemblyConfiguration.EXPORT_ASM_SINGLE_FILE, flags));
                            break;
                        }
                        case "stl":
                            model.Export(target.getPath(), com.ptc.pfc.pfcModel.pfcModel.STLBinaryExportInstructions_Create(null));
                            break;
                        default:
                            model.Export(target.getPath(), com.ptc.pfc.pfcExport.pfcExport.PDFExportInstructions_Create());
                    }
                } catch (jxthrowable refused) {
                    throw new HostError(HostError.NATIVE, "Creo did not export " + plan.docId + ".").nativeMessage(refused.toString());
                }
                File produced = produced(temp.toFile(), ext);
                if (produced == null) {
                    throw new HostError(HostError.NATIVE, "Creo reported the export done but wrote no ." + ext + " file.", "dispatched");
                }
                return moved(produced, out, Json.map("path", out.getPath(), "format", format));
            } finally {
                deleteTree(temp.toFile());
            }
        };
    }

    private void render(Plan plan, Model model, Map<String, Object> in) throws Exception {
        if (!(model instanceof Solid)) {
            throw new HostError(HostError.VALIDATION, Creo.fileName(model) + " is a drawing; render shows parts and assemblies.");
        }
        File out = new File(required(in, "output")).getAbsoluteFile();
        String ext = extension(out);
        if (!"jpg".equals(ext) && !"jpeg".equals(ext)) {
            throw new HostError(HostError.VALIDATION, "render writes JPEG: give an output ending in .jpg.");
        }
        if (out.getParentFile() == null || !out.getParentFile().isDirectory()) {
            throw new HostError(HostError.VALIDATION, "The folder " + out.getParent() + " does not exist.");
        }
        Long w = Json.integer(in, "width");
        Long h = Json.integer(in, "height");
        int width = w == null ? 1024 : w.intValue();
        int height = h == null ? 768 : h.intValue();
        if (width < 1 || width > 4096 || height < 1 || height > 4096) {
            throw new HostError(HostError.VALIDATION, "--width and --height are 1 to 4096 pixels.");
        }
        Session session = Creo.session();
        Window window = null;
        try {
            window = session.GetModelWindow(model);
        } catch (Throwable none) {
            window = null;
        }
        String key = Docs.fileKey(out.getPath());
        plan.records = false;
        plan.target(key, "file", out.getPath());
        plan.change(key, "exists", out.exists(), true);
        if (window == null) {
            plan.block(plan.docId + " has no window in Creo (it is open only as part of an assembly or drawing); render "
                    + "takes a picture of its window: open it with doc open first", "creo-display-requirements");
        }
        plan.action = "Write a " + width + " x " + height + " JPEG of " + plan.docId + "'s window to " + out.getPath() + ".";
        final Window target = window;
        plan.work = () -> {
            Path temp = Files.createTempDirectory("creo-cli-render");
            try {
                File file = new File(temp.toFile(), "render." + ext);
                com.ptc.pfc.pfcWindow.JPEGImageExportInstructions jpeg =
                        com.ptc.pfc.pfcWindow.pfcWindow.JPEGImageExportInstructions_Create(width / DPI, height / DPI);
                jpeg.SetDotsPerInch(com.ptc.pfc.pfcWindow.DotsPerInch.RASTERDPI_100);
                jpeg.SetImageDepth(com.ptc.pfc.pfcWindow.RasterDepth.RASTERDEPTH_24);
                try {
                    target.ExportRasterImage(file.getPath(), jpeg);
                } catch (jxthrowable refused) {
                    throw new HostError(HostError.NATIVE, "Creo did not write the image.").nativeMessage(refused.toString());
                }
                File produced = file.isFile() ? file : produced(temp.toFile(), ext);
                if (produced == null) {
                    throw new HostError(HostError.NATIVE, "Creo reported the image done but wrote no file.", "dispatched");
                }
                return moved(produced, out, Json.map("path", out.getPath(), "width", width, "height", height));
            } finally {
                deleteTree(temp.toFile());
            }
        };
    }

    private static String extension(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    /** The file Creo wrote in a private folder; Creo may choose its own name and adds __out.log beside it. */
    private static File produced(File dir, String ext) {
        File[] files = dir.listFiles();
        for (int i = 0; files != null && i < files.length; i++) {
            String name = files[i].getName().toLowerCase(Locale.ROOT);
            if (files[i].isFile() && (name.endsWith("." + ext) || name.matches(".*\\." + ext + "\\.[0-9]+"))) {
                return files[i];
            }
        }
        return null;
    }

    private static Map<String, Object> moved(File produced, File out, Map<String, Object> result) throws Exception {
        try {
            Files.move(produced.toPath(), out.toPath(), StandardCopyOption.REPLACE_EXISTING);
        } catch (Exception failed) {
            throw new HostError(HostError.NATIVE, "The file could not be written to " + out.getPath() + ": " + failed.getMessage(),
                    "dispatched");
        }
        result.put("bytes", out.length());
        // A write that creates files reports change not_applicable and persistence saved (DCLI-058).
        Map<String, Object> facts = Docs.facts("dispatched", "not_applicable", Json.map("result", result));
        facts.put("persistence", "saved");
        List<Object> files = new ArrayList<>();
        files.add(Json.map("path", out.getPath(), "bytes", out.length(), "sha256", Docs.sha256(out)));
        facts.put("files", files);
        return facts;
    }

    private static void deleteTree(File dir) {
        File[] files = dir.listFiles();
        for (int i = 0; files != null && i < files.length; i++) {
            if (files[i].isDirectory()) {
                deleteTree(files[i]);
            } else if (!files[i].delete()) {
                files[i].deleteOnExit();
            }
        }
        if (!dir.delete()) {
            dir.deleteOnExit();
        }
    }

    // ------------------------------------------------------------------ numbers

    /** A value without the floating noise Creo's solver leaves: 10.000000000000002 is 10. */
    static double clean(double value) {
        return Math.abs(value) < 1e9 ? Math.round(value * 1e9) / 1e9 : value;
    }

    private static List<Object> point(Point3D p, double f) throws jxthrowable {
        return Arrays.asList(clean(p.get(0) * f), clean(p.get(1) * f), clean(p.get(2) * f));
    }

    private static List<Object> vector(Vector3D v) throws jxthrowable {
        return Arrays.asList(clean(v.get(0)), clean(v.get(1)), clean(v.get(2)));
    }

    private static void repaint() {
        try {
            Window window = Creo.session().GetCurrentWindow();
            if (window != null) {
                window.Repaint();
            }
        } catch (Throwable ignored) {
            // Cosmetic; the model is already correct.
        }
    }
}
