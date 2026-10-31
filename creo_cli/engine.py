"""How every command talks to Creo: reads, and writes through preview, confirmation and receipt.

A preview is the request checked against a reading of the live session -- the model's
units, its datum planes, where Creo will write -- not predicted geometry. The token is bound
to that reading, so a model changed in the meantime (by a person in the GUI, say) makes
the confirmation fail instead of building on a state nobody previewed.

Each write reads back what Creo did and reports the reading next to what was asked:
`verification.checks` are postconditions, and a failed one is E_VERIFY_FAILED;
missing required read-back is E_VERIFY_INCOMPLETE, never a completed verification.
`verification.observations` inform without failing. A failure Creo reports is settled by
reading the target again, so the receipt says whether Creo was left as it was found.
Everything that can be checked without Creo is checked before connecting to it.
"""

from __future__ import annotations

import contextvars
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import (
    driver,
    native_diagnostic_recovery,
    native_read_recovery,
    operations,
    paths,
    safety,
    timing,
)
from .core import Error, digest
from .transport import Client

PREVIEW_KIND = "request_plan_with_observed_preconditions_not_predicted_geometry"
MODEL_NAME = re.compile(r"([A-Za-z][A-Za-z0-9_-]{0,30})(?:\.(prt|asm|drw))?", re.I)
# Failures that leave nothing to settle: refused before any change, never started, never sent.
NOTHING_DONE = (
    "E_VALIDATION",
    "E_NOT_FOUND",
    "E_CONFLICT",
    "E_CONFIG",
    "E_UNSUPPORTED",
    "E_AUTH",
    "E_BACKEND_UNAVAILABLE",
    "E_TIMEOUT",
)
READ_BACK_FAILURES = (
    "E_TIMEOUT",
    "E_NETWORK",
    "E_PROTOCOL",
    "E_BACKEND_UNAVAILABLE",
    "E_NOT_FOUND",
    "E_NATIVE_FAILURE",
    "E_AUTH",
    "E_UNSUPPORTED",
    "E_VERIFY_INCOMPLETE",
    "E_NATIVE_READ_PENDING",
    "E_NATIVE_DIAGNOSTIC",
)


# ------------------------------------------------------------------ names and values


def model_name(raw: str, kinds: tuple = ("prt", "asm", "drw"), path: str = "model") -> str:
    """The model's file name as Creo reports it: lower case, with its extension."""
    m = MODEL_NAME.fullmatch(raw or "")
    if not m:
        raise Error(
            "E_VALIDATION",
            "a model name starts with a letter, then letters, digits, '_' or '-', at most 31 "
            "characters, optionally with .prt, .asm or .drw",
            {"path": path},
        )
    # Without an extension a name means a part -- or, where only one kind fits, that kind.
    extension = (m[2] or (kinds[0] if len(kinds) == 1 else "prt")).lower()
    if extension not in kinds:
        wanted = {"prt": "a part", "asm": "an assembly", "drw": "a drawing"}
        raise Error(
            "E_VALIDATION",
            "this command takes " + " or ".join(wanted[k] for k in kinds),
            {"path": path, "given": raw},
        )
    return m[1].lower() + "." + extension


def normalize(value: Any, key: str = "") -> Any:
    """Ids leave as strings."""
    if isinstance(value, dict):
        return {k: normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v, key) for v in value]
    return str(value) if key == "id" and type(value) is int else value


def resource_inventory(client: Client, op: str, request: dict) -> dict:
    """Require a complete, source-identified independent bounded resource inventory."""
    data = normalize(client.op(op, request))
    items = data.get("items")
    coverage = data.get("coverage")
    if (
        not isinstance(items, list)
        or any(not isinstance(row, dict) or row.get("error") is not None for row in items)
        or data.get("completed") is not True
        or data.get("model") != request["model"]
        or not isinstance(data.get("source"), str)
        or not data["source"]
        or not isinstance(coverage, dict)
        or type(coverage.get("count")) is not int
        or coverage["count"] != len(items)
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "required resource getter did not complete",
            {
                "model": request["model"],
                "resource": request.get("kind"),
                "observation": data,
                "automatic_retry": False,
            },
        )
    return data


