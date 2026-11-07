package com.fateforge.creocli.host;

import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.fateforge.creocli.host.core.Sketch;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcArgument.ArgValue;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.UVOutline;
import com.ptc.pfc.pfcBase.UVParams;
import com.ptc.pfc.pfcBase.Vector3D;
import com.ptc.pfc.pfcDimension.Dimension;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.FeatureStatus;
import com.ptc.pfc.pfcGeometry.Contour;
import com.ptc.pfc.pfcGeometry.ContourTraversal;
import com.ptc.pfc.pfcGeometry.Contours;
import com.ptc.pfc.pfcGeometry.Edge;
import com.ptc.pfc.pfcGeometry.Edges;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.SurfXYZData;
import com.ptc.pfc.pfcGeometry.SurfaceType;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcSolid.SolidBody;
import com.ptc.wfc.wfcCollection.CurveCollectionInstrType;
import com.ptc.wfc.wfcCollection.CurveCollectionInstructions;
import com.ptc.wfc.wfcCollection.SurfaceCollectionInstrType;
import com.ptc.wfc.wfcCollection.SurfaceCollectionInstructions;
import com.ptc.wfc.wfcCollection.SurfaceCollectionRefType;
import com.ptc.wfc.wfcCollection.SurfaceCollectionReferences;
import com.ptc.wfc.wfcCollection.SurfaceCollectionRules;
import com.ptc.wfc.wfcCollection.wfcCollection;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElementTree.wfcElementTree;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.PatternType;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOptions;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The commands that create features: one feature per call, built from an element tree,
 * regenerated at once, and taken out again when Creo does not regenerate it. A feature is
 * named by the Agent, which is how the read-back finds it.
 */
