"""Closed sketch profiles: their request schemas, the checks Creo would reject, their areas.

A profile is drawn on a datum plane, in that plane's own 2D axes measured from where the
sketch references cross -- for RIGHT, TOP or FRONT of a template part, the part origin.

Every profile but an ellipse is one or more loops of lines and arcs: an outer loop, and the
holes inside it. Areas and centroids are exact (Green's theorem over each segment); arcs are
sampled only to check that an outline does not cross itself and that holes lie inside.
"""

from __future__ import annotations

import math
from typing import Any

from .core import Error
from .validation import NUM, POS, strict, text, validate

DATUM = text(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,30}$", maximum=31)
# Where a sketch goes: a datum plane by name, or a flat face of the part.
SKETCH_PLANE = text(pattern=r"^(?:surface:[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30})$", maximum=40)
FEATURE_NAME = text(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,30}$", maximum=31)
LENGTH_UNITS = text(enum=("mm", "cm", "m", "in", "ft"))
POINT = {"type": "array", "items": NUM, "minItems": 2, "maxItems": 2}
MAX_POLYGON_POINTS = 64
MAX_SEGMENTS = 64
MAX_HOLES = 32
DEFAULT_PLANES = ("RIGHT", "TOP", "FRONT")
# Profiles of several entities must be dimensioned to references projected from the
# model, which only the service's native sketch library can add. So must any with holes.
MULTI_ENTITY = {"rectangle", "polygon", "slot", "outline"}
# How finely (degrees) an arc is sampled for the crossing and containment checks.
SAMPLE_DEGREES = 10.0
TOLERANCE = 1e-9
# A spline segment passes through at most this many points between its ends.
MAX_SPLINE_THROUGH = 30

SHAPES = {
    "circle": ({"diameter": POS, "center": POINT}, ("diameter",)),
    "ellipse": ({"x_radius": POS, "y_radius": POS, "center": POINT}, ("x_radius", "y_radius")),
    "rectangle": (
        {"width": POS, "height": POS, "center": POINT, "corner_radius": POS},
        ("width", "height"),
    ),
    "polygon": (
        {
            "points": {
                "type": "array",
                "items": POINT,
                "minItems": 3,
                "maxItems": MAX_POLYGON_POINTS,
            }
        },
        ("points",),
    ),
    "slot": (
        {"centers": {"type": "array", "items": POINT, "minItems": 2, "maxItems": 2}, "width": POS},
        ("centers", "width"),
    ),
    "outline": (
        {
            "start": POINT,
            "segments": {
                "type": "array",
                "items": strict(
                    {
                        "to": POINT,
                        "sweep": {"type": "number", "minimum": -359.999, "maximum": 359.999},
                        "through": {
                            "type": "array",
                            "items": POINT,
                            "minItems": 1,
                            "maxItems": MAX_SPLINE_THROUGH,
                        },
                    },
                    ("to",),
                ),
                "minItems": 1,
                "maxItems": MAX_SEGMENTS,
            },
        },
        ("start", "segments"),
    ),
}
# Samples per span of a spline for its area and centroid; the crossing checks take every
# eighth.
SPLINE_SAMPLES = 128
SPLINE_CHECK_STRIDE = 8