def check(name: str, passed: bool, **detail) -> dict:
    return {"check": name, "passed": bool(passed), **detail}


def verification_status(verification: dict) -> str:
    """A missing reading is not a pass, even if all available reply checks passed."""
    checks = verification.get("checks") or []
    if any(c.get("passed") is False for c in checks):
        return "failed"
    if (
        not checks
        or any(c.get("passed") is not True for c in checks)
        or verification.get("status") == "incomplete"
        or verification.get("level") == "service_reply_only"
    ):
        return "incomplete"
    return "passed"


def same_path(a: str | Path, b: str | Path) -> bool:
    def norm(p):
        return os.path.normcase(os.path.abspath(str(p).rstrip("\\/")))

    return norm(a) == norm(b)


def by_name(names: list, wanted: str) -> str | None:
    return next((n for n in names if str(n).upper() == wanted.upper()), None)


# ------------------------------------------------------------------ live readings


def session(client: Client) -> dict:
    s = client.op("session.status")
    for key, kind in (
        ("creation_api", bool),
        ("working_directory", str),
        ("models", list),
        ("native_sketch_available", bool),
    ):
        if type(s.get(key)) is not kind:
            raise Error("E_PROTOCOL", "the service's session reading lacks a field", {"field": key})
    s["models"] = sorted({str(m).lower() for m in s["models"]})
    return s


def show(client: Client, name: str) -> dict:
    return normalize(client.op("model.show", {"model": name}))


def require_in_session(s: dict, name: str) -> None:
    if name not in s["models"]:
        raise Error(
            "E_NOT_FOUND",
            "no model of that name is in session",
            {
                "model": name,
                "models_in_session": s["models"],
                "fix": "open it with creo-cli model open, or create it",
                "_untrusted": ["model", "models_in_session"],
            },
        )


def working_directory(s: dict) -> Path:
    """Creo's working directory, which must lie inside the workspace."""
    try:
        return paths.contained(s["working_directory"], directory=True)
    except Error as exc:
        if exc.code in ("E_FORBIDDEN", "E_NOT_FOUND"):
            raise Error(
                "E_FORBIDDEN",
                "Creo's working directory is outside the workspace; new models and saves would "
                "land there",
                {
                    "working_directory": s["working_directory"],
                    "fix": "creo-cli session cd --path <a directory inside CREO_CLI_WORKSPACE>",
                    "_untrusted": ["working_directory"],
                },
            ) from exc
        raise


def origin_directory(origin: str) -> Path:
    """Creo reports a model's origin as its version file, block.prt.3, or as a directory."""
    p = Path(origin)
    # Native family instances can be backed by accelerator files, not *.prt/*.asm.
    accelerator = re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\.(?:xpr|xas)(?:\.[0-9]+)?", p.name, re.I)
    return p.parent if paths.MODEL_FILE.fullmatch(p.name) or accelerator else p


def store_directory(described: dict, s: dict) -> Path:
    """Where Creo will store the model: the directory it came from, else the working directory."""
    proof = described.get("origin_readback")
    if proof is not None and (
        proof.get("complete") is not True or proof.get("value") != described.get("origin")
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "native origin read failed; cannot substitute the working directory",
        )
    origin = described.get("origin")
    if not origin:
        return working_directory(s)
    if not Path(origin).is_absolute():
        raise Error(
            "E_FORBIDDEN",
            "the model's origin is not a local path inside the workspace",
            {"origin": origin, "_untrusted": ["origin"]},
        )
    try:
        return paths.contained(str(origin_directory(origin)), directory=True)
    except Error as exc:
        if exc.code in ("E_FORBIDDEN", "E_NOT_FOUND"):
            raise Error(
                "E_FORBIDDEN",
                "the model came from outside the workspace, and Creo stores a model back where it "
                "came from; only models that live in the workspace are changed",
                {"origin": origin, "_untrusted": ["origin"]},
            ) from exc
        raise


