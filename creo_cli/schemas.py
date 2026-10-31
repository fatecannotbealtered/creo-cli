"""Output shapes shared by commands: `reference` publishes them, every reply is checked on them."""

from __future__ import annotations

S, INT, B, N = ({"type": t} for t in ("string", "integer", "boolean", "number"))
NS, NB, NN, NI = ({"type": [t, "null"]} for t in ("string", "boolean", "number", "integer"))
ANY = {}


def array(item: dict) -> dict:
    return {"type": "array", "items": item}


def shape(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": True,
    }


UNTRUSTED = array(S)

ASSEMBLY_EXPLOSION = shape(
    {
        "complete": B,
        "states": array(shape({})),
        "is_exploded": NB,
        "active_state_id": NS,
        "source": S,
        "context": shape(
            {
                "complete": B,
                "kind": {
                    "enum": ["assembly", "drawing", "other_model", "unknown", "contradictory"]
                },
                "assembly_context_admitted": B,
                "target_model": S,
                "current_model": NS,
                "current_model_type": NS,
                "window_id": {
                    "type": ["string", "null"],
                    "pattern": "^(0|[1-9][0-9]{0,9})$",
                    "description": "String.valueOf native nonnegative Java int window ID; "
                    "0 is valid; admissible range is 0..2147483647, never a default value",
                },
                "window_model": NS,
                "window_model_type": NS,
                "source": {
                    "const": "Session.GetCurrentModel/GetCurrentWindow; "
                    "Window.GetModel; Model.GetType/GetFileName"
                },
                "reason": S,
                "error": ANY,
            }
        ),
        "display_readback": shape(
            {
                "complete": B,
                "status": {"enum": ["observed", "not_checked", "incomplete"]},
                "value": NB,
                "source": {"const": "Assembly.GetIsExploded"},
                "reason": S,
                "error": ANY,
            }
        ),
        "error": ANY,
    }
)

# Project-owned error details. The pinned driver receipt schemas describe writes;
# an unresolved native read has neither an operation ID nor a fabricated receipt.
_NONNEGATIVE_SECONDS = {"type": "number", "minimum": 0}
_TIMING_STAGE = {
    **shape(
        {
            "calls": {"type": "integer", "minimum": 0},
            "seconds": _NONNEGATIVE_SECONDS,
            "self_seconds": _NONNEGATIVE_SECONDS,
        },
        ("calls", "seconds", "self_seconds"),
    ),
    "additionalProperties": False,
}
INVOCATION_TIMING = {
    **shape(
        {
            "scope": {"const": "current CLI invocation, cumulative through this observation"},
            "budget_seconds": {"type": "number", "exclusiveMinimum": 0},
            "elapsed_seconds": _NONNEGATIVE_SECONDS,
            "remaining_seconds": _NONNEGATIVE_SECONDS,
            "stages": {
                "type": "object",
                "properties": {
                    name: _TIMING_STAGE
                    for name in (
                        "startup",
                        "observation",
                        "identity_resolution",
                        "history_read",
                        "dependency_scan",
                        "planning",
                        "state_read",
                        "native_execution",
                        "execution_control",
                        "installation_copy",
                        "workflow_control",
                        "workflow_steps",
                        "verification",
                        "record_write",
                        "export",
                    )
                },
                "required": [
                    "startup",
                    "observation",
                    "identity_resolution",
                    "history_read",
                    "dependency_scan",
                    "planning",
                    "state_read",
                    "native_execution",
                    "verification",
                    "record_write",
                    "export",
                ],
                "additionalProperties": False,
            },
            "rpc": array(
                {
                    **shape(
                        {
                            "operation": {"type": "string", "minLength": 1},
                            "write": B,
                            "count": {"type": "integer", "minimum": 0},
                            "seconds": _NONNEGATIVE_SECONDS,
                        },
                        ("operation", "write", "count", "seconds"),
                    ),
                    "additionalProperties": False,
                }
            ),
            "limits": array({"type": "string", "minLength": 1}),
        },
        (
            "scope",
            "budget_seconds",
            "elapsed_seconds",
            "remaining_seconds",
            "stages",
            "rpc",
            "limits",
        ),
    ),
    "additionalProperties": False,
}
NATIVE_READ_PENDING_DETAILS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "operation": {"type": "string", "minLength": 1},
        "cli_invocation_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{32}$",
            "description": "Locally generated CLI process correlation; not a service identity.",
        },
        "diagnostic_request_id": {
            "type": "string",
            "minLength": 1,
            "description": "Optional service-provided request correlation; omitted when "
            "unavailable, including with older formal services. Never derived from the CLI "
            "invocation ID.",
        },
        "cause_code": {"type": "string", "pattern": "^E_[A-Z0-9_]+$"},
        "cause": S,
        "request_sent": B,
        "dispatch_state": {"enum": ["started", "unknown"]},
        "read_only": {"const": True},
        "automatic_retry": {"const": False},
        "next_action": {"type": "string", "minLength": 1},
        "started": {"const": True},
        "native_call_pending": {"const": True},
        "native_call_may_be_pending": {"const": True},
        "state_unknown": {"const": True},
        "http_status": INT,
        "service_code": S,
        "service_message": S,
        "service_details": shape({}),
        "_untrusted": UNTRUSTED,
        "blocked_requested_operation": {"type": "string", "minLength": 1},
        "blocked_request_dispatch_state": {"const": "not_started"},
        "pending_original_read": {"const": True},
        "pending_original_request_sent": {"const": True},
        "timing": INVOCATION_TIMING,
    },
    "required": [
        "operation",
        "cli_invocation_id",
        "cause_code",
        "cause",
        "request_sent",
        "dispatch_state",
        "read_only",
        "automatic_retry",
        "next_action",
    ],
    "additionalProperties": False,
    "allOf": [
        {
            "oneOf": [
                {
                    "properties": {"dispatch_state": {"const": "started"}},
                    "required": ["started", "native_call_pending"],
                    "not": {"required": ["native_call_may_be_pending"]},
                },
                {
                    "properties": {"dispatch_state": {"const": "unknown"}},
                    "required": ["native_call_may_be_pending", "state_unknown"],
                    "not": {
                        "anyOf": [
                            {"required": ["started"]},
                            {"required": ["native_call_pending"]},
                        ]
                    },
                },
            ]
        },
        {
            "oneOf": [
                {
                    "properties": {"request_sent": {"const": True}},
                    "not": {
                        "anyOf": [
                            {"required": [name]}
                            for name in (
                                "blocked_requested_operation",
                                "blocked_request_dispatch_state",
                                "pending_original_read",
                                "pending_original_request_sent",
                            )
                        ]
                    },
                },
                {
                    "properties": {"request_sent": {"const": False}},
                    "required": [
                        "blocked_requested_operation",
                        "blocked_request_dispatch_state",
                        "pending_original_read",
                        "pending_original_request_sent",
                    ],
                },
            ]
        },
    ],
}
NATIVE_READ_PENDING_ERROR = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **shape(
        {
            "code": {"const": "E_NATIVE_READ_PENDING"},
            "message": S,
            "details": NATIVE_READ_PENDING_DETAILS,
            "retryable": {"const": False},
        },
        ("code", "message", "details", "retryable"),
    ),
    "additionalProperties": False,
}

