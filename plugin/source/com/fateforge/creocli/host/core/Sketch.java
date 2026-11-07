package com.fateforge.creocli.host.core;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * A sketch as the Agent writes it (the --sketch JSON of extrude create and the like), checked
 * and turned into the program the C library builds the section from (ccn_sketch in
 * creo_cli_native.c).
 *
 * <p>The JSON names a sketch plane, the model axis the sketch's x axis runs along, the
 * references to project, entities (profiles such as rectangles, and lines, arcs, circles,
 * centerlines and points), constraints and dimensions, each dimension with an optional name.
 * Coordinates are in millimetres in the sketch frame: its origin is the model origin projected
 * onto the plane, x runs along {@code x_axis}, y is the plane's normal crossed with x.
 *
 * <p>Creo's intent manager needs every constraint stated, so a profile is expanded into its
 * entities with all the constraints that make it that profile, and a sketch that leaves a
 * freedom open ends with weak dimensions. The profiles' freedoms are checked here before
 * Creo is asked, so that the preview lists what is missing.
 */
public final class Sketch {
    /** A plane the sketch can lie on or refer to: a datum plane or a planar face. */
    public static final class Plane {
        public final String name;
        public final int surfaceId;
        public final double[] point;
        public final double[] normal;

        public Plane(String name, int surfaceId, double[] point, double[] normal) {
            this.name = name;
            this.surfaceId = surfaceId;
            this.point = point;
            this.normal = normal;
        }
    }

    /** Finds the plane a name stands for: a datum name, surface:<id>, or a feature's face such as BASE/end. */
    public interface Planes {
        Plane find(String name) throws Exception;
    }

