"""Public bounded workflow composition for material and numeric tolerance changes."""

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests.fixture_features import Refusal
from tests.test_commands import ROOT
from tests.test_features import Built


class WorkflowProperties(Built):
    def prepare_model(self, table_driven=False):
        model = self.block()
        dimensions = [d for d in model["dimensions"] if d["name"].startswith("d")]
        self.target, self.other = dimensions[:2]
        if table_driven:
            self.other["tolerance"] = {
                "type": "symmetric",
                "value": 0.2,
                "upper": self.other["value"] + 0.2,
                "lower": self.other["value"] - 0.2,
            }
            self.other["numeric_tolerance_table"] = {"complete": True, "assigned": True}
        self.source = self.ws / "R12_SYNTH.mtl"
        self.source.write_text(
            "ND_RelParSet_K01 = {\nName = R12_SYNTH\nPARAMETERS =\n{\n"
            "Name = PTC_MASS_DENSITY\nType = Real\nDefault = 2.7e-9 tonne / mm^3\n"
            "Access = Full\n}\n}\n",
            encoding="utf-8",
        )
        self.gated("model", "save", "--model", "block.prt")
        self.world.events.clear()
        return model

    def standard(self):
        return {
            "id": "standard",
            "command": "model set-tolerance-standard",
            "args": {"model": "block.prt", "standard": "iso", "class": "medium"},
        }

    def tolerance(self, ident="tolerance", value=0.1):
        return {
            "id": ident,
            "command": "dimension set-tolerance",
            "args": {
                "model": "block.prt",
                "dimension": self.target["name"],
                "symmetric": value,
                "units": "mm",
            },
        }

    def material(self, explicit=True):
        return {
            "id": "material",
            "command": "material assign",
            "args": {"model": "block.prt", "material": "R12_SYNTH", "file": str(self.source)}
            if explicit
            else {"model": "block.prt", "material": "Steel_low_carbon"},
        }

    def save(self, ident="save"):
        return {"id": ident, "command": "model save", "args": {"model": "block.prt"}}

    def preview(self, steps):
        words = ("workflow", "run", "--request", self.request({"steps": steps}))
        return words, self.cli(*words, "--dry-run")["data"]

    def confirm(self, words, preview, status=0):
        return self.cli(*words, "--confirm", preview["confirm_token"], status=status)

    def parent(self, preview):
        return self.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"][
            "operation_status"
        ]

    def test_standard_then_numeric_tolerance_preserves_authorized_transition(self):
        model = self.prepare_model(table_driven=True)
        original_other = deepcopy(self.other["tolerance"])
        words, preview = self.preview(
            [self.material(), self.standard(), self.tolerance(), self.save()]
        )
        self.assertFalse(
            any(op in self.world.ops() for op in ("material.assign", "dimension.tolerance"))
        )
        out = self.confirm(words, preview)["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(out["workflow"]["summary"]["completed"], 4)
        self.assertEqual(self.other["tolerance"], original_other)
        self.assertFalse(self.other["numeric_tolerance_table"]["assigned"])
        self.assertEqual(self.target["tolerance"]["value"], 0.1)
        self.assertEqual(model["density"], 2.7e-9)
        self.assertFalse(model["modified"])
        rows = self.parent(preview)["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual(
            [r["receipt"]["outcome"]["persistence"] for r in rows], ["unsaved"] * 3 + ["saved"]
        )
        count = len(self.world.ops())
        self.confirm(words, preview, status=6)
        self.assertEqual(len(self.world.ops()), count)

    def test_without_prior_standard_table_driven_conflict_is_zero_dispatch(self):
        self.prepare_model(table_driven=True)
        self.cli(
            "workflow",
            "run",
            "--request",
            self.request({"steps": [self.tolerance()]}),
            "--dry-run",
            status=6,
        )
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_material_file_drift_before_confirmation_is_zero_dispatch(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        self.source.write_text(
            self.source.read_text(encoding="utf-8").replace("2.7e-9", "3.1e-9"), encoding="utf-8"
        )
        error = self.confirm(words, preview, status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertNotIn("material.assign", self.world.ops())

    def test_material_same_bytes_replaced_between_steps_stops_before_assign(self):
        self.prepare_model()
        words, preview = self.preview([self.standard(), self.material(), self.save()])
        original = self.world.op

        def replace(op, q):
            result = original(op, q)
            if op == "model.set-tolerance-standard":
                replacement = self.source.with_suffix(".replacement")
                replacement.write_bytes(self.source.read_bytes())
                replacement.replace(self.source)
            return result

        with patch.object(self.world, "op", side_effect=replace):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("material.assign", self.world.ops())
        rows = self.parent(preview)["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([r["status"] for r in rows], ["completed", "failed", "skipped"])
        self.assertEqual(rows[0]["receipt"]["outcome"]["change"], "applied")

    def test_tolerance_external_drift_after_verified_step_is_not_adopted(self):
        self.prepare_model()
        words, preview = self.preview([self.standard(), self.tolerance(), self.save()])
        original = operations.update
        altered = False

        def drift(record):
            nonlocal altered
            result = original(record)
            rows = record.get("driver_workflow", {}).get("steps", [])
            if not altered and rows and rows[0]["status"] == "completed":
                altered = True
                self.other["tolerance"] = {"type": "basic"}
            return result

        with patch.object(operations, "update", side_effect=drift):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_failed_standard_readback_stops_tolerance(self):
        self.prepare_model(table_driven=True)
        words, preview = self.preview([self.standard(), self.tolerance(), self.save()])
        original = self.world.set_tolerance_standard

        def incomplete(q):
            result = original(q)
            self.other["numeric_tolerance_table"] = {"complete": False}
            return result

        with patch.object(self.world, "set_tolerance_standard", side_effect=incomplete):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertIn(error["code"], ("E_PARTIAL", "E_VERIFY_FAILED"))
        self.assertNotIn("dimension.tolerance", self.world.ops())
        rows = self.parent(preview)["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([r["status"] for r in rows], ["failed", "skipped", "skipped"])

    def test_save_then_tolerance_change_reports_unsaved(self):
        model = self.prepare_model()
        words, preview = self.preview([self.material(), self.save(), self.tolerance()])
        out = self.confirm(words, preview)["data"]
        self.assertTrue(model["modified"])
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "unsaved")

    def test_material_reply_lost_preserves_unknown_and_skips_save(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        self.world.drop = "material.assign"
        error = self.confirm(words, preview, status=6)["error"]
        self.world.drop = None
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        parent = self.parent(preview)
        self.assertEqual(parent["status"], "unknown")
        self.assertEqual(parent["receipt"]["outcome"]["persistence"], "unknown")
        self.assertEqual(parent["extensions"]["creo"]["workflow"]["steps"][1]["status"], "skipped")
        self.assertNotIn("model.save", self.world.ops())
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_final_parent_receipt_failure_keeps_successful_children(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        original = operations.update

        def fail(record):
            if record["command"] == "workflow run" and record.get("driver_receipt"):
                raise Error("E_IO", "controlled final parent receipt failure")
            return original(record)

        with patch.object(operations, "update", side_effect=fail):
            self.confirm(words, preview, status=6)
        with patch.dict(os.environ, self.env, clear=True):
            stored = operations.get(preview["preview"]["operation_id"])
        self.assertEqual(stored["status"], "running")
        self.assertIsNone(stored["driver_receipt"])
        parent = self.parent(preview)
        self.assertEqual(parent["status"], "unknown")
        rows = parent["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([r["status"] for r in rows], ["completed", "completed"])
        self.assertEqual(rows[-1]["receipt"]["outcome"]["persistence"], "saved")
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_mid_tolerance_failure_preserves_prior_material_and_stops(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.tolerance(), self.save()])
        with patch.object(
            self.world,
            "dimension_tolerance",
            side_effect=Refusal("E_CREO", "fixture refusal before effect"),
        ):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(self.world.models["block.prt"]["density"], 2.7e-9)
        self.assertNotIn("model.save", self.world.ops())

    def test_scope_change_between_steps_stops_material(self):
        self.prepare_model()
        words, preview = self.preview([self.standard(), self.material(), self.save()])
        original = self.world.op

        def revoke(op, q):
            result = original(op, q)
            if op == "model.set-tolerance-standard":
                path = Path(self.env["CREO_CLI_SCOPE_FILE"])
                data = json.loads(path.read_text(encoding="utf-8"))
                data["effects"] = [e for e in data["effects"] if e != "observe"]
                path.write_text(json.dumps(data), encoding="utf-8")
            return result

        with patch.object(self.world, "op", side_effect=revoke):
            self.confirm(words, preview, status=1)
        self.assertNotIn("material.assign", self.world.ops())

    def test_two_numeric_edits_and_consecutive_saves_keep_authorized_history(self):
        self.prepare_model(table_driven=True)
        words, preview = self.preview(
            [
                self.standard(),
                self.tolerance(),
                self.save(),
                self.tolerance("later", 0.3),
                self.save("second_save"),
            ]
        )
        out = self.confirm(words, preview)["data"]
        self.assertEqual(out["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(self.target["tolerance"]["value"], 0.3)
        self.assertEqual(out["workflow"]["summary"]["completed"], 5)
        rows = out["workflow"]["steps"]
        self.assertEqual(
            rows[1]["extensions"]["creo"]["property_prerequisite"]["operation_id"],
            rows[0]["operation_id"],
        )
        self.assertEqual(
            rows[3]["extensions"]["creo"]["property_prerequisite"]["operation_id"],
            rows[0]["operation_id"],
        )

    def test_wrong_model_standard_does_not_authorize_table_detachment(self):
        self.prepare_model(table_driven=True)
        self.world.part("other.prt")
        standard = self.standard()
        standard["args"]["model"] = "other.prt"
        self.cli(
            "workflow",
            "run",
            "--request",
            self.request({"steps": [standard, self.tolerance()]}),
            "--dry-run",
            status=6,
        )
        self.assertNotIn("model.set-tolerance-standard", self.world.ops())
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def material_changes_between_steps(self, change):
        self.prepare_model()
        words, preview = self.preview([self.standard(), self.material(), self.save()])
        original = self.world.op

        def mutate(op, q):
            result = original(op, q)
            if op == "model.set-tolerance-standard":
                change(self.source)
            return result

        with patch.object(self.world, "op", side_effect=mutate):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("material.assign", self.world.ops())
        rows = self.parent(preview)["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([r["status"] for r in rows], ["completed", "failed", "skipped"])

    def test_material_content_changes_between_steps_stop_before_assign(self):
        self.material_changes_between_steps(
            lambda path: path.write_text(
                path.read_text(encoding="utf-8").replace("2.7e-9", "3.1e-9"), encoding="utf-8"
            )
        )

    def test_material_file_deleted_between_steps_stops_before_assign(self):
        self.material_changes_between_steps(lambda path: path.unlink())

    def test_implicit_library_source_is_bound_and_drift_is_rejected(self):
        self.prepare_model()
        source = self.world.material_library / "Steel_low_carbon.mtl"
        words, preview = self.preview([self.standard(), self.material(explicit=False), self.save()])
        inputs = preview["preview"]["base_snapshot"]["extensions"]["creo"]["observation"][
            "file_inputs"
        ]["inputs"]
        self.assertIn(str(source), inputs)
        original = self.world.op

        def mutate(op, q):
            result = original(op, q)
            if op == "model.set-tolerance-standard":
                replacement = source.with_suffix(".replacement")
                replacement.write_bytes(source.read_bytes())
                replacement.replace(source)
            return result

        with patch.object(self.world, "op", side_effect=mutate):
            self.confirm(words, preview, status=1)
        self.assertNotIn("material.assign", self.world.ops())

    def test_implicit_library_catalog_cannot_switch_to_new_source_between_steps(self):
        self.prepare_model()
        source = self.world.material_library / "Steel_low_carbon.mtl"
        alternate_dir = self.ws / "alternate"
        alternate_dir.mkdir()
        alternate = alternate_dir / source.name
        alternate.write_bytes(source.read_bytes())
        words, preview = self.preview([self.standard(), self.material(explicit=False), self.save()])
        original = self.world.material_list
        changed = False
        original_update = operations.update

        def list_materials(q):
            data = original(q)
            if changed:
                for row in data["materials"]:
                    if row["name"] == "Steel_low_carbon":
                        row["file"] = str(alternate)
            return data

        def set_changed(record):
            nonlocal changed
            result = original_update(record)
            rows = record.get("driver_workflow", {}).get("steps", [])
            if rows and rows[0]["status"] == "completed":
                changed = True
            return result

        with (
            patch.object(self.world, "material_list", side_effect=list_materials),
            patch.object(operations, "update", side_effect=set_changed),
        ):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("material.assign", self.world.ops())

    def test_material_observe_path_outside_scope_is_zero_dispatch(self):
        self.prepare_model()
        source = self.world.material_library / "Steel_low_carbon.mtl"
        external = self.root / "external-library"
        external.mkdir()
        (external / source.name).write_bytes(source.read_bytes())
        self.world.material_library = external
        words, preview = self.preview([self.material(explicit=False), self.save()])
        self.assertFalse(preview["preview"]["can_apply"])
        self.confirm(words, preview, status=4)
        self.assertNotIn("material.assign", self.world.ops())

    def test_numeric_table_ownership_drift_after_standard_blocks_later_tolerance(self):
        self.prepare_model(table_driven=True)
        words, preview = self.preview([self.standard(), self.tolerance(), self.save()])
        original = operations.update
        changed = False

        def mutate(record):
            nonlocal changed
            result = original(record)
            rows = record.get("driver_workflow", {}).get("steps", [])
            if not changed and rows and rows[0]["status"] == "completed":
                changed = True
                self.other["numeric_tolerance_table"]["assigned"] = True
            return result

        with patch.object(operations, "update", side_effect=mutate):
            self.confirm(words, preview, status=1)
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_geometry_mutating_mix_is_explicitly_unsupported_before_write(self):
        self.prepare_model()
        geometry = {
            "id": "geometry",
            "command": "dimension set",
            "args": {
                "model": "block.prt",
                "dimension": self.target["name"],
                "value": 42,
                "units": "mm",
            },
        }
        error = self.cli(
            "workflow",
            "run",
            "--request",
            self.request({"steps": [self.material(), geometry]}),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertNotIn("material.assign", self.world.ops())

    def test_non_numeric_tolerance_combination_is_explicitly_unsupported(self):
        self.prepare_model()
        tolerance = self.tolerance()
        tolerance["args"] = {"model": "block.prt", "dimension": self.target["name"], "basic": True}
        error = self.cli(
            "workflow",
            "run",
            "--request",
            self.request({"steps": [self.standard(), tolerance]}),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertNotIn("model.set-tolerance-standard", self.world.ops())

    def test_partial_save_remains_partial_after_successful_properties(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save(), self.tolerance()])
        original = self.world.op

        def extra_version(op, q):
            result = original(op, q)
            if op == "model.save":
                self.world.write_version(self.ws, "block.prt", self.world.models["block.prt"])
            return result

        with patch.object(self.world, "op", side_effect=extra_version):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "partial")
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_final_unknown_is_queryable_from_new_process_without_replay(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        original = operations.update

        def limited(record):
            if record["command"] == "workflow run" and record.get("driver_receipt"):
                with patch.object(operations, "MAX_RECORD_BYTES", 1):
                    return original(record)
            return original(record)

        with patch.object(operations, "update", side_effect=limited):
            self.confirm(words, preview, status=6)
        before = len(self.world.ops())
        shown = subprocess.run(
            [
                sys.executable,
                "-m",
                "creo_cli",
                "operation",
                "show",
                "--id",
                preview["preview"]["operation_id"],
            ],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(shown.returncode, 0, shown.stderr)
        status = json.loads(shown.stdout)["data"]["operation_status"]
        self.assertEqual(status["status"], "unknown")
        rows = status["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual(rows[0]["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(rows[1]["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(len(self.world.ops()), before)

    def test_change_after_leaf_verifier_is_not_adopted_from_later_effect_readback(self):
        self.prepare_model()
        words, preview = self.preview([self.standard(), self.tolerance(), self.save()])
        original = operations.checkpoint_domain
        changed = False

        def mutate(record):
            nonlocal changed
            result = original(record)
            if (
                not changed
                and record["command"] == "model set-tolerance-standard"
                and record["status"] == "completed"
            ):
                changed = True
                self.other["tolerance"] = {"type": "basic"}
            return result

        with patch.object(operations, "checkpoint_domain", side_effect=mutate):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotIn("dimension.tolerance", self.world.ops())
        rows = self.parent(preview)["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual(rows[0]["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(rows[1]["status"], "skipped")

    def test_parent_consumed_then_external_drift_is_rejected_before_first_leaf(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        original = operations.begin

        def mutate(command, *args, **kwargs):
            record = original(command, *args, **kwargs)
            if command == "workflow run":
                self.other["tolerance"] = {"type": "basic"}
            return record

        with patch.object(operations, "begin", side_effect=mutate):
            error = self.confirm(words, preview, status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertNotIn("material.assign", self.world.ops())
        self.assertNotIn("model.save", self.world.ops())
        self.assertEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")

    def test_final_leaf_completed_then_external_drift_is_parent_partial(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        original = operations.update
        changed = False

        def mutate(record):
            nonlocal changed
            result = original(record)
            rows = record.get("driver_workflow", {}).get("steps", [])
            if not changed and rows and all(row["status"] == "completed" for row in rows):
                changed = True
                self.other["tolerance"] = {"type": "basic"}
                self.world.models["block.prt"]["modified"] = True
            return result

        with patch.object(operations, "update", side_effect=mutate):
            error = self.confirm(words, preview, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        parent = self.parent(preview)
        self.assertEqual(parent["status"], "partial")
        self.assertEqual(parent["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(parent["receipt"]["outcome"]["verification"]["status"], "failed")
        self.assertEqual(
            parent["receipt"]["extensions"]["creo"]["final_validation"]["status"], "failed"
        )
        rows = parent["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([row["status"] for row in rows], ["completed", "completed"])
        self.assertEqual(rows[-1]["receipt"]["outcome"]["persistence"], "saved")
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_final_property_read_failure_keeps_unknown_and_child_facts(self):
        self.prepare_model()
        words, preview = self.preview([self.material(), self.save()])
        original = operations.update
        original_dimensions = self.world.dimension_list
        changed = False

        def mutate(record):
            nonlocal changed
            result = original(record)
            rows = record.get("driver_workflow", {}).get("steps", [])
            if rows and all(row["status"] == "completed" for row in rows):
                changed = True
            return result

        def unreadable(q):
            if changed:
                raise Refusal("E_CREO", "final property getter unavailable")
            return original_dimensions(q)

        with (
            patch.object(operations, "update", side_effect=mutate),
            patch.object(self.world, "dimension_list", side_effect=unreadable),
        ):
            error = self.confirm(words, preview, status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        parent = self.parent(preview)
        self.assertEqual(parent["status"], "unknown")
        self.assertEqual(parent["receipt"]["outcome"]["persistence"], "unknown")
        rows = parent["extensions"]["creo"]["workflow"]["steps"]
        self.assertEqual([row["status"] for row in rows], ["completed", "completed"])
        self.assertEqual(rows[-1]["receipt"]["outcome"]["persistence"], "saved")

    def test_public_discovery_reports_supported_properties_and_recovery_limits(self):
        from creo_cli.workflow_tasks import SUPPORTED_WRITES

        reference = self.cli("reference", "--command", "workflow run")["data"]
        profile = reference["command"]["extensions"]["creo"]["bounded_workflow"]
        self.assertEqual(profile["supported_leaf_writes"], sorted(SUPPORTED_WRITES))
        self.assertEqual(profile["max_steps"], 32)
        self.assertEqual(
            profile["property_workflow"]["commands"],
            ["dimension set-tolerance", "material assign", "model set-tolerance-standard"],
        )
        self.assertEqual(
            profile["property_workflow"]["tolerance_forms"], ["limits", "plus_minus", "symmetric"]
        )
        self.assertIn("file identity", profile["property_workflow"]["file_binding"])
        self.assertIn(
            "retained engineering snapshot", profile["property_workflow"]["state_binding"]
        )
        self.assertIn("unknown", profile["outcomes"])
        self.assertIn("operation resolve", profile["recovery"])
        context = self.cli("context")["data"]
        self.assertEqual(context["extensions"]["creo"]["bounded_workflow"], profile)
        checks = self.cli("doctor")["data"]["checks"]
        check = next(row for row in checks if row["check"] == "workflow_scope")
        self.assertEqual(check["status"], "warn")
        self.assertEqual(check["details"]["extensions"]["creo"]["bounded_workflow"], profile)
        self.assertEqual(
            self.cli("reference")["data"]["release_readiness"]["fcc_coverage"], "partial"
        )
