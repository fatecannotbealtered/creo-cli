"""Frozen hole-volume policy: aggregate numerical residuals never replace solid proof."""

import copy
import math
import os
from unittest.mock import patch

import pytest

import tests.test_machining_review as review
from creo_cli import machining, operations
from creo_cli.core import Error
from tests.test_commands import RECT
from tests.test_features import Built

POLICY = {
    "mode": "bounded-total-v2",
    "version": 2,
    "units": "mm^3",
    "relative_tolerance": 1e-6,
    "absolute_floor": 1e-6,
    "hard_cap": 0.001,
}
# Retained R31 native bridge 006/007, operation 93c6d8de2898470bb870c2843ec9641b.
# The original error and complete independent native snapshots stay outside the repo.
NATIVE_BEFORE = 9600.0
NATIVE_AFTER = 9430.353751779296
REMOVAL = math.pi * 3**2 * 6


def scalar_case(before=NATIVE_BEFORE, after=NATIVE_AFTER, removed=REMOVAL):
    def model(volume):
        return {
            "units": {"length": "mm"},
            "mass_properties": {"volume": volume, "units": {"length": "mm", "volume": "mm^3"}},
        }

    baseline = {"model": model(before)}
    current = {"model": model(after), "geometry": {"items": []}}
    intent = {
        "center": [0, 0, 0],
        "axis": [0, 0, 1],
        "diameter": 6,
        "through_extent": {"axis": 2, "min": -6, "max": 0},
        "complete_through_hole": {
            "wall_area": 2 * math.pi * 3 * 6,
            "removed_volume": removed,
            "rim_length_each": 2 * math.pi * 3,
            "comparison_relative_tolerance": 1e-6,
            "comparison_absolute_tolerance": 1e-6,
            "volume_comparison": copy.deepcopy(POLICY),
            "volume_unit_evidence": {"length": "mm", "volume": "mm^3"},
        },
    }
    return baseline, intent, current


def volume_check(before, intent, after):
    # Scalar unit cases inspect this predicate only, never claim the empty geometry passes.
    return next(
        row
        for row in machining.complete_hole_checks(before, intent, after, [])
        if row["check"] == "complete_hole_removed_volume"
    )


def test_native_total_residual_obeys_explicit_frozen_v2():
    check = volume_check(*scalar_case())
    assert check["passed"] is True
    assert check["expected"] == REMOVAL
    assert check["observed"] == NATIVE_BEFORE - NATIVE_AFTER
    assert check["expected_after"] == NATIVE_BEFORE - REMOVAL
    assert check["actual_after"] == NATIVE_AFTER
    assert check["effective_budget"] == 0.001
    assert check["volume_policy"] == POLICY


def test_missing_policy_keeps_native_legacy_failure():
    before, intent, after = scalar_case()
    intent["complete_through_hole"].pop("volume_comparison")
    check = volume_check(before, intent, after)
    assert check["passed"] is False


@pytest.mark.parametrize("residual", [0.0015, 0.005])
def test_cap_rejects_residual_accepted_by_total_relative_budget(residual):
    check = volume_check(*scalar_case(after=NATIVE_BEFORE - REMOVAL - residual))
    assert check["passed"] is False
    assert check["relative_passed"] is True
    assert check["cap_passed"] is False


def test_relative_gate_rejects_even_inside_cap():
    check = volume_check(*scalar_case(before=1000, after=1000 - REMOVAL - 0.0009))
    assert check["passed"] is False
    assert check["relative_passed"] is False
    assert check["cap_passed"] is True


def test_hard_cap_compares_actual_residual_without_an_isclose_allowance():
    expected_after = NATIVE_BEFORE - REMOVAL
    at_boundary = expected_after - 0.001
    for actual in (math.nextafter(at_boundary, expected_after), math.nextafter(at_boundary, 0)):
        check = volume_check(*scalar_case(after=actual))
        residual = abs(actual - expected_after)
        assert check["cap_passed"] is (residual <= 0.001)
        assert check["passed"] is (residual <= 0.001)


@pytest.mark.parametrize(
    ("before", "after", "removed"),
    [
        (True, NATIVE_AFTER, REMOVAL),
        (NATIVE_BEFORE, False, REMOVAL),
        (NATIVE_BEFORE, NATIVE_AFTER, True),
        (math.nan, NATIVE_AFTER, REMOVAL),
        (NATIVE_BEFORE, math.inf, REMOVAL),
        (NATIVE_BEFORE, NATIVE_AFTER, math.nan),
        (0, NATIVE_AFTER, REMOVAL),
        (NATIVE_BEFORE, 0, REMOVAL),
        (NATIVE_BEFORE, NATIVE_AFTER, NATIVE_BEFORE),
        (NATIVE_BEFORE, NATIVE_AFTER, -1),
    ],
)
def test_invalid_or_unresolved_volume_signal_never_passes(before, after, removed):
    assert volume_check(*scalar_case(before, after, removed))["passed"] is False


