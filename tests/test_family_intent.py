"""Public CLI faults for frozen whole-table intent; no native fault induction."""

import copy
from unittest.mock import patch

from creo_cli import operations
from tests import test_family_runtime
from tests.fixture import Refused


class FamilyIntent(test_family_runtime.FamilyRuntime):
    def setUp(self):
        super().setUp()
        self.extra = next(
            d["name"]
            for d in self.world.models["block.prt"]["dimensions"]
            if d.get("type") and d["name"] != self.depth and d["value"] > 0
        )

    def two_columns(self):
        body = copy.deepcopy(self.body)
        item = self.world._family_item(self.world.models["block.prt"], "dimension:" + self.extra)
        body["instances"][0]["values"]["dimension:" + self.extra] = item["generic_value"]
        self.gated(*self.words(body))
        self.save_close_instances()

    def test_dimension_aliases_cannot_assign_the_same_column_twice(self):
        dimension = next(
            d for d in self.world.models["block.prt"]["dimensions"] if d["name"] == self.depth
        )
        args = self.words(
            {
                "units": "mm",
                "instances": [
                    {
                        "name": "SHORT",
                        "values": {
                            "dimension:" + self.depth: 12,
                            "dimension:" + str(dimension["id"]): 14,
                        },
                    }
                ],
            }
        )
        self.cli(*args, "--dry-run", status=2)
        self.assertNotIn("family.set", self.world.ops())

    def test_table_from_another_model_is_not_an_intent_baseline(self):
        original = self.world.op

        def wrong(op, request):
            result = original(op, request)
            if op == "family.show":
                result = result | {"model": "another.prt"}
            return result

        with patch.object(self.world, "op", side_effect=wrong):
            self.cli(*self.words(), "--dry-run", status=1)
        self.assertNotIn("family.set", self.world.ops())

    def test_typeless_dimension_cannot_drive_a_family_column(self):
        placeholder = next(
            d for d in self.world.models["block.prt"]["dimensions"] if not d.get("type")
        )
        args = self.words(
            {
                "units": "mm",
                "instances": [
                    {
                        "name": "SHORT",
                        "values": {
                            "dimension:" + placeholder["name"]: 12,
                        },
                    }
                ],
            }
        )
        self.cli(*args, "--dry-run", status=2)
        self.assertNotIn("family.set", self.world.ops())

    def unexpected_table(self, *, new_row, lost):
        if new_row:
            self.two_columns()
            body = {
                "units": "mm",
                "instances": [{"name": "THIRD", "values": {"dimension:" + self.depth: 18}}],
            }
        else:
            body = self.body
        args = self.words(body)
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        original = self.world.op

        def corrupt(op, request):
            result = original(op, request)
            if op == "family.set":
                generic = self.world.models["block.prt"]
                column = self.world._family_item(generic, "dimension:" + self.extra)
                if new_row:
                    generic["family"]["rows"]["THIRD"][column["symbol"]] = (
                        column["generic_value"] + 3
                    )
                    self.world.models.pop("third.prt")
                    self.world.open_instance("block.prt", generic, "third")
                    self.world.models["third.prt"]["window_closed"] = True
                else:
                    generic["family"]["columns"].append(column)
            return result

        count = self.world.ops().count("family.set")
        self.world.drop = "family.set" if lost else None
        with patch.object(self.world, "op", side_effect=corrupt):
            error = self.cli(*args, "--confirm", p["confirm_token"], status=6 if lost else 1)[
                "error"
            ]
        self.world.drop = None
        outcome = error["details"]["receipt"]["outcome"]
        self.assertNotEqual(outcome["change"], "not_applied")
        if not lost:
            self.assertEqual(outcome["verification"]["status"], "failed")
        query = self.fresh("operation", "query", "--id", ident, "--model", "block")["data"]
        proof = query["observation"]["family_table_verification"]
        self.assertFalse(proof["accepted"])
        self.assertNotIn("applied", proof["can_register"])
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "The complete actual table deviates from the authorized pre-write intent",
            "--dry-run",
            status=1,
        )
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.assertEqual(self.world.ops().count("family.set"), count + 1)

    def test_extra_default_column_is_not_complete_success(self):
        self.unexpected_table(new_row=False, lost=False)

    def test_extra_default_column_lost_reply_cannot_register_applied(self):
        self.unexpected_table(new_row=False, lost=True)

    def test_new_row_wrong_omitted_cell_and_matching_dimensions_are_rejected(self):
        self.unexpected_table(new_row=True, lost=False)

    def test_new_row_wrong_omitted_cell_lost_reply_cannot_register_applied(self):
        self.unexpected_table(new_row=True, lost=True)

    def test_new_row_omitted_column_inherits_frozen_generic_value(self):
        self.two_columns()
        args = self.words(
            {
                "units": "mm",
                "instances": [{"name": "THIRD", "values": {"dimension:" + self.depth: 18}}],
            }
        )
        result = self.gated(*args)["data"]
        self.assertEqual(result["receipt"]["outcome"]["verification"]["status"], "passed")
        table = self.cli("family-table", "show", "--model", "block")["data"]
        row = next(x for x in table["instances"] if x["name"] == "THIRD")
        self.assertTrue(row["cells"][self.extra]["generic"])
        base = self.world._family_item(self.world.models["block.prt"], "dimension:" + self.extra)
        self.assertEqual(row["cells"][self.extra]["value"], base["generic_value"])

    def test_default_marker_changed_by_failed_cleanup_is_not_unchanged(self):
        self.two_columns()
        args = self.words(
            {
                "units": "mm",
                "instances": [{"name": "LONG", "values": {"dimension:" + self.extra: 30}}],
            }
        )
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def failed_restore(op, request):
            if op == "family.set":
                m = self.world.models["block.prt"]
                cell = self.world._family_item(m, "dimension:" + self.extra)
                m["family"]["rows"]["LONG"][self.extra] = cell["generic_value"]
                raise Refused("E_CREO", "injected cleanup restored the number but lost inheritance")
            return original(op, request)

        with patch.object(self.world, "op", side_effect=failed_restore):
            result = self.cli(*args, "--confirm", p["confirm_token"], status=1)["error"]
        receipt = result["details"]["receipt"]
        self.assertIn(receipt["outcome"]["change"], ["partial", "unknown"])
        shown = self.fresh("operation", "show", "--id", p["preview"]["operation_id"])["data"]
        self.assertNotEqual(
            shown["operation_status"]["receipt"]["outcome"]["change"], "not_applied"
        )

    def wrong_member(self, *, wrong_generic, lost):
        self.create()
        self.save_close_instances()
        member_file = self.ws / "short.prt.1"
        member_file.write_bytes(b"owned prior member version")
        args = self.words(
            {
                "units": "mm",
                "instances": [{"name": "SHORT", "values": {"dimension:" + self.depth: 14}}],
            }
        )
        p = self.cli(*args, "--dry-run")["data"]
        original = self.world.op

        def wrong(op, request):
            result = original(op, request)
            if op == "family.set":
                member = self.world.models["short.prt"]
                member["origin"] = str(member_file)
                if wrong_generic:
                    member["generic"] = "other.prt"
                    member["native_dependencies"] = ["other.prt"]
                else:
                    member.pop("generic")
                    member["native_dependencies"] = []
            return result

        self.world.drop = "family.set" if lost else None
        with patch.object(self.world, "op", side_effect=wrong):
            error = self.cli(
                *args, "--confirm", p["confirm_token"], status=6 if lost or wrong_generic else 1
            )["error"]
        self.world.drop = None
        self.assertNotEqual(error["details"]["receipt"]["outcome"]["change"], "not_applied")
        ident = p["preview"]["operation_id"]
        query = self.fresh(
            "operation",
            "query",
            "--id",
            ident,
            "--model",
            "block",
            status=2 if wrong_generic else 0,
        )
        if not wrong_generic:
            proof = query["data"]["observation"]["family_table_verification"]
            self.assertNotIn("applied", proof["can_register"])
            failed = [c["check"] for c in proof["checks"] if not c["passed"]]
            self.assertIn("instance_belongs_to_generic:short", failed)
        self.cli(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Same names and dimensions do not prove the target generic",
            "--dry-run",
            status=2 if wrong_generic else 1,
        )
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_same_name_standalone_is_not_a_family_member(self):
        self.wrong_member(wrong_generic=False, lost=False)

    def test_same_name_standalone_lost_reply_cannot_register_applied(self):
        self.wrong_member(wrong_generic=False, lost=True)

    def test_wrong_generic_is_not_a_family_member(self):
        self.wrong_member(wrong_generic=True, lost=False)

    def test_wrong_generic_lost_reply_cannot_register_applied(self):
        self.wrong_member(wrong_generic=True, lost=True)

    def test_old_incomplete_intent_evidence_does_not_unlock_writes(self):
        args = self.words()
        p = self.cli(*args, "--dry-run")["data"]
        ident = p["preview"]["operation_id"]
        self.world.drop = "family.set"
        self.cli(*args, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        self.gated(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent native family rows and geometry establish the result",
        )
        with patch.dict("os.environ", self.env, clear=True):
            run = operations.get(ident)
            receipt = copy.deepcopy(run["driver_receipt"])
            reference = run["driver_family_table_resolution"]
            observation = operations.load_query(reference["evidence_id"])["observation"]
            retained = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
            retained["family_intent"].pop("expected_table")
            proof = observation["family_table_verification"]
            proof["intent"] = copy.deepcopy(retained["family_intent"])
            current = proof["current"]
            column = self.world._family_item(
                self.world.models["block.prt"], "dimension:" + self.extra
            )
            current["table"]["columns"].append(column)
            for row in current["table"]["instances"]:
                row["cells"][column["symbol"]] = {"value": column["generic_value"], "generic": True}
            proof["checks"] = [
                c for c in proof["checks"] if not c["check"].startswith("complete_expected_family_")
            ]
            new = operations.save_query(run, observation)
            run["driver_family_table_resolution"] |= {
                "evidence_id": new["evidence_id"],
                "sha256": new["sha256"],
            }
            operations.update(run)
        calls = len(self.world.ops())
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        proof = shown["extensions"]["creo"]["family_table_inspection"]
        self.assertEqual(proof["evidence_integrity"], "valid")
        self.assertEqual(proof["evidence_status"], "insufficient")
        self.assertEqual(shown["receipt"], receipt)
        self.assertEqual(len(self.world.ops()), calls)
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)


for _name in vars(test_family_runtime.FamilyRuntime):
    if _name.startswith("test_") and _name not in vars(FamilyIntent):
        setattr(FamilyIntent, _name, None)
