"""Optional PTC VB API boundary. Interface-shaped tests are NOT live SDK validation.

No implicit model retrieval, no Save/End, no raw scripting endpoint. Only loaded
parts may be changed, and the worker itself checks tokens and human opt-in.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import platform
import struct
import subprocess
import sys
import time
from pathlib import Path
from . import models, safety
from .core import Error, CODES, MAX_INPUT, canonical, decode, digest

ACTIONS = {"session.status", "model.list", "model.info", "model.snapshot", "model.parameters",
           "model.dimensions", "model.features", "model.relations", "change.apply"}

def probe():
    windows = os.name == "nt"
    architecture = struct.calcsize("P") == 8 and platform.machine().lower() in ("amd64", "x86_64")
    binding = windows and importlib.util.find_spec("win32com") is not None
    executable = bool(os.environ.get("PRO_COMM_MSG_EXE") and Path(os.environ["PRO_COMM_MSG_EXE"]).is_file())
    registered = False
    if windows:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "pfcls.CCpfcAsyncConnection"):
                registered = True
        except OSError:
            pass
    return {"platform_supported": windows, "architecture_supported": architecture, "python_binding_present": binding,
            "communication_executable_present": executable, "com_registered": registered,
            "configured": bool(windows and architecture and binding and executable and registered),
            "live_verified": False, "license_status": "unknown"}

def sequence(seq):
    if seq is None:
        return []
    count = int(seq.Count)
    if not 0 <= count <= 50000:
        raise Error("E_VALIDATION", "native collection exceeds the 50000-item ceiling")
    return [seq.Item(i) for i in range(count)]

class Session:
    """Injectable adapter. Unit tests pass fake COM objects, never a production session."""
    def __init__(self, session, constants, cast=lambda obj, name: obj, session_identity="test-only"):
        self.session, self.c, self.cast = session, constants, cast
        self.session_id = hashlib.sha256(session_identity.encode()).hexdigest()
    def enum(self, name):
        try:
            return getattr(self.c, name)
        except AttributeError as exc:
            raise Error("E_UNSUPPORTED", "installed type library lacks a required enum", {"enum": name}) from exc
    def loaded(self):
        return sequence(self.session.ListModels())
    def model(self, ident):
        if not isinstance(ident, str) or not ident:
            raise Error("E_USAGE", "explicit loaded model filename required")
        found = [m for m in self.loaded() if str(m.FileName).casefold() == ident.casefold()]
        if len(found) != 1:
            raise Error("E_NOT_FOUND" if not found else "E_CONFLICT", "loaded model absent or ambiguous")
        return found[0]
    def kind(self, model):
        for e, value in (("EpfcMDL_PART", "part"), ("EpfcMDL_ASSEMBLY", "assembly"), ("EpfcMDL_DRAWING", "drawing")):
            if model.Type == self.enum(e):
                return value
        raise Error("E_UNSUPPORTED", "model kind not supported")
    def provenance(self):
        return {"backend": "native", "simulation": False, "adapter_live_verified": False, "session_id": self.session_id}
    def info(self, model):
        kind = self.kind(model)
        units = str(self.cast(model, "IpfcSolid").GetPrincipalUnits().Name) if kind != "drawing" else "unqueried_drawing_units"
        return {"id": str(model.FileName), "name": str(model.FullName), "kind": kind, "units": units,
                "revision": "not_observed_in_metadata_only", "dirty": bool(model.IsModified), "origin": str(model.Origin),
                "_untrusted": ["id", "name", "origin"]}
    def parameters(self, model):
        out = []
        for p in sequence(self.cast(model, "IpfcParameterOwner").ListParams()):
            value = p.Value
            for enum, kind, prop in (("EpfcPARAM_STRING", "string", "StringValue"), ("EpfcPARAM_DOUBLE", "double", "DoubleValue"),
                                     ("EpfcPARAM_INTEGER", "integer", "IntValue"), ("EpfcPARAM_BOOLEAN", "boolean", "BoolValue"), ("EpfcPARAM_NOTE", "note", "NoteId")):
                if value.discr == self.enum(enum):
                    raw = getattr(value, prop)
                    out.append({"name": str(p.Name), "kind": kind, "value": str(raw) if kind == "note" else raw,
                                "relation_driven": bool(p.IsRelationDriven), "_untrusted": ["name", "value"]})
                    break
            else:
                raise Error("E_UNSUPPORTED", "unsupported parameter discriminator")
        return sorted(out, key=lambda x: x["name"])
    def dimension_objects(self, model):
        return [self.cast(d, "IpfcBaseDimension") for d in sequence(self.cast(model, "IpfcModelItemOwner").ListItems(self.enum("EpfcITEM_DIMENSION")))]
    def dimensions(self, model):
        rows = []
        for d in self.dimension_objects(model):
            kind = "unknown"
            for enum, name in (("EpfcDIM_LINEAR", "linear"), ("EpfcDIM_RADIAL", "radial"), ("EpfcDIM_DIAMETER", "diameter"), ("EpfcDIM_ANGULAR", "angular")):
                if d.DimType == self.enum(enum):
                    kind = name
                    break
            rows.append({"id": str(d.Id), "symbol": str(d.Symbol), "kind": kind, "value": float(d.DimValue),
                         "negative_direction": bool(d.ExtendsInNegativeDirection), "relation_driven": bool(d.IsRelationDriven), "_untrusted": ["symbol"]})
        return sorted(rows, key=lambda x: x["id"])
    def features(self, model):
        if self.kind(model) == "drawing":
            return []
        return sorted([{"id": str(f.Id), "name": str(f.Name), "type": str(f.FeatTypeName), "status": str(f.Status), "_untrusted": ["name", "type"]}
                       for f in sequence(self.cast(model, "IpfcSolid").ListFeaturesByType(None, None))], key=lambda x: x["id"])
    def relations(self, model):
        return [str(r) for r in sequence(self.cast(model, "IpfcRelationOwner").Relations)]
    def snapshot(self, model):
        s = {"snapshot_schema": "1.0", "model": self.info(model), "parameters": self.parameters(model),
             "dimensions": self.dimensions(model), "features": self.features(model), "relations": self.relations(model),
             "provenance": self.provenance(), "not_checked": ["brep_geometry", "gui_concurrency", "interference", "manufacturability", "stress", "saved_reopen_roundtrip"], "_untrusted": models.UNTRUSTED}
        # Observation digest, deliberately NOT represented as PTC's revision stamp.
        s["model"]["revision"] = digest(s)
        return models.validate(s)
    def set_value(self, model, change, value):
        if change["operation"] == "dimension.set":
            found = [d for d in self.dimension_objects(model) if str(d.Id) == change["target"]]
            if len(found) != 1 or found[0].IsRelationDriven or found[0].DimType != self.enum("EpfcDIM_LINEAR"):
                raise Error("E_CONFLICT", "dimension changed or is no longer an editable linear dimension")
            found[0].DimValue = float(value)
        else:
            p = self.cast(model, "IpfcParameterOwner").GetParam(change["target"])
            if p is None or p.IsRelationDriven:
                raise Error("E_CONFLICT", "parameter disappeared or became relation-driven")
            union = p.Value
            for enum, prop in (("EpfcPARAM_STRING", "StringValue"), ("EpfcPARAM_DOUBLE", "DoubleValue"), ("EpfcPARAM_INTEGER", "IntValue"), ("EpfcPARAM_BOOLEAN", "BoolValue")):
                if union.discr == self.enum(enum):
                    setattr(union, prop, value)
                    p.Value = union
                    return
            raise Error("E_UNSUPPORTED", "parameter type is not writable")
    def verify_values(self, model, changes, key="after"):
        import math
        p = {r["name"]: r["value"] for r in self.parameters(model)}
        d = {r["id"]: r["value"] for r in self.dimensions(model)}
        for change in changes:
            actual = (d if change["operation"] == "dimension.set" else p).get(change["target"])
            expected = change[key]
            if type(expected) in (int, float) and type(actual) in (int, float):
                if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10):
                    return False
            elif type(actual) is not type(expected) or actual != expected:
                return False
        return True
    def apply(self, ident, change, expected, token):
        safety.require_write(native=True)
        with safety.lock("native:"+self.session_id+":"+ident.casefold()):
            model = self.model(ident)
            if self.kind(model) != "part":
                raise Error("E_UNSUPPORTED", "native writes are limited to individual parts")
            s = self.snapshot(model)
            rev = models.revision(s)
            if expected != rev:
                raise Error("E_CONFLICT", "native observed state changed")
            _, changes = models.plan(s, change)
            if not model.CheckIsModifiable(False):
                raise Error("E_FORBIDDEN", "Creo reports this part is not modifiable without UI")
            solid = self.cast(model, "IpfcSolid")
            old_failed = {str(f.Id) for f in sequence(solid.ListFailedFeatures())}
            safety.consume(token, safety.scope("change apply", "native", ident.casefold(), change, rev))
            def write():
                attempted = []
                try:
                    for c in changes:
                        attempted.append(c)  # setters can apply a change and then throw
                        self.set_value(model, c, c["after"])
                    solid.Regenerate(None)
                    failed = {str(f.Id) for f in sequence(solid.ListFailedFeatures())}
                    if failed-old_failed or not self.verify_values(model, changes):
                        raise Error("E_NATIVE_FAILURE", "regeneration or requested-value check failed")
                    after = self.snapshot(model)
                except (Exception, KeyboardInterrupt) as exc:
                    restored = False
                    try:
                        for c in reversed(attempted):
                            self.set_value(model, c, c["before"])
                        solid.Regenerate(None)
                        restored = self.verify_values(model, attempted, "before")
                    except Exception:
                        pass
                    raise Error("E_INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "E_NATIVE_FAILURE", "native modification did not verify; inspect the live part",
                                {"requested_values_restored": restored, "whole_model_restored": False, "state_unknown": True,
                                 "persisted": False, "safe_next_action": "inspect live state; do not save or blindly repeat the write"}) from exc
                return {"model": after["model"], "changes": changes, "backup": None, "persisted": False,
                        "verification": {"requested_values": True, "read_back": True, "regenerated": True, "geometry_verified": False, "new_failed_features": []},
                        "provenance": after["provenance"], "not_checked": after["not_checked"], "_untrusted": ["model", "changes"]}
            return safety.audited("change apply", self.session_id+":"+ident.casefold(), write)
    def dispatch(self, req):
        action, ident = req["action"], req.get("model")
        if action == "session.status":
            current = self.session.CurrentModel
            return {"connected": True, "current_model": str(current.FileName) if current else None,
                    "models_loaded": len(self.loaded()), "provenance": self.provenance(), "_untrusted": ["current_model"]}
        if action == "model.list":
            return {"items": sorted([self.info(m) for m in self.loaded()], key=lambda x: x["id"])}
        if action == "change.apply":
            return self.apply(ident, req["changeset"], req["expected_revision"], req.get("confirm_token"))
        model = self.model(ident)
        if action == "model.snapshot":
            return self.snapshot(model)
        if action == "model.info":
            return {"model": self.info(model), "provenance": self.provenance(), "_untrusted": ["model"]}
        funcs = {"model.parameters": self.parameters, "model.dimensions": self.dimensions, "model.features": self.features, "model.relations": self.relations}
        if action not in funcs:
            raise Error("E_UNSUPPORTED", "unsupported native action")
        return {"items": funcs[action](model)}

class Native:
    name = "native"
    def __init__(self, model=None, timeout=30, runner=None):
        self.model, self.target, self.timeout = model, model.casefold() if model else None, timeout
        self.runner = runner or subprocess.run
    def request(self, action, **args):
        cmd = [sys.executable, "-m", "creo_cli.native"]
        req = {"protocol_version": "1.0", "action": action, "model": self.model, **args}
        mutating = action == "change.apply"
        try:
            p = self.runner(cmd, input=canonical(req), capture_output=True, timeout=self.timeout, shell=False, check=False)
        except subprocess.TimeoutExpired as exc:
            raise Error("E_TIMEOUT", "native worker deadline exceeded", {"state_unknown": mutating, "safe_next_action": "read live state; never blindly replay a write"}) from exc
        except OSError as exc:
            raise Error("E_IO", "native worker could not start", {"write_started": False}) from exc
        if len(p.stdout) > MAX_INPUT:
            raise Error("E_PROTOCOL", "native response exceeds protocol ceiling", {"state_unknown": mutating})
        try:
            data = decode(p.stdout)
            ok = data["ok"]
            valid = type(ok) is bool and data["schema_version"] == "1.0"
            valid = valid and set(data) == {"ok", "schema_version", "meta", "data" if ok else "error"}
            valid = valid and isinstance(data["meta"], dict) and type(data["meta"].get("duration_ms")) is int and data["meta"]["duration_ms"] >= 0
            valid = valid and not set(data["meta"])-{"duration_ms", "notices"}
            if not valid:
                raise ValueError()
            if ok:
                if p.returncode != 0 or not isinstance(data["data"], dict):
                    raise ValueError()
                return data["data"]
            e = data["error"]
            if set(e) != {"code", "message", "details", "retryable"} or not isinstance(e["message"], str) or not isinstance(e["details"], dict):
                raise ValueError()
            if e["code"] not in CODES or CODES[e["code"]] != (p.returncode, e["retryable"]) or type(e["retryable"]) is not bool:
                raise ValueError()
        except (ValueError, KeyError, TypeError, Error) as exc:
            raise Error("E_PROTOCOL", "invalid native envelope or exit/error mapping", {"state_unknown": mutating}) from exc
        raise Error(e["code"], e["message"], e["details"])
    def observe(self):
        s = models.validate(self.request("model.snapshot"))
        return s, models.revision(s)

def run_native(req):
    if not probe()["configured"]:
        raise Error("E_BACKEND_UNAVAILABLE", "Windows Creo VB API is not configured", {"checks": probe(), "fix": "see docs/NATIVE_ADAPTER.md; no automatic mock fallback"})
    import pythoncom
    from win32com.client import CastTo, constants, gencache
    connection = None
    pythoncom.CoInitialize()
    try:
        factory = gencache.EnsureDispatch("pfcls.CCpfcAsyncConnection")
        connection = factory.Connect("", "", None, 10)
        identity = connection.GetConnectionId().ExternalRep
        return Session(connection.Session, constants, CastTo, identity).dispatch(req)
    except Error:
        raise
    except Exception as exc:
        raise Error("E_NATIVE_FAILURE", "PTC API call failed; inspect SDK compatibility and environment",
                    {"exception_type": type(exc).__name__, "state_unknown": req["action"] == "change.apply", "live_verified": False}) from exc
    finally:
        if connection:
            try:
                connection.Disconnect(1)  # detach, never terminate Creo
            except Exception:
                pass
        pythoncom.CoUninitialize()

def worker():
    t = time.monotonic()
    import signal
    def interrupted(_s, _f):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    exit_code = 0
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw) > MAX_INPUT:
            raise Error("E_VALIDATION", "request too large")
        req = decode(raw)
        if not isinstance(req, dict) or req.get("protocol_version") != "1.0" or req.get("action") not in ACTIONS:
            raise Error("E_PROTOCOL", "invalid native request")
        if set(req)-{"protocol_version", "action", "model", "changeset", "expected_revision", "confirm_token"}:
            raise Error("E_PROTOCOL", "unknown native request fields")
        if req["action"] != "change.apply" and set(req) & {"changeset", "expected_revision", "confirm_token"}:
            raise Error("E_PROTOCOL", "write fields are invalid on a read action")
        if req["action"] not in {"session.status", "model.list"} and (not isinstance(req.get("model"), str) or not req["model"]):
            raise Error("E_USAGE", "explicit model identity is required")
        if req["action"] == "change.apply":
            models.validate_change(req.get("changeset"))
            if not req.get("confirm_token"):
                raise Error("E_CONFIRMATION_REQUIRED", "worker writes also require a confirmation token")
        result = {"ok": True, "schema_version": "1.0", "data": run_native(req)}
    except Error as exc:
        exit_code = exc.exit
        result = {"ok": False, "schema_version": "1.0", "error": exc.payload()}
    except KeyboardInterrupt:
        exc = Error("E_INTERRUPTED", "native worker interrupted; inspect live state", {"state_unknown": True})
        exit_code, result = exc.exit, {"ok": False, "schema_version": "1.0", "error": exc.payload()}
    except Exception:
        exc = Error("E_UNKNOWN", "native worker failed", {"state_unknown": True})
        exit_code, result = exc.exit, {"ok": False, "schema_version": "1.0", "error": exc.payload()}
    result["meta"] = {"duration_ms": round((time.monotonic()-t)*1000)}
    try:
        encoded = canonical(result)
    except (ValueError, TypeError, RecursionError):
        exc = Error("E_PROTOCOL", "native result could not be encoded", {"state_unknown": True})
        exit_code = exc.exit
        encoded = canonical({"ok": False, "schema_version": "1.0", "error": exc.payload(), "meta": result["meta"]})
    sys.stdout.buffer.write(encoded+b"\n")
    return exit_code

if __name__ == "__main__":
    raise SystemExit(worker())
