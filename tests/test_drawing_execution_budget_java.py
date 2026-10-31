"""Production Java wait policy; pure JDK execution and endpoint wiring, no CAD."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ.get("JAVA_HOME", "__not_declared__")) / "bin"
JAVAC, JAVA = JDK / "javac.exe", JDK / "java.exe"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class DrawingExecutionBudgetWiringTests(unittest.TestCase):
    def test_actual_guard_precedes_policy_and_auth_precedes_queue(self):
        source = (SERVICE / "Service.java").read_text(encoding="utf-8")
        helper = source.split("private static long waitMillis(", 1)[1].split("\n    }", 1)[0]
        self.assertIn("NativeWaitBudget.milliseconds(NativeReadTrace::ensureHealthy", helper)
        for endpoint, after in (
            ("session", "One modelling operation"),
            ("operation", "session reading"),
        ):
            body = source.split(f"private static void {endpoint}(", 1)[1].split(after, 1)[0]
            self.assertLess(body.index("!authorised(exchange)"), body.index("waitMillis("))
            self.assertLess(body.index("waitMillis("), body.index("onToolkitThread("))
            self.assertIn("catch (NativeWaitBudget.Refusal failure)", body)
            self.assertIn("NativeWaitBudget.refusal(failure)", body)
        self.assertIn('waitMillis(exchange, "/session")', source)
        self.assertIn("waitMillis(exchange, op)", source)

    def test_capability_is_process_only_and_existing_queue_states_are_kept(self):
        source = (SERVICE / "Service.java").read_text(encoding="utf-8")
        health = source.split("private static void health(", 1)[1].split(
            "private static void session(", 1
        )[0]
        self.assertIn("NativeWaitBudget.CAPABILITY, NativeWaitBudget.CAPABILITY_VERSION", health)
        self.assertNotIn("onToolkitThread(", health)
        self.assertIn("state.compareAndSet(JOB_QUEUED, JOB_WITHDRAWN)", source)
        self.assertIn("state.compareAndSet(JOB_QUEUED, JOB_RUNNING)", source)
        self.assertIn('"retryable", false, "started", true', source)


@unittest.skipUnless(JAVAC.is_file() and JAVA.is_file(), "declare JAVA_HOME; this test uses no SDK")
class DrawingExecutionBudgetPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-native-wait-policy-")
        cls.classes = Path(cls.scratch.name) / "classes"
        result = subprocess.run(
            [
                str(JAVAC),
                "--release",
                "17",
                "-encoding",
                "UTF-8",
                "-d",
                str(cls.classes),
                str(SERVICE / "NativeWaitBudget.java"),
                str(ROOT / "tests/java/NativeWaitBudgetHarness.java"),
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

    def invoke(self, mode, expected_cases):
        result = subprocess.run(
            [
                str(JAVA),
                "-cp",
                str(self.classes),
                "com.fateforge.creocli.service.NativeWaitBudgetHarness",
                mode,
            ],
            capture_output=True,
            timeout=10,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        value = json.loads(result.stdout)
        self.assertEqual(value["passed_cases"], expected_cases)
        self.assertEqual(value["SDK_objects"], 0)
        self.assertEqual(value["CAD_calls"], 0)
        self.assertEqual(value["HTTP_requests"], 0)

    def test_legacy_default_minimum_first_header_and_invalid_behavior(self):
        self.invoke("legacy", 15)

    def test_only_explicit_required_operations_are_eligible(self):
        self.invoke("allowed-operations", 29)

    def test_current_remaining_budget_and_new_ceiling(self):
        self.invoke("remaining-and-cap", 11)

    def test_unknown_duplicate_and_ambiguous_profiles_are_refused(self):
        self.invoke("invalid-profile", 9)

    def test_frozen_model_writes_and_direct_session_cannot_expand(self):
        self.invoke("unsupported-operations", 23)

    def test_missing_ambiguous_nonfinite_and_overflow_waits_are_refused(self):
        self.invoke("invalid-wait", 16)

    def test_original_stop_has_priority_over_unreadable_headers(self):
        self.invoke("stop-priority", 3)
