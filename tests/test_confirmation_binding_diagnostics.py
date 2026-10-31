"""All bound fields explain refusal; rejected attempts never rewrite old write state."""

import copy
import json
from unittest.mock import patch

from creo_cli import binding_diagnostics, operations, safety
from creo_cli.core import Error, canonical
from tests.test_commands import Base as PublicBase
from tests.test_safety import Base


class BindingDiagnostics(Base):
    def extended(self):
        return self.bound | {
            "driver_scope_sha256": "scope-a",
            "driver_target": {"model": "block.prt"},
            "driver_effects": ["change"],
            "driver_paths": [["D:/owned/block.prt", "change"]],
            "driver_outputs": [{"path": "D:/owned/block.prt.2", "effect": "persist"}],
            "driver_dependencies": [{"identity": "shared.prt", "revision": "before"}],
            "driver_execution_budget": {"native_seconds": 60},
        }

    def refusal(self, token, actual, expected):
        with self.assertRaises(Error) as caught:
            safety.consume(token, actual, expected_binding=expected)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        return caught.exception

    def test_every_driver_field_has_nonempty_typed_expected_actual_diagnostic(self):
        expected = self.extended()
        token, _ = safety.issue(expected)
        self.assertLessEqual(len(token), 2048)
        for field in expected:
            actual = expected | {field: "changed"}
            with self.subTest(field=field):
                error = self.refusal(token, actual, expected)
                self.assertTrue(error.details["changed"])
                row = next(
                    r for r in error.details["binding_difference"]["fields"] if r["field"] == field
                )
                self.assertTrue(row["category"])
                self.assertNotEqual(row["expected"], row["actual"])
                self.assertTrue(row["changes"])
        safety.consume(token, expected, expected_binding=expected)

    def test_missing_added_and_unrecognized_fields_are_all_still_bound(self):
        expected = self.extended() | {"future_extension": {"mode": "strict"}}
        token, _ = safety.issue(expected)
        for actual in (
            {key: value for key, value in expected.items() if key != "driver_dependencies"},
            expected | {"future_extension": {"mode": "changed"}},
            expected | {"new_extension": [1, 2]},
        ):
            with self.subTest(actual=actual):
                error = self.refusal(token, actual, expected)
                self.assertTrue(error.details["changed"])
                self.assertTrue(error.details["binding_difference"]["fields"])

    def test_nested_object_and_actual_values_are_reported_without_credentials(self):
        expected = self.extended()
        actual = copy.deepcopy(expected)
        actual["driver_dependencies"][0]["identity"] = "other.prt"
        actual["driver_dependencies"][0]["access_token"] = "credential-plain-value"
        actual["driver_dependencies"][0]["note"] = "ct_secret-signed-token.signature"
        token, _ = safety.issue(expected)
        error = self.refusal(token, actual, expected)
        raw = json.dumps(error.details)
        self.assertIn("/driver_dependencies/0/identity", raw)
        self.assertIn("shared.prt", raw)
        self.assertIn("other.prt", raw)
        self.assertNotIn("credential-plain-value", raw)
        self.assertNotIn("ct_secret", raw)
        self.assertNotIn(token, raw)

    def test_untrusted_retained_binding_cannot_supply_expected_values(self):
        expected = self.extended()
        token, _ = safety.issue(expected)
        false_expected = expected | {"driver_target": "invented expected value"}
        error = self.refusal(token, expected | {"driver_target": "actual"}, false_expected)
        raw = json.dumps(error.details)
        self.assertNotIn("invented expected value", raw)
        self.assertIn("digest_prefix", raw)

    def test_old_five_group_token_never_repeats_changed_empty(self):
        expected = self.extended()
        old_parts = {name: safety.parts(expected)[name] for name in safety.PARTS}
        with patch.object(safety, "parts", return_value=old_parts):
            token, _ = safety.issue(expected)
        error = self.refusal(token, expected | {"driver_outputs": []}, expected)
        self.assertIn("driver_outputs", error.details["changed"])

    def test_detail_bound_preserves_every_changed_top_level_category(self):
        expected = {"driver_dependencies": list(range(200)), "new_extension": 1}
        actual = {"driver_dependencies": list(range(1, 201)), "new_extension": 2}
        result = binding_diagnostics.differences(expected, actual, maximum=3)
        self.assertEqual(len(result["fields"]), 2)
        self.assertEqual(len(result["fields"][0]["changes"]), 3)
        self.assertTrue(result["details_truncated"])

    def test_named_parameter_values_are_redacted_before_diff_loses_their_name_context(self):
        old, new = "synthetic-sensitive-old-value", "synthetic-sensitive-new-value"
        arguments = {
            "arguments": {"name": "access_token", "value": old},
            "request": {"name": "access_token", "value": old},
        }
        expected = safety.scope("parameter set", "block.prt", arguments, "same-model")
        actual = copy.deepcopy(expected)
        for section in ("arguments", "request"):
            actual["arguments"][section]["value"] = new
        token, _ = safety.issue(expected)
        error = self.refusal(token, actual, expected)
        raw = json.dumps(error.details)
        self.assertNotIn(old, raw)
        self.assertNotIn(new, raw)
        fields = error.details["binding_difference"]["fields"]
        self.assertEqual(fields[0]["field"], "arguments")
        self.assertEqual(fields[0]["category"], "arguments_or_resolved_request")
        values = [row for row in fields[0]["changes"] if row["path"].endswith("/value")]
        self.assertEqual(len(values), 2)
        for value in values:
            self.assertEqual(value["expected"], "[REDACTED]")
            self.assertEqual(value["actual"], "[REDACTED]")
            self.assertTrue(value["values_redacted"])

    def test_named_property_sanitization_preserves_structure_without_sensitive_values(self):
        value = {
            "nested": [
                {"name": "password", "value": {"text": "synthetic-password"}},
                {
                    "target": "access_token",
                    "before": "synthetic-before",
                    "after": "synthetic-after",
                },
            ]
        }
        sanitized = binding_diagnostics.sanitize(value)
        raw = json.dumps(sanitized)
        for marker in ("synthetic-password", "synthetic-before", "synthetic-after"):
            self.assertNotIn(marker, raw)
        self.assertEqual(sanitized["nested"][0]["value"], "[REDACTED]")
        self.assertEqual(sanitized["nested"][1]["before"], "[REDACTED]")
        self.assertEqual(sanitized["nested"][1]["after"], "[REDACTED]")


