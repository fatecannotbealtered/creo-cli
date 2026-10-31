"""Public loopback evidence separates a view flag from assembly-instruction acceptance."""

import copy
import unittest
from unittest.mock import patch

from creo_cli import core, registry
from tests import test_assemblies as assembly_cases
from tests import test_exploded_view_readback as view_cases
from tests.fixture import Refused
from tests.test_commands import Base, domain_preview, domain_receipt
from tests.test_explosion_context_r33 import source
from tests.test_round7_closeout import invoke


class ViewAcceptanceSchema(unittest.TestCase):
    def test_actual_validator_rejects_false_engineering_acceptance_captions(self):
        command = next(c for c in registry.COMMANDS if c.path == "drawing view add")
        schema = command.output["properties"]["result"]["properties"]["view_acceptance_scope"][
            "properties"
        ]["engineering_acceptance"]
        core.validate_schema("not_established_by_this_command", schema)
        for value in ("complete", True, None, "passed", {}, []):
            with self.subTest(value=value):
                with self.assertRaises(core.Error) as caught:
                    core.validate_schema(value, schema)
                self.assertEqual(caught.exception.code, "E_INTEGRITY")


class PublicViewSemantics(Base):
    args = view_cases.ExplodedViewReadback.args

    def setUp(self):
        super().setUp()
        assembly = self.part("support.asm")
        assembly["exploded_states"] = [copy.deepcopy(source()["explosion"]["states"][0])]
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

    def check_scope(self, scope):
        self.assertEqual(
            scope["required_independent_checks"],
            ["new_native_view_identity", "view_model", "view_sheet", "view_exploded_boolean"],
        )
        self.assertEqual(scope["engineering_acceptance"], "not_established_by_this_command")
        self.assertEqual(
            scope["not_checked"],
            [
                "per_view_named_exploded_state_identity",
                "actual_separated_projection",
                "independent_normal_assembly_placement",
                "global_assembly_display_across_drawing_context",
            ],
        )
        self.assertIn("observed reading contexts", scope["source_snapshot_comparison"])
        self.assertIn("does not prove", scope["boolean_meaning"])

    def test_preview_exposes_boolean_only_scope_and_context_bound_snapshot_protection(self):
        preview = domain_preview(self.cli(*self.args(), "--dry-run")["data"]["preview"])
        self.check_scope(preview["view_acceptance_scope"])
        self.assertNotIn("normal assembly placement is protected", str(preview))
        self.assertIn("frozen precondition", preview["exploded_state"]["source"])
        self.assertIn(
            "independent_normal_assembly_placement",
            preview["source_protection_contract"]["not_checked"],
        )
        self.assertNotIn("drawing.add-view", self.world.ops())

    def test_true_native_boolean_retains_unproved_engineering_scope_in_receipt_and_history(self):
        raw = self.gated(*self.args())["data"]
        out = domain_receipt(raw.get("receipt", raw))
        self.checks_pass(out)
        scope = out["result"]["view_acceptance_scope"]
        self.check_scope(scope)
        self.assertEqual(out["verification"]["view_acceptance_scope"], scope)
        for limit in scope["not_checked"]:
            self.assertIn(limit, out["verification"]["not_checked"])
        self.assertTrue(out["result"]["view"]["exploded_display_readback"]["value"])
        self.assertIn("exploded_source_before", out["result"])
        self.assertIn("exploded_source_after", out["result"])
        before = len(self.world.events)
        local = self.cli("operation", "show", "--id", out["operation_id"])["data"]
        self.assertEqual(len(self.world.events), before)
        self.assertIn("not_established_by_this_command", str(local))

    def test_false_native_flag_still_fails_and_retains_limits_without_replay(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.drawing_add_view

        def false_view(request):
            reply = original(request)
            self.world.models["instructions.drw"]["views"][-1]["exploded"] = False
            return reply

        with patch.object(self.world, "drawing_add_view", side_effect=false_view):
            code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "E_VERIFY_FAILED")
        retained = domain_receipt(out["error"]["details"]["receipt"])
        self.check_scope(retained["result"]["view_acceptance_scope"])
        checks = {c["check"]: c["passed"] for c in retained["verification"]["checks"]}
        self.assertIs(checks["exploded_display_as_requested"], False)
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_source_pending_retains_scope_and_absence_without_another_cad_dispatch(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def pending(op, request):
            if (
                op == "model.show"
                and request["model"] == "support.asm"
                and "drawing.add-view" in self.world.succeeded
            ):
                raise Refused("E_UNAVAILABLE", "source read still running", started=True)
            return original(op, request)

        before = len(self.world.events)
        with patch.object(self.world, "op", side_effect=pending):
            code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        details = out["error"]["details"]
        self.assertEqual(details["native_read_error"]["code"], "E_NATIVE_READ_PENDING")
        retained = domain_receipt(details["receipt"])["result"]
        self.check_scope(retained["view_acceptance_scope"])
        self.assertIsNone(retained["exploded_source_after"])
        self.assertEqual(retained["exploded_source_readback"]["after_status"], "not_returned")
        events = self.world.events[before:]
        dispatched = next(i for i, (op, _) in enumerate(events) if op == "drawing.add-view")
        self.assertEqual([op for op, _ in events[dispatched + 1 :]], ["model.show", "model.show"])
        self.assertEqual(self.world.ops().count("drawing.add-view"), 1)

    def test_true_flag_cannot_hide_changed_source_fields(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.drawing_add_view

        def changed_source(request):
            reply = original(request)
            self.world.models["support.asm"]["volume"] += 0.000001
            return reply

        with patch.object(self.world, "drawing_add_view", side_effect=changed_source):
            code, out = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "E_VERIFY_FAILED")
        retained = domain_receipt(out["error"]["details"]["receipt"])
        checks = {c["check"]: c["passed"] for c in retained["verification"]["checks"]}
        self.assertIs(checks["exploded_source_snapshot_preserved"], False)
        self.assertIs(checks["exploded_display_as_requested"], True)
        self.check_scope(retained["result"]["view_acceptance_scope"])

    def test_public_parameter_does_not_claim_automatic_named_state_selection(self):
        command = self.cli("reference", "--command", "drawing view add")["data"]["command"]
        description = next(p["description"] for p in command["params"] if p["name"] == "exploded")
        self.assertNotIn("drawn in its active exploded state", description)
        self.assertIn("does not select or prove", description)

    def test_empty_active_moves_refuse_profile_without_predicting_view_projection(self):
        self.world.models["support.asm"]["exploded_states"][0]["moves"] = []
        out = self.cli(*self.args(), "--dry-run", status=2)
        self.assertEqual(out["error"]["code"], "E_VALIDATION")
        self.assertIn("precondition has no translation moves", out["error"]["message"])
        self.assertNotIn("show it assembled", out["error"]["message"])
        self.assertNotIn("drawing.add-view", self.world.ops())


class PublicAssemblySemantics(assembly_cases.AssemblyParts):
    gearbox = assembly_cases.ExplodedStates.gearbox

    def test_assembly_preview_and_normal_checks_limit_their_evidence_claim(self):
        ids = self.gearbox()
        args = (
            "assembly",
            "explode",
            "apply",
            "--model",
            "gearbox.asm",
            "--request",
            self.request(
                {
                    "units": "mm",
                    "name": "OWNED",
                    "moves": [
                        {"components": [ids["pin.prt"]], "direction": [0, 0, 1], "distance": 35}
                    ],
                },
                "normal-scope.json",
            ),
        )
        pre = self.cli(*args, "--dry-run")["data"]
        preview = domain_preview(pre["preview"])
        self.assertIn("not independently", preview["normal_placement_check"])
        self.assertNotIn("drawing add-view --exploded draws it so", preview["effect"])
        self.assertIn("per-view named-state selection", preview["effect"])
        raw = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        result = domain_receipt(raw.get("receipt", raw))
        self.checks_pass(result)
        checks = {c["check"]: c for c in result["verification"]["checks"]}
        for key in (
            "native_normal_placement_unchanged",
            "placement_and_display_translations_consistent",
        ):
            self.assertIn("not independent", checks[key]["scope"])
        self.assertIn(
            "independent_normal_assembly_placement", result["verification"]["not_checked"]
        )
