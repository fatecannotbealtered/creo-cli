"""Request schemas for the features placed on existing geometry, and the datums.

Every reference is a string: a datum's name as the model tree shows it (FRONT, A_1), or
surface:<id>, edge:<id>, axis:<id> as `geometry list` reports them. Every length travels
with the request's `units`, which must be the model's own length unit; angles are degrees.
"""

from __future__ import annotations

from typing import Any

from .core import Error
from .sketch import FEATURE_NAME, LENGTH_UNITS, REFERENCE
from .validation import NUM, POS, strict, text, validate

REFS = {"type": "array", "items": REFERENCE, "minItems": 1, "maxItems": 200}
ANGLE = {"type": "number", "minimum": -360, "maximum": 360}
COUNT = {"type": "integer", "minimum": 2, "maximum": 500}


def _refs_distinct(refs: list, path: str) -> None:
    if len({r.upper() for r in refs}) != len(refs):
        raise Error("E_VALIDATION", "a reference is listed twice", {"path": path})


# ------------------------------------------------------------------ datums

DATUM_PLANE_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "offset": strict({"from": REFERENCE, "distance": NUM}, ("from", "distance")),
        "angle": strict(
            {"through": REFERENCE, "from": REFERENCE, "degrees": ANGLE},
            ("through", "from", "degrees"),
        ),
    },
    ("units",),
)
DATUM_PLANE_EXAMPLE = {"units": "mm", "name": "MID", "offset": {"from": "FRONT", "distance": -5}}


def validate_datum_plane(request: Any) -> dict:
    validate(request, DATUM_PLANE_SCHEMA)
    if ("offset" in request) == ("angle" in request):
        raise Error("E_VALIDATION", "give exactly one of offset or angle", {"path": "request"})
    return dict(request)


DATUM_AXIS_SCHEMA = strict(
    {
        "name": FEATURE_NAME,
        "through": {"type": "array", "items": REFERENCE, "minItems": 1, "maxItems": 2},
    },
    ("through",),
)
DATUM_AXIS_EXAMPLE = {"name": "ZAXIS", "through": ["RIGHT", "TOP"]}


def validate_datum_axis(request: Any) -> dict:
    validate(request, DATUM_AXIS_SCHEMA)
    _refs_distinct(request["through"], "request.through")
    return dict(request)


# ------------------------------------------------------------------ edges, holes, shells

ROUND_SCHEMA = strict(
    {"units": LENGTH_UNITS, "name": FEATURE_NAME, "radius": POS, "edges": REFS},
    ("units", "radius", "edges"),
)
ROUND_EXAMPLE = {"units": "mm", "name": "CORNERS", "radius": 3, "edges": ["edge:54", "edge:56"]}

CHAMFER_SCHEMA = strict(
    {"units": LENGTH_UNITS, "name": FEATURE_NAME, "distance": POS, "edges": REFS},
    ("units", "distance", "edges"),
)
CHAMFER_EXAMPLE = {"units": "mm", "name": "EDGE_BREAK", "distance": 1, "edges": ["edge:44"]}


def validate_edges(request: Any, schema: dict) -> dict:
    validate(request, schema)
    _refs_distinct(request["edges"], "request.edges")
    for i, ref in enumerate(request["edges"]):
        if not ref.lower().startswith("edge:"):
            raise Error(
                "E_VALIDATION",
                "edges are edge:<id> references from geometry list",
                {"path": f"request.edges[{i}]"},
            )
    return dict(request)


SCREW = text(pattern=r"^[A-Za-z0-9#./-]{1,24}$", maximum=24)
SERIES = text(pattern=r"^[A-Za-z0-9_/-]{1,24}$", maximum=24)
CHART_SIZED = {"type": "boolean", "enum": [True]}
HOLE_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "diameter": POS,
        "thread": strict(
            {"size": SCREW, "series": SERIES, "depth": {"oneOf": [POS, text(enum=("through",))]}},
            ("size",),
        ),
        "clearance": strict(
            {"size": SCREW, "series": SERIES, "fit": text(enum=("close", "medium", "free"))},
            ("size",),
        ),
        "counterbore": {
            "oneOf": [CHART_SIZED, strict({"diameter": POS, "depth": POS}, ("diameter", "depth"))]
        },
        "countersink": {
            "oneOf": [
                CHART_SIZED,
                strict(
                    {
                        "diameter": POS,
                        "angle": {"type": "number", "exclusiveMinimum": 0, "maximum": 179},
                    },
                    ("diameter", "angle"),
                ),
            ]
        },
        "depth": {"oneOf": [POS, text(enum=("through_all",))]},
        "placement": strict(
            {
                "surface": REFERENCE,
                "offsets": {
                    "type": "array",
                    "items": strict({"from": REFERENCE, "distance": NUM}, ("from", "distance")),
                    "minItems": 2,
                    "maxItems": 2,
                },
                "axis": REFERENCE,
                "diameter": POS,
                "angle_from": REFERENCE,
                "angle": {"type": "number", "minimum": -360, "maximum": 360},
            },
            ("surface",),
        ),
    },
    ("units", "depth", "placement"),
)
# The three ways the Hole tool places a hole, by the keys each takes besides the surface.
HOLE_PLACEMENTS = {
    "linear": ({"offsets"}, set()),
    "bolt_circle": ({"axis", "diameter", "angle_from"}, {"angle"}),
    "coaxial": ({"axis"}, set()),
}


