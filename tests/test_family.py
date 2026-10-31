"""Command-level tests for family tables and an instance opened
from its generic -- against the loopback substitute."""

from __future__ import annotations

import json

from tests.fixture import INCH
from tests.test_commands import domain_preview
from tests.test_features import Built


class Families(Built):
    """A block with a parameter, and a family of it."""

    def request(self, body, name="request.json"):
        file = self.ws / name
        file.write_text(json.dumps(body), encoding="utf8")
        return str(file)

    def close_members(self):
        self.gated("model", "save", "--model", "block")
        for name, model in list(self.world.models.items()):
            if model.get("generic") == "block.prt":
                self.gated("model", "close", "--model", name)

    def table(self):
        self.block()
        self.gated(
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "BLOCK 40",
            "--create",
        )
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        depth = next(d["name"] for d in dims if d["value"] == 10 and d.get("type"))
        width = next(d["name"] for d in dims if d["value"] == 40 and d.get("type"))
        return depth, width

    def request_for(self, depth, width):
        return {
            "units": "mm",
            "instances": [
                {
                    "name": "BLOCK_20",
                    "values": {f"dimension:{depth}": 20},
                },
                {
                    "name": "BLOCK_WIDE",
                    "values": {f"dimension:{width}": 60},
                },
            ],
        }

    def set(self, body, *flags, status=0, model="block"):
        return self.cli(
            "family-table",
            "apply",
            "--model",
            model,
            "--request",
            self.request(body, "family.json"),
            *flags,
            status=status,
        )

    def build(self, body, model="block"):
        return self.gated(
            "family-table",
            "apply",
            "--model",
            model,
            "--request",
            self.request(body, "family.json"),
        )["data"]


