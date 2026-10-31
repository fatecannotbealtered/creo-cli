"""Public CLI over real loopback HTTP: per-view evidence, not setter or assembly claims."""

import copy
import unittest
from unittest.mock import patch

from tests.test_commands import Base
from tests.test_round7_closeout import invoke


class ExplodedViewReadback(Base):
    def setUp(self):
        super().setUp()
        assembly = self.part("support.asm")
        assembly["exploded_states"] = [
            {
                "id": 40,
                "name": "OWNED_APART",
                "active": True,
                "is_default": False,
                "moves": [
                    {
                        "components": [41],
                        "component_paths": [["41"]],
                        "type": "translate",
                        "direction": [0, 0, 1],
                        "distance": 30,
                    }
                ],
            }
        ]
        assembly["is_exploded"] = True
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
        )

    def args(self, *, exploded=True, name="APART"):
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
            "--scale",
            1,
            *(("--exploded",) if exploded else ()),
        )

    def corrupt(self, mutation, *, exploded=True, check=None):
        args = self.args(exploded=exploded)
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.drawing_add_view

        def changed(request):
            reply = copy.deepcopy(original(request))
            mutation(self.world.models["instructions.drw"]["views"])
            return reply  # the creation reply still claims the correct requested view

        before = self.world.ops().count("drawing.add-view")
        with patch.object(self.world, "drawing_add_view", side_effect=changed):
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0, "setter reply must not substitute independent evidence")
        details = out["error"]["details"]
        if check:
            self.assertIn(check, [c["check"] for c in details.get("failed_checks", [])])
        self.assertEqual(self.world.ops().count("drawing.add-view"), before + 1)
        repeat = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(repeat["error"]["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before + 1)
        return out

    def test_setter_correct_but_independent_flag_false_is_rejected(self):
        self.corrupt(
            lambda views: views[-1].update(exploded=False), check="exploded_display_as_requested"
        )

    def test_independent_view_missing_cannot_fall_back_to_setter(self):
        self.corrupt(lambda views: views.clear(), check="one_new_view_identity")

    def test_wrong_independent_model_is_rejected(self):
        self.corrupt(
            lambda views: views[-1].update(model="foreign.asm"), check="view_model_as_requested"
        )

    def test_wrong_independent_sheet_is_rejected(self):
        self.corrupt(lambda views: views[-1].update(sheet=2), check="view_sheet_as_requested")

    def test_ordinary_unsupported_flag_is_incomplete_not_pending(self):
        out = self.corrupt(
            lambda views: views[-1].update(
                exploded_display_readback={
                    "complete": False,
                    "value": None,
                    "source": "WView2D.IsExplodedState",
                    "reason": "native_getter_failed",
                    "error": {"code": "E_UNSUPPORTED"},
                }
            )
        )
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("native_read_pending", out["error"]["details"])

    def test_missing_flag_does_not_inherit_assembly_true_or_setter(self):
        out = self.corrupt(lambda views: views[-1].update(exploded_display_readback={}))
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")

    def test_normal_view_actual_true_is_not_a_valid_false_default(self):
        self.corrupt(
            lambda views: views[-1].update(exploded=True),
            exploded=False,
            check="exploded_display_as_requested",
        )

    def test_reused_existing_id_cannot_identify_a_new_view(self):
        self.gated(*self.args(exploded=False, name="NORMAL"))
        self.corrupt(
            lambda views: views[-1].update(id=views[0]["id"]), check="unique_native_view_ids"
        )

    def test_duplicate_new_name_or_extra_view_is_rejected(self):
        def duplicate(views):
            extra = copy.deepcopy(views[-1])
            extra["id"] += 1
            views.append(extra)

        self.corrupt(duplicate, check="one_new_view_identity")

    def test_identity_report_cannot_disagree_with_its_view_row(self):
        def contradiction(views):
            row = self.world.drawing_view_row(views[-1], 0)
            row["view_identity_readback"]["model"]["value"] = "foreign.asm"
            views[-1].update(row)

        self.corrupt(contradiction, check="view_identity_readback_complete")

    def test_missing_native_identity_field_is_incomplete(self):
        def absent(views):
            row = self.world.drawing_view_row(views[-1], 0)
            row["view_identity_readback"]["sheet"] = {
                "complete": False,
                "value": None,
                "source": "View2D.GetSheetNumber",
            }
            row["view_identity_readback"]["complete"] = False
            views[-1].update(row)

        out = self.corrupt(absent)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")

    def test_old_view_or_drawing_resource_change_is_rejected(self):
        self.gated(*self.args(exploded=False, name="NORMAL"))
        self.corrupt(lambda views: views[0].update(exploded=True), check="existing_views_preserved")

    def test_named_state_drift_after_preview_refuses_before_dispatch(self):
        args = self.args()
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.models["support.asm"]["exploded_states"][0]["moves"][0]["distance"] = 35
        before = self.world.ops().count("drawing.add-view")
        out = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(out["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_incomplete_source_alias_cannot_authorize_exploded_view(self):
        original = self.world.op

        def incomplete(op, request):
            result = original(op, request)
            if op == "model.show" and request["model"] == "support.asm":
                result["explosion"]["complete"] = False
                self.assertTrue(result["exploded_states"][0]["moves"])
            return result

        before = self.world.ops().count("drawing.add-view")
        with patch.object(self.world, "op", side_effect=incomplete):
            code, out = invoke(self, *self.args(), "--dry-run")
        self.assertNotEqual(code, 0, "populated legacy alias does not complete the native state")
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_source_active_id_flag_and_move_gaps_refuse_before_dispatch(self):
        original = self.world.op
        for problem in (
            "active_id",
            "inactive_flag",
            "display_false",
            "missing_moves",
            "empty_moves",
        ):
            with self.subTest(problem=problem):

                def incomplete(op, request, problem=problem):
                    result = copy.deepcopy(original(op, request))
                    if op == "model.show" and request["model"] == "support.asm":
                        native = result["explosion"]
                        if problem == "active_id":
                            native["active_state_id"] = "999"
                        elif problem == "inactive_flag":
                            native["states"][0]["active"] = False
                        elif problem == "display_false":
                            native["is_exploded"] = False
                        elif problem == "missing_moves":
                            native["states"][0].pop("moves")
                        elif problem == "empty_moves":
                            native["states"][0]["moves"] = []
                    return result

                before = self.world.ops().count("drawing.add-view")
                with patch.object(self.world, "op", side_effect=incomplete):
                    code, out = invoke(self, *self.args(), "--dry-run")
                self.assertNotEqual(code, 0, out)
                self.assertIn(out["error"]["code"], ("E_VERIFY_INCOMPLETE", "E_VALIDATION"))
                self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_assembly_source_changes_after_creation_are_rejected(self):
        def changed(_views):
            self.world.models["support.asm"]["volume"] += 1

        self.corrupt(changed, check="exploded_source_snapshot_preserved")

    def test_extra_assembly_occurrence_after_creation_is_rejected(self):
        def changed(_views):
            self.world.models["support.asm"].setdefault("components", []).append(
                {
                    "id": 999,
                    "model": "foreign.prt",
                    "position": {
                        "origin": [0, 0, 0],
                        "x_axis": [1, 0, 0],
                        "y_axis": [0, 1, 0],
                        "z_axis": [0, 0, 1],
                    },
                }
            )

        self.corrupt(changed, check="exploded_source_snapshot_preserved")

    def test_postwrite_incomplete_source_remains_incomplete(self):
        args = self.args()
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def unavailable(op, request):
            result = original(op, request)
            if (
                op == "model.show"
                and request["model"] == "support.asm"
                and "drawing.add-view" in self.world.succeeded
            ):
                result["explosion"]["complete"] = False
            return result

        with patch.object(self.world, "op", side_effect=unavailable):
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0, out)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_new_source_section_with_exploded_view_refuses_before_any_write(self):
        before = copy.deepcopy(self.world.models["support.asm"])
        count = self.world.ops().count("drawing.add-view")
        code, out = invoke(self, *self.args(), "--plane", "TOP", "--dry-run")
        self.assertNotEqual(code, 0, out)
        self.assertEqual(out["error"]["code"], "E_UNSUPPORTED")
        self.assertEqual(self.world.ops().count("drawing.add-view"), count)
        self.assertEqual(self.world.models["support.asm"], before)

    def test_old_r5_exploded_refuses_before_any_cad_request(self):
        self.world.capabilities.pop("drawing_view_exploded_readback")
        before = len(self.world.events)
        out = self.cli(*self.args(), "--dry-run", status=4)
        self.assertEqual(out["error"]["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(out["error"]["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.world.events[before:], [])

    def test_old_r5_normal_path_remains_legacy_without_flag_claim(self):
        self.world.capabilities.pop("drawing_view_exploded_readback")
        result = self.gated(*self.args(exploded=False))["data"]
        self.checks_pass(result)
        self.assertIn(
            "legacy_service_per_view_exploded_flag_and_identity_metadata",
            result["verification"]["not_checked"],
        )

    def test_existing_unreadable_flag_refuses_before_new_creation(self):
        self.gated(*self.args(exploded=False, name="NORMAL"))
        self.world.models["instructions.drw"]["views"][0]["exploded_display_readback"] = {
            "complete": False,
            "value": None,
            "source": "WView2D.IsExplodedState",
        }
        before = self.world.ops().count("drawing.add-view")
        out = self.cli(*self.args(), "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_existing_duplicate_ids_refuse_before_new_creation(self):
        self.gated(*self.args(exploded=False, name="NORMAL"))
        row = self.world.models["instructions.drw"]["views"][0]
        self.world.models["instructions.drw"]["views"].append(
            copy.deepcopy(row) | {"name": "OTHER"}
        )
        before = self.world.ops().count("drawing.add-view")
        out = self.cli(*self.args(), "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_normal_confirmation_cannot_silently_downgrade_frozen_contract(self):
        args = self.args(exploded=False)
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.capabilities.pop("drawing_view_exploded_readback")
        before = self.world.ops().count("drawing.add-view")
        out = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(out["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.world.ops().count("drawing.add-view"), before)

    def test_pending_independent_read_stops_later_cad_and_never_replays_setter(self):
        args = self.args()
        pre = self.cli(*args, "--dry-run")["data"]
        before = len(self.world.events)
        self.world.then_fail = (
            "drawing.add-view",
            "model.show",
            {
                "code": "E_UNAVAILABLE",
                "message": "getter started and has not returned",
                "started": True,
            },
        )
        code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)
        pending = out["error"]["details"]["native_read_error"]
        self.assertEqual(pending["code"], "E_NATIVE_READ_PENDING")
        events = self.world.events[before:]
        index = next(i for i, (op, _) in enumerate(events) if op == "drawing.add-view")
        self.assertEqual([op for op, _ in events[index + 1 :]], ["model.show"])
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_normal_and_exploded_views_keep_their_own_flags(self):
        normal = self.gated(*self.args(exploded=False, name="NORMAL"))["data"]
        self.checks_pass(normal)
        apart = self.gated(*self.args())["data"]
        self.checks_pass(apart)
        rows = self.cli("model", "show", "--model", "instructions.drw")["data"]["views"]
        self.assertEqual(
            [(v["name"], v["exploded_display_readback"]["value"]) for v in rows],
            [("NORMAL", False), ("APART", True)],
        )
        self.assertTrue(
            all(v["named_exploded_state_reference"]["status"] == "not_checked" for v in rows)
        )


if __name__ == "__main__":
    unittest.main()
