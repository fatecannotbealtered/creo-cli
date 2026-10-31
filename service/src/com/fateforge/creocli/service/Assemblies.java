package com.fateforge.creocli.service;

import com.ptc.cipjava.intseq;
import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcAssembly.Assembly;
import com.ptc.pfc.pfcAssembly.ComponentPath;
import com.ptc.pfc.pfcAssembly.pfcAssembly;
import com.ptc.pfc.pfcBase.Matrix3D;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcBase.pfcBase;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraint;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraintType;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraints;
import com.ptc.pfc.pfcComponentFeat.ComponentFeat;
import com.ptc.pfc.pfcComponentFeat.pfcComponentFeat;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * assembly.create, assembly.add, assembly.remove, assembly.check: components placed by
 * explicit constraints, as the Component Placement dashboard places them, never by a pick.
 *
 * <p>A constraint names a reference in the assembly and one in the component. An assembly
 * reference is the assembly's own datum ({@code ASM_FRONT}) or a component's geometry
 * written {@code <ref>@<component>}, the component being its model name or its feature id;
 * a component reference is the component model's own ({@code FRONT}, {@code surface:43}).
 */
final class Assemblies {

    private Assemblies() {
    }

    static Map<String, Object> create(Map<String, Object> request) throws Exception {
        return ModelOps.createAssembly(request);
    }

