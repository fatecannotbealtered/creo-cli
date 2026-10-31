"""Command-level tests for the P2 commands: geometry, dimensions, parameters, materials, render,
export, and the features placed on existing geometry -- against the loopback substitute."""

from __future__ import annotations

import json
import math
from pathlib import Path

from tests.fixture import INCH
from tests.test_commands import RECT, Base, domain_preview

SHAFT = {
    "units": "mm",
    "name": "SHAFT",
    "angle": 360,
    "axis": [[0, 0], [0, 1]],
    "sketch": {
        "plane": "FRONT",
        "orient_ref": "RIGHT",
        "profile": {
            "type": "polygon",
            "points": [[0, 0], [10, 0], [10, 20], [6, 20], [6, 40], [0, 40]],
        },
    },
}


class Built(Base):
    """A part with a 40 x 20 x 10 block, as most placed features need one."""

    def block(self):
        self.part()
        self.world.active = "block.prt"  # This helper represents a displayed native test part.
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        return self.world.models["block.prt"]

    def edges(self, direction=None):
        items = self.cli("geometry", "list", "--model", "block", "--kind", "edge")["data"]["items"]
        if direction is None:
            return items
        return [e for e in items if e.get("direction") == direction]

    def top(self):
        faces = self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
            "items"
        ]
        return next(f for f in faces if f.get("normal") == [0, 0, 1])

    def checks_pass(self, data):
        self.assertEqual(data["status"], "completed")
        failed = [c for c in data["verification"]["checks"] if not c["passed"]]
        self.assertEqual(failed, [])


