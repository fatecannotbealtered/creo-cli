package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcSection.Section;
import com.ptc.wfc.wfcSection.wfcSection;
import com.ptc.wfc.wfcSession.wfcSession;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Closed 2D profiles and the two ways they are drawn into a feature's section.
 *
 * <p>A sketch made of several entities must be dimensioned to references projected from
 * the model; a person's sketch gets them automatically, and Object TOOLKIT Java has no
 * call that creates them. The C toolkit has {@code ProSectionEntityFromProjection}, so the
 * native library finishes such sketches; single closed entities can be drawn from Java.
 */
final class Sketches {

    /**
     * The order the native library finishes a sketch in, found by trying six on a live Creo
     * 13.4. Every order that kept intent manager on was rejected at the redefine; solving
     * explicitly was refused as "bad inputs". What Creo accepts is the C toolkit's classic
     * path: project the references, draw, auto-dimension, regenerate, set the direction,
     * redefine.
     */
    static final String NATIVE_STEPS = "refs,entities,plan,direction,redefine,readback";

    /**
     * Creo rounds a sketch dimension to default_dec_places when it is strengthened, and the
     * redefine strengthens what auto-dimensioning created: the first live hexagon had a
     * vertex at 12.99 instead of 12.990381. Switched off around each native sketch.
     */
    static final String ROUND_ON_STRENGTHEN = "sketcher_strngthn_to_def_dec_pl";

    static final String MULTI_ENTITY_SKETCH = "profiles drawn from several entities (rectangle, polygon, slot, "
            + "outline, any with holes) "
            + "must be dimensioned to references projected from the model, and Object TOOLKIT Java has "
            + "no call that creates them.";

    private Sketches() {
    }

    /** A closed 2D profile drawn into a section, and its area for the read-back. */
    interface Profile {
        void draw(Section section) throws jxthrowable;

        double area();

        /** One closed entity: the only kind Creo accepts without projected references. */
        default boolean singleEntity() {
            return false;
        }

        /**
         * The profile in the native library's format -- "L x0 y0 x1 y1" per edge, "C cx cy r"
         * for a circle, ';'-separated -- or null when the library cannot draw it.
         */
        default String nativeEntities() {
            return null;
        }

        /** Per native entity, the loop it is part of, "slot:1" (see SketchPlan). */
        default List<String> nativeLoops() {
            return null;
        }
    }

    static Profile profile(Map<String, Object> spec) {
        String type = Json.string(spec, "type");
        double cx = spec.containsKey("center") ? coordinate(spec, 0) : 0.0;
        double cy = spec.containsKey("center") ? coordinate(spec, 1) : 0.0;
        if (Outlines.hasHoles(spec) || "slot".equals(type) || "outline".equals(type)
                || ("rectangle".equals(type) && spec.containsKey("corner_radius"))) {
            if ("ellipse".equals(type)) {
                throw new Failures.Refusal("E_VALIDATION", "an ellipse takes no holes: the native library, "
                        + "which draws loops, does not draw ellipses");
            }
            // Loops of lines and arcs, and anything with holes: several entities, which only
            // the native library dimensions to projected references.
            String entities = Outlines.entities(spec);
            List<String> loops = Outlines.loopKinds(spec);
            return new Profile() {
                public void draw(Section section) {
                    throw new Failures.Refusal("E_UNSUPPORTED", "this profile is drawn by the native library only");
                }

                public double area() {
                    return Double.NaN;
                }

                public String nativeEntities() {
                    return entities;
                }

                public List<String> nativeLoops() {
                    return loops;
                }
            };
        }
        switch (type) {
            case "rectangle": {
                double w = positive(spec, "width");
                double h = positive(spec, "height");
                return new Profile() {
                    public void draw(Section section) throws jxthrowable {
                        double x0 = cx - w / 2, x1 = cx + w / 2, y0 = cy - h / 2, y1 = cy + h / 2;
                        line(section, x0, y0, x1, y0);
                        line(section, x1, y0, x1, y1);
                        line(section, x1, y1, x0, y1);
                        line(section, x0, y1, x0, y0);
                    }

                    public double area() {
                        return w * h;
                    }

                    public String nativeEntities() {
                        double x0 = cx - w / 2, x1 = cx + w / 2, y0 = cy - h / 2, y1 = cy + h / 2;
                        return edges(new double[][] {{x0, y0}, {x1, y0}, {x1, y1}, {x0, y1}});
                    }

                    public List<String> nativeLoops() {
                        return java.util.Collections.nCopies(4, "rectangle:0");
                    }
                };
            }
            case "polygon": {
                List<double[]> points = points(spec);
                return new Profile() {
                    public void draw(Section section) throws jxthrowable {
                        for (int i = 0; i < points.size(); i++) {
                            double[] a = points.get(i);
                            double[] b = points.get((i + 1) % points.size());
                            line(section, a[0], a[1], b[0], b[1]);
                        }
                    }

                    public double area() {
                        double twice = 0;
                        for (int i = 0; i < points.size(); i++) {
                            double[] a = points.get(i);
                            double[] b = points.get((i + 1) % points.size());
                            twice += a[0] * b[1] - b[0] * a[1];
                        }
                        return Math.abs(twice) / 2;
                    }

                    public String nativeEntities() {
                        return edges(points.toArray(new double[0][]));
                    }

                    public List<String> nativeLoops() {
                        return java.util.Collections.nCopies(points.size(), "polygon:0");
                    }
                };
            }
            case "ellipse": {
                double rx = positive(spec, "x_radius");
                double ry = positive(spec, "y_radius");
                return new Profile() {
                    public void draw(Section section) throws jxthrowable {
                        section.AddEntity(wfcSection.SectionEntityEllipse_Create(
                                wfcSession.CreatePoint2D(cx, cy), rx, ry));
                    }

                    public double area() {
                        return Math.PI * rx * ry;
                    }

                    public boolean singleEntity() {
                        return true;
                    }
                };
            }
            case "circle": {
                double r = positive(spec, "diameter") / 2;
                return new Profile() {
                    public void draw(Section section) throws jxthrowable {
                        section.AddEntity(wfcSection.SectionEntityCircle_Create(wfcSession.CreatePoint2D(cx, cy), r));
                    }

                    public double area() {
                        return Math.PI * r * r;
                    }

                    public boolean singleEntity() {
                        return true;
                    }

                    public String nativeEntities() {
                        return "C " + cx + " " + cy + " " + r;
                    }

                    public List<String> nativeLoops() {
                        return java.util.Collections.singletonList("circle:0");
                    }
                };
            }
            default:
                throw new Failures.Refusal("E_VALIDATION", "profile type '" + type + "' is not known; use circle, "
                        + "ellipse, rectangle, polygon, slot or outline");
        }
    }