    static Assembly assembly(Session session, String raw) throws jxthrowable {
        Model model = Creo.model(session, raw.contains(".") ? raw : raw + ".asm");
        if (model.GetType().getValue() != ModelType._MDL_ASSEMBLY) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName(model) + " is not an assembly");
        }
        return (Assembly) model;
    }

    // ------------------------------------------------------------------ assembly.add

    /**
     * Add a model already in session as a component, packaged at the assembly origin, then
     * constrained. If the constraints cannot be applied the component is taken out again:
     * a failed add leaves the assembly as it was.
     */
    static Map<String, Object> add(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Assembly asm = assembly(session, Json.string(request, "model"));
        Solid component = Creo.solid(session, Json.string(request, "component"));
        if (Creo.fileName((Model) component).equalsIgnoreCase(Creo.fileName((Model) asm))) {
            throw new Failures.Refusal("E_VALIDATION", "an assembly cannot contain itself");
        }
        Object raw = request.get("constraints");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'constraints' lists at least one constraint");
        }
        // Resolve every reference before anything is added: a bad one is refused cleanly.
        ComponentConstraints constraints = ComponentConstraints.create();
        List<Object> asked = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            Map<String, Object> spec = Json.object(item, "a constraint");
            String type = Json.string(spec, "type");
            Object offset = spec.get("offset");
            ComponentConstraint c = pfcComponentFeat.ComponentConstraint_Create(constraintType(type, offset != null));
            if (!"default".equals(type) && !"fix".equals(type)) {
                c.SetAssemblyReference(assemblySelection(session, asm, Json.string(spec, "assembly_ref")));
                c.SetComponentReference(pfcSelect.CreateModelItemSelection(
                        Geometry.item(component, Json.string(spec, "component_ref")), null));
            }
            if (offset != null) {
                if (!(offset instanceof Double)) {
                    throw new Failures.Refusal("E_VALIDATION", "'offset' is a number");
                }
                c.SetOffset((Double) offset);
            }
            constraints.append(c);
            asked.add(type);
        }
        Double before = Creo.volumeOf(Creo.measure(asm));
        ComponentFeat feature = (ComponentFeat) asm.AssembleComponent(component, identity());
        try {
            feature.SetConstraints(constraints, null);
            asm.Regenerate(null);
        } catch (Throwable failure) {
            Failures.Stage failed = new Failures.Stage("constrain", failure);
            try {
                Creo.deleteFeatures(asm, feature.GetId());
                failed.cleanup = "component removed";
            } catch (Throwable stuck) {
                failed.cleanup = "NOT removed -- the assembly still holds component " + feature.GetId();
            }
            throw failed;
        }
        Creo.repaint(session);
        ComponentFeat placed = (ComponentFeat) asm.GetFeatureById(feature.GetId());
        Map<String, Object> out = Json.map(
                "model", Creo.fileName((Model) asm),
                "units", Creo.units(asm),
                "component", row(placed, Creo.fileName((Model) component)),
                "constraints_requested", asked);
        Double after = Creo.volumeOf(Creo.measure(asm));
        out.put("volume", Json.map("before", before, "after", after,
                "change", before == null || after == null ? null : after - before));
        return out;
    }

    private static ComponentConstraintType constraintType(String type, boolean offset) {
        switch (type) {
            case "mate": return offset ? ComponentConstraintType.ASM_CONSTRAINT_MATE_OFF
                    : ComponentConstraintType.ASM_CONSTRAINT_MATE;
            case "align": return offset ? ComponentConstraintType.ASM_CONSTRAINT_ALIGN_OFF
                    : ComponentConstraintType.ASM_CONSTRAINT_ALIGN;
            case "insert": return ComponentConstraintType.ASM_CONSTRAINT_INSERT;
            case "csys": return ComponentConstraintType.ASM_CONSTRAINT_CSYS;
            case "default": return ComponentConstraintType.ASM_CONSTRAINT_DEF_PLACEMENT;
            case "fix": return ComponentConstraintType.ASM_CONSTRAINT_FIX;
            default: throw new Failures.Refusal("E_VALIDATION",
                    "a constraint type is mate, align, insert, csys, default or fix");
        }
    }

    /** The assembly's own reference, or a component's, written ref@component. */
    static Selection assemblySelection(Session session, Assembly asm, String ref) throws jxthrowable {
        int at = ref.lastIndexOf('@');
        if (at < 0) {
            ModelItem item = Geometry.item(asm, ref);
            return pfcSelect.CreateModelItemSelection(item, pfcAssembly.CreateComponentPath(asm, intseq.create()));
        }
        ComponentFeat owner = component(asm, ref.substring(at + 1));
        Solid model = (Solid) session.GetModelFromDescr(owner.GetModelDescr());
        if (model == null) {
            throw new Failures.Refusal("E_NOT_FOUND", "component " + ref.substring(at + 1) + " is not in session");
        }
        intseq ids = intseq.create();
        ids.append(owner.GetId());
        ComponentPath path = pfcAssembly.CreateComponentPath(asm, ids);
        return pfcSelect.CreateModelItemSelection(Geometry.item(model, ref.substring(0, at)), path);
    }

    /** A component by its feature id, or by its model's name when only one instance has it. */
    static ComponentFeat component(Assembly asm, String wanted) throws jxthrowable {
        String base = wanted.toLowerCase(Locale.ROOT).replaceFirst("\\.(prt|asm)$", "");
        List<ComponentFeat> byName = new ArrayList<>();
        com.ptc.pfc.pfcFeature.Features all =
                asm.ListFeaturesByType(Boolean.TRUE, com.ptc.pfc.pfcFeature.FeatureType.FEATTYPE_COMPONENT);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            ComponentFeat c = (ComponentFeat) all.get(i);
            if (wanted.equals(String.valueOf(c.GetId()))) {
                return c;
            }
            String file = Creo.fileName(c.GetModelDescr()).toLowerCase(Locale.ROOT);
            if (file.replaceFirst("\\.(prt|asm)$", "").equals(base)) {
                byName.add(c);
            }
        }
        if (byName.size() == 1) {
            return byName.get(0);
        }
        throw new Failures.Refusal(byName.isEmpty() ? "E_NOT_FOUND" : "E_CONFLICT", byName.isEmpty()
                ? "no component " + wanted + " in " + Creo.fileName((Model) asm)
                : wanted + " is placed " + byName.size() + " times; name the component by its id");
    }

    private static Transform3D identity() throws jxthrowable {
        Matrix3D m = Matrix3D.create();
        for (int i = 0; i < 4; i++) {
            for (int j = 0; j < 4; j++) {
                m.set(i, j, i == j ? 1.0 : 0.0);
            }
        }
        return pfcBase.Transform3D_Create(m);
    }

    /** One component as every reply reports it: where it is and how firmly it is placed. */
    static Map<String, Object> row(ComponentFeat c, String model) throws jxthrowable {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", c.GetId());
        out.put("model", model);
        out.put("status", Creo.enumName(c.GetStatus()));
        try {
            out.put("placed", c.GetIsPlaced());
            out.put("packaged", c.GetIsPackaged());
            out.put("underconstrained", c.GetIsUnderconstrained());
        } catch (Throwable unreadable) {
            out.put("placement_error", Failures.error(unreadable));
        }
        List<Object> constraints = new ArrayList<>();
        try {
            ComponentConstraints held = c.GetConstraints();
            for (int i = 0; held != null && i < held.getarraysize(); i++) {
                ComponentConstraint k = held.get(i);
                constraints.add(Json.map("type", Creo.enumName(k.GetType()).replace("ASM_CONSTRAINT_", "")
                        .toLowerCase(Locale.ROOT), "offset", k.GetOffset(),
                        "assembly_reference", referenceRow(k.GetAssemblyReference()),
                        "component_reference", referenceRow(k.GetComponentReference()),
                        "assembly_side", Creo.enumName(k.GetAssemblyDatumSide()),
                        "component_side", Creo.enumName(k.GetComponentDatumSide())));
            }
        } catch (Throwable unreadable) {
            out.put("constraints_error", Failures.error(unreadable));
        }
        out.put("constraints", constraints);
        try {
            Transform3D at = c.GetPosition();
            out.put("position", Json.map("origin", Geometry.point(at.GetOrigin()),
                    "x_axis", Geometry.vector(at.GetXAxis()), "y_axis", Geometry.vector(at.GetYAxis()),
                    "z_axis", Geometry.vector(at.GetZAxis())));
        } catch (Throwable unreadable) {
            out.put("position", null);
        }
        try {
            intseq ids = intseq.create();
            ids.append(c.GetId());
            Assembly root = (Assembly) ((com.ptc.wfc.wfcFeature.WFeature) c).GetSolid();
            Transform3D at = pfcAssembly.CreateComponentPath(root, ids).GetTransform(true);
            out.put("component_path_transform", Json.map("origin", Geometry.point(at.GetOrigin()),
                    "x_axis", Geometry.vector(at.GetXAxis()), "y_axis", Geometry.vector(at.GetYAxis()),
                    "z_axis", Geometry.vector(at.GetZAxis())));
        } catch (Throwable unreadable) {
            out.put("component_path_transform", null);
        }
        return out;
    }

    // ------------------------------------------------------------------ assembly.replace

    private static Map<String, Object> referenceRow(com.ptc.pfc.pfcSelect.Selection selection) throws jxthrowable {
        if (selection == null) return null;
        List<Object> path = new ArrayList<>();
        if (selection.GetPath() != null) {
            com.ptc.cipjava.intseq ids = selection.GetPath().GetComponentIds();
            for (int i = 0; i < ids.getarraysize(); i++) path.add(ids.get(i));
        }
        return Json.map("model", Creo.fileName(selection.GetSelModel()).toLowerCase(Locale.ROOT),
                "item_id", selection.GetSelItem().GetId(), "item_type", Creo.enumName(selection.GetSelItem().GetType()),
                "component_path", path);
    }

    /**
     * Put another member of the component's family where it is -- another instance, or the
     * generic -- keeping its constraints, as Component > Replace does with a family table:
     * the members share their items' ids, so each reference finds its counterpart. Any other
     * model is refused: its items' ids mean nothing to the constraints, and Creo placed a
     * block by a pin's references without a word when it happened to have ids that matched.
     * Drawn by the native library (see creo_cli_component_replace); if Creo cannot place the
     * new member, the old one goes back.
     */
    static Map<String, Object> replace(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Assembly asm = assembly(session, Json.string(request, "model"));
        ComponentFeat target = component(asm, Json.string(request, "component"));
        Solid with = Creo.solid(session, Json.string(request, "with"));
        if (Creo.fileName((Model) with).equalsIgnoreCase(Creo.fileName((Model) asm))) {
            throw new Failures.Refusal("E_VALIDATION", "an assembly cannot contain itself");
        }
        if (Service.sketchLibrary() == null) {
            throw new Failures.Refusal("E_UNSUPPORTED", "a component is replaced by the native library, which "
                    + "is not loaded: " + Service.sketchLibraryStatus());
        }
        int id = target.GetId();
        com.ptc.pfc.pfcModel.ModelDescriptor oldDescr = target.GetModelDescr();
        String from = Creo.fileName(oldDescr).toLowerCase(Locale.ROOT);
        Model old = session.GetModelFromDescr(oldDescr);
        if (Creo.fileName((Model) with).equalsIgnoreCase(from)) {
            throw new Failures.Refusal("E_VALIDATION", "the component already is " + from);
        }
        String family = old instanceof Solid ? Families.top((Solid) old) : from;
        if (!Families.top(with).equalsIgnoreCase(family)) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName((Model) with) + " is not of " + from
                    + "'s family (" + family + " and its instances); a different model is removed and added "
                    + "with constraints of its own");
        }
        Map<String, Object> before = row(target, from);
        Double volumeBefore = Creo.volumeOf(Creo.measure(asm));
        Map<String, Object> report;
        try {
            report = nativeReplace(asm, id, (Model) with);
            asm.Regenerate(null);
        } catch (Throwable failure) {
            Failures.Stage stage = new Failures.Stage("replace", failure);
            stage.cleanup = putBack(asm, id, old, from);
            throw stage;
        }
        ComponentFeat now = (ComponentFeat) asm.GetFeatureById(id);
        String model = Creo.fileName(now.GetModelDescr()).toLowerCase(Locale.ROOT);
        Map<String, Object> placed = row(now, model);
        boolean held = model.equalsIgnoreCase(Creo.fileName((Model) with))
                && now.GetStatus().getValue() == com.ptc.pfc.pfcFeature.FeatureStatus._FEAT_ACTIVE
                && Boolean.TRUE.equals(placed.get("placed"));
        if (!held) {
            Failures.Stage stage = new Failures.Stage("regenerate", new Failures.Refusal("E_CREO",
                    "Creo could not place " + Creo.fileName((Model) with) + " by the constraints " + from
                            + " was placed by: " + placed.get("status")));
            stage.cleanup = putBack(asm, id, old, from);
            throw stage;
        }
        Creo.repaint(session);
        Double volumeAfter = Creo.volumeOf(Creo.measure(asm));
        return Json.map("model", Creo.fileName((Model) asm), "units", Creo.units(asm),
                "replaced", from, "component", placed, "before", before,
                "references_moved", report.get("references"),
                "volume", Json.map("before", volumeBefore, "after", volumeAfter,
                        "change", volumeBefore == null || volumeAfter == null ? null : volumeAfter - volumeBefore));
    }

    private static Map<String, Object> nativeReplace(Assembly asm, int id, Model with) throws Exception {
        String file = Creo.fileName(with);
        int dot = file.lastIndexOf('.');
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(
                        Creo.fileName((Model) asm).replaceFirst("(?i)\\.asm$", ""))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("feature_id",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue(id)));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("with",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(0, dot))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("with_type",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(
                        file.substring(dot + 1).toLowerCase(Locale.ROOT))));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.COMPONENT_REPLACE_FUNCTION, in);
        Map<String, Object> report = new LinkedHashMap<>();
        com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            com.ptc.pfc.pfcArgument.ArgValue value = out.get(i).GetValue();
            String type = Creo.enumName(value.Getdiscr());
            report.put(out.get(i).GetLabel(), "ARG_V_INTEGER".equals(type) ? (Object) value.GetIntValue()
                    : "ARG_V_ASCII_STRING".equals(type) ? value.GetASCIIStringValue() : value.GetStringValue());
        }
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message", "the component could not be "
                    + "replaced: stopped at " + report.get("failed_step") + " with toolkit error "
                    + result.GetFunctionReturn(), "toolkit_error", result.GetFunctionReturn(), "native", report));
        }
        return report;
    }

    /** The old model put back where it was, if the component no longer holds it. */
    private static String putBack(Assembly asm, int id, Model old, String from) {
        try {
            ComponentFeat now = (ComponentFeat) asm.GetFeatureById(id);
            boolean same = Creo.fileName(now.GetModelDescr()).equalsIgnoreCase(from)
                    && now.GetStatus().getValue() == com.ptc.pfc.pfcFeature.FeatureStatus._FEAT_ACTIVE;
            if (same) {
                return "the component unchanged";
            }
            if (old == null) {
                return "NOT put back -- " + from + " is not in session";
            }
            nativeReplace(asm, id, old);
            asm.Regenerate(null);
            return "the old model put back";
        } catch (Throwable stuck) {
            return "NOT put back -- " + Failures.error(stuck);
        }
    }

    // ------------------------------------------------------------------ assembly.explode

    /**
     * An exploded state, as View > Explode > Edit Position makes one: components moved along
     * directions by distances, the state named and made the active one. A state of the same
     * name is replaced only when asked.
     */
    static Map<String, Object> explode(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Assembly asm = assembly(session, Json.string(request, "model"));
        String name = Json.string(request, "name");
        boolean replace = Json.bool(request, "replace", false);
        Object raw = request.get("moves");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'moves' lists one move or more");
        }
        com.ptc.wfc.wfcAssembly.ExplodedAnimationMoveInstructions moves =
                com.ptc.wfc.wfcAssembly.ExplodedAnimationMoveInstructions.create();
        for (Object item : (List<?>) raw) {
            Map<String, Object> move = Json.object(item, "a move");
            com.ptc.wfc.wfcAssembly.WComponentPaths set = com.ptc.wfc.wfcAssembly.WComponentPaths.create();
            Object components = move.get("components");
            if (!(components instanceof List) || ((List<?>) components).isEmpty()) {
                throw new Failures.Refusal("E_VALIDATION", "a move names one component or more");
            }
            for (Object c : (List<?>) components) {
                ComponentFeat feature = component(asm, String.valueOf(c));
                intseq ids = intseq.create();
                ids.append(feature.GetId());
                set.append((com.ptc.wfc.wfcAssembly.WComponentPath) pfcAssembly.CreateComponentPath(asm, ids));
            }
            List<?> d = (List<?>) move.get("direction");
            double[] dir = new double[3];
            double length = 0;
            for (int i = 0; i < 3; i++) {
                dir[i] = ((Number) d.get(i)).doubleValue();
                length += dir[i] * dir[i];
            }
            length = Math.sqrt(length);
            if (length < 1e-9) {
                throw new Failures.Refusal("E_VALIDATION", "a move's direction is not zero");
            }
            com.ptc.pfc.pfcBase.Vector3D v = com.ptc.pfc.pfcBase.Vector3D.create();
            com.ptc.pfc.pfcBase.Point3D origin = com.ptc.pfc.pfcBase.Point3D.create();
            for (int i = 0; i < 3; i++) {
                v.set(i, dir[i] / length);
                origin.set(i, 0.0);
            }
            moves.append(com.ptc.wfc.wfcAssembly.wfcAssembly.ExplodedAnimationMoveInstruction_Create(set,
                    com.ptc.wfc.wfcAssembly.wfcAssembly.ExplodedAnimationMove_Create(
                            com.ptc.wfc.wfcAssembly.ExplodedAnimationMoveType.EXPLDANIM_MOVE_TRANSLATE, origin, v,
                            Json.number(move, "distance"))));
        }
        List<Object> before = explodedStates(asm);
        com.ptc.wfc.wfcAssembly.WExplodedState existing = state(asm, name);
        if (existing != null) {
            if (asm.GetDefaultExplodedState() != null && asm.GetDefaultExplodedState().GetId() == existing.GetId())
                throw new Failures.Refusal("E_UNSUPPORTED", "the default explosion state cannot be replaced");
            if (!replace) {
                throw new Failures.Refusal("E_CONFLICT", Creo.fileName((Model) asm) + " has an exploded state "
                        + name + " already; ask to replace it, or name another");
            }
            // Update the existing state in place; never delete a usable state before creation.
        }
        com.ptc.wfc.wfcAssembly.WExplodedState made;
        List<Object> normalBefore = null, normalAfter = null;
        requireAssemblyContext(session, asm);
        try {
            // Position getters include exploded display transforms. Within this confirmed
            // display write, inspect native normal placement before and after the edit.
            // Do not perform these state changes in any getter or dry-run.
            if (asm.GetIsExploded()) asm.UnExplode();
            normalBefore = ModelOps.components(asm);
            if (existing == null) {
                made = ((com.ptc.wfc.wfcAssembly.WAssembly) asm).CreateExplodedState(name, moves);
            } else {
                existing.SetExplodedStateMoves(moves);
                made = existing;
            }
            made.Activate();
            if (asm.GetIsExploded()) asm.UnExplode();
            normalAfter = ModelOps.components(asm);
            if (!asm.GetIsExploded()) asm.Explode();
        } catch (Throwable failure) {
            throw new Failures.Stage("explode", failure,
                    Json.map("normal_before", normalBefore, "normal_after", normalAfter));
        }
        Creo.repaint(session);
        return Json.map("model", Creo.fileName((Model) asm), "units", Creo.units(asm),
                "state", stateRow(asm, made), "states_before", before, "states", explodedStates(asm),
                "replaced", existing != null, "normal_before", normalBefore, "normal_after", normalAfter,
                "normal_placement_source", "native component/constraint getters with display un-exploded within confirmed write");
    }

    /** Every exploded state of an assembly, the active one marked. */
    static List<Object> explodedStates(Assembly asm) {
        List<Object> out = new ArrayList<>();
        try {
            com.ptc.pfc.pfcModelItem.ModelItems items =
                    asm.ListItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_EXPLODED_STATE);
            for (int i = 0; items != null && i < items.getarraysize(); i++) {
                out.add(stateRow(asm, (com.ptc.wfc.wfcAssembly.WExplodedState) items.get(i)));
            }
        } catch (Throwable unreadable) {
            return null; // Unknown is not an empty inventory.
        }
        return out;
    }

    static List<Object> explodedStatesStrict(Assembly asm) throws jxthrowable {
        com.ptc.pfc.pfcModelItem.ModelItems items =
                asm.ListItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_EXPLODED_STATE);
        if (items == null) throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "exploded-state inventory is null");
        List<Object> rows = new ArrayList<>();
        for (int i = 0; i < items.getarraysize(); i++) {
            com.ptc.wfc.wfcAssembly.WExplodedState state = (com.ptc.wfc.wfcAssembly.WExplodedState) items.get(i);
            Map<String, Object> row = stateRow(asm, state);
            // Required identity is read independently; optional move fields retain unknowns.
            row.put("id", state.GetId());
            row.put("name", state.GetExplodedStateName());
            rows.add(row);
        }
        return rows;
    }

    private static com.ptc.wfc.wfcAssembly.WExplodedState state(Assembly asm, String name) throws jxthrowable {
        com.ptc.pfc.pfcModelItem.ModelItems items =
                asm.ListItems(com.ptc.pfc.pfcModelItem.ModelItemType.ITEM_EXPLODED_STATE);
        for (int i = 0; items != null && i < items.getarraysize(); i++) {
            com.ptc.wfc.wfcAssembly.WExplodedState s = (com.ptc.wfc.wfcAssembly.WExplodedState) items.get(i);
            if (name.equalsIgnoreCase(s.GetExplodedStateName())) {
                return s;
            }
        }
        return null;
    }

    private static Map<String, Object> stateRow(Assembly asm, com.ptc.wfc.wfcAssembly.WExplodedState s)
            throws jxthrowable {
        Integer active = null;
        boolean activeRead = true;
        try {
            com.ptc.pfc.pfcAssembly.ExplodedState on = asm.GetActiveExplodedState();
            active = on == null ? null : on.GetId();
        } catch (Throwable none) {
            activeRead = false;
        }
        List<Object> moves = new ArrayList<>();
        try {
            com.ptc.wfc.wfcAssembly.ExplodedAnimationMoveInstructions held = s.GetExplodedStateMoves();
            for (int i = 0; held != null && i < held.getarraysize(); i++) {
                com.ptc.wfc.wfcAssembly.ExplodedAnimationMoveInstruction m = held.get(i);
                List<Object> ids = new ArrayList<>();
                List<Object> paths = new ArrayList<>();
                com.ptc.wfc.wfcAssembly.WComponentPaths set = m.GetCompSet();
                for (int j = 0; set != null && j < set.getarraysize(); j++) {
                    intseq path = set.get(j).GetComponentIds();
                    List<Object> fullPath = new ArrayList<>();
                    for (int k = 0; k < path.getarraysize(); k++) fullPath.add(String.valueOf(path.get(k)));
                    paths.add(fullPath);
                    ids.add(path.get(path.getarraysize() - 1));
                }
                com.ptc.wfc.wfcAssembly.ExplodedAnimationMove move = m.GetMove();
                com.ptc.pfc.pfcBase.Vector3D nativeDirection = move.GetDirVector();
                List<Object> observedDirection = Geometry.vector(nativeDirection);
                moves.add(Json.map("components", ids, "component_paths", paths,
                        "type", Creo.enumName(move.GetMoveType()).replace("EXPLDANIM_MOVE_", "").toLowerCase(Locale.ROOT),
                        "direction", observedDirection, "distance", move.GetValue(),
                        "direction_native_binary64", Geometry.binary64(observedDirection),
                        "numeric_encoding", Geometry.precision()));
            }
        } catch (Throwable unreadable) {
            moves = null;
        }
        com.ptc.pfc.pfcAssembly.ExplodedState defaultState = asm.GetDefaultExplodedState();
        return Json.map("name", s.GetExplodedStateName(), "id", s.GetId(),
                "is_default", defaultState != null && defaultState.GetId() == s.GetId(),
                "active", activeRead ? active != null && active == s.GetId() : null, "moves", moves);
    }

    /** Admission evidence, not a substitute for a nonexistent Session.GetMode API. */
    static Map<String, Object> explosionContext(Session session, Assembly asm) {
        Map<String, Object> out = Json.map("complete", false, "kind", "unknown",
                "assembly_context_admitted", false,
                "source", "Session.GetCurrentModel/GetCurrentWindow; Window.GetModel; Model.GetType/GetFileName");
        String stage = "target.Model.GetFileName";
        try {
            String targetName = Creo.fileName((Model) asm);
            out.put("target_model", targetName);
            stage = "Session.GetCurrentModel";
            Model current = session.GetCurrentModel();
            stage = "Session.GetCurrentWindow";
            com.ptc.pfc.pfcWindow.Window window = session.GetCurrentWindow();
            stage = "Window.GetModel";
            Model windowModel = window == null ? null : window.GetModel();
            stage = "current.Model.GetFileName";
            String currentName = current == null ? null : Creo.fileName(current);
            out.put("current_model", currentName);
            stage = "current.Model.GetType";
            ModelType currentType = current == null ? null : current.GetType();
            out.put("current_model_type", Creo.typeName(currentType));
            stage = "Window.GetId";
            out.put("window_id", window == null ? null : String.valueOf(window.GetId()));
            stage = "window.Model.GetFileName";
            String windowName = windowModel == null ? null : Creo.fileName(windowModel);
            out.put("window_model", windowName);
            stage = "window.Model.GetType";
            ModelType windowType = windowModel == null ? null : windowModel.GetType();
            out.put("window_model_type", Creo.typeName(windowType));
            if (current == null || windowModel == null || currentType == null || windowType == null) {
                out.put("reason", "current_model_or_window_model_absent");
                return out;
            }
            if (!currentName.equalsIgnoreCase(windowName) || currentType.getValue() != windowType.getValue()) {
                out.put("kind", "contradictory");
                out.put("reason", "current_model_and_window_model_disagree");
                return out;
            }
            boolean admitted = currentType.getValue() == ModelType._MDL_ASSEMBLY
                    && currentName.equalsIgnoreCase(targetName);
            out.put("complete", true);
            out.put("kind", admitted ? "assembly" : currentType.getValue() == ModelType._MDL_DRAWING
                    ? "drawing" : "other_model");
            out.put("assembly_context_admitted", admitted);
            return out;
        } catch (Throwable failure) {
            out.put("error", contextFailure(failure, stage));
            return out;
        }
    }

    private static Map<String, Object> contextFailure(Throwable failure, String stage) {
        // Pure Java metadata only: Toolkit exception diagnostics may call CAD again.
        return Json.map("exception_class", failure.getClass().getName(), "stage", stage,
                "source", "caught native getter failure; no further CAD diagnostics called");
    }

    private static void requireAssemblyContext(Session session, Assembly asm) {
        Map<String, Object> context = explosionContext(session, asm);
        if (!Boolean.TRUE.equals(context.get("complete"))
                || !Boolean.TRUE.equals(context.get("assembly_context_admitted")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE",
                    "explosion edit requires matching current assembly and window context; no automatic activation: "
                            + Json.write(context));
    }

    static Map<String, Object> explosion(Session session, Assembly asm) {
        Map<String, Object> out = Json.map("complete", false, "is_exploded", null,
                "context", explosionContext(session, asm),
                "source", "GetActiveExplodedState/GetDefaultExplodedState/GetExplodedStateMoves");
        Map<String, Object> context = (Map<String, Object>) out.get("context");
        Map<String, Object> display = Json.map("complete", false, "status", "incomplete", "value", null,
                "source", "Assembly.GetIsExploded");
        out.put("display_readback", display);
        if (Boolean.TRUE.equals(context.get("complete"))
                && Boolean.TRUE.equals(context.get("assembly_context_admitted"))) {
            try {
                boolean value = asm.GetIsExploded();
                out.put("is_exploded", value);
                display.put("complete", true);
                display.put("status", "observed");
                display.put("value", value);
            } catch (Throwable failure) { display.put("error", contextFailure(failure, "GetIsExploded")); }
        } else if (Boolean.TRUE.equals(context.get("complete")) && "drawing".equals(context.get("kind"))) {
            display.put("status", "not_checked");
            display.put("reason", "not_applicable_in_drawing_context; GetIsExploded not called");
        } else {
            display.put("reason", "assembly_context_not_admitted; GetIsExploded not called");
        }
        try {
            com.ptc.pfc.pfcAssembly.ExplodedState active = asm.GetActiveExplodedState();
            List<Object> states = explodedStatesStrict(asm);
            for (Object row : states) {
                Map<String, Object> state = (Map<String, Object>) row;
                if (state.get("moves") == null || state.get("active") == null || state.get("is_default") == null)
                    throw new IllegalStateException("incomplete explosion state");
            }
            String activeId = active == null ? null : String.valueOf(active.GetId());
            out.put("states", states);
            out.put("active_state_id", activeId);
            out.put("complete", true);
        } catch (Throwable failure) {
            out.put("complete", false);
            out.put("error", contextFailure(failure, "explosion_inventory"));
        }
        return out;
    }

    // ------------------------------------------------------------------ assembly.remove

    /** Take a component out, with every feature that depends on it. */
    static Map<String, Object> remove(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Assembly asm = assembly(session, Json.string(request, "model"));
        ComponentFeat target = component(asm, Json.string(request, "component"));
        String model = Creo.fileName(target.GetModelDescr()).toLowerCase(Locale.ROOT);
        List<Object> removed = new ArrayList<>();
        java.util.Set<Integer> visible = Creo.visibleFeatureIds(asm);
        collect(target, removed, visible, new java.util.HashSet<>());
        Creo.deleteFeatures(asm, target.GetId());
        Creo.repaint(session);
        boolean gone;
        try {
            gone = asm.GetFeatureById(target.GetId()) == null;
        } catch (Throwable absent) {
            gone = true;
        }
        return Json.map("model", Creo.fileName((Model) asm), "component", model, "removed", removed, "gone", gone,
                "components", ModelOps.components(asm));
    }

    private static void collect(Feature f, List<Object> into, java.util.Set<Integer> visible,
                                java.util.Set<Integer> seen) throws jxthrowable {
        if (!seen.add(f.GetId())) {
            return;
        }
        into.add(Creo.featureRow(f, visible));
        com.ptc.pfc.pfcFeature.Features children = f.ListChildren();
        for (int i = 0; children != null && i < children.getarraysize(); i++) {
            collect(children.get(i), into, visible, seen);
        }
    }

    // ------------------------------------------------------------------ assembly.check

    /**
     * Every component and how it is placed, and every pair of parts that interferes, with the
     * volume they share -- Creo's global interference check.
     */
    static Map<String, Object> check(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Assembly asm = assembly(session, Json.string(request, "model"));
        List<Object> clashes = new ArrayList<>();
        com.ptc.pfc.pfcInterference.GlobalInterferences found =
                com.ptc.pfc.pfcInterference.pfcInterference.CreateGlobalEvaluator(asm).ComputeGlobalInterference(true);
        for (int i = 0; found != null && i < found.getarraysize(); i++) {
            com.ptc.pfc.pfcInterference.GlobalInterference clash = found.get(i);
            com.ptc.pfc.pfcSelect.SelectionPair pair = clash.GetSelParts();
            clashes.add(Json.map(
                    "parts", java.util.Arrays.asList(part(pair.GetSel1()), part(pair.GetSel2())),
                    "volume", clash.GetVolume().ComputeVolume()));
        }
        List<Object> components = ModelOps.components(asm);
        int loose = 0;
        for (Object c : components) {
            @SuppressWarnings("unchecked")
            Map<String, Object> row = (Map<String, Object>) c;
            if (Boolean.TRUE.equals(row.get("packaged")) || Boolean.TRUE.equals(row.get("underconstrained"))) {
                loose++;
            }
        }
        return Json.map("model", Creo.fileName((Model) asm), "units", Creo.units(asm), "components", components,
                "not_fully_constrained", loose, "interferences", clashes, "completed", true,
                "source", "GlobalEvaluator.ComputeGlobalInterference(true)",
                "coverage", Json.map("scope", "whole_assembly", "interference_count", clashes.size()),
                "not_checked", List.of("pair_subset", "nested_placement_completeness"));
    }

    private static Object part(Selection sel) {
        try {
            Map<String, Object> out = Json.map("model", Creo.fileName(sel.GetSelModel()));
            ComponentPath path = sel.GetPath();
            if (path != null) {
                List<Object> ids = new ArrayList<>();
                for (int i = 0; i < path.GetComponentIds().getarraysize(); i++) ids.add(path.GetComponentIds().get(i));
                out.put("component_path", ids);
            }
            return out;
        } catch (Throwable unreadable) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "interference component path getter failed");
        }
    }
}
