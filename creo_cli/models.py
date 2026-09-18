"""Portable observations and restricted ChangeSets, not a substitute CAD kernel."""
from __future__ import annotations
import copy
import hashlib
import os
from pathlib import Path
from .core import Error, require, number, canonical, decode, digest, read_bytes, atomic_write

UNTRUSTED = ["model", "parameters", "dimensions", "features", "relations"]

def value_valid(kind, value):
    return {"string": lambda: isinstance(value, str) and len(value) <= 4096,
            "note": lambda: isinstance(value, str) and len(value) <= 4096,
            "double": lambda: number(value),
            "integer": lambda: type(value) is int and -(2**31) <= value < 2**31,
            "boolean": lambda: type(value) is bool}.get(kind, lambda: False)()

def validate(s):
    require(isinstance(s, dict) and s.get("snapshot_schema") == "1.0", "unsupported snapshot shape/version")
    require(isinstance(s.get("model"), dict), "model object is required")
    for k in ("id", "name", "kind", "units", "revision"):
        require(isinstance(s["model"].get(k), str) and bool(s["model"][k]), "model identifiers and units must be nonempty strings")
    require(s["model"]["kind"] in ("part", "assembly", "drawing"), "unsupported model kind")
    require(type(s["model"].get("dirty")) is bool, "model.dirty must be boolean")
    for section, key in (("parameters", "name"), ("dimensions", "id"), ("features", "id")):
        rows = s.get(section)
        require(isinstance(rows, list), section + " must be an array")
        seen = set()
        for row in rows:
            require(isinstance(row, dict) and isinstance(row.get(key), str) and bool(row[key]), "row identifier must be a string")
            require(row[key] not in seen, "duplicate row identity")
            seen.add(row[key])
            if section == "parameters":
                require(value_valid(row.get("kind"), row.get("value")), "invalid parameter type/value")
            if section == "dimensions":
                require(number(row.get("value")), "dimension must be finite")
                require(row.get("kind") in ("linear", "radial", "diameter", "angular", "unknown"), "dimension kind required")
                require(isinstance(row.get("symbol"), str), "dimension symbol required")
            if section in ("parameters", "dimensions"):
                require(type(row.get("relation_driven")) is bool, "relation_driven must be boolean")
            else:
                require(all(isinstance(row.get(k), str) for k in ("name", "type", "status")), "invalid feature fields")
    require(isinstance(s.get("relations"), list) and all(isinstance(x, str) for x in s["relations"]), "relations must be a string array")
    require(isinstance(s.get("provenance"), dict) and type(s["provenance"].get("simulation")) is bool, "explicit provenance is required")
    require(isinstance(s.get("not_checked"), list), "not_checked is required")
    return s

def revision(s):
    return digest({k: s[k] for k in ("model", "parameters", "dimensions", "features", "relations", "provenance")})

def validate_change(c):
    require(isinstance(c, dict), "changeset must be an object")
    require(set(c) <= {"schema_version", "model", "base_revision", "operations"}, "unknown changeset field")
    require(c.get("schema_version") == "1.0" and isinstance(c.get("model"), str) and bool(c["model"]), "changeset schema/model required")
    require("base_revision" not in c or isinstance(c["base_revision"], str), "base_revision must be a string")
    ops = c.get("operations")
    require(isinstance(ops, list) and 0 < len(ops) <= 256, "operations must contain 1..256 entries")
    seen = set()
    for op in ops:
        require(isinstance(op, dict) and op.get("op") in ("parameter.set", "dimension.set"), "unsupported operation")
        dim = op["op"] == "dimension.set"
        key = "id" if dim else "name"
        require(set(op) <= {"op", key, "value", "expected"} | ({"units"} if dim else set()), "unknown operation field")
        require(isinstance(op.get(key), str) and bool(op[key]) and "value" in op, "target and value required")
        target = (op["op"], op[key])
        require(target not in seen, "duplicate operation target")
        seen.add(target)
        if dim:
            require(number(op["value"]) and op["value"] > 0, "dimension value must be positive and finite")
            require(isinstance(op.get("units"), str) and bool(op["units"]), "dimension unit-system name must be explicit")
        else:
            require(any(value_valid(k, op["value"]) for k in ("string", "double", "integer", "boolean")), "unsupported parameter value")
    return c

