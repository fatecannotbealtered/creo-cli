"""Offline retained native-102 counterexample; never reclassifies that failed call."""

import copy
import json
import math
from pathlib import Path

import pytest

from creo_cli import display, presentation
from creo_cli.core import Error

DATA = Path(__file__).parent / "data" / "native-102-unexplode-bounds.json"


def observations():
    if not DATA.exists():
        pytest.skip("Private native observations are outside the public snapshot")
    fixture = json.loads(DATA.read_text(encoding="utf-8"))
    assert fixture["original_operation_id"] == "9793e51ec3eb4b27bc8714980ceba435"
    return fixture["before"], fixture["after"]


def test_retained_display_bounds_change_is_predicted_without_dropping_either_bbox():
    before, after = observations()
    projected_before = display.unexplode_boxes(before, "phone_demo.asm")
    projected_after = display.unexplode_boxes(after, "phone_demo.asm", required=True)
    assert projected_before["raw_bbox_matches_display_union"] is True
    assert projected_after["raw_bbox_matches_display_union"] is True
    assert projected_before["raw_bbox"][0][0] == -227.79999999999998
    assert projected_after["raw_bbox"][0][0] == -37.99999999999999
    assert presentation.equivalent(
        projected_before["normal_union"], projected_after["normal_union"]
    )
    assert presentation.equivalent(
        display.physical(before, "phone_demo.asm", "unexplode", project_unexplode=True),
        display.physical(after, "phone_demo.asm", "unexplode", project_unexplode=True),
    )


def test_unexpected_point_zero_one_owner_bbox_drift_cannot_pass_projection():
    before, after = observations()
    after["models"]["phone_demo.asm"]["bbox"][1][0] += 0.01
    assert (
        display.unexplode_boxes(after, "phone_demo.asm", required=True)[
            "raw_bbox_matches_display_union"
        ]
        is False
    )
    assert not presentation.equivalent(
        display.physical(before, "phone_demo.asm", "unexplode", project_unexplode=True),
        display.physical(after, "phone_demo.asm", "unexplode", project_unexplode=True),
    )


def test_part_geometry_change_is_not_hidden_by_a_matching_union():
    before, after = observations()
    after["models"]["midframe.prt"]["bbox"][1][0] += 0.01
    after["models"]["phone_demo.asm"]["bbox"][1][0] += 0.01
    assert (
        display.unexplode_boxes(after, "phone_demo.asm", required=True)[
            "raw_bbox_matches_display_union"
        ]
        is True
    )
    assert not presentation.equivalent(
        display.physical(before, "phone_demo.asm", "unexplode", project_unexplode=True),
        display.physical(after, "phone_demo.asm", "unexplode", project_unexplode=True),
    )


def test_already_normal_noop_keeps_raw_bbox_and_does_not_limit_rigid_children():
    _, before = observations()
    before["models"]["midframe.prt"]["type"] = "assembly"
    after = copy.deepcopy(before)
    assert display.unexplode_boxes(before, "phone_demo.asm") is None
    assert presentation.equivalent(
        display.physical(before, "phone_demo.asm", "unexplode"),
        display.physical(after, "phone_demo.asm", "unexplode"),
    )
    after["models"]["phone_demo.asm"]["bbox"][1][0] += 0.01
    assert not presentation.equivalent(
        display.physical(before, "phone_demo.asm", "unexplode"),
        display.physical(after, "phone_demo.asm", "unexplode"),
    )


@pytest.mark.parametrize(
    "unsupported", ("rotated", "unit_mismatch", "assembly_child", "eleven_parts")
)
def test_bounds_profile_rejects_unqualified_transform_or_assembly_shapes(unsupported):
    before, _ = observations()
    owner = before["models"]["phone_demo.asm"]
    if unsupported == "rotated":
        value = 1 / math.sqrt(2)
        for field in ("position", "component_path_transform"):
            owner["components"][0][field]["x_axis"] = [value, value, 0]
            owner["components"][0][field]["y_axis"] = [-value, value, 0]
    elif unsupported == "unit_mismatch":
        before["models"]["midframe.prt"]["units"]["length"] = "in"
    elif unsupported == "assembly_child":
        before["models"]["midframe.prt"]["type"] = "assembly"
    else:
        owner["components"].append(copy.deepcopy(owner["components"][0]))
    with pytest.raises(Error) as caught:
        display.unexplode_boxes(before, "phone_demo.asm")
    assert caught.value.code == "E_UNSUPPORTED"
