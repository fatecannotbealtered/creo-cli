"""Public parser and loopback HTTP checks; no native Creo or real operation database."""

import copy
import unittest
from unittest.mock import patch

from tests.test_commands import Base, domain_preview, domain_receipt
from tests.test_round7_closeout import invoke


class FirstViewScaleGuard(Base):
    def setUp(self):
        super().setUp()
        self.part("support.asm")
        self.gated(
            "drawing",
            "create",
            "--name",
            "instructions",
            "--of",
            "support.asm",
            "--sheet",
            "a3",
            "--views",
            "none",
            "--scale",
            "1:1",
        )

    def args(self, scale=None, name="MAIN"):
        return (
            "drawing",
            "view",
            "add",
            "--model",
            "instructions.drw",
            "--type",
            "general",
            "--name",
            name,
            "--x",
            200,
            "--y",
            140,
            *(("--scale", scale) if scale is not None else ()),
        )

    def reject(self, args, expected):
        count = self.world.ops().count("drawing.add-view")
        for _ in range(2):
            code, answer = invoke(self, *args, "--dry-run")
            self.assertNotEqual(code, 0, answer)
            self.assertEqual(answer["error"]["code"], expected)
            self.assertEqual(answer["error"]["details"]["dispatch_state"], "not_started")
            self.assertNotIn("confirm_token", str(answer))
        self.assertEqual(self.world.ops().count("drawing.add-view"), count)
        return answer

    def test_first_explicit_different_scale_is_rejected_without_create_or_receipt(self):
        before = copy.deepcopy(self.world.models["instructions.drw"])
        receipts = self.receipts()
        answer = self.reject(self.args(1.5), "E_UNSUPPORTED")
        self.assertEqual(self.world.models["instructions.drw"], before)
        self.assertEqual(self.receipts(), receipts)
        details = answer["error"]["details"]
        self.assertEqual(details["requested_view_scale"], 1.5)
        self.assertEqual(details["current_sheet_scale"], 1.0)
        self.assertIn("drawing create --scale", details["fix"])
        # There is no epsilon that turns a real sheet change into no change.
        self.reject(self.args(1.0000000000000002), "E_UNSUPPORTED")

    def test_first_explicit_same_scale_is_allowed_and_sheet_is_preserved(self):
        self.world.models["instructions.drw"]["sheets"][0]["scale"] = 0.5
        self.world.models["instructions.drw"]["sheets"][0]["scale_label"] = "1:2"
        before = copy.deepcopy(self.world.models["instructions.drw"]["sheets"])
        raw = self.gated(*self.args(0.5))["data"]
        out = domain_receipt(raw.get("receipt", raw))
        self.checks_pass(out)
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)
        self.assertEqual(self.world.models["instructions.drw"]["sheets"], before)

    def test_nonempty_drawing_keeps_per_view_different_scale_path(self):
        self.gated(*self.args(1.0))
        before = copy.deepcopy(self.world.models["instructions.drw"]["sheets"])
        raw = self.gated(*self.args(1.5, "SECOND"))["data"]
        self.checks_pass(domain_receipt(raw.get("receipt", raw)))
        self.assertEqual(self.world.ops().count("drawing.add-view"), 2)
        self.assertEqual(self.world.models["instructions.drw"]["sheets"], before)
        self.assertEqual(self.world.models["instructions.drw"]["views"][-1]["scale"], 1.5)

    def test_no_explicit_scale_keeps_existing_path(self):
        self.world.models["instructions.drw"]["sheets"][0].pop("scale")
        raw = self.gated(*self.args())["data"]
        self.checks_pass(domain_receipt(raw.get("receipt", raw)))
        sent = [request for op, request in self.world.events if op == "drawing.add-view"]
        self.assertEqual(len(sent), 1)
        self.assertNotIn("scale", sent[0]["view"])

    def test_background_entry_counts_as_nonempty_without_foreground_filtering(self):
        self.gated(*self.args(1))
        self.world.models["instructions.drw"]["views"][0]["type"] = "background"
        before = self.world.ops().count("drawing.add-view")
        preview = self.cli(*self.args(1.5, "SECOND"), "--dry-run")["data"]
        self.assertEqual(domain_preview(preview["preview"])["views_now"], 1)
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_missing_or_ambiguous_first_sheet_scale_fails_closed(self):
        drawing = self.world.models["instructions.drw"]
        good = copy.deepcopy(drawing["sheets"])
        for sheets in (
            [],
            [{"number": 1}],
            [{"number": 2, "scale": 1}],
            good + good,
            good + [good[0] | {"number": 2}],
            [good[0] | {"scale": None}],
            [good[0] | {"scale": True}],
            [good[0] | {"scale": "1"}],
            [good[0] | {"scale": 0}],
            [good[0] | {"scale": 10**400}],
        ):
            with self.subTest(sheets=sheets):
                drawing["sheets"] = copy.deepcopy(sheets)
                self.reject(self.args(1), "E_VERIFY_INCOMPLETE")
        drawing["sheets"] = good

    def test_first_scale_does_not_guess_current_model_or_missing_view_inventory(self):
        original = self.world.drawing_summary
        for fields in (
            {"models": []},
            {"models": ["support.asm", "foreign.prt"]},
            {"views": None},
            {"views": "not an inventory"},
        ):
            with self.subTest(fields=fields):

                def unavailable(name, model, fields=fields):
                    return original(name, model) | copy.deepcopy(fields)

                with patch.object(self.world, "drawing_summary", side_effect=unavailable):
                    self.reject(self.args(1), "E_VERIFY_INCOMPLETE")

    def test_confirmation_rechecks_before_creating(self):
        args = self.args(1)
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertEqual(domain_preview(preview["preview"])["views_now"], 0)
        self.world.models["instructions.drw"]["sheets"][0]["scale"] = 0.5
        code, answer = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0, answer)
        self.assertEqual(answer["error"]["code"], "E_UNSUPPORTED")
        self.assertEqual(answer["error"]["details"]["dispatch_state"], "not_started")
        self.assertNotIn("drawing.add-view", self.world.ops())


if __name__ == "__main__":
    unittest.main()
