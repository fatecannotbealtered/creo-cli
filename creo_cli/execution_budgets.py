"""Explicit extended drawing budgets; neither cancellation nor native recovery."""

import math

from .core import Error

PROFILE = "drawing-complete-v1"
EXTENDED_MAX_SECONDS = 1200
HEADER = "X-Creo-Cli-Execution-Profile"
CAPABILITY = "drawing_execution_budget"
SCHEMA_ID = "urn:creo-cli:execution-budget:1.0"
SCHEMA = {
    "$id": SCHEMA_ID,
    "type": "object",
    "properties": {
        "profile": {"const": PROFILE},
        "version": {"const": 1},
        "total_seconds": {"type": "number", "minimum": 300, "maximum": EXTENDED_MAX_SECONDS},
        "native_request_max_seconds": {"const": 300},
        "required_capability": {
            "type": "object",
            "properties": {"name": {"const": CAPABILITY}, "version": {"const": 1}},
            "required": ["name", "version"],
            "additionalProperties": False,
        },
        "scope": {"type": "string"},
        "automatic_extension": {"const": False},
        "cancels_started_native_work": {"const": False},
    },
    "required": [
        "profile",
        "version",
        "total_seconds",
        "native_request_max_seconds",
        "required_capability",
        "scope",
        "automatic_extension",
        "cancels_started_native_work",
    ],
    "additionalProperties": False,
}
COMMANDS = frozenset(
    {
        "drawing create",
        "drawing view add",
        "drawing view move",
        "drawing view list",
        "drawing view show",
        "drawing note add",
        "drawing note list",
        "drawing note show",
        "drawing note edit",
        "drawing table move",
        "drawing table list",
        "drawing table show",
        "drawing bom add",
        "drawing bom balloons",
        "model show",
        "model save",
        "model close",
        "artifact export",
    }
)


def validate(command, seconds):
    maximum = EXTENDED_MAX_SECONDS if command in COMMANDS else 300
    if not math.isfinite(seconds) or not 0.1 <= seconds <= maximum:
        raise Error(
            "E_USAGE",
            f"--timeout must be finite and within 0.1..{maximum} seconds for this command",
        )


def selected(command, seconds):
    validate(command, seconds)
    if seconds <= 300:
        return None
    return {
        "profile": PROFILE,
        "version": 1,
        "total_seconds": seconds,
        "native_request_max_seconds": 300,
        "required_capability": {"name": CAPABILITY, "version": 1},
        "scope": "one invocation including preparation and required independent verification",
        "automatic_extension": False,
        "cancels_started_native_work": False,
    }


def contract():
    return {
        "default_seconds": 30,
        "ordinary_max_seconds": 300,
        "ordinary_native_request_max_seconds": 120,
        "extended_max_seconds": EXTENDED_MAX_SECONDS,
        "extended_native_request_max_seconds": 300,
        "profile": PROFILE,
        "selected_profile_schema": SCHEMA_ID,
        "eligible_commands": sorted(COMMANDS),
        "activation": "explicit --timeout greater than 300; matching process-only "
        "capability before CAD",
        "confirmation": "same explicit total budget and profile as preview",
        "recovery": "not recovery; preserve stopped instances and unresolved requests",
    }
