"""Finite old-solid protection: analytic unit cases and public loopback recovery.

These substitute tests do not claim native geometry or native fault injection.
"""

import copy
import math
import os
from unittest.mock import patch

import pytest

import tests.test_hole_volume_policy as volume_tests
import tests.test_machining_review as review
from creo_cli import machining, operations
from creo_cli.core import Error
from tests.test_features import Built


def analytic_case():
    """A complete six-face plate and one internally placed, full-thickness hole."""
    old_owner = {"id": "40", "name": "BASE"}
    owner = {"id": "67", "name": "CHECK_HOLE"}
    surfaces = []
    low, high = [-40, -10, -6], [40, 10, 0]
    for axis in range(3):
        for side in (0, 1):
            normal = [0, 0, 0]
            normal[axis] = -1 if side == 0 else 1
            origin = [0, 0, 0]
            origin[axis] = (low, high)[side][axis]
            bounds = [list(low), list(high)]
            bounds[0][axis] = bounds[1][axis] = origin[axis]
            ident = str(1000 + len(surfaces))
            surfaces.append(
                {
                    "ref": "surface:" + ident,
                    "id": ident,
                    "kind": "surface",
                    "type": "plane",
                    "feature": old_owner,
                    "normal": normal,
                    "origin": origin,
                    "bbox": bounds,
                    "area": math.prod(high[i] - low[i] for i in range(3) if i != axis),
                }
            )
    edges = []
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        for one in (0, 1):
            for two in (0, 1):
                start, end = list(low), list(low)
                end[axis] = high[axis]
                start[others[0]] = end[others[0]] = (low, high)[one][others[0]]
                start[others[1]] = end[others[1]] = (low, high)[two][others[1]]
                adjacent = [
                    surfaces[2 * others[0] + one]["ref"],
                    surfaces[2 * others[1] + two]["ref"],
                ]
                ident = str(2000 + len(edges))
                direction = [0, 0, 0]
                direction[axis] = 1
                edges.append(
                    {
                        "ref": "edge:" + ident,
                        "id": ident,
                        "kind": "edge",
                        "type": "line",
                        "feature": old_owner,
                        "start": start,
                        "end": end,
                        "direction": direction,
                        "length": high[axis] - low[axis],
                        "surfaces": adjacent,
                    }
                )
    request = {
        "units": "mm",
        "name": "CHECK_HOLE",
        "diameter": 6,
        "depth": "through_all",
        "placement": {
            "surface": "surface:1005",
            "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
        },
    }
    datums = [
        {
            "ref": name,
            "id": str(i),
            "kind": "datum_plane",
            "type": "plane",
            "feature": {"id": str(i)},
            "origin": [0, 0, 0],
            "normal": normal,
        }
        for i, name, normal in ((1, "RIGHT", [1, 0, 0]), (3, "TOP", [0, 1, 0]))
    ]
    before = {
        "model": {
            "units": {"length": "mm"},
            "bbox": [low, high],
            "bodies": [{"id": "-5778", "name": None, "state": "BODY_STATE_ACTIVE"}],
            "family": {
                "source": "explicit synthetic FamilyMember fields",
                "complete": True,
                "kind": "standalone",
                "generic": None,
                "instances": [],
                "row_count": 0,
                "column_count": 0,
            },
            "mass_properties": {
                "volume": 9600.0,
                "units": {"length": "mm", "volume": "mm^3"},
            },
        },
        "features": [
            {"id": str(i), "name": str(i), "type": "FEATTYPE_PROTRUSION", "status": "FEAT_ACTIVE"}
            for i in (1, 3, 40)
        ],
        "dimensions": {"dimensions": []},
        "geometry": {"items": surfaces + edges + datums, "units": {"length": "mm"}},
        "native_definitions": {},
    }
    intent = machining.hole_intent(request, before)
    machining._freeze_hole_volume_policy(request, before, intent)
    machining._freeze_hole_solid_protection(before, intent)
    after = copy.deepcopy(before)
    after["features"].append(
        {"id": "67", "name": "CHECK_HOLE", "type": "FEATTYPE_HOLE", "status": "FEAT_ACTIVE"}
    )
    after["native_definitions"]["67"] = {
        "complete": True,
        "through_all": True,
        "placement_surface": request["placement"]["surface"],
        "offsets": request["placement"]["offsets"],
    }
    after["model"]["mass_properties"]["volume"] -= math.pi * 3**2 * 6
    for row in after["geometry"]["items"]:
        if row["ref"] in intent["solid_protection"]["cap_refs"].values():
            row["area"] -= math.pi * 3**2
    wall = {
        "ref": "surface:3000",
        "id": "3000",
        "kind": "surface",
        "type": "cylinder",
        "feature": owner,
        "axis": {"origin": [10, 3, 0], "direction": [0, 0, -1]},
        "radius": 3,
        "outward": "toward_axis",
        "bbox": [[7, 0, -6], [13, 6, 0]],
        "area": math.pi * 6 * 6,
    }
    after["geometry"]["items"].append(wall)
    for i, side in enumerate(("min", "max")):
        z = intent["through_extent"][side]
        point = [13, 3, z]
        after["geometry"]["items"].append(
            {
                "ref": f"edge:{4000 + i}",
                "id": str(4000 + i),
                "kind": "edge",
                "type": "circle",
                "feature": owner,
                "center": [10, 3, z],
                "radius": 3,
                "normal": [0, 0, 1],
                "start": point,
                "end": point,
                "length": math.pi * 6,
                "surfaces": [wall["ref"], intent["solid_protection"]["cap_refs"][side]],
            }
        )
    return before, intent, after, request, "67"


