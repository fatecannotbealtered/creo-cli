"""feature extrude, revolve, datum-plane, datum-axis, round, chamfer, hole, shell, draft, rib,
pattern, mirror: one command per tool on Creo's ribbon, each a definition in a request file."""

from __future__ import annotations

import math
from copy import deepcopy

from .. import building, engine
from ..core import Error, read_request
from ..registry import MODEL, REQUEST, Command, Param
from ..requests import (
    CHAMFER_EXAMPLE,
    CHAMFER_SCHEMA,
    DATUM_AXIS_EXAMPLE,
    DATUM_AXIS_SCHEMA,
    DATUM_PLANE_EXAMPLE,
    DATUM_PLANE_SCHEMA,
    DRAFT_EXAMPLE,
    DRAFT_SCHEMA,
    HOLE_EXAMPLE,
    HOLE_SCHEMA,
    PATTERN_EXAMPLE,
    PATTERN_SCHEMA,
    ROUND_EXAMPLE,
    ROUND_SCHEMA,
    SHELL_EXAMPLE,
    SHELL_SCHEMA,
    THREAD_EXAMPLE,
    THREAD_SCHEMA,
    hole_placement,
    validate_datum_axis,
    validate_datum_plane,
    validate_draft,
    validate_edges,
    validate_hole,
    validate_pattern,
    validate_shell,
    validate_thread,
)
from ..schemas import FEATURE, NN, NS, UNITS, WRITTEN, B, N, S, array, shape, written
from ..sketch import (
    DEFAULT_PLANES,
    EXTRUDE_EXAMPLE,
    EXTRUDE_SCHEMA,
    FEATURE_NAME,
    REFERENCE,
    REVOLVE_EXAMPLE,
    REVOLVE_SCHEMA,
    RIB_EXAMPLE,
    RIB_SCHEMA,
    SWEEP_EXAMPLE,
    SWEEP_SCHEMA,
    area,
    bounds,
    chain_length,
    entities,
    has_spline,
    loops,
    needs_native,
    path_length,
    path_start_tangent,
    path_turn,
    revolved_volume,
    swept_volume,
    validate_extrude,
    validate_revolve,
    validate_rib,
    validate_sweep,
)
from ..transport import Client
from ..validation import validate

EXPECTED_TYPE = {"add": "FEATTYPE_PROTRUSION", "remove": "FEATTYPE_CUT"}
# Measured: Creo's spline through the points agrees with the model within 5e-4 of area.
SPLINE_TOLERANCE = 1e-3
SPLINE_MEANING = (
    "a spline is modeled as the cubic B-spline through its points at their chord-length "
    "parameters, as Creo's agrees within about 5e-4"
)
SWEPT_MEANING = (
    "signed, negative for a cut; equals the change only when an added solid overlaps no existing "
    "material and a cut lies wholly inside the part"
)


def _part(opts: dict) -> str:
    return engine.model_name(opts["model"], ("prt",))


def _write(command: str, prepare, plan_):
    def run(opts: dict) -> dict:
        if command in (
            "feature hole",
            "feature round",
            "feature revolve",
            "feature datum-plane",
            "feature datum-axis",
            "feature shell",
            "feature draft",
            "feature rib",
        ):
            from ..workflow_state import request_file

            def prepare_bound(options):
                before = request_file(options["request"])
                prepared = prepare(options)
                if request_file(options["request"]) != before:
                    raise Error(
                        "E_CONFLICT",
                        "request changed during validation",
                        {"conflict": "state_drift"},
                    )
                prepared["request_identity"] = {k: v for k, v in before.items() if k != "content"}
                return prepared

            def plan_bound(client, options, prepared):
                from .. import machining, prismatic, prismatic_draft, prismatic_rib, revolved

                domain = (
                    prismatic_rib
                    if command in prismatic_rib.COMMANDS
                    else prismatic_draft
                    if command in prismatic_draft.COMMANDS
                    else prismatic
                    if command in prismatic.COMMANDS
                    else revolved
                    if command in revolved.COMMANDS
                    else machining
                )

                prepared = prepared | {
                    "request": domain.canonical_request(
                        client, prepared["name"], prepared["request"]
                    )
                }
                result = plan_(client, options, prepared)
                result.binding = result.binding | {"request_identity": prepared["request_identity"]}
                if domain in (prismatic, prismatic_draft, prismatic_rib):
                    return domain.checked_plan(client, result, prepared["request"], options)
                return domain.checked_plan(client, result, prepared["request"])

            return engine.write(command, opts, prepare_bound, plan_bound)
        return engine.write(command, opts, prepare, plan_)

    run.__name__ = command.replace(" ", "_").replace("-", "_")
    return run


# ------------------------------------------------------------------ sketched: extrude, revolve


def _is_face(ref: str) -> bool:
    return ref.lower().startswith("surface:")


def _planes_exist(
    ctx: building.Context, sketch: dict, client: Client | None = None, field: str = "sketch"
) -> None:
    planes = ctx.before["datum_planes"]
    named = [("plane", sketch["plane"]), ("orient_ref", sketch["orient_ref"])]
    named += [("references", r) for r in sketch.get("references", [])]
    faces = [wanted for role, wanted in named if _is_face(wanted) and role != "references"]
    if faces and client is not None:
        found = building.references(client, ctx_name(ctx), faces)
        for ref in faces:
            if found[ref].get("kind") != "surface" or found[ref].get("type") != "plane":
                raise Error(
                    "E_VALIDATION",
                    "a sketch goes on a datum plane or a flat face of the part",
                    {"reference": ref, "is": found[ref].get("type"), "_untrusted": ["reference"]},
                )
    for role, wanted in named:
        if _is_face(wanted) and role != "references":
            continue
        if not engine.by_name(planes, wanted):
            raise Error(
                "E_NOT_FOUND",
                "the sketch names a datum plane the part does not have",
                {
                    "field": field + "." + role,
                    "plane": wanted,
                    "datum_planes": planes,
                    "_untrusted": ["plane", "datum_planes"],
                },
            )


def _face_references(client: Client, name: str, sketch: dict) -> list | None:
    """The default datum planes square to a face a sketch is on, when there are two of them:
    what a face's sketch is dimensioned to unless references are named."""
    if "references" in sketch or not _is_face(sketch["plane"]):
        return None
    found = building.references(client, name, [sketch["plane"], *DEFAULT_PLANES])
    n = found[sketch["plane"]].get("normal")
    if not n:
        return None
    square = [
        p
        for p in DEFAULT_PLANES
        if found[p].get("normal") and abs(_dot(_unit(n), _unit(found[p]["normal"]))) < 1e-9
    ]
    return square if len(square) == 2 else None


def _native_references(sketch: dict, field: str = "sketch") -> list:
    """The two planes a native sketch is dimensioned to: named, or the other default two."""
    if "references" not in sketch and sketch["plane"].upper() not in DEFAULT_PLANES:
        raise Error(
            "E_VALIDATION",
            f"sketching on a plane other than RIGHT, TOP or FRONT needs {field}.references: two "
            "datum planes perpendicular to it, to dimension the sketch to",
            {"path": f"request.{field}.references"},
        )
    return sketch.get("references") or [p for p in DEFAULT_PLANES if p != sketch["plane"].upper()]


FRAME_MEANING = (
    "a sketch point [u, v] is the model point origin + u x + v y; the sketch plane's normal "
    "points at the viewer, and side one goes the other way"
)


def _cross(a: list, b: list) -> list:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _dot(a: list, b: list) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _clean(v: list) -> list:
    return [0.0 if abs(c) < 1e-12 else round(c, 12) for c in v]


