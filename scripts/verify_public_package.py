"""Verify a complete downloaded/extracted beta without running CAD."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

COMPONENTS = {
    "cli/creo-cli.exe": "18d7eb7dfee41cc0ebae5d78140f6a42c92c19b835c3ce9af4d600d3540a8798",
    "cli/service-bundle/creo-cli-service.jar": (
        "bbc5f5a9952876aebb726f29d53d67b509278c91d4d2a3a66386f3f2270cae39"
    ),
    "cli/service-bundle/creo_cli_sketch.dll": (
        "3aaba42f693550fd6cdcc9d49521a0e17669f3e50af7702ab67a8bae42f6ea7f"
    ),
}
HELPERS = {
    "Initialize-CreoWorkspace.ps1",
    "Start-CreoWorkspace.ps1",
    "Initialize-InternalTrial.ps1",
    "Start-InternalTrial.ps1",
    "InternalUnsignedPreflight.ps1",
    "RecoveryIsolation.ps1",
    "Invoke-CreoCli.ps1",
    "start-owned-creo.ps1",
    "Start-OwnedCreoProcess.ps1",
}


def verify(root: Path):
    manifest = json.loads((root / "PACKAGE-MANIFEST.json").read_text(encoding="utf-8-sig"))
    names = set(manifest["files"])
    if not COMPONENTS.keys() <= names:
        raise ValueError("Missing runtime components")
    required = {"cli/examples/engineering/" + name for name in HELPERS}
    required |= {
        "cli/skills/" + name + "/SKILL.md"
        for name in (
            "creo-cli",
            "creo-modeling",
            "creo-assembly",
            "creo-drawing",
            "creo-presentation",
            "creo-delivery",
        )
    }
    required |= {"NOTICE.md", "LICENSE", "cli/.agent/driver/LICENSE", "COMPONENT-ORIGINS.json"}
    if not required <= names:
        raise ValueError("Missing helpers, skills or notices: " + str(sorted(required - names)))
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {
        "PACKAGE-MANIFEST.json"
    }
    if actual != names:
        raise ValueError("Manifest file set differs from payload")
    for name, expected in manifest["files"].items():
        if {"PROJECTS", "EXAMPLES", "review-evidence", "development", ".git"}.intersection(
            Path(name).parts
        ):
            raise ValueError("Private or historical payload directory")
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError("Unsafe manifest path")
        data = path.read_bytes()
        if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError("Integrity mismatch: " + name)
    origins = json.loads((root / "COMPONENT-ORIGINS.json").read_text())
    for name in COMPONENTS:
        if manifest["files"][name]["sha256"] != COMPONENTS[name]:
            raise ValueError("Component differs from the reviewed original")
        if origins["components"][name]["sha256"] != manifest["files"][name]["sha256"]:
            raise ValueError("Component origin mismatch")
    return {
        "status": "passed",
        "files_verified": len(names),
        "components": len(COMPONENTS),
        "skills": 6,
        "CAD_started": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    print(json.dumps(verify(parser.parse_args().package)))
