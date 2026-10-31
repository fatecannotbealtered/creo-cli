"""Real observer over controlled kernel calls; no CAD or actual PID is queried."""

import copy

import pytest

from creo_cli import owned_exit as ex
from creo_cli.core import Error
from tests.test_owned_process_handle import kernel as _kernel_fixture
from tests.test_owned_session_exit import OP
from tests.test_owned_session_exit import world as _world_fixture

world, kernel = _world_fixture, _kernel_fixture
REAL_HANDLE = ex.ProcessHandle


@pytest.fixture
def shutdown(world, kernel, monkeypatch):
    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds
            if self.now >= signal_at[0]:
                kernel.alive = False

    clock, signal_at, dispatch_calls = Clock(), [100.04], []
    kernel.birth = 12345
    kernel.image = world["rows"][0]["actual_image"]
    handles = []

    class Handle(REAL_HANDLE):
        def __init__(self, *args):
            super().__init__(*args)
            self.close_count = 0
            handles.append(self)

        def close(self):
            if hasattr(self, "close_count"):
                self.close_count += 1
            super().close()

    monkeypatch.setattr(ex, "ProcessHandle", Handle)
    world["client"].mode = "stop"
    original = world["client"].op

    def op(name, request, **kwargs):
        value = original(name, request, **kwargs)
        if name == "session.exit":
            dispatch_calls.append(len(kernel.calls))
            kernel.image_error, kernel.image_error_code = True, 5
        return value

    monkeypatch.setattr(world["client"], "op", op)
    plan = ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    run = {"operation_id": OP}
    plan.prepare_dispatch(run)
    monkeypatch.setattr(ex.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ex.time, "sleep", clock.sleep)
    monkeypatch.setattr(ex.timing, "deadline", lambda _: clock.now + 0.12)
    return world | {
        "kernel": kernel,
        "plan": plan,
        "run": run,
        "clock": clock,
        "signal_at": signal_at,
        "dispatch_calls": dispatch_calls,
        "handles": handles,
    }


def test_access_denied_image_before_signal_still_waits_for_joint_exit_evidence(shutdown):
    state = shutdown
    data = state["plan"].apply(state["client"], state["run"])
    _, verification = state["plan"].verify(state["client"], data)
    assert all(check["passed"] for check in verification["checks"])
    assert data["exit_observation"]["process"]["exit_code"] == 0
    assert data["exit_observation"]["process"]["creation_filetime"] == "12345"
    assert data["exit_observation"]["process"]["image_source"].startswith("cached image verified")
    assert len(state["dispatch_calls"]) == 1
    assert not any(
        call[0] == "image" for call in state["kernel"].calls[state["dispatch_calls"][0] :]
    )
    assert state["handles"][-1].close_count == 1


def test_pre_dispatch_image_failure_refuses_without_native_rpc(shutdown):
    state = shutdown
    state["kernel"].image_error, state["kernel"].image_error_code = True, 5
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["request_sent"] is False
    assert state["dispatch_calls"] == []
    detail = caught.value.details["owned_exit_diagnostics"]["last_process_read_error"]
    assert detail["details"]["windows_api"] == "QueryFullProcessImageNameW"
    assert detail["details"]["win32_error"] == 5
    assert state["handles"][-1].close_count == 1


def test_unfinished_transition_keeps_original_deadline_and_unknown(shutdown):
    state = shutdown
    state["signal_at"][0] = 100.2
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_OUTCOME_UNKNOWN"
    assert "deadline elapsed" in caught.value.message
    process = caught.value.details["owned_exit_diagnostics"]["latest_process_observation"]["state"]
    assert process["alive"] is True and process["exit_code"] is None
    assert process["image_source"].startswith("cached image verified")
    assert len(state["dispatch_calls"]) == 1
    assert state["handles"][-1].close_count == 1


def test_nonzero_terminal_code_is_raw_unknown_with_no_image_read_failure(shutdown):
    state = shutdown
    state["kernel"].code = 7
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_OUTCOME_UNKNOWN"
    detail = caught.value.details["owned_exit_diagnostics"]
    assert detail["latest_process_observation"]["state"]["exit_code"] == 7
    assert detail["process_read_error_count"] == 0
    assert state["handles"][-1].close_count == 1


def test_intent_and_same_plan_remain_bound_before_termination_phase(shutdown):
    state = shutdown
    before = copy.deepcopy(state["plan"].before)
    state["plan"].request["expected_pid"] = 999
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.details["dispatch_state"] == "not_started"
    assert state["dispatch_calls"] == []
    assert state["plan"].before == before


def test_identity_validation_crossing_original_deadline_never_dispatches(shutdown, monkeypatch):
    state = shutdown
    handle = state["handles"][-1]
    original = handle.begin_termination

    def slow_validation():
        original()
        state["clock"].now += 0.2

    monkeypatch.setattr(handle, "begin_termination", slow_validation)
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_TIMEOUT"
    assert caught.value.details["dispatch_state"] == "not_started"
    assert state["dispatch_calls"] == []
    assert handle.close_count == 1


def test_pre_dispatch_local_os_error_is_not_reported_as_a_sent_request(shutdown, monkeypatch):
    state = shutdown

    def unavailable():
        raise PermissionError(5, "controlled local OS identity read failure")

    monkeypatch.setattr(state["handles"][-1], "begin_termination", unavailable)
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["request_sent"] is False
    assert caught.value.details["dispatch_state"] == "not_started"
    assert state["dispatch_calls"] == []
    assert state["handles"][-1].close_count == 1


def test_pre_dispatch_keyboard_interrupt_retains_interrupted_cause_without_sent_request(
    shutdown,
    monkeypatch,
):
    state = shutdown
    before = len(state["kernel"].calls)

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(state["handles"][-1], "begin_termination", interrupted)
    with pytest.raises(Error) as caught:
        state["plan"].apply(state["client"], state["run"])
    assert caught.value.code == "E_INTERRUPTED"
    assert caught.value.details["cause_code"] == "E_INTERRUPTED"
    assert caught.value.details["request_sent"] is False
    assert caught.value.details["dispatch_state"] == "not_started"
    assert caught.value.details["automatic_retry"] is False
    assert state["dispatch_calls"] == []
    assert [name for name, _ in state["client"].calls] == ["session.exit-state"]
    detail = caught.value.details["owned_exit_diagnostics"]
    assert detail["request_acknowledgement"] is None
    assert detail["last_process_read_error"]["error_type"] == "KeyboardInterrupt"
    assert state["kernel"].calls[before:] == [("close", 81)]
    assert state["handles"][-1].close_count == 1
