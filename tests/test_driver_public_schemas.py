"""Validate actual command replies with an independent full JSON Schema implementation."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from creo_cli import driver
from tests.test_commands import RECT, Base

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = [
    json.loads(p.read_text(encoding="utf-8"))
    for p in (ROOT / ".agent/driver/schemas").glob("*.json")
]
RESOURCES = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS)


def validate(uri, value):
    Draft202012Validator({"$ref": uri}, registry=RESOURCES).validate(value)


class PublicSchemas(Base):
    def test_profile_metadata_plans_status_and_receipts(self):
        validate("urn:tool-driver-cli-spec:common:2.0#/$defs/driver_profile", driver.profile())
        for command in driver.MIGRATED:
            validate(
                "urn:tool-driver-cli-spec:reference:2.0#/$defs/driver",
                driver.command_metadata(command),
            )
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        validate("urn:tool-driver-cli-spec:plan:2.0", preview["preview"])
        op_id = preview["preview"]["operation_id"]
        validate(
            "urn:tool-driver-cli-spec:operation-status:2.0",
            self.cli("operation", "show", "--id", op_id)["data"]["operation_status"],
        )
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        validate("urn:tool-driver-cli-spec:receipt:2.0", result["receipt"])
        self.world.drop = "model.save"
        error = self.gated("model", "save", "--model", "block", status=6)["error"]
        validate("urn:tool-driver-cli-spec:receipt:2.0", error["details"]["receipt"])
