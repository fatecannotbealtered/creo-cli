"""feature list, show, delete, suppress, resume, rename: the model tree, read and edited.
The commands that build features are in build.py and are listed here in tree order."""

from __future__ import annotations

from .. import building, engine
from ..core import Error, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import FEATURE, NI, NN, WRITTEN, N, S, array, listing, shape, written
from ..sketch import FEATURE_NAME
from ..transport import Client
from ..validation import text, validate
from . import build

FEATURE_REF = text(pattern=r"^[A-Za-z0-9_-]{1,80}$", maximum=80)


def feature_ref(value: str) -> str:
    validate(value, FEATURE_REF, "feature")
    return value


# ------------------------------------------------------------------ reads


def list_features(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))

    def fetch(client: Client) -> dict:
        data = engine.normalize(
            client.op(
                "feature.list",
                {"model": name, "include_internal": bool(opts.get("include_internal"))},
            )
        )
        return page(data["features"], opts["limit"], opts["offset"]) | {
            "model": data["model"],
            "_untrusted": ["items", "model"],
        }

    return engine.read(opts, fetch)


def show(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))
    wanted = feature_ref(opts["feature"])

    def fetch(client: Client) -> dict:
        data = engine.normalize(client.op("feature.show", {"model": name, "feature": wanted}))
        return data | {
            "model": name,
            "_untrusted": [
                "name",
                "parents",
                "children",
                "dimensions",
                "sections",
                "native_definition",
                "native_solid_geometry",
                "native_section_readback",
                "native_auxiliary_datums",
                "model",
            ],
        }

    return engine.read(opts, fetch)


def _features(client: Client, name: str, internal: bool = False) -> list[dict]:
    return engine.normalize(
        client.op("feature.list", {"model": name, "include_internal": internal})
    )["features"]


# ------------------------------------------------------------------ delete


def _prepare_delete(opts: dict) -> dict:
    return {
        "name": engine.model_name(opts["model"], ("prt", "asm")),
        "feature": feature_ref(opts["feature"]),
    }


def _plan_delete(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted = pre["name"], pre["feature"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    target = engine.normalize(client.op("feature.show", {"model": name, "feature": wanted}))
    old = _features(client, name, internal=True)
    doomed = _descendants(client, name, target)

    def verify(c: Client, data: dict):
        after = {f["id"] for f in _features(c, name, internal=True)}
        gone = [f["id"] for f in doomed]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "feature_and_children_gone",
                    not (set(gone) & after),
                    still_present=sorted(set(gone) & after),
                ),
                engine.check(
                    "other_features_kept",
                    all(f["id"] in after for f in old if f["id"] not in gone and f.get("visible")),
                ),
            ],
            "observations": [{"observation": "volume_after", "volume": data.get("volume")}],
            "not_checked": ["design_intent_of_what_remains"],
        }

    return engine.Plan(
        op="feature.delete",
        request={"model": name, "feature": target["id"]},
        target=name,
        binding={"model": before, "features": old, "target": target},
        preview={
            "command": "feature delete",
            "model": name,
            "deletes": {k: target.get(k) for k in ("id", "name", "type", "status")},
            "children_deleted_with_it": [f for f in doomed if f["id"] != target["id"]],
            "effect": "the feature and every feature that depends on it are removed; the model "
            "must be saved "
            "to make that permanent, or discarded to undo it",
        },
        verify=verify,
        observe=lambda c: _features(c, name, internal=True),
        before=old,
        arguments={"model": opts["model"], "feature": wanted},
    )


def _descendants(client: Client, name: str, target: dict) -> list[dict]:
    """The feature and, transitively, every feature that depends on it."""
    out, queue, seen = [], [target], set()
    while queue:
        f = queue.pop(0)
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        out.append({k: f.get(k) for k in ("id", "name", "type", "visible")})
        for child in f.get("children", []):
            queue.append(
                engine.normalize(client.op("feature.show", {"model": name, "feature": child["id"]}))
            )
    return out


def delete(opts: dict) -> dict:
    return engine.write("feature delete", opts, _prepare_delete, _plan_delete)


# ------------------------------------------------------------------ suppress, resume, rename


