"""drawing create, add-view, move-view, annotate, hide-dimension, add-note: a drawing of a
part or assembly from a template, its views -- sections and details among them -- the
model's dimensions an engineer chooses to show on them, and notes. Export it with model
export (.pdf). The rest of the detailing -- editing and moving, reference dimensions,
tables, symbols -- is in detailing.py."""

from __future__ import annotations

import math
import re
from copy import deepcopy

from .. import (
    drawing_note_recovery,
    drawing_warnings,
    engine,
    native_read_recovery,
    paths,
    presentation,
    view_readback,
)
from ..core import Error, number
from ..registry import MODEL, Command, Param
from ..schemas import (
    INT,
    NB,
    NI,
    NN,
    NS,
    VIEW_NATIVE_READBACK_PROPERTIES,
    WRITTEN,
    B,
    N,
    S,
    array,
    shape,
    written,
)
from ..transport import Client
from ..validation import text, validate

FEATURE_REF = text(pattern=r"^[A-Za-z0-9_-]{1,80}$", maximum=80)
DIMENSION_REF = text(
    pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}(?:@[A-Za-z][A-Za-z0-9_-]{0,30}\.(?:prt|asm|drw))?$",
    maximum=70,
)
NOTE_LIMIT = 500


def _list(raw: str, path: str, schema: dict) -> list[str]:
    """A flag of comma-separated names, each checked; none empty, none twice."""
    items = [x.strip() for x in str(raw).split(",")]
    for item in items:
        validate(item, schema, path)
    if len({i.upper() for i in items}) != len(items):
        raise Error("E_VALIDATION", "a name is given twice", {"path": path})
    return items


SHEETS = ("a0", "a1", "a2", "a3", "a4", "a", "b", "c", "d", "e", "f")
ORIENTATIONS = ("front", "back", "top", "bottom", "left", "right", "isometric")


def _drawing(opts: dict) -> str:
    return engine.model_name(opts["model"], ("drw",))


def own(row: dict, drawing: str) -> bool:
    """A dimension made on the drawing itself (a reference dimension), not one of a model's."""
    return str(row.get("model") or "").lower() == drawing.lower()


def on_sheet(before: dict, x: float, y: float, what: str) -> None:
    """Refuse a place off the drawing's first sheet, when Creo reported the sheet's size."""
    for key, value in (("x", x), ("y", y)):
        if not math.isfinite(value):
            raise Error("E_VALIDATION", "x and y are sheet coordinates", {"path": key})
    sheet = (before.get("sheets") or [{}])[0]
    width, height = sheet.get("width"), sheet.get("height")
    if isinstance(width, int | float) and isinstance(height, int | float):
        if not (0 <= x <= width and 0 <= y <= height):
            raise Error(
                "E_VALIDATION",
                f"the {what} is placed off the sheet",
                {"path": "x", "sheet": [width, height]},
            )


def note_text(raw: str) -> str:
    """A note's text: a line break is a real newline or the two characters backslash-n."""
    note = str(raw).replace("\\n", "\n")
    lines = note.split("\n")
    if not note.strip() or len(note) > NOTE_LIMIT or len(lines) > 20:
        raise Error(
            "E_VALIDATION",
            f"a note is 1..{NOTE_LIMIT} characters on at most 20 lines",
            {"path": "text"},
        )
    if any(ord(ch) < 32 and ch != "\n" for ch in note):
        raise Error("E_VALIDATION", "a note holds no control characters", {"path": "text"})
    return note


def _views(client: Client, name: str) -> list:
    return engine.show(client, name).get("views") or []


# ------------------------------------------------------------------ create


def _prepare_create(opts: dict) -> dict:
    name = engine.model_name(opts["name"], ("drw",), "name")
    of = engine.model_name(opts["of"], ("prt", "asm"), "of")
    sheet, template = opts.get("sheet"), opts.get("template")
    scale = None
    if opts.get("scale") is not None:
        m = re.fullmatch(r"(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", str(opts["scale"]).strip())
        if not m or float(m[1]) <= 0 or float(m[2]) <= 0:
            raise Error(
                "E_VALIDATION",
                "a drawing's scale is written as a drafter writes it: 2:1, 1:1, 1:2",
                {"path": "scale"},
            )
        scale = float(m[1]) / float(m[2])
    if (sheet is None) == (template is None):
        raise Error(
            "E_VALIDATION",
            "give exactly one of --sheet (a0..a4, a..f) or --template",
            {"path": "sheet"},
        )
    source = None
    if template is not None:
        file = paths.contained(template, directory=False)
        m = paths.MODEL_FILE.fullmatch(file.name)
        if not m or m[2].lower() != "drw":
            raise Error("E_VALIDATION", "a drawing template is a *.drw file", {"path": "template"})
        source = paths.artifact(file)
    return {
        "name": name,
        "of": of,
        "sheet": sheet,
        "template": source,
        "scale": scale,
        "projection": PROJECTIONS.get(opts.get("projection")),
        # Creo's ISO sheets lay out a projection above the front -- in their first angle, the
        # part seen from below -- so on its own sheets the standard views are laid out instead.
        "views": opts.get("views") or ("standard" if sheet else "template"),
    }


# How a drawing's projections are laid out: the view from above goes below the front in
# first angle (ISO E, GB, DIN) and above it in third angle (ASME, JIS). Creo's ISO sheets
# (a0..a4) are first angle, its ANSI ones (a..f) third.
PROJECTIONS = {"first": "first_angle", "third": "third_angle"}
VIEWS_MEANING = {
    "template": "what the template lays out; without template views, front, top, side and "
    "isometric",
    "standard": "FRONT, TOP and the side view (LEFT in first angle, RIGHT in third) where the "
    "projection puts them, and ISOMETRIC; the template's own views removed",
    "none": "none: the template's views removed, for add-view to lay out",
}


def _plan_create(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, of, sheet, source = pre["name"], pre["of"], pre["sheet"], pre["template"]
    s = engine.session(client)
    cwd = engine.working_directory(s)
    engine.require_in_session(s, of)
    engine.require_workspace_models(client, s, [of], "the model to draw")
    if name in s["models"]:
        raise Error(
            "E_CONFLICT",
            "a model of that name is already in session",
            {"model": name, "_untrusted": ["model"]},
        )
    if paths.model_files(cwd, name):
        raise Error(
            "E_CONFLICT",
            "the working directory already holds files of that name",
            {"model": name, "fix": "choose another name", "_untrusted": ["model"]},
        )
    if source and not engine.same_path(engine.origin_directory(source["path"]), cwd):
        raise Error(
            "E_VALIDATION",
            "Creo takes a drawing template of your own from its working directory",
            {"template": source["path"], "working_directory": str(cwd), "_untrusted": ["template"]},
        )
    display = opts.get("display") or "lines"
    projection, views = pre["projection"], pre["views"]
    request = (
        {"name": name, "of": of, "display": display}
        | ({"sheet": sheet} if sheet else {"template": source["path"]})
        | ({"scale": pre["scale"]} if pre.get("scale") else {})
        | ({"projection": projection} if projection else {})
        | ({"views": views} if views != "template" else {})
    )

    def verify(c: Client, data: dict):
        # Creo answers a view's outline as it was before the sheet's scale changed until the
        # call that changed it returns; the drawing is read back afresh.
        fresh = engine.show(c, name)
        if fresh.get("views"):
            data = data | {"views": fresh["views"]}
        checks = [
            engine.check("drawing_in_session", name in engine.session(c)["models"]),
            engine.check("drawing_shows_the_model", of in (data.get("models") or [])),
            engine.check("drawing_has_views", bool(data.get("views")))
            if views != "none"
            else engine.check("no_views_as_asked", not data.get("views")),
        ]
        if projection:
            checks.append(
                engine.check(
                    "projection_as_asked",
                    data.get("projection") == projection,
                    projection=data.get("projection"),
                )
            )
        sheet_row = next(iter(data.get("sheets") or []), {})
        width, height = sheet_row.get("width"), sheet_row.get("height")
        if isinstance(width, int | float) and isinstance(height, int | float):
            off = [
                v.get("name")
                for v in data.get("views") or []
                if not v.get("outline")
                or v["outline"][0][0] < 0
                or v["outline"][0][1] < 0
                or v["outline"][1][0] > width
                or v["outline"][1][1] > height
            ]
            checks.append(engine.check("every_view_on_the_sheet", not off, off=off))
            boxes = [
                (v.get("name"), v.get("outline"))
                for v in data.get("views") or []
                if v.get("outline")
            ]
            crossing = [
                [a, b]
                for i, (a, p) in enumerate(boxes)
                for b, q in boxes[i + 1 :]
                if p[0][0] < q[1][0]
                and q[0][0] < p[1][0]
                and p[0][1] < q[1][1]
                and q[0][1] < p[1][1]
            ]
            checks.append(engine.check("views_apart", not crossing, overlapping=crossing))
        drawn = {v.get("name"): v.get("display") for v in data.get("views") or []}
        checks.append(
            engine.check(
                "views_drawn_as_asked", all(d == display for d in drawn.values()), drawn=drawn
            )
        )
        if sheet:
            checks.append(
                engine.check(
                    "scales_labelled_as_ratios",
                    str(data.get("scale_labels") or "").lower() == "ratio_colon",
                    scale_labels=data.get("scale_labels"),
                )
            )
            # Creo's font is localized with the session; the sheets' ISONorm has no CJK glyphs.
            checks.append(
                engine.check(
                    "lettered_in_creo_font",
                    str(data.get("lettering") or "").lower() in ("font", "font.ndx"),
                    lettering=data.get("lettering"),
                )
            )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": [
                {"observation": "sheets", "sheets": data.get("sheets")},
                {"observation": "scale_chosen", "scale": data.get("scale_chosen")},
                {
                    "observation": "projection",
                    "projection": data.get("projection"),
                    "views_replaced": data.get("views_replaced") or [],
                    "meaning": "first_angle: a projection below the front shows the part from "
                    "above, one on its right from the left; third_angle: the other way round",
                },
            ],
            "not_checked": ["layout_quality"],
        }

    def lay_out(c: Client, data: dict) -> dict:
        # Creo makes a drawing's views only in the call after the one that made it.
        if not data.get("lay_out"):
            return data
        laid = engine.normalize(
            c.op(
                "drawing.lay-out",
                {"model": name, "display": display}
                | ({"scale": pre["scale"]} if pre.get("scale") else {}),
                write=True,
            )
        )
        return {k: v for k, v in data.items() if k != "lay_out"} | laid

    return engine.Plan(
        op="drawing.create",
        request=request,
        then=lay_out,
        target=name,
        binding={"models": s["models"], "of": engine.show(client, of), "template": source or sheet},
        preview={
            "command": "drawing create",
            "creates": name,
            "of": of,
            "template": f"Creo's {sheet} drawing template" if sheet else source["path"],
            "views": VIEWS_MEANING[views],
            "projection": projection
            or "the template's: Creo's ISO sheets (a0..a4) are first angle, its ANSI ones (a..f) "
            "third angle",
            "display": DISPLAY_MEANING[display],
            "scale": opts["scale"]
            if pre.get("scale")
            else "on Creo's sheets, the largest of ISO 5455's preferred scales (1:1, 2:1, "
            "5:1, 1:2 ...) at which every view lies on the sheet with room between for "
            "dimensions; a template of your own keeps its scale. Give --scale to leave room, "
            "say, for an exploded view and a parts list",
            "working_directory": str(cwd),
        },
        verify=verify,
        observe=lambda c: engine.session(c)["models"],
        before=s["models"],
        arguments={
            "name": opts["name"],
            "of": opts["of"],
            "sheet": sheet,
            "template": opts.get("template"),
            "scale": opts.get("scale"),
            "display": display,
            "projection": projection,
            "views": views,
        },
    )


