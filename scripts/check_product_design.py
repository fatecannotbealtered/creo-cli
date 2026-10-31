"""Validate the pinned1.0.2 development design only; no public-runtime conformance claim.

Reads an existing authorized spec checkout, current declaration metadata and bounded
local evidence. Never invokes a handler, connects to Creo or fetches network content.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .build_product_design import ROOT, SOURCE_BASE, SPEC_COMMIT, snapshot
else:
    from build_product_design import ROOT, SOURCE_BASE, SPEC_COMMIT, snapshot


def load_checker(spec_root: Path):
    lock = json.loads((ROOT / "docs/development/spec-source-lock.json").read_text(encoding="utf-8"))
    if lock.get("source_commit") != SPEC_COMMIT:
        raise ValueError("design validator source commit is not the expected pinned reference")
    payloads = {}
    for relative, expected in lock["files"].items():
        path = spec_root / relative
        if ".." in Path(relative).parts or Path(relative).is_absolute() or path.is_symlink():
            raise ValueError("invalid spec source path")
        payload = path.read_bytes()
        payloads[relative] = payload
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("pinned spec source bytes changed")
    head = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD"],
        cwd=spec_root,
        capture_output=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if head.returncode or head.stdout.decode().strip() != SPEC_COMMIT:
        raise ValueError("the readonly spec checkout is not the authorized source commit")
    tree = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "ls-tree",
            "-r",
            "--full-tree",
            SPEC_COMMIT,
            "--",
            *lock["files"],
        ],
        cwd=spec_root,
        capture_output=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if tree.returncode:
        raise ValueError("cannot read pinned spec source tree")
    pinned = {}
    for line in tree.stdout.decode().splitlines():
        metadata, relative = line.split("\t", 1)
        mode, kind, object_id = metadata.split()
        if kind == "blob" and mode in {"100644", "100755"}:
            pinned[relative] = object_id
    for relative, payload in payloads.items():
        # Text checkout EOL conversion is allowed; actual bytes remain pinned by SHA-256.
        object_ids = {
            hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
            for value in (payload, payload.replace(b"\r\n", b"\n"))
        }
        if pinned.get(relative) not in object_ids:
            raise ValueError("spec worktree/lock bytes differ from the authorized commit's blobs")
    sys.path.insert(0, str(spec_root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "_pinned_creo_design_checker", spec_root / "scripts/check_product_design.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def canonical_evidence(product, directory):
    """Give the unmodified pinned validator the declared Git LF bytes, never fresh hashes."""
    rows = []
    for item in product.get("design", {}).get("evidence", []):
        if not item.get("path") or not item.get("sha256"):
            continue
        relative = Path(item["path"])
        path = directory / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.resolve().is_relative_to(directory.resolve())
            or not path.is_file()
        ):
            # Preserve the upstream error for missing, escaping or malformed sources.
            yield directory
            return
        payload = path.read_bytes()
        canonical = payload if b"\0" in payload else payload.replace(b"\r\n", b"\n")
        rows.append((relative, payload, canonical))
    if all(raw == canonical for _, raw, canonical in rows):
        yield directory
        return
    with tempfile.TemporaryDirectory(prefix="creo-design-lf-") as scratch:
        mirror = Path(scratch)
        for relative, _, payload in rows:
            target = mirror / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        yield mirror


def validate(product: dict, *, spec_root: Path, directory: Path = ROOT):
    upstream = load_checker(spec_root)
    with canonical_evidence(product, directory) as evidence_root:
        report = upstream.check_design(product, registry_dir=evidence_root, require=True)
    report["product_evidence_encoding"] = "Git LF text; binary and component runtime hashes exact"
    errors = report["errors"]
    report["public_runtime_contract_checked"] = False
    report["validation_entry"] = (
        "pinned check_design API plus current-declaration/parameter/entrypoint checks"
    )
    report["application_exhaustiveness_proven"] = False
    if product.get("kind") != "development_only_registry_design_not_runtime_contract":
        errors.append("the wrapper must be explicitly development-only")
    if (
        product.get("source_base_commit") != SOURCE_BASE
        or product.get("spec_commit") != SPEC_COMMIT
    ):
        errors.append("source/spec baselines differ from the pinned task")
    actual = {row["path"]: row for row in snapshot()}
    declared = {row["path"]: row for row in product.get("commands", [])}
    if set(actual) != set(declared):
        errors.append("development command paths differ from the actual current CLI declarations")
    for path, row in declared.items():
        if path in actual and row["params"] != actual[path]["params"]:
            errors.append("development parameters differ from the actual current CLI declarations")
    design = product.get("design", {})
    evidence = {item["id"]: item for item in design.get("evidence", [])}
    for task in design.get("tasks", []):
        critical = {(p["command_path"], p["name"]) for p in task["critical_parameters"]}
        for path in task["command_paths"]:
            if path not in actual:
                continue
            needed = {(path, p["name"]) for p in actual[path]["params"] if p["required"]}
            if not needed <= critical:
                errors.append("planned task omits required critical parameters")
            expected = {
                (entry["file"], entry["entrypoint"])
                for entry in [actual[path]["python"], *actual[path]["service_ops"]]
            }
            entries = {
                (evidence.get(e["artifact_ref"], {}).get("path"), e["entrypoint"])
                for e in task["adapter_entries"]
                if e["command_path"] == path
            }
            if expected != entries:
                errors.append(
                    "task adapter entries differ from actual Python/Java dispatch declarations"
                )
    report["declaration_counts"] = {
        "commands": len(actual),
        "tasks": len(design.get("tasks", [])),
        "capabilities": len(design.get("capabilities", [])),
    }
    return report


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "registry.design.json")
    parser.add_argument("--spec-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        # No writes to the readonly spec checkout, including Python bytecode caches.
        sys.dont_write_bytecode = True
        checker = load_checker(args.spec_root)
        product = checker.parse_json(checker.read_regular_file(args.registry, checker.LIMIT))
        report = validate(
            product, spec_root=args.spec_root, directory=args.registry.resolve().parent
        )
        if report["errors"]:
            value = {
                "ok": False,
                "schema_version": "1.0",
                "error": {
                    "code": "E_VALIDATION",
                    "retryable": False,
                    "message": "development design validation failed",
                    "details": {"errors": report["errors"], "scope": "development_design_only"},
                },
            }
            code = 2
        else:
            value = {"ok": True, "schema_version": "1.0", "data": report}
            code = 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        value = {
            "ok": False,
            "schema_version": "1.0",
            "error": {
                "code": "E_VALIDATION",
                "retryable": False,
                "message": "development design or pinned dependency is unavailable",
                "details": {"error_type": type(exc).__name__, "scope": "development_design_only"},
            },
        }
        code = 2
    value["meta"] = {"duration_ms": round((time.monotonic() - started) * 1000, 3)}
    sys.stdout.buffer.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    return code


if __name__ == "__main__":
    sys.exit(main())
