"""Independent cell-union mesh for one rectangular housing rib; no native CAD claim.

The fixture samples material occupancy on a coordinate grid and emits the exposed cell
rectangles. It does not import production intent, region, boundary or shape generators.
"""

import copy
import itertools
import math


def reshape(world, model, feature, thickness, *, shift_y=0, disconnected=False, flip=False):
    bounds = feature["rib_shell_bounds"]
    lower, upper = bounds
    wall = feature["rib_shell_thickness"]
    inner_lower = [v + wall for v in lower]
    inner_upper = [upper[0] - wall, upper[1] - wall, upper[2]]
    points = feature["rib_points"]
    x0, x1 = sorted(p[0] for p in points)
    ztop = -points[0][1]
    bottom, top = (ztop, upper[2]) if flip else (inner_lower[2], ztop)
    if disconnected:
        x0, x1, bottom = x0 + 1, x1 - 1, bottom + 1
    rib_lower = [x0, shift_y - thickness / 2, bottom]
    rib_upper = [x1, shift_y + thickness / 2, top]
    coordinates = [
        sorted({lower[i], upper[i], inner_lower[i], inner_upper[i], rib_lower[i], rib_upper[i]})
        for i in range(3)
    ]

    def within(point, lo, hi):
        return all(a < p < b for a, p, b in zip(lo, point, hi, strict=True))

    occupied = set()
    volume = 0.0
    for index in itertools.product(*(range(len(axis) - 1) for axis in coordinates)):
        lo = [coordinates[i][index[i]] for i in range(3)]
        hi = [coordinates[i][index[i] + 1] for i in range(3)]
        midpoint = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
        shell = within(midpoint, lower, upper) and not within(midpoint, inner_lower, inner_upper)
        if shell or within(midpoint, rib_lower, rib_upper):
            occupied.add(index)
            volume += math.prod(b - a for a, b in zip(lo, hi, strict=True))

    owner = {"id": feature["id"], "name": feature["name"]}
    geometry = [g for g in model["geometry"] if g["kind"] not in ("surface", "edge")]
    edges = {}
    preserved_walls = set()
    for index in sorted(occupied):
        for axis, sign in itertools.product(range(3), (-1, 1)):
            adjacent = list(index)
            adjacent[axis] += sign
            if tuple(adjacent) in occupied:
                continue
            u, v = [i for i in range(3) if i != axis]
            constant = coordinates[axis][index[axis] + (sign > 0)]
            corners = []
            for du, dv in ((0, 0), (1, 0), (1, 1), (0, 1)):
                point = [0.0, 0.0, 0.0]
                point[axis] = constant
                point[u] = coordinates[u][index[u] + du]
                point[v] = coordinates[v][index[v] + dv]
                corners.append(tuple(point))
            wall_source = next(
                (
                    row
                    for row in feature.get("rib_wall_sources", [])
                    if axis == 0
                    and row["normal"][axis] == sign
                    and row["origin"][axis] == constant
                    and row["id"] not in preserved_walls
                ),
                None,
            )
            ident = wall_source["id"] if wall_source else world._gid(model)
            if wall_source:
                preserved_walls.add(ident)
            ref = "surface:" + str(ident)
            normal = [0, 0, 0]
            normal[axis] = sign
            edge_refs = []
            for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
                key = tuple(sorted((a, b)))
                if key not in edges:
                    edge_id = world._gid(model)
                    length = math.dist(a, b)
                    edges[key] = {
                        "id": edge_id,
                        "ref": "edge:" + str(edge_id),
                        "kind": "edge",
                        "type": "line",
                        "feature": copy.deepcopy(owner),
                        "start": list(a),
                        "end": list(b),
                        "length": length,
                        "direction": [(y - x) / length for x, y in zip(a, b, strict=True)],
                        "surfaces": [],
                    }
                edges[key]["surfaces"].append(ref)
                edge_refs.append(edges[key]["ref"])
            geometry.append(
                {
                    "id": ident,
                    "ref": ref,
                    "kind": "surface",
                    "type": "plane",
                    "feature": copy.deepcopy(wall_source["feature"] if wall_source else owner),
                    "normal": normal,
                    "origin": list(corners[0]),
                    "area": (coordinates[u][index[u] + 1] - coordinates[u][index[u]])
                    * (coordinates[v][index[v] + 1] - coordinates[v][index[v]]),
                    "bbox": [
                        [min(p[i] for p in corners) for i in range(3)],
                        [max(p[i] for p in corners) for i in range(3)],
                    ],
                    "boundary_loops": [edge_refs],
                }
            )
    assert all(len(edge["surfaces"]) == 2 for edge in edges.values())
    geometry.extend(edges.values())
    model["geometry"] = geometry
    model["volume"] = volume
    model["bbox"] = copy.deepcopy(bounds)


