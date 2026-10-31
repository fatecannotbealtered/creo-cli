"""Regression for default datum reference handling; synthetic SDK objects, not native CAD."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service"
HARNESS = ROOT / "tests/java/DatumReferenceReadbackHarness.java"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"
SDK = Path(
    os.environ.get("CREO_OTK_JAR", "D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
)
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@unittest.skipUnless(
    (JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file(),
    "requires declared JDK and installed licensed Creo SDK; no CAD runtime is used",
)
class DatumReferenceReadback(unittest.TestCase):
    def test_default_and_missing_selection_are_distinguished(self):
        with tempfile.TemporaryDirectory(prefix="creo-datum-readback-") as temp:
            classes = Path(temp) / "classes"
            result = subprocess.run(
                [
                    str(JDK / "javac.exe"),
                    "--release",
                    "17",
                    "-encoding",
                    "UTF-8",
                    "-cp",
                    str(SDK),
                    "-d",
                    str(classes),
                    *map(str, sorted(SOURCE.glob("*.java"))),
                    str(HARNESS),
                ],
                capture_output=True,
                timeout=90,
                creationflags=FLAGS,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            result = subprocess.run(
                [
                    str(JDK / "java.exe"),
                    "-cp",
                    os.pathsep.join((str(classes), str(SDK))),
                    "com.fateforge.creocli.service.DatumReferenceReadbackHarness",
                ],
                capture_output=True,
                timeout=15,
                creationflags=FLAGS,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            observation = json.loads(result.stdout)
        self.assertEqual(len(observation["passed"]), 5)
        self.assertIn("no CAD calls", observation["scope"])
