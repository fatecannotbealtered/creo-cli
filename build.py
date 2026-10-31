"""PyInstaller build: one self-contained creo-cli binary for the platform it runs on.

Run from the project root: python build.py
"""

import os
import platform
import subprocess
import sys
from pathlib import Path


def main() -> int:
    entry = Path("cli.py")
    if not entry.exists():
        print("cli.py not found; run from the project root")
        return 1
    name = "creo-cli"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        name,
        "--clean",
        "--noconfirm",
        # Command modules are imported by the registry at start; collect the whole
        # package so nothing imported lazily is left out.
        "--collect-submodules",
        "creo_cli",
        "--add-data",
        f"CHANGELOG.md{os.pathsep}.",
        "--add-data",
        f".agent/driver/schemas{os.pathsep}.agent/driver/schemas",
        str(entry),
    ]
    print("building " + name + ": " + " ".join(command))
    result = subprocess.run(command)
    if result.returncode != 0:
        return result.returncode
    binary = Path("dist") / (name + (".exe" if platform.system() == "Windows" else ""))
    if not binary.exists():
        print(f"expected {binary}, found nothing")
        return 1
    print(f"built {binary} ({binary.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
