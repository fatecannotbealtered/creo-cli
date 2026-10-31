"""Validate historical evidence roles without contacting Creo or the product CLI.

By default, compare the committed normalized snapshots with the evidence summary.
Pass --evidence-root explicitly to additionally check the original recorded JSON
bytes, doctor intervals, component provenance and report bindings. A historical
snapshot never establishes a current connection or process liveness.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = "evidence-identity-role-bindings/v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ARTIFACT_SHA_FIELDS = (
    "exe_sha256",
    "jar_sha256",
    "dll_sha256",
    "source_sha256",
)
_PROCESS_FIELDS = (
    "pid",
    "parent_pid",
    "name",
    "creation_filetime",
    "actual_process_machine",
)
_PIN_FIELDS = (
    "java_pid",
    "native_pid",
    "chain",
    "process_creations",
    "service_instance_id",
)
Issue = dict[str, str]


def _issue(issues: list[Issue], code: str, path: str, message: str) -> None:
    issues.append({"code": code, "path": path, "message": message})


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _utc(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() == dt.timedelta(0) else None


def _pin(value: Any, path: str, issues: list[Issue]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(k not in value for k in _PIN_FIELDS):
        _issue(issues, "E_IDENTITY_INCOMPLETE", path, "Full runtime pin is required.")
    pin = _mapping(value)
    java, native = pin.get("java_pid"), pin.get("native_pid")
    if not (_positive_int(java) and _positive_int(native) and java != native):
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            path,
            "Distinct positive Java/native PIDs are required.",
        )
    if pin.get("chain") != [java, native] or java is None or native is None:
        _issue(
            issues,
            "E_PROCESS_CHAIN",
            path + ".chain",
            "Chain must be Java PID followed by its native parent PID.",
        )
    births = _mapping(pin.get("process_creations"))
    if set(births) != {str(java), str(native)} or any(
        not isinstance(v, str) or not v.isdigit() or int(v) <= 0 for v in births.values()
    ):
        _issue(
            issues,
            "E_PROCESS_BIRTH",
            path + ".process_creations",
            "Both PID-keyed native birth FILETIMEs are required.",
        )
    try:
        uuid.UUID(pin.get("service_instance_id", ""))
    except (ValueError, AttributeError, TypeError):
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            path + ".service_instance_id",
            "A service instance UUID is required.",
        )
    return pin


def _processes(
    value: Any, pin: dict[str, Any], path: str, issues: list[Issue]
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            path,
            "Exactly two complete native process observations are required.",
        )
        return []
    normalized = []
    for i, item in enumerate(value):
        row = _mapping(item)
        if any(k not in row for k in _PROCESS_FIELDS):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                f"{path}[{i}]",
                "Process identity fields are missing.",
            )
        normalized.append({k: row.get(k) for k in _PROCESS_FIELDS})
    by_pid = {row["pid"]: row for row in normalized if _positive_int(row["pid"])}
    java, native = pin.get("java_pid"), pin.get("native_pid")
    if not (_positive_int(java) and _positive_int(native)):
        _issue(
            issues,
            "E_PROCESS_CHAIN",
            path,
            "Process identities require a complete positive-PID pin.",
        )
        return normalized
    if set(by_pid) != {java, native} or len(by_pid) != 2:
        _issue(
            issues,
            "E_PROCESS_CHAIN",
            path,
            "Process identities must identify the pin's Java and native PIDs.",
        )
    for pid, expected_name in [(java, "java.exe"), (native, "xtop.exe")]:
        row = by_pid.get(pid, {})
        if (
            not _positive_int(row.get("parent_pid"))
            or str(row.get("name", "")).casefold() != expected_name
        ):
            _issue(issues, "E_PROCESS_CHAIN", path, "Native process name and parent are required.")
        if pid == java and row.get("parent_pid") != native:
            _issue(
                issues, "E_PROCESS_CHAIN", path, "Java's observed parent must be the native PID."
            )
        if row.get("creation_filetime") != _mapping(pin.get("process_creations")).get(str(pid)):
            _issue(issues, "E_PROCESS_BIRTH", path, "OS process birth must agree with the pin.")
        if not isinstance(row.get("actual_process_machine"), str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{4}", row["actual_process_machine"]
        ):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path,
                "Native process machine observation is required.",
            )
    return normalized


def _reference(value: Any, kind: str, path: str, issues: list[Issue]) -> dict[str, Any]:
    reference = _mapping(value)
    relative = reference.get("relative_path")
    valid_path = False
    if (
        isinstance(relative, str)
        and "\\" not in relative
        and not any(ord(c) < 32 for c in relative)
    ):
        candidate = PurePosixPath(relative)
        expected_name = {"runtime": "RUNTIME.json", "run": "RUN.json"}.get(kind)
        valid_name = (
            candidate.name == expected_name
            if expected_name
            else bool(re.fullmatch(r"\d{3}-call\.json", candidate.name))
        )
        valid_path = (
            bool(relative)
            and not candidate.is_absolute()
            and not re.match(r"^[A-Za-z]:", relative)
            and ".." not in candidate.parts
            and valid_name
        )
    if not valid_path:
        _issue(
            issues,
            "E_EVIDENCE_PATH",
            path + ".relative_path",
            "Use a relative runtime, run or numbered call JSON path inside the evidence root.",
        )
    if not isinstance(reference.get("sha256"), str) or not _SHA.fullmatch(reference["sha256"]):
        _issue(issues, "E_IDENTITY_INCOMPLETE", path + ".sha256", "A recorded SHA-256 is required.")
    return reference if valid_path else {}


def _load_record(
    reference: dict[str, Any], root: Path, path: str, issues: list[Issue]
) -> dict[str, Any] | None:
    if not reference:
        return None
    candidate = (root / reference["relative_path"]).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        _issue(issues, "E_EVIDENCE_PATH", path, "Recorded JSON resolves outside the evidence root.")
        return None
    try:
        raw = candidate.read_bytes()
    except OSError:
        _issue(issues, "E_EVIDENCE_READ", path, "Recorded JSON is unavailable.")
        return None
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        _issue(
            issues,
            "E_EVIDENCE_HASH",
            path,
            "Original recorded bytes do not match their bound SHA-256.",
        )
        return None
    try:
        record = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        _issue(issues, "E_EVIDENCE_READ", path, "Recorded evidence is not valid JSON.")
        return None
    if not isinstance(record, dict):
        _issue(issues, "E_IDENTITY_INCOMPLETE", path, "Recorded evidence must be a JSON object.")
        return None
    return record


def _check_runtime(
    observed: dict[str, Any], role: dict[str, Any], path: str, issues: list[Issue]
) -> None:
    pin = _pin(observed.get("runtime_pin"), path + ".runtime_pin", issues)
    if pin != role.get("runtime_pin"):
        _issue(
            issues,
            "E_PIN_MISMATCH",
            path + ".runtime_pin",
            "Recorded generation does not match this historical role.",
        )
    processes = _processes(
        observed.get("process_identities"), pin, path + ".process_identities", issues
    )
    if processes != role.get("process_identities"):
        _issue(
            issues,
            "E_REPORT_BINDING_MISMATCH",
            path + ".process_identities",
            "Normalized OS observations differ from the role snapshot.",
        )
    identity = _mapping(observed.get("runtime_identity"))
    if (
        observed.get("files_verified") is not True
        or observed.get("loaded_verified") is not True
        or identity.get("passed") is not True
    ):
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            path,
            "File, loaded-component and OS identity verification must all be present and true.",
        )
    if any(
        identity.get(k) != pin.get(v)
        for k, v in [
            ("java_pid", "java_pid"),
            ("native_host_pid", "native_pid"),
            ("service_instance_id", "service_instance_id"),
        ]
    ):
        _issue(
            issues,
            "E_PIN_MISMATCH",
            path + ".runtime_identity",
            "Verified runtime identity must agree with the full pin.",
        )
    artifacts = _mapping(role.get("artifacts"))
    components = _mapping(observed.get("component_files"))
    for name, key in [
        ("creo-cli-service.jar", "jar_sha256"),
        ("creo_cli_sketch.dll", "dll_sha256"),
    ]:
        value = _mapping(components.get(name)).get("sha256")
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".component_files." + name,
                "Actual component SHA-256 is missing.",
            )
        if value != artifacts.get(key):
            _issue(
                issues,
                "E_COMPONENT_MISMATCH",
                path + ".component_files." + name,
                "Actual loaded component belongs to a different role/build.",
            )
    runtime = _mapping(observed.get("observed_runtime"))
    if (
        observed.get("component_source_sha256") != artifacts.get("source_sha256")
        or runtime.get("source_sha256") != artifacts.get("source_sha256")
        or runtime.get("runtime_class") != artifacts.get("runtime_class")
    ):
        _issue(
            issues,
            "E_SOURCE_MISMATCH",
            path + ".observed_runtime",
            "Component source fingerprint and runtime class must match the role.",
        )
    if runtime.get("service_instance_id") != pin.get("service_instance_id"):
        _issue(
            issues,
            "E_PIN_MISMATCH",
            path + ".observed_runtime.service_instance_id",
            "Handshake instance must agree with OS-bound identity.",
        )


def _raw_observation(
    role: dict[str, Any],
    observation: dict[str, Any],
    root: Path,
    path: str,
    issues: list[Issue],
) -> None:
    refs = _mapping(observation.get("evidence"))
    records = {
        kind: _load_record(
            _reference(refs.get(kind), kind, path + ".evidence." + kind, issues),
            root,
            path + ".evidence." + kind,
            issues,
        )
        for kind in ["runtime", "doctor", "run"]
    }
    runtime, doctor, run = (records[k] for k in ["runtime", "doctor", "run"])
    if runtime is not None:
        _check_runtime(runtime, role, path + ".evidence.runtime", issues)
    if doctor is not None:
        stdout = _mapping(doctor.get("stdout"))
        checks = _mapping(stdout.get("data")).get("checks", [])
        candidates = (
            [
                row
                for row in checks
                if isinstance(row, dict) and row.get("check") == "installation_files"
            ]
            if isinstance(checks, list)
            else []
        )
        selected = candidates[0] if len(candidates) == 1 else {}
        actual = _mapping(_mapping(selected.get("details")).get("observation"))
        if stdout.get("ok") is not True or selected.get("status") != "pass" or not actual:
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".evidence.doctor",
                "A successful original installation_files doctor observation is required.",
            )
        else:
            _check_runtime(actual, role, path + ".evidence.doctor.observation", issues)
        if runtime is not None and actual != runtime:
            _issue(
                issues,
                "E_REPORT_BINDING_MISMATCH",
                path + ".evidence.runtime",
                "RUNTIME report must exactly equal its original doctor's embedded observation.",
            )
        argv = doctor.get("argv")
        if (
            isinstance(argv, list)
            and len(argv) > 1
            and isinstance(argv[0], str)
            and argv[0].lower().endswith(".exe")
            and argv[1] == "doctor"
        ):
            argv = argv[1:]
        if (
            not isinstance(argv, list)
            or not argv
            or argv[0] != "doctor"
            or "--installation" not in argv
        ):
            _issue(
                issues,
                "E_EVIDENCE_ROLE",
                path + ".evidence.doctor.argv",
                "Original evidence must be the declared doctor call.",
            )
        else:
            i = argv.index("--installation") + 1
            if (
                i >= len(argv)
                or not _text(actual.get("installation"))
                or argv[i] != actual.get("installation")
            ):
                _issue(
                    issues,
                    "E_EVIDENCE_ROLE",
                    path + ".evidence.doctor.argv",
                    "Doctor selector must agree with the actual installation observation.",
                )
        interval = _mapping(observation.get("interval_utc"))
        start, finish = _utc(doctor.get("started_at")), _utc(doctor.get("finished_at"))
        if (
            start is None
            or finish is None
            or finish <= start
            or start != _utc(interval.get("start"))
            or finish != _utc(interval.get("finish"))
        ):
            _issue(
                issues,
                "E_OBSERVATION_INTERVAL",
                path + ".interval_utc",
                "Historical interval must equal the original doctor call's UTC interval.",
            )
    if run is not None:
        if run.get("exe_sha256") != _mapping(role.get("artifacts")).get("exe_sha256"):
            _issue(
                issues,
                "E_COMPONENT_MISMATCH",
                path + ".evidence.run.exe_sha256",
                "Original CLI EXE SHA-256 must match the role's tested executable.",
            )
        began = _utc(run.get("started_at"))
        doctor_start = _utc(_mapping(doctor).get("started_at"))
        if began is None or (doctor_start is not None and began > doctor_start):
            _issue(
                issues,
                "E_OBSERVATION_INTERVAL",
                path + ".evidence.run.started_at",
                "Original run must begin before its doctor observation.",
            )


def validate_identity_bindings(
    bindings: dict[str, Any],
    summary: dict[str, Any],
    evidence_root: Path | None = None,
) -> list[Issue]:
    """Return specific metadata errors; read raw JSON only with an explicit root."""
    issues: list[Issue] = []
    bindings = _mapping(bindings)
    if (
        bindings.get("schema_version") != _SCHEMA
        or bindings.get("complete") is not True
        or bindings.get("scope") != "historical-only"
    ):
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            "$",
            "Complete historical-only role bindings with the supported schema are required.",
        )
    roles = _mapping(bindings.get("roles"))
    if not roles:
        _issue(
            issues,
            "E_IDENTITY_INCOMPLETE",
            "$.roles",
            "At least one complete role snapshot is required.",
        )
    instances: dict[str, str] = {}
    generations: dict[tuple[int, str], str] = {}
    for role_name, value in roles.items():
        path = "$.roles." + role_name
        role = _mapping(value)
        if (
            role.get("complete") is not True
            or role.get("role") != role_name
            or not _text(role.get("purpose"))
        ):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path,
                "Complete role, matching label and purpose are required.",
            )
        artifacts = _mapping(role.get("artifacts"))
        for key in _ARTIFACT_SHA_FIELDS:
            if not isinstance(artifacts.get(key), str) or not _SHA.fullmatch(artifacts[key]):
                _issue(
                    issues,
                    "E_IDENTITY_INCOMPLETE",
                    path + ".artifacts." + key,
                    "A role-specific SHA-256 is required.",
                )
        if not _text(artifacts.get("runtime_class")):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".artifacts.runtime_class",
                "The actual historical runtime class is required.",
            )
        artifact_paths = _mapping(role.get("summary_artifact_paths"))
        if not {"exe_sha256", "jar_sha256", "dll_sha256"}.issubset(artifact_paths):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".summary_artifact_paths",
                "Summary paths for this role's EXE, JAR and DLL are required.",
            )
        for field, field_path in artifact_paths.items():
            if (
                field not in {*_ARTIFACT_SHA_FIELDS, "runtime_class"}
                or not isinstance(field_path, list)
                or not field_path
                or any(not _text(key) for key in field_path)
            ):
                _issue(
                    issues,
                    "E_IDENTITY_INCOMPLETE",
                    path + ".summary_artifact_paths." + field,
                    "Use a supported artifact field and a nonempty summary path.",
                )
                continue
            declared: Any = summary
            for key in field_path:
                declared = _mapping(declared).get(key)
            if declared != artifacts.get(field):
                _issue(
                    issues,
                    "E_SOURCE_MISMATCH"
                    if field in {"source_sha256", "runtime_class"}
                    else "E_COMPONENT_MISMATCH",
                    "$.summary." + ".".join(field_path),
                    "Summary artifact provenance does not match this historical role.",
                )
        pin = _pin(role.get("runtime_pin"), path + ".runtime_pin", issues)
        _processes(role.get("process_identities"), pin, path + ".process_identities", issues)
        instance = pin.get("service_instance_id")
        if isinstance(instance, str):
            if instance in instances:
                _issue(
                    issues,
                    "E_ROLE_COLLISION",
                    path + ".runtime_pin",
                    "Separate historical roles must not reuse another role's service instance.",
                )
            instances[instance] = role_name
        for pid, birth in _mapping(pin.get("process_creations")).items():
            if isinstance(pid, str) and pid.isdigit() and isinstance(birth, str):
                generation = (int(pid), birth)
                if generation in generations and generations[generation] != role_name:
                    _issue(
                        issues,
                        "E_ROLE_COLLISION",
                        path + ".runtime_pin.process_creations",
                        "Separate roles must not reuse another role's observed process generation.",
                    )
                generations[generation] = role_name
        pointer = role.get("summary_pin_path")
        actual: Any = summary
        if not isinstance(pointer, list) or not pointer or any(not _text(k) for k in pointer):
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".summary_pin_path",
                "A nonempty summary field path is required.",
            )
        else:
            for key in pointer:
                actual = _mapping(actual).get(key)
            if actual != role.get("runtime_pin"):
                _issue(
                    issues,
                    "E_SUMMARY_PIN",
                    "$.summary." + ".".join(pointer),
                    "Summary pin does not match this role's original historical identity.",
                )
        observations = role.get("observations")
        if not isinstance(observations, list) or not observations:
            _issue(
                issues,
                "E_IDENTITY_INCOMPLETE",
                path + ".observations",
                "At least one original historical observation is required.",
            )
            continue
        ids: set[str] = set()
        for i, value in enumerate(observations):
            observation = _mapping(value)
            opath = path + f".observations[{i}]"
            identifier = observation.get("id")
            if not _text(identifier) or identifier in ids:
                _issue(
                    issues,
                    "E_IDENTITY_INCOMPLETE",
                    opath + ".id",
                    "Observation IDs must be nonempty and unique within the role.",
                )
            else:
                ids.add(identifier)
            interval = _mapping(observation.get("interval_utc"))
            start, finish = _utc(interval.get("start")), _utc(interval.get("finish"))
            if start is None or finish is None or finish <= start:
                _issue(
                    issues,
                    "E_OBSERVATION_INTERVAL",
                    opath + ".interval_utc",
                    "An ordered, explicit UTC doctor interval is required.",
                )
            refs = _mapping(observation.get("evidence"))
            for kind in ["runtime", "doctor", "run"]:
                _reference(refs.get(kind), kind, opath + ".evidence." + kind, issues)
            if evidence_root is not None:
                _raw_observation(role, observation, Path(evidence_root), opath, issues)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bindings",
        type=Path,
        default=_ROOT / "docs/evidence/round23-20261016/identity-role-bindings.json",
    )
    parser.add_argument(
        "--summary", type=Path, default=_ROOT / "docs/evidence/round22-20261015/summary.json"
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="Explicit root of original recorded JSON; no current runtime connection is made.",
    )
    args = parser.parse_args(argv)
    issues: list[Issue] = []
    loaded = []
    for label, path in [("bindings", args.bindings), ("summary", args.summary)]:
        try:
            value = json.loads(path.read_bytes())
        except (OSError, ValueError, UnicodeDecodeError):
            _issue(issues, "E_EVIDENCE_READ", "$" + label, "Input JSON could not be read.")
            value = {}
        loaded.append(value)
    if not issues:
        issues = validate_identity_bindings(*loaded, evidence_root=args.evidence_root)
    output = {
        "ok": not issues,
        "schema_version": "evidence-identity-validation/v1",
        "data": {
            "scope": "historical-only",
            "normalized_snapshot_and_summary_checked": not any(
                x["code"] == "E_EVIDENCE_READ" and x["path"] in ["$bindings", "$summary"]
                for x in issues
            ),
            "raw_evidence_requested": args.evidence_root is not None,
            "raw_evidence_status": "not_requested"
            if args.evidence_root is None
            else "failed"
            if issues
            else "verified",
            "current_connection": "not_assessed",
            "native_calls": 0,
        },
        "errors": issues,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
