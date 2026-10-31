"""Real HTTP fixture: an extended-field refusal records only this attempt as terminal."""

import json
import os
from copy import deepcopy
from unittest.mock import patch

import pytest

from creo_cli import driver, engine, operations
from creo_cli.core import Error, canonical
from tests.test_commands import RECT, Base


class ConfirmationAttemptCLI(Base):
    def test_driver_path_difference_reports_actual_field_and_terminal_attempt(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        operation_id = preview["preview"]["operation_id"]
        original = driver.affected_paths

        def duplicate_observed_path(client, plan, nodes=None):
            rows = original(client, plan, nodes)
            return rows + rows[:1]

        with patch.object(driver, "affected_paths", side_effect=duplicate_observed_path):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        self.assertIn("driver_paths", error["details"]["changed"])
        self.assertEqual(error["details"]["dispatch_state"], "not_started")
        self.assertNotIn(preview["confirm_token"], json.dumps(error))
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))
        with patch.dict(os.environ, self.env, clear=True):
            attempts = operations.confirmation_attempts(operation_id)
            retained = operations.get(operation_id)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "rejected_before_dispatch")
        self.assertEqual(attempts[0]["dispatch_state"], "not_started")
        self.assertEqual(retained["status"], "planned")
        self.assertIsNone(retained["started_at"])
        self.assertIsNone(retained["driver_receipt"])
        self.assertIn(
            "driver_paths",
            [r["field"] for r in attempts[0]["error"]["details"]["binding_difference"]["fields"]],
        )

    def test_failed_rejection_append_is_not_retried_by_outer_wrapper(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        operation_id = preview["preview"]["operation_id"]
        original = driver.affected_paths

        def duplicate_observed_path(client, plan, nodes=None):
            rows = original(client, plan, nodes)
            return rows + rows[:1]

        with (
            patch.object(driver, "affected_paths", side_effect=duplicate_observed_path),
            patch.object(
                operations,
                "record_confirmation_rejection",
                side_effect=Error("E_IO", "controlled append outcome unavailable"),
            ) as record,
        ):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        record.assert_called_once()
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertIn("driver_paths", error["details"]["changed"])
        self.assertFalse(error["details"]["confirmation_attempt_retained"])
        self.assertEqual(error["details"]["confirmation_attempt_record_error"], "E_IO")
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(operations.get(operation_id)["status"], "planned")
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))

    def test_other_process_start_does_not_hide_this_lock_refusal_or_rewrite_shared_record(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        operation_id = preview["preview"]["operation_id"]
        lock_error = Error("E_CONFLICT", "another invocation holds the write lock")
        other_process_record = []

        def another_process_started(*_args):
            run = operations.get(operation_id)
            run.update(status="running", started_at="2026-10-24T00:00:00Z")
            operations.update(run)
            other_process_record.append(canonical(operations.get(operation_id)))
            assert engine._CONFIRMATION_EXECUTION.get()["entered"] is False
            raise lock_error

        with (
            patch.dict(os.environ, self.env, clear=True),
            patch.object(engine, "_write", side_effect=another_process_started),
            pytest.raises(Error) as caught,
        ):
            engine.write("feature extrude", {"confirm": preview["confirm_token"]}, None, None)
        self.assertIs(caught.value, lock_error)
        self.assertEqual(
            caught.value.details["confirmation_attempt"]["dispatch_state"], "not_started"
        )
        with patch.dict(os.environ, self.env, clear=True):
            attempts = operations.confirmation_attempts(operation_id)
            unchanged = canonical(operations.get(operation_id))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "rejected_before_dispatch")
        self.assertTrue(attempts[0]["terminal"])
        self.assertEqual(unchanged, other_process_record[0])
        self.assertFalse(any(op == "feature.extrude" for op, _ in self.world.events))
        self.assertIsNone(engine._CONFIRMATION_EXECUTION.get())


def test_preflight_pending_read_survives_attempt_append_failure_without_second_history_read():
    retained = {"operation_id": "a" * 32, "status": "planned", "started_at": None}
    pending = Error(
        "E_NATIVE_READ_PENDING",
        "original native getter is still pending",
        {"original_read_id": "getter-17", "automatic_retry": False, "next_action": "stop CAD"},
    )
    with (
        patch.object(engine, "_write", side_effect=pending),
        patch("creo_cli.safety.token_operation", return_value=retained["operation_id"]),
        patch.object(operations, "get", return_value=retained) as get,
        patch.object(
            operations, "record_confirmation_rejection", side_effect=Error("E_IO", "append failed")
        ) as record,
        pytest.raises(Error) as caught,
    ):
        engine.write("feature extrude", {"confirm": "synthetic-confirm"}, None, None)
    assert caught.value is pending
    assert caught.value.code == "E_NATIVE_READ_PENDING"
    assert caught.value.details["original_read_id"] == "getter-17"
    assert caught.value.details["next_action"] == "stop CAD"
    assert caught.value.details["confirmation_attempt_retained"] is False
    assert caught.value.details["confirmation_attempt_record_error"] == "E_IO"
    get.assert_called_once_with(retained["operation_id"])
    record.assert_called_once()
    assert engine._CONFIRMATION_EXECUTION.get() is None


def test_newly_dispatched_failure_cannot_become_a_not_started_attempt():
    retained = {"operation_id": "a" * 32, "status": "planned", "started_at": None}
    pending = Error(
        "E_OUTCOME_UNKNOWN",
        "verification getter is pending",
        {"dispatch_state": "dispatched", "native_read_error": {"code": "E_NATIVE_READ_PENDING"}},
    )

    def entered_then_failed(*_args):
        engine._CONFIRMATION_EXECUTION.get()["entered"] = True
        raise pending

    with (
        patch.object(engine, "_write", side_effect=entered_then_failed),
        patch("creo_cli.safety.token_operation", return_value=retained["operation_id"]),
        patch.object(operations, "get", return_value=deepcopy(retained)) as get,
        patch.object(driver, "record_confirmation_refusal") as record,
        pytest.raises(Error) as caught,
    ):
        engine.write("feature extrude", {"confirm": "synthetic-confirm"}, None, None)
    assert caught.value is pending
    assert caught.value.details["dispatch_state"] == "dispatched"
    assert "confirmation_attempt" not in caught.value.details
    record.assert_not_called()
    get.assert_called_once_with(retained["operation_id"])
    assert engine._CONFIRMATION_EXECUTION.get() is None
