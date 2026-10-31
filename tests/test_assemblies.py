"""Command-level tests for assemblies and drawings, against the loopback substitute."""

from __future__ import annotations

from pathlib import Path

from tests.test_commands import RECT, domain_preview
from tests.test_features import Built

PIN = RECT | {
    "name": "ROD",
    "depth": 20,
    "sketch": RECT["sketch"] | {"profile": {"type": "circle", "diameter": 10}},
}


class AssemblyParts(Built):
    """A block and a pin to assemble."""

    def parts(self):
        self.block()
        self.part("pin.prt")
        self.gated(
            "feature", "extrude", "--model", "pin", "--request", self.request(PIN, "pin.json")
        )

    def assembly(self):
        created = self.gated("assembly", "create", "--name", "gearbox", "--units", "mmns")["data"]
        self.checks_pass(created)
        return created


class Assemblies(AssemblyParts):
    def test_create_add_check_remove(self):
        self.parts()
        created = self.assembly()
        self.assertEqual(created["result"]["model"], "gearbox.asm")
        self.assertEqual(created["result"]["datum_planes"], ["ASM_RIGHT", "ASM_TOP", "ASM_FRONT"])
        base = self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "gearbox",
            "--component",
            "block",
            "--request",
            self.request({"constraints": [{"type": "default"}]}, "a.json"),
        )["data"]
        self.checks_pass(base)
        top = self.top()["ref"]
        placing = {
            "constraints": [
                {"type": "mate", "assembly_ref": f"{top}@block", "component_ref": "surface:1002"},
                {"type": "align", "assembly_ref": "ASM_RIGHT", "component_ref": "RIGHT"},
                {"type": "align", "assembly_ref": "ASM_TOP", "component_ref": "TOP"},
            ]
        }
        pins = [
            g["ref"]
            for g in self.cli("geometry", "list", "--model", "pin", "--kind", "surface")["data"][
                "items"
            ]
        ]
        placing["constraints"][0]["component_ref"] = pins[1]
        preview = domain_preview(
            self.cli(
                "assembly",
                "component",
                "add",
                "--model",
                "gearbox",
                "--component",
                "pin",
                "--request",
                self.request(placing, "b.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertIn(pins[1], preview["component_references"])
        pin = self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "gearbox",
            "--component",
            "pin",
            "--request",
            self.request(placing, "b.json"),
        )["data"]
        self.checks_pass(pin)
        self.assertEqual(len(pin["result"]["component"]["constraints"]), 3)
        clean = self.cli("assembly", "interference", "check", "--model", "gearbox")["data"]
        self.assertEqual(clean["interferences"], [])
        self.assertEqual(clean["not_fully_constrained"], 0)
        clash = self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "gearbox",
            "--component",
            "pin",
            "--request",
            self.request({"constraints": [{"type": "default"}]}, "c.json"),
        )["data"]
        checked = self.cli("assembly", "interference", "check", "--model", "gearbox")["data"]
        self.assertEqual(len(checked["interferences"]), 1)
        shown = self.cli("model", "show", "--model", "gearbox.asm")["data"]
        self.assertEqual(len(shown["components"]), 3)
        ambiguous = self.cli(
            "assembly",
            "component",
            "remove",
            "--model",
            "gearbox",
            "--component",
            "pin",
            "--dangerous",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(ambiguous["code"], "E_CONFLICT")
        self.assertEqual(
            self.cli(
                "assembly",
                "component",
                "remove",
                "--model",
                "gearbox",
                "--component",
                "pin",
                "--dry-run",
                status=5,
            )["error"]["code"],
            "E_CONFIRMATION_REQUIRED",
        )
        removed = self.gated(
            "assembly",
            "component",
            "remove",
            "--model",
            "gearbox",
            "--component",
            clash["result"]["component"]["id"],
            dangerous=True,
        )["data"]
        self.checks_pass(removed)
        self.assertEqual(
            self.cli("assembly", "interference", "check", "--model", "gearbox")["data"][
                "interferences"
            ],
            [],
        )

    def test_requests_checked_before_creo(self):
        self.parts()
        self.assembly()
        for body, code, status in (
            ({"constraints": [{"type": "default", "assembly_ref": "ASM_TOP"}]}, "E_VALIDATION", 2),
            ({"constraints": [{"type": "mate", "assembly_ref": "ASM_TOP"}]}, "E_VALIDATION", 2),
            (
                {
                    "constraints": [
                        {
                            "type": "mate",
                            "assembly_ref": "ASM_TOP",
                            "component_ref": "TOP",
                            "offset": 5,
                        }
                    ]
                },
                "E_VALIDATION",
                2,
            ),
            (
                {
                    "constraints": [
                        {
                            "type": "insert",
                            "assembly_ref": "ASM_TOP",
                            "component_ref": "TOP",
                            "offset": 5,
                        }
                    ],
                    "units": "mm",
                },
                "E_VALIDATION",
                2,
            ),
            (
                {
                    "constraints": [
                        {"type": "mate", "assembly_ref": "ASM_TOP", "component_ref": "edge:5"}
                    ]
                },
                "E_NOT_FOUND",
                3,
            ),
            (
                {
                    "constraints": [
                        {"type": "mate", "assembly_ref": "ASM_TOP@@x", "component_ref": "TOP"}
                    ]
                },
                "E_VALIDATION",
                2,
            ),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "assembly",
                        "component",
                        "add",
                        "--model",
                        "gearbox",
                        "--component",
                        "pin",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        self.assertEqual(
            self.cli(
                "assembly",
                "component",
                "add",
                "--model",
                "gearbox",
                "--component",
                "gearbox.asm",
                "--request",
                self.request({"constraints": [{"type": "default"}]}, "self.json"),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        offset = {
            "units": "in",
            "constraints": [
                {"type": "mate", "assembly_ref": "ASM_TOP", "component_ref": "TOP", "offset": 1}
            ],
        }
        self.assertEqual(
            self.cli(
                "assembly",
                "component",
                "add",
                "--model",
                "gearbox",
                "--component",
                "pin",
                "--request",
                self.request(offset, "in.json"),
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )


class Drawings(Built):
    def test_create_view_annotate_and_export(self):
        self.block()
        # The template's own three views, kept as asked.
        created = self.gated(
            "drawing",
            "create",
            "--name",
            "block",
            "--of",
            "block",
            "--sheet",
            "a3",
            "--views",
            "template",
        )["data"]
        self.checks_pass(created)
        self.assertEqual(created["result"]["model"], "block.drw")
        self.assertEqual(len(created["result"]["views"]), 3)
        iso = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "general",
            "--orientation",
            "isometric",
            "--x",
            330,
            "--y",
            220,
            "--scale",
            1,
        )["data"]
        self.checks_pass(iso)
        self.assertEqual(len(iso["result"]["views"]), 4)
        parent = created["result"]["views"][0]["name"]
        projected = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "projection",
            "--parent",
            parent,
            "--x",
            300,
            "--y",
            100,
        )["data"]
        self.checks_pass(projected)
        # Named the same whatever language Creo speaks: after the orientation, or what it is.
        self.assertEqual(iso["result"]["view"]["name"], "ISOMETRIC")
        self.assertEqual(projected["result"]["view"]["name"], "PROJECTION")
        noted = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        self.checks_pass(noted)
        self.assertEqual(noted["result"]["annotated"]["shown"], 3)
        shown = self.cli("model", "show", "--model", "block.drw")["data"]
        self.assertEqual(len(shown["views"]), 5)
        (self.ws / "out").mkdir()
        pdf = self.gated("artifact", "export", "--model", "block.drw", "--output", "out/block.pdf")[
            "data"
        ]
        self.checks_pass(pdf)
        self.assertTrue(Path(pdf["result"]["file"]).read_bytes().startswith(b"%PDF-"))
        # A bare name exported to PDF is the drawing of that name.
        bare = domain_preview(
            self.cli(
                "artifact", "export", "--model", "block", "--output", "out/again.pdf", "--dry-run"
            )["data"]["preview"]
        )
        self.assertEqual(bare["model"], "block.drw")

    def test_drawn_in_lines_with_ratio_scales_and_no_datum_dimensions(self):
        self.block()
        self.gated(
            "feature",
            "datum-plane",
            "--model",
            "block",
            "--request",
            self.request(
                {"units": "mm", "name": "MID", "offset": {"from": "FRONT", "distance": -5}},
                "mid.json",
            ),
        )
        created = self.gated(
            "drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3"
        )["data"]
        self.checks_pass(created)
        # Drawn as a drafter draws, whatever the session shows, and scales labelled 2:1.
        self.assertEqual({v["display"] for v in created["result"]["views"]}, {"lines"})
        self.assertEqual(created["result"]["scale_labels"], "ratio_colon")
        iso = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "general",
            "--orientation",
            "isometric",
            "--x",
            330,
            "--y",
            220,
            "--display",
            "shaded",
        )["data"]
        self.checks_pass(iso)
        self.assertEqual(iso["result"]["view"]["display"], "shaded")
        cut = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "projection",
            "--parent",
            "FRONT",
            "--x",
            110,
            "--y",
            40,
            "--plane",
            "RIGHT",
            "--edges",
            "area",
        )["data"]
        self.checks_pass(cut)
        self.assertEqual(cut["result"]["section"]["edges"], "area")
        for args, path in (
            (("--type", "general", "--x", 300, "--y", 40, "--edges", "area"), "edges"),
            (
                (
                    "--type",
                    "detail",
                    "--parent",
                    "FRONT",
                    "--x",
                    300,
                    "--y",
                    40,
                    "--center",
                    "edge:1",
                    "--radius",
                    30,
                    "--display",
                    "hidden",
                ),
                "display",
            ),
        ):
            with self.subTest(path=path):
                error = self.cli(
                    "drawing", "view", "add", "--model", "block", *args, "--dry-run", status=2
                )["error"]
                self.assertEqual((error["code"], error["details"]["path"]), ("E_VALIDATION", path))
        noted = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        self.checks_pass(noted)
        # The datum's own offset is left off; the block's own dimensions are shown.
        self.assertEqual(len(noted["result"]["annotated"]["datums_taken_off"]), 1)
        self.assertGreater(noted["result"]["annotated"]["shown"], 0)

    def test_a_title_block_filled_from_the_model(self):
        self.block()
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")
        # The template's views stay clear of the bottom right corner.
        preview = domain_preview(
            self.cli(
                "drawing",
                "title-block",
                "apply",
                "--model",
                "block",
                "--language",
                "zh",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["command"], "drawing title-block apply")
        self.assertEqual(preview["filled"]["title"], "BLOCK")
        self.assertEqual(preview["filled"]["scale"], "1:1")
        self.assertEqual(preview["size"], [180, 32])
        self.assertEqual(preview["at"], [235, 37])
        fields = self.request({"number": "BK-001", "drawn_by": "Claude"}, "title.json")
        made = self.gated(
            "drawing",
            "title-block",
            "apply",
            "--model",
            "block",
            "--language",
            "zh",
            "--request",
            fields,
        )["data"]
        self.checks_pass(made)
        self.assertIn(
            "projection_symbol_drawn", [c["check"] for c in made["verification"]["checks"]]
        )
        self.assertEqual(made["result"]["projection_symbol"]["projection"], "first_angle")
        cells = self.cli("model", "show", "--model", "block.drw")["data"]["tables"][-1]["cells"]
        self.assertEqual(cells[0][:2], ["名称", "BLOCK"])
        self.assertEqual(cells[2][:2], ["图号", "BK-001"])
        self.assertEqual(cells[3][:2], ["制图", "Claude"])
        # A second one in the same corner is refused, and so is a view in the way.
        again = self.cli(
            "drawing", "title-block", "apply", "--model", "block", "--dry-run", status=6
        )["error"]
        self.assertEqual(again["code"], "E_CONFLICT")
        self.assertIn("table", again["details"]["fix"])
        self.gated("drawing", "create", "--name", "other", "--of", "block", "--sheet", "a3")
        added = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "other",
            "--type",
            "general",
            "--x",
            330,
            "--y",
            20,
        )
        crowded = self.cli(
            "drawing", "title-block", "apply", "--model", "other", "--dry-run", status=6
        )["error"]
        # The native title-region diagnostic identifies views by their actual IDs.
        # New faithful fixture rows now include those IDs rather than only a name.
        self.assertEqual(crowded["details"]["views"], [str(added["data"]["result"]["view"]["id"])])

    def test_views_and_templates_checked(self):
        self.block()
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")
        for args, code, status in (
            (("--type", "projection", "--x", 10, "--y", 10), "E_VALIDATION", 2),
            (("--type", "general", "--parent", "V", "--x", 10, "--y", 10), "E_VALIDATION", 2),
            (("--type", "general", "--x", 999, "--y", 10), "E_VALIDATION", 2),
            (("--type", "projection", "--parent", "NOPE", "--x", 10, "--y", 10), "E_NOT_FOUND", 3),
            (("--type", "general", "--x", 10, "--y", 10, "--scale", 0), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    self.cli(
                        "drawing",
                        "view",
                        "add",
                        "--model",
                        "block",
                        *args,
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        self.assertEqual(
            self.cli(
                "drawing", "create", "--name", "other", "--of", "block", "--dry-run", status=2
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(
                "drawing",
                "create",
                "--name",
                "block",
                "--of",
                "block",
                "--sheet",
                "a4",
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.assertEqual(
            self.cli(
                "artifact",
                "export",
                "--model",
                "block.drw",
                "--output",
                "block.stp",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )


class ExplodedStates(AssemblyParts):
    """An exploded state as View > Explode makes one, and a drawing view of it: the assembly
    shown apart for a parts list and its balloons."""

    def gearbox(self):
        self.parts()
        self.assembly()
        for component in ("block", "pin"):
            self.gated(
                "assembly",
                "component",
                "add",
                "--model",
                "gearbox",
                "--component",
                component,
                "--request",
                self.request({"constraints": [{"type": "default"}]}, component + ".json"),
            )
        rows = self.cli("model", "show", "--model", "gearbox.asm")["data"]["components"]
        return {r["model"]: r["id"] for r in rows}

    def explode(self, body, *flags, status=0):
        return self.cli(
            "assembly",
            "explode",
            "apply",
            "--model",
            "gearbox",
            "--request",
            self.request(body, "apart.json"),
            *flags,
            status=status,
        )

    def test_components_moved_apart_and_drawn_so(self):
        ids = self.gearbox()
        body = {
            "units": "mm",
            "name": "APART",
            "moves": [{"components": ["pin"], "direction": [0, 0, 2], "distance": 50}],
        }
        preview = domain_preview(self.explode(body, "--dry-run")["data"]["preview"])
        self.assertEqual(
            preview["moves"],
            [{"components": [ids["pin.prt"]], "direction": [0.0, 0.0, 1.0], "distance": 50}],
        )
        self.assertIsNone(preview["replaces"])
        data = self.gated(
            "assembly",
            "explode",
            "apply",
            "--model",
            "gearbox",
            "--request",
            self.request(body, "apart.json"),
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [c["check"] for c in data["verification"]["checks"]],
            [
                "state_made",
                "existing_state_identity_preserved",
                "native_normal_placement_unchanged",
                "state_active",
                "placement_and_display_translations_consistent",
                "physical_geometry_unchanged",
                "other_explosion_states_preserved",
                "moves_as_requested",
                "one_state_of_that_name",
            ],
        )
        states = self.cli("model", "show", "--model", "gearbox.asm")["data"]["exploded_states"]
        self.assertEqual([(x["name"], x["active"]) for x in states][:1], [("APART", True)])
        # A state of that name again: refused unless it is to be made anew.
        self.assertEqual(self.explode(body, "--dry-run", status=6)["error"]["code"], "E_CONFLICT")
        again = body | {"replace": True, "moves": [body["moves"][0] | {"distance": 80}]}
        self.checks_pass(
            self.gated(
                "assembly",
                "explode",
                "apply",
                "--model",
                "gearbox",
                "--request",
                self.request(again, "apart.json"),
            )["data"]
        )
        # Drawn exploded, on a drawing of the assembly.
        self.gated("drawing", "create", "--name", "gearbox", "--of", "gearbox.asm", "--sheet", "a3")
        view = domain_preview(
            self.cli(
                "drawing",
                "view",
                "add",
                "--model",
                "gearbox",
                "--type",
                "general",
                "--x",
                200,
                "--y",
                150,
                "--exploded",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(view["exploded_state"]["name"], "APART")
        self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "gearbox",
            "--type",
            "general",
            "--x",
            200,
            "--y",
            150,
            "--exploded",
        )
        sent = [q for n, q in self.world.events if n == "drawing.add-view"][-1]
        self.assertTrue(sent["view"]["exploded"])

    def test_an_exploded_view_needs_something_moved_and_an_assembly(self):
        self.gearbox()
        self.gated("drawing", "create", "--name", "gearbox", "--of", "gearbox.asm", "--sheet", "a3")
        error = self.cli(
            "drawing",
            "view",
            "add",
            "--model",
            "gearbox",
            "--type",
            "general",
            "--x",
            200,
            "--y",
            150,
            "--exploded",
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["details"]["active"], "Default Explode")
        self.gated("drawing", "create", "--name", "blockdrw", "--of", "block.prt", "--sheet", "a3")
        self.cli(
            "drawing",
            "view",
            "add",
            "--model",
            "blockdrw",
            "--type",
            "general",
            "--x",
            200,
            "--y",
            150,
            "--exploded",
            "--dry-run",
            status=2,
        )
        self.cli(
            "drawing",
            "view",
            "add",
            "--model",
            "gearbox",
            "--type",
            "projection",
            "--parent",
            "x",
            "--x",
            200,
            "--y",
            150,
            "--exploded",
            "--dry-run",
            status=2,
        )

    def test_what_an_explode_request_cannot_be(self):
        self.gearbox()
        good = {
            "units": "mm",
            "name": "APART",
            "moves": [{"components": ["pin"], "direction": [0, 0, 1], "distance": 50}],
        }
        move = good["moves"][0]
        for body, code, status in (
            (good | {"moves": [move | {"direction": [0, 0, 0]}]}, "E_VALIDATION", 2),
            (good | {"moves": [move | {"distance": 0}]}, "E_VALIDATION", 2),
            (good | {"moves": [move | {"components": []}]}, "E_VALIDATION", 2),
            (good | {"moves": []}, "E_VALIDATION", 2),
            (good | {"name": "1APART"}, "E_VALIDATION", 2),
            (good | {"moves": [move | {"components": ["nope"]}]}, "E_NOT_FOUND", 3),
            (good | {"units": "in"}, "E_CONFLICT", 6),
            ({"units": "mm", "name": "APART"}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.explode(body, "--dry-run", status=status)["error"]["code"], code
                )


class DrawingScaleAndZeros(AssemblyParts):
    """A sheet's scale as a drafter writes it, and no dimension of 0 on the drawing."""

    def test_a_planned_scale_and_the_zeros_left_off(self):
        self.parts()
        preview = domain_preview(
            self.cli(
                "drawing",
                "create",
                "--name",
                "blockdrw",
                "--of",
                "block.prt",
                "--sheet",
                "a3",
                "--scale",
                "1:2",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["scale"], "1:2")
        made = self.gated(
            "drawing",
            "create",
            "--name",
            "blockdrw",
            "--of",
            "block.prt",
            "--sheet",
            "a3",
            "--scale",
            "1:2",
        )["data"]
        self.checks_pass(made)
        self.assertIn(
            "every_view_on_the_sheet", [c["check"] for c in made["verification"]["checks"]]
        )
        self.assertIn("views_apart", [c["check"] for c in made["verification"]["checks"]])
        sent = [q for n, q in self.world.events if n == "drawing.create"][-1]
        self.assertEqual(sent["scale"], 0.5)
        for bad in ("2", "1:0", "two:one"):
            with self.subTest(scale=bad):
                self.cli(
                    "drawing",
                    "create",
                    "--name",
                    "x",
                    "--of",
                    "block.prt",
                    "--sheet",
                    "a3",
                    "--scale",
                    bad,
                    "--dry-run",
                    status=2,
                )
        # A 0 offset on the block, a feature on its reference: taken off, and said so.
        block = self.world.models["block.prt"]
        block["dimensions"].append(
            dict(block["dimensions"][0]) | {"id": 900, "name": "d900", "value": 0.0}
        )
        annotated = self.gated("drawing", "dimension", "annotate", "--model", "blockdrw")["data"]
        zeros = next(
            o
            for o in annotated["verification"]["observations"]
            if o["observation"] == "zeros_taken_off"
        )
        self.assertEqual([z["name"] for z in zeros["dimensions"]], ["d900"])
        self.assertNotIn(
            "with_zero", [q for n, q in self.world.events if n == "drawing.annotate"][-1]
        )


class CommonNames(AssemblyParts):
    """The name a parts list describes a part by: Creo's common name."""

    def test_a_part_described_for_its_parts_list(self):
        self.parts()
        preview = domain_preview(
            self.cli(
                "model", "set-common-name", "--model", "block", "--name", "合页底座", "--dry-run"
            )["data"]["preview"]
        )
        self.assertEqual((preview["from"], preview["to"]), (None, "合页底座"))
        data = self.gated("model", "set-common-name", "--model", "block", "--name", "合页底座")[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(
            self.cli("model", "show", "--model", "block")["data"]["common_name"], "合页底座"
        )
        for args, status in (
            (("--model", "block", "--name", ""), 2),
            (("--model", "block", "--name", "two\nlines"), 2),
            (("--model", "block.drw", "--name", "x"), 2),
            (("--model", "nothing", "--name", "x"), 3),
        ):
            with self.subTest(args=args):
                self.cli("model", "set-common-name", *args, "--dry-run", status=status)