NATIVE_DIAGNOSTIC_DETAILS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **shape(
        {
            "operation": S,
            "cli_invocation_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
            "diagnostic_request_id": {"type": "string", "minLength": 1},
            "native_diagnostic": shape(
                {
                    "contract_version": INT,
                    "enabled": B,
                    "stopped": B,
                    "reason": S,
                    "last": shape({}),
                    "last_call": shape({}),
                    "effects": array(shape({})),
                }
            ),
            "service_code": {"const": "E_NATIVE_DIAGNOSTIC"},
            "request_sent": B,
            "automatic_retry": {"const": False},
            "next_action": S,
            "blocked_requested_operation": S,
            "blocked_request_dispatch_state": {"const": "not_started"},
            "diagnostic_original_request_sent": {"const": True},
        },
        (
            "operation",
            "cli_invocation_id",
            "service_code",
            "request_sent",
            "automatic_retry",
            "next_action",
        ),
    ),
    "not": {
        "anyOf": [
            {"required": [key]}
            for key in (
                "started",
                "native_call_pending",
                "native_call_may_be_pending",
            )
        ]
    },
}
NATIVE_DIAGNOSTIC_ERROR = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **shape(
        {
            "code": {"const": "E_NATIVE_DIAGNOSTIC"},
            "message": S,
            "retryable": {"const": False},
            "details": NATIVE_DIAGNOSTIC_DETAILS,
        },
        ("code", "message", "retryable", "details"),
    ),
    "additionalProperties": False,
}

NATIVE_READ_FAILURE_CONTEXT = shape(
    {
        "native_read_error": NATIVE_READ_PENDING_ERROR,
        "parent_operation_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "read_failure_evidence_id": S,
        "read_failure_evidence_retained": {
            "const": False,
            "description": "False means the CLI did not acknowledge a retained evidence ID. "
            "It does not prove that no evidence file exists; storage_error may report an "
            "unknown storage state.",
        },
        "read_failure_evidence_note": S,
        "record_error": {"type": "string", "pattern": "^E_[A-Z0-9_]+$"},
        "storage_error": shape(
            {"code": S, "message": S, "retryable": B, "details": shape({})},
            ("code", "message", "retryable", "details"),
        ),
        "fix": S,
        "next_action": S,
        "automatic_retry": {"const": False},
    },
    ("native_read_error",),
)
NATIVE_READ_FAILURE_CONTEXT["allOf"] = [
    {
        "if": {
            "properties": {"read_failure_evidence_retained": {"const": False}},
            "required": ["read_failure_evidence_retained"],
        },
        "then": {
            "required": ["read_failure_evidence_note", "record_error", "storage_error"],
            "not": {"required": ["read_failure_evidence_id"]},
        },
    }
]

