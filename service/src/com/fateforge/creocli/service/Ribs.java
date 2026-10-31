package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
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
 * feature.rib: a profile rib, as the Rib tool makes one -- an open chain of lines sketched on
 * a datum plane from one face of the part to another, filled up to the part and thickened
 * about the plane. ProRib.h: the sketch sits one level down, under PRO_E_RIB_SECTION_COMP,
 * and its material side means nothing until the sketch exists, so it is set after drawing.
 * The feature is made as an extrusion is: incomplete first, the sketch drawn by the native
 * library, then redefined complete.
 *
 * <p>The public preview freezes which side of the chain fills before execution. Side one
 * is the right of the chain walked from its first point, in the sketch's own axes. A failed
 * creation never changes that decision or creates a second feature with the opposite side.
 */
final class Ribs {

    private Ribs() {
    }

    /** Where the rib's sketch lives: PRO_E_RIB_SECTION_COMP / PRO_E_STD_SECTION / PRO_E_SKETCHER. */
    static final String SKETCHER_PATH = Ptc.PRO_E_RIB_SECTION_COMP + "/" + Ptc.PRO_E_STD_SECTION + "/"
            + Ptc.PRO_E_SKETCHER;

    static Map<String, Object> rib(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Map<String, Object> sketch = Json.object(request.get("sketch"), "'sketch'");
        String planeName = Json.string(sketch, "plane");
        String orientName = Json.string(sketch, "orient_ref");
        int orientDir = Extrude.orientation(Json.string(sketch, "orient", "right"));
        String entities = chain(sketch.get("points"));
        double thickness = Json.number(request, "thickness");
        if (thickness <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'thickness' must be positive");
        }
        int sideOption;
        switch (Json.string(request, "side", "symmetric")) {
            case "symmetric": sideOption = Ptc.PRO_RIB_SYMMETRIC; break;
            case "one": sideOption = Ptc.PRO_RIB_SIDE_ONE; break;
            case "two": sideOption = Ptc.PRO_RIB_SIDE_TWO; break;
            default: throw new Failures.Refusal("E_VALIDATION", "'side' is symmetric, one or two");
        }
        String fill = Json.string(request, "fill", null);
        if (!"right".equals(fill) && !"left".equals(fill)) {
            throw new Failures.Refusal("E_VALIDATION",
                    "'fill' must be frozen as right or left by the public preview");
        }
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a rib's sketch is drawn by the native sketch library, "
                    + "which is not loaded: " + Service.sketchLibraryStatus());
        }
        List<String> references = Sketches.references(solid, sketch, planeName);
        Selection plane = Creo.sketchPlane(solid, planeName);
        Selection orient = Creo.sketchPlane(solid, orientName);
        com.ptc.pfc.pfcSolid.SolidBody body = solid.GetDefaultBody();
        if (body == null) {
            throw new Failures.Refusal("E_CONFLICT", "the part has no solid for a rib to stand on");
        }
        Map<String, Object> volumeBefore = Creo.measure(solid);
        Map<String, Object> made = attempt(session, solid, request, plane, orient, orientDir, body,
                thickness, sideOption, fill, entities, references);
        WFeature feature = (WFeature) made.remove("feature");
        Creo.repaint(session);
        made.put("fill", fill);
        made.put("fill_tried", Collections.emptyList());
        return Extrude.built(solid, feature, volumeBefore, made);
    }

    /** One rib, filling one side of the chain; a rib Creo cannot regenerate is deleted. */
    private static Map<String, Object> attempt(Session session, Solid solid, Map<String, Object> request,
                                               Selection plane, Selection orient, int orientDir,
                                               com.ptc.pfc.pfcSolid.SolidBody body, double thickness, int sideOption,
                                               String fill, String entities, List<String> references)
            throws Exception {
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_FEAT_RIB), 1);
        Creo.add(elements, Ptc.PRO_E_FEATURE_FORM, pfcArgument.CreateIntArgValue(Ptc.PRO_EXTRUDE), 1);
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Creo.add(elements, Ptc.PRO_E_BODY, null, 1);
        Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_SELECTED), 2);
        Creo.add(elements, Ptc.PRO_E_BODY_SELECT,
                pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(body, null)), 2);
        Creo.add(elements, Ptc.PRO_E_RIB_SECTION_COMP, null, 1);
        Creo.add(elements, Ptc.PRO_E_STD_SECTION, null, 2);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_SETUP_PLANE, null, 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE, pfcArgument.CreateSelectionArgValue(plane), 4);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_VIEW_DIR, pfcArgument.CreateIntArgValue(Ptc.PRO_SEC_VIEW_DIR_SIDE_ONE), 4);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_DIR, pfcArgument.CreateIntArgValue(orientDir), 4);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_REF, pfcArgument.CreateSelectionArgValue(orient), 4);
        Creo.add(elements, Ptc.PRO_E_RIB_THICKNESS, pfcArgument.CreateDoubleArgValue(thickness), 1);
        Creo.add(elements, Ptc.PRO_E_RIB_SIDE_OPTS, pfcArgument.CreateIntArgValue(sideOption), 1);

        WFeature feature;
        try {
            feature = ((WSolid) solid).WCreateFeature(((WSession) session).CreateElementTree(elements),
                    Creo.options(FeatCreateOption.FEAT_CR_INCOMPLETE_FEAT),
                    wfcSolidInstructions.WRegenInstructions_Create());
        } catch (Exception failure) {
            throw new Failures.Stage("create_incomplete", failure);
        }
        SketchPlan.Plan plan = SketchPlan.plan(entities, null);
        String steps = "refs,entities,plan,set_int:" + Ptc.PRO_E_RIB_SECTION_COMP + "/"
                + Ptc.PRO_E_STD_MATRLSIDE + ":"
                + ("right".equals(fill) ? Ptc.PRO_RIB_SEC_SIDE_ONE : Ptc.PRO_RIB_SEC_SIDE_TWO) + ",redefine,readback";
        Map<String, Object> report;
        try {
            final WFeature incomplete = feature;
            report = Creo.withConfig(session, Sketches.ROUND_ON_STRENGTHEN, "no", () -> Sketches.drawNatively(
                    solid, incomplete, plan == null ? entities : plan.entities, references, 0, steps, SKETCHER_PATH,
                    true, plan == null ? null : plan.spec));
            feature = (WFeature) solid.GetFeatureById(feature.GetId());
        } catch (Exception failure) {
            Object reported = Extrude.nativeCleanup(failure);
            Failures.Stage failed = failure instanceof Failures.Stage ? (Failures.Stage) failure
                    : new Failures.Stage("native_sketch", failure);
            failed.cleanup = reported != null ? String.valueOf(reported) : Extrude.deleteFeature(solid, feature);
            throw failed;
        }
        com.ptc.pfc.pfcFeature.FeatureStatus status = feature.GetStatus();
        if (status.getValue() != com.ptc.pfc.pfcFeature.FeatureStatus._FEAT_ACTIVE) {
            Failures.Stage failed = new Failures.Stage("regenerate", new Failures.Refusal("E_CREO",
                    "Creo made the rib but could not regenerate it (" + Creo.enumName(status) + "): the chain and "
                            + "the part must close a region on the side filled"), report);
            failed.cleanup = Extrude.deleteFeature(solid, feature);
            Creo.repaint(session);
            throw failed;
        }
        Map<String, Object> out = Json.map("feature", feature, "sketch", report);
        try {
            out.putAll(SketchPlan.describe(plan, report, feature, entities, references));
        } catch (Exception unread) {
            out.put("dimension_plan", "not described: " + unread);
        }
        return out;
    }

    /** "L x0 y0 x1 y1" for each leg of the open chain, as the native library takes them. */
    private static String chain(Object raw) {
        if (!(raw instanceof List) || ((List<?>) raw).size() < 2) {
            throw new Failures.Refusal("E_VALIDATION", "'sketch.points' is an open chain of at least two points");
        }
        List<double[]> points = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            if (!(item instanceof List) || ((List<?>) item).size() != 2) {
                throw new Failures.Refusal("E_VALIDATION", "each of 'sketch.points' is [x, y]");
            }
            List<?> xy = (List<?>) item;
            if (!(xy.get(0) instanceof Number) || !(xy.get(1) instanceof Number)) {
                throw new Failures.Refusal("E_VALIDATION", "each of 'sketch.points' is [x, y]");
            }
            points.add(new double[] {((Number) xy.get(0)).doubleValue(), ((Number) xy.get(1)).doubleValue()});
        }
        List<String> legs = new ArrayList<>();
        for (int i = 1; i < points.size(); i++) {
            double[] a = points.get(i - 1);
            double[] b = points.get(i);
            legs.add("L " + a[0] + " " + a[1] + " " + b[0] + " " + b[1]);
        }
        return String.join(";", legs);
    }
}
