"""A moved native anchor cannot certify an envelope from before the move."""

import copy
import json
import subprocess
import sys
from unittest.mock import patch

from creo_cli.core import Error
from creo_cli.transport import Client
from tests.test_capabilities import DrawnBlock
from tests.test_commands import ROOT


class DimensionMoveConsistency(DrawnBlock):
    def test_sanitizing_unavailable_box_is_not_itself_an_applied_native_change(self):
        row, args = self.setup_move()
        row["box"] = None
        row["at"] = [40.0, 40.0]
        error = self.gated(*args[:-4], "--x", 40, "--y", 40, status=1)["error"]
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "not_applied")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        self.assertEqual(self.world.ops().count("drawing.move-dimension"), 1)

    def test_workflow_preserves_moved_child_and_skips_save_after_stale_bounds(self):
        row, _ = self.setup_move()
        task = self.request(
            {
                "steps": [
                    {
                        "id": "move",
                        "command": "drawing dimension move",
                        "args": {"model": "block.drw", "dimension": row["name"], "x": 80, "y": 40},
                    },
                    {"id": "save", "command": "model save", "args": {"model": "block.drw"}},
                ]
            }
        )
        original = self.world.op

        def stale(op, request):
            result = original(op, request)
            if op == "drawing.move-dimension":
                row["box"] = [[35, 38], [45, 42]]
            return result

        with patch.object(self.world, "op", side_effect=stale):
            error = self.gated("workflow", "run", "--request", task, status=1)["error"]
        receipt = error["details"]["receipt"]
        steps = receipt["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual(steps[1]["status"], "skipped")
        self.assertEqual(steps[0]["receipt"]["outcome"]["change"], "applied")
        self.assertEqual(receipt["outcome"]["change"], "partial")
        self.assertEqual(receipt["outcome"]["persistence"], "unsaved")
        self.assertNotIn("model.save", self.world.ops())
        self.assertEqual(row["at"], [80, 40])
        self.assertEqual(self.world.ops().count("drawing.move-dimension"), 1)

    def test_preview_identifies_page_title_and_view_conflicts(self):
        row, args = self.setup_move()
        model = self.world.models["block.drw"]
        row["view"] = model["views"][0]["name"]
        model["views"][0].update(sheet=1, outline=[[76, 30], [96, 50]])
        model["tables"] = [{"id": "91", "sheet": 1, "outline": [[75, 38], [100, 44]]}]
        feedback = self.cli(*args, "--dry-run")["data"]["preview"]["extensions"]["creo"][
            "annotation_feedback"
        ]
        self.assertIn(
            "possible_view_boundary_intersection", [c["kind"] for c in feedback["conflicts"]]
        )
        self.assertIn("predicted_table_overlap", [c["kind"] for c in feedback["conflicts"]])
        feedback = self.cli(*args[:-4], "--x", 1, "--y", 40, "--dry-run")["data"]["preview"][
            "extensions"
        ]["creo"]["annotation_feedback"]
        self.assertIn("predicted_text_outside_sheet", [c["kind"] for c in feedback["conflicts"]])
        self.assertNotIn("drawing.move-dimension", self.world.ops())

    def test_verification_deadline_preserves_independent_anchor_in_new_process(self):
        row, args = self.setup_move()
        pre = self.cli(*args, "--dry-run")["data"]
        original = Client.op
        dispatched, reads = False, 0

        def deadline(client, op, q=None, **kwargs):
            nonlocal dispatched, reads
            if dispatched and op == "model.show":
                reads += 1
                if reads >= 2:
                    raise Error(
                        "E_TIMEOUT", "injected verification deadline", {"request_sent": False}
                    )
            result = original(client, op, q, **kwargs)
            if op == "drawing.move-dimension":
                dispatched = True
            return result

        with patch.object(Client, "op", new=deadline):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "applied")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        fresh = subprocess.run(
            [
                sys.executable,
                "-m",
                "creo_cli",
                "operation",
                "show",
                "--id",
                pre["preview"]["operation_id"],
            ],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(fresh.returncode, 0, fresh.stdout)
        self.assertEqual(
            json.loads(fresh.stdout)["data"]["operation_status"]["receipt"]["outcome"],
            receipt["outcome"],
        )
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.move-dimension"), 1)

    def setup_move(self):
        self.gated("drawing", "dimension", "annotate", "--model", "block.drw")
        row = self.world.models["block.drw"]["shown_dims"][0]
        row.update(at=[40, 40], box=[[35, 38], [45, 42]], sheet=1)
        return row, (
            "drawing",
            "dimension",
            "move",
            "--model",
            "block.drw",
            "--dimension",
            row["name"],
            "--x",
            80,
            "--y",
            40,
        )

    def test_stale_reply_and_first_independent_box_are_not_returned_as_current(self):
        row, args = self.setup_move()
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        dispatched = False
        reads = 0

        def lag(op, q):
            nonlocal dispatched, reads
            result = original(op, q)
            if op == "drawing.move-dimension":
                dispatched = True
                row["box"] = [[35, 38], [45, 42]]
                result = copy.deepcopy(result)
                next(d for d in result["dimensions"] if d["name"] == row["name"])["box"] = row[
                    "box"
                ]
            elif dispatched and op == "model.show":
                reads += 1
                if reads >= 2:
                    row["box"] = [[75, 38], [85, 42]]
                    result = original(op, q)
            return result

        with patch.object(self.world, "op", side_effect=lag):
            out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        actual = next(d for d in out["result"]["dimensions"] if d["name"] == row["name"])
        self.assertEqual(actual["at"], [80, 40])
        self.assertEqual(actual["box"], [[75, 38], [85, 42]])
        self.assertGreaterEqual(reads, 2)
        self.assertEqual(self.world.ops().count("drawing.move-dimension"), 1)

    def test_never_updated_box_is_incomplete_and_does_not_replay(self):
        row, args = self.setup_move()
        original = self.world.op

        def stale(op, q):
            result = original(op, q)
            if op == "drawing.move-dimension":
                row["box"] = [[35, 38], [45, 42]]
            return result

        with patch.object(self.world, "op", side_effect=stale):
            error = self.gated(*args, status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "applied")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        result = receipt["extensions"]["creo"]["domain_result"]
        actual = next(d for d in result["dimensions"] if d["name"] == row["name"])
        self.assertIsNone(actual["box"])
        self.assertEqual(actual["at"], [80, 40])
        self.cli("model", "save", "--model", "block.drw", "--dry-run", status=6)
        self.assertEqual(self.world.ops().count("drawing.move-dimension"), 1)
