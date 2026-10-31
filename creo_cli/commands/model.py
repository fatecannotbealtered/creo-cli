"""model list, open, save, close, discard, show: any part, assembly or drawing."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from .. import engine, export_record, paths, safety
from ..core import Error, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import (
    ASSEMBLY_EXPLOSION,
    INT,
    NB,
    NI,
    NN,
    NS,
    UNITS,
    VIEW_NATIVE_READBACK_PROPERTIES,
    WRITTEN,
    B,
    N,
    S,
    array,
    listing,
    shape,
    written,
)
from ..transport import Client
from ..validation import text, validate

CREO_TEXT = [
    "model",
    "material",
    "common_name",
    "common_name_readback",
    "origin_readback",
    "draft_entity_readback",
    "datum_planes",
    "origin",
    "bodies",
    "components",
    "models",
    "views",
    "dimensions",
    "notes",
    "tables",
    "symbols",
    "cross_sections",
    "datums",
    "gtols",
]


# ------------------------------------------------------------------ reads


def list_models(opts: dict) -> dict:
    def fetch(client: Client) -> dict:
        rows = engine.normalize(client.op("model.list")["models"])
        rows.sort(key=lambda r: str(r.get("model", "")).lower())
        return page(rows, opts["limit"], opts["offset"])

    return engine.read(opts, fetch)


def show(opts: dict) -> dict:
    name = engine.model_name(opts["model"])

    def fetch(client: Client) -> dict:
        data = engine.show(client, name)
        return data | {"_untrusted": [k for k in CREO_TEXT if k in data]}

    return engine.read(opts, fetch)


# ------------------------------------------------------------------ open


def _prepare_open(opts: dict) -> dict:
    file = paths.contained(opts["path"], exists=False)
    m = paths.MODEL_FILE.fullmatch(file.name)
    if not m:
        raise Error(
            "E_VALIDATION",
            "only Creo model files open here: *.prt, *.asm, *.drw, with or without a version",
            {"path": "path"},
        )
    name = m[1].lower() + "." + m[2].lower()
    versions = paths.model_files(file.parent, name) if file.parent.is_dir() else []
    if not file.exists():
        # block.prt names the model, as File > Open lists it: the newest version on disk.
        if m[3] is not None or not versions:
            raise Error(
                "E_NOT_FOUND",
                "no such file or directory in the workspace",
                {"path": str(file), "_untrusted": ["path"]},
            )
        file = Path(max(versions, key=lambda v: paths.version(v["path"]))["path"])
    if not file.is_file():
        raise Error("E_VALIDATION", "expected a file", {"path": str(file), "_untrusted": ["path"]})
    newest = max(versions, key=lambda v: paths.version(v["path"]))
    if not engine.same_path(newest["path"], file):
        raise Error(
            "E_VALIDATION",
            "Creo opens the newest version of a model in a directory, which is not the file given",
            {
                "given": str(file),
                "newest": newest["path"],
                "fix": "give the newest file",
                "_untrusted": ["given", "newest"],
            },
        )
    instance = opts.get("instance")
    if instance is not None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,30}", instance) or m[2].lower() != "prt":
            raise Error(
                "E_VALIDATION",
                "an instance is one of a part's family table, named as a model is",
                {"path": "instance"},
            )
        instance = instance.lower() + ".prt"
    return {"file": file, "name": name, "artifact": paths.artifact(file), "instance": instance}


def _plan_open(client: Client, opts: dict, pre: dict) -> engine.Plan:
    file, name = pre["file"], pre["name"]
    s = engine.session(client)
    if pre.get("instance"):
        return _plan_open_instance(client, opts, pre, s)
    if name in s["models"]:
        raise Error(
            "E_CONFLICT",
            "a model of that name is already in session; Creo would hand back the session copy "
            "instead of reading the file",
            {
                "model": name,
                "fix": "creo-cli model close --model " + name + " first",
                "_untrusted": ["model"],
            },
        )

    def verify(c: Client, data: dict):
        checks = [
            engine.check("model_in_session", name in engine.session(c)["models"]),
            engine.check("model_name_as_requested", str(data.get("model", "")).lower() == name),
        ]
        if data.get("origin"):
            checks.append(
                engine.check(
                    "opened_from_the_file_given",
                    engine.same_path(engine.origin_directory(data["origin"]), file.parent),
                )
            )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": ["regeneration_state"],
        }

    return engine.Plan(
        op="model.open",
        request={"path": str(file), "display": True},
        target=name,
        binding={"file": pre["artifact"], "models": s["models"]},
        preview={
            "command": "model open",
            "opens": str(file),
            "model": name,
            "file": pre["artifact"],
            "displayed": True,
        },
        verify=verify,
        observe=lambda c: engine.session(c)["models"],
        before=s["models"],
        arguments={"path": opts["path"]},
    )


def _plan_open_instance(client: Client, opts: dict, pre: dict, s: dict) -> engine.Plan:
    """An instance of the generic the file holds, as File > Open asks which one: the generic
    is opened too unless it is in session already."""
    file, generic, instance = pre["file"], pre["name"], pre["instance"]
    if instance in s["models"]:
        raise Error(
            "E_CONFLICT",
            "that instance is already in session",
            {"model": instance, "_untrusted": ["model"]},
        )
    generic_open = generic in s["models"]
    if generic_open:
        table = engine.normalize(client.op("family.show", {"model": generic}))
        names = [str(i.get("name")).lower() + ".prt" for i in table.get("instances") or []]
        if instance not in names:
            raise Error(
                "E_NOT_FOUND",
                "the part in session has no instance of that name",
                {
                    "instance": instance,
                    "instances": [i.get("name") for i in table.get("instances") or []],
                    "_untrusted": ["instance", "instances"],
                },
            )

    def verify(c: Client, data: dict):
        models = engine.session(c)["models"]
        checks = [
            engine.check("instance_in_session", instance in models),
            engine.check("model_name_as_requested", str(data.get("model", "")).lower() == instance),
            engine.check(
                "instance_of_the_generic",
                str((data.get("family") or {}).get("generic") or "").lower() == generic,
                generic=(data.get("family") or {}).get("generic"),
            ),
            engine.check("generic_in_session", generic in models),
        ]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": ["regeneration_state"],
        }

    return engine.Plan(
        op="model.open",
        request={"path": str(file), "instance": instance.removesuffix(".prt"), "display": True},
        target=instance,
        binding={"file": pre["artifact"], "models": s["models"]},
        preview={
            "command": "model open",
            "opens": str(file),
            "generic": generic,
            "generic_in_session": generic_open,
            "instance": instance,
            "file": pre["artifact"],
            "displayed": True,
            "note": "an instance has no file of its own: it is made from its generic's family "
            "table; save the generic to keep a change to the table",
        },
        verify=verify,
        observe=lambda c: engine.session(c)["models"],
        before=s["models"],
        arguments={"path": opts["path"], "instance": opts.get("instance")},
    )


def open_model(opts: dict) -> dict:
    return engine.write("model open", opts, _prepare_open, _plan_open)


# ------------------------------------------------------------------ import

IMPORT_FORMATS = {
    ".stp": "step",
    ".step": "step",
    ".igs": "iges",
    ".iges": "iges",
    ".x_t": "parasolid",
    ".x_b": "parasolid",
}
NEW_NAME = text(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,30}$", maximum=31)


def _prepare_import(opts: dict) -> dict:
    file = paths.contained(opts["path"], directory=False)
    fmt = IMPORT_FORMATS.get(file.suffix.lower())
    if fmt is None:
        raise Error(
            "E_VALIDATION",
            "an exchange file is STEP (.stp, .step), IGES (.igs, .iges) or Parasolid (.x_t, .x_b)",
            {"path": "path"},
        )
    validate(opts["name"], NEW_NAME, "name")
    return {
        "file": file,
        "format": fmt,
        "name": opts["name"].lower(),
        "artifact": paths.artifact(file),
    }


def _plan_import(client: Client, opts: dict, pre: dict) -> engine.Plan:
    file, fmt, name = pre["file"], pre["format"], pre["name"]
    s = engine.session(client)
    cwd = engine.working_directory(s)
    kinds = (
        ("prt", "asm")
        if opts.get("type") is None
        else (("prt",) if opts["type"] == "part" else ("asm",))
    )
    for ext in ("prt", "asm"):
        taken = f"{name}.{ext}"
        if taken in s["models"] or paths.model_files(cwd, taken):
            raise Error(
                "E_CONFLICT",
                "a model of that name is in session or in the working directory",
                {"model": taken, "fix": "choose another --name", "_untrusted": ["model"]},
            )
    before = s["models"]

    def verify(c: Client, data: dict):
        made = str(data.get("model", "")).lower()
        mass = (data.get("mass_properties") or {}).get("volume") or {}
        volume = mass.get("value") if isinstance(mass, dict) else mass
        solid = isinstance(volume, int | float) and volume > 0
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("model_in_session", made in engine.session(c)["models"]),
                engine.check(
                    "named_as_asked", made.split(".")[0] == name and made.split(".")[1] in kinds
                ),
                engine.check(
                    "holds_geometry",
                    solid or bool(data.get("components")),
                    volume=volume,
                    components=len(data.get("components") or []),
                ),
            ],
            "observations": [
                {"observation": "units", "units": data.get("units")},
                {"observation": "bbox", "bbox": data.get("bbox")},
            ],
            "not_checked": ["fidelity_to_the_source_system"],
        }

    request = {"path": str(file), "format": fmt, "name": name}
    if opts.get("type") is not None:
        request["type"] = opts["type"]
    return engine.Plan(
        op="model.import",
        request=request,
        target=name,
        binding={"file": pre["artifact"], "models": before},
        preview={
            "command": "model import",
            "imports": str(file),
            "format": fmt,
            "as": name,
            "type": opts.get("type") or "what the file holds, as Creo reads it",
            "working_directory": str(cwd),
            "effect": "a new model in session, from the file; model save writes it to the "
            "working directory",
        },
        verify=verify,
        observe=lambda c: engine.session(c)["models"],
        before=before,
        arguments={k: opts.get(k) for k in ("path", "name", "type")},
    )


def import_model(opts: dict) -> dict:
    return engine.write("model import", opts, _prepare_import, _plan_import)


# ------------------------------------------------------------------ save


def _prepare_named(opts: dict) -> dict:
    return {"name": engine.model_name(opts["model"])}


def _plan_save(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    described = engine.show(client, name)
    generic = (described.get("family") or {}).get("generic")
    if generic:
        raise Error(
            "E_VALIDATION",
            "an instance has no file of its own: it lives in its generic's family table",
            {"model": name, "generic": generic, "fix": "creo-cli model save --model " + generic},
        )
    directory = engine.store_directory(described, s)
    engine.require_workspace_models(client, s, engine.dependencies(described), "a model it uses")
    versions = paths.model_files(directory, name)

    def verify(c: Client, data: dict):
        after = paths.model_files(directory, name)
        old = {v["path"]: v for v in versions}
        new = [v for v in after if v["path"] not in old]
        checks = [
            engine.check("one_new_version_on_disk", len(new) == 1, files=[v["path"] for v in new]),
            engine.check(
                "older_versions_untouched",
                all(
                    any(a["path"] == p and a["sha256"] == v["sha256"] for a in after)
                    for p, v in old.items()
                ),
            ),
        ]
        if new:
            checks += [
                engine.check(
                    "reported_file_is_the_new_version",
                    bool(data.get("file")) and engine.same_path(data["file"], new[0]["path"]),
                ),
                engine.check(
                    "reported_size_matches_disk", data.get("file_bytes") == new[0]["size_bytes"]
                ),
            ]
        if data.get("modified") is not None:
            checks.append(engine.check("no_unsaved_changes_left", data["modified"] is False))
        return data | {"artifact": new[0] if len(new) == 1 else None}, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": ["reopen_equivalence"],
        }

    newest = max((paths.version(v["path"]) for v in versions), default=0)
    return engine.Plan(
        op="model.save",
        request={"model": name},
        target=name,
        binding={"model": described, "versions": versions, "directory": str(directory)},
        preview={
            "command": "model save",
            "model": name,
            "directory": str(directory),
            "existing_versions": [Path(v["path"]).name for v in versions],
            "next_version": f"{name}.{newest + 1}",
            "unsaved_changes": described.get("modified"),
            "note": "Creo writes a new numbered version on every save; older versions stay on disk",
        },
        verify=verify,
        observe=lambda c: [v["path"] for v in paths.model_files(directory, name)],
        before=[v["path"] for v in versions],
        persisted=True,
        arguments={"model": opts["model"]},
    )


def save(opts: dict) -> dict:
    return engine.write("model save", opts, _prepare_named, _plan_save)


def regenerate(opts: dict) -> dict:
    def prepare(values):
        return engine.model_name(values["model"], ("prt", "asm"))

    def plan(client, values, name):
        client.require_capability("model_regeneration", 1)
        s = engine.session(client)
        engine.require_in_session(s, name)
        before = engine.show(client, name)
        engine.store_directory(before, s)
        engine.require_workspace_models(
            client, s, engine.dependencies(before), "regeneration dependency"
        )

        def verify(c, _reply):
            native = c.op("dimension.list", {"model": name, "check_regeneration": True}).get(
                "regeneration_check"
            )
            if not isinstance(native, dict) or native.get("completed") is not True:
                raise Error(
                    "E_VERIFY_INCOMPLETE", "independent regeneration status scan did not complete"
                )
            actual = engine.show(c, name)
            inventory = c.op("feature.list", {"model": name, "include_internal": True})["features"]
            expected = {str(row["id"]) for row in inventory}
            observed = {str(value) for value in native.get("checked_feature_ids", [])}
            return {"model": name, "regeneration_check": native, "model_readback": actual}, {
                "level": "selected_postconditions_verified",
                "checks": [
                    engine.check("native_flags_completed", native["completed"] is True),
                    engine.check("no_failed_features", native.get("failed_features") == []),
                    engine.check(
                        "native_feature_count_covered",
                        bool(expected) and expected == observed,
                        expected_count=len(expected),
                        observed_count=len(observed),
                    ),
                ],
                "observations": [
                    {
                        "observation": "native_flags",
                        "source": native.get("source"),
                        "observed": native,
                    }
                ],
                "not_checked": ["design_intent", "saved_reopen_equivalence"],
            }

        return engine.Plan(
            op="model.regenerate",
            request={"model": name},
            target=name,
            binding=before,
            preview={"effect": "regenerate in memory and read all native flags; no save"},
            verify=verify,
            observe=lambda c: engine.show(c, name),
            before=before,
            arguments={"model": values["model"]},
        )

    return engine.write("model regenerate", opts, prepare, plan)


# ------------------------------------------------------------------ common name


def _prepare_common_name(opts: dict) -> dict:
    name = opts["name"]
    if not 1 <= len(name) <= 80 or any(ord(ch) < 32 for ch in name):
        raise Error(
            "E_VALIDATION",
            "a common name is one line of 1 to 80 characters",
            {"path": "name"},
        )
    return {"model": engine.model_name(opts["model"], ("prt", "asm")), "name": name}


def _plan_common_name(client: Client, opts: dict, pre: dict) -> engine.Plan:
    from .. import model_management

    return model_management.plan_common(client, opts, pre)


def set_common_name(opts: dict) -> dict:
    return engine.write("model set-common-name", opts, _prepare_common_name, _plan_common_name)


# ------------------------------------------------------------------ close / discard


def _plan_closing(discard: bool):
    command = "model discard" if discard else "model close"

    def plan(client: Client, opts: dict, pre: dict) -> engine.Plan:
        from .. import model_management

        if discard:
            return model_management.plan_discard(client, opts, pre)
        name = pre["name"]
        s = engine.session(client)
        engine.require_in_session(s, name)
        described = engine.show(client, name)
        directory = engine.store_directory(described, s)  # workspace only
        if type(described.get("modified")) is not bool:
            raise Error("E_VERIFY_INCOMPLETE", "modified state is unknown; close/discard refused")
        unsaved = described["modified"]
        model_management.require_saved_name_before_close(client, name, described, directory)
        if unsaved and not discard:
            raise Error(
                "E_CONFLICT",
                "the model holds unsaved changes",
                {
                    "model": name,
                    "fix": f"creo-cli model save --model {name}, or throw the changes away with "
                    "model discard",
                    "_untrusted": ["model"],
                },
            )

        before = model_management.session_state(client)
        lifecycle = False
        try:
            client.require_capability("model_close_lifecycle", 1)
            lifecycle = True
        except Error as exc:
            if exc.code != "E_BACKEND_UNAVAILABLE":
                raise
        if not lifecycle and any(window["model"] == name for window in before["windows"]):
            raise Error(
                "E_UNSUPPORTED",
                "closing a model window requires the deferred model-close lifecycle capability",
                {"dispatch_state": "not_started", "required_capability": "model_close_lifecycle 1"},
            )
        if lifecycle:
            target_windows = [window for window in before["windows"] if window["model"] == name]
            if len(target_windows) > 1:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "multiple target windows are outside the model-close lifecycle profile",
                    {"dispatch_state": "not_started", "model": name, "_untrusted": ["model"]},
                )
            if (
                target_windows
                and target_windows[0]["id"] == before.get("active_window")
                and before.get("active_model") != name
            ):
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "activate the target's complete context before closing its current window",
                    {
                        "dispatch_state": "not_started",
                        "model": name,
                        "active_window": before["active_window"],
                        "active_model": before.get("active_model"),
                        "fix": f"creo-cli display activate --model {name} --dry-run; confirm that "
                        "fresh activation, then rerun model close --dry-run",
                        "_untrusted": ["model", "active_model"],
                    },
                )
        request = {"model": name}
        if lifecycle:
            request["expected_session"] = deepcopy(before)
        checked = {}
        returned = {}
        reply_alias = None
        reply_frozen = None
        verification_attempted = False
        failure_attempted = False
        failure_alias = None
        failure_frozen = None
        last_observation = None
        last_observation_frozen = None

        def same_plan(planned, c):
            return (
                planned is p
                and c is client
                and p.op == "model.close"
                and p.target == name
                and p.before is before
                and not getattr(c, "_native_read_pending", None)
                and not getattr(c, "_native_diagnostic_stop", None)
                and all(getattr(p, key) == value for key, value in frozen.items())
            )

        def reusable(planned, c):
            return (
                same_plan(planned, c)
                and bool(checked)
                and reply_alias == reply_frozen
                and returned.get("after") == checked
            )

        def reusable_failure(planned, c):
            return (
                same_plan(planned, c)
                and failure_attempted
                and failure_frozen is not None
                and failure_alias == failure_frozen
            )

        def observe(c):
            nonlocal last_observation, last_observation_frozen
            if verification_attempted or failure_attempted:
                if reusable(p, c):
                    return deepcopy(checked)
                if reusable_failure(p, c):
                    return deepcopy(failure_frozen)
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "no complete model-close observation is bound to this Plan, Client and intent; "
                    "no additional CAD read was dispatched",
                    {"automatic_retry": False},
                )
            last_observation = last_observation_frozen = None
            after = model_management.session_state(c)
            last_observation, last_observation_frozen = after, deepcopy(after)
            return after

        def retain_failure_observation(planned, c, after):
            nonlocal failure_attempted, failure_alias, failure_frozen
            if failure_attempted:
                return False
            failure_attempted = True
            if (
                not same_plan(planned, c)
                or verification_attempted
                or after is not last_observation
                or after != last_observation_frozen
            ):
                return False
            failure_alias, failure_frozen = after, deepcopy(after)
            return True

        def verify(c: Client, data: dict):
            nonlocal verification_attempted, reply_alias, reply_frozen
            if failure_attempted:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "the model-close failure observation is already settled; "
                    "no additional CAD read was dispatched",
                    {"automatic_retry": False},
                )
            verification_attempted = True
            checked.clear()
            returned.clear()
            p.verified_observation = None
            reply_alias, reply_frozen = data, deepcopy(data)
            if (
                not same_plan(p, c)
                or not isinstance(data, dict)
                or data.get("model") != name
                or data.get("erased") is not True
            ):
                return data, {
                    "level": "service_reply_only",
                    "checks": [],
                    "not_checked": ["model_close_plan_client_intent_and_reply_binding"],
                }
            after = model_management.session_state(c)
            diagnostics = model_management.window_diagnostics(before, after, name)
            result = data | {"after": deepcopy(after), "window_diagnostics": diagnostics}
            returned.update(result)
            if not same_plan(p, c) or data != reply_frozen:
                return result, {
                    "level": "service_reply_only",
                    "checks": [],
                    "observations": [
                        {"observation": "unbound_model_close_readback", "state": deepcopy(after)}
                    ],
                    "not_checked": ["model_close_plan_client_intent_and_reply_binding"],
                }
            checked.update(deepcopy(after))
            checks = [
                engine.check(
                    "model_not_in_session", name not in [r["model"] for r in after["models"]]
                ),
                engine.check(
                    "non_target_model_metadata_unchanged",
                    [r for r in before["models"] if r["model"] != name] == after["models"],
                ),
            ] + model_management.window_checks(before, after, name)
            if reusable(p, c) and all(check["passed"] is True for check in checks):
                # The first independent post-close read already proved every selected
                # postcondition. Reuse only this Plan's complete state for accounting.
                p.verified_observation = deepcopy(after)
            return result, {
                "level": "selected_postconditions_verified",
                "checks": checks,
                "observations": [
                    {
                        "observation": "complete_model_close_session_readback",
                        "state": deepcopy(after),
                        "window_diagnostics": deepcopy(diagnostics),
                    }
                ],
                "not_checked": ["files_on_disk_untouched_by_design"],
            }

        p = engine.Plan(
            op="model.discard" if discard else "model.close",
            request=request,
            target=name,
            binding={"model": described, "models": s["models"], "session_windows": before},
            preview={
                "command": command,
                "model": name,
                "unsaved_changes": described.get("modified"),
                "effect": "closes its window and removes it from session; files on disk are not "
                "touched" + ("; unsaved changes are lost" if discard else ""),
                "lifecycle": "close window, return to Creo and verify it before erase; "
                "then return again and independently verify model absence"
                if lifecycle
                else "legacy no-window erase only; no window lifecycle qualification",
            },
            verify=verify,
            observe=observe,
            before=before,
            arguments={"model": opts["model"]},
        )
        frozen = deepcopy(
            {
                key: getattr(p, key)
                for key in ("request", "binding", "preview", "arguments", "before")
            }
        )
        p._verified_observation_guard = lambda planned, c: (
            reusable(planned, c) and p.verified_observation == checked
        )
        p._settled_observation = lambda planned, c: (
            deepcopy(checked)
            if reusable(planned, c)
            else deepcopy(failure_frozen)
            if reusable_failure(planned, c)
            else None
        )
        p._failure_observation_guard = lambda planned, c: (
            same_plan(planned, c) and not verification_attempted
        )
        p._retain_failure_observation = retain_failure_observation
        return p

    return plan


def close(opts: dict) -> dict:
    return engine.write("model close", opts, _prepare_named, _plan_closing(False))


def discard(opts: dict) -> dict:
    return engine.write("model discard", opts, _prepare_named, _plan_closing(True))


# ------------------------------------------------------------------ render

VIEWS = ("isometric", "front", "back", "top", "bottom", "left", "right", "current")


def _render_directory() -> Path:
    """Renders go into the workspace when there is one, else the user's creo-cli folder."""
    try:
        root = paths.workspace() / "renders"
    except Error:
        root = safety.directory() / "renders"
    root.mkdir(parents=True, exist_ok=True)
    return root


