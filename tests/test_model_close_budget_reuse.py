"""Bounded close reuse: direct Plan controls and isolated public HTTP process cases.

Public cases use PublicCase.cli, including CREO_CLI_TEST_PUBLIC_COMMAND when set.
The peer, files, scope and operation records are synthetic; no Creo/native calls.
"""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from creo_cli import driver, engine, model_management, registry  # noqa: F401
from creo_cli.commands import model
from creo_cli.core import Error
from tests import test_bom_fresh_closure_reuse as graph_controls
from tests.test_native_read_context import PublicCase, arm, local_retained, pending_context

CLOSE = ("model", "close", "--model", "close.drw")


@pytest.fixture
def context(monkeypatch, tmp_path):
    return graph_controls.context.__wrapped__(monkeypatch, tmp_path)


def close_plan():
    return SimpleNamespace(
        op="model.close",
        target="rig.drw",
        request={"model": "rig.drw"},
        preview={"command": "model close"},
        effects=None,
        arguments={},
        binding={},
    )


def test_close_final_graph_is_shared_by_paths_token_and_clear(context, monkeypatch):
    snapshots = Mock(wraps=driver.model_dependencies.snapshots)
    monkeypatch.setattr(driver.model_dependencies, "snapshots", snapshots)
    assert (
        graph_controls.stopped_write(context, close_plan()).message == "controlled stop at consume"
    )
    context.closure.assert_called_once_with(context.client, {"rig.drw"})
    assert snapshots.call_args.args[0] is context.nodes
    assert (
        context.grant.missing.call_args.kwargs["paths"] == [(str(context.tmp_path), "change")] * 3
    )
    assert context.consume.call_args.args[1]["driver_dependencies"] == [
        {"identity": n["identity"], "revision": n["revision"]} for n in context.nodes
    ]
    context.require_clear.assert_called_once()
    assert context.require_clear.call_args.args[1] == [n["identity"] for n in context.nodes]


def test_close_next_write_has_fresh_graph_and_no_plan_cache(context):
    second = deepcopy(context.nodes)
    second[0]["revision"] = "next-write"
    context.closure.side_effect = [context.nodes, second]
    for _ in range(2):
        assert graph_controls.stopped_write(context, close_plan()).code == "E_CONFLICT"
    assert context.closure.call_count == 2
    assert (
        context.consume.call_args_list[0].args[1]["driver_dependencies"]
        != (context.consume.call_args_list[1].args[1]["driver_dependencies"])
    )


@pytest.mark.parametrize("variant", ("wrong-op", "extra-root", "missing-child"))
def test_close_refuses_wrong_or_incomplete_shared_graph(context, variant):
    p = close_plan()
    if variant == "wrong-op":
        p.op = "model.discard"
    elif variant == "extra-root":
        p.preview["model_footprint"] = ["other.prt"]
    else:
        context.nodes.pop(0)
    assert graph_controls.stopped_write(context, p).code == "E_VERIFY_INCOMPLETE"
    context.consume.assert_not_called()
    assert context.closure.call_count == (1 if variant == "missing-child" else 0)


def management_state(include_target=True):
    names = ["source.prt", "close.drw"] if include_target else ["source.prt"]
    return {
        "completed": True,
        "models": [
            {
                "model": name,
                "modified": False,
                "dependencies_complete": True,
                "dependencies": ["source.prt"] if name.endswith(".drw") else [],
            }
            for name in names
        ],
        "windows": [{"id": name, "model": name} for name in names],
        "active_window": "close.drw" if include_target else None,
        "active_model": "close.drw" if include_target else None,
        "source": "isolated direct state getter",
    }


