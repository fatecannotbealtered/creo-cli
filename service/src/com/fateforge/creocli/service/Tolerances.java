package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcDrawing.Drawing;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel2D.Model2D;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcView2D.View2D;
import com.ptc.wfc.wfcAnnotation.Annotation;
import com.ptc.wfc.wfcAnnotation.LeaderArrowType;
import com.ptc.wfc.wfcAnnotation.SetDatumTag;
import com.ptc.wfc.wfcAnnotation.SetDatumTags;
import com.ptc.wfc.wfcDrawing.WDrawing;
import com.ptc.wfc.wfcGTol.GTol;
import com.ptc.wfc.wfcGTol.GTolAttach;
import com.ptc.wfc.wfcGTol.GTolDatumReferences;
import com.ptc.wfc.wfcGTol.GTolLeaderAttachType;
import com.ptc.wfc.wfcGTol.GTolLeaderInstructionsSeq;
import com.ptc.wfc.wfcGTol.GTolSymbol;
import com.ptc.wfc.wfcGTol.GTolType;
import com.ptc.wfc.wfcGTol.SymbolFont;
import com.ptc.wfc.wfcGTol.wfcGTol;
import com.ptc.wfc.wfcModel.WModel;
import com.ptc.wfc.wfcSession.WSession;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Geometric tolerancing on a drawing, as a person adds it: datum feature symbols on the
 * faces a part is located by, and feature control frames -- a characteristic, a value,
 * the datums it is measured from -- attached to a dimension, led to an edge, or free.
 */
final class Tolerances {
    static final Map<String, GTolType> TYPES = new LinkedHashMap<>();

    static {
        TYPES.put("straightness", GTolType.GTOLTYPE_STRAIGHTNESS);
        TYPES.put("flatness", GTolType.GTOLTYPE_FLATNESS);
        TYPES.put("circularity", GTolType.GTOLTYPE_CIRCULAR);
        TYPES.put("cylindricity", GTolType.GTOLTYPE_CYLINDRICAL);
        TYPES.put("line-profile", GTolType.GTOLTYPE_LINE);
        TYPES.put("surface-profile", GTolType.GTOLTYPE_SURFACE);
        TYPES.put("angularity", GTolType.GTOLTYPE_ANGULAR);
        TYPES.put("perpendicularity", GTolType.GTOLTYPE_PERPENDICULAR);
        TYPES.put("parallelism", GTolType.GTOLTYPE_PARALLEL);
        TYPES.put("position", GTolType.GTOLTYPE_POSITION);
        TYPES.put("concentricity", GTolType.GTOLTYPE_CONCENTRICITY);
        TYPES.put("symmetry", GTolType.GTOLTYPE_SYMMETRY);
        TYPES.put("circular-runout", GTolType.GTOLTYPE_CIRCULAR_RUNOUT);
        TYPES.put("total-runout", GTolType.GTOLTYPE_TOTAL_RUNOUT);
    }

    private Tolerances() {
    }

    // ------------------------------------------------------------------ datums

    /** A datum feature symbol on an edge of the part a view shows: the face it stands for. */
    static Map<String, Object> addDatum(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        String label = Json.string(request, "label");
        for (Object row : datumRows(drawing)) {
            if (label.equals(((Map<?, ?>) row).get("label"))) {
                throw new Failures.Refusal("E_CONFLICT", "the drawing already has datum " + label);
            }
        }
        // On a face of the part as a view shows it: Creo draws the symbol on the edge the face
        // is seen as. An edge itself, or a dimension, is refused as bad inputs (measured).
        Selection pick = onView(drawing, request);
        SetDatumTag tag = ((WModel) drawing).CreateSetDatumTag(pick, label, null);
        // A drawing's own symbol shows in its view as it is made: Show answers bad inputs and
        // ShowInDrawing no change (measured).
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("datum", datumRow(drawing, tag));
        return out;
    }

    static List<Object> datumRows(Model2D drawing) {
        List<Object> out = new ArrayList<>();
        try {
            SetDatumTags tags = ((WDrawing) drawing).ListSetDatumTags();
            for (int i = 0; tags != null && i < tags.getarraysize(); i++) {
                out.add(datumRow(drawing, tags.get(i)));
            }
        } catch (Throwable none) {
            // No datum symbols.
        }
        return out;
    }

