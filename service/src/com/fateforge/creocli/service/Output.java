package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.CoordAxis;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcModel.ExportType;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcView.ViewOwner;
import com.ptc.pfc.pfcWindow.DotsPerInch;
import com.ptc.pfc.pfcWindow.JPEGImageExportInstructions;
import com.ptc.pfc.pfcWindow.RasterDepth;
import com.ptc.pfc.pfcWindow.Window;
import com.ptc.pfc.pfcWindow.pfcWindow;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * model.render and model.export: what leaves Creo as a file -- a picture of the model for an
 * agent that can look, and the exchange formats a design is delivered in. The CLI names a
 * directory inside the workspace that holds nothing yet; the reply lists what Creo wrote
 * there, since some exports choose their own file names.
 */
final class Output {

    /** Raster size is given to Creo in inches at a DPI; 100 DPI makes inches x 100 pixels. */
    private static final double DPI = 100.0;

    private Output() {
    }

    // ------------------------------------------------------------------ model.render

    static Map<String, Object> render(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model model = Creo.model(session, Json.string(request, "model"));
        if (!(model instanceof ViewOwner) || model.GetType().getValue() == ModelType._MDL_DRAWING) {
            throw new Failures.Refusal("E_VALIDATION", "render shows parts and assemblies; " + Creo.fileName(model)
                    + " is a drawing");
        }
        File file = new File(Json.string(request, "file"));
        String view = Json.string(request, "view", "isometric");
        int width = Json.integer(request, "width", 1024);
        int height = Json.integer(request, "height", 768);
        if (width < 64 || width > 4000 || height < 64 || height > 4000 || file.exists())
            throw new Failures.Refusal("E_VALIDATION", "invalid raster size or existing file");
        Map<String, Object> before = renderState(request);
        Window previous = session.GetCurrentWindow();
        Window window = Creo.window(session, model);
        ViewOwner owner = (ViewOwner) model;
        if (!"current".equals(view)) {
            String required = "isometric".equals(view) ? "FRONT" : view.toUpperCase(Locale.ROOT);
            if (!((List<?>) before.get("named_views")).contains(required))
                throw new Failures.Refusal("E_NOT_FOUND", "saved orientation missing: " + required);
        }
        List<Rotation> rotations = new ArrayList<>();
        com.ptc.pfc.pfcBase.ScreenTransform currentScreen = window.GetScreenTransform();
        com.ptc.pfc.pfcBase.ScreenTransform screen = com.ptc.pfc.pfcBase.pfcBase.ScreenTransform_Create(
                currentScreen.GetPanX(), currentScreen.GetPanY(), currentScreen.GetZoom());
        Map<String, Object> configs = (Map<String, Object>) before.get("datums");
        Throwable failure = null;
        List<Object> cleanup = new ArrayList<>();
        try {
            if (previous.GetId() != window.GetId())
                throw new IllegalStateException("render target context drifted before export");
            orientReversibly(owner, view, rotations);
            // Refit also changes the model view scale/shift; render keeps the caller framing.
            for (String option : DATUM_DISPLAY) session.SetConfigOption(option, "no");
            window.Repaint();
            JPEGImageExportInstructions jpeg =
                    pfcWindow.JPEGImageExportInstructions_Create(width / DPI, height / DPI);
            jpeg.SetDotsPerInch(DotsPerInch.RASTERDPI_100);
            jpeg.SetImageDepth(RasterDepth.RASTERDEPTH_24);
            window.ExportRasterImage(file.getPath(), jpeg);
        } catch (Throwable problem) {
            failure = problem;
        } finally {
            cleanup.addAll(restore(session, owner, window, previous, rotations, screen, configs));
        }
        if (failure != null || !cleanup.isEmpty()) {
            Map<String, Object> after;
            try { after = renderState(request); }
            catch (Throwable unreadable) { after = Json.map("complete", false, "error", Failures.error(unreadable)); }
            throw new Failures.Stage(cleanup.isEmpty() ? "render_export" : "render_restore",
                    failure != null ? failure : new IllegalStateException("render restoration failed"),
                    Json.map("file", file.getPath(), "file_exists", file.isFile(),
                            "before", before, "after", after, "restoration_errors", cleanup));
        }
        return Json.map("model", Creo.fileName(model), "view", view, "width", width, "height", height,
                "window_opened", false, "files", written(file.getParentFile()));
    }