@pytest.fixture
def close_verifier(monkeypatch, tmp_path):
    monkeypatch.setenv("CREO_CLI_WORKSPACE", str(tmp_path))
    before, after = management_state(), management_state(False)
    client = SimpleNamespace(op=Mock(side_effect=[before, after]), require_capability=Mock())
    monkeypatch.setattr(
        engine,
        "session",
        lambda c: {
            "models": ["close.drw", "source.prt"],
            "working_directory": str(tmp_path),
        },
    )
    monkeypatch.setattr(
        engine,
        "show",
        lambda c, n: {
            "model": n,
            "modified": False,
            "origin": str(tmp_path / (n + ".1")),
        },
    )
    monkeypatch.setattr(model_management, "require_saved_name_before_close", Mock())
    p = model._plan_closing(False)(client, {"model": "close.drw"}, {"name": "close.drw"})
    return SimpleNamespace(client=client, p=p, after=after)


def test_close_first_after_read_is_fresh_and_plan_local_copy(close_verifier):
    c = close_verifier
    assert c.p.verified_observation is None
    _, verification = c.p.verify(c.client, {"model": "close.drw", "erased": True})
    assert c.client.op.call_count == 2  # plan-before, then the first independent after
    assert len(verification["checks"]) == 5
    assert all(row["passed"] is True for row in verification["checks"])
    assert c.p.verified_observation == c.after
    assert c.p.verified_observation is not c.after
    c.after["models"][0]["modified"] = True
    assert c.p.verified_observation["models"][0]["modified"] is False


@pytest.mark.parametrize(
    "variant",
    ("wrong-command", "wrong-client", "wrong-reply", "failed-check", "incomplete", "pending"),
)
def test_close_failed_or_unkeyed_after_cannot_fill_cache(close_verifier, variant):
    c = close_verifier
    c.p.verified_observation = {"stale": True}
    reply = {"model": "close.drw", "erased": True}
    verify_client = c.client
    if variant == "wrong-client":
        verify_client = SimpleNamespace(op=c.client.op, require_capability=Mock())
    if variant == "wrong-command":
        c.p.preview["command"] = "model discard"
    elif variant == "wrong-reply":
        reply["model"] = "other.drw"
    elif variant == "failed-check":
        c.after["models"][0]["modified"] = True
    elif variant == "incomplete":
        c.after.pop("windows")
    elif variant == "pending":
        failure = Error("E_NATIVE_READ_PENDING", "controlled first after is still pending")
        c.client.op.side_effect = failure
    if variant in ("incomplete", "pending"):
        with pytest.raises(Error) as caught:
            c.p.verify(verify_client, reply)
        assert caught.value.code == (
            "E_NATIVE_READ_PENDING" if variant == "pending" else "E_VERIFY_INCOMPLETE"
        )
        if variant == "pending":
            assert caught.value is failure
    else:
        _, verification = c.p.verify(verify_client, reply)
        if variant == "failed-check":
            assert any(row["passed"] is False for row in verification["checks"])
    assert c.p.verified_observation is None


@pytest.fixture
def close_case():
    case = PublicCase()
    case.setUp()
    case.part("source.prt")
    case.part("sibling.prt")
    case.world.drawing_create(
        {"name": "close.drw", "of": "source.prt", "sheet": "a3", "views": "none"}
    )
    case.world.models["close.drw"]["tables"] = [
        {
            "id": "0",
            "rows": 4,
            "columns": 5,
            "cells": [["fixture"]],
            "raw": {"NOTES": None},
            "source": "synthetic saved-table fixture",
        }
    ]
    try:
        yield case
    finally:
        case.doCleanups()


def test_public_close_reuses_only_verified_complete_state(close_case):
    c = close_case
    original_bytes = (c.ws / "close.drw.1").read_bytes()
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    c.world.events.clear()
    result = c.cli(*CLOSE, "--confirm", dry["confirm_token"])["data"]
    ops = c.world.ops()
    close_index = ops.index("model.close")
    assert ops[close_index + 1 :] == ["model.management-state"]
    assert ops.count("model.close") == 1
    assert sum(op == "model.show" and q["model"] == "close.drw" for op, q in c.world.events) == 3
    assert set(c.world.models) == {"source.prt", "sibling.prt"}
    assert (c.ws / "close.drw.1").read_bytes() == original_bytes
    assert result["status"] == "completed"
    assert len(result["verification"]["checks"]) == 5
    assert all(row["passed"] is True for row in result["verification"]["checks"])
    assert result["receipt"]["effects"] == ["session"]
    assert result["receipt"]["outcome"]["execution"] == "completed"


