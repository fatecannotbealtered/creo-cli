"""Public CLI reproductions for operation-scoped balloons and replace failure state."""

import copy
import io
import json
import os
from contextlib import redirect_stdout
from unittest.mock import patch

from creo_cli.main import main
from tests import test_capabilities as caps
from tests import test_family as families
from tests.fixture_features import Refusal


def invoke(case, *words):
    output = io.StringIO()
    with patch.dict(os.environ, case.env, clear=True), redirect_stdout(output):
        code = main([str(w) for w in words])
    return code, json.loads(output.getvalue())


class BalloonScope(caps.AssemblyDrawing):
    test_a_parts_list_its_balloons_and_its_place = None
    test_a_part_drawing_has_no_parts_list = None

    def args(self):
        table = self.gated("drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35)["data"][
            "result"
        ]["table"]
        return (
            "drawing",
            "bom",
            "balloons",
            "--model",
            "rig",
            "--table",
            table["id"],
            "--view",
            "FRONT",
        )

    def test_old_complete_coverage_cannot_certify_new_unreferenced_note(self):
        args = self.args()
        self.gated(*args)
        model = self.world.models["rig.drw"]

        def wrong(q):
            model["notes"].append(
                {
                    "id": 998,
                    "text": "WRONG",
                    "displayed_text": "WRONG",
                    "leaders": [],
                    "leaders_complete": False,
                    "at": [30, 30],
                }
            )
            model["modified"] = True
            return self.world.drawing_summary("rig.drw", model) | {"balloons": {"made": 1}}

        with patch.object(self.world, "drawing_add_balloons", side_effect=wrong):
            code, pre = invoke(self, *args, "--dry-run")
            if code == 0:
                code, out = invoke(self, *args, "--confirm", pre["data"]["confirm_token"])
                self.assertNotEqual(code, 0, "old coverage falsely certified an unrelated new note")
                self.assertNotEqual(
                    out["error"]["details"]["receipt"]["outcome"]["change"], "not_applied"
                )
            else:
                self.assertEqual(pre["error"]["code"], "E_CONFLICT")
                self.assertEqual(len(model["notes"]), 2)

    def test_existing_other_view_numeric_leader_is_preserved_and_ignored(self):
        args = self.args()
        note = {
            "id": 999,
            "text": "99",
            "displayed_text": "99",
            "at": [380, 60],
            "leaders_complete": True,
            "leaders": [
                {
                    "root": "rig.asm",
                    "model": "block.prt",
                    "component_path": [40],
                    "view": "OTHER",
                    "item_id": 12,
                    "item_type": "edge",
                }
            ],
        }
        self.world.models["rig.drw"]["notes"].append(copy.deepcopy(note))
        result = self.gated(*args)["data"]
        self.assertEqual(result["receipt"]["outcome"]["execution"], "completed")
        self.assertEqual(
            next(n for n in self.world.models["rig.drw"]["notes"] if n["id"] == 999), note
        )

    def test_other_view_bom_conversion_is_rejected_before_dispatch(self):
        args = list(self.args())
        self.gated(*args)
        before = copy.deepcopy(self.world.models["rig.drw"]["notes"])
        other = copy.deepcopy(self.world.models["rig.drw"]["views"][0])
        other.update(
            id=max(int(v["id"]) for v in self.world.models["rig.drw"]["views"]) + 1,
            name="OTHER",
            outline=[[260, 180], [310, 220]],
        )
        self.world.models["rig.drw"]["views"].append(other)
        args[-1] = "OTHER"
        error = self.cli(*args, "--dry-run", status=2)["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertEqual(self.world.models["rig.drw"]["notes"], before)
        self.assertEqual(self.world.ops().count("drawing.add-balloons"), 1)

    def test_every_added_note_requires_complete_correct_references(self):
        args = self.args()
        original = self.world.drawing_add_balloons
        base = copy.deepcopy(self.world.models["rig.drw"])
        for defect in ("no_leader", "incomplete", "item", "model", "occurrence", "view"):
            with self.subTest(defect=defect):
                self.world.models["rig.drw"] = copy.deepcopy(base)

                def wrong(q, defect=defect):
                    result = original(q)
                    note = self.world.models["rig.drw"]["notes"][-1]
                    if defect == "no_leader":
                        note["leaders"] = []
                    elif defect == "incomplete":
                        note["leaders_complete"] = False
                    elif defect == "item":
                        note["displayed_text"] = "99"
                    elif defect == "model":
                        note["leaders"][0]["model"] = "wrong.prt"
                    elif defect == "occurrence":
                        note["leaders"][0]["component_path"] = [999]
                    else:
                        note["leaders"][0]["view"] = "OTHER"
                    return result

                with patch.object(self.world, "drawing_add_balloons", side_effect=wrong):
                    pre = self.cli(*args, "--dry-run")["data"]
                    code, result = invoke(self, *args, "--confirm", pre["confirm_token"])
                self.assertNotEqual(code, 0)
                self.cli("model", "save", "--model", "rig.drw", "--dry-run", status=6)
                ident = pre["preview"]["operation_id"]
                self.cli(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "partial",
                    "--evidence",
                    "fixture readback: changed native notes have invalid association; no replay",
                )

    def test_complete_new_coverage_does_not_excuse_an_extra_bad_note(self):
        args = self.args()
        original = self.world.drawing_add_balloons

        def extra_bad(q):
            result = original(q)
            self.world.models["rig.drw"]["notes"].append(
                {
                    "id": 996,
                    "text": "BAD",
                    "displayed_text": "BAD",
                    "at": [20, 20],
                    "leaders": [],
                    "leaders_complete": False,
                }
            )
            return result

        with patch.object(self.world, "drawing_add_balloons", side_effect=extra_bad):
            pre = self.cli(*args, "--dry-run")["data"]
            code, result = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertNotEqual(
            result["error"]["details"]["receipt"]["outcome"]["change"], "not_applied"
        )
        self.cli("model", "save", "--model", "rig.drw", "--dry-run", status=6)


class ReplacementFailure(families.Families):
    def test_accelerator_origin_is_a_file_and_is_bound(self):
        component = families.ReplacingAComponent.rig(self)
        file = self.ws / "block_wide.xpr"
        file.write_bytes(b"owned family accelerator")
        self.world.models["block_wide.prt"]["origin"] = str(file)
        args = (
            "assembly",
            "component",
            "replace",
            "--model",
            "rig",
            "--component",
            component,
            "--with",
            "block_wide",
        )
        pre = self.cli(*args, "--dry-run")["data"]
        file.write_bytes(b"external accelerator change")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("assembly.replace", self.world.ops())

    def test_same_ids_and_models_do_not_hide_partial_failure(self):
        component = families.ReplacingAComponent.rig(self)
        args = (
            "assembly",
            "component",
            "replace",
            "--model",
            "rig",
            "--component",
            component,
            "--with",
            "block_wide",
        )
        initial = copy.deepcopy(self.world.models["rig.asm"])
        for defect in ("position", "constraint", "status", "incomplete"):
            with self.subTest(defect=defect):
                self.world.models["rig.asm"] = copy.deepcopy(initial)

                def failure(q, defect=defect):
                    model = self.world.models["rig.asm"]
                    row = model["components"][0]
                    if defect == "position":
                        row["position"]["origin"][0] = 17
                    elif defect == "constraint":
                        row["constraints"][0]["offset"] = 17
                    elif defect == "status":
                        row["status"] = "FEAT_FAILED"
                    else:
                        row.pop("position")
                    model["modified"] = True
                    raise Refusal("E_CREO", "injected replace failed after placement change")

                with patch.object(self.world, "assembly_replace", side_effect=failure):
                    pre = self.cli(*args, "--dry-run")["data"]
                    code, result = invoke(self, *args, "--confirm", pre["confirm_token"])
                self.assertNotEqual(code, 0)
                self.assertIn(result["error"]["code"], ("E_PARTIAL", "E_OUTCOME_UNKNOWN"))
                status = self.cli("operation", "show", "--id", pre["preview"]["operation_id"])[
                    "data"
                ]["operation_status"]
                self.assertIn(status["status"], ("partial", "unknown"))
                self.assertNotEqual(status["receipt"]["outcome"]["change"], "not_applied")
                self.cli("model", "save", "--model", "rig.asm", "--dry-run", status=6)
                self.cli(
                    "operation",
                    "resolve",
                    "--id",
                    pre["preview"]["operation_id"],
                    "--outcome",
                    "partial",
                    "--evidence",
                    "fixture readback: same IDs/models but changed or incomplete placement; "
                    "no replay",
                )


class ProjectionGeometry(caps.DrawnBlock):
    def test_six_entities_do_not_prove_two_complete_circles(self):
        original = self.world.drawing_add_table

        def incomplete(q):
            result = original(q)
            self.world.models["block.drw"]["draft_arcs"][0]["end_angle"] = 1.0
            return result

        with patch.object(self.world, "drawing_add_table", side_effect=incomplete):
            result = self.gated("drawing", "title-block", "apply", "--model", "block", status=1)
        self.assertEqual(self.world.models["block.drw"]["entities"], 6)
        checks = result["error"]["details"]["failed_checks"]
        self.assertIn("two_complete_projection_circles", [c["check"] for c in checks])
        self.cli("model", "save", "--model", "block.drw", "--dry-run", status=6)
