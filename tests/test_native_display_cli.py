"""Public CLI over real loopback HTTP; fixture behavior is not native CAD evidence."""

import copy
from unittest.mock import patch

from tests.fixture_features import Refusal
from tests.test_features import Built
from tests.test_round7_closeout import invoke


class NativePresentationHTTP(Built):
    def repeated_source(self):
        source = self.block()
        owner = self.part("holdout.asm")
        owner["components"] = []
        for ident, x in ((40, 0.0), (41, 50.0)):
            owner["components"].append(
                {
                    "id": ident,
                    "model": "block.prt",
                    "status": "FEAT_ACTIVE",
                    "placed": True,
                    "packaged": False,
                    "underconstrained": False,
                    "constraints": [{"type": "align", "offset": x}],
                    "position": {
                        "origin": [x, 0.0, 0.0],
                        "x_axis": [1.0, 0.0, 0.0],
                        "y_axis": [0.0, 1.0, 0.0],
                        "z_axis": [0.0, 0.0, 1.0],
                    },
                    "volume": source["volume"],
                }
            )
        owner["volume"] = source["volume"] * 2
        self.world.write_version(self.ws, "holdout.asm", owner)
        self.world.active = "holdout.asm"
        return source, owner

    def color_request(self, rgb, *, affected=None, restore=False):
        observed = self.cli("appearance", "show", "--model", "BLOCK.PRT")["data"]
        request = {
            "scope": "source_part",
            "source_file_authorized": True,
            "affected_occurrences": observed["affected_occurrences"]
            if affected is None
            else affected,
        }
        request["appearance" if restore else "rgb"] = rgb
        return self.request(request, "恢复颜色.json" if restore else "颜色请求.json")

    def replacement_request(self, rgb):
        observed = self.cli("appearance", "show", "--model", "block.prt")["data"]
        return self.request(
            {
                "scope": "source_part",
                "source_file_authorized": True,
                "affected_occurrences": observed["affected_occurrences"],
                "reference_action": "create_and_bind",
                "reference_replacement_authorized": True,
                "rgb": rgb,
            },
            "创建引用并重新绑定.json",
        )

    def test_authorized_colour_change_binds_actual_id_and_preserves_shared_old_source(self):
        source, owner = self.repeated_source()
        initial = self.color_request([0.125, 0.375, 0.875])
        self.gated("appearance", "set", "--model", "block.prt", "--request", initial)
        other = self.part("display.prt")
        # Two sources deliberately use the same old object in this controlled substitute.
        other["cosmetic_appearance"] = source["cosmetic_appearance"]
        before_other = copy.deepcopy(other)
        before_constraints = copy.deepcopy(owner["components"])
        old_id = source["cosmetic_appearance"]["name"]
        request = self.replacement_request([0.125, 0.75, 0.5])
        args = ("appearance", "set", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]
        intended = preview["preview"]["extensions"]["creo"]
        self.assertIsNone(intended["reference_after"]["native_id"])
        self.assertEqual(
            intended["reference_after"]["allocation_status"], "pending_native_allocation"
        )
        self.assertEqual(len(intended["affected_occurrences"]), 2)
        completed = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        result = completed["result"]
        self.assertEqual(result["reference_before"]["native_id"], old_id)
        self.assertNotEqual(result["reference_after"]["native_id"], old_id)
        self.assertTrue(result["reference_after"]["whole_source_binding_observed"])
        self.assertEqual(other, before_other)
        self.assertEqual(owner["components"], before_constraints)
        reference = completed["receipt"]["extensions"]["creo"]["appearance_reference"]
        self.assertEqual(reference["action"], "create_and_bind")
        self.assertTrue(reference["reference_replacement_authorized"])
        self.assertEqual(reference["target"], "block.prt")
        self.assertEqual(reference["scope"], "source_part")
        self.assertEqual(reference["before"]["native_id"], old_id)
        self.assertEqual(reference["after"], result["reference_after"])
        self.assertEqual(reference["affected_occurrences"], intended["affected_occurrences"])
        self.assertFalse(reference["native_id_prediction_used"])
        self.assertFalse(reference["saved_reopen_binding_verified"])

    def test_existing_colour_change_without_reference_authorization_never_dispatches(self):
        source = self.block()
        initial = self.color_request([0.125, 0.375, 0.875])
        self.gated("appearance", "set", "--model", "block.prt", "--request", initial)
        count = self.world.ops().count("appearance.set")
        request = self.color_request([0.125, 0.75, 0.5])
        code, error = invoke(
            self, "appearance", "set", "--model", "block.prt", "--request", request, "--dry-run"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(error["error"]["code"], "E_UNSUPPORTED")
        self.assertEqual(self.world.ops().count("appearance.set"), count)
        self.assertEqual(source["cosmetic_appearance"]["rgb"], [0.125, 0.375, 0.875])

    def test_actual_replacement_save_normal_close_exact_reopen_and_second_colour_change(self):
        self.block()
        initial = self.color_request([0.125, 0.375, 0.875])
        self.gated("appearance", "set", "--model", "block.prt", "--request", initial)
        for rgb in ([0.125, 0.75, 0.5], [0.625, 0.125, 0.75]):
            before = self.cli("appearance", "show", "--model", "block.prt")["data"]
            request = self.replacement_request(rgb)
            result = self.gated("appearance", "set", "--model", "block.prt", "--request", request)[
                "data"
            ]
            self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
            self.assertNotEqual(
                result["result"]["reference_after"]["native_id"], before["appearance"]["name"]
            )
            saved = self.gated("model", "save", "--model", "block.prt")["data"]["result"]["file"]
            self.gated("model", "close", "--model", "block.prt")
            self.gated("model", "open", "--path", saved)
            reopened = self.cli("appearance", "show", "--model", "block.prt")["data"]
            self.assertEqual(reopened["appearance"]["rgb"], rgb)
            self.assertTrue(reopened["reference_binding"]["whole_source_binding_observed"])
            self.assertFalse(reopened["modified"])

    def test_service_before_guard_refuses_gap_drift_and_never_assigns_new_reference(self):
        source = self.block()
        initial = self.color_request([0.125, 0.375, 0.875])
        self.gated("appearance", "set", "--model", "block.prt", "--request", initial)
        self.gated("model", "save", "--model", "block.prt")
        request = self.replacement_request([0.125, 0.75, 0.5])
        args = ("appearance", "set", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]
        setter = self.world.appearance_set

        def drift_after_confirm_observation(q):
            source["cosmetic_appearance"]["label"] = "controlled concurrent label"
            return setter(q)

        with patch.object(
            self.world, "appearance_set", side_effect=drift_after_confirm_observation
        ):
            code, error = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertEqual(error["error"]["code"], "E_CONFLICT")
        self.assertEqual(source["cosmetic_appearance"]["rgb"], [0.125, 0.375, 0.875])
        self.assertFalse(source["modified"])
        self.assertFalse(hasattr(self.world, "appearance_reference_serial"))

    def test_repeated_source_requires_every_exact_occurrence_and_protects_constraints(self):
        source, owner = self.repeated_source()
        constraints = copy.deepcopy(owner["components"])
        observed = self.cli("appearance", "show", "--model", "block.prt")["data"]
        self.assertEqual(len(observed["affected_occurrences"]), 2)
        incomplete = self.color_request(
            [0.1, 0.2, 0.3], affected=observed["affected_occurrences"][:1]
        )
        code, error = invoke(
            self, "appearance", "set", "--model", "block.prt", "--request", incomplete, "--dry-run"
        )
        self.assertEqual(code, 4, error)
        self.assertEqual(error["error"]["code"], "E_FORBIDDEN")
        self.assertNotIn("appearance.set", self.world.ops())
        complete = self.color_request([0.123456789123, 0.8, 0.1])
        result = self.gated("appearance", "set", "--model", "BLOCK.PRT", "--request", complete)[
            "data"
        ]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(source["cosmetic_appearance"]["rgb"], [0.123456789123, 0.8, 0.1])
        self.assertEqual(owner["components"], constraints)
        self.assertNotIn("model.save", self.world.ops())

    def test_color_explicit_save_normal_close_exact_reopen_restore(self):
        self.block()
        original = self.cli("appearance", "show", "--model", "block.prt")["data"]["appearance"]
        request = self.color_request([0.1, 0.3, 0.7])
        self.gated("appearance", "set", "--model", "block.prt", "--request", request)
        saved = self.gated("model", "save", "--model", "block.prt")["data"]["result"]["file"]
        self.gated("model", "close", "--model", "block.prt")
        self.gated("model", "open", "--path", saved)
        readback = self.cli("appearance", "show", "--model", "block.prt")["data"]
        self.assertEqual(readback["appearance"]["rgb"], [0.1, 0.3, 0.7])
        self.assertFalse(readback["modified"])
        restore = self.color_request(original, restore=True)
        self.gated("appearance", "restore", "--model", "block.prt", "--request", restore)
        self.assertEqual(
            self.cli("appearance", "show", "--model", "block.prt")["data"]["appearance"], original
        )

    def test_public_activation_fit_same_view_render_and_single_occurrence_hide(self):
        _, owner = self.repeated_source()
        self.gated("display", "activate", "--model", "holdout.asm")
        hidden_result = self.gated(
            "display",
            "component-visibility",
            "--model",
            "holdout.asm",
            "--component",
            "40",
            "--state",
            "hidden",
        )
        self.assertEqual(hidden_result["data"]["receipt"]["outcome"]["persistence"], "unsaved")
        visibility = self.cli("display", "show", "--model", "holdout.asm")["data"][
            "component_visibility"
        ]
        self.assertEqual([row["hidden"] for row in visibility], [True, False])
        self.gated(
            "display",
            "component-visibility",
            "--model",
            "holdout.asm",
            "--component",
            "40",
            "--state",
            "visible",
        )
        self.assertEqual(len(owner["components"]), 2)
        fitted = self.gated(
            "display", "fit", "--model", "holdout.asm", "--view", "isometric", "--margin", 0.15
        )["data"]
        self.assertEqual(fitted["receipt"]["outcome"]["verification"]["status"], "passed")
        image = self.gated(
            "artifact",
            "render",
            "--model",
            "holdout.asm",
            "--view",
            "current",
            "--output",
            "fixture-presentation.jpg",
        )["data"]
        self.assertTrue(image["result"]["published"])
        self.assertIn("not a native image", image["result"]["decoded"]["source"])

    def test_render_missing_actual_source_rgb_is_rejected_before_export(self):
        self.block()
        original = self.world.render_state

        def absent(q):
            observed = original(q)
            observed.pop("native_part_appearances")
            return observed

        with patch.object(self.world, "render_state", side_effect=absent):
            code, error = invoke(
                self,
                "artifact",
                "render",
                "--model",
                "block.prt",
                "--view",
                "current",
                "--output",
                "missing-color.jpg",
                "--dry-run",
            )
        self.assertNotEqual(code, 0)
        self.assertEqual(error["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("model.render", self.world.ops())

    def test_dirty_only_native_error_remains_unsaved_and_is_not_replayed(self):
        model = self.block()
        self.gated("model", "save", "--model", "block.prt")
        request = self.color_request([0.2, 0.6, 0.9])
        args = ("appearance", "set", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]

        def dirty(q):
            model["modified"] = True
            failure = Refusal("E_CREO", "controlled dirty-only setter failure")
            failure.error |= {"stage": "appearance_set", "model_state": {"modified": True}}
            raise failure

        with patch.object(self.world, "appearance_set", side_effect=dirty):
            code, error = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        receipt = error["error"]["details"]["receipt"]
        self.assertNotEqual(receipt["outcome"]["persistence"], "unchanged")
        self.assertTrue(model["modified"])
        self.assertIsNone(model.get("cosmetic_appearance"))
        self.assertEqual(self.world.ops().count("appearance.set"), 1)

    def test_window_owner_without_session_current_model_is_not_activation_proof(self):
        self.repeated_source()
        self.world.native_current_model_override = None
        observed = self.cli("display", "show", "--model", "holdout.asm")["data"]
        self.assertFalse(observed["target_active"])
        self.assertEqual(observed["window_model"], "holdout.asm")
        self.assertIsNone(observed["current_model"])
        for verb in ("activate", "unexplode"):
            code, error = invoke(self, "display", verb, "--model", "holdout.asm", "--dry-run")
            self.assertNotEqual(code, 0)
            self.assertIn(error["error"]["code"], ("E_UNSUPPORTED", "E_VERIFY_INCOMPLETE"))
        self.assertNotIn("display.activate", self.world.ops())
        self.assertNotIn("display.unexplode", self.world.ops())

    def test_visibility_failed_independent_readback_reports_unknown_persistence(self):
        _, owner = self.repeated_source()
        args = (
            "display",
            "component-visibility",
            "--model",
            "holdout.asm",
            "--component",
            "40",
            "--state",
            "hidden",
        )
        preview = self.cli(*args, "--dry-run")["data"]
        setter = self.world.display_visibility

        def set_then_lose_readback(q):
            result = setter(q)
            self.world.fail = (
                "display.state",
                {"code": "E_CREO", "message": "controlled persistent display readback failure"},
            )
            return result

        with patch.object(self.world, "display_visibility", side_effect=set_then_lose_readback):
            code, error = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        receipt = error["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertNotEqual(receipt["outcome"]["verification"]["status"], "passed")
        self.assertTrue(owner["modified"])
        self.assertTrue(owner["hidden_components"]["40"])
        self.assertEqual(self.world.ops().count("display.visibility"), 1)
        self.assertNotIn("model.save", self.world.ops())

    def test_appearance_readback_failure_never_reports_passed(self):
        self.block()
        request = self.color_request([0.9, 0.2, 0.1])
        args = ("appearance", "set", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]
        self.world.then_fail = (
            "appearance.set",
            "appearance.get",
            {"code": "E_CREO", "message": "controlled readback failure"},
        )
        code, error = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertNotEqual(
            error["error"]["details"]["receipt"]["outcome"]["verification"]["status"], "passed"
        )
        self.assertEqual(self.world.ops().count("appearance.set"), 1)

    def test_noop_color_keeps_domain_and_public_persistence_unchanged(self):
        self.block()
        request = self.color_request([0.2, 0.4, 0.6])
        self.gated("appearance", "set", "--model", "block.prt", "--request", request)
        self.gated("model", "save", "--model", "block.prt")
        request = self.color_request([0.2, 0.4, 0.6])
        with patch.object(
            self.world,
            "appearance_set",
            return_value={"model": "block.prt", "scope": "source_part", "setter_returned": True},
        ):
            result = self.gated("appearance", "set", "--model", "block.prt", "--request", request)[
                "data"
            ]
        self.assertEqual(result["result"]["persistence"], "unchanged")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unchanged")

    def inventory_injection(self, kind):
        self.block()
        request = self.color_request([0.6, 0.4, 0.2])
        args = ("appearance", "set", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]
        setter = self.world.appearance_set

        def injected(q):
            result = setter(q)
            row = self.world.appearance_get(q)["assignments"][0]
            if kind == "face":
                row["item_type"], row["item_id"] = "ITEM_SURFACE", "99"
            else:
                row["textures"][0]["file_path"] = "controlled-real-texture.png"
            self.world.models["block.prt"]["cosmetic_assignments"] = [row]
            return result

        with patch.object(self.world, "appearance_set", side_effect=injected):
            code, error = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertEqual(
            error["error"]["details"]["receipt"]["outcome"]["verification"]["status"], "failed"
        )
        self.assertEqual(self.world.ops().count("appearance.set"), 1)

    def test_after_new_face_override_cannot_report_color_passed(self):
        self.inventory_injection("face")

    def test_after_new_actual_texture_cannot_report_color_passed(self):
        self.inventory_injection("texture")
