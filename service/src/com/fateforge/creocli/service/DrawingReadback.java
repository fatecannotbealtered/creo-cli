package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import com.ptc.pfc.pfcDetail.*;
import com.ptc.pfc.pfcModel2D.Model2D;
import com.ptc.pfc.pfcView2D.View2D;
import com.ptc.pfc.pfcView2D.View2Ds;
import com.ptc.wfc.wfcView2D.*;

/** Native drawing identities and dependency completeness, without guessed associations. */
final class DrawingReadback {
    private DrawingReadback() {}

    private static <T> T call(String getter, NativeReadTrace.Call<T> body) throws com.ptc.cipjava.jxthrowable {
        return NativeReadTrace.call(getter, body);
    }

    static Map<String, Object> view(View2D view) {
        Map<String, Object> out = Json.map("complete", false, "source", "WView2D native identity/parent/children/section/alignment getters");
        try (var scope = NativeReadTrace.scope("readback", "view")) {
            WView2D nativeView = (WView2D) view;
            int id = call("WView2D.GetViewId", () -> nativeView.GetViewId());
            NativeReadTrace.known("view_id", id);
            out.put("id", String.valueOf(id));
            out.put("background", call("View2D.GetIsBackground", () -> view.GetIsBackground()));
            View2D parent = call("WView2D.GetParentView", () -> nativeView.GetParentView());
            out.put("parent", parent == null ? null : call("View2D.GetName(parent)", () -> parent.GetName()));
            List<Object> names = new ArrayList<>();
            View2Ds children = call("WView2D.GetChildren", () -> nativeView.GetChildren());
            for (int i = 0; children != null && i < call("View2Ds.getarraysize(children)", () -> children.getarraysize()); i++) {
                final int index = i;
                try (var childScope = NativeReadTrace.scope("child_index", String.valueOf(index))) {
                    View2D child = call("View2Ds.get(child)", () -> children.get(index));
                    names.add(call("View2D.GetName(child)", () -> child.GetName()));
                }
            }
            out.put("children", names);
            DrawingViewSectionType section = call("WView2D.GetDrawingViewSectionType", () -> nativeView.GetDrawingViewSectionType());
            out.put("section_type", call("DrawingViewSectionType.getValue", () -> section.getValue()) == DrawingViewSectionType._VIEW_NO_SECTION
                    ? "none" : call("DrawingViewSectionType.enumName", () -> Creo.enumName(section)));
            out.put("basic_complete", true);
            ViewAlignmentInstructions alignment = call("WView2D.GetAlignmentInstructions", () -> nativeView.GetAlignmentInstructions());
            View2D reference = alignment == null ? null : call("ViewAlignmentInstructions.GetReferenceView", () -> alignment.GetReferenceView());
            out.put("alignment_view", reference == null ? null : call("View2D.GetName(alignment)", () -> reference.GetName()));
            out.put("alignment_complete", true);
            out.put("complete", true);
        } catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            out.put("error", Failures.error(unavailable));
        }
        return out;
    }

    static Map<String, Object> note(DetailNoteItem note) {
        Map<String, Object> out = Json.map("complete", false, "source", "DetailNoteItem.GetInstructions; native attachment selection/view");
        try (var scope = NativeReadTrace.scope("readback", "note_attachment")) {
            DetailNoteInstructions instructions = call("DetailNoteItem.GetInstructions(attachment)", () -> note.GetInstructions(true));
            DetailLeaders leader = call("DetailNoteInstructions.GetLeader(attachment)", () -> instructions.GetLeader());
            if (leader == null || call("DetailLeaders.GetItemAttachment(presence)", () -> leader.GetItemAttachment()) == null) return out;
            Attachment attachment = call("DetailLeaders.GetItemAttachment(value)", () -> leader.GetItemAttachment());
            View2D found = null;
            if (attachment instanceof FreeAttachment) {
                found = call("FreeAttachment.GetView", () -> ((FreeAttachment) attachment).GetView());
                out.put("kind", "free");
            } else {
                com.ptc.pfc.pfcSelect.Selection selected = null;
                if (attachment instanceof ParametricAttachment)
                    selected = call("ParametricAttachment.GetAttachedGeometry", () -> ((ParametricAttachment) attachment).GetAttachedGeometry());
                else if (attachment instanceof OffsetAttachment)
                    selected = call("OffsetAttachment.GetAttachedGeometry", () -> ((OffsetAttachment) attachment).GetAttachedGeometry());
                if (selected == null) return out;
                final com.ptc.pfc.pfcSelect.Selection selection = selected;
                found = call("Selection.GetSelView2D(attachment)", () -> selection.GetSelView2D());
                if (found == null) return out;
                out.put("kind", "geometry");
            }
            final View2D view = found;
            out.put("view", view == null ? null : call("View2D.GetName(attachment)", () -> view.GetName()));
            out.put("view_id", view == null ? null : String.valueOf(call("WView2D.GetViewId(attachment)", () -> ((WView2D) view).GetViewId())));
            out.put("background", view != null && call("View2D.GetIsBackground(attachment)", () -> view.GetIsBackground()));
            Integer sheet = view == null ? null : call("View2D.GetSheetNumber(attachment)", () -> view.GetSheetNumber());
            NativeReadTrace.known("note_sheet", sheet);
            out.put("sheet", sheet);
            out.put("complete", sheet != null && sheet > 0);
        } catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            out.put("error", Failures.error(unavailable));
        }
        return out;
    }

    static Boolean readOnly(DetailNoteItem note) {
        try { return call("DetailNoteItem.IsReadOnly", () -> note.IsReadOnly()); }
        catch (Throwable unavailable) { NativeReadTrace.rethrowFatal(unavailable); return null; }
    }

    /** Full bounded entity observations, including the native attachment; no summary fallback. */
    static List<Object> entities(Model2D drawing) throws Exception {
        NativeReadTrace.stage("drawing_readback.entities");
        DetailItems found;
        try { found = call("Model2D.ListDetailItems(entities)", () -> drawing.ListDetailItems(DetailType.DETAIL_ENTITY, null)); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { found = null; }
        final DetailItems items = found;
        List<Object> rows = new ArrayList<>();
        if (items != null && call("DetailItems.getarraysize(entity_limit)", () -> items.getarraysize()) > 256)
            throw new Failures.Refusal("E_UNSUPPORTED", "draft-entity inventory exceeds 256");
        for (int i = 0; items != null && i < call("DetailItems.getarraysize(entities)", () -> items.getarraysize()); i++) {
            final int index = i;
            try (var scope = NativeReadTrace.scope("entity_index", String.valueOf(index))) {
                DetailEntityItem item = (DetailEntityItem) call("DetailItems.get(entity)", () -> items.get(index));
                DetailEntityInstructions instruction = call("DetailEntityItem.GetInstructions", () -> item.GetInstructions());
                View2D view = call("DetailEntityInstructions.GetView", () -> instruction.GetView());
                if (view == null) throw new IllegalStateException("entity attachment view unavailable");
                int sheet = call("View2D.GetSheetNumber(entity)", () -> view.GetSheetNumber());
                com.ptc.pfc.pfcGeometry.CurveDescriptor curve = call("DetailEntityInstructions.GetGeometry", () -> instruction.GetGeometry());
                if (!(curve instanceof com.ptc.pfc.pfcGeometry.LineDescriptor))
                    throw new Failures.Refusal("E_UNSUPPORTED", "view deletion protects straight draft lines only; entity "
                            + call("DetailEntityItem.GetId(unsupported)", () -> item.GetId()));
                com.ptc.pfc.pfcGeometry.LineDescriptor line = (com.ptc.pfc.pfcGeometry.LineDescriptor) curve;
                com.ptc.pfc.pfcBase.Transform3D transform = call("Model2D.GetSheetTransform(entity)", () -> drawing.GetSheetTransform(sheet));
                int id = call("DetailEntityItem.GetId", () -> item.GetId());
                NativeReadTrace.known("entity_id", id);
                String name = call("View2D.GetName(entity)", () -> view.GetName());
                int viewId = call("WView2D.GetViewId(entity)", () -> ((WView2D) view).GetViewId());
                boolean background = call("View2D.GetIsBackground(entity)", () -> view.GetIsBackground());
                com.ptc.pfc.pfcSheet.SheetInfo info = call("Model2D.GetSheetInfo(entity)", () -> drawing.GetSheetInfo(sheet));
                var units = call("SheetInfo.GetUnits(entity)", () -> info.GetUnits());
                var unitType = call("Unit.GetType(entity)", () -> units.GetType());
                String unitName = call("LengthUnitType.enumName(entity)", () -> Creo.enumName(unitType));
                com.ptc.pfc.pfcBase.Point3D start = call("LineDescriptor.GetEnd1", () -> line.GetEnd1());
                var transformedStart = call("Transform3D.TransformPoint(line_start)", () -> transform.TransformPoint(start));
                List<Object> startXYZ = xyz(transformedStart);
                com.ptc.pfc.pfcBase.Point3D end = call("LineDescriptor.GetEnd2", () -> line.GetEnd2());
                var transformedEnd = call("Transform3D.TransformPoint(line_end)", () -> transform.TransformPoint(end));
                rows.add(Json.map("id", String.valueOf(id), "type", "line", "sheet", sheet,
                        "view", name, "view_id", String.valueOf(viewId), "background", background, "complete", true,
                        "units", unitName.replace("LENGTHUNIT_", "").toLowerCase(java.util.Locale.ROOT),
                        "coordinate_space", "sheet_lower_left_xyz",
                        "geometry", Json.map("start", startXYZ, "end", xyz(transformedEnd)),
                        "source", "DetailEntityItem.GetInstructions/LineDescriptor; native View2D identity and sheet transform"));
            } catch (Failures.Refusal refused) { throw refused; }
            catch (Throwable unavailable) {
                NativeReadTrace.rethrowFatal(unavailable);
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "native detail-entity identity/owner/line read failed: " + unavailable.getClass().getSimpleName());
            }
        }
        return rows;
    }

    static Map<String, Object> entityReport(Model2D drawing) {
        try {
            List<Object> rows = entities(drawing);
            return Json.map("completed", true, "items", rows, "count", rows.size(),
                    "scope", "bounded_straight_lines", "source", "native detail-entity getters");
        } catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            return Json.map("completed", false, "items", null, "count", null,
                    "scope", "bounded_straight_lines", "error", Failures.error(unavailable));
        }
    }

    private static List<Object> xyz(com.ptc.pfc.pfcBase.Point3D point) throws com.ptc.cipjava.jxthrowable {
        List<Object> result = new ArrayList<>();
        for (int axis = 0; axis < 3; axis++) {
            final int coordinate = axis;
            double value = call("Point3D.get(entity_axis_" + coordinate + ")", () -> point.get(coordinate));
            if (!Double.isFinite(value)) throw new IllegalStateException("non-finite entity coordinate");
            result.add(value);
        }
        return result;
    }

    static Map<String, Object> detailScope(Model2D drawing) {
        Map<String, Object> out = Json.map("complete", false, "source", "ListDetailItems(all types); bounded view-removal profile");
        try {
            NativeReadTrace.stage("drawing_readback.detail_scope");
            DetailItems found;
            try { found = call("Model2D.ListDetailItems(all)", () -> drawing.ListDetailItems(null, null)); }
            catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { found = null; }
            final DetailItems items = found;
            List<Object> unsupported = new ArrayList<>();
            for (int i = 0; items != null && i < call("DetailItems.getarraysize(scope)", () -> items.getarraysize()); i++) {
                final int index = i;
                DetailItem item = call("DetailItems.get(scope_type)", () -> items.get(index));
                DetailType type = call("DetailItem.GetDetailType", () -> item.GetDetailType());
                String kind = call("DetailType.enumName", () -> Creo.enumName(type));
                // A definition has no placement; placed instances are separately inventoried.
                if (!"DETAIL_NOTE".equals(kind) && !"DETAIL_ENTITY".equals(kind)
                        && !"DETAIL_SYM_DEFINITION".equals(kind)) {
                    DetailItem again = call("DetailItems.get(scope_id)", () -> items.get(index));
                    unsupported.add(Json.map("id", String.valueOf(call("DetailItem.GetId(scope)", () -> again.GetId())), "kind", kind));
                }
            }
            out.put("unsupported", unsupported);
            out.put("complete", true);
        } catch (Throwable unavailable) {
            NativeReadTrace.rethrowFatal(unavailable);
            out.put("error", Failures.error(unavailable));
        }
        return out;
    }
}
