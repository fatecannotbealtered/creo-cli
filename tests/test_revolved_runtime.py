"""Bounded revolve/datum contract tests; loopback evidence is not native acceptance."""

import copy
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations, revolved
from creo_cli.core import Error
from tests.fixture import Refused
from tests.test_commands import ROOT, domain_receipt
from tests.test_features import SHAFT, Built


class RevolvedRuntime(Built):
    @staticmethod
    def stepped_request():
        request = copy.deepcopy(SHAFT)
        request["sketch"]["profile"] = {
            "type": "polygon",
            "points": [[2, 0], [10, 0], [10, 10], [8, 10], [8, 20], [4, 20], [4, 10], [2, 10]],
        }
        return request

    def coplanar_wrong(self, mode, lost):
        self.part()
        original = self.world.revolve

        def wrong(request):
            result = original(request)
            items = self.world.models["block.prt"]["geometry"]
            cap = next(g for g in items if g.get("fixture_radial_interval") == [2, 4])
            before_area, before_origin = cap["area"], copy.deepcopy(cap["origin"])
            for edge in items:
                if edge.get("kind") != "edge" or cap["ref"] not in edge.get("surfaces", []):
                    continue
                if mode == "rim":
                    radius = math.sqrt(edge["radius"] ** 2 + 4)
                    edge["radius"], edge["length"] = radius, 2 * math.pi * radius
                    edge["start"] = edge["end"] = [
                        edge["center"][0],
                        edge["center"][1],
                        edge["center"][2] + radius,
                    ]
                else:
                    wrong_wall = next(
                        g for g in items if g.get("type") == "cylinder" and g["radius"] == 8
                    )
                    edge["surfaces"] = [cap["ref"], wrong_wall["ref"]]
            self.assertEqual(cap["area"], before_area)
            self.assertEqual(cap["origin"], before_origin)
            return result

        args = self.args("revolve", self.stepped_request())
        preview = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "feature.revolve" if lost else None
        with patch.object(self.world, "revolve", side_effect=wrong):
            result = self.cli(*args, "--confirm", preview["confirm_token"], status=6 if lost else 1)
        self.world.drop = None
        if not lost:
            self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")
        self.fresh(
            "operation",
            "resolve",
            "--id",
            preview["preview"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "Same-plane cap areas and axial positions retained, but physical rims "
            "or adjacent cylinders are wrong",
            status=1,
        )
        self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)
        self.assertEqual(self.world.ops().count("feature.revolve"), 1)

    def test_same_plane_equal_area_wrong_rims_reject(self):
        self.coplanar_wrong("rim", False)

    def test_same_plane_equal_area_wrong_rims_lost_reply_cannot_register(self):
        self.coplanar_wrong("rim", True)

    def test_same_plane_equal_area_wrong_cylinder_adjacency_reject(self):
        self.coplanar_wrong("adjacent", False)

    def test_same_plane_equal_area_wrong_adjacency_lost_reply_cannot_register(self):
        self.coplanar_wrong("adjacent", True)

    def test_one_valid_annular_region_split_into_shared_edge_patches(self):
        self.part()
        original = self.world.revolve

        def split(request):
            result = original(request)
            model = self.world.models["block.prt"]
            items = model["geometry"]
            cap = next(g for g in items if g.get("fixture_radial_interval") == [2, 4])
            cap["area"] /= 2
            other = copy.deepcopy(cap)
            other["id"] = self.world._gid(model)
            other["ref"] = "surface:" + str(other["id"])
            items.append(other)
            for edge in list(items):
                if edge.get("kind") != "edge" or cap["ref"] not in edge.get("surfaces", []):
                    continue
                radius = edge["radius"]
                edge["type"], edge["length"] = "arc", math.pi * radius
                edge["start"] = [edge["center"][0], edge["center"][1], edge["center"][2] + radius]
                edge["end"] = [edge["center"][0], edge["center"][1], edge["center"][2] - radius]
                second = copy.deepcopy(edge)
                second["id"] = self.world._gid(model)
                second["ref"] = "edge:" + str(second["id"])
                second["surfaces"] = [
                    other["ref"] if ref == cap["ref"] else ref for ref in edge["surfaces"]
                ]
                second["start"], second["end"] = second["end"], second["start"]
                items.append(second)
            for sign in (1, -1):
                ident = self.world._gid(model)
                items.append(
                    {
                        "kind": "edge",
                        "type": "line",
                        "id": ident,
                        "ref": "edge:" + str(ident),
                        "start": [0, 10, sign * 2],
                        "end": [0, 10, sign * 4],
                        "length": 2,
                        "surfaces": [cap["ref"], other["ref"]],
                        "feature": cap["feature"],
                    }
                )
            return result

        with patch.object(self.world, "revolve", side_effect=split):
            result = self.gated(*self.args("revolve", self.stepped_request()))["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")

    def test_planar_same_area_wrong_rim_relation_cannot_pass_or_register(self):
        self.part()
        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        original = self.world.revolve

        def wrong(q):
            result = original(q)
            items = self.world.models["block.prt"]["geometry"]
            caps = [g for g in items if g.get("kind") == "surface" and g.get("type") == "plane"]
            for g in items:
                if g.get("kind") == "edge":
                    g["surfaces"] = [
                        caps[1]["ref"]
                        if ref == caps[0]["ref"]
                        else caps[0]["ref"]
                        if ref == caps[1]["ref"]
                        else ref
                        for ref in g["surfaces"]
                    ]
            return result

        self.world.drop = "feature.revolve"
        with patch.object(self.world, "revolve", side_effect=wrong):
            self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.world.drop = None
        error = self.fresh(
            "operation",
            "resolve",
            "--id",
            pre["preview"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "Equal cap areas but native physical rim adjacency is wrong",
            status=1,
        )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(self.world.ops().count("feature.revolve"), 1)

    def test_disjoint_coplanar_step_shoulders_match_distinct_radial_regions(self):
        self.part()
        request = copy.deepcopy(SHAFT)
        request["sketch"]["profile"] = {
            "type": "polygon",
            "points": [[2, 0], [10, 0], [10, 10], [8, 10], [8, 20], [4, 20], [4, 10], [2, 10]],
        }
        result = self.gated(*self.args("revolve", request))["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")

    def test_checked_snapshot_is_reused_only_after_successful_verification(self):
        from creo_cli import revolved

        self.part()
        with patch.object(revolved, "snapshot", wraps=revolved.snapshot) as read:
            result = self.gated(*self.args("revolve"))["data"]
        self.assertEqual(read.call_count, 3)  # preview, confirmation baseline, post-write proof
        self.assertEqual(
            result["receipt"]["extensions"]["creo"]["effects_readback"]["source"],
            "independent snapshot checked by this leaf verifier",
        )

    def fresh(self, *words, status=0):
        p = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, words)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(p.returncode, status, p.stdout[:1000] + p.stderr)
        return json.loads(p.stdout)

    def args(self, kind, body=None):
        body = (
            body
            or {
                "revolve": SHAFT,
                "datum-plane": {
                    "units": "mm",
                    "name": "OFFSET",
                    "offset": {"from": "FRONT", "distance": 5},
                },
                "datum-axis": {"name": "Y_AXIS", "through": ["RIGHT", "FRONT"]},
            }[kind]
        )
        return ("feature", kind, "--model", "block.prt", "--request", self.request(body))

    def test_wrong_signed_plane_offset_cannot_pass(self):
        self.part()
        original = self.world.datum_plane

        def wrong(q):
            result = original(q)
            result["geometry"]["origin"][2] *= -1
            return result

        request = self.request(
            {"units": "mm", "name": "OFFSET", "offset": {"from": "FRONT", "distance": 5}}
        )
        with patch.object(self.world, "datum_plane", side_effect=wrong):
            result = self.gated(
                "feature", "datum-plane", "--model", "block", "--request", request, status=1
            )
        self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_wrong_axis_position_and_direction_cannot_pass(self):
        self.part()
        original = self.world.datum_axis

        def wrong(q):
            result = original(q)
            result["geometry"].update(start=[2, 0, 10], end=[2, 0, -10], direction=[0, 0, -1])
            return result

        with patch.object(self.world, "datum_axis", side_effect=wrong):
            result = self.gated(
                "feature",
                "datum-axis",
                "--model",
                "block",
                "--request",
                self.request({"name": "Y_AXIS", "through": ["RIGHT", "FRONT"]}),
                status=1,
            )
        self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")

    def test_revolve_volume_without_current_solid_does_not_pass(self):
        self.part()
        original = self.world.revolve

        def phantom(q):
            result = original(q)
            ident = result["feature"]["id"]
            model = self.world.models["block.prt"]
            model["geometry"] = [
                g for g in model["geometry"] if g.get("feature", {}).get("id") != ident
            ]
            return result

        with patch.object(self.world, "revolve", side_effect=phantom):
            result = self.gated(
                "feature",
                "revolve",
                "--model",
                "block",
                "--request",
                self.request(SHAFT),
                status=1,
            )
        self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")

    def test_correct_offset_has_public_receipt(self):
        self.part()
        data = self.gated(
            "feature",
            "datum-plane",
            "--model",
            "block",
            "--request",
            self.request({"units": "mm", "offset": {"from": "FRONT", "distance": 5}}),
        )["data"]
        self.assertIn("outcome", data["receipt"])
        self.assertEqual(domain_receipt(data["receipt"])["status"], "completed")

    def test_full_shaft_and_axis_have_independent_proof(self):
        self.part()
        axis = self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "Y_AXIS", "through": ["RIGHT", "FRONT"]}),
        )["data"]
        self.assertEqual(axis["status"], "completed")
        result = self.gated(
            "feature", "revolve", "--model", "block", "--request", self.request(SHAFT)
        )["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(
            result["result"]["construction_intent"]["box"], [[-10, 0, -10], [10, 40, 10]]
        )

    def test_request_replacement_and_geometry_drift_are_zero_dispatch(self):
        self.part()
        for kind in ("datum-plane", "datum-axis", "revolve"):
            with self.subTest(kind=kind):
                args = self.args(kind)
                pre = self.cli(*args, "--dry-run")["data"]
                path = Path(args[-1])
                replacement = path.with_suffix(".new")
                replacement.write_bytes(path.read_bytes())
                os.replace(replacement, path)
                self.cli(*args, "--confirm", pre["confirm_token"], status=6)
                pre = self.cli(*args, "--dry-run")["data"]
                self.world.models["block.prt"]["geometry"][0]["origin"][0] += 1
                self.cli(*args, "--confirm", pre["confirm_token"], status=6)
                self.world.models["block.prt"]["geometry"][0]["origin"][0] -= 1
                self.assertNotIn("feature." + kind, self.world.ops())

    def test_scope_drift_is_zero_dispatch(self):
        self.part()
        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        original = scope.read_bytes()
        q = json.loads(original)
        q["effects"] = ["observe"]
        scope.write_text(json.dumps(q), encoding="utf8")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        scope.write_bytes(original)
        self.assertNotIn("feature.revolve", self.world.ops())

    def test_unsupported_variants_are_refused_before_write(self):
        self.part()
        for kind, body in (
            ("revolve", SHAFT | {"angle": 180}),
            (
                "datum-plane",
                {"units": "mm", "angle": {"from": "TOP", "through": "RIGHT", "degrees": 30}},
            ),
            ("datum-axis", {"through": ["FRONT"]}),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.cli(*self.args(kind, body), "--dry-run", status=2)["error"]["code"],
                    "E_UNSUPPORTED",
                )
                self.assertNotIn("feature." + kind, self.world.ops())

    def test_lost_reply_retained_intent_registers_without_replay(self):
        self.part()
        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        ident = pre["preview"]["operation_id"]
        self.world.drop = "feature.revolve"
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.world.drop = None
        Path(args[-1]).unlink()
        observation = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")[
            "data"
        ]["observation"]["construction_verification"]
        self.assertEqual(observation["can_register"], ["applied"])
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Fresh independent section, complete cylinders and planes match frozen shape and axis",
        )
        self.fresh("model", "save", "--model", "block.prt", "--dry-run")
        self.assertEqual(self.world.ops().count("feature.revolve"), 1)

    def test_same_volume_wrong_geometry_cannot_register_applied(self):
        self.part()
        original = self.world.revolve

        def displaced(q):
            result = original(q)
            m = self.world.models["block.prt"]
            for row in m["geometry"]:
                if row.get("type") == "cylinder":
                    row["axis"]["origin"][0] += 1
            return result

        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "feature.revolve"
        with patch.object(self.world, "revolve", side_effect=displaced):
            self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.world.drop = None
        ident = pre["preview"]["operation_id"]
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Feature volume matches but axes are displaced; must not register applied",
            status=1,
        )
        self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_native_angle_mismatch_is_not_hidden_by_full_volume(self):
        self.part()
        original = self.world.revolve

        def wrong(q):
            result = original(q)
            self.world.models["block.prt"]["features"][-1]["native_definition"]["angle"] = 270
            return result

        with patch.object(self.world, "revolve", side_effect=wrong):
            error = self.gated(*self.args("revolve"), status=1)["error"]
        self.assertIn(
            "revolve_definition_matches", [c["check"] for c in error["details"]["failed_checks"]]
        )

    def test_missing_geometry_after_lost_reply_cannot_register_partial(self):
        self.part()
        original = self.world.revolve

        def unreadable(q):
            result = original(q)
            for row in self.world.models["block.prt"]["geometry"]:
                if row.get("type") == "cylinder":
                    row["axis"].pop("direction")
            return result

        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "feature.revolve"
        with patch.object(self.world, "revolve", side_effect=unreadable):
            self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.world.drop = None
        error = self.fresh(
            "operation",
            "resolve",
            "--id",
            pre["preview"]["operation_id"],
            "--outcome",
            "partial",
            "--evidence",
            "Native cylinder direction is unreadable; retain unknown",
            status=1,
        )["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")

    def test_missing_rim_adjacency_retains_unknown(self):
        self.part()
        original = self.world.revolve

        def incomplete(q):
            result = original(q)
            for row in self.world.models["block.prt"]["geometry"]:
                if row.get("kind") == "edge":
                    row.pop("surfaces", None)
            return result

        args = self.args("revolve")
        pre = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "feature.revolve"
        with patch.object(self.world, "revolve", side_effect=incomplete):
            self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.world.drop = None
        self.fresh(
            "operation",
            "resolve",
            "--id",
            pre["preview"]["operation_id"],
            "--outcome",
            "partial",
            "--evidence",
            "Current rim adjacency is incomplete; retain the unresolved outcome",
            status=1,
        )

    def test_final_receipt_failure_fresh_process_and_duplicate(self):
        self.part()
        args = self.args("datum-plane")
        pre = self.cli(*args, "--dry-run")["data"]
        update = operations.update

        def fail(record):
            if record.get("driver_receipt"):
                raise Error("E_IO", "injected final receipt failure")
            return update(record)

        with patch.object(operations, "update", side_effect=fail):
            self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        ident = pre["preview"]["operation_id"]
        with patch.dict(os.environ, self.env, clear=True):
            record = operations.get(ident)
        self.assertEqual(record["status"], "running")
        self.assertIsNone(record["driver_receipt"])
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        # The service did return, but the final receipt could not be retained.
        # Its execution facet is separate from an unknown overall outcome.
        self.assertTrue(record["service_reported_done"])
        self.assertEqual(shown["status"], "unknown")
        self.assertEqual(shown["receipt"]["outcome"]["persistence"], "unknown")
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "completed")
        self.assertEqual(shown["receipt"]["outcome"]["change"], "unknown")
        self.assertEqual(shown["receipt"]["outcome"]["verification"]["status"], "incomplete")
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent signed plane position normal and constraint agree with retained intent",
        )
        self.fresh(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_incomplete_existing_native_definition_refuses_before_setter(self):
        self.part()
        existing = self.world.models["block.prt"]["features"][0]
        failure = {
            "complete": False,
            "source": "controlled HTTP fixture",
            "error": {"code": "E_CREO", "message": "controlled nested native read failure"},
        }
        existing["native_definition"] = copy.deepcopy(failure)
        answer = self.cli(*self.args("datum-plane"), "--dry-run", status=1)
        self.assertEqual(answer["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(answer["error"]["details"]["feature"], str(existing["id"]))
        self.assertEqual(answer["error"]["details"]["native_definition"], failure)
        self.assertEqual(answer["error"]["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 0)

    def _existing_datum(self, kind):
        model = self.world.models["block.prt"]
        if kind == "plane":
            return model["features"][0]
        feature = {
            "id": 901,
            "name": "FIXTURE_AXIS",
            "type": "FEATTYPE_DATUM_AXIS",
            "status": "FEAT_ACTIVE",
            "visible": True,
            "parents": [],
            "children": [],
            "surfaces": 0,
            "native_definition": {
                "complete": True,
                "kind": "datum_axis",
                "source": "controlled fixture",
            },
        }
        model["features"].append(feature)
        return feature

    def test_missing_and_null_existing_datum_definitions_refuse_before_setter(self):
        self.part()
        for kind in ("plane", "axis"):
            existing = self._existing_datum(kind)
            valid = copy.deepcopy(existing["native_definition"])
            for status in ("missing", "null"):
                with self.subTest(kind=kind, status=status):
                    if status == "missing":
                        existing.pop("native_definition")
                    else:
                        existing["native_definition"] = None
                    answer = self.cli(*self.args("datum-plane"), "--dry-run", status=1)
                    self.assertEqual(answer["error"]["code"], "E_VERIFY_INCOMPLETE")
                    self.assertEqual(answer["error"]["details"]["feature"], str(existing["id"]))
                    self.assertEqual(answer["error"]["details"]["native_definition_status"], status)
                    self.assertEqual(answer["error"]["details"]["dispatch_state"], "not_started")
                    self.assertEqual(self.world.ops().count("feature.datum-plane"), 0)
                    existing["native_definition"] = copy.deepcopy(valid)

    def _missing_datum_definition_after_setter(self, kind, status):
        self.part()
        existing = self._existing_datum(kind)
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.datum_plane

        def mutate(q):
            result = original(q)
            if status == "missing":
                existing.pop("native_definition")
            else:
                existing["native_definition"] = None
            return result

        with patch.object(self.world, "datum_plane", side_effect=mutate):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(answer["error"]["code"], "E_OUTCOME_UNKNOWN")
        receipt = answer["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        observed = receipt["extensions"]["creo"]["effects_readback_error"]
        self.assertEqual(observed["details"]["native_definition_status"], status)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_missing_plane_definition_after_setter_is_unknown(self):
        self._missing_datum_definition_after_setter("plane", "missing")

    def test_null_plane_definition_after_setter_is_unknown(self):
        self._missing_datum_definition_after_setter("plane", "null")

    def test_missing_axis_definition_after_setter_is_unknown(self):
        self._missing_datum_definition_after_setter("axis", "missing")

    def test_null_axis_definition_after_setter_is_unknown(self):
        self._missing_datum_definition_after_setter("axis", "null")

    def test_post_setter_nested_failure_cannot_claim_protected_state(self):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.datum_plane
        failure = {
            "complete": False,
            "source": "controlled HTTP fixture",
            "error": {"code": "E_CREO", "message": "controlled nested native read failure"},
        }

        def mutate(q):
            result = original(q)
            self.world.models["block.prt"]["features"][0]["native_definition"] = copy.deepcopy(
                failure
            )
            return result

        with patch.object(self.world, "datum_plane", side_effect=mutate):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(answer["error"]["code"], "E_OUTCOME_UNKNOWN")
        outcome = answer["error"]["details"]["receipt"]["outcome"]
        self.assertEqual(outcome["change"], "unknown")
        self.assertEqual(outcome["persistence"], "unknown")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        observed = outcome["verification"]["extensions"]["creo"]["observations"]
        self.assertEqual(observed[0]["error"]["details"]["native_definition"], failure)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def _single_incomplete_read_never_uses_a_later_observation(self, unchanged):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        before = copy.deepcopy(self.world.models["block.prt"])
        state = {"setter": False, "failed": 0, "feature_reads": 0}
        failure = {
            "complete": False,
            "error": {"code": "E_CREO", "message": "controlled one-time nested failure"},
        }

        def intercept(op, q):
            result = original(op, q)
            if op == "feature.datum-plane":
                state["setter"] = True
                if unchanged:
                    self.world.models["block.prt"] = copy.deepcopy(before)
            if state["setter"] and op == "feature.show":
                state["feature_reads"] += 1
                if str(q.get("feature")) == "1" and state["failed"] == 0:
                    result["native_definition"] = copy.deepcopy(failure)
                    state["failed"] += 1
            return result

        with patch.object(self.world, "op", side_effect=intercept):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(answer["error"]["code"], "E_OUTCOME_UNKNOWN")
        receipt = answer["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["execution"], "completed")
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        actual_error = receipt["extensions"]["creo"]["effects_readback_error"]
        self.assertEqual(actual_error["details"]["native_definition"], failure)
        self.assertEqual(state["failed"], 1)
        self.assertEqual(state["feature_reads"], 1)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_single_failed_read_cannot_use_later_changed_state(self):
        self._single_incomplete_read_never_uses_a_later_observation(False)

    def test_single_failed_read_cannot_use_later_unchanged_state(self):
        self._single_incomplete_read_never_uses_a_later_observation(True)

    def _nested_stop_is_preserved_without_another_getter(self, code, exit_status):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        state = {"setter": False, "feature_reads": 0}
        nested = {"code": code, "message": "controlled nested stop", "details": {"synthetic": True}}

        def intercept(op, q):
            result = original(op, q)
            if op == "feature.datum-plane":
                state["setter"] = True
            if state["setter"] and op == "feature.show" and str(q.get("feature")) == "1":
                state["feature_reads"] += 1
                result["native_definition"] = {"complete": False, "error": copy.deepcopy(nested)}
            return result

        with patch.object(self.world, "op", side_effect=intercept):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=exit_status)
        error = answer["error"]
        field = (
            "native_read_error" if code == "E_NATIVE_READ_PENDING" else "native_diagnostic_error"
        )
        retained = error["details"][field]
        self.assertEqual(retained["code"], code)
        self.assertEqual(retained, nested)
        self.assertIn("stop further CAD dispatch", error["details"]["next_action"])
        outcome = error["details"]["receipt"]["outcome"]
        self.assertEqual(outcome["change"], "unknown")
        self.assertEqual(outcome["persistence"], "unknown")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        observations = outcome["verification"]["extensions"]["creo"]["observations"]
        self.assertEqual(observations[0]["error"]["details"]["native_definition"]["error"], nested)
        self.assertEqual(state["feature_reads"], 1)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_nested_pending_stop_is_not_downgraded(self):
        self._nested_stop_is_preserved_without_another_getter("E_NATIVE_READ_PENDING", 6)

    def test_nested_diagnostic_stop_is_not_downgraded(self):
        self._nested_stop_is_preserved_without_another_getter("E_NATIVE_DIAGNOSTIC", 1)

    def _first_parent_getter_failure_stops_verification(self, operation, code, exit_status):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        state = {"setter": False, "failed": False, "later_getters": 0}

        def intercept(op, q):
            if state["setter"] and state["failed"]:
                state["later_getters"] += 1
            if state["setter"] and op == operation and not state["failed"]:
                state["failed"] = True
                raise Refused(
                    code, "controlled first verifier getter failure", stage="controlled_read"
                )
            result = original(op, q)
            if op == "feature.datum-plane":
                state["setter"] = True
            return result

        with patch.object(self.world, "op", side_effect=intercept):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=exit_status)
        error = answer["error"]
        outcome = error["details"]["receipt"]["outcome"]
        self.assertEqual(outcome["change"], "unknown")
        self.assertEqual(outcome["persistence"], "unknown")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        self.assertEqual(state["later_getters"], 0)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)
        if code == "E_CREO":
            observation = outcome["verification"]["extensions"]["creo"]["observations"][0]
            first = observation["error"]["details"]["first_readback_error"]
            self.assertEqual(first["details"]["service_code"], "E_CREO")
            self.assertEqual(
                first["details"]["service_message"], "controlled first verifier getter failure"
            )
        else:
            field = (
                "native_read_error"
                if code == "E_NATIVE_READ_PENDING"
                else "native_diagnostic_error"
            )
            self.assertEqual(error["details"][field]["code"], code)
            self.assertIn("stop further CAD dispatch", error["details"]["next_action"])

    def test_feature_list_first_failure_never_reads_a_later_snapshot(self):
        self._first_parent_getter_failure_stops_verification("feature.list", "E_CREO", 6)

    def test_model_show_first_failure_never_reads_a_later_snapshot(self):
        self._first_parent_getter_failure_stops_verification("model.show", "E_CREO", 6)

    def test_parent_pending_stop_never_reads_a_later_snapshot(self):
        self._first_parent_getter_failure_stops_verification(
            "feature.list", "E_NATIVE_READ_PENDING", 6
        )

    def test_parent_diagnostic_stop_never_reads_a_later_snapshot(self):
        self._first_parent_getter_failure_stops_verification(
            "feature.list", "E_NATIVE_DIAGNOSTIC", 1
        )

    def _setter_failure_then_nested_readback_failure(self, code, exit_status):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        state = {"setter_attempts": 0, "feature_reads": 0, "after_failure_ops": 0, "failed": False}
        nested = {
            "code": code,
            "message": "controlled read failure",
            "details": {"synthetic": True},
        }

        def intercept(op, q):
            if state["failed"]:
                state["after_failure_ops"] += 1
            if op == "feature.datum-plane":
                state["setter_attempts"] += 1
                self.world.models["block.prt"]["modified"] = True
                raise Refused("E_CREO", "controlled setter failure", stage="model_setter")
            result = original(op, q)
            if state["setter_attempts"] and op == "feature.show" and str(q.get("feature")) == "1":
                state["feature_reads"] += 1
                result["native_definition"] = {"complete": False, "error": copy.deepcopy(nested)}
                state["failed"] = True
            return result

        with patch.object(self.world, "op", side_effect=intercept):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=exit_status)
        error = answer["error"]
        self.assertEqual(error["details"]["service_code"], "E_CREO")
        self.assertEqual(error["details"]["service_message"], "controlled setter failure")
        receipt = error["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        retained = receipt["extensions"]["creo"]["effects_readback_error"]
        self.assertEqual(retained["details"]["native_definition"]["error"], nested)
        if code in ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"):
            field = (
                "native_read_error"
                if code == "E_NATIVE_READ_PENDING"
                else "native_diagnostic_error"
            )
            self.assertEqual(error["details"][field]["code"], code)
            self.assertIn("stop further CAD dispatch", error["details"]["next_action"])
        self.assertEqual(
            state,
            {"setter_attempts": 1, "feature_reads": 1, "after_failure_ops": 0, "failed": True},
        )

    def test_setter_failure_retains_first_nested_readback_error(self):
        self._setter_failure_then_nested_readback_failure("E_CREO", 6)

    def test_setter_failure_retains_nested_pending_stop(self):
        self._setter_failure_then_nested_readback_failure("E_NATIVE_READ_PENDING", 6)

    def test_setter_failure_retains_nested_diagnostic_stop(self):
        self._setter_failure_then_nested_readback_failure("E_NATIVE_DIAGNOSTIC", 1)

    def test_missing_bound_guard_downgrades_public_verification(self):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = revolved.checked_plan

        def without_guard(client, plan, request):
            plan = original(client, plan, request)
            verify = plan.verify

            def remove_guard_after_verification(c, data):
                result = verify(c, data)
                del plan._verified_observation_guard
                return result

            plan.verify = remove_guard_after_verification
            return plan

        with patch.object(revolved, "checked_plan", side_effect=without_guard):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(answer["error"]["code"], "E_OUTCOME_UNKNOWN")
        receipt = answer["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["change"], "unknown")
        self.assertEqual(receipt["outcome"]["persistence"], "unknown")
        self.assertEqual(receipt["outcome"]["verification"]["status"], "incomplete")
        self.assertTrue(receipt["outcome"]["verification"]["checks"])
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def _final_feature_list_drift_is_not_a_verified_success(self, drift):
        self.part()
        args = self.args("datum-plane", {"units": "mm", "offset": {"from": "FRONT", "distance": 5}})
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op
        before_ids = {str(row["id"]) for row in self.world.models["block.prt"]["features"]}
        state = {"setter": False, "feature_lists": 0}

        def intercept(op, q):
            result = original(op, q)
            if op == "feature.datum-plane":
                state["setter"] = True
            if state["setter"] and op == "feature.list":
                state["feature_lists"] += 1
                if state["feature_lists"] == 2:
                    target = next(
                        row for row in result["features"] if str(row["id"]) not in before_ids
                    )
                    if drift == "missing_name":
                        target.pop("name", None)
                    elif drift == "different_default_name":
                        target["name"] = "ANOTHER_NATIVE_DEFAULT"
                    else:
                        result["features"].append(copy.deepcopy(target))
            return result

        expected_status = 1 if drift == "different_default_name" else 6
        with patch.object(self.world, "op", side_effect=intercept):
            answer = self.cli(*args, "--confirm", preview["confirm_token"], status=expected_status)
        self.assertFalse(answer["ok"])
        receipt = answer["error"]["details"]["receipt"]
        verification = receipt["outcome"]["verification"]
        self.assertNotEqual(verification["status"], "passed")
        if expected_status == 1:
            checks = verification["extensions"]["creo"]["checks"]
            consistency = next(
                item for item in checks if item["check"] == "feature_observation_consistent"
            )
            self.assertFalse(consistency["passed"])
        else:
            self.assertEqual(receipt["outcome"]["change"], "unknown")
            self.assertEqual(receipt["outcome"]["persistence"], "unknown")
            self.assertEqual(verification["status"], "incomplete")
            self.assertEqual(
                receipt["extensions"]["creo"]["effects_readback_error"]["code"],
                "E_VERIFY_INCOMPLETE",
            )
        self.assertEqual(state["feature_lists"], 2)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_final_feature_snapshot_missing_name_cannot_reuse_earlier_pass(self):
        self._final_feature_list_drift_is_not_a_verified_success("missing_name")

    def test_final_feature_snapshot_different_default_name_is_drift(self):
        self._final_feature_list_drift_is_not_a_verified_success("different_default_name")

    def test_final_feature_snapshot_duplicate_identity_is_not_unique(self):
        self._final_feature_list_drift_is_not_a_verified_success("duplicate")

    def test_final_feature_snapshot_supplies_the_passed_receipt_observation(self):
        self.part()
        args = self.args("datum-plane", {"units": "mm", "offset": {"from": "FRONT", "distance": 5}})
        preview = self.cli(*args, "--dry-run")["data"]
        answer = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        verification = answer["verification"]
        self.assertEqual(verification["status"], "passed")
        name_check = next(
            c for c in verification["checks"] if c["check"] == "feature_name_native_default"
        )
        self.assertEqual(name_check["observation_source"], "independent_construction_snapshot")
        self.assertTrue(name_check["earlier_observation_passed"])
        comparison = next(
            o
            for o in verification["observations"]
            if o["observation"] == "feature_observation_comparison"
        )
        self.assertEqual(comparison["earlier"], comparison["final"])
        observation = next(
            o["current"]
            for o in verification["observations"]
            if o["observation"] == "independent_construction_snapshot"
        )
        self.assertEqual(
            answer["receipt"]["extensions"]["creo"]["effects_readback"]["after"], observation
        )

    def _construction_persistence_uses_observed_modified(self, value, expected):
        self.part()
        args = self.args("datum-plane")
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.datum_plane

        def mutate(q):
            result = original(q)
            self.world.models["block.prt"]["modified"] = value
            return result

        with patch.object(self.world, "datum_plane", side_effect=mutate):
            answer = self.cli(
                *args,
                "--confirm",
                preview["confirm_token"],
                status=6 if expected == "unknown" else 0,
            )
        receipt = (
            answer["error"]["details"]["receipt"]
            if expected == "unknown"
            else answer["data"]["receipt"]
        )
        self.assertEqual(receipt["outcome"]["persistence"], expected)
        self.assertEqual(self.world.ops().count("feature.datum-plane"), 1)

    def test_construction_observed_dirty_is_unsaved(self):
        self._construction_persistence_uses_observed_modified(True, "unsaved")

    def test_construction_unknown_modified_is_unknown(self):
        self._construction_persistence_uses_observed_modified(None, "unknown")

    def test_construction_changed_but_clean_does_not_claim_unchanged(self):
        self._construction_persistence_uses_observed_modified(False, "unknown")

    def test_mixed_case_references_resolve_actual_native_items(self):
        self.part()
        for kind, request in (
            (
                "datum-plane",
                {"units": "mm", "name": "OFFSET", "offset": {"from": "fRoNt", "distance": -5}},
            ),
            ("datum-axis", {"name": "Y_AXIS", "through": ["oFfSeT", "rIGhT"]}),
        ):
            self.gated(*self.args(kind, request))
        model = copy.deepcopy(self.world.models["block.prt"])
        error = self.cli(
            *self.args("datum-axis", {"through": ["axis:99999"]}), "--dry-run", status=3
        )
        self.assertEqual(error["error"]["code"], "E_NOT_FOUND")
        self.assertEqual(model, self.world.models["block.prt"])
