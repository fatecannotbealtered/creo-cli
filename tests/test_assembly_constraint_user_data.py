"""Retain native empty versus null user data per constraint; synthetic, no CAD."""

from copy import deepcopy

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli.core import Error
from tests.test_assembly_constraint_policy import (
    bind_native_references,
    failed_checks,
    native_state,
    state_request,
    state_row,
    transform,
)


def edit_with_user_data(values):
    before = native_state()
    for c, value in zip(state_row(before, 83)["constraints"], values, strict=True):
        c["user_data"] = value
    frozen = deepcopy(before)
    q = state_request(before)
    intent = policy.make_intent(before, q)
    after = deepcopy(before)
    state_row(after, 83)["constraints"] = deepcopy(intent["constraints"])
    # Independent native readback reflects the requested preservation, not the intent builder.
    for c, value in zip(state_row(after, 83)["constraints"], values, strict=True):
        c["user_data"] = value
    bind_native_references(after)
    state_row(after, 83)["component_path_transform"] = transform([12, 0, 0])
    state_row(after, 126)["component_path_transform"] = transform([15, 0, 0])
    assert before == frozen
    return before, after, intent


@pytest.mark.parametrize(
    "values", [("", "", ""), (None, None, None), ("", None, ""), (None, "", None)]
)
def test_correct_readback_keeps_each_original_empty_or_null_value(values):
    before, after, intent = edit_with_user_data(values)
    assert [c["user_data"] for c in intent["constraints"]] == list(values)
    assert not failed_checks(policy.compare(before, after, intent))


@pytest.mark.parametrize("old,new", [(None, ""), ("", None)])
def test_null_and_empty_are_not_automatically_normalized_after_setting(old, new):
    before, after, intent = edit_with_user_data((old, None, None))
    state_row(after, 83)["constraints"][0]["user_data"] = new
    assert failed_checks(policy.compare(before, after, intent))


def test_correct_empty_string_native_readback_passes_the_complete_pose_predicate():
    before, after, intent = edit_with_user_data(("", None, None))
    assert not failed_checks(policy.compare(before, after, intent))


def test_mixed_original_values_cannot_be_reordered_between_constraints():
    before, after, intent = edit_with_user_data(("", None, ""))
    state_row(after, 83)["constraints"][0]["user_data"] = None
    state_row(after, 83)["constraints"][1]["user_data"] = ""
    assert failed_checks(policy.compare(before, after, intent))


@pytest.mark.parametrize("bad", ["application-owned", {"error": "GetterFailed"}, 0, False])
def test_nonempty_failed_or_malformed_target_user_data_is_refused_before_edit(bad):
    state = native_state()
    state_row(state, 83)["constraints"][0]["user_data"] = bad
    q = state_request(state)
    frozen = deepcopy((state, q))
    with pytest.raises(Error):
        policy.make_intent(state, q)
    assert (state, q) == frozen


def test_missing_user_data_getter_is_not_a_native_null_result():
    state = native_state()
    state_row(state, 83)["constraints"][0].pop("user_data")
    q = state_request(state)
    with pytest.raises(Error):
        policy.make_intent(state, q)
