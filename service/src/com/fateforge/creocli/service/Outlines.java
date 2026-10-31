package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Profiles as loops of lines and arcs, in the native library's format: "L x0 y0 x1 y1" per
 * line, "A cx cy r a0 a1" per arc -- counter-clockwise from a0 to a1, in radians, as PTC's
 * own slot example draws them -- and "C cx cy r" per circle. An outer loop first, then the
 * holes inside it. The CLI checks the shapes; this only draws them.
 */
final class Outlines {
    private static final double TOLERANCE = 1e-9;

    private Outlines() {
    }

    /** Every loop of a profile: the outer one, then its holes. */
    static String entities(Map<String, Object> profile) {
        List<String> out = new ArrayList<>(loop(profile));
        Object holes = profile.get("holes");
        if (holes instanceof List) {
            for (Object hole : (List<?>) holes) {
                out.addAll(loop(Json.object(hole, "a hole")));
            }
        }
        return String.join(";", out);
    }

    /**
     * Per entity of entities(profile), the loop it is part of: its type -- "rounded" for a
     * rectangle with rounded corners -- and which loop, 0 the outer one, "slot:1".
     */
    static List<String> loopKinds(Map<String, Object> profile) {
        List<String> out = new ArrayList<>();
        label(profile, 0, out);
        Object holes = profile.get("holes");
        if (holes instanceof List) {
            int index = 1;
            for (Object hole : (List<?>) holes) {
                label(Json.object(hole, "a hole"), index++, out);
            }
        }
        return out;
    }

    private static void label(Map<String, Object> loop, int index, List<String> out) {
        String type = Json.string(loop, "type");
        if ("rectangle".equals(type) && loop.containsKey("corner_radius")) {
            type = "rounded";
        }
        int count = loop(loop).size();
        for (int i = 0; i < count; i++) {
            out.add(type + ":" + index);
        }
    }

    static boolean hasHoles(Map<String, Object> profile) {
        return profile.get("holes") instanceof List && !((List<?>) profile.get("holes")).isEmpty();
    }

