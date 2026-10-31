"""Binding transitions under controlled complete observations, never native qualification."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from creo_cli import appearance, driver, engine
from creo_cli.core import Error
from tests.test_native_display_contract import bind_source, cosmetic, intended, planned, repeated


def default_before():
    before = repeated()
    before["colors"]["shared.prt"]["appearance"] = None
    bind_source(before["colors"]["shared.prt"])
    return before


def original_request(before, *, restore=False, value=None):
    request = intended(before)
    request.pop("reference_action")
    request.pop("reference_replacement_authorized")
    if restore:
        request.pop("rgb")
        request["appearance"] = deepcopy(value)
    return request


def created_after(before, *, name="native_initial_reference_7"):
    after = deepcopy(before)
    after["models"]["shared.prt"]["modified"] = True
    after["physical_materials"]["shared.prt"]["modified"]["value"] = True
    state = after["colors"]["shared.prt"]
    state["modified"] = True
    state["appearance"] = cosmetic(intended(before)["rgb"]) | {"name": name}
    bind_source(state)
    return after


def verify(monkeypatch, before, after, *, restore=False, value=None):
    client, plan = planned(
        monkeypatch, before, original_request(before, restore=restore, value=value), restore
    )
    snapshots = Mock(return_value=deepcopy(after))
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    result, verification = plan.verify(client, {})
    return client, plan, snapshots, result, verification


def test_first_null_preview_binds_creation_without_predicting_a_native_id(monkeypatch):
    before = default_before()
    _, plan = planned(monkeypatch, before, original_request(before))
    assert plan.preview["reference_transition"] == "create_initial_binding"
    assert plan.request["reference_transition"] == "create_initial_binding"
    assert plan.preview["intent"]["reference_transition"] == "create_initial_binding"
    assert plan.preview["reference_before"]["native_id"] is None
    assert plan.preview["reference_after"]["native_id"] is None
    assert plan.preview["reference_after"]["allocation_status"] == "pending_native_allocation"
    assert "create and bind the first" in plan.preview["reference_semantics"]
    assert "native_reference_identity" not in plan.preview["protected"]
    assert "initial_native_reference_and_source_binding" in plan.preview["protected"]
    wire = plan.send()
    assert "reference_transition" not in wire
    assert wire["reference_action"] == "preserve"
    assert wire["expected_before"] == before["colors"]["shared.prt"]


def test_valid_initial_binding_is_verified_and_effect_uses_exactly_that_a(monkeypatch):
    before = default_before()
    after = created_after(before)
    client, plan, snapshots, result, verification = verify(monkeypatch, before, after)
    assert engine.verification_status(verification) == "passed"
    assert result["reference_transition"] == "create_initial_binding"
    assert result["reference_after"]["native_id"] == "native_initial_reference_7"
    assert result["reference_after"]["whole_source_binding_observed"] is True
    assert driver._effect_observation(plan, client) == after
    assert snapshots.call_count == 1
    result["after"]["models"]["other.prt"]["modified"] = True
    assert driver._effect_observation(plan, client) == after
    plan.request["reference_transition"] = "preserve"
    assert driver._effect_observation(plan, client) is None


@pytest.mark.parametrize("actual_name", ["sample", "SAMPLE"])
def test_initial_reference_cannot_alias_another_loaded_source(monkeypatch, actual_name):
    before = default_before()
    after = created_after(before, name=actual_name)
    client, plan, snapshots, result, verification = verify(monkeypatch, before, after)
    checks = {row["check"]: row["passed"] for row in verification["checks"]}
    assert checks["requested_native_appearance"] is True
    assert checks["allocated_reference_distinct_from_other_loaded_sources"] is False
    assert engine.verification_status(verification) != "passed"
    assert driver._effect_observation(plan, client) is None
    assert plan._settled_observation(plan, client) == result["after"] == after
    assert snapshots.call_count == 1


def test_unnamed_other_loaded_reference_refuses_creation_before_dispatch(monkeypatch):
    before = default_before()
    before["colors"]["other.prt"]["appearance"]["name"] = None
    bind_source(before["colors"]["other.prt"])
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, original_request(before))
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


def test_old_service_without_unique_reference_capability_refuses_before_dispatch(monkeypatch):
    before = default_before()
    client = Mock(spec=["require_capability"])

    def require(name, version):
        if name == "source_part_appearance_unique_reference":
            raise Error("E_UNSUPPORTED", "controlled older service")

    client.require_capability.side_effect = require
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(before))
    monkeypatch.setattr(engine, "session", lambda c: {"models": list(before["models"])})
    monkeypatch.setattr(engine, "store_directory", lambda *args: None)
    with pytest.raises(Error) as caught:
        appearance.plan(
            client,
            {},
            {"model": "shared.prt", "request": original_request(before), "restore": False},
        )
    assert caught.value.code == "E_UNSUPPORTED"


@pytest.mark.parametrize(
    "drift",
    (
        "null_id",
        "empty_id",
        "blank_id",
        "zero_assignments",
        "duplicate_assignments",
        "wrong_visible_selection",
        "wrong_assignment_selection",
        "wrong_selection_type",
        "wrong_assignment_id",
        "wrong_assignment_appearance",
        "wrong_source_context",
        "wrong_source_type",
    ),
)
def test_initial_rgb_match_cannot_qualify_an_invalid_native_binding(monkeypatch, drift):
    before = default_before()
    after = created_after(before)
    state = after["colors"]["shared.prt"]
    if drift in {"null_id", "empty_id", "blank_id"}:
        state["appearance"]["name"] = {"null_id": None, "empty_id": "", "blank_id": "  "}[drift]
        bind_source(state)
    elif drift == "zero_assignments":
        state["assignments"] = []
    elif drift == "duplicate_assignments":
        state["assignments"].append(deepcopy(state["assignments"][0]))
    elif drift == "wrong_visible_selection":
        state["selection_model"] = "other.prt"
    elif drift == "wrong_assignment_selection":
        state["assignments"][0]["selection_model"] = "other.prt"
    elif drift == "wrong_selection_type":
        state["assignments"][0]["selection_model_type"] = "assembly"
    elif drift == "wrong_assignment_id":
        state["assignments"][0]["item_id"] = "18"
    elif drift == "wrong_assignment_appearance":
        state["assignments"][0]["appearance"]["name"] = "different_reference"
    elif drift == "wrong_source_context":
        after["models"]["shared.prt"]["origin"] = "D:/unrelated/shared.prt.3"
    else:
        after["models"]["shared.prt"]["type"] = "assembly"
    client, plan, snapshots, result, verification = verify(monkeypatch, before, after)
    assert (
        next(
            row["passed"]
            for row in verification["checks"]
            if row["check"] == "requested_native_appearance"
        )
        is True
    )
    assert engine.verification_status(verification) != "passed"
    assert driver._effect_observation(plan, client) is None
    assert plan._settled_observation(plan, client) == result["after"] == after
    assert snapshots.call_count == 1


@pytest.mark.parametrize("field", ("selection_model", "selection_model_type"))
def test_first_creation_needs_an_independently_identified_absent_binding(monkeypatch, field):
    before = default_before()
    before["colors"]["shared.prt"].pop(field)
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, original_request(before))
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("was_default", (False, True))
def test_null_restore_explicitly_removes_the_model_override(monkeypatch, was_default):
    before = default_before() if was_default else repeated()
    after = deepcopy(before)
    after["colors"]["shared.prt"]["appearance"] = None
    bind_source(after["colors"]["shared.prt"])
    client, plan, snapshots, result, verification = verify(monkeypatch, before, after, restore=True)
    assert plan.preview["reference_transition"] == "restore_native_default"
    assert plan.preview["reference_after"]["native_id"] is None
    assert plan.preview["reference_after"]["allocation_status"] == "no_model_override"
    assert "remove the target model override" in plan.preview["reference_semantics"]
    assert result["reference_transition"] == "restore_native_default"
    assert result["reference_after"]["native_id"] is None
    assert result["reference_after"]["whole_source_binding_observed"] is False
    assert engine.verification_status(verification) == "passed"
    assert driver._effect_observation(plan, client) == after
    assert snapshots.call_count == 1


@pytest.mark.parametrize("drift", ("wrong_selection", "wrong_assignment_selection", "stale_id"))
def test_default_restore_requires_observed_absence_not_just_null_visible_name(monkeypatch, drift):
    before = repeated()
    after = deepcopy(before)
    state = after["colors"]["shared.prt"]
    state["appearance"] = None
    bind_source(state)
    if drift == "wrong_selection":
        state["selection_model"] = "other.prt"
    else:
        holder = deepcopy(before["colors"]["shared.prt"]["assignments"][0])
        holder["appearance"] = None if drift == "wrong_assignment_selection" else cosmetic()
        holder["selection_model"] = (
            "other.prt" if drift == "wrong_assignment_selection" else "shared.prt"
        )
        state["assignments"] = [holder]
    client, plan, _, _, verification = verify(monkeypatch, before, after, restore=True)
    assert engine.verification_status(verification) != "passed"
    assert driver._effect_observation(plan, client) is None


def test_creation_first_read_failure_and_foreign_client_do_not_authorize_a_second_read(
    monkeypatch,
):
    before = default_before()
    client, plan = planned(monkeypatch, before, original_request(before))
    snapshots = Mock(side_effect=Error("E_VERIFY_INCOMPLETE", "controlled first read failure"))
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    with pytest.raises(Error):
        plan.verify(object(), {})
    snapshots.assert_not_called()
    with pytest.raises(Error):
        plan.verify(client, {})
    with pytest.raises(Error):
        plan.observe(client)
    assert snapshots.call_count == 1
    assert driver._effect_observation(plan, client) is None


def test_setter_failure_cannot_promote_an_initial_binding_observation_to_success(monkeypatch):
    before = default_before()
    client, plan = planned(monkeypatch, before, original_request(before))
    after = created_after(before)
    snapshots = Mock(return_value=deepcopy(after))
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    settled = plan.observe(client)
    assert plan.failure_unchanged(settled) is False
    assert driver._effect_observation(plan, client) is None
    with pytest.raises(Error):
        plan.verify(client, {})
    assert snapshots.call_count == 1
    assert driver._effect_observation(plan, client) is None


def test_restore_nonnull_from_default_observes_allocated_id_not_historical_text(monkeypatch):
    before = default_before()
    requested = cosmetic() | {"name": "historical_source_reference"}
    after = created_after(before)
    after["colors"]["shared.prt"]["appearance"] = requested | {"name": "new_native_37"}
    bind_source(after["colors"]["shared.prt"])
    client, plan, _, result, verification = verify(
        monkeypatch, before, after, restore=True, value=requested
    )
    assert plan.preview["reference_transition"] == "create_initial_binding"
    assert plan.request["appearance"]["name"] == requested["name"]
    assert plan.preview["intent"]["appearance"]["name"] == requested["name"]
    assert plan.send()["appearance"]["name"] == ""
    assert engine.verification_status(verification) == "passed"
    assert result["reference_after"]["native_id"] == "new_native_37"
    assert driver._effect_observation(plan, client) == after


@pytest.mark.parametrize("native_id", (None, "", "  ", "historical_source_reference"))
def test_initial_recorded_restore_requires_actual_binding_not_predicted_name(
    monkeypatch, native_id
):
    before = default_before()
    requested = cosmetic() | {"name": "historical_source_reference"}
    after = created_after(before)
    state = after["colors"]["shared.prt"]
    state["appearance"] = requested | {"name": native_id}
    bind_source(state)
    client, plan, snapshots, result, verification = verify(
        monkeypatch, before, after, restore=True, value=requested
    )
    assert plan.send()["appearance"]["name"] == ""
    assert plan.request["appearance"]["name"] == requested["name"]
    assert snapshots.call_count == 1
    valid = native_id == requested["name"]
    assert (engine.verification_status(verification) == "passed") is valid
    assert (driver._effect_observation(plan, client) == result["after"]) is valid


def test_initial_recorded_restore_missing_assignment_and_send_tamper_cannot_qualify(
    monkeypatch,
):
    before = default_before()
    requested = cosmetic() | {"name": "historical_source_reference"}
    after = created_after(before)
    state = after["colors"]["shared.prt"]
    state["appearance"] = requested | {"name": "allocated_native_19"}
    state["assignments"] = []
    client, plan, _, _, verification = verify(
        monkeypatch, before, after, restore=True, value=requested
    )
    assert engine.verification_status(verification) == "failed"
    assert driver._effect_observation(plan, client) is None
    plan.send = lambda: dict(plan.request)
    with pytest.raises(Error):
        plan.observe(client)
    assert plan.request["appearance"]["name"] == requested["name"]


def test_invalid_initial_observation_a_is_not_replaced_with_a_valid_b(monkeypatch):
    before = default_before()
    client, plan = planned(monkeypatch, before, original_request(before))
    invalid = created_after(before)
    invalid["colors"]["shared.prt"]["assignments"] = []
    snapshots = Mock(side_effect=[deepcopy(invalid), created_after(before)])
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    result, verification = plan.verify(client, {})
    assert engine.verification_status(verification) == "failed"
    assert plan.observe(client) == result["after"] == invalid
    with pytest.raises(Error):
        plan.verify(client, {})
    assert snapshots.call_count == 1
    assert driver._effect_observation(plan, client) is None


def test_private_wire_projection_and_plan_identity_cannot_be_replaced(monkeypatch):
    before = default_before()
    client, plan = planned(monkeypatch, before, original_request(before))
    wire = plan.send()
    wire["rgb"] = [1, 1, 1]
    assert plan.send()["rgb"] == intended(before)["rgb"]
    after = created_after(before)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    plan.verify(client, {})
    assert driver._effect_observation(plan, client) == after
    plan.send = lambda: wire
    assert driver._effect_observation(plan, client) is None


def test_default_restore_can_observe_one_empty_identified_model_holder(monkeypatch):
    before = repeated()
    after = deepcopy(before)
    state = after["colors"]["shared.prt"]
    state["appearance"] = None
    state["assignments"][0]["appearance"] = None
    client, plan, _, result, verification = verify(monkeypatch, before, after, restore=True)
    assert engine.verification_status(verification) == "passed"
    assert result["reference_after"]["whole_source_binding_observed"] is False
    assert result["reference_after"]["assignments"][0]["appearance"] is None
    assert driver._effect_observation(plan, client) == after
