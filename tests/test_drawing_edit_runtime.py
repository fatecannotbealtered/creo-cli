"""Migrated table edit chain: scope, file binding and public workflow records."""

import json
from pathlib import Path

from tests.test_capabilities import DrawnBlock


class DrawingEditRuntime(DrawnBlock):
    def test_dimension_move_preview_reports_known_text_overlap_without_dispatch(self):
        self.gated("drawing", "dimension", "annotate", "--model", "block.drw")
        model = self.world.models["block.drw"]
        a, b = model["shown_dims"][:2]
        for dim, x in ((a, 40), (b, 80)):
            dim.update(at=[x, 40], box=[[x - 5, 38], [x + 5, 42]], view=model["views"][0]["name"])
        pre = self.cli(
            "drawing",
            "dimension",
            "move",
            "--model",
            "block.drw",
            "--dimension",
            a["name"],
            "--x",
            80,
            "--y",
            40,
            "--dry-run",
        )["data"]["preview"]
        feedback = pre["extensions"]["creo"]["annotation_feedback"]
        self.assertTrue(
            any(
                c["kind"] == "predicted_text_overlap" and c["object"] == b["name"]
                for c in feedback["conflicts"]
            )
        )
        self.assertNotIn("drawing.move-dimension", self.world.ops())
        a["box"] = None
        pre = self.cli(
            "drawing",
            "dimension",
            "move",
            "--model",
            "block.drw",
            "--dimension",
            a["name"],
            "--x",
            80,
            "--y",
            40,
            "--dry-run",
        )["data"]["preview"]
        feedback = pre["extensions"]["creo"]["annotation_feedback"]
        self.assertFalse(feedback["available"])
        self.assertNotIn("predicted_text_box", feedback)

    def test_workflow_retains_resource_handler_selector_normalization(self):
        table = self.table()
        note = self.gated(
            "drawing",
            "note",
            "add",
            "--model",
            "block.drw",
            "--text",
            "WORK NOTE",
            "--x",
            25,
            "--y",
            40,
        )["data"]["result"]["note"]
        task = self.request(
            {
                "steps": [
                    {
                        "id": "note",
                        "command": "drawing note remove",
                        "args": {"model": "block.drw", "item": str(note["id"])},
                    },
                    {
                        "id": "table",
                        "command": "drawing table remove",
                        "args": {"model": "block.drw", "item": str(table["id"])},
                    },
                    {"id": "save", "command": "model save", "args": {"model": "block.drw"}},
                ]
            }
        )
        out = self.gated("workflow", "run", "--request", task)["data"]
        self.assertEqual(out["workflow"]["summary"]["completed"], 3)
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")

    def table(self):
        request = self.request(
            {
                "units": "mm",
                "at": [180, 35],
                "columns": [50, 50],
                "rows": [8, 8],
                "cells": [["WORKFLOW", "REFERENCE ONLY"], ["UNITS", "mm"]],
            }
        )
        out = self.gated("drawing", "table", "add", "--model", "block.drw", "--request", request)[
            "data"
        ]
        self.assertIn("outcome", out["receipt"])
        return out["result"]["table"]

    def test_table_move_save_remove_public_chain(self):
        table = self.table()
        task = self.request(
            {
                "steps": [
                    {
                        "id": "move",
                        "command": "drawing table move",
                        "args": {
                            "model": "block.drw",
                            "table": str(table["id"]),
                            "x": 181,
                            "y": 38,
                        },
                    },
                    {"id": "save", "command": "model save", "args": {"model": "block.drw"}},
                ]
            }
        )
        completed = self.gated("workflow", "run", "--request", task)["data"]
        self.assertEqual(completed["receipt"]["outcome"]["persistence"], "saved")
        rows = self.cli("drawing", "table", "list", "--model", "block.drw")["data"]["items"]
        self.assertEqual(next(t for t in rows if t["id"] == table["id"])["at"], [181, 38])
        deleted = self.gated(
            "drawing", "table", "remove", "--model", "block.drw", "--item", table["id"]
        )["data"]
        self.assertEqual(deleted["receipt"]["outcome"]["change"], "applied")
        self.assertFalse(
            any(
                t["id"] == table["id"]
                for t in self.cli("drawing", "table", "list", "--model", "block.drw")["data"][
                    "items"
                ]
            )
        )

    def test_table_confirmation_drift_and_repeat_are_rejected(self):
        table = self.table()
        args = ("drawing", "table", "remove", "--model", "block.drw", "--item", table["id"])
        pre = self.cli(*args, "--dry-run")["data"]
        self.gated(
            "drawing",
            "table",
            "move",
            "--model",
            "block.drw",
            "--table",
            table["id"],
            "--x",
            181,
            "--y",
            38,
        )
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        fresh = self.cli(*args, "--dry-run")["data"]
        self.cli(*args, "--confirm", fresh["confirm_token"])
        self.cli(*args, "--confirm", fresh["confirm_token"], status=6)

    def test_table_scope_denial_no_native_dispatch(self):
        table = self.table()
        path = Path(self.env["CREO_CLI_SCOPE_FILE"])
        grant = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(grant | {"effects": ["observe", "persist"]}), encoding="utf-8")
        args = ("drawing", "table", "remove", "--model", "block.drw", "--item", table["id"])
        pre = self.cli(*args, "--dry-run")["data"]
        self.assertFalse(pre["preview"]["can_apply"])
        self.cli(*args, "--confirm", pre["confirm_token"], status=4)
        self.assertNotIn("drawing.remove", self.world.ops())
