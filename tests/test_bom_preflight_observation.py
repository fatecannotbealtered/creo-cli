"""Bounded BOM preparation over real isolated HTTP; no Creo, native DB or GUI.

Public parser controls use the source entry point so phase instrumentation observes
the actual Client. Transport controls use the same live loopback service directly.
Neither kind substitutes a setter reply for the first independent verification.
"""

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from unittest.mock import patch

import pytest

from creo_cli import driver, native_diagnostic_recovery, registry, transport  # noqa: F401
from creo_cli.commands import detailing
from creo_cli.core import Error
from creo_cli.main import main
from tests.test_commands import Base


@pytest.fixture
def bom_case():
    case = Base()
    case.setUp()
    case.part("p.prt")
    assembly = case.part("rig.asm")
    case.world.make_assembly(assembly)
    for _ in range(2):
        case.world.assembly_add(
            {"model": "rig.asm", "component": "p.prt", "constraints": [{"type": "default"}]}
        )
    case.world.write_version(case.ws, "rig.asm", assembly)
    case.world.drawing_create({"name": "rig.drw", "of": "rig.asm", "sheet": "a3", "views": "none"})
    case.world.drawing_add_view(
        {
            "model": "rig.drw",
            "view": {
                "name": "FRONT",
                "type": "general",
                "at": [130, 200],
                "scale": 1,
                "display": "lines",
            },
        }
    )
    case.world.events.clear()
    try:
        yield case
    finally:
        case.doCleanups()


def command(case, kind):
    if kind == "add":
        return ("drawing", "bom", "add", "--model", "rig.drw", "--x", 10, "--y", 35)
    table = case.world.drawing_add_bom({"model": "rig.drw", "at": [10, 35]})["table"]
    case.world.events.clear()
    return (
        "drawing",
        "bom",
        "balloons",
        "--model",
        "rig.drw",
        "--table",
        table["id"],
        "--view",
        "FRONT",
    )


def shows(case, model="rig.drw"):
    return [
        request
        for op, request in case.world.events
        if op == "model.show" and request["model"] == model
    ]


def phase_readings(monkeypatch, kind):
    readings = []
    original_guard = driver.guard_model
    original_plan = getattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons")
    original_write = driver.write

    def guard(command, client, opts):
        readings.append(("guard", client, client._observation))
        return original_guard(command, client, opts)

    def plan(client, opts, pre):
        readings.append(("plan", client, client._observation))
        return original_plan(client, opts, pre)

    def write(command, opts, client, plan):
        readings.append(("write", client, client._observation))
        return original_write(command, opts, client, plan)

    monkeypatch.setattr(driver, "guard_model", guard)
    monkeypatch.setattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons", plan)
    monkeypatch.setattr(driver, "write", write)
    return readings


