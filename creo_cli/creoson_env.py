"""Environment probe for the CREOSON route, mirroring native.probe() for the VB API one.

`doctor` previously only reported on the VB API adapter, so the questions that
actually decide whether the primary route works -- is the API toolkit installed, is
the service up, is there a usable workspace -- had to be answered by hand. Each check
here exists because answering it by hand cost real time.

One deliberate implementation note. Creo installations delivered through an
application-streaming layer expose a partial filesystem view to processes outside the
container: `os.stat` on a path under the load point raises FileNotFoundError while
`os.scandir` of its parent lists it correctly. Every lookup below therefore walks
directory entries instead of stat-ing a composed path, so a present toolkit is never
reported as missing on those hosts.
"""
from __future__ import annotations

import os
from pathlib import Path

# Installed automatically with Creo Object TOOLKIT Java since Creo 4.0; J-Link has not
# been a separate installer selection since then, which is why "install J-Link" is not
# actionable advice and the fix text names the component that actually ships it.
JLINK_JAR = "pfcasync.jar"
JLINK_SUBDIR = ("text", "java")
TOOLKIT_COMPONENT = "Creo Object TOOLKIT Java"
STREAMING_MARKERS = (r"C:\Program Files\Numecent\Application Jukebox Player",
                     r"C:\Program Files (x86)\Numecent\Application Jukebox Player")
PTC_ROOTS = (r"C:\Program Files\PTC", r"C:\PTC", r"D:\PTC")


def entries(directory: Path) -> dict[str, os.DirEntry]:
    """Directory entries by casefolded name, or empty when unreadable.

    Uses scandir rather than stat for the reason in the module docstring.
    """
    try:
        with os.scandir(directory) as scan:
            return {e.name.casefold(): e for e in scan}
    except OSError:
        return {}


def common_files() -> Path | None:
    """Locate Creo's Common Files directory without trusting a composed path."""
    configured = os.environ.get("PRO_COMM_MSG_EXE")
    if configured:
        # <load point>/Common Files/<platform>/obj/pro_comm_msg.exe
        candidate = Path(configured).parent.parent.parent
        if entries(candidate):
            return candidate
    for root in PTC_ROOTS:
        for name, entry in sorted(entries(Path(root)).items()):
            if not name.startswith("creo"):
                continue
            found = entries(Path(entry.path)).get("common files")
            if found:
                return Path(found.path)
    return None


def toolkit() -> dict:
    """Report whether the API toolkit that ships J-Link is present."""
    root = common_files()
    if root is None:
        return {"creo_load_point": None, "api_toolkit_present": False,
                "detail": "no Creo installation found under the standard load points"}
    java_dir = root
    for part in JLINK_SUBDIR:
        found = entries(java_dir).get(part)
        if not found:
            return {"creo_load_point": str(root), "api_toolkit_present": False,
                    "detail": f"{'/'.join(JLINK_SUBDIR)} is absent from the installation"}
        java_dir = Path(found.path)
    present = JLINK_JAR.casefold() in entries(java_dir)
    return {"creo_load_point": str(root), "api_toolkit_present": present,
            "detail": f"{JLINK_JAR} {'found' if present else 'missing'} in {java_dir}"}


def streamed_delivery() -> bool:
    """True when Creo appears to be delivered by an application-streaming player.

    Those builds are packaged by the vendor and have no installer to re-run, so the
    API toolkit cannot be added to them at all. Saying so is more useful than
    repeating "install the toolkit" at someone who has no way to do it.
    """
    # Look the marker up in its parent's entries rather than testing its contents: an
    # installed-but-empty player directory still means a streamed delivery.
    return any(Path(marker).name.casefold() in entries(Path(marker).parent) for marker in STREAMING_MARKERS)


def workspace() -> dict:
    raw = os.environ.get("CREO_CLI_WORKSPACE")
    if not raw:
        return {"configured": False, "usable": False, "detail": "CREO_CLI_WORKSPACE is not set"}
    from . import creoson_state as store
    from .core import Error
    try:
        resolved = store.workspace()
    except Error as exc:
        return {"configured": True, "usable": False, "detail": exc.message}
    return {"configured": True, "usable": True, "detail": str(resolved)}


def probe() -> dict:
    kit = toolkit()
    return {"creo_load_point": kit["creo_load_point"], "api_toolkit_present": kit["api_toolkit_present"],
            "api_toolkit_detail": kit["detail"], "streamed_delivery": streamed_delivery(),
            "workspace": workspace()}
