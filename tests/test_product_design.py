"""Development-record consistency and false native-promotion guards, not Creo tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.check_product_design import ROOT, validate

SPEC_ROOT = os.environ.get("CREO_CLI_DESIGN_SPEC_ROOT")


@unittest.skipUnless(
    SPEC_ROOT, "development-schema tests need an existing readonly pinned spec checkout"
)
class ProductDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.product = json.loads((ROOT / "registry.design.json").read_text(encoding="utf-8"))

    def check(self, product):
        return validate(product, spec_root=Path(SPEC_ROOT))

    def test_all_actual_commands_and_scoped_capabilities_close_without_native_claims(self):
        report = self.check(self.product)
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            report["declaration_counts"],
            {
                "commands": len(__import__("creo_cli.registry", fromlist=["COMMANDS"]).COMMANDS),
                "tasks": 8,
                "capabilities": 36,
            },
        )
        self.assertEqual(report["coverage"]["verified"], 0)
        self.assertEqual(report["coverage"]["supported_tasks"], 0)
        self.assertEqual(
            report["coverage"]["declared_command_fcc"], "not_evaluated_by_this_checker"
        )
        self.assertFalse(report["public_runtime_contract_checked"])

    def test_command_omission_is_rejected(self):
        product = copy.deepcopy(self.product)
        product["design"]["commands"].pop()
        self.assertTrue(self.check(product)["errors"])

    def test_dropping_a_difficult_capability_from_the_denominator_is_rejected(self):
        product = copy.deepcopy(self.product)
        product["design"]["coverage"]["denominator_ids"].remove("g-native-modelcheck")
        self.assertTrue(self.check(product)["errors"])

    def test_required_parameters_remain_required_even_for_planned_tasks(self):
        product = copy.deepcopy(self.product)
        task = next(t for t in product["design"]["tasks"] if t["id"] == "t-min")
        task["critical_parameters"] = [
            p
            for p in task["critical_parameters"]
            if (p["command_path"], p["name"]) != ("dimension set", "model")
        ]
        self.assertIn(
            "planned task omits required critical parameters", self.check(product)["errors"]
        )

    def test_forged_adapter_entry_is_rejected(self):
        product = copy.deepcopy(self.product)
        product["design"]["tasks"][0]["adapter_entries"][0]["entrypoint"] = "fictional_handler"
        self.assertIn(
            "task adapter entries differ from actual Python/Java dispatch declarations",
            self.check(product)["errors"],
        )

    def test_changed_evidence_hash_is_rejected(self):
        product = copy.deepcopy(self.product)
        product["design"]["evidence"][0]["sha256"] = "0" * 64
        self.assertTrue(self.check(product)["errors"])

    def test_git_lf_evidence_validates_crlf_and_lf_without_accepting_content_drift(self):
        product = copy.deepcopy(self.product)
        with tempfile.TemporaryDirectory() as directory:
            mirror = Path(directory)
            for item in product["design"]["evidence"]:
                if not item.get("path") or not item.get("sha256"):
                    continue
                data = (ROOT / item["path"]).read_bytes().replace(b"\r\n", b"\n")
                item["sha256"] = hashlib.sha256(data).hexdigest()
                target = mirror / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            for newline in (b"\r\n", b"\n"):
                changed = mirror / "creo_cli/commands/assembly.py"
                data = changed.read_bytes().replace(b"\r\n", b"\n")
                changed.write_bytes(data.replace(b"\n", newline))
                self.assertEqual(
                    validate(product, spec_root=Path(SPEC_ROOT), directory=mirror)["errors"], []
                )
            changed.write_bytes(changed.read_bytes() + b"# unapproved semantic input\n")
            self.assertTrue(
                validate(product, spec_root=Path(SPEC_ROOT), directory=mirror)["errors"]
            )

    def test_fixture_success_cannot_be_a_passed_native_task_test(self):
        product = copy.deepcopy(self.product)
        test = product["design"]["tests"][0]
        test["status"] = "passed"
        test["evidence_ref"] = "ev-fixture-offline"
        self.assertTrue(
            any("passed needs matching real run" in e for e in self.check(product)["errors"])
        )

    def test_available_source_cannot_be_promoted_to_native_verified(self):
        product = copy.deepcopy(self.product)
        next(c for c in product["design"]["capabilities"] if c["id"] == "c-dimension")[
            "testing"
        ] = "verified"
        self.assertTrue(any("verified needs" in e for e in self.check(product)["errors"]))

    def test_supported_task_requires_actual_passing_command_readback_evidence(self):
        product = copy.deepcopy(self.product)
        next(t for t in product["design"]["tasks"] if t["id"] == "t-min")["status"] = "supported"
        self.assertTrue(
            any("actual passing command/readback tests" in e for e in self.check(product)["errors"])
        )