def verified(case):
    before, intent, after, request, ident = case
    _, proof = machining.verify_geometry("feature.hole", request, before, intent, after, ident)
    return {row["check"]: row for row in proof["checks"]}


def old_owner_change(after, mode):
    row = next(
        g
        for g in after["geometry"]["items"]
        if g.get("kind") == "surface" and g.get("normal") == [1, 0, 0]
    )
    if mode == "extra-face":
        extra = copy.deepcopy(row)
        extra.update(id="999999", ref="surface:999999")
        extra["origin"][0] += 0.01
        after["geometry"]["items"].append(extra)
        after["model"]["mass_properties"]["volume"] += 0.0005
    elif mode == "changed-face":
        row["origin"][0] += 0.01
    else:
        raise AssertionError(mode)


def test_complete_bounded_plate_keeps_finite_material_protection():
    checks = verified(analytic_case())
    assert all(row["passed"] for row in checks.values())


@pytest.mark.parametrize("side", ["min", "max"])
def test_each_physical_end_normal_must_point_outward_from_its_coordinate_extent(side):
    before, intent, after, _, _ = analytic_case()
    ref = intent["solid_protection"]["cap_refs"][side]
    for state in (before, after):
        cap = next(g for g in state["geometry"]["items"] if g["ref"] == ref)
        cap["normal"] = [-value for value in cap["normal"]]
    with pytest.raises(Error) as exc:
        machining._hole_solid_protection(before, intent)
    assert exc.value.code == "E_UNSUPPORTED"
    assert "outward normal" in exc.value.message


@pytest.mark.parametrize("mode", ["extra-face", "changed-face"])
def test_volume_pass_does_not_cover_old_owner_physical_changes(mode):
    case = analytic_case()
    old_owner_change(case[2], mode)
    checks = verified(case)
    assert checks["complete_hole_removed_volume"]["passed"] is True
    assert not all(row["passed"] for row in checks.values())
    expected = (
        "complete_hole_physical_surface_inventory"
        if mode == "extra-face"
        else "complete_hole_unaffected_surfaces_unchanged"
    )
    assert checks[expected]["passed"] is False


@pytest.mark.parametrize("fault", ["cap-area", "cap-origin", "old-edge", "extra-edge", "cap-id"])
def test_only_frozen_circular_trim_is_allowed(fault):
    case = analytic_case()
    before, intent, after, _, _ = case
    ref = intent["solid_protection"]["cap_refs"]["max"]
    row = next(g for g in after["geometry"]["items"] if g["ref"] == ref)
    if fault == "cap-area":
        row["area"] += 0.0005
    elif fault == "cap-origin":
        row["origin"][0] += 1e-8
    elif fault == "cap-id":
        row["id"] = "999999"
    else:
        edge = next(g for g in after["geometry"]["items"] if g.get("kind") == "edge")
        if fault == "old-edge":
            edge["length"] += 1e-8
        else:
            edge = copy.deepcopy(edge)
            edge.update(ref="edge:999999", id="999999")
            after["geometry"]["items"].append(edge)
    checks = verified(case)
    assert checks["complete_hole_removed_volume"]["passed"] is True
    assert not all(row["passed"] for row in checks.values())
    assert before["geometry"]["items"] != after["geometry"]["items"]