def dependencies(described: dict) -> list[str]:
    """The models an assembly's components or a drawing's views show."""
    if described.get("type") == "drawing":
        return [str(m).lower() for m in described.get("models") or []]
    return [str(c["model"]).lower() for c in described.get("components") or [] if c.get("model")]


def require_workspace_models(client: Client, s: dict, names: list[str], role: str) -> None:
    """Models a write makes something depend on, or a save may store with it. Saving an
    assembly or drawing stores its changed dependencies too, each back where it came from, so
    every one of them must live in the workspace -- and theirs, down the tree."""
    seen: set[str] = set()
    pending = [(n, role) for n in names]
    while pending:
        name, what = pending.pop()
        if name in seen or name not in s["models"]:
            continue
        seen.add(name)
        described = show(client, name)
        try:
            store_directory(described, s)
        except Error as exc:
            if exc.code != "E_FORBIDDEN":
                raise
            raise Error(
                "E_FORBIDDEN",
                f"{what} came from outside the workspace; saving what uses it can store it back "
                "there, so only models that live in the workspace are used",
                {
                    "model": name,
                    "origin": described.get("origin"),
                    "_untrusted": ["model", "origin"],
                },
            ) from exc
        pending += [(d, "a model it uses") for d in dependencies(described)]


# ------------------------------------------------------------------ reads


def read(opts: dict, fetch: Callable[[Client], dict]) -> dict:
    with Client(opts.get("timeout", 30)) as client:
        client.health()
        command = opts.get("_command_path", "")
        if command.startswith("appearance "):
            client.require_capability("source_part_appearance", 2)
        if command.startswith("display "):
            client.require_capability("native_presentation", 2)
        with timing.phase("observation"):
            value = fetch(client)
        return timing.stamp(value)


# ------------------------------------------------------------------ writes


@dataclass
class Plan:
    """One write, planned against a live reading."""

    op: str
    request: dict  # what is sent to the service
    target: str  # what the write changes, for the token and the receipt
    binding: Any  # the observed state the token is bound to
    preview: dict
    verify: Callable[[Client, dict], tuple[dict, dict]]
    observe: Callable[[Client], Any]  # re-read after a reported failure
    before: Any  # what observe() returned before the write
    persisted: bool = False
    arguments: dict = field(default_factory=dict)  # the caller's own arguments
    # Builds the request actually sent, at confirmation only -- for a write that must prepare
    # something first (an export's private staging directory). The token binds `request`.
    send: Callable[[], dict] | None = None
    # A second operation the write needs, given the first's reply, returning the reply to
    # read back: Creo does some work only in the call after the one that made a model.
    then: Callable[[Client, dict], dict] | None = None
    first: Callable[[Client], Any] | None = None
    effects: list[str] | None = None
    apply: Callable[[Client, dict], dict] | None = None
    artifacts_after: Callable[[], list[dict]] | None = None
    prepare_dispatch: Callable[[dict], None] | None = None
    verified_observation: Any = None  # opt-in independent snapshot already checked by verify
    # A leaf with separately observed persistence may require more than geometric equality.
    failure_unchanged: Callable[[Any], bool | None] | None = None


# Set by `workflow run` while it collects its steps: a write then hands over how it would be
# prepared and planned instead of running, so steps are planned and run one at a time later.
CAPTURE: contextvars.ContextVar[list | None] = contextvars.ContextVar("capture", default=None)
_CONFIRMATION_EXECUTION = contextvars.ContextVar("confirmation_execution", default=None)


