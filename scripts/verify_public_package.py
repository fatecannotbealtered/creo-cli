"""Verify a complete downloaded/extracted beta without running CAD."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

COMPONENTS = {
    "cli/creo-cli.exe": "07cb21b2534f9b9918f0a30b82ead8a6ca953e2a188887ab1e521d528a28faef",
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
    required |= {"CLIENT-BUILD.json", "CLIENT-ARTIFACT.json", "RUNTIME-DISTRIBUTION.json"}
    required |= {"release/CONTROLLED-RUNTIME.json", "release/CONTROLLED-RUNTIME-INPUTS.json"}
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
            raise ValueError("Component differs from the reviewed client rebuild/native original")
        if origins["components"][name]["sha256"] != manifest["files"][name]["sha256"]:
            raise ValueError("Component origin mismatch")
    runtime = json.loads((root / "RUNTIME-DISTRIBUTION.json").read_text())
    artifact = json.loads((root / "CLIENT-ARTIFACT.json").read_text())
    client = manifest["files"]["cli/creo-cli.exe"]
    if artifact["exe"] != client or runtime["client"] != client:
        raise ValueError("Runtime inventory does not bind this exact client")
    if artifact["source_commit"] != runtime["client_source_commit"]:
        raise ValueError("Runtime inventory source binding differs")
    if (
        hashlib.sha256((root / "CLIENT-BUILD.json").read_bytes()).hexdigest()
        != runtime["embedded_client_build_sha256"]
    ):
        raise ValueError("Embedded client build record sidecar differs")
    for name, expected in runtime["notices"].items():
        if manifest["files"].get(name) != expected:
            raise ValueError("Required runtime copyright notice differs: " + name)
    if len(runtime["native_files"]) != 20 or len(runtime["components"]) != 12:
        raise ValueError("Unexpected embedded runtime inventory")
    control = json.loads((root / "release/CONTROLLED-RUNTIME.json").read_text())
    if (
        runtime["native_files"]["_lzma.pyd"]["sha256"]
        != control["test_lzma"]["runtime_lzma_sha256"]
    ):
        raise ValueError("Frozen XZ extension does not match the tested controlled runtime")
    if control["xz"] != "5.8.4" or len(control["upstream_regressions"]) != 2:
        raise ValueError("Missing patched XZ source/regression identity")
    if (
        hashlib.sha256((root / "release/CONTROLLED-RUNTIME.json").read_bytes()).hexdigest()
        != (runtime["controlled_source_proof"]["control_record_sha256"])
    ):
        raise ValueError("Controlled source provenance differs")
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