class PublicBindingRedaction(PublicBase):
    def test_named_parameter_argument_drift_does_not_leak_public_or_attempt_values(self):
        self.part()
        old, new = "synthetic-sensitive-old-value", "synthetic-sensitive-new-value"
        common = (
            "parameter",
            "set",
            "--model",
            "block.prt",
            "--name",
            "access_token",
            "--type",
            "string",
            "--create",
            "--value",
        )
        preview = self.cli(*common, old, "--dry-run")["data"]
        answer = self.cli(*common, new, "--confirm", preview["confirm_token"], status=6)
        raw = json.dumps(answer)
        self.assertNotIn(old, raw)
        self.assertNotIn(new, raw)
        self.assertNotIn(preview["confirm_token"], raw)
        self.assertEqual(answer["error"]["code"], "E_CONFLICT")
        self.assertTrue(answer["error"]["details"]["changed"])
        self.assertIn("binding_difference", answer["error"]["details"])
        with patch.dict("os.environ", self.env, clear=True):
            attempts = operations.confirmation_attempts(preview["preview"]["operation_id"])
        self.assertEqual(len(attempts), 1)
        self.assertNotIn(old, json.dumps(attempts))
        self.assertNotIn(new, json.dumps(attempts))
        self.assertNotIn("parameter.set", self.world.ops())


class RejectedAttemptHistory(Base):
    def planned(self):
        return operations.record_plan(
            "feature extrude",
            "block.prt",
            {},
            "http://127.0.0.1:1",
            {"operation_id": "a" * 32},
            self.bound,
        )

    def test_refusals_append_terminal_attempts_without_rewriting_plan(self):
        run = self.planned()
        original = canonical(operations.get(run["operation_id"]))
        error = Error(
            "E_CONFLICT",
            "refused ct_sensitive.signature",
            {"reason": "scope_changed", "token": "sensitive"},
        )
        first = operations.record_confirmation_rejection(run, error, self.bound)
        second = operations.record_confirmation_rejection(run, error, self.bound)
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        attempts = operations.confirmation_attempts(run["operation_id"])
        self.assertEqual(len(attempts), 2)
        for attempt in attempts:
            self.assertEqual(attempt["status"], "rejected_before_dispatch")
            self.assertEqual(attempt["dispatch_state"], "not_started")
            self.assertEqual(attempt["original_operation_status"], "planned")
            self.assertFalse(attempt["write_started"])
            self.assertNotIn("ct_sensitive", json.dumps(attempt))
            self.assertNotIn('"sensitive"', json.dumps(attempt))
        self.assertEqual(canonical(operations.get(run["operation_id"])), original)

    def test_current_not_started_does_not_settle_original_unknown(self):
        run = self.planned()
        run["status"] = "unknown"
        operations.update(run)
        error = Error("E_CONFLICT", "already dispatched", {"conflict": "token_used"})
        attempt = operations.record_confirmation_rejection(run, error, self.bound)
        self.assertEqual(attempt["dispatch_state"], "not_started")
        self.assertEqual(attempt["original_operation_status"], "unknown")
        self.assertEqual(operations.get(run["operation_id"])["status"], "unknown")
        with self.assertRaises(Error):
            operations.require_clear()

    def test_old_database_without_attempt_table_reads_empty(self):
        run = self.planned()
        self.assertEqual(operations.confirmation_attempts(run["operation_id"]), [])
