"""Explicit eight-vertex wedge fixture. No native-CAD qualification is claimed."""

import copy
import math


def reshape(world, model, feature, angle, *, wrong_wall=False):
    lo, hi = feature["draft_bounds"]
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    delta = (z1 - z0) * math.tan(math.radians(angle))
    left = x0 + delta if wrong_wall else x0
    right = x1 if wrong_wall else x1 - delta
    a, b, c, d = (left, y0, z0), (right, y0, z0), (right, y1, z0), (left, y1, z0)
    e, f, g, h = (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)
    polygons = {
        "2:-1": [a, d, c, b],
        "2:1": [e, f, g, h],
        "0:-1": [a, e, h, d],
        "0:1": [b, c, g, f],
        "1:-1": [a, b, f, e],
        "1:1": [d, h, g, c],
    }
    geometry = copy.deepcopy(feature["draft_auxiliary"])
    edges = {}
    for label, vertices in polygons.items():
        face = copy.deepcopy(feature["draft_original_faces"][label])
        if label == ("0:-1" if wrong_wall else "0:1"):
            face["id"] = feature["draft_surface_id"]
            face["ref"] = "surface:" + str(face["id"])
            face["feature"] = {"id": feature["id"], "name": feature["name"]}
        cross = [0.0] * 3
        for i in (1, 2):
            u = [v - o for o, v in zip(vertices[0], vertices[i], strict=True)]
            v = [v - o for o, v in zip(vertices[0], vertices[i + 1], strict=True)]
            part = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
            cross = [x + y for x, y in zip(cross, part, strict=True)]
        length = math.sqrt(sum(v * v for v in cross))
        face.update(
            normal=[v / length for v in cross],
            origin=list(vertices[0]),
            area=length / 2,
            bbox=[
                [min(p[i] for p in vertices) for i in range(3)],
                [max(p[i] for p in vertices) for i in range(3)],
            ],
        )
        refs = []
        for start, end in zip(vertices, vertices[1:] + vertices[:1], strict=True):
            key = tuple(sorted((start, end)))
            if key not in edges:
                gid = world._gid(model)
                size = math.dist(start, end)
                edges[key] = {
                    "id": gid,
                    "ref": "edge:" + str(gid),
                    "kind": "edge",
                    "type": "line",
                    "start": list(start),
                    "end": list(end),
                    "length": size,
                    "direction": [(v - u) / size for u, v in zip(start, end, strict=True)],
                    "surfaces": [],
                    "feature": copy.deepcopy(face["feature"]),
                }
            edges[key]["surfaces"].append(face["ref"])
            refs.append(edges[key]["ref"])
        face["boundary_loops"] = [refs]
        geometry.append(face)
    geometry.extend(edges.values())
    model["geometry"] = geometry
    model["volume"] = (y1 - y0) * (z1 - z0) * ((x1 - x0) + (right - left)) / 2
    vertices = [a, b, c, d, e, f, g, h]
    model["bbox"] = [
        [min(p[i] for p in vertices) for i in range(3)],
        [max(p[i] for p in vertices) for i in range(3)],
    ]


def create(world, name, model, request):
    before = model["volume"]
    points = [g[k] for g in model["geometry"] if g["kind"] == "edge" for k in ("start", "end")]
    bounds = [
        [min(p[i] for p in points) for i in range(3)],
        [max(p[i] for p in points) for i in range(3)],
    ]
    faces = {}
    for face in model["geometry"]:
        if face["kind"] == "surface":
            axis = next(i for i, n in enumerate(face["normal"]) if n)
            faces[f"{axis}:{1 if face['normal'][axis] > 0 else -1}"] = copy.deepcopy(face)
    feature = world.new_feature(model, request.get("name"), "FEATTYPE_DRAFT", "DRAFT")
    feature.update(
        draft_bounds=bounds,
        draft_original_faces=faces,
        draft_auxiliary=copy.deepcopy(
            [g for g in model["geometry"] if g["kind"] not in ("surface", "edge")]
        ),
        draft_surface_id=world._gid(model),
    )
    feature["native_definition"] = {
        "complete": True,
        "kind": "draft",
        "selected": list(request["surfaces"]),
        "hinge": request["hinge"],
        "pull": request.get("pull", request["hinge"]),
        "flip_pull": bool(request.get("flip_pull")),
        "angle": request["angle"],
        "split": "none",
        "mode": "constant",
        "neutral_type": "plane",
        "independent": True,
        "include_tangent": True,
        "selection_rule": "single_included_surface",
        "rule_count": 0,
    }
    world._dimension(model, feature, request["angle"], kind="angle")
    reshape(world, model, feature, request["angle"])
    selected = [
        g
        for g in model["geometry"]
        if g["kind"] == "surface" and g["id"] == feature["draft_surface_id"]
    ]
    return world.built(name, model, feature, before, drafted=selected)
