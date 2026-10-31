package com.fateforge.creocli.service;

import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSolid.Solid;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * How a native sketch is dimensioned: as a drafter would, before Creo fills in whatever is
 * left. Auto-dimensioning alone reads coincidences as intent. Two edges of a stepped shaft
 * that happen to be 30 long became one length, and a corner that happened to lie level with
 * another edge was held to it, so setting one dimension later moved what the caller never
 * tied together (measured: a shoulder set from 30 to 35 moved both). Given first, these
 * dimensions leave auto-dimensioning nothing to read those coincidences into:
 *
 * <ul>
 * <li>a rectangle by its width and height, centred on centre lines through its centre that
 * are placed from the references -- outside a revolve's sketch;</li>
 * <li>any other edge parallel to a reference by its distance from that reference -- in a
 * revolve's sketch, an edge parallel to the axis by its diameter across it;</li>
 * <li>a corner on no such edge by its distance from each reference it is off, unless an arc
 * meets it tangentially, which places it;</li>
 * <li>an arc by its radius, a circle by its diameter and its centre's distances;</li>
 * <li>where a profile names one number for several things -- a rounded rectangle's corner
 * radius, a slot's width -- one dimension, the rest held equal to it by Creo.</li>
 * </ul>
 *
 * A spline's inner points, and anything else this does not reach, are left to Creo. If the
 * plan over-constrains a sketch the native library drops it and Creo dimensions the sketch
 * alone. Either way the reply says what each dimension measures, and what Creo holds
 * together.
 */
final class SketchPlan {
    private static final double TOLERANCE = 1e-6;
    private static final int LINE_POINT = 2;
    private static final int RADIUS = 3;
    private static final int DIAMETER = 4;
    private static final int LINE_LINE = 5;

    private SketchPlan() {
    }

    /**
     * The entities to draw -- those asked for and any centre lines the plan adds -- with the
     * loop each is part of, the native library's "dims", and what each planned dimension
     * measures, with {rv} and {rh} standing for the references.
     */
    static final class Plan {
        final String entities;
        final List<String> loops;
        final String spec;
        final List<String> measures;

        Plan(String entities, List<String> loops, String spec, List<String> measures) {
            this.entities = entities;
            this.loops = loops;
            this.spec = spec;
            this.measures = measures;
        }
    }

    private static final class Entity {
        final char kind;
        final String loop;
        double[] start;
        double[] end;
        double[] center;
        double radius;
        double a0;
        double a1;

        Entity(char kind, String loop) {
            this.kind = kind;
            this.loop = loop;
        }

        boolean level() {
            return kind == 'L' && Math.abs(end[1] - start[1]) < TOLERANCE;
        }

        boolean upright() {
            return kind == 'L' && Math.abs(end[0] - start[0]) < TOLERANCE;
        }

        /** The direction along the entity at one end, unit length; an arc runs counter-clockwise. */
        double[] tangent(boolean atEnd) {
            if (kind == 'A') {
                double t = atEnd ? a1 : a0;
                return new double[] {-Math.sin(t), Math.cos(t)};
            }
            double dx = end[0] - start[0], dy = end[1] - start[1], n = Math.hypot(dx, dy);
            return new double[] {dx / n, dy / n};
        }
    }

    private static final class Vertex {
        final double x;
        final double y;
        final List<int[]> ends = new ArrayList<>(); // {entity, 0 at its start | 1 at its end}

        Vertex(double x, double y) {
            this.x = x;
            this.y = y;
        }
    }

    /** The planned dimensions and the words for them. */
    private static final class Builder {
        final List<String> specs = new ArrayList<>();
        final List<String> measures = new ArrayList<>();
        final double minX;
        final double minY;
        final double gap;
        int below;
        int left;

        Builder(double minX, double minY, double gap) {
            this.minX = minX;
            this.minY = minY;
            this.gap = gap;
        }

        void add(int type, boolean diameter, double[] text, String measures, String... refs) {
            specs.add(type + " " + (diameter ? "d" : "-") + " " + text[0] + " " + text[1] + " " + String.join(" ", refs));
            this.measures.add(measures);
        }

        /** A distance across the sketch, its text stacked below it. */
        double[] belowAt(double x) {
            return new double[] {x, minY - gap * ++below};
        }

        /** A distance up the sketch, its text stacked to its left. */
        double[] leftAt(double y) {
            return new double[] {minX - gap * ++left, y};
        }
    }

