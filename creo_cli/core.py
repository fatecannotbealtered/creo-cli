"""Machine contract, bounded input, projection, hashing and safe file replacement."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from .contract_gen import CODES as CONTRACT

# Generated from the fleet's contract.json plus contract/contract-ext.json; never edited here.
CODES = {name: (spec["exit"], spec["retryable"]) for name, spec in CONTRACT.items()}
MAX_INPUT = 8 * 1024 * 1024
SECRET_KEYS = {
    "password",
    "secret",
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "sessionid",
    "session_id",
}


class Error(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        if code not in CODES:
            raise ValueError("undeclared error code")
        self.code, self.message, self.details = code, message, details or {}
        self.exit, self.retryable = CODES[code]
        super().__init__(message)

    def payload(self):
        details = dict(self.details)
        details.setdefault(
            "dispatch_state", "unknown" if details.get("operation_id") else "not_started"
        )
        details.setdefault(
            "next_action",
            details.get("fix")
            or (
                "query the operation and read the target independently; do not repeat the write"
                if details["dispatch_state"] != "not_started"
                else "inspect the command reference and correct the stated prerequisite"
            ),
        )
        if self.code in ("E_USAGE", "E_VALIDATION", "E_CONFIRMATION_REQUIRED"):
            details.setdefault(
                "problem",
                "confirmation_required"
                if self.code == "E_CONFIRMATION_REQUIRED"
                else "invalid_value",
            )
            if details.get("path"):
                details.setdefault("parameter", details["path"])
                details.setdefault("expected", "the parameter's declared schema")
        if self.code == "E_CONFLICT":
            conflicts = {
                "expired": "token_expired",
                "already_used": "token_used",
                "arguments_changed": "token_mismatch",
                "malformed": "token_mismatch",
                "state_changed": "state_drift",
                "policy_changed": "scope_changed",
                "scope_changed": "scope_changed",
            }
            details.setdefault("conflict", conflicts.get(details.get("reason"), "state_drift"))
        if self.code == "E_OUTCOME_UNKNOWN" and details.get("operation_id"):
            details.setdefault("lookup", ["operation", "show", "--id", details["operation_id"]])
        return {
            "code": self.code,
            "message": self.message,
            "details": details,
            "retryable": self.retryable,
        }


def require(condition, message):
    if not condition:
        raise Error("E_VALIDATION", message)


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def canonical(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


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
        return json.loads(raw, object_pairs_hook=pairs, parse_float=real, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Error(
            "E_VALIDATION",
            "expected strict UTF-8 JSON; duplicate keys and non-finite numbers are forbidden",
        ) from exc


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
        raise Error(
            "E_NOT_FOUND", "input file not found", {"path": str(p), "_untrusted": ["path"]}
        ) from exc
    except OSError as exc:
        raise Error(
            "E_IO", "input file cannot be read", {"path": str(p), "_untrusted": ["path"]}
        ) from exc
    require(len(raw) <= maximum, "input exceeds the 8 MiB ceiling")
    return raw


def read_json(path):
    return decode(read_bytes(path))


def request_path(value: str) -> Path:
    """A request file: an absolute path, or a relative one from the current directory or,
    failing that, from the workspace root -- where an agent keeps its requests."""
    p = Path(value).expanduser()
    if p.drive and not p.is_absolute():
        raise Error("E_VALIDATION", "a request path with a drive must be absolute")
    if p.is_absolute():
        return p
    tried = [Path.cwd() / p]
    root = os.environ.get("CREO_CLI_WORKSPACE")
    if root:
        tried.append(Path(root).expanduser().absolute() / p)
    for candidate in tried:
        if candidate.exists():
            return candidate
    raise Error(
        "E_NOT_FOUND",
        "request file not found",
        {"path": value, "tried": [str(t) for t in tried], "_untrusted": ["path", "tried"]},
    )


def read_request(value):
    """A request file, or JSON on stdin when the value is '-'; strict and bounded either way.
    A workflow step may carry its request inline, already decoded as strictly."""
    if isinstance(value, dict):
        return decode(canonical(value).decode("utf-8"))
    if value != "-":
        return read_json(request_path(value))
    import sys

    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    require(len(raw) <= MAX_INPUT, "request on stdin exceeds the 8 MiB ceiling")
    try:
        return decode(raw.decode("utf-8", "strict"))
    except UnicodeError as exc:
        raise Error("E_VALIDATION", "request on stdin is not UTF-8") from exc


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
        raise Error(
            "E_IO", "atomic write failed; inspect target before retrying", {"state_unknown": True}
        ) from exc
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def page(items, limit=100, offset=0):
    result = {
        "items": items[offset : offset + limit],
        "count": len(items[offset : offset + limit]),
        "total": len(items),
        "offset": offset,
        "has_more": offset + limit < len(items),
        "_untrusted": ["items"],
    }
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
        if isinstance(data, dict) and "items" in data and path.split(".")[0] not in data:
            path = "items." + path  # on a list, item fields need no prefix
        node = tree
        for bit in path.split("."):
            node = node.setdefault(bit, {})
        node[""] = True

    # The rows of a list need not all have the same fields -- a feature's kind decides what it
    # reports -- so a field some rows lack is left out of those; a field none has is a mistake.
    found, missed = set(), {}

    def pick(obj, selector, at):
        if "" in selector:
            return obj
        if isinstance(obj, list):
            return [pick(row, selector, at) for row in obj]
        if obj is None:
            return None
        if not isinstance(obj, dict):
            for k in selector:
                missed.setdefault(at + "." + k, at)
            return obj
        out = {}
        for k, sub in selector.items():
            path = at + "." + k if at else k
            if k in obj:
                found.add(path)
                out[k] = pick(obj[k], sub, path)
            else:
                missed.setdefault(path, sorted(obj))
        for k in (
            "_untrusted",
            "provenance",
            "not_checked",
            "count",
            "total",
            "offset",
            "next_offset",
            "has_more",
            "truncated",
        ):
            if k in obj:
                out.setdefault(k, obj[k])
        return out

    out = pick(data, tree, "")
    wrong = sorted(set(missed) - found)
    if wrong:
        there = missed[wrong[0]]
        if isinstance(there, str):
            raise Error(
                "E_USAGE",
                f"--fields names {wrong[0]}, but {there} is a value with nothing below it",
                {"field": wrong[0]},
            )
        raise Error(
            "E_USAGE",
            f"--fields names {wrong[0]}, which this output does not have",
            {"field": wrong[0], "available": there[:60]},
        )
    return out


def validate_schema(value, schema, path="data"):
    """Small deliberately bounded subset of JSON Schema used by the registry."""
    if not schema:
        return
    kinds = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(
        number(value) if t == "number" else type(value) is kinds[t] for t in types
    ):
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
