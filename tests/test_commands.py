"""Command-level tests for every command, against a loopback substitute of the service.

Nothing here runs Creo. What is tested is the CLI's side of the contract: arguments,
previews bound to observed state, the write policy and the dangerous gate, receipts, and
what each kind of failure is called.
"""

from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from creo_cli.core import CODES
from creo_cli.main import main
from tests.fixture import INCH, MM, Server, World


def domain_preview(value):
    """Domain details moved under the pinned plan's Creo extension on migrated paths."""
    return value.get("extensions", {}).get("creo", value)


def domain_receipt(value):
    """Inspect retained domain evidence, while driver tests check the public facets."""
    if "outcome" not in value:
        return value
    domain = value["extensions"]["creo"]
    return {
        "operation_id": value["operation_id"],
        "status": domain["legacy_status"],
        "result": domain["domain_result"],
        "verification": value["outcome"]["verification"]["extensions"]["creo"],
        "persisted": {
            "saved": True,
            "unsaved": False,
            "unchanged": False,
            "not_applicable": False,
        }.get(value["outcome"]["persistence"]),
    }


ROOT = Path(__file__).resolve().parents[1]
RECT = {
    "units": "mm",
    "name": "BLOCK",
    "depth": 10,
    "sketch": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "profile": {"type": "rectangle", "width": 40, "height": 20},
    },
}
HOLE = {
    "units": "mm",
    "name": "HOLE",
    "depth": 10,
    "material": "remove",
    "sketch": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "profile": {"type": "circle", "diameter": 6, "center": [-12, 0]},
    },
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.ws = self.root / "ws"
        self.ws.mkdir()
        self.world = World(self.ws)
        # Synthetic table bytes never pretend to be a redistributable PTC template.
        import hashlib

        from creo_cli import bom

        fixture_table = self.ws / "fixture-bom.tbl"
        fixture_table.write_bytes(b"creo-cli loopback repeat-region fixture")
        self.world.bom_template = fixture_table
        profile = patch.dict(
            bom.TEMPLATES,
            {
                hashlib.sha256(fixture_table.read_bytes()).hexdigest(): next(
                    iter(bom.TEMPLATES.values())
                )
            },
        )
        profile.start()
        self.addCleanup(profile.stop)
        self.server = Server(self.world)
        self.addCleanup(self.server.close)
        token = self.root / "service-token"
        token.write_text(self.world.token, encoding="ascii")
        scope = self.root / "scope.json"
        scope.write_text(
            json.dumps(
                {
                    "scope_id": "fixture-task",
                    "tool": "creo-cli",
                    "granted_by": "test-fixture",
                    "granted_at": "2026-10-07T00:00:00Z",
                    "expires_at": None,
                    "effects": ["observe", "session", "change", "persist", "artifact"],
                    "dangerous": True,
                    "roots": [str(self.ws)],
                    "outputs": [str(self.ws)],
                }
            ),
            encoding="utf-8",
        )
        self.env = dict(
            os.environ,
            CREO_CLI_CONFIG_DIR=str(self.root / "state"),
            CREO_CLI_WORKSPACE=str(self.ws),
            CREO_CLI_PERMISSION="write",
            CREO_CLI_EXPERIMENTAL_NATIVE_WRITES="1",
            CREO_CLI_SERVICE_URL=self.server.url,
            CREO_CLI_SERVICE_TOKEN_FILE=str(token),
            CREO_CLI_SCOPE_FILE=str(scope),
        )
        self.env.pop("CREO_CLI_TEST_TRACE", None)

    def cli(self, *args, status=0, env=None, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        fake_in = io.TextIOWrapper(io.BytesIO((stdin or "").encode("utf-8")), encoding="utf-8")
        with (
            patch.dict(os.environ, env or self.env, clear=True),
            redirect_stdout(out),
            redirect_stderr(err),
            patch("sys.stdin", fake_in),
        ):
            code = main([str(a) for a in args])
        result = json.loads(out.getvalue())
        self.assertEqual(code, status, result)
        self.assertEqual(
            set(result), {"ok", "schema_version", "meta", "data" if result["ok"] else "error"}
        )
        if not result["ok"]:
            self.assertEqual(set(result["error"]), {"code", "message", "details", "retryable"})
            self.assertEqual((code, result["error"]["retryable"]), CODES[result["error"]["code"]])
        self.assertNotIn(self.world.token, out.getvalue() + err.getvalue())
        return result

    def gated(self, *args, dangerous=False, status=0, env=None, stdin=None):
        extra = ("--dangerous",) if dangerous else ()
        dry = self.cli(*args, *extra, "--dry-run", env=env, stdin=stdin)
        return self.cli(
            *args,
            *extra,
            "--confirm",
            dry["data"]["confirm_token"],
            status=status,
            env=env,
            stdin=stdin,
        )

    def request(self, body, name="request.json"):
        p = self.root / name
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def part(self, name="block.prt", units=MM):
        m = self.world.part(name, units)
        self.world.write_version(self.ws, name, m)
        return m

    def receipts(self):
        return self.cli("operation", "list")["data"]["items"]

    def checks_pass(self, data):
        self.assertTrue(
            all(c["passed"] for c in data["verification"]["checks"]), data["verification"]
        )


class Meta(Base):
    def test_reference_lists_every_command_and_scopes(self):
        from creo_cli import registry

        data = self.cli("reference")["data"]
        self.assertEqual([c["path"] for c in data["commands"]], [c.path for c in registry.COMMANDS])
        one = self.cli("reference", "--command", "feature extrude")["data"]
        self.assertEqual([one["command"]["path"]], ["feature extrude"])
        self.assertEqual(
            set(one["schemas"]),
            {"feature_extrude"},
        )
        self.assertIn("request_schema", one["command"])
        self.assertEqual(
            self.cli("reference", "--command", "part explode", status=3)["error"]["code"],
            "E_NOT_FOUND",
        )
        # A noun gives its commands; --fields cuts the whole contract down to an index.
        drawing = self.cli("reference", "--command", "drawing")["data"]["commands"]
        self.assertEqual(
            [c["path"] for c in drawing],
            [c.path for c in registry.COMMANDS if c.path.startswith("drawing ")],
        )
        index = self.cli("reference", "--fields", "version,commands.path,commands.description")
        self.assertEqual(set(index["data"]["commands"][0]), {"path", "description"})

    def test_context_contacts_nothing(self):
        env = dict(self.env, CREO_CLI_SERVICE_URL=f"http://127.0.0.1:{free_port()}")
        data = self.cli("context", env=env)["data"]
        self.assertEqual(data["config"]["permission"], "write")
        self.assertTrue(data["config"]["workspace_usable"])
        self.assertEqual(data["service"]["protocol"], 2)
        self.assertEqual(self.world.events, [])

    def test_doctor_reports_each_check_with_a_fix(self):
        checks = {c["check"]: c for c in self.cli("doctor")["data"]["checks"]}
        for name in (
            "creo_api_toolkit",
            "creo_java_runtime",
            "service",
            "creation_api",
            "native_sketch_library",
            "working_directory",
            "workspace",
            "write_policy",
            "release_readiness",
        ):
            self.assertIn(name, checks)
        self.assertEqual(checks["service"]["status"], "pass")
        level = self.cli("reference")["data"]["release_readiness"]["level"]
        self.assertEqual(checks["release_readiness"]["details"]["level"], level)
        self.assertEqual(
            checks["release_readiness"]["status"],
            {"stable": "pass", "beta": "warn"}.get(level, "fail"),
        )
        down = dict(
            self.env,
            CREO_CLI_SERVICE_URL=f"http://127.0.0.1:{free_port()}",
            CREO_CLI_PERMISSION="read",
        )
        checks = {c["check"]: c for c in self.cli("doctor", env=down)["data"]["checks"]}
        self.assertEqual(checks["service"]["status"], "fail")
        self.assertTrue(checks["service"]["fix"])
        self.assertEqual(checks["write_policy"]["status"], "warn")
        self.assertNotIn("creation_api", checks)

    def test_doctor_compares_the_installed_skill_with_this_binary(self):
        home = self.root / "home"
        env = dict(self.env, HOME=str(home), USERPROFILE=str(home))

        def skill_check():
            checks = {c["check"]: c for c in self.cli("doctor", env=env)["data"]["checks"]}
            return checks["skill_version"]

        self.assertEqual(skill_check()["status"], "pass")
        for where, needed in ((".agents", "1.0.0"), (".claude", "9.1.0")):
            skill = home / where / "skills" / "creo-cli" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                f'---\nmetadata: {{"requires": {{"min_version": "{needed}"}}}}\n---\n',
                encoding="utf-8",
            )
        check = skill_check()
        self.assertEqual(check["status"], "fail")
        self.assertIn("9.1.0", check["message"])
        self.assertIn("private candidate package", check["fix"])
        self.assertIn("9.1.0", check["fix"])
        self.assertNotIn("npm install", check["fix"])
        (home / ".claude" / "skills" / "creo-cli" / "SKILL.md").unlink()
        check = skill_check()
        self.assertEqual(check["status"], "pass")
        self.assertIn(str(home / ".agents"), check["message"])

    def test_changelog(self):
        data = self.cli("changelog")["data"]
        self.assertTrue(data["entries"])
        newest = data["entries"][0]
        self.assertEqual(newest["version"], data["current_version"])
        self.assertTrue(newest["summary"])
        source = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        # Wrapped bullets come back whole: every entry ends where its source bullet ends.
        for entry in newest["changes"]["added"]:
            self.assertIn(entry.split()[-1], source)
            self.assertNotRegex(entry, r"\s{2,}")
        self.assertEqual(self.cli("changelog", "--since", "9.0.0")["data"]["entries"], [])
        self.assertEqual(
            self.cli("changelog", "--since", data["current_version"])["data"]["entries"], []
        )
        self.assertEqual(
            self.cli("changelog", "--since", "one", status=2)["error"]["code"], "E_VALIDATION"
        )