def _meet(planes: list) -> list | None:
    """The point three planes share, (normal, point) each; None when they share no one point."""
    (n0, p0), (n1, p1), (n2, p2) = planes
    det = _dot(n0, _cross(n1, n2))
    if abs(det) < 1e-9:
        return None
    d0, d1, d2 = _dot(n0, p0), _dot(n1, p1), _dot(n2, p2)
    terms = [_cross(n1, n2), _cross(n2, n0), _cross(n0, n1)]
    return _clean(
        [(d0 * terms[0][k] + d1 * terms[1][k] + d2 * terms[2][k]) / det for k in range(3)]
    )


def _frame(client: Client, name: str, sketch: dict, references: list | None) -> dict | None:
    """Where a sketch lies in the model, as Creo lays it out -- measured on RIGHT, TOP and
    FRONT in every orientation: the plane's normal points at the viewer; orient_ref's normal
    is the sketch's +u (right), -u (left), +v (up) or -v (down); the other axis completes a
    right-handed frame; the origin is where the sketch references cross."""
    wanted = [sketch["plane"], sketch["orient_ref"], *(references or [])]
    refs = building.references(client, name, wanted)
    n, r = refs[sketch["plane"]].get("normal"), refs[sketch["orient_ref"]].get("normal")
    if not n or not r:
        return None
    n, r = _unit(n), _unit(r)
    orient = sketch.get("orient", "right")
    if orient in ("right", "left"):
        x = r if orient == "right" else [-c for c in r]
        y = _cross(n, x)
    else:
        y = r if orient == "up" else [-c for c in r]
        x = _cross(y, n)
    origin = None
    if references and len(references) == 2:
        planes = [refs[k] for k in (sketch["plane"], *references)]
        if all(p.get("normal") and p.get("origin") for p in planes):
            origin = _meet([(_unit(p["normal"]), p["origin"]) for p in planes])
    return {
        "origin": origin,
        "x": _clean(x),
        "y": _clean(y),
        "normal": _clean(n),
        "meaning": FRAME_MEANING,
    }


def _in_model(frame: dict | None, uv: list) -> list | None:
    if not frame or frame.get("origin") is None:
        return None
    return _clean(
        [frame["origin"][k] + uv[0] * frame["x"][k] + uv[1] * frame["y"][k] for k in range(3)]
    )


def _swept_box(frame: dict | None, profile: dict, depth: float, side: str) -> list | None:
    """The box an extrusion will fill: the profile's box carried along the plane's normal."""
    if not frame or frame.get("origin") is None:
        return None
    (u0, v0), (u1, v1) = bounds(profile)
    corners = [_in_model(frame, [u, v]) for u in (u0, u1) for v in (v0, v1)]
    n = frame["normal"]
    reach = {"one": (-depth, 0.0), "two": (0.0, depth), "symmetric": (-depth / 2, depth / 2)}[side]
    points = [[c[k] + t * n[k] for k in range(3)] for c in corners for t in reach]
    return [
        _clean([min(p[k] for p in points) for k in range(3)]),
        _clean([max(p[k] for p in points) for k in range(3)]),
    ]


def _sketch(client: Client, ctx: building.Context, q: dict) -> dict:
    """What a sketch on a datum plane will be, checked against the part: its planes exist, the
    profile can be drawn in this session, and what it is dimensioned to."""
    sketch, profile = q["sketch"], q["sketch"]["profile"]
    _planes_exist(ctx, sketch, client)
    square = _face_references(client, ctx_name(ctx), sketch)
    if square:
        sketch = sketch | {"references": square}
        q["sketch"] = sketch
    kind = profile["type"]
    native = ctx.session["native_sketch_available"]
    centerline = isinstance(q.get("axis"), list)
    several = needs_native(profile)
    if (several or centerline) and not native:
        raise Error(
            "E_UNSUPPORTED",
            "rectangles, polygons, slots, outlines, profiles with holes and sketched axes need "
            "the native sketch library, which this Creo session has not loaded",
            {
                "native_sketch_library": ctx.session.get("native_sketch_library"),
                "fix": "register creo_cli_sketch.dll with the service (docs/SERVICE.md)",
                "_untrusted": ["native_sketch_library"],
            },
        )
    drawn_by = "native" if several or centerline or (kind == "circle" and native) else "java"
    references = _native_references(sketch) if drawn_by == "native" else sketch.get("references")
    frame = _frame(
        client,
        ctx_name(ctx),
        sketch,
        references or [p for p in DEFAULT_PLANES if p != sketch["plane"].upper()]
        if sketch["plane"].upper() in DEFAULT_PLANES
        else references,
    )
    return {
        "plane": sketch["plane"],
        "orient_ref": sketch["orient_ref"],
        "orient": sketch.get("orient", "right"),
        "references": references,
        "profile": profile,
        "entities": entities(profile),
        "drawn_by": drawn_by,
        "frame": frame,
    }


def ctx_name(ctx: building.Context) -> str:
    return ctx.before["model"]


def _engine_observation(data: dict) -> list:
    return [{"observation": "sketch_engine", "engine": (data.get("sketch") or {}).get("engine")}]


# What a sketched feature's reply says about its sketch: each dimension by name, its value and
# what it measures -- given by the CLI as a drafter would, or chosen by Creo -- and what Creo
# holds together (see SketchPlan in the service).
SKETCHED_KEYS = ("sketch_dimensions", "held_together", "dimension_plan")


def _sketched(command: str, revolve: bool):
    def prepare(opts: dict) -> dict:
        raw = read_request(opts["request"])
        return {
            "name": _part(opts),
            "request": validate_revolve(raw) if revolve else validate_extrude(raw),
        }

    def plan_(client: Client, opts: dict, pre: dict) -> engine.Plan:
        name, q = pre["name"], pre["request"]
        ctx = building.context(client, name, q)
        sketch = _sketch(client, ctx, q)
        material = q.get("material", "add")
        sign = -1 if material == "remove" else 1
        preview = {
            "feature": {
                "type": EXPECTED_TYPE[material],
                "name": q.get("name"),
                "side": q.get("side", "one"),
                "body": "all" if material == "remove" else q.get("body", "default"),
            },
            "sketch": sketch,
            "profile_area": area(q["sketch"]["profile"]),
        }
        expected = None
        axis_refs = {}
        if revolve:
            if isinstance(q["axis"], str):
                axis_refs = building.references(client, name, [q["axis"]])
                found = axis_refs[q["axis"]]
                if found.get("kind") != "axis" and not (
                    found.get("kind") == "edge" and found.get("type") == "line"
                ):
                    raise Error(
                        "E_VALIDATION",
                        "a revolve turns about an axis or a straight edge",
                        {
                            "reference": q["axis"],
                            "is": found.get("kind"),
                            "_untrusted": ["reference"],
                        },
                    )
                preview["axis"] = {"external": found}
            else:
                expected = sign * revolved_volume(q["sketch"]["profile"], q["axis"], q["angle"])
                preview["axis"] = {"sketched": q["axis"]}
            preview["angle_deg"] = q["angle"]
            if isinstance(q["axis"], list):
                preview["axis"]["in_model"] = [_in_model(sketch["frame"], p) for p in q["axis"]]
        else:
            expected = sign * area(q["sketch"]["profile"]) * q["depth"]
            preview["depth"] = q["depth"]
            frame = sketch["frame"]
            side = q.get("side", "one")
            if frame:
                n = frame["normal"]
                preview["extrudes_toward"] = (
                    _clean({"one": [-c for c in n], "two": list(n)}[side])
                    if side != "symmetric"
                    else [_clean(list(n)), _clean([-c for c in n])]
                )
                preview["model_box"] = _swept_box(frame, q["sketch"]["profile"], q["depth"], side)
        preview["expected_volume_change"] = expected
        preview["expected_volume_change_meaning"] = (
            SWEPT_MEANING + ("; " + SPLINE_MEANING if has_spline(q["sketch"]["profile"]) else "")
            if expected is not None
            else "not estimated: the axis is not in the sketch"
        )
        request = {k: v for k, v in q.items() if k != "units"} | {"model": name}
        return building.plan(
            op="feature.revolve" if revolve else "feature.extrude",
            command=command,
            name=name,
            q=q,
            ctx=ctx,
            request=request,
            preview=preview,
            expected_type=EXPECTED_TYPE[material],
            arguments={"model": opts["model"], "request": q},
            expected_change=expected,
            volume_meaning=SWEPT_MEANING
            + ("; " + SPLINE_MEANING if has_spline(q["sketch"]["profile"]) else ""),
            extra_observations=_engine_observation,
            result_keys=SKETCHED_KEYS,
            binding={"native": ctx.session["native_sketch_available"], "axis": axis_refs},
            volume_tolerance=SPLINE_TOLERANCE
            if has_spline(q["sketch"]["profile"])
            else building.VOLUME_TOLERANCE,
        )

    return _write(command, prepare, plan_)


