"""Guarded CREOSON execution with observations, explicit verification, and receipts.

This is NOT a Creo transaction/geometry engine. A preview is a request plan with
observed preconditions, not predicted solids. Cooperative locks exclude only
this CLI; a person must provide exclusive ownership of a disposable session.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from . import safety
from .core import Error, atomic_write, canonical, digest, page, read_json, read_bytes, redact, validate_schema
from .creoson_catalog import BY_PATH, MODEL, Operation, validate
from . import creoson_state as store
from .creoson_transport import Client, cache_path, endpoint
from .creoson_schemas import envelope_schema

PROVENANCE = {"backend": "creoson", "simulation": False, "live_verified": False,
              "evidence_level": "published_interface_and_offline_tests"}
LIMITS = ["real_creo_execution_not_verified", "no_full_geometry_or_design_intent_verification",
          "no_transaction_or_automatic_rollback", "external_gui_and_other_clients_not_locked", "upstream_feature_listing_is_visible_features_only"]
LOCK = "creoson-shared-native-session"
ID_KEYS = {"id", "feat_id", "feat_number", "featureid", "owner_id", "relation_id", "surface_id", "edge_id"}


def normalize(value: Any, key: str = "") -> Any:
    """Boundary normalization only; do not pretend source-specific fields are universal."""
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            name = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
            if name in result:
                raise Error("E_PROTOCOL", "upstream keys collide after snake_case conversion")
            result[name] = normalize(v, name)
        return result
    if isinstance(value, list):
        return [str(v) if key == "path" and type(v) is int else normalize(v, key) for v in value]
    return str(value) if key in ID_KEYS and type(value) is int else value


def required(data: dict, key: str, kind: type) -> Any:
    if key not in data or type(data[key]) is not kind:
        raise Error("E_PROTOCOL", "required upstream field is missing or has the wrong type", {"field": key})
    return data[key]


def one(rows: list, name: str) -> dict:
    matches = [r for r in rows if isinstance(r, dict) and str(r.get("name", "")).casefold() == name.casefold()]
    if len(matches) != 1:
        raise Error("E_NOT_FOUND" if not matches else "E_CONFLICT", "target name must resolve to exactly one object", {"name": name, "matches": len(matches), "_untrusted": ["name"]})
    return matches[0]


def units_equal(actual: str, expected: str) -> bool:
    aliases = {"millimeter": "mm", "millimeters": "mm", "millimetre": "mm", "mm": "mm",
               "centimeter": "cm", "centimeters": "cm", "cm": "cm", "meter": "m", "meters": "m", "m": "m",
               "inch": "in", "inches": "in", "in": "in", "foot": "ft", "feet": "ft", "ft": "ft"}
    return aliases.get(actual.strip().lower()) == expected


def close_number(a: Any, b: Any) -> bool:
    return type(a) in (int, float) and type(b) in (int, float) and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def blocked_relation(lines: list, name: str) -> bool:
    # Conservative: reject any relation text mentioning the edited identifier.
    # Does not evaluate or claim complete parsing of Creo's relation language.
    return any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", str(line), re.I) for line in lines)


class Engine:
    def __init__(self, client: Client):
        self.client = client

    def call(self, command: str, function: str, data: dict | None = None, *, write=False) -> dict:
        return self.client.request(command, function, data, write=write)

    def loaded(self) -> list[str]:
        rows = required(self.call("file", "list"), "files", list)
        if len(rows) > 10000 or any(type(x) is not str for x in rows):
            raise Error("E_PROTOCOL", "invalid or oversized loaded model list")
        if len({r.casefold() for r in rows}) != len(rows):
            raise Error("E_PROTOCOL", "loaded model names are ambiguous after case normalization")
        return sorted(rows, key=str.casefold)

    def ensure_loaded(self, names: list[str]) -> None:
        available = {n.casefold() for n in self.loaded()}
        missing = [n for n in names if n.casefold() not in available]
        if missing:
            raise Error("E_NOT_FOUND", "explicit models must already be loaded", {"models": missing, "_untrusted": ["models"]})

    def units(self, name: str) -> dict:
        return {"length_units": required(self.call("file", "get_length_units", {"file": name}), "units", str),
                "mass_units": required(self.call("file", "get_mass_units", {"file": name}), "units", str)}

    def observation(self, name: str) -> dict:
        info = self.call("file", "get_fileinfo", {"file": name})
        if required(info, "file", str).casefold() != name.casefold():
            raise Error("E_PROTOCOL", "upstream returned another model's metadata")
        directory = store.contained(required(info, "dirname", str), directory=True)
        # Include exact disk version hashes: neither mtime nor filename alone is a content version.
        state = {"info": info, "disk": store.model_files(directory, name)}
        if name.lower().endswith(".drw"):
            state["models"] = required(self.call("drawing", "list_models", {"drawing": name}), "files", list)
            state["views"] = required(self.call("drawing", "list_view_details", {"drawing": name}), "views", list)
            state["sheets"] = required(self.call("drawing", "get_num_sheets", {"drawing": name}), "num_sheets", int)
            state["symbols"] = required(self.call("drawing", "list_symbols", {"drawing": name}), "symbols", list)
        else:
            state["units"] = self.units(name)
            state["parameters"] = required(self.call("parameter", "list", {"file": name, "encoded": False}), "paramlist", list)
            state["dimensions"] = required(self.call("dimension", "list_detail", {"file": name, "encoded": False, "select": False}), "dimlist", list)
            state["features"] = required(self.call("feature", "list", {"file": name, "paths": True, "inc_unnamed": True}), "featlist", list)
            state["relations"] = required(self.call("file", "relations_get", {"file": name}), "relations", list)
            state["postregen_relations"] = required(self.call("file", "postregen_relations_get", {"file": name}), "relations", list)
            state["views"] = required(self.call("view", "list", {"file": name}), "viewlist", list)
            if name.lower().endswith(".prt"):
                state["materials"] = required(self.call("file", "list_materials", {"file": name}), "materials", list)
                state["material"] = self.call("file", "get_cur_material", {"file": name}).get("material")
            else:
                state["components"] = self.call("bom", "get_paths", {"file": name, "paths": True, "skeletons": True, "get_transforms": True})
        # Canonicalize order for identity tables, while retaining relation and drawing sheet order.
        for key in ("parameters", "dimensions", "features", "views", "materials", "models"):
            if key in state:
                state[key] = sorted(state[key], key=lambda v: canonical(v))
        return state

    def wire(self, op: Operation, q: dict) -> dict:
        wire = op.wire(q)
        if op.path == "assembly transform":
            wire["path"] = [int(n) for n in q["path"]]
        if op.path == "drawing delete-symbol-instance":
            wire["symbol_id"] = int(q["symbol_id"])
        if op.path == "familytable replace" and "path" in wire:
            wire["path"] = [int(n) for n in q["path"]]
        if op.path == "geometry edges":
            # Ids cross the CLI boundary as strings (CLI-SPEC) and go upstream as the
            # integers geometry.get_edges publishes, like assembly transform's path.
            wire["surface_ids"] = [int(n) for n in q["surface_ids"]]
        if op.path == "parameter set":
            wire["no_create"] = not q["create"]
        if op.write:
            if op.path == "creo mkdir":
                # Contained like any other write target, but this is the one case where
                # the directory must not exist yet; the shared branch requires existence.
                wire["dirname"] = str(store.contained(wire["dirname"], exists=False))
            for field in ("dirname", "template"):
                if field in wire and op.path != "creo mkdir":
                    wire[field] = str(store.contained(wire[field], directory=(field == "dirname")))
            if "target_dir" in wire:
                wire["target_dir"] = str(store.contained(wire["target_dir"], exists=False))
            if op.path == "export image":
                wire["filename"] = str(Path(wire.pop("dirname")) / wire["filename"])
        return wire

    def read(self, op: Operation, q: dict, limit=100, offset=0) -> dict:
        op.validate(q)
        self.ensure_loaded([q[k] for k in op.target_keys]) if op.target_keys else None
        if op.verifier == "units":
            raw = self.units(q["file"])
        else:
            raw = self.call(op.command, op.function, self.wire(op, q))
        if op.verifier == "massprops":
            for key in ("mass", "volume", "density", "surface_area"):
                if type(raw.get(key)) not in (int, float):
                    raise Error("E_PROTOCOL", "mass properties response is missing a numeric field", {"field": key})
            raw["unit_context"] = self.units(q["file"]) | {"density_source": "upstream_model_properties", "material_assignment_verified": False}
        if op.list_key:
            items = required(raw, op.list_key, list)
            if op.path != "file relations":
                # Stable presentation for identical observations; never reorder relation lines.
                items = sorted(items, key=lambda item: (str(item.get("name", item.get("file", item.get("feat_id", "")))).casefold(), canonical(item)) if isinstance(item, dict) else (str(item).casefold(), canonical(item)))
            raw = {k: v for k, v in raw.items() if k != op.list_key} | page(normalize(items), limit, offset)
        else:
            raw = normalize(raw)
        output = {"operation": op.path, "result": raw, "verification": {"level": "observation", "checks": []},
                "provenance": PROVENANCE, "not_checked": LIMITS + (["inactive_and_unregenerated_components_omitted_by_upstream"] if op.path == "assembly tree" else []),
                "request_count": self.client.calls, "_untrusted": ["result"]}
        validate_schema(output, envelope_schema(op))
        return output

    def preconditions(self, op: Operation, q: dict, states: dict, loaded: set[str]) -> dict:
        wire = self.wire(op, q)
        details: dict = {"wire": wire, "artifacts": []}
        if op.version_required and not self.client.session.get("version_configured"):
            raise Error("E_CONFIG", "operation needs a session configured by creoson connect --creo-major")
        if op.path == "file roundtrip" and loaded != {q["file"].casefold()}:
            raise Error("E_CONFLICT", "save/reopen roundtrip requires exactly one isolated loaded part, with no other models in session")
        if op.path == "file open":
            if q["file"].casefold() in loaded:
                raise Error("E_CONFLICT", "model name is already loaded; cannot overwrite its in-memory identity")
            details["artifacts"] = store.model_files(Path(wire["dirname"]), q["file"])
            if not details["artifacts"]:
                raise Error("E_NOT_FOUND", "no matching native working-copy file was found")
            return details
        if op.path == "drawing create":
            if q["drawing"].casefold() in loaded or store.model_files(store.contained(self.call("creo", "pwd")["dirname"], directory=True), q["drawing"]):
                raise Error("E_CONFLICT", "drawing destination already exists on disk or in memory")
            details["artifacts"] = [store.artifact(Path(wire["template"]))]
        for key in op.target_keys:
            if key == "drawing" and op.path == "drawing create":
                continue
            if q[key].casefold() not in loaded:
                raise Error("E_NOT_FOUND", "write target is not loaded", {"model": q[key], "_untrusted": ["model"]})
        state = states.get(q.get("file", q.get("drawing", "")), {})
        if "expected_length_units" in q:
            for key in op.target_keys:
                actual = states[q[key]].get("units", {}).get("length_units", "")
                if not units_equal(actual, q["expected_length_units"]):
                    raise Error("E_CONFLICT", "model units do not match the explicit expected units; no implicit conversion", {"model": q[key], "actual": actual, "expected": q["expected_length_units"], "_untrusted": ["model", "actual"]})
        if op.path == "parameter set":
            rows = [v for v in state["parameters"] if v.get("name", "").casefold() == q["name"].casefold()]
            if (q["create"] and rows) or (not q["create"] and len(rows) != 1):
                raise Error("E_CONFLICT", "parameter existence does not match explicit create policy")
            if rows and (rows[0].get("type") != q["type"] or rows[0].get("encoded")):
                raise Error("E_CONFLICT", "parameter type or encoding is incompatible")
            if blocked_relation(state["relations"] + state["postregen_relations"], q["name"]):
                raise Error("E_CONFLICT", "parameter is mentioned in relations; direct edit refused")
        if op.path == "dimension set":
            dim = one(state["dimensions"], q["name"])
            if dim.get("dim_type") not in ("linear", "radial", "diameter") or dim.get("dwg_dim") is not False or dim.get("encoded"):
                raise Error("E_UNSUPPORTED", "only unencoded model length dimensions with explicit type are writable")
            if blocked_relation(state["relations"] + state["postregen_relations"], q["name"]):
                raise Error("E_CONFLICT", "dimension is mentioned in relations; direct edit refused")
        if op.path.startswith("feature "):
            row = one(state["features"], q["name"])
            if "feat_id" not in row:
                raise Error("E_PROTOCOL", "feature identity missing; cannot bind a name-only write")
            if op.verifier == "feature_name" and any(v.get("name", "").casefold() == q["new_name"].casefold() for v in state["features"]):
                raise Error("E_CONFLICT", "new feature name already exists")
        if op.path == "material assign" and q["material"] not in state["materials"]:
            raise Error("E_NOT_FOUND", "material must already be loaded on the part")
        if op.path == "view activate" and q["name"] not in state["views"]:
            raise Error("E_NOT_FOUND", "named orientation does not exist")
        if op.path == "view save" and q["name"] in state["views"]:
            raise Error("E_CONFLICT", "named view already exists")
        if op.path == "assembly assemble" and q["constraints"][0]["type"] == "csys":
            c = q["constraints"][0]
            for key, ref in (("file", "compref"), ("into_asm", "asmref")):
                datum = one(states[q[key]]["features"], c[ref])
                if datum.get("type") not in ("COORD_SYS", "COORDINATE SYSTEM") or datum.get("status") != "ACTIVE":
                    raise Error("E_CONFLICT", "assembly requires active coordinate-system references")
        if op.path == "drawing add-model" and q["model"] in state["models"]:
            raise Error("E_CONFLICT", "model is already part of the drawing")
        if op.verifier == "drawing_views":
            names = [v.get("name") for v in state["views"]]
            if q["view"] in names or q["sheet"] > state["sheets"]:
                raise Error("E_CONFLICT", "drawing view already exists or target sheet is missing")
            if "parent_view" in q:
                parent = one(state["views"], q["parent_view"])
                if parent.get("sheet") != q["sheet"]:
                    raise Error("E_CONFLICT", "projected view and parent must use the same sheet")
            elif q["model"] not in state["models"] or q["model_view"] not in states[q["model"]]["views"]:
                raise Error("E_NOT_FOUND", "drawing model or requested model orientation is missing")
        if op.verifier == "export":
            directory = store.contained(q["dirname"], directory=True)
            out = store.contained(str(directory / q["filename"]), exists=False)
            if out.exists():
                raise Error("E_CONFLICT", "export destination exists; overwrite is not supported")
            details["destination"] = str(out)
        if op.verifier == "backup":
            target = store.contained(q["target_dir"], exists=False)
            if target.exists() or not target.parent.is_dir():
                raise Error("E_CONFLICT", "backup needs a new directory under an existing workspace parent")
            details["destination"] = str(target)
        return details

    def observe_targets(self, op: Operation, q: dict, loaded: set[str]) -> dict:
        return {q[k]: self.observation(q[k]) for k in op.target_keys if q[k].casefold() in loaded}

    def verify(self, op: Operation, q: dict, result: dict, before: dict, prep: dict, run: dict) -> dict:
        mode, checks = op.verifier, []
        state = before.get(q.get("file", q.get("drawing", "")), {})
        def check(label, passed):
            checks.append({"check": label, "passed": bool(passed)})
            if not passed:
                raise Error("E_VERIFY_FAILED", "upstream accepted the write but a readback check failed", {"checks": checks, "rollback_performed": False})
        if mode == "acknowledgement":
            return {"level": "upstream_acknowledged_only", "checks": [], "not_checked": ["visual_result", "geometric_result"]}
        if mode in ("open", "drawing_create"):
            target = q["drawing"] if mode == "drawing_create" else q["file"]
            check("model_loaded", target.casefold() in {n.casefold() for n in self.loaded()})
            if mode == "drawing_create":
                check("model_linked", q["model"] in required(self.call("drawing", "list_models", {"drawing": target}), "files", list))
            else:
                check("open_errors_clear", required(self.call("file", "open_errors", {"file": target}), "errors", bool) is False)
        elif mode == "active":
            check("active_model", self.call("file", "get_active").get("file", "").casefold() == q["file"].casefold())
        elif mode in ("parameter", "dimension"):
            rows = required(self.call(op.command, "list" if mode == "parameter" else "list_detail", {"file": q["file"], "name": q["name"], "encoded": False, **({"select": False} if mode == "dimension" else {})}), "paramlist" if mode == "parameter" else "dimlist", list)
            value = one(rows, q["name"])
            check("value_readback", close_number(value.get("value"), q["value"]) if type(q["value"]) in (int, float) else type(value.get("value")) is type(q["value"]) and value["value"] == q["value"])
            if mode == "parameter":
                check("parameter_type", value.get("type") == q["type"])
        elif mode in ("suppress", "resume", "feature_name", "regenerate"):
            rows = required(self.call("feature", "list", {"file": q["file"], "paths": True, "inc_unnamed": True}), "featlist", list)
            if mode == "regenerate":
                check("no_failed_or_unregenerated_features_in_upstream_listing", not any(r.get("status") in ("FAILED", "UNREGENERATED") for r in rows))
            else:
                old = one(state["features"], q["name"])
                found = [r for r in rows if r.get("feat_id") == old["feat_id"]]
                check("same_feature_identity", len(found) == 1)
                wanted = q["new_name"] if mode == "feature_name" else "SUPPRESSED" if mode == "suppress" else "ACTIVE"
                check("requested_feature_state", found[0].get("name" if mode == "feature_name" else "status") == wanted)
                before_others = {str(r["feat_id"]): r for r in state["features"] if r.get("feat_id") != old["feat_id"]}
                after_others = {str(r["feat_id"]): r for r in rows if r.get("feat_id") != old["feat_id"]}
                check("other_observed_features_unchanged", before_others == after_others)
        elif mode == "material":
            check("material_assignment", self.call("file", "get_cur_material", {"file": q["file"]}).get("material") == q["material"])
        elif mode == "view":
            check("view_name_exists", q["name"] in required(self.call("view", "list", {"file": q["file"]}), "viewlist", list))
        elif mode == "assemble":
            feature_id = result.get("featureid")
            rows = required(self.call("feature", "list", {"file": q["into_asm"], "paths": True, "inc_unnamed": True}), "featlist", list)
            old_ids = {r.get("feat_id") for r in before[q["into_asm"]]["features"]}
            check("new_component_feature", type(feature_id) is int and feature_id not in old_ids and any(r.get("feat_id") == feature_id and r.get("status") == "ACTIVE" for r in rows))
            # Numeric solve accuracy and all degrees of freedom are not exposed here.
        elif mode.startswith("drawing_sheet_") or mode.startswith("drawing_model_") or mode.startswith("drawing_view_") or mode.startswith("drawing_symbol_"):
            drawing = q["drawing"]
            if mode == "drawing_sheet_current":
                check("current_sheet", required(self.call("drawing", "get_cur_sheet", {"drawing": drawing}), "sheet", int) == q["sheet"])
            elif mode == "drawing_sheet_scale":
                got = self.call("drawing", "get_sheet_scale", {"drawing": drawing, "sheet": q["sheet"]}).get("scale")
                check("sheet_scale", close_number(got, q["scale"]))
            elif mode == "drawing_sheet_format":
                check("sheet_format", str(self.call("drawing", "get_sheet_format", {"drawing": drawing, "sheet": q["sheet"]}).get("file", "")).casefold() == q["file"].casefold())
            elif mode == "drawing_sheet_count":
                check("sheet_count_decremented", self.call("drawing", "get_num_sheets", {"drawing": drawing}).get("num_sheets") == state["sheets"] - 1)
            elif mode == "drawing_model_current":
                check("current_model", str(self.call("drawing", "get_cur_model", {"drawing": drawing}).get("file", "")).casefold() == q["model"].casefold())
            elif mode == "drawing_model_absent":
                models = required(self.call("drawing", "list_models", {"drawing": drawing}), "files", list)
                check("model_removed", q["model"].casefold() not in {str(f).casefold() for f in models})
            else:
                names = lambda: {str(v).casefold() for v in required(self.call("drawing", "list_views", {"drawing": drawing}), "views", list)}
                if mode == "drawing_view_renamed":
                    current = names()
                    check("new_view_name_present", q["new_view"].casefold() in current)
                    check("old_view_name_gone", q["view"].casefold() not in current)
                elif mode == "drawing_view_absent":
                    check("view_removed", q["view"].casefold() not in names())
                elif mode == "drawing_view_moved":
                    loc = self.call("drawing", "get_view_loc", {"drawing": drawing, "view": q["view"]})
                    check("view_location", all(close_number(loc.get(axis), value) for axis, value in q["point"].items()))
                elif mode == "drawing_view_scaled":
                    # A per-view failure list is the upstream's way of half-succeeding.
                    check("no_failed_views", not (result.get("failed_views") or []))
                    check("view_scale", close_number(self.call("drawing", "get_view_scale", {"drawing": drawing, "view": q["view"]}).get("scale"), q["scale"]))
                elif mode == "drawing_symbol_loaded":
                    check("symbol_definition_loaded", required(self.call("drawing", "is_symbol_def_loaded", {"drawing": drawing, "symbol_file": q["symbol_file"]}), "loaded", bool))
                elif mode == "drawing_symbol_definition_absent":
                    check("symbol_definition_unloaded", required(self.call("drawing", "is_symbol_def_loaded", {"drawing": drawing, "symbol_file": q["symbol_file"]}), "loaded", bool) is False)
                elif mode == "drawing_symbol_placed":
                    placed = required(self.call("drawing", "list_symbols", {"drawing": drawing}), "symbols", list)
                    check("symbol_instance_added", len(placed) == len(state.get("symbols", [])) + 1)
                elif mode == "drawing_symbol_instance_absent":
                    placed = required(self.call("drawing", "list_symbols", {"drawing": drawing}), "symbols", list)
                    check("symbol_instance_removed", q["symbol_id"] not in {str(s.get("id")) for s in placed if isinstance(s, dict)})
        elif mode == "renamed":
            check("renamed_model_loaded", q["new_name"].casefold() in {n.casefold() for n in self.loaded()})
        elif mode == "erased":
            check("erased_from_memory", q["file"].casefold() not in {n.casefold() for n in self.loaded()})
        elif mode in ("length_units", "mass_units"):
            # Read the units back rather than trusting the setter: the convert flag
            # decides whether numbers were rescaled or merely relabelled, and getting
            # that wrong silently reinterprets every dimension in the model.
            got = self.units(q["file"])[mode]
            check(mode, units_equal(got, q["units"]) if mode == "length_units" else got.strip().lower() == q["units"].lower())
        elif mode == "unit_system":
            check("unit_system", str(required(self.call("file", "get_unit_system", {"file": q["file"]}), "name", str)).casefold() == q["name"].casefold())
        elif mode in ("material_present", "material_absent"):
            wanted = mode == "material_present"
            rows = {str(x).casefold() for x in required(self.call("file", "list_materials", {"file": q["file"]}), "materials", list)}
            check("material_" + ("loaded" if wanted else "removed"), (q["material"].casefold() in rows) is wanted)
        elif mode in ("relations", "postregen_relations"):
            function = "relations_get" if mode == "relations" else "postregen_relations_get"
            check("relations_readback", required(self.call("file", function, {"file": q["file"]}), "relations", list) == q["relations"])
        elif mode in ("parameter_copied", "parameter_absent", "parameter_designated"):
            target = q.get("to_file", q["file"])
            name = q.get("to_name", q["name"])
            rows = required(self.call("parameter", "list", {"file": target, "encoded": False}), "paramlist", list)
            present = {str(r.get("name", "")).casefold() for r in rows if isinstance(r, dict)}
            if mode == "parameter_copied":
                check("copy_present", name.casefold() in present)
            elif mode == "parameter_absent":
                check("parameter_removed", q["name"].casefold() not in present)
            else:
                check("designation", bool(one(rows, q["name"]).get("designate")) is q["designate"])
        elif mode in ("dimension_copied", "dimension_text"):
            target = q.get("to_file", q["file"])
            name = q.get("to_name", q["name"])
            rows = required(self.call("dimension", "list_detail", {"file": target, "encoded": False, "select": False}), "dimlist", list)
            if mode == "dimension_copied":
                check("copy_present", name.casefold() in {str(r.get("name", "")).casefold() for r in rows if isinstance(r, dict)})
            else:
                shown = one(rows, q["name"]).get("text")
                check("text_readback", q["text"] in (shown if isinstance(shown, list) else [shown]))
        elif mode == "feature_absent":
            rows = required(self.call("feature", "list", {"file": q["file"], "paths": True, "inc_unnamed": True}), "featlist", list)
            check("feature_removed", q["name"].casefold() not in {str(r.get("name", "")).casefold() for r in rows if isinstance(r, dict)})
        elif mode in ("feature_param", "feature_param_absent"):
            wanted = mode == "feature_param"
            found = required(self.call("feature", "param_exists", {"file": q["file"], "name": q["name"], "param": q["param"]}), "exists", bool)
            check("feature_parameter_" + ("set" if wanted else "removed"), found is wanted)
            if wanted:
                rows = required(self.call("feature", "list_params", {"file": q["file"], "name": q["name"], "param": q["param"], "encoded": False}), "paramlist", list)
                value = one(rows, q["param"]).get("value")
                check("feature_parameter_value", close_number(value, q["value"]) if type(q["value"]) in (int, float) else value == q["value"])
        elif mode in ("note_present", "note_copied", "note_absent"):
            target = q.get("to_file", q["file"])
            name = q.get("to_name", q["name"])
            found = required(self.call("note", "exists", {"file": target, "name": name}), "exists", bool)
            check("note_" + ("removed" if mode == "note_absent" else "present"), found is (mode != "note_absent"))
            if mode == "note_present":
                check("note_text", self.call("note", "get", {"file": q["file"], "name": q["name"]}).get("value") == q["value"])
        elif mode in ("layer_status", "layer_absent"):
            rows = required(self.call("layer", "list", {"file": q["file"]}), "layers", list)
            named = {str(r.get("name", "")).casefold(): r for r in rows if isinstance(r, dict)}
            if mode == "layer_absent":
                check("layer_removed", q["name"].casefold() not in named)
            else:
                check("layer_display", str(named.get(q["name"].casefold(), {}).get("status", "")).upper() == ("SHOWN" if q["show"] else "HIDDEN"))
        elif mode in ("familytable_present", "familytable_absent"):
            wanted = mode == "familytable_present"
            found = required(self.call("familytable", "exists", {"file": q["file"], "instance": q["instance"]}), "exists", bool)
            check("instance_" + ("added" if wanted else "removed"), found is wanted)
        elif mode == "familytable_table_absent":
            # Deleting the whole table is judged by the model no longer owning one,
            # not by the upstream having accepted the request.
            check("family_table_removed",
                  required(self.call("file", "has_instances", {"file": q["file"]}), "exists", bool) is False)
        elif mode == "familytable_created":
            created = result.get("name")
            check("instance_model_named", type(created) is str and bool(created))
            check("instance_model_loaded", str(created).casefold() in {n.casefold() for n in self.loaded()})
        elif mode == "familytable_cell":
            cell = self.call("familytable", "get_cell", {"file": q["file"], "instance": q["instance"], "colid": q["colid"]})
            value = cell.get("value")
            check("cell_value_readback", close_number(value, q["value"]) if type(q["value"]) in (int, float)
                  else type(value) is type(q["value"]) and value == q["value"])
            # A value that lands in a column of another type is a silent data error.
            check("cell_declared_datatype", str(cell.get("datatype", "")).upper() == q["expected_datatype"])
        elif mode == "familytable_replaced":
            check("replacement_instance_present",
                  required(self.call("familytable", "exists", {"file": q["cur_model"], "instance": q["new_inst"]}), "exists", bool))
        elif mode == "working_directory":
            # Read Creo's own answer back rather than trusting the echoed request:
            # a cd that silently did not move is exactly the failure worth catching.
            moved = required(self.call("creo", "pwd"), "dirname", str)
            check("creo_working_directory", Path(moved) == store.contained(q["dirname"], directory=True))
        elif mode in ("directory_present", "directory_absent"):
            wanted = mode == "directory_present"
            check("directory_" + ("created" if wanted else "removed"),
                  Path(prep["wire"]["dirname"]).is_dir() is wanted)
        elif mode == "config_option":
            values = required(self.call("creo", "get_config", {"name": q["name"]}), "values", list)
            check("config_value_readback", q["value"] in values)
        elif mode == "drawing_models":
            check("drawing_model_link", q["model"] in required(self.call("drawing", "list_models", {"drawing": q["drawing"]}), "files", list))
        elif mode == "drawing_sheets":
            check("sheet_count_incremented", self.call("drawing", "get_num_sheets", {"drawing": q["drawing"]}).get("num_sheets") == state["sheets"] + 1)
        elif mode == "drawing_views":
            rows = required(self.call("drawing", "list_view_details", {"drawing": q["drawing"]}), "views", list)
            row = one(rows, q["view"])
            check("view_on_requested_sheet", row.get("sheet") == q["sheet"])
            if "model" in q:
                check("view_references_model", row.get("view_model") == q["model"])
        elif mode == "roundtrip":
            after_disk = store.model_files(Path(state["info"]["dirname"]), q["file"])
            check("new_or_changed_saved_artifact", bool(after_disk) and after_disk != state["disk"])
            for stage, function, data in (
                ("close_window", "close_window", {"file": q["file"]}),
                ("erase_memory", "erase", {"file": q["file"], "erase_children": False}),
                ("reopen", "open", {"file": q["file"], "dirname": state["info"]["dirname"], "display": True, "activate": True, "new_window": False, "regen_force": False}),
            ):
                run["current_step"]["native_subphase"] = stage
                store.update(run)
                self.call("file", function, data, write=True)
                if stage == "erase_memory":
                    check("erased_from_memory", q["file"].casefold() not in {n.casefold() for n in self.loaded()})
            check("reopened", q["file"].casefold() in {n.casefold() for n in self.loaded()})
            check("no_open_errors", required(self.call("file", "open_errors", {"file": q["file"]}), "errors", bool) is False)
            after = self.observation(q["file"])
            sections = [key for key in state if key not in ("disk", "info")]
            for key in sections:
                check("persisted_" + key, state[key] == after[key])
            result.update(roundtrip_verified=True, artifacts=after_disk, compared_sections=sections)
        elif mode in ("export", "save", "backup"):
            if mode == "export":
                out = Path(prep["staged_destination"])
                check("export_exists", out.is_file())
                info = store.artifact(out)
                check("export_nonempty", info["size_bytes"] > 0)
                with out.open("rb") as handle:
                    header = handle.read(512)
                check("export_header", (b"ISO-10303-21" in header if op.path == "export step" else
                      header.startswith(b"%PDF-") if op.path == "export pdf" else
                      header.startswith(b"\xff\xd8\xff") if op.path == "export image" else
                      b"SECTION" in header or header.startswith(b"AutoCAD Binary DXF") if op.path == "export dxf" else
                      len(header) >= 73 and b"S" in header[72:73]))
                # Publication uses an atomic no-clobber local operation. CREOSON
                # never receives the public destination, so a race cannot cause
                # it to overwrite an existing user file.
                final = Path(prep["destination"])
                export_bytes = read_bytes(out, maximum=store.MAX_ARTIFACT)
                import hashlib
                if hashlib.sha256(export_bytes).hexdigest() != info["sha256"]:
                    raise Error("E_CONFLICT", "staged output changed after verification; publication refused")
                atomic_write(final, export_bytes, overwrite=False)
                result["artifact"] = store.artifact(final)
                result["filename"], result["dirname"] = final.name, str(final.parent)
                result["publish_policy"] = "atomic_no_clobber"
                out.unlink()
                try:
                    out.parent.rmdir()
                except OSError:
                    pass
            elif mode == "save":
                after = store.model_files(Path(state["info"]["dirname"]), q["file"])
                check("saved_files_present", bool(after))
                check("new_or_changed_disk_artifact", after != state["disk"])
                result["artifacts"] = after
            else:
                dest = Path(prep["destination"])
                check("backup_directory_created", dest.is_dir())
                output = store.model_files(dest, q["file"])
                check("backup_model_present", bool(output))
                result["artifacts"] = output
        else:
            raise Error("E_INTEGRITY", "missing verification implementation")
        return {"level": "selected_postconditions_verified", "checks": checks,
                "not_checked": ["full_geometry", "engineering_correctness", "constraint_degrees_of_freedom", "hidden_features_outside_upstream_listing"] + ([] if mode == "roundtrip" else ["reopen_persistence"])}

    def step(self, step: dict, run: dict, expected: dict) -> dict:
        op, q = BY_PATH[step["command"]], step["request"]
        if not op.write:
            return self.read(op, q)
        loaded = {n.casefold() for n in self.loaded()}
        states = self.observe_targets(op, q, loaded)
        for name, value in states.items():
            if name in expected and digest(value) != digest(expected[name]):
                raise Error("E_CONFLICT", "model changed after token validation and before execution", {"model": name, "_untrusted": ["model"]})
        prep = self.preconditions(op, q, states, loaded)
        backups = []
        if op.verifier in ("save", "roundtrip"):
            # Preserve the on-disk versions, never claim this backs up unsaved RAM.
            dest = store.workspace() / ".creo-cli-backups"
            store.no_links(dest)
            dest.mkdir(exist_ok=True, mode=0o700)
            dest = dest / (run["operation_id"] + "-" + step["id"])
            dest.mkdir(mode=0o700)
            for f in states[q["file"]]["disk"]:
                src = Path(f["path"])
                raw = read_bytes(src, maximum=store.MAX_ARTIFACT)
                import hashlib
                if hashlib.sha256(raw).hexdigest() != f["sha256"]:
                    raise Error("E_CONFLICT", "disk model changed before backup")
                out = dest / src.name
                atomic_write(out, raw, overwrite=False)
                backups.append(store.artifact(out))
        if op.verifier == "backup":
            # PTC backup APIs expect an existing target directory. Reserve a new
            # empty directory locally after confirmation, never during preview.
            Path(prep["destination"]).mkdir(mode=0o700)
        if op.verifier == "export":
            staging_root = store.contained(str(store.workspace() / ".creo-cli-staging"), exists=False)
            staging_root.mkdir(exist_ok=True, mode=0o700)
            staging = staging_root / (run["operation_id"] + "-" + step["id"])
            staging.mkdir(mode=0o700)
            prep["staged_destination"] = str(staging / q["filename"])
            if op.path == "export image":
                prep["wire"]["filename"] = prep["staged_destination"]
            else:
                prep["wire"]["dirname"] = str(staging)
        intent = {"id": step["id"], "command": op.path, "phase": "write_intent",
                  "request_sha256": digest(q), "disk_backups": backups,
                  **({"staged_destination": prep["staged_destination"], "publish_destination": prep["destination"]} if op.verifier == "export" else {})}
        run["current_step"] = intent
        store.update(run)
        result = self.call(op.command, op.function, prep["wire"], write=True)
        run["current_step"]["phase"] = "accepted_verifying"
        store.update(run)
        verification = self.verify(op, q, result, states, prep, run)
        output = {"operation": op.path, "result": normalize(result), "verification": verification,
                "provenance": PROVENANCE, "not_checked": LIMITS, "disk_backups": backups,
                "request_count": self.client.calls, "_untrusted": ["result", "disk_backups"]}
        validate_schema(output, envelope_schema(op)["properties"]["last_result"])
        return output


def manifest(value: Any) -> list[dict]:
    if not isinstance(value, dict) or set(value) != {"workflow_schema", "steps"} or value["workflow_schema"] != "1.0":
        raise Error("E_VALIDATION", "workflow needs only workflow_schema=1.0 and steps")
    if not isinstance(value["steps"], list) or not 1 <= len(value["steps"]) <= 32:
        raise Error("E_VALIDATION", "workflow must contain 1..32 steps")
    seen, out = set(), []
    for s in value["steps"]:
        if not isinstance(s, dict) or set(s) != {"id", "command", "request"}:
            raise Error("E_VALIDATION", "each step needs exactly id, command and request")
        if type(s["id"]) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", s["id"]) or s["id"] in seen:
            raise Error("E_VALIDATION", "step IDs must be unique lowercase ASCII identifiers")
        seen.add(s["id"])
        if type(s["command"]) is not str or s["command"] not in BY_PATH:
            raise Error("E_UNSUPPORTED", "workflow command is outside the native operation allowlist")
        q = BY_PATH[s["command"]].validate(s["request"])
        out.append({"id": s["id"], "command": s["command"], "request": q})
    return out


def preview(engine: Engine, steps: list[dict]) -> tuple[dict, dict]:
    root = store.workspace()
    cwd = store.contained(required(engine.call("creo", "pwd"), "dirname", str), directory=True)
    loaded = {n.casefold() for n in engine.loaded()}
    targets = sorted({s["request"][k] for s in steps for k in BY_PATH[s["command"]].target_keys})
    if len(targets) > 8:
        raise Error("E_VALIDATION", "a native workflow is limited to eight explicitly named model targets")
    observations = {n: engine.observation(n) if n.casefold() in loaded else {"absent": True} for n in targets}
    available, touched, plan, external = set(loaded), set(), [], []
    destinations = set()
    for s in steps:
        op, q = BY_PATH[s["command"]], s["request"]
        names = {q[k].casefold() for k in op.target_keys}
        creates = q["file"] if op.path == "file open" else q["drawing"] if op.path == "drawing create" else None
        needs = names - ({creates.casefold()} if creates else set())
        if needs - available:
            raise Error("E_NOT_FOUND", "workflow references a model before it is loaded/created", {"step": s["id"], "models": sorted(needs - available)})
        deferred = bool(names & touched)
        wire = engine.wire(op, q)
        if op.write and not deferred:
            prep = engine.preconditions(op, q, observations, loaded)
            external.extend(prep["artifacts"])
        # Path and output policy remains checkable even for future-created targets.
        if op.verifier == "export":
            out = str(store.contained(str(store.contained(q["dirname"], directory=True) / q["filename"]), exists=False))
            if Path(out).exists() or out.casefold() in destinations:
                raise Error("E_CONFLICT", "duplicate or existing export destination")
            destinations.add(out.casefold())
        if op.path == "file open" and deferred:
            raise Error("E_CONFLICT", "a workflow cannot open a model name twice")
        if op.path == "drawing create":
            template = store.contained(q["template"], directory=False)
            external.append(store.artifact(template))
        if creates:
            if creates.casefold() in available:
                raise Error("E_CONFLICT", "new model name is already available")
            available.add(creates.casefold())
        plan.append({"id": s["id"], "command": op.path, "request": q, "upstream": {"command": op.command, "function": op.function, "data": wire},
                     "effect": op.effect, "state_check": "deferred_until_execution" if deferred else "observed",
                     "verification_policy": op.verifier, "interaction_risks": list(op.interaction_risks)})
        if op.write:
            touched |= names
    binding = {"workspace": str(root), "creo_working_directory": str(cwd), "identity": engine.client.identity,
               "observations": observations, "input_artifacts": external, "destinations": sorted(destinations)}
    plan_doc = {"steps": redact(plan), "state_sha256": digest(binding), "target_models": targets,
                "preview_kind": "request_plan_not_predicted_geometry", "atomic": False, "rollback_available": False,
                "exclusive_disposable_session_required": True, "export_policy": "private_staging_then_atomic_no_clobber_publish", "observed_model_count": sum(n.casefold() in loaded for n in targets)}
    return plan_doc, binding


def scope(command: str, steps: list, binding: dict) -> dict:
    return safety.scope(command, "creoson", endpoint(), {"steps": steps, "connection": binding.get("identity"), "workspace": binding.get("workspace")}, digest(binding))


def execute_plan(command: str, steps: list, opts: dict) -> dict:
    # Preview uses reads only, but refuses unresolved native jobs and native policy
    # violations before issuing an execution token.
    safety.require_write(native=True)
    with safety.lock(LOCK):
        store.require_clear()
        with Client(opts.get("timeout", 30)) as client:
            engine = Engine(client)
            plan, binding = preview(engine, steps)
            bound = scope(command, steps, binding)
            if opts.get("dry_run"):
                token, expires = safety.issue(bound)
                return {"preview": plan, "confirm_token": token, "expires_at": expires,
                        "provenance": PROVENANCE, "not_checked": LIMITS, "_untrusted": ["preview"]}
            safety.consume(opts.get("confirm"), bound)
            run = store.begin(client.identity, command, steps)
            try:
                expected = dict(binding["observations"])
                for s in steps:
                    result = engine.step(s, run, expected)
                    if BY_PATH[s["command"]].write:
                        for key in BY_PATH[s["command"]].target_keys:
                            expected.pop(s["request"][key], None)
                    record = {"id": s["id"], "command": s["command"], "ok": True,
                              "verification": result["verification"], "result_sha256": digest(result["result"]),
                              "result_artifact": store.save_result(run["operation_id"], s["id"], result)}
                    # Receipts retain selected results (bounded by transport and receipt caps).
                    run["steps"].append(record)
                    run["completed_steps"] += 1
                    run.pop("current_step", None)
                    store.update(run)
                    last_result = result
                run["status"] = "completed"
                run["request_count"] = client.calls
                run["verification_scope"] = "selected_postconditions_only"
                store.update(run)
            except BaseException as exc:
                if isinstance(exc, Error) and run.get("current_step") and exc.code in ("E_TIMEOUT", "E_NETWORK", "E_PROTOCOL", "E_SERVER", "E_RATE_LIMITED", "E_IO"):
                    exc = Error("E_OUTCOME_UNKNOWN", "write was attempted but its post-state could not be established; inspect Creo before another write", {"cause_code": exc.code, "state_unknown": True})
                run["status"] = ("unknown" if isinstance(exc, KeyboardInterrupt) or isinstance(exc, Error) and exc.code == "E_OUTCOME_UNKNOWN"
                                 else "verification_failed" if isinstance(exc, Error) and exc.code == "E_VERIFY_FAILED"
                                 else "partial" if run["completed_steps"] or run.get("current_step") else "failed_before_write")
                run["error_code"] = exc.code if isinstance(exc, Error) else "E_INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "E_UNKNOWN"
                try:
                    store.update(run)
                except Error:
                    pass  # persisted running intent is deliberately a blocking state
                if isinstance(exc, Error):
                    exc.details |= {"operation_id": run["operation_id"], "completed_steps": run["completed_steps"], "receipt_status": run["status"],
                                    "rollback_performed": False, "automatic_retry": False}
                    raise exc
                raise
            return {"operation_id": run["operation_id"], "status": run["status"], "completed_steps": run["completed_steps"],
                    "steps": run["steps"], "last_result": last_result, "request_count": client.calls,
                    "provenance": PROVENANCE, "not_checked": LIMITS, "_untrusted": ["last_result"]}


def dispatch(path: str, opts: dict) -> dict:
    if path in BY_PATH:
        op = BY_PATH[path]
        q = op.validate(read_json(opts["request"]) if opts.get("request") else {})
        if op.write:
            return execute_plan(path, [{"id": "operation", "command": path, "request": q}], opts)
        with Client(opts.get("timeout", 30)) as client:
            return Engine(client).read(op, q, opts.get("limit", 100), opts.get("offset", 0))
    if path == "workflow validate":
        steps = manifest(read_json(opts["input"]))
        return {"valid": True, "kind": "creoson_workflow", "summary": {"steps": len(steps), "writes": sum(BY_PATH[s["command"]].write for s in steps), "live_verified": False}}
    if path == "workflow run":
        return execute_plan(path, manifest(read_json(opts["input"])), opts)
    if path == "workflow history":
        return page(store.all_runs(), opts["limit"], opts["offset"])
    if path == "workflow status":
        return {"receipt": store.get_run(opts["operation-id"] if "operation-id" in opts else opts["operation_id"]), "provenance": PROVENANCE, "not_checked": ["current_creo_state"], "_untrusted": ["receipt"]}
    if path == "workflow result":
        run = store.get_run(opts["operation_id"])
        matches = [s for s in run["steps"] if s["id"] == opts["step_id"]]
        if not matches:
            raise Error("E_NOT_FOUND", "no completed step result with this identity")
        return {"operation_id": run["operation_id"], "step_id": opts["step_id"],
                "result": store.load_result(run["operation_id"], opts["step_id"], matches[0]["result_artifact"]),
                "provenance": PROVENANCE, "_untrusted": ["result"]}
    if path == "workflow reconcile":
        safety.require_write(native=True)
        # This changes local bookkeeping only. A note is a human assertion,
        # never evidence that the server stopped or that geometry is correct.
        if opts.get("acknowledge") != "human-inspected-server-idle":
            raise Error("E_FORBIDDEN", "reconciliation needs an explicit human-inspected-server-idle acknowledgement")
        note = opts.get("note", "")
        if not 10 <= len(note) <= 1000:
            raise Error("E_VALIDATION", "reconciliation note must contain 10..1000 characters")
        with safety.lock(LOCK):
            run = store.get_run(opts["operation_id"])
            if run["status"] not in ("running", "unknown", "partial", "verification_failed"):
                raise Error("E_CONFLICT", "receipt is not awaiting reconciliation")
            bound = safety.scope(path, "creoson", run["operation_id"], {"note": note, "acknowledge": opts["acknowledge"]}, digest(run))
            if opts.get("dry_run"):
                token, expires = safety.issue(bound)
                return {"preview": {"receipt": run, "note": note, "action": "acknowledge_only_no_retry_or_rollback"}, "confirm_token": token, "expires_at": expires, "provenance": PROVENANCE, "not_checked": LIMITS}
            safety.consume(opts.get("confirm"), bound)
            run["execution_status_before_acknowledgement"] = run["status"]
            run["status"] = "human_acknowledged"
            run["human_note"] = note
            store.update(run)
            return {"receipt": redact(run), "provenance": PROVENANCE, "not_checked": ["actual_server_idle", "actual_geometry_state"], "_untrusted": ["receipt"]}
    if path == "creoson status":
        with Client(opts.get("timeout", 30), connected=False) as client:
            running = required(client.request("connection", "is_creo_running"), "running", bool)
            return {"running": running, "session_cached": cache_path().is_file(), "provenance": PROVENANCE}
    if path == "creoson connect":
        # Establishes automation session metadata, not a CAD content mutation.
        safety.require_write()
        major = opts["creo_major"]
        if not 2 <= major <= 99:
            raise Error("E_VALIDATION", "Creo major version must be an integer in 2..99; this is a user declaration, not detection")
        with safety.lock(LOCK):
            store.require_clear()
            old = store.artifact(cache_path()) if cache_path().exists() else None
            bound = safety.scope(path, "creoson", endpoint(), {"creo_major": major}, digest(old))
            if opts.get("dry_run"):
                token, expires = safety.issue(bound)
                return {"preview": {"endpoint": endpoint(), "creo_major_declared": major, "starts_creo": False, "replaces_cached_session": bool(old)}, "confirm_token": token, "expires_at": expires, "provenance": PROVENANCE, "not_checked": ["server_reachability", "actual_creo_version"]}
            safety.consume(opts.get("confirm"), bound)
            with Client(opts.get("timeout", 30), connected=False) as client:
                run = store.begin(client.identity, path, [{"creo_major": major}])
                try:
                    result = client.connect(major)
                except BaseException:
                    run["status"] = "unknown"
                    store.update(run)
                    raise
                run["status"] = "completed"
                store.update(run)
                return result | {"operation_id": run["operation_id"], "provenance": PROVENANCE}
    raise Error("E_UNSUPPORTED", "unknown CREOSON orchestration command")
