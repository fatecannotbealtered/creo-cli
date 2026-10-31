"""The seam between the Java service and the native sketch library.

Nothing type-checks it. Java calls a C function by name through
Dll.ExecuteFunction and passes labelled arguments; C finds them by comparing wide
strings. A renamed function or a misspelled label compiles on both sides and fails
only on a live Creo, as "not found". So the names are read out of both sources and
made to agree here.

The C side needs no element-id guard of its own: it is compiled against PTC's
headers, so its PRO_E_* names are the real ones by construction.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
C_SOURCE = (ROOT / "service" / "native" / "creo_cli_sketch.c").read_text(encoding="utf-8")
JAVA = ROOT / "service" / "src" / "com" / "fateforge" / "creocli" / "service"
MODELING = "\n".join(p.read_text(encoding="utf-8") for p in sorted(JAVA.glob("*.java")))
SERVICE = (JAVA / "Service.java").read_text(encoding="utf-8")
BUILD = (ROOT / "scripts" / "build_native_sketch.py").read_text(encoding="utf-8")


def c_function(name: str) -> str:
    """One exported function's text: up to its closing brace, the first at the line's start."""
    start = C_SOURCE.index(f"PRO_TK_DLL_EXPORT ProError {name}(")
    return C_SOURCE[start : C_SOURCE.index("\n}\n", start) + 2]


def c_inputs(name: str = "creo_cli_sketch") -> set[str]:
    # Required inputs are read with arg_text/arg_int/arg_double/arg_name directly; optional
    # ones too, but without failing the call, so all of them count. So do the ones a static
    # helper reads for the function, handed the inputs.
    body = c_function(name)
    read = set(re.findall(r'arg_(?:text|int|double|name)\(inputs,\s*L"([a-z_]+)"', body))
    for helper in re.findall(r"static ProError (\w+)\(ProArgument \*inputs", C_SOURCE):
        if re.search(rf"\b{helper}\(inputs", body):
            start = C_SOURCE.index(f"static ProError {helper}(ProArgument *inputs")
            end = C_SOURCE.index("\n}\n", start)
            read |= set(
                re.findall(
                    r'arg_(?:text|int|double|name)\(inputs,\s*L"([a-z_]+)"', C_SOURCE[start:end]
                )
            )
    return read


def c_outputs(name: str) -> set[str]:
    return set(
        re.findall(r'put_(?:int|double|text|ascii)\(outputs,\s*L"([a-z_]+)"', c_function(name))
    )


def java_inputs(caller: str = "static Map<String, Object> drawNatively") -> set[str]:
    body = MODELING[MODELING.index(caller) :]
    body = body[: body.index("ExecuteFunction")]
    return set(re.findall(r'Argument_Create\(\s*"([a-z_]+)"', body))


def java_method(signature: str) -> str:
    """One Java method's text, from its signature to its closing brace."""
    start = MODELING.index(signature)
    depth, i = 0, MODELING.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(MODELING[i], 0)
        if depth == 0:
            return MODELING[start : i + 1]
        i += 1


def java_labels(signature: str) -> set[str]:
    return set(re.findall(r'Argument_Create\(\s*"([a-z_]+)"', java_method(signature)))


