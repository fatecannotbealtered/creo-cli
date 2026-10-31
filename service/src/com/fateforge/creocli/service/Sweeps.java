package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcCollection.CurveCollectionInstrType;
import com.ptc.wfc.wfcCollection.CurveCollectionInstructions;
import com.ptc.wfc.wfcCollection.wfcCollection;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * feature.sweep: a section swept along a path, as the Sweep tool makes one -- a pipe, a
 * handle, a groove. Two features, as a person makes them: the path, a sketched datum curve
 * of lines and arcs on a datum plane or flat face, and the sweep along it, whose section
 * Creo sets up square to the path at its start. Both sketches are drawn by the native
 * library -- the sweep's at PRO_E_SWEEP_PROF_COMP / PRO_E_SWEEP_SECTION / PRO_E_SKETCHER,
 * around the path's start, as PTC's own sweep example draws its circle at the origin.
 *
 * Measured: the section's y is the path plane's normal and its x that normal crossed with
 * the path's direction where the sweep starts. The sweep starts where Creo's chain does,
 * which is not always the path's start (see runsFrom); set up at the other end, the
 * section is drawn mirrored, so a section point lands where the request put it either way.
 */
final class Sweeps {

    private Sweeps() {
    }

    static final String SECTION_PATH = Ptc.PRO_E_SWEEP_PROF_COMP + "/" + Ptc.PRO_E_SWEEP_SECTION + "/"
            + Ptc.PRO_E_SKETCHER;