def test_removal_not_above_effective_budget_cannot_be_full_proof():
    check = volume_check(*scalar_case(before=1, after=1 - 0.5e-6, removed=0.5e-6))
    assert check["passed"] is False
    assert check["removal_resolved"] is False


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        POLICY | {"mode": "unknown"},
        POLICY | {"version": 3},
        POLICY | {"units": "in^3"},
        POLICY | {"hard_cap": True},
    ],
)
def test_explicit_unknown_or_incomplete_policy_is_not_legacy(policy):
    before, intent, after = scalar_case()
    intent["complete_through_hole"]["volume_comparison"] = policy
    with pytest.raises(Error) as exc:
        volume_check(before, intent, after)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("missing", list(POLICY))
def test_no_new_policy_field_can_be_filled_from_current_defaults(missing):
    before, intent, after = scalar_case()
    intent["complete_through_hole"]["volume_comparison"].pop(missing)
    with pytest.raises(Error) as exc:
        volume_check(before, intent, after)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


def test_frozen_unit_evidence_is_required_as_well_as_policy_unit_label():
    before, intent, after = scalar_case()
    intent["complete_through_hole"].pop("volume_unit_evidence")
    with pytest.raises(Error) as exc:
        volume_check(before, intent, after)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize("fault", ["missing", "wrong-length", "wrong-volume"])
def test_v2_requires_actual_mass_property_unit_evidence(side, fault):
    before, intent, after = scalar_case()
    state = before if side == "before" else after
    if fault == "missing":
        state["model"]["mass_properties"].pop("units")
    else:
        key, value = ("length", "in") if fault == "wrong-length" else ("volume", "in^3")
        state["model"]["mass_properties"]["units"][key] = value
    with pytest.raises(Error) as exc:
        volume_check(before, intent, after)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


def test_non_mm_plan_does_not_receive_new_policy():
    before, intent, after = scalar_case()
    intent["complete_through_hole"].pop("volume_comparison")
    for state in (before, after):
        state["model"]["units"]["length"] = "in"
        state["model"]["mass_properties"]["units"] = {"length": "in", "volume": "in^3"}
    machining._freeze_hole_volume_policy({"units": "in"}, before, intent)
    assert "volume_comparison" not in intent["complete_through_hole"]
    assert volume_check(before, intent, after)["passed"] is False