extrude = _sketched("feature extrude", revolve=False)
revolve = _sketched("feature revolve", revolve=True)


# ------------------------------------------------------------------ rib

RIB_FILL = (
    "the side of the chain the rib fills, looking along it from its first point in the "
    "sketch's own axes; the unique direction toward the proven housing floor is frozen "
    "before dispatch, including when omitted in the original request"
)


ENDS_CARRIED = (
    "the bounded housing's complete inner-wall regions determine each actual endpoint; "
    "the original and actual endpoints and their native attachment faces are frozen "
    "before one creation attempt"
)


def _prepare_rib(opts: dict) -> dict:
    return {"name": _part(opts), "request": validate_rib(read_request(opts["request"]))}


def _plan_rib(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    sketch = q["sketch"]
    _planes_exist(ctx, sketch, client)
    square = _face_references(client, name, sketch)
    if square:
        sketch = sketch | {"references": square}
        q["sketch"] = sketch
    if not ctx.session["native_sketch_available"]:
        raise Error(
            "E_UNSUPPORTED",
            "a rib's sketch is drawn by the native sketch library, which this Creo session has "
            "not loaded",
            {
                "native_sketch_library": ctx.session.get("native_sketch_library"),
                "fix": "register creo_cli_sketch.dll with the service (docs/SERVICE.md)",
                "_untrusted": ["native_sketch_library"],
            },
        )
    references = _native_references(sketch)
    frame = _frame(client, name, sketch, references)
    carried = []  # The bounded checker resolves exact wall intersections from full regions.
    # A chain's ends lie on faces of the part; one outside its box lies on none -- most often
    # a sketch read in the wrong axes (the preview's frame says which way u and v run).
    box = ctx.before.get("bbox")
    if frame and isinstance(box, list) and len(box) == 2:
        size = max(abs(b - a) for a, b in zip(box[0], box[1], strict=True)) or 1.0
        off = [
            point
            for point in (
                _in_model(frame, p) for p in sketch["points"][:: len(sketch["points"]) - 1]
            )
            if any(
                not (lo - 1e-6 * size <= c <= hi + 1e-6 * size)
                for c, lo, hi in zip(point, box[0], box[1], strict=True)
            )
        ]
        if off:
            raise Error(
                "E_VALIDATION",
                "the chain's ends lie on the faces it joins, but these lie outside the part",
                {
                    "path": "request.sketch.points",
                    "ends_in_model": off,
                    "part_box": box,
                    "frame": frame,
                    "fix": "a sketch point [u, v] is origin + u x + v y of the frame; read the "
                    "points in those axes",
                },
            )

    def checks(c: Client, data: dict) -> list:
        change = (data.get("volume") or {}).get("change")
        out = [engine.check("material_added", change is not None and change > 0, change=change)]
        if "fill" in q:
            out.append(
                engine.check(
                    "fill_as_requested", data.get("fill") == q["fill"], fill=data.get("fill")
                )
            )
        return out

    def observed(data: dict) -> list:
        return [
            {"observation": "volume", "change": (data.get("volume") or {}).get("change")},
            {
                "observation": "fill",
                "fill": data.get("fill"),
                "tried_first": data.get("fill_tried") or [],
            },
        ]

    return building.plan(
        op="feature.rib",
        command="feature rib",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_RIB", "name": q.get("name")},
            "sketch": {
                "plane": sketch["plane"],
                "orient_ref": sketch["orient_ref"],
                "orient": sketch.get("orient", "right"),
                "references": references,
                "points": sketch["points"],
                "chain_length": chain_length(sketch["points"]),
                "frame": frame,
                "chain_in_model": [_in_model(frame, p) for p in sketch["points"]],
            },
            "thickness": q["thickness"],
            "side": q.get("side", "symmetric"),
            "fill": q.get("fill", "unique proven floor direction, resolved in rib_intent"),
            "fill_meaning": RIB_FILL,
            "ends_carried": carried,
            "ends_carried_meaning": ENDS_CARRIED,
        },
        expected_type="FEATTYPE_RIB",
        arguments={"model": opts["model"], "request": q},
        result_keys=("fill", "fill_tried", "sketch", *SKETCHED_KEYS),
        extra_checks=checks,
        extra_observations=observed,
        binding={"native": True, "references": references},
    )


rib = _write("feature rib", _prepare_rib, _plan_rib)


# ------------------------------------------------------------------ sweep

SWEEP_MEANING = (
    "the section's area times how far its centroid travels (Pappus) -- "
    + SWEPT_MEANING
    + "; Creo measures a swept round surface to about 1e-3, a swept flat one exactly"
)
SECTION_MEANING = (
    "a section point [u, v] lands at origin + u x + v y, where the sweep starts: y is the path "
    "plane's normal, x that normal crossed with the path's direction there -- the path's left "
    "as its sketch is seen"
)
# Measured: round sections swept along lines and arcs read back 5e-4 to 1.3e-3 under Pappus.
ROUND_SECTION_TOLERANCE = 2e-3


def _prepare_sweep(opts: dict) -> dict:
    return {"name": _part(opts), "request": validate_sweep(read_request(opts["request"]))}