    /**
     * A revolve's axis drawn in its sketch: two points of a centerline, in the sketch's own
     * axes, in the native library's format.
     */
    static String centerline(Object axis) {
        if (!(axis instanceof List) || ((List<?>) axis).size() != 2) {
            throw new Failures.Refusal("E_VALIDATION", "'axis' must be two sketch points [[x0, y0], [x1, y1]] or "
                    + "the name of an axis or straight edge");
        }
        double[][] p = new double[2][];
        for (int i = 0; i < 2; i++) {
            Object point = ((List<?>) axis).get(i);
            if (!(point instanceof List) || ((List<?>) point).size() != 2
                    || !(((List<?>) point).get(0) instanceof Double) || !(((List<?>) point).get(1) instanceof Double)) {
                throw new Failures.Refusal("E_VALIDATION", "'axis' points are [x, y] numbers");
            }
            p[i] = new double[] {(Double) ((List<?>) point).get(0), (Double) ((List<?>) point).get(1)};
        }
        if (Math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1]) == 0) {
            throw new Failures.Refusal("E_VALIDATION", "'axis' needs two different points");
        }
        return "K " + p[0][0] + " " + p[0][1] + " " + p[1][0] + " " + p[1][1];
    }

    /**
     * The datum planes a sketch on this plane is dimensioned to: given explicitly, or for a
     * sketch on one of the template's default planes, the other two -- what Creo's sketcher
     * picks when a person starts a sketch there.
     */
    static List<String> references(Solid solid, Map<String, Object> sketch, String plane) throws jxthrowable {
        Object given = sketch.get("references");
        List<String> out = new ArrayList<>();
        if (given != null) {
            if (!(given instanceof List) || ((List<?>) given).size() != 2) {
                throw new Failures.Refusal("E_VALIDATION", "'references' must name exactly two datum planes");
            }
            for (Object name : (List<?>) given) {
                if (!(name instanceof String) || ((String) name).isEmpty()) {
                    throw new Failures.Refusal("E_VALIDATION", "'references' must name exactly two datum planes");
                }
                out.add((String) name);
            }
        } else {
            List<String> defaults = new ArrayList<>(java.util.Arrays.asList("RIGHT", "TOP", "FRONT"));
            if (!defaults.remove(plane.toUpperCase(java.util.Locale.ROOT))) {
                throw new Failures.Refusal("E_VALIDATION", "sketching on " + plane + " needs 'references': two "
                        + "datum planes perpendicular to it, to dimension the sketch to");
            }
            out.addAll(defaults);
        }
        for (String name : out) {
            Creo.datumSurface(solid, name); // refuses with the planes that do exist
        }
        return out;
    }

    /**
     * Finish an incomplete feature's sketch in C: project the references, draw, dimension,
     * set the direction and redefine. Its outputs are plain values, read here on the toolkit
     * thread. On failure the library deletes the feature itself when asked to -- Java's
     * delete is refused with BAD_CONTEXT once the library has touched it.
     */
    static Map<String, Object> drawNatively(Solid solid, Feature feature, String entities, List<String> references,
                                            int direction, String beforeRedefine, boolean cleanup,
                                            SketchPlan.Plan plan) throws Exception {
        // Steps a feature needs once its sketch exists go just before the redefine.
        String steps = beforeRedefine == null ? NATIVE_STEPS
                : NATIVE_STEPS.replace(",redefine", "," + beforeRedefine + ",redefine");
        return drawNatively(solid, feature, entities, references, direction, steps, null, cleanup,
                plan == null ? null : plan.spec);
    }

    /** The same, with the steps spelled out and the sketch at another place in the tree. */
    static Map<String, Object> drawNatively(Solid solid, Feature feature, String entities, List<String> references,
                                            int direction, String steps, String sketcherPath, boolean cleanup)
            throws Exception {
        return drawNatively(solid, feature, entities, references, direction, steps, sketcherPath, cleanup, null);
    }

    /** The same, with the dimensions the "plan" step gives the sketch (see SketchPlan). */
    static Map<String, Object> drawNatively(Solid solid, Feature feature, String entities, List<String> references,
                                            int direction, String steps, String sketcherPath, boolean cleanup,
                                            String dims) throws Exception {
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        if (sketcherPath != null) {
            in.append(pfcArgument.Argument_Create("sketcher_path", pfcArgument.CreateStringArgValue(sketcherPath)));
        }
        String model = Creo.fileName((Model) solid).replaceFirst("(?i)\\.prt$", "");
        in.append(pfcArgument.Argument_Create("model", pfcArgument.CreateStringArgValue(model)));
        in.append(pfcArgument.Argument_Create("feature_id", pfcArgument.CreateIntArgValue(feature.GetId())));
        in.append(pfcArgument.Argument_Create("refs", pfcArgument.CreateStringArgValue(String.join(";", references))));
        in.append(pfcArgument.Argument_Create("entities", pfcArgument.CreateStringArgValue(entities)));
        in.append(pfcArgument.Argument_Create("direction", pfcArgument.CreateIntArgValue(direction)));
        in.append(pfcArgument.Argument_Create("steps", pfcArgument.CreateStringArgValue(steps)));
        in.append(pfcArgument.Argument_Create("cleanup", pfcArgument.CreateIntArgValue(cleanup ? 1 : 0)));
        if (dims != null) {
            in.append(pfcArgument.Argument_Create("dims", pfcArgument.CreateStringArgValue(dims)));
        }
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.SKETCH_LIBRARY_NAME, in);
        Map<String, Object> report = Json.map("engine", "native", "references", new ArrayList<Object>(references));
        com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            com.ptc.pfc.pfcArgument.Argument argument = out.get(i);
            com.ptc.pfc.pfcArgument.ArgValue value = argument.GetValue();
            String type = Creo.enumName(value.Getdiscr());
            Object read;
            if ("ARG_V_INTEGER".equals(type)) {
                read = value.GetIntValue();
            } else if ("ARG_V_DOUBLE".equals(type)) {
                read = value.GetDoubleValue();
            } else if ("ARG_V_BOOLEAN".equals(type)) {
                read = value.GetBoolValue();
            } else if ("ARG_V_ASCII_STRING".equals(type)) {
                read = value.GetASCIIStringValue();
            } else {
                read = value.GetStringValue();
            }
            report.put(argument.GetLabel(), read);
        }
        report.put("returned", result.GetFunctionReturn());
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO",
                    "message", "native sketch stopped at " + report.get("failed_step")
                            + " with toolkit error " + result.GetFunctionReturn(),
                    "toolkit_error", result.GetFunctionReturn(), "native", report));
        }
        return report;
    }

    /** What the sketch holds and whether it solves, before the feature is committed. */
    static Map<String, Object> state(Section section) {
        Map<String, Object> state = Json.map("engine", "java");
        try {
            com.ptc.wfc.wfcSection.SectionEntities entities = section.ListSectionEntities();
            state.put("entities", entities == null ? 0 : entities.getarraysize());
        } catch (Throwable unreadable) {
            state.put("entities", null);
            state.put("list_error", Failures.error(unreadable));
        }
        try {
            com.ptc.wfc.wfcSection.SectionDimIds dims = section.GetSectionDimensions();
            com.ptc.cipjava.intseq ids = dims == null ? null : dims.GetSectionIds();
            state.put("dimensions", ids == null ? 0 : ids.getarraysize());
        } catch (Throwable unreadable) {
            state.put("dimensions", null);
        }
        try {
            section.Regenerate();
            state.put("solves", true);
        } catch (Throwable failure) {
            state.put("solves", false);
            state.put("error", Failures.error(failure));
        }
        return state;
    }

    /** A section's entities with their ids and geometry, its epsilon and dimension counts. */
    static Map<String, Object> describe(Section section) {
        Map<String, Object> out = Json.map();
        try {
            out.put("name", section.GetName());
        } catch (Throwable ignored) {
            // unnamed
        }
        try {
            out.put("epsilon", section.GetEpsilon());
        } catch (Throwable ignored) {
            // not available on this section
        }
        try {
            com.ptc.cipjava.intseq ids = section.GetEntityIds();
            List<Object> rows = new ArrayList<>();
            for (int i = 0; ids != null && i < ids.getarraysize(); i++) {
                int id = ids.get(i);
                Map<String, Object> row = Json.map("id", id);
                try {
                    com.ptc.wfc.wfcSection.SectionEntity entity = section.GetEntity(id);
                    row.put("type", Creo.enumName(entity.GetSectionEntityType()));
                    if (entity instanceof com.ptc.wfc.wfcSection.SectionEntityLine) {
                        com.ptc.pfc.pfcBase.Outline2D l = ((com.ptc.wfc.wfcSection.SectionEntityLine) entity).GetLine();
                        row.put("from", java.util.Arrays.asList(l.get(0).get(0), l.get(0).get(1)));
                        row.put("to", java.util.Arrays.asList(l.get(1).get(0), l.get(1).get(1)));
                    } else if (entity instanceof com.ptc.wfc.wfcSection.SectionEntityCircle) {
                        com.ptc.wfc.wfcSection.SectionEntityCircle c = (com.ptc.wfc.wfcSection.SectionEntityCircle) entity;
                        row.put("center", java.util.Arrays.asList(c.GetCenter().get(0), c.GetCenter().get(1)));
                        row.put("radius", c.GetRadius());
                    }
                } catch (Throwable unreadable) {
                    row.put("error", Failures.error(unreadable));
                }
                rows.add(row);
            }
            out.put("entities", rows);
        } catch (Throwable failure) {
            out.put("entities_error", Failures.error(failure));
        }
        return out;
    }

    private static String edges(double[][] vertices) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < vertices.length; i++) {
            double[] a = vertices[i];
            double[] b = vertices[(i + 1) % vertices.length];
            if (out.length() > 0) {
                out.append(';');
            }
            out.append("L ").append(a[0]).append(' ').append(a[1]).append(' ').append(b[0]).append(' ').append(b[1]);
        }
        return out.toString();
    }

    private static List<double[]> points(Map<String, Object> spec) {
        Object raw = spec.get("points");
        if (!(raw instanceof List) || ((List<?>) raw).size() < 3) {
            throw new Failures.Refusal("E_VALIDATION", "'points' must list at least three [x, y] vertices");
        }
        List<double[]> out = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            if (!(item instanceof List) || ((List<?>) item).size() != 2
                    || !(((List<?>) item).get(0) instanceof Double) || !(((List<?>) item).get(1) instanceof Double)) {
                throw new Failures.Refusal("E_VALIDATION", "each point must be [x, y]");
            }
            out.add(new double[] {(Double) ((List<?>) item).get(0), (Double) ((List<?>) item).get(1)});
        }
        return out;
    }

    private static void line(Section section, double x0, double y0, double x1, double y1) throws jxthrowable {
        section.AddEntity(wfcSection.SectionEntityLine_Create(wfcSession.CreateOutline2D(x0, y0, x1, y1)));
    }

    static double positive(Map<String, Object> spec, String key) {
        double value = Json.number(spec, key);
        if (value <= 0) {
            throw new Failures.Refusal("E_VALIDATION", "'" + key + "' must be positive");
        }
        return value;
    }

    private static double coordinate(Map<String, Object> spec, int index) {
        Object center = spec.get("center");
        if (!(center instanceof List) || ((List<?>) center).size() != 2
                || !(((List<?>) center).get(index) instanceof Double)) {
            throw new Failures.Refusal("E_VALIDATION", "'center' must be [x, y]");
        }
        return (Double) ((List<?>) center).get(index);
    }
}
