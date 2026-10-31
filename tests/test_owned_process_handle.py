"""Held-handle observer controls and only newly spawned, naturally exiting test children."""

import ctypes
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from creo_cli import owned_exit as ex
from creo_cli.core import Error


class Call:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@pytest.fixture
def kernel(monkeypatch):
    class Kernel:
        alive, birth, image, code = True, 321, "C:/test-owned/python.exe", 0
        image_error = False
        image_error_code = 31
        exit_during_image = False
        exit_after_image = False
        wait_failure = False
        times_failure = False
        code_failure = False
        open_failure = False
        last_error = 0

        def __init__(self):
            self.calls = []
            for name in (
                "OpenProcess",
                "CloseHandle",
                "GetProcessTimes",
                "QueryFullProcessImageNameW",
                "WaitForSingleObject",
                "GetExitCodeProcess",
                "GetTickCount64",
            ):
                setattr(self, name, Call(getattr(self, "_" + name)))

        def _OpenProcess(self, rights, inherit, pid):
            self.calls.append(("open", rights, inherit, pid))
            self.last_error = 5 if self.open_failure else 0
            return 0 if self.open_failure else 81

        def _CloseHandle(self, handle):
            self.calls.append(("close", handle))
            return 1

        def _GetProcessTimes(self, handle, created, exited, _kernel, _user):
            self.calls.append(("times", handle, self.alive))
            if self.times_failure:
                self.last_error = 6
                return 0
            created._obj.dwLowDateTime = self.birth
            created._obj.dwHighDateTime = 0
            exited._obj.dwLowDateTime = 0 if self.alive else 654
            exited._obj.dwHighDateTime = 0
            return 1

        def _QueryFullProcessImageNameW(self, handle, _flags, name, size):
            self.calls.append(("image", handle))
            if self.exit_during_image:
                self.alive = False
                self.last_error = 31
                return 0
            if self.image_error or not self.alive:
                self.last_error = self.image_error_code
                return 0
            name.value = self.image
            size._obj.value = len(self.image)
            if self.exit_after_image:
                self.alive = False
            return 1

        def _WaitForSingleObject(self, handle, timeout):
            self.calls.append(("wait", handle, timeout))
            if self.wait_failure:
                self.last_error = 6
                return 0xFFFFFFFF
            return 258 if self.alive else 0

        def _GetExitCodeProcess(self, handle, value):
            self.calls.append(("code", handle))
            if self.code_failure:
                self.last_error = 5
                return 0
            value._obj.value = self.code
            return 1

        def _GetTickCount64(self):
            return 42

    k = Kernel()
    monkeypatch.setattr(ex, "os", SimpleNamespace(**(vars(os) | {"name": "nt"})))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: k, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: k.last_error, raising=False)
    return k


def opened(kernel):
    return ex.ProcessHandle(123, str(kernel.birth), kernel.image)


def test_original_minimal_read_rights_and_verified_live_identity(kernel):
    handle = opened(kernel)
    observed = handle.observe()
    assert observed["alive"] is True and observed["exit_filetime"] is None
    assert observed["image_source"] == "QueryFullProcessImageNameW on same held handle while alive"
    assert observed["image_verified_at_utc"].endswith("Z")
    assert kernel.calls[0] == ("open", 0x100000 | 0x1000, False, 123)
    handle.close()
    handle.close()
    assert [row for row in kernel.calls if row[0] == "close"] == [("close", 81)]


@pytest.mark.parametrize("code", [0, 7, 259, 0xC0000005])
def test_terminal_uses_same_handle_verified_image_and_raw_exit_code(kernel, code):
    handle = opened(kernel)
    kernel.alive, kernel.code = False, code
    before = len(kernel.calls)
    observed = handle.observe()
    assert observed["signaled"] is True and observed["alive"] is False
    assert observed["exit_code"] == code and observed["exit_filetime"] == "654"
    assert observed["creation_filetime"] == "321"
    assert observed["image_source"] == "cached image verified on same held handle while alive"
    assert [row[0] for row in kernel.calls[before:]] == ["wait", "times", "code"]
    assert len([row for row in kernel.calls if row[0] == "open"]) == 1
    handle.close()


