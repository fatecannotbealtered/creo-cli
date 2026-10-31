"""Controlled exit polling/retention; no OS process or CAD is observed or terminated."""

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from creo_cli import operations
from creo_cli import owned_exit as ex
from creo_cli.core import Error
from tests.test_owned_session_exit import OP
from tests.test_owned_session_exit import world as _world_fixture

world = _world_fixture
ALL_RUNS = operations.selected_runs


@pytest.fixture
def polling(world, monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    clock = Clock()
    original = world["handle"]
    handles, events = [], []
    run = {"operation_id": OP}

    class Handle(original):
        signal_at = float("inf")
        observation_seconds = 0.0

        def __init__(self, *args):
            super().__init__(*args)
            self.close_count = 0
            handles.append(self)

        def observe(self):
            assert self.handle is not None, "no sample after closing the original handle"
            clock.now += self.observation_seconds
            self.alive = clock.now < self.signal_at
            events.append(("process", clock.now))
            return super().observe()

        def close(self):
            events.append(("close", copy.deepcopy(run.get("owned_exit_diagnostics"))))
            self.close_count += 1
            super().close()

    monkeypatch.setattr(ex, "ProcessHandle", Handle)
    world["client"].mode = "stop"
    p = ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    p.prepare_dispatch(run)
    monkeypatch.setattr(ex.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ex.time, "sleep", clock.sleep)
    monkeypatch.setattr(ex.timing, "deadline", lambda _: clock.now + 0.12)
    return world | {
        "plan": p,
        "clock": clock,
        "handles": handles,
        "events": events,
        "run": run,
        "poll_handle": Handle,
    }


def failed_apply(state):
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_OUTCOME_UNKNOWN"
    assert [name for name, _ in state["client"].calls] == ["session.exit-state", "session.exit"]
    assert state["handles"][-1].close_count == 1
    return caught.value


def test_alive_through_deadline_retains_same_handle_observation_before_close(polling):
    failure = failed_apply(polling)
    detail = failure.details["owned_exit_diagnostics"]
    process = detail["latest_process_observation"]
    complete = detail["latest_complete_observation"]
    assert process["state"]["alive"] is True
    assert process["state"]["signaled"] is False
    assert process["state"]["exit_code"] is None
    assert complete["state"]["entered"]["data"]["status"] == "native_entered"
    assert complete["state"]["stop"]["data"]["status"] == "service_stop_after_owned_native_entry"
    assert process["sampled_at_utc"].endswith("Z") and process["age_ms"] >= 0
    assert complete["age_ms"] <= process["age_ms"]
    assert detail["request_acknowledgement"] == {"status": "request_scheduled", "operation_id": OP}
    assert detail == polling["run"]["owned_exit_diagnostics"]
    assert polling["events"][-1] == ("close", detail)
    assert not polling["plan"]._verified_observation_guard(polling["plan"], polling["client"])
    before_reads = len(polling["events"])
    assert polling["plan"].observe(polling["client"]) == complete["state"]
    assert len(polling["events"]) == before_reads


def test_delayed_signal_zero_within_original_deadline_is_qualified(polling):
    polling["poll_handle"].signal_at = 100.08
    result = polling["plan"].apply(polling["client"], polling["run"])
    _, verification = polling["plan"].verify(polling["client"], result)
    assert all(row["passed"] for row in verification["checks"])
    assert result["exit_observation"]["process"]["exit_code"] == 0
    assert polling["handles"][-1].close_count == 1


def test_signal_after_deadline_never_qualifies_or_starts_another_poll(polling):
    polling["poll_handle"].signal_at = 100.14
    failure = failed_apply(polling)
    detail = failure.details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["alive"] is True
    assert all(at < 100.12 for kind, at in polling["events"] if kind == "process")


def test_observation_finishing_after_deadline_is_retained_but_not_verified(polling):
    polling["poll_handle"].signal_at = 100.14
    polling["poll_handle"].observation_seconds = 0.15
    failure = failed_apply(polling)
    detail = failure.details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["exit_code"] == 0
    assert detail["latest_complete_observation"]["within_deadline"] is False
    assert not polling["plan"]._verified_observation_guard(polling["plan"], polling["client"])


@pytest.mark.parametrize("kind", ["permission", "partial_json", "oversized"])
def test_witness_read_failure_keeps_latest_process_and_error(polling, monkeypatch, kind):
    original = ex._witness

    def witness(runtime, op, name):
        if name != "stop":
            return original(runtime, op, name)
        if kind == "permission":
            raise PermissionError(13, "controlled unavailable witness")
        if kind == "partial_json":
            raise json.JSONDecodeError("controlled incomplete witness", "{", 1)
        raise Error("E_VERIFY_INCOMPLETE", "owned-exit witness exceeds its bound")

    monkeypatch.setattr(ex, "_witness", witness)
    failure = failed_apply(polling)
    detail = failure.details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["alive"] is True
    assert detail["latest_complete_observation"] is None
    assert detail["witness_read_error_count"] >= 1
    assert detail["last_witness_read_error"]["witness"] == "stop"
    assert detail["last_witness_read_error"]["error_type"] in {
        "PermissionError",
        "JSONDecodeError",
        "Error",
    }
    assert detail["last_witness_read_error"]["sampled_at_utc"].endswith("Z")
    assert polling["events"][-1] == ("close", detail)


def test_local_public_operation_show_retains_unknown_diagnostics(polling, monkeypatch, tmp_path):
    from creo_cli import driver, registry
    from creo_cli.commands import operation

    assert any(command.path == "operation show" for command in registry.COMMANDS)
    config = tmp_path / "isolated-test-history"
    config.mkdir()
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(config))
    monkeypatch.setattr(operations, "selected_runs", ALL_RUNS)
    public_plan = {
        "operation_id": OP,
        "plan_id": "b" * 32,
        "capability_id": "session-exit",
        "target": copy.deepcopy(polling["plan"].preview["owned_target"]),
        "changes": [
            {"action": "session.exit", "resource": "session", "summary": "controlled exit"}
        ],
        "effects": ["session"],
        "authorization_scope_id": "controlled-scope",
        "base_snapshot": driver.snapshot(polling["plan"].binding),
        "level": "plan",
        "outputs": [],
        "unknowns": [],
        "constraints": [],
        "trial_snapshot": None,
        "can_apply": True,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    stored = operations.record_plan(
        "session exit", "session", {}, polling["client"].url, public_plan, {}
    )
    stored.update(status="running", started_at=operations.now())
    operations.update(stored)
    polling["run"].update(stored)
    failure = failed_apply(polling)
    # Only local storage after apply: no settling SDK, OS or HTTP read is permitted.
    run = operations.get(OP)
    assert run["owned_exit_diagnostics"] == failure.details["owned_exit_diagnostics"]
    assert run["status"] == "running" and run["driver_stage"] == "finalizing"
    shown = operation.show({"id": OP})["operation_status"]
    assert shown["status"] == "unknown"
    assert shown["extensions"]["creo"]["owned_exit_diagnostics"] == run["owned_exit_diagnostics"]
    assert shown["receipt"]["snapshot_after"] is None
    assert shown["receipt"]["outcome"]["change"] == "unknown"
    assert [name for name, _ in polling["client"].calls] == ["session.exit-state", "session.exit"]


def test_latest_process_and_older_complete_sample_are_separate(polling, monkeypatch):
    original = ex._witness
    polling["poll_handle"].signal_at = 100.04

    def witness(runtime, op, name):
        if name == "stop" and polling["clock"].now >= 100.04:
            raise PermissionError(13, "controlled later witness read failure")
        return original(runtime, op, name)

    monkeypatch.setattr(ex, "_witness", witness)
    detail = failed_apply(polling).details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["exit_code"] == 0
    assert detail["latest_complete_observation"]["state"]["process"]["alive"] is True
    assert (
        detail["latest_complete_observation"]["age_ms"]
        > detail["latest_process_observation"]["age_ms"]
    )
    assert not polling["plan"]._verified_observation_guard(polling["plan"], polling["client"])


def test_held_process_read_error_retains_previous_sample_without_reopening(polling, monkeypatch):
    original = polling["poll_handle"].observe

    def unreadable(handle):
        if polling["clock"].now >= 100.04:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "controlled held-process read failure ct_test.secret",
                {
                    "windows_api": "GetProcessTimes",
                    "win32_error": 6,
                    "process_observation_stage": "creation_and_exit_times",
                    "token": "private",
                },
            )
        return original(handle)

    monkeypatch.setattr(polling["poll_handle"], "observe", unreadable)
    detail = failed_apply(polling).details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["alive"] is True
    assert detail["process_read_error_count"] == 1
    assert detail["last_process_read_error"]["cause_code"] == "E_VERIFY_INCOMPLETE"
    error = detail["last_process_read_error"]
    assert error["message"] == "controlled held-process read failure [REDACTED]"
    assert error["details"] == {
        "windows_api": "GetProcessTimes",
        "win32_error": 6,
        "process_observation_stage": "creation_and_exit_times",
        "token": "[REDACTED]",
    }
    assert "ct_test.secret" not in json.dumps(polling["run"])
    assert len(polling["handles"]) == 2  # original preview and original dispatch handles only


