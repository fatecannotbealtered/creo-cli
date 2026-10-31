"""Bounded warning coverage; fixture HTTP is separate from native evidence."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from creo_cli import bom, drawing_warnings, registry
from creo_cli.core import Error
from tests import test_capabilities as capabilities
from tests.fixture import Refused
from tests.test_commands import domain_preview


def snapshot():
    return {
        "model": "fixture.drw",
        "origin": "fixture.drw.1",
        "modified": False,
        "sheets": [{"number": 1, "units": "mm", "width": 100, "height": 100}],
        "views": [],
        "dimensions": [],
        "notes": [],
        "tables": [],
    }


def note(ident="n1", box=None, sheet=1):
    return {
        "id": ident,
        "sheet": sheet,
        "box": box or [[40, 40], [45, 45]],
        "bounds_readback": {
            "complete": True,
            "source": "synthetic rectangle fixture; not native evidence",
        },
    }


@pytest.mark.parametrize(
    "source",
    [
        "DetailNoteItem.GetLineEnvelope; actual sheet transform and matrix",
        "WDetailNoteItem.Get3DLineEnvelope + note sheet transform",
    ],
)
def test_note_rectangle_reports_actual_recorded_source_without_3d_fallback(source):
    before = snapshot()
    row = note()
    row["bounds_readback"]["source"] = source
    before["notes"] = [row]
    frozen = deepcopy(before)
    out = drawing_warnings.feedback(before)
    assert before == frozen
    assert out["objects"][0]["source"] == source
    assert out["checked"][0]["source"] == source
    assert out["objects"][0]["reliable_coverage"]
    assert not out["whole_layout_verified"]
    assert not out["cross_time_protection_verified"]


@pytest.mark.parametrize("source", [None, "", " ", [], 1, True])
def test_note_rectangle_missing_source_remains_unqualified(source):
    before = snapshot()
    row = note()
    row["bounds_readback"]["source"] = source
    before["notes"] = [row, note("n2")]
    out = drawing_warnings.feedback(before)
    actual = out["objects"][0]
    assert actual["source"] == "not_recorded_in_snapshot"
    assert actual["candidate_available"] and not actual["reliable_coverage"]
    assert not any(x["object"] == "n1" for x in out["checked"])
    gap = next(x for x in out["not_checked"] if x["reason"] == "note_bounds_source_not_recorded")
    assert (gap["object"], gap["sheet"], gap["units"]) == ("n1", 1, "mm")
    assert out["conflicts"] and not out["conflicts"][0]["reliable_rectangles"]


@pytest.mark.parametrize("complete", [False, None, 0, 1, "true"])
def test_note_rectangle_recorded_source_does_not_replace_complete_readback(complete):
    before = snapshot()
    row = note()
    row["bounds_readback"]["complete"] = complete
    before["notes"] = [row, note("n2")]
    out = drawing_warnings.feedback(before)
    actual = out["objects"][0]
    assert actual["source"] == row["bounds_readback"]["source"]
    assert actual["candidate_available"] and not actual["reliable_coverage"]
    assert not any(x["object"] == "n1" for x in out["checked"])
    assert any(x["reason"] == "note_bounds_readback_incomplete" for x in out["not_checked"])
    assert out["conflicts"] and not out["conflicts"][0]["reliable_rectangles"]


@pytest.mark.parametrize("readback", [None, {}, [], "legacy box only"])
def test_legacy_note_box_cannot_invent_getter_source_or_complete_status(readback):
    before = snapshot()
    row = note()
    row["bounds_readback"] = readback
    before["notes"] = [row]
    frozen = deepcopy(before)
    out = drawing_warnings.feedback(before)
    assert before == frozen
    assert out["objects"][0]["source"] == "not_recorded_in_snapshot"
    assert not out["objects"][0]["reliable_coverage"]
    assert not out["checked"]
    assert {"note_bounds_source_not_recorded", "note_bounds_readback_incomplete"} <= {
        x["reason"] for x in out["not_checked"]
    }


def test_translated_note_prediction_does_not_upgrade_incomplete_native_bounds():
    before = snapshot()
    row = note()
    row.update(at=[42, 42])
    row["bounds_readback"]["complete"] = False
    before["notes"] = [row]
    out = drawing_warnings.feedback(
        before, proposals=[drawing_warnings.translated("notes", row, [44, 44])]
    )
    actual = out["objects"][0]
    assert actual["predicted"] and actual["candidate_available"]
    assert actual["source"] == "translation of frozen native rectangle"
    assert not actual["reliable_coverage"] and not out["checked"]
    assert any(x["reason"] == "note_bounds_readback_incomplete" for x in out["not_checked"])


def dimension():
    return {
        "id": "8",
        "name": "d8",
        "model": "part.prt",
        "view": "FRONT",
        "sheet": 1,
        "at": [20, 20],
        "box": [[18, 18], [22, 22]],
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [[0, 0], [0, 1]],
        [[2, 0], [1, 1]],
        [[0, 0], [float("nan"), 2]],
        [[0, 0], [float("inf"), 2]],
        [[0, 0]],
    ],
)
def test_invalid_bounds_are_named_gaps_not_zero_extent(raw):
    before = snapshot()
    row = note()
    row["box"] = raw
    before["notes"] = [row]
    out = drawing_warnings.feedback(before)
    assert out["conflicts"] == []
    assert not out["whole_layout_verified"]
    assert not out["layout_coverage"]["complete"]
    assert any(x.get("reason") == "bounds_unavailable_or_invalid" for x in out["not_checked"])
    assert out["objects"][0]["raw_bounds"] is raw


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing_page", "sheet_unavailable"),
        ("unknown_page", "sheet_unavailable"),
        ("unit_missing", "sheet_units_unavailable"),
        ("unit_mismatch", "object_sheet_units_mismatch"),
        ("duplicate_page", "sheet_unavailable"),
    ],
)
def test_page_unit_and_identity_gaps_are_not_defaulted(change, reason):
    before = snapshot()
    row = note()
    before["notes"] = [row]
    if change == "missing_page":
        row.pop("sheet")
    elif change == "unknown_page":
        row["sheet"] = 8
    elif change == "unit_missing":
        before["sheets"][0].pop("units")
    elif change == "unit_mismatch":
        row["units"] = "in"
    else:
        before["sheets"].append(dict(before["sheets"][0]))
    out = drawing_warnings.feedback(before)
    assert out["conflicts"] == []
    assert not out["checked"]
    assert any(x.get("reason") == reason for x in out["not_checked"])


def test_identical_xy_on_different_pages_has_no_conflict_and_no_mm_conversion():
    before = snapshot()
    before["sheets"].append({"number": 2, "units": "in", "width": 100, "height": 100})
    before["notes"] = [note("n1"), note("n2", sheet=2)]
    out = drawing_warnings.feedback(before)
    assert out["conflicts"] == []
    assert [r["units"] for r in out["checked"]] == ["mm", "in"]
    before["notes"][1]["sheet"] = 1
    same = drawing_warnings.feedback(before)
    assert same["conflicts"][0]["units"] == "mm"


def test_legacy_dimension_box_never_becomes_reliable_from_repetition_or_target_exception():
    before = snapshot()
    before["views"] = [
        {
            "id": "10",
            "name": "FRONT",
            "model": "part.prt",
            "sheet": 1,
            "outline": [[1, 1], [10, 10]],
        }
    ]
    before["dimensions"] = [dimension(), dimension() | {"id": "9", "name": "d9"}]
    before["notes"] = [note(box=[[18, 18], [22, 22]])]
    before["dimensions"][0]["target_box_exception"] = True
    first = drawing_warnings.feedback(before)
    second = drawing_warnings.feedback(deepcopy(before))
    assert first == second
    for row in first["objects"]:
        if row["kind"] == "dimensions":
            assert row["representation"] == "legacy_native_aggregate"
            assert row["cross_time"] == "unverified"
            assert row["completeness"] == "completeness_not_independently_recorded"
            assert row["candidate_available"] and not row["reliable_coverage"]
    assert not any(row["kind"] == "dimensions" for row in first["checked"])
    assert any(not c["reliable_rectangles"] for c in first["conflicts"])


def test_dimension_move_warns_notes_all_views_and_missing_table_without_extra_reading():
    from creo_cli.commands import detailing

    assert registry.COMMANDS
    before = snapshot()
    row = dimension()
    before.update(dimensions=[row], notes=[note()], tables=[{"id": "t1", "sheet": 1}])
    before["views"] = [
        {
            "id": "10",
            "name": "FRONT",
            "model": "part.prt",
            "sheet": 1,
            "outline": [[1, 1], [10, 10]],
        },
        {
            "id": "11",
            "name": "OTHER",
            "model": "part.prt",
            "sheet": 1,
            "outline": [[39, 35], [49, 49]],
        },
    ]
    out = detailing._dimension_move_feedback(before, row, [42, 42])
    assert {c["kind"] for c in out["conflicts"]} >= {
        "predicted_note_text_overlap",
        "possible_view_boundary_intersection",
    }
    assert any(c.get("object") == "OTHER" for c in out["conflicts"])
    assert any(
        c.get("kind") == "tables" and c.get("object") == "t1"
        for c in out["layout_feedback"]["not_checked"]
    )
    assert not out["layout_feedback"]["cross_time_protection_verified"]


def test_table_move_excludes_old_self_rectangle_and_warns_peer_text():
    before = snapshot()
    table = {
        "id": "1",
        "sheet": 1,
        "at": [20, 30],
        "outline": [[20, 20], [30, 30]],
        "segments": 1,
        "bounds_source": "fixture native outline",
    }
    before["tables"] = [table]
    before["notes"] = [note(box=[[30, 25], [35, 30]])]
    out = drawing_warnings.feedback(
        before, proposals=[drawing_warnings.translated("tables", table, [25, 30])]
    )
    assert len(out["conflicts"]) == 1
    assert out["conflicts"][0]["object_kinds"] == ["tables", "notes"]
    assert out["conflicts"][0]["reliable_rectangles"]
    assert before["tables"][0]["outline"] == [[20, 20], [30, 30]]
    target = next(o for o in out["objects"] if o["predicted"])
    assert target["raw_bounds"] == [[20, 20], [30, 30]]
    assert target["candidate_bounds"] == [[25, 20], [35, 30]]


def test_partial_table_rectangle_is_only_potential_warning_not_reliable_coverage():
    before = snapshot()
    before["tables"] = [{"id": "1", "sheet": 1, "outline": [[40, 40], [45, 45]]}]
    before["notes"] = [note()]
    out = drawing_warnings.feedback(before)
    assert out["conflicts"] and not out["conflicts"][0]["reliable_rectangles"]
    assert not any(r["kind"] == "tables" for r in out["checked"])
    assert any(r.get("reason") == "single_table_segment_not_recorded" for r in out["not_checked"])


def test_view_bounds_are_coarse_and_missing_outline_has_no_clearance_claim():
    from creo_cli.commands import drawing

    before = snapshot()
    before["views"] = [
        {
            "id": "10",
            "name": "FRONT",
            "model": "part.prt",
            "sheet": 1,
            "outline": [[39, 39], [50, 50]],
            "dependency_readback": {
                "alignment_complete": False,
                "error": {"code": "E_UNSUPPORTED"},
            },
        }
    ]
    before["notes"] = [note()]
    out = drawing_warnings.feedback(before)
    assert out["conflicts"][0]["kind"] == "possible_view_boundary_intersection"
    assert "not exact contour" in out["conflicts"][0]["meaning"]
    assert any(r["kind"] == "view_alignment" for r in out["not_checked"])
    missing = drawing.overlaps({"name": "MISSING", "sheet": 1}, before["views"], "fixture.drw")
    assert missing["views"] == [] and missing["available"] is False
    assert missing["not_checked"]
    assert (
        drawing.off_sheet(
            {"sheet": 8, "outline": [[1, 1], [5, 5]]}, before["sheets"], "fixture.drw"
        )["off"]
        is None
    )


def test_zero_dimension_extent_and_bom_soft_annotation_warning_preserve_existing_gates():
    from creo_cli.commands import drawing

    before = snapshot()
    before["dimensions"] = [dimension() | {"box": [[1, 1], [1, 2]]}]
    usable, missing = drawing._text_boxes(before)
    assert not usable and missing
    before["notes"] = [note(box=[[4, 4], [8, 8]])]
    region = bom.region(before, [[0, 0], [10, 10]], "test bounded region")
    assert region["layout_feedback"]["conflicts"]
    assert not region["layout_feedback"]["whole_layout_verified"]
    before["views"] = [
        {"id": "10", "name": "FRONT", "model": "part.prt", "sheet": 1, "outline": [[1, 1], [2, 2]]}
    ]
    with pytest.raises(Error) as refused:
        bom.region(before, [[0, 0], [10, 10]], "test bounded region")
    assert refused.value.code == "E_CONFLICT"


@pytest.fixture
def drawn_case():
    # Reuse the existing qualified fixture setup without collecting its inherited tests.
    case = capabilities.DrawnBlock(methodName="runTest")
    try:
        case.setUp()
        yield case
    finally:
        case.doCleanups()


def move_args(case):
    case.gated("drawing", "dimension", "annotate", "--model", "block.drw")
    model = case.world.models["block.drw"]
    row = model["shown_dims"][0]
    row.update(at=[20, 20], box=[[18, 18], [22, 22]], view=model["views"][0]["name"], sheet=1)
    return (
        model,
        row,
        (
            "drawing",
            "dimension",
            "move",
            "--model",
            "block.drw",
            "--dimension",
            row["name"],
            "--x",
            42,
            "--y",
            42,
        ),
    )


def test_public_dimension_preview_warns_known_note_without_setter(drawn_case):
    case = drawn_case
    model, _, args = move_args(case)
    model["notes"] = [note()]
    events = len(case.world.events)
    result = case.cli(*args, "--dry-run")["data"]["preview"]["extensions"]["creo"]
    assert any(
        c["kind"] == "predicted_note_text_overlap"
        for c in result["annotation_feedback"]["conflicts"]
    )
    assert result["layout_feedback"]["layout_coverage"]["complete"] is False
    assert not any(op == "drawing.move-dimension" for op, _ in case.world.events[events:])


def test_public_view_move_and_add_preview_disclose_coarse_and_future_gaps(drawn_case):
    case = drawn_case
    model = case.world.models["block.drw"]
    row = model["views"][0]
    row.update(sheet=1, outline=[[20, 20], [40, 40]])
    model["notes"] = [note()]
    events = len(case.world.events)
    moved = domain_preview(
        case.cli(
            "drawing",
            "view",
            "move",
            "--model",
            "block.drw",
            "--view",
            row["name"],
            "--x",
            42,
            "--y",
            42,
            "--dry-run",
        )["data"]["preview"]
    )
    assert any(
        c["kind"] == "possible_view_boundary_intersection"
        for c in moved["layout_feedback"]["conflicts"]
    )
    added = domain_preview(
        case.cli(
            "drawing",
            "view",
            "add",
            "--model",
            "block.drw",
            "--type",
            "general",
            "--orientation",
            "front",
            "--name",
            "NEW_FRONT",
            "--x",
            240,
            "--y",
            180,
            "--dry-run",
        )["data"]["preview"]
    )
    assert "unavailable before native creation" in added["future_view_extent"]
    assert not added["layout_feedback"]["whole_layout_verified"]
    assert not any(
        op in ("drawing.move-view", "drawing.add-view") for op, _ in case.world.events[events:]
    )


def test_public_table_move_warns_peer_text_without_setter(drawn_case):
    case = drawn_case
    request = case.request(
        {"units": "mm", "at": [180, 35], "columns": [50], "rows": [8], "cells": [["SYNTHETIC"]]}
    )
    result = case.gated("drawing", "table", "add", "--model", "block.drw", "--request", request)[
        "data"
    ]["result"]
    table = result["table"]
    case.world.models["block.drw"]["notes"] = [note(box=[[185, 31], [192, 36]])]
    events = len(case.world.events)
    moved = domain_preview(
        case.cli(
            "drawing",
            "table",
            "move",
            "--model",
            "block.drw",
            "--table",
            table["id"],
            "--x",
            181,
            "--y",
            38,
            "--dry-run",
        )["data"]["preview"]
    )
    assert any(
        c.get("object_kinds") == ["tables", "notes"] for c in moved["layout_feedback"]["conflicts"]
    )
    assert not any(op == "drawing.move-table" for op, _ in case.world.events[events:])


def test_public_returned_unsupported_is_gap_not_pending(drawn_case):
    case = drawn_case
    _, _, args = move_args(case)
    original = case.world.op

    def ordinary(op, q):
        result = original(op, q)
        if op == "model.show" and q.get("model") == "block.drw":
            result["draft_entity_readback"] = {
                "completed": False,
                "items": None,
                "error": {"code": "E_UNSUPPORTED", "entity": "4"},
            }
        return result

    with patch.object(case.world, "op", side_effect=ordinary):
        result = case.cli(*args, "--dry-run")["data"]["preview"]["extensions"]["creo"][
            "layout_feedback"
        ]
    gap = next(x for x in result["not_checked"] if x["kind"] == "draft_native_readback")
    assert gap["observed"]["error"]["code"] == "E_UNSUPPORTED"
    assert gap["observed"]["items"] is None
    assert "drawing.move-dimension" not in case.world.ops()


def test_public_pending_preparation_stops_and_keeps_request_context(drawn_case):
    case = drawn_case
    _, _, args = move_args(case)
    original, seen = case.world.op, []

    def pending(op, q):
        seen.append(op)
        if op == "model.show" and q.get("model") == "block.drw":
            raise Refused(
                "E_BUSY",
                "controlled started read",
                started=True,
                diagnostic_request_id="fixture-read-1",
            )
        return original(op, q)

    with patch.object(case.world, "op", side_effect=pending):
        error = case.cli(*args, "--dry-run", status=8)["error"]
    assert error["code"] == "E_NATIVE_READ_PENDING"
    assert error["details"]["dispatch_state"] == "started"
    assert error["details"]["diagnostic_request_id"] == "fixture-read-1"
    assert error["details"]["operation"] == "model.show"
    assert seen[-1] == "model.show"
    assert "drawing.move-dimension" not in seen
