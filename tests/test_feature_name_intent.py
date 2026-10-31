"""Public CLI feature identity counterexamples; fixture faults are not native evidence."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from creo_cli import operations
from tests import test_draft_runtime, test_features, test_shell_runtime
from tests.test_commands import RECT, ROOT


class PublicProcesses:
    """Every invocation, including recovery and record inspection, starts a new process."""

    def cli(self, *args, status=0, env=None, stdin=None):
        binary = os.environ.get("CREO_CLI_TEST_BINARY")
        invocation = [binary] if binary else [sys.executable, "-m", "creo_cli"]
        result = subprocess.run(
            [*invocation, *map(str, args)],
            cwd=ROOT,
            env=env or self.env,
            input=None if stdin is None else stdin.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
        output = json.loads(result.stdout)
        self.assertNotIn(self.world.token, result.stdout.decode() + result.stderr.decode())
        evidence = os.environ.get("CREO_CLI_NAME_TEST_EVIDENCE")
        if evidence:
            # Opt-in preservation of loopback failure/success evidence, never a real CAD log.
            folder = Path(evidence)
            folder.mkdir(parents=True, exist_ok=True)
            record = {
                "source": "public EXE against loopback fixture; no native claim"
                if binary
                else "public Python CLI against loopback fixture; no native claim",
                "arguments": [str(a) for a in args],
                "exit_code": result.returncode,
                "stdout": output,
                "stderr": result.stderr.decode(),
            }
            for i, word in enumerate(record["arguments"]):
                if word == "--confirm":
                    record["arguments"][i + 1] = "<fixture-confirm-token-redacted>"

            def redact(value):
                if isinstance(value, dict):
                    return {
                        k: "<fixture-confirm-token-redacted>" if k == "confirm_token" else redact(v)
                        for k, v in value.items()
                    }
                if isinstance(value, list):
                    return [redact(v) for v in value]
                return value

            path = folder / (self.id().replace(".", "-") + ".jsonl")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(redact(record), ensure_ascii=False) + "\n")
        self.assertEqual(result.returncode, status, output)
        self.assertEqual(output["ok"], status == 0, output)
        return output

    def fresh(self, *args, status=0):
        return self.cli(*args, status=status)


class BoundedNameCases(PublicProcesses):
    """One shared independent name criterion for normal, query, resolve and old evidence."""

    def frozen(self, preview):
        return preview["preview"]["extensions"]["creo"][self.intent_key]

    def inspection(self, *, wrong_name=False):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        ident = preview["preview"]["operation_id"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == self.native_op and wrong_name:
                # The service reply keeps the requested name, while its independent tree does not.
                result = copy.deepcopy(result)
                feature = self.world.feature(self.world.models["block.prt"], self.body["name"])
                self.assertEqual(result["feature"]["name"], self.body["name"])
                feature["name"] = "WRONG_NATIVE_NAME"
            return result

        self.world.drop = self.native_op
        try:
            with patch.object(self.world, "op", side_effect=changed):
                self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        finally:
            self.world.drop = None
        return args, preview, ident

    def register(self, ident):
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent native feature name, definition and complete geometry match frozen intent",
        )

    def test_requested_name_is_in_the_frozen_intent(self):
        preview = self.cli(*self.args(), "--dry-run")["data"]
        self.assertEqual(
            self.frozen(preview).get("name_intent"),
            {"policy": "requested", "name": self.body["name"]},
        )
        self.assertNotIn(self.native_op, self.world.ops())

    def test_omitted_name_freezes_native_default_without_guessing_spelling(self):
        body = {k: v for k, v in self.body.items() if k != "name"}
        args = self.args(body)
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertEqual(
            self.frozen(preview).get("name_intent"), {"policy": "native_default", "name": None}
        )
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")

    def native_default_name(self, value):
        body = {k: v for k, v in self.body.items() if k != "name"}
        args = self.args(body)
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == self.native_op:
                result = copy.deepcopy(result)
                feature = self.world.feature(
                    self.world.models["block.prt"], result["feature"]["id"]
                )
                feature["name"] = value
            return result

        with patch.object(self.world, "op", side_effect=changed):
            result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        self.assertEqual(self.world.ops().count(self.native_op), 1)

    def test_native_default_allows_observed_null_name(self):
        self.native_default_name(None)

    def test_native_default_allows_observed_empty_name(self):
        self.native_default_name("")

    def test_native_default_missing_independent_name_field_cannot_pass(self):
        body = {k: v for k, v in self.body.items() if k != "name"}
        args = self.args(body)
        preview = self.cli(*args, "--dry-run")["data"]
        old_ids = {str(f["id"]) for f in self.world.models["block.prt"]["features"]}
        original = self.world.op

        def missing(op, request):
            result = original(op, request)
            if op == "feature.list":
                result = copy.deepcopy(result)
                for row in result["features"]:
                    if str(row["id"]) not in old_ids:
                        row.pop("name", None)
            return result

        with patch.object(self.world, "op", side_effect=missing):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(self.world.ops().count(self.native_op), 1)

    def test_requested_name_service_reply_cannot_replace_independent_tree(self):
        args = self.args()
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == self.native_op:
                result = copy.deepcopy(result)
                self.assertEqual(result["feature"]["name"], self.body["name"])
                self.world.feature(self.world.models["block.prt"], self.body["name"])["name"] = (
                    "WRONG_NATIVE_NAME"
                )
            return result

        with patch.object(self.world, "op", side_effect=changed):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=1)["error"]
        self.assertEqual(error["details"]["receipt"]["outcome"]["verification"]["status"], "failed")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.assertEqual(self.world.ops().count(self.native_op), 1)

    def test_lost_reply_wrong_name_query_does_not_offer_applied(self):
        _, _, ident = self.inspection(wrong_name=True)
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        proof = query["observation"][self.query_key]
        self.assertFalse(proof["accepted"], proof)
        self.assertNotIn("applied", proof["can_register"])
        self.assertEqual(self.world.ops().count(self.native_op), 1)
        self.assertTrue(
            any(
                f["name"] == "WRONG_NATIVE_NAME" for f in self.world.models["block.prt"]["features"]
            )
        )

    def test_lost_reply_wrong_name_cannot_resolve_applied(self):
        _, _, ident = self.inspection(wrong_name=True)
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Correct geometry does not establish the requested independent feature name",
            "--dry-run",
            status=1,
        )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.assertEqual(self.world.ops().count(self.native_op), 1)
        self.assertTrue(
            any(
                f["name"] == "WRONG_NATIVE_NAME" for f in self.world.models["block.prt"]["features"]
            )
        )

    def test_correct_name_cross_process_registration_keeps_original_unknown_receipt(self):
        args, preview, ident = self.inspection()
        before = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]["receipt"]
        query = self.cli("operation", "query", "--id", ident, "--model", "block")["data"]
        self.assertEqual(query["observation"][self.query_key]["can_register"], ["applied"])
        self.register(ident)
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"], before)
        self.assertEqual(before["outcome"]["execution"], "unknown")
        self.assertEqual(
            shown["extensions"]["creo"][self.record_kind + "_inspection"]["evidence_status"],
            "verified",
        )
        self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count(self.native_op), 1)

    def historical(self, *, omit_intent):
        _, _, ident = self.inspection()
        self.register(ident)
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            original_receipt = copy.deepcopy(run["driver_receipt"])
            reference = run["driver_" + self.record_kind + "_resolution"]
            observation = operations.load_query(reference["evidence_id"])["observation"]
            proof = observation[self.record_kind + "_verification"]
            retained = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
            if omit_intent:
                # Historic records lack the new field even when request/reply once held a name.
                retained[self.retained_intent_key].pop("name_intent", None)
                proof["intent"] = copy.deepcopy(retained[self.retained_intent_key])
            else:
                previous = {
                    f["id"] for f in retained[self.before_key]["parts"]["block.prt"]["features"]
                }
                added = next(
                    f
                    for f in proof["current"]["parts"]["block.prt"]["features"]
                    if f["id"] not in previous
                )
                added["name"] = "WRONG_RETAINED_NAME"
            # Re-serialize the altered observation so file integrity is honestly valid.
            new = operations.save_query(run, observation)
            run["driver_" + self.record_kind + "_resolution"] |= {
                "evidence_id": new["evidence_id"],
                "sha256": new["sha256"],
            }
            operations.update(run)
        calls = len(self.world.ops())
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        proof = shown["extensions"]["creo"][self.record_kind + "_inspection"]
        self.assertEqual(proof["evidence_integrity"], "valid")
        self.assertEqual(proof["evidence_status"], "insufficient", proof)
        self.assertEqual(shown["receipt"], original_receipt)
        self.assertEqual(len(self.world.ops()), calls)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_old_intent_without_name_does_not_unlock_from_valid_hash(self):
        self.historical(omit_intent=True)

    def test_retained_wrong_name_does_not_unlock_from_valid_hash(self):
        self.historical(omit_intent=False)


class ShellNameIntent(BoundedNameCases, test_shell_runtime.ShellRuntime):
    native_op = "feature.shell"
    intent_key = "shell_intent"
    retained_intent_key = "prismatic_intent"
    before_key = "prismatic_before"
    query_key = "prismatic_verification"
    record_kind = "prismatic"


class DraftNameIntent(BoundedNameCases, test_draft_runtime.DraftRuntime):
    native_op = "feature.draft"
    intent_key = "draft_intent"
    retained_intent_key = "draft_intent"
    before_key = "draft_before"
    query_key = "draft_verification"
    record_kind = "prismatic_draft"


class OrdinaryFeatureIdentity(PublicProcesses, test_features.Built):
    def wrong_independent_row(self, field, value):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def changed(op, request):
            result = original(op, request)
            if op == "feature.extrude":
                result = copy.deepcopy(result)
                actual = self.world.feature(self.world.models["block.prt"], RECT["name"])
                self.assertNotEqual(result["feature"][field], value)
                actual[field] = value
            return result

        with patch.object(self.world, "op", side_effect=changed):
            self.cli(*args, "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(self.world.ops().count("feature.extrude"), 1)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_reply_name_does_not_replace_independent_added_feature_name(self):
        self.wrong_independent_row("name", "WRONG_NATIVE_NAME")

    def test_reply_type_does_not_replace_independent_added_feature_type(self):
        self.wrong_independent_row("type", "FEATTYPE_CUT")

    def test_reply_status_does_not_replace_independent_added_feature_status(self):
        self.wrong_independent_row("status", "FEAT_SUPPRESSED")


# Reuse setup and public helpers without repeating the existing shell/draft regression suite.
for _derived, _base in (
    (ShellNameIntent, test_shell_runtime.ShellRuntime),
    (DraftNameIntent, test_draft_runtime.DraftRuntime),
):
    for _name in vars(_base):
        if _name.startswith("test_") and _name not in vars(BoundedNameCases):
            setattr(_derived, _name, None)
del _derived, _base, _name
