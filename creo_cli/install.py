"""What `doctor` asks of the machine: is Creo installed with the API toolkit, and which Java.

Creo installations delivered through an application-streaming layer expose a partial
filesystem view to processes outside the container: `os.stat` on a path under the load
point raises FileNotFoundError while `os.scandir` of its parent lists it. Every lookup
here walks directory entries instead of stat-ing a composed path, so a present toolkit is
never reported missing on those hosts.
"""

from __future__ import annotations

import os
from pathlib import Path

# The service runs on otk.jar, which the installer component "Creo Object TOOLKIT Java"
# ships. There has been no separate "J-Link" selection since Creo 4.0, which is why fix
# text names the component that actually ships it.
OTK_JAR = "otk.jar"
JAR_SUBDIR = ("text", "java")
TOOLKIT_COMPONENT = "Creo Object TOOLKIT Java"
STREAMING_MARKERS = (
    r"C:\Program Files\Numecent\Application Jukebox Player",
    r"C:\Program Files (x86)\Numecent\Application Jukebox Player",
)
PTC_ROOTS = (r"C:\Program Files\PTC", r"C:\PTC", r"D:\PTC")
COMMON_FILES = "common files"
# Installers nest the load point under a container directory -- D:\PTC\Creo13.4\Creo
# 13.4.1.0\Common Files -- so the search goes a few levels down, and no further.
SEARCH_DEPTH = 4


def entries(directory: Path) -> dict[str, os.DirEntry]:
    try:
        with os.scandir(directory) as scan:
            return {e.name.casefold(): e for e in scan}
    except OSError:
        return {}


def common_files_candidates() -> list[Path]:
    """Every plausible Creo 'Common Files' directory, best guess first."""
    found: list[Path] = []
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


def jar(root: Path) -> Path | None:
    directory = root
    for part in JAR_SUBDIR:
        found = entries(directory).get(part)
        if not found:
            return None
        directory = Path(found.path)
    found = entries(directory).get(OTK_JAR)
    return Path(found.path) if found else None


def toolkit() -> dict:
    """Is the API toolkit the service runs on installed? Every candidate load point counts."""
    candidates = common_files_candidates()
    if not candidates:
        return {
            "creo_load_point": None,
            "present": False,
            "detail": "no Creo installation found under the standard load points",
        }
    for root in candidates:
        found = jar(root)
        if found is not None:
            return {
                "creo_load_point": str(root),
                "present": True,
                "detail": f"{OTK_JAR} found at {found}",
            }
    return {
        "creo_load_point": str(candidates[0]),
        "present": False,
        "detail": f"{OTK_JAR} is absent under {candidates[0] / Path(*JAR_SUBDIR)}; "
        f"{len(candidates)} load point(s) checked",
    }


def streamed_delivery() -> bool:
    """True when Creo is delivered by an application-streaming player, which has no
    installer to re-run -- so the toolkit cannot be added to it at all."""
    return any(Path(m).name.casefold() in entries(Path(m).parent) for m in STREAMING_MARKERS)


def java_runtime() -> dict:
    """Which JVM Creo will start the service in.

    Creo 13.4 requires Java 25 and fails the application during load, before any of its
    code runs, when it cannot find one -- so there is no application log to read.
    PRO_JAVA_COMMAND takes precedence over the config option jlink_java_command.
    """
    configured = os.environ.get("PRO_JAVA_COMMAND")
    if configured:
        exists = Path(configured).name.casefold() in entries(Path(configured).parent)
        return {
            "source": "PRO_JAVA_COMMAND",
            "command": configured,
            "resolved": exists,
            "detail": configured
            if exists
            else f"PRO_JAVA_COMMAND points at a missing file: {configured}",
        }
    return {
        "source": None,
        "command": None,
        "resolved": False,
        "detail": "PRO_JAVA_COMMAND is not set; Creo falls back to its own detection",
    }
