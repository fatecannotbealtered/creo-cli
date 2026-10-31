"""Deterministic contract counterexamples; not native Creo qualification."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from creo_cli import appearance, display, driver, engine, presentation, registry  # noqa: F401
from creo_cli.core import Error
from tests.physical_observation_fixture import physical


def cosmetic(rgb=None):
    return {
        "rgb": rgb or [0.2, 0.4, 0.6],
        "ambient": 0.3,
        "diffuse": 0.7,
        "highlight": 0.0,
        "shininess": 0.2,
        "transparency": 0.0,
        "highlight_rgb": [1.0, 1.0, 1.0],
        "reflection": 0.0,
        "name": "sample",
        "label": "",
        "description": "",
        "keywords": "",
    }


def model(name, kind="part"):
    return {
        "model": name,
        "type": kind,
        "modified": False,
        "material": "AL",
        "mass_properties": {"volume": 100, "density": 2.7},
        "bbox": [[0, 0, 0], [10, 10, 1]],
        "family": {"complete": True, "kind": "standalone"},
        "units": {"length": "mm", "mass": "tonne"},
        "bodies": [{"id": "1", "name": "fixture-body", "state": "BODY_STATE_ACTIVE"}],
    }


def state(name):
    result = {
        "complete": True,
        "model": name,
        "scope": "source_part",
        "selection_model": name,
        "selection_model_type": "part",
        "appearance": cosmetic(),
        "assignments": [],
        "modified": False,
        "source": appearance.SOURCE,
    }
    bind_source(result)
    return result


def repeated():
    models = {
        "shared.prt": model("shared.prt"),
        "other.prt": model("other.prt"),
        "holdout.asm": model("holdout.asm", "assembly"),
    }
    models["holdout.asm"]["components"] = [
        {"id": "40", "model": "shared.prt", "constraints": [{"offset": 0}]},
        {"id": "41", "model": "shared.prt", "constraints": [{"offset": 20}]},
    ]
    return {
        "models": models,
        "colors": {name: state(name) for name in ("shared.prt", "other.prt")},
        "physical_materials": {
            name: physical(models[name]) for name in ("shared.prt", "other.prt")
        },
        "geometry": {"model": "shared.prt", "items": [{"ref": "surface:8", "area": 100}]},
        "affected_occurrences": [
            {"assembly": "holdout.asm", "component_path": ["40"]},
            {"assembly": "holdout.asm", "component_path": ["41"]},
        ],
    }


def intended(before, **fields):
    return {
        "scope": "source_part",
        "source_file_authorized": True,
        "affected_occurrences": deepcopy(before["affected_occurrences"]),
        "rgb": [0.123456789123, 0.8, 0.1],
        "reference_action": "create_and_bind",
        "reference_replacement_authorized": True,
        **fields,
    }


def planned(monkeypatch, before, request=None, restore=False):
    client = Mock(spec=["require_capability"])
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(before))
    monkeypatch.setattr(engine, "session", lambda c: {"models": list(before["models"])})
    monkeypatch.setattr(engine, "store_directory", lambda *a: None)
    pre = {"model": "shared.prt", "request": request or intended(before), "restore": restore}
    return client, appearance.plan(client, {}, pre)


def successful_after(before, rgb=None, *, replace=True):
    after = deepcopy(before)
    after["models"]["shared.prt"]["modified"] = True
    after["colors"]["shared.prt"]["modified"] = True
    after["physical_materials"]["shared.prt"]["modified"]["value"] = True
    after["colors"]["shared.prt"]["appearance"]["rgb"] = rgb or intended(before)["rgb"]
    if replace:
        after["colors"]["shared.prt"]["appearance"]["name"] = "native_allocated_fixture_41"
    bind_source(after["colors"]["shared.prt"])
    return after


def bind_source(current):
    current["assignments"] = (
        []
        if current["appearance"] is None
        else [
            {
                "item_type": "model",
                "item_id": None,
                "appearance": deepcopy(current["appearance"]),
                "selection_model": current["model"],
                "selection_model_type": "part",
                "texture_count": 0,
                "texture_inventory_complete": True,
                "textures": [],
            }
        ]
    )


def test_repeat_inventory_keeps_both_occurrences():
    before = repeated()
    assert appearance.occurrences(before["models"], "shared.prt") == before["affected_occurrences"]


def test_nested_inventory_keeps_root_paths_without_name_collapsing():
    before = repeated()
    before["models"]["top.asm"] = model("top.asm", "assembly")
    before["models"]["top.asm"]["components"] = [{"id": "12", "model": "holdout.asm"}]
    actual = appearance.occurrences(before["models"], "shared.prt")
    assert len(actual) == 4
    assert {tuple(row["component_path"]) for row in actual if row["assembly"] == "top.asm"} == {
        ("12", "40"),
        ("12", "41"),
    }


def test_missing_repeated_authorization_is_refused_before_dispatch(monkeypatch):
    before = repeated()
    request = intended(before, affected_occurrences=before["affected_occurrences"][:1])
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, request)
    assert caught.value.code == "E_FORBIDDEN"
    assert caught.value.details["required"] == before["affected_occurrences"]


def test_unknown_source_or_cycle_does_not_claim_complete_influence():
    before = repeated()
    before["models"]["holdout.asm"]["components"][0]["model"] = "absent.prt"
    with pytest.raises(Error) as caught:
        appearance.occurrences(before["models"], "shared.prt")
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


def test_exact_rgb_readback_and_same_observation_binding(monkeypatch):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    after = successful_after(before)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    result, checks = plan.verify(client, {})
    assert all(row["passed"] for row in checks["checks"])
    assert result["after"] == after
    assert driver._effect_observation(plan, client) == after
    assert driver._effect_observation(plan, object()) is None
    plan.request["rgb"] = [1, 0, 0]
    assert driver._effect_observation(plan, client) is None


def test_retained_f29_native_identifier_rename_stays_a_failed_protection(monkeypatch):
    if not (Path(__file__).parent / "data/native-f29-appearance-identity.json").exists():
        pytest.skip("Private native observations are outside the public snapshot")
    native = json.loads(
        (Path(__file__).parent / "data/native-f29-appearance-identity.json").read_text(
            encoding="utf-8"
        )
    )
    before = repeated()
    before["colors"]["shared.prt"]["appearance"] = deepcopy(native["before"])
    bind_source(before["colors"]["shared.prt"])
    preserve = intended(
        before,
        rgb=native["requested_rgb"],
        reference_action="preserve",
        reference_replacement_authorized=False,
    )
    # The original unauthorized real recolor is now refused before any write.
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before, preserve)
    assert caught.value.code == "E_UNSUPPORTED"
    # A preserve-mode no-op still rejects the independently retained changed Name.
    preserve["rgb"] = native["before"]["rgb"]
    client, plan = planned(monkeypatch, before, preserve)
    after = successful_after(before, native["before"]["rgb"], replace=False)
    after["colors"]["shared.prt"]["appearance"]["name"] = native["after"]["name"]
    bind_source(after["colors"]["shared.prt"])
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    results = {check["check"]: check["passed"] for check in verification["checks"]}
    assert results["requested_native_appearance"] is True
    assert results["non_rgb_cosmetic_properties_preserved"] is False
    assert results["native_reference_identity_preserved"] is False
    assert results["physical_and_non_target_state_unchanged"] is True
    assert results["complete_affected_occurrence_set_unchanged"] is True
    assert driver._effect_observation(plan, client) is None


def test_full_recorded_restore_still_requires_the_exact_native_identifier(monkeypatch):
    before = repeated()
    request = intended(before)
    request.pop("rgb")
    request["reference_action"] = "preserve"
    request["reference_replacement_authorized"] = False
    request["appearance"] = deepcopy(before["colors"]["shared.prt"]["appearance"])
    client, plan = planned(monkeypatch, before, request, restore=True)
    after = successful_after(before)
    after["colors"]["shared.prt"]["appearance"] = deepcopy(request["appearance"])
    after["colors"]["shared.prt"]["appearance"]["name"] = "ref_color41"
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert (
        next(
            check["passed"]
            for check in verification["checks"]
            if check["check"] == "requested_native_appearance"
        )
        is False
    )
    assert driver._effect_observation(plan, client) is None


@pytest.mark.parametrize(
    "changed", ("density", "geometry", "constraints", "other_color", "other_dirty")
)
def test_cosmetic_success_cannot_qualify_protected_changes(monkeypatch, changed):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    after = successful_after(before)
    if changed == "density":
        after["models"]["shared.prt"]["mass_properties"]["density"] = 5
    elif changed == "geometry":
        after["geometry"]["items"][0]["area"] = 101
    elif changed == "constraints":
        after["models"]["holdout.asm"]["components"][1]["constraints"][0]["offset"] = 21
    elif changed == "other_color":
        after["colors"]["other.prt"]["appearance"]["rgb"] = [1, 0, 0]
    else:
        after["models"]["other.prt"]["modified"] = True
        after["colors"]["other.prt"]["modified"] = True
        after["physical_materials"]["other.prt"]["modified"]["value"] = True
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert not all(row["passed"] for row in verification["checks"])
    assert driver._effect_observation(plan, client) is None


def test_rounded_rgb_cannot_pass_exact_request(monkeypatch):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    after = successful_after(before, [0.123456789, 0.8, 0.1])
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert (
        next(
            row for row in verification["checks"] if row["check"] == "requested_native_appearance"
        )["passed"]
        is False
    )


def test_dirty_only_failure_is_not_unchanged(monkeypatch):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    after = deepcopy(before)
    after["models"]["shared.prt"]["modified"] = True
    after["colors"]["shared.prt"]["modified"] = True
    after["physical_materials"]["shared.prt"]["modified"]["value"] = True
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    assert plan.failure_unchanged(plan.observe(client)) is False


def test_readback_error_cannot_reuse_prior_passing_snapshot(monkeypatch):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: successful_after(before))
    plan.verify(client, {})
    assert driver._effect_observation(plan, client) is not None
    failed = Mock(side_effect=Error("E_VERIFY_INCOMPLETE", "native read unavailable"))
    monkeypatch.setattr(appearance, "snapshot", failed)
    with pytest.raises(Error):
        plan.verify(client, {})
    assert driver._effect_observation(plan, client) is None


def test_failure_settlement_uses_same_complete_modified_observation(monkeypatch):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    dirty = deepcopy(before)
    dirty["models"]["shared.prt"]["modified"] = True
    dirty["colors"]["shared.prt"]["modified"] = True
    dirty["physical_materials"]["shared.prt"]["modified"]["value"] = True
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(dirty))
    assert plan.failure_unchanged(plan.observe(client)) is False
    assert plan._settled_observation(plan, client) == dirty
    dirty["models"]["shared.prt"]["modified"] = False
    assert plan._settled_observation(plan, client)["models"]["shared.prt"]["modified"] is True
    assert plan._settled_observation(plan, object()) is None
    plan.target = "other.prt"
    assert plan._settled_observation(plan, client) is None


@pytest.mark.parametrize("default", (True, False))
def test_restore_full_recorded_appearance_or_default(monkeypatch, default):
    before = repeated()
    restore_value = None if default else cosmetic([0.9, 0.8, 0.7])
    request = intended(before)
    request.pop("rgb")
    request["appearance"] = restore_value
    if default:
        request["reference_action"] = "preserve"
        request["reference_replacement_authorized"] = False
    client, plan = planned(monkeypatch, before, request, True)
    after = successful_after(before)
    after["colors"]["shared.prt"]["appearance"] = deepcopy(restore_value)
    if not default:
        after["colors"]["shared.prt"]["appearance"]["name"] = "native_allocated_restore_42"
    bind_source(after["colors"]["shared.prt"])
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert all(row["passed"] for row in verification["checks"])


def test_restore_does_not_accept_display_rounded_rgb(monkeypatch):
    before = repeated()
    request = intended(before)
    request.pop("rgb")
    request["appearance"] = cosmetic([0.123456789123, 0.8, 0.1])
    client, plan = planned(monkeypatch, before, request, True)
    after = successful_after(before, [0.123456789, 0.8, 0.1])
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert (
        next(
            row for row in verification["checks"] if row["check"] == "requested_native_appearance"
        )["passed"]
        is False
    )


def test_instance_override_and_source_false_are_refused_before_cad(monkeypatch):
    request = intended(repeated(), scope="instance")
    monkeypatch.setattr(appearance, "read_request", lambda p: request)
    with pytest.raises(Error) as caught:
        appearance.prepare({"model": "SHARED.PRT", "request": "color.json"})
    assert caught.value.code == "E_UNSUPPORTED"
    request["scope"] = "source_part"
    request["source_file_authorized"] = False
    with pytest.raises(Error) as caught:
        appearance.prepare({"model": "shared.prt", "request": "color.json"})
    assert caught.value.code == "E_FORBIDDEN"


@pytest.mark.parametrize("kind", ("surface", "texture"))
def test_surface_overrides_and_textures_are_explicitly_refused(monkeypatch, kind):
    before = repeated()
    assignment = {
        "item_type": "ITEM_SURFACE" if kind == "surface" else "model",
        "item_id": "88" if kind == "surface" else None,
        "appearance": cosmetic(),
        "texture_count": 0 if kind == "surface" else 1,
        "texture_inventory_complete": True,
        "textures": []
        if kind == "surface"
        else [
            {
                "complete": True,
                "type": "COLOR_TEXTURE",
                "file_path": "owned-texture.png",
                "placement": None,
            }
        ],
    }
    before["colors"]["shared.prt"]["assignments"] = [assignment]
    with pytest.raises(Error) as caught:
        planned(monkeypatch, before)
    assert caught.value.code == "E_UNSUPPORTED"


@pytest.mark.parametrize(
    "kind", ("empty_slots", "new_texture", "new_face", "mismatched_source_assignment")
)
def test_after_source_assignment_inventory_is_independently_required(monkeypatch, kind):
    before = repeated()
    client, plan = planned(monkeypatch, before)
    after = successful_after(before)
    current = after["colors"]["shared.prt"]
    row = {
        "item_type": "model",
        "item_id": None,
        "selection_model": current["model"],
        "selection_model_type": "part",
        "appearance": deepcopy(current["appearance"]),
        "texture_count": 3,
        "texture_inventory_complete": True,
        "textures": [
            {"complete": True, "type": texture_type, "file_path": "", "placement": None}
            for texture_type in ("BUMP_TEXTURE", "COLOR_TEXTURE", "DECAL_TEXTURE")
        ],
    }
    if kind == "new_texture":
        row["textures"][0]["file_path"] = "new-texture.png"
    elif kind == "new_face":
        row["item_type"], row["item_id"] = "ITEM_SURFACE", "88"
    elif kind == "mismatched_source_assignment":
        row["appearance"]["rgb"] = [1, 0, 0]
    current["assignments"] = [row]
    monkeypatch.setattr(appearance, "snapshot", lambda c, n: deepcopy(after))
    _, verified = plan.verify(client, {})
    assert all(check["passed"] for check in verified["checks"]) is (kind == "empty_slots")


def test_texture_count_without_complete_native_slot_getters_is_incomplete():
    current = state("shared.prt")
    current["assignments"] = [
        {"item_type": "model", "item_id": None, "appearance": cosmetic(), "texture_count": 3}
    ]
    with pytest.raises(Error) as caught:
        appearance.validate_color_state(current, "shared.prt")
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("margin", (-0.01, 0.41, float("nan"), float("inf")))
def test_invalid_fit_margin_refuses_without_native_dispatch(margin):
    with pytest.raises(Error) as caught:
        display.prepare({"model": "phone_demo.asm", "margin": margin}, "fit")
    assert caught.value.code == "E_VALIDATION"


def explosion(exploded):
    return {
        "complete": True,
        "is_exploded": exploded,
        "active_state_id": "1",
        "states": [
            {
                "id": "1",
                "name": "DIAGONAL",
                "active": True,
                "is_default": False,
                "moves": [
                    {
                        "type": "translate",
                        "components": ["40"],
                        "component_paths": [["40"]],
                        "direction": [0.6, 0.8, 0.0],
                        "distance": 7.0,
                    }
                ],
            }
        ],
        "context": {
            "complete": True,
            "kind": "assembly",
            "assembly_context_admitted": True,
            "target_model": "holdout.asm",
            "current_model": "holdout.asm",
            "window_model": "holdout.asm",
            "current_model_type": "assembly",
            "window_model_type": "assembly",
            "window_id": "1",
            "source": presentation.ASSEMBLY_CONTEXT_SOURCE,
        },
        "display_readback": {
            "source": "Assembly.GetIsExploded",
            "complete": True,
            "status": "observed",
            "value": exploded,
        },
    }


def test_unexplode_normalization_keeps_position_drift_protection():
    before = {
        "presentation": {},
        "models": {
            "holdout.asm": model("holdout.asm", "assembly"),
            "shared.prt": model("shared.prt"),
        },
        "colors": {},
    }
    before["models"]["holdout.asm"] |= {
        "explosion": explosion(True),
        "bbox": [[14.2, 25.6, 30], [24.2, 35.6, 31]],
        "components": [
            {
                "id": "40",
                "model": "shared.prt",
                "position": {
                    "origin": [14.2, 25.6, 30],
                    "x_axis": [1, 0, 0],
                    "y_axis": [0, 1, 0],
                    "z_axis": [0, 0, 1],
                },
                "component_path_transform": {
                    "origin": [14.2, 25.6, 30],
                    "x_axis": [1, 0, 0],
                    "y_axis": [0, 1, 0],
                    "z_axis": [0, 0, 1],
                },
            }
        ],
    }
    after = deepcopy(before)
    after["models"]["holdout.asm"]["explosion"] = explosion(False)
    after["models"]["holdout.asm"]["bbox"] = [[10, 20, 30], [20, 30, 31]]
    for field in ("position", "component_path_transform"):
        after["models"]["holdout.asm"]["components"][0][field]["origin"] = [10, 20, 30]
    assert presentation.equivalent(
        display.physical(before, "holdout.asm", "unexplode", project_unexplode=True),
        display.physical(after, "holdout.asm", "unexplode", project_unexplode=True),
    )
    for key in ("position", "component_path_transform"):
        after["models"]["holdout.asm"]["components"][0][key]["origin"][0] += 0.01
    assert not presentation.equivalent(
        display.physical(before, "holdout.asm", "unexplode", project_unexplode=True),
        display.physical(after, "holdout.asm", "unexplode", project_unexplode=True),
    )


def displayed_scene(target="holdout.asm"):
    source = repeated()
    source.pop("geometry")
    source.pop("affected_occurrences")
    source["presentation"] = {
        "model": target,
        "target_active": True,
        "active_model": target,
        "current_model": target,
        "current_model_type": "assembly",
        "window_model": target,
        "window_model_type": "assembly",
        "context_complete": True,
        "named_views": ["FRONT", "BACK", "TOP", "BOTTOM", "LEFT", "RIGHT"],
        "named_views_complete": True,
        "modified": False,
        "screen": {"pan_x": 0, "pan_y": 0, "zoom": 1.0},
        "view_transform": [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]],
        "component_visibility": [
            {"id": "40", "model": "shared.prt", "hidden": False},
            {"id": "41", "model": "shared.prt", "hidden": False},
        ],
    }
    return source


def planned_display(monkeypatch, before, action, **opts):
    client = object()
    monkeypatch.setattr(display, "snapshot", lambda c, n: deepcopy(before))
    monkeypatch.setattr(engine, "session", lambda c: {"models": list(before["models"])})
    monkeypatch.setattr(engine, "store_directory", lambda *a: None)
    pre = display.prepare({"model": "holdout.asm", **opts}, action)
    return client, display.plan(client, opts, pre)


@pytest.mark.parametrize("wrong_occurrence", (False, True))
def test_visibility_changes_only_the_exact_repeated_occurrence(monkeypatch, wrong_occurrence):
    before = displayed_scene()
    client, plan = planned_display(
        monkeypatch, before, "visibility", component="40", state="hidden"
    )
    after = deepcopy(before)
    after["presentation"]["component_visibility"][int(wrong_occurrence)]["hidden"] = True
    monkeypatch.setattr(display, "snapshot", lambda c, n: deepcopy(after))
    _, verification = plan.verify(client, {})
    assert all(row["passed"] for row in verification["checks"]) is not wrong_occurrence


@pytest.mark.parametrize("drift", (None, "zoom", "orientation", "density"))
def test_fit_protects_requested_margin_orientation_and_physical_state(monkeypatch, drift):
    before = displayed_scene()
    client, plan = planned_display(monkeypatch, before, "fit", margin=0.1, view="current")
    after = deepcopy(before)
    after["presentation"]["screen"]["zoom"] = 0.8
    if drift == "zoom":
        after["presentation"]["screen"]["zoom"] = 1.0
    elif drift == "orientation":
        after["presentation"]["view_transform"][0][0] = -1.0
    elif drift == "density":
        after["models"]["shared.prt"]["mass_properties"]["density"] = 9.0
    monkeypatch.setattr(display, "snapshot", lambda c, n: deepcopy(after))
    proof = {
        "fit": {
            "source": "WWindow.Refit/Window.SetScreenTransform",
            "margin": 0.1,
            "refit_zoom": 1.0,
            "view": "current",
            "orientation": [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]],
        }
    }
    _, verification = plan.verify(client, proof)
    assert all(row["passed"] for row in verification["checks"]) is (drift is None)
    assert (driver._effect_observation(plan, client) is not None) is (drift is None)


def test_named_view_fit_requires_complete_context_without_desktop_fallback(monkeypatch):
    before = displayed_scene()
    before["presentation"]["target_active"] = False
    with pytest.raises(Error) as caught:
        planned_display(monkeypatch, before, "fit", margin=0.1, view="isometric")
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert "Session.GetCurrentModel" in caught.value.message


@pytest.mark.parametrize("missing_inventory", (False, True))
def test_fit_named_orientation_is_checked_before_dispatch(monkeypatch, missing_inventory):
    before = displayed_scene()
    before["presentation"]["named_views"] = ["TOP"]
    before["presentation"]["named_views_complete"] = not missing_inventory
    with pytest.raises(Error) as caught:
        planned_display(monkeypatch, before, "fit", margin=0.1, view="isometric")
    assert caught.value.code == ("E_VERIFY_INCOMPLETE" if missing_inventory else "E_NOT_FOUND")


@pytest.mark.parametrize(
    "broken", (None, "null_current_model", "wrong_current_type", "false_context")
)
def test_window_owner_is_not_independent_current_model_proof(broken):
    observed = displayed_scene()["presentation"] | {
        "complete": True,
        "model": "holdout.asm",
        "source": display.SOURCE,
        "window": "1001",
        "active_window": "1001",
    }
    if broken == "null_current_model":
        observed["current_model"] = None
    elif broken == "wrong_current_type":
        observed["current_model_type"] = "part"
    elif broken == "false_context":
        observed["context_complete"] = False
    client = Mock()
    client.op.return_value = observed
    if broken is None:
        assert display.state(client, "holdout.asm")["target_active"] is True
    else:
        with pytest.raises(Error) as caught:
            display.state(client, "holdout.asm")
        assert caught.value.code == "E_VERIFY_INCOMPLETE"


def render_observation():
    return {
        "complete": True,
        "model": "shared.prt",
        "window": "1",
        "active_window": "1",
        "active_model": "shared.prt",
        "current_model": "shared.prt",
        "current_model_type": "part",
        "window_model": "shared.prt",
        "window_model_type": "part",
        "context_complete": True,
        "modified": False,
        "view_transform": [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]],
        "screen": {"pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0},
        "datums": {
            key: "yes"
            for key in ("display_planes", "display_axes", "display_points", "display_coord_sys")
        },
        "native_part_appearances": {
            "shared.prt": state("shared.prt"),
            "other.prt": state("other.prt"),
        },
    }


@pytest.mark.parametrize(
    "broken",
    (
        None,
        "missing_map",
        "missing_part",
        "appearance_field",
        "rgb_channel",
        "wrong_source",
        "wrong_model",
        "assignment_field",
        "current_model_absent",
        "current_model_wrong",
    ),
)
def test_render_requires_complete_native_colors_for_all_session_parts(monkeypatch, broken):
    observed = render_observation()
    colors = observed["native_part_appearances"]
    if broken == "missing_map":
        observed.pop("native_part_appearances")
    elif broken == "missing_part":
        colors.pop("other.prt")
    elif broken == "appearance_field":
        colors["shared.prt"]["appearance"].pop("reflection")
    elif broken == "rgb_channel":
        colors["shared.prt"]["appearance"]["rgb"] = [0.1, 0.2]
    elif broken == "wrong_source":
        colors["shared.prt"]["source"] = "cached_palette"
    elif broken == "wrong_model":
        colors["shared.prt"]["model"] = "other.prt"
    elif broken == "assignment_field":
        colors["shared.prt"]["assignments"] = [{"item_type": "model", "texture_count": 0}]
    elif broken == "current_model_absent":
        observed["current_model"] = None
    elif broken == "current_model_wrong":
        observed["current_model"] = "other.prt"
    monkeypatch.setattr(engine, "session", lambda c: {"models": ["shared.prt", "other.prt"]})
    client = Mock()
    client.op.return_value = deepcopy(observed)
    if broken is None:
        assert presentation.render_state(client, "shared.prt") == observed
    else:
        with pytest.raises(Error) as caught:
            presentation.render_state(client, "shared.prt")
        assert caught.value.code == "E_VERIFY_INCOMPLETE"
