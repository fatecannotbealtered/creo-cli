"""Typed task execution. References select prior observations, never executable expressions."""

from __future__ import annotations

import math
import re
import time
from copy import deepcopy

from . import engine, native_diagnostic_recovery, native_read_recovery, operations, safety, timing
from .core import Error, digest
from .transport import Client


def _refs(value):
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise Error("E_VALIDATION", "a reference contains only a string $ref")
            yield value["$ref"]
        else:
            for child in value.values():
                yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _get(data, path):
    for part in path.split("."):
        try:
            data = data[int(part)] if isinstance(data, list) else data[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise Error(
                "E_NOT_FOUND", "reference path is absent in the actual observation", {"path": path}
            ) from exc
    return data


def _resolve(value, outputs):
    if isinstance(value, dict):
        if "$ref" in value:
            return deepcopy(_get(outputs, value["$ref"]))
        return {key: _resolve(child, outputs) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve(child, outputs) for child in value]
    return value


def compile_task(q):
    from .commands.workflow import EXCLUDED, MAX_STEPS, _options
    from .registry import BY_PATH

    if (
        not isinstance(q, dict)
        or set(q) != {"steps"}
        or not isinstance(q["steps"], list)
        or not 1 <= len(q["steps"]) <= MAX_STEPS
    ):
        raise Error("E_VALIDATION", "a task contains 1..32 ordered steps")
    steps, seen, provenance = [], set(), {}
    for index, raw in enumerate(q["steps"]):
        if not isinstance(raw, dict):
            raise Error("E_VALIDATION", "step must be an object", {"step": index + 1})
        s = deepcopy(raw)
        ident = s.setdefault("id", f"s{index + 1}")
        kind = s.setdefault("kind", "write")
        if (
            not isinstance(ident, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", ident)
            or ident in seen
        ):
            raise Error("E_VALIDATION", "step ids must be unique identifiers", {"step": index + 1})
        allowed = {"id", "kind", "depends_on"}
        if kind in ("read", "write"):
            allowed |= {"command", "args"}
            command = BY_PATH.get(s.get("command"))
            if (
                command is None
                or command.write != (kind == "write")
                or command.dangerous
                or command.path in EXCLUDED
                or command.path.startswith(("workflow ", "operation ", "service "))
            ):
                raise Error(
                    "E_VALIDATION",
                    "task command is not eligible for this step kind",
                    {"step": ident},
                )
            args = s.get("args", {})
            if not isinstance(args, dict):
                raise Error("E_VALIDATION", "step args must be an object")
            params = {p.name for p in command.params}
            if set(args) - params or any(p.required and p.name not in args for p in command.params):
                raise Error(
                    "E_VALIDATION", "step arguments do not match the command", {"step": ident}
                )
            if not list(_refs(args)):
                _options(command, args, index)
            provenance[ident] = "observation" if kind == "read" else "write_result"
        elif kind == "select":
            allowed |= {"from", "where", "expect_count"}
            if (
                not isinstance(s.get("from"), dict)
                or "$ref" not in s["from"]
                or not isinstance(s.get("where", {}), dict)
                or s.get("expect_count", 1) != 1
            ):
                raise Error(
                    "E_VALIDATION",
                    (
                        "select requires a prior list reference, an equality "
                        "predicate and expect_count=1"
                    ),
                )
            provenance[ident] = "observation"
        elif kind == "assert":
            allowed |= {"actual", "expected", "tolerance"}
            if (
                not isinstance(s.get("actual"), dict)
                or "$ref" not in s["actual"]
                or "expected" not in s
            ):
                raise Error(
                    "E_VALIDATION", "assert actual must reference a prior read or selection"
                )
            tol = s.get("tolerance")
            if tol is not None and (
                isinstance(tol, bool)
                or not isinstance(tol, (int, float))
                or not math.isfinite(tol)
                or tol < 0
            ):
                raise Error("E_VALIDATION", "assert tolerance must be finite and nonnegative")
            provenance[ident] = "assertion"
        else:
            raise Error("E_VALIDATION", "step kind is read, select, assert or write")
        if set(s) - allowed:
            raise Error(
                "E_VALIDATION",
                "unknown step fields",
                {"step": ident, "fields": sorted(set(s) - allowed)},
            )
        deps = s.get("depends_on", [])
        if not isinstance(deps, list) or any(dep not in seen for dep in deps):
            raise Error("E_VALIDATION", "dependencies must name prior steps", {"step": ident})
        for ref in _refs(s):
            if ref.split(".")[0] not in seen:
                raise Error(
                    "E_VALIDATION",
                    "references must name prior steps",
                    {"step": ident, "reference": ref},
                )
        for ref in _refs(
            s.get("actual") if kind == "assert" else s.get("from") if kind == "select" else None
        ):
            if provenance.get(ref.split(".")[0]) != "observation":
                raise Error(
                    "E_VALIDATION",
                    "selection/assertion must use an independent read, not a write response",
                    {"step": ident},
                )
        seen.add(ident)
        steps.append(s)
    return steps


def _observe(step, outputs, opts, frozen_request=None):
    from .commands.workflow import _options
    from .registry import BY_PATH

    s = _resolve(step, outputs)
    if frozen_request is not None:
        s.setdefault("args", {})["request"] = deepcopy(frozen_request)
    if s["kind"] == "read":
        command = BY_PATH[s["command"]]
        result = command.handler(
            _options(command, s.get("args", {}), 0) | {"timeout": opts.get("timeout", 30)}
        )
        if result.get("has_more") is True or result.get("completed") is False:
            raise Error(
                "E_VERIFY_INCOMPLETE", "workflow observation is incomplete", {"step": s["id"]}
            )
        return result
    if s["kind"] == "select":
        rows = s["from"]
        if not isinstance(rows, list):
            raise Error("E_VALIDATION", "selection source is not a list")
        matches = [
            row
            for row in rows
            if isinstance(row, dict)
            and all(_get(row, k) == v for k, v in s.get("where", {}).items())
        ]
        if len(matches) != 1:
            raise Error(
                "E_CONFLICT",
                "selection must match exactly one actual item",
                {"matched_count": len(matches), "step": s["id"]},
            )
        return matches[0]
    actual, expected = s["actual"], s["expected"]
    tolerance = s.get("tolerance")
    if tolerance is None:
        passed = type(actual) is type(expected) and actual == expected
    else:
        numeric = all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in (actual, expected)
        )
        passed = numeric and abs(actual - expected) <= tolerance
    if not passed:
        raise Error(
            "E_VERIFY_FAILED",
            "workflow assertion failed on an independent observation",
            {"step": s["id"], "actual": actual, "expected": expected, "tolerance": tolerance},
        )
    return {"passed": True, "actual": actual, "expected": expected, "tolerance": tolerance}


def _capture(step, outputs, opts, frozen_request=None):
    from .commands.workflow import _options
    from .registry import BY_PATH

    s = _resolve(step, outputs)
    command = BY_PATH[s["command"]]
    step_opts = _options(command, s.get("args", {}), 0) | {"timeout": opts.get("timeout", 30)}
    if frozen_request is not None:
        step_opts["request"] = deepcopy(frozen_request)
    sink = []
    marker = engine.CAPTURE.set(sink)
    try:
        command.handler(step_opts)
    finally:
        engine.CAPTURE.reset(marker)
    if len(sink) != 1:
        raise Error("E_VALIDATION", "write command cannot be a task step")
    _, prepare, make_plan, normalized_opts = sink[0]
    return command, normalized_opts, prepare, make_plan


def _prefix(steps, opts):
    outputs, trace = {}, []
    for step in steps:
        if step["kind"] == "write":
            break
        outputs[step["id"]] = _observe(step, outputs, opts)
        trace.append({"id": step["id"], "kind": step["kind"], "result": outputs[step["id"]]})
    return outputs, trace


def plan(opts, q):
    steps = compile_task(q)
    outputs, trace = _prefix(steps, opts)
    return {
        "steps": steps,
        "observations": outputs,
        "read_prefix": trace,
        "deferred_steps": [s["id"] for s in steps[len(trace) :]],
        "planning_scope": (
            "arguments/dependencies and read prefix; each later write is "
            "planned against the resulting live state"
        ),
        "rollback": "none; completed writes remain on failure",
        "_untrusted": ["observations", "read_prefix"],
    }


SUPPORTED_WRITES = {
    "parameter set",
    "relation set",
    "dimension set",
    "material assign",
    "model set-tolerance-standard",
    "dimension set-tolerance",
    "model regenerate",
    "model save",
    "drawing dimension annotate",
    "drawing dimension move",
    "drawing dimension add",
    "drawing dimension hide",
    "drawing note add",
    "drawing note edit",
    "drawing table add",
    "drawing table move",
    "drawing table remove",
    "drawing note remove",
    "drawing dimension remove",
    "drawing view move",
    "drawing layout apply",
    "artifact export",
    "feature rename",
    "feature suppress",
    "feature resume",
}


def _workflow_record(steps, parent_id):
    from . import driver

    return {
        "operation_id": parent_id,
        "observed_at": operations.now(),
        "failure_policy": "stop",
        "steps": [
            {
                "id": s["id"],
                "depends_on": list(
                    dict.fromkeys(s.get("depends_on", []) + ([steps[i - 1]["id"]] if i else []))
                ),
                "phase": "apply"
                if s["kind"] == "write"
                else "verify"
                if s["kind"] == "assert"
                else "observe",
                "effects": driver.MIGRATED[s["command"]] if s["kind"] == "write" else ["observe"],
                "operation_id": None,
                "status": "not_started",
                "receipt": None,
                "output_refs": [],
                "skip_reason": None,
                "error": None,
                "extensions": {"creo": {"kind": s["kind"], "command": s.get("command")}},
            }
            for i, s in enumerate(steps)
        ],
        "summary": {},
        "_untrusted": ["steps"],
    }


def _summarize(workflow):
    from . import driver_schema

    states = ("not_started", "running", "completed", "failed", "skipped", "cancelled", "unknown")
    workflow["observed_at"] = operations.now()
    workflow["summary"] = {"total": len(workflow["steps"])} | {
        s: sum(r["status"] == s for r in workflow["steps"]) for s in states
    }
    driver_schema.validate("workflow", workflow)
    return workflow


def aggregate_receipt(run, p, output=None, error=None):
    from types import SimpleNamespace

    from . import driver, driver_schema

    receipt = driver.make_receipt(
        run,
        SimpleNamespace(op="workflow.aggregate", target=p.target, before=p.before),
        output,
        error,
    )
    workflow = run.get("driver_workflow")
    rows = workflow["steps"] if workflow else []
    children = [r["receipt"] for r in rows if r["receipt"]]
    unknown = (
        run["status"] in ("running", "unknown")
        or any(r["status"] == "unknown" for r in rows)
        or run.get("workflow_final_validation", {}).get("status") == "unknown"
    )
    steps_complete = bool(rows) and all(r["status"] == "completed" for r in rows)
    complete = steps_complete and error is None
    changed = any(c["outcome"]["change"] in ("applied", "partial") for c in children)
    from . import workflow_state

    persistence, objects = workflow_state.persistence(run, rows)
    receipt["outcome"].update(
        execution="unknown" if unknown else "completed" if complete else "failed",
        change="unknown" if unknown else "applied" if changed else "not_applied",
        persistence="unknown"
        if unknown and set(receipt["effects"]) & {"persist", "change"}
        else persistence,
        delivery="not_applicable",
    )
    receipt["artifacts"] = [a for c in children for a in c["artifacts"]]
    receipt["changed_items"] = [a for c in children for a in c["changed_items"]]
    receipt["extensions"]["creo"]["workflow"] = workflow
    receipt["extensions"]["creo"]["object_persistence"] = objects
    if run.get("workflow_final_validation"):
        receipt["extensions"]["creo"]["final_validation"] = run["workflow_final_validation"]
    if persistence == "partial":
        receipt["failed_stage"] = "persist"
    if unknown or persistence == "partial" or not complete:
        receipt["recovery"] = {
            "action": "inspect",
            "reason": "query parent and children; register independent evidence "
            "before conflicting writes",
            "supported": True,
        }
    if not complete:
        receipt["outcome"]["verification"].update(
            status="failed"
            if run.get("workflow_final_validation", {}).get("status") == "failed"
            else "incomplete",
            coverage="partial" if children else "none",
            reason="the final workflow boundary did not verify after completed leaf operations"
            if steps_complete
            else "not every requested dependency step completed",
        )
    if changed or persistence in ("saved", "partial") or receipt["artifacts"]:
        if not complete and not unknown:
            receipt["outcome"]["change"] = "partial" if changed else "not_applied"
    native_read_recovery.annotate_receipt(
        receipt,
        native_read_recovery.pending_error(run) or native_read_recovery.pending_error(error),
    )
    native_diagnostic_recovery.annotate_receipt(
        receipt,
        native_diagnostic_recovery.diagnostic_error(run)
        or native_diagnostic_recovery.diagnostic_error(error),
    )
    driver_schema.validate("receipt", receipt)
    return receipt


@timing.phase("workflow_control")
def run(opts, q):
    from . import dependencies, driver, workflow_properties, workflow_state

    if not opts.get("dry_run"):
        prior = operations.get(safety.token_operation(opts.get("confirm")))
        if prior["status"] != "planned":
            raise Error(
                "E_CONFLICT",
                "workflow operation was already submitted",
                {"conflict": "token_used", "operation_id": prior["operation_id"]},
            )
        saved_inputs = prior["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"][
            "file_inputs"
        ].get("inputs", {})
        for path, expected in saved_inputs.items():
            observed = workflow_state.files({"models": {}, "outputs": [], "inputs": [path]})[
                "inputs"
            ][path]
            workflow_state.require_files(expected, observed)
    steps = compile_task(q)
    writes = [s for s in steps if s["kind"] == "write"]
    if not writes:
        raise Error("E_VALIDATION", "use workflow plan for a task with no writes")
    for s in steps:
        if s["kind"] == "write" and s["command"] not in SUPPORTED_WRITES:
            raise Error(
                "E_UNSUPPORTED",
                "workflow currently edits existing open models using the declared migrated leaves",
                {"step": s["id"], "command": s["command"]},
            )
        if s["kind"] in ("read", "write"):
            for name in ("model", "of", "component", "output", "path", "file"):
                if isinstance(s.get("args", {}).get(name), dict):
                    raise Error(
                        "E_UNSUPPORTED",
                        "workflow object and file scope must be literal before execution",
                        {"step": s["id"], "parameter": name},
                    )
    property_models = workflow_properties.models(steps)
    workflow_properties.require_supported(steps, property_models)
    material_models = workflow_properties.models(
        [s for s in steps if s.get("command") == "material assign"]
    )
    with safety.lock(), Client(opts.get("timeout", 30)) as client:
        client._guard_pending_read("workflow.run")
        safety.actor()
        preparation_started = time.monotonic()
        client.health()
        outputs, prefix = _prefix(steps, opts)
        frozen_requests, input_sources = {}, {}
        for s in steps:
            value = _resolve(s.get("args", {}), outputs).get("request")
            if isinstance(value, str):
                if value == "-":
                    raise Error(
                        "E_UNSUPPORTED",
                        "workflow leaf requests must be inline JSON or repeatable files",
                        {"step": s["id"]},
                    )
                source = workflow_state.request_file(value)
                frozen_requests[s["id"]] = source["content"]
                input_sources[source["path"]] = {k: v for k, v in source.items() if k != "content"}
        if isinstance(opts.get("request"), str) and opts["request"] != "-":
            source = workflow_state.request_file(opts["request"])
            if source["content"] != q:
                raise Error(
                    "E_CONFLICT",
                    "workflow request changed during preparation",
                    {"conflict": "state_drift"},
                )
            input_sources[source["path"]] = {k: v for k, v in source.items() if k != "content"}
        from .commands.workflow import _options
        from .registry import BY_PATH

        for index, step in enumerate(steps):
            if step["kind"] in ("read", "write"):
                try:
                    args = _resolve(step.get("args", {}), outputs)
                except Error as exc:
                    raise Error(
                        "E_UNSUPPORTED",
                        "command arguments require literal values or prefix observations",
                        {"step": step["id"]},
                    ) from exc
                _options(BY_PATH[step["command"]], args, index)
        roots = set()
        for s in steps:
            if s["kind"] in ("read", "write"):
                roots |= dependencies.references(s["command"], s.get("args", {}))
        session = engine.session(client)
        for name in roots:
            engine.require_in_session(session, name)
        initial = dependencies.closure(client, roots)
        first_target = sorted(roots)[0] if roots else None
        if first_target is None:
            raise Error("E_UNSUPPORTED", "workflow needs explicit existing model targets")
        preplans = []
        paths = []
        artifacts = []
        effects = set()
        missing = {}
        grant = driver.scope()
        save_counts = {}
        standard_preconditions = {}
        for s in writes:
            try:
                command, so, prepare, make_plan = _capture(
                    s, outputs, opts, frozen_requests.get(s["id"])
                )
            except Error as exc:
                if exc.code == "E_NOT_FOUND":
                    raise Error(
                        "E_UNSUPPORTED",
                        "write arguments can reference only observations before the first write",
                        {"step": s["id"]},
                    ) from exc
                raise
            driver.guard_model(command.path, client, so)
            prepared = prepare(so)
            pending_standard = None
            if command.path == "dimension set-tolerance":
                if prepared["spec"]["type"] not in workflow_properties.NUMERIC:
                    raise Error(
                        "E_UNSUPPORTED",
                        "property workflows currently support numeric plus/minus, symmetric "
                        "or limit tolerances",
                        {"step": s["id"]},
                    )
                pending_standard = standard_preconditions.get(prepared["name"])
            with (
                timing.phase("planning"),
                client.observation(enabled=command.path in workflow_properties.WRITES),
            ):
                if pending_standard:
                    from .commands.dimension import plan_workflow_tolerance

                    p = plan_workflow_tolerance(client, so, prepared, pending_standard)
                else:
                    p = make_plan(client, so, prepared)
            if command.path == "model set-tolerance-standard":
                standard_preconditions[p.target] = workflow_properties.standard_precondition(s, p)
            for file in p.preview.get("input_files", []):
                source = workflow_state.file_input(file)
                if p.op == "material.assign":
                    frozen_source = p.binding["source"]
                    if any(
                        source[k] != frozen_source[k]
                        for k in ("sha256", "size_bytes", "file_identity")
                    ):
                        raise Error(
                            "E_CONFLICT",
                            "material file changed during workflow planning",
                            {"conflict": "state_drift"},
                        )
                if source["path"] in input_sources:
                    workflow_state.require_files(input_sources[source["path"]], source)
                input_sources[source["path"]] = source
            touched = driver.affected_paths(client, p)
            out = driver.outputs_for(p)
            if command.path == "model save":
                from pathlib import Path

                from . import paths as model_paths

                offset = save_counts.get(p.target, 0)
                out[0]["path"] = str(
                    Path(p.preview["directory"])
                    / f"{p.target}.{model_paths.version(p.preview['next_version']) + offset}"
                )
                save_counts[p.target] = offset + 1
            denied = grant.missing(
                effects=driver.MIGRATED[command.path],
                dangerous=False,
                target=driver.target(client, p),
                paths=touched,
                outputs=out,
            )
            if denied:
                missing[s["id"]] = denied
            paths.extend(touched)
            artifacts.extend(out)
            effects.update(driver.MIGRATED[command.path])
            preplans.append(
                {
                    "id": s["id"],
                    "command": command.path,
                    "request": p.request,
                    "arguments": p.arguments,
                    "binding": p.binding,
                    "prerequisite": pending_standard,
                }
            )
        before = dependencies.snapshots(initial)
        where = workflow_state.locations(client, initial, artifacts, input_sources)
        initial_files = workflow_state.files(where)
        workflow_state.require_files(input_sources, initial_files["inputs"])
        initial_properties = workflow_properties.observe(client, property_models, material_models)

        def observe(c):
            return dependencies.snapshots(dependencies.closure(c, roots))

        final_boundary = {}

        def verify_final_boundary(c):
            record = final_boundary["record"]
            try:
                workflow_state.require_files(final_boundary["files"], workflow_state.files(where))
                workflow_properties.require_state(
                    final_boundary["properties"],
                    workflow_properties.observe(c, property_models, material_models),
                )
                nodes = dependencies.closure(c, roots)
                record["workflow_final_models"] = {n["identity"]: n["description"] for n in nodes}
                if dependencies.snapshots(nodes) != final_boundary["dependencies"]:
                    raise Error(
                        "E_CONFLICT",
                        "workflow dependency changed at the final boundary",
                        {"conflict": "state_drift"},
                    )
            except Error as exc:
                pending = native_read_recovery.capture(record, exc)
                diagnostic = native_diagnostic_recovery.capture(record, exc)
                record["workflow_final_validation"] = {
                    "status": "failed" if exc.code == "E_CONFLICT" else "unknown",
                    "code": exc.code,
                    "message": exc.message,
                    **native_read_recovery.details(pending),
                    **native_diagnostic_recovery.details(diagnostic),
                }
                if pending or diagnostic:
                    record["workflow_final_models"] = {}
                else:
                    try:
                        record["workflow_final_models"] = {
                            n["identity"]: n["description"] for n in dependencies.closure(c, roots)
                        }
                    except Error as readback_error:
                        pending = native_read_recovery.capture(record, readback_error)
                        diagnostic = native_diagnostic_recovery.capture(record, readback_error)
                        record["workflow_final_models"] = {}
                        record["workflow_final_validation"].update(
                            native_read_recovery.details(pending)
                        )
                        record["workflow_final_validation"].update(
                            native_diagnostic_recovery.details(diagnostic)
                        )
                operations.update(record)
                details = exc.details | {
                    "workflow": record["driver_workflow"],
                    "workflow_operation_id": record["operation_id"],
                    "completed_steps": [
                        r["id"]
                        for r in record["driver_workflow"]["steps"]
                        if r["status"] == "completed"
                    ],
                    "not_run": [],
                    "automatic_retry": False,
                    "request_sent": True,
                    "cause_code": exc.code,
                }
                details.update(native_read_recovery.details(pending))
                details.update(native_diagnostic_recovery.details(diagnostic))
                raise Error(
                    "E_NATIVE_DIAGNOSTIC"
                    if diagnostic
                    else exc.code
                    if exc.code == "E_CONFLICT"
                    else "E_OUTCOME_UNKNOWN",
                    "final workflow state did not match the verified leaf results",
                    details,
                ) from exc
            record["workflow_final_validation"] = {
                "status": "passed",
                "properties_sha256": digest(final_boundary["properties"]),
            }
            operations.update(record)

        @timing.phase("workflow_steps")
        def apply(c, record):
            from . import driver

            workflow = _workflow_record(steps, record["operation_id"])
            record["driver_workflow"] = workflow
            leaf_by_id = {p["id"]: p for p in preplans}
            for row in workflow["steps"]:
                if row["id"] in leaf_by_id:
                    row["extensions"]["creo"]["target"] = leaf_by_id[row["id"]]["request"].get(
                        "model"
                    )
            values = dict(outputs)
            trace = list(prefix)
            expected = before
            expected_files = initial_files
            expected_properties = initial_properties
            record["workflow_initial_models"] = {n["identity"]: n["description"] for n in initial}
            record["workflow_final_models"] = record["workflow_initial_models"]
            for row, item in zip(workflow["steps"], prefix, strict=False):
                row.update(
                    status="completed",
                    output_refs=["operation:" + record["operation_id"] + ":" + row["id"]],
                )
                row["extensions"]["creo"]["result"] = item["result"]
            _summarize(workflow)
            operations.update(record)
            marker = driver.WORKFLOW_PARENT.set(record["operation_id"])
            try:
                for index in range(len(prefix), len(steps)):
                    s = steps[index]
                    row = workflow["steps"][index]
                    row["status"] = "running"
                    _summarize(workflow)
                    operations.update(record)
                    try:
                        workflow_state.require_files(expected_files, workflow_state.files(where))
                        with c.observation():
                            current_properties = workflow_properties.observe(
                                c, property_models, material_models
                            )
                            workflow_properties.require_state(
                                expected_properties, current_properties
                            )
                            if observe(c) != expected:
                                raise Error(
                                    "E_CONFLICT",
                                    "workflow dependency revision changed between steps",
                                    {"conflict": "state_drift"},
                                )
                        if s["kind"] == "write":
                            prerequisite = leaf_by_id[s["id"]].get("prerequisite")
                            workflow_properties.require_predecessor(
                                prerequisite, workflow, current_properties
                            )
                            if prerequisite:
                                row["extensions"]["creo"]["property_prerequisite"] = {
                                    "step_id": prerequisite["step_id"],
                                    "operation_id": next(
                                        r["operation_id"]
                                        for r in workflow["steps"]
                                        if r["id"] == prerequisite["step_id"]
                                    ),
                                    "verified": True,
                                }
                            command, so, prepare, make_plan = _capture(
                                s, values, opts, frozen_requests.get(s["id"])
                            )
                            driver.guard_model(command.path, c, so)
                            with (
                                timing.phase("planning"),
                                c.observation(enabled=command.path in workflow_properties.WRITES),
                            ):
                                p = make_plan(c, so, prepare(so))
                            workflow_properties.require_intent(leaf_by_id[s["id"]], p)
                            preview = driver.write(command.path, so | {"dry_run": True}, c, p)
                            row["operation_id"] = preview["preview"]["operation_id"]
                            child = operations.get(row["operation_id"])
                            child["workflow_parent_id"] = record["operation_id"]
                            child["workflow_step_id"] = s["id"]
                            operations.update(child)
                            _summarize(workflow)
                            operations.update(record)
                            # Re-check the same leaf boundary before its own confirmation.
                            workflow_state.require_files(
                                expected_files, workflow_state.files(where)
                            )
                            with c.observation(enabled=command.path in workflow_properties.WRITES):
                                workflow_properties.require_state(
                                    expected_properties,
                                    workflow_properties.observe(
                                        c, property_models, material_models
                                    ),
                                )
                                driver.guard_model(command.path, c, so)
                                with timing.phase("planning"):
                                    p = make_plan(c, so, prepare(so))
                            workflow_properties.require_intent(leaf_by_id[s["id"]], p)
                            out = driver.write(
                                command.path, so | {"confirm": preview["confirm_token"]}, c, p
                            )
                            values[s["id"]] = out["result"]
                            row["receipt"] = out["receipt"]
                            # The leaf has durably finished. Further sampling belongs to
                            # the parent's next boundary and cannot undo that fact.
                            row["status"] = "completed"
                            row["extensions"]["creo"]["result"] = values[s["id"]]
                            row["output_refs"] = [
                                "operation:" + record["operation_id"] + ":" + s["id"]
                            ]
                            _summarize(workflow)
                            operations.update(record)
                            expected_properties = workflow_properties.advance(
                                expected_properties,
                                workflow_properties.observe(c, property_models, material_models),
                                command.path,
                                row["receipt"],
                            )
                            trace.append(
                                {
                                    "id": s["id"],
                                    "kind": "write",
                                    "command": command.path,
                                    "operation_id": out["operation_id"],
                                    "result": out["result"],
                                    "persisted": out["persisted"],
                                }
                            )
                            after_nodes = dependencies.closure(c, roots)
                            expected = dependencies.snapshots(after_nodes)
                            expected_files = workflow_state.advance_files(
                                expected_files,
                                workflow_state.files(where),
                                command.path,
                                row["receipt"],
                            )
                            record["workflow_final_models"] = {
                                n["identity"]: n["description"] for n in after_nodes
                            }
                        else:
                            values[s["id"]] = _observe(
                                s, values, opts, frozen_requests.get(s["id"])
                            )
                            trace.append(
                                {"id": s["id"], "kind": s["kind"], "result": values[s["id"]]}
                            )
                        row["status"] = "completed"
                        row["extensions"]["creo"]["result"] = values[s["id"]]
                        row["output_refs"] = ["operation:" + record["operation_id"] + ":" + s["id"]]
                        _summarize(workflow)
                        operations.update(record)
                    except Error as exc:
                        pending = native_read_recovery.capture(record, exc)
                        diagnostic = native_diagnostic_recovery.capture(record, exc)
                        row["receipt"] = (
                            (exc.details.get("receipt") or row["receipt"])
                            if row["operation_id"]
                            else None
                        )
                        failure = {
                            "code": exc.code,
                            "message": exc.message,
                            "retryable": False,
                        }
                        if pending:
                            row["extensions"]["creo"]["native_read_error"] = deepcopy(pending)
                        if diagnostic:
                            row["extensions"]["creo"]["native_diagnostic_error"] = deepcopy(
                                diagnostic
                            )
                        completed_leaf = row["status"] == "completed" and row["receipt"] is not None
                        if completed_leaf:
                            record["workflow_final_validation"] = {
                                "status": "failed" if exc.code == "E_CONFLICT" else "unknown",
                                "after_step": s["id"],
                                **failure,
                                **native_read_recovery.details(pending),
                                **native_diagnostic_recovery.details(diagnostic),
                            }
                        else:
                            row["status"] = (
                                "unknown"
                                if exc.code
                                in (
                                    "E_OUTCOME_UNKNOWN",
                                    "E_NATIVE_READ_PENDING",
                                    "E_NATIVE_DIAGNOSTIC",
                                )
                                else "failed"
                            )
                            row["error"] = failure
                        if pending or diagnostic:
                            # A nested reader owns a different Client. Do not bypass its
                            # pending guard by sampling CAD through this outer Client.
                            record["workflow_final_models"] = {}
                        else:
                            try:
                                record["workflow_final_models"] = {
                                    n["identity"]: n["description"]
                                    for n in dependencies.closure(c, roots)
                                }
                            except Error:
                                record["workflow_final_models"] = {}
                        for later in workflow["steps"][index + 1 :]:
                            later.update(
                                status="skipped",
                                skip_reason="failure policy stop; parent boundary was not verified"
                                if completed_leaf
                                else "failure policy stop; preceding step did not complete",
                            )
                        _summarize(workflow)
                        operations.update(record)
                        exc.details.update(
                            workflow=workflow,
                            workflow_operation_id=record["operation_id"],
                            step=s["id"],
                            completed_steps=[
                                r["id"] for r in workflow["steps"] if r["status"] == "completed"
                            ],
                            not_run=[
                                r["id"] for r in workflow["steps"] if r["status"] == "skipped"
                            ],
                            automatic_retry=False,
                            request_sent=any(r["operation_id"] for r in workflow["steps"]),
                        )
                        exc.details.update(native_read_recovery.details(pending))
                        exc.details.update(native_diagnostic_recovery.details(diagnostic))
                        raise
            finally:
                driver.WORKFLOW_PARENT.reset(marker)
            final_boundary.update(
                record=record,
                files=expected_files,
                properties=expected_properties,
                dependencies=expected,
            )
            verify_final_boundary(c)
            return {"steps": trace, "workflow": workflow}

        def verify(c, data):
            verify_final_boundary(c)
            return data, {
                "level": "selected_postconditions_verified",
                "checks": [
                    engine.check(
                        "every_requested_step_completed",
                        data["workflow"]["summary"]["completed"] == len(steps),
                    ),
                    engine.check("final_bound_input_and_engineering_state_unchanged", True),
                ],
                "not_checked": [
                    "independent STEP/PDF consumer and manufacturing approval",
                    "rollback, cancellation or automatic resume",
                ],
            }

        p = engine.Plan(
            op="workflow.run",
            request=q,
            target=first_target,
            binding={
                "dependencies": before,
                "observations": outputs,
                "leaf_requests": preplans,
                "file_inputs": initial_files,
                "engineering_properties": initial_properties,
            },
            preview={
                "command": "workflow run",
                "steps": steps,
                "first_step": {"command": writes[0]["command"]},
                "model_footprint": [n["identity"] for n in initial],
                "scope_paths": paths,
                "scope_outputs": artifacts,
                "scope_missing": missing,
                "operation_cost": 1 + len(writes),
                "execution_budget": {
                    "seconds": opts.get("timeout", 30),
                    "scope": "one invocation shared by planning, nested readers and all steps; "
                    "preview and confirmation are separate invocations",
                    "preparation_observed_seconds": round(
                        time.monotonic() - preparation_started, 6
                    ),
                    "remaining_now_seconds": round(max(0.0, client.deadline - time.monotonic()), 6),
                    "write_steps": len(writes),
                    "advisory": "preparation already used at least one third of this budget"
                    if time.monotonic() - preparation_started >= opts.get("timeout", 30) / 3
                    else "planning measurements do not bound later native work",
                    "remaining_work": "leaf plans, native writes, independent verification and "
                    "durable records still consume this same deadline",
                    "next_action": "choose an explicit measured budget or split into separately "
                    "previewed tasks at verified boundaries; never replay "
                    "completed or unknown steps",
                    "automatic_extension": False,
                    "native_cancellation": False,
                },
                "engineering_property_profile": {
                    "models": sorted(property_models),
                    "numeric_tolerance_forms": sorted(workflow_properties.NUMERIC),
                    "preconditions": [
                        {"step_id": leaf["id"], "after_step": leaf["prerequisite"]["step_id"]}
                        for leaf in preplans
                        if leaf.get("prerequisite")
                    ],
                    "layout_feedback": "tolerance lettering can enlarge drawing labels; "
                    "inspect text bounds and known conflicts before placement/export, "
                    "then render every PDF page; leader intersections require visual review",
                    "not_supported": [
                        "geometry-edit and property-write interleaving",
                        "fit, basic or nominal tolerance workflow steps",
                        "automatic continuation or creation-derived targets",
                    ],
                }
                if property_models
                else None,
                "supported_range": (
                    "existing open models; literal scope; migrated non-dangerous writes; "
                    "prefix-derived arguments"
                ),
                "rollback": "none",
                "recovery": (
                    "evidence registration only; new explicit remaining-step task, never replay"
                ),
            },
            verify=verify,
            observe=observe,
            before=before,
            persisted="persist" in effects,
            effects=sorted(effects),
            apply=apply,
        )
        out = driver.write("workflow run", opts, client, p)
        if not opts.get("dry_run"):
            out["workflow"] = out["result"]["workflow"]
        return out