def create(opts: dict) -> dict:
    return engine.write("drawing create", opts, _prepare_create, _plan_create)


# ------------------------------------------------------------------ add-view

VIEW_NAME = text(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,30}$", maximum=31)
SECTION_NAME = text(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,30}$", maximum=31)
PLANE_REF = text(pattern=r"^(?:surface:[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30})$", maximum=40)
EDGE_REF = text(pattern=r"^edge:[0-9]{1,9}$", maximum=16)
# Letters a section or detail is named by; drawing standards leave out I, O and Q.
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def _view_name(kind: str, opts: dict, section: dict | None, views: list) -> str:
    """A view's name when none is asked: after its orientation (FRONT), its section
    (SECTION_A) or what it is (PROJECTION), numbered on from 2 if taken. Creo's own default
    follows its interface language -- a Chinese session names a projection 左侧_4 -- so a
    caller's later references would work on one machine and not another."""
    if kind == "general":
        stem = (opts.get("orientation") or "front").upper()
    elif section:
        stem = "SECTION_" + str(section["name"]).upper()
    else:
        stem = "PROJECTION"
    taken = {str(v.get("name")).upper() for v in views}
    if stem not in taken:
        return stem
    n = 2
    while f"{stem}_{n}" in taken:
        n += 1
    return f"{stem}_{n}"


DISPLAYS = ("lines", "hidden", "shaded")
DISPLAY_MEANING = {
    "lines": "drawn in lines: the visible edges, as a drafter draws; tangent edges left out",
    "hidden": "drawn in lines, hidden edges dashed as well",
    "shaded": "shaded, as Creo shows the model",
}


def next_letter(taken: set) -> str:
    """The first letter -- then pair of letters -- no section or view of the drawing has."""
    for name in [*LETTERS, *(a + b for a in LETTERS for b in LETTERS)]:
        if name not in taken:
            return name
    raise Error("E_CONFLICT", "every section letter is taken")


def _prepare_view(opts: dict) -> dict:
    kind = opts["type"]
    given = {
        k
        for k in (
            "orientation",
            "parent",
            "section",
            "plane",
            "half",
            "center",
            "radius",
            "exploded",
        )
        if opts.get(k)
    }
    allowed = {
        "general": {"orientation", "section", "plane", "half", "exploded"},
        "projection": {"parent", "section", "plane", "half"},
        "detail": {"parent", "center", "radius"},
    }[kind]
    stray = sorted(given - allowed)
    if stray:
        raise Error(
            "E_VALIDATION",
            f"a {kind} view takes no --{stray[0]}",
            {"path": stray[0], "takes": sorted(allowed)},
        )
    if kind in ("projection", "detail") and not opts.get("parent"):
        raise Error("E_VALIDATION", f"a {kind} view needs --parent", {"path": "parent"})
    if kind == "detail":
        for key in ("center", "radius"):
            if opts.get(key) is None:
                raise Error("E_VALIDATION", f"a detail view needs --{key}", {"path": key})
        validate(opts["center"], EDGE_REF, "center")
        if not 0 < opts["radius"] <= 1e6:
            raise Error("E_VALIDATION", "radius is a positive length", {"path": "radius"})
    if opts.get("section") is not None:
        validate(opts["section"], SECTION_NAME, "section")
    if opts.get("plane") is not None:
        validate(opts["plane"], PLANE_REF, "plane")
    if opts.get("half") is not None:
        validate(opts["half"], PLANE_REF, "half")
        if not (opts.get("section") or opts.get("plane")):
            raise Error(
                "E_VALIDATION",
                "--half divides a section view: give --plane or --section too",
                {"path": "half"},
            )
        if opts.get("plane") and opts["plane"].upper() == opts["half"].upper():
            raise Error(
                "E_VALIDATION",
                "a half section is divided by a plane other than the one it cuts through",
                {"path": "half"},
            )
    if opts.get("name") is not None:
        validate(opts["name"], VIEW_NAME, "name")
    for key in ("x", "y"):
        if not math.isfinite(opts[key]):
            raise Error("E_VALIDATION", "x and y are sheet coordinates", {"path": key})
    if opts.get("scale") is not None and not 0 < opts["scale"] <= 1000:
        raise Error("E_VALIDATION", "scale is more than 0, at most 1000", {"path": "scale"})
    return {"name": _drawing(opts)}


def _one_view(views: list, wanted: str, path: str) -> dict:
    """A view by name; Creo lets two views share one, and such a name is refused."""
    hits = [v for v in views if v.get("name") == wanted]
    if not hits:
        raise Error(
            "E_NOT_FOUND",
            "the drawing has no view of that name",
            {path: wanted, "views": [v.get("name") for v in views], "_untrusted": [path, "views"]},
        )
    if len(hits) > 1:
        raise Error(
            "E_CONFLICT",
            "two views of the drawing share that name",
            {path: wanted, "_untrusted": [path]},
        )
    return hits[0]


def _section_plan(client: Client, s: dict, model: str, opts: dict, taken: set) -> dict:
    """Which cross-section a view is cut by: one the model has, or a new one through a plane."""
    if not str(model).lower().endswith((".prt", ".asm")):
        raise Error("E_CONFLICT", "the view shows no part or assembly to section")
    engine.require_workspace_models(client, s, [model], "the model to section")
    shown = engine.show(client, model)
    sections = shown.get("cross_sections") or []
    wanted, plane = opts.get("section"), opts.get("plane")
    existing = None
    if wanted is not None:
        existing = next((x for x in sections if str(x.get("name")).upper() == wanted.upper()), None)
    elif plane is not None:
        existing = next(
            (x for x in sections if str(x.get("plane") or "").upper() == plane.upper()), None
        )
    if existing is not None:
        if plane is not None and str(existing.get("plane") or "").upper() != plane.upper():
            raise Error(
                "E_CONFLICT",
                "the model's cross-section of that name is cut through another plane",
                {"section": existing, "_untrusted": ["section"]},
            )
        return {
            "name": existing["name"],
            "plane": existing.get("plane"),
            "made": False,
            "model": shown,
        }
    if plane is None:
        raise Error(
            "E_NOT_FOUND",
            "the model has no cross-section of that name; give --plane to cut it",
            {"section": wanted, "cross_sections": sections, "_untrusted": ["cross_sections"]},
        )
    items = engine.normalize(client.op("geometry.list", {"model": model}))["items"]
    planes = {
        str(i.get("ref")).upper()
        for i in items
        if i.get("kind") == "datum_plane"
        or (i.get("kind") == "surface" and i.get("type") == "plane")
    }
    if plane.upper() not in planes:
        raise Error(
            "E_NOT_FOUND",
            "the model has no datum plane or flat surface of that name",
            {
                "plane": plane,
                "fix": f"creo-cli geometry list --model {model} --kind datum_plane",
                "_untrusted": ["plane", "fix"],
            },
        )
    name = wanted or next_letter(taken)
    return {"name": name, "plane": plane, "made": True, "model": shown}


def _point(raw: str) -> list:
    """x,y,z in the model's units."""
    try:
        point = [float(p) for p in str(raw).split(",")]
    except ValueError:
        point = []
    if len(point) != 3 or not all(math.isfinite(p) for p in point):
        raise Error("E_VALIDATION", "--near is a model point x,y,z", {"path": "near"})
    return point


