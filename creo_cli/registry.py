"""One registry drives dispatch, argument validation and runtime reference."""
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Param:
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    choices: tuple = ()
    def describe(self):
        return {"name": self.name, "type": self.type, "required": self.required, "multiple": False,
                "default": self.default, **({"choices": list(self.choices)} if self.choices else {})}

@dataclass(frozen=True)
class Command:
    path: str
    description: str
    schema: str
    params: tuple = ()
    write: bool = False
    backends: tuple = ("local",)
    example: str = ""
    def describe(self):
        base = ("creo-cli "+self.path+" "+self.example).strip()
        examples = [base+" --dry-run --compact", base+" --confirm <confirm_token> --compact"] if self.write else [base+" --compact"]
        return {**native_description(self.path), "path": self.path, "description": self.description, "output_schema": self.schema,
                "type": "write" if self.write else "read", "permission": "write" if self.write else "read",
                "params": [p.describe() for p in self.params], "supported_backends": list(self.backends),
                "examples": examples, "dangerous": False,
                **({"pagination": {"style": "offset", "default_sort": {
                    "workspace scan": "name casefold, kind, numeric file version, id",
                    "change history": "event id descending",
                    "model parameters": "parameter name ascending",
                    "model relations": "source relation order",
                    "snapshot diff": "section traversal then stable object identity",
                }.get(self.path, "source relation order" if self.path == "file relations" else "name casefold then canonical row" if self.path in {op.path for op in CREOSON_OPS} else "event row descending" if self.path == "workflow history" else "id ascending"), "snapshot_consistent_across_calls": False}}
                   if any(p.name == "limit" for p in self.params) else {})}

MODEL = Param("model", required=True)
BACKEND = Param("backend", default="native", choices=("native", "mock"))
LIMIT, OFFSET = Param("limit", "integer", default=100), Param("offset", "integer", default=0)
INPUT, CHANGE = Param("input", required=True), Param("changeset", required=True)
BOTH = ("native", "mock")
COMMANDS = [
    Command("reference", "Live machine contract, optionally scoped to one command", "reference", (Param("command"),)),
    Command("context", "Local configuration only; does not connect to Creo or network", "context"),
    Command("doctor", "Local diagnostics and honest release-readiness checks", "doctor"),
    Command("changelog", "Version changes derived from packaged CHANGELOG", "changelog", (Param("since"),)),
    Command("system capabilities", "Backend boundaries and unavailable domains", "capabilities"),
    Command("workspace scan", "Inventory one directory of native-looking filenames; not CAD contents", "workspace", (Param("root", required=True), LIMIT, OFFSET), example="--root ./workspace"),
    Command("workspace inspect", "SHA-256 a regular file, with a 1 GiB input ceiling", "file", (Param("file", required=True),), example="--file part.prt.1"),
    Command("snapshot validate", "Validate a portable observation, not a native CAD model", "validation", (INPUT,), example="--input examples/bracket.creo.json"),
    Command("snapshot diff", "Compare observations by stable object identities", "diff", (INPUT, Param("other", required=True), LIMIT, OFFSET), example="--input before.json --other after.json"),
    Command("session status", "Inspect an existing session; never starts or terminates Creo", "session", (BACKEND, Param("model")), backends=BOTH),
    Command("model list", "List loaded models; mock requires one explicit observation file", "model_list", (BACKEND, Param("model"), Param("name"), LIMIT, OFFSET), backends=BOTH),
    Command("model info", "Read metadata; revision digest requires an explicit snapshot", "model_info", (BACKEND, MODEL), backends=BOTH, example="--model bracket.prt"),
    Command("model snapshot", "Read full bounded observed state; no geometry validity claim", "snapshot", (BACKEND, MODEL), backends=BOTH, example="--model bracket.prt"),
    Command("model parameters", "Read typed parameters; relation-driven values remain read-only", "parameters", (BACKEND, MODEL, Param("name"), LIMIT, OFFSET), backends=BOTH, example="--model bracket.prt"),
    Command("model dimensions", "Read dimensions, types and Creo unit-system context", "dimensions", (BACKEND, MODEL, Param("name"), LIMIT, OFFSET), backends=BOTH, example="--model bracket.prt"),
    Command("model features", "Read feature identities and statuses, not create features", "features", (BACKEND, MODEL, Param("name"), LIMIT, OFFSET), backends=BOTH, example="--model bracket.prt"),
    Command("model relations", "Return relations as untrusted text; never evaluate them", "relations", (BACKEND, MODEL, LIMIT, OFFSET), backends=BOTH, example="--model bracket.prt"),
    Command("model init", "Create a SIMULATION .creo.json fixture, not a Creo .prt", "initialized", (Param("backend", default="mock", choices=("mock",)), MODEL, Param("name", default="bracket")), True, ("mock",), "--backend mock --model demo.creo.json --name bracket"),
    Command("change history", "Read local redacted audit records, newest first", "history", (LIMIT, OFFSET)),
    Command("change validate", "Validate restricted ChangeSet syntax without contacting Creo", "validation", (CHANGE,), example="--changeset examples/change.json"),
    Command("change preview", "Read current state and check a parameter plan; no token issued", "preview", (BACKEND, MODEL, CHANGE), backends=BOTH, example="--model bracket.prt --changeset change.json"),
    Command("change apply", "Guarded typed modification; native changes remain unsaved", "applied", (BACKEND, MODEL, CHANGE), True, BOTH, "--model bracket.prt --changeset change.json"),
]
S, B, I, O, A = ({"type": t} for t in ("string", "boolean", "integer", "object", "array"))
def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": True}
def schema(properties, untrusted=()):
    return {"shape": "object", "fields": list(properties), "untrusted_fields": list(untrusted), "json_schema": obj(properties)}
