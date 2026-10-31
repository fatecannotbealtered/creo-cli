"""Pure-data retention of a service diagnostic stop; never calls a CAD getter."""

from __future__ import annotations

from copy import deepcopy

from .core import Error
from .native_read_recovery import error_record

STOP_ACTION = (
    "stop further CAD dispatch to this Creo instance and preserve the diagnostic journal, "
    "created object identities and original receipts. Only local operation show, process-only "
    "health and OS observations are immediate checks; none proves native health or permits "
    "query, resolve or another CAD getter. Independently establish the stopped call and instance "
    "state before engineering read-back or registration. A new Client, CLI restart or repaired "
    "diagnostic directory is not recovery; never replay the setter"
)


def diagnostic_error(value) -> dict | None:
    if isinstance(value, Error):
        nested = diagnostic_error(value.details.get("native_diagnostic_error"))
        return nested or (
            error_record(value)
            if value.code == "E_NATIVE_DIAGNOSTIC"
            else diagnostic_error(value.details)
        )
    if not isinstance(value, dict):
        return None
    for key in ("driver_native_diagnostic_error", "native_diagnostic_error"):
        found = diagnostic_error(value.get(key))
        if found:
            return found
    if value.get("code") == "E_NATIVE_DIAGNOSTIC" and isinstance(value.get("details"), dict):
        return deepcopy(value)
    for key in (
        "details",
        "driver_effect_readback_error",
        "driver_receipt",
        "receipt",
        "extensions",
        "creo",
        "verification",
        "outcome",
        "workflow_final_validation",
        "final_validation",
    ):
        found = diagnostic_error(value.get(key))
        if found:
            return found
    return None


def capture(run: dict, exc: Error) -> dict | None:
    stopped = diagnostic_error(run) or diagnostic_error(exc)
    if stopped:
        run.setdefault("driver_native_diagnostic_error", deepcopy(stopped))
    return stopped


def capture_client(run: dict, client) -> dict | None:
    original = getattr(client, "_native_diagnostic_stop", None)
    return capture(run, original) if isinstance(original, Error) else diagnostic_error(run)


def capture_effects(run: dict, stopped: dict | None, operation: str, target: str) -> bool:
    """Accept only a versioned, request-correlated, actual-target setter completion fact."""
    if not stopped:
        return False
    context = stopped.get("details", {})
    evidence = context.get("native_diagnostic", {})
    request_id = context.get("diagnostic_request_id")
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("contract_version")) is not int
        or evidence.get("contract_version") != 1
        or evidence.get("enabled") is not True
        or evidence.get("stopped") is not True
        or not request_id
    ):
        return False
    effects = evidence.get("effects")
    if not isinstance(effects, list) or any(not isinstance(event, dict) for event in effects):
        return False
    for event in effects:
        facts = event.get("facts")
        if (
            event.get("effect") == "native_write_returned"
            and event.get("event") == "effect"
            and type(event.get("effect_contract_version")) is int
            and event.get("effect_contract_version") == 1
            and event.get("diagnostic_request_id") == request_id
            and event.get("operation") == operation
            and isinstance(facts, dict)
            and facts.get("operation") == operation
            and facts.get("target", facts.get("actual_drawing")) == target
        ):
            run["native_write_returned"] = deepcopy(event)
            return True
    return False


def details(stopped: dict | None) -> dict:
    return (
        {
            "native_diagnostic_error": deepcopy(stopped),
            "next_action": STOP_ACTION,
            "fix": STOP_ACTION,
            "automatic_retry": False,
        }
        if stopped
        else {}
    )


def annotate_receipt(receipt: dict, stopped: dict | None) -> dict:
    if stopped:
        receipt.setdefault("extensions", {}).setdefault("creo", {})["native_diagnostic_error"] = (
            deepcopy(stopped)
        )
        receipt["recovery"] = {"action": "inspect", "reason": STOP_ACTION, "supported": True}
    return receipt