def _detail_plan(client: Client, model: str, opts: dict) -> None:
    """The edge a detail centres on, and a circle that reaches it."""
    edges = engine.normalize(client.op("geometry.list", {"model": model, "kind": "edge"}))["items"]
    edge = next((e for e in edges if e.get("ref") == opts["center"]), None)
    if edge is None:
        raise Error(
            "E_NOT_FOUND",
            "the parent view's model has no edge of that id",
            {
                "center": opts["center"],
                "fix": f"creo-cli geometry list --model {model} --kind edge",
            },
        )
    if opts.get("near") is not None:
        return
    reach = edge.get("radius") if edge.get("type") in ("arc", "circle") else 0
    if isinstance(reach, int | float) and not opts["radius"] > reach:
        raise Error(
            "E_VALIDATION",
            "the circle must reach the edge: a radius of more than the arc's",
            {"path": "radius", "more_than": reach},
        )


def _first_general_view_scale(before: dict, opts: dict) -> None:
    """Keep the service's explicit first-view sheet-scale setter out of this scope."""
    requested = opts.get("scale")
    if opts["type"] != "general" or requested is None:
        return
    views = before.get("views")
    if not isinstance(views, list):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "the drawing's view inventory is unavailable; first-view scale scope is unknown",
            {"path": "scale", "dispatch_state": "not_started"},
        )
    # Drawings.addView counts every List2DViews entry, including background views.
    # Do not substitute a foreground-only count for that native branch condition.
    if views:
        return
    sheets, models = before.get("sheets"), before.get("models")
    # The summary scale belongs to ListModels[0], whereas addView uses CurrentSolid
    # on CurrentSheet. Only one model and one sheet establish the same scale context
    # from the currently available public readback; do not guess a multi-model default.
    readable = (
        isinstance(sheets, list)
        and len(sheets) == 1
        and isinstance(sheets[0], dict)
        and type(sheets[0].get("number")) is int
        and sheets[0]["number"] == 1
        and number(sheets[0].get("scale"))
        and sheets[0]["scale"] > 0
        and isinstance(models, list)
        and len(models) == 1
        and isinstance(models[0], str)
        and models[0].lower().endswith((".prt", ".asm"))
    )
    if not readable:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "the first general view's current sheet/model scale is not uniquely readable",
            {
                "path": "scale",
                "dispatch_state": "not_started",
                "required": "one drawing model, one sheet numbered 1, and its actual "
                "positive scale",
            },
        )
    current = sheets[0]["scale"]
    if requested != current:
        raise Error(
            "E_UNSUPPORTED",
            "the service changes the sheet default for an explicit first general-view scale; "
            "this command protects that default",
            {
                "path": "scale",
                "dispatch_state": "not_started",
                "requested_view_scale": requested,
                "current_sheet_scale": current,
                "fix": "use the current sheet scale, or set the required page scale with "
                "drawing create --scale while creating a new drawing; this command does not "
                "authorize changing the existing sheet default",
            },
        )


