"""Context admission and the exact, limited drawing-source protection projection."""

import copy
import unittest
from unittest.mock import patch

from creo_cli import presentation
from creo_cli.core import Error
from tests import test_exploded_view_readback as view_cases
from tests.fixture import Refused
from tests.test_commands import Base
from tests.test_round7_closeout import invoke


def source(*, drawing=False):
    current = "instructions.drw" if drawing else "support.asm"
    kind = "drawing" if drawing else "assembly"
    return {
        "model": "support.asm",
        "components": [{"id": "41", "position": {"origin": [0, 0, 30]}}],
        "exploded_states": [{"id": "40", "name": "APART"}],
        "explosion": {
            "complete": True,
            "is_exploded": None if drawing else True,
            "active_state_id": "40",
            "states": [
                {
                    "id": "40",
                    "name": "APART",
                    "active": True,
                    "is_default": False,
                    "moves": [
                        {
                            "type": "translate",
                            "components": ["41"],
                            "component_paths": [["41"]],
                            "direction": [0, 0, 1],
                            "distance": 30,
                        }
                    ],
                }
            ],
            "context": {
                "complete": True,
                "kind": kind,
                "assembly_context_admitted": not drawing,
                "target_model": "support.asm",
                "current_model": current,
                "current_model_type": kind,
                "window_id": "7",
                "window_model": current,
                "window_model_type": kind,
                "source": "Session.GetCurrentModel/GetCurrentWindow; "
                "Window.GetModel; Model.GetType/GetFileName",
            },
            "display_readback": {
                "complete": not drawing,
                "status": "not_checked" if drawing else "observed",
                "value": None if drawing else True,
                "source": "Assembly.GetIsExploded",
                **(
                    {"reason": "not_applicable_in_drawing_context; GetIsExploded not called"}
                    if drawing
                    else {}
                ),
            },
            "source": "state getters",
        },
    }