    /**
     * The plan for a sketch's entities, in the native library's format, given the loop each
     * is part of -- its profile type and which loop it is, "slot:1" -- and "axis" for a
     * revolve's centerline. Null when there is nothing to plan.
     */
    static Plan plan(String entities, List<String> loops) {
        List<Entity> list = parse(entities, loops);
        if (list == null || list.isEmpty()) {
            return null;
        }
        List<String> labels = new ArrayList<>();
        for (Entity e : list) {
            labels.add(e.loop);
        }
        // A revolve's axis: diameters are measured across it.
        int axis = -1;
        boolean acrossY = false, acrossX = false;
        double axisAt = 0;
        for (int i = 0; i < list.size(); i++) {
            Entity e = list.get(i);
            if (e.kind == 'K' && "axis".equals(e.loop)) {
                axis = i;
                if (Math.abs(e.end[1] - e.start[1]) < TOLERANCE) {
                    acrossY = true;
                    axisAt = e.start[1];
                } else if (Math.abs(e.end[0] - e.start[0]) < TOLERANCE) {
                    acrossX = true;
                    axisAt = e.start[0];
                }
            }
        }
        double minX = Double.MAX_VALUE, minY = Double.MAX_VALUE, maxX = -Double.MAX_VALUE, maxY = -Double.MAX_VALUE;
        for (Entity e : list) {
            if (e.kind == 'K') {
                continue;
            }
            for (double[] p : e.kind == 'C' || e.kind == 'A'
                    ? new double[][] {{e.center[0] - e.radius, e.center[1] - e.radius},
                                      {e.center[0] + e.radius, e.center[1] + e.radius}}
                    : new double[][] {e.start, e.end}) {
                minX = Math.min(minX, p[0]);
                minY = Math.min(minY, p[1]);
                maxX = Math.max(maxX, p[0]);
                maxY = Math.max(maxY, p[1]);
            }
        }
        if (minX == Double.MAX_VALUE) {
            return null;
        }
        Builder b = new Builder(minX, minY, Math.max(1.0, 0.06 * Math.max(maxX - minX, maxY - minY)));
        String axisRef = axis >= 0 ? "e" + axis : null;
        StringBuilder drawn = new StringBuilder(entities);

        // Rectangles, outside a revolve's sketch: width and height, centred on centre lines.
        Set<Integer> boxed = new HashSet<>();
        if (axis < 0) {
            Map<String, List<Integer>> boxes = new LinkedHashMap<>();
            for (int i = 0; i < list.size(); i++) {
                String loop = list.get(i).loop;
                if (list.get(i).kind == 'L' && (loop.startsWith("rectangle:") || loop.startsWith("rounded:"))) {
                    boxes.computeIfAbsent(loop, k -> new ArrayList<>()).add(i);
                }
            }
            for (Map.Entry<String, List<Integer>> box : boxes.entrySet()) {
                List<Integer> ups = new ArrayList<>(), levels = new ArrayList<>();
                for (int i : box.getValue()) {
                    if (list.get(i).upright()) {
                        ups.add(i);
                    } else if (list.get(i).level()) {
                        levels.add(i);
                    }
                }
                if (ups.size() != 2 || levels.size() != 2) {
                    continue;
                }
                boolean firstLeft = list.get(ups.get(0)).start[0] <= list.get(ups.get(1)).start[0];
                int left = firstLeft ? ups.get(0) : ups.get(1), right = firstLeft ? ups.get(1) : ups.get(0);
                boolean firstLow = list.get(levels.get(0)).start[1] <= list.get(levels.get(1)).start[1];
                int bottom = firstLow ? levels.get(0) : levels.get(1), top = firstLow ? levels.get(1) : levels.get(0);
                double x0 = list.get(left).start[0], x1 = list.get(right).start[0];
                double y0 = list.get(bottom).start[1], y1 = list.get(top).start[1];
                double cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
                String which = "the rectangle centred at " + point(cx, cy);
                int upright = list.size(), level = list.size() + 1;
                Entity uprightLine = centreLine(cx, cy - 1, cx, cy + 1, "centre:" + box.getKey());
                Entity levelLine = centreLine(cx - 1, cy, cx + 1, cy, "centre:" + box.getKey());
                list.add(uprightLine);
                list.add(levelLine);
                labels.add(uprightLine.loop);
                labels.add(levelLine.loop);
                drawn.append(";K ").append(cx).append(' ').append(cy - 1).append(' ').append(cx).append(' ').append(cy + 1);
                drawn.append(";K ").append(cx - 1).append(' ').append(cy).append(' ').append(cx + 1).append(' ').append(cy);
                b.add(LINE_LINE, false, new double[] {cx, y1 + b.gap}, "width of " + which, "e" + left, "e" + right);
                b.add(LINE_LINE, false, new double[] {x1 + b.gap, cy}, "height of " + which, "e" + bottom, "e" + top);
                if (Math.abs(cx) > TOLERANCE) {
                    b.add(LINE_LINE, false, b.belowAt(cx / 2), "distance from {rv} to the centre of " + which, "rv",
                            "e" + upright);
                }
                if (Math.abs(cy) > TOLERANCE) {
                    b.add(LINE_LINE, false, b.leftAt(cy / 2), "distance from {rh} to the centre of " + which, "rh",
                            "e" + level);
                }
                boxed.addAll(box.getValue());
            }
        }

        // Corners where entities meet.
        List<Vertex> vertices = new ArrayList<>();
        Map<String, Vertex> byKey = new LinkedHashMap<>();
        for (int i = 0; i < list.size(); i++) {
            Entity e = list.get(i);
            if (e.kind == 'K' || e.kind == 'C') {
                continue;
            }
            for (int end = 0; end < 2; end++) {
                double[] p = end == 0 ? e.start : e.end;
                String key = Math.round(p[0] / TOLERANCE) + "," + Math.round(p[1] / TOLERANCE);
                Vertex v = byKey.get(key);
                if (v == null) {
                    v = new Vertex(p[0], p[1]);
                    byKey.put(key, v);
                    vertices.add(v);
                }
                v.ends.add(new int[] {i, end});
            }
        }

        // Runs of level edges, and of upright ones: each placed once.
        int[] run = new int[list.size()];
        for (int i = 0; i < run.length; i++) {
            run[i] = i;
        }
        for (Vertex v : vertices) {
            for (int[] a : v.ends) {
                for (int[] c : v.ends) {
                    Entity ea = list.get(a[0]), ec = list.get(c[0]);
                    if (a[0] != c[0] && ((ea.level() && ec.level()) || (ea.upright() && ec.upright()))) {
                        union(run, a[0], c[0]);
                    }
                }
            }
        }
        Map<Integer, List<Integer>> runs = new LinkedHashMap<>();
        for (int i = 0; i < list.size(); i++) {
            Entity e = list.get(i);
            if ((e.level() || e.upright()) && !e.loop.startsWith("slot:") && !boxed.contains(i)) {
                runs.computeIfAbsent(find(run, i), k -> new ArrayList<>()).add(i);
            }
        }
        for (List<Integer> members : runs.values()) {
            Entity first = list.get(members.get(0));
            boolean level = first.level();
            double at = level ? first.start[1] : first.start[0];
            double low = Double.MAX_VALUE, high = -Double.MAX_VALUE;
            for (int i : members) {
                Entity e = list.get(i);
                int along = level ? 0 : 1;
                low = Math.min(low, Math.min(e.start[along], e.end[along]));
                high = Math.max(high, Math.max(e.start[along], e.end[along]));
            }
            Entity only = members.size() == 1 ? first : null;
            String edge = only != null
                    ? "the edge from " + point(only.start[0], only.start[1]) + " to " + point(only.end[0], only.end[1])
                    : "the edge from " + point(level ? low : at, level ? at : low) + " to "
                            + point(level ? high : at, level ? at : high);
            boolean across = level ? acrossY : acrossX;
            String ref = "e" + members.get(0);
            if (across) {
                if (Math.abs(at - axisAt) > TOLERANCE) {
                    // Its text beyond the edge, away from the axis: on the axis Creo draws the
                    // diameter from the axis outward, past the part (measured).
                    double beyond = at + Math.signum(at - axisAt) * b.gap;
                    double[] t = level ? new double[] {(low + high) / 2, beyond} : new double[] {beyond, (low + high) / 2};
                    b.add(LINE_LINE, true, t, "diameter of " + edge + ", across the axis", axisRef, ref);
                }
            } else if (Math.abs(at) > TOLERANCE) {
                b.add(LINE_LINE, false, level ? b.leftAt(at / 2) : b.belowAt(at / 2),
                        "distance from " + (level ? "{rh}" : "{rv}") + " to " + edge, level ? "rh" : "rv", ref);
            }
        }

        // Corners no such edge places -- unless an arc meets them tangentially, which places them.
        for (Vertex v : vertices) {
            boolean onLevel = false, onUpright = false, placed = false;
            for (int[] end : v.ends) {
                Entity e = list.get(end[0]);
                onLevel |= e.level();
                onUpright |= e.upright();
                placed |= e.loop.startsWith("slot:") || e.loop.startsWith("rounded:") || boxed.contains(end[0]);
                for (int[] other : v.ends) {
                    Entity o = list.get(other[0]);
                    if (other[0] == end[0] || e.kind != 'A') {
                        continue;
                    }
                    double[] te = e.tangent(end[1] == 1), to = o.kind == 'S' ? null : o.tangent(other[1] == 1);
                    placed |= to == null || Math.abs(te[0] * to[1] - te[1] * to[0]) < TOLERANCE;
                }
            }
            if (placed) {
                continue;
            }
            int[] at = v.ends.get(0);
            String ref = "e" + at[0] + (at[1] == 0 ? ".s" : ".e");
            String corner = "the corner at " + point(v.x, v.y);
            if (!onUpright) {
                if (acrossX) {
                    if (Math.abs(v.x - axisAt) > TOLERANCE) {
                        b.add(LINE_POINT, true, new double[] {v.x, v.y}, "diameter at " + corner + ", across the axis",
                                axisRef, ref);
                    }
                } else if (Math.abs(v.x) > TOLERANCE) {
                    b.add(LINE_POINT, false, b.belowAt(v.x / 2), "distance from {rv} to " + corner, "rv", ref);
                }
            }
            if (!onLevel) {
                if (acrossY) {
                    if (Math.abs(v.y - axisAt) > TOLERANCE) {
                        b.add(LINE_POINT, true, new double[] {v.x, v.y}, "diameter at " + corner + ", across the axis",
                                axisRef, ref);
                    }
                } else if (Math.abs(v.y) > TOLERANCE) {
                    b.add(LINE_POINT, false, b.leftAt(v.y / 2), "distance from {rh} to " + corner, "rh", ref);
                }
            }
        }

        // Arcs and circles: their sizes, and where circles and a slot's ends sit.
        Set<String> sized = new HashSet<>();
        for (int i = 0; i < list.size(); i++) {
            Entity e = list.get(i);
            if (e.kind != 'A' && e.kind != 'C') {
                continue;
            }
            String ref = "e" + i;
            double reach = e.radius + b.gap;
            if (e.kind == 'C') {
                String circle = "the circle at " + point(e.center[0], e.center[1]);
                b.add(DIAMETER, false, new double[] {e.center[0] + reach * 0.7071, e.center[1] + reach * 0.7071},
                        "diameter of " + circle, ref);
                centre(b, e, ref + ".c", "the centre of " + circle, acrossX, acrossY, axisAt, axisRef);
            } else if (e.loop.startsWith("slot:")) {
                if (sized.add(e.loop)) {
                    double mid = (e.a0 + e.a1) / 2;
                    b.add(DIAMETER, false, new double[] {e.center[0] + reach * Math.cos(mid), e.center[1] + reach * Math.sin(mid)},
                            "width of the slot, both ends held equal to it", ref);
                }
                centre(b, e, ref + ".c", "the centre of the slot's end at " + point(e.center[0], e.center[1]), acrossX,
                        acrossY, axisAt, axisRef);
            } else if (e.loop.startsWith("rounded:")) {
                if (sized.add(e.loop)) {
                    double mid = (e.a0 + e.a1) / 2;
                    b.add(RADIUS, false, new double[] {e.center[0] + reach * Math.cos(mid), e.center[1] + reach * Math.sin(mid)},
                            "radius of the rectangle's corners, all four held equal to it", ref);
                }
            } else {
                double mid = (e.a0 + e.a1) / 2;
                b.add(RADIUS, false, new double[] {e.center[0] + reach * Math.cos(mid), e.center[1] + reach * Math.sin(mid)},
                        "radius of the arc from " + point(e.start[0], e.start[1]) + " to " + point(e.end[0], e.end[1]), ref);
            }
        }
        if (b.specs.isEmpty()) {
            return null;
        }
        return new Plan(drawn.toString(), labels, String.join(";", b.specs), b.measures);
    }

