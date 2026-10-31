"""Production Java summary-return controls; SDK declarations, no actual CAD objects or calls."""

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


class AddedNoteSummaryWiringTests(unittest.TestCase):
    def test_creation_return_has_one_summary_and_no_second_note_row(self):
        source = (ROOT / "service/src/com/fateforge/creocli/service/Drawings.java").read_text(
            encoding="utf-8"
        )
        body = source.split("static Map<String, Object> addNote(", 1)[1].split(
            "static Map<String, Object> addedNoteSummary(", 1
        )[0]
        self.assertEqual(body.count("summary(drawing)"), 1)
        self.assertNotIn("noteRow(drawing, note)", body)
        self.assertEqual(body.count("note.GetId()"), 1)
        self.assertIn('call("DetailNoteItem.GetId(created_note)"', body)
        self.assertIn("String actualDrawing = requireActiveNoteDrawing", body)
        self.assertIn("addedNoteSummary(actualDrawing, createdNoteId", body)


@unittest.skipUnless(
    SDK.is_file() and JAVAC.is_file() and JAVA.is_file(),
    "declare licensed CREO_CLI_OTK_JAR and JAVA_HOME; controls construct no SDK objects",
)
class AddedNoteSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-added-note-summary-")
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
                str(ROOT / "tests/java/AddedNoteSummaryHarness.java"),
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
                "com.fateforge.creocli.service.AddedNoteSummaryHarness",
                mode,
                str(Path(self.scratch.name) / mode),
            ],
            capture_output=True,
            timeout=20,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        value = json.loads(result.stdout)
        self.assertEqual(value["PTC_objects_constructed"], 0)
        self.assertEqual(value["real_CAD_calls"], 0)
        return value

    def test_actual_unique_native_member_is_returned_without_optional_fabrication(self):
        for mode in ("actual", "zero-id", "mixed-case"):
            with self.subTest(mode=mode):
                value = self.invoke(mode)
                self.assertTrue(value["returned_actual_row"])
                self.assertEqual(value["summary_traversals"], 1)
                self.assertEqual(value["summary_bodies"], 1)

    def test_missing_or_ambiguous_native_identity_never_falls_back(self):
        for mode in (
            "null-summary",
            "wrong-drawing",
            "missing-drawing",
            "wrong-type",
            "untyped-drawing",
            "negative-created-id",
            "null-inventory",
            "missing-inventory",
            "wrong-row",
            "missing-created",
            "missing-id",
            "duplicate-id",
            "duplicate-other-id",
            "boolean-id",
            "floating-id",
            "string-id",
            "negative-id",
            "overflow-id",
            "row-error",
        ):
            with self.subTest(mode=mode):
                value = self.invoke(mode)
                self.assertEqual(value["error"]["code"], "E_VERIFY_INCOMPLETE")
                self.assertFalse(value["diagnostic"]["stopped"])
                self.assertFalse(value["returned_actual_row"])

    def test_missing_or_wrong_membership_never_falls_back(self):
        for mode in (
            "missing-membership",
            "incomplete-membership",
            "missing-owner",
            "wrong-owner",
            "path-owner",
            "wrong-member-id",
            "boolean-member-id",
            "missing-member-id",
            "missing-source",
            "empty-source",
        ):
            with self.subTest(mode=mode):
                value = self.invoke(mode)
                self.assertEqual(value["error"]["summary_failure"], "created_note_membership")
                self.assertFalse(value["diagnostic"]["stopped"])

    def test_original_pending_diagnostic_and_ordinary_failures_are_not_replaced(self):
        for mode in ("pending", "diagnostic", "ordinary-error"):
            with self.subTest(mode=mode):
                value = self.invoke(mode)
                self.assertTrue(value["same_failure"])
                self.assertFalse(value["returned_actual_row"])
                if mode == "pending":
                    self.assertEqual(value["error"]["diagnostic_request_id"], "controlled-original")
                    self.assertEqual(value["error"]["cause"], {"code": "E_TIMEOUT"})

    def test_durable_failure_or_sticky_stop_cannot_start_fallback_reads(self):
        for mode, bodies in (
            ("begin-failure", 0),
            ("end-failure", 1),
            ("already-stopped", 0),
            ("stopped-after-summary", 1),
        ):
            with self.subTest(mode=mode):
                value = self.invoke(mode)
                self.assertEqual(value["summary_bodies"], bodies)
                self.assertTrue(value["diagnostic"]["stopped"])
                self.assertFalse(value["returned_actual_row"])
