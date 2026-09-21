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


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip()[:2000])


def sources() -> list[str]:
    return [str(p) for p in sorted(SOURCE.rglob("*.java"))]


def registry(classpath: Path) -> str:
    """The protk.dat Creo reads to find this application.

    `startup otk_java` and `toolkit object` are what distinguish an Object TOOLKIT
    Java application from a J-Link one; with `startup java` Creo would load it against
    the library that cannot create geometry. `delay_start true` keeps Creo's own
    startup unaffected -- the application is started deliberately from Auxiliary
    Applications rather than every time anyone opens Creo.
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
        "delay_start       true",
        "end",
        "",
    ])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creo", required=True, help="Creo load point, the directory holding 'Common Files'")
    p.add_argument("--java-home", help="JDK to compile with; defaults to javac on PATH")
    p.add_argument("--register", help="also write protk.dat into this directory")
    a = p.parse_args()

    creo = Path(a.creo).expanduser()
    otk = creo.joinpath(*OTK_JAR)
    java_home = Path(a.java_home).expanduser() if a.java_home else None
    try:
        if not otk.is_file():
            raise RuntimeError(f"otk.jar not found at {otk}; is 'Creo Object TOOLKIT Java' installed? "
                               f"see docs/CREO_SETUP.md")
        classes = BUILD / "classes"
        if classes.exists():
            shutil.rmtree(classes)
        classes.mkdir(parents=True)
        run([tool(java_home, "javac"), "--release", RELEASE, "-nowarn",
             "-cp", str(otk), "-d", str(classes), *sources()])
        jar = BUILD / JAR_NAME
        run([tool(java_home, "jar"), "--create", "--file", str(jar), "-C", str(classes), "."])
        written = {"jar": str(jar.relative_to(ROOT))}
        if a.register:
            target = Path(a.register).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            registry_file = target / "protk.dat"
            with io.open(registry_file, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(registry(jar))
            written["registry"] = str(registry_file)
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}))
        return 1
    print(json.dumps({"ok": True, **written,
                      "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
                      "compiled_against": str(otk),
                      "otk_jar_sha256": hashlib.sha256(otk.read_bytes()).hexdigest(),
                      "application": APP_NAME, "entry_class": APP_CLASS}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
