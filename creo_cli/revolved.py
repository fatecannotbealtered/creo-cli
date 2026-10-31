"""Bounded analytic revolve and datum proofs, shared by confirmation and recovery.

This module supplies domain predicates to the existing engine/driver. It never dispatches
a write. Infinite reference display extents are not physical geometry.
"""

import copy
import math

from . import building, engine, machining, native_diagnostic_recovery, native_read_recovery
from .core import Error, digest
from .presentation import equivalent

COMMANDS = ("feature revolve", "feature datum-plane", "feature datum-axis")
TOL = 1e-6
TYPES = {
    "feature.revolve": "FEATTYPE_PROTRUSION",
    "feature.datum-plane": "FEATTYPE_DATUM_PLANE",
    "feature.datum-axis": "FEATTYPE_DATUM_AXIS",
}


def close(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b, strict=True))
    return (
        type(a) in (int, float)
        and type(b) in (int, float)
        and math.isfinite(a)
        and math.isfinite(b)
        and math.isclose(a, b, rel_tol=1e-6, abs_tol=TOL)
    )


def unit(vector):
    if not machining._point(vector):
        raise Error("E_VERIFY_INCOMPLETE", "a reference has no readable three-dimensional vector")
    size = math.sqrt(machining.dot(vector, vector))
    if size <= TOL:
        raise Error("E_VERIFY_INCOMPLETE", "a reference has a zero direction")
    return [v / size for v in vector]


def line(point, direction):
    d = unit(direction)
    if not machining._point(point):
        raise Error("E_VERIFY_INCOMPLETE", "a reference has no readable point on its axis")
    # An unoriented geometric axis: opposite endpoint order represents the same line.
    if next(v for v in d if abs(v) > TOL) < 0:
        d = [-v for v in d]
    t = machining.dot(point, d)
    return {"origin": [p - t * v for p, v in zip(point, d, strict=True)], "direction": d}


def reference_line(item):
    if item.get("axis"):
        return line(item["axis"].get("origin"), item["axis"].get("direction"))
    return line(item.get("start"), item.get("direction"))


def same_line(a, b):
    try:
        x, y = line(a["origin"], a["direction"]), line(b["origin"], b["direction"])
        return close(x["origin"], y["origin"]) and close(x["direction"], y["direction"])
    except (Error, KeyError, TypeError):
        return False


def canonical_request(client, model, request):
    q = copy.deepcopy(request)
    slots = []
    if "sketch" in q:
        for k in ("plane", "orient_ref"):
            slots.append((q["sketch"], k))
        slots += [
            (q["sketch"]["references"], i) for i in range(len(q["sketch"].get("references", [])))
        ]
        if isinstance(q["axis"], str):
            slots.append((q, "axis"))
    elif "through" in q:
        slots += [(q["through"], i) for i in range(len(q["through"]))]
    else:
        spec = q.get("offset") or q["angle"]
        slots += [(spec, k) for k in ("from", "through") if k in spec]
    resolved = building.resolve_references(
        machining.geometry(client, model)["items"], [container[key] for container, key in slots]
    )
    for container, key in slots:
        container[key] = resolved[container[key]]["ref"]
    return q


def snapshot(client, model):
    from . import protected_readback

    state = machining.snapshot(client, model)
    protected_readback.require_units(state["model"])
    if len(state["features"]) > 128:
        raise Error(
            "E_UNSUPPORTED", "bounded datum/revolve inspection supports at most 128 features"
        )
    details = {}
    for f in state["features"]:
        if f["type"] not in TYPES.values():
            continue
        detail = engine.normalize(client.op("feature.show", {"model": model, "feature": f["id"]}))
        if detail.get("id") != f["id"] or not isinstance(detail.get("parents"), list):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "feature relation readback is incomplete",
                {"feature": f["id"]},
            )
        definition = detail.get("native_definition")
        native_tree = detail.get("native_tree_observation")
        if f["type"] == "FEATTYPE_PROTRUSION" and definition is None:
            if detail.get(
                "native_definition_status"
            ) != "unsupported" or not protected_readback.tree_complete(native_tree):
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "existing protrusion requires a successful complete native tree observation",
                    {"feature": f["id"], "observation": native_tree},
                )
        if f["type"] in ("FEATTYPE_DATUM_PLANE", "FEATTYPE_DATUM_AXIS") and definition is None:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "existing datum native definition is unavailable",
                {
                    "feature": f["id"],
                    "native_definition_status": "null"
                    if "native_definition" in detail
                    else "missing",
                },
            )
        if definition is not None and (
            not isinstance(definition, dict)
            or definition.get("complete") is not True
            or definition.get("error") is not None
        ):
            # Two matching nested errors are not evidence that an unrelated
            # construction stayed unchanged. Preserve the actual observation.
            nested = definition.get("error") if isinstance(definition, dict) else None
            pending = native_read_recovery.pending_error(nested)
            diagnostic = native_diagnostic_recovery.diagnostic_error(nested)
            if pending or diagnostic:
                original = pending or diagnostic
                code = "E_NATIVE_READ_PENDING" if pending else "E_NATIVE_DIAGNOSTIC"
                key = "native_read_error" if pending else "native_diagnostic_error"
                raise Error(
                    code,
                    original.get("message") or "nested native read requires an immediate stop",
                    {
                        key: copy.deepcopy(original),
                        "feature": f["id"],
                        "native_definition": copy.deepcopy(definition),
                    },
                )
            if isinstance(nested, dict) and nested.get("code") in (
                "E_NATIVE_READ_PENDING",
                "E_NATIVE_DIAGNOSTIC",
            ):
                code = nested["code"]
                raise Error(
                    code,
                    nested.get("message") or "nested native read requires an immediate stop",
                    {"feature": f["id"], "native_definition": copy.deepcopy(definition)},
                )
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "existing construction native definition is incomplete",
                {"feature": f["id"], "native_definition": copy.deepcopy(definition)},
            )
        details[f["id"]] = {
            k: detail.get(k)
            for k in (
                "parents",
                "dimensions",
                "native_definition",
                "native_definition_status",
                "native_tree_observation",
                "sections",
                "native_section_readback",
            )
        }
    state["construction_details"] = details
    for g in state["geometry"]["items"]:
        if g.get("kind") == "axis":
            g["line"] = reference_line(g)
            g.pop("start", None)
            g.pop("end", None)
    return state


