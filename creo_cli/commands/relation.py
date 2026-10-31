"""relation list, relation set: a model's relations -- the equations that tie its dimensions
and parameters together, d2 = d1 / 2 -- as a person writes them in Tools > Relations. Set
replaces the model's own list and regenerates; if the model will not regenerate, Creo is put
back as it was."""

from __future__ import annotations

import re

from .. import engine
from ..core import Error, read_request
from ..registry import MODEL, REQUEST, Command
from ..schemas import NN, WRITTEN, S, array, shape, written
from ..transport import Client
from ..validation import strict, validate

MAX_RELATIONS = 200
LINE = {"type": "string", "minLength": 1, "maxLength": 400}
REQUEST_SCHEMA = strict(
    {"relations": {"type": "array", "items": LINE, "maxItems": MAX_RELATIONS}}, ("relations",)
)
REQUEST_EXAMPLE = {"relations": ["d2 = d1 / 2", "/* keep the hole centred", "d5 = d0 / 2"]}


def _part(opts: dict) -> str:
    return engine.model_name(opts["model"], ("prt", "asm"))


def _same(a: str, b: str) -> bool:
    """Two relations the same but for spacing and case, as Creo may rewrite them."""
    return re.sub(r"\s+", "", a).lower() == re.sub(r"\s+", "", b).lower()


def list_relations(opts: dict) -> dict:
    name = _part(opts)

    def fetch(client: Client) -> dict:
        data = client.op("relation.list", {"model": name})
        return {"model": data["model"], "relations": data["relations"], "_untrusted": ["relations"]}

    return engine.read(opts, fetch)


def validate_relations(q: dict) -> dict:
    validate(q, REQUEST_SCHEMA)
    for i, line in enumerate(q["relations"]):
        if any(ord(ch) < 32 for ch in line):
            raise Error(
                "E_VALIDATION",
                "a relation is one line, without control characters",
                {"path": f"request.relations[{i}]"},
            )
    return q


def _prepare_set(opts: dict) -> dict:
    return {"name": _part(opts), "request": validate_relations(read_request(opts["request"]))}


def _plan_set(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted = pre["name"], pre["request"]["relations"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    current = client.op("relation.list", {"model": name})["relations"]

    def verify(c: Client, data: dict):
        now = c.op("relation.list", {"model": name})["relations"]
        from .dimension import _rows

        reading = _rows(c, name, check_regeneration=True)
        native = reading.get("regeneration_check") or {}
        inventory = c.op("feature.list", {"model": name, "include_internal": True})["features"]
        required = {str(f["id"]) for f in inventory}
        if (
            native.get("completed") is not True
            or not native.get("source")
            or not required <= {str(i) for i in native.get("checked_feature_ids", [])}
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "independent relation regeneration coverage is incomplete"
            )
        dims = reading["dimensions"]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "relations_as_written",
                    len(now) == len(wanted)
                    and all(_same(a, b) for a, b in zip(now, wanted, strict=False)),
                    relations=now,
                ),
                engine.check(
                    "native_regeneration_no_failed_features", native.get("failed_features") == []
                ),
            ],
            "observations": [
                {
                    "observation": "independent_regeneration",
                    "source": native["source"],
                    "observed": native,
                },
                {
                    "observation": "driven_dimensions",
                    "dimensions": [
                        {"name": d.get("name"), "value": d.get("value")}
                        for d in dims
                        if d.get("relation_driven")
                    ],
                },
                {"observation": "volume", "volume": data.get("volume")},
            ],
            "not_checked": ["design_intent"],
        }

    return engine.Plan(
        op="relation.set",
        request={"model": name, "relations": wanted},
        target=name,
        binding={"model": before, "relations": current},
        preview={
            "command": "relation set",
            "model": name,
            "from": current,
            "to": wanted,
            "effect": "the model's relations replaced by these, then regenerated; if it will not "
            "regenerate the old ones go back. Dimensions a relation drives can no longer be set "
            "with dimension set",
        },
        verify=verify,
        observe=lambda c: c.op("relation.list", {"model": name})["relations"],
        before=current,
        arguments={"model": opts["model"], "request": pre["request"]},
    )


def set_relations(opts: dict) -> dict:
    return engine.write("relation set", opts, _prepare_set, _plan_set)


COMMANDS = [
    Command(
        "relation list",
        "A model's relations, one per line, as Tools > Relations shows them",
        list_relations,
        shape({"model": S, "relations": array(S), "_untrusted": array(S)}, ("model", "relations")),
        (MODEL,),
        untrusted=("relations",),
        example="--model block",
        service_ops=("relation.list",),
    ),
    Command(
        "relation set",
        "Replace a model's relations -- d2 = d1 / 2 -- and regenerate; the old ones go back if it "
        "will not regenerate",
        set_relations,
        written(
            shape(
                {
                    "model": S,
                    "relations": array(S),
                    "relations_before": array(S),
                    "volume": shape({"before": NN, "after": NN, "change": NN}),
                    "dimensions": array(shape({})),
                },
                ("model", "relations"),
            )
        ),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=REQUEST_SCHEMA,
        request_example=REQUEST_EXAMPLE,
        example="--model block --request relations.json",
        service_ops=("relation.list", "relation.set"),
    ),
]