final class Modeling {
    private static final Pattern NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_]{0,30}");
    /** "BASE/end", "BASE/side[+x]": a feature's faces by their place in it, with a normal filter. */
    private static final Pattern ROLE = Pattern.compile("([A-Za-z][A-Za-z0-9_]{0,30})/(start|end|side)(?:\\[([+-][xyz])\\])?");
    private static final Pattern SURFACE_ID = Pattern.compile("surface:([0-9]+)");
    private static final double EPS = 1e-6;
    private static final List<String> KNOWLEDGE = Arrays.asList("creo-sketches");

    // ProElemId.h and the feature headers of Creo TOOLKIT 13.4.
    private static final int PRO_E_FEATURE_TREE = 386, PRO_E_FEATURE_TYPE = 387, PRO_E_FEATURE_FORM = 388,
            PRO_E_STD_FEATURE_NAME = 1964, PRO_E_EXT_SURF_CUT_SOLID_TYPE = 1956, PRO_E_REMOVE_MATERIAL = 2023,
            PRO_E_FEAT_FORM_IS_THIN = 3176, PRO_E_STD_SECTION = 447, PRO_E_STD_SEC_SETUP_PLANE = 450,
            PRO_E_STD_SEC_PLANE = 451, PRO_E_STD_SEC_PLANE_VIEW_DIR = 452, PRO_E_STD_SEC_PLANE_ORIENT_DIR = 454,
            PRO_E_STD_SEC_PLANE_ORIENT_REF = 455, PRO_E_STD_DIRECTION = 436, PRO_E_STD_MATRLSIDE = 499,
            PRO_E_STD_EXT_DEPTH = 515, PRO_E_EXT_DEPTH_TO = 429, PRO_E_EXT_DEPTH_TO_TYPE = 433,
            PRO_E_EXT_DEPTH_TO_VALUE = 434, PRO_E_EXT_DEPTH_TO_REF = 435, PRO_E_BODY = 6314, PRO_E_BODY_USE = 6315,
            PRO_E_BODY_SELECT = 6316, PRO_E_SHELL_SRF = 73, PRO_E_SHELL_THICK = 74, PRO_E_SHELL_FLIP = 2194,
            PRO_E_RNDCH_SETS = 2101, PRO_E_RNDCH_SET = 2102, PRO_E_RNDCH_SHAPE_OPTIONS = 2178, PRO_E_RNDCH_COMPOUND_CONIC = 2177,
            PRO_E_RNDCH_CONIC_TYPE = 2119, PRO_E_RNDCH_REFERENCES = 2121, PRO_E_RNDCH_REFERENCE_TYPE = 2179,
            PRO_E_STD_CURVE_COLLECTION_APPL = 2124, PRO_E_RNDCH_RADII = 2123, PRO_E_RNDCH_RADIUS = 2122, PRO_E_RNDCH_LEG1 = 2106,
            PRO_E_RNDCH_LEG_TYPE = 2108, PRO_E_RNDCH_LEG_VALUE = 2109, PRO_E_RNDCH_ATTACH_TYPE = 3042;
    private static final int PRO_FEAT_PROTRUSION = 917, PRO_FEAT_CUT = 916, PRO_EXTRUDE = 1, PRO_EXT_FEAT_TYPE_SOLID = 917,
            PRO_EXT_MATERIAL_ADD = -1, PRO_EXT_MATERIAL_REMOVE = 916, PRO_EXT_FEAT_FORM_NO_THIN = 0,
            PRO_SEC_VIEW_DIR_SIDE_ONE = 1, PRO_SEC_ORIENT_DIR_LEFT = 3, PRO_SEC_ORIENT_DIR_RIGHT = 4,
            PRO_EXT_CR_IN_SIDE_ONE = -1, PRO_EXT_CR_IN_SIDE_TWO = 1, PRO_EXT_MATERIAL_SIDE_ONE = 1,
            PRO_BODY_USE_NEW = 0, PRO_BODY_USE_SELECTED = 2, PRO_EXT_DEPTH_TO_BLIND = 1 << 18,
            PRO_EXT_DEPTH_TO_ALL = 1 << 20, PRO_EXT_DEPTH_TO_REF = 1 << 22, PRO_EXT_DEPTH_SYMMETRIC = 1 << 28,
            PRO_FEAT_SHELL = 928, PRO_SHELL_INSIDE = 1, PRO_FEAT_ROUND = 913, PRO_ROUND_TYPE_CONSTANT = 0,
            PRO_ROUND_CONIC_DISABLE = 2, PRO_ROUND_REF_EDGE = 1, PRO_ROUND_RADIUS_TYPE_VALUE = 1, PRO_ROUND_ATTACHED = 0;
    private static final int PRO_E_PATTERN_ROOT = 604, PRO_E_GENPAT_TYPE = 3124, PRO_E_GENPAT_REGEN_METHOD = 3131,
            PRO_E_GENPAT_DIR = 3129, PRO_E_DIR_PAT_DIR1_OPT = 4026, PRO_E_GENPAT_DIR1 = 3291, PRO_E_DIRECTION_COMPOUND = 3252,
            PRO_E_DIRECTION_REFERENCE = 3253, PRO_E_DIRECTION_FLIP = 3254, PRO_E_DIR_PAT_DIR1_FLIP = 3307,
            PRO_E_GENPAT_DIR1_INC = 3274, PRO_E_GENPAT_DIM_FIRST_DIR_NUM_INST = 3134, PRO_E_GENPAT_DIM_SECOND_DIR_NUM_INST = 3136,
            PRO_GENPAT_DIR_DRIVEN = 5, PRO_PAT_GENERAL = 4, PRO_GENPAT_TRANSLATIONAL = -1;
    private static final int PRO_E_DTMPLN_CONSTRAINTS = 410, PRO_E_DTMPLN_CONSTRAINT = 411, PRO_E_DTMPLN_CONSTR_TYPE = 412,
            PRO_E_DTMPLN_CONSTR_REF = 413, PRO_E_DTMPLN_CONSTR_REF_OFFSET = 414, PRO_E_DTMPLN_CONSTR_REF_ANGLE = 415,
            PRO_FEAT_DATUM = 923, PRO_DTMPLN_THRU = 0, PRO_DTMPLN_OFFS = 3, PRO_DTMPLN_ANG = 4,
            PRO_E_DTMAXIS_CONSTRAINTS = 2015, PRO_E_DTMAXIS_CONSTRAINT = 2016, PRO_E_DTMAXIS_CONSTR_TYPE = 2017,
            PRO_E_DTMAXIS_CONSTR_REF = 2018, PRO_FEAT_DATUM_AXIS = 926, PRO_DTMAXIS_CONSTR_TYPE_THRU = 1;
    private static final int PRO_FEAT_CHAMFER = 914, PRO_E_RNDCH_DIMENSIONAL_SCHEMA = 2103, PRO_E_RNDCH_CHAMFER_SHAPE = 3184,
            PRO_CHM_D_X_D = 602, PRO_CHM_TANGENT_LEGS = 0;
    private static final int PRO_FEAT_DRAFT = 927, PRO_E_DRAFT_SPLIT = 2154, PRO_E_STD_SURF_COLLECTION_APPL = 2213,
            PRO_E_DRAFT_CONSTANT_OR_VARIABLE = 2150, PRO_E_DRAFT_INCLUDE_TANGENT = 3177, PRO_E_DRAFT_SIDE_1 = 2164,
            PRO_E_DRAFT_NEUTRAL_OBJECT_TYPE_1 = 2167, PRO_E_DRAFT_NEUTRAL_PLANE_1 = 2169, PRO_E_DRAFT_DEPENDENT_1 = 2171,
            PRO_E_DRAFT_ANGLE_1 = 2168, PRO_DRAFT_UI_SPLIT_NONE = 0, PRO_DRAFT_UI_CONSTANT = 1, PRO_DRAFT_UI_INC_TANG = 1,
            PRO_DRAFT_UI_PLANE = 1, PRO_DRAFT_UI_INDEPENDENT = 0;

    private final Docs docs;

    Modeling(Docs docs) {
        this.docs = docs;
    }

    // ------------------------------------------------------------------ extrude create

    void extrudeCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        Sketch sketch = Sketch.read(in.get("sketch"), planes(solid), f);
        for (String problem : sketch.problems) {
            plan.block(problem, "creo-sketches");
        }
        boolean remove = Boolean.TRUE.equals(Json.bool(in, "remove"));
        boolean throughAll = Boolean.TRUE.equals(Json.bool(in, "through_all"));
        boolean symmetric = Boolean.TRUE.equals(Json.bool(in, "symmetric"));
        Double depth = Json.number(in, "depth_mm");
        String to = Json.string(in, "to", null);
        int ways = (depth != null ? 1 : 0) + (throughAll ? 1 : 0) + (to != null ? 1 : 0);
        if (ways != 1) {
            throw new HostError(HostError.VALIDATION, "Give one depth: --depth, --through-all or --to.");
        }
        if (depth != null && depth <= 0) {
            throw new HostError(HostError.VALIDATION, "--depth must be greater than 0; --direction says which side.");
        }
        if (symmetric && depth == null) {
            throw new HostError(HostError.VALIDATION, "--symmetric splits --depth to both sides of the sketch; give --depth.");
        }
        String depthName = dimensionName(in, "depth_name");
        if (depthName != null && depth == null) {
            throw new HostError(HostError.VALIDATION, "--depth-name names the --depth dimension; give --depth.");
        }
        String directionText = Json.string(in, "direction", null);
        double[] direction = directionText == null ? sketch.normal : Sketch.axis(directionText);
        if (direction == null || Math.abs(Math.abs(Sketch.dot(direction, sketch.normal)) - 1) > EPS) {
            throw new HostError(HostError.VALIDATION, "--direction must be a model axis across the sketch plane, such as "
                    + axisName(sketch.normal) + " or " + axisName(new double[] {-sketch.normal[0], -sketch.normal[1], -sketch.normal[2]}) + ".");
        }
        boolean sideOne = Sketch.dot(direction, sketch.normal) > 0;
        Sketch.Plane toPlane = to == null ? null : planes(solid).find(to);
        Sketch.Plane orient = orientation(solid, sketch);
        if (orient == null) {
            plan.block("No datum plane of the model faces along x_axis " + sketch.xAxis + "; Creo orients a sketch by one.", "creo-sketches");
        }
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        for (Map.Entry<String, Double> d : sketch.namedValues.entrySet()) {
            plan.change(docKey + "#/dimensions/" + d.getKey(), "value_mm", null, Ops.clean(d.getValue()));
        }
        if (depthName != null) {
            plan.change(docKey + "#/dimensions/" + depthName, "value_mm", null, Ops.clean(depth));
        }
        String how = throughAll ? "through all" : to != null ? "up to " + to : (symmetric ? Ops.clean(depth) + " mm split to both sides"
                : Ops.clean(depth) + " mm toward " + axisName(direction));
        plan.action = "Extrude a sketch on " + sketch.plane.name + " into the feature " + name + ", "
                + (remove ? "removing" : "adding") + " material, " + how + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            WSolid wsolid = (WSolid) solid;
            Elements elements = Elements.create();
            add(elements, PRO_E_FEATURE_TREE, null, 0);
            add(elements, PRO_E_FEATURE_TYPE, integer(remove ? PRO_FEAT_CUT : PRO_FEAT_PROTRUSION), 1);
            add(elements, PRO_E_FEATURE_FORM, integer(PRO_EXTRUDE), 1);
            add(elements, PRO_E_EXT_SURF_CUT_SOLID_TYPE, integer(PRO_EXT_FEAT_TYPE_SOLID), 1);
            add(elements, PRO_E_REMOVE_MATERIAL, integer(remove ? PRO_EXT_MATERIAL_REMOVE : PRO_EXT_MATERIAL_ADD), 1);
            if (remove) {
                add(elements, PRO_E_STD_MATRLSIDE, integer(PRO_EXT_MATERIAL_SIDE_ONE), 1);
            }
            add(elements, PRO_E_FEAT_FORM_IS_THIN, integer(PRO_EXT_FEAT_FORM_NO_THIN), 1);
            body(solid, elements);
            add(elements, PRO_E_STD_SECTION, null, 1);
            add(elements, PRO_E_STD_SEC_SETUP_PLANE, null, 2);
            add(elements, PRO_E_STD_SEC_PLANE, select(solid, sketch.plane.surfaceId), 3);
            add(elements, PRO_E_STD_SEC_PLANE_VIEW_DIR, integer(PRO_SEC_VIEW_DIR_SIDE_ONE), 3);
            add(elements, PRO_E_STD_SEC_PLANE_ORIENT_DIR, integer(Sketch.dot(orient.normal, sketch.x) > 0
                    ? PRO_SEC_ORIENT_DIR_RIGHT : PRO_SEC_ORIENT_DIR_LEFT), 3);
            add(elements, PRO_E_STD_SEC_PLANE_ORIENT_REF, select(solid, orient.surfaceId), 3);
            // The library sets the side from the section's own normal (ccn_sketch "direction").
            add(elements, PRO_E_STD_DIRECTION, integer(sideOne ? PRO_EXT_CR_IN_SIDE_ONE : PRO_EXT_CR_IN_SIDE_TWO), 1);
            add(elements, PRO_E_STD_EXT_DEPTH, null, 1);
            add(elements, PRO_E_EXT_DEPTH_TO, null, 2);
            if (throughAll) {
                add(elements, PRO_E_EXT_DEPTH_TO_TYPE, integer(PRO_EXT_DEPTH_TO_ALL), 3);
            } else if (toPlane != null) {
                add(elements, PRO_E_EXT_DEPTH_TO_TYPE, integer(PRO_EXT_DEPTH_TO_REF), 3);
                add(elements, PRO_E_EXT_DEPTH_TO_REF, select(solid, toPlane.surfaceId), 3);
            } else {
                add(elements, PRO_E_EXT_DEPTH_TO_TYPE, integer(symmetric ? PRO_EXT_DEPTH_SYMMETRIC : PRO_EXT_DEPTH_TO_BLIND), 3);
                add(elements, PRO_E_EXT_DEPTH_TO_VALUE, pfcArgument.CreateDoubleArgValue(depth / f), 3);
            }
            add(elements, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
            WSession session = (WSession) Creo.session();
            WFeature feature;
            try {
                feature = wsolid.WCreateFeature(session.CreateElementTree(elements), options(FeatCreateOption.FEAT_CR_INCOMPLETE_FEAT),
                        wfcSolidInstructions.WRegenInstructions_Create());
            } catch (jxthrowable refused) {
                throw new HostError(HostError.NATIVE, "Creo did not start the extrude " + name + ".").nativeMessage(refused.toString());
            }
            int id = feature.GetId();
            try {
                Map<String, Object> built = Native.call("ccn_sketch", Json.map("model", base(model), "kind", "part",
                        "feature", id, "program", sketch.program()));
                sketched(name, built);
                Feature made = solid.GetFeatureById(id);
                if (made == null || made.GetStatus() != FeatureStatus.FEAT_ACTIVE) {
                    throw new HostError(HostError.NATIVE, "Creo built " + name + " but could not regenerate it, for example a depth "
                            + "up to a face it does not reach; the model is as it was.").with("knowledge", KNOWLEDGE);
                }
                // Which way Creo's sides run depends on the plane; the geometry says which way it went.
                double went = side(made, sketch);
                // A cut that went into the air has no faces at all.
                if (!symmetric && (went * Sketch.dot(direction, sketch.normal) < 0 || (remove && went == 0))) {
                    flip((WFeature) made);
                    made = solid.GetFeatureById(id);
                    if (made == null || made.GetStatus() != FeatureStatus.FEAT_ACTIVE || side(made, sketch) * Sketch.dot(direction, sketch.normal) < 0) {
                        throw new HostError(HostError.NATIVE, "Creo did not extrude " + name + " toward " + axisName(direction)
                                + "; the model is as it was.").with("knowledge", KNOWLEDGE);
                    }
                }
                double change = volume(solid, f) - before;
                if (remove ? !(change < 0) : !(change > 0)) {
                    throw new HostError(HostError.VALIDATION, name + " would " + (remove ? "remove" : "add") + " no material: the "
                            + "sketch lies outside the part, or --direction points away from it. The model is as it was.")
                            .with("knowledge", KNOWLEDGE);
                }
                rename(made, built);
                if (depthName != null) {
                    nameValue(made, depth / f, depthName);
                }
            } catch (Throwable failed) {
                takeOut(solid, id);
                throw failed;
            }
            Ops.repaint();
            Feature made = solid.GetFeatureById(id);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
    }

    // ------------------------------------------------------------------ feature delete

    void featureDelete(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        String wanted = Json.string(in, "id", null);
        if (wanted == null) {
            throw new HostError(HostError.VALIDATION, "--id is required: the feature's ID or name.");
        }
        Feature feature = Creo.feature(solid, wanted);
        Map<Integer, Feature> going = new LinkedHashMap<>();
        children(feature, going);
        String docKey = docs.key(model);
        List<String> names = new ArrayList<>();
        for (Feature f : going.values()) {
            String key = docKey + "#/features/" + f.GetId();
            plan.target(key, "feature", f.GetName() == null ? String.valueOf(f.GetId()) : f.GetName());
            plan.change(key, "exists", true, false);
            names.add(f.GetName() == null ? String.valueOf(f.GetId()) : f.GetName() + " (" + f.GetId() + ")");
        }
        plan.action = "Delete " + String.join(", ", names) + (going.size() > 1 ? ": the feature and the features that depend on it" : "")
                + " from " + plan.docId + "; nothing in Creo can bring them back but closing without saving.";
        plan.work = () -> {
            com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
            for (Integer id : going.keySet()) {
                ids.append(id);
            }
            com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions options =
                    com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions.create();
            options.append(com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOption.FEAT_SUPP_OR_DEL_NO_OPTS);
            try {
                ((WSolid) solid).DeleteFeatures(ids, options, wfcSolidInstructions.WRegenInstructions_Create());
            } catch (jxthrowable refused) {
                throw new HostError(HostError.NATIVE, "Creo did not delete " + String.join(", ", names) + ".", "unknown")
                        .nativeMessage(refused.toString());
            }
            Ops.repaint();
            return Docs.facts("dispatched", "applied", Json.map("result", Json.map("deleted", names)));
        };
    }

    private static void children(Feature feature, Map<Integer, Feature> into) throws jxthrowable {
        if (into.containsKey(feature.GetId())) {
            return;
        }
        into.put(feature.GetId(), feature);
        com.ptc.pfc.pfcFeature.Features kids = feature.ListChildren();
        for (int i = 0; kids != null && i < kids.getarraysize(); i++) {
            children(kids.get(i), into);
        }
    }

    // ------------------------------------------------------------------ model check

    private static java.nio.file.Path reports;

    /** Where ModelCHECK writes its reports: a folder beside the host component, never the user's folders. */
    static void reportFolder(java.nio.file.Path folder) {
        reports = folder;
    }

    private static final Pattern DEFAULT_NAME = Pattern.compile("(EXTRUDE|REVOLVE|PROTRUSION|CUT|ROUND|CHAMFER|SHELL|DRAFT|PATTERN|"
            + "HOLE|RIB|DTM|A_|ADTM)[_]?[0-9]+");

    /**
     * Creo's ModelCHECK and creo-cli's own checks of a part: failed or suppressed features, and
     * features left with Creo's default names. ModelCHECK runs in read-only mode with its
     * report in the host's folder; a run that saved the model is reported as an error.
     */
    Map<String, Object> modelCheck(Model model) throws Exception {
        Solid solid = Creo.solid(model);
        List<Object> items = new ArrayList<>();
        Map<String, Object> mc = new LinkedHashMap<>();
        boolean modifiedBefore = model.GetIsModified();
        try {
            java.nio.file.Path out = (reports != null ? reports : java.nio.file.Paths.get(System.getProperty("java.io.tmpdir"), "creo-cli-modelcheck"))
                    .resolve(base(model).toLowerCase(Locale.ROOT));
            deleteTree(out.toFile());
            java.nio.file.Files.createDirectories(out);
            com.ptc.pfc.pfcModelCheck.ModelCheckInstructions instructions = com.ptc.pfc.pfcModelCheck.pfcModelCheck.ModelCheckInstructions_Create();
            instructions.SetOutputDir(out.toString());
            instructions.SetShowInBrowser(Boolean.FALSE);
            com.ptc.pfc.pfcModelCheck.ModelCheckResults r = Creo.session().ExecuteModelCheck(model, instructions);
            mc.put("ran", true);
            mc.put("errors", r.GetNumberOfErrors());
            mc.put("warnings", r.GetNumberOfWarnings());
            mc.put("saved", r.GetWasModelSaved());
            mc.put("report", out.toString());
            if (r.GetWasModelSaved()) {
                items.add(Json.map("rule", "modelcheck_saved", "object", base(model), "severity", "error",
                        "message", "ModelCHECK saved the model; its configuration allows saving."));
            }
        } catch (Throwable notRun) {
            mc.put("ran", false);
            mc.put("reason", String.valueOf(notRun));
        }
        if (!modifiedBefore && model.GetIsModified()) {
            items.add(Json.map("rule", "modelcheck_changed", "object", base(model), "severity", "error",
                    "message", "The model shows changes after ModelCHECK ran; its configuration may change models."));
        }
        com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.TRUE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            String status = Creo.shortName(f.GetStatus(), "FEAT_");
            String label = f.GetName() == null ? String.valueOf(f.GetId()) : f.GetName();
            if ("failed".equals(status) || "unregenerated".equals(status)) {
                items.add(Json.map("rule", "feature_failed", "object", label, "severity", "error", "message", "The feature does not regenerate."));
            } else if ("suppressed".equals(status)) {
                items.add(Json.map("rule", "feature_suppressed", "object", label, "severity", "warning", "message",
                        "The feature is suppressed; delete it or resume it before handing the model over."));
            }
            String type = Creo.shortName(f.GetFeatType(), "FEATTYPE_");
            boolean datumOfTemplate = f.GetId() <= 7 && ("datum_plane".equals(type) || "coord_sys".equals(type));
            if (!datumOfTemplate && f.GetName() != null && DEFAULT_NAME.matcher(f.GetName()).matches()) {
                items.add(Json.map("rule", "feature_unnamed", "object", label, "severity", "warning", "message",
                        "The feature keeps Creo's default name; give it a name that says what it is."));
            }
        }
        long errors = items.stream().filter(x -> "error".equals(((Map<?, ?>) x).get("severity"))).count()
                + (Boolean.TRUE.equals(mc.get("ran")) ? ((Number) mc.get("errors")).longValue() : 0);
        return Json.map("modelcheck", mc, "findings", items, "errors", errors, "passed", errors == 0 && Boolean.TRUE.equals(mc.get("ran")));
    }

    private static void deleteTree(java.io.File dir) {
        java.io.File[] files = dir.listFiles();
        for (int i = 0; files != null && i < files.length; i++) {
            if (files[i].isDirectory()) {
                deleteTree(files[i]);
            }
            files[i].delete();
        }
        dir.delete();
    }

    // ------------------------------------------------------------------ shell create

    void shellCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        Double thickness = Json.number(in, "thickness_mm");
        if (thickness == null || thickness <= 0) {
            throw new HostError(HostError.VALIDATION, "--thickness is required and greater than 0: the wall left, measured inward.");
        }
        List<Surface> removed = new ArrayList<>();
        String removeText = Json.string(in, "remove", null);
        if (removeText != null) {
            for (String one : removeText.split(";")) {
                removed.addAll(faces(solid, one.trim(), false));
            }
        }
        String dimName = dimensionName(in, "thickness_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (dimName != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_mm", null, Ops.clean(thickness));
        }
        plan.action = "Shell the part into " + name + " with " + Ops.clean(thickness) + " mm walls"
                + (removed.isEmpty() ? ", closed" : ", open at " + removeText) + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            Elements elements = Elements.create();
            add(elements, PRO_E_FEATURE_TREE, null, 0);
            add(elements, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_SHELL), 1);
            add(elements, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
            body(solid, elements);
            for (Surface s : removed) {
                add(elements, PRO_E_SHELL_SRF, pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(s, null)), 1);
            }
            add(elements, PRO_E_SHELL_THICK, pfcArgument.CreateDoubleArgValue(thickness / f), 1);
            add(elements, PRO_E_SHELL_FLIP, integer(PRO_SHELL_INSIDE), 1);
            Feature made = complete(solid, elements, name, f, before, false);
            nameOnly(made, dimName);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
    }

    // ------------------------------------------------------------------ round create

    void roundCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        Double radius = Json.number(in, "radius_mm");
        if (radius == null || radius <= 0) {
            throw new HostError(HostError.VALIDATION, "--radius is required and greater than 0.");
        }
        String edgesText = Json.string(in, "edges", null);
        if (edgesText == null) {
            throw new HostError(HostError.VALIDATION, "--edges is required: such as BASE/end:outer-edges, edge(BASE/end, BASE/side[+x]) "
                    + "or edge:57; several separated by ;.");
        }
        List<Edge> edges = edges(solid, edgesText);
        String dimName = dimensionName(in, "radius_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (dimName != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_mm", null, Ops.clean(radius));
        }
        plan.action = "Round " + edges.size() + " edges (" + edgesText + ") to R" + Ops.clean(radius) + " as " + name + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            CurveCollectionInstructions instructions = CurveCollectionInstructions.create();
            for (Edge edge : edges) {
                Selections one = Selections.create();
                one.append(pfcSelect.CreateModelItemSelection(edge, null));
                instructions.append(wfcCollection.CurveCollectionInstruction_Create(CurveCollectionInstrType.CURVCOLL_ADD_ONE_INSTR, one));
            }
            com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
            collection.SetCrvCollection(wfcCollection.CurveCollection_Create(instructions));
            Elements elements = Elements.create();
            add(elements, PRO_E_FEATURE_TREE, null, 0);
            add(elements, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_ROUND), 1);
            add(elements, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
            add(elements, PRO_E_RNDCH_SETS, null, 1);
            add(elements, PRO_E_RNDCH_SET, null, 2);
            add(elements, PRO_E_RNDCH_SHAPE_OPTIONS, integer(PRO_ROUND_TYPE_CONSTANT), 3);
            add(elements, PRO_E_RNDCH_COMPOUND_CONIC, null, 3);
            add(elements, PRO_E_RNDCH_CONIC_TYPE, integer(PRO_ROUND_CONIC_DISABLE), 4);
            add(elements, PRO_E_RNDCH_REFERENCES, null, 3);
            add(elements, PRO_E_RNDCH_REFERENCE_TYPE, integer(PRO_ROUND_REF_EDGE), 4);
            add(elements, PRO_E_STD_CURVE_COLLECTION_APPL, null, 4).SetElemCollection(collection);
            add(elements, PRO_E_RNDCH_RADII, null, 3);
            add(elements, PRO_E_RNDCH_RADIUS, null, 4);
            add(elements, PRO_E_RNDCH_LEG1, null, 5);
            add(elements, PRO_E_RNDCH_LEG_TYPE, integer(PRO_ROUND_RADIUS_TYPE_VALUE), 6);
            add(elements, PRO_E_RNDCH_LEG_VALUE, pfcArgument.CreateDoubleArgValue(radius / f), 6);
            add(elements, PRO_E_RNDCH_ATTACH_TYPE, integer(PRO_ROUND_ATTACHED), 1);
            Feature made = complete(solid, elements, name, f, before, null);
            nameOnly(made, dimName);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
    }

    // ------------------------------------------------------------------ chamfer create

    void chamferCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        Double distance = Json.number(in, "distance_mm");
        if (distance == null || distance <= 0) {
            throw new HostError(HostError.VALIDATION, "--distance is required and greater than 0: the leg on each face.");
        }
        String edgesText = Json.string(in, "edges", null);
        if (edgesText == null) {
            throw new HostError(HostError.VALIDATION, "--edges is required: such as BASE/end:outer-edges or edge:57; several separated by ;.");
        }
        List<Edge> edges = edges(solid, edgesText);
        String dimName = dimensionName(in, "distance_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (dimName != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_mm", null, Ops.clean(distance));
        }
        plan.action = "Chamfer " + edges.size() + " edges (" + edgesText + ") " + Ops.clean(distance) + " x " + Ops.clean(distance)
                + " mm as " + name + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            Elements elements = Elements.create();
            add(elements, PRO_E_FEATURE_TREE, null, 0);
            add(elements, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_CHAMFER), 1);
            add(elements, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
            add(elements, PRO_E_RNDCH_SETS, null, 1);
            add(elements, PRO_E_RNDCH_SET, null, 2);
            add(elements, PRO_E_RNDCH_DIMENSIONAL_SCHEMA, integer(PRO_CHM_D_X_D), 3);
            add(elements, PRO_E_RNDCH_CHAMFER_SHAPE, integer(PRO_CHM_TANGENT_LEGS), 3);
            add(elements, PRO_E_RNDCH_REFERENCES, null, 3);
            add(elements, PRO_E_RNDCH_REFERENCE_TYPE, integer(PRO_ROUND_REF_EDGE), 4);
            add(elements, PRO_E_STD_CURVE_COLLECTION_APPL, null, 4).SetElemCollection(curves(edges));
            add(elements, PRO_E_RNDCH_RADII, null, 3);
            add(elements, PRO_E_RNDCH_RADIUS, null, 4);
            add(elements, PRO_E_RNDCH_LEG1, null, 5);
            add(elements, PRO_E_RNDCH_LEG_TYPE, integer(PRO_ROUND_RADIUS_TYPE_VALUE), 6);
            add(elements, PRO_E_RNDCH_LEG_VALUE, pfcArgument.CreateDoubleArgValue(distance / f), 6);
            Feature made = complete(solid, elements, name, f, before, null);
            nameOnly(made, dimName);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
    }

    private static com.ptc.wfc.wfcCollection.Collection curves(List<Edge> edges) throws jxthrowable {
        CurveCollectionInstructions instructions = CurveCollectionInstructions.create();
        for (Edge edge : edges) {
            Selections one = Selections.create();
            one.append(pfcSelect.CreateModelItemSelection(edge, null));
            instructions.append(wfcCollection.CurveCollectionInstruction_Create(CurveCollectionInstrType.CURVCOLL_ADD_ONE_INSTR, one));
        }
        com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
        collection.SetCrvCollection(wfcCollection.CurveCollection_Create(instructions));
        return collection;
    }

    // ------------------------------------------------------------------ draft create

    void draftCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        String facesText = Json.string(in, "faces", null);
        String hingeText = Json.string(in, "hinge", null);
        double[] pull = Sketch.axis(Json.string(in, "pull", null));
        Double angle = Json.number(in, "angle_deg");
        if (facesText == null || hingeText == null || pull == null || angle == null) {
            throw new HostError(HostError.VALIDATION, "Give --faces (the faces to draft), --hinge (the plane they turn about), --pull "
                    + "(the model axis the mold opens along, such as +y) and --angle.");
        }
        if (angle <= 0 || angle >= 30) {
            throw new HostError(HostError.VALIDATION, "--angle is greater than 0 and less than 30 degrees; the faces always narrow "
                    + "toward --pull.");
        }
        List<Surface> drafted = new ArrayList<>();
        for (String one : facesText.split(";")) {
            drafted.addAll(faces(solid, one.trim(), false));
        }
        for (Surface s : drafted) {
            if (Math.abs(Sketch.dot(Sketch.unit(pointAndNormal(s)[1]), pull)) > 1 - EPS) {
                throw new HostError(HostError.VALIDATION, "surface:" + s.GetId() + " faces along --pull; a draft turns faces that run along it.");
            }
        }
        Sketch.Plane hinge = planes(solid).find(hingeText);
        Sketch.Plane pullPlane = axisPlane(solid, pull);
        if (pullPlane == null) {
            plan.block("No datum plane of the model is normal to --pull; Creo takes the pull direction from one", null);
        }
        String dimName = dimensionName(in, "angle_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (dimName != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_deg", null, Ops.clean(angle));
        }
        plan.action = "Draft " + drafted.size() + " faces (" + facesText + ") " + Ops.clean(angle) + " deg about " + hingeText
                + ", narrowing toward " + axisName(pull) + ", as " + name + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            Feature made = draft(solid, name, drafted, hinge, pullPlane, angle, f, before);
            // The sign of a draft angle turns the faces one way or the other; check the faces narrow toward the pull.
            if (tilt(made, pull) < 0) {
                takeOut(solid, made.GetId());
                made = draft(solid, name, drafted, hinge, pullPlane, -angle, f, before);
                if (tilt(made, pull) < 0) {
                    takeOut(solid, made.GetId());
                    throw new HostError(HostError.NATIVE, "Creo did not draft " + name + " to narrow toward " + axisName(pull)
                            + "; the model is as it was.");
                }
            }
            if (dimName != null) {
                ModelItems dims = made.ListSubItems(ModelItemType.ITEM_DIMENSION);
                for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
                    Dimension d = (Dimension) dims.get(i);
                    if (Math.abs(Math.abs(d.GetDimValue()) - angle) < 1e-9) {
                        d.SetName(dimName);
                    }
                }
            }
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
    }

    private static Feature draft(Solid solid, String name, List<Surface> drafted, Sketch.Plane hinge, Sketch.Plane pullPlane,
                                 double angle, double f, double before) throws Exception {
        SurfaceCollectionInstructions instructions = SurfaceCollectionInstructions.create();
        for (Surface s : drafted) {
            SurfaceCollectionReferences refs = SurfaceCollectionReferences.create();
            refs.append(wfcCollection.SurfaceCollectionReference_Create(SurfaceCollectionRefType.SURFCOLL_REF_SINGLE,
                    pfcSelect.CreateModelItemSelection(s, null)));
            instructions.append(wfcCollection.SurfaceCollectionInstruction_Create(SurfaceCollectionInstrType.SURFCOLL_SINGLE_SURF, true,
                    refs, SurfaceCollectionRules.create()));
        }
        com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
        collection.SetSurfCollection(wfcCollection.SurfaceCollection_Create(instructions));
        Elements e = Elements.create();
        add(e, PRO_E_FEATURE_TREE, null, 0);
        add(e, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_DRAFT), 1);
        add(e, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        add(e, PRO_E_DRAFT_SPLIT, integer(PRO_DRAFT_UI_SPLIT_NONE), 1);
        add(e, PRO_E_STD_SURF_COLLECTION_APPL, null, 1).SetElemCollection(collection);
        add(e, PRO_E_DIRECTION_COMPOUND, null, 1);
        add(e, PRO_E_DIRECTION_REFERENCE, select(solid, pullPlane.surfaceId), 2);
        add(e, PRO_E_DIRECTION_FLIP, integer(0), 2);
        add(e, PRO_E_DRAFT_CONSTANT_OR_VARIABLE, integer(PRO_DRAFT_UI_CONSTANT), 1);
        add(e, PRO_E_DRAFT_INCLUDE_TANGENT, integer(PRO_DRAFT_UI_INC_TANG), 1);
        add(e, PRO_E_DRAFT_SIDE_1, null, 1);
        add(e, PRO_E_DRAFT_NEUTRAL_OBJECT_TYPE_1, integer(PRO_DRAFT_UI_PLANE), 2);
        add(e, PRO_E_DRAFT_NEUTRAL_PLANE_1, select(solid, hinge.surfaceId), 2);
        add(e, PRO_E_DRAFT_DEPENDENT_1, integer(PRO_DRAFT_UI_INDEPENDENT), 2);
        add(e, PRO_E_DRAFT_ANGLE_1, pfcArgument.CreateDoubleArgValue(angle), 2);
        return complete(solid, e, name, f, before, null);
    }

    /** How the drafted faces lean: their mean normal along the pull, outward; positive when they narrow toward it. */
    private static double tilt(Feature draft, double[] pull) throws jxthrowable {
        ModelItems items = draft.ListSubItems(ModelItemType.ITEM_SURFACE);
        double sum = 0;
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            Surface s = (Surface) items.get(i);
            double[] n = Sketch.unit(pointAndNormal(s)[1]);
            if (s.GetOrientation() == com.ptc.pfc.pfcGeometry.SurfaceOrientation.SURFACEORIENT_INWARD) {
                n = new double[] {-n[0], -n[1], -n[2]};
            }
            sum += Sketch.dot(n, pull);
        }
        return sum;
    }

    // ------------------------------------------------------------------ plane create

    void planeCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        String fromText = Json.string(in, "from", null);
        if (fromText == null) {
            throw new HostError(HostError.VALIDATION, "--from is required: the plane or planar face to offset from, or to measure "
                    + "the angle from with --through.");
        }
        Sketch.Plane from = planes(solid).find(fromText);
        Double offset = Json.number(in, "distance_mm");
        Double angle = Json.number(in, "angle_deg");
        String through = Json.string(in, "through", null);
        if ((offset == null) == (angle == null)) {
            throw new HostError(HostError.VALIDATION, "Give --distance, or --through with --angle.");
        }
        if (angle != null && through == null) {
            throw new HostError(HostError.VALIDATION, "--angle needs --through: the axis the plane turns about.");
        }
        if (offset != null && offset <= 0) {
            throw new HostError(HostError.VALIDATION, "--distance must be greater than 0; --direction says which side.");
        }
        ModelItem axis = through == null ? null : axisItem(solid, through);
        double[] direction = from.normal;
        String directionText = Json.string(in, "direction", null);
        if (directionText != null) {
            direction = Sketch.axis(directionText);
            if (direction == null || Math.abs(Math.abs(Sketch.dot(direction, Sketch.unit(from.normal))) - 1) > EPS) {
                throw new HostError(HostError.VALIDATION, "--direction must be a model axis across " + fromText + ".");
            }
        }
        String dimName = dimensionName(in, offset != null ? "distance_name" : "angle_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (dimName != null && offset != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_mm", null, Ops.clean(offset));
        } else if (dimName != null) {
            plan.change(docKey + "#/dimensions/" + dimName, "value_deg", null, Ops.clean(angle));
        }
        plan.action = offset != null
                ? "Create the datum plane " + name + " " + Ops.clean(offset) + " mm from " + fromText + " toward " + axisName(Sketch.unit(direction)) + "."
                : "Create the datum plane " + name + " through " + through + " at " + Ops.clean(angle) + " deg from " + fromText + ".";
        final double[] toward = Sketch.unit(direction);
        plan.work = () -> {
            Feature made = datumPlane(solid, name, from, offset == null ? null : offset / f, axis, angle, f);
            if (offset != null) {
                double[][] pn = pointAndNormal(datumSurface(made));
                if (Sketch.dot(Sketch.minus(pn[0], from.point), toward) < 0) {
                    takeOut(solid, made.GetId());
                    made = datumPlane(solid, name, from, -offset / f, axis, angle, f);
                }
            }
            if (dimName != null) {
                nameOnly(made, dimName);
            }
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, volume(solid, f), f)));
        };
    }

    private Feature datumPlane(Solid solid, String name, Sketch.Plane from, Double offset, ModelItem axis, Double angle, double f) throws Exception {
        Elements e = Elements.create();
        add(e, PRO_E_FEATURE_TREE, null, 0);
        add(e, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_DATUM), 1);
        add(e, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        add(e, PRO_E_DTMPLN_CONSTRAINTS, null, 1);
        if (offset != null) {
            add(e, PRO_E_DTMPLN_CONSTRAINT, null, 2);
            add(e, PRO_E_DTMPLN_CONSTR_TYPE, integer(PRO_DTMPLN_OFFS), 3);
            add(e, PRO_E_DTMPLN_CONSTR_REF, select(solid, from.surfaceId), 3);
            add(e, PRO_E_DTMPLN_CONSTR_REF_OFFSET, pfcArgument.CreateDoubleArgValue(offset), 3);
        } else {
            add(e, PRO_E_DTMPLN_CONSTRAINT, null, 2);
            add(e, PRO_E_DTMPLN_CONSTR_TYPE, integer(PRO_DTMPLN_THRU), 3);
            add(e, PRO_E_DTMPLN_CONSTR_REF, pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(axis, null)), 3);
            add(e, PRO_E_DTMPLN_CONSTRAINT, null, 2);
            add(e, PRO_E_DTMPLN_CONSTR_TYPE, integer(PRO_DTMPLN_ANG), 3);
            add(e, PRO_E_DTMPLN_CONSTR_REF, select(solid, from.surfaceId), 3);
            add(e, PRO_E_DTMPLN_CONSTR_REF_ANGLE, pfcArgument.CreateDoubleArgValue(angle), 3);
        }
        return complete(solid, e, name, f, 0, null);
    }

    private static Surface datumSurface(Feature datum) throws jxthrowable {
        ModelItems items = datum.ListSubItems(ModelItemType.ITEM_SURFACE);
        if (items == null || items.getarraysize() == 0) {
            throw new HostError(HostError.NATIVE, "The datum plane " + datum.GetName() + " has no plane.");
        }
        return (Surface) items.get(0);
    }

    /** A datum axis by name, or axis:<id>. */
    private static ModelItem axisItem(Solid solid, String text) throws jxthrowable {
        Matcher id = Pattern.compile("axis:([0-9]+)").matcher(text);
        ModelItem item = id.matches() ? solid.GetItemById(ModelItemType.ITEM_AXIS, Integer.parseInt(id.group(1)))
                : solid.GetItemByName(ModelItemType.ITEM_AXIS, text);
        if (item == null) {
            throw new HostError(HostError.NOT_FOUND, "The model has no datum axis " + text + "; geometry list --kind axis shows them.");
        }
        return item;
    }

    // ------------------------------------------------------------------ axis create

    void axisCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        String planesText = Json.string(in, "planes", null);
        String through = Json.string(in, "through", null);
        if ((planesText == null) == (through == null)) {
            throw new HostError(HostError.VALIDATION, "Give --planes A;B (where two planes cross) or --through <cylindrical face>.");
        }
        List<Surface> refs = new ArrayList<>();
        if (planesText != null) {
            String[] two = planesText.split(";");
            if (two.length != 2) {
                throw new HostError(HostError.VALIDATION, "--planes names two planes separated by ;, such as RIGHT;FRONT.");
            }
            for (String one : two) {
                refs.add(faces(solid, one.trim(), true).get(0));
            }
            double[] a = Sketch.unit(pointAndNormal(refs.get(0))[1]);
            double[] b = Sketch.unit(pointAndNormal(refs.get(1))[1]);
            if (Math.abs(Math.abs(Sketch.dot(a, b)) - 1) < EPS) {
                throw new HostError(HostError.VALIDATION, "The two planes are parallel and do not cross.");
            }
        } else {
            Surface s = faces(solid, through, true).get(0);
            if (s.GetSurfaceType() != SurfaceType.SURFACE_CYLINDER) {
                throw new HostError(HostError.VALIDATION, through + " is not cylindrical; --through takes a cylindrical face.");
            }
            refs.add(s);
        }
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        plan.action = "Create the datum axis " + name + (planesText != null ? " where " + planesText.replace(";", " and ") + " cross."
                : " through the axis of " + through + ".");
        plan.work = () -> {
            Elements e = Elements.create();
            add(e, PRO_E_FEATURE_TREE, null, 0);
            add(e, PRO_E_FEATURE_TYPE, integer(PRO_FEAT_DATUM_AXIS), 1);
            add(e, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
            // The constraints form of ProDtmAxis.h: two planes, or a cylinder, each passed through.
            add(e, PRO_E_DTMAXIS_CONSTRAINTS, null, 1);
            for (Surface ref : refs) {
                add(e, PRO_E_DTMAXIS_CONSTRAINT, null, 2);
                add(e, PRO_E_DTMAXIS_CONSTR_TYPE, integer(PRO_DTMAXIS_CONSTR_TYPE_THRU), 3);
                add(e, PRO_E_DTMAXIS_CONSTR_REF, pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(ref, null)), 3);
            }
            Feature made = complete(solid, e, name, f, 0, null);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, volume(solid, f), f)));
        };
    }

    // ------------------------------------------------------------------ pattern create

    void patternCreate(Ops.Plan plan, Model model, Map<String, Object> in) throws Exception {
        Solid solid = Creo.solid(model);
        double f = Units.mmPerUnit(model);
        String name = newName(plan, solid, in);
        String leaderName = Json.string(in, "feature", null);
        if (leaderName == null) {
            throw new HostError(HostError.VALIDATION, "--feature is required: the feature to repeat, by name or ID.");
        }
        Feature leader = Creo.feature(solid, leaderName);
        double[] along = Sketch.axis(Json.string(in, "along", null));
        if (along == null) {
            throw new HostError(HostError.VALIDATION, "--along is required: the model axis the copies step along, such as +x.");
        }
        Long count = Json.integer(in, "count");
        if (count == null || count < 2) {
            throw new HostError(HostError.VALIDATION, "--count is required: how many in all, the original included, 2 or more.");
        }
        Double spacing = Json.number(in, "spacing_mm");
        if (spacing == null || spacing <= 0) {
            throw new HostError(HostError.VALIDATION, "--spacing is required and greater than 0: the step from one copy to the next.");
        }
        try {
            if (leader.GetPattern() != null || leader.GetGroupPattern() != null) {
                plan.block(leaderName + " is already in a pattern", null);
            }
        } catch (jxthrowable unknown) {
            // Not in a pattern.
        }
        Sketch.Plane direction = axisPlane(solid, along);
        if (direction == null) {
            plan.block("No datum plane of the model is normal to " + Json.string(in, "along", null) + "; Creo takes a pattern's direction from one", null);
        }
        String spacingName = dimensionName(in, "spacing_name");
        String docKey = docs.key(model);
        String key = docKey + "#/features/" + name;
        plan.target(key, "feature", name);
        plan.change(key, "status", null, "active");
        if (spacingName != null) {
            plan.change(docKey + "#/dimensions/" + spacingName, "value_mm", null, Ops.clean(spacing));
        }
        plan.action = "Repeat " + leaderName + " " + count + " times in all along " + Json.string(in, "along", null) + ", "
                + Ops.clean(spacing) + " mm apart, as the pattern " + name + "; then regenerate.";
        plan.work = () -> {
            double before = volume(solid, f);
            boolean flip = Sketch.dot(Sketch.unit(direction.normal), along) < 0;
            pattern((WFeature) leader, name, direction, flip, count, spacing / f);
            // CreatePattern answers a member; the pattern itself is the header named in the tree.
            Feature done = Creo.feature(solid, name);
            double[] step = step(leader);
            if (step != null && Sketch.dot(step, along) < 0) {
                setInt((WFeature) done, PRO_E_DIR_PAT_DIR1_FLIP, flip ? 0 : 1);
                done = Creo.feature(solid, name);
                step = step(leader);
            }
            if (done.GetStatus() != FeatureStatus.FEAT_ACTIVE || (step != null && Sketch.dot(step, along) < 0)) {
                takeOut(solid, done.GetId());
                throw new HostError(HostError.NATIVE, "Creo created " + name + " but could not regenerate it toward "
                        + Json.string(in, "along", null) + ", for example copies that run off the part; the model is as it was.");
            }
            if (spacingName != null) {
                nameValue(done, spacing / f, spacingName);
            }
            Ops.repaint();
            Map<String, Object> result = created(solid, done, before, f);
            result.put("count", count);
            return Docs.facts("dispatched", "applied", Json.map("result", result));
        };
    }

    private static WFeature pattern(WFeature leader, String name, Sketch.Plane direction, boolean flip, long count, double spacing) throws Exception {
        Solid solid = (Solid) leader.GetDBParent();
        Elements elements = Elements.create();
        add(elements, PRO_E_PATTERN_ROOT, null, 0);
        add(elements, PRO_E_GENPAT_TYPE, integer(PRO_GENPAT_DIR_DRIVEN), 1);
        add(elements, PRO_E_GENPAT_REGEN_METHOD, integer(PRO_PAT_GENERAL), 1);
        add(elements, PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        add(elements, PRO_E_GENPAT_DIR, null, 1);
        add(elements, PRO_E_DIR_PAT_DIR1_OPT, integer(PRO_GENPAT_TRANSLATIONAL), 2);
        add(elements, PRO_E_GENPAT_DIR1, null, 2);
        add(elements, PRO_E_DIRECTION_COMPOUND, null, 3);
        add(elements, PRO_E_DIRECTION_REFERENCE, select(solid, direction.surfaceId), 4);
        add(elements, PRO_E_DIRECTION_FLIP, integer(0), 4);
        add(elements, PRO_E_DIR_PAT_DIR1_FLIP, integer(flip ? 1 : 0), 2);
        add(elements, PRO_E_GENPAT_DIR1_INC, pfcArgument.CreateDoubleArgValue(spacing), 2);
        add(elements, PRO_E_GENPAT_DIM_FIRST_DIR_NUM_INST, integer((int) count), 2);
        add(elements, PRO_E_GENPAT_DIM_SECOND_DIR_NUM_INST, integer(0), 2);
        try {
            return leader.CreatePattern(((WSession) Creo.session()).CreateElementTree(elements), PatternType.FEAT_PATTERN);
        } catch (jxthrowable refused) {
            throw new HostError(HostError.NATIVE, "Creo did not create the pattern " + name + "; the model is as it was.")
                    .nativeMessage(refused.toString());
        }
    }

    /** Sets one integer element of a feature's tree and redefines it. */
    private static void setInt(WFeature feature, int id, int value) throws jxthrowable {
        ElementTree tree = feature.GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
        Elements all = tree.ListTreeElements();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            if (all.get(i).GetId() == id) {
                all.get(i).SetValue(integer(value));
            }
        }
        feature.RedefineFeature(null, ((WSession) Creo.session()).CreateElementTree(all), options(FeatCreateOption.FEAT_CR_NO_OPTS),
                wfcSolidInstructions.WRegenInstructions_Create());
    }

    /** The step from the leader to the next member, from their faces' mean points; null when unknown. */
    private static double[] step(Feature leader) {
        try {
            com.ptc.pfc.pfcFeature.FeaturePattern fp = leader.GetPattern();
            com.ptc.pfc.pfcFeature.Features members = fp == null ? null : fp.ListMembers();
            if (members == null || members.getarraysize() < 2) {
                return null;
            }
            double[] a = mean(leader);
            double[] b = mean(members.get(1));
            return a == null || b == null ? null : Sketch.minus(b, a);
        } catch (Throwable unknown) {
            return null;
        }
    }

    private static double[] mean(Feature feature) throws jxthrowable {
        ModelItems items = feature.ListSubItems(ModelItemType.ITEM_SURFACE);
        if (items == null || items.getarraysize() == 0) {
            return null;
        }
        double[] sum = new double[3];
        for (int i = 0; i < items.getarraysize(); i++) {
            double[] p = pointAndNormal((Surface) items.get(i))[0];
            sum[0] += p[0];
            sum[1] += p[1];
            sum[2] += p[2];
        }
        int n = items.getarraysize();
        return new double[] {sum[0] / n, sum[1] / n, sum[2] / n};
    }

    /** A datum plane normal to a model axis, to take a direction from. */
    private Sketch.Plane axisPlane(Solid solid, double[] axis) throws Exception {
        for (String n : new String[] {"RIGHT", "TOP", "FRONT"}) {
            try {
                Sketch.Plane p = planes(solid).find(n);
                if (Math.abs(Math.abs(Sketch.dot(Sketch.unit(p.normal), axis)) - 1) < EPS) {
                    return p;
                }
            } catch (HostError absent) {
                // Not in this model.
            }
        }
        return null;
    }

    /**
     * Creates a feature from a complete element tree and checks it: active after regeneration,
     * and, when {@code adds} is not null, the volume grew (true) or shrank (false). Otherwise the
     * feature is taken back out and the call fails.
     */
    private static Feature complete(Solid solid, Elements elements, String name, double f, double before, Boolean adds) throws Exception {
        WFeature feature;
        try {
            feature = ((WSolid) solid).WCreateFeature(((WSession) Creo.session()).CreateElementTree(elements),
                    options(FeatCreateOption.FEAT_CR_NO_OPTS), wfcSolidInstructions.WRegenInstructions_Create());
        } catch (jxthrowable refused) {
            Feature left = null;
            try {
                left = Creo.feature(solid, name);
            } catch (HostError none) {
                // Nothing was left behind.
            }
            if (left != null) {
                takeOut(solid, left.GetId());
            }
            throw new HostError(HostError.NATIVE, "Creo did not create " + name + ", for example a wall too thick for the part or "
                    + "a radius larger than the faces it joins; the model is as it was.").nativeMessage(refused.toString());
        }
        int id = feature.GetId();
        Feature made = solid.GetFeatureById(id);
        if (made == null || made.GetStatus() != FeatureStatus.FEAT_ACTIVE) {
            takeOut(solid, id);
            throw new HostError(HostError.NATIVE, "Creo created " + name + " but could not regenerate it; the model is as it was.");
        }
        if (adds != null) {
            double change = volume(solid, f) - before;
            if (adds ? !(change > 0) : !(change < 0)) {
                takeOut(solid, id);
                throw new HostError(HostError.VALIDATION, name + " changed no material; the model is as it was.");
            }
        }
        Ops.repaint();
        return solid.GetFeatureById(id);
    }

    /** Names a feature's one key dimension, such as a shell's thickness. */
    private static void nameOnly(Feature feature, String name) throws jxthrowable {
        if (name == null) {
            return;
        }
        ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
            Dimension d = (Dimension) dims.get(i);
            if (d.GetDimValue() != 0) {
                d.SetName(name);
                return;
            }
        }
    }

    /** Names the dimension of a feature that still has Creo's name and holds this value. */
    private static void nameValue(Feature feature, double value, String name) throws jxthrowable {
        ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
            Dimension d = (Dimension) dims.get(i);
            if (Math.abs(d.GetDimValue() - value) < 1e-9 && d.GetSymbol().matches("d[0-9]+")) {
                d.SetName(name);
                return;
            }
        }
    }

    private static String dimensionName(Map<String, Object> in, String key) {
        String name = Json.string(in, key, null);
        if (name != null && !NAME.matcher(name).matches()) {
            throw new HostError(HostError.VALIDATION, "--" + key.replace('_', '-') + " must be a letter, then letters, digits or _, 31 at most.");
        }
        return name;
    }

    // ------------------------------------------------------------------ faces and edges by name

    /** One or more faces: a datum name, surface:<id>, or a feature's faces by place such as BASE/start. */
    List<Surface> faces(Solid solid, String text, boolean one) throws Exception {
        Matcher id = SURFACE_ID.matcher(text);
        if (id.matches()) {
            ModelItem item = solid.GetItemById(ModelItemType.ITEM_SURFACE, Integer.parseInt(id.group(1)));
            if (!(item instanceof Surface)) {
                throw new HostError(HostError.NOT_FOUND, "The model has no surface " + id.group(1) + "; geometry list shows them.");
            }
            return new ArrayList<>(Arrays.asList((Surface) item));
        }
        Matcher m = ROLE.matcher(text);
        if (m.matches()) {
            Feature feature = Creo.feature(solid, m.group(1));
            List<Surface> found = role(solid, feature, m.group(2), m.group(3));
            if (found.isEmpty()) {
                throw new HostError(HostError.NOT_FOUND, "Feature " + m.group(1) + " has no " + m.group(2) + " face"
                        + (m.group(3) == null ? "" : " facing " + m.group(3)) + ".").with("knowledge", Arrays.asList("creo-geometry-references"));
            }
            if (one && found.size() > 1) {
                List<Object> candidates = new ArrayList<>();
                for (Surface s : found) {
                    candidates.add("surface:" + s.GetId());
                }
                throw new HostError("E_AMBIGUOUS", text + " is " + found.size() + " faces; add a normal filter such as [+x], "
                        + "or name one by its surface ID.").with("candidates", candidates);
            }
            return found;
        }
        ModelItem item = solid.GetItemByName(ModelItemType.ITEM_SURFACE, text);
        if (!(item instanceof Surface)) {
            throw new HostError(HostError.NOT_FOUND, "Nothing in the model is named " + text + "; faces are written as BASE/end, "
                    + "BASE/side[+x] or surface:<id>.").with("knowledge", Arrays.asList("creo-geometry-references"));
        }
        return new ArrayList<>(Arrays.asList((Surface) item));
    }

    private static final Pattern EDGE_ID = Pattern.compile("edge:([0-9]+)");
    private static final Pattern EDGE_OF = Pattern.compile("edge\\((.+),(.+)\\)");
    private static final Pattern EDGES_OF = Pattern.compile("(.+):(outer-edges|edges)");

    /** Edges, separated by ;: edge:<id>, edge(face, face), face:edges, face:outer-edges or FEATURE:edges. */
    List<Edge> edges(Solid solid, String text) throws Exception {
        Map<Integer, Edge> out = new LinkedHashMap<>();
        for (String raw : text.split(";")) {
            String one = raw.trim();
            Matcher id = EDGE_ID.matcher(one);
            Matcher of = EDGE_OF.matcher(one);
            Matcher all = EDGES_OF.matcher(one);
            if (id.matches()) {
                ModelItem item = solid.GetItemById(ModelItemType.ITEM_EDGE, Integer.parseInt(id.group(1)));
                if (!(item instanceof Edge)) {
                    throw new HostError(HostError.NOT_FOUND, "The model has no edge " + id.group(1) + "; geometry list shows them.");
                }
                out.put(item.GetId(), (Edge) item);
            } else if (of.matches()) {
                Surface a = faces(solid, of.group(1).trim(), true).get(0);
                Surface b = faces(solid, of.group(2).trim(), true).get(0);
                int before = out.size();
                for (Edge e : edgesOf(a, false)) {
                    if (touches(e, b)) {
                        out.put(e.GetId(), e);
                    }
                }
                if (out.size() == before) {
                    throw new HostError(HostError.NOT_FOUND, of.group(1).trim() + " and " + of.group(2).trim() + " share no edge.");
                }
            } else if (all.matches()) {
                String what = all.group(1).trim();
                boolean outer = "outer-edges".equals(all.group(2));
                List<Surface> surfaces;
                if (NAME.matcher(what).matches() && !isDatum(solid, what)) {
                    surfaces = new ArrayList<>();
                    ModelItems items = Creo.feature(solid, what).ListSubItems(ModelItemType.ITEM_SURFACE);
                    for (int i = 0; items != null && i < items.getarraysize(); i++) {
                        surfaces.add((Surface) items.get(i));
                    }
                } else {
                    surfaces = faces(solid, what, false);
                }
                for (Surface s : surfaces) {
                    for (Edge e : edgesOf(s, outer)) {
                        out.put(e.GetId(), e);
                    }
                }
            } else {
                throw new HostError(HostError.VALIDATION, "Edges are written edge:<id>, edge(face, face), face:edges, face:outer-edges "
                        + "or FEATURE:edges, separated by ;. " + one + " is none of them.").with("knowledge", Arrays.asList("creo-geometry-references"));
            }
        }
        if (out.isEmpty()) {
            throw new HostError(HostError.NOT_FOUND, text + " names no edge.");
        }
        return new ArrayList<>(out.values());
    }

    private static boolean isDatum(Solid solid, String name) {
        try {
            return solid.GetItemByName(ModelItemType.ITEM_SURFACE, name) != null;
        } catch (Throwable none) {
            return false;
        }
    }

    private static List<Edge> edgesOf(Surface s, boolean outerOnly) throws jxthrowable {
        List<Edge> out = new ArrayList<>();
        Contours contours = s.ListContours();
        for (int c = 0; contours != null && c < contours.getarraysize(); c++) {
            Contour contour = contours.get(c);
            if (outerOnly && contour.GetInternalTraversal() != ContourTraversal.CONTOUR_TRAV_EXTERNAL) {
                continue;
            }
            Edges edges = contour.ListElements();
            for (int e = 0; edges != null && e < edges.getarraysize(); e++) {
                out.add(edges.get(e));
            }
        }
        return out;
    }

    private static boolean touches(Edge e, Surface s) throws jxthrowable {
        Surface a = e.GetSurface1();
        Surface b = e.GetSurface2();
        return (a != null && a.GetId() == s.GetId()) || (b != null && b.GetId() == s.GetId());
    }

    /** What ccn_sketch answered, as an error when the sketch was not taken. */
    @SuppressWarnings("unchecked")
    private static void sketched(String name, Map<String, Object> built) {
        Object weak = built.get("weak");
        if (weak instanceof List && !((List<Object>) weak).isEmpty()) {
            List<String> open = new ArrayList<>();
            for (Object w : (List<Object>) weak) {
                if (w instanceof Map) {
                    Map<String, Object> m = (Map<String, Object>) w;
                    open.add(m.get("refs") + " = " + m.get("value"));
                }
            }
            throw new HostError(HostError.VALIDATION, "The sketch of " + name + " is not fully defined: Creo needed " + open.size()
                    + " more dimensions, on " + String.join("; ", open) + ". Add the constraints or dimensions that fix them; "
                    + "the model is as it was.").with("knowledge", KNOWLEDGE);
        }
        if (!Boolean.TRUE.equals(built.get("redefined"))) {
            Object errors = built.get("errors");
            throw new HostError(HostError.NATIVE, "Creo did not take the sketch of " + name + (errors instanceof List
                    && !((List<Object>) errors).isEmpty() ? ": " + errors : "") + "; the model is as it was.").with("knowledge", KNOWLEDGE);
        }
    }

    /** Gives the sketch's dimensions the names the Agent wrote, by the solid dimension IDs the library mapped. */
    @SuppressWarnings("unchecked")
    private static void rename(Feature feature, Map<String, Object> built) throws jxthrowable {
        Object listed = built.get("dimensions");
        if (!(listed instanceof List)) {
            return;
        }
        ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (Object o : (List<Object>) listed) {
            Map<String, Object> d = (Map<String, Object>) o;
            String name = Json.string(d, "name", "-");
            Long solidId = Json.integer(d, "solid");
            if ("-".equals(name) || solidId == null) {
                continue;
            }
            for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
                Dimension dim = (Dimension) dims.get(i);
                if (dim.GetId() == solidId) {
                    dim.SetName(name);
                }
            }
        }
    }

    /**
     * Which side of the sketch plane a feature's faces lie on, along the plane's normal: the
     * sign of their mean distance, 0 when they sit on both sides alike.
     */
    private static double side(Feature feature, Sketch sketch) throws jxthrowable {
        ModelItems items = feature.ListSubItems(ModelItemType.ITEM_SURFACE);
        double sum = 0;
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            double[][] pn = pointAndNormal((Surface) items.get(i));
            sum += Sketch.dot(Sketch.minus(pn[0], sketch.plane.point), sketch.normal);
        }
        return Math.abs(sum) < EPS ? 0 : Math.signum(sum);
    }

    /** Turns a feature to the other side of its sketch plane: the other value of PRO_E_STD_DIRECTION. */
    private static void flip(WFeature feature) throws jxthrowable {
        ElementTree tree = feature.GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
        Elements all = tree.ListTreeElements();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Element e = all.get(i);
            if (e.GetId() == PRO_E_STD_DIRECTION && e.GetValue() != null) {
                e.SetValue(integer(e.GetValue().GetIntValue() == PRO_EXT_CR_IN_SIDE_ONE ? PRO_EXT_CR_IN_SIDE_TWO : PRO_EXT_CR_IN_SIDE_ONE));
            }
        }
        feature.RedefineFeature(null, ((WSession) Creo.session()).CreateElementTree(all), options(FeatCreateOption.FEAT_CR_NO_OPTS),
                wfcSolidInstructions.WRegenInstructions_Create());
    }

    /**
     * Takes a feature that did not come out right back out of the model. A feature just made has
     * no children, so it goes alone (WSolid.DeleteFeatures without clip); FeatureOperations
     * through Solid.ExecuteFeatureOps leaves a datum plane in place (measured on Creo 13.4.1.0).
     */
    private static void takeOut(Solid solid, int id) {
        try {
            com.ptc.cipjava.intseq ids = com.ptc.cipjava.intseq.create();
            ids.append(id);
            com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions options =
                    com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOptions.create();
            options.append(com.ptc.wfc.wfcFeatureInstructions.FeatSuppressOrDeleteOption.FEAT_SUPP_OR_DEL_NO_OPTS);
            ((WSolid) solid).DeleteFeatures(ids, options, wfcSolidInstructions.WRegenInstructions_Create());
        } catch (Throwable stays) {
            throw new HostError(HostError.NATIVE, "Creo did not take feature " + id + " back out after it failed; feature list shows "
                    + "it, and suppressing it (feature update --status suppressed) puts the model back as it was.", "dispatched")
                    .nativeMessage(stays.toString());
        }
    }

    /** The result of a create: the feature, its dimensions, the change of volume and the faces by place. */
    private Map<String, Object> created(Solid solid, Feature feature, double before, double f) throws Exception {
        Map<String, Object> out = new LinkedHashMap<>(Creo.featureRow(feature));
        List<Object> dims = new ArrayList<>();
        ModelItems items = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            Dimension d = (Dimension) items.get(i);
            double v = d.GetDimValue();
            if (v == 0) {
                continue;
            }
            boolean angle = d.GetDimType() == com.ptc.pfc.pfcDimension.DimensionType.DIM_ANGULAR;
            if (d.GetSymbol().matches("p[0-9]+")) {
                dims.add(Json.map("id", d.GetSymbol(), "value", (long) Math.round(v)));  // a pattern's count
            } else {
                dims.add(angle ? Json.map("id", d.GetSymbol(), "value_deg", Ops.clean(v)) : Json.map("id", d.GetSymbol(), "value_mm", Ops.clean(v * f)));
            }
        }
        out.put("dimensions", dims);
        double after = volume(solid, f);
        out.put("volume_mm3", Ops.clean(after));
        out.put("volume_change_mm3", Ops.clean(after - before));
        try {
            com.ptc.pfc.pfcBase.Outline3D box = solid.GetGeomOutline();
            out.put("bounding_box_mm", Json.map("min", point(box.get(0), f), "max", point(box.get(1), f)));
        } catch (Throwable none) {
            out.put("bounding_box_mm", null);
        }
        Map<String, Object> faces = new LinkedHashMap<>();
        for (String role : new String[] {"start", "end", "side"}) {
            faces.put(role, role(solid, feature, role, null).size());
        }
        out.put("faces", faces);
        return out;
    }

    // ------------------------------------------------------------------ names, planes and faces

    private static String newName(Ops.Plan plan, Solid solid, Map<String, Object> in) throws jxthrowable {
        String name = Json.string(in, "name", null);
        if (name == null || !NAME.matcher(name).matches()) {
            throw new HostError(HostError.VALIDATION, "--name is required: a letter, then letters, digits or _, 31 at most, "
                    + "such as BASE or SOCKET_CUT.");
        }
        try {
            Creo.feature(solid, name);
            plan.block("A feature named " + name + " exists; choose another name", null);
        } catch (HostError none) {
            // The name is free.
        }
        return name;
    }

    /** Planes by datum name, by surface:<id>, or a feature's face by its place: BASE/end, BASE/side[+x]. */
    Sketch.Planes planes(Solid solid) {
        return name -> {
            Surface surface = faces(solid, name, true).get(0);
            if (surface.GetSurfaceType() != SurfaceType.SURFACE_PLANE) {
                throw new HostError(HostError.VALIDATION, name + " is not planar; a sketch and its references need planes.");
            }
            double[][] pn = pointAndNormal(surface);
            return new Sketch.Plane(name, surface.GetId(), pn[0], pn[1]);
        };
    }

    /** A datum plane whose normal runs along the sketch's x axis, to orient the sketch by. */
    private Sketch.Plane orientation(Solid solid, Sketch sketch) throws Exception {
        List<String> names = new ArrayList<>(Arrays.asList("RIGHT", "TOP", "FRONT"));
        names.addAll(sketch.references.keySet());
        for (String n : names) {
            try {
                Sketch.Plane p = planes(solid).find(n);
                if (Math.abs(Math.abs(Sketch.dot(Sketch.unit(p.normal), sketch.x)) - 1) < EPS) {
                    return p;
                }
            } catch (HostError absent) {
                // Not in this model.
            }
        }
        return null;
    }

    /**
     * A feature's faces by their place: start, the faces on its sketch plane; end, the planar
     * faces parallel to it farthest away; side, the rest. With a filter such as +x, only faces
     * whose normal points that way.
     */
    static List<Surface> role(Solid solid, Feature feature, String role, String filter) throws Exception {
        List<Surface> out = new ArrayList<>();
        ModelItems items = feature.ListSubItems(ModelItemType.ITEM_SURFACE);
        if (items == null || items.getarraysize() == 0) {
            return out;
        }
        double[][] sketchPlane = sketchPlane(feature);
        double farthest = 0;
        List<Object[]> parallel = new ArrayList<>();
        List<Surface> sides = new ArrayList<>();
        for (int i = 0; i < items.getarraysize(); i++) {
            Surface s = (Surface) items.get(i);
            double[][] pn = pointAndNormal(s);
            boolean planar = s.GetSurfaceType() == SurfaceType.SURFACE_PLANE;
            if (sketchPlane != null && planar && Math.abs(Math.abs(Sketch.dot(Sketch.unit(pn[1]), sketchPlane[1])) - 1) < EPS) {
                double distance = Math.abs(Sketch.dot(Sketch.minus(pn[0], sketchPlane[0]), sketchPlane[1]));
                parallel.add(new Object[] {s, distance, pn[1]});
                farthest = Math.max(farthest, distance);
            } else {
                sides.add(s);
            }
        }
        double[] wanted = filter == null ? null : Sketch.axis(filter);
        for (Object[] p : parallel) {
            double distance = (double) p[1];
            boolean isStart = distance < EPS;
            boolean isEnd = !isStart && Math.abs(distance - farthest) < EPS;
            if (("start".equals(role) && isStart) || ("end".equals(role) && isEnd) || ("side".equals(role) && !isStart && !isEnd)) {
                if (wanted == null || Sketch.dot(Sketch.unit((double[]) p[2]), wanted) > 1 - EPS) {
                    out.add((Surface) p[0]);
                }
            }
        }
        if ("side".equals(role)) {
            for (Surface s : sides) {
                if (wanted == null || Sketch.dot(Sketch.unit(pointAndNormal(s)[1]), wanted) > 1 - EPS) {
                    out.add(s);
                }
            }
        }
        return out;
    }

    /** The point and unit normal of a feature's sketch plane, from its element tree; null when it has no sketch. */
    private static double[][] sketchPlane(Feature feature) {
        try {
            ElementTree tree = ((WFeature) feature).GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
            Elements all = tree.ListTreeElements();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                Element e = all.get(i);
                if (e.GetId() == PRO_E_STD_SEC_PLANE && e.GetValue() != null) {
                    Selection sel = e.GetValue().GetSelectionValue();
                    if (sel != null && sel.GetSelItem() instanceof Surface) {
                        double[][] pn = pointAndNormal((Surface) sel.GetSelItem());
                        return new double[][] {pn[0], Sketch.unit(pn[1])};
                    }
                }
            }
        } catch (Throwable none) {
            // A feature without a sketch plane.
        }
        return null;
    }

    /** A point in the middle of a surface's parameter range and the normal there, in model units. */
    static double[][] pointAndNormal(Surface s) throws jxthrowable {
        UVOutline uv = s.GetUVExtents();
        UVParams mid = UVParams.create();
        mid.set(0, (uv.get(0).get(0) + uv.get(1).get(0)) / 2);
        mid.set(1, (uv.get(0).get(1) + uv.get(1).get(1)) / 2);
        SurfXYZData data = s.Eval3DData(mid);
        Point3D p = data.GetPoint();
        Vector3D n = data.GetNormal();
        return new double[][] {{p.get(0), p.get(1), p.get(2)}, {n.get(0), n.get(1), n.get(2)}};
    }

    // ------------------------------------------------------------------ helpers

    private static void body(Solid solid, Elements elements) throws jxthrowable {
        add(elements, PRO_E_BODY, null, 1);
        SolidBody body = solid.GetDefaultBody();
        if (body == null) {
            add(elements, PRO_E_BODY_USE, integer(PRO_BODY_USE_NEW), 2);
        } else {
            add(elements, PRO_E_BODY_USE, integer(PRO_BODY_USE_SELECTED), 2);
            add(elements, PRO_E_BODY_SELECT, pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(body, null)), 2);
        }
    }

    private static ArgValue select(Solid solid, int surfaceId) throws jxthrowable {
        ModelItem item = solid.GetItemById(ModelItemType.ITEM_SURFACE, surfaceId);
        return pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(item, null));
    }

    private static Element add(Elements elements, int id, ArgValue value, int level) throws jxthrowable {
        Element element = wfcElementTree.Element_Create(id, value, level);
        elements.append(element);
        return element;
    }

    private static ArgValue integer(int value) throws jxthrowable {
        return pfcArgument.CreateIntArgValue(value);
    }

    private static FeatCreateOptions options(FeatCreateOption option) throws jxthrowable {
        FeatCreateOptions options = FeatCreateOptions.create();
        options.append(option);
        return options;
    }

    /** The model's name as the C library looks it up: the file name without its extension. */
    private static String base(Model model) throws jxthrowable {
        String file = Creo.fileName(model);
        int dot = file.lastIndexOf('.');
        return dot < 0 ? file : file.substring(0, dot);
    }

    private static double volume(Solid solid, double f) {
        try {
            return solid.GetMassPropertyWithDensity(null, com.ptc.pfc.pfcSolid.MPDensityUse.MP_DENSITY_USE_IF_MISSING, 1.0).GetVolume() * f * f * f;
        } catch (Throwable unknown) {
            return Double.NaN;
        }
    }

    private static List<Object> point(Point3D p, double f) throws jxthrowable {
        return Arrays.asList(Ops.clean(p.get(0) * f), Ops.clean(p.get(1) * f), Ops.clean(p.get(2) * f));
    }

    private static String axisName(double[] v) {
        String[] names = {"x", "y", "z"};
        for (int i = 0; i < 3; i++) {
            if (Math.abs(Math.abs(v[i]) - 1) < EPS) {
                return (v[i] > 0 ? "+" : "-") + names[i];
            }
        }
        return String.format(Locale.ROOT, "(%.3f, %.3f, %.3f)", v[0], v[1], v[2]);
    }
}
