"""Source/actual-EXE transport for the limited C18 controlled contract checks."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def trace_invocation(command, code, value, stderr=""):
    trace = os.environ.get("CREO_CLI_CONTRACT_TRACE")
    if not trace:
        return

    def redact(item):
        if isinstance(item, dict):
            return {
                key: "[REDACTED_TOKEN]"
                if key in ("confirm_token", "service_token")
                else redact(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [redact(child) for child in item]
        return item

    directory = Path(trace)
    directory.mkdir(parents=True, exist_ok=True)
    safe = list(command)
    for index, word in enumerate(safe[:-1]):
        if word == "--confirm":
            safe[index + 1] = "[REDACTED_CONFIRM_TOKEN]"
    with (directory / "invocations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"command": safe, "returncode": code, "stdout": redact(value), "stderr": stderr}
            )
            + "\n"
        )


def external_cli(env, args, *, fresh=False, stdin=None):
    executable = os.environ.get("CREO_CLI_CONTRACT_EXE")
    if not executable and not fresh:
        return None
    command = [executable] if executable else [sys.executable, "-m", "creo_cli"]
    command += list(map(str, args))
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    trace_invocation(command, result.returncode, json.loads(result.stdout), result.stderr)
    return result


class ContractCliMixin:
    def cli(self, *args, status=0, env=None, stdin=None):
        result = external_cli(env or self.env, args, stdin=stdin)
        if result is None:
            value = super().cli(*args, status=status, env=env, stdin=stdin)
            trace_invocation(["source-main", *map(str, args)], status, value)
            return value
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertNotIn(self.world.token, result.stdout + result.stderr)
        return value