def _solve(a: list, b: list) -> list:
    """Gaussian elimination with partial pivoting: a x = b, small and square."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        if abs(m[col][col]) < 1e-15:
            raise Error("E_VALIDATION", "a spline's points do not define a curve")
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _basis(i: int, p: int, u: float, knots: list) -> float:
    """The B-spline basis N(i, p) at u (Cox-de Boor); the last span includes its end."""
    if p == 0:
        last = u == knots[-1] and knots[i] < u <= knots[i + 1]
        return 1.0 if knots[i] <= u < knots[i + 1] or last else 0.0
    left = right = 0.0
    if knots[i + p] != knots[i]:
        left = (u - knots[i]) / (knots[i + p] - knots[i]) * _basis(i, p - 1, u, knots)
    if knots[i + p + 1] != knots[i + 1]:
        right = (
            (knots[i + p + 1] - u)
            / (knots[i + p + 1] - knots[i + 1])
            * _basis(i + 1, p - 1, u, knots)
        )
    return left + right


def spline_points(points: list, per_span: int = SPLINE_SAMPLES) -> list[list[float]]:
    """Points along the spline Creo's sketcher draws through these points, ends free:
    modeled as the cubic B-spline (quadratic through three) interpolating them at their
    chord-length parameters, with averaged knots. Measured against Creo 13.4: its areas
    agree within 1e-6 for evenly spaced points, within 5e-4 for unevenly spaced ones."""
    n = len(points) - 1
    p = min(3, n)
    chords = [math.dist(points[k], points[k + 1]) for k in range(n)]
    total = sum(chords)
    params = [0.0]
    for c in chords:
        params.append(params[-1] + c / total)
    params[-1] = 1.0
    knots = [0.0] * (p + 1)
    knots += [sum(params[j : j + p]) / p for j in range(1, n - p + 1)]
    knots += [1.0] * (p + 1)
    basis = [[_basis(i, p, u, knots) for i in range(n + 1)] for u in params]
    cx = _solve(basis, [pt[0] for pt in points])
    cy = _solve(basis, [pt[1] for pt in points])
    out = []
    steps = per_span * n
    for k in range(steps + 1):
        u = k / steps
        weights = [_basis(i, p, u, knots) for i in range(n + 1)]
        out.append(
            [
                sum(w * c for w, c in zip(weights, cx, strict=True)),
                sum(w * c for w, c in zip(weights, cy, strict=True)),
            ]
        )
    out[0], out[-1] = list(points[0]), list(points[-1])
    return out


def has_spline(profile: dict) -> bool:
    return any("through" in seg for seg in profile.get("segments") or []) or any(
        has_spline(h) for h in profile.get("holes") or []
    )


# What an inner loop may be: anything the native library draws, without holes of its own.
HOLE_TYPES = ("circle", "rectangle", "polygon", "slot", "outline")


def _shape(kind: str, holes: bool) -> dict:
    properties, required = SHAPES[kind]
    extra = {}
    if holes:
        extra["holes"] = {
            "type": "array",
            "items": {"oneOf": [_shape(k, False) for k in HOLE_TYPES], "discriminator": "type"},
            "minItems": 1,
            "maxItems": MAX_HOLES,
        }
    return strict({"type": text(enum=(kind,))} | properties | extra, ("type", *required))


PROFILES = {kind: _shape(kind, kind != "ellipse") for kind in SHAPES}
HOLES = {kind: _shape(kind, False) for kind in HOLE_TYPES}


def sketch_schema(profile: dict) -> dict:
    return strict(
        {
            "plane": SKETCH_PLANE,
            "orient_ref": SKETCH_PLANE,
            "orient": text(enum=("right", "left", "up", "down")),
            "references": {"type": "array", "items": DATUM, "minItems": 2, "maxItems": 2},
            "profile": profile,
        },
        ("plane", "orient_ref", "profile"),
    )


def extrude_schema(profile: dict) -> dict:
    return strict(
        {
            "units": LENGTH_UNITS,
            "sketch": sketch_schema(profile),
            "depth": POS,
            "side": text(enum=("one", "two", "symmetric")),
            "material": text(enum=("add", "remove")),
            "name": FEATURE_NAME,
            "body": text(enum=("default", "new")),
        },
        ("units", "sketch", "depth"),
    )


EXTRUDE_SCHEMA = extrude_schema({"oneOf": list(PROFILES.values()), "discriminator": "type"})
EXTRUDE_EXAMPLE = {
    "units": "mm",
    "name": "BLOCK",
    "depth": 10,
    "sketch": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "profile": {"type": "rectangle", "width": 40, "height": 20},
    },
}


def needs_native(profile: dict) -> bool:
    """Whether only the native library can draw the profile: several entities, or holes."""
    return profile["type"] in MULTI_ENTITY or bool(profile.get("holes"))


def validate_extrude(request: Any) -> dict:
    """The request, checked in full; everything Creo would reject for shape, refused here."""
    if not isinstance(request, dict):
        raise Error("E_VALIDATION", "wrong value type", {"path": "request", "expected": ["object"]})
    sketch = request.get("sketch")
    profile = sketch.get("profile") if isinstance(sketch, dict) else None
    kind = profile.get("type") if isinstance(profile, dict) else None
    if kind not in PROFILES:
        raise Error(
            "E_VALIDATION",
            "sketch.profile.type must name a supported profile",
            {"path": "request.sketch.profile.type", "allowed": sorted(PROFILES)},
        )
    # Each hole by its own type first, so a wrong one is named, not "none of the forms".
    holes = profile.get("holes") if kind != "ellipse" else None
    if isinstance(holes, list):
        for i, hole in enumerate(holes):
            where = f"request.sketch.profile.holes[{i}]"
            hole_kind = hole.get("type") if isinstance(hole, dict) else None
            if hole_kind not in HOLES:
                raise Error(
                    "E_VALIDATION",
                    "a hole is one of the profiles the native library draws",
                    {"path": where + ".type", "allowed": list(HOLE_TYPES)},
                )
            validate(hole, HOLES[hole_kind], where)
    validate(request, extrude_schema(PROFILES[kind]))
    s = request["sketch"]
    check_planes(s)
    if request.get("material") == "remove" and request.get("body") == "new":
        raise Error(
            "E_VALIDATION",
            "a cut removes material from existing bodies; it cannot make a new body",
            {"path": "request.body"},
        )
    check_profile(s["profile"], "request.sketch.profile")
    return dict(request)


def check_planes(s: dict) -> None:
    """A sketch's orientation reference and dimensioning references are other planes."""
    plane, orient = s["plane"].upper(), s["orient_ref"].upper()
    if plane == orient:
        raise Error(
            "E_VALIDATION",
            "the orientation reference must be a different plane from the sketch plane",
            {"path": "request.sketch.orient_ref"},
        )
    if "references" in s:
        refs = [r.upper() for r in s["references"]]
        if refs[0] == refs[1] or plane in refs:
            raise Error(
                "E_VALIDATION",
                "references must be two different planes, neither of them the sketch plane",
                {"path": "request.sketch.references"},
            )


