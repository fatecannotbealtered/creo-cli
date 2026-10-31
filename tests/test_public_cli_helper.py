"""The shipped PowerShell helper uses only a controlled EXE, never Creo or Python at runtime."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/engineering/Invoke-CreoCli.ps1"
PWSH = shutil.which("pwsh")
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
TOKEN = "ct_controlled_token_never_publish"
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PWSH or not CSC.is_file(),
    reason="requires Windows, PowerShell 7.4 and the local C# compiler",
)


@pytest.fixture(scope="module")
def controlled_cli(tmp_path_factory):
    directory = tmp_path_factory.mktemp("controlled-public-cli")
    source = directory / "Controlled.cs"
    source.write_text(
        r"""
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Web.Script.Serialization;
class Controlled {
  static int Main(string[] args) {
    if (args.Length > 0 && args[0] == "--controlled-pipe-child") {
      System.Threading.Thread.Sleep(2500); return 0;
    }
    Console.OutputEncoding = new UTF8Encoding(false);
    var json = new JavaScriptSerializer();
    var fixture = json.Deserialize<Dictionary<string,object>>(File.ReadAllText(
      Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"fixture.json"),Encoding.UTF8));
    var call = new { args=args, unexpected_creo=
      Environment.GetEnvironmentVariable("CREO_CLI_INHERITED_SHOULD_CLEAR") != null,
      unexpected_python=Environment.GetEnvironmentVariable("PYTHONPATH") != null,
      explicit_marker=Environment.GetEnvironmentVariable("CREO_CLI_EXPLICIT_MARKER"),
      config_dir=Environment.GetEnvironmentVariable("CREO_CLI_CONFIG_DIR") };
    File.AppendAllText((string)fixture["trace"],json.Serialize(call)+"\n",new UTF8Encoding(false));
    var mode = (string)fixture["mode"];
    if (args.Contains("--controlled-sleep")) System.Threading.Thread.Sleep(2500);
    if (args.Contains("--controlled-held-pipe")) {
      Process.Start(new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
        "--controlled-pipe-child") { UseShellExecute=false, CreateNoWindow=true });
    }
    Console.Error.Write("受控stderr：保留原始UTF-8\n");
    if (mode == "invalid") { Console.Write("原始非JSON响应\n"); return 0; }
    bool preview = args.Contains("--dry-run");
    bool confirm = args.Contains("--confirm");
    bool local = args.Length > 1 && args[0] == "operation" && args[1] == "show";
    bool ok = mode != "okfalse" && !(mode == "fail-confirm" && confirm);
    object data = preview ? (object)new { preview=new { can_apply=mode!="cannot-apply" },
      confirm_token="ct_controlled_token_never_publish" } : (object)new { args=args, local=local };
    object output = ok ? (object)new { ok=true, schema_version="1.0", data=data } :
      (object)new { ok=false, schema_version="1.0", error=new { code="E_CREO" } };
    Console.Write(json.Serialize(output)+"\n");
    return mode=="nonzero" || (mode=="fail-confirm" && confirm) ? 6 : 0;
  }
}
""",
        encoding="utf-8",
    )
    binary = directory / "controlled.exe"
    subprocess.run(
        [str(CSC), "/nologo", "/r:System.Web.Extensions.dll", f"/out:{binary}", str(source)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return binary


class Case:
    def __init__(self, root, binary, mode="ok"):
        self.root = root
        self.trace = root / "calls.jsonl"
        self.exe = root / "CLI 中文 空格.exe"
        shutil.copyfile(binary, self.exe)
        self.history = root / "continuing-history"
        self.history.mkdir()
        self.history_file = self.history / "operations.sqlite3"
        self.history_file.write_bytes(b"retained original continuous history: never replace")
        self.evidence = root / "evidence"
        self.env = {
            "CREO_CLI_CONFIG_DIR": str(self.history),
            "CREO_CLI_SERVICE_URL": "http://127.0.0.1:19202",
            "CREO_CLI_WORKSPACE": str(root),
            "CREO_CLI_EXPLICIT_MARKER": "中文 保持MiXeD",
        }
        (root / "fixture.json").write_text(
            json.dumps({"trace": str(self.trace), "mode": mode}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.config = root / "caller.json"
        self.config.write_text(
            json.dumps(
                {
                    "script": str(SCRIPT),
                    "exe": str(self.exe),
                    "evidence": str(self.evidence),
                    "environment": self.env,
                    "arguments": [
                        "model",
                        "show",
                        "--model",
                        "MiXeD 手机 空格`$().prt",
                        'quote"tail\\',
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @property
    def calls(self):
        return [json.loads(line) for line in self.trace.read_text("utf-8").splitlines()]

    def run(self, body):
        script = self.root / "caller.ps1"
        script.write_text(
            "param([string]$Configuration)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "$config = Get-Content -LiteralPath $Configuration -Raw -Encoding utf8 | "
            "ConvertFrom-Json -AsHashtable\n"
            ". $config.script\n"
            "$run = New-CreoCliRun -ExecutablePath $config.exe "
            "-EvidenceDirectory $config.evidence -Environment $config.environment "
            "-TimeoutSeconds 8\n" + body,
            encoding="utf-8",
        )
        env = dict(
            os.environ,
            CREO_CLI_INHERITED_SHOULD_CLEAR="inherited-secret-never-propagate",
            PYTHONPATH="inherited Python path must clear",
        )
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(script), str(self.config)],
            env=env,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
        assert self.history_file.read_bytes() == (
            b"retained original continuous history: never replace"
        )
        return json.loads(result.stdout.decode("utf-8-sig"))


def test_exact_argument_boundaries_UTF8_and_environment_without_Python(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    answer = case.run(
        "$result = Invoke-CreoCli -Run $run -Label exact -Arguments $config.arguments\n"
        "$result | ConvertTo-Json -Depth 16\n"
    )
    args = json.loads(case.config.read_text("utf-8"))["arguments"]
    assert answer["data"]["args"] == [*args, "--json", "--compact"]
    assert case.calls[0]["args"] == answer["data"]["args"]
    assert not case.calls[0]["unexpected_creo"]
    assert not case.calls[0]["unexpected_python"]
    assert case.calls[0]["explicit_marker"] == "中文 保持MiXeD"
    raw = (case.evidence / "exact.stdout.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw) == answer
    assert (case.evidence / "exact.stderr.log").read_text("utf-8") == "受控stderr：保留原始UTF-8\n"
    meta = json.loads((case.evidence / "exact.metadata.json").read_text("utf-8"))
    assert meta["state"] == "finished" and meta["ok"] is True


def test_write_uses_only_this_preview_token_and_same_business_arguments(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    answer = case.run(
        "$result = Invoke-CreoCliWrite -Run $run -Label color -Arguments $config.arguments "
        "-Review { param($preview); $preview.data.preview.can_apply -eq $true }\n"
        "$result | ConvertTo-Json -Depth 16\n"
    )
    assert answer["ok"]
    args = json.loads(case.config.read_text("utf-8"))["arguments"]
    assert case.calls[0]["args"] == [*args, "--dry-run", "--json", "--compact"]
    assert case.calls[1]["args"] == [*args, "--confirm", TOKEN, "--json", "--compact"]
    for meta in case.evidence.glob("*.metadata.json"):
        assert TOKEN not in meta.read_text("utf-8")
    assert TOKEN in (case.evidence / "color-preview.stdout.json").read_text("utf-8")


@pytest.mark.parametrize("mode", ["okfalse", "nonzero", "invalid", "cannot-apply", "fail-confirm"])
def test_failures_stop_without_confirmation_replay_or_followup_CAD(tmp_path, controlled_cli, mode):
    case = Case(tmp_path, controlled_cli, mode)
    answer = case.run(
        "$caught = $false; $blocked = $false\n"
        "try { Invoke-CreoCliWrite -Run $run -Label attempt "
        "-Arguments $config.arguments | Out-Null } "
        "catch { $caught = $true }\n"
        "try { Invoke-CreoCli -Run $run -Label prohibited "
        "-Arguments @('model','list') | Out-Null } "
        "catch { $blocked = $true }\n"
        "@{ caught=$caught; blocked=$blocked; reason=$run.BlockReason } | ConvertTo-Json\n"
    )
    assert answer["caught"] and answer["blocked"]
    assert len(case.calls) == (2 if mode == "fail-confirm" else 1)
    assert not (case.evidence / "prohibited.metadata.json").exists()
    assert (case.evidence / "attempt-preview.stdout.json").is_file()


def test_unique_label_preserves_original_output(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    answer = case.run(
        "Invoke-CreoCli -Run $run -Label once -Arguments $config.arguments | Out-Null\n"
        "$path = Join-Path $run.EvidenceDirectory 'once.stdout.json'\n"
        "$before = (Get-FileHash -LiteralPath $path).Hash\n"
        "$rejected = $false\n"
        "try { Invoke-CreoCli -Run $run -Label once -Arguments @('model','list') | Out-Null } "
        "catch { $rejected = $true }\n"
        "$after = (Get-FileHash -LiteralPath $path).Hash\n"
        "@{ rejected=$rejected; unchanged=($before -eq $after) } | ConvertTo-Json\n"
    )
    assert answer == {"rejected": True, "unchanged": True}
    assert len(case.calls) == 1


def test_timeout_keeps_process_alive_and_only_allows_local_operation_show(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    answer = case.run(
        "$caught = $false; $blocked = $false\n"
        "try { Invoke-CreoCli -Run $run -Label slow "
        "-Arguments @('model','show','--controlled-sleep') "
        "-TimeoutSeconds 1 | Out-Null } catch { $caught=$true }\n"
        "$alive = -not $run.PendingInvocations[0].Process.HasExited\n"
        "try { Invoke-CreoCli -Run $run -Label prohibited "
        "-Arguments @('model','list') | Out-Null } "
        "catch { $blocked=$true }\n"
        "$local = Get-CreoCliLocalOperation -Run $run -Label local -OperationId controlled-op\n"
        "foreach ($pending in $run.PendingInvocations) {\n"
        "  [void]$pending.Process.WaitForExit(5000); [void]$pending.StdoutTask.Wait(5000); "
        "[void]$pending.StderrTask.Wait(5000)\n"
        "  $pending.StdoutStream.Flush($true); $pending.StderrStream.Flush($true)\n"
        "  $pending.StdoutStream.Dispose(); $pending.StderrStream.Dispose(); "
        "$pending.Process.Dispose()\n"
        "}\n"
        "@{ caught=$caught; blocked=$blocked; alive_at_timeout=$alive; local_ok=$local.ok; "
        "pending_count=$run.PendingInvocations.Count } | ConvertTo-Json\n"
    )
    assert answer == {
        "caught": True,
        "blocked": True,
        "alive_at_timeout": True,
        "local_ok": True,
        "pending_count": 1,
    }
    assert len(case.calls) == 2
    assert case.calls[1]["args"][:4] == ["operation", "show", "--id", "controlled-op"]
    metadata = json.loads((case.evidence / "slow.metadata.json").read_text("utf-8"))
    assert metadata["state"] == "pending"
    assert metadata["process_killed"] is False
    assert metadata["automatic_retry"] is False
    assert json.loads((case.evidence / "slow.stdout.json").read_text("utf-8"))["ok"]


def test_missing_continuous_history_is_refused_without_creating_it(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    value = json.loads(case.config.read_text("utf-8"))
    missing = tmp_path / "new-history-must-not-create"
    value["environment"]["CREO_CLI_CONFIG_DIR"] = str(missing)
    case.config.write_text(json.dumps(value), encoding="utf-8")
    script = tmp_path / "missing.ps1"
    script.write_text(
        "param([string]$Configuration)\n"
        "$config=Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json -AsHashtable\n"
        ". $config.script\n"
        "try { New-CreoCliRun -ExecutablePath $config.exe -EvidenceDirectory $config.evidence "
        "-Environment $config.environment | Out-Null; exit 99 } catch { exit 0 }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(script), str(case.config)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert not missing.exists()
    assert not case.trace.exists()


def test_finished_CLI_with_inherited_open_pipe_remains_pending(tmp_path, controlled_cli):
    case = Case(tmp_path, controlled_cli)
    answer = case.run(
        "$caught=$false\n"
        "try { Invoke-CreoCli -Run $run -Label held "
        "-Arguments @('reference','--controlled-held-pipe') -TimeoutSeconds 1 | Out-Null } "
        "catch { $caught=$true }\n"
        "$exited = $run.PendingInvocations[0].Process.HasExited\n"
        "foreach ($pending in $run.PendingInvocations) {\n"
        "  [void]$pending.StdoutTask.Wait(5000); [void]$pending.StderrTask.Wait(5000)\n"
        "  $pending.StdoutStream.Flush($true); $pending.StderrStream.Flush($true)\n"
        "  $pending.StdoutStream.Dispose(); $pending.StderrStream.Dispose(); "
        "$pending.Process.Dispose()\n"
        "}\n"
        "@{ caught=$caught; blocked=$run.Blocked; CLI_exited=$exited } | ConvertTo-Json\n"
    )
    assert answer == {"caught": True, "blocked": True, "CLI_exited": True}
    metadata = json.loads((case.evidence / "held.metadata.json").read_text("utf-8"))
    assert metadata["state"] == "process_exited_output_pending"
    assert metadata["exit_code"] == 0
    assert metadata["process_killed"] is False
    assert len(case.calls) == 1
