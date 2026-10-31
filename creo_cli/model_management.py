"""Bounded standalone-part naming and explicit discard; no CAD replay during inspection."""

from copy import deepcopy
from pathlib import Path

from . import driver, engine, machining, operations, paths, safety
from .core import Error, canonical, digest


def session_state(client):
    client.require_capability("model_management_readback", 2)
    state = engine.normalize(client.op("model.management-state", {}))
    if (
        state.get("completed") is not True
        or not isinstance(state.get("models"), list)
        or not isinstance(state.get("windows"), list)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "native model/window inventory is incomplete")
    if len(state["models"]) > 16 or len(state["windows"]) > 32:
        raise Error("E_UNSUPPORTED", "model management supports at most 16 models / 32 windows")
    names, ids = set(), set()
    for row in state["models"]:
        name = row.get("model")
        if (
            not name
            or name in names
            or type(row.get("modified")) is not bool
            or row.get("dependencies_complete") is not True
            or not isinstance(row.get("dependencies"), list)
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "model identity, modified state or dependencies unavailable"
            )
        names.add(name)
    for window in state["windows"]:
        if (
            not window.get("id")
            or window["id"] in ids
            or (window.get("model") is not None and window["model"] not in names)
        ):
            raise Error("E_VERIFY_INCOMPLETE", "native window identity/ownership unavailable")
        ids.add(window["id"])
    if state.get("active_window") is not None and state["active_window"] not in ids:
        raise Error("E_VERIFY_INCOMPLETE", "active window is outside the complete inventory")
    state["models"] = sorted(state["models"], key=lambda r: r["model"])
    state["windows"] = sorted(state["windows"], key=lambda r: r["id"])
    return state


def saved_origin(row):
    """A readable native version-file identity, never the current working directory."""
    proof = row.get("origin_readback") or {}
    origin = row.get("origin")
    name = row.get("model")
    if (
        proof.get("complete") is not True
        or proof.get("state") != "saved"
        or not isinstance(origin, str)
        or not origin
        or proof.get("value") != origin
        or not proof.get("source")
        or not Path(origin).is_absolute()
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "native saved model origin is unavailable; working directory is not source proof",
            {
                "model": name,
                "origin_state": proof.get("state", "unproved"),
                "_untrusted": ["model"],
            },
        )
    filename = Path(origin).name.lower()
    suffix = (
        filename[len(name) :]
        if isinstance(name, str) and filename.startswith(name.lower())
        else None
    )
    if suffix is None or (suffix != "" and not (suffix.startswith(".") and suffix[1:].isdigit())):
        raise Error(
            "E_VERIFY_INCOMPLETE", "native origin does not identify this model's version file"
        )
    return Path(origin)


def family_identity(row):
    proof = row.get("family")
    if not isinstance(proof, dict) or proof.get("complete") is not True:
        raise Error("E_VERIFY_INCOMPLETE", "native family identity/table inventory is incomplete")
    names = proof.get("instances")
    generic, kind = proof.get("generic"), proof.get("kind")
    columns = proof.get("column_count")
    if (
        not isinstance(names, list)
        or not all(isinstance(n, str) and n for n in names)
        or len({n.lower() for n in names}) != len(names)
        or type(proof.get("row_count")) is not int
        or proof["row_count"] != len(names)
        or type(columns) is not int
        or columns < 0
        or not proof.get("source")
        or kind not in ("standalone", "generic", "instance")
        or (
            generic is not None
            and (
                not isinstance(generic, str)
                or not generic
                or generic.lower() == row["model"].lower()
            )
        )
        or (kind == "instance") != (generic is not None)
        or (kind == "standalone" and (names or columns))
        or (kind == "generic" and not (names or columns))
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "native family kind/rows/columns/generic are contradictory"
        )
    return proof


