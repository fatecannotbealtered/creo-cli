"""Real loopback replies and isolated public receipts; no CAD or production history."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from creo_cli import native_diagnostic_recovery, operations, registry, transport
from creo_cli.core import Error
from tests.test_native_read_context import (
    PARAMETER_ARGS,
    PublicCase,
    unknown_saved_operation,
    workflow_request,
)
from tests.test_native_read_transport_uncertainty import capture_error, controlled_peer

DIAGNOSTIC_ID = "8722964a-65ae-4f82-b14b-68bbe3b39a86"


def diagnostic(operation, *, reason="native_serious_message_observed", completion=False):
    event = {
        "event": "effect",
        "effect": "native_write_returned",
        "effect_contract_version": 1,
        "operation": operation,
        "diagnostic_request_id": DIAGNOSTIC_ID,
        "facts": {"operation": operation, "target": "block.prt", "saved": False},
    }
    return {
        "ok": False,
        "diagnostic_request_id": DIAGNOSTIC_ID,
        "error": {
            "code": "E_NATIVE_DIAGNOSTIC",
            "message": "controlled native diagnostic stop",
            "native_diagnostic": {
                "contract_version": 1,
                "enabled": True,
                "stopped": True,
                "reason": reason,
                "last_call": {
                    "getter": "Get3DLineEnvelope",
                    "event": "end",
                    "result": "returned_object",
                },
                "effects": [event] if completion else [],
                "journal": "isolated-controlled-journal",
            },
        },
    }


@pytest.fixture
def case():
    value = PublicCase()
    value.setUp()
    value.part()
    try:
        yield value
    finally:
        value.doCleanups()


def arm_diagnostic(case, stage, *, reason="native_serious_message_observed", completion=False):
    original = case.world.handle
    state = {"wrote": False, "reads": 0, "fired": False, "event_index": None}

    def handle(op, request):
        reply, keep = original(op, request)
        if op == "parameter.set":
            state["wrote"] = True
            trigger = stage == "write_summary"
        elif state["wrote"] and op == "parameter.list":
            state["reads"] += 1
            trigger = state["reads"] == (2 if stage == "final_observe" else 1)
        else:
            trigger = False
        if trigger and not state["fired"]:
            state.update(fired=True, event_index=len(case.world.events))
            return diagnostic(op, reason=reason, completion=completion), keep
        return reply, keep

    case.world.handle = handle
    return state


@pytest.mark.parametrize("stage", ("write_summary", "verify", "final_observe"))
@pytest.mark.parametrize(
    "reason", ("native_serious_message_observed", "diagnostic_persistence_failed")
)
def test_public_write_stops_without_hidden_settlement_or_replay(case, stage, reason):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    state = arm_diagnostic(case, stage, reason=reason, completion=stage == "write_summary")
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=1)["error"]
    assert state["fired"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert error["retryable"] is False
    assert case.world.ops().count("parameter.set") == 1
    assert len(case.world.events) == state["event_index"]  # no further getter at any layer
    details = error["details"]
    context = details["native_diagnostic_error"]
    assert context["details"]["diagnostic_request_id"] == DIAGNOSTIC_ID
    assert context["details"]["native_diagnostic"]["reason"] == reason
    assert "started" not in context["details"]
    assert "native_read_error" not in details
    receipt = details["receipt"]
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["change"] == "unknown"
    assert receipt["outcome"]["persistence"] == "unknown"
    assert receipt["outcome"]["verification"]["status"] == "incomplete"
    ident = dry["preview"]["operation_id"]
    assert details["operation_id"] == ident
    with patch.dict(os.environ, case.env, clear=True):
        stored = operations.get(ident)
    assert bool(stored.get("service_reported_done")) is (stage != "write_summary")
    before = deepcopy(case.world.events)
    shown = case.cli("operation", "show", "--id", ident)["data"]
    assert case.world.events == before
    assert shown["operation_status"]["receipt"] == receipt
    assert shown["operation_status"]["extensions"]["creo"]["native_diagnostic_error"] == context
    assert shown["recovery_guidance"]["query"] is None
    text = json.dumps({key: details.get(key) for key in ("next_action", "fix")})
    assert "process-only" in text and "operation show" in text
    assert "model show" not in text and "feature list" not in text
    case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)
    assert case.world.events == before


@pytest.mark.parametrize("id_present", (True, False))
def test_real_http_source_read_and_client_guard_not_pending(case, id_present):
    original = case.world.handle
    response = diagnostic("model.show")
    if not id_present:
        response.pop("diagnostic_request_id")

    def handle(op, request):
        value, keep = original(op, request)
        return (response if op == "model.show" else value), keep

    case.world.handle = handle
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        client.health()
        first = capture_error(lambda: client.op("model.show", {"model": "block.prt"}))
        assert first.code == "E_NATIVE_DIAGNOSTIC" and first.exit == 1
        assert client._native_read_pending is None
        Draft202012Validator(registry.NATIVE_DIAGNOSTIC_RECOVERY["error_schema"]).validate(
            first.payload()
        )
        assert ("diagnostic_request_id" in first.details) is id_present
        assert "operation_id" not in first.details and "receipt" not in first.details
        events = deepcopy(case.world.events)
        assert client.health()["ok"]
        for op, write in (("feature.list", False), ("model.save", True)):
            refused = capture_error(lambda op=op, write=write: client.op(op, write=write))
            assert refused.code == first.code
            assert refused.details["request_sent"] is False
            assert refused.details["diagnostic_original_request_sent"] is True
            assert refused.details["native_diagnostic"] == first.details["native_diagnostic"]
        assert events == case.world.events


@pytest.mark.parametrize("fault", ("reply_lost", "invalid_json", "busy_started"))
def test_old_read_uncertainty_is_not_reclassified(fault):
    with controlled_peer(fault), transport.Client() as client:
        error = capture_error(lambda: client.op("model.show"))
        assert error.code == "E_NATIVE_READ_PENDING"
        assert client._native_diagnostic_stop is None


def test_write_reply_loss_keeps_original_unknown(case):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    case.world.drop = "parameter.set"
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert "native_diagnostic_error" not in error["details"]


def test_ordinary_unsupported_does_not_set_diagnostic_stop(case):
    case.world.fail = (
        "model.show",
        {"code": "E_UNSUPPORTED", "message": "ordinary optional getter"},
    )
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        error = capture_error(lambda: client.op("model.show"))
        assert error.code == "E_UNSUPPORTED"
        assert client._native_diagnostic_stop is None
        case.world.fail = None
        assert client.op("model.show", {"model": "block.prt"})


@pytest.mark.parametrize(
    "drift", ("contract", "target", "operation", "request_id", "effect", "malformed_list_member")
)
def test_completion_facts_need_actual_target_version_and_request_correlation(drift):
    raw = diagnostic("drawing.add-note", completion=True)
    evidence = raw["error"]["native_diagnostic"]
    event = evidence["effects"][0]
    event["facts"]["target"] = "a.drw"
    if drift == "contract":
        evidence["contract_version"] = 0
    if drift == "target":
        event["facts"]["target"] = "other.drw"
    if drift == "operation":
        event["facts"]["operation"] = "other"
    if drift == "request_id":
        event["diagnostic_request_id"] = "other"
    if drift == "effect":
        event["effect"] = "note_created"
    if drift == "malformed_list_member":
        evidence["effects"].append(None)
    stopped = {
        "code": "E_NATIVE_DIAGNOSTIC",
        "details": {
            "diagnostic_request_id": DIAGNOSTIC_ID,
            "native_diagnostic": evidence,
        },
    }
    run = {}
    assert not native_diagnostic_recovery.capture_effects(run, stopped, "drawing.add-note", "a.drw")
    assert "native_write_returned" not in run


def test_inspection_sidecar_failure_keeps_original_stop_and_receipt(case):
    run = {"operation_id": "a" * 32}
    original = diagnostic("model.show")
    error = Error(
        "E_NATIVE_DIAGNOSTIC",
        "stopped",
        {
            "operation": "model.show",
            "diagnostic_request_id": DIAGNOSTIC_ID,
            "native_diagnostic": original["error"]["native_diagnostic"],
        },
    )
    before = deepcopy(run)
    with patch.object(operations, "save_query", side_effect=PermissionError("isolated")):
        operations.retain_pending_inspection(run, error, "operation query")
    assert error.code == "E_NATIVE_DIAGNOSTIC"
    assert (
        error.details["native_diagnostic_error"]["details"]["diagnostic_request_id"]
        == DIAGNOSTIC_ID
    )
    assert error.details["read_failure_evidence_retained"] is False
    assert "read_failure_evidence_id" not in error.details
    assert before == run


def test_full_reference_declares_diagnostic_separate_from_read_pending(case):
    data = case.cli("reference")["data"]
    declaration = data["extensions"]["creo"]["native_diagnostic_recovery"]
    assert declaration == registry.NATIVE_DIAGNOSTIC_RECOVERY
    assert data["error_codes"]["E_NATIVE_DIAGNOSTIC"]["exit"] == 1
    assert not declaration["persistent_global_lock"]
    assert case.world.ops() == []


def test_workflow_leaf_stop_does_not_bypass_guard_through_outer_client(case):
    args = ("workflow", "run", "--request", workflow_request(case))
    dry = case.cli(*args, "--dry-run")["data"]
    state = arm_diagnostic(case, "verify")
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert len(case.world.events) == state["event_index"]
    assert case.world.ops().count("parameter.set") == 1
    assert "model.save" not in case.world.ops()
    assert error["details"]["native_diagnostic_error"]["details"]["operation"] == "parameter.list"
    with patch.dict(os.environ, case.env, clear=True):
        assert operations.get(dry["preview"]["operation_id"])["status"] == "unknown"


@pytest.mark.parametrize("boundary", (1, 2, 3))
def test_parent_boundary_diagnostic_preserves_completed_child_and_zero_followup(case, boundary):
    args = ("workflow", "run", "--request", workflow_request(case, save=False))
    dry = case.cli(*args, "--dry-run")["data"]
    original = case.world.handle
    count = {"wrote": False, "leaf_reads": 0, "models": 0, "fired": False, "index": None}

    def handle(op, request):
        reply, keep = original(op, request)
        if op == "parameter.set":
            count["wrote"] = True
        if count["wrote"] and op == "parameter.list":
            count["leaf_reads"] += 1
        if count["leaf_reads"] >= 2 and op == "model.show":
            count["models"] += 1
            if count["models"] == boundary and not count["fired"]:
                count.update(fired=True, index=len(case.world.events))
                return diagnostic(op), keep
        return reply, keep

    case.world.handle = handle
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=1)["error"]
    assert count["fired"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert len(case.world.events) == count["index"]
    assert case.world.ops().count("parameter.set") == 1
    child = error["details"]["receipt"]["extensions"]["creo"]["workflow"]["steps"][0]
    assert child["status"] == "completed"
    assert child["receipt"]["outcome"]["change"] == "applied"
    with patch.dict(os.environ, case.env, clear=True):
        assert operations.get(dry["preview"]["operation_id"])["status"] == "unknown"


@pytest.mark.parametrize("mode", ("query", "resolve"))
def test_independent_inspection_stop_keeps_original_write_receipt(case, mode):
    ident, original_status = unknown_saved_operation(case, common_name=mode == "resolve")
    if mode == "query":
        args = ("operation", "query", "--id", ident, "--model", "block")
    else:
        args = (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "independent controlled inspection remains incomplete",
        )
        dry = case.cli(*args, "--dry-run")["data"]
        args += ("--confirm", dry["confirm_token"])
    read = "model.management-state" if mode == "resolve" else "model.show"
    original = case.world.handle

    def handle(op, request):
        reply, keep = original(op, request)
        return (diagnostic(op) if op == read else reply), keep

    case.world.handle = handle
    case.world.events.clear()
    error = case.cli(*args, status=1)["error"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert case.world.ops() == [read]
    assert error["details"]["parent_operation_id"] == ident
    assert "operation_id" not in error["details"]
    assert "receipt" not in error["details"]
    shown = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert shown["receipt"] == original_status["receipt"]


@pytest.mark.parametrize("kind", ("note", "balloons"))
@pytest.mark.parametrize("stage", ("normal", "write_summary", "verify"))
def test_actual_public_note_and_balloon_paths_preserve_created_identity(case, kind, stage):
    if kind == "balloons":
        case.gated("assembly", "create", "--name", "rig", "--units", "mmns")
        case.world.assembly_add(
            {"model": "rig.asm", "component": "block.prt", "constraints": [{"type": "default"}]}
        )
        source = "rig.asm"
    else:
        source = "block.prt"
    case.world.drawing_create({"name": "drawing.drw", "of": source, "sheet": "a3"})
    drawing = case.world.models["drawing.drw"]
    if kind == "balloons":
        # Arrange an existing repeat-region resource in the HTTP substitute. The
        # synthetic template whitelist patch cannot affect an independent EXE;
        # BOM insertion is not the operation under test here.
        case.world.drawing_add_bom({"model": "drawing.drw", "at": [10, 50]})
        table = drawing["tables"][0]
        view = drawing["views"][0]["name"]
        args = (
            "drawing",
            "bom",
            "balloons",
            "--model",
            "drawing",
            "--table",
            table["id"],
            "--view",
            view,
        )
        wire = "drawing.add-balloons"
    else:
        args = (
            "drawing",
            "note",
            "add",
            "--model",
            "drawing",
            "--text",
            "SYNTHETIC TEST ONLY",
            "--x",
            30,
            "--y",
            30,
        )
        wire = "drawing.add-note"
    dry = case.cli(*args, "--dry-run")["data"]
    original = case.world.handle
    state = {"wrote": False, "fired": False, "index": None}

    def handle(op, request):
        reply, keep = original(op, request)
        if op == wire:
            state["wrote"] = True
        trigger = (stage == "write_summary" and op == wire) or (
            stage == "verify" and state["wrote"] and op == "model.show"
        )
        if trigger and not state["fired"]:
            state.update(fired=True, index=len(case.world.events))
            stopped = diagnostic(op, completion=stage == "write_summary")
            for event in stopped["error"]["native_diagnostic"]["effects"]:
                event["facts"]["target"] = "drawing.drw"
                event["facts"]["created_ids"] = [str(row["id"]) for row in drawing["notes"]]
            return stopped, keep
        return reply, keep

    case.world.handle = handle
    case.world.events.clear()
    result = case.cli(
        *args, "--confirm", dry["confirm_token"], status=0 if stage == "normal" else 1
    )
    assert case.world.ops().count(wire) == 1
    assert len(drawing["notes"]) == 1
    if stage == "normal":
        assert result["ok"] is True
        return
    assert result["error"]["code"] == "E_NATIVE_DIAGNOSTIC"
    assert len(case.world.events) == state["index"]
    receipt = result["error"]["details"]["receipt"]
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["change"] == "unknown"
    if stage == "write_summary":
        retained = receipt["extensions"]["creo"]["native_write_returned"]
        assert retained["facts"]["created_ids"] == [str(drawing["notes"][0]["id"])]


@pytest.mark.parametrize("effects", (None, 1, {}, "unreadable", [None]))
def test_malformed_effects_cannot_hide_diagnostic_stop_or_claim_setter_completion(case, effects):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    original = case.world.handle
    index = []

    def handle(op, request):
        reply, keep = original(op, request)
        if op == "parameter.set":
            reply = diagnostic(op, completion=True)
            reply["error"]["native_diagnostic"]["effects"] = deepcopy(effects)
            index.append(len(case.world.events))
        return reply, keep

    case.world.handle = handle
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert len(case.world.events) == index[0]
    assert case.world.ops().count("parameter.set") == 1
    context = error["details"]["native_diagnostic_error"]
    assert context["details"]["native_diagnostic"]["effects"] == effects
    receipt = error["details"]["receipt"]
    assert receipt["outcome"]["execution"] == "unknown"
    assert receipt["outcome"]["change"] == "unknown"
    assert "native_write_returned" not in receipt["extensions"]["creo"]