# ------------------------------------------------------------------ ribs

RIB_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "sketch": strict(
            {
                "plane": SKETCH_PLANE,
                "orient_ref": SKETCH_PLANE,
                "orient": text(enum=("right", "left", "up", "down")),
                "references": {"type": "array", "items": DATUM, "minItems": 2, "maxItems": 2},
                "points": {
                    "type": "array",
                    "items": POINT,
                    "minItems": 2,
                    "maxItems": MAX_SEGMENTS + 1,
                },
            },
            ("plane", "orient_ref", "points"),
        ),
        "thickness": POS,
        "side": text(enum=("symmetric", "one", "two")),
        "fill": text(enum=("right", "left")),
    },
    ("units", "sketch", "thickness"),
)
RIB_EXAMPLE = {
    "units": "mm",
    "name": "CENTER_RIB",
    "thickness": 2,
    "side": "symmetric",
    "fill": "left",
    "sketch": {"plane": "TOP", "orient_ref": "RIGHT", "points": [[-15, 6], [15, 6]]},
}


def validate_rib(request: Any) -> dict:
    """A rib's sketch is an open chain of lines: each leg of some length, none crossing
    another, and not closed -- the part closes the region it fills."""
    validate(request, RIB_SCHEMA)
    s = request["sketch"]
    check_planes(s)
    points = s["points"]
    where = "request.sketch.points"
    for i in range(1, len(points)):
        if math.dist(points[i - 1], points[i]) <= TOLERANCE:
            raise Error(
                "E_VALIDATION",
                "a leg of the chain must have some length",
                {"path": f"{where}[{i}]"},
            )
    if len(points) > 2 and math.dist(points[0], points[-1]) <= TOLERANCE:
        raise Error(
            "E_VALIDATION",
            "a rib's chain is open; the faces of the part close the region it fills",
            {"path": where},
        )
    legs = list(zip(points, points[1:], strict=False))
    for i, (a, b) in enumerate(legs):
        for j in range(i + 1, len(legs)):
            c, d = legs[j]
            if j == i + 1:
                # Neighbours share a point; they cross only if one doubles back along the other.
                turn = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
                back = (b[0] - a[0]) * (d[0] - c[0]) + (b[1] - a[1]) * (d[1] - c[1])
                if abs(turn) <= 1e-12 and back < 0:
                    raise Error(
                        "E_VALIDATION",
                        "the chain doubles back on itself",
                        {"path": where, "legs": [i, j]},
                    )
            elif crossing(a, b, c, d):
                raise Error(
                    "E_VALIDATION",
                    "the chain crosses or touches itself",
                    {"path": where, "legs": [i, j]},
                )
    return dict(request)


def chain_length(points: list) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


# ------------------------------------------------------------------ sweeps

SWEPT_SHAPES = ("circle", "rectangle", "polygon", "slot", "outline")
PATH = strict(
    {
        "plane": SKETCH_PLANE,
        "orient_ref": SKETCH_PLANE,
        "orient": text(enum=("right", "left", "up", "down")),
        "references": {"type": "array", "items": DATUM, "minItems": 2, "maxItems": 2},
        "start": POINT,
        "segments": {
            "type": "array",
            "items": strict(
                {"to": POINT, "sweep": {"type": "number", "minimum": -359.999, "maximum": 359.999}},
                ("to",),
            ),
            "minItems": 1,
            "maxItems": MAX_SEGMENTS,
        },
    },
    ("plane", "orient_ref", "start", "segments"),
)


def sweep_schema(section: dict) -> dict:
    return strict(
        {
            "units": LENGTH_UNITS,
            "name": FEATURE_NAME,
            "path": PATH,
            "section": section,
            "material": text(enum=("add", "remove")),
        },
        ("units", "path", "section"),
    )


SWEEP_SCHEMA = sweep_schema({"oneOf": [PROFILES[k] for k in SWEPT_SHAPES], "discriminator": "type"})
SWEEP_EXAMPLE = {
    "units": "mm",
    "name": "PIPE",
    "path": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "start": [0, 0],
        "segments": [{"to": [0, 40]}, {"to": [20, 60], "sweep": -90}, {"to": [60, 60]}],
    },
    "section": {"type": "circle", "diameter": 10},
}