def datum_intent(op, q, state):
    refs = {g["ref"]: g for g in state["geometry"]["items"]}
    if op == "feature.datum-plane":
        if "offset" not in q:
            raise Error(
                "E_UNSUPPORTED",
                "bounded datum-plane proof supports a signed plane offset only",
                {"fix": "use offset.from and offset.distance; angular datums are not verified"},
            )
        source = refs[q["offset"]["from"]]
        if source.get("type") != "plane" or not machining._point(source.get("origin")):
            raise Error("E_UNSUPPORTED", "offset requires a readable datum plane or planar face")
        n = unit(source.get("normal"))
        return {
            "kind": "datum_plane",
            "normal": n,
            "origin": [
                p + q["offset"]["distance"] * v for p, v in zip(source["origin"], n, strict=True)
            ],
            "constraints": [
                {"kind": "offset", "reference": source["ref"], "distance": q["offset"]["distance"]}
            ],
            "meaning": "infinite geometric plane; signed offset in model length units; "
            "no manufacturing datum claim",
        }
    selected = [refs[r] for r in q["through"]]
    if len(selected) == 2 and all(g.get("type") == "plane" for g in selected):
        a, b = selected
        n, m = unit(a.get("normal")), unit(b.get("normal"))
        d = machining.cross(n, m)
        denom = machining.dot(d, d)
        if denom <= TOL:
            raise Error("E_VALIDATION", "two parallel planes do not define one datum axis")
        u, v = machining.dot(n, a["origin"]), machining.dot(m, b["origin"])
        point = [
            (u * x + v * y) / denom
            for x, y in zip(machining.cross(m, d), machining.cross(d, n), strict=True)
        ]
        axis = line(point, d)
    elif len(selected) == 1 and (
        (selected[0].get("kind") == "edge" and selected[0].get("type") == "line")
        or selected[0].get("type") == "cylinder"
    ):
        axis = reference_line(selected[0])
    else:
        raise Error(
            "E_UNSUPPORTED",
            "bounded datum axis requires two nonparallel planes, one straight edge or one cylinder",
            {"fix": "read geometry list and select explicit supported references"},
        )
    return {
        "kind": "datum_axis",
        "line": axis,
        "constraints": [{"kind": "through", "reference": r} for r in q["through"]],
        "meaning": "infinite unoriented line; display endpoints are not physical boundaries",
    }


def _world(frame, point):
    return [
        frame["origin"][i] + point[0] * frame["x"][i] + point[1] * frame["y"][i] for i in range(3)
    ]


def profile_points(profile):
    if profile.get("holes"):
        raise Error(
            "E_UNSUPPORTED", "bounded revolve proof supports one closed loop without profile holes"
        )
    if profile["type"] == "polygon":
        return profile["points"]
    if profile["type"] == "rectangle":
        x, y = profile.get("center", [0, 0])
        w, h = profile["width"] / 2, profile["height"] / 2
        return [[x - w, y - h], [x + w, y - h], [x + w, y + h], [x - w, y + h]]
    raise Error(
        "E_UNSUPPORTED",
        "bounded revolve proof requires a straight orthogonal closed polygon or rectangle",
    )


