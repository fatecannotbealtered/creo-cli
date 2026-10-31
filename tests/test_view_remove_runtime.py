"""View deletion has a bounded no-cascade contract; fixtures are not native evidence."""

import copy
import json
import os
import subprocess
import sys
from unittest.mock import patch

from creo_cli import operations
from creo_cli.core import Error
from tests.test_capabilities import DrawnBlock
from tests.test_commands import ROOT


class ViewRemoveRuntime(DrawnBlock):
    def setUp(self):
        super().setUp()
        self.drawing = self.world.models["block.drw"]
        for i, row in enumerate(self.drawing["views"], 1):
            row["id"] = str(i)
            row["dependency_readback"] = {
                "background": False,
                "complete": True,
                "children": [
                    v["name"] for v in self.drawing["views"] if v.get("parent") == row["name"]
                ],
                "section_type": "none",
                "alignment_view": None,
            }
        self.drawing["views"].append(
            {
                "id": "71",
                "name": "AUX",
                "sheet": 1,
                "scale": 1.0,
                "model": "block.prt",
                "outline": [[300.0, 210.0], [360.0, 250.0]],
                "type": "general",
                "parent": None,
                "sections": [],
                "display": "lines",
                "dependency_readback": {
                    "background": False,
                    "complete": True,
                    "children": [],
                    "section_type": "none",
                    "alignment_view": None,
                },
            }
        )

    def args(self):
        return ("drawing", "view", "remove", "--model", "block.drw", "--item", "AUX")

    def entity_source(self):
        self.drawing["entities"] = 1
        self.drawing["draft_arcs"] = []
        state = {
            "complete": True,
            "items": [
                {
                    "id": "900",
                    "type": "line",
                    "sheet": 1,
                    "view": "overlay_view",
                    "view_id": "0",
                    "background": True,
                    "complete": True,
                    "units": "mm",
                    "coordinate_space": "sheet_lower_left_xyz",
                    "geometry": {"start": [10.0, 10.0, 0.0], "end": [20.0, 20.0, 0.0]},
                }
            ],
        }
        original = self.world.op

        def read(op, request):
            if op == "drawing.resources" and request.get("kind") == "entities":
                return {
                    "model": "block.drw",
                    "items": copy.deepcopy(state["items"]),
                    "completed": state["complete"],
                    "source": "fixture:native-detail-entities",
                    "scope": "all_sheets",
                    "coverage": {"count": 1},
                }
            return original(op, request)

        return state, patch.object(self.world, "op", side_effect=read)

    def test_same_count_changed_line_endpoints_fails_after_delete(self):
        state, reader = self.entity_source()
        original = self.world.drawing_remove

        def mutate(request):
            result = original(request)
            state["items"][0]["geometry"]["end"][0] += 5
            return result

        with reader, patch.object(self.world, "drawing_remove", side_effect=mutate):
            preview = self.cli(*self.args(), "--dry-run")["data"]
            result = self.cli(*self.args(), "--confirm", preview["confirm_token"], status=1)
        self.assertEqual(result["error"]["code"], "E_VERIFY_FAILED")
        self.assertNotEqual(
            result["error"]["details"]["receipt"]["outcome"]["change"], "not_applied"
        )

    def test_same_count_changed_entity_owner_fails_after_delete(self):
        state, reader = self.entity_source()
        original = self.world.drawing_remove

        def mutate(request):
            result = original(request)
            state["items"][0].update(view="FRONT", view_id="1", background=False)
            return result

        with reader, patch.object(self.world, "drawing_remove", side_effect=mutate):
            preview = self.cli(*self.args(), "--dry-run")["data"]
            self.cli(*self.args(), "--confirm", preview["confirm_token"], status=1)

    def test_target_attached_entity_is_refused_before_delete(self):
        state, reader = self.entity_source()
        state["items"][0].update(view="AUX", view_id="71", background=False)
        with reader:
            error = self.cli(*self.args(), "--dry-run", status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_entity_read_failure_is_not_empty_or_safe_preview(self):
        state, reader = self.entity_source()
        state.update(complete=False, items=None)
        with reader:
            error = self.cli(*self.args(), "--dry-run", status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_lost_reply_identical_incomplete_entities_cannot_register_applied(self):
        state, reader = self.entity_source()
        with reader:
            preview = self.cli(*self.args(), "--dry-run")["data"]
            self.world.drop = "drawing.remove"
            self.cli(*self.args(), "--confirm", preview["confirm_token"], status=6)
            self.world.drop = None
            state.update(complete=False, items=None)
            ident = preview["preview"]["operation_id"]
            self.fresh("operation", "query", "--id", ident, "--model", "block.drw", status=1)
            self.fresh(
                "operation",
                "resolve",
                "--id",
                ident,
                "--outcome",
                "applied",
                "--evidence",
                "Two incomplete entity readings must not establish no collateral damage",
                status=1,
            )
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def test_view_resolution_exposes_evidence_in_offline_fresh_status(self):
        preview = self.cli(*self.args(), "--dry-run")["data"]
        self.world.drop = "drawing.remove"
        self.cli(*self.args(), "--confirm", preview["confirm_token"], status=6)
        self.world.drop = None
        ident = preview["preview"]["operation_id"]
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent current view resources and source geometry match frozen intent",
        )
        calls = len(self.world.ops())
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        inspection = shown.get("extensions", {}).get("creo", {}).get("view_removal_inspection")
        self.assertIsNotNone(inspection)
        self.assertEqual(inspection["registered_outcome"], "applied")
        self.assertEqual(inspection["evidence_status"], "verified")
        self.assertIn("evidence_id", inspection)
        self.assertEqual(len(self.world.ops()), calls)

    def test_missing_or_tampered_registered_evidence_keeps_history_and_blocks_conflicts(self):
        from pathlib import Path

        preview = self.cli(*self.args(), "--dry-run")["data"]
        self.world.drop = "drawing.remove"
        self.cli(*self.args(), "--confirm", preview["confirm_token"], status=6)
        self.world.drop = None
        ident = preview["preview"]["operation_id"]
        resolved = self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Stable complete independent view and source observations",
        )
        initial = resolved["data"]["operation_status"]
        evidence = initial["extensions"]["creo"]["view_removal_inspection"]
        file = (
            Path(self.env["CREO_CLI_CONFIG_DIR"])
            / "operation-queries"
            / (evidence["evidence_id"] + ".json")
        )
        raw = file.read_bytes()
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt):
                if corrupt:
                    file.write_bytes(raw + b" ")
                else:
                    file.unlink()
                calls = len(self.world.ops())
                status = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
                self.assertNotEqual(
                    status["extensions"]["creo"]["view_removal_inspection"]["evidence_status"],
                    "verified",
                )
                self.assertEqual(status["resolution"], initial["resolution"])
                self.assertEqual(status["receipt"], initial["receipt"])
                self.assertEqual(len(self.world.ops()), calls)
                self.fresh("model", "save", "--model", "block.drw", "--dry-run", status=6)
                file.write_bytes(raw)  # Exact immutable backup restoration, not new evidence.
        self.assertEqual(
            self.fresh("operation", "show", "--id", ident)["data"]["operation_status"][
                "extensions"
            ]["creo"]["view_removal_inspection"]["evidence_status"],
            "verified",
        )
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def test_single_view_proves_no_incoming_alignment_without_treating_failed_getter_as_empty(self):
        target = self.drawing["views"][-1]
        self.drawing["views"] = [target]
        target["dependency_readback"].update(
            complete=False, basic_complete=True, error={"toolkit_error": -2}
        )
        plan = self.cli(*self.args(), "--dry-run")["data"]["preview"]
        intent = plan["extensions"]["creo"]["view_dependencies"]
        self.assertFalse(intent["alignment"]["required"])
        self.assertEqual(intent["alignment"]["unreadable"], ["AUX"])
        self.assertEqual(plan["base_snapshot"]["source"], "mixed")

    def test_other_view_with_unreadable_alignment_and_missing_rpc_inventory_refuse(self):
        self.drawing["views"][0]["dependency_readback"].update(complete=False, basic_complete=True)
        self.cli(*self.args(), "--dry-run", status=1)
        self.drawing["views"][0]["dependency_readback"]["complete"] = True
        original = self.world.op

        def missing(op, request):
            result = original(op, request)
            return (
                result | {"items": None}
                if op == "drawing.resources" and request["kind"] == "symbols"
                else result
            )

        with patch.object(self.world, "op", side_effect=missing):
            self.cli(*self.args(), "--dry-run", status=1)
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_note_page_ownership_is_explicit_and_not_inferred_from_single_sheet(self):
        self.drawing["views"] = [self.drawing["views"][-1]]
        note = {
            "id": "999",
            "text": "PAGE NOTE",
            "sheet": 1,
            "leaders": [],
            "leaders_complete": True,
            "attachment_readback": {
                "complete": True,
                "view": "overlay_view",
                "background": True,
                "kind": "free",
                "sheet": 1,
            },
        }
        self.drawing["notes"] = [note]
        listed = self.cli("drawing", "note", "list", "--model", "block.drw", "--sheet", 1)
        self.assertEqual(listed["data"]["items"][0]["sheet"], 1)
        self.cli(*self.args(), "--dry-run")
        for row_sheet, attachment_sheet in ((None, 1), (1, None), (1, 2), (2, 2)):
            with self.subTest(row_sheet=row_sheet, attachment_sheet=attachment_sheet):
                note["sheet"] = row_sheet
                note["attachment_readback"]["sheet"] = attachment_sheet
                self.cli(*self.args(), "--dry-run", status=1)
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_file_version_drift_and_generic_entry_cannot_bypass_lifecycle(self):
        plan = self.cli(*self.args(), "--dry-run")["data"]
        from pathlib import Path

        file = Path(self.drawing["origin"])
        file.write_bytes(file.read_bytes() + b"\n")
        self.cli(*self.args(), "--confirm", plan["confirm_token"], status=6)
        self.cli(
            "drawing",
            "item",
            "remove",
            "--model",
            "block.drw",
            "--item",
            "view:AUX",
            "--dry-run",
            status=2,
        )
        self.assertNotIn("drawing.remove", self.world.ops())

    def fresh(self, *args, status=0):
        result = subprocess.run(
            [sys.executable, "-m", "creo_cli", *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, status, result.stdout[:1600] + result.stderr)
        return json.loads(result.stdout)

    def test_isolated_delete_public_receipt_and_fresh_query(self):
        source = copy.deepcopy(self.world.models["block.prt"])
        before = copy.deepcopy(self.drawing["views"][:-1])
        result = self.gated(*self.args())["data"]
        self.assertEqual(result["receipt"]["outcome"]["change"], "applied")
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(self.drawing["views"], before)
        self.assertEqual(self.world.models["block.prt"], source)
        ident = result["receipt"]["operation_id"]
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"]["outcome"]["verification"]["status"], "passed")

    def test_associated_dimension_or_note_is_refused_before_dispatch(self):
        for kind in ("dimension", "note", "balloon"):
            with self.subTest(kind=kind):
                if kind == "dimension":
                    self.drawing["shown_dims"] = [
                        {
                            "id": "999",
                            "name": "d99",
                            "model": "block.prt",
                            "view": "AUX",
                            "sheet": 1,
                        }
                    ]
                else:
                    self.drawing["notes"] = [
                        {
                            "id": "999",
                            "text": "1" if kind == "balloon" else "AUX NOTE",
                            "sheet": 1,
                            "leaders": [{"view": "AUX"}],
                            "leaders_complete": True,
                            "attachment_readback": {
                                "sheet": 1,
                                "complete": True,
                                "view": "AUX",
                                "kind": "free",
                            },
                        }
                    ]
                before = copy.deepcopy(self.drawing)
                result = self.cli(*self.args(), "--dry-run", status=6)
                self.assertEqual(result["error"]["code"], "E_CONFLICT")
                self.assertEqual(self.drawing, before)
                self.drawing["shown_dims"] = []
                self.drawing["notes"] = []
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_unreadable_relations_or_annotation_association_refuses(self):
        self.drawing["views"][-1]["dependency_readback"]["complete"] = False
        result = self.cli(*self.args(), "--dry-run", status=1)
        self.assertEqual(result["error"]["code"], "E_VERIFY_INCOMPLETE")
        self.drawing["views"][-1]["dependency_readback"]["complete"] = True
        self.drawing["notes"] = [
            {"id": "999", "text": "UNKNOWN", "leaders": [], "leaders_complete": False}
        ]
        self.cli(*self.args(), "--dry-run", status=1)
        self.assertNotIn("drawing.remove", self.world.ops())

    def test_identity_drift_with_same_name_and_repeated_confirmation(self):
        plan = self.cli(*self.args(), "--dry-run")["data"]
        self.drawing["views"][-1]["id"] = "72"
        self.cli(*self.args(), "--confirm", plan["confirm_token"], status=6)
        self.assertNotIn("drawing.remove", self.world.ops())
        plan = self.cli(*self.args(), "--dry-run")["data"]
        self.cli(*self.args(), "--confirm", plan["confirm_token"])
        self.cli(*self.args(), "--confirm", plan["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def test_lost_reply_non_target_change_cannot_register_applied(self):
        plan = self.cli(*self.args(), "--dry-run")["data"]
        original = self.world.drawing_remove

        def collateral(request):
            result = original(request)
            self.drawing["views"][0]["scale"] *= 2
            return result

        self.world.drop = "drawing.remove"
        with patch.object(self.world, "drawing_remove", side_effect=collateral):
            self.cli(*self.args(), "--confirm", plan["confirm_token"], status=6)
        self.world.drop = None
        ident = plan["preview"]["operation_id"]
        inspected = self.fresh("operation", "query", "--id", ident, "--model", "block.drw")["data"][
            "observation"
        ]["view_removal_verification"]
        self.assertEqual(inspected["can_register"], ["partial"])
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Other view scale was changed; target absence alone must not pass",
            status=1,
        )
        self.fresh("model", "save", "--model", "block.drw", "--dry-run", status=6)

    def test_final_receipt_failure_fresh_registration_and_zero_replay(self):
        plan = self.cli(*self.args(), "--dry-run")["data"]
        update = operations.update

        def fail(record):
            if record.get("driver_receipt") and record.get("command") == "drawing view remove":
                raise Error("E_IO", "injected final public receipt write failure")
            return update(record)

        with patch.object(operations, "update", side_effect=fail):
            self.cli(*self.args(), "--confirm", plan["confirm_token"], status=6)
        ident = plan["preview"]["operation_id"]
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
        self.assertEqual(run["status"], "running")
        self.assertIsNone(run["driver_receipt"])
        self.fresh("operation", "show", "--id", ident)
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "applied",
            "--evidence",
            "Independent complete drawing resources and source geometry "
            "match retained deletion intent",
        )
        self.fresh(*self.args(), "--confirm", plan["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def test_generated_section_and_native_readonly_notes_refuse_but_plain_note_edits(self):
        note = self.gated(
            "drawing",
            "note",
            "add",
            "--model",
            "block.drw",
            "--text",
            "SECTION A-A",
            "--x",
            20,
            "--y",
            20,
        )["data"]["result"]["note"]
        target = next(n for n in self.drawing["notes"] if str(n["id"]) == str(note["id"]))
        args = (
            "drawing",
            "note",
            "edit",
            "--model",
            "block.drw",
            "--note",
            note["id"],
            "--text",
            "PLAIN TEST NOTE",
        )
        target.update(text="SECTION &xsec_name", displayed_text="SECTION A-A", read_only=False)
        self.cli(*args, "--dry-run", status=2)
        target.update(text="SECTION A-A", read_only=True)
        self.cli(*args, "--dry-run", status=2)
        self.assertNotIn("drawing.edit-note", self.world.ops())
        target["read_only"] = False
        self.gated(*args)
        self.assertEqual(target["text"], "PLAIN TEST NOTE")

    def test_current_query_needs_observe_scope_but_retained_show_does_not(self):
        plan = self.cli(*self.args(), "--dry-run")["data"]
        from pathlib import Path

        scope = Path(self.env["CREO_CLI_SCOPE_FILE"])
        original = json.loads(scope.read_text())
        scope.write_text(
            json.dumps(original | {"roots": [str(self.ws / "unrelated")]}), encoding="utf8"
        )
        ident = plan["preview"]["operation_id"]
        self.fresh("operation", "show", "--id", ident)
        calls = len(self.world.ops())
        self.fresh("operation", "query", "--id", ident, "--model", "block.drw", status=4)
        self.assertEqual(len(self.world.ops()), calls)
