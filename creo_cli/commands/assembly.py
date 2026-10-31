"""assembly create, add, remove, check: components placed by explicit constraints, and whether
any of them collide."""

from __future__ import annotations

import math
from copy import deepcopy

from .. import assembly_constraints, building, engine
from ..core import Error, digest, read_request
from ..registry import MODEL, REQUEST, Command, Param
from ..schemas import INT, NN, NS, UNITS, WRITTEN, B, N, S, array, shape, written
from ..sketch import LENGTH_UNITS, REFERENCE
from ..transport import Client
from ..validation import strict, text, validate
from . import part

# A reference in the assembly: its own datum, or a component's geometry as ref@component.
ASSEMBLY_REF = text(
    pattern=r"^(?:(?:surface|edge|axis):[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30})"
    r"(?:@(?:[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30}(?:\.(?:prt|asm))?))?$",
    maximum=80,
)
TYPES = ("mate", "align", "insert", "csys", "default", "fix")
CONSTRAINT = strict(
    {
        "type": text(enum=TYPES),
        "assembly_ref": ASSEMBLY_REF,
        "component_ref": REFERENCE,
        "offset": {"type": "number", "minimum": -1e9, "maximum": 1e9},
    },
    ("type",),
)
ADD_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "constraints": {"type": "array", "items": CONSTRAINT, "minItems": 1, "maxItems": 12},
    },
    ("constraints",),
)
ADD_EXAMPLE = {
    "units": "mm",
    "constraints": [
        {"type": "mate", "assembly_ref": "surface:43@base", "component_ref": "surface:46"},
        {"type": "align", "assembly_ref": "ASM_RIGHT", "component_ref": "RIGHT"},
        {"type": "align", "assembly_ref": "ASM_TOP", "component_ref": "TOP"},
    ],
}
COMPONENT = text(
    pattern=r"^(?:[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30}(?:\.(?:prt|asm))?)$", maximum=40
)


def validate_add(request) -> dict:
    validate(request, ADD_SCHEMA)
    for i, c in enumerate(request["constraints"]):
        refs = "assembly_ref" in c and "component_ref" in c
        if c["type"] in ("default", "fix"):
            if "assembly_ref" in c or "component_ref" in c or "offset" in c:
                raise Error(
                    "E_VALIDATION",
                    f"a {c['type']} constraint takes no references and no offset",
                    {"path": f"request.constraints[{i}]"},
                )
        elif not refs:
            raise Error(
                "E_VALIDATION",
                "a constraint names assembly_ref and component_ref",
                {"path": f"request.constraints[{i}]"},
            )
        if "offset" in c and c["type"] not in ("mate", "align"):
            raise Error(
                "E_VALIDATION",
                "only mate and align take an offset",
                {"path": f"request.constraints[{i}].offset"},
            )
    if any("offset" in c for c in request["constraints"]) and "units" not in request:
        raise Error(
            "E_VALIDATION",
            "an offset is a length: the request states its units",
            {"path": "request.units"},
        )
    return dict(request)


def _assembly(opts: dict) -> str:
    return engine.model_name(opts["model"], ("asm",))


def _components(client: Client, name: str) -> list:
    return engine.show(client, name).get("components") or []


def _one_component(components: list, wanted_raw: str) -> dict:
    """A component by its id, or by its model's name when it is placed once."""
    wanted = wanted_raw.lower()
    base = wanted.rsplit(".", 1)[0] if wanted.endswith((".prt", ".asm")) else wanted
    hits = [
        c
        for c in components
        if c["id"] == wanted or str(c.get("model", "")).lower().rsplit(".", 1)[0] == base
    ]
    if not hits:
        raise Error(
            "E_NOT_FOUND",
            "no such component in the assembly",
            {"component": wanted_raw, "_untrusted": ["component"]},
        )
    if len(hits) > 1:
        raise Error(
            "E_CONFLICT",
            "that model is placed more than once; name the component by its id",
            {"ids": [c["id"] for c in hits]},
        )
    return hits[0]


# ------------------------------------------------------------------ add


def _prepare_add(opts: dict) -> dict:
    return {
        "name": _assembly(opts),
        "component": engine.model_name(opts["component"], ("prt", "asm"), "component"),
        "request": validate_add(read_request(opts["request"])),
    }


