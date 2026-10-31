"""Synthetic lifecycle routing, not native constraint or engineering qualification."""

import os
from copy import deepcopy
from unittest.mock import Mock, patch

from creo_cli import assembly_constraints, driver, engine, operations
from creo_cli.core import Error
from tests.test_assembly_constraint_policy import request
from tests.test_commands import Base


class ConstraintRecoveryWiring(Base):
    def unknown(self):
        self.gated("assembly", "create", "--name", "rotation_jig", "--units", "mmns")
        self.world.capabilities[assembly_constraints.CAPABILITY] = 2
        self.dispatch = Mock(
            side_effect=Error(
                "E_OUTCOME_UNKNOWN",
                "synthetic post-dispatch response loss",
                {"request_sent": True, "automatic_retry": False},
            )
        )
        plan = engine.Plan(
            op="assembly.redefine-constraints",
            target="rotation_jig.asm",
            request={"model": "rotation_jig.asm", "component": "83"},
            binding={"constraints_before": {"fixture": "before"}},
            preview={"command": assembly_constraints.COMMAND, "effect": "synthetic routing"},
            verify=lambda c, d: (d, {}),
            observe=lambda c: {"fixture": "after"},
            before={"fixture": "before"},
            apply=self.dispatch,
        )
        self.words = (
            "assembly",
            "component",
            "redefine",
            "--model",
            "rotation_jig.asm",
            "--component",
            "83",
            "--request",
            self.request(request()),
        )
        with patch.object(assembly_constraints, "_plan", return_value=plan):
            preview = self.cli(*self.words, "--dry-run")["data"]
            error = self.cli(*self.words, "--confirm", preview["confirm_token"], status=6)["error"]
        self.ident = preview["preview"]["operation_id"]
        self.original = deepcopy(error["details"]["receipt"])
        self.token = preview["confirm_token"]
        self.proof = {
            "accepted": True,
            "checks": [{"check": "synthetic_current_constraints", "passed": True}],
            "can_register": ["applied"],
            "current": {"fixture": "after"},
            "coverage": "synthetic integration proof only",
        }

    def test_old_service_capability_refuses_before_any_cad_getter(self):
        self.gated("assembly", "create", "--name", "rotation_jig", "--units", "mmns")
        for offered in (None, 1):
            with self.subTest(old_capability_version=offered):
                self.world.capabilities.pop(assembly_constraints.CAPABILITY, None)
                if offered is not None:
                    self.world.capabilities[assembly_constraints.CAPABILITY] = offered
                self.world.events.clear()
                with patch.object(assembly_constraints, "_plan") as plan:
                    error = self.cli(
                        "assembly",
                        "component",
                        "redefine",
                        "--model",
                        "rotation_jig.asm",
                        "--component",
                        "83",
                        "--request",
                        self.request(request()),
                        "--dry-run",
                        status=4,
                    )["error"]
                self.assertEqual(error["code"], "E_BACKEND_UNAVAILABLE")
                self.assertEqual(error["details"]["dispatch_state"], "not_started")
                self.assertEqual(
                    error["details"]["required_capability"],
                    {"name": assembly_constraints.CAPABILITY, "version": 2},
                )
                self.assertFalse(self.world.ops())
                plan.assert_not_called()

    def test_query_uses_specialized_recovery_before_generic_model_getters(self):
        self.unknown()
        self.world.events.clear()
        with patch.object(assembly_constraints, "recovery", return_value=self.proof) as recovery:
            result = self.cli(
                "operation", "query", "--id", self.ident, "--model", "rotation_jig.asm"
            )["data"]
        self.assertEqual(result["observation"]["assembly_constraints_verification"], self.proof)
        self.assertEqual(recovery.call_count, 1)
        self.assertFalse(self.world.ops())
        self.assertEqual(self.dispatch.call_count, 1)

    def test_resolve_requires_specialized_proof_and_preserves_original_receipt(self):
        self.unknown()
        evidence = "Independent synthetic constraints and actual pose routing evidence"
        with (
            patch.object(assembly_constraints, "recovery", return_value=self.proof) as recovery,
            patch.object(assembly_constraints, "retained_evidence_sufficient") as retained,
        ):
            self.gated(
                "operation",
                "resolve",
                "--id",
                self.ident,
                "--outcome",
                "applied",
                "--evidence",
                evidence,
            )
            shown = self.cli("operation", "show", "--id", self.ident)["data"]["operation_status"]
            self.assertEqual(recovery.call_count, 2)
            self.assertGreaterEqual(retained.call_count, 1)
            self.assertEqual(shown["receipt"], self.original)
            self.assertEqual(shown["resolution"]["outcome"], "applied")
            inspection = shown["extensions"]["creo"]["assembly_constraints_inspection"]
            self.assertEqual(inspection["evidence_status"], "verified")
            self.assertTrue(inspection["current_requirements_satisfied"])
            with patch.dict(os.environ, self.env, clear=True):
                run = operations.get(self.ident)
                self.assertTrue(driver.resolution_evidence_trusted(run))
            retained.side_effect = Error("E_VERIFY_INCOMPLETE", "synthetic missing pose")
            shown = self.cli("operation", "show", "--id", self.ident)["data"]["operation_status"]
            inspection = shown["extensions"]["creo"]["assembly_constraints_inspection"]
            self.assertEqual(inspection["evidence_status"], "insufficient")
            with patch.dict(os.environ, self.env, clear=True):
                self.assertFalse(driver.resolution_evidence_trusted(operations.get(self.ident)))
        self.assertEqual(self.dispatch.call_count, 1)

    def test_incomplete_recovery_cannot_be_registered_applied(self):
        self.unknown()
        proof = self.proof | {"accepted": False, "can_register": ["partial"]}
        with patch.object(assembly_constraints, "recovery", return_value=proof):
            error = self.cli(
                "operation",
                "resolve",
                "--id",
                self.ident,
                "--outcome",
                "applied",
                "--evidence",
                "Synthetic independent reading is incomplete",
                "--dry-run",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(self.dispatch.call_count, 1)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertNotIn("driver_resolution", operations.get(self.ident))

    def test_query_pending_preserves_context_and_does_not_fall_through_to_getters(self):
        self.unknown()
        self.world.events.clear()
        pending = Error(
            "E_NATIVE_READ_PENDING",
            "synthetic constraint getter may still be running",
            {
                "operation": "assembly.constraint-state",
                "dispatch_state": "started_unknown",
                "cause": {"code": "E_TIMEOUT", "message": "synthetic lost reply"},
                "cli_invocation_id": "synthetic-query-invocation",
                "automatic_retry": False,
            },
        )
        with patch.object(assembly_constraints, "recovery", side_effect=pending):
            error = self.cli(
                "operation",
                "query",
                "--id",
                self.ident,
                "--model",
                "rotation_jig.asm",
                status=pending.exit,
            )["error"]
        nested = error["details"]["native_read_error"]
        self.assertEqual(nested["details"]["operation"], "assembly.constraint-state")
        self.assertEqual(nested["details"]["cause"]["code"], "E_TIMEOUT")
        self.assertNotIn("diagnostic_request_id", nested["details"])
        self.assertIn("stop further CAD dispatch", error["details"]["next_action"])
        self.assertFalse(self.world.ops())
        self.assertEqual(self.dispatch.call_count, 1)
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(operations.get(self.ident)["driver_receipt"], self.original)
