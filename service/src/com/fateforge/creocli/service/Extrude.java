package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElementTree.SpecialValue;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcFeatureInstructions.FeatCreateOption;
import com.ptc.wfc.wfcSection.Section;
import com.ptc.wfc.wfcSession.WSession;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.WRegenInstructions;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * feature.extrude and feature.revolve: a sketched profile on a datum plane, extruded along
 * the plane's normal or revolved about an axis, to add or remove material.
 *
 * <p>Two steps, as PTC's own examples do it. The feature is first created incomplete, with
 * everything except the sketch; Creo then hands back a section already placed on the chosen
 * plane and oriented by the chosen reference -- the only reliable way to get a section whose
 * 2D frame matches the model. The profile is drawn into it and the feature redefined
 * complete. If the second step fails, the incomplete feature is deleted and the reply says
 * so: a failed call must not leave a half-built feature for the next one to build on.
 */
final class Extrude {

    private Extrude() {
    }

    static Map<String, Object> create(Map<String, Object> request) throws Exception {
        return build(request, false);
    }

    static Map<String, Object> revolve(Map<String, Object> request) throws Exception {
        return build(request, true);
    }

    private static Map<String, Object> build(Map<String, Object> request, boolean revolve) throws Exception {
        Session session = Creo.session();
        WSession wsession = (WSession) session;
        Solid solid = Creo.part(session, Json.string(request, "model"));
        Map<String, Object> sketch = Json.object(request.get("sketch"), "'sketch'");
        String planeName = Json.string(sketch, "plane");
        String orientName = Json.string(sketch, "orient_ref");
        int orientDir = orientation(Json.string(sketch, "orient", "right"));
        Sketches.Profile profile = Sketches.profile(Json.object(sketch.get("profile"), "'sketch.profile'"));
        double depth = revolve ? 0 : Json.number(request, "depth");
        if (!revolve && depth <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'depth' must be positive");
        }
        double angle = revolve ? Json.number(request, "angle") : 0;
        if (revolve && (angle <= 0 || angle > 360)) {
            throw new Failures.Refusal("E_VALIDATION", "'angle' must be more than 0 and at most 360 degrees");
        }
        String side = Json.string(request, "side", "one");
        boolean cut = "remove".equals(Json.string(request, "material", "add"));
        String featureName = Json.string(request, "name", null);
        boolean keep = Json.bool(request, "keep_on_failure", false);

        // A revolve turns about the sketch's own centerline, as a person draws it, or about an
        // axis or straight edge already in the model.
        String centerline = null;
        Selection externalAxis = null;
        String axisStep = null;
        if (revolve) {
            Object axis = request.get("axis");
            if (axis instanceof String) {
                com.ptc.pfc.pfcModelItem.ModelItem item = Geometry.item(solid, (String) axis);
                int type = item.GetType().getValue();
                if (type != com.ptc.pfc.pfcModelItem.ModelItemType._ITEM_AXIS
                        && type != com.ptc.pfc.pfcModelItem.ModelItemType._ITEM_EDGE) {
                    throw new Failures.Refusal("E_VALIDATION", "a revolve turns about an axis or a straight edge");
                }
                externalAxis = com.ptc.pfc.pfcSelect.pfcSelect.CreateModelItemSelection(item, null);
                // ProRevolve.h note 3: Creo drops the axis from a feature whose sketch is still
                // empty, so it is set again once the sketch exists.
                axisStep = "set_ref:" + Ptc.PRO_E_REVOLVE_AXIS + ":"
                        + (type == com.ptc.pfc.pfcModelItem.ModelItemType._ITEM_AXIS ? "axis" : "edge") + ":"
                        + item.GetId();
            } else {
                centerline = Sketches.centerline(axis);
            }
        }

        // Through the native library whenever it can draw the profile: its sketch is
        // dimensioned to projected references, as a person's is.
        boolean nativeSketch = profile.nativeEntities() != null && Service.sketchLibrary() != null;
        if (!nativeSketch && (!profile.singleEntity() || centerline != null)) {
            throw new Failures.Refusal("E_UNSUPPORTED", Sketches.MULTI_ENTITY_SKETCH + " The native sketch library "
                    + "that adds them is not loaded: " + Service.sketchLibraryStatus());
        }
        String entities = nativeSketch ? profile.nativeEntities() + (centerline == null ? "" : ";" + centerline) : null;
        SketchPlan.Plan plan = null;
        if (nativeSketch) {
            List<String> loops = profile.nativeLoops() == null ? null : new ArrayList<>(profile.nativeLoops());
            if (loops != null && centerline != null) {
                loops.add("axis");
            }
            plan = SketchPlan.plan(entities, loops);
        }
        List<String> references = nativeSketch ? Sketches.references(solid, sketch, planeName) : null;
        Selection plane = Creo.sketchPlane(solid, planeName);
        Selection orient = Creo.sketchPlane(solid, orientName);
        Map<String, Object> volumeBefore = Creo.measure(solid);

        Elements elements = Elements.create();
        Creo.add(elements, Ptc.PRO_E_FEATURE_TREE, null, 0);
        Creo.add(elements, Ptc.PRO_E_FEATURE_TYPE,
                pfcArgument.CreateIntArgValue(cut ? Ptc.PRO_FEAT_CUT : Ptc.PRO_FEAT_PROTRUSION), 1);
        Creo.add(elements, Ptc.PRO_E_FEATURE_FORM,
                pfcArgument.CreateIntArgValue(revolve ? Ptc.PRO_REVOLVE : Ptc.PRO_EXTRUDE), 1);
        Creo.add(elements, Ptc.PRO_E_EXT_SURF_CUT_SOLID_TYPE, pfcArgument.CreateIntArgValue(
                revolve ? Ptc.PRO_REV_FEAT_TYPE_SOLID : Ptc.PRO_EXT_FEAT_TYPE_SOLID), 1);
        Creo.add(elements, Ptc.PRO_E_REMOVE_MATERIAL, pfcArgument.CreateIntArgValue(revolve
                ? (cut ? Ptc.PRO_REV_MATERIAL_REMOVE : Ptc.PRO_REV_MATERIAL_ADD)
                : (cut ? Ptc.PRO_EXT_MATERIAL_REMOVE : Ptc.PRO_EXT_MATERIAL_ADD)), 1);
        Creo.add(elements, Ptc.PRO_E_FEAT_FORM_IS_THIN, pfcArgument.CreateIntArgValue(
                revolve ? Ptc.PRO_REV_FEAT_FORM_NO_THIN : Ptc.PRO_EXT_FEAT_FORM_NO_THIN), 1);
        String bodyUse = body(elements, solid, cut, Json.string(request, "body", "default"));
        Creo.add(elements, Ptc.PRO_E_STD_SECTION, null, 1);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_SETUP_PLANE, null, 2);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE, pfcArgument.CreateSelectionArgValue(plane), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_VIEW_DIR, pfcArgument.CreateIntArgValue(Ptc.PRO_SEC_VIEW_DIR_SIDE_ONE), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_DIR, pfcArgument.CreateIntArgValue(orientDir), 3);
        Creo.add(elements, Ptc.PRO_E_STD_SEC_PLANE_ORIENT_REF, pfcArgument.CreateSelectionArgValue(orient), 3);
        int direction = "two".equals(side)
                ? (revolve ? Ptc.PRO_REV_CR_IN_SIDE_TWO : Ptc.PRO_EXT_CR_IN_SIDE_TWO)
                : (revolve ? Ptc.PRO_REV_CR_IN_SIDE_ONE : Ptc.PRO_EXT_CR_IN_SIDE_ONE);
        Creo.add(elements, Ptc.PRO_E_STD_DIRECTION, pfcArgument.CreateIntArgValue(direction), 1);
        if (revolve) {
            if (externalAxis != null) {
                Creo.add(elements, Ptc.PRO_E_REVOLVE_AXIS_OPT, pfcArgument.CreateIntArgValue(Ptc.PRO_REV_AXIS_EXT_REF), 1);
                Creo.add(elements, Ptc.PRO_E_REVOLVE_AXIS, pfcArgument.CreateSelectionArgValue(externalAxis), 1);
            } else {
                Creo.add(elements, Ptc.PRO_E_REVOLVE_AXIS_OPT, pfcArgument.CreateIntArgValue(Ptc.PRO_REV_AXIS_INT_REF), 1);
            }
            // ProRevolve.h note 2: one side is FROM none, TO an angle; symmetric is TO symmetric.
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE, null, 1);
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE_FROM, null, 2);
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE_FROM_TYPE, pfcArgument.CreateIntArgValue(Ptc.PRO_REV_ANG_FROM_NONE), 3);
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE_TO, null, 2);
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE_TO_TYPE, pfcArgument.CreateIntArgValue(
                    "symmetric".equals(side) ? Ptc.PRO_REV_ANG_SYMMETRIC : Ptc.PRO_REV_ANG_TO_ANGLE), 3);
            Creo.add(elements, Ptc.PRO_E_REV_ANGLE_TO_VAL, pfcArgument.CreateDoubleArgValue(angle), 3);
        } else {
            Creo.add(elements, Ptc.PRO_E_STD_EXT_DEPTH, null, 1);
            Creo.add(elements, Ptc.PRO_E_EXT_DEPTH_TO, null, 2);
            Creo.add(elements, Ptc.PRO_E_EXT_DEPTH_TO_TYPE, pfcArgument.CreateIntArgValue(
                    "symmetric".equals(side) ? Ptc.PRO_EXT_DEPTH_SYMMETRIC : Ptc.PRO_EXT_DEPTH_TO_BLIND), 3);
            Creo.add(elements, Ptc.PRO_E_EXT_DEPTH_TO_VALUE, pfcArgument.CreateDoubleArgValue(depth), 3);
        }
        if (featureName != null) {
            Creo.add(elements, Ptc.PRO_E_STD_FEATURE_NAME, pfcArgument.CreateStringArgValue(featureName), 1);
        }

        WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
        WFeature feature;
        try {
            feature = ((WSolid) solid).WCreateFeature(
                    wsession.CreateElementTree(elements), Creo.options(FeatCreateOption.FEAT_CR_INCOMPLETE_FEAT), regen);
        } catch (Exception failure) {
            throw new Failures.Stage("create_incomplete", failure);
        }
        String stage = "sketch";
        Map<String, Object> sketchReport = null;
        Map<String, Object> dimensioning = new java.util.LinkedHashMap<>();
        if (nativeSketch) {
            try {
                final WFeature incomplete = feature;
                final String extra = axisStep;
                final SketchPlan.Plan planned = plan;
                final String toDraw = plan != null ? plan.entities : entities;
                sketchReport = Creo.withConfig(session, Sketches.ROUND_ON_STRENGTHEN, "no", () -> Sketches.drawNatively(
                        solid, incomplete, toDraw, references, direction, extra, !keep, planned));
                feature = (WFeature) solid.GetFeatureById(feature.GetId());
            } catch (Exception failure) {
                Object reported = nativeCleanup(failure);
                String cleanup = reported != null ? String.valueOf(reported)
                        : keep ? "kept (keep_on_failure)" : deleteFeature(solid, feature);
                Failures.Stage failed = failure instanceof Failures.Stage ? (Failures.Stage) failure
                        : new Failures.Stage("native_sketch", failure, sketchReport);
                failed.cleanup = cleanup;
                throw failed;
            }
        } else {
            try {
                ElementTree tree = feature.GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS);
                Element sketcher = tree.GetElement(Creo.path(Ptc.PRO_E_STD_SECTION, Ptc.PRO_E_SKETCHER));
                Section section = sketcher.GetSpecialValueElem().GetSectionValue();
                section.SetIntentManagerMode(true);
                profile.draw(section);
                section.SetIntentManagerMode(false);
                sketchReport = Sketches.state(section);

                stage = "complete_tree";
                // An element fetched with GetElement(path) is a detached copy: setting its
                // value changes nothing in the tree. PTC's own editing example lists the
                // elements, changes those, and builds a new tree from them; so does this.
                Elements all = tree.ListTreeElements();
                for (int i = 0; i < all.getarraysize(); i++) {
                    Element element = all.get(i);
                    int id = element.GetId();
                    if (id == Ptc.PRO_E_STD_DIRECTION) {
                        // ProExtrude.h note 3: direction is ignored until the section is
                        // fully defined, and comes back as 0, which is no direction at all.
                        element.SetValue(pfcArgument.CreateIntArgValue(direction));
                    } else if (id == Ptc.PRO_E_REVOLVE_AXIS && externalAxis != null) {
                        // Dropped the same way from a feature whose sketch was empty.
                        element.SetValue(pfcArgument.CreateSelectionArgValue(externalAxis));
                    } else if (id == Ptc.PRO_E_SKETCHER && element.GetSpecialValueElem() != null) {
                        SpecialValue value = element.GetSpecialValueElem();
                        value.SetSectionValue(section);
                        element.SetSpecialValueElem(value);
                    }
                }
                ElementTree complete = wsession.CreateElementTree(all);
                dumpTree(complete, request);

                stage = "redefine";
                feature = feature.RedefineFeature(null, complete, Creo.options(FeatCreateOption.FEAT_CR_NO_OPTS), regen);
            } catch (Exception failure) {
                Failures.Stage failed = new Failures.Stage(stage, failure, sketchReport);
                failed.cleanup = keep ? "kept (keep_on_failure)" : deleteFeature(solid, feature);
                throw failed;
            }
        }

        if (nativeSketch && sketchReport != null) {
            try {
                dimensioning = SketchPlan.describe(plan, sketchReport, feature, entities, references);
            } catch (Exception unread) {
                // The feature stands; only the words for its dimensions are missing.
                dimensioning.put("dimension_plan", "not described: " + unread);
            }
        }
        Creo.repaint(session);
        Map<String, Object> extra = Json.map("body", bodyUse, "sketch", sketchReport);
        extra.putAll(dimensioning);
        return built(solid, feature, volumeBefore, extra);
    }

    /**
     * What every feature-building op reports: the feature as Creo now holds it and the
     * volume before and after. The change is signed -- after minus before -- and is not
     * judged here; the CLI sets it beside what the request implied.
     */
    static Map<String, Object> built(Solid solid, Feature feature, Map<String, Object> volumeBefore,
                                     Map<String, Object> extra) throws jxthrowable {
        Double before = Creo.volumeOf(volumeBefore);
        Double after = Creo.volumeOf(Creo.measure(solid));
        if (before == null && after != null) {
            before = 0.0; // a part holding only datums has no volume until this gives it one
        }
        Feature current = solid.GetFeatureById(feature.GetId());
        Map<String, Object> out = Json.map(
                "model", Creo.fileName((Model) solid),
                "units", Creo.units(solid),
                "feature", Json.map(
                        "id", current.GetId(),
                        "name", current.GetName(),
                        "type", Creo.enumName(current.GetFeatType()),
                        "status", Creo.enumName(current.GetStatus())),
                "volume", Json.map("before", before, "after", after,
                        "change", before == null || after == null ? null : after - before));
        out.putAll(extra);
        return out;
    }

    /**
     * Which body the extrusion adds to, or cuts from. Creo 7 made parts multi-body, and a
     * solid extrusion's tree has required PRO_E_BODY / PRO_E_BODY_USE ever since -- which
     * PTC's own extrusion examples predate. A protrusion goes into the default body, as the
     * Extrude button does; a cut removes material from every body it passes through.
     */
    private static String body(Elements elements, Solid solid, boolean cut, String choice) throws jxthrowable {
        Creo.add(elements, Ptc.PRO_E_BODY, null, 1);
        if (!cut && "new".equals(choice)) {
            Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_NEW), 2);
            return "new";
        }
        if (cut) {
            Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_ALL), 2);
            return "all";
        }
        com.ptc.pfc.pfcSolid.SolidBody target = solid.GetDefaultBody();
        if (target == null) {
            Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_NEW), 2);
            return "new";
        }
        Creo.add(elements, Ptc.PRO_E_BODY_USE, pfcArgument.CreateIntArgValue(Ptc.PRO_BODY_USE_SELECTED), 2);
        Creo.add(elements, Ptc.PRO_E_BODY_SELECT,
                pfcArgument.CreateSelectionArgValue(pfcSelect.CreateModelItemSelection(target, null)), 2);
        return "default:" + target.GetId() + ":" + Creo.enumName(target.GetBodyState());
    }

    static int orientation(String word) {
        switch (word) {
            case "up": return Ptc.PRO_SEC_ORIENT_DIR_UP;
            case "down": return Ptc.PRO_SEC_ORIENT_DIR_DOWN;
            case "left": return Ptc.PRO_SEC_ORIENT_DIR_LEFT;
            case "right": return Ptc.PRO_SEC_ORIENT_DIR_RIGHT;
            default: throw new Failures.Refusal("E_VALIDATION", "'orient' must be up, down, left or right");
        }
    }

    /** What the native library reported doing with the feature, if it got that far. */
    @SuppressWarnings("unchecked")
    static Object nativeCleanup(Throwable failure) {
        Throwable cause = failure instanceof Failures.Stage ? failure.getCause() : failure;
        if (cause instanceof Service.ToolkitFailure) {
            Object report = ((Service.ToolkitFailure) cause).error.get("native");
            if (report instanceof Map) {
                return ((Map<String, Object>) report).get("cleanup");
            }
        }
        return null;
    }

    /**
     * Remove a half-built feature, and say what happened. It used to swallow failures; a live
     * run then left two incomplete features that the next step saved, while every reply
     * claimed the model had been left as found.
     */
    static String deleteFeature(Solid solid, Feature feature) {
        try {
            Creo.deleteFeatures(solid, feature.GetId());
            return "deleted";
        } catch (Throwable failure) {
            String id;
            try {
                id = String.valueOf(feature.GetId());
            } catch (Throwable unreadable) {
                id = "?";
            }
            return "NOT deleted -- the model still holds incomplete feature " + id + ": "
                    + Failures.error(failure).get("message");
        }
    }

    /** Diagnostics for feature discovery: write the tree about to be committed, when asked. */
    private static void dumpTree(ElementTree tree, Map<String, Object> request) {
        String target = Json.string(request, "dump_tree", null);
        if (target == null) {
            return;
        }
        try {
            tree.WriteElementTreeToFile(com.ptc.wfc.wfcElementTree.ElementTreeFormat.ELEMTREE_XML, target);
        } catch (Throwable ignored) {
            // Diagnostic only.
        }
    }
}