def snapshot(client, name, *, retained_files=None):
    session = session_state(client)
    names = [r["model"] for r in session["models"]]
    if retained_files is None and name not in names:
        raise Error("E_NOT_FOUND", "selected model is not in the observed session")
    details, files = {}, {}
    for row in session["models"]:
        key = row["model"]
        if row["type"] != "part":
            if name in row["dependencies"]:
                raise Error(
                    "E_CONFLICT",
                    "another open model depends on the selected part",
                    {"model": key, "dependency": name},
                )
            raise Error(
                "E_UNSUPPORTED",
                "bounded model management currently permits only standalone parts in session",
            )
        if row["dependencies"]:
            raise Error(
                "E_CONFLICT",
                "part dependencies are outside the standalone management profile",
                {"model": key, "dependencies": row["dependencies"]},
            )
        origin = saved_origin(row)
        family = family_identity(row)
        if family["kind"] != "standalone":
            raise Error(
                "E_UNSUPPORTED", "family-table models are outside the standalone management profile"
            )
        directory = paths.contained(str(origin.parent), directory=True)
        driver.scope().require(effects=["observe"], paths=[(str(directory), "observe")])
        detail = machining.snapshot(client, key)
        saved_origin(detail["model"])
        family_identity(detail["model"])
        if len(detail["features"]) > 128 or len(detail["geometry"]["items"]) > 4096:
            raise Error("E_UNSUPPORTED", "protected part exceeds management snapshot bounds")
        if (
            detail["model"].get("origin") != row.get("origin")
            or detail["model"]["family"] != family
            or detail["model"].get("modified") is not row["modified"]
        ):
            raise Error("E_VERIFY_INCOMPLETE", "model state changed across independent readers")
        for op, field in (("parameter.list", "parameters"), ("relation.list", "relations")):
            data = client.op(op, {"model": key})
            if not isinstance(data.get(field), list) or data.get("reading_failures"):
                raise Error(
                    "E_VERIFY_INCOMPLETE", "protected model parameters/relations unavailable"
                )
            detail[field] = engine.normalize(data[field])
        details[key] = detail
        files[key] = paths.model_files(directory, key, identity=True)
        if not any(engine.same_path(f["path"], str(origin)) for f in files[key]):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "native source version file is missing from the authorized inventory",
            )
    for key, old in (retained_files or {}).items():
        if key not in files:
            if not old:
                raise Error("E_VERIFY_INCOMPLETE", "retained saved-file baseline unavailable")
            directory = Path(old[-1]["path"]).parent
            driver.scope().require(effects=["observe"], paths=[(str(directory), "observe")])
            files[key] = paths.model_files(directory, key, identity=True)
    state = {
        "session": session,
        "parts": details,
        "files": files,
        "model": details.get(name, {}).get("model"),
    }
    if len(canonical(state)) > 512 * 1024:
        raise Error("E_UNSUPPORTED", "model-management snapshot exceeds 512 KiB")
    return state


def saved_baseline(client, name, before):
    files = before["files"][name]
    if not files:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "discard requires a verified saved baseline; no native model file was observed",
        )
    origin = before["model"].get("origin")
    current = next((f for f in files if origin and engine.same_path(f["path"], origin)), None)
    if current is None or current != files[-1]:
        raise Error("E_VERIFY_INCOMPLETE", "model origin does not identify the latest saved file")
    instance = client.health()["service_instance_id"]
    for run in reversed(operations.selected_runs(commands=("model save",))):
        receipt = run.get("driver_receipt") or {}
        target = (run.get("driver_plan") or {}).get("target", {})
        if (
            run.get("command") != "model save"
            or run.get("status") != "completed"
            or target.get("object_id") != name
            or target.get("instance_id") != instance
            or receipt.get("outcome", {}).get("persistence") != "saved"
            or receipt.get("outcome", {}).get("verification", {}).get("status") != "passed"
        ):
            continue
        if any(
            a.get("sha256") == current["sha256"]
            and engine.same_path(a.get("path", ""), current["path"])
            for a in receipt.get("artifacts", [])
        ):
            return {
                "save_operation_id": run["operation_id"],
                "file": current,
                "proof": "same-instance public save with independent persistence verification",
            }
    raise Error(
        "E_VERIFY_INCOMPLETE",
        "no verified public save matches this disk baseline",
        {
            "fix": "prepare a saved test baseline before making discardable edits; "
            "do not save current unwanted edits merely to pass this gate"
        },
    )


