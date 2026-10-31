"""Installation input isolation and current read authorization at the public entry point."""

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from creo_cli import service_installation
from tests import test_service_runtime as service_fixture
from tests.test_commands import Base


class InstallationBoundaries(Base):
    source = service_fixture.ServiceRuntime.source

    def test_directory_source_cannot_contain_the_target(self):
        source = self.source()
        before = {p.name: p.read_bytes() for p in source.iterdir()}
        for target in (source, source / "components"):
            with self.subTest(target=target):
                result = self.cli(
                    "service",
                    "install",
                    "--from",
                    source,
                    "--target",
                    target,
                    "--dry-run",
                    status=2,
                )
                self.assertEqual(result["error"]["code"], "E_VALIDATION")
                self.assertEqual(result["error"]["details"]["dispatch_state"], "not_started")
                self.assertEqual({p.name: p.read_bytes() for p in source.iterdir()}, before)
                self.assertEqual(self.receipts(), [])
        self.assertFalse((source / "components").exists())

    def test_sibling_directory_and_zip_sharing_target_parent_are_supported(self):
        source = self.source()
        archive = self.ws / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            for item in source.iterdir():
                handle.write(item, item.name)
        for item, target in (
            (source, self.ws / "components"),
            (archive, self.ws / "zip-components"),
        ):
            with self.subTest(source=item):
                result = self.gated("service", "install", "--from", item, "--target", target)
                self.assertEqual(result["data"]["receipt"]["outcome"]["persistence"], "saved")
                self.assertFalse(result["data"]["result"]["creo_load_verified"])

    def install(self):
        source = self.source()
        target = self.ws / "components"
        result = self.gated("service", "install", "--from", source, "--target", target)
        return source, target, result["data"]["operation_id"]

    def test_query_rechecks_actual_path_before_enumeration_or_hashing(self):
        source, target, ident = self.install()
        grant = self.root / "scope.json"
        initial = json.loads(grant.read_text())
        before = self.receipts()
        variants = {
            "narrowed_root": initial | {"roots": [str(source)]},
            "revoked": initial | {"revoked": True},
            "wrong_selector": initial | {"targets": [{"object_id": str(self.ws / "sibling")}]},
        }
        for name, scope in variants.items():
            with self.subTest(scope=name):
                grant.write_text(json.dumps(scope), encoding="utf-8")
                with (
                    patch.object(
                        service_installation,
                        "target_snapshot",
                        wraps=service_installation.target_snapshot,
                    ) as read,
                    patch.object(
                        service_installation, "fingerprint", wraps=service_installation.fingerprint
                    ) as hashed,
                    patch.object(
                        Path, "iterdir", side_effect=AssertionError("unauthorized enumeration")
                    ),
                ):
                    result = self.cli("operation", "query", "--id", ident, status=4)
                self.assertEqual(result["error"]["code"], "E_FORBIDDEN")
                self.assertEqual(result["error"]["details"]["dispatch_state"], "not_started")
                read.assert_not_called()
                hashed.assert_not_called()
                self.assertEqual(self.receipts(), before)

    def test_query_with_observe_only_scope_and_CAD_down(self):
        _source, target, ident = self.install()
        grant = self.root / "scope.json"
        scope = json.loads(grant.read_text())
        scope.update(
            effects=["observe"],
            dangerous=False,
            targets=[{"object_id": service_installation.target_identity(target)["object_id"]}],
        )
        grant.write_text(json.dumps(scope), encoding="utf-8")
        self.server.close()
        self.env["CREO_CLI_PERMISSION"] = "read"
        before = self.receipts()
        result = self.cli("operation", "query", "--id", ident)["data"]["observation"]
        self.assertEqual(result["installation_verification"]["state"], "files_complete")
        self.assertFalse(result["installation_verification"]["creo_load_verified"])
        self.assertEqual(self.receipts(), before)

    def test_scope_revoked_after_copy_cannot_report_zero_dispatch(self):
        source = self.source()
        target = self.ws / "revoke-after-copy"
        words = ("service", "install", "--from", source, "--target", target)
        preview = self.cli(*words, "--dry-run")["data"]
        ident = preview["preview"]["operation_id"]
        scope = self.root / "scope.json"
        original_scope = scope.read_bytes()
        copy_file = service_installation._copy_file

        def revoke(src, dst):
            result = copy_file(src, dst)
            if src.name == "manifest.json":
                scope.write_text(json.dumps(json.loads(original_scope) | {"revoked": True}))
            return result

        with patch.object(service_installation, "_copy_file", side_effect=revoke):
            failure = self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(failure["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(failure["error"]["details"]["dispatch_state"], "dispatched")
        self.assertTrue((target / "manifest.json").is_file())
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"]["outcome"]["persistence"], "unknown")
        self.cli("operation", "query", "--id", ident, status=4)
        scope.write_bytes(original_scope)
        self.cli(*words, "--dry-run", status=6)
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        proof = self.cli("operation", "query", "--id", ident)["data"]["observation"]
        self.assertEqual(proof["installation_verification"]["can_register"], ["applied"])
        self.assertEqual(self.world.ops(), [])
