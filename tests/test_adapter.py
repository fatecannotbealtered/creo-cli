"""The CLI side of the adapter: finding Creo, listing sessions, and the host component on disk."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from creo_cli import adapter as creo_adapter
from creo_cli._driver.state import AdapterStore, StateDir

ROOT = Path(__file__).resolve().parents[1]


class AdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = Path(tempfile.mkdtemp(prefix="creo-cli-adapter-"))
        self.addCleanup(shutil.rmtree, self.state, True)
        self.adapter = creo_adapter.Adapter(AdapterStore(StateDir(self.state)))

    def install(self) -> dict:
        """Install, with the build replaced: it needs Creo, a JDK 25 and a TOOLKIT license."""
        self.builds = getattr(self, "builds", 0)

        def fake_build(sources: Path, common: Path, jar: Path) -> None:
            self.builds += 1
            jar.parent.mkdir(parents=True, exist_ok=True)
            jar.write_bytes(b"jar")

        with mock.patch.object(creo_adapter, "common_files", return_value=[Path(r"D:\PTC\Creo 13.4.1.0\Common Files")]), \
                mock.patch.object(creo_adapter.build, "build", side_effect=fake_build):
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

    def test_install_copies_every_manifest_file_and_writes_the_registry(self) -> None:
        manifest = json.loads((ROOT / "plugin" / "manifest.json").read_text(encoding="utf-8"))
        facts = self.install()
        version = manifest["version"]
        target = self.state / "plugin" / version
        self.assertEqual(facts["dispatch_state"], "dispatched")
        self.assertEqual(facts["install_path"], str(target))
        for name in manifest["files"]:
            self.assertTrue((target / name).is_file(), name)
        registry = (self.state / "plugin" / "protk.dat").read_text(encoding="utf-8")
        self.assertIn("startup           otk_java", registry)
        self.assertIn("fail_tol          true", registry)
        self.assertIn(f"java_app_classpath {target / 'creo-cli-host.jar'}", registry)
        self.assertTrue((target / "creo-cli-host.jar").is_file())
        config = json.loads((self.state / "plugin" / "creo-cli-host.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"state_dir": str(self.state), "version": version,
                                  "source_sha256": creo_adapter.build.source_digest(ROOT / "plugin" / "src")})

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
        self.assertFalse((self.state / "plugin" / "protk.dat").exists())

    def test_install_without_creo_is_unsupported(self) -> None:
        with mock.patch.object(creo_adapter, "common_files", return_value=[]):
            with self.assertRaises(creo_adapter.AdapterError) as caught:
                self.adapter.plugin_install({"operation_id": "op_test", "state_dir": str(self.state)})
        self.assertEqual(caught.exception.data["code"], "E_UNSUPPORTED")
        self.assertEqual(caught.exception.data["dispatch_state"], "not_started")

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
        self.assertEqual(status["protocol_version"], "1.0.0")
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
        self.assertFalse((self.state / "plugin").exists())
        self.assertIsNone(self.adapter.plugin_status({})["version_on_disk"])

    def test_remove_without_an_install_changes_nothing(self) -> None:
        self.assertEqual(self.adapter.plugin_remove({"operation_id": "op_test"})["dispatch_state"], "not_started")

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
        self.assertEqual(item["blocker"], {"action": "dismiss_dialog", "title": "Creo Parametric Options"})

    def test_windows_helpers_answer_for_missing_processes(self) -> None:
        self.assertIsInstance(creo_adapter.windows.processes("no-such-program.exe"), list)
        self.assertIsNone(creo_adapter.windows.image_path(0))
        self.assertIsNone(creo_adapter.windows.blocker(0))


if __name__ == "__main__":
    unittest.main()
