package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Flags scan without SDK dependencies, so getter/iteration failures can be tested offline. */
final class FeatureStatusScan {
    static final int VERSION = 2;

    interface Flag {
        int id() throws Throwable;
        default int expectedId() throws Throwable { return id(); }
        boolean failed() throws Throwable;
        boolean childOfFailed() throws Throwable;
    }

    interface Flags {
        int size() throws Throwable;
        Flag get(int index) throws Throwable;
    }

    interface Reader {
        Flags read() throws Throwable;
    }

    static final class Incomplete extends Exception {
        private static final long serialVersionUID = 1L;
        final transient Map<String, Object> record;

        Incomplete(Throwable cause, Map<String, Object> record) {
            super(cause);
            this.record = record;
        }
    }

    private FeatureStatusScan() {
    }

    static Map<String, Object> record(String model) {
        return Json.map("model", model, "source", "Solid.ListFeaturesByType/WFeature.GetStatusFlag",
                "checker_version", VERSION, "input", Json.map("model", model),
                "completed", false, "checked_feature_ids", new ArrayList<>(), "failed_features", null,
                "not_checked", java.util.Arrays.asList("design_intent", "loaded_component_identity"));
    }

    static Map<String, Object> scan(String model, Reader reader) throws Incomplete {
        List<Object> checked = new ArrayList<>();
        List<Object> failed = new ArrayList<>();
        Map<String, Object> record = record(model);
        record.put("checked_feature_ids", checked);
        try {
            Flags flags = reader.read();
            if (flags == null) {
                throw new IllegalStateException("feature status flags unavailable");
            }
            int count = flags.size();
            if (count < 0 || count > 65536) {
                throw new IllegalStateException("invalid feature status flag count");
            }
            for (int i = 0; i < count; i++) {
                Flag flag = flags.get(i);
                if (flag == null) {
                    throw new IllegalStateException("feature status flag unavailable");
                }
                int id = flag.id();
                if (id < 0 || id != flag.expectedId() || checked.contains(id)) {
                    throw new IllegalStateException("feature status identity is invalid or duplicated");
                }
                boolean isFailed = flag.failed();
                // Read both properties, even when the first is true: a failed getter is incomplete.
                boolean childOfFailed = flag.childOfFailed();
                checked.add(id);
                if (isFailed || childOfFailed) {
                    failed.add(id);
                }
            }
        } catch (Throwable failure) {
            record.put("observed_failed_features", failed);
            record.put("error_type", failure.getClass().getSimpleName());
            throw new Incomplete(failure, record);
        }
        record.put("completed", true);
        record.put("failed_features", failed);
        return record;
    }
}
