"""Round-seven authorization, source and native BOM verification boundaries."""

import copy

from creo_cli import dependencies, driver
from tests import test_family as family_tests


def test_round7_paths_have_public_lifecycle():
    assert {
        "assembly component replace",
        "drawing bom add",
        "drawing bom balloons",
        "drawing title-block apply",
    } <= set(driver.MIGRATED)


def test_replacement_reference_roots_include_candidate():
    assert dependencies.references(
        "assembly component replace", {"model": "rig", "component": "41", "with": "new.asm"}
    ) == {"rig.asm", "new.asm"}


class ReplacementBoundary(family_tests.Families):
    def setup_replacement(self):
        component = family_tests.ReplacingAComponent.rig(self)
        return (
            "assembly",
            "component",
            "replace",
            "--model",
            "rig",
            "--component",
            component,
            "--with",
            "block_wide",
        )

    def test_candidate_source_file_drift_before_confirmation_no_replace(self):
        args = self.setup_replacement()
        pre = self.cli(*args, "--dry-run")["data"]
        versions = sorted(self.ws.glob("block.prt*"))
        versions[-1].write_bytes(versions[-1].read_bytes() + b"external-change")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("assembly.replace", self.world.ops())

    def test_unrelated_unknown_allowed_candidate_unknown_blocked(self):
        args = self.setup_replacement()
        self.part("unrelated.prt")
        self.world.drop = "parameter.set"
        self.gated(
            "parameter",
            "set",
            "--model",
            "unrelated",
            "--name",
            "TEST",
            "--type",
            "string",
            "--value",
            "actual",
            "--create",
            status=6,
        )
        self.world.drop = None
        self.cli(*args, "--dry-run")
        self.world.drop = "parameter.set"
        self.gated(
            "parameter",
            "set",
            "--model",
            "block_wide",
            "--name",
            "TEST",
            "--type",
            "string",
            "--value",
            "actual",
            "--create",
            status=6,
        )
        self.world.drop = None
        before = copy.deepcopy(self.world.models["rig.asm"])
        err = self.cli(*args, "--dry-run", status=6)["error"]
        self.assertEqual(err["details"]["conflict"], "unresolved_operation")
        self.assertEqual(before, self.world.models["rig.asm"])
        self.assertNotIn("assembly.replace", self.world.ops())