class Session(Base):
    def test_status_ready(self):
        data = self.cli("session", "status")["data"]
        self.assertTrue(
            data["connected"] and data["creation_api"] and data["native_sketch_available"]
        )
        self.assertTrue(data["working_directory_in_workspace"])
        self.assertEqual(data["problems"], [])

    def test_status_is_an_answer_when_creo_is_down(self):
        env = dict(self.env, CREO_CLI_SERVICE_URL=f"http://127.0.0.1:{free_port()}")
        data = self.cli("session", "status", env=env)["data"]
        self.assertFalse(data["connected"])
        self.assertEqual([p["code"] for p in data["problems"]], ["service_unavailable"])

    def test_status_names_what_stands_in_the_way(self):
        self.world.native = False
        self.world.creation_api = False
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.world.cwd = elsewhere
        codes = [p["code"] for p in self.cli("session", "status")["data"]["problems"]]
        self.assertEqual(
            codes,
            [
                "no_creation_api",
                "native_sketch_library_not_loaded",
                "working_directory_outside_workspace",
            ],
        )
        env = {k: v for k, v in self.env.items() if k != "CREO_CLI_WORKSPACE"}
        self.assertIn(
            "workspace_not_configured",
            [p["code"] for p in self.cli("session", "status", env=env)["data"]["problems"]],
        )

    def test_protocol_mismatch(self):
        self.world.protocol = 1
        self.assertFalse(self.cli("session", "status")["data"]["connected"])
        error = self.cli("model", "list", status=4)["error"]
        self.assertEqual(
            (error["code"], error["details"]["service_protocol"]), ("E_BACKEND_UNAVAILABLE", 1)
        )

    def test_cd(self):
        (self.ws / "parts").mkdir()
        data = self.gated("session", "cd", "--path", "parts")["data"]
        self.checks_pass(data)
        self.assertEqual(Path(self.world.cwd), self.ws / "parts")
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.assertEqual(
            self.cli("session", "cd", "--path", str(elsewhere), "--dry-run", status=4)["error"][
                "code"
            ],
            "E_FORBIDDEN",
        )
        self.assertEqual(
            self.cli("session", "cd", "--path", "..", "--dry-run", status=4)["error"]["code"],
            "E_FORBIDDEN",
        )
        env = {k: v for k, v in self.env.items() if k != "CREO_CLI_WORKSPACE"}
        self.assertEqual(
            self.cli("session", "cd", "--path", "parts", "--dry-run", status=4, env=env)["error"][
                "code"
            ],
            "E_CONFIG",
        )


