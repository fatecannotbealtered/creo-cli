package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Just enough JSON for a loopback protocol with one client.
 *
 * <p>A library would be the obvious choice anywhere else. Here the jar is loaded into
 * a JVM Creo owns and shares with every other toolkit application in the session, so
 * a bundled dependency is a class-path collision waiting for someone else's add-in to
 * bring a different version of it. The protocol is small and fixed, and this is the
 * whole of it: objects, arrays, strings, numbers, booleans, null.
 *
 * <p>Parsed values are {@code Map<String,Object>}, {@code List<Object>}, {@code String},
 * {@code Double}, {@code Boolean} or {@code null}. Numbers are always doubles; callers
 * that need an integer say so through {@link #integer}, which refuses fractions rather
 * than truncating them.
 */
final class Json {

    private final String text;
    private int at;

    private Json(String text) {
        this.text = text;
    }

    static Object parse(String text) {
        Json parser = new Json(text);
        parser.space();
        Object value = parser.value();
        parser.space();
        if (parser.at != text.length()) {
            throw parser.error("unexpected trailing content");
        }
        return value;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> object(Object value, String what) {
        if (!(value instanceof Map)) {
            throw new IllegalArgumentException(what + " must be a JSON object");
        }
        return (Map<String, Object>) value;
    }

    static String string(Map<String, Object> from, String key) {
        Object value = from.get(key);
        if (!(value instanceof String) || ((String) value).isEmpty()) {
            throw new IllegalArgumentException("'" + key + "' must be a non-empty string");
        }
        return (String) value;
    }

    static String string(Map<String, Object> from, String key, String fallback) {
        return from.containsKey(key) ? string(from, key) : fallback;
    }

    static double number(Map<String, Object> from, String key) {
        Object value = from.get(key);
        if (!(value instanceof Double) || ((Double) value).isNaN() || ((Double) value).isInfinite()) {
            throw new IllegalArgumentException("'" + key + "' must be a finite number");
        }
        return (Double) value;
    }

    static int integer(Map<String, Object> from, String key) {
        double value = number(from, key);
        if (value != Math.rint(value) || Math.abs(value) > Integer.MAX_VALUE) {
            throw new IllegalArgumentException("'" + key + "' must be an integer");
        }
        return (int) value;
    }

    static int integer(Map<String, Object> from, String key, int fallback) {
        return from.containsKey(key) ? integer(from, key) : fallback;
    }

    static boolean bool(Map<String, Object> from, String key, boolean fallback) {
        Object value = from.get(key);
        if (value == null) {
            return fallback;
        }
        if (!(value instanceof Boolean)) {
            throw new IllegalArgumentException("'" + key + "' must be true or false");
        }
        return (Boolean) value;
    }

    // ---------------------------------------------------------------- writing

    static String write(Object value) {
        StringBuilder out = new StringBuilder();
        write(value, out);
        return out.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(Object value, StringBuilder out) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String) {
            quote((String) value, out);
        } else if (value instanceof Boolean) {
            out.append(value);
        } else if (value instanceof Number) {
            double d = ((Number) value).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) {
                out.append("null");
            } else if (d == Math.rint(d) && Math.abs(d) < 1e15) {
                out.append((long) d);
            } else {
                out.append(d);
            }
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                quote(entry.getKey(), out);
                out.append(':');
                write(entry.getValue(), out);
            }
            out.append('}');
        } else if (value instanceof List) {
            out.append('[');
            boolean first = true;
            for (Object item : (List<Object>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                write(item, out);
            }
            out.append(']');
        } else {
            quote(String.valueOf(value), out);
        }
    }

    private static void quote(String value, StringBuilder out) {
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
            }
        }
        out.append('"');
    }

    /** An ordered map literal, so replies keep the field order they are written in. */
    static Map<String, Object> map(Object... pairs) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            out.put((String) pairs[i], pairs[i + 1]);
        }
        return out;
    }

    // ---------------------------------------------------------------- parsing

    private Object value() {
        if (at >= text.length()) {
            throw error("unexpected end of input");
        }
        char c = text.charAt(at);
        switch (c) {
            case '{': return objectValue();
            case '[': return arrayValue();
            case '"': return stringValue();
            case 't': return literal("true", Boolean.TRUE);
            case 'f': return literal("false", Boolean.FALSE);
            case 'n': return literal("null", null);
            default:
                if (c == '-' || (c >= '0' && c <= '9')) {
                    return numberValue();
                }
                throw error("unexpected character '" + c + "'");
        }
    }

    private Map<String, Object> objectValue() {
        Map<String, Object> out = new LinkedHashMap<>();
        at++;
        space();
        if (peek('}')) {
            at++;
            return out;
        }
        while (true) {
            space();
            if (!peek('"')) {
                throw error("expected a string key");
            }
            String key = stringValue();
            space();
            expect(':');
            space();
            if (out.containsKey(key)) {
                // Last-one-wins is what most parsers do and exactly how a confused client
                // gets an operation it did not intend.
                throw error("duplicate key '" + key + "'");
            }
            out.put(key, value());
            space();
            if (peek(',')) {
                at++;
                continue;
            }
            expect('}');
            return out;
        }
    }

    private List<Object> arrayValue() {
        List<Object> out = new ArrayList<>();
        at++;
        space();
        if (peek(']')) {
            at++;
            return out;
        }
        while (true) {
            space();
            out.add(value());
            space();
            if (peek(',')) {
                at++;
                continue;
            }
            expect(']');
            return out;
        }
    }

    private String stringValue() {
        StringBuilder out = new StringBuilder();
        at++;
        while (at < text.length()) {
            char c = text.charAt(at++);
            if (c == '"') {
                return out.toString();
            }
            if (c == '\\') {
                if (at >= text.length()) {
                    break;
                }
                char e = text.charAt(at++);
                switch (e) {
                    case '"': out.append('"'); break;
                    case '\\': out.append('\\'); break;
                    case '/': out.append('/'); break;
                    case 'b': out.append('\b'); break;
                    case 'f': out.append('\f'); break;
                    case 'n': out.append('\n'); break;
                    case 'r': out.append('\r'); break;
                    case 't': out.append('\t'); break;
                    case 'u':
                        if (at + 4 > text.length()) {
                            throw error("truncated \\u escape");
                        }
                        try {
                            out.append((char) Integer.parseInt(text.substring(at, at + 4), 16));
                        } catch (NumberFormatException bad) {
                            throw error("bad \\u escape");
                        }
                        at += 4;
                        break;
                    default:
                        throw error("bad escape '\\" + e + "'");
                }
            } else if (c < 0x20) {
                throw error("control character in string");
            } else {
                out.append(c);
            }
        }
        throw error("unterminated string");
    }

    private Double numberValue() {
        int start = at;
        if (peek('-')) {
            at++;
        }
        while (at < text.length() && "0123456789.eE+-".indexOf(text.charAt(at)) >= 0) {
            at++;
        }
        try {
            return Double.valueOf(text.substring(start, at));
        } catch (NumberFormatException bad) {
            throw error("bad number");
        }
    }

    private Object literal(String word, Object value) {
        if (!text.startsWith(word, at)) {
            throw error("expected '" + word + "'");
        }
        at += word.length();
        return value;
    }

    private void space() {
        while (at < text.length() && Character.isWhitespace(text.charAt(at))) {
            at++;
        }
    }

    private boolean peek(char c) {
        return at < text.length() && text.charAt(at) == c;
    }

    private void expect(char c) {
        if (!peek(c)) {
            throw error("expected '" + c + "'");
        }
        at++;
    }

    private IllegalArgumentException error(String message) {
        return new IllegalArgumentException("invalid JSON at offset " + at + ": " + message);
    }
}
