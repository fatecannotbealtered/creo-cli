package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.Matrix3D;
import com.ptc.pfc.pfcBase.Outline3D;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.pfcBase;
import com.ptc.pfc.pfcDrawing.Drawing;
import com.ptc.pfc.pfcDrawing.DrawingCreateOption;
import com.ptc.pfc.pfcDrawing.DrawingCreateOptions;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModel2D.Model2D;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcView2D.View2D;
import com.ptc.pfc.pfcView2D.pfcView2D;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import static com.fateforge.creocli.service.NativeReadTrace.run;

/**
 * drawing.create, drawing.add-view, drawing.annotate: a drawing of a part or assembly from
 * one of Creo's templates, its views, and the model's own dimensions shown on them.
 *
 * <p>Sheet coordinates are the drawing's own units, measured from the sheet's lower left
 * corner, as the drawing reports them.
 */
final class Drawings {

    /** Creo's shipped templates, by sheet: a0..a4 (ISO) and a..f (ANSI). */
    private static final String[] SHEETS = {"a0", "a1", "a2", "a3", "a4", "a", "b", "c", "d", "e", "f"};

    private Drawings() {
    }

    // Keep the SDK's checked exception contract at existing typed catch sites. The trace
    // core itself preserves the original Throwable without requiring SDK dependencies.
    private static <T> T call(String getter, NativeReadTrace.Call<T> body) throws jxthrowable {
        return NativeReadTrace.call(getter, body);
    }

    static Drawing drawing(Session session, String raw) throws jxthrowable {
        NativeReadTrace.known("requested_drawing", raw);
        Model model = call("Creo.model[delegated_lookup_internal_getters_uninstrumented]", () -> Creo.model(session, raw.contains(".") ? raw : raw + ".drw"));
        ModelType type = call("Model.GetType(drawing_lookup)", () -> model.GetType());
        if (call("ModelType.getValue(drawing_lookup)", () -> type.getValue()) != ModelType._MDL_DRAWING) {
            throw new Failures.Refusal("E_VALIDATION", fileNameTraced(model) + " is not a drawing");
        }
        NativeReadTrace.known("actual_drawing", fileNameTraced(model));
        return (Drawing) model;
    }

    /**
     * Bring the drawing's window forward. Creo builds views and shows annotations only in the
     * drawing on screen: otherwise ProAnnotationByViewShow answers PRO_TK_NOT_DISPLAYED.
     */
    static void front(Session session, Drawing drawing) throws jxthrowable {
        com.ptc.pfc.pfcWindow.Window found;
        try { found = call("Session.GetModelWindow(drawing_front)", () -> session.GetModelWindow((Model) drawing)); }
        catch (Throwable none) {
            NativeReadTrace.rethrowFatal(none);
            found = null;
        }
        final com.ptc.pfc.pfcWindow.Window window = found;
        if (window == null) {
            try {
                var created = call("Session.CreateModelWindow(drawing_front)", () -> session.CreateModelWindow((Model) drawing));
                run("Model.Display(drawing_front)", () -> ((Model) drawing).Display());
                run("Window.Activate(created_drawing)", () -> created.Activate());
            } catch (jxthrowable noWindow) { NativeReadTrace.rethrowFatal(noWindow); }
        } else {
            run("Window.Activate(drawing_front)", () -> window.Activate());
        }
    }

    static void repaintTraced(Session session) {
        NativeReadTrace.known("repaint_status", "not_entered");
        try {
            var window = call("Session.GetCurrentWindow(repaint)", () -> session.GetCurrentWindow());
            if (window != null) {
                run("Window.Repaint", () -> window.Repaint());
                NativeReadTrace.known("repaint_status", "native_returned");
            } else {
                NativeReadTrace.known("repaint_status", "no_current_window");
            }
        } catch (jxthrowable ignored) {
            NativeReadTrace.rethrowFatal(ignored);
            NativeReadTrace.known("repaint_status", "native_threw_cosmetic_error");
        }
    }

    static String fileNameTraced(Model model) throws jxthrowable {
        return model == null ? null : Creo.plainName(call("Model.GetFileName", () -> model.GetFileName()));
    }

