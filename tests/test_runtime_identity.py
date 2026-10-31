"""Fail-closed candidate gate, with independently arranged process evidence."""

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from creo_cli.runtime_identity import validate_candidate


def test_closed_jar_check_keeps_original_verified_handle_evidence():
    from scripts.inspect_native_runtime import evidence_references

    first = {"path": "first.json", "sha256": "a" * 64}
    later = {"path": "later.json", "sha256": "b" * 64}
    verified = {"identity": {"passed": True, "jar_binding": "same_generation_verified_load"}}
    kept = evidence_references({"runtime_evidence": first}, verified, later)
    assert kept["runtime_evidence"] == first
    assert kept["latest_runtime_evidence"] == later
    assert evidence_references(kept, verified, {"path": "third.json"})["runtime_evidence"] == first
    with pytest.raises(ValueError):
        evidence_references({}, verified, later)
    with pytest.raises(ValueError):
        evidence_references({}, {"identity": {"passed": False}}, later)


@pytest.fixture
def evidence(tmp_path):
    native, jar = str(tmp_path / "candidate.dll"), str(tmp_path / "candidate.jar")
    host, java = str(tmp_path / "xtop.exe"), str(tmp_path / "java.exe")
    rows = [
        {
            "pid": 10,
            "parent_pid": 5,
            "creation_filetime": "134358400000000000",
            "actual_image": host,
            "actual_process_machine": "0x8664",
        },
        {
            "pid": 20,
            "parent_pid": 10,
            "creation_filetime": "134358400010000000",
            "actual_image": java,
            "actual_process_machine": "0x8664",
        },
    ]
    return {
        "health": {
            "ok": True,
            "service": "creo-cli",
            "source_sha256": "source",
            "process_id": 20,
            "service_instance_id": "generation-a",
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
            "process_creations": {"10": "134358400000000000", "20": "134358400010000000"},
            "service_instance_id": "generation-a",
        },
        "expected": {
            "source_sha256": "source",
            "host_path": host,
            "java_path": java,
            "native": {"path": native, "sha256": "dll"},
            "jar": {"path": jar, "sha256": "jar"},
        },
        "native_image": ["10", native],
        "modules": [native],
        "open_jars": [jar],
        "sha": lambda path: "dll" if Path(path).suffix == ".dll" else "jar",
    }


def test_real_parent_chain_with_distinct_java_pid_passes(evidence):
    assert validate_candidate(**evidence)["passed"]


@pytest.mark.parametrize("where", ["before", "after"])
@pytest.mark.parametrize(
    "change",
    [
        "wrong_parent",
        "reused_java",
        "reused_host",
        "wrong_image",
        "wrong_arch",
        "missing_time",
        "missing_java",
        "duplicate",
    ],
)
def test_invalid_process_evidence_is_refused(evidence, where, change):
    rows = evidence[where]
    if change == "wrong_parent":
        rows[1]["parent_pid"] = 99
    elif change == "reused_java":
        rows[1]["creation_filetime"] = "201"
    elif change == "reused_host":
        rows[0]["creation_filetime"] = "300"
    elif change == "wrong_image":
        rows[1]["actual_image"] = "other.exe"
    elif change == "wrong_arch":
        rows[0]["actual_process_machine"] = "0x14c"
    elif change == "missing_time":
        del rows[1]["creation_filetime"]
    elif change == "missing_java":
        del rows[1]
    else:
        rows.append(deepcopy(rows[1]))
    assert not validate_candidate(**evidence)["passed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("process_id", 21),
        ("process_id", True),
        ("source_sha256", "old"),
        ("service_instance_id", "generation-b"),
        ("process_started_at", "2026-10-06T00:00:00Z"),
        ("process_started_at", None),
        ("ok", False),
    ],
)
def test_old_health_and_other_source_are_refused(evidence, field, value):
    evidence["health"][field] = value
    assert not validate_candidate(**evidence)["passed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_image", []),
        ("native_image", ["10"]),
        ("native_image", ["bad", "x"]),
        ("modules", []),
        ("open_jars", []),
    ],
)
def test_missing_loaded_artifact_evidence_is_refused(evidence, field, value):
    evidence[field] = value
    assert not validate_candidate(**evidence)["passed"]


def test_disk_hash_drift_is_refused(evidence):
    evidence["sha"] = lambda _: "changed"
    assert not validate_candidate(**evidence)["passed"]


def test_hash_read_denial_is_refused(evidence):
    def denied(_):
        raise PermissionError("denied")

    evidence["sha"] = denied
    assert not validate_candidate(**evidence)["passed"]


def test_service_generation_is_required(evidence):
    del evidence["health"]["service_instance_id"]
    del evidence["pin"]["service_instance_id"]
    assert not validate_candidate(**evidence)["passed"]


def test_closed_jar_handle_requires_a_verified_load_in_the_same_generation(evidence):
    initial = validate_candidate(**evidence)
    assert initial["passed"]
    retained = {
        "identity": initial,
        "runtime_pin": deepcopy(evidence["pin"]),
        "expected_identity": deepcopy(evidence["expected"]),
        "open_jars": evidence["open_jars"][:],
    }
    evidence["open_jars"] = []
    assert not validate_candidate(**evidence)["passed"]
    current = validate_candidate(**evidence, verified_load=retained)
    assert current["passed"] and current["jar_binding"] == "same_generation_verified_load"


@pytest.mark.parametrize(
    "drift", ["generation", "pid_reuse", "source", "jar_hash", "prior_not_verified"]
)
def test_retained_load_cannot_authorize_a_different_runtime(evidence, drift):
    initial = validate_candidate(**evidence)
    retained = {
        "identity": initial,
        "runtime_pin": deepcopy(evidence["pin"]),
        "expected_identity": deepcopy(evidence["expected"]),
        "open_jars": evidence["open_jars"][:],
    }
    evidence["open_jars"] = []
    if drift == "generation":
        evidence["health"]["service_instance_id"] = "different"
    elif drift == "pid_reuse":
        evidence["after"][1]["creation_filetime"] = "134358400020000000"
    elif drift == "source":
        evidence["health"]["source_sha256"] = "old"
    elif drift == "jar_hash":
        evidence["sha"] = lambda _: "changed"
    else:
        retained["identity"]["passed"] = False
    assert not validate_candidate(**evidence, verified_load=retained)["passed"]