def test_known_nonzero_process_exit_remains_raw_unknown_not_unreadable(polling, monkeypatch):
    original = polling["poll_handle"].observe
    polling["poll_handle"].signal_at = 100.0

    def nonzero(handle):
        return original(handle) | {"exit_code": 7}

    monkeypatch.setattr(polling["poll_handle"], "observe", nonzero)
    failure = failed_apply(polling)
    assert failure.message == "owned native exit lacks complete normal-termination evidence"
    detail = failure.details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["exit_code"] == 7
    assert detail["latest_complete_observation"]["state"]["process"]["exit_code"] == 7
    assert detail["process_read_error_count"] == 0


def test_diagnostic_checkpoint_failure_keeps_unknown_and_cached_evidence(polling, monkeypatch):
    polling["run"]["status"] = "running"

    def fail_record(_run):
        raise Error("E_IO", "controlled operation storage failure")

    monkeypatch.setattr(operations, "checkpoint_domain", fail_record)
    failure = failed_apply(polling)
    assert failure.details["exit_diagnostics_checkpoint"] == "unavailable"
    assert failure.details["exit_diagnostics_record_error"] == "E_IO"
    assert failure.details["owned_exit_diagnostics"] == polling["run"]["owned_exit_diagnostics"]


def test_interruption_retains_completed_sample_before_closing_original_handle(polling, monkeypatch):
    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(ex.time, "sleep", interrupt)
    failure = failed_apply(polling)
    assert failure.details["cause_code"] == "E_INTERRUPTED"
    detail = failure.details["owned_exit_diagnostics"]
    assert detail["latest_complete_observation"]["state"]["process"]["alive"] is True
    assert polling["events"][-1] == ("close", detail)


