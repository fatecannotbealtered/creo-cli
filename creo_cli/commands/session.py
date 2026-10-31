"""session status, session cd: the running Creo, as a whole."""

from __future__ import annotations

from .. import engine, operations, owned_exit, paths
from ..core import Error
from ..registry import Command, Param
from ..schemas import NB, NI, NS, PROBLEM, WRITTEN, B, S, array, shape, written
from ..transport import SETUP, Client


def status(opts: dict) -> dict:
    """What Creo is doing now and what would stop a write -- an answer even when Creo is down."""
    out = {
        "connected": False,
        "creo_version": None,
        "creo_build": None,
        "working_directory": None,
        "working_directory_in_workspace": None,
        "active_model": None,
        "model_count": None,
        "creation_api": None,
        "native_sketch_available": None,
        "problems": [],
        "_untrusted": ["working_directory", "active_model"],
    }

    def problem(code: str, message: str, fix: str) -> None:
        out["problems"].append({"code": code, "message": message, "fix": fix})

    try:
        recovery = operations.recovery_diagnostics()
        out["operation_recovery"] = recovery
        unresolved = recovery["scoped_unresolved"] + recovery["legacy_unscoped"]
        if unresolved:
            problem(
                "unresolved_write",
                "unresolved operations require target/dependency assessment; legacy writes "
                "remain globally gated: " + ", ".join(r["operation_id"] for r in unresolved),
                "creo-cli operation show --id <operation_id>; follow recovery_guidance for "
                "current observation and evidence registration. Preview the intended target "
                "to assess conflicts; no target was assessed by session status",
            )
    except Error as exc:
        problem("receipts_unreadable", exc.message, "inspect the retained state directory")

    try:
        with Client(opts.get("timeout", 30)) as client:
            client.health()
            s = engine.session(client)
    except Error as exc:
        if exc.details.get("service_code") == "E_BUSY":
            problem(
                "service_busy",
                exc.message,
                "inspect the Creo window and any modal dialog; retain the original operation "
                "and unknown state. Retry an independent read only after Creo is responsive; "
                "do not replay the write or reinstall the running service",
            )
        else:
            problem("service_unavailable", exc.message, str(exc.details.get("fix") or SETUP))
        return out
    out |= {
        "connected": True,
        "creo_version": s.get("creo_version"),
        "creo_build": s.get("creo_build"),
        "working_directory": s["working_directory"],
        "active_model": s.get("active_model"),
        "model_count": len(s["models"]),
        "creation_api": s["creation_api"],
        "native_sketch_available": s["native_sketch_available"],
    }
    if not s["creation_api"]:
        problem(
            "no_creation_api",
            "the session can read models but not build features",
            "run the service as an Object TOOLKIT Java application under the ObjectToolkitJava "
            "licence",
        )
    if not s["native_sketch_available"]:
        problem(
            "native_sketch_library_not_loaded",
            "rectangles and polygons cannot be drawn in this session; circles and ellipses can",
            "register creo_cli_sketch.dll with the service and let Creo load it (docs/SERVICE.md)",
        )
    try:
        paths.contained(s["working_directory"], directory=True)
        out["working_directory_in_workspace"] = True
    except Error as exc:
        if exc.code == "E_CONFIG":
            problem(
                "workspace_not_configured",
                exc.message,
                "the user sets CREO_CLI_WORKSPACE to a disposable directory",
            )
        else:
            out["working_directory_in_workspace"] = False
            problem(
                "working_directory_outside_workspace",
                "Creo's working directory is not inside the workspace, so writes are refused",
                "creo-cli session cd --path <directory inside CREO_CLI_WORKSPACE>",
            )
    return out


def _prepare_cd(opts: dict) -> dict:
    return {"target": paths.contained(opts["path"], directory=True)}


def _plan_cd(client: Client, opts: dict, pre: dict) -> engine.Plan:
    target = pre["target"]
    s = engine.session(client)

    def verify(c: Client, data: dict):
        now = engine.session(c)["working_directory"]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "working_directory_is_target",
                    engine.same_path(now, target),
                    working_directory=now,
                ),
                engine.check(
                    "reply_names_the_target", engine.same_path(data["working_directory"], target)
                ),
            ],
            "not_checked": ["other_session_settings"],
        }

    return engine.Plan(
        op="session.cd",
        request={"path": str(target)},
        target="session",
        binding={"working_directory": s["working_directory"]},
        preview={
            "command": "session cd",
            "from": s["working_directory"],
            "to": str(target),
            "effect": "Creo's working directory: where new models are written and where Creo "
            "looks for the models a model references",
        },
        verify=verify,
        observe=lambda c: engine.session(c)["working_directory"],
        before=s["working_directory"],
        arguments={"path": opts["path"]},
    )


def cd(opts: dict) -> dict:
    return engine.write("session cd", opts, _prepare_cd, _plan_cd)


COMMANDS = [
    Command(
        "session exit",
        "Normally terminate only an exact owned full-component empty Creo session; "
        "verify the held native process and correlated exit evidence",
        owned_exit.execute,
        written(shape({"exit_observation": shape({}), "entrypoint": S}, ("entrypoint",))),
        (
            Param(
                "launch-record",
                required=True,
                description="exact owned startup/launch.json inside the workspace",
            ),
        ),
        write=True,
        dangerous=True,
        untrusted=WRITTEN,
        example="--launch-record startup/launch.json",
        service_ops=("session.exit-state", "session.exit"),
    ),
    Command(
        "session status",
        "The running Creo: version, working directory, active model, model count, and what would "
        "stop a write",
        status,
        shape(
            {
                "connected": B,
                "creo_version": NS,
                "creo_build": NS,
                "working_directory": NS,
                "working_directory_in_workspace": NB,
                "active_model": NS,
                "model_count": NI,
                "creation_api": NB,
                "native_sketch_available": NB,
                "problems": array(PROBLEM),
                "operation_recovery": shape({}),
                "_untrusted": array(S),
            },
            ("connected", "working_directory", "active_model", "model_count", "problems"),
        ),
        untrusted=("working_directory", "active_model"),
        service_ops=("session.status",),
    ),
    Command(
        "session cd",
        "Point Creo's working directory, where new models are written, at a directory in the "
        "workspace",
        cd,
        written(shape({"working_directory": S}, ("working_directory",))),
        (Param("path", required=True, description="a directory inside the workspace"),),
        write=True,
        untrusted=WRITTEN,
        example="--path parts",
        service_ops=("session.cd",),
    ),
]