    /** One closed loop. */
    static List<String> loop(Map<String, Object> p) {
        String type = Json.string(p, "type");
        double cx = p.containsKey("center") ? coordinate(p, "center", 0) : 0.0;
        double cy = p.containsKey("center") ? coordinate(p, "center", 1) : 0.0;
        List<String> out = new ArrayList<>();
        switch (type) {
            case "circle":
                out.add("C " + cx + " " + cy + " " + Sketches.positive(p, "diameter") / 2);
                return out;
            case "polygon": {
                List<double[]> pts = points(p, "points");
                for (int i = 0; i < pts.size(); i++) {
                    out.add(line(pts.get(i), pts.get((i + 1) % pts.size())));
                }
                return out;
            }
            case "rectangle": {
                double w = Sketches.positive(p, "width") / 2;
                double h = Sketches.positive(p, "height") / 2;
                double r = p.containsKey("corner_radius") ? Sketches.positive(p, "corner_radius") : 0.0;
                double x0 = cx - w, x1 = cx + w, y0 = cy - h, y1 = cy + h;
                if (r <= 0) {
                    double[][] c = {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}};
                    for (int i = 0; i < 4; i++) {
                        out.add(line(c[i], c[(i + 1) % 4]));
                    }
                    return out;
                }
                double half = Math.PI / 2;
                out.add(line(new double[] {x0 + r, y0}, new double[] {x1 - r, y0}));
                out.add(arc(x1 - r, y0 + r, r, -half, half));
                out.add(line(new double[] {x1, y0 + r}, new double[] {x1, y1 - r}));
                out.add(arc(x1 - r, y1 - r, r, 0.0, half));
                out.add(line(new double[] {x1 - r, y1}, new double[] {x0 + r, y1}));
                out.add(arc(x0 + r, y1 - r, r, half, half));
                out.add(line(new double[] {x0, y1 - r}, new double[] {x0, y0 + r}));
                out.add(arc(x0 + r, y0 + r, r, Math.PI, half));
                return out;
            }
            case "slot": {
                List<double[]> c = points(p, "centers");
                double[] a = c.get(0), b = c.get(1);
                double length = Math.hypot(b[0] - a[0], b[1] - a[1]);
                if (c.size() != 2 || length <= TOLERANCE) {
                    throw new Failures.Refusal("E_VALIDATION", "a slot has two different centres");
                }
                double nx = -(b[1] - a[1]) / length, ny = (b[0] - a[0]) / length;
                double r = Sketches.positive(p, "width") / 2;
                double side = Math.atan2(-ny, -nx);
                out.add(line(new double[] {a[0] - nx * r, a[1] - ny * r}, new double[] {b[0] - nx * r, b[1] - ny * r}));
                out.add(arc(b[0], b[1], r, side, Math.PI));
                out.add(line(new double[] {b[0] + nx * r, b[1] + ny * r}, new double[] {a[0] + nx * r, a[1] + ny * r}));
                out.add(arc(a[0], a[1], r, side + Math.PI, Math.PI));
                return out;
            }
            case "outline": {
                double[] start = point(p.get("start"), "'start'");
                double[] at = start;
                Object raw = p.get("segments");
                if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
                    throw new Failures.Refusal("E_VALIDATION", "an outline lists its segments");
                }
                for (Object item : (List<?>) raw) {
                    Map<String, Object> seg = Json.object(item, "a segment");
                    double[] to = point(seg.get("to"), "a segment's 'to'");
                    if (seg.containsKey("sweep")) {
                        out.add(arcThrough(at, to, Math.toRadians(Json.number(seg, "sweep"))));
                    } else if (seg.containsKey("through")) {
                        out.add(spline(at, seg.get("through"), to));
                    } else {
                        out.add(line(at, to));
                    }
                    at = to;
                }
                if (Math.hypot(start[0] - at[0], start[1] - at[1]) > TOLERANCE) {
                    out.add(line(at, start));
                }
                return out;
            }
            default:
                throw new Failures.Refusal("E_VALIDATION", "a loop is a circle, rectangle, polygon, slot or outline, "
                        + "not " + type);
        }
    }

    /**
     * An open chain of lines and arcs -- a sweep's path -- from its start through each
     * segment's "to", an arc where a segment gives the angle it turns ("sweep", degrees).
     */
    static String chain(Map<String, Object> path) {
        double[] at = point(path.get("start"), "'path.start'");
        Object raw = path.get("segments");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "a path lists its segments");
        }
        List<String> out = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            Map<String, Object> seg = Json.object(item, "a segment");
            double[] to = point(seg.get("to"), "a segment's 'to'");
            out.add(seg.containsKey("sweep") ? arcThrough(at, to, Math.toRadians(Json.number(seg, "sweep"))) : line(at, to));
            at = to;
        }
        return String.join(";", out);
    }

    /** Entities mirrored across the sketch's vertical axis: u to -u, arcs still counter-clockwise. */
    static String mirrored(String entities) {
        List<String> out = new ArrayList<>();
        for (String entity : entities.split(";")) {
            String[] p = entity.trim().split("\\s+");
            double[] v = new double[p.length - 1];
            for (int i = 1; i < p.length; i++) {
                v[i - 1] = Double.parseDouble(p[i]);
            }
            switch (p[0]) {
                case "L":
                case "K":
                    out.add(p[0] + " " + -v[0] + " " + v[1] + " " + -v[2] + " " + v[3]);
                    break;
                case "C":
                    out.add("C " + -v[0] + " " + v[1] + " " + v[2]);
                    break;
                case "A":
                    out.add("A " + -v[0] + " " + v[1] + " " + v[2] + " " + (Math.PI - v[4]) + " " + (Math.PI - v[3]));
                    break;
                default:
                    throw new IllegalArgumentException("not an entity: " + entity);
            }
        }
        return String.join(";", out);
    }

    /** Where a path starts and where it ends, in its sketch. */
    static double[][] ends(Map<String, Object> path) {
        chain(path);
        List<?> segments = (List<?>) path.get("segments");
        Map<String, Object> last = Json.object(segments.get(segments.size() - 1), "a segment");
        return new double[][] {point(path.get("start"), "'path.start'"), point(last.get("to"), "a segment's 'to'")};
    }

    /** The arc from one point to another turning through sweep (positive counter-clockwise). */
    private static String arcThrough(double[] from, double[] to, double sweep) {
        double chord = Math.hypot(to[0] - from[0], to[1] - from[1]);
        double mx = (from[0] + to[0]) / 2, my = (from[1] + to[1]) / 2;
        double lx = -(to[1] - from[1]) / chord, ly = (to[0] - from[0]) / chord;
        double d = (chord / 2) / Math.tan(sweep / 2);
        double cx = mx + lx * d, cy = my + ly * d;
        double r = (chord / 2) / Math.abs(Math.sin(sweep / 2));
        return arc(cx, cy, r, Math.atan2(from[1] - cy, from[0] - cx), sweep);
    }

    /** An arc by where it starts and how far it turns, drawn counter-clockwise. */
    private static String arc(double cx, double cy, double r, double t0, double sweep) {
        double a0 = sweep >= 0 ? t0 : t0 + sweep;
        double a1 = sweep >= 0 ? t0 + sweep : t0;
        return "A " + cx + " " + cy + " " + r + " " + a0 + " " + a1;
    }

    /** A spline from one point through others to the last, as the sketcher draws one. */
    private static String spline(double[] from, Object through, double[] to) {
        if (!(through instanceof List) || ((List<?>) through).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "a spline segment goes 'through' one point or more");
        }
        List<?> points = (List<?>) through;
        StringBuilder out = new StringBuilder("S ").append(points.size() + 2).append(' ')
                .append(from[0]).append(' ').append(from[1]);
        for (Object raw : points) {
            double[] p = point(raw, "a spline's 'through' point");
            out.append(' ').append(p[0]).append(' ').append(p[1]);
        }
        return out.append(' ').append(to[0]).append(' ').append(to[1]).toString();
    }

    private static String line(double[] a, double[] b) {
        return "L " + a[0] + " " + a[1] + " " + b[0] + " " + b[1];
    }

    private static List<double[]> points(Map<String, Object> p, String key) {
        Object raw = p.get(key);
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'" + key + "' lists [x, y] points");
        }
        List<double[]> out = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            out.add(point(item, "'" + key + "'"));
        }
        return out;
    }

    private static double[] point(Object raw, String what) {
        if (!(raw instanceof List) || ((List<?>) raw).size() != 2 || !(((List<?>) raw).get(0) instanceof Double)
                || !(((List<?>) raw).get(1) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", what + " is an [x, y] point");
        }
        return new double[] {(Double) ((List<?>) raw).get(0), (Double) ((List<?>) raw).get(1)};
    }

    private static double coordinate(Map<String, Object> p, String key, int index) {
        return point(p.get(key), "'" + key + "'")[index];
    }
}
