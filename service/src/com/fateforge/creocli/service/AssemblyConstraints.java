package com.fateforge.creocli.service;

import com.ptc.cipjava.intseq;
import com.ptc.pfc.pfcAssembly.Assembly;
import com.ptc.pfc.pfcAssembly.ComponentPath;
import com.ptc.pfc.pfcAssembly.pfcAssembly;
import com.ptc.pfc.pfcBase.DatumSide;
import com.ptc.pfc.pfcBase.Transform3D;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraint;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraintType;
import com.ptc.pfc.pfcComponentFeat.ComponentConstraints;
import com.ptc.pfc.pfcComponentFeat.ComponentFeat;
import com.ptc.pfc.pfcComponentFeat.ConstraintAttributes;
import com.ptc.pfc.pfcComponentFeat.pfcComponentFeat;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.Features;
import com.ptc.pfc.pfcFeature.FeatureType;
import com.ptc.pfc.pfcGeometry.Surface;
import com.ptc.pfc.pfcGeometry.SurfaceOrientation;
import com.ptc.pfc.pfcGeometry.SurfaceType;
import com.ptc.pfc.pfcGeometry.TransformedSurface;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ModelItem;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSelect.Selection;
import com.ptc.pfc.pfcSelect.pfcSelect;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.pfc.pfcWindow.Window;
import com.ptc.wfc.wfcComponentFeat.WComponentFeat;
import com.ptc.wfc.wfcElementTree.Element;
import com.ptc.wfc.wfcElementTree.ElementTree;
import com.ptc.wfc.wfcElementTree.Elements;
import com.ptc.wfc.wfcFeature.FeatureElemTreeExtractOptions;
import com.ptc.wfc.wfcFeature.WFeature;
import com.ptc.wfc.wfcElemIds.wfcElemIds;
import java.lang.ref.Reference;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Independent direct-occurrence constraint readings and in-place redefinition.
 * No component creation, removal, replacement, position setter or automatic rollback.
 */
final class AssemblyConstraints {
    static final String PROFILE = "direct-planar-constraints-v2";
    static final String CAPABILITY = "assembly_constraint_redefinition";
    static final int CAPABILITY_VERSION = 2;
    private AssemblyConstraints() { }

    static Map<String, Object> state(Map<String, Object> request) throws Exception {
        Probe probe = new Probe(Json.string(request, "model"));
        try { return probe.read(); }
        finally { Reference.reachabilityFence(probe.held); }
    }

    static Map<String, Object> redefine(Map<String, Object> request) throws Exception {
        String model = Json.string(request, "model");
        int id = Json.integer(request, "component");
        Map<String, Object> expected = Json.object(request.get("expected"), "expected native state");
        Probe probe = new Probe(model);
        String stage = "before_dispatch";
        boolean setterReturned = false;
        boolean regenerateReturned = false;
        try {
            Map<String, Object> before = probe.read();
            if (!same(before, expected)) throw refusal("E_CONFLICT", "assembly constraint state changed; query again before a new preview");
            @SuppressWarnings("unchecked") Map<String, Object> context = (Map<String, Object>) before.get("context");
            if (!modelName(probe.asm).equals(context.get("current_model"))
                    || !modelName(probe.asm).equals(context.get("window_model"))
                    || !Boolean.FALSE.equals(context.get("is_exploded"))
                    || !Boolean.FALSE.equals(context.get("dynamic_positioning")))
                throw refusal("E_CONFLICT", "redefinition requires the owner assembly's normal, non-dynamic model/window context");
            ComponentFeat target = probe.component(id);
            Map<String, Object> targetRow = probe.rows.get(id);
            requireEditable(targetRow);
            if (!"mm".equals(Json.string(request, "units")))
                throw refusal("E_UNSUPPORTED", "this profile requires explicit mm offsets and millimetre models");
            Object specs = request.get("constraints");
            if (!(specs instanceof List<?>) || ((List<?>) specs).size() < 3 || ((List<?>) specs).size() > 6)
                throw refusal("E_VALIDATION", "supply 3..6 explicit planar mate/align constraints");
            List<String> userData = retainedUserData(targetRow, ((List<?>) specs).size());
            ComponentConstraints constraints = ComponentConstraints.create();
            probe.held.add(constraints);
            Solid child = probe.child(target);
            int constraintIndex = 0;
            for (Object raw : (List<?>) specs) {
                Map<String, Object> spec = Json.object(raw, "constraint");
                String type = Json.string(spec, "type");
                ComponentConstraintType nativeType = "mate".equals(type) ? ComponentConstraintType.ASM_CONSTRAINT_MATE_OFF
                        : "align".equals(type) ? ComponentConstraintType.ASM_CONSTRAINT_ALIGN_OFF : null;
                if (nativeType == null) throw refusal("E_UNSUPPORTED", "only explicit planar mate and align offsets are supported");
                if (!"mm".equals(Json.string(spec, "units", "mm")))
                    throw refusal("E_UNSUPPORTED", "each offset is explicitly in mm");
                double offset = Json.number(spec, "offset");
                Selection assemblyRef = probe.select(Json.object(spec.get("assembly_reference"), "assembly reference"), null, id);
                Selection componentRef = probe.select(Json.object(spec.get("component_reference"), "component reference"), child, id);
                DatumSide assemblySide = probe.side(assemblyRef, Json.string(spec, "assembly_side"));
                DatumSide componentSide = probe.side(componentRef, Json.string(spec, "component_side"));
                ComponentConstraint constraint = pfcComponentFeat.ComponentConstraint_Create(nativeType);
                probe.held.add(constraint);
                probe.run("ComponentConstraint.SetAssemblyReference", () -> constraint.SetAssemblyReference(assemblyRef));
                probe.run("ComponentConstraint.SetComponentReference", () -> constraint.SetComponentReference(componentRef));
                probe.run("ComponentConstraint.SetAssemblyDatumSide", () -> constraint.SetAssemblyDatumSide(assemblySide));
                probe.run("ComponentConstraint.SetComponentDatumSide", () -> constraint.SetComponentDatumSide(componentSide));
                probe.run("ComponentConstraint.SetOffset", () -> constraint.SetOffset(offset));
                // Both empty and null are real optional values. Preserve the old getter result, never normalize it.
                String retainedData = userData.get(constraintIndex++);
                probe.run("ComponentConstraint.SetUserDefinedData(retained)", () -> constraint.SetUserDefinedData(retainedData));
                constraints.append(constraint);
            }
            // Reference construction and all foreseeable input checks precede the only model setter.
            probe.ensureGeneration();
            stage = "model_constraints_set";
            probe.run("ComponentFeat.SetConstraints(existing)", () -> target.SetConstraints(constraints, null));
            setterReturned = true;
            NativeReadTrace.effect("assembly_constraints_set_returned", Json.map("model", modelName(probe.asm), "component", id));
            stage = "model_constraints_regenerate";
            probe.run("Assembly.Regenerate(after-existing-constraint-set)", () -> probe.asm.Regenerate(null));
            regenerateReturned = true;
            NativeReadTrace.effect("assembly_constraints_regenerate_returned", Json.map("model", modelName(probe.asm), "component", id));
            stage = "model_constraints_independent_read";
            // A new Probe re-obtains every native object and every required value.
            Map<String, Object> after = state(Json.map("model", model));
            return Json.map("model", modelName(probe.asm), "target_id", id,
                    "stage", "independent_read_complete", "setter_returned", true,
                    "regenerate_returned", true, "state", after);
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            if ("before_dispatch".equals(stage)) {
                if (failure instanceof Exception) throw (Exception) failure;
                throw (Error) failure;
            }
            Map<String, Object> fact = Json.map("model", model, "component", id, "setter_started", true,
                    "setter_returned", setterReturned, "regenerate_returned", regenerateReturned,
                    "rollback_attempted", false, "replay_permitted", false,
                    "inspection", "independently inspect the retained occurrence and its constraints; no automatic replay or restoration");
            throw new Failures.Stage(stage, failure, fact);
        } finally { Reference.reachabilityFence(probe.held); }
    }

    private static void requireEditable(Map<String, Object> row) {
        for (String flag : List.of("frozen", "bulkitem", "substitute", "flexible", "embedded", "unplaced", "packaged", "underconstrained"))
            if (!Boolean.FALSE.equals(row.get(flag))) throw refusal("E_UNSUPPORTED", "target must be a placed rigid ordinary occurrence; unsupported flag: " + flag);
        if (!Boolean.TRUE.equals(row.get("placed")) || !"FEAT_ACTIVE".equals(row.get("status")))
            throw refusal("E_UNSUPPORTED", "target occurrence is not fully active and placed");
        @SuppressWarnings("unchecked") Map<String, Object> metadata = (Map<String, Object>) row.get("placement_metadata");
        if (!Boolean.TRUE.equals(metadata.get("supported")))
            throw refusal("E_UNSUPPORTED", "target has unsupported constraint-set, interface or attribute metadata");
        @SuppressWarnings("unchecked") List<Map<String, Object>> constraints = (List<Map<String, Object>>) row.get("constraints");
        for (Map<String, Object> constraint : constraints) {
            Object userData = constraint.get("user_data");
            if (userData != null && !"".equals(userData))
                throw refusal("E_UNSUPPORTED", "target has constraint user data this bounded editor cannot preserve");
            @SuppressWarnings("unchecked") Map<String, Object> attrs = (Map<String, Object>) constraint.get("attributes");
            if (attrs == null || (!Boolean.TRUE.equals(attrs.get("raw_null_default"))
                    && (!Boolean.FALSE.equals(attrs.get("force")) || !Boolean.FALSE.equals(attrs.get("ignore")))))
                throw refusal("E_UNSUPPORTED", "target has forced, ignored or unreadable constraint attributes");
        }
    }

    /** Public input and native output use different JSON numeric wrapper types. */
    static boolean same(Object first, Object second) {
        return Json.parse(Json.write(first)).equals(Json.parse(Json.write(second)));
    }

