"""Historical identity validation uses committed metadata and synthetic raw evidence only."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.validate_evidence_identity import validate_identity_bindings

REPO = Path(__file__).resolve().parents[1]
BINDINGS = REPO / "docs/evidence/round23-20261016/identity-role-bindings.json"
SUMMARY = REPO / "docs/evidence/round22-20261015/summary.json"
SCRIPT = REPO / "scripts/validate_evidence_identity.py"


@pytest.fixture
def historical():
    if not BINDINGS.exists() or not SUMMARY.exists():
        pytest.skip("Private historical identity records are outside the public snapshot")
    return (
        json.loads(BINDINGS.read_text(encoding="utf-8")),
        json.loads(SUMMARY.read_text(encoding="utf-8")),
    )


def _set_summary_pin(summary, role, pin):
    target = summary
    for key in role["summary_pin_path"][:-1]:
        target = target[key]
    target[role["summary_pin_path"][-1]] = deepcopy(pin)


def _assert_issue(issues, code):
    matching = [issue for issue in issues if issue["code"] == code]
    assert matching, issues
    assert all(isinstance(issue.get("path"), str) and issue["path"] for issue in matching)
    assert all(isinstance(issue.get("message"), str) and issue["message"] for issue in matching)
    assert all(issue["code"] != "E_UNKNOWN" for issue in issues)


def _write_reference(root, reference, document):
    path = root / reference["relative_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(payload)
    reference["sha256"] = hashlib.sha256(payload).hexdigest()


def _read_reference(root, reference):
    return json.loads((root / reference["relative_path"]).read_text(encoding="utf-8"))


def _synthetic_observation(role):
    artifacts = role["artifacts"]
    pin = role["runtime_pin"]
    return {
        "files_verified": True,
        "loaded_verified": True,
        "installation": "offline-fixture-" + role["role"],
        "runtime_pin": deepcopy(pin),
        "process_identities": deepcopy(role["process_identities"]),
        "runtime_identity": {
            "passed": True,
            "java_pid": pin["java_pid"],
            "native_host_pid": pin["native_pid"],
            "service_instance_id": pin["service_instance_id"],
        },
        "component_files": {
            "creo-cli-service.jar": {"sha256": artifacts["jar_sha256"]},
            "creo_cli_sketch.dll": {"sha256": artifacts["dll_sha256"]},
        },
        "component_source_sha256": artifacts["source_sha256"],
        "observed_runtime": {
            "source_sha256": artifacts["source_sha256"],
            "runtime_class": artifacts["runtime_class"],
            "service_instance_id": pin["service_instance_id"],
        },
    }


@pytest.fixture
def raw_case(historical, tmp_path):
    bindings, summary = historical
    for role in bindings["roles"].values():
        runtime = _synthetic_observation(role)
        for observation in role["observations"]:
            interval = observation["interval_utc"]
            doctor = {
                "argv": [
                    "offline-creo-cli.exe",
                    "doctor",
                    "--installation",
                    runtime["installation"],
                ],
                "started_at": interval["start"],
                "finished_at": interval["finish"],
                "stdout": {
                    "ok": True,
                    "schema_version": "1.0",
                    "data": {
                        "checks": [
                            {
                                "check": "installation_files",
                                "status": "pass",
                                "details": {"observation": deepcopy(runtime)},
                            }
                        ]
                    },
                },
            }
            run = {
                "started_at": interval["start"],
                "exe_sha256": role["artifacts"]["exe_sha256"],
            }
            for kind, document in (("runtime", runtime), ("doctor", doctor), ("run", run)):
                _write_reference(tmp_path, observation["evidence"][kind], document)
    return bindings, summary, tmp_path


def _rewrite_runtime_and_doctor(raw_case, mutate, role_name="K"):
    bindings, _, root = raw_case
    evidence = bindings["roles"][role_name]["observations"][0]["evidence"]
    runtime = _read_reference(root, evidence["runtime"])
    mutate(runtime)
    _write_reference(root, evidence["runtime"], runtime)
    doctor = _read_reference(root, evidence["doctor"])
    doctor["stdout"]["data"]["checks"][0]["details"]["observation"] = deepcopy(runtime)
    _write_reference(root, evidence["doctor"], doctor)


def test_committed_historical_snapshot_and_summary_agree(historical):
    bindings, summary = historical
    before = deepcopy((bindings, summary))
    assert validate_identity_bindings(bindings, summary) == []
    assert (bindings, summary) == before


def test_original_k_equals_j_summary_pin_is_rejected(historical):
    bindings, summary = historical
    _set_summary_pin(summary, bindings["roles"]["K"], bindings["roles"]["J"]["runtime_pin"])
    _assert_issue(validate_identity_bindings(bindings, summary), "E_SUMMARY_PIN")


def test_relabeling_j_generation_as_k_is_rejected(historical):
    bindings, summary = historical
    bindings["roles"]["K"]["runtime_pin"] = deepcopy(bindings["roles"]["J"]["runtime_pin"])
    _set_summary_pin(summary, bindings["roles"]["K"], bindings["roles"]["K"]["runtime_pin"])
    _assert_issue(validate_identity_bindings(bindings, summary), "E_ROLE_COLLISION")


def test_shared_service_instance_cannot_be_two_roles(historical):
    bindings, summary = historical
    bindings["roles"]["K"]["runtime_pin"]["service_instance_id"] = bindings["roles"]["J"][
        "runtime_pin"
    ]["service_instance_id"]
    _assert_issue(validate_identity_bindings(bindings, summary), "E_ROLE_COLLISION")


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("exe_sha256", "E_COMPONENT_MISMATCH"),
        ("jar_sha256", "E_COMPONENT_MISMATCH"),
        ("dll_sha256", "E_COMPONENT_MISMATCH"),
        ("source_sha256", "E_SOURCE_MISMATCH"),
        ("runtime_class", "E_SOURCE_MISMATCH"),
    ],
)
def test_static_k_artifacts_must_match_summary_role(historical, field, code):
    bindings, summary = historical
    original = bindings["roles"]["K"]["artifacts"][field]
    replacement = bindings["roles"]["J"]["artifacts"][field]
    if field == "dll_sha256":
        # J and K legitimately share this DLL; its unchanged hash is not a negative case.
        replacement = "0" * 64
    assert replacement != original
    bindings["roles"]["K"]["artifacts"][field] = replacement
    _assert_issue(validate_identity_bindings(bindings, summary), code)


def test_summary_k_jar_cannot_be_replaced_with_r5_without_raw_access(historical):
    bindings, summary = historical
    summary["candidate_S3"]["JAR_sha256"] = bindings["roles"]["J"]["artifacts"]["jar_sha256"]
    _assert_issue(validate_identity_bindings(bindings, summary), "E_COMPONENT_MISMATCH")


def test_summary_k_runtime_class_drift_is_rejected_without_raw_access(historical):
    bindings, summary = historical
    summary["candidate_S3"]["app_class"] = bindings["roles"]["J"]["artifacts"]["runtime_class"]
    _assert_issue(validate_identity_bindings(bindings, summary), "E_SOURCE_MISMATCH")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("reversed_chain", "E_PROCESS_CHAIN"),
        ("wrong_parent", "E_PROCESS_CHAIN"),
        ("missing_process", "E_IDENTITY_INCOMPLETE"),
    ],
)
def test_process_chain_drift_is_rejected(historical, change, code):
    bindings, summary = historical
    role = bindings["roles"]["K"]
    if change == "reversed_chain":
        role["runtime_pin"]["chain"].reverse()
    elif change == "wrong_parent":
        role["process_identities"][0]["parent_pid"] += 1
    else:
        role["process_identities"].pop()
    _assert_issue(validate_identity_bindings(bindings, summary), code)


@pytest.mark.parametrize("change", ["pin_birth", "process_birth"])
def test_process_birth_drift_is_rejected(historical, change):
    bindings, summary = historical
    role = bindings["roles"]["K"]
    if change == "pin_birth":
        role["runtime_pin"]["process_creations"][str(role["runtime_pin"]["java_pid"])] = "1"
    else:
        role["process_identities"][0]["creation_filetime"] = "1"
    _assert_issue(validate_identity_bindings(bindings, summary), "E_PROCESS_BIRTH")


@pytest.mark.parametrize(
    "field",
    [
        "runtime_pin",
        "artifacts",
        "process_identities",
        "observations",
        "summary_pin_path",
        "summary_artifact_paths",
    ],
)
def test_complete_role_requires_identity_fields(historical, field):
    bindings, summary = historical
    assert bindings["complete"] is True
    assert bindings["roles"]["K"]["complete"] is True
    del bindings["roles"]["K"][field]
    _assert_issue(validate_identity_bindings(bindings, summary), "E_IDENTITY_INCOMPLETE")


@pytest.mark.parametrize(
    "field", ["exe_sha256", "jar_sha256", "dll_sha256", "source_sha256", "runtime_class"]
)
def test_complete_role_requires_all_artifact_bindings(historical, field):
    bindings, summary = historical
    del bindings["roles"]["K"]["artifacts"][field]
    _assert_issue(validate_identity_bindings(bindings, summary), "E_IDENTITY_INCOMPLETE")


@pytest.mark.parametrize("where", ["top", "role"])
def test_incomplete_metadata_does_not_validate(historical, where):
    bindings, summary = historical
    target = bindings if where == "top" else bindings["roles"]["K"]
    target["complete"] = False
    _assert_issue(validate_identity_bindings(bindings, summary), "E_IDENTITY_INCOMPLETE")


@pytest.mark.parametrize("change", ["missing_finish", "backwards", "invalid_timestamp"])
def test_observation_interval_is_required_and_ordered(historical, change):
    bindings, summary = historical
    interval = bindings["roles"]["K"]["observations"][0]["interval_utc"]
    if change == "missing_finish":
        del interval["finish"]
    elif change == "backwards":
        interval["start"], interval["finish"] = interval["finish"], interval["start"]
    else:
        interval["start"] = "yesterday"
    _assert_issue(validate_identity_bindings(bindings, summary), "E_OBSERVATION_INTERVAL")


def test_synthetic_raw_evidence_validates_without_product_or_cad(raw_case):
    bindings, summary, root = raw_case
    assert validate_identity_bindings(bindings, summary, root) == []


@pytest.mark.parametrize("kind", ["runtime", "doctor", "run"])
def test_changed_raw_bytes_fail_even_when_json_remains_valid(raw_case, kind):
    bindings, summary, root = raw_case
    reference = bindings["roles"]["K"]["observations"][0]["evidence"][kind]
    path = root / reference["relative_path"]
    path.write_bytes(path.read_bytes() + b"\n")
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_EVIDENCE_HASH")


def test_r5_jar_cannot_be_mixed_into_k_observation(raw_case):
    bindings, summary, root = raw_case
    r5_hash = bindings["roles"]["J"]["artifacts"]["jar_sha256"]

    def replace_jar(runtime):
        runtime["component_files"]["creo-cli-service.jar"]["sha256"] = r5_hash

    _rewrite_runtime_and_doctor(raw_case, replace_jar)
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_COMPONENT_MISMATCH")


@pytest.mark.parametrize("field", ["component_source_sha256", "source_sha256", "runtime_class"])
def test_k_source_and_runtime_class_must_match_recorded_role(raw_case, field):
    bindings, summary, root = raw_case
    artifacts = bindings["roles"]["J"]["artifacts"]

    def replace_source(runtime):
        if field == "component_source_sha256":
            runtime[field] = artifacts["source_sha256"]
        else:
            runtime["observed_runtime"][field] = artifacts[field]

    _rewrite_runtime_and_doctor(raw_case, replace_source)
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_SOURCE_MISMATCH")


def test_raw_instance_drift_is_rejected_after_hashes_are_rebound(raw_case):
    bindings, summary, root = raw_case

    def replace_instance(runtime):
        for target in (
            runtime["runtime_pin"],
            runtime["runtime_identity"],
            runtime["observed_runtime"],
        ):
            target["service_instance_id"] = "another-generation"

    _rewrite_runtime_and_doctor(raw_case, replace_instance)
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_PIN_MISMATCH")


def test_doctor_observation_cannot_disagree_with_runtime_file(raw_case):
    bindings, summary, root = raw_case
    reference = bindings["roles"]["K"]["observations"][0]["evidence"]["doctor"]
    doctor = _read_reference(root, reference)
    doctor["stdout"]["data"]["checks"][0]["details"]["observation"]["files_verified"] = False
    _write_reference(root, reference, doctor)
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_REPORT_BINDING_MISMATCH")


@pytest.mark.parametrize("change", ["start", "finish", "run_after_doctor"])
def test_raw_timing_must_bind_to_exact_snapshot_interval(raw_case, change):
    bindings, summary, root = raw_case
    observation = bindings["roles"]["K"]["observations"][0]
    evidence = observation["evidence"]
    if change == "run_after_doctor":
        reference = evidence["run"]
        document = _read_reference(root, reference)
        document["started_at"] = observation["interval_utc"]["finish"]
    else:
        reference = evidence["doctor"]
        document = _read_reference(root, reference)
        key = "started_at" if change == "start" else "finished_at"
        document[key] = "2026-10-16T00:00:00+00:00"
    _write_reference(root, reference, document)
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_OBSERVATION_INTERVAL")


@pytest.mark.parametrize(
    "relative_path", ["../RUNTIME.json", "/outside/RUNTIME.json", "runtime-k-initial/private.txt"]
)
def test_raw_evidence_paths_stay_within_allowed_root_and_names(raw_case, relative_path):
    bindings, summary, root = raw_case
    reference = bindings["roles"]["K"]["observations"][0]["evidence"]["runtime"]
    reference["relative_path"] = relative_path
    _assert_issue(validate_identity_bindings(bindings, summary, root), "E_EVIDENCE_PATH")


def test_offline_cli_emits_one_json_envelope_and_fails_invalid_bindings(historical, tmp_path):
    bindings, summary = historical
    _set_summary_pin(summary, bindings["roles"]["K"], bindings["roles"]["J"]["runtime_pin"])
    bindings_path, summary_path = tmp_path / "bindings.json", tmp_path / "summary.json"
    bindings_path.write_text(json.dumps(bindings), encoding="utf-8")
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--bindings",
            str(bindings_path),
            "--summary",
            str(summary_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["schema_version"]
    assert "data" in envelope
    _assert_issue(envelope["errors"], "E_SUMMARY_PIN")
