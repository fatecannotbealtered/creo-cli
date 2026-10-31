"""The rest of the public contract: every doctor check's failing branch with its fix, context and
its defaults, changelog, the envelope's fields, paging, receipts' order, token lifetime,
features named by id, every published request example, and service install's own gates."""

from __future__ import annotations

import json
import time
from datetime import datetime
from unittest.mock import patch

from creo_cli import assembly_constraints, registry, safety
from creo_cli.commands import workflow
from creo_cli.commands.assembly import validate_add, validate_explode
from creo_cli.commands.detailing import validate_table, validate_title
from creo_cli.commands.family import validate_family
from creo_cli.commands.layout import SCHEMA as LAYOUT_SCHEMA
from creo_cli.commands.relation import validate_relations
from creo_cli.requests import (
    CHAMFER_SCHEMA,
    ROUND_SCHEMA,
    validate_datum_axis,
    validate_datum_plane,
    validate_draft,
    validate_edges,
    validate_hole,
    validate_pattern,
    validate_shell,
    validate_thread,
)
from creo_cli.sketch import validate_extrude, validate_revolve, validate_rib, validate_sweep
from creo_cli.validation import validate
from tests.test_commands import RECT, Base


def validate_workflow(example: dict) -> None:
    """The workflow's own schema, then every step checked as its command checks it."""
    validate(example, workflow.SCHEMA)
    for _, _, opts, prepare, _ in workflow._steps(example):
        prepare(opts)


class DoctorBranches(Base):
    def checks(self, env=None):
        return {c["check"]: c for c in self.cli("doctor", env=env)["data"]["checks"]}

    def test_a_missing_toolkit_names_the_installer_component(self):
        missing = {"present": False, "detail": "otk.jar is absent", "creo_load_point": None}
        with (
            patch("creo_cli.install.toolkit", return_value=missing),
            patch("creo_cli.install.streamed_delivery", return_value=False),
        ):
            check = self.checks()["creo_api_toolkit"]
        self.assertEqual(check["status"], "fail")
        self.assertIn("API Toolkits", check["fix"])
        with (
            patch("creo_cli.install.toolkit", return_value=missing),
            patch("creo_cli.install.streamed_delivery", return_value=True),
        ):
            check = self.checks()["creo_api_toolkit"]
        self.assertEqual(check["status"], "fail")
        self.assertIn("application-streaming", check["fix"])

    def test_java_that_creo_cannot_find(self):
        absent = {"resolved": False, "detail": "PRO_JAVA_COMMAND is not set"}
        with patch("creo_cli.install.java_runtime", return_value=absent):
            check = self.checks()["creo_java_runtime"]
        self.assertEqual(check["status"], "warn")
        self.assertIn("PRO_JAVA_COMMAND", check["fix"])

    def test_what_the_live_session_lacks(self):
        self.world.creation_api = False
        self.world.native = False
        outside = self.root / "elsewhere"
        outside.mkdir()
        self.world.cwd = outside
        checks = self.checks()
        self.assertEqual(checks["creation_api"]["status"], "fail")
        self.assertIn("ObjectToolkitJava", checks["creation_api"]["fix"])
        self.assertEqual(checks["native_sketch_library"]["status"], "warn")
        self.assertIn("creo_cli_sketch.dll", checks["native_sketch_library"]["fix"])
        self.assertEqual(checks["working_directory"]["status"], "warn")
        self.assertIn("session cd", checks["working_directory"]["fix"])

    def test_another_protocol_answering(self):
        self.world.protocol = 1
        check = self.checks()["service"]
        self.assertEqual(check["status"], "fail")
        self.assertIn("install the service", check["fix"])

    def test_no_workspace(self):
        away = {k: v for k, v in self.env.items() if k != "CREO_CLI_WORKSPACE"}
        checks = self.checks(away)
        self.assertEqual(checks["workspace"]["status"], "warn")
        self.assertIn("CREO_CLI_WORKSPACE", checks["workspace"]["fix"])
        self.assertEqual(checks["working_directory"]["status"], "warn")

    def test_no_service_and_no_bundle(self):
        self.server.close()
        check = self.checks()["service_installed"]
        self.assertEqual(check["status"], "warn")
        self.assertIn("service install", check["fix"])


class ContextAndDefaults(Base):
    def test_without_a_workspace_or_any_setting(self):
        home = self.root / "home"
        home.mkdir()
        bare = {
            k: v
            for k, v in self.env.items()
            if not k.startswith("CREO_CLI_") or k == "CREO_CLI_SERVICE_TOKEN_FILE"
        }
        bare = {k: v for k, v in bare.items() if k != "CREO_CLI_SERVICE_TOKEN_FILE"}
        bare |= {"HOME": str(home), "USERPROFILE": str(home)}
        data = self.cli("context", env=bare)["data"]
        self.assertEqual(
            (data["config"]["workspace"], data["config"]["workspace_usable"]), (None, False)
        )
        self.assertEqual(data["config"]["permission"], "read")
        self.assertFalse(data["config"]["native_writes_opt_in"])
        self.assertEqual(data["config"]["state_directory"], str(home / ".creo-cli"))
        self.assertEqual(data["service"]["endpoint"], "http://127.0.0.1:9057")
        self.assertFalse(data["service"]["token_file_present"])
        (home / ".creo-cli").mkdir()
        (home / ".creo-cli" / "service-token").write_text("0" * 64, encoding="ascii")
        self.assertTrue(self.cli("context", env=bare)["data"]["service"]["token_file_present"])

    def test_localhost_is_the_loopback_address(self):
        env = dict(self.env, CREO_CLI_SERVICE_URL="http://localhost:9100/")
        self.assertEqual(
            self.cli("context", env=env)["data"]["service"]["endpoint"], "http://127.0.0.1:9100"
        )

    def test_changelog_since_a_version(self):
        entries = self.cli("changelog", "--since", "0.1.0")["data"]["entries"]
        versions = [e["version"] for e in entries]
        self.assertIn("1.0.0", versions)
        self.assertNotIn("0.1.0", versions)
        self.assertTrue(all(set(e["changes"]) >= {"added", "changed", "removed"} for e in entries))


