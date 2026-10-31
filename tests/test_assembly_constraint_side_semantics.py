"""Official side applicability on synthetic data, not native physical-plane evidence."""

from copy import deepcopy

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli.core import Error
from tests.test_assembly_constraint_policy import (
    NoCadClient,
    bind_native_references,
    failed_checks,
    native_state,
    physical_state,
    state_request,
    state_row,
    transform,
)


def physical_raw(raw, role):
    state = physical_state()
    for row in state["components"]:
        for c in row["constraints"]:
            c[role] = raw
    return state


@pytest.mark.parametrize("raw", ["DATUM_SIDE_YELLOW", None, "DATUM_SIDE_RED"])
@pytest.mark.parametrize("role", ["assembly_side", "component_side"])
def test_physical_raw_side_is_retained_while_edit_input_states_nonapplicability(raw, role):
    state = physical_raw(raw, role)
    frozen = deepcopy(state)
    policy.validate_state(state)
    result = policy._query_row(NoCadClient(), state, state_row(state, 83))
    assert result["constraints"][0][role] == raw
    assert state == frozen
    q = result["edit_request"]
    assert all(
        c["assembly_side"] == "DATUM_SIDE_NONE" and c["component_side"] == "DATUM_SIDE_NONE"
        for c in q["constraints"]
    )
    policy.validate_request(q)
    policy.make_intent(state, q)


@pytest.mark.parametrize("raw", ["DATUM_SIDE_YELLOW", None, "DATUM_SIDE_RED"])
@pytest.mark.parametrize("role", ["assembly_side", "component_side"])
@pytest.mark.parametrize("wrong_pose", [False, True])
def test_physical_pose_and_target_comparison_use_geometry_without_applying_datum_side(
    raw, role, wrong_pose
):
    before = physical_raw(raw, role)
    q = policy._query_row(NoCadClient(), before, state_row(before, 83))["edit_request"]
    q["constraints"][0]["offset"] = 12
    intent = policy.make_intent(before, q)
    after = deepcopy(before)
    state_row(after, 83)["constraints"] = deepcopy(intent["constraints"])
    for c in state_row(after, 83)["constraints"]:
        c[role] = raw
    state_row(after, 83)["component_path_transform"] = transform([14 if wrong_pose else 12, 0, 0])
    state_row(after, 126)["component_path_transform"] = transform([15, 0, 0])
    bind_native_references(after)
    result = policy.compare(before, after, intent)
    assert bool(failed_checks(result)) is wrong_pose
    assert state_row(after, 83)["constraints"][0][role] == raw


@pytest.mark.parametrize("role", ["assembly_side", "component_side"])
@pytest.mark.parametrize("bad", ["UNKNOWN_SIDE", {"error": "GetterFailed"}])
def test_physical_inapplicability_does_not_hide_unknown_or_error_result(role, bad):
    state = physical_state()
    state_row(state, 83)["constraints"][0][role] = bad
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("role", ["assembly_side", "component_side"])
def test_missing_physical_side_getter_is_unread_evidence(role):
    state = physical_state()
    state_row(state, 83)["constraints"][0].pop(role)
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("role", ["assembly_side", "component_side"])
@pytest.mark.parametrize("raw", [None, "DATUM_SIDE_NONE"])
def test_datum_requires_actual_known_primary_or_secondary_side(role, raw):
    state = native_state()
    state_row(state, 83)["constraints"][0][role] = raw
    with pytest.raises(Error):
        policy.validate_state(state)


def test_datum_red_and_yellow_remain_different_constraint_intent():
    state = native_state()
    yellow = deepcopy(state_row(state, 83)["constraints"][0])
    red = deepcopy(yellow)
    red["assembly_side"] = "DATUM_SIDE_RED"
    assert policy._constraint_signature(yellow) != policy._constraint_signature(red)


@pytest.mark.parametrize(
    "native_type",
    [
        "ASM_CONSTRAINT_ALIGN",
        "ASM_CONSTRAINT_ALIGN_OFF",
        "ASM_CONSTRAINT_MATE",
        "ASM_CONSTRAINT_MATE_OFF",
    ],
)
def test_present_null_offset_has_documented_zero_meaning_for_known_offset_constraint(native_type):
    state = native_state()
    c = state_row(state, 83)["constraints"][1]
    c["type"] = "mate" if "MATE" in native_type else "align"
    c["native_type"] = native_type
    c["offset"] = None
    frozen = deepcopy(state)
    policy.validate_state(state)
    assert policy._copy_constraint(c)["offset"] == 0
    assert c["offset"] is None
    assert state == frozen


def test_formal_null_zero_still_checks_actual_offset_geometry():
    state = native_state()
    for c in state_row(state, 83)["constraints"]:
        c["offset"] = None
    policy.validate_state(state)
    assert not failed_checks({"checks": policy.pose_checks(state, "83")})
    state_row(state, 83)["component_path_transform"] = transform([0, 1, 0])
    assert failed_checks({"checks": policy.pose_checks(state, "83")})


@pytest.mark.parametrize("native_type", [None, "UNCLASSIFIED", "ASM_CONSTRAINT_FIX"])
def test_null_offset_does_not_supply_zero_without_known_applicable_native_type(native_type):
    state = native_state()
    c = state_row(state, 83)["constraints"][1]
    c["offset"] = None
    if native_type is None:
        c.pop("native_type")
    else:
        c["native_type"] = native_type
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("missing", [False, True])
def test_unread_or_failed_offset_does_not_become_formal_zero(missing):
    state = native_state()
    c = state_row(state, 83)["constraints"][1]
    if missing:
        c.pop("offset")
    else:
        c["offset"] = {"error": "GetterFailed"}
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("count_change", [-1, 1])
def test_constraint_count_change_is_refused_before_write_in_fixed_count_profile(count_change):
    state = native_state()
    if count_change == -1:
        state_row(state, 83)["constraints"].append(deepcopy(state_row(state, 83)["constraints"][0]))
    q = state_request(state)
    if count_change == 1:
        q["constraints"].append(deepcopy(q["constraints"][0]))
    policy.validate_request(q)
    frozen = deepcopy((state, q))
    with pytest.raises(Error):
        policy.make_intent(state, q)
    assert (state, q) == frozen
