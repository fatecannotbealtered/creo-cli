"""Doctor's CREOSON-route checks, including the case that is easy to get wrong.

The toolkit lookup must not use os.stat on a composed path: Creo installations
delivered through an application-streaming layer answer stat with FileNotFoundError
while directory enumeration of the same location works. A probe written the obvious
way reports a perfectly good installation as missing, so that behaviour is pinned
here with a stat that is made to fail.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from creo_cli import creoson_env  # noqa: E402
from creo_cli.cli import main  # noqa: E402


def creo_tree(root: Path, *, with_toolkit: bool) -> Path:
    """A minimal stand-in for a Creo load point; no PTC files are involved."""
    common = root / "Creo 13.4.0.0" / "Common Files"
    (common / "x86e_win64" / "obj").mkdir(parents=True)
    (common / "x86e_win64" / "obj" / "pro_comm_msg.exe").write_bytes(b"NOT A REAL PTC BINARY")
    (common / "text" / "java").mkdir(parents=True)
    if with_toolkit:
        (common / "text" / "java" / creoson_env.JLINK_JAR).write_bytes(b"NOT A REAL JLINK JAR")
    return common


class ToolkitProbe(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def env(self, common: Path, **extra):
        return dict(os.environ, PRO_COMM_MSG_EXE=str(common / "x86e_win64" / "obj" / "pro_comm_msg.exe"), **extra)

    def test_reports_the_toolkit_when_the_jar_is_installed(self):
        common = creo_tree(self.root, with_toolkit=True)
        with patch.dict(os.environ, self.env(common), clear=True):
            result = creoson_env.toolkit()
        self.assertTrue(result["api_toolkit_present"])
        self.assertEqual(Path(result["creo_load_point"]), common)

    def test_reports_the_toolkit_missing_when_the_jar_is_absent(self):
        common = creo_tree(self.root, with_toolkit=False)
        with patch.dict(os.environ, self.env(common), clear=True):
            result = creoson_env.toolkit()
        self.assertFalse(result["api_toolkit_present"])
        self.assertIn(creoson_env.JLINK_JAR, result["detail"])

    def test_an_installation_stat_cannot_see_is_still_found(self):
        # The streamed-delivery case: enumeration works, stat does not. A probe that
        # composed a path and stat-ed it would call this installation missing.
        common = creo_tree(self.root, with_toolkit=True)
        with patch.dict(os.environ, self.env(common), clear=True):
            with patch("os.stat", side_effect=FileNotFoundError(2, "no such path")):
                result = creoson_env.toolkit()
        self.assertTrue(result["api_toolkit_present"],
                        "toolkit lookup must not depend on os.stat of a composed path")

    def test_missing_installation_is_reported_without_raising(self):
        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "PRO_COMM_MSG_EXE"}, clear=True):
            with patch.object(creoson_env, "PTC_ROOTS", (str(self.root / "absent"),)):
                result = creoson_env.toolkit()
        self.assertFalse(result["api_toolkit_present"])
        self.assertIsNone(result["creo_load_point"])


class DoctorChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def doctor(self, env) -> dict:
        out = io.StringIO()
        with patch.dict(os.environ, env, clear=True), redirect_stdout(out):
            code = main(["doctor", "--compact"])
        self.assertEqual(code, 0)
        return {c["check"]: c for c in json.loads(out.getvalue())["data"]["checks"]}

    def test_doctor_reports_the_toolkit_and_the_workspace(self):
        common = creo_tree(self.root, with_toolkit=True)
        space = self.root / "work"
        space.mkdir()
        checks = self.doctor(dict(os.environ,
                                  PRO_COMM_MSG_EXE=str(common / "x86e_win64" / "obj" / "pro_comm_msg.exe"),
                                  CREO_CLI_WORKSPACE=str(space)))
        self.assertEqual(checks["creo_api_toolkit"]["status"], "pass")
        self.assertIsNone(checks["creo_api_toolkit"]["fix"])
        self.assertEqual(checks["creoson_workspace"]["status"], "pass")

    def test_a_missing_toolkit_fails_with_the_component_that_ships_it(self):
        common = creo_tree(self.root, with_toolkit=False)
        with patch.object(creoson_env, "STREAMING_MARKERS", ()):
            checks = self.doctor(dict(os.environ,
                                      PRO_COMM_MSG_EXE=str(common / "x86e_win64" / "obj" / "pro_comm_msg.exe")))
        check = checks["creo_api_toolkit"]
        self.assertEqual(check["status"], "fail")
        # Naming J-Link alone is not actionable; the installer selection is.
        self.assertIn(creoson_env.TOOLKIT_COMPONENT, check["fix"])

    def test_a_streamed_installation_says_the_toolkit_cannot_be_added(self):
        common = creo_tree(self.root, with_toolkit=False)
        marker = self.root / "streaming-player"
        marker.mkdir()
        with patch.object(creoson_env, "STREAMING_MARKERS", (str(marker),)):
            checks = self.doctor(dict(os.environ,
                                      PRO_COMM_MSG_EXE=str(common / "x86e_win64" / "obj" / "pro_comm_msg.exe")))
        check = checks["creo_api_toolkit"]
        self.assertEqual(check["status"], "fail")
        self.assertTrue(check["details"]["streamed_delivery"])
        self.assertIn("no installer", check["fix"])

    def test_an_unset_workspace_warns_rather_than_failing(self):
        checks = self.doctor({k: v for k, v in os.environ.items() if k != "CREO_CLI_WORKSPACE"})
        self.assertEqual(checks["creoson_workspace"]["status"], "warn")
        self.assertIn("CREO_CLI_WORKSPACE", checks["creoson_workspace"]["fix"])

    def test_doctor_stays_offline(self):
        # Liveness belongs to `creoson status`; doctor must not open a socket for it.
        import socket
        common = creo_tree(self.root, with_toolkit=True)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("doctor opened a socket")):
            checks = self.doctor(dict(os.environ,
                                      PRO_COMM_MSG_EXE=str(common / "x86e_win64" / "obj" / "pro_comm_msg.exe")))
        self.assertEqual(checks["creoson_service"]["status"], "warn")


if __name__ == "__main__":
    unittest.main()
