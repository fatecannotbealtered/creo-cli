package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.Vector3D;
import com.ptc.pfc.pfcDrawing.Drawing;
import com.ptc.pfc.pfcGeometry.ArcDescriptor;
import com.ptc.pfc.pfcGeometry.CircleDescriptor;
import com.ptc.pfc.pfcGeometry.CurveDescriptor;
import com.ptc.pfc.pfcGeometry.Edge;
import com.ptc.pfc.pfcGeometry.SplinePoints;
import com.ptc.pfc.pfcGeometry.pfcGeometry;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcView2D.View2D;
import com.ptc.pfc.pfcXSection.XSecCutobjType;
import com.ptc.pfc.pfcXSection.XSection;
import com.ptc.wfc.wfcDrawing.WDrawing;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcView2D.DetailViewInstructions;
import com.ptc.wfc.wfcView2D.DrawingViewSectionAreaType;
import com.ptc.wfc.wfcView2D.Section2DInstructions;
import com.ptc.wfc.wfcView2D.SequenceofSection2DInstructions;
import com.ptc.wfc.wfcView2D.ViewDetailBoundaryType;
import com.ptc.wfc.wfcView2D.WView2D;
import com.ptc.wfc.wfcView2D.wfcView2D;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * The views a drawing needs past general and projected ones: a view sectioned through a
 * plane of its part, as a person turns a projection into section A-A; and a detail view,
 * a region of another view drawn larger inside a circle.
 */
final class Views {
    private static final int SPLINE_POINTS = 32;

    private Views() {
    }

    /**
     * Section a view through a cross-section of its part: the one of that name, or a new
     * planar one through the plane named, made as Creo makes it -- a feature of the part.
     * Returns what was done, for the reply.
     */
    static Map<String, Object> section(Drawing drawing, View2D view, View2D parent, Map<String, Object> section)
            throws Exception {
        Model shown = view.GetModel();
        if (!(shown instanceof Solid)) {
            throw new Failures.Refusal("E_CONFLICT", "the view shows no part or assembly to section");
        }
        Solid solid = (Solid) shown;
        String name = Json.string(section, "name");
        String plane = Json.string(section, "plane", null);
        boolean made = false;
        XSection existing = crossSection(solid, name);
        if (existing == null) {
            if (plane == null) {
                throw new Failures.Refusal("E_NOT_FOUND", Creo.fileName((Model) solid) + " has no cross-section "
                        + name + "; name the plane to make it through");
            }
            ModelItem through = Geometry.item(solid, plane);
            if (through.GetType().getValue() != ModelItemType._ITEM_SURFACE) {
                throw new Failures.Refusal("E_VALIDATION", "a section is cut through a plane: a datum plane's "
                        + "name or a flat surface:<id>");
            }
            Selection pick = pfcSelect.CreateModelItemSelection(through, null);
            ((WSolid) solid).CreatePlanarXSectionWithOptions(name, pick, XSecCutobjType.XSECTYPE_MODEL, null,
                    false, null, null);
            made = true;
        }
        String half = Json.string(section, "half", null);
        Section2DInstructions how = wfcView2D.Section2DInstructions_Create(half == null
                ? DrawingViewSectionAreaType.VIEW_SECTION_AREA_FULL : DrawingViewSectionAreaType.VIEW_SECTION_AREA_HALF, name);
        if (half != null) {
            // A half section: cut on one side of a plane square to the section, whole on the
            // other -- a turned part's outside and inside in one view.
            ModelItem divider = Geometry.item(solid, half);
            if (divider.GetType().getValue() != ModelItemType._ITEM_SURFACE) {
                throw new Failures.Refusal("E_VALIDATION", "a half section is divided by a plane: a datum plane's "
                        + "name or a flat surface:<id>");
            }
            Selection by = pfcSelect.CreateModelItemSelection(divider, null);
            by.SetSelView2D(view);
            how.SetReference(by);
        }
        if (parent != null) {
            how.SetArrowDisplayView(parent);
        }
        ((WView2D) view).SetSection2DInstructions(how);
        view.Regenerate();
        return Json.map("name", name, "plane", plane, "made_in_part", made, "area", half == null ? "full" : "half",
                "half_by", half);
    }

