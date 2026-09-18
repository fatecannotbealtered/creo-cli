"""Derive a machine-readable index of the published CREOSON interface.

The catalog in creo_cli/creoson_catalog.py is hand-authored: it narrows the upstream
surface deliberately (explicit ASCII basenames, no wildcards, no UI selection, safe
wire defaults). What it must NOT do is invent field names or miss a required one.
This script turns CREOSON's own shipped jsonSpecs into contract/creoson-interface.json
so tests/test_creoson_interface.py can check every operation against the published
contract instead of against someone's memory of it.

The specs ship inside the CreosonServer release zip under
  web/assets/creoson_stuff/jsonSpecs/
with CRLF endings, while the Git repository stores them with LF. Blob identities are
therefore computed over the LF-normalized bytes, which reproduces the hashes already
recorded in docs/UPSTREAM_SOURCES.md (verified against file-assemble.json).

  python scripts/gen_creoson_interface.py --from <unzipped-server-dir>
  python scripts/gen_creoson_interface.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "contract" / "creoson-interface.json"
SPEC_IDS = ROOT / "creo_cli" / "creoson_spec_ids.py"
RELEASE = "v3.0.2"
REPOSITORY = "SimplifiedLogic/creoson"
SPEC_SUBDIR = "web/assets/creoson_stuff/jsonSpecs"
# Data-type definitions consumed by other specs, not callable functions.
NOT_CALLABLE = "object"


def blob_sha(data: bytes) -> str:
    """Git blob identity over LF-normalized bytes; see the module docstring."""
    normalized = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(normalized) + normalized).hexdigest()


def field(item: dict) -> dict:
    out = {"name": item["name"], "type": item["type"]}
    if item.get("required"):
        out["required"] = True
    for key in ("default", "valid_values", "wildcards_allowed"):
        if key in item:
            out[key] = item[key]
    return out


def derive(specs: Path) -> dict:
    functions: dict[str, dict] = {}
    types: dict[str, dict] = {}
    for path in sorted(specs.glob("*.json")):
        if path.name == "creosonFunctions.json":
            continue
        data = path.read_bytes()
        document = json.loads(data.decode("utf-8"))
        spec = document.get("spec")
        if spec:
            functions[f"{spec['command']}.{spec['function']}"] = {
                "command": spec["command"],
                "function": spec["function"],
                "description": spec.get("function_description", ""),
                "request": [field(i) for i in spec.get("request") or []],
                "response": [field(i) for i in spec.get("response") or []],
                "spec_file": path.name,
                "git_blob_sha": blob_sha(data),
            }
        elif document.get("object_name"):
            # Nested return types (DimDetailData, FeatureData, ...) referenced by the
            # response entries above as object:<name> / object_array:<name>.
            types[document["object_name"]] = {
                "description": document.get("description", ""),
                "notes": document.get("notes") or [],
                "data": [field(i) for i in document.get("data") or []],
                "spec_file": path.name,
                "git_blob_sha": blob_sha(data),
            }
    return {
        "$comment": "DERIVED, DO NOT HAND-EDIT. Regenerate with scripts/gen_creoson_interface.py "
                    "--from <unzipped CreosonServer release>. This is an interface index used to "
                    "check creo_cli/creoson_catalog.py against the published contract; it is not "
                    "CREOSON source and does not bundle CREOSON.",
        "release": RELEASE,
        "repository": REPOSITORY,
        "spec_subdirectory": SPEC_SUBDIR,
        "blob_identity": "git blob sha1 over LF-normalized spec bytes",
        "function_count": len(functions),
        "data_type_count": len(types),
        "functions": dict(sorted(functions.items())),
        "data_types": dict(sorted(types.items())),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="source", help="unzipped CreosonServer directory, or the jsonSpecs directory itself")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        if not INDEX.is_file():
            print(json.dumps({"ok": False, "error": "contract/creoson-interface.json is missing"}))
            return 1
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        print(json.dumps({"ok": True, "release": index["release"], "functions": index["function_count"],
                          "data_types": index["data_type_count"]}))
        return 0
    if not a.source:
        print(json.dumps({"ok": False, "error": "--from is required when not checking"}))
        return 1
    source = Path(a.source).expanduser().resolve()
    specs = source if source.name == "jsonSpecs" else source.joinpath(*SPEC_SUBDIR.split("/"))
    if not specs.is_dir():
        print(json.dumps({"ok": False, "error": f"no jsonSpecs directory under {source}"}))
        return 1
    index = derive(specs)
    if not index["functions"]:
        print(json.dumps({"ok": False, "error": "no specs found"}))
        return 1
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with io.open(INDEX, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    write_spec_ids(index)
    print(json.dumps({"ok": True, "written": [str(INDEX.relative_to(ROOT)), str(SPEC_IDS.relative_to(ROOT))],
                      "functions": index["function_count"], "data_types": index["data_type_count"]}))
    return 0


def write_spec_ids(index: dict) -> None:
    """Emit the per-function blob identities the runtime cites in `reference`.

    A generated module rather than a data file: the catalog needs these at import
    time, and it keeps provenance exact per function instead of pinning a whole
    command group to one arbitrary file's hash.
    """
    lines = ['"""Blob identity of each published CREOSON specification. GENERATED, DO NOT EDIT.',
             "",
             f"Source: {REPOSITORY}@{RELEASE}, {SPEC_SUBDIR}/<command>-<function>.json",
             "Regenerate with scripts/gen_creoson_interface.py --from <unzipped release>.",
             '"""',
             "from __future__ import annotations",
             "",
             f'RELEASE = "{RELEASE}"',
             f'REPOSITORY = "{REPOSITORY}"',
             f'SPEC_SUBDIR = "{SPEC_SUBDIR}"',
             "",
             "SPEC_BLOB_SHA = {"]
    lines += [f'    "{key}": "{entry["git_blob_sha"]}",' for key, entry in index["functions"].items()]
    lines += ["}", "",
              "# Published response field types, so a result schema can fall back to the upstream's",
              "# own answer instead of a hand-written table guessing at it. Deliberate overrides",
              "# (ids as strings, enriched or composed keys) still live in creoson_schemas.",
              "RESPONSE_TYPES = {"]
    for key, entry in index["functions"].items():
        fields = {f["name"]: f["type"] for f in entry["response"]}
        if fields:
            lines.append(f'    "{key}": {fields!r},')
    lines += ["}", ""]
    with io.open(SPEC_IDS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
