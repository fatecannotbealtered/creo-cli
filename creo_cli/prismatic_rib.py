"""One straight transverse rib in a proven rectangular housing; observation never edits."""

import math
from copy import deepcopy

from . import building, engine, operations, prismatic, safety
from .core import Error, digest

COMMANDS = ("feature rib",)
PROFILE = "rectangular-housing-rib-v1"


def canonical_request(client, name, request):
    # Keep the original request until the preview has displayed every resolved decision.
    return deepcopy(request)


def snapshot(client, name):
    offered = (client.health().get("capabilities") or {}).get("prismatic_rib_readback")
    client.require_capability(
        "prismatic_rib_readback", offered if type(offered) is int and offered in (2, 3) else 3
    )
    result = prismatic.snapshot(client, name)
    result["reference_geometry"] = engine.normalize(client.op("geometry.list", {"model": name}))
    result["sections"] = {}
    result["auxiliary"] = {}
    refs = result["reference_geometry"]
    if refs.get("model") != name or refs.get("units") != result["model"].get("units"):
        raise Error("E_VERIFY_INCOMPLETE", "rib references identify a foreign model or units")
    if not isinstance(refs.get("items"), list) or any(
        not isinstance(row, dict) or row.get("error") for row in refs["items"]
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete rib reference inventory required")
    for feature in result["parts"][name]["features"]:
        if feature["type"] == "FEATTYPE_RIB":
            row = engine.normalize(
                client.op("feature.show", {"model": name, "feature": feature["id"]})
            )
            result["definitions"][feature["id"]] = row.get("native_definition")
            result["sections"][feature["id"]] = row.get("native_section_readback")
            result["auxiliary"][feature["id"]] = row.get("native_auxiliary_datums")
    return result


def _same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return prismatic.close(a, b)


def _world(frame, uv):
    return [frame["origin"][i] + uv[0] * frame["x"][i] + uv[1] * frame["y"][i] for i in range(3)]


def _one_body(state):
    bodies = state["model"].get("bodies")
    body = state["geometry"].get("body") or {}
    return (
        isinstance(bodies, list)
        and len(bodies) == 1
        and isinstance(bodies[0], dict)
        and not bodies[0].get("error")
        and bodies[0].get("state") == "BODY_STATE_ACTIVE"
        and str(bodies[0].get("id")) == str(body.get("id"))
    )


def intent(request, before, frame):
    """Infer only the proven wall intersections and the unique direction toward the floor."""
    name = before["model"]["model"]
    part = before["parts"][name]
    constructors = [
        f
        for f in part["features"]
        if f.get("visible") is True
        and f["type"] not in ("FEATTYPE_DATUM_PLANE", "FEATTYPE_DATUM_AXIS", "FEATTYPE_COORD_SYS")
    ]
    if (
        request.get("units") != "mm"
        or not _one_body(before)
        or request.get("side", "symmetric") != "symmetric"
        or len(request["sketch"]["points"]) != 2
        or part["relations"]
        or [f["type"] for f in constructors] != ["FEATTYPE_PROTRUSION", "FEATTYPE_SHELL"]
        or any(f["status"] != "FEAT_ACTIVE" for f in constructors)
    ):
        raise Error(
            "E_UNSUPPORTED",
            "rib requires one independent mm rectangular housing, one line and symmetric thickness",
        )
    if (
        not frame
        or not _same(frame.get("x"), [1, 0, 0])
        or not _same(frame.get("y"), [0, 0, -1])
        or not _same(frame.get("normal"), [0, 1, 0])
        or not isinstance(frame.get("origin"), list)
        or not _same([frame["origin"][0], frame["origin"][2]], [0, 0])
    ):
        raise Error(
            "E_UNSUPPORTED", "rib uses an observed XZ datum frame, +X right, -Z up and +Y normal"
        )
    shell_id = constructors[1]["id"]
    shell = before["definitions"].get(shell_id) or {}
    wall = shell.get("thickness")
    regions, bounds = prismatic.regions(before["geometry"])
    if (
        shell.get("complete") is not True
        or shell.get("kind") != "shell"
        or shell.get("side") != "inside"
        or not isinstance(wall, (int, float))
        or shell.get("local_thickness_count") != 0
        or shell.get("excluded_instruction_count") != 0
        or str(shell.get("body_id")) != str(before["geometry"]["body"]["id"])
        or not all(c["passed"] for c in prismatic.shape_checks(before["geometry"], bounds, wall))
    ):
        raise Error(
            "E_UNSUPPORTED",
            "current complete body and native definition do not prove the rectangular housing",
        )
    lo, hi = bounds
    a, b, c, d, floor = lo[0] + wall, hi[0] - wall, lo[1] + wall, hi[1] - wall, lo[2] + wall
    thickness = request["thickness"]
    y = frame["origin"][1]
    if (
        not float(thickness).is_integer()
        or thickness <= 0
        or y - thickness / 2 <= c + prismatic.TOL
        or y + thickness / 2 >= d - prismatic.TOL
    ):
        raise Error(
            "E_UNSUPPORTED", "rib requires positive whole-mm thickness strictly inside both Y walls"
        )
    original = [_world(frame, p) for p in request["sketch"]["points"]]
    if (
        not _same(original[0][1:], original[1][1:])
        or abs(original[1][0] - original[0][0]) <= prismatic.TOL
        or not floor + prismatic.TOL < original[0][2] < hi[2] - prismatic.TOL
        or any(p[0] < a - prismatic.TOL or p[0] > b + prismatic.TOL for p in original)
    ):
        raise Error(
            "E_UNSUPPORTED",
            "rib needs a horizontal line inside the cavity above the floor and below the opening",
        )
    forward = original[1][0] > original[0][0]
    fill = "left" if forward else "right"
    if request.get("fill", fill) != fill:
        raise Error(
            "E_UNSUPPORTED",
            "requested fill points away from the proven floor; no native attempt is made",
        )
    actual = [[a if forward else b, y, original[0][2]], [b if forward else a, y, original[0][2]]]
    q = deepcopy(request)
    q["side"], q["fill"] = "symmetric", fill
    q["sketch"]["points"] = [[p[0], -p[2]] for p in actual]
    q["sketch"].setdefault("orient", "right")
    found = building.resolve_references(
        before["reference_geometry"]["items"], [q["sketch"]["plane"], q["sketch"]["orient_ref"]]
    )
    plane, orient = [found[q["sketch"][k]] for k in ("plane", "orient_ref")]
    if (
        plane.get("kind") != "datum_plane"
        or orient.get("kind") != "datum_plane"
        or not _same(plane.get("normal"), [0, 1, 0])
        or not _same(orient.get("normal"), [1, 0, 0])
    ):
        raise Error(
            "E_UNSUPPORTED", "rib needs actual datum-plane identities with the declared normals"
        )
    reference_names = request["sketch"].get("references", ["RIGHT", "FRONT"])
    reference_rows = building.resolve_references(
        before["reference_geometry"]["items"], reference_names
    )
    references = []
    for key in reference_names:
        row = reference_rows[key]
        if (
            row.get("kind") != "datum_plane"
            or row.get("id") is None
            or not isinstance(row.get("ref"), str)
        ):
            raise Error(
                "E_UNSUPPORTED", "rib projection references require actual datum identities"
            )
        references.append(
            {
                "ref": row["ref"],
                "id": str(row["id"]),
                "model": name[:-4],
                "model_type": "part",
                "item_type": "surface",
                "name": row["ref"],
            }
        )
    q["sketch"]["references"] = [r["ref"] for r in references]
    associations = {}
    for key, region in (
        ("left_wall", (0, 1, round(a, 6))),
        ("right_wall", (0, -1, round(b, 6))),
        ("floor", (2, 1, round(floor, 6))),
    ):
        faces = regions.get(region, {}).get("faces", [])
        if len(faces) != 1:
            raise Error(
                "E_UNSUPPORTED",
                "rib attachment requires one complete native face per wall and floor",
            )
        associations[key] = faces[0]
    cavity = (b - a) * (d - c) * (hi[2] - floor)
    volume = math.prod(y - x for x, y in zip(lo, hi, strict=True)) - cavity
    if not prismatic.close((before["model"].get("mass_properties") or {}).get("volume"), volume):
        raise Error("E_VERIFY_INCOMPLETE", "housing volume contradicts its complete boundary")
    return {
        "profile": PROFILE,
        "name_intent": building.feature_name_intent(request),
        "original_request": deepcopy(request),
        "actual_request": q,
        "frame": frame,
        "original_endpoints_mm": original,
        "actual_endpoints_mm": actual,
        "associations": associations,
        "fill": fill,
        "fill_direction": [0, 0, -1],
        "fill_policy": "requested" if "fill" in request else "unique_proven_floor_direction",
        "plane": plane["ref"],
        "orient_ref": orient["ref"],
        "references": references,
        "attachment_projections": [
            {
                "ref": associations[k],
                "id": associations[k].split(":", 1)[1],
                "model": name[:-4],
                "model_type": "part",
                "item_type": "surface",
            }
            for k in ("left_wall", "right_wall")
        ],
        "native_projection_policy": {
            "required_datums": 2,
            "wall_auxiliaries": 2,
            "allowed_wall_roles": ["projection", "construction"],
            "profile_lines": 1,
        },
        "native_auxiliary_policy": {
            "max_count": 1,
            "type": "FEATTYPE_DATUM_PLANE",
            "visible": False,
            "parent_refs": [plane["ref"], orient["ref"]],
            "same_plane": True,
            "sole_child": "new_rib",
        },
        "thickness_mm": thickness,
        "bounds_mm": bounds,
        "shell_thickness_mm": wall,
        "shell_id": shell_id,
        "shell_definition": shell,
        "body": before["geometry"]["body"],
        "expected_volume_mm3": volume + (b - a) * thickness * (actual[0][2] - floor),
    }


def expected_regions(wanted, thickness=None):
    """Analytic plane polygons, independent of the native tessellation/face partition."""
    bounds, wall = wanted["bounds_mm"], wanted["shell_thickness_mm"]
    result = prismatic.expected_regions(bounds, wall)
    lo, hi = bounds
    a, b, c, d, floor = lo[0] + wall, hi[0] - wall, lo[1] + wall, hi[1] - wall, lo[2] + wall
    _, y, top = wanted["actual_endpoints_mm"][0]
    t = wanted["thickness_mm"] if thickness is None else thickness
    p, q = y - t / 2, y + t / 2

    def region(axis, sign, coordinate, polygons):
        segments, area = [], 0
        for polygon in polygons:
            segments.extend(zip(polygon, polygon[1:] + polygon[:1], strict=True))
            u, v = [i for i in range(3) if i != axis]
            area += (
                abs(
                    sum(
                        x[u] * z[v] - z[u] * x[v]
                        for x, z in zip(polygon, polygon[1:] + polygon[:1], strict=True)
                    )
                )
                / 2
            )
        result[(axis, sign, round(coordinate, 6))] = {
            "boundary": prismatic._boundary(segments),
            "area": area,
        }

    region(
        2,
        1,
        floor,
        [
            [[a, c, floor], [b, c, floor], [b, p, floor], [a, p, floor]],
            [[a, q, floor], [b, q, floor], [b, d, floor], [a, d, floor]],
        ],
    )
    for x, sign in ((a, 1), (b, -1)):
        region(
            0,
            sign,
            x,
            [
                [
                    [x, c, floor],
                    [x, p, floor],
                    [x, p, top],
                    [x, q, top],
                    [x, q, floor],
                    [x, d, floor],
                    [x, d, hi[2]],
                    [x, c, hi[2]],
                ]
            ],
        )
    for v, sign in ((p, -1), (q, 1)):
        region(1, sign, v, [[[a, v, floor], [b, v, floor], [b, v, top], [a, v, top]]])
    region(2, 1, top, [[[a, p, top], [b, p, top], [b, q, top], [a, q, top]]])
    return result


def shape_checks(data, wanted, thickness=None):
    actual, bounds = prismatic.regions(data)
    expected = expected_regions(wanted, thickness)
    checks = [
        engine.check("exact_housing_and_rib_oriented_regions", set(actual) == set(expected)),
        engine.check("protected_outer_native_boundary", bounds == wanted["bounds_mm"]),
    ]
    for key, target in expected.items():
        found = actual.get(key, {})
        checks.append(
            engine.check(
                "rib_plane_region:" + str(key),
                prismatic.close(found.get("area"), target["area"])
                and found.get("boundary") == target["boundary"],
                expected=target,
                observed=found,
            )
        )
    return checks


def _wall_line(pair, wanted):
    lo, hi = wanted["bounds_mm"]
    wall = wanted["shell_thickness_mm"]
    y = wanted["frame"]["origin"][1]
    for label, x in (("left_wall", lo[0] + wall), ("right_wall", hi[0] - wall)):
        if (
            all(prismatic.close(p[0], x) and prismatic.close(p[1], y) for p in pair)
            and abs(pair[1][2] - pair[0][2]) > prismatic.TOL
        ):
            return label
    return None


def _section_matches(raw, wanted, geometry):
    try:
        if (
            not isinstance(raw, dict)
            or raw.get("returned") != 0
            or not wanted.get("native_projection_policy")
        ):
            return False
        values = [float(v) for v in raw["location"].split()]
        if len(values) != 12 or not all(math.isfinite(v) for v in values):
            return False
        frame = {"x": values[:3], "y": values[3:6], "normal": values[6:9], "origin": values[9:]}
        if not all(_same(frame[k], wanted["frame"][k]) for k in ("x", "y", "normal")):
            return False
        roles = {}
        for row in raw["section_entity_roles"].split(";"):
            fields = row.split()
            if (
                len(fields) != 3
                or fields[0] in roles
                or fields[1] not in ("0", "1")
                or fields[2] not in ("0", "1")
            ):
                return False
            roles[fields[0]] = (fields[1] == "1", fields[2] == "1")
        entities, profile, projected, wall_helpers = {}, [], set(), []
        for row in raw["entities_read"].split(";"):
            fields = row.split()
            if not fields:
                continue
            if len(fields) < 6 or not fields[0].startswith("#") or fields[0] in entities:
                return False
            ident, kind = fields[:2]
            if ident not in roles or kind not in ("L", "R"):
                return False
            xy = [float(v) for v in fields[2:6]]
            if not all(math.isfinite(v) for v in xy):
                return False
            pair = [_world(frame, xy[:2]), _world(frame, xy[2:])]
            entities[ident] = pair
            projection, construction = roles[ident]
            if (kind == "R") != projection:
                return False
            if projection:
                projected.add(ident)
            elif construction:
                label = _wall_line(pair, wanted)
                if label is None:
                    return False
                wall_helpers.append(label)
            else:
                profile.append(pair)
        if (
            raw.get("projection_refs_complete") != 1
            or raw.get("section_entity_roles_complete") != 1
            or raw.get("section_entity_role_count") != len(entities)
            or raw.get("section_entity_count") != len(entities)
            or set(roles) != set(entities)
            or len(entities) != 5
        ):
            return False

        def identity(r):
            return (str(r["id"]), r["item_type"], r["model"].casefold(), r["model_type"])

        required = {identity(r) for r in wanted["references"]}
        attachments = {
            identity(r): label
            for r, label in zip(
                wanted["attachment_projections"], ("left_wall", "right_wall"), strict=True
            )
        }
        seen, found, identities = set(), set(), []
        physical = {row["ref"] for row in geometry["items"] if row["kind"] == "surface"}
        for text in raw["projection_refs"].split(";"):
            fields = text.split()
            if len(fields) != 9 or fields[0] in found:
                return False
            (
                entity,
                ident,
                kind,
                model,
                model_type,
                display_name,
                model_id,
                same_owner,
                path_depth,
            ) = fields
            if (
                entity not in projected
                or int(model_id) < 0
                or same_owner != "1"
                or path_depth != "0"
            ):
                return False
            key = (ident, kind, model.casefold(), model_type)
            if key in seen or key not in required | set(attachments):
                return False
            seen.add(key)
            found.add(entity)
            identities.append(key)
            if key in attachments:
                label = attachments[key]
                if (
                    wanted["associations"][label] not in physical
                    or _wall_line(entities[entity], wanted) != label
                ):
                    return False
                wall_helpers.append(label)
        return (
            found == projected
            and raw.get("projection_ref_count") == len(found)
            and required.issubset(set(identities))
            and sorted(wall_helpers) == ["left_wall", "right_wall"]
            and len(profile) == 1
            and _same(profile[0], wanted["actual_endpoints_mm"])
        )
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def _auxiliary_checks(before, wanted, after, feature_id):
    name = before["model"]["model"]
    old = {f["id"] for f in before["parts"][name]["features"]}
    current = {f["id"]: f for f in after["parts"][name]["features"]}
    policy = wanted.get("native_auxiliary_policy")
    report = (after.get("auxiliary") or {}).get(feature_id) or {}
    complete = (
        isinstance(policy, dict)
        and report.get("complete") is True
        and str(report.get("rib_id")) == str(feature_id)
        and isinstance(report.get("items"), list)
    )
    candidates = []
    if complete:
        candidates = [row for row in report["items"] if str(row.get("id")) not in old]
        complete = len({str(row.get("id")) for row in report["items"]}) == len(report["items"])
    support = set()
    valid = complete and len(candidates) <= policy["max_count"]
    parent_ids = {
        f["id"]
        for f in before["parts"][name]["features"]
        if (f.get("name") or "").casefold()
        in {ref.casefold() for ref in (policy or {}).get("parent_refs", [])}
    }
    physical = {g["id"] for g in after["geometry"]["items"] if g["kind"] == "surface"}
    for row in candidates:
        ident = str(row.get("id"))
        surface = row.get("surface") or {}
        actual = current.get(ident, {})
        normal, origin = surface.get("normal"), surface.get("origin")
        plane_ok = (
            isinstance(normal, list)
            and isinstance(origin, list)
            and len(normal) == len(origin) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in normal + origin)
            and prismatic.close(sum(v * v for v in normal), 1)
            and any(
                all(
                    prismatic.close(a, sign * b)
                    for a, b in zip(normal, wanted["frame"]["normal"], strict=True)
                )
                for sign in (-1, 1)
            )
            and prismatic.close(
                sum(
                    (a - b) * n
                    for a, b, n in zip(
                        origin, wanted["frame"]["origin"], wanted["frame"]["normal"], strict=True
                    )
                ),
                0,
            )
        )
        valid = valid and (
            row.get("type") == "FEATTYPE_DATUM_PLANE"
            and row.get("visible") is False
            and row.get("status") == "FEAT_ACTIVE"
            and all(
                row.get(k) == actual.get(k) for k in ("id", "name", "type", "status", "visible")
            )
            and {str(i) for i in row.get("parents", [])} == parent_ids
            and len(parent_ids) == 2
            and [str(i) for i in row.get("children", [])] == [str(feature_id)]
            and surface.get("type") == "plane"
            and surface.get("id") is not None
            and str(surface["id"]) not in physical
            and plane_ok
        )
        support.add(ident)
    return [
        engine.check("frozen_native_auxiliary_policy", isinstance(policy, dict)),
        engine.check(
            "bounded_auxiliary_datum_dependencies_and_plane", bool(valid), observed=report
        ),
        engine.check(
            "exactly_one_rib_added", complete and set(current) - old == {str(feature_id)} | support
        ),
    ]


