"""Explicit budget opt-in uses real controlled HTTP; no CAD or native timing claims."""

import json
import os
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from creo_cli import execution_budgets as budgets
from creo_cli import timing, transport
from creo_cli.contract_gen import META_OPTIONAL_KEYS, META_REQUIRED_KEYS
from creo_cli.core import Error, validate_schema
from tests.test_drawing_view_budget_reuse import VIEW, view_case  # noqa: F401


@contextmanager
def peer(*, capability=1, fault=None, stopped=False):
    events = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            events.append({"path": self.path, "profile": self.headers.get(budgets.HEADER)})
            self.reply(
                {
                    "ok": True,
                    "service": "creo-cli",
                    "protocol": 2,
                    "capabilities": {budgets.CAPABILITY: capability},
                    "native_diagnostic": {"stopped": stopped() if callable(stopped) else stopped},
                }
            )

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            events.append(
                {
                    "path": self.path,
                    "operation": body["op"],
                    "profile": self.headers.get(budgets.HEADER),
                    "wait_ms": int(self.headers[transport.WAIT_HEADER]),
                }
            )
            if fault == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True
            elif fault:
                self.reply({"ok": False, "error": {"code": fault, "started": True}})
            else:
                self.reply({"ok": True, "data": {"model": body.get("model")}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with (
            patch.object(
                transport, "endpoint", return_value=f"http://127.0.0.1:{server.server_port}"
            ),
            patch.object(transport, "read_token", return_value="synthetic-budget-token"),
        ):
            yield events
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("seconds", [0.1, 30, 300])
def test_legacy_budget_sends_no_profile_or_new_health(seconds):
    with peer(capability=None) as events, timing.command("model show", seconds):
        with transport.Client(seconds) as client:
            client.op("model.show", {"model": "owned.drw"})
    assert len(events) == 1
    assert events[0]["profile"] is None


@pytest.mark.parametrize(
    "command", ["workflow run", "drawing symbol add", "feature delete", "operation query"]
)
def test_unsupported_top_level_cannot_expand_budget(command):
    with pytest.raises(Error, match="0.1..300"):
        budgets.validate(command, 600)


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), 1200.1, 0, -1])
def test_invalid_extended_budget_refused(seconds):
    with pytest.raises(Error):
        budgets.validate("drawing bom add", seconds)


@pytest.mark.parametrize("seconds", [300.1, 600, 1200])
def test_capability_and_header_precede_first_cad_and_share_deadline(seconds):
    with peer() as events, timing.command("drawing bom add", seconds):
        with transport.Client(seconds) as client:
            deadline = client.deadline
            client.op("session.status")
            client.op("model.show", {"model": "dependency.prt"})
            assert client.deadline == deadline
            assert timing.execution_profile()["total_seconds"] == seconds
            assert timing.execution_profile()["native_request_max_seconds"] == 300
    assert [e["path"] for e in events] == ["/health", "/op", "/op"]
    assert events[0]["profile"] is None
    assert all(e["profile"] == budgets.PROFILE for e in events[1:])
    assert 0 < events[1]["wait_ms"] < seconds * 1000  # unchanged service clamps this to 300s


def test_extended_allowlist_is_exact_and_does_not_raise_ordinary_limits():
    assert budgets.COMMANDS == {
        "drawing create",
        "drawing view add",
        "drawing view move",
        "drawing view list",
        "drawing view show",
        "drawing note add",
        "drawing note list",
        "drawing note show",
        "drawing note edit",
        "drawing table move",
        "drawing table list",
        "drawing table show",
        "drawing bom add",
        "drawing bom balloons",
        "model show",
        "model save",
        "model close",
        "artifact export",
    }
    for command in budgets.COMMANDS:
        selected = budgets.selected(command, 1200)
        validate_schema(selected, budgets.SCHEMA)
        assert selected["total_seconds"] == 1200
        assert selected["native_request_max_seconds"] == 300
    declared = budgets.contract()
    assert declared["default_seconds"] == 30
    assert declared["ordinary_max_seconds"] == 300
    assert declared["ordinary_native_request_max_seconds"] == 120
    assert declared["extended_max_seconds"] == 1200
    assert declared["extended_native_request_max_seconds"] == 300