@pytest.mark.parametrize("fault", ["bbox", "extra-body", "body-id", "body-state", "body-name"])
def test_entire_bounds_and_one_body_identity_remain_independent_requirements(fault):
    case = analytic_case()
    current = case[2]["model"]
    if fault == "bbox":
        current["bbox"][1][2] += 1e-12
    elif fault == "extra-body":
        current["bodies"].append({"id": "2", "name": None, "state": "BODY_STATE_ACTIVE"})
    elif fault == "body-id":
        current["bodies"][0]["id"] = "2"
    elif fault == "body-state":
        current["bodies"][0]["state"] = "BODY_STATE_CONSUMED"
    else:
        current["bodies"][0].pop("name")
    checks = verified(case)
    assert checks["complete_hole_removed_volume"]["passed"] is True
    name = (
        "complete_hole_model_bounds_unchanged"
        if fault == "bbox"
        else "complete_hole_single_active_body_preserved"
    )
    assert checks[name]["passed"] is False


@pytest.mark.parametrize(
    "fault", ["missing", "extra", "missing-name", "wrong-state", "unknown-field"]
)
def test_body_getter_incompleteness_is_never_defaulted_into_one_active_body(fault):
    before, intent, _, _, _ = analytic_case()
    bodies = before["model"]["bodies"]
    if fault == "missing":
        before["model"].pop("bodies")
    elif fault == "extra":
        bodies.append(copy.deepcopy(bodies[0]))
    elif fault == "missing-name":
        bodies[0].pop("name")
    elif fault == "wrong-state":
        bodies[0]["state"] = "UNKNOWN"
    else:
        bodies[0]["mass"] = 0
    with pytest.raises(Error) as exc:
        machining._hole_solid_protection(before, intent)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize(
    "fault", ["missing", "incomplete", "generic", "instance", "missing-rows", "extra-instance"]
)
def test_family_scope_is_explicitly_observed_not_inferred_from_the_geometry(fault):
    before, intent, _, _, _ = analytic_case()
    family = before["model"]["family"]
    if fault == "missing":
        before["model"].pop("family")
    elif fault == "incomplete":
        family["complete"] = False
    elif fault in ("generic", "instance"):
        family["kind"] = fault
    elif fault == "missing-rows":
        family.pop("row_count")
    else:
        family["instances"] = ["UNPROTECTED_INSTANCE"]
    with pytest.raises(Error) as exc:
        machining._hole_solid_protection(before, intent)
    assert exc.value.code in ("E_VERIFY_INCOMPLETE", "E_UNSUPPORTED")


def test_family_state_cannot_change_behind_an_unchanged_physical_snapshot():
    case = analytic_case()
    case[2]["model"]["family"]["kind"] = "generic"
    checks = verified(case)
    assert checks["complete_hole_removed_volume"]["passed"] is True
    assert checks["complete_hole_non_family_part_preserved"]["passed"] is False


@pytest.mark.parametrize("fault", ["family-complete", "family-rowcount", "bbox"])
def test_current_semantic_types_cannot_alias_boolean_and_numeric_values(fault):
    case = analytic_case()
    if fault == "family-complete":
        case[2]["model"]["family"]["complete"] = 1
    elif fault == "family-rowcount":
        case[2]["model"]["family"]["row_count"] = False
    else:
        case[2]["model"]["bbox"][1][2] = False
    checks = verified(case)
    name = (
        "complete_hole_model_bounds_unchanged"
        if fault == "bbox"
        else "complete_hole_non_family_part_preserved"
    )
    assert checks[name]["passed"] is False
    proof = recovery_case(case)
    assert proof["accepted"] is False
    assert "applied" not in proof["can_register"]


def test_exactly_one_added_feature_is_shared_by_confirmation_and_recovery():
    case = analytic_case()
    case[2]["features"].append(
        {
            "id": "999999",
            "name": "EXTRA_DATUM",
            "type": "FEATTYPE_DATUM_PLANE",
            "status": "FEAT_ACTIVE",
        }
    )
    checks = verified(case)
    assert checks["complete_hole_removed_volume"]["passed"] is True
    assert checks["complete_hole_exact_new_feature_inventory"]["passed"] is False
    proof = recovery_case(case)
    assert proof["accepted"] is False
    assert "applied" not in proof["can_register"]