    static Map<String, Object> sweep(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Map<String, Object> path = Json.object(request.get("path"), "'path'");
        Map<String, Object> section = Json.object(request.get("section"), "'section'");
        String pathEntities = Outlines.chain(path);
        String sectionEntities = String.join(";", Outlines.loop(section));
        boolean cut = "remove".equals(Json.string(request, "material", "add"));
        String name = Json.string(request, "name", null);
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a sweep's sketches are drawn by the native sketch library, "
                    + "which is not loaded: " + Service.sketchLibraryStatus());
        }
        List<String> references = Sketches.references(solid, path, Json.string(path, "plane"));
        Map<String, Object> volumeBefore = Creo.measure(solid);
        Object[] drawnPath = pathCurve(session, solid, path, pathEntities, references,
                name == null ? null : name + "_PATH");
        WFeature curve = (WFeature) drawnPath[0];
        @SuppressWarnings("unchecked")
        Map<String, Object> pathReport = (Map<String, Object>) drawnPath[1];
        double[][] ends = Outlines.ends(path);
        double[] startsAt = inModel(pathReport, ends[0][0], ends[0][1]);
        double[] endsAt = inModel(pathReport, ends[1][0], ends[1][1]);
        String runsFrom = runsFrom(curve, startsAt, endsAt);
        if ("end".equals(runsFrom)) {
            // Set up at the far end looking back, the section's x is the other way round:
            // drawn mirrored, it sweeps the same solid as one set up at the start.
            sectionEntities = Outlines.mirrored(sectionEntities);
        }
        WFeature swept;
        Map<String, Object> report;
        try {
            Object[] made = along(session, solid, curve, Creo.sketchPlane(solid, Json.string(path, "plane")),
                    sectionEntities, cut, name);
            swept = (WFeature) made[0];
            @SuppressWarnings("unchecked")
            Map<String, Object> drawn = (Map<String, Object>) made[1];
            report = drawn;
        } catch (Failures.Stage failed) {
            failed.cleanup = failed.cleanup + "; the path " + Extrude.deleteFeature(solid, curve);
            throw failed;
        }
        Creo.repaint(session);
        Map<String, Object> pathRow = Json.map("id", curve.GetId(), "name", curve.GetName(), "type",
                Creo.enumName(curve.GetFeatType()),
                "starts_at", startsAt == null ? null : list(startsAt),
                "ends_at", endsAt == null ? null : list(endsAt), "creo_runs_from", runsFrom);
        // The path's own dimensions, as the extrude's sketch gives its: what each measures.
        Object dimensioning = pathReport.remove("dimensioning");
        if (dimensioning instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> d = (Map<String, Object>) dimensioning;
            pathRow.put("dimensions", d.get("sketch_dimensions"));
            pathRow.put("held_together", d.get("held_together"));
            pathRow.put("dimension_plan", d.get("dimension_plan"));
        }
        return Extrude.built(solid, swept, volumeBefore, Json.map("path", pathRow, "sketch", report));
    }

    /**
     * Which end of the path Creo runs the sweep from: the end its whole chain -- the curve
     * that goes from one end of the path to the other -- starts at. Creo runs a sketched chain
     * the way its arcs turn, so a path whose arc turns clockwise it runs from its far end; a
     * start-point instruction in the chain's collection leaves the sweep with no section.
     */
    private static String runsFrom(WFeature curve, double[] start, double[] end) throws Exception {
        if (start == null || end == null) {
            return null;
        }
        ModelItems own = curve.ListSubItems(ModelItemType.ITEM_CURVE);
        for (int i = 0; own != null && i < own.getarraysize(); i++) {
            com.ptc.pfc.pfcGeometry.GeomCurve g = (com.ptc.pfc.pfcGeometry.GeomCurve) own.get(i);
            com.ptc.pfc.pfcBase.Point3D from = g.Eval3DData(0.0).GetPoint();
            com.ptc.pfc.pfcBase.Point3D to = g.Eval3DData(1.0).GetPoint();
            if (near(from, start) && near(to, end)) {
                return "start";
            }
            if (near(from, end) && near(to, start)) {
                return "end";
            }
        }
        return null;
    }

    private static boolean near(com.ptc.pfc.pfcBase.Point3D p, double[] q) throws Exception {
        double scale = 1 + Math.abs(q[0]) + Math.abs(q[1]) + Math.abs(q[2]);
        return Math.abs(p.get(0) - q[0]) + Math.abs(p.get(1) - q[1]) + Math.abs(p.get(2) - q[2]) < 1e-6 * scale;
    }

    /** A point of the path's sketch in the model, by where Creo says the sketch lies; null unsaid. */
    private static double[] inModel(Map<String, Object> report, double u, double v) {
        Object text = report.get("location");
        if (!(text instanceof String) || !(report.get("origin_x") instanceof Number)) {
            return null;
        }
        String[] parts = ((String) text).trim().split("\\s+");
        if (parts.length != 12) {
            return null;
        }
        double[] m = new double[12];
        for (int i = 0; i < 12; i++) {
            m[i] = Double.parseDouble(parts[i]);
        }
        double x = u + ((Number) report.get("origin_x")).doubleValue();
        double y = v + ((Number) report.get("origin_y")).doubleValue();
        return new double[] {m[9] + x * m[0] + y * m[3], m[10] + x * m[1] + y * m[4], m[11] + x * m[2] + y * m[5]};
    }

    private static List<Object> list(double[] p) {
        List<Object> out = new ArrayList<>();
        for (double c : p) {
            out.add(Math.abs(c) < 1e-12 ? 0.0 : c);
        }
        return out;
    }

    /** The path: a sketched datum curve, drawn as an open chain; with where its sketch lies. */
    private static Object[] pathCurve(Session session, Solid solid, Map<String, Object> path, String entities,
                                      List<String> references, String name) throws Exception {
        Selection plane = Creo.sketchPlane(solid, Json.string(path, "plane"));
        Selection orient = Creo.sketchPlane(solid, Json.string(path, "orient_ref"));
        int orientDir = Extrude.orientation(Json.string(path, "orient", "right"));
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_FEAT_CURVE), 1);
        Creo.add(elements, Ptc.PRO_E_CURVE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_CURVE_TYPE_SKETCHED), 1);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Creo.add(elements, Ptc.PRO_E_STD_SECTION, null, 1);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_SETUP_PLANE, null, 2);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE, pfcArgument.CreateSelectionArgValue(plane), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_VIEW_DIR, pfcArgument.CreateIntArgValue(Ptc.PRO_SEC_VIEW_DIR_SIDE_ONE), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_DIR, pfcArgument.CreateIntArgValue(orientDir), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_REF, pfcArgument.CreateSelectionArgValue(orient), 3);
        WFeature feature = incomplete(session, solid, elements, "create_path");
        Map<String, Object> report;
        SketchPlan.Plan plan = SketchPlan.plan(entities, null);
        try {
            report = Sketches.drawNatively(solid, feature, plan == null ? entities : plan.entities, references, 0,
                    "refs,entities,plan,locate,redefine,readback", null, true, plan == null ? null : plan.spec);
        } catch (Exception failure) {
            Object reported = Extrude.nativeCleanup(failure);
            Failures.Stage failed = failure instanceof Failures.Stage ? (Failures.Stage) failure
                    : new Failures.Stage("path", failure);
            failed.cleanup = reported != null ? String.valueOf(reported) : Extrude.deleteFeature(solid, feature);
            throw failed;
        }
        WFeature made = active(solid, (WFeature) solid.GetFeatureById(feature.GetId()), "path", null);
        try {
            report.put("dimensioning", SketchPlan.describe(plan, report, made, entities, references));
        } catch (Exception unread) {
            report.put("dimensioning", Json.map("dimension_plan", "not described: " + unread));
        }
        return new Object[] {made, report};
    }

    /** The sweep along the path's curves, its section drawn where Creo sets it up. */
    private static Object[] along(Session session, Solid solid, WFeature curve, Selection plane, String entities,
                                  boolean cut, String name) throws Exception {
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_FORM, pfcArgument.CreateIntArgValue(Ptc.PRO_SWEEP), 1);
        Creo.add(elements, Ptc.PRO_E_SWEEP_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_SWEEP_TYPE_MULTI_TRAJ), 1);
        Creo.add(elements, Ptc.PRO_E_SWEEP_FRAME_COMP, null, 1);
        Creo.add(elements, Ptc.PRO_E_FRM_OPT_TRAJ, null, 2);
        Creo.add(elements, Ptc.PRO_E_OPT_TRAJ, null, 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_METHOD, pfcArgument.CreateIntArgValue(Ptc.PRO_SEC_SELECT), 4);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_SELECT, null, 4);
        Element collection = Creo.add(elements, Ptc.PRO_E_STD_CURVE_COLLECTION_APPL, null, 5);
        collection.SetElemCollection(curves(curve));
        // As PTC's sweep example lays the frame out: the setup compound, then its options
        // beside it in the frame compound. Normal to the path's projection on its own plane --
        // for a path in that plane, square to the path -- turning about the plane's normal:
        // the section keeps its up the same all along, where the automatic frame turns the
        // section over by which way the path first bends.
        Creo.add(elements, Ptc.PRO_E_FRAME_SETUP, null, 2);
        Creo.add(elements, Ptc.PRO_E_FRM_NORMAL, pfcArgument.CreateIntArgValue(Ptc.PRO_FRAME_PIVOT_DIR), 2);
        Creo.add(elements, Ptc.PRO_E_FRM_PIVOT_DIR, null, 2);
        Creo.add(elements, Ptc.PRO_E_DIRECTION_COMPOUND, null, 3);
        Creo.add(elements, Ptc.PRO_E_DIRECTION_REFERENCE, pfcArgument.CreateSelectionArgValue(plane), 4);
        Creo.add(elements, Ptc.PRO_E_DIRECTION_FLIP, pfcArgument.CreateIntArgValue(Ptc.PRO_DIRECTION_FLIP_ALONG), 4);
        Creo.add(elements, Ptc.PRO_E_FRM_ORIENT, pfcArgument.CreateIntArgValue(Ptc.PRO_FRAME_CONSTANT), 2);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Creo.add(elements, Ptc.PRO_E_EXT_SURF_CUT_SOLID_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_SWEEP_FEAT_TYPE_SOLID), 1);
        Creo.add(elements, Ptc.PRO_E_REMOVE_MATERIAL, pfcArgument.CreateIntArgValue(
                cut ? Ptc.PRO_SWEEP_MATERIAL_REMOVE : Ptc.PRO_SWEEP_MATERIAL_ADD), 1);
        Creo.add(elements, Ptc.PRO_E_FEAT_FORM_IS_THIN, pfcArgument.CreateIntArgValue(Ptc.PRO_SWEEP_FEAT_FORM_NO_THIN), 1);
        Creo.add(elements, Ptc.PRO_E_SWP_ATTR, null, 1);
        Creo.add(elements, Ptc.PRO_E_BODY, null, 1);
        com.ptc.pfc.pfcSolid.SolidBody body = solid.GetDefaultBody();
        if (cut || body == null) {
            Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(
                    cut ? Ptc.PRO_BODY_USE_ALL : Ptc.PRO_BODY_USE_NEW), 2);
        } else {
            Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_SELECTED), 2);
            Creo.add(elements, Ptc.PRO_E_BODY_SELECT,
                    pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(body, null)), 2);
        }
        WFeature feature = incomplete(session, solid, elements, "create_sweep");
        Map<String, Object> report;
        try {
            final WFeature open = feature;
            report = Creo.withConfig(session, Sketches.ROUND_ON_STRENGTHEN, "no", () -> Sketches.drawNatively(
                    solid, open, entities, Collections.emptyList(), 0, "entities,autodim,regenerate,redefine",
                    SECTION_PATH, true));
        } catch (Exception failure) {
            Object reported = Extrude.nativeCleanup(failure);
            Failures.Stage failed = failure instanceof Failures.Stage ? (Failures.Stage) failure
                    : new Failures.Stage("section", failure);
            failed.cleanup = reported != null ? String.valueOf(reported) : Extrude.deleteFeature(solid, feature);
            throw failed;
        }
        return new Object[] {active(solid, (WFeature) solid.GetFeatureById(feature.GetId()), "sweep", report), report};
    }

    /** Every curve of the path, one instruction each, in the order the curve holds them. */
    private static com.ptc.wfc.wfcCollection.Collection curves(WFeature curve) throws Exception {
        ModelItems own = curve.ListSubItems(ModelItemType.ITEM_CURVE);
        if (own == null || own.getarraysize() == 0) {
            throw new Failures.Stage("path", new Failures.Refusal("E_CREO", "the path has no curves"));
        }
        CurveCollectionInstructions instructions = CurveCollectionInstructions.create();
        for (int i = 0; i < own.getarraysize(); i++) {
            Selections one = Selections.create();
            one.append(pfcSelect.CreateModelItemSelection(own.get(i), null));
            instructions.append(wfcCollection.CurveCollectionInstruction_Create(
                    CurveCollectionInstrType.CURVCOLL_ADD_ONE_INSTR, one));
        }
        com.ptc.wfc.wfcCollection.Collection collection = wfcCollection.Collection_Create();
        collection.SetCrvCollection(wfcCollection.CurveCollection_Create(instructions));
        return collection;
    }

    private static WFeature incomplete(Session session, Solid solid, Elements elements, String stage) throws Exception {
        try {
            return ((WSolid) solid).WCreateFeature(((WSession) session).CreateElementTree(elements),
                    Creo.options(FeatCreateOption.FEAT_CR_INCOMPLETE_FEAT), wfcSolidInstructions.WRegenInstructions_Create());
        } catch (Exception failure) {
            throw new Failures.Stage(stage, failure);
        }
    }

    /** The feature once drawn, or a failure that says so and takes it out. */
    private static WFeature active(Solid solid, WFeature feature, String what, Map<String, Object> report)
            throws Exception {
        com.ptc.pfc.pfcFeature.FeatureStatus status = feature.GetStatus();
        if (status.getValue() != com.ptc.pfc.pfcFeature.FeatureStatus._FEAT_ACTIVE) {
            Failures.Stage failed = new Failures.Stage("regenerate", new Failures.Refusal("E_CREO",
                    "Creo made the " + what + " but could not regenerate it (" + Creo.enumName(status) + ")"), report);
            failed.cleanup = Extrude.deleteFeature(solid, feature);
            throw failed;
        }
        return feature;
    }
}