    private static Entity centreLine(double x0, double y0, double x1, double y1, String loop) {
        Entity e = new Entity('K', loop);
        e.start = new double[] {x0, y0};
        e.end = new double[] {x1, y1};
        return e;
    }

    private static void centre(Builder b, Entity e, String ref, String what, boolean acrossX, boolean acrossY,
                               double axisAt, String axisRef) {
        double x = e.center[0], y = e.center[1];
        if (acrossX) {
            if (Math.abs(x - axisAt) > TOLERANCE) {
                b.add(LINE_POINT, true, new double[] {x, y}, "diameter at " + what + ", across the axis", axisRef, ref);
            }
        } else if (Math.abs(x) > TOLERANCE) {
            b.add(LINE_POINT, false, b.belowAt(x / 2), "distance from {rv} to " + what, "rv", ref);
        }
        if (acrossY) {
            if (Math.abs(y - axisAt) > TOLERANCE) {
                b.add(LINE_POINT, true, new double[] {x, y}, "diameter at " + what + ", across the axis", axisRef, ref);
            }
        } else if (Math.abs(y) > TOLERANCE) {
            b.add(LINE_POINT, false, b.leftAt(y / 2), "distance from {rh} to " + what, "rh", ref);
        }
    }

    private static int find(int[] parent, int i) {
        while (parent[i] != i) {
            parent[i] = parent[parent[i]];
            i = parent[i];
        }
        return i;
    }

