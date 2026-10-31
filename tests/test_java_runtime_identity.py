"""Independent Java-only process/JAR evidence never qualifies the native backend."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from creo_cli import deployment, runtime_identity
from tests.test_commands import Base


@pytest.fixture
def java_evidence(tmp_path):
    host = tmp_path / "Creo/Common Files/x86e_win64/obj/xtop.exe"
    java = tmp_path / "JDK/bin/java.exe"
    jar = tmp_path / "components/creo-cli-service.jar"
    for path in (host, java, jar):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"controlled fixture, never executed")
    rows = [
        {
            "pid": 10,
            "parent_pid": 5,
            "creation_filetime": "134358400000000000",
            "actual_image": str(host),
            "actual_process_machine": "0x8664",
        },
        {
            "pid": 20,
            "parent_pid": 10,
            "creation_filetime": "134358400010000000",
            "actual_image": str(java),
            "actual_process_machine": "0x8664",
        },
    ]
    generation = "93d93317-e5bb-4beb-a3c7-1d4b0480b1d6"
    return {
        "health": {
            "ok": True,
            "service": "creo-cli",
            "protocol": 2,
            "runtime_class": "controlled.Service",
            "source_sha256": "a" * 64,
            "service_instance_id": generation,
            "process_id": 20,
            "process_started_at": datetime.fromtimestamp(
                (134358400010000000 - 116444736000000000) / 1e7, UTC
            ).isoformat(),
        },
        "before": rows,
        "after": deepcopy(rows),
        "pin": {
            "java_pid": 20,
            "native_pid": 10,
            "chain": [20, 10],
            "process_creations": {
                "10": rows[0]["creation_filetime"],
                "20": rows[1]["creation_filetime"],
            },
            "service_instance_id": generation,
        },
        "expected": {
            "source_sha256": "a" * 64,
            "java_app_class": "controlled.Service",
            "java_path": str(java),
            "host_path": str(host),
            "jar": {"path": str(jar), "sha256": "jar-hash"},
        },
        "open_jars": [str(jar)],
        "sha": lambda _: "jar-hash",
    }


def test_strict_java_only_identity_requires_no_dll_claim(java_evidence):
    result = runtime_identity.validate_java_candidate(**java_evidence)
    assert result["passed"]
    assert result["profile"] == "java_component_only"
    assert result["native_dll_verified"] is False
    assert result["full_engineering_qualified"] is False
    assert result["jar_binding"] == "current_open_handle"


@pytest.mark.parametrize("where", ("before", "after"))
@pytest.mark.parametrize(
    "change",
    (
        "java_pid_reuse",
        "host_pid_reuse",
        "wrong_parent",
        "wrong_path",
        "wrong_arch",
        "missing",
        "duplicate",
    ),
)
def test_java_only_refuses_os_identity_drift(java_evidence, where, change):
    rows = java_evidence[where]
    if change == "java_pid_reuse":
        rows[1]["creation_filetime"] = "134358400020000000"
    elif change == "host_pid_reuse":
        rows[0]["creation_filetime"] = "134358400030000000"
    elif change == "wrong_parent":
        rows[1]["parent_pid"] = 99
    elif change == "wrong_path":
        rows[1]["actual_image"] = str(Path(rows[1]["actual_image"]).with_name("other.exe"))
    elif change == "wrong_arch":
        rows[0]["actual_process_machine"] = "0x14c"
    elif change == "missing":
        rows.pop()
    else:
        rows.append(deepcopy(rows[1]))
    assert runtime_identity.validate_java_candidate(**java_evidence)["passed"] is False


@pytest.mark.parametrize(
    "field,value",
    (
        ("runtime_class", "wrong.Service"),
        ("source_sha256", "b" * 64),
        ("service_instance_id", "different"),
        ("process_id", True),
        ("process_started_at", None),
        ("protocol", 1),
    ),
)
def test_java_only_refuses_wrong_handshake(java_evidence, field, value):
    java_evidence["health"][field] = value
    assert runtime_identity.validate_java_candidate(**java_evidence)["passed"] is False


@pytest.mark.parametrize("kind", ("closed", "wrong_path", "wrong_sha", "hash_denied"))
def test_java_current_jar_handle_and_backing_hash_are_mandatory(java_evidence, kind):
    if kind == "closed":
        java_evidence["open_jars"] = []
    elif kind == "wrong_path":
        java_evidence["open_jars"] = [
            str(Path(java_evidence["open_jars"][0]).with_name("other.jar"))
        ]
    elif kind == "wrong_sha":
        java_evidence["sha"] = lambda _: "wrong"
    else:
        java_evidence["sha"] = Mock(side_effect=PermissionError("controlled denial"))
    assert runtime_identity.validate_java_candidate(**java_evidence)["passed"] is False


def test_java_profile_cannot_accept_a_retained_full_load_anchor(java_evidence):
    with pytest.raises(TypeError):
        runtime_identity.validate_java_candidate(
            **java_evidence, verified_load={"identity": {"passed": True}}
        )


def inspect_java_only(java_evidence, tmp_path, *, jars=None):
    expected = java_evidence["expected"]
    target = Path(expected["jar"]["path"]).parent
    manifest = {
        "files": {
            "creo-cli-service.jar": {"sha256": "jar-hash"},
            "creo_cli_sketch.dll": {"sha256": "dll-hash"},
        },
        "java_app_class": expected["java_app_class"],
        "component_source_sha256": expected["source_sha256"],
        "runtime_profile": {"mode": "environment"},
    }
    health = java_evidence["health"] | {
        "runtime_configuration_contract": 1,
        "runtime_configuration": {
            "portable_profile": True,
            "state_directory": str(tmp_path / "runtime"),
        },
    }
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.health.return_value = health
    with (
        patch.object(
            deployment, "files", return_value=(target, manifest, {"files": manifest["files"]})
        ),
        patch.object(deployment, "Client", return_value=client),
        patch.object(
            runtime_identity,
            "processes",
            side_effect=[java_evidence["before"], java_evidence["after"]],
        ),
        patch.object(
            runtime_identity,
            "open_jars",
            return_value=java_evidence["open_jars"] if jars is None else jars,
        ),
        patch.object(runtime_identity, "modules") as modules,
        patch.object(runtime_identity, "validate_candidate") as full,
        patch.object(deployment.service_bundle, "sha256", side_effect=java_evidence["sha"]),
    ):
        result = deployment.inspect(
            target,
            creo=Path(expected["host_path"]).parents[3],
            java_home=Path(expected["java_path"]).parents[1],
        )
    modules.assert_not_called()
    full.assert_not_called()
    client.op.assert_not_called()
    return result


def test_missing_native_witness_keeps_independent_java_evidence_and_whole_gate_false(
    java_evidence, tmp_path
):
    result = inspect_java_only(java_evidence, tmp_path)
    assert result["files_verified"] is True
    assert result["java_loaded_verified"] is True
    assert result["loaded_verified"] is False
    assert result["native_loaded_verified"] is False
    assert result["diagnostic"]["kind"] == "native_witness_absent"
    assert result["diagnostic"]["module_inventory_observed"] is False
    assert result["java_runtime_identity"]["jar_binding"] == "current_open_handle"
    assert "JavaOnlyDiagnostic" in result["next_action"]


def test_missing_current_jar_handle_remains_unverified_without_native_witness(
    java_evidence, tmp_path
):
    result = inspect_java_only(java_evidence, tmp_path, jars=[])
    assert result["java_loaded_verified"] is False
    assert result["loaded_verified"] is False
    assert result["native_loaded_verified"] is False
    assert any(
        "current open handle" in error for error in result["java_runtime_identity"]["errors"]
    )


def test_full_gate_and_its_original_same_generation_anchor_remain_unchanged(
    java_evidence, tmp_path, monkeypatch
):
    expected = java_evidence["expected"]
    target = Path(expected["jar"]["path"]).parent
    native = target / "creo_cli_sketch.dll"
    native.write_bytes(b"controlled native fixture, never loaded")
    state = tmp_path / "runtime"
    state.mkdir()
    (state / "native-loaded-image.txt").write_text(f"10\n{native}\n", encoding="utf-8")
    manifest = {
        "files": {
            "creo-cli-service.jar": {"sha256": "jar-hash"},
            "creo_cli_sketch.dll": {"sha256": "dll-hash"},
        },
        "java_app_class": expected["java_app_class"],
        "component_source_sha256": expected["source_sha256"],
        "runtime_profile": {"mode": "environment"},
    }
    health = java_evidence["health"] | {
        "runtime_configuration_contract": 1,
        "runtime_configuration": {"portable_profile": True, "state_directory": str(state)},
    }
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.health.return_value = health
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(tmp_path / "config"))
    arguments = {
        "creo": Path(expected["host_path"]).parents[3],
        "java_home": Path(expected["java_path"]).parents[1],
    }
    original = runtime_identity.validate_candidate
    with (
        patch.object(
            deployment, "files", return_value=(target, manifest, {"files": manifest["files"]})
        ),
        patch.object(deployment, "Client", return_value=client),
        patch.object(
            runtime_identity,
            "processes",
            side_effect=[java_evidence["before"], java_evidence["after"]] * 2,
        ),
        patch.object(runtime_identity, "modules", return_value=[str(native)]),
        patch.object(runtime_identity, "open_jars", side_effect=[java_evidence["open_jars"], []]),
        patch.object(
            deployment.service_bundle,
            "sha256",
            side_effect=lambda path: "dll-hash" if Path(path).suffix == ".dll" else "jar-hash",
        ),
        patch.object(runtime_identity, "validate_candidate", wraps=original) as full,
    ):
        first = deployment.inspect(target, **arguments)
        later = deployment.inspect(target, **arguments)
    assert first["loaded_verified"] is True and first["native_loaded_verified"] is True
    assert first["java_loaded_verified"] is True
    assert later["loaded_verified"] is True  # Original full gate keeps its verified anchor rule.
    assert later["runtime_identity"]["jar_binding"] == "same_generation_verified_load"
    assert (
        later["java_loaded_verified"] is False
    )  # New Java-only profile never borrows that anchor.
    assert full.call_count == 2
    assert "java_app_class" not in full.call_args.args[4]
    client.op.assert_not_called()


class PublicPartialIdentity(Base):
    def test_partial_java_identity_cannot_qualify_context_or_native_backend(self):
        value = {
            "files_verified": True,
            "java_loaded_verified": True,
            "loaded_verified": False,
            "native_loaded_verified": False,
        }
        with patch.object(deployment, "inspect", return_value=value):
            context = self.cli("context", "--installation", self.ws)["data"]
            self.assertEqual(context["environment"]["connection"]["status"], "unavailable")
            # Registry is loaded by the public context call before patching this module.
            from creo_cli.commands import meta

            with patch.object(
                meta,
                "_service_checks",
                return_value=[meta._check("native_session_read", "pass", "controlled readiness")],
            ):
                doctor = self.cli("doctor", "--installation", self.ws)["data"]
        checks = {row["check"]: row for row in doctor["checks"]}
        self.assertEqual(checks["native_backend"]["status"], "fail")
        self.assertFalse(checks["native_backend"]["details"]["source_verified"])
        self.assertEqual(self.world.events, [])
