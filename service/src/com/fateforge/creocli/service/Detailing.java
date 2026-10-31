package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.cipjava.realseq;
import com.ptc.cipjava.stringseq;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.Vector2D;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcDetail.DetailItem;
import com.ptc.pfc.pfcDetail.DetailItems;
import com.ptc.pfc.pfcDetail.DetailLeaders;
import com.ptc.pfc.pfcDetail.DetailNoteItem;
import com.ptc.pfc.pfcDetail.DetailSymbolDefItem;
import com.ptc.pfc.pfcDetail.DetailSymbolInstInstructions;
import com.ptc.pfc.pfcDetail.DetailSymbolInstItem;
import com.ptc.pfc.pfcDetail.DetailTextLines;
import com.ptc.pfc.pfcDetail.DetailTexts;
import com.ptc.pfc.pfcDetail.DetailType;
import com.ptc.pfc.pfcDetail.DetailVariantTexts;
import com.ptc.pfc.pfcDetail.FreeAttachment;
import com.ptc.pfc.pfcDetail.pfcDetail;
import com.ptc.pfc.pfcDimension2D.Dimension2D;
import com.ptc.pfc.pfcDimension2D.DimensionSenses;
import com.ptc.pfc.pfcDimension2D.DrawingDimCreateInstructions;
import com.ptc.pfc.pfcDimension2D.OrientationHint;
import com.ptc.pfc.pfcDimension2D.pfcDimension2D;
import com.ptc.pfc.pfcDrawing.Drawing;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel2D.Model2D;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.Selections;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcTable.ColumnCreateOptions;
import com.ptc.pfc.pfcTable.ColumnJustification;
import com.ptc.pfc.pfcTable.ParamMode;
import com.ptc.pfc.pfcTable.Table;
import com.ptc.pfc.pfcTable.TableCreateInstructions;
import com.ptc.pfc.pfcTable.TableSizeType;
import com.ptc.pfc.pfcTable.Tables;
import com.ptc.pfc.pfcTable.pfcTable;
import com.ptc.pfc.pfcView2D.View2D;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Detailing a drawing past the model's dimensions, as a person finishes one: notes edited,
 * moved and removed; dimensions moved; reference dimensions between edges of a view; tables
 * (a title block, a list); symbols from Creo's library or the user's. Positions are sheet
 * coordinates from the lower left corner, in the drawing's units, converted to the screen
 * coordinates the toolkit places by.
 */
final class Detailing {
    // A variable text stands alone: \name\ not inside a path such as D:\dir\sub\, which a
    // definition can carry too (Creo's own ISO 1302 symbol records where it was made).
    private static final Pattern VARIABLE = Pattern.compile(
            "(?<![A-Za-z0-9_:\\\\])\\\\([A-Za-z_][A-Za-z0-9_]{0,40})\\\\(?![A-Za-z0-9_\\\\])");

    private Detailing() {
    }

    // Retain the SDK's checked contract without asking a proxy for diagnostic metadata.
    private static <T> T call(String name, NativeReadTrace.Call<T> body) throws jxthrowable {
        return NativeReadTrace.call(name, body);
    }

    /** Required cell membership must not turn a returned getter error into a partial set. */
    private static <T> T cellCall(String name, NativeReadTrace.Call<T> body) throws Exception {
        try {
            return call(name, body);
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            throw incompleteCellRead(name, failure, "returned_error");
        }
    }

    private static Service.ToolkitFailure incompleteCellRead(String name, Throwable failure, String state) {
        String failureClass = failure == null ? null : failure.getClass().getName();
        Map<String, Object> detail = Json.map("code", "E_VERIFY_INCOMPLETE", "retryable", false,
                "message", "Required drawing table-cell ownership could not be completely read.",
                "failed_getter", name, "exception_class", failureClass, "native_read_state", state,
                "cause", failure == null ? null : Json.map("code", "E_CREO",
                        "classification", "returned_exception", "exception_class", failureClass,
                        "toolkit_details", "not_read_for_diagnostic_reporting"));
        for (String key : List.of("phase", "actual_drawing", "selected_table_id", "table_inventory_index",
                "table_id", "table_row", "table_column", "note_id", "cell_notes_caller_phase",
                "cell_notes_traversal", "balloon_count_caller_phase", "balloon_count_traversal")) {
            Object value = NativeReadTrace.knownValue(key);
            if (value != null) detail.put(key, value);
        }
        return new Service.ToolkitFailure(detail);
    }

    // ------------------------------------------------------------------ notes

    static Map<String, Object> editNote(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        DetailNoteItem note = note(drawing, Json.number(request, "note"));
        String text = Json.string(request, "text", null);
        List<?> at = at(request, false);
        if (text == null && at == null) {
            throw new Failures.Refusal("E_VALIDATION", "give the note's new 'text', its new place 'at', or both");
        }
        if (at != null) {
            com.ptc.pfc.pfcDetail.Attachment attached = note.GetInstructions(true).GetLeader().GetItemAttachment();
            if (!(attached instanceof FreeAttachment)) {
                throw new Failures.Refusal("E_CONFLICT", "the note is attached to something on the drawing; only "
                        + "a free note is moved");
            }
        }
        if (text != null) {
            note.SetTextLines(lines(text));
        }
        if (at != null) {
            note.SetFreeAttachment(pfcDetail.FreeAttachment_Create(screen(drawing, at)));
        }
        note.Show();
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("note", Drawings.noteRow(drawing, note));
        return out;
    }

    private static DetailNoteItem note(Drawing drawing, double id) throws jxthrowable {
        DetailItem item = null;
        try {
            item = drawing.GetDetailItem(DetailType.DETAIL_NOTE, (int) id);
        } catch (Throwable absent) {
            // Refused below.
        }
        if (!(item instanceof DetailNoteItem)) {
            throw new Failures.Refusal("E_NOT_FOUND", "the drawing has no note " + (int) id);
        }
        return (DetailNoteItem) item;
    }

    // ------------------------------------------------------------------ removing

