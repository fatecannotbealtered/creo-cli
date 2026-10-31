"""A failed local sidecar must not hide a real controlled HTTP pending read.

No Creo, real credentials, real history, or directory ACL changes are used.
Permission failures affect only mkdir for this test's isolated sidecar directory.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import subprocess
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from creo_cli import operations, schemas
from creo_cli.core import CODES, Error, canonical, redact
from creo_cli.main import main
from tests.test_commands import ROOT
from tests.test_native_read_context import (
    PublicCase,
    arm,
    pending_context,
    safe_guidance,
    unknown_saved_operation,
)


class StorageCase(PublicCase):
    __test__ = False

    def cli(self, *args, status=0, **kwargs):
        command = os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND")
        if command:
            run = subprocess.run(
                [*json.loads(command), *map(str, args)],
                cwd=ROOT,
                env=(kwargs.get("env") or self.env) | {"PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                encoding="utf-8",
                timeout=45,
            )
            code, stdout, stderr = run.returncode, run.stdout, run.stderr
        else:
            out, err = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, kwargs.get("env") or self.env, clear=True),
                redirect_stdout(out),
                redirect_stderr(err),
            ):
                code = main(list(map(str, args)))
            stdout, stderr = out.getvalue(), err.getvalue()
        value = json.loads(stdout)
        public_args = list(map(str, args))
        if "--confirm" in public_args:
            public_args[public_args.index("--confirm") + 1] = "[REDACTED]"
        self.public_calls.append(
            {
                "args": public_args,
                "exit": code,
                "result": value,
                "stderr": stderr,
                "execution": "subprocess" if command else "inprocess_source",
            }
        )
        self.assertNotIn(self.world.token, stdout + stderr)
        self.assertEqual(
            set(value), {"ok", "schema_version", "meta", "data" if value["ok"] else "error"}
        )
        if not value["ok"]:
            self.assertEqual((code, value["error"]["retryable"]), CODES[value["error"]["code"]])
        self.assertEqual(code, status, value)
        return value


@pytest.fixture
def case(request):
    if (
        os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND")
        and getattr(request.node, "callspec", None)
        and request.node.callspec.params.get("storage") in ("permission", "error")
    ):
        pytest.skip("source-only mkdir injection cannot affect an independent product process")
    value = StorageCase()
    value.setUp()
    value.part()
    try:
        yield value
    finally:
        destination = os.environ.get("R27_PENDING_STORAGE_EVIDENCE")
        if destination:
            root = Path(destination)
            root.mkdir(parents=True, exist_ok=True)
            raw = redact(
                {
                    "kind": "controlled_http_public_cli_with_isolated_storage_fault",
                    "real_native_calls": 0,
                    "public_calls": value.public_calls,
                    "events": value.world.events,
                    "http_headers": value.http_headers,
                }
            )

            # The only confirmation tokens here are synthetic. Omit them too.
            def scrub(item):
                if isinstance(item, dict):
                    return {
                        key: "[REDACTED]" if key == "confirm_token" else scrub(val)
                        for key, val in item.items()
                    }
                return [scrub(val) for val in item] if isinstance(item, list) else item

            (root / (request.node.name + ".json")).write_bytes(canonical(scrub(raw)) + b"\n")
        value.doCleanups()


@contextmanager
def storage_fault(case, kind):
    root = Path(case.env["CREO_CLI_CONFIG_DIR"]) / "operation-queries"
    assert not root.exists()
    if kind == "file_exists":
        root.write_bytes(b"ordinary file occupying the isolated query-directory path\n")
        yield
        assert root.is_file()
        return
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == root:
            if kind == "permission":
                raise PermissionError(errno.EACCES, "controlled isolated mkdir denied", str(path))
            raise Error("E_IO", "controlled existing Error during sidecar preparation")
        return original(path, *args, **kwargs)

    with patch.object(Path, "mkdir", mkdir):
        yield
    assert not root.exists()


def inspection_args(case, mode):
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
            "controlled independent inspection remains unknown",
        )
        dry = case.cli(*args, "--dry-run")["data"]
        args += ("--confirm", dry["confirm_token"])
    with patch.dict(os.environ, case.env, clear=True):
        original_bytes = canonical(operations.get(ident))
    return ident, original, original_bytes, args


@pytest.mark.parametrize("mode", ("query", "resolve"))
@pytest.mark.parametrize("storage", ("permission", "file_exists", "error"))
@pytest.mark.parametrize("fault", ("busy_started", "reply_lost"))
def test_storage_failure_preserves_pending_inspection(case, mode, storage, fault):
    assert_pending_storage_failure(case, mode, storage, fault)


@pytest.mark.parametrize("mode", ("query", "resolve"))
def test_unavailable_started_file_exists_preserves_pending_inspection(case, mode):
    assert_pending_storage_failure(case, mode, "file_exists", "unavailable_started")


def assert_pending_storage_failure(case, mode, storage, fault):
    ident, original, original_bytes, args = inspection_args(case, mode)
    read = "model.management-state" if mode == "resolve" else "model.show"
    state = arm(case, fault, read=read, after="not-dispatched")
    state["after"] = True
    case.world.events.clear()
    with storage_fault(case, storage):
        error = case.cli(*args, status=8)["error"]
    assert error["code"] == "E_NATIVE_READ_PENDING"
    assert error["retryable"] is False
    details = error["details"]
    Draft202012Validator(schemas.NATIVE_READ_FAILURE_CONTEXT).validate(details)
    assert details["parent_operation_id"] == ident
    assert "operation_id" not in details
    assert "receipt" not in details
    assert "read_failure_evidence_id" not in details
    assert details["read_failure_evidence_retained"] is False
    assert details["record_error"] == "E_IO"
    assert details["storage_error"]["code"] == "E_IO"
    assert details["storage_error"]["retryable"] is False
    assert "not acknowledged" in details["read_failure_evidence_note"]
    assert "was not retained" not in details["read_failure_evidence_note"]
    storage_details = details["storage_error"]["details"]
    if storage != "error":
        assert (
            storage_details["exception_type"]
            == {
                "permission": "PermissionError",
                "file_exists": "FileExistsError",
            }[storage]
        )
        assert (
            storage_details["errno"]
            == {
                "permission": errno.EACCES,
                "file_exists": errno.EEXIST,
            }[storage]
        )
    context = pending_context(error, fault, read)
    assert details["operation"] == context["details"]["operation"]
    assert details["dispatch_state"] == context["details"]["dispatch_state"]
    assert details["cli_invocation_id"] == context["details"]["cli_invocation_id"]
    assert details["cause"] == context["details"]["cause"]
    safe_guidance({"next_action": details["next_action"], "fix": details["fix"]})
    # Only the one inspection getter reached the real HTTP peer. No later CAD
    # sampling or replay was performed by the failure-retention path.
    assert case.world.ops() == [read]
    before = list(case.world.events)
    saved = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert case.world.events == before
    assert saved["receipt"] == original["receipt"]
    assert saved["resolution"] == original["resolution"]
    with patch.dict(os.environ, case.env, clear=True):
        assert canonical(operations.get(ident)) == original_bytes


@pytest.mark.skipif(
    bool(os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND")),
    reason="source-only post-link injection cannot affect an independent product process",
)
@pytest.mark.parametrize("mode", ("query", "resolve"))
def test_post_link_storage_failure_preserves_pending_inspection_and_parent(case, mode):
    ident, original, original_bytes, args = inspection_args(case, mode)
    read = "model.management-state" if mode == "resolve" else "model.show"
    state = arm(case, "busy_started", read=read, after="not-dispatched")
    state["after"] = True
    root = Path(case.env["CREO_CLI_CONFIG_DIR"]) / "operation-queries"
    assert not root.exists()
    real_unlink = os.unlink
    committed_at_failure = []

    def fail_first_sidecar_cleanup(path, *unlink_args, **unlink_kwargs):
        candidate = Path(path)
        if candidate.parent == root and candidate.suffix == ".tmp" and not committed_at_failure:
            committed = list(root.glob("*.json"))
            assert len(committed) == 1
            committed_at_failure.append(
                (committed[0], hashlib.sha256(committed[0].read_bytes()).hexdigest())
            )
            raise PermissionError(errno.EACCES, "controlled post-link sidecar cleanup failure")
        return real_unlink(path, *unlink_args, **unlink_kwargs)

    case.world.events.clear()
    with patch("creo_cli.core.os.unlink", side_effect=fail_first_sidecar_cleanup):
        error = case.cli(*args, status=8)["error"]
    assert error["code"] == "E_NATIVE_READ_PENDING"
    assert error["retryable"] is False
    details = error["details"]
    Draft202012Validator(schemas.NATIVE_READ_FAILURE_CONTEXT).validate(details)
    assert details["parent_operation_id"] == ident
    assert "operation_id" not in details
    assert "receipt" not in details
    assert "read_failure_evidence_id" not in details
    assert details["read_failure_evidence_retained"] is False
    assert "not acknowledged" in details["read_failure_evidence_note"]
    assert "unknown storage state" in details["read_failure_evidence_note"]
    assert "was not retained" not in details["read_failure_evidence_note"]
    assert details["record_error"] == "E_IO"
    assert details["storage_error"]["code"] == "E_IO"
    assert details["storage_error"]["retryable"] is False
    assert details["storage_error"]["details"]["state_unknown"] is True
    context = pending_context(error, "busy_started", read)
    for key in ("operation", "dispatch_state", "cli_invocation_id", "cause"):
        assert details[key] == context["details"][key]
    safe_guidance({"next_action": details["next_action"], "fix": details["fix"]})
    assert case.world.ops() == [read]
    assert len(committed_at_failure) == 1
    evidence_file, committed_sha = committed_at_failure[0]
    assert list(root.glob("*.json")) == [evidence_file]
    assert hashlib.sha256(evidence_file.read_bytes()).hexdigest() == committed_sha
    assert evidence_file.stem.split("-")[1] == committed_sha
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert evidence["operation_id"] == ident
    assert evidence["observation"]["native_read_error"] == context
    assert evidence["proves_original_write_postconditions"] is False
    before = list(case.world.events)
    saved = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert case.world.events == before
    assert saved["receipt"] == original["receipt"]
    assert saved["resolution"] == original["resolution"]
    with patch.dict(os.environ, case.env, clear=True):
        assert canonical(operations.get(ident)) == original_bytes


@pytest.mark.parametrize("mode", ("query", "resolve"))
def test_ordinary_inspection_error_does_not_attempt_pending_storage(case, mode):
    ident, original, original_bytes, args = inspection_args(case, mode)
    read = "model.management-state" if mode == "resolve" else "model.show"
    case.world.fail = (read, {"code": "E_CREO", "message": "controlled ordinary getter error"})
    case.world.events.clear()
    no_retention = (
        nullcontext()
        if os.environ.get("CREO_CLI_TEST_PUBLIC_COMMAND")
        else patch.object(operations, "save_query", side_effect=AssertionError("must not retain"))
    )
    with no_retention:
        error = case.cli(*args, status=1)["error"]
    assert error["code"] == "E_NATIVE_FAILURE"
    assert "native_read_error" not in error["details"]
    assert "storage_error" not in error["details"]
    assert "read_failure_evidence_retained" not in error["details"]
    assert not (Path(case.env["CREO_CLI_CONFIG_DIR"]) / "operation-queries").exists()
    assert case.world.ops() == [read]
    with patch.dict(os.environ, case.env, clear=True):
        assert canonical(operations.get(ident)) == original_bytes
    assert original["receipt"]["outcome"]["change"] == "unknown"
