"""Observed property transitions inside the existing sequential workflow lifecycle."""

from copy import deepcopy

from . import engine
from .core import Error, digest

WRITES = {"material assign", "model set-tolerance-standard", "dimension set-tolerance"}
NUMERIC = {"plus_minus", "symmetric", "limits"}


def models(steps):
    return {
        engine.model_name(step["args"]["model"], ("prt", "asm"))
        for step in steps
        if step.get("kind") == "write" and step.get("command") in WRITES
    }


def require_supported(steps, names):
    """No assumed geometry-to-property transition for the newly composed profile."""
    if not names:
        return
    allowed = WRITES | {"model regenerate", "model save", "artifact export"}
    for step in steps:
        command = step.get("command", "")
        if step["kind"] != "write" or command in allowed or command.startswith("drawing "):
            continue
        raise Error(
            "E_UNSUPPORTED",
            "property workflows currently combine property changes, regeneration, save, "
            "drawing edits and export; geometry-edit transitions are not verified",
            {"step": step["id"], "command": command, "dispatch_state": "not_started"},
        )


def project(state):
    """Keep independently readable engineering fields, excluding save/view bookkeeping."""
    model = state.get("model") or {}
    dimensions = (state.get("dimensions") or {}).get("dimensions")
    if (
        not isinstance(dimensions, list)
        or not model.get("model")
        or state["dimensions"].get("model") != model["model"]
        or state["dimensions"].get("reading_failures")
        or any(not isinstance(d, dict) or not d.get("id") or d.get("error") for d in dimensions)
        or len({d["id"] for d in dimensions}) != len(dimensions)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "workflow engineering property state is incomplete")
    if any(
        not d.get("reference") and not (d.get("tolerance") or {}).get("type") for d in dimensions
    ):
        raise Error("E_VERIFY_INCOMPLETE", "workflow tolerance state cannot be independently read")
    return {
        "model": {
            k: model.get(k)
            for k in (
                "model",
                "type",
                "units",
                "material",
                "mass_properties",
                "tolerance_standard",
                "tolerance_class",
                "bbox",
            )
        },
        "dimensions": [
            {
                k: d.get(k)
                for k in (
                    "id",
                    "name",
                    "value",
                    "units",
                    "type",
                    "reference",
                    "tolerance",
                    "numeric_tolerance_table",
                )
            }
            for d in dimensions
        ],
    }


def observe(client, names, materials):
    # Refresh material discovery first; never reuse a pre-refresh model sample.
    configuration = {}
    for name in sorted(materials):
        value = client.op("material.list", {"name": "~", "model": name}).get("configuration")
        if (
            not isinstance(value, dict)
            or not value.get("effective_library")
            or not value.get("working_directory")
        ):
            raise Error("E_VERIFY_INCOMPLETE", "workflow material configuration is unreadable")
        configuration[name] = {k: value[k] for k in ("effective_library", "working_directory")}
    observations = {
        name: project(
            {
                "model": engine.show(client, name),
                "dimensions": engine.normalize(client.op("dimension.list", {"model": name})),
            }
        )
        for name in sorted(names)
    }
    return {"models": observations, "material_configuration": configuration}


def require_state(expected, observed):
    if digest(expected) != digest(observed):
        raise Error(
            "E_CONFLICT",
            "workflow engineering properties changed outside a verified predecessor",
            {
                "conflict": "state_drift",
                "dispatch_state": "not_started",
                "expected_sha256": digest(expected),
                "observed_sha256": digest(observed),
            },
        )


def require_intent(frozen, plan):
    """Replanning may observe authorized state changes, not choose a new material input."""
    if frozen["command"] not in WRITES:
        return
    if plan.request != frozen["request"]:
        raise Error(
            "E_CONFLICT",
            "workflow property request no longer matches its confirmed intent",
            {"conflict": "state_drift", "step": frozen["id"], "dispatch_state": "not_started"},
        )
    if frozen["command"] == "material assign" and plan.binding.get("source") != frozen[
        "binding"
    ].get("source"):
        raise Error(
            "E_CONFLICT",
            "workflow material source no longer matches its confirmed identity and bytes",
            {"conflict": "state_drift", "step": frozen["id"], "dispatch_state": "not_started"},
        )


def advance(expected, observed, command, receipt):
    """Advance only from the successful leaf's retained independent observation."""
    allowed = deepcopy(expected)
    if command in WRITES:
        if receipt["outcome"]["verification"]["status"] != "passed":
            raise Error(
                "E_VERIFY_INCOMPLETE", "property predecessor was not independently verified"
            )
        after = verified_after(receipt)
        name = receipt["target"]["object_id"]
        if name not in allowed["models"] or after.get("model", {}).get("model") != name:
            raise Error("E_VERIFY_INCOMPLETE", "property predecessor readback has the wrong model")
        allowed["models"][name] = project(after)
    require_state(allowed, observed)
    return allowed


def verified_after(receipt):
    """Use the snapshot checked by the verifier, not a later unverified resampling."""
    proof = receipt["outcome"]["verification"].get("extensions", {}).get("creo", {})
    rows = [
        row
        for row in proof.get("observations", [])
        if row.get("observation") == "independent_engineering_properties"
        and row.get("independent") is True
        and isinstance(row.get("observed"), dict)
    ]
    if len(rows) != 1:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "property predecessor has no unique verified engineering snapshot",
        )
    return rows[0]["observed"]


def standard_precondition(step, plan):
    """A future condition, never evidence that the native transition already happened."""
    return {
        "step_id": step["id"],
        "model": plan.target,
        "standard": plan.request["standard"],
        "class": plan.request.get("class"),
        "numeric_overrides": deepcopy(plan.preview["numeric_overrides_preserved"]),
    }


def require_predecessor(prerequisite, workflow, observed):
    if not prerequisite:
        return
    row = next((r for r in workflow["steps"] if r["id"] == prerequisite["step_id"]), None)
    receipt = (row or {}).get("receipt")
    if (
        not row
        or row["status"] != "completed"
        or not receipt
        or receipt["outcome"]["verification"]["status"] != "passed"
        or receipt["target"]["object_id"] != prerequisite["model"]
    ):
        raise Error("E_VERIFY_INCOMPLETE", "required standard predecessor has not completed")
    readback = receipt.get("extensions", {}).get("creo", {}).get("effects_readback", {})
    if not isinstance(readback.get("before"), dict) or not isinstance(readback.get("after"), dict):
        raise Error("E_VERIFY_INCOMPLETE", "standard predecessor's preserved snapshots are absent")
    state = project(verified_after(receipt))
    before = project(readback["before"])
    current_model = observed["models"][prerequisite["model"]]["model"]
    dimensions = {d["id"]: d for d in state["dimensions"]}
    valid = (
        state["model"]["tolerance_standard"]
        == current_model["tolerance_standard"]
        == prerequisite["standard"]
    )
    if prerequisite.get("class"):
        valid = (
            valid
            and state["model"]["tolerance_class"]
            == current_model["tolerance_class"]
            == prerequisite["class"]
        )
    for old in before["dimensions"]:
        if (old.get("tolerance") or {}).get("type") not in NUMERIC:
            continue
        current = dimensions.get(old["id"], {})
        table = current.get("numeric_tolerance_table") or {}
        valid = (
            valid
            and current.get("tolerance") == old.get("tolerance")
            and table.get("complete") is True
            and table.get("assigned") is False
        )
    if not valid:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "standard predecessor did not preserve the required numeric tolerances "
            "and detach their tables",
            {"step": prerequisite["step_id"], "model": prerequisite["model"]},
        )
