"""Public export retention tests against controlled adapters; no Creo/native claim."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import export_record, operations
from creo_cli.core import Error
from tests.test_commands import ROOT
from tests.test_features import Built


class ExportPreservation(Built):
    def plan(self, output="retained.stp"):
        self.block()
        args = ("artifact", "export", "--model", "block.prt", "--output", output)
        preview = self.cli(*args, "--dry-run")["data"]
        return args, preview

    def fresh(self, *args, status=0):
        result = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(status, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_invalid_header_keeps_real_generated_stage(self):
        args, preview = self.plan()
        original, sent = self.world.export, {}

        def bad_header(request):
            reply = original(request)
            sent.update(request)
            Path(request["file"]).write_bytes(b"not STEP: retained failure evidence")
            return reply

        with patch.object(self.world, "export", side_effect=bad_header):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertTrue(Path(sent["file"]).is_file(), "real generated failure evidence was deleted")
        self.assertFalse((self.ws / "retained.stp").exists())

    def test_foreign_service_file_cannot_replace_operation_stage(self):
        args, preview = self.plan()
        foreign = self.ws / "unrelated.stp"
        sentinel = b"ISO-10303-21; foreign fixture must remain here"
        foreign.write_bytes(sentinel)

        def foreign_reply(request):
            return {"model": request["model"], "format": "step", "files": [{"path": str(foreign)}]}

        with patch.object(self.world, "export", side_effect=foreign_reply):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(sentinel, foreign.read_bytes())
        self.assertFalse((self.ws / "retained.stp").exists())

    def test_output_created_after_dispatch_preserves_both_files(self):
        args, preview = self.plan()
        original, sent = self.world.export, {}
        output, sentinel = self.ws / "retained.stp", b"competing output preserved"

        def conflict(request):
            reply = original(request)
            sent.update(request)
            output.write_bytes(sentinel)
            return reply

        with patch.object(self.world, "export", side_effect=conflict):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(sentinel, output.read_bytes())
        self.assertTrue(Path(sent["file"]).is_file(), "unpublished export evidence was deleted")

    def retained(self, ident):
        with patch.dict(os.environ, self.env, clear=True):
            return operations.get(ident)

    def inspect_in_new_process_without_CAD(self, ident):
        before = len(self.world.events)
        offline = dict(self.env, CREO_CLI_SERVICE_URL="http://127.0.0.1:1")
        with patch.object(self, "env", offline):
            query = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        self.assertEqual(before, len(self.world.events))
        return query["observation"]["export_verification"]

    def test_success_reports_header_only_and_keeps_owned_files(self):
        args, preview = self.plan()
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertTrue(result["result"]["generated"])
        self.assertTrue(result["result"]["published"])
        self.assertEqual("not_checked", result["result"]["consumer_verification"])
        self.assertEqual("file_identity_and_header_only", result["result"]["verification_scope"])
        run = self.retained(preview["preview"]["operation_id"])
        self.assertEqual("published", run["driver_export"]["phase"])
        self.assertTrue(Path(run["driver_export"]["staged_path"]).is_file())
        self.assertEqual(
            "published_output", result["receipt"]["extensions"]["creo"]["export_recovery"]["state"]
        )
        self.assertEqual(
            "published_output",
            self.inspect_in_new_process_without_CAD(run["operation_id"])["state"],
        )

    def test_link_publication_race_never_overwrites(self):
        args, preview = self.plan()
        original = os.link
        output, sentinel = self.ws / "retained.stp", b"racing output preserved"
        publications = []

        def raced_link(source, target, *args, **kwargs):
            if Path(target) == output:
                publications.append((source, target))
                output.write_bytes(sentinel)
            return original(source, target, *args, **kwargs)

        with patch("creo_cli.commands.model.os.link", side_effect=raced_link):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(1, len(publications))
        self.assertEqual(sentinel, output.read_bytes())
        run = self.retained(preview["preview"]["operation_id"])
        self.assertTrue(Path(run["driver_export"]["staged_path"]).is_file())
        proof = self.inspect_in_new_process_without_CAD(run["operation_id"])
        self.assertFalse(proof["published"])
        self.assertEqual("evidence_incomplete", proof["state"])
        self.assertEqual(
            [run["driver_export"]["staged_path"]], [item["path"] for item in proof["artifacts"]]
        )

    def test_real_http_lost_reply_is_queryable_without_export_replay(self):
        args, preview = self.plan()
        ident = preview["preview"]["operation_id"]
        self.world.drop = "model.export"
        reply = self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual("E_OUTCOME_UNKNOWN", reply["error"]["code"])
        run = self.retained(ident)
        self.assertEqual("unknown", run["status"])
        self.assertEqual("dispatching", run["driver_export"]["phase"])
        self.assertTrue(Path(run["driver_export"]["staged_path"]).is_file())
        self.assertFalse((self.ws / "retained.stp").exists())
        proof = self.inspect_in_new_process_without_CAD(ident)
        self.assertEqual("generated_unpublished", proof["state"])
        self.assertFalse(proof["automatic_publication"])
        self.assertEqual([], proof["can_register"])
        shown = self.fresh("operation", "show", "--id", ident)["data"]
        guidance = shown["recovery_guidance"]
        self.assertEqual(
            ["operation", "query", "--id", ident, "--model", "block.prt"], guidance["query"]
        )
        self.assertIn("never calls CAD", guidance["inspection_dispatch"])
        self.assertIn("do not prove a pending native call ended", guidance["inspection_dispatch"])
        count = self.world.ops().count("model.export")
        self.fresh(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(count, self.world.ops().count("model.export"))
        self.assertEqual(run, self.retained(ident), "query altered the original write receipt")

    def test_final_public_receipt_failure_keeps_publication_and_durable_binding(self):
        args, preview = self.plan()
        update = operations.update

        def fail_public(run):
            if run.get("driver_receipt") is not None:
                raise Error("E_IO", "controlled final receipt storage failure")
            return update(run)

        with patch.object(operations, "update", side_effect=fail_public):
            self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        ident = preview["preview"]["operation_id"]
        run = self.retained(ident)
        self.assertEqual("published", run["driver_export"]["phase"])
        self.assertTrue((self.ws / "retained.stp").is_file())
        proof = self.inspect_in_new_process_without_CAD(ident)
        self.assertEqual("published_output", proof["state"])
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual("unknown", shown["status"])
        # The returned native call is a known fact despite the missing final receipt.
        self.assertEqual("completed", shown["receipt"]["outcome"]["execution"])
        self.assertEqual(
            "not_observed", shown["receipt"]["extensions"]["creo"]["export_recovery"]["state"]
        )
        count = self.world.ops().count("model.export")
        self.fresh(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(count, self.world.ops().count("model.export"))

    def test_header_verification_error_retains_generated_bytes(self):
        args, preview = self.plan()
        original = export_record.read_file
        raised = False

        def fail_once(path, fmt):
            nonlocal raised
            if not raised and Path(path).exists():
                raised = True
                raise Error("E_VERIFY_INCOMPLETE", "controlled local file verification failure")
            return original(path, fmt)

        with patch.object(export_record, "read_file", side_effect=fail_once):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        run = self.retained(preview["preview"]["operation_id"])
        self.assertTrue(Path(run["driver_export"]["staged_path"]).is_file())
        self.assertFalse((self.ws / "retained.stp").exists())
        self.assertEqual(
            "generated_unpublished",
            self.inspect_in_new_process_without_CAD(run["operation_id"])["state"],
        )

    def test_ownership_storage_failure_prevents_dispatch(self):
        args, preview = self.plan()
        update = operations.update

        def refuse(run):
            if run.get("driver_export"):
                raise Error("E_IO", "controlled ownership storage unavailable")
            return update(run)

        with patch.object(operations, "update", side_effect=refuse):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertNotIn("model.export", self.world.ops())
        self.assertFalse((self.ws / "retained.stp").exists())

    def test_retained_path_tampering_is_not_followed(self):
        args, preview = self.plan()
        self.world.drop = "model.export"
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        run = self.retained(preview["preview"]["operation_id"])
        foreign = self.ws / "foreign.stp"
        foreign.write_bytes(b"ISO-10303-21; unrelated")
        run["driver_export"]["staged_path"] = str(foreign)
        with patch.dict(os.environ, self.env, clear=True):
            proof = export_record.inspect(run)
        self.assertEqual("evidence_incomplete", proof["state"])
        self.assertEqual({}, proof["files"])
        self.assertEqual([], proof["artifacts"])

    def test_verified_checkpoint_failure_keeps_unpublished_file_and_unknown(self):
        args, preview = self.plan()
        update = operations.update

        def fail_verified(run):
            if run.get("driver_export", {}).get("phase") == "verified":
                raise Error("E_IO", "controlled verified-file checkpoint failure")
            return update(run)

        with patch.object(operations, "update", side_effect=fail_verified):
            result = self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual("E_IO", result["error"]["code"])
        self.assertEqual("unknown", result["error"]["details"]["receipt_status"])
        run = self.retained(preview["preview"]["operation_id"])
        self.assertEqual("unknown", run["status"])
        self.assertTrue(Path(run["driver_export"]["staged_path"]).is_file())
        self.assertFalse((self.ws / "retained.stp").exists())
        proof = self.inspect_in_new_process_without_CAD(run["operation_id"])
        self.assertTrue(proof["generated"])
        self.assertFalse(proof["published"])

    def test_same_bytes_replaced_output_is_not_owned_publication(self):
        args, preview = self.plan()
        self.cli(*args, "--confirm", preview["confirm_token"])
        output, replacement = self.ws / "retained.stp", self.ws / "replacement.stp"
        replacement.write_bytes(output.read_bytes())
        replacement.replace(output)
        proof = self.inspect_in_new_process_without_CAD(preview["preview"]["operation_id"])
        self.assertEqual("evidence_incomplete", proof["state"])
        self.assertFalse(proof["published"])
        self.assertTrue(all(item["path"] != str(output) for item in proof["artifacts"]))

    def test_in_place_stage_change_invalidates_current_publication(self):
        self.assert_in_place_link_change("staged_path", receipt_failure=False)

    def test_in_place_output_change_invalidates_current_publication(self):
        self.assert_in_place_link_change("requested_output", receipt_failure=False)

    def test_in_place_stage_change_does_not_upgrade_unknown_receipt(self):
        self.assert_in_place_link_change("staged_path", receipt_failure=True)

    def test_in_place_output_change_does_not_upgrade_unknown_receipt(self):
        self.assert_in_place_link_change("requested_output", receipt_failure=True)

    def assert_in_place_link_change(self, changed_name, *, receipt_failure):
        args, preview = self.plan()
        update = operations.update

        def fail_public(run):
            if receipt_failure and run.get("driver_receipt") is not None:
                raise Error("E_IO", "controlled final receipt storage failure")
            return update(run)

        with patch.object(operations, "update", side_effect=fail_public):
            self.cli(
                *args, "--confirm", preview["confirm_token"], status=6 if receipt_failure else 0
            )
        ident = preview["preview"]["operation_id"]
        retained = self.retained(ident)
        record = retained["driver_export"]
        staged, output = Path(record["staged_path"]), Path(record["requested_output"])
        self.assertTrue(staged.samefile(output), "publication is a hard link, not a backup")
        prior = staged.stat()
        # Preserve the file's inode and original mtime: the current byte digest must
        # invalidate the historic publication even when those metadata still match.
        with Path(record[changed_name]).open("ab") as stream:
            stream.write(b"\ncontrolled in-place modification\n")
        os.utime(staged, ns=(prior.st_atime_ns, prior.st_mtime_ns))
        self.assertEqual(prior.st_ino, staged.stat().st_ino)
        self.assertEqual(staged.read_bytes(), output.read_bytes())
        proof = self.inspect_in_new_process_without_CAD(ident)
        self.assertEqual("evidence_incomplete", proof["state"])
        self.assertFalse(proof["published"])
        self.assertEqual([], proof["can_register"])
        self.assertFalse(proof["automatic_replay"])
        self.assertFalse(proof["automatic_publication"])
        for label in ("staged", "output"):
            self.assertNotEqual(record["verified_file"]["sha256"], proof["files"][label]["sha256"])
        self.assertEqual(retained, self.retained(ident), "inspection changed original receipt")
        count = self.world.ops().count("model.export")
        self.fresh(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(count, self.world.ops().count("model.export"))

    def test_record_only_show_does_not_read_files_after_scope_narrows(self):
        self.assert_record_only_show_scope(False)

    def test_lost_reply_record_only_show_does_not_read_after_scope_narrows(self):
        self.assert_record_only_show_scope(True)

    def assert_record_only_show_scope(self, lost_reply):
        args, preview = self.plan()
        if lost_reply:
            self.world.drop = "model.export"
        update = operations.update

        def fail_public(run):
            if run.get("driver_receipt") is not None:
                raise Error("E_IO", "controlled final receipt storage failure")
            return update(run)

        with patch.object(operations, "update", side_effect=fail_public):
            self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        scope_path = Path(self.env["CREO_CLI_SCOPE_FILE"])
        scope = json.loads(scope_path.read_text(encoding="utf-8"))
        restricted = self.ws / "restricted"
        restricted.mkdir()
        scope.update(roots=[str(restricted)], outputs=[str(restricted)])
        scope_path.write_text(json.dumps(scope), encoding="utf-8")
        ident = preview["preview"]["operation_id"]
        before = len(self.world.events)
        with patch.object(export_record, "read_file", wraps=export_record.read_file) as read:
            self.cli("operation", "show", "--id", ident)
            self.assertEqual(
                0, read.call_count, "local retained history bypassed file observation scope"
            )
            self.cli("operation", "query", "--id", ident, "--model", "block.prt", status=4)
            self.assertEqual(0, read.call_count)
        self.assertEqual(before, len(self.world.events))

    def test_link_succeeded_before_publication_checkpoint_failure(self):
        args, preview = self.plan()
        checkpoint, failed = export_record.checkpoint, False

        def fail_published(run, **values):
            nonlocal failed
            if values.get("phase") == "published" and not failed:
                failed = True
                raise Error("E_IO", "controlled post-link checkpoint failure")
            return checkpoint(run, **values)

        with patch.object(export_record, "checkpoint", side_effect=fail_published):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        run = self.retained(preview["preview"]["operation_id"])
        self.assertEqual("unknown", run["status"])
        self.assertEqual("verified", run["driver_export"]["phase"])
        self.assertTrue((self.ws / "retained.stp").is_file())
        proof = self.inspect_in_new_process_without_CAD(run["operation_id"])
        self.assertEqual("published_output", proof["state"])
        count = self.world.ops().count("model.export")
        self.fresh(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(count, self.world.ops().count("model.export"))

    def test_domain_result_storage_failure_keeps_published_file(self):
        args, preview = self.plan()
        with patch.object(
            operations,
            "save_result",
            side_effect=Error("E_IO", "controlled result storage failure"),
        ):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        run = self.retained(preview["preview"]["operation_id"])
        self.assertEqual("unknown", run["status"])
        self.assertEqual("published", run["driver_export"]["phase"])
        self.assertEqual(
            "published_output",
            self.inspect_in_new_process_without_CAD(run["operation_id"])["state"],
        )
