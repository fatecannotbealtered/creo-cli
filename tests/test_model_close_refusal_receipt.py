"""Returned close read-stage refusals: real HTTP peer, no Creo/native faults.

The reply contract is taken from C6's preserved Native close refusal. The current
preview now rejects its known missing context, so the HTTP peer injects the same
returned read-stage failure after an otherwise admissible preview. This tests the
receipt boundary without disabling the new preview protection.
"""

from copy import deepcopy
from unittest.mock import patch

import pytest

from creo_cli import engine
from creo_cli.core import CODES
from tests.test_native_read_context import PublicCase

TARGET = "c6_dll_probe.prt"
CLOSE = ("model", "close", "--model", TARGET)
NATIVE_REFUSAL = {
    "code": "E_VERIFY_INCOMPLETE",
    "message": "activate the target's complete context before closing its current window",
    "stage": "model_close_stage",
    "started": False,
    "sdk_read_entered": True,
}


@pytest.fixture
def case():
    value = PublicCase()
    value.setUp()
    value.part(TARGET)
    value.world.active = TARGET
    original = value.world.management_state

    def typed_management():
        state = original()
        # Match the production SDK's numeric relation identity, rather than the
        # general fixture's stringified Python object ID.
        for row in state["models"]:
            row["relation_id"] = int(row["relation_id"])
        return state

    value.world.management_state = typed_management
    try:
        yield value
    finally:
        value.doCleanups()


def refuse_at_close(case, *, fault=None, code="E_VERIFY_INCOMPLETE", flags=None):
    original = case.world.handle
    phase = {"attempts": 0, "after_reads": 0}
    refusal = deepcopy(NATIVE_REFUSAL)
    refusal["code"] = code
    refusal.update(flags or {})

    def handle(op, request):
        if op == "model.close":
            case.world.events.append((op, deepcopy(request)))
            phase["attempts"] += 1
            if fault == "dirty":
                case.world.models[TARGET]["modified"] = True
            elif fault == "changed":
                case.world.models[TARGET]["window_closed"] = True
            return {"ok": False, "op": op, "error": refusal, "elapsed_ms": 1}, True
        if op == "model.management-state" and phase["attempts"]:
            phase["after_reads"] += 1
            if fault == "read_error":
                case.world.events.append((op, deepcopy(request)))
                return {
                    "ok": False,
                    "op": op,
                    "error": {"code": "E_CREO", "message": "controlled completed getter failure"},
                }, True
            data, handled = original(op, request)
            if fault == "missing_modified":
                data["models"][0].pop("modified")
            elif fault == "missing_identity":
                data["models"][0].pop("version_stamp")
            elif fault == "unknown_origin":
                data["models"][0]["origin_readback"]["complete"] = False
            elif fault == "unknown_family":
                data["models"][0]["family"]["complete"] = False
            return data, handled
        return original(op, request)

    case.world.handle = handle
    return phase


def confirmation(case, *, status=1):
    preview = case.cli(*CLOSE, "--dry-run")["data"]
    case.world.events.clear()
    result = case.cli(*CLOSE, "--confirm", preview["confirm_token"], status=status)
    return preview, result["error"]


def test_http_returned_read_refusal_is_not_applied_and_still_unverified(case):
    phase = refuse_at_close(case)
    preview, error = confirmation(case)
    receipt = error["details"]["receipt"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["state_after"] == "observed_unchanged"
    assert error["details"]["receipt_status"] == "failed_unchanged"
    assert receipt["outcome"]["execution"] == "failed"
    assert receipt["outcome"]["change"] == "not_applied"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    assert receipt["outcome"]["verification"]["checks"] == []
    assert receipt["changed_items"] == []
    ext = receipt["extensions"]["creo"]
    assert ext["native_close_read_refusal"]["observation_bound"] is True
    a = ext["effects_readback"]["after"]
    assert a == ext["effects_readback"]["before"]
    assert a == ext["domain_result"]["state_after"]
    assert a["models"][0]["modified"] is False
    assert phase == {"attempts": 1, "after_reads": 1}
    assert TARGET in case.world.models
    # The failed confirmation is terminal and cannot replay the returned call.
    case.cli(*CLOSE, "--confirm", preview["confirm_token"], status=6)
    assert phase["attempts"] == 1


@pytest.mark.parametrize(
    "fault",
    (
        "dirty",
        "changed",
        "read_error",
        "missing_modified",
        "missing_identity",
        "unknown_origin",
        "unknown_family",
    ),
)
def test_http_unproved_or_changed_refusal_is_unknown_not_applied(case, fault):
    phase = refuse_at_close(case, fault=fault)
    _, error = confirmation(case, status=CODES["E_OUTCOME_UNKNOWN"][0])
    receipt = error["details"]["receipt"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert receipt["outcome"]["change"] == "unknown"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    assert receipt["extensions"]["creo"]["legacy_status"] == "unknown"
    assert receipt["outcome"]["persistence"] != "unchanged"
    assert phase == {"attempts": 1, "after_reads": 1}
    assert TARGET in case.world.models
    if fault == "dirty":
        assert case.world.models[TARGET]["modified"] is True
        assert error["details"]["state_after"] == "observed_changed"


def test_other_native_error_keeps_its_existing_error_classification(case):
    phase = refuse_at_close(case, code="E_CREO")
    _, error = confirmation(case)
    assert error["code"] == "E_NATIVE_FAILURE"
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert "native_close_read_refusal" not in error["details"]["receipt"]["extensions"]["creo"]
    assert phase["attempts"] == 1


@pytest.mark.parametrize("fault", ("intent", "alias"))
def test_late_loss_of_failure_a_binding_demotes_change_to_unknown(case, fault):
    phase = refuse_at_close(case)
    original = engine.settle

    def settle_then_tamper(run, error, client, plan):
        captured = {}
        original_retainer = plan._retain_failure_observation

        def retain(planned, c, after):
            captured["a"] = after
            return original_retainer(planned, c, after)

        plan._retain_failure_observation = retain
        result = original(run, error, client, plan)
        assert run["status"] == "failed_unchanged"
        if fault == "intent":
            plan.request["controlled_late_change"] = True
        else:
            # The slot is alias-guarded. Mutate the exact A that settlement just
            # retained; the old snapshot may not become a later effect snapshot.
            captured["a"]["models"][0]["modified"] = True
        return result

    with patch.object(engine, "settle", side_effect=settle_then_tamper):
        _, error = confirmation(case, status=CODES["E_OUTCOME_UNKNOWN"][0])
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    receipt = error["details"]["receipt"]
    assert receipt["outcome"]["change"] == "unknown"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    assert receipt["extensions"]["creo"]["legacy_status"] == "unknown"
    assert phase == {"attempts": 1, "after_reads": 1}