# A confirmed write of Creo: what Creo built and the readings that checked it are Creo's text.
WRITTEN = ("result", "verification")
UNITS = shape({"system": S, "length": S, "mass": S})
MEASURE = shape({"value": NN, "mass": NN, "method": S}, ("value",))
FEATURE = shape(
    {"id": S, "name": NS, "type": S, "status": S, "number": NI, "visible": NB},
    ("id", "type", "status"),
)
VERIFICATION = shape(
    {
        "status": {"type": "string", "enum": ["passed", "failed", "incomplete"]},
        "level": {
            "type": "string",
            "enum": ["service_reply_only", "selected_postconditions_verified"],
        },
        "checks": array(shape({"check": S, "passed": B}, ("check", "passed"))),
        "observations": array(shape({"observation": S}, ("observation",))),
        "not_checked": array(S),
    },
    ("level", "checks"),
)
PROBLEM = shape({"code": S, "message": S, "fix": S}, ("code", "message", "fix"))


def listing(item: dict, **extra) -> dict:
    """A paginated list (CLI-SPEC section 8)."""
    props = {
        "items": array(item),
        "count": INT,
        "total": INT,
        "offset": INT,
        "has_more": B,
        "next_offset": INT,
        "_untrusted": UNTRUSTED,
    } | extra
    return shape(props, ("items", "count", "total", "offset", "has_more", "_untrusted"))


def written(result: dict) -> dict:
    """What a confirmed write returns: its receipt id, what Creo built, and how that was checked."""
    return shape(
        {
            "operation_id": S,
            "status": {"type": "string", "enum": ["completed"]},
            "result": result,
            "verification": VERIFICATION,
            "persisted": B,
            "_untrusted": UNTRUSTED,
        },
        ("operation_id", "status", "result", "verification", "persisted", "_untrusted"),
    )


