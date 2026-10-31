"""One planar prism wall about its top datum: frozen intent and native boundary proof."""

import math
from copy import deepcopy

from . import building, engine, model_management, operations, prismatic, safety
from .core import Error, digest

COMMANDS = ("feature draft",)
PROFILE = "single-prism-wall-draft-v1"


def canonical_request(client, name, request):
    q = deepcopy(request)
    if len(q["surfaces"]) != 1 or q.get("flip_pull"):
        raise Error("E_UNSUPPORTED", "bounded draft uses one wall and an unflipped explicit pull")
    q.setdefault("units", "mm")
    q.setdefault("pull", q["hinge"])
    refs = [*q["surfaces"], q["hinge"], q["pull"]]
    items = client.op("geometry.list", {"model": name})["items"]
    found = building.resolve_references(items, refs)
    q["surfaces"] = [found[q["surfaces"][0]]["ref"]]
    for key in ("hinge", "pull"):
        q[key] = found[q[key]]["ref"]
    return q


def snapshot(client, name):
    client.require_capability("prismatic_draft_readback", 1)
    client.require_capability("prismatic_shell_readback", 2)
    result = model_management.snapshot(client, name)
    result["geometry"] = prismatic.geometry(client, name)
    result["reference_geometry"] = engine.normalize(client.op("geometry.list", {"model": name}))
    if result["geometry"].get("units") != result["model"].get("units"):
        raise Error("E_VERIFY_INCOMPLETE", "draft body and model units disagree")
    references = result["reference_geometry"]
    if (
        references.get("model") != name
        or references.get("units") != result["model"].get("units")
        or not isinstance(references.get("items"), list)
        or any(not isinstance(row, dict) or row.get("error") for row in references["items"])
    ):
        raise Error("E_VERIFY_INCOMPLETE", "draft reference inventory is incomplete or foreign")
    result["definitions"] = {}
    for feature in result["parts"][name]["features"]:
        if feature["type"] == "FEATTYPE_DRAFT":
            row = engine.normalize(
                client.op("feature.show", {"model": name, "feature": feature["id"]})
            )
            definition = row.get("native_definition")
            if not isinstance(definition, dict) or definition.get("complete") is not True:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "native draft definition is incomplete",
                    {
                        "feature_id": feature["id"],
                        "readback": definition,
                        "_untrusted": ["readback"],
                    },
                )
            result["definitions"][feature["id"]] = definition
    return result


def _datum(state, ref):
    rows = [x for x in state["reference_geometry"]["items"] if x.get("ref") == ref]
    if len(rows) != 1 or rows[0].get("kind") != "datum_plane" or rows[0].get("type") != "plane":
        raise Error("E_UNSUPPORTED", "bounded draft requires an actual readable datum plane")
    row = rows[0]
    if (
        row.get("id") is None
        or not isinstance(row.get("feature"), dict)
        or row["feature"].get("id") is None
    ):
        raise Error("E_VERIFY_INCOMPLETE", "native datum item/owner identity is unavailable")
    normal, origin = prismatic.point(row.get("normal")), prismatic.point(row.get("origin"))
    if not prismatic.close(math.sqrt(sum(v * v for v in normal)), 1):
        raise Error("E_VERIFY_INCOMPLETE", "native datum normal is incomplete")
    return {
        "ref": ref,
        "id": row.get("id"),
        "feature": row.get("feature"),
        "normal": list(normal),
        "position_mm": sum(a * b for a, b in zip(normal, origin, strict=True)),
    }


