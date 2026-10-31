"""workflow run: several writes under one preview and one confirmation.

The public preview checks existing targets, bounded dependencies and every step's scope.
On confirmation each migrated leaf re-plans against the current state, confirms once,
reads back and commits its public receipt. First failure stops; applied facts survive.
"""

from __future__ import annotations

from .. import engine, operations
from ..core import Error, read_request
from ..registry import REQUEST, Command, Param
from ..schemas import INT, B, S, array, shape, written
from ..validation import strict, text

MAX_STEPS = 32
# Writes that are not steps: a workflow within a workflow, installing the service, recording
# a person's inspection, and anything dangerous -- that keeps its own two gates, alone.
EXCLUDED = {
    "workflow run",
    "service install",
    "operation resolve",
    "assembly component redefine",
}
STEP = strict(
    {
        "command": text(pattern=r"^[a-z][a-z-]*(?: [a-z][a-z-]*)+$", maximum=100),
        "args": {"type": "object", "additionalProperties": True},
    },
    ("command", "args"),
)
SCHEMA = strict(
    {"steps": {"type": "array", "items": STEP, "minItems": 1, "maxItems": MAX_STEPS}},
    ("steps",),
)
EXAMPLE = {
    "steps": [
        {
            "command": "parameter set",
            "args": {
                "model": "bracket",
                "name": "PLATE_LENGTH",
                "type": "real",
                "value": "80",
                "create": True,
            },
        },
        {"command": "model regenerate", "args": {"model": "bracket"}},
        {"command": "model save", "args": {"model": "bracket"}},
    ]
}
KINDS = {"string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,)}


def _options(command: Command, args: dict, index: int) -> dict:
    """A step's arguments as the command's own options, checked against its declared params."""
    params = {p.name: p for p in command.params}
    where = f"request.steps[{index}].args"
    unknown = sorted(set(args) - set(params))
    missing = sorted(p for p, d in params.items() if d.required and p not in args)
    if unknown or missing:
        raise Error(
            "E_VALIDATION",
            "a step's args are its command's flags, by name",
            {"path": where, "unknown": unknown, "missing": missing},
        )
    opts = {
        "dry_run": False,
        "confirm": None,
        "dangerous": False,
        "timeout": 30,
        "fields": None,
        "_command_path": command.path,
    }
    for p in command.params:
        value = args.get(p.name, p.default)
        if p.name in args:
            inline = p.name == "request" and isinstance(value, dict)
            if not inline and (
                not isinstance(value, KINDS[p.type])
                or (p.type != "boolean" and isinstance(value, bool))
            ):
                raise Error(
                    "E_VALIDATION",
                    f"--{p.name} takes a {p.type}",
                    {"path": f"{where}.{p.name}"},
                )
            if p.choices and value not in p.choices:
                raise Error(
                    "E_VALIDATION",
                    f"--{p.name} is one of {', '.join(map(str, p.choices))}",
                    {"path": f"{where}.{p.name}"},
                )
        opts[p.name.replace("-", "_")] = value
    return opts


def _steps(q: dict) -> list[tuple]:
    """Every step as (index, command, options, prepare, plan), its write captured unrun."""
    from ..registry import BY_PATH

    out = []
    for i, step in enumerate(q["steps"]):
        command = BY_PATH.get(step["command"])
        if command is None or not command.write or command.dangerous or command.path in EXCLUDED:
            raise Error(
                "E_VALIDATION",
                "a step is a write command that is not dangerous: part create, feature extrude, "
                "model save, ... (reference lists them)",
                {"path": f"request.steps[{i}].command", "given": step["command"]},
            )
        opts = _options(command, step["args"], i)
        sink: list = []
        token = engine.CAPTURE.set(sink)
        try:
            command.handler(opts)
        finally:
            engine.CAPTURE.reset(token)
        if len(sink) != 1:
            raise Error(
                "E_VALIDATION",
                "this command cannot be a workflow step",
                {"path": f"request.steps[{i}]"},
            )
        _, prepare, plan, normalized_opts = sink[0]
        out.append((i, command, normalized_opts, prepare, plan))
    return out


def _write_run(opts: dict) -> dict:
    from ..workflow_tasks import run as task_run

    return task_run(opts, read_request(opts["request"]))


def run(opts: dict) -> dict:
    from ..workflow_tasks import run as task_run

    q = read_request(opts["request"])
    if any("kind" in s or "id" in s for s in q.get("steps", []) if isinstance(s, dict)):
        return task_run(opts, q)
    return _write_run(opts)


def plan(opts: dict) -> dict:
    from ..workflow_tasks import plan as task_plan

    return task_plan(opts, read_request(opts["request"]))


def show(opts: dict) -> dict:
    record = operations.get(opts["id"])
    if record["command"] != "workflow run":
        raise Error("E_VALIDATION", "receipt belongs to a different command")
    return {
        "receipt": record,
        "trace": operations.load_result(record),
        "workflow": record.get("driver_workflow"),
        "_untrusted": ["receipt", "trace"],
    }


TASK_SCHEMA = strict(
    {"steps": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": MAX_STEPS}},
    ("steps",),
)
COMMANDS = [
    Command(
        "workflow plan",
        (
            "Validate a dependency-ordered read/select/assert/write task "
            "and inspect its read prefix; execution scope and public plan are "
            "checked by workflow run --dry-run"
        ),
        plan,
        shape({"steps": array(shape({})), "observations": shape({})}),
        (REQUEST,),
        request=TASK_SCHEMA,
        request_example=EXAMPLE,
        example="--request task.json",
    ),
    Command(
        "workflow show",
        "Read one workflow receipt and its recorded execution trace",
        show,
        shape(
            {
                "receipt": shape({}),
                "trace": {"type": ["object", "null"]},
                "workflow": {"type": ["object", "null"]},
            }
        ),
        (Param("id", required=True),),
        untrusted=("receipt", "trace"),
        example="--id <operation_id>",
    ),
    Command(
        "workflow run",
        "Run a public lifecycle task on existing open models with literal scope; "
        "each migrated non-dangerous leaf retains its scope, drift checks and receipt; "
        "initial leaf/file bindings remain fixed except verified authorized transitions; "
        "persistence describes final per-object state, including save then modify; "
        "first failure stops remaining steps, with partial/unknown facts retained. "
        "Possible service operations depend on the eligible step commands; "
        "actual calls are task-specific",
        run,
        written(
            shape(
                {
                    "steps": array(
                        shape(
                            {
                                "step": INT,
                                "command": S,
                                "operation_id": S,
                                "result": {},
                                "persisted": B,
                            },
                            (),
                        )
                    )
                },
                ("steps",),
            )
        ),
        (REQUEST,),
        write=True,
        untrusted=("result",),
        request=TASK_SCHEMA,
        request_example=EXAMPLE,
        example="--request build.json",
        service_ops=("session.status",),
    ),
]
