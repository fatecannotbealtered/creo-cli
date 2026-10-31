"""Explicit unsigned startup admission with controlled files/processes, never CAD."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from tests import test_owned_startup as startup_fixture
from tests.test_owned_startup import (
    assert_not_started,
    controlled_signature,
    prepare,
)

controlled_launcher = startup_fixture.controlled_launcher


def identity(path):
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def internal_files(tmp_path, controlled_launcher):
    command, startup, state, installed = prepare(tmp_path, controlled_launcher, "trust")
    for relative in (
        "applications/simulate/install/nt/pro_mech_env.bat",
        "x86e_win64/nms/nmsd.exe",
        "x86e_win64/obj/xtop.exe",
    ):
        hook = tmp_path / "Creo/Common Files" / relative
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_bytes(b"CONTROLLED vendor hook; never executed")
    (installed / "protk.dat").write_text(
        "name creo_cli_sketch\nstartup dll\nexec_file creo_cli_sketch.dll\n"
        f"text_dir {installed}\nallow_stop true\nfail_tol true\ndelay_start false\nend\n"
        "name creo_cli_service\nstartup otk_java\ntoolkit object\ncreo_type parametric\n"
        "java_app_class controlled.Service\njava_app_classpath creo-cli-service.jar\n"
        "java_app_start start\njava_app_stop stop\nallow_stop true\nfail_tol true\n"
        "delay_start false\nend\n",
        encoding="utf-8",
    )
    exe = tmp_path / "creo-cli.exe"
    exe.write_bytes(b"CONTROLLED CLI fixture; never executes")
    preparation = tmp_path / "ordinary-preparation.json"
    preparation.write_text(
        json.dumps(
            {
                "status": "ordinary_unlocked_internal_unsigned",
                "unlock_mode": "-c",
                "toolkit_unlocked": True,
                "authenticode_status": "NotSigned",
                "source_fingerprint": "c" * 64,
                "source_commit": "d" * 40,
                "dll": identity(installed / "creo_cli_sketch.dll"),
                "ordinary_unlock": {
                    "exit_code": 0,
                    "success_marker": "Successfully unlocked application.",
                },
            }
        ),
        encoding="utf-8",
    )
    binding = tmp_path / "internal-trial.json"
    data = {
        "schema_version": "1.0",
        "mode": "internal-unsigned-trial",
        "source_commit": "e" * 40,
        "component_source_sha256": "a" * 64,
        "native_source_fingerprint": "c" * 64,
        "files": {
            "creo-cli.exe": identity(exe),
            "creo-cli-service.jar": identity(installed / "creo-cli-service.jar"),
            "creo_cli_sketch.dll": identity(installed / "creo_cli_sketch.dll"),
        },
        "registry": identity(installed / "protk.dat"),
        "psf": identity(tmp_path / "Creo/Parametric/bin/parametric.psf"),
        "native_preparation": identity(preparation),
    }
    binding.write_text(json.dumps(data), encoding="utf-8")
    return command, startup, state, installed, binding, data, preparation


def internal_command(command, binding, *, preflight=True, signature_status="NotSigned"):
    args = [
        *command,
        "-InternalTrialBinding",
        str(binding),
        "-ExpectedInternalTrialBindingSha256",
        identity(binding)["sha256"],
    ]
    if preflight:
        args.append("-PreflightOnly")
    return controlled_signature(
        args,
        policy="internal-unsigned-trial",
        status=signature_status,
        signer=None,
        pin="",
    )


def invoke(command, **kwargs):
    environment = dict(os.environ)
    for key in (
        "PROTKDAT",
        "CREOTKDAT",
        "PRODEVDAT",
        "TOOLKIT_REGISTRY_FILE",
        "PRO_JAVA_CLASSPATH",
        "CLASSPATH",
        "JAVA_TOOL_OPTIONS",
        "_JAVA_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "PTC_CREO_ALT_SETTINGS_PATH",
        "PRO_DIRECTORY",
        "PRO_MACHINE_TYPE",
        "HOME",
    ):
        environment.pop(key, None)
    environment.update(kwargs.pop("extra_env", {}))
    return subprocess.run(command, env=environment, capture_output=True, timeout=15, **kwargs)


def test_internal_preflight_is_pinned_unsigned_and_read_only(tmp_path, controlled_launcher):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    result = invoke(internal_command(command, binding))
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
    answer = json.loads(result.stdout)
    assert answer["status"] == "preflight_passed_not_started"
    assert answer["process_started"] is False
    assert answer["native_signature"]["status"] == "NotSigned"
    assert answer["native_signature"]["authenticode_verified"] is False
    assert answer["native_signature"]["publisher_pin_matched"] is False
    assert answer["internal_trial"]["unlock_mode"] == "-c"
    assert answer["internal_isolation"]["complete"] is True
    assert answer["internal_trial"]["files"]["creo-cli.exe"]["sha256"]
    assert answer["proposed_policy"] == {
        "open_protk_signed_apps": "always",
        "open_protk_unsigned_apps": "always",
    }
    assert "all signed and unsigned" in answer["next_action"]
    assert answer["local_configuration_written"] is False
    assert not startup.exists() and not state.exists()


def test_internal_mode_still_requires_exact_binding(tmp_path, controlled_launcher):
    command, startup, state, _, _, _, _ = internal_files(tmp_path, controlled_launcher)
    result = invoke(
        controlled_signature(
            command, policy="internal-unsigned-trial", status="NotSigned", signer=None, pin=""
        )
    )
    assert_not_started(result, startup, state, "internal_trial_binding_required")


@pytest.mark.parametrize(
    "member",
    [
        "creo-cli.exe",
        "creo-cli-service.jar",
        "creo_cli_sketch.dll",
        "registry",
        "psf",
        "native_preparation",
    ],
)
def test_every_bound_input_is_checked_before_process(tmp_path, controlled_launcher, member):
    command, startup, state, _, binding, data, _ = internal_files(tmp_path, controlled_launcher)
    item = data[member] if member in data else data["files"][member]
    path = Path(item["path"])
    path.write_bytes(path.read_bytes() + b"tampered")
    result = invoke(internal_command(command, binding))
    # The longstanding component-manifest gate rejects JAR/DLL before the new gate.
    if member in ("creo-cli-service.jar", "creo_cli_sketch.dll"):
        assert result.returncode != 0 and not startup.exists() and not state.exists()
    else:
        assert_not_started(result, startup, state, "internal_trial_binding_required")


@pytest.mark.parametrize(
    "field,value",
    [
        ("unlock_mode", "-cd"),
        ("toolkit_unlocked", False),
        ("authenticode_status", "Valid"),
        ("status", "pending_authorized_external_authenticode_signing"),
    ],
)
def test_cd_or_unproven_unlock_is_never_admitted(tmp_path, controlled_launcher, field, value):
    command, startup, state, _, binding, data, preparation = internal_files(
        tmp_path, controlled_launcher
    )
    prepared = json.loads(preparation.read_text())
    prepared[field] = value
    preparation.write_text(json.dumps(prepared))
    data["native_preparation"] = identity(preparation)
    binding.write_text(json.dumps(data))
    result = invoke(internal_command(command, binding))
    assert_not_started(result, startup, state, "internal_trial_binding_required")


@pytest.mark.parametrize("status", ["Valid", "UnknownError", "HashMismatch", "NotTrusted"])
def test_internal_mode_requires_expected_notsigned_not_any_signature_state(
    tmp_path, controlled_launcher, status
):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    result = invoke(internal_command(command, binding, signature_status=status))
    assert_not_started(result, startup, state, "internal_trial_expected_unsigned_required")


@pytest.mark.parametrize(
    "location",
    [
        "Common Files/text/protk.dat",
        "Common Files/text/chinese_cn/creotk.dat",
        "Common Files/x86e_win64/text/usascii/prodev.dat",
    ],
)
def test_additional_registration_refuses_with_retained_source(
    tmp_path, controlled_launcher, location
):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    extra = tmp_path / "Creo" / location
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("name unknown_application\nstartup dll\nexec_file other.dll\nend\n")
    before = extra.read_bytes()
    result = invoke(internal_command(command, binding))
    answer = assert_not_started(result, startup, state, "internal_trial_isolation_unproven")
    assert answer["internal_isolation"]["complete"] is False
    assert extra.read_bytes() == before


@pytest.mark.parametrize(
    "directive", ["protkdat", "creotkdat", "prodevdat", "toolkit_registry_file"]
)
def test_external_registry_config_directives_are_refused(tmp_path, controlled_launcher, directive):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    external = tmp_path / "declared-login/config.pro"
    external.write_text(f"{directive} C:/unreviewed.dat\n")
    result = invoke(internal_command(command, binding))
    assert_not_started(result, startup, state, "internal_trial_isolation_unproven")


@pytest.mark.parametrize(
    "variable", ["PROTKDAT", "CLASSPATH", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "PRO_DIRECTORY"]
)
def test_inherited_registry_or_java_injection_is_refused(tmp_path, controlled_launcher, variable):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    result = invoke(internal_command(command, binding), extra_env={variable: "C:/unreviewed"})
    assert_not_started(result, startup, state, "internal_trial_isolation_unproven")


@pytest.mark.parametrize(
    "line",
    [
        'RUN="C:\\unreviewed.exe"',
        "ENV=CLASSPATH=C:\\unreviewed.jar",
        "ENV=PRO_DIRECTORY=C:\\unreviewed",
        "ENV=MECH_LP=C:\\unreviewed",
        "CREO_COMMON_FILES=unreviewed",
    ],
)
def test_psf_hooks_are_not_authorized_by_a_hash_alone(tmp_path, controlled_launcher, line):
    command, startup, state, _, binding, data, _ = internal_files(tmp_path, controlled_launcher)
    psf = Path(data["psf"]["path"])
    psf.write_text(psf.read_text() + "\n" + line + "\n")
    data["psf"] = identity(psf)
    binding.write_text(json.dumps(data))
    result = invoke(internal_command(command, binding))
    assert_not_started(result, startup, state, "internal_trial_isolation_unproven")


@pytest.mark.parametrize("location", ["text/config.sup", "x86e_win64/text/chinese_cn/config.sup"])
def test_internal_mode_respects_protected_policy(tmp_path, controlled_launcher, location):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    locked = tmp_path / "Creo/Common Files" / location
    locked.parent.mkdir(parents=True)
    locked.write_text("open_protk_unsigned_apps never\n")
    before = locked.read_bytes()
    result = invoke(internal_command(command, binding))
    assert_not_started(result, startup, state, "protected_configuration_conflict")
    assert locked.read_bytes() == before


def test_repinning_unknown_registry_application_does_not_authorize_it(
    tmp_path, controlled_launcher
):
    command, startup, state, installed, binding, data, _ = internal_files(
        tmp_path, controlled_launcher
    )
    registry = installed / "protk.dat"
    registry.write_text(
        registry.read_text() + "name extra\nstartup dll\nexec_file other.dll\nend\n"
    )
    data["registry"] = identity(registry)
    binding.write_text(json.dumps(data))
    result = invoke(internal_command(command, binding))
    assert_not_started(result, startup, state, "internal_trial_isolation_unproven")


@pytest.mark.parametrize(
    "changed",
    [
        "registry",
        "config",
        "launch-spec",
        "external-config",
        "extra-registry",
        "extra-protected-config",
    ],
)
def test_final_dispatch_rechecks_generated_files_and_external_sources(
    tmp_path, controlled_launcher, changed
):
    command, startup, _, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    target = {
        "registry": startup / "protk.dat",
        "config": startup / "config.pro",
        "launch-spec": startup / "process-launch-spec.json",
        "external-config": tmp_path / "declared-login/config.pro",
        "extra-registry": startup / "creotk.dat",
        "extra-protected-config": startup / "config.sup",
    }[changed]
    args = internal_command(command, binding, preflight=False)
    # A controlled hook changes a file after generation and before final dispatch.
    # It executes no native API and never touches the actual user configuration.
    hook = r"""