def _plan_add(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, component, q = pre["name"], pre["component"], pre["request"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    engine.require_in_session(s, component)
    if component == name:
        raise Error("E_VALIDATION", "an assembly cannot contain itself", {"path": "component"})
    before = engine.show(client, name)
    engine.store_directory(before, s)
    engine.require_workspace_models(client, s, [component], "the component")
    if "units" in q:
        building.check_units(before, q["units"])
    # The component's own references must exist; the assembly's are checked by Creo against
    # the components already placed.
    own = [c["component_ref"] for c in q["constraints"] if "component_ref" in c]
    refs = building.references(client, component, own) if own else {}
    old = _components(client, name)

    def verify(c: Client, data: dict):
        now = _components(c, name)
        claimed = data.get("component") or {}
        placed = next((row for row in now if row["id"] == str(claimed.get("id"))), {})
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("component_added", len(now) == len(old) + 1),
                engine.check(
                    "component_is_the_model_asked_for",
                    str(placed.get("model", "")).lower() == component,
                ),
                engine.check("component_placed", placed.get("placed") is True),
                engine.check(
                    "constraints_applied",
                    len(placed.get("constraints") or []) == len(q["constraints"]),
                    applied=[k.get("type") for k in placed.get("constraints") or []],
                ),
                engine.check(
                    "other_components_kept",
                    all(any(n["id"] == o["id"] for n in now) for o in old),
                ),
            ],
            "observations": [
                {
                    "observation": "placement",
                    "fully_constrained": placed.get("underconstrained") is False
                    and placed.get("packaged") is False,
                    "position": placed.get("position"),
                }
            ],
            "not_checked": ["design_intent_of_the_placement"],
        }

    return engine.Plan(
        op="assembly.add",
        request={"model": name, "component": component, "constraints": q["constraints"]},
        target=name,
        binding={"assembly": before, "component": component, "refs": refs},
        preview={
            "command": "assembly add",
            "model": name,
            "component": component,
            "constraints": q["constraints"],
            "component_references": refs,
            "components_now": len(old),
            "effect": "the component is packaged at the assembly origin, then constrained; if the "
            "constraints cannot be applied it is taken out again",
        },
        verify=verify,
        observe=lambda c: [x["id"] for x in _components(c, name)],
        before=[x["id"] for x in old],
        arguments={"model": opts["model"], "component": opts["component"], "request": q},
    )


def add(opts: dict) -> dict:
    return engine.write("assembly add", opts, _prepare_add, _plan_add)


# ------------------------------------------------------------------ remove


def _prepare_remove(opts: dict) -> dict:
    validate(opts["component"], COMPONENT, "component")
    return {"name": _assembly(opts)}


def _plan_remove(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    old = before.get("components") or []
    target = _one_component(old, opts["component"])

    def verify(c: Client, data: dict):
        now = _components(c, name)
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("component_gone", all(x["id"] != target["id"] for x in now)),
                engine.check("reply_says_gone", data.get("gone") is True),
            ],
            "not_checked": ["files_on_disk_untouched_by_design"],
        }

    return engine.Plan(
        op="assembly.remove",
        request={"model": name, "component": target["id"]},
        target=name,
        binding={"assembly": before},
        preview={
            "command": "assembly remove",
            "model": name,
            "removes": target,
            "effect": "the component and every feature that depends on it leave the assembly; "
            "the component's own file is not touched",
        },
        verify=verify,
        observe=lambda c: [x["id"] for x in _components(c, name)],
        before=[x["id"] for x in old],
        arguments={"model": opts["model"], "component": opts["component"]},
    )


def remove(opts: dict) -> dict:
    return engine.write("assembly remove", opts, _prepare_remove, _plan_remove)


def redefine(opts: dict) -> dict:
    from .. import assembly_constraints

    return assembly_constraints.redefine(opts)


# ------------------------------------------------------------------ replace


def _prepare_replace(opts: dict) -> dict:
    return {
        "name": _assembly(opts),
        "with": engine.model_name(opts["with"], ("prt", "asm"), "with"),
    }


def _family_of(model: dict) -> str:
    """The family a model belongs to: its generic's name, or its own."""
    return str((model.get("family") or {}).get("generic") or model.get("model") or "").lower()


