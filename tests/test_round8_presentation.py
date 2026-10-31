"""Public CLI regressions for full explode state and render restoration."""

import copy
import unittest
from unittest.mock import patch

from creo_cli import presentation
from creo_cli.core import Error
from tests import test_assemblies as asm_cases
from tests.fixture_features import Refusal
from tests.test_features import Built
from tests.test_round7_closeout import invoke


class RenderSettlement(unittest.TestCase):
    def test_display_settlement_keeps_original_criterion_and_all_observations(self):
        for states, expected in (
            ([{"zoom": 2}, {"zoom": 1}, {"zoom": 1}], {"zoom": 1}),
            ([{"zoom": 2}, {"zoom": 2}], {"zoom": 2}),
        ):
            with (
                self.subTest(states=states),
                patch.object(presentation, "render_state", side_effect=states) as getter,
            ):
                actual, samples = presentation.settled_render_state(None, "block.prt")
                self.assertEqual(actual, expected)
                self.assertEqual(samples, states)
                self.assertEqual(getter.call_count, len(states))

    def test_unsettled_or_unreadable_state_never_becomes_restored(self):
        for states in (
            [{"zoom": 1}, {"zoom": 2}, {"zoom": 1}],
            [Error("E_VERIFY_INCOMPLETE", "getter unavailable")],
        ):
            with (
                self.subTest(states=states),
                patch.object(presentation, "render_state", side_effect=states) as getter,
            ):
                with self.assertRaises(Error) as caught:
                    presentation.settled_render_state(None, "block.prt")
                self.assertEqual(caught.exception.code, "E_VERIFY_INCOMPLETE")
                self.assertEqual(getter.call_count, len(states))


class ExplodeIntegrity(asm_cases.AssemblyParts):
    gearbox = asm_cases.ExplodedStates.gearbox

    def arguments(self, **extra):
        ids = self.gearbox()
        body = {
            "units": "mm",
            "name": "OWNED",
            "moves": [{"components": [ids["pin.prt"]], "direction": [0, 0, 1], "distance": 30}],
        } | extra
        return (
            "assembly",
            "explode",
            "apply",
            "--model",
            "gearbox.asm",
            "--request",
            self.request(body, "explode.json"),
        )

    def test_incomplete_direction_is_not_certified(self):
        args = self.arguments()
        original = self.world.assembly_explode

        def incomplete(q):
            result = original(q)
            self.world.models["gearbox.asm"]["exploded_states"][0]["moves"][0]["direction"] = []
            return result

        with patch.object(self.world, "assembly_explode", side_effect=incomplete):
            pre = self.cli(*args, "--dry-run")["data"]
            code, _ = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)

    def test_failed_creation_that_changes_only_active_state_is_not_unchanged(self):
        args = self.arguments()
        states = self.world.states_of(self.world.models["gearbox.asm"])

        def failure(q):
            states[0]["active"] = False
            raise Refusal("E_CREO", "injected failure after active state change")

        with patch.object(self.world, "assembly_explode", side_effect=failure):
            pre = self.cli(*args, "--dry-run")["data"]
            _, result = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertIn(result["error"]["code"], ("E_PARTIAL", "E_OUTCOME_UNKNOWN"))

    def test_in_place_edit_preserves_identity_and_other_states(self):
        args = self.arguments()
        made = self.gated(*args)["data"]
        initial = copy.deepcopy(self.world.states_of(self.world.models["gearbox.asm"]))
        import json
        from pathlib import Path

        path = Path(args[-1])
        body = json.loads(path.read_text())
        body["replace"] = True
        body["moves"][0]["distance"] = 60
        path.write_text(json.dumps(body), encoding="utf-8")
        out = self.gated(*args)["data"]
        final = self.world.states_of(self.world.models["gearbox.asm"])
        self.assertEqual(final[0]["id"], initial[0]["id"])
        self.assertEqual(final[0]["moves"][0]["distance"], 60)
        self.assertEqual(final[1:], initial[1:])
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertNotEqual(made["operation_id"], out["operation_id"])

    def test_failure_after_losing_existing_state_is_partial_and_blocked(self):
        args = self.arguments()
        self.gated(*args)
        import json
        from pathlib import Path

        path = Path(args[-1])
        body = json.loads(path.read_text())
        body["replace"] = True
        path.write_text(json.dumps(body), encoding="utf-8")

        def failure(q):
            model = self.world.models["gearbox.asm"]
            model["exploded_states"] = [s for s in model["exploded_states"] if s["name"] != "OWNED"]
            model["exploded_states"][0]["active"] = True
            model["is_exploded"] = False
            raise Refusal("E_CREO", "controlled destructive backend failure")

        with patch.object(self.world, "assembly_explode", side_effect=failure):
            pre = self.cli(*args, "--dry-run")["data"]
            _, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertEqual(out["error"]["code"], "E_PARTIAL")
        self.cli("model", "save", "--model", "gearbox.asm", "--dry-run", status=6)

    def test_request_drift_and_duplicate_occurrences_refuse_before_dispatch(self):
        args = self.arguments()
        import json
        from pathlib import Path

        path = Path(args[-1])
        body = json.loads(path.read_text())
        pre = self.cli(*args, "--dry-run")["data"]
        body["moves"][0]["distance"] = 70
        path.write_text(json.dumps(body), encoding="utf-8")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        body["moves"].append(body["moves"][0])
        path.write_text(json.dumps(body), encoding="utf-8")
        self.cli(*args, "--dry-run", status=2)
        self.assertNotIn("assembly.explode", self.world.ops())

    def test_display_translation_cannot_hide_changed_physical_placement(self):
        args = self.arguments()
        original = self.world.assembly_explode

        def moved(q):
            result = original(q)
            # The fixture stores physical placement separately from its display projection.
            self.world.models["gearbox.asm"]["components"][0]["position"]["origin"][0] += 7
            return result

        with patch.object(self.world, "assembly_explode", side_effect=moved):
            pre = self.cli(*args, "--dry-run")["data"]
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)
        failed = out["error"]["details"]["failed_checks"]
        self.assertIn("placement_and_display_translations_consistent", [c["check"] for c in failed])

    def test_old_explosion_service_is_refused_before_writing(self):
        args = self.arguments()
        self.world.capabilities["explosion_state_readback"] = 1
        out = self.cli(*args, "--dry-run", status=4)
        self.assertEqual(out["error"]["details"]["required_capability"]["version"], 2)
        self.assertNotIn("assembly.explode", self.world.ops())

    def test_deleted_request_is_a_known_pre_dispatch_refusal(self):
        from pathlib import Path

        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        Path(args[-1]).unlink()
        out = self.cli(*args, "--confirm", pre["confirm_token"], status=3)
        self.assertEqual(out["error"]["code"], "E_NOT_FOUND")
        self.assertEqual(out["error"]["details"]["dispatch_state"], "not_started")
        self.assertNotIn("assembly.explode", self.world.ops())

    def test_workflow_does_not_implicitly_enable_explosion_leaf(self):
        args = self.arguments()
        task = self.request(
            {
                "steps": [
                    {
                        "command": "assembly explode apply",
                        "args": {"model": "gearbox.asm", "request": str(args[-1])},
                    }
                ]
            },
            "workflow.json",
        )
        out = self.cli("workflow", "run", "--request", task, "--dry-run", status=2)
        self.assertEqual(out["error"]["code"], "E_UNSUPPORTED")
        self.assertNotIn("assembly.explode", self.world.ops())