    static List<Object> datumRowsStrict(Model2D drawing) throws jxthrowable {
        SetDatumTags tags;
        try { tags = ((WDrawing) drawing).ListSetDatumTags(); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) {
            // ProDrawingSetdatumtagVisit: PRO_TK_E_NOT_FOUND means no tags in this drawing.
            // Bad inputs, missing licences and interrupted reads are not caught here.
            tags = null;
        }
        if (tags == null) {
            // Cross-check the optional annotation collection using the documented model-item
            // enumerator. A disagreement is incomplete, never an invented empty inventory.
            ModelItems check = optionalItems((Model) drawing, ModelItemType.ITEM_SET_DATUM_TAG);
            if (check != null && check.getarraysize() != 0)
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "datum inventories disagree");
        }
        List<Object> rows = new ArrayList<>();
        for (int i = 0; tags != null && i < tags.getarraysize(); i++) rows.add(datumRow(drawing, tags.get(i)));
        return rows;
    }

    private static Map<String, Object> datumRow(Model2D drawing, SetDatumTag tag) throws jxthrowable {
        String on = null;
        try {
            Selection attached = tag.GetAttachment();
            on = attached == null || attached.GetSelItem() == null ? null : Geometry.ref(attached.GetSelItem());
        } catch (Throwable unknown) {
            // Reported as null.
        }
        return Json.map("id", tag.GetId(), "label", tag.GetLabel(), "on", on);
    }

    static SetDatumTag datum(Model2D drawing, String label) throws jxthrowable {
        SetDatumTags tags = ((WDrawing) drawing).ListSetDatumTags();
        for (int i = 0; tags != null && i < tags.getarraysize(); i++) {
            if (label.equals(tags.get(i).GetLabel())) {
                return tags.get(i);
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "the drawing has no datum " + label);
    }

    // ------------------------------------------------------------------ feature control frames

    /**
     * A feature control frame: its characteristic, value (a diameter sign and a material
     * condition as Creo's own symbols), up to three datums, attached to a shown dimension,
     * led to an edge a view shows, or placed free.
     */
    static Map<String, Object> addGtol(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Drawing drawing = Drawings.drawing(session, Json.string(request, "model"));
        Drawings.front(session, drawing);
        String kind = Json.string(request, "type");
        GTolType type = TYPES.get(kind);
        if (type == null) {
            throw new Failures.Refusal("E_VALIDATION", "'type' is one of " + TYPES.keySet());
        }
        String value = Json.string(request, "value");
        if (Boolean.TRUE.equals(request.get("diameter"))) {
            value = symbol(session, GTolSymbol.GTOL_SYMBOL_DIAMETER) + value;
        }
        String material = Json.string(request, "material", null);
        if ("mmc".equals(material)) {
            value = value + symbol(session, GTolSymbol.GTOL_SYMBOL_MMC);
        } else if ("lmc".equals(material)) {
            value = value + symbol(session, GTolSymbol.GTOL_SYMBOL_LMC);
        }
        GTolAttach attach = attachment(drawing, Json.object(request.get("attach"), "'attach'"));
        GTol made = ((WModel) drawing).CreateGTol(type, attach, value);
        // A frame shows only once shown in a view: its dimension's, or the one it was placed in.
        // Display answers an invalid matrix for one attached to a model's dimension (measured).
        made.ShowInDrawing(viewOf(drawing, Json.object(request.get("attach"), "'attach'")), null);
        Object datums = request.get("datums");
        if (datums instanceof List && !((List<?>) datums).isEmpty()) {
            List<?> d = (List<?>) datums;
            // Never a null string: OTK converts it without a check and Creo dies (measured: an
            // access violation in utfstrmtz, the traceback's only frames OTK's own).
            made.SetDatumReferences(wfcGTol.GTolDatumReferences_Create(String.valueOf(d.get(0)),
                    d.size() > 1 ? String.valueOf(d.get(1)) : "", d.size() > 2 ? String.valueOf(d.get(2)) : ""));
        }
        Creo.repaint(session);
        Map<String, Object> out = Drawings.summary(drawing);
        out.put("gtol", gtolRow(drawing, made, (Model) made.GetDBParent()));
        return out;
    }

    private static String symbol(Session session, GTolSymbol which) throws jxthrowable {
        return ((WSession) session).GetGTolSymbolString(which, SymbolFont.FONT_ISO);
    }

    private static View2D viewOf(Drawing drawing, Map<String, Object> how) throws Exception {
        if (how.containsKey("dimension")) {
            return drawing.GetViewDisplaying((com.ptc.pfc.pfcDimension.BaseDimension)
                    Detailing.shownDimension(drawing, Json.string(how, "dimension"))[1]);
        }
        View2D view = drawing.GetViewByName(Json.string(how, "view"));
        if (view == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(how, "view"));
        }
        return view;
    }

    private static GTolAttach attachment(Drawing drawing, Map<String, Object> how) throws Exception {
        if (how.containsKey("dimension")) {
            Object[] found = Detailing.shownDimension(drawing, Json.string(how, "dimension"));
            if (!(found[1] instanceof Annotation)) {
                throw new Failures.Refusal("E_CONFLICT", "a frame goes on a model's dimension shown here, not on "
                        + "one made on the drawing");
            }
            return wfcGTol.GTolAttachAnnotation_Create((Annotation) found[1]);
        }
        viewOf(drawing, how);
        Point3D where = at(drawing, how);
        if (how.containsKey("on")) {
            GTolLeaderInstructionsSeq leaders = GTolLeaderInstructionsSeq.create();
            leaders.append(wfcGTol.GTolLeaderInstructions_Create(LeaderArrowType.LEADER_ARROWHEAD, onView(drawing, how)));
            return wfcGTol.GTolAttachLeader_Create(GTolLeaderAttachType.GTOL_LEADER, leaders, where, null);
        }
        return wfcGTol.GTolAttachFree_Create(where, null);
    }

    /**
     * The frames a drawing shows: its own, and those of its models -- a frame attached to a
     * model's dimension is the model's, as Creo makes it (measured) -- that it shows.
     */
    static List<Object> gtolRows(Model2D drawing) {
        List<Object> out = new ArrayList<>();
        List<Model> owners = new ArrayList<>();
        owners.add((Model) drawing);
        try {
            com.ptc.pfc.pfcModel.Models models = drawing.ListModels();
            for (int m = 0; models != null && m < models.getarraysize(); m++) {
                owners.add(models.get(m));
            }
        } catch (Throwable none) {
            // Only the drawing's own.
        }
        for (Model owner : owners) {
            try {
                ModelItems items = owner.ListItems(ModelItemType.ITEM_GTOL);
                for (int i = 0; items != null && i < items.getarraysize(); i++) {
                    if (!(items.get(i) instanceof GTol)) {
                        continue;
                    }
                    GTol g = (GTol) items.get(i);
                    if (owner != drawing && !g.IsShown((Drawing) drawing)) {
                        continue;
                    }
                    out.add(gtolRow(drawing, g, owner));
                }
            } catch (Throwable none) {
                // None of this owner's.
            }
        }
        return out;
    }

    static List<Object> gtolRowsStrict(Model2D drawing) throws jxthrowable {
        List<Model> owners = new ArrayList<>();
        owners.add((Model) drawing);
        com.ptc.pfc.pfcModel.Models models = drawing.ListModels();
        if (models == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "GTol source-model inventory is null");
        for (int i = 0; i < models.getarraysize(); i++) owners.add(models.get(i));
        List<Object> rows = new ArrayList<>();
        for (Model owner : owners) {
            ModelItems items = optionalItems(owner, ModelItemType.ITEM_GTOL);
            // ModelItemOwner.ListItems returns null when this type has no items.
            // Native errors and row type mismatches remain failures.
            for (int i = 0; items != null && i < items.getarraysize(); i++) {
                if (!(items.get(i) instanceof GTol)) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "GTol row type is unreadable");
                GTol item = (GTol) items.get(i);
                if (owner != drawing && !item.IsShown((Drawing) drawing)) continue;
                rows.add(gtolRow(drawing, item, owner));
            }
        }
        return rows;
    }

    private static ModelItems optionalItems(Model owner, ModelItemType type) throws jxthrowable {
        try { return owner.ListItems(type); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { return null; }
    }

    private static Map<String, Object> gtolRow(Model2D drawing, GTol g, Model owner) throws jxthrowable {
        String type = null;
        for (Map.Entry<String, GTolType> e : TYPES.entrySet()) {
            if (e.getValue().getValue() == g.GetGTolType().getValue()) {
                type = e.getKey();
            }
        }
        List<Object> datums = new ArrayList<>();
        try {
            GTolDatumReferences refs = g.GetDatumReferences();
            for (String d : new String[] {refs.GetPrimary(), refs.GetSecondary(), refs.GetTertiary()}) {
                if (d != null && !d.isEmpty()) {
                    datums.add(d);
                }
            }
        } catch (Throwable none) {
            // None.
        }
        String attached = null;
        try {
            attached = Creo.enumName(g.GetGTolAttach().GetType()).replace("GTOLATTACH_", "").toLowerCase(Locale.ROOT);
        } catch (Throwable unknown) {
            // Reported as null.
        }
        List<Object> place = null;
        try {
            GTolAttach how = g.GetGTolAttach();
            Point3D where = how instanceof com.ptc.wfc.wfcGTol.GTolAttachFree
                    ? ((com.ptc.wfc.wfcGTol.GTolAttachFree) how).GetLocation()
                    : how instanceof com.ptc.wfc.wfcGTol.GTolAttachLeader
                            ? ((com.ptc.wfc.wfcGTol.GTolAttachLeader) how).GetLocation() : null;
            if (where != null) {
                place = Drawings.onSheet(drawing.GetSheetTransform(drawing.GetCurrentSheetNumber()), where);
            }
        } catch (Throwable unplaced) {
            // Reported as null.
        }
        return Json.map("id", g.GetId(), "model", Creo.fileName(owner), "type", type, "value", g.GetValueString(),
                "datums", datums, "attached", attached, "at", place);
    }

    /** A frame by id: the drawing's own, or id@model for one of a model's. */
    static GTol gtol(Model2D drawing, String key) throws jxthrowable {
        String id = key.contains("@") ? key.substring(0, key.indexOf('@')) : key;
        String owner = key.contains("@") ? key.substring(key.indexOf('@') + 1) : null;
        Model in = (Model) drawing;
        if (owner != null) {
            in = null;
            com.ptc.pfc.pfcModel.Models models = drawing.ListModels();
            for (int m = 0; models != null && m < models.getarraysize(); m++) {
                if (Creo.fileName(models.get(m)).equalsIgnoreCase(owner)) {
                    in = models.get(m);
                }
            }
            if (in == null) {
                throw new Failures.Refusal("E_NOT_FOUND", "the drawing shows no model " + owner);
            }
        }
        // By listing, not GetItemById: that answered no frame for one the listing had (measured).
        ModelItems items = in.ListItems(ModelItemType.ITEM_GTOL);
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            if (items.get(i) instanceof GTol && String.valueOf(items.get(i).GetId()).equals(id)) {
                return (GTol) items.get(i);
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "no geometric tolerance " + key + " on the drawing");
    }

    // ------------------------------------------------------------------ helpers

    /** An edge, face or datum of the part a named view shows, selected in that view. */
    private static Selection onView(Drawing drawing, Map<String, Object> how) throws Exception {
        View2D view = drawing.GetViewByName(Json.string(how, "view"));
        if (view == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "no view named " + Json.string(how, "view"));
        }
        Model shown = view.GetModel();
        if (!(shown instanceof Solid)) {
            throw new Failures.Refusal("E_CONFLICT", "the view shows no part");
        }
        ModelItem item = Geometry.item((Solid) shown, Json.string(how, "on"));
        Selection pick = pfcSelect.CreateModelItemSelection(item, null);
        pick.SetSelView2D(view);
        // Where on the sheet it was picked, as a person's pick carries: an edge's middle, or a
        // face's -- the middle of its extent, brought onto the face. Without it Creo put a
        // face's datum symbol on a corner (measured).
        if (item.GetType().getValue() == ModelItemType._ITEM_EDGE) {
            pick.SetTParam(0.5);
            pick.SetPoint(view.GetTransform().TransformPoint(
                    ((com.ptc.pfc.pfcGeometry.Edge) item).Eval3DData(0.5).GetPoint()));
        } else if (item.GetType().getValue() == ModelItemType._ITEM_SURFACE) {
            com.ptc.pfc.pfcGeometry.Surface face = (com.ptc.pfc.pfcGeometry.Surface) item;
            com.ptc.pfc.pfcBase.Outline3D box = face.GetXYZExtents();
            Point3D middle = Point3D.create();
            for (int i = 0; i < 3; i++) {
                middle.set(i, (box.get(0).get(i) + box.get(1).get(i)) / 2);
            }
            Point3D on = face.EvalClosestPoint(middle);
            pick.SetParams(face.EvalParameters(on));
            pick.SetPoint(view.GetTransform().TransformPoint(on));
        }
        return pick;
    }

    private static Point3D at(Drawing drawing, Map<String, Object> how) throws jxthrowable {
        Object raw = how.get("at");
        if (!(raw instanceof List) || ((List<?>) raw).size() != 2 || !(((List<?>) raw).get(0) instanceof Double)
                || !(((List<?>) raw).get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'attach.at' is [x, y] on the sheet");
        }
        List<?> at = (List<?>) raw;
        return Drawings.toScreen(drawing, drawing.GetCurrentSheetNumber(), (Double) at.get(0), (Double) at.get(1));
    }
}
