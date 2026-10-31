package com.fateforge.creocli.service;

import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Pure same-phase selection. No SDK handles, getters or cross-request state. */
final class SummaryObservation {
    private SummaryObservation() { }

    static final class Incomplete extends Exception {
        private static final long serialVersionUID = 1L;
        Incomplete(String message) { super(message); }
    }

    /**
     * Select the actual table reading already in this summary. Structural admission
     * is not a claim that optional text/layout is complete or that the client has
     * independently verified the mutation. Existing optional nulls stay null.
     */
    @SuppressWarnings("unchecked")
    static Map<String, Object> sameSummaryTable(Map<String, Object> summary, String drawing, int tableId)
            throws Incomplete {
        if (summary == null || !sameDrawing(drawing, summary.get("model"))
                || !"drawing".equals(summary.get("type"))) throw new Incomplete("drawing_identity");
        if (!(summary.get("tables") instanceof List<?> tables)) throw new Incomplete("table_inventory");
        Map<?, ?> selected = null;
        Set<Long> identities = new HashSet<>();
        for (Object raw : tables) {
            if (!(raw instanceof Map<?, ?> row)) throw new Incomplete("table_inventory_row");
            long identity = integer(row.get("id"), "table_id");
            if (identity < 0 || !identities.add(identity)) throw new Incomplete("table_identity_ambiguous");
            if (identity == tableId) selected = row;
        }
        if (selected == null) throw new Incomplete("created_table_missing");
        long rows = integer(selected.get("rows"), "row_count");
        long columns = integer(selected.get("columns"), "column_count");
        if (rows < 1 || columns < 1) throw new Incomplete("table_shape");
        if (!(selected.get("cells") instanceof List<?> cells) || cells.size() != rows)
            throw new Incomplete("table_rows_incomplete");
        for (Object raw : cells) {
            if (!(raw instanceof List<?> line) || line.size() != columns)
                throw new Incomplete("table_columns_incomplete");
            for (Object text : line) {
                // tableRow's existing optional-null contract is retained verbatim;
                // null text is not turned into a blank or newly called complete.
                if (text != null && !(text instanceof String)) throw new Incomplete("table_cell_type");
            }
        }
        for (String field : List.of("at", "size", "outline", "rotation", "segments", "sheet",
                "bounds_source", "from_format", "cell_references")) {
            if (!selected.containsKey(field)) throw new Incomplete("missing_table_" + field);
        }
        if (integer(selected.get("sheet"), "table_sheet") < 1
                || integer(selected.get("segments"), "table_segments") < 1
                || !(selected.get("from_format") instanceof Boolean))
            throw new Incomplete("table_ownership");
        if (!(selected.get("cell_references") instanceof List<?> references) || references.isEmpty())
            throw new Incomplete("native_cell_references");
        Set<String> referenced = new HashSet<>();
        for (Object raw : references) {
            if (!(raw instanceof Map<?, ?> reference)) throw new Incomplete("native_cell_reference_row");
            long row = integer(reference.get("row"), "reference_row");
            long column = integer(reference.get("column"), "reference_column");
            if (row < 1 || row > rows || column < 1 || column > columns
                    || integer(reference.get("region"), "reference_region") < 0
                    || !referenced.add(row + ":" + column)) throw new Incomplete("native_cell_reference_identity");
            for (String field : List.of("model", "assembly", "source")) {
                if (!(reference.get(field) instanceof String text) || text.isEmpty())
                    throw new Incomplete("native_cell_reference_" + field);
            }
        }
        return (Map<String, Object>) selected;
    }

    private static boolean sameDrawing(String requested, Object observed) {
        // Creo.model resolves typed names case-insensitively. Keep the full typed
        // identity: do not infer an extension, strip a path/version, or coerce data.
        String typed = "(?i)[A-Za-z][A-Za-z0-9_-]{0,30}\\.drw";
        return requested != null && requested.matches(typed)
                && observed instanceof String actual && actual.matches(typed)
                && requested.equalsIgnoreCase(actual);
    }

    private static long integer(Object value, String field) throws Incomplete {
        if (value instanceof Integer || value instanceof Long) return ((Number) value).longValue();
        throw new Incomplete(field);
    }
}