def _plan_sweep(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    path = q["path"]
    _planes_exist(ctx, path, client, field="path")
    square = _face_references(client, name, path)
    if square:
        path = path | {"references": square}
        q["path"] = path
    if not ctx.session["native_sketch_available"]:
        raise Error(
            "E_UNSUPPORTED",
            "a sweep's path and section are drawn by the native sketch library, which this "
            "Creo session has not loaded",
            {
                "native_sketch_library": ctx.session.get("native_sketch_library"),
                "fix": "register creo_cli_sketch.dll with the service (docs/SERVICE.md)",
                "_untrusted": ["native_sketch_library"],
            },
        )
    references = _native_references(path, field="path")
    frame = _frame(client, name, path, references)
    material = q.get("material", "add")
    section = q["section"]
    expected = (-1 if material == "remove" else 1) * swept_volume(path, section)
    start = _in_model(frame, path["start"])
    section_frame = None
    if start is not None:
        tu, tv = path_start_tangent(path)
        t = _unit([tu * frame["x"][k] + tv * frame["y"][k] for k in range(3)])
        n = frame["normal"]
        section_frame = {
            "origin": start,
            "x": _clean(_cross(n, t)),
            "y": _clean(list(n)),
            "normal": _clean(t),
            "meaning": SECTION_MEANING,
        }
    end = _in_model(frame, path["segments"][-1]["to"])
    round_section = any(seg[0] in ("arc", "spline") for loop in loops(section) for seg in loop)

    def checks(c: Client, data: dict) -> list:
        made = data.get("path") or {}
        out = [
            engine.check(
                "path_made",
                made.get("type") == "FEATTYPE_CURVE",
                path=made.get("name"),
                type=made.get("type"),
            )
        ]
        if start is not None and made.get("starts_at") is not None:
            out.append(
                engine.check(
                    "path_starts_where_previewed",
                    _close(made["starts_at"], start) and _close(made.get("ends_at"), end),
                    starts_at=made["starts_at"],
                    ends_at=made.get("ends_at"),
                    previewed=[start, end],
                )
            )
        return out

    def observed(data: dict) -> list:
        made = data.get("path") or {}
        return [
            {
                "observation": "sweep_set_up_at",
                "end": made.get("creo_runs_from"),
                "meaning": "the end of the path Creo runs the sweep from; from the far end the "
                "section is drawn mirrored, so it lands where the preview says either way",
            },
            *_engine_observation(data),
        ]

    return building.plan(
        op="feature.sweep",
        command="feature sweep",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {
                "type": EXPECTED_TYPE[material],
                "name": q.get("name"),
                "body": "all" if material == "remove" else "default",
            },
            "path": {
                "plane": path["plane"],
                "orient_ref": path["orient_ref"],
                "orient": path.get("orient", "right"),
                "references": references,
                "frame": frame,
                "starts_at": start,
                "ends_at": end,
                "length": path_length(path),
                "turns_deg": math.degrees(path_turn(path)),
                "made_as": "a sketched datum curve, "
                + (q["name"] + "_PATH" if q.get("name") else "named by Creo"),
            },
            "section": {"profile": section, "area": area(section), "frame": section_frame},
            "expected_volume_change": expected,
            "expected_volume_change_meaning": SWEEP_MEANING,
        },
        expected_type=EXPECTED_TYPE[material],
        arguments={"model": opts["model"], "request": q},
        expected_change=expected,
        volume_meaning=SWEEP_MEANING,
        result_keys=("path", "sketch"),
        extra_checks=checks,
        extra_observations=observed,
        binding={"native": True, "references": references},
        volume_tolerance=ROUND_SECTION_TOLERANCE if round_section else building.VOLUME_TOLERANCE,
    )


def _close(a: list | None, b: list | None) -> bool:
    return (
        a is not None
        and b is not None
        and all(abs(x - y) <= 1e-6 * (1 + abs(y)) for x, y in zip(a, b, strict=True))
    )


sweep = _write("feature sweep", _prepare_sweep, _plan_sweep)


# ------------------------------------------------------------------ datums


def _prepare_with(validator):
    def prepare(opts: dict) -> dict:
        return {"name": _part(opts), "request": validator(read_request(opts["request"]))}

    return prepare


def _plan_datum_plane(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    spec = q.get("offset") or q["angle"]
    refs = building.references(
        client, name, [spec["from"]] + ([spec["through"]] if "through" in spec else [])
    )
    source = refs[spec["from"]]
    if "offset" in q and "normal" not in source:
        raise Error(
            "E_VALIDATION",
            "a datum plane is offset from a plane: a datum plane or a planar face",
            {"reference": spec["from"], "is": source.get("type"), "_untrusted": ["reference"]},
        )

    def checks(c: Client, data: dict) -> list:
        made = data.get("geometry") or {}
        out = [engine.check("plane_created", made.get("kind") == "datum_plane")]
        if "offset" in q and made.get("normal") and made.get("origin"):
            gap = building.distance_along(source["origin"], source["normal"], made["origin"])
            out.append(
                engine.check(
                    "plane_offset_as_requested",
                    building.parallel(source["normal"], made["normal"])
                    and math.isclose(abs(gap), abs(q["offset"]["distance"]), abs_tol=1e-6),
                    measured_offset=gap,
                    requested=q["offset"]["distance"],
                )
            )
        return out

    return building.plan(
        op="feature.datum-plane",
        command="feature datum-plane",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_DATUM_PLANE", "name": q.get("name")},
            "constraint": "offset" if "offset" in q else "through_axis_at_angle",
            "definition": spec,
            "references": refs,
        },
        expected_type="FEATTYPE_DATUM_PLANE",
        arguments={"model": opts["model"], "request": q},
        expected_change=0.0,
        exact_volume=True,
        result_keys=("geometry",),
        extra_checks=checks,
        binding=refs,
    )


def _plan_datum_axis(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q, units=False)
    refs = building.references(client, name, q["through"])

    def checks(c: Client, data: dict) -> list:
        made = data.get("geometry") or {}
        return [engine.check("axis_created", made.get("kind") == "axis" and "direction" in made)]

    return building.plan(
        op="feature.datum-axis",
        command="feature datum-axis",
        name=name,
        q=q,
        ctx=ctx,
        request=dict(q) | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_DATUM_AXIS", "name": q.get("name")},
            "through": refs,
        },
        expected_type="FEATTYPE_DATUM_AXIS",
        arguments={"model": opts["model"], "request": q},
        expected_change=0.0,
        exact_volume=True,
        result_keys=("geometry",),
        extra_checks=checks,
        binding=refs,
    )


datum_plane = _write("feature datum-plane", _prepare_with(validate_datum_plane), _plan_datum_plane)
datum_axis = _write("feature datum-axis", _prepare_with(validate_datum_axis), _plan_datum_axis)


# ------------------------------------------------------------------ round, chamfer

ROUND_MEANING = (
    "an estimate for straight convex edges between faces at right angles: (1 - pi/4) r^2 per unit "
    "of edge length removed; corners and other edges differ"
)
CHAMFER_MEANING = (
    "an estimate for straight convex edges between faces at right angles: d^2/2 per unit of edge "
    "length removed; corners and other edges differ"
)


def _edge_feature(round_: bool):
    command = "feature round" if round_ else "feature chamfer"
    schema = ROUND_SCHEMA if round_ else CHAMFER_SCHEMA

    def prepare(opts: dict) -> dict:
        return {
            "name": _part(opts),
            "request": validate_edges(read_request(opts["request"]), schema),
        }

    def plan_(client: Client, opts: dict, pre: dict) -> engine.Plan:
        name, q = pre["name"], pre["request"]
        ctx = building.context(client, name, q)
        refs = building.references(client, name, q["edges"])
        size = q["radius"] if round_ else q["distance"]
        straight = [r for r in refs.values() if r.get("type") == "line"]
        length = sum(r.get("length") or 0 for r in straight)
        per_length = (1 - math.pi / 4) * size**2 if round_ else size**2 / 2
        expected = -per_length * length if len(straight) == len(refs) else None
        kind = "FEATTYPE_ROUND" if round_ else "FEATTYPE_CHAMFER"
        return building.plan(
            op="feature.round" if round_ else "feature.chamfer",
            command=command,
            name=name,
            q=q,
            ctx=ctx,
            request={k: v for k, v in q.items() if k != "units"} | {"model": name},
            preview={
                "feature": {"type": kind, "name": q.get("name")},
                ("radius" if round_ else "distance"): size,
                "edges": refs,
                "estimated_volume_change": expected,
                "estimated_volume_change_meaning": ROUND_MEANING if round_ else CHAMFER_MEANING,
            },
            expected_type=kind,
            arguments={"model": opts["model"], "request": q},
            expected_change=expected,
            volume_meaning=ROUND_MEANING if round_ else CHAMFER_MEANING,
            result_keys=() if round_ else ("scheme",),
            binding=refs,
        )

    return _write(command, prepare, plan_)