def intent(request, before):
    q = request
    angle = q["angle"]
    if q.get("units") != "mm" or not float(angle).is_integer() or not 1 <= abs(angle) <= 15:
        raise Error(
            "E_UNSUPPORTED", "bounded draft supports mm prisms and whole-degree signed angles 1..15"
        )
    if q.get("flip_pull") or q["pull"] != q["hinge"]:
        raise Error("E_UNSUPPORTED", "use the same top datum for neutral plane and unflipped pull")
    part = before["parts"][before["model"]["model"]]
    constructors = [
        f
        for f in part["features"]
        if f.get("visible") is True
        and f["type"] not in ("FEATTYPE_DATUM_PLANE", "FEATTYPE_DATUM_AXIS", "FEATTYPE_COORD_SYS")
    ]
    if (
        len(constructors) != 1
        or constructors[0]["type"] != "FEATTYPE_PROTRUSION"
        or constructors[0]["status"] != "FEAT_ACTIVE"
        or part["relations"]
    ):
        raise Error(
            "E_UNSUPPORTED",
            "bounded draft requires one standalone editable prism without relations",
        )
    regions, bounds = prismatic.regions(before["geometry"])
    faces = [x for x in before["geometry"]["items"] if x["kind"] == "surface"]
    if (
        len(faces) != 6
        or any(
            len(f.get("boundary_loops", [])) != 1 or len(f["boundary_loops"][0]) != 4 for f in faces
        )
        or not all(c["passed"] for c in prismatic.shape_checks(before["geometry"], bounds))
    ):
        raise Error(
            "E_UNSUPPORTED", "draft proof is limited to six complete rectangular prism faces"
        )
    lo, hi = bounds
    selected = regions.get((0, 1, hi[0]), {}).get("faces", [])
    if selected != q["surfaces"]:
        raise Error(
            "E_UNSUPPORTED",
            "select the one positive-X prism wall",
            {
                "requested": q["surfaces"],
                "supported": selected,
                "_untrusted": ["requested", "supported"],
            },
        )
    plane = _datum(before, q["hinge"])
    if plane["normal"] != [0, 0, 1] or not prismatic.close(plane["position_mm"], hi[2]):
        raise Error(
            "E_UNSUPPORTED",
            "neutral/pull datum must be at maximum Z with normal +Z",
            {"observed": plane, "top_z_mm": hi[2], "_untrusted": ["observed"]},
        )
    width, depth, height = [b - a for a, b in zip(lo, hi, strict=True)]
    bottom_width = width - height * math.tan(math.radians(angle))
    if bottom_width <= 10 * prismatic.TOL:
        raise Error(
            "E_VALIDATION",
            "requested draft closes or crosses the opposite wall",
            {"bottom_width_mm": bottom_width},
        )
    if not prismatic.close(before["model"]["mass_properties"]["volume"], width * depth * height):
        raise Error("E_VERIFY_INCOMPLETE", "prism volume contradicts its complete boundary")
    return {
        "profile": PROFILE,
        "name_intent": building.feature_name_intent(q),
        "bounds_mm": bounds,
        "body": before["geometry"]["body"],
        "surfaces": selected,
        "hinge": q["hinge"],
        "pull": q["pull"],
        "datum": plane,
        "pull_direction": [0, 0, 1],
        "angle_degrees": angle,
        "neutral_z_mm": hi[2],
        "bottom_selected_x_mm": lo[0] + bottom_width,
        "expected_volume_mm3": depth * height * (width + bottom_width) / 2,
    }


def _segment(a, b):
    return tuple(sorted((prismatic.point(list(a)), prismatic.point(list(b)))))


def _polygon_area(vertices):
    first = vertices[0]
    total = [0.0] * 3
    for i in range(1, len(vertices) - 1):
        a = [v - u for u, v in zip(first, vertices[i], strict=True)]
        b = [v - u for u, v in zip(first, vertices[i + 1], strict=True)]
        cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
        total = [u + v for u, v in zip(total, cross, strict=True)]
    return math.sqrt(sum(v * v for v in total)) / 2


def expected_faces(wanted):
    lo, hi = wanted["bounds_mm"]
    angle = math.radians(wanted["angle_degrees"])
    result = {}
    for axis in range(3):
        other = [i for i in range(3) if i != axis]
        for sign, value in ((-1, lo[axis]), (1, hi[axis])):
            vertices = []
            for a, b in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = [0.0] * 3
                point[axis] = value
                point[other[0]] = (lo, hi)[a][other[0]]
                point[other[1]] = (lo, hi)[b][other[1]]
                if point[0] == hi[0]:
                    point[0] += (point[2] - hi[2]) * math.tan(angle)
                vertices.append(point)
            normal = [0.0] * 3
            normal[axis] = sign
            if axis == 0 and sign == 1:
                normal = [math.cos(angle), 0, -math.sin(angle)]
            result[f"{axis}:{sign}"] = {
                "normal": list(prismatic.point(normal)),
                "boundary": sorted(
                    _segment(a, b)
                    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True)
                ),
                "area": _polygon_area(vertices),
            }
    return result


