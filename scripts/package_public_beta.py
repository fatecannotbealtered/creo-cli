"""Repack the reviewed Windows beta without rebuilding or publishing components."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0-beta.1"
INPUT_SHA256 = "418bf4717d5f3b82b7c77e866cd7fa783019c172e5f65b697355d2504991264e"
COMPONENTS = {
    "cli/creo-cli.exe": (
        "18d7eb7dfee41cc0ebae5d78140f6a42c92c19b835c3ce9af4d600d3540a8798",
        "8049e16f0ffcf6b84188f037f94d6d0f57f85274",
    ),
    "cli/service-bundle/creo-cli-service.jar": (
        "bbc5f5a9952876aebb726f29d53d67b509278c91d4d2a3a66386f3f2270cae39",
        "156a619cecdb17714481a7dbe2807ebc1a2d8699",
    ),
    "cli/service-bundle/creo_cli_sketch.dll": (
        "3aaba42f693550fd6cdcc9d49521a0e17669f3e50af7702ab67a8bae42f6ea7f",
        "156a619cecdb17714481a7dbe2807ebc1a2d8699",
    ),
}
COPY_FROM_ORIGINAL = [
    *COMPONENTS,
    "BUILD-BINDING.json",
    "cli/deployment/native-preparation.json",
    "cli/service-bundle/manifest.json",
    "cli/service-bundle/source-lock.json",
    "cli/service-bundle/protk.dat",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def package(original: Path, output: Path):
    if sha(original.read_bytes()) != INPUT_SHA256:
        raise ValueError("Original package hash differs from the reviewed source")
    if output.exists():
        raise ValueError("Use a new output directory; preserve existing candidates")
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise ValueError("Freeze a clean source snapshot before packaging")
    # Committed blobs exclude ignored local material and checkout-specific line endings.
    with tarfile.open(
        fileobj=io.BytesIO(
            subprocess.check_output(["git", "archive", "--format=tar", source_commit], cwd=ROOT)
        )
    ) as source_archive:
        snapshot = {
            member.name: source_archive.extractfile(member).read()
            for member in source_archive.getmembers()
            if member.isfile()
        }

    def copy_snapshot(source, destination):
        if source in snapshot:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(snapshot[source])
            return
        prefix = source.rstrip("/") + "/"
        for name, data in snapshot.items():
            if name.startswith(prefix):
                path = destination / name.removeprefix(prefix)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    output.mkdir(parents=True)
    bundle = output / ("creo-cli-" + VERSION + "-windows-x64")
    bundle.mkdir()
    with zipfile.ZipFile(original) as archive:
        roots = {PurePosixPath(n).parts[0] for n in archive.namelist()}
        if len(roots) != 1:
            raise ValueError("Expected one original package root")
        prefix = roots.pop() + "/"
        for name in COPY_FROM_ORIGINAL:
            data = archive.read(prefix + name)
            if name in COMPONENTS and sha(data) != COMPONENTS[name][0]:
                raise ValueError("Component identity mismatch: " + name)
            path = bundle / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    for source, destination in [
        ("README.md", "README.md"),
        ("README_zh.md", "README_zh.md"),
        ("LICENSE", "LICENSE"),
        ("NOTICE.md", "NOTICE.md"),
        ("CHANGELOG.md", "cli/CHANGELOG.md"),
        ("knowledge", "cli/knowledge"),
        ("skills", "cli/skills"),
        ("docs", "cli/docs"),
        (".agent/driver", "cli/.agent/driver"),
        ("release/RELEASE-NOTES.md", "RELEASE-NOTES.md"),
    ]:
        copy_snapshot(source, bundle / destination)
    for name in [
        "Initialize-CreoWorkspace.ps1",
        "Start-CreoWorkspace.ps1",
        "Initialize-InternalTrial.ps1",
        "Start-InternalTrial.ps1",
        "InternalUnsignedPreflight.ps1",
        "RecoveryIsolation.ps1",
        "Invoke-CreoCli.ps1",
        "Invoke-CreoCli.md",
        "start-owned-creo.ps1",
        "Start-OwnedCreoProcess.ps1",
    ]:
        dst = bundle / "cli/examples/engineering" / name
        copy_snapshot("examples/engineering/" + name, dst)
    # Root documentation paths work both in the archive and in the source repository.
    for name in ["RUNTIME-DEPENDENCIES.md", "STARTUP-NATIVE.md"]:
        dst = bundle / "docs" / name
        copy_snapshot("docs/" + name, dst)
    copy_snapshot("docs/licenses", bundle / "docs/licenses")
    for source, dest in [
        (".agent/driver", ".agent/driver"),
        ("release/RELEASE-NOTES.md", "release/RELEASE-NOTES.md"),
    ]:
        copy_snapshot(source, bundle / dest)
    (bundle / "docs/STARTUP-NATIVE.md").write_text(
        snapshot["docs/STARTUP-NATIVE.md"]
        .decode("utf-8")
        .replace("../examples/engineering/", "../cli/examples/engineering/"),
        encoding="utf-8",
    )
    # A full CLI-directory notice keeps attribution with a separately copied CLI folder.
    for name in ("LICENSE", "NOTICE.md"):
        copy_snapshot(name, bundle / "cli" / name)
    origins = {
        "schema": "creo-component-origins/v1",
        "version": VERSION,
        "recompiled_components": [],
        "deployment_helpers_public_commit": source_commit,
        "components": {
            name: {
                "sha256": digest,
                "bytes": (bundle / name).stat().st_size,
                "build_source_commit": commit,
                "rebuilt": False,
            }
            for name, (digest, commit) in COMPONENTS.items()
        },
        "scope": (
            "Repack of unchanged components; helper-only changes add no native qualification"
        ),
    }
    write_json(bundle / "COMPONENT-ORIGINS.json", origins)
    # No raw project, image, receipt, host path or private publishing configuration is copied.
    forbidden = {"PROJECTS", "EXAMPLES", "review-evidence", "development", ".git", ".codex", ".aws"}
    files = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(bundle).as_posix()
        if forbidden.intersection(path.relative_to(bundle).parts):
            raise ValueError("Forbidden payload directory: " + name)
        data = path.read_bytes()
        files[name] = {"sha256": sha(data), "bytes": len(data)}
    write_json(
        bundle / "PACKAGE-MANIFEST.json",
        {
            "schema": "creo-public-package/v1",
            "version": VERSION,
            "target": "windows-x64",
            "prerelease": True,
            "files": files,
        },
    )
    archive = output / (bundle.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as packed:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo(
                    path.relative_to(output).as_posix(), date_time=(2026, 10, 31, 0, 0, 0)
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                packed.writestr(info, path.read_bytes())
    result = {
        "archive": archive.name,
        "sha256": sha(archive.read_bytes()),
        "bytes": archive.stat().st_size,
        "payload_files": len(files) + 1,
        "components": origins["components"],
        "published": False,
    }
    write_json(output / "ARTIFACTS.json", result)
    (output / "checksums.txt").write_text(
        result["sha256"] + "  " + archive.name + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.original, args.output)))
