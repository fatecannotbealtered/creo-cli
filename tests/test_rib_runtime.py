"""Public bounded rib lifecycle against an independent cell mesh; no native claim."""

import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests import fixture_rib, test_features
from tests.test_commands import RECT, Base
from tests.test_feature_name_intent import PublicProcesses


class RibRuntime(PublicProcesses, test_features.Built):
    def setUp(self):
        test_features.Built.setUp(self)
        self.world.capabilities["prismatic_rib_readback"] = 3
        original = self.world.op
        extended = patch.object(
            self.world,
            "op",
            side_effect=lambda op, request: fixture_rib.dispatch(self.world, original, op, request),
        )
        extended.start()
        self.addCleanup(extended.stop)
        self.part()
        self.world.active = "block.prt"
        block = copy.deepcopy(RECT)
        block["name"], block["depth"] = "HOUSING", 20
        block["sketch"]["profile"] |= {"width": 50, "height": 30}
        self.gated(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(block, "housing-extrude.json"),
        )
        shell = {"units": "mm", "name": "HOLLOW", "thickness": 2, "remove": [self.top()["ref"]]}
        self.gated(
            "feature",
            "shell",
            "--model",
            "block",
            "--request",
            self.request(shell, "housing-shell.json"),
        )
        self.body = {
            "units": "mm",
            "name": "WEB",
            "thickness": 2,
            "side": "symmetric",
            "sketch": {"plane": "TOP", "orient_ref": "RIGHT", "points": [[-15, 6], [15, 6]]},
        }

    def args(self, body=None):
        return (
            "feature",
            "rib",
            "--model",
            "block",
            "--request",
            self.request(body or self.body, "rib-request.json"),
        )

    def rib(self):
        return next(
            f for f in self.world.models["block.prt"]["features"] if f["type"] == "FEATTYPE_RIB"
        )

    def lost_reply(self, change=None):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == "feature.rib" and change:
                result = copy.deepcopy(result)
                change(self.world.models["block.prt"], self.rib())
            return result

        self.world.drop = "feature.rib"
        try:
            with patch.object(self.world, "op", side_effect=changed):
                self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        finally:
            self.world.drop = None
        return args, preview, preview["preview"]["operation_id"]

    def resolve(self, ident, *, dry=False, status=0, outcome="applied"):
        words = (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            outcome,
            "--evidence",
            "Independent native rib section, thickness, fill, complete connected body and name",
        )
        if dry:
            return self.cli(*words, "--dry-run", status=status)
        return self.gated(*words, status=status)

    def test_preview_freezes_original_extended_endpoints_associations_and_unique_floor_fill(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        intent = preview["preview"]["extensions"]["creo"]["rib_intent"]
        self.assertEqual(intent["profile"], "rectangular-housing-rib-v1")
        self.assertEqual(intent["original_request"]["sketch"]["points"], [[-15, 6], [15, 6]])
        self.assertNotIn("fill", intent["original_request"])
        self.assertEqual(intent["actual_request"]["sketch"]["points"], [[-23, 6], [23, 6]])
        self.assertEqual(intent["actual_request"]["sketch"]["references"], ["RIGHT", "FRONT"])
        self.assertEqual(intent["actual_endpoints_mm"], [[-23, 0, -6], [23, 0, -6]])
        self.assertEqual(intent["fill"], "left")
        self.assertEqual(intent["fill_direction"], [0, 0, -1])
        self.assertEqual(intent["name_intent"], {"policy": "requested", "name": "WEB"})
        self.assertEqual(set(intent["associations"]), {"left_wall", "right_wall", "floor"})
        self.assertTrue(all(v.startswith("surface:") for v in intent["associations"].values()))
        self.assertEqual(
            intent["native_auxiliary_policy"],
            {
                "max_count": 1,
                "type": "FEATTYPE_DATUM_PLANE",
                "visible": False,
                "parent_refs": ["TOP", "RIGHT"],
                "same_plane": True,
                "sole_child": "new_rib",
            },
        )
        self.assertEqual(
            intent["native_projection_policy"],
            {
                "required_datums": 2,
                "wall_auxiliaries": 2,
                "allowed_wall_roles": ["projection", "construction"],
                "profile_lines": 1,
            },
        )
        self.assertNotIn("feature.rib", self.world.ops())
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.world.models["block.prt"]["volume"], 9576)
        definition = self.cli("feature", "show", "--model", "block", "--feature", "WEB")["data"][
            "native_definition"
        ]
        self.assertEqual(definition["kind"], "rib")
        self.assertEqual(definition["thickness"], 2)
        self.assertEqual(definition["fill"], "left")
        dispatched = next(q for op, q in self.world.events if op == "feature.rib")
        self.assertEqual(dispatched["sketch"]["points"], [[-23, 6], [23, 6]])
        self.assertEqual(dispatched["fill"], "left")
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def test_thickness_roundtrip_reads_actual_native_dimension_and_requires_explicit_save(self):
        self.gated(*self.args())
        definition = self.cli("feature", "show", "--model", "block", "--feature", "WEB")["data"][
            "native_definition"
        ]
        ident = str(definition["thickness_dimension"]["id"])
        dims = self.cli("dimension", "list", "--model", "block", "--feature", "WEB")["data"][
            "items"
        ]
        self.assertTrue(any(str(d["id"]) == ident and d["value"] == 2 for d in dims))
        for thickness, expected in ((3, 10128), (2, 9576)):
            self.gated(
                "dimension",
                "set",
                "--model",
                "block",
                "--dimension",
                ident,
                "--value",
                thickness,
                "--units",
                "mm",
            )
            self.assertEqual(self.world.models["block.prt"]["volume"], expected)
            current = self.cli("feature", "show", "--model", "block", "--feature", "WEB")["data"]
            self.assertEqual(current["native_definition"]["thickness"], thickness)
            self.assertEqual(
                current["native_definition"]["thickness_dimension"]["value"], thickness
            )
        self.gated("model", "save", "--model", "block")
        self.gated("model", "close", "--model", "block")
        # Real save/all-close/reopen, continued editing and STEP consumption are native gates.

    def test_opposite_fill_is_refused_without_native_attempt(self):
        self.cli(*self.args(self.body | {"fill": "right"}), "--dry-run", status=2)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_unsupported_chain_plane_side_or_thickness_are_zero_dispatch(self):
        variants = [
            self.body | {"thickness": 2.5},
            self.body | {"thickness": 26},
            self.body | {"side": "one"},
            self.body | {"sketch": self.body["sketch"] | {"points": [[-15, 6], [15, 7]]}},
            self.body | {"sketch": self.body["sketch"] | {"points": [[-15, 6], [0, 6], [15, 6]]}},
            self.body | {"sketch": self.body["sketch"] | {"plane": "FRONT"}},
        ]
        for body in variants:
            with self.subTest(body=body):
                self.cli(*self.args(body), "--dry-run", status=2)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_missing_rib_readback_capability_refuses_before_dispatch(self):
        self.world.capabilities.pop("prismatic_rib_readback")
        self.cli(*self.args(), "--dry-run", status=4)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_old_name_only_projection_capability_refuses_before_dispatch(self):
        self.world.capabilities["prismatic_rib_readback"] = 1
        self.cli(*self.args(), "--dry-run", status=4)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_r3_old_capability_two_cannot_start_a_new_rib_write(self):
        self.world.capabilities["prismatic_rib_readback"] = 2
        self.cli(*self.args(), "--dry-run", status=4)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_rib_is_not_silently_enabled_in_workflow(self):
        rib = self.request(self.body, "workflow-rib.json")
        workflow = self.request(
            {
                "steps": [
                    {
                        "id": "rib",
                        "command": "feature rib",
                        "args": {"model": "block", "request": str(rib)},
                    }
                ]
            },
            "workflow.json",
        )
        self.cli("workflow", "run", "--request", workflow, "--dry-run", status=2)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_request_replacement_and_stale_geometry_refuse_old_confirmation(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        source = Path(args[-1])
        replacement = source.with_suffix(".replacement")
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        preview = self.cli(*args, "--dry-run")["data"]
        edge = next(g for g in self.world.models["block.prt"]["geometry"] if g["kind"] == "edge")
        edge["start"][0] += 1
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_scope_drift_refuses_old_confirmation(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        body = json.loads(scope.read_text())
        body["effects"] = ["observe"]
        scope.write_text(json.dumps(body))
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("feature.rib", self.world.ops())

    def test_lost_reply_new_process_query_and_register_without_replay(self):
        args, preview, ident = self.lost_reply()
        before = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]
        self.assertEqual(before["outcome"]["execution"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(
            query["observation"]["prismatic_rib_verification"]["can_register"], ["applied"]
        )
        self.resolve(ident)
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"], before)
        self.assertEqual(
            shown["extensions"]["creo"]["prismatic_rib_inspection"]["evidence_status"], "verified"
        )
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def wrong_geometry(self, *, disconnected=False, flip=False):
        def changed(model, feature):
            volume = model["volume"]
            fixture_rib.reshape(
                self.world,
                model,
                feature,
                2,
                shift_y=0 if disconnected or flip else 3,
                disconnected=disconnected,
                flip=flip,
            )
            # Matching the requested volume cannot compensate for wrong physical placement.
            model["volume"] = volume

        _, _, ident = self.lost_reply(changed)
        if disconnected:
            # A disjoint boundary is outside this one-connected-body profile, so public
            # observation refuses before it can produce a proof or an applied registration.
            query = self.cli("operation", "query", "--id", ident, "--model", "block", status=2)
            self.assertEqual(query["error"]["code"], "E_UNSUPPORTED")
            self.resolve(ident, dry=True, status=2)
            shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
            self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")
            self.assertEqual(self.world.ops().count("feature.rib"), 1)
            return
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        proof = query["observation"]["prismatic_rib_verification"]
        self.assertFalse(proof["accepted"])
        self.assertNotIn("applied", proof["can_register"])
        self.resolve(ident, dry=True, status=1)
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def test_same_volume_wrong_position_cannot_register_applied(self):
        self.wrong_geometry()

    def test_same_volume_wrong_fill_cannot_register_applied(self):
        self.wrong_geometry(flip=True)

    def test_disconnected_rib_cannot_register_applied(self):
        self.wrong_geometry(disconnected=True)

    def definition_fault(self, change, *, status=1):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == "feature.rib":
                result = copy.deepcopy(result)
                change(self.world.models["block.prt"], self.rib())
            return result

        with patch.object(self.world, "op", side_effect=changed):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=status)["error"]
        self.assertEqual(self.world.ops().count("feature.rib"), 1)
        return error

    def test_correct_geometry_wrong_native_fill_is_not_complete_success(self):
        self.definition_fault(
            lambda model, feature: feature["native_definition"].update(fill="right")
        )

    def test_correct_geometry_missing_actual_section_is_not_complete_success(self):
        self.definition_fault(lambda model, feature: feature.pop("native_section_readback"))

    def test_correct_geometry_unextended_section_endpoints_are_not_complete_success(self):
        def shortened(model, feature):
            raw = feature["native_section_readback"]
            raw["entities_read"] = ";".join(
                ["#1 L -15 6 15 6", *raw["entities_read"].split(";")[1:]]
            )

        self.definition_fault(shortened)

    def test_service_reply_name_cannot_replace_independent_rib_name(self):
        self.definition_fault(lambda model, feature: feature.update(name="WRONG_NATIVE_NAME"))

    def test_matching_shell_dimension_cannot_masquerade_as_rib_thickness_driver(self):
        def wrong_owner(model, feature):
            shell = self.world.feature(model, "HOLLOW")
            dimension = next(
                d
                for d in model["dimensions"]
                if d["feature"]["id"] == shell["id"] and d.get("type")
            )
            self.assertEqual(dimension["value"], feature["native_definition"]["thickness"])
            feature["native_definition"]["thickness_dimension"] = {
                k: dimension[k] for k in ("id", "name", "value")
            }

        self.definition_fault(wrong_owner)

    def test_unrelated_datum_geometry_must_remain_protected(self):
        def changed_datum(model, feature):
            datum = next(g for g in model["geometry"] if g["ref"] == "TOP")
            datum["normal"] = [0, -1, 0]

        self.definition_fault(changed_datum)

    def test_r3_construction_wall_helpers_are_read_independently(self):
        self.world.rib_fixture_wall_construction = True
        result = self.gated(*self.args())["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.world.models["block.prt"]["volume"], 9576)
        raw = self.rib()["native_section_readback"]
        self.assertEqual(raw["projection_ref_count"], 2)
        self.assertEqual(raw["section_entity_count"], 5)
        self.assertIn("#4 0 1", raw["section_entity_roles"])

    def test_r3_zero_auxiliary_datums_is_within_the_frozen_maximum(self):
        self.world.rib_fixture_auxiliary = False
        result = self.gated(*self.args())["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.rib()["native_auxiliary_datums"]["items"], [])

    def test_r3_native_null_dummy_dimension_cannot_be_the_thickness_driver(self):
        def wrong_dummy(model, feature):
            dummy = next(
                d
                for d in model["dimensions"]
                if d["feature"]["id"] == feature["id"] and d.get("type") is None
            )
            self.assertIsNone(dummy["value"])
            feature["native_definition"]["thickness_dimension"] = {
                k: dummy[k] for k in ("id", "name", "value")
            }

        self.definition_fault(wrong_dummy)

    def r3_auxiliary_fault(self, change):
        self.definition_fault(
            lambda model, feature: change(feature["native_auxiliary_datums"]["items"][0])
        )

    def test_r3_auxiliary_datum_wrong_plane_is_rejected(self):
        self.r3_auxiliary_fault(lambda row: row["surface"].update(normal=[1, 0, 0]))

    def test_r3_auxiliary_datum_wrong_parents_are_rejected(self):
        front = str(self.world.feature(self.world.models["block.prt"], "FRONT")["id"])
        self.r3_auxiliary_fault(lambda row: row.update(parents=[front, row["parents"][1]]))

    def test_r3_auxiliary_datum_extra_child_is_rejected(self):
        self.r3_auxiliary_fault(lambda row: row["children"].append("7"))

    def test_r3_auxiliary_datum_visible_state_is_rejected(self):
        self.r3_auxiliary_fault(lambda row: row.update(visible=True))

    def r4_auxiliary_normal(self, model, feature, normal):
        item = feature["native_auxiliary_datums"]["items"][0]
        item["surface"]["normal"] = normal
        actual = next(
            row
            for row in model["geometry"]
            if row["kind"] == "datum_plane" and str(row["id"]) == str(item["surface"]["id"])
        )
        actual["normal"] = list(normal)

    def test_r4_auxiliary_plane_oblique_nonunit_normal_is_rejected(self):
        self.definition_fault(
            lambda model, feature: self.r4_auxiliary_normal(model, feature, [1, 1, 0])
        )

    def test_r4_auxiliary_plane_zero_normal_is_rejected(self):
        self.definition_fault(
            lambda model, feature: self.r4_auxiliary_normal(model, feature, [0, 0, 0])
        )

    def test_r4_auxiliary_plane_nonfinite_normal_is_rejected(self):
        error = self.definition_fault(
            lambda model, feature: self.r4_auxiliary_normal(model, feature, [float("inf"), 1, 0]),
            status=6,
        )
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(
            error["details"]["receipt"]["outcome"]["verification"]["status"], "incomplete"
        )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_r4_auxiliary_plane_opposite_unit_normal_is_coincident(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def opposite(op, request):
            result = original(op, request)
            if op == "feature.rib":
                result = copy.deepcopy(result)
                self.r4_auxiliary_normal(self.world.models["block.prt"], self.rib(), [0, -1, 0])
            return result

        with patch.object(self.world, "op", side_effect=opposite):
            result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def test_r3_unreported_second_hidden_datum_is_rejected(self):
        def extra(model, feature):
            datum = self.world.new_feature(model, "EXTRA_INTERNAL", "FEATTYPE_DATUM_PLANE", "EXTRA")
            datum["visible"] = False

        self.definition_fault(extra)

    def test_r3_unknown_extra_native_feature_is_rejected(self):
        self.definition_fault(
            lambda model, feature: self.world.new_feature(
                model, "UNEXPECTED", "FEATTYPE_PROTRUSION", "EXTRA"
            )
        )

    def test_r3_wall_projection_must_reference_a_frozen_target_wall(self):
        def wrong_wall(model, feature):
            raw = feature["native_section_readback"]
            rows = raw["projection_refs"].split(";")
            fields = rows[-1].split()
            fields[1] = "99999"
            rows[-1] = " ".join(fields)
            raw["projection_refs"] = ";".join(rows)

        self.definition_fault(wrong_wall)

    def test_r3_wall_projection_must_still_exist_in_current_body(self):
        def stale_wall(model, feature):
            old_id = feature["rib_wall_sources"][0]["id"]
            face = next(
                g for g in model["geometry"] if g["kind"] == "surface" and g["id"] == old_id
            )
            old_ref = face["ref"]
            face["id"] = self.world._gid(model)
            face["ref"] = "surface:" + str(face["id"])
            for edge in model["geometry"]:
                if edge["kind"] == "edge":
                    edge["surfaces"] = [
                        face["ref"] if ref == old_ref else ref for ref in edge["surfaces"]
                    ]

        self.definition_fault(stale_wall)

    def test_r3_construction_helper_world_axis_must_match_its_wall(self):
        self.world.rib_fixture_wall_construction = True

        def wrong_axis(model, feature):
            raw = feature["native_section_readback"]
            rows = raw["entities_read"].split(";")
            rows[3] = "#4 L -22 0 -22 18"
            raw["entities_read"] = ";".join(rows)

        self.definition_fault(wrong_axis)

    def test_r3_a_second_profile_line_cannot_masquerade_as_a_wall_helper(self):
        self.world.rib_fixture_wall_construction = True

        def extra_profile(model, feature):
            raw = feature["native_section_readback"]
            raw["section_entity_roles"] = raw["section_entity_roles"].replace("#4 0 1", "#4 0 0")

        self.definition_fault(extra_profile)

    def test_r3_missing_native_entity_roles_is_not_complete_success(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].pop("section_entity_roles")
        )

    def r3_remove_frozen_policies(self, ident):
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            wanted = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"][
                "rib_intent"
            ]
            for key in (
                "attachment_projections",
                "native_projection_policy",
                "native_auxiliary_policy",
            ):
                wanted.pop(key)
            operations.update(run)

    def test_r3_old_unfrozen_policy_and_incomplete_definition_allow_only_partial_preservation(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        ident = preview["preview"]["operation_id"]
        original = self.world.op

        def ambiguous(op, request):
            result = original(op, request)
            if op == "feature.rib":
                self.rib()["native_definition"] = {
                    "complete": False,
                    "kind": "rib",
                    "error": {
                        "code": "E_VERIFY_INCOMPLETE",
                        "message": "fixture native dummy dimension is ambiguous",
                    },
                }
            return result

        with patch.object(self.world, "op", side_effect=ambiguous):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        before = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]
        self.assertEqual(before["outcome"]["verification"]["status"], "failed")
        self.r3_remove_frozen_policies(ident)
        self.world.capabilities["prismatic_rib_readback"] = 2
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(
            query["observation"]["prismatic_rib_verification"]["can_register"], ["partial"]
        )
        self.resolve(ident, dry=True, status=1)
        self.resolve(ident, outcome="partial")
        after = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]
        self.assertEqual(after, before)
        self.gated("model", "save", "--model", "block")
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def test_r3_old_unfrozen_policy_wrong_body_cannot_register_partial(self):
        def moved(model, feature):
            fixture_rib.reshape(self.world, model, feature, 2, shift_y=3)

        _, _, ident = self.lost_reply(moved)
        self.r3_remove_frozen_policies(ident)
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertNotIn(
            "partial", query["observation"]["prismatic_rib_verification"]["can_register"]
        )
        self.resolve(ident, dry=True, status=1, outcome="partial")

    def test_r3_old_unfrozen_policy_changed_protected_datum_cannot_register_partial(self):
        def changed(model, feature):
            feature["native_definition"] = {"complete": False, "kind": "rib"}
            next(g for g in model["geometry"] if g["ref"] == "TOP")["normal"] = [0, -1, 0]

        _, _, ident = self.lost_reply(changed)
        self.r3_remove_frozen_policies(ident)
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertNotIn(
            "partial", query["observation"]["prismatic_rib_verification"]["can_register"]
        )
        self.resolve(ident, dry=True, status=1, outcome="partial")

    def test_r3_old_unfrozen_policy_valid_hash_cannot_keep_applied_trust(self):
        _, _, ident = self.lost_reply()
        self.resolve(ident)
        self.r3_remove_frozen_policies(ident)
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            receipt = copy.deepcopy(run["driver_receipt"])
            reference = run["driver_prismatic_rib_resolution"]
            observation = operations.load_query(reference["evidence_id"])["observation"]
            proof = observation["prismatic_rib_verification"]
            proof["intent"] = copy.deepcopy(
                run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"][
                    "rib_intent"
                ]
            )
            new = operations.save_query(run, observation)
            run["driver_prismatic_rib_resolution"] |= {
                "evidence_id": new["evidence_id"],
                "sha256": new["sha256"],
            }
            operations.update(run)
        calls = len(self.world.ops())
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        inspection = shown["extensions"]["creo"]["prismatic_rib_inspection"]
        self.assertEqual(inspection["evidence_integrity"], "valid")
        self.assertEqual(inspection["evidence_status"], "insufficient")
        self.assertEqual(shown["receipt"], receipt)
        self.assertEqual(len(self.world.ops()), calls)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def wrong_projection(self, column, value):
        def changed_projection(model, feature):
            raw = feature["native_section_readback"]
            rows = raw["projection_refs"].split(";")
            fields = rows[0].split()
            fields[column] = str(value)
            rows[0] = " ".join(fields)
            raw["projection_refs"] = ";".join(rows)

        self.definition_fault(changed_projection)

    def test_native_projection_wrong_surface_id_is_not_complete_success(self):
        self.wrong_projection(1, 99999)

    def test_native_projection_foreign_owner_stem_is_not_complete_success(self):
        self.wrong_projection(3, "foreign")

    def test_native_projection_matching_owner_name_cannot_replace_actual_owner_identity(self):
        self.wrong_projection(7, 0)

    def test_native_projection_wrong_item_type_is_not_complete_success(self):
        self.wrong_projection(2, "axis")

    def test_native_projection_assembly_path_is_not_complete_success(self):
        self.wrong_projection(8, 1)

    def test_missing_native_projection_proof_is_not_complete_success(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].pop("projection_refs")
        )

    def test_incomplete_native_projection_proof_is_not_complete_success(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].update(
                projection_refs_complete=0
            )
        )

    def test_projection_count_must_match_actual_projection_rows(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].update(projection_ref_count=3)
        )

    def test_projection_identity_rows_must_cover_actual_native_R_entities(self):
        def missing_entity(model, feature):
            raw = feature["native_section_readback"]
            raw["entities_read"] = raw["entities_read"].split(";")[0]

        self.definition_fault(missing_entity)

    def test_missing_native_section_entity_count_is_not_complete_success(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].pop("section_entity_count")
        )

    def test_omitted_extra_native_section_entity_cannot_hide_behind_correct_line_and_refs(self):
        self.definition_fault(
            lambda model, feature: feature["native_section_readback"].update(section_entity_count=6)
        )

    def test_duplicate_native_section_entity_ids_are_not_complete_success(self):
        def duplicate_entity(model, feature):
            raw = feature["native_section_readback"]
            raw["entities_read"] += ";#1 R 0 0 0 0"
            raw["section_entity_count"] = 6
            raw["section_entity_roles"] += ";#1 1 0"
            raw["section_entity_role_count"] = 6

        self.definition_fault(duplicate_entity)

    def test_extra_native_body_cannot_be_registered_applied(self):
        _, _, ident = self.lost_reply()
        original = self.world.op

        def extra(op, request):
            result = original(op, request)
            if op == "model.show":
                result = copy.deepcopy(result)
                result["bodies"].append(
                    {"id": -9000, "name": "EXTRA", "state": "BODY_STATE_ACTIVE"}
                )
            return result

        with patch.object(self.world, "op", side_effect=extra):
            self.resolve(ident, dry=True, status=1)
        self.assertEqual(self.world.ops().count("feature.rib"), 1)

    def test_retained_missing_section_with_valid_hash_does_not_unlock_writes(self):
        _, _, ident = self.lost_reply()
        self.resolve(ident)
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            receipt = copy.deepcopy(run["driver_receipt"])
            reference = run["driver_prismatic_rib_resolution"]
            observation = operations.load_query(reference["evidence_id"])["observation"]
            proof = observation["prismatic_rib_verification"]
            proof["current"]["sections"] = {}
            new = operations.save_query(run, observation)
            run["driver_prismatic_rib_resolution"] |= {
                "evidence_id": new["evidence_id"],
                "sha256": new["sha256"],
            }
            operations.update(run)
        calls = len(self.world.ops())
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        proof = shown["extensions"]["creo"]["prismatic_rib_inspection"]
        self.assertEqual(proof["evidence_integrity"], "valid")
        self.assertEqual(proof["evidence_status"], "insufficient")
        self.assertEqual(shown["receipt"], receipt)
        self.assertEqual(len(self.world.ops()), calls)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)


