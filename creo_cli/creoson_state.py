"""Workspace containment and crash-visible execution receipts for CREOSON writes."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import safety
from .core import Error, canonical, decode, digest, redact

MAX_ARTIFACT = 256 * 1024 * 1024


def workspace() -> Path:
    raw = os.environ.get("CREO_CLI_WORKSPACE")
    if not raw:
        raise Error("E_CONFIG", "native writes require CREO_CLI_WORKSPACE pointing to a disposable local workspace")
    p = Path(raw).expanduser().absolute()
    if not p.is_dir():
        raise Error("E_CONFIG", "CREO_CLI_WORKSPACE is not an existing directory")
    no_links(p)
    return p.resolve()


def no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise Error("E_FORBIDDEN", "native workspace paths must not use symlinks or junctions")


def contained(value: str, *, directory: bool | None = None, exists: bool = True) -> Path:
    root = workspace()
    # Reject network paths and traversal even when normalization would remain in root.
    if value.startswith(("\\\\", "//")) or ".." in value.replace("\\", "/").split("/"):
        raise Error("E_FORBIDDEN", "network paths and parent traversal are not permitted")
    p = Path(value).expanduser()
    p = p if p.is_absolute() else root / p
    p = p.absolute()
    no_links(p)
    p = p.resolve()
    if not p.is_relative_to(root):
        raise Error("E_FORBIDDEN", "path is outside the configured disposable workspace")
    if exists and not p.exists():
        raise Error("E_NOT_FOUND", "workspace resource not found", {"path": str(p), "_untrusted": ["path"]})
    if exists and directory is not None and (not p.is_dir() if directory else not p.is_file()):
        raise Error("E_VALIDATION", "workspace resource has the wrong file type")
    return p


def artifact(path: Path) -> dict:
    no_links(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
        h, size = hashlib.sha256(), 0
        with os.fdopen(fd, "rb") as f:
            before = os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARTIFACT:
                raise Error("E_VALIDATION", "artifact must be a regular file no larger than 256 MiB")
            while block := f.read(1024 * 1024):
                h.update(block)
                size += len(block)
                if size > MAX_ARTIFACT:
                    raise Error("E_VALIDATION", "artifact grew past 256 MiB")
            after = os.fstat(f.fileno())
        latest = path.stat()
        stamp = lambda s: (s.st_size, s.st_mtime_ns, s.st_ino)
        if stamp(before) != stamp(after) or stamp(after) != stamp(latest):
            raise Error("E_CONFLICT", "artifact changed while hashing")
        return {"path": str(path), "size_bytes": size, "sha256": h.hexdigest()}
    except OSError as exc:
        raise Error("E_IO", "cannot read native artifact") from exc


def model_files(directory: Path, filename: str) -> list[dict]:
    pattern = re.compile(re.escape(filename) + r"(?:\.[0-9]+)?$", re.I)
    matches = []
    try:
        with os.scandir(directory) as entries:
            for n, entry in enumerate(entries):
                if n >= 20000:
                    raise Error("E_VALIDATION", "workspace directory exceeds 20000 entries")
                if pattern.fullmatch(entry.name):
                    matches.append(artifact(Path(entry.path)))
                    if len(matches) > 100:
                        raise Error("E_VALIDATION", "more than 100 versions; narrow the working copy")
    except OSError as exc:
        raise Error("E_IO", "cannot inspect native model versions") from exc
    return sorted(matches, key=lambda x: x["path"].casefold())


def _db():
    db = safety._database("creoson-operations.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL)")
    return db


def begin(identity: dict, command: str, plan: list) -> dict:
    run = {"operation_id": uuid.uuid4().hex, "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
           "command": command, "status": "running", "manifest_sha256": digest(plan),
           "endpoint_sha256": digest(identity), "completed_steps": 0, "steps": [],
           "rollback_performed": False, "live_verified": False}
    db = _db()
    try:
        db.execute("INSERT INTO runs VALUES (?,?,?,?)", (run["operation_id"], run["endpoint_sha256"], run["status"], canonical(run).decode()))
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot persist execution intent; no new upstream write attempted") from exc
    finally:
        db.close()
    return run


def update(run: dict) -> None:
    raw = canonical(redact(run))
    if len(raw) > 4 * 1024 * 1024:
        raise Error("E_IO", "receipt exceeds 4 MiB; execution stopped")
    db = _db()
    try:
        db.execute("UPDATE runs SET status=?,body=? WHERE id=?", (run["status"], raw.decode(), run["operation_id"]))
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot checkpoint receipt; a previous write may have completed", {"state_unknown": True}) from exc
    finally:
        db.close()


def all_runs() -> list[dict]:
    p = safety.directory() / "creoson-operations.sqlite3"
    if not p.exists():
        return []
    no_links(p)
    db = None
    try:
        db = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=3)
        rows = db.execute("SELECT body FROM runs ORDER BY rowid DESC LIMIT 1001").fetchall()
        if len(rows) > 1000:
            raise Error("E_VALIDATION", "receipt history exceeds 1000 runs; archive the database after inspection")
        try:
            results = [decode(row[0]) for row in rows]
            for r in results:
                if (not isinstance(r, dict) or not re.fullmatch(r"[a-f0-9]{32}", str(r.get("operation_id", "")))
                        or r.get("status") not in ("running", "completed", "failed_before_write", "unknown", "partial", "verification_failed", "human_acknowledged")
                        or type(r.get("steps")) is not list):
                    raise Error("E_INTEGRITY", "invalid persisted execution receipt")
            return results
        except Error as exc:
            raise Error("E_INTEGRITY", "execution history is corrupt; native writes remain blocked") from exc
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot read execution history; refusing to assume prior writes completed") from exc
    finally:
        if db:
            db.close()


def get_run(operation_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
        raise Error("E_VALIDATION", "operation ID must be a 32-character hexadecimal string")
    for run in all_runs():
        if run["operation_id"] == operation_id:
            return run
    raise Error("E_NOT_FOUND", "operation receipt not found")


def require_clear() -> None:
    # Global rather than per-endpoint: different microservers may drive one Creo.
    blocked = [r["operation_id"] for r in all_runs() if r["status"] in ("running", "unknown", "partial", "verification_failed")]
    if blocked:
        raise Error("E_CONFLICT", "unresolved previous execution; read workflow status and inspect Creo before explicit human reconciliation",
                    {"operation_ids": blocked, "automatic_retry": False})


def save_result(operation_id: str, step_id: str, result: dict) -> dict:
    from .core import atomic_write
    root = safety.directory(True) / "creoson-results"
    no_links(root)
    root.mkdir(exist_ok=True, mode=0o700)
    run_dir = root / operation_id
    no_links(run_dir)
    run_dir.mkdir(exist_ok=True, mode=0o700)
    p = run_dir / (step_id + ".json")
    raw = canonical(redact(result)) + b"\n"
    if len(raw) > 8 * 1024 * 1024:
        raise Error("E_IO", "step result exceeds storage limit; native write may already have completed")
    atomic_write(p, raw, overwrite=False)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def load_result(operation_id: str, step_id: str, expected: dict) -> dict:
    from .core import read_bytes
    if not re.fullmatch(r"[a-f0-9]{32}", operation_id) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", step_id):
        raise Error("E_VALIDATION", "invalid result identity")
    p = safety.directory() / "creoson-results" / operation_id / (step_id + ".json")
    no_links(p)
    raw = read_bytes(p)
    if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise Error("E_INTEGRITY", "stored step result no longer matches its receipt")
    return decode(raw.decode("utf-8", "strict"))
