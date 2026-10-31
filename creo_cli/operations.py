"""Durable write receipts and separate observations, never proof that a native read ended.

Unresolved public receipts block conflicting targets and dependencies; legacy writes
retain the global gate. Local history survives a CLI crash but cannot establish the
state of an unrecorded native call or make a new CAD inspection safe.
"""

from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import uuid
import zlib
from contextlib import closing
from datetime import UTC, datetime

from . import native_diagnostic_recovery, native_read_recovery, process_owner, safety, timing
from .core import MAX_INPUT, Error, atomic_write, canonical, decode, digest, read_bytes, redact
from .paths import no_links

DATABASE = "operations.sqlite3"
RESULTS = "operation-results"
MAX_RECORD_BYTES = 4 * 1024 * 1024
# Reuse the existing bounded JSON/result decoding capacity, not a larger model profile.
MAX_LOGICAL_RECORD_BYTES = MAX_INPUT
_RECORD_MARKER = "_creo_cli_operation_record"
_RECORD_KEYS = {_RECORD_MARKER, "version", "codec", "logical_bytes", "sha256", "payload"}
# unknown: the write was sent and what it did cannot be established.
# partial: Creo rejected it and the target was read back changed.
# verification_failed: Creo reported it done and a postcondition read back afterwards failed.
UNRESOLVED = ("running", "unknown", "partial", "verification_failed", "verification_incomplete")
# stopped: a workflow that ran some of its steps and stopped at a failure; each step's own
# receipt says what that step did, and blocks if it must.
STATUSES = UNRESOLVED + (
    "planned",
    "completed",
    "failed_before_write",
    "failed_unchanged",
    "acknowledged",
    "resolved_manual",
    "stopped",
)
OPERATION_ID = re.compile(r"[a-f0-9]{32}")


def _encode_record(run: dict) -> bytes:
    """Keep small rows unchanged; losslessly encode only a bounded oversized full run."""
    raw = canonical(redact(run))
    if len(raw) <= MAX_RECORD_BYTES:
        return raw
    if len(raw) > MAX_LOGICAL_RECORD_BYTES:
        raise Error("E_IO", "receipt exceeds the existing 8 MiB logical JSON bound")
    try:
        physical = canonical(
            {
                _RECORD_MARKER: "creo-cli",
                "version": 1,
                "codec": "zlib+base64",
                "logical_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "payload": base64.b64encode(zlib.compress(raw)).decode("ascii"),
            }
        )
    except zlib.error as exc:
        raise Error("E_IO", "cannot encode the bounded completion receipt") from exc
    if len(physical) > MAX_RECORD_BYTES:
        raise Error("E_IO", "encoded receipt exceeds the unchanged 4 MiB physical row bound")
    return physical