round_edges = _edge_feature(True)
chamfer_edges = _edge_feature(False)


# ------------------------------------------------------------------ hole

HOLE_MEANING = "pi (d/2)^2 x depth when the whole depth runs through material"
SHAPED_MEANING = (
    "the drilled hole to its depth at the shoulder, its 118-degree drill point, and the "
    "counterbore or countersink, when all of it runs through material"
)
DRILL_POINT = math.radians(118 / 2)
# A radius Creo reports, against the one asked for: the service rounds geometry to 1e-9.
RADIUS_TOLERANCE = 1e-6


def _shaped_volume(drill: float, depth: float, cbore: dict | None, csink: dict | None) -> float:
    """What a drilled hole removes: its cylinder to the shoulder, the drill point, and the
    counterbore's ring or the countersink's cone beyond the cylinder."""
    r = drill / 2
    volume = math.pi * r**2 * depth + math.pi * r**2 * (r / math.tan(DRILL_POINT)) / 3
    if cbore:
        volume += math.pi * ((cbore["diameter"] / 2) ** 2 - r**2) * cbore["depth"]
    if csink:
        big = csink["diameter"] / 2
        h = (big - r) / math.tan(math.radians(csink["angle"] / 2))
        volume += math.pi * h / 3 * (big**2 + big * r + r**2) - math.pi * r**2 * h
    return volume


def _chart_shape(q: dict, chart: dict | None, key: str, first: str, second: str) -> dict | None:
    given = q.get(key)
    if not given:
        return None
    if isinstance(given, dict):
        return {first: given[first], second: given[second]}
    prefix = "cbore" if key == "counterbore" else "csink"
    a, b = (chart or {}).get(f"{prefix}_{first}"), (chart or {}).get(f"{prefix}_{second}")
    if not a or not b:
        raise Error(
            "E_VALIDATION",
            f"Creo's chart gives no {key} for this screw; give its {first} and {second}",
            {"chart": chart, "_untrusted": ["chart"]},
        )
    return {first: a, second: b}


def _off_axis(point: list, axis: dict) -> float | None:
    """How far a point lies from the line of an axis, as geometry list gives one."""
    start, direction = axis.get("start"), axis.get("direction")
    if not point or not start or not direction:
        return None
    length = math.sqrt(sum(c * c for c in direction)) or 1.0
    unit = [c / length for c in direction]
    v = [p - s for p, s in zip(point, start, strict=False)]
    along = sum(a * b for a, b in zip(v, unit, strict=False))
    return math.sqrt(max(0.0, sum(c * c for c in v) - along * along))


def _plan_hole(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    placement = q["placement"]
    how = hole_placement(placement)
    refs = building.references(
        client,
        name,
        [placement["surface"]]
        + [o["from"] for o in placement.get("offsets") or []]
        + [placement[k] for k in ("axis", "angle_from") if k in placement],
    )
    if refs[placement["surface"]].get("type") != "plane":
        raise Error(
            "E_VALIDATION",
            "a hole is placed on a planar face or datum plane",
            {"reference": placement["surface"], "_untrusted": ["reference"]},
        )
    if "axis" in placement and refs[placement["axis"]].get("kind") != "axis":
        raise Error(
            "E_VALIDATION",
            "placement.axis is an axis of the part: A_1, or axis:<id> from geometry list",
            {"reference": placement["axis"], "_untrusted": ["reference"]},
        )
    if "angle_from" in placement and refs[placement["angle_from"]].get("type") != "plane":
        raise Error(
            "E_VALIDATION",
            "a bolt circle's angle is measured from a plane through its axis",
            {"reference": placement["angle_from"], "_untrusted": ["reference"]},
        )
    through = q["depth"] == "through_all"
    screw = q.get("thread") or q.get("clearance")
    chart = None
    if screw:
        chart = engine.normalize(
            client.op(
                "hole.chart",
                {"model": name, "series": screw.get("series", "ISO"), "size": screw["size"]},
            )
        )["chart"]
        fit = None if "thread" in q else screw.get("fit", "medium")
        drill = chart.get("tap_drill") if fit is None else chart.get(f"clearance_{fit}")
        if not drill:
            raise Error(
                "E_VALIDATION",
                "Creo's chart gives no drill for this screw and fit",
                {"chart": chart, "_untrusted": ["chart"]},
            )
    else:
        drill = q["diameter"]
    cbore = _chart_shape(q, chart, "counterbore", "diameter", "depth")
    csink = _chart_shape(q, chart, "countersink", "diameter", "angle")
    for outline, what in ((cbore, "counterbore"), (csink, "countersink")):
        if outline and outline["diameter"] <= drill:
            raise Error(
                "E_VALIDATION",
                f"the {what} is no wider than the hole",
                {"drill": drill, what: outline},
            )
    shaped = bool(screw or cbore or csink)
    kind = (
        "tapped"
        if "thread" in q
        else "clearance"
        if "clearance" in q
        else "custom"
        if shaped
        else "straight"
    )
    if through:
        expected = None
    elif shaped:
        expected = -_shaped_volume(drill, q["depth"], cbore, csink)
    else:
        expected = -math.pi * (drill / 2) ** 2 * q["depth"]
    meaning = SHAPED_MEANING if shaped else HOLE_MEANING

    def checks(c: Client, data: dict) -> list:
        radii = [s.get("radius") for s in data.get("surfaces") or [] if s.get("type") == "cylinder"]
        placed = []
        if how != "linear":
            # Where the hole's own axis came out: on the axis named, or the bolt circle about it.
            own = str((data.get("feature") or {}).get("id"))
            items = engine.normalize(c.op("geometry.list", {"model": name})).get("items") or []
            axes = [
                g
                for g in items
                if g.get("kind") == "axis" and str((g.get("feature") or {}).get("id")) == own
            ]
            off = _off_axis(axes[0].get("start"), refs[placement["axis"]]) if axes else None
            want = placement["diameter"] / 2 if how == "bolt_circle" else 0.0
            placed.append(
                engine.check(
                    "on_the_bolt_circle" if how == "bolt_circle" else "on_the_axis",
                    off is not None and abs(off - want) <= 1e-6 * max(1.0, want),
                    distance_from_axis=off,
                    wanted=want,
                )
            )

        def has(radius: float) -> bool:
            return any(
                isinstance(x, int | float) and abs(x - radius) <= RADIUS_TOLERANCE for x in radii
            )

        out = [
            engine.check(
                "drilled_to_the_diameter", has(drill / 2), drill=drill, radii=sorted(set(radii))
            )
        ]
        if cbore:
            out.append(
                engine.check(
                    "counterbore_as_requested", has(cbore["diameter"] / 2), counterbore=cbore
                )
            )
        if "thread" in q:
            major = (chart or {}).get("basic_diameter")
            out.append(
                engine.check(
                    "thread_on_the_hole", major is not None and has(major / 2), major_diameter=major
                )
            )
        return out + placed

    return building.plan(
        op="feature.hole",
        command="feature hole",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_HOLE", "name": q.get("name")},
            "kind": kind,
            "diameter": drill,
            "depth": q["depth"],
            "thread": q.get("thread"),
            "clearance": q.get("clearance"),
            "counterbore": cbore,
            "countersink": csink,
            "chart": chart,
            "placement": {"how": how, "on": refs[placement["surface"]]}
            | {k: placement[k] for k in ("offsets", "diameter", "angle") if k in placement}
            | {k: refs[placement[k]] for k in ("axis", "angle_from") if k in placement},
            "references": refs,
            "expected_volume_change": expected,
            "expected_volume_change_meaning": meaning
            if expected is not None
            else "not estimated for a hole through all",
        },
        expected_type="FEATTYPE_HOLE",
        arguments={"model": opts["model"], "request": q},
        expected_change=expected,
        volume_meaning=meaning,
        result_keys=("drill_diameter", "depth", "placement", "counterbore", "countersink", "chart"),
        extra_checks=checks,
        binding={"references": refs, "chart": chart},
    )