def arr(item):
    return {"type": "array", "items": item}
MODEL_TYPE = obj({"id": S, "name": S, "kind": {"type": "string", "enum": ["part", "assembly", "drawing"]}, "units": S, "revision": S, "dirty": B})
PARAM_TYPE = obj({"name": S, "kind": S, "value": {"type": ["string", "number", "boolean"]}, "relation_driven": B})
DIM_TYPE = obj({"id": S, "symbol": S, "kind": S, "value": {"type": "number"}, "relation_driven": B})
FEATURE_TYPE = obj({"id": S, "name": S, "type": S, "status": S})
LIST = {"items": A, "count": I, "total": I, "offset": I, "has_more": B, "_untrusted": A}
SCHEMAS = {
    "reference": schema({"tool": S, "version": S, "risk_tier": S, "release_readiness": O, "commands": A, "schemas": O, "error_codes": O, "exit_codes": O, "global_flags": A}),
    "context": schema({"version": S, "credentials": O, "config": O, "native": O}),
    "doctor": schema({"checks": A}), "changelog": schema({"current_version": S, "entries": A}),
    "capabilities": schema({"backends": A, "native_live_verified": B, "unsupported_domains": A}),
    "workspace": schema(LIST|{"root": S, "scan_errors": A, "complete": B, "provenance": O, "not_checked": A}, ("items", "root", "scan_errors")),
    "file": schema({"path": S, "sha256": S, "size_bytes": I, "provenance": O, "not_checked": A}, ("path",)),
    "validation": schema({"valid": B, "kind": S, "summary": O}, ("summary",)),
    "session": schema({"connected": B, "current_model": {"type": ["string", "null"]}, "models_loaded": I, "provenance": O}, ("current_model",)),
    "model_info": schema({"model": MODEL_TYPE, "provenance": O}, ("model",)),
    "snapshot": schema({"snapshot_schema": S, "model": MODEL_TYPE, "parameters": arr(PARAM_TYPE), "dimensions": arr(DIM_TYPE), "features": arr(FEATURE_TYPE), "relations": arr(S), "provenance": O, "not_checked": A, "_untrusted": A}, ("model", "parameters", "dimensions", "features", "relations")),
    "preview": schema({"preview": O, "revision": S, "provenance": O, "not_checked": A}, ("preview",)),
    "dry_run": schema({"preview": O, "confirm_token": S, "expires_at": S, "provenance": O, "not_checked": A}, ("preview",)),
    "applied": schema({"model": MODEL_TYPE, "changes": A, "backup": {"type": ["string", "null"]}, "persisted": B, "verification": O, "provenance": O, "not_checked": A, "audit_status": S}, ("model", "changes", "backup")),
}
for name, typ in (("model_list", MODEL_TYPE), ("parameters", PARAM_TYPE), ("dimensions", DIM_TYPE), ("features", FEATURE_TYPE), ("relations", S),
                  ("diff", obj({"section": S, "id": S, "before": {}, "after": {}})),
                  ("history", obj({"id": S, "attempt_id": S, "at": S, "command": S, "target_sha256": S, "phase": S, "error_code": {"type": ["string", "null"]}}))):
    SCHEMAS[name] = schema(LIST|{"items": arr(typ)}, ("items",))
GLOBALS = [
    {"name": "format", "type": "string", "default": "json", "choices": ["json", "text", "raw"]},
    {"name": "json", "type": "boolean", "deprecated": True},
    {"name": "compact", "type": "boolean"}, {"name": "quiet", "type": "boolean"},
    {"name": "fields", "type": "string", "description": "Read-only dotted paths; security and pagination metadata retained"},
    {"name": "timeout", "type": "number", "default": 30, "minimum": .1, "maximum": 300},
    {"name": "dry-run", "type": "boolean", "description": "Writes only; excludes confirm"},
    {"name": "confirm", "type": "string", "description": "Single-use operation-bound token; excludes dry-run"},
]

