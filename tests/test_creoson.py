from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from creo_cli import registry
from creo_cli.cli import main
from creo_cli.core import CODES, Error, canonical
from creo_cli.creoson_catalog import OPS, BY_PATH
from creo_cli.creoson_engine import manifest, normalize
from creo_cli import creoson_state as store
from creo_cli.creoson_transport import Client, cache_path, endpoint
from tests.creoson_fixture import Server, World

ROOT = Path(__file__).resolve().parents[1]


class NativeProtocol(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        # Resolve like workspace() does: the temporary root reaches the CLI as
        # CREO_CLI_WORKSPACE, and every path it reports back is resolved. Comparing
        # against an unresolved root fails wherever the two spellings differ --
        # macOS (/var -> /private/var) and Windows 8.3 names (RUNNER~1 -> runneradmin).
        self.root = Path(self.temp.name).resolve()
        self.world = World(self.root)
        self.server = Server(self.world); self.addCleanup(self.server.close)
        self.env = dict(os.environ, CREO_CLI_CONFIG_DIR=str(self.root / "state"), CREO_CLI_WORKSPACE=str(self.root),
                        CREO_CLI_PERMISSION="write", CREO_CLI_EXPERIMENTAL_NATIVE_WRITES="1", CREO_CLI_CREOSON_URL=self.server.url)
        self.env.pop("CREO_CLI_CREOSON_SESSION", None)
        with patch.dict(os.environ, self.env, clear=True):
            p = cache_path(); p.parent.mkdir(mode=0o700)
            p.write_bytes(canonical({"endpoint": self.server.url, "session_id": self.world.sid, "creo_major": 10, "version_configured": True}))

    def cli(self, *args, status=0, env=None):
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env or self.env, clear=True), redirect_stdout(out), redirect_stderr(err):
            code = main([str(a) for a in args])
        result = json.loads(out.getvalue())
        self.assertEqual(code, status, result)
        self.assertEqual(set(result), {"ok", "schema_version", "meta", "data" if result["ok"] else "error"})
        if not result["ok"]:
            self.assertEqual((code, result["error"]["retryable"]), CODES[result["error"]["code"]])
        self.assertNotIn(self.world.sid, out.getvalue() + err.getvalue())
        return result

    def request_file(self, data, name="request.json"):
        p = self.root / name; p.write_bytes(canonical(data)); return p

    def command(self, path, q=None, *tail, **kw):
        return self.cli(*path.split(), "--request", self.request_file(BY_PATH[path].example if q is None else q), *tail, **kw)

    def gated(self, path, q=None):
        q = copy.deepcopy(BY_PATH[path].example if q is None else q)
        dry = self.command(path, q, "--dry-run")
        return self.command(path, q, "--confirm", dry["data"]["confirm_token"])

    def prepare(self, op):
        if op.path == "file roundtrip": self.world.loaded = ["bracket.prt"]
        if op.path == "file open": self.world.loaded.remove("bracket.prt")
        if op.path == "feature resume": self.world.models["bracket.prt"]["features"][0]["status"] = "SUPPRESSED"
        if op.path == "drawing create":
            self.world.loaded.remove("bracket.drw"); (self.root / "bracket.drw").unlink()
        if op.path == "creo mkdir": (self.root / "exports").rmdir()
        if op.path == "creo rmdir":
            for leftover in (self.root / "exports").iterdir(): leftover.unlink()
        if op.path == "drawing add-model": self.world.models["bracket.drw"]["models"] = []
        if op.path == "drawing create-view": self.world.models["bracket.drw"]["drawing_views"] = []

    def test_connect_and_status(self):
        old_count = len(self.world.events)
        dry = self.cli("creoson", "connect", "--creo-major", "10", "--dry-run")
        self.assertEqual(len(self.world.events), old_count)
        r = self.cli("creoson", "connect", "--creo-major", "10", "--confirm", dry["data"]["confirm_token"])
        self.assertIsNone(r["data"]["creo_major_detected"])
        self.assertEqual(self.world.major, 10)
        self.assertTrue(self.cli("creoson", "status")["data"]["running"])

    def test_connect_rejects_invalid_version(self):
        self.cli("creoson", "connect", "--creo-major", "-1", "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_read_missing_session_does_not_connect(self):
        with patch.dict(os.environ, self.env, clear=True): cache_path().unlink()
        r = self.command("file list", status=4)
        self.assertEqual(r["error"]["code"], "E_CONFIG"); self.assertFalse(self.world.events)

    def test_unknown_fields_before_network(self):
        self.command("dimension set", BY_PATH["dimension set"].example | {"silent_override": True}, "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_no_permission_before_network(self):
        self.command("file save", None, "--dry-run", status=4, env=dict(self.env, CREO_CLI_PERMISSION="read"))
        self.assertFalse(self.world.events)

    def test_opt_in_before_network(self):
        env = dict(self.env); env.pop("CREO_CLI_EXPERIMENTAL_NATIVE_WRITES")
        self.command("file save", None, "--dry-run", status=4, env=env)
        self.assertFalse(self.world.events)

    def test_dry_run_never_mutates_server_or_artifacts(self):
        before = copy.deepcopy(self.world.models)
        files = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.command("dimension set", None, "--dry-run")
        self.assertEqual(before, self.world.models)
        for p, content in files.items(): self.assertEqual(Path(p).read_bytes(), content)
        self.assertFalse(any(f in ("set", "save", "assemble", "regenerate") for _, f, _ in self.world.events))

    def test_unit_mismatch_no_write(self):
        self.world.models["bracket.prt"]["length_units"] = "inch"
        self.command("dimension set", None, "--dry-run", status=6)
        self.assertFalse(any(f == "set" for _, f, _ in self.world.events))

    def test_relation_dimension_refused(self):
        self.world.models["bracket.prt"]["postregen_relations"] = ["d1 = 12"]
        self.command("dimension set", None, "--dry-run", status=6)

    def test_relation_parameter_refused(self):
        self.world.models["bracket.prt"]["relations"] = ['PART_NO="ABC"']
        self.command("parameter set", None, "--dry-run", status=6)

    def test_angular_dimension_refused(self):
        self.world.models["bracket.prt"]["dimensions"][0]["dim_type"] = "angular"
        self.command("dimension set", None, "--dry-run", status=2)

    def test_drawn_dimension_refused(self):
        self.world.models["bracket.prt"]["dimensions"][0]["dwg_dim"] = True
        self.command("dimension set", None, "--dry-run", status=2)

    def test_wrong_parameter_type(self):
        q = BY_PATH["parameter set"].example | {"type": "INTEGER", "value": True}
        self.command("parameter set", q, "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_parameter_create_explicit(self):
        q = BY_PATH["parameter set"].example | {"create": True, "name": "NEW_PARAMETER"}
        self.gated("parameter set", q)
        self.assertFalse([d for c, f, d in self.world.events if (c, f) == ("parameter", "set")][-1]["no_create"])

    def test_parameter_missing_not_silently_created(self):
        self.command("parameter set", BY_PATH["parameter set"].example | {"name": "MISSING"}, "--dry-run", status=6)

    def test_stale_in_memory_state_rejects_token(self):
        d = self.command("dimension set", None, "--dry-run")
        self.world.models["bracket.prt"]["dimensions"][0]["value"] = 42
        self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=6)
        self.assertFalse(any(f == "set" for _, f, _ in self.world.events))

    def test_stale_disk_state_rejects_token(self):
        d = self.command("file save", None, "--dry-run")
        (self.root / "bracket.prt").write_bytes(b"someone changed the disk model")
        self.command("file save", None, "--confirm", d["data"]["confirm_token"], status=6)

    def test_changed_arguments_rejects_token(self):
        d = self.command("dimension set", None, "--dry-run")
        self.command("dimension set", BY_PATH["dimension set"].example | {"value": 46}, "--confirm", d["data"]["confirm_token"], status=6)

    def test_replayed_unchanging_ui_token_refused(self):
        d = self.command("file close-window", None, "--dry-run")
        self.command("file close-window", None, "--confirm", d["data"]["confirm_token"])
        self.command("file close-window", None, "--confirm", d["data"]["confirm_token"], status=6)
        self.assertEqual(sum(f == "close_window" for _, f, _ in self.world.events), 1)

    def test_export_never_overwrites(self):
        (self.root / "exports" / "bracket.step").write_bytes(b"precious")
        self.command("export step", None, "--dry-run", status=6)
        self.assertEqual((self.root / "exports" / "bracket.step").read_bytes(), b"precious")

    def test_export_filename_traversal_refused(self):
        self.command("export pdf", BY_PATH["export pdf"].example | {"filename": "../bad.pdf"}, "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_export_outside_workspace_refused(self):
        self.command("export step", BY_PATH["export step"].example | {"dirname": ".."}, "--dry-run", status=4)

    def test_wildcard_target_refused(self):
        self.command("file save", {"file": "*.prt"}, "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_assembly_requires_noninteractive_constraints(self):
        q = BY_PATH["assembly assemble"].example | {"constraints": []}
        self.command("assembly assemble", q, "--dry-run", status=2)
        self.assertFalse(self.world.events)

    def test_fixed_assembly_exact_transform(self):
        q = BY_PATH["assembly assemble"].example | {"constraints": [{"type": "fix"}], "transform": {"origin": {"x": 1, "y": 2, "z": 3}, "x_rot": 90}}
        self.gated("assembly assemble", q)
        req = [d for c, f, d in self.world.events if (c, f) == ("file", "assemble")][-1]
        self.assertTrue(req["package_assembly"]); self.assertFalse(req["walk_children"])

    def test_projection_diagonal_rejected(self):
        self.command("drawing project-view", BY_PATH["drawing project-view"].example | {"point": {"x": 1, "y": 1}}, "--dry-run", status=2)

    def test_suppress_never_uses_broad_defaults(self):
        self.gated("feature suppress")
        req = [d for c, f, d in self.world.events if (c, f) == ("feature", "suppress")][-1]
        self.assertIs(req["clip"], False); self.assertIs(req["with_children"], False)

    def test_integer_ids_are_normalized(self):
        r = self.command("feature list")["data"]["result"]
        self.assertTrue(all(type(x["feat_id"]) is str for x in r["items"]))
        t = self.command("assembly transform")["data"]["result"]
        self.assertIn("origin", t)
        request = [d for c, f, d in self.world.events if f == "get_transform"][-1]
        self.assertEqual(request["path"], [39])

    def test_pagination_is_explicit(self):
        a = self.command("feature list", None, "--limit", "1")["data"]["result"]
        self.assertEqual((a["count"], a["has_more"], a["next_offset"]), (1, True, 1))
        b = self.command("feature list", None, "--offset", "99")["data"]["result"]
        self.assertEqual(b["items"], [])

    def test_live_claim_stays_false(self):
        r = self.gated("dimension set")["data"]
        self.assertFalse(r["provenance"]["live_verified"])
        self.assertIn("full_geometry", r["last_result"]["verification"]["not_checked"])

    def test_failed_readback_blocks_further_writes(self):
        d = self.command("dimension set", None, "--dry-run")
        self.world.skip_mutation = True
        r = self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=1)
        self.assertEqual(r["error"]["code"], "E_VERIFY_FAILED")
        self.command("file save", None, "--dry-run", status=6)

    def test_lost_reply_is_unknown_not_retryable(self):
        d = self.command("dimension set", None, "--dry-run")
        self.world.drop = ("dimension", "set")
        r = self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=6)
        self.assertEqual(r["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertFalse(r["error"]["retryable"])
        self.assertEqual(self.world.models["bracket.prt"]["dimensions"][0]["value"], 45)
        self.assertEqual(sum(f == "set" for _, f, _ in self.world.events), 1)
        self.command("file save", None, "--dry-run", status=6)

    def test_http_error_mapping(self):
        for code, exit_code in ((401, 4), (403, 4), (404, 3), (408, 8), (409, 6), (429, 7), (500, 7), (302, 1)):
            with self.subTest(http=code):
                self.world.http_status = code
                self.command("file list", status=exit_code)

    def test_business_error_redacts_session(self):
        self.world.fail = ("file", "list")
        self.command("file list", status=1)

    def test_malformed_json(self):
        self.world.bad_json = True
        self.command("file list", status=1)

    def test_total_timeout(self):
        self.world.delay = ("file", "list", .25)
        self.command("file list", None, "--timeout", ".1", status=8)

    def test_no_redirect_remote_or_proxy(self):
        for value in ("https://example.org/creoson", "http://example.org/creoson", "http://127.0.0.1:9056/admin", "http://u:p@127.0.0.1:9056/creoson"):
            with self.subTest(url=value):
                self.command("file list", status=4, env=dict(self.env, CREO_CLI_CREOSON_URL=value))
        self.assertFalse(self.world.events)
        self.command("file list", env=dict(self.env, HTTP_PROXY="http://bad.invalid", ALL_PROXY="http://bad.invalid"))

    def test_workflow_read_write_save_export(self):
        steps = [
            {"id": "inspect", "command": "dimension list", "request": {"file": "bracket.prt"}},
            {"id": "pitch", "command": "dimension set", "request": BY_PATH["dimension set"].example},
            {"id": "regen", "command": "file regenerate", "request": {"file": "bracket.prt"}},
            {"id": "save", "command": "file save", "request": {"file": "bracket.prt"}},
            {"id": "export", "command": "export step", "request": BY_PATH["export step"].example}]
        p = self.request_file({"workflow_schema": "1.0", "steps": steps}, "workflow.json")
        self.cli("workflow", "validate", "--input", p)
        d = self.cli("workflow", "run", "--input", p, "--dry-run")
        r = self.cli("workflow", "run", "--input", p, "--confirm", d["data"]["confirm_token"])["data"]
        self.assertEqual(r["completed_steps"], 5)
        self.assertTrue((self.root / "exports" / "bracket.step").is_file())
        receipt = self.cli("workflow", "status", "--operation-id", r["operation_id"])["data"]["receipt"]
        self.assertEqual(receipt["status"], "completed")
        saved = self.cli("workflow", "result", "--operation-id", r["operation_id"], "--step-id", "inspect")
        self.assertEqual(saved["data"]["result"]["operation"], "dimension list")
        self.assertEqual(self.cli("workflow", "history")["data"]["count"], 1)

    def test_workflow_template_and_two_views(self):
        self.prepare(BY_PATH["drawing create"])
        steps = [{"id": str(i), "command": p, "request": BY_PATH[p].example} for i, p in enumerate(("drawing create", "drawing create-view", "drawing project-view", "drawing regenerate", "export pdf"))]
        for i, s in enumerate(steps): s["id"] = "step_" + str(i)
        p = self.request_file({"workflow_schema": "1.0", "steps": steps})
        d = self.cli("workflow", "run", "--input", p, "--dry-run")
        self.assertEqual(d["data"]["preview"]["steps"][1]["state_check"], "deferred_until_execution")
        self.cli("workflow", "run", "--input", p, "--confirm", d["data"]["confirm_token"])
        self.assertEqual(len(self.world.models["bracket.drw"]["drawing_views"]), 2)

    def test_workflow_partial_and_human_reconciliation(self):
        p = self.request_file({"workflow_schema": "1.0", "steps": [{"id": "change", "command": "dimension set", "request": BY_PATH["dimension set"].example}, {"id": "regen", "command": "file regenerate", "request": {"file": "bracket.prt"}}]})
        d = self.cli("workflow", "run", "--input", p, "--dry-run")
        self.world.fail = ("file", "regenerate")
        r = self.cli("workflow", "run", "--input", p, "--confirm", d["data"]["confirm_token"], status=6)
        rid = r["error"]["details"]["operation_id"]
        self.assertEqual(r["error"]["details"]["completed_steps"], 1)
        self.cli("workflow", "status", "--operation-id", rid)
        args = ["workflow", "reconcile", "--operation-id", rid, "--acknowledge", "human-inspected-server-idle", "--note", "TEST ONLY: server operation stopped and disposable state inspected"]
        d = self.cli(*args, "--dry-run")
        r = self.cli(*args, "--confirm", d["data"]["confirm_token"])
        self.assertEqual(r["data"]["receipt"]["status"], "human_acknowledged")
        self.assertFalse(r["data"]["receipt"]["rollback_performed"])

    def test_workflow_rejects_raw_calls_and_duplicate_ids(self):
        base = {"workflow_schema": "1.0", "steps": [{"id": "x", "command": "interface mapkey", "request": {}}]}
        self.cli("workflow", "validate", "--input", self.request_file(base), status=2)
        s = {"id": "x", "command": "file list", "request": {}}
        self.cli("workflow", "validate", "--input", self.request_file({"workflow_schema": "1.0", "steps": [s, s]}), status=2)
        self.assertFalse(self.world.events)

    def test_duplicate_workflow_export_refused(self):
        s = {"command": "export step", "request": BY_PATH["export step"].example}
        p = self.request_file({"workflow_schema": "1.0", "steps": [s | {"id": "one"}, s | {"id": "two"}]})
        self.cli("workflow", "run", "--input", p, "--dry-run", status=6)

    def test_mass_context_is_not_unit_density(self):
        r = self.command("file massprops")["data"]["result"]
        self.assertEqual(r["unit_context"]["length_units"], "mm")
        self.assertFalse(r["unit_context"]["material_assignment_verified"])
        req = [d for c, f, d in self.world.events if f == "massprops"][-1]
        self.assertNotIn("density", req)

    def test_journal_storage_failure_refuses_write(self):
        d = self.command("dimension set", None, "--dry-run")
        with patch("creo_cli.creoson_state.begin", side_effect=Error("E_IO", "test disk full")):
            self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=1)
        self.assertFalse(any(f == "set" for _, f, _ in self.world.events))

    def test_cli_subprocess_uses_actual_http(self):
        p = self.request_file({"file": "bracket.prt"})
        r = subprocess.run([sys.executable, "-m", "creo_cli", "dimension", "list", "--request", str(p), "--compact"], cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])
        self.assertTrue(self.world.events)

    def test_bundled_request_and_workflow_examples(self):
        for op in OPS:
            p = ROOT / "examples" / "requests" / (op.path.replace(" ", "-") + ".json")
            self.assertEqual(op.validate(json.loads(p.read_text())), op.example)
        for p in (ROOT / "examples").glob("workflow-*.json"):
            self.assertTrue(manifest(json.loads(p.read_text())))

    def test_sources_schemas_and_examples_present(self):
        r = self.cli("reference")["data"]
        for op in OPS:
            c = next(c for c in r["commands"] if c["path"] == op.path)
            self.assertEqual(c["request_schema"], op.request_schema)
            self.assertFalse(c["source"]["live_verified"])
            self.assertEqual(op.validate(op.example), op.example)


    def test_roundtrip_refuses_shared_session(self):
        self.command("file roundtrip", None, "--dry-run", status=6)
        self.assertFalse(any(fn in ("save", "erase") for _, fn, _ in self.world.events))

    def test_roundtrip_observations_reloaded_from_saved_artifact(self):
        self.world.loaded = ["bracket.prt"]
        self.world.models["bracket.prt"]["dimensions"][0]["value"] = 47
        r = self.gated("file roundtrip")["data"]["last_result"]
        self.assertTrue(r["result"]["roundtrip_verified"])
        self.assertIn("dimensions", r["result"]["compared_sections"])
        self.assertNotIn("reopen_persistence", r["verification"]["not_checked"])
        requests = [(c, f) for c, f, _ in self.world.events]
        self.assertLess(requests.index(("file", "save")), requests.index(("file", "erase")))
        self.assertLess(requests.index(("file", "erase")), requests.index(("file", "open")))

    def test_export_stages_instead_of_exposing_final_path(self):
        r = self.gated("export step")["data"]["last_result"]["result"]
        req = [q for c, f, q in self.world.events if (c, f) == ("interface", "export_file")][-1]
        self.assertIn(".creo-cli-staging", req["dirname"])
        self.assertEqual(r["publish_policy"], "atomic_no_clobber")
        self.assertEqual(r["artifact"]["path"], str(self.root / "exports" / "bracket.step"))

    def test_export_publication_race_preserves_user_file(self):
        original = self.world.operation
        final = self.root / "exports" / "bracket.step"
        def race(c, f, q):
            result = original(c, f, q)
            if (c, f) == ("interface", "export_file"):
                final.write_bytes(b"RACING USER FILE")
            return result
        self.world.operation = race
        d = self.command("export step", None, "--dry-run")
        self.command("export step", None, "--confirm", d["data"]["confirm_token"], status=6)
        self.assertEqual(final.read_bytes(), b"RACING USER FILE")

    def test_export_rejects_wrong_header(self):
        original = self.world.operation
        def corrupt(c, f, q):
            result = original(c, f, q)
            if (c, f) == ("interface", "export_file"):
                (Path(q["dirname"]) / q["filename"]).write_bytes(b"not STEP")
            return result
        self.world.operation = corrupt
        d = self.command("export step", None, "--dry-run")
        r = self.command("export step", None, "--confirm", d["data"]["confirm_token"], status=1)
        self.assertEqual(r["error"]["code"], "E_VERIFY_FAILED")
        self.assertFalse((self.root / "exports" / "bracket.step").exists())

    def test_save_requires_new_disk_evidence(self):
        d = self.command("file save", None, "--dry-run")
        self.world.skip_mutation = True
        r = self.command("file save", None, "--confirm", d["data"]["confirm_token"], status=1)
        self.assertEqual(r["error"]["code"], "E_VERIFY_FAILED")

    def test_readback_transport_failure_does_not_allow_retry(self):
        d = self.command("dimension set", None, "--dry-run")
        original = self.world.operation
        def inject(c, f, q):
            result = original(c, f, q)
            if (c, f) == ("dimension", "set"):
                self.world.fail = ("dimension", "list_detail")
            return result
        self.world.operation = inject
        r = self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=1)
        self.assertFalse(r["error"]["retryable"])
        self.command("file save", None, "--dry-run", status=6)

    def test_crash_intent_blocks_new_calls(self):
        with patch.dict(os.environ, self.env, clear=True):
            store.begin({"session": "not-a-secret"}, "workflow run", [])
        self.command("dimension set", None, "--dry-run", status=6)
        self.assertFalse(self.world.events)

    def test_nested_result_schema_refuses_wrong_dimensions(self):
        self.world.models["bracket.prt"]["dimensions"][0]["value"] = {"bad": "shape"}
        self.command("dimension list", status=1)

    def test_result_integrity_and_unknown_step(self):
        r = self.gated("dimension set")["data"]
        rid = r["operation_id"]
        self.cli("workflow", "result", "--operation-id", rid, "--step-id", "missing", status=3)
        p = self.root / "state" / "creoson-results" / rid / "operation.json"
        p.write_bytes(b"{}")
        q = self.cli("workflow", "result", "--operation-id", rid, "--step-id", "operation", status=1)
        self.assertEqual(q["error"]["code"], "E_INTEGRITY")

    def test_read_only_without_workspace_is_usable(self):
        env = dict(self.env); env.pop("CREO_CLI_WORKSPACE")
        self.command("dimension list", env=env)
        self.command("dimension set", None, "--dry-run", env=env, status=4)

    def test_ambiguous_loaded_model_identity_refused(self):
        self.world.loaded.append("BRACKET.PRT")
        self.command("dimension list", status=1)

    def test_context_does_not_contact_creoson(self):
        self.cli("context"); self.cli("doctor"); self.cli("reference")
        self.assertFalse(self.world.events)

    def test_session_replacement_invalidates_token(self):
        d = self.command("dimension set", None, "--dry-run")
        with patch.dict(os.environ, self.env, clear=True):
            cache = json.loads(cache_path().read_text())
            cache["session_id"] = "a-new-private-session"
            cache_path().write_bytes(canonical(cache))
        self.world.sid = "a-new-private-session"
        self.command("dimension set", None, "--confirm", d["data"]["confirm_token"], status=6)

    def test_symlink_export_directory_refused(self):
        if os.name == "nt":
            self.skipTest("symlink creation requires platform privileges")
        outside = self.root / "linked_exports"
        outside.symlink_to(self.root / "exports", target_is_directory=True)
        self.command("export step", BY_PATH["export step"].example | {"dirname": "linked_exports"}, "--dry-run", status=4)

    def test_corrupt_persisted_history_fails_closed(self):
        with patch.dict(os.environ, self.env, clear=True):
            db = store._db(); db.execute("INSERT INTO runs VALUES ('bad','bad','running','not-json')"); db.close()
        self.command("file save", None, "--dry-run", status=1)
        self.assertFalse(self.world.events)

    def test_http_timeout_after_write_keeps_unknown_receipt(self):
        d = self.command("dimension set", None, "--dry-run")
        # Hold the write open until this call has returned. A fixed sleep would have to
        # outlast the preliminary reads as well, and those alone can exhaust a short
        # deadline on a loaded machine -- then the command times out before the write is
        # sent and reports a plain E_TIMEOUT, which is not what this test is about.
        release = threading.Event(); self.addCleanup(release.set)
        self.world.block = ("dimension", "set", release)
        r = self.command("dimension set", None, "--timeout", "1", "--confirm", d["data"]["confirm_token"], status=6)
        self.assertEqual(r["error"]["code"], "E_OUTCOME_UNKNOWN")
        # Timing out before the write instead reports receipt_status failed_before_write,
        # which would pass the status check above for the wrong reason.
        self.assertEqual(r["error"]["details"]["receipt_status"], "unknown")

    def test_reference_reports_composed_roundtrip(self):
        r = self.cli("reference", "--command", "file roundtrip")["data"]
        self.assertEqual(r["commands"][0]["upstream_sequence"], ["file.save", "file.close_window", "file.erase", "file.open"])
        self.assertFalse(r["commands"][0]["live_verified"])


    def test_released_coordinate_system_spelling(self):
        result = self.gated("assembly assemble")["data"]
        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["provenance"]["live_verified"])

    def test_documented_coordinate_system_alias(self):
        for model in self.world.models.values():
            for feature in model["features"]:
                if feature["type"] == "COORDINATE SYSTEM":
                    feature["type"] = "COORD_SYS"
        self.gated("assembly assemble")

    def test_released_unnamed_feature_response(self):
        self.world.models["bracket.prt"]["features"].append(
            {"type": "CURVE", "status": "ACTIVE", "feat_id": 620, "feat_number": 25})
        result = self.command("feature list")["data"]
        row = next(x for x in result["result"]["items"] if x["feat_id"] == "620")
        self.assertNotIn("name", row)
        self.assertIn("upstream_feature_listing_is_visible_features_only", result["not_checked"])

    def test_released_dimension_text_is_array(self):
        result = self.command("dimension list")["data"]["result"]
        self.assertEqual(result["items"][0]["text"], ["{0:@D}\n"])
        self.world.models["bracket.prt"]["dimensions"][0]["text"] = {"bad": "shape"}
        self.command("dimension list", status=1)

    def test_transform_rotation_fields_are_typed(self):
        result = self.command("assembly transform")["data"]["result"]
        self.assertEqual([result[k] for k in ("x_rot", "y_rot", "z_rot")], [0.0, 0.0, 0.0])
        schema = self.cli("reference", "--command", "assembly transform")["data"]
        schemas = schema["schemas"]
        matching = [v["json_schema"] for v in schemas.values() if "result" in v.get("json_schema", {}).get("properties", {})]
        self.assertTrue(any(v["properties"]["result"]["properties"].get("x_rot", {}).get("type") == "number" for v in matching))


    def test_drawing_modal_risk_is_machine_visible(self):
        self.prepare(BY_PATH["drawing create"])
        ref = self.cli("reference", "--command", "drawing create")["data"]["commands"][0]
        self.assertIn("upstream_may_open_modal_error_dialog", ref["interaction_risks"])
        dry = self.command("drawing create", None, "--dry-run")["data"]["preview"]
        self.assertIn("client_timeout_does_not_cancel_creo", dry["steps"][0]["interaction_risks"])


# Separate tests for each registered operation, not a single "everything passed"
# assertion. All execute through the public CLI and real loopback HTTP transport.
for _op in OPS:
    def _test(self, op=_op):
        self.prepare(op)
        if op.write:
            r = self.gated(op.path)["data"]
            self.assertEqual(r["status"], "completed")
            self.assertEqual(r["completed_steps"], 1)
        else:
            r = self.command(op.path)["data"]
            self.assertEqual(r["operation"], op.path)
        self.assertFalse(r["provenance"]["simulation"])
        self.assertFalse(r["provenance"]["live_verified"])
    setattr(NativeProtocol, "test_operation_" + _op.path.replace(" ", "_").replace("-", "_"), _test)


for _op in OPS:
    def _invalid(self, op=_op):
        self.command(op.path, op.example | {"unrecognized_option": True}, *( ["--dry-run"] if op.write else []), status=2)
        self.assertFalse(self.world.events)
    setattr(NativeProtocol, "test_reject_unknown_" + _op.path.replace(" ", "_").replace("-", "_"), _invalid)
