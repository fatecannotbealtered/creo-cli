"""Public discovery projections and local observations; never infer native verification."""

from __future__ import annotations

import os
import platform
import stat
from pathlib import Path

from . import __version__, driver, execution_budgets, operations, safety, service_bundle
from .core import CODES, Error

PUBLIC = "urn:tool-driver-cli-spec:"
RECORD_CONTROL = "operation resolve"


def metadata(command):
    if command.path in driver.MIGRATED:
        return driver.command_metadata(command.path)
    record = command.path == RECORD_CONTROL
    target_write = command.write and not record
    effects = ["observe"]
    if target_write:
        effects.append("session" if command.path == "model discard" else "change")
    mode = "session" if command.service_ops else "file"
    limits = ["Declaration and syntax coverage are not native task verification or whole-tree FCC"]
    if target_write:
        limits.append(
            "Legacy write lifecycle: global unresolved-operation gate; public "
            "receipt migration incomplete"
        )
    elif record:
        limits.append(
            "Tool-record control only; --outcome requires original scope and "
            "independent current evidence. Legacy --decision retains its "
            "preview/confirm gate. Command-specific previews/confirmations can dispatch CAD "
            "getters; independently settle any pending original read and instance state first"
        )
    elif command.path in ("operation show", "operation list", "workflow show"):
        limits.append(
            "Retained records only; no CAD connection, task scope or write permission required. "
            "Missing native-read evidence does not prove the original getter ended"
        )
    elif command.path == "operation query":
        limits.append(
            "Current target observation requires observe scope; CAD needs "
            "--model, installation queries use the retained file target without "
            "--model. CAD getters require any pending original read and instance state to "
            "be independently settled first"
        )
    return {
        "capability_id": command.path.replace(" ", "-"),
        "effects": effects,
        "phases": ["observe", "plan", "apply", "verify"] if target_write else ["observe"],
        "modes": [mode],
        "maturity": "experimental",
        "environments": [
            {
                "application": "Creo Parametric",
                "application_version": "13.4.1.0",
                "platform": "Windows",
                "arch": "x86_64",
                "adapter_version": __version__,
                "mode": mode,
                "limitations": limits,
            }
        ],
        "limits": limits,
        "recovery": {"atomicity": "none", "undo": False, "idempotent": False, "cancel": False},
        "profiles": ["core"],
        "error_codes": sorted(CODES),
        "evidence_refs": ["docs/RUNTIME-MIGRATION.md"],
    }


def counts():
    from .registry import COMMANDS

    return {
        "registered_commands": len(COMMANDS),
        "registered_write_gate_paths": sum(c.write for c in COMMANDS),
        "target_write_commands": sum(c.write and c.path != RECORD_CONTROL for c in COMMANDS),
        "record_control_gate_paths": [RECORD_CONTROL],
        "public_runtime_write_paths": len(driver.MIGRATED),
        "surveyed_capability_groups": 36,
        "meaning": (
            "Commands, historical write-gate paths, migrated target paths and "
            "survey groups have different denominators; none is whole-tree "
            "behavior FCC"
        ),
        "behavior_FCC": "partial",
    }


def units(command, parameter):
    if parameter.name in ("x", "y") and command.startswith("drawing "):
        return "sheet_length_unit; origin at lower-left of the actual target sheet"
    if command == "drawing view add" and parameter.name == "radius":
        return "model_length_unit"
    if command.startswith("dimension ") and parameter.type == "number":
        return "the selected native dimension's unit (length or angle)"
    if command == "artifact render" and parameter.name in ("width", "height"):
        return "pixel"
    return None


