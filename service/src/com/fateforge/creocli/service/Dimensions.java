package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcDimension.DimensionType;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcGlobal.pfcGlobal;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModelItem.ModelItemType;
import com.ptc.pfc.pfcModelItem.ModelItems;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolidInstructions.WRegenInstructions;
import com.ptc.wfc.wfcSolidInstructions.wfcSolidInstructions;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * dimension.list, dimension.set and dimension.tolerance: the numbers a design is driven by,
 * read and changed the way a person edits one in the model tree -- set, regenerate, and back
 * out if the model cannot regenerate with it -- and the tolerance each is made to.
 */
final class Dimensions {

    private Dimensions() {
    }

    /** Every dimension of the features a person sees, or of one feature, with its owner. */
    static Map<String, Object> list(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        String featureRef = Json.string(request, "feature", null);
        String length = lengthUnit(solid);
        List<Object> rows = new ArrayList<>();
        List<Object> held = new ArrayList<>();
        if (featureRef != null) {
            collect(solid, Creo.feature(solid, featureRef), length, rows, held);
        } else {
            Set<Integer> visible = Creo.visibleFeatureIds(solid);
            com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
            for (int i = 0; all != null && i < all.getarraysize(); i++) {
                Feature f = all.get(i);
                if (visible == null || visible.contains(f.GetId())) {
                    collect(solid, f, length, rows, held);
                }
            }
        }
        Map<String, Object> out = Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid), "dimensions", rows,
                "held_together", held);
        if (Json.bool(request, "check_regeneration", false)) {
            try {
                out.put("regeneration_check", regenerationCheck(solid));
            } catch (Failures.Stage incomplete) {
                out.put("regeneration_check", incomplete.detail);
            }
        }
        return out;
    }

    private static void collect(Solid solid, Feature feature, String length, List<Object> into, List<Object> held)
            throws jxthrowable {
        ModelItems dims = feature.ListSubItems(ModelItemType.ITEM_DIMENSION);
        Set<Integer> sketched = sketchDimensions(feature);
        // What each sketch dimension measures, and what its sketch holds together, read from
        // the sketch itself.
        SketchPlan.Read read = sketched == null || sketched.isEmpty() ? null : SketchPlan.read(solid, feature);
        Map<Integer, String> measured = read == null ? null : read.measures;
        if (read != null) {
            for (Map<String, Object> tie : read.held) {
                Map<String, Object> row = new java.util.LinkedHashMap<>();
                row.put("feature", Json.map("id", feature.GetId(), "name", feature.GetName()));
                row.putAll(tie);
                held.add(row);
            }
        }
        for (int i = 0; dims != null && i < dims.getarraysize(); i++) {
            Map<String, Object> row = row((BaseDimension) dims.get(i), feature, length);
            if (dims.get(i) instanceof com.ptc.pfc.pfcDimension.Dimension && !Boolean.TRUE.equals(row.get("reference"))) {
                try {
                    row.put("numeric_tolerance_table", numericTable(solid, (com.ptc.pfc.pfcDimension.Dimension) dims.get(i), false));
                } catch (Throwable unavailable) {
                    row.put("numeric_tolerance_table", Json.map("complete", false, "reason", Failures.error(unavailable).get("message")));
                }
            }
            row.put("in_sketch", sketched == null ? null : sketched.contains(dims.get(i).GetId()));
            if (measured != null && measured.containsKey(dims.get(i).GetId())) {
                row.put("measures", measured.get(dims.get(i).GetId()));
            }
            into.add(row);
        }
    }

    /**
     * The ids of a feature's dimensions that live in its sketch -- a rectangle's width, where
     * it sits -- as against the feature's own, such as an extrusion's depth; the two can hold
     * the same value (measured: a 40 x 20 block 10 deep has a sketch offset of 10 too). Null
     * when the feature's sections cannot be read.
     */
    static Set<Integer> sketchDimensions(Feature feature) {
        if (!(feature instanceof com.ptc.wfc.wfcFeature.WFeature)) {
            return null;
        }
        Set<Integer> out = new java.util.HashSet<>();
        try {
            com.ptc.wfc.wfcSection.Sections sections = ((com.ptc.wfc.wfcFeature.WFeature) feature).GetSections();
            for (int s = 0; sections != null && s < sections.getarraysize(); s++) {
                com.ptc.wfc.wfcSection.SectionDimIds ids = sections.get(s).GetSectionDimensions();
                com.ptc.cipjava.intseq solid = ids == null ? null : ids.GetSolidIds();
                for (int i = 0; solid != null && i < solid.getarraysize(); i++) {
                    out.add(solid.get(i));
                }
            }
        } catch (Throwable unreadable) {
            return null;
        }
        return out;
    }

    /** A mark in a dimension's text, {n:...}; and a line that is only the value. */
    private static final java.util.regex.Pattern MARK = java.util.regex.Pattern.compile("\\{\\d+:([^}]*)\\}");
    private static final java.util.regex.Pattern VALUE_ONLY = java.util.regex.Pattern.compile("[^\\p{Alnum}]*@D");

    static Map<String, Object> row(BaseDimension dim, Feature owner, String length) throws jxthrowable {
        boolean reference = false;
        if (dim instanceof com.ptc.pfc.pfcDimension.Dimension) {
            try {
                reference = ((com.ptc.pfc.pfcDimension.Dimension) dim).IsReference();
            } catch (Throwable unreadable) {
                // Treated as a driving dimension.
            }
        }
        boolean driven = false;
        try {
            driven = dim.GetIsRelationDriven();
        } catch (Throwable unreadable) {
            // Treated as free.
        }
        String kind = kind(dim.GetDimType());
        Map<String, Object> row = Json.map(
                "id", dim.GetId(),
                "name", dim.GetSymbol(),
                "value", clean(dim.GetDimValue()),
                "units", "angle".equals(kind) ? "deg" : length,
                "type", kind,
                "feature", owner == null ? null : Json.map("id", owner.GetId(), "name", owner.GetName()),
                "relation_driven", driven,
                "reference", reference);
        if (dim instanceof com.ptc.pfc.pfcDimension.Dimension && !reference) {
            row.put("tolerance", toleranceOf((com.ptc.pfc.pfcDimension.Dimension) dim));
        }
        // Lines a drawing shows besides the value -- a thread's callout, M20x2.5. Creo returns
        // each line marked up, {0:<symbol>}{1:@D} and {2:M20x2.5}, each ending in a newline: the
        // marks are taken off, and the line that is only the value (@D, with its symbol) is
        // left out.
        try {
            com.ptc.cipjava.stringseq texts = dim.GetTexts();
            List<Object> lines = new ArrayList<>();
            for (int i = 0; texts != null && i < texts.getarraysize(); i++) {
                String line = MARK.matcher(texts.get(i)).replaceAll("$1").replace("\n", "").trim();
                if (!line.isEmpty() && !VALUE_ONLY.matcher(line).matches()) {
                    lines.add(line);
                }
            }
            if (!lines.isEmpty()) {
                row.put("text", lines);
            }
        } catch (Throwable unread) {
            // No text reported.
        }
        return row;
    }

    /**
     * A dimension's value without the last bits of floating noise Creo's solver leaves --
     * 10.000000000000002, 2.4999999999999982 -- which a caller comparing it to what it asked
     * for would trip over; nine decimals is far finer than any drawing shows.
     */
    static double clean(double value) {
        return Math.round(value * 1e9) / 1e9;
    }

    // ------------------------------------------------------------------ tolerances

    /**
     * A dimension's tolerance as a person reads it off the dimension: its kind, what was
     * given, and the limits it allows. Measured on Creo 13.4: the tolerance type is how it is
     * shown (none is the nominal option); the deviations come back from GetToleranceLimits the
     * way a plus-minus tolerance holds them, +upper / -lower, for every kind; in an ISO/DIN
     * model the hole or shaft table label says whether it is a fit, and GetTolerance returns
     * that label whatever the type -- so it is not what is read here.
     */
    static Map<String, Object> toleranceOf(com.ptc.pfc.pfcDimension.Dimension dim) {
        try {
            if (dim instanceof com.ptc.wfc.wfcDimension.WDimension
                    && ((com.ptc.wfc.wfcDimension.WDimension) dim).IsBasic()) {
                return Json.map("type", "basic");
            }
            double value = dim.GetDimValue();
            com.ptc.pfc.pfcDimension.DimToleranceType type = dim.GetToleranceType();
            String fit = fitOf(dim);
            double plus = 0;
            double minus = 0;
            com.ptc.pfc.pfcDimension.DimToleranceLimits limits = dim.GetToleranceLimits();
            if (limits != null) {
                plus = micro(limits.GetUpperLimit());
                minus = micro(limits.GetLowerLimit());
            }
            int shown = type == null ? -1 : type.getValue();
            if (fit != null) {
                return Json.map("type", "fit", "fit", fit,
                        "shown", shown == com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_PLUS_MINUS ? "deviations"
                                : shown == com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_LIMITS ? "limits" : "class",
                        "plus", plus, "minus", minus, "upper", value + plus, "lower", value - minus);
            }
            switch (shown) {
                case -1:
                    return Json.map("type", "nominal");
                case com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_PLUS_MINUS:
                    return Json.map("type", "plus_minus", "plus", plus, "minus", minus,
                            "upper", value + plus, "lower", value - minus);
                case com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_SYMMETRIC:
                case com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_SYMMETRIC_SUPERSCRIPT:
                    return Json.map("type", "symmetric", "value", plus, "upper", value + plus, "lower", value - plus);
                case com.ptc.pfc.pfcDimension.DimToleranceType._DIMTOL_LIMITS:
                    return Json.map("type", "limits", "upper", value + plus, "lower", value - minus);
                default:
                    return Json.map("type", Creo.enumName(type));
            }
        } catch (Throwable unreadable) {
            return Json.map("type", null, "unreadable", Failures.error(unreadable).get("message"));
        }
    }

    /** "H7" when the dimension carries an ISO hole or shaft class; null otherwise, or in ANSI. */
    private static String fitOf(com.ptc.pfc.pfcDimension.Dimension dim) {
        try {
            com.ptc.pfc.pfcDimension.DimToleranceTable table = dim.GetToleranceTable();
            if (table == null) {
                return null;
            }
            int kind = table.GetTolTableType().getValue();
            if (kind != com.ptc.pfc.pfcDimension.ToleranceTableType._TOLTABLE_HOLES
                    && kind != com.ptc.pfc.pfcDimension.ToleranceTableType._TOLTABLE_SHAFTS) {
                return null;
            }
            return table.GetTableName() + table.GetTableColumn();
        } catch (Throwable ansi) {
            return null; // PTC: BadContext when the model is not in the ISO/DIN standard
        }
    }

    /** Back to the general table from a hole or shaft class, in an ISO/DIN model; nothing in ANSI. */
    private static void general(com.ptc.pfc.pfcDimension.Dimension dim) throws jxthrowable {
        if (fitOf(dim) != null) {
            dim.SetToleranceTable(com.ptc.pfc.pfcDimension.pfcDimension.DimToleranceTable_Create(
                    com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_GENERAL, "", 0));
        }
    }

    /**
     * Basic -- the exact value a position tolerance is measured from, boxed -- is a flag of its
     * own: measured, no tolerance type set afterwards clears it; WDimension.SetAsBasic does.
     */
    private static void basic(com.ptc.pfc.pfcDimension.Dimension dim, boolean on) throws jxthrowable {
        if (dim instanceof com.ptc.wfc.wfcDimension.WDimension) {
            com.ptc.wfc.wfcDimension.WDimension w = (com.ptc.wfc.wfcDimension.WDimension) dim;
            if (w.IsBasic() != on) {
                w.SetAsBasic(on);
            }
        } else if (on) {
            throw new Failures.Refusal("E_UNSUPPORTED", "this dimension cannot be made basic");
        }
    }

    /** The decimal places a value needs to be shown exactly, up to six. */
    static int places(double value) {
        for (int places = 0; places < 6; places++) {
            double scaled = Math.abs(value) * Math.pow(10, places);
            if (Math.abs(scaled - Math.rint(scaled)) < 1e-6) {
                return places;
            }
        }
        return 6;
    }

    /**
     * Show the tolerance to as many places as it needs, through the native library; the
     * places read back, or null when the library is not loaded.
     */
    private static Map<String, Object> numericTable(Solid solid, com.ptc.pfc.pfcDimension.Dimension dim, boolean detach) throws Exception {
        if (Service.sketchLibrary() == null) throw new Failures.Refusal("E_UNSUPPORTED", "numeric tolerance table reader is not loaded");
        String file = Creo.fileName((Model)solid); int dot = file.lastIndexOf('.');
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model", com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(0, dot))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model_type", com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(dot+1))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("dimension", com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue(dim.GetId())));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("detach", com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue(detach ? 1 : 0)));
        com.ptc.pfc.pfcProToolkit.FunctionReturn returned = Service.sketchLibrary().ExecuteFunction("creo_cli_numeric_tolerance_table", in);
        if (returned.GetFunctionReturn() != 0) throw new Failures.Refusal("E_CREO", "numeric tolerance table inspection/detachment failed: " + returned.GetFunctionReturn());
        Map<String, Object> out = Json.map("complete", true, "source", "ProDimensionTollabelGet/Set");
        com.ptc.pfc.pfcArgument.Arguments values = returned.GetOutputArguments();
        for (int i=0; values!=null && i<values.getarraysize(); i++) {
            String label = values.get(i).GetLabel();
            out.put(label, "native_image".equals(label) ? values.get(i).GetValue().GetStringValue() : values.get(i).GetValue().GetIntValue());
        }
        if (!Integer.valueOf(1).equals(out.get("contract_version")) || !(out.get("assigned") instanceof Integer) || !(out.get("native_image") instanceof String))
            throw new Failures.Refusal("E_CREO", "numeric tolerance table observation is incomplete");
        out.put("assigned", !Integer.valueOf(0).equals(out.get("assigned")));
        if (detach && Boolean.TRUE.equals(out.get("assigned"))) throw new Failures.Refusal("E_CREO", "numeric tolerance remains table-driven");
        return out;
    }

    private static Integer toleranceDecimals(Solid solid, com.ptc.pfc.pfcDimension.Dimension dim, int places)
            throws Exception {
        if (Service.sketchLibrary() == null) {
            return null;
        }
        String file = Creo.fileName((Model) solid);
        int dot = file.lastIndexOf('.');
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(0, dot))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model_type",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(dot + 1).toLowerCase(java.util.Locale.ROOT))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("dimension",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue(dim.GetId())));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("tolerance_decimals",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue(places)));
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.TOLERANCE_DECIMALS_FUNCTION, in);
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "the tolerance's decimal places could not be set: toolkit error " + result.GetFunctionReturn(),
                    "toolkit_error", result.GetFunctionReturn()));
        }
        com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            if ("tolerance_decimals".equals(out.get(i).GetLabel())) {
                return out.get(i).GetValue().GetIntValue();
            }
        }
        return null;
    }

    /** A fit's deviation, rid of the float noise its micrometre table leaves: 0.0065000000000000001. */
    private static double micro(double millimetres) {
        return Math.round(millimetres * 1e9) / 1e9;
    }

    /**
     * dimension.tolerance: set one dimension's tolerance, as the dimension's properties do --
     * plus and minus, symmetric, limits, an ISO fit from Creo's hole and shaft tables (H7 is
     * hole table H, grade 7; g6 shaft table g, grade 6), basic, or none. The geometry does not
     * change; the model does.
     */
    static Map<String, Object> tolerance(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        Object[] found = find(solid, Json.string(request, "dimension"));
        BaseDimension base = (BaseDimension) found[0];
        Feature owner = (Feature) found[1];
        if (!(base instanceof com.ptc.pfc.pfcDimension.Dimension)) {
            throw new Failures.Refusal("E_VALIDATION", base.GetSymbol() + " takes no tolerance");
        }
        com.ptc.pfc.pfcDimension.Dimension dim = (com.ptc.pfc.pfcDimension.Dimension) base;
        Map<String, Object> before = row(dim, owner, lengthUnit(solid));
        if (Boolean.TRUE.equals(before.get("reference"))) {
            throw new Failures.Refusal("E_VALIDATION", "dimension " + before.get("name")
                    + " is a reference dimension: it reports geometry and takes no tolerance");
        }
        Map<String, Object> spec = Json.object(request.get("tolerance"), "'tolerance'");
        String type = Json.string(spec, "type");
        Integer places = null;
        if ("plus_minus".equals(type) || "symmetric".equals(type) || "limits".equals(type)) {
            numericTable(solid, dim, false);
            numericTable(solid, dim, true);
        }
        try {
            if (!"fit".equals(type)) {
                general(dim);
            }
            basic(dim, false);
            switch (type) {
                case "nominal":
                    dim.SetTolerance(null);
                    break;
                case "basic":
                    dim.SetTolerance(null);
                    basic(dim, true);
                    break;
                case "plus_minus": {
                    double plus = Json.number(spec, "plus");
                    double minus = Json.number(spec, "minus");
                    dim.SetToleranceType(com.ptc.pfc.pfcDimension.DimToleranceType.DIMTOL_PLUS_MINUS);
                    dim.SetToleranceLimits(com.ptc.pfc.pfcDimension.pfcDimension.DimToleranceLimits_Create(plus, minus));
                    places = Math.max(places(plus), places(minus));
                    break;
                }
                case "symmetric": {
                    double value = Json.number(spec, "value");
                    dim.SetToleranceType(com.ptc.pfc.pfcDimension.DimToleranceType.DIMTOL_SYMMETRIC);
                    dim.SetToleranceLimits(com.ptc.pfc.pfcDimension.pfcDimension.DimToleranceLimits_Create(value, value));
                    places = places(value);
                    break;
                }
                case "limits": {
                    double upper = Json.number(spec, "upper");
                    double lower = Json.number(spec, "lower");
                    dim.SetToleranceType(com.ptc.pfc.pfcDimension.DimToleranceType.DIMTOL_LIMITS);
                    dim.SetToleranceLimits(com.ptc.pfc.pfcDimension.pfcDimension.DimToleranceLimits_Create(upper - base.GetDimValue(), base.GetDimValue() - lower));
                    places = Math.max(places(upper), places(lower));
                    break;
                }
                case "fit": {
                    setFit(solid, dim, Json.string(spec, "fit"));
                    String shown = Json.string(spec, "show", "class");
                    if ("class".equals(shown)) {
                        dim.SetTolerance(null); // keeps the class: shown as H7 alone
                    } else if ("deviations".equals(shown) || "limits".equals(shown)) {
                        dim.SetToleranceType("limits".equals(shown) ? com.ptc.pfc.pfcDimension.DimToleranceType.DIMTOL_LIMITS
                                : com.ptc.pfc.pfcDimension.DimToleranceType.DIMTOL_PLUS_MINUS);
                        com.ptc.pfc.pfcDimension.DimToleranceLimits limits = dim.GetToleranceLimits();
                        places = Math.max(places(micro(limits.GetUpperLimit())), places(micro(limits.GetLowerLimit())));
                    } else {
                        throw new Failures.Refusal("E_VALIDATION", "'tolerance.show' is class, deviations or limits");
                    }
                    break;
                }
                default:
                    throw new Failures.Refusal("E_VALIDATION",
                            "'tolerance.type' is nominal, basic, plus_minus, symmetric, limits or fit");
            }
        } catch (Failures.Refusal refused) {
            throw refused;
        } catch (Throwable failure) {
            throw new Failures.Stage("tolerance", failure);
        }
        Integer shownPlaces = places == null ? null : toleranceDecimals(solid, dim, Math.max(1, places));
        // Immediate setter values are insufficient in ISO models: regeneration
        // may reapply a retained general-table reference. The CLI independently
        // checks limits after this regeneration and rejects such a mismatch.
        if (places != null) {
            try {
                solid.Regenerate(com.ptc.pfc.pfcSolid.pfcSolid.RegenInstructions_Create(false, false, null));
            } catch (Throwable failure) {
                throw new Failures.Stage("regenerate_after_numeric_tolerance", failure);
            }
        }
        Creo.repaint(session);
        return Json.map(
                "model", Creo.fileName((Model) solid),
                "units", Creo.units(solid),
                "dimension", row(dim, owner, lengthUnit(solid)),
                "tolerance_before", before.get("tolerance"),
                "tolerance_decimals", shownPlaces);
    }

    /** An ISO fit, checked against Creo's own table before it is set. */
    private static void setFit(Solid solid, com.ptc.pfc.pfcDimension.Dimension dim, String fit) throws Exception {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("^([A-Za-z]{1,2})([0-9]{1,2})$").matcher(fit);
        if (!m.matches() || !(m.group(1).equals(m.group(1).toUpperCase(java.util.Locale.ROOT))
                || m.group(1).equals(m.group(1).toLowerCase(java.util.Locale.ROOT)))) {
            throw new Failures.Refusal("E_VALIDATION", "a fit is a hole class in capitals or a shaft class in "
                    + "small letters and a grade: H7, g6, JS9");
        }
        String name = m.group(1);
        int grade = Integer.parseInt(m.group(2));
        boolean hole = name.equals(name.toUpperCase(java.util.Locale.ROOT));
        java.io.File table = new java.io.File(new java.io.File(ModelOps.creoCommonFiles(), "tol_tables/iso"),
                (hole ? "hole_" : "shaft_") + name.toLowerCase(java.util.Locale.ROOT) + ".ttl");
        if (!table.isFile()) {
            throw new Failures.Refusal("E_VALIDATION", "Creo has no ISO " + (hole ? "hole" : "shaft")
                    + " table " + name + " (" + table.getName() + ")");
        }
        List<Integer> grades = grades(table);
        if (!grades.contains(grade)) {
            throw new Failures.Refusal("E_VALIDATION", "Creo's ISO table " + name + " has grades " + grades
                    + ", not " + grade);
        }
        com.ptc.pfc.pfcDimension.DimTolerance iso = com.ptc.pfc.pfcDimension.pfcDimension.DimTolISODIN_Create(
                hole ? com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_HOLES
                        : com.ptc.pfc.pfcDimension.ToleranceTableType.TOLTABLE_SHAFTS, name, grade);
        try {
            dim.SetTolerance(iso);
        } catch (com.ptc.pfc.pfcExceptions.XToolkitCantAccess notLoaded) {
            // PTC: the table was valid but not yet loaded in this session.
            ((WSolid) solid).LoadToleranceClass(name);
            dim.SetTolerance(iso);
        } catch (com.ptc.pfc.pfcExceptions.XToolkitBadContext wrongStandard) {
            throw new Failures.Refusal("E_CONFLICT", "ISO fits need a model in the ISO/DIN tolerance standard; "
                    + Creo.fileName((Model) solid) + " is not (File > Prepare > Model Properties > Tolerance)");
        }
    }

    /**
     * A model's tolerance standard, "ansi" or "iso", read -- or first set, when {@code set} is
     * given -- by the native library: Java has no call for it. Null when the library is not
     * loaded or the model is neither a part nor an assembly.
     */
    static String toleranceStandard(Solid solid, String set) throws Exception {
        if (Service.sketchLibrary() == null) {
            if (set != null) {
                throw new Failures.Refusal("E_UNSUPPORTED", "a model's tolerance standard is set by the native "
                        + "library, which is not loaded: " + Service.sketchLibraryStatus());
            }
            return null;
        }
        String file = Creo.fileName((Model) solid);
        int dot = file.lastIndexOf('.');
        String type = dot < 0 ? "" : file.substring(dot + 1).toLowerCase(java.util.Locale.ROOT);
        if (!"prt".equals(type) && !"asm".equals(type)) {
            return null;
        }
        com.ptc.pfc.pfcArgument.Arguments in = com.ptc.pfc.pfcArgument.Arguments.create();
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(file.substring(0, dot))));
        in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("model_type",
                com.ptc.pfc.pfcArgument.pfcArgument.CreateStringArgValue(type)));
        if (set != null) {
            in.append(com.ptc.pfc.pfcArgument.pfcArgument.Argument_Create("set",
                    com.ptc.pfc.pfcArgument.pfcArgument.CreateIntArgValue("iso".equals(set) ? 2 : 1)));
        }
        com.ptc.pfc.pfcProToolkit.FunctionReturn result =
                Service.sketchLibrary().ExecuteFunction(Service.TOLERANCE_STANDARD_FUNCTION, in);
        if (result.GetFunctionReturn() != 0) {
            throw new Service.ToolkitFailure(Json.map("code", "E_CREO", "message",
                    "the tolerance standard could not be " + (set == null ? "read" : "set") + ": toolkit error "
                            + result.GetFunctionReturn(), "toolkit_error", result.GetFunctionReturn()));
        }
        com.ptc.pfc.pfcArgument.Arguments out = result.GetOutputArguments();
        for (int i = 0; out != null && i < out.getarraysize(); i++) {
            if ("standard".equals(out.get(i).GetLabel())) {
                int standard = out.get(i).GetValue().GetIntValue();
                return standard == 2 ? "iso" : standard == 1 ? "ansi" : null;
            }
        }
        return null;
    }

    /**
     * model.set-tolerance-standard: the model's tolerance standard -- ANSI, or ISO/DIN, which
     * ISO fits and general tolerance classes need -- and for ISO/DIN its general tolerance
     * class (ISO 2768 fine, medium, coarse, very coarse), as Model Properties > Tolerance sets
     * them. The model is regenerated, as the dialog offers to; its geometry must not change.
     */
    static Map<String, Object> setToleranceStandard(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        String standard = Json.string(request, "standard");
        if (!"iso".equals(standard) && !"ansi".equals(standard)) {
            throw new Failures.Refusal("E_VALIDATION", "'standard' is ansi or iso");
        }
        String wantedClass = Json.string(request, "class", null);
        com.ptc.wfc.wfcSolid.ModelClass modelClass = null;
        if (wantedClass != null) {
            if (!"iso".equals(standard)) {
                throw new Failures.Refusal("E_VALIDATION", "a general tolerance class belongs to the ISO/DIN standard");
            }
            switch (wantedClass) {
                case "fine": modelClass = com.ptc.wfc.wfcSolid.ModelClass.MODELCLASS_FINE; break;
                case "medium": modelClass = com.ptc.wfc.wfcSolid.ModelClass.MODELCLASS_MEDIUM; break;
                case "coarse": modelClass = com.ptc.wfc.wfcSolid.ModelClass.MODELCLASS_COARSE; break;
                case "very_coarse": modelClass = com.ptc.wfc.wfcSolid.ModelClass.MODELCLASS_VERY_COARSE; break;
                default: throw new Failures.Refusal("E_VALIDATION", "'class' is fine, medium, coarse or very_coarse");
            }
        }
        String standardBefore = toleranceStandard(solid, null);
        String classBefore = modelClass(solid);
        Double volumeBefore = Creo.volumeOf(Creo.measure(solid));
        // Freeze existing explicit numeric overrides before changing the model
        // class. ISO regeneration must not substitute general-table values.
        List<Object[]> overrides = new ArrayList<>();
        com.ptc.pfc.pfcFeature.Features features = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i=0; features!=null && i<features.getarraysize(); i++) {
            ModelItems dimensions = features.get(i).ListSubItems(ModelItemType.ITEM_DIMENSION);
            for (int j=0; dimensions!=null && j<dimensions.getarraysize(); j++) {
                if (!(dimensions.get(j) instanceof com.ptc.pfc.pfcDimension.Dimension)) continue;
                com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension)dimensions.get(j);
                if (d.IsReference()) continue;
                Map<String,Object> t = toleranceOf(d);
                String kind = String.valueOf(t.get("type"));
                if ("ansi".equals(standard) && "fit".equals(kind))
                    throw new Failures.Refusal("E_UNSUPPORTED", "an ANSI transition cannot preserve an ISO fit");
                if (!"plus_minus".equals(kind) && !"symmetric".equals(kind) && !"limits".equals(kind)) continue;
                numericTable(solid, d, false);
                com.ptc.pfc.pfcDimension.DimToleranceLimits limits = d.GetToleranceLimits();
                if (limits==null) throw new Failures.Refusal("E_CREO", "existing numeric tolerance limits are unreadable");
                overrides.add(new Object[]{d, d.GetToleranceType(), limits.GetUpperLimit(), limits.GetLowerLimit()});
            }
        }
        try {
            toleranceStandard(solid, standard);
            if (modelClass != null) {
                ((WSolid) solid).SetModelClass(modelClass);
            }
            for (Object[] preserved : overrides) {
                com.ptc.pfc.pfcDimension.Dimension d = (com.ptc.pfc.pfcDimension.Dimension)preserved[0];
                numericTable(solid, d, true);
                d.SetToleranceType((com.ptc.pfc.pfcDimension.DimToleranceType)preserved[1]);
                d.SetToleranceLimits(com.ptc.pfc.pfcDimension.pfcDimension.DimToleranceLimits_Create((Double)preserved[2],(Double)preserved[3]));
            }
        } catch (Failures.Refusal refused) {
            throw refused;
        } catch (Throwable failure) {
            throw new Failures.Stage("tolerance_standard", failure);
        }
        WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
        regen.SetNoResolveMode(true);
        try {
            ((WSolid) solid).WRegenerate(regen);
        } catch (Throwable failure) {
            throw new Failures.Stage("regenerate", failure);
        }
        Creo.repaint(session);
        Double volumeAfter = Creo.volumeOf(Creo.measure(solid));
        return Json.map(
                "model", Creo.fileName((Model) solid),
                "standard", toleranceStandard(solid, null),
                "standard_before", standardBefore,
                "class", modelClass(solid),
                "class_before", classBefore,
                "volume", Json.map("before", volumeBefore, "after", volumeAfter,
                        "change", volumeBefore == null || volumeAfter == null ? null : volumeAfter - volumeBefore));
    }

    /** An ISO/DIN model's general tolerance class, or null: an ANSI model has none. */
    static String modelClass(Solid solid) {
        try {
            com.ptc.wfc.wfcSolid.ModelClass c = ((WSolid) solid).GetModelClass();
            if (c == null || c.getValue() == com.ptc.wfc.wfcSolid.ModelClass._MODELCLASS_NONE) {
                return null;
            }
            return Creo.enumName(c).replaceFirst("^MODELCLASS_", "").toLowerCase(java.util.Locale.ROOT);
        } catch (Throwable unreadable) {
            return null;
        }
    }

    /** The grades a Creo tolerance table has columns for: its "Basic Size" row. */
    private static List<Integer> grades(java.io.File table) throws java.io.IOException {
        List<Integer> out = new ArrayList<>();
        for (String line : java.nio.file.Files.readAllLines(table.toPath(), java.nio.charset.StandardCharsets.ISO_8859_1)) {
            if (line.startsWith("\"Basic Size\"")) {
                // Some tables quote their grades as text: "\"3".
                for (String cell : line.substring("\"Basic Size\"".length()).trim().split("\\s+")) {
                    String grade = cell.replace("\"", "").replace("\\", "");
                    if (grade.matches("[0-9]+")) {
                        out.add(Integer.parseInt(grade));
                    }
                }
                break;
            }
        }
        return out;
    }

    /** linear, radius, diameter, angle: what a person calls them. */
    static String kind(DimensionType type) {
        if (type == null) {
            return null;
        }
        int value = type.getValue();
        return value == DimensionType._DIM_RADIAL ? "radius"
                : value == DimensionType._DIM_DIAMETER ? "diameter"
                : value == DimensionType._DIM_ANGULAR ? "angle" : "linear";
    }

    static String lengthUnit(Solid solid) {
        Object length = Creo.units(solid).get("length");
        return length == null ? null : String.valueOf(length);
    }

    /** A dimension by the symbol Creo shows (d4) or by its id, and the feature that owns it. */
    static Object[] find(Solid solid, String wanted) throws jxthrowable {
        com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
        for (int i = 0; all != null && i < all.getarraysize(); i++) {
            Feature f = all.get(i);
            ModelItems dims = f.ListSubItems(ModelItemType.ITEM_DIMENSION);
            for (int j = 0; dims != null && j < dims.getarraysize(); j++) {
                BaseDimension dim = (BaseDimension) dims.get(j);
                if (wanted.equalsIgnoreCase(dim.GetSymbol()) || wanted.equals(String.valueOf(dim.GetId()))) {
                    return new Object[] {dim, f};
                }
            }
        }
        throw new Failures.Refusal("E_NOT_FOUND", "no dimension named or numbered " + wanted + " in "
                + Creo.fileName((Model) solid) + "; dimension list shows them");
    }

    /**
     * Set one dimension and regenerate. Creo is asked to undo the regeneration if it fails,
     * and the value is put back by hand if that did not already restore it: a change the
     * model cannot take leaves it as it was, and the reply says so.
     */
    static Map<String, Object> set(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        Object[] found = find(solid, Json.string(request, "dimension"));
        BaseDimension dim = (BaseDimension) found[0];
        Feature owner = (Feature) found[1];
        double value = Json.number(request, "value");
        Map<String, Object> before = row(dim, owner, lengthUnit(solid));
        if (Boolean.TRUE.equals(before.get("relation_driven"))) {
            throw new Failures.Refusal("E_CONFLICT", "dimension " + before.get("name")
                    + " is driven by a relation; change the relation, not the value");
        }
        if (Boolean.TRUE.equals(before.get("reference"))) {
            throw new Failures.Refusal("E_VALIDATION", "dimension " + before.get("name")
                    + " is a reference dimension: it reports geometry and cannot drive it");
        }
        double old = dim.GetDimValue();
        Double volumeBefore = Creo.volumeOf(Creo.measure(solid));
        dim.SetDimValue(value);
        WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
        regen.SetUndoIfFail(true);
        regen.SetNoResolveMode(true);
        try {
            ((WSolid) solid).WRegenerate(regen);
        } catch (Throwable failure) {
            Failures.Stage failed = new Failures.Stage("regenerate", failure);
            failed.cleanup = restore(solid, dim, old);
            throw failed;
        }
        Map<String, Object> regeneration = regenerationCheck(solid);
        List<?> failedFeatures = (List<?>) regeneration.get("failed_features");
        if (!failedFeatures.isEmpty()) {
            Failures.Stage failed = new Failures.Stage("regenerate",
                    new Failures.Refusal("E_CREO", "features failed to regenerate: " + failedFeatures));
            failed.cleanup = restore(solid, dim, old);
            throw failed;
        }
        Creo.repaint(session);
        Double volumeAfter = Creo.volumeOf(Creo.measure(solid));
        return Json.map(
                "model", Creo.fileName((Model) solid),
                "units", Creo.units(solid),
                "dimension", row(dim, owner, lengthUnit(solid)),
                "value_before", old,
                "regeneration_check", regeneration,
                "volume", Json.map("before", volumeBefore, "after", volumeAfter,
                        "change", volumeBefore == null || volumeAfter == null ? null : volumeAfter - volumeBefore));
    }

    private static String restore(Solid solid, BaseDimension dim, double old) {
        try {
            if (dim.GetDimValue() != old) {
                dim.SetDimValue(old);
                WRegenInstructions regen = wfcSolidInstructions.WRegenInstructions_Create();
                regen.SetNoResolveMode(true);
                ((WSolid) solid).WRegenerate(regen);
                return dim.GetDimValue() == old ? "value restored and regenerated" : "value not restored";
            }
            return "Creo undid the regeneration; the value is as before";
        } catch (Throwable failure) {
            return "restoring the value failed: " + failure.getClass().getSimpleName();
        }
    }

    /** Features Creo reports failed, or children of failed ones, after a regeneration. */
    @SuppressWarnings("unchecked")
    static List<Object> failedFeatures(Solid solid) throws Failures.Stage {
        return (List<Object>) regenerationCheck(solid).get("failed_features");
    }

    /** A completed flags scan is different from a scan that could not be performed. */
    static Map<String, Object> regenerationCheck(Solid solid) throws Failures.Stage {
        String model = null;
        Map<String, Object> environment = Json.map("service_protocol", Service.PROTOCOL,
                "creo_version", null, "creo_build", null);
        try {
            model = Creo.fileName((Model) solid);
            environment.put("creo_version", String.valueOf(pfcGlobal.GetProEVersion()));
            environment.put("creo_build", String.valueOf(pfcGlobal.GetProEBuildCode()));
            Map<String, Object> record = FeatureStatusScan.scan(model, () -> {
                // The solid-wide flags omit embedded sketch subfeatures. Inspect every
                // actual feature, including hidden ones, with its own native flags.
                final com.ptc.pfc.pfcFeature.Features all = solid.ListFeaturesByType(Boolean.FALSE, null);
                if (all == null) {
                    return null;
                }
                return new FeatureStatusScan.Flags() {
                    public int size() throws Throwable {
                        return all.getarraysize();
                    }
                    public FeatureStatusScan.Flag get(int index) throws Throwable {
                        final Feature feature = all.get(index);
                        if (!(feature instanceof com.ptc.wfc.wfcFeature.WFeature)) {
                            throw new IllegalStateException("feature has no native status API");
                        }
                        final int expected = feature.GetId();
                        final com.ptc.wfc.wfcFeature.FeatureStatusFlag flag =
                                ((com.ptc.wfc.wfcFeature.WFeature) feature).GetStatusFlag();
                        if (flag == null) {
                            return null;
                        }
                        return new FeatureStatusScan.Flag() {
                            public int id() throws Throwable { return flag.GetFeatureId(); }
                            public int expectedId() { return expected; }
                            public boolean failed() throws Throwable { return flag.GetIsFailed(); }
                            public boolean childOfFailed() throws Throwable { return flag.GetIsChildOfFailed(); }
                        };
                    }
                };
            });
            record.putAll(environment);
            return record;
        } catch (FeatureStatusScan.Incomplete incomplete) {
            incomplete.record.putAll(environment);
            throw new Failures.Stage("regeneration_check", incomplete.getCause(), incomplete.record);
        } catch (Throwable unreadable) {
            Map<String, Object> record = FeatureStatusScan.record(model);
            record.putAll(environment);
            record.put("error_type", unreadable.getClass().getSimpleName());
            throw new Failures.Stage("regeneration_check", unreadable, record);
        }
    }
}