def test_old_service_refused_before_any_cad_request():
    with peer(capability=None) as events, timing.command("drawing bom add", 600):
        with transport.Client(600) as client, pytest.raises(Error) as caught:
            client.op("session.status")
    assert caught.value.code == "E_BACKEND_UNAVAILABLE"
    assert caught.value.details["request_sent"] is False
    assert [e["path"] for e in events] == ["/health"]


def test_health_stop_precedes_missing_capability_without_claiming_native_dispatch():
    with peer(capability=None, stopped=True) as events, timing.command("model show", 1200):
        with transport.Client(1200) as client:
            for _ in range(2):
                with pytest.raises(Error) as caught:
                    client.op("model.show", {"model": "owned.drw"})
                assert caught.value.code == "E_NATIVE_DIAGNOSTIC"
                assert caught.value.details["request_sent"] is False
                assert "started" not in caught.value.details
    assert [e["path"] for e in events] == ["/health"]


def test_command_specific_capability_cannot_mask_health_diagnostic():
    with peer(capability=None, stopped=True) as events, timing.command("model close", 600):
        with transport.Client(600) as client, pytest.raises(Error) as caught:
            client.require_capability("model_management_readback", 2)
    assert caught.value.code == "E_NATIVE_DIAGNOSTIC"
    assert caught.value.details["diagnostic_source"] == "process_only_health"
    assert caught.value.details["request_sent"] is False
    assert [e["path"] for e in events] == ["/health"]


def test_later_health_stop_blocks_an_already_admitted_client():
    state = {"stopped": False}
    with peer(stopped=lambda: state["stopped"]) as events, timing.command("model show", 600):
        with transport.Client(600) as client:
            client.op("model.show", {"model": "owned.drw"})
            state["stopped"] = True
            client.health()
            with pytest.raises(Error) as caught:
                client.op("model.show", {"model": "owned.drw"})
    assert caught.value.code == "E_NATIVE_DIAGNOSTIC"
    assert caught.value.details["request_sent"] is False
    assert [e["path"] for e in events] == ["/health", "/op", "/health"]


@pytest.mark.parametrize("fault", ["disconnect", "E_BUSY", "E_UNAVAILABLE"])
def test_long_budget_does_not_retry_or_unblock_pending_read(fault):
    with peer(fault=fault) as events, timing.command("model show", 600):
        with transport.Client(600) as client:
            with pytest.raises(Error) as first:
                client.op("model.show", {"model": "owned.drw"})
            assert first.value.code == "E_NATIVE_READ_PENDING"
            assert ("started" in first.value.details) == (fault != "disconnect")
            client.health()
            for write in (False, True):
                with pytest.raises(Error) as blocked:
                    client.op("model.save" if write else "model.show", {}, write=write)
                assert blocked.value.code == "E_NATIVE_READ_PENDING"
                assert blocked.value.details["request_sent"] is False
    assert sum(e["path"] == "/op" for e in events) == 1


def test_nested_leaf_cannot_expand_parent_or_reset_deadline():
    with timing.command("workflow run", 300):
        with timing.command("model show", 1200):
            assert timing.execution_profile() is None
            with transport.Client(1200) as client:
                assert client.remaining() <= 300


