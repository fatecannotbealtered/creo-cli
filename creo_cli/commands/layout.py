"""Explicit view-centre layout in actual sheet units; annotation checks stay separate."""

from __future__ import annotations

from .. import drawing_warnings, engine
from ..core import Error, number, read_request
from ..registry import MODEL, REQUEST, Command
from ..schemas import DRAWING_LAYOUT_FEEDBACK, INT, S, array, shape, written
from ..validation import strict, text, validate

SCHEMA = strict(
    {
        "sheet": {"type": "integer", "minimum": 1},
        "views": {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": strict(
                {
                    "view": text(maximum=80)
                    | {
                        "description": "native view name on the selected sheet, as model show "
                        "returns it; this request does not take numeric view IDs"
                    },
                    "at": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                },
                ("view", "at"),
            ),
        },
    },
    ("sheet", "views"),
)
EXAMPLE = {"sheet": 1, "views": [{"view": "FRONT", "at": [100, 100]}]}


def _prepare(opts):
    name = engine.model_name(opts["model"], ("drw",))
    q = read_request(opts["request"])
    validate(q, SCHEMA)
    if len({v["view"] for v in q["views"]}) != len(q["views"]):
        raise Error("E_VALIDATION", "layout lists each view once")
    return name, q


def _inventory(client, name, q):
    sheets = engine.normalize(
        client.op("drawing.resources", {"model": name, "kind": "sheets", "sheet": q["sheet"]})
    )
    views = engine.normalize(
        client.op("drawing.resources", {"model": name, "kind": "views", "sheet": q["sheet"]})
    )
    if (
        sheets.get("completed") is not True
        or views.get("completed") is not True
        or len(sheets.get("items", [])) != 1
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "layout requires actual sheet and completed view inventories"
        )
    return sheets["items"][0], views["items"]


def _positions(sheet, views, q):
    planned, issues = [], []
    by_name = {v.get("name"): v for v in views}
    moves = {v["view"]: v["at"] for v in q["views"]}
    if set(moves) - set(by_name):
        raise Error(
            "E_NOT_FOUND",
            "layout requires an existing native view name on the selected sheet",
            {
                "requested_names": sorted(set(moves) - set(by_name)),
                "available_names": sorted(n for n in by_name if isinstance(n, str)),
                "selector_kind": "view_name",
                "next_action": (
                    "use native view names from model show; numeric view IDs are not layout names"
                ),
                "_untrusted": ["requested_names", "available_names"],
            },
        )
    for view in views:
        bounds = view.get("outline")
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or any(
                not isinstance(p, list) or len(p) != 2 or not all(number(v) for v in p)
                for p in bounds
            )
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "actual view bounds are unavailable",
                {"view": view.get("name")},
            )
        centre = [(bounds[0][i] + bounds[1][i]) / 2 for i in range(2)]
        at = moves.get(view["name"], centre)
        size = [abs(bounds[1][i] - bounds[0][i]) for i in range(2)]
        box = [[at[i] - size[i] / 2 for i in range(2)], [at[i] + size[i] / 2 for i in range(2)]]
        planned.append(
            {
                "view": view["name"],
                "actual_centre": centre,
                "requested_centre": at,
                "predicted_outline": box,
                "moves": view["name"] in moves,
            }
        )
        if (
            box[0][0] < 0
            or box[0][1] < 0
            or box[1][0] > sheet["width"]
            or box[1][1] > sheet["height"]
        ):
            issues.append({"kind": "clipping", "views": [view["name"]]})
    for i, a in enumerate(planned):
        for b in planned[i + 1 :]:
            x, y = a["predicted_outline"], b["predicted_outline"]
            if all(max(x[0][j], y[0][j]) < min(x[1][j], y[1][j]) for j in range(2)):
                issues.append({"kind": "view_overlap", "views": [a["view"], b["view"]]})
    return planned, issues


def _feedback(name, sheet, views, q, snapshot=None):
    moves = {v["view"]: v["at"] for v in q["views"]}
    return drawing_warnings.feedback(
        (snapshot or {}) | {"model": name, "sheets": [sheet], "views": views},
        proposals=[
            drawing_warnings.translated("views", v, moves[v["name"]])
            for v in views
            if v.get("name") in moves
        ],
    )