class FamilyTables(Families):
    """Numeric variants and conservative refusals through the migrated public contract."""

    def test_variants_set_then_read(self):
        depth, width = self.table()
        empty = self.cli("family-table", "show", "--model", "block")["data"]
        self.assertEqual((empty["columns"], empty["instances"], empty["generic"]), ([], [], None))
        body = self.request_for(depth, width)
        preview = domain_preview(self.set(body, "--dry-run")["data"]["preview"])
        self.assertEqual(preview["intent"]["requested_columns"], sorted([depth, width]))
        self.assertEqual(preview["intent"]["values"]["block_20"][depth], 20)
        self.assertEqual(preview["instance_count"], 2)
        data = self.build(body)
        self.checks_pass(data)
        self.assertEqual(data["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertIn(
            "instance_dimension:block_20:" + depth,
            [c["check"] for c in data["verification"]["checks"]],
        )
        sent = [q for n, q in self.world.events if n == "family.set"][-1]
        self.assertNotIn("units", sent)
        shown = self.cli("family-table", "show", "--model", "block")["data"]
        rows = {i["name"]: i["cells"] for i in shown["instances"]}
        self.assertEqual(rows["BLOCK_20"][depth], {"value": 20, "generic": False})
        self.assertEqual(rows["BLOCK_20"][width]["generic"], True)
        self.assertIn("columns", shown["_untrusted"])
        family = self.cli("model", "show", "--model", "block")["data"]["family"]
        self.assertEqual(
            (family["generic"], family["instances"], family["complete"]),
            (None, ["BLOCK_20", "BLOCK_WIDE"], True),
        )
        # A second set changes a cell and leaves the other instance as it was.
        self.close_members()
        again = self.build(
            {
                "units": "mm",
                "instances": [{"name": "BLOCK_20", "values": {f"dimension:{depth}": 25}}],
            }
        )
        self.checks_pass(again)

    def test_nonpositive_length_is_rejected_before_native_dispatch(self):
        depth, width = self.table()
        self.build(self.request_for(depth, width))
        bad = {
            "units": "mm",
            "instances": [
                {"name": "BLOCK_20", "values": {f"dimension:{depth}": 30}},
                {"name": "BLOCK_FLAT", "values": {f"dimension:{depth}": 0}},
            ],
        }
        count = self.world.ops().count("family.set")
        error = self.cli(
            "family-table",
            "apply",
            "--model",
            "block",
            "--request",
            self.request(bad, "family.json"),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_VALIDATION")
        self.assertEqual(self.world.ops().count("family.set"), count)
        rows = {
            i["name"]: i["cells"]
            for i in self.cli("family-table", "show", "--model", "block")["data"]["instances"]
        }
        self.assertEqual(sorted(rows), ["BLOCK_20", "BLOCK_WIDE"])
        self.assertEqual(rows["BLOCK_20"][depth]["value"], 20)
        # No rollback is asserted: the invalid edit was never dispatched.

    def test_an_instance_opened_from_its_generic(self):
        depth, width = self.table()
        self.build(self.request_for(depth, width))
        self.close_members()
        opened = self.gated(
            "model", "open", "--path", str(self.ws / "block.prt"), "--instance", "BLOCK_20"
        )["data"]
        self.checks_pass(opened)
        self.assertEqual(opened["result"]["family"]["generic"], "block.prt")
        sent = [q for n, q in self.world.events if n == "model.open"][-1]
        self.assertEqual(sent["instance"], "block_20")
        shown = self.cli("model", "show", "--model", "block_20")["data"]
        self.assertEqual(
            (shown["family"]["generic"], shown["family"]["instances"]), ("block.prt", [])
        )
        # An instance has no file of its own, and its table is its generic's.
        error = self.cli("model", "save", "--model", "block_20", "--dry-run", status=2)["error"]
        self.assertEqual(
            (error["code"], error["details"]["generic"]), ("E_VALIDATION", "block.prt")
        )
        error = self.set(self.request_for(depth, width), "--dry-run", status=2, model="block_20")[
            "error"
        ]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        # Opened again, it is refused; an instance the table lacks is named with those it has.
        self.cli(
            "model",
            "open",
            "--path",
            str(self.ws / "block.prt"),
            "--instance",
            "BLOCK_20",
            "--dry-run",
            status=6,
        )
        missing = self.cli(
            "model",
            "open",
            "--path",
            str(self.ws / "block.prt"),
            "--instance",
            "BLOCK_9",
            "--dry-run",
            status=3,
        )["error"]
        self.assertEqual(missing["details"]["instances"], ["BLOCK_20", "BLOCK_WIDE"])
        # Open members are refused; no hidden close or discard.
        self.cli(
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "BLOCK_20",
            "--dangerous",
            "--dry-run",
            status=6,
        )
        self.close_members()
        removed = self.gated(
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "BLOCK_20",
            dangerous=True,
        )["data"]
        self.checks_pass(removed)
        self.assertNotIn(
            "block_20.prt", [m["model"] for m in self.cli("model", "list")["data"]["items"]]
        )

    def test_remove_is_dangerous_and_names_what_there_is(self):
        depth, width = self.table()
        self.build(self.request_for(depth, width))
        self.close_members()
        self.cli(
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "BLOCK_20",
            "--dry-run",
            status=5,
        )
        missing = self.cli(
            "family-table",
            "remove-instance",
            "--model",
            "block",
            "--instance",
            "BLOCK_9",
            "--dangerous",
            "--dry-run",
            status=3,
        )["error"]
        self.assertEqual(missing["code"], "E_NOT_FOUND")
        preview = domain_preview(
            self.cli(
                "family-table",
                "remove-instance",
                "--model",
                "block",
                "--instance",
                "BLOCK_WIDE",
                "--dangerous",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["intent"]["instance"], "block_wide")
        self.assertIn("removal_basis", preview["intent"])

    def test_what_a_family_request_cannot_be(self):
        depth, width = self.table()
        one = {"name": "BLOCK_20", "values": {f"dimension:{depth}": 20}}
        for body, code, status in (
            ({"instances": [one]}, "E_VALIDATION", 2),
            ({"units": "mm", "instances": []}, "E_VALIDATION", 2),
            ({"units": "mm", "instances": [one | {"name": "20_BLOCK"}]}, "E_VALIDATION", 2),
            ({"units": "mm", "instances": [one, one | {"name": "block_20"}]}, "E_VALIDATION", 2),
            ({"units": "mm", "instances": [one | {"values": {}}]}, "E_VALIDATION", 2),
            ({"units": "mm", "instances": [one | {"values": {depth: 20}}]}, "E_VALIDATION", 2),
            (
                {"units": "mm", "instances": [one | {"values": {f"dimension:{depth}": "20"}}]},
                "E_VALIDATION",
                2,
            ),
            (
                {"units": "mm", "instances": [one | {"values": {"feature:BLOCK": "no"}}]},
                "E_UNSUPPORTED",
                2,
            ),
            (
                {"units": "mm", "instances": [one | {"values": {"parameter:DESCRIPTION": 20}}]},
                "E_UNSUPPORTED",
                2,
            ),
            (
                {"units": "mm", "instances": [one | {"values": {"dimension:d99": 20}}]},
                "E_NOT_FOUND",
                3,
            ),
            (
                {"units": "mm", "instances": [one | {"values": {"parameter:NOPE": "x"}}]},
                "E_UNSUPPORTED",
                2,
            ),
            (
                {"units": "mm", "instances": [one | {"values": {"feature:NOPE": True}}]},
                "E_UNSUPPORTED",
                2,
            ),
            ({"units": "in", "instances": [one]}, "E_CONFLICT", 6),
        ):
            with self.subTest(body=body):
                self.assertEqual(self.set(body, "--dry-run", status=status)["error"]["code"], code)

    def test_an_inch_part_takes_inches(self):
        self.part(units=INCH)
        self.gated(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(
                {
                    "units": "in",
                    "name": "BLOCK",
                    "depth": 1,
                    "sketch": {
                        "plane": "FRONT",
                        "orient_ref": "RIGHT",
                        "profile": {"type": "rectangle", "width": 4, "height": 2},
                    },
                },
                "inch.json",
            ),
        )
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        depth = next(d["name"] for d in dims if d["value"] == 1 and d.get("type"))
        body = {
            "units": "in",
            "instances": [{"name": "BLOCK_2", "values": {f"dimension:{depth}": 2}}],
        }
        self.checks_pass(self.build(body))
        self.set(body | {"units": "mm"}, "--dry-run", status=6)


class ReplacingAComponent(Families):
    """A component swapped for another member of its family, as Component > Replace does it
    with a family table: the same constraints hold the new size."""

    def rig(self):
        depth, width = self.table()
        self.build(self.request_for(depth, width))
        self.close_members()
        for instance in ("BLOCK_20", "BLOCK_WIDE"):
            self.gated(
                "model", "open", "--path", str(self.ws / "block.prt"), "--instance", instance
            )
        self.world.part("rig.asm")
        self.world.make_assembly(self.world.models["rig.asm"])
        placed = self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "rig",
            "--component",
            "block_20",
            "--request",
            self.request({"constraints": [{"type": "default"}]}, "default.json"),
        )["data"]
        return placed["result"]["component"]["id"]

    def test_another_size_held_by_the_same_constraints(self):
        component = self.rig()
        preview = domain_preview(
            self.cli(
                "assembly",
                "component",
                "replace",
                "--model",
                "rig",
                "--component",
                component,
                "--with",
                "block_wide",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["family"], preview["with"]), ("block.prt", "block_wide.prt"))
        data = self.gated(
            "assembly",
            "component",
            "replace",
            "--model",
            "rig",
            "--component",
            component,
            "--with",
            "block_wide",
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [c["check"] for c in data["verification"]["checks"]],
            [
                "component_holds_the_new_model",
                "component_placed",
                "constraints_kept",
                "other_components_unchanged",
                "new_dependency_independently_read",
            ],
        )
        self.assertEqual(data["result"]["replaced"], "block_20.prt")
        sent = [q for n, q in self.world.events if n == "assembly.replace"][-1]
        self.assertEqual(
            sent, {"model": "rig.asm", "component": component, "with": "block_wide.prt"}
        )
        # Back to the generic, by the model's name.
        self.checks_pass(
            self.gated(
                "assembly",
                "component",
                "replace",
                "--model",
                "rig",
                "--component",
                "block_wide",
                "--with",
                "block",
            )["data"]
        )

    def test_only_a_member_of_the_family_takes_its_place(self):
        component = self.rig()
        self.world.part("other.prt")
        for with_, code, status in (
            ("other", "E_VALIDATION", 2),
            ("block_20", "E_VALIDATION", 2),
            ("nothing", "E_NOT_FOUND", 3),
        ):
            with self.subTest(with_=with_):
                error = self.cli(
                    "assembly",
                    "component",
                    "replace",
                    "--model",
                    "rig",
                    "--component",
                    component,
                    "--with",
                    with_,
                    "--dry-run",
                    status=status,
                )["error"]
                self.assertEqual(error["code"], code)
        missing = self.cli(
            "assembly",
            "component",
            "replace",
            "--model",
            "rig",
            "--component",
            "999",
            "--with",
            "block_wide",
            "--dry-run",
            status=3,
        )["error"]
        self.assertEqual(missing["code"], "E_NOT_FOUND")
