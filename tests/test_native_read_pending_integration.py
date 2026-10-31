"""Pending reads cannot be bypassed by workflow cleanup or erase known write execution.

Failures come from the real loopback HTTP service, not a mocked Client exception.
"""

from unittest.mock import patch

from creo_cli import workflow_tasks
from tests import test_dependency_workflow as workflow_fixture
from tests.test_commands import Base

PENDING = {"code": "E_BUSY", "message": "controlled read still running", "started": True}


class NativeReadPendingIntegration(Base):
    def test_completed_write_keeps_execution_when_verification_read_is_pending(self):
        self.part()
        args = (
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "changed",
        )
        dry = self.cli(*args, "--dry-run")["data"]
        self.world.events.clear()
        self.world.then_fail = ("parameter.set", "parameter.list", PENDING)
        error = self.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        calls = self.world.ops()
        setter = calls.index("parameter.set")
        self.assertEqual(calls[setter:], ["parameter.set", "parameter.list"])
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        before_repeat = list(self.world.events)
        self.cli(*args, "--confirm", dry["confirm_token"], status=6)
        self.assertEqual(self.world.events, before_repeat)

    def test_nested_workflow_pending_read_stops_outer_client_cleanup(self):
        body = workflow_fixture.PublicWorkflow.task(self)
        body["steps"].insert(
            1, {"id": "read", "kind": "read", "command": "model show", "args": {"model": "block"}}
        )
        args = ("workflow", "run", "--request", self.request(body))
        dry = self.cli(*args, "--dry-run")["data"]
        original = workflow_tasks._observe
        pending_index = []

        def observe(step, *rest):
            if step["id"] != "read":
                return original(step, *rest)
            previous = self.world.fail
            self.world.fail = ("model.show", PENDING)
            try:
                return original(step, *rest)
            finally:
                pending_index.append(len(self.world.events) - 1)
                self.world.fail = previous

        self.world.events.clear()
        with patch.object(workflow_tasks, "_observe", side_effect=observe):
            error = self.cli(*args, "--confirm", dry["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(self.world.ops()[pending_index[0] + 1 :], [])
        workflow = error["details"]["workflow"]
        changed, read, saved = workflow["steps"]
        self.assertEqual(
            [r["status"] for r in workflow["steps"]], ["completed", "unknown", "skipped"]
        )
        self.assertIsNotNone(changed["receipt"])
        self.assertEqual(changed["receipt"]["outcome"]["execution"], "completed")
        for row in (read, saved):
            self.assertIsNone(row["operation_id"])
            self.assertIsNone(row["receipt"])
        self.assertEqual(self.world.ops().count("parameter.set"), 1)
        self.assertNotIn("model.save", self.world.ops())
        before_repeat = list(self.world.events)
        self.cli(*args, "--confirm", dry["confirm_token"], status=6)
        self.assertEqual(self.world.events, before_repeat)
