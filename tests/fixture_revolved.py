"""Analytic loopback rows for orthogonal full revolves; never used by the product."""

import math


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def axis_geometry(refs):
    if len(refs) == 2:
        a, b = refs
        n, m = a["normal"], b["normal"]
        direction = cross(n, m)
        size = sum(x * x for x in direction)
        u = sum(x * y for x, y in zip(n, a["origin"], strict=True))
        v = sum(x * y for x, y in zip(m, b["origin"], strict=True))
        point = [
            (u * x + v * y) / size
            for x, y in zip(cross(m, direction), cross(direction, n), strict=True)
        ]
    elif refs[0].get("axis"):
        point, direction = refs[0]["axis"]["origin"], refs[0]["axis"]["direction"]
    else:
        point, direction = refs[0]["start"], refs[0]["direction"]
    return {
        "start": [p - 10 * d for p, d in zip(point, direction, strict=True)],
        "end": [p + 10 * d for p, d in zip(point, direction, strict=True)],
        "direction": direction,
    }


def populate(world, model, feature, request):
    sketch = request["sketch"]
    plane, orient = [world.item(model, sketch[k]) for k in ("plane", "orient_ref")]
    z, x, origin = plane["normal"], orient["normal"], plane["origin"]
    y = cross(z, x)
    if sketch.get("orient", "right") == "left":
        x, y = [[-v for v in row] for row in (x, y)]
    profile = sketch["profile"]
    if profile["type"] == "rectangle":
        u, v = profile.get("center", [0, 0])
        w, h = profile["width"] / 2, profile["height"] / 2
        points = [[u - w, v - h], [u + w, v - h], [u + w, v + h], [u - w, v + h]]
    else:
        points = profile["points"]

    def model_point(p):
        return [o + p[0] * a + p[1] * b for o, a, b in zip(origin, x, y, strict=True)]

    external = isinstance(request["axis"], str)
    if external:
        selected = world.item(model, request["axis"])
        direction, point = selected["direction"], selected["start"]
    else:
        point, end = [model_point(p) for p in request["axis"]]
        direction = [b - a for a, b in zip(point, end, strict=True)]
    axial = next(i for i, v in enumerate(direction) if abs(v) > 1e-8)
    size = math.sqrt(sum(v * v for v in direction))
    direction = [v / size for v in direction]
    anchor = [v if i != axial else 0 for i, v in enumerate(point)]
    world_points = [model_point(p) for p in points]
    rt = [
        [math.sqrt(sum((p[i] - anchor[i]) ** 2 for i in range(3) if i != axial)), p[axial]]
        for p in world_points
    ]
    volume = abs(
        math.pi
        * sum(
            a[0] ** 2 * (b[1] - a[1])
            for a, b in zip(rt, rt[1:] + rt[:1], strict=True)
            if abs(a[0] - b[0]) < 1e-8
        )
    )
    model["volume"] += volume - feature["adds"]
    feature["adds"] = volume
    for a, b in zip(rt, rt[1:] + rt[:1], strict=True):
        if abs(a[0] - b[0]) < 1e-8:
            if a[0] < 1e-8:
                continue
            lo, hi = sorted((a[1], b[1]))
            radius = a[0]
            row = {
                "type": "cylinder",
                "radius": radius,
                "axis": {"origin": anchor, "direction": direction},
                "area": 2 * math.pi * radius * (hi - lo),
            }
        else:
            lo = hi = a[1]
            radius = max(a[0], b[0])
            pos = list(anchor)
            pos[axial] = lo
            row = {
                "type": "plane",
                "origin": pos,
                "normal": direction,
                "area": math.pi * abs(a[0] ** 2 - b[0] ** 2),
                "fixture_radial_interval": sorted((a[0], b[0])),
            }
        bbox = [[v - radius for v in anchor], [v + radius for v in anchor]]
        bbox[0][axial], bbox[1][axial] = lo, hi
        ident = world._gid(model)
        model["geometry"].append(
            row
            | {
                "ref": f"surface:{ident}",
                "kind": "surface",
                "id": ident,
                "feature": {"id": feature["id"], "name": feature["name"]},
                "bbox": bbox,
            }
        )
    radii = [p[0] for p in rt]
    model["bbox"] = [[v - max(radii) for v in anchor], [v + max(radii) for v in anchor]]
    model["bbox"][0][axial], model["bbox"][1][axial] = min(p[1] for p in rt), max(p[1] for p in rt)
    own = [g for g in model["geometry"] if g.get("feature", {}).get("id") == feature["id"]]
    for wall in [g for g in own if g["type"] == "cylinder"]:
        for station in (wall["bbox"][0][axial], wall["bbox"][1][axial]):
            cap = next(
                g
                for g in own
                if g["type"] == "plane"
                and g["origin"][axial] == station
                and wall["radius"] in g["fixture_radial_interval"]
            )
            center = list(anchor)
            center[axial] = station
            endpoint = list(center)
            endpoint[(axial + 1) % 3] += wall["radius"]
            ident = world._gid(model)
            model["geometry"].append(
                {
                    "ref": f"edge:{ident}",
                    "id": ident,
                    "kind": "edge",
                    "type": "circle",
                    "feature": {"id": feature["id"], "name": feature["name"]},
                    "center": center,
                    "normal": direction,
                    "radius": wall["radius"],
                    "length": 2 * math.pi * wall["radius"],
                    "start": endpoint,
                    "end": endpoint,
                    "surfaces": [wall["ref"], cap["ref"]],
                }
            )
    rows = [
        f"#{i} L {a[0]} {a[1]} {b[0]} {b[1]}"
        for i, (a, b) in enumerate(zip(points, points[1:] + points[:1], strict=True))
    ]
    if not external:
        a, b = request["axis"]
        rows.append(f"#99 K {a[0]} {a[1]} {b[0]} {b[1]}")
    feature["native_section_readback"] = {
        "returned": 0,
        "location": " ".join(str(v) for row in (x, y, z, origin) for v in row),
        "entities_read": ";".join(rows),
    }
    feature["native_definition"] = {
        "complete": True,
        "kind": "revolve",
        "angle": request["angle"],
        "solid": True,
        "add_material": True,
        "no_thin": True,
        "from_none": True,
        "angle_mode": "symmetric" if request.get("side") == "symmetric" else "one_side",
        "sketch_plane": sketch["plane"],
        "orient_ref": sketch["orient_ref"],
        "axis_kind": "external" if external else "sketched",
    }
    if external:
        feature["native_definition"]["axis_reference"] = request["axis"]
