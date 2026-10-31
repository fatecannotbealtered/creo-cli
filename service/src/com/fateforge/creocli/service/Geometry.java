package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.Outline3D;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.Vector3D;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.FeatureType;
import com.ptc.pfc.pfcGeometry.CoordSystem;
import com.ptc.pfc.pfcGeometry.CurveDescriptor;
import com.ptc.pfc.pfcGeometry.Edge;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.SurfaceOrientation;
import com.ptc.pfc.pfcGeometry.TransformedSurface;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcGeometry.WAxis;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * geometry.list and geometry.measure, and the one way every feature names geometry.
 *
 * <p>A reference is a string: a datum's name as the model tree shows it ({@code FRONT},
 * {@code A_1}), or {@code surface:<id>} / {@code edge:<id>} for the faces and edges of the
 * solid, whose ids {@code geometry.list} reports. There is no interactive selection.
 */
final class Geometry {

    private Geometry() {
    }

    // ------------------------------------------------------------------ references

    /** The model item a reference names, or a refusal saying what exists instead. */
    static ModelItem item(Solid solid, String ref) throws jxthrowable {
        String text = ref.trim();
        int colon = text.indexOf(':');
        if (colon > 0) {
            String kind = text.substring(0, colon).toLowerCase(Locale.ROOT);
            int id;
            try {
                id = Integer.parseInt(text.substring(colon + 1));
            } catch (NumberFormatException notAnId) {
                throw new Failures.Refusal("E_VALIDATION", "'" + ref + "' is not a reference: use surface:<id>, "
                        + "edge:<id>, axis:<id> or a datum name");
            }
            ModelItemType type = "surface".equals(kind) ? ModelItemType.ITEM_SURFACE
                    : "edge".equals(kind) ? ModelItemType.ITEM_EDGE
                    : "axis".equals(kind) ? ModelItemType.ITEM_AXIS : null;
            if (type == null) {
                throw new Failures.Refusal("E_VALIDATION", "'" + ref + "' is not a reference: use surface:<id>, "
                        + "edge:<id>, axis:<id> or a datum name");
            }
            ModelItem found = null;
            try {
                found = ((Model) solid).GetItemById(type, id);
            } catch (Throwable absent) {
                // Reported below.
            }
            if (found == null) {
                throw new Failures.Refusal("E_NOT_FOUND", "no " + kind + " with id " + id + " in "
                        + Creo.fileName((Model) solid) + "; geometry list shows what exists");
            }
            return found;
        }
        for (ModelItemType type : new ModelItemType[] {
                ModelItemType.ITEM_SURFACE, ModelItemType.ITEM_AXIS, ModelItemType.ITEM_COORD_SYS}) {
            try {
                ModelItem found = ((Model) solid).GetItemByName(type, text);
                if (found != null) {
                    return found;
                }
            } catch (Throwable absent) {
                // Try the next kind.
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "no datum named " + text + " in " + Creo.fileName((Model) solid)
                + "; geometry list shows what exists");
    }

    static Selection select(Solid solid, String ref) throws jxthrowable {
        return pfcSelect.CreateModelItemSelection(item(solid, ref), null);
    }

    /** The reference string for an item: its name for a datum, kind:id otherwise. */
    static String ref(ModelItem item) throws jxthrowable {
        int type = item.GetType().getValue();
        if (type == ModelItemType._ITEM_AXIS) {
            String name = item.GetName();
            return name == null || name.isEmpty() ? "axis:" + item.GetId() : name;
        }
        if (type == ModelItemType._ITEM_SURFACE && isDatumPlane((Surface) item)) {
            Feature owner = ((Surface) item).GetFeature();
            return owner.GetName();
        }
        return (type == ModelItemType._ITEM_EDGE ? "edge:" : "surface:") + item.GetId();
    }

    // ------------------------------------------------------------------ geometry.list

    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        if (PrismaticReadback.PROFILE.equals(request.get("profile")))
            return PrismaticReadback.geometry(solid);
        String kind = Json.string(request, "kind", null);
        String featureRef = Json.string(request, "feature", null);
        Integer only = featureRef == null ? null : Creo.feature(solid, featureRef).GetId();
        List<Object> items = new ArrayList<>();
        // The faces of the solid. Its edges are listed only between two of them: a cut also
        // carries the edges of its own caps, which bound nothing in the part.
        java.util.Set<Integer> faces = new java.util.HashSet<>();
        List<Surface> surfaces = Creo.surfaces(solid);
        for (int i = 0; i < surfaces.size(); i++) {
            Surface s = surfaces.get(i);
            faces.add(s.GetId());
            if ((kind == null || "surface".equals(kind)) && owned(s.GetFeature(), only)) {
                items.add(surface(s, false));
            }
        }
        if (kind == null || "datum_plane".equals(kind)) {
            com.ptc.pfc.pfcFeature.Features planes = solid.ListFeaturesByType(Boolean.TRUE,
                    com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_DATUM_PLANE);
            for (int i = 0; planes != null && i < planes.getarraysize(); i++) {
                Feature plane = planes.get(i);
                ModelItems own = plane.ListSubItems(ModelItemType.ITEM_SURFACE);
                if (own != null && own.getarraysize() > 0 && owned(plane, only)) {
                    items.add(surface((Surface) own.get(0), true));
                }
            }
        }
        if (kind == null || "edge".equals(kind)) {
            // Through the faces' boundary loops, as PTC's own traversal goes (surface, contour,
            // edge). ListItems(ITEM_EDGE) also returns edges earlier features left behind: a
            // corner a round replaced stays listed there, and an edge a later feature rebuilt
            // is listed once per feature that built it -- ids that still resolve, but to no
            // edge of the part.
            java.util.Set<Integer> seen = new java.util.HashSet<>();
            for (int i = 0; i < surfaces.size(); i++) {
                com.ptc.pfc.pfcGeometry.Contours loops = surfaces.get(i).ListContours();
                for (int c = 0; loops != null && c < loops.getarraysize(); c++) {
                    com.ptc.pfc.pfcGeometry.Edges edges = loops.get(c).ListElements();
                    for (int k = 0; edges != null && k < edges.getarraysize(); k++) {
                        Edge e = edges.get(k);
                        if (seen.add(e.GetId()) && owned(e.GetFeature(), only) && bounds(e, faces)) {
                            items.add(edge(e));
                        }
                    }
                }
            }
        }
        if (kind == null || "axis".equals(kind)) {
            ModelItems axes = solid.ListItems(ModelItemType.ITEM_AXIS);
            for (int i = 0; axes != null && i < axes.getarraysize(); i++) {
                WAxis a = (WAxis) axes.get(i);
                if (owned(a.GetFeature(), only)) {
                    items.add(axis(a));
                }
            }
        }
        if (kind == null || "csys".equals(kind)) {
            // Coordinate systems are what a csys constraint places a component by.
            ModelItems systems = solid.ListItems(ModelItemType.ITEM_COORD_SYS);
            for (int i = 0; systems != null && i < systems.getarraysize(); i++) {
                CoordSystem c = (CoordSystem) systems.get(i);
                String name = c.GetName();
                if (name != null && !name.isEmpty() && owned(c.GetFeature(), only)) {
                    items.add(csys(c));
                }
            }
        }
        return Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid), "items", items);
    }

    static Map<String, Object> csys(CoordSystem c) throws jxthrowable {
        Transform3D frame = c.GetCoordSys();
        return Json.map("ref", c.GetName(), "kind", "csys", "id", c.GetId(), "name", c.GetName(),
                "feature", owner(c.GetFeature()), "origin", point(frame.GetOrigin()),
                "x_axis", vector(frame.GetXAxis()), "y_axis", vector(frame.GetYAxis()),
                "z_axis", vector(frame.GetZAxis()));
    }

    private static boolean bounds(Edge e, java.util.Set<Integer> faces) {
        try {
            Surface one = e.GetSurface1();
            Surface two = e.GetSurface2();
            return !e.IsArtificial() && one != null && two != null
                    && faces.contains(one.GetId()) && faces.contains(two.GetId());
        } catch (Throwable unreadable) {
            return false;
        }
    }

    private static boolean owned(Feature feature, Integer only) throws jxthrowable {
        return only == null || (feature != null && feature.GetId() == only);
    }

    static boolean isDatumPlane(Surface s) {
        try {
            Feature owner = s.GetFeature();
            return owner != null && owner.GetFeatType().getValue() == FeatureType._FEATTYPE_DATUM_PLANE;
        } catch (Throwable unreadable) {
            return false;
        }
    }

    static Map<String, Object> surface(Surface s, boolean datum) throws jxthrowable {
        Map<String, Object> out = Json.map(
                "ref", ref(s),
                "kind", datum ? "datum_plane" : "surface",
                "id", s.GetId(),
                "type", shortName(s.GetSurfaceType(), "SURFACE_"),
                "feature", owner(s.GetFeature()));
        if (s instanceof TransformedSurface) {
            Transform3D frame = ((TransformedSurface) s).GetCoordSys();
            double flip = outwardSign(s);
            int type = s.GetSurfaceType().getValue();
            if (type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_PLANE) {
                out.put("normal", scaled(frame.GetZAxis(), flip));
                out.put("origin", point(frame.GetOrigin()));
            } else if (type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_CYLINDER
                    || type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_CONE
                    || type == com.ptc.pfc.pfcGeometry.SurfaceType._SURFACE_TORUS) {
                out.put("axis", Json.map("origin", point(frame.GetOrigin()), "direction", vector(frame.GetZAxis())));
                if (s instanceof com.ptc.pfc.pfcGeometry.Cylinder) {
                    out.put("radius", ((com.ptc.pfc.pfcGeometry.Cylinder) s).GetRadius());
                }
                out.put("outward", flip > 0 ? "away_from_axis" : "toward_axis");
            }
        }
        if (!datum) {
            // A datum plane is unbounded; its extent is only how large Creo draws it.
            try {
                out.put("area", s.EvalArea());
            } catch (Throwable unmeasured) {
                out.put("area", null);
            }
            out.put("bbox", box(s.GetXYZExtents()));
        }
        return out;
    }

    /**
     * +1 when the frame's Z axis points out of the material, -1 when it points in. PTC:
     * a surface's orientation says whether its normal points out of the solid; a datum
     * plane bounds no material and has none.
     */
    private static double outwardSign(Surface s) {
        try {
            SurfaceOrientation o = s.GetOrientation();
            return o != null && o.getValue() == SurfaceOrientation._SURFACEORIENT_INWARD ? -1.0 : 1.0;
        } catch (Throwable unreadable) {
            return 1.0;
        }
    }

    static Map<String, Object> edge(Edge e) throws jxthrowable {
        Map<String, Object> out = Json.map(
                "ref", "edge:" + e.GetId(),
                "kind", "edge",
                "id", e.GetId(),
                "type", null,
                "feature", owner(e.GetFeature()));
        List<Object> surfaces = new ArrayList<>();
        for (Surface side : new Surface[] {e.GetSurface1(), e.GetSurface2()}) {
            if (side != null) {
                surfaces.add(ref(side));
            }
        }
        out.put("surfaces", surfaces);
        Point3D start = e.Eval3DData(0.0).GetPoint();
        Point3D end = e.Eval3DData(1.0).GetPoint();
        out.put("start", point(start));
        out.put("end", point(end));
        out.put("length", e.EvalLength());
        CurveDescriptor curve = e.GetCurveDescriptor();
        if (curve != null) {
            out.put("type", shortName(curve.GetCurveType(), "CURVE_"));
            if (curve instanceof com.ptc.pfc.pfcGeometry.LineDescriptor) {
                out.put("direction", direction(start, end));
            } else if (curve instanceof com.ptc.pfc.pfcGeometry.ArcDescriptor) {
                com.ptc.pfc.pfcGeometry.ArcDescriptor arc = (com.ptc.pfc.pfcGeometry.ArcDescriptor) curve;
                out.put("center", point(arc.GetCenter()));
                out.put("radius", arc.GetRadius());
                out.put("normal", vector(cross(arc.GetVector1(), arc.GetVector2())));
            } else if (curve instanceof com.ptc.pfc.pfcGeometry.CircleDescriptor) {
                com.ptc.pfc.pfcGeometry.CircleDescriptor circle = (com.ptc.pfc.pfcGeometry.CircleDescriptor) curve;
                out.put("center", point(circle.GetCenter()));
                out.put("radius", circle.GetRadius());
                out.put("normal", vector(circle.GetUnitNormal()));
            }
        }
        return out;
    }

    static Map<String, Object> axis(WAxis a) throws jxthrowable {
        Map<String, Object> out = Json.map(
                "ref", ref(a),
                "kind", "axis",
                "id", a.GetId(),
                "name", a.GetName(),
                "feature", owner(a.GetFeature()));
        CurveDescriptor data = a.GetAxisData();
        if (data instanceof com.ptc.pfc.pfcGeometry.LineDescriptor) {
            com.ptc.pfc.pfcGeometry.LineDescriptor line = (com.ptc.pfc.pfcGeometry.LineDescriptor) data;
            out.put("start", point(line.GetEnd1()));
            out.put("end", point(line.GetEnd2()));
            out.put("direction", direction(line.GetEnd1(), line.GetEnd2()));
        }
        return out;
    }

    private static Map<String, Object> owner(Feature f) throws jxthrowable {
        return f == null ? null : Json.map("id", f.GetId(), "name", f.GetName());
    }

    // ------------------------------------------------------------------ geometry.measure

    /**
     * The shortest distance between two references, with the nearest point on each, as
     * Creo's clearance evaluator computes it; {@code interfering} when they touch or cross.
     */
    /**
     * Where a line through the part meets its faces, sorted along it, negative behind its
     * start (ProSolidRayIntersectionCompute, through the native library): a rib's chain is
     * carried along to the faces it joins by it. Changes nothing.
     */
    static Map<String, Object> ray(Map<String, Object> request) throws Exception {
        Solid solid = Creo.part(Creo.session(), Json.string(request, "model"));
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a ray is cast by the native library, which is not loaded: "
                    + Service.sketchLibraryStatus());
        }
        double[] from = triple(request.get("from"), "'from'");
        double[] along = triple(request.get("along"), "'along'");
        String hits = cast(Creo.fileName((com.ptc.pfc.pfcModel.Model) solid).replaceFirst("(?i)\\.prt$", ""), from, along,
                null);
        List<Object> rows = new ArrayList<>();
        for (String one : hits.split(";")) {
            String[] t = one.trim().split("\\s+");
            if (t.length == 4) {
                rows.add(Json.map("distance", Double.parseDouble(t[0]), "point",
                        java.util.Arrays.asList(Double.parseDouble(t[1]), Double.parseDouble(t[2]),
                                Double.parseDouble(t[3]))));
            }
        }
        return Json.map("model", Creo.fileName((com.ptc.pfc.pfcModel.Model) solid), "hits", rows);
    }

    /**
     * Where a ray from a point crosses a part's faces, natively (ProSolidRayIntersectionCompute):
     * "distance x y z;" for each, distance along the ray. Within Creo's default aperture an
     * edge a millimetre off the ray counts as hit, and a face just past its boundary (measured
     * on a 120 mm part); an aperture narrows that.
     */
    static String cast(String part, double[] from, double[] along, Double aperture) throws Exception {
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        if (aperture != null) {
            in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("aperture",
                    com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(String.valueOf(aperture))));
        }
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(part)));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("from",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(from[0] + " " + from[1] + " " + from[2])));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("along",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(along[0] + " " + along[1] + " " + along[2])));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.RAY_FUNCTION, in);
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "the ray could not be cast: toolkit error " + result.GetFunctionReturn(),
                    "toolkit_error", result.GetFunctionReturn()));
        }
        String hits = "";
        com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            if ("hits".equals(out.get(i).GetLabel())) {
                com.ptc.pfc.pfcArgument.ArgValue value = out.get(i).GetValue();
                hits = "ARG_V_ASCII_STRING".equals(Creo.enumName(value.Getdiscr())) ? value.GetASCIIStringValue()
                        : value.GetStringValue();
            }
        }
        return hits;
    }

    private static double[] triple(Object raw, String what) {
        if (!(raw instanceof List) || ((List<?>) raw).size() != 3) {
            throw new Failures.Refusal("E_VALIDATION", what + " is [x, y, z]");
        }
        double[] out = new double[3];
        for (int i = 0; i < 3; i++) {
            Object v = ((List<?>) raw).get(i);
            if (!(v instanceof Number)) {
                throw new Failures.Refusal("E_VALIDATION", what + " is [x, y, z]");
            }
            out[i] = ((Number) v).doubleValue();
        }
        return out;
    }

    static Map<String, Object> measure(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        String from = Json.string(request, "from");
        String to = Json.string(request, "to");
        com.ptc.pfc.pfcInterference.ClearanceData clearance = com.ptc.pfc.pfcInterference.pfcInterference
                .CreateSelectionEvaluator(pfcSelect.SelectionPair_Create(select(solid, from), select(solid, to)))
                .ComputeClearance();
        List<Object> nearest = new ArrayList<>();
        com.ptc.pfc.pfcBase.Point3Ds points = clearance.GetNearestPoints();
        for (int i = 0; points != null && i < points.getarraysize(); i++) {
            nearest.add(point(points.get(i)));
        }
        return Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid),
                "from", from, "to", to, "distance", clearance.GetDistance(),
                "interfering", clearance.GetIsInterfering(), "nearest_points", nearest);
    }

    // ------------------------------------------------------------------ numbers

    /** Display-oriented scalar formatting only; never use for coordinates or directions. */
    static double round(double value) {
        return Math.abs(value) < 1e9 ? Math.round(value * 1e9) / 1e9 : value;
    }

    static List<Object> point(Point3D p) throws jxthrowable {
        return coordinates(p.get(0), p.get(1), p.get(2));
    }

    static List<Object> vector(Vector3D v) throws jxthrowable {
        // Native directions already carry their native scale and effective
        // precision. Renormalizing on read changes the observed values as well.
        return coordinates(v.get(0), v.get(1), v.get(2));
    }

    static List<Object> coordinates(double x, double y, double z) {
        return Arrays.asList(x, y, z);
    }

    static List<Object> vectorBinary64(Vector3D v) throws jxthrowable {
        return binary64(vector(v));
    }

    static List<Object> binary64(List<Object> observed) {
        List<Object> result = new ArrayList<>();
        for (Object value : observed) result.add(Double.toHexString(((Number) value).doubleValue()));
        return result;
    }

    static Map<String, Object> precision() {
        return Json.map("encoding", "IEEE-754 binary64",
                "coordinates", "native accessor values, no decimal rounding",
                "native_directions", "native accessor values, no normalization or decimal rounding",
                "derived_directions", "normalized using binary64 arithmetic, no decimal rounding",
                "serialization", "round-trip decimal; optional native hexadecimal binary64 evidence",
                "display_formatting_used_for_verification", false);
    }

    private static List<Object> scaled(Vector3D v, double sign) throws jxthrowable {
        return coordinates(v.get(0) * sign, v.get(1) * sign, v.get(2) * sign);
    }

    private static List<Object> direction(Point3D a, Point3D b) throws jxthrowable {
        double[] u = unit(b.get(0) - a.get(0), b.get(1) - a.get(1), b.get(2) - a.get(2));
        return coordinates(u[0], u[1], u[2]);
    }

    private static Vector3D cross(Vector3D a, Vector3D b) throws jxthrowable {
        Vector3D out = Vector3D.create();
        out.set(0, a.get(1) * b.get(2) - a.get(2) * b.get(1));
        out.set(1, a.get(2) * b.get(0) - a.get(0) * b.get(2));
        out.set(2, a.get(0) * b.get(1) - a.get(1) * b.get(0));
        return out;
    }

    private static double[] unit(double x, double y, double z) {
        double n = Math.sqrt(x * x + y * y + z * z);
        return n == 0 ? new double[] {0, 0, 0} : new double[] {x / n, y / n, z / n};
    }

    private static List<Object> box(Outline3D box) throws jxthrowable {
        return box == null ? null : Arrays.asList(point(box.get(0)), point(box.get(1)));
    }

    /** SURFACE_PLANE to plane, CURVE_ARC to arc: the words an agent filters by. */
    private static String shortName(Object value, String prefix) {
        String name = Creo.enumName(value);
        if (name == null) {
            return null;
        }
        return (name.startsWith(prefix) ? name.substring(prefix.length()) : name).toLowerCase(Locale.ROOT);
    }
}
