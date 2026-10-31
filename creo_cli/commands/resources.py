"""Bounded object readers. Null acquisition is incomplete, never an empty collection."""

from __future__ import annotations

from .. import engine
from ..core import Error, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import S, listing, shape
from . import detailing


def _fetch(opts, op, request):
    def fetch(client):
        return engine.normalize(client.op(op, request))

    return engine.read(opts, fetch)


def _list(op, kind, model_kinds):
    def run(opts):
        name = engine.model_name(opts["model"], model_kinds)
        sheet = opts.get("sheet")
        if sheet is not None and sheet < 1:
            raise Error("E_VALIDATION", "sheet numbers begin at1")
        data = engine.read(
            opts,
            lambda client: engine.resource_inventory(
                client, op, {"model": name, "kind": kind, "sheet": sheet}
            ),
        )
        items = data["items"]
        return page(items, opts["limit"], opts["offset"]) | {
            "model": data["model"],
            "resource": kind,
            "source": data.get("source"),
            "scope": data.get("scope"),
            "coverage": data.get("coverage"),
            "_untrusted": ["items", "coverage"],
        }

    return run


def _show(op, kind, model_kinds):
    getter = _list(op, kind, model_kinds)

    def run(opts):
        # Selection operates on the entire bounded native resource inventory, not just one page.
        data = getter(opts | {"limit": 1000, "offset": 0})
        if data["has_more"]:
            raise Error("E_VALIDATION", "resource inventory exceeds1000; select a narrower scope")
        wanted = str(opts["item"])
        rows = [
            row
            for row in data["items"]
            if isinstance(row, dict)
            and any(
                row.get(key) is not None and str(row[key]) == wanted
                for key in ("id", "name", "number", "label")
            )
        ]
        if len(rows) != 1:
            raise Error(
                "E_NOT_FOUND" if not rows else "E_CONFLICT",
                "resource selector must identify exactly one item",
                {"matched_count": len(rows), "resource": kind},
            )
        return {
            "model": data["model"],
            "item": rows[0],
            "source": data["source"],
            "scope": data["scope"],
            "_untrusted": ["item"],
        }

    return run


def _single(op, kinds):
    def run(opts):
        name = engine.model_name(opts["model"], kinds)
        data = _fetch(opts, op, {"model": name})
        if data.get("completed") is not True or data.get("model") != name or not data.get("source"):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "required native getter did not complete",
                {"observation": data},
            )
        return data | {"_untrusted": ["model", "data"]}

    return run


def _component_list(opts):
    if opts.get("editable"):
        from .. import assembly_constraints

        return assembly_constraints.component_list(opts)
    return _list("assembly.components", "components", ("asm",))(opts)


def _component_show(opts):
    if opts.get("editable"):
        from .. import assembly_constraints

        return assembly_constraints.component_show(opts)
    return _show("assembly.components", "components", ("asm",))(opts)


def _remove(prefix):
    def run(opts):
        raw = opts["item"]
        if ":" in raw and not raw.startswith(prefix + ":"):
            raise Error("E_VALIDATION", "item belongs to a different drawing resource")
        return detailing.remove(opts | {"item": raw if ":" in raw else prefix + ":" + raw})

    return run


