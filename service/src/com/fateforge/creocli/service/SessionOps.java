package com.fateforge.creocli.service;

import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.wfc.wfcSession.WSession;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** session.status and session.cd: the running Creo, as a whole. */
final class SessionOps {

    private SessionOps() {
    }

    /** Actual effective deployment options; called only by the one readiness /session read. */
    static Map<String, Object> deploymentPolicy() {
        Map<String, Object> result = Json.map("complete", false,
                "signed_apps", null, "unsigned_apps", null,
                "source", "BaseSession.GetConfigOption(open_protk_signed_apps/open_protk_unsigned_apps)");
        boolean complete = true;
        for (String kind : List.of("signed", "unsigned")) {
            String option = "open_protk_" + kind + "_apps";
            Map<String, Object> observation = Json.map("option", option, "status", "read_failed",
                    "raw", null, "raw_truncated", false, "exception_category", null,
                    "exception_class", null);
            result.put(kind + "_observation", observation);
            try {
                String value = NativeReadTrace.call("BaseSession.GetConfigOption(" + option + ")",
                        () -> Creo.session().GetConfigOption(option));
                observation.put("raw", value == null ? null : value.substring(0, Math.min(value.length(), 64)));
                observation.put("raw_truncated", value != null && value.length() > 64);
                String normalized = value == null ? null : value.trim().toLowerCase(java.util.Locale.ROOT);
                if (value == null || value.isEmpty()) {
                    complete = false;
                    observation.put("status", value == null ? "unsupported_null" : "unsupported_empty");
                    result.put(kind + "_reason", value == null ? "native option returned null" : "native option returned empty");
                } else if (!List.of("always", "never", "prompt").contains(normalized)) {
                    complete = false;
                    observation.put("status", "unrecognized");
                    result.put(kind + "_reason", "native option returned an unrecognized value");
                } else {
                    observation.put("status", "recognized");
                    result.put(kind + "_apps", normalized);
                }
            } catch (Throwable failure) {
                NativeReadTrace.rethrowFatal(failure);
                complete = false;
                observation.put("exception_class", failure.getClass().getName());
                if (failure instanceof com.ptc.pfc.pfcExceptions.XToolkitNotFound) {
                    observation.put("status", "unsupported_not_found");
                    observation.put("exception_category", "XToolkitNotFound");
                } else observation.put("exception_category", "other_failure");
                result.put(kind + "_reason", failure.getClass().getName());
            }
        }
        result.put("complete", complete);
        return result;
    }

    /** Fixed recovery settings, read once by authenticated startup readiness only. */
    static Map<String, Object> recoveryConfiguration() {
        String root = System.getenv("PTC_WF_ROOT");
        Map<String, Object> result = Json.map("complete", false,
                "workflow_root", root, "last_session_directory_path", null,
                "last_session_directory_path_value_count", null, "last_session_retrieval", null,
                "workflow_root_source", "Java process environment inherited from owned Creo launcher",
                "configuration_source", "BaseSession.GetConfigOptionValues(last_session_directory_path)/GetConfigOption(last_session_retrieval)");
        boolean complete = root != null && !root.isEmpty() && root.length() <= 32767;
        try {
            Map<String, Object> observed = NativeReadTrace.call("BaseSession.GetConfigOptionValues(last_session_directory_path)", () -> {
                com.ptc.cipjava.stringseq values = Creo.session().GetConfigOptionValues("last_session_directory_path");
                int count = values == null ? 0 : values.getarraysize();
                return Json.map("count", count, "value", count == 1 ? values.get(0) : null);
            });
            int count = ((Number) observed.get("count")).intValue();
            result.put("last_session_directory_path_value_count", count);
            String value = (String) observed.get("value");
            if (count != 1 || value == null || value.isEmpty() || value.length() > 260) {
                complete = false;
                result.put("last_session_directory_path_readback", "unavailable_oversized_or_not_scalar");
            } else {
                result.put("last_session_directory_path", value);
                result.put("last_session_directory_path_readback", "observed");
            }
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            complete = false;
            result.put("last_session_directory_path_readback", "failed");
            result.put("last_session_directory_path_error_class", failure.getClass().getName());
        }
        try {
            String value = NativeReadTrace.call("BaseSession.GetConfigOption(last_session_retrieval)",
                    () -> Creo.session().GetConfigOption("last_session_retrieval"));
            if (value == null || value.isEmpty() || value.length() > 80) {
                complete = false;
                result.put("last_session_retrieval_readback", "unavailable_or_oversized");
            } else {
                result.put("last_session_retrieval", value);
                result.put("last_session_retrieval_readback", "observed");
            }
        } catch (Throwable failure) {
            NativeReadTrace.rethrowFatal(failure);
            complete = false;
            result.put("last_session_retrieval_readback", "failed");
            result.put("last_session_retrieval_error_class", failure.getClass().getName());
        }
        result.put("complete", complete);
        return result;
    }