    /**
     * Remove something the drawing itself owns: a note, a table, a symbol, or a dimension
     * made on the drawing, named note:<id>, table:<id>, symbol:<id>, dimension:<name>. A
     * model's dimension is the model's: hide-dimension takes it off the drawing instead.
     */
    static Map<String, Object> remove(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        String item = Json.string(request, "item");
        if (item.startsWith("view:") && request.get("expected_view_id") != null) {
            View2D selected = drawing.GetViewByName(item.substring(5));
            if (selected == null || !String.valueOf(((com.ptc.wfc.wfcView2D.WView2D) selected).GetViewId()).equals(request.get("expected_view_id"))
                    || selected.GetSheetNumber() != ((Number) request.get("expected_sheet")).intValue())
                throw new Failures.Refusal("E_CONFLICT", "view identity or sheet changed before dispatch");
        }
        Drawings.front(session, drawing);
        String kind = item.contains(":") ? item.substring(0, item.indexOf(':')) : "";
        String key = item.substring(item.indexOf(':') + 1);
        Map<String, Object> removed = Json.map("item", item);
        switch (kind) {
            case "note": {
                DetailNoteItem note = note(drawing, id(key));
                removed.putAll(Drawings.noteRow(drawing, note));
                note.Delete();
                break;
            }
            case "table": {
                Table table = table(drawing, id(key));
                removed.putAll(tableRow(drawing, table));
                drawing.DeleteTable(table, Boolean.FALSE);
                break;
            }
            case "symbol": {
                DetailSymbolInstItem symbol = symbol(drawing, id(key));
                removed.putAll(symbolRow(drawing, symbol));
                symbol.Delete();
                break;
            }
            case "dimension": {
                Dimension2D d = null;
                for (Dimension2D own : drawingDimensions(drawing)) {
                    if (own.GetName().equalsIgnoreCase(key)) {
                        d = own;
                    }
                }
                if (d == null) {
                    throw new Failures.Refusal("E_NOT_FOUND", "the drawing has made no dimension " + key
                            + "; a model's dimension is taken off with hide-dimension");
                }
                removed.putAll(Json.map("name", d.GetName(), "id", d.GetId(),
                        "value", Geometry.round(d.GetDimValue()), "reference", d.GetIsReference()));
                deleteNatively(drawing, d);
                break;
            }
            case "gtol": {
                com.ptc.wfc.wfcGTol.GTol frame = Tolerances.gtol(drawing, key);
                removed.putAll(Json.map("id", frame.GetId(), "model", Creo.fileName((Model) frame.GetDBParent()),
                        "value", frame.GetValueString()));
                frame.Delete();
                break;
            }
            case "datum": {
                com.ptc.wfc.wfcAnnotation.SetDatumTag tag = Tolerances.datum(drawing, key);
                removed.putAll(Json.map("id", tag.GetId(), "label", tag.GetLabel()));
                tag.Delete();
                break;
            }
            case "view": {
                View2D view = drawing.GetViewByName(key);
                if (view == null) {
                    throw new Failures.Refusal("E_NOT_FOUND", "the drawing has no view named " + key);
                }
                com.ptc.pfc.pfcView2D.View2Ds children = ((com.ptc.wfc.wfcView2D.WView2D) view).GetChildren();
                if (children != null && children.getarraysize() > 0) {
                    List<Object> names = new ArrayList<>();
                    for (int i = 0; i < children.getarraysize(); i++) {
                        names.add(children.get(i).GetName());
                    }
                    throw new Failures.Refusal("E_CONFLICT", "view " + key + " has views taken from it: " + names
                            + "; remove those first");
                }
                removed.putAll(Drawings.viewRow(drawing, view));
                view.Delete(Boolean.FALSE);
                break;
            }
            default:
                throw new Failures.Refusal("E_VALIDATION",
                        "'item' is note:<id>, table:<id>, symbol:<id>, dimension:<name>, view:<name>, "
                                + "gtol:<id> or datum:<label>");
        }
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("removed", removed);
        return out;
    }

