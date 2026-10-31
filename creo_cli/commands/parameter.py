"""parameter list, parameter set: a model's own parameters -- part number, description, the
values relations read. Types are kept: a value is never converted from one type to another."""

from __future__ import annotations

import math

from .. import engine
from ..core import Error, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import WRITTEN, B, S, listing, shape, written
from ..transport import Client
from ..validation import text, validate

NAME = text(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$", maximum=32)
TYPES = ("string", "integer", "real", "boolean")
# Creo keeps these itself -- units, the material it reports -- and rewrites them.
SYSTEM_PREFIX = "PTC_"


def _parameters(client: Client, name: str) -> dict:
    return engine.normalize(client.op("parameter.list", {"model": name}))


def list_parameters(opts: dict) -> dict:
    name = engine.model_name(opts["model"])

    def fetch(client: Client) -> dict:
        data = _parameters(client, name)
        rows = sorted(data["parameters"], key=lambda r: str(r["name"]).upper())
        return page(rows, opts["limit"], opts["offset"]) | {
            "model": data["model"],
            "_untrusted": ["items", "model"],
        }

    return engine.read(opts, fetch)


def typed(kind: str, raw: str):
    """The flag's text as a value of the parameter's type, or a refusal; never a guess."""
    if kind == "string":
        if len(raw) > 80:
            raise Error("E_VALIDATION", "a string parameter holds at most 80 characters")
        return raw
    if kind == "integer":
        try:
            return int(raw, 10)
        except ValueError:
            raise Error("E_VALIDATION", "not an integer", {"path": "value"}) from None
    if kind == "real":
        try:
            value = float(raw)
        except ValueError:
            raise Error("E_VALIDATION", "not a number", {"path": "value"}) from None
        if not math.isfinite(value):
            raise Error("E_VALIDATION", "not a finite number", {"path": "value"})
        return value
    if raw not in ("true", "false"):
        raise Error("E_VALIDATION", "a boolean is true or false", {"path": "value"})
    return raw == "true"


def _prepare_set(opts: dict) -> dict:
    validate(opts["name"], NAME, "name")
    if opts["name"].upper().startswith(SYSTEM_PREFIX):
        raise Error(
            "E_VALIDATION",
            "PTC_ parameters are Creo's own: it sets them from the model's units and material",
            {"path": "name"},
        )
    return {
        "model": engine.model_name(opts["model"]),
        "value": typed(opts["type"], opts["value"]),
    }


def _plan_set(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, value = pre["model"], pre["value"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    rows = _parameters(client, name)["parameters"]
    existing = next((r for r in rows if str(r["name"]).upper() == opts["name"].upper()), None)
    if existing is None and not opts.get("create"):
        raise Error(
            "E_NOT_FOUND",
            "no parameter of that name; add --create to make it",
            {"parameter": opts["name"], "_untrusted": ["parameter"]},
        )
    if existing is not None and existing["type"] != opts["type"]:
        raise Error(
            "E_CONFLICT",
            "the parameter is of another type; a value is never converted",
            {"parameter_type": existing["type"], "given_type": opts["type"]},
        )
    if existing is not None and existing.get("relation_driven"):
        raise Error(
            "E_CONFLICT",
            "the parameter is driven by a relation, which would overwrite the value",
            {"parameter": opts["name"], "_untrusted": ["parameter"]},
        )

    def verify(c: Client, data: dict):
        now = next(
            (
                r
                for r in _parameters(c, name)["parameters"]
                if str(r["name"]).upper() == opts["name"].upper()
            ),
            None,
        )
        same = now is not None and (
            math.isclose(now["value"], value, rel_tol=1e-12)
            if opts["type"] == "real"
            else now["value"] == value
        )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "value_as_requested", same, value=None if now is None else now["value"]
                ),
                engine.check("type_as_requested", now is not None and now["type"] == opts["type"]),
            ],
            "not_checked": ["relations_that_read_it"],
        }

    return engine.Plan(
        op="parameter.set",
        request={
            "model": name,
            "name": opts["name"],
            "type": opts["type"],
            "value": value,
            "create": existing is None,
        },
        target=name,
        binding={"model": before, "parameter": existing},
        preview={
            "command": "parameter set",
            "model": name,
            "parameter": opts["name"],
            "type": opts["type"],
            "from": None if existing is None else existing["value"],
            "to": value,
            "creates": existing is None,
        },
        verify=verify,
        observe=lambda c: [(r["name"], r["value"]) for r in _parameters(c, name)["parameters"]],
        before=[(r["name"], r["value"]) for r in rows],
        arguments={
            "model": opts["model"],
            "name": opts["name"],
            "type": opts["type"],
            "value": opts["value"],
            "create": bool(opts.get("create")),
        },
    )


def set_parameter(opts: dict) -> dict:
    return engine.write("parameter set", opts, _prepare_set, _plan_set)


ROW = shape(
    {
        "name": S,
        "type": S,
        "value": {"type": ["string", "number", "boolean", "null"]},
        "units": {"type": ["string", "null"]},
        "designated": B,
        "relation_driven": B,
        "description": {"type": ["string", "null"]},
    },
    ("name", "type", "value"),
)
COMMANDS = [
    Command(
        "parameter list",
        "A model's parameters: name, type, value, units, whether a relation drives it",
        list_parameters,
        listing(ROW, model=S),
        (MODEL, LIMIT, OFFSET),
        untrusted=("items", "model"),
        example="--model block",
        service_ops=("parameter.list",),
        sort="name",
    ),
    Command(
        "parameter set",
        "Set a parameter's value, of the type it has; --create makes a new one",
        set_parameter,
        written(
            shape(
                {
                    "model": S,
                    "parameter": ROW,
                    "before": {"type": ["object", "null"]},
                    "created": B,
                },
                ("model", "parameter", "created"),
            )
        ),
        (
            MODEL,
            Param("name", required=True, description="the parameter's name"),
            Param("type", required=True, choices=TYPES, description="the parameter's type"),
            Param("value", required=True, description="the value, as text: 12, 4.5, true, CC-001"),
            Param("create", "boolean", description="create the parameter if it does not exist"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model block --name PART_NO --type string --value CC-001 --create",
        service_ops=("parameter.list", "parameter.set"),
    ),
]
