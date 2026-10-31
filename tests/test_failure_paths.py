"""Failure paths an agent relies on beyond the write lifecycle in test_commands.py: reads that
meet a busy, silent or refusing service; writes whose own read-back fails; an unverified write
blocking the next; an uncertain receipt left running; interrupts and unexpected errors."""

from __future__ import annotations

import copy
from unittest.mock import patch

from creo_cli import operations
from tests.test_commands import RECT, Base, domain_receipt

# This fixture declares failure before toolkit dispatch, matching the service's
# pump-unavailable response. Missing `started` would leave dispatch uncertain.
GONE = {"code": "E_UNAVAILABLE", "message": "Creo's thread did not answer", "started": False}


class ReadFailures(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def show(self, status):
        return self.cli("model", "show", "--model", "block", status=status)["error"]

    def test_withdrawn_read_is_retryable_but_started_read_stays_pending(self):
        self.world.busy = "model.show"
        error = self.show(8)
        self.assertEqual(
            (error["code"], error["retryable"], error["details"]["started"]),
            ("E_TIMEOUT", True, False),
        )
        self.world.busy = None
        self.world.overrun = "model.show"
        error = self.show(8)
        self.assertEqual(
            (error["code"], error["retryable"], error["details"]["started"]),
            ("E_NATIVE_READ_PENDING", False, True),
        )
        self.assertEqual(error["details"]["dispatch_state"], "started")
        self.assertTrue(error["details"]["native_call_pending"])
        self.assertFalse(error["details"]["automatic_retry"])
        self.assertEqual(self.receipts(), [])

    def test_a_lost_reply_to_a_read_is_nonretryable_with_unknown_dispatch(self):
        self.world.drop = "model.show"
        self.world.events.clear()
        error = self.show(8)
        self.assertEqual((error["code"], error["retryable"]), ("E_NATIVE_READ_PENDING", False))
        self.assertEqual(error["details"]["cause_code"], "E_NETWORK")
        self.assertEqual(error["details"]["dispatch_state"], "unknown")
        self.assertNotIn("started", error["details"])
        self.assertEqual(self.world.ops(), ["model.show"])

    def test_what_the_service_reports_on_a_read(self):
        for code, expected, status in (
            ("E_CREO", "E_NATIVE_FAILURE", 1),
            ("E_UNAVAILABLE", "E_BACKEND_UNAVAILABLE", 4),
            ("E_AUTH", "E_AUTH", 4),
            ("E_NOT_FOUND", "E_NOT_FOUND", 3),
            ("E_SOMETHING_NEW", "E_NATIVE_READ_PENDING", 8),
        ):
            with self.subTest(code=code):
                details = {"code": code, "message": "said by the service"}
                if code == "E_UNAVAILABLE":
                    details["started"] = False  # Explicit failure before native dispatch.
                self.world.fail = ("model.show", details)
                error = self.show(status)
                self.assertEqual(error["code"], expected)
                self.assertIn("service_message", error["details"]["_untrusted"])
        # A read leaves no receipt, whatever happened to it.
        self.assertEqual(self.receipts(), [])


class ReadBack(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def test_a_feature_whose_read_back_fails_is_incomplete_and_blocks(self):
        self.world.then_fail = ("feature.extrude", "feature.list", GONE)
        request = self.request(RECT)
        error = self.gated(
            "feature", "extrude", "--model", "block", "--request", request, status=1
        )["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        data = domain_receipt(error["details"]["receipt"])
        verification = data["verification"]
        self.assertEqual(verification["level"], "service_reply_only")
        self.assertEqual(verification["status"], "incomplete")
        self.assertEqual(data["result"]["volume"]["after"], 8000)
        self.assertFalse(data["persisted"])
        self.assertIn("feature_in_part", verification["not_checked"])
        self.assertIn(
            {"observation": "independent_read_back_failed", "code": "E_BACKEND_UNAVAILABLE"},
            verification["observations"],
        )
        # The write remains in the fixture; absent independent read-back is not a pass.
        self.assertTrue(self.world.models["block.prt"]["modified"])
        self.assertEqual(self.receipts()[0]["status"], "verification_incomplete")
        self.assertFalse(self.cli("model", "save", "--model", "block", "--dry-run", status=6)["ok"])
        stored = self.cli("operation", "show", "--id", data["operation_id"])["data"]
        self.assertEqual(
            stored["operation_status"]["receipt"]["outcome"]["verification"]["status"], "incomplete"
        )

    def test_an_empty_check_list_does_not_pass_a_write(self):
        (self.ws / "parts").mkdir()
        self.world.then_fail = ("session.cd", "session.status", GONE)
        error = self.gated("session", "cd", "--path", "parts", status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        data = domain_receipt(error["details"]["receipt"])
        self.assertEqual(data["verification"]["level"], "service_reply_only")
        self.assertEqual(data["verification"]["checks"], [])
        self.assertEqual(self.receipts()[0]["status"], "verification_incomplete")
        self.assertEqual(self.world.cwd, self.ws / "parts")
        self.assertFalse(error["retryable"])
        self.assertEqual(error["details"]["dispatch_state"], "dispatched")

    def test_the_read_back_is_the_cli_own(self):
        # A reply that says the working directory moved is not enough: session cd reads it.
        (self.ws / "parts").mkdir()
        dry = self.cli("session", "cd", "--path", "parts", "--dry-run")["data"]
        real = self.world.op

        def moved_nothing(name, q):
            if name == "session.cd":
                return {"working_directory": q["path"]}
            return real(name, q)

        with patch.object(self.world, "op", side_effect=moved_nothing):
            error = self.cli(
                "session", "cd", "--path", "parts", "--confirm", dry["confirm_token"], status=1
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(
            [c["check"] for c in error["details"]["failed_checks"]], ["working_directory_is_target"]
        )
        self.assertIn("failed_checks", error["details"]["_untrusted"])


class DimensionReadBack(Base):
    """Setter claims are deliberately separated from the fixture's reader state; no Creo."""

    def setUp(self):
        super().setUp()
        self.part()
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        self.width = self.cli("dimension", "list", "--model", "block")["data"]["items"][0]

    def change(self, status=0):
        return self.gated(
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            self.width["id"],
            "--value",
            48,
            "--units",
            "mm",
            status=status,
        )

    def checked_value(self, receipt):
        return next(
            c for c in receipt["verification"]["checks"] if c["check"] == "value_as_requested"
        )

    def test_incompatible_health_capability_refuses_before_any_creo_query(self):
        receipts_before = self.receipts()
        for offered in (
            None,
            {},
            {"dimension_regeneration_readback": 0},
            {"dimension_regeneration_readback": 2},
            {"dimension_regeneration_readback": True},
            {"dimension_regeneration_readback": "1"},
        ):
            with self.subTest(offered=offered):
                self.world.capabilities = offered
                events = len(self.world.events)
                error = self.cli(
                    "dimension",
                    "set",
                    "--model",
                    "block",
                    "--dimension",
                    self.width["id"],
                    "--value",
                    48,
                    "--units",
                    "mm",
                    "--dry-run",
                    status=4,
                )["error"]
                self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
                self.assertEqual(error["details"]["dispatch_state"], "not_started")
                self.assertEqual(error["details"]["required_capability"]["version"], 1)
                self.assertFalse(error["details"]["request_sent"])
                self.assertEqual(len(self.world.events), events)
                self.assertEqual(self.world.models["block.prt"]["dimensions"][0]["value"], 40)
                self.assertEqual(self.receipts(), receipts_before)

    def test_service_capability_change_between_preview_and_confirm_refuses_before_dispatch(self):
        args = (
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            self.width["id"],
            "--value",
            48,
            "--units",
            "mm",
        )
        preview = self.cli(*args, "--dry-run")["data"]
        receipts_before = self.receipts()
        self.world.capabilities = {}
        events = len(self.world.events)
        error = self.cli(*args, "--confirm", preview["confirm_token"], status=4)["error"]
        self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(error["details"]["dispatch_state"], "not_started")
        self.assertEqual(len(self.world.events), events)
        self.assertEqual(self.receipts(), receipts_before)
        self.assertEqual(self.world.models["block.prt"]["dimensions"][0]["value"], 40)

    def test_old_health_keeps_independent_dimension_queries_compatible(self):
        self.world.capabilities = None
        data = self.cli("dimension", "list", "--model", "block")["data"]
        self.assertEqual(data["model"], "block.prt")
        self.assertEqual(next(d["value"] for d in data["items"] if d["id"] == self.width["id"]), 40)

    def test_advertised_reader_with_incomplete_preflight_coverage_never_dispatches(self):
        real = self.world.op
        receipts_before = self.receipts()

        def incomplete(op, q):
            data = copy.deepcopy(real(op, q))
            if op == "dimension.list" and q.get("check_regeneration"):
                data["regeneration_check"]["checked_feature_ids"] = []
            return data

        with patch.object(self.world, "op", side_effect=incomplete):
            error = self.cli(
                "dimension",
                "set",
                "--model",
                "block",
                "--dimension",
                self.width["id"],
                "--value",
                48,
                "--units",
                "mm",
                "--dry-run",
                status=4,
            )["error"]
        self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(error["details"]["dispatch_state"], "not_started")
        self.assertTrue(error["details"]["coverage"]["expected"])
        self.assertEqual(error["details"]["coverage"]["observed"], [])
        self.assertFalse(any(op == "dimension.set" for op, _ in self.world.events))
        self.assertEqual(self.receipts(), receipts_before)
        self.assertEqual(self.world.models["block.prt"]["dimensions"][0]["value"], 40)

    def test_success_uses_the_reader_even_when_the_setter_reports_a_wrong_value(self):
        real = self.world.op

        def wrong_reply(op, q):
            data = copy.deepcopy(real(op, q))
            if op == "dimension.set":
                data["dimension"]["value"] = -999
                data["volume"]["after"] = -999
            return data

        with patch.object(self.world, "op", side_effect=wrong_reply):
            receipt = self.change()["data"]
        value = self.checked_value(receipt)
        self.assertEqual((value["expected"], value["observed"], value["unit"]), (48, 48, "mm"))
        self.assertEqual(value["source"]["operation"], "dimension.list")
        self.assertTrue(value["source"]["independent"])
        self.assertEqual(len(value["source"]["sha256"]), 64)
        self.assertEqual(value["tolerance"], {"absolute": 1e-9, "relative": 1e-9})
        self.assertEqual(receipt["result"]["dimension"]["value"], 48)
        self.assertEqual(receipt["result"]["volume"]["after"], 9600)
        self.assertFalse(receipt["persisted"])
        self.assertEqual(receipt["verification"]["status"], "passed")
        self.assertIn("geometry_invariants", receipt["verification"]["not_checked"])

    def test_ignored_setter_is_failed_not_verified_by_its_echo(self):
        real = self.world.op

        def ignored(op, q):
            if op == "dimension.set":
                return {"model": q["model"], "dimension": self.width | {"value": q["value"]}}
            return real(op, q)

        with patch.object(self.world, "op", side_effect=ignored):
            error = self.change(status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        receipt = domain_receipt(error["details"]["receipt"])
        value = self.checked_value(receipt)
        self.assertEqual((value["expected"], value["observed"]), (48, 40))
        self.assertEqual(receipt["result"]["dimension"]["value"], 40)
        self.assertEqual(self.receipts()[0]["status"], "verification_failed")

    def test_adjusted_setter_preserves_actual_adjusted_value_and_geometry(self):
        real = self.world.op

        def adjusted(op, q):
            data = copy.deepcopy(real(op, q | {"value": 47} if op == "dimension.set" else q))
            if op == "dimension.set":
                data["dimension"]["value"] = 48
            return data

        with patch.object(self.world, "op", side_effect=adjusted):
            error = self.change(status=1)["error"]
        receipt = domain_receipt(error["details"]["receipt"])
        self.assertEqual(self.checked_value(receipt)["observed"], 47)
        self.assertEqual(receipt["result"]["volume"]["after"], 9400)
        self.assertFalse(error["details"]["rollback_performed"])

    def test_reader_exception_retains_incomplete_and_does_not_retry_or_save(self):
        self.world.then_fail = ("dimension.set", "dimension.list", GONE)
        error = self.change(status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        receipt = domain_receipt(error["details"]["receipt"])
        self.assertNotIn("dimension", receipt["result"])
        self.assertIn("value_as_requested", receipt["verification"]["not_checked"])
        self.assertTrue(self.world.models["block.prt"]["modified"])
        self.assertEqual(self.world.ops().count("dimension.set"), 1)
        self.assertNotIn("model.save", self.world.ops())
        self.assertFalse(self.cli("model", "save", "--model", "block", "--dry-run", status=6)["ok"])

    def test_unavailable_native_check_preserves_independent_dimension_observation(self):
        real = self.world.op

        def incomplete(op, q):
            data = copy.deepcopy(real(op, q))
            if (
                op == "dimension.list"
                and q.get("check_regeneration")
                and "dimension.set" in self.world.succeeded
            ):
                data["regeneration_check"] |= {
                    "completed": False,
                    "failed_features": None,
                    "error_type": "NativeGetterError",
                }
            return data

        with patch.object(self.world, "op", side_effect=incomplete):
            error = self.change(status=1)["error"]
        receipt = domain_receipt(error["details"]["receipt"])
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.checked_value(receipt)["observed"], 48)
        self.assertIn("native_failed_features_checked", receipt["verification"]["not_checked"])
        self.assertEqual(self.receipts()[0]["status"], "verification_incomplete")

    def test_known_native_failed_feature_is_a_failed_check(self):
        real = self.world.op

        def failed(op, q):
            data = copy.deepcopy(real(op, q))
            if (
                op == "dimension.list"
                and q.get("check_regeneration")
                and "dimension.set" in self.world.succeeded
            ):
                data["regeneration_check"]["failed_features"] = [40]
            return data

        with patch.object(self.world, "op", side_effect=failed):
            error = self.change(status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        check = next(
            c
            for c in error["details"]["failed_checks"]
            if c["check"] == "native_failed_features_checked"
        )
        self.assertEqual((check["expected"], check["observed"]), ([], [40]))

    def test_native_scan_error_after_write_is_incomplete_and_keeps_the_applied_change(self):
        self.world.fail_after = (
            "dimension.set",
            {
                "code": "E_VERIFY_INCOMPLETE",
                "message": "native check unavailable",
                "verification": {"status": "incomplete"},
            },
        )
        error = self.change(status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["state_after"], "observed_changed")
        self.assertEqual(error["details"]["receipt_status"], "verification_incomplete")
        self.assertEqual(self.world.models["block.prt"]["dimensions"][0]["value"], 48)

    def test_malformed_or_missing_reader_evidence_never_passes(self):
        # Each scenario gets a separate ledger; an unresolved receipt is never cleared.
        scenarios = [
            "missing_check",
            "missing_dimension",
            "invalid_number",
            "wrong_model",
            "incomplete_coverage",
            "missing_source",
            "missing_units",
        ]
        real = self.world.op
        for scenario in scenarios:
            with self.subTest(scenario=scenario):

                def malformed(op, q, scenario=scenario):
                    data = copy.deepcopy(real(op, q))
                    if (
                        op == "dimension.list"
                        and q.get("check_regeneration")
                        and "dimension.set" in self.world.succeeded
                    ):
                        if scenario == "missing_check":
                            data.pop("regeneration_check")
                        elif scenario == "missing_dimension":
                            data["dimensions"] = []
                        elif scenario == "invalid_number":
                            data["dimensions"][0]["value"] = None
                        elif scenario == "wrong_model":
                            data["model"] = "other.prt"
                        elif scenario == "incomplete_coverage":
                            data["regeneration_check"]["checked_feature_ids"] = []
                        elif scenario == "missing_source":
                            data["regeneration_check"].pop("source")
                        elif scenario == "missing_units":
                            data["dimensions"][0].pop("units")
                    return data

                # Test the verifier with a fresh operation and isolated state directory each time.
                env = dict(self.env, CREO_CLI_CONFIG_DIR=str(self.root / ("state_" + scenario)))
                self.world.models["block.prt"]["dimensions"][0]["value"] = 40
                self.world.succeeded.discard("dimension.set")
                with patch.object(self.world, "op", side_effect=malformed):
                    error = self.gated(
                        "dimension",
                        "set",
                        "--model",
                        "block",
                        "--dimension",
                        self.width["id"],
                        "--value",
                        48,
                        "--units",
                        "mm",
                        status=1,
                        env=env,
                    )["error"]
                self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
                self.assertEqual(
                    domain_receipt(error["details"]["receipt"])["verification"]["status"],
                    "incomplete",
                )

    def test_an_older_service_without_check_metadata_is_refused_before_dispatch(self):
        real = self.world.op

        def old_service(op, q):
            data = copy.deepcopy(real(op, q))
            if op == "dimension.list":
                data.pop("regeneration_check", None)
            return data

        with patch.object(self.world, "op", side_effect=old_service):
            error = self.cli(
                "dimension",
                "set",
                "--model",
                "block",
                "--dimension",
                self.width["id"],
                "--value",
                48,
                "--units",
                "mm",
                "--dry-run",
                status=4,
            )["error"]
        self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(error["details"]["dispatch_state"], "not_started")
        self.assertNotIn("dimension.set", self.world.ops())
        self.assertEqual(self.world.models["block.prt"]["dimensions"][0]["value"], 40)

    def test_native_check_error_with_unobservable_target_remains_unknown(self):
        self.world.fail_after = (
            "dimension.set",
            {"code": "E_VERIFY_INCOMPLETE", "message": "scan failed"},
        )
        real = self.world.op

        def written_then_unobservable(op, q):
            data = real(op, q)
            if op == "dimension.set":
                self.world.fail = ("dimension.list", GONE)
            return data

        with patch.object(self.world, "op", side_effect=written_then_unobservable):
            error = self.change(status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(error["details"]["receipt_status"], "unknown")
        self.assertEqual(error["details"]["verification"]["status"], "incomplete")
        self.assertEqual(error["details"]["state_after"], "not_observable")
        self.assertFalse(error["retryable"])

    def test_observed_unit_mismatch_is_failed_and_keeps_the_unit(self):
        real = self.world.op

        def mismatch(op, q):
            data = copy.deepcopy(real(op, q))
            if (
                op == "dimension.list"
                and q.get("check_regeneration")
                and "dimension.set" in self.world.succeeded
            ):
                data["dimensions"][0]["units"] = "in"
            return data

        with patch.object(self.world, "op", side_effect=mismatch):
            error = self.change(status=1)["error"]
        check = next(
            c
            for c in error["details"]["failed_checks"]
            if c["check"] == "dimension_units_unchanged"
        )
        self.assertEqual((check["expected"], check["observed"]), ("mm", "in"))

    def test_small_native_adjustment_within_declared_tolerance_keeps_observed_value(self):
        real = self.world.op

        def near(op, q):
            return real(op, q | {"value": 48 + 1e-10} if op == "dimension.set" else q)

        with patch.object(self.world, "op", side_effect=near):
            receipt = self.change()["data"]
        value = self.checked_value(receipt)
        self.assertTrue(value["passed"])
        self.assertNotEqual(value["observed"], value["expected"])
        self.assertEqual(receipt["result"]["dimension"]["value"], value["observed"])


class Blocking(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def test_an_unverified_write_blocks_the_next_until_acknowledged(self):
        self.world.wrong_type = True
        failed = self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), status=1
        )["error"]
        self.assertEqual(failed["details"]["receipt_status"], "verification_failed")
        self.world.wrong_type = False
        blocked = self.cli("model", "save", "--model", "block", "--dry-run", status=6)["error"]
        self.assertEqual(blocked["details"]["operation_ids"], [failed["details"]["operation_id"]])
        # Untargeted status names the unresolved record; the target preview proves conflict.
        problems = self.cli("session", "status")["data"]["problems"]
        self.assertEqual([p["code"] for p in problems], ["unresolved_write"])
        self.assertIn(failed["details"]["operation_id"], problems[0]["message"])
        self.gated(
            "operation",
            "resolve",
            "--id",
            failed["details"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "Inspected the feature tree in Creo: the cut is there and correct",
        )
        self.assertTrue(self.cli("model", "save", "--model", "block", "--dry-run")["ok"])

    def test_a_receipt_left_running_blocks_and_can_be_acknowledged(self):
        # A process killed between sending a write and settling it leaves `running`.
        with patch.dict("os.environ", self.env, clear=True):
            run = operations.begin("feature extrude", "block.prt", {}, "http://127.0.0.1:1")
        listed = self.cli("operation", "list", "--status", "running")["data"]["items"]
        self.assertEqual([r["operation_id"] for r in listed], [run["operation_id"]])
        blocked = self.cli("model", "save", "--model", "block", "--dry-run", status=6)["error"]
        self.assertEqual(blocked["details"]["operation_ids"], [run["operation_id"]])
        self.gated(
            "operation",
            "resolve",
            "--id",
            run["operation_id"],
            "--decision",
            "manual-accept",
            "--note",
            "Inspected Creo after the crash: no half-built feature",
        )
        self.assertTrue(self.cli("model", "save", "--model", "block", "--dry-run")["ok"])


class Interruptions(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def test_an_interrupt_is_reported_and_says_state_is_unknown(self):
        with patch("creo_cli.commands.model.engine.read", side_effect=KeyboardInterrupt):
            error = self.cli("model", "show", "--model", "block", status=130)["error"]
        self.assertEqual((error["code"], error["retryable"]), ("E_INTERRUPTED", True))
        self.assertTrue(error["details"]["state_unknown"])

    def test_an_unexpected_error_hides_its_text(self):
        with patch(
            "creo_cli.commands.model.engine.read", side_effect=RuntimeError("C:\\secret\\path")
        ):
            result = self.cli("model", "show", "--model", "block", status=1)
        error = result["error"]
        self.assertEqual(error["code"], "E_UNKNOWN")
        self.assertEqual(error["details"]["exception_type"], "RuntimeError")
        self.assertNotIn("secret", str(result))
