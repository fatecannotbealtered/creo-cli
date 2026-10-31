"""Build development-only task mappings; never invoke handlers, the service or Creo."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creo_cli import registry  # noqa: E402

SPEC_COMMIT = "9607a35fe0ea33fe822e1f2ad2704eae260d4018"
SOURCE_BASE = "0e3302cb104084626d5475af1f3989da7cee1357"
DOCS = ROOT / "docs/development"
MANAGEMENT = {
    "reference",
    "context",
    "doctor",
    "changelog",
    "update",
    "service",
    "operation",
    "workflow",
}
LABELS = {
    "c-session": "Running session state and working directory",
    "c-workspace": "Native-file workspace inventory",
    "c-model": "Model lifecycle, identity, modification and description",
    "c-part": "Template-based parts with explicit units",
    "c-prism": "Bounded parametric extrusions and revolutions",
    "c-datum": "Datum planes and axes",
    "c-local-feature": (
        "Rounds, chamfers, holes, threads, shell, draft, rib, sweep, patterns and mirrors"
    ),
    "c-feature-tree": "Feature identities, dependencies and edits",
    "c-geometry": "Geometry selectors, measurements and mass-property observations",
    "c-dimension": "Dimensional values, identities and modification",
    "c-tolerance": "Dimension tolerances and model tolerance standards",
    "c-parameter": "Typed parameter values",
    "c-relation": "Relations and dependent regeneration",
    "c-family": "Family-table columns and instances",
    "c-material": "Material inventory and assignment",
    "c-assembly": "Components, references, placement and replacement",
    "c-assembly-check": "Scoped assembly interference checks",
    "c-explode": "Assembly exploded presentation",
    "c-drawing-view": "Drawing creation and associative views",
    "c-drawing-annotation": "Drawing dimensions, notes and removal",
    "c-drawing-table": "Tables, title blocks, BOM and balloons",
    "c-drawing-gdt": "Drawing symbols, datums and geometric tolerances",
    "c-import": "Bounded native model interchange import",
    "c-persist": "Native model version persistence",
    "c-render": "Rendered image artifacts",
    "c-export": "Model and drawing interchange artifacts",
    "g-native-check": "Completed native feature-status scan embedded in dimension/relation writes",
    "g-sheetmetal": "Sheetmetal body workflows beyond the exposed solid-feature subset",
    "g-blend": "Blend variants beyond existing extrude/revolve/sweep requests",
    "g-drawing-sheets": (
        "Explicit multi-sheet creation and lifecycle beyond per-view sheet selection"
    ),
    "g-2d-import": "Drawing DXF/DWG/IGES and AutobuildZ input workflows",
    "g-native-modelcheck": "Full native ModelCHECK and manufacturing-rule checks",
    "g-angle": "Comprehensive projection-standard acceptance beyond the drawing candidate",
    "g-3d-pdf": "3D PDF delivery and independent consumer acceptance",
    "x-manufacturing": "CAM, molds, additive and manufacturing modules outside this scope",
    "x-generative": "Generative design and optimization outside this scope",
}
GOALS = {
    "t-env": "Inspect application/session/model/workspace identity and prepare a bounded target",
    "t-min": (
        "On scratch geometry change actual width40 to48mm, retain20/10mm, independently "
        "check9600mm3 and optionally reopen a saved version"
    ),
    "t-part": (
        "Build and edit a requirement-driven part with explicit geometry, datums and dependencies"
    ),
    "t-parametric": (
        "Edit typed parameters, relations, tolerances, family entries and materials with "
        "independent dependent-state readback"
    ),
    "t-assembly": (
        "Build a constrained scratch assembly and inspect components, interference and exploded "
        "state"
    ),
    "t-drawing": (
        "Create associative views, annotations, tables and BOM with actual "
        "sheet/layout/projection criteria"
    ),
    "t-delivery": (
        "Persist native versions and independently consume interchange and image artifacts"
    ),
    "t-recover": (
        "Inspect target state after unknown/incomplete operations without duplicate dispatch; "
        "tool-management query/resolve stays outside application denominator"
    ),
}
MIN_PATHS = {
    "session status",
    "model list",
    "part create",
    "feature extrude",
    "feature list",
    "model show",
    "dimension list",
    "dimension set",
    "geometry list",
    "geometry distance",
    "model save",
    "model close",
    "model open",
}
PRIMARY = {
    "c-session": "t-env",
    "c-workspace": "t-env",
    "c-model": "t-delivery",
    "c-part": "t-part",
    "c-prism": "t-part",
    "c-datum": "t-part",
    "c-local-feature": "t-part",
    "c-feature-tree": "t-part",
    "c-geometry": "t-part",
    "c-dimension": "t-parametric",
    "c-tolerance": "t-parametric",
    "c-parameter": "t-parametric",
    "c-relation": "t-parametric",
    "c-family": "t-parametric",
    "c-material": "t-parametric",
    "c-assembly": "t-assembly",
    "c-assembly-check": "t-assembly",
    "c-explode": "t-assembly",
    "c-drawing-view": "t-drawing",
    "c-drawing-annotation": "t-drawing",
    "c-drawing-table": "t-drawing",
    "c-drawing-gdt": "t-drawing",
    "c-import": "t-delivery",
    "c-persist": "t-delivery",
    "c-render": "t-delivery",
    "c-export": "t-delivery",
}


def slug(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def raw(path):
    return path.read_bytes()


def sha(path):
    return hashlib.sha256(raw(path)).hexdigest()


def product_bytes(path):
    """Repository text is committed with LF (.gitattributes); binary bytes stay exact."""
    payload = raw(path)
    return payload if b"\0" in payload else payload.replace(b"\r\n", b"\n")


def domain_cap(path):
    noun, *actions = path.split()
    verb = " ".join(actions)
    if noun == "artifact":
        return "c-render" if verb == "render" else "c-export"
    if noun == "family-table":
        return "c-family"
    if noun == "model":
        return {
            "save": "c-persist",
            "render": "c-render",
            "export": "c-export",
            "import": "c-import",
            "set-tolerance-standard": "c-tolerance",
        }.get(verb, "c-model")
    if noun == "feature":
        if verb in {"extrude", "revolve"}:
            return "c-prism"
        if verb in {"datum-plane", "datum-axis"}:
            return "c-datum"
        if verb in {"list", "show", "delete", "suppress", "resume", "rename"}:
            return "c-feature-tree"
        return "c-local-feature"
    if noun == "dimension":
        return "c-tolerance" if verb == "set-tolerance" else "c-dimension"
    if noun == "assembly":
        if verb.startswith("interference "):
            return "c-assembly-check"
        return "c-explode" if verb.startswith("explode ") else "c-assembly"
    if noun == "drawing":
        if verb == "create" or verb == "show" or verb.startswith(("view ", "sheet ", "layout ")):
            return "c-drawing-view"
        if verb.startswith(("table ", "title-block ", "bom ")):
            return "c-drawing-table"
        if verb.startswith(("symbol ", "datum ", "gtol ")):
            return "c-drawing-gdt"
        return "c-drawing-annotation"
    return "c-" + noun


def snapshot():
    """Declaration metadata only: inspect names/files, never call command handlers."""
    dispatch = {}
    for line in (
        (ROOT / "service/src/com/fateforge/creocli/service/Ops.java")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        match = re.search(r'case "([^"]+)": return (\w+)\.(\w+)\(', line)
        if match:
            dispatch[match[1]] = {
                "file": "service/src/com/fateforge/creocli/service/" + match[2] + ".java",
                "entrypoint": match[2] + "." + match[3],
            }
    rows = []
    for command in registry.COMMANDS:
        python_file = Path(inspect.getsourcefile(command.handler)).relative_to(ROOT).as_posix()
        rows.append(
            {
                "path": command.path,
                "params": command.describe()["params"],
                "current_type": "write" if command.write else "read",
                "dangerous": command.dangerous,
                "description": command.description,
                "request_required": (command.request or {}).get("required", []),
                "python": {
                    "file": python_file,
                    "entrypoint": command.handler.__module__ + "." + command.handler.__qualname__,
                },
                "service_ops": [{"operation": op, **dispatch[op]} for op in command.service_ops],
            }
        )
    return rows


def reader(path, cap):
    if path == "dimension set":
        return (
            "fresh dimension.list(check_regeneration=true), feature.list and model.show",
            (
                "Same model/stable dimension ID reads requested value with actual unit, "
                "relative1e-9/absolute1e-9 tolerance; completed native scan covers prior "
                "feature IDs; no failure IDs; actual feature/unit invariants. Scratch min "
                "additionally needs48/20/10mm, volume9600mm3 and bbox in the real sketch basis; "
                "geometry observations alone do not pass those invariants."
            ),
        )
    if cap == "g-native-check" or path == "relation set":
        return (
            "native feature-status scan plus fresh relation.list/dimension.list/model.show",
            (
                "Record actual relations and dependent values; completed native checker with "
                "API/checker/application version, input model and coverage; getter failure "
                "stays incomplete and inaccessible state stays unknown."
            ),
        )
    if cap == "c-persist":
        return (
            "actual scratch native version bytes plus close/open and independent model.show",
            (
                "Only an explicitly requested scratch save passes persistence after reopening "
                "the new version and matching actual units, dimensions, geometry and "
                "dependencies; writing an export is separate."
            ),
        )
    if cap in {"c-export", "c-render", "c-import"}:
        return (
            "fresh model/session readers and an independent artifact consumer",
            (
                "Bind actual source, artifact bytes/hash, consumer "
                "version/completion/input/coverage and task geometry/pages/fields; input echo, "
                "file headers and screenshots do not establish consumer acceptance."
            ),
        )
    if cap.startswith("c-drawing"):
        return (
            "fresh model.show and independent native drawing/view/annotation/table getters",
            (
                "Actual drawing/model IDs, sheet, projection, requested/preferred scale, "
                "positions and independent text/view bounds satisfy task layout; annotations "
                "bind real source dimensions/styles. Missing bounds remain incomplete; "
                "screenshots supplement the actual getters."
            ),
        )
    if cap.startswith("c-assembly") or cap == "c-explode":
        return (
            "fresh assembly/model component, placement, constraint and native interference getters",
            (
                "Actual component paths/references/transforms and placement agree with the "
                "task; native check records covered/excluded pairs, units and completion; an "
                "empty reply without coverage is not zero interference."
            ),
        )
    if cap in {"c-session", "c-workspace", "c-model", "c-part"}:
        return (
            (
                "fresh session.status/model.list/model.show or independently read native-file "
                "inventory"
            ),
            (
                "Requested object identity, origin/version, units, modified/activity state and "
                "authorized paths are observed; create/open/close/discard outcomes are checked "
                "using a separate session/model reader without assuming source or persistence "
                "from the request."
            ),
        )
    if cap in {"c-dimension", "c-tolerance", "c-parameter", "c-relation", "c-family", "c-material"}:
        return (
            "fresh dimension/parameter/relation/family/material getters and dependent model.show",
            (
                "Actual typed values/expressions/instances/material/tolerance and units match "
                "the task; preserve expected/observed/source/unit/tolerance and dependent "
                "geometry. Never accept a setter reply as its own reader."
            ),
        )
    return (
        "fresh feature.list/feature.show/geometry.list/geometry.measure and model.show",
        (
            "Actual stable IDs, types, names, references, dependencies and feature status plus "
            "independent geometry meet the bounded task; selector ambiguity is refused, native "
            "checker completion is separate from feature-tree status, and default "
            "anchors/invariants must be stated."
        ),
    )


def build(spec_root):
    rows = snapshot()
    evidence = []
    implementations = {}
    files = {r["python"]["file"] for r in rows}
    files |= {op["file"] for r in rows for op in r["service_ops"]}
    files |= {
        "creo_cli/registry.py",
        "creo_cli/engine.py",
        "creo_cli/transport.py",
        "creo_cli/building.py",
        "creo_cli/schemas.py",
        "service/src/com/fateforge/creocli/service/Service.java",
        "service/src/com/fateforge/creocli/service/FeatureStatusScan.java",
        "service/src/com/fateforge/creocli/service/Dimensions.java",
        "service/src/com/fateforge/creocli/service/Failures.java",
    }
    for file in sorted(files):
        identity = "imp-" + slug(file)
        implementations[file] = identity
        evidence.append(
            {
                "id": identity,
                "kind": "implementation",
                "path": file,
                "sha256": hashlib.sha256(product_bytes(ROOT / file)).hexdigest(),
                "source": "isolated source candidate on base " + SOURCE_BASE,
                "summary": (
                    "Git LF source bytes and declared entrypoints; not loaded identity, "
                    "licensing or native execution proof."
                ),
            }
        )
    for file in sorted((DOCS / "survey").glob("*.json")):
        data = json.loads(file.read_text(encoding="utf-8"))
        evidence.append(
            {
                "id": data["id"],
                "kind": data.get("kind", "document"),
                "path": file.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(product_bytes(file)).hexdigest(),
                "source": data["source"],
                "summary": data["summary"],
            }
        )
    evidence.append(
        {
            "id": "ev-command-snapshot",
            "kind": "document",
            "path": "docs/development/command-snapshot.json",
            "sha256": hashlib.sha256(
                encode({"kind": "declaration_metadata_no_handler_execution", "commands": rows})
            ).hexdigest(),
            "source": "current Python command declarations and actual Java Ops dispatch source",
            "summary": (
                f"All{len(rows)} exposed commands and their current parameters/adapter entries; "
                "this is "
                "an explicit bounded command inventory, not application exhaustiveness."
            ),
        }
    )
    mapped = []
    tasks = {
        key: {
            "id": key,
            "goal": goal,
            "status": "blocked" if key in {"t-min", "t-recover"} else "planned",
            "reason": (
                "No current candidate native end-to-end run. License, loaded component/instance "
                "identity and safe scratch scope need coordination; fixtures are separate. "
                "Scope gaps and complete driver-runtime migration remain explicit."
            ),
            "capability_ids": [],
            "command_paths": [],
            "critical_parameters": [],
            "adapter_entries": [],
            "readback": [],
            "test_ids": [],
        }
        for key, goal in GOALS.items()
    }
    tests = []
    commands = []
    for row in rows:
        path = row["path"]
        management = path.split()[0] in MANAGEMENT
        cap = None if management else domain_cap(path)
        caps = [] if management else [cap]
        if path in {"dimension set", "relation set"}:
            caps.append("g-native-check")
        tids = [] if management else [PRIMARY[cap]]
        if path in MIN_PATHS:
            tids.append("t-min")
        if path in {"session status", "model list", "model show"}:
            tids += ["t-env", "t-recover"]
        if path == "model show":
            tids += ["t-part", "t-assembly", "t-drawing", "t-parametric"]
        if path in {"geometry list", "geometry measure"}:
            tids.append("t-assembly")
        tids = sorted(set(tids))
        mapped.append(
            {
                "path": path,
                "role": "tool_management" if management else "domain",
                "capability_ids": caps,
                "task_ids": tids,
                "rationale": "Tool configuration/discovery/install/operation/workflow management: "
                + row["description"]
                if management
                else (
                    "Bounded resource action in the actual task tree; parameter and "
                    "independent-reader mapping is per command, with no fixed-depth or CRUD "
                    "requirement."
                ),
            }
        )
        commands.append(
            {
                "path": path,
                "params": row["params"],
                "driver": {
                    "capability_id": cap or "tool-management",
                    "maturity": "alpha",
                    "environments": [],
                },
            }
        )
        for tid in tids:
            task = tasks[tid]
            task["command_paths"].append(path)
            task["capability_ids"] = sorted(set(task["capability_ids"]) | set(caps))
            for parameter in row["params"]:
                reason = (
                    "Required target/input selector. "
                    if parameter["required"]
                    else "Optional task control to select explicitly when relevant. "
                ) + parameter.get("description", "")
                if parameter["name"] == "request":
                    reason += " Native request required fields: " + ", ".join(
                        row["request_required"]
                    )
                task["critical_parameters"].append(
                    {"command_path": path, "name": parameter["name"], "reason": reason}
                )
            entries = [row["python"], *row["service_ops"]]
            for entry in entries:
                item = {
                    "command_path": path,
                    "artifact_ref": implementations[entry["file"]],
                    "entrypoint": entry["entrypoint"],
                }
                if item not in task["adapter_entries"]:
                    task["adapter_entries"].append(item)
            check_id = tid + "-" + slug(path) + "-actual"
            method, criterion = reader(path, cap)
            task["readback"].append(
                {
                    "id": check_id,
                    "method": method,
                    "criterion": criterion,
                    "independence": (
                        "Fresh separate getter/consumer after execution. Only actual "
                        "observations qualify; command arguments, setter echoes, fixture "
                        "arithmetic and screenshots cannot substitute."
                    ),
                }
            )
            test_id = "native-" + tid + "-" + slug(path)
            task["test_ids"].append(test_id)
            tests.append(
                {
                    "id": test_id,
                    "task_id": tid,
                    "command_path": path,
                    "status": "not_run",
                    "evidence_ref": None,
                    "check_ids": [check_id],
                    "reason": (
                        "Future source-bound native/consumer task check. Existing offline and "
                        "historical records are not a current candidate real_run."
                    ),
                }
            )
    known = {
        "c-part": "doc-ptc-product",
        "c-prism": "doc-ptc-product",
        "c-dimension": "doc-ptc-product",
        "c-assembly": "doc-ptc-product",
        "c-geometry": "doc-ptc-mass",
        "c-material": "doc-ptc-mass",
        "g-native-check": "doc-ptc-solid",
        "c-drawing-view": "doc-ptc-drawing",
        "c-drawing-annotation": "doc-ptc-drawing",
        "g-sheetmetal": "doc-ptc-sheetmetal",
        "g-blend": "doc-ptc-sheetmetal",
        "g-drawing-sheets": "doc-ptc-drawing",
        "g-2d-import": "doc-ptc-drawing",
        "x-manufacturing": "doc-ptc-product",
        "x-generative": "doc-ptc-product",
    }
    caps = []
    for identity, label in LABELS.items():
        paths = [m["path"] for m in mapped if identity in m["capability_ids"]]
        refs = [known[identity]] if identity in known else ["doc-installed-sdk"]
        for row in rows:
            if row["path"] in paths:
                refs += [
                    implementations[row["python"]["file"]],
                    *[implementations[op["file"]] for op in row["service_ops"]],
                ]
        excluded = identity.startswith("x-")
        caps.append(
            {
                "id": identity,
                "description": label,
                "interfaces": sorted(
                    {
                        op["entrypoint"]
                        for row in rows
                        if row["path"] in paths
                        for op in row["service_ops"]
                    }
                ),
                "application_support": "supported" if identity in known else "unknown",
                "automation": "reachable" if paths else "unknown",
                "adapter": "implemented" if paths else "unimplemented",
                "cli_exposure": "exposed" if paths else "not_exposed",
                "testing": "not_run",
                "disposition": "exposed" if paths else "excluded" if excluded else "deferred",
                "reason": (
                    "Documented family-level support where cited; exact local license/variants "
                    "and loaded candidate are unverified. SDK/compiled source supports "
                    "interface-level reachability only, not a native task pass."
                )
                if paths
                else (
                    "Surveyed gap outside current exposed adapters. GUI/product support does "
                    "not establish automation; license/variants remain unknown. "
                )
                + (
                    "Explicitly excluded from core CAD task scope."
                    if excluded
                    else (
                        "Deferred pending interface/task investigation; no refusal-only "
                        "placeholder is counted as implemented."
                    )
                ),
                "evidence_refs": sorted(set(refs)),
            }
        )
    inventory = list(LABELS)
    design = {
        "design_version": "2.0",
        "application": {
            "name": "Creo Parametric",
            "version": "Creo13 build2026163 (prior readonly observation; current binding unknown)",
            "license": (
                "unknown current runtime/development/extension and per-feature entitlement; "
                "documentation alone cannot prove an available seat"
            ),
            "environment": {"platform": "windows", "arch": "x64", "mode": "session"},
            "evidence_refs": ["doc-prior-observation", "doc-installed-sdk", "doc-ptc-license"],
        },
        "scope": {
            "description": (
                "Provisional36-group core parametric CAD survey plus explicit gaps/exclusions; "
                "requirements to part/assembly/drawing/native persistence/interchange, "
                f"with{len(rows)} "
                "actual current command declarations"
            ),
            "inventory_ids": inventory,
            "inventory_evidence_refs": [
                "doc-ptc-product",
                "doc-ptc-drawing",
                "doc-ptc-sheetmetal",
                "doc-installed-sdk",
                "ev-command-snapshot",
            ],
            "excluded_scopes": [
                "CAM/manufacturing modules",
                "Generative optimization",
                "Unsurveyed Creo modules and local license entitlements",
            ],
            "limitations": [
                "This grouped provisional inventory is not the entire application.",
                (
                    "All current candidate native tests are not_run, all tasks planned/blocked, "
                    "verified capability count zero."
                ),
                (
                    "Source/SDK/fixture evidence is distinct from current loaded native "
                    "implementation and consumer acceptance."
                ),
                (
                    "Existing runtime reference/driver/scope/receipt/recovery migration remains "
                    "partial; this wrapper is development-only."
                ),
                (
                    "Official product overview is family-level; specific installed13 "
                    "variants/licensing are not inferred."
                ),
            ],
        },
        "coverage": {
            "denominator_ids": inventory,
            "fcc_scope": "declared_commands",
            "rationale": (
                "Inventory/capability/denominator IDs enumerate the same36 scoped groups."
                f"{len(rows)} "
                "command mappings include tool-management roles separately; full public-command "
                "FCC does not prove complete Creo coverage."
            ),
        },
        "capabilities": caps,
        "evidence": evidence,
        "tasks": list(tasks.values()),
        "commands": mapped,
        "tests": tests,
        "tree_decisions": [
            {
                "decision": (
                    "Use variable-depth resource paths for actual drawing/assembly objects and "
                    "explicit artifact/workflow/operation tasks, preserving native wire names."
                ),
                "alternatives": [
                    "Force a generic CRUD tree",
                    "Immediately replace everything with a single apply command",
                ],
                "reason": (
                    "Actual resources, selectors and readers justify current leaves; task "
                    "evidence can later justify high-level commands without fixed depth."
                ),
            },
            {
                "decision": (
                    "Treat service/operation/workflow/discovery as tool management and keep "
                    "heavy geometry/drawing resources bounded."
                ),
                "alternatives": [
                    "Count management as application coverage",
                    "Inline every heavy resource in model/session state",
                ],
                "reason": (
                    "Distinct application denominator and on-demand readers prevent artificial "
                    "coverage inflation and oversized state snapshots."
                ),
            },
            {
                "decision": (
                    "Retain zero current native verified claims and explicit deferred/excluded "
                    "gaps."
                ),
                "alternatives": [
                    "Promote fixture success to native supported",
                    "Drop hard gaps from the denominator",
                ],
                "reason": (
                    "Required evidence/loaded identity/readback/consumer bindings are absent; "
                    "future real runs must pass before promotion."
                ),
            },
        ],
    }
    spec_files = [
        "scripts/check_product_design.py",
        "scripts/check_spec.py",
        "scripts/contract_io.py",
        "packages/tool_driver_sdk/verification.py",
    ] + [
        p.relative_to(spec_root).as_posix() for p in sorted((spec_root / "schemas").glob("*.json"))
    ]
    lock = {
        "kind": "readonly_local_spec_design_validator_lock_not_release_adoption",
        "spec_version": "1.0.2",
        "source_commit": SPEC_COMMIT,
        "files": {p: sha(spec_root / p) for p in spec_files},
    }
    product = {
        "kind": "development_only_registry_design_not_runtime_contract",
        "name": "creo-cli",
        "source_base_commit": SOURCE_BASE,
        "spec_commit": SPEC_COMMIT,
        "commands": commands,
        "design": design,
    }
    lines = [
        "# Current development command/task map",
        "",
        (
            "Generated from actual declarations; no handler or Creo call. All current native "
            "tests are not_run."
        ),
        "",
        (
            "| Command | Role / capability | Tasks | Required parameters | Python adapter | "
            "Native entry |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for row, mapping in zip(rows, mapped, strict=True):
        lines.append(
            "| "
            + " | ".join(
                [
                    row["path"],
                    mapping["role"] + ": " + ", ".join(mapping["capability_ids"]),
                    ", ".join(mapping["task_ids"]),
                    ", ".join(p["name"] for p in row["params"] if p["required"]) or "none",
                    row["python"]["entrypoint"],
                    ", ".join(p["entrypoint"] for p in row["service_ops"])
                    or "local/tool management",
                ]
            )
            + " |"
        )
    return {
        ROOT / "registry.design.json": encode(product),
        DOCS / "command-snapshot.json": encode(
            {"kind": "declaration_metadata_no_handler_execution", "commands": rows}
        ),
        DOCS / "spec-source-lock.json": encode(lock),
        DOCS / "COMMAND-MAP.md": ("\n".join(lines) + "\n").encode("utf-8"),
    }


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-root", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build(args.spec_root)
    drift = [
        str(p.relative_to(ROOT)) for p, data in outputs.items() if not p.is_file() or raw(p) != data
    ]
    if args.check:
        print(
            json.dumps({"ok": not drift, "scope": "development_design_generation", "drift": drift})
        )
        return 1 if drift else 0
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(
        json.dumps(
            {
                "ok": True,
                "commands": len(registry.COMMANDS),
                "capabilities": len(LABELS),
                "native_verified": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
