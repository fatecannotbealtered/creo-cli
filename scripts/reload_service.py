"""Rebuild, unlock and register development components without controlling existing Creo.

Creo loads an Object TOOLKIT Java application once per session, into a JVM it starts
itself and keeps until it exits. A class it has already loaded stays loaded, and it
holds the jar open, so there is no way to see an edit without restarting Creo. That
makes the edit-test loop four steps that must happen in order and in one environment,
which is exactly the kind of thing that should not be typed by hand.

Use build_acceptance_bundle.py for an immutable candidate, then the public owned startup
recipe for a new generation. The historical --restart flag now refuses before any CAD
observation or process action: a process name or service endpoint is not ownership.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from creo_cli import install  # noqa: E402
from scripts import build_service  # noqa: E402

CREO_PROCESSES = ("parametric.exe", "xtop.exe", "nmsd.exe")
# Console tools run without a window of their own: run from a host with no console, each
# would flash one up. Creo itself is started with its window, as a person starts it.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Creo reads protk.dat from the directory it starts in; this is where its own shortcut
# points on a default installation.
DEFAULT_STARTUP_DIR = Path(r"C:\Users\Public\Documents")
DEFAULT_ENDPOINT = "http://127.0.0.1:9057"
# Written by the service at start; see Service.issueToken.
TOKEN_FILE = Path.home() / ".creo-cli" / "service-token"


def load_point(explicit: str | None) -> Path:
    """The directory holding 'Common Files'. Probed unless given."""
    if explicit:
        return Path(explicit).expanduser()
    found = install.toolkit()
    if not found.get("creo_load_point"):
        raise RuntimeError(
            "no Creo installation found; pass --creo with the directory "
            "that holds 'Common Files' (see docs/CREO_SETUP.md)"
        )
    return Path(found["creo_load_point"]).parent


def running() -> list[str]:
    result = subprocess.run(
        ["tasklist"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )
    listed = result.stdout.lower()
    return [name for name in CREO_PROCESSES if name.lower() in listed]


def stop_creo(timeout: float = 45.0) -> dict:
    """Never infer ownership from an executable name or a responding endpoint."""
    raise RuntimeError(
        "global Creo restart is disabled: process names and service endpoints do not "
        "prove ownership; preserve existing sessions and start a new owned generation "
        "using examples/engineering/start-owned-creo.ps1"
    )


def unlock(creo: Path, jar: Path, app_class: str | None = None) -> str:
    """Sign the jar with the seat's own TOOLKIT licence.

    Creo refuses to load an unsigned Object TOOLKIT application. The signing tool ships
    in the installation and needs no request to PTC: it adds PTC.SF and PTC.DSA to the
    jar's manifest using the licence already on this machine.
    """
    script = creo / "Parametric" / "bin" / "protk_unlock.bat"
    if not script.is_file():
        raise RuntimeError(f"protk_unlock.bat not found at {script}")
    # cmd.exe will not run a .bat from the working directory when this is set, and Git
    # Bash rewrites anything that looks like a path unless told otherwise.
    environment = dict(os.environ)
    environment.pop("NoDefaultCurrentDirectoryInExePath", None)
    environment["MSYS_NO_PATHCONV"] = "1"
    result = subprocess.run(
        ["cmd.exe", "/c", str(script), "-java", app_class or build_service.APP_CLASS, str(jar)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(script.parent),
        env=environment,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "protk_unlock failed").strip()[:2000])
    return (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else "signed"


def native_sketch(creo: Path, skip: bool) -> dict:
    """Build and sign the C sketch library beside the jar, when a compiler exists.

    Optional: the service works without it and refuses multi-entity sketches with the
    reason. A missing toolchain is reported and skipped; a failed compile is not --
    that is broken code, and a reload that hides it would test the old library.
    """
    from scripts import build_native_sketch

    if skip:
        build_native_sketch.OUTPUT.unlink(missing_ok=True)
        return {"built": False, "reason": "--skip-native"}
    try:
        build_native_sketch.vcvars()
    except RuntimeError as unavailable:
        return {"built": False, "reason": str(unavailable)}
    return {"built": True, **build_native_sketch.ensure(creo)}


def start_creo(creo: Path, startup_dir: Path, java_command: str | None) -> dict:
    """Launch Creo with the environment the toolkit application needs.

    PRO_JAVA_COMMAND must be in the environment of the process that launches Creo, not
    merely set for the user: Creo inherits the launching block, so setting it after a
    shell is open does nothing for anything that shell starts.
    """
    executable = creo / "Parametric" / "bin" / "parametric.exe"
    if not executable.is_file():
        raise RuntimeError(f"parametric.exe not found at {executable}")
    environment = dict(os.environ)
    if java_command:
        environment["PRO_JAVA_COMMAND"] = java_command
    startup_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [str(executable)],
        cwd=str(startup_dir),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {
        "executable": str(executable),
        "startup_dir": str(startup_dir),
        "pro_java_command": environment.get("PRO_JAVA_COMMAND"),
    }


def token() -> str | None:
    """The secret the running service wrote for this Creo session, if there is one."""
    try:
        return TOKEN_FILE.read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def ask(endpoint: str, path: str, timeout: float) -> dict | None:
    request = urllib.request.Request(endpoint + path)
    secret = token()
    if secret:
        request.add_header("X-Creo-Cli-Token", secret)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        try:
            return json.loads(refused.read().decode("utf-8"))
        except (OSError, ValueError):
            return None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def open_work(endpoint: str) -> dict:
    """What a restart would throw away, as far as it can be known.

    A restart kills Creo, so it must not happen over someone's open models. The
    service can list them; when it cannot be asked -- Creo started some other way,
    or a broken build that never came up -- nothing is known, and that is treated
    as a reason to stop rather than as permission.
    """
    if not running():
        return {"creo_running": False, "safe": True}
    session = ask(endpoint, "/session", 15.0)
    if not session or not session.get("ok"):
        return {
            "creo_running": True,
            "safe": False,
            "reason": "Creo is running but the service did not answer, so its open models "
            "cannot be listed",
        }
    models = session.get("models_in_session")
    if models is None:
        return {
            "creo_running": True,
            "safe": False,
            "reason": "the running service predates model listing",
        }
    return {
        "creo_running": True,
        "safe": not models,
        "models_in_session": models,
        **({} if not models else {"reason": f"{len(models)} model(s) open in Creo"}),
    }


def wait_for_service(endpoint: str, timeout: float) -> dict:
    """Creo takes a while to come up; the service answers only once it has."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = ask(endpoint, "/health", 2.0)
        if health:
            return {
                "health": health,
                "session": ask(endpoint, "/session", 30.0),
                "waited_seconds": round(timeout - (deadline - time.monotonic()), 1),
            }
        time.sleep(2.0)
    return {
        "error": f"the service did not answer on {endpoint} within {timeout:.0f}s",
        "log": str(Path.home() / ".creo-cli" / "service.log"),
    }


