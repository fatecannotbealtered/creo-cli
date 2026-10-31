package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.List;

/** Pure, bounded row-vector admission for a 2D screen envelope. No SDK objects. */
final class NoteEnvelopeMath {
    private NoteEnvelopeMath() {}

    static void validateMatrix(double[][] matrix) {
        if (matrix == null || matrix.length != 4) throw invalid("matrix_requires_four_rows");
        for (double[] row : matrix) {
            if (row == null || row.length != 4) throw invalid("matrix_requires_four_columns");
            for (double value : row) if (!Double.isFinite(value)) throw invalid("matrix_nonfinite");
        }
        // The installed official guide uses [x y z 1] * M, not M * [x y z 1].
        // Exact zero is intentional: an arbitrarily small z coupling is still unproved.
        if (matrix[2][0] != 0.0 || matrix[2][1] != 0.0) throw invalid("matrix_xy_depends_on_unknown_screen_z");
        if (matrix[0][3] != 0.0 || matrix[1][3] != 0.0 || matrix[2][3] != 0.0
                || matrix[3][3] != 1.0) throw invalid("matrix_not_supported_affine_form");
        double determinant = matrix[0][0] * matrix[1][1] - matrix[1][0] * matrix[0][1];
        if (!Double.isFinite(determinant) || determinant == 0.0) throw invalid("matrix_xy_map_degenerate");
    }

    static void validateCorners(List<List<Double>> corners) {
        if (corners == null || corners.size() != 4) throw invalid("line_requires_four_corners");
        for (List<Double> corner : corners) validateXY(corner);
    }

    /** All four corners of every line are required; never round or substitute zeros. */
    static List<Object> bounds(List<List<Double>> corners) {
        if (corners == null || corners.size() < 4 || corners.size() % 4 != 0)
            throw invalid("bounds_require_complete_four_corner_lines");
        double x0 = Double.POSITIVE_INFINITY, y0 = Double.POSITIVE_INFINITY;
        double x1 = Double.NEGATIVE_INFINITY, y1 = Double.NEGATIVE_INFINITY;
        for (List<Double> corner : corners) {
            validateXY(corner);
            x0 = Math.min(x0, corner.get(0)); y0 = Math.min(y0, corner.get(1));
            x1 = Math.max(x1, corner.get(0)); y1 = Math.max(y1, corner.get(1));
        }
        if (x1 <= x0 || y1 <= y0) throw invalid("text_bounds_degenerate_zero_span");
        return List.of(List.of(x0, y0), List.of(x1, y1));
    }

    static List<List<Double>> matrixRows(double[][] matrix) {
        List<List<Double>> rows = new ArrayList<>();
        for (double[] raw : matrix) {
            List<Double> row = new ArrayList<>();
            for (double value : raw) {
                if (!Double.isFinite(value)) throw invalid("matrix_nonfinite");
                row.add(value);
            }
            rows.add(row);
        }
        return rows;
    }

    private static void validateXY(List<Double> corner) {
        if (corner == null || corner.size() != 2 || corner.get(0) == null || corner.get(1) == null
                || !Double.isFinite(corner.get(0)) || !Double.isFinite(corner.get(1)))
            throw invalid("corner_requires_two_finite_raw_coordinates");
    }

    private static IllegalArgumentException invalid(String reason) {
        return new IllegalArgumentException(reason);
    }
}
