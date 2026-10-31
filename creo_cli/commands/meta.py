"""reference, context, doctor, changelog: what the tool is, where it runs, what is in the way."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .. import (
    __version__,
    discovery,
    driver,
    execution_budgets,
    install,
    operations,
    paths,
    safety,
    service_bundle,
    transport,
)
from ..core import CODES, Error
from ..registry import Command, Param
from ..schemas import S, array, shape

RISK_TIER = "T1"
RISK = (
    "T1: confirmed writes change models in a live Creo session and write model and export "
    "files inside the disposable workspace, where a render also leaves its picture; nothing "
    "overwrites or deletes the user's files, changes persistent system or Creo settings, "
    "or starts or stops Creo; outside the workspace only creo-cli's own directory is written"
)
RELEASE = {
    "level": "beta",
    "fcc_required": True,
    "fcc_status": "missing",
    "fcc_coverage": "partial",
    "mock_upstream_required": True,
    "mock_upstream_status": "partial",
    "live_smoke_required_for_stable": True,
    "live_smoke_status": "missing",
    "reason": (
        "Command-tree v2 is an unreleased breaking beta candidate. Baseline mock tests do not "
        "establish full coverage of the added readers, workflow and resolution paths. Recorded "
        "baseline live evidence is not evidence for this candidate. Native capabilities, "
        "software coverage and each selected task require separate source-bound evidence."
    ),
    "required_evidence": [
        "functional_contract_coverage_100",
        "mock_upstream_contract_tests",
        "recorded_live_smoke_for_stable",
    ],
}
LIMITS = {
    "bounded_presentation": driver.PRESENTATION_LIMITS,
    "bounded_machining": driver.MACHINING_LIMITS,
    "bounded_construction": driver.CONSTRUCTION_LIMITS,
    "bounded_engineering_properties": driver.ENGINEERING_PROPERTY_LIMITS,
    "bounded_drawing_edits": driver.DRAWING_EDIT_LIMITS,
    "bounded_family_tables": driver.FAMILY_TABLE_LIMITS,
    "inventory_meaning": "Declared adapters and task categories are not native acceptance. "
    "Read each command's bounded limits and runtime lifecycle; legacy paths remain unqualified.",
    "creates": [
        "parts and assemblies from templates, with explicit units",
        "sketched extrusions that add or remove material; bounded full-turn first-solid revolves",
        "datum planes and axes",
        "rounds, chamfers, shells, drafts and ribs",
        "sweeps of a closed section along a smooth path of lines and arcs",
        "family tables: a part's instances by its dimensions, parameters and features",
        "bounded simple native through holes in axis-aligned plates; advanced hole forms "
        "are not part of the accepted contract",
        "cosmetic threads on shafts and in bores",
        "patterns along a direction or about an axis, and a part mirrored about a plane",
        "tolerances on dimensions -- plus and minus, symmetric, limits, ISO 286 fits, basic -- "
        "and a model's tolerance standard and ISO 2768 general class",
        "components placed by explicit constraints, or swapped for another member of their family",
        "exploded states, and exploded drawing views of them",
        "parts and assemblies imported from STEP, IGES or Parasolid",
        "drawings with general, projected, section and detail views, the model's dimensions "
        "chosen and placed, reference dimensions, datums and geometric tolerances, notes, tables, "
        "an assembly's parts list and balloons, and symbols",
        "JPEG pictures, and STEP, IGES, STL and PDF files",
    ],
    "profiles": ["circle", "ellipse", "rectangle", "polygon", "slot", "outline", "holes"],
    "not_yet": [
        "blends and swept blends",
        "sheet metal",
        "offset sections",
    ],
    "never": [
        "arbitrary scripts, mapkeys or trail files",
        "deleting files outside Creo's versioning",
        "starting or stopping Creo, or changing persistent configuration",
    ],
}
# Codes of the fleet contract that do not apply here; `reference` marks them so.
NOT_RAISED = {
    "E_RATE_LIMITED": "nothing creo-cli talks to limits its rate",
    "E_SERVER": "the service's own failures come as E_NATIVE_FAILURE, E_BACKEND_UNAVAILABLE or "
    "E_PROTOCOL",
}
EXIT_CODES = {
    "0": "success",
    "1": "failure, not retryable",
    "2": "usage or validation",
    "3": "not found",
    "4": "permission, configuration or backend unavailable",
    "5": "confirmation required",
    "6": "conflict: stale token, lock, unresolved earlier write, or outcome unknown",
    "7": "transient; retry with backoff",
    "8": "timeout",
    "9": "reserved: human action required",
    "130": "interrupted",
}


def _workflow_profile():
    from ..workflow_properties import NUMERIC, WRITES
    from ..workflow_tasks import SUPPORTED_WRITES
    from .workflow import MAX_STEPS

    return {
        "supported_leaf_writes": sorted(SUPPORTED_WRITES),
        "max_steps": MAX_STEPS,
        "objects": "existing open models; literal model and file targets; no creation-derived IDs",
        "failure_policy": "stop",
        "property_workflow": {
            "commands": sorted(WRITES),
            "tolerance_forms": sorted(NUMERIC),
            "compatible_writes": [
                "property commands",
                "model regenerate",
                "model save",
                "existing supported drawing edits",
                "artifact export",
            ],
            "standard_dependency": "a completed independently verified standard step preserves "
            "numeric overrides and detaches their tables before a later numeric edit",
            "file_binding": "actual material path, file identity and bytes require observe scope; "
            "rechecked before confirmation, between steps and at the final boundary",
            "state_binding": "advance only from each successful leaf verifier's retained "
            "engineering snapshot; external resampling never expands confirmed intent",
            "layout_feedback": "tolerance lettering can enlarge associated drawing labels; "
            "inspect bounds before placement/export and render all PDF pages",
            "not_supported": [
                "geometry/property write interleaving",
                "fit/basic/nominal workflow tolerance changes",
                "dynamic objects or output IDs",
                "automatic continuation, replay or rollback",
            ],
        },
        "outcomes": "parent and child facts remain separate; later edits are unsaved, "
        "partial saves stay partial, missing final evidence stays unknown",
        "operation_lookup": [
            "operation show --id <parent_operation_id>",
            "operation show --id <child_operation_id>",
            "workflow show --id <parent_operation_id>",
        ],
        "recovery": "register independent evidence with operation resolve; preview a new task "
        "containing only explicit remaining actions",
        "coverage": "bounded composition; implementation support is separate from recorded "
        "native acceptance and whole-tree FCC",
    }


def reference(opts: dict) -> dict:
    from .. import registry

    wanted = opts.get("command")
    if wanted and opts.get("index"):
        raise Error(
            "E_USAGE",
            "--index and --command are mutually exclusive",
            {"problem": "conflicting_flags"},
        )
    commands = [
        c
        for c in registry.COMMANDS
        if not wanted or c.path == wanted or c.path.startswith(wanted + " ")
    ]
    if not commands:
        raise Error(
            "E_NOT_FOUND",
            "no such command",
            {
                "command": wanted,
                "known": [c.path for c in registry.COMMANDS],
                "_untrusted": ["command"],
            },
        )
    names = {c.schema_name for c in commands} | (
        {"dry_run"} if any(c.write for c in commands) else set()
    )
    if any(c.path in driver.MIGRATED for c in commands):
        names.add("driver_plan")
    described = [c.describe() for c in commands]
    for row in described:
        row.setdefault("extensions", {}).setdefault("creo", {})["execution_budget"] = {
            "ordinary_max_seconds": 300,
            "extended_max_seconds": execution_budgets.EXTENDED_MAX_SECONDS
            if row["path"] in execution_budgets.COMMANDS
            else 300,
            "extended_profile": execution_budgets.PROFILE
            if row["path"] in execution_budgets.COMMANDS
            else None,
        }
        if row["path"] == "workflow run":
            row["extensions"]["creo"]["bounded_workflow"] = _workflow_profile()
    errors = {
        k: {"exit": v[0], "retryable": v[1]}
        | ({"description": NOT_RAISED[k]} if k in NOT_RAISED else {})
        | (
            {"description": registry.NATIVE_READ_RECOVERY["description"]}
            if k == registry.NATIVE_READ_RECOVERY["error_code"]
            else {"description": registry.NATIVE_DIAGNOSTIC_RECOVERY["description"]}
            if k == registry.NATIVE_DIAGNOSTIC_RECOVERY["error_code"]
            else {}
        )
        for k, v in CODES.items()
    }
    if opts.get("index"):
        return {
            "view": "index",
            "tool": "creo-cli",
            "version": __version__,
            "risk_tier": RISK_TIER,
            "driver_profile": driver.profile(),
            "commands": [
                {k: c[k] for k in ("path", "type", "dangerous", "description")}
                | {k: c["driver"][k] for k in ("effects", "maturity")}
                for c in described
            ],
        }
    if len(commands) == 1 and wanted == commands[0].path:
        return discovery.command_view(
            commands[0],
            described[0],
            registry.SCHEMAS[commands[0].schema_name],
            driver.profile(),
            errors,
        )
    return {
        "view": "full",
        "tool": "creo-cli",
        "version": __version__,
        "command_tree": __import__("creo_cli.command_tree", fromlist=["description"]).description(),
        "design_spec": {
            "version": "1.0.2",
            "commit": "9607a35fe0ea33fe822e1f2ad2704eae260d4018",
            "adoption": "product-design validation; runtime contract migration is incomplete",
        },
        "driver_profile": driver.profile(),
        "runtime_migration": driver.migration(),
        "risk_tier": RISK_TIER,
        "risk": RISK,
        "release_readiness": RELEASE,
        "capabilities": LIMITS,
        "extensions": {
            "creo": {
                "bounded_workflow": _workflow_profile(),
                "operation_recovery": operations.RECOVERY_CONTRACT,
                "native_read_recovery": registry.NATIVE_READ_RECOVERY,
                "native_diagnostic_recovery": registry.NATIVE_DIAGNOSTIC_RECOVERY,
                "drawing_execution_budget": execution_budgets.contract(),
                "inventory_counts": discovery.counts(),
                "non_raised_error_codes": NOT_RAISED,
                "discovery": {
                    "scalar_repetition": "rejected with E_USAGE before handler dispatch",
                    "prefix_filter": (
                        "compatibility: a noun prefix returns the filtered full reference; an"
                        " exact path returns the pinned single-command view"
                    ),
                    "scope_schemas": (
                        "public driver schemas are URN references resolved from the pinned "
                        "schemas directory shipped with the package"
                    ),
                },
            }
        },
        "service": {"protocol": transport.PROTOCOL, "endpoint_env": "CREO_CLI_SERVICE_URL"},
        "json_schemas": {execution_budgets.SCHEMA_ID: execution_budgets.SCHEMA},
        "commands": described,
        "schemas": {k: v for k, v in registry.SCHEMAS.items() if k in names},
        "error_codes": errors,
        "exit_codes": EXIT_CODES,
        "global_flags": [
            dict(
                g,
                default=g.get("default", False if g["type"] == "boolean" else None),
                multiple=False,
            )
            for g in registry.GLOBALS
        ]
        + [
            {
                "name": "help",
                "type": "boolean",
                "default": False,
                "multiple": False,
                "description": "-h/--help: human text, exits 0 before dispatch at any tree node",
            },
            {
                "name": "version",
                "type": "boolean",
                "default": False,
                "multiple": False,
                "description": "root only; cannot combine with a command",
            },
        ],
    }


def context(opts: dict) -> dict:
    _diagnostic_options(opts)
    try:
        root = str(paths.workspace())
        usable = True
    except Error:
        root, usable = None, False
    installation = None
    if opts.get("installation"):
        from .. import deployment

        installation = deployment.inspect(
            opts["installation"],
            creo=opts.get("creo"),
            java_home=opts.get("java_home"),
            timeout=min(opts.get("timeout", 30), 5),
        )
    state = discovery.state_observation()
    try:
        recovery = operations.recovery_diagnostics()
    except Error as exc:
        recovery = {
            "available": False,
            "code": exc.code,
            "reason": exc.message,
            "next_action": (
                "inspect retained records; do not assume an empty history or replay unknown work"
            ),
        }
    service = transport.configuration()
    return {
        "version": __version__,
        "config": {
            "workspace": root,
            "workspace_usable": usable,
            "permission": safety.permission(),
            "native_writes_opt_in": safety.native_opt_in(),
            "state_directory": str(safety.directory()),
        },
        "driver_profile": driver.profile(),
        "authorization": driver.scope().authorization,
        "runtime_migration": driver.migration(),
        "capabilities": LIMITS,
        "extensions": {
            "creo": {
                "bounded_workflow": _workflow_profile(),
                "operation_recovery": recovery,
                "inventory_counts": discovery.counts(),
                "installation": installation,
            }
        },
        "service": service,
        "credentials": {
            "configured": service["token_file_present"],
            "kind": "local_service_token",
            "validity": "not_checked",
        },
        "environment": discovery.environment(installation),
        "state": state,
        "_untrusted": ["config", "environment", "state", "extensions"],
    }


def _check(name: str, status: str, message: str, fix: str | None = None, **details) -> dict:
    if "authorization" in details:
        details["task_scope"] = details.pop("authorization")
    return {
        "check": name,
        "status": status,
        "message": message,
        "fix": None if status == "pass" else fix,
        **({"details": details} if details else {}),
    }


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in text.split("-")[0].split("+")[0].split("."))


def _skill_check() -> dict:
    """The installed copies of the Skill against this binary: a Skill newer than the binary
    tells an agent to call commands the binary does not have."""
    found = []
    for base in (Path.home() / ".agents" / "skills", Path.home() / ".claude" / "skills"):
        path = base / "creo-cli" / "SKILL.md"
        try:
            m = re.search(r'"min_version"\s*:\s*"(\d+\.\d+\.\d+)', path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if m:
            found.append((str(path), m[1]))
    newer = [(p, v) for p, v in found if _version(v) > _version(__version__)]
    if newer:
        path, needed = newer[0]
        return _check(
            "skill_version",
            "fail",
            f"the Skill installed at {path} needs creo-cli {needed}; this is {__version__}",
            f"obtain a matching private candidate package for creo-cli {needed}; "
            "verify its manifest before replacing this CLI",
        )
    if found:
        return _check(
            "skill_version",
            "pass",
            f"creo-cli {__version__} meets the min_version of the Skill installed at "
            + ", ".join(p for p, _ in found),
        )
    return _check(
        "skill_version",
        "pass",
        f"creo-cli {__version__}; no installed creo-cli Skill found under ~/.agents/skills or "
        "~/.claude/skills to compare with -- compare reference.version with the Skill's "
        "min_version",
    )


def doctor(opts: dict) -> dict:
    _diagnostic_options(opts)
    checks = [_skill_check()]
    deployment_state = None
    try:
        recovery = operations.recovery_diagnostics()
        checks.append(
            _check(
                "operation_recovery",
                "warn" if recovery["legacy_writes_blocked"] else "pass",
                "retained operation summary; no specific target or dependency conflict "
                "was assessed",
                "inspect operation show recovery_guidance and preview the intended target",
                observation=recovery,
            )
        )
    except Error as exc:
        checks.append(
            _check(
                "operation_recovery", "fail", exc.message, "inspect the retained state directory"
            )
        )
    if opts.get("installation"):
        from .. import deployment

        deployment_state = deployment.inspect(
            opts["installation"],
            creo=opts.get("creo"),
            java_home=opts.get("java_home"),
            timeout=min(opts.get("timeout", 30), 5),
        )
        checks.append(
            _check(
                "installation_files",
                "pass" if deployment_state["files_verified"] else "fail",
                "installed bytes and target registry independently checked",
                deployment_state.get("next_action"),
                observation=deployment_state,
            )
        )
        checks.append(
            _check(
                "installation_runtime",
                "pass" if deployment_state["loaded_verified"] else "warn",
                "actual process/component identity is separate from file installation",
                deployment_state.get("next_action"),
            )
        )
    kit = install.toolkit()
    if kit["present"]:
        checks.append(
            _check(
                "creo_api_toolkit", "pass", kit["detail"], creo_load_point=kit["creo_load_point"]
            )
        )
    elif install.streamed_delivery():
        checks.append(
            _check(
                "creo_api_toolkit",
                "fail",
                kit["detail"],
                "this Creo is delivered by an application-streaming player, which ships without "
                "the API "
                "toolkits and has no installer to add them; a standard licensed installation is "
                "needed",
            )
        )
    else:
        checks.append(
            _check(
                "creo_api_toolkit",
                "fail",
                kit["detail"],
                "re-run the Creo installer and select API Toolkits -> "
                f"'{install.TOOLKIT_COMPONENT}' "
                "(free with a Creo seat; there has been no separate J-Link selection since Creo "
                "4.0)",
            )
        )
    java = install.java_runtime()
    checks.append(
        _check(
            "creo_java_runtime",
            "pass" if java["resolved"] else "warn",
            java["detail"],
            None
            if java["resolved"]
            else "provide PRO_JAVA_COMMAND=Java 25 java.exe to an explicitly owned test process; "
            "the current CLI environment does not prove the existing Creo process configuration",
        )
    )
    service_checks = _service_checks(min(opts.get("timeout", 30), 5))
    checks += service_checks
    readable = any(
        c["check"] == "native_session_read" and c["status"] == "pass" for c in service_checks
    )
    verified = readable and bool(deployment_state and deployment_state.get("loaded_verified"))
    mismatch = deployment_state and not deployment_state.get("loaded_verified")
    checks.append(
        _check(
            "native_backend",
            "pass" if verified else "fail" if not readable or mismatch else "warn",
            "current session and declared component identity verified"
            if verified
            else "a handshake or session read alone does not prove the candidate component source",
            (
                "inspect doctor --installation <target> --creo <load point> "
                "--java-home <JDK>; use the supplied start-owned-creo.ps1 recipe in new "
                "owned startup/runtime directories; retain external trust/license blockers "
                "without desktop loading or changing existing instances"
            ),
            session_readable=readable,
            source_verified=verified,
            installation=deployment_state,
        )
    )
    store = discovery.state_observation()
    checks.append(
        _check(
            "state_store",
            "pass" if store["available"] else "warn",
            store.get("reason", "state store observation"),
            (
                "inspect the retained state directory; do not clear unknown records "
                "or create a new history to bypass them"
            ),
            observation=store,
        )
    )
    try:
        root = paths.workspace()
        checks.append(_check("workspace", "pass", str(root)))
    except Error as exc:
        checks.append(
            _check(
                "workspace",
                "warn",
                exc.message,
                "the user sets CREO_CLI_WORKSPACE to a disposable local directory; reads work "
                "without it",
            )
        )
    policy = safety.policy()
    checks.append(
        _check(
            "write_policy",
            "pass" if policy["confirm_allowed"] else "warn",
            f"permission={policy['permission']}, "
            f"native_writes_opt_in={policy['native_writes_opt_in']}",
            policy.get("fix"),
        )
    )
    level = RELEASE["level"]
    checks.append(
        _check(
            "presentation_scope",
            "warn",
            "explode/render support direct parts and matching assembly/window context; "
            "drawing-context global assembly display is not_checked, never false; "
            "visual review is separate",
            "inspect reference limits and docs/EXPLODE-RENDER.md before planning",
            limits=driver.PRESENTATION_LIMITS,
        )
    )
    checks.append(
        _check(
            "engineering_properties_scope",
            "warn",
            "material assignment requires source-binding capability 1 and independent "
            "density/config readback; numeric overrides require regenerated table ownership "
            "and standard-preservation capabilities",
            "inspect reference limits; inspect associated drawing lettering separately",
            limits=driver.ENGINEERING_PROPERTY_LIMITS,
        )
    )
    checks.append(
        _check(
            "workflow_scope",
            "warn",
            "property workflows require stable material inputs, verified standard prerequisites "
            "and final engineering-state checks; completed leaves do not imply a saved or "
            "fully successful parent",
            "inspect reference --command workflow run; query parent and child operations "
            "before evidence registration or explicit remaining actions",
            extensions={"creo": {"bounded_workflow": _workflow_profile()}},
        )
    )
    grant = driver.scope()
    checks.append(
        _check(
            "authorization",
            "pass" if grant.granted else "warn",
            "task scope status=" + grant.summary["status"],
            (
                "the user supplies the task scope; read-only discovery and retained "
                "history do not grant model writes"
            ),
            authorization=grant.authorization,
        )
    )
    checks.append(
        _check(
            "construction_scope",
            "warn",
            "revolve/datum leaves require revolved_datum_readback capability 1, native "
            "relationships and current geometry; creating workflows remain unsupported",
            "read reference limits and docs/REVOLVED-PART.md; keep unknown if the "
            "retained construction cannot be independently proved",
            limits=driver.CONSTRUCTION_LIMITS,
        )
    )
    checks.append(
        _check(
            "drawing_edit_scope",
            "warn",
            "view removal has no implicit cascade; missing incoming dependencies remain refused",
            "inspect reference --command 'drawing view remove' and docs/DRAWING-VIEW-REMOVAL.md",
            limits=driver.DRAWING_EDIT_LIMITS,
        )
    )
    checks.append(
        _check(
            "family_table_scope",
            "warn",
            "numeric family leaves require family_dimension_runtime 1 and complete origin/"
            "family readback 2; instance generation, generic saving and clean close are separate",
            "read reference limits and docs/FAMILY-TABLES.md; missing recovery geometry stays "
            "unproved, and model discard remains non-family only",
            limits=driver.FAMILY_TABLE_LIMITS,
        )
    )
    checks.append(
        _check(
            "machining_scope",
            "warn",
            "hole/round/shell require independent native definitions and current-solid geometry; "
            "bounded shell also requires prismatic_shell_readback 2",
            "inspect reference limits; advanced forms and manufacturing approval remain unverified",
            limits=driver.MACHINING_LIMITS,
        )
    )
    checks.append(
        _check(
            "task_scope",
            "pass" if grant.granted else "warn",
            "migrated writes require an active task scope; status=" + grant.summary["status"],
            "user supplies CREO_CLI_SCOPE_FILE; CLI never grants itself a scope",
            authorization=grant.authorization,
        )
    )
    checks.append(
        _check(
            "release_readiness",
            {"stable": "pass", "beta": "warn"}.get(level, "fail"),
            f"release readiness is {level}",
            None if level == "stable" else RELEASE["reason"],
            level=level,
        )
    )
    return {"checks": checks, "_untrusted": ["checks"]}


def _diagnostic_options(opts):
    if (opts.get("creo") or opts.get("java_home")) and not opts.get("installation"):
        raise Error(
            "E_USAGE",
            "declared Creo/Java paths require --installation",
            {
                "problem": "missing_parameter",
                "fix": "provide the explicit component directory or omit the host-path options",
            },
        )


def _installed_check() -> dict:
    """Whether a service bundle is installed, when the service is not answering."""
    found = service_bundle.installed(safety.directory())
    if not found:
        return _check(
            "service_installed",
            "warn",
            "no service bundle is installed in creo-cli's directory",
            (
                "use the declared candidate service-bundle: creo-cli service install "
                "--from <bundle> --target <owned target> --dry-run; inspect scope and"
                " then confirm"
            ),
        )
    newest = found[-1]
    return _check(
        "service_installed",
        "pass",
        f"service {newest['version']} installed; Creo loads it once registered",
        "use the supplied start-owned-creo.ps1 with this installed component directory; "
        "both components auto-start in a new owned process and readiness/load identity "
        "are checked separately; preserve any external trust/license blocker",
    )


def _service_checks(timeout: float) -> list[dict]:
    """The service, probed live with a short deadline so doctor stays quick without Creo."""
    out = []
    try:
        with transport.Client(timeout) as client:
            health = client.probe()
            if health.get("service") != "creo-cli" or health.get("protocol") != transport.PROTOCOL:
                return [
                    _check(
                        "service",
                        "fail",
                        f"the endpoint answers with protocol {health.get('protocol')}; this CLI "
                        "speaks "
                        f"{transport.PROTOCOL}",
                        (
                            "install the service that ships with this CLI in an owned target; "
                            "start a new owned instance with start-owned-creo.ps1; "
                            "do not manually load services or restart other instances"
                        ),
                    )
                ]
            out.append(
                _check(
                    "service", "pass", f"answering at {client.url}, protocol {transport.PROTOCOL}"
                )
            )
            s = client.op("session.status")
    except Error as exc:
        return out + [
            _check(
                "native_session_read" if out else "service", "fail", exc.message, transport.SETUP
            ),
            _installed_check(),
        ]
    out.append(
        _check(
            "native_session_read",
            "pass",
            "current CAD session.status reader completed; this does not establish source identity",
        )
    )
    out.append(
        _check(
            "creation_api",
            "pass" if s.get("creation_api") else "fail",
            "the session can build features"
            if s.get("creation_api")
            else "the session can read models but not build features",
            None
            if s.get("creation_api")
            else "the service must run as an Object TOOLKIT Java application under the "
            "ObjectToolkitJava licence",
        )
    )
    out.append(
        _check(
            "native_sketch_library",
            "pass" if s.get("native_sketch_available") else "warn",
            str(s.get("native_sketch_library")),
            None
            if s.get("native_sketch_available")
            else "rectangles, polygons, slots, outlines and profiles with holes need "
            "creo_cli_sketch.dll registered and loaded; circles and ellipses work",
        )
    )
    try:
        paths.contained(str(s.get("working_directory")), directory=True)
        out.append(_check("working_directory", "pass", str(s.get("working_directory"))))
    except Error as exc:
        if exc.code == "E_CONFIG":
            out.append(
                _check(
                    "working_directory",
                    "warn",
                    "no workspace is configured to check it against",
                    None,
                )
            )
        else:
            out.append(
                _check(
                    "working_directory",
                    "warn",
                    f"Creo's working directory {s.get('working_directory')} is not inside the "
                    "workspace",
                    "creo-cli session cd --path <directory inside CREO_CLI_WORKSPACE>",
                )
            )
    return out


def changelog_path() -> Path:
    """CHANGELOG.md in a frozen binary, a source checkout, or a pip installation."""
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "CHANGELOG.md"
        if getattr(sys, "_MEIPASS", None)
        else None,
        Path(__file__).resolve().parents[2] / "CHANGELOG.md",
        Path(sys.prefix) / "share" / "creo-cli" / "CHANGELOG.md",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise Error("E_IO", "the changelog is not installed with this build")


_VERSION = (
    r"\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?"
)


def _version_key(version: str) -> tuple:
    core, _, prerelease = version.split("+", 1)[0].partition("-")
    identifiers = (
        tuple((0, int(value)) if value.isdigit() else (1, value) for value in prerelease.split("."))
        if prerelease
        else ()
    )
    return tuple(map(int, core.split("."))), not bool(prerelease), identifiers


def changelog(opts: dict) -> dict:
    since = opts.get("since")
    if since and not re.fullmatch(_VERSION, since):
        raise Error(
            "E_VALIDATION",
            "--since expects a version like 1.0.0 or 1.1.0-beta.1",
            {"path": "since"},
        )
    entries, current, category, bullet = [], None, None, None
    for line in changelog_path().read_text(encoding="utf-8").splitlines():
        m = re.match(r"## \[(" + _VERSION + r")\] - (\d{4}-\d{2}-\d{2})", line)
        if m:
            current = {
                "version": m[1],
                "date": m[2],
                "changes": {
                    k: []
                    for k in ("added", "changed", "fixed", "removed", "deprecated", "security")
                },
            }
            entries.append(current)
            category, bullet = None, None
        elif line.startswith("### "):
            category, bullet = line[4:].strip().lower(), None
        elif current and category in current["changes"] and line.startswith("- "):
            bullet = current["changes"][category]
            bullet.append(line[2:])
        elif bullet and line.startswith("  ") and line.strip():
            bullet[-1] += " " + line.strip()  # a wrapped bullet continues on indented lines
        elif current and category is None and line.strip():
            current["summary"] = (current.get("summary", "") + " " + line.strip()).strip()
    if since:
        key = _version_key(since)
        entries = [e for e in entries if _version_key(e["version"]) > key]
    return {"current_version": __version__, "since": since, "entries": entries}


CHECK = shape(
    {"check": S, "status": {"type": "string", "enum": ["pass", "warn", "fail"]}, "message": S},
    ("check", "status", "message"),
)
INSTALLATION_PARAMS = (
    Param(
        "installation",
        description=(
            "explicit component directory; inspect disk and declared runtime, "
            "recording a local load anchor when proved"
        ),
    ),
    Param(
        "creo", description="declared Creo load point containing Common Files; with --installation"
    ),
    Param(
        "java-home",
        description="declared JDK directory containing bin/java.exe; with --installation",
    ),
)
COMMANDS = [
    Command(
        "reference",
        "The machine contract: commands, flags, schemas, error codes, capabilities, release "
        "readiness",
        reference,
        shape(
            {
                "tool": S,
                "version": S,
                "risk_tier": S,
                "release_readiness": shape({}),
                "commands": array(shape({})),
                "schemas": shape({}),
                "error_codes": shape({}),
                "exit_codes": shape({}),
                "global_flags": array(shape({})),
                "driver_profile": shape({}),
                "view": S,
                "command": shape({}),
                "json_schemas": shape({}),
                "public_schemas": array(S),
            },
            ("tool", "version", "driver_profile"),
        )
        | {
            "anyOf": [
                {"$ref": "urn:tool-driver-cli-spec:" + name + ":2.0"}
                for name in ("reference", "reference-index", "reference-command")
            ]
        },
        (
            Param(
                "index",
                "boolean",
                description="compact pinned command index; no schemas; excludes --command",
            ),
            Param(
                "command",
                description=(
                    "exact path returns the pinned single-command view; a noun prefix "
                    "retains a filtered full reference"
                ),
            ),
        ),
    ),
    Command(
        "context",
        (
            "Offline local configuration by default; an explicit --installation "
            "inspects disk and declared process/component identity only; connected does not "
            "verify CAD readers, idle state, getter completion or recovery"
        ),
        context,
        shape(
            {
                "version": S,
                "config": shape({}),
                "service": shape({}),
                "credentials": shape({}),
                "capabilities": shape({}),
                "driver_profile": shape({}),
                "authorization": shape({}),
                "environment": shape({}),
                "state": shape({}),
            },
            (
                "version",
                "config",
                "service",
                "credentials",
                "driver_profile",
                "authorization",
                "environment",
                "state",
            ),
        )
        | {"allOf": [{"$ref": "urn:tool-driver-cli-spec:context:2.0"}]},
        INSTALLATION_PARAMS,
        untrusted=("config",),
    ),
    Command(
        "doctor",
        "Diagnose installation, service, workspace and policy, each with a fix; probes the service "
        "briefly",
        doctor,
        shape({"checks": array(CHECK)}, ("checks",))
        | {"allOf": [{"$ref": "urn:tool-driver-cli-spec:doctor:2.0"}]},
        INSTALLATION_PARAMS,
        untrusted=("checks",),
        service_ops=("session.status",),
    ),
    Command(
        "changelog",
        "What changed between versions, from the packaged changelog",
        changelog,
        shape({"current_version": S, "entries": array(shape({}))}, ("current_version", "entries")),
        (Param("since", description="only versions newer than this, e.g. 1.0.0"),),
    ),
]