def _decode_record(body) -> dict:
    """Decode this project's root storage envelope only, with no nested reference semantics."""
    try:
        raw = body.encode("utf-8") if isinstance(body, str) else body
        if not isinstance(raw, bytes) or len(raw) > MAX_RECORD_BYTES:
            raise ValueError("physical row size")
        value = decode(raw)
        if isinstance(value, dict) and _RECORD_MARKER in value:
            if (
                set(value) != _RECORD_KEYS
                or value[_RECORD_MARKER] != "creo-cli"
                or type(value["version"]) is not int
                or value["version"] != 1
                or value["codec"] != "zlib+base64"
                or type(value["logical_bytes"]) is not int
                or not 0 < value["logical_bytes"] <= MAX_LOGICAL_RECORD_BYTES
                or not isinstance(value["sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["sha256"])
                or not isinstance(value["payload"], str)
            ):
                raise ValueError("unsupported or invalid root storage envelope")
            packed = base64.b64decode(value["payload"].encode("ascii"), validate=True)
            inflater = zlib.decompressobj()
            logical = inflater.decompress(packed, MAX_LOGICAL_RECORD_BYTES + 1)
            if (
                len(logical) > MAX_LOGICAL_RECORD_BYTES
                or inflater.unconsumed_tail
                or not inflater.eof
                or inflater.unused_data
                or len(logical) != value["logical_bytes"]
                or hashlib.sha256(logical).hexdigest() != value["sha256"]
            ):
                raise ValueError("bounded receipt length/hash/stream mismatch")
            value = decode(logical)
            if isinstance(value, dict) and _RECORD_MARKER in value:
                raise ValueError("nested root encoding")
        if not isinstance(value, dict):
            raise ValueError("operation record must be an object")
        return value
    except (
        Error,
        ValueError,
        TypeError,
        UnicodeError,
        RecursionError,
        OverflowError,
        zlib.error,
    ) as exc:
        raise Error("E_INTEGRITY", "a receipt is corrupt; writes stay blocked") from exc


def _db():
    db = None
    try:
        db = safety.database(DATABASE)
        db.execute(
            "CREATE TABLE IF NOT EXISTS operations "
            "(id TEXT PRIMARY KEY, command TEXT NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL)"
        )
        return db
    except (sqlite3.Error, OSError) as exc:
        if db is not None:
            try:
                db.close()
            except (sqlite3.Error, OSError):
                pass
        raise Error("E_IO", "cannot initialize local operation history") from exc


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def begin(
    command: str, target: str, request: dict, endpoint: str, planned: dict | None = None
) -> dict:
    if planned is not None:
        run = get(planned["operation_id"])
        if run["status"] != "planned":
            raise Error(
                "E_CONFLICT",
                "operation was already dispatched",
                {"conflict": "token_used", "operation_id": run["operation_id"]},
            )
        run.update(status="running", started_at=now(), driver_owner=process_owner.lease())
        update(run)
        return run
    run = {
        "operation_id": uuid.uuid4().hex,
        "at": now(),
        "command": command,
        "target": target,
        "status": "running",
        "request_sha256": digest(request),
        "endpoint": endpoint,
        "result": None,
        "rollback_performed": False,
    }
    db = _db()
    try:
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?)",
            (run["operation_id"], command, run["status"], canonical(run).decode()),
        )
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot record the write before sending it; nothing was sent") from exc
    finally:
        db.close()
    return run


@timing.phase("record_write")
def record_plan(
    command: str, target: str, request: dict, endpoint: str, plan: dict, bound: dict
) -> dict:
    run = {
        "operation_id": plan["operation_id"],
        "at": now(),
        "command": command,
        "target": target,
        "status": "planned",
        "request_sha256": digest(request),
        "endpoint": endpoint,
        "result": None,
        "rollback_performed": False,
        "driver_plan": plan,
        "driver_binding": bound,
        "started_at": None,
        "finished_at": None,
        "driver_receipt": None,
    }
    if len(canonical(redact(run))) > MAX_RECORD_BYTES:
        raise Error("E_IO", "planned record exceeds size limit; nothing was dispatched")
    db = _db()
    try:
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?)",
            (run["operation_id"], command, "planned", canonical(run).decode()),
        )
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot retain the planned operation; nothing was dispatched") from exc
    finally:
        db.close()
    return run


@timing.phase("record_write")
def update(run: dict) -> None:
    if (
        run.get("driver_plan")
        and run["status"] == "completed"
        and run.get("driver_receipt") is None
    ):
        raise Error(
            "E_IO", "completed driver record requires its public receipt in the same commit"
        )
    raw = _encode_record(run)
    db = _db()
    try:
        changed = db.execute(
            "UPDATE operations SET status=?,body=? WHERE id=?",
            (run["status"], raw.decode(), run["operation_id"]),
        )
        if changed.rowcount != 1:
            raise Error("E_IO", "operation record disappeared; no completion can be committed")
    except sqlite3.Error as exc:
        raise Error(
            "E_IO",
            "cannot update the receipt; the write may have completed",
            {"state_unknown": True},
        ) from exc
    finally:
        db.close()


def checkpoint_domain(run: dict) -> None:
    """Keep modern records unresolved until public receipt and terminal state commit together."""
    if run.get("driver_plan"):
        update(
            run
            | {"status": "running", "driver_stage": "finalizing", "domain_status": run["status"]}
        )
    else:
        update(run)


