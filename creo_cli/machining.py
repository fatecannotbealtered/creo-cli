"""Selected hole/round geometry checks. No synthetic cutting or alternate executor."""

import copy
import math

from . import building, engine
from .core import Error

TOL = 1e-6
HOLE_VOLUME_POLICY_V2 = {
    "mode": "bounded-total-v2",
    "version": 2,
    "units": "mm^3",
    "relative_tolerance": 1e-6,
    "absolute_floor": 1e-6,
    "hard_cap": 0.001,
}
HOLE_SOLID_PROTECTION_V1 = {
    "mode": "retained-solid-boundary-v1",
    "version": 1,
    "units": "mm",
    "identity": "same native physical surface and edge refs, ids and owners",
    "scope": "standalone non-family part; two planar ends and full-thickness planar/axial sides",
    "body_schema": {"fields": ["id", "name", "state"], "count": 1, "state": "BODY_STATE_ACTIVE"},
    "cap_area_comparison": {
        "units": "mm^2",
        "absolute_serialization_budget": 2e-9,
        "binary_ulps": 8,
        "hard_cap": 1e-6,
        "relative_tolerance": 0,
    },
}


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _volume(state):
    properties = state["model"].get("mass_properties")
    return properties.get("volume") if isinstance(properties, dict) else None


def _mm_volume_units(state):
    model = state["model"]
    units = model.get("units")
    properties = model.get("mass_properties")
    mass_units = properties.get("units") if isinstance(properties, dict) else None
    return (
        isinstance(units, dict)
        and units.get("length") == "mm"
        and isinstance(mass_units, dict)
        and mass_units.get("length") == "mm"
        and mass_units.get("volume") == "mm^3"
    )


def _hole_volume_policy(expected, before):
    """Absence means legacy; an explicit unsupported policy is never assigned defaults."""
    if not isinstance(expected, dict):
        raise Error("E_VERIFY_INCOMPLETE", "retained complete-hole evidence is malformed")
    if "volume_comparison" not in expected:
        return None
    policy = expected["volume_comparison"]
    if (
        not isinstance(policy, dict)
        or policy != HOLE_VOLUME_POLICY_V2
        or type(policy.get("version")) is not int
        or not _mm_volume_units(before)
        or expected.get("comparison_relative_tolerance") != policy["relative_tolerance"]
        or expected.get("comparison_absolute_tolerance") != policy["absolute_floor"]
        or expected.get("volume_unit_evidence") != before["model"]["mass_properties"]["units"]
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained hole volume policy is unsupported or incomplete"
        )
    return policy


def _freeze_hole_volume_policy(request, before, intent):
    expected = intent.get("complete_through_hole") if intent else None
    model_units = before["model"].get("units")
    if not expected or request.get("units") != "mm":
        return  # Existing/non-mm numerical policy is unchanged.
    if not isinstance(model_units, dict) or not model_units.get("length"):
        raise Error("E_VERIFY_INCOMPLETE", "native model length-unit evidence is incomplete")
    if model_units["length"] != "mm":
        return
    if not _mm_volume_units(before):
        raise Error(
            "E_VERIFY_INCOMPLETE", "native mass-properties mm^3 unit evidence is incomplete"
        )
    volume, removed = _volume(before), expected["removed_volume"]
    if not all(_finite_number(v) and v > 0 for v in (volume, removed)):
        raise Error(
            "E_VERIFY_INCOMPLETE", "complete-hole volume baseline is not finite and positive"
        )
    if removed >= volume:
        raise Error("E_UNSUPPORTED", "complete-hole removal must be smaller than baseline volume")
    policy = copy.deepcopy(HOLE_VOLUME_POLICY_V2)
    budget = min(
        max(policy["absolute_floor"], policy["relative_tolerance"] * abs(volume - removed)),
        policy["hard_cap"],
    )
    if removed <= budget:
        raise Error(
            "E_UNSUPPORTED",
            "intended hole removal cannot be resolved above the frozen volume budget",
            {
                "expected_removed": removed,
                "effective_budget": budget,
                "dispatch_state": "not_started",
            },
        )
    expected["volume_comparison"] = policy
    expected["volume_unit_evidence"] = copy.deepcopy(before["model"]["mass_properties"]["units"])


def _hole_volume_check(before, expected, after):
    policy = _hole_volume_policy(expected, before)
    if "removed_volume" not in expected:
        raise Error("E_VERIFY_INCOMPLETE", "retained complete-hole removal is missing")
    baseline, actual, intended = _volume(before), _volume(after), expected["removed_volume"]
    if policy is None:
        removed = baseline - actual
        return engine.check(
            "complete_hole_removed_volume",
            math.isclose(removed, intended, rel_tol=1e-6, abs_tol=TOL),
            expected=intended,
            observed=removed,
        )
    if not _mm_volume_units(after):
        raise Error("E_VERIFY_INCOMPLETE", "current native mass-properties volume units differ")
    values = {"before": baseline, "after": actual, "removed_intent": intended}
    invalid = [key for key, value in values.items() if not _finite_number(value) or value <= 0]
    valid = not invalid and intended < baseline
    expected_after = baseline - intended if valid else None
    removed = baseline - actual if _finite_number(baseline) and _finite_number(actual) else None
    residual = abs(actual - expected_after) if valid else None
    relative_budget = (
        max(
            policy["absolute_floor"],
            policy["relative_tolerance"] * max(abs(actual), abs(expected_after)),
        )
        if valid
        else None
    )
    effective_budget = min(relative_budget, policy["hard_cap"]) if valid else None
    relative_passed = valid and residual <= relative_budget
    cap_passed = valid and residual <= policy["hard_cap"]
    removal_resolved = valid and min(removed, intended) > effective_budget
    return engine.check(
        "complete_hole_removed_volume",
        relative_passed and cap_passed and removal_resolved,
        expected=intended if _finite_number(intended) else None,
        observed=removed,
        volume_policy=copy.deepcopy(policy),
        before_volume=baseline if _finite_number(baseline) else None,
        expected_after=expected_after,
        actual_after=actual if _finite_number(actual) else None,
        absolute_residual=residual,
        relative_budget=relative_budget,
        effective_budget=effective_budget,
        relative_passed=relative_passed,
        cap_passed=cap_passed,
        removal_resolved=removal_resolved,
        volume_inputs_valid=valid,
        invalid_volume_inputs=invalid,
        volume_units_source="model.show.mass_properties.units",
        volume_unit_evidence=copy.deepcopy(after["model"]["mass_properties"]["units"]),
    )


def _point(value):
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in value
        )
    )