    /** Every cleanup action is attempted; the caller must fail if any result is returned. */
    static List<Object> restore(Session session, ViewOwner owner, Window window, Window previous,
            List<Rotation> rotations, com.ptc.pfc.pfcBase.ScreenTransform screen, Map<String, Object> configs) {
        List<Object> cleanup = new ArrayList<>();
            for (String option : DATUM_DISPLAY) {
                try { session.SetConfigOption(option, (String) configs.get(option)); }
                catch (Throwable problem) { cleanup.add(Json.map("stage", option, "error", Failures.error(problem))); }
            }
            // Undo the exact successful rotations, preserving scale/shift that MatrixSet refits.
            for (int i = rotations.size() - 1; i >= 0; i--) {
                Rotation rotation = rotations.get(i);
                try { owner.CurrentViewRotate(rotation.axis, -rotation.degrees); }
                catch (Throwable problem) { cleanup.add(Json.map("stage", "view_transform", "error", Failures.error(problem))); }
            }
            try {
                if (!sameScreen(window.GetScreenTransform(), screen)) window.SetScreenTransform(screen);
            }
            catch (Throwable problem) { cleanup.add(Json.map("stage", "screen_transform", "error", Failures.error(problem))); }
            try { window.Repaint(); }
            catch (Throwable problem) { cleanup.add(Json.map("stage", "repaint", "error", Failures.error(problem))); }
            try {
                if (previous.GetId() != window.GetId())
                    cleanup.add(Json.map("stage", "active_window", "reason", "synchronous model activation is not qualified; no unsupported restoration attempted"));
            } catch (Throwable problem) {
                cleanup.add(Json.map("stage", "active_window", "error", Failures.error(problem)));
            }
        return cleanup;
    }

    private static boolean sameScreen(com.ptc.pfc.pfcBase.ScreenTransform a,
            com.ptc.pfc.pfcBase.ScreenTransform b) throws jxthrowable {
        return a != null && b != null && a.GetPanX() == b.GetPanX()
                && a.GetPanY() == b.GetPanY() && a.GetZoom() == b.GetZoom();
    }

    static final class Rotation {
        final CoordAxis axis;
        final double degrees;
        Rotation(CoordAxis axis, double degrees) { this.axis = axis; this.degrees = degrees; }
    }

    private static double[][] orientation(Transform3D value) throws jxthrowable {
        com.ptc.pfc.pfcBase.Matrix3D matrix = value.GetMatrix();
        double[][] result = new double[3][3];
        for (int r = 0; r < 3; r++) {
            double length = Math.sqrt(matrix.get(r,0)*matrix.get(r,0) + matrix.get(r,1)*matrix.get(r,1) + matrix.get(r,2)*matrix.get(r,2));
            if (!Double.isFinite(length) || length <= 0) throw new IllegalStateException("invalid orientation");
            for (int c = 0; c < 3; c++) result[r][c] = matrix.get(r,c) / length;
        }
        return result;
    }

    private static void turn(ViewOwner owner, List<Rotation> done, CoordAxis axis, double radians) throws jxthrowable {
        if (Math.abs(radians) < 1e-12) return;
        double degrees = Math.toDegrees(radians);
        owner.CurrentViewRotate(axis, degrees);
        done.add(new Rotation(axis, degrees));
    }

    static void orientReversibly(ViewOwner owner, String view, List<Rotation> done) throws jxthrowable {
        if ("current".equals(view)) return;
        double[][] from = orientation(owner.GetCurrentViewTransform());
        double[][] desired = orientation(owner.GetView("isometric".equals(view) ? "FRONT" : view.toUpperCase(Locale.ROOT)).GetTransform());
        double[][] delta = new double[3][3];
        for (int r=0; r<3; r++) for (int c=0; c<3; c++) for (int k=0; k<3; k++) delta[r][c] += from[k][r]*desired[k][c];
        double y = Math.asin(Math.max(-1, Math.min(1, -delta[0][2])));
        double x = Math.abs(Math.cos(y)) > 1e-9 ? Math.atan2(delta[1][2], delta[2][2]) : 0;
        double z = Math.abs(Math.cos(y)) > 1e-9 ? Math.atan2(delta[0][1], delta[0][0]) : Math.atan2(-delta[1][0], delta[1][1]);
        turn(owner, done, CoordAxis.COORD_AXIS_X, x);
        turn(owner, done, CoordAxis.COORD_AXIS_Y, y);
        turn(owner, done, CoordAxis.COORD_AXIS_Z, z);
        double[][] actual = orientation(owner.GetCurrentViewTransform());
        for (int r=0; r<3; r++) for (int c=0; c<3; c++)
            if (Math.abs(actual[r][c]-desired[r][c]) > 1e-7)
                throw new IllegalStateException("native orientation did not match requested saved view");
        if ("isometric".equals(view)) {
            turn(owner, done, CoordAxis.COORD_AXIS_Y, Math.toRadians(-45));
            turn(owner, done, CoordAxis.COORD_AXIS_X, Math.toRadians(35.264389682754654));
        }
    }

