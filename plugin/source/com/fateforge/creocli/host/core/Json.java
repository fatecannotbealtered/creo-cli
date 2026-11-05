package com.fateforge.creocli.host.core;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A small JSON reader and writer: objects become LinkedHashMap, arrays ArrayList, numbers
 * Long when they are integers and Double otherwise. The host needs nothing more, and the
 * Creo JVM has no JSON library of its own.
 */
public final class Json {
    private final String text;
    private int at;

    private Json(String text) {
        this.text = text;
    }

    public static Object parse(String text) {
        Json reader = new Json(text);
        reader.space();
        Object value = reader.value();
        reader.space();
        if (reader.at != text.length()) {
            throw reader.error("text after the value");
        }
        return value;
    }

    public static Map<String, Object> map(Object... pairs) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) {
            out.put((String) pairs[i], pairs[i + 1]);
        }
        return out;
    }

    // ------------------------------------------------------------------ reading

    private IllegalArgumentException error(String what) {
        return new IllegalArgumentException("bad JSON at " + at + ": " + what);
    }

    private void space() {
        while (at < text.length()) {
            char c = text.charAt(at);
            if (c != ' ' && c != '\t' && c != '\n' && c != '\r') {
                return;
            }
            at++;
        }
    }

    private Object value() {
        if (at >= text.length()) {
            throw error("end of text");
        }
        char c = text.charAt(at);
        switch (c) {
            case '{':
                return object();
            case '[':
                return array();
            case '"':
                return string();
            case 't':
                return word("true", Boolean.TRUE);
            case 'f':
                return word("false", Boolean.FALSE);
            case 'n':
                return word("null", null);
            default:
                if (c == '-' || (c >= '0' && c <= '9')) {
                    return number();
                }
                throw error("unexpected character '" + c + "'");
        }
    }

    private Object word(String word, Object value) {
        if (!text.startsWith(word, at)) {
            throw error("expected " + word);
        }
        at += word.length();
        return value;
    }

    private Map<String, Object> object() {
        Map<String, Object> out = new LinkedHashMap<>();
        at++;
        space();
        if (at < text.length() && text.charAt(at) == '}') {
            at++;
            return out;
        }
        while (true) {
            space();
            if (at >= text.length() || text.charAt(at) != '"') {
                throw error("expected a key");
            }
            String key = string();
            space();
            if (at >= text.length() || text.charAt(at) != ':') {
                throw error("expected ':'");
            }
            at++;
            space();
            out.put(key, value());
            space();
            if (at >= text.length()) {
                throw error("end of text in an object");
            }
            char c = text.charAt(at++);
            if (c == '}') {
                return out;
            }
            if (c != ',') {
                throw error("expected ',' or '}'");
            }
        }
    }

    private List<Object> array() {
        List<Object> out = new ArrayList<>();
        at++;
        space();
        if (at < text.length() && text.charAt(at) == ']') {
            at++;
            return out;
        }
        while (true) {
            space();
            out.add(value());
            space();
            if (at >= text.length()) {
                throw error("end of text in an array");
            }
            char c = text.charAt(at++);
            if (c == ']') {
                return out;
            }
            if (c != ',') {
                throw error("expected ',' or ']'");
            }
        }
    }

    private String string() {
        StringBuilder out = new StringBuilder();
        at++;
        while (true) {
            if (at >= text.length()) {
                throw error("end of text in a string");
            }
            char c = text.charAt(at++);
            if (c == '"') {
                return out.toString();
            }
            if (c == '\\') {
                if (at >= text.length()) {
                    throw error("end of text in an escape");
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
                            throw error("short \\u escape");
                        }
                        out.append((char) Integer.parseInt(text.substring(at, at + 4), 16));
                        at += 4;
                        break;
                    default:
                        throw error("bad escape \\" + e);
                }
            } else if (c < 0x20) {
                throw error("control character in a string");
            } else {
                out.append(c);
            }
        }
    }

    private Object number() {
        int start = at;
        if (text.charAt(at) == '-') {
            at++;
        }
        boolean fraction = false;
        while (at < text.length()) {
            char c = text.charAt(at);
            if (c >= '0' && c <= '9') {
                at++;
            } else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') {
                fraction = true;
                at++;
            } else {
                break;
            }
        }
        String digits = text.substring(start, at);
        try {
            if (!fraction) {
                return Long.parseLong(digits);
            }
            return Double.parseDouble(digits);
        } catch (NumberFormatException bad) {
            throw error("bad number " + digits);
        }
    }

    // ------------------------------------------------------------------ writing

    public static String write(Object value) {
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
            out.append(value.toString());
        } else if (value instanceof Double || value instanceof Float) {
            double d = ((Number) value).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) {
                out.append("null");
            } else if (d == Math.rint(d) && Math.abs(d) < 1e15) {
                out.append((long) d).append(".0");
            } else {
                out.append(Double.toString(d));
            }
        } else if (value instanceof Number) {
            out.append(((Number) value).longValue());
        } else if (value instanceof Map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) value).entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                quote(e.getKey(), out);
                out.append(':');
                write(e.getValue(), out);
            }
            out.append('}');
        } else if (value instanceof Iterable) {
            out.append('[');
            boolean first = true;
            for (Object item : (Iterable<Object>) value) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                write(item, out);
            }
            out.append(']');
        } else {
            quote(value.toString(), out);
        }
    }

    private static void quote(String s, StringBuilder out) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                case '\b': out.append("\\b"); break;
                case '\f': out.append("\\f"); break;
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

    // ------------------------------------------------------------------ typed access

    public static String string(Map<String, Object> m, String key, String otherwise) {
        Object v = m.get(key);
        return v instanceof String ? (String) v : otherwise;
    }

    public static Double number(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof Number ? ((Number) v).doubleValue() : null;
    }

    public static Long integer(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (v instanceof Long || v instanceof Integer) {
            return ((Number) v).longValue();
        }
        if (v instanceof Double && (Double) v == Math.rint((Double) v)) {
            return ((Double) v).longValue();
        }
        return null;
    }

    public static Boolean bool(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof Boolean ? (Boolean) v : null;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> object(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof Map ? (Map<String, Object>) v : new LinkedHashMap<>();
    }
}