    private static String originTraced(Model model) throws jxthrowable {
        try {
            String origin = call("Model.GetOrigin", () -> model.GetOrigin());
            return origin == null || origin.trim().isEmpty() ? null : origin;
        } catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native GetOrigin failed; storage directory is unproved");
        }
    }

    private static Boolean modifiedTraced(Model model) {
        try { return call("Model.GetIsModified", () -> model.GetIsModified()); }
        catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            return null;
        }
    }

    /** Complete window activation in its own toolkit call before moving existing views. */
    static Map<String, Object> activate(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        front(session, drawing);
        return Json.map("model", Creo.fileName((Model) drawing), "window_activated", true);
    }

    // ------------------------------------------------------------------ drawing.create

    /**
     * A drawing of a model in session, from a template: one of Creo's by sheet size, or a
     * template file. What the template brings -- format, views -- comes with it; when it
     * brings no views, a front view, its top and side projections and an isometric view are
     * laid out. Asked for a projection other than the template's -- Creo's sheets are third
     * angle, a drawing to ISO E, GB or DIN first angle -- or for no views, the template's
     * views go: views are laid out by the projection in force when they are made.
     */
    static Map<String, Object> create(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        String raw = Json.string(request, "name");
        Creo.Name name = Creo.name(raw.contains(".") ? raw : raw + ".drw");
        if (name.type.getValue() != ModelType._MDL_DRAWING) {
            throw new Failures.Refusal("E_VALIDATION", "'" + name.fileName() + "' is not a drawing name");
        }
        if (Creo.find(session, name) != null) {
            throw new Failures.Refusal("E_CONFLICT", "a drawing named " + name.base + " is already in session");
        }
        Solid solid = Creo.solid(session, Json.string(request, "of"));
        String template = template(session, request);
        String projection = Json.string(request, "projection", null);
        if (projection != null && !"first_angle".equals(projection) && !"third_angle".equals(projection)) {
            throw new Failures.Refusal("E_VALIDATION", "'projection' is first_angle or third_angle");
        }
        String views = Json.string(request, "views", "template");
        if (!java.util.Arrays.asList("template", "standard", "none").contains(views)) {
            throw new Failures.Refusal("E_VALIDATION", "'views' is template, standard or none");
        }
        DrawingCreateOptions options = DrawingCreateOptions.create();
        options.append(DrawingCreateOption.DRAWINGCREATE_DISPLAY_DRAWING);
        Drawing drawing = session.CreateDrawingFromTemplate(name.base, template, ((Model) solid).GetDescr(), options);
        Map<String, String> setup = setUp(drawing, Json.string(request, "sheet", null) != null, projection);
        String lettering = setup.get("default_annotation_font");
        front(session, drawing);
        List<Object> laid = new ArrayList<>();
        List<Object> replaced = new ArrayList<>();
        boolean otherProjection = projection != null && !projection.equals(setup.get("template_projection"));
        if (new View2Ds(drawing).count() > 0 && (!"template".equals(views) || otherProjection)) {
            replaced = removeViews(drawing);
        }
        // Views are laid out by drawing.lay-out, called next: in the call that made the
        // drawing Creo refuses to make a view or move one (ProDrawingGeneralviewCreate, bad
        // inputs; ProDrawingViewMove, general error -- measured on Creo 13.4), and makes the
        // same views in the next call.
        boolean layOut = !"none".equals(views) && new View2Ds(drawing).count() == 0;
        String display = Json.string(request, "display", "lines");
        com.ptc.pfc.pfcView2D.View2Ds every = drawing.List2DViews();
        for (int i = 0; every != null && i < every.getarraysize(); i++) {
            Views.draw(every.get(i), display);
        }
        // Creo's standard sheets bring their views at 1:1, a small part lost in a corner; a
        // drafter picks the sheet's scale from the preferred ones. A template of the user's
        // keeps its own.
        Map<String, Object> scaled;
        if (request.get("scale") instanceof Number) {
            // The scale the caller planned the sheet for.
            int sheet = drawing.GetCurrentSheetNumber();
            double asked = ((Number) request.get("scale")).doubleValue();
            double before = drawing.GetSheetScale(sheet, (Model) solid);
            drawing.SetSheetScale(sheet, asked, (Model) solid);
            regenerateQuietly(drawing, sheet);
            scaled = Json.map("scale", asked, "label", scaleLabel(asked), "before", before, "meaning", "as asked");
        } else {
            scaled = Json.string(request, "sheet", null) != null || !laid.isEmpty()
                    ? fitPreferred(drawing, drawing.GetCurrentSheetNumber(), (Model) solid) : null;
        }
        Map<String, Object> out = summary(drawing);
        out.put("template", template);
        out.put("projection", setup.get("projection_type"));
        out.put("views_replaced", replaced);
        out.put("lay_out", layOut);
        out.put("views_laid_out", laid);
        out.put("lettering", lettering);
        out.put("scale_labels", setup.get("view_scale_format"));
        out.put("scale_chosen", scaled);
        return out;
    }

    /**
     * A standard sheet's drawing set up as a drafter's: lettered in Creo's own font and with
     * scales labelled 2:1.
     *
     * <p>Creo writes some of a drawing's text itself -- a view's scale label -- in the
     * session's language, but its standard sheet templates letter in ISONorm
     * (isonormlt-regular.ttf), which has no Chinese, Japanese or Korean glyphs: on a Chinese
     * Creo the label came out as boxes. Creo's own font is localized with the session
     * (text/chinese_cn/font.ndx adds chfnt.fnt to ascii.fnt). And the templates label a
     * view's scale as a decimal, 2,000 where a drawing says 2:1 (view_scale_format).
     *
     * <p>Java sets a drawing's detail options by importing a drawing setup file, the drawing's
     * own and not the session's configuration; they are read back by exporting one, and
     * returned by name.
     */
    private static Map<String, String> setUp(Drawing drawing, boolean sheet, String projection) throws Exception {
        Map<String, String> read = new java.util.HashMap<>();
        String was = options(drawing).get("projection_type");
        read.put("template_projection", was == null ? null : was.toLowerCase(Locale.ROOT));
        StringBuilder lines = new StringBuilder();
        if (sheet) {
            lines.append("default_annotation_font font\nview_scale_format ratio_colon\nview_scale_denominator 1000\n");
        }
        if (projection != null) {
            lines.append("projection_type ").append(projection.toUpperCase(Locale.ROOT)).append("\n");
        }
        if (lines.length() > 0) {
            File setup = File.createTempFile("creo-cli-setup-", ".dtl");
            try {
                java.nio.file.Files.writeString(setup.toPath(), lines.toString(), java.nio.charset.StandardCharsets.US_ASCII);
                drawing.Import(setup.getPath(), com.ptc.pfc.pfcModel.pfcModel.DWGSetupImportInstructions_Create());
            } finally {
                setup.delete();
            }
        }
        Map<String, String> now = options(drawing);
        for (String key : new String[] {"default_annotation_font", "view_scale_format", "projection_type"}) {
            String value = now.get(key);
            read.put(key, value == null ? null : "projection_type".equals(key) ? value.toLowerCase(Locale.ROOT) : value);
        }
        return read;
    }

    /** The drawing's detail options by name, as an exported drawing setup file gives them. */
    static Map<String, String> options(Drawing drawing) throws Exception {
        File check = File.createTempFile("creo-cli-setup-", ".dtl");
        Map<String, String> read = new java.util.HashMap<>();
        try {
            check.delete();
            var instructions = call("pfcModel.DWGSetupExportInstructions_Create", () -> com.ptc.pfc.pfcModel.pfcModel.DWGSetupExportInstructions_Create());
            run("Drawing.Export(drawing_setup)", () -> drawing.Export(check.getPath(), instructions));
            for (String line : java.nio.file.Files.readAllLines(check.toPath(), java.nio.charset.StandardCharsets.ISO_8859_1)) {
                String[] words = line.trim().split("\\s+");
                if (words.length >= 2) {
                    read.put(words[0].toLowerCase(Locale.ROOT), words[1]);
                }
            }
            return read;
        } finally {
            check.delete();
        }
    }

    // ------------------------------------------------------------------ drawing.lay-out

    /**
     * The standard views of a drawing that has none, by its projection: FRONT, TOP, the side
     * view and ISOMETRIC; then drawn as asked and scaled as drawing.create scales a sheet.
     * drawing create calls it in the call after the one that made the drawing.
     */
    static Map<String, Object> layOut(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        front(session, drawing);
        if (new View2Ds(drawing).count() > 0) {
            throw new Failures.Refusal("E_CONFLICT", "the drawing has views already");
        }
        Model model = drawing.GetCurrentSolid();
        if (!(model instanceof Solid)) {
            throw new Failures.Refusal("E_CONFLICT", "the drawing shows no part or assembly to lay out views of");
        }
        String projection = options(drawing).get("projection_type");
        List<View2D> views = new ArrayList<>();
        List<Object> laid = standardViews(drawing, (Solid) model, projection, views);
        String display = Json.string(request, "display", "lines");
        for (View2D view : views) {
            Views.draw(view, display);
        }
        Double asked = request.get("scale") instanceof Number ? ((Number) request.get("scale")).doubleValue() : null;
        Map<String, Object> scaled = arrange(drawing, model, projection, asked, views);
        if (Boolean.TRUE.equals(scaled.get("isometric_left_out"))) {
            laid.remove(laid.size() - 1);
        }
        Creo.repaint(session);
        Map<String, Object> out = summary(drawing);
        out.put("projection", projection == null ? null : projection.toLowerCase(Locale.ROOT));
        out.put("views_laid_out", laid);
        out.put("scale_chosen", scaled);
        return out;
    }

    /** Every view of a new drawing removed -- those taken from another first; their names. */
    private static List<Object> removeViews(Drawing drawing) throws jxthrowable {
        List<Object> names = new ArrayList<>();
        for (int pass = 0; pass < 3; pass++) {
            com.ptc.pfc.pfcView2D.View2Ds all = drawing.List2DViews();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                View2D view = all.get(i);
                boolean taken = false;
                try {
                    taken = ((com.ptc.wfc.wfcView2D.WView2D) view).GetParentView() != null;
                } catch (Throwable unknown) {
                    NativeReadTrace.rethrowFatal(unknown);
                    // Taken as a view of its own.
                }
                if (pass == 0 && !taken) {
                    continue;
                }
                String gone = view.GetName();
                try {
                    view.Delete(Boolean.FALSE);
                    names.add(gone);
                } catch (Throwable stays) {
                    NativeReadTrace.rethrowFatal(stays);
                    // Tried again on the next pass, once the views taken from it are gone.
                }
            }
        }
        return names;
    }

    /**
     * The template by name, which is how CreateDrawingFromTemplate takes it: a full path is
     * refused as too long (XStringTooLong, measured on Creo 13.4). Creo finds its own sheet
     * templates by name; a template of the user's must sit in Creo's working directory.
     */
    private static String template(Session session, Map<String, Object> request) throws jxthrowable {
        String path = Json.string(request, "template", null);
        String sheet = Json.string(request, "sheet", null);
        if ((path == null) == (sheet == null)) {
            throw new Failures.Refusal("E_VALIDATION", "give exactly one of 'sheet' (a0..a4, a..f) or 'template'");
        }
        File file;
        if (sheet != null) {
            if (!java.util.Arrays.asList(SHEETS).contains(sheet.toLowerCase(Locale.ROOT))) {
                throw new Failures.Refusal("E_VALIDATION", "'sheet' is one of a0, a1, a2, a3, a4, a, b, c, d, e, f");
            }
            file = new File(new File(ModelOps.creoCommonFiles(), "templates"), sheet.toLowerCase(Locale.ROOT) + "_drawing.drw");
        } else {
            file = new File(path);
            File cwd = new File(session.GetCurrentDirectory());
            if (!cwd.getAbsoluteFile().equals(file.getAbsoluteFile().getParentFile())) {
                throw new Failures.Refusal("E_VALIDATION", "a drawing template of your own must be in Creo's working "
                        + "directory, " + cwd);
            }
        }
        if (!file.isFile()) {
            throw new Failures.Refusal("E_NOT_FOUND", "drawing template " + file + " does not exist");
        }
        return file.getName().replaceFirst("(?i)\\.drw(\\.[0-9]+)?$", "");
    }

    /** A front view, its top and right projections, and an isometric view, fitted to the sheet. */
    private static List<Object> standardViews(Drawing drawing, Solid solid, String projection, List<View2D> views)
            throws Exception {
        int sheet = drawing.GetCurrentSheetNumber();
        double w = drawing.GetSheetInfo(sheet).GetWidth();
        double h = drawing.GetSheetInfo(sheet).GetHeight();
        // A projection shows the part as seen from the side it is placed on in third angle
        // (ASME, JIS) and from the opposite side in first angle (ISO E, GB, DIN): the view
        // from above goes above the front, or below it; the view to the front's right is the
        // part seen from the right, or from the left. The lower right corner is left for a
        // title block.
        boolean first = "first_angle".equalsIgnoreCase(projection);
        double row = first ? 0.62 : 0.4;
        List<Object> made = new ArrayList<>();
        Model model = (Model) solid;
        View2D front = general(drawing, model, sheet, toScreen(drawing, sheet, w * 0.28, h * row), "front");
        named(drawing, front, "FRONT", made);
        View2D side = drawing.CreateView(pfcView2D.ProjectionViewCreateInstructions_Create(front,
                toScreen(drawing, sheet, w * 0.6, h * row)));
        named(drawing, side, first ? "LEFT" : "RIGHT", made);
        View2D above = drawing.CreateView(pfcView2D.ProjectionViewCreateInstructions_Create(front,
                toScreen(drawing, sheet, w * 0.28, h * (first ? 0.22 : 0.8))));
        named(drawing, above, "TOP", made);
        View2D iso = general(drawing, model, sheet, toScreen(drawing, sheet, w * 0.85, h * 0.8), "isometric");
        named(drawing, iso, "ISOMETRIC", made);
        views.addAll(java.util.Arrays.asList(front, side, above, iso));
        return made;
    }

    /**
     * The standard views placed as a drafter places them: the front in the top left corner
     * (bottom left in third angle), the view from above beside it below (above), the side view
     * on its right, each a dimension's room from the next and the sheet's edge, clear of the
     * title block's corner -- at the scale asked, or the largest preferred one at which they
     * fit. The isometric view goes into the top right corner, or below the side view, where
     * it fits, and is left out where it does not. Within the call that sets a scale the views
     * answer their old outlines (measured), so their sizes at the new scale are predicted
     * from the old ones, grown about their middles, and only their middles are moved.
     */
    private static Map<String, Object> arrange(Drawing drawing, Model model, String projection, Double asked,
                                               List<View2D> views) throws jxthrowable {
        int sheet = drawing.GetCurrentSheetNumber();
        double w = drawing.GetSheetInfo(sheet).GetWidth();
        double h = drawing.GetSheetInfo(sheet).GetHeight();
        double margin = 0.05 * Math.min(w, h);
        double gap = 0.08 * Math.min(w, h);
        // The title block's corner: 180 across and 32 high, 5 in, and a little room above it.
        double[] corner = {w - 5 - 180 - 2, 0, w, 5 + 32 + 4};
        boolean first = "first_angle".equalsIgnoreCase(projection);
        double before = drawing.GetSheetScale(sheet, model);
        double[][] sizes = new double[4][];
        for (int i = 0; i < 4; i++) {
            sizes[i] = size(drawing, sheet, views.get(i));
        }
        double[] tried = asked != null ? new double[] {asked} : PREFERRED_SCALES;
        double[][] place = null;
        double chosen = before;
        for (double scale : tried) {
            double k = scale / before;
            double fw = sizes[0][0] * k, fh = sizes[0][1] * k;
            double sw = sizes[1][0] * k, sh = sizes[1][1] * k;
            double tw = sizes[2][0] * k, th = sizes[2][1] * k;
            double column = Math.max(fw, tw);
            double fx = margin + column / 2;
            double fy;
            double ty;
            if (first) {
                fy = h - margin - fh / 2;
                ty = fy - fh / 2 - gap - th / 2;
            } else {
                // Third angle: the view from above on top; the front's row below it.
                ty = h - margin - th / 2;
                fy = ty - th / 2 - gap - fh / 2;
            }
            double sx = fx + fw / 2 + gap + sw / 2;
            double[][] boxes = {box(fx, fy, fw, fh), box(sx, fy, sw, sh), box(fx, ty, tw, th)};
            boolean fits = true;
            for (double[] b : boxes) {
                fits &= b[0] >= margin && b[1] >= margin && b[2] <= w - margin && b[3] <= h - margin && !overlap(b, corner, 0);
            }
            if (fits || asked != null) {
                place = new double[][] {{fx, fy}, {sx, fy}, {fx, ty}, null};
                double iw = sizes[3][0] * k, ih = sizes[3][1] * k;
                double[][] spots = {{w - margin - iw / 2, h - margin - ih / 2},
                        {w - margin - iw / 2, fy - sh / 2 - gap - ih / 2}};
                for (double[] spot : spots) {
                    double[] b = box(spot[0], spot[1], iw, ih);
                    boolean clear = b[0] >= margin && b[1] >= margin && b[2] <= w - margin && b[3] <= h - margin
                            && !overlap(b, corner, 0);
                    for (double[] other : boxes) {
                        clear &= !overlap(b, other, gap / 2);
                    }
                    if (clear) {
                        place[3] = spot;
                        break;
                    }
                }
                chosen = scale;
                break;
            }
        }
        if (place == null) {
            // No preferred scale fits: the smallest, as fitPreferred keeps the sheet's.
            return Json.map("scale", before, "label", scaleLabel(before), "before", before, "meaning",
                    "kept: no preferred scale fits the standard views", "isometric_left_out", false);
        }
        if (Math.abs(chosen - before) > 1e-9) {
            drawing.SetSheetScale(sheet, chosen, model);
            regenerateQuietly(drawing, sheet);
        }
        for (int i = 0; i < 4; i++) {
            if (place[i] != null) {
                Views.centre(drawing, views.get(i), toScreen(drawing, sheet, place[i][0], place[i][1]));
            }
        }
        boolean leftOut = place[3] == null;
        if (leftOut) {
            views.get(3).Delete(Boolean.FALSE);
        }
        regenerateQuietly(drawing, sheet);
        return Json.map("scale", chosen, "label", scaleLabel(chosen), "before", before, "meaning",
                asked != null ? "as asked" : "the largest of ISO 5455's preferred scales at which the front, top and "
                        + "side views fit, " + Math.round(margin) + " clear of the sheet's edge, " + Math.round(gap)
                        + " apart and clear of the title block's corner",
                "isometric_left_out", leftOut);
    }

    /** A view's width and height on the sheet, at the sheet's present scale. */
    private static double[] size(Drawing drawing, int sheet, View2D view) throws jxthrowable {
        Outline3D box = view.GetOutline();
        Transform3D toSheet = drawing.GetSheetTransform(sheet);
        List<Object> a = onSheet(toSheet, box.get(0));
        List<Object> b = onSheet(toSheet, box.get(1));
        return new double[] {Math.abs(((Number) b.get(0)).doubleValue() - ((Number) a.get(0)).doubleValue()),
                Math.abs(((Number) b.get(1)).doubleValue() - ((Number) a.get(1)).doubleValue())};
    }

    private static double[] box(double cx, double cy, double width, double height) {
        return new double[] {cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2};
    }

    private static boolean overlap(double[] a, double[] b, double room) {
        return a[0] < b[2] + room && b[0] < a[2] + room && a[1] < b[3] + room && b[1] < a[3] + room;
    }

    /** A general view of the model, its failure reported with what it was given. */
    private static View2D general(Drawing drawing, Model model, int sheet, Point3D where, String orientation)
            throws Exception {
        Transform3D turned = orientation((Solid) model, orientation);
        try {
            return drawing.CreateView(pfcView2D.GeneralViewCreateInstructions_Create(model, sheet, where, turned));
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            Map<String, Object> detail = Failures.error(failure);
            detail.put("view", orientation);
            detail.put("location", java.util.Arrays.asList(where.get(0), where.get(1), where.get(2)));
            detail.put("sheet", sheet);
            throw new Service.ToolkitFailure(detail);
        }
    }

    /** A laid out view named for what it shows, the same whatever language Creo speaks. */
    private static void named(Drawing drawing, View2D view, String name, List<Object> made) throws jxthrowable {
        try {
            if (drawing.GetViewByName(name) == null) {
                view.SetName(name);
            }
        } catch (Throwable keeps) {
            NativeReadTrace.rethrowFatal(keeps);
            // Keeps Creo's own name.
        }
        made.add(view.GetName());
    }

    /** The drawing scales ISO 5455 prefers, largest first. */
    private static final double[] PREFERRED_SCALES = {50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01};

    /**
     * The sheet's scale as a drafter picks it: the largest preferred scale at which every
     * view lies on the sheet clear of its edge, with room between views for their
     * dimensions -- predicted from each view's box grown about its middle, then read back
     * once set, and the next smaller scale taken if Creo laid the views out otherwise.
     */
    private static Map<String, Object> fitPreferred(Drawing drawing, int sheet, Model solid) throws jxthrowable {
        double w = drawing.GetSheetInfo(sheet).GetWidth();
        double h = drawing.GetSheetInfo(sheet).GetHeight();
        double before = drawing.GetSheetScale(sheet, solid);
        double margin = 0.05 * Math.min(w, h);
        double gap = 0.08 * Math.min(w, h);
        List<double[]> boxes = viewBoxes(drawing, sheet);
        if (boxes.isEmpty() || before <= 0) {
            return null;
        }
        String why = "every view on the sheet, " + Math.round(margin) + " clear of its edge and "
                + Math.round(gap) + " apart for dimensions";
        for (double s : PREFERRED_SCALES) {
            if (!fits(boxes, s / before, w, h, margin, gap)) {
                continue;
            }
            if (Math.abs(s - before) > 1e-9) {
                // The views' outlines read back grown about their middles, as predicted -- in
                // the next call: within this one Creo still answers the old ones, so the caller
                // reads them back.
                drawing.SetSheetScale(sheet, s, solid);
                regenerateQuietly(drawing, sheet);
            }
            return Json.map("scale", s, "label", scaleLabel(s), "before", before, "meaning",
                    "the largest of ISO 5455's preferred scales with " + why);
        }
        return Json.map("scale", before, "label", scaleLabel(before), "before", before, "meaning",
                "kept: no preferred scale has " + why);
    }

    /**
     * A sheet regenerated after its scale changed. Measured on Creo 13.4: on a sheet whose
     * views came with Creo's template, RegenerateSheet raised XToolkitGeneralError although
     * the new scale had taken effect -- the views read back grown, where they were predicted.
     * What counts is that read-back, so a refusal here is not a failure.
     */
    private static void regenerateQuietly(Drawing drawing, int sheet) {
        try {
            drawing.RegenerateSheet(sheet);
            return;
        } catch (Throwable refused) {
            NativeReadTrace.rethrowFatal(refused);
            // Then the drawing as a whole, so its views' outlines are read back anew.
        }
        try {
            drawing.Regenerate();
        } catch (Throwable alsoRefused) {
            NativeReadTrace.rethrowFatal(alsoRefused);
            // The views are read back next.
        }
        try {
            com.ptc.pfc.pfcView2D.View2Ds views = drawing.List2DViews();
            for (int i = 0; views != null && i < views.getarraysize(); i++) {
                if (views.get(i).GetSheetNumber() == sheet) {
                    views.get(i).Regenerate();
                }
            }
        } catch (Throwable viewsRefused) {
            NativeReadTrace.rethrowFatal(viewsRefused);
            // As above.
        }
    }

    private static boolean fits(List<double[]> boxes, double k, double w, double h, double margin, double gap) {
        List<double[]> grown = new ArrayList<>();
        for (double[] b : boxes) {
            double cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
            double hx = (b[2] - b[0]) / 2 * k, hy = (b[3] - b[1]) / 2 * k;
            double[] g = {cx - hx, cy - hy, cx + hx, cy + hy};
            if (g[0] < margin || g[1] < margin || g[2] > w - margin || g[3] > h - margin) {
                return false;
            }
            grown.add(g);
        }
        for (int i = 0; i < grown.size(); i++) {
            for (int j = i + 1; j < grown.size(); j++) {
                double[] a = grown.get(i), b = grown.get(j);
                boolean apart = a[2] + gap <= b[0] || b[2] + gap <= a[0] || a[3] + gap <= b[1] || b[3] + gap <= a[1];
                if (!apart) {
                    return false;
                }
            }
        }
        return true;
    }

    private static List<double[]> viewBoxes(Drawing drawing, int sheet) throws jxthrowable {
        List<double[]> out = new ArrayList<>();
        com.ptc.pfc.pfcView2D.View2Ds views = drawing.List2DViews();
        Transform3D toSheet = drawing.GetSheetTransform(sheet);
        for (int i = 0; views != null && i < views.getarraysize(); i++) {
            if (views.get(i).GetSheetNumber() != sheet) {
                continue;
            }
            Outline3D box = views.get(i).GetOutline();
            Point3D lo = toSheet.TransformPoint(box.get(0));
            Point3D hi = toSheet.TransformPoint(box.get(1));
            out.add(new double[] {Math.min(lo.get(0), hi.get(0)), Math.min(lo.get(1), hi.get(1)),
                Math.max(lo.get(0), hi.get(0)), Math.max(lo.get(1), hi.get(1))});
        }
        return out;
    }

    static String scaleLabel(double s) {
        if (s >= 1) {
            return (Math.abs(s - Math.rint(s)) < 1e-9 ? String.valueOf((long) Math.rint(s)) : String.valueOf(s)) + ":1";
        }
        double inverse = 1 / s;
        return "1:" + (Math.abs(inverse - Math.rint(inverse)) < 1e-6 ? String.valueOf((long) Math.rint(inverse))
                : String.valueOf(inverse));
    }

    // ------------------------------------------------------------------ drawing.add-view

    static Map<String, Object> addView(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        front(session, drawing);
        Map<String, Object> view = Json.object(request.get("view"), "'view'");
        List<?> at = (List<?>) view.get("at");
        if (at == null || at.size() != 2 || !(at.get(0) instanceof Double) || !(at.get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'view.at' is [x, y] on the sheet");
        }
        Point3D where = toScreen(drawing, drawing.GetCurrentSheetNumber(), (Double) at.get(0), (Double) at.get(1));
        String kind = Json.string(view, "type");
        String asked = Json.string(view, "name", null);
        Views.requireFreeName(drawing, asked);
        // A view added never changes the sheet's scale. Creo picks one for the first view on
        // an empty sheet (measured: 1:2 for a 160 mm shaft on an A3 sheet set to 1:1).
        int sheetNumber = drawing.GetCurrentSheetNumber();
        Model drawn = drawing.GetCurrentSolid();
        boolean empty = new View2Ds(drawing).count() == 0;
        Double sheetScale = null;
        try {
            sheetScale = drawn == null ? null : drawing.GetSheetScale(sheetNumber, drawn);
        } catch (Throwable unread) {
            NativeReadTrace.rethrowFatal(unread);
            // Nothing to keep.
        }
        View2D made;
        View2D parent = null;
        if ("projection".equals(kind)) {
            parent = drawing.GetViewByName(Json.string(view, "parent"));
            if (parent == null) {
                throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(view, "parent"));
            }
            made = drawing.CreateView(pfcView2D.ProjectionViewCreateInstructions_Create(parent, where));
        } else if ("detail".equals(kind)) {
            made = Views.detail(drawing, view, where);
        } else if ("general".equals(kind)) {
            Model model = drawing.GetCurrentSolid();
            if (model == null) {
                throw new Failures.Refusal("E_CONFLICT", "the drawing shows no model to take a view of");
            }
            Transform3D turned = orientation((Solid) model, Json.string(view, "orientation", "front"));
            boolean exploded = Json.bool(view, "exploded", false);
            if (exploded && model.GetType().getValue() != com.ptc.pfc.pfcModel.ModelType._MDL_ASSEMBLY) {
                throw new Failures.Refusal("E_VALIDATION", "a view is exploded from an assembly, not "
                        + Creo.fileName(model));
            }
            try {
                com.ptc.pfc.pfcView2D.GeneralViewCreateInstructions how =
                        pfcView2D.GeneralViewCreateInstructions_Create(model, drawing.GetCurrentSheetNumber(), where,
                                turned);
                if (exploded) {
                    // Request only the exploded display switch. This does not select or
                    // prove the named Assembly explode state held by the drawing view.
                    how.SetExploded(true);
                }
                made = drawing.CreateView(how);
            } catch (Throwable failure) {
                NativeReadTrace.rethrowFatal(failure);
                Map<String, Object> detail = Failures.error(failure);
                List<Object> rows = new ArrayList<>();
                Matrix3D m = turned.GetMatrix();
                for (int i = 0; i < 4; i++) {
                    rows.add(java.util.Arrays.asList(m.get(i, 0), m.get(i, 1), m.get(i, 2), m.get(i, 3)));
                }
                detail.put("orientation_matrix", rows);
                detail.put("location", java.util.Arrays.asList(where.get(0), where.get(1), where.get(2)));
                throw new Service.ToolkitFailure(detail);
            }
        } else {
            throw new Failures.Refusal("E_VALIDATION", "'view.type' is general, projection or detail");
        }
        Views.name(drawing, made, asked);
        Model model = drawing.GetCurrentSolid();
        if (view.containsKey("scale")) {
            double scale = Json.number(view, "scale");
            if (empty && model != null) {
                // The first view on a sheet sets the sheet's scale, as a drafter's main view
                // does: a view of a scale of its own is labelled (SCALE 1:1) and would leave the
                // title block reading the sheet's.
                drawing.SetSheetScale(sheetNumber, scale, model);
            } else if (model == null || Math.abs(drawing.GetSheetScale(sheetNumber, model) - scale) > 1e-9) {
                made.SetScale(scale);
            }
            regenerateQuietly(drawing, made.GetSheetNumber());
        } else if (empty && sheetScale != null && model != null
                && Math.abs(drawing.GetSheetScale(sheetNumber, model) - sheetScale) > 1e-9) {
            drawing.SetSheetScale(sheetNumber, sheetScale, model);
            regenerateQuietly(drawing, sheetNumber);
        }
        if ("detail".equals(kind)) {
            // Creo puts a detail's reference point at the location, and scales about it; the
            // view's middle goes there, as a person places it.
            Views.centre(drawing, made, where);
            drawing.RegenerateSheet(made.GetSheetNumber());
        }
        Map<String, Object> sectioned = null;
        if (view.get("section") instanceof Map) {
            Map<String, Object> asked2 = Json.object(view.get("section"), "'view.section'");
            sectioned = Views.section(drawing, made, parent, asked2);
            // Creo labels a section view (SECTION A-A) as the sheet regenerates, and a view
            // already showing only its cut face gets no label (measured): regenerated first.
            drawing.RegenerateSheet(made.GetSheetNumber());
            String edges = Json.string(asked2, "edges", null);
            if (edges != null) {
                int labels = noteCount(drawing);
                Views.sectionEdges(drawing, made, edges);
                sectioned.put("edges", edges);
                drawing.RegenerateSheet(made.GetSheetNumber());
                if ("area".equals(edges) && noteCount(drawing) < labels) {
                    // Showing the cut face alone, Creo drops the view's own label (measured);
                    // the drawing still needs one, A-A beneath it.
                    sectioned.put("label", sectionLabel(drawing, made, Json.string(asked2, "name")));
                }
            }
        }
        // Last: setting a section's edges puts the view back in wireframe (measured). A detail
        // is drawn as its parent is: Creo refuses it a display of its own (XToolkitBadContext).
        if (!"detail".equals(kind)) {
            Views.draw(made, Json.string(view, "display", "lines"));
        }
        if ("general".equals(kind) && Json.bool(view, "exploded", false)) {
            // The creation instruction alone is not a readback of the finished view.
            // Set the specified view after its other setup, as View_States documents;
            // summary/viewRow and the client's independent observation still read it.
            Map<String, Object> failure = Json.map("code", "E_CREO", "message",
                    "the view was created, but its exploded display could not be set",
                    "stage", "post_create_exploded_display", "view_created", true,
                    "completed_stage", "view_display_setup", "drawing", Json.string(request, "model"),
                    "sheet", sheetNumber, "requested_view", new java.util.LinkedHashMap<>(view),
                    "view_interface", made == null ? null : made.getClass().getName(),
                    "cleanup", "not_attempted; the created view and any auxiliary resources are retained");
            if (!(made instanceof com.ptc.wfc.wfcView2D.WView2D)) {
                failure.put("reason", "native_view_interface_unavailable");
                failure.put("setter_attempted", false);
                throw new Service.ToolkitFailure(failure);
            }
            try {
                ((com.ptc.wfc.wfcView2D.WView2D) made).SetExplodedState(true);
            } catch (Throwable cause) {
                NativeReadTrace.rethrowFatal(cause);
                failure.put("reason", "native_setter_failed");
                failure.put("setter_attempted", true);
                // Toolkit exceptions are native proxies. Do not make more CAD calls
                // merely to describe this failure or to look up the new view's ID.
                failure.put("cause", Json.map("class", cause.getClass().getName(),
                        "message", cause instanceof jxthrowable ? null : cause.getMessage(),
                        "native_exception_details", "not_read"));
                throw new Service.ToolkitFailure(failure);
            }
        }
        Creo.repaint(session);
        Map<String, Object> out = summary(drawing);
        out.put("view", viewRow(drawing, made));
        if (sectioned != null) {
            out.put("section", sectioned);
        }
        return out;
    }

    /**
     * A view's orientation, from the model's saved views as a person picks them; isometric
     * is FRONT turned 45 degrees about the vertical and 35.26 about the horizontal.
     */
    static Transform3D orientation(Solid solid, String name) throws jxthrowable {
        String saved = "isometric".equals(name) ? "FRONT" : name.toUpperCase(Locale.ROOT);
        com.ptc.pfc.pfcView.View view = null;
        try {
            view = ((com.ptc.pfc.pfcView.ViewOwner) solid).GetView(saved);
        } catch (Throwable absent) {
            NativeReadTrace.rethrowFatal(absent);
            // Refused below.
        }
        if (view == null) {
            throw new Failures.Refusal("E_NOT_FOUND", Creo.fileName((Model) solid) + " has no saved view " + saved);
        }
        // A saved view carries the window's zoom and pan (measured on Creo 13.4: a scale of
        // 11.27 and a translation); a drawing view takes a pure rotation, rows of unit length.
        double[][] m = new double[3][3];
        Matrix3D source = view.GetTransform().GetMatrix();
        for (int i = 0; i < 3; i++) {
            double length = Math.sqrt(source.get(i, 0) * source.get(i, 0) + source.get(i, 1) * source.get(i, 1)
                    + source.get(i, 2) * source.get(i, 2));
            for (int j = 0; j < 3; j++) {
                m[i][j] = source.get(i, j) / length;
            }
        }
        if (!"isometric".equals(name)) {
            return rotation(m);
        }
        double a = Math.toRadians(-45.0), b = Math.toRadians(35.264389682754654);
        double[][] ry = {{Math.cos(a), 0, -Math.sin(a)}, {0, 1, 0}, {Math.sin(a), 0, Math.cos(a)}};
        double[][] rx = {{1, 0, 0}, {0, Math.cos(b), Math.sin(b)}, {0, -Math.sin(b), Math.cos(b)}};
        return rotation(multiply(multiply(m, ry), rx));
    }

    private static Transform3D rotation(double[][] r) throws jxthrowable {
        Matrix3D out = Matrix3D.create();
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                out.set(i, j, i < 3 && j < 3 ? r[i][j] : (i == j ? 1.0 : 0.0));
            }
        }
        return pfcBase.Transform3D_Create(out);
    }

    private static double[][] multiply(double[][] x, double[][] y) {
        double[][] z = new double[3][3];
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                for (int k = 0; k < 3; k++) {
                    z[i][j] += x[i][k] * y[k][j];
                }
            }
        }
        return z;
    }

    static Point3D point(double x, double y) throws jxthrowable {
        Point3D p = call("Point3D.create", () -> Point3D.create());
        run("Point3D.set(0)", () -> p.set(0, x));
        run("Point3D.set(1)", () -> p.set(1, y));
        run("Point3D.set(2)", () -> p.set(2, 0.0));
        return p;
    }

    // ------------------------------------------------------------------ drawing.annotate

    /**
     * Show the model's dimensions and the axes of its holes on the drawing, view by view, as
     * Show Model Annotations does, then let Creo space the dimensions out. Creo decides which
     * view each dimension suits; one it cannot place in any view stays in the model only.
     * With 'features', only the dimensions those features own stay shown: Creo shows a view's
     * dimensions all at once (showing one by one fails, measured), so the rest are taken off
     * again and the views cleaned up once more. A dimension erased from a drawing stays erased:
     * ShowAnnotations does not show it again (measured), so taking off is for good.
     */
    static Map<String, Object> annotate(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        front(session, drawing);
        java.util.Set<String> only = null;
        if (request.get("features") instanceof List) {
            only = new java.util.HashSet<>();
            for (Object wanted : (List<?>) request.get("features")) {
                only.add(String.valueOf(wanted).toUpperCase(Locale.ROOT));
            }
        }
        List<Object> refusals = new ArrayList<>();
        cleanUp(drawing, true, refusals);
        List<Object> hidden = new ArrayList<>();
        // A zero says a feature lies on its reference -- a hole on the plane of symmetry --
        // which the drawing shows by its centre lines; a drafter never writes 0.
        List<Object> zeros = new ArrayList<>();
        if (!Json.bool(request, "with_zero", false)) {
            for (Object[] shown : shownDimensionObjects(drawing)) {
                com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
                if (Math.abs(d.GetDimValue()) < 1e-9) {
                    zeros.add(takeOff(drawing, d));
                }
            }
        }
        // A datum's own dimensions place other features, which carry the dimensions a reader
        // needs; a revolve's full turn needs none. Both stay when their feature is named.
        List<Object> datums = new ArrayList<>();
        List<Object> turns = new ArrayList<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            if (owner == null || (only != null && (only.contains(String.valueOf(owner.GetId()))
                    || (owner.GetName() != null && only.contains(owner.GetName().toUpperCase(Locale.ROOT)))))) {
                continue;
            }
            int type = owner.GetFeatType().getValue();
            if (type == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_DATUM_PLANE
                    || type == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_DATUM_AXIS
                    || type == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_DATUM_POINT
                    || type == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_COORD_SYS
                    || type == com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_CURVE) {
                datums.add(takeOff(drawing, d));
            } else if ("angle".equals(Dimensions.kind(d.GetDimType())) && Math.abs(d.GetDimValue() - 360) < 1e-9) {
                turns.add(takeOff(drawing, d));
            }
        }
        if (only != null) {
            for (Object[] shown : shownDimensionObjects(drawing)) {
                com.ptc.pfc.pfcFeature.Feature owner = ownerOf((com.ptc.pfc.pfcDimension.Dimension) shown[1]);
                boolean kept = owner != null && (only.contains(String.valueOf(owner.GetId()))
                        || (owner.GetName() != null && only.contains(owner.GetName().toUpperCase(Locale.ROOT))));
                if (!kept) {
                    hidden.add(takeOff(drawing, (com.ptc.pfc.pfcDimension.Dimension) shown[1]));
                }
            }
            cleanUp(drawing, false, refusals);
        }
        List<Object> sighted = intoSight(drawing, refusals);
        List<Object> stepped = onTheirSteps(session, drawing);
        List<Object> counted = new ArrayList<>();
        List<Object> uncounted = new ArrayList<>();
        counted(drawing, counted, uncounted);
        List<Object> chamfers = chamfers(drawing, "c".equals(Json.string(request, "chamfers", "angle")));
        List<Object> threads = threads(drawing);
        List<Object> brought = ontoTheSheet(drawing);
        Map<String, Object> perView = new java.util.LinkedHashMap<>();
        int shown = shownDimensions(drawing, perView);
        Creo.repaint(session);
        Map<String, Object> out = summary(drawing);
        out.put("annotated", Json.map("shown", shown, "by_view", perView, "refused", refusals,
                "taken_off", hidden, "zeros_taken_off", zeros, "datums_taken_off", datums,
                "full_turns_taken_off", turns, "moved_into_sight", sighted, "diameters_on_their_steps", stepped,
                "counts_prefixed", counted, "counts_taken_off", uncounted, "chamfers_called_out", chamfers,
                "threads_called_out", threads,
                "brought_onto_the_sheet", brought));
        return out;
    }

    /**
     * A diameter Creo showed on a circle its view cannot see -- a hub's, behind the disc it
     * stands on, in the view of the disc's other face -- moved to a view that sees the
     * cylinder, as a drafter gives it: across the cylinder in a side view, or on its circle
     * where that faces the reader. The views it went to are spaced out again.
     */
    private static List<Object> intoSight(Drawing drawing, List<Object> refusals) throws jxthrowable {
        List<Object> moved = new ArrayList<>();
        if (Service.sketchLibrary() == null) {
            return moved;
        }
        java.util.Set<String> respace = new java.util.LinkedHashSet<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            if (!"diameter".equals(Dimensions.kind(d.GetDimType()))) {
                continue;
            }
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            View2D view = drawing.GetViewDisplaying(d);
            Model model = view == null ? null : view.GetModel();
            if (owner == null || model == null || model.GetType().getValue() != ModelType._MDL_PART) {
                continue;
            }
            com.ptc.pfc.pfcGeometry.Cylinder cylinder = cylinderOf(owner, d.GetDimValue());
            String part = Creo.fileName(model).replaceFirst("(?i)\\.prt$", "");
            if (cylinder == null || sees(part, view, cylinder)) {
                continue;
            }
            com.ptc.pfc.pfcView2D.View2Ds all = drawing.List2DViews();
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                View2D other = all.get(i);
                if (other.GetName().equals(view.GetName()) || detail(other) || other.GetModel() == null
                        || !Creo.fileName(other.GetModel()).equalsIgnoreCase(Creo.fileName(model))
                        || !sees(part, other, cylinder)) {
                    continue;
                }
                try {
                    drawing.SetViewDisplaying(d, other);
                    moved.add(Json.map("name", d.GetName(), "id", d.GetId(), "from", view.GetName(), "to", other.GetName()));
                    respace.add(other.GetName());
                    break;
                } catch (Throwable refused) {
                    NativeReadTrace.rethrowFatal(refused);
                    // Not one Creo shows there: the next view.
                }
            }
        }
        for (String name : respace) {
            View2D view = drawing.GetViewByName(name);
            try {
                ((com.ptc.wfc.wfcDrawing.WDrawing) drawing).CleanupDimensions(view);
            } catch (Throwable cannot) {
                NativeReadTrace.rethrowFatal(cannot);
                refusals.add(Json.map("view", name, "error", Failures.error(cannot)));
            }
        }
        return moved;
    }

    private static boolean detail(View2D view) {
        try {
            return ((com.ptc.wfc.wfcView2D.WView2D) view).GetViewType().getValue()
                    == com.ptc.wfc.wfcView2D.ViewType._VIEW_DETAIL;
        } catch (Throwable unknown) {
            NativeReadTrace.rethrowFatal(unknown);
            return false;
        }
    }

    /** The feature's cylinder a diameter measures: one of its own, that wide. */
    private static com.ptc.pfc.pfcGeometry.Cylinder cylinderOf(com.ptc.pfc.pfcFeature.Feature owner, double across) {
        try {
            com.ptc.pfc.pfcModelItem.ModelItems faces =
                    owner.ListSubItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_SURFACE);
            for (int i = 0; faces != null && i < faces.getarraysize(); i++) {
                if (faces.get(i) instanceof com.ptc.pfc.pfcGeometry.Cylinder
                        && Math.abs(2 * ((com.ptc.pfc.pfcGeometry.Cylinder) faces.get(i)).GetRadius() - across) < 1e-6) {
                    return (com.ptc.pfc.pfcGeometry.Cylinder) faces.get(i);
                }
            }
        } catch (Throwable unread) {
            NativeReadTrace.rethrowFatal(unread);
            // None known.
        }
        return null;
    }

    /**
     * Whether a view sees a cylinder: some point of it, on its side toward the reader or
     * along its outline, with nothing of the part between it and the reader -- a ray cast
     * toward the reader by the native library meets no face.
     */
    private static boolean sees(String part, View2D view, com.ptc.pfc.pfcGeometry.Cylinder cylinder) {
        try {
            Transform3D back = view.GetTransform();
            back.Invert();
            com.ptc.pfc.pfcBase.Vector3D z = com.ptc.pfc.pfcBase.Vector3D.create();
            z.set(0, 0.0);
            z.set(1, 0.0);
            z.set(2, 1.0);
            double[] reader = unit(back.TransformVector(z));
            Transform3D frame = cylinder.GetCoordSys();
            double[] origin = {frame.GetOrigin().get(0), frame.GetOrigin().get(1), frame.GetOrigin().get(2)};
            double[] axis = unit(frame.GetZAxis());
            boolean hole = "toward_axis".equals(Geometry.surface(cylinder, false).get("outward"));
            com.ptc.pfc.pfcBase.UVParams[] corners = {cylinder.GetUVExtents().get(0), cylinder.GetUVExtents().get(1)};
            double u0 = corners[0].get(0), v0 = corners[0].get(1), u1 = corners[1].get(0), v1 = corners[1].get(1);
            // A point just off the cylinder, a hundredth of its radius out and toward the
            // reader; only faces the ray truly crosses, within a ten-thousandth, count.
            double reach = Math.max(cylinder.GetRadius(), 1e-3) * 1e-2;
            double aperture = reach * 1e-2;
            for (int a = 0; a < 16; a++) {
                for (double t : new double[] {0.02, 0.5, 0.98}) {
                    com.ptc.pfc.pfcBase.UVParams uv = com.ptc.pfc.pfcBase.UVParams.create();
                    uv.set(0, u0 + (u1 - u0) * (a + 0.5) / 16);
                    uv.set(1, v0 + (v1 - v0) * t);
                    Point3D p = cylinder.Eval3DData(uv).GetPoint();
                    double[] at = {p.get(0), p.get(1), p.get(2)};
                    double[] off = new double[3];
                    for (int k = 0; k < 3; k++) {
                        off[k] = at[k] - origin[k];
                    }
                    double along = dot(off, axis);
                    double[] out = new double[3];
                    for (int k = 0; k < 3; k++) {
                        out[k] = (off[k] - along * axis[k]) * (hole ? -1 : 1);
                    }
                    out = unit(out);
                    if (dot(out, reader) < -0.2) {
                        continue; // the cylinder's far side
                    }
                    double[] from = new double[3];
                    for (int k = 0; k < 3; k++) {
                        from[k] = at[k] + reach * (out[k] + reader[k]);
                    }
                    if (!blocked(part, from, reader, aperture)) {
                        return true;
                    }
                }
            }
        } catch (Throwable unknown) {
            NativeReadTrace.rethrowFatal(unknown);
            return true; // not known to be hidden: left where Creo put it
        }
        return false;
    }

    /** Whether a ray meets the part ahead of its start: a hit on the ray itself, beyond the start. */
    private static boolean blocked(String part, double[] from, double[] along, double aperture) throws Exception {
        for (String one : Geometry.cast(part, from, along, aperture).split(";")) {
            String[] t = one.trim().split("\\s+");
            if (t.length != 4) {
                continue;
            }
            double distance = Double.parseDouble(t[0]);
            double off = 0;
            for (int k = 0; k < 3; k++) {
                double gap = Double.parseDouble(t[k + 1]) - (from[k] + distance * along[k]);
                off += gap * gap;
            }
            if (distance > 1e-6 && Math.sqrt(off) <= 10 * aperture) {
                return true;
            }
        }
        return false;
    }

    private static double[] unit(com.ptc.pfc.pfcBase.Vector3D v) throws jxthrowable {
        return unit(new double[] {v.get(0), v.get(1), v.get(2)});
    }

    private static double[] unit(double[] v) {
        double n = Math.sqrt(dot(v, v));
        return n > 0 ? new double[] {v[0] / n, v[1] / n, v[2] / n} : v;
    }

    private static double dot(double[] a, double[] b) {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    /** A count this wrote ahead of the rest of a prefix -- Creo's own diameter symbol: "6X " then "⌀". */
    private static final java.util.regex.Pattern COUNT = java.util.regex.Pattern.compile("\\d+X (.*)",
            java.util.regex.Pattern.DOTALL);

    /**
     * A patterned hole's size as a drafter writes it, with how many there are: 6X followed by
     * the diameter. Creo shows the pattern leader's own dimensions, without the count. The
     * count goes ahead of the dimension's prefix, which already holds the diameter symbol
     * Creo writes (measured: a diameter's prefix reads "⌀"). The prefix belongs to the
     * dimension, in the part -- where a drafter sets it too -- so the part has unsaved
     * changes after. A count this wrote on a hole no longer patterned is taken off again.
     */
    private static void counted(Drawing drawing, List<Object> counted, List<Object> uncounted) throws jxthrowable {
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            if (owner == null || owner.GetFeatType().getValue() != com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_HOLE
                    || !"diameter".equals(Dimensions.kind(d.GetDimType())) || !acrossItsBore(owner, d.GetDimValue())) {
                continue;
            }
            int count = 0;
            try {
                com.ptc.pfc.pfcFeature.FeaturePattern pattern = owner.GetPattern();
                if (pattern != null && pattern.GetPatternLeader().GetId() == owner.GetId()) {
                    com.ptc.pfc.pfcFeature.Features members = pattern.ListMembers();
                    count = members == null ? 0 : members.getarraysize();
                }
            } catch (Throwable unpatterned) {
                NativeReadTrace.rethrowFatal(unpatterned);
                // Not a pattern's leader.
            }
            com.ptc.wfc.wfcDimension.WDimension w = (com.ptc.wfc.wfcDimension.WDimension) d;
            String had = w.GetPrefix() == null ? "" : w.GetPrefix();
            java.util.regex.Matcher ours = COUNT.matcher(had);
            String rest = ours.matches() ? ours.group(1) : had;
            String want = count > 1 ? count + "X " + rest : rest;
            if (want.equals(had)) {
                continue;
            }
            w.SetPrefix(want);
            Map<String, Object> row = Json.map("name", d.GetName(), "id", d.GetId(), "model", shown[0],
                    "feature", owner.GetName());
            if (count > 1) {
                row.put("prefix", want.trim());
                counted.add(row);
            } else {
                row.put("was", had.trim());
                uncounted.add(row);
            }
        }
    }

    /**
     * A 45-degree chamfer's dimension written as ISO 129 and ASME Y14.5 write it, its size by
     * the angle: 1 X 45. Creo gives the part's chamfer dimension the 45 x D form, 45 X 1,
     * whatever the drawing's default_chamfer_text says (measured); the style is the
     * drawing's, set per dimension (ProDrawingDimensionChamferStyleSet).
     */
    private static List<Object> chamfers(Drawing drawing, boolean c) throws jxthrowable {
        com.ptc.wfc.wfcDimension.DimChamferStyle style = c ? com.ptc.wfc.wfcDimension.DimChamferStyle.DIM_CHMFRSTYLE_CD
                : com.ptc.wfc.wfcDimension.DimChamferStyle.DIM_CHMFRSTYLE_D_X_45;
        List<Object> out = new ArrayList<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            if (owner == null || owner.GetFeatType().getValue() != com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_CHAMFER) {
                continue;
            }
            com.ptc.wfc.wfcDimension.WDimension w = (com.ptc.wfc.wfcDimension.WDimension) d;
            Map<String, Object> row = Json.map("name", d.GetName(), "id", d.GetId(), "feature", owner.GetName());
            try {
                if (w.GetChamferStyle(drawing).getValue() != style.getValue()) {
                    w.SetChamferStyle(style, drawing);
                }
                row.put("style", Creo.enumName(w.GetChamferStyle(drawing)).replace("DIM_CHMFRSTYLE_", "").toLowerCase(Locale.ROOT));
            } catch (Throwable refused) {
                NativeReadTrace.rethrowFatal(refused);
                // Not a 45 x D chamfer's dimension: a D x D one is a plain length.
                row.put("style", null);
                row.put("error", Failures.error(refused).get("message"));
            }
            out.add(row);
        }
        return out;
    }

    /** ISO 261's coarse pitch for each diameter it has one for, M1 to M68. */
    private static final double[][] COARSE = {{1, 0.25}, {1.2, 0.25}, {1.6, 0.35}, {2, 0.4}, {2.5, 0.45},
        {3, 0.5}, {3.5, 0.6}, {4, 0.7}, {5, 0.8}, {6, 1}, {8, 1.25}, {10, 1.5}, {12, 1.75}, {14, 2}, {16, 2},
        {18, 2.5}, {20, 2.5}, {22, 2.5}, {24, 3}, {27, 3}, {30, 3.5}, {33, 3.5}, {36, 4}, {39, 4}, {42, 4.5},
        {45, 4.5}, {48, 5}, {52, 5}, {56, 5.5}, {60, 5.5}, {64, 6}, {68, 6}};

    /**
     * A cosmetic thread called out as a drafter calls it, on the diameter it is cut on: the
     * shaft's own diameter shown as M25x1.5 (M24 for a coarse thread, ISO 261's pitch), and the
     * thread's minor diameter taken off this drawing. Where the drawing shows no diameter of
     * that size the thread keeps its own dimension and callout. The prefix and suffix belong
     * to the dimension, in the part, as the patterned holes' counts do.
     */
    private static List<Object> threads(Drawing drawing) throws jxthrowable {
        List<Object> out = new ArrayList<>();
        List<Object[]> shown = shownDimensionObjects(drawing);
        for (Object[] row : shown) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) row[1];
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            if (owner == null || owner.GetFeatType().getValue() != com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_COSMETIC
                    && owner.GetFeatType().getValue() != com.ptc.pfc.pfcFeature.FeatureType._FEATTYPE_THREAD
                    || !"diameter".equals(Dimensions.kind(d.GetDimType()))) {
                continue;
            }
            Double major = parameter(owner, "MAJOR_DIAMETER");
            Double pitch = parameter(owner, "PITCH");
            if (major == null || pitch == null || major <= 0 || pitch <= 0) {
                continue;
            }
            // In a bore the thread is cut at its major diameter: its own dimension is the one.
            boolean inBore = Math.abs(d.GetDimValue() - major) < 1e-6;
            com.ptc.pfc.pfcDimension.Dimension across = inBore ? d : null;
            for (Object[] other : inBore ? new ArrayList<Object[]>() : shown) {
                com.ptc.pfc.pfcDimension.Dimension o = (com.ptc.pfc.pfcDimension.Dimension) other[1];
                if (o.GetId() != d.GetId() && other[0].equals(row[0]) && "diameter".equals(Dimensions.kind(o.GetDimType()))
                        && Math.abs(o.GetDimValue() - major) < 1e-6) {
                    across = o;
                    break;
                }
            }
            if (across == null) {
                continue;
            }
            boolean coarse = false;
            for (double[] c : COARSE) {
                coarse |= Math.abs(c[0] - major) < 1e-9 && Math.abs(c[1] - pitch) < 1e-9;
            }
            String suffix = coarse ? "" : "x" + Geometry.round(pitch);
            com.ptc.wfc.wfcDimension.WDimension w = (com.ptc.wfc.wfcDimension.WDimension) across;
            w.SetPrefix("M");
            w.SetSuffix(suffix);
            Object taken = null;
            if (inBore) {
                // The size on a line of its own beneath the value is now the value itself.
                com.ptc.cipjava.stringseq text = com.ptc.cipjava.stringseq.create();
                text.append("@D");
                d.SetTexts(text);
            } else {
                taken = takeOff(drawing, d).get("name");
            }
            out.add(Json.map("feature", owner.GetName(), "model", row[0], "id", across.GetId(),
                    "on", across.GetName(), "prefix", "M", "suffix", suffix, "callout",
                    "M" + Geometry.round(major) + suffix, "taken_off", taken));
        }
        return out;
    }

    private static Double parameter(com.ptc.pfc.pfcFeature.Feature feature, String name) {
        try {
            com.ptc.pfc.pfcModelItem.Parameter p = feature.GetParam(name);
            return p == null ? null : p.GetValue().GetDoubleValue();
        } catch (Throwable absent) {
            NativeReadTrace.rethrowFatal(absent);
            return null;
        }
    }

    /** Whether a diameter is one of the hole's own bores: its drill, counterbore or countersink. */
    private static boolean acrossItsBore(com.ptc.pfc.pfcFeature.Feature hole, double value) {
        try {
            com.ptc.pfc.pfcModelItem.ModelItems faces =
                    hole.ListSubItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_SURFACE);
            for (int i = 0; faces != null && i < faces.getarraysize(); i++) {
                if (faces.get(i) instanceof com.ptc.pfc.pfcGeometry.Cylinder
                        && Math.abs(2 * ((com.ptc.pfc.pfcGeometry.Cylinder) faces.get(i)).GetRadius() - value) < 1e-6) {
                    return true;
                }
            }
        } catch (Throwable unread) {
            NativeReadTrace.rethrowFatal(unread);
            // Not known to be.
        }
        return false;
    }

    /**
     * A dimension Creo's spacing left off the sheet -- a diameter's text flung out along its
     * leader past the border -- brought back as a drafter drags one: along the same line from
     * the middle of its view, to just outside the view, and within the sheet's margin.
     */
    private static List<Object> ontoTheSheet(Drawing drawing) throws jxthrowable {
        List<Object> moved = new ArrayList<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            View2D view = drawing.GetViewDisplaying(d);
            if (view == null) {
                continue;
            }
            int number = view.GetSheetNumber();
            Transform3D sheet = drawing.GetSheetTransform(number);
            double width;
            double height;
            List<Object> at;
            try {
                com.ptc.pfc.pfcSheet.SheetInfo info = drawing.GetSheetInfo(number);
                width = info.GetWidth();
                height = info.GetHeight();
                at = onSheet(sheet, ((com.ptc.wfc.wfcDimension.WDimension) d).GetDimLocation(drawing, null).GetLocation());
            } catch (Throwable unplaced) {
                NativeReadTrace.rethrowFatal(unplaced);
                continue;
            }
            double x = ((Number) at.get(0)).doubleValue();
            double y = ((Number) at.get(1)).doubleValue();
            double margin = MARGIN * Math.min(width, height);
            if (x >= margin && x <= width - margin && y >= margin && y <= height - margin) {
                continue;
            }
            Outline3D box = view.GetOutline();
            List<Object> low = onSheet(sheet, box.get(0));
            List<Object> high = onSheet(sheet, box.get(1));
            double x0 = Math.min(((Number) low.get(0)).doubleValue(), ((Number) high.get(0)).doubleValue());
            double x1 = Math.max(((Number) low.get(0)).doubleValue(), ((Number) high.get(0)).doubleValue());
            double y0 = Math.min(((Number) low.get(1)).doubleValue(), ((Number) high.get(1)).doubleValue());
            double y1 = Math.max(((Number) low.get(1)).doubleValue(), ((Number) high.get(1)).doubleValue());
            double cx = (x0 + x1) / 2;
            double cy = (y0 + y1) / 2;
            double dx = x - cx;
            double dy = y - cy;
            double gap = GAP * Math.min(width, height);
            double t = Double.MAX_VALUE;
            if (Math.abs(dx) > 1e-9) {
                t = Math.min(t, ((dx > 0 ? x1 + gap : x0 - gap) - cx) / dx);
            }
            if (Math.abs(dy) > 1e-9) {
                t = Math.min(t, ((dy > 0 ? y1 + gap : y0 - gap) - cy) / dy);
            }
            if (t == Double.MAX_VALUE) {
                t = 0;
            }
            double nx = Math.max(margin, Math.min(width - margin, cx + t * dx));
            double ny = Math.max(margin, Math.min(height - margin, cy + t * dy));
            if (Detailing.moveNatively(drawing, (String) shown[0], d, toScreen(drawing, number, nx, ny))) {
                List<Object> now = null;
                try {
                    now = onSheet(sheet, ((com.ptc.wfc.wfcDimension.WDimension) d).GetDimLocation(drawing, null).GetLocation());
                } catch (Throwable unread) {
                    NativeReadTrace.rethrowFatal(unread);
                    // Reported as null.
                }
                moved.add(Json.map("name", d.GetName(), "id", d.GetId(), "view", view.GetName(), "from", at, "to", now));
            }
        }
        return moved;
    }

    /** How far inside the sheet's edge a dimension's text stays, and beyond its view it goes: parts of the sheet's short side. */
    private static final double MARGIN = 0.03;
    private static final double GAP = 0.04;

    /**
     * A turned part's diameters as a drafter places them: each over the step it measures,
     * written halfway between the axis and the edge -- where Creo's own spacing stacks them
     * all beside the view. Only where the view sees the axis from the side.
     */
    private static List<Object> onTheirSteps(Session session, Drawing drawing) throws jxthrowable {
        List<Object> placed = new ArrayList<>();
        Map<Integer, SketchPlan.Read> reads = new java.util.HashMap<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            if (!"diameter".equals(Dimensions.kind(d.GetDimType()))) {
                continue;
            }
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            if (owner == null) {
                continue;
            }
            com.ptc.pfc.pfcSolid.Solid solid;
            try {
                solid = Creo.solid(session, (String) shown[0]);
            } catch (Throwable absent) {
                NativeReadTrace.rethrowFatal(absent);
                continue;
            }
            SketchPlan.Read read = reads.computeIfAbsent(owner.GetId(), k -> SketchPlan.read(solid, owner));
            double[][] anchor = read.anchors.get(d.GetId());
            View2D view = anchor == null ? null : drawing.GetViewDisplaying(d);
            if (view == null) {
                continue;
            }
            Transform3D t = view.GetTransform();
            Point3D at = t.TransformPoint(point3(anchor[0]));
            Point3D tip = t.TransformPoint(point3(new double[] {anchor[0][0] + anchor[1][0], anchor[0][1] + anchor[1][1],
                    anchor[0][2] + anchor[1][2]}));
            // Seen from the side the axis runs across the view; seen end on it shrinks to a point.
            double run = Math.hypot(tip.get(0) - at.get(0), tip.get(1) - at.get(1));
            if (!(run > 0.5 * view.GetScale() * screenPerModel(drawing))) {
                continue;
            }
            if (Detailing.moveNatively(drawing, (String) shown[0], d, at)) {
                placed.add(Json.map("name", d.GetName(), "id", d.GetId(), "view", view.GetName(),
                        "at", onSheet(drawing.GetSheetTransform(view.GetSheetNumber()), at)));
            }
        }
        return placed;
    }

    private static Point3D point3(double[] p) throws jxthrowable {
        Point3D out = Point3D.create();
        for (int i = 0; i < 3; i++) {
            out.set(i, p[i]);
        }
        return out;
    }

    /** Screen length per model length at a view scale of 1: the sheet's own transform's. */
    private static double screenPerModel(Drawing drawing) throws jxthrowable {
        Transform3D sheet = drawing.GetSheetTransform(drawing.GetCurrentSheetNumber());
        if (sheet == null) {
            return 1.0;
        }
        Point3D o = sheet.TransformPoint(point(0, 0)), x = sheet.TransformPoint(point(1, 0));
        double sheetPerScreen = Math.hypot(x.get(0) - o.get(0), x.get(1) - o.get(1));
        return sheetPerScreen > 0 ? 1.0 / sheetPerScreen : 1.0;
    }

    /** Show every view's dimensions and axes (when 'show'), and let Creo space them out. */
    private static void cleanUp(Drawing drawing, boolean show, List<Object> refusals) throws jxthrowable {
        com.ptc.pfc.pfcView2D.View2Ds views = drawing.List2DViews();
        for (int v = 0; views != null && v < views.getarraysize(); v++) {
            View2D view = views.get(v);
            try {
                com.ptc.wfc.wfcView2D.WView2D wview = (com.ptc.wfc.wfcView2D.WView2D) view;
                if (show) {
                    wview.ShowAnnotations(com.ptc.wfc.wfcAnnotation.AnnotationType.ANNOTATION_DIMENSION);
                    wview.ShowAxes();
                }
                ((com.ptc.wfc.wfcDrawing.WDrawing) drawing).CleanupDimensions(view);
            } catch (Throwable cannot) {
                NativeReadTrace.rethrowFatal(cannot);
                refusals.add(Json.map("view", view.GetName(), "error", Failures.error(cannot)));
            }
        }
    }

    // ------------------------------------------------------------------ drawing.hide-dimension

    /**
     * Take shown dimensions off the drawing; the model keeps them. Each is named as the
     * drawing's reading lists it, 'd12', or 'd12@part.prt' where two models share a name. All
     * are found before any is taken off.
     */
    static Map<String, Object> hideDimensions(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        front(session, drawing);
        Object raw = request.get("dimensions");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'dimensions' lists the dimensions to take off");
        }
        List<Object[]> shown = shownDimensionObjects(drawing);
        List<com.ptc.pfc.pfcDimension.Dimension> doomed = new ArrayList<>();
        for (Object wanted : (List<?>) raw) {
            String text = String.valueOf(wanted);
            String dimName = text.contains("@") ? text.substring(0, text.indexOf('@')) : text;
            String modelName = text.contains("@") ? text.substring(text.indexOf('@') + 1) : null;
            List<com.ptc.pfc.pfcDimension.Dimension> hits = new ArrayList<>();
            for (Object[] row : shown) {
                com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) row[1];
                if (dimName.equalsIgnoreCase(d.GetName())
                        && (modelName == null || modelName.equalsIgnoreCase((String) row[0]))) {
                    hits.add(d);
                }
            }
            if (hits.isEmpty()) {
                throw new Failures.Refusal("E_NOT_FOUND", "the drawing shows no dimension " + text);
            }
            if (hits.size() > 1) {
                throw new Failures.Refusal("E_CONFLICT", "two models' dimensions are named " + text
                        + "; write it as name@model");
            }
            doomed.add(hits.get(0));
        }
        List<Object> hidden = new ArrayList<>();
        for (com.ptc.pfc.pfcDimension.Dimension d : doomed) {
            hidden.add(takeOff(drawing, d));
        }
        Creo.repaint(session);
        Map<String, Object> out = summary(drawing);
        out.put("taken_off", hidden);
        return out;
    }

    private static Map<String, Object> takeOff(Drawing drawing, com.ptc.pfc.pfcDimension.Dimension d)
            throws jxthrowable {
        // Annotation.UndisplayInDrawing answers without error and leaves the dimension shown
        // (measured on Creo 13.4); WDrawing.EraseAnnotation is ProDrawingAnnotationErase.
        ((com.ptc.wfc.wfcDrawing.WDrawing) drawing).EraseAnnotation((com.ptc.wfc.wfcAnnotation.Annotation) d);
        return Json.map("name", d.GetName(), "id", d.GetId(), "how", "erased_from_drawing");
    }

    static com.ptc.pfc.pfcFeature.Feature ownerOf(com.ptc.pfc.pfcDimension.Dimension d) {
        try {
            return call("WDimension.GetOwnerFeature", () -> ((com.ptc.wfc.wfcDimension.WDimension) d).GetOwnerFeature());
        } catch (Throwable unknown) {
            NativeReadTrace.rethrowFatal(unknown);
            return null;
        }
    }

    private static int noteCount(Drawing drawing) throws jxthrowable {
        com.ptc.pfc.pfcDetail.DetailItems notes =
                call("Model2D.ListDetailItems(note_count)", () -> drawing.ListDetailItems(com.ptc.pfc.pfcDetail.DetailType.DETAIL_NOTE, null));
        return notes == null ? 0 : call("DetailItems.getarraysize(note_count)", () -> notes.getarraysize());
    }

    /** A free note naming a section view, centred beneath it: "A-A". */
    private static Map<String, Object> sectionLabel(Drawing drawing, View2D view, String section)
            throws jxthrowable {
        NativeReadTrace.stage("drawing.section_label.create");
        com.ptc.pfc.pfcBase.Outline3D box = call("View2D.GetOutline(section_label)", () -> view.GetOutline());
        int sheetNumber = call("View2D.GetSheetNumber(section_label_bounds)", () -> view.GetSheetNumber());
        Transform3D sheet = call("Model2D.GetSheetTransform(section_label)", () -> drawing.GetSheetTransform(sheetNumber));
        Point3D lowPoint = call("Outline3D.get(section_label_low)", () -> box.get(0));
        List<Object> low = onSheet(sheet, lowPoint);
        Point3D highPoint = call("Outline3D.get(section_label_high)", () -> box.get(1));
        List<Object> high = onSheet(sheet, highPoint);
        double x = (((Number) low.get(0)).doubleValue() + ((Number) high.get(0)).doubleValue()) / 2;
        double y = Math.min(((Number) low.get(1)).doubleValue(), ((Number) high.get(1)).doubleValue()) - 8;
        com.ptc.pfc.pfcDetail.DetailTextLines lines = call("DetailTextLines.create(section_label)", () -> com.ptc.pfc.pfcDetail.DetailTextLines.create());
        com.ptc.pfc.pfcDetail.DetailTexts texts = call("DetailTexts.create(section_label)", () -> com.ptc.pfc.pfcDetail.DetailTexts.create());
        var text = call("pfcDetail.DetailText_Create(section_label)", () -> com.ptc.pfc.pfcDetail.pfcDetail.DetailText_Create(section + "-" + section));
        run("DetailTexts.append(section_label)", () -> texts.append(text));
        var line = call("pfcDetail.DetailTextLine_Create(section_label)", () -> com.ptc.pfc.pfcDetail.pfcDetail.DetailTextLine_Create(texts));
        run("DetailTextLines.append(section_label)", () -> lines.append(line));
        int placementSheet = call("View2D.GetSheetNumber(section_label_place)", () -> view.GetSheetNumber());
        Point3D where = toScreen(drawing, placementSheet, x, y);
        var attachment = call("pfcDetail.FreeAttachment_Create(section_label)", () -> com.ptc.pfc.pfcDetail.pfcDetail.FreeAttachment_Create(where));
        com.ptc.pfc.pfcDetail.DetailNoteItem note = call("Model2D.CreateFreeNote(section_label)", () -> {
            var created = drawing.CreateFreeNote(lines, attachment);
            NativeReadTrace.effect("note_created", Json.map("object_reference_received", created != null,
                    "id_observed", false, "save_invoked", false, "purpose", "section_label"));
            return created;
        });
        NativeReadTrace.stage("drawing.section_label.show");
        run("DetailNoteItem.Show(section_label)", () -> note.Show());
        NativeReadTrace.stage("drawing.section_label.explicit_returned_note");
        return noteRow(drawing, note);
    }

    // ------------------------------------------------------------------ drawing.add-note

    /** A note of one or more lines placed free on the sheet, at sheet coordinates. */
    static Map<String, Object> addNote(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = drawing(session, Json.string(request, "model"));
        NativeReadTrace.known("requested_drawing", Json.string(request, "model"));
        NativeReadTrace.stage("drawing.add_note.require_active_context");
        String actualDrawing = requireActiveNoteDrawing(session, drawing);
        com.ptc.pfc.pfcDetail.DetailNoteItem note = createNoteOnly(drawing, request);
        NativeReadTrace.stage("drawing.add_note.show");
        run("DetailNoteItem.Show", () -> note.Show());
        NativeReadTrace.stage("drawing.add_note.repaint");
        repaintTraced(session);
        NativeReadTrace.effect("native_write_returned", Json.map("operation", "drawing.add-note",
                "target", NativeReadTrace.knownValue("actual_drawing"),
                "requested_model", Json.string(request, "model"), "note_id_observed", false,
                "save_invoked", false, "repaint_status", NativeReadTrace.knownValue("repaint_status"),
                "stage", "create_show_repaint_helper_returned"));
        NativeReadTrace.stage("drawing.add_note.created_identity");
        int createdNoteId = call("DetailNoteItem.GetId(created_note)", () -> note.GetId());
        NativeReadTrace.known("created_note_id", createdNoteId);
        NativeReadTrace.effect("note_identity_observed", Json.map("operation", "drawing.add-note",
                "drawing", actualDrawing, "note_id", createdNoteId, "save_invoked", false));
        return addedNoteSummary(actualDrawing, createdNoteId, () -> summary(drawing));
    }

    /**
     * Read one actual summary and select its already read note. This is service-return
     * assembly, not the client's first independent post-write verification. No fallback
     * row/getter is allowed when the summary is incomplete or ambiguous.
     */
    static Map<String, Object> addedNoteSummary(String drawing, int createdNoteId,
            java.util.concurrent.Callable<Map<String, Object>> readSummary) throws Exception {
        NativeReadTrace.ensureHealthy();
        Map<String, Object> out = readSummary.call();
        NativeReadTrace.ensureHealthy();
        NativeReadTrace.stage("drawing.add_note.returned_note_from_summary");
        Map<String, Object> row = sameSummaryNote(out, drawing, createdNoteId);
        out.put("note", row);
        return out;
    }

    /** Pure selection of the independently inventoried row; no SDK handles or calls. */
    @SuppressWarnings("unchecked")
    static Map<String, Object> sameSummaryNote(Map<String, Object> summary, String drawing, int createdNoteId)
            throws Service.ToolkitFailure {
        String reason = null;
        Map<?, ?> selected = null;
        String typedDrawing = "(?i)[A-Za-z][A-Za-z0-9_-]{0,30}\\.drw";
        if (drawing == null || !drawing.matches(typedDrawing) || summary == null
                || !(summary.get("model") instanceof String actual) || !actual.matches(typedDrawing)
                || !drawing.equalsIgnoreCase(actual) || !"drawing".equals(summary.get("type"))) {
            reason = "drawing_identity";
        } else if (createdNoteId < 0) {
            reason = "created_note_identity";
        } else if (!(summary.get("notes") instanceof List<?> rows)) {
            reason = "note_inventory";
        } else {
            java.util.Set<Long> ids = new java.util.HashSet<>();
            for (Object raw : rows) {
                if (!(raw instanceof Map<?, ?> row)) { reason = "note_inventory_row"; break; }
                Object id = row.get("id");
                if (!(id instanceof Integer || id instanceof Long)
                        || ((Number) id).longValue() < 0 || ((Number) id).longValue() > Integer.MAX_VALUE
                        || !ids.add(((Number) id).longValue())) {
                    reason = "note_identity_ambiguous";
                    break;
                }
                if (row.get("error") != null) { reason = "note_row_error"; break; }
                if (((Number) id).longValue() == createdNoteId) selected = row;
            }
            if (reason == null && selected == null) reason = "created_note_missing";
            if (reason == null) {
                Object membershipValue = selected.get("membership_readback");
                if (!(membershipValue instanceof Map<?, ?> membership)
                        || !Boolean.TRUE.equals(membership.get("complete"))
                        || !(membership.get("drawing") instanceof String owner)
                        || !owner.matches(typedDrawing) || !drawing.equalsIgnoreCase(owner)
                        || !(membership.get("note_id") instanceof Integer || membership.get("note_id") instanceof Long)
                        || ((Number) membership.get("note_id")).longValue() != createdNoteId
                        || !(membership.get("source") instanceof String source) || source.trim().isEmpty()) {
                    reason = "created_note_membership";
                }
            }
        }
        if (reason != null) throw new Service.ToolkitFailure(Json.map("code", "E_VERIFY_INCOMPLETE",
                "retryable", false, "message", "Created note was not uniquely read as a member of the same drawing summary.",
                "summary_failure", reason, "actual_drawing", drawing, "created_note_id", createdNoteId,
                "native_read_state", "summary_returned_incomplete", "automatic_retry", false));
        return (Map<String, Object>) selected;
    }

    /** A simple-note preview already requires this context; never activate a window here. */
    private static String requireActiveNoteDrawing(Session session, Drawing drawing) throws jxthrowable {
        String actual = fileNameTraced((Model) drawing);
        Model current = call("Session.GetCurrentModel(note_context)", session::GetCurrentModel);
        var window = call("Session.GetCurrentWindow(note_context)", session::GetCurrentWindow);
        Model displayed = window == null ? null : call("Window.GetModel(note_context)", window::GetModel);
        String currentName = fileNameTraced(current), displayedName = fileNameTraced(displayed);
        NativeReadTrace.known("note_creation_context", Json.map("drawing", actual,
                "current_model", currentName, "window_model", displayedName));
        if (!actual.equals(currentName) || !actual.equals(displayedName))
            throw new Failures.Refusal("E_CONFLICT", "simple-note target must already be the current model and window; no note created");
        return actual;
    }

    /** The shared creation phase only; diagnostics must not silently Show or read the note. */
    static com.ptc.pfc.pfcDetail.DetailNoteItem createNoteOnly(Model2D drawing, Map<String, Object> request)
            throws jxthrowable {
        NativeReadTrace.stage("drawing.add_note.create");
        String text = Json.string(request, "text");
        List<?> at = (List<?>) request.get("at");
        if (at == null || at.size() != 2 || !(at.get(0) instanceof Double) || !(at.get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'at' is [x, y] on the sheet");
        }
        com.ptc.pfc.pfcDetail.DetailTextLines lines = call("DetailTextLines.create", () -> com.ptc.pfc.pfcDetail.DetailTextLines.create());
        int lineIndex = 0;
        for (String line : text.split("\n", -1)) {
            try (var lineScope = NativeReadTrace.scope("line_index", String.valueOf(lineIndex++))) {
                com.ptc.pfc.pfcDetail.DetailTexts texts = call("DetailTexts.create", () -> com.ptc.pfc.pfcDetail.DetailTexts.create());
                var detailText = call("pfcDetail.DetailText_Create", () -> com.ptc.pfc.pfcDetail.pfcDetail.DetailText_Create(line));
                run("DetailTexts.append", () -> texts.append(detailText));
                var detailLine = call("pfcDetail.DetailTextLine_Create", () -> com.ptc.pfc.pfcDetail.pfcDetail.DetailTextLine_Create(texts));
                run("DetailTextLines.append", () -> lines.append(detailLine));
            }
        }
        int sheet = call("Model2D.GetCurrentSheetNumber(note_create)", () -> drawing.GetCurrentSheetNumber());
        NativeReadTrace.known("creation_sheet", sheet);
        Point3D where = toScreen(drawing, sheet, (Double) at.get(0), (Double) at.get(1));
        var attachment = call("pfcDetail.FreeAttachment_Create", () -> com.ptc.pfc.pfcDetail.pfcDetail.FreeAttachment_Create(where));
        return call("Model2D.CreateFreeNote", () -> {
            com.ptc.pfc.pfcDetail.DetailNoteItem created = drawing.CreateFreeNote(lines, attachment);
            NativeReadTrace.effect("note_created", Json.map("object_reference_received", created != null,
                    "id_observed", false, "save_invoked", false, "sheet_at_create", sheet));
            return created;
        });
    }

    static Map<String, Object> noteRow(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note)
            throws jxthrowable {
        try (var scope = NativeReadTrace.scope("note_traversal", String.valueOf(NativeReadTrace.traversal("drawing.note_row")))) {
            Map<String, Object> attachment = noteAttachment(note);
            Integer noteSheet = attachment.get("sheet") instanceof Number
                    ? ((Number) attachment.get("sheet")).intValue() : null;
            NativeReadTrace.known("note_sheet", noteSheet);
            NativeReadTrace.known("note_attachment_readback_complete", attachment.get("complete"));
            com.ptc.pfc.pfcDetail.DetailTextLines lines = noteTextLines(note, false);
            String text = noteText(lines);
            List<Object> place = noteLocation(drawing, note, noteSheet);
            com.ptc.pfc.pfcDetail.DetailTextLines displayed = noteTextLines(note, true);
            String numeric = noteText(displayed);
            Map<String, Object> leaderReadback = noteLeaders(note);
            Map<String, Object> bounds = noteBounds(drawing, note, noteSheet, displayed);
            int noteId = call("DetailNoteItem.GetId(final_row)", () -> note.GetId());
            NativeReadTrace.known("note_id", noteId);
            return Json.map("id", noteId, "sheet", noteSheet, "text", text, "at", place, "box", bounds.get("box"),
                    "bounds_readback", bounds, "membership_readback", Json.map("complete", false,
                            "status", "not_checked", "drawing", null, "note_id", null,
                            "source", "no independent drawing inventory membership at this direct row entry"),
                    "displayed_text", numeric, "leaders", leaderReadback.get("items"),
                    "read_only", DrawingReadback.readOnly(note), "attachment_readback", attachment,
                    "leaders_complete", leaderReadback.get("complete"), "reference_source", "DetailNoteItem.GetInstructions/GetTextLines; Selection.GetPath");
        }
    }

    static Map<String, Object> noteAttachment(com.ptc.pfc.pfcDetail.DetailNoteItem note) {
        try (var scope = NativeReadTrace.scope("note_phase", "attachment")) {
            return DrawingReadback.note(note);
        }
    }

    /** Called only by a successful native ListDetailItems member traversal. No CAD here. */
    private static void noteMembership(Map<String, Object> row, String drawing, int id) {
        boolean ownerKnown = drawing != null && !drawing.trim().isEmpty();
        Object finalId = row.get("id");
        boolean sameId = finalId instanceof Number && ((Number) finalId).intValue() == id;
        Map<String, Object> membership = Json.map("complete", ownerKnown && sameId, "drawing", drawing,
                "note_id", id, "source", "Model2D.ListDetailItems(DETAIL_NOTE,null); Model.GetFileName; DetailItem.GetId");
        if (!ownerKnown) membership.put("reason", "inventory_drawing_identity_unavailable");
        else if (!sameId) membership.put("reason", "note_identity_changed_within_inventory_read");
        row.put("membership_readback", membership);
    }

    static com.ptc.pfc.pfcDetail.DetailTextLines noteTextLines(com.ptc.pfc.pfcDetail.DetailNoteItem note,
            boolean numeric) throws jxthrowable {
        var mode = numeric ? com.ptc.pfc.pfcDetail.DetailTextDisplayOption.DISPMODE_NUMERIC
                : com.ptc.pfc.pfcDetail.DetailTextDisplayOption.DISPMODE_SYMBOLIC;
        NativeReadTrace.known("text_display_mode", numeric ? "numeric" : "symbolic");
        return call("DetailNoteItem.GetTextLines(" + (numeric ? "numeric" : "symbolic") + ")", () -> note.GetTextLines(mode));
    }

    static String noteText(com.ptc.pfc.pfcDetail.DetailTextLines lines) throws jxthrowable {
        StringBuilder text = new StringBuilder();
        for (int l = 0; lines != null && l < call("DetailTextLines.getarraysize(text)", () -> lines.getarraysize()); l++) {
            final int lineIndex = l;
            try (var lineScope = NativeReadTrace.scope("line_index", String.valueOf(lineIndex))) {
                if (l > 0) {
                    text.append('\n');
                }
                var line = call("DetailTextLines.get(text)", () -> lines.get(lineIndex));
                com.ptc.pfc.pfcDetail.DetailTexts texts = call("DetailTextLine.GetTexts", () -> line.GetTexts());
                for (int t = 0; texts != null && t < call("DetailTexts.getarraysize", () -> texts.getarraysize()); t++) {
                    final int fragmentIndex = t;
                    try (var fragmentScope = NativeReadTrace.scope("fragment_index", String.valueOf(fragmentIndex))) {
                        var fragment = call("DetailTexts.get", () -> texts.get(fragmentIndex));
                        text.append(call("DetailText.GetText", () -> fragment.GetText()));
                    }
                }
            }
        }
        return text.toString();
    }

    static List<Object> noteLocation(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer noteSheet) throws jxthrowable {
        List<Object> place = null;
        try (var scope = NativeReadTrace.scope("note_phase", "free_anchor")) {
            var instructions = call("DetailNoteItem.GetInstructions(free_anchor)", () -> note.GetInstructions(true));
            var leader = call("DetailNoteInstructions.GetLeader(free_anchor)", () -> instructions.GetLeader());
            com.ptc.pfc.pfcDetail.Attachment attached = call("DetailLeaders.GetItemAttachment(free_anchor)", () -> leader.GetItemAttachment());
            if (noteSheet != null && attached instanceof com.ptc.pfc.pfcDetail.FreeAttachment) {
                Transform3D transform = call("Model2D.GetSheetTransform(free_anchor)", () -> drawing.GetSheetTransform(noteSheet));
                Point3D point = call("FreeAttachment.GetAttachmentPoint", () -> ((com.ptc.pfc.pfcDetail.FreeAttachment) attached).GetAttachmentPoint());
                double[] original = new double[3];
                for (int i = 0; i < 3; i++) {
                    final int axis = i;
                    original[axis] = call("Point3D.get(free_anchor_original_" + axis + ")", () -> point.get(axis));
                }
                Point3D copy = call("Point3D.create(free_anchor_copy)", () -> Point3D.create());
                for (int i = 0; i < 3; i++) {
                    final int axis = i;
                    run("Point3D.set(free_anchor_copy_" + axis + ")", () -> copy.set(axis, original[axis]));
                }
                place = onSheet(transform, copy);
            }
        } catch (Throwable unplaced) {
            NativeReadTrace.rethrowFatal(unplaced);
            // Reported as null.
        }
        return place;
    }

    static Map<String, Object> noteLeaders(com.ptc.pfc.pfcDetail.DetailNoteItem note) throws jxthrowable {
        List<Object> leaders = new ArrayList<>();
        boolean complete = true;
        try (var scope = NativeReadTrace.scope("note_phase", "leaders")) {
            var instructions = call("DetailNoteItem.GetInstructions(leaders)", () -> note.GetInstructions(true));
            var leader = call("DetailNoteInstructions.GetLeader(leaders)", () -> instructions.GetLeader());
            com.ptc.pfc.pfcDetail.Attachments attached = call("DetailLeaders.GetLeaders", () -> leader.GetLeaders());
            for (int i = 0; attached != null && i < call("Attachments.getarraysize", () -> attached.getarraysize()); i++) {
                final int leaderIndex = i;
                try (var leaderScope = NativeReadTrace.scope("leader_index", String.valueOf(leaderIndex))) {
                    com.ptc.pfc.pfcDetail.Attachment a = call("Attachments.get", () -> attached.get(leaderIndex));
                    com.ptc.pfc.pfcSelect.Selection found = null;
                    if (a instanceof com.ptc.pfc.pfcDetail.ParametricAttachment)
                        found = call("ParametricAttachment.GetAttachedGeometry(leader)", () -> ((com.ptc.pfc.pfcDetail.ParametricAttachment) a).GetAttachedGeometry());
                    else if (a instanceof com.ptc.pfc.pfcDetail.OffsetAttachment)
                        found = call("OffsetAttachment.GetAttachedGeometry(leader)", () -> ((com.ptc.pfc.pfcDetail.OffsetAttachment) a).GetAttachedGeometry());
                    final com.ptc.pfc.pfcSelect.Selection selected = found;
                    if (selected == null) {
                        complete = false;
                        continue;
                    }
                    com.ptc.pfc.pfcAssembly.ComponentPath path = call("Selection.GetPath", () -> selected.GetPath());
                    List<Object> ids = new ArrayList<>();
                    if (path != null) {
                        com.ptc.cipjava.intseq components = call("ComponentPath.GetComponentIds", () -> path.GetComponentIds());
                        for (int j = 0; j < call("intseq.getarraysize(component_path)", () -> components.getarraysize()); j++) {
                            final int componentIndex = j;
                            ids.add(call("intseq.get(component_path_" + componentIndex + ")", () -> components.get(componentIndex)));
                        }
                    }
                    Model model = call("Selection.GetSelModel", () -> selected.GetSelModel());
                    String modelName = fileNameTraced(model);
                    Model root = path == null ? null : call("ComponentPath.GetRoot", () -> path.GetRoot());
                    String rootName = fileNameTraced(root);
                    View2D present = call("Selection.GetSelView2D(presence)", () -> selected.GetSelView2D());
                    String viewName = null;
                    if (present != null) {
                        View2D value = call("Selection.GetSelView2D(value)", () -> selected.GetSelView2D());
                        viewName = call("View2D.GetName(leader)", () -> value.GetName());
                    }
                    var item = call("Selection.GetSelItem(id)", () -> selected.GetSelItem());
                    int itemId = call("ModelItem.GetId(leader)", () -> item.GetId());
                    var typeItem = call("Selection.GetSelItem(type)", () -> selected.GetSelItem());
                    var itemType = call("ModelItem.GetType(leader)", () -> typeItem.GetType());
                    String typeName = call("ModelItemType.enumName(leader)", () -> Creo.enumName(itemType));
                    leaders.add(Json.map("model", modelName, "component_path", ids, "root", rootName,
                            "view", viewName, "item_id", itemId, "item_type", typeName));
                }
            }
        } catch (Throwable unreadable) {
            NativeReadTrace.rethrowFatal(unreadable);
            complete = false;
        }
        return Json.map("items", leaders, "complete", complete);
    }

    static List<Object> noteBox(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer noteSheet, com.ptc.pfc.pfcDetail.DetailTextLines displayed) throws jxthrowable {
        @SuppressWarnings("unchecked")
        List<Object> box = (List<Object>) noteBounds(drawing, note, noteSheet, displayed).get("box");
        return box;
    }

    static Map<String, Object> noteBounds(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer noteSheet, com.ptc.pfc.pfcDetail.DetailTextLines displayed) throws jxthrowable {
        Map<String, Object> out = emptyNoteBounds(noteSheet);
        try (var scope = NativeReadTrace.scope("note_phase", "line_envelope_2d")) {
            if (displayed == null) throw new IllegalArgumentException("native_numeric_text_lines_unavailable");
            int count = call("DetailTextLines.getarraysize(bounds_lines)", () -> displayed.getarraysize());
            if (count <= 0) throw new IllegalArgumentException("native_numeric_text_lines_empty");
            return readNoteBounds(drawing, note, noteSheet, 0, count, out);
        } catch (Throwable unavailable) {
            return incompleteNoteBounds(out, unavailable);
        }
    }

    /** One line only, used by an explicitly enabled diagnostic; never reads text or summary. */
    static Map<String, Object> noteLineBounds(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer noteSheet, int lineIndex) throws jxthrowable {
        Map<String, Object> out = emptyNoteBounds(noteSheet);
        try (var scope = NativeReadTrace.scope("note_phase", "single_line_envelope_2d")) {
            if (lineIndex < 0) throw new IllegalArgumentException("line_index_must_be_nonnegative");
            return readNoteBounds(drawing, note, noteSheet, lineIndex, 1, out);
        } catch (Throwable unavailable) {
            return incompleteNoteBounds(out, unavailable);
        }
    }

    private static Map<String, Object> emptyNoteBounds(Integer sheet) {
        return Json.map("complete", false, "source", "DetailNoteItem.GetLineEnvelope; actual sheet transform and matrix",
                "sheet", sheet, "units", null, "raw_screen", new ArrayList<>(), "raw_sheet", new ArrayList<>(),
                "matrix", null, "box", null, "rounded", false,
                "z_policy", "not_observed; z=0 lift permitted only after exact matrix proof of XY independence",
                "coverage", "all_four_text_line_corners; excludes leader geometry and overall annotation layout");
    }

    private static Map<String, Object> incompleteNoteBounds(Map<String, Object> out, Throwable unavailable) {
        NativeReadTrace.rethrowFatal(unavailable);
        out.put("complete", false);
        out.put("box", null);
        out.put("reason", unavailable instanceof IllegalArgumentException ? unavailable.getMessage() : "native_getter_failed");
        out.put("error", Failures.error(unavailable));
        return out;
    }

    private static Map<String, Object> readNoteBounds(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer sheet, int firstLine, int count, Map<String, Object> out) throws jxthrowable {
        if (sheet == null || sheet <= 0) throw new IllegalArgumentException("native_note_sheet_unavailable");
        NativeReadTrace.known("note_sheet", sheet);
        var info = call("Model2D.GetSheetInfo(note_bounds)", () -> drawing.GetSheetInfo(sheet));
        if (info == null) throw new IllegalArgumentException("native_sheet_info_unavailable");
        var units = call("SheetInfo.GetUnits(note_bounds)", () -> info.GetUnits());
        if (units == null) throw new IllegalArgumentException("native_sheet_units_unavailable");
        var type = call("LengthUnits.GetType(note_bounds)", () -> units.GetType());
        if (type == null) throw new IllegalArgumentException("native_sheet_unit_type_unavailable");
        String unitName = call("LengthUnitType.enumName(note_bounds)", () -> Creo.enumName(type));
        if (!List.of("LENGTHUNIT_MM", "LENGTHUNIT_INCH", "LENGTHUNIT_FOOT", "LENGTHUNIT_CM", "LENGTHUNIT_M",
                "LENGTHUNIT_KM", "LENGTHUNIT_MCM", "LENGTHUNIT_MILE", "LENGTHUNIT_NM").contains(unitName))
            throw new IllegalArgumentException("native_sheet_unit_type_unsupported");
        out.put("units", unitName.replace("LENGTHUNIT_", "").toLowerCase(Locale.ROOT));
        Transform3D transform = call("Model2D.GetSheetTransform(note_bounds)", () -> drawing.GetSheetTransform(sheet));
        if (transform == null) throw new IllegalArgumentException("native_sheet_transform_unavailable");
        Matrix3D matrix = call("Transform3D.GetMatrix(note_bounds)", () -> transform.GetMatrix());
        if (matrix == null) throw new IllegalArgumentException("native_sheet_matrix_unavailable");
        double[][] rawMatrix = new double[4][4];
        for (int r = 0; r < 4; r++) for (int c = 0; c < 4; c++) {
            final int row = r, column = c;
            rawMatrix[row][column] = call("Matrix3D.get(note_bounds_" + row + "," + column + ")", () -> matrix.get(row, column));
        }
        out.put("matrix", NoteEnvelopeMath.matrixRows(rawMatrix));
        NoteEnvelopeMath.validateMatrix(rawMatrix);
        List<Object> rawScreen = new ArrayList<>(), rawSheet = new ArrayList<>();
        out.put("raw_screen", rawScreen); out.put("raw_sheet", rawSheet);
        List<List<Double>> allPaperCorners = new ArrayList<>();
        for (int ordinal = 0; ordinal < count; ordinal++) {
            final int line = firstLine + ordinal;
            try (var scope = NativeReadTrace.scope("line_index", String.valueOf(line))) {
                var envelope = call("DetailNoteItem.GetLineEnvelope", () -> note.GetLineEnvelope(line));
                if (envelope == null) throw new IllegalArgumentException("native_line_envelope_unavailable");
                List<List<Double>> screenCorners = new ArrayList<>();
                for (int k = 0; k < 2; k++) for (int j = 0; j < 2; j++) {
                    final int outlineIndex = k, cornerIndex = j;
                    var outline = call("Envelope2D.get(" + outlineIndex + ")", () -> envelope.get(outlineIndex));
                    if (outline == null) throw new IllegalArgumentException("native_line_outline_unavailable");
                    var point = call("Outline2D.get(" + cornerIndex + ")", () -> outline.get(cornerIndex));
                    if (point == null) throw new IllegalArgumentException("native_line_corner_unavailable");
                    double x = call("Point2D.get(note_bounds_x)", () -> point.get(0));
                    double y = call("Point2D.get(note_bounds_y)", () -> point.get(1));
                    screenCorners.add(List.of(x, y));
                }
                NoteEnvelopeMath.validateCorners(screenCorners);
                rawScreen.add(Json.map("line_index", line, "corners", screenCorners));
                List<List<Double>> paperCorners = new ArrayList<>();
                for (int i = 0; i < 4; i++) {
                    final int cornerIndex = i;
                    List<Double> original = screenCorners.get(cornerIndex);
                    Point3D copy = call("Point3D.create(note_bounds_copy_" + cornerIndex + ")", () -> Point3D.create());
                    run("Point3D.set(note_bounds_copy_x)", () -> copy.set(0, original.get(0)));
                    run("Point3D.set(note_bounds_copy_y)", () -> copy.set(1, original.get(1)));
                    run("Point3D.set(note_bounds_copy_equivalent_z)", () -> copy.set(2, 0.0));
                    Point3D paper = call("Transform3D.TransformPoint(note_bounds_copy)", () -> transform.TransformPoint(copy));
                    if (paper == null) throw new IllegalArgumentException("native_transformed_corner_unavailable");
                    double x = call("Point3D.get(note_bounds_paper_x)", () -> paper.get(0));
                    double y = call("Point3D.get(note_bounds_paper_y)", () -> paper.get(1));
                    paperCorners.add(List.of(x, y));
                }
                NoteEnvelopeMath.validateCorners(paperCorners);
                rawSheet.add(Json.map("line_index", line, "corners", paperCorners));
                allPaperCorners.addAll(paperCorners);
            }
        }
        out.put("box", NoteEnvelopeMath.bounds(allPaperCorners));
        out.put("complete", true);
        out.put("z_policy", "depth_not_observed; exact_matrix_proves_sheet_XY_independent_of_screen_z; owned_copy_z0_equivalent");
        NativeReadTrace.ensureHealthy();
        return out;
    }

    /** Explicit internal diagnostic of one requested line; no fallback or extra note reads. */
    static List<Object> noteLineBox(Model2D drawing, com.ptc.pfc.pfcDetail.DetailNoteItem note,
            Integer noteSheet, int lineIndex) throws jxthrowable {
        if (noteSheet == null) throw new IllegalStateException("native note sheet unavailable");
        try (var scope = NativeReadTrace.scope("note_phase", "single_line_envelope_3d", "line_index", String.valueOf(lineIndex))) {
            Transform3D transform = call("Model2D.GetSheetTransform(single_line_envelope)", () -> drawing.GetSheetTransform(noteSheet));
            com.ptc.wfc.wfcDisplay.Envelope3D envelope = call("WDetailNoteItem.Get3DLineEnvelope(single_line)",
                    () -> ((com.ptc.wfc.wfcDetail.WDetailNoteItem) note).Get3DLineEnvelope(lineIndex));
            double x0 = Double.MAX_VALUE, y0 = Double.MAX_VALUE, x1 = -Double.MAX_VALUE, y1 = -Double.MAX_VALUE;
            for (int k = 0; k < 2; k++) for (int j = 0; j < 2; j++) {
                final int outlineIndex = k, cornerIndex = j;
                var outline = call("Envelope3D.get(single_line_" + outlineIndex + ")", () -> envelope.get(outlineIndex));
                Point3D corner = call("Outline3D.get(single_line_" + cornerIndex + ")", () -> outline.get(cornerIndex));
                List<Object> p = onSheet(transform, corner);
                double x = ((Number) p.get(0)).doubleValue(), y = ((Number) p.get(1)).doubleValue();
                x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
            }
            return x0 <= x1 ? java.util.Arrays.asList(java.util.Arrays.asList(x0, y0), java.util.Arrays.asList(x1, y1)) : null;
        }
    }

    /** Every model dimension the drawing shows, as [model file name, dimension]. */
    static List<Object[]> shownDimensionObjects(Model2D drawing) throws jxthrowable {
        List<Object[]> out = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models models = call("Model2D.ListModels(shown_dimensions)", () -> drawing.ListModels());
        for (int m = 0; models != null && m < call("Models.getarraysize(shown_dimensions)", () -> models.getarraysize()); m++) {
            final int modelIndex = m;
            if (!(call("Models.get(dimension_model_type)", () -> models.get(modelIndex)) instanceof Solid)) {
                continue;
            }
            Solid solid = (Solid) call("Models.get(dimension_model)", () -> models.get(modelIndex));
            com.ptc.pfc.pfcDimension.Dimensions dims = call("Model2D.CollectShownDimensions", () -> drawing.CollectShownDimensions(solid));
            for (int d = 0; dims != null && d < call("Dimensions.getarraysize(shown)", () -> dims.getarraysize()); d++) {
                final int dimensionIndex = d;
                Model model = call("Models.get(dimension_owner_name)", () -> models.get(modelIndex));
                String fileName = fileNameTraced(model);
                var dimension = call("Dimensions.get(shown)", () -> dims.get(dimensionIndex));
                out.add(new Object[] {fileName, dimension});
            }
        }
        return out;
    }

    /** The dimensions a drawing shows: their names, values, owners and views. */
    static List<Object> shownDimensionRows(Model2D drawing) throws jxthrowable {
        List<Object> rows = new ArrayList<>();
        for (Object[] shown : shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) shown[1];
            com.ptc.pfc.pfcFeature.Feature owner = ownerOf(d);
            View2D in = call("Model2D.GetViewDisplaying(dimension)", () -> drawing.GetViewDisplaying(d));
            Integer sheetNumber = in == null ? null : call("View2D.GetSheetNumber(dimension)", () -> in.GetSheetNumber());
            Transform3D sheet = sheetNumber == null ? null : call("Model2D.GetSheetTransform(dimension)", () -> drawing.GetSheetTransform(sheetNumber));
            List<Object> place = null;
            try {
                // Where the dimension's text sits, so free space can be found and a dimension moved.
                if (sheet != null) {
                    var location = call("WDimension.GetDimLocation", () -> ((com.ptc.wfc.wfcDimension.WDimension) d).GetDimLocation((Drawing) drawing, null));
                    Point3D point = call("DimLocation.GetLocation", () -> location.GetLocation());
                    place = onSheet(sheet, point);
                }
            } catch (Throwable unplaced) {
                NativeReadTrace.rethrowFatal(unplaced);
                // Reported as null.
            }
            String name = call("Dimension.GetName", () -> d.GetName());
            int id = call("Dimension.GetId", () -> d.GetId());
            double value = call("Dimension.GetDimValue", () -> d.GetDimValue());
            var type = call("Dimension.GetDimType", () -> d.GetDimType());
            String typeName = call("DimensionType.enumName", () -> Creo.enumName(type)).replace("DIM_", "").toLowerCase(Locale.ROOT);
            Map<String, Object> feature = owner == null ? null : Json.map("id", call("Feature.GetId(dimension_owner)", () -> owner.GetId()),
                    "name", call("Feature.GetName(dimension_owner)", () -> owner.GetName()));
            String viewName = in == null ? null : call("View2D.GetName(dimension)", () -> in.GetName());
            Object tolerance = call("Dimensions.toleranceOf[delegated_internal_getters_uninstrumented]", () -> Dimensions.toleranceOf(d));
            Map<String, Object> row = Json.map("name", name, "id", id, "model", shown[0],
                    "value", Geometry.round(value), "type", typeName, "feature", feature,
                    "view", viewName, "sheet", sheetNumber, "reference", false, "at", place, "tolerance", tolerance);
            row.put("box", sheet == null ? null : textBox(drawing, sheet, d));
            try {
                // What the drawing writes before and after the value: a count, 6X ⌀; X 45.
                String prefix = call("WDimension.GetPrefix", () -> ((com.ptc.wfc.wfcDimension.WDimension) d).GetPrefix());
                if (prefix != null && !prefix.trim().isEmpty()) {
                    row.put("prefix", prefix.trim());
                }
                String suffix = call("WDimension.GetSuffix", () -> ((com.ptc.wfc.wfcDimension.WDimension) d).GetSuffix());
                if (suffix != null && !suffix.trim().isEmpty()) {
                    row.put("suffix", suffix.trim());
                }
            } catch (Throwable unread) {
                NativeReadTrace.rethrowFatal(unread);
                // None reported.
            }
            rows.add(row);
        }
        rows.addAll(call("Detailing.drawingDimensionRows[delegated_internal_getters_uninstrumented]", () -> Detailing.drawingDimensionRows(drawing)));
        return rows;
    }

    /**
     * The box a dimension's text takes on the sheet, [[x0, y0], [x1, y1]] -- its whole text,
     * every line (ProDimensionEnvelopeGet with no line number), in screen coordinates taken to
     * the sheet. Null where Creo gives none.
     */
    static List<Object> textBox(Model2D drawing, Transform3D sheet, com.ptc.pfc.pfcDimension.BaseDimension d) {
        try {
            com.ptc.wfc.wfcDisplay.Envelope3D envelope =
                    call("WDimension.GetEnvelope(-1)", () -> ((com.ptc.wfc.wfcDimension.WDimension) d).GetEnvelope((Drawing) drawing, -1));
            double x0 = Double.MAX_VALUE, y0 = Double.MAX_VALUE, x1 = -Double.MAX_VALUE, y1 = -Double.MAX_VALUE;
            for (int k = 0; k < 2; k++) {
                com.ptc.pfc.pfcBase.Outline3D pair;
                try {
                    final int outlineIndex = k;
                    pair = call("Envelope3D.get(dimension_" + outlineIndex + ")", () -> envelope.get(outlineIndex));
                } catch (Throwable fewer) {
                    NativeReadTrace.rethrowFatal(fewer);
                    break;
                }
                for (int j = 0; pair != null && j < 2; j++) {
                    final int cornerIndex = j;
                    final Outline3D outline = pair;
                    Point3D corner = call("Outline3D.get(dimension_" + cornerIndex + ")", () -> outline.get(cornerIndex));
                    List<Object> p = onSheet(sheet, corner);
                    double x = ((Number) p.get(0)).doubleValue();
                    double y = ((Number) p.get(1)).doubleValue();
                    x0 = Math.min(x0, x);
                    y0 = Math.min(y0, y);
                    x1 = Math.max(x1, x);
                    y1 = Math.max(y1, y);
                }
            }
            if (x0 > x1) {
                return null;
            }
            return java.util.Arrays.asList(java.util.Arrays.asList(Geometry.round(x0), Geometry.round(y0)),
                    java.util.Arrays.asList(Geometry.round(x1), Geometry.round(y1)));
        } catch (Throwable unread) {
            NativeReadTrace.rethrowFatal(unread);
            return null;
        }
    }

    /** How many of its models' dimensions the drawing shows; counted per view into byView. */
    static int shownDimensions(Model2D drawing, Map<String, Object> byView) throws jxthrowable {
        int shown = 0;
        com.ptc.pfc.pfcModel.Models models = call("Model2D.ListModels(shown_count)", () -> drawing.ListModels());
        for (int m = 0; models != null && m < call("Models.getarraysize(shown_count)", () -> models.getarraysize()); m++) {
            final int modelIndex = m;
            if (!(call("Models.get(shown_count_type)", () -> models.get(modelIndex)) instanceof Solid)) {
                continue;
            }
            Solid model = (Solid) call("Models.get(shown_count_model)", () -> models.get(modelIndex));
            com.ptc.pfc.pfcDimension.Dimensions dims = call("Model2D.CollectShownDimensions(count)", () -> drawing.CollectShownDimensions(model));
            for (int d = 0; dims != null && d < call("Dimensions.getarraysize(shown_count)", () -> dims.getarraysize()); d++) {
                final int dimensionIndex = d;
                shown++;
                if (byView != null) {
                    var dimension = call("Dimensions.get(shown_count)", () -> dims.get(dimensionIndex));
                    View2D in = call("Model2D.GetViewDisplaying(count)", () -> drawing.GetViewDisplaying(dimension));
                    String key = in == null ? "?" : call("View2D.GetName(shown_count)", () -> in.GetName());
                    byView.put(key, ((Integer) byView.getOrDefault(key, 0)) + 1);
                }
            }
        }
        return shown;
    }

    // ------------------------------------------------------------------ summary

    static Map<String, Object> info(Map<String, Object> request) throws Exception {
        Drawing drawing = drawing(Creo.session(), Json.string(request, "model"));
        NativeReadTrace.stage("drawing.info");
        List<Object> models = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models all = call("Model2D.ListModels(info)", () -> drawing.ListModels());
        if (all == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "drawing model inventory is null");
        for (int i = 0; i < call("Models.getarraysize(info)", () -> all.getarraysize()); i++) {
            final int modelIndex = i;
            Model model = call("Models.get(info)", () -> all.get(modelIndex));
            models.add(fileNameTraced(model));
        }
        String projection = options(drawing).get("projection_type");
        if (projection == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "projection option is unavailable");
        return Json.map("model", fileNameTraced(drawing), "type", "drawing", "models", models,
                "sheet_count", call("Model2D.GetNumberOfSheets(info)", () -> drawing.GetNumberOfSheets()), "projection", projection.toLowerCase(Locale.ROOT),
                "origin", originTraced(drawing), "modified", modifiedTraced(drawing), "completed", true,
                "source", "Drawing.ListModels/GetNumberOfSheets/DWGSetupExportInstructions",
                "not_checked", List.of("resource_inventory", "layout_quality", "manufacturing_completeness"));
    }

    static Map<String, Object> resources(Map<String, Object> request) throws Exception {
        Drawing drawing = drawing(Creo.session(), Json.string(request, "model"));
        String kind = Json.string(request, "kind");
        NativeReadTrace.stage("drawing.resources." + kind);
        Integer sheet = request.get("sheet") instanceof Number ? ((Number) request.get("sheet")).intValue() : null;
        int sheets = call("Model2D.GetNumberOfSheets(resources)", () -> drawing.GetNumberOfSheets());
        if (sheet != null && (sheet < 1 || sheet > sheets)) {
            throw new Failures.Refusal("E_NOT_FOUND", "sheet is outside the actual drawing");
        }
        List<Object> rows = new ArrayList<>();
        switch (kind) {
            case "sheets":
                for (int s = 1; s <= sheets; s++) {
                    final int sheetIndex = s;
                    com.ptc.pfc.pfcSheet.SheetInfo info = call("Model2D.GetSheetInfo(resources_" + sheetIndex + ")", () -> drawing.GetSheetInfo(sheetIndex));
                    double width = call("SheetInfo.GetWidth(resources)", () -> info.GetWidth());
                    double height = call("SheetInfo.GetHeight(resources)", () -> info.GetHeight());
                    var units = call("SheetInfo.GetUnits(resources)", () -> info.GetUnits());
                    var type = call("Unit.GetType(resources)", () -> units.GetType());
                    String unitName = call("LengthUnitType.enumName(resources)", () -> Creo.enumName(type));
                    var size = call("SheetInfo.GetSheetSize(resources)", () -> info.GetSheetSize());
                    rows.add(Json.map("number", s, "sheet", s, "width", width, "height", height,
                            "units", unitName.replace("LENGTHUNIT_", "").toLowerCase(Locale.ROOT),
                            "size", call("SheetSize.enumName(resources)", () -> Creo.enumName(size))));
                }
                break;
            case "views":
                com.ptc.pfc.pfcView2D.View2Ds views = call("Model2D.List2DViews(resources)", () -> drawing.List2DViews());
                if (views == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "view inventory is null");
                for (int i = 0; i < call("View2Ds.getarraysize(resources)", () -> views.getarraysize()); i++) {
                    final int viewIndex = i;
                    View2D view = call("View2Ds.get(resources)", () -> views.get(viewIndex));
                    rows.add(viewRow(drawing, view));
                }
                break;
            case "dimensions": rows = shownDimensionRows(drawing); break;
            case "notes":
                NativeReadTrace.stage("drawing.resources.notes.cell_notes[delegated_internal_getters_uninstrumented]");
                java.util.Set<Integer> cells = call("Detailing.cellNotes[delegated_traced_getters]", () -> Detailing.cellNotes(drawing));
                NativeReadTrace.stage("drawing.resources.notes");
                com.ptc.pfc.pfcDetail.DetailItems notes =
                        call("Model2D.ListDetailItems(resources_notes)", () -> drawing.ListDetailItems(com.ptc.pfc.pfcDetail.DetailType.DETAIL_NOTE, null));
                if (notes == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "note inventory is null");
                String inventoriedDrawing = fileNameTraced(drawing);
                for (int i = 0; i < call("DetailItems.getarraysize(resources_notes)", () -> notes.getarraysize()); i++) {
                    final int noteIndex = i;
                    var item = call("DetailItems.get(resources_note_id)", () -> notes.get(noteIndex));
                    int id = call("DetailItem.GetId(resources_note)", () -> item.GetId());
                    if (!cells.contains(id)) {
                        try (var noteScope = NativeReadTrace.scope("note_id", String.valueOf(id), "note_inventory_index", String.valueOf(noteIndex))) {
                            NativeReadTrace.known("note_id", id);
                            var note = (com.ptc.pfc.pfcDetail.DetailNoteItem) call("DetailItems.get(resources_note_row)", () -> notes.get(noteIndex));
                            Map<String, Object> row = noteRow(drawing, note);
                            noteMembership(row, inventoriedDrawing, id);
                            rows.add(row);
                        }
                    }
                }
                break;
            case "tables": rows = call("Detailing.tableRowsStrict[delegated_traced_getters]", () -> Detailing.tableRowsStrict(drawing)); break;
            case "symbols": rows = call("Detailing.symbolRowsStrict[delegated_internal_getters_uninstrumented]", () -> Detailing.symbolRowsStrict(drawing)); break;
            case "datums": rows = call("Tolerances.datumRowsStrict[delegated_internal_getters_uninstrumented]", () -> Tolerances.datumRowsStrict(drawing)); break;
            case "gtols": rows = call("Tolerances.gtolRowsStrict[delegated_internal_getters_uninstrumented]", () -> Tolerances.gtolRowsStrict(drawing)); break;
            case "entities": rows = DrawingReadback.entities(drawing); break;
            default: throw new Failures.Refusal("E_VALIDATION", "unknown drawing resource");
        }
        if (rows == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "resource inventory is null");
        List<Object> selected = new ArrayList<>();
        for (Object item : rows) {
            if (!(item instanceof Map)) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "resource row is unreadable");
            Map<?, ?> row = (Map<?, ?>) item;
            if (row.get("error") != null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "resource row getter failed");
            if (sheet != null && !(row.get("sheet") instanceof Number)) {
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "resource sheet ownership is unavailable");
            }
            if (sheet == null || ((Number) row.get("sheet")).intValue() == sheet) selected.add(item);
        }
        NativeReadTrace.ensureHealthy();
        return Json.map("model", fileNameTraced(drawing), "items", selected, "completed", true,
                "source", "Drawing native " + kind + " getters", "scope", sheet == null ? "all_sheets" : "sheet:" + sheet,
                "coverage", Json.map("count", selected.size(), "inventory", kind,
                        "view_removal_scope", "views".equals(kind) ? DrawingReadback.detailScope(drawing) : null,
                        "empty_semantics", "symbols".equals(kind) || "gtols".equals(kind)
                                ? "successful SDK nullable-list return means no matching items; exceptions and missing RPC fields are not empty"
                                : "datums".equals(kind) ? "nullable ListSetDatumTags cross-checked with ListItems(ITEM_SET_DATUM_TAG)" : null,
                        "dimension_scope", "dimensions".equals(kind) ? "shown_dimensions_only" : null),
                "not_checked", List.of("every_optional_field", "hidden_model_dimensions", "clipping", "overlap", "manufacturing_completeness"));
    }

    static Map<String, Object> summary(Model2D drawing) throws jxthrowable {
        try (var summaryScope = NativeReadTrace.scope("phase", "service.summary", "summary_traversal",
                String.valueOf(NativeReadTrace.traversal("Drawings.summary")))) {
            List<Object> models = new ArrayList<>();
            com.ptc.pfc.pfcModel.Models shown = call("Model2D.ListModels(summary)", () -> drawing.ListModels());
            for (int i = 0; shown != null && i < call("Models.getarraysize(summary)", () -> shown.getarraysize()); i++) {
                final int modelIndex = i;
                Model model = call("Models.get(summary_" + modelIndex + ")", () -> shown.get(modelIndex));
                models.add(fileNameTraced(model));
            }
            List<Object> sheets = new ArrayList<>();
            for (int s = 1; s <= call("Model2D.GetNumberOfSheets(summary)", () -> drawing.GetNumberOfSheets()); s++) {
                final int sheetNumber = s;
                Map<String, Object> row = Json.map("number", s);
                try {
                    com.ptc.pfc.pfcSheet.SheetInfo info = call("Model2D.GetSheetInfo(summary_" + sheetNumber + ")", () -> drawing.GetSheetInfo(sheetNumber));
                    row.put("width", call("SheetInfo.GetWidth", () -> info.GetWidth()));
                    row.put("height", call("SheetInfo.GetHeight", () -> info.GetHeight()));
                    var units = call("SheetInfo.GetUnits", () -> info.GetUnits());
                    var unitType = call("Unit.GetType", () -> units.GetType());
                    row.put("units", call("LengthUnitType.enumName", () -> Creo.enumName(unitType)).replace("LENGTHUNIT_", "")
                            .toLowerCase(Locale.ROOT));
                    var size = call("SheetInfo.GetSheetSize", () -> info.GetSheetSize());
                    row.put("size", call("SheetSize.enumName", () -> Creo.enumName(size)).replace("SIZEPLOT", "").toLowerCase(Locale.ROOT));
                } catch (Throwable unreadable) {
                    NativeReadTrace.rethrowFatal(unreadable);
                    row.put("error", Failures.error(unreadable));
                }
                if (shown != null && call("Models.getarraysize(sheet_scale)", () -> shown.getarraysize()) > 0) {
                    try {
                        Model model = call("Models.get(sheet_scale)", () -> shown.get(0));
                        double scale = call("Model2D.GetSheetScale(summary)", () -> drawing.GetSheetScale(sheetNumber, model));
                        row.put("scale", scale);
                        row.put("scale_label", scaleLabel(scale));
                    } catch (Throwable unread) {
                        NativeReadTrace.rethrowFatal(unread);
                        // A sheet without a scale of the model is reported without one.
                    }
                }
                sheets.add(row);
            }
            List<Object> views = new ArrayList<>();
            com.ptc.pfc.pfcView2D.View2Ds all = call("Model2D.List2DViews(summary)", () -> drawing.List2DViews());
            for (int i = 0; all != null && i < call("View2Ds.getarraysize(summary)", () -> all.getarraysize()); i++) {
                final int viewIndex = i;
                View2D view = call("View2Ds.get(summary_" + viewIndex + ")", () -> all.get(viewIndex));
                views.add(viewRow(drawing, view));
            }
            Object shownCount;
            Object dimensions;
            try {
                NativeReadTrace.stage("service.summary.dimensions");
                List<Object> rows = shownDimensionRows(drawing);
                dimensions = rows;
                shownCount = rows.size();
            } catch (Throwable uncountable) {
                NativeReadTrace.rethrowFatal(uncountable);
                dimensions = null;
                shownCount = null;
            }
            Object notes;
            try {
                List<Object> rows = new ArrayList<>();
                // A table's cells are notes to Creo too; they are the table's text, listed with it.
                NativeReadTrace.stage("service.summary.cell_notes[delegated_internal_getters_uninstrumented]");
                java.util.Set<Integer> cells = call("Detailing.cellNotes[delegated_traced_getters]", () -> Detailing.cellNotes(drawing));
                NativeReadTrace.stage("service.summary.notes");
                com.ptc.pfc.pfcDetail.DetailItems items =
                        call("Model2D.ListDetailItems(notes_summary)", () -> drawing.ListDetailItems(com.ptc.pfc.pfcDetail.DetailType.DETAIL_NOTE, null));
                String inventoriedDrawing = items == null ? null : fileNameTraced(drawing);
                for (int i = 0; items != null && i < call("DetailItems.getarraysize(notes_summary)", () -> items.getarraysize()); i++) {
                    final int noteIndex = i;
                    var item = call("DetailItems.get(notes_summary_id)", () -> items.get(noteIndex));
                    int id = call("DetailItem.GetId(notes_summary)", () -> item.GetId());
                    if (!cells.contains(id)) {
                        try (var noteScope = NativeReadTrace.scope("note_id", String.valueOf(id), "note_inventory_index", String.valueOf(noteIndex))) {
                            NativeReadTrace.known("note_id", id);
                            var note = (com.ptc.pfc.pfcDetail.DetailNoteItem) call("DetailItems.get(notes_summary_row)", () -> items.get(noteIndex));
                            Map<String, Object> row = noteRow(drawing, note);
                            noteMembership(row, inventoriedDrawing, id);
                            rows.add(row);
                        }
                    }
                }
                notes = rows;
            } catch (Throwable unreadable) {
                NativeReadTrace.rethrowFatal(unreadable);
                notes = null;
            }
            Object tables;
            try {
                NativeReadTrace.stage("service.summary.tables[delegated_internal_getters_uninstrumented]");
                tables = call("Detailing.tableRows[delegated_traced_getters]", () -> Detailing.tableRows(drawing));
            } catch (Throwable unreadable) {
                NativeReadTrace.rethrowFatal(unreadable);
                tables = null;
            }
            Object symbols;
            try {
                NativeReadTrace.stage("service.summary.symbols[delegated_internal_getters_uninstrumented]");
                symbols = call("Detailing.symbolRows[delegated_internal_getters_uninstrumented]", () -> Detailing.symbolRows(drawing));
            } catch (Throwable unreadable) {
                NativeReadTrace.rethrowFatal(unreadable);
                symbols = null;
            }
            String projection = null;
            try {
                NativeReadTrace.stage("service.summary.projection_options");
                String option = options((Drawing) drawing).get("projection_type");
                projection = option == null ? null : option.toLowerCase(Locale.ROOT);
            } catch (Throwable unread) {
                NativeReadTrace.rethrowFatal(unread);
                // Reported as null.
            }
            Object entities;
            List<Object> arcs = new ArrayList<>();
            try {
                NativeReadTrace.stage("service.summary.draft_arcs");
                com.ptc.pfc.pfcDetail.DetailItems foundLines;
                try { foundLines = call("Model2D.ListDetailItems(summary_arcs)", () -> drawing.ListDetailItems(com.ptc.pfc.pfcDetail.DetailType.DETAIL_ENTITY, null)); }
                catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { foundLines = null; }
                final com.ptc.pfc.pfcDetail.DetailItems lines = foundLines;
                entities = lines == null ? 0 : call("DetailItems.getarraysize(arc_count)", () -> lines.getarraysize());
                for (int i = 0; lines != null && i < call("DetailItems.getarraysize(arcs)", () -> lines.getarraysize()); i++) {
                    final int entityIndex = i;
                    com.ptc.pfc.pfcDetail.DetailEntityItem entity = (com.ptc.pfc.pfcDetail.DetailEntityItem) call("DetailItems.get(arc)", () -> lines.get(entityIndex));
                    com.ptc.pfc.pfcDetail.DetailEntityInstructions instruction = call("DetailEntityItem.GetInstructions(arc)", () -> entity.GetInstructions());
                    if (!(call("DetailEntityInstructions.GetGeometry(arc_type)", () -> instruction.GetGeometry()) instanceof com.ptc.pfc.pfcGeometry.ArcDescriptor)) continue;
                    com.ptc.pfc.pfcGeometry.ArcDescriptor arc = (com.ptc.pfc.pfcGeometry.ArcDescriptor) call("DetailEntityInstructions.GetGeometry(arc_value)", () -> instruction.GetGeometry());
                    View2D view = call("DetailEntityInstructions.GetView(arc)", () -> instruction.GetView());
                    int number = call("View2D.GetSheetNumber(arc)", () -> view.GetSheetNumber());
                    Transform3D transform = call("Model2D.GetSheetTransform(arc)", () -> drawing.GetSheetTransform(number));
                    Point3D centerPoint = call("ArcDescriptor.GetCenter", () -> arc.GetCenter());
                    List<Object> center = onSheet(transform, centerPoint);
                    Point3D edge = call("Point3D.create(arc_edge)", () -> Point3D.create());
                    for (int j = 0; j < 3; j++) {
                        final int axis = j;
                        Point3D repeatedCenter = call("ArcDescriptor.GetCenter(axis_" + axis + ")", () -> arc.GetCenter());
                        double coordinate = call("Point3D.get(arc_center_" + axis + ")", () -> repeatedCenter.get(axis));
                        var vector = call("ArcDescriptor.GetVector1(axis_" + axis + ")", () -> arc.GetVector1());
                        double direction = call("Vector3D.get(arc_axis_" + axis + ")", () -> vector.get(axis));
                        double radius = call("ArcDescriptor.GetRadius(axis_" + axis + ")", () -> arc.GetRadius());
                        run("Point3D.set(arc_edge_" + axis + ")", () -> edge.set(axis, coordinate + direction * radius));
                    }
                    List<Object> rim = onSheet(transform, edge);
                    arcs.add(Json.map("id", call("DetailEntityItem.GetId(arc)", () -> entity.GetId()), "sheet", number,
                            "center", center, "radius", Math.hypot(((Number)rim.get(0)).doubleValue() - ((Number)center.get(0)).doubleValue(),
                                    ((Number)rim.get(1)).doubleValue() - ((Number)center.get(1)).doubleValue()),
                            "start_angle", call("ArcDescriptor.GetStartAngle", () -> arc.GetStartAngle()),
                            "end_angle", call("ArcDescriptor.GetEndAngle", () -> arc.GetEndAngle()),
                            "source", "DetailEntityItem.GetInstructions/ArcDescriptor; sheet transform"));
                }
            } catch (Throwable uncounted) {
                NativeReadTrace.rethrowFatal(uncounted);
                entities = null;
                arcs = null;
            }
            NativeReadTrace.stage("service.summary.final_fields");
            String drawingName = fileNameTraced(drawing);
            Object entityReadback = DrawingReadback.entityReport(drawing);
            NativeReadTrace.stage("service.summary.datums[delegated_internal_getters_uninstrumented]");
            Object datums = call("Tolerances.datumRows[delegated_internal_getters_uninstrumented]", () -> Tolerances.datumRows(drawing));
            NativeReadTrace.stage("service.summary.gtols[delegated_internal_getters_uninstrumented]");
            Object gtols = call("Tolerances.gtolRows[delegated_internal_getters_uninstrumented]", () -> Tolerances.gtolRows(drawing));
            NativeReadTrace.stage("service.summary.origin_modified");
            String origin = originTraced(drawing);
            Boolean modified = modifiedTraced(drawing);
            NativeReadTrace.ensureHealthy();
            return Json.map("model", drawingName, "type", "drawing", "projection", projection,
                    "draft_entities", entities, "draft_arcs", arcs,
                    "draft_entity_readback", entityReadback,
                    "models", models, "sheets", sheets,
                    "views", views, "dimensions_shown", shownCount, "dimensions", dimensions, "notes", notes,
                    "tables", tables, "symbols", symbols, "datums", datums,
                    "gtols", gtols, "origin", origin, "modified", modified);
        }
    }

    /**
     * A view as the drawing holds it, its outline in sheet coordinates. GetOutline answers in
     * screen coordinates; the sheet's transform takes them to the sheet, in drawing units from
     * its lower left corner.
     */
    static Map<String, Object> viewRow(Model2D drawing, View2D view) throws jxthrowable {
        try (var viewScope = NativeReadTrace.scope("row", "view")) {
            Outline3D box = call("View2D.GetOutline", () -> view.GetOutline());
            int sheetNumber = call("View2D.GetSheetNumber(row)", () -> view.GetSheetNumber());
            Transform3D sheet = call("Model2D.GetSheetTransform(view_row)", () -> drawing.GetSheetTransform(sheetNumber));
            String modelName = null;
            Map<String, Object> modelReadback = Json.map("complete", false, "value", null,
                    "source", "View2D.GetModel/Model.GetFileName");
            try {
                Model model = call("View2D.GetModel", () -> view.GetModel());
                modelName = model == null ? null : fileNameTraced(model);
                if (modelName == null || modelName.trim().isEmpty()) {
                    modelReadback.put("reason", model == null ? "native_model_absent" : "native_model_name_absent");
                } else {
                    modelReadback.put("complete", true);
                    modelReadback.put("value", modelName);
                }
            } catch (Throwable unavailable) {
                NativeReadTrace.rethrowFatal(unavailable);
                modelReadback.put("reason", "native_getter_failed");
                modelReadback.put("error", Failures.error(unavailable));
            }
            String type = null;
            String parent = null;
            try {
                var nativeType = call("WView2D.GetViewType", () -> ((com.ptc.wfc.wfcView2D.WView2D) view).GetViewType());
                type = call("DrawingViewType.enumName", () -> Creo.enumName(nativeType)).replace("VIEW_", "")
                        .toLowerCase(Locale.ROOT);
                View2D above = call("WView2D.GetParentView(row)", () -> ((com.ptc.wfc.wfcView2D.WView2D) view).GetParentView());
                parent = above == null ? null : call("View2D.GetName(parent_row)", () -> above.GetName());
            } catch (Throwable unknown) {
                NativeReadTrace.rethrowFatal(unknown);
                // Reported as null.
            }
            Map<String, Object> relations = DrawingReadback.view(view);
            // The identity getter has already run in DrawingReadback.view. A later dependency
            // failure does not erase that ID, and a missing ID must not trigger a second call.
            Object viewId = relations.get("id");
            Map<String, Object> idReadback = Json.map("complete", viewId != null, "value", viewId,
                    "source", "WView2D.GetViewId");
            if (viewId == null) {
                idReadback.put("reason", "native_identity_unavailable");
                if (relations.containsKey("error")) idReadback.put("error", relations.get("error"));
            }
            String name = call("View2D.GetName(row)", () -> view.GetName());
            NativeReadTrace.known("view_name", name);
            NativeReadTrace.known("view_sheet", sheetNumber);
            boolean named = name != null && !name.trim().isEmpty();
            Map<String, Object> sheetReadback = Json.map("complete", sheetNumber > 0, "value", sheetNumber,
                    "source", "View2D.GetSheetNumber");
            if (sheetNumber <= 0) sheetReadback.put("reason", "native_sheet_not_positive");
            Map<String, Object> nameReadback = Json.map("complete", named, "value", name,
                    "source", "View2D.GetName");
            if (!named) nameReadback.put("reason", "native_view_name_absent");
            Map<String, Object> identity = Json.map("complete", Boolean.TRUE.equals(modelReadback.get("complete"))
                    && viewId != null && sheetNumber > 0 && named, "model", modelReadback,
                    "id", idReadback, "sheet", sheetReadback, "name", nameReadback);
            Map<String, Object> exploded = Json.map("complete", false, "value", null,
                    "source", "WView2D.IsExplodedState");
            if (!(view instanceof com.ptc.wfc.wfcView2D.WView2D)) {
                exploded.put("reason", "native_view_interface_unavailable");
            } else {
                try {
                    boolean value = call("WView2D.IsExplodedState", () -> ((com.ptc.wfc.wfcView2D.WView2D) view).IsExplodedState());
                    exploded.put("value", value);
                    exploded.put("complete", true);
                } catch (Throwable unavailable) {
                    NativeReadTrace.rethrowFatal(unavailable);
                    exploded.put("reason", "native_getter_failed");
                    exploded.put("error", Failures.error(unavailable));
                }
            }
            double scale = call("View2D.GetScale", () -> view.GetScale());
            Object outline = null;
            if (box != null) {
                Point3D low = call("Outline3D.get(view_low)", () -> box.get(0));
                List<Object> lower = onSheet(sheet, low);
                Point3D high = call("Outline3D.get(view_high)", () -> box.get(1));
                outline = java.util.Arrays.asList(lower, onSheet(sheet, high));
            }
            Object sections = call("Views.sectionsOf[delegated_internal_getters_uninstrumented]", () -> Views.sectionsOf(view));
            Object sectionArea = call("Views.sectionArea[delegated_internal_getters_uninstrumented]", () -> Views.sectionArea(view));
            Object display = call("Views.display[delegated_internal_getters_uninstrumented]", () -> Views.display(view));
            return Json.map("name", name, "id", viewId, "dependency_readback", relations,
                    "view_identity_readback", identity, "exploded_display_readback", exploded,
                    "named_exploded_state_reference", Json.map("complete", false, "status", "not_checked", "value", null,
                            "reason", "no supported per-view named exploded-state identity getter established"),
                    "sheet", sheetNumber, "scale", scale, "model", modelName, "outline", outline,
                    "type", type, "parent", parent, "sections", sections, "section_area", sectionArea,
                    "display", display);
        }
    }

    static List<Object> onSheet(Transform3D sheet, Point3D screen) throws jxthrowable {
        Point3D p = sheet == null ? screen : call("Transform3D.TransformPoint(to_sheet)", () -> sheet.TransformPoint(screen));
        double x = call("Point3D.get(sheet_x)", () -> p.get(0));
        double y = call("Point3D.get(sheet_y)", () -> p.get(1));
        return java.util.Arrays.asList(Geometry.round(x), Geometry.round(y));
    }

    /** A point given in sheet coordinates, as the screen coordinates views are placed by. */
    static Point3D toScreen(Model2D drawing, int sheet, double x, double y) throws jxthrowable {
        Transform3D toSheet = call("Model2D.GetSheetTransform(to_screen)", () -> drawing.GetSheetTransform(sheet));
        Point3D p = point(x, y);
        if (toSheet == null) {
            return p;
        }
        run("Transform3D.Invert(to_screen)", () -> toSheet.Invert());
        return call("Transform3D.TransformPoint(to_screen)", () -> toSheet.TransformPoint(p));
    }

    /** The views a drawing holds, counted without holding toolkit objects past the call. */
    private static final class View2Ds {
        private final int count;

        View2Ds(Drawing drawing) throws jxthrowable {
            com.ptc.pfc.pfcView2D.View2Ds all = call("Model2D.List2DViews(count_helper)", () -> drawing.List2DViews());
            count = all == null ? 0 : call("View2Ds.getarraysize(count_helper)", () -> all.getarraysize());
        }

        int count() {
            return count;
        }
    }
}
