"""New bounded note policy over a real HTTP peer; no CAD or SDK claims."""

import os
from copy import deepcopy
from unittest.mock import patch

import pytest

from creo_cli import drawing_note_recovery, operations
from creo_cli.core import Error
from creo_cli.transport import Client
from tests.test_native_diagnostic_stop import diagnostic
from tests.test_native_read_context import PublicCase, arm

ARGS = (
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
    40,
)


@pytest.fixture
def case():
    value = PublicCase()
    value.setUp()
    value.part()
    value.world.drawing_create(
        {"name": "drawing.drw", "of": "block.prt", "sheet": "a3", "views": "none"}
    )
    value.world.drawing_add_note({"model": "drawing.drw", "text": "OLD NOTE", "at": [10, 15]})
    value.world.events.clear()
    try:
        yield value
    finally:
        value.doCleanups()


def test_new_policy_independently_verifies_identity_but_does_not_claim_layout(case):
    dry = case.cli(*ARGS, "--dry-run")["data"]
    intent = dry["preview"]["extensions"]["creo"]["note_intent"]
    assert intent["profile"] == drawing_note_recovery.PROFILE
    assert intent["units"] == "mm" and intent["sheet"] == 1
    result = case.cli(*ARGS, "--confirm", dry["confirm_token"])["data"]
    assert result["receipt"]["outcome"]["verification"]["status"] == "passed"
    assert result["result"]["note"]["membership_readback"]["complete"] is True
    assert "new_note_native_2d_bounds" in result["verification"]["not_checked"]
    observed = next(
        row
        for row in result["verification"]["observations"]
        if row["observation"] == "independent_note_bounds"
    )
    assert observed["layout_complete"] is False
    before = deepcopy(case.world.events)
    case.cli(*ARGS, "--confirm", dry["confirm_token"], status=6)
    assert before == case.world.events


def test_native_note_id_zero_is_valid(case):
    original = case.world.handle

    def handle(op, request):
        result = original(op, request)
        if op == "drawing.add-note":
            case.world.models["drawing.drw"]["notes"][-1]["id"] = 0
        return result

    case.world.handle = handle
    result = case.gated(*ARGS)["data"]
    assert result["result"]["note"]["id"] == "0"


@pytest.mark.parametrize(
    "fault",
    (
        "wrong_text",
        "wrong_display",
        "wrong_sheet",
        "foreign_member",
        "wrong_member_id",
        "wrong_attachment",
        "wrong_position",
        "leader",
        "missing_display",
        "missing_anchor",
        "extra_note",
        "reused_id",
        "old_note_changed",
        "source_changed",
        "boolean_attachment_sheet",
    ),
)
def test_creation_reply_cannot_replace_independent_note_or_protection_checks(case, fault):
    dry = case.cli(*ARGS, "--dry-run")["data"]
    original = case.world.handle

    def handle(op, request):
        result = original(op, request)
        if op == "drawing.add-note":
            drawing = case.world.models["drawing.drw"]
            note = drawing["notes"][-1]
            if fault == "wrong_text":
                note["text"] = "WRONG"
            if fault == "wrong_display":
                note["displayed_text"] = "WRONG"
            if fault == "wrong_sheet":
                note["sheet"] = 2
            if fault == "foreign_member":
                note["membership_readback"] = {
                    "complete": True,
                    "drawing": "foreign.drw",
                    "note_id": note["id"],
                    "source": "independent wrong owner",
                }
            if fault == "wrong_member_id":
                note["membership_readback"] = {
                    "complete": True,
                    "drawing": "drawing.drw",
                    "note_id": 999,
                    "source": "independent wrong member",
                }
            if fault == "wrong_attachment":
                note["attachment_readback"]["background"] = False
            if fault == "wrong_position":
                note["at"][0] += 0.01
            if fault == "leader":
                note["leaders"] = [{"model": "block.prt"}]
            if fault == "missing_display":
                note.pop("displayed_text")
            if fault == "missing_anchor":
                note.pop("at")
            if fault == "extra_note":
                drawing["notes"].append(deepcopy(note) | {"id": 999})
            if fault == "reused_id":
                note["id"] = drawing["notes"][0]["id"]
            if fault == "old_note_changed":
                drawing["notes"][0]["text"] = "UNAUTHORIZED"
            if fault == "source_changed":
                case.world.models["block.prt"]["volume"] += 1
            if fault == "boolean_attachment_sheet":
                note["attachment_readback"]["sheet"] = True
        return result

    case.world.handle = handle
    error = case.cli(*ARGS, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] in ("E_VERIFY_FAILED", "E_VERIFY_INCOMPLETE")
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert case.world.ops().count("drawing.add-note") == 1


