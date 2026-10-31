"""Pure-data recovery context for an unresolved native getter; never samples CAD."""

from __future__ import annotations

from copy import deepcopy

from .core import Error

STOP_ACTION = (
    "stop further CAD dispatch to this Creo instance; retain the original read and parent "
    "write records. Only local operation show, process-only health and OS observations "
    "are safe immediate checks; they do not prove that the getter ended. Independently "
    "confirm the original call and instance state before engineering read-back or evidence "
    "registration. Do not replay the setter, create a new Client, or restart the CLI as recovery"
)


def error_record(exc: Error) -> dict:
    """Retain the actual error fields without payload defaults or invented correlations."""
    return {
        "code": exc.code,
        "message": exc.message,
        "retryable": exc.retryable,
        "details": deepcopy(exc.details),
    }


def pending_error(value) -> dict | None:
    """Find an already captured error through the known receipt/workflow data wrappers."""
    if isinstance(value, Error):
        nested = pending_error(value.details.get("native_read_error"))
        return nested or (
            error_record(value)
            if value.code == "E_NATIVE_READ_PENDING"
            else pending_error(value.details)
        )
    if not isinstance(value, dict):
        return None
    # Prefer the first actual read over a later guard refusal or parent wrapper.
    for key in ("driver_native_read_error", "native_read_error"):
        if isinstance(value.get(key), dict):
            found = pending_error(value[key])
            if found:
                return found
    if value.get("code") == "E_NATIVE_READ_PENDING" and isinstance(value.get("details"), dict):
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
        found = pending_error(value.get(key))
        if found:
            return found
    return None


def capture(run: dict, exc: Error) -> dict | None:
    pending = pending_error(run) or pending_error(exc)
    if pending:
        run.setdefault("driver_native_read_error", deepcopy(pending))
    return pending


def capture_client(run: dict, client) -> dict | None:
    """Read only the transport's first saved error, even if a leaf reduced it to a code."""
    original = getattr(client, "_native_read_pending", None)
    return capture(run, original) if isinstance(original, Error) else pending_error(run)


def details(pending: dict | None) -> dict:
    return (
        {
            "native_read_error": deepcopy(pending),
            "next_action": STOP_ACTION,
            "fix": STOP_ACTION,
            "automatic_retry": False,
        }
        if pending
        else {}
    )


def annotate_receipt(receipt: dict, pending: dict | None) -> dict:
    if pending:
        receipt.setdefault("extensions", {}).setdefault("creo", {})["native_read_error"] = deepcopy(
            pending
        )
        receipt["recovery"] = {"action": "inspect", "reason": STOP_ACTION, "supported": True}
    return receipt
