"""Pending recovery inspections preserve receipts and never bypass authorization.

Faults come from the loopback HTTP service. A pending read is never retried.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations, safety
from tests.test_commands import Base

PENDING = {"code": "E_BUSY", "message": "controlled inspection still running", "started": True}


class NativeReadRecoveryCompatibility(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def operation(self, ident):
        return self.cli("operation", "show", "--id", ident)["data"]["operation_status"]

    def record(self, ident):
        with patch.dict(os.environ, self.env, clear=True):
            return operations.get(ident)

    def query_files(self):
        folder = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operation-queries"
        return {path.name: path.read_bytes() for path in folder.glob("*.json")}

    def lost_write(self, *, common_name=False):
        if common_name:
            args = ("model", "set-common-name", "--model", "block", "--name", "INSPECTED")
            native = "model.set-common-name"
        else:
            args = ("model", "save", "--model", "block")
            native = "model.save"
        preview = self.cli(*args, "--dry-run")["data"]
        self.world.drop = native
        error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        self.world.drop = None
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        ident = preview["preview"]["operation_id"]
        saved = self.operation(ident)
        self.assertEqual(saved["receipt"]["outcome"]["execution"], "unknown")
        return ident, self.record(ident)

    def resolve_args(self, ident):
        return (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent bounded model, saved files and protected state inspected",
        )

    def assert_failed_observation(self, before, error, ident, read):
        after = self.query_files()
        # Retain a failed-read observation separately from the original write;
        # it is not completed inspection or registration evidence.
        filename = error["details"]["read_failure_evidence_id"] + ".json"
        self.assertEqual(set(after) - set(before), {filename})
        self.assertTrue(all(after.get(name) == raw for name, raw in before.items()))
        with patch.dict(os.environ, self.env, clear=True):
            failed = operations.load_query(error["details"]["read_failure_evidence_id"])
        self.assertEqual(failed["operation_id"], ident)
        self.assertFalse(failed["proves_original_write_postconditions"])
        observation = failed["observation"]
        self.assertIs(observation["complete"], False)
        self.assertEqual(observation["read_status"], "pending")
        context = observation["native_read_error"]
        self.assertEqual(context, error["details"]["native_read_error"])
        self.assertEqual(context["code"], "E_NATIVE_READ_PENDING")
        self.assertFalse(context["retryable"])
        self.assertEqual(context["details"]["operation"], read)
        self.assertEqual(context["details"]["dispatch_state"], "started")
        self.assertEqual(context["details"]["cause_code"], "E_BUSY")
        self.assertTrue(context["details"]["cli_invocation_id"])
        self.assertEqual(error["details"]["parent_operation_id"], ident)
        for value in (error["details"], context["details"]):
            for key in ("operation_id", "receipt", "diagnostic_request_id"):
                self.assertNotIn(key, value)

    def test_query_pending_keeps_original_receipt_and_saves_no_evidence(self):
        ident, original = self.lost_write()
        before_queries = self.query_files()
        before_records = self.receipts()
        self.world.events.clear()
        self.world.fail = ("model.show", PENDING)

        error = self.cli("operation", "query", "--id", ident, "--model", "block", status=8)["error"]

        self.assertEqual(error["code"], "E_NATIVE_READ_PENDING")
        self.assertFalse(error["retryable"])
        self.assertEqual(self.world.ops(), ["model.show"])
        self.assertNotIn("operation_id", error["details"])
        self.assertNotIn("receipt", error["details"])
        self.assert_failed_observation(before_queries, error, ident, "model.show")
        self.assertEqual(self.receipts(), before_records)
        self.assertEqual(self.record(ident), original)

    def test_resolve_pending_inspection_does_not_consume_token_or_register(self):
        ident, original = self.lost_write(common_name=True)
        args = self.resolve_args(ident)
        preview = self.cli(*args, "--dry-run")["data"]
        before_queries = self.query_files()
        self.world.events.clear()
        self.world.fail = ("model.management-state", PENDING)

        with patch.object(safety, "consume", wraps=safety.consume) as consume:
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=8)["error"]

        self.assertEqual(error["code"], "E_NATIVE_READ_PENDING")
        self.assertFalse(error["retryable"])
        self.assertEqual(self.world.ops(), ["model.management-state"])
        consume.assert_not_called()
        self.assert_failed_observation(before_queries, error, ident, "model.management-state")
        self.assertEqual(self.record(ident), original)
        self.assertIsNone(self.operation(ident)["resolution"])

    def test_revoked_scope_stops_query_and_resolve_before_native_inspection(self):
        ident, original = self.lost_write(common_name=True)
        scope_file = Path(self.env["CREO_CLI_SCOPE_FILE"])
        scope_file.write_text(
            json.dumps(json.loads(scope_file.read_text(encoding="utf-8")) | {"revoked": True}),
            encoding="utf-8",
        )
        self.world.events.clear()
        self.world.fail = ("model.management-state", PENDING)
        before_queries = self.query_files()

        for args in (
            ("operation", "query", "--id", ident, "--model", "block"),
            (*self.resolve_args(ident), "--dry-run"),
        ):
            with self.subTest(command=args[1]):
                error = self.cli(*args, status=4)["error"]
                self.assertEqual(error["code"], "E_FORBIDDEN")
                self.assertEqual(self.world.ops(), [])

        self.assertEqual(self.query_files(), before_queries)
        self.assertEqual(self.record(ident), original)

    def test_repeated_resolved_confirmation_stops_before_native_inspection(self):
        ident, original = self.lost_write(common_name=True)
        args = self.resolve_args(ident)
        preview = self.cli(*args, "--dry-run")["data"]
        resolved = self.cli(*args, "--confirm", preview["confirm_token"])["data"][
            "operation_status"
        ]
        self.assertEqual(resolved["receipt"], original["driver_receipt"])
        self.assertEqual(resolved["resolution"]["outcome"], "applied")
        before_record = self.record(ident)
        before_queries = self.query_files()
        self.world.events.clear()
        self.world.fail = ("model.management-state", PENDING)

        error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]

        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertEqual(self.world.ops(), [])
        self.assertEqual(self.query_files(), before_queries)
        self.assertEqual(self.record(ident), before_record)