@pytest.mark.parametrize("acknowledgement", [None, "unexpected scalar", {"status": "other"}])
def test_malformed_acknowledgement_retains_unknown_without_new_getter(
    polling, monkeypatch, acknowledgement
):
    original = polling["client"].op

    def op(*args, **kwargs):
        original(*args, **kwargs)
        return acknowledgement

    monkeypatch.setattr(polling["client"], "op", op)
    before = len(polling["events"])
    detail = failed_apply(polling).details["owned_exit_diagnostics"]
    assert detail["request_acknowledgement"] == acknowledgement
    assert detail["latest_process_observation"] is None
    assert detail["latest_complete_observation"] is None
    assert [event[0] for event in polling["events"][before:]] == ["close"]


def test_nonobject_witness_retains_process_sample_and_read_error(polling, monkeypatch):
    original = polling["client"].op

    def op(*args, **kwargs):
        value = original(*args, **kwargs)
        (polling["runtime"] / f"owned-exit-{OP}.stop.json").write_text("[]", encoding="utf-8")
        return value

    monkeypatch.setattr(polling["client"], "op", op)
    detail = failed_apply(polling).details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["alive"] is True
    assert detail["last_witness_read_error"]["witness"] == "stop"
    assert detail["last_witness_read_error"]["error_type"] == "ValueError"


@pytest.mark.parametrize("partial", [b"", b'{"status":'])
def test_real_partial_witness_completes_inside_original_deadline(polling, monkeypatch, partial):
    original = polling["client"].op
    stop = polling["runtime"] / f"owned-exit-{OP}.stop.json"
    complete = None
    sleeps = []
    polling["poll_handle"].signal_at = 100.04

    def op(*args, **kwargs):
        nonlocal complete
        value = original(*args, **kwargs)
        complete = stop.read_bytes()
        stop.write_bytes(partial)
        return value

    def sleep(seconds):
        sleeps.append(seconds)
        polling["clock"].sleep(seconds)
        stop.write_bytes(complete)

    monkeypatch.setattr(polling["client"], "op", op)
    monkeypatch.setattr(ex.time, "sleep", sleep)
    result = polling["plan"].apply(polling["client"], polling["run"])
    _, verification = polling["plan"].verify(polling["client"], result)
    assert all(row["passed"] for row in verification["checks"])
    assert sleeps == [0.05]
    assert result["exit_observation"]["process"]["exit_code"] == 0
    assert result["exit_observation"]["stop"]["data"]["status"] == (
        "service_stop_after_owned_native_entry"
    )
    assert polling["handles"][-1].close_count == 1
    assert [name for name, _ in polling["client"].calls] == ["session.exit-state", "session.exit"]


