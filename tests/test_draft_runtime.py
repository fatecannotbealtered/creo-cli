"""Public bounded draft behavior with explicit wedge meshes; native evidence is separate."""

import copy
import json
import math
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tests import fixture_draft, test_features
from tests.test_commands import ROOT


class DraftRuntime(test_features.Built):
    def setUp(self):
        super().setUp()
        self.block()
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        side = next(f["ref"] for f in faces if f["normal"] == [1, 0, 0])
        self.body = {
            "units": "mm",
            "name": "LEAN",
            "surfaces": [side],
            "hinge": "FRONT",
            "pull": "FRONT",
            "angle": 5,
        }

    def args(self, body=None):
        return (
            "feature",
            "draft",
            "--model",
            "block",
            "--request",
            self.request(body or self.body),
        )

    def fresh(self, *args, status=0):
        p = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(p.returncode, status, p.stdout[:1000])
        return json.loads(p.stdout)

    def signed_case(self, angle):
        args = self.args(self.body | {"angle": angle})
        p = self.cli(*args, "--dry-run")["data"]
        self.assertNotIn("feature.draft", self.world.ops())
        result = self.cli(*args, "--confirm", p["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(
            sum(
                c["check"].startswith("complete_draft_region:")
                for c in result["verification"]["checks"]
            ),
            6,
        )
        state = self.cli("model", "show", "--model", "block")["data"]
        self.assertAlmostEqual(
            state["mass_properties"]["volume"], 8000 - 1000 * math.tan(math.radians(angle))
        )
        feature = self.cli("feature", "show", "--model", "block", "--feature", "LEAN")["data"]
        self.assertEqual(feature["native_definition"]["selected"], self.body["surfaces"])
        self.assertEqual(feature["native_definition"]["angle"], angle)
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.draft"), 1)

    def test_positive_angle_complete_wedge(self):
        self.signed_case(5)

    def test_negative_angle_complete_wedge(self):
        self.signed_case(-5)

    def test_actual_angle_dimension_can_change_and_return(self):
        self.gated(*self.args())
        dims = self.cli("dimension", "list", "--model", "block", "--feature", "LEAN")["data"][
            "items"
        ]
        angle = next(d for d in dims if d["type"] == "angle")
        for value in (-5, 5):
            self.gated(
                "dimension",
                "set",
                "--model",
                "block",
                "--dimension",
                angle["id"],
                "--value",
                str(value),
                "--units",
                "deg",
            )
            feature = self.cli("feature", "show", "--model", "block", "--feature", "LEAN")["data"]
            self.assertEqual(feature["native_definition"]["angle"], value)
            self.assertTrue(feature["native_solid_geometry"]["complete"])
        self.gated("model", "save", "--model", "block")

    def test_unsupported_selection_direction_precision_and_angle_zero_dispatch(self):
        for body in [
            self.body | {"surfaces": [self.top()["ref"]]},
            self.body | {"hinge": "TOP", "pull": "TOP"},
            self.body | {"flip_pull": True},
            self.body | {"angle": 0.5},
            self.body | {"angle": 16},
            self.body | {"surfaces": [self.body["surfaces"][0], self.top()["ref"]]},
        ]:
            with self.subTest(body=body):
                self.cli(*self.args(body), "--dry-run", status=2)
        self.assertNotIn("feature.draft", self.world.ops())

    def test_missing_capability_or_identity_refuses_before_dispatch(self):
        self.world.capabilities.pop("prismatic_draft_readback")
        self.cli(*self.args(), "--dry-run", status=4)
        self.world.capabilities["prismatic_draft_readback"] = 1
        next(g for g in self.world.models["block.prt"]["geometry"] if g["ref"] == "FRONT").pop(
            "feature"
        )
        self.cli(*self.args(), "--dry-run", status=1)
        self.assertNotIn("feature.draft", self.world.ops())

    def test_creation_leaf_is_not_silently_added_to_workflow(self):
        request = self.request(self.body, "draft-request.json")
        workflow = self.request(
            {
                "steps": [
                    {
                        "id": "draft",
                        "command": "feature draft",
                        "args": {"model": "block", "request": str(request)},
                    }
                ]
            },
            "workflow.json",
        )
        self.cli("workflow", "run", "--request", workflow, "--dry-run", status=2)
        self.assertNotIn("feature.draft", self.world.ops())

    def test_request_scope_and_geometry_drift_zero_dispatch(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        source = Path(args[-1])
        replacement = source.with_suffix(".replacement")
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        p = self.cli(*args, "--dry-run")["data"]
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        original = scope.read_bytes()
        grant = json.loads(original)
        grant["effects"] = ["observe"]
        scope.write_text(json.dumps(grant))
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        scope.write_bytes(original)
        p = self.cli(*args, "--dry-run")["data"]
        next(g for g in self.world.models["block.prt"]["geometry"] if g["kind"] == "edge")["end"][
            0
        ] += 1
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertNotIn("feature.draft", self.world.ops())

    def unknown_case(self, disk=False):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        db = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        if disk:
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute(
                    "CREATE TRIGGER draft_receipt_failure BEFORE UPDATE OF body ON operations "
                    + f"WHEN NEW.id='{ident}' AND "
                    "json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
                    "BEGIN SELECT RAISE(ABORT,'owned draft receipt fault'); END"
                )
        else:
            self.world.drop = "feature.draft"
        try:
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        finally:
            self.world.drop = None
            if disk:
                with closing(sqlite3.connect(db)) as connection, connection:
                    connection.execute("DROP TRIGGER draft_receipt_failure")
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(query["observation"]["draft_verification"]["can_register"], ["applied"])
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent selected wall reference, neutral plane, signed angle "
            "and complete current native body match frozen intent",
        )
        status = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(
            status["extensions"]["creo"]["prismatic_draft_inspection"]["evidence_status"],
            "verified",
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("feature.draft"), 1)

    def test_lost_reply_new_process_observe_and_register_without_replay(self):
        self.unknown_case()

    def test_final_receipt_failure_retains_unknown_and_recovers(self):
        self.unknown_case(disk=True)

    def test_wrong_wall_same_volume_cannot_register_applied(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def wrong(op, request):
            result = original(op, request)
            if op == "feature.draft":
                m = self.world.models["block.prt"]
                f = self.world.feature(m, "LEAN")
                intended = m["volume"]
                fixture_draft.reshape(self.world, m, f, 5, wrong_wall=True)
                self.assertAlmostEqual(m["volume"], intended)
            return result

        self.world.drop = "feature.draft"
        with patch.object(self.world, "op", side_effect=wrong):
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        ident = p["preview"]["operation_id"]
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertNotIn("applied", query["observation"]["draft_verification"]["can_register"])
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Matching volume is insufficient when the wrong wall was drafted",
            "--dry-run",
            status=1,
        )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_wrong_native_reference_or_angle_is_not_accepted(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def wrong(op, request):
            result = original(op, request)
            if op == "feature.draft":
                self.world.feature(self.world.models["block.prt"], "LEAN")["native_definition"][
                    "hinge"
                ] = "TOP"
            return result

        with patch.object(self.world, "op", side_effect=wrong):
            self.cli(*args, "--confirm", p["confirm_token"], status=1)
        q = self.fresh(
            "operation", "query", "--id", p["preview"]["operation_id"], "--model", "block"
        )["data"]
        self.assertNotIn("applied", q["observation"]["draft_verification"]["can_register"])

    def test_incomplete_definition_after_lost_reply_keeps_unknown(self):
        args = self.args()
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def missing(op, request):
            result = original(op, request)
            if op == "feature.show" and result.get("type") == "FEATTYPE_DRAFT":
                result = copy.deepcopy(result)
                result["native_definition"] = {
                    "complete": False,
                    "error": {"code": "E_CREO", "message": "injected unreadable native selection"},
                }
            return result

        self.world.drop = "feature.draft"
        with patch.object(self.world, "op", side_effect=missing):
            self.cli(*args, "--confirm", p["confirm_token"], status=6)
            self.world.drop = None
            self.fresh(
                "operation",
                "query",
                "--id",
                p["preview"]["operation_id"],
                "--model",
                "block",
                status=1,
            )
            self.cli(
                "operation",
                "resolve",
                "--id",
                p["preview"]["operation_id"],
                "--outcome",
                "applied",
                "--evidence",
                "Incomplete native selection cannot prove an applied draft",
                "--dry-run",
                status=1,
            )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