@timing.phase("history_read")
def all_runs() -> list[dict]:
    p = safety.directory() / DATABASE
    if not p.exists():
        return []
    no_links(p)
    db = None
    try:
        db = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=3)
        rows = db.execute(
            "SELECT id,command,status,body FROM operations ORDER BY rowid DESC LIMIT 5001"
        ).fetchall()
    except sqlite3.Error as exc:
        raise Error(
            "E_IO", "cannot read receipts; refusing to assume earlier writes completed"
        ) from exc
    finally:
        if db:
            db.close()
    if len(rows) > 5000:
        raise Error(
            "E_VALIDATION", "more than 5000 receipts; archive the database after inspection"
        )
    runs = []
    for ident, command, status, body in rows:
        try:
            run = _decode_record(body)
        except Error as exc:
            raise Error("E_INTEGRITY", "a receipt is corrupt; writes stay blocked") from exc
        if (
            not isinstance(run, dict)
            or not OPERATION_ID.fullmatch(str(run.get("operation_id", "")))
            or run.get("status") not in STATUSES
            or run.get("operation_id") != ident
            or run.get("command") != command
            or run.get("status") != status
        ):
            raise Error("E_INTEGRITY", "a receipt is corrupt; writes stay blocked")
        runs.append(run)
    return runs


def get(operation_id: str) -> dict:
    if not OPERATION_ID.fullmatch(operation_id):
        raise Error("E_VALIDATION", "an operation id is 32 hexadecimal characters", {"path": "id"})
    p = safety.directory() / DATABASE
    if not p.exists():
        raise Error("E_NOT_FOUND", "no receipt with that operation id")
    no_links(p)
    try:
        with closing(sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            row = db.execute(
                "SELECT id,command,status,body FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot read the requested receipt") from exc
    if row is None:
        raise Error("E_NOT_FOUND", "no receipt with that operation id")
    ident, command, status, body = row
    run = _decode_record(body)
    if (
        run.get("operation_id") != ident
        or run.get("command") != command
        or run.get("status") != status
        or status not in STATUSES
    ):
        raise Error("E_INTEGRITY", "a receipt is corrupt; writes stay blocked")
    return run


@timing.phase("history_read")
def summaries(*, write_cache=False):
    from . import operation_index

    return operation_index.scan(write_cache=write_cache)


def selected_runs(*, statuses=None, commands=None, write_cache=False):
    return [
        get(row["operation_id"])
        for row in summaries(write_cache=write_cache)
        if (statuses is None or row["status"] in statuses)
        and (commands is None or row["command"] in commands)
    ]


@timing.phase("record_write")
def record_confirmation_rejection(
    run: dict, error: Error, actual_binding: dict | None = None
) -> dict:
    """Append one pre-dispatch refusal without rewriting the original plan or write.

    A plan can have several refused attempts and still remains a historical plan.
    In particular, no absence of dispatch in this attempt settles an older unknown
    native call. This function must only be called before engine execution begins.
    """
    operation_id = run["operation_id"]
    if not OPERATION_ID.fullmatch(operation_id):
        raise Error("E_VALIDATION", "confirmation attempt needs a retained operation id")
    attempt = {
        "attempt_id": uuid.uuid4().hex,
        "operation_id": operation_id,
        "at": now(),
        "finished_at": now(),
        "status": "rejected_before_dispatch",
        "terminal": True,
        "dispatch_state": "not_started",
        "write_started": False,
        "original_operation_status": run["status"],
        "actual_binding_sha256": digest(actual_binding) if actual_binding is not None else None,
        "actual_binding_available": actual_binding is not None,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
        "original_record_unchanged": True,
        "automatic_retry": False,
    }
    # The error is already secret-safe when emitted by safety. Redact again before
    # storage, including any credential-shaped value an earlier guard supplied.
    from . import binding_diagnostics

    safe_error = binding_diagnostics.sanitize(attempt["error"])
    attempt["error"] = safe_error
    raw = canonical(redact(attempt))
    if len(raw) > MAX_RECORD_BYTES:
        raise Error("E_IO", "confirmation attempt exceeds size limit; no write was dispatched")
    db = _db()
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS confirmation_attempts "
            "(id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, body TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO confirmation_attempts VALUES (?,?,?)",
            (attempt["attempt_id"], operation_id, raw.decode()),
        )
    except sqlite3.Error as exc:
        raise Error(
            "E_IO", "cannot retain rejected confirmation attempt; no write was dispatched"
        ) from exc
    finally:
        db.close()
    return attempt


