"""Generate/check syntax from actual argparse actions; this is not behavior FCC."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creo_cli import discovery, registry  # noqa: E402
from creo_cli.main import parser  # noqa: E402


def action_row(action, inherited):
    value = action.default
    if value == argparse.SUPPRESS:
        value = inherited.get(action.dest)
    return {
        "flags": action.option_strings,
        "destination": action.dest,
        "takes_value": action.nargs != 0,
        "required": action.required,
        "default": value,
        "choices": list(action.choices) if action.choices is not None else None,
        "value_type": action.type.__name__
        if action.type
        else "boolean"
        if action.nargs == 0
        else "string",
        "repeat": "reject",
        "help": action.help,
    }


def inventory():
    tree = parser()
    inherited = {a.dest: a.default for a in tree._actions if a.option_strings}
    nodes = []

    def visit(node, words):
        command = node.get_default("_command")
        # argparse inherits defaults from the root but the root-only --version is
        # not accepted after a subcommand; keep accepted flags separate from defaults.
        actions = [action_row(a, inherited) for a in node._actions if a.option_strings]
        nodes.append({"path": " ".join(words), "terminal": command is not None, "options": actions})
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                for word, child in sorted(action.choices.items()):
                    visit(child, [*words, word])

    visit(tree, [])
    leaves = [n for n in nodes if n["terminal"]]
    assert {n["path"] for n in leaves} == set(registry.BY_PATH)
    return {
        "kind": "complete_registered_syntax_inventory",
        "generation": (
            "registry declarations plus the actual argparse tree/actions; handlers not invoked"
        ),
        "counts": discovery.counts()
        | {
            "tree_nodes": len(nodes),
            "leaf_parameter_declarations": sum(len(c.params) for c in registry.COMMANDS),
        },
        "limits": [
            (
                "All declared syntax is enumerated; accepted/rejected behavior needs "
                "separate CLI tests"
            ),
            "No live CAD coverage or whole-tree FCC conclusion follows from generation/checking",
        ],
        "global_options": registry.GLOBALS,
        "nodes": nodes,
        "commands": [
            {
                "path": c.path,
                "parameters": c.describe()["params"],
                "effects": c.describe()["driver"]["effects"],
                "target_type": c.describe()["type"],
                "registered_write_gate": c.write,
                "runtime": c.describe()["extensions"]["creo"]["runtime_lifecycle"],
            }
            for c in registry.COMMANDS
        ],
    }


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--check", action="store_true")
    opts = args.parse_args()
    value = inventory()
    path = ROOT / "docs/development/command-inventory.json"
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    same = path.is_file() and path.read_bytes().replace(b"\r\n", b"\n") == raw
    if not opts.check:
        path.write_bytes(raw)
    print(
        json.dumps(
            {
                "ok": same if opts.check else True,
                "counts": value["counts"],
                "behavior_FCC": "partial",
            }
        )
    )
    return int(opts.check and not same)


if __name__ == "__main__":
    raise SystemExit(main())