def test_public_close_pending_first_after_retains_parent_without_followup(close_case):
    c = close_case
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    state = arm(c, "busy_started", read="model.management-state", after="model.close")
    c.world.events.clear()
    error = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["operation_id"] == dry["preview"]["operation_id"]
    receipt = error["details"]["receipt"]
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["change"] == "applied"
    assert receipt["outcome"]["persistence"] == "not_applicable"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    assert c.world.ops().count("model.close") == 1
    assert c.world.ops()[state["event_index"] :] == ["model.management-state"]
    context = pending_context(error, "busy_started", "model.management-state")
    local_retained(c, dry["preview"]["operation_id"], error, context)
    events = deepcopy(c.world.events)
    repeated = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=6)["error"]
    assert repeated["code"] == "E_CONFLICT"
    assert c.world.events == events
    assert c.world.ops().count("model.close") == 1
    assert "close.drw" not in c.world.models


def after_state_fault(case, monkeypatch, mutate):
    original = case.world.op
    state = {"closed": False, "reads": 0}

    def op(name, request):
        answer = original(name, request)
        if name == "model.close":
            state["closed"] = True
        elif name == "model.management-state" and state["closed"]:
            state["reads"] += 1
            if state["reads"] == 1:
                mutate(answer)
        return answer

    monkeypatch.setattr(case.world, "op", op)
    return state


def test_public_close_incomplete_after_is_not_success(close_case, monkeypatch):
    c = close_case
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    state = after_state_fault(c, monkeypatch, lambda data: data.pop("windows"))
    error = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert "native_read_error" not in error["details"]
    assert state["reads"] >= 1
    assert c.world.ops().count("model.close") == 1


def test_public_close_wrong_after_retains_failed_complete_observation_without_second_read(
    close_case, monkeypatch
):
    c = close_case
    dry = c.cli(*CLOSE, "--dry-run")["data"]

    def wrong(data):
        next(row for row in data["models"] if row["model"] == "sibling.prt")["modified"] = True

    state = after_state_fault(c, monkeypatch, wrong)
    error = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_FAILED"
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] == "failed"
    assert state["reads"] == 1  # Complete failed A is retained; a later clean B cannot replace it.
    observed = error["details"]["receipt"]["snapshot_after"]["extensions"]["creo"]["observation"][
        "after"
    ]
    assert (
        next(row for row in observed["models"] if row["model"] == "sibling.prt")["modified"] is True
    )
    assert c.world.ops().count("model.close") == 1
    assert c.world.models["sibling.prt"]["modified"] is False


def test_public_close_scope_denial_and_final_dependency_drift_never_dispatch(
    close_case, monkeypatch
):
    c = close_case
    scope_file = Path(c.env["CREO_CLI_SCOPE_FILE"])
    scope_bytes = scope_file.read_bytes()
    limited = json.loads(scope_bytes)
    outside = c.root / "outside"
    outside.mkdir()
    limited["roots"] = [str(outside)]
    scope_file.write_text(json.dumps(limited), encoding="utf-8")
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    denied = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=4)["error"]
    assert denied["code"] == "E_FORBIDDEN"
    assert "model.close" not in c.world.ops()
    scope_file.write_bytes(scope_bytes)
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    original = c.world.op
    state = {"source_shows": 0}

    def op(name, request):
        answer = original(name, request)
        if name == "model.show" and request["model"] == "source.prt":
            state["source_shows"] += 1
            if state["source_shows"] == 2:  # final fresh closure, after separate preflight
                answer["modified"] = True
        return answer

    monkeypatch.setattr(c.world, "op", op)
    error = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["code"] == "E_CONFLICT"
    assert state["source_shows"] == 2
    assert "model.close" not in c.world.ops()
    assert "close.drw" in c.world.models