COMMANDS = []
for noun, kind in [
    ("sheet", "sheets"),
    ("view", "views"),
    ("dimension", "dimensions"),
    ("note", "notes"),
    ("table", "tables"),
    ("symbol", "symbols"),
    ("datum", "datums"),
    ("gtol", "gtols"),
]:
    params = (MODEL, Param("sheet", "integer", description="optional actual sheet number"))
    COMMANDS += [
        Command(
            f"drawing {noun} list",
            "Read actual "
            + kind
            + " with source/owner and optional sheet scope; missing getters are incomplete",
            _list("drawing.resources", kind, ("drw",)),
            listing(shape({})),
            params=(*params, LIMIT, OFFSET),
            service_ops=("drawing.resources",),
            untrusted=("items", "coverage"),
            example="--model drawing.drw",
        ),
        Command(
            f"drawing {noun} show",
            "Read exactly one actual " + noun,
            _show("drawing.resources", kind, ("drw",)),
            shape({"model": S, "item": shape({})}),
            params=(
                *params,
                Param("item", required=True, description="actual item id/name or sheet number"),
            ),
            service_ops=("drawing.resources",),
            untrusted=("item",),
            example="--model drawing.drw --item 1",
        ),
    ]
    if noun != "sheet":
        old = next(command for command in detailing.COMMANDS if command.path == "drawing remove")
        COMMANDS.append(
            Command(
                f"drawing {noun} remove",
                "Remove an isolated general view on one single-part sheet; refuse cascade "
                "and incomplete dependencies; read native IDs and preserve source geometry"
                if noun == "view"
                else "Remove a "
                + noun
                + "; source-model and drawing ownership restrictions remain",
                _remove(noun),
                old.output,
                params=(
                    MODEL,
                    Param("item", required=True, description="exact observed native name or id"),
                ),
                write=True,
                service_ops=(
                    *old.service_ops,
                    "drawing.resources",
                    "model.show",
                    "geometry.list",
                    "feature.list",
                    "dimension.list",
                )
                if noun == "view"
                else old.service_ops,
                untrusted=old.untrusted,
                example="--model drawing.drw --item 1",
            )
        )
COMMANDS += [
    Command(
        "drawing show",
        (
            "Drawing identity, actual sheet count/projection and source "
            "models; resource lists are separate"
        ),
        _single("drawing.info", ("drw",)),
        shape({"model": S}),
        params=(MODEL,),
        service_ops=("drawing.info",),
        example="--model drawing.drw",
    ),
    Command(
        "assembly component list",
        "Top-level occurrences and actual placement; --editable reads bound selections, "
        "reference catalogs and copyable constraint requests; recursive paths are not implemented",
        _component_list,
        listing(shape({})),
        params=(
            MODEL,
            Param("editable", "boolean", description="read an edit-bound constraint snapshot"),
            LIMIT,
            OFFSET,
        ),
        service_ops=("assembly.components", "assembly.constraint-state"),
        untrusted=("items",),
        example="--model group.asm",
    ),
    Command(
        "assembly component show",
        "One actual top-level occurrence; --editable includes bound references and a copyable "
        "constraint request",
        _component_show,
        shape({"model": S, "item": shape({})}),
        params=(
            MODEL,
            Param("item", required=True),
            Param("editable", "boolean", description="read an edit-bound constraint snapshot"),
        ),
        service_ops=("assembly.components", "assembly.constraint-state"),
        untrusted=("item",),
        example="--model group.asm --item 1",
    ),
    Command(
        "assembly placement check",
        "Read actual component placement without computing global interference",
        _single("assembly.placement", ("asm",)),
        shape({"model": S}),
        params=(MODEL,),
        service_ops=("assembly.placement",),
        example="--model group.asm",
    ),
    Command(
        "assembly interference check",
        "Explicit global interference evaluation; per-pair/component subsets are not implemented",
        _single("assembly.check", ("asm",)),
        shape({"model": S}),
        params=(
            MODEL,
            Param(
                "scope",
                default="all",
                choices=("all",),
                description="explicit whole-assembly evaluation",
            ),
        ),
        service_ops=("assembly.check",),
        example="--model group.asm --scope all",
    ),
    Command(
        "assembly explode show",
        "Read actual named exploded states",
        _list("assembly.exploded-states", "exploded_states", ("asm",)),
        listing(shape({})),
        params=(MODEL, LIMIT, OFFSET),
        service_ops=("assembly.exploded-states",),
        untrusted=("items",),
        example="--model group.asm",
    ),
    Command(
        "geometry mass-properties",
        "Independent native mass properties in actual model units",
        _single("geometry.mass-properties", ("prt", "asm")),
        shape({"model": S}),
        params=(MODEL,),
        service_ops=("geometry.mass-properties",),
        example="--model block",
    ),
    Command(
        "geometry bounds",
        (
            "Independent native outline with declared approximation; not "
            "an exact geometry acceptance proof"
        ),
        _single("geometry.bounds", ("prt", "asm")),
        shape({"model": S}),
        params=(MODEL,),
        service_ops=("geometry.bounds",),
        example="--model block",
    ),
]