    private static void union(int[] parent, int a, int b) {
        int ra = find(parent, a), rb = find(parent, b);
        if (ra != rb) {
            parent[Math.max(ra, rb)] = Math.min(ra, rb);
        }
    }

    private static List<Entity> parse(String entities, List<String> loops) {
        if (entities == null || entities.trim().isEmpty()) {
            return null;
        }
        String[] specs = entities.split(";");
        List<Entity> out = new ArrayList<>();
        for (int i = 0; i < specs.length; i++) {
            String[] t = specs[i].trim().split("\\s+");
            if (t[0].isEmpty()) {
                return null;
            }
            char kind = t[0].charAt(0);
            String loop = loops != null && i < loops.size() ? loops.get(i) : kind == 'K' ? "axis" : "outline:0";
            Entity e = new Entity(kind, loop);
            try {
                switch (kind) {
                    case 'L':
                    case 'K':
                        e.start = new double[] {Double.parseDouble(t[1]), Double.parseDouble(t[2])};
                        e.end = new double[] {Double.parseDouble(t[3]), Double.parseDouble(t[4])};
                        break;
                    case 'C':
                        e.center = new double[] {Double.parseDouble(t[1]), Double.parseDouble(t[2])};
                        e.radius = Double.parseDouble(t[3]);
                        break;
                    case 'A':
                        e.center = new double[] {Double.parseDouble(t[1]), Double.parseDouble(t[2])};
                        e.radius = Double.parseDouble(t[3]);
                        e.a0 = Double.parseDouble(t[4]);
                        e.a1 = Double.parseDouble(t[5]);
                        e.start = new double[] {e.center[0] + e.radius * Math.cos(e.a0), e.center[1] + e.radius * Math.sin(e.a0)};
                        e.end = new double[] {e.center[0] + e.radius * Math.cos(e.a1), e.center[1] + e.radius * Math.sin(e.a1)};
                        break;
                    case 'S': {
                        int n = Integer.parseInt(t[1]);
                        e.start = new double[] {Double.parseDouble(t[2]), Double.parseDouble(t[3])};
                        e.end = new double[] {Double.parseDouble(t[2 * n]), Double.parseDouble(t[2 * n + 1])};
                        break;
                    }
                    default:
                        return null;
                }
            } catch (RuntimeException unreadable) {
                return null;
            }
            out.add(e);
        }
        return out;
    }

