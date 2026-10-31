"""Bounded 13.4.1.0 policy profile; controlled files and SDK-free observations."""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

from tests import test_internal_unsigned_startup as fixture
from tests.test_owned_startup import PWSH, SCRIPT, assert_not_started

controlled_launcher = fixture.controlled_launcher
PROFILE = "creo-13.4.1.0-unsigned-native"
CATALOG_HASH = "61c54d38d025d416dc660f070b4634a6c603cbe11f71cc25a1fe395d2f73b649"


def profile_files(
    tmp_path,
    launcher,
    *,
    product="13.4.1.0",
    file="41,0,2026,163",
    catalog_hash=CATALOG_HASH,
    preflight=True,
):
    command, startup, state, installed, binding, data, preparation = fixture.internal_files(
        tmp_path, launcher
    )
    catalog = tmp_path / "Creo/Common Files/help/reference/pma/usascii/configoptions.pdf"
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b"CONTROLLED catalog observation fixture, never a vendor PDF")
    data["policy_profile"] = PROFILE
    data["configuration_catalog"] = {**fixture.identity(catalog), "sha256": catalog_hash}
    binding.write_text(json.dumps(data))
    args = fixture.internal_command(command, binding, preflight=preflight)
    # Native PE version and known PDF hash observations are controlled here. No
    # actual host, vendor document, license, registry or process is substituted.
    hook = r"""
function global:Get-Item {
  [CmdletBinding()]param([string]$LiteralPath,[switch]$Force)
  $item=Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -Force:$Force
  if($LiteralPath -eq $env:CREO_TEST_PROFILE_HOST){
    [pscustomobject]@{PSIsContainer=$item.PSIsContainer;Attributes=$item.Attributes;Length=$item.Length;
      VersionInfo=[pscustomobject]@{ProductVersion=$env:CREO_TEST_PROFILE_PRODUCT;FileVersion=$env:CREO_TEST_PROFILE_FILE}}
  } else {$item}
}
function global:Get-FileHash {
  [CmdletBinding()]param([string]$LiteralPath,[string]$Algorithm)
  if($LiteralPath -eq $env:CREO_TEST_PROFILE_CATALOG){
    [pscustomobject]@{Hash=$env:CREO_TEST_PROFILE_CATALOG_HASH}
  }
  else {Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm}
}
"""
    args[-1] = hook + args[-1]
    environment = {
        "CREO_TEST_PROFILE_HOST": str(tmp_path / "Creo/Common Files/x86e_win64/obj/xtop.exe"),
        "CREO_TEST_PROFILE_PRODUCT": product,
        "CREO_TEST_PROFILE_FILE": file,
        "CREO_TEST_PROFILE_CATALOG": str(catalog),
        "CREO_TEST_PROFILE_CATALOG_HASH": catalog_hash,
    }
    return args, environment, startup, state, installed, binding, data, preparation


def test_exact_profile_only_proposes_applicable_unsigned_option(tmp_path, controlled_launcher):
    args, environment, startup, state, *_ = profile_files(tmp_path, controlled_launcher)
    result = fixture.invoke(args, extra_env=environment)
    assert result.returncode == 0, result.stdout.decode() + result.stderr.decode()
    data = json.loads(result.stdout)
    assert data["proposed_policy"] == {"open_protk_unsigned_apps": "always"}
    qualified = data["internal_trial"]["policy_profile_qualification"]
    assert qualified["product_version"] == "13.4.1.0"
    assert qualified["file_version"] == "41,0,2026,163"
    assert qualified["configuration_catalog"]["sha256"] == CATALOG_HASH
    assert qualified["signed_apps_verified"] is False
    assert qualified["full_policy_option_set_verified"] is False
    assert "unsupported and unverified" in data["internal_trial"]["policy_scope"]
    assert not startup.exists() and not state.exists()


@pytest.mark.parametrize(
    "change", [{"product": "13.4.2.0"}, {"file": "41,0,2026,164"}, {"catalog_hash": "b" * 64}]
)
def test_other_version_or_catalog_cannot_use_bounded_profile(tmp_path, controlled_launcher, change):
    args, environment, startup, state, *_ = profile_files(tmp_path, controlled_launcher, **change)
    result = fixture.invoke(args, extra_env=environment)
    assert_not_started(result, startup, state, "internal_trial_binding_required")


def test_profile_does_not_accept_extra_native_application(tmp_path, controlled_launcher):
    args, environment, startup, state, installed, binding, data, _ = profile_files(
        tmp_path, controlled_launcher
    )
    registry = installed / "protk.dat"
    registry.write_text(
        registry.read_text() + "name extra\nstartup dll\nexec_file unknown.dll\nend\n"
    )
    data["registry"] = fixture.identity(registry)
    binding.write_text(json.dumps(data))
    # Rebind the changed test manifest; registry parsing must independently refuse it.
    # The controlled invocation embeds a prior expected binding hash. Replace that
    # exact 64-character value by locating its named entry, not disabling the check.
    args[-1] = re.sub(
        r"('ExpectedInternalTrialBindingSha256'=)'[a-f0-9]{64}'",
        r"\1'" + fixture.identity(binding)["sha256"] + "'",
        args[-1],
    )
    result = fixture.invoke(args, extra_env=environment)
    assert_not_started(result, startup, state, "internal_trial_isolation_unproven")