def revolve_intent(q, state, sketch):
    if (
        q["angle"] != 360
        or q.get("material", "add") != "add"
        or q.get("body", "default") != "default"
        or q.get("side", "one") != "one"
    ):
        raise Error(
            "E_UNSUPPORTED",
            "bounded revolve proof supports a full 360 degree added first solid only",
            {"fix": "use angle 360, side one, material add and the default body in an empty part"},
        )
    if any(g.get("kind") == "surface" for g in state["geometry"]["items"]):
        raise Error(
            "E_UNSUPPORTED", "bounded revolve proof requires an empty part with datums only"
        )
    frame = sketch.get("frame")
    if not frame or not machining._point(frame.get("origin")):
        raise Error(
            "E_VERIFY_INCOMPLETE", "sketch placement frame could not be independently determined"
        )
    for k in ("x", "y", "normal"):
        if not close(unit(frame.get(k)), frame[k]):
            raise Error("E_UNSUPPORTED", "bounded revolve requires an orthonormal sketch frame")
    if not close(machining.dot(frame["x"], frame["normal"]), 0) or not close(
        machining.cross(frame["x"], frame["y"]), frame["normal"]
    ):
        raise Error(
            "E_UNSUPPORTED",
            "sketch orientation reference must be perpendicular to the sketch plane",
        )
    points = profile_points(q["sketch"]["profile"])
    if len(points) > 16:
        raise Error(
            "E_UNSUPPORTED", "bounded orthogonal revolve proof supports at most 16 profile vertices"
        )
    if isinstance(q["axis"], str):
        refs = {g["ref"]: g for g in state["geometry"]["items"]}
        ref = refs[q["axis"]]
        axis = ref.get("line") or reference_line(ref)
    else:
        p, end = [_world(frame, xy) for xy in q["axis"]]
        axis = line(p, [b - a for a, b in zip(p, end, strict=True)])
    if not close(machining.dot(axis["direction"], frame["normal"]), 0) or not close(
        machining.dot(
            [a - b for a, b in zip(axis["origin"], frame["origin"], strict=True)], frame["normal"]
        ),
        0,
    ):
        raise Error("E_VALIDATION", "the revolve axis must lie in the actual sketch plane")
    axial = next((i for i, v in enumerate(axis["direction"]) if close(abs(v), 1)), None)
    if axial is None or not any(
        close(abs(machining.dot(axis["direction"], frame[k])), 1) for k in ("x", "y")
    ):
        raise Error(
            "E_UNSUPPORTED",
            "bounded revolve proof requires a model-axis-aligned axis "
            "parallel to a sketch coordinate",
        )
    radial = unit(machining.cross(axis["direction"], frame["normal"]))
    world = [_world(frame, p) for p in points]
    rt = [
        [machining.dot([p[i] - axis["origin"][i] for i in range(3)], radial), p[axial]]
        for p in world
    ]
    if all(p[0] <= TOL for p in rt):
        rt = [[-p[0], p[1]] for p in rt]
    if any(p[0] < -TOL for p in rt):
        raise Error("E_VALIDATION", "the actual profile crosses its rotation axis")
    faces = []
    for a, b in zip(rt, rt[1:] + rt[:1], strict=True):
        if close(a[0], b[0]) and not close(a[1], b[1]):
            if a[0] > TOL:
                lo, hi = sorted((a[1], b[1]))
                faces.append(
                    {
                        "type": "cylinder",
                        "radius": a[0],
                        "axial": [lo, hi],
                        "area": 2 * math.pi * a[0] * (hi - lo),
                    }
                )
        elif close(a[1], b[1]) and not close(a[0], b[0]):
            lo, hi = sorted((a[0], b[0]))
            faces.append(
                {
                    "type": "plane",
                    "at": a[1],
                    "radial": [lo, hi],
                    "area": math.pi * (hi * hi - lo * lo),
                }
            )
        else:
            raise Error(
                "E_UNSUPPORTED",
                "bounded revolve proof requires nonzero edges parallel "
                "or perpendicular to its axis",
            )
    volume = 0.0
    stations = sorted({p[1] for p in rt})
    bands = []
    for lo, hi in zip(stations, stations[1:], strict=False):
        mid = (lo + hi) / 2
        radii = sorted(
            a[0]
            for a, b in zip(rt, rt[1:] + rt[:1], strict=True)
            if close(a[0], b[0]) and min(a[1], b[1]) < mid < max(a[1], b[1])
        )
        if len(radii) != 2:
            raise Error(
                "E_UNSUPPORTED",
                "profile must define one connected radial interval at each axial station",
            )
        volume += math.pi * (radii[1] ** 2 - radii[0] ** 2) * (hi - lo)
        bands.append({"axial": [lo, hi], "radii": radii})
    radius = max(p[0] for p in rt)
    box = [
        [axis["origin"][i] - radius for i in range(3)],
        [axis["origin"][i] + radius for i in range(3)],
    ]
    box[0][axial], box[1][axial] = stations[0], stations[-1]
    return {
        "kind": "revolve",
        "frame": frame,
        "axis": axis,
        "axial_index": axial,
        "angle_deg": 360,
        "world_profile": world,
        "faces": faces,
        "bands": bands,
        "volume": volume,
        "box": box,
        "meaning": "model coordinates and model units; analytic full solid; "
        "numeric checks are not manufacturing tolerances",
    }


def _surface_box(intent, face):
    k = intent["axial_index"]
    r = face.get("radius", face.get("radial", [0, 0])[-1])
    box = [[v - r for v in intent["axis"]["origin"]], [v + r for v in intent["axis"]["origin"]]]
    box[0][k], box[1][k] = face.get("axial", [face.get("at"), face.get("at")])
    return box


def _surface_matches(g, expected, intent):
    if g.get("type") != expected["type"]:
        return False
    if expected["type"] == "cylinder":
        box = g.get("bbox")
        return (
            close(g.get("radius"), expected["radius"])
            and same_line(g.get("axis"), intent["axis"])
            and isinstance(box, list)
            and len(box) == 2
            and all(machining._point(p) for p in box)
            and close([p[intent["axial_index"]] for p in box], expected["axial"])
        )
    if not all(machining._point(g.get(k)) for k in ("normal", "origin")):
        return False
    return close(
        abs(machining.dot(g.get("normal", [0, 0, 0]), intent["axis"]["direction"])), 1
    ) and close((g.get("origin") or [None] * 3)[intent["axial_index"]], expected["at"])