def shape_checks(data, wanted, feature_id=None):
    if data.get("complete") is not True or data.get("body") != wanted["body"]:
        raise Error("E_VERIFY_INCOMPLETE", "complete same native body required for draft proof")
    items = data.get("items")
    if not isinstance(items, list) or any(not isinstance(x, dict) or x.get("error") for x in items):
        raise Error("E_VERIFY_INCOMPLETE", "draft body inventory is incomplete")
    if any(
        x.get("kind") not in ("edge", "surface")
        or x.get("ref") != str(x.get("kind")) + ":" + str(x.get("id"))
        for x in items
    ) or len({x["ref"] for x in items}) != len(items):
        raise Error("E_VERIFY_INCOMPLETE", "draft physical identities are incomplete or repeated")
    faces = {x["ref"]: x for x in items if x["kind"] == "surface"}
    edges = {x["ref"]: x for x in items if x["kind"] == "edge"}
    if len(faces) != 6 or len(edges) != 12:
        raise Error("E_UNSUPPORTED", "draft body exceeds the six-plane, twelve-line proof profile")
    uses = {ref: [] for ref in edges}
    observed = []
    for ref, face in faces.items():
        if (
            face.get("type") != "plane"
            or len(face.get("boundary_loops", [])) != 1
            or len(face["boundary_loops"][0]) != 4
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "one complete quadrilateral per draft face is required"
            )
        loop = face["boundary_loops"][0]
        prismatic._closed_loop(loop, edges, ref)
        normal, origin = prismatic.point(face.get("normal")), prismatic.point(face.get("origin"))
        if not prismatic.close(math.sqrt(sum(v * v for v in normal)), 1):
            raise Error("E_VERIFY_INCOMPLETE", "draft outward face normal is incomplete")
        boundary = []
        for edge_ref in loop:
            edge = edges[edge_ref]
            uses[edge_ref].append(ref)
            a, b = prismatic.point(edge.get("start")), prismatic.point(edge.get("end"))
            if edge.get("type") != "line" or not prismatic.close(
                edge.get("length"), math.dist(a, b)
            ):
                raise Error("E_VERIFY_INCOMPLETE", "draft physical line and endpoints disagree")
            # Test the original normal precision against each point; never derive a box from intent.
            for point in (a, b):
                if not math.isclose(
                    sum(n * (v - u) for n, u, v in zip(face["normal"], origin, point, strict=True)),
                    0,
                    abs_tol=2e-6,
                ):
                    raise Error(
                        "E_VERIFY_INCOMPLETE", "draft contour lies outside its native plane"
                    )
            boundary.append(_segment(a, b))
        observed.append(
            {
                "ref": ref,
                "feature": face.get("feature"),
                "normal": list(normal),
                "area": face.get("area"),
                "boundary": sorted(boundary),
            }
        )
    for ref, edge in edges.items():
        adjacent = edge.get("surfaces")
        if (
            not isinstance(adjacent, list)
            or len(adjacent) != 2
            or len(set(adjacent)) != 2
            or set(adjacent) != set(uses[ref])
            or len(uses[ref]) != 2
        ):
            raise Error("E_VERIFY_INCOMPLETE", "draft edge needs exactly two actual owning faces")
    checks = []
    for label, expected in expected_faces(wanted).items():
        matching = [
            f
            for f in observed
            if f["normal"] == expected["normal"]
            and f["boundary"] == expected["boundary"]
            and prismatic.close(f["area"], expected["area"])
            and (
                label != "0:1"
                or feature_id is None
                or str((f.get("feature") or {}).get("id")) == str(feature_id)
            )
        ]
        checks.append(
            engine.check(
                "complete_draft_region:" + label,
                len(matching) == 1,
                expected=expected,
                observed=observed if not matching else matching,
            )
        )
    return checks


def verify(before, wanted, after, feature_id):
    name = before["model"]["model"]
    old = {f["id"]: f for f in before["parts"][name]["features"]}
    new = {f["id"]: f for f in after["parts"][name]["features"]}
    definition = after["definitions"].get(feature_id) or {}
    checks = [
        engine.check(
            "one_active_draft_added",
            set(new) - set(old) == {feature_id}
            and new.get(feature_id, {}).get("type") == "FEATTYPE_DRAFT"
            and new.get(feature_id, {}).get("status") == "FEAT_ACTIVE",
        ),
        engine.check(
            "original_features_unchanged",
            all(
                all(
                    f.get(k) == new.get(i, {}).get(k)
                    for k in ("id", "name", "type", "status", "visible")
                )
                for i, f in old.items()
            ),
        ),
        engine.check(
            "native_selected_wall_and_neutral_pull",
            definition.get("complete") is True
            and definition.get("kind") == "draft"
            and definition.get("selected") == wanted["surfaces"]
            and definition.get("hinge") == wanted["hinge"]
            and definition.get("pull") == wanted["pull"]
            and definition.get("flip_pull") is False
            and prismatic.close(definition.get("angle"), wanted["angle_degrees"])
            and definition.get("split") == "none"
            and definition.get("mode") == "constant"
            and definition.get("neutral_type") == "plane"
            and definition.get("independent") is True
            and definition.get("include_tangent") is True
            and definition.get("selection_rule") == "single_included_surface"
            and definition.get("rule_count") == 0,
            expected=wanted,
            observed=definition,
        ),
        engine.check(
            "fixed_native_neutral_datum", _datum(after, wanted["hinge"]) == wanted["datum"]
        ),
        engine.check(
            "draft_volume",
            prismatic.close(
                after["model"]["mass_properties"]["volume"], wanted["expected_volume_mm3"]
            ),
            expected=wanted["expected_volume_mm3"],
            observed=after["model"]["mass_properties"]["volume"],
        ),
    ]
    return (
        checks
        + building.feature_readback_checks(
            before["parts"][name]["features"],
            after["parts"][name]["features"],
            feature_id,
            "FEATTYPE_DRAFT",
            wanted.get("name_intent"),
        )
        + prismatic.protected_checks(before, after)
        + shape_checks(after["geometry"], wanted, feature_id)
    )


