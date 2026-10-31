"""Family-table discovery and bounded numeric apply/remove leaves.

Writes use the existing public lifecycle in family_runtime; instances are independently
read in session and require an explicit generic save before clean close. No automatic
rollback, parameter/feature-column editing or implicit instance erasure is promised.
"""

from __future__ import annotations

import math
import re

from .. import building, engine
from ..core import Error
from ..registry import MODEL, REQUEST, Command, Param
from ..schemas import ANY, NN, NS, UNITS, WRITTEN, B, S, array, shape, written
from ..sketch import LENGTH_UNITS
from ..transport import Client
from ..validation import strict, validate

INSTANCE_NAME = r"[A-Za-z][A-Za-z0-9_-]{0,30}"
KEY = re.compile(r"(dimension|parameter|feature):(.{1,80})")
MAX_INSTANCES = 4
MAX_VALUES = 4
REQUEST_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "instances": {
            "type": "array",
            "items": strict(
                {
                    "name": {"type": "string", "pattern": INSTANCE_NAME},
                    "values": {
                        "type": "object",
                        "minProperties": 1,
                        "maxProperties": MAX_VALUES,
                        "patternProperties": {
                            r"^dimension:.{1,80}$": {"type": "number", "exclusiveMinimum": 0}
                        },
                        "propertyNames": {"pattern": r"^dimension:.{1,80}$"},
                        "additionalProperties": True,
                    },
                },
                ("name", "values"),
            ),
            "minItems": 1,
            "maxItems": MAX_INSTANCES,
        },
    },
    ("units", "instances"),
)
REQUEST_EXAMPLE = {
    "units": "mm",
    "instances": [
        {"name": "PIN_SHORT", "values": {"dimension:d1": 12}},
        {"name": "PIN_LONG", "values": {"dimension:d1": 16}},
    ],
}


def _part(opts: dict) -> str:
    return engine.model_name(opts["model"], ("prt",))


def _table(client: Client, name: str) -> dict:
    return engine.normalize(client.op("family.show", {"model": name}))


def show_family(opts: dict) -> dict:
    name = _part(opts)

    def fetch(client: Client) -> dict:
        data = _table(client, name)
        return data | {"_untrusted": ["columns", "instances"]}

    return engine.read(opts, fetch)


# ------------------------------------------------------------------ set


def validate_family(q: dict) -> dict:
    validate(q, REQUEST_SCHEMA)
    seen = set()
    for i, instance in enumerate(q["instances"]):
        where = f"request.instances[{i}]"
        if instance["name"].upper() in seen:
            raise Error("E_VALIDATION", "an instance is named once", {"path": where + ".name"})
        seen.add(instance["name"].upper())
        values = instance["values"]
        if not 1 <= len(values) <= MAX_VALUES:
            raise Error(
                "E_VALIDATION",
                f"an instance sets 1 to {MAX_VALUES} values",
                {"path": where + ".values"},
            )
        for key, value in values.items():
            m = KEY.fullmatch(key)
            here = f"{where}.values.{key}"
            if not m:
                raise Error(
                    "E_VALIDATION",
                    "a value's key is dimension:<symbol>, parameter:<name> or feature:<name>",
                    {"path": here},
                )
            kind = m[1]
            if kind != "dimension":
                raise Error(
                    "E_UNSUPPORTED",
                    "bounded family apply accepts dimension columns only",
                    {"path": here},
                )
            if kind == "dimension" and not (type(value) in (int, float) and math.isfinite(value)):
                raise Error("E_VALIDATION", "a dimension takes a number", {"path": here})
            if kind == "dimension" and value <= 0:
                raise Error(
                    "E_VALIDATION",
                    "bounded family length dimensions must be positive",
                    {"path": here},
                )
            if kind == "feature" and type(value) is not bool:
                raise Error(
                    "E_VALIDATION",
                    "a feature takes true (present) or false (suppressed)",
                    {"path": here},
                )
            if kind == "parameter" and not (
                type(value) in (str, bool, int) or (type(value) is float and math.isfinite(value))
            ):
                raise Error(
                    "E_VALIDATION",
                    "a parameter takes text, a number or true/false, as its type is",
                    {"path": here},
                )
    return q


def _prepare_set(opts: dict) -> dict:
    from .. import family_runtime

    request, source = family_runtime.request_source(opts["request"])
    return {"name": _part(opts), "request": validate_family(request), "source": source}