def _prepare_state(opts: dict) -> dict:
    return {
        "name": engine.model_name(opts["model"], ("prt", "asm")),
        "feature": feature_ref(opts["feature"]),
    }


def _state_change(command: str, op: str, suppress: bool):
    def plan(client: Client, opts: dict, pre: dict) -> engine.Plan:
        name, wanted = pre["name"], pre["feature"]
        s = engine.session(client)
        engine.require_in_session(s, name)
        before = engine.show(client, name)
        engine.store_directory(before, s)
        old = _features(client, name, internal=True)
        target = building.feature_by_ref(old, wanted)
        suppressed = target["status"] == "FEAT_SUPPRESSED"
        if suppress == suppressed:
            raise Error(
                "E_CONFLICT",
                "the feature is already " + ("suppressed" if suppressed else "active"),
                {"feature": target.get("name") or target["id"], "_untrusted": ["feature"]},
            )
        affected = (
            _descendants(
                client,
                name,
                engine.normalize(
                    client.op("feature.show", {"model": name, "feature": target["id"]})
                ),
            )
            if suppress
            else [{k: target.get(k) for k in ("id", "name", "type", "visible")}]
        )

        def verify(c: Client, data: dict):
            after = {f["id"]: f for f in _features(c, name, internal=True)}
            want = "FEAT_SUPPRESSED" if suppress else "FEAT_ACTIVE"
            touched = {f["id"] for f in affected}
            return data, {
                "level": "selected_postconditions_verified",
                "checks": [
                    engine.check(
                        "feature_" + ("suppressed" if suppress else "active"),
                        after.get(target["id"], {}).get("status") == want,
                    ),
                    engine.check(
                        "features_kept",
                        all(f["id"] in after for f in old if f.get("visible")),
                    ),
                    engine.check(
                        "other_features_unchanged",
                        all(
                            after[f["id"]]["status"] == f["status"]
                            for f in old
                            if f["id"] in after and f["id"] not in touched and f.get("visible")
                        )
                        if suppress
                        else True,
                    ),
                ],
                "observations": [{"observation": "volume", "volume": data.get("volume")}],
                "not_checked": ["design_intent"],
            }

        return engine.Plan(
            op=op,
            request={"model": name, "feature": target["id"]},
            target=name,
            binding={"model": before, "features": old},
            preview={
                "command": command,
                "model": name,
                "feature": {k: target.get(k) for k in ("id", "name", "type", "status")},
                ("suppresses" if suppress else "resumes"): affected,
                "effect": "suppressed features stay in the model and come back with feature resume"
                if suppress
                else "the feature and the parents it needs are resumed",
            },
            verify=verify,
            observe=lambda c: _features(c, name, internal=True),
            before=old,
            arguments={"model": opts["model"], "feature": wanted},
        )

    def run(opts: dict) -> dict:
        return engine.write(command, opts, _prepare_state, plan)

    return run


suppress = _state_change("feature suppress", "feature.suppress", True)
resume = _state_change("feature resume", "feature.resume", False)


def _prepare_rename(opts: dict) -> dict:
    validate(opts["name"], FEATURE_NAME, "name")
    return _prepare_state(opts) | {"new_name": opts["name"]}


def _plan_rename(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted, new_name = pre["name"], pre["feature"], pre["new_name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    old = _features(client, name, internal=True)
    target = building.feature_by_ref(old, wanted)
    if any(
        str(f.get("name") or "").upper() == new_name.upper() and f["id"] != target["id"]
        for f in old
    ):
        raise Error(
            "E_CONFLICT",
            "another feature already has that name",
            {"name": new_name, "_untrusted": ["name"]},
        )

    def verify(c: Client, data: dict):
        after = {f["id"]: f for f in _features(c, name, internal=True)}
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "feature_renamed",
                    str(after.get(target["id"], {}).get("name") or "").upper() == new_name.upper(),
                ),
                engine.check("tree_unchanged", sorted(after) == sorted(f["id"] for f in old)),
            ],
            "not_checked": ["references_by_name_elsewhere"],
        }

    return engine.Plan(
        op="feature.rename",
        request={"model": name, "feature": target["id"], "name": new_name},
        target=name,
        binding={"model": before, "features": old},
        preview={
            "command": "feature rename",
            "model": name,
            "feature": {k: target.get(k) for k in ("id", "name", "type")},
            "new_name": new_name,
        },
        verify=verify,
        observe=lambda c: _features(c, name, internal=True),
        before=old,
        arguments={"model": opts["model"], "feature": wanted, "name": new_name},
    )


