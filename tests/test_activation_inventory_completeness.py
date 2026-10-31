"""Controlled activation protection: complete structure, independently of active display."""

import copy
import math
from types import SimpleNamespace

import pytest

from creo_cli import display, engine, presentation
from creo_cli.core import Error


def observed():
    frame = {
        "origin": [0.0, 0.0, 0.0],
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "z_axis": [0.0, 0.0, 1.0],
    }
    part = {
        "model": "member.prt",
        "type": "part",
        "modified": False,
        "material": None,
        "mass_properties": {"density": None},
        "bbox": [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]],
    }
    owner = {
        **copy.deepcopy(part),
        "model": "owner.asm",
        "type": "assembly",
        "components": [
            {
                "id": "40",
                "model": "member.prt",
                "status": "FEAT_ACTIVE",
                "placed": True,
                "packaged": False,
                "underconstrained": False,
                "constraints": [{"type": "def_placement", "offset": 0.0}],
                "position": copy.deepcopy(frame),
                "component_path_transform": copy.deepcopy(frame),
            }
        ],
        "exploded_states": [
            {
                "id": "-2338921",
                "name": "Default Explode",
                "active": True,
                "is_default": True,
                "moves": [
                    {
                        "type": "translate",
                        "components": [40],
                        "component_paths": [["40"]],
                        "direction": [0.0, 0.0, 1.0],
                        "distance": 1.0,
                    }
                ],
            }
        ],
    }
    owner["explosion"] = {
        "complete": True,
        "states": copy.deepcopy(owner["exploded_states"]),
        "active_state_id": "-2338921",
        "context": {"complete": False, "current_model": None},
        "display_readback": {"complete": False, "value": None},
        "is_exploded": None,
    }
    return {
        "models": {"owner.asm": owner, "member.prt": part},
        "colors": {},
        "presentation": {
            "target_active": False,
            "component_visibility": [],
            "target_identity": {
                "model": "owner.asm",
                "type": "assembly",
                "origin": "owner.asm.1",
                "version_stamp": "1",
                "relation_id": 0,
            },
        },
    }


def set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def test_inactive_complete_definition_is_accepted_without_mutating_native_values():
    value = observed()
    frozen = copy.deepcopy(value)
    display.activation_structure(value)
    assert value == frozen
    assert value["models"]["owner.asm"]["explosion"]["is_exploded"] is None
    assert value["models"]["member.prt"]["mass_properties"]["density"] is None


@pytest.mark.parametrize(
    "path,bad",
    [
        (("exploded_states",), None),
        (("explosion", "complete"), False),
        (("explosion", "states"), None),
        (("explosion", "active_state_id"), "unreadable"),
        (("components",), None),
        (("components", 0, "position"), None),
        (("components", 0, "component_path_transform"), None),
        (("components", 0, "constraints"), None),
        (("components", 0, "constraints"), [None]),
        (("components", 0, "constraints"), [{"type": "align", "offset": 0.0}]),
        (("components", 0, "constraints", 0, "offset"), math.nan),
        (("components", 0, "status"), None),
        (("components", 0, "underconstrained"), None),
        (("components", 0, "model"), "missing.prt"),
        (("components", 0, "component_path_transform", "x_axis"), [2.0, 0.0, 0.0]),
        (("bbox",), {"error": "unavailable"}),
        (("mass_properties",), {"error": "unavailable", "density": None}),
    ],
)
def test_same_unknown_structure_on_both_sides_is_never_a_protection_baseline(path, bad):
    value = observed()
    set_path(value["models"]["owner.asm"], path, bad)
    before = copy.deepcopy(value)
    after = copy.deepcopy(value)
    if not (isinstance(bad, float) and math.isnan(bad)):
        assert presentation.equivalent(before, after)
    for observation in (before, after):
        with pytest.raises(Error) as failure:
            display.activation_structure(observation)
        assert failure.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize(
    "path,bad",
    [
        (("active",), None),
        (("is_default",), None),
        (("name",), None),
        (("moves",), None),
        (("moves", 0, "direction"), [0.0, 0.0, 0.0]),
        (("moves", 0, "direction"), [0.0, 0.0, math.inf]),
        (("moves", 0, "distance"), math.nan),
        (("moves", 0, "component_paths"), [["999"]]),
        (("moves", 0, "component_paths"), [[]]),
    ],
)
def test_both_state_inventories_must_be_fully_readable(path, bad):
    value = observed()
    owner = value["models"]["owner.asm"]
    set_path(owner["exploded_states"][0], path, bad)
    owner["explosion"]["states"] = copy.deepcopy(owner["exploded_states"])
    with pytest.raises(Error) as failure:
        display.activation_structure(value)
    assert failure.value.code == "E_VERIFY_INCOMPLETE"


