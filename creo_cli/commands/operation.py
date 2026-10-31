"""Original receipts, separate current observations and explicit manual resolution."""

from __future__ import annotations

from .. import driver, engine, native_read_recovery, operations, safety
from ..core import Error, digest, page
from ..registry import LIMIT, OFFSET, Command, Param
from ..schemas import NS, S, listing, shape
from ..transport import Client


def list_runs(opts: dict) -> dict:
    runs = operations.all_runs()
    if opts.get("status"):
        runs = [r for r in runs if r["status"] == opts["status"]]
    return page(runs, opts["limit"], opts["offset"]) | {"_untrusted": ["items"]}


def show(opts: dict) -> dict:
    run = operations.get(opts["id"])
    if run.get("driver_plan"):
        return {
            "operation_status": driver.status(run),
            "recovery_guidance": operations.recovery_guidance(run),
        }
    return {
        "receipt": run,
        "result": operations.load_result(run),
        "recovery_guidance": operations.recovery_guidance(run),
        "_untrusted": ["receipt", "result"],
    }


def query(opts: dict) -> dict:
    try:
        return _query(opts)
    except Error as exc:
        operations.retain_pending_inspection(operations.get(opts["id"]), exc, "operation query")
        raise


def _query(opts: dict) -> dict:
    run = operations.get(opts["id"])
    if run["command"] == "service install":
        from .. import service_installation

        if opts.get("model"):
            raise Error(
                "E_VALIDATION", "an installation operation has a file target, not a CAD model"
            )
        if run.get("driver_plan"):
            driver.scope().require(effects=["observe"], target=run["driver_plan"]["target"])
        observation = {
            "installation_verification": service_installation.inspect(run),
            "source": "retained installation ownership and fresh file identities/hashes",
            "coverage": "component files only; no Creo connection or loading proof",
        }
        return operations.save_query(run, observation) | {"_untrusted": ["observation"]}
    if not opts.get("model"):
        raise Error("E_USAGE", "model-targeted operation query requires --model")
    name = engine.model_name(opts["model"], ("prt", "asm", "drw"))
    target = str(run.get("target", ""))
    # An explicit model is required; a target path or session-wide operation is not guessed.
    if target not in (name, name.rsplit(".", 1)[0]):
        raise Error(
            "E_VALIDATION",
            "this receipt target cannot be queried as that model",
            {"receipt_target": target, "requested_model": name},
        )
    if run.get("driver_plan"):
        driver.scope().require(
            effects=["observe"],
            target=run["driver_plan"]["target"],
            paths=[
                (path, "observe")
                for path, _ in (run.get("driver_binding") or {}).get("driver_paths", [])
            ],
        )
    if run["command"] in ("model export", "artifact export") and run.get("driver_plan"):
        from .. import export_record

        retained = run.get("driver_export") or {}
        driver.scope().require(
            effects=["observe"],
            target=run["driver_plan"]["target"],
            paths=[
                (retained[key], "observe")
                for key in ("staged_path", "requested_output")
                if retained.get(key)
            ],
        )
        observation = {
            "export_verification": export_record.inspect(run),
            "source": "retained export ownership and fresh exact-path file identities/headers",
            "coverage": "files only; no CAD call, native completion, replay or consumer proof",
        }
        return operations.save_query(run, observation) | {"_untrusted": ["observation"]}
    with Client(opts.get("timeout", 30)) as client:
        health = client.health()
        if run["command"] == "assembly component redefine" and run.get("driver_plan"):
            from .. import assembly_constraints

            return operations.save_query(
                run,
                {
                    "assembly_constraints_verification": assembly_constraints.recovery(client, run),
                    "source": "fresh independent occurrence constraints, solved poses "
                    "and retained constituent protection",
                    "coverage": "frozen direct-occurrence constraint intent; "
                    "no mutation, replay, rollback or inferred save",
                    "health": health,
                },
            ) | {"_untrusted": ["observation"]}
        if run["command"] == "drawing note add" and run.get("driver_plan"):
            from .. import drawing_note_recovery

            return operations.save_query(
                run,
                {
                    "simple_note_verification": drawing_note_recovery.recovery(client, run),
                    "source": "fresh independent note membership, text, anchor "
                    "and retained protected resources",
                    "coverage": "frozen single-sheet literal free-note policy; "
                    "no native mutation or replay; bounds/layout separate",
                    "health": health,
                },
            ) | {"_untrusted": ["observation"]}
        if run["command"] in ("family-table apply", "family-table remove-instance") and run.get(
            "driver_plan"
        ):
            from .. import family_runtime

            observation = {
                "family_table_verification": family_runtime.recovery(client, run),
                "source": "fresh family and protected native states against retained intent",
                "coverage": "bounded family table; no replay, instantiation or automatic cleanup",
                "health": health,
            }
            return operations.save_query(run, observation) | {"_untrusted": ["observation"]}
        if run["command"] in ("model set-common-name", "model discard") and run.get("driver_plan"):
            from .. import model_management

            observation = {
                "model_management_verification": model_management.recovery(client, run),
                "source": "fresh complete native model/window/files observation "
                "against retained intent",
                "coverage": "bounded model management; no native mutation or automatic reopen",
                "health": health,
            }
            return operations.save_query(run, observation) | {"_untrusted": ["observation"]}
        snapshot = engine.normalize(client.op("model.show", {"model": name}))
        if snapshot.get("model") != name:
            raise Error(
                "E_VERIFY_INCOMPLETE", "model query did not identify the actual receipt target"
            )
        observation = {
            "model": snapshot,
            "source": "fresh model.show getters",
            "health": health,
            "endpoint": client.url,
            "coverage": (
                "model snapshot; original requested postconditions are not "
                "reconstructed from a hash"
            ),
        }
        if not name.endswith(".drw"):
            observation["features"] = engine.normalize(client.op("feature.list", {"model": name}))
            observation["dimensions"] = engine.normalize(
                client.op("dimension.list", {"model": name, "check_regeneration": False})
            )
        if run["command"] in ("feature hole", "feature round") and run.get("driver_plan"):
            from .. import machining

            observation["machining_verification"] = machining.recovery(client, run)
            observation["coverage"] = (
                "retained bounded machining intent checked against fresh current solid; "
                "original receipt is not settled"
            )
        if run["command"] in (
            "feature revolve",
            "feature datum-plane",
            "feature datum-axis",
        ) and run.get("driver_plan"):
            from .. import revolved

            observation["construction_verification"] = revolved.recovery(client, run)
            observation["coverage"] = (
                "retained bounded construction intent and fresh native geometry; "
                "original receipt is not settled"
            )
        if run["command"] == "drawing view remove" and run.get("driver_plan"):
            from .. import drawing_views

            observation["view_removal_verification"] = drawing_views.recovery(client, run)
            observation["coverage"] = (
                "retained view deletion intent and fresh complete supported "
                "resources/source geometry; original receipt not settled"
            )
        if run["command"] == "feature shell" and run.get("driver_plan"):
            from .. import prismatic

            observation["prismatic_verification"] = prismatic.recovery(client, run)
            observation["coverage"] = (
                "frozen shell intent and complete current planar body; no native replay"
            )
        if run["command"] == "feature draft" and run.get("driver_plan"):
            from .. import prismatic_draft

            observation["draft_verification"] = prismatic_draft.recovery(client, run)
            observation["coverage"] = (
                "frozen draft references and complete current planar boundary; no replay"
            )
        if run["command"] == "feature rib" and run.get("driver_plan"):
            from .. import prismatic_rib

            observation["prismatic_rib_verification"] = prismatic_rib.recovery(client, run)
            observation["coverage"] = (
                "frozen original/resolved rib decisions, native section and complete "
                "housing union; no replay"
            )
    return operations.save_query(run, observation) | {"_untrusted": ["observation"]}