def _sections(detail, intent, external):
    raw = detail.get("native_section_readback") or {}
    if raw.get("returned") != 0:
        return False
    try:
        location = [float(v) for v in raw["location"].split()]
        if len(location) != 12 or not all(math.isfinite(v) for v in location):
            return False
        frame = {
            "x": location[:3],
            "y": location[3:6],
            "normal": location[6:9],
            "origin": location[9:],
        }
        lines, axes = [], []
        for entity in raw["entities_read"].split(";"):
            fields = entity.split()
            if not fields:
                continue
            if fields[1] == "R":
                continue
            if fields[1] not in ("L", "K") or len(fields) != 6:
                return False
            values = [float(v) for v in fields[2:]]
            pair = [_world(frame, values[:2]), _world(frame, values[2:])]
            (lines if fields[1] == "L" else axes).append(pair)
        wanted = list(
            zip(
                intent["world_profile"],
                intent["world_profile"][1:] + intent["world_profile"][:1],
                strict=True,
            )
        )
        for a, b in wanted:
            found = next(
                (i for i, pair in enumerate(lines) if close(pair, [a, b]) or close(pair, [b, a])),
                None,
            )
            if found is None:
                return False
            lines.pop(found)
        if lines:
            return False
        return external or any(
            same_line(line(p, [b - a for a, b in zip(p, end, strict=True)]), intent["axis"])
            for p, end in axes
        )
    except (KeyError, TypeError, ValueError, IndexError, Error):
        return False


def cylindrical_boundary(walls, face, intent, items):
    """Allow native seam splitting, require a closed physical rim at both stations."""
    by_ref = {g["ref"]: g for g in items}
    refs = {g["ref"] for g in walls}
    rims = [[], []]
    unexpected = []
    readable = bool(walls)
    for edge in items:
        if edge.get("kind") != "edge" or not refs.intersection(edge.get("surfaces", [])):
            continue
        adjacent = edge.get("surfaces", [])
        if len(adjacent) != 2 or any(r not in by_ref for r in adjacent):
            readable = False
            continue
        if all(r in refs for r in adjacent):
            continue
        cap = by_ref[next(r for r in adjacent if r not in refs)]
        if edge.get("type") not in ("arc", "circle"):
            unexpected.append(edge["ref"])
            continue
        if not all(
            machining._point(edge.get(k)) for k in ("center", "normal", "start", "end")
        ) or type(edge.get("length")) not in (int, float):
            readable = False
            continue
        found = False
        for i, station in enumerate(face["axial"]):
            if (
                close(edge.get("radius"), face["radius"])
                and close(abs(machining.dot(edge["normal"], intent["axis"]["direction"])), 1)
                and machining._axis_distance(edge["center"], intent["axis"]) < TOL
                and all(
                    close(edge[k][intent["axial_index"]], station)
                    for k in ("center", "start", "end")
                )
                and cap.get("type") == "plane"
                and machining._point(cap.get("normal"))
                and close(abs(machining.dot(cap["normal"], intent["axis"]["direction"])), 1)
                and close((cap.get("origin") or [None] * 3)[intent["axial_index"]], station)
            ):
                rims[i].append(edge)
                found = True
        if not found:
            unexpected.append(edge["ref"])
    return {
        "readable": readable,
        "unexpected_boundary": unexpected,
        "rims": [
            {
                "at": station,
                "closed": machining._closed_rim(edges),
                "expected_length": 2 * math.pi * face["radius"],
                "observed_length": sum(e["length"] for e in edges),
                "refs": [e["ref"] for e in edges],
            }
            for station, edges in zip(face["axial"], rims, strict=True)
        ],
    }


def planar_regions(faces, items):
    """Only native shared edges connect patches; coplanarity alone does not."""
    remaining = {g["ref"]: g for g in faces}
    groups = []
    links = [set(e.get("surfaces", [])) for e in items if e.get("kind") == "edge"]
    while remaining:
        seed = next(iter(remaining))
        refs = {seed}
        while True:
            adjacent = set().union(*(edge for edge in links if edge & refs), set())
            added = set(remaining) & adjacent - refs
            if not added:
                break
            refs |= added
        groups.append([remaining.pop(ref) for ref in sorted(refs)])
    return groups


def planar_boundary(patches, face, intent, items):
    """Prove each disk/annulus from its closed, coaxial physical circular rims."""
    by_ref = {g["ref"]: g for g in items}
    refs = {g["ref"] for g in patches}
    radii = [r for r in face["radial"] if r > TOL]
    rims = [[] for _ in radii]
    readable, unexpected = bool(patches), []
    for edge in items:
        adjacent = edge.get("surfaces", [])
        if edge.get("kind") != "edge" or not refs.intersection(adjacent):
            continue
        if len(adjacent) != 2 or any(ref not in by_ref for ref in adjacent):
            readable = False
            continue
        if all(ref in refs for ref in adjacent):
            continue
        wall = by_ref[next(ref for ref in adjacent if ref not in refs)]
        if not all(
            machining._point(edge.get(k)) for k in ("center", "normal", "start", "end")
        ) or type(edge.get("length")) not in (int, float):
            readable = False
            continue
        match = next(
            (
                i
                for i, radius in enumerate(radii)
                if edge.get("type") in ("circle", "arc")
                and close(edge.get("radius"), radius)
                and close(abs(machining.dot(edge["normal"], intent["axis"]["direction"])), 1)
                and machining._axis_distance(edge["center"], intent["axis"]) < TOL
                and all(
                    close(edge[k][intent["axial_index"]], face["at"])
                    for k in ("center", "start", "end")
                )
                and wall.get("type") == "cylinder"
                and close(wall.get("radius"), radius)
                and same_line(wall.get("axis"), intent["axis"])
            ),
            None,
        )
        if match is None:
            unexpected.append(edge["ref"])
        else:
            rims[match].append(edge)
    return {
        "readable": readable,
        "unexpected_boundary": unexpected,
        "rims": [
            {
                "radius": radius,
                "closed": machining._closed_rim(edges),
                "expected_length": 2 * math.pi * radius,
                "observed_length": sum(e["length"] for e in edges),
                "refs": [e["ref"] for e in edges],
            }
            for radius, edges in zip(radii, rims, strict=True)
        ],
    }


