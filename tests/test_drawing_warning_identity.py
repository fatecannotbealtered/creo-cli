"""Identity counterexamples for frozen rectangles; no CAD, sockets or state stores."""

from copy import deepcopy

import pytest

from creo_cli import drawing_warnings as warnings


def snapshot():
    return {
        "model": "synthetic.drw",
        "sheets": [
            {"number": 1, "units": "mm", "width": 100, "height": 100},
            {"number": 2, "units": "mm", "width": 100, "height": 100},
        ],
        "views": [view()],
        "dimensions": [],
        "notes": [],
        "tables": [],
    }


def view(name="FRONT", ident="10", sheet=1):
    return {
        "name": name,
        "id": ident,
        "model": "synthetic.prt",
        "sheet": sheet,
        "outline": [[10, 10], [30, 30]],
    }


def dimension():
    return {
        "name": "d8",
        "id": "8",
        "model": "synthetic.prt",
        "view": "FRONT",
        "sheet": 1,
        "at": [20, 20],
        "box": [[18, 18], [22, 22]],
    }


def rows(out, kind, predicted=False):
    return [o for o in out["objects"] if o["kind"] == kind and o["predicted"] is predicted]


def assert_gaps(out, kind, indexes, reason):
    observed = {
        x.get("snapshot_index")
        for x in out["not_checked"]
        if x["kind"] == kind and x["reason"] == reason and x.get("proposal_index") is None
    }
    assert observed == set(indexes)


def test_duplicate_view_names_on_one_page_preserve_every_unchecked_row():
    before = snapshot()
    before["views"].append(view(ident="11"))
    out = warnings.feedback(before)
    assert len(rows(out, "views")) == 2
    assert not any(o["candidate_available"] for o in rows(out, "views"))
    assert_gaps(out, "views", [0, 1], "ambiguous_view_name_on_sheet")
    assert out["checked"] == []
    assert out["conflicts"] == []


@pytest.mark.parametrize("kind", ["views", "dimensions", "notes", "tables"])
def test_duplicate_native_ids_are_not_silently_merged_or_used(kind):
    before = snapshot()
    if kind == "views":
        before[kind] = [view(), view(name="SIDE", sheet=2)]
    elif kind == "dimensions":
        before[kind] = [dimension(), dimension() | {"name": "d9"}]
    else:
        before[kind] = [
            {
                "id": "7",
                "sheet": sheet,
                "box": [[10, 10], [20, 20]],
                "outline": [[10, 10], [20, 20]],
            }
            for sheet in (1, 2)
        ]
    out = warnings.feedback(before)
    assert len(rows(out, kind)) == 2
    assert not any(o["candidate_available"] for o in rows(out, kind))
    assert_gaps(out, kind, [0, 1], "ambiguous_object_id")


def test_cross_sheet_view_names_need_original_dimension_sheet_not_last_view():
    before = snapshot()
    before["views"].append(view(ident="11", sheet=2))
    d = dimension()
    d.pop("sheet")
    before["dimensions"] = [d]
    out = warnings.feedback(before)
    actual = rows(out, "dimensions")[0]
    assert actual["sheet"] is None
    assert not actual["candidate_available"]
    assert_gaps(out, "dimensions", [0], "ambiguous_dimension_view")
    assert len(rows(out, "views")) == 2
    assert all(o["candidate_available"] for o in rows(out, "views"))


def test_explicit_sheet_resolves_cross_sheet_name_without_moving_ownership():
    before = snapshot()
    before["views"].append(view(ident="11", sheet=2))
    before["dimensions"] = [dimension()]
    first = warnings.feedback(before)
    assert rows(first, "dimensions")[0]["candidate_available"]
    assert rows(first, "dimensions")[0]["sheet"] == 1
    before["views"].reverse()
    second = warnings.feedback(before)
    assert rows(second, "dimensions")[0]["candidate_available"]
    assert rows(second, "dimensions")[0]["sheet"] == 1


def test_unique_view_can_supply_missing_sheet_with_recorded_provenance():
    before = snapshot()
    d = dimension()
    d.pop("sheet")
    before["dimensions"] = [d]
    actual = rows(warnings.feedback(before), "dimensions")[0]
    assert actual["candidate_available"]
    assert actual["sheet"] == 1
    assert actual["sheet_source"] == "unique frozen dimension view sheet"
    assert actual["identity_source"]["matched_view_indexes"] == [0]


@pytest.mark.parametrize("field", ["model", "view"])
def test_missing_dimension_owner_or_view_does_not_become_usable(field):
    before = snapshot()
    d = dimension()
    d.pop(field)
    before["dimensions"] = [d]
    out = warnings.feedback(before)
    assert not rows(out, "dimensions")[0]["candidate_available"]
    assert_gaps(out, "dimensions", [0], f"dimension_{field}_unavailable")


