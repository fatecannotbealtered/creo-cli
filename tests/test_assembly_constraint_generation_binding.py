"""Synthetic authenticated-generation and selection-root counterexamples; no CAD."""

from copy import deepcopy

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli.core import Error
from tests.test_assembly_constraint_policy import (
    bind_native_references,
    failed_checks,
    native_state,
    state_row,
    successful_edit,
)


class ReadbackClient:
    def __init__(self, state, admitted="independent-generation-17", latest=None):
        self.state = deepcopy(state)
        self.admitted = admitted
        self.latest = latest or admitted
        self.calls = []

    def require_capability(self, name, version):
        assert (name, version) == ("assembly_constraint_redefinition", 2)
        self.calls.append("process-only admission")
        return {"service_instance_id": self.admitted}

    def health(self):
        self.calls.append("latest process-only health")
        return {"service_instance_id": self.latest}

    def op(self, name, request):
        assert (name, request) == ("assembly.constraint-state", {"model": self.state["model"]})
        self.calls.append(name)
        return deepcopy(self.state)


def test_generation_in_authenticated_readback_must_match_its_process_admission():
    state = native_state(instance_id="generation-after-restart")
    client = ReadbackClient(state)
    with pytest.raises(Error) as exc:
        policy.native_state(client, state["model"])
    assert exc.value.code == "E_CONFLICT"
    assert client.calls == ["process-only admission", "assembly.constraint-state"]


def test_later_health_cannot_relabel_an_earlier_native_state_as_a_new_generation():
    state = native_state()
    client = ReadbackClient(state, latest="generation-after-restart")
    observed = policy.native_state(client, state["model"])
    selection = policy._selection(client, observed, state_row(observed, 83))
    assert selection["instance_id"] == state["service_instance_id"]
    assert selection["instance_id"] != client.latest
    assert "latest process-only health" not in client.calls


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_authenticated_generation_cannot_be_supplied_by_health(value):
    state = native_state()
    state["service_instance_id"] = value
    client = ReadbackClient(state)
    with pytest.raises(Error):
        policy.native_state(client, state["model"])


def test_same_geometry_after_restart_does_not_pass_same_generation_protection():
    before, after, intent = successful_edit()
    after["service_instance_id"] = "new-generation-same-models"
    assert failed_checks(policy.compare(before, after, intent))


@pytest.mark.parametrize("role", ["assembly_reference", "component_reference"])
@pytest.mark.parametrize(
    "change",
    [
        {"path_root_model": "foreign_owner.asm"},
        {"reference_owner_model": "foreign_owner.asm"},
        {"path_root_source": "constructed_catalog_owner"},
        {"path_present": None},
    ],
)
def test_actual_constraint_selection_cannot_borrow_catalog_or_foreign_root(role, change):
    state = native_state()
    ref = state_row(state, 83)["constraints"][0][role]
    ref.update(change)
    with pytest.raises(Error):
        policy.validate_state(state)


def test_component_side_root_leaf_and_exact_id_bind_one_of_repeated_models():
    state = native_state()
    row = state_row(state, 83)
    ref = row["constraints"][0]["component_reference"]
    ref["component_path"] = [83]
    bind_native_references(state)
    policy.validate_state(state)
    assert ref["path_root_model"] == state["model"]
    assert ref["path_leaf_model"] == state_row(state, 157)["model"] == row["model"]
    ref["component_path"] = [157]
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize(
    "change",
    [
        {"path_leaf_model": "wrong_leaf.prt"},
        {"path_leaf_source": "constructed_catalog_model"},
        {"path_root_model": "foreign_owner.asm"},
    ],
)
def test_nonempty_sibling_selection_requires_actual_matching_root_and_leaf(change):
    state = native_state()
    ref = state_row(state, 126)["constraints"][0]["assembly_reference"]
    assert ref["component_path"] == [83]
    ref.update(change)
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("field", ["path_root_model", "path_leaf_model"])
def test_empty_model_local_selection_cannot_smuggle_a_root_or_leaf(field):
    state = native_state()
    ref = state_row(state, 83)["constraints"][0]["component_reference"]
    assert ref["path_present"] is False and ref["component_path"] == []
    ref[field] = state["model"]
    with pytest.raises(Error):
        policy.validate_state(state)


def test_rigid_model_local_empty_path_uses_the_child_assembly_root():
    state = native_state(rigid=True)
    row = state_row(state, 83)
    ref = row["constraints"][0]["component_reference"]
    ref.update(
        path_present=True,
        path_root_model=row["model"],
        path_root_source="ComponentPath.GetRoot",
        path_leaf_model=None,
        path_leaf_source="not_read_for_empty_path",
    )
    policy.validate_state(state)
    ref["path_root_model"] = state["model"]
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize(
    "change",
    [
        {"path_root_source": "ComponentPath.GetRoot"},
        {"path_leaf_source": "ComponentPath.GetLeaf"},
        {"path_root_model": "foreign_owner.asm"},
        {"path_leaf_model": "wrong_leaf.prt"},
    ],
)
def test_catalog_expected_paths_are_explicitly_constructed_not_native_selection_reads(change):
    state = native_state()
    state["reference_catalog"][0].update(change)
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize(
    "change",
    [
        {"classification": None},
        {"classification": {"public_feature": None, "source": "Feature.GetIsVisible"}},
        {"classification": {"public_feature": True, "source": "constructed_visibility"}},
        {"reference_usage": None},
    ],
)
def test_catalog_editability_requires_completed_native_visibility_classification(change):
    state = native_state()
    state["reference_catalog"][0].update(change)
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize("which", ["origin", "directory"])
def test_current_engineering_source_change_cannot_pass_pose_only_verification(which):
    before, after, intent = successful_edit()
    if which == "origin":
        after["model_origins"]["slider.prt"] += ".changed"
    else:
        after["working_directory"] += " changed"
    assert failed_checks(policy.compare(before, after, intent))


@pytest.mark.parametrize("which", ["missing_origin", "missing_proof", "failed_read"])
def test_origin_identity_requires_actual_completed_native_read(which):
    state = native_state()
    if which == "missing_origin":
        state["model_origins"].pop("slider.prt")
    elif which == "missing_proof":
        state["model_origin_readback"].pop("slider.prt")
    else:
        state["model_origin_readback"]["slider.prt"]["read_complete"] = False
    with pytest.raises(Error):
        policy.validate_state(state)