def _items(client: Client, name: str, q: dict, units_checked: dict) -> dict:
    """What each key names in the part, checked: a dimension in the part's length unit (or
    degrees), a parameter of the value's type, a feature."""
    keys = {k for i in q["instances"] for k in i["values"]}
    found = {}
    dims = None
    for key in sorted(keys):
        kind, ref = KEY.fullmatch(key).groups()
        if kind == "dimension":
            dims = dims or client.op("dimension.list", {"model": name})["dimensions"]
            row = next(
                (
                    d
                    for d in dims
                    if str(d.get("name")).lower() == ref.lower() or str(d.get("id")) == ref
                ),
                None,
            )
            if row is None:
                raise Error(
                    "E_NOT_FOUND",
                    "no dimension of that name in the part; dimension list shows them",
                    {"key": key, "_untrusted": ["key"]},
                )
            if row.get("reference") or not row.get("type"):
                raise Error(
                    "E_VALIDATION",
                    "a reference dimension reports geometry and cannot drive an instance",
                    {"key": key, "_untrusted": ["key"]},
                )
            if row.get("units") != "deg":
                building.check_units(units_checked, q["units"])
            found[key] = {"kind": kind, "name": row.get("name"), "units": row.get("units")}
    return found


def set_family(opts: dict) -> dict:
    from .. import family_runtime

    return engine.write("family set", opts, _prepare_set, family_runtime.plan_apply)


# ------------------------------------------------------------------ remove


def _prepare_remove(opts: dict) -> dict:
    instance = opts["instance"]
    if not re.fullmatch(INSTANCE_NAME, instance):
        raise Error(
            "E_VALIDATION",
            "an instance is named as a model is: a letter, then letters, digits, '_' or '-', at "
            "most 31 characters",
            {"path": "instance"},
        )
    return {"name": _part(opts), "instance": instance}


def remove_instance(opts: dict) -> dict:
    from .. import family_runtime

    return engine.write("family remove", opts, _prepare_remove, family_runtime.plan_remove)


COLUMN = shape(
    {"symbol": S, "kind": NS, "name": NS, "generic_value": ANY},
    ("symbol", "kind", "name"),
)
INSTANCE = shape(
    {"name": S, "verified": NS, "cells": shape({})},
    ("name", "cells"),
)
TABLE = shape(
    {"model": S, "units": UNITS, "columns": array(COLUMN), "instances": array(INSTANCE)},
    ("model", "columns", "instances"),
)
CHECKED = shape(
    {
        "name": S,
        "model": NS,
        "regenerated": B,
        "volume": NN,
        "reads": shape({}),
        "kept_in_session": B,
    },
    ("name", "regenerated"),
)
COMMANDS = [
    Command(
        "family show",
        "A part's family table: the columns -- dimensions, parameters, features -- and each "
        "instance's cells, and the generic when the part is an instance",
        show_family,
        shape(
            {
                "model": S,
                "units": UNITS,
                "generic": NS,
                "columns": array(COLUMN),
                "instances": array(INSTANCE),
                "_untrusted": array(S),
            },
            ("model", "generic", "columns", "instances"),
        ),
        (MODEL,),
        untrusted=("columns", "instances"),
        example="--model pin",
        service_ops=("family.show",),
    ),
    Command(
        "family set",
        "Edit explicit numeric length columns on one saved part generic; keep instantiated rows "
        "for independent readback; no open instances, nested tables, relations or implicit save",
        set_family,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "columns": shape({}),
                    "columns_added": array(S),
                    "instances": array(shape({"name": S, "created": B}, ("name", "created"))),
                    "checked": array(CHECKED),
                    "generic_volume": shape({"before": NN, "after": NN}),
                    "table": TABLE,
                },
                ("model", "columns", "instances", "checked", "table"),
            )
        ),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=REQUEST_SCHEMA,
        request_example=REQUEST_EXAMPLE,
        example="--model pin --request family.json",
        service_ops=(
            "dimension.list",
            "parameter.list",
            "feature.list",
            "family.show",
            "family.set",
        ),
    ),
    Command(
        "family remove",
        "Remove one unused, closed instance row from a saved generic; no implicit erase, "
        "cascade or deletion of disk files",
        remove_instance,
        written(shape({"model": S, "removed": S, "table": TABLE}, ("model", "removed", "table"))),
        (MODEL, Param("instance", required=True, description="the instance's name")),
        write=True,
        dangerous=True,
        untrusted=WRITTEN,
        example="--model pin --instance PIN_8X30",
        service_ops=("family.show", "family.remove"),
    ),
]
