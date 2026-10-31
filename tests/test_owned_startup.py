"""Exercise the shipped startup recipe with a controlled executable, never Creo."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from creo_cli import service_bundle
from scripts import reload_service

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    Path(os.environ.get("CREO_CLI_CONTRACT_HELPERS", ROOT / "examples/engineering"))
    / "start-owned-creo.ps1"
)
PWSH = shutil.which("pwsh")
CSC = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")


def test_registry_autostarts_native_before_java_and_keeps_explicit_manual_mode():
    value = service_bundle.registry(Path("owned/service.jar"), native_dll=Path("owned/native.dll"))
    assert value.index("startup           dll") < value.index("startup           otk_java")
    assert value.count("delay_start       false") == 2
    assert "delay_start       true" not in value
    manual = service_bundle.registry(Path("owned/service.jar"), auto_start=False)
    assert "delay_start       true" in manual


def test_legacy_restart_cannot_control_an_unowned_process_even_with_force():
    with patch.object(subprocess, "run") as runner:
        with pytest.raises(RuntimeError, match="global Creo restart is disabled"):
            reload_service.stop_creo()
    runner.assert_not_called()


def test_legacy_restart_main_refuses_before_build_observation_or_registration(capsys):
    with patch("sys.argv", ["reload_service.py", "--restart", "--force"]):
        with patch.object(reload_service, "load_point") as locate:
            assert reload_service.main() == 1
    locate.assert_not_called()
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["steps"] == {}
    assert "global Creo restart is disabled" in answer["error"]


@pytest.fixture(scope="module")
def controlled_launcher(tmp_path_factory):
    if os.name != "nt" or not PWSH or not CSC.is_file():
        pytest.skip("requires Windows, PowerShell 7.4 and the local C# compiler")
    directory = tmp_path_factory.mktemp("controlled-owned-launcher")
    source = directory / "Controlled.cs"
    source.write_text(
        r"""
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Diagnostics;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class Controlled {
  static int ServeJava(string scenario) {
    var server = new HttpListener();
    var json = new JavaScriptSerializer();
    var state = Environment.GetEnvironmentVariable("CREO_CLI_CONFIG_DIR");
    var secret = new string('b',64);
    File.WriteAllText(Path.Combine(state,"service-token"),secret);
    server.Prefixes.Add("http://127.0.0.1:"+
      Environment.GetEnvironmentVariable("CREO_CLI_SERVICE_PORT")+"/");
    server.Start();
    for (int i=0; i<3; i++) {
      var request = server.GetContext();
      var path = request.Request.RawUrl;
      File.AppendAllText("controlled-requests.txt",path+"\n");
      object response;
      if (path == "/health") {
        response = new { ok=true, service="creo-cli", protocol=2,
          runtime_class="controlled.Service", source_sha256=new string('a',64),
          service_instance_id="93d93317-e5bb-4beb-a3c7-1d4b0480b1d6",
          process_id=Process.GetCurrentProcess().Id, startup_state="ready",
          toolkit_pump_running=true, runtime_configuration=new { state_directory=state } };
      } else {
        var authenticated = request.Request.Headers["X-Creo-Cli-Token"] == secret;
        response = new { ok=authenticated && scenario != "session-error",
          session_reachable=true, creation_api=true, native_sketch_available=false,
          recovery_configuration=new {complete=true,
            workflow_root=Environment.GetEnvironmentVariable("PTC_WF_ROOT"),
            last_session_directory_path=Path.Combine(state,"session-history"),
            last_session_directory_path_value_count=1,last_session_retrieval="yes",
            last_session_directory_path_readback="observed",last_session_retrieval_readback="observed",
            workflow_root_source="Java process environment inherited from owned Creo launcher",
            configuration_source="BaseSession.GetConfigOptionValues(last_session_directory_path)/"+
              "GetConfigOption(last_session_retrieval)"} };
      }
      var bytes = Encoding.UTF8.GetBytes(json.Serialize(response));
      request.Response.ContentType="application/json";
      request.Response.ContentLength64=bytes.Length;
      request.Response.OutputStream.Write(bytes,0,bytes.Length); request.Response.Close();
      if (path == "/session" && scenario == "session-error") break;
    }
    if (scenario == "ready-long-java-only") {
      System.Threading.Thread.Sleep(12000);
      Console.WriteLine("native-log-after-checker-return");
      Console.Error.WriteLine("native-error-after-checker-return");
    } else { System.Threading.Thread.Sleep(3000); }
    server.Stop(); return 0;
  }
  static int Main(string[] args) {
    if (args.Length > 0 && args[0] == "--controlled-java") return ServeJava(args[1]);
    if (args.Length > 0 && args[0] == "--controlled-host") {
      var child = Process.Start(new ProcessStartInfo(
        Environment.GetEnvironmentVariable("PRO_JAVA_COMMAND"),
        "--controlled-java "+args[1]) { UseShellExecute=false, CreateNoWindow=true });
      child.WaitForExit(); return child.ExitCode;
    }
    var scenario = File.ReadAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"scenario"));
    File.WriteAllText("controlled-launch.txt","This is a test executable, not Creo.");
    File.WriteAllText("controlled-arguments.json",new JavaScriptSerializer().Serialize(args),
      new UTF8Encoding(false));
    if (scenario == "ready-java-only" || scenario == "session-error" ||
        scenario == "ready-long-java-only") {
      var creo = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory).Parent.Parent.FullName;
      var host = Path.Combine(creo,"Common Files/x86e_win64/obj/xtop.exe");
      var child = Process.Start(new ProcessStartInfo(host,
        "--controlled-host "+scenario+" -ppid "+Process.GetCurrentProcess().Id)
        { UseShellExecute=false, CreateNoWindow=true });
      child.WaitForExit();
      if (scenario == "ready-long-java-only") {
        Console.WriteLine("native-log-after-checker-return");
        Console.Error.WriteLine("native-error-after-checker-return");
      }
      return child.ExitCode;
    } else if (scenario == "trust" || scenario == "trust-long") {
      File.WriteAllText("trail.txt.1","! permission_request_dlg: warning\n"+
        "! This application is from an unknown source.\n");
      if (scenario == "trust-long") {
        System.Threading.Thread.Sleep(12000);
        Console.WriteLine("native-log-after-checker-return");
        Console.Error.WriteLine("native-error-after-checker-return");
      }
    } else if (scenario == "wrong-identity") {
      var server = new HttpListener();
      server.Prefixes.Add("http://127.0.0.1:"+Environment.GetEnvironmentVariable("CREO_CLI_SERVICE_PORT")+"/");
      server.Start();
      var request = server.GetContext();
      File.AppendAllText("controlled-requests.txt",request.Request.RawUrl+"\n");
      var response = Encoding.UTF8.GetBytes("{\"ok\":true,\"service\":\"creo-cli\",\"protocol\":2,"+
        "\"runtime_class\":\"unowned.Service\"}");
      request.Response.ContentType="application/json";
      request.Response.ContentLength64=response.Length;
      request.Response.OutputStream.Write(response,0,response.Length);
      request.Response.Close(); System.Threading.Thread.Sleep(200); server.Stop();
    }
    return 0;
  }
}
""",
        encoding="utf-8",
    )
    binary = directory / "controlled.exe"
    subprocess.run(
        [str(CSC), "/nologo", "/r:System.Web.Extensions.dll", f"/out:{binary}", str(source)],
        capture_output=True,
        timeout=30,
        check=True,
    )
    return binary


def prepare(directory, controlled_launcher, scenario):
    creo = directory / "Creo"
    java = directory / "Java"
    installed = directory / "components"
    startup = directory / "startup"
    state = directory / "runtime"
    login = directory / "declared-login"
    login.mkdir()
    for path in (creo / "Parametric/bin", java / "bin", installed):
        path.mkdir(parents=True)
    shutil.copyfile(controlled_launcher, creo / "Parametric/bin/parametric.exe")
    (creo / "Parametric/bin/scenario").write_text(scenario)
    (creo / "Parametric/bin/parametric.psf").write_text("controlled PSF")
    (java / "bin/java.exe").write_bytes(b"not executed")
    if scenario in ("ready-java-only", "session-error", "ready-long-java-only"):
        host = creo / "Common Files/x86e_win64/obj/xtop.exe"
        host.parent.mkdir(parents=True)
        shutil.copyfile(controlled_launcher, host)
        shutil.copyfile(controlled_launcher, java / "bin/java.exe")
    files = {}
    for name in ("creo-cli-service.jar", "creo_cli_sketch.dll"):
        payload = ("controlled fixture: " + name).encode()
        (installed / name).write_bytes(payload)
        files[name] = {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    manifest = {
        "tool": "creo-cli",
        "protocol": 2,
        "java_app_class": "controlled.Service",
        "component_source_sha256": "a" * 64,
        "runtime_profile": {"mode": "environment"},
        "files": files,
    }
    (installed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (installed / "protk.dat").write_text("installed file; startup recipe generates its own")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [
        PWSH,
        "-NoProfile",
        "-File",
        str(SCRIPT),
        "-CreoRoot",
        str(creo),
        "-JavaHome",
        str(java),
        "-InstallationDirectory",
        str(installed),
        "-StartupDirectory",
        str(startup),
        "-RuntimeDirectory",
        str(state),
        "-Port",
        str(port),
        "-WaitSeconds",
        "5",
        "-LoginConfigurationDirectory",
        str(login),
    ]
    return command, startup, state, installed


def controlled_signature(
    command, *, status="Valid", signer="a" * 40, pin="a" * 40, policy="signed-only"
):
    """PowerShell function fixture in a controlled host, never an actual signature."""

    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    fixture = (
        "function global:Get-AuthenticodeSignature { [CmdletBinding()] param([string]$LiteralPath);"
        "[pscustomobject]@{Status=" + literal(status) + ";SignatureType='Authenticode';"
        "SignerCertificate="
        + (
            "[pscustomobject]@{Thumbprint="
            + literal(signer)
            + ";Subject='CONTROLLED FIXTURE NOT A SIGNATURE'}"
            if signer is not None
            else "$null"
        )
        + ";"
        "TimeStamperCertificate=[pscustomobject]@{Subject='CONTROLLED TIMESTAMP FIXTURE'}}};"
    )
    values = [*command[4:], "-ExpectedNativeSignerThumbprint", pin, "-TrustPolicy", policy]
    parameters = []
    while values:
        key = values.pop(0)
        if not key.startswith("-"):
            raise AssertionError("controlled parameter transport requires named arguments")
        value = literal(values.pop(0)) if values and not values[0].startswith("-") else "$true"
        parameters.append(literal(key[1:]) + "=" + value)
    invocation = (
        "$fixtureParameters=@{"
        + ";".join(parameters)
        + "};& "
        + literal(command[3])
        + " @fixtureParameters"
    )
    return [command[0], "-NoProfile", "-NonInteractive", "-Command", fixture + invocation]


def assert_not_started(result, startup, state, code):
    assert result.returncode == 1, result.stderr.decode("utf-8", errors="replace")
    answer = json.loads(result.stdout.decode("utf-8"))
    assert answer["status"] == "not_started"
    assert answer["process_started"] is False
    assert answer["failure"]["code"] == code
    assert answer["session_readiness_attempts"] == 0
    assert answer["desktop_input_count"] == answer["cua_input_count"] == 0
    assert not startup.exists() and not state.exists()
    assert json.loads(Path(answer["report_path"]).read_text(encoding="utf-8")) == answer
    return answer


def test_unsigned_full_bundle_refuses_before_process_and_runtime(tmp_path, controlled_launcher):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    result = subprocess.run(command, capture_output=True, timeout=10)
    answer = assert_not_started(result, startup, state, "native_authenticode_required")
    assert answer["native_signature"]["authenticode_verified"] is False
    assert answer["native_signature"]["status"] in ("NotSigned", "UnknownError")


@pytest.mark.parametrize("status", ["NotSigned", "HashMismatch", "UnknownError", "NotTrusted"])
def test_nonvalid_signature_never_uses_stamp_or_starts_prompt(
    tmp_path, controlled_launcher, status
):
    command, startup, state, installed = prepare(tmp_path, controlled_launcher, "trust")
    (installed / "creo_cli_sketch.dll.stamp.json").write_text('{"signed":true,"trusted":true}')
    result = subprocess.run(
        controlled_signature(command, status=status), capture_output=True, timeout=10
    )
    assert_not_started(result, startup, state, "native_authenticode_required")


@pytest.mark.parametrize(
    ("signer", "pin", "code"),
    [
        ("b" * 40, "a" * 40, "native_signer_mismatch"),
        ("a" * 40, "", "native_signer_authorization_missing"),
        ("a" * 40, "not-a-thumbprint", "native_signer_authorization_missing"),
    ],
)
def test_publisher_authorization_is_explicit_and_exact(
    tmp_path, controlled_launcher, signer, pin, code
):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    result = subprocess.run(
        controlled_signature(command, signer=signer, pin=pin), capture_output=True, timeout=10
    )
    assert_not_started(result, startup, state, code)


@pytest.mark.parametrize("value", [None, "prompt", "never"])
def test_inherited_policy_must_be_proven_noninteractive(tmp_path, controlled_launcher, value):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    if value:
        (tmp_path / "declared-login/config.pro").write_text(
            "open_protk_signed_apps " + value + "\n"
        )
    result = subprocess.run(
        controlled_signature(command, policy="inherit"), capture_output=True, timeout=10
    )
    answer = assert_not_started(
        result, startup, state, "inherited_policy_not_proven_noninteractive"
    )
    assert answer["inherited_policy"]["open_protk_signed_apps"] == value
    assert answer["local_configuration_written"] is False


def test_signed_only_preflight_is_read_only_and_reports_all_signed_scope(
    tmp_path, controlled_launcher
):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    result = subprocess.run(
        controlled_signature([*command, "-PreflightOnly"]), capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    answer = json.loads(result.stdout)
    assert answer["status"] == "preflight_passed_not_started"
    assert answer["process_started"] is False
    assert not startup.exists() and not state.exists()
    assert answer["proposed_policy"] == {
        "open_protk_signed_apps": "always",
        "open_protk_unsigned_apps": "never",
    }
    assert answer["local_configuration_written"] is False
    assert answer["native_signature"]["publisher_pin_matched"] is True
    assert "all signed" in answer["next_action"]


@pytest.mark.parametrize(
    "locked_line", ["open_protk_signed_apps never", "open_protk_unsigned_apps prompt"]
)
def test_protected_policy_conflict_refuses_without_overriding(
    tmp_path, controlled_launcher, locked_line
):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    protected = tmp_path / "Creo/Common Files/text/config.sup"
    protected.parent.mkdir(parents=True)
    protected.write_text(locked_line + "\n")
    before = protected.read_bytes()
    result = subprocess.run(controlled_signature(command), capture_output=True, timeout=10)
    assert_not_started(result, startup, state, "protected_configuration_conflict")
    assert protected.read_bytes() == before


def test_inherit_proven_policy_is_not_rewritten_or_weakened(tmp_path, controlled_launcher):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "trust")
    configured = tmp_path / "declared-login/config.pro"
    configured.write_text("open_protk_signed_apps always\nopen_protk_unsigned_apps prompt\n")
    before = configured.read_bytes()
    result = subprocess.run(
        controlled_signature([*command, "-PreflightOnly"], policy="inherit"),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    answer = json.loads(result.stdout)
    assert answer["proposed_policy"] is None
    assert answer["inherited_policy"]["open_protk_unsigned_apps"] == "prompt"
    assert configured.read_bytes() == before
    assert not startup.exists() and not state.exists()


def test_java_only_diagnostic_cannot_apply_signed_only_policy(tmp_path, controlled_launcher):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, "ready-java-only")
    result = subprocess.run(
        [*command, "-JavaOnlyDiagnostic", "-TrustPolicy", "signed-only"],
        capture_output=True,
        timeout=10,
    )
    assert_not_started(result, startup, state, "java_only_cannot_apply_trust_policy")


@pytest.mark.parametrize(
    ("policy", "requested", "expected_unsigned", "accepted"),
    [
        (None, "signed-only", "prompt", False),
        (
            {"complete": False, "signed_apps": "always", "unsigned_apps": "never"},
            "signed-only",
            "prompt",
            False,
        ),
        (
            {"complete": True, "signed_apps": "prompt", "unsigned_apps": "never"},
            "signed-only",
            "prompt",
            False,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "prompt"},
            "signed-only",
            "prompt",
            False,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "unknown"},
            "inherit",
            "unknown",
            False,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "always"},
            "inherit",
            "prompt",
            False,
        ),
        ({"complete": True, "signed_apps": "always"}, "signed-only", "prompt", False),
        (
            {"complete": True, "signed_apps": "Always", "unsigned_apps": "Never"},
            "signed-only",
            "prompt",
            True,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "prompt"},
            "inherit",
            "prompt",
            True,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "always"},
            "internal-unsigned-trial",
            "prompt",
            True,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "never"},
            "internal-unsigned-trial",
            "never",
            False,
        ),
        (
            {"complete": True, "signed_apps": "always", "unsigned_apps": "prompt"},
            "internal-unsigned-trial",
            "prompt",
            False,
        ),
    ],
)
def test_effective_policy_guard_requires_actual_complete_matching_readback(
    policy, requested, expected_unsigned, accepted
):
    if os.name != "nt" or not PWSH:
        pytest.skip("PowerShell policy guard requires the declared Windows host")
    environment = dict(
        os.environ,
        CREO_POLICY_TEST_SOURCE=str(SCRIPT),
        CREO_POLICY_TEST_RESPONSE=json.dumps({"deployment_policy": policy} if policy else {}),
        CREO_POLICY_TEST_REQUESTED=requested,
        CREO_POLICY_TEST_EXPECTED_UNSIGNED=expected_unsigned,
    )
    command = r"""
