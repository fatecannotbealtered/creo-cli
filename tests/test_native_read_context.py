"""Public recovery context uses a real HTTP peer; no Creo or native geometry.

Set CREO_CLI_TEST_PUBLIC_COMMAND to a JSON argv prefix to exercise a built EXE.
All configuration, scope, service token and records are synthetic and isolated.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from creo_cli import operations
from tests.test_commands import RECT, ROOT, Base

DIAGNOSTIC_ID = "r26-controlled-verification-read"
PARAMETER_ARGS = (
    "parameter",
    "set",
    "--model",
    "block",
    "--name",
    "DESCRIPTION",
    "--type",
    "string",
    "--value",
    "controlled",
)
PENDING_FAULTS = ("busy_started", "unavailable_started", "reply_lost", "busy_started_no_diagnostic")


class PublicCase(Base):
    """Use the public parser/envelope, optionally in a separate product process."""

    __test__ = False

    def setUp(self):
        super().setUp()
        self.public_calls = []
        self.http_headers = []
        case = self
        original = self.server.http.RequestHandlerClass

        class RecordedHandler(original):
            def do_POST(self):
                case.http_headers.append(
                    {
                        "path": self.path,
                        "cli_invocation_id": self.headers.get("X-Creo-Cli-Invocation-Id"),
                    }
                )
                return super().do_POST()

        self.server.http.RequestHandlerClass = RecordedHandler

    def cli(self, *args, status=0, **kwargs):
        command = os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND")
        if not command:
            result = super().cli(*args, status=status, **kwargs)
            self.public_calls.append(
                {"args": list(map(str, args)), "exit": status, "result": result}
            )
            return result
        run = subprocess.run(
            [*json.loads(command), *map(str, args)],
            cwd=ROOT,
            env=(kwargs.get("env") or self.env) | {"PYTHONIOENCODING": "utf-8"},
            input=kwargs.get("stdin"),
            capture_output=True,
            encoding="utf-8",
            timeout=45,
        )
        result = json.loads(run.stdout)
        self.public_calls.append(
            {
                "args": list(map(str, args)),
                "exit": run.returncode,
                "stdout": run.stdout,
                "stderr": run.stderr,
                "result": result,
            }
        )
        self.assertEqual(run.returncode, status, result)
        self.assertNotIn(self.world.token, run.stdout + run.stderr)
        return result


@pytest.fixture
def case(request):
    value = PublicCase()
    value.setUp()
    value.part()
    try:
        yield value
    finally:
        evidence = os.environ.get("R26_READ_CONTEXT_EVIDENCE")
        if evidence:
            folder = Path(evidence)
            folder.mkdir(parents=True, exist_ok=True)
            name = request.node.name.replace("/", "_").replace("\\", "_").replace(":", "_")
            (folder / (name + ".json")).write_text(
                json.dumps(
                    {
                        "kind": "controlled_http_public_cli",
                        "real_native_calls": 0,
                        "public_calls": value.public_calls,
                        "events": value.world.events,
                        "http_headers": value.http_headers,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        value.doCleanups()


def arm(case, fault, *, read="parameter.list", after="parameter.set", occurrence=1):
    """Fail the requested real HTTP response after a setter has returned success."""
    original = case.world.handle
    state = {"after": False, "reads": 0, "fired": False, "event_index": None}

    def handle(op, request):
        if state["after"] and op == read:
            state["reads"] += 1
            if state["reads"] == occurrence:
                state["fired"] = True
                state["event_index"] = len(case.world.events)
                if fault == "reply_lost":
                    case.world.drop = read
                elif fault == "verification_failed":
                    pass
                else:
                    code = "E_UNAVAILABLE" if fault.startswith("unavailable") else "E_BUSY"
                    case.world.fail = (
                        read,
                        {
                            "code": code,
                            "message": "controlled required getter has not returned",
                            "started": fault not in ("withdrawn", "unavailable_unstarted"),
                        },
                    )
        answer, keep = original(op, request)
        if op == after:
            state["after"] = True
        if state["fired"] and op == read:
            if fault in (
                "busy_started",
                "unavailable_started",
                "withdrawn",
                "unavailable_unstarted",
            ):
                answer["diagnostic_request_id"] = DIAGNOSTIC_ID
            elif fault == "verification_failed":
                next(row for row in answer["data"]["parameters"] if row["name"] == "DESCRIPTION")[
                    "value"
                ] = "wrong-controlled-value"
        return answer, keep

    case.world.handle = handle
    return state


def pending_context(error, fault, operation):
    context = error["details"]["native_read_error"]
    assert context["code"] == "E_NATIVE_READ_PENDING"
    assert context["retryable"] is False
    details = context["details"]
    assert details["operation"] == operation
    assert details["dispatch_state"] == ("unknown" if fault == "reply_lost" else "started")
    assert (
        details["cause_code"]
        == {
            "reply_lost": "E_NETWORK",
            "busy_started": "E_BUSY",
            "unavailable_started": "E_UNAVAILABLE",
            "busy_started_no_diagnostic": "E_BUSY",
        }[fault]
    )
    assert details["cause"]
    assert details["cli_invocation_id"]
    assert details["request_sent"] is True
    assert "blocked_requested_operation" not in details
    assert details["automatic_retry"] is False
    if fault == "reply_lost":
        assert "started" not in details
        assert "diagnostic_request_id" not in details
    else:
        assert details["started"] is True
        if fault.endswith("no_diagnostic"):
            assert "diagnostic_request_id" not in details
        else:
            assert details["diagnostic_request_id"] == DIAGNOSTIC_ID
    return context


def safe_guidance(value):
    text = json.dumps(value, ensure_ascii=False).lower()
    assert "model show" not in text
    assert "feature list" not in text
    # Mentioning query as forbidden until independent confirmation is appropriate;
    # offering it as the next immediate command would be unsafe.
    assert "confirm the original call and instance state before" in text
    assert "stop" in text
    assert "cad" in text
    assert "process-only" in text
    assert "operation show" in text


def local_retained(case, ident, error, context):
    before = list(case.world.events)
    saved = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert case.world.events == before
    receipt = error["details"]["receipt"]
    assert saved["receipt"] == receipt
    assert receipt["extensions"]["creo"]["native_read_error"] == context
    assert saved["extensions"]["creo"]["native_read_error"] == context
    assert context["details"]["cli_invocation_id"] in {
        row["cli_invocation_id"] for row in case.http_headers
    }
    safe_guidance(
        {
            "next_action": error["details"]["next_action"],
            "fix": error["details"].get("fix"),
            "recovery": receipt["recovery"],
        }
    )
    return saved


@pytest.mark.parametrize("fault", PENDING_FAULTS)
def test_direct_completed_setter_retains_original_pending_read_and_safe_guidance(case, fault):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    state = arm(case, fault)
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)["error"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert error["details"]["operation_id"] == dry["preview"]["operation_id"]
    assert error["details"]["dispatch_state"] == "dispatched"
    assert error["details"]["receipt"]["outcome"]["execution"] == "completed"
    assert error["details"]["receipt"]["outcome"]["change"] == "unknown"
    assert error["details"]["receipt"]["outcome"]["persistence"] == "unknown"
    assert case.world.ops().count("parameter.set") == 1
    assert case.world.ops()[state["event_index"] :] == ["parameter.list"]
    context = pending_context(error, fault, "parameter.list")
    local_retained(case, dry["preview"]["operation_id"], error, context)
    before = list(case.world.events)
    case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)
    assert case.world.events == before


@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_dimension_verifier_internal_error_handling_keeps_first_pending_read(case, fault):
    case.gated("feature", "extrude", "--model", "block", "--request", case.request(RECT))
    rows = case.cli("dimension", "list", "--model", "block")["data"]["items"]
    selected = next(
        row for row in rows if not row.get("reference") and not row.get("relation_driven")
    )
    args = (
        "dimension",
        "set",
        "--model",
        "block",
        "--dimension",
        selected["id"],
        "--value",
        selected["value"] + 1,
        "--units",
        "mm",
    )
    dry = case.cli(*args, "--dry-run")["data"]
    state = arm(case, fault, read="dimension.list", after="dimension.set")
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    assert case.world.ops().count("dimension.set") == 1
    assert case.world.ops()[state["event_index"] :] == ["dimension.list"]
    assert error["details"]["receipt"]["outcome"]["execution"] == "completed"
    context = pending_context(error, fault, "dimension.list")
    local_retained(case, dry["preview"]["operation_id"], error, context)


@pytest.mark.parametrize("fault", ("withdrawn", "unavailable_unstarted", "verification_failed"))
def test_nonpending_verification_failure_is_not_promoted_to_pending(case, fault):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    arm(case, fault)
    error = case.cli(
        *PARAMETER_ARGS,
        "--confirm",
        dry["confirm_token"],
        status=1 if fault == "verification_failed" else 6,
    )["error"]
    assert error["code"] != "E_NATIVE_READ_PENDING"
    assert "native_read_error" not in error["details"]
    assert "native_read_error" not in error["details"]["receipt"]["extensions"]["creo"]
    if fault == "verification_failed":
        assert error["code"] == "E_VERIFY_FAILED"
        assert error["details"]["receipt"]["outcome"]["verification"]["status"] == "failed"
    assert case.world.ops().count("parameter.set") == 1


@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_post_verification_effect_snapshot_pending_retains_original_read(case, fault):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    state = arm(case, fault, occurrence=2)
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)["error"]
    assert state["fired"]
    assert case.world.ops()[state["event_index"] :] == ["parameter.list"]
    assert case.world.ops().count("parameter.set") == 1
    assert error["details"]["dispatch_state"] == "dispatched"
    assert error["details"]["receipt"]["outcome"]["execution"] == "completed"
    context = pending_context(error, fault, "parameter.list")
    local_retained(case, dry["preview"]["operation_id"], error, context)


@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_failed_setter_settlement_read_pending_retains_context_without_claiming_completion(
    case, fault
):
    dry = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    state = arm(case, fault)
    case.world.fail_after = (
        "parameter.set",
        {"code": "E_CREO", "message": "controlled failed setter after dispatch"},
    )
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", dry["confirm_token"], status=6)["error"]
    assert state["fired"]
    assert case.world.ops()[state["event_index"] :] == ["parameter.list"]
    assert case.world.ops().count("parameter.set") == 1
    assert error["details"]["receipt"]["outcome"]["execution"] != "completed"
    context = pending_context(error, fault, "parameter.list")
    local_retained(case, dry["preview"]["operation_id"], error, context)


def workflow_request(case, *, save=True):
    steps = [
        {
            "id": "change",
            "kind": "write",
            "command": "parameter set",
            "args": {
                "model": "block",
                "name": "DESCRIPTION",
                "type": "string",
                "value": "controlled",
            },
        }
    ]
    if save:
        steps.append(
            {"id": "save", "kind": "write", "command": "model save", "args": {"model": "block"}}
        )
    return case.request({"steps": steps}, name="workflow.json")


@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_workflow_leaf_pending_retains_parent_child_facts_and_blocks_outer_client(case, fault):
    args = ("workflow", "run", "--request", workflow_request(case))
    dry = case.cli(*args, "--dry-run")["data"]
    state = arm(case, fault)
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    context = pending_context(error, fault, "parameter.list")
    assert case.world.ops()[state["event_index"] :] == ["parameter.list"]
    assert case.world.ops().count("parameter.set") == 1
    assert "model.save" not in case.world.ops()
    saved = local_retained(case, dry["preview"]["operation_id"], error, context)
    rows = saved["extensions"]["creo"]["workflow"]["steps"]
    assert [row["status"] for row in rows] == ["unknown", "skipped"]
    child = rows[0]
    assert child["operation_id"]
    assert child["receipt"]["outcome"]["execution"] == "completed"
    assert child["receipt"]["extensions"]["creo"]["native_read_error"] == context
    assert rows[1]["operation_id"] is None
    assert rows[1]["receipt"] is None


@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
@pytest.mark.parametrize("parent_boundary", (1, 2, 3))
def test_parent_sampling_pending_preserves_already_completed_child(case, fault, parent_boundary):
    args = ("workflow", "run", "--request", workflow_request(case, save=False))
    dry = case.cli(*args, "--dry-run")["data"]
    # The simple parameter leaf reads parameter.list to verify, then once to retain
    # its independent snapshot. The next model.show is the parent's boundary.
    original = case.world.handle
    count = {"post_set_reads": 0, "set": False, "armed": False, "index": None, "models": 0}

    def handle(op, request):
        if count["set"] and op == "parameter.list":
            count["post_set_reads"] += 1
        if count["post_set_reads"] >= 2 and op == "model.show":
            count["models"] += 1
        if count["models"] == parent_boundary and op == "model.show" and not count["armed"]:
            count["armed"] = True
            count["index"] = len(case.world.events)
            if fault == "reply_lost":
                case.world.drop = op
            else:
                case.world.fail = (
                    op,
                    {
                        "code": "E_BUSY",
                        "message": "parent boundary getter pending",
                        "started": True,
                    },
                )
        answer, keep = original(op, request)
        if op == "parameter.set":
            count["set"] = True
        if count["armed"] and op == "model.show" and fault != "reply_lost":
            answer["diagnostic_request_id"] = DIAGNOSTIC_ID
        return answer, keep

    case.world.handle = handle
    case.world.events.clear()
    error = case.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
    assert count["armed"]
    assert case.world.ops()[count["index"] :] == ["model.show"]
    assert case.world.ops().count("parameter.set") == 1
    context = pending_context(error, fault, "model.show")
    saved = local_retained(case, dry["preview"]["operation_id"], error, context)
    rows = saved["extensions"]["creo"]["workflow"]["steps"]
    assert rows[0]["status"] == "completed"
    assert rows[0]["receipt"]["outcome"]["execution"] == "completed"
    assert rows[0]["receipt"]["outcome"]["change"] == "applied"
    assert "native_read_error" not in rows[0]["receipt"]["extensions"]["creo"]


def unknown_saved_operation(case, *, common_name=False):
    args = (
        ("model", "set-common-name", "--model", "block", "--name", "INSPECTED")
        if common_name
        else ("model", "save", "--model", "block")
    )
    native = "model.set-common-name" if common_name else "model.save"
    dry = case.cli(*args, "--dry-run")["data"]
    case.world.drop = native
    case.cli(*args, "--confirm", dry["confirm_token"], status=6)
    case.world.drop = None
    ident = dry["preview"]["operation_id"]
    original = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    return ident, original


@pytest.mark.parametrize("mode", ("query", "resolve"))
@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_independent_inspection_pending_preserves_original_write_and_read_context(
    case, mode, fault
):
    ident, original = unknown_saved_operation(case, common_name=mode == "resolve")
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
            "controlled independent inspection",
        )
        dry = case.cli(*args, "--dry-run")["data"]
        args += ("--confirm", dry["confirm_token"])
    read = "model.management-state" if mode == "resolve" else "model.show"
    state = arm(case, fault, read=read, after="not-dispatched")
    # The previous write is already unknown. Arm before this inspection's first
    # model.show while leaving health and the authorization checks untouched.
    state["after"] = True
    case.world.events.clear()
    error = case.cli(*args, status=8)["error"]
    assert error["code"] == "E_NATIVE_READ_PENDING"
    assert error["details"]["parent_operation_id"] == ident
    assert "operation_id" not in error["details"]
    assert "receipt" not in error["details"]
    # For an inspection the original transport error remains the top-level error.
    context = error["details"].get(
        "native_read_error",
        {
            "code": error["code"],
            "message": error["message"],
            "retryable": error["retryable"],
            "details": {
                key: value
                for key, value in error["details"].items()
                if key != "parent_operation_id"
            },
        },
    )
    pending_context({"details": {"native_read_error": context}}, fault, read)
    assert case.world.ops() == [read]
    evidence_path = (
        Path(case.env["CREO_CLI_CONFIG_DIR"])
        / "operation-queries"
        / (error["details"]["read_failure_evidence_id"] + ".json")
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["operation_id"] == ident
    assert evidence["proves_original_write_postconditions"] is False
    assert evidence["observation"]["read_status"] == "pending"
    assert evidence["observation"]["complete"] is False
    assert evidence["observation"]["native_read_error"] == context
    safe_guidance({"next_action": error["details"]["next_action"]})
    before = list(case.world.events)
    saved = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert case.world.events == before
    assert saved["receipt"] == original["receipt"]
    assert saved["resolution"] == original["resolution"]


def test_pending_query_sidecar_cannot_be_accepted_as_complete_legacy_evidence(case):
    # A synthetic historical record is seeded explicitly; it is not a new CAD
    # write or a claimed public write result. The query and resolve use public CLI.
    with patch.dict(os.environ, case.env, clear=True):
        run = operations.begin("feature extrude", "block.prt", {}, case.server.url)
        run["status"] = "unknown"
        operations.update(run)
    ident = run["operation_id"]
    state = arm(case, "busy_started", read="model.show", after="not-dispatched")
    state["after"] = True
    case.world.events.clear()
    error = case.cli("operation", "query", "--id", ident, "--model", "block", status=8)["error"]
    assert case.world.ops() == ["model.show"]
    before = list(case.world.events)
    rejected = case.cli(
        "operation",
        "resolve",
        "--id",
        ident,
        "--decision",
        "accept-observation",
        "--note",
        "controlled legacy inspection must remain incomplete",
        "--evidence",
        error["details"]["read_failure_evidence_id"],
        "--dry-run",
        status=1,
    )["error"]
    assert rejected["code"] == "E_VERIFY_INCOMPLETE"
    assert rejected["details"]["parent_operation_id"] == ident
    assert "operation_id" not in rejected["details"]
    assert rejected["details"]["native_read_error"] == error["details"]["native_read_error"]
    assert case.world.events == before
    original = case.cli("operation", "show", "--id", ident)["data"]["receipt"]
    assert original == run