@pytest.mark.parametrize("seconds", [600, 1200])
def test_public_preview_receipt_bind_total_and_reject_changed_budget(view_case, seconds):  # noqa: F811
    c = view_case
    c.world.capabilities[budgets.CAPABILITY] = 1
    dry = c.cli(*VIEW, "--timeout", seconds, "--dry-run")["data"]
    policy = dry["preview"]["extensions"]["creo"]["execution_budget"]
    assert policy["total_seconds"] == seconds
    validate_schema(policy, budgets.SCHEMA)
    c.world.events.clear()
    refused = c.cli(*VIEW, "--timeout", seconds - 50, "--confirm", dry["confirm_token"], status=6)
    assert refused["error"]["code"] == "E_CONFLICT"
    assert "drawing.add-view" not in c.world.ops()
    result = c.cli(*VIEW, "--timeout", seconds, "--confirm", dry["confirm_token"])
    assert result["data"]["receipt"]["extensions"]["creo"]["execution_budget"] == policy
    assert set(META_REQUIRED_KEYS) <= set(result["meta"])
    assert set(result["meta"]) <= set(META_REQUIRED_KEYS + META_OPTIONAL_KEYS)
    assert c.world.ops().count("drawing.add-view") == 1
    c.cli(*VIEW, "--timeout", seconds, "--confirm", dry["confirm_token"], status=6)
    assert c.world.ops().count("drawing.add-view") == 1


def test_public_discovery_exposes_precise_allowlist(view_case):  # noqa: F811
    c = view_case
    full = c.cli("reference")["data"]
    declared = full["extensions"]["creo"]["drawing_execution_budget"]
    assert set(declared["eligible_commands"]) == budgets.COMMANDS
    actual = {row["path"] for row in full["commands"]}
    assert budgets.COMMANDS <= actual
    assert "drawing symbol add" not in budgets.COMMANDS
    assert declared["extended_max_seconds"] == 1200


def public_process(tmp_path, *args):
    """An actual public child process; only the locally listening peer can receive CAD ops."""
    prefix = json.loads(os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND", "null"))
    token = tmp_path / "synthetic-token"
    token.write_text("a" * 64, encoding="ascii")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CREO_", "PTC_", "PRO_"))}
    env.update(
        CREO_CLI_SERVICE_URL=transport.endpoint(),
        CREO_CLI_SERVICE_TOKEN_FILE=str(token),
        CREO_CLI_CONFIG_DIR=str(tmp_path / "isolated-records"),
        CREO_CLI_WORKSPACE=str(tmp_path),
        CREO_CLI_PERMISSION="read",
        PYTHONIOENCODING="utf-8",
    )
    run = subprocess.run(
        [*(prefix or [sys.executable, "-m", "creo_cli"]), *args, "--compact"],
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    body = json.loads(run.stdout)
    assert set(META_REQUIRED_KEYS) <= set(body["meta"])
    assert set(body["meta"]) <= set(META_REQUIRED_KEYS + META_OPTIONAL_KEYS)
    assert "a" * 64 not in run.stdout + run.stderr
    return run.returncode, body


@pytest.mark.parametrize("fault", ["disconnect", "E_BUSY", "E_UNAVAILABLE"])
def test_public_process_long_read_failure_retains_pending(tmp_path, fault):
    with peer(fault=fault) as events:
        code, result = public_process(
            tmp_path, "model", "show", "--model", "owned.drw", "--timeout", "1200"
        )
    assert code == 8, result
    assert result["error"]["code"] == "E_NATIVE_READ_PENDING"
    assert result["error"]["retryable"] is False
    assert "operation_id" not in result["error"]["details"]
    assert sum(e["path"] == "/op" for e in events) == 1


def test_public_process_old_service_stops_before_cad(tmp_path):
    with peer(capability=None) as events:
        code, result = public_process(
            tmp_path, "model", "show", "--model", "owned.drw", "--timeout", "1200"
        )
    assert code == 4, result
    assert result["error"]["code"] == "E_BACKEND_UNAVAILABLE"
    assert not any(e["path"] == "/op" for e in events)


def test_public_process_workflow_cannot_select_extended_profile(tmp_path):
    with peer() as events:
        code, result = public_process(
            tmp_path, "workflow", "run", "--request", "{}", "--timeout", "1200", "--dry-run"
        )
    assert code == 2, result
    assert result["error"]["code"] == "E_USAGE"
    assert not events