def require_saved_name_before_close(client, name, shown, directory):
    """Creo may leave modified=false after SetCommonName: retain known unsaved intent."""
    instance = client.health()["service_instance_id"]
    pending = []
    runs = operations.selected_runs(commands=("model set-common-name", "model save"))
    for run in runs:
        plan = run.get("driver_plan") or {}
        target = plan.get("target") or {}
        effect_at = run.get("finished_at") or (run.get("driver_resolution") or {}).get(
            "resolved_at"
        )
        if (
            run.get("command") != "model set-common-name"
            or target.get("instance_id") != instance
            or target.get("object_id") != name
            or not effect_at
        ):
            continue
        outcome = (run.get("driver_receipt") or {}).get("outcome") or {}
        resolution = run.get("driver_model_management_resolution") or {}
        if (
            outcome.get("change") == "not_applied"
            or resolution.get("registered_outcome") == "not_applied"
        ):
            continue
        retained = (
            plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
        )
        before = (retained.get("management_before") or {}).get("model") or {}
        intent = retained.get("management_intent") or {}
        origin = before.get("origin")
        if (
            outcome.get("persistence") in ("unsaved", "unknown")
            and intent.get("value") == shown.get("common_name")
            and (
                (origin is None and shown.get("origin") is None)
                or (origin and engine.same_path(str(Path(origin).parent), str(directory)))
            )
        ):
            pending.append(run | {"management_effect_at": effect_at})
    if not pending:
        return
    latest = max(pending, key=lambda row: row["management_effect_at"])
    driver.scope().require(effects=["observe"], paths=[(str(directory), "observe")])
    files = paths.model_files(directory, name, identity=True)
    current = next(
        (f for f in files if engine.same_path(f["path"], shown.get("origin") or "")), None
    )
    if current:
        for run in runs:
            receipt = run.get("driver_receipt") or {}
            target = (run.get("driver_plan") or {}).get("target") or {}
            if (
                run.get("command") == "model save"
                and run.get("status") == "completed"
                and (run.get("finished_at") or "") > latest["management_effect_at"]
                and target.get("object_id") == name
                and target.get("instance_id") == instance
                and receipt.get("outcome", {}).get("persistence") == "saved"
                and receipt.get("outcome", {}).get("verification", {}).get("status") == "passed"
                and any(
                    a.get("sha256") == current["sha256"]
                    and engine.same_path(a.get("path", ""), current["path"])
                    for a in receipt.get("artifacts", [])
                )
            ):
                return
    raise Error(
        "E_CONFLICT",
        "a known common-name change has no matching subsequent saved proof",
        {
            "operation_id": latest["operation_id"],
            "native_modified": shown["modified"],
            "fix": "explicitly save and verify the model, or preview bounded dangerous discard; "
            "native modified=false does not prove the name was persisted",
        },
    )


def common_state(state, name):
    result = deepcopy(state)
    model = result["parts"][name]["model"]
    for field in ("common_name", "modified"):
        model.pop(field, None)
    model.get("common_name_readback", {}).pop("value", None)
    result["model"] = deepcopy(model)
    for row in result["session"]["models"]:
        if row["model"] == name:
            row.pop("modified", None)
            row.pop("version_stamp", None)
    return result


def common_checks(before, after, name, desired):
    actual = after.get("model") or {}
    proof = actual.get("common_name_readback") or {}
    if proof.get("readable") is not True or type(proof.get("modifiable")) is not bool:
        raise Error("E_VERIFY_INCOMPLETE", "common-name native readback is unavailable")
    return [
        engine.check("native_common_name_matches", actual.get("common_name") == desired),
        engine.check(
            "geometry_properties_parameters_other_models_windows_files_unchanged",
            digest(common_state(before, name)) == digest(common_state(after, name)),
        ),
    ]


def close_checks(before, after, name):
    old, new = before["session"], after["session"]
    checks = [
        engine.check("target_absent", name not in after["parts"]),
        engine.check("all_saved_versions_unchanged", before["files"] == after["files"]),
        engine.check(
            "other_models_full_state_unchanged",
            {k: v for k, v in before["parts"].items() if k != name} == after["parts"],
        ),
        engine.check(
            "other_model_identity_modified_dependencies_unchanged",
            [r for r in old["models"] if r["model"] != name] == new["models"],
        ),
    ]
    return checks + window_checks(old, new, name)


