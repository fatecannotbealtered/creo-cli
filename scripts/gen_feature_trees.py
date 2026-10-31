"""Derive the feature element trees from the Creo TOOLKIT headers.

Every feature Creo can build is described to it as an element tree: a fixed shape
of typed elements, each with an integer id, some holding values drawn from a named
enumeration. Getting any of it wrong -- an id, a nesting level, an enum value -- is
not a compile error anywhere. It is a feature that fails to build on a live Creo,
usually with nothing more specific than "general error". This project has no
feedback loop tight enough to discover those one at a time.

PTC publishes the shapes, and not in prose: each feature header under
`protoolkit/includes` carries an ASCII diagram of its tree, a table of every
element's value type, and the enumerations the values come from, as compilable C.
Those headers are the same definitions Creo is built from, so they are the
authority here, the way CREOSON's own specification files were for that route.

  python scripts/gen_feature_trees.py --from "<Creo>/Common Files"
  python scripts/gen_feature_trees.py --check

Produces contract/feature-trees.json. It records facts about the interface -- names,
ids, nesting, value types, enumeration values -- and the digest of every header it
read. It copies none of PTC's prose, and ships no header.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import operator
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "contract" / "feature-trees.json"
INCLUDES = ("protoolkit", "includes")

# Headers whose #define lines are the vocabulary itself rather than incidental macros.
DEFINE_SOURCES = {
    "ProElemId.h": "PRO_E_",  # element ids
    "ProFeatType.h": "PRO_FEAT_",  # feature types, PRO_E_FEATURE_TYPE values
}

DEFINE = re.compile(r"^\s*#\s*define\s+([A-Z][A-Z0-9_]*)\s+(.+?)\s*$")
ENUM = re.compile(r"typedef\s+enum\s*(?:\w+\s*)?\{(?P<body>[^{}]*)\}\s*(?P<name>\w+)\s*;", re.S)
COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
# One row of the element-type table: name, free-text label, then the value type.
TYPE_ROW = re.compile(
    r"^\s*(PRO_E_[A-Z0-9_]+)\s+.*?\s((?:PRO_VALUE_TYPE_|PRO_VALUE_)[A-Z0-9_]+|Compound|Array|Multiple)\s*$"
)
# A node in a tree diagram: optional connector, then an element name.
NODE = re.compile(r"^(?P<lead>[\s|]*?)(?P<conn>\|--+)?\s*(?P<name>PRO_E_[A-Z0-9_]+)\b")
FILLER = re.compile(r"^[\s|]*$")

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
}


def evaluate(expression: str, known: dict[str, int]) -> int | None:
    """An enum or #define value, or None if it is not a plain integer expression.

    Covers what the headers actually use: literals in any base, negation, shifts,
    or-ed flags and references to names already defined. Anything else is left
    unresolved and reported rather than guessed at.
    """
    text = expression.strip()
    text = re.sub(r"(?<=[0-9A-Fa-f])[uUlL]+\b", "", text)  # 0x10UL -> 0x10
    if not text:
        return None
    try:
        tree = ast.parse(text, mode="eval").body
    except SyntaxError:
        return None

    def walk(node: ast.AST) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.Name) and node.id in known:
            return known[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            return ~walk(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        raise ValueError(ast.dump(node))

    try:
        return walk(tree)
    except (ValueError, TypeError):
        return None


def parse_enums(text: str, known: dict[str, int]) -> tuple[dict[str, dict[str, int]], list[str]]:
    """Every `typedef enum` in one header, values resolved in declaration order."""
    enums: dict[str, dict[str, int]] = {}
    unresolved: list[str] = []
    for match in ENUM.finditer(COMMENT.sub(" ", text)):
        members: dict[str, int] = {}
        following = 0
        for entry in match.group("body").split(","):
            entry = entry.strip()
            if not entry:
                continue
            name, _, value = entry.partition("=")
            name = name.strip()
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                continue
            resolved = evaluate(value, known) if value.strip() else following
            if resolved is None:
                unresolved.append(f"{match.group('name')}.{name} = {value.strip()}")
                continue
            members[name] = resolved
            known[name] = resolved
            following = resolved + 1
        if members:
            enums[match.group("name")] = members
    return enums, unresolved


def parse_defines(text: str, prefix: str, known: dict[str, int]) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in COMMENT.sub(" ", text).splitlines():
        match = DEFINE.match(line)
        if not match or not match.group(1).startswith(prefix):
            continue
        value = evaluate(match.group(2), known)
        if value is not None:
            found[match.group(1)] = value
            known[match.group(1)] = value
    return found


def parse_trees(text: str) -> list[dict]:
    """The element-tree diagrams in one header, as nested (name, depth, parent) nodes.

    Depth comes from the column of each `|--` connector, tracked with an indentation
    stack rather than a fixed column width: the diagrams are hand-drawn and their
    indent step is not uniform from one header to the next.
    """
    trees: list[dict] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = NODE.match(lines[i])
        # A root is an element name with no connector and nothing but space before it.
        if not match or match.group("conn") or match.group("lead").strip():
            i += 1
            continue
        nodes = [{"name": match.group("name"), "depth": 0}]
        stack: list[tuple[int, str]] = [(-1, match.group("name"))]
        j = i + 1
        while j < len(lines):
            line = lines[j]
            node = NODE.match(line)
            if node and node.group("conn"):
                column = len(node.group("lead"))
                while len(stack) > 1 and stack[-1][0] >= column:
                    stack.pop()
                nodes.append({"name": node.group("name"), "depth": len(stack)})
                stack.append((column, node.group("name")))
            elif not FILLER.match(line):
                break
            j += 1
        if len(nodes) > 1:
            trees.append({"root": nodes[0]["name"], "nodes": nodes})
        i = j
    return trees


def parse_types(text: str) -> dict[str, str]:
    types: dict[str, str] = {}
    for line in text.splitlines():
        match = TYPE_ROW.match(line)
        if match:
            types.setdefault(match.group(1), match.group(2))
    return types


def build(common: Path) -> dict:
    includes = common.joinpath(*INCLUDES)
    if not includes.is_dir():
        raise RuntimeError(
            f"{includes} not found; the Creo TOOLKIT headers are part of the "
            "'Creo Parametric Toolkit' installer component (see docs/CREO_SETUP.md)"
        )
    headers = sorted(p for p in includes.iterdir() if p.suffix == ".h")
    texts = {p.name: open(p, encoding="latin-1").read() for p in headers}
    known: dict[str, int] = {}

    # Enum members refer to constants defined in other headers (PRO_VALUE_UNUSED,
    # PRO_B_TRUE, ...). Every integer #define is learned as context; only the
    # vocabulary headers are exported.
    for text in texts.values():
        parse_defines(text, "", known)
    defines: dict[str, dict[str, int]] = {}
    for name, prefix in DEFINE_SOURCES.items():
        if name not in texts:
            raise RuntimeError(f"{name} missing from {includes}")
        defines[name] = parse_defines(texts[name], prefix, known)

    enums: dict[str, dict[str, int]] = {}
    enum_sources: dict[str, str] = {}
    unresolved: list[str] = []
    # Two passes: an enum may refer to a name declared in a header that sorts later.
    for _ in range(2):
        unresolved = []
        for name, text in texts.items():
            found, missing = parse_enums(text, known)
            for enum_name, members in found.items():
                enums[enum_name] = members
                enum_sources[enum_name] = name
            unresolved += [f"{name}: {m}" for m in missing]

    element_ids = defines["ProElemId.h"]
    trees: dict[str, dict] = {}
    used: dict[str, str] = {}
    for name, text in texts.items():
        found = parse_trees(text)
        if not found:
            continue
        types = parse_types(text)
        for tree in found:
            for node in tree["nodes"]:
                node["id"] = element_ids.get(node["name"])
                if node["name"] in types:
                    node["value_type"] = types[node["name"]]
        trees[Path(name).stem] = {"header": name, "diagrams": found}
        used[name] = hashlib.sha256(text.encode("latin-1")).hexdigest()
    for name in DEFINE_SOURCES:
        used[name] = hashlib.sha256(texts[name].encode("latin-1")).hexdigest()
    for source in enum_sources.values():
        used.setdefault(source, hashlib.sha256(texts[source].encode("latin-1")).hexdigest())

    return {
        "$comment": (
            "DERIVED, DO NOT HAND-EDIT. Regenerate with scripts/gen_feature_trees.py "
            "--from <Creo Common Files>. Facts about the element-tree interface read from "
            "the Creo TOOLKIT headers: names, ids, nesting, value types, enumeration "
            "values. It is not PTC source and copies none of PTC's text."
        ),
        "source": {
            "includes_relative_path": "/".join(INCLUDES),
            "header_count": len(headers),
            "headers_sha256": dict(sorted(used.items())),
        },
        "element_ids": {
            "source_header": "ProElemId.h",
            "count": len(element_ids),
            "values": dict(sorted(element_ids.items())),
        },
        "feature_types": {
            "source_header": "ProFeatType.h",
            "values": dict(sorted(defines["ProFeatType.h"].items())),
        },
        "enums": {
            name: {"header": enum_sources[name], "values": enums[name]} for name in sorted(enums)
        },
        "unresolved_enum_members": sorted(set(unresolved)),
        "trees": dict(sorted(trees.items())),
    }


def render(index: dict) -> str:
    return json.dumps(index, indent=1, sort_keys=False, ensure_ascii=True) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="common", help="Creo 'Common Files' directory")
    p.add_argument(
        "--check",
        action="store_true",
        help="verify the committed index parses and is internally consistent",
    )
    a = p.parse_args()
    if a.check:
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        ids = index["element_ids"]["values"]
        missing = sorted(
            {
                n["name"]
                for t in index["trees"].values()
                for d in t["diagrams"]
                for n in d["nodes"]
                if n["name"] not in ids
            }
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "trees": len(index["trees"]),
                    "element_ids": len(ids),
                    "enums": len(index["enums"]),
                    "nodes_without_id": missing[:20],
                    "nodes_without_id_count": len(missing),
                }
            )
        )
        return 0
    if not a.common:
        p.error("--from is required unless --check")
    try:
        index = build(Path(a.common).expanduser())
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}))
        return 1
    INDEX.write_text(render(index), encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "ok": True,
                "index": str(INDEX.relative_to(ROOT)),
                "trees": len(index["trees"]),
                "element_ids": index["element_ids"]["count"],
                "enums": len(index["enums"]),
                "unresolved_enum_members": len(index["unresolved_enum_members"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
