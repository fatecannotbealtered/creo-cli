"""Two exact unsigned-profile controlled launches. No Creo, SDK or Java-only fallback."""

import ctypes
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from tests import test_unsigned_native_policy_profile as profile

controlled_launcher = profile.controlled_launcher


def record(target, value):
    target.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def invoke_profile(tmp_path, launcher, scenario):
    args, environment, startup, state, *_ = profile.profile_files(
        tmp_path, launcher, preflight=False
    )
    # Keep the full two-application registry/admission path. This executable is
    # the compiled controlled launcher and must never be an installed Creo.
    binary = tmp_path / "Creo/Parametric/bin/parametric.exe"
    assert (
        hashlib.sha256(binary.read_bytes()).digest()
        == hashlib.sha256(launcher.read_bytes()).digest()
    )
    (binary.parent / "scenario").write_text("trust-long", encoding="ascii")
    timeline = tmp_path / "startup-timeline.jsonl"
    changed = startup / "config.sup"
    environment.update(
        CREO_C18_TIMELINE=str(timeline), CREO_C18_SCENARIO=scenario, CREO_C18_CHANGED=str(changed)
    )
    hook = r"""
function global:Record-C18([string]$Phase) {
  [IO.File]::AppendAllText($env:CREO_C18_TIMELINE,
    ((@{phase=$Phase;at_utc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json -Compress)+"`n"))
}
Record-C18 'powershell_entry'
function global:Add-Type {
  [CmdletBinding()]param([string]$TypeDefinition)
  Record-C18 'pipe_type_compile_enter'
  Microsoft.PowerShell.Utility\Add-Type -TypeDefinition $TypeDefinition
  Record-C18 'pipe_type_compile_return'
  if($env:CREO_C18_SCENARIO -eq 'protected-mutation') {
    [IO.File]::WriteAllText($env:CREO_C18_CHANGED,"open_protk_unsigned_apps never`n")
    Record-C18 'extra_protected_config_written'
  }
}
"""
    args[-1] = hook + args[-1]
    assert "JavaOnlyDiagnostic" not in args[-1]
    started = time.monotonic()
    child = subprocess.Popen(
        args,
        env=dict(os.environ, **environment),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    terminal = []
    stop = threading.Event()

    def watch_terminal():
        while not stop.is_set():
            paths = [
                startup / "launch.json",
                *startup.parent.glob(startup.name + ".predispatch-*.json"),
            ]
            for path in paths:
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
                if data.get("status") in ("ready", "not_ready", "not_started"):
                    terminal.append({"seconds": time.monotonic() - started, "path": str(path)})
                    return
            stop.wait(0.01)

    watcher = threading.Thread(target=watch_terminal, daemon=True)
    watcher.start()
    bounded = True
    try:
        # Keep the original controlled invocation's 15-second total budget.
        # Measure EOF separately from strict preflight and process bootstrap.
        stdout, stderr = child.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        bounded = False
        # Observe the controlled long child finish naturally; do not kill CAD
        # or broaden the production deadline to turn this check into a pass.
        stdout, stderr = child.communicate(timeout=15)
    finally:
        stop.set()
        watcher.join(1)
    elapsed = time.monotonic() - started
    phases = [json.loads(line) for line in timeline.read_text().splitlines()]
    result = {
        "scenario": scenario,
        "wall_seconds_to_eof": elapsed,
        "eof_before_original_15_second_budget": bounded,
        "terminal_record": terminal[0] if terminal else None,
        "terminal_to_eof_seconds": elapsed - terminal[0]["seconds"] if terminal else None,
        "outer_returncode": child.returncode,
        "timeline": phases,
        "stdout": stdout.decode("utf-8"),
        "stderr": stderr.decode("utf-8"),
        "new_native_CAD_calls": 0,
        "java_only": False,
    }
    destination = Path(os.environ.get("CREO_CLI_CONTRACT_TRACE", tmp_path)) / scenario
    destination.mkdir(parents=True, exist_ok=True)
    record(destination / "RESULT.json", result)
    assert bounded and elapsed < 15, result
    assert terminal and result["terminal_to_eof_seconds"] < 1.5, result
    assert child.returncode == 1, result
    answer = json.loads(stdout)
    assert (
        answer["qualification"] == "internal_unsigned_full_components_automatic_startup"
        if scenario == "profile-prompt"
        else answer["status"] == "not_started"
    )
    assert (startup / "protk.dat").read_text().count("delay_start false") == 2
    assert (startup / "config.pro").read_text() == (
        "open_protk_unsigned_apps always\n"
        "last_session_directory_path ..\\runtime\\session-history\n"
        "last_session_retrieval yes\n"
    )
    assert not (state / "service-token").exists()
    for name in (
        "config.pro",
        "protk.dat",
        "launch.json",
        "launcher-process.json",
        "launcher-completion.json",
    ):
        path = startup / name
        if path.exists():
            (destination / name).write_bytes(path.read_bytes())
    return answer, result, startup, destination, binary


def test_exact_unsigned_profile_local_policy_prompt_refusal_and_bounded_eof(
    tmp_path, controlled_launcher
):
    answer, result, startup, destination, binary = invoke_profile(
        tmp_path, controlled_launcher, "profile-prompt"
    )
    assert answer["status"] == "not_ready" and answer["native_load_verified"] is False
    assert answer["external_blocker"]["code"] == "external_trust_authorization_required"
    assert answer["session_readiness_attempts"] == 0
    assert answer["failure"]["automatic_retry"] is False
    process = json.loads((startup / "launcher-process.json").read_text(encoding="utf-8-sig"))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_ulong),
    ]

    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]

    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(FileTime)] * 4
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, process["launcher_pid"])
    assert handle
    try:
        image, count = ctypes.create_unicode_buffer(32768), ctypes.c_ulong(32768)
        assert kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(count))
        assert Path(image.value).samefile(binary)
        created, exited, system, user = (FileTime() for _ in range(4))
        assert kernel.GetProcessTimes(handle, *map(ctypes.byref, (created, exited, system, user)))
        assert str((created.high << 32) | created.low) == process["launcher_creation_filetime"]
        assert kernel.WaitForSingleObject(handle, 0) == 258  # Still alive when caller EOF arrived.
        result["controlled_launcher_alive_after_outer_eof"] = True
        assert kernel.WaitForSingleObject(handle, 20000) == 0
    finally:
        kernel.CloseHandle(handle)
    until = time.monotonic() + 5
    completion = startup / "launcher-completion.json"
    while not completion.exists() and time.monotonic() < until:
        time.sleep(0.02)
    final = json.loads(completion.read_text(encoding="utf-8-sig"))
    assert final["exit_code"] == 0 and final["processes_killed"] == []
    for name, marker in (
        ("launcher.stdout.log", "native-log-after-checker-return"),
        ("launcher.stderr.log", "native-error-after-checker-return"),
    ):
        assert marker in (startup / name).read_text()
        (destination / name).write_bytes((startup / name).read_bytes())
    result["natural_child_completion"] = final
    result["late_stdout_and_stderr_retained"] = True
    record(destination / "RESULT.json", result)
    record(destination / "launcher-completion.json", final)
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "wall_seconds_to_eof",
                    "controlled_launcher_alive_after_outer_eof",
                    "late_stdout_and_stderr_retained",
                )
            }
        )
    )


def test_exact_unsigned_profile_extra_protected_config_refuses_before_child_with_bounded_eof(
    tmp_path, controlled_launcher
):
    answer, result, startup, destination, _ = invoke_profile(
        tmp_path, controlled_launcher, "protected-mutation"
    )
    assert answer["failure"]["code"] == "internal_deployment_changed_before_launch"
    assert answer["failure"]["phase"] == "deployment_predispatch"
    assert answer["failure"]["automatic_retry"] is False
    assert answer["process_started"] is False
    assert not (startup / "controlled-launch.txt").exists()
    assert not (startup / "launcher-process.json").exists()
    assert not (startup / "process-host-bootstrap.stdout.log").exists()
    assert (startup / "config.sup").read_text() == "open_protk_unsigned_apps never\n"
    result["no_launcher_or_process_host_created"] = True
    result["extra_protected_config_preserved"] = True
    record(destination / "RESULT.json", result)
    (destination / "config.sup").write_bytes((startup / "config.sup").read_bytes())
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "wall_seconds_to_eof",
                    "no_launcher_or_process_host_created",
                    "extra_protected_config_preserved",
                )
            }
        )
    )
