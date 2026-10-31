"""Review counterexamples through public CLI fixtures; not native getter-fault claims."""

import copy
from unittest.mock import patch

from creo_cli import operations
from tests import test_view_remove_runtime as view_cases
from tests.test_commands import Base


class OriginFamilyIntegrity(Base):
    def setUp(self):
        super().setUp()
        self.part()

    def _read_fault(self, *, model="block.prt", origin=False, family=False, readers=None):
        original = self.world.op

        def read(op, request):
            result = copy.deepcopy(original(op, request))
            if op == "model.management-state":
                rows = [r for r in result["models"] if r["model"] == model]
            elif op == "model.show" and result.get("model") == model:
                rows = [result]
            else:
                rows = []
            for row in rows if readers is None or op in readers else []:
                if origin:
                    row["origin"] = None
                    row["origin_readback"] = {
                        "complete": False,
                        "state": "unreadable",
                        "value": None,
                        "source": "fixture GetOrigin threw",
                        "error": {"code": "E_CREO"},
                    }
                if family:
                    row["family"] = {
                        "complete": False,
                        "kind": "unknown",
                        "generic": None,
                        "instances": [],
                        "error": {"code": "E_CREO"},
                    }
            return result

        return patch.object(self.world, "op", side_effect=read)

    def test_two_failed_origin_readers_do_not_establish_same_source(self):
        with self._read_fault(origin=True):
            error = self.cli(
                "model",
                "set-common-name",
                "--model",
                "block",
                "--name",
                "R19",
                "--dry-run",
                status=1,
            )["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_one_failed_origin_reader_is_also_incomplete(self):
        for op in ("model.show", "model.management-state"):
            with self.subTest(reader=op), self._read_fault(origin=True, readers=[op]):
                error = self.cli(
                    "model",
                    "set-common-name",
                    "--model",
                    "block",
                    "--name",
                    "R19",
                    "--dry-run",
                    status=1,
                )["error"]
                self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_incomplete_or_contradictory_family_rows_refuse(self):
        base = self.world.family_info("block.prt", self.world.models["block.prt"])
        for changed in (
            {"row_count": 1},
            {"instances": ["A", "a"], "row_count": 2, "kind": "generic"},
            {"generic": "block.prt", "kind": "instance"},
            {"kind": "standalone", "column_count": 1},
        ):
            with self.subTest(changed=changed):
                self.world.models["block.prt"]["family_readback"] = base | changed
                error = self.cli(
                    "model",
                    "set-common-name",
                    "--model",
                    "block",
                    "--name",
                    "R19",
                    "--dry-run",
                    status=1,
                )["error"]
                self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_protected_sibling_origin_failure_refuses(self):
        self.gated("part", "create", "--name", "guard", "--units", "mmns")
        with self._read_fault(model="guard.prt", origin=True):
            self.cli(
                "model",
                "set-common-name",
                "--model",
                "block",
                "--name",
                "R19",
                "--dry-run",
                status=1,
            )
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_unreadable_family_does_not_mean_standalone(self):
        with self._read_fault(family=True):
            self.cli(
                "model",
                "set-common-name",
                "--model",
                "block",
                "--name",
                "R19",
                "--dry-run",
                status=1,
            )
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_protected_sibling_family_failure_refuses(self):
        self.gated("part", "create", "--name", "guard", "--units", "mmns")
        with self._read_fault(model="guard.prt", family=True):
            self.cli(
                "model",
                "set-common-name",
                "--model",
                "block",
                "--name",
                "R19",
                "--dry-run",
                status=1,
            )
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_missing_saved_origin_cannot_fall_back_to_working_directory(self):
        self.world.models["block.prt"]["origin"] = None
        self.cli(
            "model", "set-common-name", "--model", "block", "--name", "R19", "--dry-run", status=1
        )
        self.assertNotIn("model.set-common-name", self.world.ops())

    def test_current_working_directory_is_not_the_model_source(self):
        directory = self.ws / "elsewhere"
        directory.mkdir()
        self.world.cwd = directory
        preview = self.cli(
            "model", "set-common-name", "--model", "block", "--name", "R19", "--dry-run"
        )["data"]["preview"]
        before = preview["base_snapshot"]["extensions"]["creo"]["observation"]["management_before"]
        self.assertEqual(before["files"]["block.prt"][0]["path"], str(self.ws / "block.prt.1"))

    def test_lost_reply_with_unreadable_origin_cannot_register_applied(self):
        words = ["model", "set-common-name", "--model", "block", "--name", "R19"]
        p = self.cli(*words, "--dry-run")["data"]
        self.world.drop = "model.set-common-name"
        self.cli(*words, "--confirm", p["confirm_token"], status=6)
        self.world.drop = None
        with self._read_fault(origin=True):
            self.cli(
                "operation",
                "resolve",
                "--id",
                p["preview"]["operation_id"],
                "--outcome",
                "applied",
                "--evidence",
                "Two unreadable origins cannot establish the saved source",
                "--dry-run",
                status=1,
            )
        self.assertEqual(self.world.ops().count("model.set-common-name"), 1)


class LegacyViewEvidenceIntegrity(view_cases.ViewRemoveRuntime):
    # Deliberately do not inherit the unrelated native behavior matrix as new tests.
    def test_legacy_digest_valid_evidence_does_not_satisfy_current_gate(self):
        state, reader = self.entity_source()
        with reader:
            p = self.cli(*self.args(), "--dry-run")["data"]
            self.world.drop = "drawing.remove"
            self.cli(*self.args(), "--confirm", p["confirm_token"], status=6)
            self.world.drop = None
            ident = p["preview"]["operation_id"]
            self.fresh(
                "operation",
                "resolve",
                "--id",
                ident,
                "--outcome",
                "applied",
                "--evidence",
                "Complete native entity and source observations support deletion",
            )
            with patch.dict("os.environ", self.env, clear=True):
                original = operations.get(ident)
                reference = original["driver_view_removal_resolution"]
                evidence = operations.load_query(reference["evidence_id"])
                for variant in ("missing", "empty_mismatch", "missing_geometry"):
                    with self.subTest(variant=variant):
                        run = copy.deepcopy(original)
                        observation = copy.deepcopy(evidence["observation"])
                        current = observation["view_removal_verification"]["current"]
                        if variant == "missing":
                            current["resources"].pop("entities")
                            retained = run["driver_plan"]["base_snapshot"]["extensions"]["creo"][
                                "observation"
                            ]["view_removal_before"]
                            retained["resources"].pop("entities")
                        elif variant == "empty_mismatch":
                            current["resources"]["entities"] = []
                        else:
                            current["resources"]["entities"][0].pop("geometry")
                        new = operations.save_query(run, observation)
                        run["driver_view_removal_resolution"] |= {
                            "evidence_id": new["evidence_id"],
                            "sha256": new["sha256"],
                        }
                        operations.update(run)
                        calls = len(self.world.ops())
                        shown = self.fresh("operation", "show", "--id", ident)["data"][
                            "operation_status"
                        ]
                        inspection = shown["extensions"]["creo"]["view_removal_inspection"]
                        self.assertNotEqual(inspection["evidence_status"], "verified")
                        self.assertEqual(shown["receipt"], original["driver_receipt"])
                        self.assertEqual(len(self.world.ops()), calls)
                        self.fresh("model", "save", "--model", "block.drw", "--dry-run", status=6)


# Only the new review counterexample belongs to this subclass's collection.
for _name in list(vars(view_cases.ViewRemoveRuntime)):
    if _name.startswith("test_"):
        setattr(LegacyViewEvidenceIntegrity, _name, None)
