"""Real helper controls with SDK declarations only; no PTC objects or CAD calls."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("CREO_CLI_OTK_JAR", "__not_declared__"))
JDK = Path(os.environ.get("JAVA_HOME", "__not_declared__")) / "bin"
JAVAC, JAVA = JDK / "javac.exe", JDK / "java.exe"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@unittest.skipUnless(
    SDK.is_file() and JAVAC.is_file() and JAVA.is_file(),
    "declare licensed CREO_CLI_OTK_JAR and JAVA_HOME; controls construct no SDK objects",
)
class TableCellReadbackFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-table-cell-control-")
        cls.classes = Path(cls.scratch.name) / "classes"
        sources = sorted((ROOT / "service/src").rglob("*.java"))
        result = subprocess.run(
            [
                str(JAVAC),
                "--release",
                "17",
                "-encoding",
                "UTF-8",
                "-cp",
                str(SDK),
                "-d",
                str(cls.classes),
                *map(str, sources),
                str(ROOT / "tests/java/TableCellReadbackHarness.java"),
            ],
            capture_output=True,
            timeout=60,
            creationflags=FLAGS,
        )
        if result.returncode:
            cls.scratch.cleanup()
            raise AssertionError(result.stderr.decode("utf-8", "replace"))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def invoke(self, mode):
        result = subprocess.run(
            [
                str(JAVA),
                "-cp",
                os.pathsep.join((str(self.classes), str(SDK))),
                "com.fateforge.creocli.service.TableCellReadbackHarness",
                mode,
                str(Path(self.scratch.name) / mode),
            ],
            capture_output=True,
            timeout=20,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        data = json.loads(result.stdout)
        self.assertEqual(data["PTC_objects_constructed"], 0)
        self.assertEqual(data["real_CAD_calls"], 0)
        return data

    def test_ordinary_failure_keeps_getter_class_and_owner_context(self):
        data = self.invoke("ordinary")
        error = data["error"]
        self.assertEqual(data["calls"], 1)
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertEqual(error["native_read_state"], "returned_error")
        self.assertEqual(error["failed_getter"], "ControlledTable.GetCellNote")
        self.assertEqual(error["exception_class"], "java.lang.IllegalArgumentException")
        self.assertEqual(
            [error[k] for k in ("table_inventory_index", "table_row", "table_column")],
            ["2", "3", "4"],
        )
        self.assertFalse(data["diagnostic"]["stopped"])

    def test_passive_log_does_not_replace_call_evidence(self):
        data = self.invoke("ordinary-log")
        self.assertEqual(data["error"]["failed_getter"], "ControlledTable.GetCellNote")
        last = data["diagnostic"]["last_call"]
        self.assertEqual(last["getter"], "ControlledTable.GetCellNote")
        self.assertEqual(last["result"], "threw")
        self.assertIsNone(data["diagnostic"]["last"]["getter"])

    def test_fatal_is_propagated_by_identity(self):
        data = self.invoke("fatal")
        self.assertTrue(data["same_fatal"])
        self.assertEqual(data["calls"], 1)

    def test_begin_persistence_failure_enters_no_body(self):
        data = self.invoke("begin-failure")
        self.assertEqual(data["calls"], 0)
        self.assertTrue(data["diagnostic"]["stopped"])

    def test_end_persistence_failure_never_replays_body(self):
        data = self.invoke("end-failure")
        self.assertEqual(data["calls"], 1)
        self.assertTrue(data["diagnostic"]["stopped"])

    def test_returned_null_remains_distinct_from_error(self):
        data = self.invoke("returned-null")
        self.assertIsNone(data["caught_class"])
        self.assertEqual(data["calls"], 1)
        self.assertTrue(data["value_is_null"])
        self.assertEqual(data["diagnostic"]["last_call"]["result"], "returned_null")
