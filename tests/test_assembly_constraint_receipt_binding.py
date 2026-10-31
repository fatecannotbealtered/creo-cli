"""Controlled HTTP receipt counterexamples; these are not native Creo failures."""

from copy import copy, deepcopy
from types import SimpleNamespace

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli import driver
from creo_cli.core import Error, digest
from tests.fixture import Refused
from tests.test_assembly_constraint_policy import (
    protected_snapshot,
    state_request,
    state_row,
    successful_edit,
)
from tests.test_assembly_constraint_process import GETTER, SETTER, ConstraintWorld, ProcessHarness


class ReceiptWorld(ConstraintWorld):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setter_attempts = 0
        self.native_reads = []

    def op(self, op, q):
        if op == GETTER and self.setter_attempts:
            if self.mode in ("success_read_error", "dirty_settle_read_error"):
                raise Refused(
                    "E_CREO", "controlled completed readback error", stage="constraints_get"
                )
        if op == SETTER:
            self.setter_attempts += 1
            if self.mode in (
                "dirty_owner_error",
                "dirty_member_error",
                "unknown_modified_error",
                "missing_modified_error",
                "dirty_settle_read_error",
            ):
                model = self.state["model"] if self.mode != "dirty_member_error" else "slider.prt"
                self.models[model]["modified"] = True
                if self.mode == "unknown_modified_error":
                    self.models[model]["modified"] = None
                raise Refused(
                    "E_CREO",
                    "controlled setter failure after model dirty-state change",
                    stage="model_constraints_set",
                    model_state={"model": self.state["model"], "modified": True},
                )
        result = super().op(op, q)
        if (
            op == "model.show"
            and self.setter_attempts
            and self.mode in ("missing_modified_error", "success_modified_missing")
        ):
            result.pop("modified", None)
        if op == GETTER and self.writes:
            if self.mode == "second_read_pose_drift" and self.reads_after_write >= 2:
                state_row(result, self.ids[3])["component_path_transform"]["origin"][1] += 0.01
            self.native_reads.append(deepcopy(result))
        return result


@pytest.fixture
def receipt_harness(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.test_assembly_constraint_process.ConstraintWorld", ReceiptWorld)
    h = ProcessHarness(tmp_path)
    try:
        yield h
    finally:
        h.close()


def test_process_verified_complete_observation_is_the_effect_observation(receipt_harness):
    h = receipt_harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = "second_read_pose_drift"
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.setter_attempts == 1
    receipt = answer["data"]["receipt"] if answer["ok"] else answer["error"]["details"]["receipt"]
    effects = receipt["extensions"]["creo"]["effects_readback"]["after"]
    checked = receipt["extensions"]["creo"]["domain_result"]["independent_state"]
    full_checked = receipt["extensions"]["creo"]["domain_result"]["independent_observation"]
    assert effects["native"] == checked
    assert effects == full_checked
    assert receipt["outcome"]["verification"]["extensions"]["creo"]["observation_sha256"] == digest(
        effects
    )
    assert h.world.reads_after_write == 1
    assert receipt["outcome"]["verification"]["status"] == "passed"


@pytest.mark.parametrize("mode", ["dirty_owner_error", "dirty_member_error"])
def test_process_dirty_only_legal_native_error_is_unsaved(receipt_harness, mode):
    h = receipt_harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = mode
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    receipt = answer["error"]["details"]["receipt"]
    assert receipt["extensions"]["creo"]["legacy_status"] == "partial"
    assert receipt["outcome"]["change"] == "not_applied"
    assert receipt["outcome"]["persistence"] == "unsaved"
    assert h.world.setter_attempts == 1 and h.world.writes == 0
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.setter_attempts == 1


@pytest.mark.parametrize("mode", ["unknown_modified_error", "missing_modified_error"])
def test_process_unknown_modified_after_native_error_is_honest(receipt_harness, mode):
    h = receipt_harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = mode
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    receipt = answer["error"]["details"]["receipt"]
    assert receipt["outcome"]["persistence"] == "unknown"
    assert h.world.setter_attempts == 1


def test_process_success_with_missing_modified_does_not_claim_saved_state(receipt_harness):
    h = receipt_harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = "success_modified_missing"
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    assert answer["error"]["code"] == "E_OUTCOME_UNKNOWN"
    assert answer["error"]["details"]["receipt"]["outcome"]["persistence"] == "unknown"
    assert h.world.reads_after_write == 1


@pytest.mark.parametrize("mode", ["success_read_error", "dirty_settle_read_error"])
def test_process_readback_failure_cannot_invent_unchanged_or_reuse_passed(receipt_harness, mode):
    h = receipt_harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = mode
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    receipt = answer["error"]["details"]["receipt"]
    assert receipt["outcome"]["persistence"] == "unknown"
    assert receipt["outcome"]["change"] == "unknown"
    assert receipt["outcome"]["verification"]["status"] != "passed"
    first = next(i for i, r in enumerate(h.world.journal) if r["op"] == SETTER)
    assert [r["op"] for r in h.world.journal[first:]] == [SETTER, GETTER]
    assert h.world.setter_attempts == 1


@pytest.mark.parametrize(
    "tamper", ["copied_plan", "other_client", "intent", "observation", "new_plan"]
)
def test_complete_verified_observation_authority_cannot_cross_plan_client_or_intent(
    monkeypatch, tamper
):
    before, after, _ = successful_edit()
    observations = [protected_snapshot(before), protected_snapshot(after)]
    calls = []

    def observe(c, name):
        calls.append((c, name))
        return deepcopy(observations[min(len(calls) - 1, 1)])

    monkeypatch.setattr(policy, "snapshot", observe)
    client = SimpleNamespace()
    p = policy._plan(
        client,
        {"component": "83"},
        {"name": before["model"], "request": state_request(before)},
    )
    _, verification = p.verify(client, {"controlled": "setter reply"})
    assert all(c["passed"] is True for c in verification["checks"])
    assert driver._effect_observation(p, client) == observations[1]
    planned, checked_client = p, client
    if tamper == "copied_plan":
        planned = copy(p)
    elif tamper == "other_client":
        checked_client = SimpleNamespace()
    elif tamper == "intent":
        p.binding["constraints_intent"]["affected_occurrences"] = ["83"]
    elif tamper == "observation":
        p.verified_observation["native"]["components"][-1]["component_path_transform"]["origin"][
            1
        ] += 1
    elif tamper == "new_plan":
        planned = copy(p)
        planned.verified_observation = deepcopy(p.verified_observation)
        planned._verified_observation_guard = None
    with pytest.raises(Error) as caught:
        driver._effect_observation(planned, checked_client)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert len(calls) == 2  # Refusal never reads a fresh B and never borrows A's passed result.