def _datums_preserved(before, after, feature_id=None, *, partial=False):
    def rows(state):
        return [
            r
            for r in state["reference_geometry"]["items"]
            if r.get("kind") not in ("surface", "edge")
        ]

    old_rows, new_rows = rows(before), rows(after)
    old = {(r.get("kind"), str(r.get("id"))): r for r in old_rows}
    new = {(r.get("kind"), str(r.get("id"))): r for r in new_rows}
    if (
        len(old) != len(old_rows)
        or len(new) != len(new_rows)
        or not all(row == new.get(key) for key, row in old.items())
    ):
        return False
    if partial:
        return True  # Extra effects remain partial, never an applied conclusion.
    report = (after.get("auxiliary") or {}).get(feature_id) or {}
    name = before["model"]["model"]
    old_ids = {f["id"] for f in before["parts"][name]["features"]}
    allowed = {
        str(r["surface"]["id"]): r
        for r in report.get("items", [])
        if str(r.get("id")) not in old_ids
        and isinstance(r.get("surface"), dict)
        and r["surface"].get("id") is not None
    }
    for key in set(new) - set(old):
        row = new[key]
        support = allowed.get(str(row.get("id"))) or {}
        if (
            row.get("kind") != "datum_plane"
            or row.get("type") != "plane"
            or str((row.get("feature") or {}).get("id")) != str(support.get("id"))
            or not _same(row.get("normal"), (support.get("surface") or {}).get("normal"))
        ):
            return False
    return True


