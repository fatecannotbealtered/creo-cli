"""The host's sketch checks and the program it writes for the C library, without Creo.

plugin/source/.../host/core/Sketch.java uses no Creo classes; tests/host/SketchCheck.java runs it
on a sketch with the planes of a part from the metric template. Skipped without a JDK 22 or later.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_host_protocol import CORE, NO_WINDOW, ROOT, find_jdk

BODY = {
    "plane": "TOP", "x_axis": "+x", "references": ["RIGHT", "FRONT"],
    "entities": [{"id": "body", "type": "rectangle", "width_mm": 280, "height_mm": 55, "corner_radius_mm": 8}],
    "constraints": [{"type": "symmetric", "entity": "body", "about": "RIGHT"},
                    {"type": "symmetric", "entity": "body", "about": "FRONT"}],
    "dimensions": [{"name": "BODY_LENGTH", "measure": "body.width"}, {"name": "BODY_WIDTH", "measure": "body.height"},
                   {"name": "CORNER_R", "measure": "body.corner_radius"}],
}


class SketchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        jdk = find_jdk()
        if jdk is None:
            raise unittest.SkipTest("no JDK 22 or later found")
        cls.work = Path(tempfile.mkdtemp(prefix="creo-cli-sketch-test-"))
        cls.java = jdk / "bin" / "java"
        sources = [str(p) for p in CORE.glob("*.java")] + [str(ROOT / "tests" / "host" / "SketchCheck.java")]
        subprocess.run([str(jdk / "bin" / "javac"), "--release", "22", "-encoding", "UTF-8", "-d", str(cls.work / "classes"), *sources],
                       check=True, capture_output=True, creationflags=NO_WINDOW)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.work, ignore_errors=True)

    def check(self, sketch: dict) -> dict:
        path = self.work / "sketch.json"
        path.write_text(json.dumps(sketch), encoding="utf-8")
        out = subprocess.run([str(self.java), "-cp", str(self.work / "classes"), "SketchCheck", str(path)],
                             capture_output=True, text=True, encoding="utf-8", check=True, creationflags=NO_WINDOW)
        return json.loads(out.stdout)

    def lines(self, sketch: dict) -> list[str]:
        out = self.check(sketch)
        self.assertEqual(out["problems"], [])
        return out["program"].strip().splitlines()

    def test_a_symmetric_rounded_rectangle_is_fully_defined(self) -> None:
        lines = self.lines(BODY)
        self.assertEqual(lines[0], "frame 0.000000000 0.000000000 0.000000000 1.000000000 0.000000000 0.000000000 0.000000000 0.000000000 -1.000000000")
        self.assertIn("ref RIGHT 1", lines)
        self.assertIn("ref FRONT 3", lines)
        self.assertIn("line body.bottom -132.0000000 -27.50000000 132.0000000 -27.50000000", lines)
        self.assertIn("con 9 body.vaxis RIGHT", lines)
        self.assertIn("con 9 body.haxis FRONT", lines)
        self.assertEqual(sum(1 for line in lines if line.startswith("con 4 ")), 8, "a tangency at each corner's two ends")
        self.assertTrue(any(line.startswith("dim BODY_LENGTH 5 280.0000000 ") and line.endswith(" body.left body.right") for line in lines))
        self.assertTrue(any(line.startswith("dim CORNER_R 3 8.000000000 ") and line.endswith(" body.c2") for line in lines))

    def test_the_named_dimensions_and_their_values_are_listed(self) -> None:
        self.assertEqual(self.check(BODY)["named"], {"BODY_LENGTH": 280.0, "BODY_WIDTH": 55.0, "CORNER_R": 8.0})

    def test_a_profile_without_a_position_is_not_fully_defined(self) -> None:
        loose = dict(BODY, constraints=[{"type": "symmetric", "entity": "body", "about": "FRONT"}])
        problems = self.check(loose)["problems"]
        self.assertEqual(len(problems), 1)
        self.assertIn("body is not fully defined: nothing fixes its x position", problems[0])

    def test_a_distance_to_the_center_places_and_fixes_the_profile(self) -> None:
        socket = {
            "plane": "TOP_22", "x_axis": "+x", "references": ["RIGHT", "FRONT"],
            "entities": [{"id": "socket", "type": "rectangle", "width_mm": 36, "height_mm": 36, "corner_radius_mm": 3}],
            "constraints": [{"type": "symmetric", "entity": "socket", "about": "FRONT"},
                            {"type": "equal", "a": "socket.left", "b": "socket.bottom"}],
            "dimensions": [{"name": "SOCKET_SIZE", "measure": "socket.width"}, {"measure": "socket.corner_radius"},
                           {"name": "SOCKET_X", "from": "RIGHT", "to": "socket.center", "value_mm": -102}],
        }
        lines = self.lines(socket)
        self.assertTrue(lines[0].startswith("frame 0.000000000 22.00000000 0.000000000 "), "the frame sits on the plane, over the origin")
        self.assertIn("line socket.bottom -117.0000000 -18.00000000 -87.00000000 -18.00000000", lines)
        self.assertIn("con 8 socket.left socket.bottom", lines, "equal sides make it a square")
        self.assertTrue(any(line.startswith("dim SOCKET_X 5 102.0000000 ") and line.endswith(" RIGHT socket.vaxis") for line in lines))
        self.assertTrue(any(line.startswith("dim - 3 3.000000000 ") for line in lines), "an unnamed dimension keeps Creo's name")

    def test_a_circle_is_placed_by_its_center(self) -> None:
        boss = {
            "plane": "TOP", "x_axis": "+x", "references": ["RIGHT", "FRONT"],
            "entities": [{"id": "boss", "type": "circle", "diameter_mm": 6}],
            "dimensions": [{"name": "BOSS_D", "measure": "boss.diameter"},
                           {"from": "RIGHT", "to": "boss.center", "value_mm": 132},
                           {"from": "FRONT", "to": "boss.center", "value_mm": -19.5}],
        }
        lines = self.lines(boss)
        self.assertIn("circle boss 132.0000000 -19.50000000 3.000000000", lines)
        self.assertTrue(any(line.startswith("dim - 2 132.0000000 ") and line.endswith(" RIGHT boss:center") for line in lines))

    def test_an_x_axis_out_of_the_plane_is_refused(self) -> None:
        out = self.check(dict(BODY, x_axis="+y"))
        self.assertEqual(out["error"], "E_VALIDATION")
        self.assertIn("does not lie in the plane", out["message"])

    def test_a_reference_parallel_to_the_plane_is_a_problem(self) -> None:
        out = self.check(dict(BODY, references=["RIGHT", "FRONT", "TOP_22"]))
        self.assertTrue(any("TOP_22 is parallel to the sketch plane" in p for p in out["problems"]))

    def test_unknown_names_are_problems(self) -> None:
        out = self.check(dict(BODY, dimensions=BODY["dimensions"] + [{"name": "X", "measure": "lid.width"}]))
        self.assertTrue(any("names lid, which the sketch does not have" in p for p in out["problems"]))

    def test_dimension_names_are_unique(self) -> None:
        out = self.check(dict(BODY, dimensions=BODY["dimensions"] + [{"name": "body_length", "measure": "body.width"}]))
        self.assertTrue(any("Two dimensions are named body_length" in p for p in out["problems"]))

    def test_a_corner_radius_must_fit(self) -> None:
        wide = json.loads(json.dumps(BODY))
        wide["entities"][0]["corner_radius_mm"] = 30
        self.assertTrue(any("less than half its shorter side" in p for p in self.check(wide)["problems"]))

    def test_raw_entities_are_written_as_given(self) -> None:
        cap = {
            "plane": "FRONT", "x_axis": "+x", "references": ["RIGHT", "TOP"],
            "entities": [{"id": "floor", "type": "line", "start_mm": [-9.3, 0], "end_mm": [9.3, 0]},
                         {"id": "roof", "type": "arc", "center_mm": [0, -22], "radius_mm": 30, "start_deg": 72, "end_deg": 108}],
            "constraints": [{"type": "horizontal", "entity": "floor"}, {"type": "on", "point": "floor.start", "entity": "TOP"}],
            "dimensions": [{"name": "CAP_R", "measure": "roof.radius"}, {"name": "CAP_L", "measure": "floor.length"}],
        }
        lines = self.lines(cap)
        self.assertIn("line floor -9.300000000 0.000000000 9.300000000 0.000000000", lines)
        self.assertIn("con 3 floor:start TOP", lines)
        self.assertTrue(any(line.startswith("arc roof 0.000000000 -22.00000000 30.00000000 1.256637") for line in lines))


if __name__ == "__main__":
    unittest.main()
