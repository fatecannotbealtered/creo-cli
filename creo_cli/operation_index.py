"""Disposable, authenticated summaries of strictly validated history rows.

Every scan still reads and hashes every exact original row. The cache never stores
CAD observations, never rewrites history, and cannot certify a native call's end.
"""

import hashlib
import hmac
import sqlite3
from contextlib import closing

from . import safety
from .core import Error, canonical, decode
from .paths import no_links

NAME = "operation-summary-index.sqlite3"
KEYS = {"operation_id", "command", "status", "started_at", "scope_id"}


def signature(key, fingerprint, summary):
    return hmac.new(
        key, b"creo-history-summary-v1\0" + fingerprint + canonical(summary), hashlib.sha256
    ).hexdigest()


def scan(*, write_cache=False):
    from . import operations

    source = safety.directory() / operations.DATABASE
    if not source.exists():
        return []
    no_links(source)
    cache_path = safety.directory() / NAME
    no_links(cache_path)
    key = (
        safety.secret() if write_cache or (safety.directory() / "confirm.secret").exists() else None
    )
    cache = None
    try:
        if write_cache:
            cache = safety.database(NAME)
            cache.execute(
                "CREATE TABLE IF NOT EXISTS summaries (id TEXT PRIMARY KEY, "
                "fingerprint BLOB NOT NULL, body TEXT NOT NULL, signature TEXT NOT NULL)"
            )
            cache.execute("BEGIN IMMEDIATE")
        elif cache_path.exists() and key is not None:
            cache = sqlite3.connect(cache_path.as_uri() + "?mode=ro", uri=True, timeout=3)
        cached = (
            {
                row[0]: row[1:]
                for row in cache.execute(
                    "SELECT id,fingerprint,body,signature FROM summaries "
                    "WHERE length(body)<=8192 LIMIT 5000"
                )
            }
            if cache is not None
            else {}
        )
        result = []
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=3)) as db:
            cursor = db.execute(
                "SELECT id,command,status,body FROM operations ORDER BY rowid DESC LIMIT 5001"
            )
            for ident, command, status, body in cursor:
                if len(result) >= 5000:
                    raise Error(
                        "E_VALIDATION",
                        "more than 5000 receipts; archive the database after inspection",
                    )
                raw = body.encode("utf-8") if isinstance(body, str) else body
                fingerprint = hashlib.sha256(raw).digest()
                prior = cached.get(ident)
                summary = None
                if prior is not None and prior[0] == fingerprint and key is not None:
                    try:
                        candidate = decode(prior[1])
                        if (
                            isinstance(candidate, dict)
                            and candidate.keys() == KEYS
                            and candidate["operation_id"] == ident
                            and candidate["command"] == command
                            and candidate["status"] == status
                            and status in operations.STATUSES
                            and hmac.compare_digest(
                                prior[2], signature(key, fingerprint, candidate)
                            )
                        ):
                            summary = candidate
                    except (Error, TypeError, ValueError):
                        pass  # A cache miss is rebuilt from strict original-row validation.
                if summary is None:
                    run = operations._decode_record(body)
                    if (
                        not operations.OPERATION_ID.fullmatch(str(ident))
                        or run.get("operation_id") != ident
                        or run.get("command") != command
                        or run.get("status") != status
                        or status not in operations.STATUSES
                    ):
                        raise Error("E_INTEGRITY", "a receipt is corrupt; writes stay blocked")
                    plan = run.get("driver_plan") or {}
                    if not isinstance(plan, dict):
                        raise Error("E_INTEGRITY", "a receipt plan is corrupt; writes stay blocked")
                    summary = {
                        "operation_id": ident,
                        "command": command,
                        "status": status,
                        "started_at": run.get("started_at"),
                        "scope_id": plan.get("authorization_scope_id"),
                    }
                    if cache is not None and write_cache:
                        cache.execute(
                            "INSERT OR REPLACE INTO summaries VALUES (?,?,?,?)",
                            (
                                ident,
                                fingerprint,
                                canonical(summary).decode(),
                                signature(key, fingerprint, summary),
                            ),
                        )
                result.append(summary)
        if cache is not None and write_cache:
            cache.commit()
        return result
    except (sqlite3.Error, OSError, TypeError) as exc:
        raise Error(
            "E_IO", "cannot validate operation history summaries; no history was discarded"
        ) from exc
    finally:
        if cache is not None:
            cache.close()
