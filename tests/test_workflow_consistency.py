"""Round-five public workflow persistence and confirmation regressions."""

from pathlib import Path
from unittest.mock import patch

from tests.test_commands import Base


class WorkflowConsistency(Base):
    def prepared(self, names=("block.prt",)):
        for name in names:
            self.world.part(name)
            self.world.write_version(self.ws, name, self.world.models[name])

    def change(self, model="block", value="changed", ident="change"):
        return {
            "id": ident,
            "command": "parameter set",
            "args": {"model": model, "name": "DESCRIPTION", "type": "string", "value": value},
        }

    def save(self, model="block", ident="save"):
        return {"id": ident, "command": "model save", "args": {"model": model}}

    def preview(self, steps):
        args = ("workflow", "run", "--request", self.request({"steps": steps}))
        return args, self.cli(*args, "--dry-run")["data"]

    def parent(self, preview):
        return self.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"][
            "operation_status"
        ]

    def test_preview_rejects_saved_version_byte_drift_before_write(self):
        self.prepared()
        args, pre = self.preview([self.save()])
        self.assertEqual(pre["preview"]["base_snapshot"]["source"], "mixed")
        (self.ws / "block.prt.1").write_bytes(b"externally changed, same filename")
        error = self.cli(*args, "--confirm", pre["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertFalse(any(op == "model.save" for op, _ in self.world.events))
        self.assertEqual(self.parent(pre)["status"], "planned")

    def test_partial_leaf_save_is_partial_parent_and_blocks(self):
        self.prepared()
        args, pre = self.preview([self.save()])
        original = self.world.op

        def corrupt(op, q):
            result = original(op, q)
            if op == "model.save":
                (self.ws / "block.prt.1").write_bytes(b"changed older version")
            return result

        with patch.object(self.world, "op", side_effect=corrupt):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "partial")
        parent = self.parent(pre)
        self.assertEqual(parent["status"], "partial")
        self.assertEqual(parent["receipt"]["outcome"]["persistence"], "partial")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_saved_then_changed_final_state_unsaved(self):
        self.prepared()
        args, pre = self.preview([self.save(), self.change()])
        out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(self.parent(pre)["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertTrue(self.world.models["block.prt"]["modified"])

    def test_one_saved_another_unsaved_is_partial(self):
        self.prepared(("block.prt", "other.prt"))
        args, pre = self.preview([self.save(), self.change("other")])
        error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "partial")
        self.assertEqual(self.parent(pre)["status"], "partial")
        self.assertEqual(error["details"]["receipt"]["recovery"]["action"], "inspect")

    def test_authorized_repeated_save_can_advance_version_ledger(self):
        self.prepared()
        args, pre = self.preview([self.save(ident="first"), self.change(), self.save(ident="last")])
        self.assertEqual(
            {Path(o["path"]).name for o in pre["preview"]["outputs"]},
            {"block.prt.2", "block.prt.3"},
        )
        out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(len(list(self.ws.glob("block.prt.*"))), 3)

    def test_between_steps_external_disk_drift_stops_later_save(self):
        self.prepared()
        args, pre = self.preview([self.change(), self.save()])
        original = self.world.op

        def mutate(op, q):
            result = original(op, q)
            if op == "parameter.set":
                (self.ws / "block.prt.1").write_bytes(b"external bytes during preceding step")
            return result

        with patch.object(self.world, "op", side_effect=mutate):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertFalse(any(op == "model.save" for op, _ in self.world.events))
        self.assertEqual(self.parent(pre)["status"], "partial")

    def test_saved_result_unknown_is_not_unchanged(self):
        self.prepared()
        args, pre = self.preview([self.save(), self.change()])
        self.world.drop = "model.save"
        error = self.cli(*args, "--confirm", pre["confirm_token"], status=6)["error"]
        self.world.drop = None
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "unknown")
        self.assertEqual(self.parent(pre)["status"], "unknown")
        self.assertFalse(any(op == "parameter.set" for op, _ in self.world.events))

    def test_multiple_new_versions_preserve_partial_and_children(self):
        self.prepared()
        args, pre = self.preview([self.save(), self.change()])
        original = self.world.op

        def extra(op, q):
            result = original(op, q)
            if op == "model.save":
                self.world.write_version(self.ws, "block.prt", self.world.models["block.prt"])
            return result

        with patch.object(self.world, "op", side_effect=extra):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        parent = self.parent(pre)
        self.assertEqual(error["code"], "E_PARTIAL")
        rows = parent["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual(rows[0]["receipt"]["outcome"]["persistence"], "partial")
        self.assertEqual(rows[1]["status"], "skipped")
        self.assertEqual(len(list(self.ws.glob("block.prt.*"))), 3)

    def test_unchanged_save_failure_does_not_claim_unsaved_or_applied(self):
        from tests.fixture import Refused

        self.prepared()
        args, pre = self.preview([self.save()])
        original = self.world.op

        def fail(op, q):
            if op == "model.save":
                raise Refused("E_CREO", "save refused before effect")
            return original(op, q)

        with patch.object(self.world, "op", side_effect=fail):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_NATIVE_FAILURE")
        outcome = error["details"]["receipt"]["outcome"]
        self.assertEqual((outcome["change"], outcome["persistence"]), ("not_applied", "unchanged"))

    def test_saved_one_then_other_save_fails_preserves_actual_states(self):
        from tests.fixture import Refused

        self.prepared(("block.prt", "other.prt"))
        args, pre = self.preview(
            [self.save(), self.change("other"), self.save("other", "save_other")]
        )

        original = self.world.op

        def fail(op, q):
            if op == "model.save" and q["model"] == "other.prt":
                raise Refused("E_CREO", "other save refused before effect")
            return original(op, q)

        with patch.object(self.world, "op", side_effect=fail):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        details = error["details"]["receipt"]["extensions"]["creo"]["object_persistence"]
        self.assertEqual(
            {v["object_id"]: v["state"] for v in details},
            {"block.prt": "saved", "other.prt": "unsaved"},
        )

    def test_export_only_does_not_claim_model_saved(self):
        self.prepared()
        args, pre = self.preview(
            [
                {
                    "id": "export",
                    "command": "artifact export",
                    "args": {"model": "block", "output": str(self.ws / "out.stp")},
                }
            ]
        )
        out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "not_applicable")
        self.assertEqual(len(out["receipt"]["artifacts"]), 1)

    def test_related_dependency_version_file_drift_refuses(self):
        self.prepared(("block.prt", "a.asm"))
        self.world.models["a.asm"].update(
            type="assembly", components=[{"id": "10", "model": "block.prt"}]
        )
        args, pre = self.preview([self.save("a.asm")])
        (self.ws / "block.prt.1").write_bytes(b"external child version drift")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertFalse(any(op == "model.save" for op, _ in self.world.events))

    def test_output_created_between_steps_not_adopted_or_overwritten(self):
        self.prepared()
        path = self.ws / "out.stp"
        args, pre = self.preview(
            [
                self.change(),
                {
                    "id": "export",
                    "command": "artifact export",
                    "args": {"model": "block", "output": str(path)},
                },
            ]
        )
        original = self.world.op

        def create(op, q):
            result = original(op, q)
            if op == "parameter.set":
                path.write_bytes(b"external unrelated writer owns output")
            return result

        with patch.object(self.world, "op", side_effect=create):
            self.cli(*args, "--confirm", pre["confirm_token"], status=1)
        self.assertEqual(path.read_bytes(), b"external unrelated writer owns output")
        self.assertFalse(any(op == "model.export" for op, _ in self.world.events))

    def test_unrelated_object_file_drift_does_not_lock_workflow(self):
        self.prepared(("block.prt", "other.prt"))
        args, pre = self.preview([self.save()])
        (self.ws / "other.prt.1").write_bytes(b"unrelated change")
        out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")

    def test_final_parent_record_size_failure_keeps_reliable_unknown_checkpoint(self):
        from creo_cli import operations

        self.prepared()
        args, pre = self.preview([self.change(), self.save()])
        original = operations.update

        def limited(record):
            if record["command"] == "workflow run" and record.get("driver_receipt"):
                with patch.object(operations, "MAX_RECORD_BYTES", 1):
                    return original(record)
            return original(record)

        with patch.object(operations, "update", side_effect=limited):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        parent = self.parent(pre)
        self.assertEqual(parent["status"], "unknown")
        self.assertEqual(parent["extensions"]["creo"]["workflow"]["summary"]["completed"], 2)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_one_saved_another_clean_save_failed_is_partial_persistence(self):
        from tests.fixture import Refused

        self.prepared(("block.prt", "other.prt"))
        args, pre = self.preview([self.save(), self.save("other", "other")])
        original = self.world.op

        def fail(op, q):
            if op == "model.save" and q["model"] == "other.prt":
                raise Refused("E_CREO", "independent clean save rejected")
            return original(op, q)

        with patch.object(self.world, "op", side_effect=fail):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "partial")
        objects = error["details"]["receipt"]["extensions"]["creo"]["object_persistence"]
        self.assertEqual(
            {x["object_id"]: x["state"] for x in objects},
            {"block.prt": "saved", "other.prt": "unchanged"},
        )

    def test_scope_configuration_drift_between_steps_stops(self):
        import json
        from pathlib import Path

        self.prepared()
        args, pre = self.preview([self.change(), self.save()])
        original = self.world.op

        def mutate(op, q):
            result = original(op, q)
            if op == "parameter.set":
                path = Path(self.env["CREO_CLI_SCOPE_FILE"])
                grant = json.loads(path.read_text(encoding="utf-8"))
                path.write_text(
                    json.dumps(grant | {"limits": {"max_operations": 100}}), encoding="utf-8"
                )
            return result

        with patch.object(self.world, "op", side_effect=mutate):
            error = self.cli(*args, "--confirm", pre["confirm_token"], status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertFalse(any(op == "model.save" for op, _ in self.world.events))