def test_missing_referenced_view_is_distinct_from_missing_view_field():
    before = snapshot()
    before["dimensions"] = [dimension() | {"view": "ABSENT"}]
    out = warnings.feedback(before)
    assert not rows(out, "dimensions")[0]["candidate_available"]
    assert_gaps(out, "dimensions", [0], "dimension_view_not_in_snapshot")


def test_missing_view_model_is_not_inferred_from_its_dimension_owner():
    before = snapshot()
    before["views"][0].pop("model")
    before["dimensions"] = [dimension()]
    out = warnings.feedback(before)
    assert not rows(out, "views")[0]["candidate_available"]
    assert not rows(out, "dimensions")[0]["candidate_available"]
    assert_gaps(out, "views", [0], "view_model_unavailable")
    assert_gaps(out, "dimensions", [0], "dimension_view_identity_unavailable")


@pytest.mark.parametrize("view_sheet", ["absent", None, "1", True, 0, -1, 1.0])
def test_dimension_explicit_sheet_never_repairs_missing_or_invalid_view_sheet(view_sheet):
    before = snapshot()
    if view_sheet == "absent":
        before["views"][0].pop("sheet")
    else:
        before["views"][0]["sheet"] = view_sheet
    before["dimensions"] = [dimension()]
    original = deepcopy(before)
    out = warnings.feedback(before)
    assert before == original
    v, d = rows(out, "views")[0], rows(out, "dimensions")[0]
    assert not v["candidate_available"]
    assert not d["candidate_available"]
    assert v["raw_bounds"] == original["views"][0]["outline"]
    assert d["raw_bounds"] == original["dimensions"][0]["box"]
    assert d["sheet"] == 1
    assert v["snapshot_index"] == d["snapshot_index"] == 0
    assert d["identity_source"]["matched_view_indexes"] == [0]
    assert_gaps(out, "views", [0], "view_sheet_unavailable")
    assert_gaps(out, "dimensions", [0], "dimension_view_identity_unavailable")


@pytest.mark.parametrize("page_inventory", ["missing", "duplicate"])
def test_matched_view_page_conflict_with_sheet_inventory_keeps_dimension_unchecked(page_inventory):
    before = snapshot()
    if page_inventory == "missing":
        before["sheets"] = before["sheets"][1:]
    else:
        before["sheets"].append(deepcopy(before["sheets"][0]))
    before["dimensions"] = [dimension()]
    out = warnings.feedback(before)
    v, d = rows(out, "views")[0], rows(out, "dimensions")[0]
    assert not v["candidate_available"]
    assert not d["candidate_available"]
    assert v["sheet"] == d["sheet"] == 1
    assert v["snapshot_index"] == d["snapshot_index"] == 0
    assert d["identity_source"]["matched_view_indexes"] == [0]
    assert_gaps(out, "views", [0], "view_sheet_unavailable")
    assert_gaps(out, "dimensions", [0], "dimension_view_identity_unavailable")


def test_component_dimension_owner_can_differ_from_displayed_assembly_model():
    before = snapshot()
    before["views"][0]["model"] = "assembly.asm"
    before["dimensions"] = [dimension() | {"model": "component.prt"}]
    out = warnings.feedback(before)
    assert rows(out, "views")[0]["candidate_available"]
    assert rows(out, "dimensions")[0]["candidate_available"]
    assert rows(out, "dimensions")[0]["owner_model"] == "component.prt"


def test_missing_root_drawing_owner_keeps_each_note_unchecked():
    before = snapshot()
    before.pop("model")
    before["notes"] = [
        {"id": "5", "sheet": 1, "box": [[10, 10], [20, 20]]},
        {"id": "6", "sheet": 1, "box": [[15, 15], [25, 25]]},
    ]
    out = warnings.feedback(before)
    assert not any(o["candidate_available"] for o in rows(out, "notes"))
    assert_gaps(out, "notes", [0, 1], "drawing_model_unavailable")
    assert out["conflicts"] == []


def test_dimension_view_sheet_conflict_is_not_repaired_by_proposal_sheet():
    before = snapshot()
    d = dimension() | {"sheet": 2}
    before["dimensions"] = [d]
    planned = warnings.translated("dimensions", d, [21, 21], sheet=1)
    out = warnings.feedback(before, proposals=[planned])
    assert not rows(out, "dimensions", predicted=True)[0]["candidate_available"]
    assert any(x["reason"] == "proposal_sheet_mismatch" for x in out["not_checked"])
    assert any(x["reason"] == "dimension_view_sheet_mismatch" for x in out["not_checked"])


