"""Named-state replacement identity through the public CLI and isolated HTTP fixture."""

import copy
import json
from pathlib import Path
from unittest.mock import patch

from tests import test_assemblies as assembly_cases
from tests.test_round7_closeout import invoke


class ExplodeIdentity(assembly_cases.AssemblyParts):
    gearbox = assembly_cases.ExplodedStates.gearbox

    def arguments(self, *, existing=True):
        self.ids = self.gearbox()
        request = {
            "units": "mm",
            "name": "OWNED",
            "moves": [
                {
                    "components": [self.ids["pin.prt"]],
                    "direction": [0, 0, 1],
                    "distance": 30,
                }
            ],
        }
        path = self.request(request, "explode.json")
        args = ("assembly", "explode", "apply", "--model", "gearbox", "--request", path)
        if existing:
            self.gated(*args)
            request["replace"] = True
            request["moves"][0]["distance"] = 60
            path.write_text(json.dumps(request), encoding="utf-8")
        return args

    def target(self):
        return next(
            s
            for s in self.world.states_of(self.world.models["gearbox.asm"])
            if s["name"] == "OWNED"
        )

    def count(self):
        return self.world.ops().count("assembly.explode")

    def corrupt_after_dispatch(self, mutation, check):
        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.assembly_explode

        def corrupt(q):
            result = original(q)
            mutation(self.target())
            return result

        prior = self.count()
        with patch.object(self.world, "assembly_explode", side_effect=corrupt):
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0, out)
        failed = out["error"]["details"]["failed_checks"]
        self.assertIn(check, [c["check"] for c in failed])
        self.assertEqual(self.count(), prior + 1)
        repeat = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(repeat["error"]["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.count(), prior + 1)
        receipt = out["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "failed")
        self.assertEqual(receipt["failed_stage"], "verify")
        return out

    def test_same_name_and_moves_cannot_substitute_another_native_state_id(self):
        def changed_id(state):
            state["id"] += 100

        self.corrupt_after_dispatch(changed_id, "existing_state_identity_preserved")

    def test_same_id_name_and_moves_cannot_change_default_identity(self):
        self.corrupt_after_dispatch(
            lambda state: state.update(is_default=True), "existing_state_identity_preserved"
        )

    def incomplete_post_identity(self, field, value=None, *, missing=False):
        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        prior = self.count()
        original = self.world.summary

        def unreadable(name, model):
            result = original(name, model)
            if name == "gearbox.asm" and self.count() > prior:
                result = copy.deepcopy(result)
                state = next(s for s in result["explosion"]["states"] if s["name"] == "OWNED")
                if missing:
                    state.pop(field)
                else:
                    state[field] = value
            return result

        with patch.object(self.world, "summary", side_effect=unreadable):
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0, out)
        details = out["error"]["details"]
        receipt = details["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        self.assertEqual(receipt["failed_stage"], "verify")
        self.assertIn(
            "postconditions_read_back_independently",
            [item["id"] for item in receipt["outcome"]["verification"]["not_checked"]],
        )
        self.assertNotIn("native_read_error", details)
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.count(), prior + 1)

    def test_missing_independent_default_readback_is_incomplete(self):
        self.incomplete_post_identity("is_default", missing=True)

    def test_null_independent_default_readback_is_incomplete(self):
        self.incomplete_post_identity("is_default")

    def test_non_boolean_independent_default_readback_is_incomplete(self):
        self.incomplete_post_identity("is_default", "false")

    def test_missing_independent_id_readback_is_incomplete(self):
        self.incomplete_post_identity("id", missing=True)

    def test_unreadable_default_identity_refuses_preview_without_dispatch(self):
        args = self.arguments()
        self.target().pop("is_default")
        prior = self.count()
        out = self.cli(*args, "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(self.count(), prior)

    def test_in_place_edit_has_explicit_identity_and_mass_property_scope(self):
        args = self.arguments()
        frozen = copy.deepcopy(self.target())
        pre = self.cli(*args, "--dry-run")["data"]
        prior = self.count()
        data = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        checks = {c["check"]: c for c in data["verification"]["checks"]}
        check = checks["existing_state_identity_preserved"]
        self.assertTrue(check["passed"])
        self.assertEqual(check["expected"], {"id": str(frozen["id"]), "is_default": False})
        self.assertEqual(check["observed"], check["expected"])
        mass = checks["physical_geometry_unchanged"]
        self.assertEqual(mass["expected"], mass["observed"])
        self.assertEqual(mass["source"], "independent model.show mass_properties")
        self.assertIn("mass properties only", mass["scope"])
        self.assertEqual(self.target()["id"], frozen["id"])
        self.assertIs(self.target()["is_default"], False)
        self.assertEqual(self.target()["moves"][0]["distance"], 60)
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.count(), prior + 1)

    def test_wrong_component_target_and_wrong_assembly_refuse_without_dispatch(self):
        args = self.arguments(existing=False)
        path = Path(args[-1])
        request = json.loads(path.read_text())
        request["moves"][0]["components"] = ["999999"]
        path.write_text(json.dumps(request), encoding="utf-8")
        prior = self.count()
        out = self.cli(*args, "--dry-run", status=3)
        self.assertEqual(out["error"]["code"], "E_NOT_FOUND")
        wrong_model = list(args)
        wrong_model[4] = "foreign.asm"
        out = self.cli(*wrong_model, "--dry-run", status=3)
        self.assertEqual(out["error"]["code"], "E_NOT_FOUND")
        self.assertEqual(self.count(), prior)

    def test_stale_state_id_refuses_confirmation_without_dispatch(self):
        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        self.target()["id"] += 100
        prior = self.count()
        out = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(out["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.count(), prior)

    def test_extra_occurrence_after_preview_refuses_without_dispatch(self):
        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        rows = self.world.models["gearbox.asm"]["components"]
        extra = copy.deepcopy(rows[0])
        extra["id"] = 999
        rows.append(extra)
        prior = self.count()
        out = self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(out["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.count(), prior)

    def test_unrelated_normal_constraint_change_is_not_an_identity_success(self):
        def altered(_state):
            self.world.models["gearbox.asm"]["components"][0]["constraints"][0]["offset"] = 7

        self.corrupt_after_dispatch(altered, "placement_and_display_translations_consistent")

    def test_extra_occurrence_after_dispatch_is_rejected(self):
        def added(_state):
            rows = self.world.models["gearbox.asm"]["components"]
            extra = copy.deepcopy(rows[0])
            extra["id"] = 999
            rows.append(extra)

        self.corrupt_after_dispatch(added, "placement_and_display_translations_consistent")

    def test_pending_verification_keeps_same_client_stop_and_zero_replay(self):
        args = self.arguments()
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.assembly_explode

        def pending(q):
            result = original(q)
            self.world.overrun = "model.show"
            return result

        prior = self.count()
        events_before = len(self.world.events)
        with patch.object(self.world, "assembly_explode", side_effect=pending):
            code, out = invoke(self, *args, "--confirm", pre["confirm_token"])
        self.assertNotEqual(code, 0, out)
        self.assertEqual(out["error"]["code"], "E_OUTCOME_UNKNOWN")
        pending_error = out["error"]["details"]["native_read_error"]
        self.assertEqual(pending_error["code"], "E_NATIVE_READ_PENDING")
        self.assertEqual(pending_error["details"]["operation"], "model.show")
        self.assertEqual(pending_error["details"]["dispatch_state"], "started")
        self.assertIn("stop further CAD dispatch", out["error"]["details"]["next_action"])
        receipt = out["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        tail = self.world.ops()[events_before:]
        dispatched = tail.index("assembly.explode")
        self.assertEqual(tail[dispatched + 1 :], ["model.show"])
        self.assertEqual(self.count(), prior + 1)
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.count(), prior + 1)
