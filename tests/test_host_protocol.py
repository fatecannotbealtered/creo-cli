"""The host component's protocol code, over a real named pipe, against the runtime's own client.

The core classes of the host component (plugin/src/.../host/core) use no Creo classes, so they
compile with a plain JDK. tests/host/TestHost.java wires them into a host without Creo; this
test talks to it with creo_cli._driver.hostproto, the client every CLI call uses. The test is
skipped when no JDK 22 or later is found (CREO_CLI_JDK, JAVA_HOME or PRO_JAVA_COMMAND).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from creo_cli._driver.hostproto import Connection, HostReplyError, NoReply, _connect

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "plugin" / "src" / "com" / "fateforge" / "creocli" / "host" / "core"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def find_jdk() -> Path | None:
    candidates = [os.environ.get("CREO_CLI_JDK"), os.environ.get("JAVA_HOME")]
    if os.environ.get("PRO_JAVA_COMMAND"):
        candidates.append(str(Path(os.environ["PRO_JAVA_COMMAND"]).parent.parent))
    on_path = shutil.which("javac")
    if on_path:
        candidates.append(str(Path(on_path).resolve().parent.parent))
    for candidate in candidates:
        if not candidate:
            continue
        javac = Path(candidate) / "bin" / ("javac.exe" if os.name == "nt" else "javac")
        if not javac.is_file():
            continue
        out = subprocess.run([str(javac), "-version"], capture_output=True, text=True, creationflags=NO_WINDOW)
        try:
            major = int((out.stdout + out.stderr).strip().split()[-1].split(".")[0])
        except (ValueError, IndexError):
            continue
        if major >= 22:
            return Path(candidate)
    return None


@unittest.skipUnless(sys.platform == "win32", "the host component runs on Windows only")
class HostProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        jdk = find_jdk()
        if jdk is None:
            raise unittest.SkipTest("no JDK 22 or later found")
        cls.work = Path(tempfile.mkdtemp(prefix="creo-cli-host-test-"))
        classes = cls.work / "classes"
        sources = [str(p) for p in CORE.glob("*.java")] + [str(ROOT / "tests" / "host" / "TestHost.java")]
        subprocess.run([str(jdk / "bin" / "javac.exe"), "-encoding", "UTF-8", "-d", str(classes), *sources],
                       check=True, capture_output=True, creationflags=NO_WINDOW)
        cls.proc = subprocess.Popen([str(jdk / "bin" / "java.exe"), "--enable-native-access=ALL-UNNAMED", "-cp",
                                     str(classes), "TestHost", f"creo-cli-test-{uuid.uuid4().hex[:12]}"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=NO_WINDOW)
        line = cls.proc.stdout.readline().decode().strip()
        if not line.startswith("READY "):
            cls.proc.kill()
            raise AssertionError(f"the test host did not start: {line} {cls.proc.stderr.read().decode()[:2000]}")
        cls.address = line[len("READY "):]

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.proc.stdin.close()
            cls.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - the test is over either way
            cls.proc.kill()
        shutil.rmtree(cls.work, ignore_errors=True)

    def connect(self) -> Connection:
        conn = Connection(self.address, "test", "1.0.0")
        conn.open(3000)
        self.addCleanup(conn.close)
        return conn

    def test_hello_answers_the_handshake(self) -> None:
        conn = self.connect()
        self.assertEqual(conn.hello["protocol_version"], "1.0.0")
        self.assertEqual(conn.hello["session"], {"id": "creo-1-1", "generation": 0})
        self.assertIn("read", conn.hello["methods"])

    def distance(self, a: dict, b: dict) -> float:
        return self.connect().call("distance", {"a": a, "b": b}, 3000)["distance"]

    def test_datum_distances_follow_the_geometry(self) -> None:
        front = {"kind": "plane", "at": [0, 0, 0], "direction": [0, 0, 1]}
        offset = {"kind": "plane", "at": [5, -3, 25], "direction": [0, 0, -2]}
        tilted = {"kind": "plane", "at": [0, 0, 25], "direction": [0, 1, 1]}
        axis = {"kind": "line", "at": [10, 0, 7], "direction": [1, 0, 0]}
        across = {"kind": "line", "at": [0, 4, 0], "direction": [0, 0, 1]}
        origin = {"kind": "point", "at": [3, 4, 0]}
        self.assertAlmostEqual(self.distance(front, offset), 25.0)
        self.assertEqual(self.distance(front, tilted), 0.0)
        self.assertAlmostEqual(self.distance(axis, front), 7.0)
        self.assertEqual(self.distance(across, front), 0.0)
        self.assertAlmostEqual(self.distance(axis, across), 4.0)
        self.assertAlmostEqual(self.distance(origin, across), 3.0)
        self.assertAlmostEqual(self.distance(origin, {"kind": "point", "at": [0, 0, 0]}), 5.0)

    def test_a_request_before_hello_is_refused(self) -> None:
        stream = _connect(self.address, 3.0)
        self.addCleanup(stream.close)
        stream.write({"jsonrpc": "2.0", "id": 1, "method": "read", "params": {"deadline_ms": 1000}})
        reply = stream.read(time.monotonic() + 3)
        self.assertEqual(reply["error"]["code"], -32000)
        self.assertEqual(reply["error"]["data"]["code"], "E_VALIDATION")
        self.assertEqual(reply["error"]["data"]["dispatch_state"], "not_started")

    def test_a_main_thread_result_comes_back(self) -> None:
        result = self.connect().call("read", {"command": "x", "inputs": {}}, 3000)
        self.assertEqual(result["result"], {"text": "ok"})

    def test_a_large_reply_crosses_the_pipe_whole(self) -> None:
        result = self.connect().call("read", {"command": "x", "inputs": {"size": 300_000}}, 5000)
        self.assertEqual(len(result["result"]["text"]), 300_000)

    def test_an_application_error_keeps_its_code_and_message(self) -> None:
        with self.assertRaises(HostReplyError) as caught:
            self.connect().call("read", {"command": "x", "inputs": {"fail": True}}, 3000)
        self.assertEqual(caught.exception.code, "E_NOT_FOUND")
        self.assertEqual(caught.exception.data["native_message"], "Creo says: not here")

    def test_a_second_request_while_one_runs_is_busy_and_not_sent(self) -> None:
        first = threading.Thread(target=lambda: self.connect().call("apply", {"command": "x", "inputs": {"sleep_ms": 1500}}, 5000))
        first.start()
        time.sleep(0.4)
        with self.assertRaises(HostReplyError) as caught:
            self.connect().call("read", {"command": "x", "inputs": {}}, 3000)
        first.join()
        self.assertEqual(caught.exception.code, "E_BUSY")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")
        self.assertGreater(caught.exception.data["retry_after_ms"], 0)

    def test_a_main_thread_that_takes_nothing_gives_busy(self) -> None:
        conn = self.connect()
        conn.call("pause", {}, 1000)
        try:
            with self.assertRaises(HostReplyError) as caught:
                conn.call("read", {"command": "x", "inputs": {}}, 3000)
        finally:
            conn.call("resume", {}, 1000)
        self.assertEqual(caught.exception.code, "E_BUSY")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")

    def test_a_reply_after_the_deadline_never_comes(self) -> None:
        conn = Connection(self.address, "test", "1.0.0")
        conn.open(3000)
        try:
            with self.assertRaises(NoReply) as caught:
                conn.call("apply", {"command": "x", "inputs": {"sleep_ms": 1200}}, 400)
            self.assertTrue(caught.exception.timed_out, "the host must not close the connection before the deadline")
        finally:
            conn.close()
        time.sleep(1.5)  # let the slow task end before the next test


if __name__ == "__main__":
    unittest.main()
