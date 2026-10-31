"""Canonical public paths. Wire operation names and historical receipts stay intact.

This candidate changes the early tree deliberately: removed spellings are documented
migrations, not a second public tree of aliases.
"""

from __future__ import annotations

from dataclasses import replace

TREE_VERSION = 2
MOVED = {
    "feature thread": "feature cosmetic-thread",
    "feature mirror": "feature mirror-part",
    "geometry measure": "geometry distance",
    "dimension tolerance": "dimension set-tolerance",
    "family show": "family-table show",
    "family set": "family-table apply",
    "family remove": "family-table remove-instance",
    "assembly add": "assembly component add",
    "assembly remove": "assembly component remove",
    "assembly replace": "assembly component replace",
    "assembly explode": "assembly explode apply",
    "drawing add-view": "drawing view add",
    "drawing move-view": "drawing view move",
    "drawing annotate": "drawing dimension annotate",
    "drawing hide-dimension": "drawing dimension hide",
    "drawing add-dimension": "drawing dimension add",
    "drawing move-dimension": "drawing dimension move",
    "drawing add-note": "drawing note add",
    "drawing edit-note": "drawing note edit",
    "drawing add-table": "drawing table add",
    "drawing move-table": "drawing table move",
    "drawing add-title-block": "drawing title-block apply",
    "drawing add-symbol": "drawing symbol add",
    "drawing add-bom": "drawing bom add",
    "drawing add-balloons": "drawing bom balloons",
    "drawing add-datum": "drawing datum add",
    "drawing add-gtol": "drawing gtol add",
    "drawing remove": "drawing item remove",
}
RETIRED = {
    "assembly check": ["assembly placement check", "assembly interference check"],
    "model render": ["artifact render"],
    "model export": ["artifact export"],
    "operation acknowledge": ["operation query", "operation resolve"],
}


def migrate(commands):
    descriptions = {
        "feature thread": (
            "Create a cosmetic thread annotation; it does not cut helical thread geometry"
        ),
        "feature mirror": (
            "Mirror the whole part about a plane; selected-feature mirror is not implemented"
        ),
        "geometry measure": "Measure the native distance between two selected geometry references",
    }
    return [
        replace(
            command,
            path=MOVED.get(command.path, command.path),
            description=descriptions.get(command.path, command.description),
        )
        for command in commands
        if command.path not in RETIRED
    ]


def description():
    return {
        "version": TREE_VERSION,
        "breaking_candidate_change": True,
        "aliases": [],
        "migrations": {**{old: [new] for old, new in MOVED.items()}, **RETIRED},
        "receipt_history": (
            "Old command paths in stored receipts/evidence retain their original meaning"
        ),
        "confirmation": (
            "Pre-migration previews cannot confirm a new canonical command; preview again"
        ),
        "limits": [
            "CLI structure does not prove native task success",
            "drawing item remove retains explicit ownership-qualified selectors",
            "Full tool-driver runtime adoption is still incremental",
        ],
    }
