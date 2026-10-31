"""Bounded, secret-safe explanations of a refused confirmation binding.

These descriptions never decide admission: the authenticated whole-binding digest does.
Retained expected values are used only when their digest matches the signed token.
"""

from __future__ import annotations

import re

from .core import digest

_MISSING = object()
_SECRET = re.compile(
    r"password|secret|token|authorization|cookie|credential|api[_-]?key|session[_-]?(id|key)", re.I
)
_CREDENTIAL = re.compile(r"ct_[A-Za-z0-9_.-]+|bearer\s+\S+|basic\s+\S+", re.I)
_NAMED_VALUES = frozenset({"value", "before", "after"})
_CATEGORIES = {
    "command": "command",
    "target": "target",
    "arguments": "arguments_or_resolved_request",
    "revision": "observed_state",
    "account": "calling_account",
    "permission": "write_policy",
    "native_opt_in": "write_policy",
    "driver_scope_sha256": "authorization_scope",
    "driver_target": "resolved_target",
    "driver_effects": "authorized_effects",
    "driver_paths": "authorized_paths",
    "driver_outputs": "declared_outputs",
    "driver_dependencies": "dependency_observation",
    "driver_execution_budget": "execution_budget",
}


def category(field: str) -> str:
    return _CATEGORIES.get(field, "binding_extension")


def _label(value: object) -> str:
    return _CREDENTIAL.sub("[REDACTED]", str(value))[:160]


def _sensitive_named(value):
    return isinstance(value, dict) and any(
        _SECRET.search(str(value.get(key, ""))) for key in ("name", "target")
    )


def sanitize(value, path=()):
    """Retain useful diagnostic structure while excluding credential-shaped values."""
    if any(_SECRET.search(str(piece)) for piece in path):
        return "[REDACTED]"
    if isinstance(value, dict):
        named = _sensitive_named(value)
        return {
            _label(key): "[REDACTED]"
            if named and key in _NAMED_VALUES
            else sanitize(item, (*path, key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, path) for item in value]
    if isinstance(value, str):
        return _CREDENTIAL.sub("[REDACTED]", value)
    return value


def _safe(value, path=(), *, force_redact=False):
    if value is _MISSING:
        return {"present": False}
    if force_redact or any(_SECRET.search(str(piece)) for piece in path):
        return "[REDACTED]"
    if isinstance(value, str):
        cleaned = _CREDENTIAL.sub("[REDACTED]", value)
        return cleaned if len(cleaned) <= 160 else cleaned[:160] + "[truncated]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, list):
        return {"type": "array", "length": len(value), "sha256": digest(value)}
    if isinstance(value, dict):
        return {"type": "object", "field_count": len(value), "sha256": digest(value)}
    return {"type": type(value).__name__}


def differences(expected: dict, actual: dict, *, maximum: int = 64) -> dict:
    """Name every changed top-level field; bound nested detail, redact secrets first."""
    fields = sorted(
        key
        for key in expected.keys() | actual.keys()
        if key not in expected or key not in actual or digest(expected[key]) != digest(actual[key])
    )
    rows = []
    truncated = False

    def walk(before, after, path, changes, *, force_redact=False):
        nonlocal truncated
        if before is not _MISSING and after is not _MISSING and digest(before) == digest(after):
            return
        if len(changes) >= maximum:
            truncated = True
            return
        if not force_redact and not any(_SECRET.search(str(piece)) for piece in path):
            if isinstance(before, dict) and isinstance(after, dict):
                named = _sensitive_named(before) or _sensitive_named(after)
                for key in sorted(before.keys() | after.keys()):
                    walk(
                        before.get(key, _MISSING),
                        after.get(key, _MISSING),
                        (*path, key),
                        changes,
                        force_redact=named and key in _NAMED_VALUES,
                    )
                return
            if isinstance(before, list) and isinstance(after, list):
                for index in range(max(len(before), len(after))):
                    walk(
                        before[index] if index < len(before) else _MISSING,
                        after[index] if index < len(after) else _MISSING,
                        (*path, index),
                        changes,
                    )
                return
        changes.append(
            {
                "path": "/"
                + "/".join(_label(piece).replace("~", "~0").replace("/", "~1") for piece in path),
                "expected": _safe(before, path, force_redact=force_redact),
                "actual": _safe(after, path, force_redact=force_redact),
                **({"values_redacted": True} if force_redact else {}),
            }
        )

    for field in fields:
        before, after = expected.get(field, _MISSING), actual.get(field, _MISSING)
        changes = []
        walk(before, after, (field,), changes)
        rows.append(
            {
                "field": _label(field),
                "category": category(field),
                "expected": _safe(before, (field,)),
                "actual": _safe(after, (field,)),
                "changes": changes,
            }
        )
    return {
        "fields": rows,
        "details_truncated": truncated,
        "detail_limit_per_field": maximum,
        "admission": "authenticated whole-binding digest; diagnostics do not relax admission",
    }