def _replacement_state(described):
    """A failed redefine is unchanged only when complete placement data is equal."""
    if type(described.get("modified")) is not bool:
        raise Error("E_VERIFY_INCOMPLETE", "assembly modified state is unreadable")
    rows = described.get("components")
    if not isinstance(rows, list) or len({r.get("id") for r in rows}) != len(rows):
        raise Error("E_VERIFY_INCOMPLETE", "complete unique component inventory is required")
    for row in rows:
        required = (
            "id",
            "model",
            "status",
            "placed",
            "packaged",
            "underconstrained",
            "constraints",
            "position",
        )
        if (
            any(row.get(k) is None for k in required)
            or row.get("constraints_error")
            or row.get("placement_error")
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "component placement readback is incomplete",
                {"component": row.get("id")},
            )
        position = row["position"]
        if not isinstance(position, dict) or any(
            not isinstance(position.get(k), list)
            or len(position[k]) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in position[k])
            for k in ("origin", "x_axis", "y_axis", "z_axis")
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "component transform is incomplete", {"component": row["id"]}
            )
        if "component_path_transform" in row:
            transform = row["component_path_transform"]
            if not isinstance(transform, dict) or any(
                not isinstance(transform.get(k), list)
                or len(transform[k]) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in transform[k])
                for k in ("origin", "x_axis", "y_axis", "z_axis")
            ):
                raise Error("E_VERIFY_INCOMPLETE", "native component path transform is incomplete")
        if not isinstance(row["constraints"], list):
            raise Error("E_VERIFY_INCOMPLETE", "component constraint inventory is incomplete")
        for constraint in row["constraints"]:
            if not constraint.get("type") or "offset" not in constraint:
                raise Error("E_VERIFY_INCOMPLETE", "constraint type or offset is unreadable")
            if constraint["type"] not in ("def_placement", "fix") and any(
                not isinstance(constraint.get(k), dict)
                or any(
                    constraint[k].get(field) is None
                    for field in ("model", "item_id", "item_type", "component_path")
                )
                for k in ("assembly_reference", "component_reference")
            ):
                raise Error("E_VERIFY_INCOMPLETE", "constraint references are incomplete")
    return {"components": rows, "modified": described.get("modified")}


def _plan_replace(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, with_ = pre["name"], pre["with"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    engine.require_in_session(s, with_)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    old = before.get("components") or []
    target = _one_component(old, opts["component"])
    current = str(target.get("model") or "").lower()
    if current == with_:
        raise Error(
            "E_VALIDATION",
            "the component already is that model",
            {"component": target["id"], "model": current, "_untrusted": ["model"]},
        )
    new = engine.show(client, with_)
    was = engine.show(client, current) if current in s["models"] else {"model": current}
    family = _family_of(was)
    if _family_of(new) != family:
        raise Error(
            "E_VALIDATION",
            "a component is replaced by another member of its family -- its generic or another "
            "instance -- whose items share the ids its constraints name",
            {
                "component": target["id"],
                "model": current,
                "family": family,
                "with": with_,
                "with_family": _family_of(new),
                "fix": "remove the component and add the other model with constraints of its own",
                "_untrusted": ["model", "family", "with_family"],
            },
        )
    from .. import dependencies, paths

    observed_before = _replacement_state(before)

    nodes = dependencies.closure(client, {name, with_})
    sources = {
        node["identity"]: paths.model_files(
            engine.store_directory(node["description"], s), node["identity"]
        )
        for node in nodes
    }
    from pathlib import Path

    for node in nodes:
        origin = node["description"].get("origin")
        if (
            origin
            and Path(origin).is_file()
            and str(origin) not in {f["path"] for f in sources[node["identity"]]}
        ):
            sources[node["identity"]].append(paths.artifact(Path(origin)))
    if before.get("constraints_error") or target.get("constraints_error"):
        raise Error("E_VERIFY_INCOMPLETE", "replacement constraints could not be completely read")
    expected_constraints = []
    for constraint in target.get("constraints") or []:
        expected = dict(constraint)
        ref = expected.get("component_reference")
        if constraint.get("type") != "def_placement" and (
            not ref or not expected.get("assembly_reference")
        ):
            raise Error("E_VERIFY_INCOMPLETE", "replacement requires actual constraint references")
        if ref:
            expected["component_reference"] = ref | {"model": with_}
        expected_constraints.append(expected)
    others = {c["id"]: c for c in old if c["id"] != target["id"]}

    def verify(c: Client, data: dict):
        now = {x["id"]: x for x in _replacement_state(engine.show(c, name))["components"]}
        placed = now.get(target["id"]) or {}
        refreshed = dependencies.closure(c, {name})
        return data | {"dependencies_after": dependencies.snapshots(refreshed)}, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "component_holds_the_new_model",
                    str(placed.get("model") or "").lower() == with_,
                    model=placed.get("model"),
                ),
                engine.check(
                    "component_placed",
                    placed.get("status") == "FEAT_ACTIVE" and placed.get("placed") is True,
                    status=placed.get("status"),
                ),
                engine.check(
                    "constraints_kept",
                    placed.get("constraints") == expected_constraints,
                    constraints=placed.get("constraints"),
                ),
                engine.check(
                    "other_components_unchanged",
                    all(i in now and now[i] == row for i, row in others.items())
                    and set(now) == {x["id"] for x in old},
                ),
                engine.check(
                    "new_dependency_independently_read",
                    with_ in {n["identity"] for n in refreshed},
                ),
            ],
            "observations": [
                {
                    "observation": "moved",
                    "from": target.get("position"),
                    "to": placed.get("position"),
                },
                {"observation": "volume", "volume": data.get("volume")},
            ],
            "not_checked": ["design_intent"],
        }

    return engine.Plan(
        op="assembly.replace",
        request={"model": name, "component": target["id"], "with": with_},
        target=name,
        binding={
            "assembly": before,
            "with": new,
            "sources": sources,
            "dependencies": dependencies.snapshots(nodes),
        },
        preview={
            "command": "assembly replace",
            "model": name,
            "component": target,
            "with": with_,
            "family": family,
            "effect": "the component holds the other member of its family, placed by the same "
            "constraints -- each reference finds the item of the same id in it -- and moves as "
            "they place it; if Creo cannot place it, the old model goes back. The old model "
            "stays in session",
        },
        verify=verify,
        observe=lambda c: _replacement_state(engine.show(c, name)),
        before=observed_before,
        arguments={"model": opts["model"], "component": opts["component"], "with": opts["with"]},
    )


