"""The substitute's model of geometry, dimensions, parameters, materials and the P2 feature ops.

Part of tests/fixture.py's World. It is written from the service's replies (Geometry.java,
Dimensions.java, ParameterOps.java, Materials.java, Output.java, Features.java) and keeps just
enough state to be read back consistently: faces and edges with ids and coordinates for a
rectangle extruded from FRONT, a named dimension per driving value, a parameter table, a
material with a density. It is not geometry: volumes of placed features follow the same
formulas the service's replies were checked against live, applied without looking at overlap.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from pathlib import Path

LIBRARY = [
    ("ABS", "Standard-Materials_Granta-Design/Plastics", 1.04e-09),
    ("Aluminum_wrought", "Standard-Materials_Granta-Design/Non-ferrous_metals", 2.7e-09),
    ("steel", "Legacy-Materials", 7.827e-09),
    ("Steel_low_carbon", "Standard-Materials_Granta-Design/Ferrous_metals", 7.85e-09),
    ("Stainless_steel_austenitic", "Standard-Materials_Granta-Design/Ferrous_metals", 7.9e-09),
]
LIBRARY_ROOT = "C:\\PTC\\Common Files\\text\\materials-library"
DEFAULT_PARAMETERS = [
    ("DESCRIPTION", "string", "", True),
    ("MODELED_BY", "string", "", True),
    ("PTC_MATERIAL_NAME", "string", "", False),
]
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00SUBSTITUTE, NOT A PICTURE\xff\xd9"
HEADERS = {
    "step": b"ISO-10303-21;\nHEADER;\n/* SUBSTITUTE, NOT A STEP FILE */\n",
    "iges": b"SUBSTITUTE, NOT AN IGES FILE".ljust(72) + b"S      1\n",
    "pdf": b"%PDF-1.7\n% SUBSTITUTE, NOT A PDF\n",
}


DATUM_TYPES = {
    "FEATTYPE_DATUM_PLANE",
    "FEATTYPE_DATUM_AXIS",
    "FEATTYPE_DATUM_POINT",
    "FEATTYPE_COORD_SYS",
    "FEATTYPE_CURVE",
}


class Refusal(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.error = {"code": code, "message": message}


def _sketch_frame(sketch: dict, planes: list):
    """Where a point of a sketch lies in the model, by the measured rule: the plane's normal
    toward the viewer, orient_ref's normal the named way, the origin where the plane and its
    two references cross. Returns a function of [u, v]; it answers None without origins."""
    unit = lambda v: [c / math.sqrt(sum(x * x for x in v)) for c in v]  # noqa: E731
    cross = lambda a, b: [  # noqa: E731
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    n, r = unit(planes[0]["normal"]), unit(planes[1]["normal"])
    orient = sketch.get("orient", "right")
    if orient in ("right", "left"):
        x = r if orient == "right" else [-c for c in r]
        y = cross(n, x)
    else:
        y = r if orient == "up" else [-c for c in r]
        x = cross(y, n)
    three = [planes[0], *planes[2:4]]
    if len(three) != 3 or any(p.get("origin") is None for p in three):
        return lambda uv: None
    normals = [unit(p["normal"]) for p in three]
    d = [dot(nn, p["origin"]) for nn, p in zip(normals, three, strict=True)]
    det = dot(normals[0], cross(normals[1], normals[2]))
    terms = [
        cross(normals[1], normals[2]),
        cross(normals[2], normals[0]),
        cross(normals[0], normals[1]),
    ]
    origin = [sum(d[i] * terms[i][k] for i in range(3)) / det for k in range(3)]

    def at(uv):
        return [
            0.0 if abs(c) < 1e-12 else round(c, 12)
            for c in (origin[k] + uv[0] * x[k] + uv[1] * y[k] for k in range(3))
        ]

    return at


class Features:
    """Mixed into World; `self.models`, `self.model()`, `self.feature()` come from there."""

    # ----------------------------------------------------------------- state

    def seed_geometry(self, m):
        m["geometry"] = [
            {
                "ref": name,
                "kind": "datum_plane",
                "id": fid + 1,
                "type": "plane",
                "feature": {"id": fid, "name": name},
                "normal": normal,
                "origin": [0.0, 0.0, 0.0],
            }
            for fid, name, normal in (
                (1, "RIGHT", [1, 0, 0]),
                (3, "TOP", [0, 1, 0]),
                (5, "FRONT", [0, 0, 1]),
            )
        ]
        m["geometry"].append(
            {
                "ref": "PRT_CSYS_DEF",
                "kind": "csys",
                "id": 8,
                "name": "PRT_CSYS_DEF",
                "feature": {"id": 7, "name": "PRT_CSYS_DEF"},
                "origin": [0.0, 0.0, 0.0],
                "x_axis": [1, 0, 0],
                "y_axis": [0, 1, 0],
                "z_axis": [0, 0, 1],
            }
        )
        m["dimensions"] = []
        m["parameters"] = [
            {
                "name": n,
                "type": t,
                "value": v,
                "units": None,
                "designated": d,
                "relation_driven": False,
                "description": None,
            }
            for n, t, v, d in DEFAULT_PARAMETERS
        ]
        m["material"] = "PTC_SYSTEM_MTRL_PROPS"
        m["density"] = None
        m["next_geom"] = 1000

    def mass_properties(self, m):
        density = m.get("density")
        return {
            "volume": m["volume"],
            "surface_area": None,
            "mass": m["volume"] * density if density else None,
            "density": density,
            "center_of_gravity": [0.0, 0.0, -5.0] if m["volume"] else None,
            "units": {
                "length": m["units"]["length"],
                "mass": m["units"]["mass"],
                "volume": m["units"]["length"] + "^3",
                "area": m["units"]["length"] + "^2",
            },
        }

    def _gid(self, m):
        m["next_geom"] += 1
        return m["next_geom"]

    def _dimension(self, m, feature, value, kind="linear", depth=False):
        dim = {
            "id": len(m["dimensions"]) + 1,
            "name": "d" + str(len(m["dimensions"]) + 1),
            "value": float(value),
            "units": "deg" if kind == "angle" else m["units"]["length"],
            "type": kind,
            "feature": {"id": feature["id"], "name": feature["name"]},
            "relation_driven": False,
            "reference": False,
            "in_sketch": kind != "angle" and not depth,
            "tolerance": {"type": "nominal"},
        }
        m["dimensions"].append(dim)
        # A placeholder Creo lists for a sketch's references: typeless, it drives nothing.
        m["dimensions"].append(
            dim | {"id": dim["id"] + 1000, "name": "p" + str(dim["id"]), "value": 0.0, "type": None}
        )
        return dim

    def add_solid_geometry(self, m, feature, profile, depth):
        """Faces and edges of a profile extruded from FRONT towards -z (side one)."""
        own = {"id": feature["id"], "name": feature["name"]}
        z0, z1 = 0.0, -float(depth)
        if profile["type"] != "rectangle":
            for z, n in ((z0, 1), (z1, -1)):
                m["geometry"].append(
                    {
                        "ref": None,
                        "kind": "surface",
                        "id": self._gid(m),
                        "type": "plane",
                        "feature": own,
                        "normal": [0, 0, n],
                        "origin": [0, 0, z],
                        **(
                            {
                                "bbox": [
                                    [-profile["diameter"] / 2, -profile["diameter"] / 2, z],
                                    [profile["diameter"] / 2, profile["diameter"] / 2, z],
                                ]
                            }
                            if profile["type"] == "circle"
                            else {}
                        ),
                    }
                )
            m["geometry"].append(
                {
                    "ref": None,
                    "kind": "surface",
                    "id": self._gid(m),
                    "type": "cylinder",
                    "feature": own,
                }
                | (
                    {"radius": profile["diameter"] / 2, "outward": "away_from_axis"}
                    if profile["type"] == "circle"
                    else {}
                )
            )
            for item in m["geometry"]:
                item["ref"] = item["ref"] or f"surface:{item['id']}"
            return
        cx, cy = profile.get("center", [0, 0])
        w, h = profile["width"] / 2, profile["height"] / 2
        xs, ys = (cx - w, cx + w), (cy - h, cy + h)
        faces = {
            "top": ([0, 0, 1], [cx, cy, z0]),
            "bottom": ([0, 0, -1], [cx, cy, z1]),
            "front": ([0, -1, 0], [xs[0], ys[0], z0]),
            "right": ([1, 0, 0], [xs[1], ys[0], z0]),
            "back": ([0, 1, 0], [xs[1], ys[1], z0]),
            "left": ([-1, 0, 0], [xs[0], ys[1], z0]),
        }
        low_z, high_z = min(z0, z1), max(z0, z1)
        boxes = {
            "top": [[xs[0], ys[0], z0], [xs[1], ys[1], z0]],
            "bottom": [[xs[0], ys[0], z1], [xs[1], ys[1], z1]],
            "front": [[xs[0], ys[0], low_z], [xs[1], ys[0], high_z]],
            "right": [[xs[1], ys[0], low_z], [xs[1], ys[1], high_z]],
            "back": [[xs[0], ys[1], low_z], [xs[1], ys[1], high_z]],
            "left": [[xs[0], ys[0], low_z], [xs[0], ys[1], high_z]],
        }
        ids = {}
        for key, (normal, origin) in faces.items():
            ids[key] = self._gid(m)
            m["geometry"].append(
                {
                    "ref": f"surface:{ids[key]}",
                    "kind": "surface",
                    "id": ids[key],
                    "type": "plane",
                    "feature": own,
                    "normal": normal,
                    "origin": origin,
                    "bbox": boxes[key],
                    "area": math.prod(
                        high - low for low, high in zip(*boxes[key], strict=True) if high != low
                    ),
                }
            )
        corners = [(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1])]
        sides = ["front", "right", "back", "left"]
        for z, cap in ((z0, "top"), (z1, "bottom")):
            for i in range(4):
                a, b = corners[i], corners[(i + 1) % 4]
                self._edge(m, own, [a[0], a[1], z], [b[0], b[1], z], [ids[cap], ids[sides[i]]])
        for i in range(4):
            a = corners[i]
            self._edge(
                m, own, [a[0], a[1], z0], [a[0], a[1], z1], [ids[sides[i - 1]], ids[sides[i]]]
            )

    def _edge(self, m, own, start, end, surfaces):
        gid = self._gid(m)
        length = math.dist(start, end)
        m["geometry"].append(
            {
                "ref": f"edge:{gid}",
                "kind": "edge",
                "id": gid,
                "type": "line",
                "feature": own,
                "surfaces": [f"surface:{s}" for s in surfaces],
                "start": start,
                "end": end,
                "length": length,
                "direction": [(e - s) / length for s, e in zip(start, end, strict=True)],
            }
        )

    def item(self, m, ref):
        for g in m["geometry"]:
            if str(g["ref"]).upper() == str(ref).upper():
                return g
        raise Refusal("E_NOT_FOUND", f"no geometry {ref}")

    def new_feature(self, m, name, kind, prefix, adds=0.0, parents=()):
        fid = m["next_id"]
        m["next_id"] += 11
        feature = {
            "id": fid,
            "name": (name or f"{prefix}_{fid}").upper(),
            "type": kind,
            "status": "FEAT_ACTIVE",
            "visible": True,
            "parents": list(parents),
            "children": [],
            "surfaces": 0,
            "adds": adds,
        }
        m["features"].append(feature)
        for p in parents:
            for f in m["features"]:
                if f["id"] == p:
                    f["children"].append(fid)
        m["volume"] = max(0.0, m["volume"] + adds)
        m["modified"] = True
        return feature

    def built(self, name, m, feature, before, **extra):
        return {
            "model": name,
            "units": m["units"],
            "feature": {k: feature[k] for k in ("id", "name", "type", "status")},
            "volume": {"before": before, "after": m["volume"], "change": m["volume"] - before},
            **extra,
        }

    # ----------------------------------------------------------------- reads

    def geometry_list(self, q):
        name, m = self.model(q["model"])
        if q.get("profile") == "prismatic-shell-v1":
            from tests.fixture_prismatic import read_geometry

            return read_geometry(name, m)
        items = list(m["geometry"])
        if q.get("kind"):
            items = [i for i in items if i["kind"] == q["kind"]]
        if q.get("feature"):
            f = self.feature(m, q["feature"])
            items = [i for i in items if (i.get("feature") or {}).get("id") == f["id"]]
        return {"model": name, "units": m["units"], "items": items}

    def geometry_ray(self, q):
        """Where a line meets the faces of the part's box, both ways along it."""
        name, m = self.model(q["model"])
        box = [[-20.0, -10.0, -10.0], [20.0, 10.0, 0.0]]
        o, d = q["from"], q["along"]
        low, high = -1e30, 1e30
        for i in range(3):
            if abs(d[i]) < 1e-15:
                if not box[0][i] <= o[i] <= box[1][i]:
                    return {"model": name, "hits": []}
                continue
            t0, t1 = sorted(((box[0][i] - o[i]) / d[i], (box[1][i] - o[i]) / d[i]))
            low, high = max(low, t0), min(high, t1)
        if low > high:
            return {"model": name, "hits": []}
        return {
            "model": name,
            "hits": [
                {"distance": t, "point": [o[i] + t * d[i] for i in range(3)]} for t in (low, high)
            ],
        }

    def geometry_measure(self, q):
        name, m = self.model(q["model"])
        a, b = self.item(m, q["from"]), self.item(m, q["to"])
        distance = 0.0
        if a.get("normal") and b.get("normal"):
            distance = abs(
                sum(
                    (y - x) * n
                    for x, y, n in zip(a["origin"], b["origin"], a["normal"], strict=True)
                )
            )
        return {
            "model": name,
            "units": m["units"],
            "from": q["from"],
            "to": q["to"],
            "distance": distance,
            "interfering": distance == 0.0,
            "nearest_points": [a.get("origin", [0, 0, 0]), b.get("origin", [0, 0, 0])],
        }

    def dimension_list(self, q):
        name, m = self.model(q["model"])
        dims = m["dimensions"]
        for dimension in dims:
            dimension.setdefault(
                "numeric_tolerance_table",
                {"complete": True, "assigned": False, "contract_version": 1, "source": "fixture"},
            )
        if q.get("feature"):
            f = self.feature(m, q["feature"])
            dims = [d for d in dims if d["feature"]["id"] == f["id"]]
        out = {"model": name, "units": m["units"], "dimensions": dims}
        if q.get("check_regeneration"):
            out["regeneration_check"] = {
                "model": name,
                "source": "fixture_feature_status_flags",
                "completed": True,
                "checked_feature_ids": [f["id"] for f in m["features"]],
                "failed_features": [],
            }
        return out

    def parameter_list(self, q):
        name, m = self.model(q["model"])
        return {"model": name, "parameters": m["parameters"]}

    def material_state(self, name, m):
        from tests.physical_observation_fixture import ASSIGNED, DENSITY, physical, reading

        model = self.summary(name, m)
        proof = physical(model, density=m["density"] or 0.0)
        proof["body_materials"]["value"][0]["id"] = "-5778"
        if m["density"] is None:
            proof["density"] = reading(DENSITY, None, "unknown")
            proof["assigned_density"] = reading(ASSIGNED, None, "unset")
        return {
            "model": name,
            "physical_observation": proof,
            "material": m["material"],
            "density": None
            if m["density"] is None
            else {"value": m["density"], "units": "tonne/mm^3"},
            "loaded": sorted({"PTC_SYSTEM_MTRL_PROPS", m["material"]}),
            "assigned_density": None
            if m["density"] is None
            else {"value": m["density"], "units": "tonne / mm^3"},
            "mass_properties": self.mass_properties(m),
        }

    def material_list(self, q):
        rows = [
            {"name": n, "category": c, "file": str(self.material_library / (n + ".mtl"))}
            for n, c, _ in LIBRARY
            if not q.get("name") or q["name"].lower() in n.lower()
        ]
        out = {
            "library": str(self.material_library),
            "materials": rows,
            "configuration": {
                "configured_directory": None,
                "effective_library": str(self.material_library),
                "working_directory": str(self.cwd),
            },
        }
        if q.get("model"):
            name, m = self.model(q["model"])
            out["model"] = self.material_state(name, m)
        return out

    def render_state(self, q):
        name, m = self.model(q["model"])
        active = self.active or name
        result = {
            "complete": True,
            "model": name,
            "window": name,
            "active_window": active,
            "active_model": active,
            "view_transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "screen": {"pan_x": 0, "pan_y": 0, "zoom": 1},
            "datums": {
                k: "yes"
                for k in ("display_planes", "display_axes", "display_points", "display_coord_sys")
            },
            "modified": m["modified"],
            "named_views": ["FRONT", "BACK", "TOP", "BOTTOM", "LEFT", "RIGHT"],
            "explosion": None,
            "source": "controlled fixture",
        }
        if m["type"] == "assembly":
            result["explosion"] = self.summary(name, m)["explosion"]
        return result

    def inspect_jpeg(self, q):
        return dict(
            self.rendered_images[str(q["file"])],
            decoded=True,
            sampled_rgb_range=160,
            source="fixture decode substitute; not a native image",
            geometry_verified=False,
        )

    def render(self, q):
        name, m = self.model(q["model"])
        Path(q["file"]).write_bytes(JPEG)
        if not hasattr(self, "rendered_images"):
            self.rendered_images = {}
        self.rendered_images[str(q["file"])] = {"width": q["width"], "height": q["height"]}
        return {
            "model": name,
            "view": q.get("view", "isometric"),
            "width": q.get("width", 1024),
            "height": q.get("height", 768),
            "window_opened": False,
            "files": [{"path": q["file"], "bytes": len(JPEG)}],
        }

    def export(self, q):
        name, m = self.model(q["model"])
        target = Path(q["file"])
        fmt = q["format"]
        if fmt == "stl":
            data = b"solid SUBSTITUTE".ljust(80) + (0).to_bytes(4, "little")
        else:
            data = HEADERS[fmt]
        target.write_bytes(data)
        log = target.with_name(target.stem + "__out.log.1")
        log.write_bytes(b"SUBSTITUTE LOG")
        return {
            "model": name,
            "format": fmt,
            "files": [{"path": str(target), "bytes": len(data)}, {"path": str(log), "bytes": 14}],
        }

    # ----------------------------------------------------------------- edits

    # ISO 286 deviations for 18 to 30 mm, as Creo's tables give them: (plus, minus).
    FITS = {"H7": (0.021, 0.0), "g6": (-0.007, 0.020), "k6": (0.015, -0.002)}

    def dimension_tolerance(self, q):
        """A dimension's tolerance read back the way the service reads Creo's: the deviations
        and the limits they allow; a fit only in the ISO/DIN standard."""
        name, m = self.model(q["model"])
        dim = next((d for d in m["dimensions"] if str(d["id"]) == str(q["dimension"])), None)
        if dim is None:
            raise Refusal("E_NOT_FOUND", "no dimension " + str(q["dimension"]))
        spec, value = q["tolerance"], dim["value"]
        before = dict(dim["tolerance"])
        kind = spec["type"]
        places = None
        if kind in ("nominal", "basic"):
            tol = {"type": kind}
        elif kind == "plus_minus":
            tol = {
                "type": kind,
                "plus": spec["plus"],
                "minus": spec["minus"],
                "upper": value + spec["plus"],
                "lower": value - spec["minus"],
            }
            places = 3
        elif kind == "symmetric":
            tol = {
                "type": kind,
                "value": spec["value"],
                "upper": value + spec["value"],
                "lower": value - spec["value"],
            }
            places = 3
        elif kind == "limits":
            tol = {"type": kind, "upper": spec["upper"], "lower": spec["lower"]}
            places = 3
        else:
            if m.get("tolerance_standard", "ansi") != "iso":
                raise Refusal(
                    "E_CONFLICT", "ISO fits need a model in the ISO/DIN tolerance standard"
                )
            plus, minus = self.FITS.get(spec["fit"], (0.01, 0.0))
            tol = {
                "type": "fit",
                "fit": spec["fit"],
                "shown": spec.get("show", "class"),
                "plus": plus,
                "minus": minus,
                "upper": value + plus,
                "lower": value - minus,
            }
        dim["tolerance"] = tol
        m["modified"] = True
        return {
            "model": name,
            "units": m["units"],
            "dimension": dict(dim),
            "tolerance_before": before,
            "tolerance_decimals": places,
        }

    def set_tolerance_standard(self, q):
        name, m = self.model(q["model"])
        before, class_before = m.get("tolerance_standard", "ansi"), m.get("tolerance_class")
        m["tolerance_standard"] = q["standard"]
        if q.get("class"):
            m["tolerance_class"] = q["class"]
        elif q["standard"] != "iso":
            m["tolerance_class"] = None
        m["modified"] = True
        for d in m["dimensions"]:
            if (d.get("tolerance") or {}).get("type") in ("plus_minus", "symmetric", "limits"):
                d["numeric_tolerance_table"] = {
                    "complete": True,
                    "assigned": False,
                    "contract_version": 1,
                    "source": "fixture",
                }
        return {
            "model": name,
            "standard": m["tolerance_standard"],
            "standard_before": before,
            "class": m.get("tolerance_class"),
            "class_before": class_before,
            "volume": {"before": m["volume"], "after": m["volume"], "change": 0.0},
        }

    def dimension_set(self, q):
        name, m = self.model(q["model"])
        dim = next(
            (
                d
                for d in m["dimensions"]
                if str(d["id"]) == str(q["dimension"]) or d["name"] == q["dimension"]
            ),
            None,
        )
        if dim is None:
            raise Refusal("E_NOT_FOUND", "no dimension " + str(q["dimension"]))
        if q["value"] <= 0 and dim["type"] in ("linear", "diameter", "radius"):
            # Creo cannot regenerate a zero or negative size; it undoes the regeneration.
            raise Refusal("E_CREO", "XToolkitGeneralError in ProSolidRegenerate")
        before = m["volume"]
        old = dim["value"]
        if old:
            m["volume"] *= q["value"] / old if dim["type"] == "linear" else (q["value"] / old) ** 2
        dim["value"] = float(q["value"])
        feature = self.feature(m, dim["feature"]["id"])
        if feature["type"] == "FEATTYPE_SHELL":
            from tests.fixture_prismatic import hollow

            feature["native_definition"]["thickness"] = q["value"]
            hollow(self, m, feature, q["value"], feature["shell_bounds"])
        if feature["type"] == "FEATTYPE_DRAFT":
            from tests.fixture_draft import reshape

            feature["native_definition"]["angle"] = q["value"]
            reshape(self, m, feature, q["value"])

        m["modified"] = True
        return {
            "model": name,
            "units": m["units"],
            "dimension": dim,
            "value_before": old,
            "volume": {"before": before, "after": m["volume"], "change": m["volume"] - before},
        }

    def parameter_set(self, q):
        name, m = self.model(q["model"])
        existing = next(
            (p for p in m["parameters"] if p["name"].upper() == q["name"].upper()), None
        )
        before = dict(existing) if existing else None
        if existing is None:
            if not q.get("create"):
                raise Refusal("E_NOT_FOUND", "no parameter " + q["name"])
            existing = {
                "name": q["name"].upper(),
                "type": q["type"],
                "value": None,
                "units": None,
                "designated": False,
                "relation_driven": False,
                "description": None,
            }
            m["parameters"].append(existing)
        elif existing["type"] != q["type"]:
            raise Refusal("E_CONFLICT", "type differs")
        value = q["value"]
        existing["value"] = int(value) if q["type"] == "integer" else value
        m["modified"] = True
        return {"model": name, "parameter": existing, "before": before, "created": before is None}

    def material_assign(self, q):
        name, m = self.model(q["model"])
        hit = [x for x in LIBRARY if x[0].lower() == q["material"].lower()]
        if not hit and not q.get("file"):
            raise Refusal("E_NOT_FOUND", "no material " + q["material"])
        before = self.material_state(name, m)
        if q.get("file"):
            file = Path(q["file"])
            raw = file.read_bytes()
            if hashlib.sha256(raw).hexdigest() != q.get("source_sha256"):
                raise Refusal("E_CONFLICT", "material source bytes drifted")
            density = float(re.search(r"Default\s*=\s*([0-9.Ee+-]+)\s+tonne", raw.decode())[1])
            m["material"], m["density"] = file.stem.upper(), density
        else:
            m["material"], m["density"] = hit[0][0].upper(), hit[0][2]
        m["modified"] = True
        return {
            "model": name,
            "before": before,
            "after": self.material_state(name, m),
            "category": hit[0][1] if hit else None,
            "session_config_changed": False,
        }

    def set_status(self, q, suppress):
        name, m = self.model(q["model"])
        f = self.feature(m, q["feature"])
        before = m["volume"]
        affected = [f]
        if suppress:
            queue = list(f["children"])
            while queue:
                child = next(x for x in m["features"] if x["id"] == queue.pop(0))
                affected.append(child)
                queue += child["children"]
        for x in affected:
            if (x["status"] == "FEAT_ACTIVE") == suppress:
                m["volume"] += -x.get("adds", 0.0) if suppress else x.get("adds", 0.0)
            x["status"] = "FEAT_SUPPRESSED" if suppress else "FEAT_ACTIVE"
        m["modified"] = True
        return {
            "model": name,
            "features": [self.row(x) for x in affected],
            "volume": {"before": before, "after": m["volume"], "change": m["volume"] - before},
        }

    def rename(self, q):
        name, m = self.model(q["model"])
        f = self.feature(m, q["feature"])
        before = f["name"]
        f["name"] = q["name"].upper()
        m["modified"] = True
        return {"model": name, "before": before, "feature": self.row(f)}

    # ----------------------------------------------------------------- features

    def revolve(self, q):
        name, m = self.model(q["model"])
        profile = q["sketch"]["profile"]
        before = m["volume"]
        if isinstance(q["axis"], str):
            self.item(m, q["axis"])
            volume = 1000.0
        else:
            from tests.fixture import profile_area, profile_centroid

            (x0, y0), (x1, y1) = q["axis"]
            gx, gy = profile_centroid(profile)
            r = abs((x1 - x0) * (gy - y0) - (y1 - y0) * (gx - x0)) / math.hypot(x1 - x0, y1 - y0)
            volume = profile_area(profile) * r * math.radians(q["angle"])
        cut = q.get("material", "add") == "remove"
        f = self.new_feature(
            m,
            q.get("name"),
            "FEATTYPE_CUT" if cut else "FEATTYPE_PROTRUSION",
            "REVOLVE",
            adds=-volume if cut else volume,
            parents=[1, 3, 5],
        )
        self._dimension(m, f, q["angle"], "angle")
        from tests.fixture_revolved import populate

        populate(self, m, f, q)
        return self.built(
            name,
            m,
            f,
            before,
            sketch={"engine": "native"},
            sketch_dimensions=[],
            held_together=[],
            dimension_plan="kept",
        )

    def datum_plane(self, q):
        name, m = self.model(q["model"])
        before = m["volume"]
        spec = q.get("offset") or q["angle"]
        ref = self.item(m, spec["from"])
        f = self.new_feature(
            m, q.get("name"), "FEATTYPE_DATUM_PLANE", "DTM", parents=[ref["feature"]["id"]]
        )
        normal = list(ref.get("normal", [0, 0, 1]))
        distance = q["offset"]["distance"] if "offset" in q else 0.0
        origin = [
            o + distance * n for o, n in zip(ref.get("origin", [0, 0, 0]), normal, strict=True)
        ]
        plane = {
            "ref": f["name"],
            "kind": "datum_plane",
            "id": f["id"] + 1,
            "type": "plane",
            "feature": {"id": f["id"], "name": f["name"]},
            "normal": normal,
            "origin": origin,
        }
        m["geometry"].append(plane)
        if "offset" in q:
            self._dimension(m, f, distance)
            f["native_definition"] = {
                "kind": "datum_plane",
                "complete": True,
                "constraints": [{"kind": "offset", "reference": ref["ref"], "distance": distance}],
            }
        return self.built(name, m, f, before, geometry=plane)

    def datum_axis(self, q):
        name, m = self.model(q["model"])
        before = m["volume"]
        refs = [self.item(m, r) for r in q["through"]]
        f = self.new_feature(
            m,
            q.get("name"),
            "FEATTYPE_DATUM_AXIS",
            "AXIS",
            parents=[r["feature"]["id"] for r in refs],
        )
        axis = {
            "ref": f["name"],
            "kind": "axis",
            "id": f["id"] + 3,
            "name": f["name"],
            "feature": {"id": f["id"], "name": f["name"]},
            "start": [0, 0, 10],
            "end": [0, 0, -10],
            "direction": [0, 0, -1],
        }
        from tests.fixture_revolved import axis_geometry

        axis.update(axis_geometry(refs))
        f["native_definition"] = {
            "kind": "datum_axis",
            "complete": True,
            "constraints": [{"kind": "through", "reference": ref["ref"]} for ref in refs],
        }
        m["geometry"].append(axis)
        return self.built(name, m, f, before, geometry=axis)

    def edge_feature(self, q, round_):
        name, m = self.model(q["model"])
        before = m["volume"]
        edges = [self.item(m, e) for e in q["edges"]]
        if any(e["kind"] != "edge" for e in edges):
            raise Refusal("E_VALIDATION", "not an edge")
        size = q["radius"] if round_ else q["distance"]
        per = (1 - math.pi / 4) * size**2 if round_ else size**2 / 2
        removed = per * sum(e["length"] for e in edges)
        f = self.new_feature(
            m,
            q.get("name"),
            "FEATTYPE_ROUND" if round_ else "FEATTYPE_CHAMFER",
            "ROUND" if round_ else "CHAMFER",
            adds=-removed,
            parents=sorted({e["feature"]["id"] for e in edges}),
        )
        self._dimension(m, f, size, "radius" if round_ else "linear")
        if round_:
            f["native_definition"] = {
                "complete": True,
                "source": "fixture retained definition",
                "constant": True,
                "radius": size,
                "edges": list(q["edges"]),
            }
            for edge in edges:
                faces = [self.item(m, ref) for ref in edge.get("surfaces", [])]
                origin = [
                    edge["start"][i]
                    - size * sum(face.get("normal", [0, 0, 0])[i] for face in faces)
                    for i in range(3)
                ]
                gid = self._gid(m)
                m["geometry"].append(
                    {
                        "ref": f"surface:{gid}",
                        "kind": "surface",
                        "type": "cylinder",
                        "id": gid,
                        "radius": size,
                        "outward": "away_from_axis",
                        "area": math.pi / 2 * size * edge["length"],
                        "axis": {"origin": origin, "direction": edge["direction"]},
                        "bbox": [
                            [min(a, b) for a, b in zip(edge["start"], edge["end"], strict=True)],
                            [max(a, b) for a, b in zip(edge["start"], edge["end"], strict=True)],
                        ],
                        "feature": {"id": f["id"], "name": f["name"]},
                    }
                )
            return self.built(name, m, f, before)
        return self.built(name, m, f, before, scheme="45_x_d")

    # Rows of Creo's ISO.hol, as the service reads them.
    CHART = {
        ("ISO", "M6x1"): {
            "basic_diameter": 6.0,
            "pitch": 1.0,
            "tap_drill": 5.0,
            "clearance_close": 6.4,
            "clearance_medium": 6.6,
            "clearance_free": 7.0,
            "cbore_diameter": 11.2,
            "cbore_depth": 6.0,
            "csink_diameter": 13.44,
            "csink_angle": 90.0,
        },
        ("ISO", "M8x1.25"): {
            "basic_diameter": 8.0,
            "pitch": 1.25,
            "tap_drill": 6.8,
            "clearance_close": 8.4,
            "clearance_medium": 9.0,
            "clearance_free": 10.0,
            "cbore_diameter": 14.5,
            "cbore_depth": 8.0,
            "csink_diameter": 17.92,
            "csink_angle": 90.0,
        },
        ("ISO", "M10x1.5"): {
            "basic_diameter": 10.0,
            "pitch": 1.5,
            "tap_drill": 8.5,
            "clearance_close": 10.5,
            "clearance_medium": 11.0,
            "clearance_free": 12.0,
            "cbore_diameter": 17.5,
            "cbore_depth": 10.0,
            "csink_diameter": 22.4,
            "csink_angle": 90.0,
        },
        ("ISO", "M1.1x.25"): {
            "basic_diameter": 1.1,
            "pitch": 0.25,
            "tap_drill": 0.85,
            "clearance_close": 0.0,
            "clearance_medium": 0.0,
            "clearance_free": 0.0,
            "cbore_diameter": 0.0,
            "cbore_depth": 1.1,
            "csink_diameter": 0.0,
            "csink_angle": 90.0,
        },
    }

    def hole_chart(self, q):
        name, m = self.model(q["model"])
        series = q.get("series", "ISO")
        size = q["size"]
        extra = {}
        if (series, size) not in self.CHART and size.upper().startswith("M"):
            # M6 is the coarse thread: the chart's entry of that size with the greatest pitch.
            same = [
                k[1]
                for k in self.CHART
                if k[0] == series and k[1].upper().startswith(size.upper() + "X")
            ]
            if same:
                extra = {
                    "size_asked": size,
                    "size_meaning": "the coarse thread of that size (ISO 261)",
                }
                size = max(same, key=lambda k: self.CHART[(series, k)]["pitch"])
        row = self.CHART.get((series, size))
        if row is None:
            raise Refusal("E_VALIDATION", f"Creo's {series} chart has no {q['size']}")
        return {
            "chart": {
                "series": series,
                "size": size,
                "file": series + ".hol",
                "units": m["units"]["length"],
                **row,
                **extra,
            }
        }

    def thread(self, q):
        """A cosmetic thread: at the minor diameter on a shaft, the major one in a bore; it
        removes nothing, and its diameter and depth are its two dimensions."""
        name, m = self.model(q["model"])
        before = m["volume"]
        on = self.item(m, q["surface"])
        self.item(m, q["start"])
        external = on.get("outward") != "toward_axis"
        chart = None
        if "size" in q:
            chart = self.hole_chart(
                {"model": q["model"], "size": q["size"], "series": q.get("series", "ISO")}
            )["chart"]
            diameter = (
                chart["basic_diameter"] - 1.082532 * chart["pitch"]
                if external
                else chart["basic_diameter"]
            )
        else:
            diameter = q["diameter"]
        f = self.new_feature(m, q.get("name"), "FEATTYPE_THREAD", "THREAD")
        self._dimension(m, f, diameter, "diameter", depth=True)
        self._dimension(m, f, q["depth"], "linear", depth=True)
        surfaces = [
            {
                "ref": f"surface:{self._gid(m)}",
                "kind": "surface",
                "type": "cylinder",
                "radius": diameter / 2,
            }
        ]
        return self.built(
            name,
            m,
            f,
            before,
            external=external,
            diameter=diameter,
            depth=q["depth"],
            chart=chart,
            parameters={"MAJOR_DIAMETER": (chart or {}).get("basic_diameter", 0)},
            callout=(chart or {}).get("size"),
            surfaces=surfaces,
        )

    def hole(self, q):
        name, m = self.model(q["model"])
        before = m["volume"]
        placement = q["placement"]
        on = self.item(m, placement["surface"])
        for o in placement.get("offsets") or []:
            self.item(m, o["from"])
        # Where the hole's axis goes: at the origin when placed by offsets; on the axis named,
        # or across the bolt circle about it, as Creo places it.
        start = [0, 0, 0]
        how = "linear"
        if "offsets" in placement:
            # Fixture plane intersection, independently stored for later getter tests.
            planes = [on] + [self.item(m, v["from"]) for v in placement["offsets"]]
            vectors = [p["normal"] for p in planes]

            def cross(a, b):
                return [
                    a[1] * b[2] - a[2] * b[1],
                    a[2] * b[0] - a[0] * b[2],
                    a[0] * b[1] - a[1] * b[0],
                ]

            terms = [
                cross(vectors[1], vectors[2]),
                cross(vectors[2], vectors[0]),
                cross(vectors[0], vectors[1]),
            ]
            determinant = sum(a * b for a, b in zip(vectors[0], terms[0], strict=True))
            values = [
                sum(a * b for a, b in zip(p["normal"], p["origin"], strict=True)) for p in planes
            ]
            for i, v in enumerate(placement["offsets"], 1):
                values[i] += v["distance"]
            start = [sum(values[i] * terms[i][j] for i in range(3)) / determinant for j in range(3)]
        if "axis" in placement:
            about = self.item(m, placement["axis"])
            if about["kind"] != "axis":
                raise Refusal("E_VALIDATION", "'placement.axis' is an axis")
            start = list(about["start"])
            how = "coaxial"
            if "diameter" in placement:
                self.item(m, placement["angle_from"])
                d = about["direction"]
                across = [1.0, 0.0, 0.0] if abs(d[0]) < 0.9 else [0.0, 1.0, 0.0]
                start = [
                    s + placement["diameter"] / 2 * a for s, a in zip(start, across, strict=True)
                ]
                how = "bolt_circle"
        depth = 10.0 if q["depth"] == "through_all" else q["depth"]
        screw = q.get("thread") or q.get("clearance")
        chart = self.hole_chart({"model": q["model"], **screw})["chart"] if screw else None
        if chart:
            drill = (
                chart["tap_drill"]
                if "thread" in q
                else chart["clearance_" + screw.get("fit", "medium")]
            )
        else:
            drill = q["diameter"]
        shapes = {}
        for key, prefix, second in (
            ("counterbore", "cbore", "depth"),
            ("countersink", "csink", "angle"),
        ):
            given = q.get(key)
            if given is True:
                shapes[key] = {
                    "diameter": chart[prefix + "_diameter"],
                    second: chart[prefix + "_" + second],
                }
            elif given:
                shapes[key] = dict(given)
        removed = math.pi * (drill / 2) ** 2 * depth
        surfaces = [
            {"ref": "surface:9001", "kind": "surface", "type": "cylinder", "radius": drill / 2}
        ]
        if "counterbore" in shapes:
            c = shapes["counterbore"]
            removed += math.pi * ((c["diameter"] / 2) ** 2 - (drill / 2) ** 2) * c["depth"]
            surfaces.append(
                {
                    "ref": "surface:9002",
                    "kind": "surface",
                    "type": "cylinder",
                    "radius": c["diameter"] / 2,
                }
            )
        if "thread" in q:
            surfaces.append(
                {
                    "ref": "surface:9003",
                    "kind": "surface",
                    "type": "cylinder",
                    "radius": chart["basic_diameter"] / 2,
                }
            )
        f = self.new_feature(
            m, q.get("name"), "FEATTYPE_HOLE", "HOLE", adds=-removed, parents=[on["feature"]["id"]]
        )
        self._dimension(m, f, drill, "diameter")
        f["native_definition"] = {
            "complete": True,
            "source": "fixture retained definition",
            "diameter": drill,
            "through_all": q["depth"] == "through_all",
            "placement_surface": placement["surface"],
            "offsets": copy.deepcopy(placement.get("offsets", [])),
        }
        m["geometry"].append(
            {
                "ref": f"A_{len([g for g in m['geometry'] if g['kind'] == 'axis']) + 1}",
                "kind": "axis",
                "id": f["id"] + 5,
                "name": None,
                "feature": {"id": f["id"], "name": f["name"]},
                "start": start,
                "end": [start[0], start[1], start[2] - depth],
                "direction": [0, 0, -1],
            }
        )
        bore = self._gid(m)
        m["geometry"].append(
            {
                "ref": f"surface:{bore}",
                "kind": "surface",
                "id": bore,
                "type": "cylinder",
                "radius": drill / 2,
                "area": math.pi * drill * depth,
                "outward": "toward_axis",
                "axis": {"origin": start, "direction": [0, 0, -1]},
                "bbox": [
                    [start[0] - drill / 2, start[1] - drill / 2, start[2] - depth],
                    [start[0] + drill / 2, start[1] + drill / 2, start[2]],
                ],
                "feature": {"id": f["id"], "name": f["name"]},
            }
        )
        for z in (start[2], start[2] - depth):
            cap = next(
                (
                    g
                    for g in m["geometry"]
                    if g.get("kind") == "surface"
                    and g.get("type") == "plane"
                    and g.get("origin", [None] * 3)[2] == z
                    and g.get("normal") in ([0, 0, 1], [0, 0, -1])
                ),
                None,
            )
            if cap:
                cap["area"] -= math.pi * (drill / 2) ** 2
                rim = self._gid(m)
                point = [start[0] + drill / 2, start[1], z]
                m["geometry"].append(
                    {
                        "id": rim,
                        "ref": f"edge:{rim}",
                        "kind": "edge",
                        "type": "circle",
                        "feature": {"id": f["id"], "name": f["name"]},
                        "center": [start[0], start[1], z],
                        "radius": drill / 2,
                        "normal": [0, 0, -1],
                        "length": math.pi * drill,
                        "start": point,
                        "end": point,
                        "surfaces": [f"surface:{bore}", cap["ref"]],
                    }
                )
        return self.built(
            name,
            m,
            f,
            before,
            drill_diameter=drill,
            depth=q["depth"],
            placement=how,
            counterbore=shapes.get("counterbore"),
            countersink=shapes.get("countersink"),
            chart=chart,
            surfaces=surfaces,
        )

    def shell(self, q):
        name, m = self.model(q["model"])
        faces = [self.item(m, r) for r in q.get("remove", [])]
        if any(x["kind"] != "surface" for x in faces):
            raise Refusal("E_VALIDATION", "not a face")
        from tests.fixture_prismatic import create

        return create(self, name, m, q)

    def draft(self, q):
        from tests.fixture_draft import create

        name, model = self.model(q["model"])
        return create(self, name, model, q)

    def rib(self, q):
        """A rib fills the side of its chain that the part closes -- here the side the sketch's
        origin is on; unless one is named the right is tried first, as the service does."""
        name, m = self.model(q["model"])
        before = m["volume"]
        s = q["sketch"]
        for plane in (s["plane"], s["orient_ref"], *s.get("references", [])):
            self.item(m, plane)
        points = s["points"]
        (x0, y0), (x1, y1) = points[0], points[1]
        closes = "right" if (x1 - x0) * (0 - y0) - (y1 - y0) * (0 - x0) < 0 else "left"
        sides = [q["fill"]] if "fill" in q else ["right", "left"]
        if closes not in sides:
            failure = Refusal("E_CREO", "Creo made the rib but could not regenerate it")
            failure.error |= {"stage": "regenerate", "cleanup": "deleted"}
            raise failure
        ring = [*points, [0.0, 0.0]]
        area = (
            abs(
                sum(
                    a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(ring, ring[1:] + ring[:1], strict=True)
                )
            )
            / 2
        )
        f = self.new_feature(m, q.get("name"), "FEATTYPE_RIB", "RIB", adds=area * q["thickness"])
        self._dimension(m, f, q["thickness"])
        return self.built(
            name,
            m,
            f,
            before,
            fill=closes,
            fill_tried=sides[: sides.index(closes)],
            sketch={"engine": "native"},
        )

    def sweep(self, q):
        """A sweep adds its section's area times how far the centroid travels; its path, a
        datum curve, lies where the sketch frame puts it, as the service reads it back. Creo
        runs a chain the way its arcs turn: from the far end when the first arc is clockwise."""
        from creo_cli.sketch import swept_volume

        name, m = self.model(q["model"])
        before = m["volume"]
        path = q["path"]
        refs = path.get("references") or [
            p for p in ("RIGHT", "TOP", "FRONT") if p != path["plane"].upper()
        ]
        planes = [self.item(m, p) for p in (path["plane"], path["orient_ref"], *refs)]
        curve = self.new_feature(
            m,
            q["name"] + "_PATH" if q.get("name") else None,
            "FEATTYPE_CURVE",
            "CURVE",
            parents=[planes[0]["feature"]["id"]],
        )
        v = swept_volume(path, q["section"])
        cut = q.get("material") == "remove"
        f = self.new_feature(
            m,
            q.get("name"),
            "FEATTYPE_CUT" if cut else "FEATTYPE_PROTRUSION",
            "SWEEP",
            adds=-v if cut else v,
            parents=[curve["id"]],
        )
        frame = _sketch_frame(path, planes)
        arcs = [seg["sweep"] for seg in path["segments"] if "sweep" in seg]
        return self.built(
            name,
            m,
            f,
            before,
            path={
                "id": curve["id"],
                "name": curve["name"],
                "type": "FEATTYPE_CURVE",
                "starts_at": frame(path["start"]),
                "ends_at": frame(path["segments"][-1]["to"]),
                "creo_runs_from": "end" if arcs and arcs[0] < 0 else "start",
            },
            sketch={"engine": "native"},
        )

    # ----------------------------------------------------------------- family tables

    def family_table(self, name, m):
        fam = m.get("family") or {"columns": [], "rows": {}}
        return {
            "model": name,
            "units": m["units"],
            "columns": [dict(c) for c in fam["columns"]],
            "complete": True,
            "source": "fixture family table native getters",
            "instances": [
                {
                    "name": inst,
                    "verified": "FAMINST_NOT_VERIFIED",
                    "cells": {
                        c["symbol"]: {
                            "value": row.get(c["symbol"], c["generic_value"]),
                            "generic": c["symbol"] not in row,
                        }
                        for c in fam["columns"]
                    },
                }
                for inst, row in fam["rows"].items()
            ],
        }

    def family_show(self, q):
        name, m = self.model(q["model"])
        return self.family_table(name, m) | {"generic": m.get("generic")}

    def _family_item(self, m, key):
        kind, _, ref = key.partition(":")
        if kind == "dimension":
            for d in m["dimensions"]:
                if d.get("type") and (d["name"].lower() == ref.lower() or str(d["id"]) == ref):
                    return {
                        "symbol": d["name"],
                        "kind": kind,
                        "name": d["name"],
                        "generic_value": d["value"],
                    }
            raise Refusal("E_NOT_FOUND", "no dimension named or numbered " + ref)
        if kind == "parameter":
            for p in m["parameters"]:
                if p["name"].upper() == ref.upper():
                    return {
                        "symbol": p["name"],
                        "kind": kind,
                        "name": p["name"],
                        "generic_value": p["value"],
                    }
            raise Refusal("E_NOT_FOUND", "no parameter named " + ref)
        if kind == "feature":
            f = self.feature(m, ref)
            return {"symbol": f"F{f['id']}", "kind": kind, "name": f["name"], "generic_value": True}
        raise Refusal(
            "E_VALIDATION", "a column is dimension:<symbol>, parameter:<name> or feature:<name>"
        )

    def family_set(self, q):
        """As the service does: columns and rows added, cells set, each instance made and read
        back; Creo keeps the old value of a dimension it will not take (none at or below 0),
        and the table goes back as it was."""
        import copy

        name, m = self.model(q["model"])
        bounded = q.get("profile") == "dimension-only-v1"
        if bounded and any(n.lower() + ".prt" in self.models for n in q["inspect_instances"]):
            raise Refusal("E_CONFLICT", "instance is open; bounded family apply does not erase it")
        if m.get("generic"):
            raise Refusal(
                "E_VALIDATION", name + " is an instance; the table is " + m["generic"] + "'s"
            )
        before = self.family_table(name, m)
        saved = copy.deepcopy(m.get("family") or {"columns": [], "rows": {}})
        fam = m.setdefault("family", {"columns": [], "rows": {}})
        symbols, added = {}, []
        for instance in q["instances"]:
            for key in instance["values"]:
                if key in symbols:
                    continue
                item = self._family_item(m, key)
                symbols[key] = item["symbol"]
                if not any(c["symbol"] == item["symbol"] for c in fam["columns"]):
                    fam["columns"].append(item)
                    added.append(key)
        touched, checked = [], []
        for instance in q["instances"]:
            inst = instance["name"].upper()
            created = inst not in fam["rows"]
            row = fam["rows"].setdefault(inst, {})
            for key, value in instance["values"].items():
                if key.startswith("dimension:") and value <= 0:
                    m["family"] = saved
                    failure = Refusal(
                        "E_CREO",
                        f"Creo kept {inst}'s {key} at its old value; it does not take {value}",
                    )
                    failure.error |= {
                        "stage": "family_table",
                        "cleanup": "the table put back as it was",
                    }
                    raise failure
                row[symbols[key]] = value
            touched.append({"name": inst, "created": created})
            checked.append(
                {
                    "name": inst,
                    "model": inst.lower() + ".prt",
                    "regenerated": True,
                    "volume": m["volume"],
                    "reads": dict(instance["values"]),
                    "kept_in_session": inst.lower() + ".prt" in self.models,
                }
            )
        if bounded:
            for instance in q["inspect_instances"]:
                self.open_instance(name, m, instance)
                self.models[instance.lower() + ".prt"]["window_closed"] = True
            m["modified"] = True
        return {
            "model": name,
            "units": m["units"],
            "columns": symbols,
            "columns_added": added,
            "instances": touched,
            "checked": checked,
            "generic_volume": {"before": m["volume"], "after": m["volume"]},
            "table_before": before,
            "table": self.family_table(name, m),
        }

    def family_remove(self, q):
        name, m = self.model(q["model"])
        rows = (m.get("family") or {}).get("rows", {})
        inst = q["instance"].upper()
        if q.get("profile") == "dimension-only-v1" and inst.lower() + ".prt" in self.models:
            raise Refusal("E_CONFLICT", "open instance cannot be removed")
        if inst not in rows:
            raise Refusal("E_NOT_FOUND", name + " has no instance " + q["instance"])
        before = self.family_table(name, m)
        del rows[inst]
        self.models.pop(inst.lower() + ".prt", None)
        m["modified"] = True
        return {
            "model": name,
            "removed": inst,
            "table_before": before,
            "table": self.family_table(name, m),
        }

    def open_instance(self, generic, m, instance):
        import copy

        inst = instance.upper()
        if inst not in (m.get("family") or {}).get("rows", {}):
            raise Refusal("E_NOT_FOUND", generic + " has no instance " + instance)
        name = inst.lower() + ".prt"
        if name in self.models:
            raise Refusal("E_CONFLICT", name + " is already in session")
        made = copy.deepcopy(m)
        self.models[name] = made
        made.pop("family", None)
        made["generic"] = generic
        made["modified"] = True
        made["native_dependencies"] = [generic]
        ratio = 1.0
        cells = m["family"]["rows"][inst]
        for column in m["family"]["columns"]:
            if column["kind"] == "dimension" and column["symbol"] in cells:
                dimension = next(d for d in made["dimensions"] if d["name"] == column["name"])
                if dimension["value"]:
                    ratio *= cells[column["symbol"]] / dimension["value"]
                dimension["value"] = cells[column["symbol"]]
        made["volume"] = m["volume"] * ratio
        return name

    def pattern(self, q):
        name, m = self.model(q["model"])
        before = m["volume"]
        leader = self.feature(m, q["feature"])
        spec = q.get("direction") or q["axis"]
        self.item(m, spec.get("along") or spec["about"])
        if q.get("direction2"):
            self.item(m, q["direction2"]["along"])
        head = self.new_feature(m, q.get("name"), "FEATTYPE_PATTERN_HEAD", "PATTERN")
        members = [{"id": leader["id"], "name": leader["name"]}]
        for _ in range(spec["count"] * (q.get("direction2") or {}).get("count", 1) - 1):
            copy = self.new_feature(m, None, leader["type"], "COPY", adds=leader.get("adds", 0.0))
            copy["name"] = None
            members.append({"id": copy["id"], "name": None})
        leader["pattern_count"] = len(members)
        return self.built(name, m, head, before, members=members)

    def mirror(self, q):
        name, m = self.model(q["model"])
        before = m["volume"]
        plane = self.item(m, q["plane"])
        f = self.new_feature(
            m,
            q.get("name"),
            "FEATTYPE_GENERAL_MERGE",
            "MIRROR",
            adds=m["volume"],
            parents=[plane["feature"]["id"]],
        )
        return self.built(name, m, f, before)

    # ----------------------------------------------------------------- assemblies

    def make_assembly(self, m):
        """Turn a freshly made part into an assembly: ASM_ datums and no components."""
        for f in m["features"]:
            if f["name"] in ("RIGHT", "TOP", "FRONT"):
                f["name"] = "ASM_" + f["name"]
            elif f["name"] == "PRT_CSYS_DEF":
                f["name"] = "ASM_DEF_CSYS"
        for g in m["geometry"]:
            if g["kind"] == "datum_plane":
                g["ref"] = "ASM_" + g["ref"]
                g["feature"]["name"] = "ASM_" + g["feature"]["name"]
            elif g["kind"] == "csys":
                g["ref"] = g["name"] = g["feature"]["name"] = "ASM_DEF_CSYS"
        m["components"] = []

    def _assembly(self, raw):
        name, m = self.model(raw if "." in raw else raw + ".asm")
        if m["type"] != "assembly":
            raise Refusal("E_VALIDATION", name + " is not an assembly")
        return name, m

    def _component_of(self, m, wanted):
        hits = [
            c
            for c in m["components"]
            if str(c["id"]) == str(wanted)
            or c["model"].split(".")[0] == wanted.split(".")[0].lower()
        ]
        if len(hits) != 1:
            raise Refusal("E_NOT_FOUND" if not hits else "E_CONFLICT", "component " + wanted)
        return hits[0]

    def assembly_add(self, q):
        name, m = self._assembly(q["model"])
        cname, comp = self.model(q["component"])
        for c in q["constraints"]:
            if c["type"] in ("default", "fix"):
                continue
            ref = c["assembly_ref"]
            if "@" in ref:
                own, _, where = ref.rpartition("@")
                placed = self._component_of(m, where)
                self.item(self.models[placed["model"]], own)
            else:
                self.item(m, ref)
            self.item(comp, c["component_ref"])
        kinds = [c["type"] for c in q["constraints"]]
        firm = "default" in kinds or "csys" in kinds or "fix" in kinds or len(kinds) >= 3
        row = {
            "id": m["next_id"],
            "model": cname,
            "status": "FEAT_ACTIVE",
            "placed": True,
            "packaged": False,
            "underconstrained": not firm,
            "constraints": [
                {"type": "def_placement" if k == "default" else k, "offset": 0.0} for k in kinds
            ],
            "position": {
                "origin": [0.0, 0.0, 0.0] if "default" in kinds else [0.0, 0.0, 20.0],
                "x_axis": [1, 0, 0],
                "y_axis": [0, 1, 0],
                "z_axis": [0, 0, 1],
            },
            "volume": comp["volume"],
        }
        m["next_id"] += 1
        before = m["volume"]
        m["components"].append(row)
        m["volume"] += comp["volume"]
        m["modified"] = True
        return {
            "model": name,
            "units": m["units"],
            "component": {k: v for k, v in row.items() if k != "volume"},
            "constraints_requested": kinds,
            "volume": {"before": before, "after": m["volume"], "change": m["volume"] - before},
        }

    def assembly_remove(self, q):
        name, m = self._assembly(q["model"])
        target = self._component_of(m, str(q["component"]))
        m["components"] = [c for c in m["components"] if c["id"] != target["id"]]
        m["volume"] -= target.get("volume", 0.0)
        m["modified"] = True
        return {
            "model": name,
            "component": target["model"],
            "removed": [
                {
                    "id": target["id"],
                    "name": None,
                    "type": "FEATTYPE_COMPONENT",
                    "status": "FEAT_ACTIVE",
                    "number": None,
                    "visible": True,
                }
            ],
            "gone": True,
            "components": [{k: v for k, v in c.items() if k != "volume"} for c in m["components"]],
        }

    def assembly_replace(self, q):
        """Another member of the component's family in its place, held by the same
        constraints; any other model refused, as the service does."""
        name, m = self._assembly(q["model"])
        target = self._component_of(m, str(q["component"]))
        wname, with_ = self.model(q["with"])
        old = self.models.get(target["model"]) or {}
        family = old.get("generic") or target["model"]
        if (with_.get("generic") or wname) != family:
            raise Refusal("E_VALIDATION", wname + " is not of " + target["model"] + "'s family")
        before_row = {k: v for k, v in target.items() if k != "volume"}
        volume = m["volume"]
        m["volume"] += with_["volume"] - target.get("volume", 0.0)
        target["model"], target["volume"] = wname, with_["volume"]
        m["modified"] = True
        return {
            "model": name,
            "units": m["units"],
            "replaced": before_row["model"],
            "component": {k: v for k, v in target.items() if k != "volume"},
            "before": before_row,
            "references_moved": len(target["constraints"]),
            "volume": {"before": volume, "after": m["volume"], "change": m["volume"] - volume},
        }

    def states_of(self, m):
        """An assembly's exploded states; every assembly has Creo's default, moving nothing."""
        return m.setdefault(
            "exploded_states",
            [
                {
                    "name": "Default Explode",
                    "id": -2338921,
                    "active": True,
                    "is_default": True,
                    "moves": [],
                }
            ],
        )

    def assembly_explode(self, q):
        import copy

        name, m = self._assembly(q["model"])
        normal = copy.deepcopy(m["components"])
        for row in normal:
            row["component_path_transform"] = copy.deepcopy(row["position"])
        states = self.states_of(m)
        existing = [x for x in states if x["name"].upper() == q["name"].upper()]
        if existing and not q.get("replace"):
            raise Refusal("E_CONFLICT", name + " has an exploded state " + q["name"] + " already")
        before = [dict(x) for x in states]
        for x in existing:
            states.remove(x)
        moves = []
        for move in q["moves"]:
            ids = [int(self._component_of(m, str(c))["id"]) for c in move["components"]]
            moves.append(
                {
                    "components": ids,
                    "component_paths": [[str(i)] for i in ids],
                    "type": "translate",
                    "direction": move["direction"],
                    "distance": move["distance"],
                }
            )
        for x in states:
            x["active"] = False
        state = {
            "name": q["name"],
            "id": existing[0]["id"] if existing else m["next_id"],
            "is_default": False,
            "active": True,
            "moves": moves,
        }
        m["is_exploded"] = True
        m["modified"] = True
        m["next_id"] += 1
        states.insert(0, state)
        return {
            "model": name,
            "units": m["units"],
            "state": dict(state),
            "states_before": before,
            "states": [dict(x) for x in states],
            "replaced": bool(existing),
            "normal_before": copy.deepcopy(normal),
            "normal_after": copy.deepcopy(normal),
        }

    def assembly_check(self, q):
        name, m = self._assembly(q["model"])
        rows = [{k: v for k, v in c.items() if k != "volume"} for c in m["components"]]
        at_origin = [c for c in m["components"] if c["position"]["origin"] == [0.0, 0.0, 0.0]]
        clashes = []
        for i in range(len(at_origin)):
            for j in range(i + 1, len(at_origin)):
                a, b = at_origin[i], at_origin[j]
                clashes.append(
                    {
                        "parts": [
                            {"model": a["model"], "component_path": str(a["id"])},
                            {"model": b["model"], "component_path": str(b["id"])},
                        ],
                        "volume": min(a.get("volume", 0.0), b.get("volume", 0.0)),
                    }
                )
        return {
            "model": name,
            "units": m["units"],
            "components": rows,
            "not_fully_constrained": sum(1 for c in rows if c["underconstrained"] or c["packaged"]),
            "interferences": clashes,
        }

    # ----------------------------------------------------------------- drawings

    def drawing_view_row(self, view, index):
        """Per-view observations, never inferred from the assembly's current state."""
        row = copy.deepcopy(view)
        row.setdefault("id", index + 1)
        if self.capabilities.get("drawing_view_exploded_readback") == 1:
            row.setdefault(
                "view_identity_readback",
                {"complete": True}
                | {
                    field: {"complete": True, "value": row.get(field), "source": source}
                    for field, source in (
                        ("id", "WView2D.GetViewId"),
                        ("name", "View2D.GetName"),
                        ("sheet", "View2D.GetSheetNumber"),
                        ("model", "View2D.GetModel/Model.GetFileName"),
                    )
                },
            )
            row.setdefault(
                "exploded_display_readback",
                {
                    "complete": True,
                    "value": bool(row.get("exploded", False)),
                    "source": "WView2D.IsExplodedState",
                },
            )
            row.setdefault(
                "named_exploded_state_reference",
                {
                    "complete": False,
                    "status": "not_checked",
                    "value": None,
                    "reason": "no supported per-view named exploded-state identity getter "
                    "established",
                },
            )
        return row

    def drawing_summary(self, name, m):
        notes = []
        for previous in m.get("notes", []):
            row = dict(previous)
            row.setdefault(
                "membership_readback",
                {
                    "complete": True,
                    "drawing": name,
                    "note_id": row["id"],
                    "source": "loopback fixture drawing enumeration; not SDK evidence",
                },
            )
            notes.append(row)
        entities = m.get("entities", 0)
        return {
            "model": name,
            "type": "drawing",
            "projection": m.get("projection"),
            "draft_entities": m.get("entities", 0),
            "draft_entity_readback": {
                "completed": entities == 0,
                "items": [] if entities == 0 else None,
                "count": entities,
                "scope": "bounded_straight_lines",
                "source": "loopback fixture empty entity inventory",
            },
            "draft_arcs": copy.deepcopy(m.get("draft_arcs", [])),
            "models": list(m["drawing_models"]),
            "sheets": [dict(s) for s in m["sheets"]],
            "views": [self.drawing_view_row(v, i) for i, v in enumerate(m["views"])],
            "dimensions_shown": len(m.get("shown_dims", [])),
            "dimensions": [dict(d) for d in m.get("shown_dims", []) + m.get("own_dims", [])],
            "notes": notes,
            "tables": [{k: v for k, v in t.items() if k != "bom"} for t in m.get("tables", [])],
            "symbols": [dict(t) for t in m.get("symbols", [])],
            "datums": [dict(t) for t in m.get("datums", [])],
            "gtols": [dict(t) for t in m.get("gtols", [])],
            "origin": m["origin"],
            "modified": m["modified"],
        }

    def drawing_create(self, q):
        name = self.name(q["name"] if "." in q["name"] else q["name"] + ".drw")
        if name in self.models:
            raise Refusal("E_CONFLICT", "a drawing named " + name + " is already in session")
        of, solid = self.model(q["of"])
        m = {
            "type": "drawing",
            "units": dict(solid["units"]),
            "features": [],
            "volume": 0.0,
            "origin": None,
            "modified": False,
            "next_id": 1,
            "drawing_models": [of],
            "sheets": [
                {
                    "number": 1,
                    "width": 420.0,
                    "height": 297.0,
                    "units": "mm",
                    "size": q.get("sheet") or "variable",
                    "scale": float(q.get("scale") or 1.0),
                    "scale_label": "1:2" if q.get("scale") == 0.5 else "1:1",
                }
            ],
            "views": [
                {
                    "name": f"VIEW_TEMPLATE_{i}",
                    "sheet": 1,
                    "scale": 1.0,
                    "model": of,
                    "outline": [[x, y], [x + 60.0, y + 40.0]],
                    "type": "general" if i == 1 else "projection",
                    "parent": None if i == 1 else "VIEW_TEMPLATE_1",
                    "sections": [],
                    "display": q.get("display", "lines"),
                }
                for i, (x, y) in enumerate(((78.75, 92.5), (78.75, 227.4), (263.0, 92.5)), 1)
            ],
            "projection": q.get("projection")
            or (
                "first_angle" if q.get("sheet") in ("a0", "a1", "a2", "a3", "a4") else "third_angle"
            ),
            "shown_dims": [],
            "notes": [],
        }
        # The template's views go when another projection, standard views or none are asked;
        # standard ones are laid out by drawing.lay-out, called next.
        replaced, laid = [], []
        views = q.get("views", "template")
        kept = "first_angle" if q.get("sheet") in ("a0", "a1", "a2", "a3", "a4") else "third_angle"
        if views != "template" or m["projection"] != kept:
            replaced = [v["name"] for v in m["views"]]
            m["views"] = []
        lay_out = views != "none" and not m["views"]
        self.models[name] = m
        self.active = name
        self.write_version(Path(self.cwd), name, m)
        asked = q.get("scale")
        if asked:
            for v in m["views"]:
                v["scale"] = float(asked)
        return self.drawing_summary(name, m) | {
            "projection": m["projection"],
            "views_replaced": replaced,
            "lay_out": lay_out,
            "template": (q.get("sheet") or "custom") + "_drawing",
            "lettering": "font" if q.get("sheet") else None,
            "scale_labels": "ratio_colon" if q.get("sheet") else None,
            "views_laid_out": laid,
            "scale_chosen": {
                "scale": float(asked or 1.0),
                "label": "1:2" if asked == 0.5 else "1:1",
                "before": 1.0,
                "meaning": "as asked" if asked else "the largest preferred scale that fits",
            },
        }

    def drawing_lay_out(self, q):
        name, m = self._drawing(q["model"])
        if m["views"]:
            raise Refusal("E_CONFLICT", "the drawing has views already")
        first = m["projection"] == "first_angle"
        laid = []
        for name_, kind, parent, (x, y) in (
            ("FRONT", "general", None, (90.0, 170.0 if first else 100.0)),
            (
                "LEFT" if first else "RIGHT",
                "projection",
                "FRONT",
                (230.0, 170.0 if first else 100.0),
            ),
            ("TOP", "projection", "FRONT", (90.0, 50.0 if first else 220.0)),
            ("ISOMETRIC", "general", None, (330.0, 220.0)),
        ):
            m["views"].append(
                {
                    "name": name_,
                    "sheet": 1,
                    "scale": float(q.get("scale") or 1.0),
                    "model": m["drawing_models"][0],
                    "outline": [[x, y], [x + 60.0, y + 40.0]],
                    "type": kind,
                    "parent": parent,
                    "sections": [],
                    "display": q.get("display", "lines"),
                }
            )
            laid.append(name_)
        m["modified"] = True
        asked = q.get("scale")
        return self.drawing_summary(name, m) | {
            "projection": m["projection"],
            "views_laid_out": laid,
            "scale_chosen": {
                "scale": float(asked or 1.0),
                "label": "1:2" if asked == 0.5 else "1:1",
                "before": 1.0,
                "meaning": "as asked" if asked else "the largest preferred scale that fits",
            },
        }

    def _drawing(self, raw):
        name, m = self.model(raw if "." in raw else raw + ".drw")
        if m["type"] != "drawing":
            raise Refusal("E_VALIDATION", name + " is not a drawing")
        return name, m

    def drawing_add_view(self, q):
        name, m = self._drawing(q["model"])
        view = q["view"]
        if view.get("name") and any(v["name"] == view["name"] for v in m["views"]):
            raise Refusal("E_CONFLICT", "the drawing already has a view named " + view["name"])
        if view["type"] in ("projection", "detail") and not any(
            v["name"] == view["parent"] for v in m["views"]
        ):
            raise Refusal("E_NOT_FOUND", "no view named " + view["parent"])
        x, y = view["at"]
        half = 25.0
        if view["type"] == "detail":
            _, solid = self.model(m["drawing_models"][0])
            self.item(solid, view["detail"]["center"])
            half = view["detail"]["radius"] * view.get("scale", 1.0)
        row = {
            "id": max((v.get("id", i + 1) for i, v in enumerate(m["views"])), default=0) + 1,
            "name": view.get("name") or f"new_view_{len(m['views']) + 1}",
            "exploded": bool(view.get("exploded", False)),
            "sheet": 1,
            "scale": float(view.get("scale", 1.0)),
            "model": m["drawing_models"][0],
            "outline": [[x - half, y - half], [x + half, y + half]],
            "type": view["type"],
            "parent": view.get("parent"),
            "sections": [],
            "display": view.get("display", "lines") if view["type"] != "detail" else "lines",
        }
        out = {}
        if view.get("section"):
            _, solid = self.model(m["drawing_models"][0])
            sections = solid.setdefault("cross_sections", [])
            wanted = view["section"]["name"]
            made = not any(x["name"] == wanted for x in sections)
            if made:
                if not view["section"].get("plane"):
                    raise Refusal("E_NOT_FOUND", "no cross-section " + wanted)
                sections.append({"name": wanted, "plane": view["section"]["plane"]})
                solid["modified"] = True
            row["sections"] = [wanted]
            row["section_area"] = "half" if view["section"].get("half") else "full"
            out["section"] = {
                "name": wanted,
                "plane": view["section"].get("plane"),
                "made_in_part": made,
                "area": row["section_area"],
                "half_by": view["section"].get("half"),
            }
            if view["section"].get("edges"):
                out["section"]["edges"] = view["section"]["edges"]
        m["views"].append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"view": row} | out

    def drawing_move_view(self, q):
        name, m = self._drawing(q["model"])
        row = next((v for v in m["views"] if v["name"] == q["view"]), None)
        if row is None:
            raise Refusal("E_NOT_FOUND", "no view named " + q["view"])
        (x0, y0), (x1, y1) = row["outline"]
        dx, dy = q["at"][0] - (x0 + x1) / 2, q["at"][1] - (y0 + y1) / 2
        row["outline"] = [[x0 + dx, y0 + dy], [x1 + dx, y1 + dy]]
        m["modified"] = True
        return self.drawing_summary(name, m) | {"view": dict(row)}

    def drawing_annotate(self, q):
        name, m = self._drawing(q["model"])
        solid_name = m["drawing_models"][0]
        solid = self.models[solid_name]
        view = m["views"][0]["name"]
        only = {str(f).upper() for f in q["features"]} if q.get("features") is not None else None
        rows, taken, zeros, datums, turns, counted, chamfers = [], [], [], [], [], [], []
        erased = m.setdefault("erased", set())
        for d in (d for d in solid["dimensions"] if d.get("type") and d["id"] not in erased):
            owner = d["feature"]
            if d["value"] == 0 and not q.get("with_zero"):
                zeros.append({"name": d["name"], "id": d["id"], "how": "erased_from_drawing"})
                erased.add(d["id"])
                continue
            named = only is not None and bool({str(owner["id"]), str(owner["name"]).upper()} & only)
            kind = next((f["type"] for f in solid["features"] if f["id"] == owner["id"]), None)
            if not named and kind in DATUM_TYPES:
                datums.append({"name": d["name"], "id": d["id"], "how": "erased_from_drawing"})
                erased.add(d["id"])
                continue
            if not named and d["type"] == "angle" and d["value"] == 360:
                turns.append({"name": d["name"], "id": d["id"], "how": "erased_from_drawing"})
                erased.add(d["id"])
                continue
            if only is not None and not named:
                taken.append({"name": d["name"], "id": d["id"], "how": "erased_from_drawing"})
                erased.add(d["id"])
                continue
            rows.append(
                {
                    "name": d["name"],
                    "id": d["id"],
                    "model": solid_name,
                    "value": d["value"],
                    "type": d["type"],
                    "feature": dict(owner),
                    "view": view,
                    "reference": False,
                    "at": [60.0 + 12.0 * (len(rows) % 25), 150.0 - 10.0 * (len(rows) // 25)],
                }
            )
            # A patterned hole's diameter, with how many there are; a chamfer as 1 X 45.
            leader = next((f for f in solid["features"] if f["id"] == owner["id"]), {})
            if leader.get("type") == "FEATTYPE_CHAMFER":
                chamfers.append(
                    {
                        "name": d["name"],
                        "id": d["id"],
                        "feature": owner["name"],
                        "style": "cd" if q.get("chamfers") == "c" else "d_x_45",
                    }
                )
            if (
                leader.get("type") == "FEATTYPE_HOLE"
                and leader.get("pattern_count", 1) > 1
                and d["type"] == "diameter"
            ):
                rows[-1]["prefix"] = f"{leader['pattern_count']}X"
                counted.append(
                    {
                        "name": d["name"],
                        "id": d["id"],
                        "model": solid_name,
                        "feature": owner["name"],
                        "prefix": rows[-1]["prefix"],
                    }
                )
                solid["modified"] = True
        for row in rows:
            x, y = row["at"]
            row["box"] = [[x - 5, y - 2], [x + 5, y + 2]]
            row["sheet"] = 1
        m["shown_dims"] = rows
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "annotated": {
                "shown": len(rows),
                "by_view": {view: len(rows)} if rows else {},
                "refused": [],
                "taken_off": taken,
                "zeros_taken_off": zeros,
                "datums_taken_off": datums,
                "full_turns_taken_off": turns,
                "moved_into_sight": [],
                "diameters_on_their_steps": [],
                "counts_prefixed": counted,
                "counts_taken_off": [],
                "chamfers_called_out": chamfers,
                "threads_called_out": [],
                "brought_onto_the_sheet": [],
            }
        }

    def drawing_hide_dimension(self, q):
        name, m = self._drawing(q["model"])
        shown = m["shown_dims"]
        doomed = []
        for wanted in q["dimensions"]:
            dim, _, model = str(wanted).partition("@")
            hits = [
                d
                for d in shown
                if d["name"].lower() == dim.lower() and (not model or d["model"] == model.lower())
            ]
            if not hits:
                raise Refusal("E_NOT_FOUND", "the drawing shows no dimension " + str(wanted))
            if len(hits) > 1:
                raise Refusal("E_CONFLICT", "two models' dimensions are named " + str(wanted))
            doomed.append(hits[0])
        m["shown_dims"] = [d for d in shown if d not in doomed]
        m.setdefault("erased", set()).update(d["id"] for d in doomed)
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "taken_off": [
                {"name": d["name"], "id": d["id"], "how": "erased_from_drawing"} for d in doomed
            ]
        }

    def drawing_add_note(self, q):
        name, m = self._drawing(q["model"])
        note = {
            "id": 700 + len(m["notes"]),
            "text": q["text"],
            "displayed_text": q["text"],
            "at": [float(v) for v in q["at"]],
            "sheet": 1,
            "attachment_readback": {
                "complete": True,
                "kind": "free",
                "background": True,
                "sheet": 1,
                "view": "overlay_view",
                "view_id": "0",
                "source": "loopback fixture attachment; not SDK evidence",
            },
            "leaders": [],
            "leaders_complete": True,
            "bounds_readback": {
                "complete": False,
                "reason": "loopback fixture does not establish a native 2D envelope",
            },
        }
        m["notes"].append(note)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"note": dict(note)}

    def _note(self, m, raw):
        note = next((n for n in m["notes"] if n["id"] == int(raw)), None)
        if note is None:
            raise Refusal("E_NOT_FOUND", f"the drawing has no note {int(raw)}")
        return note

    def drawing_edit_note(self, q):
        name, m = self._drawing(q["model"])
        note = self._note(m, q["note"])
        if "at" in q and note["at"] is None:
            raise Refusal("E_CONFLICT", "the note is attached to something on the drawing")
        if "text" in q:
            note["text"] = q["text"]
        if "at" in q:
            note["at"] = [float(v) for v in q["at"]]
        m["modified"] = True
        return self.drawing_summary(name, m) | {"note": dict(note)}

    def drawing_move_dimension(self, q):
        name, m = self._drawing(q["model"])
        dim, _, model = str(q["dimension"]).partition("@")
        rows = [
            d
            for d in m["shown_dims"] + m.setdefault("own_dims", [])
            if d["name"].lower() == dim.lower() and (not model or d["model"] == model.lower())
        ]
        if len(rows) != 1:
            raise Refusal("E_NOT_FOUND", "the drawing shows no dimension " + str(q["dimension"]))
        old = rows[0].get("at")
        if old and rows[0].get("box"):
            rows[0]["box"] = [
                [point[i] + q["at"][i] - old[i] for i in (0, 1)] for point in rows[0]["box"]
            ]
        rows[0]["at"] = [float(v) for v in q["at"]]
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "moved": {"name": rows[0]["name"], "id": rows[0]["id"]}
        }

    def drawing_add_dimension(self, q):
        name, m = self._drawing(q["model"])
        view = next((v for v in m["views"] if v["name"] == q["view"]), None)
        if view is None:
            raise Refusal("E_NOT_FOUND", "no view named " + q["view"])
        _, solid = self.model(view["model"])
        a, b = self.item(solid, q["from"]), self.item(solid, q["to"])
        own = m.setdefault("own_dims", [])
        number = m.setdefault("next_own_dim", 0)
        m["next_own_dim"] += 1
        row = {
            "name": f"rdd{number}",
            "id": number,
            "model": name,
            "value": round(
                math.dist(a.get("center") or a.get("start"), b.get("center") or b.get("start")), 9
            ),
            "type": "linear",
            "feature": None,
            "view": q["view"],
            "reference": True,
            "at": [float(v) for v in q["at"]],
        }
        row["associative"] = True
        x, y = row["at"]
        row["box"] = [[x - 5, y - 2], [x + 5, y + 2]]
        row["sheet"] = view["sheet"]
        row["attachments"] = [
            {
                "ref": q[k],
                "model": view["model"],
                "sense": q.get(k + "_sense", "auto"),
            }
            for k in ("from", "to")
        ]
        own.append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"dimension": dict(row)}

    def drawing_add_table(self, q):
        name, m = self._drawing(q["model"])
        tables = m.setdefault("tables", [])
        rows, columns = len(q["rows"]), len(q["columns"])
        cells = [[""] * columns for _ in range(rows)]
        for r, line in enumerate(q.get("cells") or []):
            for c, value in enumerate(line):
                if value:
                    cells[r][c] = value
        for r1, c1, r2, c2 in q.get("merge") or []:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    if (r, c) != (r1, c1):
                        cells[r - 1][c - 1] = None
        row = {
            "id": 900 + len(tables),
            "rows": rows,
            "columns": columns,
            "cells": cells,
            "at": [float(v) for v in q["at"]],
            "size": [float(sum(q["columns"])), float(sum(q["rows"]))],
            "outline": [
                [float(q["at"][0]), float(q["at"][1]) - sum(q["rows"])],
                [float(q["at"][0]) + sum(q["columns"]), float(q["at"][1])],
            ],
            "sheet": 1,
            "segments": 1,
            "rotation": 0,
            "bounds_source": "loopback fixture table geometry",
            "from_format": False,
            "cell_references": [],
        }
        tables.append(row)
        m["modified"] = True
        out = {"table": dict(row)}
        if q.get("projection_symbol"):
            # Four lines and two circles, by the drawing's projection.
            m["entities"] = m.get("entities", 0) + 6
            arcs = m.setdefault("draft_arcs", [])
            for radius in [
                q["projection_symbol"]["height"] / 4,
                q["projection_symbol"]["height"] / 2,
            ]:
                arcs.append(
                    {
                        "id": 2000 + len(arcs),
                        "sheet": 1,
                        "radius": radius,
                        "start_angle": 0,
                        "end_angle": 2 * math.pi,
                    }
                )
            out["projection_symbol"] = {
                "projection": m.get("projection"),
                "at": q["projection_symbol"]["at"],
                "height": q["projection_symbol"]["height"],
                "entities": 6,
            }
        return self.drawing_summary(name, m) | out

    NUMERIC = {"roughness_height"}
    SYMBOLS = {
        "surffins/generic/standard": ["roughness_height"],
        "library_syms/weldsymlib/iso_weld/iso_fillet": ["weld_size", "weld_length"],
    }

    def _symbol(self, raw):
        if Path(raw).is_absolute():
            file = Path(raw)
            if not file.is_file():
                return None, []
            return file, re.findall(
                r"(?<![A-Za-z0-9_:\\])\\([A-Za-z_][A-Za-z0-9_]{0,40})\\(?![A-Za-z0-9_\\])",
                file.read_text("latin-1"),
            )
        return (raw, self.SYMBOLS[raw]) if raw in self.SYMBOLS else (None, [])

    def drawing_symbol(self, q):
        found, variables = self._symbol(q["symbol"])
        if found is None:
            return {"symbol": None, "library": sorted(self.SYMBOLS)}
        return {"symbol": {"name": q["symbol"], "path": str(found), "variables": variables}}

    def drawing_add_symbol(self, q):
        name, m = self._drawing(q["model"])
        found, variables = self._symbol(q["symbol"])
        if found is None:
            raise Refusal("E_NOT_FOUND", "no symbol definition " + q["symbol"])
        symbols = m.setdefault("symbols", [])
        base = Path(str(q["symbol"])).name.removesuffix(".sym")
        row = {
            "id": 800 + len(symbols),
            "definition": base,
            "at": [float(v) for v in q["at"]],
            "values": {
                # Creo keeps a numeric variable as a number and shows it in the drawing's own
                # format: 3.2 as 3,200 on its metric sheets.
                k: f"{float(v):.3f}".replace(".", ",") if k in self.NUMERIC else v
                for k, v in (q.get("values") or {}).items()
            },
        }
        symbols.append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "symbol": {"id": row["id"], "definition": base, "variables": variables}
        }

    def drawing_add_bom(self, q):
        """Creo's own parts list, filled from the drawn assembly: one row per model, counted."""
        name, m = self._drawing(q["model"])
        of = m["drawing_models"][0]
        _, assembly = self.model(of)
        if assembly["type"] != "assembly":
            raise Refusal("E_CONFLICT", "the drawing shows no assembly")
        counts = {}
        for c in assembly.get("components", []):
            counts[c["model"]] = counts.get(c["model"], 0) + 1
        cells = [["ITEM\nNO", "PART NUMBER", "QTY", "DESCRIPTION", "NOTES"]]
        for i, (model, n) in enumerate(counts.items(), 1):
            cells.append([str(i), model.split(".")[0].upper(), str(n), "", None])
        tables = m.setdefault("tables", [])
        row = {
            "id": 900 + len(tables),
            "rows": len(cells),
            "columns": 5,
            "cells": cells,
            "at": [float(v) for v in q["at"]],
            "size": [217.043, 7.62 * len(cells)],
            "outline": [
                [float(q["at"][0]), float(q["at"][1]) - 7.62 * len(cells)],
                [float(q["at"][0]) + 217.043, float(q["at"][1])],
            ],
            "sheet": 1,
            "segments": 1,
            "rotation": 0,
            "bounds_source": "loopback fixture BOM table geometry",
            "from_format": False,
            "bom": list(counts),
            "cell_references": [
                {
                    "row": index + 2,
                    "column": 2,
                    "model": model,
                    "assembly": of,
                    "source": "loopback repeat-region cell reference",
                }
                for index, model in enumerate(counts)
            ],
        }
        tables.append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "table": {k: v for k, v in row.items() if k != "bom"}
        }

    def drawing_add_balloons(self, q):
        name, m = self._drawing(q["model"])
        table = next((t for t in m.get("tables", []) if t["id"] == int(q["table"])), None)
        if table is None:
            raise Refusal("E_NOT_FOUND", "the drawing has no table " + str(q["table"]))
        made = 0
        assembly = m["drawing_models"][0]
        for i, model in enumerate(table.get("bom", []), 1):
            component = next(c for c in self.models[assembly]["components"] if c["model"] == model)
            m["notes"].append(
                {
                    "id": 700 + len(m["notes"]),
                    "text": f" {i} ",
                    "at": [100.0, 60.0 + 20 * i],
                    "displayed_text": str(i),
                    "leaders_complete": True,
                    "leaders": [
                        {
                            "model": model,
                            "component_path": [str(component["id"])],
                            "root": assembly,
                            "view": q.get("view"),
                            "item_id": 12,
                            "item_type": "edge",
                        }
                    ],
                }
            )
            made += 1
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "balloons": {"table": table["id"], "view": q.get("view"), "made": made}
        }

    def drawing_move_table(self, q):
        name, m = self._drawing(q["model"])
        table = next((t for t in m.get("tables", []) if t["id"] == int(q["table"])), None)
        if table is None:
            raise Refusal("E_NOT_FOUND", "the drawing has no table " + str(q["table"]))
        delta = [q["at"][i] - table["at"][i] for i in (0, 1)]
        if table.get("outline"):
            table["outline"] = [[p[i] + delta[i] for i in (0, 1)] for p in table["outline"]]
        table["at"] = [float(v) for v in q["at"]]
        m["modified"] = True
        return self.drawing_summary(name, m) | {
            "table": {k: v for k, v in table.items() if k != "bom"}
        }

    def drawing_add_datum(self, q):
        name, m = self._drawing(q["model"])
        datums = m.setdefault("datums", [])
        if any(d["label"] == q["label"] for d in datums):
            raise Refusal("E_CONFLICT", "the drawing already has datum " + q["label"])
        _, solid = self.model(m["drawing_models"][0])
        self.item(solid, q["on"])
        row = {"id": len(datums), "label": q["label"], "on": q["on"]}
        datums.append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"datum": dict(row)}

    def drawing_add_gtol(self, q):
        name, m = self._drawing(q["model"])
        frames = m.setdefault("gtols", [])
        attach = q["attach"]
        # Creo writes its own symbols into the value, and keeps a frame on a model's dimension
        # with that model.
        value = ("⌀" if q.get("diameter") else "") + q["value"]
        value += {"mmc": "Ⓜ", "lmc": "Ⓛ"}.get(q.get("material"), "")
        if "dimension" in attach:
            dim, _, owner = attach["dimension"].partition("@")
            if not any(d["name"] == dim for d in m["shown_dims"]):
                raise Refusal("E_NOT_FOUND", "the drawing shows no dimension " + dim)
            owner_name, kind, at = owner, "annotation", None
        else:
            owner_name = name
            kind = "leaders" if "on" in attach else "free"
            at = [float(v) for v in attach["at"]]
        row = {
            "id": sum(1 for f in frames if f["model"] == owner_name),
            "model": owner_name,
            "type": q["type"],
            "value": value,
            "datums": list(q.get("datums") or []),
            "attached": kind,
            "at": at,
        }
        frames.append(row)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"gtol": dict(row)}

    def drawing_remove(self, q):
        name, m = self._drawing(q["model"])
        kind, _, key = str(q["item"]).partition(":")
        place = {
            "note": "notes",
            "table": "tables",
            "symbol": "symbols",
            "dimension": "own_dims",
            "view": "views",
            "gtol": "gtols",
            "datum": "datums",
        }
        rows = m.setdefault(place[kind], [])
        if kind == "gtol":
            number, _, owner = key.partition("@")
            owner = owner or name
            hit = next((r for r in rows if str(r["id"]) == number and r["model"] == owner), None)
        elif kind == "datum":
            hit = next((r for r in rows if r["label"] == key), None)
        elif kind == "view":
            hit = next((r for r in rows if r["name"] == key), None)
            if hit is not None and any(r.get("parent") == key for r in rows):
                raise Refusal("E_CONFLICT", f"view {key} has views taken from it")
        elif kind == "dimension":
            hit = next((r for r in rows if r["name"].lower() == key.lower()), None)
        else:
            hit = next((r for r in rows if str(r["id"]) == key), None)
        if hit is None:
            raise Refusal("E_NOT_FOUND", f"the drawing has no {kind} {key}")
        rows.remove(hit)
        m["modified"] = True
        return self.drawing_summary(name, m) | {"removed": {"item": q["item"], **hit}}

    def relation_list(self, q):
        name, m = self.model(q["model"])
        return {"model": name, "relations": list(m.get("relations", []))}

    def relation_set(self, q):
        """A relation drives the dimension on its left: d2 = d1 / 2 makes d2 half of d1."""
        name, m = self.model(q["model"])
        before = list(m.get("relations", []))
        dims = {d["name"]: d for d in m["dimensions"]}
        for line in q["relations"]:
            if line.strip().startswith("/*"):
                continue
            left, eq, right = line.partition("=")
            if not eq or left.strip() not in dims:
                raise Refusal("E_CREO", f"the relation does not evaluate: {line}")
        m["relations"] = list(q["relations"])
        for d in m["dimensions"]:
            d["relation_driven"] = False
        for line in q["relations"]:
            left, eq, right = line.partition("=")
            if eq and left.strip() in dims:
                target = dims[left.strip()]
                target["relation_driven"] = True
                target["value"] = float(eval(right, {}, {k: v["value"] for k, v in dims.items()}))  # noqa: S307
        m["modified"] = True
        return {
            "model": name,
            "relations": list(m["relations"]),
            "relations_before": before,
            "volume": {"before": m["volume"], "after": m["volume"], "change": 0.0},
            "dimensions": [dict(d) for d in m["dimensions"] if d.get("type")],
        }

    def import_model(self, q):
        """An exchange file read as a new part (or assembly), in session, unsaved."""
        path = Path(q["path"])
        if not path.is_file():
            raise Refusal("E_NOT_FOUND", f"{path} does not exist")
        kind = q.get("type") or ("assembly" if b"ASSEMBLY" in path.read_bytes()[:4096] else "part")
        name = self.name(q["name"] + (".asm" if kind == "assembly" else ".prt"))
        if name in self.models:
            raise Refusal("E_CONFLICT", name + " is already in session")
        from tests.fixture import MM

        m = self.part(name, MM, modified=True)
        m["volume"] = 8000.0
        if kind == "assembly":
            m["components"] = []
        return self.summary(name, m) | {"imported": {"path": str(path), "format": q["format"]}}

    def p2_op(self, op, q):
        """The P2 operations by name, or None for an op this mixin does not know."""
        table = {
            "geometry.list": self.geometry_list,
            "geometry.measure": self.geometry_measure,
            "geometry.ray": self.geometry_ray,
            "dimension.list": self.dimension_list,
            "dimension.set": self.dimension_set,
            "dimension.tolerance": self.dimension_tolerance,
            "model.set-tolerance-standard": self.set_tolerance_standard,
            "parameter.list": self.parameter_list,
            "parameter.set": self.parameter_set,
            "material.list": self.material_list,
            "material.assign": self.material_assign,
            "model.render": self.render,
            "model.render-state": self.render_state,
            "artifact.jpeg-inspect": self.inspect_jpeg,
            "model.import": self.import_model,
            "relation.list": self.relation_list,
            "relation.set": self.relation_set,
            "model.export": self.export,
            "feature.suppress": lambda x: self.set_status(x, True),
            "feature.resume": lambda x: self.set_status(x, False),
            "feature.rename": self.rename,
            "feature.revolve": self.revolve,
            "feature.datum-plane": self.datum_plane,
            "feature.datum-axis": self.datum_axis,
            "feature.round": lambda x: self.edge_feature(x, True),
            "feature.chamfer": lambda x: self.edge_feature(x, False),
            "feature.hole": self.hole,
            "feature.shell": self.shell,
            "feature.draft": self.draft,
            "hole.chart": self.hole_chart,
            "feature.thread": self.thread,
            "feature.rib": self.rib,
            "feature.sweep": self.sweep,
            "family.show": self.family_show,
            "family.set": self.family_set,
            "family.remove": self.family_remove,
            "feature.pattern": self.pattern,
            "feature.mirror": self.mirror,
            "assembly.add": self.assembly_add,
            "assembly.remove": self.assembly_remove,
            "assembly.replace": self.assembly_replace,
            "assembly.explode": self.assembly_explode,
            "assembly.check": self.assembly_check,
            "drawing.create": self.drawing_create,
            "drawing.lay-out": self.drawing_lay_out,
            "drawing.add-view": self.drawing_add_view,
            "drawing.move-view": self.drawing_move_view,
            "drawing.annotate": self.drawing_annotate,
            "drawing.hide-dimension": self.drawing_hide_dimension,
            "drawing.add-note": self.drawing_add_note,
            "drawing.edit-note": self.drawing_edit_note,
            "drawing.move-dimension": self.drawing_move_dimension,
            "drawing.add-dimension": self.drawing_add_dimension,
            "drawing.add-table": self.drawing_add_table,
            "drawing.symbol": self.drawing_symbol,
            "drawing.add-symbol": self.drawing_add_symbol,
            "drawing.remove": self.drawing_remove,
            "drawing.add-datum": self.drawing_add_datum,
            "drawing.add-bom": self.drawing_add_bom,
            "drawing.bom-template": lambda q: {
                "path": str(self.bom_template)
                if q["table"] == "Assembly/bom_description_down"
                else q["table"]
            },
            "drawing.add-balloons": self.drawing_add_balloons,
            "drawing.move-table": self.drawing_move_table,
            "drawing.add-gtol": self.drawing_add_gtol,
        }
        handler = table.get(op)
        return None if handler is None else handler(q)
