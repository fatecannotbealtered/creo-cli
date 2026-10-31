"""geometry list, geometry measure: the faces, edges, axes, datum planes and coordinate systems
a feature or a constraint can reference, and the distance between two of them."""

from __future__ import annotations

import math

from .. import engine
from ..core import Error, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import NN, UNITS, B, N, S, array, listing, shape
from ..sketch import REFERENCE
from ..transport import Client
from ..validation import text, validate

KINDS = ("surface", "edge", "axis", "datum_plane", "csys")
TYPES = ("plane", "cylinder", "cone", "torus", "line", "arc", "circle", "spline", "bspline")
KIND_ORDER = {k: i for i, k in enumerate(("datum_plane", "csys", "axis", "surface", "edge"))}


def _point(raw: str) -> list:
    try:
        p = [float(v) for v in str(raw).split(",")]
    except ValueError:
        p = []
    if len(p) != 3 or not all(math.isfinite(v) for v in p):
        raise Error("E_VALIDATION", "--near is a model point x,y,z", {"path": "near"})
    return p


def _sub(a: list, b: list) -> list:
    return [x - y for x, y in zip(a, b, strict=True)]


def _dot(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _segment(p: list, a: list, b: list) -> float:
    ab = _sub(b, a)
    t = _dot(_sub(p, a), ab) / (_dot(ab, ab) or 1.0)
    t = min(1.0, max(0.0, t))
    return math.dist(p, [x + t * d for x, d in zip(a, ab, strict=True)])


def _cross(a: list, b: list) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _round(p: list, c: list, r: float, n: list, start: list, end: list, full: bool) -> float:
    """From a point to a circle or arc (counter-clockwise about its normal, start to end)."""
    length = math.sqrt(_dot(n, n)) or 1.0
    n = [v / length for v in n]
    q = _sub(p, c)
    h = _dot(q, n)
    flat = [x - h * y for x, y in zip(q, n, strict=True)]
    size = math.sqrt(_dot(flat, flat))
    if size < 1e-12:
        return math.sqrt(h * h + r * r)
    m = [cc + r * f / size for cc, f in zip(c, flat, strict=True)]
    if not full:
        u = _sub(start, c)
        u = [v / (math.sqrt(_dot(u, u)) or 1.0) for v in u]
        v = _cross(n, u)

        def angle(point: list) -> float:
            d = _sub(point, c)
            return math.atan2(_dot(d, v), _dot(d, u)) % (2 * math.pi)

        if angle(m) > angle(end) + 1e-9:
            return min(math.dist(p, start), math.dist(p, end))
    return math.dist(p, m)


def distance_to(item: dict, p: list) -> float | None:
    """How far a model point is from a piece of geometry as geometry list gives it: exactly
    for edges, datum planes, axes and coordinate systems; from a face's box for a face."""
    kind, shape_ = item.get("kind"), item.get("type")
    start, end = item.get("start"), item.get("end")
    if kind == "edge" and start and end:
        if shape_ in ("arc", "circle") and item.get("center") and item.get("normal"):
            return _round(
                p,
                item["center"],
                item.get("radius") or 0.0,
                item["normal"],
                start,
                end,
                shape_ == "circle",
            )
        if shape_ == "line":
            return _segment(p, start, end)
        return min(math.dist(p, start), math.dist(p, end))
    if kind == "surface":
        # Lower bounds of the true distance, the larger kept: the face's box, its plane, its
        # cylinder's axis.
        bounds = []
        if item.get("bbox"):
            low, high = item["bbox"]
            nearest = [min(max(v, lo), hi) for v, lo, hi in zip(p, low, high, strict=True)]
            bounds.append(math.dist(p, nearest))
        if shape_ == "plane" and item.get("normal") and item.get("origin"):
            n = item["normal"]
            bounds.append(abs(_dot(_sub(p, item["origin"]), n)) / (math.sqrt(_dot(n, n)) or 1.0))
        axis = item.get("axis") or {}
        if shape_ == "cylinder" and axis.get("origin") and axis.get("direction"):
            d = axis["direction"]
            cross = _cross(_sub(p, axis["origin"]), d)
            off = math.sqrt(_dot(cross, cross)) / (math.sqrt(_dot(d, d)) or 1.0)
            bounds.append(abs(off - (item.get("radius") or 0.0)))
        return max(bounds) if bounds else None
    if kind == "datum_plane" and item.get("normal") and item.get("origin"):
        n = item["normal"]
        return abs(_dot(_sub(p, item["origin"]), n)) / (math.sqrt(_dot(n, n)) or 1.0)
    if kind == "axis" and start and item.get("direction"):
        d = item["direction"]
        q = _sub(p, start)
        cross = _cross(q, d)
        return math.sqrt(_dot(cross, cross)) / (math.sqrt(_dot(d, d)) or 1.0)
    if kind == "csys" and item.get("origin"):
        return math.dist(p, item["origin"])
    return None


def list_geometry(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))
    near = _point(opts["near"]) if opts.get("near") else None
    query = {"model": name}
    if opts.get("kind"):
        query["kind"] = opts["kind"]
    if opts.get("feature"):
        validate(opts["feature"], text(pattern=r"^[A-Za-z0-9_-]{1,80}$", maximum=80), "feature")
        query["feature"] = opts["feature"]

    def fetch(client: Client) -> dict:
        data = engine.normalize(client.op("geometry.list", query))
        items = data["items"]
        if opts.get("type"):
            items = [i for i in items if i.get("type") == opts["type"]]
        items.sort(key=lambda i: (KIND_ORDER.get(i.get("kind"), 9), int(i.get("id") or 0)))
        if near is not None:
            # Nearest first: a face or an edge picked by where it is, as a person points.
            for i in items:
                d = distance_to(i, near)
                i["distance"] = None if d is None else round(d, 9)
            items.sort(key=lambda i: (i["distance"] is None, i["distance"] or 0.0))
        return page(items, opts["limit"], opts["offset"]) | {
            "model": data["model"],
            "units": data["units"],
            "_untrusted": ["items", "model"],
        }

    return engine.read(opts, fetch)


