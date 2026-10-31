package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.Matrix3D;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.pfcBase;
import com.ptc.pfc.pfcDetail.DetailNoteItem;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModel2D.Model2D;
import com.ptc.pfc.pfcSession.Session;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Internal, explicitly enabled one-stage experiments. Never a public command or recovery. */
final class NoteDiagnostic {
    private static final Map<String, HeldNote> HELD = new LinkedHashMap<>();

    private record HeldNote(String drawing, DetailNoteItem note, Integer observedId) {}

    private NoteDiagnostic() {}

    private static <T> T call(String label, NativeReadTrace.Call<T> getter) throws jxthrowable {
        return NativeReadTrace.call(label, getter);
    }

    static Map<String, Object> op(Session session, Map<String, Object> request) throws Throwable {
        if (!"1".equals(System.getenv("CREO_CLI_NATIVE_DIAGNOSTIC")))
            throw new Failures.Refusal("E_VALIDATION", "internal annotation diagnostics are disabled");
        String action = Json.string(request, "action");
        String wanted = Json.string(request, "model");
        if (!wanted.toLowerCase(java.util.Locale.ROOT).endsWith(".drw"))
            throw new Failures.Refusal("E_VALIDATION", "diagnostics require an explicit drawing filename");
        NativeReadTrace.stage("diagnostic.note." + action);
        try (var scope = NativeReadTrace.scope("experiment_action", action, "requested_drawing", wanted)) {
            Creo.Name name = Creo.name(wanted);
            Model model = call("Session.GetModel(diagnostic)", () -> session.GetModel(name.base, ModelType.MDL_DRAWING));
            String actual = Drawings.fileNameTraced(model);
            if (!actual.equalsIgnoreCase(wanted))
                throw new Failures.Refusal("E_VALIDATION", "diagnostic drawing identity differs from the request");
            NativeReadTrace.known("actual_drawing", actual);
            ModelType type = call("Model.GetType(diagnostic)", model::GetType);
            if (call("ModelType.getValue(diagnostic)", type::getValue) != ModelType._MDL_DRAWING)
                throw new Failures.Refusal("E_VALIDATION", "diagnostic target is not a drawing");
            Model2D drawing = (Model2D) model;
            Object value;
            switch (action) {
                case "context": {
                    Model current = call("Session.GetCurrentModel(diagnostic)", session::GetCurrentModel);
                    var window = call("Session.GetCurrentWindow(diagnostic)", session::GetCurrentWindow);
                    Model windowModel = window == null ? null : call("Window.GetModel(diagnostic)", window::GetModel);
                    int sheet = call("Model2D.GetCurrentSheetNumber(diagnostic)", drawing::GetCurrentSheetNumber);
                    value = Json.map("current_model", Drawings.fileNameTraced(current),
                            "window_model", Drawings.fileNameTraced(windowModel), "sheet", sheet);
                    break;
                }
                case "inventory": value = inventory(drawing); break;
                case "select": {
                    int id = Json.integer(request, "note_id");
                    String reference = unusedReference(request);
                    var items = call("Model2D.ListDetailItems(select)", () -> drawing.ListDetailItems(
                            com.ptc.pfc.pfcDetail.DetailType.DETAIL_NOTE, null));
                    int count = items == null ? 0 : call("DetailItems.getarraysize(select)", items::getarraysize);
                    if (count != 1) throw new Failures.Refusal("E_VALIDATION", "minimal diagnostic requires exactly one native note");
                    var item = call("DetailItems.get(select)", () -> items.get(0));
                    if (!(item instanceof DetailNoteItem))
                        throw new Failures.Refusal("E_VALIDATION", "native item does not implement DetailNoteItem");
                    DetailNoteItem note = (DetailNoteItem) item;
                    int found = call("DetailNoteItem.GetId(select)", note::GetId);
                    if (found != id) throw new Failures.Refusal("E_VALIDATION", "native note identity differs");
                    NativeReadTrace.known("note_id", found);
                    HELD.put(reference, new HeldNote(actual, note, found));
                    value = Json.map("note_ref", reference, "note_id", found, "native_membership_drawing", actual);
                    break;
                }
                case "create_only": {
                    String reference = unusedReference(request);
                    String text = Json.string(request, "text");
                    if (text.length() > 1024 || text.split("\n", -1).length > 2)
                        throw new Failures.Refusal("E_VALIDATION", "diagnostic text is limited to two short synthetic lines");
                    DetailNoteItem note = Drawings.createNoteOnly(drawing, request);
                    HELD.put(reference, new HeldNote(actual, note, null));
                    value = Json.map("note_ref", reference, "create_returned", true, "id_observed", false,
                            "show_invoked", false, "repaint_invoked", false, "save_invoked", false);
                    break;
                }
                case "repaint_only":
                    Drawings.repaintTraced(session);
                    value = Json.map("repaint_status", NativeReadTrace.knownValue("repaint_status"));
                    break;
                case "sheet_transform": value = transform(drawing, Json.integer(request, "sheet")); break;
                default: {
                    String reference = Json.string(request, "note_ref");
                    HeldNote held = HELD.get(reference);
                    if (held == null || !held.drawing().equalsIgnoreCase(actual))
                        throw new Failures.Refusal("E_VALIDATION", "no note reference retained for this drawing in this instance");
                    DetailNoteItem note = held.note();
                    if (held.observedId() != null) NativeReadTrace.known("note_id", held.observedId());
                    if (held.observedId() == null && !action.equals("identity") && !action.equals("show_only"))
                        throw new Failures.Refusal("E_VALIDATION", "observe the retained native note identity before diagnostic reads");
                    try (var subject = NativeReadTrace.scope("diagnostic_note_ref", reference)) {
                        switch (action) {
                            case "show_only":
                                NativeReadTrace.run("DetailNoteItem.Show(diagnostic)", note::Show);
                                NativeReadTrace.effect("diagnostic_note_shown", Json.map("note_ref", reference, "actual_model", actual));
                                value = Json.map("show_returned", true); break;
                            case "identity": {
                                int id = call("DetailNoteItem.GetId(diagnostic)", note::GetId);
                                if (held.observedId() != null && id != held.observedId())
                                    throw new Failures.Refusal("E_CONFLICT", "retained diagnostic note identity changed; do not reselect or replay");
                                NativeReadTrace.known("note_id", id);
                                HELD.put(reference, new HeldNote(actual, note, id));
                                value = Json.map("note_id", id, "java_class", note.getClass().getName()); break;
                            }
                            case "attachment": value = Drawings.noteAttachment(note); break;
                            case "text_symbolic": value = Json.map("text", Drawings.noteText(Drawings.noteTextLines(note, false))); break;
                            case "text_numeric": value = Json.map("text", Drawings.noteText(Drawings.noteTextLines(note, true))); break;
                            case "leaders": value = Drawings.noteLeaders(note); break;
                            case "location": value = Drawings.noteLocation(drawing, note, Json.integer(request, "sheet")); break;
                            case "anchor_raw": value = anchor(drawing, note, Json.integer(request, "sheet")); break;
                            case "envelope3d_line": value = envelope(drawing, note, request, false); break;
                            case "envelope2d_line_raw": value = envelope(drawing, note, request, true); break;
                            case "envelope2d_line_validated": {
                                int line = Json.integer(request, "line");
                                if (line < 0 || line > 1)
                                    throw new Failures.Refusal("E_VALIDATION", "minimal diagnostic line is zero or one");
                                value = Drawings.noteLineBounds(drawing, note, Json.integer(request, "sheet"), line);
                                break;
                            }
                            default: throw new Failures.Refusal("E_VALIDATION", "unknown fixed diagnostic stage");
                        }
                    }
                }
            }
            NativeReadTrace.check();
            return Json.map("diagnostic_only", true, "not_public_acceptance", true, "action", action,
                    "actual_drawing", actual, "value", value, "save_proven", false);
        }
    }

