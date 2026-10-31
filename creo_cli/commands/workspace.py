"""workspace list: the model files on disk, with their versions. Needs no Creo."""

from __future__ import annotations

from .. import paths
from ..core import page
from ..registry import LIMIT, OFFSET, Command, Param
from ..schemas import INT, NI, NS, S, array, listing, shape


def list_files(opts: dict) -> dict:
    rows = paths.list_models(opts.get("kind"), opts.get("name"))
    return page(rows, opts["limit"], opts["offset"]) | {
        "workspace": str(paths.workspace()),
        "_untrusted": ["items", "workspace"],
    }


ROW = shape(
    {
        "model": S,
        "kind": S,
        "directory": S,
        "versions": array(INT),
        "newest": S,
        "size_bytes": NI,
        "modified_at": NS,
    },
    ("model", "kind", "directory", "versions", "newest"),
)
COMMANDS = [
    Command(
        "workspace list",
        "Model files under the workspace, one row per model with its versions; needs no Creo",
        list_files,
        listing(ROW, workspace=S),
        (
            Param(
                "kind",
                choices=("part", "assembly", "drawing"),
                description="only this kind of model",
            ),
            Param("name", description="only models whose name contains this"),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items", "workspace"),
        sort="directory, then model name",
    ),
]
