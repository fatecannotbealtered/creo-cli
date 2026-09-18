"""Machine contract, bounded input, projection, hashing and safe file replacement."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

CORE = {
    "E_USAGE": (2, False), "E_VALIDATION": (2, False), "E_NOT_FOUND": (3, False),
    "E_AUTH": (4, False), "E_FORBIDDEN": (4, False), "E_CONFIG": (4, False),
    "E_CONFIRMATION_REQUIRED": (5, False), "E_CONFLICT": (6, False),
    "E_NETWORK": (7, True), "E_RATE_LIMITED": (7, True), "E_SERVER": (7, True),
    "E_TIMEOUT": (8, True), "E_INTEGRITY": (1, False), "E_IO": (1, False),
    "E_INTERRUPTED": (130, True), "E_UNKNOWN": (1, False),
}
EXT = {"E_BACKEND_UNAVAILABLE": (4, False), "E_UNSUPPORTED": (2, False),
       "E_PROTOCOL": (1, False), "E_NATIVE_FAILURE": (1, False), "E_OUTCOME_UNKNOWN": (6, False), "E_VERIFY_FAILED": (1, False)}
CODES = CORE | EXT
MAX_INPUT = 8 * 1024 * 1024
SECRET_KEYS = {"password", "secret", "authorization", "cookie", "access_token", "refresh_token", "token", "api_key", "apikey", "client_secret", "private_key", "sessionid", "session_id"}

class Error(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        if code not in CODES:
            raise ValueError("undeclared error code")
        self.code, self.message, self.details = code, message, details or {}
        self.exit, self.retryable = CODES[code]
        super().__init__(message)
    def payload(self):
        return {"code": self.code, "message": self.message, "details": self.details,
                "retryable": self.retryable}

def require(condition, message):
    if not condition:
        raise Error("E_VALIDATION", message)

def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False

def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")

def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def decode(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise ValueError("duplicate key")
            d[k] = v
        return d
    def real(s):
        n = float(s)
        if not math.isfinite(n):
            raise ValueError("nonfinite")
        return n
    def invalid(_):
        raise ValueError("nonfinite")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=real,
                          parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Error("E_VALIDATION", "expected strict UTF-8 JSON; duplicate keys and non-finite numbers are forbidden") from exc

def read_bytes(path, maximum=MAX_INPUT):
    p = Path(path).expanduser()
    try:
        if not p.is_file():
            if not p.exists():
                raise FileNotFoundError()
            raise Error("E_VALIDATION", "input must be a regular file")
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as f:
            import stat
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Error("E_VALIDATION", "input must be a regular file")
            raw = f.read(maximum + 1)
    except FileNotFoundError as exc:
        raise Error("E_NOT_FOUND", "input file not found", {"path": str(p), "_untrusted": ["path"]}) from exc
    except OSError as exc:
        raise Error("E_IO", "input file cannot be read", {"path": str(p), "_untrusted": ["path"]}) from exc
    require(len(raw) <= maximum, "input exceeds the 8 MiB ceiling")
    return raw

def read_json(path):
    return decode(read_bytes(path))

def atomic_write(path: Path, raw: bytes, overwrite=True):
    """Stage beside target, fsync, replace. New files use atomic no-clobber hard-link.

    Does not create parents. A post-rename IO error can mean committed state.
    Cooperative locks protect CLI callers, not arbitrary external writers.
    """
    if path.is_symlink():
        raise Error("E_FORBIDDEN", "refusing a symbolic-link output")
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)
            os.unlink(tmp)
        tmp = None
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except FileExistsError as exc:
        raise Error("E_CONFLICT", "destination exists; nothing was overwritten") from exc
    except OSError as exc:
        raise Error("E_IO", "atomic write failed; inspect target before retrying", {"state_unknown": True}) from exc
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass

def page(items, limit=100, offset=0):
    result = {"items": items[offset:offset+limit], "count": len(items[offset:offset+limit]),
              "total": len(items), "offset": offset, "has_more": offset+limit < len(items),
              "_untrusted": ["items"]}
    if result["has_more"]:
        result["next_offset"] = offset + result["count"]
    return result

def redact(value):
    if isinstance(value, list):
        return [redact(x) for x in value]
    if not isinstance(value, dict):
        return value
    d = dict(value)
    if str(d.get("name", "")).lower() in SECRET_KEYS and "value" in d:
        d["value"] = "[REDACTED]"
    if str(d.get("target", "")).lower() in SECRET_KEYS:
        for k in ("before", "after"):
            if k in d:
                d[k] = "[REDACTED]"
    return {k: "[REDACTED]" if str(k).lower() in SECRET_KEYS else redact(v) for k, v in d.items()}

def project(data, fields):
    if fields is None:
        return data
    tree = {}
    for path in fields.split(","):
        if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", path):
            raise Error("E_USAGE", "--fields expects nonempty comma-separated dotted paths")
        node = tree
        for bit in path.split("."):
            node = node.setdefault(bit, {})
        node[""] = True
    def pick(obj, selector):
        if "" in selector:
            return obj
        if isinstance(obj, list):
            return [pick(row, selector) for row in obj]
        if not isinstance(obj, dict) or set(selector) - set(obj):
            raise Error("E_USAGE", "field projection refers to an absent field or crosses a scalar")
        out = {k: pick(obj[k], sub) for k, sub in selector.items()}
        for k in ("_untrusted", "provenance", "not_checked", "count", "total", "offset", "next_offset", "has_more", "truncated"):
            if k in obj:
                out.setdefault(k, obj[k])
        return out
    return pick(data, tree)

def validate_schema(value, schema, path="data"):
    """Small deliberately bounded subset of JSON Schema used by the registry."""
    if not schema:
        return
    kinds = {"object": dict, "array": list, "string": str, "integer": int,
             "boolean": bool, "null": type(None)}
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(number(value) if t == "number" else type(value) is kinds[t] for t in types):
        raise Error("E_INTEGRITY", "output type does not match its schema", {"path": path})
    if "enum" in schema and value not in schema["enum"]:
        raise Error("E_INTEGRITY", "output enum does not match its schema", {"path": path})
    if isinstance(value, dict):
        if set(schema.get("required", [])) - set(value):
            raise Error("E_INTEGRITY", "output lacks required schema fields", {"path": path})
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                validate_schema(value[k], sub, path + "." + k)
    if isinstance(value, list) and "items" in schema:
        for row in value:
            validate_schema(row, schema["items"], path + "[]")