class Workspace(Base):
    def test_list_needs_no_creo(self):
        (self.ws / "sub").mkdir()
        for name in (
            "block.prt.1",
            "block.prt.2",
            "sub/gear.asm.4",
            "sub/block.drw.1",
            "notes.txt",
        ):
            (self.ws / name).write_bytes(b"x")
        env = dict(self.env, CREO_CLI_SERVICE_URL=f"http://127.0.0.1:{free_port()}")
        data = self.cli("workspace", "list", env=env)["data"]
        rows = {(r["directory"], r["model"]): r for r in data["items"]}
        self.assertEqual(rows[(".", "block.prt")]["versions"], [1, 2])
        self.assertEqual(rows[(".", "block.prt")]["newest"], "block.prt.2")
        self.assertEqual(rows[("sub", "gear.asm")]["kind"], "assembly")
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(
            [
                r["model"]
                for r in self.cli("workspace", "list", "--kind", "drawing")["data"]["items"]
            ],
            ["block.drw"],
        )
        self.assertEqual(len(self.cli("workspace", "list", "--name", "gear")["data"]["items"]), 1)
        paged = self.cli("workspace", "list", "--limit", "2")["data"]
        self.assertTrue(paged["has_more"])
        self.assertEqual(paged["next_offset"], 2)
        self.assertEqual(self.world.events, [])


