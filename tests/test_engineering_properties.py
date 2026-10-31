"""Public lifecycle and independent material/tolerance engineering checks."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests.fixture_features import Refusal
from tests.test_commands import ROOT
from tests.test_features import Built


class EngineeringProperties(Built):
    def test_other_table_driven_numeric_override_refuses_before_leaf_write(self):
        model = self.block()
        dims = model["dimensions"]
        target = self.numeric_dimension()
        other = next(d for d in dims if d["id"] != target["id"] and d["name"].startswith("d"))
        other["tolerance"] = {
            "type": "symmetric",
            "value": 0.2,
            "upper": other["value"] + 0.2,
            "lower": other["value"] - 0.2,
        }
        other["numeric_tolerance_table"] = {"complete": True, "assigned": True}
        self.cli(
            "dimension",
            "set-tolerance",
            "--model",
            "block.prt",
            "--dimension",
            target["name"],
            "--symmetric",
            0.1,
            "--units",
            "mm",
            "--dry-run",
            status=6,
        )
        self.assertNotIn("dimension.tolerance", self.world.ops())
        before = dict(other["tolerance"])
        self.gated(
            "model",
            "set-tolerance-standard",
            "--model",
            "block.prt",
            "--standard",
            "iso",
            "--class",
            "medium",
        )
        self.assertEqual(other["tolerance"], before)
        self.assertFalse(other["numeric_tolerance_table"]["assigned"])
        self.gated(
            "dimension",
            "set-tolerance",
            "--model",
            "block.prt",
            "--dimension",
            target["name"],
            "--symmetric",
            0.1,
            "--units",
            "mm",
        )

    def test_unreadable_tolerance_blocks_engineering_property_plan(self):
        self.block()
        self.numeric_dimension()["tolerance"] = {"type": None, "unreadable": "controlled"}
        self.cli(
            "model",
            "set-tolerance-standard",
            "--model",
            "block.prt",
            "--standard",
            "iso",
            "--dry-run",
            status=1,
        )
        self.assertNotIn("model.set-tolerance-standard", self.world.ops())

    def test_numeric_tolerance_missing_table_readback_is_zero_dispatch(self):
        self.block()
        dim = self.numeric_dimension()
        dim["numeric_tolerance_table"] = {"complete": False}
        self.cli(
            "dimension",
            "set-tolerance",
            "--model",
            "block.prt",
            "--dimension",
            dim["name"],
            "--symmetric",
            0.2,
            "--units",
            "mm",
            "--dry-run",
            status=1,
        )
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_old_numeric_service_capability_is_zero_dispatch(self):
        self.block()
        dim = self.numeric_dimension()
        self.world.capabilities.pop("numeric_tolerance_regeneration_readback")
        self.cli(
            "dimension",
            "set-tolerance",
            "--model",
            "block.prt",
            "--dimension",
            dim["name"],
            "--symmetric",
            0.2,
            "--units",
            "mm",
            "--dry-run",
            status=4,
        )
        self.assertNotIn("dimension.tolerance", self.world.ops())

    def test_failure_after_only_table_detachment_is_partial(self):
        model = self.block()
        self.gated("model", "save", "--model", "block.prt")
        dim = self.numeric_dimension()
        dim["numeric_tolerance_table"] = {"complete": True, "assigned": True}

        def detached(q):
            dim["numeric_tolerance_table"] = {"complete": True, "assigned": False}
            raise Refusal("E_CREO", "controlled failure after detaching the table")

        with patch.object(self.world, "dimension_tolerance", side_effect=detached):
            error = self.gated(
                "dimension",
                "set-tolerance",
                "--model",
                "block.prt",
                "--dimension",
                dim["name"],
                "--symmetric",
                0.2,
                "--units",
                "mm",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertFalse(model["modified"])
        self.assertNotEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_numeric_tolerance_reset_to_general_values_is_not_success(self):
        model = self.block()
        target = self.numeric_dimension()
        original = self.world.dimension_tolerance

        def reset_to_general(q):
            echoed = original(q)
            value = target["value"]
            target["tolerance"] = {
                "type": "symmetric",
                "value": 0.3,
                "upper": value + 0.3,
                "lower": value - 0.3,
            }
            return echoed

        with patch.object(self.world, "dimension_tolerance", side_effect=reset_to_general):
            error = self.gated(
                "dimension",
                "set-tolerance",
                "--model",
                "block.prt",
                "--dimension",
                target["name"],
                "--symmetric",
                0.2,
                "--units",
                "mm",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertTrue(model["modified"])
        self.assertNotEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_public_discovery_reports_property_limits_and_source_option(self):
        ref = self.cli("reference", "--command", "material assign")["data"]
        command = ref["command"]
        self.assertIn("file", [p["name"] for p in command["params"]])
        limits = self.cli("reference")["data"]["capabilities"]["bounded_engineering_properties"]
        self.assertEqual(len(limits), 3)
        self.assertEqual(
            self.cli("context")["data"]["capabilities"]["bounded_engineering_properties"],
            limits,
        )

    def test_missing_or_malformed_density_is_explicitly_rejected(self):
        from creo_cli.material_files import read_source

        missing = self.ws / "absent.mtl"
        with self.assertRaises(Error) as raised:
            read_source(missing)
        self.assertEqual(raised.exception.code, "E_NOT_FOUND")
        file = self.synthetic()
        file.write_text(file.read_text().replace("2.7e-9", ".."))
        with self.assertRaises(Error) as raised:
            read_source(file)
        self.assertEqual(raised.exception.code, "E_VERIFY_INCOMPLETE")

    def synthetic(self):
        path = self.ws / "R11_SYNTH.mtl"
        path.write_text(
            "ND_RelParSet_K01 = {\nName = R11_SYNTH\nPARAMETERS =\n{\n"
            "Name = PTC_MASS_DENSITY\nType = Real\nDefault = 2.7e-9 tonne / mm^3\n"
            "Access = Full\n}\n}\n"
        )
        return path

    def material_args(self, file):
        return (
            "material",
            "assign",
            "--model",
            "block.prt",
            "--material",
            "R11_SYNTH",
            "--file",
            file,
        )

    def test_explicit_source_assigns_independently_measured_density_and_mass(self):
        self.block()
        result = self.gated(*self.material_args(self.synthetic()))["data"]
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        actual = self.cli("material", "list", "--model", "block.prt")["data"]["model"]
        self.assertEqual(actual["density"], {"value": 2.7e-9, "units": "tonne/mm^3"})
        self.assertAlmostEqual(actual["mass_properties"]["mass"], 8000 * 2.7e-9)

    def test_same_bytes_replaced_material_source_rejects_confirmation(self):
        self.block()
        path = self.synthetic()
        words = self.material_args(path)
        preview = self.cli(*words, "--dry-run")["data"]
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("material.assign", self.world.ops())

    def test_changed_material_density_source_rejects_confirmation(self):
        self.block()
        path = self.synthetic()
        words = self.material_args(path)
        preview = self.cli(*words, "--dry-run")["data"]
        path.write_text(path.read_text().replace("2.7e-9", "3.1e-9"))
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("material.assign", self.world.ops())

    def test_material_scope_denial_is_zero_native_dispatch(self):
        self.block()
        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        data = json.loads(scope.read_text())
        data["effects"] = ["observe"]
        scope.write_text(json.dumps(data))
        words = self.material_args(self.synthetic())
        preview = self.cli(*words, "--dry-run")["data"]
        self.assertFalse(preview["preview"]["can_apply"])
        self.cli(*words, "--confirm", preview["confirm_token"], status=4)
        self.assertNotIn("material.assign", self.world.ops())

    def test_final_receipt_failure_keeps_each_property_path_unknown(self):
        self.block()
        dim = self.numeric_dimension()["name"]
        commands = [
            self.material_args(self.synthetic()),
            (
                "dimension",
                "set-tolerance",
                "--model",
                "block.prt",
                "--dimension",
                dim,
                "--symmetric",
                0.1,
                "--units",
                "mm",
            ),
            (
                "model",
                "set-tolerance-standard",
                "--model",
                "block.prt",
                "--standard",
                "iso",
                "--class",
                "medium",
            ),
        ]
        for words in commands:
            with self.subTest(command=words[:2]):
                pre = self.cli(*words, "--dry-run")["data"]
                update = operations.update

                def fail_final(record, update=update):
                    if record.get("driver_receipt"):
                        raise Error("E_IO", "controlled final property receipt failure")
                    return update(record)

                with patch.object(operations, "update", side_effect=fail_final):
                    self.cli(*words, "--confirm", pre["confirm_token"], status=6)
                ident = pre["preview"]["operation_id"]
                with patch.dict(os.environ, self.env, clear=True):
                    stored = operations.get(ident)
                self.assertEqual(stored["status"], "running")
                self.assertIsNone(stored["driver_receipt"])
                p = subprocess.run(
                    [sys.executable, "-m", "creo_cli", "operation", "show", "--id", ident],
                    cwd=ROOT,
                    env=self.env,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                shown = json.loads(p.stdout)["data"]["operation_status"]
                self.assertEqual(shown["receipt"]["outcome"]["persistence"], "unknown")
                self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)
                self.cli(*words, "--confirm", pre["confirm_token"], status=6)
                self.cli(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "applied",
                    "--evidence",
                    "Independent fixture model, numeric property and unchanged geometry inspected",
                )

    def numeric_dimension(self):
        return next(
            d for d in self.world.models["block.prt"]["dimensions"] if d["name"].startswith("d")
        )

    def test_three_existing_paths_preallocate_public_operations(self):
        self.block()
        dim = self.numeric_dimension()["name"]
        commands = [
            ("material", "assign", "--model", "block.prt", "--material", "Steel_low_carbon"),
            (
                "dimension",
                "set-tolerance",
                "--model",
                "block.prt",
                "--dimension",
                dim,
                "--symmetric",
                0.1,
                "--units",
                "mm",
            ),
            (
                "model",
                "set-tolerance-standard",
                "--model",
                "block.prt",
                "--standard",
                "iso",
                "--class",
                "medium",
            ),
        ]
        for words in commands:
            with self.subTest(command=words[:2]):
                data = self.cli(*words, "--dry-run")["data"]
                self.assertIn("operation_id", data["preview"])

    def test_tolerance_cannot_change_an_unrelated_dimension(self):
        model = self.block()
        target = self.numeric_dimension()
        other = next(
            d
            for d in model["dimensions"]
            if d["name"].startswith("d") and d["name"] != target["name"]
        )
        original = self.world.dimension_tolerance

        def wrong(q):
            result = original(q)
            other["value"] += 1
            return result

        with patch.object(self.world, "dimension_tolerance", side_effect=wrong):
            error = self.gated(
                "dimension",
                "set-tolerance",
                "--model",
                "block.prt",
                "--dimension",
                target["name"],
                "--symmetric",
                0.1,
                "--units",
                "mm",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.cli("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_standard_failure_that_dirties_model_is_partial(self):
        model = self.block()
        self.gated("model", "save", "--model", "block.prt")

        def dirty(q):
            model["modified"] = True
            raise Refusal("E_CREO", "failed after marking the test model modified")

        with patch.object(self.world, "set_tolerance_standard", side_effect=dirty):
            error = self.gated(
                "model",
                "set-tolerance-standard",
                "--model",
                "block.prt",
                "--standard",
                "iso",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertNotEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")

    def test_material_name_and_positive_mass_do_not_replace_density_readback(self):
        self.block()
        original = self.world.material_assign

        def wrong(q):
            result = original(q)
            self.world.models["block.prt"]["density"] = 1e-9
            return result

        with patch.object(self.world, "material_assign", side_effect=wrong):
            error = self.gated(
                "material",
                "assign",
                "--model",
                "block.prt",
                "--material",
                "Steel_low_carbon",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