def replace(opts: dict) -> dict:
    return engine.write("assembly replace", opts, _prepare_replace, _plan_replace)


# ------------------------------------------------------------------ explode

STATE_NAME = {"type": "string", "pattern": r"[A-Za-z][A-Za-z0-9_-]{0,30}"}
EXPLODE_SCHEMA = strict(
    {
        "units": LENGTH_UNITS,
        "name": STATE_NAME,
        "replace": {"type": "boolean"},
        "moves": {
            "type": "array",
            "items": strict(
                {
                    "components": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 64},
                        "minItems": 1,
                        "maxItems": 100,
                    },
                    "direction": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "distance": {"type": "number", "minimum": -1e6, "maximum": 1e6},
                },
                ("components", "direction", "distance"),
            ),
            "minItems": 1,
            "maxItems": 50,
        },
    },
    ("units", "name", "moves"),
)
EXPLODE_EXAMPLE = {
    "units": "mm",
    "name": "APART",
    "moves": [
        {"components": ["41"], "direction": [0, 0, 1], "distance": 50},
        {"components": ["bolt"], "direction": [0, 0, -1], "distance": 30},
    ],
}


def validate_explode(request) -> dict:
    validate(request, EXPLODE_SCHEMA)
    for i, move in enumerate(request["moves"]):
        if (
            not math.isfinite(math.hypot(*move["direction"]))
            or math.hypot(*move["direction"]) < 1e-9
        ):
            raise Error(
                "E_VALIDATION",
                "a move goes some way: its direction is not zero",
                {"path": f"request.moves[{i}].direction"},
            )
        if move["distance"] == 0:
            raise Error(
                "E_VALIDATION",
                "a move goes some distance",
                {"path": f"request.moves[{i}].distance"},
            )
    return request


def _prepare_explode(opts: dict) -> dict:
    from ..workflow_state import request_file

    source = request_file(opts["request"])
    return {
        "name": _assembly(opts),
        "request": validate_explode(source["content"]),
        "source": source,
    }


def _unit(v: list) -> list:
    n = math.hypot(*v)
    return [c / n for c in v]