    static List<String> retainedUserData(Map<String, Object> row, int requestedCount) {
        Object raw = row.get("constraints");
        if (!(raw instanceof List<?>)) throw refusal("E_VERIFY_INCOMPLETE", "old constraint sequence is unreadable");
        List<?> constraints = (List<?>) raw;
        if (requestedCount != constraints.size())
            throw refusal("E_UNSUPPORTED", "this bounded redefinition preserves the actual old constraint count");
        List<String> values = new ArrayList<>();
        for (Object item : constraints) {
            if (!(item instanceof Map<?, ?>) || !((Map<?, ?>) item).containsKey("user_data"))
                throw refusal("E_VERIFY_INCOMPLETE", "old constraint custom-data getter is missing");
            Object value = ((Map<?, ?>) item).get("user_data");
            if (value != null && !(value instanceof String))
                throw refusal("E_VERIFY_INCOMPLETE", "old constraint custom-data getter is not a string or explicit null");
            if (value instanceof String && !((String) value).isEmpty())
                throw refusal("E_UNSUPPORTED", "nonempty constraint custom data is outside this bounded editor");
            values.add((String) value);
        }
        return values;
    }

    @SuppressWarnings("unchecked")
    static int uniqueAuxiliaryConstraint(List<?> constraints, Map<String, Object> reference, double offset) {
        int found = -1;
        for (int i = 0; i < constraints.size(); i++) {
            if (!(constraints.get(i) instanceof Map<?, ?>)) return -1;
            Map<String, Object> constraint = (Map<String, Object>) constraints.get(i);
            String type = String.valueOf(constraint.get("type"));
            if (!("mate".equals(type) || "align".equals(type))) continue;
            String nativeType = String.valueOf(constraint.get("native_type"));
            if (!(nativeType.equals("ASM_CONSTRAINT_" + type.toUpperCase(Locale.ROOT))
                    || nativeType.equals("ASM_CONSTRAINT_" + type.toUpperCase(Locale.ROOT) + "_OFF"))) continue;
            if (!(constraint.get("assembly_reference") instanceof Map<?, ?>)) continue;
            Map<String, Object> original = (Map<String, Object>) constraint.get("assembly_reference");
            boolean sameRef = true;
            for (String key : List.of("model", "item_id", "item_type", "component_path", "path_present",
                    "path_root_model", "path_root_source", "path_leaf_model", "path_leaf_source", "reference_owner_model")) {
                if (!reference.containsKey(key) || !original.containsKey(key)
                        || !same(Json.map("value", reference.get(key)), Json.map("value", original.get(key)))) {
                    sameRef = false; break;
                }
            }
            Object raw = constraint.get("offset");
            if (!constraint.containsKey("offset") || raw != null && !(raw instanceof Number)) continue;
            // Null-zero interpretation is restricted to an actually read native mate/align offset.
            double value = raw == null ? 0.0 : ((Number) raw).doubleValue();
            if (!sameRef || !Double.isFinite(value) || value != offset) continue;
            if (found >= 0) return -1;
            found = i;
        }
        return found;
    }

    @SuppressWarnings("unchecked")
    static boolean auxiliaryPlaneEquation(Map<String, Object> actual, Map<String, Object> reference,
            double offset, int flip, Map<String, Object> transform) {
        if (!Double.isFinite(offset) || flip != Ptc.PRO_DTMPLN_FLIP_DIR_NO && flip != Ptc.PRO_DTMPLN_FLIP_DIR_YES) return false;
        try {
            Map<String, Object> source = (Map<String, Object>) reference.get("plane");
            double[] origin = coordinates(source.get("origin")), normal = coordinates(source.get("normal"));
            if (transform != null) {
                origin = transformCoordinates(origin, transform, true);
                normal = transformCoordinates(normal, transform, false);
            }
            double[] actualOrigin = coordinates(actual.get("origin")), actualNormal = coordinates(actual.get("normal"));
            Map<String, Object> actualFrame = (Map<String, Object>) actual.get("frame");
            double[][] axes = {coordinates(actualFrame.get("x_axis")), coordinates(actualFrame.get("y_axis")), coordinates(actualFrame.get("z_axis"))};
            for (int i = 0; i < 3; i++) {
                for (int j = 0; j < 3; j++) if (Math.abs(dot(axes[i], axes[j]) - (i == j ? 1.0 : 0.0)) > 1e-7) return false;
                if (Math.abs(actualOrigin[i] - coordinates(actualFrame.get("origin"))[i]) > 1e-7
                        || Math.abs(actualNormal[i] - axes[2][i]) > 1e-7) return false;
            }
            double handed = axes[0][0] * (axes[1][1] * axes[2][2] - axes[1][2] * axes[2][1])
                    - axes[0][1] * (axes[1][0] * axes[2][2] - axes[1][2] * axes[2][0])
                    + axes[0][2] * (axes[1][0] * axes[2][1] - axes[1][1] * axes[2][0]);
            if (Math.abs(handed - 1) > 1e-7 || Math.abs(dot(normal, normal) - 1) > 1e-7) return false;
            double sign = flip == Ptc.PRO_DTMPLN_FLIP_DIR_NO ? 1 : -1;
            if (Math.abs(dot(normal, actualNormal) - sign) > 1e-7) return false;
            double distance = 0;
            for (int i = 0; i < 3; i++) distance += (actualOrigin[i] - origin[i]) * normal[i];
            return Math.abs(distance - offset) <= 1e-7;
        } catch (RuntimeException malformed) { return false; }
    }