def _physical_inventory(state):
    """Require readable physical identities and finite supported analytic geometry."""
    units = state["geometry"].get("units")
    if not isinstance(units, dict) or units.get("length") != "mm":
        raise Error(
            "E_VERIFY_INCOMPLETE", "physical geometry millimetre unit evidence is incomplete"
        )
    features = {str(row["id"]) for row in state["features"]}
    items = [g for g in state["geometry"]["items"] if g.get("kind") in ("surface", "edge")]
    refs = [g.get("ref") for g in items]
    ids = [(g.get("kind"), g.get("id")) for g in items]
    if (
        not items
        or not all(isinstance(ref, str) and ref for ref in refs)
        or len(set(refs)) != len(refs)
        or not all(isinstance(ident, str) and ident for _, ident in ids)
        or len(set(ids)) != len(ids)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "physical surface/edge identity inventory is incomplete")
    surfaces = {g["ref"]: g for g in items if g["kind"] == "surface"}
    edges = {g["ref"]: g for g in items if g["kind"] == "edge"}
    for row in items:
        owner = row.get("feature")
        if not isinstance(owner, dict) or str(owner.get("id")) not in features:
            raise Error("E_VERIFY_INCOMPLETE", "physical surface/edge ownership is incomplete")
        if row["kind"] == "surface":
            bounds = row.get("bbox")
            if (
                not _finite_number(row.get("area"))
                or row["area"] <= 0
                or not isinstance(bounds, list)
                or len(bounds) != 2
                or not all(_point(point) for point in bounds)
                or any(low > high for low, high in zip(*bounds, strict=True))
            ):
                raise Error("E_VERIFY_INCOMPLETE", "physical surface area or bounds are incomplete")
            if row.get("type") == "plane":
                complete = all(
                    _point(row.get(key)) for key in ("normal", "origin")
                ) and math.isclose(dot(row["normal"], row["normal"]), 1, abs_tol=TOL)
            elif row.get("type") == "cylinder":
                axis = row.get("axis")
                complete = (
                    isinstance(axis, dict)
                    and all(_point(axis.get(key)) for key in ("origin", "direction"))
                    and math.isclose(dot(axis["direction"], axis["direction"]), 1, abs_tol=TOL)
                    and _finite_number(row.get("radius"))
                    and row["radius"] > 0
                    and row.get("outward") in ("toward_axis", "away_from_axis")
                )
            else:
                raise Error("E_UNSUPPORTED", "solid-boundary proof supports only planes/cylinders")
        else:
            adjacent = row.get("surfaces")
            complete = (
                isinstance(adjacent, list)
                and len(adjacent) == 2
                and all(isinstance(ref, str) for ref in adjacent)
                and len(set(adjacent)) == 2
                and all(ref in surfaces for ref in adjacent)
                and all(_point(row.get(key)) for key in ("start", "end"))
                and _finite_number(row.get("length"))
                and row["length"] > 0
            )
            if row.get("type") == "line":
                complete = (
                    complete
                    and _point(row.get("direction"))
                    and math.isclose(dot(row["direction"], row["direction"]), 1, abs_tol=TOL)
                )
            elif row.get("type") in ("arc", "circle"):
                complete = (
                    complete
                    and all(_point(row.get(key)) for key in ("center", "normal"))
                    and math.isclose(dot(row["normal"], row["normal"]), 1, abs_tol=TOL)
                    and _finite_number(row.get("radius"))
                    and row["radius"] > 0
                )
            else:
                raise Error("E_UNSUPPORTED", "solid-boundary proof supports line/arc/circle edges")
        if not complete:
            raise Error("E_VERIFY_INCOMPLETE", "physical analytic geometry fields are incomplete")
    return surfaces, edges


def _closed_components(edges):
    """Every connected cap boundary component closes, including old circular holes."""
    remaining = list(edges)
    if not remaining:
        return False
    while remaining:
        group = [remaining.pop()]
        while True:
            joined = [
                edge
                for edge in remaining
                if any(
                    math.dist(edge[a], item[b]) < TOL
                    for item in group
                    for a in ("start", "end")
                    for b in ("start", "end")
                )
            ]
            if not joined:
                break
            group.extend(joined)
            remaining = [edge for edge in remaining if edge not in joined]
        if not _closed_rim(group):
            return False
    return True


def _family_readable(family):
    return (
        isinstance(family, dict)
        and family.get("complete") is True
        and isinstance(family.get("source"), str)
        and bool(family["source"])
        and all(key in family for key in ("generic", "instances", "row_count", "column_count"))
    )


def _standalone_family(family):
    return (
        _family_readable(family)
        and family.get("kind") == "standalone"
        and family["generic"] is None
        and family["instances"] == []
        and type(family["row_count"]) is int
        and family["row_count"] == 0
        and type(family["column_count"]) is int
        and family["column_count"] == 0
    )


