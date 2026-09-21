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


COMMON_FILES = "common files"
# Installers nest the load point under a container directory -- D:\PTC\Creo13.4\Creo
# 13.4.1.0\Common Files -- and some layouts repeat the version folder again inside
# it, so searching only the first level finds nothing and stopping at the first hit
# can land on the wrong copy. Bounded, because an unbounded walk of a 12 GB tree is
# not something `doctor` should do.
SEARCH_DEPTH = 4


def common_files_candidates() -> list[Path]:
    """Every plausible Creo Common Files directory, best guess first."""
    found: list[Path] = []
    configured = os.environ.get("PRO_COMM_MSG_EXE")
    if configured:
        # <load point>/Common Files/<platform>/obj/pro_comm_msg.exe
        candidate = Path(configured).parent.parent.parent
        if entries(candidate):
            found.append(candidate)
    for root in PTC_ROOTS:
        queue = [(Path(root), 0)]
        while queue:
            directory, depth = queue.pop(0)
            for name, entry in sorted(entries(directory).items()):
                path = Path(entry.path)
                if name == COMMON_FILES:
                    found.append(path)
                elif depth < SEARCH_DEPTH and name.startswith(("creo", "ptc", "m0", "f0")):
                    queue.append((path, depth + 1))
    return found


def common_files() -> Path | None:
    candidates = common_files_candidates()
    return candidates[0] if candidates else None


def jlink_jar(root: Path) -> Path | None:
    directory = root
    for part in JLINK_SUBDIR:
        found = entries(directory).get(part)
        if not found:
            return None
        directory = Path(found.path)
    found = entries(directory).get(JLINK_JAR.casefold())
    return Path(found.path) if found else None


def toolkit() -> dict:
    """Report whether the API toolkit that ships J-Link is present.

    Checks every candidate load point rather than the first: a layout that repeats
    the version directory inside itself yields two, and only one carries the jar.
    """
    candidates = common_files_candidates()
    if not candidates:
        return {"creo_load_point": None, "api_toolkit_present": False,
                "detail": "no Creo installation found under the standard load points"}
    for root in candidates:
        jar = jlink_jar(root)
        if jar is not None:
            return {"creo_load_point": str(root), "api_toolkit_present": True,
                    "detail": f"{JLINK_JAR} found at {jar}"}
    root = candidates[0]
    return {"creo_load_point": str(root), "api_toolkit_present": False,
            "detail": f"{JLINK_JAR} is absent under {root / Path(*JLINK_SUBDIR)}; "
                      f"{len(candidates)} load point(s) checked"}


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
