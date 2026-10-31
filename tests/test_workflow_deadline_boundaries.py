"""Public parent/child records survive three distinct invocation deadline boundaries."""

import json
import subprocess
import sys
import time
from unittest.mock import patch

from creo_cli import engine, operations
from creo_cli.transport import Client
from tests.test_commands import ROOT
from tests.test_features import Built


class WorkflowDeadlineBoundaries(Built):
    def exercise(self, phase):
        model = self.block()
        target_dimension = next(d for d in model["dimensions"] if d["name"].startswith("d"))
        first = {"id": "save", "command": "model save", "args": {"model": "block.prt"}}
        native_write = "model.save"
        if phase == "during_verification":
            first = {
                "id": "tolerance",
                "command": "dimension set-tolerance",
                "args": {
                    "model": "block.prt",
                    "dimension": target_dimension["name"],
                    "symmetric": 0.29,
                    "units": "mm",
                },
            }
            native_write = "dimension.tolerance"
        args = (
            "workflow",
            "run",
            "--request",
            self.request(
                {
                    "steps": [
                        first,
                        {
                            "id": "regen",
                            "command": "model regenerate",
                            "args": {"model": "block.prt"},
                        },
                    ]
                }
            ),
        )
        preview = self.cli(*args, "--dry-run")["data"]
        expired = False
        execute, finish, update, remaining = (
            engine.execute,
            engine.finish,
            operations.update,
            Client.remaining,
        )

        def start(command, client, plan, *a, **kw):
            nonlocal expired
            if command == "model save" and phase == "before_dispatch":
                expired = True
            return execute(command, client, plan, *a, **kw)

        def verify(run, *a, **kw):
            nonlocal expired
            if run["command"] == first["command"] and phase == "during_verification":
                expired = True
            return finish(run, *a, **kw)

        def record(run):
            nonlocal expired
            result = update(run)
            if (
                phase == "after_receipt"
                and run["command"] == "model save"
                and run.get("driver_receipt")
                and run["status"] == "completed"
            ):
                expired = True
            return result

        def budget(client):
            if expired:
                client.deadline = min(client.deadline, time.monotonic() - 1)
            return remaining(client)

        self.world.events.clear()
        with (
            patch.object(engine, "execute", side_effect=start),
            patch.object(engine, "finish", side_effect=verify),
            patch.object(operations, "update", side_effect=record),
            patch.object(Client, "remaining", budget),
        ):
            result = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertTrue(expired)
        self.assertNotIn("model.regenerate", self.world.ops())
        self.assertEqual(
            self.world.ops().count(native_write), 0 if phase == "before_dispatch" else 1
        )
        parent_id = preview["preview"]["operation_id"]

        def fresh(ident):
            process = subprocess.run(
                [sys.executable, "-m", "creo_cli", "operation", "show", "--id", ident],
                cwd=ROOT,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            return json.loads(process.stdout)["data"]["operation_status"]

        parent = fresh(parent_id)
        rows = parent["extensions"]["creo"]["workflow"]["steps"]
        child = fresh(rows[0]["operation_id"])
        self.assertEqual(rows[1]["status"], "skipped")
        self.assertIsNone(rows[1]["operation_id"])
        self.assertEqual(rows[0]["receipt"], child["receipt"])
        count = len(self.world.ops())
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(len(self.world.ops()), count)
        if phase == "before_dispatch":
            self.assertEqual(parent["receipt"]["outcome"]["change"], "not_applied")
            self.assertEqual(child["receipt"]["outcome"]["change"], "not_applied")
            self.assertTrue(model["modified"])
        else:
            self.assertEqual(parent["receipt"]["outcome"]["persistence"], "unknown")
            self.assertEqual(model["modified"], phase == "during_verification")
            self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)
        if phase == "during_verification":
            self.assertEqual(target_dimension["tolerance"]["value"], 0.29)
            self.assertNotEqual(child["status"], "succeeded")
            self.assertEqual(child["receipt"]["outcome"]["verification"]["status"], "incomplete")
            missing = child["receipt"]["outcome"]["verification"]["not_checked"]
            required = next(
                item for item in missing if item["id"] == "postconditions_read_back_independently"
            )
            self.assertTrue(required["required"])
            self.assertNotIn("outside", required["reason"])
        if phase == "after_receipt":
            self.assertEqual(child["status"], "succeeded")
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(child["receipt"]["outcome"]["persistence"], "saved")
            self.assertIn("save", result["error"]["details"]["completed_steps"])
        return parent

    def test_deadline_expires_before_child_dispatch(self):
        self.exercise("before_dispatch")

    def test_deadline_expires_during_post_write_verification(self):
        self.exercise("during_verification")

    def test_completed_child_is_not_relabelled_failed_when_parent_budget_expires(self):
        self.exercise("after_receipt")