def _boundary_passes(boundary):
    return (
        boundary["readable"]
        and not boundary["unexpected_boundary"]
        and all(
            r["closed"] and close(r["observed_length"], r["expected_length"])
            for r in boundary["rims"]
        )
    )


def verify_geometry(op, q, before, intent, after, ident):
    checks = []

    def check(name, passed, **detail):
        checks.append(engine.check(name, passed, **detail))

    f = next((f for f in after["features"] if f["id"] == ident), {})
    check(
        "identified_feature_active", f.get("type") == TYPES[op] and f.get("status") == "FEAT_ACTIVE"
    )

    check(
        "feature_name_matches",
        not q.get("name") or str(f.get("name")).casefold() == q["name"].casefold(),
    )
    check("units_unchanged", before["model"].get("units") == after["model"].get("units"))
    old = {f["id"]: f for f in before["features"]}
    now = {f["id"]: f for f in after["features"]}
    check("unrelated_features_unchanged", all(now.get(i) == row for i, row in old.items()))
    check(
        "no_unexpected_visible_features",
        all(i in old or i == ident or row.get("visible") is False for i, row in now.items()),
    )
    old_dims = {d["name"]: d for d in before["dimensions"]["dimensions"]}
    now_dims = {d["name"]: d for d in after["dimensions"]["dimensions"]}
    check(
        "unrelated_dimensions_unchanged",
        all(equivalent(now_dims.get(i), row) for i, row in old_dims.items()),
    )
    check(
        "unrelated_constructions_unchanged",
        all(
            equivalent(after["construction_details"].get(i), row)
            for i, row in before["construction_details"].items()
        ),
    )
    previous = {g["ref"]: g for g in before["geometry"]["items"]}
    current = {g["ref"]: g for g in after["geometry"]["items"]}
    check(
        "previous_geometry_unchanged",
        all(equivalent(current.get(i), row) for i, row in previous.items()),
    )
    detail = after["construction_details"].get(ident, {})
    definition = detail.get("native_definition") or {}
    check("native_definition_complete", definition.get("complete") is True)
    own = [
        g for g in after["geometry"]["items"] if str((g.get("feature") or {}).get("id")) == ident
    ]
    check("construction_evidence_readable", evidence_readable(intent, after, ident))
    if op != "feature.revolve":
        actual = [
            {k: row.get(k) for k in expected}
            for row, expected in zip(
                definition.get("constraints", []), intent["constraints"], strict=False
            )
        ]
        check(
            "native_constraint_relations",
            len(definition.get("constraints", [])) == len(intent["constraints"])
            and equivalent(actual, intent["constraints"]),
        )
        geometry = [
            g
            for g in own
            if g.get("kind") == ("axis" if intent["kind"] == "datum_axis" else "datum_plane")
        ]
        if op == "feature.datum-plane":
            good = (
                len(geometry) == 1
                and machining._point(geometry[0].get("origin"))
                and close(geometry[0].get("normal"), intent["normal"])
            )
            if good:
                good = close(
                    machining.dot(geometry[0].get("origin", [0, 0, 0]), intent["normal"]),
                    machining.dot(intent["origin"], intent["normal"]),
                )
            check("signed_plane_position_and_normal", good, expected=intent)
        else:
            check(
                "axis_position_and_direction",
                len(geometry) == 1 and same_line(geometry[0].get("line"), intent["line"]),
                expected=intent["line"],
            )
        check(
            "physical_solid_unchanged",
            equivalent(
                before["model"].get("mass_properties"), after["model"].get("mass_properties")
            )
            and equivalent(before["model"].get("bbox"), after["model"].get("bbox")),
        )
    else:
        bodies = after["model"].get("bodies")
        check(
            "one_active_solid_body",
            isinstance(bodies, list)
            and len(bodies) == 1
            and bodies[0].get("state") == "BODY_STATE_ACTIVE",
            observed=bodies,
        )
        check(
            "revolve_definition_matches",
            definition.get("kind") == "revolve"
            and close(definition.get("angle"), 360)
            and all(
                definition.get(k) is True for k in ("solid", "add_material", "no_thin", "from_none")
            )
            and definition.get("angle_mode")
            == ("symmetric" if q.get("side") == "symmetric" else "one_side")
            and definition.get("sketch_plane") == q["sketch"]["plane"]
            and definition.get("orient_ref") == q["sketch"]["orient_ref"],
        )
        external = isinstance(q["axis"], str)
        check(
            "revolve_axis_reference",
            definition.get("axis_kind") == ("external" if external else "sketched")
            and (not external or definition.get("axis_reference") == q["axis"]),
        )
        check("actual_section_in_model_coordinates", _sections(detail, intent, external))
        faces = [g for g in after["geometry"]["items"] if g.get("kind") == "surface"]
        remaining = list(faces)
        matched = []
        for expected in intent["faces"]:
            group = [g for g in remaining if _surface_matches(g, expected, intent)]
            if expected["type"] == "plane":
                candidates = planar_regions(group, after["geometry"]["items"])
                matches = [
                    patches
                    for patches in candidates
                    if _boundary_passes(
                        planar_boundary(patches, expected, intent, after["geometry"]["items"])
                    )
                ]
                group = matches[0] if len(matches) == 1 else []
            readable = bool(group) and all(
                type(g.get("area")) in (int, float) and math.isfinite(g["area"]) for g in group
            )
            observed_area = sum(g["area"] for g in group) if readable else None
            row = {
                "expected": expected,
                "observed": group,
                "observed_area": observed_area,
                "passed": readable and close(observed_area, expected["area"]),
            }
            if expected["type"] == "cylinder":
                boundary = cylindrical_boundary(group, expected, intent, after["geometry"]["items"])
            else:
                boundary = planar_boundary(group, expected, intent, after["geometry"]["items"])
            row["boundary"] = boundary
            row["passed"] = row["passed"] and _boundary_passes(boundary)
            matched.append(row)
            for hit in group:
                remaining.remove(hit)
        complete_boundary = not remaining and all(r["passed"] for r in matched)
        check(
            "complete_analytic_solid_boundary",
            complete_boundary,
            surfaces=matched,
            unmatched_surfaces=[g["ref"] for g in remaining],
        )
        check(
            "solid_volume",
            close(after["model"].get("mass_properties", {}).get("volume"), intent["volume"]),
            expected=intent["volume"],
            observed=after["model"].get("mass_properties", {}).get("volume"),
        )
        # GetGeomOutline / GetXYZExtents may conservatively expand a curved face.
        # Derive exact bounds only from the independently proven full analytic boundary.
        boxes = []
        for row in matched:
            if row["expected"]["type"] != "cylinder" or not row["observed"]:
                continue
            g = row["observed"][0]
            measured_axis = line(g["axis"]["origin"], g["axis"]["direction"])
            k = intent["axial_index"]
            actual = {
                "type": "cylinder",
                "radius": g["radius"],
                "axial": [g["bbox"][0][k], g["bbox"][1][k]],
            }
            boxes.append(_surface_box(intent | {"axis": measured_axis}, actual))
        box = (
            [
                [min(b[0][i] for b in boxes) for i in range(3)],
                [max(b[1][i] for b in boxes) for i in range(3)],
            ]
            if boxes
            else None
        )
        check(
            "solid_bounds",
            complete_boundary and close(box, intent["box"]),
            expected=intent["box"],
            observed=box,
            raw_native_outline=after["model"].get("bbox"),
            source="analytic radii/axes, trimmed axial extents and verified closed circular rims; "
            "raw outline is conservative",
        )
    return {
        "construction_intent": intent,
        "native_definition": definition,
        "independent_geometry": own,
    }, {
        "checks": checks,
        "observations": [{"observation": "independent_construction_snapshot", "current": after}],
        "level": "selected_postconditions_verified",
        "not_checked": ["manufacturing approval", "unsupported revolve/datum variants"],
    }