def public_refs(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith(PUBLIC):
                found.add(item.split("#")[0])
            found.update(public_refs(item))
    elif isinstance(value, list):
        for item in value:
            found.update(public_refs(item))
    return found


def command_view(command, description, schema, profile, errors):
    result = {
        "view": "command",
        "tool": "creo-cli",
        "version": __version__,
        "driver_profile": profile,
        "command": description,
        "schemas": {command.schema_name: schema},
        "error_codes": errors,
        "json_schemas": {execution_budgets.SCHEMA_ID: execution_budgets.SCHEMA}
        if command.path in execution_budgets.COMMANDS
        else {},
    }
    if command.request is not None:
        uri = "urn:creo-cli:request:" + command.path.replace(" ", "-") + ":1.0"
        result["command"]["driver"]["request_schema"] = uri
        result["json_schemas"][uri] = command.request
    refs = public_refs(schema)
    if command.path in driver.MIGRATED:
        refs |= {PUBLIC + name + ":2.0" for name in ("plan", "receipt", "scope", "common")}
    refs |= {PUBLIC + name + ":2.0" for name in ("reference-command", "common")}
    result["public_schemas"] = sorted(refs)
    return result


def state_observation():
    """Readability, not a write probe. Discovery never creates or repairs the store."""
    root = safety.directory()
    result = {
        "dir": str(root),
        "available": False,
        "protection": "unknown",
        "record_retention_days": None,
    }
    try:
        operations.no_links(root)
        if not root.is_dir():
            result["reason"] = "state directory not initialized; discovery did not create it"
            return result
        operations.summaries()
        result["available"] = True
        if (
            os.name != "nt"
            and stat.S_IMODE(root.stat().st_mode) & 0o077 == 0
            and root.stat().st_uid == os.getuid()
        ):
            result["protection"] = "posix_owner_only"
        elif os.name == "nt" and root.resolve().is_relative_to(Path.home().resolve()):
            result["protection"] = "windows_profile_acl"
        result["reason"] = (
            "existing records are readable; write availability is checked before "
            "dispatch; custom Windows ACLs are not inferred"
        )
    except (Error, OSError) as exc:
        result["reason"] = (
            exc.message if isinstance(exc, Error) else "state directory could not be inspected"
        )
    return result


def environment(installation=None):
    components = [
        {
            "name": "creo-cli",
            "role": "cli",
            "version": __version__,
            "build_id": None,
            "location": "disk",
            "identity_status": "observed",
            "reason": "running CLI version; no installed-binary hash asserted by self-description",
        }
    ]
    connection = {
        "status": "unknown",
        "instance_id": None,
        "generation": None,
        "ownership": None,
        "reason": "not probed by offline context",
    }
    if installation is not None:
        files = installation.get("component_files") or {}
        for filename, item in files.items():
            if not isinstance(item, dict) or not item.get("sha256"):
                continue
            components.append(
                {
                    "name": filename,
                    "role": "service" if filename.endswith(".jar") else "plugin",
                    "version": None,
                    "build_id": item.get("sha256"),
                    "location": "disk",
                    "identity_status": "observed",
                    "reason": "explicit installation file hash; loaded identity and CAD "
                    "readiness require separate evidence",
                }
            )
        running = installation.get("observed_runtime") or {}
        if running:
            components.append(
                {
                    "name": "running creo-cli-service",
                    "role": "service",
                    "version": None,
                    "build_id": running.get("source_sha256"),
                    "location": "running",
                    "identity_status": "observed",
                    "reason": "health-reported source; actual loaded-file validation is separate",
                }
            )
        pin = installation.get("runtime_pin") or {}
        identity = installation.get("runtime_identity") or {}
        processes = installation.get("process_identities") or []
        by_pid = {row.get("pid"): row for row in processes if isinstance(row, dict)}
        # Project an actual completed deployment observation. Health or a lone
        # loaded_verified flag cannot supply missing process/component evidence.
        loaded = (
            installation.get("files_verified") is True
            and installation.get("loaded_verified") is True
            and identity.get("passed") is True
            and bool(running.get("service_instance_id"))
            and running.get("service_instance_id")
            == pin.get("service_instance_id")
            == identity.get("service_instance_id")
            and bool(running.get("source_sha256"))
            and running.get("source_sha256") == installation.get("component_source_sha256")
            and bool(running.get("runtime_class"))
            and running.get("runtime_class") == installation.get("java_app_class")
            and bool(running.get("process_started_at"))
            and all(
                isinstance(files.get(name), dict) and bool(files[name].get("sha256"))
                for name in (service_bundle.JAR, service_bundle.DLL)
            )
            and identity.get("java_pid") == pin.get("java_pid")
            and identity.get("native_host_pid") == pin.get("native_pid")
            and all(
                bool(by_pid.get(pin.get(key), {}).get("actual_image"))
                and bool(by_pid.get(pin.get(key), {}).get("creation_filetime"))
                and by_pid[pin[key]]["creation_filetime"]
                == (pin.get("process_creations") or {}).get(str(pin[key]))
                for key in ("java_pid", "native_pid")
            )
        )
        if loaded:
            for name, role, pid in (
                ("Creo Parametric", "application", pin["native_pid"]),
                ("Java", "runtime", pin["java_pid"]),
            ):
                row = by_pid[pid]
                components.append(
                    {
                        "name": name,
                        "role": role,
                        "version": None,
                        "build_id": None,
                        "location": "running",
                        "identity_status": "observed",
                        "reason": "validated process identity at "
                        + row["actual_image"]
                        + "; version not observed; process-only evidence",
                    }
                )
            for component in components:
                if component["role"] in ("service", "plugin"):
                    component["reason"] = (
                        "explicit installation/runtime gate verified this generation's "
                        "component identity; process-only evidence, not CAD reader, idle, "
                        "getter completion or recovery verification"
                    )
            connection.update(
                status="connected",
                instance_id=pin.get("service_instance_id"),
                generation=str(pin.get("process_creations")),
                ownership="attached",
                reason=(
                    "explicit installation inspection verified current process/component "
                    "identity only; no CAD reader, idle, getter completion or recovery "
                    "verification"
                ),
            )
        else:
            connection.update(
                status="unavailable",
                reason=(
                    "complete installation/runtime identity evidence is unavailable; "
                    "inspect extensions.creo.installation"
                ),
            )
    observed_roles = {component["role"] for component in components}
    for name, role in (
        ("creo-cli-service", "service"),
        ("creo_cli_sketch", "plugin"),
        ("Creo Parametric", "application"),
        ("Java", "runtime"),
    ):
        if role in observed_roles:
            continue
        components.append(
            {
                "name": name,
                "role": role,
                "version": None,
                "build_id": None,
                "location": "unknown",
                "identity_status": "unavailable",
                "reason": (
                    "offline context did not observe this component; use an explicit "
                    "installation inspection for current identity"
                    if installation is None
                    else "explicit installation inspection did not verify this component's "
                    "identity; inspect extensions.creo.installation"
                ),
            }
        )
    return {
        "platform": platform.system(),
        "arch": platform.machine() or "unknown",
        "components": components,
        "connection": connection,
    }