function global:Add-Type {
  [CmdletBinding()]param([string]$TypeDefinition)
  Microsoft.PowerShell.Utility\Add-Type -TypeDefinition $TypeDefinition
  [System.IO.File]::AppendAllText($env:CREO_TEST_CHANGED_STARTUP,'# controlled mutation')
}
"""
    args[-1] = hook + args[-1]
    result = invoke(args, extra_env={"CREO_TEST_CHANGED_STARTUP": str(target)})
    assert result.returncode == 1, result.stdout.decode() + result.stderr.decode()
    answer = json.loads(result.stdout)
    assert answer["status"] == "not_started"
    assert answer["failure"]["code"] == "internal_deployment_changed_before_launch"
    assert answer["process_started"] is False
    assert not (startup / "controlled-launch.txt").exists()
    assert not (startup / "launcher-process.json").exists()


def test_programdata_plugins_registration_is_also_audited(tmp_path, controlled_launcher):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    root = tmp_path / "program-data"
    registry = root / "PTC/Creo Toolkit 13/Plugins/extra/child/protk.dat"
    registry.parent.mkdir(parents=True)
    registry.write_text("name unknown\nstartup dll\nexec_file unknown.dll\nend\n")
    result = invoke(internal_command(command, binding), extra_env={"ProgramData": str(root)})
    answer = assert_not_started(result, startup, state, "internal_trial_isolation_unproven")
    assert any(
        item["path"] == str(registry) and item["active_entries"]
        for item in answer["internal_isolation"]["registries"]
    )


def test_standard_vendor_psf_hooks_are_recorded_without_expanding_authority(
    tmp_path, controlled_launcher
):
    command, startup, state, _, binding, data, _ = internal_files(tmp_path, controlled_launcher)
    psf = Path(data["psf"]["path"])
    psf.write_text(
        "ENV=MECH_LP=%PRO_DIRECTORY%\\applications\\simulate\n"
        'RUN="%MECH_LP%\\install\\nt\\pro_mech_env.bat"\n'
        'RUN="%PRO_DIRECTORY%\\%PRO_MACHINE_TYPE%\\nms\\nmsd.exe" '
        "-noservice -timeout %NMSD_TIMEOUT% &\n"
        'RUN="%PRO_DIRECTORY%\\%PRO_MACHINE_TYPE%\\obj\\xtop.exe"\n'
    )
    data["psf"] = identity(psf)
    binding.write_text(json.dumps(data))
    result = invoke(internal_command(command, binding))
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
    answer = json.loads(result.stdout)
    assert answer["internal_isolation"]["psf"] == identity(psf)
    assert not startup.exists() and not state.exists()


def test_internal_launch_writes_only_local_policy_and_does_not_accept_prompt(
    tmp_path, controlled_launcher
):
    command, startup, state, _, binding, _, _ = internal_files(tmp_path, controlled_launcher)
    result = invoke(internal_command(command, binding, preflight=False))
    assert result.returncode == 1, result.stdout.decode() + result.stderr.decode()
    answer = json.loads(result.stdout)
    assert answer["status"] == "not_ready"
    if answer.get("failure", {}).get("code") == "launcher_record_unknown":
        assert answer["failure"]["phase"] == "launcher_bootstrap"
        assert answer["native_process_identity"] == "unknown"
    elif "external_blocker" not in answer:
        assert answer["failure"]["phase"] == "startup_process_only"
        assert "deadline" in answer["failure"]["message"]
    else:
        assert answer["external_blocker"]["code"] == "external_trust_authorization_required"
    assert answer["qualification"] == "internal_unsigned_full_components_automatic_startup"
    assert answer["native_load_verified"] is False
    assert answer["session_readiness_attempts"] == 0
    assert (startup / "config.pro").read_text() == (
        "open_protk_signed_apps always\nopen_protk_unsigned_apps always\n"
        "last_session_directory_path ..\\runtime\\session-history\n"
        "last_session_retrieval yes\n"
    )
    assert (startup / "protk.dat").read_text().count("delay_start false") == 2
    assert not (state / "service-token").exists()
