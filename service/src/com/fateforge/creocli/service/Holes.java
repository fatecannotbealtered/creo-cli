package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * The holes a fastener needs, as the Hole tool makes them: tapped for a screw, clear of one,
 * counterbored for its head or countersunk for a flat one. A tapped or clearance hole is a
 * Standard hole of the thread series' chart -- Creo's own .hol files, which also give the
 * tap drill, the clearance for each fit and the counterbore and countersink sizes; a plain
 * hole with a counterbore or countersink is a Custom one. Placement is the straight hole's.
 */
final class Holes {

    private Holes() {
    }

    /** hole.chart: one fastener's row of Creo's chart, in the part's unit, for a preview. */
    static Map<String, Object> chart(Map<String, Object> request) throws Exception {
        Solid solid = Creo.part(Creo.session(), Json.string(request, "model"));
        return Json.map("chart", chartRow(Json.string(request, "series", "ISO"), Json.string(request, "size"),
                Dimensions.lengthUnit(solid)));
    }

    /** Whether the request asks for more than a straight hole. */
    static boolean shaped(Map<String, Object> request) {
        return request.containsKey("thread") || request.containsKey("clearance")
                || request.containsKey("counterbore") || request.containsKey("countersink");
    }

    static Map<String, Object> hole(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Map<String, Object> thread = request.containsKey("thread") ? Json.object(request.get("thread"), "'thread'") : null;
        Map<String, Object> clearance = request.containsKey("clearance")
                ? Json.object(request.get("clearance"), "'clearance'") : null;
        if (thread != null && clearance != null) {
            throw new Failures.Refusal("E_VALIDATION", "a hole is tapped for a screw or clear of one, not both");
        }
        Map<String, Object> standard = thread != null ? thread : clearance;
        Object depthValue = request.get("depth");
        boolean through = "through_all".equals(depthValue);
        if (!through && !(depthValue instanceof Double && (Double) depthValue > 0)) {
            throw new Failures.Refusal("E_VALIDATION", "'depth' is a positive number or \"through_all\"");
        }
        String length = Dimensions.lengthUnit(solid);
        Map<String, Object> chart = null;
        int[] indexes = null;
        double diameter;
        String fit = null;
        if (standard != null) {
            String series = Json.string(standard, "series", "ISO");
            String size = Json.string(standard, "size");
            chart = chartRow(series, size, length);
            indexes = indexes(solid, series, (String) chart.get("size"));
            if (thread != null) {
                diameter = (Double) chart.get("tap_drill");
            } else {
                fit = Json.string(clearance, "fit", "medium");
                Object d = chart.get("clearance_" + fit);
                if (!(d instanceof Double) || (Double) d <= 0) {
                    throw new Failures.Refusal("E_VALIDATION", "the " + series + " chart gives no " + fit
                            + " clearance for " + size);
                }
                diameter = (Double) d;
            }
        } else {
            diameter = Json.number(request, "diameter");
        }
        if (diameter <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'diameter' must be positive");
        }
        double[] cbore = feature(request.get("counterbore"), chart, "cbore", "counterbore", "diameter", "depth");
        double[] csink = feature(request.get("countersink"), chart, "csink", "countersink", "diameter", "angle");
        if (cbore != null && csink != null) {
            throw new Failures.Refusal("E_VALIDATION", "a hole has a counterbore or a countersink, not both");
        }
        if (cbore != null && cbore[0] <= diameter) {
            throw new Failures.Refusal("E_VALIDATION", "a counterbore is wider than the hole");
        }
        if (csink != null && csink[0] <= diameter) {
            throw new Failures.Refusal("E_VALIDATION", "a countersink is wider than the hole");
        }
        double threadDepth = 0;
        boolean throughThread = false;
        if (thread != null) {
            Object t = thread.get("depth");
            throughThread = t == null || "through".equals(t);
            if (!throughThread) {
                threadDepth = Json.number(thread, "depth");
                if (threadDepth <= 0 || (!through && threadDepth > (Double) depthValue)) {
                    throw new Failures.Refusal("E_VALIDATION", "'thread.depth' is positive and no deeper than the hole");
                }
            } else if (!through) {
                throw new Failures.Refusal("E_VALIDATION", "a blind tapped hole says how deep its thread goes: "
                        + "'thread.depth'");
            }
        }
        Map<String, Object> placement = Json.object(request.get("placement"), "'placement'");

        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_FEAT_HOLE), 1);
        Creo.add(elements, Ptc.PRO_E_FEATURE_FORM, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_TYPE_SKETCHED), 1);
        Creo.add(elements, Ptc.PRO_E_HLE_COM, null, 1);
        Creo.add(elements, Ptc.PRO_E_HLE_TYPE_NEW, pfcArgument.CreateIntArgValue(
                standard != null ? Ptc.PRO_HLE_NEW_TYPE_STANDARD : Ptc.PRO_HLE_CUSTOM_TYPE), 2);
        if (standard != null) {
            Creo.add(elements, Ptc.PRO_E_HLE_STAN_TYPE, pfcArgument.CreateIntArgValue(
                    thread != null ? Ptc.PRO_HLE_TAPPED_TYPE : Ptc.PRO_HLE_CLEARANCE_TYPE), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_THRDSERIS, pfcArgument.CreateIntArgValue(indexes[0]), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_FITTYPE, pfcArgument.CreateIntArgValue(
                    "close".equals(fit) || fit == null ? Ptc.PRO_HLE_CLOSE_FIT
                            : "free".equals(fit) ? Ptc.PRO_HLE_FREE_FIT : Ptc.PRO_HLE_MEDIUM_FIT), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_SCREWSIZE, pfcArgument.CreateIntArgValue(indexes[1]), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_ADD_THREAD, pfcArgument.CreateIntArgValue(
                    thread != null ? Ptc.PRO_HLE_ADD_THREAD : Ptc.PRO_HLE_NO_THREAD), 2);
        }
        Creo.add(elements, Ptc.PRO_E_HLE_ADD_CBORE, pfcArgument.CreateIntArgValue(
                cbore != null ? Ptc.PRO_HLE_ADD_CBORE : Ptc.PRO_HLE_NO_CBORE), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_ADD_CSINK, pfcArgument.CreateIntArgValue(
                csink != null ? Ptc.PRO_HLE_ADD_CSINK : Ptc.PRO_HLE_NO_CSINK), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_HOLEDIAM, pfcArgument.CreateDoubleArgValue(diameter), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_DEPTH, pfcArgument.CreateIntArgValue(
                through ? Ptc.PRO_HLE_STD_THRU_ALL_DEPTH : Ptc.PRO_HLE_STD_VAR_DEPTH), 2);
        if (csink != null) {
            Creo.add(elements, Ptc.PRO_E_HLE_CSINKANGLE, pfcArgument.CreateDoubleArgValue(csink[1]), 2);
        }
        if (cbore != null) {
            Creo.add(elements, Ptc.PRO_E_HLE_CBOREDEPTH, pfcArgument.CreateDoubleArgValue(cbore[1]), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_CBOREDIAM, pfcArgument.CreateDoubleArgValue(cbore[0]), 2);
        }
        if (csink != null) {
            Creo.add(elements, Ptc.PRO_E_HLE_CSINKDIAM, pfcArgument.CreateDoubleArgValue(csink[0]), 2);
        }
        if (!through) {
            Creo.add(elements, Ptc.PRO_E_HLE_DEPTH_DIM_TYPE,
                    pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_DEP_SHOULDER_DIM_SCHEME), 2);
        }
        if (thread != null) {
            Creo.add(elements, Ptc.PRO_E_HLE_THRD_DEPTH, pfcArgument.CreateIntArgValue(
                    throughThread ? Ptc.PRO_HLE_THRU_THREAD : Ptc.PRO_HLE_VARIABLE_THREAD), 2);
            // ProHole.h: mandatory even when the thread runs through; then it is not used.
            Creo.add(elements, Ptc.PRO_E_HLE_THRDDEPTH, pfcArgument.CreateDoubleArgValue(
                    throughThread ? diameter : threadDepth), 2);
        }
        if (!through) {
            Creo.add(elements, Ptc.PRO_E_HLE_DRILLANGLE, pfcArgument.CreateDoubleArgValue(118.0), 2);
        }
        // ProHole.h: mandatory even for a hole through all, and then not used. Its table omits
        // it for a custom hole, whose blind depth it nonetheless is: without it Creo drilled
        // one of its own choosing.
        Creo.add(elements, Ptc.PRO_E_HLE_DRILLDEPTH, pfcArgument.CreateDoubleArgValue(
                through ? diameter * 2 : (Double) depthValue), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_CRDIR_FLIP, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_CR_IN_SIDE_ONE), 2);
        if (through) {
            Creo.add(elements, Ptc.PRO_E_HLE_ADD_EXIT_CSINK, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_NO_EXIT_CSINK), 2);
        }
        Creo.add(elements, Ptc.PRO_E_HLE_ADD_NOTE, pfcArgument.CreateIntArgValue(Ptc.PRO_HOLE_ADD_NOTE_FLAG), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_TOP_CLEARANCE, pfcArgument.CreateIntArgValue(Ptc.PRO_HOLE_GEN_CLRNCE), 2);
        String placed = place(elements, solid, placement);
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = Features.create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        Map<String, Object> made = new LinkedHashMap<>();
        made.put("drill_diameter", diameter);
        made.put("depth", through ? "through_all" : depthValue);
        made.put("placement", placed);
        made.put("counterbore", cbore == null ? null : Json.map("diameter", cbore[0], "depth", cbore[1]));
        made.put("countersink", csink == null ? null : Json.map("diameter", csink[0], "angle", csink[1]));
        made.put("chart", chart);
        made.put("surfaces", surfaces(feature));
        return Extrude.built(solid, feature, before, made);
    }

    /**
     * Where a hole goes, as the Hole tool places one (ProHole.h, table Hole:4): on a planar face
     * at distances from two references (linear, case A); on a bolt circle -- about an axis, at
     * a diameter, turned an angle from a plane through the axis (case C), so that a drawing
     * gives the circle's diameter as a drafter does; or on an axis (coaxial, case F), which
     * needs no dimension at all. Returns which.
     */
    static String place(Elements elements, Solid solid, Map<String, Object> placement) throws Exception {
        Selection surface = Geometry.select(solid, Json.string(placement, "surface"));
        String axisRef = Json.string(placement, "axis", null);
        Creo.add(elements, Ptc.PRO_E_HLE_PLACEMENT, null, 1);
        if (axisRef == null) {
            Object offsets = placement.get("offsets");
            if (!(offsets instanceof List) || ((List<?>) offsets).size() != 2) {
                throw new Failures.Refusal("E_VALIDATION", "'placement' needs two 'offsets' {from, distance}, "
                        + "or an 'axis' -- with a 'diameter' and an 'angle_from' plane for a bolt circle");
            }
            Creo.add(elements, Ptc.PRO_E_HLE_PRIM_REF, pfcArgument.CreateSelectionArgValue(surface), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_PL_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_PL_TYPE_LIN), 2);
            Map<String, Object> first = Json.object(((List<?>) offsets).get(0), "'placement.offsets[0]'");
            Map<String, Object> second = Json.object(((List<?>) offsets).get(1), "'placement.offsets[1]'");
            Creo.add(elements, Ptc.PRO_E_HLE_DIM_REF1,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(first, "from"))), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_DIM_DIST1,
                    pfcArgument.CreateDoubleArgValue(Json.number(first, "distance")), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_DIM_REF2,
                    pfcArgument.CreateSelectionArgValue(Geometry.select(solid, Json.string(second, "from"))), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_DIM_DIST2,
                    pfcArgument.CreateDoubleArgValue(Json.number(second, "distance")), 2);
            return "linear";
        }
        com.ptc.pfc.pfcModelItem.ModelItem axisItem = Geometry.item(solid, axisRef);
        if (axisItem.GetType().getValue() != com.ptc.pfc.pfcModelItem.ModelItemType._ITEM_AXIS) {
            throw new Failures.Refusal("E_VALIDATION", "'placement.axis' is an axis: A_1, or axis:<id>");
        }
        Selection axis = com.ptc.pfc.pfcSelect.pfcSelect.CreateModelItemSelection(axisItem, null);
        if (!placement.containsKey("diameter")) {
            Creo.add(elements, Ptc.PRO_E_HLE_PRIM_REF, pfcArgument.CreateSelectionArgValue(axis), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_PL_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_PL_TYPE_COAX), 2);
            Creo.add(elements, Ptc.PRO_E_HLE_PLCMNT_PLANE, pfcArgument.CreateSelectionArgValue(surface), 2);
            return "coaxial";
        }
        double across = Json.number(placement, "diameter");
        if (across <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'placement.diameter' is the bolt circle's, positive");
        }
        Selection from = Geometry.select(solid, Json.string(placement, "angle_from"));
        double angle = placement.containsKey("angle") ? Json.number(placement, "angle") : 0.0;
        Creo.add(elements, Ptc.PRO_E_HLE_PRIM_REF, pfcArgument.CreateSelectionArgValue(surface), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_PL_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_HLE_PL_TYPE_RAD_DIA_DIM), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_AXIS, pfcArgument.CreateSelectionArgValue(axis), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_DIM_DIA, pfcArgument.CreateDoubleArgValue(across), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_REF_PLANE_1, pfcArgument.CreateSelectionArgValue(from), 2);
        Creo.add(elements, Ptc.PRO_E_HLE_REF_ANG_1, pfcArgument.CreateDoubleArgValue(angle), 2);
        return "bolt_circle";
    }

    // ------------------------------------------------------------------ cosmetic thread

    /** ISO 68-1: a basic profile's minor diameter lies 1.082532 x the pitch inside its major. */
    static final double MINOR_OFFSET = 1.082532;

    /**
     * feature.thread: a cosmetic thread on a cylinder -- a shaft's end, or a bore -- as the
     * Cosmetic Thread tool makes one, from a planar face along the cylinder to a depth. It
     * removes nothing: the thread is a surface, dashed on drawings, at the thread's other
     * diameter -- the minor one on a shaft, the major one in a bore.
     *
     * <p>Measured on Creo 13.4: a standard thread made from an element tree ignores its series
     * and size (the thread came out 0.02 across whatever indexes it was given), and a depth
     * compound in the tree fails the feature. So the thread is made simple, at the diameter
     * the chart implies, without the depth; its depth and diameter are then set through its
     * own two dimensions, and its parameters carry the size for the note.
     */
    static Map<String, Object> thread(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.part(session, Json.string(request, "model"));
        com.ptc.pfc.pfcModelItem.ModelItem cylinder = Geometry.item(solid, Json.string(request, "surface"));
        if (!(cylinder instanceof com.ptc.pfc.pfcGeometry.Cylinder)) {
            throw new Failures.Refusal("E_VALIDATION", "a thread goes on a cylindrical face: a shaft or a bore");
        }
        com.ptc.pfc.pfcModelItem.ModelItem start = Geometry.item(solid, Json.string(request, "start"));
        if (!(start instanceof com.ptc.pfc.pfcGeometry.Plane)) {
            throw new Failures.Refusal("E_VALIDATION", "a thread starts from a planar face: the shaft's end");
        }
        double depth = Json.number(request, "depth");
        if (depth <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'depth' must be positive");
        }
        Map<String, Object> row = Geometry.surface((com.ptc.pfc.pfcGeometry.Surface) cylinder, false);
        boolean external = !"toward_axis".equals(row.get("outward"));
        double across = 2 * ((com.ptc.pfc.pfcGeometry.Cylinder) cylinder).GetRadius();
        String size = Json.string(request, "size", null);
        Double given = request.containsKey("diameter") ? Json.number(request, "diameter") : null;
        if ((size == null) == (given == null)) {
            throw new Failures.Refusal("E_VALIDATION", "a thread has a 'size' from a chart or a 'diameter', one of them");
        }
        Map<String, Object> chart = null;
        double diameter;
        Double major = null;
        Double pitch = null;
        if (size != null) {
            String unit = Dimensions.lengthUnit(solid);
            chart = chartRow(Json.string(request, "series", "ISO"), size, unit);
            major = (Double) chart.get("basic_diameter");
            // A metric chart's THREAD column is the pitch; an inch one's is threads per inch.
            Double column = (Double) chart.get("pitch");
            boolean metricChart = size.toUpperCase(java.util.Locale.ROOT).startsWith("M");
            pitch = metricChart ? column : column == null || column == 0 ? null
                    : (unit != null && unit.toLowerCase(java.util.Locale.ROOT).startsWith("in") ? 1 / column : 25.4 / column);
            if (major == null || pitch == null) {
                throw new Failures.Refusal("E_VALIDATION", "the chart gives no diameter and pitch for " + size);
            }
            diameter = external ? major - MINOR_OFFSET * pitch : major;
            if (external && Math.abs(across - major) > 0.02 * major) {
                throw new Failures.Refusal("E_VALIDATION", "a " + size + " thread goes on a shaft of " + major
                        + "; this one is " + Geometry.round(across));
            }
            if (!external && !(across < major)) {
                throw new Failures.Refusal("E_VALIDATION", "a " + size + " thread goes in a bore smaller than "
                        + major + " (its tap drill); this one is " + Geometry.round(across));
            }
        } else {
            diameter = given;
            if (external ? !(diameter < across) : !(diameter > across)) {
                throw new Failures.Refusal("E_VALIDATION", external
                        ? "a shaft's thread is given by its minor diameter, smaller than the shaft's " + Geometry.round(across)
                        : "a bore's thread is given by its major diameter, larger than the bore's " + Geometry.round(across));
            }
        }
        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_FEAT_THREAD), 1);
        String name = Json.string(request, "name", null);
        if (name != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(name), 1);
        }
        Creo.add(elements, Ptc.PRO_E_THRD_TYPE_OPT_NEW, pfcArgument.CreateBoolArgValue(false), 1);
        Creo.add(elements, Ptc.PRO_E_THRD_SURF_NEW, pfcArgument.CreateSelectionArgValue(
                com.ptc.pfc.pfcSelect.pfcSelect.CreateModelItemSelection(cylinder, null)), 1);
        Creo.add(elements, Ptc.PRO_E_THRD_DIAM_NEW, pfcArgument.CreateDoubleArgValue(diameter), 1);
        Creo.add(elements, Ptc.PRO_E_THRD_START_REF_NEW, pfcArgument.CreateSelectionArgValue(
                com.ptc.pfc.pfcSelect.pfcSelect.CreateModelItemSelection(start, null)), 1);
        Map<String, Object> before = Creo.measure(solid);
        WFeature feature = Features.create(session, solid, elements, FeatCreateOption.FEAT_CR_DEFINE_MISS_ELEMS);
        String callout = null;
        try {
            sizeThread(solid, feature, diameter, depth);
            if (major != null) {
                param(feature, "MAJOR_DIAMETER", major);
                param(feature, "PITCH", pitch);
                callout = label(feature, (String) chart.get("size"));
            }
        } catch (Throwable failure) {
            Failures.Stage failed = failure instanceof Failures.Stage ? (Failures.Stage) failure
                    : new Failures.Stage("size", failure);
            failed.cleanup = Extrude.deleteFeature(solid, feature);
            throw failed;
        }
        Creo.repaint(session);
        Map<String, Object> made = new LinkedHashMap<>();
        made.put("external", external);
        made.put("diameter", diameter);
        made.put("depth", depth);
        made.put("chart", chart);
        made.put("parameters", params(feature));
        made.put("callout", callout);
        made.put("surfaces", surfaces(feature));
        return Extrude.built(solid, feature, before, made);
    }

    /**
     * The thread's two dimensions -- its diameter and its depth -- set to the values asked
     * for: the tree rounds its diameter to the model's places (8.376 came back 8.38), and its
     * depth could not be given in the tree at all. Backed out as dimension set is.
     */
    private static void sizeThread(Solid solid, WFeature feature, double diameter, double depth) throws Exception {
        com.ptc.pfc.pfcModelItem.ModelItems dims = feature.ListSubItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_DIMENSION);
        com.ptc.pfc.pfcDimension.BaseDimension across = null;
        com.ptc.pfc.pfcDimension.BaseDimension along = null;
        for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
            com.ptc.pfc.pfcDimension.BaseDimension d = (com.ptc.pfc.pfcDimension.BaseDimension) dims.get(i);
            if ("diameter".equals(Dimensions.kind(d.GetDimType()))) {
                across = d;
            } else {
                along = d;
            }
        }
        if (across == null || along == null) {
            throw new Failures.Refusal("E_CREO", "the thread has no diameter and depth dimensions to size");
        }
        across.SetDimValue(diameter);
        along.SetDimValue(depth);
        com.ptc.wfc.wfcSolidInstructions.WRegenInstructions regen =
                com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions.WRegenInstructions_Create();
        regen.SetUndoIfFail(true);
        regen.SetNoResolveMode(true);
        try {
            ((com.ptc.wfc.wfcSolid.WSolid) solid).WRegenerate(regen);
        } catch (Throwable failure) {
            throw new Failures.Stage("regenerate", failure);
        }
        if (!Dimensions.failedFeatures(solid).isEmpty()) {
            throw new Failures.Stage("regenerate", new Failures.Refusal("E_CREO",
                    "the thread does not fit the cylinder at that depth"));
        }
    }

    /**
     * A thread from the chart is called out on a drawing as M20x2.5, beneath the minor
     * diameter its surface is cut at (17.29): a line of its diameter dimension's text, so every
     * drawing of the part shows it.
     */
    private static String label(WFeature feature, String size) {
        if (size == null || size.isEmpty()) {
            return null;
        }
        String done = null;
        try {
            com.ptc.pfc.pfcModelItem.ModelItems dims =
                    feature.ListSubItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_DIMENSION);
            for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
                com.ptc.pfc.pfcDimension.BaseDimension d = (com.ptc.pfc.pfcDimension.BaseDimension) dims.get(i);
                if ("diameter".equals(Dimensions.kind(d.GetDimType()))) {
                    // A driving dimension's value cannot be hidden (Creo allows it a driven
                    // one only), so the size goes on a line of its own beneath it.
                    com.ptc.cipjava.stringseq was = d.GetTexts();
                    com.ptc.cipjava.stringseq text = com.ptc.cipjava.stringseq.create();
                    for (int k = 0; was != null && k < was.getarraysize(); k++) {
                        if (!size.equals(was.get(k))) {
                            text.append(was.get(k));
                        }
                    }
                    if (text.getarraysize() == 0) {
                        text.append("@D");
                    }
                    text.append(size);
                    d.SetTexts(text);
                    done = size;
                }
            }
        } catch (Throwable unlabelled) {
            // The drawing shows the diameter; the thread itself is unaffected.
        }
        return done;
    }

    private static void param(WFeature feature, String name, double value) {
        try {
            com.ptc.pfc.pfcModelItem.Parameter p = feature.GetParam(name);
            if (p != null) {
                p.SetValue(com.ptc.pfc.pfcModelItem.pfcModelItem.CreateDoubleParamValue(value));
            }
        } catch (Throwable unset) {
            // The note shows the diameter without it; the thread itself is unaffected.
        }
    }

    private static Map<String, Object> params(WFeature feature) {
        Map<String, Object> out = new LinkedHashMap<>();
        try {
            com.ptc.pfc.pfcModelItem.Parameters all = feature.ListParams();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                com.ptc.pfc.pfcModelItem.ParamValue v = all.get(i).GetValue();
                int t = v.Getdiscr().getValue();
                out.put(all.get(i).GetName(), t == com.ptc.pfc.pfcModelItem.ParamValueType._PARAM_STRING ? v.GetStringValue()
                        : t == com.ptc.pfc.pfcModelItem.ParamValueType._PARAM_DOUBLE ? (Object) v.GetDoubleValue()
                        : t == com.ptc.pfc.pfcModelItem.ParamValueType._PARAM_INTEGER ? (Object) v.GetIntValue()
                        : t == com.ptc.pfc.pfcModelItem.ParamValueType._PARAM_BOOLEAN ? (Object) v.GetBoolValue() : null);
            }
        } catch (Throwable unreadable) {
            // Reported as whatever was read.
        }
        return out;
    }

    /** A counterbore's or countersink's two numbers: given, or the chart's for the screw. */
    private static double[] feature(Object raw, Map<String, Object> chart, String prefix, String what,
                                    String first, String second) {
        if (raw == null || Boolean.FALSE.equals(raw)) {
            return null;
        }
        if (Boolean.TRUE.equals(raw)) {
            if (chart == null) {
                throw new Failures.Refusal("E_VALIDATION", "a " + what + " sized by the chart needs a thread or "
                        + "clearance for a screw; otherwise give its " + first + " and " + second);
            }
            Object a = chart.get(prefix + "_" + first);
            Object b = chart.get(prefix + "_" + second);
            if (!(a instanceof Double) || (Double) a <= 0 || !(b instanceof Double) || (Double) b <= 0) {
                throw new Failures.Refusal("E_VALIDATION", "the chart gives no " + what + " for " + chart.get("size")
                        + "; give its " + first + " and " + second);
            }
            return new double[] {(Double) a, (Double) b};
        }
        Map<String, Object> given = Json.object(raw, "'" + what + "'");
        double a = Json.number(given, first);
        double b = Json.number(given, second);
        if (a <= 0 || b <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "a " + what + "'s " + first + " and " + second + " are positive");
        }
        return new double[] {a, b};
    }

    /** The feature's own surfaces with their radii: what the hole turned out to be. */
    static List<Object> surfaces(WFeature feature) throws Exception {
        List<Object> out = new ArrayList<>();
        com.ptc.pfc.pfcModelItem.ModelItems own = feature.ListSubItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_SURFACE);
        for (int i = 0; own != null && i < own.getarraysize(); i++) {
            out.add(Geometry.surface((com.ptc.pfc.pfcGeometry.Surface) own.get(i), false));
        }
        return out;
    }

    /** Creo's indexes for a series and a fastener in it, through the native library. */
    private static int[] indexes(Solid solid, String series, String size) throws Exception {
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a standard hole's series and size are looked up by the "
                    + "native library, which is not loaded: " + Service.sketchLibraryStatus());
        }
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        String model = Creo.fileName((Model) solid).replaceFirst("(?i)\\.prt$", "");
        in.append(pfcArgument.Argument_Create("model", pfcArgument.CreateStringArgValue(model)));
        in.append(pfcArgument.Argument_Create("series", pfcArgument.CreateStringArgValue(series)));
        in.append(pfcArgument.Argument_Create("screw", pfcArgument.CreateStringArgValue(size)));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.HOLE_INDEXES_FUNCTION, in);
        int[] out = {-1, -1};
        String failed = "";
        com.ptc.pfc.pfcArgument.Arguments read = result.GetOutputArguments();
        for (int i = 0; read != null && i < read.getarraysize(); i++) {
            String label = read.get(i).GetLabel();
            if ("series_index".equals(label)) {
                out[0] = read.get(i).GetValue().GetIntValue();
            } else if ("screw_index".equals(label)) {
                out[1] = read.get(i).GetValue().GetIntValue();
            } else if ("failed_step".equals(label)) {
                failed = read.get(i).GetValue().GetStringValue();
            }
        }
        if (result.GetFunctionReturn() != 0) {
            throw new Failures.Refusal("series".equals(failed) || "screw".equals(failed) ? "E_VALIDATION" : "E_CREO",
                    "series".equals(failed) ? "Creo knows no thread series " + series
                            : "screw".equals(failed) ? "Creo's " + series + " chart has no " + size
                            : "the hole chart could not be read: toolkit error " + result.GetFunctionReturn());
        }
        return out;
    }

    /**
     * One fastener's row of Creo's own chart for the series, from the installation's text/hole
     * folder, in the part's length unit: the thread, the tap drill, the clearance for each
     * fit, the counterbore and the countersink.
     */
    static Map<String, Object> chartRow(String series, String size, String partUnit) throws Exception {
        File folder = new File(ModelOps.creoCommonFiles(), "text/hole");
        File[] files = folder.listFiles((dir, name) -> name.toLowerCase(Locale.ROOT).endsWith(".hol"));
        for (File file : files == null ? new File[0] : files) {
            List<String> lines = Files.readAllLines(file.toPath(), StandardCharsets.ISO_8859_1);
            String fileSeries = null;
            String units = null;
            int header = -1;
            for (int i = 0; i < lines.size(); i++) {
                String[] words = lines.get(i).trim().split("\\s+");
                if (words.length >= 2 && "THREAD_SERIES".equals(words[0])) {
                    fileSeries = words[1];
                } else if (words.length >= 2 && "TABLE_UNITS".equals(words[0])) {
                    units = words[1];
                } else if (words.length > 0 && "FASTENER_ID".equals(words[0])) {
                    header = i;
                    break;
                }
            }
            if (header < 0 || !series.equalsIgnoreCase(fileSeries)) {
                continue;
            }
            String[] columns = lines.get(header).trim().split("\\s+");
            List<String> sizes = new ArrayList<>();
            List<String[]> rows = new ArrayList<>();
            for (int i = header + 1; i < lines.size(); i++) {
                String[] cells = lines.get(i).trim().split("\\s+");
                if (cells.length >= columns.length / 2) {
                    sizes.add(cells[0]);
                    rows.add(cells);
                }
            }
            // M5 is how a screw is named, and it means the coarse thread (ISO 261): of the
            // chart's M5x.5 and M5x.8, the one with the greatest pitch.
            String[] found = null;
            String[] coarse = null;
            for (String[] cells : rows) {
                if (cells[0].equalsIgnoreCase(size)) {
                    found = cells;
                    break;
                }
                String name = cells[0].toUpperCase(Locale.ROOT);
                String bare = size.toUpperCase(Locale.ROOT);
                Double pitch = number(columns, cells, "THREAD", 1.0);
                if (bare.startsWith("M") && name.startsWith(bare + "X") && pitch != null
                        && (coarse == null || pitch > number(columns, coarse, "THREAD", 1.0))) {
                    coarse = cells;
                }
            }
            String[] cells = found != null ? found : coarse;
            if (cells != null) {
                double scale = scale(units, partUnit);
                Map<String, Object> row = Json.map("series", fileSeries, "size", cells[0], "file", file.getName(),
                        "units", partUnit);
                if (found == null) {
                    row.put("size_asked", size);
                    row.put("size_meaning", "the coarse thread of that size (ISO 261), the chart's greatest pitch");
                }
                row.put("basic_diameter", number(columns, cells, "BASIC_DIAM", scale));
                row.put("pitch", number(columns, cells, "THREAD", 1.0));
                row.put("tap_drill", number(columns, cells, "TAP_DEC", scale));
                row.put("clearance_close", number(columns, cells, "CLOSE_DEC", scale));
                row.put("clearance_medium", number(columns, cells, "MED_DEC", scale));
                row.put("clearance_free", number(columns, cells, "FREE_DEC", scale));
                row.put("cbore_diameter", number(columns, cells, "CBOREDIAM", scale));
                row.put("cbore_depth", number(columns, cells, "CBOREDEPTH", scale));
                row.put("csink_diameter", number(columns, cells, "CSINKDIAM", scale));
                row.put("csink_angle", number(columns, cells, "CSINKANGLE", 1.0));
                return row;
            }
            throw new Failures.Refusal("E_VALIDATION", "Creo's " + fileSeries + " chart (" + file.getName()
                    + ") has no " + size + "; it has " + sizes);
        }
        throw new Failures.Refusal("E_VALIDATION", "Creo has no hole chart for the thread series " + series
                + " in " + folder);
    }

    private static Double number(String[] columns, String[] cells, String column, double scale) {
        for (int i = 0; i < columns.length && i < cells.length; i++) {
            if (column.equals(columns[i])) {
                try {
                    return Double.parseDouble(cells[i].replace("%", "")) * scale;
                } catch (NumberFormatException notANumber) {
                    return null;
                }
            }
        }
        return null;
    }

    /** From the chart's unit to the part's: an inch chart on a millimetre part, or the other way. */
    private static double scale(String chartUnit, String partUnit) {
        boolean chartInch = chartUnit != null && chartUnit.toLowerCase(Locale.ROOT).startsWith("in");
        boolean partInch = partUnit != null && partUnit.toLowerCase(Locale.ROOT).startsWith("in");
        return chartInch == partInch ? 1.0 : chartInch ? 25.4 : 1 / 25.4;
    }
}
