"""Independent synthetic OCCT consumer tests; these make no Creo claim or CAD calls."""

import datetime
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CONSUMER = Path(__file__).resolve().parents[1] / "scripts" / "consume_prism_step.py"
BUILDER = r"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve(strict=True)))
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopoDS import TopoDS_Compound

kind, output = sys.argv[2:]
depth = 9 if kind == "box9" else 6
xmin = -39 if kind == "wrong_position" else -40
shape = BRepPrimAPI_MakeBox(gp_Pnt(xmin, -25, -depth), gp_Pnt(xmin + 80, 25, 0)).Shape()
if kind == "hole":
    tool = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -7), gp_Dir(0, 0, 1)), 3, 8)
    cut = BRepAlgoAPI_Cut(shape, tool.Shape())
    cut.Build()
    assert cut.IsDone()
    shape = cut.Shape()
if kind in ("extra_solid", "loose_vertex"):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, shape)
    extra = (
        BRepPrimAPI_MakeBox(gp_Pnt(90, 0, 0), gp_Pnt(91, 1, 1)).Shape()
        if kind == "extra_solid"
        else BRepBuilderAPI_MakeVertex(gp_Pnt(90, 0, 0)).Vertex()
    )
    builder.Add(compound, extra)
    shape = compound
assert not Path(output).exists()
writer = STEPControl_Writer()
assert Interface_Static.SetCVal_s("write.step.unit", "M" if kind == "metre_units" else "MM")
assert writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone
if kind == "two_roots":
    second = BRepPrimAPI_MakeBox(gp_Pnt(90, 0, 0), gp_Pnt(100, 10, 10)).Shape()
    assert writer.Transfer(second, STEPControl_AsIs) == IFSelect_RetDone
assert writer.Write(output) == IFSelect_RetDone
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, directory, name):
    result = subprocess.run(
        command, capture_output=True, encoding="utf-8", errors="replace", timeout=90
    )
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
        stdout = directory / (name + ".stdout.log")
        stderr = directory / (name + ".stderr.log")
        stdout.write_text(result.stdout, encoding="utf-8")
        stderr.write_text(result.stderr, encoding="utf-8")
        record = {
            "kind": "independent synthetic consumer process; no CAD/native application",
            "command": command,
            "exit_code": result.returncode,
            "consumer_source_sha256": digest(CONSUMER),
            "test_source_sha256": digest(Path(__file__)),
            "stdout_sha256": digest(stdout),
            "stderr_sha256": digest(stderr),
            "files": {
                str(path): {"bytes": path.stat().st_size, "sha256": digest(path)}
                for path in sorted(directory.iterdir())
                if path.is_file() and path.suffix in (".step", ".json")
            },
        }
        with (directory / (name + ".call.json")).open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
    return result


class StepPrismConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        explicit = os.environ.get("CREO_PRISM_TEST_OCP_PATH")
        if explicit:
            cls.dependencies = Path(explicit)
        else:
            specification = importlib.util.find_spec("OCP")
            if specification is None or specification.origin is None:
                raise unittest.SkipTest(
                    "OCP unavailable: set CREO_PRISM_TEST_OCP_PATH to its declared module directory"
                )
            cls.dependencies = Path(specification.origin).parent.parent
        cls.temporary = tempfile.TemporaryDirectory(prefix="creo-independent-prism-")
        evidence = os.environ.get("CREO_PRISM_TEST_EVIDENCE_DIR")
        cls.root = Path(evidence) if evidence else Path(cls.temporary.name)
        if evidence:
            cls.root.mkdir(parents=True, exist_ok=False)
        probe = execute(
            [
                sys.executable,
                "-B",
                str(CONSUMER),
                "--python-path",
                str(cls.dependencies),
                "--probe",
            ],
            cls.root,
            "dependency-probe",
        )
        if probe.returncode:
            cls.temporary.cleanup()
            raise RuntimeError(
                "Explicit OCP dependency import failed: " + probe.stdout + probe.stderr
            )
        cls.probe = json.loads(probe.stdout)
        with (cls.root / "RUN.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "kind": "independent synthetic OCCT tests only; no Creo verification",
                    "started_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
                    "cad_calls": 0,
                    "consumer": str(CONSUMER),
                    "consumer_sha256": digest(CONSUMER),
                    "tests_sha256": digest(Path(__file__)),
                    "probe": cls.probe,
                },
                stream,
                indent=2,
            )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.directory = self.root / self._testMethodName
        self.directory.mkdir()

    def build(self, kind):
        path = self.directory / (kind + ".step")
        built = execute(
            [sys.executable, "-B", "-c", BUILDER, str(self.dependencies), kind, str(path)],
            self.directory,
            "build-" + kind,
        )
        self.assertEqual(0, built.returncode, built.stdout + built.stderr)
        return path

    def consume(self, source, depth=6, output=None):
        output = output or self.directory / "report.json"
        before = digest(source)
        result = execute(
            [
                sys.executable,
                "-B",
                str(CONSUMER),
                "--python-path",
                str(self.dependencies),
                "--input",
                str(source),
                "--output",
                str(output),
                "--expected-bounds",
                "-40",
                "-25",
                str(-depth),
                "40",
                "25",
                "0",
            ],
            self.directory,
            "consume",
        )
        self.assertEqual(before, digest(source), "consumer changed its input")
        return result, json.loads(output.read_text(encoding="utf-8"))

    def assert_rejected_shape(self, kind, failed_id, depth=6):
        result, report = self.consume(self.build(kind), depth)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", report["status"])
        self.assertIn(report["stage"], ("complete", "full_boundary_and_boolean_proof"))
        if report["stage"] != "complete":
            self.assertIn("error", report)
        self.assertIn(failed_id, [row["id"] for row in report["checks"] if not row["passed"]])
        self.assertEqual(digest(CONSUMER), report["consumer_source_sha256"])

    def test_probe_binds_actual_import(self):
        self.assertEqual("passed", self.probe["status"])
        self.assertEqual("dependency_probe", self.probe["mode"])
        self.assertNotIn("observed", self.probe)
        runtime = self.probe["runtime"]
        self.assertEqual(digest(Path(runtime["binary"])), runtime["binary_sha256"])
        self.assertEqual(
            digest(Path(runtime["python_executable"])), runtime["python_executable_sha256"]
        )
        Path(runtime["binary"]).resolve().relative_to(self.dependencies.resolve())
        self.assertEqual(
            str(self.dependencies.resolve()), runtime["explicit_module_search_directory"]
        )

    def test_complete_box6(self):
        source = self.build("box6")
        result, report = self.consume(source)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", report["status"])
        self.assertTrue(all(row["passed"] for row in report["checks"]))
        self.assertEqual(0, report["observed"]["load_diagnostics"]["warning_count"])
        self.assertTrue(report["observed"]["load_diagnostics"]["no_messages"])
        self.assertEqual(digest(source), report["input_sha256"])
        self.assertGreaterEqual(len(report["checks"]), 20)
        self.assertEqual(1, report["observed"]["topology"]["solids"])
        self.assertTrue(
            all(
                value["empty"]
                for value in report["observed"]["bidirectional_boolean_difference"].values()
            )
        )

    def test_complete_box9(self):
        result, report = self.consume(self.build("box9"), depth=9)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertAlmostEqual(36000, report["observed"]["volume_mm3"], places=4)
        self.assertAlmostEqual(10340, report["observed"]["surface_area_mm2"], places=4)

    def angular_unit_fixture(self, dimensions):
        """New synthetic box variants, never a repair of a retained Creo export.

        conversion_based_unit inherits explicit named_unit.dimensions, whereas
        si_unit redeclares it as derived (STEP Part 41). The explicit entity
        requirement also appears in OCCT V8_0_1's complex DEGREE reader:
        RWStepBasic_RWConversionBasedUnitAndPlaneAngleUnit::ReadStep.
        """
        source = self.build("box6")
        text = source.read_text(encoding="utf-8")
        angle_units = list(
            re.finditer(
                r"#(\d+)\s*=\s*\(\s*NAMED_UNIT\(\*\)\s*"
                r"PLANE_ANGLE_UNIT\(\)\s*SI_UNIT\(\$,\.RADIAN\.\)\s*\);",
                text,
            )
        )
        self.assertEqual(1, len(angle_units), "fixture needs one SI radian context unit")
        original_angle = angle_units[0]
        angle_id = original_angle.group(1)
        first_id = max(int(value) for value in re.findall(r"#(\d+)\s*=", text)) + 1
        dimension_id, factor_id, radian_id = (f"#{first_id + i}" for i in range(3))
        dimensions = {
            "explicit": dimension_id,
            "derived": "*",
            "omitted": "$",
            "missing_reference": "#999999",
            "wrong_entity_type": radian_id,
        }[dimensions]
        conversion = (
            f"#{angle_id} = ( CONVERSION_BASED_UNIT('DEGREE',{factor_id}) "
            f"NAMED_UNIT({dimensions}) PLANE_ANGLE_UNIT() );"
        )
        # Only the angular context unit changes. All box geometry and the SI
        # millimetre/steradian declarations remain the builder's original bytes.
        text = text[: original_angle.start()] + conversion + text[original_angle.end() :]
        extra = (
            f"{dimension_id} = DIMENSIONAL_EXPONENTS(0.,0.,0.,0.,0.,0.,0.);\n"
            f"{factor_id} = PLANE_ANGLE_MEASURE_WITH_UNIT("
            f"PLANE_ANGLE_MEASURE(0.017453292519943295),{radian_id});\n"
            f"{radian_id} = ( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) );\n"
        )
        position = text.rfind("ENDSEC;")
        self.assertGreater(position, original_angle.start())
        target = self.directory / "degree-variant.step"
        target.write_text(text[:position] + extra + text[position:], encoding="utf-8")
        return target

    def test_degree_conversion_explicit_dimensions_complete(self):
        result, report = self.consume(self.angular_unit_fixture("explicit"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("passed", report["status"])
        self.assertEqual("complete", report["stage"])
        self.assertTrue(report["observed"]["load_diagnostics"]["no_messages"])
        self.assertTrue(all(row["passed"] for row in report["checks"]))
        self.assertEqual(1, len(report["observed"]["root_transfers"]))
        self.assertEqual(1, report["observed"]["topology"]["solids"])

    def assert_degree_dimensions_rejected(self, dimensions):
        result, report = self.consume(self.angular_unit_fixture(dimensions))
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", report["status"])
        self.assertEqual("step_load_validation", report["stage"])
        load = report["observed"]["load_diagnostics"]
        self.assertFalse(load["no_failures"])
        self.assertGreater(load["failure_count"], 0)
        self.assertTrue(
            any("dimensions" in message for row in load["checks"] for message in row["failures"])
        )
        self.assertNotIn("root_transfers", report["observed"])
        self.assertNotIn("topology", report["observed"])

    def test_degree_conversion_derived_dimensions_rejected(self):
        self.assert_degree_dimensions_rejected("derived")

    def test_degree_conversion_omitted_dimensions_rejected(self):
        self.assert_degree_dimensions_rejected("omitted")

    def test_degree_conversion_missing_dimensions_reference_rejected(self):
        self.assert_degree_dimensions_rejected("missing_reference")

    def test_degree_conversion_wrong_dimensions_entity_type_rejected(self):
        self.assert_degree_dimensions_rejected("wrong_entity_type")

    def test_si_units_keep_derived_dimensions(self):
        source = self.build("box6")
        text = source.read_text(encoding="utf-8")
        self.assertRegex(
            text, r"LENGTH_UNIT\(\)\s*NAMED_UNIT\(\*\)\s*SI_UNIT\(\.MILLI\.,\.METRE\.\)"
        )
        self.assertRegex(
            text, r"NAMED_UNIT\(\*\)\s*PLANE_ANGLE_UNIT\(\)\s*SI_UNIT\(\$,\.RADIAN\.\)"
        )
        self.assertRegex(
            text, r"NAMED_UNIT\(\*\)\s*SI_UNIT\(\$,\.STERADIAN\.\)\s*SOLID_ANGLE_UNIT\(\)"
        )
        result, report = self.consume(source)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(report["observed"]["load_diagnostics"]["no_messages"])
        self.assertTrue(all(row["passed"] for row in report["checks"]))

    def test_same_volume_wrong_position_rejected(self):
        self.assert_rejected_shape("wrong_position", "bounds_match")

    def test_wrong_dimension_rejected(self):
        self.assert_rejected_shape("box6", "bounds_match", depth=9)

    def test_extra_solid_rejected(self):
        self.assert_rejected_shape("extra_solid", "one_valid_solid")

    def test_loose_vertex_rejected(self):
        self.assert_rejected_shape("loose_vertex", "no_loose_geometry")

    def test_cylindrical_cavity_rejected(self):
        self.assert_rejected_shape("hole", "one_closed_shell_six_faces_twelve_edges_eight_vertices")

    def test_non_mm_units_rejected(self):
        self.assert_rejected_shape("metre_units", "explicit_millimetre_file_units")

    def test_empty_input_rejected_with_bound_failure_report(self):
        source = self.directory / "empty.step"
        source.write_bytes(b"")
        result, report = self.consume(source)
        self.assertEqual(1, result.returncode)
        self.assertEqual("failed", report["status"])
        self.assertEqual("step_read", report["stage"])
        self.assertEqual(hashlib.sha256(b"").hexdigest(), report["input_sha256"])

    def test_existing_report_is_preserved(self):
        source = self.build("box6")
        output = self.directory / "report.json"
        sentinel = b'{"original_evidence":true}\n'
        output.write_bytes(sentinel)
        result, report = self.consume(source, output=output)
        self.assertEqual(2, result.returncode)
        self.assertEqual({"original_evidence": True}, report)
        self.assertEqual(sentinel, output.read_bytes())
        self.assertIn("existing evidence is preserved", result.stderr)

    def test_input_cannot_be_report(self):
        source = self.build("box6")
        result = execute(
            [
                sys.executable,
                "-B",
                str(CONSUMER),
                "--python-path",
                str(self.dependencies),
                "--input",
                str(source),
                "--output",
                str(source),
                "--expected-bounds",
                "-40",
                "-25",
                "-6",
                "40",
                "25",
                "0",
            ],
            self.directory,
            "consume",
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("cannot overwrite the STEP input", result.stderr)

    def test_probe_missing_dependency_fails_without_cad(self):
        result = execute(
            [
                sys.executable,
                "-B",
                str(CONSUMER),
                "--python-path",
                str(self.directory / "absent-dependency"),
                "--probe",
            ],
            self.directory,
            "missing-dependency-probe",
        )
        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("failed", report["status"])
        self.assertEqual("independent_dependency_load", report["stage"])
        self.assertNotIn("runtime", report)

    def damaged_file(self, kind):
        source = self.build("extra_solid" if kind == "empty_shell_branch" else "two_roots")
        text = source.read_text(encoding="utf-8")
        entity = {
            "missing_representation": "SHAPE_DEFINITION_REPRESENTATION",
            "missing_representation_item": "ADVANCED_BREP_SHAPE_REPRESENTATION",
            "missing_outer_shell": "MANIFOLD_SOLID_BREP",
            "empty_representation": "ADVANCED_BREP_SHAPE_REPRESENTATION",
            "empty_shell_branch": "CLOSED_SHELL",
        }[kind]
        entities = list(re.finditer(r"#\d+\s*=\s*" + entity + r"\([^;]*;", text))
        self.assertEqual(2, len(entities), "fixture must contain two distinct target STEP entities")
        target = entities[1]
        statement = target.group()
        if kind == "missing_representation":
            changed, count = re.subn(r"#\d+(\s*\);)$", r"#999999\1", statement)
        elif kind == "missing_representation_item":
            changed, count = re.subn(
                r"(ADVANCED_BREP_SHAPE_REPRESENTATION\('[^']*',\([^)]*,\s*)#\d+",
                r"\g<1>#999999",
                statement,
            )
        elif kind == "missing_outer_shell":
            changed, count = re.subn(r"#\d+(\s*\);)$", r"#999999\1", statement)
        elif kind == "empty_representation":
            changed, count = re.subn(
                r"(ADVANCED_BREP_SHAPE_REPRESENTATION\('[^']*',)\([^)]*\)",
                r"\g<1>()",
                statement,
            )
        else:
            changed, count = re.subn(r"(CLOSED_SHELL\('[^']*',)\([^)]*\)", r"\g<1>()", statement)
        self.assertEqual(1, count, "damage must change exactly one declared STEP entity")
        path = self.directory / (kind + ".step")
        path.write_text(text[: target.start()] + changed + text[target.end() :], encoding="utf-8")
        return path

    def assert_structurally_rejected(self, kind, expected_stage):
        source = self.damaged_file(kind)
        result, report = self.consume(source)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", report["status"])
        self.assertEqual(expected_stage, report["stage"])
        self.assertNotIn("topology", report["observed"], "a valid subset must not reach box proof")
        self.assertEqual(digest(source), report["input_sha256"])
        if expected_stage == "step_load_validation":
            load = report["observed"]["load_diagnostics"]
            self.assertFalse(load["no_messages"])
            if kind in ("empty_representation", "empty_shell_branch"):
                self.assertEqual(0, load["failure_count"])
                self.assertGreater(load["warning_count"], 0)
                self.assertTrue(load["no_failures"])
            else:
                self.assertGreater(load["failure_count"], 0)
                self.assertFalse(load["no_failures"])
        elif kind == "empty_representation":
            roots = report["observed"]["root_transfers"]
            self.assertEqual(2, len(roots))
            self.assertTrue(roots[0]["complete"])
            self.assertFalse(roots[1]["complete"])
            self.assertTrue(roots[1]["transfer_returned_success"])
            self.assertEqual(0, roots[1]["output_shapes"][0]["topology"]["vertices"])
        else:
            roots = report["observed"]["root_transfers"]
            self.assertEqual(1, len(roots))
            self.assertTrue(roots[0]["transfer_returned_success"])
            self.assertFalse(roots[0]["complete"])
            self.assertEqual(0, roots[0]["transient_diagnostics"]["failure_count"])
            self.assertGreater(roots[0]["transient_diagnostics"]["warning_count"], 0)

    def test_damaged_branch_load_warning_rejected(self):
        self.assert_structurally_rejected("empty_shell_branch", "step_load_validation")

    def test_missing_representation_root_rejected(self):
        self.assert_structurally_rejected("missing_representation", "step_load_validation")

    def test_missing_representation_item_rejected(self):
        self.assert_structurally_rejected("missing_representation_item", "step_load_validation")

    def test_missing_outer_shell_rejected(self):
        self.assert_structurally_rejected("missing_outer_shell", "step_load_validation")

    def test_successful_transfer_of_empty_root_rejected(self):
        self.assert_structurally_rejected("empty_representation", "step_load_validation")

    def test_orphan_empty_representation_load_warning_rejected(self):
        source = self.build("box6")
        text = source.read_text(encoding="utf-8")
        representation = re.search(r"ADVANCED_BREP_SHAPE_REPRESENTATION\([^;]*;", text)
        self.assertIsNotNone(representation)
        references = re.findall(r"#\d+", representation.group())
        self.assertGreaterEqual(len(references), 2)
        context = references[-1]
        extra_id = max(int(value) for value in re.findall(r"#(\d+)\s*=", text)) + 1
        extra = f"#{extra_id} = ADVANCED_BREP_SHAPE_REPRESENTATION('',(),{context});\n"
        position = text.rfind("ENDSEC;")
        self.assertGreater(position, 0)
        damaged = self.directory / "orphan_empty_representation.step"
        damaged.write_text(text[:position] + extra + text[position:], encoding="utf-8")
        result, report = self.consume(damaged)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual("failed", report["status"])
        self.assertEqual("step_load_validation", report["stage"])
        load = report["observed"]["load_diagnostics"]
        self.assertEqual(0, load["failure_count"])
        self.assertEqual(1, load["warning_count"])
        self.assertFalse(load["no_messages"])
        self.assertNotIn("root_transfers", report["observed"])
        self.assertNotIn("topology", report["observed"])


if __name__ == "__main__":
    unittest.main()
