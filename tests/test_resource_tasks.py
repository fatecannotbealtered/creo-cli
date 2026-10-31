"""New tree/task semantics against the labelled loopback fixture, never native proof."""

from __future__ import annotations

from unittest.mock import patch

from creo_cli import registry
from creo_cli.core import Error
from creo_cli.workflow_tasks import compile_task
from tests.test_commands import RECT
from tests.test_features import Built


class ResourceTasks(Built):
    def test_old_names_are_rejected_and_new_depths_are_exposed(self):
        for old in (
            "feature thread",
            "feature mirror",
            "geometry measure",
            "assembly add",
            "assembly check",
            "drawing add-note",
            "family show",
            "model export",
            "model render",
            "operation acknowledge",
        ):
            self.assertEqual(self.cli(*old.split(), status=2)["error"]["code"], "E_USAGE")
        self.assertIn("assembly component list", registry.BY_PATH)
        self.assertIn("drawing view show", registry.BY_PATH)
        self.assertIn("assembly interference check", registry.BY_PATH)
        plan = self.cli("reference", "--command", "workflow plan")["data"]["command"]
        self.assertTrue(plan["uses_creo"])
        self.assertFalse(plan["live_verified"])
        self.assertIn("geometry.mass-properties", plan["service_ops"])
        self.assertNotIn("feature.extrude", plan["service_ops"])
        run = self.cli("reference", "--command", "workflow run")["data"]["command"]
        self.assertIn("feature.extrude", run["service_ops"])
        self.assertNotIn("feature.delete", run["service_ops"])
        self.assertIn("cosmetic", registry.BY_PATH["feature cosmetic-thread"].description)
        self.assertIn("whole part", registry.BY_PATH["feature mirror-part"].description)

    def test_geometry_and_assembly_readers_use_actual_fixture_inventory(self):
        self.block()
        mass = self.cli("geometry", "mass-properties", "--model", "block")["data"]
        self.assertEqual(mass["data"]["volume"], 8000)
        self.cli("geometry", "bounds", "--model", "block")
        self.gated("assembly", "create", "--name", "group", "--units", "mmns")
        self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "group",
            "--component",
            "block",
            "--request",
            self.request({"constraints": [{"type": "default"}]}),
        )
        listed = self.cli("assembly", "component", "list", "--model", "group")["data"]
        self.assertEqual(len(listed["items"]), 1)
        ident = listed["items"][0]["id"]
        selected = self.cli("assembly", "component", "show", "--model", "group", "--item", ident)[
            "data"
        ]
        self.assertEqual(selected["item"]["id"], ident)
        self.world.events.clear()
        self.cli("assembly", "placement", "check", "--model", "group")
        self.assertFalse(any(op == "assembly.check" for op, _ in self.world.events))
        self.cli("assembly", "interference", "check", "--model", "group", "--scope", "all")
        self.cli("assembly", "explode", "show", "--model", "group")

    def test_drawing_resource_inventory_and_typed_removal_restrictions(self):
        self.block()
        self.gated("drawing", "create", "--name", "drawing", "--of", "block", "--sheet", "a3")
        self.cli("drawing", "show", "--model", "drawing.drw")
        for noun in ("sheet", "view", "dimension", "note", "table", "symbol", "datum", "gtol"):
            data = self.cli("drawing", noun, "list", "--model", "drawing.drw")["data"]
            if data["items"]:
                row = data["items"][0]
                selector = next(
                    str(row[k]) for k in ("id", "name", "number") if row.get(k) is not None
                )
                self.cli("drawing", noun, "show", "--model", "drawing.drw", "--item", selector)
            if noun != "sheet":
                self.assertEqual(
                    self.cli(
                        "drawing",
                        noun,
                        "remove",
                        "--model",
                        "drawing.drw",
                        "--item",
                        "other:1",
                        "--dry-run",
                        status=2,
                    )["error"]["code"],
                    "E_VALIDATION",
                )
        original = self.world.op

        def incomplete(op, request):
            return (
                {"model": "drawing.drw", "items": None, "completed": False}
                if op == "drawing.resources"
                else original(op, request)
            )

        with patch.object(self.world, "op", incomplete):
            self.assertEqual(
                self.cli("drawing", "view", "list", "--model", "drawing.drw", status=1)["error"][
                    "code"
                ],
                "E_VERIFY_INCOMPLETE",
            )

        def different_model(op, query):
            return (
                {
                    "model": "other.drw",
                    "items": [],
                    "completed": True,
                    "source": "fixture:independent-getter",
                    "coverage": {"count": 0},
                }
                if op == "drawing.resources"
                else original(op, query)
            )

        with patch.object(self.world, "op", different_model):
            self.assertEqual(
                self.cli("drawing", "view", "list", "--model", "drawing.drw", status=1)["error"][
                    "code"
                ],
                "E_VERIFY_INCOMPLETE",
            )

    def test_layout_predicted_positions_are_separate_from_actual_and_collision_refused(self):
        self.block()
        self.gated("drawing", "create", "--name", "drawing", "--of", "block", "--sheet", "a3")
        views = self.cli("drawing", "view", "list", "--model", "drawing.drw")["data"]["items"]
        chosen = views[0]
        bounds = chosen["outline"]
        centre = [(bounds[0][i] + bounds[1][i]) / 2 for i in range(2)]
        req = self.request({"sheet": 1, "views": [{"view": chosen["name"], "at": centre}]})
        planned = self.cli("drawing", "layout", "plan", "--model", "drawing.drw", "--request", req)[
            "data"
        ]
        self.assertEqual(planned["actual_observations"]["views"], views)
        if not planned["issues"]:
            self.checks_pass(
                self.gated(
                    "drawing", "layout", "apply", "--model", "drawing.drw", "--request", req
                )["data"]
            )
        req = self.request({"sheet": 1, "views": [{"view": chosen["name"], "at": [-100, -100]}]})
        self.assertEqual(
            self.cli(
                "drawing",
                "layout",
                "apply",
                "--model",
                "drawing.drw",
                "--request",
                req,
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )

    def test_typed_workflow_selects_reads_asserts_and_edits_then_records_trace(self):
        self.part()
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        q = {
            "steps": [
                {
                    "id": "dims",
                    "kind": "read",
                    "command": "dimension list",
                    "args": {"model": "block"},
                },
                {
                    "id": "width",
                    "kind": "select",
                    "from": {"$ref": "dims.items"},
                    "where": {"value": 40.0},
                },
                {
                    "id": "assert_width",
                    "kind": "assert",
                    "actual": {"$ref": "width.value"},
                    "expected": 40.0,
                },
                {
                    "id": "edit",
                    "kind": "write",
                    "command": "dimension set",
                    "args": {
                        "model": "block",
                        "dimension": {"$ref": "width.id"},
                        "value": 48.0,
                        "units": "mm",
                    },
                },
                {
                    "id": "mass",
                    "kind": "read",
                    "command": "geometry mass-properties",
                    "args": {"model": "block"},
                },
                {
                    "id": "assert_mass",
                    "kind": "assert",
                    "actual": {"$ref": "mass.data.volume"},
                    "expected": 9600.0,
                    "tolerance": 1e-9,
                },
            ]
        }
        req = self.request(q)
        design = self.cli("workflow", "plan", "--request", req)["data"]
        self.assertIn("dims", design["observations"])
        self.assertEqual(len(design["deferred_steps"]), 3)
        completed = self.gated("workflow", "run", "--request", req)["data"]
        self.assertEqual(len(completed["result"]["steps"]), 6)
        stored = self.cli("workflow", "show", "--id", completed["operation_id"])["data"]
        self.assertEqual(
            stored["workflow"]["steps"][-1]["extensions"]["creo"]["result"]["actual"], 9600.0
        )

    def test_workflow_rejects_echo_assertions_and_forward_references_before_mutation(self):
        for q in (
            {
                "steps": [
                    {
                        "id": "edit",
                        "command": "part create",
                        "args": {"name": "x", "units": "mmns"},
                    },
                    {"kind": "assert", "actual": {"$ref": "edit.model"}, "expected": "x.prt"},
                ]
            },
            {
                "steps": [
                    {
                        "kind": "read",
                        "command": "dimension list",
                        "args": {"model": {"$ref": "later.model"}},
                    }
                ]
            },
        ):
            with self.assertRaises(Error):
                compile_task(q)
        self.assertFalse(self.world.models)

    def test_query_does_not_unblock_resolution_preserves_original_uncertainty(self):
        self.part()
        self.world.drop = "feature.extrude"
        err = self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT), status=6
        )["error"]
        operation_id = err["details"]["operation_id"]
        self.world.drop = None
        queried = self.cli("operation", "query", "--id", operation_id, "--model", "block")["data"]
        self.assertFalse(queried["proves_original_write_postconditions"])
        self.assertEqual(
            self.cli("operation", "show", "--id", operation_id)["data"]["operation_status"][
                "status"
            ],
            "unknown",
        )
        resolved = self.gated(
            "operation",
            "resolve",
            "--id",
            operation_id,
            "--outcome",
            "applied",
            "--evidence",
            "Independent model snapshot inspected: " + queried["evidence_id"],
        )["data"]
        record = resolved["operation_status"]
        self.assertEqual(record["resolution"]["outcome"], "applied")
        self.assertEqual(record["receipt"]["outcome"]["execution"], "unknown")
        self.assertEqual(record["receipt"]["outcome"]["verification"]["status"], "incomplete")

    def test_artifact_inspection_does_not_promote_a_header_to_geometry(self):
        file = self.ws / "header-only.stp"
        file.write_bytes(b"ISO-10303-21; malformed geometry")
        inspected = self.cli("artifact", "inspect", "--file", "header-only.stp")["data"]
        self.assertEqual(inspected["detected_header"], "step")
        self.assertFalse(inspected["inspection"]["consumer_semantics_verified"])
        self.assertEqual(inspected["artifact"]["size_bytes"], file.stat().st_size)
