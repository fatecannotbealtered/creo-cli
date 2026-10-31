"""Bounded model metadata/discard behavior; substitute service, never native evidence."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests.fixture import Refused
from tests.test_commands import ROOT, Base


class ModelManagement(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def test_unreadable_common_name_or_modifiability_refuses(self):
        model = self.world.models["block.prt"]
        for proof in (
            {"readable": False, "modifiable": True, "value": None},
            {"readable": True, "modifiable": None, "value": None},
        ):
            with self.subTest(proof=proof):
                model["common_name_readback"] = proof
                self.cli(
                    "model",
                    "set-common-name",
                    "--model",
                    "block",
                    "--name",
                    "SYNTH_R18",
                    "--dry-run",
                    status=1,
                )
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_modified_unknown_is_not_clean_for_close_or_discard(self):
        self.world.models["block.prt"]["modified"] = None
        for command in ("close", "discard"):
            with self.subTest(command=command):
                self.cli(
                    "model",
                    command,
                    "--model",
                    "block",
                    *(["--dangerous"] if command == "discard" else []),
                    "--dry-run",
                    status=1,
                )
        self.assertNotIn("model.close", self.world.ops())
        self.assertNotIn("model.discard", self.world.ops())

    def test_window_closed_erase_failed_is_not_unchanged(self):
        original = self.world.op

        def fail(op, request):
            if op == "model.close":
                self.world.models["block.prt"]["window_closed"] = True
                raise Refused(
                    "E_CREO", "injected Erase failure after window close", stage="model_erase"
                )
            return original(op, request)

        with patch.object(self.world, "op", side_effect=fail):
            plan = self.cli("model", "close", "--model", "block", "--dry-run")["data"]
            error = self.cli(
                "model", "close", "--model", "block", "--confirm", plan["confirm_token"], status=1
            )["error"]
        self.assertIn("block.prt", self.world.models)
        self.assertNotEqual(error["details"]["receipt_status"], "failed_unchanged")

    def test_discard_without_verified_saved_baseline_refuses(self):
        self.world.models["block.prt"]["modified"] = True
        self.cli("model", "discard", "--model", "block", "--dangerous", "--dry-run", status=1)
        self.assertNotIn("model.discard", self.world.ops())

    def test_common_name_collateral_material_change_fails(self):
        original = self.world.op

        def corrupt(op, request):
            result = original(op, request)
            if op == "model.set-common-name":
                self.world.models["block.prt"]["material"] = "WRONG_MATERIAL"
            return result

        with patch.object(self.world, "op", side_effect=corrupt):
            plan = self.cli(
                "model", "set-common-name", "--model", "block", "--name", "SYNTH_R18", "--dry-run"
            )["data"]
            self.cli(
                "model",
                "set-common-name",
                "--model",
                "block",
                "--name",
                "SYNTH_R18",
                "--confirm",
                plan["confirm_token"],
                status=1,
            )

    def test_common_name_roundtrip_and_same_value_dirty_receipt(self):
        original_files = list(self.ws.glob("block.prt.*"))
        first = self.gated("model", "set-common-name", "--model", "block", "--name", "SYNTH_R18")[
            "data"
        ]
        self.assertEqual(first["receipt"]["outcome"]["persistence"], "unsaved")
        second = self.gated("model", "set-common-name", "--model", "block", "--name", "SYNTH_R18")[
            "data"
        ]
        self.assertEqual(second["receipt"]["outcome"]["change"], "not_applied")
        self.assertEqual(second["receipt"]["outcome"]["persistence"], "unsaved")
        self.gated("model", "set-common-name", "--model", "block", "--name", "ANOTHER")
        self.gated("model", "set-common-name", "--model", "block", "--name", "SYNTH_R18")
        self.assertEqual(self.world.models["block.prt"]["common_name"], "SYNTH_R18")
        self.assertEqual(list(self.ws.glob("block.prt.*")), original_files)

    def test_verified_baseline_discard_keeps_disk_and_sibling(self):
        self.gated("model", "save", "--model", "block")
        self.part("other.prt")
        other = copy.deepcopy(self.world.models["other.prt"])
        self.world.models["block.prt"]["modified"] = True
        files = {p.name: p.read_bytes() for p in self.ws.glob("block.prt.*")}
        result = self.gated("model", "discard", "--model", "block", dangerous=True)["data"]
        self.assertEqual(result["receipt"]["outcome"]["change"], "applied")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unchanged")
        self.assertNotIn("block.prt", self.world.models)
        self.assertEqual(self.world.models["other.prt"], other)
        self.assertEqual({p.name: p.read_bytes() for p in self.ws.glob("block.prt.*")}, files)

    def test_changed_native_common_name_without_modified_flag_is_unsaved(self):
        original = self.world.op

        def native_clean_flag(op, request):
            result = original(op, request)
            if op == "model.set-common-name":
                self.world.models["block.prt"]["modified"] = False
                result["modified"] = False
            return result

        with patch.object(self.world, "op", side_effect=native_clean_flag):
            result = self.gated(
                "model", "set-common-name", "--model", "block", "--name", "R18_NATIVE_FLAG"
            )["data"]
        self.assertIs(result["result"]["readback"]["modified"], False)
        self.assertEqual(result["receipt"]["outcome"]["change"], "applied")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.cli("model", "close", "--model", "block", "--dry-run", status=6)
        self.assertNotIn("model.close", self.world.ops())
        self.gated("model", "save", "--model", "block")
        self.gated("model", "close", "--model", "block")

    def fresh(self, *args, status=0):
        p = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            timeout=40,
        )
        self.assertEqual(p.returncode, status, p.stdout[:1200])
        return json.loads(p.stdout)

    def discarded_args(self):
        self.gated("model", "save", "--model", "block")
        self.world.models["block.prt"]["modified"] = True
        return ("model", "discard", "--model", "block", "--dangerous")

    def test_discard_reply_loss_new_process_observes_absence_and_full_guards(self):
        words = self.discarded_args()
        preview = self.cli(*words, "--dry-run")["data"]
        self.world.drop = "model.discard"
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.world.drop = None
        ident = preview["preview"]["operation_id"]
        observed = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")
        proof = observed["data"]["observation"]["model_management_verification"]
        self.assertEqual(proof["can_register"], ["applied"])
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent absence, every disk version and protected session state match",
        )
        self.fresh(*words, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("model.discard"), 1)

    def test_discard_window_failure_is_partial_unsaved_and_applied_is_refused(self):
        words = self.discarded_args()
        original = self.world.op

        def failure(op, request):
            if op == "model.discard":
                self.world.models["block.prt"]["window_closed"] = True
                raise Refused("E_CREO", "erase failed after window changed", stage="model_erase")
            return original(op, request)

        with patch.object(self.world, "op", side_effect=failure):
            preview = self.cli(*words, "--dry-run")["data"]
            error = self.cli(*words, "--confirm", preview["confirm_token"], status=1)["error"]
        self.assertEqual(error["details"]["receipt"]["outcome"]["change"], "partial")
        self.assertEqual(error["details"]["receipt"]["outcome"]["persistence"], "unsaved")
        ident = preview["preview"]["operation_id"]
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Model still exists and only its window was closed",
            status=1,
        )
        query = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")
        self.assertEqual(
            query["data"]["observation"]["model_management_verification"]["can_register"],
            ["partial"],
        )

    def test_discard_never_started_preserves_dirty_model(self):
        words = self.discarded_args()
        before = copy.deepcopy(self.world.models)
        self.world.fail = (
            "model.discard",
            {"code": "E_CONFLICT", "message": "refused before close"},
        )
        result = self.gated(*words, status=6)["error"]
        self.assertEqual(self.world.models, before)
        self.assertEqual(result["details"]["receipt"]["outcome"]["change"], "not_applied")
        self.assertEqual(result["details"]["receipt"]["outcome"]["persistence"], "unsaved")

    def test_discard_saved_file_drift_or_memory_drift_zero_dispatch(self):
        words = self.discarded_args()
        preview = self.cli(*words, "--dry-run")["data"]
        file = Path(self.world.models["block.prt"]["origin"])
        raw = file.read_bytes()
        file.write_bytes(raw + b" external")
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        file.write_bytes(raw)
        preview = self.cli(*words, "--dry-run")["data"]
        self.world.models["block.prt"]["common_name"] = "EXTERNAL"
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.assertNotIn("model.discard", self.world.ops())

    def test_dependency_or_unsaved_new_part_is_refused(self):
        words = self.discarded_args()
        self.world.models["block.prt"]["native_dependencies"] = ["other.prt"]
        self.cli(*words, "--dry-run", status=6)
        self.world.models["block.prt"].pop("native_dependencies")
        self.world.models["block.prt"]["origin"] = None
        for p in self.ws.glob("block.prt.*"):
            p.unlink()
        self.cli(*words, "--dry-run", status=1)
        self.assertNotIn("model.discard", self.world.ops())

    def test_common_name_file_identity_and_origin_drift_zero_dispatch(self):
        words = ("model", "set-common-name", "--model", "block", "--name", "SYNTH")
        first = self.cli(*words, "--dry-run")["data"]
        origin = Path(self.world.models["block.prt"]["origin"])
        replacement = origin.with_suffix(".replacement")
        replacement.write_bytes(origin.read_bytes())
        replacement.replace(origin)
        self.cli(*words, "--confirm", first["confirm_token"], status=6)
        second = self.cli(*words, "--dry-run")["data"]
        elsewhere = self.ws / "another-source"
        elsewhere.mkdir()
        other_file = elsewhere / origin.name
        other_file.write_bytes(origin.read_bytes())
        self.world.models["block.prt"]["origin"] = str(other_file)
        self.cli(*words, "--confirm", second["confirm_token"], status=6)
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_readonly_confirmation_and_wrong_target_never_dispatch(self):
        for command in ("set-common-name", "discard"):
            with self.subTest(command=command):
                words = (
                    self.discarded_args()
                    if command == "discard"
                    else ("model", command, "--model", "block", "--name", "SYNTH")
                )
                preview = self.cli(*words, "--dry-run")["data"]
                old = self.env["CREO_CLI_PERMISSION"]
                self.env["CREO_CLI_PERMISSION"] = "read"
                try:
                    self.cli(*words, "--confirm", preview["confirm_token"], status=4)
                finally:
                    self.env["CREO_CLI_PERMISSION"] = old
                wrong = list(words)
                wrong[wrong.index("--model") + 1] = "missing.prt"
                self.cli(*wrong, "--dry-run", status=3)
        self.assertNotIn("model.discard", self.world.ops())
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_common_name_reply_loss_with_collateral_cannot_register_applied(self):
        self.part("other.prt")
        words = ("model", "set-common-name", "--model", "block", "--name", "SYNTH")
        preview = self.cli(*words, "--dry-run")["data"]
        self.world.drop = "model.set-common-name"
        self.cli(*words, "--confirm", preview["confirm_token"], status=6)
        self.world.drop = None
        self.world.models["other.prt"]["material"] = "EXTERNAL_CHANGED"
        ident = preview["preview"]["operation_id"]
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Changed another protected model; a matching name alone is insufficient",
            status=1,
        )
        query = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")
        self.assertEqual(
            query["data"]["observation"]["model_management_verification"]["can_register"],
            ["partial"],
        )

    def test_lost_reply_same_value_with_identical_state_is_not_applied(self):
        self.world.models["block.prt"]["common_name"] = "SAME"
        original = self.world.op

        def unchanged(op, request):
            data = original(op, request)
            if op == "model.set-common-name":
                self.world.models["block.prt"]["modified"] = False
                data["modified"] = False
            return data

        words = ("model", "set-common-name", "--model", "block", "--name", "SAME")
        with patch.object(self.world, "op", side_effect=unchanged):
            preview = self.cli(*words, "--dry-run")["data"]
            self.world.drop = "model.set-common-name"
            self.cli(*words, "--confirm", preview["confirm_token"], status=6)
            self.world.drop = None
            ident = preview["preview"]["operation_id"]
            result = self.fresh("operation", "query", "--id", ident, "--model", "block.prt")
        self.assertEqual(
            result["data"]["observation"]["model_management_verification"]["can_register"],
            ["not_applied"],
        )
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Identical complete state does not prove an applied change",
            status=1,
        )
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "not_applied",
            "--evidence",
            "Complete model, windows and files are identical to the frozen baseline",
        )
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(
            shown["extensions"]["creo"]["model_management_inspection"]["registered_outcome"],
            "not_applied",
        )
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")

    def test_final_receipt_failure_retains_reliable_checkpoint_for_both_paths(self):
        original = self.world.op

        def clean_flag(op, request):
            data = original(op, request)
            if op == "model.set-common-name":
                self.world.models["block.prt"]["modified"] = False
                data["modified"] = False
            return data

        self.world.op = clean_flag
        for command in ("set-common-name", "discard"):
            with self.subTest(command=command):
                if "block.prt" not in self.world.models:
                    self.part()
                words = (
                    self.discarded_args()
                    if command == "discard"
                    else ("model", command, "--model", "block", "--name", "SYNTH_FINAL")
                )
                preview = self.cli(*words, "--dry-run")["data"]
                ident = preview["preview"]["operation_id"]
                update = operations.update

                def fail(record, ident=ident, update=update):
                    if record.get("operation_id") == ident and record.get("driver_receipt"):
                        raise Error("E_IO", "owned final receipt fault")
                    return update(record)

                with patch.object(operations, "update", side_effect=fail):
                    self.cli(*words, "--confirm", preview["confirm_token"], status=6)
                with patch.dict(os.environ, self.env, clear=True):
                    record = operations.get(ident)
                self.assertEqual(record["status"], "running")
                self.assertIsNone(record.get("driver_receipt"))
                shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
                self.assertEqual(shown["receipt"]["outcome"]["execution"], "unknown")
                self.fresh(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "applied",
                    "--evidence",
                    "Complete independent model and window and file observations agree",
                )
                self.fresh(*words, "--confirm", preview["confirm_token"], status=6)
                if command == "set-common-name":
                    self.fresh("model", "close", "--model", "block", "--dry-run", status=6)