def _recheck_feature_observation(plan, before, after, feature_id, verification):
    """Recheck the final snapshot; keep the earlier feature read as separate evidence."""
    rows = after.get("features")
    baseline = plan.binding.get("features")
    naming = plan.binding.get("name_intent")
    if not isinstance(rows, list) or not isinstance(baseline, list) or not isinstance(naming, dict):
        raise Error("E_VERIFY_INCOMPLETE", "construction feature comparison is incomplete")
    if any(not isinstance(row, dict) or row.get("id") is None for row in baseline + rows):
        raise Error("E_VERIFY_INCOMPLETE", "construction feature identity is unavailable")
    baseline_ids = [str(row["id"]) for row in baseline]
    if len(baseline_ids) != len(set(baseline_ids)):
        raise Error("E_VERIFY_INCOMPLETE", "construction baseline feature identity is ambiguous")
    ident = str(feature_id)
    final_matches = [row for row in rows if str(row.get("id")) == ident]
    if len(final_matches) != 1:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "the final construction feature identity is ambiguous",
            {"feature": ident, "matching_rows": len(final_matches)},
        )
    final_name = final_matches[0].get("name")
    if "name" not in final_matches[0] or not (final_name is None or isinstance(final_name, str)):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "the final construction feature name is unavailable",
            {"feature": ident, "name_field_present": "name" in final_matches[0]},
        )
    prior = [
        item
        for item in verification.get("observations", [])
        if item.get("observation") == "new_features"
    ]
    if len(prior) != 1 or not isinstance(prior[0].get("features"), list):
        raise Error(
            "E_VERIFY_INCOMPLETE", "the earlier construction feature observation is unavailable"
        )
    earlier_matches = [row for row in prior[0]["features"] if str(row.get("id")) == ident]
    if len(earlier_matches) != 1:
        raise Error("E_VERIFY_INCOMPLETE", "the earlier construction feature identity is ambiguous")

    replacement = {
        check["check"]: check
        for check in building.feature_readback_checks(baseline, rows, ident, TYPES[plan.op], naming)
    }
    after_ids = [str(row.get("id")) for row in rows]
    by_id = {str(row.get("id")): row for row in rows}
    replacement["existing_features_unchanged"] = engine.check(
        "existing_features_unchanged",
        len(after_ids) == len(set(after_ids))
        and all(
            str(row.get("id")) in by_id and by_id[str(row["id"])].get("status") == row.get("status")
            for row in baseline
        ),
    )
    replacement["units_unchanged"] = engine.check(
        "units_unchanged", before["model"].get("units") == after["model"].get("units")
    )
    seen = set()
    checks = []
    for old in verification.get("checks", []):
        name = old.get("check")
        if name not in replacement:
            retained = copy.deepcopy(old)
            retained.setdefault("observation_source", "service_reply_or_earlier_verification")
            checks.append(retained)
            continue
        if name in seen:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "duplicate earlier feature verification check",
                {"check": name},
            )
        seen.add(name)
        current = replacement[name]
        current["earlier_observation_passed"] = old.get("passed") is True
        current["observation_source"] = "independent_construction_snapshot"
        if "service_reply_passed" in old:
            current["service_reply_passed"] = old["service_reply_passed"]
        current["passed"] = current.get("passed") is True and old.get("passed") is True
        checks.append(current)
    if seen != set(replacement):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "required earlier feature verification checks are missing",
            {"checks": sorted(set(replacement) - seen)},
        )
    earlier = earlier_matches[0]
    final = final_matches[0] if len(final_matches) == 1 else None
    checks.append(
        engine.check(
            "feature_observation_consistent",
            final is not None and digest(earlier) == digest(final),
            earlier=copy.deepcopy(earlier),
            final=copy.deepcopy(final),
            source="earlier feature list and final independent construction snapshot",
        )
    )
    verification["checks"] = checks
    prior[0]["source"] = "earlier_independent_feature_list"
    verification["observations"].append(
        {
            "observation": "feature_observation_comparison",
            "earlier": copy.deepcopy(earlier),
            "final": copy.deepcopy(final),
            "source": "same Plan and Client; no earlier success is substituted "
            "for the final snapshot",
        }
    )