def hole_placement(placement: dict) -> str:
    """linear (offsets from two references), bolt_circle (about an axis, at a diameter, an
    angle from a plane through the axis) or coaxial (on an axis)."""
    given = set(placement) - {"surface"}
    for how, (needed, optional) in HOLE_PLACEMENTS.items():
        if needed <= given <= needed | optional:
            return how
    raise Error(
        "E_VALIDATION",
        "a hole is placed one of three ways: 'offsets' from two references; on a bolt circle, "
        "'axis', 'diameter' and 'angle_from' a plane through the axis (and 'angle'); or on an "
        "'axis' alone, coaxial",
        {"path": "request.placement", "given": sorted(given)},
    )


HOLE_EXAMPLE = {
    "units": "mm",
    "name": "BOLT_HOLE",
    "diameter": 5,
    "depth": "through_all",
    "placement": {
        "surface": "surface:43",
        "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
    },
}


def validate_hole(request: Any) -> dict:
    validate(request, HOLE_SCHEMA)
    sized = [k for k in ("diameter", "thread", "clearance") if k in request]
    if len(sized) != 1:
        raise Error(
            "E_VALIDATION",
            "a hole has one of: a diameter, a screw it is tapped for (thread), or a screw it "
            "is clear of (clearance)",
            {"path": "request", "given": sized},
        )
    if "counterbore" in request and "countersink" in request:
        raise Error(
            "E_VALIDATION",
            "a hole has a counterbore or a countersink, not both",
            {"path": "request"},
        )
    for key in ("counterbore", "countersink"):
        shape = request.get(key)
        if shape is True and "diameter" in request:
            raise Error(
                "E_VALIDATION",
                f"a {key} sized by Creo's chart needs the screw: a thread or clearance; for a "
                "plain hole give its diameter and depth or angle",
                {"path": f"request.{key}"},
            )
        if (
            isinstance(shape, dict)
            and "diameter" in request
            and shape["diameter"] <= request["diameter"]
        ):
            raise Error(
                "E_VALIDATION", f"a {key} is wider than the hole", {"path": f"request.{key}"}
            )
    thread = request.get("thread")
    if thread and request["depth"] != "through_all":
        reach = thread.get("depth", "through")
        if reach == "through":
            raise Error(
                "E_VALIDATION",
                "a blind tapped hole says how deep its thread goes: thread.depth",
                {"path": "request.thread.depth"},
            )
        if reach > request["depth"]:
            raise Error(
                "E_VALIDATION",
                "the thread goes no deeper than the hole",
                {"path": "request.thread.depth"},
            )
    placement = request["placement"]
    how = hole_placement(placement)
    if how == "linear":
        offsets = placement["offsets"]
        _refs_distinct([o["from"] for o in offsets], "request.placement.offsets")
        if placement["surface"].upper() in {o["from"].upper() for o in offsets}:
            raise Error(
                "E_VALIDATION",
                "the hole is placed on one reference and dimensioned from two others",
                {"path": "request.placement"},
            )
    else:
        _refs_distinct(
            [placement["surface"], placement["axis"]]
            + ([placement["angle_from"]] if how == "bolt_circle" else []),
            "request.placement",
        )
    return dict(request)


SHELL_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "thickness": POS,
        "remove": {"type": "array", "items": REFERENCE, "minItems": 0, "maxItems": 200},
        "side": text(enum=("inside", "outside")),
    },
    ("units", "thickness"),
)
SHELL_EXAMPLE = {"units": "mm", "name": "HOLLOW", "thickness": 1.5, "remove": ["surface:43"]}
SHELL_SCHEMA["description"] = (
    "The current bounded lifecycle accepts mm, one explicit complete top face and uniform "
    "inward thickness on a standalone rectangular prism. Other syntactic variants refuse "
    "before native dispatch. Names/IDs come from actual geometry readback."
)


def validate_shell(request: Any) -> dict:
    validate(request, SHELL_SCHEMA)
    _refs_distinct(request.get("remove", []), "request.remove")
    return dict(request)


# ------------------------------------------------------------------ threads