def test_old_service_is_refused_before_any_cad_model_read(case):
    case.world.capabilities.pop(drawing_note_recovery.CAPABILITY)
    case.world.events.clear()
    error = case.cli(*ARGS, "--dry-run", status=4)["error"]
    assert error["code"] == "E_BACKEND_UNAVAILABLE"
    assert case.world.ops() == []


@pytest.mark.parametrize("fault", ("multi_page", "units", "missing_membership", "wrong_active"))
def test_unsupported_or_unreadable_baseline_rejected_before_write(case, fault):
    drawing = case.world.models["drawing.drw"]
    if fault == "multi_page":
        drawing["sheets"].append(drawing["sheets"][0] | {"number": 2})
    if fault == "units":
        drawing["sheets"][0]["units"] = "inch"
    if fault == "missing_membership":
        drawing["notes"][0]["membership_readback"] = {"complete": False}
    if fault == "wrong_active":
        case.world.active = "block.prt"
    status = {"multi_page": 2, "units": 2, "missing_membership": 1, "wrong_active": 6}[fault]
    case.cli(*ARGS, "--dry-run", status=status)
    assert "drawing.add-note" not in case.world.ops()


def unknown(case):
    dry = case.cli(*ARGS, "--dry-run")["data"]
    case.world.drop = "drawing.add-note"
    case.cli(*ARGS, "--confirm", dry["confirm_token"], status=6)
    case.world.drop = None
    return dry["preview"]["operation_id"]


def test_query_and_registration_reuse_frozen_predicate_and_preserve_original_receipt(case):
    ident = unknown(case)
    original = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]
    query = case.cli("operation", "query", "--id", ident, "--model", "drawing.drw")["data"]
    proof = query["observation"]["simple_note_verification"]
    assert proof["accepted"] and proof["can_register"] == ["applied"]
    args = (
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "applied",
        "--evidence",
        "independent current note and protected resources verified",
    )
    case.gated(*args)
    shown = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert shown["receipt"] == original
    assert (
        shown["extensions"]["creo"]["simple_note_inspection"]["current_requirements_satisfied"]
        is True
    )
    assert case.world.ops().count("drawing.add-note") == 1


@pytest.mark.parametrize("mode", ("query", "resolve"))
def test_inspection_capability_gate_precedes_all_cad_reads(case, mode):
    ident = unknown(case)
    case.world.capabilities.pop(drawing_note_recovery.CAPABILITY)
    case.world.events.clear()
    if mode == "query":
        args = ("operation", "query", "--id", ident, "--model", "drawing.drw")
    else:
        args = (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "cannot bypass an unqualified legacy service",
            "--dry-run",
        )
    case.cli(*args, status=4)
    assert case.world.ops() == []


def test_no_new_policy_is_inferred_for_an_old_receipt(case):
    ident = unknown(case)
    with patch.dict(os.environ, case.env, clear=True):
        run = operations.get(ident)
        saved = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
        saved.pop("note_intent")
        operations.update(run)
    case.world.events.clear()
    error = case.cli("operation", "query", "--id", ident, "--model", "drawing.drw", status=2)[
        "error"
    ]
    assert error["code"] == "E_UNSUPPORTED"
    assert case.world.ops() == []


@pytest.mark.parametrize("fault", ("request", "binding", "source_protection"))
def test_frozen_intent_and_input_binding_drift_refused_without_cad(case, fault):
    ident = unknown(case)
    with patch.dict(os.environ, case.env, clear=True):
        run = operations.get(ident)
        if fault == "request":
            run["driver_plan"]["changes"][0]["after"]["text"] = "ALTERED"
        elif fault == "binding":
            run["driver_binding"]["arguments"]["request"]["at"] = [10, 10]
        else:
            run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]["note_before"][
                "sources"
            ] = {}
        operations.update(run)
    case.world.events.clear()
    error = case.cli("operation", "query", "--id", ident, "--model", "drawing.drw", status=1)[
        "error"
    ]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert case.world.ops() == []


