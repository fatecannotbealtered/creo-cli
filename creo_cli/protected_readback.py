"""Required observations for bounded preservation, independent of a setter reply."""

import re

from . import engine
from .core import Error


def tree_complete(read):
    return (
        isinstance(read, dict)
        and read.get("status") == "success"
        and read.get("complete") is True
        and "error" not in read
        and re.fullmatch(r"[a-f0-9]{64}", str(read.get("sha256", ""))) is not None
        and type(read.get("canonical_bytes")) is int
        and read["canonical_bytes"] > 0
    )


def require_units(model):
    units = model.get("units") if isinstance(model, dict) else None
    if (
        not isinstance(units, dict)
        or any(not isinstance(units.get(k), str) or not units[k] for k in ("length", "mass"))
        or any(k.endswith("error") or isinstance(v, (dict, list)) for k, v in units.items())
    ):
        raise Error("E_VERIFY_INCOMPLETE", "required native model units were not successfully read")
    return units


def definitions(client, name, model):
    client.require_capability("protected_definition_readback", 1)
    require_units(model)
    value = engine.normalize(client.op("model.definition-state", {"model": name}))
    rows = value.get("features")
    count = model.get("feature_count")
    excluded = value.get("excluded_component_count")
    if (
        value.get("model") != name
        or value.get("status") != "success"
        or value.get("complete") is not True
        or not isinstance(rows, list)
        or type(count) is not int
        or value.get("visible_feature_count") != count
        or type(excluded) is not int
        or not 0 <= excluded <= count
        or len(rows) != count - excluded
        or len({r.get("id") for r in rows if isinstance(r, dict)}) != len(rows)
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "required native feature-tree inventory is incomplete",
            {"model": name, "observation": value},
        )
    for row in rows:
        read = row.get("definition") if isinstance(row, dict) else None
        if not tree_complete(read):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "required native feature tree was not successfully read",
                {"model": name, "feature": row},
            )
    return value


def physical(client, name, model):
    from .appearance import physical_qualification

    material = engine.normalize(client.op("material.list", {"name": "~", "model": name}))
    observed = material.get("model")
    proof = observed.get("physical_observation") if isinstance(observed, dict) else None
    qualification = physical_qualification(proof, model)
    if (
        not isinstance(observed, dict)
        or observed.get("model") != name
        or not qualification["complete"]
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "required physical observation is incomplete",
            {"model": name, "qualification": qualification},
        )
    if qualification.get("numeric_density_qualified"):
        raise Error(
            "E_UNSUPPORTED",
            "numeric density preservation has not completed native qualification "
            "for this internal trial",
            {"model": name},
        )
    return proof
