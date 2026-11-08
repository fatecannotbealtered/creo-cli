"""The CLI side of the adapter: finding Creo, listing sessions, and the host component on disk."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from creo_cli import adapter as creo_adapter
from creo_cli._driver.state import AdapterStore, StateDir

ROOT = Path(__file__).resolve().parents[1]


class AdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = Path(tempfile.mkdtemp(prefix="creo-cli-adapter-"))
        self.addCleanup(shutil.rmtree, self.state, True)
        # The host component goes to %LOCALAPPDATA%; here, to a folder of the test's own.
        self.local = Path(tempfile.mkdtemp(prefix="creo-cli-local-"))
        self.addCleanup(shutil.rmtree, self.local, True)
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = creo_adapter.host_home(self.state)
        self.adapter = creo_adapter.Adapter(AdapterStore(StateDir(self.state)))

    def install(self, native_reason: str | None = None) -> dict:
        """Install, with the builds replaced: they need Creo, a JDK 25, a C compiler and TOOLKIT licenses."""
        self.builds = getattr(self, "builds", 0)

        def fake_build(sources: Path, common: Path, jar: Path, version: str) -> None:
            self.builds += 1
            self.built_version = version
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(b"jar")

        def fake_native(sources: Path, common: Path, dll: Path) -> str | None:
            if native_reason is None:
                dll.write_bytes(b"dll")
            return native_reason

        with mock.patch.object(creo_adapter, "common_files", return_value=[Path(r"D:\PTC\Creo 13.4.1.0\Common Files")]), \
                mock.patch.object(creo_adapter.build, "build", side_effect=fake_build), \
                mock.patch.object(creo_adapter.build, "build_native", side_effect=fake_native):
            return self.adapter.plugin_install({"operation_id": "op_test", "state_dir": str(self.state)})

    def test_the_version_comes_from_the_install_folder(self) -> None:
        self.assertEqual(creo_adapter.version_of(r"D:\PTC\Creo13.4\Creo 13.4.1.0\Common Files"), "13.4.1.0")
        self.assertIsNone(creo_adapter.version_of(r"D:\elsewhere"))

    def test_probe_without_creo_says_not_found(self) -> None:
        with mock.patch.object(creo_adapter, "common_files", return_value=[]):
            self.assertEqual(self.adapter.probe({}), {"found": False})

    def test_probe_reports_the_installation(self) -> None:
        found = Path(r"D:\PTC\Creo13.4\Creo 13.4.1.0\Common Files")
        with mock.patch.object(creo_adapter, "common_files", return_value=[found]):
            out = self.adapter.probe({})
        self.assertEqual(out, {"found": True, "path": str(found.parent), "license": "unknown", "version": "13.4.1.0"})

    def test_the_jar_is_built_as_the_manifest_version(self) -> None:
        manifest = json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))
        self.install()
        self.assertEqual(self.built_version, manifest["version"], "the host reports the version written into its JAR")

    def test_install_copies_every_manifest_file_and_writes_the_registry(self) -> None:
        manifest = json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))
        facts = self.install()
        version = manifest["version"]
        target = self.home / version
        self.assertEqual(facts["dispatch_state"], "dispatched")
        self.assertEqual(facts["install_path"], str(self.home))
        self.assertTrue(self.home.is_relative_to(self.local / "creo-cli" / "host"))
        self.assertFalse((self.state / "plugin").exists(), "nothing of the host component goes into the state directory")
        for name in manifest["files"]:
            self.assertTrue((target / name).is_file(), name)
        registry = (self.home / "protk.dat").read_text(encoding="utf-8")
        self.assertIn("startup           otk_java", registry)
        self.assertIn("fail_tol          true", registry)
        self.assertIn(f"java_app_classpath {target / 'creo-cli-host.jar'}", registry)
        self.assertTrue((target / "creo-cli-host.jar").is_file())
        self.assertEqual((target / "creo-cli-native.dll").read_bytes(), b"dll")
        config = json.loads((self.home / "creo-cli-host.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"state_dir": str(self.state), "version": version,
                                  "source_sha256": creo_adapter.build.source_digest(ROOT / "plugin" / "source"),
                                  "native": {"installed": True}})

    def test_without_the_c_library_the_java_host_is_still_installed(self) -> None:
        facts = self.install(native_reason="no Visual Studio with the x64 C compiler was found")
        target = self.home / json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))["version"]
        self.assertEqual(facts["change"], "applied")
        self.assertTrue((target / "creo-cli-host.jar").is_file())
        self.assertFalse((target / "creo-cli-native.dll").exists())
        config = json.loads((self.home / "creo-cli-host.json").read_text(encoding="utf-8"))
        self.assertEqual(config["native"], {"installed": False, "reason": "no Visual Studio with the x64 C compiler was found"})

    def test_a_missing_c_library_file_is_built_again(self) -> None:
        self.install()
        target = self.home / json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))["version"]
        (target / "creo-cli-native.dll").unlink()
        self.install()
        self.assertEqual(self.builds, 2)
        self.assertTrue((target / "creo-cli-native.dll").is_file())

    def test_the_c_library_needs_a_compiler(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="creo-cli-native-src-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "lib.c").write_text("int x;", encoding="utf-8")
        with mock.patch.object(creo_adapter.build, "find_vcvars", return_value=None):
            reason = creo_adapter.build.build_native(folder, Path(r"D:\PTC\Common Files"), folder / "out.dll")
        self.assertIn("Visual Studio", reason)
        self.assertFalse((folder / "out.dll").exists())

    def test_the_c_library_needs_creo_toolkit(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="creo-cli-native-src-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "lib.c").write_text("int x;", encoding="utf-8")
        vcvars = folder / "vcvars64.bat"
        vcvars.write_text("@echo off", encoding="utf-8")
        with mock.patch.dict(os.environ, {"CREO_CLI_VCVARS": str(vcvars)}):
            reason = creo_adapter.build.build_native(folder, folder / "Common Files", folder / "out.dll")
        self.assertIn("Creo TOOLKIT", reason)

    def test_a_named_vcvars_that_does_not_exist_is_not_used(self) -> None:
        with mock.patch.dict(os.environ, {"CREO_CLI_VCVARS": str(self.state / "missing.bat")}):
            self.assertIsNone(creo_adapter.build.find_vcvars())

    def test_each_state_directory_has_its_own_host_folder(self) -> None:
        other = self.state / "elsewhere"
        self.assertNotEqual(creo_adapter.host_home(other), self.home)
        self.assertEqual(creo_adapter.host_home(str(self.state)), self.home)

    def test_install_again_does_not_rebuild_the_same_sources(self) -> None:
        self.install()
        self.install()
        self.assertEqual(self.builds, 1)

    def test_a_failed_build_installs_nothing(self) -> None:
        failure = creo_adapter.AdapterError("E_NATIVE_FAILURE", "unlock failed", dispatch_state="not_started")
        with mock.patch.object(creo_adapter, "common_files", return_value=[Path(r"D:\PTC\Common Files")]), \
                mock.patch.object(creo_adapter.build, "build", side_effect=failure):
            with self.assertRaises(creo_adapter.AdapterError):
                self.adapter.plugin_install({"operation_id": "op_test", "state_dir": str(self.state)})
        self.assertIsNone(self.adapter.plugin_status({})["version_on_disk"])
        self.assertFalse((self.home / "protk.dat").exists())

    def test_install_without_creo_is_unsupported(self) -> None:
        with mock.patch.object(creo_adapter, "common_files", return_value=[]):
            with self.assertRaises(creo_adapter.AdapterError) as caught:
                self.adapter.plugin_install({"operation_id": "op_test", "state_dir": str(self.state)})
        self.assertEqual(caught.exception.data["code"], "E_UNSUPPORTED")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")

    def test_the_source_digest_covers_the_c_sources(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="creo-cli-src-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "A.java").write_text("class A {}", encoding="utf-8")
        before = creo_adapter.build.source_digest(folder)
        (folder / "native").mkdir()
        (folder / "native" / "lib.c").write_text("int x;", encoding="utf-8")
        self.assertNotEqual(creo_adapter.build.source_digest(folder), before)

    def test_the_source_digest_ignores_line_endings(self) -> None:
        folder = self.state / "src"
        folder.mkdir()
        (folder / "A.java").write_bytes(b"class A {}\r\n")
        crlf = creo_adapter.build.source_digest(folder)
        (folder / "A.java").write_bytes(b"class A {}\n")
        self.assertEqual(creo_adapter.build.source_digest(folder), crlf)

    def test_status_reports_what_is_installed(self) -> None:
        self.assertIsNone(self.adapter.plugin_status({})["version_on_disk"])
        self.install()
        status = self.adapter.plugin_status({})
        self.assertEqual(status["version_on_disk"], json.loads((ROOT / "package.json").read_text())["version"])
        self.assertEqual(status["protocol_version"], "1.2.0")
        self.assertEqual(status["loaded"], [])

    def test_status_lists_the_hosts_that_are_running(self) -> None:
        hosts = self.state / "hosts"
        hosts.mkdir()
        (hosts / "creo-1-2.json").write_text(json.dumps({"address": r"\\.\pipe\x", "pid": os.getpid(),
                                                          "plugin_version": "1.0.0"}), encoding="utf-8")
        self.assertEqual(self.adapter.plugin_status({})["loaded"], [{"session": "creo-1-2", "version": "1.0.0"}])

    def test_remove_deletes_the_install(self) -> None:
        self.install()
        facts = self.adapter.plugin_remove({"operation_id": "op_test"})
        self.assertEqual(facts["change"], "applied")
        self.assertFalse(self.home.exists())
        self.assertIsNone(self.adapter.plugin_status({})["version_on_disk"])

    def test_remove_without_an_install_changes_nothing(self) -> None:
        self.assertEqual(self.adapter.plugin_remove({"operation_id": "op_test"})["dispatch_state"], "not_started")

    # ------------------------------------------------------------------ session open and close

    def test_session_open_needs_the_file_it_opens(self) -> None:
        with self.assertRaises(creo_adapter.AdapterError) as caught:
            self.adapter.open_session({"operation_id": "op_test", "path": str(self.state / "missing.prt")})
        self.assertEqual(caught.exception.data["code"], "E_NOT_FOUND")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")

    def test_session_open_needs_the_host_component(self) -> None:
        creo = self.local / "Creo 13.4.1.0"
        (creo / "Parametric" / "bin").mkdir(parents=True)
        (creo / "Parametric" / "bin" / "parametric.exe").write_bytes(b"")
        with mock.patch.object(creo_adapter, "common_files", return_value=[creo / "Common Files"]):
            with self.assertRaises(creo_adapter.AdapterError) as caught:
                self.adapter.open_session({"operation_id": "op_test"})
        self.assertEqual(caught.exception.data["code"], "E_UNSUPPORTED")

    def test_session_open_starts_creo_from_its_own_folder_and_owns_it(self) -> None:
        self.install()
        creo = self.local / "Creo 13.4.1.0"
        (creo / "Parametric" / "bin").mkdir(parents=True)
        (creo / "Parametric" / "bin" / "parametric.exe").write_bytes(b"")
        started = []
        discovery = []

        def popen(command, cwd, **kwargs):
            started.append((command, cwd))
            discovery.append({"pid": 4242, "address": r"\\.\pipe\x", "plugin_version": "1.0.0", "_file": "creo-4242-1.json"})
            return SimpleNamespace(pid=4241)

        with mock.patch.object(creo_adapter, "common_files", return_value=[creo / "Common Files"]), \
                mock.patch.object(creo_adapter.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(creo_adapter, "read_discovery", side_effect=lambda folder: list(discovery)), \
                mock.patch.object(creo_adapter, "pid_alive", return_value=True), \
                mock.patch.object(creo_adapter.windows, "processes", side_effect=lambda name: [4242] if discovery else []), \
                mock.patch.object(creo_adapter.windows, "image_path", return_value=str(creo / "Parametric" / "bin" / "xtop.exe")), \
                mock.patch.object(creo_adapter.windows, "blocker", return_value=None), \
                mock.patch.object(creo_adapter, "session_id", side_effect=lambda prefix, pid: f"creo-{pid}-1"), \
                mock.patch.object(creo_adapter.Adapter, "_ask_host", return_value=None), \
                mock.patch.object(creo_adapter.time, "sleep"):
            facts = self.adapter.open_session({"operation_id": "op_test"})
        self.assertEqual(facts["change"], "applied")
        self.assertEqual(facts["session"]["id"], "creo-4242-1")
        self.assertTrue(facts["session"]["owned"])
        command, cwd = started[0]
        self.assertEqual(Path(command[0]).name, "parametric.exe")
        self.assertEqual(Path(cwd), self.home / "start")
        config = (self.home / "start" / "config.pro").read_text(encoding="utf-8")
        self.assertIn(f"toolkit_registry_file {self.home / 'protk.dat'}", config)
        self.assertIn("open_protk_unsigned_apps always", config)

    def test_session_close_needs_a_loaded_host_component(self) -> None:
        with mock.patch.object(creo_adapter, "read_discovery", return_value=[]):
            with self.assertRaises(creo_adapter.AdapterError) as caught:
                self.adapter.close_session({"operation_id": "op_test", "session": "creo-4242-1"})
        self.assertEqual(caught.exception.data["code"], "E_UNSUPPORTED")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")

    def test_session_close_waits_for_creo_to_end(self) -> None:
        self.adapter.store.set("owned-sessions", ["creo-4242-1"])
        calls = []

        class FakeConnection:
            def __init__(self, *args) -> None:
                pass

            def open(self, deadline_ms):
                return {}

            def call(self, method, params, deadline_ms):
                calls.append(method)
                return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "unchanged"}

            def close(self) -> None:
                pass

        alive = iter([True, True, False, False, False])
        with mock.patch.object(creo_adapter, "read_discovery", return_value=[{"pid": 4242, "address": "pipe"}]), \
                mock.patch.object(creo_adapter, "Connection", FakeConnection), \
                mock.patch.object(creo_adapter, "pid_alive", side_effect=lambda pid: next(alive)), \
                mock.patch.object(creo_adapter.windows, "processes", return_value=[]), \
                mock.patch.object(creo_adapter.time, "sleep"):
            facts = self.adapter.close_session({"operation_id": "op_test", "session": "creo-4242-1"})
        self.assertEqual(calls, ["close_session"])
        self.assertEqual(facts["change"], "applied")
        self.assertEqual(self.adapter.store.get("owned-sessions"), [])

    def test_sessions_marks_the_ones_the_tool_started(self) -> None:
        self.adapter.store.set("owned-sessions", ["creo-7-1"])
        with mock.patch.object(creo_adapter.windows, "processes", return_value=[7, 8]), \
                mock.patch.object(creo_adapter.windows, "image_path", return_value=None), \
                mock.patch.object(creo_adapter.windows, "blocker", return_value=None), \
                mock.patch.object(creo_adapter, "session_id", side_effect=lambda prefix, pid: f"creo-{pid}-1"):
            items = self.adapter.sessions({})["items"]
        self.assertEqual({i["id"]: i["owned"] for i in items}, {"creo-7-1": True, "creo-8-1": False})

    def test_sessions_lists_each_creo_process(self) -> None:
        with mock.patch.object(creo_adapter.windows, "processes", return_value=[4242]), \
                mock.patch.object(creo_adapter.windows, "image_path", return_value=r"D:\PTC\Creo 13.4.1.0\x\xtop.exe"), \
                mock.patch.object(creo_adapter.windows, "blocker", return_value=None), \
                mock.patch.object(creo_adapter, "session_id", return_value="creo-4242-1"):
            out = self.adapter.sessions({})
        self.assertTrue(out["complete"])
        self.assertEqual(out["items"], [{
            "id": "creo-4242-1", "application": {"name": "Creo Parametric", "version": "13.4.1.0"}, "pid": 4242,
            "owned": False, "generation": 0, "state": "ready", "documents": [], "plugin_loaded": None}])

    def test_a_dialog_makes_the_session_blocked(self) -> None:
        with mock.patch.object(creo_adapter.windows, "processes", return_value=[4242]), \
                mock.patch.object(creo_adapter.windows, "image_path", return_value=None), \
                mock.patch.object(creo_adapter.windows, "blocker", return_value="Creo Parametric Options"), \
                mock.patch.object(creo_adapter, "session_id", return_value="creo-4242-1"):
            item = self.adapter.sessions({})["items"][0]
        self.assertEqual(item["state"], "blocked")
        self.assertEqual(item["blocker"], {"action": "dismiss_dialog", "title": "Creo Parametric Options",
                                           "knowledge": ["creo-troubleshooting"]})

    def test_a_busy_host_keeps_the_last_document_list(self) -> None:
        hosts = self.state / "hosts"
        hosts.mkdir()
        (hosts / "creo-4242-1.json").write_text(json.dumps({"address": r"\\.\pipe\x", "pid": 4242}), encoding="utf-8")
        docs = [{"id": "disc.prt", "path": r"D:\work\disc.prt", "dirty": False}]

        class Host:
            busy = False

            def __init__(self, *args: object) -> None:
                pass

            def open(self, deadline_ms: int) -> dict:
                return {"session": {"generation": 3}}

            def call(self, method: str, params: dict, deadline_ms: int) -> dict:
                if Host.busy:
                    raise creo_adapter.HostReplyError("busy", {"code": "E_BUSY", "dispatch_state": "not_started"})
                return {"items": docs}

            def close(self) -> None:
                pass

        def listed() -> dict:
            with mock.patch.object(creo_adapter.windows, "processes", return_value=[4242]), \
                    mock.patch.object(creo_adapter.windows, "image_path", return_value=None), \
                    mock.patch.object(creo_adapter.windows, "blocker", return_value=None), \
                    mock.patch.object(creo_adapter, "pid_alive", return_value=True), \
                    mock.patch.object(creo_adapter, "session_id", return_value="creo-4242-1"), \
                    mock.patch.object(creo_adapter, "Connection", Host):
                return self.adapter.sessions({})["items"][0]

        self.assertEqual(listed()["documents"], docs)
        Host.busy = True
        item = listed()
        self.assertEqual(item["state"], "busy")
        self.assertEqual(item["documents"], docs)

    def test_each_instance_answers_at_once_within_its_own_limit(self) -> None:
        hosts = self.state / "hosts"
        hosts.mkdir()
        for pid in (4242, 4343):
            (hosts / f"creo-{pid}-1.json").write_text(json.dumps({"address": rf"\\.\pipe\{pid}", "pid": pid}),
                                                      encoding="utf-8")
        # Both hellos must be waiting at the same time: asked one after the other, the barrier breaks.
        together = threading.Barrier(2, timeout=5)
        # Each thread's own clock, where opening takes the longest it may: connecting, then the hello.
        clock: dict[int, float] = {}
        taken: list[float] = []

        def now() -> float:
            return clock.get(threading.get_ident(), 0.0)

        class Host:
            def __init__(self, *args: object) -> None:
                pass

            def open(self, deadline_ms: int) -> dict:
                together.wait()
                clock[threading.get_ident()] = now() + 2 * deadline_ms / 1000
                return {"session": {"generation": 1}}

            def call(self, method: str, params: dict, deadline_ms: int) -> dict:
                taken.append(now() + deadline_ms / 1000)
                return {"items": []}

            def close(self) -> None:
                pass

        with mock.patch.object(creo_adapter.windows, "processes", return_value=[4242, 4343]),                 mock.patch.object(creo_adapter.windows, "image_path", return_value=None),                 mock.patch.object(creo_adapter.windows, "blocker", return_value=None),                 mock.patch.object(creo_adapter, "pid_alive", return_value=True),                 mock.patch.object(creo_adapter, "session_id", side_effect=lambda app, pid: f"creo-{pid}-1"),                 mock.patch.object(creo_adapter, "time", SimpleNamespace(monotonic=now)),                 mock.patch.object(creo_adapter, "Connection", Host):
            items = self.adapter.sessions({})["items"]
        self.assertEqual([i["generation"] for i in items], [1, 1])
        self.assertEqual(len(taken), 2)
        self.assertTrue(all(seconds <= 2.0 for seconds in taken), taken)

    def test_main_windows_are_told_from_dialogs_by_title(self) -> None:
        for title in ("DISC - Creo Parametric 13", "Creo Parametric 13", "PAIR (Active) - Creo Parametric 13.4"):
            self.assertTrue(creo_adapter.windows.is_main_title(title), title)
        for title in ("Creo Parametric Options", "Creo Parametric", "Relations", "creo-cli test dialog"):
            self.assertFalse(creo_adapter.windows.is_main_title(title), title)

    def test_windows_helpers_answer_for_missing_processes(self) -> None:
        self.assertIsInstance(creo_adapter.windows.processes("no-such-program.exe"), list)
        self.assertIsNone(creo_adapter.windows.image_path(0))
        self.assertIsNone(creo_adapter.windows.blocker(0))


if __name__ == "__main__":
    unittest.main()