@pytest.mark.parametrize(
    "fault",
    (
        "source_value",
        "base_revision",
        "binding_revision",
        "binding_target",
        "binding_command",
        "bound_instance",
        "plan_object_id",
    ),
)
def test_whole_frozen_observation_and_target_bindings_checked_before_cad(case, fault):
    if fault == "source_value":
        # Hold the nonempty/empty-derived fields constant for this exact drift case.
        case.world.models["block.prt"]["volume"] = 100.0
    ident = unknown(case)
    original_receipt = case.cli("operation", "show", "--id", ident)["data"]["operation_status"][
        "receipt"
    ]
    with patch.dict(os.environ, case.env, clear=True):
        run = operations.get(ident)
        if fault == "source_value":
            # An altered baseline made equal to current drift must not become evidence.
            source = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"][
                "note_before"
            ]["sources"]["block.prt"]
            source["mass_properties"]["volume"] += 0.0005
            case.world.models["block.prt"]["volume"] = source["mass_properties"]["volume"]
        elif fault == "base_revision":
            run["driver_plan"]["base_snapshot"]["revision"] = "0" * 64
        elif fault == "binding_revision":
            run["driver_binding"]["revision"] = "0" * 64
        elif fault == "binding_target":
            run["driver_binding"]["target"] = "another.drw"
        elif fault == "binding_command":
            run["driver_binding"]["command"] = "drawing view add"
        elif fault == "bound_instance":
            run["driver_binding"]["driver_target"]["instance_id"] = "another-generation"
        else:
            run["driver_plan"]["target"]["object_id"] = "another.drw"
        operations.update(run)
    case.world.events.clear()
    error = case.cli("operation", "query", "--id", ident, "--model", "drawing.drw", status=1)[
        "error"
    ]
    assert error["code"] == "E_VERIFY_INCOMPLETE"
    assert case.world.ops() == []
    shown = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert shown["receipt"] == original_receipt


@pytest.mark.parametrize("fault", ("sheet_number", "old_note_sheet", "old_attachment_sheet"))
def test_boolean_page_metadata_is_not_an_observed_native_sheet(case, fault):
    result = case.gated(*ARGS)["data"]
    with patch.dict(os.environ, case.env, clear=True):
        before, _ = drawing_note_recovery.retained(operations.get(result["operation_id"]))
    drawing = deepcopy(before["drawing"])
    if fault == "sheet_number":
        drawing["sheets"][0]["number"] = True
    elif fault == "old_note_sheet":
        drawing["notes"][0]["sheet"] = True
    else:
        drawing["notes"][0]["attachment_readback"]["sheet"] = True
    case.world.events.clear()
    with pytest.raises(Error):
        drawing_note_recovery.validate_drawing(drawing, "drawing.drw")
    assert case.world.ops() == []


def test_shared_pure_predicate_does_not_accept_a_boolean_attachment_page(case):
    result = case.gated(*ARGS)["data"]
    with patch.dict(os.environ, case.env, clear=True):
        before, wanted = drawing_note_recovery.retained(operations.get(result["operation_id"]))
        with Client(30) as client:
            after = drawing_note_recovery.snapshot(
                client, "drawing.drw", baseline=False, source_models=wanted["source_models"]
            )
    assert drawing_note_recovery.verify(before, wanted, after)["accepted"]
    after["drawing"]["notes"][-1]["attachment_readback"]["sheet"] = True
    case.world.events.clear()
    assert not drawing_note_recovery.verify(before, wanted, after)["accepted"]
    assert case.world.ops() == []


