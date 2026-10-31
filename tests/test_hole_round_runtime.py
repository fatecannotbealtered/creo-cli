"""Bounded machining lifecycle regressions; fixture evidence is not native acceptance."""

import json
import os
import subprocess
import sys
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests.fixture_features import Refusal
from tests.test_commands import ROOT
from tests.test_features import Built


class MachiningRuntime(Built):
    def test_current_reference_changes_reject_old_round_confirmation(self):
        self.block()
        edge = self.edges([0, 0, -1])[0]["ref"]
        request = self.request({"units": "mm", "radius": 1, "edges": [edge]})
        args = ("feature", "round", "--model", "block.prt", "--request", request)
        pre = self.cli(*args, "--dry-run")["data"]
        actual = next(g for g in self.world.models["block.prt"]["geometry"] if g["ref"] == edge)
        actual["end"][0] += 1
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("feature.round", self.world.ops())

    def test_missing_getter_capability_and_deleted_request_are_zero_dispatch(self):
        from pathlib import Path

        self.block()
        args = self.hole_args()
        pre = self.cli(*args, "--dry-run")["data"]
        Path(args[-1]).unlink()
        self.cli(*args, "--confirm", pre["confirm_token"], status=3)
        self.world.capabilities.pop("machining_feature_readback")
        self.cli(*self.hole_args(), "--dry-run", status=4)
        self.assertNotIn("feature.hole", self.world.ops())

    def test_final_receipt_failure_is_unknown_in_fresh_process_for_both_paths(self):
        self.block()
        for kind in ("hole", "round"):
            with self.subTest(kind=kind):
                args = (
                    self.hole_args()
                    if kind == "hole"
                    else (
                        "feature",
                        "round",
                        "--model",
                        "block.prt",
                        "--request",
                        self.request(
                            {
                                "units": "mm",
                                "radius": 1,
                                "edges": [self.edges([0, 0, -1])[0]["ref"]],
                            },
                            "final-round.json",
                        ),
                    )
                )
                plan = self.cli(*args, "--dry-run")["data"]
                original = operations.update

                def final_failure(record, original=original):
                    if record.get("driver_receipt"):
                        raise Error("E_IO", "controlled final public receipt failure")
                    return original(record)

                with patch.object(operations, "update", side_effect=final_failure):
                    error = self.cli(*args, "--confirm", plan["confirm_token"], status=6)["error"]
                self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
                ident = plan["preview"]["operation_id"]
                with patch.dict(os.environ, self.env, clear=True):
                    disk = operations.get(ident)
                self.assertEqual(disk["status"], "running")
                self.assertIsNone(disk["driver_receipt"])
                result = subprocess.run(
                    [sys.executable, "-m", "creo_cli", "operation", "show", "--id", ident],
                    cwd=ROOT,
                    env=self.env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                shown = json.loads(result.stdout)["data"]["operation_status"]
                self.assertEqual(shown["receipt"]["outcome"]["persistence"], "unknown")
                self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)
                self.cli(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "applied",
                    "--evidence",
                    "independent fixture current-solid geometry and feature definitions checked",
                )

    def hole_args(self, **updates):
        body = {
            "units": "mm",
            "name": "HOLE_A",
            "diameter": 6,
            "depth": "through_all",
            "placement": {
                "surface": self.top()["ref"],
                "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
            },
        }
        body.update(updates)
        return ("feature", "hole", "--model", "block.prt", "--request", self.request(body))

    def test_active_phantom_hole_with_no_current_solid_cut_cannot_pass(self):
        self.block()
        original = self.world.hole

        def phantom(q):
            old = self.world.models["block.prt"]["volume"]
            result = original(q)
            m = self.world.models["block.prt"]
            ident = result["feature"]["id"]
            m["geometry"] = [
                g
                for g in m["geometry"]
                if not (g.get("type") == "cylinder" and g.get("feature", {}).get("id") == ident)
            ]
            m["volume"] = old
            return result

        with patch.object(self.world, "hole", side_effect=phantom):
            error = self.gated(*self.hole_args(), status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertIn(
            "hole_is_in_current_solid", [c["check"] for c in error["details"]["failed_checks"]]
        )
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_wrong_center_cannot_borrow_correct_diameter_echo(self):
        self.block()
        original = self.world.hole

        def displaced(q):
            result = original(q)
            own = result["feature"]["id"]
            for g in self.world.models["block.prt"]["geometry"]:
                if g.get("type") == "cylinder" and g.get("feature", {}).get("id") == own:
                    g["axis"]["origin"][0] += 2
            return result

        with patch.object(self.world, "hole", side_effect=displaced):
            error = self.gated(*self.hole_args(), status=1)["error"]
        self.assertIn(
            "hole_diameter_and_center", [c["check"] for c in error["details"]["failed_checks"]]
        )

    def test_native_round_dimension_does_not_replace_actual_radius_readback(self):
        self.block()
        original = self.world.edge_feature

        def wrong(q, round_):
            result = original(q, round_)
            for g in self.world.models["block.prt"]["geometry"]:
                if (
                    g.get("type") == "cylinder"
                    and g.get("feature", {}).get("id") == result["feature"]["id"]
                ):
                    g["radius"] = 2
            return result

        request = self.request(
            {"units": "mm", "radius": 1, "edges": [self.edges([0, 0, -1])[0]["ref"]]}
        )
        with patch.object(self.world, "edge_feature", side_effect=wrong):
            error = self.gated(
                "feature", "round", "--model", "block.prt", "--request", request, status=1
            )["error"]
        self.assertIn(
            "round_radius_in_current_solid", [c["check"] for c in error["details"]["failed_checks"]]
        )

    def test_outside_hole_and_impossible_round_reject_before_dispatch(self):
        self.block()
        self.cli(*self.hole_args(diameter=100), "--dry-run", status=2)
        request = self.request(
            {"units": "mm", "radius": 100, "edges": [self.edges([0, 0, -1])[0]["ref"]]}
        )
        self.cli(
            "feature", "round", "--model", "block.prt", "--request", request, "--dry-run", status=2
        )
        self.assertNotIn("feature.hole", self.world.ops())
        self.assertNotIn("feature.round", self.world.ops())

    def test_failed_native_write_that_only_dirties_model_is_partial(self):
        self.block()
        self.gated("model", "save", "--model", "block.prt")

        def dirty(q):
            self.world.models["block.prt"]["modified"] = True
            raise Refusal("E_CREO", "failed after marking model dirty")

        with patch.object(self.world, "hole", side_effect=dirty):
            error = self.gated(*self.hole_args(), status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")

    def test_incomplete_geometry_is_explicit_and_pre_dispatch(self):
        self.block()
        args = self.hole_args()
        with patch.object(
            self.world, "geometry_list", return_value={"model": "block.prt", "items": None}
        ):
            out = self.cli(*args, "--dry-run", status=1)
        self.assertEqual(out["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("feature.hole", self.world.ops())

    def test_both_existing_paths_preallocate_public_operation(self):
        self.block()
        requests = {
            "round": {"units": "mm", "radius": 1, "edges": [self.edges([0, 0, -1])[0]["ref"]]},
            "hole": {
                "units": "mm",
                "diameter": 6,
                "depth": "through_all",
                "placement": {
                    "surface": self.top()["ref"],
                    "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
                },
            },
        }
        for command, body in requests.items():
            with self.subTest(command=command):
                pre = self.cli(
                    "feature",
                    command,
                    "--model",
                    "block.prt",
                    "--request",
                    self.request(body, command + ".json"),
                    "--dry-run",
                )["data"]
                self.assertIn("operation_id", pre["preview"])

    def test_same_bytes_request_replacement_invalidates_round_preview(self):
        self.block()
        path = self.request(
            {"units": "mm", "radius": 1, "edges": [self.edges([0, 0, -1])[0]["ref"]]}
        )
        from pathlib import Path

        path = Path(path)
        args = ("feature", "round", "--model", "block.prt", "--request", path)
        pre = self.cli(*args, "--dry-run")["data"]
        replacement = path.with_suffix(".new")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("feature.round", self.world.ops())
