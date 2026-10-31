package com.fateforge.creocli.service;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/** CPU-only getter fault tests. No PTC SDK, native library or Creo session is loaded. */
public final class FeatureStatusScanTest {
    private static int cases;

    private static void equal(Object actual, Object expected) {
        if (!java.util.Objects.equals(actual, expected)) {
            throw new AssertionError("expected " + expected + ", observed " + actual);
        }
    }

    private static FeatureStatusScan.Flag flag(int id, boolean failed, boolean child, boolean throwChild) {
        return new FeatureStatusScan.Flag() {
            public int id() { return id; }
            public boolean failed() { return failed; }
            public boolean childOfFailed() {
                if (throwChild) { throw new IllegalStateException("child getter failed"); }
                return child;
            }
        };
    }

    private static FeatureStatusScan.Flags flags(FeatureStatusScan.Flag... items) {
        return new FeatureStatusScan.Flags() {
            public int size() { return items.length; }
            public FeatureStatusScan.Flag get(int index) { return items[index]; }
        };
    }

    private static void incomplete(FeatureStatusScan.Reader reader, List<?> checked, List<?> observedFailed) throws Exception {
        try {
            FeatureStatusScan.scan("block.prt", reader);
            throw new AssertionError("unavailable scan was accepted as complete");
        } catch (FeatureStatusScan.Incomplete failure) {
            Map<String, Object> record = failure.record;
            equal(record.get("model"), "block.prt");
            equal(record.get("input"), Json.map("model", "block.prt"));
            equal(record.get("checker_version"), FeatureStatusScan.VERSION);
            equal(record.get("source"), "Solid.ListFeaturesByType/WFeature.GetStatusFlag");
            equal(record.get("completed"), false);
            equal(record.get("failed_features"), null);
            equal(record.get("checked_feature_ids"), checked);
            equal(record.get("observed_failed_features"), observedFailed);
            if (record.get("error_type") == null) { throw new AssertionError("missing error"); }
            cases++;
        }
    }

    public static void main(String[] args) throws Exception {
        Map<String, Object> empty = FeatureStatusScan.scan("block.prt", () -> flags());
        equal(empty.get("completed"), true);
        equal(empty.get("input"), Json.map("model", "block.prt"));
        equal(empty.get("checker_version"), FeatureStatusScan.VERSION);
        equal(empty.get("failed_features"), Collections.emptyList());
        cases++;

        Map<String, Object> healthy = FeatureStatusScan.scan("block.prt", () -> flags(
                flag(11, false, false, false), flag(12, false, false, false)));
        equal(healthy.get("checked_feature_ids"), Arrays.asList(11, 12));
        equal(healthy.get("failed_features"), Collections.emptyList());
        cases++;

        Map<String, Object> failed = FeatureStatusScan.scan("block.prt", () -> flags(
                flag(11, true, false, false), flag(12, false, true, false)));
        equal(failed.get("completed"), true);
        equal(failed.get("failed_features"), Arrays.asList(11, 12));
        cases++;

        Map<String, Object> embedded = FeatureStatusScan.scan("block.prt", () -> flags(
                flag(40, false, false, false), flag(41, true, false, false)));
        equal(embedded.get("checked_feature_ids"), Arrays.asList(40, 41));
        equal(embedded.get("failed_features"), Arrays.asList(41));
        cases++;
        incomplete(() -> flags(flag(40, false, false, false), flag(40, false, false, false)),
                Arrays.asList(40), Collections.emptyList());
        incomplete(() -> flags(flag(-1, false, false, false)), Collections.emptyList(), Collections.emptyList());
        incomplete(() -> flags(new FeatureStatusScan.Flag() {
            public int id() { return 41; }
            public int expectedId() { return 40; }
            public boolean failed() { return false; }
            public boolean childOfFailed() { return false; }
        }), Collections.emptyList(), Collections.emptyList());

        incomplete(() -> { throw new IllegalStateException("getter failed"); }, Collections.emptyList(), Collections.emptyList());
        incomplete(() -> null, Collections.emptyList(), Collections.emptyList());
        incomplete(() -> flags((FeatureStatusScan.Flag) null), Collections.emptyList(), Collections.emptyList());
        incomplete(() -> flags(flag(11, true, false, true)), Collections.emptyList(), Collections.emptyList());
        incomplete(() -> new FeatureStatusScan.Flags() {
            public int size() { return -1; }
            public FeatureStatusScan.Flag get(int index) { throw new AssertionError("must not run"); }
        }, Collections.emptyList(), Collections.emptyList());
        incomplete(() -> new FeatureStatusScan.Flags() {
            public int size() { throw new IllegalStateException("size getter failed"); }
            public FeatureStatusScan.Flag get(int index) { throw new AssertionError("must not run"); }
        }, Collections.emptyList(), Collections.emptyList());
        incomplete(() -> new FeatureStatusScan.Flags() {
            public int size() { return 2; }
            public FeatureStatusScan.Flag get(int index) {
                if (index == 1) { throw new IllegalStateException("iteration failed after first flag"); }
                return flag(11, true, false, false);
            }
        }, Arrays.asList(11), Arrays.asList(11));
        incomplete(() -> flags(new FeatureStatusScan.Flag() {
            public int id() { return 11; }
            public boolean failed() { throw new IllegalStateException("failure flag getter failed"); }
            public boolean childOfFailed() { return false; }
        }), Collections.emptyList(), Collections.emptyList());
        incomplete(() -> flags(new FeatureStatusScan.Flag() {
            public int id() { throw new IllegalStateException("ID getter failed"); }
            public boolean failed() { return false; }
            public boolean childOfFailed() { return false; }
        }), Collections.emptyList(), Collections.emptyList());
        System.out.println("{\"ok\":true,\"cases\":" + cases + ",\"kind\":\"cpu_only_no_creo\"}");
    }
}
