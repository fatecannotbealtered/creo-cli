import com.fateforge.creocli.host.core.Distance;
import com.fateforge.creocli.host.core.HostError;
import com.fateforge.creocli.host.core.Json;
import com.fateforge.creocli.host.core.MainThread;
import com.fateforge.creocli.host.core.Pipe;
import com.fateforge.creocli.host.core.Protocol;

import java.util.Arrays;
import java.util.Map;

/**
 * A host made of the real core classes and no Creo, for tests/test_host_protocol.py: the
 * pipe, the framing, the handshake, the main-thread hand-off, deadlines and errors. A thread
 * stands in for Creo's timer. "pause" and "resume" (on the pipe thread) stop and restart it.
 */
public final class TestHost {
    private static volatile boolean paused;

    public static void main(String[] args) throws Exception {
        MainThread main = new MainThread(300);
        Thread pump = new Thread(() -> {
            while (true) {
                if (!paused) {
                    main.pump();
                }
                try {
                    Thread.sleep(20);
                } catch (InterruptedException stop) {
                    return;
                }
            }
        }, "test-pump");
        pump.setDaemon(true);
        pump.start();
        Pipe pipe = new Pipe(args[0], stream -> Protocol.serve(stream, (method, params) -> call(main, method, params)));
        pipe.start();
        System.out.println("READY " + pipe.name);
        System.out.flush();
        System.in.read();
        pipe.stop();
    }

    private static Object call(MainThread main, String method, Map<String, Object> params) {
        long deadline = Json.integer(params, "deadline_ms") == null ? 5000 : Json.integer(params, "deadline_ms");
        switch (method) {
            case "hello":
                return Json.map("protocol_version", "1.2.0", "plugin_version", "test",
                        "application", Json.map("name", "Creo Parametric", "version", "13.4.1.0"),
                        "session", Json.map("id", "creo-1-1", "generation", 0),
                        "methods", Arrays.asList("documents", "read", "apply"));
            case "distance":
                return Json.map("distance", Distance.between(shape(Json.object(params, "a")), shape(Json.object(params, "b"))));
            case "pause":
                paused = true;
                return Json.map();
            case "resume":
                paused = false;
                return Json.map();
            case "documents":
            case "read":
            case "apply":
                Map<String, Object> inputs = Json.object(params, "inputs");
                return main.submit(() -> {
                    Long sleep = Json.integer(inputs, "sleep_ms");
                    if (sleep != null) {
                        Thread.sleep(sleep);
                    }
                    if (inputs.containsKey("fail")) {
                        throw new HostError(HostError.NOT_FOUND, "no such object").nativeMessage("Creo says: not here");
                    }
                    Long size = Json.integer(inputs, "size");
                    String text = size == null ? "ok" : "x".repeat(size.intValue());
                    return "apply".equals(method) ? Json.map("dispatch_state", "dispatched", "change", "applied",
                            "delivery", "not_applicable", "persistence", "unchanged", "result", Json.map("text", text))
                            : Json.map("result", Json.map("text", text), "items", Arrays.asList());
                }, deadline);
            default:
                throw new HostError(HostError.UNSUPPORTED, "no method " + method);
        }
    }

    /** {"kind": "point" | "line" | "plane", "at": [x, y, z], "direction": [x, y, z]} */
    private static Distance.Shape shape(Map<String, Object> spec) {
        double[] at = triple(spec.get("at"));
        switch (Json.string(spec, "kind", "plane")) {
            case "point": return Distance.Shape.point(at);
            case "line": return Distance.Shape.line(at, triple(spec.get("direction")));
            default: return Distance.Shape.plane(at, triple(spec.get("direction")));
        }
    }

    private static double[] triple(Object raw) {
        java.util.List<?> list = (java.util.List<?>) raw;
        return new double[] {((Number) list.get(0)).doubleValue(), ((Number) list.get(1)).doubleValue(),
                ((Number) list.get(2)).doubleValue()};
    }
}
