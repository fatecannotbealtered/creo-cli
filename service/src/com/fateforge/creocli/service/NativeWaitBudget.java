package com.fateforge.creocli.service;

import java.util.List;
import java.util.Map;
import java.util.Set;

/** Pure Java wait policy. It changes caller patience, never native cancellation or scope. */
final class NativeWaitBudget {
    static final String PROFILE_HEADER = "X-Creo-Cli-Execution-Profile";
    static final String PROFILE = "drawing-complete-v1";
    static final String CAPABILITY = "drawing_execution_budget";
    static final int CAPABILITY_VERSION = 1;
    static final long LEGACY_MILLIS = 120_000;
    static final long DRAWING_MILLIS = 300_000;
    static final long MIN_MILLIS = 100;

    // The CLI restricts the top-level command/target. Its source/dependency and first
    // independent readback can legitimately read parts, so do not require *.drw here.
    private static final Set<String> DRAWING_OPERATIONS = Set.of(
            "session.status", "model.list", "model.management-state", "model.show",
            "dimension.list", "feature.list", "feature.show", "geometry.list",
            "geometry.mass-properties", "geometry.bounds", "parameter.list", "relation.list",
            "material.list", "family.show", "drawing.info", "drawing.resources",
            "drawing.bom-template", "drawing.activate", "drawing.create", "drawing.add-note",
            "drawing.edit-note", "drawing.add-bom", "drawing.add-balloons", "drawing.add-view",
            "drawing.move-view", "drawing.move-table", "model.save", "model.close", "model.export");

    private NativeWaitBudget() { }

    /** A definite pre-queue refusal; messages contain no supplied header values. */
    static final class Refusal extends IllegalArgumentException {
        private static final long serialVersionUID = 1L;
        Refusal(String message) { super(message); }
    }

    /** The real service diagnostic guard has priority over any malformed budget header. */
    static long milliseconds(Runnable nativeGuard, String operation, List<String> profiles,
                             List<String> waits) {
        nativeGuard.run();
        if (profiles == null) return legacy(first(waits));
        if (profiles.size() != 1 || !PROFILE.equals(profiles.get(0)))
            throw new Refusal("execution profile is absent, ambiguous or unsupported");
        if (operation == null || !DRAWING_OPERATIONS.contains(operation))
            throw new Refusal("the operation does not support the drawing execution profile");
        if (waits == null || waits.size() != 1 || waits.get(0) == null)
            throw new Refusal("the drawing execution profile requires one wait budget");
        String given = waits.get(0).trim();
        if (!given.matches("[0-9]{1,19}"))
            throw new Refusal("the drawing execution wait budget must be positive integer milliseconds");
        long value;
        try { value = Long.parseLong(given); }
        catch (NumberFormatException invalid) {
            throw new Refusal("the drawing execution wait budget is out of range");
        }
        if (value <= 0)
            throw new Refusal("the drawing execution wait budget must be positive");
        return Math.max(MIN_MILLIS, Math.min(DRAWING_MILLIS, value));
    }

    private static String first(List<String> values) {
        return values == null || values.isEmpty() ? null : values.get(0);
    }

    /** Exactly the previous default, minimum, first-header and malformed-value behavior. */
    static long legacy(String given) {
        if (given == null) return LEGACY_MILLIS;
        try { return Math.max(MIN_MILLIS, Math.min(LEGACY_MILLIS, Long.parseLong(given.trim()))); }
        catch (NumberFormatException unreadable) { return LEGACY_MILLIS; }
    }

    static Map<String, Object> refusal(Refusal failure) {
        return Map.of("code", "E_VALIDATION", "message", failure.getMessage(),
                "retryable", false, "started", false);
    }
}