    // ------------------------------------------------------------------ the reply

    /**
     * The native report turned into what a caller can act on: each of the feature's sketch
     * dimensions by name, its value and what it measures, and what Creo holds together. The
     * native library's raw read-back is taken out of the report.
     */
    static Map<String, Object> describe(Plan plan, Map<String, Object> report, Feature feature, String entities,
                                        List<String> references) throws Exception {
        Object dimsRead = report.remove("dims_read");
        Object idsRead = report.remove("dim_ids");
        Object constraintsRead = report.remove("constraints");
        Object planned = report.remove("planned");
        Object dropped = report.remove("plan_dropped");
        Object verticalRef = report.remove("vertical_ref");
        List<String> names = references == null ? new ArrayList<>() : new ArrayList<>(references);
        int vertical = verticalRef instanceof Integer ? (Integer) verticalRef : -1;
        String rv = vertical >= 0 && vertical < names.size() ? names.get(vertical) : "the upright reference";
        String rh = vertical >= 0 && names.size() == 2 ? names.get(1 - vertical) : "the level reference";
        List<Entity> list = plan != null ? parse(plan.entities, plan.loops) : parse(entities, null);
        Map<String, Entity> known = new HashMap<>();
        for (int i = 0; list != null && i < list.size(); i++) {
            known.put("e" + i, list.get(i));
        }
        for (int k = 0; k < names.size(); k++) {
            known.put("r" + k, new Entity('R', names.get(k)));
        }

        // Section dimension -> what the plan said it measures.
        Map<Integer, String> meant = new HashMap<>();
        if (plan != null && planned instanceof String && !((String) planned).isEmpty()) {
            String[] made = ((String) planned).split(",");
            for (int i = 0; i < made.length && i < plan.measures.size(); i++) {
                if (!made[i].startsWith("x")) {
                    meant.put(Integer.parseInt(made[i].trim()),
                            plan.measures.get(i).replace("{rv}", rv).replace("{rh}", rh));
                }
            }
        }
        Map<Integer, BaseDimension> byId = dimensionsOf(feature);
        Map<Integer, Integer> toModel = pairs(idsRead);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (String[] t : rows(dimsRead)) {
            Integer model = toModel.get(Integer.parseInt(t[0]));
            BaseDimension dim = model == null ? null : byId.get(model);
            if (dim == null) {
                continue;
            }
            String what = meant.get(Integer.parseInt(t[0]));
            boolean ours = what != null;
            if (!ours) {
                what = measure(t, known) + " (chosen by Creo)";
            }
            rows.add(Json.map("name", dim.GetSymbol(), "value", Dimensions.clean(dim.GetDimValue()),
                    "measures", what, "by", ours ? "cli" : "creo"));
        }
        rows.sort((a, c) -> Integer.compare(symbolNumber(a.get("name")), symbolNumber(c.get("name"))));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("sketch_dimensions", rows);
        out.put("held_together", held(constraintsRead, known));
        out.put("dimension_plan", dropped != null ? "dropped, Creo dimensioned the sketch alone: " + dropped
                : plan == null ? "none needed" : "kept");
        return out;
    }

    /**
     * What each sketch dimension of an existing feature measures, by model dimension id --
     * however the sketch was made, by this service or by a person -- read from the feature by
     * the native library, which changes nothing. Empty when there is no sketch it can read.
     */
    static Read read(Solid solid, Feature feature) {
        Read out = new Read();
        if (Service.sketchLibrary() == null) {
            return out;
        }
        String steps = "describe,locate";
        boolean rib = false;
        try {
            rib = "FEATTYPE_RIB".equals(Creo.enumName(feature.GetFeatType()));
            if (rib)
                steps += ",projection_refs";
        } catch (Throwable unavailable) {
            out.observation = Json.map("complete", false, "error", Failures.error(unavailable));
            return out;
        }
        Map<String, Object> report = null;
        List<Object> attempts = new ArrayList<>();
        // An extrusion's or revolve's sketch, a rib's, a sweep's section: each where its tree
        // keeps it; the first that answers is read.
        for (String path : rib ? new String[] {Ribs.SKETCHER_PATH}
                : new String[] {null, Ribs.SKETCHER_PATH, Sweeps.SECTION_PATH}) {
            try {
                report = Sketches.drawNatively(solid, feature, "", new ArrayList<>(), 0, steps, path,
                        false, null);
                if (rib) report.put("read_path", path);
                break;
            } catch (Exception elsewhere) {
                Map<String, Object> error = Failures.error(elsewhere);
                attempts.add(Json.map("path", path, "error", error));
                if (rib) {
                    out.observation = new LinkedHashMap<>();
                    Object nativeReport = error.get("native");
                    if (nativeReport instanceof Map)
                        out.observation.putAll(Json.object(nativeReport, "native sketch readback error"));
                    out.observation.put("complete", false);
                    out.observation.put("read_path", path);
                    out.observation.put("error", error);
                    out.observation.put("attempts", attempts);
                    return out;
                }
            }
        }
        if (report == null) {
            return out;
        }
        out.observation = new LinkedHashMap<>(report);
        if (rib) out.observation.put("complete", true);
        double[] offset = new double[2];
        Map<String, Entity> known = sectionEntities(report.get("entities_read"), offset);
        double[][] frame = location(report.get("location"));
        Map<Integer, Integer> toModel = pairs(report.get("dim_ids"));
        for (String[] t : rows(report.get("dims_read"))) {
            Integer model = toModel.get(Integer.parseInt(t[0]));
            if (model != null) {
                out.measures.put(model, measure(t, known));
                double[][] anchor = frame == null || !"1".equals(t[2]) ? null : anchor(t, known, offset, frame);
                if (anchor != null) {
                    out.anchors.put(model, anchor);
                }
            }
        }
        out.held.addAll(held(report.get("constraints"), known));
        return out;
    }

