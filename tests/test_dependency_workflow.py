"""Round-four dependency and public workflow regressions against the loopback service."""

from tests.test_commands import RECT, Base


class DependencyClosure(Base):
    def graph(self, nested=False):
        for name in ("p.prt", "a.asm", "b.asm"):
            self.world.part(name)
            if name.endswith(".asm"):
                self.world.models[name]["type"] = "assembly"
            self.world.write_version(self.ws, name, self.world.models[name])
        self.world.models["a.asm"]["components"] = [
            {"id": "10", "model": "b.asm" if nested else "p.prt"}
        ]
        self.world.models["b.asm"]["components"] = [{"id": "11", "model": "p.prt"}]

    def unknown_part(self, nested):
        self.graph(nested)
        self.world.drop = "feature.extrude"
        self.gated("feature", "extrude", "--model", "p", "--request", self.request(RECT), status=6)
        self.world.drop = None
        error = self.cli(
            "drawing",
            "create",
            "--name",
            "d",
            "--of",
            "a.asm",
            "--sheet",
            "a4",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(error["details"]["conflict"], "unresolved_operation")
        self.assertNotIn("d.drw", self.world.models)

    def test_drawing_refuses_unknown_direct_part(self):
        self.unknown_part(False)

    def test_drawing_refuses_unknown_nested_part(self):
        self.unknown_part(True)

    def test_preview_binds_transitive_child_revision(self):
        self.graph(True)
        args = ("drawing", "create", "--name", "d", "--of", "a.asm", "--sheet", "a4")
        preview = self.cli(*args, "--dry-run")["data"]
        identities = {d["identity"] for d in preview["preview"]["base_snapshot"]["dependencies"]}
        self.assertIn("p.prt", identities)
        self.world.models["p.prt"]["modified"] = True
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("d.drw", self.world.models)

    def test_missing_child_fails_incomplete_before_plan(self):
        self.graph()
        del self.world.models["p.prt"]
        error = self.cli(
            "drawing",
            "create",
            "--name",
            "d",
            "--of",
            "a.asm",
            "--sheet",
            "a4",
            "--dry-run",
            status=1,
        )["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")

    def test_shared_child_is_read_once_without_false_cycle(self):
        import os
        from unittest.mock import patch

        from creo_cli import dependencies
        from creo_cli.transport import Client

        self.graph(True)
        self.world.models["a.asm"]["components"].append({"id": "12", "model": "p.prt"})
        with patch.dict(os.environ, self.env, clear=True), Client(30) as client:
            nodes = dependencies.closure(client, ["a.asm"])
        self.assertEqual({n["identity"] for n in nodes}, {"a.asm", "b.asm", "p.prt"})

    def test_cycles_bounds_and_incomplete_component_identity_refuse(self):
        from unittest.mock import patch

        from creo_cli import dependencies

        self.graph(True)
        args = ("drawing", "create", "--name", "d", "--of", "a.asm", "--sheet", "a4", "--dry-run")
        for change in ("cycle", "identity", "depth", "count"):
            with self.subTest(change=change):
                original = list(self.world.models["b.asm"]["components"])
                if change == "cycle":
                    self.world.models["b.asm"]["components"] = [{"id": "9", "model": "a.asm"}]
                if change == "identity":
                    self.world.models["b.asm"]["components"] = [{"id": "9", "model": None}]
                with (
                    patch.object(dependencies, "MAX_DEPTH", 0 if change == "depth" else 32),
                    patch.object(dependencies, "MAX_MODELS", 1 if change == "count" else 1000),
                ):
                    error = self.cli(*args, status=1)["error"]
                self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
                self.world.models["b.asm"]["components"] = original


class PublicWorkflow(Base):
    def task(self):
        self.part()
        return {
            "steps": [
                {
                    "id": "change",
                    "kind": "write",
                    "command": "parameter set",
                    "args": {
                        "model": "block",
                        "name": "DESCRIPTION",
                        "type": "string",
                        "value": "changed",
                    },
                },
                {
                    "id": "save",
                    "kind": "write",
                    "command": "model save",
                    "args": {"model": "block"},
                },
            ]
        }

    def test_public_parent_plan_and_workflow_are_queryable(self):
        body = self.task()
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertIn("operation_id", preview["preview"])
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["workflow"]["summary"]["completed"], 2)
        self.assertEqual(result["receipt"]["operation_id"], preview["preview"]["operation_id"])

    def test_later_effects_denied_before_first_write(self):
        body = self.task()
        body["steps"].append(
            {
                "id": "export",
                "kind": "write",
                "command": "artifact export",
                "args": {"model": "block", "output": str(self.ws / "out.stp")},
            }
        )
        import json
        from pathlib import Path

        p = Path(self.env["CREO_CLI_SCOPE_FILE"])
        s = json.loads(p.read_text(encoding="utf-8"))
        s["effects"] = ["change", "persist"]
        p.write_text(json.dumps(s), encoding="utf-8")
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertFalse(preview["preview"]["can_apply"])
        self.cli(*args, "--confirm", preview["confirm_token"], status=4)
        self.assertFalse(any(op == "parameter.set" for op, _ in self.world.events))

    def test_partial_assertion_keeps_completed_child(self):
        body = self.task()
        body["steps"][1:1] = [
            {"id": "read", "kind": "read", "command": "parameter list", "args": {"model": "block"}},
            {
                "id": "pick",
                "kind": "select",
                "from": {"$ref": "read.items"},
                "where": {"name": "DESCRIPTION"},
            },
            {
                "id": "check",
                "kind": "assert",
                "actual": {"$ref": "pick.value"},
                "expected": "wrong",
            },
        ]
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        error = self.cli(*args, "--confirm", preview["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        w = error["details"]["workflow"]
        self.assertEqual(w["steps"][0]["status"], "completed")
        self.assertEqual(w["steps"][-1]["status"], "skipped")
        parent = self.cli("operation", "show", "--id", w["operation_id"])["data"][
            "operation_status"
        ]
        self.assertEqual(parent["status"], "partial")

    def test_lost_reply_blocks_parent_child_and_repeat(self):
        body = self.task()
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        self.world.drop = "parameter.set"
        error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        self.world.drop = None
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        w = error["details"]["workflow"]
        self.assertEqual(w["steps"][0]["status"], "unknown")
        self.assertEqual(w["steps"][1]["status"], "skipped")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        count = sum(op == "parameter.set" for op, _ in self.world.events)
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(count, sum(op == "parameter.set" for op, _ in self.world.events))

    def test_only_final_parent_public_commit_failure_remains_unresolved(self):
        from unittest.mock import patch

        from creo_cli import operations
        from creo_cli.core import Error

        body = self.task()
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        original = operations.update

        def fail(record):
            if record["command"] == "workflow run" and record.get("driver_receipt"):
                raise Error("E_IO", "injected parent receipt commit failure")
            return original(record)

        with patch("creo_cli.operations.update", side_effect=fail):
            self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        parent = self.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"][
            "operation_status"
        ]
        self.assertEqual(parent["status"], "unknown")
        self.assertEqual(parent["extensions"]["creo"]["workflow"]["summary"]["completed"], 2)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_whole_operation_budget_and_scope_drift(self):
        import json
        from pathlib import Path

        body = self.task()
        args = ("workflow", "run", "--request", self.request(body))
        p = Path(self.env["CREO_CLI_SCOPE_FILE"])
        grant = json.loads(p.read_text(encoding="utf-8"))
        p.write_text(json.dumps(grant | {"limits": {"max_operations": 2}}), encoding="utf-8")
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertFalse(preview["preview"]["can_apply"])
        self.cli(*args, "--confirm", preview["confirm_token"], status=4)
        p.write_text(json.dumps(grant), encoding="utf-8")
        preview = self.cli(*args, "--dry-run")["data"]
        p.write_text(json.dumps(grant | {"revoked": True}), encoding="utf-8")
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertFalse(any(op == "parameter.set" for op, _ in self.world.events))
