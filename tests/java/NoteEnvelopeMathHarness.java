package com.fateforge.creocli.service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** SDK-free numeric controls. No Creo imports, files, dispatch, templates or getters. */
public final class NoteEnvelopeMathHarness {
    private static int checks;

    private static double[][] identity() {
        return new double[][] {{1, 0, 0, 0}, {0, 1, 0, 0}, {0, 0, 1, 0}, {0, 0, 0, 1}};
    }

    private static void require(boolean condition, String reason) {
        checks++;
        if (!condition) throw new AssertionError(reason);
    }

    private static void rejected(Runnable operation, String reason) {
        checks++;
        try { operation.run(); }
        catch (IllegalArgumentException expected) {
            if (!expected.getMessage().equals(reason)) throw new AssertionError(expected);
            return;
        }
        throw new AssertionError("unsafe input accepted: " + reason);
    }

    private static List<List<Double>> corners() {
        // Both extrema occur in corners that are not a single diagonal pair.
        return List.of(List.of(0.0, 0.0), List.of(10.0, 1.0), List.of(-3.0, 12.0), List.of(5.0, -7.0));
    }

    private static void zCoupling() {
        for (int column = 0; column < 2; column++) {
            double[][] matrix = identity();
            matrix[2][column] = 1e-300;
            rejected(() -> NoteEnvelopeMath.validateMatrix(matrix), "matrix_xy_depends_on_unknown_screen_z");
        }
        double[][] rowVector = identity();
        rowVector[0][2] = 12.0; rowVector[1][2] = -7.0;
        NoteEnvelopeMath.validateMatrix(rowVector);
        require(true, "row-vector output Z may depend on input X/Y");
        double[][] negativeZero = identity(); negativeZero[2][0] = -0.0;
        NoteEnvelopeMath.validateMatrix(negativeZero);
        require(Double.doubleToRawLongBits(NoteEnvelopeMath.matrixRows(negativeZero).get(2).get(0))
                == Double.doubleToRawLongBits(-0.0), "negative zero evidence was normalized");
    }

    private static void affine() {
        for (int row = 0; row < 3; row++) {
            double[][] matrix = identity(); matrix[row][3] = 1e-300;
            rejected(() -> NoteEnvelopeMath.validateMatrix(matrix), "matrix_not_supported_affine_form");
        }
        double[][] homogeneous = identity(); homogeneous[3][3] = Math.nextDown(1.0);
        rejected(() -> NoteEnvelopeMath.validateMatrix(homogeneous), "matrix_not_supported_affine_form");
        double[][] mirroredRotation = {{0, 2, 0, 0}, {3, 0, 0, 0}, {0, 0, 1, 0}, {-123.25, 45.125, 9, 1}};
        NoteEnvelopeMath.validateMatrix(mirroredRotation);
        require(true, "valid rotated/mirrored affine XY map rejected");
    }

    private static void malformed() {
        rejected(() -> NoteEnvelopeMath.validateMatrix(null), "matrix_requires_four_rows");
        rejected(() -> NoteEnvelopeMath.validateMatrix(new double[3][4]), "matrix_requires_four_rows");
        double[][] absent = identity(); absent[2] = null;
        rejected(() -> NoteEnvelopeMath.validateMatrix(absent), "matrix_requires_four_columns");
        double[][] shortRow = identity(); shortRow[1] = new double[3];
        rejected(() -> NoteEnvelopeMath.validateMatrix(shortRow), "matrix_requires_four_columns");
        for (double value : new double[] {Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY}) {
            double[][] matrix = identity(); matrix[3][0] = value;
            rejected(() -> NoteEnvelopeMath.validateMatrix(matrix), "matrix_nonfinite");
            rejected(() -> NoteEnvelopeMath.matrixRows(matrix), "matrix_nonfinite");
        }
        double[][] singular = identity(); singular[0][0] = 1; singular[1][0] = 2; singular[0][1] = 2; singular[1][1] = 4;
        rejected(() -> NoteEnvelopeMath.validateMatrix(singular), "matrix_xy_map_degenerate");
        double[][] overflow = identity(); overflow[0][0] = Double.MAX_VALUE; overflow[1][1] = 2;
        rejected(() -> NoteEnvelopeMath.validateMatrix(overflow), "matrix_xy_map_degenerate");
        double[][] smallValid = identity(); smallValid[0][0] = 1e-300;
        NoteEnvelopeMath.validateMatrix(smallValid);
        require(true, "small but nonzero XY determinant was rounded to zero");
    }

