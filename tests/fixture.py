"""Stateful substitute for the service that runs inside Creo (service/). No Creo, no PTC SDK.

Written from the service's protocol -- Service.java, Ops.java and docs/SERVICE.md -- and
independent of the CLI code. It exercises the CLI's side of the contract: tokens, previews
bound to observed state, receipts, failure handling. It models just enough of a model
(features with parents and children, a volume, versions on disk) to be read back; it is not
geometry, and its volume arithmetic assumes profiles never overlap existing material.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from .fixture_features import Features, Refusal
    from .fixture_presentation import PresentationFixture
except ImportError:  # run as a top-level module
    from fixture_features import Features, Refusal
    from fixture_presentation import PresentationFixture

BLOCK_CEILING_SECONDS = 30.0
MM = {"system": "millimeter Newton Second (mmNs)", "length": "mm", "mass": "tonne"}
INCH = {"system": "Inch lbm Second (Creo Parametric Default)", "length": "in", "mass": "lbm"}
DEFAULT_FEATURES = [
    (1, "RIGHT", "FEATTYPE_DATUM_PLANE"),
    (3, "TOP", "FEATTYPE_DATUM_PLANE"),
    (5, "FRONT", "FEATTYPE_DATUM_PLANE"),
    (7, "PRT_CSYS_DEF", "FEATTYPE_COORD_SYS"),
]
TYPES = {"prt": "part", "asm": "assembly", "drw": "drawing"}


class Refused(Exception):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.error = {"code": code, "message": message, **extra}


class World(PresentationFixture, Features):
    def __init__(self, root: Path):
        self.root = root
        self.token = "5eed" * 16
        self.protocol = 2
        self.capabilities = {
            "dimension_regeneration_readback": 1,
            "drawing_window_activation": 1,
            "model_regeneration": 1,
            "bom_reference_readback": 2,
            "title_projection_arcs": 2,
            "explosion_state_readback": 2,
            "geometry_binary64_readback": 1,
            "assembly_explosion_context_readback": 1,
            "render_state_restoration": 3,
            "source_part_appearance": 2,
            "source_part_appearance_reference": 1,
            "source_part_appearance_unique_reference": 1,
            "protected_definition_readback": 1,
            "native_presentation": 2,
            "machining_feature_readback": 1,
            "revolved_datum_readback": 1,
            "drawing_view_dependencies": 1,
            "drawing_view_exploded_readback": 1,
            "simple_drawing_note_readback": 1,
            "model_management_readback": 2,
            "model_close_lifecycle": 1,
            "family_dimension_runtime": 1,
            "prismatic_shell_readback": 2,
            "prismatic_draft_readback": 1,
            "material_source_binding": 1,
            "numeric_tolerance_regeneration_readback": 1,
            "tolerance_standard_numeric_preservation": 1,
        }
        from tests.fixture_features import LIBRARY

        self.material_library = root / "material-library"
        self.material_library.mkdir()
        for name, _, density in LIBRARY:
            (self.material_library / (name + ".mtl")).write_text(
                "ND_RelParSet_K01 = {\nName = " + name + "\nPARAMETERS =\n{\n"
                "Name = PTC_MASS_DENSITY\nType = Real\nDefault = "
                + str(density)
                + " tonne / mm^3\nAccess = Full\n}\n}\n"
            )
        self.cwd = root
        self.models: dict[str, dict] = {}
        self.active = None
        self.native = True
        self.creation_api = True
        self.events: list[tuple[str, dict]] = []
        self.wait_headers: list[str | None] = []
        self.fail = None  # (op, error): reply ok:false without acting
        self.fail_after = (
            None  # (op, error): act, then reply ok:false -- a Creo failure that left work behind
        )
        self.drop = None  # op: act, then lose the reply
        self.busy = None  # op: withdrawn before it started
        self.overrun = None  # op: act, then report started-but-unfinished
        self.block = None  # (op, threading.Event): hold the reply
        self.lie = None  # op: report success without acting
        # (write_op, op, error): once write_op has succeeded, the next op replies with error --
        # a read-back that fails after a write.
        self.then_fail = None
        self.succeeded: set[str] = set()
        self.wrong_type = False  # extrude reports the wrong feature type
        self.health_broken = False

    # ----------------------------------------------------------------- model state

    def part(self, name, units=MM, origin=None, modified=False):
        features = [
            {
                "id": i,
                "name": n,
                "type": t,
                "status": "FEAT_ACTIVE",
                "visible": True,
                "parents": [],
                "children": [],
                "surfaces": 1 if "PLANE" in t else 0,
                # Controlled fixture data represents a complete hypothetical
                # default-datum observation; it is not native Creo qualification.
                **(
                    {
                        "native_definition": {
                            "complete": True,
                            "kind": "datum_plane",
                            "source": "controlled fixture",
                            "default_name": n,
                        }
                    }
                    if t == "FEATTYPE_DATUM_PLANE"
                    else {}
                ),
            }
            for i, n, t in DEFAULT_FEATURES
        ]
        self.models[name] = {
            "type": TYPES[name.rsplit(".", 1)[1]],
            "units": dict(units),
            "features": features,
            "volume": 0.0,
            "origin": origin,
            "modified": modified,
            "next_id": 40,
        }
        self.seed_geometry(self.models[name])
        return self.models[name]

    def name(self, raw):
        text = raw.lower()
        base, _, ext = text.partition(".")
        ext = ext.split(".")[0] if ext else "prt"
        if not base or not base[0].isalpha() or len(base) > 31 or ext not in TYPES:
            raise Refused("E_VALIDATION", f"'{raw}' is not a valid Creo model name")
        return base + "." + ext

    def model(self, raw):
        name = self.name(raw)
        if name not in self.models:
            raise Refused(
                "E_NOT_FOUND",
                "no "
                + TYPES[name.split(".")[1]]
                + " named "
                + name.split(".")[0]
                + " is in session",
            )
        return name, self.models[name]

    def feature(self, m, wanted):
        for f in m["features"]:
            if str(f["name"]).upper() == str(wanted).upper() or str(f["id"]) == str(wanted):
                return f
        raise Refused("E_NOT_FOUND", "no feature named or numbered " + str(wanted))

    def planes(self, m):
        return [
            f["name"] for f in m["features"] if f["type"] == "FEATTYPE_DATUM_PLANE" and f["visible"]
        ]

    def row(self, f):
        return {
            "id": f["id"],
            "name": f["name"],
            "type": f["type"],
            "status": f["status"],
            "number": f.get("number"),
            "visible": f["visible"],
        }

    def versions(self, directory: Path, name: str) -> list[Path]:
        found = [
            p
            for p in directory.iterdir()
            if p.name.lower().startswith(name + ".") and p.name[len(name) + 1 :].isdigit()
        ]
        return sorted(found, key=lambda p: int(p.name[len(name) + 1 :]))

    def write_version(self, directory: Path, name: str, m: dict) -> Path:
        found = self.versions(directory, name)
        n = int(found[-1].name[len(name) + 1 :]) + 1 if found else 1
        out = directory / f"{name}.{n}"
        out.write_bytes(
            b"SUBSTITUTE, NOT A CREO MODEL: "
            + json.dumps([f["name"] for f in m["features"]]).encode()
        )
        m["origin"], m["modified"] = str(out), False
        self.presentation_record_save(out, m)
        return out

    def summary(self, name, m):
        if m["type"] == "drawing":
            return self.drawing_summary(name, m)
        visible = [f for f in m["features"] if f["visible"]]
        out = {
            "model": name,
            "type": m["type"],
            "units": m["units"],
            "material": m.get("material"),
            "mass_properties": self.mass_properties(m),
            "bbox": m.get("bbox", [[-20.0, -10.0, -10.0], [20.0, 10.0, 0.0]])
            if m["volume"]
            else {"error": {"code": "E_CREO"}},
            "bodies": [{"id": -5778, "name": None, "state": "BODY_STATE_ACTIVE"}],
            "datum_planes": self.planes(m),
            "cross_sections": [dict(x) for x in m.get("cross_sections", [])],
            "tolerance_standard": m.get("tolerance_standard", "ansi"),
            "tolerance_class": m.get("tolerance_class"),
            "common_name": m.get("common_name"),
            "common_name_readback": m.get(
                "common_name_readback",
                {
                    "readable": True,
                    "modifiable": True,
                    "value": m.get("common_name"),
                    "source": "fixture Model.GetCommonName/IsCommonNameModifiable",
                },
            ),
            "family": self.family_info(name, m),
            "feature_count": len(visible),
            "origin": m["origin"],
            "origin_readback": self.origin_info(m),
            "modified": m["modified"],
        }
        if m["type"] == "assembly":
            import copy

            out["components"] = [dict(c) for c in m.get("components", [])]
            for c in out["components"]:
                c["component_path_transform"] = copy.deepcopy(c.get("position"))
            out["exploded_states"] = [{k: v for k, v in x.items()} for x in self.states_of(m)]
            active = next((x for x in self.states_of(m) if x["active"]), None)
            out["explosion"] = {
                "complete": True,
                "states": out["exploded_states"],
                "active_state_id": str(active["id"]) if active else None,
                "is_exploded": m.get("is_exploded", False),
                "source": "fixture explosion readback",
            }
            current = self.active or name
            kind = self.models[current]["type"]
            admitted = current == name and kind == "assembly"
            context = {
                "complete": True,
                "kind": "assembly"
                if admitted
                else "drawing"
                if kind == "drawing"
                else "other_model",
                "assembly_context_admitted": admitted,
                "target_model": name,
                "current_model": current,
                "current_model_type": kind,
                "window_model": current,
                "window_model_type": kind,
                "window_id": str(list(self.models).index(current)),
                "source": "Session.GetCurrentModel/GetCurrentWindow; "
                "Window.GetModel; Model.GetType/GetFileName",
            }
            out["explosion"]["context"] = copy.deepcopy(m.get("explosion_context", context))
            out["explosion"]["display_readback"] = {
                "complete": admitted,
                "status": "observed"
                if admitted
                else "not_checked"
                if kind == "drawing"
                else "incomplete",
                "value": m.get("is_exploded", False) if admitted else None,
                "source": "Assembly.GetIsExploded",
            }
            if not admitted:
                out["explosion"]["is_exploded"] = None
                out["explosion"]["display_readback"]["reason"] = (
                    "not_applicable_in_drawing_context; GetIsExploded not called"
                    if kind == "drawing"
                    else "assembly_context_not_admitted; GetIsExploded not called"
                )
            # Native GetPosition reports active display displacement in the bounded profile.
            if active and m.get("is_exploded", False):
                import copy

                out["components"] = copy.deepcopy(out["components"])
                for move in active["moves"] or []:
                    if len(move.get("direction", [])) != 3:
                        continue
                    for component in out["components"]:
                        if component["id"] in move["components"]:
                            component["position"]["origin"] = [
                                x + d * move["distance"]
                                for x, d in zip(
                                    component["position"]["origin"], move["direction"], strict=True
                                )
                            ]
                            component["component_path_transform"] = copy.deepcopy(
                                component["position"]
                            )
        return out

    def origin_info(self, model):
        return model.get(
            "origin_readback",
            {
                "complete": True,
                "state": "saved" if model["origin"] else "no_origin",
                "value": model["origin"],
                "source": "fixture Model.GetOrigin",
                "new_model_proven": False,
            },
        )

    def family_info(self, name, model):
        rows = list((model.get("family") or {}).get("rows", {}))
        columns = len((model.get("family") or {}).get("columns", {}))
        generic = model.get("generic")
        return model.get(
            "family_readback",
            {
                "complete": True,
                "kind": "instance" if generic else "generic" if rows or columns else "standalone",
                "generic": generic,
                "instances": rows,
                "row_count": len(rows),
                "column_count": columns,
                "source": "fixture FamilyMember native getters",
            },
        )

    # ----------------------------------------------------------------- ops

    def session(self):
        return {
            "protocol": self.protocol,
            "creation_api": self.creation_api,
            "creo_version": "Creo 13",
            "creo_build": "2026163",
            "working_directory": str(self.cwd) + os.sep,
            "models": list(self.models),
            "active_model": self.active,
            "native_sketch_available": self.native,
            "native_sketch_library": "loaded by Creo, found by handshake id 1"
            if self.native
            else "not registered",
        }

    def management_state(self):
        """One synthetic model/window observation; never a Native timing claim."""
        models, windows = [], []
        for name, model in self.models.items():
            dependencies = model.get("native_dependencies", model.get("drawing_models", []))
            if model["type"] == "assembly":
                dependencies = [c["model"] for c in model.get("components", [])]
            models.append(
                {
                    "model": name,
                    "type": model["type"],
                    "origin": model["origin"],
                    "origin_readback": self.origin_info(model),
                    "family": self.family_info(name, model),
                    "modified": model["modified"],
                    "version_stamp": str(id(model)),
                    "relation_id": str(id(model)),
                    "dependencies": dependencies,
                    "dependencies_complete": model.get("dependencies_complete", True),
                }
            )
            if not model.get("window_closed", False):
                windows.append({"id": str(id(model)), "model": name})
        current = next((w["id"] for w in windows if w["model"] == self.active), None)
        return {
            "completed": True,
            "models": models,
            "windows": windows,
            "active_window": current,
            "active_model": self.active,
            "source": "fixture native session/model/window getters",
        }

    def op(self, op, q):
        presentation_result = self.presentation_op(op, q)
        if presentation_result is not None:
            return presentation_result
        if op == "model.management-state":
            return self.management_state()
        if op == "model.regenerate":
            return {"model": q["model"]}
        if op == "drawing.activate":
            return {"model": q["model"], "window_activated": True}
        if op in ("geometry.mass-properties", "geometry.bounds"):
            name, model = self.model(q["model"])
            snapshot = self.summary(name, model)
            return {
                "model": name,
                "units": model["units"],
                "completed": True,
                "source": "fixture:getter",
                "data": snapshot["bbox"] if op.endswith("bounds") else snapshot["mass_properties"],
            }
        if op in (
            "assembly.components",
            "assembly.placement",
            "assembly.exploded-states",
            "assembly.check",
        ):
            name, model = self.model(q["model"])
            if op == "assembly.check":
                return self.assembly_check(q) | {
                    "completed": True,
                    "source": "fixture:interference",
                    "coverage": {"scope": "all"},
                }
            if model["type"] != "assembly":
                raise Refused("E_VALIDATION", "not an assembly")
            rows = (
                copy.deepcopy(model.get("components", []))
                if not op.endswith("states")
                else copy.deepcopy(self.states_of(model))
            )
            out = {
                "model": name,
                "items": rows,
                "completed": True,
                "source": "fixture:assembly-getters",
                "scope": "top_level",
                "coverage": {"count": len(rows), "recursive": False},
            }
            if op == "assembly.placement":
                out["not_fully_constrained"] = sum(
                    bool(r.get("packaged") or r.get("underconstrained")) for r in rows
                )
            return out
        if op in ("drawing.info", "drawing.resources", "drawing.apply-layout"):
            name, model = self.model(q["model"])
            if model["type"] != "drawing":
                raise Refused("E_VALIDATION", "not a drawing")
            if op == "drawing.apply-layout":
                for move in q["views"]:
                    self.drawing_move_view({"model": name, **move})
                return self.drawing_summary(name, model)
            snapshot = self.drawing_summary(name, model)
            if op == "drawing.info":
                return {
                    "model": name,
                    "sheet_count": len(snapshot["sheets"]),
                    "projection": snapshot["projection"],
                    "models": snapshot["models"],
                    "completed": True,
                    "source": "fixture:drawing-info",
                }
            rows = copy.deepcopy(
                model.get("draft_entity_items", [])
                if q["kind"] == "entities"
                else snapshot[q["kind"]]
            )
            if q.get("sheet") is not None:
                if any(r.get("sheet", r.get("number")) is None for r in rows):
                    raise Refused("E_VERIFY_INCOMPLETE", "fixture sheet ownership unavailable")
                rows = [r for r in rows if r.get("sheet", r.get("number")) == q["sheet"]]
            return {
                "model": name,
                "items": rows,
                "completed": True,
                "source": "fixture:resource-getters",
                "scope": "all_sheets" if q.get("sheet") is None else f"sheet:{q['sheet']}",
                "coverage": {
                    "count": len(rows),
                    "view_removal_scope": {"complete": True, "unsupported": []},
                },
            }
        if op == "session.status":
            return self.session()
        if op == "session.cd":
            target = Path(q["path"])
            if not target.is_dir():
                raise Refused("E_NOT_FOUND", f"{target} is not an existing directory")
            self.cwd = target
            return {"working_directory": str(target) + os.sep}
        if op == "model.list":
            return {
                "models": [
                    {
                        "model": n,
                        "type": m["type"],
                        "modified": m["modified"],
                        "origin": m["origin"],
                        "displayed": True,
                        "active": n == self.active,
                    }
                    for n, m in self.models.items()
                ]
            }
        if op in ("part.create", "assembly.create"):
            name = self.name(q["name"])
            if name in self.models:
                raise Refused("E_CONFLICT", "a model named " + name + " is already in session")
            if ("units" in q) == ("template" in q):
                raise Refused("E_VALIDATION", "give exactly one of 'units' or 'template'")
            units = {"mmns": MM, "inlbs": INCH, "session_default": INCH}.get(q.get("units"), MM)
            m = self.part(name, units)
            if op == "assembly.create":
                self.make_assembly(m)
            self.write_version(Path(self.cwd), name, m)
            self.active = name
            shipped = "asm_design_abs.asm" if op == "assembly.create" else "part_solid_abs.prt"
            template = (
                q.get("template") or f"C:\\PTC\\Common Files\\templates\\{q['units']}_{shipped}"
            )
            return {
                "model": name,
                "template": template,
                "units": m["units"],
                "datum_planes": self.planes(m),
                "displayed": True,
                "working_directory": str(self.cwd) + os.sep,
                "origin": m["origin"],
                "modified": m["modified"],
            }
        if op == "model.show":
            name, m = self.model(q["model"])
            return self.summary(name, m)
        if op == "model.open":
            path = Path(q["path"])
            if not path.is_file():
                raise Refused("E_NOT_FOUND", f"{path} does not exist")
            name = self.name(path.name.split(".")[0] + "." + path.name.split(".")[1])
            if name in self.models and not q.get("instance"):
                raise Refused("E_CONFLICT", name + " is already in session")
            opened = name not in self.models
            m = self.models[name] if not opened else self.part(name, MM, origin=str(path))
            if q.get("instance"):
                inst = self.open_instance(name, m, q["instance"])
                self.active = inst
                return self.summary(inst, self.models[inst]) | {
                    "displayed": True,
                    "generic_opened": opened,
                }
            self.active = name
            return self.summary(name, m) | {"displayed": True}
        if op == "model.set-common-name":
            name, m = self.model(q["model"])
            if m["type"] == "drawing":
                raise Refused("E_VALIDATION", name + " is not a part or assembly")
            before = m.get("common_name")
            m["common_name"] = q["name"]
            m["modified"] = True
            return {
                "model": name,
                "common_name": q["name"],
                "before": before,
                "modified": m["modified"],
            }
        if op == "model.save":
            name, m = self.model(q["model"])
            if m.get("generic"):
                raise Refused(
                    "E_VALIDATION",
                    name + " is an instance of " + m["generic"] + "'s family table and has no "
                    "file of its own; save " + m["generic"],
                )
            directory = Path(m["origin"]).parent if m["origin"] else Path(self.cwd)
            out = self.write_version(directory, name, m)
            # Observed on Creo13: saving the generic clears newly regenerated member dirty flags.
            for member in self.models.values():
                if member.get("generic") == name:
                    member["modified"] = False
                    member["origin"] = str(out)
            return {
                "model": name,
                "directory": str(directory),
                "file": str(out),
                "file_bytes": out.stat().st_size,
                "on_disk": True,
                "origin": m["origin"],
                "modified": m["modified"],
            }
        if op in ("model.close", "model.discard"):
            name, m = self.model(q["model"])
            before = self.management_state()
            before["models"].sort(key=lambda row: row["model"])
            before["windows"].sort(key=lambda row: row["id"])
            if op == "model.close" and q.get("expected_session") != before:
                raise Refused(
                    "E_CONFLICT",
                    "complete model/window baseline changed before close dispatch",
                    started=False,
                )
            unsaved = m["modified"]
            if unsaved and op == "model.close":
                raise Refused(
                    "E_CONFLICT", name + " holds unsaved changes; save it first, or discard them"
                )
            del self.models[name]
            if self.active == name:
                self.active = None
            result = {
                "model": name,
                "window_closed": True,
                "erased": True,
                "discarded_changes": unsaved and op == "model.discard",
            }
            if op == "model.close":
                after = self.management_state()
                after["models"].sort(key=lambda row: row["model"])
                after["windows"].sort(key=lambda row: row["id"])
                result |= {
                    "lifecycle_before": before,
                    "lifecycle_after": after,
                    "window_close_tick": 1,
                    "erase_tick": 2,
                    "verification_tick": 3,
                    "returned_to_creo_before_erase": True,
                    "controlled_peer_only": True,
                }
            return result
        if op == "model.definition-state":
            name, m = self.model(q["model"])
            rows = []
            for f in m["features"]:
                if not f["visible"] or f["type"] == "FEATTYPE_COMPONENT":
                    continue
                raw = json.dumps(
                    {k: v for k, v in f.items() if k != "children"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                read = f.get(
                    "definition_observation",
                    {
                        "status": "success",
                        "complete": True,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "canonical_bytes": len(raw),
                        "source": "controlled fixture only",
                    },
                )
                rows.append(
                    {"id": str(f["id"]), "type": f["type"], "definition": copy.deepcopy(read)}
                )
            return {
                "model": name,
                "status": "success",
                "complete": True,
                "features": rows,
                "visible_feature_count": len([f for f in m["features"] if f["visible"]]),
                "excluded_component_count": len(
                    [f for f in m["features"] if f["visible"] and f["type"] == "FEATTYPE_COMPONENT"]
                ),
                "scope": "visible non-component native element trees; "
                "components use constraint/transform protection",
            }
        if op == "feature.list":
            name, m = self.model(q["model"])
            rows = [self.row(f) for f in m["features"] if q.get("include_internal") or f["visible"]]
            return {"model": name, "features": rows}
        if op == "feature.show":
            name, m = self.model(q["model"])
            f = self.feature(m, q["feature"])
            ids = {x["id"]: x for x in m["features"]}
            return self.row(f) | {
                "native_definition_status": "unsupported"
                if f.get("native_definition") is None
                else "success"
                if f["native_definition"].get("complete")
                else "failure",
                "native_tree_observation": f.get(
                    "definition_observation",
                    {
                        "status": "success",
                        "complete": True,
                        "sha256": hashlib.sha256(
                            json.dumps(
                                {k: v for k, v in f.items() if k != "children"}, sort_keys=True
                            ).encode()
                        ).hexdigest(),
                        "canonical_bytes": 100,
                        "source": "controlled fixture only",
                    },
                ),
                "parents": [
                    {
                        "id": i,
                        "name": ids[i]["name"],
                        "type": ids[i]["type"],
                        "visible": ids[i]["visible"],
                    }
                    for i in f["parents"]
                    if i in ids
                ],
                "children": [
                    {
                        "id": i,
                        "name": ids[i]["name"],
                        "type": ids[i]["type"],
                        "visible": ids[i]["visible"],
                    }
                    for i in f["children"]
                    if i in ids
                ],
                "dimensions": [{"name": "d1", "value": 10.0, "type": "DIM_LINEAR"}],
                "sections": [{"name": "Section 1", "entities": []}],
                **(
                    {"native_section_readback": copy.deepcopy(f["native_section_readback"])}
                    if "native_section_readback" in f
                    else {}
                ),
                **(
                    {"native_definition": copy.deepcopy(f["native_definition"])}
                    if "native_definition" in f
                    else {}
                ),
                **(
                    {
                        "native_solid_geometry": self.geometry_list(
                            {"model": name, "profile": "prismatic-shell-v1"}
                        )
                    }
                    if f["type"] in ("FEATTYPE_SHELL", "FEATTYPE_DRAFT")
                    else {}
                ),
            }
        if op == "feature.delete":
            name, m = self.model(q["model"])
            f = self.feature(m, q["feature"])
            doomed, queue = [], [f["id"]]
            by_id = {x["id"]: x for x in m["features"]}
            while queue:
                i = queue.pop(0)
                if i in doomed or i not in by_id:
                    continue
                doomed.append(i)
                queue += by_id[i]["children"] + by_id[i].get("embedded", [])
            removed = [self.row(by_id[i]) for i in doomed]
            before = m["volume"]
            m["features"] = [x for x in m["features"] if x["id"] not in doomed]
            m["volume"] -= sum(by_id[i].get("adds", 0.0) for i in doomed)
            m["modified"] = True
            return {
                "model": name,
                "deleted": removed,
                "still_present": [],
                "feature_count": len([x for x in m["features"] if x["visible"]]),
                "volume": {"before": before, "after": m["volume"], "change": m["volume"] - before},
            }
        if op == "feature.extrude":
            return self.extrude(q)
        answer = self.p2_op(op, q)
        if answer is not None:
            return answer
        raise Refused("E_VALIDATION", "unknown op '" + op + "'")

    def extrude(self, q):
        name, m = self.model(q["model"])
        sketch, profile = q["sketch"], q["sketch"]["profile"]
        for plane in [sketch["plane"], sketch["orient_ref"], *sketch.get("references", [])]:
            if plane.lower().startswith("surface:"):
                # A flat face: Creo.sketchPlane takes one of the part's planar surfaces.
                if not any(
                    g["ref"] == plane and g.get("type") == "plane" for g in m.get("geometry", [])
                ):
                    raise Refused("E_VALIDATION", plane + " is not flat")
                continue
            if plane.upper() not in [p.upper() for p in self.planes(m)]:
                raise Refused(
                    "E_NOT_FOUND",
                    f"no datum plane named {plane} in {name}; it has {self.planes(m)}",
                )
        kind = profile["type"]
        several = kind in ("rectangle", "polygon", "slot", "outline") or profile.get("holes")
        if several and not self.native:
            raise Refused("E_UNSUPPORTED", "multi-entity sketch without the native library")
        area = profile_area(profile)
        cut = q.get("material", "add") == "remove"
        expected = -area * q["depth"] if cut else area * q["depth"]
        before = m["volume"]
        after = max(0.0, before + expected)
        fid = m["next_id"]
        m["next_id"] += 27
        parents = [x["id"] for x in m["features"] if x["name"] in ("RIGHT", "TOP", "FRONT")]
        internal = {
            "id": fid + 1,
            "name": "no_name",
            "type": "FEATTYPE_DATUM_PLANE",
            "status": "FEAT_ACTIVE",
            "visible": False,
            "parents": [],
            "children": [],
            "surfaces": 1,
            "native_definition": {
                "complete": True,
                "kind": "datum_plane",
                "source": "controlled fixture",
                "reference": "FRONT",
            },
        }
        kind_name = "FEATTYPE_CUT" if cut else "FEATTYPE_PROTRUSION"
        if self.wrong_type:
            kind_name = "FEATTYPE_PROTRUSION" if cut else "FEATTYPE_CUT"
        feature = {
            "id": fid,
            "name": (q.get("name") or f"EXTRUDE_{fid}").upper(),
            "type": kind_name,
            "status": "FEAT_ACTIVE",
            "visible": True,
            "parents": parents,
            "children": [],
            "embedded": [fid + 1],
            "surfaces": 6,
            "adds": after - before,
        }
        m["features"] += [internal, feature]
        m["volume"], m["modified"] = after, True
        if not cut:
            self.add_solid_geometry(m, feature, profile, q["depth"])
        # As SketchPlan words them: a rectangle by its width and height about its centre, a
        # circle by its diameter.
        centre = profile.get("center", [0.0, 0.0])
        where = f"({_number(centre[0])}, {_number(centre[1])})"
        drafted = []
        for word, value in (("width", profile.get("width")), ("height", profile.get("height"))):
            if value:
                dim = self._dimension(m, feature, value)
                if kind == "rectangle":
                    drafted.append((dim, f"{word} of the rectangle centred at {where}"))
        self._dimension(m, feature, q["depth"], depth=True)
        if profile.get("diameter"):
            dim = self._dimension(m, feature, profile["diameter"], "diameter")
            drafted.append((dim, f"diameter of the circle at {where}"))
        change = after - before
        engine = "native" if several or (kind == "circle" and self.native) else "java"
        reply = {
            "model": name,
            "units": m["units"],
            "body": "all" if cut else "default:-5778:BODY_STATE_ACTIVE",
            "feature": {k: feature[k] for k in ("id", "name", "type", "status")},
            "sketch": {"engine": engine},
            "volume": {
                "before": before,
                "after": after,
                "change": change,
                "expected_change": expected,
                "matches_request": abs(change - expected) <= 1e-4 * max(1.0, abs(expected)),
            },
        }
        for d, words in drafted:
            d["measures"] = words
        if engine == "native":
            reply["sketch_dimensions"] = [
                {"name": d["name"], "value": d["value"], "measures": words, "by": "cli"}
                for d, words in drafted
            ]
            reply["held_together"] = []
            reply["dimension_plan"] = "kept"
        return reply

    def handle(self, op, q):
        self.events.append((op, copy.deepcopy(q)))
        if self.then_fail and self.then_fail[1] == op and self.then_fail[0] in self.succeeded:
            error, self.then_fail = self.then_fail[2], None
            return {"ok": False, "op": op, "error": dict(error), "elapsed_ms": 1}, True
        if self.fail and self.fail[0] == op:
            return {"ok": False, "op": op, "error": dict(self.fail[1]), "elapsed_ms": 1}, True
        if self.busy == op:
            return {
                "ok": False,
                "op": op,
                "error": {
                    "code": "E_BUSY",
                    "message": "withdrawn",
                    "retryable": True,
                    "started": False,
                },
            }, True
        if self.lie == op:
            name, m = self.model(q["model"])
            return {
                "ok": True,
                "op": op,
                "data": {
                    "model": name,
                    "directory": str(self.cwd),
                    "file": str(Path(self.cwd) / (name + ".99")),
                    "file_bytes": 1,
                    "on_disk": True,
                    "origin": m["origin"],
                    "modified": False,
                },
            }, True
        try:
            data = self.op(op, q)
        except (Refused, Refusal) as refused:
            return {"ok": False, "op": op, "error": refused.error}, True
        if self.fail_after and self.fail_after[0] == op:
            return {"ok": False, "op": op, "error": dict(self.fail_after[1])}, True
        if self.overrun == op:
            return {
                "ok": False,
                "op": op,
                "error": {
                    "code": "E_BUSY",
                    "message": "still running",
                    "retryable": False,
                    "started": True,
                },
            }, True
        if self.drop == op:
            return None, False
        self.succeeded.add(op)
        return {"ok": True, "op": op, "data": data, "elapsed_ms": 1}, True

    def ops(self):
        return [op for op, _ in self.events]


class Server:
    def __init__(self, world: World):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            def log_message(self, *_):
                pass

            def handle(self):
                try:
                    super().handle()
                except ConnectionError:
                    pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/health":
                    if world.health_broken:
                        self.reply(200, {"ok": True, "service": "something-else"})
                    else:
                        self.reply(
                            200,
                            {
                                "ok": True,
                                "service": "creo-cli",
                                "protocol": world.protocol,
                                "revision": "fixture-readback-integrity-1",
                                "capabilities": world.capabilities,
                                "checked": "process_only",
                                "service_instance_id": "fixture-generation-1",
                            },
                        )
                else:
                    self.send_error(404)

            def do_POST(self):
                if self.path != "/op":
                    self.send_error(404)
                    return
                if self.headers.get("X-Creo-Cli-Token") != world.token:
                    self.reply(
                        401,
                        {
                            "ok": False,
                            "error": {
                                "code": "E_AUTH",
                                "message": "missing or wrong X-Creo-Cli-Token",
                            },
                        },
                    )
                    return
                world.wait_headers.append(self.headers.get("X-Creo-Cli-Wait-Ms"))
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                op = body.pop("op")
                if world.block and world.block[0] == op:
                    world.block[1].wait(BLOCK_CEILING_SECONDS)
                answer, keep = world.handle(op, body)
                if not keep:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self.reply(200, answer)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.thread = threading.Thread(
            target=self.http.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


# A substitute's own geometry, independent of the CLI's exact formulas: loops sampled finely
# and measured as polygons, the way a mesh would be. They agree to about 1e-7.
FINE = 4096


def _polygon(p: dict) -> list:
    kind = p["type"]
    cx, cy = p.get("center", [0, 0])
    if kind == "ellipse":
        return [
            (cx + p["x_radius"] * math.cos(t), cy + p["y_radius"] * math.sin(t))
            for t in (2 * math.pi * k / FINE for k in range(FINE))
        ]
    if kind == "circle":
        return _arc_points(cx, cy, p["diameter"] / 2, 0.0, 2 * math.pi)
    if kind == "polygon":
        return [tuple(v) for v in p["points"]]
    if kind == "rectangle":
        w, h, r = p["width"] / 2, p["height"] / 2, p.get("corner_radius") or 0.0
        if not r:
            return [(cx - w, cy - h), (cx + w, cy - h), (cx + w, cy + h), (cx - w, cy + h)]
        corners = (
            (cx + w - r, cy - h + r, -90),
            (cx + w - r, cy + h - r, 0),
            (cx - w + r, cy + h - r, 90),
            (cx - w + r, cy - h + r, 180),
        )
        out = []
        for x, y, a in corners:
            out += _arc_points(x, y, r, math.radians(a), math.pi / 2)
        return out
    if kind == "slot":
        (ax, ay), (bx, by) = p["centers"]
        base = math.atan2(by - ay, bx - ax)
        r = p["width"] / 2
        return _arc_points(bx, by, r, base - math.pi / 2, math.pi) + _arc_points(
            ax, ay, r, base + math.pi / 2, math.pi
        )
    x, y = p["start"]
    out = []
    for seg in p["segments"]:
        tx, ty = seg["to"]
        if "sweep" in seg:
            sweep = math.radians(seg["sweep"])
            half = math.hypot(tx - x, ty - y) / 2
            r = half / abs(math.sin(sweep / 2))
            mx, my = (x + tx) / 2, (y + ty) / 2
            ux, uy = (tx - x) / (2 * half), (ty - y) / (2 * half)
            ccx = mx - uy * half / math.tan(sweep / 2)
            ccy = my + ux * half / math.tan(sweep / 2)
            out += _arc_points(ccx, ccy, r, math.atan2(y - ccy, x - ccx), sweep)
        elif "through" in seg:
            # The substitute draws Creo's spline as the CLI models it: what was measured on
            # Creo is in tests/test_capabilities.py, ProfileOptions.
            from creo_cli.sketch import spline_points

            out += [tuple(pt) for pt in spline_points([[x, y], *seg["through"], [tx, ty]])[:-1]]
        else:
            out.append((x, y))
        x, y = tx, ty
    if math.hypot(x - p["start"][0], y - p["start"][1]) > 1e-9:
        out.append((x, y))  # the last segment's end; a line closes back to the start
    return out


def _arc_points(cx, cy, r, t0, sweep):
    n = max(8, int(FINE * abs(sweep) / (2 * math.pi)))
    return [
        (cx + r * math.cos(t0 + sweep * k / n), cy + r * math.sin(t0 + sweep * k / n))
        for k in range(n)
    ]


def _shoelace(pts: list) -> tuple:
    a = gx = gy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        cross = x0 * y1 - x1 * y0
        a += cross
        gx += (x0 + x1) * cross
        gy += (y0 + y1) * cross
    return a / 2, gx / (3 * a), gy / (3 * a)


def _measure(loop: dict) -> tuple:
    """A loop's area and centroid: exact for a circle or an ellipse, whose areas Creo reports
    exactly; a dense polygon for loops with arcs; a polygon's own for straight edges."""
    kind = loop["type"]
    cx, cy = loop.get("center", [0, 0])
    if kind == "circle":
        return math.pi * (loop["diameter"] / 2) ** 2, cx, cy
    if kind == "ellipse":
        return math.pi * loop["x_radius"] * loop["y_radius"], cx, cy
    a, x, y = _shoelace(_polygon(loop))
    return abs(a), x, y


def _number(v: float) -> str:
    r = round(v, 6)
    return str(int(r)) if r == int(r) else f"{r:g}"


def profile_area(p: dict) -> float:
    return _measure(p)[0] - sum(_measure(h)[0] for h in p.get("holes") or [])


def profile_centroid(p: dict) -> tuple:
    total = gx = gy = 0.0
    for i, loop in enumerate([p, *(p.get("holes") or [])]):
        a, x, y = _measure(loop)
        w = a * (1 if i == 0 else -1)
        total, gx, gy = total + w, gx + w * x, gy + w * y
    return gx / total, gy / total