    private static double[] coordinates(Object raw) {
        if (!(raw instanceof List<?>) || ((List<?>) raw).size() != 3) throw new IllegalArgumentException("missing vector");
        double[] result = new double[3];
        for (int i = 0; i < 3; i++) {
            Object value = ((List<?>) raw).get(i);
            if (!(value instanceof Number) || !Double.isFinite(((Number) value).doubleValue())) throw new IllegalArgumentException("invalid vector");
            result[i] = ((Number) value).doubleValue();
        }
        return result;
    }
    private static double dot(double[] a, double[] b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
    private static double[] transformCoordinates(double[] value, Map<String, Object> transform, boolean point) {
        double[][] axes = {coordinates(transform.get("x_axis")), coordinates(transform.get("y_axis")), coordinates(transform.get("z_axis"))};
        double[] result = point ? coordinates(transform.get("origin")) : new double[3];
        for (int j = 0; j < 3; j++) for (int i = 0; i < 3; i++) result[j] += axes[i][j] * value[i];
        return result;
    }

    /** Pure identity admission; native acquisition and direct-owner member validation remain separate. */
    static boolean referencePathAdmitted(boolean componentSide, String owner, String child,
            boolean childIsAssembly, int targetId, boolean pathPresent, List<Integer> ids,
            String root, String leaf, String selectedModel) {
        if (owner == null || child == null || selectedModel == null || ids == null) return false;
        if (componentSide) {
            if (!child.equals(selectedModel)) return false;
            if (!pathPresent) return ids.isEmpty() && root == null && leaf == null;
            if (ids.isEmpty()) return childIsAssembly && child.equals(root) && leaf == null;
            return ids.size() == 1 && ids.get(0) == targetId && owner.equals(root) && child.equals(leaf);
        }
        if (!pathPresent || !owner.equals(root)) return false;
        if (ids.isEmpty()) return owner.equals(selectedModel) && leaf == null;
        return ids.size() == 1 && ids.get(0) != targetId && selectedModel.equals(leaf);
    }

    private static Failures.Refusal refusal(String code, String message) { return new Failures.Refusal(code, message); }
    private static String modelName(Model model) throws com.ptc.cipjava.jxthrowable { return Creo.fileName(model).toLowerCase(Locale.ROOT); }

    private static final class Probe {
        final List<Object> held = new ArrayList<>();
        final Session session;
        final Assembly asm;
        final String serviceInstanceId;
        final Map<Integer, ComponentFeat> occurrences = new LinkedHashMap<>();
        final Map<Integer, Map<String, Object>> rows = new LinkedHashMap<>();
        final Map<String, Object> modelOrigins = new LinkedHashMap<>();
        final Map<String, Object> modelOriginReadback = new LinkedHashMap<>();
        final List<Object> catalog = new ArrayList<>();
        final Map<Integer, Surface> rootInternalSurfaces = new LinkedHashMap<>();
        final Map<Integer, Map<String, Object>> rootInternalEntries = new LinkedHashMap<>();

        Probe(String model) throws Exception {
            serviceInstanceId = Service.instanceIdForReadback();
            if (serviceInstanceId == null || serviceInstanceId.isBlank())
                throw refusal("E_VERIFY_INCOMPLETE", "actual service generation is unavailable; no CAD state was read");
            session = q("Creo.session", Creo::session);
            asm = q("Assemblies.assembly", () -> Assemblies.assembly(session, model));
        }

        <T> T q(String name, NativeReadTrace.Call<T> action) {
            T value = NativeReadTrace.call(name, action);
            if (value != null) held.add(value);
            return value;
        }
        void run(String name, NativeReadTrace.VoidCall action) { q(name, () -> { action.run(); return null; }); }

        void ensureGeneration() {
            if (!serviceInstanceId.equals(Service.instanceIdForReadback()))
                throw refusal("E_CONFLICT", "service generation changed during constraint observation; no selection may be reused");
        }

        Map<String, Object> read() throws Exception {
            ensureGeneration();
            String owner = q("Model.GetFileName(owner)", () -> modelName(asm));
            bindOrigin(asm);
            String workingDirectory = q("Session.GetCurrentDirectory(constraint-origin)", session::GetCurrentDirectory);
            if (workingDirectory == null || workingDirectory.isBlank())
                throw refusal("E_VERIFY_INCOMPLETE", "actual working directory is unavailable");
            Map<String, Object> units = units(asm);
            Model current = q("Session.GetCurrentModel(constraint-context)", session::GetCurrentModel);
            Window window = q("Session.GetCurrentWindow(constraint-context)", session::GetCurrentWindow);
            Model windowModel = window == null ? null : q("Window.GetModel(constraint-context)", window::GetModel);
            Map<String, Object> context = Json.map("current_model", current == null ? null : modelName(current),
                    "window_model", windowModel == null ? null : modelName(windowModel),
                    "is_exploded", q("Assembly.GetIsExploded", asm::GetIsExploded),
                    "dynamic_positioning", q("Assembly.GetDynamicPositioning", asm::GetDynamicPositioning));
            Features features = q("Assembly.ListFeaturesByType(components-all)", () -> asm.ListFeaturesByType(Boolean.FALSE, FeatureType.FEATTYPE_COMPONENT));
            if (features == null) throw refusal("E_VERIFY_INCOMPLETE", "component inventory is unavailable");
            int count = q("Features.getarraysize(components)", features::getarraysize);
            if (count == 0 || count > 32) throw refusal("E_UNSUPPORTED", "constraint profile requires 1..32 direct occurrences");
            addCatalog(asm, List.of());
            List<Object> components = new ArrayList<>();
            for (int i = 0; i < count; i++) {
                final int index = i;
                Feature feature = q("Features.get(component)", () -> features.get(index));
                if (!(feature instanceof ComponentFeat) || !(feature instanceof WComponentFeat))
                    throw refusal("E_VERIFY_INCOMPLETE", "component feature lacks supported ComponentFeat/WComponentFeat interfaces");
                ComponentFeat component = (ComponentFeat) feature;
                int id = q("ComponentFeat.GetId", component::GetId);
                if (occurrences.put(id, component) != null) throw refusal("E_VERIFY_INCOMPLETE", "duplicate direct occurrence ID");
                Map<String, Object> row = row(component);
                rows.put(id, row);
                components.add(row);
                addCatalog(child(component), List.of(id));
            }
            // All direct occurrence identities and constraints must exist before associating construction inputs.
            for (Map.Entry<Integer, Surface> internal : rootInternalSurfaces.entrySet()) {
                Map<String, Object> entry = rootInternalEntries.get(internal.getKey());
                entry.put("auxiliary", auxiliary(internal.getValue(), entry));
            }
            Features failed = q("Assembly.ListFailedFeatures", asm::ListFailedFeatures);
            List<Object> failedIds = ids(failed);
            String finalDirectory = q("Session.GetCurrentDirectory(constraint-origin-final)", session::GetCurrentDirectory);
            if (!workingDirectory.equals(finalDirectory))
                throw refusal("E_CONFLICT", "working directory changed during constraint observation");
            ensureGeneration();
            return Json.map("profile", PROFILE, "service_instance_id", serviceInstanceId,
                    "complete", true, "model", owner, "units", units,
                    "working_directory", workingDirectory, "working_directory_source", "Session.GetCurrentDirectory",
                    "model_origins", modelOrigins, "model_origin_readback", modelOriginReadback,
                    "context", context, "components", components, "reference_catalog", catalog,
                    "failed_features", failedIds, "source", "independent ComponentFeat constraints; ComponentPath.GetTransform(true); indexed element metadata and planar getters");
        }

        ComponentFeat component(int id) {
            ComponentFeat found = occurrences.get(id);
            if (found == null) throw refusal("E_NOT_FOUND", "no direct occurrence ID " + id);
            return found;
        }
        Solid child(ComponentFeat component) {
            var descriptor = q("ComponentFeat.GetModelDescr", component::GetModelDescr);
            Model child = q("Session.GetModelFromDescr(component)", () -> session.GetModelFromDescr(descriptor));
            if (!(child instanceof Solid)) throw refusal("E_VERIFY_INCOMPLETE", "component solid is unavailable");
            units((Solid) child);
            bindOrigin((Solid) child);
            return (Solid) child;
        }
        void bindOrigin(Solid model) {
            String name = q("Model.GetFileName(origin-binding)", () -> modelName(model));
            if (modelOrigins.containsKey(name)) return; // Once per distinct definition in this Probe, never across a write/request.
            String origin = q("Model.GetOrigin(constraint-binding)", model::GetOrigin);
            modelOrigins.put(name, origin);
            modelOriginReadback.put(name, Json.map("source", "Model.GetOrigin", "read_complete", true,
                    "result_category", origin == null ? "returned_null_unqualified" : "returned_string"));
        }
        Map<String, Object> units(Solid solid) {
            var system = q("Solid.GetPrincipalUnits", solid::GetPrincipalUnits);
            if (system == null) throw refusal("E_VERIFY_INCOMPLETE", "principal unit system is unavailable");
            var length = q("UnitSystem.GetUnit(length)", () -> system.GetUnit(com.ptc.pfc.pfcBase.UnitType.UNIT_LENGTH));
            String name = q("Unit.GetName(length)", length::GetName);
            if (!"mm".equalsIgnoreCase(name)) throw refusal("E_UNSUPPORTED", "constraint profile supports explicitly millimetre models only");
            return Json.map("length", "mm", "system", q("UnitSystem.GetName", system::GetName));
        }

        Map<String, Object> row(ComponentFeat c) throws Exception {
            int id = q("ComponentFeat.GetId(row)", c::GetId);
            WComponentFeat w = (WComponentFeat) c;
            Solid model = child(c);
            List<Object> constraints = constraintRows(c);
            Map<String, Object> row = Json.map("id", id, "owner", modelName(asm), "component_path", List.of(id),
                    "model", modelName(model), "model_type", q("Model.GetType(component)", model::GetType).getValue() == ModelType._MDL_PART ? "part" : "assembly",
                    "status", Creo.enumName(q("ComponentFeat.GetStatus", c::GetStatus)),
                    "placed", q("ComponentFeat.GetIsPlaced", c::GetIsPlaced), "packaged", q("ComponentFeat.GetIsPackaged", c::GetIsPackaged),
                    "underconstrained", q("ComponentFeat.GetIsUnderconstrained", c::GetIsUnderconstrained),
                    "frozen", q("ComponentFeat.GetIsFrozen", c::GetIsFrozen), "bulkitem", q("ComponentFeat.GetIsBulkitem", c::GetIsBulkitem),
                    "substitute", q("ComponentFeat.GetIsSubstitute", c::GetIsSubstitute), "flexible", q("WComponentFeat.IsFlexible", w::IsFlexible),
                    "embedded", q("WComponentFeat.IsEmbedded", w::IsEmbedded), "unplaced", q("WComponentFeat.IsUnplaced", w::IsUnplaced),
                    "parents", ids(q("Feature.ListParents(component)", c::ListParents)), "children", ids(q("Feature.ListChildren(component)", c::ListChildren)),
                    "constraints", constraints, "placement_metadata", metadata(w, constraints.size(), id),
                    "initial_position", frame(q("ComponentFeat.GetPosition(initial-only)", c::GetPosition)));
            ComponentPath path = path(List.of(id));
            row.put("component_path_transform", frame(q("ComponentPath.GetTransform(true)", () -> path.GetTransform(true))));
            if (q("Model.GetType(rigid-child)", model::GetType).getValue() == ModelType._MDL_ASSEMBLY) {
                Assembly nested = (Assembly) model;
                if (q("Assembly.GetDynamicPositioning(rigid-child)", nested::GetDynamicPositioning)
                        || q("Assembly.GetIsExploded(rigid-child)", nested::GetIsExploded))
                    throw refusal("E_UNSUPPORTED", "exploded/dynamic rigid-child assembly is unsupported");
                Features nestedFeatures = q("Solid.ListFeaturesByType(rigid-child)", () -> model.ListFeaturesByType(Boolean.FALSE, FeatureType.FEATTYPE_COMPONENT));
                if (nestedFeatures == null) throw refusal("E_VERIFY_INCOMPLETE", "rigid-child occurrence inventory is unavailable");
                List<Object> rigidChildren = new ArrayList<>();
                int nestedCount = q("Features.getarraysize(rigid-child)", nestedFeatures::getarraysize);
                for (int j = 0; j < nestedCount; j++) {
                    final int index = j;
                    Feature nestedFeature = q("Features.get(rigid-child)", () -> nestedFeatures.get(index));
                    if (!(nestedFeature instanceof ComponentFeat) || !(nestedFeature instanceof WComponentFeat))
                        throw refusal("E_VERIFY_INCOMPLETE", "rigid child lacks supported component interfaces");
                    ComponentFeat nestedComponent = (ComponentFeat) nestedFeature;
                    WComponentFeat nestedW = (WComponentFeat) nestedComponent;
                    Solid nestedSolid = child(nestedComponent);
                    if (q("Model.GetType(rigid-grandchild)", nestedSolid::GetType).getValue() != ModelType._MDL_PART)
                        throw refusal("E_UNSUPPORTED", "this profile covers one rigid subassembly level containing ordinary parts");
                    int nestedId = q("ComponentFeat.GetId(rigid-child)", nestedComponent::GetId);
                    intseq nestedIds = q("intseq.create(rigid-child)", intseq::create);
                    run("intseq.append(rigid-child)", () -> nestedIds.append(nestedId));
                    ComponentPath nestedPath = q("pfcAssembly.CreateComponentPath(rigid-child)", () -> pfcAssembly.CreateComponentPath(nested, nestedIds));
                    List<Object> nestedConstraints = constraintRows(nestedComponent);
                    Map<String, Object> nestedRow = Json.map("id", nestedId, "owner", modelName(nested), "model", modelName(nestedSolid),
                            "status", Creo.enumName(q("ComponentFeat.GetStatus(rigid-child)", nestedComponent::GetStatus)),
                            "placed", q("ComponentFeat.GetIsPlaced(rigid-child)", nestedComponent::GetIsPlaced),
                            "packaged", q("ComponentFeat.GetIsPackaged(rigid-child)", nestedComponent::GetIsPackaged),
                            "underconstrained", q("ComponentFeat.GetIsUnderconstrained(rigid-child)", nestedComponent::GetIsUnderconstrained),
                            "frozen", q("ComponentFeat.GetIsFrozen(rigid-child)", nestedComponent::GetIsFrozen),
                            "bulkitem", q("ComponentFeat.GetIsBulkitem(rigid-child)", nestedComponent::GetIsBulkitem),
                            "substitute", q("ComponentFeat.GetIsSubstitute(rigid-child)", nestedComponent::GetIsSubstitute),
                            "flexible", q("WComponentFeat.IsFlexible(rigid-child)", nestedW::IsFlexible),
                            "embedded", q("WComponentFeat.IsEmbedded(rigid-child)", nestedW::IsEmbedded),
                            "unplaced", q("WComponentFeat.IsUnplaced(rigid-child)", nestedW::IsUnplaced),
                            "parents", ids(q("Feature.ListParents(rigid-child)", nestedComponent::ListParents)),
                            "children", ids(q("Feature.ListChildren(rigid-child)", nestedComponent::ListChildren)),
                            "constraints", nestedConstraints,
                            "transform", frame(q("ComponentPath.GetTransform(true,rigid-child)", () -> nestedPath.GetTransform(true))),
                            "placement_metadata", metadata(nestedW, nestedConstraints.size(), nestedId));
                    requireEditable(nestedRow);
                    rigidChildren.add(nestedRow);
                }
                row.put("rigid_children", rigidChildren);
            }
            return row;
        }

        List<Object> constraintRows(ComponentFeat c) throws Exception {
            if (!(c instanceof WFeature)) throw refusal("E_VERIFY_INCOMPLETE", "constraint owner lacks supported WFeature owner access");
            Solid ownerSolid = q("WFeature.GetSolid(constraint-owner)", ((WFeature) c)::GetSolid);
            if (!(ownerSolid instanceof Assembly)) throw refusal("E_VERIFY_INCOMPLETE", "component constraint owner is not an actual assembly");
            Assembly ownerAssembly = (Assembly) ownerSolid;
            Solid componentModel = child(c);
            int componentId = q("ComponentFeat.GetId(constraint-owner)", c::GetId);
            String ownerName = q("Model.GetFileName(constraint-owner)", () -> modelName(ownerAssembly));
            try (var ownerScope = NativeReadTrace.scope("constraint_owner_model", ownerName,
                    "constraint_component_id", String.valueOf(componentId))) {
            List<Object> constraints = new ArrayList<>();
            ComponentConstraints nativeConstraints = q("ComponentFeat.GetConstraintsWithCompPath", () -> c.GetConstraintsWithCompPath(null));
            if (nativeConstraints == null) throw refusal("E_VERIFY_INCOMPLETE", "required occurrence constraints are unavailable");
            int count = q("ComponentConstraints.getarraysize", nativeConstraints::getarraysize);
            for (int i = 0; i < count; i++) {
                final int index = i;
                try (var scope = NativeReadTrace.scope("constraint_index", String.valueOf(index))) {
                    ComponentConstraint constraint = q("ComponentConstraints.get", () -> nativeConstraints.get(index));
                    String type = Creo.enumName(q("ComponentConstraint.GetType", constraint::GetType));
                    String shortType = type.replace("ASM_CONSTRAINT_", "").toLowerCase(Locale.ROOT);
                    ConstraintAttributes attrs = q("ComponentConstraint.GetAttributes", constraint::GetAttributes);
                    Map<String, Object> attributes = attrs == null ? Json.map("raw_null_default", true, "force", null, "ignore", null)
                            : Json.map("raw_null_default", false, "force", q("ConstraintAttributes.GetForce", attrs::GetForce), "ignore", q("ConstraintAttributes.GetIgnore", attrs::GetIgnore));
                    constraints.add(Json.map("type", shortType.endsWith("_off") ? shortType.substring(0, shortType.length() - 4) : shortType,
                            "native_type", type, "offset", q("ComponentConstraint.GetOffset", constraint::GetOffset), "units", "mm",
                            "assembly_reference", ref(q("ComponentConstraint.GetAssemblyReference", constraint::GetAssemblyReference), ownerAssembly, componentModel, componentId, false),
                            "component_reference", ref(q("ComponentConstraint.GetComponentReference", constraint::GetComponentReference), ownerAssembly, componentModel, componentId, true),
                            "assembly_side", Creo.enumName(q("ComponentConstraint.GetAssemblyDatumSide", constraint::GetAssemblyDatumSide)),
                            "component_side", Creo.enumName(q("ComponentConstraint.GetComponentDatumSide", constraint::GetComponentDatumSide)),
                            "attributes", attributes, "user_data", q("ComponentConstraint.GetUserDefinedData", constraint::GetUserDefinedData)));
                }
            }
            return constraints;
            }
        }

        List<Object> ids(Features features) {
            List<Object> ids = new ArrayList<>();
            if (features == null) return ids; // ListFailedFeatures and first-generation relationships allow no items.
            int count = q("Features.getarraysize(relations)", features::getarraysize);
            for (int i = 0; i < count; i++) { final int index = i; Feature f = q("Features.get(relation)", () -> features.get(index)); ids.add(q("Feature.GetId(relation)", f::GetId)); }
            return ids;
        }

        Map<String, Object> frame(Transform3D transform) {
            if (transform == null) throw refusal("E_VERIFY_INCOMPLETE", "required transform is unavailable");
            return Json.map("origin", rawPoint(q("Transform3D.GetOrigin", transform::GetOrigin)),
                    "x_axis", rawVector(q("Transform3D.GetXAxis", transform::GetXAxis)),
                    "y_axis", rawVector(q("Transform3D.GetYAxis", transform::GetYAxis)),
                    "z_axis", rawVector(q("Transform3D.GetZAxis", transform::GetZAxis)));
        }
        List<Object> rawPoint(com.ptc.pfc.pfcBase.Point3D vector) {
            List<Object> values = new ArrayList<>();
            for (int j = 0; j < 3; j++) { final int index = j; double value = q("Point3D.get", () -> vector.get(index)); if (!Double.isFinite(value)) throw refusal("E_VERIFY_INCOMPLETE", "nonfinite plane/transform coordinate"); values.add(value); }
            return values;
        }
        List<Object> rawVector(com.ptc.pfc.pfcBase.Vector3D vector) {
            List<Object> values = new ArrayList<>();
            for (int j = 0; j < 3; j++) { final int index = j; double value = q("Vector3D.get", () -> vector.get(index)); if (!Double.isFinite(value)) throw refusal("E_VERIFY_INCOMPLETE", "nonfinite plane/transform direction"); values.add(value); }
            return values;
        }

        ComponentPath path(List<Integer> values) {
            intseq ids = q("intseq.create(component-path)", intseq::create);
            for (int value : values) run("intseq.append(component-path)", () -> ids.append(value));
            return q("pfcAssembly.CreateComponentPath(direct)", () -> pfcAssembly.CreateComponentPath(asm, ids));
        }

        Map<String, Object> ref(Selection selection, Assembly owner, Solid child, int targetId, boolean componentSide) throws Exception {
            return ref(selection, owner, child, targetId, componentSide, "ComponentFeat.WFeature.GetSolid");
        }

        Map<String, Object> ref(Selection selection, Assembly owner, Solid child, int targetId,
                boolean componentSide, String ownerSource) throws Exception {
            if (selection == null) return null;
            ModelItem item = q("Selection.GetSelItem", selection::GetSelItem);
            Model model = q("Selection.GetSelModel", selection::GetSelModel);
            ComponentPath componentPath = q("Selection.GetPath", selection::GetPath);
            List<Integer> ids = new ArrayList<>();
            String rootModel = null;
            String leafModel = null;
            if (componentPath != null) {
                Assembly root = q("ComponentPath.GetRoot(constraint-reference)", componentPath::GetRoot);
                if (root == null) throw refusal("E_VERIFY_INCOMPLETE", "reference path root getter returned null");
                rootModel = q("Model.GetFileName(reference-path-root)", () -> modelName(root));
                intseq nativeIds = q("ComponentPath.GetComponentIds", componentPath::GetComponentIds);
                if (nativeIds == null) throw refusal("E_VERIFY_INCOMPLETE", "reference path IDs are unavailable");
                int count = q("intseq.getarraysize(reference-path)", nativeIds::getarraysize);
                for (int i = 0; i < count; i++) { final int index = i; ids.add(q("intseq.get(reference-path)", () -> nativeIds.get(index))); }
                if (!ids.isEmpty()) {
                    Solid leaf = q("ComponentPath.GetLeaf(constraint-reference)", componentPath::GetLeaf);
                    if (leaf == null) throw refusal("E_VERIFY_INCOMPLETE", "nonempty reference path leaf getter returned null");
                    leafModel = q("Model.GetFileName(reference-path-leaf)", () -> modelName(leaf));
                }
            }
            if (item == null || model == null) throw refusal("E_VERIFY_INCOMPLETE", "reference selected model/item is unavailable");
            String ownerName = q("Model.GetFileName(reference-owner)", () -> modelName(owner));
            String childName = q("Model.GetFileName(reference-component)", () -> modelName(child));
            String selectedModel = q("Model.GetFileName(reference-selected)", () -> modelName(model));
            boolean childIsAssembly = q("Model.GetType(reference-component)", child::GetType).getValue() == ModelType._MDL_ASSEMBLY;
            if (!referencePathAdmitted(componentSide, ownerName, childName, childIsAssembly,
                    targetId, componentPath != null, ids, rootModel, leafModel, selectedModel))
                throw refusal("E_UNSUPPORTED", "constraint selection root/leaf/path cannot be bound to this direct owner occurrence: "
                        + ownerName + " component " + targetId + " path " + Json.write(ids));
            if (!componentSide && !ids.isEmpty()) {
                // Check against the actual constraint owner, including inside a rigid subassembly.
                Feature feature = q("Assembly.GetFeatureById(reference-member)", () -> owner.GetFeatureById(ids.get(0)));
                if (!(feature instanceof ComponentFeat) || !(feature instanceof WFeature))
                    throw refusal("E_VERIFY_INCOMPLETE", "reference path does not identify an actual component feature");
                Solid featureOwner = q("WFeature.GetSolid(reference-member-owner)", ((WFeature) feature)::GetSolid);
                if (featureOwner == null || !ownerName.equals(modelName(featureOwner)))
                    throw refusal("E_VERIFY_INCOMPLETE", "reference member has the wrong actual owner");
                Solid memberModel = child((ComponentFeat) feature);
                if (!selectedModel.equals(modelName(memberModel)))
                    throw refusal("E_VERIFY_INCOMPLETE", "reference path leaf disagrees with its actual member model");
            }
            Map<String, Object> out = reference(item, model, ids);
            out.put("path_present", componentPath != null);
            out.put("path_root_model", rootModel);
            out.put("path_root_source", componentPath == null ? "Selection.GetPath.returned_null" : "ComponentPath.GetRoot");
            out.put("path_leaf_model", leafModel);
            out.put("path_leaf_source", componentPath == null ? "Selection.GetPath.returned_null"
                    : ids.isEmpty() ? "not_read_for_empty_path" : "ComponentPath.GetLeaf");
            out.put("reference_owner_model", ownerName);
            out.put("reference_owner_source", ownerSource);
            return out;
        }

        Map<String, Object> catalogReference(ModelItem item, Model model, List<Integer> componentPath) throws Exception {
            Map<String, Object> out = reference(item, model, componentPath);
            out.put("path_root_model", q("Model.GetFileName(catalog-owner)", () -> modelName(asm)));
            out.put("path_root_source", "constructed_catalog_owner");
            out.put("path_leaf_model", q("Model.GetFileName(catalog-model)", () -> modelName(model)));
            out.put("path_leaf_source", "constructed_catalog_model");
            if (!(item instanceof Surface)) throw refusal("E_UNSUPPORTED", "planar catalog item must be a surface");
            Feature feature = q("Surface.GetFeature(catalog-classification)", ((Surface) item)::GetFeature);
            if (feature == null) throw refusal("E_VERIFY_INCOMPLETE", "catalog feature classification owner is unavailable");
            boolean publicFeature = q("Feature.GetIsVisible(catalog-classification)", feature::GetIsVisible);
            out.put("classification", Json.map("public_feature", publicFeature, "source", "Feature.GetIsVisible"));
            out.put("reference_usage", publicFeature ? "editable" : "protection_only");
            @SuppressWarnings("unchecked") Map<String, Object> plane = (Map<String, Object>) out.get("plane");
            if (!publicFeature && componentPath.isEmpty() && modelName(model).equals(modelName(asm))) {
                if (!"datum_plane".equals(plane.get("kind")))
                    throw refusal("E_UNSUPPORTED", "root internal non-datum geometry is outside the bounded placement profile");
                int featureId = ((Number) plane.get("feature_id")).intValue();
                if (rootInternalSurfaces.put(featureId, (Surface) item) != null)
                    throw refusal("E_VERIFY_INCOMPLETE", "internal datum exposes more than one catalog surface");
                rootInternalEntries.put(featureId, out);
            }
            return out;
        }

        @SuppressWarnings("unchecked")
        Map<String, Object> auxiliary(Surface surface, Map<String, Object> entry) throws Exception {
            int knownFeature = ((Number) ((Map<String, Object>) entry.get("plane")).get("feature_id")).intValue();
            try (var scope = NativeReadTrace.scope("auxiliary_feature_id", String.valueOf(knownFeature), "phase", "construction_datum_read")) {
                Feature feature = q("Surface.GetFeature(auxiliary)", surface::GetFeature);
                if (!(feature instanceof WFeature)) throw refusal("E_VERIFY_INCOMPLETE", "internal datum lacks supported owner/tree access");
                int featureId = q("Feature.GetId(auxiliary)", feature::GetId);
                int surfaceId = q("Surface.GetId(auxiliary)", surface::GetId);
                Solid actualOwner = q("WFeature.GetSolid(auxiliary)", ((WFeature) feature)::GetSolid);
                if (!(actualOwner instanceof Assembly) || !modelName(asm).equals(modelName(actualOwner))
                        || featureId != knownFeature || !numberEquals(entry.get("item_id"), surfaceId))
                    throw refusal("E_VERIFY_INCOMPLETE", "construction datum model/feature/surface identity changed");
                if (q("Feature.GetIsVisible(auxiliary)", feature::GetIsVisible)
                        || q("Feature.GetFeatType(auxiliary)", feature::GetFeatType).getValue() != FeatureType._FEATTYPE_DATUM_PLANE)
                    throw refusal("E_VERIFY_INCOMPLETE", "construction datum classification is contradictory");
                String status = Creo.enumName(q("Feature.GetStatus(auxiliary)", feature::GetStatus));
                if (!"FEAT_ACTIVE".equals(status)) throw refusal("E_UNSUPPORTED", "construction datum must be active");
                List<Object> parents = ids(q("Feature.ListParents(auxiliary)", feature::ListParents));
                List<Object> children = ids(q("Feature.ListChildren(auxiliary)", feature::ListChildren));
                if (children.size() != 1 || !(children.get(0) instanceof Number))
                    throw refusal("E_UNSUPPORTED", "internal datum must have exactly one independently enumerated direct component consumer");
                int consumerId = ((Number) children.get(0)).intValue();
                ComponentFeat consumer = component(consumerId);
                Map<String, Object> consumerRow = rows.get(consumerId);
                requireEditable(consumerRow);
                Solid consumerModel = child(consumer);
                ElementTree tree = q("WFeature.GetElementTree(auxiliary)", () -> ((WFeature) feature).GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS));
                if (tree == null) throw refusal("E_VERIFY_INCOMPLETE", "construction datum tree is unavailable");
                Map<Integer, List<Element>> elements = auxiliaryIndex(q("ElementTree.ListTreeElements(auxiliary)", tree::ListTreeElements));
                Element array = auxiliaryOne(elements, wfcElemIds.PRO_E_DTMPLN_CONSTRAINTS);
                if (!q("Element.GetIsArray(auxiliary-constraints)", array::GetIsArray))
                    throw refusal("E_VERIFY_INCOMPLETE", "datum constraint array type is unreadable");
                Elements nativeConstraints = q("Element.GetChildren(auxiliary-constraints)", array::GetChildren);
                if (nativeConstraints == null || q("Elements.getarraysize(auxiliary-constraints)", nativeConstraints::getarraysize) != 1)
                    throw refusal("E_UNSUPPORTED", "only a complete single-offset internal datum is admitted");
                Element constraint = q("Elements.get(auxiliary-constraint-0)", () -> nativeConstraints.get(0));
                if (q("Element.GetId(auxiliary-constraint-0)", constraint::GetId) != wfcElemIds.PRO_E_DTMPLN_CONSTRAINT
                        || !q("Element.GetIsCompound(auxiliary-constraint-0)", constraint::GetIsCompound))
                    throw refusal("E_VERIFY_INCOMPLETE", "datum constraint array entry is invalid");
                Map<Integer, List<Element>> values = auxiliaryIndex(q("Element.GetChildren(auxiliary-constraint-0)", constraint::GetChildren));
                List<Object> indexedPath = List.of(Json.map("element_id", wfcElemIds.PRO_E_DTMPLN_CONSTRAINTS), Json.map("array_index", 0));
                int type = auxiliaryInteger(values, wfcElemIds.PRO_E_DTMPLN_CONSTR_TYPE, "PRO_E_DTMPLN_CONSTR_TYPE", indexedPath);
                if (type != Ptc.PRO_DTMPLN_OFFS) throw refusal("E_UNSUPPORTED", "internal datum constraint must be an actual planar offset");
                Selection referenceSelection = auxiliarySelection(values, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF, indexedPath);
                Map<String, Object> reference = ref(referenceSelection, (Assembly) actualOwner, consumerModel, consumerId, false,
                        "DatumFeature.WFeature.GetSolid");
                if (!"ITEM_SURFACE".equals(reference.get("item_type")) || !(reference.get("plane") instanceof Map<?, ?>))
                    throw refusal("E_UNSUPPORTED", "internal offset must reference a readable planar surface");
                double offset = auxiliaryDouble(values, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET, "PRO_E_DTMPLN_CONSTR_REF_OFFSET", indexedPath);
                int flip = auxiliaryInteger(elements, wfcElemIds.PRO_E_DTMPLN_FLIP_DIR, "PRO_E_DTMPLN_FLIP_DIR", List.of());
                if (flip != Ptc.PRO_DTMPLN_FLIP_DIR_NO && flip != Ptc.PRO_DTMPLN_FLIP_DIR_YES)
                    throw refusal("E_UNSUPPORTED", "internal datum flip is not independently known");
                Element fitGroup = auxiliaryOne(elements, wfcElemIds.PRO_E_DTMPLN_FIT);
                if (!q("Element.GetIsCompound(auxiliary-fit)", fitGroup::GetIsCompound))
                    throw refusal("E_VERIFY_INCOMPLETE", "datum fit mode group is unreadable");
                Map<Integer, List<Element>> fitValues = auxiliaryIndex(q("Element.GetChildren(auxiliary-fit)", fitGroup::GetChildren));
                int fit = auxiliaryInteger(fitValues, wfcElemIds.PRO_E_DTMPLN_FIT_TYPE, "PRO_E_DTMPLN_FIT_TYPE", List.of(Json.map("element_id", wfcElemIds.PRO_E_DTMPLN_FIT)));
                if (fit != Ptc.PRO_DTMPLN_FIT_DEFAULT)
                    throw refusal("E_UNSUPPORTED", "only an explicitly read default fit mode is admitted; outline fit remains unsupported");
                Set<Integer> knownConstraintIds = Set.of(wfcElemIds.PRO_E_DTMPLN_CONSTR_TYPE, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF,
                        wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_ANGLE,
                        wfcElemIds.PRO_E_DTMPLN_SEC_IND, wfcElemIds.PRO_E_DTMPLN_OFF_CSYS, wfcElemIds.PRO_E_DTMPLN_OFF_CSYS_OFFSET);
                if (!knownConstraintIds.containsAll(values.keySet()) || !Set.of(wfcElemIds.PRO_E_DTMPLN_FIT_TYPE,
                        wfcElemIds.PRO_E_DTMPLN_FIT_REF, wfcElemIds.PRO_E_DTMPLN_FIT_DTM_RAD, wfcElemIds.PRO_E_DTMPLN_FIT_OUTLINE).containsAll(fitValues.keySet()))
                    throw refusal("E_UNSUPPORTED", "internal datum has additional unclassified definition fields");
                int matched = uniqueAuxiliaryConstraint((List<?>) consumerRow.get("constraints"), reference, offset);
                if (matched < 0) throw refusal("E_VERIFY_INCOMPLETE", "construction datum cannot be uniquely associated with one actual consumer constraint");
                List<?> referencePath = (List<?>) reference.get("component_path");
                Map<String, Object> referencePlane = (Map<String, Object>) reference.get("plane");
                int expectedParent = referencePath.isEmpty() ? ((Number) referencePlane.get("feature_id")).intValue()
                        : ((Number) referencePath.get(0)).intValue();
                if (parents.size() != 1 || !numberEquals(parents.get(0), expectedParent))
                    throw refusal("E_VERIFY_INCOMPLETE", "construction datum parents disagree with its complete reference definition");
                Map<String, Object> referenceTransform = referencePath.isEmpty() ? null
                        : (Map<String, Object>) rows.get(((Number) referencePath.get(0)).intValue()).get("component_path_transform");
                Map<String, Object> actualPlane = (Map<String, Object>) entry.get("plane");
                if (!auxiliaryPlaneEquation(actualPlane, reference, offset, flip, referenceTransform))
                    throw refusal("E_VERIFY_INCOMPLETE", "construction datum actual frame/plane equation disagrees with its native offset definition");
                Map<String, Object> fitRecord = Json.map("type_raw", fit, "mode", "default",
                        "reference_applicability", "not_applicable", "radius_applicability", "not_applicable",
                        "outline_applicability", "not_applicable", "outline_value_read", false,
                        "not_checked", List.of("datum_display_outline"),
                        "element_presence", Json.map("reference", fitValues.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_REF),
                                "radius", fitValues.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_DTM_RAD), "outline", fitValues.containsKey(wfcElemIds.PRO_E_DTMPLN_FIT_OUTLINE)),
                        "source", "actual PRO_E_DTMPLN_FIT_TYPE; ProDtmPln.h conditional applicability; outline pointer not read");
                Map<String, Object> definition = Json.map("constraint_count", 1, "array_read_complete", true,
                        "constraints", List.of(Json.map("index", 0, "indexed_path", indexedPath,
                                "element_paths", Json.map("type", auxiliaryPath(indexedPath, wfcElemIds.PRO_E_DTMPLN_CONSTR_TYPE),
                                        "reference", auxiliaryPath(indexedPath, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF),
                                        "offset", auxiliaryPath(indexedPath, wfcElemIds.PRO_E_DTMPLN_CONSTR_REF_OFFSET)),
                                "type_raw", type, "reference", reference, "offset_raw", offset, "units", "mm")),
                        "flip_raw", flip, "fit", fitRecord,
                        "unread_inapplicable_elements", List.of("angle for OFFSET", "section index for OFFSET", "csys offsets for surface reference"),
                        "source", "WFeature.GetElementTree; complete indexed PRO_E_DTMPLN_CONSTRAINTS.GetChildren");
                return Json.map("owner_model", modelName(actualOwner), "feature_id", featureId, "surface_id", surfaceId,
                        "status", status, "parents", parents, "children", children, "definition", definition,
                        "consumer_occurrence_id", consumerId, "matched_constraint_index", matched,
                        "link_basis", "internal_visibility_single_consumer_unique_offset_definition",
                        "driver_crosscheck", Json.map("status", "not_checked"),
                        "native_plane_equation_check", Json.map("passed", true, "residual_tolerance_mm", 1e-7,
                                "full_frame_protection", "requires_frozen_before_after_comparison"));
            }
        }

        Map<Integer, List<Element>> auxiliaryIndex(Elements values) {
            if (values == null) throw refusal("E_VERIFY_INCOMPLETE", "required auxiliary element sequence is unavailable");
            int count = q("Elements.getarraysize(auxiliary-index)", values::getarraysize);
            if (count > 4096) throw refusal("E_UNSUPPORTED", "auxiliary element sequence exceeds bounded reader scope");
            Map<Integer, List<Element>> result = new LinkedHashMap<>();
            for (int i = 0; i < count; i++) {
                final int index = i;
                try (var scope = NativeReadTrace.scope("auxiliary_array_index", String.valueOf(index))) {
                    Element element = q("Elements.get(auxiliary-index)", () -> values.get(index));
                    int id = q("Element.GetId(auxiliary-index)", element::GetId);
                    result.computeIfAbsent(id, ignored -> new ArrayList<>()).add(element);
                }
            }
            return result;
        }
        Element auxiliaryOne(Map<Integer, List<Element>> values, int id) {
            List<Element> found = values.get(id);
            if (found == null || found.size() != 1) throw refusal("E_VERIFY_INCOMPLETE", "missing or repeated required auxiliary element " + id);
            return found.get(0);
        }
        List<Object> auxiliaryPath(List<Object> prefix, int id) {
            List<Object> path = new ArrayList<>(prefix); path.add(Json.map("element_id", id)); return path;
        }
        int auxiliaryInteger(Map<Integer, List<Element>> values, int id, String name, List<Object> prefix) {
            Element element = auxiliaryOne(values, id);
            try (var scope = NativeReadTrace.scope("auxiliary_element_name", name, "auxiliary_element_id", String.valueOf(id),
                    "auxiliary_indexed_path", Json.write(auxiliaryPath(prefix, id)))) {
                var value = q("Element.GetValue(auxiliary-integer)", element::GetValue);
                if (value == null || !"ARG_V_INTEGER".equals(Creo.enumName(q("ArgValue.Getdiscr(auxiliary-integer)", value::Getdiscr))))
                    throw refusal("E_VERIFY_INCOMPLETE", "auxiliary integer is unavailable: " + name);
                return q("ArgValue.GetIntValue(auxiliary)", value::GetIntValue);
            }
        }
        double auxiliaryDouble(Map<Integer, List<Element>> values, int id, String name, List<Object> prefix) {
            Element element = auxiliaryOne(values, id);
            try (var scope = NativeReadTrace.scope("auxiliary_element_name", name, "auxiliary_element_id", String.valueOf(id),
                    "auxiliary_indexed_path", Json.write(auxiliaryPath(prefix, id)))) {
                var value = q("Element.GetValue(auxiliary-double)", element::GetValue);
                if (value == null || !"ARG_V_DOUBLE".equals(Creo.enumName(q("ArgValue.Getdiscr(auxiliary-double)", value::Getdiscr))))
                    throw refusal("E_VERIFY_INCOMPLETE", "auxiliary double is unavailable: " + name);
                double number = q("ArgValue.GetDoubleValue(auxiliary)", value::GetDoubleValue);
                if (!Double.isFinite(number)) throw refusal("E_VERIFY_INCOMPLETE", "auxiliary double is not finite: " + name);
                return number;
            }
        }
        Selection auxiliarySelection(Map<Integer, List<Element>> values, int id, List<Object> prefix) {
            Element element = auxiliaryOne(values, id);
            try (var scope = NativeReadTrace.scope("auxiliary_element_name", "PRO_E_DTMPLN_CONSTR_REF", "auxiliary_element_id", String.valueOf(id),
                    "auxiliary_indexed_path", Json.write(auxiliaryPath(prefix, id)))) {
                var value = q("Element.GetValue(auxiliary-reference)", element::GetValue);
                if (value == null || !"ARG_V_SELECTION".equals(Creo.enumName(q("ArgValue.Getdiscr(auxiliary-reference)", value::Getdiscr))))
                    throw refusal("E_VERIFY_INCOMPLETE", "auxiliary reference selection is unavailable");
                Selection selected = q("ArgValue.GetSelectionValue(auxiliary)", value::GetSelectionValue);
                if (selected == null) throw refusal("E_VERIFY_INCOMPLETE", "auxiliary reference getter returned null");
                return selected;
            }
        }

        Map<String, Object> reference(ModelItem item, Model model, List<Integer> componentPath) throws Exception {
            Map<String, Object> out = Json.map("model", modelName(model), "item_id", q("ModelItem.GetId(reference)", item::GetId),
                    "item_type", Creo.enumName(q("ModelItem.GetType(reference)", item::GetType)), "component_path", componentPath,
                    "ref", q("Geometry.ref(reference)", () -> Geometry.ref(item)));
            if (item instanceof Surface) {
                Map<String, Object> plane = plane((Surface) item);
                if (!modelName(model).equals(plane.get("feature_owner")))
                    throw refusal("E_VERIFY_INCOMPLETE", "reference surface feature owner differs from its selected model");
                out.put("plane", plane);
            }
            else out.put("plane", null);
            return out;
        }

        Map<String, Object> plane(Surface surface) throws Exception {
            if (q("Surface.GetSurfaceType", surface::GetSurfaceType).getValue() != SurfaceType._SURFACE_PLANE
                    || !(surface instanceof TransformedSurface)) throw refusal("E_UNSUPPORTED", "constraint references must be readable planar surfaces/datums");
            Feature feature = q("Surface.GetFeature", surface::GetFeature);
            if (feature == null) throw refusal("E_VERIFY_INCOMPLETE", "plane feature owner is unavailable");
            if (!(feature instanceof WFeature)) throw refusal("E_VERIFY_INCOMPLETE", "plane feature lacks the supported owner-solid interface");
            Solid featureOwner = q("WFeature.GetSolid(plane-owner)", ((WFeature) feature)::GetSolid);
            if (featureOwner == null) throw refusal("E_VERIFY_INCOMPLETE", "plane feature's actual model owner is unavailable");
            boolean datum = q("Feature.GetFeatType(plane)", feature::GetFeatType).getValue() == FeatureType._FEATTYPE_DATUM_PLANE;
            Transform3D transform = q("TransformedSurface.GetCoordSys", ((TransformedSurface) surface)::GetCoordSys);
            Map<String, Object> frame = frame(transform);
            Object normal = frame.get("z_axis");
            String orientation = null;
            if (!datum) {
                SurfaceOrientation nativeOrientation = q("Surface.GetOrientation", surface::GetOrientation);
                orientation = Creo.enumName(nativeOrientation);
                if (nativeOrientation == null || (nativeOrientation.getValue() != SurfaceOrientation._SURFACEORIENT_INWARD
                        && nativeOrientation.getValue() != SurfaceOrientation._SURFACEORIENT_OUTWARD))
                    throw refusal("E_VERIFY_INCOMPLETE", "physical plane orientation is unavailable");
                if (nativeOrientation.getValue() == SurfaceOrientation._SURFACEORIENT_INWARD) {
                    @SuppressWarnings("unchecked") List<Object> raw = (List<Object>) normal;
                    List<Object> flipped = new ArrayList<>(); for (Object value : raw) flipped.add(-((Number) value).doubleValue()); normal = flipped;
                }
            }
            return Json.map("kind", datum ? "datum_plane" : "physical_plane", "feature_id", q("Feature.GetId(plane)", feature::GetId),
                    "feature_owner", modelName(featureOwner),
                    "feature_name", q("Feature.GetName(plane)", feature::GetName), "origin", frame.get("origin"), "normal", normal,
                    "frame", frame, "orientation", orientation, "units", "mm",
                    "source", "TransformedSurface.GetCoordSys; physical Surface.GetOrientation; datum primary frame");
        }

        void addCatalog(Solid solid, List<Integer> occurrencePath) throws Exception {
            Set<Integer> seen = new HashSet<>();
            List<Surface> physical = q("Creo.surfaces(reference-catalog)", () -> Creo.surfaces(solid));
            for (Surface surface : physical) {
                if (q("Surface.GetSurfaceType(catalog)", surface::GetSurfaceType).getValue() == SurfaceType._SURFACE_PLANE) {
                    Feature feature = q("Surface.GetFeature(catalog-owner)", surface::GetFeature);
                    if (!(feature instanceof WFeature)) throw refusal("E_VERIFY_INCOMPLETE", "catalog plane lacks supported owner access");
                    Solid actualOwner = q("WFeature.GetSolid(catalog-owner)", ((WFeature) feature)::GetSolid);
                    if (actualOwner == null) throw refusal("E_VERIFY_INCOMPLETE", "catalog plane owner is unavailable");
                    if (!modelName(solid).equals(modelName(actualOwner))) continue; // Aggregated assembly members require their actual occurrence path.
                    catalog.add(catalogReference(surface, solid, occurrencePath)); seen.add(q("Surface.GetId(catalog)", surface::GetId));
                }
            }
            Features datums = q("Solid.ListFeaturesByType(datums-catalog)", () -> solid.ListFeaturesByType(Boolean.FALSE, FeatureType.FEATTYPE_DATUM_PLANE));
            for (int i = 0; datums != null && i < datums.getarraysize(); i++) {
                Feature feature = datums.get(i); held.add(feature);
                if (!"FEAT_ACTIVE".equals(Creo.enumName(q("Feature.GetStatus(datum)", feature::GetStatus)))) continue;
                ModelItems items = q("Feature.ListSubItems(datum-surfaces)", () -> feature.ListSubItems(ModelItemType.ITEM_SURFACE));
                if (items == null || items.getarraysize() != 1) throw refusal("E_VERIFY_INCOMPLETE", "datum does not expose exactly one surface");
                Surface surface = (Surface) items.get(0); held.add(surface);
                if (seen.add(q("Surface.GetId(datum)", surface::GetId))) catalog.add(catalogReference(surface, solid, occurrencePath));
            }
        }

        Selection select(Map<String, Object> input, Solid local, int targetId) throws Exception {
            int id = Json.integer(input, "item_id");
            if (!"ITEM_SURFACE".equals(Json.string(input, "item_type"))) throw refusal("E_UNSUPPORTED", "only planar surface selections are supported");
            Object raw = input.get("component_path");
            if (!(raw instanceof List<?>)) throw refusal("E_VALIDATION", "reference component_path must be explicit");
            List<Integer> ids = new ArrayList<>();
            for (Object value : (List<?>) raw) {
                if (!(value instanceof Number) || ((Number) value).doubleValue() != ((Number) value).intValue())
                    throw refusal("E_VALIDATION", "reference path IDs must be integers");
                ids.add(((Number) value).intValue());
            }
            Solid solid;
            ComponentPath nativePath;
            if (local != null) {
                if (!ids.isEmpty()) throw refusal("E_UNSUPPORTED", "component reference uses its own model with an empty local path");
                solid = local; nativePath = null;
            } else if (ids.isEmpty()) { solid = asm; nativePath = path(ids); }
            else if (ids.size() == 1 && ids.get(0) != targetId) { solid = child(component(ids.get(0))); nativePath = path(ids); }
            else throw refusal("E_UNSUPPORTED", "assembly reference must be owner-local or one other direct occurrence");
            if (!modelName(solid).equals(Json.string(input, "model").toLowerCase(Locale.ROOT)))
                throw refusal("E_CONFLICT", "reference model does not match its occurrence owner");
            List<Integer> catalogPath = local == null ? ids : List.of(targetId);
            boolean catalogued = false;
            for (Object rawEntry : catalog) {
                @SuppressWarnings("unchecked") Map<String, Object> entry = (Map<String, Object>) rawEntry;
                if (modelName(solid).equals(entry.get("model")) && numberEquals(entry.get("item_id"), id)
                        && "ITEM_SURFACE".equals(entry.get("item_type")) && same(entry.get("component_path"), catalogPath)) {
                    if (!"editable".equals(entry.get("reference_usage")))
                        throw refusal("E_UNSUPPORTED", "internal construction references are protection-only and cannot be selected for a new constraint");
                    catalogued = true; break;
                }
            }
            if (!catalogued) throw refusal("E_CONFLICT", "reference is not an active physical plane/datum in the freshly observed occurrence catalog");
            ModelItem item = q("Model.GetItemById(constraint-input)", () -> solid.GetItemById(ModelItemType.ITEM_SURFACE, id));
            if (!(item instanceof Surface)) throw refusal("E_NOT_FOUND", "reference surface is unavailable");
            plane((Surface) item); // Validate true surface kind and complete frame before any model setter.
            return q("pfcSelect.CreateModelItemSelection(constraint-input)", () -> pfcSelect.CreateModelItemSelection(item, nativePath));
        }

        DatumSide side(Selection selection, String value) throws Exception {
            Surface surface = (Surface) q("Selection.GetSelItem(side)", selection::GetSelItem);
            Map<String, Object> plane = plane(surface);
            if ("physical_plane".equals(plane.get("kind"))) {
                if (!"DATUM_SIDE_NONE".equals(value)) throw refusal("E_UNSUPPORTED", "datum side is inapplicable to a physical plane; specify DATUM_SIDE_NONE");
                return DatumSide.DATUM_SIDE_NONE;
            }
            if ("DATUM_SIDE_YELLOW".equals(value)) return DatumSide.DATUM_SIDE_YELLOW;
            if ("DATUM_SIDE_RED".equals(value)) return DatumSide.DATUM_SIDE_RED;
            throw refusal("E_UNSUPPORTED", "datum reference requires explicit DATUM_SIDE_YELLOW or DATUM_SIDE_RED");
        }

        private record MetaElement(Element element, int id, int level, String name, int index) { }

        Map<String, Object> metadata(WFeature feature, int nativeConstraintCount, int featureId) throws Exception {
            try (var subject = NativeReadTrace.scope("metadata_feature_id", String.valueOf(featureId))) {
            ElementTree tree = q("WFeature.GetElementTree(component-metadata)", () -> feature.GetElementTree(null, FeatureElemTreeExtractOptions.FEAT_EXTRACT_NO_OPTS));
            if (tree == null) throw refusal("E_VERIFY_INCOMPLETE", "component placement element tree is unavailable");
            Elements elements = q("ElementTree.ListTreeElements(component-metadata)", tree::ListTreeElements);
            if (elements == null) throw refusal("E_VERIFY_INCOMPLETE", "component placement elements are unavailable");
            Map<String, Object> roots = new LinkedHashMap<>();
            List<Object> attrs = new ArrayList<>();
            List<Object> setIds = new ArrayList<>();
            List<Object> inventory = new ArrayList<>();
            List<MetaElement> flat = new ArrayList<>();
            int constraintArrayCount = 0;
            int elementCount = q("Elements.getarraysize(placement)", elements::getarraysize);
            for (int i = 0; i < elementCount; i++) {
                final int index = i;
                try (var scope = NativeReadTrace.scope("metadata_flat_index", String.valueOf(index))) {
                    Element element = q("Elements.get(placement)", () -> elements.get(index));
                    int id = q("Element.GetId(placement)", element::GetId);
                    NativeReadTrace.known("metadata_element_id", id);
                    String name = elementName(id, element);
                    NativeReadTrace.known("metadata_element_name", name);
                    int level = q("Element.GetLevel(placement)", element::GetLevel);
                    if (level < 0) throw refusal("E_VERIFY_INCOMPLETE", "negative element-tree level");
                    inventory.add(Json.map("index", index, "id", id, "name", name, "level", level));
                    flat.add(new MetaElement(element, id, level, name, index));
                }
            }
            for (MetaElement node : flat) {
                String name = node.name();
                if ("PRO_E_COMPONENT_CONSTRAINTS".equals(name)) {
                    constraintArrayCount++;
                    if (flatChildren(node, flat).size() != nativeConstraintCount)
                        throw refusal("E_VERIFY_INCOMPLETE", "element-tree constraint array count disagrees with the independent native constraint sequence");
                }
                if (List.of("PRO_E_COMPONENT_SETS", "PRO_E_COMP_PLACE_INTERFACE", "PRO_E_COMPONENT_CONSTR_ATTR",
                        "PRO_E_COMPONENT_CONSTR_SET_ID", "PRO_E_COMPONENT_MISC_ATTR", "PRO_E_COMPONENT_MOVEMENTS").contains(name)) {
                    Object value = element(node, List.of(node.index()), flat);
                    if ("PRO_E_COMPONENT_CONSTR_ATTR".equals(name)) attrs.add(value);
                    else if ("PRO_E_COMPONENT_CONSTR_SET_ID".equals(name)) setIds.add(value);
                    else if (roots.put(name, value) != null) throw refusal("E_VERIFY_INCOMPLETE", "duplicate placement metadata root");
                }
            }
            if (constraintArrayCount != 1) throw refusal("E_VERIFY_INCOMPLETE", "complete component constraint array identity is unavailable in the element-tree inventory");
            boolean supported = metadataSupported(roots, attrs, setIds, nativeConstraintCount);
            return Json.map("supported", supported, "roots", roots, "raw_constraint_attrs", attrs,
                    "constraint_set_ids", setIds, "native_constraint_count", nativeConstraintCount, "element_inventory", inventory,
                    "admission_basis", "explicit empty sets/movements; every native constraint has raw set index -1 and attr 0; complete no-interface references; raw -1 interface type is the bounded B011/B012 unassigned shape, not PRO_ASM_INTFC_NONE",
                    "source", "WFeature element-tree indexed children; ProAsmcomp.h sets/interface/attributes");
            }
        }

        String elementName(int id, Element element) {
            // Installed public wfcElemIds symbols, not string-name guesses or private integer IDs.
            if (id == wfcElemIds.PRO_E_COMPONENT_SETS) return "PRO_E_COMPONENT_SETS";
            if (id == wfcElemIds.PRO_E_COMPONENT_CONSTRAINTS) return "PRO_E_COMPONENT_CONSTRAINTS";
            if (id == wfcElemIds.PRO_E_COMPONENT_CONSTR_ATTR) return "PRO_E_COMPONENT_CONSTR_ATTR";
            if (id == wfcElemIds.PRO_E_COMPONENT_MISC_ATTR) return "PRO_E_COMPONENT_MISC_ATTR";
            if (id == wfcElemIds.PRO_E_COMPONENT_MOVEMENTS) return "PRO_E_COMPONENT_MOVEMENTS";
            if (id == wfcElemIds.PRO_E_COMP_PLACE_INTERFACE) return "PRO_E_COMP_PLACE_INTERFACE";
            if (id == wfcElemIds.PRO_E_COMP_PLACE_INTERFACE_TYPE) return "PRO_E_COMP_PLACE_INTERFACE_TYPE";
            if (id == wfcElemIds.PRO_E_COMP_PLACE_INTERFACE_COMP) return "PRO_E_COMP_PLACE_INTERFACE_COMP";
            if (id == wfcElemIds.PRO_E_COMP_PLACE_INTERFACE_ASSEMS) return "PRO_E_COMP_PLACE_INTERFACE_ASSEMS";
            if (id == wfcElemIds.PRO_E_COMPONENT_CONSTR_SET_ID) return "PRO_E_COMPONENT_CONSTR_SET_ID";
            if (id == wfcElemIds.PRO_E_COMPONENT_SET_TYPE) return "PRO_E_COMPONENT_SET_TYPE";
            if (id == wfcElemIds.PRO_E_COMPONENT_SET_ID) return "PRO_E_COMPONENT_SET_ID";
            if (id == wfcElemIds.PRO_E_COMPONENT_SET_NAME) return "PRO_E_COMPONENT_SET_NAME";
            if (id == wfcElemIds.PRO_E_COMPONENT_SET_MISC_ATTR) return "PRO_E_COMPONENT_SET_MISC_ATTR";
            if (id == wfcElemIds.PRO_E_COMPONENT_SET_FLIP) return "PRO_E_COMPONENT_SET_FLIP";
            return q("Element.GetIdAsString(metadata)", element::GetIdAsString);
        }

        List<Integer> flatChildren(MetaElement parent, List<MetaElement> flat) {
            List<Integer> children = new ArrayList<>();
            for (int i = parent.index() + 1; i < flat.size(); i++) {
                int level = flat.get(i).level();
                if (level <= parent.level()) break;
                if (level == parent.level() + 1) children.add(i);
                else if (children.isEmpty()) throw refusal("E_VERIFY_INCOMPLETE", "element-tree descendant skips its direct parent level");
            }
            return children;
        }

        Map<String, Object> element(MetaElement node, List<Integer> path, List<MetaElement> flat) throws Exception {
            Element element = node.element();
            String name = node.name();
            String getter = "not_started";
            Map<String, Object> detail = Json.map("element_id", node.id(), "element_name", name,
                    "indexed_path", path, "flat_index", node.index(), "native_level", node.level());
            try (var scope = NativeReadTrace.scope("metadata_element_id", String.valueOf(node.id()),
                    "metadata_element_name", name, "metadata_indexed_path", Json.write(path))) {
            getter = "Element.GetIsArray(metadata)";
            boolean array = q(getter, element::GetIsArray);
            detail.put("is_array", array);
            getter = "Element.GetIsCompound(metadata)";
            boolean compound = q(getter, element::GetIsCompound);
            detail.put("is_compound", compound);
            getter = "Element.GetIsMultival(metadata)";
            boolean multival = q(getter, element::GetIsMultival);
            detail.put("is_multivalue", multival);
            Map<String, Object> row = Json.map("id", node.id(), "name", name, "path", path,
                    "flat_index", node.index(), "array", array, "compound", compound, "multivalue", multival);
            if (array || compound) {
                List<Integer> expected = flatChildren(node, flat);
                getter = "Element.GetChildren(metadata)";
                Elements children = q(getter, element::GetChildren);
                List<Object> values = new ArrayList<>();
                int count = 0;
                if (children != null) {
                    getter = "Elements.getarraysize(metadata-children)";
                    count = q(getter, children::getarraysize);
                }
                // Optional null is not guessed empty: the full independent flat inventory must also contain no children.
                if (count != expected.size()) throw refusal("E_VERIFY_INCOMPLETE", "metadata child array disagrees with the complete element inventory");
                for (int i = 0; i < count; i++) {
                    final int index = i;
                    List<Integer> childPath = new ArrayList<>(path); childPath.add(index);
                    MetaElement expectedChild = flat.get(expected.get(index));
                    try (var childScope = NativeReadTrace.scope("metadata_element_id", String.valueOf(expectedChild.id()),
                            "metadata_element_name", expectedChild.name(), "metadata_indexed_path", Json.write(childPath))) {
                        getter = "Elements.get(metadata-child)";
                        Element child = q(getter, () -> children.get(index));
                        getter = "Element.GetId(metadata-child)";
                        int childId = q(getter, child::GetId);
                        getter = "Element.GetLevel(metadata-child)";
                        int childLevel = q(getter, child::GetLevel);
                        if (childId != expectedChild.id() || childLevel != expectedChild.level())
                            throw refusal("E_VERIFY_INCOMPLETE", "indexed child identity disagrees with the complete element inventory");
                        values.add(element(new MetaElement(child, childId, childLevel, expectedChild.name(), expectedChild.index()), childPath, flat));
                    }
                }
                row.put("children", values);
                row.put("children_read_complete", true);
                row.put("children_state", children == null ? "returned_null_optional_and_flat_inventory_empty" : "returned_array");
                row.put("flat_child_count", expected.size());
            } else if ("PRO_E_COMP_PLACE_INTERFACE_COMP".equals(name)) {
                // This is a selection field, not a scalar ArgValue. Read through the public selection accessor.
                getter = "Element.GetSelections(interface-component)";
                var selections = q(getter, element::GetSelections);
                int count = 0;
                if (selections != null) {
                    getter = "Selections.getarraysize(interface-component)";
                    count = q(getter, selections::getarraysize);
                }
                row.put("value_kind", "selection");
                row.put("selection_read_complete", true);
                row.put("selection_state", selections == null ? "returned_null_optional" : "returned_array");
                row.put("selection_count", count);
            } else {
                getter = "Element.GetValue(metadata)";
                var value = q(getter, element::GetValue);
                if (value == null) {
                    detail.put("result_category", "returned_null_required_scalar");
                    throw refusal("E_VERIFY_INCOMPLETE", "required metadata scalar returned null: " + name + " at " + Json.write(path));
                }
                // These admitted branches contain only documented scalar fields. Unexpected selections are rejected.
                getter = "ArgValue.Getdiscr(metadata)";
                String type = Creo.enumName(q(getter, value::Getdiscr));
                row.put("value_type", type);
                detail.put("value_type", type);
                if ("ARG_V_INTEGER".equals(type)) { getter = "ArgValue.GetIntValue(metadata)"; row.put("value", q(getter, value::GetIntValue)); }
                else if ("ARG_V_STRING".equals(type) || "ARG_V_WSTRING".equals(type)) { getter = "ArgValue.GetStringValue(metadata)"; row.put("value", q(getter, value::GetStringValue)); }
                else if ("ARG_V_BOOLEAN".equals(type)) { getter = "ArgValue.GetBoolValue(metadata)"; row.put("value", q(getter, value::GetBoolValue)); }
                else if ("ARG_V_DOUBLE".equals(type)) { getter = "ArgValue.GetDoubleValue(metadata)"; row.put("value", q(getter, value::GetDoubleValue)); }
                else throw refusal("E_UNSUPPORTED", "unsupported placement metadata scalar " + name + ": " + type);
                row.put("value_state", "returned_scalar");
            }
            return row;
            } catch (Throwable failure) {
                NativeReadTrace.rethrowFatal(failure);
                if (failure instanceof Failures.Stage) throw (Failures.Stage) failure;
                detail.put("getter", getter);
                detail.putIfAbsent("result_category", "threw_or_rejected");
                throw new Failures.Stage("constraint_metadata_read", failure, detail);
            }
        }
    }

    @SuppressWarnings("unchecked")
    static boolean metadataSupported(Map<String, Object> roots, List<Object> attrs, List<Object> setIds, int constraintCount) {
        if (constraintCount < 1 || attrs.size() != constraintCount || setIds.size() != constraintCount) return false;
        if (!roots.keySet().equals(Set.of("PRO_E_COMPONENT_SETS", "PRO_E_COMP_PLACE_INTERFACE",
                "PRO_E_COMPONENT_MISC_ATTR", "PRO_E_COMPONENT_MOVEMENTS"))) return false;
        for (Object raw : attrs) if (!scalarEquals((Map<String, Object>) raw, 0)) return false;
        // This is a bounded, observed unassigned index shape, not a fabricated PTC enum/default.
        for (Object raw : setIds) if (!scalarEquals((Map<String, Object>) raw, -1)) return false;
        if (!scalarEquals((Map<String, Object>) roots.get("PRO_E_COMPONENT_MISC_ATTR"), 0)
                || !explicitEmptyArray(roots.get("PRO_E_COMPONENT_SETS"))
                || !explicitEmptyArray(roots.get("PRO_E_COMPONENT_MOVEMENTS"))) return false;
        Map<String, Object> placement = (Map<String, Object>) roots.get("PRO_E_COMP_PLACE_INTERFACE");
        if (!Boolean.TRUE.equals(placement.get("compound")) || !Boolean.TRUE.equals(placement.get("children_read_complete"))
                || !(placement.get("children") instanceof List<?>)) return false;
        Map<String, Map<String, Object>> fields = new LinkedHashMap<>();
        for (Object raw : (List<?>) placement.get("children")) {
            if (!(raw instanceof Map<?, ?>)) return false;
            Map<String, Object> field = (Map<String, Object>) raw;
            String name = (String) field.get("name");
            if (name == null || fields.put(name, field) != null) return false;
        }
        if (!fields.keySet().equals(Set.of("PRO_E_COMP_PLACE_INTERFACE_TYPE", "PRO_E_COMP_PLACE_INTERFACE_COMP", "PRO_E_COMP_PLACE_INTERFACE_ASSEMS"))) return false;
        Map<String, Object> type = fields.get("PRO_E_COMP_PLACE_INTERFACE_TYPE");
        if (!scalarEquals(type, Ptc.PRO_ASM_INTFC_NONE) && !scalarEquals(type, -1)) return false;
        Map<String, Object> selected = fields.get("PRO_E_COMP_PLACE_INTERFACE_COMP");
        return "selection".equals(selected.get("value_kind")) && Boolean.TRUE.equals(selected.get("selection_read_complete"))
                && ("returned_null_optional".equals(selected.get("selection_state")) || "returned_array".equals(selected.get("selection_state")))
                && numberEquals(selected.get("selection_count"), 0)
                && explicitEmptyArray(fields.get("PRO_E_COMP_PLACE_INTERFACE_ASSEMS"));
    }

    private static boolean scalarEquals(Map<String, Object> node, int value) {
        return node != null && "returned_scalar".equals(node.get("value_state"))
                && "ARG_V_INTEGER".equals(node.get("value_type")) && numberEquals(node.get("value"), value);
    }
    @SuppressWarnings("unchecked") private static boolean explicitEmptyArray(Object raw) {
        if (!(raw instanceof Map<?, ?>)) return false;
        Map<String, Object> node = (Map<String, Object>) raw;
        return Boolean.TRUE.equals(node.get("array")) && Boolean.TRUE.equals(node.get("children_read_complete"))
                && node.get("children") instanceof List<?> && ((List<?>) node.get("children")).isEmpty()
                && numberEquals(node.get("flat_child_count"), 0)
                && ("returned_array".equals(node.get("children_state"))
                    || "returned_null_optional_and_flat_inventory_empty".equals(node.get("children_state")));
    }
    private static boolean numberEquals(Object value, int expected) { return value instanceof Number && ((Number) value).doubleValue() == expected; }
}