def test_exact_profile_writes_no_unsupported_signed_keyword(tmp_path, controlled_launcher):
    args, environment, startup, state, *_ = profile_files(
        tmp_path, controlled_launcher, preflight=False
    )
    result = fixture.invoke(args, extra_env=environment)
    assert result.returncode == 1 and result.stdout, result.stderr.decode()
    data = json.loads(result.stdout)
    assert data["status"] == "not_ready"
    assert data["native_load_verified"] is False
    assert data["session_readiness_attempts"] == 0
    assert (startup / "config.pro").read_text() == (
        "open_protk_unsigned_apps always\n"
        "last_session_directory_path ..\\runtime\\session-history\n"
        "last_session_retrieval yes\n"
    )


def observation(kind, status="recognized", raw="always", *, category=None, exception=None):
    return {
        "option": f"open_protk_{kind}_apps",
        "status": status,
        "raw": raw,
        "raw_truncated": False,
        "exception_category": category,
        "exception_class": exception,
    }


def response(status="unsupported_null", raw=None, *, category=None, exception=None):
    return {
        "deployment_policy": {
            "complete": False,
            "signed_apps": None,
            "unsigned_apps": "always",
            "signed_observation": observation(
                "signed", status, raw, category=category, exception=exception
            ),
            "unsigned_observation": observation("unsigned"),
            "source": (
                "BaseSession.GetConfigOption(open_protk_signed_apps/open_protk_unsigned_apps)"
            ),
        }
    }


def require_policy(data, *, requested="internal-unsigned-trial", profile=PROFILE):
    if not PWSH or os.name != "nt":
        pytest.skip("requires PowerShell on Windows")
    environment = dict(
        os.environ,
        CREO_PROFILE_SOURCE=str(SCRIPT),
        CREO_PROFILE_RESPONSE=json.dumps(data),
        CREO_PROFILE_REQUESTED=requested,
        CREO_PROFILE_NAME=profile,
    )
    command = r"""
$ErrorActionPreference='Stop';$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:CREO_PROFILE_SOURCE,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Invalid source'}
$function=$ast.Find({param($n)
  $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
  $n.Name -eq 'Require-EffectiveDeploymentPolicy'
},$true)
. ([scriptblock]::Create($function.Extent.Text))
try {
  $response=ConvertFrom-Json $env:CREO_PROFILE_RESPONSE
  $policyArgs=@{Response=$response;Requested=$env:CREO_PROFILE_REQUESTED;
    ExpectedUnsigned='prompt';PolicyProfile=$env:CREO_PROFILE_NAME}
  $value=Require-EffectiveDeploymentPolicy @policyArgs
  @{accepted=$true;value=$value}|ConvertTo-Json -Depth 10
} catch {@{accepted=$false;reason=$_.Exception.Message}|ConvertTo-Json -Depth 4}
"""
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "data",
    [
        response(),
        response("unsupported_empty", ""),
        response(
            "unsupported_not_found",
            None,
            category="XToolkitNotFound",
            exception="com.ptc.pfc.pfcExceptions.XToolkitNotFound",
        ),
    ],
)
def test_only_typed_null_empty_and_notfound_accept_applicable_policy(data):
    result = require_policy(data)
    assert result["accepted"] is True, result
    assert result["value"]["complete"] is False
    assert result["value"]["applicable_policy_verified"] is True
    assert result["value"]["signed_apps_verified"] is False
    assert result["value"]["full_policy_option_set_verified"] is False


@pytest.mark.parametrize(
    "data",
    [
        response("unrecognized", "unexpected"),
        response("read_failed", None, category="other_failure", exception="java.lang.Exception"),
        response("unsupported_null", "unexpected"),
        response("unsupported_empty", " "),
        response(
            "unsupported_not_found", None, category="other_failure", exception="java.lang.Exception"
        ),
        response("unsupported_null", None, exception="java.lang.Exception"),
    ],
)
def test_unrecognized_or_other_failed_signed_option_is_rejected(data):
    assert require_policy(data)["accepted"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", "false"),
        ("complete", True),
        ("unsigned_apps", "never"),
        ("unsigned_apps", None),
        ("signed_apps", "always"),
    ],
)
def test_profile_rejects_contradictory_or_untyped_fields(field, value):
    data = response()
    data["deployment_policy"][field] = value
    assert require_policy(data)["accepted"] is False


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("signed", "raw_truncated", True),
        ("signed", "raw_truncated", "false"),
        ("signed", "option", "other_option"),
        ("unsigned", "status", "read_failed"),
        ("unsigned", "raw", "unexpected"),
        ("unsigned", "exception_category", "other_failure"),
    ],
)
def test_incomplete_or_contradictory_option_observations_are_rejected(kind, field, value):
    data = response()
    data["deployment_policy"][kind + "_observation"][field] = value
    assert require_policy(data)["accepted"] is False


def test_missing_typed_observation_cannot_be_inferred_from_null_apps():
    data = response()
    del data["deployment_policy"]["signed_observation"]["exception_category"]
    assert require_policy(data)["accepted"] is False


@pytest.mark.parametrize(
    "requested,profile",
    [
        ("inherit", PROFILE),
        ("signed-only", PROFILE),
        ("internal-unsigned-trial", "all-options"),
        ("internal-unsigned-trial", "unknown"),
    ],
)
def test_other_modes_remain_strict_and_do_not_auto_select_profile(requested, profile):
    assert require_policy(response(), requested=requested, profile=profile)["accepted"] is False