def window_diagnostics(old, new, name):
    """Describe observed window differences without changing the close policy."""
    old_other = [w for w in old["windows"] if w["model"] != name]
    affected = {w["id"] for w in old["windows"] if w["model"] == name}
    new_other = [w for w in new["windows"] if w["id"] not in affected]
    residual = [w for w in new["windows"] if w["id"] in affected]
    before_by_id = {w["id"]: w for w in old_other}
    after_by_id = {w["id"]: w for w in new_other}
    differences = []
    for identity in sorted(before_by_id.keys() | after_by_id.keys()):
        expected, actual = before_by_id.get(identity), after_by_id.get(identity)
        if expected != actual:
            differences.append(
                {
                    "window_id": identity,
                    "category": "added"
                    if expected is None
                    else "removed"
                    if actual is None
                    else "model_attachment_changed",
                    "expected": deepcopy(expected),
                    "actual": deepcopy(actual),
                }
            )
    return {
        "target_model": name,
        "target_window_ids_before": sorted(affected),
        "expected_non_target_windows": deepcopy(old_other),
        "actual_non_target_windows": deepcopy(new_other),
        "target_window_residuals": deepcopy(residual),
        "differences": differences,
        "active_before": {"id": old["active_window"], "model": old["active_model"]},
        "active_after": {"id": new["active_window"], "model": new["active_model"]},
        "identity_policy": "exact window IDs and model attachments; no inferred rehoming",
    }


def window_checks(old, new, name):
    evidence = window_diagnostics(old, new, name)
    old_other = evidence["expected_non_target_windows"]
    new_other = evidence["actual_non_target_windows"]
    residual = evidence["target_window_residuals"]
    return [
        engine.check(
            "other_window_identities_unchanged",
            old_other == new_other,
            expected=deepcopy(old_other),
            actual=deepcopy(new_other),
            differences=deepcopy(evidence["differences"]),
        ),
        engine.check(
            "removed_target_window_or_empty_base",
            all(w["model"] is None for w in residual),
            affected_window_ids=deepcopy(evidence["target_window_ids_before"]),
            actual_residuals=deepcopy(residual),
        ),
        engine.check(
            "non_target_active_window_preserved",
            old["active_model"] == name or old["active_window"] == new["active_window"],
            before=deepcopy(evidence["active_before"]),
            after=deepcopy(evidence["active_after"]),
        ),
    ]


def confirm_baseline(opts, before):
    if not opts.get("confirm"):
        return
    run = operations.get(safety.token_operation(opts["confirm"]))
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    if digest(retained.get("management_before")) != digest(before):
        raise Error(
            "E_CONFLICT",
            "model, window or file baseline changed since preview",
            {"conflict": "state_drift", "dispatch_state": "not_started"},
        )


def plan_common(client, opts, pre):
    name, desired = pre["model"], pre["name"]
    before = snapshot(client, name)
    confirm_baseline(opts, before)
    proof = before["model"].get("common_name_readback") or {}
    if proof.get("readable") is not True or type(proof.get("modifiable")) is not bool:
        raise Error(
            "E_VERIFY_INCOMPLETE", "common-name value or IsCommonNameModifiable could not be read"
        )
    if not proof["modifiable"]:
        raise Error("E_CONFLICT", "native common name is not modifiable")

    def verify(c, data):
        after = snapshot(c, name)
        checks = common_checks(before, after, name, desired)
        if all(x["passed"] for x in checks):
            planned.verified_observation = deepcopy(after)
        return data | {"readback": after["model"]}, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": ["BOM/title-block attribute associations", "save/reopen equivalence"],
        }

    planned = engine.Plan(
        op="model.set-common-name",
        target=name,
        request={"model": name, "name": desired},
        binding={
            "management_before": before,
            "management_intent": {"kind": "common_name", "model": name, "value": desired},
        },
        preview={
            "command": "model set-common-name",
            "model": name,
            "from": before["model"].get("common_name"),
            "to": desired,
            "effect": "change the native model common name; filename/identity and parameters "
            "are separate; no save or table update",
            "model_footprint": list(before["parts"]),
            "scope_paths": scope_paths(before, name),
        },
        verify=verify,
        observe=lambda c: snapshot(c, name),
        before=before,
        arguments={"model": opts["model"], "name": desired},
    )
    return planned


def scope_paths(state, name):
    return [
        (str(Path(v[0]["path"]).parent), "change" if k == name else "observe")
        for k, v in state["files"].items()
        if v
    ]