def render(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))
    width, height = opts["width"], opts["height"]
    if not (64 <= width <= 4000 and 64 <= height <= 4000):
        raise Error("E_VALIDATION", "width and height are 64 to 4000 pixels", {"path": "width"})
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    file = _render_directory() / f"{name.replace('.', '-')}-{opts['view']}-{stamp}.jpg"

    def fetch(client: Client) -> dict:
        data = engine.normalize(
            client.op(
                "model.render",
                {
                    "model": name,
                    "file": str(file),
                    "view": opts["view"],
                    "width": width,
                    "height": height,
                },
            )
        )
        if not file.is_file() or file.stat().st_size == 0 or file.read_bytes()[:2] != b"\xff\xd8":
            raise Error(
                "E_NATIVE_FAILURE",
                "Creo reported the picture taken, but no JPEG is where it was asked to write",
                {"path": str(file), "_untrusted": ["path"]},
            )
        return {
            "model": data["model"],
            "file": str(file),
            "format": "jpeg",
            "view": data["view"],
            "width": width,
            "height": height,
            "bytes": file.stat().st_size,
            "window_opened": data.get("window_opened"),
            "_untrusted": ["model", "file"],
        }

    return engine.read(opts, fetch)


# ------------------------------------------------------------------ export

FORMATS = {"step": ".stp", "iges": ".igs", "stl": ".stl", "pdf": ".pdf"}
# The output's extension says the format: one less flag to get wrong.
SUFFIXES = {
    ".stp": "step",
    ".step": "step",
    ".igs": "iges",
    ".iges": "iges",
    ".stl": "stl",
    ".pdf": "pdf",
}


