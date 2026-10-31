"""Exact unsigned-native owned-exit admission; controlled files only, no CAD."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from creo_cli import owned_exit as ex
from creo_cli.core import Error
from tests.test_owned_session_exit import OP
from tests.test_owned_session_exit import world as _world_fixture

world = _world_fixture


def identity(path):
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def write_launch(world):
    world["path"].write_text(json.dumps(world["launch"]), encoding="utf-8")


def recovery_fixture(state):
    launch = state["launch"]
    runtime = state["runtime"]
    startup = state["path"].parent
    workflow, history = runtime / "wfroot", runtime / "session-history"
    workflow.mkdir()
    history.mkdir()
    declared = {
        "workflow_root": str(workflow),
        "last_session_directory_path": str(history),
        "configured_directory_value": os.path.relpath(history, startup),
        "recording": "yes",
        "new_paths_before_launch": True,
        "empty_before_dispatch": True,
        "previous_recovery_data_read_copied_removed": False,
        "configuration_sources": [],
    }
    actual = {
        "complete": True,
        "workflow_root": str(workflow),
        "last_session_directory_path": str(history),
        "last_session_retrieval": "yes",
        "workflow_root_source": "Java process environment inherited from owned Creo launcher",
        "configuration_source": (
            "BaseSession.GetConfigOptionValues(last_session_directory_path)"
            "/GetConfigOption(last_session_retrieval)"
        ),
        "last_session_directory_path_value_count": 1,
        "last_session_directory_path_readback": "observed",
        "last_session_retrieval_readback": "observed",
    }
    launch.update(
        recovery_isolation_verified=True,
        recovery_isolation=declared,
        recovery_configuration=actual,
        session_readiness_attempts=1,
        session_readiness={
            "ok": True,
            "session_reachable": True,
            "recovery_configuration": copy.deepcopy(actual),
        },
    )
    launch["deployment_preflight"]["recovery_isolation"] = copy.deepcopy(declared)
    launch["health"]["source_sha256"] = "b" * 64
    launch["recovery_window_observations"] = [
        {
            "phase": phase,
            "native_pid": launch["runtime_pin"]["native_pid"],
            "native_creation_filetime": "12345",
            "service_instance_id": launch["runtime_pin"]["service_instance_id"],
            "component_source_sha256": "b" * 64,
            "at_utc": f"2026-10-26T01:00:0{index}Z",
            "source": (
                "OS EnumWindows/GetWindowThreadProcessId; only exact owned native PID; read-only"
            ),
            "recovery_dialogs": [],
            "visible_windows_only": True,
            "desktop_input_count": 0,
            "CUA_input_count": 0,
        }
        for index, phase in enumerate(
            ("before_authenticated_readiness", "after_authenticated_readiness")
        )
    ]
    (startup / "protk.dat").write_bytes(b"CONTROLLED generated registry")
    (startup / "config.pro").write_text(
        f"last_session_directory_path {declared['configured_directory_value']}\n"
        "last_session_retrieval yes\n",
        encoding="utf-8",
    )
    (startup / "process-launch-spec.json").write_text(
        json.dumps(
            {
                "working_directory": str(startup),
                "environment": {"CREO_CLI_CONFIG_DIR": str(runtime), "PTC_WF_ROOT": str(workflow)},
            }
        ),
        encoding="utf-8",
    )
    launch["deployment_preflight"]["generated_startup_files"] = [
        identity(startup / name) for name in ("protk.dat", "config.pro", "process-launch-spec.json")
    ]


@pytest.fixture
def internal(world, monkeypatch):
    launch = world["launch"]
    workspace = world["path"].parent.parent
    creo = Path(launch["executable"]).parents[2]
    installation = Path(launch["installation"])
    native_host = creo / "Common Files/x86e_win64/obj/xtop.exe"
    catalog = creo / "Common Files/help/reference/pma/usascii/configoptions.pdf"
    for path, raw in (
        (native_host, b"CONTROLLED native host; never executes"),
        (catalog, b"CONTROLLED exact configuration catalog fixture"),
        (installation / "creo_cli_sketch.dll", b"CONTROLLED ordinary-unlocked DLL fixture"),
        (installation / "creo-cli-service.jar", b"CONTROLLED Java fixture"),
        (installation / "protk.dat", b"CONTROLLED two-application registry fixture"),
        (workspace / "creo-cli.exe", b"CONTROLLED client fixture; never executes"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(ex, "CONFIGURATION_CATALOG_SHA256", identity(catalog)["sha256"])
    preparation = workspace / "ordinary-preparation.json"
    preparation.write_text(
        json.dumps(
            {
                "status": "ordinary_unlocked_internal_unsigned",
                "unlock_mode": "-c",
                "toolkit_unlocked": True,
                "authenticode_status": "NotSigned",
                "ordinary_unlock": {
                    "exit_code": 0,
                    "success_marker": "Successfully unlocked application.",
                },
                "dll": identity(installation / "creo_cli_sketch.dll"),
            }
        ),
        encoding="utf-8",
    )
    profile = ex.UNSIGNED_NATIVE_PROFILE
    policy = {
        "complete": False,
        "signed_apps": None,
        "unsigned_apps": "always",
        "source": "BaseSession.GetConfigOption(open_protk_signed_apps/open_protk_unsigned_apps)",
        "policy_profile": profile,
        "applicable_policy_verified": True,
        "signed_apps_verified": False,
        "full_policy_option_set_verified": False,
        "signed_observation": {
            "option": "open_protk_signed_apps",
            "status": "unsupported_null",
            "raw": None,
            "raw_truncated": False,
            "exception_category": None,
            "exception_class": None,
        },
        "unsigned_observation": {
            "option": "open_protk_unsigned_apps",
            "status": "recognized",
            "raw": "Always",
            "raw_truncated": False,
            "exception_category": None,
            "exception_class": None,
        },
    }
    launch.update(
        deployment_policy_verified=False,
        applicable_policy_verified=True,
        signed_apps_verified=False,
        full_policy_option_set_verified=False,
        qualification="internal_unsigned_full_components_automatic_startup",
        effective_deployment_policy=policy,
        deployment_preflight={
            "trust_policy_requested": "internal-unsigned-trial",
            "internal_isolation": {"complete": True},
            "native_signature": {
                "path": str(installation / "creo_cli_sketch.dll"),
                "sha256": identity(installation / "creo_cli_sketch.dll")["sha256"],
                "status": "NotSigned",
                "signature_type": "None",
                "authenticode_verified": False,
                "publisher_pin_matched": False,
                "signer_thumbprint": None,
                "signer_subject": None,
                "timestamp_present": False,
            },
            "internal_trial": {
                "policy_profile": profile,
                "unlock_mode": "-c",
                "toolkit_unlocked": True,
                "authenticode_verified": False,
                "native_preparation": identity(preparation),
                "files": {
                    "creo-cli.exe": identity(workspace / "creo-cli.exe"),
                    "creo-cli-service.jar": identity(installation / "creo-cli-service.jar"),
                    "creo_cli_sketch.dll": identity(installation / "creo_cli_sketch.dll"),
                },
                "registry": identity(installation / "protk.dat"),
                "policy_profile_qualification": {
                    "profile": profile,
                    "product_version": "13.4.1.0",
                    "file_version": "41,0,2026,163",
                    "native_host": identity(native_host),
                    "configuration_catalog": identity(catalog),
                    "applicable_configuration": {"open_protk_unsigned_apps": "always"},
                    "signed_apps_verified": False,
                    "full_policy_option_set_verified": False,
                },
            },
        },
    )
    recovery_fixture(world)
    write_launch(world)
    return world


def path_set(value, path, replacement):
    parts = path.split("/")
    for key in parts[:-1]:
        value = value[key]
    value[parts[-1]] = replacement


@pytest.mark.parametrize(
    "signed_status", ["unsupported_null", "unsupported_empty", "unsupported_not_found"]
)
def test_precise_internal_profile_can_use_original_complete_exit_guards(internal, signed_status):
    signed = internal["launch"]["effective_deployment_policy"]["signed_observation"]
    signed["status"] = signed_status
    if signed_status == "unsupported_empty":
        signed["raw"] = ""
    elif signed_status == "unsupported_not_found":
        signed.update(
            exception_category="XToolkitNotFound",
            exception_class="com.ptc.pfc.pfcExceptions.XToolkitNotFound",
        )
    write_launch(internal)
    pre = ex.prepare(internal["opts"])
    assert pre["policy_evidence"]["policy_profile"] == ex.UNSIGNED_NATIVE_PROFILE
    client = internal["client"]
    plan = ex.plan(client, internal["opts"], pre)
    assert plan.binding["deployment_policy_evidence"] == pre["policy_evidence"]
    plan.prepare_dispatch({"operation_id": OP})
    data = plan.apply(client, {"operation_id": OP})
    _, verification = plan.verify(client, data)
    assert all(item["passed"] for item in verification["checks"])
    assert [name for name, _ in client.calls] == ["session.exit-state", "session.exit"]


@pytest.mark.parametrize(
    "path,value",
    [
        ("deployment_policy_verified", True),
        ("applicable_policy_verified", False),
        ("applicable_policy_verified", 1),
        ("signed_apps_verified", True),
        ("full_policy_option_set_verified", True),
        ("deployment_preflight/trust_policy_requested", "inherit"),
        ("deployment_preflight/internal_isolation/complete", False),
        ("deployment_preflight/internal_isolation/complete", 1),
        ("deployment_preflight/internal_trial/policy_profile", "all-options"),
        ("deployment_preflight/internal_trial/unlock_mode", "-cd"),
        ("deployment_preflight/internal_trial/toolkit_unlocked", False),
        ("deployment_preflight/internal_trial/authenticode_verified", True),
        (
            "deployment_preflight/internal_trial/policy_profile_qualification/product_version",
            "13.4.0.0",
        ),
        (
            "deployment_preflight/internal_trial/policy_profile_qualification/file_version",
            "41,0,2026,162",
        ),
        (
            "deployment_preflight/internal_trial/policy_profile_qualification/configuration_catalog/sha256",
            "a" * 64,
        ),
        ("deployment_preflight/native_signature/status", "Valid"),
        ("deployment_preflight/native_signature/authenticode_verified", True),
        ("deployment_preflight/native_signature/sha256", "a" * 64),
        ("deployment_preflight/native_signature/signer_thumbprint", "a" * 40),
        ("effective_deployment_policy/complete", True),
        ("effective_deployment_policy/complete", 0),
        ("effective_deployment_policy/signed_apps", "always"),
        ("effective_deployment_policy/unsigned_apps", "prompt"),
        ("effective_deployment_policy/policy_profile", "other"),
        ("effective_deployment_policy/source", "config.pro statement only"),
        ("effective_deployment_policy/signed_observation/status", "unrecognized"),
        ("effective_deployment_policy/signed_observation/status", "read_failed"),
        ("effective_deployment_policy/signed_observation/raw", "yes"),
        ("effective_deployment_policy/signed_observation/exception_category", "other_failure"),
        ("effective_deployment_policy/signed_observation/raw_truncated", True),
        ("effective_deployment_policy/signed_observation/raw_truncated", 0),
        ("effective_deployment_policy/unsigned_observation/status", "unsupported_empty"),
        ("effective_deployment_policy/unsigned_observation/raw", "yes"),
        ("effective_deployment_policy/unsigned_observation/raw", "never"),
        ("effective_deployment_policy/unsigned_observation/exception_class", "ReadFailed"),
        ("effective_deployment_policy/unsigned_observation/raw_truncated", True),
    ],
)
def test_boolean_applicability_cannot_substitute_for_complete_scoped_evidence(
    internal, path, value
):
    path_set(internal["launch"], path, value)
    write_launch(internal)
    with pytest.raises(Error) as error:
        ex.prepare(internal["opts"])
    assert error.value.code == "E_FORBIDDEN"
    assert error.value.details["dispatch_state"] == "not_started"
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "path",
    [
        "applicable_policy_verified",
        "signed_apps_verified",
        "deployment_preflight/internal_isolation",
        "deployment_preflight/internal_trial/policy_profile_qualification",
        "effective_deployment_policy/signed_observation/raw",
        "effective_deployment_policy/unsigned_observation/exception_class",
    ],
)
def test_missing_scoped_evidence_is_not_implicitly_filled(internal, path):
    parts = path.split("/")
    target = internal["launch"]
    for part in parts[:-1]:
        target = target[part]
    del target[parts[-1]]
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "file_key",
    [
        "catalog",
        "native_host",
        "creo-cli.exe",
        "creo-cli-service.jar",
        "creo_cli_sketch.dll",
        "registry",
        "native_preparation",
    ],
)
def test_scoped_files_are_rehashed_at_preparation(internal, file_key):
    trial = internal["launch"]["deployment_preflight"]["internal_trial"]
    expected = (
        trial["policy_profile_qualification"][
            "configuration_catalog" if file_key == "catalog" else "native_host"
        ]
        if file_key in ("catalog", "native_host")
        else trial["files"].get(file_key, trial.get(file_key))
    )
    path = Path(expected["path"])
    path.write_bytes(path.read_bytes() + b"CHANGED")
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


def padded_preparation(internal, size, *, unlock_mode="-c"):
    trial = internal["launch"]["deployment_preflight"]["internal_trial"]
    path = Path(trial["native_preparation"]["path"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["unlock_mode"] = unlock_mode
    data["build_transcript"] = ""
    overhead = len(json.dumps(data).encode("utf-8"))
    assert size >= overhead
    data["build_transcript"] = "x" * (size - overhead)
    raw = json.dumps(data).encode("utf-8")
    assert len(raw) == size
    path.write_bytes(raw)
    trial["native_preparation"] = identity(path)
    write_launch(internal)
    return path


@pytest.mark.parametrize("size", [4_074_092, ex.MAX_NATIVE_PREPARATION_BYTES])
def test_complete_native_preparation_within_bound_is_accepted(internal, size):
    path = padded_preparation(internal, size)
    pre = ex.prepare(internal["opts"])
    assert pre["policy_evidence"]["files"]["native_preparation"] == identity(path)
    assert not internal["client"].calls


def test_oversized_native_preparation_is_rejected(internal):
    padded_preparation(internal, ex.MAX_NATIVE_PREPARATION_BYTES + 1)
    with pytest.raises(Error) as error:
        ex.prepare(internal["opts"])
    assert error.value.code == "E_FORBIDDEN"
    assert not internal["client"].calls


def test_oversized_actual_preparation_is_not_opened_even_with_small_declared_size(
    internal, monkeypatch
):
    path = padded_preparation(internal, ex.MAX_NATIVE_PREPARATION_BYTES + 1)
    trial = internal["launch"]["deployment_preflight"]["internal_trial"]
    trial["native_preparation"]["bytes"] = ex.MAX_NATIVE_PREPARATION_BYTES
    write_launch(internal)
    original_open = Path.open

    def checked_open(self, *args, **kwargs):
        assert self != path, "an oversized preparation must not be read"
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    with pytest.raises(Error) as error:
        ex.prepare(internal["opts"])
    assert error.value.code == "E_FORBIDDEN"
    assert not internal["client"].calls


def test_large_preparation_still_requires_exact_digest(internal):
    path = padded_preparation(internal, 4_074_092)
    raw = bytearray(path.read_bytes())
    index = raw.index(b"xxxx")
    raw[index] = ord("y")
    path.write_bytes(raw)
    with pytest.raises(Error) as error:
        ex.prepare(internal["opts"])
    assert error.value.code == "E_FORBIDDEN"
    assert not internal["client"].calls


def test_repinned_large_signing_input_still_cannot_authorize_exit(internal):
    padded_preparation(internal, 4_074_092, unlock_mode="-cd")
    with pytest.raises(Error) as error:
        ex.prepare(internal["opts"])
    assert error.value.code == "E_FORBIDDEN"
    assert not internal["client"].calls


def test_scoped_evidence_stays_bound_until_exit_dispatch(internal):
    pre = ex.prepare(internal["opts"])
    client = internal["client"]
    plan = ex.plan(client, internal["opts"], pre)
    Path(pre["policy_evidence"]["files"]["creo_cli_sketch.dll"]["path"]).write_bytes(b"CHANGED")
    with pytest.raises(Error) as error:
        plan.prepare_dispatch({"operation_id": OP})
    assert error.value.code == "E_CONFLICT"
    assert error.value.details["dispatch_state"] == "not_started"
    assert [name for name, _ in client.calls] == ["session.exit-state"]
    assert not list(internal["runtime"].glob("owned-exit-*"))


@pytest.mark.parametrize(
    "path,value",
    [
        ("unlock_mode", "-cd"),
        ("status", "pending_authorized_external_authenticode_signing"),
        ("toolkit_unlocked", False),
        ("authenticode_status", "Valid"),
        ("ordinary_unlock/exit_code", True),
        ("ordinary_unlock/success_marker", "No license available"),
        ("dll/sha256", "a" * 64),
        ("dll/bytes", True),
    ],
)
def test_repinning_invalid_preparation_does_not_authorize_exit(internal, path, value):
    trial = internal["launch"]["deployment_preflight"]["internal_trial"]
    preparation = Path(trial["native_preparation"]["path"])
    data = json.loads(preparation.read_text(encoding="utf-8"))
    path_set(data, path, value)
    preparation.write_text(json.dumps(data), encoding="utf-8")
    trial["native_preparation"] = identity(preparation)
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "case", ["catalog_path", "native_host_path", "extra_dll", "not_found_error"]
)
def test_matching_hash_or_unsupported_label_does_not_expand_the_profile(internal, case):
    trial = internal["launch"]["deployment_preflight"]["internal_trial"]
    if case in ("catalog_path", "native_host_path"):
        key = "configuration_catalog" if case == "catalog_path" else "native_host"
        original = Path(trial["policy_profile_qualification"][key]["path"])
        alternate = internal["path"].parent.parent / original.name
        alternate.write_bytes(original.read_bytes())
        trial["policy_profile_qualification"][key] = identity(alternate)
    elif case == "extra_dll":
        trial["files"]["unknown.dll"] = copy.deepcopy(trial["files"]["creo_cli_sketch.dll"])
    else:
        internal["launch"]["effective_deployment_policy"]["signed_observation"].update(
            status="unsupported_not_found",
            exception_category="other_failure",
            exception_class="Unknown",
        )
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize("case", ["nonempty", "unresolved", "unowned"])
def test_internal_profile_retains_existing_raw_empty_sticky_and_ownership_gates(
    internal, monkeypatch, case
):
    if case == "nonempty":
        internal["client"].state = copy.deepcopy(internal["client"].state) | {"raw_model_count": 1}
    elif case == "unresolved":
        monkeypatch.setattr(
            ex.operations, "selected_runs", lambda **kwargs: [{"status": "unknown"}]
        )
    else:
        internal["launch"]["ownership"] = "attached"
        write_launch(internal)
    with pytest.raises(Error):
        ex.plan(internal["client"], internal["opts"], ex.prepare(internal["opts"]))
    assert not any(name == "session.exit" for name, _ in internal["client"].calls)


@pytest.mark.parametrize(
    "path,value",
    [
        ("recovery_isolation_verified", False),
        ("recovery_isolation_verified", 1),
        ("recovery_isolation/new_paths_before_launch", False),
        ("recovery_isolation/previous_recovery_data_read_copied_removed", True),
        ("recovery_isolation/recording", "no"),
        ("session_readiness_attempts", 2),
        ("session_readiness/ok", False),
        ("recovery_configuration/complete", False),
        ("recovery_configuration/complete", 1),
        ("recovery_configuration/last_session_retrieval", "no"),
        ("recovery_configuration/last_session_directory_path_value_count", 0),
        ("recovery_configuration/last_session_directory_path_value_count", 2),
        ("recovery_configuration/last_session_directory_path_value_count", True),
        ("recovery_configuration/last_session_directory_path_readback", "failed"),
        ("recovery_configuration/last_session_retrieval_readback", "unavailable_or_oversized"),
        ("recovery_configuration/last_session_retrieval_error_class", "XToolkitGeneralError"),
        ("recovery_configuration/workflow_root_source", "guessed file setting"),
        ("recovery_configuration/configuration_source", "file only"),
    ],
)
def test_internal_exit_requires_complete_actual_recovery_isolation(internal, path, value):
    path_set(internal["launch"], path, value)
    if path.startswith("recovery_isolation/"):
        internal["launch"]["deployment_preflight"]["recovery_isolation"] = copy.deepcopy(
            internal["launch"]["recovery_isolation"]
        )
    if path.startswith("recovery_configuration/"):
        internal["launch"]["session_readiness"]["recovery_configuration"] = copy.deepcopy(
            internal["launch"]["recovery_configuration"]
        )
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize("value", ["missing", False, 1])
def test_empty_before_dispatch_proof_is_mandatory_and_typed(internal, value):
    declared = internal["launch"]["recovery_isolation"]
    if value == "missing":
        del declared["empty_before_dispatch"]
    else:
        declared["empty_before_dispatch"] = value
    internal["launch"]["deployment_preflight"]["recovery_isolation"] = copy.deepcopy(declared)
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize("where", ["declaration", "native", "child-spec"])
def test_internal_exit_refuses_foreign_recovery_roots_even_with_consistent_records(internal, where):
    launch = internal["launch"]
    alternate = internal["path"].parent.parent / "foreign-root"
    alternate.mkdir()
    if where == "declaration":
        launch["recovery_isolation"]["workflow_root"] = str(alternate)
        launch["deployment_preflight"]["recovery_isolation"] = copy.deepcopy(
            launch["recovery_isolation"]
        )
    elif where == "native":
        launch["recovery_configuration"]["last_session_directory_path"] = str(alternate)
        launch["session_readiness"]["recovery_configuration"] = copy.deepcopy(
            launch["recovery_configuration"]
        )
    else:
        spec = internal["path"].parent / "process-launch-spec.json"
        raw = json.loads(spec.read_text(encoding="utf-8"))
        raw["environment"]["PTC_WF_ROOT"] = str(alternate)
        spec.write_text(json.dumps(raw), encoding="utf-8")
        launch["deployment_preflight"]["generated_startup_files"][2] = identity(spec)
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "after_authenticated_readiness"),
        ("native_pid", 999),
        ("native_pid", True),
        ("native_creation_filetime", "10000"),
        ("native_creation_filetime", 12345),
        ("service_instance_id", "foreign"),
        ("component_source_sha256", "c" * 64),
        ("at_utc", "2026-10-26T01:00:00"),
        ("at_utc", None),
        ("source", "observed another seat"),
        ("recovery_dialogs", ["Retrieval"]),
        ("visible_windows_only", False),
        ("desktop_input_count", 1),
        ("CUA_input_count", False),
    ],
)
def test_owned_recovery_dialog_veto_requires_same_generation_and_typed_os_evidence(
    internal, field, value
):
    internal["launch"]["recovery_window_observations"][0][field] = value
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "reversed_time",
        "missing_raw",
        "raw_type_mismatch",
        "declaration_type_mismatch",
        "empty_type_mismatch",
    ],
)
def test_recovery_stage_and_same_observation_snapshots_cannot_be_reconstructed(internal, case):
    launch = internal["launch"]
    if case == "missing":
        launch["recovery_window_observations"].pop()
    elif case == "reversed_time":
        launch["recovery_window_observations"][1]["at_utc"] = "2026-10-26T00:59:59Z"
    elif case == "missing_raw":
        del launch["session_readiness"]["recovery_configuration"]
    elif case == "raw_type_mismatch":
        launch["session_readiness"]["recovery_configuration"]["complete"] = 1
    elif case == "declaration_type_mismatch":
        launch["deployment_preflight"]["recovery_isolation"]["new_paths_before_launch"] = 1
    else:
        launch["deployment_preflight"]["recovery_isolation"]["empty_before_dispatch"] = 1
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize("changed", ["workflow-directory", "config", "spec"])
def test_recovery_proof_is_rechecked_before_exit_intent(internal, changed):
    pre = ex.prepare(internal["opts"])
    client = internal["client"]
    plan = ex.plan(client, internal["opts"], pre)
    if changed == "workflow-directory":
        root = Path(internal["launch"]["recovery_isolation"]["workflow_root"])
        root.rmdir()
        root.write_bytes(b"CHANGED directory to file")
    else:
        path = internal["path"].parent / (
            "config.pro" if changed == "config" else "process-launch-spec.json"
        )
        path.write_bytes(path.read_bytes() + b"CHANGED")
    with pytest.raises(Error) as error:
        plan.prepare_dispatch({"operation_id": OP})
    assert error.value.code == "E_CONFLICT"
    assert not list(internal["runtime"].glob("owned-exit-*"))
    assert [name for name, _ in client.calls] == ["session.exit-state"]


def test_volatile_recovery_contents_are_not_hashed_or_treated_as_configuration_drift(internal):
    pre = ex.prepare(internal["opts"])
    plan = ex.plan(internal["client"], internal["opts"], pre)
    Path(internal["launch"]["recovery_isolation"]["workflow_root"], "new-cache-file").write_bytes(
        b"NATIVE cache change"
    )
    Path(
        internal["launch"]["recovery_isolation"]["last_session_directory_path"], "new-history-file"
    ).write_bytes(b"NATIVE history change")
    plan.prepare_dispatch({"operation_id": OP})
    assert pre["policy_evidence"]["recovery_evidence"]["directory_contents_hashed"] is False
    assert pre["policy_evidence"]["recovery_evidence"]["empty_before_dispatch"] is True


def test_quoted_native_directory_scalar_is_not_reinterpreted_as_an_actual_native_path(internal):
    launch = internal["launch"]
    launch["recovery_configuration"]["last_session_directory_path"] = (
        '"' + launch["recovery_configuration"]["last_session_directory_path"] + '"'
    )
    launch["session_readiness"]["recovery_configuration"] = copy.deepcopy(
        launch["recovery_configuration"]
    )
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "case", ["missing", "absolute", "quoted", "noncanonical", "space", "colon", "bang", "hash"]
)
def test_relative_recovery_configuration_value_is_exactly_the_owned_startup_relative_path(
    internal, case
):
    declared = internal["launch"]["recovery_isolation"]
    original = declared["configured_directory_value"]
    if case == "missing":
        del declared["configured_directory_value"]
    else:
        declared["configured_directory_value"] = {
            "absolute": declared["last_session_directory_path"],
            "quoted": '"' + original + '"',
            "noncanonical": "." + os.sep + original,
            "space": original + " extra",
            "colon": original + ":extra",
            "bang": original + "!extra",
            "hash": original + "#extra",
        }[case]
    internal["launch"]["deployment_preflight"]["recovery_isolation"] = copy.deepcopy(declared)
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize(
    "case",
    [
        "quoted-relative",
        "quoted-absolute",
        "duplicate",
        "comment",
        "missing-recording",
        "recording-no",
    ],
)
def test_repinning_configuration_bytes_cannot_hide_wrong_or_quoted_recovery_lines(internal, case):
    launch = internal["launch"]
    declared = launch["recovery_isolation"]
    value = declared["configured_directory_value"]
    if case == "quoted-relative":
        path_line = 'last_session_directory_path "' + value + '"'
    elif case == "quoted-absolute":
        path_line = 'last_session_directory_path "' + declared["last_session_directory_path"] + '"'
    elif case == "duplicate":
        path_line = f"last_session_directory_path {value}\nlast_session_directory_path {value}"
    elif case == "comment":
        path_line = "last_session_directory_path " + value + " !extra"
    else:
        path_line = "last_session_directory_path " + value
    recording = (
        ""
        if case == "missing-recording"
        else "last_session_retrieval " + ("no" if case == "recording-no" else "yes")
    )
    config = internal["path"].parent / "config.pro"
    config.write_text(path_line + "\n" + recording + "\n", encoding="utf-8")
    generated = launch["deployment_preflight"]["generated_startup_files"]
    generated[:] = [
        identity(config) if Path(item["path"]).name == "config.pro" else item for item in generated
    ]
    write_launch(internal)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


@pytest.mark.parametrize("case", ["relative", "embedded-quoted-prefix"])
def test_native_recovery_path_is_never_guessed_from_caller_working_directory(
    internal, monkeypatch, case
):
    launch = internal["launch"]
    value = (
        launch["recovery_isolation"]["configured_directory_value"]
        if case == "relative"
        else str(internal["path"].parent)
        + '\\"'
        + launch["recovery_isolation"]["last_session_directory_path"]
        + '"'
    )
    launch["recovery_configuration"]["last_session_directory_path"] = value
    launch["session_readiness"]["recovery_configuration"] = copy.deepcopy(
        launch["recovery_configuration"]
    )
    write_launch(internal)
    monkeypatch.chdir(internal["path"].parent)
    with pytest.raises(Error):
        ex.prepare(internal["opts"])
    assert not internal["client"].calls


def test_relative_config_line_and_genuine_canonical_native_path_accept_utf8_bom(internal):
    launch = internal["launch"]
    history = Path(launch["recovery_isolation"]["last_session_directory_path"])
    launch["recovery_configuration"]["last_session_directory_path"] = str(
        history / ".." / history.name
    )
    launch["session_readiness"]["recovery_configuration"] = copy.deepcopy(
        launch["recovery_configuration"]
    )
    config = internal["path"].parent / "config.pro"
    config.write_bytes(b"\xef\xbb\xbf" + config.read_bytes())
    generated = launch["deployment_preflight"]["generated_startup_files"]
    generated[:] = [
        identity(config) if Path(item["path"]).name == "config.pro" else item for item in generated
    ]
    write_launch(internal)
    proof = ex.prepare(internal["opts"])["policy_evidence"]["recovery_evidence"]
    assert proof["configured_directory_value"] == os.path.relpath(history, internal["path"].parent)
    assert proof["empty_before_dispatch"] is True