def _plan_view(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name = pre["name"]
    kind = opts["type"]
    if opts.get("exploded"):
        client.require_capability("drawing_view_exploded_readback", 1)
        client.require_capability("assembly_explosion_context_readback", 1)
    capabilities = (client._health or client.health()).get("capabilities")
    version = (
        capabilities.get("drawing_view_exploded_readback")
        if isinstance(capabilities, dict)
        else None
    )
    qualified_view_readback = type(version) is int and version == 1
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    _first_general_view_scale(before, opts)
    old = before.get("views") or []
    parent = _one_view(old, opts["parent"], "parent") if opts.get("parent") else None
    sheet = next((sh for sh in before.get("sheets") or [] if sh.get("number") == 1), {})
    width, height = sheet.get("width"), sheet.get("height")
    if isinstance(width, int | float) and not (
        0 <= opts["x"] <= width and 0 <= opts["y"] <= height
    ):
        raise Error(
            "E_VALIDATION",
            "the view's position is off the sheet",
            {"sheet": {"width": width, "height": height}, "x": opts["x"], "y": opts["y"]},
        )
    if opts.get("name") is not None and any(v.get("name") == opts["name"] for v in old):
        raise Error(
            "E_CONFLICT",
            "the drawing already has a view of that name",
            {"name": opts["name"], "_untrusted": ["name"]},
        )
    model = (parent or {}).get("model") or next(iter(before.get("models") or []), None)
    taken = {str(v.get("name")).upper() for v in old}
    source_models = {}
    for m in before.get("models") or []:
        if str(m).lower().endswith((".prt", ".asm")):
            source_models[str(m).lower()] = engine.show(client, str(m).lower())
            taken |= {
                str(x.get("name")).upper()
                for x in source_models[str(m).lower()].get("cross_sections") or []
            }
    view = {"type": kind, "at": [opts["x"], opts["y"]]}
    exploded_state = None
    assembly_display = None
    if opts.get("exploded"):
        if not str(model).lower().endswith(".asm"):
            raise Error(
                "E_VALIDATION",
                "a view is exploded from an assembly; this drawing shows a part",
                {"path": "exploded", "model": model, "_untrusted": ["model"]},
            )
        source = source_models.get(str(model).lower())
        if source is None:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "the view model is missing from the drawing's model inventory",
            )
        assembly_display = presentation.explosion(source, drawing_inventory=True)
        states = assembly_display["states"]
        active = [x for x in states if x.get("active") is True]
        if assembly_display["is_exploded"] is False:
            raise Error(
                "E_VALIDATION",
                "the assembly is not displayed in its exploded state",
                {
                    "path": "exploded",
                    "active": active[0]["name"] if len(active) == 1 else None,
                    "active_state_id": assembly_display["active_state_id"],
                    "is_exploded": False,
                },
            )
        if len(active) != 1:
            raise Error(
                "E_VERIFY_INCOMPLETE", "the exploded assembly has no unique readable active state"
            )
        exploded_state = active[0]
        if not exploded_state["moves"]:
            raise Error(
                "E_VALIDATION",
                "the required active assembly-state precondition has no translation moves; "
                "this source state does not meet the bounded exploded-view profile",
                {
                    "path": "exploded",
                    "active": (exploded_state or {}).get("name"),
                    "fix": "creo-cli assembly explode apply --model "
                    + str(model).lower()
                    + " --request <moves>",
                    "_untrusted": ["active"],
                },
            )
        view["exploded"] = True
    if kind == "general":
        view["orientation"] = opts.get("orientation") or "front"
    else:
        view["parent"] = opts["parent"]
    if kind == "detail":
        if opts.get("display"):
            raise Error(
                "E_VALIDATION",
                "a detail is drawn as its parent view is; --display is for general and "
                "projection views",
                {"path": "display"},
            )
    else:
        view["display"] = opts.get("display") or "lines"
    if opts.get("edges") and not (opts.get("section") or opts.get("plane")):
        raise Error(
            "E_VALIDATION",
            "--edges is a section view's: give --section or --plane",
            {"path": "edges"},
        )
    section = None
    if opts.get("section") or opts.get("plane"):
        section = _section_plan(client, s, str(model).lower(), opts, taken)
        if exploded_state is not None and section["made"]:
            raise Error(
                "E_UNSUPPORTED",
                "an exploded view cannot create a source cross-section; use an already "
                "verified section",
            )
        view["section"] = (
            {"name": section["name"]}
            | ({"plane": section["plane"]} if section["made"] else {})
            | ({"half": opts["half"]} if opts.get("half") else {})
            | ({"edges": opts["edges"]} if opts.get("edges") else {})
        )
    if kind == "detail":
        _detail_plan(client, str(model).lower(), opts)
        view["detail"] = {"center": opts["center"], "radius": opts["radius"]} | (
            {"near": _point(opts["near"])} if opts.get("near") is not None else {}
        )
        view["name"] = opts.get("name") or next_letter(taken)
        view["scale"] = opts["scale"] if opts.get("scale") is not None else 2 * parent["scale"]
    else:
        view["name"] = opts.get("name") or _view_name(kind, opts, section, old)
        if opts.get("scale") is not None:
            view["scale"] = opts["scale"]

    if qualified_view_readback:
        identity = view_readback.inventory(old)
        if (
            not identity["complete"]
            or not identity["unique"]
            or not all(view_readback.protected_view_complete(row) for row in old)
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "existing view identities are unavailable or ambiguous",
                {"view_identity_inventory": identity},
            )

    exploded_view_scope = {
        "required_independent_checks": [
            "new_native_view_identity",
            "view_model",
            "view_sheet",
            "view_exploded_boolean",
        ],
        "source_snapshot_comparison": "strict comparison of retained source fields in their "
        "observed reading contexts; not independent normal-assembly placement evidence",
        "boolean_meaning": "the native view display switch only; true does not prove "
        "named-state selection or a visibly separated projection",
        "engineering_acceptance": "not_established_by_this_command",
        "not_checked": [
            "per_view_named_exploded_state_identity",
            "actual_separated_projection",
            "independent_normal_assembly_placement",
            "global_assembly_display_across_drawing_context",
        ],
    }

    def verify(c: Client, data: dict):
        nonlocal verified_names
        p.verified_observation = None
        verified_names = None
        if exploded_state is not None:
            # Mutate the actual object passed by finish: its failure fallback persists
            # this object, not a locally rebound result. These are independent raw
            # observations, not service creation claims or completed verification.
            data.update(
                view_acceptance_scope=exploded_view_scope,
                exploded_source_before=source_models[str(model).lower()],
                exploded_source_after=None,
                exploded_source_readback={
                    "source": "independent model.show",
                    "before_status": "returned_at_plan",
                    "after_status": "not_requested",
                    "qualification": "not_started",
                },
            )
        observed = engine.show(c, name)
        now = observed.get("views") or []
        # The view as the drawing holds it now: a scale set in the same call shows in its
        # outline only once that call has returned.
        identity_checks = []
        if qualified_view_readback:
            fresh, identity_checks = view_readback.added_view(
                old,
                now,
                name=view["name"],
                model=model,
                sheet=1,
                exploded=bool(opts.get("exploded")),
            )
        else:
            matches = [row for row in now if row.get("name") == view["name"]]
            fresh = matches[0] if len(matches) == 1 else None
        # A creation reply is never a substitute for an independently observed view.
        made = fresh or {}
        data.update(view=fresh, view_readback_source="independent model.show")
        checks = [
            engine.check("drawing_owner_as_requested", observed.get("model") == name),
            engine.check("view_added", len(now) == len(old) + 1),
            engine.check(
                "scale_as_requested",
                "scale" not in view
                or (
                    isinstance(made.get("scale"), int | float)
                    and math.isclose(made["scale"], view["scale"], rel_tol=1e-9)
                ),
            ),
        ] + identity_checks
        if qualified_view_readback:
            old_ids = view_readback.inventory(old)["ids"]
            retained = [row for row in now if str(row.get("id")) in old_ids]
            checks.append(
                engine.check(
                    "existing_views_preserved",
                    len(retained) == len(old)
                    and all(
                        [row for row in retained if row.get("id") == previous.get("id")]
                        == [previous]
                        for previous in old
                    ),
                )
            )
        resources = (
            "models",
            "sheets",
            "dimensions",
            "notes",
            "tables",
            "symbols",
            "datums",
            "gtols",
            "draft_entities",
            "draft_arcs",
            "draft_entity_readback",
            "projection",
        )
        checks.append(
            engine.check(
                "existing_drawing_resources_preserved",
                all(observed.get(key) == before.get(key) for key in resources),
            )
        )
        if exploded_state is not None:
            retained = data["exploded_source_readback"]
            retained["after_status"] = "requested"
            try:
                source_after = engine.show(c, str(model).lower())
            except Error as exc:
                retained.update(
                    after_status="not_returned",
                    qualification="not_checked",
                    read_error=native_read_recovery.error_record(exc),
                )
                raise
            data["exploded_source_after"] = source_after
            retained.update(after_status="returned", qualification="not_checked")
            try:
                protected_source = presentation.drawing_source(source_after)
            except Error as exc:
                retained.update(
                    qualification="incomplete",
                    validation_error=native_read_recovery.error_record(exc),
                )
                raise
            retained["qualification"] = "required_fields_readable"
            checks.append(
                engine.check(
                    "exploded_source_snapshot_preserved",
                    protected_source
                    == presentation.drawing_source(source_models[str(model).lower()]),
                    source="independent model.show fields in their observed reading contexts; "
                    "not independent normal-placement or per-view named-state evidence",
                )
            )
            data["exploded_source_protection_projection"] = protected_source
        if "name" in view:
            checks.append(engine.check("named_as_asked", made.get("name") == view["name"]))
        if "display" in view:
            # A section of the cut face alone has nothing beyond it to hide; Creo holds it in
            # wireframe whatever it is set to (measured).
            cut_face = opts.get("edges") == "area" and view["display"] == "lines"
            checks.append(
                engine.check(
                    "drawn_as_asked",
                    made.get("display") == view["display"]
                    or (cut_face and made.get("display") == "wireframe"),
                    display=made.get("display"),
                )
            )
        if opts.get("edges"):
            checks.append(
                engine.check(
                    "section_edges_as_asked",
                    (data.get("section") or {}).get("edges") == opts["edges"],
                    edges=(data.get("section") or {}).get("edges"),
                )
            )
        if section is not None:
            cut = engine.show(c, str(model).lower()).get("cross_sections") or []
            checks += [
                engine.check(
                    "view_cut_by_the_section",
                    made.get("sections") == [section["name"]],
                    sections=made.get("sections"),
                ),
                engine.check(
                    "section_in_the_model",
                    any(x.get("name") == section["name"] for x in cut),
                ),
                engine.check(
                    "cut_as_much_as_asked",
                    made.get("section_area") == ("half" if opts.get("half") else "full"),
                    area=made.get("section_area"),
                ),
            ]
        if kind == "detail":
            box = made.get("outline") or [[None, None], [None, None]]
            middle = (
                [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2]
                if None not in (*box[0], *box[1])
                else None
            )
            checks += [
                engine.check(
                    "a_detail_of_the_parent",
                    made.get("type") == "detail" and made.get("parent") == opts["parent"],
                ),
                engine.check(
                    "centred_where_asked",
                    middle is not None
                    and math.isclose(middle[0], opts["x"], abs_tol=1e-6)
                    and math.isclose(middle[1], opts["y"], abs_tol=1e-6),
                    centre=middle,
                ),
            ]
        verification = {
            "level": "selected_postconditions_verified",
            **(
                {"view_acceptance_scope": exploded_view_scope} if exploded_state is not None else {}
            ),
            "checks": checks,
            "observations": [
                {"observation": "outline_on_sheet", "outline": made.get("outline")},
                off_sheet(made, before.get("sheets"), name),
                overlaps(made, now, name, before.get("sheets")),
                {"observation": "layout_feedback", **drawing_warnings.feedback(observed)},
            ],
            "not_checked": list(drawing_warnings.EXCLUSIONS)
            + ["per_view_named_exploded_state_identity"]
            + (exploded_view_scope["not_checked"][1:] if exploded_state is not None else [])
            + (
                []
                if qualified_view_readback
                else ["legacy_service_per_view_exploded_flag_and_identity_metadata"]
            ),
        }
        identities = view_readback.inventory(now) if qualified_view_readback else {}
        names = [row.get("name") for row in now]
        if (
            qualified_view_readback
            and same_plan(p, c)
            and before.get("model") == name
            and observed.get("model") == name
            and observed.get("type") == "drawing"
            and before.get("type") == "drawing"
            and before.get("models") == [model]
            and observed.get("models") == [model]
            and isinstance(model, str)
            and model.endswith((".prt", ".asm"))
            and identities["complete"]
            and identities["unique"]
            and all(view_readback.protected_view_complete(row) for row in now)
            and all(isinstance(value, str) and value.strip() for value in names)
            and len(set(names)) == len(names)
            and checks
            and all(check["passed"] is True for check in checks)
        ):
            # The first independent read proved the required postconditions. Keep
            # exactly observe()'s actual name inventory for this Plan's accounting.
            # The creation reply, optional layout coverage and named explode-state
            # binding supply no additional evidence here.
            verified_names = deepcopy(names)
            p.verified_observation = deepcopy(names)
        return data, verification

    preview = {
        "command": "drawing add-view",
        "model": name,
        "view": view,
        "views_now": len(old),
        "layout_feedback": drawing_warnings.feedback(before),
        "future_view_extent": "unavailable before native creation; no predicted contour "
        "or text clearance",
        "view_readback_contract": "native_per_view_identity_and_boolean_v1"
        if qualified_view_readback
        else "legacy_without_per_view_exploded_readback",
    }
    if exploded_state is not None:
        preview["view_acceptance_scope"] = exploded_view_scope
        preview["exploded_state"] = {
            "id": exploded_state.get("id"),
            "name": exploded_state.get("name"),
            "moves": exploded_state.get("moves"),
            "source": "independent assembly model.show active state; frozen precondition",
            "per_view_named_state_reference": "not_checked; no supported identity getter "
            "established",
            "note": "the active assembly state is a frozen precondition, not a selected "
            "per-view state; the independent Boolean does not establish named-state binding "
            "or visible separation; source snapshots do not independently prove normal "
            "assembly placement",
        }
        preview["assembly_display_readback"] = assembly_display
        preview["source_protection_contract"] = {
            "projection": "all source fields except explosion.is_exploded/context/display_readback",
            "meaning": exploded_view_scope["source_snapshot_comparison"],
            "not_checked": [
                "independent_normal_assembly_placement",
                "global_assembly_display_across_drawing_context",
            ],
            "raw_before_after_retained": True,
        }
    if section is not None:
        preview["section"] = (
            f"cuts cross-section {section['name']} through {section['plane']} in {model}: a "
            "feature of that model, kept with it"
            if section["made"]
            else f"shows the model's cross-section {section['name']}"
        )
    binding = {"drawing": before, "view_readback_contract": preview["view_readback_contract"]}
    if exploded_state is not None:
        binding["exploded_source_model"] = presentation.drawing_source(
            source_models[str(model).lower()]
        )
    if section is not None:
        binding["model"] = section["model"]
    p = engine.Plan(
        op="drawing.add-view",
        request={"model": name, "view": view},
        target=name,
        binding=binding,
        preview=preview,
        verify=verify,
        observe=lambda c: [v["name"] for v in _views(c, name)],
        before=[v["name"] for v in old],
        arguments={
            k: opts.get(k)
            for k in (
                "model",
                "type",
                "orientation",
                "parent",
                "x",
                "y",
                "scale",
                "name",
                "section",
                "plane",
                "center",
                "radius",
                "display",
                "edges",
                "near",
                "exploded",
            )
        },
    )
    frozen = deepcopy(
        {
            "request": p.request,
            "binding": p.binding,
            "preview": p.preview,
            "arguments": p.arguments,
            "before": p.before,
        }
    )
    verified_names = None

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and p.op == "drawing.add-view"
            and p.target == name
            and p.preview.get("command") == "drawing add-view"
            and not getattr(c, "_native_read_pending", None)
            and not getattr(c, "_native_diagnostic_stop", None)
            and all(getattr(p, key) == value for key, value in frozen.items())
        )

    def verified_guard(planned, c):
        # Called again by the driver immediately before reuse. No CAD getter or
        # persistence is involved, and a copied Plan cannot inherit this authority.
        return (
            same_plan(planned, c)
            and verified_names is not None
            and p.verified_observation == verified_names
        )

    p._verified_view_guard = verified_guard
    return p