def header_ok(fmt: str, data: bytes) -> bool:
    """The first bytes each format starts with; not a full parse."""
    if fmt == "step":
        return data.startswith(b"ISO-10303-21")
    if fmt == "pdf":
        return data.startswith(b"%PDF-")
    if fmt == "iges":
        first = data.split(b"\n", 1)[0].rstrip(b"\r")
        return len(first) >= 73 and first[72:73] == b"S"
    if len(data) < 84:
        return False
    if data[:5].lower() == b"solid" and b"facet" in data[:4096]:
        return True  # ASCII STL
    count = int.from_bytes(data[80:84], "little")
    return len(data) == 84 + 50 * count


def _prepare_export(opts: dict) -> dict:
    output = paths.contained(opts["output"], exists=False)
    fmt = SUFFIXES.get(output.suffix.lower())
    if fmt is None:
        raise Error(
            "E_VALIDATION",
            "the output's extension names the format: .stp or .step, .igs or .iges, .stl, .pdf",
            {"path": "output"},
        )
    # A bare name exported to PDF is the drawing of that name: only a drawing makes one.
    name = engine.model_name(opts["model"], ("drw",) if fmt == "pdf" else ("prt", "asm", "drw"))
    if output.exists():
        raise Error(
            "E_CONFLICT",
            "the output file exists; exports never overwrite",
            {"path": str(output), "_untrusted": ["path"]},
        )
    if not output.parent.is_dir():
        raise Error(
            "E_NOT_FOUND",
            "the output's directory does not exist in the workspace",
            {"path": str(output.parent), "_untrusted": ["path"]},
        )
    kind = name.rsplit(".", 1)[1]
    if (fmt == "pdf") != (kind == "drw"):
        raise Error(
            "E_VALIDATION",
            "pdf is for drawings; step, iges and stl are for parts and assemblies",
            {"path": "format"},
        )
    return {"name": name, "output": output, "format": fmt}


