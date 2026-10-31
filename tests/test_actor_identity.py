"""Caller identity with isolated loopback/config; no Creo or real native dispatch."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from creo_cli import driver, engine, operations, safety, transport
from creo_cli.core import Error, canonical
from tests.test_commands import ROOT
from tests.test_features import Built
from tests.test_native_read_context import arm, pending_context, safe_guidance, workflow_request
from tests.test_pending_inspection_storage import (
    StorageCase,
    inspection_args,
    storage_fault,
)

IDENTITY_ENV = ("LOGNAME", "USER", "LNAME", "USERNAME")
DIMENSION = (
    "dimension",
    "set",
    "--model",
    "block",
    "--dimension",
    "d5",
    "--value",
    "9",
    "--units",
    "mm",
)


def missing_identity(env):
    return {key: value for key, value in env.items() if key not in IDENTITY_ENV}


def unavailable_actor():
    return patch("creo_cli.safety.getpass.getuser", side_effect=OSError("private caller data"))


@pytest.fixture
def case():
    value = Built()
    value.setUp()
    value.block()
    value.world.events.clear()
    try:
        yield value
    finally:
        value.doCleanups()


def test_normal_getpass_identity_and_scope_remain_byte_for_byte_compatible():
    with (
        patch("creo_cli.safety.getpass.getuser", return_value="existing-caller"),
        patch("creo_cli.safety.os.getlogin") as fallback,
    ):
        assert safety.actor() == "existing-caller"
        assert safety.scope("dimension set", "block.prt", {}, "revision")["account"] == (
            "existing-caller"
        )
    fallback.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="real Windows OS login acquisition")
def test_real_windows_missing_four_variables_uses_same_actual_login():
    expected = os.getlogin()
    with patch.dict(os.environ, missing_identity(os.environ), clear=True):
        with pytest.raises(ModuleNotFoundError, match="pwd"):
            getpass.getuser()
        assert safety.actor() == expected


def test_controlled_windows_fallback_uses_real_getlogin_result():
    with (
        patch("creo_cli.safety.os.name", "nt"),
        unavailable_actor(),
        patch("creo_cli.safety.os.getlogin", return_value="controlled-os-login") as fallback,
    ):
        assert safety.actor() == "controlled-os-login"
    fallback.assert_called_once_with()


@pytest.mark.parametrize("invalid", (None, "", "  \t\n", 42, [], {}))
def test_empty_or_nonstring_getpass_identity_is_never_replaced_with_default(invalid):
    with (
        patch("creo_cli.safety.getpass.getuser", return_value=invalid),
        patch("creo_cli.safety.os.getlogin") as fallback,
        pytest.raises(Error) as caught,
    ):
        safety.actor()
    assert caught.value.code == "E_CONFIG"
    fallback.assert_not_called()


@pytest.mark.parametrize("invalid", (None, "", " \t", 42))
def test_invalid_windows_fallback_fails_closed_without_original_exception(invalid):
    with (
        patch("creo_cli.safety.os.name", "nt"),
        unavailable_actor(),
        patch("creo_cli.safety.os.getlogin", return_value=invalid),
        pytest.raises(Error) as caught,
    ):
        safety.actor()
    assert caught.value.code == "E_CONFIG"
    assert "private caller data" not in str(caught.value.payload())


def test_unix_failure_does_not_fall_back_to_an_unrelated_terminal_user():
    with (
        patch("creo_cli.safety.os.name", "posix"),
        unavailable_actor(),
        patch("creo_cli.safety.os.getlogin") as fallback,
        pytest.raises(Error) as caught,
    ):
        safety.actor()
    assert caught.value.code == "E_CONFIG"
    fallback.assert_not_called()


@pytest.mark.parametrize("workflow", (False, True))
def test_identity_unavailable_refuses_before_any_cad_preview_or_token(case, workflow):
    args = ("workflow", "run", "--request", workflow_request(case)) if workflow else DIMENSION
    before = sorted((Path(case.env["CREO_CLI_CONFIG_DIR"]) / "operations").glob("*"))
    with (
        unavailable_actor(),
        patch("creo_cli.safety.os.getlogin", side_effect=OSError("private OS data")),
        patch("creo_cli.safety.issue") as issue,
        patch("creo_cli.operations.record_plan") as record,
    ):
        error = case.cli(*args, "--dry-run", status=4)["error"]
    assert error["code"] == "E_CONFIG"
    assert error["retryable"] is False
    assert error["details"]["dispatch_state"] == "not_started"
    assert "operation_id" not in error["details"]
    assert "receipt" not in error["details"]
    assert case.world.ops() == []
    assert "private" not in str(error)
    issue.assert_not_called()
    record.assert_not_called()
    assert sorted((Path(case.env["CREO_CLI_CONFIG_DIR"]) / "operations").glob("*")) == before


def public_process(case, args, env):
    command = json.loads(os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND", "null"))
    run = subprocess.run(
        [*(command or [sys.executable, str(ROOT / "cli.py")]), *args, "--compact"],
        cwd=case.root,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert case.world.token not in run.stdout + run.stderr
    return run.returncode, json.loads(run.stdout)


@pytest.mark.skipif(os.name != "nt", reason="real Windows fallback across processes")
@pytest.mark.parametrize("missing_at_preview", (False, True))
def test_cross_process_preview_confirm_bind_the_same_real_windows_user(case, missing_at_preview):
    missing = missing_identity(case.env)
    present = missing | {"USERNAME": os.getlogin()}
    first, second = (missing, present) if missing_at_preview else (present, missing)
    code, preview = public_process(case, [*DIMENSION, "--dry-run"], first)
    assert code == 0, preview
    assert preview["ok"] is True
    code, result = public_process(
        case, [*DIMENSION, "--confirm", preview["data"]["confirm_token"]], second
    )
    assert code == 0, result
    assert result["ok"] is True
    assert case.world.ops().count("dimension.set") == 1


def test_cross_process_different_actor_cannot_confirm_another_users_plan(case):
    first = missing_identity(case.env) | {
        "USERNAME": "controlled-actor-one",
        "USER": "controlled-actor-one",
    }
    second = missing_identity(case.env) | {
        "USERNAME": "controlled-actor-two",
        "USER": "controlled-actor-two",
    }
    code, preview = public_process(case, [*DIMENSION, "--dry-run"], first)
    assert code == 0, preview
    code, result = public_process(
        case, [*DIMENSION, "--confirm", preview["data"]["confirm_token"]], second
    )
    assert code == 6, result
    assert result["error"]["code"] == "E_CONFLICT"
    assert result["error"]["details"]["reason"] == "policy_changed"
    assert "dimension.set" not in case.world.ops()


@pytest.mark.parametrize("boundary", ("engine", "driver", "workflow"))
def test_same_client_pending_read_has_priority_over_actor_failure(case, boundary):
    with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
        case.world.fail = (
            "model.show",
            {"code": "E_BUSY", "message": "controlled", "started": True},
        )
        with pytest.raises(Error) as first:
            client.op("model.show", {"model": "block.prt"})
        assert first.value.code == "E_NATIVE_READ_PENDING"
        case.world.events.clear()
        with unavailable_actor() as actor, pytest.raises(Error) as caught:
            if boundary == "driver":
                driver.write(
                    "dimension set",
                    {"dry_run": True},
                    client,
                    SimpleNamespace(effects=["change"], op="dimension.set"),
                )
            elif boundary == "engine":
                with patch("creo_cli.engine.Client", return_value=client):
                    engine.write(
                        "dimension set",
                        {"dry_run": True},
                        lambda _: {},
                        lambda *_: pytest.fail("no CAD plan"),
                    )
            else:
                from creo_cli import workflow_tasks

                with patch("creo_cli.workflow_tasks.Client", return_value=client):
                    workflow_tasks.run(
                        {"dry_run": True},
                        {
                            "steps": [
                                {
                                    "id": "set",
                                    "command": "parameter set",
                                    "args": {
                                        "model": "block",
                                        "name": "DESCRIPTION",
                                        "type": "string",
                                        "value": "test",
                                    },
                                }
                            ]
                        },
                    )
        actor.assert_not_called()
        assert caught.value.code == first.value.code
        for key in ("cause_code", "cause", "operation", "cli_invocation_id", "next_action"):
            assert caught.value.details[key] == first.value.details[key]
        assert case.world.ops() == []


def test_readonly_and_local_history_do_not_require_actor(case):
    with unavailable_actor() as actor:
        assert case.cli("dimension", "list", "--model", "block")["ok"]
        assert case.cli("operation", "list")["ok"]
        assert case.cli("context")["ok"]
        with patch.dict(os.environ, case.env, clear=True), transport.Client() as client:
            assert client.health()["ok"]
    actor.assert_not_called()


@pytest.mark.parametrize("storage", (None, "error"))
def test_inspection_pending_precedes_identity_and_preserves_original_record(storage):
    case = StorageCase()
    case.setUp()
    case.part()
    try:
        ident, _, original, args = inspection_args(case, "resolve")
        state = arm(case, "busy_started", read="model.management-state", after="not-dispatched")
        state["after"] = True
        case.world.events.clear()
        with (
            unavailable_actor() as actor,
            storage_fault(case, storage) if storage else nullcontext(),
        ):
            error = case.cli(*args, status=8)["error"]
        actor.assert_not_called()
        context = pending_context(error, "busy_started", "model.management-state")
        assert error["details"]["parent_operation_id"] == ident
        for key in ("cause", "operation", "cli_invocation_id", "dispatch_state"):
            assert error["details"][key] == context["details"][key]
        safe_guidance(error["details"])
        assert "receipt" not in error["details"]
        assert case.world.ops() == ["model.management-state"]
        if storage:
            assert "read_failure_evidence_id" not in error["details"]
            assert error["details"]["read_failure_evidence_retained"] is False
        with patch.dict(os.environ, case.env, clear=True):
            assert canonical(operations.get(ident)) == original
    finally:
        case.doCleanups()


def test_inspection_identity_failure_refuses_registration_without_rewriting_receipt():
    case = StorageCase()
    case.setUp()
    case.part()
    try:
        ident, _, original, args = inspection_args(case, "resolve")
        case.world.events.clear()
        with (
            unavailable_actor(),
            patch("creo_cli.safety.os.getlogin", side_effect=OSError("private login data")),
            patch("creo_cli.safety.issue") as issue,
            patch("creo_cli.safety.consume") as consume,
        ):
            error = case.cli(*args, status=4)["error"]
        assert error["code"] == "E_CONFIG"
        assert "private" not in str(error)
        assert "operation_id" not in error["details"]
        assert "receipt" not in error["details"]
        assert "read_failure_evidence_id" not in error["details"]
        assert case.world.ops()[0] == "model.management-state"
        assert not any(op.endswith((".set", ".save", ".regenerate")) for op in case.world.ops())
        issue.assert_not_called()
        consume.assert_not_called()
        with patch.dict(os.environ, case.env, clear=True):
            assert canonical(operations.get(ident)) == original
    finally:
        case.doCleanups()


def test_registration_reuses_the_confirmed_scope_actor():
    case = StorageCase()
    case.setUp()
    case.part()
    try:
        ident, _, _, args = inspection_args(case, "resolve")
        with patch.dict(os.environ, case.env, clear=True):
            run = operations.get(ident)
            expected = run["driver_binding"]["account"]
        # Only scope acquisition is needed: registration must not resolve a second
        # identity after consuming the token or writing an inspection sidecar.
        with patch("creo_cli.safety.actor", return_value=expected) as actor:
            assert case.cli(*args)["ok"]
        actor.assert_called_once_with()
        with patch.dict(os.environ, case.env, clear=True):
            saved = operations.get(ident)
        assert saved["driver_resolution"]["recorded_by"] == expected
    finally:
        case.doCleanups()