def resolve(opts: dict) -> dict:
    if operations.get(opts["id"]).get("driver_plan"):
        return driver.resolve(opts)
    if not opts.get("note") or not opts.get("decision"):
        raise Error("E_VALIDATION", "legacy operation requires --note and --decision")
    note = opts["note"].strip()
    if not 10 <= len(note) <= 1000:
        raise Error(
            "E_VALIDATION",
            "resolution note states the inspection and accepted consequences:10..1000 characters",
        )
    decision = opts["decision"]
    with safety.lock():
        run = operations.get(opts["id"])
        if run["status"] not in operations.UNRESOLVED:
            raise Error("E_CONFLICT", "receipt is already settled", {"status": run["status"]})
        evidence = operations.load_query(opts["evidence"]) if opts.get("evidence") else None
        failed_read = (evidence or {}).get("observation", {})
        if failed_read.get("read_status") == "pending" and failed_read.get("complete") is False:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "a failed native inspection cannot support evidence registration",
                {"parent_operation_id": run["operation_id"]}
                | native_read_recovery.details(native_read_recovery.pending_error(failed_read)),
            )
        if decision == "accept-observation" and evidence is None:
            raise Error(
                "E_VALIDATION", "accept-observation requires --evidence from operation query"
            )
        if evidence and (
            evidence["operation_id"] != run["operation_id"]
            or evidence["receipt_sha256"] != digest(run)
        ):
            raise Error("E_CONFLICT", "query evidence belongs to a different or changed receipt")
        args = {"decision": decision, "note": note, "evidence": opts.get("evidence")}
        bound = safety.scope("operation resolve", run["operation_id"], args, digest(run))
        if opts.get("dry_run"):
            token, expires = safety.issue(bound)
            return {
                "preview": {
                    "command": "operation resolve",
                    "receipt": run,
                    "decision": decision,
                    "evidence": opts.get("evidence"),
                    "note": note,
                    "effect": (
                        "record manual acceptance and unblock later writes; no retry, "
                        "rollback or model mutation"
                    ),
                    "original_postconditions_verified": False,
                    "policy": safety.policy(),
                },
                "confirm_token": token,
                "expires_at": expires,
                "_untrusted": ["preview"],
            }
        safety.require_write()
        safety.consume(opts.get("confirm"), bound)
        run["status_before_resolution"] = run["status"]
        run["status"] = "resolved_manual"
        run["resolution"] = args | {
            "at": operations.now(),
            "original_postconditions_verified": False,
        }
        operations.update(run)
        saved = operations.get(run["operation_id"])
        return {
            "operation_id": run["operation_id"],
            "status": "completed",
            "result": {"receipt": saved},
            "verification": {
                "level": "selected_postconditions_verified",
                "checks": [{"check": "receipt_resolution_saved", "passed": saved == run}],
                "not_checked": ["original_write_postconditions", "current_model_state"],
                "scope": "receipt_only",
            },
            "persisted": True,
            "_untrusted": ["result"],
        }