def path_segments(path: dict) -> list[tuple]:
    """The path as ("line", x0, y0, x1, y1) and ("arc", cx, cy, r, t0, sweep) segments, open."""
    x, y = path["start"]
    out = []
    for seg in path["segments"]:
        tx, ty = seg["to"]
        if "sweep" in seg:
            out.append(_arc(x, y, tx, ty, math.radians(seg["sweep"])))
        else:
            out.append(("line", x, y, tx, ty))
        x, y = tx, ty
    return out


def path_length(path: dict) -> float:
    return sum(
        math.hypot(s[3] - s[1], s[4] - s[2]) if s[0] == "line" else abs(s[3] * s[5])
        for s in path_segments(path)
    )


def path_turn(path: dict) -> float:
    """How far the path turns from start to end, radians, counter-clockwise as its sketch is
    seen: its arcs' turns, a smooth path having no corners."""
    return sum(math.radians(seg.get("sweep", 0)) for seg in path["segments"])


def _directions(x0: float, y0: float, seg: dict) -> tuple[float, float]:
    """A segment's direction where it starts and where it ends, as angles: a line's own; an
    arc's, its chord's turned back and on by half the arc."""
    tx, ty = seg["to"]
    chord = math.atan2(ty - y0, tx - x0)
    half = math.radians(seg.get("sweep", 0)) / 2
    return chord - half, chord + half


def path_start_tangent(path: dict) -> list[float]:
    """The path's direction where it starts, a unit vector in the sketch's own axes."""
    angle = _directions(*path["start"], path["segments"][0])[0]
    return [math.cos(angle), math.sin(angle)]


def _u_range(profile: dict) -> tuple[float, float]:
    """The section's least and greatest u, exactly: arcs reach past their ends."""
    us = []
    for seg in _loop(profile):
        if seg[0] == "line":
            us += [seg[1], seg[3]]
            continue
        if seg[0] == "spline":
            us += [pt[0] for pt in seg[1]]
            continue
        _, cx, _cy, r, t0, sweep = seg
        us += [cx + r * math.cos(t0), cx + r * math.cos(t0 + sweep)]
        lo, hi = min(t0, t0 + sweep), max(t0, t0 + sweep)
        for extreme in (0.0, math.pi):
            k = math.ceil((lo - extreme) / (2 * math.pi))
            if extreme + 2 * math.pi * k <= hi:
                us.append(cx + r * math.cos(extreme))
    return min(us), max(us)


def swept_volume(path: dict, section: dict) -> float:
    """Pappus: the section's area times how far its centroid travels -- the path's length,
    less the centroid's offset toward the side the path turns to times the turn."""
    gx, _gy = centroid(section)
    return area(section) * (path_length(path) - gx * path_turn(path))


def validate_sweep(request: Any) -> dict:
    """A sweep: a smooth open path of lines and arcs that does not cross itself, and a closed
    section, holes aside, that no arc of the path turns about a point inside."""
    if not isinstance(request, dict):
        raise Error("E_VALIDATION", "wrong value type", {"path": "request", "expected": ["object"]})
    section = request.get("section")
    kind = section.get("type") if isinstance(section, dict) else None
    if kind not in SWEPT_SHAPES:
        raise Error(
            "E_VALIDATION",
            "a sweep's section is a circle, rectangle, polygon, slot or outline",
            {"path": "request.section.type", "allowed": list(SWEPT_SHAPES)},
        )
    validate(request, sweep_schema(PROFILES[kind]))
    if section.get("holes"):
        raise Error(
            "E_VALIDATION", "a sweep's section has no holes", {"path": "request.section.holes"}
        )
    path = request["path"]
    check_planes(path)
    x, y = path["start"]
    ending = None
    for i, seg in enumerate(path["segments"]):
        where = f"request.path.segments[{i}]"
        tx, ty = seg["to"]
        if math.hypot(tx - x, ty - y) <= TOLERANCE:
            raise Error(
                "E_VALIDATION",
                "a segment of the path ends away from where it starts",
                {"path": where},
            )
        if "sweep" in seg and abs(seg["sweep"]) <= 1e-9:
            raise Error("E_VALIDATION", "an arc turns through some angle", {"path": where})
        starting, then = _directions(x, y, seg)
        if ending is not None:
            corner = math.degrees(math.remainder(starting - ending, 2 * math.pi))
            if abs(corner) > 1e-6:
                raise Error(
                    "E_VALIDATION",
                    "a sweep's path turns smoothly: this segment starts in another direction "
                    "than the one before ends -- round the corner with an arc",
                    {"path": where, "corner_deg": corner},
                )
        ending = then
        x, y = tx, ty
    if math.hypot(x - path["start"][0], y - path["start"][1]) <= TOLERANCE:
        raise Error(
            "E_VALIDATION",
            "a sweep's path is open: it ends away from its start",
            {"path": "request.path"},
        )
    segments = path_segments(path)
    points = _samples(segments) + [list(path["segments"][-1]["to"])]
    legs = list(zip(points, points[1:], strict=False))
    for i, (a, b) in enumerate(legs):
        for j in range(i + 2, len(legs)):
            if crossing(a, b, *legs[j]):
                raise Error("E_VALIDATION", "the path crosses itself", {"path": "request.path"})
    check_profile(section, "request.section")
    # The section's u runs left of the path; an arc turning left turns about a point r to the
    # left, one turning right about a point r to the right. A section reaching past it would
    # sweep through itself.
    u_min, u_max = _u_range(section)
    for i, seg in enumerate(segments):
        if seg[0] == "arc" and (
            (seg[5] > 0 and u_max >= seg[3]) or (seg[5] < 0 and -u_min >= seg[3])
        ):
            raise Error(
                "E_VALIDATION",
                "the section reaches past the centre an arc of the path turns about: make the "
                "arc's radius larger than the section's reach toward its centre",
                {
                    "path": f"request.path.segments[{i}]",
                    "radius": seg[3],
                    "reach": u_max if seg[5] > 0 else -u_min,
                },
            )
    return dict(request)