@pytest.mark.parametrize("fault", ["missing-wall-area", "unreadable-rim-end", "unsupported-side"])
def test_current_boundary_failure_retains_a_queryable_incomplete_proof(fault):
    case = analytic_case()
    current = case[2]
    if fault == "missing-wall-area":
        next(g for g in current["geometry"]["items"] if g["ref"] == "surface:3000").pop("area")
    elif fault == "unreadable-rim-end":
        next(g for g in current["geometry"]["items"] if g["ref"] == "edge:4000")["end"] = [
            None,
            None,
            None,
        ]
    else:
        next(g for g in current["geometry"]["items"] if g.get("normal") == [1, 0, 0])["type"] = (
            "spline"
        )
    proof = recovery_case(case)
    assert proof["accepted"] is False
    assert "applied" not in proof["can_register"]
    check = next(
        row
        for row in proof["checks"]
        if row["check"] == "complete_hole_solid_boundary_evidence_readable"
    )
    assert check["incomplete"] is True
    assert check["error"]["code"] in ("E_VERIFY_INCOMPLETE", "E_UNSUPPORTED")
    assert proof["current"] == current


def test_current_inventory_handler_never_swallows_a_pending_read_error():
    before, intent, after, _, ident = analytic_case()
    original = machining._physical_inventory
    pending = Error(
        "E_NATIVE_READ_PENDING",
        "controlled pending read",
        {"operation": "geometry.list", "cli_invocation_id": "test-invocation"},
    )
    attempts = []

    def current_inventory(state):
        if state is after:
            attempts.append(state)
            raise pending
        return original(state)

    with patch.object(machining, "_physical_inventory", side_effect=current_inventory):
        with pytest.raises(Error) as exc:
            machining._hole_solid_checks(before, intent, after, ident, [])
    assert exc.value is pending
    assert len(attempts) == 1


@pytest.mark.parametrize(
    "fault", ["area", "identity", "owner", "boundary", "type", "partial-side", "units"]
)
def test_incomplete_or_unsupported_baseline_is_refused_before_a_new_policy(fault):
    before, intent, _, _, _ = analytic_case()
    side = next(g for g in before["geometry"]["items"] if g.get("normal") == [1, 0, 0])
    if fault == "area":
        side.pop("area")
    elif fault == "identity":
        before["geometry"]["items"].append(copy.deepcopy(side))
    elif fault == "owner":
        side["feature"] = {"id": "999999"}
    elif fault == "type":
        side["type"] = "spline"
    elif fault == "partial-side":
        side["bbox"][0][2] += 1
    elif fault == "units":
        before["geometry"].pop("units")
    else:
        before["geometry"]["items"] = [
            g for g in before["geometry"]["items"] if g.get("ref") != "edge:2000"
        ]
    with pytest.raises(Error) as exc:
        machining._hole_solid_protection(before, intent)
    assert exc.value.code in ("E_VERIFY_INCOMPLETE", "E_UNSUPPORTED")


@pytest.mark.parametrize("version", [True, 2, None])
def test_unknown_or_changed_explicit_policy_is_never_a_legacy_default(version):
    case = analytic_case()
    case[1]["solid_protection"]["version"] = version
    with pytest.raises(Error) as exc:
        verified(case)
    assert exc.value.code == "E_VERIFY_INCOMPLETE"


def test_old_intent_does_not_gain_the_new_grade():
    case = analytic_case()
    case[1].pop("solid_protection")
    old_owner_change(case[2], "extra-face")
    checks = verified(case)
    assert all(row["passed"] for row in checks.values())
    assert "complete_hole_physical_surface_inventory" not in checks


def recovery_case(case):
    before, intent, after, request, _ = case
    run = {
        "target": "case.prt",
        "command": "feature hole",
        "operation_id": "retained-test-operation",
        "driver_plan": {
            "target": {"instance_id": "test-generation"},
            "changes": [{"after": {"model": "case.prt", **request}}],
            "base_snapshot": {
                "extensions": {
                    "creo": {
                        "observation": {"machining_before": before, "machining_intent": intent}
                    }
                }
            },
        },
    }

    class ReadOnly:
        def health(self):
            return {"service_instance_id": "test-generation"}

        def require_capability(self, *_):
            pass

        def op(self, *_):
            raise AssertionError("unit predicate must not dispatch or repair native data")

    retained = copy.deepcopy(run)
    with patch.object(machining, "snapshot", side_effect=lambda *_: copy.deepcopy(after)):
        proof = machining.recovery(ReadOnly(), run)
    assert run == retained
    return proof


@pytest.mark.parametrize("mode", ["extra-face", "changed-face"])
def test_recovery_uses_exact_frozen_surface_policy_without_repair(mode):
    case = analytic_case()
    old_owner_change(case[2], mode)
    proof = recovery_case(case)
    assert proof["accepted"] is False
    assert "applied" not in proof["can_register"]
    assert proof["solid_protection_coverage"] == "retained-solid-boundary-v1"


