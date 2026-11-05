package com.fateforge.creocli.host.core;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The host protocol on one connection (DCLI-272 to DCLI-279): Content-Length framing with
 * CRLF, JSON-RPC 2.0, {@code hello} first, and every failure as a JSON-RPC error with code
 * -32000 whose {@code data} carries the host error code and the dispatch state.
 */
public final class Protocol {
    /** The methods a host answers. */
    public interface Methods {
        /** The result, {@link MainThread#NO_REPLY}, or a thrown {@link HostError}. */
        Object call(String method, Map<String, Object> params);
    }

    private static final Pattern HEADER = Pattern.compile("Content-Length: ([0-9]{1,9})\r\n\r\n");
    private static final int MAX_HEADER = 32;
    private static final int MAX_BODY = 64 * 1024 * 1024;

    private final Pipe.Stream stream;
    private final Methods methods;
    private byte[] buffer = new byte[0];

    private Protocol(Pipe.Stream stream, Methods methods) {
        this.stream = stream;
        this.methods = methods;
    }

    /** Answer requests until the client closes the connection or breaks the framing. */
    public static void serve(Pipe.Stream stream, Methods methods) {
        new Protocol(stream, methods).loop();
    }

    private void loop() {
        boolean greeted = false;
        while (true) {
            String body = next();
            if (body == null) {
                return;
            }
            Object parsed;
            try {
                parsed = Json.parse(body);
            } catch (IllegalArgumentException bad) {
                reply(error(null, new HostError(HostError.VALIDATION, "the request is not JSON: " + bad.getMessage())));
                continue;
            }
            Map<String, Object> request = asRequest(parsed);
            if (request == null) {
                Object id = parsed instanceof Map ? ((Map<?, ?>) parsed).get("id") : null;
                reply(error(id, new HostError(HostError.VALIDATION, "the request is not a JSON-RPC 2.0 request")));
                continue;
            }
            Object id = request.get("id");
            String method = (String) request.get("method");
            @SuppressWarnings("unchecked")
            Map<String, Object> params = request.get("params") instanceof Map
                    ? (Map<String, Object>) request.get("params") : new LinkedHashMap<>();
            if (!greeted && !"hello".equals(method)) {
                reply(error(id, new HostError(HostError.VALIDATION, "the first request on a connection must be hello")));
                continue;
            }
            greeted = true;
            Object result;
            try {
                result = methods.call(method, params);
            } catch (HostError refused) {
                reply(error(id, refused));
                continue;
            } catch (Throwable failure) {
                HostError unknown = new HostError(HostError.NATIVE, "the host failed: " + failure, "unknown");
                reply(error(id, unknown));
                continue;
            }
            if (result == MainThread.NO_REPLY) {
                return; // the deadline passed; a late reply must not answer the next request
            }
            Map<String, Object> ok = new LinkedHashMap<>();
            ok.put("jsonrpc", "2.0");
            ok.put("id", id);
            ok.put("result", result);
            reply(ok);
        }
    }

    private static Map<String, Object> asRequest(Object parsed) {
        if (!(parsed instanceof Map)) {
            return null;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> m = (Map<String, Object>) parsed;
        Object id = m.get("id");
        boolean idOk = id instanceof String || id instanceof Long;
        if (!"2.0".equals(m.get("jsonrpc")) || !(m.get("method") instanceof String) || !idOk
                || (m.containsKey("params") && !(m.get("params") instanceof Map))) {
            return null;
        }
        return m;
    }

    private static Map<String, Object> error(Object id, HostError failure) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", -32000);
        error.put("message", failure.getMessage());
        error.put("data", failure.data());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("jsonrpc", "2.0");
        out.put("id", id);
        out.put("error", error);
        return out;
    }

    // ------------------------------------------------------------------ framing

    /** The next message body, or null at the end of the stream or on a framing error. */
    private String next() {
        int end;
        while ((end = indexOf(buffer, new byte[] {'\r', '\n', '\r', '\n'})) < 0) {
            if (buffer.length > MAX_HEADER || !fill()) {
                return null;
            }
        }
        String header = new String(buffer, 0, end + 4, StandardCharsets.US_ASCII);
        Matcher match = HEADER.matcher(header);
        if (!match.matches()) {
            return null;
        }
        int size = Integer.parseInt(match.group(1));
        if (size > MAX_BODY) {
            return null;
        }
        buffer = slice(buffer, end + 4, buffer.length);
        while (buffer.length < size) {
            if (!fill()) {
                return null;
            }
        }
        String body = new String(buffer, 0, size, StandardCharsets.UTF_8);
        buffer = slice(buffer, size, buffer.length);
        return body;
    }

    private boolean fill() {
        byte[] chunk = stream.read(65536);
        if (chunk.length == 0) {
            return false;
        }
        ByteArrayOutputStream joined = new ByteArrayOutputStream(buffer.length + chunk.length);
        joined.write(buffer, 0, buffer.length);
        joined.write(chunk, 0, chunk.length);
        buffer = joined.toByteArray();
        return true;
    }

    private void reply(Map<String, Object> message) {
        byte[] body = Json.write(message).getBytes(StandardCharsets.UTF_8);
        byte[] header = ("Content-Length: " + body.length + "\r\n\r\n").getBytes(StandardCharsets.US_ASCII);
        byte[] all = new byte[header.length + body.length];
        System.arraycopy(header, 0, all, 0, header.length);
        System.arraycopy(body, 0, all, header.length, body.length);
        stream.write(all);
    }

    private static int indexOf(byte[] data, byte[] pattern) {
        outer:
        for (int i = 0; i + pattern.length <= data.length; i++) {
            for (int j = 0; j < pattern.length; j++) {
                if (data[i + j] != pattern[j]) {
                    continue outer;
                }
            }
            return i;
        }
        return -1;
    }

    private static byte[] slice(byte[] data, int from, int to) {
        byte[] out = new byte[to - from];
        System.arraycopy(data, from, out, 0, out.length);
        return out;
    }
}
