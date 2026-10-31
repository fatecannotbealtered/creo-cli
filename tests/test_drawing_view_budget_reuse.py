"""One view Plan may reuse its independently verified name inventory, never its reply.

Direct controls and public CLI over an isolated real HTTP peer; no Creo is used.
"""

import json
import os
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from creo_cli import driver, engine, registry, view_readback  # noqa: F401
from creo_cli.commands import drawing
from creo_cli.core import Error
from tests import test_bom_fresh_closure_reuse as closure_controls
from tests.test_native_read_context import PublicCase, arm

VIEW = (
    "drawing",
    "view",
    "add",
    "--model",
    "instructions.drw",
    "--type",
    "general",
    "--name",
    "REFERENCE",
    "--x",
    200,
    "--y",
    140,
    "--scale",
    1,
)


@pytest.fixture
def view_case(request):
    c = PublicCase()
    c.setUp()
    c.part("source.prt")
    c.world.drawing_create(
        {"name": "instructions.drw", "of": "source.prt", "sheet": "a3", "views": "none"}
    )
    try:
        yield c
    finally:
        root = os.environ.get("R37_VIEW_BUDGET_EVIDENCE")
        if root:
            folder = Path(root)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (request.node.name.replace(":", "_") + ".json")).write_text(
                json.dumps(
                    {
                        "kind": "controlled_http_public_cli",
                        "real_native_calls": 0,
                        # Confirmation tokens are useful only inside this test.
                        # Persist neither raw public results/argv nor request values.
                        "public_command_count": len(c.public_calls),
                        "operation_shapes": [
                            {"operation": op, "request_keys": sorted(request)}
                            for op, request in c.world.events
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        c.doCleanups()


def test_public_view_reuses_only_first_verified_inventory(view_case):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    c.world.events.clear()
    result = c.cli(*VIEW, "--confirm", dry["confirm_token"])["data"]
    ops = c.world.ops()
    added = ops.index("drawing.add-view")
    assert ops[added + 1 :] == ["model.show"]
    assert all(check["passed"] is True for check in result["verification"]["checks"])
    assert result["status"] == "completed"
    # Separate preflight, Plan-before, final fresh closure, then first independent verify.
    assert (
        sum(op == "model.show" and q["model"] == "instructions.drw" for op, q in c.world.events)
        == 4
    )
    events = deepcopy(c.world.events)
    c.cli(*VIEW, "--confirm", dry["confirm_token"], status=6)
    assert c.world.events == events
    assert c.world.ops().count("drawing.add-view") == 1


def test_public_view_no_late_effect_read_can_become_pending(view_case):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    state = arm(c, "busy_started", read="model.show", after="drawing.add-view", occurrence=2)
    result = c.cli(*VIEW, "--confirm", dry["confirm_token"])["data"]
    assert result["status"] == "completed"
    assert state["reads"] == 1
    assert not state["fired"]


@pytest.fixture
def view_plan(monkeypatch, tmp_path):
    before = {
        "model": "rig.drw",
        "type": "drawing",
        "models": ["source.prt"],
        "views": [],
        "sheets": [{"number": 1, "width": 420, "height": 297, "units": "mm", "scale": 1}],
        "notes": [],
        "tables": [],
        "dimensions": [],
    }
    after = deepcopy(before)
    row = {
        "id": 10,
        "name": "REFERENCE",
        "model": "source.prt",
        "sheet": 1,
        "type": "general",
        "at": [200, 140],
        "orientation": "front",
        "display": "lines",
        "scale": 1,
        "outline": [[180, 120], [220, 160]],
        "exploded_display_readback": {
            "complete": True,
            "value": False,
            "source": "WView2D.IsExplodedState",
        },
    }
    row["view_identity_readback"] = {"complete": True} | {
        key: {"complete": True, "value": row[key], "source": source}
        for key, source in view_readback.SOURCES.items()
    }
    after["views"] = [row]
    c = SimpleNamespace(_health={"capabilities": {"drawing_view_exploded_readback": 1}})
    state = SimpleNamespace(before=before, after=after, reads=[], error=None, phase="before")

    def show(client, name):
        state.reads.append((client, name))
        if name == "source.prt":
            return {"model": name, "type": "part", "cross_sections": []}
        if state.error is not None:
            raise state.error
        return deepcopy(state.before if state.phase == "before" else state.after)

    monkeypatch.setattr(engine, "session", lambda c: {"models": ["rig.drw", "source.prt"]})
    monkeypatch.setattr(engine, "store_directory", lambda *args: tmp_path)
    monkeypatch.setattr(engine, "show", show)
    opts = {
        "model": "rig.drw",
        "type": "general",
        "name": "REFERENCE",
        "x": 200,
        "y": 140,
        "scale": 1,
    }
    p = drawing._plan_view(c, opts, {"name": "rig.drw"})
    state.phase = "after"
    state.reads.clear()
    return SimpleNamespace(client=c, plan=p, state=state, opts=opts)


def test_view_cache_is_actual_name_list_deepcopy_and_first_read_is_fresh(view_plan):
    x = view_plan
    reply = {"view": {"name": "SETTER_ONLY"}, "views": [{"name": "SETTER_ONLY"}]}
    _, verification = x.plan.verify(x.client, reply)
    assert all(check["passed"] is True for check in verification["checks"])
    assert x.state.reads == [(x.client, "rig.drw")]
    assert x.plan.verified_observation == ["REFERENCE"]
    assert driver._effect_observation(x.plan, x.client) == ["REFERENCE"]
    x.state.after["views"][0]["name"] = "LATER"
    assert x.plan.verified_observation == ["REFERENCE"]
    # Explicit observe/query paths always perform fresh reads; the cache changes none of them.
    assert x.plan.observe(x.client) == ["LATER"]
    assert len(x.state.reads) == 2


@pytest.mark.parametrize(
    "problem",
    (
        "drawing",
        "type",
        "source",
        "duplicate-source",
        "duplicate-id",
        "duplicate-name",
        "name",
        "page",
        "boolean",
        "identity",
        "view-source",
        "display",
        "scale",
        "resources",
    ),
)
def test_unqualified_or_failed_observation_never_becomes_effect_cache(view_plan, problem):
    x = view_plan
    row = x.state.after["views"][0]
    if problem == "drawing":
        x.state.after["model"] = "other.drw"
    elif problem == "type":
        x.state.after["type"] = "part"
    elif problem == "source":
        x.state.after["models"] = ["foreign.prt"]
    elif problem == "duplicate-source":
        x.state.after["models"] *= 2
    elif problem in ("duplicate-id", "duplicate-name"):
        extra = deepcopy(row)
        extra["id"] = row["id"] if problem == "duplicate-id" else 11
        x.state.after["views"].append(extra)
    elif problem == "identity":
        row["view_identity_readback"]["id"]["complete"] = False
    elif problem == "view-source":
        row["model"] = "foreign.prt"
        row["view_identity_readback"]["model"]["value"] = "foreign.prt"
    elif problem in ("name", "page"):
        key = "name" if problem == "name" else "sheet"
        row[key] = "OTHER" if problem == "name" else 2
        row["view_identity_readback"][key]["value"] = row[key]
    elif problem == "boolean":
        row["exploded_display_readback"]["value"] = True
    elif problem in ("display", "scale"):
        row[problem] = "hidden" if problem == "display" else 2
    elif problem == "resources":
        x.state.after["notes"] = [{"id": "extra"}]
    x.plan.verify(x.client, {})
    assert x.plan.verified_observation is None
    assert driver._effect_observation(x.plan, x.client) is None


@pytest.mark.parametrize("problem", ("pending", "diagnostic", "ordinary-error"))
def test_verify_entry_clears_prior_cache_before_any_failed_read(view_plan, problem):
    x = view_plan
    x.plan.verify(x.client, {})
    x.state.error = Error(
        {
            "pending": "E_NATIVE_READ_PENDING",
            "diagnostic": "E_NATIVE_DIAGNOSTIC",
            "ordinary-error": "E_UNSUPPORTED",
        }[problem],
        "controlled read",
    )
    with pytest.raises(Error):
        x.plan.verify(x.client, {})
    assert x.plan.verified_observation is None
    assert driver._effect_observation(x.plan, x.client) is None


@pytest.mark.parametrize(
    "problem",
    (
        "client",
        "plan",
        "request",
        "binding",
        "target",
        "op",
        "preview",
        "arguments",
        "before",
        "cached-value",
        "pending-guard",
        "diagnostic-guard",
    ),
)
def test_effect_rechecks_exact_plan_identity_and_frozen_inputs(view_plan, problem):
    x = view_plan
    x.plan.verify(x.client, {})
    p, c = x.plan, x.client
    if problem == "client":
        c = SimpleNamespace()
    elif problem == "plan":
        p = copy(p)
    elif problem == "request":
        p.request["view"]["at"][0] += 1
    elif problem == "binding":
        p.binding["drawing"]["notes"].append({"id": "drift"})
    elif problem in ("target", "op"):
        setattr(p, problem, "other.drw" if problem == "target" else "other.op")
    elif problem == "preview":
        p.preview["command"] = "drawing view add"
    elif problem == "arguments":
        p.arguments["x"] += 1
    elif problem == "before":
        p.before.append("DRIFT")
    elif problem == "cached-value":
        p.verified_observation.append("SETTER_ONLY")
    elif problem == "pending-guard":
        c._native_read_pending = Error("E_NATIVE_READ_PENDING", "controlled")
    elif problem == "diagnostic-guard":
        c._native_diagnostic_stop = Error("E_NATIVE_DIAGNOSTIC", "controlled")
    assert driver._effect_observation(p, c) is None


def test_another_client_cannot_populate_view_cache(view_plan):
    x = view_plan
    x.plan.verify(SimpleNamespace(), {})
    assert x.plan.verified_observation is None


def test_public_query_is_fresh_and_does_not_reuse_verified_view(view_case):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    result = c.cli(*VIEW, "--confirm", dry["confirm_token"])["data"]
    c.world.models["instructions.drw"]["views"][0]["name"] = "LATER"
    c.world.events.clear()
    queried = c.cli(
        "operation", "query", "--id", result["operation_id"], "--model", "instructions.drw"
    )["data"]
    assert c.world.ops() == ["model.show"]
    assert queried["observation"]["model"]["views"][0]["name"] == "LATER"


@pytest.mark.parametrize("fault", ("busy_started", "unavailable_started", "reply_lost"))
def test_public_first_read_pending_stops_followup_and_repeat(view_case, fault):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    state = arm(c, fault, read="model.show", after="drawing.add-view")
    c.world.events.clear()
    error = c.cli(*VIEW, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert error["details"]["native_read_error"]["code"] == "E_NATIVE_READ_PENDING"
    assert state["fired"]
    ops = c.world.ops()
    assert ops[ops.index("drawing.add-view") + 1 :] == ["model.show"]
    events = deepcopy(c.world.events)
    c.cli(*VIEW, "--confirm", dry["confirm_token"], status=6)
    assert c.world.events == events
    assert c.world.ops().count("drawing.add-view") == 1


def view_path_plan():
    return SimpleNamespace(
        op="drawing.add-view",
        target="rig.drw",
        request={"model": "rig.drw", "view": {}},
        preview={"command": "drawing add-view"},
        effects=None,
        arguments={},
        binding={},
    )


@pytest.fixture
def closure_context(monkeypatch, tmp_path):
    return closure_controls.context.__wrapped__(monkeypatch, tmp_path)


def test_view_final_closure_is_fresh_and_shared_after_separate_preflight(closure_context):
    x = closure_context
    old = closure_controls.graph(x.tmp_path, "preflight")
    x.closure.side_effect = [old, x.nodes]
    driver.guard_model("drawing view add", x.client, {"model": "rig.drw"})
    with pytest.raises(Error, match="controlled stop at consume"):
        driver.write("drawing view add", {"confirm": "fixture"}, x.client, view_path_plan())
    assert x.closure.call_count == 2
    assert x.consume.call_args.args[1]["driver_dependencies"] == [
        {"identity": node["identity"], "revision": node["revision"]} for node in x.nodes
    ]
    assert x.grant.missing.call_args.kwargs["paths"] == [(str(x.tmp_path), "change")] * 3
    x.execute.assert_not_called()
    x.show.assert_not_called()


@pytest.mark.parametrize("problem", ("canonical-preview", "wrong-op", "extra-root"))
def test_view_shared_closure_requires_exact_canonical_alias_and_roots(closure_context, problem):
    x = closure_context
    p = view_path_plan()
    if problem == "canonical-preview":
        p.preview["command"] = "drawing view add"
    elif problem == "wrong-op":
        p.op = "drawing.edit-note"
    else:
        p.preview["model_footprint"] = ["other.prt"]
    with pytest.raises(Error) as error:
        driver.write("drawing view add", {"confirm": "fixture"}, x.client, p)
    assert error.value.code == "E_VERIFY_INCOMPLETE"
    x.closure.assert_not_called()
    x.consume.assert_not_called()
    x.execute.assert_not_called()


def test_legacy_view_does_not_gain_verified_reuse(view_plan):
    x = view_plan
    x.state.phase = "before"
    x.client._health["capabilities"] = {}
    p = drawing._plan_view(x.client, x.opts, {"name": "rig.drw"})
    x.state.phase = "after"
    _, verification = p.verify(x.client, {})
    assert all(check["passed"] is True for check in verification["checks"])
    assert (
        "legacy_service_per_view_exploded_flag_and_identity_metadata" in verification["not_checked"]
    )
    assert p.verified_observation is None
    assert driver._effect_observation(p, x.client) is None


def test_public_failed_verification_keeps_effect_observe_fresh(view_case, monkeypatch):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    original = c.world.op
    state = {"written": False, "reads": 0}

    def op(name, request):
        answer = original(name, request)
        if name == "drawing.add-view":
            state["written"] = True
        elif state["written"] and name == "model.show":
            state["reads"] += 1
            if state["reads"] == 1:
                answer["views"][0]["name"] = "WRONG"
        return answer

    monkeypatch.setattr(c.world, "op", op)
    error = c.cli(*VIEW, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_FAILED"
    assert state["reads"] == 2
    assert c.world.ops().count("drawing.add-view") == 1


def test_public_diagnostic_first_read_prevents_effect_and_replay(view_case, monkeypatch):
    c = view_case
    dry = c.cli(*VIEW, "--dry-run")["data"]
    original = c.world.handle
    state = {"written": False, "fired": False}

    def handle(op, request):
        answer, keep = original(op, request)
        if op == "drawing.add-view":
            state["written"] = True
        elif state["written"] and op == "model.show":
            state["fired"] = True
            answer = {
                "ok": False,
                "diagnostic_request_id": "controlled-view-read",
                "error": {
                    "code": "E_NATIVE_DIAGNOSTIC",
                    "message": "controlled stop",
                    "native_diagnostic": {
                        "contract_version": 1,
                        "enabled": True,
                        "stopped": True,
                        "reason": "native_serious_message_observed",
                    },
                },
            }
        return answer, keep

    monkeypatch.setattr(c.world, "handle", handle)
    c.world.events.clear()
    error = c.cli(*VIEW, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert state["fired"]
    ops = c.world.ops()
    assert ops[ops.index("drawing.add-view") + 1 :] == ["model.show"]
    events = deepcopy(c.world.events)
    c.cli(*VIEW, "--confirm", dry["confirm_token"], status=6)
    assert c.world.events == events