def confirmation_attempts(operation_id: str) -> list[dict]:
    """Read local attempt history only; never query CAD or rewrite original receipts."""
    if not OPERATION_ID.fullmatch(operation_id):
        raise Error("E_VALIDATION", "an operation id is 32 hexadecimal characters", {"path": "id"})
    p = safety.directory() / DATABASE
    if not p.exists():
        return []
    no_links(p)
    db = None
    try:
        db = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=3)
        exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='confirmation_attempts'"
        ).fetchone()
        if not exists:
            return []
        rows = db.execute(
            "SELECT id,body FROM confirmation_attempts WHERE operation_id=? ORDER BY rowid",
            (operation_id,),
        ).fetchall()
        attempts = []
        for ident, body in rows:
            attempt = decode(body)
            if (
                not isinstance(attempt, dict)
                or not OPERATION_ID.fullmatch(str(ident))
                or attempt.get("attempt_id") != ident
                or attempt.get("operation_id") != operation_id
                or attempt.get("status") != "rejected_before_dispatch"
                or attempt.get("terminal") is not True
                or attempt.get("dispatch_state") != "not_started"
            ):
                raise Error("E_INTEGRITY", "local confirmation attempt history is corrupt")
            attempts.append(attempt)
        return attempts
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot read local confirmation attempt history") from exc
    finally:
        if db:
            db.close()


def require_clear(ignore: str | None = None) -> None:
    """Refuse while an earlier write is unresolved -- except `ignore`, the workflow that is
    itself running the next step."""
    blocked = [
        r["operation_id"]
        for r in selected_runs(statuses=UNRESOLVED, write_cache=True)
        if r["status"] in UNRESOLVED and r["operation_id"] != ignore
    ]
    if blocked:
        raise Error(
            "E_CONFLICT",
            "an earlier write is unresolved; inspect Creo, then record manual resolution",
            {
                "operation_ids": blocked,
                "automatic_retry": False,
                "fix": (
                    "creo-cli operation show --id <operation_id>; follow recovery_guidance "
                    "for the retained lifecycle and target. Inspect independent evidence before "
                    "registration; never replay or infer non-application from absence."
                ),
            },
        )


RECOVERY_CONTRACT = {
    "migrated_guard": "unresolved operations block conflicting objects and recursive dependencies; "
    "file directory targets include ancestors and descendants, not unrelated siblings",
    "legacy_guard": "legacy writes use a global unresolved-operation gate; an unresolved legacy "
    "record without a reliable footprint also blocks migrated writes conservatively",
    "untargeted_diagnostics": "no target was requested; only an actual target preview can assess "
    "dependency conflicts, scope, inputs and native prerequisites",
    "local_history": "operation show reads retained records only; missing native-read evidence "
    "does not prove that an earlier getter ended or that this instance is ready for CAD",
    "CAD_precondition": "if a native read is known or may still be pending, stop CAD dispatch "
    "and independently confirm the original call has ended and the original instance state "
    "before query, resolve inspection or any engineering read-back; local history, "
    "process-only health and a new CLI process cannot establish this",
    "query": {
        "installation": "omit --model; retained target requires current observe roots "
        "and selectors; "
        "no CAD or write permission required",
        "CAD": "supply the receipt's explicit --model, including material assignments; a material "
        "source file does not make its operation a file-targeted installation",
        "historical": "missing ownership or independent evidence remains unknown; current absence "
        "does not establish that a historical operation was not applied",
    },
    "registration": "observation, saved state, verification and receipt completion are separate; "
    "registration preserves the original receipt and never replays writes; CAD query and "
    "some resolve previews/confirmations issue fresh native getters, so they are conditional "
    "inspection entry points, not a way to settle a pending getter",
}


