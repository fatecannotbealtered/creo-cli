"""Machine-readable result shapes for the CREOSON command surface.

Optional vendor fields stay optional; fields added by this adapter are required.
This does not imply that the upstream's geometric assertions have been verified.
"""
from __future__ import annotations

from copy import deepcopy

S, I, B, N = ({"type": t} for t in ("string", "integer", "boolean", "number"))


def array(item): return {"type": "array", "items": item}
def obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": True}

VECTOR = obj({"x": N, "y": N, "z": N}, ("x", "y", "z"))
ARTIFACT = obj({"path": S, "size_bytes": I, "sha256": S}, ("path", "size_bytes", "sha256"))
PROVENANCE = obj({"backend": {"type": "string", "enum": ["creoson"]}, "simulation": {"type": "boolean", "enum": [False]},
                  "live_verified": {"type": "boolean", "enum": [False]}, "evidence_level": S}, ("backend", "simulation", "live_verified"))
VERIFICATION = obj({"level": {"type": "string", "enum": ["observation", "upstream_acknowledged_only", "selected_postconditions_verified"]},
                    "checks": array(obj({"check": S, "passed": B}, ("check", "passed"))), "not_checked": array(S)}, ("level", "checks"))
PARAMETER = obj({"name": S, "type": S, "value": {"type": ["string", "number", "boolean", "null"]}, "encoded": B, "description": S, "owner_name": S}, ("name", "type", "value"))
DIMENSION = obj({"name": S, "value": {"type": ["number", "string"]}, "dim_type": S, "encoded": B, "dwg_dim": B, "text": array(S), "location": VECTOR, "sheet": I, "view_name": S, "tolerance_type": S, "tol_plus": N, "tol_minus": N}, ("name", "value"))
FEATURE = obj({"name": S, "type": S, "status": S, "feat_id": S, "feat_number": S, "path": array(S)}, ("type", "status"))
DRAWING_VIEW = obj({"name": S, "sheet": I, "location": VECTOR, "text_height": N, "view_model": S, "simp_rep": S}, ("name", "sheet"))
BASE_FIELDS = {"file": S, "dirname": S, "revision": I, "files": array(S), "generic": S, "has_simprep": B,
               "material": {"type": ["string", "null"]}, "num_sheets": I, "featureid": S,
               "origin": VECTOR, "x_axis": VECTOR, "y_axis": VECTOR, "z_axis": VECTOR, "x_rot": N, "y_rot": N, "z_rot": N,
               "mass": N, "volume": N, "density": N, "surface_area": N, "ctr_grav": VECTOR,
               "length_units": S, "mass_units": S, "filename": S, "drawing": S,
               "roundtrip_verified": B, "compared_sections": array(S), "artifacts": array(ARTIFACT)}


def result_schema(op):
    props = {name: deepcopy(BASE_FIELDS.get(name, {"type": "object"})) for name in op.response_fields}
    required = []
    if op.path == "file units": required = ["length_units", "mass_units"]
    if op.path == "file massprops":
        props["unit_context"] = obj({"length_units": S, "mass_units": S, "density_source": S, "material_assignment_verified": B}, ("length_units", "mass_units", "density_source", "material_assignment_verified"))
        required = ["mass", "volume", "density", "surface_area", "unit_context"]
    if op.path == "assembly tree":
        # The upstream represents the root differently across versions; preserve it.
        props["children"] = {"type": ["array", "object"]}
    if op.list_key:
        props.pop(op.list_key, None)
        item = {"parameter list": PARAMETER, "dimension list": DIMENSION, "feature list": FEATURE, "drawing views": DRAWING_VIEW}.get(op.path, S)
        props |= {"items": array(item), "count": I, "total": I, "offset": I, "has_more": B, "next_offset": I, "_untrusted": array(S)}
        required = ["items", "count", "total", "offset", "has_more", "_untrusted"]
    if op.verifier == "export":
        props |= {"artifact": ARTIFACT, "publish_policy": {"type": "string", "enum": ["atomic_no_clobber"]}}
        required = ["artifact", "publish_policy", "filename", "dirname"]
    if op.verifier in ("backup", "save"):
        props["artifacts"] = array(ARTIFACT); required = ["artifacts"]
    if op.verifier == "roundtrip": required = ["roundtrip_verified", "compared_sections", "artifacts"]
    return obj(props, required)


def envelope_schema(op):
    observation = obj({"operation": S, "result": result_schema(op), "verification": VERIFICATION,
                       "provenance": PROVENANCE, "request_count": I, "not_checked": array(S), "_untrusted": array(S)},
                      ("operation", "result", "verification", "provenance", "request_count", "not_checked", "_untrusted"))
    if not op.write: return observation
    return obj({"operation_id": S, "status": {"type": "string", "enum": ["completed"]}, "completed_steps": I,
                "steps": array(obj({"id": S, "command": S, "ok": B, "verification": VERIFICATION, "result_sha256": S, "result_artifact": obj({"sha256": S, "size_bytes": I}, ("sha256", "size_bytes"))}, ("id", "command", "ok", "verification", "result_sha256", "result_artifact"))),
                "last_result": observation, "request_count": I, "provenance": PROVENANCE,
                "not_checked": array(S), "_untrusted": array(S)},
               ("operation_id", "status", "completed_steps", "steps", "last_result", "request_count", "provenance", "not_checked", "_untrusted"))
