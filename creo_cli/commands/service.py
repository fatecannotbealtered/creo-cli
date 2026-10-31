"""Persist checked component bytes and an auto-start registry; launching remains explicit."""

from .. import driver, operations, safety, service_installation
from ..core import Error
from ..registry import Command, Param
from ..schemas import S, array, shape, written


def install(opts):
    with safety.lock():
        if not opts.get("dry_run"):
            op_id = safety.token_operation(opts.get("confirm"))
            if operations.get(op_id)["status"] != "planned":
                raise Error(
                    "E_CONFLICT",
                    "installation was already dispatched",
                    {
                        "conflict": "token_used",
                        "operation_id": op_id,
                        "dispatch_state": "not_started",
                    },
                )
        client, plan = service_installation.plan(opts)
        return driver.write("service install", opts, client, plan)


COMMANDS = [
    Command(
        "service install",
        "Persist a source-bound service bundle into a new installation directory; existing "
        "different or incomplete targets are preserved. Does not register or load Creo.",
        install,
        written(
            shape(
                {
                    "installed_to": S,
                    "protk_dat": S,
                    "files": shape({}),
                    "version": S,
                    "then": array(S),
                },
                ("installed_to", "protk_dat", "version", "then"),
            )
        ),
        (
            Param("from", required=True, description="concrete component directory or ZIP"),
            Param(
                "target",
                description="new directory inside the authorized workspace; "
                "defaults to the tool service/version directory",
            ),
        ),
        write=True,
        untrusted=("result",),
        example="--from service-bundle --target D:/owned-workspace/components",
    ),
]
