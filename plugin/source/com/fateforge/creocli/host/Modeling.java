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
import com.ptc.pfc.pfcFeature.FeatureOperations;
import com.ptc.pfc.pfcFeature.FeatureStatus;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.SurfXYZData;
import com.ptc.pfc.pfcGeometry.SurfaceType;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcSolid.SolidBody;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcElementTree.wfcElementTree;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
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
            PRO_E_BODY_SELECT = 6316;
    private static final int PRO_FEAT_PROTRUSION = 917, PRO_FEAT_CUT = 916, PRO_EXTRUDE = 1, PRO_EXT_FEAT_TYPE_SOLID = 917,
            PRO_EXT_MATERIAL_ADD = -1, PRO_EXT_MATERIAL_REMOVE = 916, PRO_EXT_FEAT_FORM_NO_THIN = 0,
            PRO_SEC_VIEW_DIR_SIDE_ONE = 1, PRO_SEC_ORIENT_DIR_LEFT = 3, PRO_SEC_ORIENT_DIR_RIGHT = 4,
            PRO_EXT_CR_IN_SIDE_ONE = -1, PRO_EXT_CR_IN_SIDE_TWO = 1, PRO_EXT_MATERIAL_SIDE_ONE = 1,
            PRO_BODY_USE_NEW = 0, PRO_BODY_USE_SELECTED = 2, PRO_EXT_DEPTH_TO_BLIND = 1 << 18,
            PRO_EXT_DEPTH_TO_ALL = 1 << 20, PRO_EXT_DEPTH_TO_REF = 1 << 22, PRO_EXT_DEPTH_SYMMETRIC = 1 << 28;

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
            } catch (Throwable failed) {
                takeOut(solid, id);
                throw failed;
            }
            Ops.repaint();
            Feature made = solid.GetFeatureById(id);
            return Docs.facts("dispatched", "applied", Json.map("result", created(solid, made, before, f)));
        };
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

    /** Takes a feature that did not come out right back out of the model. */
    private static void takeOut(Solid solid, int id) {
        try {
            Feature f = solid.GetFeatureById(id);
            if (f != null) {
                FeatureOperations ops = FeatureOperations.create();
                ops.append(f.CreateDeleteOp());
                solid.ExecuteFeatureOps(ops, null);
            }
        } catch (Throwable stays) {
            // Reported by the read-back: the feature list still has it.
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
            dims.add(angle ? Json.map("id", d.GetSymbol(), "value_deg", Ops.clean(v)) : Json.map("id", d.GetSymbol(), "value_mm", Ops.clean(v * f)));
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
            Matcher id = SURFACE_ID.matcher(name);
            Surface surface;
            if (id.matches()) {
                ModelItem item = solid.GetItemById(ModelItemType.ITEM_SURFACE, Integer.parseInt(id.group(1)));
                if (!(item instanceof Surface)) {
                    throw new HostError(HostError.NOT_FOUND, "The model has no surface " + id.group(1) + "; geometry list shows them.");
                }
                surface = (Surface) item;
            } else if (ROLE.matcher(name).matches()) {
                Matcher m = ROLE.matcher(name);
                m.matches();
                Feature feature = Creo.feature(solid, m.group(1));
                List<Surface> found = role(solid, feature, m.group(2), m.group(3));
                if (found.isEmpty()) {
                    throw new HostError(HostError.NOT_FOUND, "Feature " + m.group(1) + " has no " + m.group(2) + " face"
                            + (m.group(3) == null ? "" : " facing " + m.group(3)) + ".").with("knowledge", Arrays.asList("creo-geometry-references"));
                }
                if (found.size() > 1) {
                    List<Object> candidates = new ArrayList<>();
                    for (Surface s : found) {
                        candidates.add("surface:" + s.GetId());
                    }
                    throw new HostError("E_AMBIGUOUS", name + " is " + found.size() + " faces; add a normal filter such as [+x], "
                            + "or name one by its surface ID.").with("candidates", candidates);
                }
                surface = found.get(0);
            } else {
                ModelItem item = solid.GetItemByName(ModelItemType.ITEM_SURFACE, name);
                if (!(item instanceof Surface)) {
                    throw new HostError(HostError.NOT_FOUND, "The model has no datum plane " + name + "; geometry list --kind "
                            + "datum-plane shows them.").with("knowledge", Arrays.asList("creo-geometry-references"));
                }
                surface = (Surface) item;
            }
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
