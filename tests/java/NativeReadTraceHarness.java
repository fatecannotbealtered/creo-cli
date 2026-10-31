package com.fateforge.creocli.service;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

/** CPU-only control processes. This class never imports or loads a PTC class. */
public final class NativeReadTraceHarness {
    private static final AtomicInteger CALLS = new AtomicInteger();
    private static Path state;
    private static Path log;
    private static String mode;

    private static void append(Path path, byte[] bytes) throws IOException {
        Files.createDirectories(path.getParent());
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.CREATE,
                StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) channel.write(buffer);
            channel.force(true);
        }
    }
    private static NativeReadTrace.Scope request(String id) {
        return NativeReadTrace.begin(Json.map("diagnostic_request_id", id, "cli_invocation_id", null,
                "operation", "controlled.read", "phase", "controlled-phase",
                "drawing_observed", "owned-test.drw", "note_id", "12", "line_index", "0"));
    }
    private static void init(NativeReadTrace.Sink sink) throws Exception {
        Files.createDirectories(state);
        log = state.resolve("std.out");
        Files.write(log, new byte[0]);
        NativeReadTrace.initialize(state, Json.map("service_instance_id", "controlled-generation",
                "java_process_id", String.valueOf(ProcessHandle.current().pid()),
                "java_started_at", ProcessHandle.current().info().startInstant().orElseThrow().toString()),
                List.of(log), sink);
    }
    private static void nextMustBeBlocked() {
        int before = CALLS.get();
        try (NativeReadTrace.Scope trace = request("second-request")) {
            NativeReadTrace.call("NeverDispatchAgain", () -> CALLS.incrementAndGet());
            throw new AssertionError("sticky stop was cleared by a new request");
        } catch (NativeReadTrace.Fatal expected) { }
        if (CALLS.get() != before) throw new AssertionError("native replay after stop");
    }
    public static void main(String[] args) throws Exception {
        mode = args[0]; state = Path.of(args[1]).toAbsolutePath();
        if ("inspect".equals(mode)) {
            System.out.println(Json.write(NativeReadTrace.inspectJournal(state.resolve("native-read-trace.ndjson"))));
            return;
        }
        if ("channels".equals(mode)) {
            Files.createDirectories(state);
            log = state.resolve("std.out");
            Path trail = state.resolve("trail.txt.1");
            Files.write(log, new byte[0]);
            Files.write(trail, new byte[0]);
            NativeReadTrace.initialize(state, Json.map("service_instance_id", "channel-generation"),
                    List.of(log, trail), NativeReadTraceHarness::append);
            try (NativeReadTrace.Scope trace = request("channels-request")) {
                NativeReadTrace.call("BothChannelsSameNativeEvent", () -> {
                    CALLS.incrementAndGet();
                    Files.writeString(log, "ORDER_DEBUG: same event\n", StandardOpenOption.APPEND);
                    Files.writeString(trail, "ORDER_DEBUG: same event\n", StandardOpenOption.APPEND);
                    return 1;
                });
                throw new AssertionError("serious event ignored");
            } catch (NativeReadTrace.Fatal expected) { }
            nextMustBeBlocked();
        } else if ("absent".equals(mode)) {
            Files.createDirectories(state);
            log = state.resolve("std.out");
            NativeReadTrace.initialize(state, Json.map("service_instance_id", "absent-generation"),
                    List.of(log), NativeReadTraceHarness::append);
            try (NativeReadTrace.Scope trace = request("absent-request")) {
                NativeReadTrace.call("FirstCallCreatesDeclaredLog", () -> {
                    CALLS.incrementAndGet();
                    Files.writeString(log, "safe first line\n");
                    return 1;
                });
                NativeReadTrace.call("SecondCall", () -> CALLS.incrementAndGet());
            }
        } else if ("not-regular".equals(mode)) {
            Files.createDirectories(state);
            log = state.resolve("std.out");
            Files.createDirectory(log);
            try {
                NativeReadTrace.initialize(state, Json.map("service_instance_id", "bad-log-generation"),
                        List.of(log), NativeReadTraceHarness::append);
                throw new AssertionError("unreadable non-file log silently accepted");
            } catch (NativeReadTrace.Fatal expected) { }
            nextMustBeBlocked();
        } else if (mode.startsWith("persist-")) {
            String boundary = mode.contains("-end-") ? "\"event\":\"end\"" : "\"event\":\"begin\"";
            boolean partial = mode.endsWith("partial");
            init((path, bytes) -> {
                String text = new String(bytes, StandardCharsets.UTF_8);
                if (text.contains(boundary)) {
                    if (partial) append(path, java.util.Arrays.copyOf(bytes, bytes.length / 2));
                    throw new IOException("controlled append/force boundary failure");
                }
                append(path, bytes);
            });
            try (NativeReadTrace.Scope trace = request("persistence-request")) {
                NativeReadTrace.call("ControlledNative", () -> CALLS.incrementAndGet());
                throw new AssertionError("missing persistence stop");
            } catch (NativeReadTrace.Fatal expected) { }
            nextMustBeBlocked();
            int wanted = boundary.contains("end") ? 1 : 0;
            if (CALLS.get() != wanted) throw new AssertionError("wrong actual call count");
        } else if ("observer-persist-failure".equals(mode)) {
            try {
                init((path, bytes) -> { throw new IOException("controlled initial force failure"); });
                throw new AssertionError("missing initialization persistence stop");
            } catch (NativeReadTrace.Fatal expected) { }
            nextMustBeBlocked();
        } else {
            init(NativeReadTraceHarness::append);
            if ("wait-expiry-completion".equals(mode)) {
                CountDownLatch entered = new CountDownLatch(1);
                CountDownLatch release = new CountDownLatch(1);
                CompletableFuture<Object> work = new CompletableFuture<>();
                Thread toolkit = new Thread(() -> {
                    try (NativeReadTrace.Scope trace = request("wait-expiry-request")) {
                        NativeReadTrace.call("ReturnsAfterHttpWaitExpired", () -> {
                            CALLS.incrementAndGet();
                            entered.countDown();
                            release.await();
                            NativeReadTrace.effect("created_object", Json.map("id", "19", "saved", false));
                            return 9;
                        });
                        NativeReadTrace.call("NeverAfterUnreturnedStop", () -> CALLS.incrementAndGet());
                        work.complete("unexpected later dispatch");
                    } catch (NativeReadTrace.Fatal expected) { work.complete(expected.reason); }
                    catch (Throwable failure) { work.completeExceptionally(failure); }
                }, "controlled-toolkit-thread");
                toolkit.start();
                if (!entered.await(5, TimeUnit.SECONDS)) throw new AssertionError("getter not entered");
                try { work.get(75, TimeUnit.MILLISECONDS); throw new AssertionError("getter unexpectedly returned"); }
                catch (TimeoutException expected) {
                    NativeReadTrace.requestUnreturned(Json.map("operation", "controlled.read",
                            "diagnostic_request_id", "wait-expiry-request", "cli_invocation_id", null),
                            Json.map("code", "E_BUSY", "started", true, "retryable", false));
                }
                nextMustBeBlocked();
                if (!toolkit.isAlive()) throw new AssertionError("HTTP wait expiry cancelled the native call");
                release.countDown();
                Object result = work.get(5, TimeUnit.SECONDS);
                toolkit.join(5000);
                if (!"native_request_unreturned_at_wait_expiry".equals(result)) throw new AssertionError("wrong stop result");
                if (toolkit.isAlive() || CALLS.get() != 1) throw new AssertionError("later native dispatch or lost completion");
            } else if ("hang".equals(mode) || "halt".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("unreturned-request")) {
                    NativeReadTrace.call("GetterThatDoesNotReturn", () -> {
                        CALLS.incrementAndGet();
                        if ("halt".equals(mode)) Runtime.getRuntime().halt(73);
                        new CountDownLatch(1).await();
                        return null;
                    });
                }
            } else if ("normal".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("normal-request")) {
                    Object proxyLike = new Object() {
                        @Override public String toString() { throw new AssertionError("proxy stringification"); }
                    };
                    NativeReadTrace.call("ObjectReturn", () -> { CALLS.incrementAndGet(); return proxyLike; });
                    NativeReadTrace.call("NullReturn", () -> { CALLS.incrementAndGet(); return null; });
                    try {
                        NativeReadTrace.call("OrdinaryUnsupported", () -> {
                            CALLS.incrementAndGet();
                            throw new RuntimeException() {
                                @Override public String getMessage() { throw new AssertionError("exception getter"); }
                                @Override public String toString() { throw new AssertionError("exception formatting"); }
                            };
                        });
                    } catch (RuntimeException expected) { NativeReadTrace.rethrowFatal(expected); }
                    NativeReadTrace.effect("native_write_returned", Json.map("operation", "controlled.write", "id", "7"));
                    NativeReadTrace.call("StillAllowedAfterOrdinaryError", () -> CALLS.incrementAndGet());
                    try { NativeReadTrace.known("not_plain", proxyLike); throw new AssertionError("proxy accepted"); }
                    catch (IllegalArgumentException expected) { }
                }
                if (Boolean.TRUE.equals(NativeReadTrace.stopEvidence().get("stopped"))) throw new AssertionError("ordinary error stopped generation");
            } else if ("serious-returned".equals(mode) || "serious-split".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("serious-request")) {
                    NativeReadTrace.call("ReturnedBeforeVisibleSerious", () -> {
                        CALLS.incrementAndGet();
                        NativeReadTrace.effect("created_object", Json.map("id", "17", "saved", false));
                        Files.writeString(log, "serious-split".equals(mode) ? "prefix ORDER_" : "prefix ORDER_DEBUG: 3\n", StandardOpenOption.APPEND);
                        return 17;
                    });
                    if ("serious-split".equals(mode)) Files.writeString(log, "DEBUG: split across polls\n", StandardOpenOption.APPEND);
                    NativeReadTrace.call("MustNotRun", () -> CALLS.incrementAndGet());
                    throw new AssertionError("serious message was ignored");
                } catch (NativeReadTrace.Fatal expected) { }
                nextMustBeBlocked();
                if (CALLS.get() != 1) throw new AssertionError("a later call ran after serious became visible");
            } else if ("delayed-serious".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("delayed-request")) {
                    NativeReadTrace.call("EarlierCallBeforeLogFlush", () -> CALLS.incrementAndGet());
                    NativeReadTrace.call("AlreadyEnteredWhenLogBecameVisible", () -> {
                        CALLS.incrementAndGet();
                        Files.writeString(log, "ORDER_DEBUG: delayed flush from unknown native event time\n", StandardOpenOption.APPEND);
                        return 2;
                    });
                    throw new AssertionError("serious message was ignored");
                } catch (NativeReadTrace.Fatal expected) { }
                nextMustBeBlocked();
                if (CALLS.get() != 2) throw new AssertionError("in-flight call facts changed");
            } else if ("truncate".equals(mode) || "replace".equals(mode) || "rewrite".equals(mode)
                    || "oversized".equals(mode) || "partial-line".equals(mode) || "disappear".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("log-boundary-request")) {
                    NativeReadTrace.call("InitialSuccessfulCall", () -> {
                        CALLS.incrementAndGet();
                        Files.writeString(log, "first safe line\n", StandardOpenOption.APPEND);
                        return null;
                    });
                    if ("truncate".equals(mode)) Files.write(log, new byte[0]);
                    if ("rewrite".equals(mode)) Files.writeString(log, "other safe line\n");
                    if ("disappear".equals(mode)) Files.delete(log);
                    if ("replace".equals(mode)) {
                        Files.move(log, state.resolve("retained-original.out"));
                        Files.writeString(log, "replacement\n");
                    }
                    if ("oversized".equals(mode)) Files.write(log, new byte[(1 << 20) + 1], StandardOpenOption.APPEND);
                    if ("partial-line".equals(mode)) Files.write(log, new byte[65537], StandardOpenOption.APPEND);
                    NativeReadTrace.call("MustNotRunAfterUnreliableLog", () -> CALLS.incrementAndGet());
                    throw new AssertionError("log boundary was ignored");
                } catch (NativeReadTrace.Fatal expected) { }
                nextMustBeBlocked();
                if (CALLS.get() != 1) throw new AssertionError("native call ran after log coverage loss");
            } else if ("safe-increment".equals(mode)) {
                try (NativeReadTrace.Scope trace = request("increment-request")) {
                    for (int i = 0; i < 3; i++) {
                        Files.writeString(log, "ordinary line\n", StandardOpenOption.APPEND);
                        NativeReadTrace.call("SafeIncrement", () -> CALLS.incrementAndGet());
                    }
                }
            } else throw new AssertionError("unknown harness mode " + mode);
        }
        System.out.println(Json.write(Json.map("ok", true, "mode", mode, "calls", CALLS.get(),
                "kind", "sdk_free_control_no_creo", "native_diagnostic", NativeReadTrace.stopEvidence())));
    }
}