    /**
     * A dimension made on the drawing, deleted through the native library: Dimension2D's own
     * EraseFromModel2D answers without error and leaves it in the drawing (measured), and Java
     * has no delete for a Dimension2D.
     */
    private static void deleteNatively(Drawing drawing, Dimension2D d) throws Exception {
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "deleting a dimension made on the drawing needs the "
                    + "native library, which this Creo session has not loaded: " + Service.sketchLibraryStatus());
        }
        com.ptc.pfc.pfcProToolkit.FunctionReturn result = Service.sketchLibrary().ExecuteFunction(
                Service.DIMENSION_DELETE_FUNCTION, namedDimension(drawing, Creo.fileName(drawing), d));
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "ProDimensionDelete answered " + result.GetFunctionReturn()
                            + " (PTC lists it under the TOOLKIT for 3D Drawings licence)",
                    "toolkit_error", result.GetFunctionReturn()));
        }
    }

    private static double id(String key) {
        if (!key.matches("[0-9]{1,9}")) {
            throw new Failures.Refusal("E_VALIDATION", "a note's, table's or symbol's id is a whole number");
        }
        return Double.parseDouble(key);
    }

    private static Table table(Drawing drawing, double id) throws jxthrowable {
        try (var scope = NativeReadTrace.scope("table_lookup_requested_id", String.valueOf((int) id))) {
            Tables tables = call("Model2D.ListTables(table_lookup)", () -> drawing.ListTables());
            for (int i = 0; tables != null && i < call("Tables.getarraysize(table_lookup)", () -> tables.getarraysize()); i++) {
                final int tableIndex = i;
                try (var tableScope = NativeReadTrace.scope("table_inventory_index", String.valueOf(tableIndex),
                        "table_id", "unobserved")) {
                    Table selected = call("Tables.get(table_lookup)", () -> tables.get(tableIndex));
                    int actualId = call("Table.GetId(table_lookup)", () -> selected.GetId());
                    NativeReadTrace.known("table_id", actualId);
                    if (actualId == (int) id) {
                        if (call("Table.CheckIfIsFromFormat(table_lookup)", () -> selected.CheckIfIsFromFormat(0))) {
                            throw new Failures.Refusal("E_CONFLICT", "table " + (int) id + " belongs to the drawing's "
                                    + "format, not to the drawing");
                        }
                        return selected;
                    }
                }
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "the drawing has no table " + (int) id);
    }

    private static DetailSymbolInstItem symbol(Drawing drawing, double id) throws jxthrowable {
        DetailItem item = null;
        try {
            item = drawing.GetDetailItem(DetailType.DETAIL_SYM_INSTANCE, (int) id);
        } catch (Throwable absent) {
            // Refused below.
        }
        if (!(item instanceof DetailSymbolInstItem)) {
            throw new Failures.Refusal("E_NOT_FOUND", "the drawing has no symbol " + (int) id);
        }
        return (DetailSymbolInstItem) item;
    }

    static DetailTextLines lines(String text) throws jxthrowable {
        DetailTextLines lines = DetailTextLines.create();
        for (String line : text.split("\n", -1)) {
            DetailTexts texts = DetailTexts.create();
            texts.append(pfcDetail.DetailText_Create(line));
            lines.append(pfcDetail.DetailTextLine_Create(texts));
        }
        return lines;
    }

    // ------------------------------------------------------------------ dimensions

    /**
     * Move a shown dimension's text to a point on the sheet; the model's value is not touched.
     * A model's dimension and one made on the drawing move the same way, through the native
     * library, so that both read back by the measure they were placed by.
     */
    static Map<String, Object> moveDimension(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        String wanted = Json.string(request, "dimension");
        Point3D where = screen(drawing, at(request, true));
        Object[] found = dimension(drawing, wanted);
        com.ptc.pfc.pfcDimension.BaseDimension d = (com.ptc.pfc.pfcDimension.BaseDimension) found[1];
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "moving a dimension on a drawing needs the native "
                    + "library, which this Creo session has not loaded: " + Service.sketchLibraryStatus());
        }
        com.ptc.pfc.pfcArgument.Arguments in = namedDimension(drawing, (String) found[0], d);
        in.append(pfcArgument.Argument_Create("x", pfcArgument.CreateDoubleArgValue(where.get(0))));
        in.append(pfcArgument.Argument_Create("y", pfcArgument.CreateDoubleArgValue(where.get(1))));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.DIMENSION_MOVE_FUNCTION, in);
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "ProDrawingDimensionMove answered " + result.GetFunctionReturn(),
                    "toolkit_error", result.GetFunctionReturn()));
        }
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("moved", Json.map("name", d.GetName(), "id", d.GetId()));
        return out;
    }

    /**
     * Where a dimension made on the drawing has its text, on the sheet: read natively by
     * ProDimlocationTextGet, the measure ProDrawingDimensionMove places by. Dimension2D's
     * own GetLocation reads the text box's centre, which is not where the text was put
     * (measured: 2.6 mm across and 7.4 mm along a vertical dimension). Null when the native
     * library is not loaded or Creo cannot say.
     */
    private static List<Object> placeOf(Model2D drawing, Transform3D sheet, Dimension2D d) {
        if (Service.sketchLibrary() == null) {
            return null;
        }
        try {
            com.ptc.pfc.pfcProToolkit.FunctionReturn result = Service.sketchLibrary().ExecuteFunction(
                    Service.DIMENSION_PLACE_FUNCTION, namedDimension(drawing, Creo.fileName((Model) drawing), d));
            if (result.GetFunctionReturn() != 0) {
                return null;
            }
            Double x = null;
            Double y = null;
            com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
            for (int i = 0; out != null && i < out.getarraysize(); i++) {
                if ("x".equals(out.get(i).GetLabel())) {
                    x = out.get(i).GetValue().GetDoubleValue();
                } else if ("y".equals(out.get(i).GetLabel())) {
                    y = out.get(i).GetValue().GetDoubleValue();
                }
            }
            return x == null || y == null ? null : Drawings.onSheet(sheet, point(x, y));
        } catch (Throwable unread) {
            return null;
        }
    }

    /** A shown dimension's text moved to a point on the screen, natively; whether it moved. */
    static boolean moveNatively(Drawing drawing, String owner, com.ptc.pfc.pfcDimension.BaseDimension d,
                                Point3D where) {
        if (Service.sketchLibrary() == null) {
            return false;
        }
        try {
            com.ptc.pfc.pfcArgument.Arguments in = namedDimension(drawing, owner, d);
            in.append(pfcArgument.Argument_Create("x", pfcArgument.CreateDoubleArgValue(where.get(0))));
            in.append(pfcArgument.Argument_Create("y", pfcArgument.CreateDoubleArgValue(where.get(1))));
            return Service.sketchLibrary().ExecuteFunction(Service.DIMENSION_MOVE_FUNCTION, in).GetFunctionReturn() == 0;
        } catch (Throwable refused) {
            return false;
        }
    }

    /** The arguments that name a dimension to the native library: its drawing, owner, id and kind. */
    private static com.ptc.pfc.pfcArgument.Arguments namedDimension(Model2D drawing, String owner,
            com.ptc.pfc.pfcDimension.BaseDimension d) throws jxthrowable {
        String type = owner.toLowerCase(java.util.Locale.ROOT).replaceFirst("^.*\\.", "");
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(pfcArgument.Argument_Create("drawing", pfcArgument.CreateStringArgValue(
                Creo.fileName((Model) drawing).replaceFirst("(?i)\\.drw$", ""))));
        in.append(pfcArgument.Argument_Create("owner",
                pfcArgument.CreateStringArgValue(owner.replaceFirst("(?i)\\.(prt|asm|drw)$", ""))));
        in.append(pfcArgument.Argument_Create("owner_type", pfcArgument.CreateStringArgValue(type)));
        in.append(pfcArgument.Argument_Create("dimension", pfcArgument.CreateIntArgValue(d.GetId())));
        in.append(pfcArgument.Argument_Create("reference", pfcArgument.CreateIntArgValue(
                d.GetType().getValue() == ModelItemType._ITEM_REF_DIMENSION ? 1 : 0)));
        return in;
    }

    private static Point3D point(double x, double y) throws jxthrowable {
        Point3D p = Point3D.create();
        p.set(0, x);
        p.set(1, y);
        p.set(2, 0.0);
        return p;
    }

    static Object[] shownDimension(Drawing drawing, String wanted) throws jxthrowable {
        return dimension(drawing, wanted);
    }

    /** A shown model dimension, d12 or d12@part.prt, or one of the drawing's own: [owner, dimension]. */
    private static Object[] dimension(Drawing drawing, String wanted) throws jxthrowable {
        String name = wanted.contains("@") ? wanted.substring(0, wanted.indexOf('@')) : wanted;
        String model = wanted.contains("@") ? wanted.substring(wanted.indexOf('@') + 1) : null;
        List<Object[]> hits = new ArrayList<>();
        for (Object[] row : Drawings.shownDimensionObjects(drawing)) {
            com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension) row[1];
            if (name.equalsIgnoreCase(d.GetName()) && (model == null || model.equalsIgnoreCase((String) row[0]))) {
                hits.add(row);
            }
        }
        for (Dimension2D d : drawingDimensions(drawing)) {
            if (name.equalsIgnoreCase(d.GetName())
                    && (model == null || model.equalsIgnoreCase(Creo.fileName(drawing)))) {
                hits.add(new Object[] {Creo.fileName(drawing), d});
            }
        }
        if (hits.isEmpty()) {
            throw new Failures.Refusal("E_NOT_FOUND", "the drawing shows no dimension " + wanted);
        }
        if (hits.size() > 1) {
            throw new Failures.Refusal("E_CONFLICT", "two dimensions are named " + wanted + "; write it as name@model");
        }
        return hits.get(0);
    }

    /** The drawing's own dimensions, reference ones included. */
    static List<Dimension2D> drawingDimensions(Model2D drawing) throws jxthrowable {
        List<Dimension2D> out = new ArrayList<>();
        for (ModelItemType type : new ModelItemType[] {ModelItemType.ITEM_DIMENSION, ModelItemType.ITEM_REF_DIMENSION}) {
            ModelItems items = null;
            try {
                items = ((Model) drawing).ListItems(type);
            } catch (Throwable none) {
                // None of this kind.
            }
            for (int i = 0; items != null && i < items.getarraysize(); i++) {
                if (items.get(i) instanceof Dimension2D) {
                    out.add((Dimension2D) items.get(i));
                }
            }
        }
        return out;
    }

    static List<Object> drawingDimensionRows(Model2D drawing) throws jxthrowable {
        List<Object> rows = new ArrayList<>();
        for (Dimension2D d : drawingDimensions(drawing)) {
            View2D view = null;
            try {
                view = drawing.GetViewDisplaying(d);
            } catch (Throwable unknown) {
                // A dimension without a known view has no proved sheet-coordinate frame.
            }
            Integer sheetNumber = view == null ? null : view.GetSheetNumber();
            Transform3D sheet = sheetNumber == null ? null : drawing.GetSheetTransform(sheetNumber);
            Map<String, Object> row = Json.map("name", d.GetName(), "id", d.GetId(), "model", Creo.fileName((Model) drawing),
                    "value", Geometry.round(d.GetDimValue()),
                    "type", Creo.enumName(d.GetDimType()).replace("DIM_", "").toLowerCase(java.util.Locale.ROOT),
                    "feature", null, "view", view == null ? null : view.GetName(), "sheet", sheetNumber,
                    "reference", d.GetIsReference(), "at", sheet == null ? null : placeOf(drawing, sheet, d),
                    "box", sheet == null ? null : Drawings.textBox(drawing, sheet, d));
            Selections points = d.GetAttachmentPoints();
            DimensionSenses senses = d.GetDimensionSenses();
            List<Object> attachments = new ArrayList<>();
            if (points == null || senses == null || points.getarraysize() != senses.getarraysize()) {
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "drawing dimension attachment getter is incomplete");
            }
            for (int index = 0; index < points.getarraysize(); index++) {
                Selection pick = points.get(index);
                ModelItem item = pick.GetSelItem();
                Object sense = senses.get(index);
                String meaning = sense instanceof com.ptc.pfc.pfcDimension2D.PointDimensionSense
                        ? Creo.enumName(((com.ptc.pfc.pfcDimension2D.PointDimensionSense) sense).GetPointType())
                                .replace("DIMPOINT_", "").toLowerCase(java.util.Locale.ROOT) : "auto";
                attachments.add(Json.map("ref", "edge:" + item.GetId(), "model", Creo.fileName(pick.GetSelModel()),
                        "sense", meaning, "source", "Dimension2D.GetAttachmentPoints/GetDimensionSenses"));
            }
            row.put("associative", d.GetIsAssociative());
            row.put("attachments", attachments);
            rows.add(row);
        }
        return rows;
    }

    private static String viewName(Model2D drawing, Dimension2D d) {
        try {
            View2D in = drawing.GetViewDisplaying(d);
            return in == null ? null : in.GetName();
        } catch (Throwable unknown) {
            return null;
        }
    }

    /**
     * A reference dimension between two straight edges of the model as a view shows them --
     * the size the model has but no feature dimensions, such as a total thickness. Creo
     * measures it; it drives nothing.
     */
    static Map<String, Object> addDimension(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        View2D view = drawing.GetViewByName(Json.string(request, "view"));
        if (view == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(request, "view"));
        }
        Model shown = view.GetModel();
        if (!(shown instanceof Solid)) {
            throw new Failures.Refusal("E_CONFLICT", "the view shows no part to dimension");
        }
        Selections attachments = Selections.create();
        DimensionSenses senses = DimensionSenses.create();
        for (String key : new String[] {"from", "to"}) {
            ModelItem item = Geometry.item((Solid) shown, Json.string(request, key));
            if (item.GetType().getValue() != ModelItemType._ITEM_EDGE) {
                throw new Failures.Refusal("E_VALIDATION", "'" + key + "' is a straight edge: edge:<id>");
            }
            Selection pick = pfcSelect.CreateModelItemSelection(item, null);
            pick.SetSelView2D(view);
            attachments.append(pick);
            String sense = Json.string(request, key + "_sense", "auto");
            com.ptc.pfc.pfcDimension2D.DimensionPointType pointType =
                    "center".equals(sense) ? com.ptc.pfc.pfcDimension2D.DimensionPointType.DIMPOINT_CENTER
                    : "end1".equals(sense) ? com.ptc.pfc.pfcDimension2D.DimensionPointType.DIMPOINT_END1
                    : "end2".equals(sense) ? com.ptc.pfc.pfcDimension2D.DimensionPointType.DIMPOINT_END2
                    : "midpoint".equals(sense) ? com.ptc.pfc.pfcDimension2D.DimensionPointType.DIMPOINT_MIDPOINT : null;
            senses.append(pointType == null ? pfcDimension2D.EmptyDimensionSense_Create()
                    : pfcDimension2D.PointDimensionSense_Create(pointType));
        }
        String orient = Json.string(request, "orientation", "slanted");
        OrientationHint hint = "horizontal".equals(orient) ? OrientationHint.ORIENTHINT_HORIZONTAL
                : "vertical".equals(orient) ? OrientationHint.ORIENTHINT_VERTICAL : OrientationHint.ORIENTHINT_SLANTED;
        Point3D where = screen(drawing, at(request, true));
        Vector2D text = Vector2D.create();
        text.set(0, where.get(0));
        text.set(1, where.get(1));
        DrawingDimCreateInstructions how = pfcDimension2D.DrawingDimCreateInstructions_Create(attachments, senses,
                text, hint);
        how.SetIsRefDimension(true);
        how.SetDisplay(true);
        Dimension2D made = drawing.CreateDrawingDimension(how);
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        Object row = Json.map("name", made.GetName(), "id", made.GetId(), "model", Creo.fileName(drawing),
                "value", Geometry.round(made.GetDimValue()), "reference", made.GetIsReference());
        for (Object own : drawingDimensionRows(drawing)) {
            if (((Map<?, ?>) own).get("id").equals(made.GetId())) {
                row = own;
            }
        }
        out.put("dimension", row);
        return out;
    }

    // ------------------------------------------------------------------ tables

    /**
     * A table whose top left corner is at a point on the sheet: column widths and row
     * heights in the drawing's units, the cells' text row by row, regions merged.
     */
    static Map<String, Object> addTable(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        Map<String, Object> symbolSpec = request.get("projection_symbol") instanceof Map
                ? Json.object(request.get("projection_symbol"), "'projection_symbol'") : null;
        String symbolProjection = null;
        if (symbolSpec != null) {
            symbolProjection = Drawings.options(drawing).get("projection_type");
            if (!"first_angle".equalsIgnoreCase(symbolProjection) && !"third_angle".equalsIgnoreCase(symbolProjection)) {
                throw new Failures.Refusal("E_CONFLICT", "the drawing's projection is unknown; no table or projection symbol was created");
            }
        }
        List<?> columns = list(request, "columns");
        List<?> rows = list(request, "rows");
        TableCreateInstructions how = pfcTable.TableCreateInstructions_Create(screen(drawing, at(request, true)));
        how.SetSizeType(TableSizeType.TABLESIZE_BY_LENGTH);
        ColumnCreateOptions data = ColumnCreateOptions.create();
        for (Object width : columns) {
            data.append(pfcTable.ColumnCreateOption_Create(ColumnJustification.COL_JUSTIFY_LEFT, number(width)));
        }
        how.SetColumnData(data);
        realseq heights = realseq.create();
        for (Object height : rows) {
            heights.append(number(height));
        }
        how.SetRowHeights(heights);
        Table table = drawing.CreateTable(how);
        if (request.get("merge") instanceof List) {
            for (Object region : (List<?>) request.get("merge")) {
                List<?> r = (List<?>) region;
                table.MergeRegion(pfcTable.TableCell_Create(integer(r.get(0)), integer(r.get(1))),
                        pfcTable.TableCell_Create(integer(r.get(2)), integer(r.get(3))), Boolean.FALSE);
            }
        }
        if (request.get("cells") instanceof List) {
            List<?> cells = (List<?>) request.get("cells");
            for (int r = 0; r < cells.size(); r++) {
                List<?> row = (List<?>) cells.get(r);
                for (int c = 0; c < row.size(); c++) {
                    Object value = row.get(c);
                    if (value == null || String.valueOf(value).isEmpty()) {
                        continue;
                    }
                    stringseq text = stringseq.create();
                    for (String line : String.valueOf(value).split("\n", -1)) {
                        text.append(line);
                    }
                    table.SetText(pfcTable.TableCell_Create(r + 1, c + 1), text);
                }
            }
        }
        table.Display();
        Map<String, Object> symbol = symbolSpec != null ? projectionSymbol(drawing, symbolSpec, symbolProjection) : null;
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("table", tableRow(drawing, table));
        if (symbol != null) {
            out.put("projection_symbol", symbol);
        }
        return out;
    }

    /**
     * ISO 5456-2's projection symbol, drawn in draft lines centred at a point on the sheet: a
     * truncated cone seen from its side, its small end on the left, and seen end on -- two
     * circles -- to its right in first angle, to its left in third. The drawing's own
     * projection decides which.
     */
    private static Map<String, Object> projectionSymbol(Drawing drawing, Map<String, Object> spec, String projection) throws Exception {
        boolean first = "first_angle".equalsIgnoreCase(projection);
        List<?> at = (List<?>) spec.get("at");
        double cx = number(at.get(0)), cy = number(at.get(1));
        double big = Json.number(spec, "height");
        double small = big / 2, length = big, gap = 0.35 * big;
        double width = length + gap + big;
        double coneLeft = first ? cx - width / 2 : cx + width / 2 - length;
        double coneRight = coneLeft + length;
        double circles = first ? cx + width / 2 - big / 2 : cx - width / 2 + big / 2;
        int sheet = drawing.GetCurrentSheetNumber();
        double[][] lines = {
            {coneLeft, cy - small / 2, coneLeft, cy + small / 2},
            {coneRight, cy - big / 2, coneRight, cy + big / 2},
            {coneLeft, cy + small / 2, coneRight, cy + big / 2},
            {coneLeft, cy - small / 2, coneRight, cy - big / 2},
        };
        int drawn = 0;
        for (double[] l : lines) {
            draft(drawing, com.ptc.pfc.pfcGeometry.pfcGeometry.LineDescriptor_Create(
                    Drawings.toScreen(drawing, sheet, l[0], l[1]), Drawings.toScreen(drawing, sheet, l[2], l[3])));
            drawn++;
        }
        com.ptc.pfc.pfcBase.Vector3D xAxis = com.ptc.pfc.pfcBase.Vector3D.create();
        com.ptc.pfc.pfcBase.Vector3D yAxis = com.ptc.pfc.pfcBase.Vector3D.create();
        for (int i = 0; i < 3; i++) {
            xAxis.set(i, i == 0 ? 1.0 : 0.0);
            yAxis.set(i, i == 1 ? 1.0 : 0.0);
        }
        Point3D centre = Drawings.toScreen(drawing, sheet, circles, cy);
        Point3D rim = Drawings.toScreen(drawing, sheet, circles + 1.0, cy);
        double perUnit = Math.hypot(rim.get(0) - centre.get(0), rim.get(1) - centre.get(1));
        for (double diameter : new double[] {big, small}) {
            // PTC requires a full ArcDescriptor for drawing circles (DetailEntityInstructions).
            draft(drawing, com.ptc.pfc.pfcGeometry.pfcGeometry.ArcDescriptor_Create(
                    xAxis, yAxis, centre, 0.0, 2.0 * Math.PI, diameter / 2 * perUnit));
            drawn++;
        }
        return Json.map("projection", first ? "first_angle" : "third_angle", "at", java.util.Arrays.asList(cx, cy),
                "height", big, "entities", drawn);
    }

    private static void draft(Drawing drawing, com.ptc.pfc.pfcGeometry.CurveDescriptor curve) throws jxthrowable {
        com.ptc.pfc.pfcDetail.DetailEntityItem line = (com.ptc.pfc.pfcDetail.DetailEntityItem) drawing.CreateDetailItem(
                com.ptc.pfc.pfcDetail.pfcDetail.DetailEntityInstructions_Create(
                        curve, drawing.GetSheetBackgroundView(drawing.GetCurrentSheetNumber())));
        line.Draw();
    }

    static List<Object> tableRows(Model2D drawing) throws Exception {
        List<Object> out = new ArrayList<>();
        try (var scope = NativeReadTrace.scope("phase", "drawing.table_rows",
                "table_inventory_traversal", String.valueOf(NativeReadTrace.traversal("Detailing.tableRows")))) {
            Tables tables = call("Model2D.ListTables(table_rows)", () -> drawing.ListTables());
            int tableCount = tables == null ? 0 : call("Tables.getarraysize(table_rows)", () -> tables.getarraysize());
            for (int i = 0; i < tableCount; i++) {
                final int tableIndex = i;
                try (var tableScope = NativeReadTrace.scope("table_inventory_index", String.valueOf(tableIndex),
                        "table_id", "unobserved")) {
                    Table table = call("Tables.get(table_rows)", () -> tables.get(tableIndex));
                    out.add(tableRow(drawing, table));
                }
            }
        }
        return out;
    }

    static List<Object> tableRowsStrict(Model2D drawing) throws Exception {
        List<Object> rows = new ArrayList<>();
        try (var scope = NativeReadTrace.scope("phase", "drawing.table_rows_strict",
                "table_inventory_traversal", String.valueOf(NativeReadTrace.traversal("Detailing.tableRowsStrict")))) {
            Tables tables = call("Model2D.ListTables(table_rows_strict)", () -> drawing.ListTables());
            if (tables == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "table inventory is null");
            int tableCount = call("Tables.getarraysize(table_rows_strict)", () -> tables.getarraysize());
            for (int i = 0; i < tableCount; i++) {
                final int tableIndex = i;
                try (var tableScope = NativeReadTrace.scope("table_inventory_index", String.valueOf(tableIndex),
                        "table_id", "unobserved")) {
                    Table table = call("Tables.get(table_rows_strict)", () -> tables.get(tableIndex));
                    rows.add(tableRow(drawing, table));
                }
            }
        }
        return rows;
    }

    private static Map<String, Object> tableRow(Model2D drawing, Table table) throws Exception {
        int rows = call("Table.GetRowCount(table_row)", () -> table.GetRowCount());
        int columns = call("Table.GetColumnCount(table_row)", () -> table.GetColumnCount());
        List<Object> cells = new ArrayList<>();
        List<Object> references = bomReferences(drawing, table);
        for (int r = 1; r <= rows; r++) {
            final int row = r;
            List<Object> line = new ArrayList<>();
            for (int c = 1; c <= columns; c++) {
                final int column = c;
                String text = "";
                try (var cellScope = NativeReadTrace.scope("table_row", String.valueOf(row),
                        "table_column", String.valueOf(column))) {
                    var cell = call("pfcTable.TableCell_Create(table_text)", () -> pfcTable.TableCell_Create(row, column));
                    stringseq got = call("Table.GetText", () -> table.GetText(cell, ParamMode.DWGTABLE_NORMAL));
                    int lineCount = got == null ? 0 : call("stringseq.getarraysize(table_text)", () -> got.getarraysize());
                    StringBuilder all = new StringBuilder();
                    for (int k = 0; k < lineCount; k++) {
                        final int textIndex = k;
                        if (k > 0) {
                            all.append('\n');
                        }
                        try (var textScope = NativeReadTrace.scope("table_text_line_index", String.valueOf(textIndex))) {
                            String textLine = call("stringseq.get(table_text)", () -> got.get(textIndex));
                            all.append(textLine);
                        }
                    }
                    text = all.toString();
                } catch (Throwable merged) {
                    NativeReadTrace.rethrowFatal(merged);
                    // Keep the existing nullable text contract; a traced getter failure
                    // remains distinguishable from an actual empty returned text sequence.
                    text = null;
                }
                line.add(text);

            }
            cells.add(line);
        }
        List<Object> origin = null;
        List<Object> size = null;
        List<Object> outline = null;
        Double rotation = null;
        Integer segments = null;
        Integer targetSheet = null;
        Boolean format = null;
        Throwable placementFailure = null;
        String placementFailureGetter = null;
        try {
            // The first segment's origin: the corner the table was placed by, on the sheet;
            // and its outline's extent, for placing it.
            targetSheet = call("Table.GetSegmentSheet", () -> table.GetSegmentSheet(0));
            NativeReadTrace.known("table_sheet", targetSheet);
            final int sheetNumber = targetSheet;
            Transform3D sheet = call("Model2D.GetSheetTransform(table_row)", () -> drawing.GetSheetTransform(sheetNumber));
            var info = call("Table.GetInfo(table_segment)", () -> table.GetInfo(0));
            Point3D originPoint = call("TableInfo.GetOrigin", () -> info.GetOrigin());
            origin = Drawings.onSheet(sheet, originPoint);
            com.ptc.pfc.pfcBase.Outline3D box = call("TableInfo.GetOutline", () -> info.GetOutline());
            Point3D firstCorner = call("Outline3D.get(table_first_corner)", () -> box.get(0));
            List<Object> a = Drawings.onSheet(sheet, firstCorner);
            Point3D secondCorner = call("Outline3D.get(table_second_corner)", () -> box.get(1));
            List<Object> b = Drawings.onSheet(sheet, secondCorner);
            outline = java.util.Arrays.asList(
                    java.util.Arrays.asList(Math.min((Double) a.get(0), (Double) b.get(0)), Math.min((Double) a.get(1), (Double) b.get(1))),
                    java.util.Arrays.asList(Math.max((Double) a.get(0), (Double) b.get(0)), Math.max((Double) a.get(1), (Double) b.get(1))));
            rotation = call("TableInfo.GetRotation", () -> info.GetRotation());
            segments = call("Table.GetSegmentCount", () -> table.GetSegmentCount());
            size = java.util.Arrays.asList(Geometry.round(Math.abs((Double) b.get(0) - (Double) a.get(0))),
                    Geometry.round(Math.abs((Double) b.get(1) - (Double) a.get(1))));
        } catch (Throwable unplaced) {
            NativeReadTrace.rethrowFatal(unplaced);
            placementFailure = unplaced;
            // A later passive log window may replace latest(); last_call retains
            // the actual end record. Do not attribute a pure Java failure to a
            // preceding successful native call.
            Object lastCall = NativeReadTrace.stopEvidence().get("last_call");
            if (lastCall instanceof Map<?, ?> ended && "threw".equals(ended.get("result"))
                    && unplaced.getClass().getName().equals(ended.get("exception_class"))) {
                Object getter = ended.get("getter");
                placementFailureGetter = getter instanceof String ? (String) getter : null;
            }
            // Optional position remains nullable. Ownership is independently required below.
        }
        if (placementFailure == null) {
            format = cellCall("Table.CheckIfIsFromFormat(table_row)", () -> table.CheckIfIsFromFormat(0));
        }
        if (format == null) {
            Service.ToolkitFailure incomplete = incompleteCellRead(placementFailureGetter,
                    placementFailure, placementFailure == null ? "returned_null" : "required_ownership_not_read");
            incomplete.error.put("required_getter", "Table.CheckIfIsFromFormat(table_row)");
            throw incomplete;
        }
        int tableId = call("Table.GetId(table_row)", () -> table.GetId());
        NativeReadTrace.known("table_id", tableId);
        return Json.map("id", tableId, "rows", rows, "columns", columns, "cells", cells, "at", origin,
                "size", size, "outline", outline, "rotation", rotation, "segments", segments,
                "sheet", targetSheet,
                "bounds_source", outline == null ? null : "Table.GetInfo(0).GetOutline; segment sheet transform",
                "from_format", format, "cell_references", references);
    }

    // ------------------------------------------------------------------ parts lists

    private static List<Object> bomReferences(Model2D drawing, Table table) throws jxthrowable {
        List<Object> rows = new ArrayList<>();
        if (Service.sketchLibrary() == null) return null;
        try (var scope = NativeReadTrace.scope("phase", "drawing.bom_references",
                "bom_reference_traversal", String.valueOf(NativeReadTrace.traversal("Detailing.bomReferences")))) {
            com.ptc.pfc.pfcArgument.Arguments inputs = call("Arguments.create(bom_references)",
                    () -> com.ptc.pfc.pfcArgument.Arguments.create());
            String drawingName = Drawings.fileNameTraced((Model) drawing).replaceFirst("(?i)\\.drw$", "");
            var drawingValue = call("pfcArgument.CreateStringArgValue(bom_reference_drawing)",
                    () -> pfcArgument.CreateStringArgValue(drawingName));
            var drawingArgument = call("pfcArgument.Argument_Create(bom_reference_drawing)",
                    () -> pfcArgument.Argument_Create("drawing", drawingValue));
            NativeReadTrace.run("Arguments.append(bom_reference_drawing)", () -> inputs.append(drawingArgument));
            int tableId = call("Table.GetId(bom_references)", () -> table.GetId());
            NativeReadTrace.known("table_id", tableId);
            var tableValue = call("pfcArgument.CreateIntArgValue(bom_reference_table)", () -> pfcArgument.CreateIntArgValue(tableId));
            var tableArgument = call("pfcArgument.Argument_Create(bom_reference_table)",
                    () -> pfcArgument.Argument_Create("table", tableValue));
            NativeReadTrace.run("Arguments.append(bom_reference_table)", () -> inputs.append(tableArgument));
            com.ptc.pfc.pfcProToolkit.FunctionReturn result = call("NativeLibrary.ExecuteFunction(bom_references)",
                    () -> Service.sketchLibrary().ExecuteFunction(Service.BOM_REFERENCES_FUNCTION, inputs));
            if (call("FunctionReturn.GetFunctionReturn(bom_references)", () -> result.GetFunctionReturn()) != 0) return null;
            com.ptc.pfc.pfcArgument.Arguments output = call("FunctionReturn.GetOutputArguments(bom_references)",
                    () -> result.GetOutputArguments());
            int argumentCount = output == null ? 0 : call("Arguments.getarraysize(bom_references)", () -> output.getarraysize());
            for (int i = 0; i < argumentCount; i++) {
                final int argumentIndex = i;
                try (var argumentScope = NativeReadTrace.scope("bom_reference_argument_index", String.valueOf(argumentIndex))) {
                    var argument = call("Arguments.get(bom_references)", () -> output.get(argumentIndex));
                    String label = call("Argument.GetLabel(bom_references)", () -> argument.GetLabel());
                    if (!"cells".equals(label)) continue;
                    var value = call("Argument.GetValue(bom_references)", () -> argument.GetValue());
                    String contents = call("ArgValue.GetStringValue(bom_references)", () -> value.GetStringValue());
                    for (String line : contents.split(";")) {
                        if (line.isEmpty()) continue;
                        String[] fields = line.split(",");
                        if (fields.length != 5) return null;
                        rows.add(Json.map("row", Integer.parseInt(fields[0]), "column", Integer.parseInt(fields[1]),
                                "region", Integer.parseInt(fields[2]), "model", Creo.plainName(fields[3]),
                                "assembly", Creo.plainName(fields[4]), "source", "ProDwgtableCellRefmodelGet/ProDwgtableCellRegionGet"));
                    }
                }
            }
            return rows;
        } catch (Throwable unreadable) {
            NativeReadTrace.rethrowFatal(unreadable);
            return null;
        }
    }

    /** Resolve a table library entry without retrieving or modifying any drawing. */
    static Map<String, Object> bomTemplate(Map<String, Object> request) throws Exception {
        File file = tableFile(Json.string(request, "table")).getCanonicalFile();
        return Json.map("path", file.getPath(), "source", "active Creo installation table library or explicit file");
    }

    /**
     * A parts list: a table Creo fills from the drawn assembly itself -- a repeat region --
     * retrieved from Creo's table library (text/table, named by its path there without .tbl)
     * or a .tbl file the caller names, its corner at a point on the sheet. It follows the
     * assembly as components come and go.
     */
    static Map<String, Object> addBom(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        Model shown = drawing.GetCurrentSolid();
        if (!(shown instanceof com.ptc.pfc.pfcAssembly.Assembly)) {
            throw new Failures.Refusal("E_CONFLICT", "a parts list is of an assembly; the drawing shows "
                    + (shown == null ? "no model" : Creo.fileName(shown)));
        }
        File file = tableFile(Json.string(request, "table"));
        String expected = Json.string(request, "template_sha256", "");
        if (!expected.isEmpty()) {
            byte[] hash = java.security.MessageDigest.getInstance("SHA-256").digest(java.nio.file.Files.readAllBytes(file.toPath()));
            StringBuilder actual = new StringBuilder();
            for (byte value : hash) actual.append(String.format("%02x", value & 255));
            if (!expected.equals(actual.toString()))
                throw new Failures.Refusal("E_CONFLICT", "BOM template bytes changed before native retrieval");
        }
        com.ptc.pfc.pfcTable.TableRetrieveInstructions how = pfcTable.TableRetrieveInstructions_Create(
                file.getName().replaceFirst("(?i)\\.tbl$", ""), screen(drawing, at(request, true)));
        how.SetPath(file.getParentFile().getPath());
        how.SetReferenceSolid((Solid) shown);
        Table table = drawing.RetrieveTable(how);
        drawing.UpdateTables();
        Creo.repaint(session);
        int tableId = call("Table.GetId(add_bom)", () -> table.GetId());
        NativeReadTrace.known("created_table_id", tableId);
        Map<String, Object> out = Drawings.summary(drawing);
        try {
            // Reuse only this completed native summary, with exact identity. This
            // response does not replace the client's first independent verification.
            out.put("table", SummaryObservation.sameSummaryTable(out, Json.string(request, "model"), tableId));
        } catch (SummaryObservation.Incomplete incomplete) {
            throw new Service.ToolkitFailure(Json.map("code", "E_VERIFY_INCOMPLETE", "retryable", false,
                    "message", "Created BOM table was not uniquely and structurally read in the same drawing summary.",
                    "summary_failure", incomplete.getMessage(), "requested_drawing", Json.string(request, "model"),
                    "created_table_id", tableId, "native_read_state", "summary_returned_incomplete",
                    "automatic_retry", false));
        }
        return out;
    }

    /** Balloons are notes to Creo (" 1 ", measured): counted as the notes past the tables' cells. */
    private static int balloonNotes(Drawing drawing) throws Exception {
        try (var scope = NativeReadTrace.scope("phase", "drawing.balloon_notes",
                "balloon_count_caller_phase", String.valueOf(NativeReadTrace.knownValue("phase")),
                "nullable_inventory_contract", "legacy_null_as_empty; absence_semantics_unverified",
                "balloon_count_traversal", String.valueOf(NativeReadTrace.traversal("Detailing.balloonNotes")))) {
            DetailItems notes = cellCall("Model2D.ListDetailItems(balloon_count)",
                    () -> drawing.ListDetailItems(DetailType.DETAIL_NOTE, null));
            int count = notes == null ? 0 : cellCall("DetailItems.getarraysize(balloon_count)", () -> notes.getarraysize());
            return count - cellNotes(drawing).size();
        }
    }

    /**
     * The parts list's balloons in a view, or in the first view: one per component, numbered
     * by its row, through the native library -- Java has no call that makes them.
     */
    static Map<String, Object> addBalloons(Map<String, Object> request) throws Exception {
        NativeReadTrace.stage("drawing.add_balloons.lookup");
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        Table table = table(drawing, Json.number(request, "table"));
        String view = Json.string(request, "view", "");
        NativeReadTrace.known("requested_balloon_view", view);
        if (!view.isEmpty() && call("Model2D.GetViewByName(add_balloons)", () -> drawing.GetViewByName(view)) == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + view);
        }
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "balloons need the native library, which this Creo "
                    + "session has not loaded: " + Service.sketchLibraryStatus());
        }
        NativeReadTrace.stage("drawing.add_balloons.count_before");
        int before = balloonNotes(drawing);
        NativeReadTrace.stage("drawing.add_balloons.native_arguments");
        com.ptc.pfc.pfcArgument.Arguments in = call("Arguments.create(add_balloons)",
                () -> com.ptc.pfc.pfcArgument.Arguments.create());
        String drawingName = Drawings.fileNameTraced(drawing).replaceFirst("(?i)\\.drw$", "");
        var drawingValue = call("pfcArgument.CreateStringArgValue(balloon_drawing)",
                () -> pfcArgument.CreateStringArgValue(drawingName));
        var drawingArgument = call("pfcArgument.Argument_Create(balloon_drawing)",
                () -> pfcArgument.Argument_Create("drawing", drawingValue));
        NativeReadTrace.run("Arguments.append(balloon_drawing)", () -> in.append(drawingArgument));
        int tableId = call("Table.GetId(add_balloons)", () -> table.GetId());
        NativeReadTrace.known("selected_table_id", tableId);
        var tableValue = call("pfcArgument.CreateIntArgValue(balloon_table)",
                () -> pfcArgument.CreateIntArgValue(tableId));
        var tableArgument = call("pfcArgument.Argument_Create(balloon_table)",
                () -> pfcArgument.Argument_Create("table", tableValue));
        NativeReadTrace.run("Arguments.append(balloon_table)", () -> in.append(tableArgument));
        var viewValue = call("pfcArgument.CreateStringArgValue(balloon_view)",
                () -> pfcArgument.CreateStringArgValue(view));
        var viewArgument = call("pfcArgument.Argument_Create(balloon_view)",
                () -> pfcArgument.Argument_Create("view", viewValue));
        NativeReadTrace.run("Arguments.append(balloon_view)", () -> in.append(viewArgument));
        NativeReadTrace.stage("drawing.add_balloons.native_execute");
        com.ptc.pfc.pfcProToolkit.FunctionReturn result = call("NativeLibrary.ExecuteFunction(bom_balloons)",
                () -> Service.sketchLibrary().ExecuteFunction(Service.BOM_BALLOONS_FUNCTION, in));
        int status = call("FunctionReturn.GetFunctionReturn(bom_balloons)", () -> result.GetFunctionReturn());
        if (status != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "ProBomballoonCreate answered " + status, "toolkit_error", status));
        }
        NativeReadTrace.stage("drawing.add_balloons.repaint");
        Drawings.repaintTraced(session);
        NativeReadTrace.stage("drawing.add_balloons.summary");
        Map<String, Object> out = Drawings.summary(drawing);
        NativeReadTrace.stage("drawing.add_balloons.count_after");
        out.put("balloons", Json.map("table", tableId, "view", view.isEmpty() ? null : view,
                "made", balloonNotes(drawing) - before));
        return out;
    }

    /** Move a table so its origin -- the corner it was placed by -- is at a point on the sheet. */
    static Map<String, Object> moveTable(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        Table table = table(drawing, Json.number(request, "table"));
        table.MoveSegment(0, screen(drawing, at(request, true)), Boolean.TRUE);
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("table", tableRow(drawing, table));
        return out;
    }

    /** The ids of the notes that are a table's cells: text of the table's, not free notes. */
    static java.util.Set<Integer> cellNotes(Model2D drawing) throws Exception {
        java.util.Set<Integer> out = new java.util.HashSet<>();
        try (var scope = NativeReadTrace.scope("phase", "drawing.cell_notes",
                "cell_notes_caller_phase", String.valueOf(NativeReadTrace.knownValue("phase")),
                "nullable_inventory_contract", "legacy_null_as_empty; absence_semantics_unverified",
                "cell_notes_traversal", String.valueOf(NativeReadTrace.traversal("Detailing.cellNotes")))) {
            Tables tables = cellCall("Model2D.ListTables(cell_notes)", () -> drawing.ListTables());
            int tableCount = tables == null ? 0 : cellCall("Tables.getarraysize(cell_notes)", () -> tables.getarraysize());
            for (int t = 0; t < tableCount; t++) {
                final int tableIndex = t;
                try (var tableScope = NativeReadTrace.scope("table_inventory_index", String.valueOf(tableIndex),
                        "table_id", "unobserved_by_cell_notes")) {
                    Table table = cellCall("Tables.get(cell_notes)", () -> tables.get(tableIndex));
                    int rows = cellCall("Table.GetRowCount(cell_notes)", () -> table.GetRowCount());
                    int columns = cellCall("Table.GetColumnCount(cell_notes)", () -> table.GetColumnCount());
                    for (int r = 1; r <= rows; r++) {
                        final int row = r;
                        try (var rowScope = NativeReadTrace.scope("table_row", String.valueOf(row))) {
                            for (int c = 1; c <= columns; c++) {
                                final int column = c;
                                try (var cellScope = NativeReadTrace.scope("table_column", String.valueOf(column),
                                        "note_id", "unobserved")) {
                                    var cell = cellCall("pfcTable.TableCell_Create(cell_notes)", () -> pfcTable.TableCell_Create(row, column));
                                    ModelItem note = cellCall("Table.GetCellNote(cell_notes)", () -> table.GetCellNote(cell));
                                    if (note != null) {
                                        int noteId = cellCall("ModelItem.GetId(cell_notes)", () -> note.GetId());
                                        NativeReadTrace.known("note_id", noteId);
                                        out.add(noteId);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        return out;
    }

    private static File tableFile(String name) throws Exception {
        File given = new File(name);
        if (given.isAbsolute()) {
            if (given.isFile() && given.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".tbl")) {
                return given;
            }
            throw new Failures.Refusal("E_NOT_FOUND", "no table file " + name);
        }
        File library = new File(new File(ModelOps.creoCommonFiles(), "text"), "table").getCanonicalFile();
        File file = new File(library, name.replace('/', File.separatorChar)
                + (name.toLowerCase(java.util.Locale.ROOT).endsWith(".tbl") ? "" : ".tbl")).getCanonicalFile();
        if (!file.isFile() || !file.getPath().startsWith(library.getPath() + File.separator)) {
            throw new Failures.Refusal("E_NOT_FOUND", "no table " + name + " in Creo's table library");
        }
        return file;
    }

    // ------------------------------------------------------------------ symbols

    /**
     * A symbol placed free on the sheet: a definition from Creo's symbol library
     * (<load point>/Common Files/symbols, named by its path there without .sym) or a .sym
     * file the caller names, its variable texts filled by name. The variables a definition
     * takes are the \\name\\ texts in its file.
     */
    static Map<String, Object> addSymbol(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        File file = symbolFile(Json.string(request, "symbol"));
        Set<String> variables = variables(file);
        Map<String, Object> values = request.get("values") instanceof Map
                ? Json.object(request.get("values"), "'values'") : Map.of();
        for (String name : values.keySet()) {
            if (!variables.contains(name)) {
                throw new Failures.Refusal("E_VALIDATION", "the symbol takes no variable '" + name + "'; it takes "
                        + variables);
            }
        }
        String base = file.getName().replaceFirst("(?i)\\.sym$", "");
        DetailSymbolDefItem def = drawing.RetrieveSymbolDefinition(base, file.getParentFile().getPath(), null,
                Boolean.FALSE);
        DetailSymbolInstInstructions how = pfcDetail.DetailSymbolInstInstructions_Create(def);
        DetailLeaders place = pfcDetail.DetailLeaders_Create();
        place.SetItemAttachment(pfcDetail.FreeAttachment_Create(screen(drawing, at(request, true))));
        how.SetInstAttachment(place);
        if (!values.isEmpty()) {
            DetailVariantTexts texts = DetailVariantTexts.create();
            for (Map.Entry<String, Object> entry : values.entrySet()) {
                texts.append(pfcDetail.DetailVariantText_Create(entry.getKey(), String.valueOf(entry.getValue())));
            }
            how.SetTextValues(texts);
        }
        how.SetIsDisplayed(Boolean.TRUE);
        DetailSymbolInstItem made = (DetailSymbolInstItem) drawing.CreateDetailItem(how);
        made.Show();
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("symbol", Json.map("id", made.GetId(), "definition", base, "variables", new ArrayList<>(variables)));
        return out;
    }

    static List<Object> symbolRows(Model2D drawing) throws jxthrowable {
        List<Object> out = new ArrayList<>();
        DetailItems items = drawing.ListDetailItems(DetailType.DETAIL_SYM_INSTANCE, null);
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            out.add(symbolRow(drawing, (DetailSymbolInstItem) items.get(i)));
        }
        return out;
    }

    static List<Object> symbolRowsStrict(Model2D drawing) throws jxthrowable {
        DetailItems items;
        try { items = drawing.ListDetailItems(DetailType.DETAIL_SYM_INSTANCE, null); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { items = null; }
        // PTC ListDetailItems documents a successful null return as no matching items.
        // Exceptions still propagate; this is not a fallback for a failed getter.
        List<Object> rows = new ArrayList<>();
        for (int i = 0; items != null && i < items.getarraysize(); i++) rows.add(symbolRow(drawing, (DetailSymbolInstItem) items.get(i)));
        return rows;
    }

    /** A placed symbol: its definition, where it sits when placed free, its variables' values. */
    private static Map<String, Object> symbolRow(Model2D drawing, DetailSymbolInstItem symbol) throws jxthrowable {
        String definition = null;
        List<Object> place = null;
        Map<String, Object> values = new java.util.LinkedHashMap<>();
        try {
            DetailSymbolInstInstructions how = symbol.GetInstructions(true);
            definition = how.GetSymbolDef().GetInstructions().GetFullPath();
            com.ptc.pfc.pfcDetail.Attachment attached = how.GetInstAttachment().GetItemAttachment();
            if (attached instanceof FreeAttachment) {
                place = Drawings.onSheet(drawing.GetSheetTransform(drawing.GetCurrentSheetNumber()),
                        ((FreeAttachment) attached).GetAttachmentPoint());
            }
            DetailVariantTexts texts = how.GetTextValues();
            for (int t = 0; texts != null && t < texts.getarraysize(); t++) {
                values.put(texts.get(t).GetPrompt(), texts.get(t).GetValue());
            }
        } catch (Throwable unreadable) {
            NativeReadTrace.rethrowFatal(unreadable);
            // Reported as null or empty.
        }
        return Json.map("id", symbol.GetId(), "definition", definition, "at", place, "values", values);
    }

    private static File symbolFile(String symbol) throws Exception {
        File file = findSymbol(symbol);
        if (file == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no symbol definition " + symbol);
        }
        return file;
    }

    /**
     * A definition by its name in Creo's library (its path under the library, without .sym)
     * or by a .sym file's absolute path; null when there is none. A library name stays
     * inside the library.
     */
    private static File findSymbol(String symbol) throws Exception {
        File given = new File(symbol);
        if (given.isAbsolute()) {
            return given.isFile() && given.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".sym") ? given : null;
        }
        File library = symbolLibrary().getCanonicalFile();
        File file = new File(library, symbol.replace('/', File.separatorChar)
                + (symbol.toLowerCase(java.util.Locale.ROOT).endsWith(".sym") ? "" : ".sym")).getCanonicalFile();
        return file.isFile() && file.getPath().startsWith(library.getPath() + File.separator) ? file : null;
    }

    private static File symbolLibrary() throws Exception {
        return new File(ModelOps.creoCommonFiles(), "symbols");
    }

    /**
     * A symbol definition and the variables it takes, read before placing it; when there is
     * no such definition, the names Creo's library has instead.
     */
    static Map<String, Object> symbolDefinition(Map<String, Object> request) throws Exception {
        String name = Json.string(request, "symbol");
        File file = findSymbol(name);
        if (file != null) {
            return Json.map("symbol", Json.map("name", name, "path", file.getPath(),
                    "variables", new ArrayList<>(variables(file))));
        }
        List<Object> names = new ArrayList<>();
        java.nio.file.Path root = symbolLibrary().toPath();
        if (Files.isDirectory(root)) {
            try (java.util.stream.Stream<java.nio.file.Path> walk = Files.walk(root, 6)) {
                walk.filter(p -> p.getFileName().toString().toLowerCase(java.util.Locale.ROOT).endsWith(".sym"))
                        .map(p -> root.relativize(p).toString().replace(File.separatorChar, '/')
                                .replaceFirst("(?i)\\.sym$", ""))
                        .sorted(String.CASE_INSENSITIVE_ORDER)
                        .forEach(names::add);
            }
        }
        return Json.map("symbol", null, "library", names);
    }

    /** The variable texts a symbol definition takes: \\name\\ in its file. */
    static Set<String> variables(File file) throws Exception {
        Set<String> out = new LinkedHashSet<>();
        Matcher m = VARIABLE.matcher(new String(Files.readAllBytes(file.toPath()), StandardCharsets.ISO_8859_1));
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    // ------------------------------------------------------------------ helpers

    private static List<?> at(Map<String, Object> request, boolean required) {
        Object raw = request.get("at");
        if (raw == null && !required) {
            return null;
        }
        if (!(raw instanceof List) || ((List<?>) raw).size() != 2 || !(((List<?>) raw).get(0) instanceof Double)
                || !(((List<?>) raw).get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'at' is [x, y] on the sheet");
        }
        return (List<?>) raw;
    }

    private static Point3D screen(Drawing drawing, List<?> at) throws jxthrowable {
        return Drawings.toScreen(drawing, drawing.GetCurrentSheetNumber(), (Double) at.get(0), (Double) at.get(1));
    }

    private static List<?> list(Map<String, Object> request, String key) {
        Object raw = request.get(key);
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'" + key + "' lists numbers");
        }
        return (List<?>) raw;
    }

    private static double number(Object value) {
        if (!(value instanceof Double) || !((Double) value > 0)) {
            throw new Failures.Refusal("E_VALIDATION", "a table's widths and heights are positive numbers");
        }
        return (Double) value;
    }

    private static int integer(Object value) {
        if (!(value instanceof Double) || (Double) value < 1 || (Double) value != Math.floor((Double) value)) {
            throw new Failures.Refusal("E_VALIDATION", "a table cell is [row, column], counted from 1");
        }
        return (int) Math.round((Double) value);
    }
}