def add_view(opts: dict) -> dict:
    return engine.write("drawing add-view", opts, _prepare_view, _plan_view)


# ------------------------------------------------------------------ move-view


def _prepare_move_view(opts: dict) -> dict:
    for key in ("x", "y"):
        if not math.isfinite(opts[key]):
            raise Error("E_VALIDATION", "x and y are sheet coordinates", {"path": key})
    return {"name": _drawing(opts)}


def off_sheet(view: dict, sheets: list, drawing: str) -> dict:
    """Whether a view's outline runs off its sheet, by how much on each side, and the middle
    that would bring it back -- read from the outline, not predicted."""
    box = view.get("outline")
    sheet = next((s for s in sheets or [] if s.get("number") == view.get("sheet")), {})
    width, height = sheet.get("width"), sheet.get("height")
    out = {"observation": "off_the_sheet", "off": None}
    if (
        not drawing_warnings.bounds(box)
        or not drawing_warnings.point([width, height])
        or min(width, height) <= 0
    ):
        return out | {"reason": "identified sheet or positive native outline unavailable"}
    beyond = {
        "left": max(0.0, -box[0][0]),
        "right": max(0.0, box[1][0] - width),
        "bottom": max(0.0, -box[0][1]),
        "top": max(0.0, box[1][1] - height),
    }
    out["off"] = any(v > 0 for v in beyond.values())
    if out["off"]:
        w, h = box[1][0] - box[0][0], box[1][1] - box[0][1]
        out["beyond"] = {k: round(v, 3) for k, v in beyond.items() if v > 0}
        out["middle_that_fits"] = (
            {
                "x": [round(w / 2, 3), round(width - w / 2, 3)],
                "y": [round(h / 2, 3), round(height - h / 2, 3)],
            }
            if w <= width and h <= height
            else None
        )
        out["fix"] = (
            f"creo-cli drawing view move --model {drawing} --view {view.get('name')} "
            "--x <x> --y <y>"
            if out["middle_that_fits"]
            else "the view is larger than the sheet: a smaller --scale, or a larger sheet"
        )
    return out


# Room kept between views, and from the sheet's edge, when a clear place is looked for.
VIEW_GAP = 8.0


def overlaps(view: dict, views: list, drawing: str, sheets: list | None = None) -> dict:
    """Which views a view's outline runs into on its sheet: a projection lines up with its
    parent and lands where it lands, so the answer is read, not assumed. When it runs into
    one, the nearest middle that clears them all -- a projection slid along its line with
    its parent, so it stays lined up -- and the move that puts it there."""
    box = view.get("outline")
    others = [
        o.get("outline")
        for o in views
        if o.get("name") != view.get("name")
        and o.get("sheet") == view.get("sheet")
        and view.get("sheet") is not None
        and drawing_warnings.bounds(o.get("outline"))
    ]
    hits = [
        other.get("name")
        for other in views
        if drawing_warnings.bounds(box)
        and view.get("sheet") is not None
        and other.get("name") != view.get("name")
        and other.get("sheet") == view.get("sheet")
        and drawing_warnings.bounds(other.get("outline"))
        and _crossing(box, other["outline"], 0.5)
    ]
    out = {
        "observation": "overlaps_views",
        "views": hits,
        "available": drawing_warnings.bounds(box),
        "scope": "same-sheet coarse view rectangles only",
        "sheet": view.get("sheet"),
        "units": next(
            (s.get("units") for s in sheets or [] if s.get("number") == view.get("sheet")), None
        ),
        "whole_layout_verified": False,
        "not_checked": ["exact_projected_contours", "annotations", "unknown_view_bounds"],
    }
    if hits:
        clear = _clear_middle(view, views, others, sheets)
        out["middle_that_clears"] = clear
        out["fix"] = f"creo-cli drawing view move --model {drawing} --view {view.get('name')} " + (
            f"--x {clear[0]:g} --y {clear[1]:g}" if clear else "--x <x> --y <y>"
        )
    return out


def _crossing(a: list, b: list, by: float) -> bool:
    return (
        min(a[1][0], b[1][0]) - max(a[0][0], b[0][0]) > by
        and min(a[1][1], b[1][1]) - max(a[0][1], b[0][1]) > by
    )


def _clear_middle(view: dict, views: list, others: list, sheets: list | None) -> list | None:
    """The nearest middle at which the view clears every other by VIEW_GAP and stays on the
    sheet: along the line with its parent for a projection, anywhere for another view."""
    box = view["outline"]
    w, h = box[1][0] - box[0][0], box[1][1] - box[0][1]
    middle = [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2]
    sheet = next((s for s in sheets or [] if s.get("number") == view.get("sheet")), None)
    width = (
        (sheet or {}).get("width") if isinstance((sheet or {}).get("width"), int | float) else None
    )
    height = (
        (sheet or {}).get("height")
        if isinstance((sheet or {}).get("height"), int | float)
        else None
    )
    parent = next((v for v in views if v.get("name") == view.get("parent")), None)
    axes = [(1, 0), (0, 1)]
    if view.get("type") == "projection" and parent and parent.get("outline"):
        p = parent["outline"]
        dx = middle[0] - (p[0][0] + p[1][0]) / 2
        dy = middle[1] - (p[0][1] + p[1][1]) / 2
        axes = [(1, 0)] if abs(dx) >= abs(dy) else [(0, 1)]

    def fits(cx: float, cy: float) -> bool:
        candidate = [[cx - w / 2, cy - h / 2], [cx + w / 2, cy + h / 2]]
        if width is not None and not (
            VIEW_GAP <= candidate[0][0] and candidate[1][0] <= width - VIEW_GAP
        ):
            return False
        if height is not None and not (
            VIEW_GAP <= candidate[0][1] and candidate[1][1] <= height - VIEW_GAP
        ):
            return False
        grown = [
            [candidate[0][0] - VIEW_GAP, candidate[0][1] - VIEW_GAP],
            [candidate[1][0] + VIEW_GAP, candidate[1][1] + VIEW_GAP],
        ]
        return not any(_crossing(grown, o, 0.0) for o in others)

    step, reach = 5.0, max(width or 0.0, height or 0.0, 4 * max(w, h), 400.0)
    for k in range(1, int(reach / step) + 1):
        candidates = []
        if len(axes) == 1:
            ax = axes[0]
            candidates = [
                (middle[0] + s * k * step * ax[0], middle[1] + s * k * step * ax[1])
                for s in (1, -1)
            ]
        else:
            ring = range(-k, k + 1)
            candidates = sorted(
                {
                    (middle[0] + i * step, middle[1] + j * step)
                    for i in ring
                    for j in ring
                    if max(abs(i), abs(j)) == k
                },
                key=lambda c: math.dist(c, middle),
            )
        for cx, cy in candidates:
            if fits(cx, cy):
                return [round(cx, 3), round(cy, 3)]
    return None


def _plan_move_view(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    views = before.get("views") or []
    target = _one_view(views, opts["view"], "view")
    on_sheet(before, opts["x"], opts["y"], "view")
    at = [opts["x"], opts["y"]]

    def verify(c: Client, data: dict):
        observed = engine.show(c, name)
        after = observed.get("views") or []
        row = next((v for v in after if v.get("name") == opts["view"]), {})
        box = row.get("outline")
        middle = [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2] if box else None
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "view_centred_where_asked",
                    middle is not None
                    and math.isclose(middle[0], at[0], abs_tol=1e-6)
                    and math.isclose(middle[1], at[1], abs_tol=1e-6),
                    centre=middle,
                ),
                engine.check(
                    "scale_untouched",
                    row.get("scale") == target.get("scale"),
                ),
            ],
            "observations": [
                off_sheet(row, before.get("sheets"), name),
                overlaps(row, after, name, before.get("sheets")),
                {"observation": "layout_feedback", **drawing_warnings.feedback(observed)},
            ],
            "not_checked": list(drawing_warnings.EXCLUSIONS),
        }

    return engine.Plan(
        op="drawing.move-view",
        request={"model": name, "view": opts["view"], "at": at},
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing move-view",
            "model": name,
            "view": target,
            "to": at,
            "layout_feedback": drawing_warnings.feedback(
                before, proposals=[drawing_warnings.translated("views", target, at)]
            ),
            "effect": "the view's middle moves there, with what is shown in it; a projection "
            "stays lined up with its parent only if moved along the line between them",
        },
        verify=verify,
        observe=lambda c: _views(c, name),
        before=views,
        arguments={k: opts.get(k) for k in ("model", "view", "x", "y")},
    )


def move_view(opts: dict) -> dict:
    return engine.write("drawing move-view", opts, _prepare_move_view, _plan_move_view)


# ------------------------------------------------------------------ annotate


def _prepare_annotate(opts: dict) -> dict:
    features = opts.get("feature")
    return {
        "name": _drawing(opts),
        "features": None if features is None else _list(features, "feature", FEATURE_REF),
    }


def _off_the_sheet(after: dict) -> list[str]:
    """The shown dimensions whose text lies outside the sheet their view is on."""
    sheets = {s.get("number"): s for s in after.get("sheets") or []}
    view_sheet = {v.get("name"): v.get("sheet") for v in after.get("views") or []}
    off = []
    for row in after.get("dimensions") or []:
        at = row.get("at")
        sheet = sheets.get(view_sheet.get(row.get("view")))
        if not at or not sheet or not sheet.get("width") or not sheet.get("height"):
            continue
        if not (0 <= at[0] <= sheet["width"] and 0 <= at[1] <= sheet["height"]):
            off.append(row.get("name"))
    return off