def test_all_loaded_assemblies_are_checked_when_target_is_a_part():
    value = observed()
    value["presentation"]["target_identity"]["model"] = "member.prt"
    value["models"]["owner.asm"]["components"][0]["component_path_transform"] = None
    with pytest.raises(Error):
        display.activation_structure(value)


@pytest.mark.parametrize("name,wrong_type", [("owner.asm", "part"), ("member.prt", "assembly")])
def test_model_suffix_type_mismatch_cannot_hide_an_assembly_inventory(name, wrong_type):
    value = observed()
    value["models"][name]["type"] = wrong_type
    with pytest.raises(Error) as failure:
        display.activation_structure(value)
    assert failure.value.code == "E_VERIFY_INCOMPLETE"


def test_valid_but_changed_pose_and_bbox_remain_physical_differences():
    before = observed()
    for path, value in [
        (("components", 0, "position", "origin"), [0.1, 0.0, 0.0]),
        (("components", 0, "component_path_transform", "origin"), [0.1, 0.0, 0.0]),
        (("bbox",), [[0.0, 0.0, 0.0], [2.0, 1.0, 1.0]]),
    ]:
        after = copy.deepcopy(before)
        set_path(after["models"]["owner.asm"], path, value)
        display.activation_structure(after)
        assert not presentation.equivalent(
            display.physical(before, "owner.asm", "activate"),
            display.physical(after, "owner.asm", "activate"),
        )


def test_valid_changed_active_identity_remains_a_protected_physical_difference():
    before = observed()
    owner = before["models"]["owner.asm"]
    owner["exploded_states"].append(
        {"id": "8", "name": "Other State", "active": False, "is_default": False, "moves": []}
    )
    owner["explosion"]["states"] = copy.deepcopy(owner["exploded_states"])
    after = copy.deepcopy(before)
    changed = after["models"]["owner.asm"]
    changed["exploded_states"][0]["active"] = False
    changed["exploded_states"][1]["active"] = True
    changed["explosion"]["states"] = copy.deepcopy(changed["exploded_states"])
    changed["explosion"]["active_state_id"] = "8"
    for observation in (before, after):
        display.activation_structure(observation)
    assert not presentation.equivalent(
        display.physical(before, "owner.asm", "activate"),
        display.physical(after, "owner.asm", "activate"),
    )


def test_planning_and_verification_both_validate_the_same_complete_observation(monkeypatch):
    before = observed()
    monkeypatch.setattr(engine, "session", lambda _: {"models": list(before["models"])})
    monkeypatch.setattr(engine, "store_directory", lambda *_: None)
    monkeypatch.setattr(display, "snapshot", lambda *_: copy.deepcopy(before))
    client = SimpleNamespace(require_capability=lambda *_: None)
    pre = display.prepare({"model": "owner.asm"}, "activate")
    plan = display.plan(client, {}, pre)
    assert plan.preview["activation_structure_profile"] == "complete_loaded_model_inventory_v1"
    broken = copy.deepcopy(before)
    broken["models"]["owner.asm"]["explosion"]["complete"] = False
    monkeypatch.setattr(display, "snapshot", lambda *_: broken)
    with pytest.raises(Error) as failure:
        plan.verify(client, {})
    assert failure.value.code == "E_VERIFY_INCOMPLETE"
    assert plan.verified_observation is None
    with pytest.raises(Error):
        display.plan(client, {}, display.prepare({"model": "owner.asm"}, "activate"))


def test_new_capability_already_active_noop_still_requires_complete_structure(monkeypatch):
    value = observed()
    value["presentation"]["target_active"] = True
    value["models"]["owner.asm"]["exploded_states"] = None
    monkeypatch.setattr(engine, "session", lambda _: {"models": list(value["models"])})
    monkeypatch.setattr(engine, "store_directory", lambda *_: None)
    monkeypatch.setattr(display, "snapshot", lambda *_: value)
    client = SimpleNamespace(require_capability=lambda *_: None)
    with pytest.raises(Error):
        display.plan(client, {}, display.prepare({"model": "owner.asm"}, "activate"))