class Geometry(Built):
    def test_list_filters_and_orders(self):
        self.block()
        data = self.cli("geometry", "list", "--model", "block")["data"]
        kinds = [i["kind"] for i in data["items"]]
        self.assertEqual(kinds[:3], ["datum_plane"] * 3)
        self.assertEqual(kinds.count("surface"), 6)
        self.assertEqual(kinds.count("edge"), 12)
        self.assertTrue(all(isinstance(i["id"], str) for i in data["items"]))
        edges = self.edges()
        self.assertEqual(len(edges), 12)
        self.assertEqual(len(self.edges([0, 0, -1])), 4)
        by_feature = self.cli("geometry", "list", "--model", "block", "--feature", "BLOCK")["data"]
        self.assertEqual(by_feature["total"], 18)
        planes = self.cli(
            "geometry", "list", "--model", "block", "--type", "plane", "--fields", "ref"
        )
        self.assertEqual(planes["data"]["total"], 9)
        self.assertEqual(
            self.cli("geometry", "list", "--model", "block", "--kind", "vertex", status=2)["error"][
                "code"
            ],
            "E_USAGE",
        )

    def test_picked_by_where_it_is(self):
        self.block()
        # The nearest geometry first, each with its distance: an edge exactly, a face from its box.
        near = self.cli(
            "geometry",
            "list",
            "--model",
            "block",
            "--kind",
            "edge",
            "--near",
            "20,10,-5",
            "--limit",
            "3",
        )["data"]["items"]
        self.assertEqual(near[0]["distance"], 0.0)
        self.assertEqual(near[0]["direction"] in ([0, 0, 1], [0, 0, -1]), True)
        self.assertTrue(
            all(a["distance"] <= b["distance"] for a, b in zip(near, near[1:], strict=False))
        )
        faces = self.cli(
            "geometry", "list", "--model", "block", "--kind", "surface", "--near", "0,0,-30"
        )["data"]["items"]
        self.assertEqual((faces[0]["normal"], faces[0]["distance"]), ([0, 0, -1], 20.0))
        self.assertEqual(
            self.cli("geometry", "list", "--model", "block", "--near", "1,2", status=2)["error"][
                "code"
            ],
            "E_VALIDATION",
        )

    def test_measure(self):
        self.block()
        top = self.top()
        data = self.cli(
            "geometry", "distance", "--model", "block", "--from", top["ref"], "--to", "FRONT"
        )["data"]
        self.assertEqual(data["distance"], 0.0)
        bottom = next(
            f
            for f in self.cli("geometry", "list", "--model", "block", "--kind", "surface")["data"][
                "items"
            ]
            if f.get("normal") == [0, 0, -1]
        )
        gap = self.cli(
            "geometry", "distance", "--model", "block", "--from", top["ref"], "--to", bottom["ref"]
        )["data"]
        self.assertEqual(gap["distance"], 10.0)
        self.assertEqual(
            self.cli(
                "geometry",
                "distance",
                "--model",
                "block",
                "--from",
                "x y",
                "--to",
                "FRONT",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )


class Dimensions(Built):
    def test_list_hides_placeholders_and_set_reads_back(self):
        self.block()
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        self.assertEqual([d["value"] for d in dims], [40.0, 20.0, 10.0])
        self.assertTrue(all(d["type"] for d in dims))
        depth = dims[2]["name"]
        data = self.gated(
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
        )["data"]
        self.checks_pass(data)
        self.assertEqual(data["result"]["dimension"]["value"], 12.0)
        self.assertAlmostEqual(data["result"]["volume"]["after"], 9600.0)
        one = self.cli("dimension", "list", "--model", "block", "--feature", "BLOCK")["data"]
        self.assertEqual(one["total"], 3)

    def test_units_mismatch_refused_and_failed_regeneration_is_unchanged(self):
        self.block()
        depth = self.cli("dimension", "list", "--model", "block")["data"]["items"][2]["name"]
        mismatch = self.cli(
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            depth,
            "--value",
            1,
            "--units",
            "in",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(mismatch["code"], "E_CONFLICT")
        failed = self.gated(
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            depth,
            "--value",
            -1,
            "--units",
            "mm",
            status=1,
        )["error"]
        self.assertEqual(failed["code"], "E_NATIVE_FAILURE")
        self.assertEqual(failed["details"]["receipt_status"], "failed_unchanged")
        missing = self.cli(
            "dimension",
            "set",
            "--model",
            "block",
            "--dimension",
            "d99",
            "--value",
            1,
            "--units",
            "mm",
            "--dry-run",
            status=3,
        )["error"]
        self.assertIn("dimension list", missing["details"]["fix"])


class Parameters(Built):
    def test_list_set_create_and_type_rules(self):
        self.part()
        listed = self.cli("parameter", "list", "--model", "block")["data"]
        self.assertIn("DESCRIPTION", [p["name"] for p in listed["items"]])
        data = self.gated(
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "bracket",
        )["data"]
        self.checks_pass(data)
        created = self.gated(
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "REV",
            "--type",
            "integer",
            "--value",
            "3",
            "--create",
        )["data"]
        self.assertTrue(created["result"]["created"])
        self.assertEqual(created["result"]["parameter"]["value"], 3)
        self.assertEqual(
            self.cli(
                "parameter",
                "set",
                "--model",
                "block",
                "--name",
                "NEW",
                "--type",
                "string",
                "--value",
                "x",
                "--dry-run",
                status=3,
            )["error"]["code"],
            "E_NOT_FOUND",
        )
        self.assertEqual(
            self.cli(
                "parameter",
                "set",
                "--model",
                "block",
                "--name",
                "DESCRIPTION",
                "--type",
                "real",
                "--value",
                "1.5",
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        for bad in (("integer", "1.5"), ("boolean", "yes"), ("real", "nan")):
            with self.subTest(bad=bad):
                self.assertEqual(
                    self.cli(
                        "parameter",
                        "set",
                        "--model",
                        "block",
                        "--name",
                        "REV",
                        "--type",
                        bad[0],
                        "--value",
                        bad[1],
                        "--dry-run",
                        status=2,
                    )["error"]["code"],
                    "E_VALIDATION",
                )
        system = self.cli(
            "parameter",
            "set",
            "--model",
            "block",
            "--name",
            "PTC_MATERIAL_NAME",
            "--type",
            "string",
            "--value",
            "x",
            "--dry-run",
            status=2,
        )["error"]
        self.assertIn("PTC_", system["message"])


class Materials(Built):
    def test_list_and_assign(self):
        self.block()
        library = self.cli("material", "list", "--name", "steel")["data"]
        self.assertEqual(library["total"], 3)
        self.assertNotIn("model", library)
        with_model = self.cli("material", "list", "--model", "block", "--limit", 2)["data"]
        self.assertEqual(with_model["model"]["material"], "PTC_SYSTEM_MTRL_PROPS")
        self.assertTrue(with_model["has_more"])
        data = self.gated(
            "material", "assign", "--model", "block", "--material", "Steel_low_carbon"
        )["data"]
        self.checks_pass(data)
        mass = data["result"]["after"]["mass_properties"]["mass"]
        self.assertAlmostEqual(mass, 8000 * 7.85e-09)
        shown = self.cli("model", "show", "--model", "block")["data"]
        self.assertEqual(shown["material"], "STEEL_LOW_CARBON")
        self.assertAlmostEqual(shown["mass_properties"]["mass"], mass)
        missing = self.cli(
            "material",
            "assign",
            "--model",
            "block",
            "--material",
            "Unobtainium",
            "--dry-run",
            status=3,
        )["error"]
        self.assertIn("material list", missing["details"]["fix"])


class RenderAndExport(Built):
    def test_render_writes_a_jpeg(self):
        self.block()
        data = self.gated(
            "artifact",
            "render",
            "--model",
            "block",
            "--output",
            "block.jpg",
            "--view",
            "front",
            "--width",
            320,
            "--height",
            200,
        )["data"]["result"]
        picture = Path(data["file"])
        self.assertTrue(picture.is_file())
        self.assertEqual(picture.read_bytes()[:2], b"\xff\xd8")
        self.assertEqual(picture.parent, self.ws)
        self.assertEqual(data["view"], "front")
        self.assertEqual(
            self.cli(
                "artifact",
                "render",
                "--model",
                "block",
                "--output",
                "bad.jpg",
                "--width",
                10,
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_export_publishes_without_overwriting(self):
        self.block()
        (self.ws / "exports").mkdir()
        for output, magic in (
            ("exports/block.stp", b"ISO-10303-21"),
            ("exports/block.igs", b"SUBSTITUTE"),
            ("exports/block.stl", b"solid"),
        ):
            with self.subTest(output=output):
                data = self.gated("artifact", "export", "--model", "block", "--output", output)[
                    "data"
                ]
                self.checks_pass(data)
                self.assertTrue(data["persisted"])
                written = Path(data["result"]["file"])
                self.assertEqual(written, self.ws / output)
                self.assertTrue(written.read_bytes().startswith(magic))
        stages = list((self.ws / ".creo-cli" / "staging").iterdir())
        self.assertEqual(3, len(stages))
        for stage in stages:
            retained = [file for file in stage.iterdir() if file.suffix in (".stp", ".igs", ".stl")]
            self.assertEqual(1, len(retained))
            self.assertTrue(retained[0].samefile(self.ws / "exports" / retained[0].name))
        again = self.cli(
            "artifact",
            "export",
            "--model",
            "block",
            "--output",
            "exports/block.stp",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(again["code"], "E_CONFLICT")
        for output, code, status in (
            ("exports/block.txt", "E_VALIDATION", 2),
            ("exports/block.pdf", "E_VALIDATION", 2),
            ("nowhere/block.stp", "E_NOT_FOUND", 3),
            ("../outside.stp", "E_FORBIDDEN", 4),
        ):
            with self.subTest(output=output):
                self.assertEqual(
                    self.cli(
                        "artifact",
                        "export",
                        "--model",
                        "block",
                        "--output",
                        output,
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )


class Revolve(Built):
    def test_revolve_matches_pappus(self):
        self.part("shaft.prt")
        preview = domain_preview(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(SHAFT),
                "--dry-run",
            )["data"]["preview"]
        )
        self.assertAlmostEqual(preview["expected_volume_change"], math.pi * 2720)
        self.assertEqual(preview["sketch"]["drawn_by"], "native")
        data = self.gated(
            "feature", "revolve", "--model", "shaft", "--request", self.request(SHAFT)
        )["data"]
        self.checks_pass(data)
        self.assertTrue(data["result"]["volume"]["matches_request"])

    def test_profile_crossing_the_axis_and_missing_library_refused(self):
        self.part("shaft.prt")
        crossing = SHAFT | {"axis": [[5, 0], [5, 1]]}
        self.assertEqual(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(crossing),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.world.native = False
        self.assertEqual(
            self.cli(
                "feature",
                "revolve",
                "--model",
                "shaft",
                "--request",
                self.request(SHAFT),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_UNSUPPORTED",
        )


class Datums(Built):
    def test_offset_plane_and_axis(self):
        self.block()
        plane = self.gated(
            "feature",
            "datum-plane",
            "--model",
            "block",
            "--request",
            self.request(
                {"units": "mm", "name": "MID", "offset": {"from": "FRONT", "distance": -5}}
            ),
        )["data"]
        self.checks_pass(plane)
        self.assertEqual(plane["result"]["geometry"]["origin"], [0.0, 0.0, -5.0])
        self.assertIn("MID", self.cli("model", "show", "--model", "block")["data"]["datum_planes"])
        axis = self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "ZAXIS", "through": ["RIGHT", "TOP"]}),
        )["data"]
        self.checks_pass(axis)
        self.assertEqual(axis["result"]["feature"]["type"], "FEATTYPE_DATUM_AXIS")

    def test_requests_are_checked_before_creo(self):
        self.block()
        for body, code, status in (
            (
                {
                    "units": "mm",
                    "offset": {"from": "FRONT", "distance": 1},
                    "angle": {"through": "A_1", "from": "TOP", "degrees": 30},
                },
                "E_VALIDATION",
                2,
            ),
            ({"units": "mm", "offset": {"from": "NOWHERE", "distance": 1}}, "E_NOT_FOUND", 3),
            ({"units": "in", "offset": {"from": "FRONT", "distance": 1}}, "E_CONFLICT", 6),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "datum-plane",
                        "--model",
                        "block",
                        "--request",
                        self.request(body),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )


class EdgesHolesShells(Built):
    def test_round_estimate_matches_straight_edges(self):
        self.block()
        vertical = [e["ref"] for e in self.edges([0, 0, -1])]
        body = {"units": "mm", "name": "CORNERS", "radius": 3, "edges": vertical}
        preview = domain_preview(
            self.cli(
                "feature", "round", "--model", "block", "--request", self.request(body), "--dry-run"
            )["data"]["preview"]
        )
        self.assertAlmostEqual(preview["estimated_volume_change"], -(1 - math.pi / 4) * 9 * 40)
        self.assertEqual(sorted(preview["edges"]), sorted(vertical))
        data = self.gated("feature", "round", "--model", "block", "--request", self.request(body))[
            "data"
        ]
        self.checks_pass(data)
        self.assertTrue(data["result"]["volume"]["matches_request"])

    def test_chamfer_and_bad_edges(self):
        self.block()
        edge = self.edges([1, 0, 0])[0]["ref"]
        body = {"units": "mm", "distance": 1, "edges": [edge]}
        data = self.gated(
            "feature", "chamfer", "--model", "block", "--request", self.request(body)
        )["data"]
        self.checks_pass(data)
        self.assertAlmostEqual(data["result"]["volume"]["change"], -0.5 * 40)
        for edges, code, status in (
            (["surface:1001"], "E_VALIDATION", 2),
            ([edge, edge], "E_VALIDATION", 2),
            (["edge:999999"], "E_NOT_FOUND", 3),
        ):
            with self.subTest(edges=edges):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "chamfer",
                        "--model",
                        "block",
                        "--request",
                        self.request(body | {"edges": edges}),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )

    def test_hole_blind_and_through(self):
        self.block()
        top = self.top()["ref"]
        blind = {
            "units": "mm",
            "name": "H1",
            "diameter": 4,
            "depth": 5,
            "placement": {
                "surface": top,
                "offsets": [{"from": "RIGHT", "distance": 10}, {"from": "TOP", "distance": 3}],
            },
        }
        data = self.gated("feature", "hole", "--model", "block", "--request", self.request(blind))[
            "data"
        ]
        self.checks_pass(data)
        self.assertAlmostEqual(data["result"]["volume"]["expected_change"], -math.pi * 4 * 5)
        # A plain hole says what was drilled, as a shaped one does.
        self.assertEqual(
            {k: data["result"][k] for k in ("drill_diameter", "depth", "placement")},
            {"drill_diameter": 4, "depth": 5, "placement": "linear"},
        )
        self.assertIn(
            "drilled_to_the_diameter", [c["check"] for c in data["verification"]["checks"]]
        )
        through = blind | {"name": "H2", "depth": "through_all"}
        data = self.gated(
            "feature", "hole", "--model", "block", "--request", self.request(through)
        )["data"]
        self.checks_pass(data)
        self.assertNotIn("expected_change", data["result"]["volume"])
        same = blind | {
            "name": "H3",
            "placement": {
                "surface": top,
                "offsets": [{"from": top, "distance": 1}, {"from": "TOP", "distance": 1}],
            },
        }
        self.assertEqual(
            self.cli(
                "feature",
                "hole",
                "--model",
                "block",
                "--request",
                self.request(same),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )

    def test_holes_on_a_bolt_circle_and_on_an_axis(self):
        # A flange's bolt holes go on a circle about its axis, which its drawing then gives as
        # the circle's diameter; its bore goes on the axis itself, needing no dimension.
        self.block()
        top = self.top()["ref"]
        self.gated(
            "feature",
            "datum-axis",
            "--model",
            "block",
            "--request",
            self.request({"name": "MID", "through": ["RIGHT", "FRONT"]}),
        )
        bolt = {
            "units": "mm",
            "name": "BOLT",
            "diameter": 4,
            "depth": "through_all",
            "placement": {"surface": top, "axis": "MID", "diameter": 12, "angle_from": "RIGHT"},
        }
        dry = domain_preview(
            self.cli(
                "feature", "hole", "--model", "block", "--request", self.request(bolt), "--dry-run"
            )["data"]["preview"]
        )["placement"]
        self.assertEqual(
            (dry["how"], dry["diameter"], dry["axis"]["kind"]), ("bolt_circle", 12, "axis")
        )
        data = self.gated("feature", "hole", "--model", "block", "--request", self.request(bolt))[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(data["result"]["placement"], "bolt_circle")
        circle = next(
            c for c in data["verification"]["checks"] if c["check"] == "on_the_bolt_circle"
        )
        self.assertAlmostEqual(circle["distance_from_axis"], 6)
        bore = bolt | {"name": "BORE", "diameter": 3, "placement": {"surface": top, "axis": "MID"}}
        data = self.gated("feature", "hole", "--model", "block", "--request", self.request(bore))[
            "data"
        ]
        self.checks_pass(data)
        self.assertEqual(data["result"]["placement"], "coaxial")
        self.assertIn("on_the_axis", [c["check"] for c in data["verification"]["checks"]])
        for placement, code in (
            ({"surface": top, "axis": "MID", "diameter": 12}, "E_VALIDATION"),
            (
                {
                    "surface": top,
                    "axis": "MID",
                    "offsets": [{"from": "RIGHT", "distance": 1}, {"from": "TOP", "distance": 1}],
                },
                "E_VALIDATION",
            ),
            ({"surface": top, "axis": top}, "E_VALIDATION"),
            ({"surface": top, "axis": "RIGHT"}, "E_VALIDATION"),
            ({"surface": top, "axis": "MID", "diameter": 12, "angle_from": "MID"}, "E_VALIDATION"),
            ({"surface": top}, "E_VALIDATION"),
        ):
            with self.subTest(placement=placement):
                self.assertEqual(
                    self.cli(
                        "feature",
                        "hole",
                        "--model",
                        "block",
                        "--request",
                        self.request(bolt | {"name": "BAD", "placement": placement}, "bad.json"),
                        "--dry-run",
                        status=2,
                    )["error"]["code"],
                    code,
                )

    def test_shell_removes_material(self):
        self.block()
        body = {"units": "mm", "name": "HOLLOW", "thickness": 1.5, "remove": [self.top()["ref"]]}
        data = self.gated("feature", "shell", "--model", "block", "--request", self.request(body))[
            "data"
        ]
        self.checks_pass(data)
        self.assertLess(data["result"]["volume"]["change"], 0)
        edge = self.edges()[0]["ref"]
        self.assertEqual(
            self.cli(
                "feature",
                "shell",
                "--model",
                "block",
                "--request",
                self.request(body | {"name": "X", "remove": [edge]}),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )


class PatternsAndMirror(Built):
    def test_direction_pattern_counts_instances(self):
        self.block()
        top = self.top()["ref"]
        hole = {
            "units": "mm",
            "name": "H1",
            "diameter": 2,
            "depth": "through_all",
            "placement": {
                "surface": top,
                "offsets": [{"from": "RIGHT", "distance": -15}, {"from": "TOP", "distance": 0}],
            },
        }
        self.gated("feature", "hole", "--model", "block", "--request", self.request(hole))
        body = {
            "units": "mm",
            "name": "ROW",
            "feature": "H1",
            "direction": {"along": "RIGHT", "spacing": 10, "count": 4},
        }
        data = self.gated(
            "feature", "pattern", "--model", "block", "--request", self.request(body)
        )["data"]
        self.checks_pass(data)
        self.assertEqual(len(data["result"]["members"]), 4)
        self.assertEqual(data["result"]["feature"]["type"], "FEATTYPE_PATTERN_HEAD")
        both = body | {"name": "X", "axis": {"about": "A_1", "angle": 90, "count": 4}}
        self.assertEqual(
            self.cli(
                "feature",
                "pattern",
                "--model",
                "block",
                "--request",
                self.request(both),
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(
                "feature",
                "pattern",
                "--model",
                "block",
                "--request",
                self.request(body | {"name": "Y", "feature": "NOPE"}),
                "--dry-run",
                status=3,
            )["error"]["code"],
            "E_NOT_FOUND",
        )

    def test_mirror_doubles_the_part(self):
        self.block()
        data = self.gated(
            "feature", "mirror-part", "--model", "block", "--plane", "FRONT", "--name", "MIR"
        )["data"]
        self.checks_pass(data)
        self.assertTrue(data["result"]["volume"]["matches_request"])
        edge = self.edges()[0]["ref"]
        self.assertEqual(
            self.cli(
                "feature", "mirror-part", "--model", "block", "--plane", edge, "--dry-run", status=2
            )["error"]["code"],
            "E_VALIDATION",
        )


class TreeEdits(Built):
    def test_suppress_resume_rename(self):
        self.block()
        suppressed = self.gated("feature", "suppress", "--model", "block", "--feature", "BLOCK")[
            "data"
        ]
        self.checks_pass(suppressed)
        self.assertEqual(suppressed["result"]["volume"]["after"], 0.0)
        again = self.cli(
            "feature", "suppress", "--model", "block", "--feature", "BLOCK", "--dry-run", status=6
        )["error"]
        self.assertEqual(again["code"], "E_CONFLICT")
        resumed = self.gated("feature", "resume", "--model", "block", "--feature", "BLOCK")["data"]
        self.checks_pass(resumed)
        self.assertEqual(resumed["result"]["volume"]["after"], 8000.0)
        renamed = self.gated(
            "feature", "rename", "--model", "block", "--feature", "BLOCK", "--name", "BASE"
        )["data"]
        self.checks_pass(renamed)
        self.assertEqual(renamed["result"]["feature"]["name"], "BASE")
        taken = self.cli(
            "feature",
            "rename",
            "--model",
            "block",
            "--feature",
            "BASE",
            "--name",
            "TOP",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(taken["code"], "E_CONFLICT")
        self.assertEqual(
            self.cli(
                "feature",
                "rename",
                "--model",
                "block",
                "--feature",
                "BASE",
                "--name",
                "9x",
                "--dry-run",
                status=2,
            )["error"]["code"],
            "E_VALIDATION",
        )


class InchParts(Built):
    def test_millimetre_requests_refused_on_an_inch_part(self):
        self.part("imperial.prt", INCH)
        body = {"units": "mm", "name": "MID", "offset": {"from": "FRONT", "distance": 1}}
        self.assertEqual(
            self.cli(
                "feature",
                "datum-plane",
                "--model",
                "imperial",
                "--request",
                self.request(body),
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.assertEqual(json.loads(json.dumps(body))["units"], "mm")