def measure(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))
    validate(opts["from"], REFERENCE, "from")
    validate(opts["to"], REFERENCE, "to")

    def fetch(client: Client) -> dict:
        data = engine.normalize(
            client.op("geometry.measure", {"model": name, "from": opts["from"], "to": opts["to"]})
        )
        return data | {"_untrusted": ["model", "from", "to"]}

    return engine.read(opts, fetch)


ITEM = shape(
    {
        "ref": S,
        "kind": S,
        "id": S,
        "type": {"type": ["string", "null"]},
        "feature": {"type": ["object", "null"]},
        "normal": array(N),
        "origin": array(N),
        "axis": shape({}),
        "radius": N,
        "outward": S,
        "area": NN,
        "bbox": array(array(N)),
        "surfaces": array(S),
        "start": array(N),
        "end": array(N),
        "length": N,
        "direction": array(N),
        "center": array(N),
        "distance": NN,
        "name": {"type": ["string", "null"]},
        "x_axis": array(N),
        "y_axis": array(N),
        "z_axis": array(N),
    },
    ("ref", "kind", "id"),
)
COMMANDS = [
    Command(
        "geometry list",
        "Faces, edges, axes, datum planes and coordinate systems with the reference strings "
        "features and constraints take, and where each is: normals, axes, end points, lengths, "
        "areas",
        list_geometry,
        listing(ITEM, model=S, units=UNITS),
        (
            MODEL,
            Param("kind", choices=KINDS, description="only this kind of geometry"),
            Param("type", choices=TYPES, description="only this shape: plane, cylinder, line, arc"),
            Param("feature", description="only the geometry this feature created (name or id)"),
            Param(
                "near",
                description="a model point x,y,z: nearest first, each with its distance -- a "
                "face's from its box, an edge's exactly",
            ),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items", "model"),
        example="--model block",
        service_ops=("geometry.list",),
        sort="datum planes, coordinate systems, axes, faces, edges; then by id; with --near, "
        "nearest first",
    ),
    Command(
        "geometry measure",
        "The shortest distance between two references, with the nearest point on each",
        measure,
        shape(
            {
                "model": S,
                "units": UNITS,
                "from": S,
                "to": S,
                "distance": N,
                "interfering": B,
                "nearest_points": array(array(N)),
            },
            ("model", "from", "to", "distance", "interfering"),
        ),
        (
            MODEL,
            Param(
                "from",
                required=True,
                description="a reference: a datum name or surface:<id>, edge:<id>",
            ),
            Param("to", required=True, description="a reference, as --from"),
        ),
        untrusted=("model", "from", "to"),
        example="--model block --from FRONT --to surface:53",
        service_ops=("geometry.measure",),
    ),
]
