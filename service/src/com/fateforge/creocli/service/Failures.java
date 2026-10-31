package com.fateforge.creocli.service;

import com.ptc.pfc.pfcExceptions.XToolkitError;

import java.util.Map;

/**
 * The two kinds of failure an operation raises on purpose, and the reduction of any
 * failure to plain data. Everything here runs on the toolkit thread: a toolkit
 * exception is itself a proxy, and reading it anywhere else is a toolkit call from the
 * wrong thread (see {@link Service.ToolkitFailure}).
 */
final class Failures {

    private Failures() {
    }

    /**
     * A problem the caller can fix, with a stable code. Every refusal is raised by a check
     * made before the operation changes anything, which is what lets the CLI record the
     * attempt as "failed before write".
     */
    static final class Refusal extends RuntimeException {
        private static final long serialVersionUID = 1L;
        final String code;

        Refusal(String code, String message) {
            super(message);
            this.code = code;
        }
    }

    /**
     * Which step of a multi-step operation failed. A bare "general error" from a redefine
     * says nothing about whether the tree, the sketch or Creo was at fault; the stage at
     * least says where to look, and {@code cleanup} what became of the half-built feature.
     */
    static final class Stage extends Exception {
        private static final long serialVersionUID = 1L;
        final String stage;
        final transient Map<String, Object> detail;
        String cleanup;

        Stage(String stage, Throwable cause) {
            this(stage, cause, null);
        }

        Stage(String stage, Throwable cause, Map<String, Object> detail) {
            super(cause);
            this.stage = stage;
            this.detail = detail;
        }
    }

    /** What went wrong, in a form the caller can act on. Must run on the toolkit thread. */
    static Map<String, Object> error(Throwable failure) {
        if (failure instanceof NativeReadTrace.Fatal
                || Boolean.TRUE.equals(NativeReadTrace.stopEvidence().get("stopped"))) {
            return NativeReadTrace.error(failure);
        }
        if (failure instanceof Stage) {
            Map<String, Object> inner = error(failure.getCause());
            inner.put("stage", ((Stage) failure).stage);
            if ("regeneration_check".equals(((Stage) failure).stage)) {
                inner.put("code", "E_VERIFY_INCOMPLETE");
                inner.put("verification", Json.map("status", "incomplete",
                        "native_check", ((Stage) failure).detail));
                return inner;
            }
            if (((Stage) failure).stage.startsWith("render") || ((Stage) failure).stage.startsWith("explode")
                    || ((Stage) failure).stage.equals("config_restore") || ((Stage) failure).stage.startsWith("model_")) {
                inner.put("native_cause_code", inner.get("code"));
                inner.put("code", "E_CREO");
            }
            if (((Stage) failure).detail != null) {
                inner.put(((Stage) failure).stage.startsWith("constraint_") ? "assembly_constraints"
                        : ((Stage) failure).stage.startsWith("render") ? "render"
                        : ((Stage) failure).stage.startsWith("model_") ? "model_state" : "sketch", ((Stage) failure).detail);
            }
            if (((Stage) failure).cleanup != null) {
                inner.put("cleanup", ((Stage) failure).cleanup);
            }
            return inner;
        }
        if (failure instanceof Service.ToolkitFailure) {
            return new java.util.LinkedHashMap<>(((Service.ToolkitFailure) failure).error);
        }
        if (failure instanceof Refusal) {
            return Json.map("code", ((Refusal) failure).code, "message", failure.getMessage());
        }
        if (failure instanceof IllegalArgumentException) {
            return Json.map("code", "E_VALIDATION", "message", failure.getMessage());
        }
        if (failure instanceof XToolkitError) {
            // Diagnostic formatting must not add native exception-detail getters to
            // the call chain that we are trying to locate.
            if (NativeReadTrace.active()) return Json.map("code", "E_CREO",
                    "message", failure.getClass().getName(), "exception_class", failure.getClass().getName(),
                    "toolkit_details", "not_read_during_native_diagnostic");
            XToolkitError toolkit = (XToolkitError) failure;
            String function = "?";
            int code = 0;
            try {
                function = toolkit.GetToolkitFunctionName();
                code = toolkit.GetErrorCode();
            } catch (Throwable ignored) {
                // Detail unavailable; the class name still says what kind of failure.
            }
            return Json.map("code", "E_CREO", "message", failure.getClass().getSimpleName()
                    + " in " + function, "toolkit_function", function, "toolkit_error", code);
        }
        if (NativeReadTrace.active()) return Json.map("code", "E_CREO", "message", failure.getClass().getName(),
                "exception_class", failure.getClass().getName(), "exception_message", "not_read_during_native_diagnostic");
        return Json.map("code", "E_CREO", "message", failure.getClass().getName()
                + (failure.getMessage() == null ? "" : ": " + failure.getMessage()));
    }
}
