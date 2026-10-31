"""Package the reviewed rebuilt client and unchanged native components; never publish."""

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
        "cd3c18cbc139dfb85b0c9f20ac9a30734b81d29385a9d7a87379ad097d771668",
        "87ad66e6e5d6a549545620b4d8899ef7176f32e5",
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
    *(n for n in COMPONENTS if n != "cli/creo-cli.exe"),
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


def package(original: Path, client: Path, output: Path):
    if sha(original.read_bytes()) != INPUT_SHA256:
        raise ValueError("Original package hash differs from the reviewed source")
    if output.exists():
        raise ValueError("Use a new output directory; preserve existing candidates")
    if sha(client.read_bytes()) != COMPONENTS["cli/creo-cli.exe"][0]:
        raise ValueError("Client differs from the reviewed rebuild")
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
                if name in {
                    "docs/licenses/PYTHON-3.12.10-LICENSE.md",
                    "docs/licenses/PYINSTALLER-6.21.0-COPYING.md",
                }:
                    continue
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
    (bundle / "cli/creo-cli.exe").write_bytes(client.read_bytes())
    artifact = json.loads(snapshot["release/CLIENT-ARTIFACT.json"])
    runtime = json.loads(snapshot["release/RUNTIME-DISTRIBUTION.json"])
    if (
        artifact["source_commit"] != COMPONENTS["cli/creo-cli.exe"][1]
        or artifact["exe"] != runtime["client"]
        or artifact["exe"]["sha256"] != sha(client.read_bytes())
        or runtime["client_source_commit"] != artifact["source_commit"]
    ):
        raise ValueError("Client, build record and actual embedded-runtime inventory differ")
    binding_path = bundle / "BUILD-BINDING.json"
    binding = json.loads(binding_path.read_bytes())
    binding.update(
        schema="creo.public.beta-binding.v1",
        client_source_commit=artifact["source_commit"],
        deployment_helper_source_commit=source_commit,
        initializer_revision="public-" + VERSION,
        qualification=(
            "Rebuilt client checked offline; original JAR/DLL retained. "
            "No new native CAD qualification."
        ),
        baseline_package_sha256=INPUT_SHA256,
    )
    binding["components"]["EXE"] = artifact["exe"]
    write_json(binding_path, binding)
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
        ("release/CLIENT-BUILD.json", "CLIENT-BUILD.json"),
        ("release/CLIENT-ARTIFACT.json", "CLIENT-ARTIFACT.json"),
        ("release/RUNTIME-DISTRIBUTION.json", "RUNTIME-DISTRIBUTION.json"),
        ("release/COPYRIGHT-SOURCES.json", "release/COPYRIGHT-SOURCES.json"),
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
    for name in ("CLIENT-BUILD.json", "CLIENT-ARTIFACT.json", "RUNTIME-DISTRIBUTION.json"):
        copy_snapshot("release/" + name, bundle / "cli" / name)
    origins = {
        "schema": "creo-component-origins/v1",
        "version": VERSION,
        "recompiled_components": ["cli/creo-cli.exe"],
        "deployment_helpers_public_commit": source_commit,
        "components": {
            name: {
                "sha256": digest,
                "bytes": (bundle / name).stat().st_size,
                "build_source_commit": commit,
                "rebuilt": name == "cli/creo-cli.exe",
            }
            for name, (digest, commit) in COMPONENTS.items()
        },
        "scope": (
            "Only the client is rebuilt. Native JAR/DLL retain original bytes and build source; "
            "offline checks add no native qualification"
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
    parser.add_argument("--client", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.original, args.client, args.output)))