def _same_typed_family(actual, expected):
    """Family metadata must not exploit Python's True == 1 or False == 0."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same_typed_family(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_typed_family(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return actual == expected


def _model_bounds_readable(bounds):
    return (
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(_point(point) for point in bounds)
        and all(low < high for low, high in zip(*bounds, strict=True))
    )


def _hole_solid_protection(before, intent):
    """Build a finite impact zone from the frozen baseline, without new CAD getters."""
    family = before["model"].get("family")
    if not _family_readable(family):
        raise Error("E_VERIFY_INCOMPLETE", "native non-family part evidence is incomplete")
    if not _standalone_family(family):
        raise Error(
            "E_UNSUPPORTED", "solid-boundary proof is limited to standalone non-family parts"
        )
    bodies = before["model"].get("bodies")
    bounds = before["model"].get("bbox")
    if (
        not isinstance(bodies, list)
        or len(bodies) != 1
        or not isinstance(bodies[0], dict)
        or set(bodies[0]) != {"id", "name", "state"}
        or not isinstance(bodies[0]["id"], str)
        or not bodies[0]["id"]
        or bodies[0]["state"] != "BODY_STATE_ACTIVE"
        or (bodies[0]["name"] is not None and not isinstance(bodies[0]["name"], str))
        or not _model_bounds_readable(bounds)
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "single active body identity or model bounds are incomplete"
        )
    surfaces, edges = _physical_inventory(before)
    ext, direction = intent["through_extent"], intent["axis"]
    axis, radius = ext["axis"], intent["diameter"] / 2
    center = intent["center"]
    caps = {}
    for side in ("min", "max"):
        candidates = [
            row
            for row in surfaces.values()
            if row["type"] == "plane"
            and building.parallel(direction, row["normal"])
            and abs(row["origin"][axis] - ext[side]) < TOL
            and all(abs(point[axis] - ext[side]) < TOL for point in row["bbox"])
        ]
        if len(candidates) != 1:
            raise Error("E_UNSUPPORTED", "solid-boundary proof needs one actual plane per end")
        cap = candidates[0]
        outward = [0, 0, 0]
        outward[axis] = -1 if side == "min" else 1
        if any(
            abs(actual - wanted) > TOL
            for actual, wanted in zip(cap["normal"], outward, strict=True)
        ):
            raise Error(
                "E_UNSUPPORTED", "physical end-face outward normal contradicts plate extent"
            )
        cap_edges = [edge for edge in edges.values() if cap["ref"] in edge["surfaces"]]
        if not _closed_components(cap_edges) or any(
            abs(edge[key][axis] - ext[side]) >= TOL
            for edge in cap_edges
            for key in ("start", "end")
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "physical end-face boundary is not completely closed"
            )
        caps[side] = cap["ref"]
    if caps["min"] == caps["max"]:
        raise Error("E_VERIFY_INCOMPLETE", "physical end faces have the same identity")
    for row in surfaces.values():
        if row["ref"] in caps.values():
            continue
        if any(
            abs(row["bbox"][i][axis] - ext[side]) >= TOL for i, side in enumerate(("min", "max"))
        ):
            raise Error("E_UNSUPPORTED", "solid-boundary proof requires full-thickness side faces")
        if row["type"] == "plane":
            normal = row["normal"]
            if (
                abs(dot(normal, direction)) >= TOL
                or not math.isclose(dot(normal, normal), 1, abs_tol=TOL)
                or dot(normal, [a - b for a, b in zip(center, row["origin"], strict=True)])
                >= -radius - TOL
            ):
                raise Error(
                    "E_UNSUPPORTED", "hole footprint is not inside each physical side plane"
                )
        elif (
            not building.parallel(direction, row["axis"]["direction"])
            or _axis_distance(center, row["axis"]) <= row["radius"] + radius + TOL
        ):
            raise Error("E_UNSUPPORTED", "hole footprint reaches an existing cylinder exclusion")
        if any(
            not any(
                row["ref"] in edge["surfaces"] and cap in edge["surfaces"]
                for edge in edges.values()
            )
            for cap in caps.values()
        ):
            raise Error("E_VERIFY_INCOMPLETE", "a side face lacks both physical end boundaries")
    drop = math.pi * radius**2
    budgets = {}
    for side, ref in caps.items():
        value = surfaces[ref]["area"]
        expected = value - drop
        comparison = HOLE_SOLID_PROTECTION_V1["cap_area_comparison"]
        budget = comparison["absolute_serialization_budget"] + comparison["binary_ulps"] * max(
            math.ulp(value), math.ulp(expected)
        )
        if not 0 < expected < value < 1e9 or budget > comparison["hard_cap"]:
            raise Error("E_UNSUPPORTED", "end-face area cannot resolve the intended circular trim")
        budgets[side] = budget
    return copy.deepcopy(HOLE_SOLID_PROTECTION_V1) | {
        "cap_refs": caps,
        "unaffected_surface_refs": sorted(set(surfaces) - set(caps.values())),
        "retained_edge_refs": sorted(edges),
        "removed_area_each": drop,
        "cap_area_budgets": budgets,
        "body_identity": copy.deepcopy(bodies),
        "model_bbox": copy.deepcopy(bounds),
        "model_family": copy.deepcopy(family),
    }


def _freeze_hole_solid_protection(before, intent):
    if intent and intent.get("complete_through_hole", {}).get("volume_comparison"):
        intent["solid_protection"] = _hole_solid_protection(before, intent)


def _retained_hole_solid_policy(before, intent):
    if "solid_protection" not in intent:
        return None
    policy = intent["solid_protection"]
    if (
        not isinstance(policy, dict)
        or type(policy.get("version")) is not int
        or policy != _hole_solid_protection(before, intent)
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained solid-boundary policy is incomplete or changed"
        )
    return policy


def _hole_solid_checks(before, intent, after, ident, walls):
    policy = _retained_hole_solid_policy(before, intent)
    if policy is None:
        return []  # Historical receipts retain their explicitly older coverage.
    old_surfaces, old_edges = _physical_inventory(before)
    try:
        surfaces, edges = _physical_inventory(after)
    except Error as exc:
        if exc.code not in ("E_VERIFY_INCOMPLETE", "E_UNSUPPORTED"):
            raise
        return [
            engine.check(
                "complete_hole_solid_boundary_evidence_readable",
                False,
                incomplete=True,
                error={
                    "code": exc.code,
                    "message": exc.message,
                    "details": copy.deepcopy(exc.details),
                },
                evidence_source="independent_machining_snapshot.geometry; "
                "full raw current snapshot retained",
            )
        ]
    cap_refs = policy["cap_refs"]
    caps = set(cap_refs.values())
    wall_refs = {row["ref"] for row in walls}
    new_surfaces = set(surfaces) - set(old_surfaces)
    new_edges = set(edges) - set(old_edges)
    before_feature_ids = {row["id"] for row in before["features"]}
    current_feature_ids = [row["id"] for row in after["features"]]
    added_feature_ids = [value for value in current_feature_ids if value not in before_feature_ids]
    checks = [
        engine.check(
            "complete_hole_exact_new_feature_inventory",
            added_feature_ids == [ident]
            and len(current_feature_ids) == len(set(current_feature_ids)),
            expected_added_feature_ids=[ident],
            observed_added_feature_ids=added_feature_ids,
        ),
        engine.check(
            "complete_hole_non_family_part_preserved",
            _standalone_family(after["model"].get("family"))
            and _same_typed_family(after["model"]["family"], policy["model_family"]),
            expected=policy["model_family"],
            observed=after["model"].get("family"),
        ),
        engine.check(
            "complete_hole_single_active_body_preserved",
            after["model"].get("bodies") == policy["body_identity"],
            expected=policy["body_identity"],
            observed=after["model"].get("bodies"),
        ),
        engine.check(
            "complete_hole_model_bounds_unchanged",
            _model_bounds_readable(after["model"].get("bbox"))
            and after["model"]["bbox"] == policy["model_bbox"],
            expected=policy["model_bbox"],
            observed=after["model"].get("bbox"),
        ),
        engine.check(
            "complete_hole_physical_surface_inventory",
            set(old_surfaces) <= set(surfaces) and new_surfaces == wall_refs,
            retained_surface_refs=sorted(old_surfaces),
            new_surface_refs=sorted(new_surfaces),
            permitted_wall_refs=sorted(wall_refs),
        ),
        engine.check(
            "complete_hole_unaffected_surfaces_unchanged",
            all(surfaces.get(ref) == row for ref, row in old_surfaces.items() if ref not in caps),
            protected_refs=policy["unaffected_surface_refs"],
        ),
        engine.check(
            "complete_hole_existing_physical_edges_unchanged",
            all(edges.get(ref) == row for ref, row in old_edges.items()),
            protected_edge_refs=policy["retained_edge_refs"],
        ),
        engine.check(
            "complete_hole_only_frozen_cap_rims_added",
            bool(new_edges)
            and all(
                str(edges[ref]["feature"]["id"]) == ident
                and len(set(edges[ref]["surfaces"]) & wall_refs) == 1
                and len(set(edges[ref]["surfaces"]) & caps) == 1
                and edges[ref]["type"] in ("arc", "circle")
                for ref in new_edges
            ),
            new_edge_refs=sorted(new_edges),
            frozen_cap_refs=cap_refs,
        ),
    ]
    for side, ref in cap_refs.items():
        original, current = old_surfaces[ref], surfaces.get(ref, {})
        old_fields = {key: value for key, value in original.items() if key != "area"}
        fields = {key: value for key, value in current.items() if key != "area"}
        expected_area = original["area"] - policy["removed_area_each"]
        actual_area = current.get("area")
        residual = abs(actual_area - expected_area) if _finite_number(actual_area) else None
        checks += [
            engine.check("complete_hole_end_face_identity_" + side, old_fields == fields),
            engine.check(
                "complete_hole_end_face_trim_" + side,
                residual is not None and residual <= policy["cap_area_budgets"][side],
                expected=expected_area,
                observed=actual_area,
                absolute_residual=residual,
                effective_budget=policy["cap_area_budgets"][side],
                comparison=policy["cap_area_comparison"],
                surface_ref=ref,
            ),
        ]
    return checks


def canonical_request(client, model, request):
    return canonical_request_from_geometry(request, geometry(client, model)["items"])


def canonical_request_from_geometry(request, items):
    from .requests import ROUND_SCHEMA, validate_edges, validate_hole

    q = copy.deepcopy(request)
    if "edges" in q:
        refs = building.resolve_references(items, q["edges"])
        q["edges"] = [refs[ref]["ref"] for ref in q["edges"]]
        return validate_edges(q, ROUND_SCHEMA)
    place = q["placement"]
    names = [place["surface"]] + [v["from"] for v in place.get("offsets", [])]
    names += [place[k] for k in ("axis", "angle_from") if k in place]
    refs = building.resolve_references(items, names)
    for key in ("surface", "axis", "angle_from"):
        if key in place:
            place[key] = refs[place[key]]["ref"]
    for offset in place.get("offsets", []):
        offset["from"] = refs[offset["from"]]["ref"]
    return validate_hole(q)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def geometry(client, model):
    data = engine.normalize(client.op("geometry.list", {"model": model}))
    if (
        data.get("model") != model
        or not isinstance(data.get("items"), list)
        or any(g.get("error") for g in data.get("items") or [])
    ):
        raise Error("E_VERIFY_INCOMPLETE", "current solid geometry is unreadable")
    return data


def snapshot(client, model):
    shown = engine.show(client, model)
    features = building.features_of(client, model)
    dimensions = engine.normalize(client.op("dimension.list", {"model": model}))
    if not isinstance(dimensions.get("dimensions"), list) or any(
        d.get("error") for d in dimensions["dimensions"]
    ):
        raise Error("E_VERIFY_INCOMPLETE", "independent dimensions are incomplete")
    definitions = {}
    for f in features:
        if f["type"] in ("FEATTYPE_HOLE", "FEATTYPE_ROUND"):
            detail = engine.normalize(
                client.op("feature.show", {"model": model, "feature": f["id"]})
            )
            definition = detail.get("native_definition")
            if not isinstance(definition, dict) or definition.get("error"):
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "native feature definition is unreadable",
                    {"feature": f["id"], "definition": definition},
                )
            definitions[f["id"]] = definition
    solid_geometry = geometry(client, model)
    # Datum outlines describe display extents, not finite material or reference identity.
    # Finite solid-face bounds remain part of the bound geometry snapshot.
    solid_geometry["items"] = [
        {k: v for k, v in g.items() if k not in ("bbox", "area")}
        if g.get("kind") == "datum_plane"
        else g
        for g in solid_geometry["items"]
    ]
    return {
        "model": shown,
        "features": features,
        "dimensions": dimensions,
        "geometry": solid_geometry,
        "native_definitions": definitions,
    }


def linear_center(placement, refs):
    """PTC offsets are signed along the selected plane normals, not unsigned edge distances."""
    planes = [refs[placement["surface"]]] + [refs[v["from"]] for v in placement["offsets"]]
    if any(p.get("type") != "plane" or not p.get("normal") or not p.get("origin") for p in planes):
        raise Error("E_UNSUPPORTED", "linear hole checks require three readable planar references")
    normals = [p["normal"] for p in planes]
    determinant = dot(normals[0], cross(normals[1], normals[2]))
    if abs(determinant) < TOL:
        raise Error("E_VALIDATION", "hole placement references do not uniquely locate a center")
    values = [dot(p["normal"], p["origin"]) for p in planes]
    for i, offset in enumerate(placement["offsets"], 1):
        values[i] += offset["distance"]
    vectors = [
        cross(normals[1], normals[2]),
        cross(normals[2], normals[0]),
        cross(normals[0], normals[1]),
    ]
    return [sum(values[i] * vectors[i][j] for i in range(3)) / determinant for j in range(3)]


def hole_intent(request, state, *, validate_placement=True):
    if (
        any(k in request for k in ("thread", "clearance", "counterbore", "countersink"))
        or "offsets" not in request["placement"]
    ):
        return None  # Existing advanced variants are not newly certified by this reader.
    refs = {g["ref"]: g for g in state["geometry"]["items"]}
    place = request["placement"]
    center = linear_center(place, refs)
    surface = refs[place["surface"]]
    normal = surface["normal"]
    axis = next((i for i in range(3) if abs(abs(normal[i]) - 1) <= TOL), None)
    intent = {
        "center": center,
        "axis": normal,
        "diameter": request["diameter"],
        "depth": request["depth"],
        "offset_convention": "signed along reference plane normal",
        "placement_kind": surface.get("kind"),
        "cut_intent": "remove material from the current solid",
    }
    if axis is None:
        if validate_placement and request["depth"] == "through_all":
            raise Error(
                "E_UNSUPPORTED", "complete-hole proof is limited to axis-aligned simple plates"
            )
        intent["bounds_check"] = "outside axis-aligned plate precheck"
        return intent
    datum = surface.get("kind") == "datum_plane"
    bounds = surface.get("bbox") if not datum else None
    if not datum and bounds is None:
        raise Error("E_VERIFY_INCOMPLETE", "selected hole face has no reliable physical bounds")
    radius = request["diameter"] / 2
    outside = (
        []
        if datum
        else [
            i
            for i in range(3)
            if i != axis
            and not bounds[0][i] + radius + TOL < center[i] < bounds[1][i] - radius - TOL
        ]
    )
    if outside and validate_placement:
        raise Error(
            "E_VALIDATION",
            "hole footprint is outside or touches the selected face boundary",
            {
                "center": center,
                "diameter": request["diameter"],
                "face": surface["ref"],
                "bounds": bounds,
                "offending_axes": outside,
                "dispatch_state": "not_started",
            },
        )
    solid_bounds = state["model"].get("bbox")
    if not solid_bounds and validate_placement and request["depth"] == "through_all":
        raise Error(
            "E_VERIFY_INCOMPLETE", "complete-hole intent requires readable physical plate extents"
        )
    if solid_bounds:
        footprint_outside = [
            i
            for i in range(3)
            if i != axis
            and not solid_bounds[0][i] + radius + TOL
            < center[i]
            < solid_bounds[1][i] - radius - TOL
        ]
        if footprint_outside and validate_placement:
            raise Error(
                "E_VALIDATION",
                "complete hole footprint reaches the physical solid's outer extent",
                {
                    "center": center,
                    "diameter": request["diameter"],
                    "solid_bounds": solid_bounds,
                    "offending_axes": footprint_outside,
                    "dispatch_state": "not_started",
                    "source": "actual model solid extents; never datum display bounds",
                    "limit": "necessary exclusion only; being inside does not prove "
                    "complete material",
                },
            )
        intent["through_extent"] = {
            "axis": axis,
            "min": solid_bounds[0][axis],
            "max": solid_bounds[1][axis],
        }
        if request["depth"] == "through_all":
            thickness = solid_bounds[1][axis] - solid_bounds[0][axis]
            intent["complete_through_hole"] = {
                "wall_area": 2 * math.pi * radius * thickness,
                "removed_volume": math.pi * radius**2 * thickness,
                "rim_length_each": 2 * math.pi * radius,
                "proof": "current inward cylindrical wall area, two closed circular rims with "
                "physical cap adjacency, no open lateral boundary, and full cylindrical removal",
                "comparison_relative_tolerance": 1e-6,
                "comparison_absolute_tolerance": TOL,
                "not_a_manufacturing_tolerance": True,
            }
    intent["bounds_check"] = (
        "infinite datum plane; display extents ignored; physical outer bounds only exclude "
        "impossible full footprints; closed walls/rims and complete cutting are checked after apply"
        if datum
        else "axis-aligned finite face bounding box; trims checked after apply"
    )
    return intent


def _closed_rim(edges):
    """A single connected degree-two cycle; edge counts or length alone do not close a rim."""
    nodes, links = [], []
    for edge in edges:
        pair = []
        for name in ("start", "end"):
            point = edge.get(name)
            if not _point(point):
                return False
            index = next((i for i, p in enumerate(nodes) if math.dist(p, point) < TOL), None)
            if index is None:
                index = len(nodes)
                nodes.append(point)
            pair.append(index)
        links.append(pair)
    if not nodes or any(sum(link.count(i) for link in links) != 2 for i in range(len(nodes))):
        return False
    seen = {0}
    while True:
        expanded = seen | {i for pair in links if seen.intersection(pair) for i in pair}
        if expanded == seen:
            return len(seen) == len(nodes)
        seen = expanded


def complete_hole_checks(before, intent, after, walls):
    """Bounded plate proof from real trimmed surfaces and their current boundary edges."""
    expected = intent.get("complete_through_hole")
    if not expected:
        return [
            engine.check("complete_hole_evidence_readable", False, reason="no frozen plate extent")
        ]
    if not isinstance(expected, dict) or any(
        key not in expected for key in ("wall_area", "removed_volume", "rim_length_each")
    ):
        raise Error("E_VERIFY_INCOMPLETE", "retained complete-hole scalar intent is incomplete")
    ext = intent["through_extent"]
    axis = ext["axis"]
    by_ref = {g["ref"]: g for g in after["geometry"]["items"]}
    refs = {g["ref"] for g in walls}
    boundary = [
        g
        for g in by_ref.values()
        if g.get("kind") == "edge" and refs.intersection(g.get("surfaces", []))
    ]
    readable = not walls or (
        bool(boundary)
        and all(
            isinstance(g.get("area"), (int, float)) and math.isfinite(g["area"]) and g["area"] > 0
            for g in walls
        )
    )
    rims = {"min": [], "max": []}
    other = []
    for edge in boundary:
        adjacent = edge.get("surfaces", [])
        if len(adjacent) != 2 or any(r not in by_ref for r in adjacent):
            readable = False
            other.append(edge["ref"])
            continue
        if all(r in refs for r in adjacent):
            continue  # A seam joining two halves of the same cylindrical wall.
        cap = by_ref[next(r for r in adjacent if r not in refs)]
        edge_readable = (
            all(_point(edge.get(k)) for k in ("center", "normal", "start", "end"))
            and isinstance(edge.get("radius"), (int, float))
            and isinstance(edge.get("length"), (int, float))
        )
        # Non-circular lateral edges are known open boundaries, not missing successful rims.
        if edge.get("type") in ("arc", "circle") and not edge_readable:
            readable = False
        found = False
        if edge_readable and edge.get("type") in ("arc", "circle"):
            for side in rims:
                if (
                    abs(edge["radius"] - intent["diameter"] / 2) < TOL
                    and building.parallel(intent["axis"], edge["normal"])
                    and _axis_distance(
                        edge["center"], {"origin": intent["center"], "direction": intent["axis"]}
                    )
                    < TOL
                    and all(
                        abs(edge[k][axis] - ext[side]) < TOL for k in ("center", "start", "end")
                    )
                    and cap.get("type") == "plane"
                    and _point(cap.get("normal"))
                    and _point(cap.get("origin"))
                    and building.parallel(intent["axis"], cap["normal"])
                    and abs(cap["origin"][axis] - ext[side]) < TOL
                ):
                    rims[side].append(edge)
                    found = True
        if not found:
            other.append(edge["ref"])
    area = sum(g["area"] for g in walls) if readable else None

    def close(actual, wanted):
        return actual is not None and math.isclose(actual, wanted, rel_tol=1e-6, abs_tol=TOL)

    checks = [
        engine.check(
            "complete_hole_evidence_readable",
            readable,
            wall_refs=sorted(refs),
            boundary_refs=[e["ref"] for e in boundary],
        ),
        engine.check(
            "complete_hole_wall_area",
            close(area, expected["wall_area"]),
            expected=expected["wall_area"],
            observed=area,
        ),
        _hole_volume_check(before, expected, after),
        engine.check(
            "complete_hole_no_lateral_opening",
            readable and not other,
            unexpected_boundary_refs=other,
        ),
    ]
    for side, edges in rims.items():
        length = sum(e["length"] for e in edges)
        checks.append(
            engine.check(
                "complete_hole_closed_rim_" + side,
                _closed_rim(edges) and close(length, expected["rim_length_each"]),
                expected_length=expected["rim_length_each"],
                observed_length=length,
                edge_refs=[e["ref"] for e in edges],
                axial_position=ext[side],
            )
        )
    return checks


def round_intent(request, state):
    by_ref = {g["ref"]: g for g in state["geometry"]["items"]}
    rows = []
    for ref in request["edges"]:
        edge = by_ref[ref]
        if edge.get("kind") != "edge":
            raise Error(
                "E_VALIDATION", "round reference is not a current solid edge", {"reference": ref}
            )
        bounds = state["model"].get("bbox")
        if edge.get("type") == "line" and edge.get("direction") and bounds:
            perpendicular = [i for i, d in enumerate(edge["direction"]) if abs(d) < TOL]
            if perpendicular and request["radius"] >= min(
                bounds[1][i] - bounds[0][i] for i in perpendicular
            ):
                raise Error(
                    "E_VALIDATION",
                    "round radius exceeds the available transverse solid extent",
                    {"edge": ref, "radius": request["radius"], "bounds": bounds},
                )
        rows.append(edge)
    envelopes = []
    for edge in rows:
        faces = [by_ref.get(ref, {}) for ref in edge.get("surfaces", [])]
        if (
            edge.get("type") != "line"
            or len(faces) != 2
            or any(f.get("type") != "plane" or not f.get("normal") for f in faces)
            or abs(dot(faces[0]["normal"], faces[1]["normal"])) > TOL
        ):
            continue
        radius = request["radius"]
        axis = next((i for i, v in enumerate(edge["direction"]) if abs(abs(v) - 1) < TOL), None)
        if axis is None:
            continue
        low, high = sorted((edge["start"][axis], edge["end"][axis]))
        origin = [edge["start"][i] - radius * sum(f["normal"][i] for f in faces) for i in range(3)]
        envelopes.append(
            {
                "edge": edge["ref"],
                "axis_origin": origin,
                "axis_direction": edge["direction"],
                "start": edge["start"],
                "end": edge["end"],
                "radius": radius,
                "extent": {"axis": axis, "min": low, "max": high},
                "curved_area": math.pi / 2 * radius * (high - low),
            }
        )
    return {
        "radius": request["radius"],
        "edges": rows,
        "exterior_edge_envelopes": envelopes,
        "cut_intent": "remove material at the selected exterior edges",
        "coverage": "constant radius; native acceptance limited to straight exterior edges",
    }


def checked_plan(client, plan, request):
    client.require_capability("machining_feature_readback", 1)
    before = snapshot(client, plan.target)
    intent = (
        hole_intent(request, before) if plan.op == "feature.hole" else round_intent(request, before)
    )
    if plan.op == "feature.hole":
        _freeze_hole_volume_policy(request, before, intent)
        _freeze_hole_solid_protection(before, intent)
    plan.binding |= {"machining_before": before, "machining_intent": intent}
    plan.preview["machining_intent"] = intent
    plan.preview["unverified_variants"] = [
        "threads/counterbores/countersinks",
        "variable radius",
        "complex topology",
    ]
    plan.before = before
    plan.observe = lambda c: snapshot(c, plan.target)
    previous = plan.verify

    def verify(c, data):
        result, checks = previous(c, data)
        after = snapshot(c, plan.target)
        extra, proof = verify_geometry(
            plan.op, request, before, intent, after, str(data["feature"]["id"])
        )
        result.update(extra)
        checks["checks"].extend(proof["checks"])
        checks["observations"].extend(proof["observations"])
        return result, checks

    plan.verify = verify
    return plan


def verify_geometry(op, request, before, intent, after, ident):
    """The same independent geometric predicates serve confirmation and later inspection."""
    expected_type = "FEATTYPE_HOLE" if op == "feature.hole" else "FEATTYPE_ROUND"
    result = {}
    checks = {"checks": [], "observations": []}
    checks["checks"] += [
        engine.check(
            "units_unchanged", before["model"].get("units") == after["model"].get("units")
        ),
        engine.check(
            "material_removed",
            after["model"]["mass_properties"]["volume"]
            < before["model"]["mass_properties"]["volume"],
        ),
    ]
    definition = after["native_definitions"].get(ident, {})
    own = [
        g for g in after["geometry"]["items"] if str((g.get("feature") or {}).get("id")) == ident
    ]
    checks["checks"].append(
        engine.check(
            "current_native_feature_type",
            any(
                f["id"] == ident and f["type"] == expected_type and f["status"] == "FEAT_ACTIVE"
                for f in after["features"]
            ),
        )
    )
    old_features = {f["id"]: f for f in before["features"]}
    actual_features = {f["id"]: f for f in after["features"]}
    checks["checks"].append(
        engine.check(
            "unrelated_feature_rows_unchanged",
            all(actual_features.get(k) == v for k, v in old_features.items()),
        )
    )
    checks["checks"].append(
        engine.check(
            "existing_native_definitions_unchanged",
            all(
                after["native_definitions"].get(k) == v
                for k, v in before["native_definitions"].items()
            ),
        )
    )
    old_dims = {d["name"]: d for d in before["dimensions"]["dimensions"]}
    new_dims = {d["name"]: d for d in after["dimensions"]["dimensions"]}
    checks["checks"].append(
        engine.check(
            "unrelated_dimensions_unchanged",
            all(new_dims.get(k) == v for k, v in old_dims.items()),
        )
    )
    if op == "feature.hole":
        if intent and "solid_protection" in intent:
            _retained_hole_solid_policy(before, intent)
        volume_policy = (
            _hole_volume_policy(intent["complete_through_hole"], before)
            if intent and intent.get("complete_through_hole")
            else None
        )
        own_surfaces = []
        if volume_policy:
            physical = [g for g in after["geometry"]["items"] if g.get("kind") == "surface"]
            feature_ids = {str(f["id"]) for f in after["features"]}
            if not physical or any(
                not isinstance(g.get("feature"), dict)
                or not isinstance(g["feature"].get("id"), (str, int))
                or isinstance(g["feature"].get("id"), bool)
                or not str(g["feature"]["id"]).strip()
                or str(g["feature"]["id"]) not in feature_ids
                for g in physical
            ):
                raise Error(
                    "E_VERIFY_INCOMPLETE", "current physical surface ownership is incomplete"
                )
            own_surfaces = [g for g in own if g.get("kind") == "surface"]
        cylinders = [
            g
            for g in own
            if g.get("type") == "cylinder"
            and g.get("outward") == "toward_axis"
            and (not volume_policy or g.get("kind") == "surface")
        ]
        checks["checks"].append(
            engine.check("hole_is_in_current_solid", bool(cylinders), current_cylinders=cylinders)
        )
        if intent is not None:
            radius = request["diameter"] / 2
            matched = [
                g
                for g in cylinders
                if isinstance(g.get("radius"), int | float)
                and abs(g["radius"] - radius) < TOL
                and isinstance(g.get("axis"), dict)
                and _point(g["axis"].get("direction"))
                and _point(g["axis"].get("origin"))
                and building.parallel(intent["axis"], g["axis"]["direction"])
                and _axis_distance(intent["center"], g["axis"]) < TOL
            ]
            if volume_policy:
                own_refs = [g.get("ref") for g in own_surfaces]
                matched_refs = [g.get("ref") for g in matched if g.get("kind") == "surface"]
                unique_refs = all(isinstance(ref, str) and bool(ref) for ref in own_refs) and len(
                    own_refs
                ) == len(set(own_refs))
                checks["checks"].append(
                    engine.check(
                        "complete_hole_owned_surfaces_covered",
                        bool(own_refs) and unique_refs and set(own_refs) == set(matched_refs),
                        own_surface_refs=own_refs,
                        matched_wall_refs=matched_refs,
                    )
                )
            checks["checks"] += [
                engine.check("native_hole_definition_complete", definition.get("complete") is True),
                engine.check(
                    "hole_diameter_and_center",
                    bool(matched),
                    expected=intent,
                    observed=cylinders,
                ),
                engine.check(
                    "hole_depth_type",
                    definition.get("through_all") == (request["depth"] == "through_all"),
                ),
                engine.check(
                    "hole_placement_references",
                    references_match(
                        [definition.get("placement_surface")],
                        [request["placement"]["surface"]],
                        before,
                    )
                    and references_match(
                        [o.get("from") for o in definition.get("offsets", [])],
                        [o["from"] for o in request["placement"]["offsets"]],
                        before,
                    )
                    and [o.get("distance") for o in definition.get("offsets", [])]
                    == [o["distance"] for o in request["placement"]["offsets"]],
                ),
            ]
            if request["depth"] == "through_all" and intent.get("through_extent"):
                ext = intent["through_extent"]
                spans = any(
                    g.get("bbox")
                    and abs(g["bbox"][0][ext["axis"]] - ext["min"]) < TOL
                    and abs(g["bbox"][1][ext["axis"]] - ext["max"]) < TOL
                    for g in matched
                )
                checks["checks"].append(
                    engine.check(
                        "hole_spans_solid_thickness",
                        spans,
                        expected=ext,
                        observed=[g.get("bbox") for g in matched],
                    )
                )
                checks["checks"].extend(complete_hole_checks(before, intent, after, matched))
                own_covered = all(
                    row["passed"]
                    for row in checks["checks"]
                    if row["check"] == "complete_hole_owned_surfaces_covered"
                )
                if own_covered:
                    checks["checks"].extend(
                        _hole_solid_checks(before, intent, after, ident, matched)
                    )
                elif "solid_protection" in intent:
                    checks["checks"].append(
                        engine.check(
                            "complete_hole_retained_solid_boundary",
                            False,
                            reason="new-hole surface inventory already contradicts frozen intent",
                        )
                    )
    else:
        checks["checks"] += [
            engine.check("native_round_definition_complete", definition.get("complete") is True),
            engine.check(
                "native_round_radius",
                definition.get("constant") is True
                and isinstance(definition.get("radius"), int | float)
                and math.isclose(definition.get("radius", -1), request["radius"], abs_tol=TOL),
            ),
            engine.check(
                "native_round_references",
                references_match(
                    sorted(definition.get("edges", [])), sorted(request["edges"]), before
                ),
            ),
            engine.check(
                "round_in_current_solid", bool([g for g in own if g.get("kind") == "surface"])
            ),
        ]
        if all(e.get("type") == "line" for e in intent["edges"]):
            checks["checks"].append(
                engine.check(
                    "round_radius_in_current_solid",
                    any(
                        g.get("type") == "cylinder"
                        and isinstance(g.get("radius"), int | float)
                        and abs(g["radius"] - request["radius"]) < TOL
                        for g in own
                    ),
                    expected_radius=request["radius"],
                    observed_geometry=own,
                )
            )
        for envelope in intent.get("exterior_edge_envelopes", []):
            candidates = [
                g
                for g in own
                if g.get("type") == "cylinder"
                and g.get("axis")
                and g.get("outward") == "away_from_axis"
                and isinstance(g.get("radius"), (int, float))
                and abs(g.get("radius", -1) - envelope["radius"]) < TOL
                and building.parallel(envelope["axis_direction"], g["axis"]["direction"])
                and _axis_distance(envelope["axis_origin"], g["axis"]) < TOL
            ]
            checks["checks"].append(
                engine.check(
                    "round_at_selected_edge",
                    bool(candidates),
                    expected=envelope,
                    observed=candidates,
                )
            )
            extent = envelope["extent"]
            intervals = sorted(
                (g["bbox"][0][extent["axis"]], g["bbox"][1][extent["axis"]])
                for g in candidates
                if g.get("bbox")
            )
            covered = extent["min"]
            for low, high in intervals:
                if low > covered + TOL:
                    break
                covered = max(covered, high)
            spans = (
                bool(intervals)
                and abs(intervals[0][0] - extent["min"]) < TOL
                and abs(covered - extent["max"]) < TOL
            )
            readable_area = bool(candidates) and all(
                isinstance(g.get("area"), (int, float)) for g in candidates
            )
            area = sum(g["area"] for g in candidates) if readable_area else None
            checks["checks"] += [
                engine.check(
                    "round_full_selected_extent", spans, expected=extent, observed=intervals
                ),
                engine.check(
                    "round_curved_area",
                    area is not None
                    and math.isclose(area, envelope["curved_area"], rel_tol=1e-6, abs_tol=1e-6),
                    expected=envelope["curved_area"],
                    observed=area,
                ),
            ]
    result["native_definition"] = definition
    result["current_feature_geometry"] = own
    if op == "feature.hole":
        result["solid_protection_coverage"] = (
            intent["solid_protection"]["mode"]
            if intent and "solid_protection" in intent
            else "legacy; no retained unaffected-solid-boundary policy"
        )
    checks["observations"].append(
        {
            "observation": "independent_machining_snapshot",
            "observed": after,
            "independent": True,
        }
    )
    return result, checks


def _axis_distance(point, axis):
    if (
        not _point(point)
        or not isinstance(axis, dict)
        or not all(_point(axis.get(k)) for k in ("origin", "direction"))
    ):
        return math.inf
    vector = [p - o for p, o in zip(point, axis["origin"], strict=True)]
    length = math.sqrt(dot(axis["direction"], axis["direction"]))
    return (
        math.sqrt(sum(x * x for x in cross(vector, axis["direction"]))) / length
        if length > TOL
        else math.inf
    )


def references_match(actual, expected, before):
    if not all(isinstance(v, str) for v in actual) or len(actual) != len(expected):
        return False
    try:
        rows = building.resolve_references(before["geometry"]["items"], actual + expected)
        return [rows[v]["ref"] for v in actual] == [rows[v]["ref"] for v in expected]
    except Error:
        return False


def recovery(client, run):
    """Inspect frozen intent against fresh current-solid data; never replay or settle here."""
    plan = run.get("driver_plan") or {}
    baseline = (
        plan.get("base_snapshot", {}).get("extensions", {}).get("creo", {}).get("observation", {})
    )
    before = baseline.get("machining_before")
    original = plan.get("changes", [{}])[0].get("after")
    if not before or not isinstance(original, dict) or original.get("model") != run.get("target"):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "retained machining intent is unavailable; outcome remains unknown",
        )
    health = client.health()
    if health.get("service_instance_id") != plan.get("target", {}).get("instance_id"):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "current service instance differs from the original operation; "
            "absence is not recovery evidence",
        )
    client.require_capability("machining_feature_readback", 1)
    request = {k: v for k, v in original.items() if k != "model"}
    units = before["model"].get("units")
    unit = units.get("length") if isinstance(units, dict) else None
    if unit not in building.UNIT_ALIASES:
        raise Error("E_VERIFY_INCOMPLETE", "retained machining model units are incomplete")
    request["units"] = building.UNIT_ALIASES[unit]
    request = canonical_request_from_geometry(request, before["geometry"]["items"])
    op = "feature.hole" if run["command"] == "feature hole" else "feature.round"
    # Recovery inspects a write that already occurred, including an old invalid placement.
    # Re-running preview exclusions here would hide the readable partial native outcome.
    if op == "feature.hole":
        if "machining_intent" not in baseline:
            # Very old records may lack a retained intent. The constructor is
            # deliberately legacy; only a newly checked plan can freeze v2.
            intent = hole_intent(request, before, validate_placement=False)
        elif not isinstance(baseline["machining_intent"], dict):
            raise Error("E_VERIFY_INCOMPLETE", "retained hole intent is malformed")
        else:
            intent = copy.deepcopy(baseline["machining_intent"])
        if intent is not None:
            ext = intent.get("through_extent")
            expected = intent.get("complete_through_hole")
            if (
                not _point(intent.get("axis"))
                or not any(abs(v) > TOL for v in intent["axis"])
                or not _point(intent.get("center"))
                or not _finite_number(intent.get("diameter"))
                or intent["diameter"] <= 0
                or not isinstance(ext, dict)
                or type(ext.get("axis")) is not int
                or ext["axis"] not in (0, 1, 2)
                or not all(_finite_number(ext.get(key)) for key in ("min", "max"))
                or ext["max"] <= ext["min"]
                or not isinstance(expected, dict)
                or not all(
                    _finite_number(expected.get(key)) and expected[key] > 0
                    for key in ("removed_volume", "wall_area", "rim_length_each")
                )
            ):
                raise Error("E_VERIFY_INCOMPLETE", "retained complete-hole intent is incomplete")
            _hole_volume_policy(expected, before)
            _retained_hole_solid_policy(before, intent)
    else:
        intent = round_intent(request, before)
    if (
        intent is None
        or (
            op == "feature.hole"
            and (request["depth"] != "through_all" or not intent.get("through_extent"))
        )
        or (
            op == "feature.round"
            and len(intent["exterior_edge_envelopes"]) != len(request["edges"])
        )
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "this retained shape is outside the bounded independent recovery proof",
        )
    after = snapshot(client, run["target"])
    prior_ids = {f["id"] for f in before["features"]}
    added = [f for f in after["features"] if f["id"] not in prior_ids]
    expected_type = "FEATTYPE_HOLE" if op == "feature.hole" else "FEATTYPE_ROUND"
    identified = (
        len(added) == 1
        and added[0]["type"] == expected_type
        and (
            not request.get("name")
            or str(added[0].get("name")).casefold() == request["name"].casefold()
        )
    )
    checks = [engine.check("one_identified_native_feature_added", identified, observed=added)]
    if identified:
        _, proof = verify_geometry(op, request, before, intent, after, added[0]["id"])
        checks += proof["checks"]
    if op == "feature.hole" and "solid_protection" not in intent:
        checks.append(
            engine.check(
                "retained_solid_boundary_policy_available",
                False,
                reason="historical predicates remain available, but the old frozen intent has "
                "no unaffected-solid protection policy; full applied registration is incomplete",
                historical_receipt_unchanged=True,
            )
        )
    complete = all(d.get("complete") is True for d in after["native_definitions"].values())
    own = [
        g
        for g in after["geometry"]["items"]
        if identified and str(g.get("feature", {}).get("id")) == added[0]["id"]
    ]
    for g in own:
        if g.get("type") == "cylinder":
            complete = (
                complete and isinstance(g.get("radius"), (int, float)) and bool(g.get("axis"))
            )
            if g.get("axis"):
                complete = complete and all(
                    _point(g["axis"].get(k)) for k in ("origin", "direction")
                )
            complete = complete and bool(g.get("bbox"))
            complete = complete and isinstance(g.get("area"), (int, float))
    if op == "feature.hole" and identified:
        complete = complete and all(
            c["passed"] for c in checks if c["check"] == "complete_hole_evidence_readable"
        )
    checks.append(engine.check("native_definitions_complete", complete))
    from .presentation import equivalent

    stable = equivalent(after, snapshot(client, run["target"]))
    checks.append(engine.check("independent_readback_stable", stable))
    accepted = all(row["passed"] for row in checks)
    unchanged = complete and stable and equivalent(before, after)
    can_register = (
        ["applied"]
        if accepted
        else ["not_applied"]
        if unchanged
        else ["partial"]
        if complete and stable and identified
        else []
    )
    return {
        "accepted": accepted,
        "can_register": can_register,
        "checks": checks,
        "intent": intent,
        "current": after,
        "original_operation_id": run["operation_id"],
        "solid_protection_coverage": (
            intent["solid_protection"]["mode"]
            if op == "feature.hole" and "solid_protection" in intent
            else "legacy; no retained unaffected-solid-boundary policy"
            if op == "feature.hole"
            else "bounded exterior-round intent"
        ),
        "coverage": "retained simple through-hole or orthogonal exterior-round intent versus "
        "current solid; historical receipt unchanged",
    }
