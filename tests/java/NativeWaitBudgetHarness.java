package com.fateforge.creocli.service;

import java.util.AbstractList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Production pure-JDK policy only; no HTTP server, SDK classes or CAD objects. */
public final class NativeWaitBudgetHarness {
    private static int cases;
    private static final Runnable HEALTHY = () -> { };
    private static final List<String> PROFILE = List.of("drawing-complete-v1");

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void expect(long wanted, String op, List<String> profile, List<String> wait) {
        check(NativeWaitBudget.milliseconds(HEALTHY, op, profile, wait) == wanted, "wrong wait");
        cases++;
    }

    private static void refuse(String op, List<String> profile, List<String> wait) {
        try {
            NativeWaitBudget.milliseconds(HEALTHY, op, profile, wait);
            throw new AssertionError("unexpected acceptance");
        } catch (NativeWaitBudget.Refusal failure) {
            Map<String, Object> error = NativeWaitBudget.refusal(failure);
            check(error.get("code").equals("E_VALIDATION"), "wrong refusal code");
            check(Boolean.FALSE.equals(error.get("started")), "a refusal did not start CAD");
            check(Boolean.FALSE.equals(error.get("retryable")), "a refusal is not automatic retry");
            check(error.size() == 4, "no invented diagnostic/request or write identity");
            check(!failure.getMessage().contains("secret-sentinel"), "raw header was echoed");
            cases++;
        }
    }

    public static void main(String[] args) {
        switch (args[0]) {
            case "legacy": {
                expect(120_000, "/session", null, null);
                expect(120_000, "feature.delete", null, List.of());
                String[] values = {"100", "119999", "120000", "120001", "600000",
                        "0", "-1", "9223372036854775807", "-9223372036854775808",
                        "nonsense", "9223372036854775808", " 17500 "};
                long[] expected = {100, 119999, 120000, 120000, 120000, 100, 100,
                        120000, 100, 120000, 120000, 17500};
                for (int i = 0; i < values.length; i++)
                    expect(expected[i], null, null, List.of(values[i]));
                expect(1234, "model.show", null, List.of("1234", "5678"));
                break;
            }
            case "allowed-operations": {
                String[] ops = {"session.status", "model.list", "model.management-state", "model.show",
                        "dimension.list", "feature.list", "feature.show", "geometry.list",
                        "geometry.mass-properties", "geometry.bounds", "parameter.list", "relation.list",
                        "material.list", "family.show", "drawing.info", "drawing.resources",
                        "drawing.bom-template", "drawing.activate", "drawing.create", "drawing.add-note",
                        "drawing.edit-note", "drawing.add-bom", "drawing.add-balloons", "drawing.add-view",
                        "drawing.move-view", "drawing.move-table", "model.save", "model.close", "model.export"};
                for (String op : ops) expect(300_000, op, PROFILE, List.of("600000"));
                break;
            }
            case "remaining-and-cap": {
                String[] values = {"1", "99", "100", "111876", "120000", "120001",
                        "299999", "300000", "600000", "9223372036854775807", " 17500 "};
                long[] expected = {100, 100, 100, 111876, 120000, 120001, 299999,
                        300000, 300000, 300000, 17500};
                for (int i = 0; i < values.length; i++)
                    expect(expected[i], "drawing.add-bom", PROFILE, List.of(values[i]));
                break;
            }
            case "invalid-profile": {
                for (List<String> profile : List.of(List.<String>of(), List.of(""),
                        List.of("secret-sentinel"), List.of("DRAWING-COMPLETE-V1"),
                        List.of(" drawing-complete-v1 "), List.of("drawing-complete-v2"),
                        List.of("drawing-complete-v1,drawing-complete-v1"),
                        List.of("drawing-complete-v1", "drawing-complete-v1")))
                    refuse("model.show", profile, List.of("300000"));
                refuse("model.show", Arrays.asList((String) null), List.of("300000"));
                break;
            }
            case "unsupported-operations": {
                String[] ops = {"/session", "/health", "diagnostic.note", "feature.delete",
                        "feature.round", "feature.hole", "feature.rib", "dimension.set", "material.assign",
                        "model.open", "model.discard", "model.regenerate", "model.import",
                        "assembly.explode", "drawing.symbol", "drawing.add-symbol", "drawing.add-gtol",
                        "drawing.add-datum", "drawing.apply-layout", "drawing.remove", "workflow.run", ""};
                for (String op : ops) refuse(op, PROFILE, List.of("300000"));
                refuse(null, PROFILE, List.of("300000"));
                break;
            }
            case "invalid-wait": {
                refuse("model.show", PROFILE, null);
                refuse("model.show", PROFILE, List.of());
                refuse("model.show", PROFILE, List.of("100", "200"));
                refuse("model.show", PROFILE, Arrays.asList((String) null));
                for (String value : new String[] {"", " ", "0", "-1", "+100", "NaN", "Infinity",
                        "1e4", "100.0", "100,200", "9223372036854775808", "12345678901234567890"})
                    refuse("model.show", PROFILE, List.of(value));
                break;
            }
            case "stop-priority": {
                Error sentinel = new AssertionError("original diagnostic stop");
                AtomicInteger guardCalls = new AtomicInteger();
                List<String> unreadableHeaders = new AbstractList<>() {
                    @Override public String get(int index) { throw new AssertionError("header inspected"); }
                    @Override public int size() { throw new AssertionError("header inspected"); }
                };
                for (List<String> profile : Arrays.asList(null, PROFILE, unreadableHeaders)) {
                    try {
                        NativeWaitBudget.milliseconds(() -> {
                            guardCalls.incrementAndGet(); throw sentinel;
                        }, "feature.delete", profile, unreadableHeaders);
                        throw new AssertionError("guard swallowed");
                    } catch (Error failure) {
                        check(failure == sentinel, "original stop was replaced");
                        cases++;
                    }
                }
                check(guardCalls.get() == 3, "guard must run exactly once per policy call");
                break;
            }
            default: throw new AssertionError("unknown test mode");
        }
        System.out.println("{\"passed_cases\":" + cases
                + ",\"SDK_objects\":0,\"CAD_calls\":0,\"HTTP_requests\":0}");
    }
}