    /** An existing sketch read: what each model dimension measures, and what is held together. */
    static final class Read {
        /** Raw getter provenance; a successful task must check its required fields. */
        Map<String, Object> observation;
        final Map<Integer, String> measures = new HashMap<>();
        final List<Map<String, Object>> held = new ArrayList<>();
        /**
         * Per diameter across a revolve's axis, in the model: where its text sits on a turned
         * part's drawing -- halfway between the axis and the edge it measures, over that edge
         * -- and the axis's direction.
         */
        final Map<Integer, double[][]> anchors = new HashMap<>();
    }

    /** The section's x and y axes and origin in the model, from the locate step. */
    private static double[][] location(Object read) {
        if (!(read instanceof String)) {
            return null;
        }
        String[] t = ((String) read).trim().split("\\s+");
        if (t.length != 12) {
            return null;
        }
        double[] v = new double[12];
        for (int i = 0; i < 12; i++) {
            v[i] = Double.parseDouble(t[i]);
        }
        return new double[][] {{v[0], v[1], v[2]}, {v[3], v[4], v[5]}, {v[9], v[10], v[11]}};
    }

    /** A diameter's text place and the axis's direction, in the model; null if not one. */
    private static double[][] anchor(String[] t, Map<String, Entity> known, double[] offset, double[][] frame) {
        Entity axis = null, measured = null;
        int point = 1;
        for (int r = 4; r < t.length; r++) {
            String[] p = t[r].split("\\.");
            Entity e = known.get(p[0]);
            if (e == null) {
                continue;
            }
            if (e.kind == 'K') {
                axis = e;
            } else if (measured == null) {
                measured = e;
                point = p.length > 1 ? Integer.parseInt(p[1]) : 1;
            }
        }
        if (axis == null || measured == null || measured.start == null) {
            return null;
        }
        double[] a = point == 2 ? measured.start : point == 3 ? measured.end
                : new double[] {(measured.start[0] + measured.end[0]) / 2, (measured.start[1] + measured.end[1]) / 2};
        double dx = axis.end[0] - axis.start[0], dy = axis.end[1] - axis.start[1], n = Math.hypot(dx, dy);
        if (n == 0) {
            return null;
        }
        double s = ((a[0] - axis.start[0]) * dx + (a[1] - axis.start[1]) * dy) / (n * n);
        double[] foot = {axis.start[0] + s * dx, axis.start[1] + s * dy};
        double u = (a[0] + foot[0]) / 2 + offset[0], v = (a[1] + foot[1]) / 2 + offset[1];
        double[] at = new double[3], along = new double[3];
        for (int i = 0; i < 3; i++) {
            at[i] = frame[2][i] + u * frame[0][i] + v * frame[1][i];
            along[i] = (dx * frame[0][i] + dy * frame[1][i]) / n;
        }
        return new double[][] {at, along};
    }

    /**
     * A sketch's entities as the describe step reads them, in the section's own coordinates,
     * moved so that the references cross at the origin, as the sketch was drawn.
     */
    private static Map<String, Entity> sectionEntities(Object read) {
        return sectionEntities(read, new double[2]);
    }