class ContextAdmission(unittest.TestCase):
    def test_review_non_native_context_source_is_rejected(self):
        model = source()
        model["explosion"]["context"]["source"] = "snapshot default"
        with self.assertRaises(Error):
            presentation.explosion(model)

    def test_review_invalid_window_id_is_rejected(self):
        for value in (False, {}, "unknown", "-1", "01", "2147483648", 0):
            with self.subTest(window_id=value):
                model = source()
                model["explosion"]["context"]["window_id"] = value
                with self.assertRaises(Error):
                    presentation.explosion(model)

    def test_review_window_zero_remains_valid(self):
        model = source()
        model["explosion"]["context"]["window_id"] = "0"
        self.assertIs(presentation.explosion(model), model["explosion"])

    def test_review_complete_inventory_with_explicit_error_is_rejected(self):
        model = source()
        model["explosion"]["error"] = {"stage": "active.GetId", "exception_class": "XToolkit"}
        with self.assertRaises(Error):
            presentation.explosion(model)

    def test_drawing_inventory_is_complete_but_not_normal_placement_evidence(self):
        model = source(drawing=True)
        state = presentation.explosion(model, drawing_inventory=True)
        self.assertIsNone(state["is_exploded"])
        with self.assertRaises(Error):
            presentation.explosion(model)
        with self.assertRaises(Error):
            presentation.normal_components(model["components"], state)

    def test_unknown_contradiction_failure_and_missing_provenance_are_incomplete(self):
        mutations = (
            lambda e: e.pop("context"),
            lambda e: e["context"].update(complete=False),
            lambda e: e["context"].update(window_model="foreign.asm"),
            lambda e: e["context"].update(kind="unknown"),
            lambda e: e["context"].update(error={"exception_class": "XToolkit"}),
            lambda e: e["display_readback"].update(complete=False, value=None),
            lambda e: e["display_readback"].update(error={"exception_class": "XToolkit"}),
            lambda e: e["states"][0].pop("is_default"),
            lambda e: e["states"][0]["moves"][0].update(component_paths=[]),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                model = source()
                mutate(model["explosion"])
                with self.assertRaises(Error) as caught:
                    presentation.explosion(model, drawing_inventory=True)
                self.assertEqual(caught.exception.code, "E_VERIFY_INCOMPLETE")

    def test_projection_excludes_only_context_display_fields_and_preserves_raw(self):
        a, b = source(), source(drawing=True)
        frozen = copy.deepcopy((a, b))
        self.assertEqual(presentation.drawing_source(a), presentation.drawing_source(b))
        self.assertEqual((a, b), frozen)
        mutations = (
            lambda m: m["components"][0]["position"]["origin"].__setitem__(0, 0.000001),
            lambda m: m["components"][0].update(constraints=[{"type": "changed"}]),
            lambda m: m["exploded_states"][0].update(id="999"),
            lambda m: m["explosion"]["states"][0].update(id="999", active=False),
            lambda m: m["explosion"]["states"][0].update(is_default=True),
            lambda m: m["explosion"]["states"][0]["moves"][0].update(distance=31),
            lambda m: m.update(modified=True),
        )
        for mutate in mutations:
            model = copy.deepcopy(b)
            mutate(model)
            with self.subTest(model=model):
                try:
                    projected = presentation.drawing_source(model)
                except Error:
                    continue
                self.assertNotEqual(presentation.drawing_source(a), projected)


class PublicDrawingContext(Base):
    args = view_cases.ExplodedViewReadback.args

    def setUp(self):
        super().setUp()
        model = self.part("support.asm")
        state = source()["explosion"]["states"][0]
        model["exploded_states"] = [copy.deepcopy(state)]
        model["is_exploded"] = True
        model["components"] = []
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

    def test_context_only_change_survives_confirm_and_keeps_raw_evidence(self):
        self.world.active = "support.asm"
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.drawing_add_view

        def created(q):
            result = original(q)
            self.world.active = "instructions.drw"
            return result

        with patch.object(self.world, "drawing_add_view", side_effect=created):
            out = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.checks_pass(out)
        self.assertTrue(out["result"]["exploded_source_before"]["explosion"]["is_exploded"])
        self.assertIsNone(out["result"]["exploded_source_after"]["explosion"]["is_exploded"])
        self.assertIn(
            "global_assembly_display_across_drawing_context", out["verification"]["not_checked"]
        )
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_drawing_context_then_assembly_readback_protects_state_and_real_view_flag(self):
        self.world.active = "instructions.drw"
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.drawing_add_view

        def created(q):
            result = original(q)
            self.world.active = "support.asm"
            return result

        with patch.object(self.world, "drawing_add_view", side_effect=created):
            out = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.checks_pass(out)
        self.assertTrue(out["result"]["exploded_source_after"]["explosion"]["is_exploded"])

    def test_same_context_engineering_drift_refuses_without_dispatch(self):
        for key, value in (("id", "999"), ("is_default", True)):
            with self.subTest(key=key):
                self.world.active = "instructions.drw"
                args = self.args(name=key.upper())
                before = copy.deepcopy(self.world.models["support.asm"]["exploded_states"])
                preview = self.cli(*args, "--dry-run")["data"]
                self.world.models["support.asm"]["exploded_states"][0][key] = value
                code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
                self.assertNotEqual(code, 0)
                self.assertEqual(self.world.ops().count("drawing.add-view"), 0)
                self.world.models["support.asm"]["exploded_states"] = before

    def test_old_service_plain_read_survives_but_exploded_write_gates_before_cad(self):
        self.world.capabilities.pop("assembly_explosion_context_readback")
        self.cli("model", "show", "--model", "support.asm")
        before = len(self.world.events)
        out = self.cli(*self.args(), "--dry-run", status=4)
        self.assertEqual(out["error"]["code"], "E_BACKEND_UNAVAILABLE")
        self.assertEqual(self.world.events[before:], [])

    def test_unknown_or_contradictory_context_cannot_authorize_drawing(self):
        model = self.world.models["support.asm"]
        model["explosion_context"] = {"complete": False, "kind": "unknown"}
        out = self.cli(*self.args(), "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("drawing.add-view", self.world.ops())

    def test_review_returned_incomplete_source_is_retained_in_original_receipt(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def incomplete(op, request):
            result = original(op, request)
            if (
                op == "model.show"
                and request["model"] == "support.asm"
                and "drawing.add-view" in self.world.succeeded
            ):
                result = copy.deepcopy(result)
                result["explosion"]["complete"] = False
                result["returned_failure_marker"] = "independent_after_must_survive"
            return result

        before = len(self.world.events)
        with patch.object(self.world, "op", side_effect=incomplete):
            code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        receipt = out["error"]["details"]["receipt"]
        retained = receipt["extensions"]["creo"]["domain_result"]
        self.assertIn("exploded_source_before", retained)
        self.assertEqual(
            retained["exploded_source_after"]["returned_failure_marker"],
            "independent_after_must_survive",
        )
        metadata = retained["exploded_source_readback"]
        self.assertEqual(metadata["source"], "independent model.show")
        self.assertEqual(metadata["after_status"], "returned")
        self.assertEqual(metadata["qualification"], "incomplete")
        self.assertEqual(metadata["validation_error"]["code"], "E_VERIFY_INCOMPLETE")
        local = self.cli("operation", "show", "--id", receipt["operation_id"])
        self.assertIn("independent_after_must_survive", str(local))
        events = self.world.events[before:]
        dispatched = next(i for i, (op, _) in enumerate(events) if op == "drawing.add-view")
        source_reads = [
            q
            for op, q in events[dispatched + 1 :]
            if op == "model.show" and q["model"] == "support.asm"
        ]
        self.assertEqual(len(source_reads), 1)
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_review_source_pending_retains_absence_and_original_read_context_without_more_cad(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def pending(op, request):
            if (
                op == "model.show"
                and request["model"] == "support.asm"
                and "drawing.add-view" in self.world.succeeded
            ):
                raise Refused(
                    "E_UNAVAILABLE", "source getter started and has not returned", started=True
                )
            return original(op, request)

        before = len(self.world.events)
        with patch.object(self.world, "op", side_effect=pending):
            code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        details = out["error"]["details"]
        receipt = details["receipt"]
        raw = receipt["extensions"]["creo"]["domain_result"]
        self.assertIsNone(raw["exploded_source_after"])
        retained = raw["exploded_source_readback"]
        self.assertEqual(retained["after_status"], "not_returned")
        self.assertEqual(retained["qualification"], "not_checked")
        self.assertEqual(retained["read_error"], details["native_read_error"])
        error = retained["read_error"]
        self.assertEqual(error["code"], "E_NATIVE_READ_PENDING")
        self.assertEqual(error["details"]["operation"], "model.show")
        self.assertEqual(error["details"]["cause_code"], "E_UNAVAILABLE")
        self.assertEqual(error["details"]["dispatch_state"], "started")
        self.assertTrue(error["details"]["cli_invocation_id"])
        self.assertNotIn("diagnostic_request_id", error["details"])
        self.assertIn("stop further CAD dispatch", details["next_action"])
        events = self.world.events[before:]
        dispatched = next(i for i, (op, _) in enumerate(events) if op == "drawing.add-view")
        self.assertEqual([op for op, _ in events[dispatched + 1 :]], ["model.show", "model.show"])
        stopped = len(self.world.events)
        local = self.cli("operation", "show", "--id", receipt["operation_id"])
        self.assertIn("not_returned", str(local))
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(len(self.world.events), stopped)
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def assembly_args(self):
        self.part("plate.prt")
        self.world.models["support.asm"]["components"] = [
            {
                "id": "41",
                "model": "plate.prt",
                "status": "FEAT_ACTIVE",
                "placed": True,
                "packaged": False,
                "underconstrained": False,
                "constraints": [],
                "position": {
                    "origin": [0, 0, 0],
                    "x_axis": [1, 0, 0],
                    "y_axis": [0, 1, 0],
                    "z_axis": [0, 0, 1],
                },
            }
        ]
        request = self.request(
            {
                "units": "mm",
                "name": "NEW_APART",
                "moves": [{"components": ["41"], "direction": [0, 0, 1], "distance": 35}],
            },
            "explode-context.json",
        )
        return "assembly", "explode", "apply", "--model", "support.asm", "--request", request

    def test_assembly_write_refuses_drawing_context_without_native_write(self):
        args = self.assembly_args()
        self.world.active = "instructions.drw"
        out = self.cli(*args, "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("assembly.explode", self.world.ops())

    def test_old_service_assembly_write_gates_before_cad(self):
        args = self.assembly_args()
        self.world.capabilities.pop("assembly_explosion_context_readback")
        before = len(self.world.events)
        self.cli(*args, "--dry-run", status=4)
        self.assertEqual(self.world.events[before:], [])