def verify(before, wanted, after, feature_id):
    name = before["model"]["model"]
    previous, current = before["parts"][name], after["parts"][name]
    old = {f["id"]: f for f in previous["features"]}
    new = {f["id"]: f for f in current["features"]}
    definition = after["definitions"].get(feature_id) or {}
    dimension = definition.get("thickness_dimension") or {}
    dims = current["dimensions"]["dimensions"]
    matches = [d for d in dims if str(d.get("id")) == str(dimension.get("id"))]
    original_dim_ids = {str(d["id"]) for d in previous["dimensions"]["dimensions"]}

    checks = building.feature_readback_checks(
        previous["features"], current["features"], feature_id, "FEATTYPE_RIB", wanted["name_intent"]
    )
    checks += [
        engine.check(
            "original_feature_identities_preserved",
            all(
                all(
                    f.get(k) == new.get(i, {}).get(k)
                    for k in ("id", "name", "type", "status", "visible")
                )
                for i, f in old.items()
            ),
        ),
        engine.check("same_active_native_body", after["geometry"].get("body") == wanted["body"]),
        engine.check("single_native_body_inventory", _one_body(after)),
        engine.check(
            "original_datum_geometry_preserved", _datums_preserved(before, after, feature_id)
        ),
        engine.check(
            "original_shell_definition_preserved",
            after["definitions"].get(wanted["shell_id"]) == wanted["shell_definition"],
        ),
        engine.check(
            "native_rib_definition",
            definition.get("complete") is True
            and definition.get("kind") == "rib"
            and definition.get("form") == "extrude"
            and definition.get("body_use") == "selected"
            and str(definition.get("body_id")) == str(wanted["body"]["id"])
            and prismatic.close(definition.get("thickness"), wanted["thickness_mm"])
            and definition.get("side") == "symmetric"
            and definition.get("fill") == wanted["fill"]
            and definition.get("plane") == wanted["plane"]
            and definition.get("orient_ref") == wanted["orient_ref"]
            and definition.get("plane_view_dir") == 1
            and definition.get("orient") == "right",
            expected=wanted,
            observed=definition,
        ),
        engine.check(
            "native_rib_thickness_dimension",
            len(matches) == 1
            and str(dimension.get("id")) not in original_dim_ids
            and str((matches[0].get("feature") or {}).get("id")) == str(feature_id)
            and matches[0].get("name") == dimension.get("name")
            and matches[0].get("type") == "linear"
            and matches[0].get("units") == "mm"
            and matches[0].get("reference") is False
            and matches[0].get("relation_driven") is False
            and matches[0].get("in_sketch") is False
            and prismatic.close(matches[0].get("value"), wanted["thickness_mm"])
            and prismatic.close(dimension.get("value"), wanted["thickness_mm"]),
            observed=dimension,
        ),
        engine.check(
            "native_rib_section_position_and_endpoints",
            _section_matches(after["sections"].get(feature_id), wanted, after["geometry"]),
        ),
        engine.check(
            "native_housing_and_rib_volume",
            prismatic.close(
                (after["model"].get("mass_properties") or {}).get("volume"),
                wanted["expected_volume_mm3"],
            ),
        ),
    ]
    return (
        checks
        + _auxiliary_checks(before, wanted, after, feature_id)
        + prismatic.protected_checks(before, after)
        + shape_checks(after["geometry"], wanted)
    )


