"""Authorized reference replacement counterexamples; controlled observations, never CAD proof."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from creo_cli import appearance, driver
from creo_cli.core import Error
from tests.test_native_display_contract import (
    bind_source,
    intended,
    planned,
    repeated,
    successful_after,
)


def verified(monkeypatch, before, after, request=None, *, restore=False):
    client, plan = planned(monkeypatch, before, request, restore)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    result, checks = plan.verify(client, {})
    return client, plan, result, {row["check"]: row["passed"] for row in checks["checks"]}


def test_preview_binds_authorization_old_identity_full_impact_and_pending_native_allocation(
    monkeypatch,
):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    assert client.require_capability.call_args_list == [
        call("source_part_appearance_reference", 1),
        call("source_part_appearance_unique_reference", 1),
    ]
    assert plan.preview["reference_action"] == "create_and_bind"
    assert plan.preview["reference_replacement_authorized"] is True
    assert plan.preview["reference_before"]["native_id"] == "sample"
    assert plan.preview["reference_before"]["source_context"]["model"] == "shared.prt"
    assert plan.preview["reference_after"]["native_id"] is None
    assert plan.preview["reference_after"]["allocation_status"] == "pending_native_allocation"
    assert plan.preview["affected_occurrences"] == before["affected_occurrences"]
    assert plan.request["expected_before"] == before["colors"]["shared.prt"]
    assert plan.request["expected_source_context"] == {"model": "shared.prt", "origin": None}
    assert "other_sources_still_using_the_old_appearance" in plan.preview["protected"]


@pytest.mark.parametrize(
    ("fields", "restore", "error"),
    (
        ({"reference_replacement_authorized": False}, False, "E_FORBIDDEN"),
        ({"reference_action": "preserve"}, False, "E_VALIDATION"),
        ({"reference_action": "replace_unknown"}, False, "E_VALIDATION"),
        ({"appearance": None}, True, "E_VALIDATION"),
    ),
)
def test_reference_authorization_and_null_restore_are_explicit_before_cad(
    monkeypatch, fields, restore, error
):
    request = intended(repeated(), **fields)
    if restore:
        request.pop("rgb")
    monkeypatch.setattr(appearance, "read_request", lambda p: request)
    with pytest.raises(Error) as caught:
        appearance.prepare({"model": "shared.prt", "request": "request.json"}, restore)
    assert caught.value.code == error


def test_old_service_cannot_silently_accept_create_and_bind(monkeypatch):
    client = Mock()
    client.require_capability.side_effect = Error("E_UNSUPPORTED", "old service capability")
    observed = Mock(side_effect=AssertionError("snapshot must not run before capability refusal"))
    monkeypatch.setattr(appearance, "snapshot", observed)
    with pytest.raises(Error) as caught:
        appearance.plan(
            client,
            {},
            {"model": "shared.prt", "request": intended(repeated()), "restore": False},
        )
    assert caught.value.code == "E_UNSUPPORTED"
    observed.assert_not_called()


@pytest.mark.parametrize(
    "missing", ("selection_model", "selection_model_type", "assignment_selection")
)
def test_new_mode_requires_actual_selection_owner_identity_not_old_payload(monkeypatch, missing):
    before = repeated()
    if missing == "assignment_selection":
        before["colors"]["shared.prt"]["assignments"][0].pop("selection_model")
    else:
        before["colors"]["shared.prt"].pop(missing)
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("native_id", ("", "   ", None, "sample"))
def test_new_native_id_must_be_valid_and_different_from_old_id(monkeypatch, native_id):
    before = repeated()
    after = successful_after(before)
    after["colors"]["shared.prt"]["appearance"]["name"] = native_id
    bind_source(after["colors"]["shared.prt"])
    client, plan, _, checks = verified(monkeypatch, before, after)
    assert checks["requested_native_appearance"] is True
    assert checks["authorized_native_reference_creation_and_source_binding"] is False
    assert driver._effect_observation(plan, client) is None


@pytest.mark.parametrize(
    "drift",
    (
        "wrong_assignment_id",
        "wrong_assignment_model",
        "wrong_visible_model",
        "wrong_type",
        "missing",
        "label",
    ),
)
def test_binding_is_more_than_two_matching_names(monkeypatch, drift):
    before = repeated()
    after = successful_after(before)
    state = after["colors"]["shared.prt"]
    if drift == "wrong_assignment_id":
        state["assignments"][0]["appearance"]["name"] = "different_reference"
    elif drift == "wrong_assignment_model":
        state["assignments"][0]["selection_model"] = "other.prt"
    elif drift == "wrong_visible_model":
        state["selection_model"] = "other.prt"
    elif drift == "wrong_type":
        state["assignments"][0]["selection_model_type"] = "assembly"
    elif drift == "missing":
        state["assignments"] = []
    else:
        state["appearance"]["label"] = "changed without authorization"
        bind_source(state)
    client, plan, _, checks = verified(monkeypatch, before, after)
    assert not all(checks.values())
    if drift == "label":
        assert checks["non_reference_non_rgb_cosmetic_properties_preserved"] is False
    else:
        assert checks["authorized_native_reference_creation_and_source_binding"] is False
    assert driver._effect_observation(plan, client) is None


@pytest.mark.parametrize("field", ("name", "label", "rgb", "reflection"))
def test_old_reference_still_used_by_other_source_must_remain_unchanged(monkeypatch, field):
    before = repeated()
    after = successful_after(before)
    changed = after["colors"]["other.prt"]["appearance"]
    changed[field] = [1, 0, 0] if field == "rgb" else 15 if field == "reflection" else "changed"
    bind_source(after["colors"]["other.prt"])
    client, plan, _, checks = verified(monkeypatch, before, after)
    assert checks["authorized_native_reference_creation_and_source_binding"] is True
    assert checks["physical_and_non_target_state_unchanged"] is False
    assert driver._effect_observation(plan, client) is None


def test_new_mode_result_records_actual_old_and_new_scoped_identity(monkeypatch):
    before = repeated()
    after = successful_after(before)
    client, plan, result, checks = verified(monkeypatch, before, after)
    assert all(checks.values())
    assert result["reference_before"]["native_id"] == "sample"
    assert result["reference_after"]["native_id"] == "native_allocated_fixture_41"
    assert result["reference_after"]["whole_source_binding_observed"] is True
    assert driver._effect_observation(plan, client) == after
    plan.request["expected_before"]["appearance"]["name"] = "tampered_old_id"
    assert driver._effect_observation(plan, client) is None


@pytest.mark.parametrize(
    "fixture", ("native-f29-appearance-identity.json", "native-f176-appearance-identity.json")
)
def test_both_retained_native_colour_failures_now_refuse_without_new_authorization(
    monkeypatch, fixture
):
    data = Path(__file__).parent / "data" / fixture
    if not data.exists():
        pytest.skip("Private native observations are outside the public snapshot")
    native = json.loads(data.read_text(encoding="utf-8"))
    before = repeated()
    before["colors"]["shared.prt"]["appearance"] = deepcopy(native["before"])
    bind_source(before["colors"]["shared.prt"])
    request = intended(before, rgb=native["requested_rgb"])
    request.pop("reference_action")
    request.pop("reference_replacement_authorized")
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, request)
    assert caught.value.code == "E_UNSUPPORTED"
    assert native["failed_check"] == "non_rgb_cosmetic_properties_preserved"
    assert native["before"]["name"] != native["after"]["name"]
    assert native["old_receipt_rewritten"] is False


def test_restore_creates_new_reference_and_treats_recorded_id_as_historical(monkeypatch):
    before = repeated()
    requested = deepcopy(before["colors"]["shared.prt"]["appearance"])
    requested |= {"rgb": [0.9, 0.2, 0.3], "label": "recorded label", "name": "historical_ref"}
    request = intended(before)
    request.pop("rgb")
    request["appearance"] = requested
    after = successful_after(before)
    after["colors"]["shared.prt"]["appearance"] = requested | {"name": "native_restore_ref_9"}
    bind_source(after["colors"]["shared.prt"])
    client, plan, result, checks = verified(monkeypatch, before, after, request, restore=True)
    assert all(checks.values())
    assert "recorded Name is historical only" in plan.preview["reference_semantics"]
    assert plan.request["appearance"]["name"] == "historical_ref"
    assert result["reference_after"]["native_id"] == "native_restore_ref_9"
    assert driver._effect_observation(plan, client) == after


def saved_and_reopened():
    snapshot = repeated()
    files = {}
    for name, model in snapshot["models"].items():
        model["origin"] = "D:/owned/" + name + ".4"
        model["origin_readback"] = {
            "complete": True,
            "source": "Model.GetOrigin",
            "value": model["origin"],
        }
        if model["type"] == "part":
            snapshot["physical_materials"][name]["identity"]["value"]["origin"] = model["origin"]
        files[name] = {
            "exact_path": model["origin"],
            "sha256": "a" * 64,
            "source_context": appearance.source_context(model),
        }
    source = snapshot["models"]["shared.prt"]
    saved = appearance.reference_binding(snapshot["colors"]["shared.prt"], source)
    reopened = deepcopy(saved)
    reopened["native_id"] = "reloaded_native_ref_1"
    reopened["appearance"]["name"] = reopened["native_id"]
    reopened["assignments"][0]["appearance"]["name"] = reopened["native_id"]
    file = files["shared.prt"]
    protected = appearance._physical(snapshot, "shared.prt")
    protected["dependency_files"] = files
    return (
        saved,
        reopened,
        {
            "saved_file": deepcopy(file),
            "reopened_file": deepcopy(file),
            "saved_protected": deepcopy(protected),
            "reopened_protected": deepcopy(protected),
        },
    )


def test_reopen_id_text_alone_can_change_only_with_exact_file_and_self_consistent_binding():
    saved, reopened, proof = saved_and_reopened()
    assert appearance.reopened_binding_equal(saved, reopened, **proof)


@pytest.mark.parametrize(
    "drift",
    (
        "wrong_model",
        "wrong_assignment",
        "label",
        "file_hash",
        "geometry",
        "file_path",
        "missing_protected",
    ),
)
def test_reopen_id_equivalence_never_ignores_wrong_source_binding_or_physical_change(drift):
    saved, reopened, proof = saved_and_reopened()
    if drift == "wrong_model":
        reopened["source_context"]["model"] = "other.prt"
        proof["reopened_file"]["source_context"] = reopened["source_context"]
    elif drift == "wrong_assignment":
        reopened["assignments"][0]["selection_model"] = "other.prt"
    elif drift == "label":
        reopened["appearance"]["label"] = "changed"
        reopened["assignments"][0]["appearance"]["label"] = "changed"
    elif drift == "file_hash":
        proof["reopened_file"]["sha256"] = "b" * 64
    elif drift == "geometry":
        proof["reopened_protected"]["geometry"]["items"][0]["area"] += 0.1
    elif drift == "file_path":
        proof["reopened_file"]["exact_path"] = "D:/wrong/shared.prt.4"
    else:
        proof["saved_protected"] = {}
    assert appearance.reopened_binding_equal(saved, reopened, **proof) is False


def test_authorized_exact_copy_needs_explicit_same_hash_file_mapping():
    saved, reopened, proof = saved_and_reopened()
    new_path = "D:/independent/shared.prt.4"
    reopened["source_context"]["origin"] = new_path
    proof["reopened_file"] |= {
        "exact_path": new_path,
        "source_context": reopened["source_context"],
        "authorized_exact_copy_of": proof["saved_file"]["exact_path"],
    }
    protected = proof["reopened_protected"]
    protected["models"]["shared.prt"]["origin"] = new_path
    protected["models"]["shared.prt"]["origin_readback"]["value"] = new_path
    protected["physical_materials"]["shared.prt"]["identity"]["value"]["origin"] = new_path
    protected["dependency_files"]["shared.prt"] = deepcopy(proof["reopened_file"])
    assert appearance.reopened_binding_equal(saved, reopened, **proof)


@pytest.mark.parametrize("counterexample", ("placeholder", "unrelated_file", "no_native_origin"))
def test_reopen_retains_independent_review_counterexamples(counterexample):
    saved, reopened, proof = saved_and_reopened()
    if counterexample == "placeholder":
        proof["saved_protected"] = proof["reopened_protected"] = {"placeholder": True}
    elif counterexample == "unrelated_file":
        for key in ("saved_file", "reopened_file"):
            proof[key]["exact_path"] = "D:/unrelated/shared.prt.4"
    else:
        for binding, key in ((saved, "saved_file"), (reopened, "reopened_file")):
            binding["source_context"]["origin"] = None
            proof[key]["source_context"]["origin"] = None
    assert appearance.reopened_binding_equal(saved, reopened, **proof) is False


@pytest.mark.parametrize("drift", ("target_not_part", "model_suffix_type_mismatch"))
def test_reopen_rejects_self_consistent_but_wrong_native_model_type(drift):
    saved, reopened, proof = saved_and_reopened()
    for key in ("saved_protected", "reopened_protected"):
        models = proof[key]["models"]
        name = (
            "shared.prt"
            if drift == "target_not_part"
            else next(name for name in models if name.endswith(".asm"))
        )
        models[name]["type"] = "assembly" if name.endswith(".prt") else "part"
        models[name]["components"] = []
    assert appearance.reopened_binding_equal(saved, reopened, **proof) is False


@pytest.mark.parametrize("restore", (False, True))
def test_preserve_mode_refuses_even_sub_tolerance_real_change_before_dispatch(monkeypatch, restore):
    before = repeated()
    current = deepcopy(before["colors"]["shared.prt"]["appearance"])
    current["rgb"][0] += 1e-13
    request = intended(
        before,
        reference_action="preserve",
        reference_replacement_authorized=False,
        rgb=current["rgb"],
    )
    if restore:
        request.pop("rgb")
        request["appearance"] = current
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, request, restore)
    assert caught.value.code == "E_UNSUPPORTED"
