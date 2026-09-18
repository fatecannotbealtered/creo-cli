"""Expiring HMAC tokens, durable single-consumption, local locks and redacted audit."""
from __future__ import annotations
import base64
import getpass
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .core import Error, canonical, decode, digest

TTL = 900

def directory(create=False):
    p = Path(os.environ.get("CREO_CLI_CONFIG_DIR", str(Path.home()/".creo-cli"))).expanduser().absolute()
    if create:
        if p.is_symlink():
            raise Error("E_FORBIDDEN", "state directory must not be a symbolic link")
        try:
            p.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                p.chmod(0o700)
        except OSError as exc:
            raise Error("E_IO", "cannot initialize local state") from exc
    return p

def permission():
    p = os.environ.get("CREO_CLI_PERMISSION", "read")
    if p not in ("read", "write"):
        raise Error("E_CONFIG", "CREO_CLI_PERMISSION must be read or write")
    return p

def require_write(native=False):
    if permission() != "write":
        raise Error("E_FORBIDDEN", "local policy disables writes; a human must configure write permission")
    if native and os.environ.get("CREO_CLI_EXPERIMENTAL_NATIVE_WRITES") != "1":
        raise Error("E_FORBIDDEN", "experimental native writes require separate human opt-in; use disposable parts only")

def scope(command, backend, target, arguments, revision):
    return {"command": command, "backend": backend, "target": target, "arguments": arguments,
            "revision": revision, "account": getpass.getuser(), "permission": permission(),
            "native_opt_in": os.environ.get("CREO_CLI_EXPERIMENTAL_NATIVE_WRITES") == "1"}

def secret():
    p = directory(True)/"confirm.secret"
    if p.is_symlink():
        raise Error("E_FORBIDDEN", "secret must not be a symbolic link")
    from .core import atomic_write
    if not p.exists():
        try:
            atomic_write(p, secrets.token_bytes(32), overwrite=False)
        except Error as exc:
            if exc.code != "E_CONFLICT":
                raise
    try:
        fd = os.open(p, os.O_RDONLY|getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            raw = f.read(33)
    except OSError as exc:
        raise Error("E_IO", "cannot read confirmation secret") from exc
    if len(raw) != 32:
        raise Error("E_INTEGRITY", "confirmation secret is malformed")
    return raw

def issue(bound, now=None):
    expires = int(time.time() if now is None else now) + TTL
    body = base64.urlsafe_b64encode(canonical({"scope": digest(bound), "expires": expires,
                                             "nonce": secrets.token_hex(16)})).decode().rstrip("=")
    signature = hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()
    return "ct_" + body + "." + signature, datetime.fromtimestamp(expires, timezone.utc).isoformat().replace("+00:00", "Z")

def _database(name):
    p = directory(True)/name
    if p.is_symlink():
        raise Error("E_FORBIDDEN", "state database must not be a symbolic link")
    conn = None
    try:
        conn = sqlite3.connect(p, isolation_level=None, timeout=3)
        conn.execute("PRAGMA synchronous=FULL")
        if os.name != "nt":
            p.chmod(0o600)
        return conn
    except (OSError, sqlite3.Error) as exc:
        if conn:
            conn.close()
        raise Error("E_IO", "state database unavailable; write refused", {"write_started": False}) from exc

def consume(token, bound, now=None):
    if not token:
        raise Error("E_CONFIRMATION_REQUIRED", "run --dry-run and inspect the preview")
    key = secret()  # preserve configuration/IO errors instead of calling them conflicts
    current = time.time() if now is None else now
    try:
        if not isinstance(token, str) or not token.startswith("ct_") or len(token) > 2048:
            raise ValueError()
        body, sig = token[3:].split(".")
        expected = hmac.new(key, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise ValueError()
        payload = decode(base64.b64decode(body + "="*(-len(body)%4), altchars=b"-_", validate=True))
        expiry = payload["expires"]
        if type(expiry) is not int or not current < expiry <= current + TTL + 1 or payload["scope"] != digest(bound):
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError, Error) as exc:
        raise Error("E_CONFLICT", "token expired, malformed or bound to different state; repeat --dry-run") from exc
    conn = _database("consumed.sqlite3")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS consumed (fingerprint TEXT PRIMARY KEY, expires INTEGER NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM consumed WHERE expires <= ?", (current,))
        conn.execute("INSERT INTO consumed VALUES (?, ?)", (hashlib.sha256(token.encode()).hexdigest(), expiry))
        conn.execute("COMMIT")
    except sqlite3.IntegrityError as exc:
        raise Error("E_CONFLICT", "token already consumed; inspect state and repeat --dry-run") from exc
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot durably consume token; write refused", {"write_started": False}) from exc
    finally:
        conn.close()

@contextmanager
def lock(target):
    p = directory(True)/("lock-" + hashlib.sha256(target.encode()).hexdigest() + ".json")
    try:
        fd = os.open(p, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Error("E_CONFLICT", "another CLI operation holds the resource lock",
                    {"lock_path": str(p), "fix": "inspect owner process; never remove a live lock", "_untrusted": ["lock_path"]}) from exc
    except OSError as exc:
        raise Error("E_IO", "cannot acquire resource lock") from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(canonical({"pid": os.getpid(), "at": datetime.now(timezone.utc).isoformat()}))
        yield
    finally:
        try:
            p.unlink()
        except OSError:
            pass

def event(attempt, command, target_hash, phase, code=None):
    conn = _database("audit.sqlite3")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, attempt TEXT, at TEXT, command TEXT, target_sha256 TEXT, phase TEXT, code TEXT)")
        conn.execute("INSERT INTO events (attempt,at,command,target_sha256,phase,code) VALUES (?,?,?,?,?,?)",
                     (attempt, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), command, target_hash, phase, code))
    except sqlite3.Error as exc:
        raise Error("E_IO", "cannot persist audit event") from exc
    finally:
        conn.close()

def audited(command, target, action):
    record = (uuid.uuid4().hex, command, hashlib.sha256(target.encode()).hexdigest())
    event(*record, "started")
    try:
        result = action()
    except BaseException as exc:
        try:
            event(*record, "failed", exc.code if isinstance(exc, Error) else "E_INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "E_UNKNOWN")
        except Error:
            pass
        raise
    try:
        event(*record, "verified")
        result["audit_status"] = "recorded"
    except Error:
        result["audit_status"] = "started_only"
    return result

def history():
    p = directory()/"audit.sqlite3"
    if not p.exists():
        return []
    if p.is_symlink():
        raise Error("E_FORBIDDEN", "audit database must not be a symbolic link")
    from urllib.parse import quote
    conn = None
    try:
        conn = sqlite3.connect("file:"+quote(str(p), safe="/:")+"?mode=ro", uri=True, timeout=3)
        rows = conn.execute("SELECT id,attempt,at,command,target_sha256,phase,code FROM events ORDER BY id DESC LIMIT 10001").fetchall()
        if len(rows) > 10000:
            raise Error("E_VALIDATION", "history exceeds the 10000-event query ceiling; inspect preserved DB offline")
        keys = ("id", "attempt_id", "at", "command", "target_sha256", "phase", "error_code")
        return [dict(zip(keys, (str(row[0]), *row[1:]))) for row in rows]
    except sqlite3.Error as exc:
        raise Error("E_IO", "audit history cannot be read") from exc
    finally:
        if conn:
            conn.close()
