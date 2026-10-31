"""JSON-first entry point. Unknown arguments are refused, never silently ignored."""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import time

from . import __version__
from .core import Error, project, redact, validate_schema


class Parser(argparse.ArgumentParser):
    def error(self, message):
        details = {
            "reason": message.split(":", 1)[0],
            "fix": "creo-cli reference --command '<command path>' lists the accepted flags",
        }
        if re.match(r"argument (?:group|subcommand_[0-9]+): invalid choice:", message):
            details["problem"] = "unknown_command"
        elif "unrecognized arguments" in message:
            details["problem"] = "unknown_flag"
        elif "required" in message:
            details["problem"] = "missing_parameter"
        else:
            details["problem"] = "invalid_value"
        # The choices a flag takes are the tool's own words; the value given is not echoed.
        choices = re.search(r"\(choose from (.*)\)\s*$", message)
        if choices:
            details["allowed"] = [c.strip().strip("'") for c in choices[1].split(",")]
        raise Error("E_USAGE", "invalid command arguments", details)


def globals_on(p: argparse.ArgumentParser, inherited: bool = False) -> None:
    from .registry import GLOBALS

    about = {g["name"]: g["description"] for g in GLOBALS}
    absent = argparse.SUPPRESS if inherited else None
    p.add_argument(
        "--format",
        choices=("json", "text", "raw"),
        default=absent if inherited else "json",
        help=about["format"],
    )
    for flag in ("json", "compact", "quiet", "dry-run", "dangerous"):
        p.add_argument(
            "--" + flag,
            action="store_true",
            default=absent if inherited else False,
            help=about[flag],
        )
    for flag in ("fields", "confirm"):
        p.add_argument("--" + flag, default=absent, help=about[flag])
    p.add_argument(
        "--timeout", type=float, default=absent if inherited else 30.0, help=about["timeout"]
    )


def parser() -> Parser:
    from . import registry

    p = Parser(
        prog="creo-cli",
        allow_abbrev=False,
        description="Creo Parametric for AI agents. Run `creo-cli reference`.",
    )
    globals_on(p)
    p.add_argument("--version", action="store_true", help="the tool's name and version")
    root = p.add_subparsers(dest="group")
    branches: dict[tuple[str, ...], object] = {(): root}
    nodes: dict[tuple[str, ...], Parser] = {}
    for c in registry.COMMANDS:
        parts = c.path.split()
        for depth, word in enumerate(parts):
            prefix = tuple(parts[:depth])
            path = (*prefix, word)
            terminal = depth == len(parts) - 1
            if path not in nodes:
                children = sorted(
                    {
                        candidate.path.split()[len(path)]
                        for candidate in registry.COMMANDS
                        if tuple(candidate.path.split()[: len(path)]) == path
                        and len(candidate.path.split()) > len(path)
                    }
                )
                node = branches[prefix].add_parser(
                    word,
                    help=c.description if terminal else ", ".join(children),
                    allow_abbrev=False,
                )
                globals_on(node, True)
                nodes[path] = node
                if not terminal:
                    branches[path] = node.add_subparsers(dest=f"subcommand_{depth + 1}")
            elif terminal or path not in branches:
                raise ValueError(f"duplicate command or command-prefix collision: {c.path}")
        leaf = nodes[tuple(parts)]
        for item in c.params:
            if item.type == "boolean":
                leaf.add_argument(
                    "--" + item.name, action="store_true", default=False, help=item.description
                )
                continue
            options = {"required": item.required, "default": item.default, "help": item.description}
            if item.type == "integer":
                options["type"] = int
            elif item.type == "number":
                options["type"] = float
            if item.choices:
                options["choices"] = item.choices
            leaf.add_argument("--" + item.name, **options)
        leaf.set_defaults(_command=c)
    return p