def checked_plan(client, plan, request):
    client.require_capability("revolved_datum_readback", 1)
    before = snapshot(client, plan.target)
    if plan.before.get("model", {}).get("units") != before["model"].get("units") or plan.before.get(
        "features"
    ) != before.get("features"):
        raise Error("E_VERIFY_INCOMPLETE", "construction pre-state observations disagree")
    intent = (
        revolve_intent(request, before, plan.preview["sketch"])
        if plan.op == "feature.revolve"
        else datum_intent(plan.op, request, before)
    )
    plan.binding |= {"construction_before": before, "construction_intent": intent}
    plan.preview["construction_intent"] = intent
    plan.preview["limits"] = [
        "full 360 degree orthogonal first-solid revolve",
        "signed offset plane",
        "axis through two nonparallel planes or one line/cylinder",
        "leaf commands only; no creating workflow",
    ]
    plan.before = before
    plan.observe = lambda c: snapshot(c, plan.target)
    previous = plan.verify
    frozen_request = copy.deepcopy(request)
    frozen_intent = copy.deepcopy(intent)
    frozen_plan = copy.deepcopy(
        {
            key: getattr(plan, key)
            for key in ("op", "target", "request", "binding", "preview", "arguments", "before")
        }
    )
    frozen_request_digest = digest(frozen_request)
    frozen_intent_digest = digest(frozen_intent)
    frozen_plan_digest = digest(frozen_plan)
    checked_after = {}
    first_failure = {}
    verifier_state = {"attempted": False, "invalid": False}

    def same_plan(planned, c):
        try:
            return (
                planned is plan
                and c is client
                and plan.op in ("feature.revolve", "feature.datum-plane", "feature.datum-axis")
                and digest(request) == frozen_request_digest
                and digest(intent) == frozen_intent_digest
                and not verifier_state["invalid"]
                and not getattr(c, "_native_read_pending", None)
                and not getattr(c, "_native_diagnostic_stop", None)
                and digest({key: getattr(plan, key) for key in frozen_plan}) == frozen_plan_digest
            )
        except (TypeError, ValueError, OverflowError):
            return False

    def verify(c, data):
        if not same_plan(plan, c) or verifier_state["attempted"]:
            verifier_state["invalid"] = True
            plan.verified_observation = None
            raise Error("E_VERIFY_INCOMPLETE", "construction verifier cannot be reused or rebound")
        verifier_state["attempted"] = True
        plan.verified_observation = None
        checked_after.clear()
        first_failure.clear()
        try:
            result, verification = previous(c, data)
            if (
                verification.get("status") == "incomplete"
                or verification.get("level") == "service_reply_only"
            ):
                first = next(
                    (
                        item.get("error")
                        for item in verification.get("observations", [])
                        if item.get("observation") == "independent_read_back_failed"
                        and isinstance(item.get("error"), dict)
                    ),
                    None,
                )
                pending = native_read_recovery.pending_error(first)
                diagnostic = native_diagnostic_recovery.diagnostic_error(first)
                if pending or diagnostic:
                    original = pending or diagnostic
                    code = "E_NATIVE_READ_PENDING" if pending else "E_NATIVE_DIAGNOSTIC"
                    key = "native_read_error" if pending else "native_diagnostic_error"
                    raise Error(
                        code,
                        original.get("message") or "native read requires an immediate stop",
                        {
                            key: copy.deepcopy(original),
                            "first_readback_error": copy.deepcopy(first),
                        },
                    )
                if first and first.get("code") in ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"):
                    raise Error(
                        first["code"],
                        first.get("message") or "native read requires an immediate stop",
                        copy.deepcopy(first.get("details") or {}),
                    )
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "the first construction verification observation is incomplete",
                    {
                        "first_readback_error": copy.deepcopy(first),
                        "verification": copy.deepcopy(verification),
                    },
                )
            after = snapshot(c, plan.target)
            extra, proof = verify_geometry(
                plan.op, request, before, intent, after, str(data["feature"]["id"])
            )
            _recheck_feature_observation(plan, before, after, data["feature"]["id"], verification)
        except Error as exc:
            if same_plan(plan, c):
                first_failure.update(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                    details=copy.deepcopy(exc.details),
                )
            raise
        if not same_plan(plan, c):
            raise Error(
                "E_VERIFY_INCOMPLETE", "construction observation lost its Plan and Client binding"
            )
        result.update(extra)
        verification["checks"].extend(
            check | {"observation_source": "independent_construction_snapshot"}
            for check in proof["checks"]
        )
        verification["observations"].extend(proof["observations"])
        checked_after.update(copy.deepcopy(after))
        if engine.verification_status(verification) == "passed":
            # No CAD mutation follows this verifier before the receipt is committed.
            # Reuse exactly this checked snapshot, as the existing property leaves do.
            plan.verified_observation = copy.deepcopy(after)
        return result, verification

    def verified_guard(planned, c):
        if not same_plan(planned, c) or not checked_after:
            return False
        try:
            return digest(plan.verified_observation) == digest(checked_after)
        except (TypeError, ValueError, OverflowError):
            return False

    plan.verify = verify
    plan._verified_observation_guard = verified_guard
    plan._settled_observation = lambda planned, c: (
        copy.deepcopy(checked_after) if same_plan(planned, c) and checked_after else None
    )
    plan._first_verification_failure = lambda planned, c: (
        copy.deepcopy(first_failure) if same_plan(planned, c) and first_failure else None
    )
    return plan