@pytest.mark.parametrize("during_query", [True, False])
def test_alive_to_terminal_race_rereads_terminal_times(kernel, during_query):
    handle = opened(kernel)
    kernel.exit_during_image = during_query
    kernel.exit_after_image = not during_query
    before = len(kernel.calls)
    observed = handle.observe()
    assert observed["exit_code"] == 0 and observed["exit_filetime"] == "654"
    rows = kernel.calls[before:]
    assert [row for row in rows if row[0] == "times"] == [("times", 81, True), ("times", 81, False)]
    assert observed["image_source"].startswith("cached image verified")
    handle.close()


def test_alive_image_failure_is_not_accepted_from_cached_identity(kernel):
    handle = opened(kernel)
    kernel.image_error = True
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["windows_api"] == "QueryFullProcessImageNameW"
    assert caught.value.details["win32_error"] == 31
    assert not any(row[0] == "code" for row in kernel.calls)
    handle.close()


def test_explicit_termination_phase_does_not_query_tearing_down_image(kernel):
    handle = opened(kernel)
    handle.begin_termination()
    before = len(kernel.calls)
    kernel.image_error, kernel.image_error_code = True, 5
    pending = handle.observe()
    assert pending["alive"] is True and pending["exit_code"] is None
    assert pending["image_source"] == "cached image verified on same held handle while alive"
    assert pending["observation_phase"] == "termination_dispatch"
    kernel.alive = False
    terminal = handle.observe()
    assert terminal["signaled"] is True and terminal["exit_code"] == 0
    assert not any(row[0] == "image" for row in kernel.calls[before:])
    handle.close()


def test_begin_termination_rechecks_live_image_before_enabling_cached_mode(kernel):
    handle = opened(kernel)
    before = len(kernel.calls)
    kernel.image_error, kernel.image_error_code = True, 5
    with pytest.raises(Error) as caught:
        handle.begin_termination()
    assert caught.value.details["windows_api"] == "QueryFullProcessImageNameW"
    assert caught.value.details["win32_error"] == 5
    assert any(row[0] == "image" for row in kernel.calls[before:])
    assert handle._termination_started is False
    handle.close()


@pytest.mark.parametrize("terminal", [False, True])
def test_termination_phase_does_not_replace_missing_cache_with_expected_path(kernel, terminal):
    handle = opened(kernel)
    handle.begin_termination()
    handle._verified_identity = None
    kernel.alive = not terminal
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == "E_CONFLICT"
    handle.close()


@pytest.mark.parametrize("failure", ["wait_failure", "times_failure", "changed_birth"])
def test_pending_termination_still_requires_fresh_wait_and_creation_identity(kernel, failure):
    handle = opened(kernel)
    handle.begin_termination()
    if failure == "changed_birth":
        kernel.birth = 999
    else:
        setattr(kernel, failure, True)
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == (
        "E_CONFLICT" if failure == "changed_birth" else "E_VERIFY_INCOMPLETE"
    )
    handle.close()


@pytest.mark.parametrize(
    "field,value", [("image", "C:/stale/other.exe"), ("creation_filetime", "999")]
)
def test_termination_phase_rejects_stale_cache_before_and_after_entry(kernel, field, value):
    handle = opened(kernel)
    original = dict(handle._verified_identity)
    handle._verified_identity[field] = value
    with pytest.raises(Error) as refused:
        handle.begin_termination()
    assert refused.value.code == "E_CONFLICT"
    handle._verified_identity = original
    handle.begin_termination()
    handle._verified_identity[field] = value
    with pytest.raises(Error) as refused:
        handle.observe()
    assert refused.value.code == "E_CONFLICT"
    handle.close()


