"""Local CLI leases use process birth identity; a reused PID is a different owner."""

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def births():
    if os.name == "nt":
        from .runtime_identity import processes

        return {row["pid"]: row.get("creation_filetime") for row in processes()}
    if sys.platform.startswith("linux"):
        result = {}
        for row in Path("/proc").iterdir():
            if row.name.isdigit():
                try:
                    stat = (row / "stat").read_text()
                    result[int(row.name)] = stat[stat.rindex(")") + 2 :].split()[19]
                except (OSError, ValueError, IndexError):
                    pass
        return result
    return None


def lease(seconds=60):
    observed = births()
    return {
        "pid": os.getpid(),
        "birth": (observed or {}).get(os.getpid()),
        "expires_at": (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def abandoned(owner):
    if not isinstance(owner, dict) or not owner.get("birth"):
        return False
    observed = births()
    if observed is None:
        return False
    birth = observed.get(owner["pid"])
    # A present process whose birth is unreadable is ambiguous, not dead.
    gone = owner["pid"] not in observed or birth is not None and birth != owner["birth"]
    return gone and datetime.fromisoformat(
        owner["expires_at"].replace("Z", "+00:00")
    ) <= datetime.now(UTC)