def plan(opts):
    name, q = _prepare(opts)

    def read(client):
        sheet, views = _inventory(client, name, q)
        positions, issues = _positions(sheet, views, q)
        return {
            "model": name,
            "sheet": q["sheet"],
            "moves": positions,
            "issues": issues,
            "layout_feedback": _feedback(name, sheet, views, q),
            "actual_observations": {"sheet": sheet, "views": views},
            "source": "fresh drawing.resources getters",
            "scope": "view outlines only",
            "not_checked": [
                "annotations",
                "BOM_and_balloon_links",
                "PDF_pages",
                "manufacturing_completeness",
            ],
            "_untrusted": ["actual_observations"],
        }

    return engine.read(opts, read)


def _plan(client, opts, pre):
    name, q = pre
    session = engine.session(client)
    before = engine.show(client, name)
    engine.store_directory(before, session)
    sheet, views = _inventory(client, name, q)
    positions, issues = _positions(sheet, views, q)
    if issues:
        raise Error(
            "E_CONFLICT",
            "requested layout clips or overlaps actual view outlines",
            {"issues": issues},
        )

    def verify(c, _reply):
        actual_sheet, actual = _inventory(c, name, q)
        observed, _ = _positions(actual_sheet, actual, q)
        checks = [
            engine.check(
                "view_centre:" + row["view"],
                all(
                    abs(row["actual_centre"][j] - row["requested_centre"][j]) <= 1e-4
                    for j in range(2)
                ),
            )
            for row in observed
            if row["moves"]
        ]
        return {"model": name, "sheet": q["sheet"], "views": actual}, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": [
                {
                    "observation": "actual_view_inventory",
                    "observed": actual,
                    "source": "fresh drawing.resources/views",
                    "independent": True,
                },
                {
                    "observation": "layout_feedback",
                    **drawing_warnings.feedback(
                        {"model": name, "sheets": [actual_sheet], "views": actual}
                    ),
                },
            ],
            "not_checked": [
                "annotations",
                "PDF_pages",
                "source_dimension_coverage",
                "manufacturing_completeness",
            ],
        }

    return engine.Plan(
        op="drawing.apply-layout",
        request={"model": name, **q},
        target=name,
        binding={"drawing": before, "sheet": sheet, "views": views},
        preview={
            "command": "drawing layout apply",
            "model": name,
            "moves": positions,
            "layout_feedback": _feedback(name, sheet, views, q, before),
            "effects": ["drawing_view_positions", "drawing_window_activation"],
            "rollback": "none",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name),
        before=before,
        persisted=False,
        arguments={"model": name, "request": q},
    )


def apply(opts):
    return engine.write("drawing layout apply", opts, _prepare, _plan)


COMMANDS = [
    Command(
        "drawing layout plan",
        (
            "Plan explicit view centres using actual sheet bounds; report "
            "clipping/overlap and excluded annotation checks"
        ),
        plan,
        shape(
            {
                "model": S,
                "sheet": INT,
                "moves": array(shape({})),
                "issues": array(shape({})),
                "layout_feedback": DRAWING_LAYOUT_FEEDBACK,
            }
        ),
        (MODEL, REQUEST),
        request=SCHEMA,
        request_example=EXAMPLE,
        service_ops=("drawing.resources",),
        example="--model drawing.drw --request layout.json",
    ),
    Command(
        "drawing layout apply",
        (
            "Move selected views with preview/confirm and independent "
            "actual-centre readback; no automatic rollback"
        ),
        apply,
        written(shape({"model": S, "sheet": INT, "views": array(shape({}))})),
        (MODEL, REQUEST),
        write=True,
        request=SCHEMA,
        request_example=EXAMPLE,
        service_ops=("drawing.resources", "drawing.apply-layout", "session.status", "model.show"),
        untrusted=("result", "verification"),
        example="--model drawing.drw --request layout.json",
    ),
]
