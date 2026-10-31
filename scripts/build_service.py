"""Compile the Creo-side service and write the registry file Creo loads it from.

The jar is built against the `otk.jar` in a real Creo installation and is never
bundled with one: that library is PTC's, and pinning a copy would also pin a Creo
version. The build records which installation it compiled against so a jar can be
traced back to it.

  python scripts/build_service.py --creo "<Creo load point>" [--java-home <jdk>]
  python scripts/build_service.py --creo "<...>" --register <dir>

`--register` additionally writes a `protk.dat` into the given directory. Creo reads
that file from its startup directory, so writing it into the working directory Creo
is launched from is what makes the application appear under Auxiliary Applications.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import locale
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creo_cli import service_bundle  # noqa: E402

SERVICE = ROOT / "service"
SOURCE = SERVICE / "src"
BUILD = SERVICE / "build"
JAR_NAME = "creo-cli-service.jar"
APP_NAME = "creo_cli_service"
APP_CLASS = "com.fateforge.creocli.service.Service"
NATIVE_APP_NAME = "creo_cli_sketch"
OTK_JAR = ("Common Files", "text", "java", "otk.jar")
# This is a bytecode target, not runtime or cross-Creo qualification. Actual component
# evidence is tied to the declared licensed Creo 13.4.1.0 / JDK 25.0.3 host.
RELEASE = "17"


def tool(java_home: Path | None, name: str) -> str:
    if java_home:
        candidate = java_home / "bin" / name
        return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"{name} not found; pass --java-home")
    return found


def decode(raw: bytes) -> str:
    """Decode tool output the way this console produced it.

    The JDK writes messages in the system's ANSI code page, not UTF-8, so on a Chinese
    or Japanese Windows a UTF-8 read turns the one thing that explains a failure into
    replacement characters.
    """
    for encoding in (locale.getpreferredencoding(False), "utf-8"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        message = (decode(result.stderr) or decode(result.stdout) or "command failed").strip()
        if "jar" in command[0] and ("move" in message or "FileSystemException" in message):
            message += (
                "\n\nCreo keeps the jar open for the life of its session. Close Creo, or "
                "retain this generation and build a separate candidate; the build tool "
                "does not stop Creo or replace a loaded component."
            )
        raise RuntimeError(message[:2000])


def sources() -> list[str]:
    return [str(p) for p in sorted(SOURCE.rglob("*.java"))]


def registry(classpath: Path, *, auto_start: bool = True, native_dll: Path | None = None) -> str:
    """The protk.dat Creo reads to find the service; written by one function, which
    `creo-cli service install` uses too (creo_cli/service_bundle.py)."""
    return service_bundle.registry(classpath, auto_start=auto_start, native_dll=native_dll)


def otk_jar(creo: Path) -> Path:
    """The library to compile against, with the installer step named if it is absent."""
    jar = creo.joinpath(*OTK_JAR)
    if not jar.is_file():
        raise RuntimeError(
            f"otk.jar not found at {jar}; is 'Creo Object TOOLKIT Java' installed? "
            f"see docs/CREO_SETUP.md"
        )
    return jar


def compile_into(
    creo: Path,
    java_home: Path | None,
    classes: Path,
    *,
    namespace: str = "",
    runtime_profile: dict | None = None,
) -> Path:
    otk = otk_jar(creo)
    classes.mkdir(parents=True, exist_ok=True)
    material = {
        str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(SOURCE.rglob("*.java"))
    }
    native = ROOT / "service" / "native" / "creo_cli_sketch.c"
    material["service/native/creo_cli_sketch.c"] = hashlib.sha256(native.read_bytes()).hexdigest()
    if namespace and not re.fullmatch(
        r"com\.fateforge\.creocli\.service\.g[a-f0-9]{8,32}", namespace
    ):
        raise ValueError("runtime namespace must be a unique service-generation package")
    parameters = {"namespace": namespace, "runtime_profile": runtime_profile or {}}
    source_hash = hashlib.sha256(
        json.dumps(
            {"files": material, "build_parameters": parameters},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    generated = classes.parent / (classes.name + "-source")
    generated.mkdir(parents=True, exist_ok=True)
    identity = generated / "BuildIdentity.java"
    identity.write_text(
        "package com.fateforge.creocli.service;\nfinal class BuildIdentity {\n"
        f'    static final String SOURCE_SHA256 = "{source_hash}";\n'
        "    private BuildIdentity() { }\n}\n",
        encoding="utf-8",
    )
    compile_sources = []
    effective = {}
    for raw in sources():
        path = Path(raw)
        if path.name == "BuildIdentity.java":
            continue
        content = path.read_text(encoding="utf-8")
        if path.name == "RuntimeProfile.java" and runtime_profile:
            state = json.dumps(runtime_profile["state_directory"])
            native_id = json.dumps(runtime_profile["native_id_file"])
            port = runtime_profile["port"]
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError("runtime port is outside the supported range")
            content = content.replace('STATE_DIRECTORY = ""', "STATE_DIRECTORY = " + state)
            content = content.replace('NATIVE_ID_FILE = ""', "NATIVE_ID_FILE = " + native_id)
            content = content.replace("PORT = 0", "PORT = " + str(port))
        if namespace:
            content = content.replace("com.fateforge.creocli.service", namespace)
        retained = generated / path.name
        retained.write_text(content, encoding="utf-8", newline="\n")
        effective[path.name] = hashlib.sha256(retained.read_bytes()).hexdigest()
        compile_sources.append(str(retained))
    if namespace:
        identity.write_text(
            identity.read_text(encoding="utf-8").replace(
                "com.fateforge.creocli.service", namespace
            ),
            encoding="utf-8",
            newline="\n",
        )
    effective[identity.name] = hashlib.sha256(identity.read_bytes()).hexdigest()
    compile_sources.append(str(identity))
    (generated / "source-lock.json").write_text(
        json.dumps(
            {
                "source_sha256": source_hash,
                "files": material,
                "build_parameters": parameters,
                "effective_java_source_files": effective,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # The sources are UTF-8. Without saying so, a javac older than JDK 18 reads them in the
    # system's ANSI code page -- GBK on a Chinese Windows -- and rejects the first dash in
    # a comment.
    run(
        [
            tool(java_home, "javac"),
            "--release",
            RELEASE,
            "-nowarn",
            "-encoding",
            "UTF-8",
            "-cp",
            str(otk),
            "-d",
            str(classes),
            *compile_sources,
        ]
    )
    return otk


def check_compiles(creo: Path, java_home: Path | None = None) -> None:
    """Compile into a scratch directory, touching nothing a running Creo holds open."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="creo-cli-service-") as scratch:
        compile_into(creo, java_home, Path(scratch))


