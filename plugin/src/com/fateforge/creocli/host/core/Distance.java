package com.fateforge.creocli.host.core;

/**
 * The shortest distance between points, infinite lines and infinite planes. Creo's clearance
 * measures solid geometry only: between two datum planes it answers with a sentinel of about
 * 1e9 (measured on Creo 13.4). Datums are unbounded, as Creo's Measure tool treats them, so
 * two planes or a line and a plane that are not parallel are 0 apart.
 */
public final class Distance {
    private static final double PARALLEL = 1e-9;

    private Distance() {
    }

    /** A point, an infinite line through a point, or an infinite plane through a point. */
    public static final class Shape {
        final int kind; // 0 point, 1 line, 2 plane
        final double[] at;
        final double[] direction; // the line's direction or the plane's normal, unit length

        private Shape(int kind, double[] at, double[] direction) {
            this.kind = kind;
            this.at = at.clone();
            this.direction = direction == null ? null : unit(direction);
        }

        public static Shape point(double[] at) {
            return new Shape(0, at, null);
        }

        public static Shape line(double[] at, double[] direction) {
            return new Shape(1, at, direction);
        }

        public static Shape plane(double[] at, double[] normal) {
            return new Shape(2, at, normal);
        }
    }

    public static double between(Shape a, Shape b) {
        if (a.kind > b.kind) {
            Shape swap = a;
            a = b;
            b = swap;
        }
        double[] gap = minus(b.at, a.at);
        switch (a.kind * 3 + b.kind) {
            case 0: // point, point
                return length(gap);
            case 1: // point, line
                return length(cross(gap, b.direction));
            case 2: // point, plane
                return Math.abs(dot(gap, b.direction));
            case 4: { // line, line
                double[] normal = cross(a.direction, b.direction);
                double size = length(normal);
                return size < PARALLEL ? length(cross(gap, a.direction)) : Math.abs(dot(gap, normal)) / size;
            }
            case 5: // line, plane
                return Math.abs(dot(a.direction, b.direction)) < PARALLEL ? Math.abs(dot(gap, b.direction)) : 0.0;
            default: // plane, plane
                return length(cross(a.direction, b.direction)) < PARALLEL ? Math.abs(dot(gap, a.direction)) : 0.0;
        }
    }

    private static double[] unit(double[] v) {
        double size = length(v);
        if (!(size > 0)) {
            throw new IllegalArgumentException("a direction of zero length");
        }
        return new double[] {v[0] / size, v[1] / size, v[2] / size};
    }

    private static double[] minus(double[] a, double[] b) {
        return new double[] {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
    }

    private static double[] cross(double[] a, double[] b) {
        return new double[] {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
    }

    private static double dot(double[] a, double[] b) {
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    private static double length(double[] v) {
        return Math.sqrt(dot(v, v));
    }
}