_FALSE = {"type": "boolean", "enum": [False]}
VIEW_EXPLODED_DISPLAY_READBACK = shape(
    {
        "complete": B,
        "value": NB,
        "source": {"const": "WView2D.IsExplodedState"},
        "reason": S,
        "error": ANY,
    },
    ("complete", "value", "source"),
)
VIEW_EXPLODED_DISPLAY_READBACK["allOf"] = [
    {
        "if": {"properties": {"complete": {"const": True}}, "required": ["complete"]},
        "then": {"properties": {"value": B}},
        "else": {"properties": {"value": {"type": "null"}}},
    }
]
VIEW_IDENTITY_READBACK = shape(
    {
        "complete": B,
        **{
            key: shape(
                {
                    "complete": B,
                    "value": ANY,
                    "source": {"const": source},
                    "reason": S,
                    "error": ANY,
                },
                ("complete", "value", "source"),
            )
            for key, source in {
                "id": "WView2D.GetViewId",
                "name": "View2D.GetName",
                "sheet": "View2D.GetSheetNumber",
                "model": "View2D.GetModel/Model.GetFileName",
            }.items()
        },
    },
    ("complete", "id", "name", "sheet", "model"),
)
VIEW_NAMED_EXPLODED_STATE_REFERENCE = shape(
    {
        "complete": _FALSE,
        "status": {"const": "not_checked"},
        "value": {"type": "null"},
        "reason": S,
    },
    ("complete", "status", "value", "reason"),
)
VIEW_NATIVE_READBACK_PROPERTIES = {
    "id": {"type": ["integer", "string", "null"]},
    "view_identity_readback": VIEW_IDENTITY_READBACK,
    "exploded_display_readback": VIEW_EXPLODED_DISPLAY_READBACK,
    "named_exploded_state_reference": VIEW_NAMED_EXPLODED_STATE_REFERENCE,
}
_LAYOUT_KINDS = {"type": "string", "enum": ["views", "dimensions", "notes", "tables"]}
_LAYOUT_OBJECT = shape(
    {
        "kind": _LAYOUT_KINDS,
        "object": S,
        "source": S,
        "sheet": ANY,
        "units": ANY,
        "raw_bounds": ANY,
        "candidate_bounds": ANY,
        "predicted": B,
        "candidate_available": B,
        "reliable_coverage": B,
        "representation": S,
        "cross_time": S,
        "completeness": S,
        "snapshot_index": {"type": ["integer", "null"], "minimum": 0},
        "proposal_index": {"type": ["integer", "null"], "minimum": 0},
        "identity_source": shape(
            {
                "drawing": ANY,
                "inventory": _LAYOUT_KINDS,
                "snapshot_index": {"type": ["integer", "null"], "minimum": 0},
                "proposal_index": {"type": ["integer", "null"], "minimum": 0},
                "matched_view_indexes": array({"type": "integer", "minimum": 0}),
            }
        ),
    },
    (
        "kind",
        "object",
        "source",
        "raw_bounds",
        "candidate_bounds",
        "predicted",
        "candidate_available",
        "reliable_coverage",
    ),
)
_LAYOUT_OBJECT["allOf"] = [
    {
        "if": {"properties": {"kind": {"enum": ["dimensions"]}}, "required": ["kind"]},
        "then": {
            "properties": {
                "reliable_coverage": _FALSE,
                "representation": {"enum": ["legacy_native_aggregate"]},
                "cross_time": {"enum": ["unverified"]},
                "completeness": {"enum": ["completeness_not_independently_recorded"]},
            },
            "required": ["representation", "cross_time", "completeness"],
        },
    },
    {
        "if": {"properties": {"candidate_available": _FALSE}, "required": ["candidate_available"]},
        "then": {"properties": {"reliable_coverage": _FALSE}},
    },
    {
        "if": {
            "properties": {"candidate_available": {"enum": [True]}},
            "required": ["candidate_available"],
        },
        "then": {
            "properties": {
                "sheet": {"type": "integer", "minimum": 1},
                "units": {"type": "string", "minLength": 1},
                "candidate_bounds": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": N},
                },
            },
            "required": ["sheet", "units", "candidate_bounds"],
        },
    },
]
_LAYOUT_CANDIDATE = shape(
    {
        "kind": {
            "enum": [
                "possible_paper_edge_crossing",
                "possible_view_boundary_intersection",
                "possible_rectangle_intersection",
            ]
        },
        "objects": array(S),
        "object_kinds": array(_LAYOUT_KINDS),
        "sheet": INT,
        "units": S,
        "bounds": ANY,
        "reliable_rectangles": B,
        "meaning": S,
    },
    ("kind", "objects", "sheet", "units"),
)
_LAYOUT_CANDIDATE["allOf"] = [
    {
        "if": {
            "properties": {"object_kinds": {"contains": {"enum": ["dimensions"]}}},
            "required": ["object_kinds"],
        },
        "then": {"properties": {"reliable_rectangles": _FALSE}},
    }
]
DRAWING_LAYOUT_FEEDBACK = shape(
    {
        "scope": S,
        "source": S,
        "drawing": NS,
        "snapshot_identity": shape({"model": ANY, "origin": ANY, "modified": ANY}),
        "observation_time": NS,
        "observation_time_source": S,
        "sheets": array(
            shape({"sheet": INT, "units": ANY, "coordinate_system": S}, ("sheet", "units"))
        ),
        "objects": array(_LAYOUT_OBJECT),
        "checked": array(
            shape(
                {
                    "kind": {"enum": ["views", "notes", "tables"]},
                    "object": S,
                    "sheet": INT,
                    "units": S,
                    "source": S,
                    "predicted": B,
                },
                ("kind", "object", "sheet", "units", "source", "predicted"),
            )
        ),
        "not_checked": array(
            shape(
                {"kind": S, "reason": S, "object": ANY, "sheet": ANY, "observed": ANY},
                ("kind", "reason"),
            )
        ),
        "conflicts": array(_LAYOUT_CANDIDATE),
        "whole_layout_verified": _FALSE,
        "cross_time_protection_verified": _FALSE,
        "layout_coverage": shape({"complete": _FALSE, "meaning": S}, ("complete", "meaning")),
        "empty_conflicts_means": S,
    },
    (
        "scope",
        "source",
        "objects",
        "checked",
        "not_checked",
        "conflicts",
        "whole_layout_verified",
        "cross_time_protection_verified",
        "layout_coverage",
    ),
)
DRAWING_LAYOUT_FEEDBACK["description"] = (
    "Frozen per-sheet/unit rectangle candidates only. Invalid raw evidence is retained; "
    "R5 dimension aggregates lack independently recorded completeness and cross-time "
    "qualification. Ambiguous identities remain separate indexed unchecked rows; no last-name "
    "selection or broad proposal exclusion. Empty conflicts is never a whole-layout pass."
)

DRY_RUN = shape(
    {
        "preview": shape(
            {
                "extensions": shape(
                    {
                        "creo": shape(
                            {
                                "layout_feedback": DRAWING_LAYOUT_FEEDBACK,
                            }
                        )
                    }
                )
            }
        ),
        "confirm_token": S,
        "expires_at": S,
        "_untrusted": UNTRUSTED,
    },
    ("preview", "confirm_token", "expires_at"),
)