def test_legacy_recovery_explicitly_retains_its_older_grade():
    case = analytic_case()
    case[1].pop("solid_protection")
    old_owner_change(case[2], "extra-face")
    proof = recovery_case(case)
    assert proof["accepted"] is False
    assert "applied" not in proof["can_register"]
    assert proof["solid_protection_coverage"].startswith("legacy;")
    old_checks = [
        row for row in proof["checks"] if row["check"] != "retained_solid_boundary_policy_available"
    ]
    assert all(
        row["passed"] for row in old_checks
    )  # The old predicates and receipt are not rewritten.
    assert not any(
        row["check"] == "complete_hole_physical_surface_inventory" for row in proof["checks"]
    )


class HoleSolidPublic(Built):
    """Public commands use one shared finite predicate for confirmation and registration."""

    block = volume_tests.HoleVolumePolicy.block
    hole_request = review.MachiningReview.hole_request
    args = review.MachiningReview.args
    fresh = review.MachiningReview.fresh
    lost_hole = review.MachiningReview.lost_hole
    refuse_false_applied = review.MachiningReview.refuse_false_applied

    @staticmethod
    def mutate(model, ident, before, mode):
        after = {
            "geometry": {"items": model["geometry"]},
            "model": {"mass_properties": {"volume": model["volume"]}},
        }
        old_owner_change(after, mode)
        model["volume"] = after["model"]["mass_properties"]["volume"]

    def normal_refuses(self, mode):
        self.block()
        args = self.args("hole", self.hole_request())
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.hole

        def changed(request):
            reply = original(request)
            self.mutate(self.world.models["block.prt"], reply["feature"]["id"], 0, mode)
            return reply

        with patch.object(self.world, "hole", side_effect=changed):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=1)["error"]
        assert error["code"] == "E_VERIFY_FAILED"
        checks = {row["check"]: row for row in error["details"]["failed_checks"]}
        expected = (
            "complete_hole_physical_surface_inventory"
            if mode == "extra-face"
            else "complete_hole_unaffected_surfaces_unchanged"
        )
        assert expected in checks
        assert self.world.ops().count("feature.hole") == 1
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        assert self.world.ops().count("feature.hole") == 1

    def test_public_normal_confirmation_rejects_old_owner_extra_surface(self):
        self.normal_refuses("extra-face")

    def test_public_normal_confirmation_rejects_unaffected_surface_change(self):
        self.normal_refuses("changed-face")

    def lost_refuses(self, mode):
        # Exactly one controlled lost reply in an isolated temporary fixture history.
        ident, _ = self.lost_hole(
            lambda model, feature, before: self.mutate(model, feature, before, mode)
        )
        query = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        proof = query["observation"]["machining_verification"]
        assert proof["accepted"] is False
        assert "applied" not in proof["can_register"]
        assert proof["solid_protection_coverage"] == "retained-solid-boundary-v1"
        assert (
            next(row for row in proof["checks"] if row["check"] == "complete_hole_removed_volume")[
                "passed"
            ]
            is True
        )
        with patch.dict(os.environ, self.env, clear=True):
            original = operations.get(ident)
        self.refuse_false_applied(ident)
        with patch.dict(os.environ, self.env, clear=True):
            assert operations.get(ident) == original
        assert self.world.ops().count("feature.hole") == 1

    def test_public_lost_reply_extra_old_owner_face_is_not_applied(self):
        self.lost_refuses("extra-face")

    def test_public_lost_reply_unaffected_face_change_is_not_applied(self):
        self.lost_refuses("changed-face")

    def test_public_extra_active_feature_is_refused_without_replaying_the_hole(self):
        self.block()
        args = self.args("hole", self.hole_request())
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.hole

        def changed(request):
            reply = original(request)
            self.world.models["block.prt"]["features"].append(
                {
                    "id": 999999,
                    "name": "EXTRA_DATUM",
                    "type": "FEATTYPE_DATUM_PLANE",
                    "status": "FEAT_ACTIVE",
                    "visible": True,
                }
            )
            return reply

        with patch.object(self.world, "hole", side_effect=changed):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=1)["error"]
        assert error["code"] == "E_VERIFY_FAILED"
        assert "complete_hole_exact_new_feature_inventory" in {
            row["check"] for row in error["details"]["failed_checks"]
        }
        assert self.world.ops().count("feature.hole") == 1
        self.refuse_false_applied(preview["preview"]["operation_id"])
        assert self.world.ops().count("feature.hole") == 1
