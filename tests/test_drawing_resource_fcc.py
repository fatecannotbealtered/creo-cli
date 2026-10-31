"""Drawing resource FCC gaps against the loopback substitute; never live Creo evidence.

Fixture inventories are arranged independently of CLI inputs. Calls traverse the real
CLI/client/receipt engine. Faults are injected at the fake service boundary only.
"""

from __future__ import annotations

import copy
import hashlib
from unittest.mock import patch

from tests.fixture import Refused
from tests.test_commands import Base, domain_preview, domain_receipt

KINDS = {
    "view": "views",
    "dimension": "own_dims",
    "note": "notes",
    "table": "tables",
    "symbol": "symbols",
    "datum": "datums",
    "gtol": "gtols",
}
SHOWS = ("dimension", "note", "table", "symbol", "datum", "gtol")
CHANGES = {
    "view": ("scale", 2.0),
    "dimension": ("value", 9.0),
    "note": ("text", "changed independently"),
    "table": ("cells", [["changed independently"]]),
    "symbol": ("definition", "changed.sym"),
    "datum": ("label", "Z"),
    "gtol": ("value", "0.9"),
}


class DrawingResourceFCC(Base):
    def setUp(self):
        super().setUp()
        self.part()
        self.world.drawing_create({"name": "drawing.drw", "of": "block.prt", "sheet": "a3"})
        drawing = self.world.models["drawing.drw"]
        drawing["sheets"].append(drawing["sheets"][0] | {"number": 2})
        self.seed = copy.deepcopy(self.world.models)

    def arranged(self, noun=None):
        self.world.models = copy.deepcopy(self.seed)
        drawing = self.world.models["drawing.drw"]
        for resource, storage in KINDS.items():
            drawing[storage] = [self.row(resource, index) for index in (1, 2)]
        if noun == "view":
            drawing["sheets"] = drawing["sheets"][:1]
            for index, view in enumerate(drawing["views"], 1):
                view.update(
                    id=str(index),
                    sheet=1,
                    sections=[],
                    dependency_readback={
                        "complete": True,
                        "background": False,
                        "children": [],
                        "section_type": "none",
                        "alignment_view": None,
                    },
                )
            for row in drawing["own_dims"]:
                row.update(view="KEEP", sheet=1)
            for row in drawing["notes"]:
                row.update(
                    sheet=1,
                    leaders=[],
                    leaders_complete=True,
                    attachment_readback={
                        "complete": True,
                        "view": None,
                        "kind": "free",
                        "sheet": 1,
                    },
                )
            for row in drawing["tables"]:
                row.update(sheet=1, cell_references=[])
            for kind in ("symbols", "datums", "gtols"):
                drawing[kind] = []
        self.world.events.clear()
        return drawing

    @staticmethod
    def row(noun, index):
        common = {"id": str(index), "sheet": index}
        if noun == "view":
            return {
                "name": "LEAF" if index == 1 else "KEEP",
                "sheet": index,
                "model": "block.prt",
                "type": "general",
                "parent": None,
                "scale": 1.0,
                "display": "lines",
                "outline": [[10.0 * index, 10.0], [20.0 * index, 20.0]],
            }
        if noun == "dimension":
            return common | {
                "name": f"r{index}",
                "model": "drawing.drw",
                "value": float(index),
                "reference": True,
                "view": "LEAF" if index == 1 else "KEEP",
            }
        if noun == "note":
            return common | {"text": f"independent note {index}", "at": [10.0, 10.0]}
        if noun == "table":
            return common | {
                "rows": 1,
                "columns": 1,
                "cells": [[f"independent table {index}"]],
                "from_format": False,
            }
        if noun == "symbol":
            return common | {"definition": f"independent-{index}.sym", "variables": {}}
        if noun == "datum":
            return common | {"label": "A" if index == 1 else "B", "model": "drawing.drw"}
        return common | {"model": "drawing.drw", "type": "flatness", "value": "0.1"}

    @staticmethod
    def selector(noun, row):
        return (
            row["name"]
            if noun in ("view", "dimension")
            else row["label"]
            if noun == "datum"
            else row["id"]
        )

    def snapshot(self):
        return {
            "models": copy.deepcopy(self.world.models),
            "files": {
                str(path.relative_to(self.ws)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.ws.rglob("*")
                if path.is_file()
            },
        }

    def words(self, noun, verb, item):
        return ("drawing", noun, verb, "--model", "drawing.drw", "--item", str(item))

    def assert_no_dispatch_or_change(self, before):
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("drawing.remove", self.world.ops())
        self.assertTrue(
            all(r["status"] == "planned" and r.get("started_at") is None for r in self.receipts())
        )

    def show_success(self, noun):
        drawing = self.arranged(noun)
        before = self.snapshot()
        row = drawing[KINDS[noun]][1]
        data = self.cli(*self.words(noun, "show", self.selector(noun, row)), "--sheet", 2)["data"]
        observed = dict(data["item"])
        if noun == "note":
            membership = observed.pop("membership_readback")
            self.assertTrue(membership["complete"])
            self.assertEqual(membership["drawing"], "drawing.drw")
            self.assertEqual(str(membership["note_id"]), str(row["id"]))
            self.assertIn("not SDK evidence", membership["source"])
        self.assertEqual(observed, row)
        self.assertEqual(data["model"], "drawing.drw")
        self.assertEqual(data["source"], "fixture:resource-getters")
        self.assertEqual(data["scope"], "sheet:2")
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn("drawing.remove", self.world.ops())

    def show_selector_refusals(self, noun):
        drawing = self.arranged(noun)
        before = self.snapshot()
        self.assertEqual(
            self.cli(*self.words(noun, "show", "absent"), status=3)["error"]["code"], "E_NOT_FOUND"
        )
        self.assertEqual(self.snapshot(), before)
        drawing[KINDS[noun]].append(copy.deepcopy(drawing[KINDS[noun]][0]))
        before = self.snapshot()
        selector = self.selector(noun, drawing[KINDS[noun]][0])
        error = self.cli(*self.words(noun, "show", selector), status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertEqual(error["details"]["matched_count"], 2)
        self.assertEqual(self.snapshot(), before)

    def show_acquisition_refusals(self, noun):
        self.arranged(noun)
        before = self.snapshot()
        original = self.world.op
        for key, value in (
            ("items", None),
            ("completed", False),
            ("model", "other.drw"),
            ("source", ""),
            ("coverage", None),
            ("coverage", {}),
            ("coverage", {"count": 0}),
            ("items", [None, self.row(noun, 2)]),
            ("items", [self.row(noun, 1) | {"error": "getter failed"}, self.row(noun, 2)]),
        ):
            with self.subTest(field=key):

                def broken(op, request, field=key, replacement=value):
                    data = original(op, request)
                    return data | {field: replacement} if op == "drawing.resources" else data

                with patch.object(self.world, "op", side_effect=broken):
                    error = self.cli(*self.words(noun, "show", "1"), status=1)["error"]
                self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
                self.assertEqual(self.snapshot(), before)
        self.assertNotIn("drawing.remove", self.world.ops())

    def show_scope_refusals(self, noun):
        drawing = self.arranged(noun)
        selector = self.selector(noun, drawing[KINDS[noun]][0])
        before = self.snapshot()
        error = self.cli(*self.words(noun, "show", selector), "--sheet", 0, status=2)["error"]
        self.assertEqual(error["code"], "E_VALIDATION")
        self.assertEqual(self.snapshot(), before)
        drawing[KINDS[noun]] = [self.row(noun, index) for index in range(1, 1002)]
        before = self.snapshot()
        error = self.cli(*self.words(noun, "show", selector), status=2)["error"]
        self.assertEqual(error["code"], "E_VALIDATION")
        self.assertIn("exceeds1000", error["message"])
        self.assertEqual(self.snapshot(), before)

    def remove_success(self, noun):
        for qualified in (False, True):
            with self.subTest(qualified=qualified):
                drawing = self.arranged(noun)
                rows = drawing[KINDS[noun]]
                kept = copy.deepcopy(rows[1:])
                item = self.selector(noun, rows[0])
                words = self.words(noun, "remove", f"{noun}:{item}" if qualified else item)
                before = self.snapshot()
                preview = self.cli(*words, "--dry-run")["data"]
                self.assertEqual(self.snapshot(), before)
                self.assertNotIn("drawing.remove", self.world.ops())
                token = preview["confirm_token"]
                receipt = self.cli(*words, "--confirm", token)["data"]
                shown = self.cli("operation", "show", "--id", receipt["operation_id"])["data"]
                if noun in ("note", "table", "dimension", "view"):
                    self.assertEqual(
                        shown["operation_status"]["capability_id"], f"drawing-{noun}-remove"
                    )
                else:
                    self.assertEqual(shown["receipt"]["command"], f"drawing {noun} remove")
                self.assertEqual(receipt["status"], "completed")
                self.checks_pass(receipt)
                self.assertFalse(receipt["persisted"])
                self.assertEqual(drawing[KINDS[noun]], kept)
                after = self.snapshot()
                expected = copy.deepcopy(before)
                expected["models"]["drawing.drw"][KINDS[noun]] = kept
                expected["models"]["drawing.drw"]["modified"] = True
                self.assertEqual(after, expected)
                self.assertEqual(self.world.ops().count("drawing.remove"), 1)
                # A fixture undo restores the same CAD state, so this reaches the single-use
                # token gate rather than merely failing because the deleted item is absent.
                self.arranged(noun)
                before_replay = self.snapshot()
                self.assertEqual(
                    self.cli(*words, "--confirm", token, status=6)["error"]["code"], "E_CONFLICT"
                )
                self.assertEqual(self.snapshot(), before_replay)
                self.assertNotIn("drawing.remove", self.world.ops())

    def remove_wrong_kind_and_missing_gates(self, noun):
        drawing = self.arranged(noun)
        before = self.snapshot()
        item = self.selector(noun, drawing[KINDS[noun]][0])
        self.assertEqual(
            self.cli(*self.words(noun, "remove", "other:1"), "--dry-run", status=2)["error"][
                "code"
            ],
            "E_VALIDATION",
        )
        self.assertEqual(
            self.cli(*self.words(noun, "remove", item), status=5)["error"]["code"],
            "E_CONFIRMATION_REQUIRED",
        )
        self.assert_no_dispatch_or_change(before)

    def remove_missing_target(self, noun):
        self.arranged(noun)
        missing = "ZZ" if noun == "datum" else "MISSING" if noun in ("view", "dimension") else "999"
        before = self.snapshot()
        self.assertEqual(
            self.cli(*self.words(noun, "remove", missing), "--dry-run", status=3)["error"]["code"],
            "E_NOT_FOUND",
        )
        self.assert_no_dispatch_or_change(before)

    def remove_incomplete_preview(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        before = self.snapshot()
        original = self.world.op

        def missing(op, request):
            data = original(op, request)
            if op == "drawing.resources":
                return data | {"items": None, "completed": False}
            if op == "model.show" and data.get("model") == "drawing.drw":
                data[KINDS[noun] if noun != "dimension" else "dimensions"] = None
            return data

        with patch.object(self.world, "op", side_effect=missing):
            error = self.cli(*words, "--dry-run", status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_INCOMPLETE")
        self.assert_no_dispatch_or_change(before)

    def remove_external_drawing(self, noun):
        drawing = self.arranged(noun)
        drawing["origin"] = str(self.root / "external" / "drawing.drw.1")
        before = self.snapshot()
        self.assertEqual(
            self.cli(
                *self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0])),
                "--dry-run",
                status=4,
            )["error"]["code"],
            "E_FORBIDDEN",
        )
        self.assert_no_dispatch_or_change(before)

    def remove_stale_preview(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        drawing["modified"] = True
        before = self.snapshot()
        self.world.events.clear()
        error = self.cli(*words, "--confirm", token, status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertEqual(error["details"]["reason"], "state_changed")
        self.assert_no_dispatch_or_change(before)

    def remove_service_refusal(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        before = self.snapshot()
        original = self.world.op

        def refusing(op, request):
            if op == "drawing.remove":
                raise Refused("E_CREO", "injected fixture refusal before mutation")
            return original(op, request)

        with patch.object(self.world, "op", side_effect=refusing):
            error = self.cli(*words, "--confirm", token, status=1)["error"]
        self.assertEqual(error["code"], "E_NATIVE_FAILURE")
        self.assertEqual(error["details"]["receipt_status"], "failed_unchanged")
        self.assertFalse(error["details"]["rollback_performed"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def remove_no_op_writer(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        before = self.snapshot()
        original = self.world.op

        def echoed(op, request):
            if op == "drawing.remove":
                return self.world.drawing_summary("drawing.drw", drawing) | {
                    "removed": {"item": request["item"]}
                }
            return original(op, request)

        with patch.object(self.world, "op", side_effect=echoed):
            error = self.cli(*words, "--confirm", token, status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(self.snapshot(), before)

    def remove_read_permission(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        readonly = self.env | {"CREO_CLI_PERMISSION": "read"}
        before = self.snapshot()
        preview = self.cli(*words, "--dry-run", env=readonly)["data"]
        self.assertFalse(domain_preview(preview["preview"])["policy"]["confirm_allowed"])
        error = self.cli(*words, "--confirm", preview["confirm_token"], env=readonly, status=4)[
            "error"
        ]
        self.assertEqual(error["code"], "E_FORBIDDEN")
        self.assert_no_dispatch_or_change(before)

    def remove_failure_after_mutation(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        kept = copy.deepcopy(drawing[KINDS[noun]][1:])
        before = self.snapshot()
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        self.world.fail_after = (
            "drawing.remove",
            {"code": "E_CREO", "message": "injected error after deletion"},
        )
        error = self.cli(*words, "--confirm", token, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt_status"], "partial")
        self.assertEqual(error["details"]["state_after"], "observed_changed")
        self.assertFalse(error["details"]["rollback_performed"])
        expected = copy.deepcopy(before)
        expected["models"]["drawing.drw"][KINDS[noun]] = kept
        expected["models"]["drawing.drw"]["modified"] = True
        self.assertEqual(self.snapshot(), expected)
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)
        self.assertEqual(self.cli(*words, "--dry-run", status=6)["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def remove_incomplete_readback(self, noun):
        drawing = self.arranged(noun)
        drawing[KINDS[noun]] = drawing[KINDS[noun]][:1]
        if noun == "view":
            drawing["own_dims"] = []  # the removed KEEP fixture view has no surviving annotations
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        original = self.world.op
        dispatched = False

        def missing(op, request):
            nonlocal dispatched
            result = original(op, request)
            if op == "drawing.remove":
                dispatched = True
            if dispatched and op == "model.show" and result.get("model") == "drawing.drw":
                result[KINDS[noun] if noun != "dimension" else "dimensions"] = None
            if dispatched and op == "drawing.resources":
                result = result | {"items": None, "completed": False}
            return result

        with patch.object(self.world, "op", side_effect=missing):
            error = self.cli(
                *words,
                "--confirm",
                token,
                status=6 if noun in ("note", "table", "dimension", "view") else 1,
            )["error"]
        self.assertEqual(
            error["code"],
            "E_OUTCOME_UNKNOWN"
            if noun in ("note", "table", "dimension", "view")
            else "E_VERIFY_INCOMPLETE",
        )
        self.assertEqual(
            domain_receipt(error["details"]["receipt"])["verification"]["status"], "incomplete"
        )
        self.assertTrue(error["details"]["service_reported_done"])
        self.assertFalse(error["details"]["rollback_performed"])
        self.assertEqual(drawing[KINDS[noun]], [])
        self.assertEqual(self.cli(*words, "--dry-run", status=6)["error"]["code"], "E_CONFLICT")
        self.assertEqual(self.world.ops().count("drawing.remove"), 1)

    def remove_changed_sibling(self, noun):
        drawing = self.arranged(noun)
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        original = self.world.op

        def collateral(op, request):
            result = original(op, request)
            if op == "drawing.remove":
                key, value = CHANGES[noun]
                drawing[KINDS[noun]][0][key] = copy.deepcopy(value)
            return result

        with patch.object(self.world, "op", side_effect=collateral):
            error = self.cli(*words, "--confirm", token, status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(error["details"]["receipt_status"], "verification_failed")
        self.assertFalse(error["details"]["rollback_performed"])
        self.assertTrue(
            any(
                c["check"] == "non_target_views_unchanged"
                if noun == "view"
                else c["check"].startswith("other_")
                for c in error["details"]["failed_checks"]
            )
        )

    def remove_ambiguous_target(self, noun):
        drawing = self.arranged(noun)
        drawing[KINDS[noun]].append(copy.deepcopy(drawing[KINDS[noun]][0]))
        words = self.words(noun, "remove", self.selector(noun, drawing[KINDS[noun]][0]))
        before = self.snapshot()
        error = self.cli(*words, "--dry-run", status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assert_no_dispatch_or_change(before)

    def test_dimension_source_owner_cannot_be_deleted(self):
        drawing = self.arranged()
        drawing["own_dims"] = []
        drawing["shown_dims"] = [self.row("dimension", 1) | {"model": "block.prt"}]
        before = self.snapshot()
        self.assertEqual(
            self.cli(*self.words("dimension", "remove", "r1"), "--dry-run", status=6)["error"][
                "code"
            ],
            "E_CONFLICT",
        )
        self.assert_no_dispatch_or_change(before)

    def test_format_table_cannot_be_deleted(self):
        drawing = self.arranged()
        drawing["tables"][0]["from_format"] = True
        before = self.snapshot()
        self.assertEqual(
            self.cli(*self.words("table", "remove", "1"), "--dry-run", status=6)["error"]["code"],
            "E_CONFLICT",
        )
        self.assert_no_dispatch_or_change(before)

    def test_view_with_children_cannot_cascade_delete(self):
        drawing = self.arranged("view")
        drawing["views"][1]["parent"] = "LEAF"
        drawing["views"][0]["dependency_readback"]["children"] = ["KEEP"]
        before = self.snapshot()
        self.assertEqual(
            self.cli(*self.words("view", "remove", "LEAF"), "--dry-run", status=6)["error"]["code"],
            "E_CONFLICT",
        )
        self.assert_no_dispatch_or_change(before)

    def test_gtol_external_source_owner_cannot_be_changed(self):
        drawing = self.arranged()
        drawing["gtols"][0]["model"] = "block.prt"
        self.world.models["block.prt"]["origin"] = str(self.root / "external" / "block.prt.1")
        before = self.snapshot()
        error = self.cli(*self.words("gtol", "remove", "1@block.prt"), "--dry-run", status=4)[
            "error"
        ]
        self.assertEqual(error["code"], "E_FORBIDDEN")
        self.assert_no_dispatch_or_change(before)

    def test_gtol_owned_source_owner_is_disclosed_and_bound_to_preview(self):
        drawing = self.arranged()
        drawing["gtols"][0]["model"] = "block.prt"
        words = self.words("gtol", "remove", "1@block.prt")
        preview = self.cli(*words, "--dry-run")["data"]
        self.assertEqual(
            domain_preview(preview["preview"])["affected_models"], ["drawing.drw", "block.prt"]
        )
        self.world.models["block.prt"]["modified"] = True
        before = self.snapshot()
        self.world.events.clear()
        error = self.cli(*words, "--confirm", preview["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_CONFLICT")
        self.assertEqual(error["details"]["reason"], "state_changed")
        self.assert_no_dispatch_or_change(before)

    def test_gtol_service_failure_observes_owned_source_model_change(self):
        drawing = self.arranged()
        drawing["gtols"][0]["model"] = "block.prt"
        words = self.words("gtol", "remove", "1@block.prt")
        before_rows = copy.deepcopy(drawing["gtols"])
        token = self.cli(*words, "--dry-run")["data"]["confirm_token"]
        original = self.world.op

        def changed_owner(op, request):
            if op == "drawing.remove":
                self.world.models["block.prt"]["modified"] = True
                raise Refused("E_CREO", "injected source-model change without frame deletion")
            return original(op, request)

        with patch.object(self.world, "op", side_effect=changed_owner):
            error = self.cli(*words, "--confirm", token, status=1)["error"]
        self.assertEqual(error["code"], "E_PARTIAL")
        self.assertEqual(error["details"]["receipt_status"], "partial")
        self.assertEqual(error["details"]["state_after"], "observed_changed")
        self.assertEqual(drawing["gtols"], before_rows)
        self.assertFalse(error["details"]["rollback_performed"])


def case(method, noun):
    def run(self):
        getattr(self, method)(noun)

    run.__doc__ = f"Offline fixture {noun}: {method.replace('_', ' ')}."
    return run


for noun in SHOWS:
    for scenario in (
        "show_success",
        "show_selector_refusals",
        "show_acquisition_refusals",
        "show_scope_refusals",
    ):
        setattr(DrawingResourceFCC, f"test_{noun}_{scenario}", case(scenario, noun))
for noun in KINDS:
    for scenario in (
        "remove_success",
        "remove_wrong_kind_and_missing_gates",
        "remove_missing_target",
        "remove_incomplete_preview",
        "remove_external_drawing",
        "remove_stale_preview",
        "remove_service_refusal",
        "remove_no_op_writer",
        "remove_read_permission",
        "remove_failure_after_mutation",
        "remove_incomplete_readback",
        "remove_changed_sibling",
        "remove_ambiguous_target",
    ):
        setattr(DrawingResourceFCC, f"test_{noun}_{scenario}", case(scenario, noun))