    static Map<String, Object> renderState(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model model = Creo.model(session, Json.string(request, "model"));
        PresentationOps.requireTargetContext(session, model);
        Window target = Creo.window(session, model), active = session.GetCurrentWindow();
        Model currentModel = session.GetCurrentModel();
        if (!(model instanceof ViewOwner) || target == null || active == null)
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "render requires an existing model and active window");
        if (active.GetModel() == null || active.GetModel().GetType().getValue() == ModelType._MDL_DRAWING)
            throw new Failures.Refusal("E_UNSUPPORTED", "render inspection requires part or assembly window context");
        if (active.GetId() != target.GetId())
            throw new Failures.Refusal("E_UNSUPPORTED", "inactive-window presentation getters are outside the render profile; select the target window before preview");
        com.ptc.pfc.pfcBase.Matrix3D matrix = ((ViewOwner) model).GetCurrentViewTransform().GetMatrix();
        List<Object> rows = new ArrayList<>(), views = new ArrayList<>();
        for (int r = 0; r < 4; r++) {
            List<Object> row = new ArrayList<>();
            for (int c = 0; c < 4; c++) row.add(matrix.get(r, c));
            rows.add(row);
        }
        com.ptc.pfc.pfcBase.ScreenTransform screen = target.GetScreenTransform();
        Map<String, Object> configs = new java.util.LinkedHashMap<>();
        for (String option : DATUM_DISPLAY) {
            String value = session.GetConfigOption(option);
            if (value == null || value.isEmpty())
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "effective datum option unavailable: " + option);
            configs.put(option, value);
        }
        com.ptc.pfc.pfcView.Views named = ((ViewOwner) model).ListViews();
        for (int i = 0; named != null && i < named.getarraysize(); i++) views.add(named.get(i).GetName());
        // Bind pixels to actual source RGB readback, separately from physical materials.
        Map<String, Object> colors = new java.util.TreeMap<>();
        com.ptc.pfc.pfcModel.Models present = session.ListModels();
        for (int i = 0; present != null && i < present.getarraysize(); i++) {
            Model part = present.get(i);
            if (part.GetType().getValue() == ModelType._MDL_PART)
                colors.put(Creo.fileName(part), AppearanceOps.get(Json.map("model", Creo.fileName(part))));
        }
        return Json.map("complete", true, "model", Creo.fileName(model),
                "window", String.valueOf(target.GetId()), "active_window", String.valueOf(active.GetId()),
                "active_model", Creo.fileName(active.GetModel()), "view_transform", rows,
                "current_model", Creo.fileName(currentModel),
                "current_model_type", Creo.typeName(currentModel.GetType()),
                "window_model", Creo.fileName(active.GetModel()),
                "window_model_type", Creo.typeName(active.GetModel().GetType()),
                "context_complete", true,
                "graphics", Json.map("width", target.GetGraphicsAreaWidth(), "height", target.GetGraphicsAreaHeight()),
                "screen", Json.map("pan_x", screen.GetPanX(), "pan_y", screen.GetPanY(), "zoom", screen.GetZoom()),
                "datums", configs, "modified", Creo.modified(model), "named_views", views,
                "native_part_appearances", colors,
                "explosion", model instanceof com.ptc.pfc.pfcAssembly.Assembly
                        ? Assemblies.explosion(session, (com.ptc.pfc.pfcAssembly.Assembly) model) : null,
                "source", "ViewOwner.GetCurrentViewTransform/Window.GetScreenTransform/GetCurrentWindow/GetConfigOption");
    }

    static Map<String, Object> inspectJpeg(Map<String, Object> request) throws Exception {
        File file = new File(Json.string(request, "file"));
        java.awt.image.BufferedImage image;
        List<Object> warnings = new ArrayList<>();
        String format;
        try (javax.imageio.stream.ImageInputStream input = javax.imageio.ImageIO.createImageInputStream(file)) {
            java.util.Iterator<javax.imageio.ImageReader> readers = javax.imageio.ImageIO.getImageReaders(input);
            if (!readers.hasNext()) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "no image decoder");
            javax.imageio.ImageReader reader = readers.next();
            try {
                reader.addIIOReadWarningListener((source, warning) -> warnings.add(warning));
                reader.setInput(input);
                format = reader.getFormatName();
                image = reader.read(0);
            } finally { reader.dispose(); }
        }
        if (image == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "image decoder returned no image");
        int[] low = {255, 255, 255}, high = {0, 0, 0};
        int stride = Math.max(1, (int) Math.sqrt((long) image.getWidth() * image.getHeight() / 1000000.0));
        for (int y = 0; y < image.getHeight(); y += stride) for (int x = 0; x < image.getWidth(); x += stride) {
            int rgb = image.getRGB(x, y);
            for (int channel = 0; channel < 3; channel++) {
                int value = (rgb >> (channel * 8)) & 255;
                low[channel] = Math.min(low[channel], value); high[channel] = Math.max(high[channel], value);
            }
        }
        return Json.map("decoded", warnings.isEmpty() && "JPEG".equalsIgnoreCase(format), "warnings", warnings,
                "width", image.getWidth(), "height", image.getHeight(),
                "sampled_rgb_range", Math.max(high[0]-low[0], Math.max(high[1]-low[1], high[2]-low[2])), "source", "independent ImageIO.read of actual file", "geometry_verified", false);
    }

    /** The config options that draw datums; each is off while the picture is taken. */
    private static final String[] DATUM_DISPLAY = {"display_planes", "display_axes", "display_points",
            "display_coord_sys"};

    private static <T> T withoutDatums(Session session, String[] options, int from, Creo.Work<T> work)
            throws Exception {
        if (from == options.length) {
            return work.run();
        }
        return Creo.withConfig(session, options[from], "no", "yes",
                () -> withoutDatums(session, options, from + 1, work));
    }

    // ------------------------------------------------------------------ model.export

    static Map<String, Object> export(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Model model = Creo.model(session, Json.string(request, "model"));
        String format = Json.string(request, "format");
        File file = new File(Json.string(request, "file"));
        boolean drawing = model.GetType().getValue() == ModelType._MDL_DRAWING;
        switch (format) {
            case "step":
                solidOnly(model, drawing, format);
                model.ExportIntf3D(file.getPath(), ExportType.EXPORT_STEP, null);
                break;
            case "iges":
                solidOnly(model, drawing, format);
                com.ptc.pfc.pfcExport.GeometryFlags flags = com.ptc.pfc.pfcExport.pfcExport.GeometryFlags_Create();
                flags.SetAsSolids(true);
                model.Export(file.getPath(), com.ptc.pfc.pfcExport.pfcExport.IGES3DNewExportInstructions_Create(
                        com.ptc.pfc.pfcExport.AssemblyConfiguration.EXPORT_ASM_SINGLE_FILE, flags));
                break;
            case "stl":
                solidOnly(model, drawing, format);
                model.Export(file.getPath(), com.ptc.pfc.pfcModel.pfcModel.STLBinaryExportInstructions_Create(
                        coordinateSystem(model)));
                break;
            case "pdf":
                if (!drawing) {
                    throw new Failures.Refusal("E_VALIDATION", "pdf exports drawings; " + Creo.fileName(model)
                            + " is not one");
                }
                // A drawing for a person to read: datum planes and axes drawn over it are noise.
                withoutDatums(session, DATUM_DISPLAY, 0, () -> {
                    model.Export(file.getPath(), com.ptc.pfc.pfcExport.pfcExport.PDFExportInstructions_Create());
                    return null;
                });
                break;
            default:
                throw new Failures.Refusal("E_VALIDATION", "'format' must be step, iges, stl or pdf");
        }
        return Json.map("model", Creo.fileName(model), "format", format, "files", written(file.getParentFile()));
    }

    private static void solidOnly(Model model, boolean drawing, String format) {
        if (drawing) {
            throw new Failures.Refusal("E_VALIDATION", format + " exports parts and assemblies; use pdf for a drawing");
        }
    }

    /** The first coordinate system of the model, which STL output is expressed in. */
    private static String coordinateSystem(Model model) throws jxthrowable {
        ModelItems systems = model.ListItems(ModelItemType.ITEM_COORD_SYS);
        return systems == null || systems.getarraysize() == 0 ? null : systems.get(0).GetName();
    }

    /** What the output directory holds after Creo wrote into it. */
    private static List<Object> written(File directory) {
        List<Object> out = new ArrayList<>();
        File[] files = directory == null ? null : directory.listFiles();
        if (files != null) {
            for (File f : files) {
                if (f.isFile()) {
                    out.add(Json.map("path", f.getPath(), "bytes", f.length()));
                }
            }
        }
        return out;
    }
}
