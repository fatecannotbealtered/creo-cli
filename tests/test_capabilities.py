"""Every option a request schema or a flag declares, used successfully at least once -- against
the loopback substitute. The substitute does not model geometry closely enough to judge the
shapes; what it proves is that each option is accepted, checked, carried to the service as
declared and read back. docs/evidence/live-creo.json has Creo's own measurements of them."""

from __future__ import annotations

import math
from pathlib import Path

from tests.test_assemblies import PIN
from tests.test_commands import RECT, domain_preview
from tests.test_features import Built


class SketchOptions(Built):
    def sent(self, op):
        return [q for name, q in self.world.events if name == op][-1]

    def test_both_sides_and_symmetric(self):
        self.part()
        for side in ("two", "symmetric"):
            with self.subTest(side=side):
                body = RECT | {"name": "B_" + side.upper(), "side": side}
                preview = domain_preview(
                    self.cli(
                        "feature",
                        "extrude",
                        "--model",
                        "block",
                        "--request",
                        self.request(body),
                        "--dry-run",
                    )["data"]["preview"]
                )
                self.assertEqual(preview["feature"]["side"], side)
                data = self.gated(
                    "feature", "extrude", "--model", "block", "--request", self.request(body)
                )["data"]
                self.checks_pass(data)
                self.assertEqual(self.sent("feature.extrude")["side"], side)

    def test_a_new_body(self):
        self.part()
        body = RECT | {"body": "new"}
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(body),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["feature"]["body"], "new")
        self.checks_pass(
            self.gated("feature", "extrude", "--model", "block", "--request", self.request(body))[
                "data"
            ]
        )
        self.assertEqual(self.sent("feature.extrude")["body"], "new")

    def test_revolved_cut_and_partial_turn_are_outside_bounded_proof(self):
        from tests.test_features import SHAFT

        self.part("shaft.prt")
        self.gated("feature", "revolve", "--model", "shaft", "--request", self.request(SHAFT))
        groove = SHAFT | {
            "name": "GROOVE",
            "material": "remove",
            "sketch": SHAFT["sketch"]
            | {"profile": {"type": "polygon", "points": [[8, 8], [10, 8], [10, 12], [8, 12]]}},
        }
        key = SHAFT | {
            "name": "KEY",
            "angle": 90,
            "side": "symmetric",
            "sketch": SHAFT["sketch"]
            | {"profile": {"type": "polygon", "points": [[6, 30], [8, 30], [8, 34], [6, 34]]}},
        }
        for request in (groove, key):
            error = self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(request),
                "--dry-run",
                status=2,
            )["error"]
            self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertEqual(self.world.ops().count("feature.revolve"), 1)

    def test_orientation_of_the_sketch(self):
        self.part()
        body = RECT | {"sketch": RECT["sketch"] | {"orient_ref": "TOP", "orient": "up"}}
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(body),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(
            (preview["sketch"]["orient_ref"], preview["sketch"]["orient"]), ("TOP", "up")
        )
        self.checks_pass(
            self.gated("feature", "extrude", "--model", "block", "--request", self.request(body))[
                "data"
            ]
        )
        self.assertEqual(self.sent("feature.extrude")["sketch"]["orient"], "up")

    def test_a_plane_of_ones_own_needs_references(self):
        self.block()
        self.gated(
            "feature",
            "datum-plane",
            "--model",
            "block",
            "--request",
            self.request(
                {"units": "mm", "name": "MID", "offset": {"from": "RIGHT", "distance": 20}}
            ),
        )
        on_mid = {"plane": "MID", "orient_ref": "TOP", "orient": "up"}
        slot = RECT | {
            "name": "SLOT",
            "material": "remove",
            "sketch": on_mid | {"profile": {"type": "rectangle", "width": 4, "height": 2}},
        }
        refused = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(slot),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(refused["details"]["path"], "request.sketch.references")
        slot["sketch"] = slot["sketch"] | {"references": ["TOP", "FRONT"]}
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(slot),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["sketch"]["references"], ["TOP", "FRONT"])
        self.checks_pass(
            self.gated("feature", "extrude", "--model", "block", "--request", self.request(slot))[
                "data"
            ]
        )
        self.assertEqual(self.sent("feature.extrude")["sketch"]["references"], ["TOP", "FRONT"])
        # A circle Java draws needs no references: without the library, it is Java's.
        self.world.native = False
        circle = RECT | {
            "name": "DOT",
            "sketch": on_mid | {"profile": {"type": "circle", "diameter": 2}},
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(circle),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(
            (preview["sketch"]["drawn_by"], preview["sketch"]["references"]), ("java", None)
        )

    def test_revolve_about_an_axis_of_the_part(self):
        self.part("shaft.prt")
        self.gated(
            "feature",
            "datum-axis",
            "--model",
            "shaft",
            "--request",
            self.request({"name": "ZAXIS", "through": ["RIGHT", "TOP"]}),
        )
        ring = {
            "units": "mm",
            "name": "RING",
            "angle": 360,
            "axis": "ZAXIS",
            "sketch": {
                "plane": "RIGHT",
                "orient_ref": "TOP",
                "orient": "right",
                "profile": {"type": "polygon", "points": [[5, 0], [12, 0], [12, 30], [5, 30]]},
            },
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(ring),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertIn("external", preview["axis"])
        self.assertIsNone(preview["expected_volume_change"])
        data = self.gated(
            "feature", "revolve", "--model", "shaft", "--request", self.request(ring)
        )["data"]
        self.checks_pass(data)
        self.assertNotIn("expected_change", data["result"]["volume"])
        self.assertEqual(self.sent("feature.revolve")["axis"], "ZAXIS")
        self.block()
        edge = self.edges([1, 0, 0])[0]["ref"]
        on_front = ring["sketch"] | {"plane": "FRONT", "orient_ref": "RIGHT", "orient": "right"}
        about_an_edge = ring | {"name": "HOOP", "axis": edge, "sketch": on_front}
        self.assertEqual(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "block",
                "--request",
                self.request(about_an_edge),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_UNSUPPORTED",
        )
        about_a_face = about_an_edge | {"name": "NOPE", "axis": self.top()["ref"]}
        self.assertEqual(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "block",
                "--request",
                self.request(about_a_face),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        missing = ring | {"axis": "NOWHERE", "name": "RING2"}
        self.assertEqual(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(missing),
                "--dry-run",
                status=3,
            )["error"]["code"],
            "E_NOT_FOUND",
        )


class DatumOptions(Built):
    def axis(self):
        return self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "ZAXIS", "through": ["RIGHT", "TOP"]}, "axis.json"),
        )["data"]

    def test_angular_plane_is_refused_before_dispatch(self):
        self.block()
        self.axis()
        body = {
            "units": "mm",
            "name": "TILT",
            "angle": {"through": "ZAXIS", "from": "TOP", "degrees": 30},
        }
        self.assertEqual(
            self.cli(
                "feature",
                "datum-plane",
                "--model",
                "block",
                "--request",
                self.request(body),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_UNSUPPORTED",
        )
        self.assertNotIn("feature.datum-plane", self.world.ops())
        edge = self.edges()[0]["ref"]
        offset_from_an_edge = {"units": "mm", "offset": {"from": edge, "distance": 1}}
        self.assertEqual(
            self.cli(
                "feature",
                "datum-plane",
                "--model",
                "block",
                "--request",
                self.request(offset_from_an_edge),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_an_axis_along_an_edge_or_through_a_face(self):
        self.block()
        edge = self.edges([1, 0, 0])[0]["ref"]
        along = self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "EDGE_AXIS", "through": [edge]}),
        )["data"]
        self.checks_pass(along)
        face = self.top()["ref"]
        through = self.cli(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "FACE_AXIS", "through": [face]}),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(through["code"], "E_UNSUPPORTED")
        sent = [q for name, q in self.world.events if name == "feature.datum-axis"]
        self.assertEqual([q["through"] for q in sent], [[edge]])


