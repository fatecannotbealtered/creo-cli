"""Public CLI regressions for reference identity, datum placement and recovery proof."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from tests.test_commands import ROOT
from tests.test_features import Built


class MachiningReview(Built):
    def hole_request(self, **changes):
        request = {
            "units": "mm",
            "name": "REVIEW_HOLE",
            "diameter": 6,
            "depth": "through_all",
            "placement": {
                "surface": self.top()["ref"],
                "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
            },
        }
        return request | changes

    def args(self, kind, request):
        return ("feature", kind, "--model", "block.prt", "--request", self.request(request))

    def test_mixed_edge_reference_is_canonical_through_confirmation(self):
        self.block()
        edge = self.edges([0, 0, -1])[0]["ref"]
        words = self.args("round", {"units": "mm", "radius": 1, "edges": [edge.upper()]})
        preview = self.cli(*words, "--dry-run")["data"]
        self.assertEqual(preview["preview"]["changes"][0]["after"]["edges"], [edge])
        actual = self.cli(*words, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(actual["result"]["native_definition"]["edges"], [edge])

    def test_mixed_surface_and_datum_references_reach_native_definition(self):
        self.block()
        q = self.hole_request()
        canonical = copy.deepcopy(q["placement"])
        q["placement"]["surface"] = q["placement"]["surface"].upper()
        q["placement"]["offsets"][0]["from"] = "right"
        q["placement"]["offsets"][1]["from"] = "ToP"
        result = self.gated(*self.args("hole", q))["data"]
        definition = result["result"]["native_definition"]
        self.assertEqual(definition["placement_surface"], canonical["surface"])
        self.assertEqual(definition["offsets"], canonical["offsets"])

    def test_datum_placement_does_not_require_a_finite_face_box(self):
        self.block()
        q = self.hole_request()
        q["placement"]["surface"] = "FRONT"
        result = self.gated(*self.args("hole", q))["data"]
        self.assertEqual(result["result"]["native_definition"]["placement_surface"], "FRONT")

    def test_mixed_datum_offsets_do_not_reach_case_sensitive_lookup(self):
        self.block()
        q = self.hole_request()
        q["placement"]["offsets"][0]["from"] = "right"
        q["placement"]["offsets"][1]["from"] = "ToP"
        self.gated(*self.args("hole", q))

    def test_datum_display_extent_does_not_clip_the_hole(self):
        model = self.block()
        plane = next(g for g in model["geometry"] if g["ref"] == "FRONT")
        plane["bbox"] = [[-0.1, -0.1, 0], [0.1, 0.1, 0]]
        q = self.hole_request()
        q["placement"]["surface"] = "FRONT"
        self.gated(*self.args("hole", q))

    def test_unknown_mixed_reference_is_explicit_and_zero_dispatch(self):
        self.block()
        q = self.hole_request()
        q["placement"]["surface"] = "SuRfAcE:999999"
        error = self.cli(*self.args("hole", q), "--dry-run", status=3)["error"]
        self.assertEqual(error["code"], "E_NOT_FOUND")
        self.assertNotIn("feature.hole", self.world.ops())

    def test_datum_surface_id_alias_resolves_to_the_actual_named_plane(self):
        model = self.block()
        datum = next(g for g in model["geometry"] if g["ref"] == "FRONT")
        q = self.hole_request()
        q["placement"]["surface"] = "SuRfAcE:" + str(datum["id"])
        result = self.gated(*self.args("hole", q))["data"]
        self.assertEqual(result["result"]["native_definition"]["placement_surface"], "FRONT")

    def test_datum_display_extent_can_change_but_plane_position_cannot(self):
        model = self.block()
        datum = next(g for g in model["geometry"] if g["ref"] == "FRONT")
        q = self.hole_request()
        q["placement"]["surface"] = "FRONT"
        words = self.args("hole", q)
        pre = self.cli(*words, "--dry-run")["data"]
        datum["bbox"] = [[-0.1, -0.1, 0], [0.1, 0.1, 0]]
        datum["area"] = 0.04
        self.cli(*words, "--confirm", pre["confirm_token"])
        q["name"] = "SECOND_HOLE"
        q["placement"]["offsets"][0]["distance"] = -10
        words = self.args("hole", q)
        pre = self.cli(*words, "--dry-run")["data"]
        datum["origin"][2] = 1
        self.cli(*words, "--confirm", pre["confirm_token"], status=6)

    def test_casing_only_request_file_change_still_invalidates_authorization(self):
        self.block()
        q = self.hole_request()
        words = self.args("hole", q)
        pre = self.cli(*words, "--dry-run")["data"]
        q["placement"]["offsets"][0]["from"] = "right"
        Path(words[-1]).write_text(json.dumps(q))
        self.cli(*words, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("feature.hole", self.world.ops())

    def fresh(self, *words, status=0):
        p = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, words)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(p.returncode, status, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def lost_hole(self, mutation=None):
        self.block()
        words = self.args("hole", self.hole_request())
        preview = self.cli(*words, "--dry-run")["data"]
        original = self.world.hole

        def altered(q):
            model = self.world.models["block.prt"]
            before = model["volume"]
            reply = original(q)
            if mutation:
                mutation(model, reply["feature"]["id"], before)
            return reply

        self.world.drop = "feature.hole"
        try:
            with patch.object(self.world, "hole", side_effect=altered):
                self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        finally:
            self.world.drop = None
        return preview["preview"]["operation_id"], words

    def refuse_false_applied(self, ident):
        with patch.dict(os.environ, self.env, clear=True):
            before = operations.get(ident)
        error = self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "feature getter and feature count look correct, but require independent solid proof",
            status=1,
        )["error"]
        self.assertIn(error["code"], ("E_VERIFY_FAILED", "E_VERIFY_INCOMPLETE"))
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(operations.get(ident), before)
        self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_phantom_hole_plus_lost_reply_cannot_be_registered_applied(self):
        def mutation(m, ident, before):
            m["geometry"] = [g for g in m["geometry"] if g.get("feature", {}).get("id") != ident]
            m["volume"] = before

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)

    def test_wrong_center_plus_lost_reply_cannot_be_registered_applied(self):
        def mutation(m, ident, before):
            for g in m["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident:
                    g["axis"]["origin"][0] += 2

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)

    def test_wrong_through_extent_plus_lost_reply_cannot_be_registered_applied(self):
        def mutation(m, ident, before):
            for g in m["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident:
                    g["bbox"][0][2] += 2

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)

    def test_wrong_axis_plus_lost_reply_cannot_be_registered_applied(self):
        def mutation(m, ident, before):
            for g in m["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident:
                    g["axis"]["direction"] = [1, 0, 0]

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)

    def test_wrong_hole_radius_plus_lost_reply_cannot_be_registered_applied(self):
        def mutation(m, ident, before):
            for g in m["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident:
                    g["radius"] = 2

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)

    def test_missing_axis_keeps_unknown_even_for_partial_registration(self):
        def mutation(m, ident, before):
            for g in m["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident:
                    g.pop("axis")

        ident, _ = self.lost_hole(mutation)
        self.refuse_false_applied(ident)
        error = self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "partial",
            "--evidence",
            "native current-solid axis is unavailable, so evidence is incomplete",
            status=1,
        )["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")

    def test_legitimate_lost_reply_uses_frozen_plan_without_request_file(self):
        ident, words = self.lost_hole()
        Path(words[-1]).unlink()
        observed = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")
        self.assertTrue(observed["data"]["observation"]["machining_verification"]["accepted"])
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "fresh solid geometry agrees with the retained center, axis, diameter "
            "and through extent",
        )
        self.fresh("model", "save", "--model", "block.prt", "--dry-run")
        self.assertEqual(self.world.ops().count("feature.hole"), 1)

    def lost_round(self, change):
        self.block()
        words = self.args("round", {"units": "mm", "radius": 1, "edges": [self.edges()[0]["ref"]]})
        original = self.world.edge_feature

        def altered(q, round_):
            reply = original(q, round_)
            for g in self.world.models["block.prt"]["geometry"]:
                if (
                    g.get("type") == "cylinder"
                    and g.get("feature", {}).get("id") == reply["feature"]["id"]
                ):
                    change(g)
            return reply

        pre = self.cli(*words, "--dry-run")["data"]
        self.world.drop = "feature.round"
        try:
            with patch.object(self.world, "edge_feature", side_effect=altered):
                self.cli(*words, "--confirm", pre["confirm_token"], status=6)
        finally:
            self.world.drop = None
        self.refuse_false_applied(pre["preview"]["operation_id"])

    def test_wrong_round_radius_plus_lost_reply_cannot_be_registered_applied(self):
        self.lost_round(lambda g: g.update(radius=2))

    def test_wrong_round_location_plus_lost_reply_cannot_be_registered_applied(self):
        def change(g):
            g["axis"]["origin"][2] += 3

        self.lost_round(change)

    def test_partial_round_extent_plus_lost_reply_cannot_be_registered_applied(self):
        def change(g):
            direction = g["axis"]["direction"]
            axis = max(range(3), key=lambda i: abs(direction[i]))
            g["bbox"][0][axis] = (g["bbox"][0][axis] + g["bbox"][1][axis]) / 2

        self.lost_round(change)

    def test_missing_round_extent_plus_lost_reply_cannot_be_registered_applied(self):
        self.lost_round(lambda g: g.pop("bbox"))