THREAD_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "surface": REFERENCE,
        "start": REFERENCE,
        "size": SCREW,
        "series": SERIES,
        "diameter": POS,
        "depth": POS,
    },
    ("units", "surface", "start", "depth"),
)
THREAD_EXAMPLE = {
    "units": "mm",
    "name": "END_THREAD",
    "surface": "surface:49",
    "start": "surface:43",
    "size": "M10x1.5",
    "depth": 15,
}


def validate_thread(request: Any) -> dict:
    validate(request, THREAD_SCHEMA)
    if ("size" in request) == ("diameter" in request):
        raise Error(
            "E_VALIDATION",
            "a thread has a size from Creo's chart (M10x1.5) or a diameter, one of them",
            {"path": "request"},
        )
    if "series" in request and "size" not in request:
        raise Error("E_VALIDATION", "a series goes with a size", {"path": "request.series"})
    if request["surface"].upper() == request["start"].upper():
        raise Error(
            "E_VALIDATION",
            "a thread starts from a face other than the one it is on",
            {"path": "request.start"},
        )
    return dict(request)


# ------------------------------------------------------------------ drafts

DRAFT_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "surfaces": REFS,
        "hinge": REFERENCE,
        "angle": {"type": "number", "minimum": -89, "maximum": 89},
        "pull": REFERENCE,
        "flip_pull": {"type": "boolean"},
    },
    ("surfaces", "hinge", "angle"),
)
DRAFT_SCHEMA["description"] = (
    "The retained adapter grammar is narrowed by the current native profile: one positive-X "
    "wall of a rectangular mm prism, an actual top +Z datum used as neutral/pull, "
    "constant unsplit whole-degree signed angle 1..15. Other variants refuse before dispatch."
)
DRAFT_EXAMPLE = {
    "units": "mm",
    "name": "WALL_DRAFT",
    "surfaces": ["surface:53"],
    "hinge": "FRONT",
    "pull": "FRONT",
    "angle": 5,
}


def validate_draft(request: Any) -> dict:
    validate(request, DRAFT_SCHEMA)
    _refs_distinct(request["surfaces"], "request.surfaces")
    for i, ref in enumerate(request["surfaces"]):
        if not ref.lower().startswith("surface:"):
            raise Error(
                "E_VALIDATION",
                "the faces to draft are surface:<id> references from geometry list",
                {"path": f"request.surfaces[{i}]"},
            )
    if request["angle"] == 0:
        raise Error("E_VALIDATION", "a draft angle is not zero", {"path": "request.angle"})
    if request["hinge"].upper() in {r.upper() for r in request["surfaces"]}:
        raise Error(
            "E_VALIDATION",
            "the hinge the faces turn about is not one of them",
            {"path": "request.hinge"},
        )
    return dict(request)


# ------------------------------------------------------------------ patterns

PATTERN_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": FEATURE_NAME,
        "feature": text(pattern=r"^[A-Za-z0-9_-]{1,80}$", maximum=80),
        "direction": strict(
            {"along": REFERENCE, "spacing": NUM, "count": COUNT}, ("along", "spacing", "count")
        ),
        "direction2": strict(
            {"along": REFERENCE, "spacing": NUM, "count": COUNT}, ("along", "spacing", "count")
        ),
        "axis": strict(
            {"about": REFERENCE, "angle": ANGLE, "count": COUNT}, ("about", "angle", "count")
        ),
    },
    ("units", "feature"),
)
PATTERN_EXAMPLE = {
    "units": "mm",
    "name": "HOLE_ROW",
    "feature": "BOLT_HOLE",
    "direction": {"along": "RIGHT", "spacing": 10, "count": 5},
}


def validate_pattern(request: Any) -> dict:
    validate(request, PATTERN_SCHEMA)
    if ("direction" in request) == ("axis" in request):
        raise Error("E_VALIDATION", "give exactly one of direction or axis", {"path": "request"})
    if "direction2" in request:
        if "direction" not in request:
            raise Error(
                "E_VALIDATION",
                "a second direction goes with a first: direction and direction2 make a grid",
                {"path": "request.direction2"},
            )
        if request["direction2"]["spacing"] == 0:
            raise Error(
                "E_VALIDATION",
                "the spacing between rows is not zero",
                {"path": "request.direction2.spacing"},
            )
        if request["direction2"]["along"].upper() == request["direction"]["along"].upper():
            raise Error(
                "E_VALIDATION",
                "the two directions of a grid are different references",
                {"path": "request.direction2.along"},
            )
        if request["direction"]["count"] * request["direction2"]["count"] > 500:
            raise Error("E_VALIDATION", "a grid of at most 500 instances", {"path": "request"})
    step = request["direction"]["spacing"] if "direction" in request else request["axis"]["angle"]
    if step == 0:
        raise Error(
            "E_VALIDATION",
            "the spacing or angle between instances is not zero",
            {"path": "request"},
        )
    return dict(request)