    /**
     * How a view is drawn: "lines", the visible edges, as a drafter draws; "hidden", hidden
     * edges dashed as well; or "shaded". Left alone a view follows the session's display, so
     * one drawing came out shaded and another in lines (measured). Tangent edges are left out:
     * a drawing shows where surfaces meet at a corner, not where they blend.
     */
    static void draw(View2D view, String display) throws jxthrowable {
        com.ptc.pfc.pfcBase.DisplayStyle style = "hidden".equals(display)
                ? com.ptc.pfc.pfcBase.DisplayStyle.DISPSTYLE_HIDDEN_LINE
                : "shaded".equals(display) ? com.ptc.pfc.pfcBase.DisplayStyle.DISPSTYLE_SHADED
                : com.ptc.pfc.pfcBase.DisplayStyle.DISPSTYLE_NO_HIDDEN;
        view.SetDisplay(com.ptc.pfc.pfcView2D.pfcView2D.ViewDisplay_Create(style,
                com.ptc.pfc.pfcBase.TangentEdgeDisplayStyle.TANEDGE_NONE,
                com.ptc.pfc.pfcBase.CableDisplayStyle.CABLEDISP_DEFAULT, false, false, false));
    }

    /** How a view is drawn, as draw names it; anything else by Creo's own name. */
    static String display(View2D view) {
        try {
            int style = view.GetDisplay().GetStyle().getValue();
            if (style == com.ptc.pfc.pfcBase.DisplayStyle._DISPSTYLE_NO_HIDDEN) {
                return "lines";
            }
            if (style == com.ptc.pfc.pfcBase.DisplayStyle._DISPSTYLE_HIDDEN_LINE) {
                return "hidden";
            }
            if (style == com.ptc.pfc.pfcBase.DisplayStyle._DISPSTYLE_SHADED) {
                return "shaded";
            }
            return Creo.enumName(view.GetDisplay().GetStyle()).replaceFirst("^DISPSTYLE_", "").toLowerCase(java.util.Locale.ROOT);
        } catch (Throwable unread) {
            return null;
        }
    }