def write(
    command: str,
    opts: dict,
    prepare: Callable[[dict], Any],
    plan: Callable[[Client, dict, Any], Plan],
) -> dict:
    """Retain pre-dispatch confirmation refusals even when preparation could not finish."""
    path = opts.get("_command_path", command)
    retained = None
    if path in driver.MIGRATED and not opts.get("dry_run") and opts.get("confirm"):
        try:
            retained = operations.get(safety.token_operation(opts["confirm"]))
        except Error:
            pass  # No authenticated retained operation to associate with malformed input.
    execution = {"entered": False}
    marker = _CONFIRMATION_EXECUTION.set(execution)
    try:
        return _write(command, opts, prepare, plan)
    except Error as exc:
        if (
            retained is not None
            and not execution["entered"]
            and "confirmation_attempt" not in exc.details
            and "confirmation_attempt_retained" not in exc.details
        ):
            # This is an invocation-local fact: another process starting the same
            # retained plan cannot hide our refused attempt or turn it into success.
            driver.record_confirmation_refusal(retained, exc)
        raise
    finally:
        _CONFIRMATION_EXECUTION.reset(marker)


def _write(command, opts, prepare, plan) -> dict:
    command = opts.get("_command_path", command)
    sink = CAPTURE.get()
    if sink is not None:
        # Resource handlers normalize selectors before reaching this boundary. Preserve
        # those options so workflow capture uses the same input as a direct leaf call.
        sink.append((command, prepare, plan, dict(opts)))
        return {}
    if command in driver.MIGRATED and not opts.get("dry_run"):
        run = operations.get(safety.token_operation(opts.get("confirm")))
        if run["status"] != "planned":
            raise Error(
                "E_CONFLICT",
                "operation was already dispatched",
                {
                    "conflict": "token_used",
                    "operation_id": run["operation_id"],
                    "dispatch_state": "not_started",
                },
            )
    with timing.phase("planning"):
        pre = prepare(opts)
    with safety.lock():
        if command not in driver.MIGRATED:
            operations.require_clear()
        with Client(opts.get("timeout", 30)) as client:
            client._guard_pending_read(command)
            safety.actor()
            client.health()
            # Only this invocation's preflight and domain planning share observations.
            # Leave the boundary before the driver's final fresh dependency closure,
            # confirmation drift check, setter and first independent verification.
            shared_bom_preparation = command in {"drawing bom add", "drawing bom balloons"}
            shared_preparation = shared_bom_preparation or command in {
                "feature extrude",
                "assembly component add",
                "model save",
                "appearance set",
                "appearance restore",
                "display activate",
                "display fit",
                "display component-visibility",
                "display unexplode",
            }
            with client.observation(
                enabled=shared_preparation,
                fresh_operations={"drawing.bom-template"} if shared_bom_preparation else (),
            ):
                if command in driver.MIGRATED:
                    driver.guard_model(command, client, opts)
                with client.observation(enabled=command in driver.ENGINEERING_PROPERTY_LIMITS):
                    with timing.phase("planning"), timing.phase("observation"):
                        p = plan(client, opts, pre)
            if command in driver.MIGRATED:
                return driver.write(command, opts, client, p)
            bound = safety.scope(
                command,
                p.target,
                {"arguments": p.arguments, "request": p.request},
                digest(p.binding),
            )
            if opts.get("dry_run"):
                token, expires = safety.issue(bound)
                return {
                    "preview": p.preview
                    | {"command": command, "preview_kind": PREVIEW_KIND, "policy": safety.policy()},
                    "confirm_token": token,
                    "expires_at": expires,
                    "_untrusted": ["preview"],
                }
            safety.require_write()
            safety.consume(opts.get("confirm"), bound)
            return execute(command, client, p)


@timing.phase("execution_control")
def execute(command: str, client: Client, p: Plan, planned: dict | None = None) -> dict:
    """Send a planned write, read it back and settle its receipt. The caller holds the lock
    and has cleared the token."""
    execution = _CONFIRMATION_EXECUTION.get()
    if execution is not None:
        execution["entered"] = True
    run = operations.begin(command, p.target, p.request, client.url, planned=planned)
    if p.prepare_dispatch:
        try:
            p.prepare_dispatch(run)
        except (Error, OSError) as exc:
            failure = Error(
                exc.code if isinstance(exc, Error) else "E_IO",
                "cannot prepare durable dispatch ownership; nothing was dispatched",
                {"request_sent": False, "dispatch_state": "not_started"},
            )
            raise settle(run, failure, client, p) from exc
    try:
        if p.first:
            p.first(client)
        data = normalize(
            p.apply(client, run)
            if p.apply
            else client.op(p.op, p.send() if p.send else p.request, write=True)
        )
        if p.then:
            data = p.then(client, data)
    except Error as exc:
        raise settle(run, exc, client, p) from None
    except (OSError, KeyboardInterrupt) as exc:
        raise settle(run, local_outcome_unknown(exc), client, p) from None
    try:
        return finish(run, client, p, data)
    except (OSError, KeyboardInterrupt) as exc:
        raise settle(run, local_outcome_unknown(exc), client, p) from None