def rename(opts: dict) -> dict:
    return engine.write("feature rename", opts, _prepare_rename, _plan_rename)


# ------------------------------------------------------------------ declarations

SHOWN = shape(
    {
        "id": S,
        "name": {"type": ["string", "null"]},
        "type": S,
        "status": S,
        "number": NI,
        "parents": array(shape({})),
        "children": array(shape({})),
        "dimensions": array(shape({"name": S, "value": N})),
        "sections": array(shape({})),
        "native_definition": shape({}),
        "native_solid_geometry": shape({}),
        "native_section_readback": {"type": ["object", "null"]},
        "native_auxiliary_datums": {"type": ["object", "null"]},
        "model": S,
    },
    ("id", "type", "status", "parents", "children", "dimensions", "sections"),
)
DELETED = shape(
    {
        "model": S,
        "deleted": array(FEATURE),
        "still_present": array({}),
        "feature_count": NI,
        "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
    },
    ("model", "deleted", "still_present"),
)
STATUS_CHANGED = shape(
    {
        "model": S,
        "features": array(FEATURE),
        "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
    },
    ("model", "features"),
)
RENAMED = shape(
    {"model": S, "before": {"type": ["string", "null"]}, "feature": FEATURE}, ("model", "feature")
)
COMMANDS = [
    Command(
        "feature list",
        "The model tree in regeneration order: id, name, type, status; internal ones on request",
        list_features,
        listing(FEATURE, model=S),
        (
            MODEL,
            Param(
                "include-internal",
                "boolean",
                description="also list features Creo keeps out of the tree",
            ),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items", "model"),
        example="--model block",
        service_ops=("feature.list",),
        sort="regeneration order",
    ),
    Command(
        "feature show",
        "One feature in full: dimensions, parents, children, sketch entities; "
        "native construction/machining definition, section placement and bounded rib "
        "auxiliary datum dependencies when readable",
        show,
        SHOWN,
        (MODEL, Param("feature", required=True, description="feature name or id")),
        untrusted=(
            "name",
            "parents",
            "children",
            "dimensions",
            "sections",
            "native_definition",
            "native_solid_geometry",
            "native_section_readback",
            "native_auxiliary_datums",
            "model",
        ),
        example="--model block --feature BASE",
        service_ops=("feature.show",),
    ),
    *build.COMMANDS,
    Command(
        "feature delete",
        "Delete a feature and every feature that depends on it; the preview lists them",
        delete,
        written(DELETED),
        (MODEL, Param("feature", required=True, description="feature name or id")),
        write=True,
        dangerous=True,
        untrusted=WRITTEN,
        example="--model block --feature HOLE",
        service_ops=("feature.show", "feature.delete"),
    ),
    Command(
        "feature suppress",
        "Suppress a feature and every feature that depends on it; they stay in the model",
        suppress,
        written(STATUS_CHANGED),
        (MODEL, Param("feature", required=True, description="feature name or id")),
        write=True,
        untrusted=WRITTEN,
        example="--model block --feature HOLE",
        service_ops=("feature.show", "feature.suppress"),
    ),
    Command(
        "feature resume",
        "Resume a suppressed feature, with the parents it needs",
        resume,
        written(STATUS_CHANGED),
        (MODEL, Param("feature", required=True, description="feature name or id")),
        write=True,
        untrusted=WRITTEN,
        example="--model block --feature HOLE",
        service_ops=("feature.resume",),
    ),
    Command(
        "feature rename",
        "Give a feature a new name",
        rename,
        written(RENAMED),
        (
            MODEL,
            Param("feature", required=True, description="feature name or id"),
            Param(
                "name",
                required=True,
                description="the new name: a letter, then letters, digits or '_', 31 at most",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model block --feature EXTRUDE_40 --name BASE",
        service_ops=("feature.rename",),
    ),
]