@pytest.mark.parametrize(
    "fault", ("old_sheet", "drawing_sheet", "old_attachment_sheet", "view_sheet")
)
def test_preserved_objects_do_not_alias_boolean_and_integer_pages(case, fault):
    result = case.gated(*ARGS)["data"]
    with patch.dict(os.environ, case.env, clear=True):
        before, wanted = drawing_note_recovery.retained(operations.get(result["operation_id"]))
        with Client(30) as client:
            after = drawing_note_recovery.snapshot(
                client, "drawing.drw", baseline=False, source_models=wanted["source_models"]
            )
    if fault == "view_sheet":
        view = {"id": "5", "sheet": 1, "model": "block.prt", "name": "OWNED"}
        before["drawing"]["views"].append(view)
        after["drawing"]["views"].append(deepcopy(view))
    assert drawing_note_recovery.verify(before, wanted, after)["accepted"]
    if fault == "old_sheet":
        after["drawing"]["notes"][0]["sheet"] = True
    elif fault == "drawing_sheet":
        after["drawing"]["sheets"][0]["number"] = True
    elif fault == "old_attachment_sheet":
        after["drawing"]["notes"][0]["attachment_readback"]["sheet"] = True
    else:
        after["drawing"]["views"][0]["sheet"] = True
    case.world.events.clear()
    assert not drawing_note_recovery.verify(before, wanted, after)["accepted"]
    assert case.world.ops() == []


@pytest.mark.parametrize("fault", ("missing_sources", "foreign_source", "wrong_target_type"))
def test_retained_proof_rechecks_required_sources_and_target_type(case, fault):
    result = case.gated(*ARGS)["data"]
    with patch.dict(os.environ, case.env, clear=True):
        run = operations.get(result["operation_id"])
        before, wanted = drawing_note_recovery.retained(run)
        with Client(30) as client:
            after = drawing_note_recovery.snapshot(
                client, "drawing.drw", baseline=False, source_models=wanted["source_models"]
            )
    assert drawing_note_recovery.verify(before, wanted, after)["accepted"]
    if fault == "missing_sources":
        after.pop("sources")
    elif fault == "foreign_source":
        after["sources"]["block.prt"]["model"] = "foreign.prt"
    else:
        after["drawing"]["type"] = "part"
    proof = {"intent": wanted, "current": after, "accepted": True}
    assert not drawing_note_recovery.verify(before, wanted, after)["accepted"]
    with pytest.raises(Error, match="does not satisfy"):
        drawing_note_recovery.retained_evidence_sufficient(run, proof)


@pytest.mark.parametrize("value", ("00", "０", True, -1))
def test_native_identity_does_not_merge_noncanonical_or_boolean_ids(value):
    assert drawing_note_recovery.native_id(value) is None
    assert drawing_note_recovery.native_id(0) == "0"


@pytest.mark.parametrize("fault", ("busy_started", "unavailable_started", "reply_lost"))
def test_note_verification_pending_preserves_write_and_zero_followup(case, fault):
    dry = case.cli(*ARGS, "--dry-run")["data"]
    state = arm(case, fault, read="model.show", after="drawing.add-note")
    case.world.events.clear()
    error = case.cli(*ARGS, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["details"]["receipt"]["outcome"]["execution"] == "completed"
    assert error["details"]["native_read_error"]["code"] == "E_NATIVE_READ_PENDING"
    assert case.world.ops().count("drawing.add-note") == 1
    assert case.world.ops()[state["event_index"] :] == ["model.show"]
    events = deepcopy(case.world.events)
    case.cli(*ARGS, "--confirm", dry["confirm_token"], status=6)
    assert events == case.world.events


def test_note_diagnostic_stop_does_not_enter_another_getter_or_replay(case):
    dry = case.cli(*ARGS, "--dry-run")["data"]
    original = case.world.handle
    state = {"created": False, "fired": False, "end": None}

    def handle(op, request):
        reply, keep = original(op, request)
        if state["created"] and op == "model.show":
            state.update(fired=True, end=len(case.world.events))
            return diagnostic(op), keep
        if op == "drawing.add-note":
            state["created"] = True
        return reply, keep

    case.world.handle = handle
    error = case.cli(*ARGS, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_NATIVE_DIAGNOSTIC"
    assert state["fired"] and len(case.world.events) == state["end"]
    assert case.world.ops().count("drawing.add-note") == 1
    assert error["details"]["receipt"]["outcome"]["execution"] == "completed"
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] == "incomplete"
    assert "native_read_error" not in error["details"]
