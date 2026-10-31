"""Public project schemas distinguish known starts, unknown reads and blocked attempts."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from creo_cli import registry, transport
from tests.contract_cli import ContractCliMixin
from tests.test_commands import Base
from tests.test_driver_public_schemas import validate
from tests.test_native_read_transport_uncertainty import capture_error, controlled_peer


class NativeReadStatusSchema(ContractCliMixin, Base):
    def recovery(self):
        data = self.cli("reference")["data"]
        validate("urn:tool-driver-cli-spec:reference:2.0", data)
        recovery = data["extensions"]["creo"]["native_read_recovery"]
        error = data["error_codes"][recovery["error_code"]]
        self.assertEqual((error["exit"], error["retryable"]), (8, False))
        self.assertEqual(error["description"], recovery["description"])
        self.assertEqual(recovery, registry.NATIVE_READ_RECOVERY)
        self.assertEqual(recovery["guard_scope"], "one_client_object")
        self.assertFalse(recovery["persistent_guard"])
        self.assertFalse(recovery["requires_operation_id"])
        self.assertFalse(recovery["creates_write_receipt"])
        self.assertIn("omitted", recovery["request_correlation"]["diagnostic_request_id"])
        for name in ("details_schema", "error_schema"):
            Draft202012Validator.check_schema(recovery[name])
        return recovery

    def test_full_reference_publishes_project_schema_without_CAD_or_write_records(self):
        self.recovery()
        self.assertEqual(self.world.ops(), [])
        self.assertEqual(self.receipts(), [])
        index = self.cli("reference", "--index")["data"]
        one = self.cli("reference", "--command", "model show")["data"]
        validate("urn:tool-driver-cli-spec:reference-index:2.0", index)
        validate("urn:tool-driver-cli-spec:reference-command:2.0", one)
        self.assertNotIn("extensions", index)
        self.assertNotIn("extensions", one)

    def test_actual_errors_and_guard_preserve_the_published_state_variants(self):
        recovery = self.recovery()
        details = Draft202012Validator(recovery["details_schema"])
        errors = Draft202012Validator(recovery["error_schema"])
        for fault, state in (
            ("busy_started", "started"),
            ("unavailable_started", "started"),
            ("reply_lost", "unknown"),
            ("invalid_json", "unknown"),
            ("unavailable_unknown", "unknown"),
        ):
            with self.subTest(fault=fault), controlled_peer(fault), transport.Client() as client:
                original = capture_error(lambda: client.op("model.show")).payload()
                details.validate(original["details"])
                errors.validate(original)
                self.assertEqual(original["details"]["dispatch_state"], state)
                self.assertNotIn("operation_id", original["details"])
                self.assertNotIn("receipt", original["details"])
                self.assertTrue(client.health()["ok"])
                blocked = capture_error(lambda: client.op("model.save", write=True)).payload()
                details.validate(blocked["details"])
                errors.validate(blocked)
                self.assertFalse(blocked["details"]["request_sent"])
                self.assertTrue(blocked["details"]["pending_original_request_sent"])
                self.assertEqual(blocked["details"]["operation"], "model.show")
                for name in ("cause_code", "cause", "cli_invocation_id", "diagnostic_request_id"):
                    self.assertEqual(blocked["details"].get(name), original["details"].get(name))

    def test_public_CLI_pending_errors_validate_without_fabricated_write_receipts(self):
        recovery = self.recovery()
        validator = Draft202012Validator(recovery["error_schema"])
        self.part()
        for fault, state in (("overrun", "started"), ("drop", "unknown")):
            with self.subTest(fault=fault):
                self.world.overrun = self.world.drop = None
                setattr(self.world, fault, "model.show")
                self.world.events.clear()
                result = self.cli("model", "show", "--model", "block", status=8)
                validator.validate(result["error"])
                self.assertEqual(result["error"]["details"]["dispatch_state"], state)
                self.assertFalse(result["error"]["retryable"])
                self.assertFalse(result["error"]["details"]["automatic_retry"])
                self.assertTrue(result["error"]["details"]["read_only"])
                self.assertNotIn("operation_id", result["error"]["details"])
                self.assertNotIn("receipt", result["error"]["details"])
                self.assertEqual(self.world.ops(), ["model.show"])
                self.assertEqual(self.receipts(), [])
                for path, wrong in (
                    (("unexpected",), 1),
                    (("elapsed_seconds",), -1),
                    (("stages", "state_read", "unexpected"), 1),
                    (("rpc", 0, "write"), "false"),
                ):
                    changed = deepcopy(result["error"])
                    cursor = changed["details"]["timing"]
                    for part in path[:-1]:
                        cursor = cursor[part]
                    cursor[path[-1]] = wrong
                    self.assertFalse(validator.is_valid(changed), changed)
                print(f"pending-read {fault}: schema/dispatch/no-retry/no-write-receipt checked")

    def test_older_service_without_diagnostic_id_validates_without_inventing_one(self):
        validator = Draft202012Validator(self.recovery()["error_schema"])
        for fault in ("busy_started", "invalid_envelope"):
            with (
                self.subTest(fault=fault),
                controlled_peer(fault, diagnostic=False),
                transport.Client() as client,
            ):
                original = capture_error(lambda: client.op("model.show")).payload()
                blocked = capture_error(lambda: client.op("feature.list")).payload()
                for error in (original, blocked):
                    validator.validate(error)
                    self.assertNotIn("diagnostic_request_id", error["details"])
                    self.assertEqual(error["details"]["cli_invocation_id"], transport.INVOCATION_ID)

    def test_schema_rejects_false_start_retry_and_fabricated_write_or_guard_evidence(self):
        recovery = self.recovery()
        validator = Draft202012Validator(recovery["error_schema"])
        with controlled_peer("invalid_json"), transport.Client() as client:
            unknown = capture_error(lambda: client.op("model.show")).payload()
            blocked = capture_error(lambda: client.op("feature.list")).payload()
        with controlled_peer("busy_started"), transport.Client() as client:
            started = capture_error(lambda: client.op("model.show")).payload()

        invalid = []
        for extra in (
            {"started": True},
            {"started": False},
            {"native_call_pending": True},
            {"operation_id": "invented-write"},
            {"receipt": {}},
            {"automatic_retry": True},
            {"cli_invocation_id": "invalid"},
            {"request_sent": False},
            {"dispatch_state": "not_started"},
        ):
            candidate = deepcopy(unknown)
            candidate["details"].update(extra)
            invalid.append(candidate)
        retry = deepcopy(unknown)
        retry["retryable"] = True
        invalid.append(retry)
        for field in ("cause_code", "native_call_may_be_pending", "cli_invocation_id"):
            candidate = deepcopy(unknown)
            del candidate["details"][field]
            invalid.append(candidate)
        for field in ("started", "native_call_pending"):
            candidate = deepcopy(started)
            del candidate["details"][field]
            invalid.append(candidate)
        for field in ("pending_original_request_sent", "blocked_request_dispatch_state"):
            candidate = deepcopy(blocked)
            del candidate["details"][field]
            invalid.append(candidate)
        sent_guard = deepcopy(blocked)
        sent_guard["details"]["request_sent"] = True
        invalid.append(sent_guard)
        for index, candidate in enumerate(invalid):
            with self.subTest(invalid=index):
                self.assertFalse(validator.is_valid(candidate), candidate)