def check_flags(c, opts: dict) -> None:
    if (
        "limit" in opts
        and not 1 <= opts["limit"] <= 1000
        or "offset" in opts
        and opts["offset"] < 0
    ):
        raise Error("E_USAGE", "limit must be 1..1000 and offset non-negative")
    if opts["dry_run"] and opts.get("confirm"):
        raise Error("E_USAGE", "--dry-run and --confirm are mutually exclusive")
    if not c.write and (opts["dry_run"] or opts.get("confirm")):
        raise Error("E_USAGE", "--dry-run and --confirm are for writes; this command only reads")
    if c.write and opts.get("fields") is not None:
        raise Error("E_USAGE", "--fields is for reads; a write's preview and receipt stay whole")
    if opts["dangerous"] and not c.dangerous:
        raise Error("E_USAGE", "--dangerous is only accepted by commands marked dangerous")
    if (
        c.write
        and not opts["dry_run"]
        and not opts.get("confirm")
        and not (c.path == "operation resolve" and opts.get("outcome"))
    ):
        raise Error(
            "E_CONFIRMATION_REQUIRED",
            "a write runs as --dry-run first, then --confirm with the token it returns",
            {"fix": "creo-cli " + c.path + " ... --dry-run"},
        )
    if c.dangerous and not opts["dangerous"]:
        raise Error(
            "E_CONFIRMATION_REQUIRED",
            "this command is dangerous: it needs --dangerous with both --dry-run and --confirm",
            {"fix": "add --dangerous to both steps after reading the preview"},
        )


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    started, opts, status = time.monotonic(), {}, 0
    old = None

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt()

    try:
        old = signal.signal(signal.SIGTERM, interrupted)
    except (ValueError, AttributeError):
        pass
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if not args:
            raise Error("E_USAGE", "a command is required", {"fix": "creo-cli reference"})
        seen_flags = set()
        for arg in args:
            if arg.startswith("--"):
                flag = arg.split("=", 1)[0]
                if flag in seen_flags:
                    raise Error(
                        "E_USAGE",
                        "scalar flags must occur only once",
                        {
                            "problem": "conflicting_flags",
                            "fix": (
                                "remove the repeated flag; use reference for the command's "
                                "single-value parameters"
                            ),
                        },
                    )
                seen_flags.add(flag)
        opts = vars(parser().parse_args(args))
        from . import execution_budgets

        execution_budgets.validate(getattr(opts.get("_command"), "path", None), opts["timeout"])
        if opts["version"]:
            if opts.get("_command") or opts["dry_run"] or opts.get("confirm"):
                raise Error("E_USAGE", "--version cannot be combined with a command")
            data = {"tool": "creo-cli", "version": __version__}
        else:
            c = opts.get("_command")
            if c is None:
                raise Error(
                    "E_USAGE", "a complete command is required", {"fix": "creo-cli reference"}
                )
            check_flags(c, opts)
            from . import registry, timing

            opts["_command_path"] = c.path
            with timing.command(c.path, opts["timeout"]):
                timing.runtime_startup(time.monotonic() - started)
                try:
                    data = c.handler(opts)
                except Error as exc:
                    measured = timing.report()
                    if measured is not None:
                        exc.details["timing"] = measured
                    raise
            if not opts["dry_run"]:
                # The declaration is the promise: every field it names is listed as untrusted.
                listed = list(data.get("_untrusted", []))
                listed += [f for f in c.untrusted if f in data and f not in listed]
                if listed:
                    data["_untrusted"] = listed
            validate_schema(
                data,
                registry.SCHEMAS["dry_run" if c.write and opts["dry_run"] else c.schema_name][
                    "json_schema"
                ],
            )
        original_data = data
        data = redact(data)
        if opts.get("_command_path") == "reference":
            # These are immutable bundled schema documents, never upstream values.
            # A property named authorization is a definition here, not a credential.
            from . import driver_schema

            for key in ("schemas", "json_schemas"):
                if key in original_data:
                    data[key] = original_data[key]
            schema = {"index": "reference-index", "command": "reference-command"}.get(
                data.get("view"), "reference"
            )
            driver_schema.validate(schema, data)
        elif opts.get("_command_path") in ("context", "doctor"):
            from . import driver_schema

            if opts["_command_path"] == "context":
                # Generated task-scope summary, not an HTTP Authorization credential.
                # Its closed public schema is checked before emitting it.
                data["authorization"] = original_data["authorization"]
            driver_schema.validate(opts["_command_path"], data)
        data = project(data, opts.get("fields"))
        document = {"ok": True, "schema_version": "1.0", "data": data}
    except Error as exc:
        status, document = (
            exc.exit,
            {"ok": False, "schema_version": "1.0", "error": redact(exc.payload())},
        )
    except KeyboardInterrupt:
        exc = Error(
            "E_INTERRUPTED",
            "interrupted; inspect state before another write",
            {"state_unknown": True},
        )
        status, document = exc.exit, {"ok": False, "schema_version": "1.0", "error": exc.payload()}
    except SystemExit as exc:
        return int(exc.code or 0)  # an explicit --help is the human escape hatch
    except Exception as exc:
        error = Error(
            "E_UNKNOWN",
            "unexpected error; raw exception text is not exposed",
            {"exception_type": type(exc).__name__, "state_unknown": True},
        )
        status, document = (
            error.exit,
            {"ok": False, "schema_version": "1.0", "error": error.payload()},
        )
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)
    document["meta"] = {"duration_ms": round((time.monotonic() - started) * 1000)}
    fmt = "json" if opts.get("json") else opts.get("format", "json")
    payload = document if fmt == "json" else document.get("data", document.get("error"))
    try:
        text = (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                indent=2 if fmt == "text" else None,
                separators=(",", ":") if opts.get("compact") else None,
            )
            + "\n"
        )
    except (ValueError, TypeError, RecursionError):
        exc = Error("E_INTEGRITY", "output could not be safely encoded", {"state_unknown": True})
        document = {
            "ok": False,
            "schema_version": "1.0",
            "error": exc.payload(),
            "meta": document["meta"],
        }
        text, status = json.dumps(document) + "\n", exc.exit
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