    private static String unusedReference(Map<String, Object> request) {
        String reference = Json.string(request, "note_ref");
        if (HELD.containsKey(reference) || HELD.size() >= 8)
            throw new Failures.Refusal("E_VALIDATION", "diagnostic reference already used or bounded capacity exhausted; never replay creation");
        return reference;
    }

    private static List<Object> inventory(Model2D drawing) throws jxthrowable {
        var items = call("Model2D.ListDetailItems(inventory)", () -> drawing.ListDetailItems(
                com.ptc.pfc.pfcDetail.DetailType.DETAIL_NOTE, null));
        int count = items == null ? 0 : call("DetailItems.getarraysize(inventory)", items::getarraysize);
        if (count > 1) throw new Failures.Refusal("E_VALIDATION", "minimal diagnostic has more than one note");
        List<Object> result = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            final int index = i;
            var item = call("DetailItems.get(inventory)", () -> items.get(index));
            int id = call("DetailItem.GetId(inventory)", item::GetId);
            result.add(Json.map("id", id, "java_class", item.getClass().getName(), "inventory_index", index));
        }
        return result;
    }

    private static Map<String, Object> transform(Model2D drawing, int sheet) throws jxthrowable {
        Transform3D transform = call("Model2D.GetSheetTransform(diagnostic)", () -> drawing.GetSheetTransform(sheet));
        Matrix3D matrix = call("Transform3D.GetMatrix(diagnostic)", transform::GetMatrix);
        List<Object> rows = new ArrayList<>();
        for (int i = 0; i < 4; i++) {
            List<Object> row = new ArrayList<>();
            for (int j = 0; j < 4; j++) {
                final int r = i, c = j;
                row.add(call("Matrix3D.get(" + r + "," + c + ")", () -> matrix.get(r, c)));
            }
            rows.add(row);
        }
        return Json.map("sheet", sheet, "raw_matrix", rows, "source", "screen_to_drawing_sheet_transform", "rounded", false);
    }

    private static Map<String, Object> anchor(Model2D drawing, DetailNoteItem note, int sheet) throws jxthrowable {
        var instructions = call("DetailNoteItem.GetInstructions(anchor_raw)", () -> note.GetInstructions(true));
        var leaders = call("DetailNoteInstructions.GetLeader(anchor_raw)", instructions::GetLeader);
        var attachment = call("DetailLeaders.GetItemAttachment(anchor_raw)", leaders::GetItemAttachment);
        if (!(attachment instanceof com.ptc.pfc.pfcDetail.FreeAttachment))
            throw new Failures.Refusal("E_VALIDATION", "raw anchor comparison requires an actual free attachment");
        Point3D screen = call("FreeAttachment.GetAttachmentPoint(anchor_raw)", () ->
                ((com.ptc.pfc.pfcDetail.FreeAttachment) attachment).GetAttachmentPoint());
        List<Object> screenCoordinates = new ArrayList<>(), paperCoordinates = new ArrayList<>();
        double[] rawScreen = new double[3];
        for (int i = 0; i < 3; i++) {
            final int axis = i;
            rawScreen[i] = call("Point3D.get(screen_anchor," + axis + ")", () -> screen.get(axis));
            screenCoordinates.add(rawScreen[i]);
        }
        // TransformPoint may return its input object. Preserve the native anchor's
        // raw values first and transform only an independently allocated copy.
        Point3D input = call("Point3D.create(anchor_copy)", Point3D::create);
        for (int i = 0; i < 3; i++) {
            final int axis = i;
            NativeReadTrace.run("Point3D.set(anchor_copy," + axis + ")", () -> input.set(axis, rawScreen[axis]));
        }
        Transform3D transform = call("Model2D.GetSheetTransform(anchor_raw)", () -> drawing.GetSheetTransform(sheet));
        Point3D paper = call("Transform3D.TransformPoint(anchor_copy)", () -> transform.TransformPoint(input));
        for (int i = 0; i < 3; i++) {
            final int axis = i;
            paperCoordinates.add(call("Point3D.get(paper_anchor," + axis + ")", () -> paper.get(axis)));
        }
        return Json.map("screen_raw", screenCoordinates, "paper_raw", paperCoordinates,
                "sheet", sheet, "rounded", false, "source", "actual_free_attachment_and_screen_to_drawing_transform");
    }

    private static Map<String, Object> envelope(Model2D drawing, DetailNoteItem note,
            Map<String, Object> request, boolean twoD) throws jxthrowable {
        int line = Json.integer(request, "line");
        if (line < 0 || line > 1) throw new Failures.Refusal("E_VALIDATION", "minimal diagnostic line is zero or one");
        try (var scope = NativeReadTrace.scope("line_index", String.valueOf(line), "diagnostic_envelope", twoD ? "2d" : "3d")) {
            List<Object> corners = new ArrayList<>();
            if (twoD) {
                var envelope = call("DetailNoteItem.GetLineEnvelope(diagnostic)", () -> note.GetLineEnvelope(line));
                for (int i = 0; i < 2; i++) {
                    final int oi = i;
                    var outline = call("Envelope2D.get(" + oi + ")", () -> envelope.get(oi));
                    for (int j = 0; j < 2; j++) {
                        final int ci = j;
                        var point = call("Outline2D.get(" + ci + ")", () -> outline.get(ci));
                        double x = call("Point2D.get(0)", () -> point.get(0));
                        double y = call("Point2D.get(1)", () -> point.get(1));
                        corners.add(List.of(x, y));
                    }
                }
            } else {
                var envelope = call("WDetailNoteItem.Get3DLineEnvelope(diagnostic)", () ->
                        ((com.ptc.wfc.wfcDetail.WDetailNoteItem) note).Get3DLineEnvelope(line));
                for (int i = 0; i < 2; i++) {
                    final int oi = i;
                    var outline = call("Envelope3D.get(" + oi + ")", () -> envelope.get(oi));
                    for (int j = 0; j < 2; j++) {
                        final int ci = j;
                        Point3D point = call("Outline3D.get(" + ci + ")", () -> outline.get(ci));
                        List<Object> raw = new ArrayList<>();
                        for (int k = 0; k < 3; k++) {
                            final int axis = k;
                            raw.add(call("Point3D.get(" + axis + ")", () -> point.get(axis)));
                        }
                        corners.add(raw);
                    }
                }
            }
            return Json.map("line_index", line, "raw_corners", corners, "rounded", false,
                    "coordinate_provenance", twoD ? "official_screen_xy" : "Java_API_coordinate_system_unspecified",
                    "layout_protection_complete", false);
        }
    }
}
