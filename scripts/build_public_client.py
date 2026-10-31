"""Build only the Windows client from a clean committed source and fixed runtime."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import sqlite3
import ssl
import struct
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    profile = json.loads((ROOT / "release/CLIENT-RUNTIME.json").read_text(encoding="utf-8"))
    if (
        platform.system() != "Windows"
        or struct.calcsize("P") != 8
        or platform.machine().upper() not in {"AMD64", "X86_64"}
    ):
        raise ValueError("The public client build is Windows x64 only")
    actual = {
        "python": platform.python_version(),
        "openssl": ssl.OPENSSL_VERSION,
        "sqlite": sqlite3.sqlite_version,
        "pyinstaller": importlib.metadata.version("pyinstaller"),
        "free_threaded": bool(sysconfig_value("Py_GIL_DISABLED")),
    }
    if actual != profile["required_build_versions"]:
        raise ValueError("Build runtime differs from the reviewed fixed profile")
    base_python = Path(sys.base_prefix)
    for relative, expected in profile["native_build_inputs"].items():
        if digest(base_python / relative) != expected["sha256"]:
            raise ValueError("Official runtime file differs: " + relative)
    pyinstaller_root = Path(
        importlib.metadata.distribution("pyinstaller").locate_file("PyInstaller")
    )
    bootloader = pyinstaller_root / "bootloader/Windows-64bit-intel/run.exe"
    if digest(bootloader) != profile["pyinstaller_bootloader_sha256"]:
        raise ValueError("Stock official PyInstaller bootloader differs")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        raise ValueError("Commit the reviewed source before building")
    if output.exists():
        raise ValueError("Use a new immutable build directory")
    output.mkdir(parents=True)
    exported = output / "source"
    exported.mkdir()
    archive_data = subprocess.check_output(["git", "archive", "--format=tar", source], cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive_data)) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            path = (exported / member.name).resolve()
            if not path.is_relative_to(exported):
                raise ValueError("Source archive path leaves build directory")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    source_files = {
        p.relative_to(exported).as_posix(): digest(p)
        for p in sorted((exported / "creo_cli").rglob("*.py"))
    }
    source_files["cli.py"] = digest(exported / "cli.py")
    source_files["CHANGELOG.md"] = digest(exported / "CHANGELOG.md")
    binding = {
        "schema": "creo-public-client-build/v1",
        "source_commit": source,
        "version": "1.1.0-beta.1",
        "runtime": actual,
        "runtime_distribution": profile["runtime_distribution"],
        "native_build_inputs": profile["native_build_inputs"],
        "pyinstaller_bootloader_sha256": digest(bootloader),
        "build_lock_sha256": digest(exported / "requirements-build.lock"),
        "source_files": source_files,
        "built_at_utc": datetime.now(UTC).isoformat(),
        "native_components_rebuilt": False,
        "stock_bootloader_security_checks": True,
    }
    binding_path = output / "CLIENT-BUILD.json"
    binding_path.write_text(json.dumps(binding, indent=2) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        "-I",
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "creo-cli",
        "--clean",
        "--noconfirm",
        "--collect-submodules",
        "creo_cli",
        "--distpath",
        str(output / "dist"),
        "--workpath",
        str(output / "work"),
        "--specpath",
        str(output / "spec"),
        "--add-data",
        f"{exported / 'CHANGELOG.md'}{os.pathsep}.",
        "--add-data",
        f"{exported / '.agent/driver/schemas'}{os.pathsep}.agent/driver/schemas",
        "--add-data",
        f"{binding_path}{os.pathsep}.",
        str(exported / "cli.py"),
    ]
    env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(output / "cache"))
    for name in list(env):
        if name.startswith(("CREO_CLI_", "PYI_", "_PYI_")):
            del env[name]
    with (output / "build.stdout").open("wb") as out, (output / "build.stderr").open("wb") as err:
        result = subprocess.run(command, cwd=exported, env=env, stdout=out, stderr=err)
    if result.returncode:
        raise RuntimeError("Client build failed; retained the original build logs")
    binary = output / "dist/creo-cli.exe"
    binding["exe"] = {"sha256": digest(binary), "bytes": binary.stat().st_size}
    binding["command"] = [
        "<fixed-python>",
        "-I",
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "creo-cli",
        "--clean",
        "--noconfirm",
        "--collect-submodules",
        "creo_cli",
        "--distpath",
        "<build>/dist",
        "--workpath",
        "<build>/work",
        "--specpath",
        "<build>/spec",
        "--add-data",
        "CHANGELOG.md;.",
        "--add-data",
        ".agent/driver/schemas;.agent/driver/schemas",
        "--add-data",
        "<build>/CLIENT-BUILD.json;.",
        "cli.py",
    ]
    (output / "BUILD-RESULT.json").write_text(
        json.dumps(binding, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"source_commit": source, "exe": binding["exe"], "runtime": actual}))


def sysconfig_value(name):
    import sysconfig

    return sysconfig.get_config_var(name)


if __name__ == "__main__":
    main()
