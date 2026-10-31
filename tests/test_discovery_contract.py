"""Public discovery replies against the independent pinned-schema validator.

These are CLI/loopback observations, not evidence of native engineering coverage.
"""

from pathlib import Path
from unittest.mock import patch

from tests.test_commands import Base
from tests.test_driver_public_schemas import validate


class DiscoveryContract(Base):
    def test_all_single_command_views_validate_independently_without_service_calls(self):
        commands = self.cli("reference", "--index")["data"]["commands"]
        for row in commands:
            with self.subTest(command=row["path"]):
                result = self.cli("reference", "--command", row["path"])["data"]
                validate("urn:tool-driver-cli-spec:reference-command:2.0", result)
                self.assertEqual(result["command"]["path"], row["path"])
        self.assertFalse(self.world.ops())

    def test_default_boolean_enum_units_and_record_control_meaning(self):
        feature = self.cli("reference", "--command", "feature list")["data"]["command"]
        internal = next(p for p in feature["params"] if p["name"] == "include-internal")
        self.assertIs(internal["default"], False)
        view = self.cli("reference", "--command", "drawing view add")["data"]["command"]
        kind = next(p for p in view["params"] if p["name"] == "type")
        self.assertEqual(kind["enum"], ["general", "projection", "detail"])
        self.assertIn(
            "sheet_length_unit", next(p for p in view["params"] if p["name"] == "x")["unit"]
        )
        record = self.cli("reference", "--command", "operation resolve")["data"]["command"]
        self.assertEqual((record["type"], record["driver"]["effects"]), ("read", ["observe"]))

    def test_installation_mismatch_keeps_disk_and_reported_runtime_distinct(self):
        observed = {
            "files_verified": True,
            "loaded_verified": False,
            "component_files": {"creo-cli-service.jar": {"sha256": "b" * 64}},
            "observed_runtime": {"source_sha256": "a" * 64, "service_instance_id": "old-instance"},
            "next_action": "load the intended owned component after preserving the session",
        }
        words = (
            "--installation",
            str(self.ws / "components"),
            "--creo",
            str(self.ws),
            "--java-home",
            str(self.ws),
        )
        with patch("creo_cli.deployment.inspect", return_value=observed):
            context = self.cli("context", *words)["data"]
            checks = self.cli("doctor", *words)["data"]["checks"]
        validate("urn:tool-driver-cli-spec:context:2.0", context)
        self.assertEqual(context["environment"]["connection"]["status"], "unavailable")
        components = context["environment"]["components"]
        self.assertTrue(
            any(c["location"] == "disk" and c["build_id"] == "b" * 64 for c in components)
        )
        self.assertTrue(
            any(c["location"] == "running" and c["build_id"] == "a" * 64 for c in components)
        )
        self.assertEqual(
            next(c for c in checks if c["check"] == "native_backend")["status"], "fail"
        )

    def test_invalid_discovery_parameters_do_not_contact_service(self):
        for words in (
            ("reference", "--index", "--command", "model show"),
            ("context", "--creo", str(self.ws)),
            ("doctor", "--java-home", str(self.ws)),
            ("reference", "--unknown-option"),
        ):
            with self.subTest(words=words):
                self.cli(*words, status=2)
        self.assertFalse(self.world.ops())

    def test_full_reference_matches_fixed_public_schema(self):
        result = self.cli("reference")["data"]
        validate("urn:tool-driver-cli-spec:reference:2.0", result)
        self.assertEqual(len(result["commands"]), 129)
        self.assertEqual(result["runtime_migration"]["write_paths_total"], 79)

    def test_single_command_and_index_use_pinned_views_without_public_schema_bodies(self):
        index = self.cli("reference", "--index")["data"]
        validate("urn:tool-driver-cli-spec:reference-index:2.0", index)
        one = self.cli("reference", "--command", "feature hole")["data"]
        validate("urn:tool-driver-cli-spec:reference-command:2.0", one)
        self.assertEqual(one["command"]["path"], "feature hole")
        self.assertEqual(len(one["schemas"]), 1)
        self.assertFalse(
            any(k.startswith("urn:tool-driver-cli-spec:") for k in one["json_schemas"])
        )
        self.assertFalse(self.world.ops())

    def test_offline_context_is_schema_valid_and_does_not_create_records_or_call_CAD(self):
        state = Path(self.env["CREO_CLI_CONFIG_DIR"])
        self.assertFalse(state.exists())
        self.server.close()
        result = self.cli("context")["data"]
        validate("urn:tool-driver-cli-spec:context:2.0", result)
        self.assertEqual(result["environment"]["connection"]["status"], "unknown")
        self.assertIsNone(result["environment"]["connection"]["instance_id"])
        self.assertFalse(state.exists())
        self.assertFalse(self.world.ops())

    def test_doctor_checks_have_fixed_semantics_and_required_diagnostics(self):
        result = self.cli("doctor")["data"]
        validate("urn:tool-driver-cli-spec:doctor:2.0", result)
        checks = {row["check"]: row for row in result["checks"]}
        self.assertTrue(
            {"release_readiness", "authorization", "native_backend", "state_store"} <= checks.keys()
        )
        self.assertTrue(
            all(row["fix"] is None for row in checks.values() if row["status"] == "pass")
        )

    def test_scalar_and_global_duplicates_are_usage_errors_before_service_access(self):
        for arguments in (
            ("context", "--timeout", "1", "--timeout", "2"),
            ("--timeout", "1", "context", "--timeout=2"),
            ("model", "show", "--model", "one", "--model", "two"),
            ("reference", "--compact", "--compact"),
        ):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments, status=2)
                self.assertEqual(result["error"]["code"], "E_USAGE")
        self.assertFalse(self.world.ops())

    def test_doctor_does_not_hide_failed_session_reader_after_successful_handshake(self):
        from creo_cli.core import Error

        with patch(
            "creo_cli.transport.Client.op",
            side_effect=Error("E_VERIFY_INCOMPLETE", "fixture reader unavailable"),
        ):
            result = self.cli("doctor")["data"]
        checks = {row["check"]: row for row in result["checks"]}
        self.assertEqual(checks["native_backend"]["status"], "fail")
        self.assertIsNotNone(checks["native_backend"]["fix"])
