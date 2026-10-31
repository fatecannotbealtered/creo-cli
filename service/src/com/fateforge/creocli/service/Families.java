package com.fateforge.creocli.service;

import com.ptc.cipjava.jxthrowable;
import com.ptc.pfc.pfcDimension.BaseDimension;
import com.ptc.pfc.pfcFamily.FamColDimension;
import com.ptc.pfc.pfcFamily.FamColFeature;
import com.ptc.pfc.pfcFamily.FamColModelItem;
import com.ptc.pfc.pfcFamily.FamColParam;
import com.ptc.pfc.pfcFamily.FamilyTableColumn;
import com.ptc.pfc.pfcFamily.FamilyTableColumns;
import com.ptc.pfc.pfcFamily.FamilyTableRow;
import com.ptc.pfc.pfcFamily.FamilyTableRows;
import com.ptc.pfc.pfcFeature.Feature;
import com.ptc.pfc.pfcFeature.FeatureStatus;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.pfc.pfcModelItem.ParamValue;
import com.ptc.pfc.pfcModelItem.Parameter;
import com.ptc.pfc.pfcModelItem.pfcModelItem;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * family.show / family.set / family.remove: a part's family table, as Tools > Family Table
 * keeps it -- the generic's dimensions, parameters and features as columns, one row per
 * instance. Every instance set is made in session and read back, so what the table says is
 * what the instance regenerates to; an instance that will not regenerate puts the table back
 * as it was.
 */
final class Families {

    private Families() {
    }

    private static final Pattern NAME = Pattern.compile("[A-Za-z][A-Za-z0-9_-]{0,30}");

    static Map<String, Object> show(Map<String, Object> request) throws Exception {
        Solid solid = Creo.solid(Creo.session(), Json.string(request, "model"));
        Map<String, Object> out = table(solid);
        out.put("generic", genericOf(solid));
        return out;
    }

