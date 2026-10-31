"""Diagnostics describe actual target guards and retain uncertainty without replay."""

import json
from unittest.mock import patch

from creo_cli import operations, service_installation
from creo_cli.core import Error
from tests import test_service_runtime as service_fixture
from tests.test_commands import Base


class RecoveryDiagnostics(Base):
    source = service_fixture.ServiceRuntime.source

    def unresolved_install(self, missing_ownership=False):
        source = self.source()
        target = self.ws / "components"
        words = ("service", "install", "--from", source, "--target", target)
        pre = self.cli(*words, "--dry-run")["data"]
        update = operations.update

        def fail(run):
            if (
                run.get("installation_ownership")
                if missing_ownership
                else run.get("driver_receipt")
            ):
                raise Error("E_IO", "owned diagnostic failure")
            return update(run)

        with patch.object(operations, "update", side_effect=fail):
            self.cli(*words, "--confirm", pre["confirm_token"], status=6)
        return source, target, pre["preview"]["operation_id"], words

    def test_public_diagnostics_match_related_and_sibling_previews(self):
        source, _target, ident, words = self.unresolved_install()
        before = self.receipts()
        status = self.cli("session", "status")["data"]
        self.assertNotIn("every write", str(status))
        self.assertNotIn("manual-accept", status["problems"][0]["fix"])
        self.assertEqual(status["operation_recovery"]["target_assessment"], "not_requested")
        self.assertEqual(status["operation_recovery"]["legacy_unscoped"], [])
        self.assertEqual(
            status["operation_recovery"]["scoped_unresolved"][0]["operation_id"], ident
        )
        denied = self.cli(*words, "--dry-run", status=6)
        self.assertEqual(denied["error"]["details"]["operation_ids"], [ident])
        sibling = self.cli(
            "service", "install", "--from", source, "--target", self.ws / "sibling", "--dry-run"
        )
        self.assertTrue(sibling["data"]["preview"]["can_apply"])
        self.assertEqual(
            next(r for r in self.receipts() if r["operation_id"] == ident),
            next(r for r in before if r["operation_id"] == ident),
        )
        reference = self.cli("reference")["data"]["extensions"]["creo"]["operation_recovery"]
        context = self.cli("context")["data"]["extensions"]["creo"]["operation_recovery"]
        checks = self.cli("doctor")["data"]["checks"]
        doctor = next(r for r in checks if r["check"] == "operation_recovery")
        self.assertEqual(context["contract"], reference)
        self.assertEqual(doctor["details"]["observation"]["contract"], reference)
        with patch("creo_cli.process_owner.abandoned", return_value=True):
            shown = self.cli("operation", "show", "--id", ident)["data"]
        self.assertNotIn("--model", shown["recovery_guidance"]["query"])
        self.assertIn("--outcome", shown["recovery_guidance"]["resolve_preview"])

    def test_historical_missing_ownership_remains_unknown_with_no_CAD(self):
        _source, target, ident, _words = self.unresolved_install(missing_ownership=True)
        self.server.close()
        before = self.receipts()
        with patch("creo_cli.process_owner.abandoned", return_value=True):
            shown = self.cli("operation", "show", "--id", ident)["data"]
        self.assertEqual(shown["operation_status"]["status"], "unknown")
        query = self.cli("operation", "query", "--id", ident)["data"]["observation"]
        self.assertEqual(query["installation_verification"]["can_register"], [])
        self.assertEqual(query["installation_verification"]["state"], "evidence_incomplete")
        self.assertFalse(target.exists())
        self.assertEqual(self.receipts(), before)

    def test_retained_show_never_observes_installation_under_revoked_scope(self):
        _source, _target, ident, _words = self.unresolved_install()
        scope = self.root / "scope.json"
        scope.write_text(json.dumps(json.loads(scope.read_text()) | {"revoked": True}))
        with patch.object(
            service_installation,
            "target_snapshot",
            side_effect=AssertionError("unexpected disk observation"),
        ):
            result = self.cli("operation", "show", "--id", ident)["data"]
        self.assertEqual(result["operation_status"]["status"], "unknown")
        self.assertEqual(result["operation_status"]["receipt"]["outcome"]["persistence"], "unknown")
