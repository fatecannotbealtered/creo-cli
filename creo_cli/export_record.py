"""Durable exact-file export ownership; inspection never exports, publishes or settles."""

import hashlib
from pathlib import Path

from . import operations, paths
from .core import Error, digest


def file_identity(path):
    """Read a stable regular file and retain physical identity as well as its bytes."""
    artifact = paths.artifact(Path(path), identity=True)
    device, inode, _size, modified = artifact.pop("file_identity")
    return artifact | {"device": device, "inode": inode, "mtime_ns": modified}


def read_file(path, fmt):
    from .commands.model import header_ok

    identity = file_identity(path)
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != identity["sha256"] or file_identity(path) != identity:
        raise Error("E_CONFLICT", "export file changed during header verification")
    return identity | {"header_valid": bool(raw) and header_ok(fmt, raw)}


def checkpoint(run, **values):
    record = run["driver_export"] | values
    operations.update(run | {"driver_export": record})
    run["driver_export"] = record


def prepare(run, output, binding, request, suffix):
    """Persist the actual stage before creating it or dispatching any native operation."""
    staged = (
        paths.workspace()
        / ".creo-cli"
        / "staging"
        / run["operation_id"]
        / (request["model"].split(".")[0] + suffix)
    )
    paths.no_links(staged)
    if staged.parent.exists() or output.exists():
        raise Error("E_CONFLICT", "export stage or output already exists; nothing dispatched")
    record = {
        "version": 1,
        "operation_id": run["operation_id"],
        "target": run["driver_plan"]["target"],
        "owner": run["driver_owner"],
        "workspace": str(paths.workspace()),
        "staged_path": str(staged),
        "requested_output": str(output),
        "model": request["model"],
        "format": request["format"],
        "request_sha256": digest(request),
        "before": binding,
        "phase": "prepared",
        "consumer_verification": "not_checked",
    }
    operations.update(run | {"driver_export": record})
    run["driver_export"] = record
    staged.parent.mkdir(parents=True, exist_ok=False)
    checkpoint(run, phase="dispatching")
    return staged


def retained(run):
    """Local history only. Current file observation still requires public query scope."""
    record = run.get("driver_export")
    record = record if isinstance(record, dict) else {}
    return {
        "state": "not_observed",
        "phase": record.get("phase"),
        "dispatch": "unknown",
        "generated": None,
        "published": None,
        "verification_scope": "retained_history_only",
        "consumer_verification": "not_checked",
        "files": {},
        "artifacts": [],
        "issues": [],
        "source": "retained export ownership only; current files were not inspected",
        "retained_ownership": {
            key: record.get(key)
            for key in (
                "model",
                "format",
                "staged_path",
                "requested_output",
                "native_reply_returned",
                "header_verification",
            )
        },
        "CAD_state": "not_queried; local history does not establish native call completion",
        "automatic_replay": False,
        "automatic_publication": False,
        "can_register": [],
    }


def inspect(run):
    """Independent exact-path disk reads; absence is not proof a native export did not run."""
    from .commands.model import FORMATS

    result = {
        "state": "evidence_incomplete",
        "phase": None,
        "dispatch": "unknown",
        "generated": None,
        "published": None,
        "verification_scope": "file_identity_and_header_only",
        "consumer_verification": "not_checked",
        "files": {},
        "artifacts": [],
        "issues": [],
        "source": "retained export ownership and exact-path independent disk reads",
        "CAD_state": "not_queried; file observations do not establish native call completion",
        "automatic_replay": False,
        "automatic_publication": False,
        "can_register": [],
    }
    record = run.get("driver_export")
    try:
        plan = run["driver_plan"]
        request = plan["changes"][0]["after"]
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("missing or unsupported export ownership record")
        if (
            record["operation_id"] != run["operation_id"]
            or run["request_sha256"] != digest(request)
            or record["target"] != plan["target"]
            or record["owner"] != run["driver_owner"]
            or record["request_sha256"] != digest(request)
            or record["model"] != request.get("model")
            or record["model"] != run["target"]
            or record["model"] != plan["target"]["object_id"]
            or record["format"] != request.get("format")
            or record["requested_output"] != request.get("output")
        ):
            raise ValueError("export ownership does not match retained operation and plan")
        root, output, stage = (
            Path(record[key]) for key in ("workspace", "requested_output", "staged_path")
        )
        expected = (
            root
            / ".creo-cli"
            / "staging"
            / run["operation_id"]
            / (record["model"].split(".")[0] + FORMATS[record["format"]])
        )
        if (
            root != paths.workspace()
            or not root.is_absolute()
            or not output.is_absolute()
            or not output.is_relative_to(root)
            or stage != expected
            or stage == output
            or ".." in stage.parts
            or ".." in output.parts
        ):
            raise ValueError("invalid retained export paths")
        result["phase"] = record["phase"]
        if record["phase"] == "prepared":
            result["dispatch"] = "not_started"
        for label, path in (("staged", stage), ("output", output)):
            try:
                paths.no_links(path)
                result["files"][label] = (
                    {"state": "observed", **read_file(path, record["format"])}
                    if path.exists()
                    else {"path": str(path), "state": "absent"}
                )
            except (Error, OSError) as exc:
                result["files"][label] = {"path": str(path), "state": "unreadable"}
                result["issues"].append({"file": label, "error": type(exc).__name__})
        staged, output_file = result["files"]["staged"], result["files"]["output"]
        verified = record.get("verified_file")
        same = bool(
            verified
            and verified.get("inode")
            and output_file["state"] == "observed"
            and all(
                output_file.get(key) == verified.get(key)
                for key in ("device", "inode", "sha256", "size_bytes", "mtime_ns")
            )
        )
        result["generated"] = staged["state"] == "observed" or same
        result["published"] = same
        if staged["state"] == "observed" and not same:
            result["artifacts"].append(staged)
        if same:
            result["artifacts"].append(output_file)
        if output_file["state"] == "observed" and not same:
            result["issues"].append({"file": "output", "error": "ownership_not_proven"})
        if record["phase"] == "published" and not same:
            result["issues"].append({"file": "output", "error": "publication_no_longer_observable"})
        if not result["issues"]:
            result["state"] = (
                "published_output"
                if same
                else "generated_unpublished"
                if result["generated"]
                else "no_generated_file_observed"
            )
        result["retained_header_verification"] = record.get("header_verification", "not_checked")
    except (Error, KeyError, TypeError, ValueError) as exc:
        result["issues"].append({"error": str(exc)})
    return result