class Envelope(Base):
    def test_every_reply_says_how_long_it_took(self):
        ok = self.cli("reference", "--command", "model show")
        failed = self.cli("model", "show", "--model", "9lives", status=2)
        for doc in (ok, failed):
            self.assertIsInstance(doc["meta"]["duration_ms"], int)
            self.assertGreaterEqual(doc["meta"]["duration_ms"], 0)

    def test_lists_page_and_fields_pick_item_fields(self):
        self.part("a.prt")
        self.part("b.prt")
        first = self.cli("model", "list", "--limit", 1)["data"]
        self.assertEqual((first["count"], first["total"], first["has_more"]), (1, 2, True))
        self.assertEqual(first["next_offset"], 1)
        second = self.cli("model", "list", "--limit", 1, "--offset", 1)["data"]
        self.assertEqual((second["offset"], second["has_more"]), (1, False))
        self.assertNotEqual(first["items"], second["items"])
        picked = self.cli("model", "list", "--fields", "model")["data"]
        self.assertEqual([set(i) for i in picked["items"]], [{"model"}, {"model"}])
        self.assertEqual(picked["total"], 2)


class ReceiptsAndTokens(Base):
    def test_receipts_come_newest_first(self):
        self.part()
        (self.ws / "one").mkdir()
        (self.ws / "two").mkdir()
        self.gated("session", "cd", "--path", "one")
        self.gated("session", "cd", "--path", "two")
        runs = self.receipts()
        self.assertEqual(len(runs), 2)
        self.assertGreaterEqual(runs[0]["at"], runs[1]["at"])
        older = self.cli("operation", "list", "--offset", 1)["data"]["items"]
        self.assertEqual([r["operation_id"] for r in older], [runs[1]["operation_id"]])

    def test_a_token_lives_fifteen_minutes(self):
        self.assertEqual(safety.TTL, 900)
        self.part()
        dry = self.cli("model", "save", "--model", "block", "--dry-run")["data"]
        expires = datetime.fromisoformat(dry["expires_at"].replace("Z", "+00:00")).timestamp()
        self.assertAlmostEqual(expires - time.time(), 900, delta=10)

    def test_a_feature_is_named_or_numbered(self):
        self.part()
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        rows = self.cli("feature", "list", "--model", "block")["data"]["items"]
        block = next(r for r in rows if r["name"] == "BLOCK")
        shown = self.cli("feature", "show", "--model", "block", "--feature", block["id"])["data"]
        self.assertEqual(shown["name"], "BLOCK")
        renamed = self.gated(
            "feature", "rename", "--model", "block", "--feature", block["id"], "--name", "BASE"
        )["data"]
        self.assertEqual(renamed["result"]["feature"]["name"], "BASE")


class PublishedExamples(Base):
    VALIDATORS = {
        "feature extrude": validate_extrude,
        "feature revolve": validate_revolve,
        "feature datum-plane": validate_datum_plane,
        "feature datum-axis": validate_datum_axis,
        "feature round": lambda r: validate_edges(r, ROUND_SCHEMA),
        "feature chamfer": lambda r: validate_edges(r, CHAMFER_SCHEMA),
        "feature hole": validate_hole,
        "feature shell": validate_shell,
        "feature draft": validate_draft,
        "feature cosmetic-thread": validate_thread,
        "feature rib": validate_rib,
        "feature sweep": validate_sweep,
        "family-table apply": validate_family,
        "assembly explode apply": validate_explode,
        "feature pattern": validate_pattern,
        "assembly component add": validate_add,
        "assembly component redefine": assembly_constraints.validate_request,
        "drawing table add": validate_table,
        "drawing title-block apply": validate_title,
        "relation set": validate_relations,
        "workflow run": validate_workflow,
        "workflow plan": validate_workflow,
        "drawing layout plan": lambda r: validate(r, LAYOUT_SCHEMA),
        "drawing layout apply": lambda r: validate(r, LAYOUT_SCHEMA),
    }

    def test_every_request_example_passes_its_own_checks(self):
        patch.dict("os.environ", self.env, clear=True).start()
        self.addCleanup(patch.stopall)
        published = {
            c["path"]: c for c in self.cli("reference")["data"]["commands"] if "request_schema" in c
        }
        self.assertEqual(set(published), set(self.VALIDATORS))
        for path, command in published.items():
            with self.subTest(command=path):
                example = command["request_example"]
                self.VALIDATORS[path](json.loads(json.dumps(example)))
                self.assertEqual(registry.BY_PATH[path].request_example, example)