    private static void fourCorners() {
        NoteEnvelopeMath.validateCorners(corners());
        require(NoteEnvelopeMath.bounds(corners()).equals(List.of(List.of(-3.0, -7.0), List.of(10.0, 12.0))),
                "not all four corners contributed to bounds");
        List<List<Double>> lines = new ArrayList<>(corners());
        lines.addAll(List.of(List.of(20.0, 0.0), List.of(1.0, 30.0), List.of(-20.0, 1.0), List.of(0.0, -30.0)));
        require(NoteEnvelopeMath.bounds(lines).equals(List.of(List.of(-20.0, -30.0), List.of(20.0, 30.0))),
                "a later line was omitted");
        rejected(() -> NoteEnvelopeMath.validateCorners(corners().subList(0, 3)), "line_requires_four_corners");
        rejected(() -> NoteEnvelopeMath.bounds(corners().subList(0, 3)), "bounds_require_complete_four_corner_lines");
        lines.remove(7);
        rejected(() -> NoteEnvelopeMath.bounds(lines), "bounds_require_complete_four_corner_lines");
        List<List<Double>> broken = new ArrayList<>(corners()); broken.set(2, null);
        rejected(() -> NoteEnvelopeMath.validateCorners(broken), "corner_requires_two_finite_raw_coordinates");
        broken.set(2, Arrays.asList(null, 1.0));
        rejected(() -> NoteEnvelopeMath.validateCorners(broken), "corner_requires_two_finite_raw_coordinates");
        broken.set(2, List.of(Double.NaN, 1.0));
        rejected(() -> NoteEnvelopeMath.validateCorners(broken), "corner_requires_two_finite_raw_coordinates");
    }

    private static void noRounding() {
        double low = Math.nextDown(1.0), high = Math.nextUp(1.0), tiny = 0.000000000012345678901234;
        List<List<Double>> raw = List.of(List.of(low, tiny), List.of(high, tiny), List.of(low, -tiny), List.of(high, -tiny));
        List<Object> box = NoteEnvelopeMath.bounds(raw);
        List<?> lower = (List<?>) box.get(0), upper = (List<?>) box.get(1);
        require(Double.doubleToRawLongBits((Double) lower.get(0)) == Double.doubleToRawLongBits(low), "lower X rounded");
        require(Double.doubleToRawLongBits((Double) upper.get(0)) == Double.doubleToRawLongBits(high), "upper X rounded");
        require(Double.doubleToRawLongBits((Double) lower.get(1)) == Double.doubleToRawLongBits(-tiny), "tiny lower Y rounded");
        require(Double.doubleToRawLongBits((Double) upper.get(1)) == Double.doubleToRawLongBits(tiny), "tiny upper Y rounded");
        double[][] matrix = identity(); matrix[3][0] = high;
        require(Double.doubleToRawLongBits(NoteEnvelopeMath.matrixRows(matrix).get(3).get(0))
                == Double.doubleToRawLongBits(high), "matrix translation rounded");
    }

    private static void zeroSpan() {
        rejected(() -> NoteEnvelopeMath.bounds(List.of(List.of(1.0, 0.0), List.of(1.0, 5.0),
                List.of(1.0, 10.0), List.of(1.0, 15.0))), "text_bounds_degenerate_zero_span");
        rejected(() -> NoteEnvelopeMath.bounds(List.of(List.of(0.0, 2.0), List.of(5.0, 2.0),
                List.of(10.0, 2.0), List.of(15.0, 2.0))), "text_bounds_degenerate_zero_span");
    }

    public static void main(String[] args) {
        switch (args[0]) {
            case "z": zCoupling(); break;
            case "affine": affine(); break;
            case "malformed": malformed(); break;
            case "corners": fourCorners(); break;
            case "precision": noRounding(); break;
            case "zero": zeroSpan(); break;
            default: throw new AssertionError("unknown fixed test");
        }
        System.out.println("{\"mode\":\"" + args[0] + "\",\"checks\":" + checks + ",\"native_calls\":0}");
    }
}