def test_proposal_cannot_supply_a_sheet_to_choose_between_ambiguous_views():
    before = snapshot()
    before["views"].append(view(ident="11", sheet=2))
    d = dimension()
    d.pop("sheet")
    before["dimensions"] = [d]
    out = warnings.feedback(
        before, proposals=[warnings.translated("dimensions", d, [21, 21], sheet=1)]
    )
    assert not rows(out, "dimensions", predicted=True)[0]["candidate_available"]
    assert any(x["reason"] == "ambiguous_dimension_view" for x in out["not_checked"])


def test_duplicate_proposal_identity_excludes_no_frozen_object():
    before = snapshot()
    d = dimension()
    before["dimensions"] = [d, deepcopy(d)]
    out = warnings.feedback(before, proposals=[warnings.translated("dimensions", d, [40, 40])])
    assert len(rows(out, "dimensions")) == 2
    assert len(rows(out, "dimensions", predicted=True)) == 1
    assert not any(o["candidate_available"] for o in rows(out, "dimensions", predicted=True))
    assert_gaps(out, "dimensions", [0, 1], "ambiguous_object_id")


def test_duplicate_proposals_do_not_exclude_the_only_frozen_target():
    before = snapshot()
    d = dimension()
    before["dimensions"] = [d]
    p = warnings.translated("dimensions", d, [40, 40])
    out = warnings.feedback(before, proposals=[p, deepcopy(p)])
    assert len(rows(out, "dimensions")) == 1
    assert len(rows(out, "dimensions", predicted=True)) == 2
    assert not any(o["candidate_available"] for o in rows(out, "dimensions", predicted=True))
    assert sum(x["reason"] == "ambiguous_proposal_identity" for x in out["not_checked"]) == 2


def test_stale_proposal_row_does_not_exclude_the_current_target():
    before = snapshot()
    d = dimension()
    before["dimensions"] = [d]
    stale = deepcopy(d)
    stale["box"] = [[1, 1], [2, 2]]
    out = warnings.feedback(before, proposals=[warnings.translated("dimensions", stale, [40, 40])])
    assert len(rows(out, "dimensions")) == 1
    assert not rows(out, "dimensions", predicted=True)[0]["candidate_available"]
    assert any(x["reason"] == "proposal_source_not_equal_to_frozen_row" for x in out["not_checked"])


def test_cross_sheet_same_name_move_excludes_only_exact_frozen_view():
    before = snapshot()
    before["views"].append(view(ident="11", sheet=2))
    out = warnings.feedback(
        before, proposals=[warnings.translated("views", deepcopy(before["views"][0]), [25, 25])]
    )
    assert [o["sheet"] for o in rows(out, "views")] == [2]
    assert [o["sheet"] for o in rows(out, "views", predicted=True)] == [1]
    assert out["conflicts"] == []
    assert all(o["candidate_available"] for o in out["objects"])


def test_dimension_id_duplicate_detection_preserves_native_id_string_and_owner_case():
    before = snapshot()
    before["dimensions"] = [dimension(), dimension() | {"id": 8, "model": "SYNTHETIC.PRT"}]
    out = warnings.feedback(before)
    assert not any(o["candidate_available"] for o in rows(out, "dimensions"))
    assert_gaps(out, "dimensions", [0, 1], "ambiguous_object_id")


def test_unique_move_excludes_only_its_own_row_and_keeps_page_and_rectangle_warning():
    before = snapshot()
    before["views"] = []
    n = {"id": "5", "sheet": 1, "at": [90, 90], "box": [[88, 88], [92, 92]]}
    before["notes"] = [n, {"id": "6", "sheet": 1, "box": [[98, 98], [104, 104]]}]
    out = warnings.feedback(
        before, proposals=[warnings.translated("notes", deepcopy(n), [100, 100])]
    )
    assert len(rows(out, "notes")) == 1
    assert len(rows(out, "notes", predicted=True)) == 1
    assert rows(out, "notes", predicted=True)[0]["candidate_available"]
    assert {c["kind"] for c in out["conflicts"]} == {
        "possible_paper_edge_crossing",
        "possible_rectangle_intersection",
    }
    assert not out["whole_layout_verified"]


def test_new_requested_rectangle_does_not_need_a_matching_frozen_target():
    before = snapshot()
    before["views"] = []
    before["notes"] = [{"id": "5", "sheet": 1, "box": [[10, 10], [20, 20]]}]
    p = warnings.proposal("tables", {"id": "requested", "sheet": 1}, [[15, 15], [30, 30]])
    out = warnings.feedback(before, proposals=[p])
    assert rows(out, "tables", predicted=True)[0]["candidate_available"]
    assert len(out["conflicts"]) == 1
