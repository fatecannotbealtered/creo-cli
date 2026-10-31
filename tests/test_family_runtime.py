"""Bounded family lifecycle with public CLI fixtures; independent native evidence is separate."""

import copy
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests import test_features
from tests.fixture import Refused
from tests.test_commands import ROOT


class FamilyRuntime(test_features.Built):
    def setUp(self):
        super().setUp()
        self.block()
        dimensions = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        self.depth = next(d["name"] for d in dimensions if d["value"] == 10 and d.get("type"))
        self.body = {
            "units": "mm",
            "instances": [
                {"name": "SHORT", "values": {"dimension:" + self.depth: 12}},
                {"name": "LONG", "values": {"dimension:" + self.depth: 16}},
            ],
        }

    def words(self, body=None):
        source = self.ws / "family.json"
        source.write_text(json.dumps(body or self.body), encoding="utf8")
        return (
            "family-table",
            "apply",
            "--model",
            "block",
            "--request",
            str(source),
        )

    def create(self):
        result = self.gated(*self.words())["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        return result

    def save_close_instances(self):
        self.gated("model", "save", "--model", "block")
        for name in ("short", "long"):
            self.gated("model", "close", "--model", name)

    def fresh(self, *words, status=0):
        p = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, words)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(p.returncode, status, p.stdout[:1200])
        return json.loads(p.stdout)

    def test_public_plan_and_independent_instance_dimensions(self):
        original = copy.deepcopy(self.world.models["block.prt"]["dimensions"])
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        self.assertIn("operation_id", p["preview"])
        self.assertNotIn("family.set", self.world.ops())
        result = self.cli(*args, "--confirm", p["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        for name, length in (("short", 12), ("long", 16)):
            dims = self.cli("dimension", "list", "--model", name)["data"]["items"]
            self.assertEqual(next(d["value"] for d in dims if d["name"] == self.depth), length)
        self.assertEqual(self.world.models["block.prt"]["dimensions"], original)
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("family.set"), 1)

    def test_open_instance_refusal_and_exact_unused_row_removal(self):
        self.create()
        remove = (
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "SHORT",
            "--dangerous",
        )
        self.cli(*remove, "--dry-run", status=6)
        self.assertNotIn("family.remove", self.world.ops())
        self.save_close_instances()
        before = {p.name: p.read_bytes() for p in self.ws.glob("*.prt.*")}
        result = self.gated(*remove)["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        rows = self.cli("family-table", "show", "--model", "block")["data"]["instances"]
        self.assertEqual([r["name"] for r in rows], ["LONG"])
        self.assertEqual({p.name: p.read_bytes() for p in self.ws.glob("*.prt.*")}, before)

    def test_request_identity_and_scope_drift_zero_dispatch(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        file = self.ws / "family.json"
        replacement = self.ws / "replacement.json"
        replacement.write_bytes(file.read_bytes())
        replacement.replace(file)
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertNotIn("family.set", self.world.ops())

    def test_partial_native_restore_does_not_claim_unchanged(self):
        original = self.world.op

        def fail(op, request):
            if op == "family.set":
                original(op, request)
                self.world.models["block.prt"]["family"] = {"columns": [], "rows": {}}
                raise Refused(
                    "E_CREO",
                    "injected regeneration failure; table restored but instances remain",
                    stage="family_table",
                )
            return original(op, request)

        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        with patch.object(self.world, "op", side_effect=fail):
            error = self.cli(*args, "--confirm", p["confirm_token"], status=1)["error"]
        self.assertIn(error["details"]["receipt"]["outcome"]["change"], ("partial", "unknown"))
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_single_row_edit_preserves_other_row_and_generic(self):
        self.create()
        self.save_close_instances()
        before = copy.deepcopy(self.world.models["block.prt"]["dimensions"])
        self.gated(
            *self.words(
                {
                    "units": "mm",
                    "instances": [{"name": "SHORT", "values": {"dimension:" + self.depth: 14}}],
                }
            )
        )
        self.assertEqual(
            next(
                d["value"]
                for d in self.world.models["short.prt"]["dimensions"]
                if d["name"] == self.depth
            ),
            14,
        )
        self.assertEqual(
            next(
                d["value"]
                for d in self.world.models["long.prt"]["dimensions"]
                if d["name"] == self.depth
            ),
            16,
        )
        self.assertEqual(before, self.world.models["block.prt"]["dimensions"])

    def test_unsupported_columns_and_duplicate_names_refuse_before_dispatch(self):
        for body in (
            {"units": "mm", "instances": [{"name": "A", "values": {"parameter:VALUE": 1}}]},
            {"units": "mm", "instances": [{"name": "A", "values": {"feature:BLOCK": False}}]},
            {"units": "mm", "instances": [{"name": "A", "values": {"dimension:" + self.depth: 0}}]},
            {
                "units": "mm",
                "instances": [
                    {"name": "A", "values": {"dimension:" + self.depth: 12}},
                    {"name": "a", "values": {"dimension:" + self.depth: 13}},
                ],
            },
        ):
            with self.subTest(body=body):
                self.cli(*self.words(body), "--dry-run", status=2)
        self.assertNotIn("family.set", self.world.ops())

    def test_related_part_and_unsaved_generic_refuse_removal(self):
        self.create()
        self.save_close_instances()
        remove = (
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "SHORT",
            "--dangerous",
            "--dry-run",
        )
        self.world.models["block.prt"]["modified"] = True
        self.cli(*remove, status=6)
        self.world.models["block.prt"]["modified"] = False
        self.part("guard.prt")
        self.world.models["guard.prt"]["native_dependencies"] = ["short.prt"]
        self.cli(*remove, status=6)
        self.assertNotIn("family.remove", self.world.ops())

    def test_closed_saved_assembly_reference_is_not_unused(self):
        self._closed_reference_case(dispatched=True)

    def test_unconfirmed_reference_plan_does_not_claim_instance_used(self):
        self._closed_reference_case(dispatched=False)

    def _closed_reference_case(self, *, dispatched):
        self.create()
        nested = self.ws / "dependent"
        nested.mkdir()
        self.gated("session", "cd", "--path", nested)
        self.gated("assembly", "create", "--name", "consumer", "--units", "mmns")
        request = nested / "placement.json"
        request.write_text(json.dumps({"units": "mm", "constraints": [{"type": "default"}]}))
        words = (
            "assembly",
            "component",
            "add",
            "--model",
            "consumer.asm",
            "--component",
            "short",
            "--request",
            request,
        )
        if dispatched:
            self.gated(*words)
        else:
            self.cli(*words, "--dry-run")
        self.gated("model", "save", "--model", "consumer.asm")
        self.gated("model", "close", "--model", "consumer.asm")
        self.gated("session", "cd", "--path", self.ws)
        self.save_close_instances()
        result = self.cli(
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "SHORT",
            "--dangerous",
            "--dry-run",
            status=6 if dispatched else 0,
        )
        if dispatched:
            self.assertEqual(result["error"]["code"], "E_CONFLICT")
            self.assertEqual(result["error"]["details"]["reference_model"], "consumer.asm")
        self.assertNotIn("family.remove", self.world.ops())

    def test_reply_loss_preserves_instance_claims_and_requires_current_evidence(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        self.world.drop = "family.set"
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        self.fresh("operation", "show", "--id", ident)
        self.cli("model", "save", "--model", "short", "--dry-run", status=6)
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(
            query["observation"]["family_table_verification"]["can_register"], ["applied"]
        )
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent complete table and current instance geometry protect the generic "
            "and saved files",
        )
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(
            shown["extensions"]["creo"]["family_table_inspection"]["evidence_status"], "verified"
        )
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("family.set"), 1)

    def test_final_receipt_failure_leaves_reliable_checkpoint_and_no_replay(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        db = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        with closing(sqlite3.connect(db)) as con, con:
            con.execute(
                "CREATE TRIGGER final_family_failure BEFORE UPDATE OF body ON operations "
                f"WHEN NEW.id='{ident}' AND json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'test only final receipt failure'); END"
            )
        try:
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        finally:
            with closing(sqlite3.connect(db)) as con, con:
                con.execute("DROP TRIGGER final_family_failure")
        with closing(sqlite3.connect(db)) as con, con:
            retained = json.loads(
                con.execute("SELECT body FROM operations WHERE id=?", (ident,)).fetchone()[0]
            )
        self.assertEqual(
            (retained["status"], retained["driver_stage"], retained["driver_receipt"]),
            ("running", "finalizing", None),
        )
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Complete current native table instance dimensions geometry windows and disk "
            "observations establish the applied change",
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("family.set"), 1)

    def test_recovery_inspection_and_confirmation_are_stable_across_process_hash_seeds(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        self.world.drop = "family.set"
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        observations = []
        for seed in ("0", "1", "2", "3"):
            with patch.dict(self.env, PYTHONHASHSEED=seed):
                query = self.fresh("operation", "query", "--id", ident, "--model", "block")
            observations.append(query["data"]["observation"]["family_table_verification"])
        self.assertTrue(all(row == observations[0] for row in observations[1:]))
        words = (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent stable native dimensions geometry and retained sources "
            "support registration",
        )
        with patch.dict(self.env, PYTHONHASHSEED="0"):
            preview = self.fresh(*words, "--dry-run")["data"]
        with patch.dict(self.env, PYTHONHASHSEED="1"):
            self.fresh(*words, "--confirm", preview["confirm_token"])
        self.assertEqual(self.world.ops().count("family.set"), 1)

    def test_scope_change_before_confirmation_is_zero_dispatch(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        old = scope.read_bytes()
        try:
            changed = json.loads(old)
            changed["effects"] = ["observe"]
            scope.write_text(json.dumps(changed), encoding="utf8")
            error = self.cli(*args, "--confirm", p["confirm_token"], status=6)["error"]
            self.assertEqual(error["details"]["conflict"], "scope_changed")
        finally:
            scope.write_bytes(old)
        self.assertNotIn("family.set", self.world.ops())

    def test_table_drift_rejects_old_confirmation(self):
        self.create()
        self.save_close_instances()
        args = self.words(
            {
                "units": "mm",
                "instances": [{"name": "SHORT", "values": {"dimension:" + self.depth: 14}}],
            }
        )
        p = self.cli(*args, "--dry-run")["data"]
        calls = self.world.ops().count("family.set")
        self.world.models["block.prt"]["family"]["rows"]["LONG"][self.depth] = 17
        error = self.cli(*args, "--confirm", p["confirm_token"], status=6)["error"]
        self.assertEqual(error["details"]["conflict"], "state_drift")
        self.assertEqual(self.world.ops().count("family.set"), calls)

    def test_missing_instance_geometry_cannot_register_after_lost_reply(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        self.world.drop = "family.set"
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        self.world.models.pop("short.prt")
        error = self.fresh("operation", "query", "--id", ident, "--model", "block", status=1)[
            "error"
        ]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Absent instance geometry cannot prove the original family intent",
            "--dry-run",
            status=1,
        )
        self.assertEqual(self.world.ops().count("family.set"), 1)

    def test_unexpected_disk_change_is_partial_persistence(self):
        original = self.world.op

        def write_file(op, request):
            result = original(op, request)
            if op == "family.set":
                p = self.ws / "block.prt.1"
                p.write_bytes(p.read_bytes() + b" unexpected file effect")
            return result

        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        with patch.object(self.world, "op", side_effect=write_file):
            error = self.cli(*args, "--confirm", p["confirm_token"], status=1)["error"]
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "partial")

    def test_remove_final_receipt_failure_and_independent_resolution(self):
        self.create()
        self.save_close_instances()
        args = (
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "SHORT",
            "--dangerous",
        )
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        db = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        with closing(sqlite3.connect(db)) as con, con:
            con.execute(
                "CREATE TRIGGER fail_remove_receipt BEFORE UPDATE OF body ON operations "
                f"WHEN NEW.id='{ident}' AND json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'test remove receipt'); END"
            )
        try:
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        finally:
            with closing(sqlite3.connect(db)) as con, con:
                con.execute("DROP TRIGGER fail_remove_receipt")
        status = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(status["receipt"]["outcome"]["execution"], "unknown")
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(
            query["observation"]["family_table_verification"]["can_register"], ["applied"]
        )
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "The exact row is absent while complete generic other rows windows and saved "
            "versions remain unchanged",
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("family.remove"), 1)


for _name in list(vars(test_features.Built)):
    if _name.startswith("test_"):
        setattr(FamilyRuntime, _name, None)
