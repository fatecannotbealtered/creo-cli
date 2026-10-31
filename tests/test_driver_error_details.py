"""Driver error diagnostics must preserve dispatch and recovery information."""

import pytest

from creo_cli.core import Error


@pytest.mark.parametrize("code", ["E_USAGE", "E_VALIDATION", "E_CONFIRMATION_REQUIRED"])
def test_local_input_errors_have_problem_and_no_native_dispatch(code):
    details = Error(code, "invalid input", {"path": "units"}).payload()["details"]
    assert details["dispatch_state"] == "not_started"
    assert details["problem"] in ("invalid_value", "confirmation_required")
    assert details["parameter"] == "units" and details["expected"]
    assert details["next_action"]


@pytest.mark.parametrize(
    "reason,conflict",
    [
        ("state_changed", "state_drift"),
        ("expired", "token_expired"),
        ("already_used", "token_used"),
        ("arguments_changed", "token_mismatch"),
        ("policy_changed", "scope_changed"),
    ],
)
def test_token_refusals_keep_domain_reason_and_public_conflict(reason, conflict):
    details = Error("E_CONFLICT", "refused", {"reason": reason}).payload()["details"]
    assert details["reason"] == reason and details["conflict"] == conflict
    assert details["dispatch_state"] == "not_started"


def test_operation_failure_is_never_defaulted_to_not_started():
    details = Error("E_OUTCOME_UNKNOWN", "reply lost", {"operation_id": "abc"}).payload()["details"]
    assert details["dispatch_state"] == "unknown"
    assert details["lookup"] == ["operation", "show", "--id", "abc"]
    assert "do not repeat" in details["next_action"]


def test_explicit_dispatch_state_survives_output_formatting():
    original = {"operation_id": "abc", "dispatch_state": "dispatched", "next_action": "inspect"}
    assert Error("E_PARTIAL", "changed", original).payload()["details"] == original
