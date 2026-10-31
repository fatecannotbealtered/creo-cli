"""Round-six review reproduction through direct CLI and bounded workflows."""

import copy
import json
from unittest.mock import patch

from tests.test_capabilities import DrawnBlock
from tests.test_commands import Base


class WorkflowInputBoundary(DrawnBlock):
    def file_task(self, path):
        return self.request(
            {
                "steps": [
                    {
                        "id": "relation",
                        "command": "relation set",
                        "args": {"model": "block.prt", "request": str(path)},
                    },
                    {"id": "save", "command": "model save", "args": {"model": "block.prt"}},
                ]
            },
            "task.json",
        )

    def test_unchanged_request_succeeds_and_identity_is_bound(self):
        path = self.request({"relations": ["d1 = 41"]}, "relations.json")
        out = self.gated("workflow", "run", "--request", self.file_task(path))["data"]
        self.assertEqual(out["workflow"]["summary"]["completed"], 2)
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")

    def test_changed_replaced_deleted_request_before_confirm_zero_writes(self):
        path = self.request({"relations": ["d1 = 41"]}, "relations.json")
        for mode in ("content", "replace", "delete"):
            with self.subTest(mode=mode):
                path.write_text(json.dumps({"relations": ["d1 = 41"]}), encoding="utf-8")
                args = ("workflow", "run", "--request", self.file_task(path))
                pre = self.cli(*args, "--dry-run")["data"]
                old = path.read_bytes()
                if mode == "content":
                    path.write_text(json.dumps({"relations": ["d1 = 42"]}), encoding="utf-8")
                elif mode == "replace":
                    replacement = path.with_suffix(".new")
                    replacement.write_bytes(old)
                    replacement.replace(path)
                else:
                    path.unlink()
                self.cli(*args, "--confirm", pre["confirm_token"], status=6)
                self.assertNotIn("relation.set", self.world.ops())
                self.assertNotIn("model.save", self.world.ops())

    def test_layout_and_table_request_files_are_frozen(self):
        specs = [
            (
                "drawing layout apply",
                {"sheet": 1, "views": [{"view": "FRONT", "at": [120, 190]}]},
            ),
            (
                "drawing table add",
                {
                    "units": "mm",
                    "at": [25, 56],
                    "columns": [50, 50],
                    "rows": [8, 8],
                    "cells": [["FIRST", "REFERENCE"], ["UNIT", "mm"]],
                },
            ),
        ]
        for command, body in specs:
            with self.subTest(command=command):
                path = self.request(body, "leaf.json")
                task = self.request(
                    {
                        "steps": [
                            {
                                "id": "leaf",
                                "command": command,
                                "args": {"model": "block.drw", "request": str(path)},
                            }
                        ]
                    },
                    "task.json",
                )
                args = ("workflow", "run", "--request", task)
                pre = self.cli(*args, "--dry-run")["data"]
                path.write_bytes(path.read_bytes() + b" ")
                self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("drawing.apply-layout", self.world.ops())
        self.assertNotIn("drawing.add-table", self.world.ops())

    def test_request_changed_between_authorized_steps_refuses_later_native_write(self):
        relation = self.request({"relations": ["d1 = 41"]}, "relations.json")
        task = self.request(
            {
                "steps": [
                    {
                        "id": "first",
                        "command": "parameter set",
                        "args": {
                            "model": "block.prt",
                            "name": "DESCRIPTION",
                            "type": "string",
                            "value": "authorized",
                        },
                    },
                    {
                        "id": "relation",
                        "command": "relation set",
                        "args": {"model": "block.prt", "request": str(relation)},
                    },
                    {"id": "save", "command": "model save", "args": {"model": "block.prt"}},
                ]
            },
            "task.json",
        )
        args = ("workflow", "run", "--request", task)
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def change_file(op, q):
            result = original(op, q)
            if op == "parameter.set":
                relation.write_text(json.dumps({"relations": ["d1 = 42"]}), encoding="utf-8")
            return result

        with patch.object(self.world, "op", side_effect=change_file):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("relation.set", self.world.ops())
        self.assertEqual(error["details"]["workflow"]["steps"][0]["status"], "completed")
        self.assertEqual(error["details"]["workflow"]["steps"][-1]["status"], "skipped")


class PersistenceBoundary(Base):
    def test_same_value_independently_clean_is_not_invented_as_dirty(self):
        self.world.part("block.prt")
        self.world.write_version(self.ws, "block.prt", self.world.models["block.prt"])
        task = self.request(
            {
                "steps": [
                    {
                        "command": "parameter set",
                        "args": {
                            "model": "block.prt",
                            "name": "DESCRIPTION",
                            "type": "string",
                            "value": "",
                        },
                    }
                ]
            }
        )
        original = self.world.op

        def clean(op, q):
            out = original(op, q)
            if op == "parameter.set":
                self.world.models["block.prt"]["modified"] = False
            return out

        with patch.object(self.world, "op", side_effect=clean):
            out = self.gated("workflow", "run", "--request", task)["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unchanged")

    def test_preexisting_dirty_same_value_is_still_unsaved(self):
        self.world.part("block.prt", modified=True)
        task = self.request(
            {
                "steps": [
                    {
                        "command": "parameter set",
                        "args": {
                            "model": "block.prt",
                            "name": "DESCRIPTION",
                            "type": "string",
                            "value": "",
                        },
                    }
                ]
            }
        )
        out = self.gated("workflow", "run", "--request", task)["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unsaved")

    def test_same_value_dirty_model_reports_unsaved_not_unchanged(self):
        self.world.part("block.prt")
        self.world.write_version(self.ws, "block.prt", self.world.models["block.prt"])
        task = self.request(
            {
                "steps": [
                    {
                        "id": "same",
                        "command": "parameter set",
                        "args": {
                            "model": "block.prt",
                            "name": "DESCRIPTION",
                            "type": "string",
                            "value": "",
                        },
                    }
                ]
            }
        )
        out = self.gated("workflow", "run", "--request", task)["data"]
        child = out["workflow"]["steps"][0]["receipt"]["outcome"]
        self.assertEqual(child["change"], "not_applied")
        self.assertEqual(child["persistence"], "unsaved")
        self.assertTrue(self.world.models["block.prt"]["modified"])
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unsaved")