def recovery_guidance(run):
    """Describe the existing public recovery entry points without observing a target."""
    ident = run["operation_id"]
    public = bool(run.get("driver_plan"))
    diagnostic = native_diagnostic_recovery.diagnostic_error(run)
    if diagnostic:
        return {
            "lifecycle": "public" if public else "legacy",
            "show": ["operation", "show", "--id", ident],
            "query": None,
            "resolve_preview": None,
            "native_diagnostic_error": diagnostic,
            "constraint": native_diagnostic_recovery.STOP_ACTION,
            "local_history": RECOVERY_CONTRACT["local_history"],
        }
    pending = native_read_recovery.pending_error(run)
    if pending:
        return {
            "lifecycle": "public" if public else "legacy",
            "show": ["operation", "show", "--id", ident],
            "query": None,
            "resolve_preview": None,
            "native_read_error": pending,
            "constraint": native_read_recovery.STOP_ACTION,
            "cad_readback_precondition": (
                "independent confirmation that the original call ended and of this instance "
                "state before query, resolve inspection or engineering read-back; "
                "neither local records, process-only health, OS presence nor a new CLI "
                "process proves native completion"
            ),
            "local_history": RECOVERY_CONTRACT["local_history"],
            "guard_scope": "single Client only; this retained warning is not a cross-process lock",
        }
    query = ["operation", "query", "--id", ident]
    if run["command"] != "service install":
        target = str(run.get("target", ""))
        query = (
            query + ["--model", target]
            if target.lower().endswith((".prt", ".asm", ".drw"))
            else None
        )
    guidance = {
        "lifecycle": "public" if public else "legacy",
        "show": ["operation", "show", "--id", ident],
        "query": query,
        "resolve_preview": ["operation", "resolve", "--id", ident]
        + (
            [
                "--outcome",
                "<applied|not_applied|partial>",
                "--evidence",
                "<independent evidence text>",
            ]
            if public
            else [
                "--decision",
                "accept-observation",
                "--evidence",
                "<query evidence_id>",
                "--note",
                "<inspection and accepted consequences>",
            ]
        )
        + ["--dry-run"],
        "constraint": "only register an independently supported outcome after the owner stopped; "
        "retain unknown when evidence is insufficient. Confirm the resulting preview explicitly; "
        "no automatic retry, rollback or continuation",
    }
    guidance["local_history"] = RECOVERY_CONTRACT["local_history"]
    if run["command"] in ("model export", "artifact export") and run.get("driver_plan"):
        guidance["cad_readback_precondition"] = RECOVERY_CONTRACT["CAD_precondition"]
        guidance["inspection_dispatch"] = (
            "export query requires the original --model selector and current observe scope, "
            "but reads only retained exact file paths; it never calls CAD, publishes or "
            "replays an export. Missing ownership remains incomplete. File observations "
            "do not prove a pending native call ended. Independently settle that call and "
            "instance state before any CAD read or resolve."
        )
    elif run["command"] != "service install":
        guidance["cad_readback_precondition"] = RECOVERY_CONTRACT["CAD_precondition"]
        guidance["inspection_dispatch"] = (
            "query and command-specific resolve previews/confirmations can issue fresh CAD "
            "getters; the listed commands are conditional inspection entry points. If an "
            "earlier read may still be pending, independently settle the original call and "
            "instance state first; an unknown write alone does not establish a pending read"
        )
    return guidance


def recovery_diagnostics():
    rows = [r for r in selected_runs(statuses=UNRESOLVED) if not r.get("driver_resolution")]
    scoped = []
    legacy = []
    for run in rows:
        plan = run.get("driver_plan")
        item = {
            "operation_id": run["operation_id"],
            "stored_status": run["status"],
            "target": plan["target"] if plan else run.get("target"),
            "guidance": recovery_guidance(run),
        }
        (scoped if plan else legacy).append(item)
    return {
        "target_assessment": "not_requested",
        "scoped_unresolved": scoped,
        "legacy_unscoped": legacy,
        "legacy_writes_blocked": bool(rows),
        "contract": RECOVERY_CONTRACT,
    }