def create(world, request):
    name, model = world.model(request["model"])
    shell = next(f for f in model["features"] if f["type"] == "FEATTYPE_SHELL")
    before = model["volume"]
    walls = []
    for sign, x in (
        (1, shell["shell_bounds"][0][0] + shell["native_definition"]["thickness"]),
        (-1, shell["shell_bounds"][1][0] - shell["native_definition"]["thickness"]),
    ):
        walls.append(
            copy.deepcopy(
                next(
                    row
                    for row in model["geometry"]
                    if row["kind"] == "surface"
                    and row["normal"] == [sign, 0, 0]
                    and row["origin"][0] == x
                )
            )
        )
    auxiliary = None
    if getattr(world, "rib_fixture_auxiliary", True):
        parents = [world.feature(model, ref)["id"] for ref in ("TOP", "RIGHT")]
        auxiliary = world.new_feature(
            model, None, "FEATTYPE_DATUM_PLANE", "INTERNAL_RIB", parents=parents
        )
        auxiliary["name"], auxiliary["visible"] = None, False
        plane = world.item(model, request["sketch"]["plane"])
        geometry_id = world._gid(model)
        auxiliary["auxiliary_surface"] = {
            "id": str(geometry_id),
            "ref": "surface:" + str(geometry_id),
            "type": "plane",
            "normal": copy.deepcopy(plane["normal"]),
            "origin": copy.deepcopy(plane["origin"]),
        }
        model["geometry"].append(
            auxiliary["auxiliary_surface"]
            | {
                "kind": "datum_plane",
                "type": "plane",
                "feature": {"id": auxiliary["id"], "name": auxiliary["name"]},
            }
        )
    feature = world.new_feature(
        model,
        request.get("name"),
        "FEATTYPE_RIB",
        "RIB",
        parents=() if auxiliary is None else (auxiliary["id"],),
    )
    points = copy.deepcopy(request["sketch"]["points"])
    feature.update(
        rib_shell_bounds=copy.deepcopy(shell["shell_bounds"]),
        rib_shell_thickness=shell["native_definition"]["thickness"],
        rib_points=points,
        rib_wall_sources=walls,
    )
    dimension = world._dimension(model, feature, request["thickness"], depth=True)
    # Native DIM_NONE placeholders can be null even when the real element-bound driver exists.
    model["dimensions"][-1]["value"] = None
    feature["native_auxiliary_datums"] = {
        "complete": True,
        "kind": "rib_auxiliary_datum_dependencies",
        "rib_id": str(feature["id"]),
        "items": []
        if auxiliary is None
        else [
            {
                **world.row(auxiliary),
                "id": str(auxiliary["id"]),
                "parents": [str(ident) for ident in auxiliary["parents"]],
                "children": [str(ident) for ident in auxiliary["children"]],
                "surface": copy.deepcopy(auxiliary["auxiliary_surface"]),
            }
        ],
        "source": "independent loopback feature dependencies and datum surface; no native claim",
    }
    feature["native_definition"] = {
        "complete": True,
        "kind": "rib",
        "form": "extrude",
        "body_use": "selected",
        "body_id": -5778,
        "thickness": request["thickness"],
        "side": request.get("side", "symmetric"),
        "fill": request.get("fill", "left"),
        "plane": request["sketch"]["plane"],
        "orient_ref": request["sketch"]["orient_ref"],
        "plane_view_dir": 1,
        "orient": request["sketch"].get("orient", "right"),
        "orient_dir": 1,
        "thickness_dimension": {k: dimension[k] for k in ("id", "name", "value")},
    }
    feature["native_section_readback"] = {
        "returned": 0,
        "location": "1 0 0 0 0 -1 0 1 0 0 0 0",
        "entities_read": "#1 L " + " ".join(str(v) for point in points for v in point),
    }
    references = request["sketch"].get("references") or ["RIGHT", "FRONT"]
    projection_rows = []
    for entity_id, reference in enumerate(references, start=2):
        item = world.item(model, reference)
        projection_rows.append(
            f"#{entity_id} {item['id']} surface {name.rsplit('.', 1)[0]} part "
            f"{item['ref']} 1042 1 0"
        )
        feature["native_section_readback"]["entities_read"] += f";#{entity_id} R 0 0 0 0"
    roles = ["#1 0 0", "#2 1 0", "#3 1 0"]
    for entity_id, wall_source in enumerate(walls, start=4):
        if getattr(world, "rib_fixture_wall_construction", False):
            x = wall_source["origin"][0]
            feature["native_section_readback"]["entities_read"] += f";#{entity_id} L {x} 0 {x} 18"
            roles.append(f"#{entity_id} 0 1")
        else:
            projection_rows.append(
                f"#{entity_id} {wall_source['id']} surface {name.rsplit('.', 1)[0]} part - 1042 1 0"
            )
            x = wall_source["origin"][0]
            feature["native_section_readback"]["entities_read"] += f";#{entity_id} R {x} 0 {x} 18"
            roles.append(f"#{entity_id} 1 0")
    feature["native_section_readback"].update(
        section_entity_count=5,
        projection_refs_complete=1,
        projection_ref_count=len(projection_rows),
        projection_refs=";".join(projection_rows),
        section_entity_roles=";".join(roles),
        section_entity_roles_complete=1,
        section_entity_role_count=5,
    )
    reshape(world, model, feature, request["thickness"])
    feature["adds"] = model["volume"] - before
    return world.built(
        name,
        model,
        feature,
        before,
        fill=request.get("fill", "left"),
        fill_tried=[],
        sketch={"engine": "native"},
    )


def dispatch(world, original, op, request):
    """Extend only the owning test's World, without editing shared fixture behavior."""
    if op == "feature.rib":
        return create(world, request)
    if op == "feature.show":
        result = original(op, request)
        _, model = world.model(request["model"])
        feature = world.feature(model, request["feature"])
        if "native_auxiliary_datums" in feature:
            result["native_auxiliary_datums"] = copy.deepcopy(feature["native_auxiliary_datums"])
        return result
    if op == "dimension.set":
        name, model = world.model(request["model"])
        before = model["volume"]
        result = original(op, request)
        feature = world.feature(model, result["dimension"]["feature"]["id"])
        if feature["type"] == "FEATTYPE_RIB":
            definition = feature["native_definition"]
            definition["thickness"] = request["value"]
            definition["thickness_dimension"]["value"] = request["value"]
            reshape(world, model, feature, request["value"])
            result["volume"] = {
                "before": before,
                "after": model["volume"],
                "change": model["volume"] - before,
            }
        return result
    return original(op, request)
