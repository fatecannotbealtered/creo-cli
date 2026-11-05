"""creo-cli: lets an AI Agent operate Creo Parametric safely from the command line.

The driver runtime in ``_driver/`` does everything every driver tool shares. This package adds
the domain commands (``commands/``) and the adapter that talks to Creo Parametric (``adapter/``).
"""
from __future__ import annotations

import sys
from pathlib import Path

from ._driver import Tool
from .adapter import Adapter
from .commands import COMMANDS
from .maturity import STANDARD

# package.json, CHANGELOG.md, knowledge/, skills/ and contract/ sit at the project root; in the
# native program they are bundled next to the code.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))

TOOL = Tool(
    root=ROOT,
    adapter=Adapter,
    commands=COMMANDS,
    application="Creo Parametric",
    versions=">=13.4 <13.5",
    modes=["session"],
    host_component=True,
    # Standard writes that take Creo Parametric more than a minute: opening a large assembly
    # retrieves every model it uses. The runtime runs them as long jobs (DCLI-065).
    long_commands=["doc open"],
    # plugin/manifest.json records the host component's files and methods; `python scripts/spec.py
    # generate` writes all of it but `methods` (DCLI-240).
    plugin_manifest=ROOT / "plugin" / "manifest.json",
    maturity=STANDARD,
)


def main() -> None:
    TOOL.main()