hole = _write("feature hole", _prepare_with(validate_hole), _plan_hole)


# ------------------------------------------------------------------ thread

MINOR_OFFSET = 1.082532  # ISO 68-1: the basic minor diameter lies this many pitches inside


def _plan_thread(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    refs = building.references(client, name, [q["surface"], q["start"]])
    on, start = refs[q["surface"]], refs[q["start"]]
    if on.get("kind") != "surface" or on.get("type") != "cylinder":
        raise Error(
            "E_VALIDATION",
            "a thread goes on a cylindrical face of the part: a shaft or a bore",
            {"reference": q["surface"], "is": on.get("type"), "_untrusted": ["reference"]},
        )
    if start.get("type") != "plane":
        raise Error(
            "E_VALIDATION",
            "a thread starts from a planar face: the shaft's end, the bore's mouth",
            {"reference": q["start"], "is": start.get("type"), "_untrusted": ["reference"]},
        )
    external = on.get("outward") != "toward_axis"
    across = 2 * (on.get("radius") or 0)
    chart = None
    if "size" in q:
        chart = engine.normalize(
            client.op(
                "hole.chart", {"model": name, "series": q.get("series", "ISO"), "size": q["size"]}
            )
        )["chart"]
        major, column = chart.get("basic_diameter"), chart.get("pitch")
        if not major or not column:
            raise Error(
                "E_VALIDATION",
                "Creo's chart gives no diameter and pitch for this size",
                {"chart": chart, "_untrusted": ["chart"]},
            )
        pitch = (
            column
            if q["size"].upper().startswith("M")
            else (
                1 / column
                if ctx.before["units"]["length"].lower().startswith("in")
                else 25.4 / column
            )
        )
        diameter = major - MINOR_OFFSET * pitch if external else major
        if external and abs(across - major) > 0.02 * major:
            raise Error(
                "E_VALIDATION",
                "the thread's size does not fit the shaft",
                {"shaft": across, "thread_major": major},
            )
        if not external and not across < major:
            raise Error(
                "E_VALIDATION",
                "an internal thread goes in a bore smaller than its major diameter: its tap drill",
                {"bore": across, "thread_major": major},
            )
    else:
        diameter = q["diameter"]
        if external and not diameter < across:
            raise Error(
                "E_VALIDATION",
                "a shaft's thread is given by its minor diameter, smaller than the shaft",
                {"shaft": across, "diameter": diameter},
            )
        if not external and not diameter > across:
            raise Error(
                "E_VALIDATION",
                "a bore's thread is given by its major diameter, larger than the bore",
                {"bore": across, "diameter": diameter},
            )

    def checks(c: Client, data: dict) -> list:
        dims = engine.normalize(
            c.op("dimension.list", {"model": name, "feature": str(data["feature"]["id"])})
        )["dimensions"]
        across_read = next((d["value"] for d in dims if d.get("type") == "diameter"), None)
        along_read = next((d["value"] for d in dims if d.get("type") == "linear"), None)
        radii = [s.get("radius") for s in data.get("surfaces") or [] if s.get("type") == "cylinder"]
        change = (data.get("volume") or {}).get("change")
        return [
            engine.check(
                "thread_diameter_as_requested",
                across_read is not None and abs(across_read - diameter) <= RADIUS_TOLERANCE,
                diameter=across_read,
                expected=diameter,
            ),
            engine.check(
                "thread_depth_as_requested",
                along_read is not None and abs(along_read - q["depth"]) <= RADIUS_TOLERANCE,
                depth=along_read,
            ),
            engine.check(
                "thread_surface_at_the_diameter",
                any(
                    isinstance(r, int | float) and abs(r - diameter / 2) <= RADIUS_TOLERANCE
                    for r in radii
                ),
            ),
            engine.check(
                "nothing_removed", change is not None and abs(change) <= 1e-9, change=change
            ),
        ]

    return building.plan(
        op="feature.thread",
        command="feature thread",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_THREAD", "name": q.get("name")},
            "on": on,
            "start": start,
            "external": external,
            "diameter": diameter,
            "diameter_meaning": "the thread's minor diameter on a shaft, its major one in a bore",
            "depth": q["depth"],
            "chart": chart,
        },
        expected_type="FEATTYPE_THREAD",
        arguments={"model": opts["model"], "request": q},
        result_keys=("external", "diameter", "depth", "chart", "parameters", "callout"),
        extra_checks=checks,
        binding={"references": refs, "chart": chart},
    )


thread = _write("feature thread", _prepare_with(validate_thread), _plan_thread)


# ------------------------------------------------------------------ shell


def _plan_shell(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    refs = building.references(client, name, q.get("remove", []))
    for ref, item in refs.items():
        if item.get("kind") != "surface":
            raise Error(
                "E_VALIDATION",
                "a shell removes faces of the part",
                {"reference": ref, "is": item.get("kind"), "_untrusted": ["reference"]},
            )

    inside = q.get("side", "inside") == "inside"

    def checks(c: Client, data: dict) -> list:
        change = (data.get("volume") or {}).get("change")
        if not inside:
            return []  # a wall grown outwards can add more than the hollow takes
        return [engine.check("material_removed", change is not None and change < 0, change=change)]

    def observed(data: dict) -> list:
        return [{"observation": "volume", "change": (data.get("volume") or {}).get("change")}]

    return building.plan(
        op="feature.shell",
        command="feature shell",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_SHELL", "name": q.get("name")},
            "thickness": q["thickness"],
            "side": q.get("side", "inside"),
            "removed_faces": refs,
        },
        expected_type="FEATTYPE_SHELL",
        arguments={"model": opts["model"], "request": q},
        extra_checks=checks,
        extra_observations=None if inside else observed,
        binding=refs,
    )


shell = _write("feature shell", _prepare_with(validate_shell), _plan_shell)


# ------------------------------------------------------------------ draft

DRAFT_MEANING = (
    "measured from the pull direction; positive turns every face so that the part grows wider "
    "along the pull direction -- the face's outward normal leans against the pull by the angle "
    "-- and negative so that it grows narrower"
)
# A face read back from Creo, against the angle asked for: normals come rounded to 1e-9.
DRAFT_TOLERANCE_DEGREES = 1e-5


def _unit(v: list) -> list:
    length = math.sqrt(sum(c * c for c in v))
    return [c / length for c in v]


def _lean(normal: list, pull: list) -> float:
    """How far a face's outward normal leans toward the pull direction, in degrees."""
    dot = sum(a * b for a, b in zip(_unit(normal), pull, strict=True))
    return math.degrees(math.asin(max(-1.0, min(1.0, dot))))