def _plan_explode(client: Client, opts: dict, pre: dict) -> engine.Plan:
    client.require_capability("assembly_explosion_context_readback", 1)
    name, q = pre["name"], pre["request"]

    def incomplete(message):
        raise Error("E_VERIFY_INCOMPLETE", message, {"automatic_retry": False})

    def model_identity(model):
        if not isinstance(model, dict) or not isinstance(model.get("model"), str):
            incomplete("complete explosion observation has no readable target model")
        try:
            actual_name = engine.model_name(model["model"], ("asm",))
        except Error:
            incomplete("complete explosion observation has an invalid assembly filename")
        if actual_name != name or model.get("type") != "assembly":
            incomplete("complete explosion observation belongs to another target model or type")
        origin, proof = model.get("origin"), model.get("origin_readback")
        if (
            "origin" not in model
            or not isinstance(proof, dict)
            or proof.get("complete") is not True
            or "error" in proof
            or "value" not in proof
            or proof["value"] != origin
            or not isinstance(proof.get("source"), str)
            or not proof["source"]
            or not (
                origin is None
                and proof.get("state") == "no_origin"
                or isinstance(origin, str)
                and bool(origin)
                and proof.get("state") == "saved"
            )
        ):
            incomplete("complete explosion observation has no explicit readable native origin")
        return {"model": actual_name, "type": "assembly", "origin": origin}

    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    initial_identity = model_identity(before)
    engine.store_directory(before, s)
    building.check_units(before, q["units"])
    components = before.get("components") or []
    moves = [
        {
            "components": [_one_component(components, c)["id"] for c in m["components"]],
            "direction": _unit(m["direction"]),
            "distance": m["distance"],
        }
        for m in q["moves"]
    ]
    from .. import presentation

    initial = presentation.explosion(before)
    physical = _replacement_state(before)
    if any(not c["model"].lower().endswith(".prt") for c in components) or len(components) > 10:
        raise Error("E_UNSUPPORTED", "explode profile supports at most ten direct part occurrences")
    ids = [i for m in moves for i in m["components"]]
    if len(set(ids)) != len(ids):
        raise Error("E_VALIDATION", "an occurrence may appear in only one translation")
    for state in initial["states"]:
        for move in state["moves"]:
            if move["type"] != "translate" or any(len(p) != 1 for p in move["component_paths"]):
                raise Error(
                    "E_UNSUPPORTED", "only complete direct-translation states are supported"
                )
    states = initial["states"]
    existing = next((x for x in states if str(x.get("name")).upper() == q["name"].upper()), None)
    if existing is not None and existing.get("is_default") is True:
        raise Error(
            "E_UNSUPPORTED", "the built-in default explosion is not an editable named state"
        )
    if existing is not None and type(existing.get("is_default")) is not bool:
        raise Error("E_VERIFY_INCOMPLETE", "existing explosion default identity is unreadable")
    if existing is not None and not q.get("replace"):
        raise Error(
            "E_CONFLICT",
            "the assembly has an exploded state of that name",
            {
                "state": q["name"],
                "states": [x.get("name") for x in states],
                "fix": 'set "replace": true to edit its translations in place, or name another',
                "_untrusted": ["states"],
            },
        )

    def verify(c: Client, data: dict):
        if verification_attempt["started"]:
            verification_attempt["reentered"] = True
            incomplete("the first explosion verification cannot be replaced")
        verification_attempt["started"] = True
        after = read_first(c, "verification")
        observed = presentation.explosion(after)
        now = observed["states"]
        state = next((x for x in now if str(x.get("name")).upper() == q["name"].upper()), {})
        if existing is not None and state and type(state.get("is_default")) is not bool:
            raise Error("E_VERIFY_INCOMPLETE", "edited explosion default identity is unreadable")
        held = state.get("moves") or []
        same = len(held) == len(moves) and all(
            [str(i) for i in h.get("components") or []] == m["components"]
            and h.get("component_paths") == [[i] for i in m["components"]]
            and h.get("type") == "translate"
            and presentation.numbers(h.get("direction"), 3)
            and all(
                abs(a - b) <= 1e-9
                for a, b in zip(h.get("direction") or [], m["direction"], strict=False)
            )
            and abs((h.get("distance") or 0) - m["distance"]) <= 1e-9 * max(1.0, abs(m["distance"]))
            for h, m in zip(held, moves, strict=False)
        )
        normal_before, normal_after = (
            engine.normalize(data.get(k)) for k in ("normal_before", "normal_after")
        )
        if not isinstance(normal_before, list) or not isinstance(normal_after, list):
            raise Error("E_VERIFY_INCOMPLETE", "native normal-placement observations are missing")
        _replacement_state({"components": normal_before, "modified": False})
        _replacement_state({"components": normal_after, "modified": False})
        verification = {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("state_made", bool(state)),
                engine.check(
                    "existing_state_identity_preserved",
                    existing is None
                    or (
                        state.get("id") == existing["id"]
                        and state.get("is_default") is existing["is_default"]
                    ),
                    expected=(
                        {k: existing[k] for k in ("id", "is_default")}
                        if existing is not None
                        else None
                    ),
                    observed={k: state.get(k) for k in ("id", "is_default")},
                    source="independent model.show explosion inventory",
                    scope="existing named-state edits preserve the frozen native ID/default flag",
                ),
                engine.check(
                    "native_normal_placement_unchanged",
                    presentation.equivalent(normal_before, normal_after)
                    and presentation.equivalent(
                        normal_before,
                        presentation.normal_components(physical["components"], initial),
                    ),
                    expected=normal_before,
                    observed=normal_after,
                    source=(
                        "service-recorded initial-position/path fields before/after edit "
                        "while un-exploded, "
                        "within the confirmed operation"
                    ),
                    scope=(
                        "raw service snapshots and mathematical consistency only; "
                        "not independent external normal assembly placement proof"
                    ),
                ),
                engine.check(
                    "state_active", state.get("active") is True and observed["is_exploded"]
                ),
                engine.check(
                    "placement_and_display_translations_consistent",
                    presentation.equivalent(
                        presentation.normal_components(
                            _replacement_state(after)["components"], observed
                        ),
                        presentation.normal_components(physical["components"], initial),
                    ),
                    source="full native components/constraints and active translation readback",
                    normal_position=(
                        "mathematically derived from recorded origins; actual normal placement "
                        "requires independent same-context non-exploded observations"
                    ),
                    scope=(
                        "recorded transforms, constraints and move consistency; "
                        "not independent external normal assembly placement proof"
                    ),
                ),
                engine.check(
                    "physical_geometry_unchanged",
                    presentation.equivalent(
                        after.get("mass_properties"), before.get("mass_properties")
                    ),
                    expected=before.get("mass_properties"),
                    observed=after.get("mass_properties"),
                    source="independent model.show mass_properties",
                    scope=(
                        "mass properties only; complete per-part physical geometry, "
                        "material and tolerance preservation are not established by this check"
                    ),
                ),
                engine.check(
                    "other_explosion_states_preserved",
                    presentation.equivalent(
                        [
                            {k: v for k, v in x.items() if k != "active"}
                            for x in now
                            if x["name"].upper() != q["name"].upper()
                        ],
                        [
                            {k: v for k, v in x.items() if k != "active"}
                            for x in states
                            if x["name"].upper() != q["name"].upper()
                        ],
                    ),
                ),
                engine.check("moves_as_requested", same, moves=held),
                engine.check(
                    "one_state_of_that_name",
                    sum(str(x.get("name")).upper() == q["name"].upper() for x in now) == 1,
                ),
            ],
            "observations": [
                {"observation": "states", "observed": observed},
                {"observation": "component_display_positions", "observed": after["components"]},
                {"observation": "complete_model_show", "observed": deepcopy(after)},
            ],
            "not_checked": [
                "how_the_model_looks",
                "independent_normal_assembly_placement",
                "independent_saved_reopened_normal_placement",
            ],
        }
        if not same_plan(p, c):
            incomplete("explosion verification is not bound to this Plan, Client and intent")
        value = first_observation["value"]
        p.verified_observation = deepcopy(value)
        verification["observation_sha256"] = digest(value)
        result = deepcopy(data)
        verification_attempt["issued"] = verification
        verification_attempt["sealed"] = deepcopy(verification)
        verification_attempt["result"] = result
        verification_attempt["sealed_result"] = deepcopy(result)
        return result, verification

    p = engine.Plan(
        op="assembly.explode",
        request={
            "model": name,
            "name": q["name"],
            "replace": bool(q.get("replace")),
            "moves": moves,
        },
        target=name,
        binding={"assembly": before, "request_source": pre["source"]},
        preview={
            "command": "assembly explode apply",
            "model_footprint": [name, "session:presentation"],
            "display_before": initial,
            "normal_placement_check": (
                "during confirmation the service temporarily un-explodes and records component "
                "initial-position/path fields before/after edit, then activates the named "
                "state; raw comparison and derived consistency are not independently observed "
                "external normal assembly placement proof"
            ),
            "limits": ["direct part occurrences; translation only; no animation or auto restore"],
            "model": name,
            "state": q["name"],
            "replaces": existing,
            "moves": moves,
            "effect": "an exploded state of that name -- each component set moved along its "
            "direction by its distance, in the assembly's axes -- made and made the active one: "
            "assembly activity is checked separately from per-view named-state selection and "
            "actual separated projection; drawing --exploded does not establish those facts. "
            "Actual normal assembly placement needs independent same-context verification",
        },
        verify=verify,
        observe=lambda c: observe(c),
        before={
            "explosion": initial,
            "physical": physical,
            "complete_model_observation": deepcopy(before),
        },
        arguments={"model": opts["model"], "request": opts["request"]},
    )
    frozen = deepcopy(
        {
            key: getattr(p, key)
            for key in (
                "request",
                "binding",
                "preview",
                "arguments",
                "before",
                "effects",
                "persisted",
            )
        }
    )
    frozen_request, frozen_moves = deepcopy(q), deepcopy(moves)
    frozen_dispatch = {
        key: getattr(p, key)
        for key in ("send", "first", "then", "apply", "prepare_dispatch", "artifacts_after")
    }
    frozen_observe = p.observe
    first_observation = {
        "attempted": False,
        "purpose": None,
        "model": None,
        "value": None,
        "bound": False,
        "issued": [],
    }
    verification_attempt = {"started": False, "reentered": False}

    def same_value(actual, expected):
        try:
            return digest(actual) == digest(expected)
        except (TypeError, ValueError, RecursionError):
            return False

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and p.op == "assembly.explode"
            and p.target == name
            and all(getattr(p, key, None) is value for key, value in frozen_dispatch.items())
            and p.verify is verify
            and p.observe is frozen_observe
            and not verification_attempt["reentered"]
            and not getattr(c, "_native_read_pending", None)
            and not getattr(c, "_native_diagnostic_stop", None)
            and same_value(q, frozen_request)
            and same_value(moves, frozen_moves)
            and all(same_value(getattr(p, key, None), value) for key, value in frozen.items())
        )

    def read_first(c, purpose):
        if not same_plan(p, c):
            incomplete("explosion observation is not bound to this Plan, Client and intent")
        if not first_observation["attempted"]:
            # Mark before the getter: a failed first read must never authorize B.
            first_observation["attempted"] = True
            first_observation["purpose"] = purpose
            model = engine.show(c, name)
            first_observation["model"] = deepcopy(model)
            if model_identity(model) != initial_identity:
                incomplete("complete explosion observation belongs to another native origin")
            first_observation["value"] = {
                "explosion": presentation.explosion(model),
                "physical": _replacement_state(model),
                "complete_model_observation": deepcopy(model),
            }
            first_observation["bound"] = same_plan(p, c)
        if (
            not first_observation["bound"]
            or first_observation["model"] is None
            or purpose == "verification"
            and first_observation["purpose"] != "verification"
        ):
            incomplete("the first complete explosion observation is unavailable or unbound")
        return deepcopy(first_observation["model"])

    def observe(c):
        read_first(c, "settling")
        issued = deepcopy(first_observation["value"])
        first_observation["issued"].append(issued)
        return issued

    def verified_guard(planned, c):
        return (
            same_plan(planned, c)
            and first_observation["bound"]
            and first_observation["purpose"] == "verification"
            and same_value(getattr(p, "verified_observation", None), first_observation["value"])
            and same_value(verification_attempt.get("issued"), verification_attempt.get("sealed"))
            and same_value(
                verification_attempt.get("result"), verification_attempt.get("sealed_result")
            )
        )

    def failure_unchanged(after):
        if (
            not same_plan(p, client)
            or not first_observation["bound"]
            or not any(after is issued for issued in first_observation["issued"])
            or not same_value(after, first_observation["value"])
        ):
            return None
        if same_value(p.before, first_observation["value"]):
            # An already-dirty owner is not evidence of unchanged saved state.
            return None if after["physical"]["modified"] else True
        return False

    p.failure_unchanged = failure_unchanged
    p._verified_observation_guard = verified_guard
    p._settled_observation = lambda planned, c: (
        deepcopy(first_observation["value"])
        if same_plan(planned, c) and first_observation["bound"]
        else None
    )
    return p


