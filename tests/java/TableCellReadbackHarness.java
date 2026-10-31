package com.fateforge.creocli.service;

import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Exercises our helper with JDK lambdas; never constructs or calls a PTC object. */
public final class TableCellReadbackHarness {
    private static void append(Path path, byte[] bytes) throws IOException {
        try (FileChannel out = FileChannel.open(path, StandardOpenOption.CREATE,
                StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) out.write(buffer);
            out.force(true);
        }
    }

    public static void main(String[] args) throws Exception {
        String mode = args[0];
        Path state = Path.of(args[1]);
        Files.createDirectories(state);
        Path log = state.resolve("ordinary.log");
        Files.writeString(log, "");
        NativeReadTrace.initialize(state, Json.map("service_instance_id", "controlled-only"),
                List.of(log), (path, bytes) -> {
                    String text = new String(bytes, StandardCharsets.UTF_8);
                    if (("begin-failure".equals(mode) && text.contains("\"event\":\"begin\""))
                            || ("end-failure".equals(mode) && text.contains("\"event\":\"end\""))) {
                        throw new IOException("controlled durable-boundary failure");
                    }
                    append(path, bytes);
                });
        // Reflection is confined to our helper, not an SDK wrapper or native object.
        Method method = Detailing.class.getDeclaredMethod("cellCall", String.class, NativeReadTrace.Call.class);
        method.setAccessible(true);
        AtomicInteger calls = new AtomicInteger();
        NativeReadTrace.Fatal sentinel = new NativeReadTrace.Fatal("controlled-fatal", "body", null);
        Throwable caught = null;
        Object value = null;
        try (var request = NativeReadTrace.begin(Json.map("diagnostic_request_id", "owned-control",
                "operation", "controlled-cell-read", "phase", "cell-control", "actual_drawing", "owned.drw",
                "table_inventory_index", "2", "table_row", "3", "table_column", "4"))) {
            NativeReadTrace.Call<Object> body = () -> {
                calls.incrementAndGet();
                if ("fatal".equals(mode)) throw sentinel;
                if (mode.startsWith("ordinary")) {
                    if ("ordinary-log".equals(mode)) Files.writeString(log, "ordinary line\n", StandardOpenOption.APPEND);
                    throw new IllegalArgumentException("controlled body, no SDK getter");
                }
                return null;
            };
            try { value = method.invoke(null, "ControlledTable.GetCellNote", body); }
            catch (InvocationTargetException failure) { caught = failure.getCause(); }
        }
        Map<String, Object> out = Json.map("mode", mode, "calls", calls.get(), "value_is_null", value == null,
                "PTC_objects_constructed", 0, "real_CAD_calls", 0,
                "caught_class", caught == null ? null : caught.getClass().getName(),
                "same_fatal", caught == sentinel, "diagnostic", NativeReadTrace.stopEvidence());
        if (caught instanceof Service.ToolkitFailure failure) out.put("error", failure.error);
        if (mode.startsWith("ordinary")) {
            if (!(caught instanceof Service.ToolkitFailure failure)
                    || !"E_VERIFY_INCOMPLETE".equals(failure.error.get("code"))) throw new AssertionError("ordinary error lost");
        } else if ("fatal".equals(mode)) {
            if (caught != sentinel) throw new AssertionError("fatal replaced");
        } else if (mode.endsWith("failure")) {
            if (!(caught instanceof NativeReadTrace.Fatal)) throw new AssertionError("persistence failure replaced");
            int before = calls.get();
            try (var request = NativeReadTrace.begin(Json.map("diagnostic_request_id", "must-not-retry"))) {
                method.invoke(null, "NeverDispatchAgain", (NativeReadTrace.Call<Object>) () -> calls.incrementAndGet());
                throw new AssertionError("sticky stop cleared");
            } catch (NativeReadTrace.Fatal expected) { }
            if (calls.get() != before) throw new AssertionError("body replayed");
        } else if (caught != null) throw new AssertionError("normal null result failed", caught);
        System.out.println(Json.write(out));
    }
}