    /** Complete bounded model/window identity and modified/dependency observation; no mutation. */
    static Map<String, Object> managementState() throws Exception {
        Session session = Creo.session();
        List<Object> models = new ArrayList<>(), windows = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models all = session.ListModels();
        if (all != null && all.getarraysize() > 64)
            throw new Failures.Refusal("E_UNSUPPORTED", "native model inventory exceeds management bound");
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Model model = all.get(i);
            if (Creo.internal(model)) continue;
            List<Object> dependencies = new ArrayList<>();
            com.ptc.pfc.pfcModel.Dependencies found;
            try { found = model.ListDependencies(); }
            catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { found = null; }
            for (int j = 0; found != null && j < found.getarraysize(); j++) {
                com.ptc.pfc.pfcModel.ModelDescriptor descriptor = found.get(j).GetDepModel();
                if (descriptor == null || descriptor.GetFileName() == null)
                    throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "dependency model descriptor unavailable");
                dependencies.add(descriptor.GetFileName().toLowerCase(java.util.Locale.ROOT));
            }
            Map<String, Object> origin = Creo.originInfo(model);
            models.add(Json.map("model", Creo.fileName(model), "type", Creo.typeName(model.GetType()),
                    "origin", origin.get("value"), "origin_readback", origin,
                    "family", model instanceof com.ptc.pfc.pfcSolid.Solid ? Families.info((com.ptc.pfc.pfcSolid.Solid) model) : null,
                    "modified", model.GetIsModified(),
                    "version_stamp", model.GetVersionStamp(), "relation_id", model.GetRelationId(),
                    "dependencies", dependencies, "dependencies_complete", true));
        }
        com.ptc.pfc.pfcWindow.Windows allWindows = session.ListWindows();
        if (allWindows != null && allWindows.getarraysize() > 32)
            throw new Failures.Refusal("E_UNSUPPORTED", "window inventory exceeds management bound");
        for (int i = 0; allWindows != null && i < allWindows.getarraysize(); i++) {
            com.ptc.pfc.pfcWindow.Window window = allWindows.get(i);
            Model model;
            try { model = window.GetModel(); }
            catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { model = null; }
            windows.add(Json.map("id", String.valueOf(window.GetId()), "model", model == null ? null : Creo.fileName(model)));
        }
        com.ptc.pfc.pfcWindow.Window active;
        try { active = session.GetCurrentWindow(); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { active = null; }
        Model current;
        try { current = session.GetCurrentModel(); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound empty) { current = null; }
        return Json.map("completed", true, "models", models, "windows", windows,
                "active_window", active == null ? null : String.valueOf(active.GetId()),
                "active_model", current == null ? null : Creo.fileName(current),
                "source", "ListModels/ListWindows; native origin/version/modified/dependency getters",
                "not_checked", List.of("camera and display settings", "cross-instance object identity"));
    }

    /**
     * One reading of the session. Whether it casts to {@link WSession} decides what this
     * tool can do: {@code WSession} is where element trees are built, and element trees are
     * how features are created. The native sketch library is looked up here too, so a
     * caller can tell before it asks for a rectangle whether one can be drawn.
     */
    static Map<String, Object> status() throws Exception {
        Session session = Creo.session();
        List<Object> models = new ArrayList<>();
        com.ptc.pfc.pfcModel.Models open = session.ListModels();
        for (int i = 0; open != null && i < open.getarraysize(); i++) {
            if (!Creo.internal(open.get(i))) {
                models.add(Creo.fileName(open.get(i)));
            }
        }
        Model current = null;
        try {
            current = session.GetCurrentModel();
        } catch (Throwable none) {
            // No model is current.
        }
        boolean nativeSketch = Service.sketchLibrary() != null;
        return Json.map(
                "protocol", Service.PROTOCOL,
                "creation_api", session instanceof WSession,
                "creo_version", String.valueOf(pfcGlobal.GetProEVersion()),
                "creo_build", String.valueOf(pfcGlobal.GetProEBuildCode()),
                "working_directory", session.GetCurrentDirectory(),
                "models", models,
                "active_model", current == null ? null : Creo.fileName(current),
                "native_sketch_available", nativeSketch,
                "native_sketch_library", Service.sketchLibraryStatus());
    }

    /**
     * Where new models are written and where Creo looks for the models a model references.
     * Keeps an agent's output out of wherever Creo happened to start.
     */
    static Map<String, Object> cd(Map<String, Object> request) throws Exception {
        File target = new File(Json.string(request, "path"));
        if (!target.isDirectory()) {
            throw new Failures.Refusal("E_NOT_FOUND", target + " is not an existing directory");
        }
        Session session = Creo.session();
        session.ChangeDirectory(target.getAbsolutePath());
        return Json.map("working_directory", session.GetCurrentDirectory());
    }
}