def _plan_draft(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q, units="units" in q)  # an angle has none
    pull_ref = q.get("pull", q["hinge"])
    refs = building.references(
        client, name, [*q["surfaces"], q["hinge"], *[q[k] for k in ("pull",) if k in q]]
    )
    for ref in q["surfaces"]:
        if refs[ref].get("kind") != "surface":
            raise Error(
                "E_VALIDATION",
                "the faces drafted are faces of the part",
                {"reference": ref, "is": refs[ref].get("kind"), "_untrusted": ["reference"]},
            )
    for role, ref in (("hinge", q["hinge"]), ("pull", pull_ref)):
        if refs[ref].get("type") != "plane" or not refs[ref].get("normal"):
            raise Error(
                "E_VALIDATION",
                f"the {role} is a datum plane or a planar face",
                {"reference": ref, "is": refs[ref].get("type"), "_untrusted": ["reference"]},
            )
    pull = _unit(refs[pull_ref]["normal"])
    if q.get("flip_pull"):
        pull = [-c for c in pull]
    angle = q["angle"]

    def leaning(data: dict) -> list:
        return [
            {"ref": f.get("ref"), "leans_toward_pull": _lean(f["normal"], pull)}
            for f in data.get("drafted") or []
            if f.get("type") == "plane" and f.get("normal")
        ]

    def checks(c: Client, data: dict) -> list:
        drafted = data.get("drafted") or []
        out = [
            engine.check(
                "every_face_drafted",
                len(drafted) >= len(q["surfaces"]),
                drafted=len(drafted),
                requested=len(q["surfaces"]),
            )
        ]
        planar = leaning(data)
        if planar:
            out.append(
                engine.check(
                    "faces_at_the_draft_angle",
                    all(
                        abs(f["leans_toward_pull"] + angle) <= DRAFT_TOLERANCE_DEGREES
                        for f in planar
                    ),
                    expected_lean_toward_pull=-angle,
                    faces=planar,
                )
            )
        return out

    def observed(data: dict) -> list:
        out = [{"observation": "volume", "change": (data.get("volume") or {}).get("change")}]
        curved = [f.get("ref") for f in data.get("drafted") or [] if f.get("type") != "plane"]
        if curved:
            out.append({"observation": "curved_faces_drafted", "faces": curved})
        return out

    return building.plan(
        op="feature.draft",
        command="feature draft",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_DRAFT", "name": q.get("name")},
            "angle": angle,
            "angle_meaning": DRAFT_MEANING,
            "hinge": refs[q["hinge"]],
            "pull": {"reference": pull_ref, "flipped": bool(q.get("flip_pull")), "direction": pull},
            "surfaces": {
                ref: refs[ref]
                | (
                    {"leans_toward_pull": _lean(refs[ref]["normal"], pull)}
                    if refs[ref].get("normal")
                    else {}
                )
                for ref in q["surfaces"]
            },
        },
        expected_type="FEATTYPE_DRAFT",
        arguments={"model": opts["model"], "request": q},
        result_keys=("drafted",),
        extra_checks=checks,
        extra_observations=observed,
        binding=refs,
    )


draft = _write("feature draft", _prepare_with(validate_draft), _plan_draft)


# ------------------------------------------------------------------ pattern


def _plan_pattern(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q)
    leader = building.feature_by_ref(ctx.features, q["feature"])
    spec = q.get("direction") or q["axis"]
    second = q.get("direction2")
    refs = building.references(
        client, name, [spec.get("along") or spec["about"], *([second["along"]] if second else [])]
    )
    instances = spec["count"] * (second["count"] if second else 1)

    def checks(c: Client, data: dict) -> list:
        members = data.get("members") or []
        return [
            engine.check("instances_as_requested", len(members) == instances, found=len(members))
        ]

    return building.plan(
        op="feature.pattern",
        command="feature pattern",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if k != "units"}
        | {"model": name, "feature": leader["id"]},
        preview={
            "feature": {"type": "FEATTYPE_PATTERN_HEAD", "name": q.get("name")},
            "patterned": {k: leader.get(k) for k in ("id", "name", "type")},
            "kind": "grid" if second else "direction" if "direction" in q else "axis",
            "definition": spec | ({"second": second} if second else {}),
            "references": refs,
            "instances": instances,
        },
        expected_type="FEATTYPE_PATTERN_HEAD",
        arguments={"model": opts["model"], "request": q},
        result_keys=("members",),
        extra_checks=checks,
        binding={"refs": refs, "leader": leader},
    )


pattern = _write("feature pattern", _prepare_with(validate_pattern), _plan_pattern)


# ------------------------------------------------------------------ mirror

MIRROR_MEANING = "doubles the volume when the mirror image does not overlap the original"


def _prepare_mirror(opts: dict) -> dict:
    validate(opts["plane"], REFERENCE, "plane")
    if opts.get("name") is not None:
        validate(opts["name"], FEATURE_NAME, "name")
    return {"name": _part(opts), "request": {"plane": opts["plane"], "name": opts.get("name")}}


