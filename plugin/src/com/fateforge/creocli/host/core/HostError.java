package com.fateforge.creocli.host.core;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A failure the host reports to the CLI (DCLI-279). Only the host error codes are allowed;
 * every error says whether the change began ({@code dispatch_state}, DCLI-275).
 */
public final class HostError extends RuntimeException {
    public static final String BUSY = "E_BUSY";
    public static final String NATIVE = "E_NATIVE_FAILURE";
    public static final String HUMAN = "E_HUMAN_REQUIRED";
    public static final String NOT_FOUND = "E_NOT_FOUND";
    public static final String VALIDATION = "E_VALIDATION";
    public static final String UNSUPPORTED = "E_UNSUPPORTED";

    public final String code;
    public final String dispatchState;
    public final Map<String, Object> extra = new LinkedHashMap<>();

    public HostError(String code, String message) {
        this(code, message, "not_started");
    }

    public HostError(String code, String message, String dispatchState) {
        super(message);
        this.code = code;
        this.dispatchState = dispatchState;
    }

    /** The application's own words; the CLI marks them untrusted (DSEC-020). */
    public HostError nativeMessage(String text) {
        if (text != null && !text.isEmpty()) {
            extra.put("native_message", text);
        }
        return this;
    }

    public HostError with(String key, Object value) {
        extra.put(key, value);
        return this;
    }

    public static HostError busy(String message, long retryAfterMs) {
        return new HostError(BUSY, message).with("retry_after_ms", retryAfterMs);
    }

    public Map<String, Object> data() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("code", code);
        out.put("dispatch_state", dispatchState);
        out.putAll(extra);
        return out;
    }
}
