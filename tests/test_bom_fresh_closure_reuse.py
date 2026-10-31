"""One fresh, bounded graph per write invocation; direct stubs, no CAD or transport."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from creo_cli import driver, engine, registry  # noqa: F401
from creo_cli.core import Error, digest


def plan(command="drawing bom add"):
    return SimpleNamespace(
        op={
            "drawing bom add": "drawing.add-bom",
            "drawing bom balloons": "drawing.add-balloons",
        }.get(command, "drawing.edit-note"),
        target="rig.drw",
        request={"model": "rig.drw"},
        preview={"command": command},
        effects=None,
        arguments={},
        binding={"preflight_revision": "old-do-not-reuse"},
    )


def graph(directory, revision="fresh"):
    def node(name, kind, children, **fields):
        return {
            "identity": name,
            "revision": revision + ":" + name,
            "children": children,
            "description": {
                "model": name,
                "type": kind,
                "origin": str(directory / (name + ".1")),
                **fields,
            },
        }

    return [
        node("p.prt", "part", []),
        node("rig.asm", "assembly", ["p.prt"], components=[{"id": "40", "model": "p.prt"}]),
        node("rig.drw", "drawing", ["rig.asm"], models=["rig.asm"]),
    ]


@pytest.fixture
def context(monkeypatch, tmp_path):
    monkeypatch.setenv("CREO_CLI_WORKSPACE", str(tmp_path))
    nodes = graph(tmp_path)
    session = {
        "models": ["p.prt", "rig.asm", "rig.drw"],
        "working_directory": str(tmp_path),
    }
    monkeypatch.setattr(engine, "session", Mock(return_value=session))
    closure = Mock(return_value=nodes)
    monkeypatch.setattr(driver.model_dependencies, "closure", closure)
    show = Mock(side_effect=AssertionError("no fallback CAD getter"))
    monkeypatch.setattr(engine, "show", show)
    client = SimpleNamespace(url="fixture-only", _guard_pending_read=Mock())
    target = {
        "mode": "session",
        "engine_id": "creo",
        "instance_id": "fixture",
        "object_id": "rig.drw",
        "locator": "fixture-only",
    }
    grant = SimpleNamespace(
        record={"scope_id": "fixture"},
        scope_id="fixture",
        max_operations=None,
        missing=Mock(return_value={}),
    )
    run = {
        "operation_id": "a" * 32,
        "status": "planned",
        "driver_plan": {},
        "driver_binding": {"driver_scope_sha256": digest(grant.record)},
    }
    monkeypatch.setattr(driver, "target", Mock(return_value=target))
    monkeypatch.setattr(driver, "scope", Mock(return_value=grant))
    require_clear = Mock()
    monkeypatch.setattr(driver, "require_clear", require_clear)
    monkeypatch.setattr(driver.safety, "actor", Mock())
    monkeypatch.setattr(driver.safety, "policy", lambda: {"confirm_allowed": True})
    monkeypatch.setattr(driver.safety, "scope", lambda *args: {})
    monkeypatch.setattr(driver.safety, "require_write", Mock())
    monkeypatch.setattr(driver.safety, "token_operation", lambda token: run["operation_id"])
    monkeypatch.setattr(driver.operations, "get", Mock(return_value=run))
    monkeypatch.setattr(driver.operations, "selected_runs", Mock(return_value=[]))
    consume = Mock(side_effect=Error("E_CONFLICT", "controlled stop at consume"))
    monkeypatch.setattr(driver.safety, "consume", consume)
    execute = Mock(side_effect=AssertionError("never dispatch in these controls"))
    monkeypatch.setattr(engine, "execute", execute)
    return SimpleNamespace(
        client=client,
        nodes=nodes,
        session=session,
        closure=closure,
        show=show,
        grant=grant,
        consume=consume,
        execute=execute,
        require_clear=require_clear,
        tmp_path=tmp_path,
    )


def stopped_write(ctx, p):
    with pytest.raises(Error) as caught:
        driver.write(p.preview["command"], {"confirm": "fixture-token"}, ctx.client, p)
    ctx.execute.assert_not_called()
    ctx.show.assert_not_called()
    return caught.value


@pytest.mark.parametrize("command", ("drawing bom add", "drawing bom balloons"))
def test_one_actual_fresh_graph_serves_paths_dependencies_and_conflicts(
    context, monkeypatch, command
):
    snapshots = Mock(wraps=driver.model_dependencies.snapshots)
    monkeypatch.setattr(driver.model_dependencies, "snapshots", snapshots)
    error = stopped_write(context, plan(command))
    assert error.code == "E_CONFLICT"
    assert str(error.message) == "controlled stop at consume"
    context.closure.assert_called_once_with(context.client, {"rig.drw"})
    assert snapshots.call_args.args[0] is context.nodes
    assert (
        context.grant.missing.call_args.kwargs["paths"] == [(str(context.tmp_path), "change")] * 3
    )
    expected = [{"identity": n["identity"], "revision": n["revision"]} for n in context.nodes]
    assert context.consume.call_args.args[1]["driver_dependencies"] == expected
    context.require_clear.assert_called_once()
    assert context.require_clear.call_args.args[1] == [n["identity"] for n in context.nodes]


def test_fresh_graph_after_plan_does_not_reuse_preflight_or_prior_plan(context):
    old = graph(context.tmp_path, "preflight")
    context.closure.side_effect = [old, context.nodes]
    preflight = driver.model_dependencies.closure(context.client, {"rig.drw"})
    p = plan()
    p.preflight_nodes = preflight
    p.verified_observation = {"not": "dependency graph"}
    error = stopped_write(context, p)
    assert error.code == "E_CONFLICT"
    assert context.closure.call_count == 2  # one preflight, one fresh inside write
    assert context.consume.call_args.args[1]["driver_dependencies"] == [
        {"identity": n["identity"], "revision": n["revision"]} for n in context.nodes
    ]


def test_next_write_invocation_requires_new_fresh_graph(context):
    second = graph(context.tmp_path, "next-invocation")
    context.closure.side_effect = [context.nodes, second]
    assert stopped_write(context, plan()).code == "E_CONFLICT"
    assert stopped_write(context, plan()).code == "E_CONFLICT"
    assert context.closure.call_count == 2
    assert (
        context.consume.call_args_list[0].args[1]["driver_dependencies"]
        != (context.consume.call_args_list[1].args[1]["driver_dependencies"])
    )


def test_source_revision_drift_still_reaches_token_refusal_before_dispatch(context):
    def refuse(token, bound, *, expected_binding):
        assert isinstance(expected_binding, dict)
        assert bound["driver_dependencies"][0]["revision"] == "fresh:p.prt"
        raise Error("E_CONFLICT", "source revision drift retained")

    context.consume.side_effect = refuse
    error = stopped_write(context, plan())
    assert error.code == "E_CONFLICT"
    assert error.message == "source revision drift retained"
    context.closure.assert_called_once()


def test_changed_origin_cannot_expand_write_authorization(context):
    context.nodes[0]["description"]["origin"] = str(context.tmp_path.parent / "foreign/p.prt.1")
    error = stopped_write(context, plan())
    assert error.code == "E_FORBIDDEN"
    context.consume.assert_not_called()


@pytest.mark.parametrize(
    "variant",
    (
        "missing-child",
        "duplicate",
        "missing-description",
        "wrong-owner",
        "bad-revision",
        "edges",
        "extra",
        "empty",
        "cycle",
        "wrong-type",
    ),
)
def test_incomplete_supplied_nodes_refuse_without_fallback(context, variant):
    nodes = deepcopy(context.nodes)
    if variant == "missing-child":
        nodes.pop(0)
    elif variant == "duplicate":
        nodes.append(deepcopy(nodes[0]))
    elif variant == "missing-description":
        nodes[0].pop("description")
    elif variant == "wrong-owner":
        nodes[0]["description"]["model"] = "other.prt"
    elif variant == "bad-revision":
        nodes[0]["revision"] = None
    elif variant == "edges":
        nodes[-1]["children"] = []
    elif variant == "extra":
        extra = deepcopy(nodes[0])
        extra["identity"] = extra["description"]["model"] = "extra.prt"
        context.session["models"].append("extra.prt")
        nodes.append(extra)
    elif variant == "empty":
        nodes = []
    elif variant == "cycle":
        nodes[1]["description"]["components"] = [{"model": "rig.asm"}]
        nodes[1]["children"] = ["rig.asm"]
    elif variant == "wrong-type":
        nodes[0]["description"]["type"] = "drawing"
    with pytest.raises(Error) as caught:
        driver.affected_paths(context.client, plan(), nodes=nodes)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    context.closure.assert_not_called()
    context.show.assert_not_called()


@pytest.mark.parametrize("variant", ("missing", "duplicate", "untyped", "incomplete"))
def test_incomplete_session_refuses_supplied_nodes(context, variant):
    if variant == "missing":
        context.session.pop("models")
    elif variant == "duplicate":
        context.session["models"].append("p.prt")
    elif variant == "untyped":
        context.session["models"][0] = "p"
    else:
        context.session["models"].remove("p.prt")
    with pytest.raises(Error) as caught:
        driver.affected_paths(context.client, plan(), nodes=context.nodes)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    context.closure.assert_not_called()


@pytest.mark.parametrize("variant", ("extra-footprint", "wrong-command", "wrong-op"))
def test_bounded_scope_mismatch_refuses_before_closure(context, variant):
    p = plan()
    command = p.preview["command"]
    if variant == "extra-footprint":
        p.preview["model_footprint"] = ["unrelated.prt"]
    elif variant == "wrong-command":
        p.preview["command"] = "drawing bom balloons"
    else:
        p.op = "drawing.edit-note"
    with pytest.raises(Error) as caught:
        driver.write(command, {"confirm": "fixture-token"}, context.client, p)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    context.closure.assert_not_called()
    context.consume.assert_not_called()


def test_other_leaf_keeps_separate_existing_closures(context):
    assert stopped_write(context, plan("drawing note edit")).code == "E_CONFLICT"
    assert context.closure.call_count == 2
