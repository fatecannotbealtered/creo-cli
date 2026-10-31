package com.fateforge.creocli.service;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Calls the production summary-return helper with plain maps; no PTC object is constructed. */
public final class AddedNoteSummaryHarness {
    private static Map<String, Object> note(int id) {
        return Json.map("id", id, "sheet", 1, "text", "SYNTHETIC TEST ONLY",
                "displayed_text", "SYNTHETIC TEST ONLY", "at", List.of(10.000000000000002, 40.0),
                "box", null, "bounds_readback", Json.map("complete", false, "status", "unsupported",
                        "error", Json.map("code", "E_UNSUPPORTED", "native_read_state", "returned_error")),
                "membership_readback", Json.map("complete", true, "drawing", "owned.drw", "note_id", id,
                        "source", "Model2D.ListDetailItems(DETAIL_NOTE,null); Model.GetFileName; DetailItem.GetId"),
                "leaders", List.of(), "leaders_complete", true, "read_only", null);
    }

    private static Map<String, Object> summary() {
        return Json.map("model", "owned.drw", "type", "drawing", "notes", new ArrayList<>(List.of(note(4), note(7))),
                "models", List.of("support.asm"), "tables", List.of());
    }

    @SuppressWarnings("unchecked") private static Map<String, Object> selected(Map<String, Object> summary) {
        return (Map<String, Object>) ((List<?>) summary.get("notes")).get(1);
    }