def local_outcome_unknown(exc: BaseException) -> Error:
    return Error(
        "E_OUTCOME_UNKNOWN",
        "local interruption or I/O failure after dispatch; inspect actual effects",
        {
            "request_sent": True,
            "cause_code": "E_INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "E_IO",
            "exception_type": type(exc).__name__,
            "automatic_retry": False,
        },
    )


@timing.phase("verification")
def finish(run: dict, client: Client, p: Plan, data: dict) -> dict:
    run["service_reported_done"] = True
    try:
        try:
            result, verification = p.verify(client, data)
        except Error as exc:
            if exc.code not in READ_BACK_FAILURES:
                raise
            native_read_recovery.capture(run, exc)
            native_diagnostic_recovery.capture(run, exc)
            # The service said the write is done; only reading it back independently failed.
            result, verification = (
                data,
                {
                    "level": "service_reply_only",
                    "checks": [],
                    "observations": [
                        {
                            "observation": "independent_read_back_failed",
                            "code": exc.code,
                            "error": native_read_recovery.error_record(exc),
                        }
                    ],
                    "not_checked": ["postconditions_read_back_independently"],
                },
            )
        pending = native_read_recovery.capture_client(run, client)
        diagnostic = native_diagnostic_recovery.capture_client(run, client)
        if pending or diagnostic:
            stopped = diagnostic or pending
            observations = list(verification.get("observations", []))
            if not any(
                isinstance(row, dict) and row.get("error") == stopped for row in observations
            ):
                observations.append(
                    {
                        "observation": "native_diagnostic_stop"
                        if diagnostic
                        else "native_read_pending",
                        "error": stopped,
                    }
                )
            verification = verification | {
                "status": "incomplete",
                "observations": observations,
                "not_checked": list(
                    dict.fromkeys(
                        [
                            *verification.get("not_checked", []),
                            "postconditions_read_back_independently",
                        ]
                    )
                ),
            }
        status = verification_status(verification)
        verification = verification | {"status": status}
        receipt_status = {
            "passed": "completed",
            "failed": "verification_failed",
            "incomplete": "verification_incomplete",
        }[status]
        output = {
            "operation_id": run["operation_id"],
            "status": receipt_status,
            "result": result,
            "verification": verification,
            "persisted": p.persisted,
            "_untrusted": ["result", "verification"],
        }
        run["result"] = operations.save_result(run["operation_id"], output)
        run["status"] = receipt_status
        run["checks"] = [
            {"check": c["check"], "passed": c["passed"]} for c in verification["checks"]
        ]
        operations.checkpoint_domain(run)
    except Error as exc:
        native_read_recovery.capture_client(run, client)
        native_diagnostic_recovery.capture_client(run, client)
        run["status"], run["error_code"] = "unknown", exc.code
        try:
            operations.checkpoint_domain(run)
        except Error:
            pass
        exc.details |= {
            "operation_id": run["operation_id"],
            "receipt_status": "unknown",
            "service_reported_done": True,
        }
        exc.details.update(native_read_recovery.details(native_read_recovery.pending_error(run)))
        exc.details.update(
            native_diagnostic_recovery.details(native_diagnostic_recovery.diagnostic_error(run))
        )
        raise
    if status != "passed":
        details = {
            "operation_id": run["operation_id"],
            "receipt_status": receipt_status,
            "receipt": output,
            "dispatch_state": "dispatched",
            "service_reported_done": True,
            "failed_checks": [c for c in verification["checks"] if not c["passed"]],
            "_untrusted": ["failed_checks", "receipt"],
            "rollback_performed": False,
            "automatic_retry": False,
            "next_action": "query the recorded operation and read the target independently; "
            "do not repeat the write or clear the receipt without an actual inspection",
            "fix": "inspect the model (creo-cli model show / feature list); a person "
            "acknowledges the "
            "receipt before further writes",
        }
        details.update(native_read_recovery.details(native_read_recovery.pending_error(run)))
        diagnostic = native_diagnostic_recovery.diagnostic_error(run)
        details.update(native_diagnostic_recovery.details(diagnostic))
        if diagnostic:
            raise Error(
                "E_NATIVE_DIAGNOSTIC",
                "the write returned, but native diagnostics stopped verification",
                details,
            )
        if status == "failed":
            raise Error(
                "E_VERIFY_FAILED",
                "Creo reported the operation done, but a postcondition read back afterwards failed",
                details,
            )
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "Creo reported completion, but required independent read-back is incomplete",
            details,
        )
    return output