# ------------------------------------------------------------------ loops


def loops(profile: dict) -> list[list[tuple]]:
    """The profile's loops, the outer one first: each a list of ("line", x0, y0, x1, y1) and
    ("arc", cx, cy, r, t0, sweep) segments, sweep in radians and signed (positive turns
    counter-clockwise), end to end."""
    return [_loop(profile)] + [_loop(h) for h in profile.get("holes") or []]


def _loop(p: dict) -> list[tuple]:
    kind = p["type"]
    cx, cy = p.get("center", [0, 0])
    if kind == "circle":
        return [("arc", cx, cy, p["diameter"] / 2, 0.0, 2 * math.pi)]
    if kind == "polygon":
        pts = p["points"]
        return [("line", *pts[i], *pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    if kind == "rectangle":
        w, h, r = p["width"] / 2, p["height"] / 2, p.get("corner_radius") or 0.0
        if r <= 0:
            corners = [[cx - w, cy - h], [cx + w, cy - h], [cx + w, cy + h], [cx - w, cy + h]]
            return [("line", *corners[i], *corners[(i + 1) % 4]) for i in range(4)]
        x0, x1, y0, y1 = cx - w, cx + w, cy - h, cy + h
        half = math.pi / 2
        return [
            ("line", x0 + r, y0, x1 - r, y0),
            ("arc", x1 - r, y0 + r, r, -half, half),
            ("line", x1, y0 + r, x1, y1 - r),
            ("arc", x1 - r, y1 - r, r, 0.0, half),
            ("line", x1 - r, y1, x0 + r, y1),
            ("arc", x0 + r, y1 - r, r, half, half),
            ("line", x0, y1 - r, x0, y0 + r),
            ("arc", x0 + r, y0 + r, r, math.pi, half),
        ]
    if kind == "slot":
        (ax, ay), (bx, by) = p["centers"]
        length = math.hypot(bx - ax, by - ay)
        dx, dy = (bx - ax) / length, (by - ay) / length
        nx, ny, r = -dy, dx, p["width"] / 2
        side = math.atan2(-ny, -nx)
        return [
            ("line", ax - nx * r, ay - ny * r, bx - nx * r, by - ny * r),
            ("arc", bx, by, r, side, math.pi),
            ("line", bx + nx * r, by + ny * r, ax + nx * r, ay + ny * r),
            ("arc", ax, ay, r, side + math.pi, math.pi),
        ]
    # outline
    x, y = p["start"]
    out = []
    for seg in p["segments"]:
        tx, ty = seg["to"]
        if "sweep" in seg:
            out.append(_arc(x, y, tx, ty, math.radians(seg["sweep"])))
        elif "through" in seg:
            out.append(("spline", spline_points([[x, y], *seg["through"], [tx, ty]])))
        else:
            out.append(("line", x, y, tx, ty))
        x, y = tx, ty
    sx, sy = p["start"]
    if math.hypot(sx - x, sy - y) > TOLERANCE:
        out.append(("line", x, y, sx, sy))
    return out


def _arc(x0: float, y0: float, x1: float, y1: float, sweep: float) -> tuple:
    """The arc from one point to another turning through sweep (radians, positive
    counter-clockwise): its centre lies off the chord's middle, left of it for a
    counter-clockwise arc of less than half a turn."""
    chord = math.hypot(x1 - x0, y1 - y0)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    lx, ly = -(y1 - y0) / chord, (x1 - x0) / chord
    d = (chord / 2) / math.tan(sweep / 2)
    cx, cy = mx + lx * d, my + ly * d
    r = (chord / 2) / abs(math.sin(sweep / 2))
    return ("arc", cx, cy, r, math.atan2(y0 - cy, x0 - cx), sweep)


def _integrals(loop: list[tuple]) -> tuple[float, float, float]:
    """Signed area and first moments of a closed loop, by Green's theorem segment by
    segment: A = 1/2 (x dy - y dx), Mx = 1/2 x^2 dy, My = -1/2 y^2 dx."""
    a = mx = my = 0.0
    for seg in _lines_of_splines(loop):
        if seg[0] == "line":
            _, x0, y0, x1, y1 = seg
            dx, dy = x1 - x0, y1 - y0
            a += (x0 * y1 - x1 * y0) / 2
            mx += dy * (x0 * x0 + x0 * dx + dx * dx / 3) / 2
            my -= dx * (y0 * y0 + y0 * dy + dy * dy / 3) / 2
        else:
            _, cx, cy, r, t0, sweep = seg
            t1 = t0 + sweep
            s0, s1, c0, c1 = math.sin(t0), math.sin(t1), math.cos(t0), math.cos(t1)
            a += (cx * r * (s1 - s0) - cy * r * (c1 - c0) + r * r * sweep) / 2
            cos2 = sweep / 2 + (math.sin(2 * t1) - math.sin(2 * t0)) / 4
            sin2 = sweep / 2 - (math.sin(2 * t1) - math.sin(2 * t0)) / 4
            cos3 = (s1 - s1**3 / 3) - (s0 - s0**3 / 3)
            sin3 = (-c1 + c1**3 / 3) - (-c0 + c0**3 / 3)
            mx += (cx * cx * r * (s1 - s0) + 2 * cx * r * r * cos2 + r**3 * cos3) / 2
            my += (cy * cy * r * (-c1 + c0) + 2 * cy * r * r * sin2 + r**3 * sin3) / 2
    return a, mx, my


def _lines_of_splines(loop: list[tuple]) -> list[tuple]:
    """The loop with each spline as the short lines between its samples."""
    out = []
    for seg in loop:
        if seg[0] == "spline":
            pts = seg[1]
            out += [("line", *a, *b) for a, b in zip(pts, pts[1:], strict=False)]
        else:
            out.append(seg)
    return out


def _samples(loop: list[tuple]) -> list[list[float]]:
    """Points along a loop, each segment's start and, for an arc or a spline, points
    between."""
    out = []
    for seg in loop:
        if seg[0] == "line":
            out.append([seg[1], seg[2]])
        elif seg[0] == "spline":
            out += [list(pt) for pt in seg[1][:-1:SPLINE_CHECK_STRIDE]]
        else:
            _, cx, cy, r, t0, sweep = seg
            n = max(4, math.ceil(abs(math.degrees(sweep)) / SAMPLE_DEGREES))
            for k in range(n):
                t = t0 + sweep * k / n
                out.append([cx + r * math.cos(t), cy + r * math.sin(t)])
    return out


def _ellipse_samples(p: dict) -> list[list[float]]:
    cx, cy = p.get("center", [0, 0])
    return [
        [cx + p["x_radius"] * math.cos(a), cy + p["y_radius"] * math.sin(a)]
        for a in (k * math.pi / 32 for k in range(64))
    ]


# ------------------------------------------------------------------ checks


def check_profile(profile: dict, where: str) -> None:
    """What Creo would reject in a profile's shape: degenerate or crossing loops, holes that
    do not lie apart inside the outer loop."""
    _check_one(profile, where)
    holes = profile.get("holes") or []
    for i, hole in enumerate(holes):
        _check_one(hole, f"{where}.holes[{i}]")
    if not holes:
        return
    outer = _samples(_loop(profile))
    inner = [_samples(_loop(h)) for h in holes]
    for i, ring in enumerate(inner):
        at = {"path": f"{where}.holes[{i}]"}
        if not all(_inside(pt, outer) for pt in ring) or _rings_cross(ring, outer):
            raise Error("E_VALIDATION", "a hole must lie wholly inside the outer loop", at)
        for j in range(i):
            other = inner[j]
            if _rings_cross(ring, other) or _inside(ring[0], other) or _inside(other[0], ring):
                raise Error(
                    "E_VALIDATION",
                    "holes must lie apart, neither inside the other",
                    at | {"with": j},
                )


def _check_one(p: dict, where: str) -> None:
    kind = p["type"]
    at = {"path": where}
    if kind == "polygon":
        polygon(p["points"], where + ".points")
    elif kind == "rectangle" and p.get("corner_radius"):
        if not p["corner_radius"] < min(p["width"], p["height"]) / 2:
            raise Error(
                "E_VALIDATION",
                "a corner radius is less than half the rectangle's shorter side",
                {"path": where + ".corner_radius"},
            )
    elif kind == "slot":
        (ax, ay), (bx, by) = p["centers"]
        if math.hypot(bx - ax, by - ay) <= TOLERANCE:
            raise Error(
                "E_VALIDATION", "a slot's two centres must differ", {"path": where + ".centers"}
            )
    elif kind == "outline":
        x, y = p["start"]
        for i, seg in enumerate(p["segments"]):
            tx, ty = seg["to"]
            if math.hypot(tx - x, ty - y) <= TOLERANCE:
                raise Error(
                    "E_VALIDATION",
                    "a segment must end away from where it starts",
                    {"path": f"{where}.segments[{i}]"},
                )
            if "sweep" in seg and abs(seg["sweep"]) <= 1e-9:
                raise Error(
                    "E_VALIDATION",
                    "an arc turns through some angle; leave out sweep for a line",
                    {"path": f"{where}.segments[{i}].sweep"},
                )
            if "sweep" in seg and "through" in seg:
                raise Error(
                    "E_VALIDATION",
                    "a segment is a line, an arc (sweep) or a spline (through), one of them",
                    {"path": f"{where}.segments[{i}]"},
                )
            if "through" in seg:
                chain = [[x, y], *seg["through"], [tx, ty]]
                if any(
                    math.dist(a, b) <= TOLERANCE for a, b in zip(chain, chain[1:], strict=False)
                ):
                    raise Error(
                        "E_VALIDATION",
                        "a spline passes through each of its points once: no two in a row the same",
                        {"path": f"{where}.segments[{i}].through"},
                    )
            x, y = tx, ty
        ring = _samples(_loop(p))
        if _ring_crosses_itself(ring):
            raise Error(
                "E_VALIDATION",
                "the outline crosses or touches itself; Creo cannot extrude it",
                at,
            )
    if kind != "ellipse" and abs(_integrals(_loop(p))[0]) <= 1e-12:
        raise Error("E_VALIDATION", "the profile encloses no area", at)


def polygon(points: list, where: str = "request.sketch.profile.points") -> None:
    """A simple polygon: no repeated vertex, no fold-back, no crossing edges, an area."""
    n = len(points)
    at = {"path": where}
    for i in range(n):
        for j in range(i + 1, n):
            if math.isclose(points[i][0], points[j][0], abs_tol=1e-9) and math.isclose(
                points[i][1], points[j][1], abs_tol=1e-9
            ):
                raise Error(
                    "E_VALIDATION", "polygon vertices must all differ", at | {"vertices": [i, j]}
                )
    for i in range(n):
        a, b, c = points[i - 1], points[i], points[(i + 1) % n]
        turn = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        back = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1])
        if abs(turn) <= 1e-12 and back < 0:
            raise Error(
                "E_VALIDATION", "polygon doubles back on itself at a vertex", at | {"vertex": i}
            )
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if crossing(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n]):
                raise Error(
                    "E_VALIDATION",
                    "polygon edges must not cross or touch; Creo cannot extrude a "
                    "self-intersecting outline",
                    at | {"edges": [i, j]},
                )
    if abs(_integrals(_loop({"type": "polygon", "points": points}))[0]) <= 1e-12:
        raise Error("E_VALIDATION", "polygon encloses no area", at)


