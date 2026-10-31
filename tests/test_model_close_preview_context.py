"""Public close admission mirrors the deferred native lifecycle; controlled HTTP only."""

import os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from creo_cli import operations
from creo_cli.core import Error
from tests.test_model_close_budget_reuse import close_verifier as close_verifier
from tests.test_native_read_context import PublicCase

TARGET = "c6_dll_probe.prt"
CLOSE = ("model", "close", "--model", TARGET)


@pytest.fixture
def case():
    value = PublicCase()
    value.setUp()
    value.part(TARGET)
    value.world.active = TARGET
    try:
        yield value
    finally:
        value.doCleanups()


@pytest.mark.parametrize("other_window", (False, True))
@pytest.mark.parametrize("active_model", (None, "other.prt"))
def test_current_target_window_without_target_current_model_refuses_in_preview(
    case, other_window, active_model
):
    if other_window or active_model is not None:
        case.part("other.prt")
        if not other_window:
            case.world.models["other.prt"]["window_closed"] = True
    original = case.world.management_state

    def absent_context():
        state = original()
        # Reproduce the retained Native failure's independent window/current-model
        # disagreement without making this fixture a Native acceptance claim.
        state["active_model"] = active_model
        return state

    before = deepcopy(case.world.models)
    case.world.events.clear()
    with patch.object(case.world, "management_state", side_effect=absent_context):
        error = case.cli(*CLOSE, "--dry-run", status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["dispatch_state"] == "not_started"
    assert error["details"]["model"] == TARGET
    assert error["details"]["active_model"] == active_model
    assert "display activate" in error["details"]["fix"]
    assert "model close --dry-run" in error["details"]["fix"]
    assert "model.close" not in case.world.ops()
    assert "display.activate" not in case.world.ops()
    assert case.world.ops().count("model.management-state") == 1
    assert case.world.models == before
    assert case.cli("operation", "list")["data"]["items"] == []


def test_current_target_with_complete_context_and_existing_other_window_stays_admitted(case):
    case.part("other.prt")
    before = deepcopy(case.world.management_state())
    preview = case.cli(*CLOSE, "--dry-run")["data"]
    assert preview["preview"]["can_apply"] is True
    expected = preview["preview"]["extensions"]["creo"]
    assert expected["command"] == "model close"
    assert case.world.management_state() == before
    result = case.cli(*CLOSE, "--confirm", preview["confirm_token"])["data"]
    assert result["status"] == "completed"
    assert result["verification"]["status"] == "passed"
    assert set(case.world.models) == {"other.prt"}


def test_noncurrent_target_window_stays_admitted_with_other_model_active(case):
    case.part("other.prt")
    case.world.active = "other.prt"
    other_before = deepcopy(case.world.models["other.prt"])
    preview = case.cli(*CLOSE, "--dry-run")["data"]
    assert preview["preview"]["can_apply"] is True
    result = case.cli(*CLOSE, "--confirm", preview["confirm_token"])["data"]
    assert result["verification"]["status"] == "passed"
    assert case.world.active == "other.prt"
    assert case.world.models["other.prt"] == other_before


def test_no_target_window_stays_admitted_for_the_existing_no_window_erase_path(case):
    case.world.models[TARGET]["window_closed"] = True
    case.world.active = None
    preview = case.cli(*CLOSE, "--dry-run")["data"]
    assert preview["preview"]["can_apply"] is True
    result = case.cli(*CLOSE, "--confirm", preview["confirm_token"])["data"]
    assert result["verification"]["status"] == "passed"
    assert not case.world.models


def test_multiple_target_windows_refuse_before_confirmation(case):
    original = case.world.management_state

    def duplicate_target():
        state = original()
        state["windows"].append({"id": "second-target-window", "model": TARGET})
        return state

    case.world.events.clear()
    with patch.object(case.world, "management_state", side_effect=duplicate_target):
        error = case.cli(*CLOSE, "--dry-run", status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["dispatch_state"] == "not_started"
    assert "multiple target windows" in error["message"]
    assert "model.close" not in case.world.ops()
    assert case.world.ops().count("model.management-state") == 1


def test_context_drift_at_confirmation_retains_a_terminal_refusal_not_old_plan_success(case):
    preview = case.cli(*CLOSE, "--dry-run")["data"]
    operation_id = preview["preview"]["operation_id"]
    original = case.world.management_state

    def missing_current():
        state = original()
        state["active_model"] = None
        return state

    case.world.events.clear()
    with patch.object(case.world, "management_state", side_effect=missing_current):
        error = case.cli(*CLOSE, "--confirm", preview["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["dispatch_state"] == "not_started"
    attempt = error["details"]["confirmation_attempt"]
    assert attempt["terminal"] is True
    assert attempt["dispatch_state"] == "not_started"
    assert attempt["status"] == "rejected_before_dispatch"
    assert "model.close" not in case.world.ops()
    with patch.dict(os.environ, case.env, clear=True):
        original_plan = operations.get(operation_id)
        attempts = operations.confirmation_attempts(operation_id)
    assert original_plan["status"] == "planned"
    assert original_plan["started_at"] is None and original_plan["driver_receipt"] is None
    assert len(attempts) == 1 and attempts[0]["attempt_id"] == attempt["attempt_id"]


def test_failure_state_a_is_retained_without_becoming_success_or_an_extra_read(close_verifier):
    c = close_verifier
    assert c.p._failure_observation_guard(c.p, c.client) is True
    after = c.p.observe(c.client)
    assert c.p._retain_failure_observation(c.p, c.client, after) is True
    assert c.p._settled_observation(c.p, c.client) == after
    assert c.p._settled_observation(c.p, c.client) is not after
    assert c.p.observe(c.client) == after
    assert c.client.op.call_count == 2  # one plan-before, one complete failure A
    assert c.p.verified_observation is None
    assert c.p._verified_observation_guard(c.p, c.client) is False


@pytest.mark.parametrize("field", ("request", "binding", "preview", "arguments", "before"))
def test_failure_state_a_cannot_survive_changed_intent(close_verifier, field):
    c = close_verifier
    after = c.p.observe(c.client)
    assert c.p._retain_failure_observation(c.p, c.client, after) is True
    getattr(c.p, field)["controlled_change"] = True
    assert c.p._failure_observation_guard(c.p, c.client) is False
    assert c.p._settled_observation(c.p, c.client) is None
    with pytest.raises(Error, match="no complete model-close observation"):
        c.p.observe(c.client)
    assert c.client.op.call_count == 2


def test_failure_alias_mutation_refuses_reuse_instead_of_reading_b(close_verifier):
    c = close_verifier
    after = c.p.observe(c.client)
    assert c.p._retain_failure_observation(c.p, c.client, after) is True
    after["models"][0]["modified"] = True
    assert c.p._settled_observation(c.p, c.client) is None
    with pytest.raises(Error, match="no complete model-close observation"):
        c.p.observe(c.client)
    assert c.client.op.call_count == 2


@pytest.mark.parametrize("variant", ("other-plan", "other-client", "copied-reading"))
def test_failure_retention_requires_the_exact_plan_client_and_fresh_reading(
    close_verifier, variant
):
    c = close_verifier
    after = c.p.observe(c.client)
    planned, client, observed = c.p, c.client, after
    if variant == "other-plan":
        planned = deepcopy(c.p)
    elif variant == "other-client":
        client = SimpleNamespace(op=c.client.op, require_capability=c.client.require_capability)
    else:
        observed = deepcopy(after)
    assert c.p._retain_failure_observation(planned, client, observed) is False
    assert c.p._settled_observation(c.p, c.client) is None
    with pytest.raises(Error, match="no complete model-close observation"):
        c.p.observe(c.client)
    assert c.client.op.call_count == 2


def test_failure_a_cannot_be_overwritten_and_does_not_alias_its_returned_copy(close_verifier):
    c = close_verifier
    after = c.p.observe(c.client)
    expected = deepcopy(after)
    assert c.p._retain_failure_observation(c.p, c.client, after) is True
    assert c.p._retain_failure_observation(c.p, c.client, {"completed": False}) is False
    returned = c.p._settled_observation(c.p, c.client)
    returned["models"][0]["modified"] = True
    assert c.p._settled_observation(c.p, c.client) == expected
    assert c.p.verified_observation is None
    assert c.client.op.call_count == 2


def test_late_verification_cannot_replace_settled_failure_a_with_a_new_read(close_verifier):
    c = close_verifier
    after = c.p.observe(c.client)
    expected = deepcopy(after)
    assert c.p._retain_failure_observation(c.p, c.client, after) is True
    with pytest.raises(Error, match="failure observation is already settled"):
        c.p.verify(c.client, {"model": "close.drw", "erased": True})
    assert c.p._settled_observation(c.p, c.client) == expected
    assert c.p.verified_observation is None
    assert c.p._verified_observation_guard(c.p, c.client) is False
    assert c.client.op.call_count == 2
