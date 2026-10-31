"""Captured startup-health decisions in pure PowerShell, never the launcher or CAD."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STARTER = ROOT / "examples/engineering/start-owned-creo.ps1"
PWSH = shutil.which("pwsh")
if not PWSH:
    declared = Path(
        "C:/Users/example/.cache/codex-runtimes/codex-primary-runtime/"
        "dependencies/native/powershell/pwsh.exe"
    )
    PWSH = str(declared) if declared.is_file() else None

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PWSH, reason="requires the declared PowerShell 7 host"
)

# Exact native_diagnostic in the C10 process-only failed-start capture. This is
# a legal disabled diagnostic observation, not a complete ready/loaded assertion.
CAPTURED_DISABLED = {"contract_version": 1, "enabled": False, "stopped": False}


def ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def shell(tmp_path, cases, mode, body, *, as_hashtable=False):
    fixture = tmp_path / "captured-decision-cases.json"
    fixture.write_text(json.dumps(cases), encoding="utf-8")
    code = (
        "$ErrorActionPreference='Stop';"
        + ("Set-StrictMode -Version Latest;" if mode == "Latest" else "Set-StrictMode -Off;")
        + "$tokens=$null;$parseErrors=$null;"
        + f"$ast=[Management.Automation.Language.Parser]::ParseFile({ps(STARTER)},"
        + "[ref]$tokens,[ref]$parseErrors);if($parseErrors.Count){throw 'Source parse error'};"
        + "$functionAst=$ast.Find({param($n)"
        + "$n -is [Management.Automation.Language.FunctionDefinitionAst] -and "
        + "$n.Name -eq 'Test-NativeDiagnosticStop'},$true);"
        + "if($null -eq $functionAst){throw 'Missing actual optional diagnostic helper'};"
        + ". ([scriptblock]::Create($functionAst.Extent.Text));"
        + f"$cases=Get-Content -LiteralPath {ps(fixture)} -Raw -Encoding utf8 | "
        + ("ConvertFrom-Json -AsHashtable;" if as_hashtable else "ConvertFrom-Json;")
        + body
    )
    completed = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout.decode(
        "utf-8", errors="replace"
    ) + completed.stderr.decode("utf-8", errors="replace")
    return json.loads(completed.stdout)


@pytest.mark.parametrize("mode", ["Latest", "default"])
@pytest.mark.parametrize("as_hashtable", [False, True])
def test_real_disabled_optional_and_all_existing_stop_signals(tmp_path, mode, as_hashtable):
    cases = [
        {"name": "captured_disabled", "health": {"native_diagnostic": CAPTURED_DISABLED}},
        {"name": "legacy_absent", "health": {}},
        {"name": "explicit_null", "health": {"native_diagnostic": None}},
        {
            "name": "enabled_without_stop",
            "health": {"native_diagnostic": {"enabled": True, "stopped": False}},
        },
        {
            "name": "optional_nulls",
            "health": {"native_diagnostic": {"stopped": False, "status": None, "blocked": None}},
        },
        {"name": "stopped_bool", "health": {"native_diagnostic": {"stopped": True}}},
        {"name": "stopped_status", "health": {"native_diagnostic": {"status": "stopped"}}},
        {"name": "blocked_bool", "health": {"native_diagnostic": {"blocked": True}}},
        {
            "name": "disabled_cannot_hide_stop",
            "health": {"native_diagnostic": {"enabled": False, "stopped": True}},
        },
        {
            "name": "false_stop_cannot_hide_blocked",
            "health": {
                "native_diagnostic": {"stopped": False, "status": "running", "blocked": True}
            },
        },
        {
            "name": "pending_original_request",
            "health": {
                "native_diagnostic": {
                    "enabled": True,
                    "stopped": True,
                    "reason": "native_request_unreturned_at_wait_expiry",
                    "unreturned_request": {"completion": "not_observed_at_http_wait_expiry"},
                }
            },
        },
        {
            "name": "diagnostic_persistence_error",
            "health": {
                "native_diagnostic": {
                    "enabled": True,
                    "stopped": True,
                    "reason": "diagnostic_persistence_failed",
                    "last": {"status": "diagnostic_persistence_failed"},
                }
            },
        },
    ]
    answer = shell(
        tmp_path,
        cases,
        mode,
        "$rows=@();foreach($case in $cases){"
        "$rows+=@{name=$case.name;blocked=(Test-NativeDiagnosticStop $case.health)}};"
        "$strictRemains=$false;try{([pscustomobject]@{}).no_such_property|Out-Null}"
        "catch{$strictRemains=$true};"
        "@{rows=$rows;strictRemains=$strictRemains}|ConvertTo-Json -Depth 12",
        as_hashtable=as_hashtable,
    )
    assert [row["blocked"] for row in answer["rows"]] == [False] * 5 + [True] * 7
    assert answer["strictRemains"] is (mode == "Latest")


@pytest.mark.parametrize("mode", ["Latest", "default"])
def test_malformed_diagnostic_types_refuse_instead_of_admitting_readiness(tmp_path, mode):
    values = [
        {"stopped": "false"},
        {"stopped": 0},
        {"stopped": [False]},
        {"blocked": "true"},
        {"blocked": 1},
        {"blocked": {"value": False}},
        {"status": True},
        {"status": ["stopped"]},
        "stopped",
        ["stopped"],
    ]
    answer = shell(
        tmp_path,
        [{"native_diagnostic": value} for value in values],
        mode,
        "$rows=@();foreach($health in $cases){try{"
        "$null=Test-NativeDiagnosticStop $health;$rows+=@{refused=$false}}"
        "catch{$rows+=@{refused=$true}}};$rows|ConvertTo-Json -Depth 8",
    )
    assert len(answer) == len(values)
    assert all(row["refused"] for row in answer)


def identity_health():
    return {
        "ok": True,
        "service": "creo-cli",
        "protocol": 2,
        "runtime_class": "controlled.Service",
        "source_sha256": "a" * 64,
        "runtime_configuration": {"state_directory": "C:/controlled/runtime"},
        "native_diagnostic": CAPTURED_DISABLED,
        "startup_state": "starting",
        "toolkit_pump_running": False,
    }


def test_optional_fix_does_not_default_missing_required_identity_fields(tmp_path):
    good = identity_health()
    cases = [good]
    for field in (
        "ok",
        "service",
        "protocol",
        "runtime_class",
        "source_sha256",
        "runtime_configuration",
    ):
        bad = copy.deepcopy(good)
        del bad[field]
        cases.append(bad)
    bad = copy.deepcopy(good)
    del bad["runtime_configuration"]["state_directory"]
    cases.append(bad)
    wrong = copy.deepcopy(good)
    wrong["runtime_class"] = "different.Service"
    cases.append(wrong)
    answer = shell(
        tmp_path,
        cases,
        "Latest",
        "$samePath=$ast.Find({param($n)"
        "$n -is [Management.Automation.Language.FunctionDefinitionAst] -and "
        "$n.Name -eq 'Same-Path'},$true);. ([scriptblock]::Create($samePath.Extent.Text));"
        "$identity=$ast.Find({param($n)"
        "$n -is [Management.Automation.Language.IfStatementAst] -and "
        "$n.Clauses[0].Item1.Extent.Text.Contains('$health.ok')},$true);"
        "$check=[scriptblock]::Create($identity.Extent.Text);"
        "$bundleManifest=[pscustomobject]@{java_app_class='controlled.Service';"
        "component_source_sha256=('a'*64)};$runtimePath='C:/controlled/runtime';"
        "$rows=@();foreach($health in $cases){try{. $check;"
        "$null=Test-NativeDiagnosticStop $health;$rows+=@{accepted=$true}}"
        "catch{$rows+=@{accepted=$false}}};$rows|ConvertTo-Json -Depth 8",
    )
    assert answer[0]["accepted"] is True
    assert all(not row["accepted"] for row in answer[1:])


def test_unblocked_diagnostic_does_not_promote_starting_or_missing_required_ready_fields(tmp_path):
    cases = [identity_health()]
    for field in ("startup_state", "toolkit_pump_running"):
        bad = identity_health()
        bad["startup_state"] = "ready"
        bad["toolkit_pump_running"] = True
        del bad[field]
        cases.append(bad)
    answer = shell(
        tmp_path,
        cases,
        "Latest",
        "$ready=$ast.Find({param($n)"
        "$n -is [Management.Automation.Language.IfStatementAst] -and "
        "$n.Clauses[0].Item1.Extent.Text.Contains('$health.toolkit_pump_running')},$true);"
        "$check=[scriptblock]::Create('return ('+$ready.Clauses[0].Item1.Extent.Text+')');"
        "$requireNative=$true;$nativeImageFile='C:/not-a-witness';"
        "$tokenFile='C:/not-a-credential';$rows=@();foreach($health in $cases){try{"
        "$unblocked= -not (Test-NativeDiagnosticStop $health);$isReady= . $check;"
        "$rows+=@{unblocked=$unblocked;ready=$isReady;refused=$false}}"
        "catch{$rows+=@{refused=$true}}};$rows|ConvertTo-Json -Depth 8",
    )
    assert answer[0] == {"unblocked": True, "ready": False, "refused": False}
    assert all(row["refused"] for row in answer[1:])
