"""Durable render ownership and read-only recovery; never render or publish on lookup."""

from pathlib import Path

from . import operations, paths
from .core import Error, digest


def file_identity(path):
    """Bind bytes and physical file identity, including a link created before a crash."""
    path = Path(path)
    paths.no_links(path)
    before = path.stat()
    artifact = paths.artifact(path)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, k) != getattr(after, k) for k in fields):
        raise Error("E_CONFLICT", "render file changed during identity read")
    return artifact | {"device": after.st_dev, "inode": after.st_ino, "mtime_ns": after.st_mtime_ns}


def checkpoint(run, **values):
    record = run["driver_render"] | values
    candidate = run | {"driver_render": record}
    operations.update(candidate)
    run["driver_render"] = record


def prepare(run, staged, output, binding, request):
    """Must succeed before any native dispatch. Paths are actual, never reconstructed guesses."""
    record = {
        "version": 1,
        "operation_id": run["operation_id"],
        "target": run["driver_plan"]["target"],
        "owner": run["driver_owner"],
        "workspace": str(paths.workspace()),
        "staged_path": str(staged),
        "requested_output": str(output),
        "request_sha256": digest(request),
        "before": binding,
        "phase": "prepared",
    }
    # The stage is private and must not pre-exist. Preview never creates it.
    if staged.parent.exists() or output.exists():
        raise Error("E_CONFLICT", "render stage or output already exists; nothing dispatched")
    operations.update(run | {"driver_render": record})
    run["driver_render"] = record
    staged.parent.mkdir(parents=True, exist_ok=False)
    checkpoint(run, phase="dispatching")


def inspect(run):
    """Observe only the two operation-bound paths, even when Creo is unavailable.

    A file at the output pathname alone is NOT publication evidence. A retained
    verified stage identity must match its inode and bytes. Legacy records safely
    lack that proof. File observations never settle the original operation.
    """
    result = {
        "state": "evidence_incomplete",
        "phase": None,
        "dispatch": "unknown",
        "files": {},
        "artifacts": [],
        "issues": [],
        "source": "retained operation ownership and exact-path independent disk reads",
        "session_state": "not_queried; retained observations are historical only",
        "automatic_replay": False,
        "automatic_publication": False,
    }
    record = run.get("driver_render")
    plan = run["driver_plan"]
    request = plan["changes"][0].get("after", {})
    try:
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("missing or unsupported render ownership record")
        if (
            record["operation_id"] != run["operation_id"]
            or record["target"] != plan["target"]
            or record["request_sha256"] != digest(request)
            or record["requested_output"] != request.get("output")
        ):
            raise ValueError("render ownership does not match retained plan")
        root = Path(record["workspace"])
        stage, output = Path(record["staged_path"]), Path(record["requested_output"])
        if (
            not root.is_absolute()
            or not stage.is_absolute()
            or not output.is_absolute()
            or not stage.is_relative_to(root / ".creo-cli" / "staging")
            or not output.is_relative_to(root)
            or stage == output
            or ".." in stage.parts
            or ".." in output.parts
        ):
            raise ValueError("invalid retained render paths")
        result["phase"] = record["phase"]
        if record["phase"] == "prepared":
            result["dispatch"] = "not_started"
        for label, path in (("staged", stage), ("output", output)):
            try:
                identity = file_identity(path)
                result["files"][label] = {"state": "observed", **identity}
            except FileNotFoundError:
                result["files"][label] = {"path": str(path), "state": "absent"}
            except (Error, OSError) as exc:
                result["files"][label] = {"path": str(path), "state": "unreadable"}
                result["issues"].append({"file": label, "error": type(exc).__name__})
        staged, published = result["files"]["staged"], result["files"]["output"]
        verified = record.get("verified_file")
        same = bool(
            verified
            and verified.get("inode")
            and published["state"] == "observed"
            and all(
                published.get(k) == verified.get(k)
                for k in ("device", "inode", "sha256", "size_bytes", "mtime_ns")
            )
        )
        if staged["state"] == "observed":
            result["artifacts"].append(staged)
        if same:
            result["artifacts"].append(published)
        if not result["issues"]:
            result["state"] = (
                "published_output"
                if same
                else "evidence_incomplete"
                if published["state"] != "absent"
                else "staged_observed"
                if staged["state"] == "observed"
                else "no_generated_file_observed"
            )
        if published["state"] == "observed" and not same:
            result["issues"].append({"file": "output", "error": "ownership_not_proven"})
        if record["phase"] == "published" and not same:
            result["state"] = "evidence_incomplete"
            result["issues"].append(
                {"file": "output", "error": "retained_publication_no_longer_observable"}
            )
        result["retained_readback"] = record.get("readback")
        result["retained_decode"] = record.get("decoded")
    except (KeyError, TypeError, ValueError) as exc:
        result["issues"].append({"error": str(exc)})
    return result