@pytest.mark.parametrize("pid", [True, False, 0, -1, "123", 1.0, 0x100000000])
def test_malformed_pid_is_refused_before_any_open(kernel, pid):
    with pytest.raises(Error) as caught:
        ex.ProcessHandle(pid, "321", kernel.image)
    assert caught.value.code == "E_VALIDATION"
    assert kernel.calls == []


@pytest.mark.parametrize(
    "failure,api",
    [
        ("times_failure", "GetProcessTimes"),
        ("wait_failure", "WaitForSingleObject"),
        ("code_failure", "GetExitCodeProcess"),
    ],
)
def test_terminal_api_failure_retains_exact_stage_and_win32_code(kernel, failure, api):
    handle = opened(kernel)
    kernel.alive = False
    setattr(kernel, failure, True)
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert caught.value.details["windows_api"] == api
    assert caught.value.details["win32_error"] in (5, 6)
    handle.close()


@pytest.mark.parametrize("terminal", [False, True])
def test_creation_identity_change_remains_conflict(kernel, terminal):
    handle = opened(kernel)
    kernel.alive, kernel.birth = not terminal, 999
    with pytest.raises(Error, match="exact owned native identity") as caught:
        handle.observe()
    assert caught.value.code == "E_CONFLICT"
    handle.close()


def test_changed_live_image_remains_conflict(kernel):
    handle = opened(kernel)
    kernel.image = "C:/test-owned/other.exe"
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == "E_CONFLICT"
    handle.close()


@pytest.mark.parametrize(
    "field,value", [("image", "C:/stale/other.exe"), ("creation_filetime", "999")]
)
def test_stale_cached_identity_cannot_supply_terminal_identity(kernel, field, value):
    handle = opened(kernel)
    handle._verified_identity[field] = value
    kernel.alive = False
    with pytest.raises(Error) as caught:
        handle.observe()
    assert caught.value.code == "E_CONFLICT"
    handle.close()


@pytest.mark.parametrize(
    "failure", ["open_failure", "image_error", "exit_after_image", "already_exited", "wrong_birth"]
)
def test_constructor_requires_live_verified_identity_and_cleans_handle(kernel, failure):
    if failure == "already_exited":
        kernel.alive = False
    elif failure == "wrong_birth":
        kernel.birth = 999
    else:
        setattr(kernel, failure, True)
    with pytest.raises(Error):
        ex.ProcessHandle(123, "321", kernel.image)
    closes = [row for row in kernel.calls if row[0] == "close"]
    assert len(closes) == (0 if failure == "open_failure" else 1)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only new test child, no CAD")
@pytest.mark.parametrize("code", [0, 7])
def test_real_owned_child_natural_exit_same_held_handle(code):
    from ctypes import wintypes as w

    child = subprocess.Popen(
        [sys.executable, "-c", f"import sys; sys.stdin.buffer.read(1); raise SystemExit({code})"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    handle = None
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
        times = [w.FILETIME() for _ in range(4)]
        assert k.GetProcessTimes(int(child._handle), *[ctypes.byref(v) for v in times])
        birth = str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        handle = ex.ProcessHandle(child.pid, birth, sys.executable)
        initial = handle.observe()
        assert initial["alive"] is True
        handle.begin_termination()
        pending = handle.observe()
        assert pending["alive"] is True
        assert pending["image_source"].startswith("cached image verified")
        child.stdin.write(b"x")  # Only this test-owned child; request its natural return.
        child.stdin.close()
        assert child.wait(timeout=5) == code
        terminal = handle.observe()
        assert terminal["exit_code"] == code and terminal["signaled"] is True
        assert terminal["alive"] is False and int(terminal["exit_filetime"]) > 0
        assert terminal["creation_filetime"] == initial["creation_filetime"] == birth
        assert terminal["image"] == initial["image"]
        assert terminal["image_source"].startswith("cached image verified")
    finally:
        if handle is not None:
            handle.close()
            assert handle.handle is None
        if not child.stdin.closed:
            # EOF also releases the child's bounded read after a failed assertion.
            child.stdin.close()
        if child.poll() is None:
            child.wait(timeout=5)  # The test child exits naturally; never terminate/kill.