def jdk_of(java_command: str | None) -> Path | None:
    """The JDK holding the java.exe Creo runs the service with, when it is a full JDK.

    otk.jar is compiled for the Java that Creo requires (25 for Creo 13.4); an older javac
    first on PATH cannot even read its class files. The runtime Creo is pointed at is the
    one version known to be right.
    """
    if not java_command:
        return None
    home = Path(java_command).expanduser().parent.parent
    return (
        home if (home / "bin" / ("javac.exe" if os.name == "nt" else "javac")).is_file() else None
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creo", help="Creo load point; probed when omitted")
    p.add_argument(
        "--java-home",
        help="JDK to compile with; defaults to the JDK --java-command belongs to, "
        "else javac on PATH",
    )
    p.add_argument(
        "--java-command",
        default=os.environ.get("PRO_JAVA_COMMAND"),
        help="java.exe Creo should start the application with",
    )
    p.add_argument(
        "--startup-dir",
        default=str(DEFAULT_STARTUP_DIR),
        help="the directory Creo starts in, where protk.dat is read from",
    )
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument(
        "--restart",
        action="store_true",
        help="retained for compatibility; refuses global restart before any CAD/process action",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="retained for compatibility; does not authorize touching unowned instances",
    )
    p.add_argument("--wait", type=float, default=180.0, help="seconds to wait for Creo to come up")
    p.add_argument(
        "--skip-native",
        action="store_true",
        help="do not build the C sketch library; multi-entity sketches will be refused",
    )
    a = p.parse_args()

    steps: dict = {}
    try:
        if a.restart:
            # Fail before a toolkit observation, build, registration or process action.
            # --force never authorizes touching an unowned session.
            stop_creo()
        creo = load_point(a.creo)
        steps["creo"] = str(creo)
        java_home = Path(a.java_home).expanduser() if a.java_home else jdk_of(a.java_command)
        steps["java_home"] = str(java_home) if java_home else "javac on PATH"
        # Before Creo is stopped: a compile error must not cost the running session.
        build_service.check_compiles(creo, java_home)
        if a.restart:
            work = open_work(a.endpoint)
            steps["open_work"] = work
            if not work["safe"] and not a.force:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": f"not restarting Creo: {work['reason']}; "
                            "save and close them, or pass --force to discard them",
                            "steps": steps,
                        },
                        indent=2,
                    )
                )
                return 1
            steps["stopped"] = stop_creo()
        built = build_service.build(creo, java_home)
        steps["built"] = built
        jar = Path(built["jar"])
        steps["signed"] = unlock(creo, jar)
        steps["native_sketch"] = native_sketch(creo, a.skip_native)
        native_dll = (
            Path(steps["native_sketch"]["dll"]) if steps["native_sketch"].get("built") else None
        )
        steps["registered"] = str(
            build_service.write_registry(
                Path(a.startup_dir).expanduser(), jar, native_dll=native_dll
            )
        )
        if a.restart:
            steps["started"] = start_creo(creo, Path(a.startup_dir).expanduser(), a.java_command)
            steps["service"] = wait_for_service(a.endpoint, a.wait)
        else:
            steps["note"] = (
                "Existing Creo sessions retain their loaded component bytes. Preserve them; "
                "package an immutable candidate and start a new explicitly owned generation "
                "with examples/engineering/start-owned-creo.ps1, then verify actual loading"
            )
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure), "steps": steps}, indent=2))
        return 1
    ok = not a.restart or bool(steps.get("service", {}).get("health"))
    print(json.dumps({"ok": ok, "steps": steps}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
