"""Compile the Creo-side service and write the registry file Creo loads it from.

The jar is built against the `otk.jar` in a real Creo installation and is never
bundled with one: that library is PTC's, and pinning a copy would also pin a Creo
version. The build records which installation it compiled against so a jar can be
traced back to it.

  python scripts/build_otk_service.py --creo "<Creo load point>" [--java-home <jdk>]
  python scripts/build_otk_service.py --creo "<...>" --register <dir>

`--register` additionally writes a `protk.dat` into the given directory. Creo reads
that file from its startup directory, so writing it into the working directory Creo
is launched from is what makes the application appear under Auxiliary Applications.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import io
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "otk_service"
SOURCE = SERVICE / "src"
BUILD = SERVICE / "build"
JAR_NAME = "creo-cli-otk.jar"
APP_NAME = "creo_cli_otk"
APP_CLASS = "com.fateforge.creocli.otk.Service"
OTK_JAR = ("Common Files", "text", "java", "otk.jar")
# Creo 13 hosts a Java 21 runtime for its own components; targeting an older release
# than the host runs on is safe, the reverse is not. 17 is comfortably below any Creo
# that ships Object TOOLKIT Java and keeps the jar loadable across versions.
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
            message += ("\n\nCreo keeps the jar open for the life of its session. Close Creo, or "
                        "use scripts/reload_otk_service.py --restart, which does it in order.")
        raise RuntimeError(message[:2000])


def sources() -> list[str]:
    return [str(p) for p in sorted(SOURCE.rglob("*.java"))]


def registry(classpath: Path, *, auto_start: bool = True) -> str:
    """The protk.dat Creo reads to find this application.

    `startup otk_java` and `toolkit object` are what distinguish an Object TOOLKIT
    Java application from a J-Link one; with `startup java` Creo would load it against
    the library that cannot create geometry.

    `delay_start` defaults to false so the service is simply there whenever Creo is.
    The alternative makes every session begin with a human opening a dialog and
    clicking Start, which is the kind of manual step this tool exists to remove --
    and it cannot be automated from outside, since it is a Creo UI action.
    """
    return "\n".join([
        f"name              {APP_NAME}",
        "startup           otk_java",
        "toolkit           object",
        "creo_type         parametric",
        f"java_app_class    {APP_CLASS}",
        f"java_app_classpath {classpath}",
        "java_app_start    start",
        "java_app_stop     stop",
        "allow_stop        true",
        f"delay_start       {'false' if auto_start else 'true'}",
        "end",
        "",
    ])


def otk_jar(creo: Path) -> Path:
    """The library to compile against, with the installer step named if it is absent."""
    jar = creo.joinpath(*OTK_JAR)
    if not jar.is_file():
        raise RuntimeError(f"otk.jar not found at {jar}; is 'Creo Object TOOLKIT Java' installed? "
                           f"see docs/CREO_SETUP.md")
    return jar


def build(creo: Path, java_home: Path | None = None) -> dict:
    """Compile and jar the service, recording which installation it was built against."""
    otk = otk_jar(creo)
    classes = BUILD / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    run([tool(java_home, "javac"), "--release", RELEASE, "-nowarn",
         "-cp", str(otk), "-d", str(classes), *sources()])
    jar = BUILD / JAR_NAME
    run([tool(java_home, "jar"), "--create", "--file", str(jar), "-C", str(classes), "."])
    return {"jar": str(jar), "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
            "compiled_against": str(otk),
            "otk_jar_sha256": hashlib.sha256(otk.read_bytes()).hexdigest(),
            "application": APP_NAME, "entry_class": APP_CLASS}


def write_registry(target: Path, jar: Path, *, auto_start: bool = True) -> Path:
    """Put protk.dat where Creo looks for it: the directory Creo starts in."""
    target.mkdir(parents=True, exist_ok=True)
    registry_file = target / "protk.dat"
    with io.open(registry_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(registry(jar, auto_start=auto_start))
    return registry_file


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creo", required=True, help="Creo load point, the directory holding 'Common Files'")
    p.add_argument("--java-home", help="JDK to compile with; defaults to javac on PATH")
    p.add_argument("--register", help="also write protk.dat into this directory; "
                                      "Creo reads it from the directory it starts in")
    p.add_argument("--manual-start", action="store_true",
                   help="require a human to press Start in Auxiliary Applications")
    a = p.parse_args()

    try:
        built = build(Path(a.creo).expanduser(),
                      Path(a.java_home).expanduser() if a.java_home else None)
        built["jar"] = str(Path(built["jar"]).relative_to(ROOT))
        if a.register:
            registry_file = write_registry(Path(a.register).expanduser(), BUILD / JAR_NAME,
                                           auto_start=not a.manual_start)
            built["registry"] = str(registry_file)
            built["auto_start"] = not a.manual_start
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}))
        return 1
    print(json.dumps({"ok": True, **built}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
