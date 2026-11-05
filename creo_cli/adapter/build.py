"""Build the host component on the user's computer, during `plugin install`.

creo-cli ships the host component as source (plugin/src) and no binary. An Object TOOLKIT Java
application must be unlocked with the PTC tool `protk_unlock` before Creo loads it from a seat
without a development license, and an unlocked file must not change afterwards. So the JAR is
compiled with the user's JDK 25 against the user's own `otk.jar`, and unlocked there with the
user's license: the Creo Object TOOLKIT Java development license, or its extension license with
a Creo TOOLKIT license (PTC, "Unlocking, Running and Signing the Creo Object TOOLKIT Java
Application"). Nothing signed with somebody else's license is distributed.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .._driver import AdapterError

APP_CLASS = "com.fateforge.creocli.host.Host"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
UNLOCK_TIMEOUT_S = 50


def source_digest(sources: Path) -> str:
    """One SHA-256 over every source file, by its path below plugin/src and its bytes."""
    digest = hashlib.sha256()
    for path in sorted(sources.rglob("*.java")):
        digest.update(path.relative_to(sources).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def find_jdk() -> Path | None:
    """A JDK 25 home: CREO_CLI_JDK, the JDK of PRO_JAVA_COMMAND (the Java Creo runs its
    applications with), or JAVA_HOME. otk.jar of Creo 13.4 is built for Java 25."""
    candidates = [os.environ.get("CREO_CLI_JDK")]
    if os.environ.get("PRO_JAVA_COMMAND"):
        candidates.append(str(Path(os.environ["PRO_JAVA_COMMAND"]).parent.parent))
    candidates.append(os.environ.get("JAVA_HOME"))
    for candidate in candidates:
        if not candidate:
            continue
        javac = Path(candidate) / "bin" / "javac.exe"
        if not javac.is_file():
            continue
        try:
            out = subprocess.run([str(javac), "-version"], capture_output=True, text=True, timeout=30,
                                 creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        words = (out.stdout + out.stderr).strip().split()
        if words and words[-1].split(".")[0] == "25":
            return Path(candidate)
    return None


def build(sources: Path, common_files: Path, jar: Path) -> None:
    """Compile ``sources``, package them and unlock the JAR, then put it at ``jar``. On any
    failure nothing is written at ``jar``."""
    jdk = find_jdk()
    if jdk is None:
        raise AdapterError("E_UNSUPPORTED", "plugin install builds the host component with a JDK 25, and none was found. "
                           "Install one and set CREO_CLI_JDK to its folder.", dispatch_state="not_started")
    otk = common_files / "text" / "java" / "otk.jar"
    unlock = common_files.parent / "Parametric" / "bin" / "protk_unlock.bat"
    for needed in (otk, unlock):
        if not needed.is_file():
            raise AdapterError("E_UNSUPPORTED", f"The Creo installation has no {needed.name} at {needed.parent}; "
                               "install Object TOOLKIT Java with Creo.", dispatch_state="not_started")
    with tempfile.TemporaryDirectory(prefix="creo-cli-host-") as work:
        classes = Path(work) / "classes"
        built = Path(work) / jar.name
        files = sorted(str(p) for p in sources.rglob("*.java"))
        _run([str(jdk / "bin" / "javac.exe"), "--release", "25", "-encoding", "UTF-8", "-cp", str(otk),
              "-d", str(classes), *files], "compiling the host component")
        _run([str(jdk / "bin" / "jar.exe"), "--create", "--file", str(built), "-C", str(classes), "."],
             "packaging the host component")
        environment = dict(os.environ)
        environment.pop("NoDefaultCurrentDirectoryInExePath", None)  # cmd.exe must find the .bat in its folder
        environment["MSYS_NO_PATHCONV"] = "1"
        _run(["cmd.exe", "/c", str(unlock), "-java", APP_CLASS, str(built)], "unlocking the host component with "
             "protk_unlock; it needs the Creo Object TOOLKIT Java development license, or its extension license "
             "with a Creo TOOLKIT license, free on the license server", cwd=unlock.parent, env=environment)
        if not _unlocked(built):
            raise AdapterError("E_NATIVE_FAILURE", "protk_unlock ended without unlocking the host component.",
                               dispatch_state="not_started")
        jar.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built, jar)


def _unlocked(jar: Path) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(jar) as archive:
            return "META-INF/PTC.SF" in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _run(command: list[str], what: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    try:
        out = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=UNLOCK_TIMEOUT_S, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdapterError("E_NATIVE_FAILURE", f"Failed {what}: {exc}.", dispatch_state="not_started") from None
    if out.returncode != 0:
        raise AdapterError("E_NATIVE_FAILURE", f"Failed {what}.", dispatch_state="not_started",
                           native_message=(out.stdout + out.stderr).strip()[-2000:])