def evidence_readable(intent, state, ident):
    detail = state["construction_details"].get(ident, {})
    definition = detail.get("native_definition") or {}
    if definition.get("complete") is not True:
        return False
    own = [
        g for g in state["geometry"]["items"] if str((g.get("feature") or {}).get("id")) == ident
    ]
    if intent["kind"] == "datum_plane":
        return any(
            g.get("kind") == "datum_plane"
            and all(machining._point(g.get(k)) for k in ("origin", "normal"))
            for g in own
        )
    if intent["kind"] == "datum_axis":
        return any(
            g.get("kind") == "axis"
            and isinstance(g.get("line"), dict)
            and all(machining._point(g["line"].get(k)) for k in ("origin", "direction"))
            for g in own
        )
    raw = detail.get("native_section_readback") or {}
    try:
        values = [float(v) for v in raw["location"].split()]
        if raw.get("returned") != 0:
            return False
        if (
            len(values) != 12
            or not all(math.isfinite(v) for v in values)
            or not raw.get("entities_read")
        ):
            return False
    except (KeyError, ValueError, TypeError):
        return False
    items = state["geometry"]["items"]
    refs = {g["ref"] for g in items}
    for g in items:
        if g.get("kind") == "surface":
            if type(g.get("area")) not in (int, float) or not math.isfinite(g["area"]):
                return False
            if g.get("type") == "cylinder" and (
                not g.get("axis")
                or not all(machining._point(g["axis"].get(k)) for k in ("origin", "direction"))
                or type(g.get("radius")) not in (int, float)
                or not g.get("bbox")
            ):
                return False
            if g.get("type") == "plane" and not all(
                machining._point(g.get(k)) for k in ("origin", "normal")
            ):
                return False
        if (
            g.get("kind") == "edge"
            and g.get("type") in ("circle", "arc")
            and (
                not all(machining._point(g.get(k)) for k in ("center", "normal", "start", "end"))
                or type(g.get("radius")) not in (int, float)
                or type(g.get("length")) not in (int, float)
            )
        ):
            return False
        if g.get("kind") == "edge" and (
            not isinstance(g.get("surfaces"), list)
            or len(g["surfaces"]) != 2
            or any(r not in refs for r in g["surfaces"])
        ):
            return False
        if (
            g.get("kind") == "surface"
            and g.get("type") == "cylinder"
            and not any(
                e.get("kind") == "edge" and g["ref"] in e.get("surfaces", []) for e in items
            )
        ):
            return False
    return True


def recovery(client, run):
    plan = run.get("driver_plan") or {}
    baseline = (
        plan.get("base_snapshot", {}).get("extensions", {}).get("creo", {}).get("observation", {})
    )
    before, intent = baseline.get("construction_before"), baseline.get("construction_intent")
    request = (plan.get("changes") or [{}])[0].get("after")
    if (
        not before
        or not intent
        or not isinstance(request, dict)
        or request.get("model") != run.get("target")
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "retained construction intent is unavailable; outcome remains unknown",
        )
    if client.health().get("service_instance_id") != plan.get("target", {}).get("instance_id"):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "current instance differs; model absence is not recovery evidence",
        )
    client.require_capability("revolved_datum_readback", 1)
    after = snapshot(client, run["target"])
    previous = {f["id"] for f in before["features"]}
    added = [f for f in after["features"] if f["id"] not in previous]
    op = run["command"].replace(" ", ".")
    candidates = [
        f
        for f in added
        if f["type"] == TYPES[op]
        and (not request.get("name") or str(f.get("name")).casefold() == request["name"].casefold())
    ]
    identified = len(candidates) == 1
    checks = [engine.check("one_identified_construction", identified, added=added)]
    if identified:
        _, proof = verify_geometry(op, request, before, intent, after, candidates[0]["id"])
        checks += proof["checks"]
    stable = equivalent(after, snapshot(client, run["target"]))
    checks.append(engine.check("independent_readback_stable", stable))
    complete = identified and evidence_readable(intent, after, candidates[0]["id"])
    accepted = all(c["passed"] for c in checks)
    unchanged = stable and equivalent(before, after)
    return {
        "accepted": accepted,
        "can_register": ["applied"]
        if accepted
        else ["not_applied"]
        if unchanged
        else ["partial"]
        if stable and complete
        else [],
        "checks": checks,
        "intent": intent,
        "current": after,
        "original_operation_id": run["operation_id"],
        "coverage": "frozen bounded construction intent, native relations/section "
        "and current analytic solid; no replay",
    }
