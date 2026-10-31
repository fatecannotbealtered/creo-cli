"""Strict request validation: the subset of JSON Schema that request files use.

Unknown fields are refused, never ignored: an agent that misspells a field hears about
it before anything reaches Creo.
"""

from __future__ import annotations

import re
from typing import Any

from .core import Error, number

NUM = {"type": "number", "minimum": -1e9, "maximum": 1e9}
POS = {"type": "number", "exclusiveMinimum": 0, "maximum": 1e9}
BOOL = {"type": "boolean"}


def text(*, enum: tuple = (), pattern: str | None = None, maximum: int = 256) -> dict:
    result: dict = {"type": "string", "minLength": 1, "maxLength": maximum}
    if enum:
        result["enum"] = list(enum)
    if pattern:
        result["pattern"] = pattern
    return result


def strict(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def validate(value: Any, schema: dict, path: str = "request", depth: int = 0) -> None:
    if depth > 24:
        raise Error("E_VALIDATION", "request nesting limit exceeded", {"path": path})
    if not schema:
        return  # an empty schema takes any value, as in JSON Schema
    if "oneOf" in schema:
        for alternative in schema["oneOf"]:
            try:
                validate(value, alternative, path, depth + 1)
                return
            except Error:
                continue
        raise Error("E_VALIDATION", "matches none of the allowed forms", {"path": path})
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {
        "object": type(value) is dict,
        "array": type(value) is list,
        "string": type(value) is str,
        "integer": type(value) is int,
        "number": number(value),
        "boolean": type(value) is bool,
        "null": value is None,
    }
    if kinds and not any(matches[k] for k in kinds):
        raise Error("E_VALIDATION", "wrong value type", {"path": path, "expected": kinds})
    if "enum" in schema and value not in schema["enum"]:
        raise Error("E_VALIDATION", "unsupported value", {"path": path, "allowed": schema["enum"]})
    if isinstance(value, dict):
        props = schema.get("properties", {})
        # Unknown fields are refused unless a schema says the object is open (a workflow
        # step's args, which its own command then checks).
        open_object = schema.get("additionalProperties") is True
        unknown = [] if open_object else sorted(set(value) - set(props))
        missing = sorted(set(schema.get("required", [])) - set(value))
        if unknown or missing:
            raise Error(
                "E_VALIDATION",
                "missing or unknown fields",
                {"path": path, "unknown": unknown, "missing": missing},
            )
        for k, v in value.items():
            validate(v, props.get(k, {}), path + "." + k, depth + 1)
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            raise Error(
                "E_VALIDATION",
                "list size out of range",
                {
                    "path": path,
                    "min": schema.get("minItems", 0),
                    "max": schema.get("maxItems", 1000),
                },
            )
        for v in value:
            validate(v, schema.get("items", {}), path + "[]", depth + 1)
    elif isinstance(value, str):
        if (
            not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000)
            or (schema.get("pattern") and not re.fullmatch(schema["pattern"], value))
            or "\x00" in value
        ):
            raise Error("E_VALIDATION", "invalid string", {"path": path})
    elif number(value):
        if (
            ("minimum" in schema and value < schema["minimum"])
            or ("maximum" in schema and value > schema["maximum"])
            or ("exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"])
        ):
            raise Error("E_VALIDATION", "number out of range", {"path": path})