def _overlapping(after: dict) -> list[list]:
    """Pairs of shown dimensions whose texts' boxes overlap on the sheet, with by how much."""
    rows, _ = _text_boxes(after)
    out = []
    for i, (a, sheet_a) in enumerate(rows):
        (ax0, ay0), (ax1, ay1) = a["box"]
        for b, sheet_b in rows[i + 1 :]:
            if sheet_a != sheet_b:
                continue
            (bx0, by0), (bx1, by1) = b["box"]
            dx, dy = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
            if dx > 0 and dy > 0:
                out.append([a.get("name"), b.get("name"), round(min(dx, dy), 2)])
    return out


def _text_boxes(after: dict) -> tuple[list, list]:
    """Keep usable boxes with known sheet identities; unknown boxes are not empty coverage."""
    view_sheet = {v.get("name"): v.get("sheet") for v in after.get("views") or []}
    rows, missing = [], []
    for row in after.get("dimensions") or []:
        box = row.get("box")
        sheet = row.get("sheet") or view_sheet.get(row.get("view"))
        valid = (
            isinstance(box, list)
            and len(box) == 2
            and all(isinstance(p, list) and len(p) == 2 for p in box)
            and all(type(n) in (int, float) and math.isfinite(n) for p in box for n in p)
            and box[0][0] < box[1][0]
            and box[0][1] < box[1][1]
        )
        if valid and sheet is not None:
            rows.append((row, sheet))
        else:
            missing.append(
                {
                    "name": row.get("name"),
                    "model": row.get("model"),
                    "reason": "text_box_unavailable" if not valid else "sheet_unavailable",
                }
            )
    return rows, missing


def _owned(row: dict, features: list[str]) -> bool:
    owner = row.get("feature") or {}
    wanted = {f.upper() for f in features}
    return str(owner.get("id")) in wanted or str(owner.get("name") or "").upper() in wanted