@pytest.mark.parametrize("invalid", [b'{"status":', b'{"x":1,"x":2}', b'{"x":NaN}'])
def test_real_invalid_witness_never_qualifies_and_keeps_read_error(polling, monkeypatch, invalid):
    original = polling["client"].op
    stop = polling["runtime"] / f"owned-exit-{OP}.stop.json"
    polling["poll_handle"].signal_at = 100.0

    def op(*args, **kwargs):
        value = original(*args, **kwargs)
        stop.write_bytes(invalid)
        return value

    monkeypatch.setattr(polling["client"], "op", op)
    detail = failed_apply(polling).details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["exit_code"] == 0
    assert detail["latest_complete_observation"] is None
    assert detail["witness_read_error_count"] >= 1
    assert detail["last_witness_read_error"]["witness"] == "stop"
    if invalid == b'{"status":':
        assert detail["witness_read_error_count"] > 1
        assert detail["last_witness_read_error"]["error_type"] == "JSONDecodeError"
    else:
        assert detail["last_witness_read_error"]["cause_code"] == "E_VALIDATION"
    assert not polling["plan"]._verified_observation_guard(polling["plan"], polling["client"])


@pytest.mark.parametrize(
    "storage_error", [sqlite3.OperationalError("locked"), PermissionError(13, "denied")]
)
def test_raw_checkpoint_storage_error_preserves_original_unknown(
    polling, monkeypatch, storage_error
):
    polling["run"]["status"] = "running"

    def checkpoint(_run):
        raise storage_error

    monkeypatch.setattr(operations, "checkpoint_domain", checkpoint)
    failure = failed_apply(polling)
    assert failure.message == "owned exit deadline elapsed; do not retry or query CAD"
    assert failure.details["exit_diagnostics_checkpoint"] == "unavailable"
    assert failure.details["exit_diagnostics_record_error"] == "E_IO"
    assert failure.details["exit_diagnostics_record_error_type"] == type(storage_error).__name__
    assert failure.details["owned_exit_diagnostics"] == polling["run"]["owned_exit_diagnostics"]
    assert polling["events"][-1] == ("close", polling["run"]["owned_exit_diagnostics"])


@pytest.mark.parametrize("failure_kind", ["schema_lock", "permission"])
def test_persistent_db_failure_keeps_unknown_through_settlement(
    polling, monkeypatch, tmp_path, failure_kind
):
    config = tmp_path / "persistent-storage-failure"
    config.mkdir()
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(config))
    database = config / operations.DATABASE
    connections = []
    blocked = False
    lock = None

    class Connection(sqlite3.Connection):
        close_count = 0

        def close(self):
            self.close_count += 1
            super().close()

    def connect(_name):
        if blocked and failure_kind == "permission":
            raise PermissionError(13, "controlled history permission failure")
        result = sqlite3.connect(database, isolation_level=None, timeout=0, factory=Connection)
        connections.append(result)
        return result

    monkeypatch.setattr(operations.safety, "database", connect)
    monkeypatch.setattr(operations.uuid, "uuid4", lambda: SimpleNamespace(hex=OP))
    run = operations.begin(
        "session exit", "session", polling["plan"].request, polling["client"].url
    )
    polling["run"].update(run)
    original = polling["client"].op

    def op(*args, **kwargs):
        nonlocal blocked, lock
        reply = original(*args, **kwargs)
        if failure_kind == "schema_lock":
            lock = sqlite3.connect(database, isolation_level=None, timeout=0)
            lock.execute("BEGIN EXCLUSIVE")
        blocked = True
        return reply

    monkeypatch.setattr(polling["client"], "op", op)
    try:
        failure = failed_apply(polling)
        settled = ex.engine.settle(polling["run"], failure, polling["client"], polling["plan"])
        assert settled is failure
        assert settled.code == "E_OUTCOME_UNKNOWN"
        assert settled.message == "owned exit deadline elapsed; do not retry or query CAD"
        assert settled.details["exit_diagnostics_checkpoint"] == "unavailable"
        assert settled.details["exit_diagnostics_record_error"] == "E_IO"
        assert settled.details["receipt_status"] == "unknown"
        assert polling["run"]["status"] == "unknown"
        assert settled.details["owned_exit_diagnostics"] == polling["run"]["owned_exit_diagnostics"]
        assert [name for name, _ in polling["client"].calls] == [
            "session.exit-state",
            "session.exit",
        ]
        assert all(connection.close_count == 1 for connection in connections)
    finally:
        if lock is not None:
            lock.rollback()
            lock.close()
    # No automatic re-storage after the lock/permission is released. The old
    # running record remains unresolved; only the error envelope has the sample.
    with sqlite3.connect(database) as readable:
        status, body = readable.execute(
            "SELECT status,body FROM operations WHERE id=?", (OP,)
        ).fetchone()
    assert status == "running"
    assert "owned_exit_diagnostics" not in json.loads(body)