def build(
    creo: Path,
    java_home: Path | None = None,
    *,
    namespace: str = "",
    runtime_profile: dict | None = None,
) -> dict:
    """Compile and jar the service, recording which installation it was built against."""
    classes = BUILD / "classes"
    expected = ROOT.resolve() / "service" / "build" / "classes"
    if classes.resolve() != expected or classes.is_symlink():
        raise RuntimeError(
            "classes directory does not resolve to this repository's build directory"
        )
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    otk = compile_into(
        creo, java_home, classes, namespace=namespace, runtime_profile=runtime_profile
    )
    jar = BUILD / JAR_NAME
    run([tool(java_home, "jar"), "--create", "--file", str(jar), "-C", str(classes), "."])
    return {
        "jar": str(jar),
        "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
        "compiled_against": str(otk),
        "otk_jar_sha256": hashlib.sha256(otk.read_bytes()).hexdigest(),
        "application": APP_NAME,
        "entry_class": APP_CLASS,
    }


def write_registry(
    target: Path, jar: Path, *, auto_start: bool = True, native_dll: Path | None = None
) -> Path:
    """Put protk.dat where Creo looks for it: the directory Creo starts in."""
    target.mkdir(parents=True, exist_ok=True)
    registry_file = target / "protk.dat"
    with open(registry_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(registry(jar, auto_start=auto_start, native_dll=native_dll))
    return registry_file


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--creo", required=True, help="Creo load point, the directory holding 'Common Files'"
    )
    p.add_argument("--java-home", help="JDK to compile with; defaults to javac on PATH")
    p.add_argument(
        "--register",
        help="also write protk.dat into this directory; "
        "Creo reads it from the directory it starts in",
    )
    p.add_argument(
        "--manual-start",
        action="store_true",
        help="require a human to press Start in Auxiliary Applications",
    )
    a = p.parse_args()

    try:
        built = build(
            Path(a.creo).expanduser(), Path(a.java_home).expanduser() if a.java_home else None
        )
        built["jar"] = str(Path(built["jar"]).relative_to(ROOT))
        if a.register:
            registry_file = write_registry(
                Path(a.register).expanduser(), BUILD / JAR_NAME, auto_start=not a.manual_start
            )
            built["registry"] = str(registry_file)
            built["auto_start"] = not a.manual_start
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}))
        return 1
    print(json.dumps({"ok": True, **built}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
