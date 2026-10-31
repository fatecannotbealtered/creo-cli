"""Public bounded shell lifecycle against explicit meshes; no native claim."""

import copy
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests import fixture_prismatic, test_features
from tests.test_commands import ROOT


class ShellRuntime(test_features.Built):
    def setUp(self):
        super().setUp()
        self.block()
        self.body = {
            "units": "mm",
            "name": "HOLLOW",
            "thickness": 1.5,
            "remove": [self.top()["ref"]],
        }

    def args(self, body=None):
        return (
            "feature",
            "shell",
            "--model",
            "block",
            "--request",
            self.request(body or self.body),
        )

    def fresh(self, *args, status=0):
        result = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, status, result.stdout[:1000])
        return json.loads(result.stdout)

    def test_public_plan_definition_and_complete_boundaries(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        self.assertNotIn("feature.shell", self.world.ops())
        self.assertIn("operation_id", p["preview"])
        result = self.cli(*args, "--confirm", p["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        feature = self.cli("feature", "show", "--model", "block", "--feature", "HOLLOW")["data"]
        self.assertTrue(feature["native_solid_geometry"]["complete"])
        self.assertEqual(feature["native_definition"]["removed"], self.body["remove"])
        self.assertEqual(
            self.cli("model", "show", "--model", "block")["data"]["mass_properties"]["volume"],
            2653.5,
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.shell"), 1)

    def test_thickness_roundtrip_and_save_are_explicit_public_steps(self):
        self.gated(*self.args())
        dims = self.cli("dimension", "list", "--model", "block", "--feature", "HOLLOW")["data"][
            "items"
        ]
        dim = next(d for d in dims if d.get("type"))
        for thickness, expected in [(2, 3392), (1.5, 2653.5)]:
            self.gated(
                "dimension",
                "set",
                "--model",
                "block",
                "--dimension",
                dim["id"],
                "--value",
                str(thickness),
                "--units",
                "mm",
            )
            actual = self.cli("model", "show", "--model", "block")["data"]
            self.assertEqual(actual["mass_properties"]["volume"], expected)
        self.gated("model", "save", "--model", "block")
        self.assertEqual(
            self.cli("feature", "show", "--model", "block", "--feature", "HOLLOW")["data"][
                "native_definition"
            ]["thickness"],
            1.5,
        )
        self.gated("model", "close", "--model", "block")
        # Native persistence/reopen belongs to the real-Creo case, not this mesh fixture.

    def test_fractional_thickness_uses_the_same_native_coordinate_resolution(self):
        result = self.gated(*self.args(self.body | {"thickness": 1.2345671}))["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.world.ops().count("feature.shell"), 1)

    def test_old_creation_precision_profile_refuses_before_dispatch(self):
        self.world.capabilities["prismatic_shell_readback"] = 1
        self.cli(*self.args(), "--dry-run", status=4)
        self.assertNotIn("feature.shell", self.world.ops())

    def test_readback_reply_loss_keeps_completed_execution_but_unknown_effect(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def lose_readback(op, request):
            result = original(op, request)
            if op == "feature.shell":
                self.world.drop = "feature.show"
            return result

        self.world.events.clear()
        with patch.object(self.world, "op", side_effect=lose_readback):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        receipt = error["details"]["receipt"]
        outcome = receipt["outcome"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(outcome["execution"], "completed")
        self.assertEqual(outcome["change"], "unknown")
        self.assertEqual(outcome["persistence"], "unknown")
        self.assertEqual(outcome["verification"]["status"], "incomplete")
        # Earlier independent getters returned, but the required protected snapshot
        # did not finish. The old test cleared drop on a second feature.show and
        # relied on post-error sampling to establish partial change. That sampling
        # is now forbidden; retain the setter reply without promoting it to proof.
        domain = receipt["extensions"]["creo"]["domain_result"]
        self.assertEqual(domain["feature"]["name"], "HOLLOW")
        calls = self.world.ops()
        lost = calls.index("feature.show", calls.index("feature.shell") + 1)
        self.assertEqual(calls[lost + 1 :], [])
        check = next(
            x
            for x in outcome["verification"]["not_checked"]
            if x["id"] == "postconditions_read_back_independently"
        )
        self.assertTrue(check["required"])
        stored = self.cli("operation", "show", "--id", receipt["operation_id"])["data"][
            "operation_status"
        ]
        self.assertEqual(stored["receipt"], receipt)
        before_repeat = list(self.world.events)
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.events, before_repeat)
        self.assertEqual(self.world.ops().count("feature.shell"), 1)

    def test_preflight_wrong_face_and_unprovable_thickness_zero_dispatch(self):
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        bottom = next(f["ref"] for f in faces if f["normal"] == [0, 0, -1])
        for body in [
            self.body | {"thickness": 10},
            self.body | {"thickness": 1e-9},
            self.body | {"remove": [bottom]},
        ]:
            with self.subTest(body=body):
                self.cli(*self.args(body), "--dry-run", status=2)
        self.assertNotIn("feature.shell", self.world.ops())

    def test_wrong_model_units_or_incomplete_body_cannot_authorize_shell(self):
        original = self.world.op
        for variant in ("model", "units", "body", "item"):
            with self.subTest(variant=variant):

                def broken(op, request, variant=variant):
                    result = original(op, request)
                    if op == "geometry.list" and request.get("profile"):
                        result = copy.deepcopy(result)
                        if variant == "model":
                            result["model"] = "foreign.prt"
                        elif variant == "units":
                            result["units"]["length"] = "in"
                        elif variant == "body":
                            result["body"] = None
                        else:
                            result["items"][0] = None
                    return result

                with patch.object(self.world, "op", side_effect=broken):
                    self.cli(*self.args(), "--dry-run", status=1)
        self.assertNotIn("feature.shell", self.world.ops())

    def test_request_and_geometry_drift_refuse_old_confirmation(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        source = Path(args[-1])
        replacement = source.with_suffix(".new")
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        p = self.cli(*args, "--dry-run")["data"]
        self.world.models["block.prt"]["geometry"][-1]["end"][0] += 1
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertNotIn("feature.shell", self.world.ops())

    def test_scope_drift_and_missing_native_capability_are_zero_dispatch(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        before = scope.read_bytes()
        data = json.loads(before)
        data["effects"] = ["observe"]
        scope.write_text(json.dumps(data))
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        scope.write_bytes(before)
        self.world.capabilities.pop("prismatic_shell_readback")
        self.cli(*args, "--dry-run", status=4)
        self.assertNotIn("feature.shell", self.world.ops())

    def lost_or_receipt(self, *, disk_fault):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        db = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        if disk_fault:
            with closing(sqlite3.connect(db)) as con, con:
                con.execute(
                    "CREATE TRIGGER shell_receipt_failure BEFORE UPDATE OF body ON operations "
                    f"WHEN NEW.id='{ident}' AND "
                    "json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
                    "BEGIN SELECT RAISE(ABORT,'final shell receipt fault'); END"
                )
        else:
            self.world.drop = "feature.shell"
        try:
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        finally:
            self.world.drop = None
            if disk_fault:
                with closing(sqlite3.connect(db)) as con, con:
                    con.execute("DROP TRIGGER shell_receipt_failure")
        status = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        outcome = status["receipt"]["outcome"]
        # A public-record commit failure does not erase the retained successful
        # setter reply. A lost setter reply has no such completion witness.
        self.assertEqual(outcome["execution"], "completed" if disk_fault else "unknown")
        if disk_fault:
            self.assertEqual(outcome["change"], "unknown")
            self.assertEqual(outcome["persistence"], "unknown")
            self.assertEqual(outcome["verification"]["status"], "incomplete")
            missing = next(
                check
                for check in outcome["verification"]["not_checked"]
                if check["id"] == "requested_postconditions"
            )
            self.assertTrue(missing["required"])
            self.assertNotIn("outside", missing["reason"])
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(
            query["observation"]["prismatic_verification"]["can_register"], ["applied"]
        )
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent complete native body contours and definition match frozen intent",
        )
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(
            shown["extensions"]["creo"]["prismatic_inspection"]["evidence_status"], "verified"
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.shell"), 1)

    def test_reply_loss_requires_current_body_inspection(self):
        self.lost_or_receipt(disk_fault=False)

    def test_final_receipt_failure_can_be_queried_from_new_process(self):
        self.lost_or_receipt(disk_fault=True)

    def test_wrong_walls_even_with_expected_volume_do_not_register_applied(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def wrong(op, request):
            result = original(op, request)
            if op == "feature.shell":
                m = self.world.models["block.prt"]
                f = self.world.feature(m, "HOLLOW")
                intended_volume = m["volume"]
                fixture_prismatic.hollow(self.world, m, f, 1.25, f["shell_bounds"])
                m["volume"] = intended_volume
            return result

        self.world.drop = "feature.shell"
        with patch.object(self.world, "op", side_effect=wrong):
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        ident = p["preview"]["operation_id"]
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        proof = query["observation"]["prismatic_verification"]
        self.assertNotIn("applied", proof["can_register"])
        self.assertFalse(proof["accepted"])
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Matching feature getter and volume do not prove the wall boundary",
            "--dry-run",
            status=1,
        )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_incomplete_contour_readback_keeps_outcome_unresolved(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "feature.shell"
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        original = self.world.op

        def incomplete(op, request):
            result = original(op, request)
            if op == "geometry.list" and request.get("profile"):
                result = copy.deepcopy(result)
                result["items"][0].pop("boundary_loops")
            return result

        with patch.object(self.world, "op", side_effect=incomplete):
            self.cli(
                "operation",
                "resolve",
                "--id",
                p["preview"]["operation_id"],
                "--outcome",
                "applied",
                "--evidence",
                "Unreadable contours cannot prove applied shell",
                "--dry-run",
                status=1,
            )
        self.assertEqual(self.world.ops().count("feature.shell"), 1)
