"""Build the host component on the user's computer, during `plugin install`.

creo-cli ships the host component as source (plugin/source) and no binary. An Object TOOLKIT Java
application must be unlocked with the PTC tool `protk_unlock` before Creo loads it from a seat
without a development license, and an unlocked file must not change afterwards. So the JAR is
compiled with the user's JDK 25 against the user's own `otk.jar`, and unlocked there with the
user's license: the Creo Object TOOLKIT Java development license, or its extension license with
a Creo TOOLKIT license (PTC, "Unlocking, Running and Signing the Creo Object TOOLKIT Java
Application"). Nothing signed with somebody else's license is distributed.

The host component's C library (plugin/source/native) is built the same way: compiled with the
user's Visual Studio C compiler against the Creo TOOLKIT headers and libraries of the user's
Creo, and unlocked with the user's Creo TOOLKIT development license. A computer without them
still gets the Java host; the commands that need the C library then say what is missing.
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
COMPILE_TIMEOUT_S = 300
NATIVE_DLL = "creo-cli-native.dll"
# cmd.exe and the tools it runs read and write the console code page.
CONSOLE = "oem" if os.name == "nt" else "utf-8"


def _said(raw: bytes) -> str:
    """A tool's output as text: UTF-8, else the console code page."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(CONSOLE, errors="replace")


SOURCE_SUFFIXES = (".java", ".c", ".h")
CRLF = chr(13) + chr(10)  # cmd.exe reads a batch file by CRLF lines


def source_digest(sources: Path) -> str:
    """One SHA-256 over every source file, Java and C, by its path below plugin/source and its bytes."""
    digest = hashlib.sha256()
    for path in sorted(p for p in sources.rglob("*") if p.suffix in SOURCE_SUFFIXES):
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
        _run([str(jdk / "bin" / "javac.exe"), "-J-Duser.language=en", "--release", "25", "-encoding", "UTF-8", "-cp", str(otk),
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
        out = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, capture_output=True,
                             timeout=UNLOCK_TIMEOUT_S, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdapterError("E_NATIVE_FAILURE", f"Failed {what}: {exc}.", dispatch_state="not_started") from None
    if out.returncode != 0:
        raise AdapterError("E_NATIVE_FAILURE", f"Failed {what}.", dispatch_state="not_started",
                           native_message=_said(out.stdout + out.stderr).strip()[-2000:])


def find_vcvars() -> Path | None:
    """vcvars64.bat of a Visual Studio with the x64 C compiler: CREO_CLI_VCVARS, else the newest
    installation vswhere reports."""
    named = os.environ.get("CREO_CLI_VCVARS")
    if named:
        return Path(named) if Path(named).is_file() else None
    program_files = os.environ.get("ProgramFiles(x86)") or "C:/Program Files (x86)"
    vswhere = Path(program_files) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        out = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                              "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.stdout.splitlines():
        candidate = Path(line.strip()) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if line.strip() and candidate.is_file():
            return candidate
    return None


def build_native(sources: Path, common_files: Path, dll: Path) -> str | None:
    """Compile the C library in ``sources``, unlock it and put it at ``dll``. Returns None when it
    is built, or why it is not: a computer without a C compiler, Creo TOOLKIT or its license
    still gets the Java host. Nothing is written at ``dll`` unless the build succeeds."""
    files = sorted(str(p.resolve()) for p in sources.glob("*.c"))
    if not files:
        return "the host component has no C sources"
    vcvars = find_vcvars()
    if vcvars is None:
        return ("no Visual Studio with the x64 C compiler was found; install Visual Studio 2022 or its Build Tools "
                "with \"Desktop development with C++\", or set CREO_CLI_VCVARS to its vcvars64.bat")
    toolkit = common_files / "protoolkit"
    libs = toolkit / "x86e_win64" / "obj"
    unlock = common_files.parent / "Parametric" / "bin" / "protk_unlock.bat"
    needed = [toolkit / "includes" / "ProToolkit.h", libs / "protk_dll_NU.lib", libs / "ucore.lib", libs / "udata.lib", unlock]
    missing = [str(p) for p in needed if not p.is_file()]
    if missing:
        return "the Creo installation has no Creo TOOLKIT component (missing " + ", ".join(missing) + ")"
    with tempfile.TemporaryDirectory(prefix="creo-cli-native-") as work:
        built = Path(work) / NATIVE_DLL
        script = Path(work) / "build.bat"
        system = ("libcmt.lib kernel32.lib user32.lib wsock32.lib advapi32.lib mpr.lib winspool.lib netapi32.lib "
                  "psapi.lib gdi32.lib shell32.lib comdlg32.lib ole32.lib ws2_32.lib")
        objects = " ".join(f'"{Path(work) / (Path(f).stem + ".obj")}"' for f in files)
        script.write_text(CRLF.join([
            "@echo off",
            f'call "{vcvars}" >nul 2>nul || exit /b 10',
            f'cd /d "{work}"',
            "cl -nologo -c -GS -fp:precise -W3 -D_WSTDIO_DEFINED -DPRO_MACHINE=36 -DPRO_OS=4 "
            f'-I"{toolkit / "includes"}" ' + " ".join(f'"{f}"' for f in files) + " || exit /b 11",
            f'link -nologo /dll /machine:amd64 /debug:none -out:"{built}" {objects} '
            f'"{libs / "protk_dll_NU.lib"}" "{libs / "ucore.lib"}" "{libs / "udata.lib"}" {system} || exit /b 12',
            "",
        ]), encoding=CONSOLE, newline="")
        try:
            # VSLANG=1033: the compiler's messages in English, like the rest of creo-cli's output.
            out = subprocess.run(["cmd.exe", "/c", str(script)], env={**os.environ, "VSLANG": "1033"},
                                 capture_output=True, timeout=COMPILE_TIMEOUT_S, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"compiling the C library failed: {exc}"
        if out.returncode != 0 or not built.is_file():
            tail = _said(out.stdout + out.stderr).strip()[-600:]
            return f"compiling the C library failed: {tail}"
        environment = dict(os.environ)
        environment.pop("NoDefaultCurrentDirectoryInExePath", None)
        environment["MSYS_NO_PATHCONV"] = "1"
        try:
            out = subprocess.run(["cmd.exe", "/c", str(unlock), str(built)], cwd=str(unlock.parent), env=environment,
                                 capture_output=True, timeout=UNLOCK_TIMEOUT_S, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"unlocking the C library with protk_unlock failed: {exc}"
        said = _said(out.stdout + out.stderr).strip()
        if out.returncode != 0 or "successfully unlocked" not in said.lower():
            return ("protk_unlock did not unlock the C library; it needs a Creo TOOLKIT development license: "
                    + said[-300:])
        dll.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(built, dll)
    return None