class RibReceiptStorageFailure(PublicProcesses, test_features.Built):
    """Source-level storage injection; keep outside the final EXE RibRuntime set."""

    setUp = RibRuntime.setUp
    args = RibRuntime.args
    resolve = RibRuntime.resolve

    def test_final_public_receipt_failure_new_process_recovery_without_replay(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        ident = preview["preview"]["operation_id"]
        original = operations.update
        witnesses = []

        def fail_only_target_final(record):
            receipt = record.get("driver_receipt") or {}
            outcome = receipt.get("outcome") or {}
            if (
                not witnesses
                and record.get("operation_id") == ident
                and record.get("command") == "feature rib"
                and record.get("driver_stage") == "finished"
                and outcome.get("execution") == "completed"
                and outcome.get("verification", {}).get("status") == "passed"
            ):
                witnesses.append(copy.deepcopy(record))
                raise Error("E_IO", "owned final public rib receipt storage failure")
            return original(record)

        # Only this confirmation runs source main in-process for the storage patch.
        # All observation and registration commands below start fresh CLI processes.
        with patch.object(operations, "update", side_effect=fail_only_target_final):
            result = Base.cli(self, *args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(len(witnesses), 1)
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(result["error"]["details"]["record_error"], "E_IO")
        self.assertEqual(result["error"]["details"]["dispatch_state"], "dispatched")
        self.assertTrue(witnesses[0]["driver_effect_observed"])
        self.assertEqual(witnesses[0]["driver_receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(self.world.ops().count("feature.rib"), 1)
        with patch.dict(os.environ, self.env, clear=True):
            stored = operations.get(ident)
        self.assertEqual(stored["status"], "running")
        self.assertEqual(stored["driver_stage"], "finalizing")
        self.assertIsNone(stored["driver_receipt"])

        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "unknown")
        before = shown["receipt"]
        self.assertEqual(before["outcome"]["execution"], "unknown")
        blocked = self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.assertEqual(blocked["error"]["code"], "E_CONFLICT")
        self.assertEqual(blocked["error"]["details"]["operation_ids"], [ident])
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        proof = query["observation"]["prismatic_rib_verification"]
        self.assertTrue(proof["accepted"])
        self.assertEqual(proof["can_register"], ["applied"])
        self.assertTrue(all(c["passed"] for c in proof["checks"]))
        self.resolve(ident)
        resolved = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(resolved["receipt"], before)
        self.assertEqual(resolved["resolution"]["outcome"], "applied")
        self.assertEqual(
            resolved["extensions"]["creo"]["prismatic_rib_inspection"]["evidence_status"],
            "verified",
        )
        events_before_repeat = len(self.world.events)
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(len(self.world.events), events_before_repeat)
        self.assertEqual(self.world.ops().count("feature.rib"), 1)
