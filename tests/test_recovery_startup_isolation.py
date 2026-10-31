"""Fresh owned recovery data and refusal-only window diagnostics, never Creo."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import test_owned_startup as fixture

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "examples/engineering/RecoveryIsolation.ps1"
STARTER = fixture.SCRIPT
controlled_launcher = fixture.controlled_launcher
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not fixture.PWSH, reason="requires Windows PowerShell startup host"
)


def shell(code, *, extra_env=None):
    environment = dict(os.environ)
    for key in ("PTC_WF_CACHE", "PTC_WLD_ROOT"):
        environment.pop(key, None)
    environment.update(extra_env or {})
    result = subprocess.run(
        [fixture.PWSH, "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        timeout=30,
        env=environment,
    )
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
    return json.loads(result.stdout)


def ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def base(tmp_path):
    creo = tmp_path / "Creo"
    login = tmp_path / "login"
    runtime = tmp_path / "runtime"
    (creo / "Common Files/text").mkdir(parents=True)
    login.mkdir()
    psf = creo / "parametric.psf"
    psf.write_text("CONTROLLED test PSF, never Creo")
    return (
        (
            f"$ErrorActionPreference='Stop';. {ps(HELPER)};"
            "function Resolve-OwnedPath([string]$Value){return [IO.Path]::GetFullPath($Value)};"
            f"$launchCreoRoot={ps(creo)};$creoPsf={ps(psf)};"
            f"$LoginConfigurationDirectory={ps(login)};$loginConfigurationExplicit=$true;"
            f"$startupPath={ps(tmp_path / 'startup')};"
            f"$workflowRootPath={ps(runtime / 'wfroot')};"
            f"$lastSessionPath={ps(runtime / 'session-history')};"
        ),
        creo,
        login,
        runtime,
        psf,
    )


def test_fresh_roots_are_separate_from_inherited_cache_and_not_created_by_preflight(tmp_path):
    code, _, _, runtime, _ = base(tmp_path)
    old = tmp_path / "old-recovery"
    old.mkdir()
    marker = old / "preserved.txt"
    marker.write_bytes(b"original recovery evidence")
    answer = shell(
        code + "Read-RecoveryIsolationSources | ConvertTo-Json -Depth 12",
        extra_env={"PTC_WF_ROOT": str(old)},
    )
    assert answer["workflow_root"] == str(runtime / "wfroot")
    assert answer["last_session_directory_path"] == str(runtime / "session-history")
    assert answer["recording"] == "yes"
    assert answer["inherited_workflow_root_replaced_in_child_only"] is True
    assert answer["previous_recovery_data_read_copied_removed"] is False
    assert not runtime.exists()
    assert marker.read_bytes() == b"original recovery evidence"


@pytest.mark.parametrize(
    "setting",
    ["last_session_retrieval no", 'last_session_directory_path "C:/old-recovery"'],
)
def test_protected_recovery_settings_are_never_overridden(tmp_path, setting):
    code, creo, _, _, _ = base(tmp_path)
    (creo / "Common Files/text/config.sup").write_text(setting)
    answer = shell(
        code + "$answer=try{Read-RecoveryIsolationSources|Out-Null;@{refused=$false}}"
        "catch{@{refused=$true}};$answer|ConvertTo-Json"
    )
    assert answer["refused"] is True


@pytest.mark.parametrize("variable", ["PTC_WF_CACHE", "PTC_WLD_ROOT"])
def test_inherited_unknown_alternate_cache_selector_refuses_start(tmp_path, variable):
    code, _, _, _, _ = base(tmp_path)
    answer = shell(
        code + "$answer=try{Read-RecoveryIsolationSources|Out-Null;@{refused=$false}}"
        "catch{@{refused=$true}};$answer|ConvertTo-Json",
        extra_env={variable: "C:/unreviewed"},
    )
    assert answer["refused"] is True


@pytest.mark.parametrize("variable", ["PTC_WF_ROOT", "PTC_WF_CACHE", "PTC_WLD_ROOT"])
def test_psf_cache_retargeting_is_refused(tmp_path, variable):
    code, _, _, _, psf = base(tmp_path)
    psf.write_text(f"ENV={variable}=C:/unreviewed")
    answer = shell(
        code + "$answer=try{Read-RecoveryIsolationSources|Out-Null;@{refused=$false}}"
        "catch{@{refused=$true}};$answer|ConvertTo-Json"
    )
    assert answer["refused"] is True


def response(runtime):
    return {
        "recovery_configuration": {
            "complete": True,
            "workflow_root": str(runtime / "wfroot"),
            "last_session_directory_path": str(runtime / "session-history"),
            "last_session_retrieval": "YES",
            "last_session_directory_path_value_count": 1,
            "workflow_root_source": "Java process environment inherited from owned Creo launcher",
            "configuration_source": (
                "BaseSession.GetConfigOptionValues(last_session_directory_path)/"
                "GetConfigOption(last_session_retrieval)"
            ),
            "last_session_directory_path_readback": "observed",
            "last_session_retrieval_readback": "observed",
        }
    }


def check_readback(code, data):
    return shell(
        code
        + "$response=ConvertFrom-Json "
        + ps(json.dumps(data))
        + ";$answer=try{Require-RecoveryReadback $response|Out-Null;@{accepted=$true}}"
        "catch{@{accepted=$false}};$answer|ConvertTo-Json"
    )["accepted"]


def test_actual_exact_env_and_native_paths_are_required(tmp_path):
    code, _, _, runtime, _ = base(tmp_path)
    assert check_readback(code, response(runtime)) is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", False),
        ("complete", "true"),
        ("workflow_root", "C:/old-recovery"),
        ("last_session_directory_path", "C:/old-recovery"),
        ("last_session_retrieval", "no"),
        ("last_session_retrieval", " yes "),
        ("last_session_retrieval_readback", "failed"),
        ("configuration_source", "file-only claim"),
        ("last_session_directory_path_value_count", "1"),
        ("last_session_directory_path_value_count", True),
        ("last_session_directory_path_value_count", 2),
    ],
)
def test_mismatched_or_incomplete_native_readback_is_refused(tmp_path, field, value):
    code, _, _, runtime, _ = base(tmp_path)
    data = response(runtime)
    data["recovery_configuration"][field] = value
    assert check_readback(code, data) is False


def test_existing_recovery_path_is_preserved_and_refused(tmp_path):
    code, _, _, runtime, _ = base(tmp_path)
    runtime.mkdir()
    preserved = runtime / "wfroot"
    preserved.mkdir()
    (preserved / "old.txt").write_text("do not erase")
    answer = shell(
        code
        + "$answer=try{Assert-RecoveryLocalPath $workflowRootPath -New|Out-Null;@{refused=$false}}"
        "catch{@{refused=$true}};$answer|ConvertTo-Json"
    )
    assert answer["refused"] is True
    assert (preserved / "old.txt").read_text() == "do not erase"


def test_populated_root_before_dispatch_refuses_without_reading_or_deleting_data(tmp_path):
    code, _, _, runtime, _ = base(tmp_path)
    (runtime / "wfroot").mkdir(parents=True)
    (runtime / "session-history").mkdir()
    old = runtime / "wfroot" / "old-recovery.txt"
    old.write_bytes(b"preserve prior evidence")
    answer = shell(
        code + "$answer=try{Require-OwnedRecoveryDirectories -Empty;@{refused=$false}}"
        "catch{@{refused=$true}};$answer|ConvertTo-Json"
    )
    assert answer["refused"] is True
    assert old.read_bytes() == b"preserve prior evidence"


def test_window_veto_only_queries_exact_owned_pid_and_never_sends_input(tmp_path):
    code, _, _, _, _ = base(tmp_path)
    answer = shell(
        code + "$bundleManifest=@{component_source_sha256=('b'*64)};"
        "$record=@{runtime_pin=@{native_pid=321;service_instance_id='own';process_creations=@{'321'='123'}};recovery_window_observations=@()};"
        "$hostExecutable='C:/owned/xtop.exe';"
        "function Owned-Process([int]$Id,[string]$Executable){@{Id=$Id}};"
        "function Get-Process{param([int]$Id)"
        "[pscustomobject]@{StartTime=[DateTime]::FromFileTimeUtc(123)}};"
        "function Get-OwnedRecoveryDialogs([int]$NativeProcessId){"
        "if($NativeProcessId-ne321){throw 'foreign PID'};'Retrieval'};"
        "try{Require-NoOwnedRecoveryDialog 'before_authenticated_readiness';$refused=$false}"
        "catch{$refused=$true};"
        "@{refused=$refused;record=$record}|ConvertTo-Json -Depth 12"
    )
    assert answer["refused"] is True
    record = answer["record"]
    assert record["external_blocker"]["code"] == "owned_recovery_dialog_requires_input"
    assert record["external_blocker"]["action_performed"] == "none"
    assert record["recovery_window_observations"][0]["native_pid"] == 321
    assert record["recovery_window_observations"][0]["recovery_dialogs"] == ["Retrieval"]
    helper = HELPER.read_text(encoding="utf-8")
    assert "SendMessage" not in helper and "PostMessage" not in helper
    assert "SendInput" not in helper and "BM_CLICK" not in helper


def test_starter_sets_only_child_workflow_root_and_requires_both_window_observations():
    text = STARTER.read_text(encoding="utf-8")
    assert "PTC_WF_ROOT = $workflowRootPath" in text
    assert "Require-NoOwnedRecoveryDialog 'before_authenticated_readiness'" in text
    assert "Require-NoOwnedRecoveryDialog 'after_authenticated_readiness'" in text
    assert text.index(
        "Require-NoOwnedRecoveryDialog 'before_authenticated_readiness'"
    ) < text.index("$session = Invoke-RestMethod")
    assert text.index("Require-NoOwnedRecoveryDialog 'after_authenticated_readiness'") < text.index(
        "$record.recovery_isolation_verified = $true"
    )


def test_late_launcher_record_is_structured_unknown_without_retry_or_kill(
    tmp_path, controlled_launcher
):
    import shutil
    import time

    command, startup, state, _ = fixture.prepare(tmp_path, controlled_launcher, "trust")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ["start-owned-creo.ps1", "RecoveryIsolation.ps1", "InternalUnsignedPreflight.ps1"]:
        shutil.copyfile(ROOT / "examples/engineering" / name, scripts / name)
    host = scripts / "Start-OwnedCreoProcess.ps1"
    host.write_text(
        "param([string]$LaunchSpecPath)\n"
        "$spec=Get-Content -LiteralPath $LaunchSpecPath -Raw|ConvertFrom-Json\n"
        "Start-Sleep -Seconds 6\n"
        "[IO.File]::WriteAllText($spec.process_record,'{\"controlled_late_record\":true}')\n",
        encoding="utf-8",
    )
    command[command.index("-File") + 1] = str(scripts / "start-owned-creo.ps1")
    result = subprocess.run([*command, "-JavaOnlyDiagnostic"], capture_output=True, timeout=20)
    assert result.returncode == 1, result.stdout.decode() + result.stderr.decode()
    answer = json.loads(result.stdout)
    assert answer["status"] == "not_ready"
    assert answer["failure"]["phase"] == "launcher_bootstrap"
    assert answer["failure"]["code"] == "launcher_record_unknown"
    assert answer["native_process_identity"] == "unknown"
    assert answer["session_readiness_attempts"] == 0
    assert answer["failure"]["automatic_retry"] is False
    assert answer["failure"]["processes_stopped"] == []
    assert answer["desktop_input_count"] == answer["cua_input_count"] == 0
    assert answer["recovery_isolation_verified"] is False
    assert (
        json.loads((startup / "launch.json").read_text(encoding="utf-8-sig"))["failure"]
        == answer["failure"]
    )
    deadline = time.monotonic() + 12
    while not (startup / "launcher-process.json").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (
        json.loads((startup / "launcher-process.json").read_text())["controlled_late_record"]
        is True
    )
    assert not (state / "service-token").exists()
