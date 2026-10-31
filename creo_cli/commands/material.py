"""material list, material assign: Creo's material library, and giving a part one of its
materials so it has a density and a mass."""

from __future__ import annotations

from .. import engine, paths
from ..core import Error, page
from ..registry import LIMIT, OFFSET, Command, Param
from ..schemas import WRITTEN, S, listing, shape, written
from ..transport import Client
from ..validation import text, validate

NAME = text(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$", maximum=80)
FILTER = text(pattern=r"^[A-Za-z0-9_.-]{1,80}$", maximum=80)


def list_materials(opts: dict) -> dict:
    query = {}
    if opts.get("name"):
        validate(opts["name"], FILTER, "name")
        query["name"] = opts["name"]
    if opts.get("model"):
        query["model"] = engine.model_name(opts["model"], ("prt",))

    def fetch(client: Client) -> dict:
        data = engine.normalize(client.op("material.list", query))
        out = page(data["materials"], opts["limit"], opts["offset"]) | {
            "library": data["library"],
            "_untrusted": ["items", "library", "model"],
        }
        if "model" in data:
            out["model"] = data["model"]
        return out

    return engine.read(opts, fetch)


def _state(client: Client, name: str) -> dict:
    """The part's own material and mass, read on their own: a filter no material matches."""
    data = engine.normalize(client.op("material.list", {"name": "~", "model": name}))
    state = data.get("model")
    if not isinstance(state, dict) or state.get("model") != name:
        raise Error("E_VERIFY_INCOMPLETE", "material state could not be independently read")
    return state | {"configuration": data.get("configuration")}


def _prepare_assign(opts: dict) -> dict:
    from ..material_files import read_source

    validate(opts["material"], NAME, "material")
    result = {"name": engine.model_name(opts["model"], ("prt",))}
    if opts.get("file"):
        file = paths.contained(opts["file"], directory=False)
        if file.stem.casefold() != opts["material"].casefold():
            raise Error("E_VALIDATION", "material name must identify the supplied file's stem")
        result["source"] = read_source(file)
    return result


def _plan_assign(client: Client, opts: dict, pre: dict) -> engine.Plan:
    from ..engineering_properties import checked_plan
    from ..material_files import read_source

    client.require_capability("material_source_binding", 1)
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    library = engine.normalize(
        client.op("material.list", {"name": opts["material"], "model": name})
    )
    exact = [m for m in library["materials"] if m["name"].lower() == opts["material"].lower()]
    if not exact and not pre.get("source"):
        raise Error(
            "E_NOT_FOUND",
            "no material of that name in Creo's material library",
            {
                "material": opts["material"],
                "similar": [m["name"] for m in library["materials"]][:10],
                "fix": "creo-cli material list --name <part of the name>",
                "_untrusted": ["material", "similar"],
            },
        )
    if len(exact) > 1 and not pre.get("source"):
        raise Error(
            "E_CONFLICT",
            "the library holds more than one material of that name",
            {"categories": [m["category"] for m in exact], "_untrusted": ["categories"]},
        )
    state = library.get("model") or {}
    if not pre.get("source") and not exact[0].get("file"):
        raise Error("E_VERIFY_INCOMPLETE", "material library did not expose the actual source file")
    source = pre.get("source") or read_source(exact[0]["file"])
    chosen = (
        {"name": opts["material"], "category": None, "file": source["path"]}
        if pre.get("source")
        else exact[0]
    )
    if before["units"].get("length") != "mm" or before["units"].get("mass") != "tonne":
        raise Error(
            "E_UNSUPPORTED", "this material engineering profile requires mm and tonne model units"
        )

    def verify(c: Client, data: dict):
        after = _state(c, name)
        mass = (after.get("mass_properties") or {}).get("mass")
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "material_assigned",
                    str(after.get("material") or "").lower() == chosen["name"].lower(),
                    material=after.get("material"),
                ),
                engine.check("part_has_a_mass", isinstance(mass, int | float) and mass > 0),
            ],
            "not_checked": ["material_properties_beyond_density"],
        }

    plan = engine.Plan(
        op="material.assign",
        request={
            "model": name,
            "material": chosen["name"],
            "file": source["path"],
            "source_sha256": source["sha256"],
        },
        target=name,
        binding={"model": before, "material": chosen, "state": state, "source": source},
        preview={
            "command": "material assign",
            "model": name,
            "material": chosen,
            "source": source,
            "input_files": [source["path"]],
            "density_in_model_units": {
                "value": source["model_density_tonne_per_mm3"],
                "units": "tonne/mm^3",
            },
            "current_material": state.get("material"),
            "effect": "the part gets the material's density, and a mass",
        },
        verify=verify,
        observe=lambda c: _state(c, name),
        before=state,
        arguments={"model": opts["model"], "material": opts["material"], "file": opts.get("file")},
    )
    return checked_plan(
        client, plan, expected_density=source["model_density_tonne_per_mm3"], material_reader=_state
    )


def assign(opts: dict) -> dict:
    return engine.write("material assign", opts, _prepare_assign, _plan_assign)


ROW = shape({"name": S, "category": {"type": ["string", "null"]}, "file": S}, ("name",))
STATE = {"type": ["object", "null"]}
COMMANDS = [
    Command(
        "material list",
        "Materials in Creo's library, with their category; with --model, also the part's own",
        list_materials,
        listing(ROW, library=S, model=STATE),
        (
            Param("name", description="only materials whose name contains this"),
            Param("model", description="also report this part's material and mass"),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items", "library", "model"),
        service_ops=("material.list",),
        sort="name",
    ),
    Command(
        "material assign",
        "Assign a source-bound material to a mm/tonne part; independently verify density and mass",
        assign,
        written(
            shape(
                {
                    "model": S,
                    "before": STATE,
                    "after": STATE,
                    "category": {"type": ["string", "null"]},
                },
                ("model", "after"),
            )
        ),
        (
            Param("model", required=True, description="part name, e.g. bracket"),
            Param("material", required=True, description="a material name from material list"),
            Param(
                "file", description="explicit workspace .mtl source; its stem must match --material"
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --material Steel_low_carbon",
        service_ops=("material.list", "material.assign"),
    ),
]