def checked_plan(client, plan, request, options=None):
    client.require_capability("prismatic_rib_readback", 3)
    before = snapshot(client, plan.target)
    if (options or {}).get("confirm"):
        run = operations.get(safety.token_operation(options["confirm"]))
        retained = (
            run.get("driver_plan", {})
            .get("base_snapshot", {})
            .get("extensions", {})
            .get("creo", {})
            .get("observation", {})
        )
        if digest(retained.get("rib_before")) != digest(before):
            raise Error(
                "E_CONFLICT",
                "rib geometry, references or protected state changed after preview",
                {"conflict": "state_drift", "dispatch_state": "not_started"},
            )
    wanted = intent(request, before, plan.preview["sketch"]["frame"])
    plan.request = {k: v for k, v in wanted["actual_request"].items() if k != "units"} | {
        "model": plan.target
    }
    plan.binding |= {"rib_before": before, "rib_intent": wanted}
    plan.preview["rib_intent"] = wanted
    plan.preview["sketch"]["points"] = wanted["actual_request"]["sketch"]["points"]
    plan.preview["sketch"]["chain_in_model"] = wanted["actual_endpoints_mm"]
    plan.preview["sketch"]["chain_length"] = math.dist(*wanted["actual_endpoints_mm"])
    plan.preview["fill"] = wanted["fill"]
    plan.preview["ends_carried"] = [
        {"end": which, "asked": old, "drawn": new, "associated_face": wanted["associations"][wall]}
        for which, old, new, wall in zip(
            ("first", "last"),
            request["sketch"]["points"],
            wanted["actual_request"]["sketch"]["points"],
            ("left_wall", "right_wall")
            if wanted["fill"] == "left"
            else ("right_wall", "left_wall"),
            strict=True,
        )
    ]
    plan.preview["limits"] = [
        "one proven independent mm housing; one horizontal line, symmetric whole-mm thickness",
        "unique floor fill and actual wall intersections frozen before one native attempt",
        "complete connected planar body and native rib/section proof; no workflow or replay",
    ]
    plan.before = before
    plan.observe = lambda c: snapshot(c, plan.target)
    previous = plan.verify

    def check(c, data):
        result, verification = previous(c, data)
        after = snapshot(c, plan.target)
        verification["checks"].extend(verify(before, wanted, after, str(data["feature"]["id"])))
        result["rib_readback"] = {
            "definition": after["definitions"],
            "section": after["sections"],
            "geometry": after["geometry"],
        }
        if engine.verification_status(verification) == "passed":
            plan.verified_observation = deepcopy(after)
        return result, verification

    plan.verify = check
    return plan