def _plan_export(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, output = pre["name"], pre["output"]
    s = engine.session(client)
    base = name.rsplit(".", 1)[0]
    if pre["format"] == "pdf" and name not in s["models"]:
        others = [m for m in s["models"] if m.rsplit(".", 1)[0] == base]
        if others:
            raise Error(
                "E_VALIDATION",
                "pdf is for drawings; step, iges and stl are for parts and assemblies",
                {
                    "path": "format",
                    "in_session": others,
                    "fix": "export the drawing of it, or the model itself to .stp, .igs or .stl",
                    "_untrusted": ["in_session"],
                },
            )
    engine.require_in_session(s, name)
    described = engine.show(client, name)
    fmt = pre["format"]
    request = {"model": name, "format": fmt, "output": str(output)}
    binding = {"model": described, "output": str(output)}
    staged, active_run = None, None

    def prepare_dispatch(run):
        nonlocal staged, active_run
        active_run = run
        staged = export_record.prepare(run, output, binding, request, FORMATS[fmt])

    def files():
        return export_record.inspect(active_run)["artifacts"] if active_run else []

    def verify(c: Client, data: dict):
        # Service paths are observations, never substitutes for the operation-owned path.
        reply_files = data.get("files", [])
        reply_owned = isinstance(reply_files, list) and all(
            isinstance(row, dict)
            and isinstance(row.get("path"), str)
            and Path(row["path"]).parent == staged.parent
            for row in reply_files
        )
        found = export_record.read_file(staged, fmt) if staged.exists() else None
        ok = bool(found and found["header_valid"])
        export_record.checkpoint(
            active_run,
            phase="generated" if found else "reply_returned_without_file",
            native_reply_returned=True,
            header_verification="passed_header_only" if ok else "failed_header_only",
            service_file_paths_within_owned_stage=reply_owned,
        )
        published = False
        if ok and reply_owned:
            export_record.checkpoint(active_run, phase="verified", verified_file=found)
            try:
                # Hard-link creation is exclusive; a competing output is never replaced.
                os.link(staged, output)
            except FileExistsError:
                export_record.checkpoint(active_run, publication_error="output_exists")
            else:
                published = True
                export_record.checkpoint(active_run, phase="published")
        known = files()
        moved = next((item for item in known if item["path"] == str(output)), None)
        return {
            "model": name,
            "format": fmt,
            "file": str(output) if moved else None,
            "bytes": moved["size_bytes"] if moved else None,
            "sha256": moved["sha256"] if moved else None,
            "generated": found is not None,
            "published": published,
            "verification_scope": "file_identity_and_header_only",
            "consumer_verification": "not_checked",
            "retained_files": known,
        }, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("file_written", found is not None),
                engine.check("service_paths_within_owned_stage", reply_owned),
                engine.check("header_is_" + fmt, ok),
                engine.check("published_without_overwriting", moved is not None),
            ],
            "not_checked": ["full_parse_of_the_file", "geometry_fidelity"],
        }

    def send():
        return {"model": name, "format": fmt, "file": str(staged)}

    return engine.Plan(
        op="model.export",
        request=request,
        send=send,
        prepare_dispatch=prepare_dispatch,
        artifacts_after=files,
        target=name,
        binding=binding,
        preview={
            "command": "model export",
            "model": name,
            "format": fmt,
            "output": str(output),
            "effect": "Creo writes the file into a private staging directory; it is checked and "
            "exclusively linked to the output, which is never overwritten; generated files "
            "are retained on failure; header checks do not prove full parse or geometry",
        },
        verify=verify,
        observe=lambda c: export_record.inspect(active_run),
        before=False,
        persisted=True,
        arguments={"model": opts["model"], "output": opts["output"]},
    )