def crossing(a, b, c, d) -> bool:
    def side(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) <= 1e-12 else (1 if v > 0 else -1)

    def within(p, q, r):
        return (
            min(p[0], q[0]) - 1e-12 <= r[0] <= max(p[0], q[0]) + 1e-12
            and min(p[1], q[1]) - 1e-12 <= r[1] <= max(p[1], q[1]) + 1e-12
        )

    s1, s2, s3, s4 = side(a, b, c), side(a, b, d), side(c, d, a), side(c, d, b)
    if s1 != s2 and s3 != s4 and 0 not in (s1, s2, s3, s4):
        return True
    return (
        (s1 == 0 and within(a, b, c))
        or (s2 == 0 and within(a, b, d))
        or (s3 == 0 and within(c, d, a))
        or (s4 == 0 and within(c, d, b))
    )


def _edges(ring: list) -> list[tuple]:
    return [(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring))]


def _apart(a: tuple, b: tuple) -> bool:
    """Two edges whose boxes do not meet cannot cross: the quick test before the exact one."""
    (p, q), (r, s) = a, b
    return (
        max(p[0], q[0]) < min(r[0], s[0]) - 1e-12
        or max(r[0], s[0]) < min(p[0], q[0]) - 1e-12
        or max(p[1], q[1]) < min(r[1], s[1]) - 1e-12
        or max(r[1], s[1]) < min(p[1], q[1]) - 1e-12
    )