def _model_close_read_refusal(p, exc):
    details = exc.details.get("service_details")
    return (
        p.op == "model.close"
        and exc.code == "E_VERIFY_INCOMPLETE"
        and isinstance(details, dict)
        and details.get("stage") == "model_close_stage"
        and details.get("started") is False
        and details.get("sdk_read_entered") is True
    )


def _complete_close_observation(value):
    """The complete returned model-management observation, including dirty state."""
    if (
        not isinstance(value, dict)
        or value.get("completed") is not True
        or not isinstance(value.get("models"), list)
        or not isinstance(value.get("windows"), list)
        or not {"active_model", "active_window"} <= value.keys()
    ):
        return False
    names, windows = set(), set()
    for row in value["models"]:
        if not isinstance(row, dict):
            return False
        name, origin = row.get("model"), row.get("origin")
        source, family = row.get("origin_readback"), row.get("family")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(row.get("type"), str)
            or not isinstance(origin, str)
            or not origin
            or not isinstance(source, dict)
            or source.get("complete") is not True
            or source.get("state") != "saved"
            or source.get("value") != origin
            or not source.get("source")
            or not isinstance(family, dict)
            or family.get("complete") is not True
            or type(row.get("modified")) is not bool
            or not isinstance(row.get("version_stamp"), str)
            or not row["version_stamp"]
            or type(row.get("relation_id")) is not int
            or row.get("dependencies_complete") is not True
            or not isinstance(row.get("dependencies"), list)
            or not all(isinstance(name, str) and name for name in row["dependencies"])
        ):
            return False
        names.add(name)
    for window in value["windows"]:
        if (
            not isinstance(window, dict)
            or not isinstance(window.get("id"), str)
            or not window["id"]
            or window["id"] in windows
            or "model" not in window
            or window["model"] is not None
            and window["model"] not in names
        ):
            return False
        windows.add(window["id"])
    return (value["active_window"] is None or value["active_window"] in windows) and (
        value["active_model"] is None or value["active_model"] in names
    )


