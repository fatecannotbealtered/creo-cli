"""Bounded observation reuse with direct stubs: no HTTP server, CAD or product EXE."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from creo_cli import (
    bom,
    driver,
    engine,
    registry,  # noqa: F401 - initialize the registry before importing a leaf
)
from creo_cli.commands import detailing
from creo_cli.core import Error, digest


def path_plan():
    return SimpleNamespace(
        op="drawing.add-bom",
        target="rig.drw",
        request={"model": "rig.drw"},
        preview={"command": "drawing bom add"},
        arguments={},
        binding={},
        effects=None,
    )


def path_context(monkeypatch, tmp_path, description):
    monkeypatch.setenv("CREO_CLI_WORKSPACE", str(tmp_path))
    session = {"models": ["rig.drw", "unrelated.prt"], "working_directory": str(tmp_path)}
    monkeypatch.setattr(engine, "session", lambda client: session)
    show = Mock(side_effect=AssertionError("affected_paths must not re-read the closure"))
    monkeypatch.setattr(engine, "show", show)
    nodes = [{"identity": "rig.drw", "revision": "first", "description": description}]
    closure = Mock(return_value=nodes)
    monkeypatch.setattr(driver.model_dependencies, "closure", closure)
    return closure, show


def test_affected_paths_uses_the_same_closure_description(monkeypatch, tmp_path):
    description = {"model": "rig.drw", "origin": str(tmp_path / "rig.drw.1")}
    closure, show = path_context(monkeypatch, tmp_path, description)
    assert driver.affected_paths(object(), path_plan()) == [(str(tmp_path), "change")]
    closure.assert_called_once()
    show.assert_not_called()


@pytest.mark.parametrize("description", (None, {}, {"model": "different.drw"}))
def test_missing_closure_description_fails_without_fallback(monkeypatch, tmp_path, description):
    _, show = path_context(monkeypatch, tmp_path, description)
    with pytest.raises(Error) as caught:
        driver.affected_paths(object(), path_plan())
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details == {"model": "rig.drw"}
    show.assert_not_called()


@pytest.mark.parametrize("unreadable", (True, False))
def test_closure_origin_keeps_original_fail_closed_checks(monkeypatch, tmp_path, unreadable):
    description = {
        "model": "rig.drw",
        "origin": None if unreadable else str(tmp_path.parent / "foreign" / "rig.drw.1"),
        "origin_readback": {"complete": not unreadable},
    }
    description["origin_readback"]["value"] = description["origin"]
    _, show = path_context(monkeypatch, tmp_path, description)
    with pytest.raises(Error) as caught:
        driver.affected_paths(object(), path_plan())
    assert caught.value.code == ("E_VERIFY_INCOMPLETE" if unreadable else "E_FORBIDDEN")
    show.assert_not_called()


def driver_context(monkeypatch, plan):
    """Stop at the existing execute boundary; no persistence or transport is used."""
    client = SimpleNamespace(
        url="fixture-no-network",
        _guard_pending_read=Mock(),
        _native_read_pending=None,
        _native_diagnostic_stop=None,
    )
    target = {
        "mode": "session",
        "engine_id": "creo",
        "instance_id": "fixture",
        "object_id": plan.target,
        "locator": "http://fixture.invalid/models/" + plan.target,
    }
    grant = SimpleNamespace(
        record={"scope_id": "fixture"}, max_operations=None, missing=Mock(return_value={})
    )
    run = {
        "operation_id": "a" * 32,
        "command": plan.preview["command"],
        "status": "planned",
        "driver_binding": {"driver_scope_sha256": digest(grant.record)},
        "driver_plan": {
            "effects": ["change"],
            "base_snapshot": driver.snapshot({}),
            "capability_id": "fixture",
            "plan_id": "b" * 32,
            "target": target,
            "authorization_scope_id": "fixture",
        },
    }
    monkeypatch.setattr(driver, "target", lambda client, p: target)
    monkeypatch.setattr(driver, "scope", lambda: grant)
    monkeypatch.setattr(driver, "require_clear", Mock())
    monkeypatch.setattr(driver.safety, "actor", Mock())
    monkeypatch.setattr(driver.safety, "policy", lambda: {"confirm_allowed": True})
    monkeypatch.setattr(driver.safety, "scope", lambda *args: {})
    monkeypatch.setattr(driver.safety, "require_write", Mock())
    monkeypatch.setattr(driver.safety, "token_operation", lambda token: run["operation_id"])
    monkeypatch.setattr(driver.safety, "consume", Mock())
    monkeypatch.setattr(driver.operations, "get", lambda ident: run)
    monkeypatch.setattr(driver.operations, "update", Mock())
    return client, run


def test_last_fresh_closure_still_binds_drift_at_confirmation(monkeypatch, tmp_path):
    description = {
        "model": "rig.drw",
        "type": "drawing",
        "models": [],
        "origin": str(tmp_path / "rig.drw.1"),
    }
    closure, show = path_context(monkeypatch, tmp_path, description)
    first = {
        "identity": "rig.drw",
        "revision": "preflight-reading",
        "children": [],
        "description": description,
    }
    fresh = first | {"revision": "fresh-drift"}
    closure.side_effect = [[first], [fresh]]
    plan = path_plan()
    client, _ = driver_context(monkeypatch, plan)
    # A prior phase may have observed an earlier revision. write must obtain
    # its own fresh closure once, then share it only inside this write phase.
    assert driver.model_dependencies.closure(client, {"rig.drw"}) == [first]

    def refuse_drift(token, bound, *, expected_binding):
        assert isinstance(expected_binding, dict)
        assert bound["driver_dependencies"] == [{"identity": "rig.drw", "revision": "fresh-drift"}]
        raise Error("E_CONFLICT", "fixture token bound to the earlier revision")

    monkeypatch.setattr(driver.safety, "consume", refuse_drift)
    execute = Mock(side_effect=AssertionError("drift must refuse before execution"))
    monkeypatch.setattr(engine, "execute", execute)
    with pytest.raises(Error, match="earlier revision") as caught:
        driver.write("drawing bom add", {"confirm": "fixture-token"}, client, plan)
    assert caught.value.code == "E_CONFLICT"
    assert closure.call_count == 2
    show.assert_not_called()
    execute.assert_not_called()


@pytest.fixture
def annotation_case(monkeypatch):
    header = ["ITEM\nNO", "PART NUMBER", "QTY", "DESCRIPTION", "NOTES"]
    table = {
        "id": "0",
        "sheet": 1,
        "segments": 1,
        "cells": [header, ["1", "P", "1", "", ""]],
        "cell_references": [{"row": 2, "model": "p.prt", "assembly": "rig.asm"}],
        "outline": [[10, 30], [30, 40]],
        "at": [10, 40],
        "size": [20, 10],
    }
    components = [{"id": "40", "model": "p.prt", "status": "FEAT_ACTIVE", "placed": True}]
    before = {
        "model": "rig.drw",
        "models": ["rig.asm"],
        "tables": [],
        "notes": [],
        "views": [
            {
                "id": "1",
                "name": "FRONT",
                "sheet": 1,
                "model": "rig.asm",
                "outline": [[100, 100], [150, 150]],
            }
        ],
        "sheets": [{"number": 1, "width": 420, "height": 297, "units": "mm"}],
    }
    note = {
        "id": "9",
        "displayed_text": "1",
        "leaders_complete": True,
        "leaders": [{"root": "rig.asm", "model": "p.prt", "component_path": [40], "view": "FRONT"}],
    }
    state = SimpleNamespace(
        before=before,
        drawing=None,
        assembly={"model": "rig.asm", "components": components},
        assembly_error=None,
        calls=[],
    )

    def show(client, model):
        state.calls.append(model)
        if model == "rig.asm":
            if state.assembly_error is not None:
                raise state.assembly_error
            return state.assembly
        if isinstance(state.drawing, Error):
            raise state.drawing
        return state.drawing

    monkeypatch.setattr(detailing, "_reading", lambda client, name: deepcopy(state.before))
    monkeypatch.setattr(engine, "show", show)
    monkeypatch.setattr(
        bom,
        "template",
        lambda *args: (
            {"path": "fixture.tbl", "sha256": "fixture"},
            {"units": "mm", "width": 20, "header_height": 5, "row_height": 5},
        ),
    )
    monkeypatch.setattr(bom, "region", lambda *args: {"layout_feedback": {}})
    monkeypatch.setattr(detailing.drawing_warnings, "feedback", lambda *args, **kwargs: {})

    def make(kind):
        client = SimpleNamespace(require_capability=Mock())
        if kind == "bom":
            plan = detailing._plan_bom(
                client, {}, {"name": "rig.drw", "table": "fixture", "at": [10, 40]}
            )
            state.drawing = deepcopy(before) | {"tables": [deepcopy(table)]}
        else:
            state.before["tables"] = [deepcopy(table)]
            plan = detailing._plan_balloons(
                client, {"table": "0", "view": "FRONT"}, {"name": "rig.drw"}
            )
            state.drawing = deepcopy(state.before) | {"notes": [deepcopy(note)]}
        state.calls.clear()
        return client, plan

    return state, make


@pytest.mark.parametrize("kind,inventory", (("bom", "tables"), ("balloons", "notes")))
def test_verified_inventory_is_independent_same_shape_and_copied(annotation_case, kind, inventory):
    state, make = annotation_case
    client, plan = make(kind)
    setter = {"model": "rig.drw", inventory: [{"id": "setter-only"}]}
    _, verification = plan.verify(client, setter)
    assert all(row["passed"] is True for row in verification["checks"])
    assert state.calls == ["rig.drw", "rig.asm"]
    assert plan.verified_observation == state.drawing[inventory]
    assert plan.verified_observation != setter[inventory]
    assert isinstance(plan.verified_observation, type(plan.before))
    assert plan.verified_observation == plan.observe(client)
    retained = deepcopy(plan.verified_observation)
    state.drawing[inventory][0]["id"] = "changed-after-reading"
    assert plan.verified_observation == retained


@pytest.mark.parametrize("kind,inventory", (("bom", "tables"), ("balloons", "notes")))
def test_missing_inventory_is_not_cached_as_empty(annotation_case, kind, inventory):
    state, make = annotation_case
    client, plan = make(kind)
    del state.drawing[inventory]
    with pytest.raises(Error) as caught:
        plan.verify(client, {})
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert state.calls == ["rig.drw"]
    assert plan.verified_observation is None


@pytest.mark.parametrize("kind", ("bom", "balloons"))
def test_wrong_native_table_or_balloon_association_still_fails(annotation_case, kind):
    state, make = annotation_case
    client, plan = make(kind)
    if kind == "bom":
        state.drawing["tables"][0]["cells"][1][2] = "99"
    else:
        state.drawing["notes"][0]["leaders"][0]["component_path"] = [99]
    _, verification = plan.verify(client, {})
    assert any(row["passed"] is False for row in verification["checks"])
    assert plan.verified_observation is None


def wrong_annotation_identity(state, fault):
    if fault == "wrong_drawing":
        state.drawing["model"] = "other.drw"
    elif fault == "missing_drawing":
        del state.drawing["model"]
    elif fault == "wrong_association":
        state.drawing["models"] = ["other.asm"]
    elif fault == "missing_association":
        del state.drawing["models"]
    elif fault == "extra_association":
        state.drawing["models"].append("other.asm")
    elif fault == "wrong_assembly":
        state.assembly["model"] = "other.asm"
    elif fault == "missing_assembly":
        del state.assembly["model"]
    else:
        raise AssertionError("unknown isolated identity fault")


@pytest.mark.parametrize("kind", ("bom", "balloons"))
@pytest.mark.parametrize(
    "fault",
    (
        "wrong_drawing",
        "missing_drawing",
        "wrong_association",
        "missing_association",
        "extra_association",
        "wrong_assembly",
        "missing_assembly",
    ),
)
def test_independent_annotation_identity_is_required_before_effect_reuse(
    annotation_case, kind, fault
):
    state, make = annotation_case
    client, plan = make(kind)
    wrong_annotation_identity(state, fault)
    with pytest.raises(Error) as caught:
        plan.verify(client, {"model": "rig.drw", "reply_only": True})
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert plan.verified_observation is None
    assert state.calls == (["rig.drw", "rig.asm"] if fault.endswith("assembly") else ["rig.drw"])


@pytest.mark.parametrize("kind", ("bom", "balloons"))
@pytest.mark.parametrize(
    "fault",
    ("wrong_drawing", "missing_drawing", "wrong_association", "missing_association"),
)
def test_uncached_effect_observation_requires_the_same_drawing(annotation_case, kind, fault):
    state, make = annotation_case
    client, plan = make(kind)
    wrong_annotation_identity(state, fault)
    with pytest.raises(Error) as caught:
        plan.observe(client)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert plan.verified_observation is None
    assert state.calls == ["rig.drw"]


@pytest.mark.parametrize("kind", ("bom", "balloons"))
@pytest.mark.parametrize("code", ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"))
@pytest.mark.parametrize("at_assembly", (False, True))
def test_getter_stop_never_caches_reply_or_adds_a_followup(
    annotation_case, kind, code, at_assembly
):
    state, make = annotation_case
    client, plan = make(kind)
    original = Error(
        code,
        "original fixture native getter",
        {"cause": {"code": "E_BUSY", "message": "nested original cause"}},
    )
    if at_assembly:
        state.assembly_error = original
    else:
        state.drawing = original
    with pytest.raises(Error) as caught:
        plan.verify(client, {"notes": [{"id": "setter-only"}]})
    assert caught.value is original
    assert state.calls == (["rig.drw", "rig.asm"] if at_assembly else ["rig.drw"])
    assert plan.verified_observation is None


@pytest.mark.parametrize("kind", ("bom", "balloons"))
@pytest.mark.parametrize("at_assembly", (False, True))
@pytest.mark.parametrize("missing", (False, True))
def test_preflight_requires_actual_drawing_and_assembly_identity(
    annotation_case, kind, at_assembly, missing
):
    state, make = annotation_case
    reading = state.assembly if at_assembly else state.before
    if missing:
        del reading["model"]
    else:
        reading["model"] = "other.asm" if at_assembly else "other.drw"
    with pytest.raises(Error) as caught:
        make(kind)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert state.calls == (["rig.asm"] if at_assembly else [])


@pytest.mark.parametrize("kind,inventory", (("bom", "tables"), ("balloons", "notes")))
def test_a_new_plan_never_inherits_another_plans_verified_inventory(
    annotation_case, kind, inventory
):
    state, make = annotation_case
    client, first = make(kind)
    first.verify(client, {})
    retained = deepcopy(first.verified_observation)
    assert retained == state.drawing[inventory]
    client, second = make(kind)
    assert second is not first
    assert second.verified_observation is None
    assert state.calls == []
    state.drawing["model"] = "other.drw"
    with pytest.raises(Error) as caught:
        second.verify(client, {})
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert state.calls == ["rig.drw"]
    assert second.verified_observation is None
    assert first.verified_observation == retained


@pytest.mark.parametrize("kind", ("bom", "balloons"))
def test_driver_reuses_verified_inventory_with_equivalent_effects_and_snapshot(
    monkeypatch, annotation_case, kind
):
    monkeypatch.setattr(driver.uuid, "uuid4", lambda: SimpleNamespace(hex="f" * 32))
    state, make = annotation_case
    _, plan = make(kind)
    client, run = driver_context(monkeypatch, plan)
    monkeypatch.setattr(driver, "affected_paths", lambda *args: [])
    monkeypatch.setattr(driver.model_dependencies, "closure", lambda *args: [])
    original_observe = plan.observe
    plan.observe = Mock(side_effect=AssertionError("no post-verification getter"))

    def execute(command, c, p, planned):
        result, verification = p.verify(c, {"model": "rig.drw", "reply_only": True})
        run["status"] = "completed"
        return {
            "status": "completed",
            "result": result,
            "verification": verification | {"status": "passed"},
            "persisted": False,
        }

    monkeypatch.setattr(engine, "execute", execute)
    output = driver.write(plan.preview["command"], {"confirm": "fixture-token"}, client, plan)
    plan.observe.assert_not_called()
    assert state.calls == ["rig.drw", "rig.asm"]
    assert run["driver_effect_readback"] == plan.verified_observation
    observed = original_observe(client)
    equivalent = driver.make_receipt(run | {"driver_effect_readback": observed}, plan, output)
    receipt = output["receipt"]
    assert receipt["outcome"] == equivalent["outcome"]
    assert receipt["outcome"]["change"] == "applied"
    assert receipt["snapshot_after"]["revision"] == equivalent["snapshot_after"]["revision"]
    assert receipt["extensions"]["creo"]["effects_readback"]["after"] == observed


@pytest.mark.parametrize("code", ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"))
def test_driver_pending_priority_keeps_nested_cause_and_queues_no_observation(monkeypatch, code):
    plan = engine.Plan(
        "drawing.add-bom",
        {"model": "rig.drw"},
        "rig.drw",
        {},
        {"command": "drawing bom add"},
        Mock(),
        Mock(side_effect=AssertionError("no getter after stop")),
        [],
    )
    plan.verified_observation = [{"id": "earlier-observation"}]
    client, run = driver_context(monkeypatch, plan)
    monkeypatch.setattr(driver, "affected_paths", lambda *args: [])
    monkeypatch.setattr(driver.model_dependencies, "closure", lambda *args: [])
    original = Error(
        code,
        "original fixture native getter",
        {
            "started": True,
            "native_call_pending": code == "E_NATIVE_READ_PENDING",
            "cause": {"code": "E_BUSY", "message": "nested original cause"},
        },
    )

    def execute(*args, **kwargs):
        run["status"] = "verification_incomplete"
        if code == "E_NATIVE_READ_PENDING":
            client._native_read_pending = original
        else:
            client._native_diagnostic_stop = original
        raise Error("E_VERIFY_INCOMPLETE", "parent verification could not finish")

    monkeypatch.setattr(engine, "execute", execute)
    with pytest.raises(Error) as caught:
        driver.write("drawing bom add", {"confirm": "fixture-token"}, client, plan)
    expected = "E_OUTCOME_UNKNOWN" if code == "E_NATIVE_READ_PENDING" else "E_NATIVE_DIAGNOSTIC"
    assert caught.value.code == expected
    key = "native_read_error" if code == "E_NATIVE_READ_PENDING" else "native_diagnostic_error"
    assert caught.value.details[key]["details"]["cause"] == original.details["cause"]
    assert run["driver_effect_observed"] is False
    plan.observe.assert_not_called()
    plan.verify.assert_not_called()
