"""BOM geometry, native correspondence and scope refusals through the public CLI."""

import copy
from unittest.mock import patch

from creo_cli import bom
from creo_cli.core import Error
from tests import test_capabilities as capabilities


class BomRuntime(capabilities.AssemblyDrawing):
    # Parent setup builds a synthetic flat assembly; its old contract tests remain
    # in their own module rather than being counted a second time here.
    test_a_parts_list_its_balloons_and_its_place = None
    test_a_part_drawing_has_no_parts_list = None

    def test_anchor_inside_full_table_outside_zero_dispatch(self):
        before = copy.deepcopy(self.world.models["rig.drw"])
        for x, y in ((290, 120), (-1, 120), (10, 10), (10, 298)):
            with self.subTest(x=x, y=y):
                self.cli(
                    "drawing",
                    "bom",
                    "add",
                    "--model",
                    "rig",
                    "--x",
                    x,
                    "--y",
                    y,
                    "--dry-run",
                    status=2,
                )
        self.assertEqual(before, self.world.models["rig.drw"])
        self.assertNotIn("drawing.add-bom", self.world.ops())

    def test_unknown_template_and_template_drift_no_dispatch(self):
        args = ("drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35)
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.bom_template.write_bytes(b"changed template")
        error = self.cli(*args, "--confirm", pre["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.cli(*args, "--dry-run", status=2)
        self.assertNotIn("drawing.add-bom", self.world.ops())

    def test_missing_template_no_dispatch(self):
        self.world.bom_template.unlink()
        error = self.cli(
            "drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35, "--dry-run", status=3
        )["error"]
        self.assertEqual(error["code"], "E_NOT_FOUND")

    def test_partial_readback_rejects_static_table_or_wrong_quantity(self):
        made = self.gated("drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35)["data"]
        table = self.world.models["rig.drw"]["tables"][0]
        args = (
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
        with patch.dict(table, {"cell_references": []}):
            self.cli(*args, "--dry-run", status=1)
        original = table["cells"][2][2]
        table["cells"][2][2] = "99"
        self.cli(*args, "--dry-run", status=1)
        table["cells"][2][2] = original
        views = self.world.models["rig.drw"]["views"]
        same_name = copy.deepcopy(views[0])
        same_name["id"] = max(int(v["id"]) for v in views) + 1
        views.append(same_name)
        self.cli(*args, "--dry-run", status=3)
        views.pop()
        self.assertNotIn("drawing.add-balloons", self.world.ops())
        self.assertEqual(made["receipt"]["outcome"]["change"], "applied")


def test_balloon_wrong_occurrence_is_not_proven_by_text_count():
    rows = [{"item": 1, "model": "p.prt", "quantity": 2, "occurrences": [["40"], ["41"]]}]
    good = {
        "id": "9",
        "displayed_text": "1",
        "leaders_complete": True,
        "leaders": [{"root": "a.asm", "model": "p.prt", "component_path": [40], "view": "FRONT"}],
    }
    assert bom.balloons([good], rows, "a.asm", "FRONT")[0]["quantity"] == 2
    for field, value in (("component_path", [99]), ("model", "other.prt"), ("view", "TOP")):
        wrong = copy.deepcopy(good)
        wrong["leaders"][0][field] = value
        try:
            bom.balloons([wrong], rows, "a.asm", "FRONT")
        except Error as exc:
            assert exc.code == "E_VERIFY_FAILED"
        else:
            raise AssertionError("incorrect native association accepted")