class RenderIntegrity(Built):
    def test_public_discovery_and_workflow_boundaries(self):
        self.block()
        data = self.cli("reference", "--command", "artifact render")["data"]
        self.assertIn("active", str(data))
        context = self.cli("context")["data"]
        self.assertIn(
            "artifact render",
            context["capabilities"]["bounded_presentation"],
        )
        doctor = self.cli("doctor")["data"]
        self.assertTrue(any(c["check"] == "presentation_scope" for c in doctor["checks"]))
        task = self.request(
            {
                "steps": [
                    {
                        "command": "artifact render",
                        "args": {"model": "block.prt", "output": "no.jpg"},
                    }
                ]
            },
            "workflow.json",
        )
        out = self.cli("workflow", "run", "--request", task, "--dry-run", status=2)
        self.assertEqual(out["error"]["code"], "E_UNSUPPORTED")
        self.assertNotIn("model.render", self.world.ops())

    def test_inactive_target_is_refused_before_native_render(self):
        self.block()
        self.world.part("other.prt")
        self.world.active = "other.prt"
        out = self.cli(
            "artifact",
            "render",
            "--model",
            "block.prt",
            "--output",
            "inactive.jpg",
            "--dry-run",
            status=2,
        )
        self.assertEqual(out["error"]["code"], "E_UNSUPPORTED")
        self.assertNotIn("model.render", self.world.ops())

    def test_generated_file_does_not_excuse_unrestored_presentation(self):
        self.block()
        state = {
            "complete": True,
            "model": "block.prt",
            "window": "1",
            "active_window": "1",
            "active_model": "block.prt",
            "view_transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
            "screen": {"pan_x": 0, "pan_y": 0, "zoom": 1},
            "datums": {
                "display_planes": "yes",
                "display_axes": "yes",
                "display_points": "yes",
                "display_coord_sys": "yes",
            },
            "explosion": None,
            "modified": True,
            "source": "controlled native fixture",
            "current_model": "block.prt",
            "current_model_type": "part",
            "window_model": "block.prt",
            "window_model_type": "part",
            "context_complete": True,
            "native_part_appearances": {
                "block.prt": self.world.appearance_get({"model": "block.prt"})
            },
        }
        original, render = self.world.op, self.world.render

        def op(name, q):
            if name == "model.render-state":
                return copy.deepcopy(state)
            return original(name, q)

        def unrestored(q):
            result = render(q)
            state["screen"]["zoom"] = 2
            return result

        args = (
            "artifact",
            "render",
            "--model",
            "block.prt",
            "--output",
            "view.jpg",
            "--view",
            "current",
        )
        with (
            patch.object(self.world, "op", side_effect=op),
            patch.object(self.world, "render", side_effect=unrestored),
        ):
            pre = self.cli(*args, "--dry-run")["data"]
            code, _ = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)

    def test_render_failure_keeps_artifact_and_blocks_shared_presentation(self):
        self.block()
        original = self.world.render

        def failure(q):
            original(q)
            raise Refusal("E_CREO", "controlled error after exporting the JPEG")

        args = ("artifact", "render", "--model", "block.prt", "--output", "failed.jpg")
        with patch.object(self.world, "render", side_effect=failure):
            pre = self.cli(*args, "--dry-run")["data"]
            code, result = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0)
        receipt = result["error"]["details"]["receipt"]
        self.assertTrue(receipt["artifacts"])
        self.assertEqual(receipt["outcome"]["change"], "not_applied")
        ident = pre["preview"]["operation_id"]
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "partial")
        self.world.part("other.prt")
        # Selecting another eligible window cannot bypass unresolved presentation effects.
        self.world.active = "other.prt"
        self.cli(
            "artifact",
            "render",
            "--model",
            "other.prt",
            "--output",
            "other.jpg",
            "--dry-run",
            status=6,
        )

    def test_unreadable_after_state_is_unknown_even_with_file(self):
        self.block()
        render, getter = self.world.render, self.world.render_state
        state = {"written": False}

        def unreadable(q):
            if state["written"]:
                raise Refusal("E_CREO", "controlled context getter failure")
            return getter(q)

        def rendered(q):
            result = render(q)
            state["written"] = True
            return result

        args = ("artifact", "render", "--model", "block.prt", "--output", "unknown.jpg")
        with (
            patch.object(self.world, "render", side_effect=rendered),
            patch.object(self.world, "render_state", side_effect=unreadable),
        ):
            pre = self.cli(*args, "--dry-run")["data"]
            _, result = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertTrue(result["error"]["details"]["receipt"]["artifacts"])

    def test_wrong_dimensions_or_decode_failure_never_publish(self):
        self.block()
        for decoded in (False, True):
            with self.subTest(decoded=decoded):
                args = (
                    "artifact",
                    "render",
                    "--model",
                    "block.prt",
                    "--output",
                    str(decoded) + ".jpg",
                )
                with patch.object(
                    self.world,
                    "inspect_jpeg",
                    return_value={
                        "decoded": decoded,
                        "width": 1,
                        "height": 1,
                        "sampled_rgb_range": 1,
                    },
                ):
                    pre = self.cli(*args, "--dry-run")["data"]
                    code, _ = invoke(self, *args, "--confirm", pre["confirm_token"])
                self.assertNotEqual(code, 0)
                self.assertFalse((self.ws / (str(decoded) + ".jpg")).exists())
                self.cli(
                    "operation",
                    "resolve",
                    "--id",
                    pre["preview"]["operation_id"],
                    "--outcome",
                    "partial",
                    "--evidence",
                    "fixture image is invalid; no replay",
                )

    def test_inconsistent_modified_readback_preserves_unknown_persistence(self):
        self.block()
        original, render = self.world.render_state, self.world.render
        written = [False]

        def context(q):
            result = original(q)
            if written[0]:
                result["modified"] = False  # Model show independently still reports dirty.
            return result

        def apply(q):
            result = render(q)
            written[0] = True
            return result

        args = ("artifact", "render", "--model", "block.prt", "--output", "mixed.jpg")
        with (
            patch.object(self.world, "render_state", side_effect=context),
            patch.object(self.world, "render", side_effect=apply),
        ):
            pre = self.cli(*args, "--dry-run")["data"]
            _, result = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        receipt = result["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertTrue(receipt["artifacts"])
        self.assertFalse((self.ws / "mixed.jpg").exists())
