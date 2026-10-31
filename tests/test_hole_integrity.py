"""Complete simple through-hole intent through the public CLI and fresh recovery processes."""

import math
from unittest.mock import patch

import tests.test_machining_review as review
from tests.test_features import Built


class HoleIntegrity(Built):
    hole_request = review.MachiningReview.hole_request
    args = review.MachiningReview.args
    fresh = review.MachiningReview.fresh
    lost_hole = review.MachiningReview.lost_hole
    refuse_false_applied = review.MachiningReview.refuse_false_applied

    def test_edge_and_tangent_footprints_refuse_for_face_and_infinite_datum(self):
        self.block()
        for placement in (self.top()["ref"], "FRONT"):
            for x in (-20, -19, 17, 19, 20):
                with self.subTest(placement=placement, x=x):
                    q = self.hole_request()
                    q["placement"]["surface"] = placement
                    q["placement"]["offsets"][0]["distance"] = x
                    error = self.cli(*self.args("hole", q), "--dry-run", status=2)["error"]
                    self.assertEqual(error["code"], "E_VALIDATION")
        self.assertNotIn("feature.hole", self.world.ops())

    @staticmethod
    def partial_wall(model, ident, volume_before):
        for surface in model["geometry"]:
            if (
                str(surface.get("feature", {}).get("id")) == str(ident)
                and surface.get("type") == "cylinder"
            ):
                height = surface["bbox"][1][2] - surface["bbox"][0][2]
                surface["area"] = math.pi * surface["radius"] * height
        model["volume"] = volume_before - (volume_before - model["volume"]) / 2

    def test_correct_axis_radius_and_extent_do_not_prove_complete_wall(self):
        model = self.block()
        words = self.args("hole", self.hole_request())
        preview = self.cli(*words, "--dry-run")["data"]
        original = self.world.hole

        def changed(q):
            before = model["volume"]
            reply = original(q)
            self.partial_wall(model, reply["feature"]["id"], before)
            return reply

        with patch.object(self.world, "hole", side_effect=changed):
            error = self.cli(*words, "--confirm", preview["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_partial_wall_after_lost_reply_cannot_be_registered_applied(self):
        ident, _ = self.lost_hole(self.partial_wall)
        self.refuse_false_applied(ident)

    def test_missing_wall_area_after_lost_reply_remains_unresolved(self):
        def missing(model, ident, before):
            for surface in model["geometry"]:
                if str(surface.get("feature", {}).get("id")) == str(ident):
                    surface.pop("area", None)

        ident, _ = self.lost_hole(missing)
        self.refuse_false_applied(ident)
        shown = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        self.assertEqual(shown["observation"]["machining_verification"]["can_register"], [])

    def test_missing_rim_with_full_area_and_cut_volume_cannot_be_registered_applied(self):
        def missing(model, ident, before):
            model["geometry"] = [
                g
                for g in model["geometry"]
                if not (
                    g.get("kind") == "edge" and str(g.get("feature", {}).get("id")) == str(ident)
                )
            ]

        ident, _ = self.lost_hole(missing)
        self.refuse_false_applied(ident)

    def test_positive_but_incomplete_cut_volume_cannot_be_registered_applied(self):
        def insufficient(model, ident, before):
            model["volume"] = before - (before - model["volume"]) / 2

        ident, _ = self.lost_hole(insufficient)
        self.refuse_false_applied(ident)

    def test_unreadable_rim_endpoint_keeps_unknown_without_query_crash(self):
        def unreadable(model, ident, before):
            for edge in model["geometry"]:
                if edge.get("kind") == "edge" and str(edge.get("feature", {}).get("id")) == str(
                    ident
                ):
                    edge["end"] = [None, None, None]

        ident, _ = self.lost_hole(unreadable)
        self.refuse_false_applied(ident)
        shown = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        self.assertEqual(shown["observation"]["machining_verification"]["can_register"], [])
