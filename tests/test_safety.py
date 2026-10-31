"""Tokens, locks, strict input, containment, redaction: the mechanisms every write relies on."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creo_cli import paths, safety
from creo_cli.core import Error, atomic_write, decode, number, project, redact

ROOT = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name).resolve()
        self.env = {
            "CREO_CLI_CONFIG_DIR": str(self.dir / "state"),
            "CREO_CLI_PERMISSION": "write",
            "CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "1",
            "CREO_CLI_WORKSPACE": str(self.dir),
        }
        p = patch.dict(os.environ, self.env, clear=False)
        p.start()
        self.addCleanup(p.stop)
        self.bound = safety.scope("feature extrude", "block.prt", {"x": 1}, "rev")


class Tokens(Base):
    def test_single_use(self):
        t, _ = safety.issue(self.bound)
        safety.consume(t, self.bound)
        with self.assertRaises(Error) as e:
            safety.consume(t, self.bound)
        self.assertEqual(e.exception.code, "E_CONFLICT")

    def reason(self, token, bound, now=None):
        with self.assertRaises(Error) as e:
            safety.consume(token, bound, now=now)
        self.assertEqual(e.exception.code, "E_CONFLICT")
        return e.exception.details["reason"], e.exception.details.get("changed"), str(e.exception)

    def test_expiry(self):
        t, _ = safety.issue(self.bound, now=100)
        reason, _, message = self.reason(t, self.bound, now=100 + safety.TTL + 600)
        self.assertEqual(reason, "expired")
        self.assertIn("10 min ago", message)

    def test_every_scope_field_is_bound(self):
        t, _ = safety.issue(self.bound)
        for k in self.bound:
            with self.subTest(key=k), self.assertRaises(Error):
                safety.consume(t, self.bound | {k: "changed"})

    def test_a_refusal_names_what_changed(self):
        # What a person confirming needs to know: their arguments differ, the model moved on
        # since the preview, or the policy they confirm under is not the one they previewed in.
        engine = {"arguments": {"model": "block"}, "request": {"feature_id": 7}}
        bound = safety.scope("feature delete", "block.prt", engine, "rev")
        t, _ = safety.issue(bound)
        cases = (
            (
                bound | {"arguments": engine | {"arguments": {"model": "plate"}}},
                "arguments_changed",
                ["arguments"],
            ),
            (bound | {"command": "feature rename"}, "arguments_changed", ["command"]),
            (bound | {"revision": "rev2"}, "state_changed", ["state"]),
            # Same arguments resolving to another request: the model is what changed.
            (
                bound | {"arguments": engine | {"request": {"feature_id": 9}}},
                "state_changed",
                ["state"],
            ),
            (bound | {"permission": "read"}, "policy_changed", ["policy"]),
        )
        for changed, reason, parts in cases:
            with self.subTest(reason=reason, parts=parts):
                self.assertEqual(self.reason(t, changed)[:2], (reason, parts))
        safety.consume(t, bound)
        self.assertEqual(self.reason(t, bound)[0], "already_used")

    def test_policy_is_part_of_the_scope(self):
        t, _ = safety.issue(self.bound)
        with patch.dict(os.environ, {"CREO_CLI_PERMISSION": "read"}):
            changed = safety.scope("feature extrude", "block.prt", {"x": 1}, "rev")
        self.assertEqual(self.reason(t, changed)[:2], ("policy_changed", ["policy"]))

    def test_malformed(self):
        for t in ("ct_", "ct_a.b", "ct_" + "a" * 3000, "bad"):
            with self.subTest(token=t):
                self.assertEqual(self.reason(t, self.bound)[0], "malformed")
        with self.assertRaises(Error) as e:
            safety.consume(None, self.bound)
        self.assertEqual(e.exception.code, "E_CONFIRMATION_REQUIRED")

    def test_another_machine_cannot_mint_one(self):
        t, _ = safety.issue(self.bound)
        (safety.directory() / "confirm.secret").write_bytes(b"x" * 32)
        with self.assertRaises(Error):
            safety.consume(t, self.bound)

    def test_corrupt_secret_and_ledger(self):
        t, _ = safety.issue(self.bound)
        (safety.directory() / "consumed.sqlite3").mkdir()
        with self.assertRaises(Error) as e:
            safety.consume(t, self.bound)
        self.assertEqual(e.exception.code, "E_IO")
        (safety.directory() / "confirm.secret").write_bytes(b"bad")
        with self.assertRaises(Error) as e:
            safety.consume("ct_fake", self.bound)
        self.assertEqual(e.exception.code, "E_INTEGRITY")

    def test_nonces(self):
        self.assertEqual(len({safety.issue(self.bound, now=100)[0] for _ in range(64)}), 64)

    def test_one_consumer_across_threads_and_processes(self):
        t, _ = safety.issue(self.bound)

        def consume(_):
            try:
                safety.consume(t, self.bound)
                return "ok"
            except Error as e:
                return e.code

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(consume, range(16)))
        self.assertEqual((results.count("ok"), set(results)), (1, {"ok", "E_CONFLICT"}))
        t2, _ = safety.issue(self.bound)
        program = (
            "import json,sys\nfrom creo_cli.safety import consume\nfrom creo_cli.core import "
            "Error\n"
            "x=json.load(sys.stdin)\ntry:\n consume(x['token'],x['scope']);print('ok')\nexcept "
            "Error as e:print(e.code)\n"
        )

        def call(_):
            return subprocess.run(
                [sys.executable, "-c", program],
                input=json.dumps({"token": t2, "scope": self.bound}),
                text=True,
                capture_output=True,
                cwd=ROOT,
                env=dict(os.environ),
                timeout=30,
            ).stdout.strip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(4)))
        self.assertEqual((results.count("ok"), set(results)), (1, {"ok", "E_CONFLICT"}))

    def test_policy_gate(self):
        safety.require_write()
        with patch.dict(os.environ, {"CREO_CLI_PERMISSION": "read"}), self.assertRaises(Error) as e:
            safety.require_write()
        self.assertEqual(e.exception.code, "E_FORBIDDEN")
        with (
            patch.dict(os.environ, {"CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "0"}),
            self.assertRaises(Error),
        ):
            safety.require_write()
        with (
            patch.dict(os.environ, {"CREO_CLI_PERMISSION": "admin"}),
            self.assertRaises(Error) as e,
        ):
            safety.permission()
        self.assertEqual(e.exception.code, "E_CONFIG")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(safety.permission(), "read")


class Locks(Base):
    def test_exclusive_and_released(self):
        with safety.lock("fixture"), self.assertRaises(Error):
            with safety.lock("fixture"):
                pass
        with safety.lock("fixture"):
            pass

    def test_released_on_exception(self):
        with self.assertRaises(ValueError), safety.lock("fixture"):
            raise ValueError()
        with safety.lock("fixture"):
            pass


class Files(Base):
    def test_atomic_no_clobber(self):
        p = self.dir / "file"
        atomic_write(p, b"one", overwrite=False)
        with self.assertRaises(Error):
            atomic_write(p, b"two", overwrite=False)
        self.assertEqual(p.read_bytes(), b"one")
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])

    def test_containment(self):
        (self.dir / "sub").mkdir()
        self.assertEqual(paths.contained("sub", directory=True), self.dir / "sub")
        for bad in ("..", "sub/../..", "\\\\server\\share", "//server/share", str(self.dir.parent)):
            with self.subTest(path=bad), self.assertRaises(Error):
                paths.contained(bad, directory=True)
        with self.assertRaises(Error) as e:
            paths.contained("missing")
        self.assertEqual(e.exception.code, "E_NOT_FOUND")
        with patch.dict(os.environ, {"CREO_CLI_WORKSPACE": ""}), self.assertRaises(Error) as e:
            paths.workspace()
        self.assertEqual(e.exception.code, "E_CONFIG")

    def test_versions(self):
        for name in ("block.prt.1", "block.prt.10", "block.prt.2", "blockx.prt.1"):
            (self.dir / name).write_bytes(name.encode())
        self.assertEqual(
            [Path(v["path"]).name for v in paths.model_files(self.dir, "block.prt")],
            ["block.prt.1", "block.prt.2", "block.prt.10"],
        )
        self.assertEqual(paths.version("block.prt.10"), 10)
        self.assertEqual(paths.version("notes.txt"), -1)


class Input(unittest.TestCase):
    def test_strict_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b'{"a":Infinity}', b"\xff"):
            with self.subTest(raw=raw), self.assertRaises(Error):
                decode(raw)

    def test_huge_numbers_are_not_finite(self):
        self.assertFalse(number(10**1000))
        self.assertFalse(number(True))

    def test_projection_keeps_safety_metadata(self):
        r = project(
            {
                "items": [{"name": "a", "value": 1, "_untrusted": ["name"]}],
                "count": 1,
                "_untrusted": ["items"],
            },
            "items.name",
        )
        self.assertEqual(r["items"][0], {"name": "a", "_untrusted": ["name"]})
        self.assertEqual(r["count"], 1)
        with self.assertRaises(Error) as e:
            project({"a": 1, "c": 2}, "b")
        self.assertEqual(e.exception.details, {"field": "b", "available": ["a", "c"]})
        with self.assertRaises(Error) as e:
            project({"a": 1}, "a.b")
        self.assertIn("a is a value", str(e.exception))

    def test_projection_over_rows_that_differ(self):
        # A list's rows report what their kind has: a field some rows lack is left out of
        # those rows; one no row has is a mistake, named.
        rows = {
            "items": [
                {"name": "HOLE", "result": {"diameter": 10}},
                {"name": "ROUND", "result": None},
                {"name": "PROTRUSION"},
            ],
            "count": 3,
        }
        self.assertEqual(
            project(rows, "name,result.diameter")["items"],
            [
                {"name": "HOLE", "result": {"diameter": 10}},
                {"name": "ROUND", "result": None},
                {"name": "PROTRUSION"},
            ],
        )
        with self.assertRaises(Error) as e:
            project(rows, "name,result.depth")
        self.assertEqual(e.exception.details["field"], "items.result.depth")
        self.assertEqual(e.exception.details["available"], ["diameter"])

    def test_redaction(self):
        self.assertEqual(
            redact({"token": "x", "nested": [{"password": "y"}], "confirm_token": "ct_z"}),
            {
                "token": "[REDACTED]",
                "nested": [{"password": "[REDACTED]"}],
                "confirm_token": "ct_z",
            },
        )


class Requests(Base):
    def test_a_relative_request_is_found_in_the_workspace(self):
        from creo_cli.core import read_request

        (self.dir / "req").mkdir()
        (self.dir / "req" / "a.json").write_text('{"x": 1}', encoding="utf-8")
        self.assertEqual(read_request("req/a.json"), {"x": 1})
        with self.assertRaises(Error) as e:
            read_request("req/missing.json")
        self.assertEqual(e.exception.code, "E_NOT_FOUND")
        self.assertEqual(len(e.exception.details["tried"]), 2)
        self.assertTrue(all(Path(t).is_absolute() for t in e.exception.details["tried"]))

    def test_current_directory_wins_and_invalid_local_file_is_not_silently_replaced(self):
        from creo_cli.core import read_request

        cwd = self.dir / "caller"
        cwd.mkdir()
        (cwd / "request.json").write_text('{"x": 2}', encoding="utf-8")
        (self.dir / "request.json").write_text('{"x": 1}', encoding="utf-8")
        with patch("pathlib.Path.cwd", return_value=cwd):
            self.assertEqual(read_request("request.json"), {"x": 2})
            (cwd / "request.json").write_text("not json", encoding="utf-8")
            with self.assertRaises(Error) as caught:
                read_request("request.json")
        self.assertEqual(caught.exception.code, "E_VALIDATION")

    @unittest.skipUnless(os.name == "nt", "drive-relative paths are a Windows input form")
    def test_drive_relative_request_is_ambiguous_and_refused(self):
        from creo_cli.core import read_request

        with self.assertRaises(Error) as caught:
            read_request("C:request.json")
        self.assertEqual(caught.exception.code, "E_VALIDATION")


if __name__ == "__main__":
    unittest.main()