def explode(opts: dict) -> dict:
    return engine.write("assembly explode", opts, _prepare_explode, _plan_explode)


# ------------------------------------------------------------------ check


def check(opts: dict) -> dict:
    name = _assembly(opts)

    def fetch(client: Client) -> dict:
        data = engine.normalize(client.op("assembly.check", {"model": name}))
        return data | {"_untrusted": ["model", "components", "interferences"]}

    return engine.read(opts, fetch)


# ------------------------------------------------------------------ declarations

EXPLODED_STATE = shape(
    {"name": S, "id": S, "active": B, "moves": {"type": ["array", "null"]}},
    ("name", "active"),
)

CONSTRAINT_REFERENCE = shape(
    {"model": S, "item_id": INT, "item_type": S, "component_path": array(INT)}
)
CONSTRAINT_REFERENCE["type"] = ["object", "null"]
COMPONENT_ROW = shape(
    {
        "id": S,
        "model": {"type": ["string", "null"]},
        "status": S,
        "placed": B,
        "packaged": B,
        "underconstrained": B,
        "constraints": array(
            shape(
                {
                    "type": S,
                    "offset": NN,
                    "assembly_reference": CONSTRAINT_REFERENCE,
                    "component_reference": CONSTRAINT_REFERENCE,
                    "assembly_side": NS,
                    "component_side": NS,
                }
            )
        ),
        "position": {"type": ["object", "null"]},
        "component_path_transform": {"type": ["object", "null"]},
    },
    ("id", "model", "status"),
)
COMMANDS = [
    part.declaration(
        part.ASSEMBLY,
        "Create an assembly from a template, as File > New does; units are never implied",
        "gearbox",
    ),
    Command(
        "assembly component redefine",
        "Redefine an existing direct occurrence's bound mate/align constraints in place; "
        "independently verify solved placement and protected components",
        redefine,
        written(
            shape(
                {
                    "model": S,
                    "occurrence": S,
                    "setter_report": shape({}),
                    "independent_state": shape(
                        {
                            "profile": S,
                            "complete": B,
                            "model": S,
                            "units": UNITS,
                            "context": shape({}),
                            "components": array(shape({})),
                            "reference_catalog": array(shape({})),
                            "failed_features": array(INT),
                            "source": S,
                        },
                        ("profile", "complete", "model", "components", "reference_catalog"),
                    ),
                },
                ("model", "occurrence", "independent_state"),
            )
        ),
        (
            MODEL,
            Param(
                "component",
                required=True,
                description="exact occurrence ID, or a model name placed uniquely in the owner",
            ),
            REQUEST,
        ),
        write=True,
        untrusted=WRITTEN,
        request=assembly_constraints.REQUEST_SCHEMA,
        request_example=assembly_constraints.REQUEST_EXAMPLE,
        example="--model gearbox.asm --component 41 --request constraints.json",
        service_ops=("assembly.constraint-state", "assembly.redefine-constraints", "geometry.list"),
    ),
    Command(
        "assembly add",
        "Add a model in session as a component, placed by explicit constraints: mate, align, "
        "insert, csys, default or fix",
        add,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "component": COMPONENT_ROW,
                    "constraints_requested": array(S),
                    "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
                },
                ("model", "component"),
            )
        ),
        (
            MODEL,
            Param(
                "component", required=True, description="the part or assembly to add, in session"
            ),
            REQUEST,
        ),
        write=True,
        untrusted=WRITTEN,
        request=ADD_SCHEMA,
        request_example=ADD_EXAMPLE,
        example="--model gearbox --component pin --request place.json",
        service_ops=("geometry.list", "assembly.add"),
    ),
    Command(
        "assembly remove",
        "Take a component out of an assembly, with every feature that depends on it",
        remove,
        written(
            shape(
                {
                    "model": S,
                    "component": S,
                    "removed": array(shape({})),
                    "gone": B,
                    "components": array(COMPONENT_ROW),
                },
                ("model", "component", "gone"),
            )
        ),
        (
            MODEL,
            Param("component", required=True, description="the component's id, or its model name"),
        ),
        write=True,
        dangerous=True,
        untrusted=WRITTEN,
        example="--model gearbox --component pin",
        service_ops=("assembly.remove",),
    ),
    Command(
        "assembly replace",
        "Put another member of a component's family -- another instance, or the generic -- in "
        "its place, held by the same constraints",
        replace,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "replaced": S,
                    "component": COMPONENT_ROW,
                    "before": COMPONENT_ROW,
                    "references_moved": N,
                    "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
                },
                ("model", "replaced", "component"),
            )
        ),
        (
            MODEL,
            Param("component", required=True, description="the component's id, or its model name"),
            Param(
                "with",
                required=True,
                description="the family member to put in its place, in session: "
                "model open --instance brings one in",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model gearbox --component 41 --with pin_6x40",
        service_ops=("assembly.replace",),
    ),
    Command(
        "assembly explode",
        "Create or edit a named translation state in place and activate it; at most ten direct "
        "part occurrences, full direction/distance and native normal-placement readback; "
        "no animation",
        explode,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "state": EXPLODED_STATE,
                    "states": array(EXPLODED_STATE),
                    "replaced": B,
                    "normal_before": array(COMPONENT_ROW),
                    "normal_after": array(COMPONENT_ROW),
                    "normal_placement_source": S,
                },
                ("model", "state", "states"),
            )
        ),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=EXPLODE_SCHEMA,
        request_example=EXPLODE_EXAMPLE,
        example="--model gearbox --request apart.json",
        service_ops=("assembly.explode",),
    ),
    Command(
        "assembly check",
        "Every component and how firmly it is placed, and every pair of parts that interfere, with "
        "the volume they share",
        check,
        shape(
            {
                "model": S,
                "units": UNITS,
                "components": array(COMPONENT_ROW),
                "not_fully_constrained": N,
                "interferences": array(shape({"parts": array(shape({})), "volume": N})),
            },
            ("model", "components", "interferences"),
        ),
        (MODEL,),
        untrusted=("model", "components", "interferences"),
        service_ops=("assembly.check",),
    ),
]