    /** The same, with where the references cross in the section written into offset. */
    private static Map<String, Entity> sectionEntities(Object read, double[] offset) {
        Map<String, Entity> known = new LinkedHashMap<>();
        if (!(read instanceof String)) {
            return known;
        }
        List<Entity> projections = new ArrayList<>();
        for (String one : ((String) read).split(";")) {
            String[] t = one.trim().split("\\s+");
            if (t.length < 2 || !t[0].startsWith("#") || t[1].isEmpty()) {
                continue;
            }
            char kind = t[1].charAt(0);
            try {
                Entity e;
                switch (kind) {
                    case 'R':
                    case 'L':
                    case 'K':
                        e = new Entity(kind, kind == 'R' ? (t.length > 6 ? t[6] : "a reference")
                                : kind == 'K' ? "centre line" : "outline:0");
                        e.start = new double[] {Double.parseDouble(t[2]), Double.parseDouble(t[3])};
                        e.end = new double[] {Double.parseDouble(t[4]), Double.parseDouble(t[5])};
                        if (kind == 'R') {
                            projections.add(e);
                        }
                        break;
                    case 'A':
                        e = new Entity('A', "outline:0");
                        e.center = new double[] {Double.parseDouble(t[2]), Double.parseDouble(t[3])};
                        e.radius = Double.parseDouble(t[4]);
                        e.a0 = Double.parseDouble(t[5]);
                        e.a1 = Double.parseDouble(t[6]);
                        break;
                    case 'C':
                        e = new Entity('C', "outline:0");
                        e.center = new double[] {Double.parseDouble(t[2]), Double.parseDouble(t[3])};
                        e.radius = Double.parseDouble(t[4]);
                        break;
                    case 'S':
                        e = new Entity('S', "outline:0");
                        e.start = new double[] {Double.parseDouble(t[3]), Double.parseDouble(t[4])};
                        e.end = new double[] {Double.parseDouble(t[5]), Double.parseDouble(t[6])};
                        break;
                    default:
                        continue;
                }
                known.put(t[0], e);
            } catch (RuntimeException unreadable) {
                // An entity this cannot read is named "another entity".
            }
        }
        double[] origin = crossing(projections);
        offset[0] = origin[0];
        offset[1] = origin[1];
        for (Entity e : known.values()) {
            for (double[] p : new double[][] {e.start, e.end, e.center}) {
                if (p != null) {
                    p[0] -= origin[0];
                    p[1] -= origin[1];
                }
            }
            if (e.kind == 'A') {
                e.start = new double[] {e.center[0] + e.radius * Math.cos(e.a0), e.center[1] + e.radius * Math.sin(e.a0)};
                e.end = new double[] {e.center[0] + e.radius * Math.cos(e.a1), e.center[1] + e.radius * Math.sin(e.a1)};
            }
        }
        return known;
    }

    /** Where the first two references that are not parallel cross; the section's origin else. */
    private static double[] crossing(List<Entity> lines) {
        for (int i = 0; i < lines.size(); i++) {
            for (int j = i + 1; j < lines.size(); j++) {
                Entity a = lines.get(i), b = lines.get(j);
                double ax = a.end[0] - a.start[0], ay = a.end[1] - a.start[1];
                double bx = b.end[0] - b.start[0], by = b.end[1] - b.start[1];
                double cross = ax * by - ay * bx;
                if (Math.abs(cross) < TOLERANCE * Math.hypot(ax, ay) * Math.hypot(bx, by)) {
                    continue;
                }
                double t = ((b.start[0] - a.start[0]) * by - (b.start[1] - a.start[1]) * bx) / cross;
                return new double[] {a.start[0] + t * ax, a.start[1] + t * ay};
            }
        }
        return new double[] {0, 0};
    }

