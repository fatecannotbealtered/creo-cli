"""Public schema counterexamples; offline discovery must not contact Creo."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from tests.test_drawing_warning_contract import cli, offline_only  # noqa: F401

pytestmark = pytest.mark.usefixtures("offline_only")


def public_view():
    status, answer = cli("reference", "--command", "model show")
    assert status == 0
    schema = answer["data"]["schemas"]["model_show"]["json_schema"]
    return schema["properties"]["views"]["items"]["properties"]


def test_public_false_flag_is_observed_and_missing_flag_is_not_false():
    declared = public_view()["exploded_display_readback"]
    validator = Draft202012Validator(declared)
    validator.validate({"complete": True, "value": False, "source": "WView2D.IsExplodedState"})
    validator.validate(
        {
            "complete": False,
            "value": None,
            "source": "WView2D.IsExplodedState",
            "reason": "native_getter_failed",
        }
    )
    for bad in (
        {"complete": False, "value": False},
        {"complete": True, "value": None},
        {"complete": True, "value": "false"},
    ):
        with pytest.raises(ValidationError):
            validator.validate(bad | {"source": "WView2D.IsExplodedState"})


def test_public_named_state_is_unavailable_not_assembly_activity():
    declared = public_view()["named_exploded_state_reference"]
    validator = Draft202012Validator(declared)
    missing = {
        "complete": False,
        "status": "not_checked",
        "value": None,
        "reason": "no supported per-view getter",
    }
    validator.validate(missing)
    with pytest.raises(ValidationError):
        validator.validate(missing | {"complete": True, "value": "ASSEMBLY_ACTIVE"})


def test_public_identity_requires_individual_getter_sources():
    declared = public_view()["view_identity_readback"]
    validator = Draft202012Validator(declared)
    sample = {"complete": True}
    for key, source, value in (
        ("id", "WView2D.GetViewId", 123),
        ("name", "View2D.GetName", "EXPLODED"),
        ("sheet", "View2D.GetSheetNumber", 1),
        ("model", "View2D.GetModel/Model.GetFileName", "support.asm"),
    ):
        sample[key] = {"complete": True, "value": value, "source": source}
    validator.validate(sample)
    bad = deepcopy(sample)
    bad["model"]["source"] = "request parameter"
    with pytest.raises(ValidationError):
        validator.validate(bad)
    del bad["id"]
    with pytest.raises(ValidationError):
        validator.validate(bad)


def test_public_layout_schema_keeps_indexed_ambiguous_objects():
    status, answer = cli("reference")
    assert status == 0
    schema = answer["data"]["schemas"]["dry_run"]["json_schema"]
    fields = schema["properties"]["preview"]["properties"]["extensions"]["properties"]["creo"][
        "properties"
    ]["layout_feedback"]["properties"]["objects"]["items"]["properties"]
    assert "snapshot_index" in fields and "proposal_index" in fields
    assert "matched_view_indexes" in fields["identity_source"]["properties"]
    limits = answer["data"]["capabilities"]["bounded_drawing_edits"]["drawing view add"]
    text = " ".join(limits)
    assert "drawing_view_exploded_readback 1" in text and "not_checked" in text