    private static final Pattern ID = Pattern.compile("[A-Za-z][A-Za-z0-9_]{0,30}");
    private static final Pattern DIM_NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_]{0,30}");
    private static final double EPS = 1e-6;
    // ProConstraintType and ProSecdimType of Creo TOOLKIT.
    private static final int SAME_POINT = 0, HORIZONTAL = 1, VERTICAL = 2, POINT_ON = 3, TANGENT = 4, PERPENDICULAR = 5,
            EQUAL_RADII = 6, PARALLEL = 7, EQUAL_LENGTH = 8, COLLINEAR = 9, SYMMETRY = 14;
    private static final int DIM_LINE = 1, DIM_LINE_POINT = 2, DIM_RADIUS = 3, DIM_DIAMETER = 4, DIM_LINE_LINE = 5,
            DIM_POINT_POINT = 6;

    public final Plane plane;
    /** The sketch frame in model units: origin, x axis, y axis, normal. */
    public final double[] origin;
    public final double[] x;
    public final double[] y;
    public final double[] normal;
    public final String xAxis;
    public final List<String> problems = new ArrayList<>();
    public final List<String> dimensionNames = new ArrayList<>();
    /** The value in millimetres of each named dimension, by its name as written. */
    public final Map<String, Double> namedValues = new LinkedHashMap<>();
    public final Map<String, Plane> references = new LinkedHashMap<>();

    private final double mmPerUnit;
    private final List<String> program = new ArrayList<>();
    private final Map<String, Map<String, Object>> entities = new LinkedHashMap<>();
    private final Map<String, String> kinds = new LinkedHashMap<>();
    /** A reference's trace in the sketch: 'x' for a line x = c, 'y' for a line y = c, and c. */
    private final Map<String, Object[]> traces = new LinkedHashMap<>();
    private final Set<String> axesMade = new LinkedHashSet<>();
    private final Map<String, double[]> centers = new LinkedHashMap<>();
    private final Map<String, Set<String>> fixed = new LinkedHashMap<>();
    /** The sketch axes ('x', 'y') on which each profile's center is placed by center_mm, a constraint or a dimension. */
    private final Map<String, Set<Character>> placed = new LinkedHashMap<>();
    /** Profiles whose centers mirror each other about a reference or centerline: {a, b, about}. */
    private final List<String[]> mirrors = new ArrayList<>();
    /** Circles made equal: {a, b}; one's size fixes the other's. */
    private final List<String[]> sameSize = new ArrayList<>();
    /** How many geometry centerlines (type axis) the sketch has: a revolve needs exactly one. */
    public int axes;

    private Sketch(Plane plane, double[] x, String xAxis, double mmPerUnit) {
        this.plane = plane;
        this.mmPerUnit = mmPerUnit;
        this.xAxis = xAxis;
        this.normal = unit(plane.normal);
        this.x = x;
        this.y = cross(normal, x);
        double d = dot(plane.point, normal);
        this.origin = new double[] {d * normal[0], d * normal[1], d * normal[2]};
    }

    /** Reads and checks the --sketch value; what Creo would refuse goes into {@link #problems}. */
    public static Sketch read(Object value, Planes planes, double mmPerUnit) throws Exception {
        if (!(value instanceof Map)) {
            throw new HostError(HostError.VALIDATION, "--sketch must be a JSON object with plane, x_axis, entities and dimensions.");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> spec = (Map<String, Object>) value;
        String planeName = Json.string(spec, "plane", null);
        if (planeName == null) {
            throw new HostError(HostError.VALIDATION, "--sketch needs plane: a datum such as TOP, or a face such as BASE/end.");
        }
        Plane plane = planes.find(planeName);
        String xAxis = Json.string(spec, "x_axis", null);
        double[] x = axis(xAxis);
        if (x == null) {
            throw new HostError(HostError.VALIDATION, "--sketch needs x_axis: the model axis the sketch's x runs along, such as +x.");
        }
        if (Math.abs(dot(x, unit(plane.normal))) > EPS) {
            throw new HostError(HostError.VALIDATION, "x_axis " + xAxis + " does not lie in the plane " + planeName
                    + "; choose a model axis along the plane.");
        }
        Sketch sketch = new Sketch(plane, x, xAxis, mmPerUnit);
        sketch.parse(spec, planes);
        return sketch;
    }

    /** The program for ccn_sketch. */
    public String program() {
        return String.join("\n", program) + "\n";
    }

    // ------------------------------------------------------------------ parsing

    private void parse(Map<String, Object> spec, Planes planes) throws Exception {
        program.add("frame " + num(origin[0]) + " " + num(origin[1]) + " " + num(origin[2]) + " " + num(x[0]) + " "
                + num(x[1]) + " " + num(x[2]) + " " + num(y[0]) + " " + num(y[1]) + " " + num(y[2]));
        for (Object r : list(spec, "references")) {
            String name = String.valueOf(r);
            reference(name, planes);
        }
        for (Object e : list(spec, "entities")) {
            if (!(e instanceof Map)) {
                problems.add("Each entity is an object with id and type.");
                continue;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> entity = (Map<String, Object>) e;
            String id = Json.string(entity, "id", null);
            String type = Json.string(entity, "type", null);
            if (id == null || !ID.matcher(id).matches()) {
                problems.add("Entity id " + id + " must be a letter followed by letters, digits or _.");
                continue;
            }
            if (entities.containsKey(id) || references.containsKey(id)) {
                problems.add("Two entities or references are named " + id + ".");
                continue;
            }
            if (type == null) {
                problems.add("Entity " + id + " has no type.");
                continue;
            }
            entities.put(id, entity);
            kinds.put(id, type);
            fixed.put(id, new LinkedHashSet<>());
        }
        List<Map<String, Object>> constraints = objects(spec, "constraints");
        List<Map<String, Object>> dimensions = objects(spec, "dimensions");
        // Profiles are placed from their constraints and dimensions before they are written.
        for (Map<String, Object> c : constraints) {
            place(c);
        }
        for (Map<String, Object> d : dimensions) {
            placeByDimension(d);
        }
        placeMirrors();
        for (Map.Entry<String, Map<String, Object>> e : entities.entrySet()) {
            write(e.getKey(), kinds.get(e.getKey()), e.getValue());
        }
        for (Map<String, Object> c : constraints) {
            constrain(c);
        }
        for (Map<String, Object> d : dimensions) {
            dimension(d);
        }
        passFreedoms();
        for (Map.Entry<String, Set<String>> e : fixed.entrySet()) {
            if (e.getValue().remove("square")) {
                e.getValue().add(e.getValue().contains("width") ? "height" : "width");
            }
            String kind = kinds.get(e.getKey());
            List<String> missing = new ArrayList<>();
            for (String freedom : freedoms(kind, entities.get(e.getKey()))) {
                if (!e.getValue().contains(freedom)) {
                    missing.add(freedom);
                }
            }
            if (!missing.isEmpty()) {
                problems.add(e.getKey() + " is not fully defined: nothing fixes its " + String.join(", ", missing)
                        + ". Add a dimension or a symmetric constraint for each.");
            }
        }
    }

    /** The freedoms of a profile the checker follows; other entities are left to Creo. */
    private static List<String> freedoms(String kind, Map<String, Object> entity) {
        List<String> out = new ArrayList<>();
        if ("rectangle".equals(kind)) {
            out.add("x position");
            out.add("y position");
            out.add("width");
            out.add("height");
            if (positive(entity, "corner_radius_mm")) {
                out.add("corner radius");
            }
        } else if ("circle".equals(kind)) {
            out.add("x position");
            out.add("y position");
            out.add("size");
        }
        return out;
    }

    private void reference(String name, Planes planes) throws Exception {
        if (references.containsKey(name)) {
            return;
        }
        Plane p = planes.find(name);
        double[] n = unit(p.normal);
        if (Math.abs(dot(n, normal)) > 1 - EPS) {
            problems.add("The reference " + name + " is parallel to the sketch plane; only planes across it project to a line.");
            return;
        }
        references.put(name, p);
        program.add("ref " + token(name) + " " + p.surfaceId);
        double[] rel = minus(p.point, origin);
        if (Math.abs(Math.abs(dot(n, x)) - 1) < EPS) {
            traces.put(name, new Object[] {'x', dot(rel, x) * mmPerUnit});
        } else if (Math.abs(Math.abs(dot(n, y)) - 1) < EPS) {
            traces.put(name, new Object[] {'y', dot(rel, y) * mmPerUnit});
        } else {
            traces.put(name, new Object[] {'?', 0.0});
        }
    }

    // ------------------------------------------------------------------ placing profiles

    private void place(Map<String, Object> c) {
        String type = Json.string(c, "type", null);
        if ("equal".equals(type)) {
            String a = Json.string(c, "a", null);
            String b = Json.string(c, "b", null);
            if ("circle".equals(kinds.get(a)) && "circle".equals(kinds.get(b))) {
                sameSize.add(new String[] {a, b});
            }
            return;
        }
        if (!"symmetric".equals(type)) {
            return;
        }
        String entity = Json.string(c, "entity", null);
        String about = Json.string(c, "about", null);
        if (entity == null && about != null) {
            String[] a = split(String.valueOf(Json.string(c, "a", null)));
            String[] b = split(String.valueOf(Json.string(c, "b", null)));
            if (isProfile(a[0]) && isProfile(b[0]) && "center".equals(a[1]) && "center".equals(b[1])) {
                mirrors.add(new String[] {a[0], b[0], about});
            }
            return;
        }
        if (entity == null || about == null || !traces.containsKey(about) || !isProfile(entity)) {
            return;
        }
        Object[] trace = traces.get(about);
        double[] center = centers.computeIfAbsent(entity, k -> initialCenter(k));
        if ((char) trace[0] == 'x') {
            center[0] = (double) trace[1];
            placedOn(entity, 'x');
        } else if ((char) trace[0] == 'y') {
            center[1] = (double) trace[1];
            placedOn(entity, 'y');
        }
    }

    private void placedOn(String id, char axis) {
        placed.computeIfAbsent(id, k -> new LinkedHashSet<>()).add(axis);
    }

    /** A center mirrored from its partner's, for each pair where only one is placed. */
    private void placeMirrors() {
        for (String id : entities.keySet()) {
            if (isProfile(id)) {
                centers.computeIfAbsent(id, k -> initialCenter(k));  // marks centers given by center_mm as placed
            }
        }
        for (int pass = 0; pass <= mirrors.size(); pass++) {
            for (String[] m : mirrors) {
                Object[] trace = traces.get(m[2]);
                if (trace == null || (char) trace[0] == '?') {
                    continue;
                }
                boolean aKnown = placed.getOrDefault(m[0], Collections.emptySet()).size() == 2;
                boolean bKnown = placed.getOrDefault(m[1], Collections.emptySet()).size() == 2;
                if (aKnown == bKnown) {
                    continue;
                }
                String from = aKnown ? m[0] : m[1];
                String to = aKnown ? m[1] : m[0];
                double[] c = centers.computeIfAbsent(from, k -> initialCenter(k)).clone();
                int i = (char) trace[0] == 'x' ? 0 : 1;
                c[i] = 2 * (double) trace[1] - c[i];
                centers.put(to, c);
                placedOn(to, 'x');
                placedOn(to, 'y');
            }
        }
    }

    /** Freedoms one profile's constraints fix in its mirror or its equal circle. */
    private void passFreedoms() {
        boolean changed = true;
        while (changed) {
            changed = false;
            for (String[] m : mirrors) {
                Object[] trace = traces.get(m[2]);
                boolean straight = trace != null && (char) trace[0] != '?';
                Set<String> a = fixed.get(m[0]);
                Set<String> b = fixed.get(m[1]);
                for (String freedom : new String[] {"x position", "y position"}) {
                    // About a reference along a sketch axis, each coordinate follows its partner's; about a slanted
                    // centerline, both coordinates follow together.
                    boolean aHas = straight ? a.contains(freedom) : a.contains("x position") && a.contains("y position");
                    boolean bHas = straight ? b.contains(freedom) : b.contains("x position") && b.contains("y position");
                    if (aHas && !b.contains(freedom)) {
                        changed |= b.add(freedom);
                    }
                    if (bHas && !a.contains(freedom)) {
                        changed |= a.add(freedom);
                    }
                }
            }
            for (String[] s : sameSize) {
                Set<String> a = fixed.get(s[0]);
                Set<String> b = fixed.get(s[1]);
                if (a.contains("size") != b.contains("size")) {
                    a.add("size");
                    b.add("size");
                    changed = true;
                }
            }
        }
    }

    private void placeByDimension(Map<String, Object> d) {
        String from = Json.string(d, "from", null);
        String to = Json.string(d, "to", null);
        Double value = Json.number(d, "value_mm");
        if (from == null || to == null || value == null || !traces.containsKey(from)) {
            return;
        }
        String[] target = split(to);
        if (!isProfile(target[0]) || !"center".equals(target[1])) {
            return;
        }
        Object[] trace = traces.get(from);
        double[] center = centers.computeIfAbsent(target[0], k -> initialCenter(k));
        if ((char) trace[0] == 'x') {
            center[0] = (double) trace[1] + value;
            placedOn(target[0], 'x');
        } else if ((char) trace[0] == 'y') {
            center[1] = (double) trace[1] + value;
            placedOn(target[0], 'y');
        }
    }

    private double[] initialCenter(String id) {
        Map<String, Object> e = entities.get(id);
        List<Object> at = e == null ? null : numbers(e, "center_mm");
        if (at != null && at.size() == 2) {
            placedOn(id, 'x');
            placedOn(id, 'y');
            return new double[] {((Number) at.get(0)).doubleValue(), ((Number) at.get(1)).doubleValue()};
        }
        return new double[] {0, 0};
    }

    private boolean isProfile(String id) {
        String kind = kinds.get(id);
        return "rectangle".equals(kind) || "circle".equals(kind);
    }

    // ------------------------------------------------------------------ entities

    private void write(String id, String kind, Map<String, Object> e) {
        switch (kind) {
            case "rectangle": {
                Double w = Json.number(e, "width_mm");
                Double h = Json.number(e, "height_mm");
                double r = positive(e, "corner_radius_mm") ? Json.number(e, "corner_radius_mm") : 0;
                if (w == null || h == null || w <= 0 || h <= 0) {
                    problems.add("Rectangle " + id + " needs width_mm and height_mm greater than 0.");
                    return;
                }
                if (r * 2 >= Math.min(w, h)) {
                    problems.add("The corner radius of " + id + " must be less than half its shorter side.");
                    return;
                }
                double[] c = centers.computeIfAbsent(id, k -> initialCenter(k));
                rectangle(id, c[0], c[1], w, h, r);
                return;
            }
            case "circle": {
                Double d = Json.number(e, "diameter_mm");
                Double radius = Json.number(e, "radius_mm");
                double rr = d != null ? d / 2 : radius != null ? radius : -1;
                if (rr <= 0) {
                    problems.add("Circle " + id + " needs diameter_mm or radius_mm greater than 0.");
                    return;
                }
                double[] c = centers.computeIfAbsent(id, k -> initialCenter(k));
                program.add("circle " + id + " " + u(c[0]) + " " + u(c[1]) + " " + u(rr));
                return;
            }
            case "line":
            case "centerline":
            case "axis": {
                List<Object> a = numbers(e, "start_mm");
                List<Object> b = numbers(e, "end_mm");
                if (a == null || b == null || a.size() != 2 || b.size() != 2) {
                    problems.add(kind + " " + id + " needs start_mm and end_mm, each [x, y].");
                    return;
                }
                if ("axis".equals(kind)) {
                    axes++;
                }
                program.add(("line".equals(kind) ? "line " : "axis".equals(kind) ? "axis " : "cline ") + id + " " + u(n(a, 0)) + " "
                        + u(n(a, 1)) + " " + u(n(b, 0)) + " " + u(n(b, 1)));
                return;
            }
            case "arc": {
                List<Object> c = numbers(e, "center_mm");
                Double r = Json.number(e, "radius_mm");
                Double a0 = Json.number(e, "start_deg");
                Double a1 = Json.number(e, "end_deg");
                if (c == null || c.size() != 2 || r == null || r <= 0 || a0 == null || a1 == null) {
                    problems.add("Arc " + id + " needs center_mm, radius_mm, start_deg and end_deg (counterclockwise).");
                    return;
                }
                program.add("arc " + id + " " + u(n(c, 0)) + " " + u(n(c, 1)) + " " + u(r) + " " + num(Math.toRadians(a0)) + " "
                        + num(Math.toRadians(a1)));
                return;
            }
            case "point": {
                List<Object> at = numbers(e, "at_mm");
                if (at == null || at.size() != 2) {
                    problems.add("Point " + id + " needs at_mm: [x, y].");
                    return;
                }
                program.add("point " + id + " " + u(n(at, 0)) + " " + u(n(at, 1)));
                return;
            }
            default:
                problems.add("Entity " + id + " has the type " + kind + "; use rectangle, circle, line, arc, centerline, axis or point.");
        }
    }

    /** A rectangle, its corners rounded when r > 0, with every constraint that keeps it one, and its two axes. */
    private void rectangle(String id, double cx, double cy, double w, double h, double r) {
        double hx = w / 2, hy = h / 2;
        String b = id + ".bottom", ri = id + ".right", t = id + ".top", l = id + ".left";
        program.add("line " + b + " " + u(cx - hx + r) + " " + u(cy - hy) + " " + u(cx + hx - r) + " " + u(cy - hy));
        if (r > 0) {
            program.add("arc " + id + ".c1 " + u(cx + hx - r) + " " + u(cy - hy + r) + " " + u(r) + " " + num(1.5 * Math.PI) + " " + num(2 * Math.PI));
        }
        program.add("line " + ri + " " + u(cx + hx) + " " + u(cy - hy + r) + " " + u(cx + hx) + " " + u(cy + hy - r));
        if (r > 0) {
            program.add("arc " + id + ".c2 " + u(cx + hx - r) + " " + u(cy + hy - r) + " " + u(r) + " 0 " + num(0.5 * Math.PI));
        }
        program.add("line " + t + " " + u(cx + hx - r) + " " + u(cy + hy) + " " + u(cx - hx + r) + " " + u(cy + hy));
        if (r > 0) {
            program.add("arc " + id + ".c3 " + u(cx - hx + r) + " " + u(cy + hy - r) + " " + u(r) + " " + num(0.5 * Math.PI) + " " + num(Math.PI));
        }
        program.add("line " + l + " " + u(cx - hx) + " " + u(cy + hy - r) + " " + u(cx - hx) + " " + u(cy - hy + r));
        if (r > 0) {
            program.add("arc " + id + ".c4 " + u(cx - hx + r) + " " + u(cy - hy + r) + " " + u(r) + " " + num(Math.PI) + " " + num(1.5 * Math.PI));
        }
        String[] chain = r > 0 ? new String[] {b, id + ".c1", ri, id + ".c2", t, id + ".c3", l, id + ".c4"} : new String[] {b, ri, t, l};
        for (int i = 0; i < chain.length; i++) {
            String next = chain[(i + 1) % chain.length];
            program.add("con " + SAME_POINT + " " + chain[i] + ":end " + next + ":start");
            if (r > 0) {
                program.add("con " + TANGENT + " " + chain[i] + " " + next);
            }
        }
        program.add("con " + HORIZONTAL + " " + b);
        program.add("con " + HORIZONTAL + " " + t);
        program.add("con " + VERTICAL + " " + l);
        program.add("con " + VERTICAL + " " + ri);
        if (r > 0) {
            for (int k = 2; k <= 4; k++) {
                program.add("con " + EQUAL_RADII + " " + id + ".c1 " + id + ".c" + k);
            }
        }
        // The axes: the center of the rectangle is where they cross.
        double ext = Math.max(w, h);
        program.add("cline " + id + ".vaxis " + u(cx) + " " + u(cy - ext) + " " + u(cx) + " " + u(cy + ext));
        program.add("con " + VERTICAL + " " + id + ".vaxis");
        program.add("con " + SYMMETRY + " " + b + ":start " + b + ":end " + id + ".vaxis");
        program.add("cline " + id + ".haxis " + u(cx - ext) + " " + u(cy) + " " + u(cx + ext) + " " + u(cy));
        program.add("con " + HORIZONTAL + " " + id + ".haxis");
        program.add("con " + SYMMETRY + " " + ri + ":start " + ri + ":end " + id + ".haxis");
    }

    // ------------------------------------------------------------------ constraints

    private void constrain(Map<String, Object> c) {
        String type = Json.string(c, "type", "");
        switch (type) {
            case "symmetric": {
                String about = Json.string(c, "about", null);
                String entity = Json.string(c, "entity", null);
                if (about == null) {
                    problems.add("A symmetric constraint needs about: a reference or a centerline.");
                    return;
                }
                if (entity != null) {
                    symmetricProfile(entity, about);
                    return;
                }
                String a = point(Json.string(c, "a", null));
                String b = point(Json.string(c, "b", null));
                String axis = symmetryAxis(about);
                if (a == null || b == null || axis == null) {
                    problems.add("A symmetric constraint needs entity, or a and b, and about.");
                    return;
                }
                program.add("con " + SYMMETRY + " " + a + " " + b + " " + axis);
                return;
            }
            case "horizontal":
            case "vertical": {
                String e = whole(Json.string(c, "entity", null));
                if (e == null) {
                    problems.add("A " + type + " constraint needs entity: a line or centerline.");
                    return;
                }
                program.add("con " + ("horizontal".equals(type) ? HORIZONTAL : VERTICAL) + " " + e);
                return;
            }
            case "coincident": {
                String a = point(Json.string(c, "a", null));
                String b = point(Json.string(c, "b", null));
                if (a == null || b == null) {
                    problems.add("A coincident constraint needs a and b: points such as line1.end and arc1.start.");
                    return;
                }
                program.add("con " + SAME_POINT + " " + a + " " + b);
                return;
            }
            case "on": {
                String p = point(Json.string(c, "point", null));
                String e = whole(Json.string(c, "entity", null));
                if (p == null || e == null) {
                    problems.add("An on constraint needs point and entity.");
                    return;
                }
                program.add("con " + POINT_ON + " " + p + " " + e);
                return;
            }
            case "tangent":
            case "parallel":
            case "perpendicular":
            case "equal": {
                String a = whole(Json.string(c, "a", null));
                String b = whole(Json.string(c, "b", null));
                if (a == null || b == null) {
                    problems.add("A " + type + " constraint needs a and b.");
                    return;
                }
                int t;
                if ("tangent".equals(type)) {
                    t = TANGENT;
                } else if ("parallel".equals(type)) {
                    t = PARALLEL;
                } else if ("perpendicular".equals(type)) {
                    t = PERPENDICULAR;
                } else {
                    String ka = kinds.get(Json.string(c, "a", null));
                    boolean round = "arc".equals(ka) || "circle".equals(ka) || a.matches(".*\\.c[1-4]");
                    t = round ? EQUAL_RADII : EQUAL_LENGTH;
                    squared(a, b);
                }
                program.add("con " + t + " " + a + " " + b);
                return;
            }
            default:
                problems.add("Constraint type " + type + " is not one of symmetric, horizontal, vertical, coincident, on, "
                        + "tangent, parallel, perpendicular, equal.");
        }
    }

    /** A side of a rectangle made equal to a side across: its height follows its width, or the other way. */
    private void squared(String a, String b) {
        String[] pa = split(a);
        String[] pb = split(b);
        if (!pa[0].equals(pb[0]) || !"rectangle".equals(kinds.get(pa[0]))) {
            return;
        }
        boolean aAcross = "left".equals(pa[1]) || "right".equals(pa[1]);
        boolean bAcross = "left".equals(pb[1]) || "right".equals(pb[1]);
        boolean aAlong = "top".equals(pa[1]) || "bottom".equals(pa[1]);
        boolean bAlong = "top".equals(pb[1]) || "bottom".equals(pb[1]);
        if ((aAcross && bAlong) || (aAlong && bAcross)) {
            fixed.get(pa[0]).add(fixed.get(pa[0]).contains("width") ? "height" : "square");
        }
    }

    private void symmetricProfile(String entity, String about) {
        String kind = kinds.get(entity);
        Object[] trace = traces.get(about);
        if (trace == null) {
            problems.add("Symmetric about " + about + ": list " + about + " under references.");
            return;
        }
        if ("rectangle".equals(kind)) {
            if ((char) trace[0] == 'x') {
                program.add("con " + COLLINEAR + " " + entity + ".vaxis " + token(about));
                fixed.get(entity).add("x position");
            } else if ((char) trace[0] == 'y') {
                program.add("con " + COLLINEAR + " " + entity + ".haxis " + token(about));
                fixed.get(entity).add("y position");
            } else {
                problems.add(about + " runs along neither sketch axis; a rectangle is symmetric only about a reference along one.");
            }
        } else if ("circle".equals(kind)) {
            program.add("con " + POINT_ON + " " + entity + ":center " + token(about));
            if ((char) trace[0] == 'x') {
                fixed.get(entity).add("x position");
            } else if ((char) trace[0] == 'y') {
                fixed.get(entity).add("y position");
            }
        } else {
            problems.add("Symmetric with entity takes a rectangle or a circle; for other entities give a, b and about.");
        }
    }

    /** A centerline to be symmetric about: a centerline entity, or one made on a reference. */
    private String symmetryAxis(String name) {
        if ("centerline".equals(kinds.get(name)) || "axis".equals(kinds.get(name))) {
            return name;
        }
        Object[] trace = traces.get(name);
        if (trace == null) {
            return null;
        }
        String axis = token(name) + ".axis";
        if (axesMade.add(axis)) {
            double c = (double) trace[1];
            if ((char) trace[0] == 'x') {
                program.add("cline " + axis + " " + u(c) + " -10 " + u(c) + " 10");
            } else {
                program.add("cline " + axis + " -10 " + u(c) + " 10 " + u(c));
            }
            program.add("con " + COLLINEAR + " " + axis + " " + token(name));
        }
        return axis;
    }

    // ------------------------------------------------------------------ dimensions

    private void dimension(Map<String, Object> d) {
        String name = Json.string(d, "name", null);
        if (name != null && !DIM_NAME.matcher(name).matches()) {
            problems.add("Dimension name " + name + " must be a letter followed by letters, digits or _, 31 at most.");
            return;
        }
        if (name != null) {
            if (dimensionNames.contains(name.toUpperCase(Locale.ROOT))) {
                problems.add("Two dimensions are named " + name + ".");
                return;
            }
            dimensionNames.add(name.toUpperCase(Locale.ROOT));
        }
        String token = name == null ? "-" : name;
        String measure = Json.string(d, "measure", null);
        if (measure != null) {
            measure(token, measure);
            return;
        }
        String from = Json.string(d, "from", null);
        String to = Json.string(d, "to", null);
        Double value = Json.number(d, "value_mm");
        if (from == null || to == null || value == null) {
            problems.add("A dimension needs measure, or from, to and value_mm.");
            return;
        }
        distance(token, from, to, value);
    }

    private void named(String token, double mm) {
        if (!"-".equals(token)) {
            namedValues.put(token, mm);
        }
    }

    private void measure(String token, String measure) {
        String[] m = split(measure);
        String id = m[0];
        String what = m[1];
        String kind = kinds.get(id);
        Map<String, Object> e = entities.get(id);
        if (kind == null) {
            problems.add("The dimension " + measure + " names " + id + ", which the sketch does not have.");
            return;
        }
        if ("rectangle".equals(kind)) {
            if ("width".equals(what)) {
                double w = Json.number(e, "width_mm");
                named(token, w);
                double[] c = centers.get(id);
                program.add("dim " + token + " " + DIM_LINE_LINE + " " + u(w) + " " + u(c[0]) + " "
                        + u(c[1] + Json.number(e, "height_mm") / 2 + 10) + " " + id + ".left " + id + ".right");
                fixed.get(id).add("width");
                return;
            }
            if ("height".equals(what)) {
                double h = Json.number(e, "height_mm");
                named(token, h);
                double[] c = centers.get(id);
                program.add("dim " + token + " " + DIM_LINE_LINE + " " + u(h) + " " + u(c[0] + Json.number(e, "width_mm") / 2 + 10)
                        + " " + u(c[1]) + " " + id + ".bottom " + id + ".top");
                fixed.get(id).add("height");
                return;
            }
            if ("corner_radius".equals(what) && positive(e, "corner_radius_mm")) {
                double r = Json.number(e, "corner_radius_mm");
                named(token, r);
                double[] c = centers.get(id);
                program.add("dim " + token + " " + DIM_RADIUS + " " + u(r) + " " + u(c[0] + Json.number(e, "width_mm") / 2 + 5) + " "
                        + u(c[1] + Json.number(e, "height_mm") / 2 + 5) + " " + id + ".c2");
                fixed.get(id).add("corner radius");
                return;
            }
        } else if ("circle".equals(kind) && ("diameter".equals(what) || "radius".equals(what))) {
            double r = Json.number(e, "diameter_mm") != null ? Json.number(e, "diameter_mm") / 2 : Json.number(e, "radius_mm");
            double[] c = centers.get(id);
            boolean diameter = "diameter".equals(what);
            named(token, diameter ? 2 * r : r);
            program.add("dim " + token + " " + (diameter ? DIM_DIAMETER : DIM_RADIUS) + " " + u(diameter ? 2 * r : r) + " "
                    + u(c[0] + r + 5) + " " + u(c[1] + r + 5) + " " + id);
            fixed.get(id).add("size");
            return;
        } else if ("line".equals(kind) && "length".equals(what)) {
            List<Object> a = numbers(e, "start_mm");
            List<Object> b = numbers(e, "end_mm");
            double len = Math.hypot(n(b, 0) - n(a, 0), n(b, 1) - n(a, 1));
            named(token, len);
            program.add("dim " + token + " " + DIM_LINE + " " + u(len) + " " + u((n(a, 0) + n(b, 0)) / 2 + 5) + " "
                    + u((n(a, 1) + n(b, 1)) / 2 + 5) + " " + id);
            return;
        } else if ("arc".equals(kind) && "radius".equals(what)) {
            List<Object> c = numbers(e, "center_mm");
            double r = Json.number(e, "radius_mm");
            named(token, r);
            program.add("dim " + token + " " + DIM_RADIUS + " " + u(r) + " " + u(n(c, 0) + r + 5) + " " + u(n(c, 1) + r + 5) + " " + id);
            return;
        }
        problems.add("The dimension " + measure + " is not one of: rectangle width, height, corner_radius; circle diameter, "
                + "radius; line length; arc radius.");
    }

    private void distance(String token, String from, String to, double value) {
        String a = distanceEnd(from, to);
        String b = distanceEnd(to, from);
        if (a == null || b == null) {
            return;
        }
        boolean aLine = !a.contains(":") || a.endsWith(":whole");
        boolean bLine = !b.contains(":") || b.endsWith(":whole");
        int type = aLine && bLine ? DIM_LINE_LINE : aLine || bLine ? DIM_LINE_POINT : DIM_POINT_POINT;
        if (type == DIM_LINE_POINT && !aLine) {
            String t = a;
            a = b;
            b = t;
        }
        named(token, Math.abs(value));
        double[] at = placeAt(from, to);
        program.add("dim " + token + " " + type + " " + u(Math.abs(value)) + " " + u(at[0]) + " " + u(at[1]) + " " + a + " " + b);
        String[] target = split(to);
        Object[] trace = traces.get(from);
        if (isProfile(target[0]) && trace != null) {
            if ((char) trace[0] == 'x' && fixed.containsKey(target[0])) {
                fixed.get(target[0]).add("x position");
            } else if ((char) trace[0] == 'y' && fixed.containsKey(target[0])) {
                fixed.get(target[0]).add("y position");
            }
        }
    }

    /** One end of a distance: a reference or line as a whole, a point, or a profile's center or side. */
    private String distanceEnd(String end, String other) {
        if (traces.containsKey(end)) {
            return token(end);
        }
        String[] p = split(end);
        String kind = kinds.get(p[0]);
        if (kind == null) {
            problems.add("The dimension names " + p[0] + ", which the sketch does not have.");
            return null;
        }
        if ("rectangle".equals(kind)) {
            switch (p[1]) {
                case "left":
                case "right":
                case "top":
                case "bottom":
                    return p[0] + "." + p[1];
                case "center": {
                    Object[] trace = traces.get(other);
                    if (trace != null && (char) trace[0] == 'x') {
                        return p[0] + ".vaxis";
                    }
                    if (trace != null && (char) trace[0] == 'y') {
                        return p[0] + ".haxis";
                    }
                    problems.add("A distance to the center of " + p[0] + " runs from a reference along one of the sketch's axes.");
                    return null;
                }
                default:
                    problems.add("A rectangle's ends for a distance are center, left, right, top and bottom, not " + p[1] + ".");
                    return null;
            }
        }
        if ("circle".equals(kind)) {
            return p[0] + ":center";
        }
        if ("line".equals(kind) || "centerline".equals(kind) || "axis".equals(kind)) {
            return p[1].isEmpty() ? p[0] : p[0] + ":" + p[1];
        }
        if ("arc".equals(kind)) {
            return p[0] + ":" + (p[1].isEmpty() ? "center" : p[1]);
        }
        return p[0] + ":whole";
    }

    private double[] placeAt(String from, String to) {
        double[] a = where(from);
        double[] b = where(to);
        return new double[] {(a[0] + b[0]) / 2 + 3, (a[1] + b[1]) / 2 + 3};
    }

    private double[] where(String end) {
        Object[] trace = traces.get(end);
        if (trace != null) {
            return (char) trace[0] == 'x' ? new double[] {(double) trace[1], 0} : new double[] {0, (double) trace[1]};
        }
        String[] p = split(end);
        double[] c = centers.get(p[0]);
        return c != null ? c : new double[] {0, 0};
    }

    // ------------------------------------------------------------------ helpers

    /**
     * A reference's name in the program: the program separates an entity from its point with a
     * colon, so surface:41 or BASE/side[+x] is written with letters, digits and _ only.
     */
    private static String token(String reference) {
        return "R_" + reference.replaceAll("[^A-Za-z0-9_]", "_");
    }

    /** "id.part" into id and part; "id" into id and "". */
    private static String[] split(String text) {
        int dot = text.indexOf('.');
        return dot < 0 ? new String[] {text, ""} : new String[] {text.substring(0, dot), text.substring(dot + 1)};
    }

    private String point(String text) {
        if (text == null) {
            return null;
        }
        String[] p = split(text);
        String kind = kinds.get(p[0]);
        if ("rectangle".equals(kind)) {
            int dot = text.lastIndexOf('.');
            String part = text.substring(0, dot);
            String end = text.substring(dot + 1);
            if (dot > p[0].length() && RECTANGLE_PARTS.contains(split(part)[1]) && (end.equals("start") || end.equals("end") || end.equals("center"))) {
                return part + ":" + end;
            }
            problems.add(text + " is not a point of rectangle " + p[0] + ": use a side's end, such as " + p[0] + ".left.start.");
            return null;
        }
        if (kind == null) {
            problems.add(text + " names " + p[0] + ", which the sketch does not have.");
            return null;
        }
        if ("point".equals(kind)) {
            return p[0];
        }
        if (!p[1].equals("start") && !p[1].equals("end") && !p[1].equals("center")) {
            problems.add(text + " is not a point: use .start, .end or .center.");
            return null;
        }
        return p[0] + ":" + p[1];
    }

    private static final java.util.Set<String> RECTANGLE_PARTS = new java.util.HashSet<>(
            Arrays.asList("left", "right", "top", "bottom", "c1", "c2", "c3", "c4", "vaxis", "haxis"));

    /** An entity or reference as a whole; a rectangle's side, corner arc or axis by id.part. */
    private String whole(String text) {
        if (text == null) {
            return null;
        }
        if (traces.containsKey(text)) {
            return token(text);
        }
        String[] p = split(text);
        if ("rectangle".equals(kinds.get(p[0])) && RECTANGLE_PARTS.contains(p[1])) {
            if (p[1].startsWith("c") && !positive(entities.get(p[0]), "corner_radius_mm")) {
                problems.add(p[0] + " has no rounded corners, so it has no " + p[1] + ".");
                return null;
            }
            return text;
        }
        if (!kinds.containsKey(text)) {
            problems.add(text + " is neither an entity nor a reference of the sketch; a rectangle's sides are id.left, "
                    + "id.right, id.top and id.bottom.");
            return null;
        }
        return text;
    }

    private String u(double mm) {
        return num(mm / mmPerUnit);
    }

    private static String num(double v) {
        return String.format(Locale.ROOT, "%.10g", v);
    }

    private static double n(List<Object> values, int i) {
        return ((Number) values.get(i)).doubleValue();
    }

    private static boolean positive(Map<String, Object> e, String key) {
        Double v = Json.number(e, key);
        return v != null && v > 0;
    }

    @SuppressWarnings("unchecked")
    private static List<Object> numbers(Map<String, Object> e, String key) {
        Object v = e.get(key);
        if (!(v instanceof List)) {
            return null;
        }
        for (Object o : (List<Object>) v) {
            if (!(o instanceof Number)) {
                return null;
            }
        }
        return (List<Object>) v;
    }

    @SuppressWarnings("unchecked")
    private static List<Object> list(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v instanceof List ? (List<Object>) v : new ArrayList<>();
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> objects(Map<String, Object> m, String key) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Object o : list(m, key)) {
            if (o instanceof Map) {
                out.add((Map<String, Object>) o);
            } else {
                problems.add("Each item of " + key + " is an object.");
            }
        }
        return out;
    }

    /** "+x" and the like as a unit vector of the model. */
    public static double[] axis(String name) {
        if (name == null || name.length() != 2) {
            return null;
        }
        double sign = name.charAt(0) == '+' ? 1 : name.charAt(0) == '-' ? -1 : 0;
        int index = "xyz".indexOf(Character.toLowerCase(name.charAt(1)));
        if (sign == 0 || index < 0) {
            return null;
        }
        double[] v = new double[3];
        v[index] = sign;
        return v;
    }

    public static double dot(double[] a, double[] b) {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    public static double[] cross(double[] a, double[] b) {
        return new double[] {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
    }

    public static double[] minus(double[] a, double[] b) {
        return new double[] {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
    }

    public static double[] unit(double[] a) {
        double len = Math.sqrt(dot(a, a));
        return len == 0 ? a : new double[] {a[0] / len, a[1] / len, a[2] / len};
    }
}