def _plan_annotate(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, features = pre["name"], pre["features"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    engine.require_workspace_models(
        client,
        s,
        [str(model).lower() for model in before.get("models") or []],
        "models whose dimension text annotation may change",
    )
    if not before.get("views"):
        raise Error("E_CONFLICT", "the drawing has no views to show dimensions on")
    before_shown = before.get("dimensions_shown") or 0
    if features is not None:
        # Each named feature must be one of the drawn models' own.
        known = []
        for model in before.get("models") or []:
            if str(model).lower().endswith((".prt", ".asm")):
                rows = engine.normalize(client.op("feature.list", {"model": str(model).lower()}))
                known += rows.get("features") or []
        for wanted in features:
            if not any(
                str(f.get("id")) == wanted or str(f.get("name") or "").upper() == wanted.upper()
                for f in known
            ):
                raise Error(
                    "E_NOT_FOUND",
                    "no feature of that name or id in the drawn models",
                    {"feature": wanted, "_untrusted": ["feature"]},
                )

    def verify(c: Client, data: dict):
        after = engine.show(c, name)
        rows = after.get("dimensions") or []
        shown = sum(str(row.get("model", "")).lower() != name for row in rows)
        annotated = data.get("annotated") or {}
        reported = annotated.get("shown")
        off = _off_the_sheet(after)
        checks = [
            engine.check(
                "reply_counts_the_same",
                reported == shown,
                reported=reported,
                observed_model_dimensions=shown,
                observed_drawing_owned_dimensions=len(rows) - shown,
                scope="model dimension count; drawing reference dimensions counted separately",
            ),
            engine.check("dimensions_on_the_sheet", not off, off_the_sheet=off),
        ]
        sighted = annotated.get("moved_into_sight") or []
        if sighted:
            in_view = {str(r.get("id")): r.get("view") for r in rows}
            checks.append(
                engine.check(
                    "moved_into_sight_read_back",
                    all(in_view.get(str(m.get("id"))) == m.get("to") for m in sighted),
                    moved=[[m.get("name"), m.get("from"), m.get("to")] for m in sighted],
                )
            )
        counted = annotated.get("counts_prefixed") or []
        if counted:
            by_id = {str(r.get("id")): r for r in rows}
            checks.append(
                engine.check(
                    "counts_read_back",
                    all(
                        (by_id.get(str(row.get("id"))) or {}).get("prefix") == row.get("prefix")
                        for row in counted
                    ),
                    dimensions=[row.get("name") for row in counted],
                )
            )
        threads = annotated.get("threads_called_out") or []
        if threads:
            by_key = {(str(r.get("model") or "").lower(), str(r.get("id"))): r for r in rows}
            checks.append(
                engine.check(
                    "thread_callouts_read_back",
                    all(
                        (
                            by_key.get((str(t.get("model") or "").lower(), str(t.get("id")))) or {}
                        ).get("prefix")
                        == t.get("prefix")
                        and (
                            by_key.get((str(t.get("model") or "").lower(), str(t.get("id")))) or {}
                        ).get("suffix", "")
                        == t.get("suffix")
                        for t in threads
                    ),
                    dimensions=[t.get("on") for t in threads],
                )
            )
        if opts.get("chamfers") is not None:
            expected_style = "cd" if opts["chamfers"] == "c" else "d_x_45"
            reported_chamfers = annotated.get("chamfers_called_out")
            checks.append(
                engine.check(
                    "requested_chamfer_style_reported",
                    isinstance(reported_chamfers, list)
                    and all(row.get("style") == expected_style for row in reported_chamfers),
                    expected=expected_style,
                    reported=reported_chamfers,
                )
            )
        boxes, missing_boxes = _text_boxes(after)
        observations = [
            {
                "observation": "refused_views",
                "refused": (data.get("annotated") or {}).get("refused"),
            },
            {
                "observation": "zeros_taken_off",
                "dimensions": (data.get("annotated") or {}).get("zeros_taken_off") or [],
            },
            {
                "observation": "datums_and_full_turns_taken_off",
                "datums": (data.get("annotated") or {}).get("datums_taken_off") or [],
                "full_turns": (data.get("annotated") or {}).get("full_turns_taken_off") or [],
                "meaning": "a datum's own dimensions place other features, which carry what a "
                "reader needs, and a revolve's full turn needs none; name the feature with "
                "--feature to show them",
            },
            {
                "observation": "moved_into_sight",
                "dimensions": sighted,
                "meaning": "diameters Creo showed on a circle their view cannot see -- behind "
                "other material -- moved to a view that sees the cylinder",
            },
            {
                "observation": "diameters_on_their_steps",
                "dimensions": (data.get("annotated") or {}).get("diameters_on_their_steps") or [],
                "meaning": "a turned part's diameters, each moved over the step it measures, "
                "halfway between the axis and the edge, in the views that see the axis from "
                "the side",
            },
            {
                "observation": "counts_prefixed",
                "dimensions": counted,
                "taken_off": annotated.get("counts_taken_off") or [],
                "meaning": "a patterned hole's diameter given with how many there are, 6X; the "
                "prefix is the dimension's, in the part, which now has unsaved changes",
            },
            {
                "observation": "threads_called_out",
                "threads": threads,
                "meaning": "a cosmetic thread called out on the diameter it is cut on, M25x1.5 "
                "(M24 for a coarse one), its minor diameter taken off this drawing; the prefix "
                "and suffix belong to the part's dimension and leave the part unsaved",
            },
            {
                "observation": "chamfers_called_out",
                "dimensions": annotated.get("chamfers_called_out") or [],
                "meaning": "a 45-degree chamfer's dimension written as its size by the angle, "
                "1 X 45, or C1 when --chamfers c was requested, in this drawing",
            },
            {
                "observation": "texts_overlapping",
                "pairs": _overlapping(after),
                "checked_dimensions": len(boxes),
                "not_checked": missing_boxes,
                "complete": False,
                "representation": "legacy_native_aggregate",
                "cross_time": "unverified",
                "completeness": "completeness_not_independently_recorded",
                "meaning": "possible intersections of current native aggregate rectangles; "
                "not complete dimension-line, text-glyph or cross-time protection",
            },
            {
                "observation": "brought_onto_the_sheet",
                "dimensions": annotated.get("brought_onto_the_sheet") or [],
                "meaning": "dimensions Creo's spacing left off the sheet, moved back along the "
                "same line from their view to just outside it",
            },
            {"observation": "layout_feedback", **drawing_warnings.feedback(after)},
        ]
        if features is None:
            checks.insert(
                0,
                engine.check(
                    "dimensions_shown",
                    isinstance(shown, int) and shown > 0,
                    shown=shown,
                    before=before_shown,
                ),
            )
        else:
            strays = [r["name"] for r in rows if not own(r, name) and not _owned(r, features)]
            checks.insert(0, engine.check("only_the_named_features_dimensions", not strays))
            observations.append({"observation": "dimensions_shown", "shown": shown})
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": observations,
            "not_checked": ["dimension_layout"],
        }

    return engine.Plan(
        op="drawing.annotate",
        request={"model": name}
        | ({"features": features} if features is not None else {})
        | ({"with_zero": True} if opts.get("with_zero") else {})
        | ({"chamfers": opts["chamfers"]} if opts.get("chamfers") else {}),
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing annotate",
            "model": name,
            "views": [v["name"] for v in before["views"]],
            "features": features,
            "layout_feedback": drawing_warnings.feedback(before),
            "future_dimension_extents": "not predicted before native annotation",
            "effect": "the model's dimensions and hole axes are shown in the views Creo finds "
            "them suited to, then spaced out"
            + (
                "; only the named features' dimensions stay shown: the others are taken off this "
                "drawing for good, as drawing hide-dimension does"
                if features
                else "; dimensions taken off this drawing earlier stay off"
            )
            + (
                ""
                if opts.get("with_zero")
                else "; a dimension of 0 -- a feature on its reference, shown by its centre "
                "lines -- is taken off for good"
            )
            + "; a diameter on a circle its view cannot see goes to a view that sees it; a "
            "patterned hole's diameter gets its count as a prefix, 6X, in the part; a 45-degree "
            "chamfer is written 1 X 45; a dimension left off the sheet is brought back beside its "
            "view",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("dimensions"),
        before=before.get("dimensions"),
        arguments={
            "model": opts["model"],
            "feature": opts.get("feature"),
            "with_zero": bool(opts.get("with_zero")),
            "chamfers": opts.get("chamfers"),
        },
    )


def annotate(opts: dict) -> dict:
    return engine.write("drawing annotate", opts, _prepare_annotate, _plan_annotate)


# ------------------------------------------------------------------ hide-dimension


def _prepare_hide(opts: dict) -> dict:
    return {
        "name": _drawing(opts),
        "dimensions": _list(opts["dimension"], "dimension", DIMENSION_REF),
    }


def _match(rows: list, wanted: str) -> list:
    dim, _, model = wanted.partition("@")
    return [
        r
        for r in rows
        if str(r.get("name")).lower() == dim.lower()
        and (not model or str(r.get("model")).lower() == model.lower())
    ]


def _plan_hide(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted = pre["name"], pre["dimensions"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    rows = before.get("dimensions") or []
    doomed = []
    for w in wanted:
        hits = _match(rows, w)
        if not hits:
            raise Error(
                "E_NOT_FOUND",
                "the drawing shows no dimension of that name",
                {
                    "dimension": w,
                    "shown": [r.get("name") for r in rows],
                    "fix": f"creo-cli model show --model {name} lists them under dimensions",
                    "_untrusted": ["dimension", "shown"],
                },
            )
        if len(hits) > 1:
            raise Error(
                "E_CONFLICT",
                "two models' dimensions carry that name; write it as name@model",
                {
                    "dimension": w,
                    "models": [h.get("model") for h in hits],
                    "_untrusted": ["models"],
                },
            )
        if own(hits[0], name):
            raise Error(
                "E_CONFLICT",
                "that dimension was made on the drawing, not shown from a model; remove it",
                {
                    "dimension": w,
                    "fix": f"creo-cli drawing item remove --model {name} "
                    f"--item dimension:{hits[0]['name']}",
                    "_untrusted": ["dimension", "fix"],
                },
            )
        doomed.append(hits[0])

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("dimensions") or []
        still = [d["name"] for d in doomed if any(_same(d, a) for a in after)]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("dimensions_taken_off", not still, still_shown=still),
                engine.check(
                    "other_dimensions_kept", len(after) == len(rows) - len(doomed), shown=len(after)
                ),
            ],
            "not_checked": ["the_models_own_dimensions_untouched_by_design"],
        }

    return engine.Plan(
        op="drawing.hide-dimension",
        request={"model": name, "dimensions": [f"{d['name']}@{d['model']}" for d in doomed]},
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing hide-dimension",
            "model": name,
            "takes_off": doomed,
            "effect": "the dimensions leave this drawing for good: Creo does not show an erased "
            "dimension again, not even through drawing annotate; the model keeps them, and a new "
            "drawing shows them",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("dimensions"),
        before=rows,
        arguments={"model": opts["model"], "dimension": opts["dimension"]},
    )


def _same(a: dict, b: dict) -> bool:
    return str(a.get("id")) == str(b.get("id")) and a.get("model") == b.get("model")


def hide_dimension(opts: dict) -> dict:
    return engine.write("drawing hide-dimension", opts, _prepare_hide, _plan_hide)


# ------------------------------------------------------------------ add-note


def _prepare_note(opts: dict) -> dict:
    for key in ("x", "y"):
        if not math.isfinite(opts[key]):
            raise Error("E_VALIDATION", "x and y are sheet coordinates", {"path": key})
    return {"name": _drawing(opts), "text": note_text(opts["text"])}


def _plan_note(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, note = pre["name"], pre["text"]
    client.require_capability(drawing_note_recovery.CAPABILITY, 1)
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = drawing_note_recovery.snapshot(client, name)
    engine.store_directory(before["drawing"], s)
    x, y = opts["x"], opts["y"]
    on_sheet(before["drawing"], x, y, "note")
    wanted = drawing_note_recovery.intent(before, note, [x, y])

    def verify(c: Client, data: dict):
        after = drawing_note_recovery.snapshot(
            c, name, baseline=False, source_models=wanted["source_models"]
        )
        proof = drawing_note_recovery.verify(before, wanted, after)
        data.update(note=proof["note"], note_readback=proof)
        if proof["accepted"]:
            from copy import deepcopy

            planned.verified_observation = deepcopy(after)
        return data, {
            "level": "selected_postconditions_verified",
            "checks": proof["checks"],
            "observations": [
                {"observation": "independent_note_bounds", **proof["bounds_observation"]}
                if "bounds_observation" in proof
                else {"observation": "note_readback_incomplete"},
                {"observation": "layout_feedback", **drawing_warnings.feedback(after["drawing"])},
            ],
            "not_checked": proof["not_checked"],
        }

    planned = engine.Plan(
        op="drawing.add-note",
        request={"model": name, "text": note, "at": [x, y]},
        target=name,
        binding={"note_before": before, "note_intent": wanted},
        preview={
            "command": "drawing add-note",
            "model": name,
            "text": note,
            "at": [x, y],
            "note_intent": wanted,
            "not_checked": drawing_note_recovery.NOT_CHECKED,
            "layout_feedback": drawing_warnings.feedback(before["drawing"]),
            "proposed_note_bounds": {
                "available": False,
                "reason": "actual text extent is not predicted before creation; "
                "anchor is not a zero-size text box",
            },
        },
        verify=verify,
        observe=lambda c: drawing_note_recovery.snapshot(
            c, name, baseline=False, source_models=wanted["source_models"]
        ),
        before=before,
        arguments={"model": opts["model"], "text": opts["text"], "x": x, "y": y},
    )
    return planned


def add_note(opts: dict) -> dict:
    return engine.write("drawing add-note", opts, _prepare_note, _plan_note)


# ------------------------------------------------------------------ declarations

VIEW = shape(
    {
        **VIEW_NATIVE_READBACK_PROPERTIES,
        "name": S,
        "sheet": N,
        "scale": N,
        "model": NS,
        "outline": {"type": ["array", "null"]},
        "type": NS,
        "parent": NS,
        "sections": array(S),
        "section_area": NS,
        "display": NS,
    },
    ("name", "sheet", "scale"),
)
PLACE = {"type": ["array", "null"], "items": N}
DIMENSION = shape(
    {
        "name": S,
        "id": S,
        "model": S,
        "value": NN,
        "type": S,
        "feature": {"type": ["object", "null"]},
        "view": NS,
        "reference": NB,
        "at": PLACE,
        "box": {"type": ["array", "null"], "items": PLACE},
        "box_status": S,
        "sheet": NI,
        "tolerance": {"type": ["object", "null"]},
    },
    ("name", "id", "model", "value"),
)
NOTE = shape(
    {
        "id": S,
        "sheet": NI,
        "text": S,
        "at": PLACE,
        "box": {"type": ["array", "null"], "items": PLACE},
        "read_only": NB,
        "attachment_readback": shape(
            {
                "complete": B,
                "sheet": NI,
                "view": NS,
                "view_id": NS,
                "background": NB,
                "kind": NS,
                "source": S,
            },
            ("complete",),
        ),
        "displayed_text": S,
        "membership_readback": shape({}),
        "bounds_readback": {
            **shape({}),
            "description": "Optional native 2D line-envelope four-corner readback, actual sheet "
            "transform and independent z/affine/finite gates. Missing/incomplete bounds never "
            "mean zero text extent or complete layout.",
        },
        "leaders": array(shape({})),
        "leaders_complete": B,
        "reference_source": S,
    },
    ("id", "text"),
)
TABLE = shape(
    {
        "id": S,
        "rows": N,
        "columns": N,
        "cells": array({"type": "array", "items": NS}),
        "at": PLACE,
        "size": PLACE,
        "outline": {"type": ["array", "null"], "items": PLACE},
        "sheet": NI,
        "segments": NI,
        "rotation": NN,
        "bounds_source": NS,
        "from_format": NB,
        "cell_references": {"type": ["array", "null"], "items": shape({})},
    },
    ("id", "rows", "columns", "cells"),
)
SYMBOL = shape({"id": S, "definition": NS, "at": PLACE, "values": shape({})}, ("id",))
GTOL = shape(
    {
        "id": S,
        "model": S,
        "type": NS,
        "value": NS,
        "datums": array(S),
        "attached": NS,
        "at": PLACE,
    },
    ("id", "model", "type", "value"),
)
DATUM = shape({"id": S, "label": S, "on": NS}, ("id", "label"))
SUMMARY = {
    "model": S,
    "type": S,
    "models": array(S),
    "sheets": array(shape({})),
    "views": array(VIEW),
    "dimensions_shown": NI,
    "draft_entities": NI,
    "draft_arcs": {
        "type": ["array", "null"],
        "items": shape(
            {
                "id": S,
                "sheet": INT,
                "center": PLACE,
                "radius": N,
                "start_angle": N,
                "end_angle": N,
                "source": S,
            }
        ),
    },
    "dimensions": {"type": ["array", "null"], "items": DIMENSION},
    "notes": {"type": ["array", "null"], "items": NOTE},
    "tables": {"type": ["array", "null"], "items": TABLE},
    "symbols": {"type": ["array", "null"], "items": SYMBOL},
    "datums": {"type": ["array", "null"], "items": DATUM},
    "gtols": {"type": ["array", "null"], "items": GTOL},
    "origin": NS,
    "modified": NB,
}
COMMANDS = [
    Command(
        "drawing create",
        "Create a drawing of a part or assembly in session from a sheet template (a0..a4, a..f) "
        "or a template of your own",
        create,
        written(
            shape(
                SUMMARY
                | {
                    "template": S,
                    "projection": {
                        "type": ["string", "null"],
                        "enum": ["first_angle", "third_angle", None],
                    },
                    "views_replaced": array(S),
                    "views_laid_out": array(S),
                    "scale_chosen": {"type": ["object", "null"]},
                    "scale_labels": NS,
                },
                ("model", "models", "sheets", "views"),
            )
        ),
        (
            Param("name", required=True, description="the new drawing's name"),
            Param("of", required=True, description="the part or assembly to draw, in session"),
            Param("sheet", choices=SHEETS, description="one of Creo's sheet templates"),
            Param("template", description="or a *.drw template in Creo's working directory"),
            Param(
                "scale",
                description="the sheet's scale, 2:1, 1:1, 1:2 ...; omitted, the largest preferred "
                "scale at which the views fit with room for dimensions",
            ),
            Param(
                "display",
                choices=DISPLAYS,
                description="how its views are drawn: lines (default; visible edges, as a drafter "
                "draws), hidden (hidden edges dashed too) or shaded",
            ),
            Param(
                "projection",
                choices=tuple(PROJECTIONS),
                description="first (ISO E, GB, DIN: the top view below the front, the left view on "
                "its right) or third angle (ASME, JIS: the top view above); omitted, the "
                "template's -- Creo's ISO sheets are first angle, its ANSI ones third",
            ),
            Param(
                "views",
                choices=tuple(VIEWS_MEANING),
                description="standard (the default on Creo's sheets: FRONT, TOP, the side view "
                "and ISOMETRIC, by the projection), template (the default for a template of your "
                "own: what it lays out) or none (an empty sheet for add-view)",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--name bracket --of bracket --sheet a3 --projection first",
        service_ops=("drawing.create", "drawing.lay-out"),
    ),
    Command(
        "drawing add-view",
        "Add a view to a drawing: a general view in a standard orientation, a projection of "
        "another view -- either cut as a section through a plane -- or a detail view of a "
        "region of another view, drawn larger; x and y are the view's middle on the sheet",
        add_view,
        written(
            shape(
                SUMMARY
                | {
                    "view": VIEW,
                    "section": shape({"name": S, "made_in_part": B}),
                    "view_acceptance_scope": shape(
                        {
                            "required_independent_checks": array(S),
                            "source_snapshot_comparison": S,
                            "boolean_meaning": S,
                            "engineering_acceptance": {
                                "type": "string",
                                "enum": ["not_established_by_this_command"],
                            },
                            "not_checked": array(S),
                        },
                        (
                            "required_independent_checks",
                            "source_snapshot_comparison",
                            "boolean_meaning",
                            "engineering_acceptance",
                            "not_checked",
                        ),
                    ),
                },
                ("model", "view"),
            )
        ),
        (
            MODEL,
            Param("type", required=True, choices=("general", "projection", "detail")),
            Param("orientation", choices=ORIENTATIONS, description="a general view's orientation"),
            Param("parent", description="the view a projection or detail is taken from"),
            Param("x", "number", required=True, description="sheet x, in the drawing's units"),
            Param("y", "number", required=True, description="sheet y, in the drawing's units"),
            Param(
                "scale",
                "number",
                description="the view's own scale; a detail's defaults to twice its parent's; "
                "an explicit first general-view scale must equal the independently readable "
                "current sheet default (one model, one sheet); set a new page's default with "
                "drawing create --scale",
            ),
            Param(
                "name",
                description="the view's name; by default a general view's is its orientation "
                "(FRONT), a section's SECTION_<letter>, a projection's PROJECTION, a detail's the "
                "next letter -- the same whatever language Creo speaks",
            ),
            Param(
                "section",
                description="cut the view by this cross-section of the model; with --plane, "
                "one is made if the model has none of that name",
            ),
            Param(
                "plane",
                description="the datum plane or flat surface:<id> to cut a new cross-section "
                "through; named by the next letter unless --section names it",
            ),
            Param(
                "half",
                description="with a section: the datum plane or flat surface:<id> square to it "
                "that divides the view, cut on one side and whole on the other",
            ),
            Param(
                "exploded",
                "boolean",
                description="request a general assembly view's exploded Boolean display switch "
                "with drawing_view_exploded_readback 1 and assembly_explosion_context_readback 1: "
                "complete named-state inventory; drawing-context global display is not_checked; "
                "native per-view Boolean independently "
                "verified; this does not select or prove the per-view named state, actual "
                "separated projection or normal assembly placement; these remain not_checked; "
                "cannot create a source cross-section",
            ),
            Param(
                "display",
                choices=DISPLAYS,
                description="how the view is drawn: lines (default; visible edges, as a drafter "
                "draws), hidden (hidden edges dashed too) or shaded",
            ),
            Param(
                "edges",
                choices=("total", "area"),
                description="a section's model edges: total, everything beyond the cut as well "
                "(Creo's default), or area, the cut face alone -- a shaft's section through a "
                "keyway",
            ),
            Param(
                "center",
                description="a detail's edge:<id>: an arc's centre, a line's middle -- or, with "
                "--near, the point of the edge nearest that point",
            ),
            Param(
                "near",
                description="with --center: a model point x,y,z; the detail is centred on the "
                "point of the edge nearest it -- a chamfer at the rim of a shaft whose end circle "
                "is seen edge on",
            ),
            Param(
                "radius",
                "number",
                description="a detail's circle, in the model's units; it must reach the edge",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --type projection --parent FRONT --plane SEC_H1 --x 110 --y 40",
        service_ops=("drawing.add-view", "geometry.list"),
    ),
    Command(
        "drawing move-view",
        "Move a view on its sheet, with what it shows: its middle goes to x, y",
        move_view,
        written(shape(SUMMARY | {"view": VIEW}, ("model", "view"))),
        (
            MODEL,
            Param("view", required=True, description="the view's name, as model show lists it"),
            Param("x", "number", required=True, description="sheet x, in the drawing's units"),
            Param("y", "number", required=True, description="sheet y, in the drawing's units"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --view B --x 330 --y 90",
        service_ops=("drawing.move-view",),
    ),
    Command(
        "drawing annotate",
        "Show the model's dimensions and hole axes on the drawing's views, as Show Model "
        "Annotations does; with --feature, only the dimensions those features own, the others "
        "taken off for good",
        annotate,
        written(
            shape(
                SUMMARY
                | {
                    "annotated": shape(
                        {
                            "shown": N,
                            "by_view": shape({}),
                            "taken_off": array(shape({})),
                            "zeros_taken_off": array(shape({})),
                            "datums_taken_off": array(shape({})),
                            "full_turns_taken_off": array(shape({})),
                            "diameters_on_their_steps": array(shape({})),
                            "moved_into_sight": array(shape({})),
                            "counts_prefixed": array(shape({})),
                            "counts_taken_off": array(shape({})),
                            "chamfers_called_out": array(shape({})),
                            "threads_called_out": array(shape({})),
                            "brought_onto_the_sheet": array(shape({})),
                        },
                        ("shown",),
                    )
                },
                ("model", "annotated"),
            )
        ),
        (
            MODEL,
            Param(
                "feature",
                description="comma-separated feature names or ids whose dimensions to show; "
                "omitted, all of them",
            ),
            Param(
                "with-zero",
                "boolean",
                description="keep dimensions of 0 -- a feature on its reference -- which are "
                "otherwise taken off",
            ),
            Param(
                "chamfers",
                choices=("angle", "c"),
                description="how a 45-degree chamfer is written: angle (default, 1 X 45, ISO 129) "
                "or c (C1, as GB and JIS drawings write it)",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --feature BASE,H1",
        service_ops=("drawing.annotate", "feature.list"),
    ),
    Command(
        "drawing hide-dimension",
        "Take shown dimensions off a drawing for good -- duplicates, ones a reader does not "
        "need; the model keeps them. Names as model show lists them under dimensions",
        hide_dimension,
        written(shape(SUMMARY | {"taken_off": array(shape({}))}, ("model", "taken_off"))),
        (
            MODEL,
            Param(
                "dimension",
                required=True,
                description="comma-separated dimension names, d12 or d12@part.prt",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --dimension d4,d7",
        service_ops=("drawing.hide-dimension",),
    ),
    Command(
        "drawing add-note",
        "Place a note on a drawing at sheet coordinates: a quantity (25X), a general note, a "
        "title; in the drawing's own lettering",
        add_note,
        written(shape(SUMMARY | {"note": NOTE}, ("model", "note"))),
        (
            MODEL,
            Param("text", required=True, description="the note; \\n breaks a line"),
            Param("x", "number", required=True, description="sheet x, in the drawing's units"),
            Param("y", "number", required=True, description="sheet y, in the drawing's units"),
        ),
        write=True,
        untrusted=WRITTEN,
        example='--model bracket --text "4X M6" --x 40 --y 30',
        service_ops=("drawing.add-note",),
    ),
]