RECEIPT = shape(
    {"operation_id": S, "at": S, "command": S, "target": S, "status": S, "error_code": NS},
    ("operation_id", "at", "command", "status"),
)
COMMANDS = [
    Command(
        "operation list",
        "Receipts of writes, newest first; unresolved public records block conflicting targets; "
        "legacy paths retain the global gate",
        list_runs,
        listing(RECEIPT),
        (
            Param("status", choices=operations.STATUSES, description="only receipts in this state"),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items",),
        sort="newest first",
    ),
    Command(
        "operation show",
        "Read one local receipt, its recorded result and conditional recovery guidance; "
        "does not contact CAD or prove that an unrecorded native getter ended",
        show,
        shape(
            {
                "receipt": RECEIPT,
                "result": {"type": ["object", "null"]},
                "operation_status": shape({}),
                "recovery_guidance": shape({}),
            }
        ),
        (Param("id", required=True, description="the operation_id a write returned"),),
        untrusted=("receipt", "result"),
        example="--id <operation_id>",
    ),
    Command(
        "operation resolve",
        (
            "Explicitly accept an inspected state, preserving uncertainty "
            "in the original receipt; bounded hole/round results require fresh solid checks; "
            "CAD inspection requires any pending original read and instance state to be "
            "independently settled first, including before --dry-run; no retry or rollback"
        ),
        resolve,
        shape({"operation_status": shape({}), "receipt": shape({}), "result": shape({})}),
        (
            Param("id", required=True, description="the unresolved operation_id"),
            Param(
                "outcome",
                choices=("applied", "not_applied", "partial"),
                description="inspected outcome for driver operations",
            ),
            Param("note", description="inspection note for legacy operations"),
            Param(
                "decision",
                choices=("manual-accept", "accept-observation"),
                description="legacy resolution path",
            ),
            Param(
                "evidence",
                description="inspection text; legacy path accepts query evidence_id",
            ),
        ),
        write=True,
        untrusted=("result",),
        example=(
            '--id <operation_id> --outcome partial --evidence "Independent model and '
            'saved-file inspection proves only the documented first step applied" --dry-run'
        ),
        service_ops=(
            "model.show",
            "feature.list",
            "feature.show",
            "dimension.list",
            "geometry.list",
        ),
    ),
    Command(
        "operation query",
        (
            "Independently inspect a model, retained installation or owned export files now and "
            "store hashed observations; does not settle its original "
            "postconditions or cancel a pending getter. CAD inspection requires any pending "
            "original read and instance state to be independently settled first. New export "
            "records inspect only scope-authorized files, never CAD or consumer geometry; bounded "
            "hole/round intent also checks current solid geometry"
        ),
        query,
        shape({"evidence_id": S, "observation": shape({})}),
        (
            Param("id", required=True),
            Param(
                "model",
                description="required for model targets, including file-only export queries; "
                "omit for service installation",
            ),
        ),
        service_ops=(
            "model.show",
            "feature.list",
            "feature.show",
            "dimension.list",
            "geometry.list",
        ),
        untrusted=("observation",),
        example="--id <operation_id> --model block",
    ),
]