def plan(s, c):
    validate(s)
    validate_change(c)
    if s["model"]["id"] != c["model"] or (c.get("base_revision") is not None and c["base_revision"] != s["model"]["revision"]):
        raise Error("E_CONFLICT", "changeset model or base_revision does not match current state")
    result = copy.deepcopy(s)
    lookup = {"parameter.set": {p["name"]: p for p in result["parameters"]},
              "dimension.set": {p["id"]: p for p in result["dimensions"]}}
    changes = []
    for op in c["operations"]:
        target = op["id"] if op["op"] == "dimension.set" else op["name"]
        row = lookup[op["op"]].get(target)
        if row is None:
            raise Error("E_NOT_FOUND", "changeset target does not exist", {"target": target, "_untrusted": ["target"]})
        if row["relation_driven"] or row.get("kind") == "note":
            raise Error("E_FORBIDDEN", "relation-driven values and note parameters are read-only")
        if "expected" in op:
            equal = op["expected"] == row["value"] and (type(op["expected"]) is type(row["value"]) or number(op["expected"]) and number(row["value"]))
            if not equal:
                raise Error("E_CONFLICT", "expected value has changed")
        if op["op"] == "dimension.set":
            if row["kind"] != "linear":
                raise Error("E_UNSUPPORTED", "this development version edits linear dimensions only")
            require(op["units"] == s["model"]["units"], "unit-system mismatch; no implicit unit conversion")
        else:
            require(value_valid(row["kind"], op["value"]), "value does not match existing parameter type")
        changes.append({"operation": op["op"], "target": target, "before": row["value"], "after": op["value"], "_untrusted": ["target", "before", "after"]})
        row["value"] = op["value"]
    return result, changes

def sample(name="bracket"):
    return {"snapshot_schema": "1.0", "model": {"id": name+".prt", "name": name, "kind": "part", "units": "mm", "revision": "0", "dirty": False},
            "parameters": [{"name": "DESCRIPTION", "kind": "string", "value": "Simulation fixture, not a Creo model", "relation_driven": False}],
            "dimensions": [{"id": "1", "symbol": "width", "kind": "linear", "value": 80.0, "relation_driven": False},
                           {"id": "2", "symbol": "hole_pitch", "kind": "linear", "value": 40.0, "relation_driven": False}],
            "features": [{"id": "1", "name": "SIMULATED_BASE", "type": "simulation", "status": "not_evaluated"}],
            "relations": [], "provenance": {"backend": "mock", "simulation": True},
            "not_checked": ["all_cad_geometry", "regeneration", "interference", "manufacturability", "native_persistence"], "_untrusted": UNTRUSTED}

def diff(a, b):
    validate(a)
    validate(b)
    out = []
    for section, key in (("parameters", "name"), ("dimensions", "id"), ("features", "id")):
        x, y = ({r[key]: r for r in s[section]} for s in (a, b))
        for ident in sorted(set(x)|set(y)):
            if x.get(ident) != y.get(ident):
                out.append({"section": section, "id": ident, "before": x.get(ident), "after": y.get(ident), "_untrusted": ["id", "before", "after"]})
    for section in ("model", "relations"):
        if a[section] != b[section]:
            out.append({"section": section, "id": section, "before": a[section], "after": b[section], "_untrusted": ["before", "after"]})
    return out

class Mock:
    name = "mock"
    def __init__(self, model):
        if not model:
            raise Error("E_USAGE", "mock backend requires an explicit --model .creo.json file")
        self.path = Path(model).expanduser().absolute()
        require(self.path.name.endswith(".creo.json"), "mock accepts only .creo.json files, never native CAD files")
        if self.path.is_symlink():
            raise Error("E_FORBIDDEN", "mock target must not be a symbolic link")
        self.target = os.path.normcase(str(self.path.resolve()))
    def observe(self):
        raw = read_bytes(self.path)
        s = validate(decode(raw))
        require(s["provenance"].get("backend") == "mock" and s["provenance"]["simulation"], "mock input must declare simulation provenance")
        require(len(s["model"]["revision"]) <= 18 and s["model"]["revision"].isascii() and s["model"]["revision"].isdigit(), "mock revision must be a decimal string")
        return s, hashlib.sha256(raw).hexdigest()
    def apply(self, c, expected):
        s, rev = self.observe()
        if rev != expected:
            raise Error("E_CONFLICT", "file changed before write")
        result, changes = plan(s, c)
        require(int(s["model"]["revision"]) < 10**18-1, "mock revision space exhausted")
        result["model"]["revision"] = str(int(s["model"]["revision"])+1)
        result["model"]["dirty"] = False
        original = read_bytes(self.path)
        if hashlib.sha256(original).hexdigest() != expected:
            raise Error("E_CONFLICT", "file changed during preparation")
        backup = self.path.with_name(self.path.name+"."+expected+".bak")
        if backup.is_symlink():
            raise Error("E_FORBIDDEN", "backup must not be a symbolic link")
        if backup.exists():
            if read_bytes(backup) != original:
                raise Error("E_INTEGRITY", "existing content-addressed backup is corrupt")
        else:
            atomic_write(backup, original, overwrite=False)
        if self.observe()[1] != expected:
            raise Error("E_CONFLICT", "file changed during backup")
        atomic_write(self.path, canonical(result)+b"\n")
        if self.observe()[0] != result:
            raise Error("E_INTEGRITY", "read-back mismatch; preserve backup and inspect state", {"state_unknown": True})
        return {"model": result["model"], "changes": changes, "backup": str(backup), "persisted": True,
                "verification": {"requested_values": True, "read_back": True, "regenerated": False, "geometry_verified": False},
                "provenance": result["provenance"], "not_checked": result["not_checked"], "_untrusted": ["model", "changes", "backup"]}
