"""Packaged PowerShell entry checks with a controlled subprocess, never a CAD service."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from ctypes import wintypes
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/engineering/check-engineer-environment.ps1"
PWSH = shutil.which("pwsh")
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
pytestmark = pytest.mark.skipif(
    os.name != "nt" or not PWSH or not CSC.is_file(),
    reason="Windows PowerShell 7.4 and local .NET Framework compiler are required",
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def binding(path):
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


@pytest.fixture(scope="session")
def fake_exe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("entry-controlled-process")
    source = directory / "Controlled.cs"
    source.write_text(
        r"""
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
class Controlled {
  static int Main(string[] args) {
    if (args.Length == 2 && args[0] == "--pipe-child") {
      System.Threading.Thread.Sleep(Int32.Parse(args[1])); return 0;
    }
    var json = new JavaScriptSerializer();
    var fixture = json.Deserialize<Dictionary<string,object>>(
      File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"fake.json"),Encoding.UTF8));
    var call = new Dictionary<string,object> {
      {"args",args},
      {"unexpected_token_environment",
       Environment.GetEnvironmentVariable("CREO_CLI_SERVICE_TOKEN") != null},
      {"config_dir",Environment.GetEnvironmentVariable("CREO_CLI_CONFIG_DIR")}
    };
    File.AppendAllText((string)fixture["trace"],json.Serialize(call)+"\n",new UTF8Encoding(false));
    if (args.Length >= 1 && args[0] == "context" && fixture.ContainsKey("failure_document")) {
      if (fixture.ContainsKey("report_collision")) {
        var report = (string)fixture["report_directory"];
        var collision = (string)fixture["report_collision"];
        if (collision == "command" || collision == "both")
          Directory.CreateDirectory(Path.Combine(report,"03-context-offline.stdout.json"));
        if (collision == "final" || collision == "both")
          Directory.CreateDirectory(Path.Combine(report,"REPORT.stdout.json"));
      }
      Console.OutputEncoding = new UTF8Encoding(false);
      Console.WriteLine(json.Serialize(fixture["failure_document"]));
      Console.Error.WriteLine("controlled-private-stderr-never-retain");
      return (int)fixture["failure_exit"];
    }
    object data;
    if (args.Length == 1 && args[0] == "--version") data = fixture["version"];
    else if (args.Length == 3 && args[0] == "reference" && args[1] == "--index")
      data = fixture["index"];
    else if (args.Length >= 2 && args[0] == "context") {
      if (fixture.ContainsKey("delay_ms")) System.Threading.Thread.Sleep((int)fixture["delay_ms"]);
      if (fixture.ContainsKey("pipe_child_ms")) {
        var child = new System.Diagnostics.ProcessStartInfo();
        child.FileName = System.Reflection.Assembly.GetExecutingAssembly().Location;
        child.Arguments = "--pipe-child " + fixture["pipe_child_ms"].ToString();
        child.UseShellExecute = false; child.CreateNoWindow = true;
        System.Diagnostics.Process.Start(child);
      }
      data = fixture[args.Contains("--installation") ? "connected" : "offline"];
    }
    else { Console.WriteLine("{\"ok\":false,\"schema_version\":\"1.0\"}"); return 91; }
    Console.OutputEncoding = new UTF8Encoding(false);
    Console.WriteLine(json.Serialize(new Dictionary<string,object> {
      {"ok",true},{"schema_version","1.0"},{"data",data}
    }));
    return 0;
  }
}
""",
        encoding="utf-8",
    )
    exe = directory / "controlled.exe"
    subprocess.run(
        [str(CSC), "/nologo", "/r:System.Web.Extensions.dll", f"/out:{exe}", str(source)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return exe


class Package:
    def __init__(self, directory, fake_exe):
        self.directory = directory
        self.directory.mkdir()
        self.trace = directory.parent / "calls.jsonl"
        cli = directory / "cli"
        cli.mkdir()
        shutil.copyfile(fake_exe, cli / "creo-cli.exe")
        shutil.copyfile(SCRIPT, directory / "START.ps1")
        (directory / "README.md").write_text("工程师独立入口\n", encoding="utf-8")
        self.pin = {
            "java_pid": 61001,
            "native_pid": 61002,
            "chain": [61001, 61002],
            "process_creations": {"61001": "134000000000000001", "61002": "134000000000000002"},
            "service_instance_id": str(uuid.uuid4()),
        }
        self.components = {
            "creo-cli-service.jar": {"sha256": "a" * 64, "bytes": 17},
            "creo_cli_sketch.dll": {"sha256": "b" * 64, "bytes": 23},
        }
        self.fixture = {
            "trace": str(self.trace),
            "version": {"tool": "creo-cli", "version": "1.1.0-beta.1"},
            "index": {"version": "1.1.0-beta.1", "commands": [{"path": "context"}]},
            "offline": {"version": "1.1.0-beta.1", "state": {"available": True}},
            "connected": {
                "environment": {
                    "connection": {
                        "status": "connected",
                        "instance_id": self.pin["service_instance_id"],
                        "generation": str(self.pin["process_creations"]),
                    }
                },
                "extensions": {
                    "creo": {
                        "installation": {
                            "files_verified": True,
                            "loaded_verified": True,
                            "runtime_identity": {"passed": True},
                            "runtime_pin": self.pin,
                            "component_files": self.components,
                        }
                    }
                },
            },
        }
        self.refresh()

    def refresh(self):
        (self.directory / "cli/fake.json").write_bytes(encoded(self.fixture))
        files = {
            path.relative_to(self.directory).as_posix(): binding(path)
            for path in self.directory.rglob("*")
            if path.is_file() and path.name != "PACKAGE-MANIFEST.json"
        }
        self.manifest = {
            "files": files,
            "file_count_excluding_manifest": len(files),
            "manifest_excludes_itself": True,
        }
        self.manifest_path.write_bytes(encoded(self.manifest))

    @property
    def manifest_path(self):
        return self.directory / "PACKAGE-MANIFEST.json"

    @property
    def calls(self):
        return [json.loads(line) for line in self.trace.read_text("utf-8").splitlines()]

    @property
    def observation(self):
        return self.fixture["connected"]["extensions"]["creo"]["installation"]

    def environment(self):
        external = self.directory.parent / "工程师 外部依赖"
        external.mkdir()
        for name in (
            "Creo/Common Files/x86e_win64/obj/xtop.exe",
            "Creo/Parametric/bin/parametric.exe",
            "JDK/bin/java.exe",
            "components/manifest.json",
            "components/protk.dat",
            "components/creo-cli-service.jar",
            "components/creo_cli_sketch.dll",
            "scope.json",
            "token-file",
        ):
            path = external / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"external fixture, token bytes must never appear")
        for name in self.components:
            self.components[name] = binding(external / "components" / name)
        (external / "workspace").mkdir()
        config = external / "continuous-history"
        config.mkdir()
        for path in (config / "operations.sqlite3", external / "true-global.sqlite3"):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE retained_history (value TEXT)")
                connection.execute("INSERT INTO retained_history VALUES ('preserve me')")
                connection.commit()
        value = {
            "creo": str(external / "Creo"),
            "java": str(external / "JDK"),
            "installation": str(external / "components"),
            "true_global_history": str(external / "true-global.sqlite3"),
            "environment_variables": {
                "CREO_CLI_WORKSPACE": str(external / "workspace"),
                "CREO_CLI_CONFIG_DIR": str(config),
                "CREO_CLI_PERMISSION": "read",
                "CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "0",
                "CREO_CLI_SERVICE_URL": "http://127.0.0.1:19202",
                "CREO_CLI_SERVICE_TOKEN_FILE": str(external / "token-file"),
                "CREO_CLI_SCOPE_FILE": str(external / "scope.json"),
            },
            "runtime_pin": self.pin,
            "component_files": self.components,
            "observed_at_utc": "2026-10-17T12:00:00Z",
        }
        path = external / "工程师 环境.json"
        path.write_bytes(encoded(value))
        self.observation["installation"] = value["installation"]
        self.refresh()
        return path, value

    def run(self, *args, source_override=False):
        script = SCRIPT if source_override else self.directory / "START.ps1"
        command = [PWSH, "-NoProfile", "-File", str(script)]
        if source_override:
            command.extend(["-PackageRoot", str(self.directory)])
        environment = dict(os.environ, CREO_CLI_SERVICE_TOKEN="inherited-secret-must-not-load")
        result = subprocess.run(
            [*command, *map(str, args)],
            capture_output=True,
            env=environment,
            timeout=60,
        )
        assert not result.stderr, result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8")
        assert not stdout.startswith("\ufeff")
        document = json.loads(stdout)
        assert "external fixture, token bytes must never appear" not in stdout
        assert "inherited-secret-must-not-load" not in stdout
        original = document.get("error", {}).get("details", {}).get("original_cli_error")
        if original:
            expected = original["exit_code"] or 1
        else:
            expected = (
                0
                if document["ok"]
                else {
                    "E_CONFIG": 4,
                    "E_NOT_FOUND": 3,
                    "E_CONFLICT": 6,
                }.get(document["error"]["code"], 1)
            )
        assert result.returncode == expected
        return document


@pytest.fixture
def package(tmp_path, fake_exe):
    return Package(tmp_path / "工程师 交付包", fake_exe)


def test_default_offline_is_self_contained_and_creates_no_history(package):
    before = {
        p.relative_to(package.directory): binding(p)
        for p in package.directory.rglob("*")
        if p.is_file()
    }
    result = package.run()
    assert result["ok"], result
    assert result["data"]["package"]["verified"]
    assert result["data"]["operation_database_created"] is False
    assert [call["args"] for call in package.calls] == [
        ["--version"],
        ["reference", "--index", "--compact"],
        ["context", "--compact"],
    ]
    assert all(not call["unexpected_token_environment"] for call in package.calls)
    assert all(call["config_dir"] is None for call in package.calls)
    assert before == {
        p.relative_to(package.directory): binding(p)
        for p in package.directory.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "fault", ["missing", "hash", "size", "extra", "traversal", "self", "collision"]
)
def test_payload_integrity_faults_refuse_before_exe(package, fault):
    readme = package.directory / "README.md"
    if fault == "missing":
        readme.unlink()
    elif fault == "hash":
        readme.write_bytes(b"X" * readme.stat().st_size)
    elif fault == "size":
        readme.write_bytes(b"changed length")
    elif fault == "extra":
        (package.directory / "extra.txt").write_bytes(b"extra")
    else:
        name = {
            "traversal": "../outside",
            "self": "PACKAGE-MANIFEST.json",
            "collision": "readme.md",
        }[fault]
        package.manifest["files"][name] = {"sha256": "a" * 64, "bytes": 1}
        package.manifest_path.write_bytes(encoded(package.manifest))
    result = package.run(source_override=True)
    assert not result["ok"]
    assert result["error"]["code"] == "E_INTEGRITY"
    assert not package.trace.exists()


def test_explicit_environment_preserves_both_existing_histories(package):
    path, declaration = package.environment()
    histories = [
        Path(declaration["true_global_history"]),
        Path(declaration["environment_variables"]["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3",
    ]
    before = [binding(item) for item in histories]
    result = package.run("-EnvironmentFile", path)
    assert result["ok"], result
    assert result["data"]["environment"]["history_preserved"]
    assert [binding(item) for item in histories] == before
    assert all(
        call["config_dir"] == declaration["environment_variables"]["CREO_CLI_CONFIG_DIR"]
        for call in package.calls
    )


def test_preflight_checks_token_presence_without_reading_locked_contents(package):
    path, declaration = package.environment()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(
        declaration["environment_variables"]["CREO_CLI_SERVICE_TOKEN_FILE"],
        0x80000000,
        0,
        None,
        3,
        0,
        None,
    )
    assert handle != ctypes.c_void_p(-1).value
    try:
        result = package.run("-EnvironmentFile", path)
        assert result["ok"], result
        assert result["data"]["environment"]["token_contents_read_by_preflight"] is False
    finally:
        kernel.CloseHandle(handle)


@pytest.mark.parametrize(
    "fault",
    [
        "environment",
        "token",
        "scope",
        "workspace",
        "history",
        "global",
        "empty-history",
        "unknown-variable",
    ],
)
def test_missing_or_invalid_external_declaration_never_creates_replacements(package, fault):
    path, declaration = package.environment()
    variables = declaration["environment_variables"]
    if fault == "environment":
        path.unlink()
    elif fault in ("token", "scope", "history", "global"):
        target = {
            "token": Path(variables["CREO_CLI_SERVICE_TOKEN_FILE"]),
            "scope": Path(variables["CREO_CLI_SCOPE_FILE"]),
            "history": Path(variables["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3",
            "global": Path(declaration["true_global_history"]),
        }[fault]
        target.unlink()
    elif fault == "workspace":
        Path(variables["CREO_CLI_WORKSPACE"]).rmdir()
    elif fault == "empty-history":
        target = Path(variables["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        target.write_bytes(b"")
    else:
        variables["CREO_CLI_SERVICE_TOKEN"] = "must-not-be-output"
        path.write_bytes(encoded(declaration))
    result = package.run("-EnvironmentFile", path)
    assert not result["ok"]
    assert result["error"]["details"]["next_action"]
    assert "must-not-be-output" not in json.dumps(result)
    assert not package.trace.exists()
    if fault in ("token", "scope", "history", "global"):
        assert not target.exists()


@pytest.mark.parametrize("pin", [None, "historical-PID", {"java_pid": 61001}])
def test_connect_needs_complete_engineer_declared_pin(package, pin):
    path, declaration = package.environment()
    if pin is None:
        declaration.pop("runtime_pin")
    else:
        declaration["runtime_pin"] = pin
    path.write_bytes(encoded(declaration))
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert not result["ok"]
    assert result["error"]["code"] == "E_CONFIG"
    assert not package.trace.exists()


def test_connect_collects_all_missing_declaration_fields_before_any_public_call(package):
    path, declaration = package.environment()
    for name in ("java", "observed_at_utc", "component_files", "runtime_pin"):
        declaration.pop(name)
    for name in ("CREO_CLI_SCOPE_FILE", "CREO_CLI_SERVICE_TOKEN_FILE"):
        declaration["environment_variables"].pop(name)
    path.write_bytes(encoded(declaration))
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert result["error"]["code"] == "E_CONFIG"
    summary = result["error"]["details"]["summary"]
    fields = {item["field"] for item in summary["environment"]["declaration_issues"]}
    assert fields == {
        "java",
        "observed_at_utc",
        "runtime_pin",
        "component_files.creo-cli-service.jar",
        "component_files.creo_cli_sketch.dll",
        "environment_variables.CREO_CLI_SCOPE_FILE",
        "environment_variables.CREO_CLI_SERVICE_TOKEN_FILE",
    }
    assert summary["commands"] == []
    assert summary["CAD_calls"] == 0
    assert not package.trace.exists()


def test_connect_collects_invalid_identity_and_component_fields_without_inventing_time(package):
    path, declaration = package.environment()
    declaration.update(observed_at_utc="2026-10-17T12:00:00", runtime_pin={})
    declaration["component_files"]["creo-cli-service.jar"] = {"sha256": "wrong", "bytes": 1}
    declaration["component_files"].pop("creo_cli_sketch.dll")
    path.write_bytes(encoded(declaration))
    result = package.run("-EnvironmentFile", path, "-Connect")
    issues = result["error"]["details"]["summary"]["environment"]["declaration_issues"]
    assert {item["field"] for item in issues} == {
        "observed_at_utc",
        "runtime_pin",
        "component_files.creo-cli-service.jar",
        "component_files.creo_cli_sketch.dll",
    }
    assert all(set(item) == {"field", "problem"} for item in issues)
    assert not package.trace.exists()


@pytest.mark.parametrize("fault", ["missing", "changed"])
def test_connect_checks_both_actual_component_files_before_public_discovery(package, fault):
    path, declaration = package.environment()
    for name in package.components:
        target = Path(declaration["installation"]) / name
        if fault == "missing":
            target.unlink()
        else:
            target.write_bytes(b"unexpected installed component bytes")
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert result["error"]["code"] == "E_CONFIG"
    summary = result["error"]["details"]["summary"]
    assert {item["file"] for item in summary["environment"]["component_file_issues"]} == set(
        package.components
    )
    assert summary["commands"] == []
    assert summary["CAD_calls"] == 0
    assert not package.trace.exists()


def test_connect_retains_declared_observation_time_without_treating_it_as_readiness(package):
    path, declaration = package.environment()
    declaration["observed_at_utc"] = "2026-10-17T20:00:00+08:00"
    path.write_bytes(encoded(declaration))
    before = binding(path)
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert result["ok"], result
    assert result["data"]["connection"]["status"] == "verified_process_only"
    assert result["data"]["connection"]["CAD_readiness"] == "not_assessed"
    assert result["data"]["environment"]["declared_component_files_verified"] is True
    assert binding(path) == before


@pytest.mark.parametrize(
    "fault",
    [
        "files",
        "loaded",
        "health-only",
        "generation",
        "component",
        "state",
        "missing",
        "wrong-type",
        "missing-connection",
        "unknown-connection",
        "wrong-instance",
        "missing-generation",
        "wrong-installation",
    ],
)
def test_connection_observations_cannot_be_promoted_when_incomplete(package, fault):
    path, _ = package.environment()
    if fault == "files":
        package.observation["files_verified"] = False
    elif fault == "loaded":
        package.observation["loaded_verified"] = False
    elif fault == "health-only":
        package.observation.pop("runtime_identity")
    elif fault == "generation":
        package.observation["runtime_pin"] = dict(
            package.pin, service_instance_id=str(uuid.uuid4())
        )
    elif fault == "component":
        package.observation["component_files"] = {
            "creo-cli-service.jar": {"sha256": "c" * 64, "bytes": 17}
        }
    elif fault == "state":
        package.fixture["offline"]["state"]["available"] = False
    elif fault == "missing":
        package.fixture["connected"] = {}
    elif fault == "wrong-type":
        package.observation["loaded_verified"] = "true"
    elif fault == "missing-connection":
        package.fixture["connected"].pop("environment")
    elif fault == "unknown-connection":
        package.fixture["connected"]["environment"]["connection"]["status"] = "unknown"
    elif fault == "wrong-instance":
        package.fixture["connected"]["environment"]["connection"]["instance_id"] = str(uuid.uuid4())
    elif fault == "missing-generation":
        package.fixture["connected"]["environment"]["connection"].pop("generation")
    else:
        package.observation["installation"] = str(package.directory)
    package.refresh()
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert not result["ok"]
    assert all(call["args"][0] in ("--version", "reference", "context") for call in package.calls)
    assert result["error"]["details"]["summary"]["CAD_calls"] == 0


def test_connect_runs_only_explicit_public_process_context(package):
    path, declaration = package.environment()
    result = package.run("-EnvironmentFile", path, "-Connect")
    assert result["ok"], result
    assert result["data"]["connection"]["status"] == "verified_process_only"
    assert result["data"]["connection"]["CAD_readiness"] == "not_assessed"
    assert package.calls[-1]["args"] == [
        "context",
        "--installation",
        declaration["installation"],
        "--creo",
        declaration["creo"],
        "--java-home",
        declaration["java"],
        "--compact",
    ]
    assert len(package.calls) == 4


def test_connect_without_environment_is_actionable(package):
    result = package.run("-Connect")
    assert not result["ok"]
    assert "EnvironmentFile" in result["error"]["message"]
    assert not package.trace.exists()


def test_selected_delivery_is_optional_and_must_bind_same_package(package):
    current = package.directory.parent / "explicit-delivery.json"
    value = {
        "package": {
            "manifest": dict(binding(package.manifest_path), path=str(package.manifest_path)),
            "client_exe": dict(
                binding(package.directory / "cli/creo-cli.exe"),
                path=str(package.directory / "cli/creo-cli.exe"),
            ),
        }
    }
    current.write_bytes(encoded(value))
    assert package.run("-CurrentDeliveryFile", current)["ok"]
    value["package"]["client_exe"]["sha256"] = "0" * 64
    current.write_bytes(encoded(value))
    assert not package.run("-CurrentDeliveryFile", current)["ok"]


def test_new_external_report_retains_json_and_exit_without_overwrite(package):
    report = package.directory.parent / "独立 预检报告"
    result = package.run("-ReportDirectory", report)
    assert result["ok"], result
    assert json.loads((report / "REPORT.stdout.json").read_text("utf-8")) == result
    assert json.loads((report / "REPORT.exit.json").read_text("utf-8")) == {"exit_code": 0}
    before = {p.name: binding(p) for p in report.iterdir()}
    assert len(before) == 8
    assert not package.run("-ReportDirectory", report)["ok"]
    assert before == {p.name: binding(p) for p in report.iterdir()}
    assert not package.run("-ReportDirectory", package.directory / "reports")["ok"]
    assert not (package.directory / "reports").exists()


def test_retained_structured_stdout_redacts_credential_fields(package):
    package.fixture["offline"]["token"] = "controlled-secret-never-retain"
    package.fixture["offline"]["nested"] = [{"password": "controlled-password-never-retain"}]
    package.fixture["offline"]["other"] = {
        key: "controlled-credential-must-not-retain"
        for key in (
            "access_token",
            "refresh_token",
            "client_secret",
            "private_key",
            "sessionid",
            "session_id",
        )
    }
    package.fixture["offline"]["parameters"] = [
        {"name": "api_key", "value": "controlled-named-value-must-not-retain"},
        {
            "target": "secret",
            "before": "controlled-before-secret",
            "after": "controlled-after-secret",
        },
    ]
    package.refresh()
    report = package.directory.parent / "redacted-output"
    assert package.run("-ReportDirectory", report)["ok"]
    retained = (report / "03-context-offline.stdout.json").read_text("utf-8")
    assert "controlled-secret-never-retain" not in retained
    assert "controlled-password-never-retain" not in retained
    assert "controlled-credential-must-not-retain" not in retained
    assert "controlled-named-value-must-not-retain" not in retained
    assert "controlled-before-secret" not in retained
    assert "controlled-after-secret" not in retained
    document = json.loads(retained)
    assert document["data"]["token"] == "<redacted>"
    assert document["data"]["nested"][0]["password"] == "<redacted>"


@pytest.mark.parametrize("delay", ["delay_ms", "pipe_child_ms"])
def test_stalled_public_exe_has_a_deadline_without_claiming_cancellation(package, delay):
    package.fixture[delay] = 3000
    package.refresh()
    started = time.monotonic()
    result = package.run("-CommandTimeoutSeconds", 1)
    assert time.monotonic() - started < 12
    assert not result["ok"]
    assert result["error"]["code"] == "E_VERIFY_INCOMPLETE"
    assert result["error"]["details"]["summary"]["commands"][-1]["timed_out"]
    assert "may still be running" in result["error"]["message"]
    assert "did not kill" in result["error"]["details"]["next_action"]


@pytest.mark.parametrize(
    ("code", "retryable", "exit_code"),
    [("E_AUTH", False, 4), ("E_NATIVE_READ_PENDING", False, 8), ("E_NETWORK", True, 7)],
)
@pytest.mark.parametrize("collision", [None, "command", "final", "both"])
def test_original_cli_error_survives_report_storage_failure(
    package, code, retryable, exit_code, collision
):
    report = package.directory.parent / "controlled-error-report"
    package.fixture["failure_document"] = {
        "ok": False,
        "schema_version": "1.0",
        "error": {
            "code": code,
            "retryable": retryable,
            "message": "controlled-private-message-never-retain",
            "details": {
                "token": "controlled-private-token-never-retain",
                "evidence_id": "forged-evidence-never-retain",
                "diagnostic_request_id": "forged-request-never-retain",
            },
        },
    }
    package.fixture["failure_exit"] = exit_code
    if collision:
        package.fixture["report_collision"] = collision
        package.fixture["report_directory"] = str(report)
    package.refresh()
    result = package.run("-ReportDirectory", report)
    expected = {"code": code, "retryable": retryable, "exit_code": exit_code}
    assert not result["ok"]
    assert result["error"]["code"] == code
    assert result["error"]["retryable"] is retryable
    assert result["error"]["details"]["original_cli_error"] == expected
    assert result["error"]["details"]["summary"]["commands"][-1]["exit_code"] == exit_code
    if collision:
        storage = result["error"]["details"]["report_storage_error"]
        assert storage["code"] == "E_IO"
        assert storage["failures"]
    else:
        assert "report_storage_error" not in result["error"]["details"]
    combined = json.dumps(result) + "".join(
        path.read_text("utf-8") for path in report.iterdir() if path.is_file()
    )
    for marker in (
        "controlled-private-message-never-retain",
        "controlled-private-token-never-retain",
        "controlled-private-stderr-never-retain",
        "forged-evidence-never-retain",
        "forged-request-never-retain",
    ):
        assert marker not in combined
    if collision in ("command", "both"):
        assert (report / "03-context-offline.stdout.json").is_dir()
    if collision in ("final", "both"):
        assert (report / "REPORT.stdout.json").is_dir()
