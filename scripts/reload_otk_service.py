"""Rebuild the Creo-side service and put the change in front of a running Creo.

Creo loads an Object TOOLKIT Java application once per session, into a JVM it starts
itself and keeps until it exits. A class it has already loaded stays loaded, and it
holds the jar open, so there is no way to see an edit without restarting Creo. That
makes the edit-test loop four steps that must happen in order and in one environment,
which is exactly the kind of thing that should not be typed by hand.

  python scripts/reload_otk_service.py --restart

Without --restart the script builds, signs and registers, and tells you Creo has to be
restarted to pick it up. With it, Creo is closed and reopened, and the script waits for
the service to answer before reporting.

Restarting Creo discards anything unsaved in it. That is why it is a flag.
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

from creo_cli import creoson_env  # noqa: E402
from scripts import build_otk_service  # noqa: E402

CREO_PROCESSES = ("parametric.exe", "xtop.exe", "nmsd.exe")
# Creo reads protk.dat from the directory it starts in; this is where its own shortcut
# points on a default installation.
DEFAULT_STARTUP_DIR = Path(r"C:\Users\Public\Documents")
DEFAULT_ENDPOINT = "http://127.0.0.1:9057"


def load_point(explicit: str | None) -> Path:
    """The directory holding 'Common Files'. Probed unless given."""
    if explicit:
        return Path(explicit).expanduser()
    found = creoson_env.toolkit()
    if not found.get("creo_load_point"):
        raise RuntimeError("no Creo installation found; pass --creo with the directory "
                           "that holds 'Common Files' (see docs/CREO_SETUP.md)")
    return Path(found["creo_load_point"]).parent


def running() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    listed = result.stdout.lower()
    return [name for name in CREO_PROCESSES if name.lower() in listed]


def stop_creo(timeout: float = 45.0) -> dict:
    """Ask Creo to close, then insist. Returns what it took."""
    if not running():
        return {"was_running": False}
    for name in ("parametric.exe", "xtop.exe"):
        subprocess.run(["taskkill", "/IM", name], capture_output=True, text=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not running():
            return {"was_running": True, "forced": False}
        time.sleep(1.0)
    for name in CREO_PROCESSES:
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True, text=True)
    time.sleep(2.0)
    return {"was_running": True, "forced": True, "still_up": running()}


def unlock(creo: Path, jar: Path) -> str:
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
        ["cmd.exe", "/c", str(script), "-java", build_otk_service.APP_CLASS, str(jar)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(script.parent), env=environment, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "protk_unlock failed").strip()[:2000])
    return (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else "signed"


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
    subprocess.Popen([str(executable)], cwd=str(startup_dir), env=environment,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"executable": str(executable), "startup_dir": str(startup_dir),
            "pro_java_command": environment.get("PRO_JAVA_COMMAND")}


def ask(endpoint: str, path: str, timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(endpoint + path, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for_service(endpoint: str, timeout: float) -> dict:
    """Creo takes a while to come up; the service answers only once it has."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = ask(endpoint, "/health", 2.0)
        if health:
            return {"health": health, "session": ask(endpoint, "/session", 30.0),
                    "waited_seconds": round(timeout - (deadline - time.monotonic()), 1)}
        time.sleep(2.0)
    return {"error": f"the service did not answer on {endpoint} within {timeout:.0f}s",
            "log": str(Path.home() / ".creo-cli" / "otk-service.log")}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creo", help="Creo load point; probed when omitted")
    p.add_argument("--java-home", help="JDK to compile with; defaults to javac on PATH")
    p.add_argument("--java-command", default=os.environ.get("PRO_JAVA_COMMAND"),
                   help="java.exe Creo should start the application with")
    p.add_argument("--startup-dir", default=str(DEFAULT_STARTUP_DIR),
                   help="the directory Creo starts in, where protk.dat is read from")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument("--restart", action="store_true",
                   help="close and reopen Creo so the rebuilt service is loaded; "
                        "anything unsaved in Creo is lost")
    p.add_argument("--wait", type=float, default=180.0, help="seconds to wait for Creo to come up")
    a = p.parse_args()

    steps: dict = {}
    try:
        creo = load_point(a.creo)
        steps["creo"] = str(creo)
        if a.restart:
            steps["stopped"] = stop_creo()
        built = build_otk_service.build(creo, Path(a.java_home).expanduser() if a.java_home else None)
        steps["built"] = built
        jar = Path(built["jar"])
        steps["signed"] = unlock(creo, jar)
        steps["registered"] = str(build_otk_service.write_registry(Path(a.startup_dir).expanduser(), jar))
        if a.restart:
            steps["started"] = start_creo(creo, Path(a.startup_dir).expanduser(), a.java_command)
            steps["service"] = wait_for_service(a.endpoint, a.wait)
        else:
            steps["note"] = ("Creo loads the application once per session; restart it, or rerun "
                             "with --restart, before this build is what is running")
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure), "steps": steps}, indent=2))
        return 1
    ok = not a.restart or bool(steps.get("service", {}).get("health"))
    print(json.dumps({"ok": ok, "steps": steps}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