class Model(Base):
    def test_list_and_show(self):
        self.part()
        rows = self.cli("model", "list")["data"]["items"]
        self.assertEqual(rows[0]["model"], "block.prt")
        shown = self.cli("model", "show", "--model", "block")["data"]
        self.assertEqual(
            (shown["model"], shown["type"], shown["units"]["length"]), ("block.prt", "part", "mm")
        )
        self.assertIn("datum_planes", shown["_untrusted"])
        self.assertEqual(
            self.cli("model", "show", "--model", "nope", status=3)["error"]["code"], "E_NOT_FOUND"
        )
        self.assertEqual(
            self.cli("model", "show", "--model", "9lives", status=2)["error"]["code"],
            "E_VALIDATION",
        )

    def test_open(self):
        sub = self.ws / "sub"
        sub.mkdir()
        (sub / "fixture.prt.1").write_bytes(b"v1")
        (sub / "fixture.prt.2").write_bytes(b"v2")
        older = self.cli("model", "open", "--path", "sub/fixture.prt.1", "--dry-run", status=2)[
            "error"
        ]
        self.assertEqual(Path(older["details"]["newest"]).name, "fixture.prt.2")
        opened = self.gated("model", "open", "--path", "sub/fixture.prt.2")["data"]
        self.checks_pass(opened)
        self.assertEqual(
            self.cli("model", "open", "--path", "sub/fixture.prt.2", "--dry-run", status=6)[
                "error"
            ]["code"],
            "E_CONFLICT",
        )
        (self.ws / "notes.txt").write_bytes(b"x")
        self.assertEqual(
            self.cli("model", "open", "--path", "notes.txt", "--dry-run", status=2)["error"][
                "code"
            ],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli("model", "open", "--path", "missing.prt", "--dry-run", status=3)["error"][
                "code"
            ],
            "E_NOT_FOUND",
        )

    def test_save_writes_where_the_model_came_from(self):
        sub = self.ws / "sub"
        sub.mkdir()
        (sub / "fixture.prt.1").write_bytes(b"v1")
        self.gated("model", "open", "--path", "sub/fixture.prt.1")
        preview = domain_preview(
            self.cli("model", "save", "--model", "fixture", "--dry-run")["data"]["preview"]
        )
        self.assertEqual(preview["next_version"], "fixture.prt.2")
        saved = self.gated("model", "save", "--model", "fixture")["data"]
        self.checks_pass(saved)
        self.assertTrue(saved["persisted"])
        self.assertEqual(Path(saved["result"]["artifact"]["path"]), sub / "fixture.prt.2")

    def test_writes_refuse_models_from_outside_the_workspace(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.world.part("outsider.prt", MM, origin=str(elsewhere / "outsider.prt.4"), modified=True)
        for args in (
            ("model", "save", "--model", "outsider"),
            ("model", "close", "--model", "outsider"),
            ("model", "discard", "--model", "outsider", "--dangerous"),
            ("feature", "delete", "--model", "outsider", "--feature", "TOP", "--dangerous"),
        ):
            with self.subTest(command=args[:2]):
                error = self.cli(*args, "--dry-run", status=4)["error"]
                self.assertEqual(error["code"], "E_FORBIDDEN")
        self.assertIn("outsider.prt", self.world.models)

    def test_close_refuses_unsaved_work_and_discard_needs_the_dangerous_flag(self):
        self.part()
        self.gated("model", "save", "--model", "block")  # explicit verified discard baseline
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        refused = self.cli("model", "close", "--model", "block", "--dry-run", status=6)["error"]
        self.assertIn("model save", refused["details"]["fix"])
        self.assertEqual(
            self.cli("model", "discard", "--model", "block", "--dry-run", status=5)["error"][
                "code"
            ],
            "E_CONFIRMATION_REQUIRED",
        )
        preview = domain_preview(
            self.cli("model", "discard", "--model", "block", "--dangerous", "--dry-run")["data"][
                "preview"
            ]
        )
        self.assertTrue(preview["unsaved_changes"])
        data = self.gated("model", "discard", "--model", "block", dangerous=True)["data"]
        self.assertTrue(data["result"]["discarded_changes"])
        self.assertNotIn("block.prt", self.world.models)

    def test_close_after_save(self):
        self.part()
        data = self.gated("model", "close", "--model", "block")["data"]
        self.checks_pass(data)
        self.assertEqual(
            self.cli("model", "close", "--model", "block", "--dry-run", status=3)["error"]["code"],
            "E_NOT_FOUND",
        )


class Part(Base):
    def test_create(self):
        data = self.gated("part", "create", "--name", "block", "--units", "mmns")["data"]
        self.checks_pass(data)
        self.assertTrue((self.ws / "block.prt.1").is_file())
        inch = self.gated("part", "create", "--name", "plate", "--units", "inlbs")["data"]
        self.assertEqual(inch["result"]["units"]["length"], "in")
        self.checks_pass(inch)

    def test_create_from_a_workspace_template(self):
        (self.ws / "company.prt.2").write_bytes(b"template")
        data = self.gated("part", "create", "--name", "bracket", "--template", "company.prt.2")[
            "data"
        ]
        self.assertTrue(data["result"]["template"].endswith("company.prt.2"))

    def test_create_refusals(self):
        self.assertEqual(
            self.cli("part", "create", "--name", "x", "--dry-run", status=2)["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(
                "part",
                "create",
                "--name",
                "x",
                "--units",
                "mmns",
                "--template",
                "t.prt",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli("part", "create", "--name", "x.asm", "--units", "mmns", "--dry-run", status=2)[
                "error"
            ]["code"],
            "E_VALIDATION",
        )
        (self.ws / "block.prt.3").write_bytes(b"old")
        self.assertEqual(
            self.cli("part", "create", "--name", "block", "--units", "mmns", "--dry-run", status=6)[
                "error"
            ]["code"],
            "E_CONFLICT",
        )
        self.world.part("other.prt")
        self.assertEqual(
            self.cli("part", "create", "--name", "OTHER", "--units", "mmns", "--dry-run", status=6)[
                "error"
            ]["code"],
            "E_CONFLICT",
        )
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        self.world.cwd = elsewhere
        error = self.cli(
            "part", "create", "--name", "fresh", "--units", "mmns", "--dry-run", status=4
        )["error"]
        self.assertEqual(error["code"], "E_FORBIDDEN")
        self.assertIn("session cd", error["details"]["fix"])


class Feature(Base):
    def test_build_read_and_delete(self):
        self.part()
        block = self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT)
        )["data"]
        self.checks_pass(block)
        self.assertEqual(block["result"]["volume"]["change"], 8000)
        # Each sketch dimension by name, with what it measures, as a drafter gives it.
        self.assertEqual(
            [(d["value"], d["measures"], d["by"]) for d in block["result"]["sketch_dimensions"]],
            [
                (40, "width of the rectangle centred at (0, 0)", "cli"),
                (20, "height of the rectangle centred at (0, 0)", "cli"),
            ],
        )
        self.assertEqual(block["result"]["dimension_plan"], "kept")
        listed = self.cli("dimension", "list", "--model", "block", "--feature", "BLOCK")["data"]
        self.assertEqual(
            [d.get("measures") for d in listed["items"] if d["in_sketch"]],
            [
                "width of the rectangle centred at (0, 0)",
                "height of the rectangle centred at (0, 0)",
            ],
        )
        self.assertEqual(listed["held_together"], [])
        self.assertIsInstance(block["result"]["feature"]["id"], str)
        self.assertFalse(block["persisted"])
        hole = self.gated(
            "feature", "extrude", "--model", "block", "--request", "-", stdin=json.dumps(HOLE)
        )["data"]
        self.checks_pass(hole)
        volume = hole["result"]["volume"]
        self.assertLess(volume["change"], 0)
        self.assertAlmostEqual(volume["change"], volume["expected_change"])
        self.assertEqual(
            set(hole["result"]),
            {"model", "units", "feature", "volume", "sketch_dimensions", "held_together"}
            | {"dimension_plan"},
        )
        self.assertEqual(
            hole["result"]["sketch_dimensions"][0]["measures"], "diameter of the circle at (-12, 0)"
        )
        listed = self.cli("feature", "list", "--model", "block")["data"]
        self.assertEqual([f["name"] for f in listed["items"]][-2:], ["BLOCK", "HOLE"])
        internal = self.cli("feature", "list", "--model", "block", "--include-internal")["data"]
        self.assertGreater(internal["total"], listed["total"])
        shown = self.cli("feature", "show", "--model", "block", "--feature", "hole")["data"]
        self.assertEqual(shown["type"], "FEATTYPE_CUT")
        self.assertEqual([p["name"] for p in shown["parents"]], ["RIGHT", "TOP", "FRONT"])
        self.assertEqual(
            self.cli("feature", "show", "--model", "block", "--feature", "a b", status=2)["error"][
                "code"
            ],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(
                "feature", "delete", "--model", "block", "--feature", "HOLE", "--dry-run", status=5
            )["error"]["code"],
            "E_CONFIRMATION_REQUIRED",
        )
        deleted = self.gated(
            "feature", "delete", "--model", "block", "--feature", "HOLE", dangerous=True
        )["data"]
        self.checks_pass(deleted)
        self.assertNotIn(
            "HOLE",
            [f["name"] for f in self.cli("feature", "list", "--model", "block")["data"]["items"]],
        )

    def test_delete_lists_and_removes_children(self):
        m = self.part()
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(HOLE))
        block = next(f for f in m["features"] if f["name"] == "BLOCK")
        hole = next(f for f in m["features"] if f["name"] == "HOLE")
        block["children"] = [hole["id"]]
        preview = domain_preview(
            self.cli(
                "feature",
                "delete",
                "--model",
                "block",
                "--feature",
                "BLOCK",
                "--dangerous",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual([c["name"] for c in preview["children_deleted_with_it"]], ["HOLE"])
        data = self.gated(
            "feature", "delete", "--model", "block", "--feature", "BLOCK", dangerous=True
        )["data"]
        self.checks_pass(data)
        self.assertEqual({f["name"] for f in data["result"]["deleted"]} >= {"BLOCK", "HOLE"}, True)

    def test_every_profile(self):
        self.part("hex.prt")
        hexagon = json.loads(
            (ROOT / "examples" / "extrude-hexagon.json").read_text(encoding="utf-8")
        )
        data = self.gated(
            "feature", "extrude", "--model", "hex", "--request", self.request(hexagon)
        )["data"]
        self.assertAlmostEqual(
            data["result"]["volume"]["change"], 3 * 3**0.5 / 2 * 15**2 * 8, places=6
        )
        ellipse = {
            "units": "mm",
            "depth": 2,
            "sketch": {
                "plane": "TOP",
                "orient_ref": "RIGHT",
                "profile": {"type": "ellipse", "x_radius": 3, "y_radius": 2},
            },
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "hex",
                "--request",
                self.request(ellipse),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["sketch"]["drawn_by"], "java")
        self.assertIsNone(preview["sketch"]["references"])

    def test_preview_reads_only_and_says_what_will_happen(self):
        self.part()
        data = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        p = domain_preview(data["preview"])
        self.assertEqual(
            (p["units"]["length"], p["expected_volume_change"], p["sketch"]["drawn_by"]),
            ("mm", 8000, "native"),
        )
        self.assertEqual(p["sketch"]["references"], ["RIGHT", "TOP"])
        self.assertTrue(p["policy"]["confirm_allowed"])
        self.assertTrue(data["confirm_token"].startswith("ct_"))
        self.assertNotIn("feature.extrude", self.world.ops())
        self.assertEqual([r["status"] for r in self.receipts()], ["planned"])

    def test_read_policy_previews_but_cannot_confirm(self):
        self.part()
        read_only = dict(self.env, CREO_CLI_PERMISSION="read")
        dry = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--dry-run",
            env=read_only,
        )["data"]
        self.assertFalse(domain_preview(dry["preview"])["policy"]["confirm_allowed"])
        refused = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["confirm_token"],
            status=4,
            env=read_only,
        )["error"]
        self.assertEqual(refused["code"], "E_FORBIDDEN")
        stale = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["confirm_token"],
            status=6,
        )["error"]
        self.assertEqual(stale["code"], "E_CONFLICT")
        no_opt_in = dict(self.env, CREO_CLI_EXPERIMENTAL_NATIVE_WRITES="0")
        self.assertEqual(
            self.gated(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                status=4,
                env=no_opt_in,
            )["error"]["code"],
            "E_FORBIDDEN",
        )
        self.assertNotIn("feature.extrude", self.world.ops())

    def test_token_is_bound_to_state_request_and_one_use(self):
        m = self.part()
        dry = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        m["features"].append(
            {
                "id": 900,
                "name": "GUI_EDIT",
                "type": "FEATTYPE_ROUND",
                "status": "FEAT_ACTIVE",
                "visible": True,
                "parents": [],
                "children": [],
                "surfaces": 2,
            }
        )
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                "--confirm",
                dry["confirm_token"],
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        dry = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        deeper = self.request(dict(RECT, depth=11), "deeper.json")
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                deeper,
                "--confirm",
                dry["confirm_token"],
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        dry = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["confirm_token"],
        )
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                "--confirm",
                dry["confirm_token"],
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.assertEqual(self.world.ops().count("feature.extrude"), 1)

    def test_malformed_requests_never_reach_creo(self):
        self.part()
        bowtie = {"type": "polygon", "points": [[0, 0], [10, 10], [10, 0], [0, 10]]}
        folded = {"type": "polygon", "points": [[0, 0], [10, 0], [5, 0], [5, 5]]}
        repeated = {"type": "polygon", "points": [[0, 0], [10, 0], [10, 0], [5, 5]]}
        flat = {"type": "polygon", "points": [[0, 0], [5, 0], [10, 0]]}
        cases = [
            dict(RECT, extra=1),
            {k: v for k, v in RECT.items() if k != "units"},
            dict(RECT, depth=0),
            dict(RECT, depth="10"),
            dict(RECT, material="remove", body="new"),
            dict(RECT, sketch=dict(RECT["sketch"], orient_ref="front")),
            dict(RECT, sketch=dict(RECT["sketch"], references=["TOP", "TOP"])),
            dict(RECT, sketch=dict(RECT["sketch"], references=["FRONT", "TOP"])),
            dict(RECT, sketch=dict(RECT["sketch"], profile={"type": "slot", "width": 1})),
            dict(
                RECT,
                sketch=dict(RECT["sketch"], profile={"type": "circle", "diameter": 5, "radius": 2}),
            ),
            dict(
                RECT,
                sketch=dict(
                    RECT["sketch"], profile={"type": "circle", "diameter": 5, "center": [1]}
                ),
            ),
            dict(RECT, name="has space"),
            dict(RECT, units="mils"),
            [],
        ]
        cases += [
            dict(RECT, sketch=dict(RECT["sketch"], profile=p))
            for p in (bowtie, folded, repeated, flat)
        ]
        for i, case in enumerate(cases):
            with self.subTest(case=i):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "extrude",
                        "--model",
                        "block",
                        "--request",
                        self.request(case),
                        "--dry-run",
                        status=2,
                    )["error"]["code"],
                    "E_VALIDATION",
                )
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                "-",
                "--dry-run",
                stdin="{bad",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block.asm",
                "--request",
                self.request(RECT),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(self.world.events, [])

    def test_live_state_refusals(self):
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                "--dry-run",
                status=3,
            )["error"]["code"],
            "E_NOT_FOUND",
        )
        self.part(units=INCH)
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(
            (error["code"], error["details"]["part_length_unit"]), ("E_CONFLICT", "in")
        )
        self.world.models.clear()
        self.part()
        other = dict(RECT, sketch=dict(RECT["sketch"], plane="DTM9"))
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(other),
            "--dry-run",
            status=3,
        )["error"]
        self.assertEqual(error["details"]["datum_planes"], ["RIGHT", "TOP", "FRONT"])
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.world.native = False
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(dict(RECT, name="B2")),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.world.creation_api = False
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(HOLE),
                "--dry-run",
                status=4,
            )["error"]["code"],
            "E_BACKEND_UNAVAILABLE",
        )