class Seam(unittest.TestCase):
    def test_java_calls_the_functions_the_library_exports(self):
        exported = re.findall(r"PRO_TK_DLL_EXPORT\s+ProError\s+(\w+)\s*\(", C_SOURCE)
        # Java may name a function by a Service constant or an explicit literal.
        called = re.findall(r"ExecuteFunction\(\s*Service\.(\w+),", MODELING)
        literal_calls = re.findall(r'ExecuteFunction\(\s*"(creo_cli_[a-z_]+)"', MODELING)
        constants = dict(re.findall(r'static final String (\w+) = "([^"]+)"', SERVICE))
        self.assertEqual(
            exported,
            [
                "creo_cli_sketch",
                "creo_cli_dimension_move",
                "creo_cli_dimension_place",
                "creo_cli_dimension_delete",
                "creo_cli_bom_balloons",
                "creo_cli_bom_references",
                "creo_cli_tolerance_standard",
                "creo_cli_numeric_tolerance_table",
                "creo_cli_tolerance_decimals",
                "creo_cli_hole_indexes",
                "creo_cli_component_replace",
                "creo_cli_section_edges",
                "creo_cli_ray",
            ],
        )
        self.assertEqual(
            sorted(set(called)),
            [
                "BOM_BALLOONS_FUNCTION",
                "BOM_REFERENCES_FUNCTION",
                "COMPONENT_REPLACE_FUNCTION",
                "DIMENSION_DELETE_FUNCTION",
                "DIMENSION_MOVE_FUNCTION",
                "DIMENSION_PLACE_FUNCTION",
                "HOLE_INDEXES_FUNCTION",
                "RAY_FUNCTION",
                "SECTION_EDGES_FUNCTION",
                "SKETCH_LIBRARY_NAME",
                "TOLERANCE_DECIMALS_FUNCTION",
                "TOLERANCE_STANDARD_FUNCTION",
            ],
        )
        self.assertEqual(literal_calls, ["creo_cli_numeric_tolerance_table"])
        self.assertEqual(
            sorted({constants[c] for c in called} | set(literal_calls)), sorted(exported)
        )

    def test_every_argument_java_sends_is_one_the_library_reads(self):
        self.assertLessEqual(java_inputs(), c_inputs())
        self.assertEqual(
            c_inputs(),
            {
                "model",
                "feature_id",
                "refs",
                "entities",
                "direction",
                "steps",
                "cleanup",
                "sketcher_path",
                "dims",
            },
        )
        # A dimension is named to both drawing functions by one Java helper and one C helper.
        named = java_labels("private static com.ptc.pfc.pfcArgument.Arguments namedDimension")
        self.assertEqual(named, {"drawing", "owner", "owner_type", "dimension", "reference"})
        moved = named | java_labels("static Map<String, Object> moveDimension")
        self.assertEqual(moved, c_inputs("creo_cli_dimension_move"))
        self.assertEqual(moved, named | {"x", "y"})
        placed = named | java_labels("private static List<Object> placeOf")
        self.assertEqual(placed, c_inputs("creo_cli_dimension_place"))
        deleted = named | java_labels("private static void deleteNatively")
        self.assertEqual(deleted, c_inputs("creo_cli_dimension_delete"))
        balloons = java_labels("static Map<String, Object> addBalloons")
        self.assertEqual(balloons, c_inputs("creo_cli_bom_balloons"))
        self.assertEqual(balloons, {"drawing", "table", "view"})
        references = java_labels("private static List<Object> bomReferences")
        self.assertEqual(references, c_inputs("creo_cli_bom_references"))
        self.assertEqual(references, {"drawing", "table"})
        # A model is named to both tolerance functions by one C helper.
        standard = java_labels("static String toleranceStandard")
        self.assertEqual(standard, c_inputs("creo_cli_tolerance_standard"))
        self.assertEqual(standard, {"model", "model_type", "set"})
        places = java_labels("private static Integer toleranceDecimals")
        self.assertEqual(places, c_inputs("creo_cli_tolerance_decimals"))
        self.assertEqual(places, {"model", "model_type", "dimension", "tolerance_decimals"})
        table = java_labels("private static Map<String, Object> numericTable")
        self.assertEqual(table, c_inputs("creo_cli_numeric_tolerance_table"))
        self.assertEqual(table, {"model", "model_type", "dimension", "detach"})
        charted = java_labels("private static int[] indexes")
        self.assertEqual(charted, c_inputs("creo_cli_hole_indexes"))
        self.assertEqual(charted, {"model", "series", "screw"})
        replaced = java_labels("private static Map<String, Object> nativeReplace")
        self.assertEqual(replaced, c_inputs("creo_cli_component_replace"))
        self.assertEqual(replaced, {"model", "feature_id", "with", "with_type"})
        edged = java_labels("static void sectionEdges")
        self.assertEqual(edged, c_inputs("creo_cli_section_edges"))
        self.assertEqual(edged, {"drawing", "view", "edges"})
        cast = java_labels("static String cast(")
        self.assertEqual(cast, c_inputs("creo_cli_ray"))
        self.assertEqual(cast, {"model", "from", "along", "aperture"})

    def test_every_output_java_reads_is_one_the_library_writes(self):
        label = r'"([a-z_]+)"\.equals\(out\.get\(i\)\.GetLabel\(\)\)'
        read = set(re.findall(label, MODELING))
        self.assertEqual(read, {"x", "y", "standard", "tolerance_decimals", "hits"})
        self.assertLessEqual({"hits"}, c_outputs("creo_cli_ray"))
        self.assertLessEqual({"x", "y"}, c_outputs("creo_cli_dimension_place"))
        self.assertEqual(
            set(re.findall(label, java_method("static String toleranceStandard"))), {"standard"}
        )
        self.assertLessEqual({"standard"}, c_outputs("creo_cli_tolerance_standard"))
        self.assertEqual(
            set(re.findall(label, java_method("private static Integer toleranceDecimals"))),
            {"tolerance_decimals"},
        )
        self.assertLessEqual({"tolerance_decimals"}, c_outputs("creo_cli_tolerance_decimals"))
        # The hole chart's indexes are read by label in a loop of their own.
        read = set(
            re.findall(r'"([a-z_]+)"\.equals\(label\)', java_method("private static int[] indexes"))
        )
        self.assertEqual(read, {"series_index", "screw_index", "failed_step"})
        self.assertLessEqual(read, c_outputs("creo_cli_hole_indexes"))
        self.assertEqual(
            c_outputs("creo_cli_numeric_tolerance_table"),
            {
                "contract_version",
                "standard",
                "before_table_type",
                "table_type",
                "assigned",
                "status",
                "native_image",
            },
        )

    def test_the_sketch_read_back_java_describes_is_what_the_library_writes(self):
        # SketchPlan takes the native read-back out of the report by label and turns it into
        # what the reply says about each dimension.
        taken = set(
            re.findall(
                r'report\.remove\("([a-z_]+)"\)',
                java_method("static Map<String, Object> describe(Plan plan"),
            )
        )
        self.assertEqual(
            taken,
            {"dims_read", "dim_ids", "constraints", "planned", "plan_dropped", "vertical_ref"},
        )
        self.assertLessEqual(taken, c_outputs("creo_cli_sketch"))

    def test_planned_dimension_types_are_ptcs(self):
        # ProSecdimType.h: PRO_TK_DIM_LINE_POINT 2, _RAD 3, _DIA 4, _LINE_LINE 5. The plan
        # names them by number, which nothing else checks.
        plan = (JAVA / "SketchPlan.java").read_text(encoding="utf-8")
        declared = dict(re.findall(r"private static final int (\w+) = (\d+);", plan))
        self.assertEqual(
            declared, {"LINE_POINT": "2", "RADIUS": "3", "DIAMETER": "4", "LINE_LINE": "5"}
        )
        # And the references a plan names are the ones the library resolves.
        self.assertIn("text[0] == 'r' && (text[1] == 'v' || text[1] == 'h')", C_SOURCE)
        for point in ('".s"', '".e"', '".c"', '".w"'):
            self.assertIn(point, C_SOURCE)

    def test_the_registry_name_agrees_between_registration_and_lookup(self):
        # Java asks Creo for the library by the name protk.dat registers it under.
        looked_up = re.findall(r'SKETCH_LIBRARY_NAME = "([^"]+)"', SERVICE)
        registered = re.findall(
            r'NATIVE_APP_NAME = "([^"]+)"',
            (ROOT / "scripts" / "build_service.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(looked_up, ["creo_cli_sketch"])
        self.assertEqual(registered, looked_up)

    def test_entity_kinds_java_emits_are_ones_the_library_parses(self):
        emitted = set(re.findall(r'append\("([A-Z]) "\)', MODELING))
        parsed = set(re.findall(r"kind == '([A-Z])'", C_SOURCE))
        self.assertTrue(emitted)
        self.assertLessEqual(emitted, parsed)


class Discipline(unittest.TestCase):
    """The library runs in Creo's own process; these are the rules that keep it safe."""

    def test_the_default_order_never_regenerates_under_intent_manager(self):
        # ProSection.h: ProSectionSolve, ProSectionRegenerate and ProSectionAutodim
        # "shouldn't be called if Intent Manager mode is used" and answer
        # PRO_TK_BAD_CONTEXT -- which is where the first live run stopped.
        default = re.search(r'#define DEFAULT_STEPS "([^"]+)"', C_SOURCE).group(1).split(",")
        intent = False
        for step in default:
            if step in ("im_on", "im_off"):
                intent = step == "im_on"
            elif step in ("solve", "regenerate", "autodim"):
                self.assertFalse(intent, f"{step} runs with intent manager on")
        self.assertEqual(default[-1], "redefine")
        self.assertLess(
            default.index("refs"),
            default.index("entities"),
            "entities are measured from the projected references",
        )

    def test_the_order_java_sends_is_one_the_library_can_run(self):
        # NATIVE_STEPS is what actually reaches Creo; the library's own default is a
        # fallback. Found live: every intent-manager order was rejected at the redefine.
        sent = re.search(r'NATIVE_STEPS = "([^"]+)"', MODELING).group(1).split(",")
        known = set(re.findall(r'strcmp\(step, "([a-z_]+)"\) == 0', C_SOURCE))
        self.assertLessEqual(set(sent), known)
        # The read-back reads the feature the redefine made.
        self.assertEqual(sent[-2:], ["redefine", "readback"])
        self.assertLess(sent.index("refs"), sent.index("entities"))
        self.assertLess(
            sent.index("entities"),
            sent.index("plan"),
            "dimensioning needs the references and entities in place",
        )
        intent = False
        for step in sent:
            if step in ("im_on", "im_off"):
                intent = step == "im_on"
            elif step in ("solve", "regenerate", "autodim", "plan"):
                self.assertFalse(intent, f"{step} runs with intent manager on")

    def test_the_plan_gives_its_dimensions_before_auto_dimensioning(self):
        # Given after, they would meet the equalities auto-dimensioning had already read
        # into coincidences; given before, there is nothing left to read them into.
        plan = C_SOURCE[C_SOURCE.index('strcmp(step, "plan") == 0') :]
        plan = plan[: plan.index("} else if (strcmp(step,")]
        self.assertLess(plan.index("plan_dimension("), plan.index("ProSectionAutodim("))
        # An over-constraining plan is dropped: its dimensions deleted, Creo alone again.
        self.assertIn("ProSecdimDelete(section, made[k])", plan)
        self.assertEqual(plan.count("ProSectionAutodim("), 2)

    def test_every_step_java_spells_out_is_one_the_library_runs(self):
        # Features that set their own order -- a rib's material side, a sweep's path read
        # back for where it lies -- pass it as a literal beside the sketch.
        known = set(re.findall(r'strcmp\(step, "([a-z_]+)"\) == 0', C_SOURCE))
        orders = re.findall(r'"((?:[a-z_]+,)+(?:redefine|readback))"', MODELING)
        self.assertTrue(orders)
        for order in orders:
            with self.subTest(order=order):
                self.assertLessEqual(set(order.split(",")), known)

    def test_the_sweep_reads_where_its_path_lies_as_the_library_writes_it(self):
        order = re.findall(
            r'"((?:[a-z_]+,)+(?:redefine|readback))"',
            java_method("private static Object[] pathCurve"),
        )
        self.assertEqual(len(order), 1)
        steps = order[0].split(",")
        # The path is dimensioned and regenerated (plan) before its location is read.
        self.assertLess(steps.index("plan"), steps.index("locate"))
        self.assertIn('report.get("location")', java_method("private static double[] inModel"))
        self.assertIn("location", c_outputs("creo_cli_sketch"))

    def test_every_step_the_default_names_is_one_the_library_runs(self):
        default = re.search(r'#define DEFAULT_STEPS "([^"]+)"', C_SOURCE).group(1).split(",")
        known = set(re.findall(r'strcmp\(step, "([a-z_]+)"\) == 0', C_SOURCE))
        self.assertLessEqual(set(default), known)

    def test_every_allocation_on_the_way_is_freed_at_the_end(self):
        finish = C_SOURCE[C_SOURCE.index("finish:") :]
        for release in (
            "ProArrayFree((ProArray *)&options)",
            "ProSecerrorFree(&sec_errors)",
            "ProFeatureElemtreeFree(&feature, tree)",
        ):
            self.assertIn(release, finish)
        self.assertIn("ProSelectionFree(&selection)", C_SOURCE)

    def test_output_strings_are_toolkit_copies(self):
        # The caller frees output strings with ProArgumentProarrayFree, so they must
        # come from the toolkit's allocator, not point at this function's stack.
        self.assertIn("ProValuedataWstringSet", C_SOURCE)
        self.assertNotRegex(C_SOURCE, r"\.v\.w\s*=")

    def test_built_with_ptcs_own_flags(self):
        for flag in ('"-DPRO_MACHINE=36"', '"-DPRO_OS=4"', '"-D_WSTDIO_DEFINED"', '"-fp:precise"'):
            self.assertIn(flag, BUILD)
        self.assertIn("protk_dll_NU.lib", BUILD)


if __name__ == "__main__":
    unittest.main()


class Reuse(unittest.TestCase):
    """A rebuilt DLL is new to Creo, and an unsigned new toolkit DLL means a prompt.

    So an unchanged source must reuse the signed binary, and a changed one must not.
    """

    def setUp(self):
        import sys
        import tempfile

        sys.path.insert(0, str(ROOT))
        from scripts import build_native_sketch

        self.b = build_native_sketch
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        work = Path(self.temp.name).resolve()
        self.source = work / "creo_cli_sketch.c"
        self.source.write_text("int x;\n", encoding="utf-8")
        self.output = work / "creo_cli_sketch.dll"
        from unittest.mock import patch

        for name, value in (
            ("SOURCE", self.source),
            ("OUTPUT", self.output),
            ("STAMP", work / "creo_cli_sketch.dll.stamp.json"),
        ):
            patcher = patch.object(self.b, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.builds = 0

        def fake_build(creo):
            self.builds += 1
            self.output.write_bytes(b"binary %d" % self.builds)
            return {"dll": str(self.output)}

        for name, fake in (("build", fake_build), ("unlock", lambda creo, dll: "signed")):
            patcher = patch.object(self.b, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_fingerprint_follows_the_source(self):
        before = self.b.fingerprint()
        self.source.write_text("int y;\n", encoding="utf-8")
        self.assertNotEqual(before, self.b.fingerprint())

    def test_an_unchanged_source_reuses_the_signed_binary(self):
        first = self.b.ensure(Path("creo"))
        second = self.b.ensure(Path("creo"))
        self.assertTrue(first["rebuilt"])
        self.assertFalse(second["rebuilt"])
        self.assertEqual(self.builds, 1)

    def test_a_changed_source_rebuilds(self):
        self.b.ensure(Path("creo"))
        self.source.write_text("int z;\n", encoding="utf-8")
        self.assertTrue(self.b.ensure(Path("creo"))["rebuilt"])
        self.assertEqual(self.builds, 2)

    def test_a_tampered_binary_is_not_trusted_as_the_old_one(self):
        self.b.ensure(Path("creo"))
        self.output.write_bytes(b"something else")
        self.assertTrue(self.b.ensure(Path("creo"))["rebuilt"])