def _retained(run):
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, wanted = retained.get("rib_before"), retained.get("rib_intent")
    if not before or not wanted or wanted.get("profile") != PROFILE:
        raise Error("E_VERIFY_INCOMPLETE", "frozen rib decisions and housing baseline unavailable")
    building.retained_feature_name_intent(run, wanted)
    request = {k: v for k, v in wanted["actual_request"].items() if k != "units"} | {
        "model": run["target"]
    }
    expected = intent(wanted["original_request"], before, wanted["frame"])
    additions = ("attachment_projections", "native_projection_policy", "native_auxiliary_policy")
    # Old plans are never upgraded to applied. Their exact original intent can
    # still support a conservative partial observation and preservation save.
    if not any(key in wanted for key in additions):
        expected = {k: v for k, v in expected.items() if k not in additions}
    if request != run["driver_plan"]["changes"][0].get("after") or expected != wanted:
        raise Error(
            "E_VERIFY_INCOMPLETE", "rib frozen decisions do not match original intent and baseline"
        )
    return before, wanted


def _new_ribs(before, after):
    name = before["model"]["model"]
    old = {f["id"] for f in before["parts"][name]["features"]}
    return [
        f
        for f in after["parts"][name]["features"]
        if f["id"] not in old and f["type"] == "FEATTYPE_RIB"
    ]