class Failures(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def confirm_extrude(self, status):
        return self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), status=status
        )["error"]

    def acknowledge(self, operation_id):
        args = (
            "operation",
            "resolve",
            "--id",
            operation_id,
            "--outcome",
            "not_applied",
            "--evidence",
            "Inspected the part in Creo; no stray feature",
        )
        return self.gated(*args)["data"]

    def test_refusal_at_confirm_leaves_nothing_to_resolve(self):
        self.world.fail = (
            "feature.extrude",
            {"code": "E_NOT_FOUND", "message": "no datum plane named FRONT"},
        )
        error = self.confirm_extrude(3)
        self.assertEqual(
            (error["code"], error["details"]["receipt_status"]),
            ("E_NOT_FOUND", "failed_before_write"),
        )
        self.assertIn("service_message", error["details"]["_untrusted"])
        self.world.fail = None
        self.assertTrue(
            self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))[
                "ok"
            ]
        )

    def test_creo_failure_that_cleaned_up(self):
        self.world.fail = (
            "feature.extrude",
            {
                "code": "E_CREO",
                "message": "XToolkitGeneralError in RedefineFeature",
                "toolkit_function": "RedefineFeature",
                "toolkit_error": -1,
                "stage": "redefine",
                "cleanup": "deleted",
            },
        )
        error = self.confirm_extrude(1)
        self.assertEqual(
            (error["code"], error["details"]["state_after"], error["details"]["receipt_status"]),
            ("E_NATIVE_FAILURE", "observed_unchanged", "failed_unchanged"),
        )
        self.assertEqual(error["details"]["service_details"]["stage"], "redefine")
        self.world.fail = None
        self.assertTrue(
            self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))[
                "ok"
            ]
        )

    def test_creo_failure_that_left_changes_blocks_until_acknowledged(self):
        self.world.fail_after = (
            "feature.extrude",
            {
                "code": "E_CREO",
                "message": "general error",
                "cleanup": "NOT deleted -- the model still holds incomplete feature 40",
            },
        )
        error = self.confirm_extrude(1)
        self.assertEqual(
            (error["details"]["state_after"], error["details"]["receipt_status"]),
            ("observed_changed", "partial"),
        )
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(domain_receipt(error["details"]["receipt"])["status"], "partial")
        self.assertIsNotNone(
            domain_receipt(error["details"]["receipt"])["result"]["observed_after"]
        )
        self.assertIn("left changed", error["message"])
        self.world.fail_after = None
        blocked = self.cli("model", "save", "--model", "block", "--dry-run", status=6)["error"]
        self.assertEqual(blocked["details"]["operation_ids"], [error["details"]["operation_id"]])
        self.assertTrue(self.cli("model", "show", "--model", "block")["ok"])  # reads stay available
        self.acknowledge(error["details"]["operation_id"])
        self.assertTrue(self.cli("model", "save", "--model", "block", "--dry-run")["ok"])

    def test_lost_reply_is_outcome_unknown(self):
        self.world.drop = "feature.extrude"
        error = self.confirm_extrude(6)
        self.assertEqual(
            (error["code"], error["details"]["receipt_status"]), ("E_OUTCOME_UNKNOWN", "unknown")
        )
        self.assertFalse(error["retryable"])
        self.world.drop = None
        self.assertEqual(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT),
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.acknowledge(error["details"]["operation_id"])
        self.assertTrue(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(dict(RECT, name="B2")),
                "--dry-run",
            )["ok"]
        )

    def test_withdrawn_before_it_started_is_a_retryable_timeout(self):
        self.world.busy = "feature.extrude"
        error = self.confirm_extrude(8)
        self.assertEqual(
            (error["code"], error["details"]["started"], error["details"]["receipt_status"]),
            ("E_TIMEOUT", False, "failed_before_write"),
        )
        self.assertTrue(error["retryable"])

    def test_started_but_unfinished_is_outcome_unknown(self):
        self.world.overrun = "feature.extrude"
        error = self.confirm_extrude(6)
        self.assertEqual(
            (error["code"], error["details"]["receipt_status"]), ("E_OUTCOME_UNKNOWN", "unknown")
        )

    def test_deadline_after_sending_is_outcome_unknown(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        dry = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        self.world.block = ("feature.extrude", gate)
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["confirm_token"],
            "--timeout",
            "1.5",
            status=6,
        )["error"]
        gate.set()
        self.assertEqual(
            (error["code"], error["details"]["cause_code"]), ("E_OUTCOME_UNKNOWN", "E_TIMEOUT")
        )

    def test_wait_budget_stays_below_the_deadline(self):
        self.cli("model", "show", "--model", "block", "--timeout", "20")
        budget = int(self.world.wait_headers[-1])
        self.assertTrue(17000 <= budget <= 19000, budget)

    def test_failed_postcondition(self):
        self.world.wrong_type = True
        error = self.confirm_extrude(1)
        self.assertEqual(
            (error["code"], error["details"]["receipt_status"]),
            ("E_VERIFY_FAILED", "verification_failed"),
        )
        self.assertEqual(
            [c["check"] for c in error["details"]["failed_checks"]], ["feature_type_as_requested"]
        )

    def test_a_save_that_wrote_nothing_is_caught(self):
        self.world.lie = "model.save"
        error = self.gated("model", "save", "--model", "block", status=1)["error"]
        self.assertIn(
            "one_new_version_on_disk", [c["check"] for c in error["details"]["failed_checks"]]
        )

    def test_service_down_at_confirm_leaves_no_receipt(self):
        dry = self.cli(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), "--dry-run"
        )["data"]
        env = dict(self.env, CREO_CLI_SERVICE_URL=f"http://127.0.0.1:{free_port()}")
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(RECT),
            "--confirm",
            dry["confirm_token"],
            status=4,
            env=env,
        )["error"]
        self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual([r["status"] for r in self.receipts()], ["planned"])

    def test_token_problems(self):
        (self.root / "service-token").write_text("0" * 64, encoding="ascii")
        self.assertEqual(self.cli("model", "list", status=4)["error"]["code"], "E_AUTH")
        (self.root / "service-token").write_text("not a token", encoding="ascii")
        self.assertEqual(
            self.cli("model", "list", status=4)["error"]["code"], "E_BACKEND_UNAVAILABLE"
        )
        (self.root / "service-token").unlink()
        error = self.cli("model", "list", status=4)["error"]
        self.assertIn("token_file", error["details"]["_untrusted"])

    def test_endpoint_must_be_loopback(self):
        for url in (
            "http://example.com:9057",
            "http://127.0.0.1:9057/op",
            "https://127.0.0.1:9057",
            "http://u:p@127.0.0.1:9057",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.cli(
                        "model", "list", status=4, env=dict(self.env, CREO_CLI_SERVICE_URL=url)
                    )["error"]["code"],
                    "E_CONFIG",
                )

    def test_not_the_service(self):
        self.world.health_broken = True
        self.assertEqual(self.cli("model", "list", status=1)["error"]["code"], "E_PROTOCOL")


