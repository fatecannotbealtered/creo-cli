"""Run the whole suite with pytest; with --evidence, record what ran against which source.

The fingerprint covers every source, contract and doc file -- the Java service and the C
sketch library included -- so evidence recorded for one tree is visibly stale for another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
}
EXTENSIONS = {".py", ".json", ".md", ".js", ".toml", ".yml", ".yaml", ".java", ".c", ".h"}
SPECIAL = {"LICENSE", ".gitignore", ".gitattributes", ".npmrc", "SPEC_VERSION"}


def fingerprint() -> str:
    h = hashlib.sha256()
    found = []
    for directory, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORED and not d.endswith(".egg-info")]
        for name in names:
            p = Path(directory) / name
            rel = p.relative_to(ROOT).as_posix()
            if rel.startswith("docs/evidence/") or rel == "docs/HANDOFF_zh.md":
                continue
            if p.suffix in EXTENSIONS or name in SPECIAL:
                found.append(p)
    for p in sorted(found):
        h.update(p.relative_to(ROOT).as_posix().encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", help="write the run's record here")
    a = p.parse_args()
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "junit.xml"
        env = dict(os.environ, CREO_CLI_CONFIG_DIR=str(Path(tmp) / "state"))
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "--junitxml", str(report)],
            cwd=ROOT,
            env=env,
        )
        suite = ET.parse(report).getroot()
        suite = suite if suite.tag == "testsuite" else suite.find("testsuite")
        counts = {k: int(suite.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
    reference = subprocess.run(
        [sys.executable, "-m", "creo_cli", "reference", "--compact"],
        cwd=ROOT,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    data = json.loads(reference.stdout)["data"]
    doc = {
        "ok": run.returncode == 0 and counts["failures"] == 0 and counts["errors"] == 0,
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tests_run": counts["tests"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "declared_commands": len(data["commands"]),
        "release_readiness": data["release_readiness"],
        "duration_seconds": round(time.monotonic() - started, 3),
        "source_fingerprint_sha256": fingerprint(),
        "limitations": [
            "Command tests run against a loopback substitute of the service, not Creo; live "
            "runs are recorded separately.",
            "Java and C guards check the service's vocabulary and seams statically; they do "
            "not run Creo.",
        ],
    }
    if a.evidence:
        dest = Path(a.evidence)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                k: doc[k]
                for k in ("ok", "tests_run", "failures", "errors", "skipped", "declared_commands")
            }
        )
    )
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