    /** For model show: the generic an instance is of, and the instances a generic has. */
    static Map<String, Object> info(Solid solid) {
        List<Object> names = new ArrayList<>();
        try {
            String generic = genericOf(solid);
            FamilyTableRows rows = solid.ListRows();
            for (int r = 0; rows != null && r < rows.getarraysize(); r++) {
                String name = rows.get(r).GetInstanceName();
                if (name == null || name.isBlank() || names.contains(name.toLowerCase(Locale.ROOT)))
                    throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "family row identity is missing or duplicated");
                names.add(name.toLowerCase(Locale.ROOT));
            }
            FamilyTableColumns columns = solid.ListColumns();
            int columnCount = columns == null ? 0 : columns.getarraysize();
            String model = Creo.fileName((Model) solid).toLowerCase(Locale.ROOT);
            if (model.equals(generic))
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "immediate generic cannot be the instance itself");
            return Json.map("complete", true, "kind", generic != null ? "instance" : (!names.isEmpty() || columnCount > 0) ? "generic" : "standalone",
                    "generic", generic, "instances", names, "row_count", names.size(), "column_count", columnCount,
                    "source", "FamilyMember.GetImmediateGenericInfo/ListRows/ListColumns",
                    "empty_semantics", "optional null/empty rows and columns; only documented GetImmediateGenericInfo XToolkitNotFound means no generic");
        } catch (Throwable unreadable) {
            return Json.map("complete", false, "kind", "unknown", "generic", null, "instances", null,
                    "row_count", null, "column_count", null, "error", Failures.error(unreadable),
                    "source", "FamilyMember.GetImmediateGenericInfo/ListRows/ListColumns");
        }
    }

    /** The generic's file name when this model is an instance; null for a model of its own. */
    static String genericOf(Solid solid) {
        try {
            com.ptc.pfc.pfcModel.ModelDescriptor generic = solid.GetImmediateGenericInfo();
            return generic == null ? null : Creo.fileName(generic).toLowerCase(Locale.ROOT);
        } catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound notAnInstance) {
            return null;
        } catch (Throwable unreadable) {
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE", "GetImmediateGenericInfo failed: " + unreadable.getClass().getSimpleName());
        }
    }

    /** The family a model belongs to: its top generic's file name, or its own for one of its own. */
    static String top(Solid solid) throws jxthrowable {
        try {
            com.ptc.pfc.pfcModel.ModelDescriptor top = solid.GetTopGenericInfo();
            if (top != null) {
                return Creo.fileName(top).toLowerCase(Locale.ROOT);
            }
        } catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound notAnInstance) {
            // Its own.
        }
        return Creo.fileName((Model) solid).toLowerCase(Locale.ROOT);
    }

    static Map<String, Object> table(Solid solid) throws jxthrowable {
        List<Object> columns = new ArrayList<>();
        FamilyTableColumns cols = solid.ListColumns();
        for (int i = 0; cols != null && i < cols.getarraysize(); i++) {
            columns.add(column(cols.get(i)));
        }
        List<Object> instances = new ArrayList<>();
        FamilyTableRows rows = solid.ListRows();
        for (int r = 0; rows != null && r < rows.getarraysize(); r++) {
            FamilyTableRow row = rows.get(r);
            Map<String, Object> cells = new LinkedHashMap<>();
            for (int i = 0; cols != null && i < cols.getarraysize(); i++) {
                FamilyTableColumn col = cols.get(i);
                Map<String, Object> cell = Json.map("value", null, "generic", null);
                try {
                    Object rawValue = ParameterOps.plain(solid.GetCell(col, row));
                    boolean inherited = solid.GetCellIsDefault(col, row);
                    Map<String, Object> definition = (Map<String, Object>) columns.get(i);
                    cell.put("raw_value", rawValue);
                    cell.put("generic", inherited);
                    // GetCell may represent inheritance symbolically. The native default flag
                    // means the generic's current dimension value, not a requested setter value.
                    cell.put("value", inherited && "dimension".equals(definition.get("kind"))
                            ? definition.get("generic_value") : rawValue);
                } catch (Throwable unreadable) {
                    cell.put("error", Failures.error(unreadable));
                }
                cells.put(col.GetSymbol(), cell);
            }
            String verified = null;
            try {
                verified = Creo.enumName(row.GetIsVerified());
            } catch (Throwable unknown) {
                // Unknown.
            }
            instances.add(Json.map("name", row.GetInstanceName(), "verified", verified, "cells", cells));
        }
        boolean complete = true;
        for (Object value : columns) {
            Map<String, Object> column = (Map<String, Object>) value;
            if (column.get("error") != null || column.get("kind") == null || column.get("name") == null) complete = false;
        }
        for (Object value : instances) {
            Map<String, Object> instance = (Map<String, Object>) value;
            for (Object cell : ((Map<?, ?>) instance.get("cells")).values())
                if (((Map<?, ?>) cell).get("error") != null) complete = false;
        }
        return Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid),
                "columns", columns, "instances", instances, "complete", complete,
                "source", "FamilyMember.ListColumns/ListRows/GetCell/GetCellIsDefault; no write");
    }

    private static Map<String, Object> column(FamilyTableColumn col) throws jxthrowable {
        Map<String, Object> out = Json.map("symbol", col.GetSymbol(), "kind", null, "name", null);
        try {
            if (col instanceof FamColDimension) {
                BaseDimension dim = (BaseDimension) ((FamColModelItem) col).GetRefItem();
                out.put("kind", "dimension");
                out.put("name", dim.GetSymbol());
                out.put("generic_value", dim.GetDimValue());
            } else if (col instanceof FamColParam) {
                Parameter p = ((FamColParam) col).GetRefParam();
                out.put("kind", "parameter");
                out.put("name", p.GetName());
                out.put("generic_value", ParameterOps.plain(p.GetValue()));
            } else if (col instanceof FamColFeature) {
                Feature f = (Feature) ((FamColModelItem) col).GetRefItem();
                out.put("kind", "feature");
                out.put("name", f.GetName());
                out.put("generic_value", true);
            } else {
                out.put("kind", Creo.enumName(col.GetType()).toLowerCase(Locale.ROOT));
            }
        } catch (Throwable unreadable) {
            out.put("error", Failures.error(unreadable));
        }
        return out;
    }

    /** What a key names in the generic, and its column once the table has one. */
    private static final class Key {
        final String key;
        final String kind;
        final Object item;
        FamilyTableColumn column;
        boolean added;

        Key(String key, String kind, Object item) {
            this.key = key;
            this.kind = kind;
            this.item = item;
        }
    }

    /**
     * Add the columns and instances named and set the cells given: a number for a dimension,
     * the parameter's own type for a parameter, true (present) or false (suppressed) for a
     * feature. Columns and instances not named are left as they are.
     */
    static Map<String, Object> set(Map<String, Object> request) throws Exception {
        Session session = Creo.session();
        requireProfile(request);
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        String generic = genericOf(solid);
        if (generic != null) {
            throw new Failures.Refusal("E_VALIDATION", Creo.fileName((Model) solid) + " is an instance; the table is "
                    + generic + "'s");
        }
        Object raw = request.get("instances");
        if (!(raw instanceof List) || ((List<?>) raw).isEmpty()) {
            throw new Failures.Refusal("E_VALIDATION", "'instances' lists one instance or more");
        }
        List<Map<String, Object>> wanted = new ArrayList<>();
        for (Object item : (List<?>) raw) {
            Map<String, Object> instance = Json.object(item, "an instance");
            String name = Json.string(instance, "name");
            if (!NAME.matcher(name).matches()) {
                throw new Failures.Refusal("E_VALIDATION", "an instance is named as a model is: a letter, then "
                        + "letters, digits, '_' or '-', at most 31 characters; not " + name);
            }
            wanted.add(instance);
        }
        List<String> inspect = new ArrayList<>();
        Object inspectRaw = request.get("inspect_instances");
        if (!(inspectRaw instanceof List) || ((List<?>) inspectRaw).isEmpty() || ((List<?>) inspectRaw).size() > 4)
            throw new Failures.Refusal("E_VALIDATION", "bounded family apply requires 1..4 explicit inspection instances");
        for (Object value : (List<?>) inspectRaw) {
            if (!(value instanceof String) || !NAME.matcher((String) value).matches() || inspect.contains(((String) value).toLowerCase(Locale.ROOT)))
                throw new Failures.Refusal("E_VALIDATION", "inspection instance identity is invalid or repeated");
            inspect.add(((String) value).toLowerCase(Locale.ROOT));
        }
        requireClosedRows(session, inspect);
        Map<String, Key> keys = new LinkedHashMap<>();
        for (Map<String, Object> instance : wanted) {
            for (String key : Json.object(instance.get("values"), "'values'").keySet()) {
                if (!key.startsWith("dimension:"))
                    throw new Failures.Refusal("E_UNSUPPORTED", "bounded family apply supports dimension columns only");
                if (!keys.containsKey(key)) {
                    keys.put(key, resolve(solid, key));
                }
            }
        }
        Map<String, Object> before = table(solid);
        Double genericVolume = Creo.volumeOf(Creo.measure(solid));
        // What goes back if an instance will not regenerate.
        List<String> createdRows = new ArrayList<>();
        List<Object[]> oldCells = new ArrayList<>();
        try {
            for (Key k : keys.values()) {
                FamilyTableColumn fresh = fresh(solid, k);
                FamilyTableColumn existing = solid.GetColumn(fresh.GetSymbol());
                if (existing != null) {
                    k.column = existing;
                } else {
                    k.column = solid.AddColumn(fresh, null);
                    k.added = true;
                }
            }
            List<Object> touched = new ArrayList<>();
            for (Map<String, Object> instance : wanted) {
                String name = Json.string(instance, "name");
                FamilyTableRow row = solid.GetRow(name);
                boolean created = row == null;
                if (created) {
                    row = solid.AddRow(name, null);
                    createdRows.add(row.GetInstanceName());
                }
                for (Map.Entry<String, Object> e : Json.object(instance.get("values"), "'values'").entrySet()) {
                    Key k = keys.get(e.getKey());
                    if (!created && !k.added) {
                        oldCells.add(new Object[] {k.column, row.GetInstanceName(),
                                solid.GetCell(k.column, row), solid.GetCellIsDefault(k.column, row)});
                    }
                    ParamValue given = value(k, e.getValue());
                    solid.SetCell(k.column, row, given);
                    // Creo keeps the old value, without a word, for one it will not take: a
                    // depth of 0 stays 20.
                    Object now = ParameterOps.plain(solid.GetCell(k.column, row));
                    if (!same(now, ParameterOps.plain(given))) {
                        throw new Failures.Refusal("E_CREO", "Creo kept " + row.GetInstanceName() + "'s " + k.key
                                + " at " + now + "; it does not take " + e.getValue());
                    }
                }
                touched.add(Json.map("name", row.GetInstanceName(), "created", created));
            }
            List<Object> checked = new ArrayList<>();
            List<String> failed = new ArrayList<>();
            for (String instance : inspect) {
                Map<String, Object> read = check(session, solid, instance, keys, true);
                checked.add(read);
                if (!Boolean.TRUE.equals(read.get("regenerated"))) {
                    failed.add(instance + ": " + read.get("error"));
                }
            }
            if (!failed.isEmpty()) {
                throw new Failures.Refusal("E_CREO", "instances that do not regenerate: " + String.join("; ", failed));
            }
            Map<String, Object> symbols = new LinkedHashMap<>();
            List<Object> added = new ArrayList<>();
            for (Key k : keys.values()) {
                symbols.put(k.key, k.column.GetSymbol());
                if (k.added) {
                    added.add(k.key);
                }
            }
            return Json.map("model", Creo.fileName((Model) solid), "units", Creo.units(solid),
                    "columns", symbols, "columns_added", added, "instances", touched, "checked", checked,
                    "generic_volume", Json.map("before", genericVolume, "after", Creo.volumeOf(Creo.measure(solid))),
                    "table_before", before, "table", table(solid));
        } catch (Exception failure) {
            Failures.Stage stage = failure instanceof Failures.Stage ? (Failures.Stage) failure
                    : new Failures.Stage("family_table", failure);
            List<String> cleanup = new ArrayList<>();
            for (String instance : inspect) {
                try {
                    FamilyTableRow row = solid.GetRow(instance);
                    if (row != null && findInstance(session, instance) != null) row.Erase();
                } catch (Throwable remaining) { cleanup.add("instance " + instance + ": " + remaining.getClass().getSimpleName()); }
            }
            stage.cleanup = restore(solid, keys, createdRows, oldCells)
                    + "; instance cleanup errors=" + cleanup + "; independent complete readback required; rollback is not asserted";
            throw stage;
        }
    }

    /** The table put back: rows made taken out, cells changed set back, columns added removed. */
    private static String restore(Solid solid, Map<String, Key> keys, List<String> createdRows, List<Object[]> oldCells) {
        List<String> problems = new ArrayList<>();
        for (String name : createdRows) {
            try {
                FamilyTableRow row = solid.GetRow(name);
                if (row != null) {
                    eraseQuietly(row);
                    solid.RemoveRow(row);
                }
            } catch (Throwable left) {
                problems.add("row " + name);
            }
        }
        for (Object[] cell : oldCells) {
            try {
                FamilyTableRow row = solid.GetRow((String) cell[1]);
                if (row == null || cell[2] == null) {
                    problems.add("cell " + cell[1] + ": prior raw value or row unavailable");
                    continue;
                }
                eraseQuietly(row);
                FamilyTableColumn column = (FamilyTableColumn) cell[0];
                solid.SetCell(column, row, (ParamValue) cell[2]);
                if (!same(ParameterOps.plain(solid.GetCell(column, row)),
                        ParameterOps.plain((ParamValue) cell[2]))
                        || solid.GetCellIsDefault(column, row) != (Boolean) cell[3]) {
                    problems.add("cell " + cell[1] + ": value/default inheritance not restored");
                }
            } catch (Throwable left) {
                problems.add("cell " + cell[1]);
            }
        }
        for (Key k : keys.values()) {
            if (k.added && k.column != null) {
                try {
                    solid.RemoveColumn(k.column);
                } catch (Throwable left) {
                    problems.add("column " + k.key);
                }
            }
        }
        return "table restoration attempted; errors=" + problems;
    }

    private static boolean same(Object a, Object b) {
        if (a instanceof Number && b instanceof Number) {
            double x = ((Number) a).doubleValue();
            double y = ((Number) b).doubleValue();
            return Math.abs(x - y) <= 1e-9 * Math.max(1.0, Math.abs(y));
        }
        return a == null ? b == null : a.equals(b);
    }

    private static void eraseQuietly(FamilyTableRow row) {
        try {
            row.Erase();
        } catch (Throwable notInSession) {
            // Nothing to erase.
        }
    }

    /** dimension:d4, parameter:NAME or feature:NAME, found in the generic. */
    private static Key resolve(Solid solid, String key) throws Exception {
        int colon = key.indexOf(':');
        String kind = colon < 1 ? "" : key.substring(0, colon).toLowerCase(Locale.ROOT);
        String name = colon < 1 ? key : key.substring(colon + 1);
        switch (kind) {
            case "dimension":
                return new Key(key, kind, Dimensions.find(solid, name)[0]);
            case "parameter":
                Parameter p = null;
                try {
                    p = solid.GetParam(name);
                } catch (Throwable absent) {
                    // Refused below.
                }
                if (p == null) {
                    throw new Failures.Refusal("E_NOT_FOUND", "no parameter named " + name + " in "
                            + Creo.fileName((Model) solid) + "; parameter list shows them");
                }
                return new Key(key, kind, p);
            case "feature":
                return new Key(key, kind, Creo.feature(solid, name));
            default:
                throw new Failures.Refusal("E_VALIDATION", "a column is dimension:<symbol>, parameter:<name> or "
                        + "feature:<name>, not " + key);
        }
    }

    private static FamilyTableColumn fresh(Solid solid, Key k) throws jxthrowable {
        switch (k.kind) {
            case "dimension":
                return solid.CreateDimensionColumn((com.ptc.pfc.pfcDimension.Dimension) k.item);
            case "parameter":
                return solid.CreateParamColumn((Parameter) k.item);
            default:
                return solid.CreateFeatureColumn((Feature) k.item);
        }
    }

    private static ParamValue value(Key k, Object raw) throws Exception {
        switch (k.kind) {
            case "dimension":
                if (!(raw instanceof Number)) {
                    throw new Failures.Refusal("E_VALIDATION", k.key + " takes a number");
                }
                return pfcModelItem.CreateDoubleParamValue(((Number) raw).doubleValue());
            case "feature":
                if (!(raw instanceof Boolean)) {
                    throw new Failures.Refusal("E_VALIDATION", k.key + " takes true (present) or false (suppressed)");
                }
                return pfcModelItem.CreateBoolParamValue((Boolean) raw);
            default:
                return ParameterOps.value(ParameterOps.type(((Parameter) k.item).GetValue()), raw);
        }
    }

    /**
     * One instance made in session and read back: its volume and what each key reads in it.
     * An instance already in session is regenerated where it is; one made here goes again.
     */
    private static Map<String, Object> check(Session session, Solid generic, String name, Map<String, Key> keys, boolean retain)
            throws Exception {
        Map<String, Object> out = Json.map("name", name);
        FamilyTableRow row = generic.GetRow(name);
        Model already = findInstance(session, name);
        Solid inst;
        try {
            if (already != null) {
                inst = (Solid) already;
                inst.Regenerate(null);
            } else {
                inst = (Solid) row.CreateInstance();
            }
        } catch (Throwable failed) {
            out.put("regenerated", false);
            out.put("error", Failures.error(failed));
            return out;
        }
        List<Object> broken = Dimensions.failedFeatures(inst);
        out.put("model", Creo.fileName((Model) inst));
        out.put("regenerated", broken.isEmpty());
        if (!broken.isEmpty()) {
            out.put("error", "features that did not regenerate: " + broken);
        }
        out.put("volume", Creo.volumeOf(Creo.measure(inst)));
        Map<String, Object> reads = new LinkedHashMap<>();
        for (Key k : keys.values()) {
            try {
                if ("dimension".equals(k.kind)) {
                    int id = ((BaseDimension) k.item).GetId();
                    reads.put(k.key, ((BaseDimension) Dimensions.find(inst, String.valueOf(id))[0]).GetDimValue());
                } else if ("parameter".equals(k.kind)) {
                    reads.put(k.key, ParameterOps.plain(inst.GetParam(((Parameter) k.item).GetName()).GetValue()));
                } else {
                    int status = inst.GetFeatureById(((Feature) k.item).GetId()).GetStatus().getValue();
                    reads.put(k.key, status != FeatureStatus._FEAT_SUPPRESSED
                            && status != FeatureStatus._FEAT_FAMILY_TABLE_SUPPRESSED);
                }
            } catch (Throwable unreadable) {
                reads.put(k.key, Json.map("error", Failures.error(unreadable)));
            }
        }
        out.put("reads", reads);
        out.put("kept_in_session", already != null || retain);
        if (already == null && !retain) {
            eraseQuietly(row);
        }
        return out;
    }

    /** Take an instance out of the table; out of session first, if it is there. */
    static Map<String, Object> remove(Map<String, Object> request) throws Exception {
        requireProfile(request);
        Session session = Creo.session();
        Solid solid = Creo.solid(session, Json.string(request, "model"));
        String name = Json.string(request, "instance");
        requireClosedRows(session, List.of(name.toLowerCase(Locale.ROOT)));
        FamilyTableRow row = solid.GetRow(name);
        if (row == null) {
            throw new Failures.Refusal("E_NOT_FOUND", Creo.fileName((Model) solid) + " has no instance " + name
                    + "; it has " + info(solid).get("instances"));
        }
        Map<String, Object> before = table(solid);
        String removed = row.GetInstanceName();
        try {
            solid.RemoveRow(row);
            return Json.map("model", Creo.fileName((Model) solid), "removed", removed, "table_before", before,
                    "table", table(solid));
        } catch (Throwable failed) {
            throw new Failures.Stage("family_row_removal", failed);
        }
    }

    private static void requireProfile(Map<String, Object> request) {
        if (!"dimension-only-v1".equals(request.get("profile")))
            throw new Failures.Refusal("E_UNSUPPORTED", "family write requires the bounded dimension-only public lifecycle");
    }

    private static Model findInstance(Session session, String name) throws jxthrowable {
        try { return session.GetModel(name, ModelType.MDL_PART); }
        catch (com.ptc.pfc.pfcExceptions.XToolkitNotFound absent) { return null; }
    }

    private static void requireClosedRows(Session session, List<String> names) throws Exception {
        Map<String, Object> state = SessionOps.managementState();
        for (Object value : (List<?>) state.get("models")) {
            Map<String, Object> model = Json.object(value, "native model state");
            String name = ((String) model.get("model")).toLowerCase(Locale.ROOT);
            if (!"part".equals(model.get("type")))
                throw new Failures.Refusal("E_UNSUPPORTED", "bounded family writes require a part-only session; referenced assembly/drawing combinations are refused");
            for (String instance : names) {
                if (name.equals(instance + ".prt") || ((List<?>) model.get("dependencies")).contains(instance + ".prt"))
                    throw new Failures.Refusal("E_CONFLICT", "instance is open or referenced: " + instance);
            }
        }
    }

    /** An instance of a generic brought into session, as File > Open asks which one. */
    static Model open(Session session, Solid generic, String name) throws Exception {
        FamilyTableRow row = generic.GetRow(name);
        if (row == null) {
            throw new Failures.Refusal("E_NOT_FOUND", Creo.fileName((Model) generic) + " has no instance " + name
                    + "; it has " + info(generic).get("instances"));
        }
        Model already = null;
        try {
            already = session.GetModel(name, ModelType.MDL_PART);
        } catch (Throwable absent) {
            // Not in session.
        }
        if (already != null) {
            throw new Failures.Refusal("E_CONFLICT", Creo.fileName(already) + " is already in session");
        }
        return row.CreateInstance();
    }
}