def export(opts: dict) -> dict:
    return engine.write("model export", opts, _prepare_export, _plan_export)


# ------------------------------------------------------------------ declarations

ROW = shape(
    {"model": S, "type": S, "modified": NB, "origin": NS, "displayed": B, "active": B},
    ("model", "type"),
)
MASS_PROPERTIES = shape(
    {
        "volume": NN,
        "surface_area": NN,
        "mass": NN,
        "density": NN,
        "center_of_gravity": {"type": ["array", "null"]},
        "units": shape({}),
    },
    ("volume", "mass", "units"),
)
SHOWN = shape(
    {
        "model": S,
        "type": S,
        "units": UNITS,
        "material": NS,
        "mass_properties": MASS_PROPERTIES,
        "bbox": {"type": ["array", "object"]},
        "bodies": array(shape({})),
        "datum_planes": array(S),
        "cross_sections": array(shape({"name": S, "plane": NS}, ("name",))),
        "tolerance_standard": {"type": ["string", "null"], "enum": ["ansi", "iso", None]},
        "tolerance_class": NS,
        "explosion": ASSEMBLY_EXPLOSION,
        "family": shape(
            {
                "generic": NS,
                "instances": {"type": ["array", "null"], "items": S},
                "complete": B,
                "kind": S,
                "row_count": NI,
                "column_count": NI,
                "source": S,
                "error": shape({}),
                "empty_semantics": S,
            },
            ("generic", "instances"),
        ),
        "origin_readback": shape(
            {
                "complete": B,
                "state": S,
                "value": NS,
                "source": S,
                "error": shape({}),
                "new_model_proven": B,
            },
            ("complete", "state", "value", "source"),
        ),
        "common_name": NS,
        "common_name_readback": shape(
            {
                "readable": B,
                "value": NS,
                "modifiable": NB,
                "source": S,
                "name_error": shape({}),
                "modifiable_error": shape({}),
            },
            ("readable", "modifiable", "source"),
        ),
        "feature_count": NI,
        "components": array(shape({"id": S, "model": NS, "status": S})),
        "exploded_states": array(shape({"name": S, "active": B}, ("name", "active"))),
        "sheets": array(shape({})),
        "draft_entities": NI,
        "draft_arcs": {"type": ["array", "null"], "items": shape({})},
        "draft_entity_readback": shape(
            {
                "completed": B,
                "items": {
                    "type": ["array", "null"],
                    "items": shape(
                        {
                            "id": S,
                            "type": {"const": "line"},
                            "sheet": INT,
                            "view": S,
                            "view_id": S,
                            "background": B,
                            "complete": B,
                            "units": S,
                            "coordinate_space": {"const": "sheet_lower_left_xyz"},
                            "geometry": shape(
                                {"start": array(N), "end": array(N)}, ("start", "end")
                            ),
                            "source": S,
                        },
                        ("id", "type", "sheet", "view_id", "background", "complete", "geometry"),
                    ),
                },
                "count": NI,
                "scope": S,
                "source": S,
                "error": shape({}),
            },
            ("completed", "items", "count", "scope"),
        ),
        "views": array(shape(VIEW_NATIVE_READBACK_PROPERTIES)),
        "models": array(S),
        "origin": NS,
        "modified": NB,
    },
    ("model", "type", "origin", "modified"),
)
CLOSED = shape(
    {"model": S, "window_closed": B, "erased": B, "discarded_changes": B}, ("model", "erased")
)
SAVED = shape(
    {
        "model": S,
        "directory": S,
        "file": NS,
        "file_bytes": NI,
        "on_disk": B,
        "origin": NS,
        "modified": NB,
    },
    ("model", "directory", "file", "on_disk"),
)
COMMANDS = [
    Command(
        "model regenerate",
        "Regenerate a solid and read native flags, including embedded sketches",
        regenerate,
        written(shape({"model": S, "regeneration_check": shape({}), "model_readback": SHOWN})),
        (Param("model", required=True),),
        write=True,
        untrusted=WRITTEN,
        service_ops=("model.regenerate", "dimension.list", "model.show"),
        example="--model block",
    ),
    Command(
        "model list",
        "Models in session: type, unsaved changes, where each came from, which is active",
        list_models,
        listing(ROW),
        (LIMIT, OFFSET),
        untrusted=("items",),
        service_ops=("model.list",),
        sort="model name",
    ),
    Command(
        "model open",
        "Bring a part, assembly or drawing from the workspace into session; newest version only",
        open_model,
        written(SHOWN),
        (
            Param(
                "path",
                required=True,
                description="a model file inside the workspace: parts/block.prt opens its newest "
                "version, parts/block.prt.3 that one if it is the newest",
            ),
            Param(
                "instance",
                description="an instance of the part's family table, as File > Open asks which "
                "one; the generic is opened too unless it is in session",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--path parts/block.prt.2",
        service_ops=("model.open",),
    ),
    Command(
        "model save",
        "Save a model: Creo writes a new numbered version where it came from, keeping the old",
        save,
        written(SAVED),
        (MODEL,),
        write=True,
        untrusted=WRITTEN,
        example="--model block",
        service_ops=("model.save",),
    ),
    Command(
        "model set-common-name",
        "Set a standalone part's native common name; bind protected models/windows/files; "
        "no file rename, implicit save or associated table update",
        set_common_name,
        written(
            shape(
                {"model": S, "common_name": NS, "before": NS, "modified": NB},
                ("model", "common_name"),
            )
        ),
        (
            MODEL,
            Param(
                "name",
                required=True,
                description="nonempty common name, one line, 1..80 characters",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model leaf --name 'Hinge leaf'",
        service_ops=("model.set-common-name",),
    ),
    Command(
        "model close",
        "Close a model's window and remove it from session; refused while it holds unsaved changes",
        close,
        written(CLOSED),
        (MODEL,),
        write=True,
        untrusted=WRITTEN,
        example="--model block",
        service_ops=("model.close",),
    ),
    Command(
        "model discard",
        "Discard a standalone part's memory after a verified saved baseline; "
        "dangerous confirmation, preserved disk versions/other parts/windows; no automatic reopen",
        discard,
        written(CLOSED),
        (MODEL,),
        write=True,
        dangerous=True,
        untrusted=WRITTEN,
        example="--model block",
        service_ops=("model.discard",),
    ),
    Command(
        "model import",
        "Make a part or assembly from a STEP, IGES or Parasolid file in the workspace, under a new "
        "name -- a supplier's part to place in an assembly; model save keeps it",
        import_model,
        written(SHOWN),
        (
            Param("path", required=True, description="the exchange file, inside the workspace"),
            Param("name", required=True, description="the new model's name, without extension"),
            Param(
                "type",
                choices=("part", "assembly"),
                description="what to make; by default what the file holds, as Creo reads it",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--path vendor/motor.stp --name motor",
        service_ops=("model.import",),
    ),
    Command(
        "model show",
        "What a model holds: units, material, mass properties, bounding box, bodies, datums, "
        "feature count",
        show,
        SHOWN,
        (MODEL,),
        untrusted=tuple(CREO_TEXT),
        example="--model block",
        service_ops=("model.show",),
    ),
    Command(
        "model render",
        "A picture of a part or assembly, as a JPEG file, from a standard view; the window's "
        "own view is put back afterwards",
        render,
        shape(
            {
                "model": S,
                "file": S,
                "format": S,
                "view": S,
                "width": INT,
                "height": INT,
                "bytes": INT,
                "window_opened": NB,
            },
            ("model", "file", "view", "width", "height"),
        ),
        (
            MODEL,
            Param("view", choices=VIEWS, default="isometric", description="the view to show"),
            Param("width", "integer", default=1024, description="pixels, 64..4000"),
            Param("height", "integer", default=768, description="pixels, 64..4000"),
        ),
        untrusted=("model", "file"),
        example="--model block --view isometric",
        service_ops=("model.render",),
    ),
    Command(
        "model export",
        "Export a part or assembly as STEP, IGES or STL, or a drawing as PDF, to a new file in "
        "the workspace; nothing is overwritten; verification covers file identity and header "
        "only, not structured consumer loading, geometry or page layout",
        export,
        written(
            shape(
                {
                    "model": S,
                    "format": S,
                    "file": NS,
                    "bytes": NI,
                    "sha256": NS,
                    "generated": B,
                    "published": B,
                    "verification_scope": S,
                    "consumer_verification": S,
                    "retained_files": array(
                        shape(
                            {"path": S, "size_bytes": INT, "sha256": S},
                            ("path", "size_bytes", "sha256"),
                        )
                    ),
                },
                ("model", "format", "file"),
            )
        ),
        (
            MODEL,
            Param(
                "output",
                required=True,
                description="the new file, inside the workspace; its extension says the format: "
                ".stp, .igs, .stl, or .pdf for a drawing",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model block --output exports/block.stp",
        service_ops=("model.export",),
    ),
]