def _ring_crosses_itself(ring: list) -> bool:
    edges = _edges(ring)
    n = len(edges)
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            if not _apart(edges[i], edges[j]) and crossing(*edges[i], *edges[j]):
                return True
    return False


def _rings_cross(a: list, b: list) -> bool:
    return any(not _apart(e, f) and crossing(*e, *f) for e in _edges(a) for f in _edges(b))


def _inside(pt: list, ring: list) -> bool:
    """Even-odd: whether a point lies inside a closed ring of points."""
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in _edges(ring):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


# ------------------------------------------------------------------ measures


def area(profile: dict) -> float:
    """The profile's area: the outer loop's less its holes'."""
    if profile["type"] == "ellipse":
        return math.pi * profile["x_radius"] * profile["y_radius"]
    outer, *holes = loops(profile)
    return abs(_integrals(outer)[0]) - sum(abs(_integrals(h)[0]) for h in holes)


def centroid(profile: dict) -> tuple[float, float]:
    if profile["type"] == "ellipse":
        c = profile.get("center", [0, 0])
        return float(c[0]), float(c[1])
    total = gx = gy = 0.0
    for i, loop in enumerate(loops(profile)):
        a, mx, my = _integrals(loop)
        weight = abs(a) * (1 if i == 0 else -1)
        total += weight
        gx += weight * mx / a
        gy += weight * my / a
    return gx / total, gy / total


