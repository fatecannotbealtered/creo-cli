"""One registry drives parsing, dispatch, output validation and the `reference` contract.

Commands use task-justified resource paths of variable depth. Command
modules declare their commands next to their handlers; this module collects them in a
fixed order so `reference` lists them stably.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from . import execution_budgets, schemas


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "string"  # string | integer | number | boolean (a flag)
    required: bool = False
    default: Any = None
    choices: tuple = ()
    description: str = ""

    def describe(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "multiple": False,
            "default": False if self.type == "boolean" and self.default is None else self.default,
            **({"description": self.description} if self.description else {}),
            **({"enum": list(self.choices)} if self.choices else {}),
        }


@dataclass(frozen=True)
class Command:
    path: str
    description: str
    handler: Callable[[dict], dict]
    output: dict  # JSON schema of `data`: a read's result, or a confirmed write's receipt
    params: tuple = ()
    write: bool = False
    dangerous: bool = False
    untrusted: tuple = ()
    request: dict | None = None  # schema of --request, when the command takes one
    request_example: dict | None = None
    example: str = ""
    service_ops: tuple = ()
    sort: str | None = None  # default order of a paginated list

    @property
    def schema_name(self) -> str:
        return self.path.replace(" ", "_")

    @property
    def paginated(self) -> bool:
        return any(p.name == "limit" for p in self.params)

    def describe(self) -> dict:
        from . import discovery, driver

        base = ("creo-cli " + self.path + " " + self.example).strip()
        gate = " --dangerous" if self.dangerous else ""
        examples = (
            [
                base + gate + " --dry-run --compact",
                base + gate + " --confirm <confirm_token> --compact",
            ]
            if self.write
            else [base + " --compact"]
        )
        out = {
            "path": self.path,
            "description": self.description,
            "type": "write" if self.write and self.path != discovery.RECORD_CONTROL else "read",
            "permission": "write"
            if self.write and self.path != discovery.RECORD_CONTROL
            else "read",
            "dangerous": self.dangerous,
            "params": [
                p.describe() | ({"unit": unit} if (unit := discovery.units(self.path, p)) else {})
                for p in self.params
            ],
            "output_schema": self.schema_name,
            "examples": examples,
            "service_ops": list(self.service_ops),
            "uses_creo": bool(self.service_ops),
            # null: the command never talks to Creo, so there is nothing to verify live.
            "live_verified": (self.path in LIVE_VERIFIED) if self.service_ops else None,
            "driver": discovery.metadata(self),
            "extensions": {
                "creo": {
                    "runtime_lifecycle": "public"
                    if self.path in driver.MIGRATED
                    else "record_control"
                    if self.path == discovery.RECORD_CONTROL
                    else "legacy"
                    if self.write
                    else "read",
                    "write_gate": self.write,
                }
            },
        }
        if self.path == discovery.RECORD_CONTROL:
            out["examples"] = [base.removesuffix(" --dry-run") + " --compact"]
        if self.write:
            out["dry_run_schema"] = "dry_run"
        if self.path in driver.MIGRATED:
            out["driver"] = driver.command_metadata(self.path)
            out["dry_run_schema"] = "driver_plan"
            out["receipt_schema"] = "urn:tool-driver-cli-spec:receipt:2.0"
        if self.request is not None:
            out["request_schema"] = self.request
            out["request_example"] = self.request_example
        if self.paginated:
            out["pagination"] = {
                "style": "offset",
                "default_sort": self.sort or "stable source order",
            }
        return out


# Paths recorded running as CLI subprocesses against a live Creo. tests/test_contract.py
# holds each one to a call in LIVE_EVIDENCE; a command joins only when a recording shows it.
LIVE_EVIDENCE = "docs/evidence/live-creo.json"
LIVE_VERIFIED: frozenset = frozenset(
    {
        "assembly add",
        "assembly check",
        "assembly create",
        "assembly explode",
        "assembly remove",
        "assembly replace",
        "dimension list",
        "dimension set",
        "dimension tolerance",
        "doctor",
        "drawing add-balloons",
        "drawing add-bom",
        "drawing add-datum",
        "drawing add-dimension",
        "drawing add-gtol",
        "drawing add-note",
        "drawing add-symbol",
        "drawing add-table",
        "drawing add-title-block",
        "drawing add-view",
        "drawing annotate",
        "drawing create",
        "drawing edit-note",
        "drawing hide-dimension",
        "drawing move-dimension",
        "drawing move-table",
        "drawing move-view",
        "drawing remove",
        "feature chamfer",
        "feature datum-axis",
        "feature datum-plane",
        "feature draft",
        "feature delete",
        "family remove",
        "family set",
        "family show",
        "feature extrude",
        "feature hole",
        "feature list",
        "feature mirror",
        "feature pattern",
        "feature rename",
        "feature resume",
        "feature revolve",
        "feature rib",
        "feature round",
        "feature shell",
        "feature show",
        "feature suppress",
        "feature sweep",
        "feature thread",
        "geometry list",
        "geometry measure",
        "material assign",
        "material list",
        "model close",
        "model discard",
        "model export",
        "model import",
        "model list",
        "model open",
        "model render",
        "model save",
        "model set-common-name",
        "model set-tolerance-standard",
        "model show",
        "parameter list",
        "parameter set",
        "part create",
        "relation list",
        "relation set",
        "session cd",
        "session status",
        "workflow run",
    }
)

PENDING_LIVE_VERIFICATION = frozenset(
    {
        "dimension set",
        "relation set",
        "drawing create",
        "drawing add-view",
        "drawing annotate",
        "drawing add-title-block",
        "drawing add-table",
        "model show",
    }
)
# Preserve recorded history while not assigning it to unreleased native behavior.
LIVE_VERIFIED = LIVE_VERIFIED - PENDING_LIVE_VERIFICATION

LIMIT = Param("limit", "integer", default=100, description="page size, 1..1000")
OFFSET = Param("offset", "integer", default=0, description="items to skip")
MODEL = Param("model", required=True, description="model name, e.g. block or block.prt")
REQUEST = Param("request", required=True, description="request file, or - to read JSON from stdin")

GLOBALS = [
    {
        "name": "format",
        "type": "string",
        "default": "json",
        "choices": ["json", "text", "raw"],
        "description": "json: the envelope; text: the data or the error alone, indented, for "
        "people; raw: the data or the error alone",
    },
    {
        "name": "json",
        "type": "boolean",
        "deprecated": True,
        "description": "alias of --format json",
    },
    {"name": "compact", "type": "boolean", "description": "JSON without whitespace"},
    {
        "name": "quiet",
        "type": "boolean",
        "description": "no progress on stderr; creo-cli writes none, and never hides an error",
    },
    {
        "name": "fields",
        "type": "string",
        "description": "reads only: comma-separated dotted paths to keep; on a list, a path "
        "that is not a top-level field is taken inside items (--fields model,type), and a "
        "field some items lack is left out of those",
    },
    {
        "name": "timeout",
        "type": "number",
        "default": 30,
        "minimum": 0.1,
        "maximum": execution_budgets.EXTENDED_MAX_SECONDS,
        "description": "whole invocation service-wait budget in seconds, shared by workflow "
        "steps and readers; each call uses the remaining time. Queued work is withdrawn; "
        "already-started native work is not cancelled. Ordinary maximum is 300; only the "
        "explicit drawing_execution_budget eligible command list permits >300 up to 1200 "
        "with a matching service; preview and confirmation must select the same total",
    },
    {
        "name": "dry-run",
        "type": "boolean",
        "description": "writes only: preview and issue a token; excludes confirm",
    },
    {
        "name": "confirm",
        "type": "string",
        "description": "writes only: the token a --dry-run issued; single use",
    },
    {
        "name": "dangerous",
        "type": "boolean",
        "description": "required, with both steps, on commands marked dangerous",
    },
]


def _collect() -> list[Command]:
    from .command_tree import migrate
    from .commands import (
        appearance,
        artifact,
        assembly,
        detailing,
        dimension,
        display,
        drawing,
        family,
        feature,
        geometry,
        layout,
        material,
        meta,
        model,
        operation,
        parameter,
        part,
        relation,
        resources,
        service,
        session,
        workflow,
        workspace,
    )

    current = [
        *meta.COMMANDS,
        *service.COMMANDS,
        *session.COMMANDS,
        *workspace.COMMANDS,
        *model.COMMANDS,
        *part.COMMANDS,
        *feature.COMMANDS,
        *geometry.COMMANDS,
        *dimension.COMMANDS,
        *parameter.COMMANDS,
        *relation.COMMANDS,
        *family.COMMANDS,
        *material.COMMANDS,
        *assembly.COMMANDS,
        *drawing.COMMANDS,
        *detailing.COMMANDS,
        *workflow.COMMANDS,
        *operation.COMMANDS,
    ]
    collected = [
        *migrate(current),
        *resources.COMMANDS,
        *artifact.COMMANDS,
        *layout.COMMANDS,
        *appearance.COMMANDS,
        *display.COMMANDS,
    ]
    eligible = [
        command
        for command in collected
        if not command.dangerous
        and command.path not in workflow.EXCLUDED
        and not command.path.startswith(("workflow ", "operation ", "service "))
    ]
    # These are possible dependency operations, not a promise to execute every one.
    # Planning executes only the eligible read prefix; a run also reaches write steps.
    read_ops = tuple(
        sorted({op for command in eligible if not command.write for op in command.service_ops})
    )
    task_ops = tuple(sorted({op for command in eligible for op in command.service_ops}))
    return [
        replace(command, service_ops=read_ops)
        if command.path == "workflow plan"
        else replace(command, service_ops=task_ops)
        if command.path == "workflow run"
        else command
        for command in collected
    ]


COMMANDS: list[Command] = _collect()
BY_PATH: dict[str, Command] = {c.path: c for c in COMMANDS}
# Historical native recordings do not authenticate this changed candidate's paths/readers.
LIVE_VERIFIED = frozenset()
PENDING_LIVE_VERIFICATION = frozenset(c.path for c in COMMANDS if c.service_ops)


def _schemas() -> dict:
    out = {}
    for c in COMMANDS:
        from . import driver

        output = c.output
        if c.path in driver.MIGRATED:
            output = output | {
                "properties": output.get("properties", {})
                | {"receipt": {"$ref": "urn:tool-driver-cli-spec:receipt:2.0"}},
                "required": output.get("required", []) + ["receipt"],
            }
        props = output.get("properties", {})
        out[c.schema_name] = {
            "shape": "object",
            "fields": list(props),
            "untrusted_fields": list(c.untrusted),
            "json_schema": output,
        }
    out["dry_run"] = {
        "shape": "object",
        "fields": list(schemas.DRY_RUN["properties"]),
        "untrusted_fields": ["preview"],
        "json_schema": schemas.DRY_RUN,
    }
    out["driver_plan"] = {
        "shape": "object",
        "fields": ["preview", "confirm_token", "expires_at"],
        "untrusted_fields": ["preview"],
        "json_schema": schemas.DRY_RUN
        | {
            "properties": schemas.DRY_RUN["properties"]
            | {"preview": {"$ref": "urn:tool-driver-cli-spec:plan:2.0"}}
        },
    }
    return out


SCHEMAS: dict = _schemas()

NATIVE_READ_RECOVERY = {
    "error_code": "E_NATIVE_READ_PENDING",
    "description": "a confirmed-started native read remains unresolved, or a sent read's "
    "start/completion is unknown because its reply was lost or unreadable; "
    "never retry automatically",
    "details_schema": schemas.NATIVE_READ_PENDING_DETAILS,
    "error_schema": schemas.NATIVE_READ_PENDING_ERROR,
    "guard_scope": "one_client_object",
    "persistent_guard": False,
    "requires_operation_id": False,
    "creates_write_receipt": False,
    "parent_write": {
        "description": "A completed setter and its write ID/dispatch facts remain separate "
        "from an unresolved required verification read. Parent unknown/partial receipt "
        "semantics do not erase the nested original read error.",
        "context_schema": schemas.NATIVE_READ_FAILURE_CONTEXT,
        "receipt_context": "receipt.extensions.creo.native_read_error",
        "error_context": "error.details.native_read_error",
        "local_record": "operation show preserves the same original read context",
        "safe_immediate_checks": [
            "local operation show",
            "process-only GET /health",
            "OS observations",
        ],
        "engineering_readback_precondition": "independently confirm original call and instance "
        "state before any new CAD dispatch, operation query or registration",
        "read_operation_id": None,
        "service_request_id": "only the actual supplied diagnostic_request_id; omitted when absent",
    },
    "automatic_retry": False,
    "request_correlation": {
        "cli_invocation_id": "locally generated CLI process correlation; not a service identity",
        "diagnostic_request_id": "optional service-provided request correlation; omitted when "
        "unavailable, including with older formal services; never inferred from CLI identity",
    },
    "confirmed_started": "started=true and native_call_pending=true require service confirmation",
    "unknown_dispatch": "a sent read with an unreadable reply may still run; omit started and "
    "report native_call_may_be_pending=true",
    "blocked_request": "request_sent=false describes the later blocked attempt; "
    "pending_original_request_sent=true and operation retain the original read identity",
    "process_health": "GET /health touches no CAD API and remains allowed within the deadline",
    "non_poisoning_failures": [
        "failure before request dispatch",
        "HTTP or service authentication refusal",
        "explicit service confirmation started=false",
        "non-CAD HTTP endpoints",
    ],
    "next_action": "preserve diagnostic journals and available request identities; inspect the "
    "instance using process-only health or OS observations; do not issue further CAD requests "
    "until the pending call is resolved, including from a new client or CLI process",
}


NATIVE_DIAGNOSTIC_RECOVERY = {
    "error_code": "E_NATIVE_DIAGNOSTIC",
    "description": "the service observed a serious native message or durable diagnostic failure "
    "and stopped CAD dispatch; this is not proof of a pending getter or a completed write",
    "details_schema": schemas.NATIVE_DIAGNOSTIC_DETAILS,
    "error_schema": schemas.NATIVE_DIAGNOSTIC_ERROR,
    "client_guard_scope": "one_client_object",
    "service_guard_scope": "the_reporting_service_instance_when_enabled",
    "persistent_global_lock": False,
    "automatic_retry": False,
    "creates_write_receipt": False,
    "request_correlation": "only actual service diagnostic_request_id, omitted when absent; "
    "cli_invocation_id is local correlation and cannot substitute for service identity",
    "parent_write": "retain the original operation_id, dispatch facts and raw native effects; "
    "a versioned actual-target setter-return fact is distinct from service_reported_done, "
    "independent effect verification and saving",
    "safe_immediate_checks": ["local operation show", "process-only health", "OS observations"],
    "next_action": "preserve journals and the stopped instance; independently establish original "
    "call and instance state before CAD query or registration. Health, a new Client, CLI restart "
    "or a repaired journal directory does not establish native health or recovery",
}
