"""Run the actual Java flags scanner against getter faults; never load the PTC SDK or Creo."""

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


@unittest.skipUnless(JAVAC and JAVA, "CPU-only Java scanner regression requires an available JDK")
class RegenerationScan(unittest.TestCase):
    def test_getter_iteration_and_partial_read_failures_never_become_zero_failures(self):
        source = ROOT / "service/src/com/fateforge/creocli/service"
        with tempfile.TemporaryDirectory() as temp:
            compiled = subprocess.run(
                [
                    JAVAC,
                    "--release",
                    "17",
                    "-encoding",
                    "UTF-8",
                    "-d",
                    temp,
                    str(source / "Json.java"),
                    str(source / "FeatureStatusScan.java"),
                    str(ROOT / "tests/java/FeatureStatusScanTest.java"),
                ],
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode("utf-8", "replace"))
            run = subprocess.run(
                [JAVA, "-cp", temp, "com.fateforge.creocli.service.FeatureStatusScanTest"],
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
            self.assertEqual(
                json.loads(run.stdout), {"ok": True, "cases": 16, "kind": "cpu_only_no_creo"}
            )
