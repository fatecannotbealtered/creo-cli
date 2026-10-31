"""Construction readback failures remain queryable without inventing an empty session."""

from unittest.mock import patch

from creo_cli import building
from creo_cli.core import Error
from tests.test_commands import RECT, Base


class ConstructionDiagnostics(Base):
    def test_busy_session_is_unknown_and_does_not_suggest_reinstall(self):
        self.world.busy = "session.status"
        status = self.cli("session", "status")["data"]
        self.assertFalse(status["connected"])
        self.assertIsNone(status["model_count"])
        problem = next(p for p in status["problems"] if p["code"] == "service_busy")
        self.assertIn("dialog", problem["fix"])
        self.assertNotIn("register", problem["fix"])

    def test_effect_read_failure_keeps_specific_rpc_and_failed_stage(self):
        self.part()
        original = building.plan

        def fail_after_proof(**kwargs):
            plan = original(**kwargs)
            observe, verify = plan.observe, plan.verify
            done = False

            def checked(c, data):
                nonlocal done
                result = verify(c, data)
                done = True
                return result

            def observed(c):
                if done:
                    raise Error(
                        "E_TIMEOUT",
                        "owned final effect-read timeout",
                        {
                            "operation": "feature.show",
                            "service_code": "E_BUSY",
                            "started": True,
                        },
                    )
                return observe(c)

            plan.verify, plan.observe = checked, observed
            return plan

        with patch.object(building, "plan", side_effect=fail_after_proof):
            error = self.gated(
                "feature", "extrude", "--model", "block", "--request", self.request(RECT), status=6
            )["error"]
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        self.assertEqual(receipt["failed_stage"], "verify")
        detail = receipt["extensions"]["creo"]["effects_readback_error"]
        self.assertEqual(detail["details"]["operation"], "feature.show")
        self.assertTrue(detail["details"]["started"])
