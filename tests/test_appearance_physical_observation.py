"""Physical read availability and exact density counterexamples; no CAD calls."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from creo_cli import appearance, driver, engine
from creo_cli.core import Error
from tests.physical_observation_fixture import ASSIGNED, DENSITY, physical, reading, with_physical
from tests.test_appearance_reference_contract import saved_and_reopened
from tests.test_native_display_contract import planned, repeated, successful_after


def state():
    before = with_physical(repeated())
    for model in before["models"].values():
        model["mass_properties"]["mass"] = None
        model["mass_properties"]["density"] = None
    return before


def proof_unknown(proof):
    for key in ("density", "assigned_density"):
        proof[key] = reading(proof[key]["source"], None, "unknown") | {
            "exception_type": "com.ptc.pfc.pfcExceptions.XToolkitNotFound"
        }


def after_color(before):
    after = successful_after(before)
    after["physical_materials"]["shared.prt"]["modified"]["value"] = True
    return after


def test_null_summary_cannot_hide_tiny_model_density_change(monkeypatch):
    before = state()
    before["models"]["shared.prt"]["mass_properties"]["density"] = 0.0
    client, plan = planned(monkeypatch, before)
    after = after_color(before)
    after["models"]["shared.prt"]["mass_properties"]["density"] = 7.8e-9
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert (
        next(
            row["passed"]
            for row in verification["checks"]
            if row["check"] == "physical_and_non_target_state_unchanged"
        )
        is False
    )
    assert driver._effect_observation(plan, client) is None


def test_two_unknown_density_readings_refuse_before_mutation(monkeypatch):
    before = state()
    proof_unknown(before["physical_materials"]["shared.prt"])
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["dispatch_state"] == "not_started"


@pytest.mark.parametrize(
    "drift",
    ("identity", "origin", "relation", "units", "body_override", "multiple", "inventory"),
)
def test_incomplete_or_mixed_source_and_material_inventory_refuses_before_write(monkeypatch, drift):
    before = state()
    observed = before["physical_materials"]["other.prt"]
    if drift == "identity":
        observed["identity"]["value"]["model"] = "other-origin.prt"
    elif drift == "origin":
        observed["identity"]["value"]["origin"] = "D:/foreign/other.prt.1"
    elif drift == "relation":
        observed["identity"]["value"].pop("relation_id")
    elif drift == "units":
        observed["model_units"]["mass"] = "kg"
    elif drift == "body_override":
        observed["body_materials"]["value"][0]["material"]["id"] = "99"
    elif drift == "multiple":
        observed["body_materials"]["value"].append(deepcopy(observed["body_materials"]["value"][0]))
    else:
        observed["loaded_materials"] = reading(
            observed["loaded_materials"]["source"], None, "unknown"
        )
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["dispatch_state"] == "not_started"


def test_snapshot_reads_fresh_material_state_for_each_part_and_retains_native_identity(monkeypatch):
    before = state()
    for name, model in before["models"].items():
        model["feature_count"] = 0
        if model["type"] != "part":
            continue
        before["physical_materials"][name]["density"] = reading(DENSITY, None, "unknown")
        before["physical_materials"][name]["assigned_density"] = reading(ASSIGNED, None, "unset")
    client = Mock()
    calls = []

    def native_read(operation, request):
        calls.append((operation, deepcopy(request)))
        if operation == "model.definition-state":
            return {
                "model": request["model"],
                "status": "success",
                "complete": True,
                "features": [],
                "visible_feature_count": 0,
                "excluded_component_count": 0,
            }
        if operation == "material.list":
            name = request["model"]
            return {
                "model": {
                    "model": name,
                    "physical_observation": deepcopy(before["physical_materials"][name]),
                }
            }
        assert operation == "geometry.list"
        return deepcopy(before["geometry"])

    client.op.side_effect = native_read
    monkeypatch.setattr(engine, "session", lambda c: {"models": list(before["models"])})
    monkeypatch.setattr(engine, "show", lambda c, n: deepcopy(before["models"][n]))
    monkeypatch.setattr(appearance, "color_state", lambda c, n: deepcopy(before["colors"][n]))
    first = appearance.snapshot(client, "shared.prt")
    before["physical_materials"]["other.prt"]["density"] = reading(
        DENSITY, {"value": 7.8e-9, "units": "tonne/mm^3"}
    )
    with pytest.raises(Error) as caught:
        appearance.snapshot(client, "shared.prt")
    assert caught.value.code == "E_UNSUPPORTED"
    assert first["physical_materials"]["other.prt"]["density"]["value"] is None
    assert [request["model"] for op, request in calls if op == "material.list"] == [
        "other.prt",
        "shared.prt",
        "other.prt",
    ]
    assert all(request["name"] == "~" for op, request in calls if op == "material.list")


@pytest.mark.parametrize("name", ("shared.prt", "other.prt"))
@pytest.mark.parametrize("field", ("density", "assigned_density"))
def test_even_tiny_numeric_density_changes_are_exact_protection_failures(monkeypatch, name, field):
    before = state()
    client, plan = planned(monkeypatch, before)
    after = after_color(before)
    after["physical_materials"][name][field]["value"]["value"] += 1e-20
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert (
        next(
            row["passed"]
            for row in verification["checks"]
            if row["check"] == "physical_and_non_target_state_unchanged"
        )
        is False
    )


def test_returned_null_property_is_known_unset_without_inventing_density(monkeypatch):
    before = state()
    proof = before["physical_materials"]["shared.prt"]
    proof["assigned_density"] = reading(ASSIGNED, None, "unset")
    proof["density"] = reading(DENSITY, None, "unknown") | {"exception_type": "some.NativeFailure"}
    client, plan = planned(monkeypatch, before)
    after = after_color(before)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    result, verification = plan.verify(client, {})
    assert all(row["passed"] for row in verification["checks"])
    qualification = result["physical_protection"]["shared.prt"]
    assert qualification["status"] == "known_unset"
    assert qualification["numeric_density_qualified"] is False
    assert result["after"]["models"]["shared.prt"]["mass_properties"]["density"] is None


def test_direct_finite_density_qualifies_while_assigned_property_error_stays_visible(monkeypatch):
    before = state()
    proof = before["physical_materials"]["shared.prt"]
    proof["assigned_density"] = reading(ASSIGNED, None, "unknown") | {
        "exception_type": "com.ptc.pfc.pfcExceptions.XToolkitNotFound"
    }
    client, plan = planned(monkeypatch, before)
    after = after_color(before)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    result, verification = plan.verify(client, {})
    assert all(row["passed"] for row in verification["checks"])
    assert result["physical_protection"]["shared.prt"]["status"] == "known_numeric"
    assert (
        result["after"]["physical_materials"]["shared.prt"]["assigned_density"]
        == proof["assigned_density"]
    )


def test_lost_physical_evidence_after_setter_is_incomplete_and_never_read_as_b(monkeypatch):
    before = state()
    client, plan = planned(monkeypatch, before)
    after = after_color(before)
    proof_unknown(after["physical_materials"]["shared.prt"])
    snapshots = Mock(side_effect=[deepcopy(after), after_color(before)])
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    result, verification = plan.verify(client, {})
    assert engine.verification_status(verification) == "incomplete"
    assert driver._effect_observation(plan, client) is None
    assert plan._settled_observation(plan, client) == result["after"] == after
    assert plan.observe(client) == after
    assert snapshots.call_count == 1
    assert plan._settled_observation(plan, object()) is None
    plan.arguments["model"] = "other.prt"
    assert plan._settled_observation(plan, client) is None


def test_failed_first_read_cannot_trigger_a_second_read_or_reuse_an_old_pass(monkeypatch):
    before = state()
    client, plan = planned(monkeypatch, before)
    snapshots = Mock(side_effect=Error("E_VERIFY_INCOMPLETE", "read failed"))
    monkeypatch.setattr(appearance, "snapshot", snapshots)
    with pytest.raises(Error):
        plan.verify(client, {})
    with pytest.raises(Error):
        plan.observe(client)
    with pytest.raises(Error):
        plan.verify(client, {})
    assert snapshots.call_count == 1
    assert driver._effect_observation(plan, client) is None


def test_wrong_client_never_enters_the_first_verification_read(monkeypatch):
    client, plan = planned(monkeypatch, state())
    read = Mock(side_effect=AssertionError("wrong Client cannot read CAD"))
    monkeypatch.setattr(appearance, "snapshot", read)
    with pytest.raises(Error):
        plan.verify(object(), {})
    read.assert_not_called()
    assert driver._effect_observation(plan, client) is None


def test_setter_failure_observe_rejects_foreign_client_before_any_read(monkeypatch):
    client, plan = planned(monkeypatch, state())
    read = Mock(side_effect=AssertionError("foreign Client cannot issue a failure observation"))
    monkeypatch.setattr(appearance, "snapshot", read)
    with pytest.raises(Error):
        plan.observe(object())
    read.assert_not_called()
    assert plan._settled_observation(plan, client) is None


@pytest.mark.parametrize("incomplete", (False, True))
def test_setter_failure_uses_only_first_issued_a_never_arbitrary_or_later_b(
    monkeypatch, incomplete
):
    before = state()
    client, plan = planned(monkeypatch, before)
    first = after_color(before)
    if incomplete:
        proof_unknown(first["physical_materials"]["shared.prt"])
    later_unchanged = deepcopy(before)
    read = Mock(side_effect=[deepcopy(first), later_unchanged])
    monkeypatch.setattr(appearance, "snapshot", read)
    issued = plan.observe(client)
    assert plan.failure_unchanged(issued) is (None if incomplete else False)
    assert plan.failure_unchanged(later_unchanged) is None
    assert plan.failure_unchanged(deepcopy(issued)) is None
    assert plan._settled_observation(plan, client) == first
    again = plan.observe(client)
    assert again == first
    assert plan.failure_unchanged(again) is (None if incomplete else False)
    assert plan._settled_observation(plan, client) == first
    assert read.call_count == 1
    with pytest.raises(Error):
        plan.observe(object())
    assert read.call_count == 1


def test_setter_failure_first_read_error_is_terminal_for_observation(monkeypatch):
    before = state()
    client, plan = planned(monkeypatch, before)
    read = Mock(side_effect=[Error("E_VERIFY_INCOMPLETE", "failure read unavailable"), before])
    monkeypatch.setattr(appearance, "snapshot", read)
    with pytest.raises(Error):
        plan.observe(client)
    with pytest.raises(Error):
        plan.observe(client)
    assert plan.failure_unchanged(before) is None
    assert plan._settled_observation(plan, client) is None
    assert read.call_count == 1


def test_setter_failure_tampering_with_issued_a_never_changes_the_retained_original(monkeypatch):
    before = state()
    client, plan = planned(monkeypatch, before)
    read = Mock(return_value=deepcopy(before))
    monkeypatch.setattr(appearance, "snapshot", read)
    issued = plan.observe(client)
    issued["physical_materials"]["shared.prt"]["density"]["value"]["value"] += 1e-20
    assert plan.failure_unchanged(issued) is None
    assert plan._settled_observation(plan, client) == before
    assert plan.failure_unchanged(plan.observe(client)) is True
    assert read.call_count == 1


@pytest.mark.parametrize("before_read", (False, True))
def test_setter_failure_observation_and_classifier_require_immutable_intent(
    monkeypatch, before_read
):
    before = state()
    client, plan = planned(monkeypatch, before)
    read = Mock(return_value=deepcopy(before))
    monkeypatch.setattr(appearance, "snapshot", read)
    issued = None if before_read else plan.observe(client)
    plan.arguments["request"]["rgb"][0] = 0.999
    with pytest.raises(Error):
        plan.observe(client)
    assert plan.failure_unchanged(issued or before) is None
    assert plan._settled_observation(plan, client) is None
    assert read.call_count == (0 if before_read else 1)


@pytest.mark.parametrize("drift", ("density", "stamp", "dirty"))
def test_already_dirty_setter_failure_does_not_normalize_density_or_version_changes(
    monkeypatch, drift
):
    before = after_color(state())
    client, plan = planned(monkeypatch, before)
    first = deepcopy(before)
    if drift == "density":
        first["physical_materials"]["shared.prt"]["density"]["value"]["value"] += 1e-20
    elif drift == "stamp":
        first["physical_materials"]["shared.prt"]["identity"]["value"]["version_stamp"] += (
            "-changed"
        )
    else:
        first["models"]["shared.prt"]["modified"] = False
        first["colors"]["shared.prt"]["modified"] = False
        first["physical_materials"]["shared.prt"]["modified"]["value"] = False
    read = Mock(return_value=deepcopy(first))
    monkeypatch.setattr(appearance, "snapshot", read)
    assert plan.failure_unchanged(plan.observe(client)) is False
    assert read.call_count == 1


def test_a_settlement_observation_cannot_be_reverified_and_promoted_after_failed_setter(
    monkeypatch,
):
    before = state()
    client, plan = planned(monkeypatch, before)
    read = Mock(return_value=after_color(before))
    monkeypatch.setattr(appearance, "snapshot", read)
    issued = plan.observe(client)
    assert plan.failure_unchanged(issued) is False
    with pytest.raises(Error):
        plan.verify(client, {})
    assert driver._effect_observation(plan, client) is None
    assert read.call_count == 1


@pytest.mark.parametrize("drift", ("density", "missing", "unknown", "wrong_native_origin"))
def test_reopen_requires_current_complete_exact_physical_state(drift):
    saved, reopened, proof = saved_and_reopened()
    for key in ("saved_protected", "reopened_protected"):
        proof[key]["physical_materials"] = {
            name: physical(model)
            for name, model in proof[key]["models"].items()
            if model["type"] == "part"
        }
    # _physical has intentionally removed the target's permitted dirty flag.
    for key in ("saved_protected", "reopened_protected"):
        proof[key]["physical_materials"]["shared.prt"].pop("modified", None)
    assert appearance.reopened_binding_equal(saved, reopened, **proof)
    material = proof["reopened_protected"]["physical_materials"]["shared.prt"]
    if drift == "density":
        material["density"]["value"]["value"] += 1e-20
    elif drift == "missing":
        proof["reopened_protected"].pop("physical_materials")
    elif drift == "unknown":
        proof_unknown(material)
    else:
        material["identity"]["value"]["origin"] = "D:/wrong/shared.prt.4"
    assert appearance.reopened_binding_equal(saved, reopened, **proof) is False