def plan_discard(client, opts, pre):
    name = pre["name"]
    before = snapshot(client, name)
    confirm_baseline(opts, before)
    baseline = saved_baseline(client, name, before)

    def observe(c):
        return snapshot(c, name, retained_files=before["files"])

    def verify(c, data):
        after = observe(c)
        checks = close_checks(before, after, name)
        if all(x["passed"] for x in checks):
            planned.verified_observation = deepcopy(after)
        return data | {"readback": after, "disk_baseline": baseline}, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": [
                "reopen baseline: use a separate explicit model open",
                "camera restoration",
            ],
        }

    planned = engine.Plan(
        op="model.discard",
        target=name,
        request={"model": name},
        binding={
            "management_before": before,
            "management_intent": {"kind": "discard", "model": name, "disk_baseline": baseline},
        },
        preview={
            "command": "model discard",
            "model": name,
            "unsaved_changes": before["model"]["modified"],
            "disk_baseline": baseline,
            "windows": before["session"]["windows"],
            "effect": "irreversibly discard selected part memory and remove it from session; "
            "preserve every disk version and other model/window identity",
            "constraints": [
                "standalone saved parts only; explicit dangerous confirmation",
                "active target window may switch to an existing window or empty base window; "
                "no automatic reopen",
            ],
            "model_footprint": list(before["parts"]),
            "scope_paths": scope_paths(before, name),
        },
        verify=verify,
        observe=observe,
        before=before,
        arguments={"model": opts["model"]},
    )
    return planned


def retained_state_complete(state):
    if not isinstance(state, dict) or not isinstance(state.get("session", {}).get("models"), list):
        raise Error("E_VERIFY_INCOMPLETE", "retained management model inventory is unavailable")
    rows = state["session"]["models"]
    if {r.get("model") for r in rows} != set(state.get("parts", {})):
        raise Error("E_VERIFY_INCOMPLETE", "retained protected-model inventory is contradictory")
    for row in rows:
        origin = saved_origin(row)
        family = family_identity(row)
        part = state["parts"][row["model"]]["model"]
        if (
            saved_origin(part) != origin
            or family_identity(part) != family
            or family["kind"] != "standalone"
        ):
            raise Error("E_VERIFY_INCOMPLETE", "retained source/family readers disagree")
        if not any(
            engine.same_path(f["path"], str(origin))
            for f in state.get("files", {}).get(row["model"], [])
        ):
            raise Error("E_VERIFY_INCOMPLETE", "retained saved source file identity is unavailable")


def retained_evidence_sufficient(run, proof):
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, intent = retained.get("management_before"), retained.get("management_intent")
    retained_state_complete(before)
    retained_state_complete(proof.get("current"))
    if proof.get("intent") != intent:
        raise Error("E_VERIFY_INCOMPLETE", "retained management intent differs from registration")


def recovery(client, run):
    plan = run["driver_plan"]
    retained = plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
    before, intent = retained.get("management_before"), retained.get("management_intent")
    if not before or not intent:
        raise Error("E_VERIFY_INCOMPLETE", "retained management baseline/intent unavailable")
    retained_state_complete(before)
    if client.health()["service_instance_id"] != plan["target"]["instance_id"]:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "another instance cannot establish the old model management outcome",
        )
    name = intent["model"]
    after = snapshot(client, name, retained_files=before["files"])
    second = snapshot(client, name, retained_files=before["files"])
    stable = digest(after) == digest(second)
    if intent["kind"] == "common_name":
        checks = common_checks(before, after, name, intent["value"])
    else:
        baseline = intent.get("disk_baseline", {})
        if not baseline.get("save_operation_id") or not baseline.get("file"):
            raise Error("E_VERIFY_INCOMPLETE", "discard saved baseline was not retained")
        checks = close_checks(before, after, name)
    checks.append(engine.check("independent_observation_stable", stable))
    accepted = all(c["passed"] for c in checks)
    return {
        "accepted": accepted,
        "checks": checks,
        "current": after,
        "intent": intent,
        "can_register": []
        if not stable
        else ["not_applied"]
        if digest(after) == digest(before)
        else ["applied"]
        if accepted
        else ["partial"],
        "coverage": "retained intent, full bounded part state, windows, other models and "
        "all saved-file versions; no replay",
    }