class TableBoundary(DrawnBlock):
    def test_full_extent_edges_legal_and_illegal_moves(self):
        table = self.table()
        sheet = self.shown()["sheets"][0]
        w, h = sheet["width"], sheet["height"]
        for x, y in ((0, 16), (w - 100, 16), (0, h), (w - 100, h), (25, 58)):
            with self.subTest(legal=[x, y]):
                self.gated(
                    "drawing",
                    "table",
                    "move",
                    "--model",
                    "block.drw",
                    "--table",
                    table["id"],
                    "--x",
                    x,
                    "--y",
                    y,
                )
        before = copy.deepcopy(self.world.models["block.drw"])
        count = self.world.ops().count("drawing.move-table")
        for x, y in ((-0.01, 58), (0, 15.99), (w - 99.99, 58), (0, h + 0.01)):
            with self.subTest(illegal=[x, y]):
                error = self.cli(
                    "drawing",
                    "table",
                    "move",
                    "--model",
                    "block.drw",
                    "--table",
                    table["id"],
                    "--x",
                    x,
                    "--y",
                    y,
                    "--dry-run",
                    status=2,
                )["error"]
                self.assertIn("outline_after", error["details"])
        self.assertEqual(self.world.models["block.drw"], before)
        self.assertEqual(self.world.ops().count("drawing.move-table"), count)

    def test_missing_bounds_and_segment_scope_refuse(self):
        table = self.table()
        row = self.world.models["block.drw"]["tables"][0]
        for field, value in (
            ("outline", None),
            ("segments", 2),
            ("sheet", 2),
            ("bounds_source", None),
        ):
            with self.subTest(field=field):
                old = row[field]
                row[field] = value
                self.cli(
                    "drawing",
                    "table",
                    "move",
                    "--model",
                    "block.drw",
                    "--table",
                    table["id"],
                    "--x",
                    25,
                    "--y",
                    58,
                    "--dry-run",
                    status=1,
                )
                row[field] = old
        self.assertNotIn("drawing.move-table", self.world.ops())

    def test_workflow_invalid_table_extent_refuses_before_all_steps(self):
        table = self.table()
        w = self.shown()["sheets"][0]["width"]
        count = self.world.ops().count("parameter.set")
        task = self.request(
            {
                "steps": [
                    {
                        "command": "parameter set",
                        "args": {
                            "model": "block.prt",
                            "name": "DESCRIPTION",
                            "type": "string",
                            "value": "should not run",
                        },
                    },
                    {
                        "command": "drawing table move",
                        "args": {
                            "model": "block.drw",
                            "table": str(table["id"]),
                            "x": w - 1,
                            "y": 58,
                        },
                    },
                ]
            }
        )
        self.cli("workflow", "run", "--request", task, "--dry-run", status=2)
        self.assertEqual(self.world.ops().count("parameter.set"), count)

    def table(self):
        req = self.request(
            {
                "units": "mm",
                "at": [25, 56],
                "columns": [50, 50],
                "rows": [8, 8],
                "cells": [["WORKFLOW", "REFERENCE ONLY"], ["UNITS", "mm"]],
            }
        )
        return self.gated("drawing", "table", "add", "--model", "block.drw", "--request", req)[
            "data"
        ]["result"]["table"]

    def test_anchor_inside_sheet_but_full_table_outside_refused(self):
        table = self.table()
        drawing = self.world.models["block.drw"]
        before = copy.deepcopy(drawing)
        width = self.shown()["sheets"][0]["width"]
        error = self.cli(
            "drawing",
            "table",
            "move",
            "--model",
            "block.drw",
            "--table",
            table["id"],
            "--x",
            width - 1,
            "--y",
            58,
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_VALIDATION")
        self.assertEqual(drawing, before)
        self.assertNotIn("drawing.move-table", self.world.ops())

    def test_multiple_sheets_not_validated_as_first_sheet(self):
        table = self.table()
        original = self.world.op

        def multi(op, q):
            data = original(op, q)
            if op == "model.show" and q.get("model") == "block.drw":
                data = copy.deepcopy(data)
                data["sheets"].append(data["sheets"][0] | {"number": 2, "width": 50, "height": 50})
            return data

        with patch.object(self.world, "op", side_effect=multi):
            self.cli(
                "drawing",
                "table",
                "move",
                "--model",
                "block.drw",
                "--table",
                table["id"],
                "--x",
                25,
                "--y",
                58,
                "--dry-run",
                status=2,
            )
