"""Bounded, offline validation of the pinned driver schemas (no network or dependencies).

Only the vocabulary used by the adopted schemas is supported. Unknown assertions fail
closed. This is not a general JSON Schema implementation.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .core import Error


@lru_cache
def schemas() -> dict:
    folder = Path(__file__).resolve().parents[1] / ".agent" / "driver" / "schemas"
    if not folder.is_dir():
        folder = Path(sys.prefix) / "share" / "creo-cli" / "driver" / "schemas"
    return {
        row["$id"]: row
        for p in folder.glob("*.schema.json")
        if isinstance(row := json.loads(p.read_text(encoding="utf-8")), dict)
    }


def validate(name: str, value) -> None:
    uri = name if name.startswith("urn:") else f"urn:tool-driver-cli-spec:{name}:2.0"
    try:
        _check(schemas()[uri], value, schemas()[uri], "$")
    except (ValueError, KeyError, TypeError, RecursionError) as exc:
        raise Error(
            "E_PROTOCOL", "driver schema validation failed", {"schema": uri, "problem": str(exc)}
        ) from exc


def _check(rule: dict | bool, value, document: dict, path: str) -> None:
    if rule is True:
        return
    if rule is False:
        raise ValueError(path + ": forbidden value")
    if "$ref" in rule:
        uri, _, pointer = rule["$ref"].partition("#")
        target_doc = schemas()[uri] if uri else document
        target = target_doc
        for key in pointer.split("/")[1:]:
            target = target[key.replace("~1", "/").replace("~0", "~")]
        _check(target, value, target_doc, path)
    for key in ("allOf", "anyOf", "oneOf"):
        if key not in rule:
            continue
        passed = 0
        for sub in rule[key]:
            try:
                _check(sub, value, document, path)
                passed += 1
            except ValueError:
                pass
        if (
            (key == "allOf" and passed != len(rule[key]))
            or (key == "anyOf" and not passed)
            or (key == "oneOf" and passed != 1)
        ):
            raise ValueError(path + ": " + key)
    if "not" in rule:
        try:
            _check(rule["not"], value, document, path)
        except ValueError:
            pass
        else:
            raise ValueError(path + ": not")
    if "if" in rule:
        try:
            _check(rule["if"], value, document, path)
            branch = "then"
        except ValueError:
            branch = "else"
        _check(rule.get(branch, {}), value, document, path)
    types = {
        "object": lambda v: type(v) is dict,
        "array": lambda v: type(v) is list,
        "string": lambda v: type(v) is str,
        "boolean": lambda v: type(v) is bool,
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) in (int, float),
        "null": lambda v: v is None,
    }
    expected = rule.get("type")
    if expected is not None and not any(
        types[t](value) for t in (expected if isinstance(expected, list) else [expected])
    ):
        raise ValueError(path + ": wrong type")
    if "const" in rule and value != rule["const"]:
        raise ValueError(path + ": const")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(path + ": enum")
    if type(value) is dict:
        if set(rule.get("required", [])) - value.keys():
            raise ValueError(path + ": missing required fields")
        if len(value) < rule.get("minProperties", 0):
            raise ValueError(path + ": minProperties")
        if len(value) > rule.get("maxProperties", float("inf")):
            raise ValueError(path + ": maxProperties")
        for k, v in value.items():
            _check(rule.get("propertyNames", True), k, document, path + ".<key>")
            sub = rule.get("properties", {}).get(k, rule.get("additionalProperties", True))
            _check(sub, v, document, path + "." + k)
    if type(value) is list:
        if len(value) < rule.get("minItems", 0) or len(value) > rule.get("maxItems", float("inf")):
            raise ValueError(path + ": array size")
        if rule.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(
            value
        ):
            raise ValueError(path + ": duplicate items")
        for i, row in enumerate(value):
            _check(rule.get("items", {}), row, document, f"{path}[{i}]")
        if "contains" in rule:
            matches = 0
            for row in value:
                try:
                    _check(rule["contains"], row, document, path)
                    matches += 1
                except ValueError:
                    pass
            if not rule.get("minContains", 1) <= matches <= rule.get("maxContains", float("inf")):
                raise ValueError(path + ": contains")
    if type(value) is str:
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get(
            "maxLength", float("inf")
        ):
            raise ValueError(path + ": string size")
        if "pattern" in rule and not re.search(rule["pattern"], value):
            raise ValueError(path + ": pattern")
        if rule.get("format") in ("date", "date-time"):
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    if type(value) in (int, float):
        if value < rule.get("minimum", -float("inf")) or value > rule.get("maximum", float("inf")):
            raise ValueError(path + ": numeric range")
    supported = {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "title",
        "description",
        "default",
        "examples",
        "type",
        "enum",
        "const",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "properties",
        "required",
        "additionalProperties",
        "minProperties",
        "maxProperties",
        "propertyNames",
        "items",
        "minItems",
        "maxItems",
        "uniqueItems",
        "contains",
        "minContains",
        "maxContains",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
    }
    if set(rule) - supported:
        raise ValueError(path + ": unsupported schema assertion " + str(set(rule) - supported))
