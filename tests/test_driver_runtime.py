"""Command-level scope, preallocation, lost replies and evidence-only recovery tests."""

import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from creo_cli import driver_schema
from tests.test_commands import RECT, Base


class DriverRuntime(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def args(self):
        return ("feature", "extrude", "--model", "block", "--request", self.request(RECT))

    def grant(self, **changes):
        path = Path(self.env["CREO_CLI_SCOPE_FILE"])
        value = json.loads(path.read_text(encoding="utf-8")) | changes
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_preallocation_and_five_dimensions_validate_against_pinned_schemas(self):
        preview = self.cli(*self.args(), "--dry-run")["data"]
        plan = preview["preview"]
        driver_schema.validate("plan", plan)
        shown = self.cli("operation", "show", "--id", plan["operation_id"])["data"][
            "operation_status"
        ]
        driver_schema.validate("operation-status", shown)
        self.assertEqual(shown["status"], "planned")
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))
        result = self.cli(*self.args(), "--confirm", preview["confirm_token"])["data"]
        receipt = result["receipt"]
        driver_schema.validate("receipt", receipt)
        self.assertEqual(receipt["operation_id"], plan["operation_id"])
        self.assertEqual(
            set(receipt["outcome"]),
            {"execution", "change", "persistence", "delivery", "verification"},
        )
        count = sum(op == "feature.extrude" for op, _ in self.world.events)
        again = self.cli(*self.args(), "--confirm", preview["confirm_token"], status=6)["error"]
        self.assertEqual(again["details"]["conflict"], "token_used")
        self.assertEqual(count, sum(op == "feature.extrude" for op, _ in self.world.events))

    def test_absent_scope_is_read_only_even_with_old_write_environment(self):
        Path(self.env["CREO_CLI_SCOPE_FILE"]).unlink()
        preview = self.cli(*self.args(), "--dry-run")["data"]
        self.assertFalse(preview["preview"]["can_apply"])
        self.cli(*self.args(), "--confirm", preview["confirm_token"], status=4)
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))

    def test_revoked_scope_and_scope_drift_refuse_before_dispatch(self):
        preview = self.cli(*self.args(), "--dry-run")["data"]
        self.grant(revoked=True)
        error = self.cli(*self.args(), "--confirm", preview["confirm_token"], status=6)["error"]
        self.assertEqual(error["details"]["conflict"], "scope_changed")
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))

    def test_expired_malformed_scope_and_root_boundaries_cannot_grant(self):
        for change in (
            {"expires_at": "2001-01-01T00:00:00Z"},
            {"roots": [str(self.root / "outside")]},
            {"effects": ["observe"]},
            {"unexpected": True},
        ):
            with self.subTest(change=change):
                path = Path(self.env["CREO_CLI_SCOPE_FILE"])
                original = path.read_bytes()
                self.grant(**change)
                preview = self.cli(*self.args(), "--dry-run")["data"]
                self.assertFalse(preview["preview"]["can_apply"])
                self.cli(*self.args(), "--confirm", preview["confirm_token"], status=4)
                path.write_bytes(original)
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))

    def test_scope_limit_counts_confirmed_operations_not_plans(self):
        self.grant(limits={"max_operations": 1})
        self.cli(*self.args(), "--dry-run")
        self.cli(*self.args(), "--dry-run")
        self.gated(*self.args())
        next_plan = self.cli("model", "save", "--model", "block", "--dry-run")["data"]
        self.assertFalse(next_plan["preview"]["can_apply"])
        error = self.cli(
            "model", "save", "--model", "block", "--confirm", next_plan["confirm_token"], status=4
        )["error"]
        self.assertIn("limit", error["details"]["scope"]["missing"])

    def test_input_drift_does_not_consume_the_planned_operation(self):
        path = self.request(RECT)
        preview = self.cli(
            "feature", "extrude", "--model", "block", "--request", path, "--dry-run"
        )["data"]
        path.write_text(json.dumps(RECT | {"depth": 12}), encoding="utf-8")
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            path,
            "--confirm",
            preview["confirm_token"],
            status=6,
        )["error"]
        self.assertEqual(error["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.receipts()[0]["status"], "planned")

    def test_save_reply_lost_is_unknown_until_independent_inspection_and_resolution(self):
        self.world.drop = "model.save"
        error = self.gated("model", "save", "--model", "block", status=6)["error"]
        op_id = error["details"]["operation_id"]
        original = error["details"]["receipt"]
        self.assertEqual(original["outcome"]["persistence"], "unknown")
        self.assertTrue(list(self.ws.glob("block.prt.*")))
        self.world.drop = None
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        # An evidence-free retry/resolve is refused. Query stores fresh independent getters.
        self.cli(
            "operation", "resolve", "--id", op_id, "--outcome", "applied", "--dry-run", status=2
        )
        query = self.cli("operation", "query", "--id", op_id, "--model", "block")["data"]
        self.gated(
            "operation",
            "resolve",
            "--id",
            op_id,
            "--outcome",
            "applied",
            "--evidence",
            "independent saved file and model query " + query["evidence_id"],
        )
        shown = self.cli("operation", "show", "--id", op_id)["data"]["operation_status"]
        self.assertEqual(shown["receipt"], original)
        self.assertEqual(shown["resolution"]["outcome"], "applied")
        self.cli("model", "save", "--model", "block", "--dry-run")

    def test_scope_revocation_blocks_recovery_without_erasing_original_uncertainty(self):
        self.world.drop = "model.save"
        error = self.gated("model", "save", "--model", "block", status=6)["error"]
        self.world.drop = None
        self.grant(revoked=True)
        self.cli(
            "operation",
            "resolve",
            "--id",
            error["details"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "independent model and disk checked",
            "--dry-run",
            status=4,
        )
        shown = self.cli("operation", "show", "--id", error["details"]["operation_id"])["data"][
            "operation_status"
        ]
        self.assertIsNone(shown["resolution"])
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")

    def test_regeneration_reader_is_independent_and_missing_flags_remain_incomplete(self):
        result = self.gated("model", "regenerate", "--model", "block")["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertTrue(
            any(
                op == "dimension.list" and q.get("check_regeneration")
                for op, q in self.world.events
            )
        )

    def test_direct_resolution_is_only_local_record_control(self):
        self.world.drop = "model.save"
        error = self.gated("model", "save", "--model", "block", status=6)["error"]
        self.world.drop = None
        before = len(self.world.events)
        record = self.cli(
            "operation",
            "resolve",
            "--id",
            error["details"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "independent saved file and getters inspected",
        )["data"]["operation_status"]
        self.assertEqual(len(self.world.events), before)
        self.assertEqual(record["receipt"]["outcome"]["execution"], "unknown")
        self.assertFalse(record["stop_observed"])

    def test_publication_io_failure_keeps_operation_identity_and_unknown_artifact_effect(self):
        self.gated(*self.args())
        args = ("artifact", "export", "--model", "block", "--output", "blocked.stp")
        preview = self.cli(*args, "--dry-run")["data"]
        output = self.ws / "blocked.stp"
        real_link = os.link
        publication = Mock(side_effect=PermissionError("fixture publication blocked"))

        def link(source, target, *args, **kwargs):
            if Path(target) == output:
                return publication(source, target, *args, **kwargs)
            return real_link(source, target, *args, **kwargs)

        self.world.events.clear()
        with patch("creo_cli.commands.model.os.link", side_effect=link):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        publication.assert_called_once()
        self.assertEqual(self.world.ops().count("model.export"), 1)
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(error["details"]["operation_id"], preview["preview"]["operation_id"])
        self.assertEqual(error["details"]["receipt_status"], "unknown")
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["change"], "not_applied")
        self.assertEqual(receipt["extensions"]["creo"]["artifact_state"], "observed_on_disk")
        recovery = receipt["extensions"]["creo"]["export_recovery"]
        self.assertEqual(recovery["state"], "generated_unpublished")
        self.assertTrue(recovery["generated"])
        self.assertFalse(recovery["published"])
        self.assertFalse((self.ws / "blocked.stp").exists())
        self.assertTrue(list((self.ws / ".creo-cli/staging").rglob("*.stp")))
