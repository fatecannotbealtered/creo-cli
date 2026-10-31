"""Unreleased drawing candidate: offline contracts, never live Creo evidence."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from creo_cli import registry  # noqa: F401 -- initialize the command registry before leaf modules
from creo_cli.commands.drawing import _overlapping, _text_boxes
from tests.test_commands import domain_preview
from tests.test_features import Built


class TextBoxes(unittest.TestCase):
    def test_same_coordinates_on_different_sheets_do_not_overlap(self):
        drawing = {
            "views": [{"name": "FRONT", "sheet": 1}, {"name": "TOP", "sheet": 2}],
            "dimensions": [
                {"name": "d1", "view": "FRONT", "box": [[1, 1], [4, 4]]},
                {"name": "d2", "view": "TOP", "box": [[2, 2], [5, 5]]},
            ],
        }
        self.assertEqual(_overlapping(drawing), [])
        drawing["dimensions"][1]["sheet"] = 1
        self.assertEqual(_overlapping(drawing), [["d1", "d2", 2]])

    def test_missing_invalid_and_unknown_sheet_boxes_are_visible_gaps(self):
        drawing = {
            "dimensions": [
                {"name": "missing", "sheet": 1},
                {"name": "wrong", "sheet": 1, "box": [[4, 4], [1, 1]]},
                {"name": "unknown", "box": [[1, 1], [4, 4]]},
            ]
        }
        boxes, missing = _text_boxes(drawing)
        self.assertEqual(boxes, [])
        self.assertEqual(
            [item["reason"] for item in missing],
            ["text_box_unavailable", "text_box_unavailable", "sheet_unavailable"],
        )
        self.assertEqual(_overlapping(drawing), [])


class DrawingCandidate(Built):
    def setUp(self):
        super().setUp()
        self.block()
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")

    def test_title_symbol_preview_and_readback_follow_third_angle(self):
        self.world.models["block.drw"]["projection"] = "third_angle"
        preview = domain_preview(
            self.cli("drawing", "title-block", "apply", "--model", "block", "--dry-run")["data"][
                "preview"
            ]
        )
        self.assertEqual(preview["projection_symbol"]["projection"], "third_angle")
        self.assertEqual(preview["projection_symbol"]["entities"], 6)
        result = self.gated("drawing", "title-block", "apply", "--model", "block")["data"]
        self.checks_pass(result)
        self.assertEqual(result["result"]["projection_symbol"]["projection"], "third_angle")

    def test_annotate_discloses_missing_boxes_without_claiming_full_layout(self):
        original = self.world.op

        def missing_boxes(op, request):
            result = original(op, request)
            for row in result.get("dimensions", []):
                row["box"] = None
            return result

        with patch.object(self.world, "op", side_effect=missing_boxes):
            data = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        observation = next(
            row
            for row in data["verification"]["observations"]
            if row["observation"] == "texts_overlapping"
        )
        self.assertFalse(observation["complete"])
        self.assertTrue(observation["not_checked"])
        self.assertIn("dimension_layout", data["verification"]["not_checked"])
        self.assertFalse(data["persisted"])

    def test_reported_thread_text_must_be_read_back(self):
        real = self.world.op

        def wrong_callout(name, request):
            result = real(name, request)
            if name == "drawing.annotate":
                row = result["dimensions"][0]
                result["annotated"]["threads_called_out"] = [
                    {
                        "model": row["model"],
                        "id": row["id"],
                        "on": row["name"],
                        "prefix": "M",
                        "suffix": "x1.5",
                    }
                ]
            return result

        with patch.object(self.world, "op", side_effect=wrong_callout):
            error = self.gated("drawing", "dimension", "annotate", "--model", "block", status=1)[
                "error"
            ]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertIn(
            "thread_callouts_read_back", [row["check"] for row in error["details"]["failed_checks"]]
        )

    def test_chamfer_c_style_is_sent_and_reported_without_saving(self):
        edge = next(
            row
            for row in self.cli("geometry", "list", "--model", "block", "--kind", "edge")["data"][
                "items"
            ]
            if row.get("type") == "line"
        )
        request = {"units": "mm", "name": "EDGE", "distance": 1, "edges": [edge["ref"]]}
        self.gated("feature", "chamfer", "--model", "block", "--request", self.request(request))
        data = self.gated(
            "drawing", "dimension", "annotate", "--model", "block", "--chamfers", "c"
        )["data"]
        self.assertEqual(
            [row["style"] for row in data["result"]["annotated"]["chamfers_called_out"]], ["cd"]
        )
        self.assertFalse(data["persisted"])
        sent = [
            request for operation, request in self.world.events if operation == "drawing.annotate"
        ][-1]
        self.assertEqual(sent["chamfers"], "c")

    def test_current_candidate_does_not_inherit_historical_live_flags(self):
        data = self.cli("reference")["data"]
        self.assertEqual(data["release_readiness"]["level"], "beta")
        self.assertEqual(data["release_readiness"]["live_smoke_status"], "missing")
        pending = registry.PENDING_LIVE_VERIFICATION
        self.assertTrue(pending)
        for command in registry.COMMANDS:
            if command.path in pending:
                self.assertFalse(command.describe()["live_verified"])

    def _assert_unhonored_chamfer_style_is_not_success(self, returned_style):
        edge = next(
            row
            for row in self.cli("geometry", "list", "--model", "block", "--kind", "edge")["data"][
                "items"
            ]
            if row.get("type") == "line"
        )
        self.gated(
            "feature",
            "chamfer",
            "--model",
            "block",
            "--request",
            self.request({"units": "mm", "name": "EDGE", "distance": 1, "edges": [edge["ref"]]}),
        )
        real = self.world.op

        def old_or_refusing_service(name, request):
            result = real(name, request)
            if name == "drawing.annotate":
                for row in result["annotated"]["chamfers_called_out"]:
                    row.update(style=returned_style, error="style unavailable")
            return result

        with patch.object(self.world, "op", side_effect=old_or_refusing_service):
            error = self.gated(
                "drawing", "dimension", "annotate", "--model", "block", "--chamfers", "c", status=1
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertIn(
            "requested_chamfer_style_reported",
            [row["check"] for row in error["details"]["failed_checks"]],
        )

    def test_old_service_cannot_ignore_explicit_chamfer_c_style(self):
        self._assert_unhonored_chamfer_style_is_not_success("d_x_45")

    def test_refused_chamfer_setter_cannot_report_success(self):
        self._assert_unhonored_chamfer_style_is_not_success(None)

    def test_missing_chamfer_coverage_cannot_report_requested_style(self):
        real = self.world.op

        def unreported(name, request):
            result = real(name, request)
            if name == "drawing.annotate":
                result["annotated"].pop("chamfers_called_out", None)
            return result

        with patch.object(self.world, "op", side_effect=unreported):
            error = self.gated(
                "drawing", "dimension", "annotate", "--model", "block", "--chamfers", "c", status=1
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")

    def test_annotate_will_not_change_dimension_text_in_an_external_part(self):
        self.world.models["block.prt"]["origin"] = str(self.root / "external" / "block.prt.1")
        before = len(self.world.events)
        error = self.cli(
            "drawing", "dimension", "annotate", "--model", "block", "--dry-run", status=4
        )["error"]
        self.assertEqual(error["code"], "E_FORBIDDEN")
        self.assertFalse(any(op == "drawing.annotate" for op, _ in self.world.events[before:]))

    def test_unknown_projection_cannot_pass_symbol_verification(self):
        real = self.world.op
        applied = False

        def missing_projection(name, request):
            nonlocal applied
            result = real(name, request)
            if name == "drawing.add-table":
                applied = True
            if (
                applied
                and name in ("model.show", "drawing.add-table")
                and result.get("type") == "drawing"
            ):
                result["projection"] = None
                if "projection_symbol" in result:
                    result["projection_symbol"]["projection"] = None
            return result

        with patch.object(self.world, "op", side_effect=missing_projection):
            error = self.gated("drawing", "title-block", "apply", "--model", "block", status=1)[
                "error"
            ]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertIn(
            "projection_symbol_drawn", [row["check"] for row in error["details"]["failed_checks"]]
        )

    def test_missing_or_unknown_service_projection_is_refused_before_table_dispatch(self):
        real = self.world.op
        for value in (None, "unknown", "missing-key"):
            with self.subTest(projection=value):

                def old_service(name, request, projection=value):
                    result = real(name, request)
                    if name == "model.show" and result.get("type") == "drawing":
                        if projection == "missing-key":
                            result.pop("projection", None)
                        else:
                            result["projection"] = projection
                    return result

                start = len(self.world.events)
                with patch.object(self.world, "op", side_effect=old_service):
                    error = self.cli(
                        "drawing", "title-block", "apply", "--model", "block", "--dry-run", status=6
                    )["error"]
                self.assertEqual(error["code"], "E_CONFLICT")
                self.assertFalse(error["details"]["automatic_retry"])
                self.assertIn("loaded service", error["details"]["next_action"])
                self.assertFalse(
                    any(
                        operation == "drawing.add-table"
                        for operation, _ in self.world.events[start:]
                    )
                )