    /**
     * A section view's model edges: "area", the cut face alone -- a shaft's section through a
     * keyway -- or "total", everything beyond the cut as well, Creo's default. Java has no
     * call for it; the native library's creo_cli_section_edges is ProDrawingView2DSectionAreaSet.
     */
    static void sectionEdges(Drawing drawing, View2D view, String edges) throws Exception {
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a section's edges are set by the native library, which is "
                    + "not loaded: " + Service.sketchLibraryStatus());
        }
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("drawing",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(
                        Creo.fileName(drawing).replaceFirst("(?i)\\.drw$", ""))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("view",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(view.GetName())));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("edges",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(edges)));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.SECTION_EDGES_FUNCTION, in);
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message", "the section's edges could not be "
                    + "set to " + edges + ": toolkit error " + result.GetFunctionReturn(),
                    "toolkit_error", result.GetFunctionReturn()));
        }
        view.Regenerate();
    }

    static XSection crossSection(Solid solid, String name) {
        try {
            return solid.GetCrossSection(name);
        } catch (Throwable absent) {
            return null;
        }
    }

    /** The names of the cross-sections a view is sectioned by, or an empty list. */
    /** How much of a view its section cuts: "full", "half", "local", or null for none. */
    static String sectionArea(View2D view) {
        try {
            SequenceofSection2DInstructions all = ((WView2D) view).GetSection2DInstructions();
            if (all == null || all.getarraysize() == 0) {
                return null;
            }
            return Creo.enumName(all.get(0).GetSectionAreaType()).replaceFirst("^VIEW_SECTION_AREA_", "")
                    .toLowerCase(java.util.Locale.ROOT);
        } catch (Throwable none) {
            return null;
        }
    }

    static List<Object> sectionsOf(View2D view) {
        List<Object> out = new ArrayList<>();
        try {
            SequenceofSection2DInstructions all = ((WView2D) view).GetSection2DInstructions();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                out.add(all.get(i).GetSectionName());
            }
        } catch (Throwable none) {
            // No section.
        }
        return out;
    }

    /**
     * A detail view: the region of a parent view inside a circle of the given radius, in the
     * part's units, around one of its part's edges -- an arc's or circle's centre, a straight
     * edge's middle -- drawn at the view's place and scale. Creo notes it on the parent.
     */
    static View2D detail(Drawing drawing, Map<String, Object> view, Point3D where) throws Exception {
        View2D parent = drawing.GetViewByName(Json.string(view, "parent"));
        if (parent == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(view, "parent"));
        }
        Model shown = parent.GetModel();
        if (!(shown instanceof Solid)) {
            throw new Failures.Refusal("E_CONFLICT", "the parent view shows no part to take a detail of");
        }
        Map<String, Object> detail = Json.object(view.get("detail"), "'view.detail'");
        ModelItem item = Geometry.item((Solid) shown, Json.string(detail, "center"));
        if (item.GetType().getValue() != ModelItemType._ITEM_EDGE) {
            throw new Failures.Refusal("E_VALIDATION", "a detail is centred on an edge:<id> the parent view shows");
        }
        double radius = Json.number(detail, "radius");
        if (!(radius > 0)) {
            throw new Failures.Refusal("E_VALIDATION", "'view.detail.radius' is a positive length");
        }
        // The reference is a point on the edge in the parent view; the boundary must enclose it.
        // Centred on an arc's centre or a line's middle -- or on the point of the edge nearest
        // the one given, as a drafter rings a chamfer at the rim of a shaft whose end circle is
        // seen edge on.
        Selection reference = pfcSelect.CreateModelItemSelection(item, null);
        reference.SetSelView2D(parent);
        double t = 0.5;
        Object near = detail.get("near");
        if (near instanceof List && ((List<?>) near).size() == 3) {
            double[] p = new double[3];
            for (int i = 0; i < 3; i++) {
                p[i] = ((Number) ((List<?>) near).get(i)).doubleValue();
            }
            t = nearest((Edge) item, p);
        }
        reference.SetTParam(t);
        Point3D middle = ((Edge) item).Eval3DData(t).GetPoint();
        Point3D around = middle;
        CurveDescriptor curve = ((Edge) item).GetCurveDescriptor();
        if (near == null && curve instanceof ArcDescriptor) {
            around = ((ArcDescriptor) curve).GetCenter();
        } else if (near == null && curve instanceof CircleDescriptor) {
            around = ((CircleDescriptor) curve).GetCenter();
        }
        double reach = Math.sqrt(Math.pow(middle.get(0) - around.get(0), 2) + Math.pow(middle.get(1) - around.get(1), 2)
                + Math.pow(middle.get(2) - around.get(2), 2));
        if (!(radius > reach)) {
            throw new Failures.Refusal("E_VALIDATION", "the circle must reach the edge: a radius of more than "
                    + Geometry.round(reach));
        }
        // The spline is in drawing coordinates, around the reference (ProDrawingView.h), and
        // closed; a tangent is the circle's derivative in the spline's own parameter.
        Transform3D toScreen = parent.GetTransform();
        Point3D centre = toScreen.TransformPoint(around);
        // The view's scale, from any direction in the part: the depth counts, as a side view
        // looks along the axis the offset takes.
        Point3D rim = toScreen.TransformPoint(offset(around, radius));
        double r = Math.sqrt(Math.pow(rim.get(0) - centre.get(0), 2) + Math.pow(rim.get(1) - centre.get(1), 2)
                + Math.pow(rim.get(2) - centre.get(2), 2));
        SplinePoints points = SplinePoints.create();
        for (int i = 0; i <= SPLINE_POINTS; i++) {
            double a = 2.0 * Math.PI * i / SPLINE_POINTS;
            double speed = 2.0 * Math.PI * r;
            points.append(pfcGeometry.SplinePoint_Create((double) i / SPLINE_POINTS,
                    Drawings.point(centre.get(0) + r * Math.cos(a), centre.get(1) + r * Math.sin(a)),
                    vector(-speed * Math.sin(a), speed * Math.cos(a))));
        }
        DetailViewInstructions how = wfcView2D.DetailViewInstructions_Create(reference,
                pfcGeometry.SplineDescriptor_Create(points));
        how.SetBoundaryType(ViewDetailBoundaryType.DETAIL_BOUNDARY_CIRCLE);
        how.ShowBoundary(true);
        return ((WDrawing) drawing).CreateDetailView(how, where);
    }

    /** The parameter of the point of an edge nearest a point: sampled, then narrowed. */
    private static double nearest(Edge edge, double[] p) throws jxthrowable {
        int samples = 360;
        double best = 0, bestDistance = Double.MAX_VALUE;
        for (int i = 0; i <= samples; i++) {
            double t = (double) i / samples;
            double d = distance(edge.Eval3DData(t).GetPoint(), p);
            if (d < bestDistance) {
                bestDistance = d;
                best = t;
            }
        }
        double low = Math.max(0, best - 1.0 / samples), high = Math.min(1, best + 1.0 / samples);
        for (int i = 0; i < 40; i++) {
            double a = low + (high - low) / 3, b = high - (high - low) / 3;
            if (distance(edge.Eval3DData(a).GetPoint(), p) < distance(edge.Eval3DData(b).GetPoint(), p)) {
                high = b;
            } else {
                low = a;
            }
        }
        return (low + high) / 2;
    }

    private static double distance(Point3D a, double[] p) throws jxthrowable {
        return Math.sqrt(Math.pow(a.get(0) - p[0], 2) + Math.pow(a.get(1) - p[1], 2) + Math.pow(a.get(2) - p[2], 2));
    }

    /** Put the middle of a view's outline at a point on the screen. */
    static void centre(Drawing drawing, View2D view, Point3D where) throws jxthrowable {
        com.ptc.pfc.pfcBase.Outline3D box = view.GetOutline();
        double cx = (box.get(0).get(0) + box.get(1).get(0)) / 2.0;
        double cy = (box.get(0).get(1) + box.get(1).get(1)) / 2.0;
        view.Translate(vector(where.get(0) - cx, where.get(1) - cy));
    }

    /**
     * Refuse a name another view has, before anything is made: SetName answers XToolkitFound
     * only after the view exists (measured), which would leave a view nobody asked for.
     */
    static void requireFreeName(Drawing drawing, String name) throws jxthrowable {
        if (name != null && drawing.GetViewByName(name) != null) {
            throw new Failures.Refusal("E_CONFLICT", "the drawing already has a view named " + name);
        }
    }

    /**
     * Name a new view: as asked, or, when Creo's own name repeats another view's -- it does,
     * for a second projection the same way (measured) -- with the next free number.
     */
    static void name(Drawing drawing, View2D made, String asked) throws jxthrowable {
        if (asked != null) {
            made.SetName(asked);
            return;
        }
        String given = made.GetName();
        int same = 0;
        com.ptc.pfc.pfcView2D.View2Ds all = drawing.List2DViews();
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            if (given.equals(all.get(i).GetName())) {
                same++;
            }
        }
        if (same < 2) {
            return;
        }
        String stem = given.replaceFirst("_[0-9]+$", "");
        for (int n = 2; n < 1000; n++) {
            if (drawing.GetViewByName(stem + "_" + n) == null) {
                made.SetName(stem + "_" + n);
                return;
            }
        }
    }

    /** Move a view so the middle of its outline sits at a point on the sheet. */
    static Map<String, Object> move(Map<String, Object> request) throws Exception {
        com.ptc.pfc.pfcSession.Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        View2D view = drawing.GetViewByName(Json.string(request, "view"));
        if (view == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(request, "view"));
        }
        Object raw = request.get("at");
        if (!(raw instanceof List) || ((List<?>) raw).size() != 2) {
            throw new Failures.Refusal("E_VALIDATION", "'at' is [x, y] on the sheet");
        }
        List<?> at = (List<?>) raw;
        if (!(at.get(0) instanceof Double) || !(at.get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'at' is [x, y] on the sheet");
        }
        Point3D target = Drawings.toScreen(drawing, view.GetSheetNumber(), (Double) at.get(0), (Double) at.get(1));
        centre(drawing, view, target);
        drawing.RegenerateSheet(view.GetSheetNumber());
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("view", Drawings.viewRow(drawing, view));
        return out;
    }

    private static Point3D offset(Point3D p, double dx) throws jxthrowable {
        Point3D q = Point3D.create();
        q.set(0, p.get(0) + dx);
        q.set(1, p.get(1));
        q.set(2, p.get(2));
        return q;
    }

    private static Vector3D vector(double x, double y) throws jxthrowable {
        Vector3D v = Vector3D.create();
        v.set(0, x);
        v.set(1, y);
        v.set(2, 0.0);
        return v;
    }

    /** A part's cross-sections: name and the plane each is cut through, for model show. */
    static List<Object> crossSections(Solid solid) {
        List<Object> out = new ArrayList<>();
        try {
            com.ptc.pfc.pfcXSection.XSections all = solid.ListCrossSections();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                XSection x = all.get(i);
                // A section feature cuts through a plane of its own (GetPlane answers that one,
                // measured); the datum it was placed on is its parent.
                String plane = null;
                try {
                    com.ptc.pfc.pfcFeature.Features parents =
                            ((com.ptc.wfc.wfcXSection.WXSection) x).GetFeature().ListParents();
                    for (int k = 0; parents != null && k < parents.getarraysize(); k++) {
                        if (parents.get(k).GetFeatType() == com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_DATUM_PLANE) {
                            plane = parents.get(k).GetName();
                        }
                    }
                } catch (Throwable unknown) {
                    // Reported as null.
                }
                out.add(Json.map("name", x.GetName(), "plane", plane));
            }
        } catch (Throwable none) {
            // No cross-sections.
        }
        return out;
    }
}
