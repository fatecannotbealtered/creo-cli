"""Small independent polygon mesh fixture, not a CAD or production geometry generator."""

import copy
import math


def read_geometry(name, model):
    items = copy.deepcopy([g for g in model["geometry"] if g["kind"] in ("surface", "edge")])
    faces = [g for g in items if g["kind"] == "surface"]
    edges = {g["ref"]: g for g in items if g["kind"] == "edge"}
    for face in faces:
        if face.get("type") != "plane":
            return {
                "model": name,
                "complete": False,
                "profile": "prismatic-shell-v1",
                "error": {"code": "E_UNSUPPORTED", "message": "curved fixture surface"},
            }
        if "area" not in face:
            lengths = [b - a for a, b in zip(*face["bbox"], strict=True)]
            face["area"] = math.prod(v for v in lengths if v != 0)
        if "boundary_loops" not in face:
            face["boundary_loops"] = [
                [ref for ref, edge in edges.items() if face["ref"] in edge["surfaces"]]
            ]
    return {
        "model": name,
        "units": copy.deepcopy(model["units"]),
        "complete": True,
        "profile": "prismatic-shell-v1",
        "body": {"id": -5778, "state": "BODY_STATE_ACTIVE"},
        "items": items,
        "source": "explicit simulated polygon mesh; not native evidence",
    }


def hollow(world, model, feature, thickness, bounds):
    """Construct faces by polygon boundaries; each undirected segment has two owners."""
    x0, y0, z0 = bounds[0]
    x1, y1, z1 = bounds[1]
    a, b, c, d, floor = (
        x0 + thickness,
        x1 - thickness,
        y0 + thickness,
        y1 - thickness,
        z0 + thickness,
    )
    outer_bottom = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)]
    outer_top = [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    inner_bottom = [(a, c, floor), (b, c, floor), (b, d, floor), (a, d, floor)]
    inner_top = [(a, c, z1), (b, c, z1), (b, d, z1), (a, d, z1)]
    specs = [
        ([0, 0, -1], [outer_bottom], (x1 - x0) * (y1 - y0)),
        ([0, 0, 1], [outer_top, inner_top], (x1 - x0) * (y1 - y0) - (b - a) * (d - c)),
        ([0, 0, 1], [inner_bottom], (b - a) * (d - c)),
    ]
    outside_normals = [[0, -1, 0], [1, 0, 0], [0, 1, 0], [-1, 0, 0]]
    for i, normal in enumerate(outside_normals):
        j = (i + 1) % 4
        specs.append(
            (
                normal,
                [[outer_bottom[i], outer_bottom[j], outer_top[j], outer_top[i]]],
                math.dist(outer_top[i], outer_top[j]) * (z1 - z0),
            )
        )
        specs.append(
            (
                [-v for v in normal],
                [[inner_bottom[i], inner_bottom[j], inner_top[j], inner_top[i]]],
                math.dist(inner_top[i], inner_top[j]) * (z1 - floor),
            )
        )
    owner = {"id": feature["id"], "name": feature["name"]}
    geometry = [g for g in model["geometry"] if g["kind"] not in ("surface", "edge")]
    edges = {}
    for normal, loops, area in specs:
        ident = world._gid(model)
        ref = "surface:" + str(ident)
        points = [p for loop in loops for p in loop]
        face = {
            "id": ident,
            "ref": ref,
            "kind": "surface",
            "type": "plane",
            "feature": owner,
            "normal": normal,
            "origin": list(points[0]),
            "area": area,
            "bbox": [
                [min(p[i] for p in points) for i in range(3)],
                [max(p[i] for p in points) for i in range(3)],
            ],
            "boundary_loops": [],
        }
        for loop in loops:
            refs = []
            for start, end in zip(loop, loop[1:] + loop[:1], strict=True):
                key = tuple(sorted((start, end)))
                if key not in edges:
                    gid = world._gid(model)
                    length = math.dist(start, end)
                    edges[key] = {
                        "id": gid,
                        "ref": "edge:" + str(gid),
                        "kind": "edge",
                        "type": "line",
                        "feature": owner,
                        "start": list(start),
                        "end": list(end),
                        "length": length,
                        "direction": [(v - u) / length for u, v in zip(start, end, strict=True)],
                        "surfaces": [],
                    }
                edge = edges[key]
                edge["surfaces"].append(ref)
                refs.append(edge["ref"])
            face["boundary_loops"].append(refs)
        geometry.append(face)
    assert all(len(e["surfaces"]) == 2 for e in edges.values())
    geometry.extend(edges.values())
    model["geometry"] = geometry
    model["volume"] = (x1 - x0) * (y1 - y0) * (z1 - z0) - (b - a) * (d - c) * (z1 - floor)
    model["bbox"] = copy.deepcopy(bounds)


def create(world, name, model, request):
    points = [g[k] for g in model["geometry"] if g["kind"] == "edge" for k in ("start", "end")]
    bounds = [
        [min(p[i] for p in points) for i in range(3)],
        [max(p[i] for p in points) for i in range(3)],
    ]
    before = model["volume"]
    feature = world.new_feature(model, request.get("name"), "FEATTYPE_SHELL", "SHELL")
    feature["native_definition"] = {
        "complete": True,
        "kind": "shell",
        "thickness": request["thickness"],
        "side": request.get("side", "inside"),
        "removed": list(request.get("remove", [])),
        "body_id": -5778,
        "local_thickness_count": 0,
        "excluded_instruction_count": 0,
    }
    feature["shell_bounds"] = bounds
    world._dimension(model, feature, request["thickness"])
    hollow(world, model, feature, request["thickness"], bounds)
    feature["adds"] = model["volume"] - before
    return world.built(name, model, feature, before)