$ErrorActionPreference='Stop';$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:CREO_POLICY_TEST_SOURCE,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Source under test does not parse'}
$function=$ast.Find({param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
  $node.Name -eq 'Require-EffectiveDeploymentPolicy'
},$true)
if($null -eq $function){throw 'Policy guard absent'}
. ([scriptblock]::Create($function.Extent.Text))
$response=ConvertFrom-Json $env:CREO_POLICY_TEST_RESPONSE
try {
  $policyArgs=@{Response=$response;Requested=$env:CREO_POLICY_TEST_REQUESTED;
    ExpectedUnsigned=$env:CREO_POLICY_TEST_EXPECTED_UNSIGNED}
  $observed=Require-EffectiveDeploymentPolicy @policyArgs
  @{accepted=$true;observed=$observed}|ConvertTo-Json -Depth 5
} catch { @{accepted=$false;message=$_.Exception.Message}|ConvertTo-Json -Depth 5 }
"""
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        timeout=10,
        check=True,
    )
    answer = json.loads(result.stdout)
    assert answer["accepted"] is accepted


@pytest.mark.parametrize("scenario", ["trust", "wrong-identity", "no-response"])
def test_automatic_startup_preserves_first_failure_without_CAD_or_desktop_fallback(
    tmp_path, controlled_launcher, scenario
):
    command, startup, state, _ = prepare(tmp_path, controlled_launcher, scenario)
    result = subprocess.run(controlled_signature(command), capture_output=True, timeout=20)
    assert result.returncode == 1, result.stderr.decode("utf-8", errors="replace")
    answer = json.loads(result.stdout.decode("utf-8"))
    retained = json.loads((startup / "launch.json").read_text(encoding="utf-8-sig"))
    assert answer == retained
    assert answer["status"] == "not_ready"
    assert answer["session_readiness_attempts"] == 0
    assert answer["desktop_input_count"] == answer["cua_input_count"] == 0
    assert answer["headless"] is False
    assert answer["failure"]["automatic_retry"] is False
    assert answer["failure"]["processes_stopped"] == []
    assert (startup / "controlled-launch.txt").is_file()
    assert not (state / "service-token").exists()
    registry = (startup / "protk.dat").read_text()
    assert registry.count("delay_start false") == 2
    assert (
        startup / "config.pro"
    ).read_text() == "open_protk_signed_apps always\nopen_protk_unsigned_apps never\n"
    assert answer["deployment_preflight"]["local_configuration_written"] is True
    if scenario == "trust":
        assert answer["external_blocker"]["code"] == "external_trust_authorization_required"
        assert (startup / "trail.txt.1").is_file()
    elif scenario == "wrong-identity":
        assert "identity differs" in answer["failure"]["message"]
        assert (startup / "controlled-requests.txt").read_text().splitlines() == ["/health"]


def test_existing_owned_directory_is_preserved_before_process_launch(tmp_path, controlled_launcher):
    command, startup, _, _ = prepare(tmp_path, controlled_launcher, "trust")
    startup.mkdir()
    sentinel = startup / "retained.txt"
    sentinel.write_text("must remain unchanged")
    result = subprocess.run(command, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert sentinel.read_text() == "must remain unchanged"
    assert not (startup / "controlled-launch.txt").exists()


@pytest.mark.parametrize("scenario", ["ready-java-only", "session-error"])
def test_java_only_readiness_is_authenticated_once_and_never_claims_native_acceptance(
    tmp_path, controlled_launcher, scenario
):
    command, startup, _, _ = prepare(tmp_path, controlled_launcher, scenario)
    result = subprocess.run([*command, "-JavaOnlyDiagnostic"], capture_output=True, timeout=20)
    answer = json.loads(result.stdout.decode("utf-8"))
    assert answer["desktop_input_count"] == answer["cua_input_count"] == 0
    assert answer["require_native"] is False
    assert answer["native_load_verified"] is False
    assert answer["qualification"] == "java_only_diagnostic_not_engineering_acceptance"
    assert answer["session_readiness_attempts"] == 1
    assert (startup / "protk.dat").read_text().count("delay_start true") == 1
    assert "b" * 64 not in result.stdout.decode("utf-8")
    calls = (startup / "controlled-requests.txt").read_text().splitlines()
    assert calls.count("/session") == 1
    if scenario == "ready-java-only":
        assert result.returncode == 0
        assert answer["status"] == "ready"
        assert calls[-2:] == ["/session", "/health"]
        assert answer["session_readiness"]["ok"] is True
    else:
        assert result.returncode == 1
        assert answer["status"] == "not_ready"
        assert calls[-1] == "/session"
        assert answer["session_readiness"]["ok"] is False


def test_exact_InitialModel_uses_safe_UTF8_single_file_argument_and_retains_input_hash(
    tmp_path, controlled_launcher
):
    command, startup, _, _ = prepare(tmp_path, controlled_launcher, "ready-java-only")
    model = tmp_path / "中文 空格`$()" / "MiXeD_frame.prt.2"
    model.parent.mkdir()
    model.write_bytes(b"controlled exact native version; never interpreted by real Creo")
    before = hashlib.sha256(model.read_bytes()).hexdigest()
    result = subprocess.run(
        [*command, "-JavaOnlyDiagnostic", "-InitialModel", str(model)],
        capture_output=True,
        timeout=20,
    )
    answer = json.loads(result.stdout.decode("utf-8"))
    assert result.returncode == 0, answer
    assert answer["status"] == "ready"
    assert answer["psf"] is None
    assert answer["argument_transport"] == "ProcessStartInfo.ArgumentList"
    assert answer["launch_arguments"] == [str(model)]
    assert answer["initial_model"]["path"] == str(model)
    assert answer["initial_model"]["sha256"] == before
    assert answer["initial_model"]["input_bytes_unchanged_after_start"] is True
    assert answer["initial_model"]["selection"] == "exact_file_argument"
    assert "independent public CLI readback" in answer["initial_model"]["context_qualification"]
    assert json.loads((startup / "controlled-arguments.json").read_text("utf-8")) == [str(model)]
    assert hashlib.sha256(model.read_bytes()).hexdigest() == before
    assert answer["require_native"] is False and answer["native_load_verified"] is False


@pytest.mark.parametrize("kind", ["relative", "directory", "unnumbered", "zero", "STEP", "control"])
def test_invalid_InitialModel_refuses_before_launch_without_touching_input(
    tmp_path, controlled_launcher, kind
):
    command, startup, _, _ = prepare(tmp_path, controlled_launcher, "trust")
    model = (
        tmp_path
        / {
            "relative": "part.prt.2",
            "directory": "directory.asm.2",
            "unnumbered": "part.prt",
            "zero": "part.prt.0",
            "STEP": "part.stp",
            "control": "part.prt.2",
        }[kind]
    )
    if kind == "directory":
        model.mkdir()
    else:
        model.write_bytes(b"preserved input")
    value = str(model)
    if kind == "relative":
        value = model.name
    elif kind == "control":
        value += "\n"
    result = subprocess.run([*command, "-InitialModel", value], capture_output=True, timeout=10)
    assert result.returncode != 0
    assert not startup.exists()
    if kind != "directory":
        assert model.read_bytes() == b"preserved input"


@pytest.mark.parametrize("scenario", ["trust-long", "ready-long-java-only"])
def test_outer_stdout_EOF_is_bounded_while_owned_host_and_native_keep_running(
    tmp_path, controlled_launcher, scenario
):
    """Real pipe/process boundary; C1 waits for the 12-second native lifetime here."""
    command, startup, _, _ = prepare(tmp_path, controlled_launcher, scenario)
    command[command.index("-WaitSeconds") + 1] = "20"
    if scenario == "ready-long-java-only":
        command.append("-JavaOnlyDiagnostic")
    else:
        command = controlled_signature(command)
    started = time.monotonic()
    outer = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, stderr = outer.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        # Never kill the checker/log host/native process, including on regression.
        # Collect the original result after the controlled native natural exit.
        stdout, stderr = outer.communicate(timeout=25)
        pytest.fail("outer EOF remained held by the long-lived host/native process")
    assert time.monotonic() - started < 8
    assert not stderr, stderr.decode("utf-8", errors="replace")
    answer = json.loads(stdout.decode("utf-8"))
    assert answer["status"] == ("ready" if scenario == "ready-long-java-only" else "not_ready")
    assert outer.returncode == (0 if scenario == "ready-long-java-only" else 1)
    assert answer["process_host_stdio"] == "redirected_away_from_checker_outer_pipes"
    assert not (startup / "launcher-completion.json").exists()
    record = json.loads((startup / "launcher-process.json").read_text("utf-8"))
    # Both are actual live processes after the outer result and EOF were collected.
    for process_id in (record["process_host_pid"], record["launcher_pid"]):
        observed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {process_id}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=5,
        )
        assert str(process_id).encode() in observed.stdout
    deadline = time.monotonic() + 20
    while not (startup / "launcher-completion.json").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    completion = json.loads((startup / "launcher-completion.json").read_text("utf-8"))
    assert completion["processes_killed"] == []
    assert completion["exit_code"] == 0
    assert "native-log-after-checker-return" in (startup / "launcher.stdout.log").read_text()
    assert "native-error-after-checker-return" in (startup / "launcher.stderr.log").read_text()