    private static Map<Integer, BaseDimension> dimensionsOf(Feature feature) throws Exception {
        Map<Integer, BaseDimension> byId = new HashMap<>();
        ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
            byId.put(dims.get(i).GetId(), (BaseDimension) dims.get(i));
        }
        return byId;
    }

    /** "section:model,..." as read back. */
    private static Map<Integer, Integer> pairs(Object read) {
        Map<Integer, Integer> out = new HashMap<>();
        if (read instanceof String) {
            for (String pair : ((String) read).split(",")) {
                String[] p = pair.split(":");
                if (p.length == 2) {
                    try {
                        out.put(Integer.parseInt(p[0].trim()), Integer.parseInt(p[1].trim()));
                    } catch (NumberFormatException unreadable) {
                        // skipped
                    }
                }
            }
        }
        return out;
    }

    /** Each dimension read back: "<id> <type> <diameter> <value> <ref>.<point>...". */
    private static List<String[]> rows(Object read) {
        List<String[]> out = new ArrayList<>();
        if (read instanceof String) {
            for (String one : ((String) read).split(";")) {
                String[] t = one.trim().split("\\s+");
                if (t.length >= 4 && t[0].matches("\\d+")) {
                    out.add(t);
                }
            }
        }
        return out;
    }

    private static List<Map<String, Object>> held(Object read, Map<String, Entity> known) {
        List<Map<String, Object>> held = new ArrayList<>();
        if (!(read instanceof String)) {
            return held;
        }
        for (String one : ((String) read).split(";")) {
            String[] t = one.trim().split("\\s+");
            if (t.length < 2) {
                continue;
            }
            String tie = tie(Integer.parseInt(t[0]), t, known);
            if (tie == null) {
                continue;
            }
            List<String> between = new ArrayList<>();
            for (int r = 1; r < t.length; r++) {
                between.add(name(t[r], known));
            }
            held.add(Json.map("held", tie, "between", between));
        }
        return held;
    }

    private static int symbolNumber(Object symbol) {
        try {
            return Integer.parseInt(String.valueOf(symbol).replaceAll("\\D", ""));
        } catch (NumberFormatException none) {
            return Integer.MAX_VALUE;
        }
    }

    /**
     * What Creo holds together that ties one number to another: an equality, a corner held
     * on another edge. Points held on references, the axis or a rectangle's centre lines are
     * where the caller drew them; tangency and the like are the shape itself.
     */
    private static String tie(int type, String[] t, Map<String, Entity> known) {
        String kind;
        switch (type) {
            case 3:
                kind = "a point held on another entity";
                break;
            case 6:
                kind = "equal radii";
                break;
            case 8:
                kind = "equal lengths";
                break;
            case 9:
                kind = "collinear";
                break;
            case 14:
                kind = "symmetric";
                break;
            case 17:
                kind = "the same point";
                break;
            case 30:
                kind = "level with each other";
                break;
            case 31:
                kind = "upright from each other";
                break;
            case 35:
                kind = "a point held at a midpoint";
                break;
            case 36:
                kind = "equal curvature";
                break;
            default:
                return null;
        }
        for (int r = 1; r < t.length; r++) {
            Entity e = known.get(t[r].split("\\.")[0]);
            if (e == null || e.kind == 'R' || e.kind == 'K') {
                return null; // held to a reference, the axis or a centre line
            }
        }
        return kind;
    }

    /** What a dimension read back measures, from its type and what it references. */
    private static String measure(String[] t, Map<String, Entity> known) {
        int type = Integer.parseInt(t[1]);
        boolean diameter = "1".equals(t[2]);
        List<String> refs = new ArrayList<>();
        String other = null;
        for (int r = 4; r < t.length; r++) {
            String named = name(t[r], known);
            refs.add(named);
            Entity e = known.get(t[r].split("\\.")[0]);
            if (other == null && (e == null || e.kind != 'K')) {
                other = named;
            }
        }
        String a = refs.isEmpty() ? "?" : refs.get(0), c = refs.size() > 1 ? refs.get(1) : "?";
        if (diameter) {
            String across = other == null ? a : other;
            return (across.startsWith("the corner") || across.startsWith("the centre") ? "diameter at " : "diameter of ")
                    + across + ", across the axis";
        }
        switch (type) {
            case 1:
                return "length of " + a;
            case 3:
                return "radius of " + a;
            case 4:
                return "diameter of " + a;
            case 2:
            case 5:
            case 6:
                return "distance from " + a + " to " + c;
            case 7:
                return "horizontal distance from " + a + " to " + c;
            case 8:
                return "vertical distance from " + a + " to " + c;
            case 11:
                return "angle of " + a;
            case 12:
                return "angle between " + a + " and " + c;
            default:
                return "a dimension of " + String.join(" and ", refs);
        }
    }

    /** An entity, or a point of one, as the reply names it: by where it is in the sketch. */
    private static String name(String ref, Map<String, Entity> known) {
        String[] p = ref.split("\\.");
        int point = 1;
        try {
            point = p.length > 1 ? Integer.parseInt(p[1]) : 1;
        } catch (NumberFormatException whole) {
            // the whole entity
        }
        Entity e = known.get(p[0]);
        if (e == null) {
            return "another entity";
        }
        if (e.kind == 'R') {
            return e.loop;
        }
        if (e.kind == 'K') {
            boolean upright = Math.abs(e.end[0] - e.start[0]) < TOLERANCE;
            boolean level = Math.abs(e.end[1] - e.start[1]) < TOLERANCE;
            if (e.loop.startsWith("centre:")) {
                return "the " + (upright ? "upright" : "level") + " centre line of the rectangle centred at "
                        + point((e.start[0] + e.end[0]) / 2, (e.start[1] + e.end[1]) / 2);
            }
            if ("axis".equals(e.loop)) {
                return "the axis";
            }
            return upright ? "the upright centre line at x = " + number(e.start[0])
                    : level ? "the level centre line at y = " + number(e.start[1])
                    : "the centre line through " + point(e.start[0], e.start[1]) + " and " + point(e.end[0], e.end[1]);
        }
        if (point == 2 && e.start != null) {
            return "the corner at " + point(e.start[0], e.start[1]);
        }
        if (point == 3 && e.end != null) {
            return "the corner at " + point(e.end[0], e.end[1]);
        }
        if (point == 4 && e.center != null) {
            return "the centre of " + name(p[0], known);
        }
        switch (e.kind) {
            case 'L':
                return "the edge from " + point(e.start[0], e.start[1]) + " to " + point(e.end[0], e.end[1]);
            case 'A':
                return "the arc from " + point(e.start[0], e.start[1]) + " to " + point(e.end[0], e.end[1]);
            case 'C':
                return "the circle at " + point(e.center[0], e.center[1]);
            case 'S':
                return "the spline from " + point(e.start[0], e.start[1]) + " to " + point(e.end[0], e.end[1]);
            default:
                return "another entity";
        }
    }

    static String point(double x, double y) {
        return "(" + number(x) + ", " + number(y) + ")";
    }

    private static String number(double v) {
        double r = Math.round(v * 1e6) / 1e6;
        if (r == Math.rint(r) && Math.abs(r) < 1e15) {
            return Long.toString((long) r == 0 ? 0 : (long) r);
        }
        return java.math.BigDecimal.valueOf(r).stripTrailingZeros().toPlainString();
    }
}
