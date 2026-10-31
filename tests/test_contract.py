"""The machine contract: reference, schemas, envelopes, error codes, and the promises the
registry makes about itself. These guard the contract as a whole, independent of any one command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from creo_cli import __version__, registry
from creo_cli.contract_gen import CODES as CONTRACT
from creo_cli.contract_gen import ERROR_OBJECT_KEYS, SUCCESS_ENVELOPE_KEYS
from creo_cli.core import CODES, Error, validate_schema
from creo_cli.sketch import EXTRUDE_EXAMPLE, validate_extrude

ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None):
    environment = dict(os.environ, **(env or {}))
    environment.pop("CREO_CLI_TEST_TRACE", None)
    result = subprocess.run(
        [sys.executable, "-m", "creo_cli", *args],
        capture_output=True,
        cwd=ROOT,
        env=environment,
        timeout=60,
    )
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


class Registry(unittest.TestCase):
    def test_every_command_has_a_resource_path_schema_and_example(self):
        for c in registry.COMMANDS:
            with self.subTest(command=c.path):
                words = c.path.split()
                self.assertTrue(words)
                self.assertTrue(all(word.replace("-", "").isalpha() for word in words))
                self.assertFalse(
                    any(other.path.startswith(c.path + " ") for other in registry.COMMANDS)
                )
                described = c.describe()
                self.assertIn(c.schema_name, registry.SCHEMAS)
                self.assertTrue(registry.SCHEMAS[c.schema_name]["fields"], "a stub schema")
                self.assertTrue(described["examples"])
                if described["type"] == "write":
                    self.assertEqual(len(described["examples"]), 2)
                    self.assertIn("--dry-run", described["examples"][0])
                    self.assertIn("--confirm <confirm_token>", described["examples"][1])
                elif c.path == "operation resolve":
                    self.assertEqual(described["driver"]["effects"], ["observe"])
                    self.assertTrue(described["extensions"]["creo"]["write_gate"])

    def test_dangerous_is_truthful(self):
        # Irreversible or cascading writes, and nothing else, carry the second gate.
        dangerous = {c.path for c in registry.COMMANDS if c.dangerous}
        self.assertEqual(
            dangerous,
            {
                "model discard",
                "feature delete",
                "assembly component remove",
                "family-table remove-instance",
            },
        )
        for c in registry.COMMANDS:
            if c.dangerous:
                self.assertTrue(c.write)
                self.assertTrue(all("--dangerous" in e for e in c.describe()["examples"]))

    def test_paths_are_unique_and_groups_are_nouns(self):
        paths = [c.path for c in registry.COMMANDS]
        self.assertEqual(len(paths), len(set(paths)))
        groups = {p.split()[0] for p in paths if " " in p}
        self.assertEqual(
            groups,
            {
                "service",
                "appearance",
                "display",
                "session",
                "workspace",
                "model",
                "part",
                "feature",
                "geometry",
                "dimension",
                "parameter",
                "relation",
                "family-table",
                "artifact",
                "material",
                "assembly",
                "drawing",
                "workflow",
                "operation",
            },
        )

    def test_request_example_is_valid(self):
        validate_extrude(EXTRUDE_EXAMPLE)
        for f in sorted((ROOT / "examples").glob("extrude-*.json")):
            with self.subTest(example=f.name):
                validate_extrude(json.loads(f.read_text(encoding="utf-8")))

    def test_live_verified_marks_are_backed_by_recorded_calls(self):
        if not registry.LIVE_VERIFIED:
            self.skipTest("no command claims live verification")
        evidence = json.loads((ROOT / registry.LIVE_EVIDENCE).read_text(encoding="utf-8"))
        self.assertTrue(evidence["ok"] and evidence["real_creo_verified"])
        by_path = {c.path: c for c in registry.COMMANDS}
        succeeded = set()
        for call in evidence["calls"]:
            argv = call["argv"]
            path = " ".join(argv[:2]) if " ".join(argv[:2]) in by_path else argv[0]
            if call["exit_code"] != 0 or path not in by_path:
                continue
            # A write counts only when a confirmation succeeded, not just its preview.
            if by_path[path].write and "--confirm" not in argv:
                continue
            succeeded.add(path)
        for path in registry.LIVE_VERIFIED:
            with self.subTest(command=path):
                self.assertIn(path, by_path)
                self.assertTrue(by_path[path].service_ops, f"{path} never talks to Creo")
                self.assertIn(path, succeeded, f"{path} has no successful call in the evidence")

    def test_a_stable_claim_rests_on_every_command_run_live(self):
        from creo_cli.commands.meta import RELEASE

        if RELEASE["level"] != "stable":
            self.skipTest(f"release readiness is {RELEASE['level']}")
        self.assertEqual(RELEASE["fcc_status"], "verified")
        self.assertEqual(RELEASE["live_smoke_status"], "verified")
        talking = {c.path for c in registry.COMMANDS if c.service_ops}
        self.assertEqual(talking - set(registry.LIVE_VERIFIED), set())


class ErrorContract(unittest.TestCase):
    def test_codes_come_from_the_generated_contract(self):
        self.assertEqual(set(CODES), set(CONTRACT))
        for name, (exit_code, retryable) in CODES.items():
            self.assertEqual(
                (exit_code, retryable), (CONTRACT[name]["exit"], CONTRACT[name]["retryable"])
            )

    def test_undeclared_codes_cannot_be_raised(self):
        with self.assertRaises(ValueError):
            Error("E_MADE_UP", "no")

    def test_every_code_the_source_raises_is_declared(self):
        import re

        raised = set()
        for p in (ROOT / "creo_cli").rglob("*.py"):
            raised |= set(re.findall(r'Error\(\s*"(E_[A-Z_]+)"', p.read_text(encoding="utf-8")))
        self.assertTrue(raised)
        self.assertLessEqual(raised, set(CODES))
        # A declared code no source raises is marked so in reference, and only such a code.
        from creo_cli.commands.meta import NOT_RAISED

        self.assertEqual(set(CODES) - raised, set(NOT_RAISED))
        published = json.loads(run("reference", "--compact")[1])["data"]
        marked = set(published["extensions"]["creo"]["non_raised_error_codes"])
        self.assertEqual(marked, set(NOT_RAISED))
        for key in marked:
            self.assertEqual(published["error_codes"][key]["description"], NOT_RAISED[key])


class Envelope(unittest.TestCase):
    def test_real_process_success_and_failure(self):
        code, out, err = run("reference", "--compact")
        doc = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(doc), sorted(SUCCESS_ENVELOPE_KEYS))
        self.assertEqual(doc["data"]["version"], __version__)
        self.assertEqual(out.count("\n"), 1, "exactly one JSON document on stdout")
        self.assertNotIn('": ', out, "--compact leaves no whitespace")
        self.assertEqual(err, "", "stderr stays empty")
        code, out, err = run("model", "show", "--model", "9lives")
        doc = json.loads(out)
        self.assertEqual(
            (code, doc["ok"], sorted(doc["error"])), (2, False, sorted(ERROR_OBJECT_KEYS))
        )
        self.assertEqual(err, "", "a failure is the document on stdout, not text on stderr")
        # --quiet has no progress to suppress and never hides the error; --json is the
        # deprecated alias of the default.
        for flag in ("--quiet", "--json"):
            code, out, err = run("model", "show", "--model", "9lives", flag)
            self.assertEqual((code, json.loads(out)["error"]["code"], err), (2, "E_VALIDATION", ""))

    def test_text_and_raw_unwrap(self):
        code, out, _ = run("changelog", "--format", "text")
        self.assertEqual(code, 0)
        self.assertIn("current_version", json.loads(out))
        self.assertGreater(out.count("\n"), 1, "text is indented for people")
        code, out, _ = run("changelog", "--format", "raw")
        self.assertIn("entries", json.loads(out))
        for fmt in ("text", "raw"):
            code, out, _ = run("model", "show", "--model", "9lives", "--format", fmt)
            self.assertEqual((code, json.loads(out)["code"]), (2, "E_VALIDATION"))

    def test_help_is_human_text(self):
        code, out, _ = run("--help")
        self.assertEqual(code, 0)
        self.assertIn("creo-cli", out)
        # Every noun lists its verbs; every global flag says what it does.
        self.assertIn("assembly", out)
        code, group, _ = run("assembly", "component", "--help")
        self.assertEqual(code, 0)
        for action in ("add", "remove", "replace", "list", "show"):
            self.assertIn(action, group)
        for g in registry.GLOBALS:
            with self.subTest(flag=g["name"]):
                self.assertTrue(g["description"])
        code, out, _ = run("feature", "extrude", "--help")
        self.assertEqual(code, 0)
        self.assertIn("--request", out)

    def test_reference_matches_its_published_schema(self):
        code, out, _ = run("reference")
        data = json.loads(out)["data"]
        validate_schema(data, registry.SCHEMAS["reference"]["json_schema"])
        self.assertEqual(
            data["release_readiness"]["level"] in ("stable", "beta", "unpublishable"), True
        )
        for c in data["commands"]:
            self.assertIn(c["output_schema"], data["schemas"])

    def test_schema_validator_catches_wrong_shapes(self):
        with self.assertRaises(Error):
            validate_schema({"a": 1}, {"type": "object", "required": ["b"]})
        with self.assertRaises(Error):
            validate_schema(
                {"a": "x"}, {"type": "object", "properties": {"a": {"type": "integer"}}}
            )


if __name__ == "__main__":
    unittest.main()
