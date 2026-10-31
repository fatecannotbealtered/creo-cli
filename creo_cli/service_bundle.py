"""The service bundle: the unlocked jar and native library a licensed machine builds, and what
it takes to put them where Creo can load them.

A bundle is a directory or a .zip holding `manifest.json`, `creo-cli-service.jar` and,
optionally, `creo_cli_sketch.dll`. The manifest names the protocol the service speaks and
the SHA-256 of every file; nothing is installed that does not match it. Installing copies
the files into an owned directory and writes an auto-start `protk.dat`; launching a new
owned Creo from a private startup directory remains an explicit separate step.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .core import Error, atomic_write

JAR = "creo-cli-service.jar"
DLL = "creo_cli_sketch.dll"
MANIFEST = "manifest.json"
APP_NAME = "creo_cli_service"
APP_CLASS = "com.fateforge.creocli.service.Service"
NATIVE_APP_NAME = "creo_cli_sketch"
MAX_FILE = 64 * 1024 * 1024
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]{1,40})?$")


def registry(
    classpath: Path,
    *,
    auto_start: bool = True,
    native_dll: Path | None = None,
    app_class: str = APP_CLASS,
) -> str:
    """The protk.dat Creo reads to find the service.

    `startup otk_java` and `toolkit object` are what make it an Object TOOLKIT Java
    application; with `startup java` Creo would load it against the library that cannot
    create geometry. `delay_start false`: the service is there whenever Creo is, with no
    dialog to click. `fail_tol true` on every entry: without it, an application whose start
    fails makes Creo shut itself down, with the user's work, by design. The native sketch
    library is its own DLL entry; Creo loads it from the path given here.
    """
    lines = []
    if native_dll is not None:
        lines += [
            f"name              {NATIVE_APP_NAME}",
            "startup           dll",
            f"exec_file         {native_dll}",
            f"text_dir          {native_dll.parent}",
            "allow_stop        true",
            "fail_tol          true",
            "delay_start       false",
            "end",
        ]
    lines += [
        f"name              {APP_NAME}",
        "startup           otk_java",
        "toolkit           object",
        "creo_type         parametric",
        f"java_app_class    {app_class}",
        f"java_app_classpath {classpath}",
        "java_app_start    start",
        "java_app_stop     stop",
        "allow_stop        true",
        "fail_tol          true",
        f"delay_start       {'false' if auto_start else 'true'}",
        "end",
    ]
    return "\n".join(lines + [""])


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_for(directory: Path, *, version: str, protocol: int, creo: dict) -> dict:
    files = {}
    for name in (JAR, DLL):
        p = directory / name
        if p.is_file():
            files[name] = {"sha256": sha256(p), "bytes": p.stat().st_size}
    return {
        "tool": "creo-cli",
        "service_version": version,
        "protocol": protocol,
        "built_for": creo,
        "unlocked": True,
        "files": files,
    }


def open_bundle(source: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    """The bundle's directory; a .zip is unpacked into a private temporary one first."""
    if source.is_dir():
        return source, None
    if source.suffix.lower() != ".zip" or not source.is_file():
        raise Error(
            "E_VALIDATION",
            "a service bundle is a directory or a .zip",
            {"path": str(source), "_untrusted": ["path"]},
        )
    scratch = tempfile.TemporaryDirectory(prefix="creo-cli-bundle-")
    root = Path(scratch.name)
    try:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                leaf = name.rsplit("/", 1)[-1]
                if info.is_dir() or leaf not in (MANIFEST, JAR, DLL):
                    continue
                if info.file_size > MAX_FILE:
                    raise Error(
                        "E_VALIDATION", "a bundle file is larger than 64 MiB", {"file": leaf}
                    )
                with archive.open(info) as src, (root / leaf).open("xb") as dst:
                    shutil.copyfileobj(src, dst)
    except (OSError, zipfile.BadZipFile) as exc:
        scratch.cleanup()
        raise Error(
            "E_VALIDATION", "the bundle cannot be read as a zip", {"reason": type(exc).__name__}
        ) from exc
    except Error:
        scratch.cleanup()
        raise
    return root, scratch


def read(directory: Path, protocol: int) -> dict:
    """The bundle's manifest, checked against its files and against this CLI."""
    try:
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Error(
            "E_VALIDATION",
            "the bundle has no readable manifest.json",
            {"path": str(directory), "_untrusted": ["path"]},
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("tool") != "creo-cli":
        raise Error("E_VALIDATION", "the manifest is not a creo-cli service bundle's")
    version = manifest.get("service_version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise Error("E_VALIDATION", "the manifest names no valid service_version")
    if manifest.get("protocol") != protocol:
        raise Error(
            "E_CONFLICT",
            "the bundle's service speaks another protocol than this CLI",
            {"bundle_protocol": manifest.get("protocol"), "cli_protocol": protocol},
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or JAR not in files or set(files) - {JAR, DLL}:
        raise Error(
            "E_VALIDATION", "the manifest must list the service jar, and at most the sketch DLL"
        )
    for name, expected in files.items():
        p = directory / name
        if not p.is_file():
            raise Error(
                "E_VALIDATION", "the bundle lacks a file its manifest lists", {"file": name}
            )
        if p.stat().st_size > MAX_FILE or sha256(p) != (expected or {}).get("sha256"):
            raise Error(
                "E_INTEGRITY",
                "a bundle file does not match the manifest's SHA-256",
                {"file": name},
            )
    return manifest


def install(directory: Path, manifest: dict, target: Path) -> dict:
    """Copy the files into `target` and write protk.dat there. A target that already holds
    the same files is left as it is; one that holds other files is refused."""
    files = manifest["files"]
    complete = (target / MANIFEST).is_file()
    if complete:
        same = all(
            (target / n).is_file() and sha256(target / n) == f["sha256"] for n, f in files.items()
        )
        if not same:
            raise Error(
                "E_CONFLICT",
                "another build of this service version is already installed there",
                {"path": str(target), "_untrusted": ["path"]},
            )
    dll = target / DLL if DLL in files else None
    registry_file = target / "protk.dat"
    try:
        if not complete:
            # Files are copied in place and the manifest written last, so a target without one
            # is an interrupted install and is simply done again. Renaming a directory holding
            # a new DLL is refused while a virus scanner still has it open, so nothing is
            # renamed.
            target.mkdir(parents=True, exist_ok=True)
            for name, expected in files.items():
                shutil.copyfile(directory / name, target / name)
                if sha256(target / name) != expected["sha256"]:
                    raise Error("E_IO", "a copied file does not match its manifest", {"file": name})
            atomic_write(target / MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode())
        atomic_write(registry_file, registry(target / JAR, native_dll=dll).encode())
    except OSError as exc:
        # Nothing counts as installed without its manifest and protk.dat, so an install cut
        # short leaves what was installed as it was; installing again finishes it.
        raise Error(
            "E_IO",
            "the bundle could not be copied into place; install it again once the file is free",
            {"path": str(target), "reason": str(exc), "_untrusted": ["path", "reason"]},
        ) from exc
    return {
        "installed_to": str(target),
        "protk_dat": str(registry_file),
        "files": {n: str(target / n) for n in files},
    }


def installed(root: Path) -> list[dict]:
    """The service versions installed under creo-cli's own directory."""
    out = []
    base = root / "service"
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir()):
        m = child / MANIFEST
        if child.is_dir() and m.is_file() and (child / "protk.dat").is_file():
            try:
                manifest = json.loads(m.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append(
                {
                    "version": manifest.get("service_version"),
                    "protocol": manifest.get("protocol"),
                    "protk_dat": str(child / "protk.dat"),
                }
            )
    return out