@pytest.mark.parametrize("kind", ["add", "balloons"])
def test_public_preflight_and_plan_share_only_the_same_client_boundary(bom_case, monkeypatch, kind):
    case = bom_case
    args = command(case, kind)
    readings = phase_readings(monkeypatch, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    assert [phase for phase, _, _ in readings] == ["guard", "plan", "write"]
    assert readings[0][1] is readings[1][1] is readings[2][1]
    assert readings[0][2] is not None
    assert readings[0][2] is readings[1][2]
    assert readings[2][2] is None
    # Shared preflight/Plan, then a separate final fresh closure, even in preview.
    assert len(shows(case)) == 2
    assert len(shows(case, "rig.asm")) == 2
    assert len(shows(case, "p.prt")) == 2
    assert dry["preview"]["can_apply"] is True
    assert not any(op.startswith("drawing.add-") for op in case.world.ops())


@pytest.mark.parametrize(
    "kind, setter", [("add", "drawing.add-bom"), ("balloons", "drawing.add-balloons")]
)
def test_public_first_independent_read_is_fresh_and_repeat_confirmation_never_replays(
    bom_case, monkeypatch, kind, setter
):
    case = bom_case
    args = command(case, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    readings = phase_readings(monkeypatch, kind)
    original = case.world.handle
    post_setter_boundaries = []
    state = {"written": False}

    def handle(op, request):
        if state["written"] and op == "model.show":
            post_setter_boundaries.append(readings[-1][1]._observation)
        result = original(op, request)
        if op == setter:
            state["written"] = True
        return result

    case.world.handle = handle
    case.world.events.clear()
    result = case.cli(*args, "--confirm", dry["confirm_token"])["data"]
    assert result["receipt"]["outcome"]["change"] == "applied"
    assert result["receipt"]["outcome"]["verification"]["status"] == "passed"
    assert case.world.ops().count(setter) == 1
    after = case.world.events[case.world.ops().index(setter) + 1 :]
    assert [(op, q.get("model")) for op, q in after] == [
        ("model.show", "rig.drw"),
        ("model.show", "rig.asm"),
    ]
    assert post_setter_boundaries == [None, None]
    before_repeat = deepcopy(case.world.events)
    case.cli(*args, "--confirm", dry["confirm_token"], status=6)
    assert case.world.events == before_repeat


@pytest.mark.parametrize("kind", ["add", "balloons"])
def test_next_public_command_has_a_new_client_and_a_new_preparation(bom_case, monkeypatch, kind):
    case = bom_case
    args = command(case, kind)
    readings = phase_readings(monkeypatch, kind)
    first = case.cli(*args, "--dry-run")["data"]
    case.world.models["rig.drw"]["notes"].append({"id": 123, "text": "LATER", "at": [300, 20]})
    case.world.events.clear()
    second = case.cli(*args, "--dry-run")["data"]
    assert readings[0][1] is not readings[3][1]
    assert readings[0][2] is not readings[3][2]
    assert len(shows(case)) == 2
    before = first["preview"]["base_snapshot"]["extensions"]["creo"]["observation"]
    after = second["preview"]["base_snapshot"]["extensions"]["creo"]["observation"]
    assert before["drawing"]["notes"] == []
    assert after["drawing"]["notes"][0]["text"] == "LATER"


@pytest.mark.parametrize(
    "kind, setter", [("add", "drawing.add-bom"), ("balloons", "drawing.add-balloons")]
)
def test_final_closure_detects_drift_after_shared_plan_before_setter(
    bom_case, monkeypatch, kind, setter
):
    case = bom_case
    args = command(case, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    original = driver.write

    def changed(command, opts, client, plan):
        assert client._observation is None
        case.world.models["rig.drw"]["notes"].append({"id": 321, "text": "DRIFT", "at": [300, 20]})
        return original(command, opts, client, plan)

    monkeypatch.setattr(driver, "write", changed)
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["code"] == "E_CONFLICT"
    assert setter not in case.world.ops()
    assert len(shows(case)) == 2


@pytest.mark.parametrize("kind", ["add", "balloons"])
@pytest.mark.parametrize("fault", ["error", "incomplete", "pending", "diagnostic"])
def test_failed_preflight_cannot_feed_a_plan_or_continue_dispatch(
    bom_case, monkeypatch, kind, fault
):
    case = bom_case
    args = command(case, kind)
    original = case.world.handle
    plans = []
    planned = getattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons")

    def plan(*args):
        plans.append(True)
        return planned(*args)

    def handle(op, request):
        answer, keep = original(op, request)
        if op == "model.show" and request["model"] == "rig.drw":
            if fault == "incomplete":
                answer["data"].pop("models")
            else:
                answer = {
                    "ok": False,
                    "diagnostic_request_id": "controlled-preflight-id",
                    "error": {
                        "code": {
                            "error": "E_UNSUPPORTED",
                            "pending": "E_BUSY",
                            "diagnostic": "E_NATIVE_DIAGNOSTIC",
                        }[fault],
                        "message": "controlled preflight failure",
                        **({"started": True} if fault == "pending" else {}),
                        **(
                            {"native_diagnostic": {"reason": "controlled_serious_message"}}
                            if fault == "diagnostic"
                            else {}
                        ),
                    },
                }
        return answer, keep

    monkeypatch.setattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons", plan)
    case.world.handle = handle
    error = case.cli(*args, "--dry-run", status=8 if fault == "pending" else 1)["error"]
    assert error["code"] == {
        "pending": "E_NATIVE_READ_PENDING",
        "diagnostic": "E_NATIVE_DIAGNOSTIC",
    }.get(fault, "E_VERIFY_INCOMPLETE")
    if fault == "diagnostic":
        details = error["details"]
        assert details["operation"] == "model.show"
        assert details["diagnostic_request_id"] == "controlled-preflight-id"
        assert details["cli_invocation_id"]
        assert details["native_diagnostic"]["reason"] == "controlled_serious_message"
        assert details["next_action"] == native_diagnostic_recovery.STOP_ACTION
    assert plans == []
    assert case.world.ops() == ["session.status", "model.show"]


@pytest.mark.parametrize(
    "kind, setter", [("add", "drawing.add-bom"), ("balloons", "drawing.add-balloons")]
)
@pytest.mark.parametrize("fault", ["pending", "wrong_quantity"])
def test_post_setter_failure_cannot_be_satisfied_by_cached_preflight(bom_case, kind, setter, fault):
    case = bom_case
    args = command(case, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    original = case.world.handle
    state = {"written": False}

    def handle(op, request):
        answer, keep = original(op, request)
        if state["written"] and op == "model.show" and request["model"] == "rig.drw":
            if fault == "pending":
                answer = {
                    "ok": False,
                    "error": {
                        "code": "E_UNAVAILABLE",
                        "started": True,
                        "message": "controlled first independent read pending",
                    },
                }
            else:
                answer["data"]["tables"][0]["cells"][1][2] = "999"
        if op == setter:
            state["written"] = True
        return answer, keep

    case.world.handle = handle
    case.world.events.clear()
    error = case.cli(
        *args, "--confirm", dry["confirm_token"], status=6 if fault == "pending" else 1
    )["error"]
    receipt = error["details"]["receipt"]
    # A completed write can be applied while an independent postcondition fails;
    # its verification facet must not be falsely promoted by cached preflight.
    assert receipt["outcome"]["verification"]["status"] != "passed"
    assert receipt["outcome"]["execution"] == "completed"
    assert case.world.ops().count(setter) == 1
    if fault == "pending":
        assert case.world.ops()[case.world.ops().index(setter) + 1 :] == ["model.show"]
        assert error["details"]["native_read_error"]["code"] == "E_NATIVE_READ_PENDING"


def test_transport_boundary_keys_exact_request_and_client_and_keeps_template_fresh(bom_case):
    case = bom_case
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        with client.observation(fresh_operations={"drawing.bom-template"}):
            client.op("model.show", {"model": "rig.drw"})
            client.op("model.show", {"model": "rig.drw"})
            client.op("model.show", {"model": "rig.asm"})
            client.op("drawing.bom-template", {"table": "Assembly/bom_description_down"})
            client.op("drawing.bom-template", {"table": "Assembly/bom_description_down"})
            with transport.Client() as other:
                other.op("model.show", {"model": "rig.drw"})
        client.op("model.show", {"model": "rig.drw"})
    assert len(shows(case)) == 3
    assert len(shows(case, "rig.asm")) == 1
    assert case.world.ops().count("drawing.bom-template") == 2


@pytest.mark.parametrize(
    "operation, write", [("model.save", True), ("model.save", False), ("drawing.add-bom", True)]
)
def test_shared_preparation_cannot_dispatch_mutation(bom_case, operation, write):
    case = bom_case
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        with client.observation(fresh_operations={"drawing.bom-template"}):
            with pytest.raises(Error) as caught:
                client.op(operation, {"model": "rig.drw"}, write=write)
    assert caught.value.code == "E_FORBIDDEN"
    assert caught.value.details["request_sent"] is False
    assert case.world.events == []


def test_only_declared_template_getter_can_be_added_as_fresh(bom_case):
    case = bom_case
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        with pytest.raises(Error) as caught:
            with client.observation(fresh_operations={"drawing.add-bom"}):
                raise AssertionError("invalid scope must fail before entry")
    assert caught.value.code == "E_FORBIDDEN"
    assert case.world.events == []


@pytest.mark.parametrize("inventory", ["tables", "notes", "views"])
def test_missing_bom_native_inventory_cannot_become_a_complete_plan(bom_case, inventory):
    case = bom_case
    args = command(case, "add")
    original = case.world.handle

    def incomplete(op, request):
        answer, keep = original(op, request)
        if op == "model.show" and request["model"] == "rig.drw":
            answer["data"][inventory] = None
        return answer, keep

    case.world.handle = incomplete
    out, err = io.StringIO(), io.StringIO()
    with patch.dict(os.environ, case.env, clear=True), redirect_stdout(out), redirect_stderr(err):
        code = main([*map(str, args), "--dry-run"])
    result = json.loads(out.getvalue())
    assert code == 1, json.dumps(
        {
            "inventory": inventory,
            "exit": code,
            "ok": result["ok"],
            "can_apply": result.get("data", {}).get("preview", {}).get("can_apply"),
        }
    )
    assert result["error"]["code"] == "E_VERIFY_INCOMPLETE"
    assert not any(op.startswith("drawing.add-") for op in case.world.ops())


@pytest.mark.parametrize("inventory", ["tables", "notes", "views"])
@pytest.mark.parametrize("fault", ["duplicate_id", "missing_id", "bool_id", "non_object"])
def test_ambiguous_native_inventory_is_refused_before_write(bom_case, inventory, fault):
    case = bom_case
    args = command(case, "add")
    original = case.world.handle

    def ambiguous(op, request):
        answer, keep = original(op, request)
        if op == "model.show" and request["model"] == "rig.drw":
            row = {"id": 77}
            answer["data"][inventory] = {
                "duplicate_id": [row, {"id": "77"}],
                "missing_id": [{}],
                "bool_id": [{"id": True}],
                "non_object": ["not-an-object"],
            }[fault]
        return answer, keep

    case.world.handle = ambiguous
    error = case.cli(*args, "--dry-run", status=1)["error"]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert not any(op.startswith("drawing.add-") for op in case.world.ops())


@pytest.mark.parametrize(
    "kind, setter", [("add", "drawing.add-bom"), ("balloons", "drawing.add-balloons")]
)
@pytest.mark.parametrize("inventory", ["tables", "notes", "views"])
def test_missing_first_independent_inventory_never_becomes_verified_evidence(
    bom_case, monkeypatch, kind, setter, inventory
):
    case = bom_case
    args = command(case, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    original = case.world.handle
    original_plan = getattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons")
    plans = []
    state = {"written": False}

    def plan(*args):
        result = original_plan(*args)
        plans.append(result)
        return result

    def incomplete(op, request):
        answer, keep = original(op, request)
        if state["written"] and op == "model.show" and request["model"] == "rig.drw":
            answer["data"][inventory] = None
        if op == setter:
            state["written"] = True
        return answer, keep

    monkeypatch.setattr(detailing, "_plan_bom" if kind == "add" else "_plan_balloons", plan)
    case.world.handle = incomplete
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    receipt = error["details"]["receipt"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["change"] == "unknown"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    assert plans[0].verified_observation is None
    assert case.world.ops().count(setter) == 1


@pytest.mark.parametrize("fault", ["pending", "diagnostic"])
def test_stop_from_another_getter_precedes_a_cached_target_or_write(bom_case, fault):
    case = bom_case
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        with client.observation(fresh_operations={"drawing.bom-template"}):
            client.op("model.show", {"model": "rig.drw"})
            case.world.fail = (
                "model.show",
                {
                    "code": "E_BUSY" if fault == "pending" else "E_NATIVE_DIAGNOSTIC",
                    "message": "controlled stop after earlier successful cached target",
                    **({"started": True} if fault == "pending" else {}),
                },
            )
            with pytest.raises(Error) as first:
                client.op("model.show", {"model": "rig.asm"})
            before = deepcopy(case.world.events)
            for operation, write in [("model.show", False), ("model.save", True)]:
                with pytest.raises(Error) as blocked:
                    client.op(operation, {"model": "rig.drw"}, write=write)
                assert blocked.value.code == first.value.code
                assert blocked.value.details["request_sent"] is False
            assert case.world.events == before
    assert len(case.world.events) == 2


def test_definite_read_error_is_not_cached_as_success(bom_case):
    case = bom_case
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        with client.observation(fresh_operations={"drawing.bom-template"}):
            case.world.fail = ("model.show", {"code": "E_NOT_FOUND", "message": "definite refusal"})
            with pytest.raises(Error) as caught:
                client.op("model.show", {"model": "rig.drw"})
            assert caught.value.code == "E_NOT_FOUND"
            case.world.fail = None
            actual = client.op("model.show", {"model": "rig.drw"})
            assert actual["model"] == "rig.drw"
    assert len(shows(case)) == 2


@pytest.mark.parametrize(
    "kind, setter", [("add", "drawing.add-bom"), ("balloons", "drawing.add-balloons")]
)
def test_public_query_is_fresh_and_resolution_does_not_enter_preparation_cache(
    bom_case, monkeypatch, kind, setter
):
    case = bom_case
    args = command(case, kind)
    dry = case.cli(*args, "--dry-run")["data"]
    # The controlled synchronous peer completes its setter before intentionally
    # closing the HTTP response. This is write-result loss, not a pending read.
    case.world.drop = setter
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    case.world.drop = None
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    ident = dry["preview"]["operation_id"]
    receipt = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]

    def refuse_boundary(*args, **kwargs):
        raise AssertionError("query/resolve must not borrow a BOM preparation boundary")

    monkeypatch.setattr(transport.Client, "observation", refuse_boundary)
    case.world.events.clear()
    first = case.cli("operation", "query", "--id", ident, "--model", "rig.drw")["data"]
    case.world.models["rig.drw"]["notes"].append({"id": 444, "text": "FRESH", "at": [300, 20]})
    second = case.cli("operation", "query", "--id", ident, "--model", "rig.drw")["data"]
    assert len(shows(case)) == 2
    assert first["observation"]["model"]["notes"] != second["observation"]["model"]["notes"]
    before_resolve = deepcopy(case.world.events)
    resolve = (
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "partial",
        "--evidence",
        "Controlled peer completed; fresh drawing inspected; bounded manual partial registration",
    )
    preview = case.cli(*resolve, "--dry-run")["data"]
    resolved = case.cli(*resolve, "--confirm", preview["confirm_token"])["data"]["operation_status"]
    assert case.world.events == before_resolve
    assert resolved["receipt"] == receipt
    assert resolved["resolution"]["outcome"] == "partial"
    assert case.world.ops().count(setter) == 0


@pytest.mark.parametrize("kind", ["add", "balloons"])
@pytest.mark.parametrize("getter", ["parameter.list", "relation.list"])
@pytest.mark.parametrize("fault", ["pending", "diagnostic"])
def test_revision_getter_stop_keeps_correlation_and_no_further_cad(bom_case, kind, getter, fault):
    case = bom_case
    args = command(case, kind)
    original = case.world.handle
    stopped_at = []

    def stop(op, request):
        answer, keep = original(op, request)
        if op == getter:
            stopped_at.append(len(case.world.events))
            answer = {
                "ok": False,
                "diagnostic_request_id": "controlled-revision-id",
                "error": {
                    "code": "E_BUSY" if fault == "pending" else "E_NATIVE_DIAGNOSTIC",
                    "message": "controlled revision getter stop",
                    **({"started": True} if fault == "pending" else {}),
                },
            }
        return answer, keep

    case.world.handle = stop
    error = case.cli(*args, "--dry-run", status=8 if fault == "pending" else 1)["error"]
    assert error["code"] == (
        "E_NATIVE_READ_PENDING" if fault == "pending" else "E_NATIVE_DIAGNOSTIC"
    )
    assert error["details"]["operation"] == getter
    assert error["details"]["diagnostic_request_id"] == "controlled-revision-id"
    assert error["details"]["cli_invocation_id"]
    assert len(stopped_at) == 1
    assert len(case.world.events) == stopped_at[0]
