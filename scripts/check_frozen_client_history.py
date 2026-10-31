"""Check a runtime upgrade against actual old-client history using loopback only.

Both executables are explicit inputs. The private fixture directory retains the
SQLite files, synthetic service token and complete answers; never distribute it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.fixture import Server, World  # noqa: E402


def rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT id,command,status,body FROM operations ORDER BY rowid").fetchall()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def check(previous: Path, candidate: Path, output: Path):
    if output.exists():
        raise ValueError("Use a new private fixture output; do not clear history")
    output.mkdir(parents=True)
    work = output / "兼容历史 Unicode path" / "workspace"
    work.mkdir(parents=True)
    history = output / "兼容历史 Unicode path" / "history"
    world = World(work)
    part = world.part("block.prt")
    world.write_version(work, "block.prt", part)
    world.active = "block.prt"
    server = Server(world)
    token_file = output / "synthetic-service-token"
    token_file.write_text(world.token, encoding="ascii")
    scope = output / "synthetic-scope.json"
    scope.write_text(
        json.dumps(
            {
                "scope_id": "runtime-upgrade-fixture",
                "tool": "creo-cli",
                "granted_by": "offline-fixture",
                "granted_at": "2026-10-31T00:00:00Z",
                "expires_at": None,
                "effects": ["observe", "session", "change", "persist", "artifact"],
                "dangerous": True,
                "roots": [str(work)],
                "outputs": [str(work)],
            }
        ),
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("CREO_CLI_")}
    env.update(
        CREO_CLI_CONFIG_DIR=str(history),
        CREO_CLI_WORKSPACE=str(work),
        CREO_CLI_SERVICE_URL=server.url,
        CREO_CLI_SERVICE_TOKEN_FILE=str(token_file),
        CREO_CLI_SCOPE_FILE=str(scope),
        CREO_CLI_PERMISSION="write",
        CREO_CLI_EXPERIMENTAL_NATIVE_WRITES="1",
    )
    answers = []

    def invoke(exe, args, status=0):
        process = subprocess.run(
            [str(exe), *args, "--compact"],
            env=env,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=60,
        )
        answer = json.loads(process.stdout.decode("utf-8"))
        answers.append(
            {
                "client": "previous" if exe == previous else "candidate",
                "command": args[:2],
                "exit_code": process.returncode,
                "answer": answer,
            }
        )
        if process.returncode != status or answer["ok"] != (status == 0):
            raise AssertionError(
                "Unexpected result: "
                + str(args[:2])
                + " / "
                + str(answer.get("error", {}).get("code"))
            )
        if world.token in process.stdout.decode("utf-8") + process.stderr.decode("utf-8"):
            raise AssertionError("Synthetic service credential escaped")
        return answer

    def change(exe, args, unknown=False):
        preview = invoke(exe, [*args, "--dry-run"])["data"]
        if unknown:
            world.drop = "parameter.set"
        try:
            answer = invoke(
                exe, [*args, "--confirm", preview["confirm_token"]], 6 if unknown else 0
            )
        finally:
            world.drop = None
        return preview["confirm_token"], answer

    try:
        description = [
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "兼容回执 Unicode",
        ]
        change(previous, description)
        numeric = [
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "RUNTIME_RATIO",
            "--type",
            "real",
            "--value",
            "1.23456789012345",
            "--create",
        ]
        change(previous, numeric)
        unknown_args = [*description[:-1], "unknown 中文"]
        used_token, unknown = change(previous, unknown_args, unknown=True)
        if unknown["error"]["code"] != "E_OUTCOME_UNKNOWN":
            raise AssertionError("Expected a retained uncertain outcome")
        before = rows(history / "operations.sqlite3")
        if [r[2] for r in before].count("unknown") != 1:
            raise AssertionError("Old client did not retain exactly one unknown operation")
        raw = json.dumps(before, ensure_ascii=False)
        if "兼容回执 Unicode" not in raw or "1.23456789012345" not in raw:
            raise AssertionError("Old history lacks the Unicode or binary64 fixture")
        old_listing = invoke(previous, ["operation", "list"])["data"]
        old_details = {
            r[0]: invoke(previous, ["operation", "show", "--id", r[0]])["data"] for r in before
        }
        new_listing = invoke(candidate, ["operation", "list"])["data"]
        if old_listing != new_listing:
            raise AssertionError("New runtime changes original logical history listing")
        for ident, expected in old_details.items():
            actual = invoke(candidate, ["operation", "show", "--id", ident])["data"]
            # operation_status.observed_at is the time this read occurred, not
            # a field of the original stored receipt. Compare every other field.
            comparable = deepcopy(actual)
            if "operation_status" in comparable:
                now = comparable["operation_status"]["observed_at"]
                before_time = expected["operation_status"]["observed_at"]
                if datetime.fromisoformat(now) < datetime.fromisoformat(before_time):
                    raise AssertionError("Observation timestamp moved backwards")
                comparable["operation_status"]["observed_at"] = before_time
            if comparable != expected:
                raise AssertionError("New runtime changes an old logical receipt")
        events_before_repeat = list(world.events)
        old_refused = invoke(previous, [*unknown_args, "--confirm", used_token], 6)
        refused = invoke(candidate, [*unknown_args, "--confirm", used_token], 6)
        if (
            refused["error"]["code"] != old_refused["error"]["code"]
            or refused["error"]["code"] != "E_CONFLICT"
            or refused["error"]["details"].get("conflict") != "token_used"
            or refused["error"]["details"].get("dispatch_state") != "not_started"
            or world.events != events_before_repeat
        ):
            raise AssertionError("Unknown confirmation was replayed or incorrectly classified")
        after = rows(history / "operations.sqlite3")
        if before != after:
            raise AssertionError("Reading/refusing replay rewrote the original operations")
        with sqlite3.connect(history / "operations.sqlite3") as db:
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise AssertionError("History integrity check failed")
        for command in ("reference", "context", "doctor", "changelog"):
            invoke(candidate, [command])
        result = {
            "status": "passed",
            "CAD_started": False,
            "service": "controlled loopback substitute",
            "previous_exe_sha256": hashlib.sha256(previous.read_bytes()).hexdigest(),
            "candidate_exe_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "old_operations": len(before),
            "unknown_operations_preserved": 1,
            "old_operation_rows_sha256": digest(before),
            "new_operation_rows_sha256": digest(after),
            "logical_receipts_identical": True,
            "unicode_and_binary64_preserved": True,
            "fresh_observation_time_compared_separately": "operation_status.observed_at",
            "unknown_repeat_sent_no_service_calls": True,
            "repeat_refusal_code_matches_previous": refused["error"]["code"],
            "sqlite_integrity": "ok",
            "self_description": ["reference", "context", "doctor", "changelog"],
        }
        (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        # Complete answers are private review evidence and can include fixture-only tokens.
        (output / "answers-PRIVATE.json").write_text(
            json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        server.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-client", required=True, type=Path)
    parser.add_argument("--candidate-client", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            check(
                args.previous_client.resolve(),
                args.candidate_client.resolve(),
                args.output.resolve(),
            )
        )
    )
