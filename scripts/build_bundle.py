"""Package retained, unlocked component bytes without starting or stopping Creo.

Use --candidate from build_acceptance_bundle.py. Proprietary SDK/Java/Creo binaries,
credentials and the machine's license files are external dependencies, never bundled.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creo_cli import __version__, service_bundle, transport  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate", type=Path, required=True, help="retained successful candidate.json"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="new output parent; existing bundles are refused"
    )
    parser.add_argument("--creo-version", default="13.4.1.0")
    parser.add_argument("--creo-build", default="2026163")
    args = parser.parse_args()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if candidate.get("success") is not True:
        raise ValueError("candidate build/unlock did not complete")
    if candidate.get("runtime_profile"):
        raise ValueError(
            "fixed-path development profiles are not movable; build without runtime-state"
        )
    lock = candidate["source_lock"]
    if lock["build_parameters"].get("runtime_profile"):
        raise ValueError("source lock contains fixed runtime paths")
    payloads = {
        service_bundle.JAR: Path(candidate["files"]["jar"]["path"]),
        service_bundle.DLL: Path(candidate["files"]["native"]["path"]),
    }
    for key, name in (("jar", service_bundle.JAR), ("native", service_bundle.DLL)):
        if service_bundle.sha256(payloads[name]) != candidate["files"][key]["sha256"]:
            raise ValueError("retained component bytes changed: " + name)
    with ZipFile(payloads[service_bundle.JAR]) as jar:
        if not {"META-INF/PTC.SF", "META-INF/PTC.DSA"} <= set(jar.namelist()):
            raise ValueError("retained Java component lacks its PTC unlock entries")
    name = "creo-cli-service-" + __version__
    output = args.output.resolve() / name
    archive = output.with_suffix(output.suffix + ".zip")
    if output.exists() or archive.exists():
        raise ValueError("bundle output already exists; choose a new directory")
    output.mkdir(parents=True)
    for filename, original in payloads.items():
        shutil.copyfile(original, output / filename)
    manifest = service_bundle.manifest_for(
        output,
        version=__version__,
        protocol=transport.PROTOCOL,
        creo={
            "version": args.creo_version,
            "build": args.creo_build,
            "arch": "x86_64",
            "platform": "Windows",
        },
    )
    manifest.update(
        java_app_class=candidate["app_class"],
        component_source_sha256=lock["source_sha256"],
        build_source=lock,
        runtime_profile={
            "mode": "environment",
            "state_directory_variable": "CREO_CLI_CONFIG_DIR",
            "port_variable": "CREO_CLI_SERVICE_PORT",
            "embedded_fixed_paths": False,
        },
        dependencies={
            "creo": "existing licensed compatible installation",
            "java_major": 25,
            "java_selection_variable": "PRO_JAVA_COMMAND",
            "object_toolkit_java": "provided by Creo",
            "native_runtime": "provided by the licensed supported host",
        },
        limitations=[
            "copy verification is separate from actual Creo loading and engineering results",
            "same licensed host relocation; clean-machine, cross-version "
            "and redistribution rights not certified",
        ],
    )
    (output / service_bundle.MANIFEST).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    with ZipFile(archive, "x", ZIP_DEFLATED) as zipped:
        for file in sorted(output.iterdir()):
            zipped.write(file, name + "/" + file.name)
    print(
        json.dumps(
            {
                "ok": True,
                "bundle": str(output),
                "zip": str(archive),
                "component_source_sha256": lock["source_sha256"],
                "files": manifest["files"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        raise SystemExit(1) from None
