"""service install: bundles checked against their manifest, installed into creo-cli's own
directory, protk.dat written, Creo's configuration left to the user."""

from __future__ import annotations

import json
import zipfile
from unittest.mock import patch

from creo_cli import operations, service_bundle
from tests.test_commands import Base, domain_preview, free_port


class ServiceInstall(Base):
    def setUp(self):
        super().setUp()
        scope = self.root / "scope.json"
        value = json.loads(scope.read_text())
        value.update(roots=[str(self.root)], outputs=[str(self.root)])
        scope.write_text(json.dumps(value), encoding="utf-8")

    def bundle(self, name="bundle", protocol=2, tamper=False):
        root = self.root / name
        root.mkdir()
        (root / service_bundle.JAR).write_bytes(b"PK\x03\x04 SUBSTITUTE JAR")
        (root / service_bundle.DLL).write_bytes(b"MZ SUBSTITUTE DLL")
        manifest = service_bundle.manifest_for(
            root,
            version="1.0.0",
            protocol=protocol,
            creo={"version": "Creo 13", "build": "2026163"},
        )
        (root / service_bundle.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        if tamper:
            (root / service_bundle.DLL).write_bytes(b"MZ SOMETHING ELSE")
        return root

    def zipped(self, directory):
        archive = self.root / (directory.name + ".zip")
        with zipfile.ZipFile(archive, "w") as z:
            for f in directory.iterdir():
                z.write(f, "creo-cli-service-1.0.0/" + f.name)
        return archive

    def test_install_from_a_directory_and_a_zip(self):
        source = self.bundle()
        preview = domain_preview(
            self.cli("service", "install", "--from", source, "--dry-run")["data"]["preview"]
        )
        self.assertEqual(preview["version"], "1.0.0")
        self.assertTrue(preview["policy"]["confirm_allowed"])
        self.assertIn("toolkit_registry_file", preview["then"][0])
        data = self.gated("service", "install", "--from", source)["data"]
        self.assertTrue(all(c["passed"] for c in data["verification"]["checks"]))
        target = self.root / "state" / "service" / "1.0.0"
        protk = (target / "protk.dat").read_text(encoding="utf-8")
        self.assertIn(str(target / service_bundle.JAR), protk)
        self.assertIn("startup           otk_java", protk)
        self.assertIn(str(target / service_bundle.DLL), protk)
        self.assertEqual(protk.count("delay_start       false"), 2)
        self.assertLess(
            protk.index("startup           dll"), protk.index("startup           otk_java")
        )
        # The same build again is a no-op; the zip of it installs the same way.
        again = self.gated("service", "install", "--from", self.zipped(source))["data"]
        self.assertEqual(again["result"]["installed_to"], str(target))
        self.assertFalse((self.root / "evil.txt").exists())
        receipts = self.cli("operation", "list")["data"]["items"]
        self.assertIn("service install", [r["command"] for r in receipts])

    def test_refusals(self):
        self.assertEqual(
            self.cli(
                "service",
                "install",
                "--from",
                self.bundle("old", protocol=1),
                "--dry-run",
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )
        self.assertEqual(
            self.cli(
                "service",
                "install",
                "--from",
                self.bundle("bad", tamper=True),
                "--dry-run",
                status=1,
            )["error"]["code"],
            "E_INTEGRITY",
        )
        self.assertEqual(
            self.cli("service", "install", "--from", self.root / "nothing", "--dry-run", status=3)[
                "error"
            ]["code"],
            "E_NOT_FOUND",
        )
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(
            self.cli("service", "install", "--from", empty, "--dry-run", status=2)["error"]["code"],
            "E_VALIDATION",
        )
        source = self.bundle()
        token = self.cli("service", "install", "--from", source, "--dry-run")["data"][
            "confirm_token"
        ]
        read_only = dict(self.env, CREO_CLI_PERMISSION="read")
        self.assertEqual(
            self.cli(
                "service", "install", "--from", source, "--confirm", token, env=read_only, status=4
            )["error"]["code"],
            "E_FORBIDDEN",
        )
        self.gated("service", "install", "--from", source)
        other = self.bundle("other")
        (other / service_bundle.JAR).write_bytes(b"PK\x03\x04 ANOTHER BUILD")
        manifest = service_bundle.manifest_for(other, version="1.0.0", protocol=2, creo={})
        (other / service_bundle.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(
            self.cli("service", "install", "--from", other, "--dry-run", status=6)["error"]["code"],
            "E_CONFLICT",
        )

    def test_preexisting_incomplete_target_is_preserved_and_refused(self):
        source = self.bundle()
        target = self.root / "state" / "service" / "1.0.0"
        # A directory where the DLL must go: the copy fails as it does when a scanner holds
        # the file.
        (target / service_bundle.DLL).mkdir(parents=True)
        failed = self.cli("service", "install", "--from", source, "--dry-run", status=6)
        self.assertEqual(failed["error"]["code"], "E_CONFLICT")
        self.assertFalse((target / "protk.dat").exists())
        self.assertEqual(service_bundle.installed(self.root / "state"), [])
        self.assertTrue((target / service_bundle.DLL).is_dir())
        self.assertEqual(self.receipts(), [])

    def test_archive_traversal_is_rejected_before_installation(self):
        archive = self.zipped(self.bundle())
        with zipfile.ZipFile(archive, "a") as out:
            out.writestr("../evil.txt", "outside")
        result = self.cli("service", "install", "--from", archive, "--dry-run", status=2)
        self.assertEqual(result["error"]["code"], "E_VALIDATION")
        self.assertFalse((self.root / "evil.txt").exists())
        self.assertEqual(service_bundle.installed(self.root / "state"), [])

    def test_an_unresolved_receipt_stops_it_too(self):
        with patch.dict("os.environ", self.env, clear=True):
            run = operations.begin("feature extrude", "block.prt", {}, "http://127.0.0.1:1")
        blocked = self.cli("service", "install", "--from", self.bundle(), "--dry-run", status=6)[
            "error"
        ]
        self.assertEqual(blocked["details"]["operation_ids"], [run["operation_id"]])

    def test_it_needs_neither_the_native_opt_in_nor_a_workspace(self):
        plain = {
            k: v
            for k, v in self.env.items()
            if k not in ("CREO_CLI_EXPERIMENTAL_NATIVE_WRITES", "CREO_CLI_WORKSPACE")
        }
        plain["CREO_CLI_SERVICE_URL"] = f"http://127.0.0.1:{free_port()}"
        data = self.gated("service", "install", "--from", self.bundle(), env=plain)["data"]
        self.assertTrue(all(c["passed"] for c in data["verification"]["checks"]))

    def test_doctor_points_at_the_installed_bundle_when_creo_is_down(self):
        self.gated("service", "install", "--from", self.bundle())
        self.server.close()
        checks = {c["check"]: c for c in self.cli("doctor")["data"]["checks"]}
        self.assertEqual(checks["service"]["status"], "fail")
        self.assertEqual(checks["service_installed"]["status"], "pass")
        self.assertIsNone(checks["service_installed"]["fix"])
        self.assertIn("protk.dat", checks["service"]["fix"])