    private static void append(Path path, byte[] bytes) throws IOException {
        try (FileChannel out = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE,
                StandardOpenOption.APPEND)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) out.write(buffer);
            out.force(true);
        }
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    @SuppressWarnings("unchecked") public static void main(String[] args) throws Exception {
        String mode = args[0];
        Map<String, Object> summary = summary();
        Map<String, Object> note = selected(summary);
        Map<String, Object> membership = (Map<String, Object>) note.get("membership_readback");
        String drawing = "owned.drw";
        int createdId = 7;
        boolean incomplete = false;
        Throwable sentinel = null;
        switch (mode) {
            case "actual": break;
            case "zero-id": note.put("id", 0); membership.put("note_id", 0); createdId = 0; break;
            case "mixed-case": summary.put("model", "OWNED.DRW"); membership.put("drawing", "Owned.Drw"); break;
            case "null-summary": summary = null; incomplete = true; break;
            case "wrong-drawing": summary.put("model", "other.drw"); incomplete = true; break;
            case "missing-drawing": summary.remove("model"); incomplete = true; break;
            case "wrong-type": summary.put("type", "part"); incomplete = true; break;
            case "untyped-drawing": drawing = "owned"; incomplete = true; break;
            case "negative-created-id": createdId = -1; incomplete = true; break;
            case "null-inventory": summary.put("notes", null); incomplete = true; break;
            case "missing-inventory": summary.remove("notes"); incomplete = true; break;
            case "wrong-row": ((List<Object>) summary.get("notes")).set(0, "unreadable"); incomplete = true; break;
            case "missing-created": ((List<Object>) summary.get("notes")).remove(1); incomplete = true; break;
            case "missing-id": note.remove("id"); incomplete = true; break;
            case "duplicate-id": ((List<Object>) summary.get("notes")).add(note(7)); incomplete = true; break;
            case "duplicate-other-id": ((List<Object>) summary.get("notes")).add(note(4)); incomplete = true; break;
            case "boolean-id": note.put("id", true); incomplete = true; break;
            case "floating-id": note.put("id", 7.0); incomplete = true; break;
            case "string-id": note.put("id", "7"); incomplete = true; break;
            case "negative-id": note.put("id", -1); incomplete = true; break;
            case "overflow-id": note.put("id", 0x100000007L); incomplete = true; break;
            case "row-error": note.put("error", Json.map("code", "E_CREO")); incomplete = true; break;
            case "missing-membership": note.remove("membership_readback"); incomplete = true; break;
            case "incomplete-membership": membership.put("complete", false); incomplete = true; break;
            case "missing-owner": membership.remove("drawing"); incomplete = true; break;
            case "wrong-owner": membership.put("drawing", "other.drw"); incomplete = true; break;
            case "path-owner": membership.put("drawing", "D:/owned.drw"); incomplete = true; break;
            case "wrong-member-id": membership.put("note_id", 8); incomplete = true; break;
            case "boolean-member-id": membership.put("note_id", true); incomplete = true; break;
            case "missing-member-id": membership.remove("note_id"); incomplete = true; break;
            case "missing-source": membership.remove("source"); incomplete = true; break;
            case "empty-source": membership.put("source", "  "); incomplete = true; break;
            case "pending": sentinel = new Service.ToolkitFailure(Json.map("code", "E_BUSY", "started", true,
                    "diagnostic_request_id", "controlled-original", "cause", Json.map("code", "E_TIMEOUT"))); break;
            case "diagnostic": sentinel = new NativeReadTrace.Fatal("controlled", "summary", null); break;
            case "ordinary-error": sentinel = new IllegalArgumentException("controlled summary getter failure"); break;
            case "begin-failure": case "end-failure": case "already-stopped": case "stopped-after-summary": {
                Path state = Path.of(args[1]);
                Files.createDirectories(state);
                Path log = state.resolve("ordinary.log");
                Files.writeString(log, "");
                NativeReadTrace.initialize(state, Json.map("service_instance_id", "controlled-only"), List.of(log),
                        (path, bytes) -> {
                            String text = new String(bytes, StandardCharsets.UTF_8);
                            if ((mode.equals("begin-failure") && text.contains("\"event\":\"begin\""))
                                    || (mode.equals("end-failure") && text.contains("\"event\":\"end\"")))
                                throw new IOException("controlled persistence boundary");
                            append(path, bytes);
                        });
                if (mode.equals("already-stopped"))
                    NativeReadTrace.requestUnreturned(Json.map("diagnostic_request_id", "original"),
                            Json.map("code", "E_BUSY", "started", true));
                break;
            }
            default: throw new AssertionError("unknown control");
        }
        AtomicInteger traversals = new AtomicInteger();
        AtomicInteger bodies = new AtomicInteger();
        final Map<String, Object> actualSummary = summary;
        final Throwable failure = sentinel;
        String before = Json.write(summary);
        Throwable caught = null;
        Map<String, Object> result = null;
        try (var request = NativeReadTrace.begin(Json.map("diagnostic_request_id", "owned-control",
                "operation", "controlled-summary-return", "actual_drawing", "owned.drw"))) {
            result = Drawings.addedNoteSummary(drawing, createdId, () -> {
                traversals.incrementAndGet();
                return NativeReadTrace.call("ControlledSummaryTraversal", () -> {
                    bodies.incrementAndGet();
                    if (failure != null) throw failure;
                    if (mode.equals("stopped-after-summary"))
                        NativeReadTrace.requestUnreturned(Json.map("diagnostic_request_id", "original"),
                                Json.map("code", "E_BUSY", "started", true));
                    return actualSummary;
                });
            });
        } catch (Throwable thrown) { caught = thrown; }
        if (incomplete) {
            check(caught instanceof Service.ToolkitFailure, "incomplete must have ordinary explicit classification");
            Map<String, Object> error = ((Service.ToolkitFailure) caught).error;
            check("E_VERIFY_INCOMPLETE".equals(error.get("code")), "wrong incomplete code");
            check("summary_returned_incomplete".equals(error.get("native_read_state")), "wrong native state");
            check(!error.containsKey("started") && !error.containsKey("native_call_pending"), "invented pending");
            check(Boolean.FALSE.equals(error.get("automatic_retry")), "must not replay");
            check(Json.write(summary).equals(before), "incomplete response mutated");
        } else if (sentinel != null) {
            check(caught == sentinel, "original summary failure replaced");
            check(!summary.containsKey("note"), "failed summary became returned note");
        } else if (mode.endsWith("failure") || mode.endsWith("stopped") || mode.equals("stopped-after-summary")) {
            check(caught instanceof NativeReadTrace.Fatal, "durable/stop failure replaced");
            check(!summary.containsKey("note"), "stopped summary became returned note");
        } else {
            if (caught != null) throw new AssertionError("valid response failed", caught);
            check(result == summary && result.get("note") == note, "must reuse exact actual row without native fallback");
            check(note.get("box") == null && Boolean.FALSE.equals(((Map<?, ?>) note.get("bounds_readback")).get("complete")),
                    "optional incomplete bounds fabricated");
            check(note.get("read_only") == null, "optional null fabricated");
            check(((List<?>) note.get("at")).get(0).equals(10.000000000000002), "coordinate rounded");
        }
        check(traversals.get() == (mode.equals("already-stopped") ? 0 : 1), "summary traversal repeated");
        check(bodies.get() == (mode.equals("already-stopped") || mode.equals("begin-failure") ? 0 : 1), "body repeated");
        Map<String, Object> out = Json.map("mode", mode, "summary_traversals", traversals.get(),
                "summary_bodies", bodies.get(), "PTC_objects_constructed", 0, "real_CAD_calls", 0,
                "same_failure", sentinel != null && caught == sentinel,
                "caught_class", caught == null ? null : caught.getClass().getName(),
                "returned_actual_row", result != null && result.get("note") == note,
                "diagnostic", NativeReadTrace.stopEvidence());
        if (caught instanceof Service.ToolkitFailure failureResult) out.put("error", failureResult.error);
        System.out.println(Json.write(out));
    }
}