def entities(profile: dict) -> int:
    """How many sketch entities the profile is drawn with."""
    if profile["type"] == "ellipse":
        return 1
    return sum(len(loop) for loop in loops(profile))


# ------------------------------------------------------------------ revolve

AXIS_POINTS = {"type": "array", "items": POINT, "minItems": 2, "maxItems": 2}
REFERENCE = text(
    pattern=r"^(?:(?:[sS][uU][rR][fF][aA][cC][eE]|[eE][dD][gG][eE]|[aA][xX][iI][sS]):"
    r"[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30})$",
    maximum=40,
)


def revolve_schema(profile: dict) -> dict:
    return strict(
        {
            "units": LENGTH_UNITS,
            "sketch": sketch_schema(profile),
            "axis": {"oneOf": [AXIS_POINTS, REFERENCE]},
            "angle": {"type": "number", "exclusiveMinimum": 0, "maximum": 360},
            "side": text(enum=("one", "two", "symmetric")),
            "material": text(enum=("add", "remove")),
            "name": FEATURE_NAME,
            "body": text(enum=("default", "new")),
        },
        ("units", "sketch", "axis", "angle"),
    )


REVOLVE_SCHEMA = revolve_schema({"oneOf": list(PROFILES.values()), "discriminator": "type"})
REVOLVE_EXAMPLE = {
    "units": "mm",
    "name": "SHAFT",
    "angle": 360,
    "axis": [[0, 0], [0, 1]],
    "sketch": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "profile": {
            "type": "polygon",
            "points": [[0, 0], [10, 0], [10, 20], [6, 20], [6, 40], [0, 40]],
        },
    },
}


def validate_revolve(request: Any) -> dict:
    """A revolve request: the extrusion's sketch checks, and a profile on one side of its axis."""
    if not isinstance(request, dict):
        raise Error("E_VALIDATION", "wrong value type", {"path": "request", "expected": ["object"]})
    probe = {k: v for k, v in request.items() if k not in ("axis", "angle")} | {"depth": 1}
    checked = validate_extrude(probe)
    kind = checked["sketch"]["profile"]["type"]
    validate(request, revolve_schema(PROFILES[kind]))
    axis = request["axis"]
    if isinstance(axis, list):
        (x0, y0), (x1, y1) = axis
        if math.hypot(x1 - x0, y1 - y0) <= 1e-12:
            raise Error(
                "E_VALIDATION", "the axis needs two different points", {"path": "request.axis"}
            )
        sides = {_side(axis, p) for p in _outline(checked["sketch"]["profile"])} - {0}
        if len(sides) > 1:
            raise Error(
                "E_VALIDATION",
                "the profile crosses its axis; a revolved profile lies on one side of it",
                {"path": "request.sketch.profile"},
            )
    return dict(request)


def bounds(profile: dict) -> list[list[float]]:
    """The profile's box in the sketch's own axes: [[u_min, v_min], [u_max, v_max]]."""
    points = _outline(profile)
    us, vs = [p[0] for p in points], [p[1] for p in points]
    return [[min(us), min(vs)], [max(us), max(vs)]]


def _outline(profile: dict) -> list:
    """Points that bound the profile, enough to tell which side of a line it lies on."""
    if profile["type"] == "ellipse":
        return _ellipse_samples(profile)
    return _samples(_loop(profile))


def _side(axis: list, p: list) -> int:
    (x0, y0), (x1, y1) = axis
    v = (x1 - x0) * (p[1] - y0) - (y1 - y0) * (p[0] - x0)
    return 0 if abs(v) <= 1e-9 else (1 if v > 0 else -1)


def revolved_volume(profile: dict, axis: list, angle: float) -> float:
    """Pappus: area times the distance its centroid travels about the axis."""
    (x0, y0), (x1, y1) = axis
    gx, gy = centroid(profile)
    r = abs((x1 - x0) * (gy - y0) - (y1 - y0) * (gx - x0)) / math.hypot(x1 - x0, y1 - y0)
    return area(profile) * r * math.radians(angle)