SCHEMAS["initialized"] = schema(SCHEMAS["snapshot"]["json_schema"]["properties"] | {"audit_status": S}, SCHEMAS["snapshot"]["untrusted_fields"])


# CREOSON operations use explicit JSON requests. Request fields/defaults and
# source provenance remain discoverable from the same registry as dispatch.
def native_description(path):
    from .creoson_catalog import BY_PATH
    op = BY_PATH.get(path)
    if not op:
        return {}
    return {"request_schema": op.request_schema, "request_example": op.example,
            "upstream": {"command": op.command, "function": op.function,
                         "safe_defaults": op.defaults, "response_fields": list(op.response_fields)},
            "source": op.source(), "effect": op.effect, "interaction_risks": list(op.interaction_risks),
            **({"upstream_sequence": ["file.save", "file.close_window", "file.erase", "file.open"], "requires": "one isolated loaded part"} if path == "file roundtrip" else {}),
            "verification_policy": op.verifier, "live_verified": False,
            "preview_kind": "request_plan_not_predicted_geometry" if op.write else None}

from .creoson_catalog import OPS as CREOSON_OPS
for operation in CREOSON_OPS:
    params = (Param("request", required=bool(operation.request_schema["required"])),)
    if operation.list_key:
        params += (LIMIT, OFFSET)
    COMMANDS.append(Command(operation.path, operation.description,
        "native_execution" if operation.write else "native_observation", params,
        operation.write, ("creoson",), "--request examples/requests/" + operation.path.replace(" ", "-") + ".json"))

COMMANDS += [
    Command("creoson connect", "Connect to an existing CREOSON service; never starts Creo", "creoson_connected", (Param("creo-major", "integer", required=True),), True, ("creoson",), "--creo-major 10"),
    Command("creoson status", "Probe the local CREOSON service for an existing Creo session", "creoson_status", (), False, ("creoson",)),
    Command("workflow validate", "Validate an explicit native workflow offline, without executing it", "validation", (INPUT,), example="--input examples/workflow-bracket.json"),
    Command("workflow run", "Execute an allowlisted native workflow with one confirmation and durable partial-result receipts", "native_execution", (INPUT,), True, ("creoson",), "--input examples/workflow-bracket.json"),
    Command("workflow status", "Read a local receipt; does not query or resume Creo", "native_receipt", (Param("operation-id", required=True),), example="--operation-id <operation_id>"),
    Command("workflow history", "List local native workflow receipts; never retry writes", "native_history", (LIMIT, OFFSET)),
    Command("workflow reconcile", "Human acknowledgement after inspecting an uncertain run and verifying server idle; never rolls back or resumes", "native_receipt", (Param("operation-id", required=True), Param("note", required=True), Param("acknowledge", required=True, choices=("human-inspected-server-idle",))), True, ("local",), '--operation-id <operation_id> --acknowledge human-inspected-server-idle --note "Manually inspected disposable Creo session and server is idle"'),
]
SCHEMAS.update({
    "native_observation": schema({"operation": S, "result": O, "verification": O, "provenance": O, "not_checked": A, "request_count": I, "_untrusted": A}, ("result",)),
    "native_execution": schema({"operation_id": S, "status": S, "completed_steps": I, "steps": A, "last_result": O, "request_count": I, "provenance": O, "not_checked": A, "_untrusted": A}, ("last_result",)),
    "native_receipt": schema({"receipt": O, "provenance": O, "not_checked": A, "_untrusted": A}, ("receipt",)),
    "native_history": schema(LIST, ("items",)),
    "creoson_status": schema({"running": B, "session_cached": B, "provenance": O}),
    "creoson_connected": schema({"connected": B, "creo_major_declared": I, "creo_major_detected": {"type": ["integer", "null"]}, "session_stored": B, "live_verified": B, "operation_id": S, "provenance": O}),
})

COMMANDS.append(Command("workflow result", "Read a hash-verified saved result for one completed workflow step", "native_step_result", (Param("operation-id", required=True), Param("step-id", required=True)), example="--operation-id <operation_id> --step-id inspect"))
SCHEMAS["native_step_result"] = schema({"operation_id": S, "step_id": S, "result": O, "provenance": O, "_untrusted": A}, ("result",))


# Each concrete native operation has a real nested response schema, not one
# generic 'object' promise shared across every kind of business result.
from dataclasses import replace
from .creoson_schemas import envelope_schema
for operation in CREOSON_OPS:
    name = "creoson_" + operation.path.replace(" ", "_").replace("-", "_")
    machine = envelope_schema(operation)
    SCHEMAS[name] = {"shape": "object", "fields": list(machine["properties"]),
                     "untrusted_fields": ["last_result"] if operation.write else ["result"],
                     "json_schema": machine}
    COMMANDS = [replace(c, schema=name) if c.path == operation.path else c for c in COMMANDS]