class Operation(Base):
    def test_list_show_and_acknowledge(self):
        self.part()
        self.world.drop = "feature.extrude"
        error = self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), status=6
        )["error"]
        op_id = error["details"]["operation_id"]
        self.world.drop = None
        self.assertEqual(
            [
                r["status"]
                for r in self.cli("operation", "list", "--status", "unknown")["data"]["items"]
            ],
            ["unknown"],
        )
        shown = self.cli("operation", "show", "--id", op_id)["data"]
        self.assertEqual(shown["operation_status"]["capability_id"], "feature-extrude")
        self.assertEqual(shown["operation_status"]["receipt"]["outcome"]["execution"], "unknown")
        self.assertEqual(
            self.cli("operation", "show", "--id", "nope", status=2)["error"]["code"], "E_VALIDATION"
        )
        self.assertEqual(
            self.cli("operation", "show", "--id", "0" * 32, status=3)["error"]["code"],
            "E_NOT_FOUND",
        )
        short = self.cli(
            "operation",
            "resolve",
            "--id",
            op_id,
            "--outcome",
            "not_applied",
            "--evidence",
            "ok",
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(short["code"], "E_VALIDATION")
        read_only = dict(self.env, CREO_CLI_PERMISSION="read")
        dry = self.cli(
            "operation",
            "resolve",
            "--id",
            op_id,
            "--outcome",
            "not_applied",
            "--evidence",
            "Looked at Creo: nothing was built",
            "--dry-run",
            env=read_only,
        )["data"]
        self.assertEqual(
            self.cli(
                "operation",
                "resolve",
                "--id",
                op_id,
                "--outcome",
                "not_applied",
                "--evidence",
                "Looked at Creo: nothing was built",
                "--confirm",
                dry["confirm_token"],
                status=4,
                env=read_only,
            )["error"]["code"],
            "E_FORBIDDEN",
        )
        done = self.gated(
            "operation",
            "resolve",
            "--id",
            op_id,
            "--outcome",
            "not_applied",
            "--evidence",
            "Looked at Creo: nothing was built",
        )["data"]
        self.assertEqual(done["operation_status"]["resolution"]["outcome"], "not_applied")
        self.assertEqual(
            self.cli(
                "operation",
                "resolve",
                "--id",
                op_id,
                "--outcome",
                "not_applied",
                "--evidence",
                "Looked at Creo again today",
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        completed = self.gated(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(dict(RECT, name="B2")),
        )["data"]
        stored = self.cli("operation", "show", "--id", completed["operation_id"])["data"]
        self.assertEqual(
            stored["operation_status"]["receipt"]["extensions"]["creo"]["domain_result"]["feature"][
                "name"
            ],
            "B2",
        )


class Flags(Base):
    def test_write_flags(self):
        self.part()
        self.assertEqual(
            self.cli("model", "save", "--model", "block", status=5)["error"]["code"],
            "E_CONFIRMATION_REQUIRED",
        )
        self.assertEqual(
            self.cli("model", "show", "--model", "block", "--dry-run", status=2)["error"]["code"],
            "E_USAGE",
        )
        self.assertEqual(
            self.cli(
                "model", "save", "--model", "block", "--dry-run", "--confirm", "ct_x", status=2
            )["error"]["code"],
            "E_USAGE",
        )
        self.assertEqual(
            self.cli(
                "model", "save", "--model", "block", "--dry-run", "--fields", "preview", status=2
            )["error"]["code"],
            "E_USAGE",
        )
        self.assertEqual(
            self.cli("model", "save", "--model", "block", "--dry-run", "--dangerous", status=2)[
                "error"
            ]["code"],
            "E_USAGE",
        )
        self.assertEqual(
            self.cli("model", "save", "--model", "block", "--confirm", "ct_forged.x", status=6)[
                "error"
            ]["code"],
            "E_CONFLICT",
        )

    def test_global_flags(self):
        self.part()
        self.assertEqual(
            self.cli("model", "show", "--model", "block", "--fields", "model,units.length")["data"][
                "units"
            ],
            {"length": "mm"},
        )
        self.assertEqual(
            self.cli("model", "list", "--limit", "0", status=2)["error"]["code"], "E_USAGE"
        )
        self.assertEqual(
            self.cli("model", "list", "--timeout", "0", status=2)["error"]["code"], "E_USAGE"
        )
        self.assertEqual(
            self.cli("model", "list", "--nonsense", status=2)["error"]["code"], "E_USAGE"
        )
        self.assertEqual(self.cli(status=2)["error"]["code"], "E_USAGE")
        self.assertEqual(self.cli("model", status=2)["error"]["code"], "E_USAGE")
        version = self.cli("--version")["data"]
        self.assertEqual(version["tool"], "creo-cli")


if __name__ == "__main__":
    unittest.main()