def _partial_body_proven(before, wanted, after):
    """Only a changed complete protected body is enough to register partial, never applied."""
    ribs = _new_ribs(before, after)
    if len(ribs) != 1 or not _one_body(after):
        return False
    name = before["model"]["model"]
    checks = building.feature_readback_checks(
        before["parts"][name]["features"],
        after["parts"][name]["features"],
        ribs[0]["id"],
        "FEATTYPE_RIB",
        wanted["name_intent"],
    )
    checks += prismatic.protected_checks(before, after)
    checks += shape_checks(after["geometry"], wanted)
    current = {f["id"]: f for f in after["parts"][name]["features"]}
    checks.append(
        engine.check(
            "original_feature_identities_preserved",
            all(
                all(
                    row.get(k) == current.get(row["id"], {}).get(k)
                    for k in ("id", "name", "type", "status", "visible")
                )
                for row in before["parts"][name]["features"]
            ),
        )
    )
    checks.append(
        engine.check(
            "original_datum_geometry_preserved", _datums_preserved(before, after, partial=True)
        )
    )
    return all(c["passed"] for c in checks)


def _outcomes(before, wanted, after, stable, accepted):
    ribs = _new_ribs(before, after)
    if not stable:
        return []
    if digest(before) == digest(after):
        return ["not_applied"]
    if accepted:
        return ["applied"]
    definition_read = (
        len(ribs) == 1 and (after["definitions"].get(ribs[0]["id"]) or {}).get("complete") is True
    )
    current_policy = all(
        key in wanted
        for key in ("native_auxiliary_policy", "native_projection_policy", "attachment_projections")
    )
    return (
        ["partial"]
        if ((current_policy and definition_read) or _partial_body_proven(before, wanted, after))
        else []
    )