def settle(run: dict, exc: Error, client: Client, p: Plan) -> Error:
    """Say in the receipt what the failure left behind, as far as it can be known."""
    observed_after = None
    close_refusal = _model_close_read_refusal(p, exc)
    close_observation_bound = False

    def observed_status(after):
        unchanged = (
            p.failure_unchanged(after)
            if p.failure_unchanged is not None
            else digest(after) == digest(p.before)
        )
        return "unknown" if unchanged is None else "failed_unchanged" if unchanged else "partial"

    pending = native_read_recovery.capture_client(run, client) or native_read_recovery.capture(
        run, exc
    )
    diagnostic = native_diagnostic_recovery.capture_client(
        run, client
    ) or native_diagnostic_recovery.capture(run, exc)
    if diagnostic:
        # A definite diagnostic stop never authorizes an additional settling getter.
        native_diagnostic_recovery.capture_effects(run, diagnostic, p.op, p.target)
        status = "verification_incomplete" if run.get("native_write_returned") else "unknown"
    elif p.op == "service.install" and exc.details.get("request_sent"):
        try:
            observed_after = p.observe(client)
            status = observed_status(observed_after)
        except (Error, OSError):
            status = "unknown"
    elif p.op == "workflow.run" and run.get("driver_workflow"):
        rows = run["driver_workflow"]["steps"]
        status = (
            "unknown"
            if any(r["status"] in ("unknown", "running") for r in rows)
            else "partial"
            if any(
                r.get("receipt")
                and (
                    r["receipt"]["outcome"]["change"] in ("applied", "partial")
                    or r["receipt"]["outcome"]["persistence"] in ("saved", "partial")
                    or r["receipt"]["artifacts"]
                )
                for r in rows
            )
            else "failed_before_write"
        )
        if status == "partial" and not pending:
            try:
                observed_after = p.observe(client)
            except Error as readback_error:
                pending = native_read_recovery.capture(run, readback_error)
                status = "unknown"
        if pending:
            status = "unknown"
    elif pending or exc.code == "E_OUTCOME_UNKNOWN" or exc.details.get("started") is True:
        status = "unknown"
    elif not exc.details.get("request_sent", False) or exc.code in NOTHING_DONE:
        status = "failed_before_write"
    elif exc.code in ("E_NATIVE_FAILURE", "E_VERIFY_INCOMPLETE"):
        # The service answered, so the operation is over; what it left is read, not assumed.
        try:
            guard = getattr(p, "_failure_observation_guard", None)
            guarded_before = close_refusal and callable(guard) and guard(p, client)
            observed_after = p.observe(client)
            status = observed_status(observed_after)
            if close_refusal:
                retain = getattr(p, "_retain_failure_observation", None)
                close_observation_bound = bool(
                    guarded_before
                    and guard(p, client)
                    and _complete_close_observation(p.before)
                    and _complete_close_observation(observed_after)
                    and callable(retain)
                    and retain(p, client, observed_after)
                )
        except Error as readback_error:
            pending = native_read_recovery.capture(run, readback_error)
            diagnostic = native_diagnostic_recovery.capture(run, readback_error) or diagnostic
            run.setdefault(
                "driver_effect_readback_error", native_read_recovery.error_record(readback_error)
            )
            run["driver_effect_observed"] = False
            observed_after = None
            status = "unknown"
        exc.details["state_after"] = {
            "failed_unchanged": "observed_unchanged",
            "partial": "observed_changed",
            "unknown": "not_observable",
        }[status]
        if exc.code == "E_VERIFY_INCOMPLETE":
            # Reading the changed values does not complete the failed native check.
            exc.details["verification"] = {
                "status": "incomplete",
                "native_check": (exc.details.get("service_details") or {}).get("verification"),
            }
            if close_refusal:
                run["native_close_read_refusal"] = {
                    "stage": "model_close_stage",
                    "mutation_started": False,
                    "sdk_read_entered": True,
                    "observation_bound": close_observation_bound,
                    "state_after": exc.details["state_after"],
                }
            if status == "failed_unchanged" and close_refusal and close_observation_bound:
                # A returned read-stage refusal did not enter the close mutator,
                # and this Plan's sole complete observation proves no session or
                # dirty-state change. The failed native check stays incomplete.
                pass
            elif close_refusal:
                status = "unknown"
                exc = Error(
                    "E_OUTCOME_UNKNOWN",
                    "the returned close refusal did not establish a complete unchanged "
                    "session observation bound to this Plan, Client and intent",
                    exc.details | {"cause_code": "E_VERIFY_INCOMPLETE"},
                )
            elif status != "unknown":
                status = "verification_incomplete"
            else:
                exc = Error(
                    "E_OUTCOME_UNKNOWN",
                    "the native check is incomplete and the changed target could not be read back",
                    exc.details | {"cause_code": "E_VERIFY_INCOMPLETE"},
                )
            receipt = {
                "operation_id": run["operation_id"],
                "status": status,
                "result": {"target": p.target, "state_after": observed_after},
                "persisted": p.persisted,
                "verification": {
                    "level": "service_reply_only"
                    if observed_after is None
                    else "selected_postconditions_verified",
                    "status": "incomplete",
                    "checks": [],
                    "observations": [
                        {
                            "observation": "state_after_native_check_error",
                            "expected_before": p.before,
                            "observed": observed_after,
                            "source": "plan.observe",
                            "independent": observed_after is not None,
                        },
                        {
                            "observation": "native_check",
                            "check": exc.details["verification"]["native_check"],
                        },
                    ],
                    "not_checked": ["native_regeneration_check"],
                },
                "_untrusted": ["result", "verification"],
            }
            exc.details["receipt"] = receipt
            exc.details.setdefault("_untrusted", []).append("receipt")
            try:
                run["result"] = operations.save_result(run["operation_id"], receipt)
            except Error:
                status = "unknown"
                receipt["status"] = "unknown"
                exc = Error(
                    "E_OUTCOME_UNKNOWN",
                    "cannot retain the incomplete native-check result",
                    exc.details | {"cause_code": "E_VERIFY_INCOMPLETE"},
                )
    else:
        status = "unknown"
    cause_code = exc.code
    if status == "partial":
        exc = Error("E_PARTIAL", exc.message, exc.details | {"cause_code": cause_code})
    elif status == "unknown" and exc.code == "E_NATIVE_FAILURE":
        exc = Error("E_OUTCOME_UNKNOWN", exc.message, exc.details | {"cause_code": cause_code})
    run["status"], run["error_code"] = status, exc.code
    try:
        operations.checkpoint_domain(run)
    except Error:
        pass  # the receipt still says running, which blocks further writes: the safe side
    exc.details |= {
        "operation_id": run["operation_id"],
        "receipt_status": status,
        "rollback_performed": False,
        "automatic_retry": False,
        "dispatch_state": "dispatched" if exc.details.get("request_sent") else "unknown",
    }
    if status in ("verification_incomplete", "unknown"):
        exc.details["next_action"] = (
            "query the operation and inspect the target and the incomplete native check; "
            "do not repeat the write or clear the receipt without an actual inspection"
        )
    exc.details.update(native_read_recovery.details(pending))
    exc.details.update(native_diagnostic_recovery.details(diagnostic))
    if status == "partial":
        receipt = {
            "operation_id": run["operation_id"],
            "status": "partial",
            "result": {"target": p.target, "before": p.before, "observed_after": observed_after},
            "persisted": None,
            "verification": {
                "status": "incomplete",
                "level": "selected_postconditions_verified",
                "checks": [],
                "observations": [
                    {
                        "observation": "native_failure_state",
                        "source": "plan.observe",
                        "independent": True,
                    }
                ],
                "not_checked": ["requested_postconditions", "persistence_after_failure"],
            },
            "_untrusted": ["result", "verification"],
        }
        exc.details["receipt"] = receipt
        exc.details.setdefault("_untrusted", []).append("receipt")
        try:
            run["result"] = operations.save_result(run["operation_id"], receipt)
            operations.checkpoint_domain(run)
        except Error as recording:
            raise Error(
                "E_OUTCOME_UNKNOWN",
                "the changed-state result could not be retained",
                {
                    "operation_id": run["operation_id"],
                    "dispatch_state": "dispatched",
                    "receipt_status": status,
                    "receipt": receipt,
                    "automatic_retry": False,
                    "cause_code": recording.code,
                    "_untrusted": ["receipt"],
                },
            ) from None
        exc.message = (
            "Creo rejected the operation and the model was left changed; "
            "inspect it before any further write"
        )
    elif status == "unknown" and cause_code == "E_NATIVE_FAILURE":
        exc.message = (
            "Creo rejected the operation and what it left could not be read back; "
            "inspect Creo first"
        )
    return exc