def checked_plan(client, plan, request, options=None):
    before = snapshot(client, plan.target)
    if (options or {}).get("confirm"):
        retained = operations.get(safety.token_operation(options["confirm"]))["driver_plan"][
            "base_snapshot"
        ]["extensions"]["creo"]["observation"]
        if digest(retained.get("draft_before")) != digest(before):
            raise Error(
                "E_CONFLICT",
                "draft geometry, references or protected state changed after preview",
                {"conflict": "state_drift", "dispatch_state": "not_started"},
            )
    wanted = intent(request, before)
    plan.binding |= {"draft_before": before, "draft_intent": wanted}
    plan.preview["draft_intent"] = wanted
    plan.preview["limits"] = [
        "one standalone rectangular mm prism; one positive-X wall; top +Z datum as neutral/pull",
        "constant unsplit whole-degree angle 1..15, either sign; no hollow bodies or workflow",
        "top footprint and opposite wall fixed; bottom and Y-wall trimming explicitly predicted",
    ]
    plan.before = before
    plan.observe = lambda c: snapshot(c, plan.target)
    previous = plan.verify

    def check(c, data):
        result, verification = previous(c, data)
        after = snapshot(c, plan.target)
        verification["checks"].extend(verify(before, wanted, after, str(data["feature"]["id"])))
        result["draft_readback"] = {
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
    stored = plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
    before, wanted = stored.get("draft_before"), stored.get("draft_intent")
    if not before or not wanted or wanted.get("profile") != PROFILE:
        raise Error("E_VERIFY_INCOMPLETE", "frozen draft reference and boundary intent unavailable")
    building.retained_feature_name_intent(run, wanted)
    if client.health()["service_instance_id"] != plan["target"]["instance_id"]:
        raise Error("E_VERIFY_INCOMPLETE", "another instance cannot establish this draft outcome")
    after = snapshot(client, run["target"])
    old = {f["id"] for f in before["parts"][run["target"]]["features"]}
    added = [f for f in after["parts"][run["target"]]["features"] if f["id"] not in old]
    checks = [
        engine.check(
            "one_identified_draft", len(added) == 1 and added[0]["type"] == "FEATTYPE_DRAFT"
        )
    ]
    if checks[0]["passed"]:
        checks += verify(before, wanted, after, added[0]["id"])
    stable = digest(after) == digest(snapshot(client, run["target"]))
    checks.append(engine.check("independent_draft_readback_stable", stable))
    accepted = all(c["passed"] for c in checks)
    complete = (
        len(added) == 1 and (after["definitions"].get(added[0]["id"]) or {}).get("complete") is True
    )
    return {
        "accepted": accepted,
        "checks": checks,
        "intent": wanted,
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
        "coverage": (
            "frozen feature name, selected wall, signed angle, native neutral/pull "
            "and complete current planar boundaries; no replay"
        ),
    }


def retained_evidence_sufficient(run, proof):
    stored = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, wanted = stored.get("draft_before"), stored.get("draft_intent")
    if not before or not wanted or wanted != proof.get("intent"):
        raise Error("E_VERIFY_INCOMPLETE", "retained draft proof lacks frozen intent")
    building.retained_feature_name_intent(run, wanted)
    after = proof.get("current") or {}
    old = {f["id"] for f in before["parts"][run["target"]]["features"]}
    added = [f for f in after["parts"][run["target"]]["features"] if f["id"] not in old]
    accepted = (
        len(added) == 1
        and added[0]["type"] == "FEATTYPE_DRAFT"
        and all(c["passed"] for c in verify(before, wanted, after, added[0]["id"]))
    )
    if proof.get("accepted") is not accepted:
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained draft conclusion lacks complete current geometry proof"
        )