def recovery(client, run):
    before, wanted = _retained(run)
    if client.health()["service_instance_id"] != run["driver_plan"]["target"]["instance_id"]:
        raise Error(
            "E_VERIFY_INCOMPLETE", "another instance cannot establish the retained rib outcome"
        )
    after = snapshot(client, run["target"])
    ribs = _new_ribs(before, after)
    checks = [engine.check("one_identified_rib", len(ribs) == 1)]
    if checks[0]["passed"]:
        checks += verify(before, wanted, after, ribs[0]["id"])
    stable = digest(after) == digest(snapshot(client, run["target"]))
    checks.append(engine.check("independent_rib_readback_stable", stable))
    accepted = all(c["passed"] for c in checks)
    return {
        "accepted": accepted,
        "checks": checks,
        "intent": wanted,
        "current": after,
        "can_register": _outcomes(before, wanted, after, stable, accepted),
        "coverage": "frozen original/resolved endpoints, native rib/name/thickness/fill/section, "
        "complete connected housing union and protection; no replay",
    }


def retained_evidence_sufficient(run, proof):
    before, wanted = _retained(run)
    if wanted != proof.get("intent"):
        raise Error("E_VERIFY_INCOMPLETE", "retained rib proof has another frozen intent")
    after = proof.get("current") or {}
    ribs = _new_ribs(before, after)
    accepted = len(ribs) == 1 and all(
        c["passed"] for c in verify(before, wanted, after, ribs[0]["id"])
    )
    stable = any(
        c.get("check") == "independent_rib_readback_stable" and c.get("passed") is True
        for c in proof.get("checks", [])
    )
    if proof.get("accepted") is not accepted or proof.get("can_register") != _outcomes(
        before, wanted, after, stable, accepted
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "retained rib conclusion lacks full independent geometry and identity proof",
        )
