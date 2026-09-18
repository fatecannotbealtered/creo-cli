"""JSON-first public entry. Unknown arguments are refused, never silently ignored."""
from __future__ import annotations
import argparse
import json
import math
import os
import signal
import sys
import time
from . import __version__, registry
from .core import Error, project, redact, validate_schema

class Parser(argparse.ArgumentParser):
    def error(self, text):
        raise Error("E_USAGE", "invalid command arguments", {"reason": text.split(":", 1)[0], "hint": "run reference for accepted parameters"})

def globals_on(p, inherited=False):
    absent = argparse.SUPPRESS if inherited else None
    p.add_argument("--format", choices=("json", "text", "raw"), default=absent if inherited else "json")
    for k in ("json", "compact", "quiet", "dry-run"):
        p.add_argument("--"+k, action="store_true", default=absent if inherited else False)
    for k in ("fields", "confirm"):
        p.add_argument("--"+k, default=absent)
    p.add_argument("--timeout", type=float, default=absent if inherited else 30.0)

def parser():
    p = Parser(prog="creo-cli", allow_abbrev=False, description="AI-native Creo automation. Use reference for machine capabilities.")
    globals_on(p)
    p.add_argument("--version", action="store_true")
    root = p.add_subparsers(dest="group")
    groups = {}
    for c in registry.COMMANDS:
        parts = c.path.split()
        if len(parts) == 1:
            leaf = root.add_parser(parts[0], help=c.description, allow_abbrev=False)
        else:
            if parts[0] not in groups:
                group = root.add_parser(parts[0], allow_abbrev=False)
                globals_on(group, True)
                groups[parts[0]] = group.add_subparsers(dest="verb")
            leaf = groups[parts[0]].add_parser(parts[1], help=c.description, allow_abbrev=False)
        globals_on(leaf, True)
        for item in c.params:
            options = {"required": item.required, "default": item.default}
            if item.type == "integer":
                options["type"] = int
            if item.choices:
                options["choices"] = item.choices
            leaf.add_argument("--"+item.name, **options)
        leaf.set_defaults(_dispatch_command=c)
    return p

def trace(path):
    target = os.environ.get("CREO_CLI_TEST_TRACE")
    if target:
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(path+"\n")
        except OSError:
            pass

def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    t, opts, status = time.monotonic(), {}, 0
    old = None
    def interrupted(_s, _f):
        raise KeyboardInterrupt()
    try:
        old = signal.signal(signal.SIGTERM, interrupted)
    except (ValueError, AttributeError):
        pass
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if not args:
            raise Error("E_USAGE", "a command is required; run reference or --help")
        opts = vars(parser().parse_args(args))
        if not math.isfinite(opts["timeout"]) or not .1 <= opts["timeout"] <= 300:
            raise Error("E_USAGE", "--timeout must be finite and in 0.1..300 seconds")
        if opts["version"]:
            if opts.get("_dispatch_command") or opts["dry_run"] or opts.get("confirm"):
                raise Error("E_USAGE", "--version cannot be combined with a task or write flags")
            data = {"tool": "creo-cli", "version": __version__}
        else:
            c = opts.get("_dispatch_command")
            if c is None:
                raise Error("E_USAGE", "a leaf command is required")
            if "limit" in opts and not 1 <= opts["limit"] <= 1000 or "offset" in opts and opts["offset"] < 0:
                raise Error("E_USAGE", "limit must be 1..1000; offset must be non-negative")
            if opts["dry_run"] and opts.get("confirm"):
                raise Error("E_USAGE", "dry-run and confirm are mutually exclusive")
            if not c.write and (opts["dry_run"] or opts.get("confirm")):
                raise Error("E_USAGE", "write flags are invalid on reads")
            if c.write and opts.get("fields") is not None:
                raise Error("E_USAGE", "projection is read-only; write previews must remain visible")
            if c.write and not opts["dry_run"] and not opts.get("confirm"):
                raise Error("E_CONFIRMATION_REQUIRED", "run --dry-run before confirming a write")
            trace(c.path)
            from .service import execute
            data = execute(c.path, opts)
            validate_schema(data, registry.SCHEMAS["dry_run" if c.write and opts["dry_run"] else c.schema]["json_schema"])
        data = project(redact(data), opts.get("fields"))
        document = {"ok": True, "schema_version": "1.0", "data": data}
    except Error as exc:
        status, document = exc.exit, {"ok": False, "schema_version": "1.0", "error": redact(exc.payload())}
    except KeyboardInterrupt:
        exc = Error("E_INTERRUPTED", "interrupted; inspect state before another write", {"state_unknown": True})
        status, document = exc.exit, {"ok": False, "schema_version": "1.0", "error": exc.payload()}
    except SystemExit as exc:
        return int(exc.code or 0)  # explicit --help is a text escape hatch
    except Exception as exc:
        error = Error("E_UNKNOWN", "unexpected error; raw exception text is not exposed", {"exception_type": type(exc).__name__, "state_unknown": True})
        status, document = 1, {"ok": False, "schema_version": "1.0", "error": error.payload()}
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)
    document["meta"] = {"duration_ms": round((time.monotonic()-t)*1000)}
    fmt = "json" if opts.get("json") else opts.get("format", "json")
    payload = document if fmt == "json" else document.get("data", document.get("error"))
    try:
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2 if fmt == "text" else None,
                          separators=(",", ":") if opts.get("compact") else None)+"\n"
    except (ValueError, TypeError, RecursionError):
        exc = Error("E_INTEGRITY", "output could not be safely encoded", {"state_unknown": True})
        text, status = json.dumps({"ok": False, "schema_version": "1.0", "error": exc.payload(), "meta": document["meta"]})+"\n", 1
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except BrokenPipeError:
        return 1
    return status