@timing.phase("record_write")
def save_result(operation_id: str, result: dict) -> dict:
    root = safety.directory(True) / RESULTS
    no_links(root)
    root.mkdir(exist_ok=True, mode=0o700)
    raw = canonical(redact(result)) + b"\n"
    if len(raw) > 8 * 1024 * 1024:
        raise Error("E_IO", "result exceeds 8 MiB; the write itself may have completed")
    atomic_write(root / (operation_id + ".json"), raw, overwrite=False)
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def load_result(run: dict) -> dict | None:
    stored = run.get("result")
    if not stored:
        return None
    p = safety.directory() / RESULTS / (run["operation_id"] + ".json")
    no_links(p)
    raw = read_bytes(p)
    if hashlib.sha256(raw).hexdigest() != stored["sha256"]:
        raise Error("E_INTEGRITY", "the stored result no longer matches its receipt")
    return decode(raw.decode("utf-8", "strict"))


def save_query(run: dict, observation: dict) -> dict:
    query_id = uuid.uuid4().hex
    body = {
        "query_id": query_id,
        "operation_id": run["operation_id"],
        "at": now(),
        "receipt_sha256": digest(run),
        "observation": observation,
        "proves_original_write_postconditions": False,
    }
    root = safety.directory(True) / "operation-queries"
    no_links(root)
    root.mkdir(exist_ok=True, mode=0o700)
    raw = canonical(redact(body)) + b"\n"
    if len(raw) > 8 * 1024 * 1024:
        raise Error("E_IO", "query observation exceeds8MiB")
    sha = hashlib.sha256(raw).hexdigest()
    # The content digest is part of the id, so a later resolve checks immutable bytes.
    ident = query_id + "-" + sha
    atomic_write(root / (ident + ".json"), raw, overwrite=False)
    return body | {"evidence_id": ident, "sha256": sha}


def retain_pending_inspection(run: dict, exc: Error, source: str) -> None:
    """Keep failed read evidence separately; never rewrite the original write receipt."""
    pending = native_read_recovery.pending_error(exc)
    diagnostic = native_diagnostic_recovery.diagnostic_error(exc)
    if not (pending or diagnostic):
        return
    exc.details.update(native_read_recovery.details(pending))
    exc.details.update(native_diagnostic_recovery.details(diagnostic))
    exc.details["parent_operation_id"] = run["operation_id"]
    try:
        evidence = save_query(
            run,
            {
                "source": source,
                "read_status": "diagnostic_stopped" if diagnostic else "pending",
                "complete": False,
                **(
                    {"native_diagnostic_error": diagnostic}
                    if diagnostic
                    else {"native_read_error": pending}
                ),
                "coverage": (
                    "failed native inspection; no complete target or postcondition evidence"
                ),
            },
        )
        exc.details["read_failure_evidence_id"] = evidence["evidence_id"]
    except (Error, OSError) as recording:
        # Directory preparation can fail before atomic_write has converted a
        # filesystem error to Error. Retention is secondary to the pending read:
        # never let it replace the original CAD state or trigger another getter.
        if isinstance(recording, Error):
            storage_error = native_read_recovery.error_record(recording)
        else:
            storage_details = {"exception_type": type(recording).__name__}
            for key in ("errno", "winerror"):
                value = getattr(recording, key, None)
                if value is not None:
                    storage_details[key] = value
            storage_error = native_read_recovery.error_record(
                Error("E_IO", "cannot retain failed native inspection evidence", storage_details)
            )
        exc.details.update(
            read_failure_evidence_retained=False,
            read_failure_evidence_note=(
                "failed inspection evidence retention was not acknowledged; no evidence ID is "
                "available; storage_error may report an unknown storage state. The original "
                + (
                    "native stop remains unresolved and the original write receipt is unchanged"
                    if diagnostic
                    else "read remains pending and the original write receipt is unchanged"
                )
            ),
            record_error=storage_error["code"],
            storage_error=storage_error,
        )


def load_query(ident: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}-[a-f0-9]{64}", ident):
        raise Error("E_VALIDATION", "query evidence id must be the id returned by operation query")
    p = safety.directory() / "operation-queries" / (ident + ".json")
    no_links(p)
    raw = read_bytes(p)
    if hashlib.sha256(raw).hexdigest() != ident.split("-")[1]:
        raise Error("E_INTEGRITY", "query evidence content was changed")
    return decode(raw.decode("utf-8", "strict"))
