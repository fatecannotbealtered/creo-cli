"""Public installation plans, immutable source inputs and durable partial-copy outcomes."""

import json
import os
import subprocess
import sys
from unittest.mock import patch

from creo_cli import operations, service_bundle, service_installation
from creo_cli.core import Error, digest
from tests.test_commands import ROOT, Base


class ServiceRuntime(Base):
    def setUp(self):
        super().setUp()
        scope = self.root / "scope.json"
        data = json.loads(scope.read_text())
        data.update(roots=[str(self.root)], outputs=[str(self.root)])
        scope.write_text(json.dumps(data), encoding="utf-8")

    def source(self):
        source = self.ws / "source bundle"
        source.mkdir()
        (source / service_bundle.JAR).write_bytes(b"fixture jar: not a real service")
        (source / service_bundle.DLL).write_bytes(b"fixture native library")
        manifest = service_bundle.manifest_for(source, version="1.0.0", protocol=2, creo={})
        (source / service_bundle.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        return source

    def test_preallocated_operation_and_five_dimensions_without_CAD(self):
        source = self.source()
        self.server.close()
        preview = self.cli("service", "install", "--from", source, "--dry-run")["data"]
        operation_id = preview["preview"]["operation_id"]
        planned = self.cli("operation", "show", "--id", operation_id)["data"]
        self.assertEqual(planned["operation_status"]["status"], "planned")
        applied = self.cli(
            "service", "install", "--from", source, "--confirm", preview["confirm_token"]
        )["data"]
        self.assertEqual(applied["operation_id"], operation_id)
        self.assertEqual(applied["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(applied["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertFalse(applied["result"]["creo_load_verified"])

    def test_same_bytes_source_replacement_refuses_before_copy(self):
        source = self.source()
        preview = self.cli("service", "install", "--from", source, "--dry-run")["data"]
        replacement = source / "replacement"
        replacement.write_bytes((source / service_bundle.JAR).read_bytes())
        os.replace(replacement, source / service_bundle.JAR)
        result = self.cli(
            "service",
            "install",
            "--from",
            source,
            "--confirm",
            preview["confirm_token"],
            status=6,
        )
        self.assertEqual(result["error"]["code"], "E_CONFLICT")
        self.assertFalse((self.root / "state/service/1.0.0").exists())

    def test_copy_failure_with_real_written_bytes_is_not_unchanged(self):
        source = self.source()
        preview = self.cli("service", "install", "--from", source, "--dry-run")["data"]
        original = service_installation._copy_file

        def fail_dll(src, dst, *args, **kwargs):
            if str(src).endswith(service_bundle.DLL):
                raise OSError("owned partial-copy failure")
            return original(src, dst, *args, **kwargs)

        with patch.object(service_installation, "_copy_file", side_effect=fail_dll):
            result = self.cli(
                "service",
                "install",
                "--from",
                source,
                "--confirm",
                preview["confirm_token"],
                status=1,
            )
        self.assertFalse(result["ok"])
        record = self.receipts()[0]
        self.assertNotIn(record["status"], ("failed_unchanged", "failed_before_write", "completed"))
        self.assertEqual(service_bundle.installed(self.root / "state"), [])
        inspected = self.cli("operation", "query", "--id", record["operation_id"])["data"]
        proof = inspected["observation"]["installation_verification"]
        self.assertEqual(proof["state"], "partial_files")
        self.assertEqual(proof["can_register"], ["partial"])
        rejected = self.cli(
            "operation",
            "resolve",
            "--id",
            record["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "Owned partial files inspected through the public query",
            "--dry-run",
            status=1,
        )
        self.assertEqual(rejected["error"]["code"], "E_VERIFY_FAILED")
        original_receipt = digest(record["driver_receipt"])
        self.gated(
            "operation",
            "resolve",
            "--id",
            record["operation_id"],
            "--outcome",
            "partial",
            "--evidence",
            "Public query proves the owned JAR exists and the DLL and manifest do not",
        )
        self.assertEqual(digest(self.receipts()[0]["driver_receipt"]), original_receipt)
        self.assertEqual(self.world.ops(), [])

    def child(self, *words, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, words), "--compact"],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            timeout=15,
        )
        body = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(result.returncode, expected, body)
        return body

    def test_final_receipt_failure_new_process_inspection_and_explicit_registration(self):
        source = self.source()
        pre = self.cli("service", "install", "--from", source, "--dry-run")["data"]
        ident = pre["preview"]["operation_id"]
        original = operations.update

        def fail_only_final(record):
            if record.get("command") == "service install" and record.get("driver_receipt"):
                raise Error("E_IO", "owned final receipt failure")
            return original(record)

        with patch.object(operations, "update", side_effect=fail_only_final):
            result = self.cli(
                "service",
                "install",
                "--from",
                source,
                "--confirm",
                pre["confirm_token"],
                status=6,
            )
        self.assertEqual(result["error"]["code"], "E_OUTCOME_UNKNOWN")
        stored = self.receipts()[0]
        self.assertEqual(stored["status"], "running")
        self.assertEqual(stored["driver_stage"], "finalizing")
        self.assertIsNone(stored["driver_receipt"])
        shown = self.child("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "unknown")
        proof = self.child("operation", "query", "--id", ident)["data"]["observation"][
            "installation_verification"
        ]
        self.assertEqual(proof["can_register"], ["applied"])
        self.assertFalse(proof["creo_load_verified"])
        self.child("service", "install", "--from", source, "--dry-run", expected=6)
        child_target = self.root / "state/service/1.0.0/nested"
        with patch.dict(self.env, {"CREO_CLI_WORKSPACE": str(self.root)}):
            blocked = self.cli(
                "service",
                "install",
                "--from",
                source,
                "--target",
                child_target,
                "--dry-run",
                status=6,
            )
        self.assertEqual(blocked["error"]["details"]["operation_ids"], [ident])
        self.assertFalse(child_target.exists())
        resolve = (
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent file hashes and exact operation marker match the retained package",
        )
        planned = self.child(*resolve, "--dry-run")["data"]
        self.child(*resolve, "--confirm", planned["confirm_token"])
        self.child(
            "service", "install", "--from", source, "--confirm", pre["confirm_token"], expected=6
        )
        self.assertEqual(self.world.ops(), [])

    def test_reference_supplies_the_pinned_scope_and_reference_definitions(self):
        data = self.cli("reference", "--command", "service install")["data"]
        for name in ("scope", "common"):
            self.assertIn(f"urn:tool-driver-cli-spec:{name}:2.0", data["public_schemas"])
            self.assertNotIn("driver_" + name, data["schemas"])
        self.assertFalse(
            any(k.startswith("urn:tool-driver-cli-spec:") for k in data["json_schemas"])
        )

    def test_explicit_unicode_target_and_scope_refusal(self):
        source = self.source()
        target = self.ws / "组件 安装"
        data = self.gated("service", "install", "--from", source, "--target", target)["data"]
        self.assertEqual(data["result"]["installed_to"], str(target))
        self.assertIn(str(target), (target / "protk.dat").read_text(encoding="utf-8"))
        self.assertEqual(data["receipt"]["outcome"]["persistence"], "saved")
        scope = self.root / "scope.json"
        value = json.loads(scope.read_text())
        value["effects"] = ["observe"]
        scope.write_text(json.dumps(value), encoding="utf-8")
        denied = self.cli(
            "service", "install", "--from", source, "--target", self.ws / "denied", "--dry-run"
        )["data"]
        self.assertFalse(denied["preview"]["can_apply"])
        self.assertFalse((self.ws / "denied").exists())

    def test_doctor_separates_disk_files_from_missing_runtime_dependencies(self):
        source = self.source()
        target = self.ws / "inspection"
        self.gated("service", "install", "--from", source, "--target", target)
        diagnosed = self.cli(
            "doctor",
            "--installation",
            target,
            "--creo",
            self.ws / "absent-creo",
            "--java-home",
            self.ws / "absent-jdk",
        )["data"]
        checks = {row["check"]: row for row in diagnosed["checks"]}
        self.assertEqual(checks["installation_files"]["status"], "pass")
        self.assertEqual(checks["installation_runtime"]["status"], "warn")
        self.assertFalse(checks["installation_files"]["details"]["observation"]["loaded_verified"])
        (target / service_bundle.JAR).write_bytes(b"tampered")
        checked = self.cli("doctor", "--installation", target)["data"]
        by_name = {row["check"]: row for row in checked["checks"]}
        self.assertEqual(by_name["installation_files"]["status"], "fail")

    def test_unresolved_file_targets_conflict_at_parent_or_child_but_not_siblings(self):
        from creo_cli import driver

        target = self.ws / "components"
        identity = service_installation.target_identity(target)
        run = {
            "operation_id": "a" * 32,
            "status": "unknown",
            "driver_plan": {"target": identity},
            "driver_receipt": None,
        }
        with (
            patch.object(operations, "selected_runs", return_value=[run]),
            patch.object(driver, "status", return_value={"status": "unknown"}),
        ):
            for path in (target, target / "child", target.parent):
                with self.assertRaises(Error) as caught:
                    driver.require_clear(service_installation.target_identity(path))
                self.assertEqual(caught.exception.code, "E_CONFLICT")
            driver.require_clear(service_installation.target_identity(self.ws / "components2"))

    def test_ownership_record_failure_cannot_copy_any_files(self):
        source = self.source()
        pre = self.cli("service", "install", "--from", source, "--dry-run")["data"]
        original = operations.update

        def fail_ownership(row):
            if row.get("installation_ownership"):
                raise Error("E_IO", "owned pre-dispatch storage failure")
            return original(row)

        with patch.object(operations, "update", side_effect=fail_ownership):
            result = self.cli(
                "service", "install", "--from", source, "--confirm", pre["confirm_token"], status=6
            )
        self.assertFalse(result["ok"])
        self.assertFalse(result["error"]["details"]["request_sent"])
        self.assertFalse((self.root / "state/service/1.0.0").exists())
        self.assertEqual(self.world.ops(), [])