def _plan_mirror(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    ctx = building.context(client, name, q, units=False)
    refs = building.references(client, name, [q["plane"]])
    if refs[q["plane"]].get("type") != "plane":
        raise Error(
            "E_VALIDATION",
            "a part is mirrored about a datum plane or planar face",
            {"reference": q["plane"], "_untrusted": ["reference"]},
        )
    volume = (ctx.before.get("mass_properties") or {}).get("volume")
    return building.plan(
        op="feature.mirror",
        command="feature mirror",
        name=name,
        q=q,
        ctx=ctx,
        request={k: v for k, v in q.items() if v is not None} | {"model": name},
        preview={
            "feature": {"type": "FEATTYPE_GENERAL_MERGE", "name": q.get("name")},
            "mirrors": "the whole part, merged with its mirror image",
            "plane": refs[q["plane"]],
        },
        expected_type="FEATTYPE_GENERAL_MERGE",
        arguments={"model": opts["model"], "plane": opts["plane"], "name": opts.get("name")},
        expected_change=volume,
        volume_meaning=MIRROR_MEANING,
        binding=refs,
    )


mirror = _write("feature mirror", _prepare_mirror, _plan_mirror)


# ------------------------------------------------------------------ declarations

VOLUME = shape(
    {"before": NN, "after": NN, "change": NN, "expected_change": N, "matches_request": B},
    ("before", "after", "change"),
)


def built(**extra) -> dict:
    return written(
        shape(
            {"model": S, "units": UNITS, "feature": FEATURE, "volume": VOLUME, **extra},
            ("model", "units", "feature", "volume"),
        )
    )


def _creates(command, description, handler, schema, example, ops, **extra) -> Command:
    return Command(
        command,
        description,
        handler,
        built(**extra),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=schema,
        request_example=example,
        example=f"--model block --request {command.split()[1]}.json",
        service_ops=ops,
    )


GEOMETRY = {"type": ["object", "null"]}
SKETCH_DIMENSIONS = array(
    shape(
        {"name": S, "value": N, "measures": S, "by": {"type": "string", "enum": ["cli", "creo"]}},
        ("name", "value", "measures", "by"),
    )
)
HELD_TOGETHER = array(shape({"held": S, "between": array(S)}, ("held", "between")))
SKETCHED = {
    "sketch_dimensions": SKETCH_DIMENSIONS,
    "held_together": HELD_TOGETHER,
    "dimension_plan": S,
}
SWEPT_PATH = shape(
    {
        "id": S,
        "name": NS,
        "type": S,
        "starts_at": {"type": ["array", "null"], "items": N},
        "ends_at": {"type": ["array", "null"], "items": N},
        "creo_runs_from": {"type": ["string", "null"], "enum": ["start", "end", None]},
        "dimensions": {"type": ["array", "null"]},
        "held_together": {"type": ["array", "null"]},
        "dimension_plan": {"type": ["string", "null"]},
    },
    ("id", "type", "starts_at", "ends_at", "creo_runs_from"),
)
ANY_VECTOR = {"type": ["array", "null"], "items": N}
BOUNDED_REVOLVE_SCHEMA = deepcopy(REVOLVE_SCHEMA)
BOUNDED_REVOLVE_SCHEMA["properties"]["angle"]["enum"] = [360]
BOUNDED_REVOLVE_SCHEMA["properties"]["material"]["enum"] = ["add"]
BOUNDED_REVOLVE_SCHEMA["properties"]["body"]["enum"] = ["default"]
BOUNDED_REVOLVE_SCHEMA["properties"]["side"]["enum"] = ["one"]
_profile_schema = BOUNDED_REVOLVE_SCHEMA["properties"]["sketch"]["properties"]["profile"]
_profile_schema["oneOf"] = [
    p
    for p in _profile_schema["oneOf"]
    if p["properties"]["type"]["enum"][0] in ("rectangle", "polygon")
]
for _profile in _profile_schema["oneOf"]:
    _profile["properties"].pop("holes", None)
    if "points" in _profile["properties"]:
        _profile["properties"]["points"]["maxItems"] = 16
BOUNDED_DATUM_PLANE_SCHEMA = deepcopy(DATUM_PLANE_SCHEMA)
BOUNDED_DATUM_PLANE_SCHEMA["properties"].pop("angle")
BOUNDED_DATUM_PLANE_SCHEMA["required"] = ["units", "offset"]
CONSTRUCTION_RESULT = {
    "construction_intent": shape({}),
    "native_definition": shape({}),
    "independent_geometry": array(shape({})),
}
COMMANDS = [
    _creates(
        "feature extrude",
        "Sketch one closed profile on a datum plane and extrude it, adding or removing material",
        extrude,
        EXTRUDE_SCHEMA,
        EXTRUDE_EXAMPLE,
        ("feature.extrude",),
        **SKETCHED,
    ),
    _creates(
        "feature revolve",
        "Revolve one orthogonal closed profile through 360 degrees as the first solid; "
        "explicit in-plane, model-axis-aligned rotation axis and independent boundary proof",
        revolve,
        BOUNDED_REVOLVE_SCHEMA,
        REVOLVE_EXAMPLE,
        ("geometry.list", "feature.show", "dimension.list", "feature.revolve"),
        **SKETCHED,
        **CONSTRUCTION_RESULT,
    ),
    _creates(
        "feature datum-plane",
        "A signed offset datum plane from a plane or planar face; verify native constraint, "
        "position and normal independently",
        datum_plane,
        BOUNDED_DATUM_PLANE_SCHEMA,
        DATUM_PLANE_EXAMPLE,
        ("geometry.list", "feature.show", "dimension.list", "feature.datum-plane"),
        geometry=GEOMETRY,
        **CONSTRUCTION_RESULT,
    ),
    _creates(
        "feature datum-axis",
        "A datum axis through two nonparallel planes, one straight edge or one cylinder; "
        "verify full spatial line and native reference relationships",
        datum_axis,
        DATUM_AXIS_SCHEMA,
        DATUM_AXIS_EXAMPLE,
        ("geometry.list", "feature.show", "dimension.list", "feature.datum-axis"),
        geometry=GEOMETRY,
        **CONSTRUCTION_RESULT,
    ),
    _creates(
        "feature round",
        "Round edges to a constant radius; edges are edge:<id> from geometry list",
        round_edges,
        ROUND_SCHEMA,
        ROUND_EXAMPLE,
        ("geometry.list", "feature.show", "dimension.list", "feature.round"),
        native_definition=shape({}),
        current_feature_geometry=array(shape({})),
    ),
    _creates(
        "feature chamfer",
        "Chamfer edges by an equal distance on both faces, called out 1 X 45 on a drawing where "
        "the faces meet square; edges are edge:<id> from geometry list",
        chamfer_edges,
        CHAMFER_SCHEMA,
        CHAMFER_EXAMPLE,
        ("geometry.list", "feature.chamfer"),
        scheme={"type": ["string", "null"], "enum": ["45_x_d", "d_x_d", None]},
    ),
    _creates(
        "feature hole",
        "A hole on a planar face -- placed by distances from two references, on a bolt circle "
        "about an axis, or on an axis -- blind or through all: straight, tapped for a screw or "
        "clear of one (Creo's hole charts: ISO, UNC, ...), counterbored or countersunk",
        hole,
        HOLE_SCHEMA,
        HOLE_EXAMPLE,
        ("geometry.list", "feature.show", "dimension.list", "hole.chart", "feature.hole"),
        native_definition=shape({}),
        current_feature_geometry=array(shape({})),
        drill_diameter=NN,
        depth={"type": ["number", "string", "null"]},
        placement={"type": ["string", "null"], "enum": ["linear", "bolt_circle", "coaxial", None]},
        counterbore={"type": ["object", "null"]},
        countersink={"type": ["object", "null"]},
        chart={"type": ["object", "null"]},
    ),
    _creates(
        "feature thread",
        "A cosmetic thread on a shaft or in a bore, from a face to a depth: a size from Creo's "
        "chart (M10x1.5) or a diameter; it removes nothing and shows on drawings",
        thread,
        THREAD_SCHEMA,
        THREAD_EXAMPLE,
        ("geometry.list", "hole.chart", "dimension.list", "feature.thread"),
        external=B,
        diameter=NN,
        depth=NN,
        chart={"type": ["object", "null"]},
        parameters={"type": ["object", "null"]},
        callout={"type": ["string", "null"]},
    ),
    _creates(
        "feature shell",
        "Uniform inward shell of one mm rectangular prism, removing its explicit top face; "
        "complete native boundary and definition readback",
        shell,
        SHELL_SCHEMA,
        SHELL_EXAMPLE,
        ("geometry.list", "model.management-state", "feature.show", "feature.shell"),
        shell_readback=shape({}),
    ),
    _creates(
        "feature draft",
        "Tilt faces by an angle about a hinge plane, as a molded or cast part needs to come out "
        "of its mold; the angle is measured from the pull direction",
        draft,
        DRAFT_SCHEMA,
        DRAFT_EXAMPLE,
        ("geometry.list", "feature.draft"),
        drafted=array(
            shape({"ref": S, "kind": S, "type": NS, "normal": ANY_VECTOR, "area": NN}, ("ref",))
        ),
    ),
    _creates(
        "feature rib",
        "One straight transverse rib in a proven rectangular mm housing; freeze actual "
        "wall endpoints and floor fill, then verify its complete native body and section",
        rib,
        RIB_SCHEMA,
        RIB_EXAMPLE,
        ("geometry.list", "model.management-state", "feature.show", "feature.rib"),
        rib_readback=shape({}),
        fill={"type": "string", "enum": ["right", "left"]},
        fill_tried=array(S),
        **SKETCHED,
    ),
    _creates(
        "feature sweep",
        "Sweep a closed section along a path of lines and arcs sketched on a datum plane or "
        "flat face -- a pipe, a handle, a groove -- adding or removing material",
        sweep,
        SWEEP_SCHEMA,
        SWEEP_EXAMPLE,
        ("geometry.list", "feature.sweep"),
        path=SWEPT_PATH,
        sketch={"type": ["object", "null"]},
    ),
    _creates(
        "feature pattern",
        "Repeat a feature along a direction at a spacing, or about an axis at an angle",
        pattern,
        PATTERN_SCHEMA,
        PATTERN_EXAMPLE,
        ("geometry.list", "feature.pattern"),
        members=array(shape({"id": S, "name": {"type": ["string", "null"]}})),
    ),
    Command(
        "feature mirror",
        "Mirror the whole part about a datum plane or planar face and merge the image with it",
        mirror,
        built(),
        (
            MODEL,
            Param("plane", required=True, description="datum plane name or surface:<id>"),
            Param("name", description="the new feature's name"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --plane RIGHT",
        service_ops=("geometry.list", "feature.mirror"),
    ),
]
