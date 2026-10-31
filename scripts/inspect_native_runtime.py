"""Read source-bound runtime identity without launching, closing or editing Creo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from creo_cli import runtime_identity  # noqa: E402
from creo_cli.transport import Client  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(launch: dict) -> dict:
    if Path(launch["source_root"]).resolve() != ROOT:
        raise RuntimeError("launch source checkout differs from this checkout")
    for relative, digest in launch["source_lock"]["files"].items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError("native candidate source differs: " + relative)
    os.environ["CREO_CLI_SERVICE_URL"] = f"http://127.0.0.1:{launch['port']}"
    os.environ["CREO_CLI_SERVICE_TOKEN_FILE"] = str(Path(launch["state"]) / "service-token")
    rows = runtime_identity.processes()
    by_pid = {row["pid"]: row for row in rows}
    health = Client(5).health()
    handshake = Path(launch.get("native_handshake_dir", launch["state"]))
    image = (handshake / "native-loaded-image.txt").read_text(encoding="utf-8").splitlines()
    java_pid, host_pid = health["process_id"], int(image[0])
    chain, current = [], java_pid
    while current in by_pid and current not in chain and len(chain) < 32:
        chain.append(current)
        if current == host_pid:
            break
        current = by_pid[current]["parent_pid"]
    pin = launch.get("runtime_pin") or {
        "java_pid": java_pid,
        "native_pid": host_pid,
        "chain": chain,
        "process_creations": {str(pid): by_pid[pid].get("creation_filetime") for pid in chain},
        "service_instance_id": health.get("service_instance_id"),
    }
    prior = {row["pid"]: row.get("creation_filetime") for row in launch["preexisting_processes"]}
    if launch.get("ownership") != "attached" and any(
        by_pid.get(pid, {}).get("creation_filetime") == prior.get(pid) for pid in chain
    ):
        raise RuntimeError("candidate is attached to a preexisting process")
    # Ownership additionally reaches the actual launched PTC process. Its start
    # must agree with the launch timestamp, preventing a recycled launcher PID.
    ancestry, current = [], host_pid
    while current in by_pid and current not in ancestry and len(ancestry) < 32:
        ancestry.append(current)
        if current == launch["launcher_pid"]:
            break
        current = by_pid[current]["parent_pid"]
    if not ancestry or ancestry[-1] != launch["launcher_pid"]:
        raise RuntimeError("native host is not descended from the recorded launcher")
    created = (int(by_pid[current]["creation_filetime"]) - 116444736000000000) / 1e7
    if launch.get("ownership") == "attached":
        host_pin = launch["attached_host"]
        if host_pid != host_pin["pid"] or by_pid[host_pid] != host_pin:
            raise RuntimeError("attached Creo process differs from its captured identity")
    elif not 0 <= created - datetime.fromisoformat(launch["at_utc"]).timestamp() <= 5:
        raise RuntimeError("launcher PID creation differs from the recorded launch")
    expected = launch.get("expected_identity") or {
        "source_sha256": launch["source_sha256"],
        "java_path": by_pid[java_pid].get("actual_image", ""),
        "host_path": str(
            Path(launch["executable"]).parents[2] / "Common Files/x86e_win64/obj/xtop.exe"
        ),
        **launch["candidate_files"],
    }
    # The actual runtime must use the JDK selected by the candidate's build.
    expected["java_path"] = launch.get("java_path") or expected["java_path"]
    if (
        launch.get("expected_runtime_class")
        and health.get("runtime_class") != launch["expected_runtime_class"]
    ):
        raise RuntimeError("loaded Java class differs from the source-bound build profile")
    modules = runtime_identity.modules(host_pid)
    jars = runtime_identity.open_jars(java_pid)
    after = runtime_identity.processes()
    prior_load = None
    if launch.get("runtime_evidence"):
        retained = Path(launch["runtime_evidence"]["path"])
        if sha(retained) != launch["runtime_evidence"]["sha256"]:
            raise RuntimeError("retained runtime identity evidence changed")
        prior_load = json.loads(retained.read_text(encoding="utf-8"))
    gate = runtime_identity.validate_candidate(
        health,
        rows,
        after,
        pin,
        expected,
        image,
        modules,
        jars,
        sha,
        verified_load=prior_load,
    )
    post = {row["pid"]: row for row in after}
    if any(by_pid[pid] != post.get(pid) for pid in ancestry):
        gate["passed"] = False
        gate["errors"].append("owned launcher ancestry changed during observation")
    return {
        "at_utc": datetime.now(UTC).isoformat(),
        "health": health,
        "runtime_pin": pin,
        "expected_identity": expected,
        "identity": gate,
        "processes": [by_pid[pid] for pid in dict.fromkeys(chain + ancestry)],
        "native_modules": [p for p in modules if "creo_cli" in p.lower()],
        "open_jars": jars,
        "read_only": True,
    }


def evidence_references(launch, observed, latest):
    """Keep the observation with an actual JAR handle as the immutable load anchor."""
    if observed.get("identity", {}).get("passed") is not True:
        raise ValueError("an unverified observation cannot establish a load anchor")
    if observed["identity"].get("jar_binding") == "same_generation_verified_load":
        if not launch.get("runtime_evidence"):
            raise ValueError("same-generation verification requires the retained load anchor")
        return {"runtime_evidence": launch["runtime_evidence"], "latest_runtime_evidence": latest}
    return {"runtime_evidence": latest, "latest_runtime_evidence": latest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    args = parser.parse_args()
    path = args.launch.resolve()
    launch = json.loads(path.read_text(encoding="utf-8"))
    observed = inspect(launch)
    output = path.parent / ("runtime-identity-" + uuid.uuid4().hex[:8] + ".json")
    output.write_text(json.dumps(observed, indent=2), encoding="utf-8")
    if observed["identity"]["passed"]:
        launch.update(
            runtime_pin=observed["runtime_pin"], expected_identity=observed["expected_identity"]
        )
        launch["prior_launch"] = {"path": str(path), "sha256": sha(path)}
        launch.update(
            evidence_references(launch, observed, {"path": str(output), "sha256": sha(output)})
        )
        verified = path.parent / ("verified-launch-" + uuid.uuid4().hex[:8] + ".json")
        verified.write_text(json.dumps(launch, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "launch": str(verified), "evidence": str(output)}))
        return 0
    print(
        json.dumps(
            {"passed": False, "evidence": str(output), "errors": observed["identity"]["errors"]}
        )
    )
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
