"""Independent numerical controls for the bounded 2D screen-to-sheet admission."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JDK = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
JAVAC = str(JDK / "javac.exe") if JDK and (JDK / "javac.exe").is_file() else shutil.which("javac")
JAVA = str(JDK / "java.exe") if JDK and (JDK / "java.exe").is_file() else shutil.which("java")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@unittest.skipUnless(JAVAC and JAVA, "SDK-free envelope controls require an available JDK")
class NoteEnvelopeMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-note-envelope-controls-")
        cls.classes = Path(cls.scratch.name) / "classes"
        result = subprocess.run(
            [
                JAVAC,
                "--release",
                "17",
                "-encoding",
                "UTF-8",
                "-d",
                str(cls.classes),
                str(ROOT / "service/src/com/fateforge/creocli/service/NoteEnvelopeMath.java"),
                str(ROOT / "tests/java/NoteEnvelopeMathHarness.java"),
            ],
            capture_output=True,
            timeout=30,
            creationflags=FLAGS,
        )
        if result.returncode:
            cls.scratch.cleanup()
            raise AssertionError(result.stderr.decode("utf-8", "replace"))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def run_case(self, mode):
        result = subprocess.run(
            [
                JAVA,
                "-cp",
                str(self.classes),
                "com.fateforge.creocli.service.NoteEnvelopeMathHarness",
                mode,
            ],
            capture_output=True,
            timeout=15,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        report = json.loads(result.stdout)
        self.assertGreater(report["checks"], 0)
        self.assertEqual(report["native_calls"], 0)

    def test_tiny_z_coupling_rejected_with_correct_row_vector_convention(self):
        self.run_case("z")

    def test_affine_gate_accepts_rotation_and_mirror_but_rejects_projective_terms(self):
        self.run_case("affine")

    def test_missing_nonfinite_and_degenerate_matrix_rejected(self):
        self.run_case("malformed")

    def test_every_corner_and_every_line_required(self):
        self.run_case("corners")

    def test_raw_representable_differences_survive_without_rounding(self):
        self.run_case("precision")

    def test_zero_width_or_height_cannot_be_used_as_text_bounds(self):
        self.run_case("zero")