class PatternAndShellOptions(Built):
    def hole(self):
        top = self.top()["ref"]
        self.gated(
            "feature",
            "hole",
            "--model",
            "block",
            "--request",
            self.request(
                {
                    "units": "mm",
                    "name": "H1",
                    "diameter": 2,
                    "depth": "through_all",
                    "placement": {
                        "surface": top,
                        "offsets": [
                            {"from": "RIGHT", "distance": 10},
                            {"from": "TOP", "distance": 0},
                        ],
                    },
                },
                "hole.json",
            ),
        )

    def test_about_an_axis_and_backwards_along_a_direction(self):
        self.block()
        self.hole()
        self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "ZAXIS", "through": ["RIGHT", "TOP"]}, "axis.json"),
        )
        circle = {
            "units": "mm",
            "name": "RING",
            "feature": "H1",
            "axis": {"about": "ZAXIS", "angle": -90, "count": 4},
        }
        data = self.gated(
            "feature", "pattern", "--model", "block", "--request", self.request(circle)
        )["data"]
        self.checks_pass(data)
        self.assertEqual(len(data["result"]["members"]), 4)
        back = {
            "units": "mm",
            "name": "BACK",
            "feature": "H1",
            "direction": {"along": "RIGHT", "spacing": -8, "count": 2},
        }
        self.checks_pass(
            self.gated("feature", "pattern", "--model", "block", "--request", self.request(back))[
                "data"
            ]
        )
        sent = [q for name, q in self.world.events if name == "feature.pattern"]
        self.assertEqual(sent[-1]["direction"]["spacing"], -8)
        self.assertEqual(sent[-2]["axis"]["angle"], -90)

    def test_a_closed_shell_is_refused_by_bounded_profile(self):
        self.block()
        self.cli(
            "feature",
            "shell",
            "--model",
            "block",
            "--request",
            self.request({"units": "mm", "name": "CLOSED", "thickness": 1}),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.shell", self.world.ops())

    def test_a_shell_grown_outwards_is_refused_by_bounded_profile(self):
        self.block()
        body = {
            "units": "mm",
            "name": "SKIN",
            "thickness": 1,
            "side": "outside",
            "remove": [self.top()["ref"]],
        }
        self.cli(
            "feature",
            "shell",
            "--model",
            "block",
            "--request",
            self.request(body),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.shell", self.world.ops())


class ResultSemantics(Built):
    def test_what_a_confirmed_feature_reports(self):
        self.part()
        data = self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(RECT)
        )["data"]
        verification = data["verification"]
        observed = {o["observation"]: o for o in verification["observations"]}
        self.assertEqual(observed["volume"]["expected_change"], 8000.0)
        self.assertTrue(observed["volume"]["matches_request"])
        self.assertEqual(observed["sketch_engine"]["engine"], "native")
        self.assertEqual([f["name"] for f in observed["new_features"]["features"]][-1], "BLOCK")
        self.assertTrue(verification["not_checked"])
        self.assertEqual(data["_untrusted"], ["result", "verification"])

    def test_an_estimate_that_does_not_match_is_not_a_failure(self):
        # A cut into an empty part removes nothing: the estimate says otherwise, and that is
        # information, not an error.
        self.part()
        cut = RECT | {"name": "AIR", "material": "remove"}
        data = self.gated("feature", "extrude", "--model", "block", "--request", self.request(cut))[
            "data"
        ]
        self.assertEqual(data["status"], "completed")
        self.assertFalse(data["result"]["volume"]["matches_request"])
        self.assertLess(data["result"]["volume"]["expected_change"], 0)

    def test_a_part_without_density_has_no_mass(self):
        self.block()
        mass = self.cli("model", "show", "--model", "block")["data"]["mass_properties"]
        self.assertEqual((mass["mass"], mass["density"]), (None, None))
        self.assertEqual(mass["volume"], 8000.0)

    def test_units_from_creo_default_template_are_read_back(self):
        data = self.gated("part", "create", "--name", "legacy", "--units", "session_default")[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(data["result"]["units"]["length"], "in")
        observed = [
            o
            for o in data["verification"]["observations"]
            if o["observation"] == "created_model_read_back"
        ]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["model"]["units"]["length"], "in")
        self.assertEqual(observed[0]["model"]["units"], data["result"]["units"])


class PicturesAndFiles(Built):
    def test_picture_requires_workspace_output_confirmation_and_no_overwrite(self):
        self.block()
        shot = self.gated(
            "artifact",
            "render",
            "--model",
            "block",
            "--output",
            "block.jpg",
            "--view",
            "top",
            "--width",
            64,
            "--height",
            64,
        )["data"]
        self.checks_pass(shot)
        self.assertEqual(Path(shot["result"]["file"]).parent, self.ws)
        self.assertEqual(shot["result"]["view"], "top")
        self.assertEqual(
            self.cli(
                "artifact",
                "render",
                "--model",
                "block",
                "--output",
                "block.jpg",
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        away = {k: v for k, v in self.env.items() if k != "CREO_CLI_WORKSPACE"}
        self.assertEqual(
            self.cli(
                "artifact",
                "render",
                "--model",
                "block",
                "--output",
                "other.jpg",
                "--dry-run",
                env=away,
                status=4,
            )["error"]["code"],
            "E_CONFIG",
        )
        self.assertEqual(
            self.cli(
                "artifact",
                "render",
                "--model",
                "block",
                "--output",
                "other.jpg",
                "--width",
                10,
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_every_extension_names_its_format(self):
        self.block()
        (self.ws / "out").mkdir()
        for suffix, fmt in ((".step", "step"), (".iges", "iges"), (".stl", "stl")):
            with self.subTest(suffix=suffix):
                data = self.gated(
                    "artifact", "export", "--model", "block", "--output", f"out/block{suffix}"
                )["data"]
                self.checks_pass(data)
                self.assertEqual(data["result"]["format"], fmt)
        self.assertEqual(
            self.cli(
                "artifact",
                "export",
                "--model",
                "block",
                "--output",
                "out/block.dwg",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_a_model_from_elsewhere_can_be_exported_but_not_used(self):
        outside = self.root / "vault"
        outside.mkdir()
        self.world.part("bought.prt", origin=str(outside / "bought.prt.1"))
        (self.ws / "out").mkdir()
        exported = self.gated(
            "artifact", "export", "--model", "bought", "--output", "out/bought.stp"
        )["data"]
        self.checks_pass(exported)
        self.assertEqual(
            self.cli(
                "drawing",
                "create",
                "--name",
                "bought",
                "--of",
                "bought",
                "--sheet",
                "a4",
                "--dry-run",
                status=4,
            )["error"]["code"],
            "E_FORBIDDEN",
        )


class AssemblyOptions(Built):
    def setUp(self):
        super().setUp()
        self.block()
        self.gated(
            "feature",
            "hole",
            "--model",
            "block",
            "--request",
            self.request(
                {
                    "units": "mm",
                    "name": "BORE",
                    "diameter": 10,
                    "depth": "through_all",
                    "placement": {
                        "surface": self.top()["ref"],
                        "offsets": [
                            {"from": "RIGHT", "distance": 0},
                            {"from": "TOP", "distance": 0},
                        ],
                    },
                },
                "bore.json",
            ),
        )
        self.part("pin.prt")
        self.gated(
            "feature", "extrude", "--model", "pin", "--request", self.request(PIN, "pin.json")
        )
        self.gated(
            "feature",
            "datum-axis",
            "--model",
            "pin",
            "--request",
            self.request({"name": "PIN_AXIS", "through": ["RIGHT", "TOP"]}, "pin_axis.json"),
        )
        self.gated("assembly", "create", "--name", "rig", "--units", "mmns")
        self.base = self.add(
            "block",
            {
                "constraints": [
                    {
                        "type": "csys",
                        "assembly_ref": "ASM_DEF_CSYS",
                        "component_ref": "PRT_CSYS_DEF",
                    }
                ]
            },
        )

    def add(self, component, body, status=0):
        return self.gated(
            "assembly",
            "component",
            "add",
            "--model",
            "rig",
            "--component",
            component,
            "--request",
            self.request(body, f"add_{component}.json"),
            status=status,
        )

    def test_insert_by_a_component_id_with_an_offset(self):
        self.checks_pass(self.base["data"])
        self.assertFalse(self.base["data"]["result"]["component"]["underconstrained"])
        placed = self.base["data"]["result"]["component"]["id"]
        top = self.top()["ref"]
        body = {
            "units": "mm",
            "constraints": [
                {"type": "insert", "assembly_ref": f"A_1@{placed}", "component_ref": "PIN_AXIS"},
                {
                    "type": "mate",
                    "assembly_ref": f"{top}@{placed}",
                    "component_ref": "FRONT",
                    "offset": 2,
                },
                {"type": "align", "assembly_ref": "ASM_RIGHT", "component_ref": "RIGHT"},
            ],
        }
        data = self.add("pin", body)["data"]
        self.checks_pass(data)
        self.assertEqual(
            [c["type"] for c in data["result"]["component"]["constraints"]],
            ["insert", "mate", "align"],
        )
        sent = [q for name, q in self.world.events if name == "assembly.add"][-1]
        self.assertEqual(sent["constraints"][1]["offset"], 2)

    def test_fixed_where_it_lands(self):
        data = self.add("pin", {"constraints": [{"type": "fix"}]})["data"]
        self.checks_pass(data)
        self.assertEqual(data["result"]["component"]["constraints"][0]["type"], "fix")

    def test_a_coordinate_system_is_a_reference(self):
        systems = self.cli("geometry", "list", "--model", "pin", "--kind", "csys")["data"]["items"]
        self.assertEqual([s["ref"] for s in systems], ["PRT_CSYS_DEF"])
        self.assertEqual(systems[0]["z_axis"], [0, 0, 1])
        asm = self.cli("geometry", "list", "--model", "rig.asm", "--kind", "csys")["data"]["items"]
        self.assertEqual([s["ref"] for s in asm], ["ASM_DEF_CSYS"])

    def test_saving_the_assembly(self):
        saved = self.gated("model", "save", "--model", "rig.asm")["data"]
        self.checks_pass(saved)
        self.assertTrue(Path(saved["result"]["file"]).name.startswith("rig.asm."))

    def test_components_from_elsewhere_are_refused(self):
        outside = self.root / "vault"
        outside.mkdir()
        self.world.part("bought.prt", origin=str(outside / "bought.prt.1"))
        refused = self.cli(
            "assembly",
            "component",
            "add",
            "--model",
            "rig",
            "--component",
            "bought",
            "--request",
            self.request({"constraints": [{"type": "default"}]}, "bought.json"),
            "--dry-run",
            status=4,
        )["error"]
        self.assertEqual(
            (refused["code"], refused["details"]["model"]), ("E_FORBIDDEN", "bought.prt")
        )
        # An assembly that already uses one is not saved: Creo would store it back out there.
        self.world.models["rig.asm"]["components"].append(
            {"id": 999, "model": "bought.prt", "status": "FEAT_ACTIVE", "placed": True}
        )
        self.assertEqual(
            self.cli("model", "save", "--model", "rig.asm", "--dry-run", status=4)["error"]["code"],
            "E_FORBIDDEN",
        )


class AssemblyTemplate(Built):
    def test_an_assembly_from_a_template_of_ones_own(self):
        (self.ws / "company_asm.asm.1").write_bytes(b"template")
        data = self.gated(
            "assembly", "create", "--name", "frame", "--template", "company_asm.asm.1"
        )["data"]
        self.checks_pass(data)
        self.assertTrue(data["result"]["template"].endswith("company_asm.asm.1"))
        self.assertEqual(data["result"]["datum_planes"], ["ASM_RIGHT", "ASM_TOP", "ASM_FRONT"])


class DrawingOptions(Built):
    def test_a_template_of_ones_own(self):
        self.block()
        (self.ws / "mine.drw").write_bytes(b"SUBSTITUTE DRAWING TEMPLATE")
        data = self.gated(
            "drawing", "create", "--name", "block", "--of", "block", "--template", "mine.drw"
        )["data"]
        self.checks_pass(data)
        # A template of one's own keeps its lettering.
        self.assertNotIn(
            "lettered_in_creo_font", [c["check"] for c in data["verification"]["checks"]]
        )
        self.assertTrue(
            [q for name, q in self.world.events if name == "drawing.create"][-1][
                "template"
            ].endswith("mine.drw")
        )
        (self.ws / "sub").mkdir()
        (self.ws / "sub" / "far.drw").write_bytes(b"x")
        (self.ws / "notes.txt").write_bytes(b"x")
        for args, code, status in (
            (("--template", "sub/far.drw"), "E_VALIDATION", 2),
            (("--template", "notes.txt"), "E_VALIDATION", 2),
            (("--template", "mine.drw", "--sheet", "a3"), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    self.cli(
                        "drawing",
                        "create",
                        "--name",
                        "other",
                        "--of",
                        "block",
                        *args,
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )

    def test_a_standard_sheet_letters_in_creo_own_font(self):
        # Creo writes a view's scale label in the session's language; the standard sheets'
        # ISONorm has no Chinese glyphs, Creo's own font is localized with the session.
        self.block()
        data = self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")[
            "data"
        ]
        lettering = next(
            c for c in data["verification"]["checks"] if c["check"] == "lettered_in_creo_font"
        )
        self.assertEqual((lettering["passed"], lettering["lettering"]), (True, "font"))

    def test_views_laid_out_by_the_projection(self):
        # Creo's ISO sheets are first angle, as ISO E and GB drawings are: the view from above
        # lies below the front, the view from the left on its right. Third angle the other way.
        self.block()
        data = self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")[
            "data"
        ]
        self.checks_pass(data)
        result = data["result"]
        self.assertEqual(result["projection"], "first_angle")
        self.assertEqual(result["views_laid_out"], ["FRONT", "LEFT", "TOP", "ISOMETRIC"])
        views = {v["name"]: v["outline"] for v in result["views"]}
        self.assertLess(views["TOP"][1][1], views["FRONT"][0][1])
        self.assertGreater(views["LEFT"][0][0], views["FRONT"][1][0])
        dry = domain_preview(
            self.cli(
                "drawing",
                "create",
                "--name",
                "third",
                "--of",
                "block",
                "--sheet",
                "a3",
                "--projection",
                "third",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(dry["projection"], "third_angle")
        data = self.gated(
            "drawing",
            "create",
            "--name",
            "third",
            "--of",
            "block",
            "--sheet",
            "a3",
            "--projection",
            "third",
        )["data"]
        self.checks_pass(data)
        self.assertIn("projection_as_asked", [c["check"] for c in data["verification"]["checks"]])
        self.assertEqual(data["result"]["views_laid_out"], ["FRONT", "RIGHT", "TOP", "ISOMETRIC"])
        views = {v["name"]: v["outline"] for v in data["result"]["views"]}
        self.assertGreater(views["TOP"][0][1], views["FRONT"][1][1])
        empty = self.gated(
            "drawing",
            "create",
            "--name",
            "bare",
            "--of",
            "block",
            "--sheet",
            "c",
            "--views",
            "none",
        )["data"]
        self.checks_pass(empty)
        self.assertEqual(
            (empty["result"]["views"], empty["result"]["projection"]), ([], "third_angle")
        )

    def test_the_dimensions_are_read_back_from_the_drawing(self):
        self.block()
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")
        data = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        shown = next(c for c in data["verification"]["checks"] if c["check"] == "dimensions_shown")
        self.assertEqual(shown["shown"], 3)
        self.assertEqual(
            self.cli("model", "show", "--model", "block.drw")["data"]["dimensions_shown"], 3
        )
        # Annotating again shows nothing new and is still sound.
        self.checks_pass(self.gated("drawing", "dimension", "annotate", "--model", "block")["data"])


class DrawnBlock(Built):
    """The block with a hole, drawn on A3 -- what the drawing tests start from."""

    def setUp(self):
        super().setUp()
        self.block()
        self.gated(
            "feature",
            "hole",
            "--model",
            "block",
            "--request",
            self.request(
                {
                    "units": "mm",
                    "name": "H1",
                    "diameter": 4,
                    "depth": "through_all",
                    "placement": {
                        "surface": self.top()["ref"],
                        "offsets": [
                            {"from": "RIGHT", "distance": 10},
                            {"from": "TOP", "distance": 3},
                        ],
                    },
                },
                "h1.json",
            ),
        )
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")

    def shown(self):
        return self.cli("model", "show", "--model", "block.drw")["data"]


class DrawingDetailing(DrawnBlock):
    """An engineer's drawing: the dimensions chosen, the duplicates taken off, notes added."""

    def test_a_patterned_hole_is_counted(self):
        # A drafter writes how many holes there are before their size: 3X followed by the
        # diameter, read back from the drawing.
        row = {"along": "RIGHT", "spacing": -10, "count": 3}
        self.gated(
            "feature",
            "pattern",
            "--model",
            "block",
            "--request",
            self.request(
                {"units": "mm", "name": "ROW", "feature": "H1", "direction": row}, "p.json"
            ),
        )
        data = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        self.checks_pass(data)
        counted = data["result"]["annotated"]["counts_prefixed"]
        self.assertEqual([(c["feature"], c["prefix"]) for c in counted], [("H1", "3X")])
        self.assertIn("counts_read_back", [c["check"] for c in data["verification"]["checks"]])
        shown = {r["name"]: r for r in self.shown()["dimensions"]}
        self.assertEqual(shown[counted[0]["name"]]["prefix"], "3X")

    def test_a_chamfer_is_called_out_by_its_angle(self):
        edge = next(
            e
            for e in self.cli("geometry", "list", "--model", "block", "--kind", "edge")["data"][
                "items"
            ]
            if e.get("type") == "line"
        )
        chamfer = {"units": "mm", "name": "EDGE", "distance": 1, "edges": [edge["ref"]]}
        made = self.gated(
            "feature", "chamfer", "--model", "block", "--request", self.request(chamfer, "c.json")
        )["data"]
        self.assertEqual(made["result"]["scheme"], "45_x_d")
        data = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        called = data["result"]["annotated"]["chamfers_called_out"]
        self.assertEqual([(c["feature"], c["style"]) for c in called], [("EDGE", "d_x_45")])

    def test_a_diameter_moved_into_sight_is_read_back(self):
        # A diameter on a circle its view cannot see goes to a view that sees the cylinder;
        # the drawing read back afterwards must show it there.
        annotate = self.world.drawing_annotate

        def moved(q, lie=False):
            out = annotate(q)
            row = self.world.models["block.drw"]["shown_dims"][0]
            to = "TOP"
            if not lie:
                row["view"] = to
            out["annotated"]["moved_into_sight"] = [
                {"name": row["name"], "id": row["id"], "from": "FRONT", "to": to}
            ]
            return out

        self.world.drawing_annotate = moved
        data = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        self.checks_pass(data)
        self.assertIn(
            "moved_into_sight_read_back", [c["check"] for c in data["verification"]["checks"]]
        )
        self.world.drawing_annotate = lambda q: moved(q, lie=True)
        error = self.gated("drawing", "dimension", "annotate", "--model", "block", status=1)[
            "error"
        ]
        self.assertEqual(
            [c["check"] for c in error["details"]["failed_checks"]], ["moved_into_sight_read_back"]
        )

    def test_a_dimension_left_off_the_sheet_is_caught(self):
        # Creo's spacing can fling a dimension past the border; one still off the sheet after
        # annotate fails the write's verification instead of passing unseen.
        annotate = self.world.drawing_annotate

        def flung(q):
            out = annotate(q)
            self.world.models["block.drw"]["shown_dims"][-1]["at"] = [9999.0, 150.0]
            return out

        self.world.drawing_annotate = flung
        error = self.gated("drawing", "dimension", "annotate", "--model", "block", status=1)[
            "error"
        ]
        self.assertEqual(
            [c["check"] for c in error["details"]["failed_checks"]], ["dimensions_on_the_sheet"]
        )

    def test_only_the_features_asked_for(self):
        data = self.gated(
            "drawing", "dimension", "annotate", "--model", "block", "--feature", "H1"
        )["data"]
        self.checks_pass(data)
        rows = self.shown()["dimensions"]
        self.assertTrue(rows)
        self.assertEqual({r["feature"]["name"] for r in rows}, {"H1"})
        self.assertTrue(data["result"]["annotated"]["taken_off"])
        # Creo does not show an erased dimension again: BLOCK's stay off this drawing.
        again = self.gated("drawing", "dimension", "annotate", "--model", "block")["data"]
        self.checks_pass(again)
        self.assertEqual({r["feature"]["name"] for r in self.shown()["dimensions"]}, {"H1"})
        self.assertEqual(
            self.cli(
                "drawing",
                "dimension",
                "annotate",
                "--model",
                "block",
                "--feature",
                "NOPE",
                "--dry-run",
                status=3,
            )["error"]["code"],
            "E_NOT_FOUND",
        )
        self.assertEqual(
            self.cli(
                "drawing",
                "dimension",
                "annotate",
                "--model",
                "block",
                "--feature",
                "H1,h1",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_taking_dimensions_off(self):
        self.gated("drawing", "dimension", "annotate", "--model", "block")
        rows = self.shown()["dimensions"]
        doomed = next(r for r in rows if r["feature"]["name"] == "BLOCK")
        preview = domain_preview(
            self.cli(
                "drawing",
                "dimension",
                "hide",
                "--model",
                "block",
                "--dimension",
                doomed["name"],
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual([d["name"] for d in preview["takes_off"]], [doomed["name"]])
        data = self.gated(
            "drawing",
            "dimension",
            "hide",
            "--model",
            "block",
            "--dimension",
            f"{doomed['name']}@block.prt",
        )["data"]
        self.checks_pass(data)
        after = self.shown()["dimensions"]
        self.assertEqual(len(after), len(rows) - 1)
        self.assertNotIn(doomed["name"], [r["name"] for r in after])
        for flag, code, status in (
            ("d999", "E_NOT_FOUND", 3),
            (doomed["name"], "E_NOT_FOUND", 3),
            ("1abc", "E_VALIDATION", 2),
            ("d1,d1", "E_VALIDATION", 2),
        ):
            with self.subTest(flag=flag):
                self.assertEqual(
                    self.cli(
                        "drawing",
                        "dimension",
                        "hide",
                        "--model",
                        "block",
                        "--dimension",
                        flag,
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )

    def test_a_note_on_the_sheet(self):
        data = self.gated(
            "drawing",
            "note",
            "add",
            "--model",
            "block",
            "--text",
            "4X Ø7\n未注圆角 R4",
            "--x",
            40,
            "--y",
            30,
        )["data"]
        self.checks_pass(data)
        notes = self.shown()["notes"]
        self.assertEqual([n["text"] for n in notes], ["4X Ø7\n未注圆角 R4"])
        self.assertEqual(notes[0]["at"], [40.0, 30.0])
        for args, code in (
            (("--text", "far", "--x", 999, "--y", 30), "E_VALIDATION"),
            (("--text", "   ", "--x", 40, "--y", 30), "E_VALIDATION"),
            (("--text", "bell\x07", "--x", 40, "--y", 30), "E_VALIDATION"),
            (("--text", "x" * 501, "--x", 40, "--y", 30), "E_VALIDATION"),
        ):
            with self.subTest(args=args[:2]):
                self.assertEqual(
                    self.cli(
                        "drawing", "note", "add", "--model", "block", *args, "--dry-run", status=2
                    )["error"]["code"],
                    code,
                )


class DrawingFinishing(DrawnBlock):
    """The rest of a person's detailing: notes edited and moved, dimensions moved, a reference
    dimension, a title block, a surface finish symbol, and taking off what the drawing owns."""

    def drawing(self):
        return self.world.models["block.drw"]

    def refused(self, *args, status):
        return self.cli(*args, "--dry-run", status=status)["error"]

    def test_a_note_edited_and_moved(self):
        self.gated(
            "drawing", "note", "add", "--model", "block", "--text", "4X M6", "--x", 40, "--y", 30
        )
        note = self.shown()["notes"][0]
        data = self.gated(
            "drawing",
            "note",
            "edit",
            "--model",
            "block",
            "--note",
            note["id"],
            "--text",
            "4X M6 THRU",
        )["data"]
        self.checks_pass(data)
        self.assertEqual(self.shown()["notes"][0]["text"], "4X M6 THRU")
        preview = domain_preview(
            self.cli(
                "drawing",
                "note",
                "edit",
                "--model",
                "block",
                "--note",
                note["id"],
                "--x",
                60,
                "--y",
                25,
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["text"], preview["at"]), ("4X M6 THRU", [60, 25]))
        data = self.gated(
            "drawing",
            "note",
            "edit",
            "--model",
            "block",
            "--note",
            note["id"],
            "--text",
            "4X M6\\n深 12",
            "--x",
            60,
            "--y",
            25,
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [(n["text"], n["at"]) for n in self.shown()["notes"]], [("4X M6\n深 12", [60.0, 25.0])]
        )
        sent = [q for name, q in self.world.events if name == "drawing.edit-note"][-1]
        self.assertEqual(
            sent,
            {"model": "block.drw", "note": int(note["id"]), "text": "4X M6\n深 12", "at": [60, 25]},
        )
        # A note attached to something on the drawing keeps its place.
        self.drawing()["notes"].append({"id": 5, "text": "on a leader", "at": None})
        base = ("drawing", "note", "edit", "--model", "block")
        for args, code, status in (
            (("--note", note["id"]), "E_VALIDATION", 2),
            (("--note", note["id"], "--x", 60), "E_VALIDATION", 2),
            (("--note", "x1", "--text", "a"), "E_VALIDATION", 2),
            (("--note", "77", "--text", "a"), "E_NOT_FOUND", 3),
            (("--note", note["id"], "--x", 999, "--y", 30), "E_VALIDATION", 2),
            (("--note", note["id"], "--text", "bell\x07"), "E_VALIDATION", 2),
            (("--note", "5", "--x", 60, "--y", 30), "E_CONFLICT", 6),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)

    def test_dimensions_moved_off_each_other(self):
        self.gated("drawing", "dimension", "annotate", "--model", "block")
        target = self.shown()["dimensions"][0]
        preview = domain_preview(
            self.cli(
                "drawing",
                "dimension",
                "move",
                "--model",
                "block",
                "--dimension",
                target["name"],
                "--x",
                120,
                "--y",
                40,
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["dimension"]["name"], preview["to"]), (target["name"], [120, 40]))
        data = self.gated(
            "drawing",
            "dimension",
            "move",
            "--model",
            "block",
            "--dimension",
            f"{target['name']}@block.prt",
            "--x",
            120,
            "--y",
            40,
        )["data"]
        self.checks_pass(data)
        moved = next(d for d in self.shown()["dimensions"] if d["name"] == target["name"])
        self.assertEqual((moved["at"], moved["value"]), ([120.0, 40.0], target["value"]))
        sent = [q for name, q in self.world.events if name == "drawing.move-dimension"][-1]
        self.assertEqual(sent["dimension"], f"{target['name']}@block.prt")
        base = ("drawing", "dimension", "move", "--model", "block")
        for args, code, status in (
            (("--dimension", "d999", "--x", 1, "--y", 1), "E_NOT_FOUND", 3),
            (("--dimension", target["name"], "--x", 999, "--y", 1), "E_VALIDATION", 2),
            (("--dimension", "1abc", "--x", 1, "--y", 1), "E_VALIDATION", 2),
            (("--dimension", target["name"], "--x", 1), "E_USAGE", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)

    def test_a_reference_dimension_for_the_thickness(self):
        top, bottom = (e["ref"] for e in self.edges([1, 0, 0])[:2])
        view = self.shown()["views"][0]["name"]
        args = ("--model", "block", "--view", view, "--from", top, "--to", bottom)
        vertical = ("--orientation", "vertical", "--x", 170, "--y", 232)
        preview = domain_preview(
            self.cli("drawing", "dimension", "add", *args, *vertical, "--dry-run")["data"][
                "preview"
            ]
        )
        self.assertEqual(preview["parallel_edges_apart"], 10)
        self.assertEqual(preview["orientation"], "vertical")
        data = self.gated("drawing", "dimension", "add", *args, *vertical)["data"]
        self.checks_pass(data)
        made = data["result"]["dimension"]
        self.assertEqual((made["name"], made["reference"], made["value"]), ("rdd0", True, 10))
        sent = [q for name, q in self.world.events if name == "drawing.add-dimension"][-1]
        self.assertEqual(sent["orientation"], "vertical")
        # Slanted, square to the edges, is the default.
        preview = domain_preview(
            self.cli("drawing", "dimension", "add", *args, "--x", 170, "--y", 232, "--dry-run")[
                "data"
            ]["preview"]
        )
        self.assertEqual(preview["orientation"], "slanted")
        # It moves like any other, and is taken off with remove, not hide-dimension.
        moved = self.gated(
            "drawing",
            "dimension",
            "move",
            "--model",
            "block",
            "--dimension",
            "rdd0",
            "--x",
            180,
            "--y",
            240,
        )["data"]
        self.checks_pass(moved)
        hide = self.refused(
            "drawing", "dimension", "hide", "--model", "block", "--dimension", "rdd0", status=6
        )
        self.assertEqual(hide["code"], "E_CONFLICT")
        self.assertIn("drawing item remove", hide["details"]["fix"])
        self.checks_pass(
            self.gated("drawing", "item", "remove", "--model", "block", "--item", "dimension:rdd0")[
                "data"
            ]
        )
        self.assertNotIn("rdd0", [d["name"] for d in self.shown()["dimensions"]])
        base = ("drawing", "dimension", "add", "--model", "block", "--x", 170, "--y", 232)
        for extra, code, status in (
            (("--view", view, "--from", top, "--to", top), "E_VALIDATION", 2),
            (("--view", view, "--from", "surface:1", "--to", top), "E_VALIDATION", 2),
            (("--view", "NOPE", "--from", top, "--to", bottom), "E_NOT_FOUND", 3),
            (("--view", view, "--from", "edge:9999", "--to", bottom), "E_NOT_FOUND", 3),
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.refused(*base, *extra, status=status)["code"], code)

    def test_a_title_block_table(self):
        body = {
            "units": "mm",
            "at": [240, 50],
            "columns": [30, 60, 30],
            "rows": [8, 8, 8],
            "cells": [
                ["名称", "A5 线圈笔记本", "1:2"],
                ["材料", "纸、钢丝", None],
                ["备注\n见说明"],
            ],
            "merge": [[3, 1, 3, 3]],
        }
        preview = domain_preview(
            self.cli(
                "drawing",
                "table",
                "add",
                "--model",
                "block",
                "--request",
                self.request(body, "t.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["size"], preview["rows"], preview["columns"]), ([120, 24], 3, 3))
        self.assertEqual(preview["cells_too_narrow"], [])
        # The name in a 20 mm column: at Creo's 3.5 mm lettering it runs out of its cell.
        squeezed = domain_preview(
            self.cli(
                "drawing",
                "table",
                "add",
                "--model",
                "block",
                "--request",
                self.request(body | {"columns": [30, 20, 70]}, "t2.json"),
                "--dry-run",
            )["data"]["preview"]
        )["cells_too_narrow"]
        self.assertEqual([(c["row"], c["column"], c["width"]) for c in squeezed], [(0, 1, 20)])
        data = self.gated(
            "drawing", "table", "add", "--model", "block", "--request", self.request(body, "t.json")
        )["data"]
        self.checks_pass(data)
        table = self.shown()["tables"][0]
        self.assertEqual(table["cells"][0], ["名称", "A5 线圈笔记本", "1:2"])
        self.assertEqual(table["cells"][2], ["备注\n见说明", None, None])
        for change in (
            {"units": "in"},
            {"at": [400, 50]},
            {"at": [240, 10]},
            {"merge": [[1, 1, 1, 1]]},
            {"merge": [[1, 1, 2, 2], [2, 2, 3, 3]]},
            {"merge": [[1, 1, 1, 2]]},
            {"cells": [["a", "b", "c", "d"]]},
            {"cells": [["bell\x07"]]},
            {"colour": "red"},
        ):
            with self.subTest(change=change):
                refused = self.refused(
                    "drawing",
                    "table",
                    "add",
                    "--model",
                    "block",
                    "--request",
                    self.request(body | change, "bad.json"),
                    status=2,
                )
                self.assertEqual(refused["code"], "E_VALIDATION")
        removed = self.gated(
            "drawing", "item", "remove", "--model", "block", "--item", f"table:{table['id']}"
        )["data"]
        self.checks_pass(removed)
        self.assertEqual(self.shown()["tables"], [])

    def test_a_surface_finish_symbol(self):
        base = ("drawing", "symbol", "add", "--model", "block", "--x", 200, "--y", 150)
        finish = ("--symbol", "surffins/generic/standard", "--value", "roughness_height=3.2")
        preview = domain_preview(self.cli(*base, *finish, "--dry-run")["data"]["preview"])
        self.assertEqual(preview["variables"], ["roughness_height"])
        data = self.gated(*base, *finish)["data"]
        self.checks_pass(data)
        placed = self.shown()["symbols"][0]
        # A numeric variable reads back in the drawing's number format, and still matches.
        self.assertEqual(
            (placed["at"], placed["values"]), ([200.0, 150.0], {"roughness_height": "3,200"})
        )
        # A definition of one's own, from the workspace.
        (self.ws / "mark.sym").write_bytes(b"#SYM\n\\mark\\\n")
        self.checks_pass(self.gated(*base, "--symbol", "mark.sym", "--value", "mark=A")["data"])
        unknown = self.refused(*base, "--symbol", "surffins/none", status=3)
        self.assertEqual(unknown["code"], "E_NOT_FOUND")
        self.assertIn("surffins/generic/standard", unknown["details"]["library"])
        standard = ("--symbol", "surffins/generic/standard")
        for args, code, status in (
            ((*standard, "--value", "height=3.2"), "E_VALIDATION", 2),
            ((*standard, "--value", "3.2"), "E_VALIDATION", 2),
            ((*standard, "--value", "roughness_height=a,roughness_height=b"), "E_VALIDATION", 2),
            (("--symbol", "../outside.sym"), "E_FORBIDDEN", 4),
            (("--symbol", "surffins/../x"), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)
        removed = self.gated(
            "drawing", "item", "remove", "--model", "block", "--item", f"symbol:{placed['id']}"
        )["data"]
        self.checks_pass(removed)
        self.assertEqual(len(self.shown()["symbols"]), 1)

    def test_removing_what_the_drawing_owns(self):
        self.gated(
            "drawing", "note", "add", "--model", "block", "--text", "gone", "--x", 40, "--y", 30
        )
        note = self.shown()["notes"][0]
        item = f"note:{note['id']}"
        preview = domain_preview(
            self.cli("drawing", "item", "remove", "--model", "block", "--item", item, "--dry-run")[
                "data"
            ]["preview"]
        )
        self.assertEqual(preview["removes"]["text"], "gone")
        self.checks_pass(
            self.gated("drawing", "item", "remove", "--model", "block", "--item", item)["data"]
        )
        self.assertEqual(self.shown()["notes"], [])
        self.gated("drawing", "dimension", "annotate", "--model", "block")
        model_dim = self.shown()["dimensions"][0]["name"]
        self.drawing().setdefault("tables", []).append(
            {
                "id": 1,
                "rows": 1,
                "columns": 1,
                "cells": [["TITLE"]],
                "at": [0, 0],
                "from_format": True,
            }
        )
        base = ("drawing", "item", "remove", "--model", "block", "--item")
        for wanted, code, status in (
            (f"dimension:{model_dim}", "E_CONFLICT", 6),
            ("table:1", "E_CONFLICT", 6),
            ("note:77", "E_NOT_FOUND", 3),
            ("symbol:1", "E_NOT_FOUND", 3),
            ("sheet:1", "E_VALIDATION", 2),
            ("note:x", "E_VALIDATION", 2),
        ):
            with self.subTest(item=wanted):
                self.assertEqual(self.refused(*base, wanted, status=status)["code"], code)


class DrawingViews(DrawnBlock):
    """Section and detail views, and views moved and taken off, as a person lays out a sheet."""

    def drawing(self):
        return self.world.models["block.drw"]

    def test_a_view_off_the_sheet_says_where_it_fits(self):
        # The substitute draws a view 50 wide about its middle: at x = 410 on an A3 sheet it
        # runs 15 past the right edge.
        data = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "general",
            "--x",
            410,
            "--y",
            150,
        )["data"]
        off = next(
            o for o in data["verification"]["observations"] if o["observation"] == "off_the_sheet"
        )
        self.assertEqual((off["off"], off["beyond"]), (True, {"right": 15.0}))
        self.assertEqual(off["middle_that_fits"]["x"], [25.0, 395.0])
        self.assertIn("drawing view move", off["fix"])
        moved = self.gated(
            "drawing",
            "view",
            "move",
            "--model",
            "block",
            "--view",
            data["result"]["view"]["name"],
            "--x",
            380,
            "--y",
            150,
        )["data"]
        back = next(
            o for o in moved["verification"]["observations"] if o["observation"] == "off_the_sheet"
        )
        self.assertFalse(back["off"])

    def refused(self, *args, status):
        return self.cli(*args, "--dry-run", status=status)["error"]

    def test_a_section_view_through_a_plane(self):
        below = ("--type", "projection", "--parent", "FRONT", "--x", 110, "--y", 40)
        preview = domain_preview(
            self.cli(
                "drawing",
                "view",
                "add",
                "--model",
                "block",
                *below,
                "--plane",
                "RIGHT",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["view"]["section"], {"name": "A", "plane": "RIGHT"})
        self.assertIn("cuts cross-section A through RIGHT", preview["section"])
        data = self.gated("drawing", "view", "add", "--model", "block", *below, "--plane", "RIGHT")[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(data["result"]["view"]["sections"], ["A"])
        self.assertEqual(data["result"]["view"]["name"], "SECTION_A")
        self.assertEqual(preview["view"]["name"], "SECTION_A")
        part = self.cli("model", "show", "--model", "block")["data"]
        self.assertEqual(part["cross_sections"], [{"name": "A", "plane": "RIGHT"}])
        # The same section again, by its name: nothing new is cut in the part.
        again = ("--type", "projection", "--parent", "FRONT", "--x", 300, "--y", 40)
        preview = domain_preview(
            self.cli(
                "drawing", "view", "add", "--model", "block", *again, "--section", "A", "--dry-run"
            )["data"]["preview"]
        )
        self.assertEqual(preview["view"]["section"], {"name": "A"})
        self.assertIn("shows the model's cross-section A", preview["section"])
        self.checks_pass(
            self.gated("drawing", "view", "add", "--model", "block", *again, "--section", "A")[
                "data"
            ]
        )
        base = ("drawing", "view", "add", "--model", "block")
        for args, code, status in (
            ((*again, "--section", "B"), "E_NOT_FOUND", 3),
            ((*again, "--section", "A", "--plane", "TOP"), "E_CONFLICT", 6),
            ((*again, "--plane", "NOPE"), "E_NOT_FOUND", 3),
            ((*again, "--section", "1A"), "E_VALIDATION", 2),
            (
                ("--type", "detail", "--parent", "FRONT", "--x", 1, "--y", 1),
                "E_VALIDATION",
                2,
            ),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)

    def test_a_half_section(self):
        beside = ("--type", "projection", "--parent", "FRONT", "--x", 110, "--y", 40)
        preview = domain_preview(
            self.cli(
                "drawing",
                "view",
                "add",
                "--model",
                "block",
                *beside,
                "--plane",
                "RIGHT",
                "--half",
                "TOP",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["view"]["section"], {"name": "A", "plane": "RIGHT", "half": "TOP"})
        data = self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            *beside,
            "--plane",
            "RIGHT",
            "--half",
            "TOP",
        )["data"]
        self.checks_pass(data)
        self.assertIn("cut_as_much_as_asked", [c["check"] for c in data["verification"]["checks"]])
        self.assertEqual(data["result"]["view"]["section_area"], "half")
        base = ("drawing", "view", "add", "--model", "block")
        for args in ((*beside, "--half", "TOP"), (*beside, "--plane", "RIGHT", "--half", "RIGHT")):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=2)["code"], "E_VALIDATION")

    def test_a_detail_view_of_a_region(self):
        edge = self.edges()[0]["ref"]
        detail = (
            "--type",
            "detail",
            "--parent",
            "FRONT",
            "--center",
            edge,
            "--radius",
            5,
            "--x",
            330,
            "--y",
            70,
        )
        preview = domain_preview(
            self.cli("drawing", "view", "add", "--model", "block", *detail, "--dry-run")["data"][
                "preview"
            ]
        )
        self.assertEqual(preview["view"]["name"], "A")
        self.assertEqual(preview["view"]["scale"], 2)
        data = self.gated("drawing", "view", "add", "--model", "block", *detail)["data"]
        self.checks_pass(data)
        made = data["result"]["view"]
        self.assertEqual((made["type"], made["parent"], made["name"]), ("detail", "FRONT", "A"))
        # A cross-section's letter is taken too: the next detail is B.
        preview = domain_preview(
            self.cli(
                "drawing",
                "view",
                "add",
                "--model",
                "block",
                *detail[:-4],
                "--x",
                330,
                "--y",
                160,
                "--scale",
                3,
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["view"]["name"], preview["view"]["scale"]), ("B", 3))
        self.world.models["block.prt"]["geometry"].append(
            {"ref": "edge:990", "kind": "edge", "id": 990, "type": "arc", "radius": 2.0}
        )
        base = (
            "drawing",
            "view",
            "add",
            "--model",
            "block",
            "--type",
            "detail",
            "--x",
            330,
            "--y",
            70,
        )
        parent = ("--parent", "FRONT")
        for args, code, status in (
            ((*parent, "--radius", 5), "E_VALIDATION", 2),
            (("--center", edge, "--radius", 5), "E_VALIDATION", 2),
            ((*parent, "--center", "edge:9999", "--radius", 5), "E_NOT_FOUND", 3),
            ((*parent, "--center", "edge:990", "--radius", 1.5), "E_VALIDATION", 2),
            ((*parent, "--center", edge, "--radius", 5, "--name", "A"), "E_CONFLICT", 6),
            ((*parent, "--center", edge, "--radius", 5, "--name", "1bad"), "E_VALIDATION", 2),
            ((*parent, "--center", "surface:1", "--radius", 5), "E_VALIDATION", 2),
            ((*parent, "--center", edge, "--radius", 5, "--orientation", "top"), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)

    def test_views_moved_and_taken_off(self):
        data = self.gated(
            "drawing",
            "view",
            "move",
            "--model",
            "block",
            "--view",
            "LEFT",
            "--x",
            300,
            "--y",
            150,
        )["data"]
        self.checks_pass(data)
        (x0, y0), (x1, y1) = data["result"]["view"]["outline"]
        self.assertEqual([(x0 + x1) / 2, (y0 + y1) / 2], [300, 150])
        # The generic legacy entry must not bypass the dedicated no-cascade lifecycle.
        # Native dependency/refusal/deletion cases live in test_view_remove_runtime.
        before = self.shown()["views"]
        for view in ("FRONT", "LEFT"):
            refused = self.refused(
                "drawing",
                "item",
                "remove",
                "--model",
                "block",
                "--item",
                "view:" + view,
                status=2,
            )
            self.assertEqual(refused["code"], "E_UNSUPPORTED")
            self.assertIn("drawing view remove", refused["details"]["fix"])
        self.assertEqual(self.shown()["views"], before)
        # Creo lets two views share a name; such a name is refused, never guessed at.
        twin = dict(self.drawing()["views"][1])
        self.drawing()["views"].append(twin)
        for args, code, status in (
            (
                (
                    "drawing",
                    "view",
                    "move",
                    "--model",
                    "block",
                    "--view",
                    "NOPE",
                    "--x",
                    1,
                    "--y",
                    1,
                ),
                "E_NOT_FOUND",
                3,
            ),
            (
                (
                    "drawing",
                    "view",
                    "move",
                    "--model",
                    "block",
                    "--view",
                    twin["name"],
                    "--x",
                    1,
                    "--y",
                    1,
                ),
                "E_CONFLICT",
                6,
            ),
            (
                (
                    "drawing",
                    "view",
                    "move",
                    "--model",
                    "block",
                    "--view",
                    "FRONT",
                    "--x",
                    999,
                    "--y",
                    1,
                ),
                "E_VALIDATION",
                2,
            ),
            (
                ("drawing", "item", "remove", "--model", "block", "--item", f"view:{twin['name']}"),
                "E_UNSUPPORTED",
                2,
            ),
            (
                ("drawing", "item", "remove", "--model", "block", "--item", "view:NOPE"),
                "E_UNSUPPORTED",
                2,
            ),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*args, status=status)["code"], code)


class ProfileOptions(Built):
    """Profiles past polygons: arcs in a loop, slots, rounded corners, holes inside the outline."""

    def extrude(self, profile, name, **extra):
        body = RECT | {"name": name, "sketch": RECT["sketch"] | {"profile": profile}} | extra
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(body, name + ".json"),
                "--dry-run",
            )["data"]["preview"]
        )
        data = self.gated(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(body, name + ".json"),
        )["data"]
        self.checks_pass(data)
        return preview, data

    def test_a_plate_with_rounded_corners_and_holes(self):
        self.part()
        plate = {
            "type": "rectangle",
            "width": 60,
            "height": 40,
            "corner_radius": 5,
            "holes": [
                {"type": "circle", "diameter": 6, "center": [-22, -12]},
                {"type": "circle", "diameter": 6, "center": [22, 12]},
                {"type": "slot", "centers": [[-8, 0], [8, 0]], "width": 6},
            ],
        }
        preview, data = self.extrude(plate, "PLATE")
        expected = 60 * 40 - (4 - math.pi) * 25 - 2 * math.pi * 9 - (16 * 6 + math.pi * 9)
        self.assertAlmostEqual(preview["profile_area"], expected, places=9)
        self.assertEqual(preview["sketch"]["entities"], 8 + 1 + 1 + 4)
        self.assertEqual(preview["sketch"]["drawn_by"], "native")
        # The substitute measures a dense polygon, not the arcs: they agree to about 1e-7.
        self.assertLess(abs(data["result"]["volume"]["change"] / (expected * 10) - 1), 1e-6)
        self.assertEqual(
            [q for name, q in self.world.events if name == "feature.extrude"][-1]["sketch"][
                "profile"
            ]["holes"][2]["type"],
            "slot",
        )

    def test_an_outline_of_lines_and_arcs(self):
        self.part()
        # An L bracket, its inside corner filleted R4: the arc turns clockwise, -90 degrees.
        bracket = {
            "type": "outline",
            "start": [0, 0],
            "segments": [
                {"to": [30, 0]},
                {"to": [30, 10]},
                {"to": [14, 10]},
                {"to": [10, 14], "sweep": -90},
                {"to": [10, 30]},
                {"to": [0, 30]},
            ],
        }
        preview, data = self.extrude(bracket, "BRACKET")
        self.assertAlmostEqual(preview["profile_area"], 500 + 16 - 4 * math.pi, places=9)
        self.assertEqual(preview["sketch"]["entities"], 7)
        self.assertTrue(data["result"]["volume"]["matches_request"])
        # A slot cut through it.
        cut = {"type": "slot", "centers": [[4, 4], [4, 24]], "width": 4}
        preview, data = self.extrude(cut, "SLOT", material="remove")
        self.assertAlmostEqual(preview["expected_volume_change"], -(20 * 4 + 4 * math.pi) * 10)

    # Measured on Creo 13.4: a profile with a spline through its points, extruded 10 deep,
    # its area by volume / 10. The CLI's model of Creo's spline agrees as written beside each.
    SPLINES = (
        (
            [{"to": [40, 0]}, {"to": [30, 30], "through": [[50, 15]]}, {"to": [0, 30]}],
            1358.0893922230423,
            1e-5,
        ),
        (
            [{"to": [40, 0]}, {"to": [30, 30], "through": [[52, 8], [45, 24]]}, {"to": [0, 30]}],
            1438.6920190414712,
            1e-5,
        ),
        (
            [
                {"to": [60, 0]},
                {"to": [60, 20]},
                {"to": [0, 20], "through": [[45, 28], [30, 18], [15, 28]]},
            ],
            1492.4266763583644,
            1e-5,
        ),
        (
            [
                {"to": [40, 0]},
                {"to": [20, 30], "through": [[50, 10], [48, 22], [35, 32]]},
                {"to": [0, 30]},
            ],
            1461.6533467873378,
            2e-4,
        ),
        (
            [
                {"to": [40, 0]},
                {"to": [10, 40], "through": [[55, 5], [50, 25], [35, 30], [20, 45]]},
                {"to": [0, 40]},
            ],
            1937.3195150582233,
            5e-4,
        ),
    )

    def test_a_spline_through_points_as_creo_draws_it(self):
        from creo_cli.sketch import area

        for segments, measured, within in self.SPLINES:
            with self.subTest(segments=segments):
                modeled = area({"type": "outline", "start": [0, 0], "segments": segments})
                self.assertLess(abs(modeled / measured - 1), within)
        self.part()
        wave = {"type": "outline", "start": [0, 0], "segments": self.SPLINES[2][0]}
        preview, data = self.extrude(wave, "WAVE")
        # One entity per segment: the spline is one, through its points.
        self.assertEqual(preview["sketch"]["entities"], 3 + 1)
        self.assertTrue(data["result"]["volume"]["matches_request"])
        observed = next(
            o for o in data["verification"]["observations"] if o["observation"] == "volume"
        )
        self.assertIn("B-spline", observed["meaning"])
        sent = [q for n, q in self.world.events if n == "feature.extrude"][-1]
        self.assertEqual(
            sent["sketch"]["profile"]["segments"][2]["through"], [[45, 28], [30, 18], [15, 28]]
        )

    def test_what_a_spline_cannot_be(self):
        self.part()
        line = {"to": [40, 0]}
        for segments in (
            [line, {"to": [30, 30], "through": [[50, 15]], "sweep": 90}, {"to": [0, 30]}],
            [line, {"to": [30, 30], "through": [[40, 0], [50, 15]]}, {"to": [0, 30]}],
            [line, {"to": [30, 30], "through": []}, {"to": [0, 30]}],
            [line, {"to": [30, 30], "through": [[x, 1] for x in range(31)]}, {"to": [0, 30]}],
            # It loops back across the line it started from.
            [line, {"to": [30, 30], "through": [[50, 15], [20, -10], [10, 20]]}, {"to": [0, 30]}],
        ):
            with self.subTest(segments=segments):
                body = RECT | {
                    "name": "BAD",
                    "sketch": RECT["sketch"]
                    | {"profile": {"type": "outline", "start": [0, 0], "segments": segments}},
                }
                self.cli(
                    "feature",
                    "extrude",
                    "--model",
                    "block",
                    "--request",
                    self.request(body, "bad.json"),
                    "--dry-run",
                    status=2,
                )

    def test_revolved_curved_outline_is_refused_before_dispatch(self):
        from tests.test_features import SHAFT

        self.part("shaft.prt")
        shoulder = {
            "type": "outline",
            "start": [0, 0],
            "segments": [
                {"to": [10, 0]},
                {"to": [10, 18]},
                {"to": [8, 20], "sweep": 90},
                {"to": [6, 20]},
                {"to": [6, 40]},
                {"to": [0, 40]},
            ],
        }
        body = SHAFT | {"sketch": SHAFT["sketch"] | {"profile": shoulder}}
        error = self.cli(
            "feature",
            "revolve",
            "--model",
            "shaft",
            "--request",
            self.request(body),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertNotIn("feature.revolve", self.world.ops())

    def test_what_a_profile_cannot_be(self):
        self.part()
        base = RECT["sketch"]
        cases = (
            (
                {
                    "type": "outline",
                    "start": [0, 0],
                    "segments": [{"to": [10, 10]}, {"to": [10, 0]}, {"to": [0, 10]}],
                },
                "crosses or touches itself",
            ),
            (
                {
                    "type": "rectangle",
                    "width": 40,
                    "height": 20,
                    "holes": [{"type": "circle", "diameter": 30}],
                },
                "wholly inside",
            ),
            (
                {
                    "type": "rectangle",
                    "width": 40,
                    "height": 20,
                    "holes": [
                        {"type": "circle", "diameter": 6},
                        {"type": "circle", "diameter": 6, "center": [2, 0]},
                    ],
                },
                "lie apart",
            ),
            (
                {"type": "rectangle", "width": 40, "height": 20, "corner_radius": 10},
                "corner radius",
            ),
            ({"type": "slot", "centers": [[1, 1], [1, 1]], "width": 3}, "two centres"),
            (
                {
                    "type": "outline",
                    "start": [0, 0],
                    "segments": [{"to": [10, 0], "sweep": 0}, {"to": [0, 10]}],
                },
                "turns through some angle",
            ),
            (
                {
                    "type": "circle",
                    "diameter": 20,
                    "holes": [{"type": "ellipse", "x_radius": 2, "y_radius": 1}],
                },
                "native library draws",
            ),
            (
                {
                    "type": "ellipse",
                    "x_radius": 20,
                    "y_radius": 10,
                    "holes": [{"type": "circle", "diameter": 2}],
                },
                "missing or unknown fields",
            ),
            (
                {"type": "outline", "start": [0, 0], "segments": [{"to": [0, 0]}]},
                "end away from where it starts",
            ),
        )
        for profile, message in cases:
            with self.subTest(message=message):
                error = self.cli(
                    "feature",
                    "extrude",
                    "--model",
                    "block",
                    "--request",
                    self.request(RECT | {"sketch": base | {"profile": profile}}, "bad.json"),
                    "--dry-run",
                    status=2,
                )["error"]
                self.assertEqual(error["code"], "E_VALIDATION")
                self.assertIn(message, error["message"])
        # Holes need the native library, as every loop of several entities does.
        self.world.native = False
        error = self.cli(
            "feature",
            "extrude",
            "--model",
            "block",
            "--request",
            self.request(
                RECT
                | {
                    "sketch": base
                    | {
                        "profile": {
                            "type": "circle",
                            "diameter": 20,
                            "holes": [{"type": "circle", "diameter": 5}],
                        }
                    }
                },
                "ring.json",
            ),
            "--dry-run",
            status=2,
        )["error"]
        self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertIn("profiles with holes", error["message"])


class DrawingTolerances(DrawnBlock):
    """Datum feature symbols and feature control frames, as a person tolerances a drawing."""

    def refused(self, *args, status):
        return self.cli(*args, "--dry-run", status=status)["error"]

    def face(self, normal):
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        return next(f["ref"] for f in faces if f.get("normal") == normal)

    def test_datums_on_faces(self):
        bottom = self.face([0, 0, -1])
        view = ("--view", "FRONT")
        preview = domain_preview(
            self.cli(
                "drawing",
                "datum",
                "add",
                "--model",
                "block",
                "--label",
                "A",
                *view,
                "--on",
                bottom,
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["on"]["ref"], bottom)
        data = self.gated(
            "drawing", "datum", "add", "--model", "block", "--label", "A", *view, "--on", bottom
        )["data"]
        self.checks_pass(data)
        self.assertEqual([d["label"] for d in self.shown()["datums"]], ["A"])
        self.checks_pass(
            self.gated(
                "drawing",
                "datum",
                "add",
                "--model",
                "block",
                "--label",
                "B",
                *view,
                "--on",
                "RIGHT",
            )["data"]
        )
        base = ("drawing", "datum", "add", "--model", "block")
        for args, code, status in (
            (("--label", "A", *view, "--on", bottom), "E_CONFLICT", 6),
            (("--label", "I", *view, "--on", bottom), "E_VALIDATION", 2),
            (("--label", "a", *view, "--on", bottom), "E_VALIDATION", 2),
            (("--label", "C", *view, "--on", "surface:9999"), "E_NOT_FOUND", 3),
            (("--label", "C", "--view", "NOPE", "--on", bottom), "E_NOT_FOUND", 3),
            (("--label", "C", *view, "--on", "edge:1"), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)
        self.checks_pass(
            self.gated("drawing", "item", "remove", "--model", "block", "--item", "datum:B")["data"]
        )
        self.assertEqual([d["label"] for d in self.shown()["datums"]], ["A"])

    def test_frames_on_a_dimension_an_edge_and_in_a_view(self):
        self.gated("drawing", "dimension", "annotate", "--model", "block", "--feature", "H1")
        self.gated(
            "drawing",
            "datum",
            "add",
            "--model",
            "block",
            "--label",
            "A",
            "--view",
            "FRONT",
            "--on",
            self.face([0, 0, -1]),
        )
        hole = self.shown()["dimensions"][0]["name"]
        position = (
            "--type",
            "position",
            "--value",
            "0.1",
            "--diameter",
            "--material",
            "mmc",
            "--datums",
            "A,B",
            "--dimension",
            hole,
        )
        preview = domain_preview(
            self.cli("drawing", "gtol", "add", "--model", "block", *position, "--dry-run")["data"][
                "preview"
            ]
        )
        self.assertEqual(preview["owner"], "block.prt")
        self.assertEqual(preview["datums_not_on_this_drawing"], ["B"])
        data = self.gated("drawing", "gtol", "add", "--model", "block", *position)["data"]
        self.checks_pass(data)
        frame = data["result"]["gtol"]
        self.assertEqual(
            (frame["value"], frame["model"], frame["attached"]),
            ("⌀0.1Ⓜ", "block.prt", "annotation"),
        )
        missing = next(
            o
            for o in data["verification"]["observations"]
            if o["observation"] == "datums_not_on_this_drawing"
        )
        self.assertEqual(missing["labels"], ["B"])
        edge = self.edges()[0]["ref"]
        flat = ("--type", "flatness", "--value", "0.05", "--view", "FRONT")
        data = self.gated(
            "drawing",
            "gtol",
            "add",
            "--model",
            "block",
            *flat,
            "--on",
            edge,
            "--x",
            160,
            "--y",
            250,
        )["data"]
        self.checks_pass(data)
        self.assertEqual(data["result"]["gtol"]["attached"], "leaders")
        data = self.gated(
            "drawing",
            "gtol",
            "add",
            "--model",
            "block",
            "--type",
            "parallelism",
            "--value",
            "0.02",
            "--datums",
            "A",
            "--view",
            "FRONT",
            "--x",
            200,
            "--y",
            180,
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [(g["type"], g["model"]) for g in self.shown()["gtols"]],
            [("position", "block.prt"), ("flatness", "block.drw"), ("parallelism", "block.drw")],
        )
        # A frame kept with the part is removed by its owner's name; the preview says so.
        preview = domain_preview(
            self.cli(
                "drawing",
                "item",
                "remove",
                "--model",
                "block",
                "--item",
                "gtol:0@block.prt",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertIn("block.prt's, which changes", preview["effect"])
        self.checks_pass(
            self.gated(
                "drawing", "item", "remove", "--model", "block", "--item", "gtol:0@block.prt"
            )["data"]
        )
        self.checks_pass(
            self.gated("drawing", "item", "remove", "--model", "block", "--item", "gtol:1")["data"]
        )
        self.assertEqual([g["type"] for g in self.shown()["gtols"]], ["flatness"])
        base = (
            "drawing",
            "gtol",
            "add",
            "--model",
            "block",
            "--type",
            "flatness",
            "--value",
            "0.05",
        )
        for args, code, status in (
            (("--dimension", hole, "--view", "FRONT"), "E_VALIDATION", 2),
            (("--view", "FRONT", "--x", 10), "E_VALIDATION", 2),
            ((), "E_VALIDATION", 2),
            (("--dimension", "d999"), "E_NOT_FOUND", 3),
            (
                ("--view", "FRONT", "--on", "edge:9999", "--x", 10, "--y", 10),
                "E_NOT_FOUND",
                3,
            ),
            (("--view", "FRONT", "--x", 999, "--y", 10), "E_VALIDATION", 2),
            (("--dimension", hole, "--datums", "A,B,C,D"), "E_VALIDATION", 2),
            (("--dimension", hole, "--datums", "A,A"), "E_VALIDATION", 2),
            (("--dimension", hole, "--datums", "O"), "E_VALIDATION", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.refused(*base, *args, status=status)["code"], code)
        self.assertEqual(
            self.refused(
                "drawing",
                "gtol",
                "add",
                "--model",
                "block",
                "--type",
                "flatness",
                "--value",
                "0,05",
                "--dimension",
                hole,
                status=2,
            )["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.refused(
                "drawing", "item", "remove", "--model", "block", "--item", "gtol:7", status=3
            )["code"],
            "E_NOT_FOUND",
        )


class AssemblyDrawing(Built):
    """A drawing of an assembly: its parts list, balloons, and the list moved to fit."""

    def setUp(self):
        super().setUp()
        self.block()
        self.part("pin.prt")
        self.gated(
            "feature", "extrude", "--model", "pin", "--request", self.request(PIN, "pin.json")
        )
        self.gated("assembly", "create", "--name", "rig", "--units", "mmns")
        for component, name in (("block", "a"), ("pin", "b"), ("pin", "c")):
            self.gated(
                "assembly",
                "component",
                "add",
                "--model",
                "rig",
                "--component",
                component,
                "--request",
                self.request({"constraints": [{"type": "default"}]}, name + ".json"),
            )
        self.gated(
            "drawing",
            "create",
            "--name",
            "rig",
            "--of",
            "rig.asm",
            "--sheet",
            "a3",
            "--views",
            "none",
            "--scale",
            "2:1",
        )
        self.gated(
            "drawing",
            "view",
            "add",
            "--model",
            "rig",
            "--type",
            "general",
            "--orientation",
            "front",
            "--x",
            130,
            "--y",
            200,
            "--scale",
            2,
        )

    def shown(self):
        return self.cli("model", "show", "--model", "rig.drw")["data"]

    def test_a_parts_list_its_balloons_and_its_place(self):
        preview = domain_preview(
            self.cli("drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35, "--dry-run")[
                "data"
            ]["preview"]
        )
        self.assertEqual(
            preview["lists"],
            [{"model": "block.prt", "quantity": 1}, {"model": "pin.prt", "quantity": 2}],
        )
        self.assertEqual(preview["table"], "Assembly/bom_description_down")
        data = self.gated("drawing", "bom", "add", "--model", "rig", "--x", 10, "--y", 35)["data"]
        self.checks_pass(data)
        table = data["result"]["table"]
        self.assertEqual(table["cells"][2][:3], ["2", "PIN", "2"])
        fits = next(
            o
            for o in data["verification"]["observations"]
            if o["observation"] == "fits_on_the_sheet"
        )
        self.assertTrue(fits["fits"])
        # Move a fully preflighted, page-contained table.
        x = 15
        moved = self.gated(
            "drawing",
            "table",
            "move",
            "--model",
            "rig",
            "--table",
            table["id"],
            "--x",
            x,
            "--y",
            40,
        )["data"]
        self.checks_pass(moved)
        self.assertEqual(moved["result"]["table"]["at"], [x, 40])
        balloons = self.gated(
            "drawing",
            "bom",
            "balloons",
            "--model",
            "rig",
            "--table",
            table["id"],
            "--view",
            "FRONT",
        )["data"]
        self.checks_pass(balloons)
        self.assertEqual(balloons["result"]["balloons"]["made"], 2)
        numbers = next(
            o for o in balloons["verification"]["observations"] if o["observation"] == "numbers"
        )
        self.assertEqual(numbers["numbers"], ["1", "2"])
        for args, code, status in (
            (
                (
                    "drawing",
                    "bom",
                    "balloons",
                    "--model",
                    "rig",
                    "--view",
                    "FRONT",
                    "--table",
                    "77",
                ),
                "E_NOT_FOUND",
                3,
            ),
            (
                (
                    "drawing",
                    "bom",
                    "balloons",
                    "--model",
                    "rig",
                    "--table",
                    table["id"],
                    "--view",
                    "NOPE",
                ),
                "E_NOT_FOUND",
                3,
            ),
            (
                ("drawing", "bom", "balloons", "--model", "rig", "--view", "FRONT", "--table", "x"),
                "E_VALIDATION",
                2,
            ),
            (
                ("drawing", "table", "move", "--model", "rig", "--table", "77", "--x", 1, "--y", 1),
                "E_NOT_FOUND",
                3,
            ),
            (
                (
                    "drawing",
                    "table",
                    "move",
                    "--model",
                    "rig",
                    "--table",
                    table["id"],
                    "--x",
                    999,
                    "--y",
                    1,
                ),
                "E_VALIDATION",
                2,
            ),
            (("drawing", "bom", "add", "--model", "rig", "--x", 999, "--y", 1), "E_VALIDATION", 2),
            (
                ("drawing", "bom", "add", "--model", "rig", "--x", 1, "--y", 1, "--table", "../x"),
                "E_VALIDATION",
                2,
            ),
            (
                (
                    "drawing",
                    "bom",
                    "add",
                    "--model",
                    "rig",
                    "--x",
                    1,
                    "--y",
                    1,
                    "--table",
                    "none.tbl",
                ),
                "E_NOT_FOUND",
                3,
            ),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args, "--dry-run", status=status)["error"]["code"], code)

    def test_a_part_drawing_has_no_parts_list(self):
        self.gated("drawing", "create", "--name", "block", "--of", "block", "--sheet", "a3")
        error = self.cli(
            "drawing",
            "bom",
            "add",
            "--model",
            "block",
            "--x",
            200,
            "--y",
            120,
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(error["code"], "E_CONFLICT")


class ModelImport(Built):
    """A supplier's part from an exchange file, made a model of its own."""

    def test_a_step_file_becomes_a_part(self):
        (self.ws / "vendor").mkdir()
        (self.ws / "vendor" / "motor.stp").write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\n")
        preview = domain_preview(
            self.cli(
                "model", "import", "--path", "vendor/motor.stp", "--name", "motor", "--dry-run"
            )["data"]["preview"]
        )
        self.assertEqual((preview["format"], preview["as"]), ("step", "motor"))
        data = self.gated("model", "import", "--path", "vendor/motor.stp", "--name", "motor")[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(data["result"]["model"], "motor.prt")
        self.assertEqual(
            [q for name, q in self.world.events if name == "model.import"][-1]["format"], "step"
        )
        (self.ws / "notes.txt").write_bytes(b"x")
        for args, code, status in (
            (("--path", "vendor/motor.stp", "--name", "motor"), "E_CONFLICT", 6),
            (("--path", "notes.txt", "--name", "other"), "E_VALIDATION", 2),
            (("--path", "vendor/none.stp", "--name", "other"), "E_NOT_FOUND", 3),
            (("--path", "../outside.stp", "--name", "other"), "E_FORBIDDEN", 4),
            (("--path", "vendor/motor.stp", "--name", "1motor"), "E_VALIDATION", 2),
            (("--path", "vendor/motor.stp", "--name", "other", "--type", "drawing"), "E_USAGE", 2),
        ):
            with self.subTest(args=args):
                self.assertEqual(
                    self.cli("model", "import", *args, "--dry-run", status=status)["error"]["code"],
                    code,
                )
        data = self.gated(
            "model",
            "import",
            "--path",
            "vendor/motor.stp",
            "--name",
            "motor2",
            "--type",
            "assembly",
        )["data"]
        self.checks_pass(data)
        self.assertEqual(data["result"]["model"], "motor2.asm")


class RelationOptions(Built):
    """Relations as a person writes them: a dimension tied to another, then refused a value."""

    def test_a_dimension_driven_by_a_relation(self):
        self.block()
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        width, depth = dims[0]["name"], dims[2]["name"]
        rules = {
            "relations": [
                "/* the block as deep as a quarter of its width",
                f"{depth} = {width} / 4",
            ]
        }
        preview = domain_preview(
            self.cli(
                "relation",
                "set",
                "--model",
                "block",
                "--request",
                self.request(rules, "rel.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["from"], preview["to"]), ([], rules["relations"]))
        data = self.gated(
            "relation", "set", "--model", "block", "--request", self.request(rules, "rel.json")
        )["data"]
        self.checks_pass(data)
        driven = next(
            o
            for o in data["verification"]["observations"]
            if o["observation"] == "driven_dimensions"
        )
        self.assertEqual(driven["dimensions"], [{"name": depth, "value": 10.0}])
        self.assertEqual(
            self.cli("relation", "list", "--model", "block")["data"]["relations"],
            rules["relations"],
        )
        # A driven dimension is set through its relation, not directly.
        refused = self.cli(
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            depth,
            "--value",
            12,
            "--units",
            "mm",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(refused["code"], "E_CONFLICT")
        for body, code, status in (
            ({"relations": ["d1 = 2\nd2 = 3"]}, "E_VALIDATION", 2),
            ({"relations": "d1 = 2"}, "E_VALIDATION", 2),
            ({"rules": []}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "relation",
                        "set",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        # A relation Creo cannot evaluate changes nothing.
        failed = self.gated(
            "relation",
            "set",
            "--model",
            "block",
            "--request",
            self.request({"relations": ["nope = 1"]}, "nope.json"),
            status=1,
        )["error"]
        self.assertEqual(failed["details"]["receipt_status"], "failed_unchanged")
        self.assertEqual(
            self.cli("relation", "list", "--model", "block")["data"]["relations"],
            rules["relations"],
        )
        # Clearing them frees the dimension again.
        self.checks_pass(
            self.gated(
                "relation",
                "set",
                "--model",
                "block",
                "--request",
                self.request({"relations": []}, "none.json"),
            )["data"]
        )


class DraftOptions(Built):
    """A draft as a molded part takes one: a block's walls tilted about its base, or about a
    datum plane with the pull turned round."""

    def faces(self):
        return self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]

    def walls_and_base(self):
        faces = self.faces()
        walls = [f["ref"] for f in faces if f.get("normal") and f["normal"][2] == 0]
        base = next(f["ref"] for f in faces if f.get("normal") == [0, 0, -1])
        return walls, base

    def test_multiple_walls_are_refused_by_bounded_profile(self):
        self.block()
        walls, base = self.walls_and_base()
        body = {"name": "WALL_DRAFT", "surfaces": walls, "hinge": base, "angle": 3}
        result = self.cli(
            "feature",
            "draft",
            "--model",
            "block",
            "--request",
            self.request(body, "draft.json"),
            "--dry-run",
            status=2,
        )
        self.assertEqual(result["error"]["code"], "E_UNSUPPORTED")
        self.assertNotIn("feature.draft", self.world.ops())

    def test_reversed_pull_is_refused_by_bounded_profile(self):
        self.block()
        side = next(f["ref"] for f in self.faces() if f["normal"] == [1, 0, 0])
        body = {
            "surfaces": [side],
            "hinge": "FRONT",
            "pull": "FRONT",
            "flip_pull": True,
            "angle": -5,
        }
        self.cli(
            "feature",
            "draft",
            "--model",
            "block",
            "--request",
            self.request(body, "draft.json"),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.draft", self.world.ops())

    def test_what_a_draft_cannot_be(self):
        self.block()
        walls, base = self.walls_and_base()
        edge = self.edges()[0]["ref"]
        side = next(f["ref"] for f in self.faces() if f["normal"] == [1, 0, 0])
        good = {"surfaces": [side], "hinge": "FRONT", "angle": 3}
        for body, code, status in (
            (good | {"angle": 0}, "E_VALIDATION", 2),
            (good | {"angle": 90}, "E_VALIDATION", 2),
            (good | {"surfaces": [edge]}, "E_VALIDATION", 2),
            (good | {"surfaces": [walls[0], walls[0]]}, "E_VALIDATION", 2),
            (good | {"hinge": side}, "E_VALIDATION", 2),
            (good | {"hinge": edge}, "E_VALIDATION", 2),
            (good | {"pull": edge}, "E_VALIDATION", 2),
            (good | {"surfaces": ["surface:9999"]}, "E_NOT_FOUND", 3),
            ({"surfaces": walls, "angle": 3}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "draft",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        # A square-to-pull face is now refused before the native creation attempt.
        top = self.top()["ref"]
        self.cli(
            "feature",
            "draft",
            "--model",
            "block",
            "--request",
            self.request({"surfaces": [top], "hinge": "FRONT", "angle": 3}, "top.json"),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.draft", self.world.ops())


class RibOptions(Built):
    """Old unbounded gussets and side selection are explicitly outside the new profile."""

    SKETCH = {"plane": "FRONT", "orient_ref": "RIGHT", "points": [[-20, 5], [0, -10]]}

    def test_unbounded_gusset_refuses_without_direction_trials(self):
        self.block()
        self.world.capabilities["prismatic_rib_readback"] = 3
        body = {"units": "mm", "name": "GUSSET", "thickness": 4, "sketch": self.SKETCH}
        result = self.cli(
            "feature",
            "rib",
            "--model",
            "block",
            "--request",
            self.request(body, "rib.json"),
            "--dry-run",
            status=2,
        )
        self.assertEqual(result["error"]["code"], "E_UNSUPPORTED")
        self.assertNotIn("feature.rib", self.world.ops())
        self.assertNotIn("geometry.ray", self.world.ops())

    def test_solid_prism_does_not_authorize_endpoint_extension(self):
        self.block()
        self.world.capabilities["prismatic_rib_readback"] = 3
        body = {
            "units": "mm",
            "thickness": 4,
            "sketch": self.SKETCH | {"points": [[-15, 5], [0, -10]]},
        }
        self.cli(
            "feature",
            "rib",
            "--model",
            "block",
            "--request",
            self.request(body, "rib.json"),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.rib", self.world.ops())
        self.assertNotIn("geometry.ray", self.world.ops())

    def test_one_sided_multisegment_chain_is_outside_bounded_profile(self):
        self.block()
        self.world.capabilities["prismatic_rib_readback"] = 3
        body = {
            "units": "mm",
            "name": "STIFFENER",
            "thickness": 3,
            "side": "one",
            "fill": "right",
            "sketch": self.SKETCH | {"points": [[-20, 5], [-5, 5], [0, -10]]},
        }
        self.cli(
            "feature",
            "rib",
            "--model",
            "block",
            "--request",
            self.request(body, "rib.json"),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.rib", self.world.ops())

    def test_what_a_rib_cannot_be(self):
        self.block()
        self.world.capabilities["prismatic_rib_readback"] = 3
        good = {"units": "mm", "thickness": 4, "sketch": self.SKETCH}
        for body, code, status in (
            (good | {"thickness": 0}, "E_VALIDATION", 2),
            (good | {"sketch": self.SKETCH | {"points": [[0, 0]]}}, "E_VALIDATION", 2),
            (good | {"sketch": self.SKETCH | {"points": [[0, 0], [0, 0]]}}, "E_VALIDATION", 2),
            (
                good | {"sketch": self.SKETCH | {"points": [[0, 0], [10, 0], [10, 10], [0, 0]]}},
                "E_VALIDATION",
                2,
            ),
            (
                good | {"sketch": self.SKETCH | {"points": [[0, 0], [10, 10], [10, 0], [0, 10]]}},
                "E_VALIDATION",
                2,
            ),
            (
                good | {"sketch": self.SKETCH | {"points": [[0, 0], [10, 0], [5, 0]]}},
                "E_VALIDATION",
                2,
            ),
            (good | {"sketch": self.SKETCH | {"orient_ref": "FRONT"}}, "E_VALIDATION", 2),
            (good | {"sketch": self.SKETCH | {"plane": "NOPE"}}, "E_NOT_FOUND", 3),
            (good | {"side": "both"}, "E_VALIDATION", 2),
            (good | {"fill": "up"}, "E_VALIDATION", 2),
            ({"units": "mm", "sketch": self.SKETCH}, "E_VALIDATION", 2),
            # An end off the part: a chain read in the wrong axes.
            (
                good | {"sketch": self.SKETCH | {"points": [[-20, 5], [0, 400]]}},
                "E_VALIDATION",
                2,
            ),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "rib",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        self.cli(
            "feature",
            "rib",
            "--model",
            "block",
            "--request",
            self.request(good | {"fill": "right"}, "right.json"),
            "--dry-run",
            status=2,
        )
        self.assertNotIn("feature.rib", self.world.ops())


class ToleranceOptions(Built):
    """Tolerances as a drafter gives them: plus and minus, symmetric, limits, an ISO fit once the
    part is in the ISO/DIN standard, basic, and none again."""

    def diameter(self):
        self.part()
        body = {
            "units": "mm",
            "name": "PIN",
            "depth": 30,
            "sketch": RECT["sketch"] | {"profile": {"type": "circle", "diameter": 20}},
        }
        self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(body, "pin.json")
        )
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        return next(d for d in dims if d["type"] == "diameter")

    def tolerance(self, dim, *flags, status=0):
        return self.gated(
            "dimension",
            "set-tolerance",
            "--model",
            "block",
            "--dimension",
            dim["name"],
            *flags,
            status=status,
        )

    def test_plus_minus_symmetric_limits_and_back_to_none(self):
        dim = self.diameter()
        self.assertEqual(dim["tolerance"], {"type": "nominal"})
        preview = domain_preview(
            self.cli(
                "dimension",
                "set-tolerance",
                "--model",
                "block",
                "--dimension",
                dim["name"],
                "--plus",
                0.021,
                "--minus",
                0,
                "--units",
                "mm",
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(
            preview["to"],
            {"type": "plus_minus", "plus": 0.021, "minus": 0.0, "upper": 20.021, "lower": 20.0},
        )
        self.assertEqual(preview["from"], {"type": "nominal"})
        for flags, read in (
            (
                ("--plus", 0.021, "--minus", 0, "--units", "mm"),
                {"type": "plus_minus", "upper": 20.021},
            ),
            (("--symmetric", 0.005, "--units", "mm"), {"type": "symmetric", "value": 0.005}),
            (
                ("--upper", 20.013, "--lower", 19.992, "--units", "mm"),
                {"type": "limits", "lower": 19.992},
            ),
            (("--basic",), {"type": "basic"}),
            (("--nominal",), {"type": "nominal"}),
        ):
            with self.subTest(flags=flags):
                data = self.tolerance(dim, *flags)["data"]
                self.checks_pass(data)
                now = next(
                    d
                    for d in self.cli("dimension", "list", "--model", "block")["data"]["items"]
                    if d["id"] == dim["id"]
                )
                self.assertEqual({k: now["tolerance"].get(k) for k in read}, read)

    def test_what_a_tolerance_cannot_be(self):
        dim = self.diameter()
        for flags, code, status in (
            ((), "E_USAGE", 2),
            (("--plus", 0.1, "--units", "mm"), "E_USAGE", 2),
            (("--plus", 0.1, "--minus", 0.1), "E_USAGE", 2),
            (("--symmetric", 0.1, "--fit", "H7", "--units", "mm"), "E_USAGE", 2),
            (("--fit", "H7", "--units", "mm"), "E_USAGE", 2),
            (("--nominal", "--show", "class"), "E_USAGE", 2),
            (("--plus", -0.1, "--minus", 0.05, "--units", "mm"), "E_VALIDATION", 2),
            (("--symmetric", 0, "--units", "mm"), "E_VALIDATION", 2),
            (("--upper", 19.9, "--lower", 20.1, "--units", "mm"), "E_VALIDATION", 2),
            (("--fit", "Hg7"), "E_VALIDATION", 2),
            (("--symmetric", 0.1, "--units", "in"), "E_CONFLICT", 6),
        ):
            with self.subTest(flags=flags):
                self.assertEqual(
                    self.cli(
                        "dimension",
                        "set-tolerance",
                        "--model",
                        "block",
                        "--dimension",
                        dim["name"],
                        *flags,
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        # A fit needs the ISO/DIN standard; the refusal says how to get there.
        refused = self.cli(
            "dimension",
            "set-tolerance",
            "--model",
            "block",
            "--dimension",
            dim["name"],
            "--fit",
            "H7",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(refused["code"], "E_CONFLICT")
        self.assertIn("set-tolerance-standard", refused["details"]["fix"])

    def test_an_iso_fit_once_the_part_is_iso(self):
        dim = self.diameter()
        self.assertEqual(
            self.cli("model", "show", "--model", "block")["data"]["tolerance_standard"], "ansi"
        )
        data = self.gated(
            "model",
            "set-tolerance-standard",
            "--model",
            "block",
            "--standard",
            "iso",
            "--class",
            "medium",
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [c["check"] for c in data["verification"]["checks"]],
            [
                "standard_as_requested",
                "geometry_unchanged",
                "every_feature_still_regenerates",
                "class_as_requested",
                "all_nominal_dimension_values_unchanged",
                "native_feature_rows_unchanged",
                "native_feature_definitions_unchanged",
                "solid_geometry_unchanged",
                "units_unchanged",
                "explicit_dimension_tolerances_unchanged",
                "material_and_mass_unchanged",
            ],
        )
        shown = self.cli("model", "show", "--model", "block")["data"]
        self.assertEqual((shown["tolerance_standard"], shown["tolerance_class"]), ("iso", "medium"))
        for flags, read in (
            (("--fit", "H7"), {"fit": "H7", "shown": "class", "upper": 20.021, "lower": 20.0}),
            (
                ("--fit", "g6", "--show", "deviations"),
                {"fit": "g6", "shown": "deviations", "plus": -0.007},
            ),
        ):
            with self.subTest(flags=flags):
                result = self.tolerance(dim, *flags)["data"]
                self.checks_pass(result)
                self.assertEqual(
                    {k: result["result"]["dimension"]["tolerance"].get(k) for k in read}, read
                )
        sent = [q for name, q in self.world.events if name == "dimension.tolerance"][-1]
        self.assertEqual(sent["tolerance"], {"type": "fit", "fit": "g6", "show": "deviations"})
        self.assertEqual(
            self.cli(
                "model",
                "set-tolerance-standard",
                "--model",
                "block",
                "--standard",
                "ansi",
                "--class",
                "fine",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_USAGE",
        )


class HoleOptions(Built):
    """The holes a fastener needs: tapped for it, clear of it, counterbored for its head,
    countersunk for a flat one -- sized from Creo's hole chart, or by hand."""

    def place(self, x):
        return {
            "surface": self.top()["ref"],
            "offsets": [{"from": "RIGHT", "distance": x}, {"from": "TOP", "distance": 0}],
        }

    def hole(self, body, status=0, name="hole.json"):
        return self.gated(
            "feature",
            "hole",
            "--model",
            "block",
            "--request",
            self.request(body, name),
            status=status,
        )

    def test_a_screw_named_as_a_person_names_it(self):
        # M8 is the coarse thread: the chart's M8x1.25, said so in the preview.
        self.block()
        body = {
            "units": "mm",
            "name": "CLEAR",
            "clearance": {"size": "M8"},
            "depth": "through_all",
            "placement": self.place(-10),
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "hole",
                "--model",
                "block",
                "--request",
                self.request(body, "m8.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(
            (preview["chart"]["size"], preview["chart"]["size_asked"], preview["diameter"]),
            ("M8x1.25", "M8", 9.0),
        )
        self.checks_pass(self.hole(body, name="m8.json")["data"])

    def test_tapped_and_clearance_holes_from_the_chart(self):
        self.block()
        tapped = {
            "units": "mm",
            "name": "TAP",
            "thread": {"size": "M8x1.25", "depth": 6},
            "depth": 8,
            "placement": self.place(-10),
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "hole",
                "--model",
                "block",
                "--request",
                self.request(tapped, "tap.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["kind"], preview["diameter"]), ("tapped", 6.8))
        self.assertEqual(preview["chart"]["basic_diameter"], 8.0)
        r = 3.4
        point = math.pi * r**2 * (r / math.tan(math.radians(59))) / 3
        self.assertAlmostEqual(
            preview["expected_volume_change"], -(math.pi * r**2 * 8 + point), places=9
        )
        data = self.hole(tapped, name="tap.json")["data"]
        self.checks_pass(data)
        self.assertTrue(
            {"drilled_to_the_diameter", "thread_on_the_hole"}
            <= {c["check"] for c in data["verification"]["checks"]}
        )
        self.assertEqual(data["result"]["drill_diameter"], 6.8)
        bolted = {
            "units": "mm",
            "name": "CB",
            "clearance": {"size": "M6x1", "fit": "medium"},
            "counterbore": True,
            "depth": "through_all",
            "placement": self.place(10),
        }
        data = self.hole(bolted, name="cb.json")["data"]
        self.checks_pass(data)
        self.assertEqual(data["result"]["counterbore"], {"diameter": 11.2, "depth": 6.0})
        self.assertIn(
            "counterbore_as_requested", [c["check"] for c in data["verification"]["checks"]]
        )
        sent = [q for n, q in self.world.events if n == "feature.hole"][-1]
        self.assertEqual(
            (sent["clearance"], sent["counterbore"]), ({"size": "M6x1", "fit": "medium"}, True)
        )

    def test_a_plain_hole_countersunk_by_hand(self):
        self.block()
        body = {
            "units": "mm",
            "name": "CS",
            "diameter": 4.5,
            "countersink": {"diameter": 9, "angle": 90},
            "depth": 6,
            "placement": self.place(0),
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "hole",
                "--model",
                "block",
                "--request",
                self.request(body, "cs.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["kind"], preview["chart"]), ("custom", None))
        r, big = 2.25, 4.5
        h = big - r
        expected = math.pi * r**2 * 6 + math.pi * r**2 * (r / math.tan(math.radians(59))) / 3
        expected += math.pi * h / 3 * (big**2 + big * r + r**2) - math.pi * r**2 * h
        self.assertAlmostEqual(preview["expected_volume_change"], -expected, places=9)
        self.checks_pass(self.hole(body, name="cs.json")["data"])

    def test_what_a_hole_cannot_be(self):
        self.block()
        base = {"units": "mm", "depth": 8, "placement": self.place(0)}
        for body, code, status in (
            (base, "E_VALIDATION", 2),
            (base | {"diameter": 5, "thread": {"size": "M6x1", "depth": 6}}, "E_VALIDATION", 2),
            (base | {"diameter": 5, "counterbore": True}, "E_VALIDATION", 2),
            (base | {"diameter": 5, "counterbore": {"diameter": 4, "depth": 2}}, "E_VALIDATION", 2),
            (base | {"thread": {"size": "M6x1"}}, "E_VALIDATION", 2),
            (base | {"thread": {"size": "M6x1", "depth": 9}}, "E_VALIDATION", 2),
            (
                base | {"clearance": {"size": "M6x1"}, "counterbore": True, "countersink": True},
                "E_VALIDATION",
                2,
            ),
            (base | {"clearance": {"size": "M6x1", "fit": "loose"}}, "E_VALIDATION", 2),
            (base | {"clearance": {"size": "M1.1x.25"}}, "E_VALIDATION", 2),
            (
                base | {"thread": {"size": "M1.1x.25", "depth": 2}, "counterbore": True},
                "E_VALIDATION",
                2,
            ),
            (base | {"thread": {"size": "M6x9", "depth": 2}}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "hole",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )


class ThreadOptions(Built):
    """Cosmetic threads as a drawing shows them: a shaft's end threaded M10, a thread given by
    its diameter, and what a thread cannot be."""

    def shaft(self):
        self.part()
        body = {
            "units": "mm",
            "name": "SHAFT",
            "depth": 40,
            "sketch": RECT["sketch"] | {"profile": {"type": "circle", "diameter": 10}},
        }
        self.gated(
            "feature", "extrude", "--model", "block", "--request", self.request(body, "shaft.json")
        )
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        cylinder = next(f["ref"] for f in faces if f.get("type") == "cylinder")
        end = next(f["ref"] for f in faces if f.get("normal") == [0, 0, 1])
        return cylinder, end

    def test_a_shaft_end_threaded_from_the_chart(self):
        cylinder, end = self.shaft()
        body = {
            "units": "mm",
            "name": "END",
            "surface": cylinder,
            "start": end,
            "size": "M10x1.5",
            "depth": 15,
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "cosmetic-thread",
                "--model",
                "block",
                "--request",
                self.request(body, "t.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertTrue(preview["external"])
        self.assertAlmostEqual(preview["diameter"], 10 - 1.082532 * 1.5, places=9)
        data = self.gated(
            "feature",
            "cosmetic-thread",
            "--model",
            "block",
            "--request",
            self.request(body, "t.json"),
        )["data"]
        self.checks_pass(data)
        self.assertEqual(
            [c["check"] for c in data["verification"]["checks"]][-4:],
            [
                "thread_diameter_as_requested",
                "thread_depth_as_requested",
                "thread_surface_at_the_diameter",
                "nothing_removed",
            ],
        )
        self.assertEqual(data["result"]["feature"]["type"], "FEATTYPE_THREAD")
        # Called out on drawings as the chart names it.
        self.assertEqual(data["result"]["callout"], data["result"]["chart"]["size"])

    def test_a_tapped_bore(self):
        _, end = self.shaft()
        drill = {
            "units": "mm",
            "name": "DRILL",
            "diameter": 8.5,
            "depth": 12,
            "placement": {
                "surface": end,
                "offsets": [{"from": "RIGHT", "distance": 0}, {"from": "TOP", "distance": 0}],
            },
        }
        self.gated(
            "feature", "hole", "--model", "block", "--request", self.request(drill, "drill.json")
        )
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        bore = next(f["ref"] for f in faces if f.get("outward") == "toward_axis")
        body = {"units": "mm", "surface": bore, "start": end, "size": "M10x1.5", "depth": 10}
        preview = domain_preview(
            self.cli(
                "feature",
                "cosmetic-thread",
                "--model",
                "block",
                "--request",
                self.request(body, "t.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["external"], preview["diameter"]), (False, 10.0))
        self.checks_pass(
            self.gated(
                "feature",
                "cosmetic-thread",
                "--model",
                "block",
                "--request",
                self.request(body, "t.json"),
            )["data"]
        )
        # A bore as wide as the thread has nothing to cut it into.
        wide = body | {"diameter": 8.0}
        del wide["size"]
        self.assertEqual(
            self.cli(
                "feature",
                "cosmetic-thread",
                "--model",
                "block",
                "--request",
                self.request(wide, "w.json"),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_a_thread_given_by_its_diameter(self):
        cylinder, end = self.shaft()
        body = {"units": "mm", "surface": cylinder, "start": end, "diameter": 8.2, "depth": 6}
        self.checks_pass(
            self.gated(
                "feature",
                "cosmetic-thread",
                "--model",
                "block",
                "--request",
                self.request(body, "t.json"),
            )["data"]
        )
        sent = [q for n, q in self.world.events if n == "feature.thread"][-1]
        self.assertEqual((sent["diameter"], sent["depth"]), (8.2, 6))

    def test_what_a_thread_cannot_be(self):
        cylinder, end = self.shaft()
        good = {"units": "mm", "surface": cylinder, "start": end, "size": "M10x1.5", "depth": 15}
        for body, code, status in (
            (good | {"diameter": 8}, "E_VALIDATION", 2),
            ({k: v for k, v in good.items() if k != "size"}, "E_VALIDATION", 2),
            (
                {k: v for k, v in good.items() if k != "size"} | {"diameter": 8, "series": "ISO"},
                "E_VALIDATION",
                2,
            ),
            (good | {"start": cylinder}, "E_VALIDATION", 2),
            (good | {"surface": end, "start": cylinder}, "E_VALIDATION", 2),
            (good | {"depth": 0}, "E_VALIDATION", 2),
            ({k: v for k, v in good.items() if k != "size"} | {"diameter": 11}, "E_VALIDATION", 2),
            (good | {"size": "M8x1.25"}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "cosmetic-thread",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )


class SketchFrames(Built):
    """Where a sketch lies in the model, before anything is built: the frame Creo lays each
    plane and orientation out in, as measured, and the box an extrusion will fill."""

    CASES = (
        ("TOP", "RIGHT", "right", [1, 0, 0], [0, 0, -1], [0, 1, 0]),
        ("TOP", "FRONT", "up", [-1, 0, 0], [0, 0, 1], [0, 1, 0]),
        ("RIGHT", "FRONT", "up", [0, 1, 0], [0, 0, 1], [1, 0, 0]),
        ("RIGHT", "TOP", "right", [0, 1, 0], [0, 0, 1], [1, 0, 0]),
        ("FRONT", "TOP", "up", [1, 0, 0], [0, 1, 0], [0, 0, 1]),
        ("FRONT", "RIGHT", "left", [-1, 0, 0], [0, -1, 0], [0, 0, 1]),
        ("TOP", "RIGHT", "down", [0, 0, -1], [-1, 0, 0], [0, 1, 0]),
    )

    def test_each_plane_and_orientation_as_creo_lays_it_out(self):
        self.part()
        for plane, ref, orient, x, y, n in self.CASES:
            with self.subTest(plane=plane, ref=ref, orient=orient):
                body = {
                    "units": "mm",
                    "depth": 1,
                    "sketch": {
                        "plane": plane,
                        "orient_ref": ref,
                        "orient": orient,
                        "profile": {
                            "type": "rectangle",
                            "width": 2,
                            "height": 2,
                            "center": [10, 5],
                        },
                    },
                }
                preview = domain_preview(
                    self.cli(
                        "feature",
                        "extrude",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "f.json"),
                        "--dry-run",
                    )["data"]["preview"]
                )
                frame = preview["sketch"]["frame"]
                self.assertEqual(
                    (frame["x"], frame["y"], frame["normal"], frame["origin"]), (x, y, n, [0, 0, 0])
                )
                # The point [10, 5] of the sketch, carried a depth of 1 against the normal.
                centre = [10 * a + 5 * b for a, b in zip(x, y, strict=True)]
                box = preview["model_box"]
                self.assertEqual(
                    [round((lo + hi) / 2, 9) for lo, hi in zip(*box, strict=True)],
                    [round(c - 0.5 * m, 9) for c, m in zip(centre, n, strict=True)],
                )
                self.assertEqual(preview["extrudes_toward"], [-c for c in n])

    def test_the_block_it_will_be_and_a_symmetric_one(self):
        self.part()
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(RECT, "b.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["model_box"], [[-20, -10, -10], [20, 10, 0]])
        both = RECT | {"side": "symmetric"}
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(both, "s.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["model_box"], [[-20, -10, -5], [20, 10, 5]])
        self.assertEqual(preview["extrudes_toward"], [[0, 0, 1], [0, 0, -1]])


class PatternGrid(Built):
    """A grid of holes, rows by columns, as the Pattern tool's two directions make one."""

    def test_four_bolt_holes_in_two_rows(self):
        self.block()
        top = self.top()["ref"]
        self.gated(
            "feature",
            "hole",
            "--model",
            "block",
            "--request",
            self.request(
                {
                    "units": "mm",
                    "name": "H1",
                    "diameter": 5,
                    "depth": "through_all",
                    "placement": {
                        "surface": top,
                        "offsets": [
                            {"from": "RIGHT", "distance": 15},
                            {"from": "TOP", "distance": 5},
                        ],
                    },
                },
                "h.json",
            ),
        )
        grid = {
            "units": "mm",
            "name": "GRID",
            "feature": "H1",
            "direction": {"along": "RIGHT", "spacing": -30, "count": 2},
            "direction2": {"along": "TOP", "spacing": -10, "count": 2},
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "pattern",
                "--model",
                "block",
                "--request",
                self.request(grid, "g.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual((preview["kind"], preview["instances"]), ("grid", 4))
        data = self.gated(
            "feature", "pattern", "--model", "block", "--request", self.request(grid, "g.json")
        )["data"]
        self.checks_pass(data)
        self.assertEqual(len(data["result"]["members"]), 4)
        for body in (
            {k: v for k, v in grid.items() if k != "direction"}
            | {"axis": {"about": "RIGHT", "angle": 90, "count": 2}},
            grid | {"direction2": {"along": "RIGHT", "spacing": 10, "count": 2}},
            grid | {"direction2": {"along": "TOP", "spacing": 0, "count": 2}},
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "pattern",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=2,
                    )["error"]["code"],
                    "E_VALIDATION",
                )


class ViewOverlaps(Built):
    """A view that lands on another is reported, with the move that clears it."""

    def test_a_projection_that_lands_on_another_view(self):
        from creo_cli import registry  # noqa: F401 -- the commands load through it
        from creo_cli.commands.drawing import overlaps

        views = [
            {"name": "FRONT", "sheet": 1, "outline": [[50, 80], [170, 140]]},
            {"name": "SIDE", "sheet": 1, "outline": [[230, 80], [305, 140]]},
            {"name": "LATER", "sheet": 2, "outline": [[290, 80], [370, 140]]},
        ]
        made = {"name": "A_A", "sheet": 1, "outline": [[292, 82], [367, 142]]}
        seen = overlaps(made, views + [made], "housing")
        self.assertEqual(seen["views"], ["SIDE"])
        self.assertIn("drawing view move --model housing --view A_A", seen["fix"])
        clear = {"name": "A_A", "sheet": 1, "outline": [[320, 82], [395, 142]]}
        self.assertEqual(
            overlaps(clear, views, "housing"), {"observation": "overlaps_views", "views": []}
        )
        # A projection is slid along its line with its parent to the nearest place clear of
        # every view by 8 and on the sheet, and the move given in numbers.
        sheet = [{"number": 1, "width": 420, "height": 297}]
        projected = made | {"type": "projection", "parent": "FRONT"}
        seen = overlaps(projected, views + [projected], "housing", sheet)
        middle = seen["middle_that_clears"]
        self.assertEqual(middle[1], 112)
        self.assertGreaterEqual(middle[0] - 37.5, 305 + 8)
        self.assertLessEqual(middle[0] + 37.5, 420 - 8)
        self.assertTrue(seen["fix"].endswith(f"--x {middle[0]:g} --y {middle[1]:g}"))


class SketchOnAFace(Built):
    """A sketch on a flat face, as a person clicks the face: dimensioned to the default planes
    square to it, laid out from it, and the box it fills said before it is built."""

    def test_a_boss_on_the_top_and_a_slot_in_the_side(self):
        self.block()
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        top = next(f["ref"] for f in faces if f.get("normal") == [0, 0, 1])
        side = next(f["ref"] for f in faces if f.get("normal") == [1, 0, 0])
        boss = {
            "units": "mm",
            "name": "BOSS",
            "depth": 5,
            "side": "two",
            "sketch": {
                "plane": top,
                "orient_ref": "RIGHT",
                "profile": {"type": "circle", "diameter": 10, "center": [5, 0]},
            },
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(boss, "boss.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["sketch"]["references"], ["RIGHT", "TOP"])
        self.assertEqual(preview["sketch"]["frame"]["normal"], [0, 0, 1])
        self.assertEqual(
            (preview["extrudes_toward"], preview["model_box"]),
            ([0, 0, 1], [[0, -5, 0], [10, 5, 5]]),
        )
        self.checks_pass(
            self.gated(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(boss, "boss.json"),
            )["data"]
        )
        sent = [q for n, q in self.world.events if n == "feature.extrude"][-1]
        self.assertEqual(
            (sent["sketch"]["plane"], sent["sketch"]["references"]), (top, ["RIGHT", "TOP"])
        )
        slot = {
            "units": "mm",
            "name": "SLOT",
            "depth": 3,
            "material": "remove",
            "sketch": {
                "plane": side,
                "orient_ref": "FRONT",
                "orient": "up",
                "profile": {"type": "rectangle", "width": 8, "height": 4, "center": [0, -5]},
            },
        }
        preview = domain_preview(
            self.cli(
                "feature",
                "extrude",
                "--model",
                "block",
                "--request",
                self.request(slot, "slot.json"),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertEqual(preview["sketch"]["references"], ["TOP", "FRONT"])
        self.assertEqual(preview["sketch"]["frame"]["origin"], [20, 0, 0])
        self.assertEqual(preview["model_box"], [[17, -4, -7], [20, 4, -3]])

    def test_what_a_sketch_cannot_go_on(self):
        self.block()
        edge = self.edges()[0]["ref"]
        for plane, code in ((edge, "E_VALIDATION"), ("surface:9999", "E_NOT_FOUND")):
            body = {
                "units": "mm",
                "depth": 5,
                "sketch": {
                    "plane": plane,
                    "orient_ref": "RIGHT",
                    "profile": {"type": "circle", "diameter": 4},
                },
            }
            with self.subTest(plane=plane):
                status = 3 if code == "E_NOT_FOUND" else 2
                self.assertEqual(
                    self.cli(
                        "feature",
                        "extrude",
                        "--model",
                        "block",
                        "--request",
                        self.request(body, "bad.json"),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )


class SweepOptions(Built):
    """A sweep as a person makes one: a path of lines and arcs sketched on a plane, a section
    square to it where it starts, and where each lands said before it is built."""

    PATH = {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "start": [0, 0],
        "segments": [{"to": [0, 40]}, {"to": [20, 60], "sweep": -90}, {"to": [60, 60]}],
    }

    def sweep(self, body, *flags, status=0):
        return self.cli(
            "feature",
            "sweep",
            "--model",
            "block",
            "--request",
            self.request(body, "sweep.json"),
            *flags,
            status=status,
        )

    def build(self, body):
        return self.gated(
            "feature", "sweep", "--model", "block", "--request", self.request(body, "sweep.json")
        )["data"]

    def test_a_pipe_previewed_then_built(self):
        self.part()
        body = {
            "units": "mm",
            "name": "PIPE",
            "path": self.PATH,
            "section": {"type": "circle", "diameter": 10},
        }
        preview = domain_preview(self.sweep(body, "--dry-run")["data"]["preview"])
        path, section = preview["path"], preview["section"]
        length = 80 + 10 * math.pi
        self.assertAlmostEqual(path["length"], length)
        self.assertEqual(path["turns_deg"], -90.0)
        self.assertEqual(path["references"], ["RIGHT", "TOP"])
        self.assertEqual((path["starts_at"], path["ends_at"]), ([0, 0, 0], [60, 60, 0]))
        self.assertEqual(path["made_as"], "a sketched datum curve, PIPE_PATH")
        # Square to the path where it starts: up is the plane's normal, x the path's left.
        self.assertEqual(
            (section["frame"]["x"], section["frame"]["y"], section["frame"]["normal"]),
            ([-1, 0, 0], [0, 0, 1], [0, 1, 0]),
        )
        self.assertAlmostEqual(preview["expected_volume_change"], 25 * math.pi * length)
        data = self.build(body)
        self.checks_pass(data)
        checks = [c["check"] for c in data["verification"]["checks"]]
        self.assertIn("path_made", checks)
        self.assertIn("path_starts_where_previewed", checks)
        self.assertEqual(data["result"]["path"]["name"], "PIPE_PATH")
        # Its arc turns clockwise: Creo runs it from the far end, and says so.
        self.assertEqual(data["result"]["path"]["creo_runs_from"], "end")
        self.assertTrue(data["result"]["volume"]["matches_request"])
        sent = [q for n, q in self.world.events if n == "feature.sweep"][-1]
        self.assertEqual(sent["path"]["segments"], self.PATH["segments"])
        self.assertNotIn("units", sent)

    def test_where_an_off_centre_section_goes(self):
        # Left of a path that turns right, a section travels the outside of the turn: Pappus
        # adds its offset times the turn.
        self.part()
        body = {
            "units": "mm",
            "path": self.PATH | {"segments": [{"to": [20, 20], "sweep": -90}]},
            "section": {"type": "rectangle", "width": 2, "height": 2, "center": [5, 0]},
        }
        preview = domain_preview(self.sweep(body, "--dry-run")["data"]["preview"])
        # An arc first: the path starts along its tangent, the chord turned back half the arc.
        self.assertEqual(preview["section"]["frame"]["normal"], [0, 1, 0])
        self.assertAlmostEqual(
            preview["expected_volume_change"], 4 * (10 * math.pi + 5 * math.pi / 2)
        )
        self.checks_pass(self.build(body))

    def test_a_groove_cut_along_a_face(self):
        self.block()
        top = self.top()["ref"]
        body = {
            "units": "mm",
            "name": "GROOVE",
            "material": "remove",
            "path": {
                "plane": top,
                "orient_ref": "RIGHT",
                "start": [-15, -5],
                "segments": [{"to": [0, -5]}, {"to": [5, 0], "sweep": 90}, {"to": [5, 5]}],
            },
            "section": {"type": "circle", "diameter": 2},
        }
        preview = domain_preview(self.sweep(body, "--dry-run")["data"]["preview"])
        self.assertEqual(preview["path"]["references"], ["RIGHT", "TOP"])
        self.assertEqual(preview["feature"]["body"], "all")
        self.assertLess(preview["expected_volume_change"], 0)
        data = self.build(body)
        self.checks_pass(data)
        self.assertEqual(data["result"]["feature"]["type"], "FEATTYPE_CUT")
        self.assertEqual(data["result"]["path"]["creo_runs_from"], "start")

    def test_what_a_sweep_cannot_be(self):
        self.block()
        good = {"units": "mm", "path": self.PATH, "section": {"type": "circle", "diameter": 10}}
        corner = self.PATH | {"segments": [{"to": [0, 40]}, {"to": [40, 40]}]}
        closed = self.PATH | {
            "segments": [{"to": [20, 20], "sweep": -180}, {"to": [0, 0], "sweep": -180}]
        }
        crossing = self.PATH | {
            "segments": [
                {"to": [0, 40]},
                {"to": [20, 40], "sweep": -180},
                {"to": [20, 20]},
                {"to": [-10, 20], "sweep": -180},
                {"to": [-10, 30]},
                {"to": [30, 30], "sweep": -180},
            ]
        }
        holed = {"type": "circle", "diameter": 10, "holes": [{"type": "circle", "diameter": 2}]}
        for body, code, status, where in (
            (good | {"path": corner}, "E_VALIDATION", 2, "request.path.segments[1]"),
            (good | {"path": closed}, "E_VALIDATION", 2, "request.path"),
            (good | {"path": crossing}, "E_VALIDATION", 2, "request.path"),
            (
                good | {"section": {"type": "circle", "diameter": 50}},
                "E_VALIDATION",
                2,
                "request.path.segments[1]",
            ),
            (
                good | {"section": {"type": "ellipse", "x_radius": 3, "y_radius": 2}},
                "E_VALIDATION",
                2,
                "request.section.type",
            ),
            (good | {"section": holed}, "E_VALIDATION", 2, "request.section.holes"),
            (
                good | {"path": self.PATH | {"segments": [{"to": [0, 0]}]}},
                "E_VALIDATION",
                2,
                "request.path.segments[0]",
            ),
            (good | {"path": self.PATH | {"plane": "NOPE"}}, "E_NOT_FOUND", 3, None),
            (good | {"path": self.PATH | {"orient_ref": "FRONT"}}, "E_VALIDATION", 2, None),
            (good | {"material": "both"}, "E_VALIDATION", 2, None),
            ({"units": "mm", "path": self.PATH}, "E_VALIDATION", 2, None),
        ):
            with self.subTest(body=body):
                error = self.sweep(body, "--dry-run", status=status)["error"]
                self.assertEqual(error["code"], code)
                if where:
                    self.assertEqual(error["details"]["path"], where)

    def test_a_plane_of_its_own_names_its_references(self):
        self.part()
        self.gated(
            "feature",
            "datum-plane",
            "--model",
            "block",
            "--request",
            self.request(
                {"units": "mm", "name": "SHIFTED", "offset": {"from": "FRONT", "distance": 5}},
                "plane.json",
            ),
        )
        body = {
            "units": "mm",
            "path": self.PATH | {"plane": "SHIFTED"},
            "section": {"type": "circle", "diameter": 10},
        }
        error = self.sweep(body, "--dry-run", status=2)["error"]
        self.assertEqual(error["details"]["path"], "request.path.references")
        body["path"] = body["path"] | {"references": ["RIGHT", "TOP"]}
        self.checks_pass(self.build(body))