class HoleVolumePolicy(Built):
    hole_request = review.MachiningReview.hole_request
    args = review.MachiningReview.args
    fresh = review.MachiningReview.fresh
    lost_hole = review.MachiningReview.lost_hole
    refuse_false_applied = review.MachiningReview.refuse_false_applied

    def block(self):
        self.part()
        self.world.active = "block.prt"
        request = copy.deepcopy(RECT)
        request["depth"] = 6
        request["sketch"]["profile"]["width"] = 80
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(request))
        model = self.world.models["block.prt"]
        # The generic fixture summary otherwise retains its default 40x20x10 bounds.
        model["bbox"] = [[-40, -10, -6], [40, 10, 0]]
        original = self.world.hole

        def fixture_through_hole(request):
            # The shared substitute assumes through_all=10. Honor this owned
            # fixture's actual 6mm extrusion without changing the product/service.
            if request["depth"] != "through_all":
                return original(request)
            reply = original(request | {"depth": 6})
            feature = next(f for f in model["features"] if f["id"] == reply["feature"]["id"])
            feature["native_definition"]["through_all"] = True
            return reply | {"depth": "through_all"}

        self.world.hole = fixture_through_hole
        return model

    def test_new_mm_preview_freezes_policy(self):
        self.block()
        preview = self.cli(*self.args("hole", self.hole_request()), "--dry-run")["data"]["preview"]
        intent = preview["base_snapshot"]["extensions"]["creo"]["observation"]["machining_intent"]
        assert intent["complete_through_hole"].get("volume_comparison") == POLICY

    def test_old_preview_cannot_confirm_after_new_policy_is_frozen(self):
        self.block()
        args = self.args("hole", self.hole_request())
        with patch.object(machining, "_freeze_hole_volume_policy", return_value=None):
            old = self.cli(*args, "--dry-run")["data"]
        error = self.cli(*args, "--confirm", old["confirm_token"], status=6)["error"]
        assert error["code"] == "E_CONFLICT"
        assert "feature.hole" not in self.world.ops()

    def test_unresolvable_tiny_removal_rejects_before_dispatch(self):
        self.block()
        diameter = math.sqrt(4 * 0.5e-6 / (math.pi * 6))
        result = self.cli(
            *self.args("hole", self.hole_request(diameter=diameter)), "--dry-run", status=2
        )
        assert result["error"]["code"] == "E_UNSUPPORTED"
        assert "feature.hole" not in self.world.ops()

    @staticmethod
    def native_residual(model, ident, before):
        assert before == NATIVE_BEFORE
        model["volume"] = NATIVE_AFTER

    def test_new_frozen_policy_is_reused_by_fresh_query(self):
        ident, _ = self.lost_hole(self.native_residual)
        result = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        proof = result["observation"]["machining_verification"]
        assert proof["accepted"] is True
        assert proof["intent"]["complete_through_hole"]["volume_comparison"] == POLICY

    def test_query_uses_retained_intent_without_reconstructing_current_defaults(self):
        ident, _ = self.lost_hole(self.native_residual)
        with patch.object(
            machining, "hole_intent", side_effect=AssertionError("must use frozen intent")
        ):
            result = self.cli("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        assert result["observation"]["machining_verification"]["accepted"] is True

    def edit_fixture_intent(self, ident, edit):
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            baseline = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
            edit(baseline)
            operations.update(run)
            return copy.deepcopy(run)

    def test_missing_entire_old_intent_can_only_reconstruct_legacy(self):
        ident, _ = self.lost_hole(self.native_residual)
        run = self.edit_fixture_intent(ident, lambda baseline: baseline.pop("machining_intent"))
        proof = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"][
            "observation"
        ]["machining_verification"]
        assert proof["accepted"] is False
        assert proof["can_register"] == ["partial"]
        assert "volume_comparison" not in proof["intent"]["complete_through_hole"]
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == run

    def test_explicit_null_intent_is_not_a_missing_legacy_intent(self):
        ident, _ = self.lost_hole(self.native_residual)
        run = self.edit_fixture_intent(
            ident, lambda baseline: baseline.update(machining_intent=None)
        )
        error = self.fresh("operation", "query", "--id", ident, "--model", "block.prt", status=1)[
            "error"
        ]
        assert error["code"] == "E_VERIFY_INCOMPLETE"
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == run

    def test_missing_frozen_model_units_cannot_be_derived_from_new_policy_label(self):
        ident, _ = self.lost_hole(self.native_residual)

        def missing(baseline):
            baseline["machining_before"]["model"].pop("units")

        run = self.edit_fixture_intent(ident, missing)
        error = self.fresh("operation", "query", "--id", ident, "--model", "block.prt", status=1)[
            "error"
        ]
        assert error["code"] == "E_VERIFY_INCOMPLETE"
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == run

    def test_missing_retained_v2_scalar_is_incomplete_before_machining_snapshot(self):
        ident, _ = self.lost_hole(self.native_residual)

        def missing(baseline):
            baseline["machining_intent"]["complete_through_hole"].pop("removed_volume")

        run = self.edit_fixture_intent(ident, missing)
        before = len(self.world.events)
        error = self.fresh("operation", "query", "--id", ident, "--model", "block.prt", status=1)[
            "error"
        ]
        assert error["code"] == "E_VERIFY_INCOMPLETE"
        assert [op for op, _ in self.world.events[before:]] == [
            "model.show",
            "feature.list",
            "dimension.list",
        ]  # Existing generic query prefix; no machining snapshot/geometry reads follow.
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == run

    def test_missing_frozen_unit_evidence_cannot_be_filled_during_query(self):
        ident, _ = self.lost_hole(self.native_residual)

        def missing(baseline):
            baseline["machining_intent"]["complete_through_hole"].pop("volume_unit_evidence")

        run = self.edit_fixture_intent(ident, missing)
        before = len(self.world.events)
        error = self.fresh("operation", "query", "--id", ident, "--model", "block.prt", status=1)[
            "error"
        ]
        assert error["code"] == "E_VERIFY_INCOMPLETE"
        assert [op for op, _ in self.world.events[before:]] == [
            "model.show",
            "feature.list",
            "dimension.list",
        ]
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == run

    def test_current_mass_property_unit_drift_is_incomplete_not_pending(self):
        ident, _ = self.lost_hole(self.native_residual)
        original = self.world.mass_properties

        def changed(model):
            properties = original(model)
            properties["units"]["volume"] = "in^3"
            return properties

        with patch.object(self.world, "mass_properties", side_effect=changed):
            error = self.fresh(
                "operation", "query", "--id", ident, "--model", "block.prt", status=1
            )["error"]
        assert error["code"] == "E_VERIFY_INCOMPLETE"
        assert "E_NATIVE_READ_PENDING" not in str(error)

    def test_old_policy_query_still_fails_and_only_partial_is_available(self):
        ident, _ = self.lost_hole(self.native_residual)
        with patch.dict(os.environ, self.env, clear=True):
            original = operations.get(ident)
            # Controlled local fixture represents a pre-v2 record, never a real history edit.
            old = copy.deepcopy(original)
            old_intent = old["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"][
                "machining_intent"
            ]
            old_intent["complete_through_hole"].pop("volume_comparison", None)
            operations.update(old)
        result = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        proof = result["observation"]["machining_verification"]
        assert proof["accepted"] is False
        assert proof["can_register"] == ["partial"]
        assert "volume_comparison" not in proof["intent"]["complete_through_hole"]
        self.refuse_false_applied(ident)

    def test_residual_above_cap_is_ordinary_failure_not_pending(self):
        model = self.block()
        args = self.args("hole", self.hole_request())
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.hole

        def too_much(request):
            reply = original(request)
            model["volume"] -= 0.005
            return reply

        with patch.object(self.world, "hole", side_effect=too_much):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=1)["error"]
        assert error["code"] == "E_VERIFY_FAILED"
        assert "E_NATIVE_READ_PENDING" not in str(error)

    def geometry_fixture(self):
        self.block()
        args = self.args("hole", self.hole_request())
        dry = self.cli(*args, "--dry-run")["data"]
        preview = dry["preview"]
        self.cli(*args, "--confirm", dry["confirm_token"])
        from creo_cli.transport import Client

        with patch.dict(os.environ, self.env, clear=True), Client() as client:
            after = machining.snapshot(client, "block.prt")
        baseline = preview["base_snapshot"]["extensions"]["creo"]["observation"]
        before = baseline["machining_before"]
        ident = next(
            f["id"]
            for f in after["features"]
            if f["id"] not in {r["id"] for r in before["features"]}
        )
        return before, baseline["machining_intent"], after, preview["changes"][0]["after"], ident

    def test_extra_physical_faces_cannot_hide_inside_volume_cap(self):
        before, intent, after, request, ident = self.geometry_fixture()
        wall = next(
            g
            for g in after["geometry"]["items"]
            if g.get("kind") == "surface" and str(g.get("feature", {}).get("id")) == ident
        )
        for fault in ("radius", "axis", "outward", "plane", "unknown"):
            with self.subTest(fault=fault):
                current = copy.deepcopy(after)
                extra = copy.deepcopy(wall)
                extra.update(ref="surface:999999", id="999999")
                if fault == "radius":
                    extra["radius"] += 0.1
                elif fault == "axis":
                    extra["axis"]["origin"][0] += 1
                elif fault == "outward":
                    extra["outward"] = "away_from_axis"
                else:
                    extra["type"] = fault
                current["geometry"]["items"].append(extra)
                current["model"]["mass_properties"]["volume"] -= 0.0005
                _, verification = machining.verify_geometry(
                    "feature.hole", request, before, intent, current, ident
                )
                checks = {c["check"]: c for c in verification["checks"]}
                assert checks["complete_hole_removed_volume"]["passed"] is True
                assert checks["complete_hole_owned_surfaces_covered"]["passed"] is False

    def test_unknown_or_missing_surface_owner_is_incomplete(self):
        before, intent, after, request, ident = self.geometry_fixture()
        for owner in (None, "999999"):
            with self.subTest(owner=owner):
                current = copy.deepcopy(after)
                surface = next(
                    g for g in current["geometry"]["items"] if g.get("kind") == "surface"
                )
                surface["feature"] = None if owner is None else {"id": owner}
                with pytest.raises(Error) as exc:
                    machining.verify_geometry(
                        "feature.hole", request, before, intent, current, ident
                    )
                assert exc.value.code == "E_VERIFY_INCOMPLETE"

    def test_extra_small_surface_with_nonexistent_owner_is_incomplete(self):
        before, intent, after, request, ident = self.geometry_fixture()
        wall = next(g for g in after["geometry"]["items"] if g.get("kind") == "surface")
        extra = copy.deepcopy(wall)
        extra.update(ref="surface:999999", id="999999", feature={"id": "999999"})
        after["geometry"]["items"].append(extra)
        after["model"]["mass_properties"]["volume"] -= 0.0005
        with pytest.raises(Error) as exc:
            machining.verify_geometry("feature.hole", request, before, intent, after, ident)
        assert exc.value.code == "E_VERIFY_INCOMPLETE"

    def test_non_surface_owned_axis_does_not_expand_wall_inventory(self):
        before, intent, after, request, ident = self.geometry_fixture()
        after["geometry"]["items"].append(
            {
                "ref": "axis:999999",
                "id": "999999",
                "kind": "axis",
                "type": "cylinder",
                "feature": {"id": ident},
                "outward": "toward_axis",
            }
        )
        after["geometry"]["items"].append(
            {
                "ref": "datum:999998",
                "id": "999998",
                "kind": "datum_plane",
                "type": "plane",
                "feature": {"id": ident},
            }
        )
        _, verification = machining.verify_geometry(
            "feature.hole", request, before, intent, after, ident
        )
        assert all(c["passed"] for c in verification["checks"])
