"""Bounded inward rectangular shells: frozen intent and current native boundary proof.

This module only supplies observations and predicates to the existing lifecycle.
It neither creates geometry nor dispatches, retries, or restores a write.
"""

import math
from copy import deepcopy

from . import building, engine, model_management, operations, safety
from .core import Error, digest

COMMANDS = ("feature shell",)
PROFILE = "prismatic-shell-v1"
TOL = 1e-6  # mm/geometry comparison, never a manufacturing tolerance.


def close(a, b):
    return (
        type(a) in (int, float)
        and type(b) in (int, float)
        and math.isfinite(a)
        and math.isfinite(b)
        and math.isclose(a, b, abs_tol=TOL, rel_tol=1e-6)
    )


def point(p):
    if (
        not isinstance(p, list)
        or len(p) != 3
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete finite native XYZ coordinates required")
    return tuple(round(float(v), 6) for v in p)


def canonical_request(client, name, request):
    q = deepcopy(request)
    if (
        q.get("units") != "mm"
        or q.get("side", "inside") != "inside"
        or len(q.get("remove", [])) != 1
    ):
        raise Error(
            "E_UNSUPPORTED", "bounded shell supports mm, inward walls and one explicit top face"
        )
    data = client.op("geometry.list", {"model": name})
    resolved = building.resolve_references(data["items"], q.get("remove", []))
    q["remove"] = [resolved[r]["ref"] for r in q.get("remove", [])]
    return q


def geometry(client, name):
    result = engine.normalize(client.op("geometry.list", {"model": name, "profile": PROFILE}))
    if (
        result.get("complete") is not True
        or result.get("profile") != PROFILE
        or result.get("model") != name
    ):
        code = (
            "E_UNSUPPORTED"
            if (result.get("error") or {}).get("code") == "E_UNSUPPORTED"
            else "E_VERIFY_INCOMPLETE"
        )
        raise Error(
            code,
            "complete bounded planar-body readback is required",
            {"readback": result, "_untrusted": ["readback"]},
        )
    return result


def snapshot(client, name):
    client.require_capability("prismatic_shell_readback", 2)
    result = model_management.snapshot(client, name)
    result["geometry"] = geometry(client, name)
    if result["geometry"].get("units") != result["model"].get("units"):
        raise Error("E_VERIFY_INCOMPLETE", "native body units disagree with its model")
    result["definitions"] = {}
    for feature in result["parts"][name]["features"]:
        if feature["type"] == "FEATTYPE_SHELL":
            detail = engine.normalize(
                client.op("feature.show", {"model": name, "feature": feature["id"]})
            )
            result["definitions"][feature["id"]] = detail.get("native_definition")
    return result


def _line(a, b):
    a, b = point(list(a)), point(list(b))
    axes = [i for i in range(3) if abs(a[i] - b[i]) > TOL]
    if len(axes) != 1:
        raise Error(
            "E_UNSUPPORTED", "bounded rectangular shell needs axis-aligned straight boundaries"
        )
    axis = axes[0]
    fixed = tuple(a[i] for i in range(3) if i != axis)
    if any(not close(a[i], b[i]) for i in range(3) if i != axis):
        raise Error("E_VERIFY_INCOMPLETE", "boundary line is not axis aligned")
    return (axis, *fixed), (min(a[axis], b[axis]), max(a[axis], b[axis]))


def _boundary(segments):
    lines = {}
    for a, b in segments:
        key, interval = _line(a, b)
        lines.setdefault(key, []).append(interval)
    result = []
    for key, intervals in sorted(lines.items()):
        merged = []
        for lo, hi in sorted(intervals):
            if merged and lo < merged[-1][1] - TOL:
                raise Error("E_VERIFY_INCOMPLETE", "overlapping physical boundary edges")
            if merged and close(lo, merged[-1][1]):
                merged[-1] = (merged[-1][0], hi)
            else:
                merged.append((lo, hi))
        result.extend([list(key), list(interval)] for interval in merged)
    return result


def _closed_loop(refs, edges, face):
    if (
        not isinstance(refs, list)
        or len(refs) < 3
        or any(not isinstance(r, str) or not r for r in refs)
        or len(set(refs)) != len(refs)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "native contour identity is incomplete or repeated")
    graph = {}
    for ref in refs:
        edge = edges.get(ref)
        if not edge or face not in edge.get("surfaces", []):
            raise Error("E_VERIFY_INCOMPLETE", "contour/edge/native-face ownership disagrees")
        a, b = point(edge.get("start")), point(edge.get("end"))
        if a == b:
            raise Error("E_VERIFY_INCOMPLETE", "degenerate native contour edge")
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    if any(len(neighbors) != 2 for neighbors in graph.values()):
        raise Error("E_VERIFY_INCOMPLETE", "native contour is not a closed linear cycle")
    seen, todo = set(), [next(iter(graph))]
    while todo:
        vertex = todo.pop()
        if vertex not in seen:
            seen.add(vertex)
            todo.extend(graph[vertex])
    if len(seen) != len(graph):
        raise Error("E_VERIFY_INCOMPLETE", "native contour contains disconnected cycles")


def regions(data):
    if (
        not isinstance(data, dict)
        or data.get("complete") is not True
        or data.get("profile") != PROFILE
        or not isinstance(data.get("body"), dict)
        or data["body"].get("state") != "BODY_STATE_ACTIVE"
    ):
        raise Error("E_VERIFY_INCOMPLETE", "one complete active native body is required")
    items = data.get("items")
    if not isinstance(items, list) or any(not isinstance(x, dict) or x.get("error") for x in items):
        raise Error("E_VERIFY_INCOMPLETE", "native boundary inventory is incomplete")
    if not isinstance(data.get("body", {}).get("id"), (int, str)) or any(
        x.get("kind") not in ("surface", "edge")
        or str(x.get("ref")) != str(x["kind"]) + ":" + str(x.get("id"))
        for x in items
    ):
        raise Error("E_VERIFY_INCOMPLETE", "native body or physical item identity is incomplete")
    if len({x.get("ref") for x in items}) != len(items):
        raise Error("E_VERIFY_INCOMPLETE", "native geometry identities are repeated")
    faces = {x["ref"]: x for x in items if x.get("kind") == "surface"}
    edges = {x["ref"]: x for x in items if x.get("kind") == "edge"}
    if not faces or not edges or len(faces) + len(edges) != len(items):
        raise Error("E_VERIFY_INCOMPLETE", "complete physical faces and edges are required")
    grouped, ownership, uses = {}, {}, {ref: [] for ref in edges}
    for ref, face in faces.items():
        normal, origin = point(face.get("normal")), point(face.get("origin"))
        axes = [i for i, v in enumerate(normal) if abs(v) > TOL]
        if face.get("type") != "plane" or len(axes) != 1 or not close(abs(normal[axes[0]]), 1):
            raise Error("E_UNSUPPORTED", "bounded shell proof needs orthogonal model-axis planes")
        axis = axes[0]
        key = (axis, 1 if normal[axis] > 0 else -1, origin[axis])
        if (
            type(face.get("area")) not in (int, float)
            or not math.isfinite(face["area"])
            or face["area"] <= 0
        ):
            raise Error("E_VERIFY_INCOMPLETE", "positive native face area is unavailable")
        group = grouped.setdefault(key, {"faces": [], "area": 0.0, "segments": []})
        group["faces"].append(ref)
        group["area"] += face["area"]
        ownership[ref] = key
        loops = face.get("boundary_loops")
        if not isinstance(loops, list) or not loops:
            raise Error("E_VERIFY_INCOMPLETE", "complete native face contours required")
        for loop in loops:
            _closed_loop(loop, edges, ref)
            for edge_ref in loop:
                uses[edge_ref].append(ref)
                for p in (edges[edge_ref]["start"], edges[edge_ref]["end"]):
                    if not close(point(p)[axis], origin[axis]):
                        raise Error(
                            "E_VERIFY_INCOMPLETE", "face contour lies outside its native plane"
                        )
    graph = {ref: set() for ref in faces}
    for ref, edge in edges.items():
        adjacent = edge.get("surfaces")
        if (
            edge.get("type") != "line"
            or not isinstance(adjacent, list)
            or len(adjacent) != 2
            or len(set(adjacent)) != 2
            or set(uses[ref]) != set(adjacent)
            or len(uses[ref]) != 2
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "physical edge must bound exactly two observed faces"
            )
        a, b = point(edge.get("start")), point(edge.get("end"))
        if not close(edge.get("length"), math.dist(a, b)):
            raise Error("E_VERIFY_INCOMPLETE", "native straight-edge length and endpoints disagree")
        _line(a, b)
        graph[adjacent[0]].add(adjacent[1])
        graph[adjacent[1]].add(adjacent[0])
        keys = {ownership[face] for face in adjacent}
        if len(keys) == 2:
            for key in keys:
                grouped[key]["segments"].append((a, b))
    seen, todo = set(), [next(iter(faces))]
    while todo:
        face = todo.pop()
        if face not in seen:
            seen.add(face)
            todo.extend(graph[face])
    if len(seen) != len(faces):
        raise Error("E_UNSUPPORTED", "disconnected shells or bodies are outside this profile")
    for value in grouped.values():
        value["boundary"] = _boundary(value.pop("segments"))
    points = [point(e[k]) for e in edges.values() for k in ("start", "end")]
    bounds = [
        [min(p[i] for p in points) for i in range(3)],
        [max(p[i] for p in points) for i in range(3)],
    ]
    return grouped, bounds


def _rectangle(axis, coordinate, lo, hi):
    u, v = [i for i in range(3) if i != axis]
    corners = []
    for x, y in ((lo[u], lo[v]), (hi[u], lo[v]), (hi[u], hi[v]), (lo[u], hi[v])):
        p = [0.0, 0.0, 0.0]
        p[axis], p[u], p[v] = coordinate, x, y
        corners.append(p)
    return list(zip(corners, corners[1:] + corners[:1], strict=True)), (hi[u] - lo[u]) * (
        hi[v] - lo[v]
    )


def expected_regions(bounds, thickness=None):
    lo, hi = bounds
    result = {}
    for axis in range(3):
        for sign, value in ((-1, lo[axis]), (1, hi[axis])):
            edges, area = _rectangle(axis, value, lo, hi)
            result[(axis, sign, value)] = {"segments": edges, "area": area}
    if thickness is not None:
        inner_lo = [v + thickness for v in lo]
        inner_hi = [hi[0] - thickness, hi[1] - thickness, hi[2]]
        rim, hole = _rectangle(2, hi[2], inner_lo, inner_hi)
        result[(2, 1, hi[2])]["segments"] += rim
        result[(2, 1, hi[2])]["area"] -= hole
        for axis in (0, 1):
            for sign, value in ((1, inner_lo[axis]), (-1, inner_hi[axis])):
                edges, area = _rectangle(axis, value, inner_lo, inner_hi)
                result[(axis, sign, value)] = {"segments": edges, "area": area}
        edges, area = _rectangle(2, inner_lo[2], inner_lo, inner_hi)
        result[(2, 1, inner_lo[2])] = {"segments": edges, "area": area}
    # Native origins and contour points share point()'s six-decimal mm resolution.
    # Compare intended plane identities at that same resolution, while retaining the
    # requested thickness and unrounded analytic areas/volume in their own checks.
    return {
        (axis, sign, round(coordinate, 6)): {
            "boundary": _boundary(value["segments"]),
            "area": value["area"],
        }
        for (axis, sign, coordinate), value in result.items()
    }


def shape_checks(data, bounds, thickness=None):
    actual, actual_bounds = regions(data)
    expected = expected_regions(bounds, thickness)
    checks = [
        engine.check("exact_oriented_plane_regions", set(actual) == set(expected)),
        engine.check("outer_native_boundary_unchanged", actual_bounds == bounds),
    ]
    for key, wanted in expected.items():
        found = actual.get(key, {})
        checks.append(
            engine.check(
                "plane_region:" + str(key),
                close(found.get("area"), wanted["area"])
                and found.get("boundary") == wanted["boundary"],
                expected=wanted,
                observed=found,
            )
        )
    return checks


def shell_intent(request, before):
    if (
        request.get("units") != "mm"
        or request.get("side", "inside") != "inside"
        or len(request.get("remove", [])) != 1
    ):
        raise Error(
            "E_UNSUPPORTED", "bounded shell supports mm, inward thickness and one explicit top face"
        )
    name = before["model"]["model"]
    target = before["parts"][name]
    constructors = [
        f
        for f in target["features"]
        if f.get("visible") is True
        and f["type"] not in ("FEATTYPE_DATUM_PLANE", "FEATTYPE_DATUM_AXIS", "FEATTYPE_COORD_SYS")
    ]
    if (
        len(constructors) != 1
        or constructors[0]["type"] != "FEATTYPE_PROTRUSION"
        or constructors[0]["status"] != "FEAT_ACTIVE"
        or target["relations"]
    ):
        raise Error(
            "E_UNSUPPORTED",
            "bounded shell requires one editable prismatic protrusion without relations",
        )
    actual, bounds = regions(before["geometry"])
    checks = shape_checks(before["geometry"], bounds)
    if not all(c["passed"] for c in checks):
        raise Error(
            "E_UNSUPPORTED", "current solid is not the proven rectangular prism", {"checks": checks}
        )
    lo, hi = bounds
    lengths = [b - a for a, b in zip(lo, hi, strict=True)]
    thickness = request["thickness"]
    if thickness <= 10 * TOL:
        raise Error(
            "E_UNSUPPORTED",
            "thickness is below this bounded geometry proof resolution",
            {
                "minimum_exclusive_mm": 10 * TOL,
                "meaning": "verification resolution, not manufacturing tolerance",
            },
        )
    if thickness >= min(lengths[0] / 2, lengths[1] / 2, lengths[2]) - TOL:
        raise Error(
            "E_VALIDATION",
            "wall thickness leaves no proven rectangular interior",
            {
                "thickness": thickness,
                "strict_upper_bound_mm": min(lengths[0] / 2, lengths[1] / 2, lengths[2]),
            },
        )
    top = actual.get((2, 1, hi[2]), {})
    if top.get("faces") != request["remove"]:
        raise Error(
            "E_UNSUPPORTED",
            "select the single complete top face at maximum model Z",
            {
                "requested": request["remove"],
                "supported_top_faces": top.get("faces", []),
                "opening_normal": [0, 0, 1],
                "opening_z_mm": hi[2],
                "_untrusted": ["requested", "supported_top_faces"],
            },
        )
    volume = math.prod(lengths)
    if not close((before["model"].get("mass_properties") or {}).get("volume"), volume):
        raise Error("E_VERIFY_INCOMPLETE", "native prism volume contradicts its complete boundary")
    return {
        "profile": PROFILE,
        "name_intent": building.feature_name_intent(request),
        "bounds_mm": bounds,
        "body_id": before["geometry"]["body"]["id"],
        "thickness_mm": thickness,
        "remove": request["remove"],
        "side": "inside",
        "opening_normal": [0, 0, 1],
        "opening_z_mm": hi[2],
        "expected_volume_mm3": volume
        - (lengths[0] - 2 * thickness) * (lengths[1] - 2 * thickness) * (lengths[2] - thickness),
    }


def protected_checks(before, after):
    """Shared observation-only protection for the bounded native prism operations."""
    name = before["model"]["model"]
    previous = before["parts"][name]
    current = after["parts"][name]
    checks = [
        engine.check("saved_versions_unchanged", before["files"] == after["files"]),
        engine.check(
            "unrelated_models_unchanged",
            all(v == after["parts"].get(k) for k, v in before["parts"].items() if k != name),
        ),
        engine.check(
            "session_models_and_windows_preserved",
            {r["model"] for r in before["session"]["models"]}
            == {r["model"] for r in after["session"]["models"]}
            and {k: v for k, v in before["session"].items() if k != "models"}
            == {k: v for k, v in after["session"].items() if k != "models"},
        ),
        engine.check(
            "protected_parameters_relations",
            previous["parameters"] == current["parameters"]
            and previous["relations"] == current["relations"],
        ),
    ]
    for key in (
        "units",
        "origin",
        "origin_readback",
        "family",
        "common_name",
        "material",
        "tolerance_standard",
        "tolerance_class",
    ):
        checks.append(
            engine.check(
                "protected_model_attribute:" + key,
                before["model"].get(key) == after["model"].get(key),
            )
        )
    original_dims = {d["id"]: d for d in previous["dimensions"]["dimensions"]}
    current_dims = {d["id"]: d for d in current["dimensions"]["dimensions"]}
    checks.append(
        engine.check(
            "original_dimensions_and_tolerances_preserved",
            all(v == current_dims.get(k) for k, v in original_dims.items()),
        )
    )
    return checks


def verify(before, intent, after, feature_id):
    name = before["model"]["model"]
    previous = before["parts"][name]
    current = after["parts"][name]
    old = {f["id"]: f for f in previous["features"]}
    new = {f["id"]: f for f in current["features"]}
    definition = after["definitions"].get(feature_id) or {}
    checks = [
        engine.check(
            "exactly_one_shell_feature_added",
            set(new) - set(old) == {feature_id}
            and new.get(feature_id, {}).get("type") == "FEATTYPE_SHELL"
            and new.get(feature_id, {}).get("status") == "FEAT_ACTIVE",
        ),
        engine.check(
            "existing_feature_identity_status_preserved",
            all(
                all(
                    f.get(k) == new.get(i, {}).get(k)
                    for k in ("id", "name", "type", "status", "visible")
                )
                for i, f in old.items()
            ),
        ),
        engine.check(
            "native_shell_definition",
            definition.get("complete") is True
            and close(definition.get("thickness"), intent["thickness_mm"])
            and definition.get("side") == "inside"
            and definition.get("removed") == intent["remove"]
            and str(definition.get("body_id")) == str(intent["body_id"])
            and definition.get("local_thickness_count") == 0
            and definition.get("excluded_instruction_count") == 0,
            expected=intent,
            observed=definition,
        ),
        engine.check(
            "same_active_body", after["geometry"].get("body") == before["geometry"].get("body")
        ),
        engine.check(
            "native_shell_volume",
            close(
                (after["model"].get("mass_properties") or {}).get("volume"),
                intent["expected_volume_mm3"],
            ),
            expected=intent["expected_volume_mm3"],
            observed=(after["model"].get("mass_properties") or {}).get("volume"),
        ),
    ]
    checks += building.feature_readback_checks(
        previous["features"],
        current["features"],
        feature_id,
        "FEATTYPE_SHELL",
        intent.get("name_intent"),
    )
    checks += protected_checks(before, after)
    checks += shape_checks(after["geometry"], intent["bounds_mm"], intent["thickness_mm"])
    return checks


def checked_plan(client, plan, request, options=None):
    before = snapshot(client, plan.target)
    if (options or {}).get("confirm"):
        old = operations.get(safety.token_operation(options["confirm"]))
        retained = (
            old.get("driver_plan", {})
            .get("base_snapshot", {})
            .get("extensions", {})
            .get("creo", {})
            .get("observation", {})
        )
        if digest(retained.get("prismatic_before")) != digest(before):
            raise Error(
                "E_CONFLICT",
                "shell model, geometry or protected state changed after preview",
                {"conflict": "state_drift", "dispatch_state": "not_started"},
            )
    intent = shell_intent(request, before)
    plan.binding |= {"prismatic_before": before, "prismatic_intent": intent}
    plan.preview["shell_intent"] = intent
    plan.preview["limits"] = [
        "mm, one standalone rectangular protrusion, one top face, uniform inward walls",
        "complete planar body/contours required; no closed/outward/multiple-body shell",
        "shape checks are not manufacturing approval; leaf command only",
    ]
    plan.before = before
    plan.observe = lambda c: snapshot(c, plan.target)
    previous = plan.verify

    def check(c, data):
        result, verification = previous(c, data)
        after = snapshot(c, plan.target)
        checks = verify(before, intent, after, str(data["feature"]["id"]))
        verification["checks"].extend(checks)
        result["shell_readback"] = {
            "definition": after["definitions"],
            "geometry": after["geometry"],
        }
        if engine.verification_status(verification) == "passed":
            plan.verified_observation = deepcopy(after)
        return result, verification

    plan.verify = check
    return plan


def recovery(client, run):
    plan = run["driver_plan"]
    retained = plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
    before, intent = retained.get("prismatic_before"), retained.get("prismatic_intent")
    if not before or not intent or intent.get("profile") != PROFILE:
        raise Error("E_VERIFY_INCOMPLETE", "frozen shell boundary/intent is unavailable")
    building.retained_feature_name_intent(run, intent)
    if client.health()["service_instance_id"] != plan["target"]["instance_id"]:
        raise Error(
            "E_VERIFY_INCOMPLETE", "another instance cannot prove the retained shell outcome"
        )
    after = snapshot(client, run["target"])
    old_ids = {f["id"] for f in before["parts"][run["target"]]["features"]}
    added = [f for f in after["parts"][run["target"]]["features"] if f["id"] not in old_ids]
    checks = [
        engine.check(
            "one_identified_shell", len(added) == 1 and added[0]["type"] == "FEATTYPE_SHELL"
        )
    ]
    if checks[0]["passed"]:
        checks += verify(before, intent, after, added[0]["id"])
    stable = digest(after) == digest(snapshot(client, run["target"]))
    checks.append(engine.check("independent_shell_readback_stable", stable))
    accepted = all(c["passed"] for c in checks)
    complete = (
        len(added) == 1 and (after["definitions"].get(added[0]["id"]) or {}).get("complete") is True
    )
    return {
        "accepted": accepted,
        "checks": checks,
        "intent": intent,
        "current": after,
        "can_register": []
        if not stable
        else ["not_applied"]
        if digest(before) == digest(after)
        else ["applied"]
        if accepted
        else ["partial"]
        if complete
        else [],
        "coverage": "frozen feature name, removed face/thickness/body, complete current "
        "planar regions and protected state; no replay",
    }


def retained_evidence_sufficient(run, proof):
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, intent = retained.get("prismatic_before"), retained.get("prismatic_intent")
    if not before or not intent or intent != proof.get("intent"):
        raise Error("E_VERIFY_INCOMPLETE", "retained shell proof lacks its frozen intent")
    building.retained_feature_name_intent(run, intent)
    after = proof.get("current") or {}
    old = {f["id"] for f in before["parts"][run["target"]]["features"]}
    new = [f for f in after["parts"][run["target"]]["features"] if f["id"] not in old]
    accepted = (
        len(new) == 1
        and new[0]["type"] == "FEATTYPE_SHELL"
        and all(c["passed"] for c in verify(before, intent, after, new[0]["id"]))
    )
    if proof.get("accepted") is not accepted:
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained shell conclusion lacks complete current geometry proof"
        )
