"""Pure, bounded paper-space warnings from an already obtained drawing snapshot.

Rectangles are evidence of their stated scope, never proof of full drawing clearance.
This module neither obtains CAD readings nor qualifies a cross-time envelope contract.
"""

from __future__ import annotations

import math

EXCLUSIONS = (
    "dimension_and_extension_lines",
    "leader_paths_and_arrowheads",
    "balloon_circle_and_glyph_bounds",
    "exact_projected_contours",
    "complete_draft_line_geometry",
    "actual_table_cell_text_fit",
    "future_text_rerouting",
    "cross_time_dimension_envelope_preservation",
    "symbol_gtol_and_datum_display_bounds",
)
SOURCES = {
    "views": "View2D.GetOutline + drawing.GetSheetTransform",
    "dimensions": "WDimension.GetEnvelope(drawing,-1) + drawing.GetSheetTransform",
    "notes": "not_recorded_in_snapshot",
    "tables": "Table.GetInfo(0).GetOutline + table segment sheet transform",
}


def point(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(n) in (int, float) and math.isfinite(n) for n in value)
    )


def bounds(value):
    """Zero extent has no supported interpretation as zero-size visible content."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(point(p) for p in value)
        and all(value[0][i] < value[1][i] for i in (0, 1))
    )


def identity(kind, row):
    if kind == "dimensions":
        return f"{row.get('name')}@{row.get('model')}:{row.get('id')}"
    return str(row.get("name") if kind == "views" else row.get("id"))


def proposal(kind, row, outline=None, *, sheet=None, source="requested rectangle"):
    """A prediction is labelled separately from its frozen native source rectangle."""
    return {
        "kind": kind,
        "object": identity(kind, row),
        "name": row.get("name"),
        "sheet": row.get("sheet") if sheet is None else sheet,
        "bounds": outline,
        "source": source,
        "predicted": True,
        "row": row,
    }


def translated(kind, row, at, *, sheet=None):
    box = row.get("box" if kind in ("dimensions", "notes") else "outline")
    origin = row.get("at")
    if kind == "views" and bounds(box):
        origin = [(box[0][i] + box[1][i]) / 2 for i in (0, 1)]
    predicted = (
        [[p[i] + at[i] - origin[i] for i in (0, 1)] for p in box]
        if bounds(box) and point(origin) and point(at)
        else None
    )
    return proposal(
        kind, row, predicted, sheet=sheet, source="translation of frozen native rectangle"
    )


def feedback(drawing, *, proposals=None):
    """Report same-page rectangle candidates and explicit gaps; no native calls.

    With proposals, compare only requested rectangles to frozen peers. Without them,
    screen the current snapshot. Existing R5 dimension aggregates stay unqualified even
    when coordinates are finite or repeated observations happen to match.
    """
    pages, ambiguous = {}, set()
    unchecked, checked, objects, conflicts = [], [], [], []
    for sheet in drawing.get("sheets") or []:
        number = sheet.get("number")
        if type(number) is not int or number < 1:
            unchecked.append(
                {"kind": "sheets", "object": number, "reason": "invalid_page_identity"}
            )
            continue
        if type(number) is int and number > 0 and number not in pages and number not in ambiguous:
            pages[number] = sheet
        else:
            pages.pop(number, None)
            ambiguous.add(number)
            unchecked.append({"kind": "sheets", "object": number, "reason": "ambiguous_page"})
    inventories = {kind: drawing.get(kind) or [] for kind in SOURCES}

    def present(value):
        return isinstance(value, str) and bool(value.strip())

    def object_key(kind, row):
        ident = row.get("id")
        if type(ident) not in (str, int) or ident == "":
            return None
        # Dimension IDs are model-owned; detail/view IDs are drawing-owned. Pages
        # do not turn duplicate native IDs into different native objects.
        owner = row.get("model") if kind == "dimensions" else drawing.get("model")
        return (str(owner).casefold(), str(ident))

    duplicate_ids = {
        kind: {
            key
            for key in (object_key(kind, row) for row in inventory)
            if key is not None and sum(object_key(kind, other) == key for other in inventory) > 1
        }
        for kind, inventory in inventories.items()
    }

    def view_name_matches(name):
        return [
            (i, view)
            for i, view in enumerate(inventories["views"])
            if present(name)
            and present(view.get("name"))
            and view["name"].casefold() == name.casefold()
        ]

    def view_page_usable(row):
        page = row.get("sheet")
        return type(page) is int and page > 0 and page in pages

    def own_identity_reasons(kind, row):
        reasons = []
        if not present(drawing.get("model")):
            reasons.append("drawing_model_unavailable")
        if kind == "views":
            if not present(row.get("name")):
                reasons.append("object_identity_unavailable")
            if not present(row.get("model")):
                reasons.append("view_model_unavailable")
            if not view_page_usable(row):
                reasons.append("view_sheet_unavailable")
            peers = view_name_matches(row.get("name"))
            if sum(v.get("sheet") == row.get("sheet") for _, v in peers) > 1:
                reasons.append("ambiguous_view_name_on_sheet")
        elif object_key(kind, row) is None:
            reasons.append("object_identity_unavailable")
        if object_key(kind, row) in duplicate_ids[kind]:
            reasons.append("ambiguous_object_id")
        if kind == "dimensions" and not present(row.get("model")):
            reasons.append("dimension_model_unavailable")
        return reasons

    def frozen_identity(kind, row):
        """Resolve only native snapshot fields, never a proposed destination page."""
        page, reasons, matches = row.get("sheet"), own_identity_reasons(kind, row), []
        if kind != "dimensions":
            return page, reasons, matches
        if not present(row.get("view")):
            reasons.append("dimension_view_unavailable")
            return page, reasons, matches
        named = view_name_matches(row["view"])
        matches = named
        if page is not None:
            matches = [(i, v) for i, v in named if not view_page_usable(v) or v["sheet"] == page]
        if not named:
            reasons.append("dimension_view_not_in_snapshot")
        elif not matches:
            reasons.append("dimension_view_sheet_mismatch")
        elif len(matches) != 1:
            reasons.append("ambiguous_dimension_view")
        else:
            _, view = matches[0]
            if own_identity_reasons("views", view):
                reasons.append("dimension_view_identity_unavailable")
            if page is None:
                page = view.get("sheet")
        return page, reasons, [i for i, _ in matches]

    def same_identity(kind, a, b):
        if kind == "views":
            return (
                present(a.get("name"))
                and present(b.get("name"))
                and a["name"].casefold() == b["name"].casefold()
                and a.get("sheet") == b.get("sheet")
            ) or (object_key(kind, a) is not None and object_key(kind, a) == object_key(kind, b))
        return object_key(kind, a) is not None and object_key(kind, a) == object_key(kind, b)

    plans = []
    for index, planned in enumerate(proposals or []):
        kind, row = planned["kind"], planned["row"]
        matches = [
            i for i, other in enumerate(inventories[kind]) if same_identity(kind, row, other)
        ]
        reasons = []
        duplicate = (
            sum(p["kind"] == kind and same_identity(kind, row, p["row"]) for p in proposals) > 1
        )
        if duplicate:
            reasons.append("ambiguous_proposal_identity")
        if len(matches) > 1:
            reasons.append("ambiguous_proposal_target")
        elif matches and row != inventories[kind][matches[0]]:
            reasons.append("proposal_source_not_equal_to_frozen_row")
        elif not matches and planned["source"] == "translation of frozen native rectangle":
            reasons.append("proposal_target_not_in_snapshot")
        _, source_reasons, _ = frozen_identity(kind, row)
        if source_reasons:
            reasons.extend(source_reasons)
        plans.append((planned, index, matches, reasons))

    def record(kind, row, snapshot_index=None, planned=None, proposal_index=None, issues=()):
        page, reasons, matched_views = frozen_identity(kind, row)
        reasons.extend(issues)
        sheet_source = (
            "explicit frozen row sheet"
            if row.get("sheet") is not None
            else "unique frozen dimension view sheet"
            if kind == "dimensions" and len(matched_views) == 1 and page is not None
            else "not_resolved_in_snapshot"
        )
        if planned and planned.get("sheet") is not None:
            if type(planned["sheet"]) is not int or planned["sheet"] < 1:
                reasons.append("proposal_sheet_invalid")
            elif page is not None and planned["sheet"] != page:
                reasons.append("proposal_sheet_mismatch")
            elif page is None and kind != "dimensions":
                # New rectangles may declare their page; a translation may not
                # supply missing native ownership or repair an ambiguous match.
                if planned["source"] == "translation of frozen native rectangle":
                    reasons.append("proposal_source_sheet_unavailable")
                else:
                    page, sheet_source = planned["sheet"], "explicit new proposal sheet"
        page_key = page if type(page) is int else None
        sheet = pages.get(page_key, {})
        unit = sheet.get("units")
        raw = (
            planned.get("bounds")
            if planned
            else row.get("box" if kind in ("dimensions", "notes") else "outline")
        )
        note_bounds = row.get("bounds_readback")
        note_bounds = note_bounds if isinstance(note_bounds, dict) else {}
        note_source = note_bounds.get("source")
        note_source_recorded = isinstance(note_source, str) and bool(note_source.strip())
        source = note_source if kind == "notes" and note_source_recorded else SOURCES[kind]
        out = {
            "kind": kind,
            "object": identity(kind, row),
            "id": row.get("id"),
            "name": row.get("name"),
            "owner_model": row.get("model"),
            "view": row.get("view"),
            "sheet": page,
            "sheet_source": sheet_source,
            "snapshot_index": snapshot_index,
            "proposal_index": proposal_index,
            "identity_source": {
                "drawing": drawing.get("model"),
                "inventory": kind,
                "snapshot_index": snapshot_index,
                "proposal_index": proposal_index,
                "matched_view_indexes": matched_views,
            },
            "units": unit,
            "coordinate_system": "sheet_xy_lower_left" if page_key in pages else None,
            "raw_bounds": row.get("box" if kind in ("dimensions", "notes") else "outline"),
            "candidate_bounds": raw,
            "source": planned["source"] if planned else source,
            "predicted": planned is not None,
        }
        if planned:
            out["prediction_source"] = planned["source"]
        if page_key not in pages:
            reasons.append("sheet_unavailable")
        if not isinstance(unit, str) or not unit.strip():
            reasons.append("sheet_units_unavailable")
        if row.get("units") not in (None, unit):
            reasons.append("object_sheet_units_mismatch")
        if not bounds(raw):
            reasons.append("bounds_unavailable_or_invalid")
        if kind == "dimensions":
            out.update(
                representation="legacy_native_aggregate",
                cross_time="unverified",
                completeness="completeness_not_independently_recorded",
            )
        out["candidate_available"] = not reasons
        qualification = []
        if kind == "notes":
            if note_bounds.get("complete") is not True:
                qualification.append("note_bounds_readback_incomplete")
            if not note_source_recorded:
                qualification.append("note_bounds_source_not_recorded")
        if kind == "tables" and row.get("segments") != 1:
            qualification.append("single_table_segment_not_recorded")
        if kind == "tables" and not row.get("bounds_source"):
            qualification.append("table_bounds_source_not_recorded")
        out["reliable_coverage"] = not reasons and not qualification and kind != "dimensions"
        objects.append(out)
        provenance = {
            "snapshot_index": snapshot_index,
            "proposal_index": proposal_index,
            "identity_source": out["identity_source"],
        }
        unchecked.extend(
            {
                "kind": kind,
                "object": out["object"],
                "sheet": page,
                "units": unit,
                "reason": reason,
                **provenance,
            }
            for reason in qualification
        )
        if reasons:
            unchecked.extend(
                {
                    "kind": kind,
                    "object": out["object"],
                    "sheet": page,
                    "reason": reason,
                    **provenance,
                }
                for reason in dict.fromkeys(reasons)
            )
        elif kind == "dimensions":
            unchecked.append(
                {
                    "kind": kind,
                    "object": out["object"],
                    "sheet": page,
                    "reason": "legacy_native_aggregate_not_qualified",
                    **provenance,
                }
            )
        elif not qualification:
            checked.append(
                {k: out[k] for k in ("kind", "object", "sheet", "units", "source", "predicted")}
            )
        return out

    excluded = {
        (p["kind"], matches[0])
        for p, _, matches, reasons in plans
        if len(matches) == 1 and not reasons
    }
    for kind in SOURCES:
        if not isinstance(drawing.get(kind), list):
            unchecked.append({"kind": kind, "reason": "inventory_not_in_snapshot"})
        for index, row in enumerate(inventories[kind]):
            if (kind, index) not in excluded:
                record(kind, row, snapshot_index=index)
            if kind == "views":
                dependency = row.get("dependency_readback") or {}
                if dependency.get("alignment_complete") is not True:
                    unchecked.append(
                        {
                            "kind": "view_alignment",
                            "object": identity(kind, row),
                            "reason": "not_readable_in_snapshot",
                            "observed": dependency,
                            "snapshot_index": index,
                        }
                    )
    peers = list(objects)
    targets = (
        [
            record(
                p["kind"],
                p["row"],
                snapshot_index=matches[0] if len(matches) == 1 else None,
                planned=p,
                proposal_index=index,
                issues=reasons,
            )
            for p, index, matches, reasons in plans
        ]
        if proposals
        else peers
    )
    for i, a in enumerate(targets):
        if not a["candidate_available"]:
            continue
        box = a["candidate_bounds"]
        sheet = pages[a["sheet"]]
        size = [sheet.get("width"), sheet.get("height")]
        if all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in size):
            if any(box[0][j] < 0 or box[1][j] > size[j] for j in (0, 1)):
                conflicts.append(
                    {
                        "kind": "possible_paper_edge_crossing",
                        "objects": [a["object"]],
                        "sheet": a["sheet"],
                        "units": a["units"],
                    }
                )
        else:
            unchecked.append(
                {
                    "kind": "paper_edge",
                    "object": a["object"],
                    "sheet": a["sheet"],
                    "reason": "sheet_size_unavailable",
                }
            )
        others = peers + targets[i + 1 :] if proposals else peers[i + 1 :]
        for b in others:
            if not b["candidate_available"] or a["sheet"] != b["sheet"] or a["units"] != b["units"]:
                continue
            other = b["candidate_bounds"]
            if all(max(box[0][j], other[0][j]) < min(box[1][j], other[1][j]) for j in (0, 1)):
                conflicts.append(
                    {
                        "kind": "possible_view_boundary_intersection"
                        if "views" in (a["kind"], b["kind"])
                        else "possible_rectangle_intersection",
                        "objects": [a["object"], b["object"]],
                        "object_kinds": [a["kind"], b["kind"]],
                        "sheet": a["sheet"],
                        "units": a["units"],
                        "bounds": [box, other],
                        "reliable_rectangles": a["reliable_coverage"] and b["reliable_coverage"],
                        "meaning": "candidate AABB intersection; not exact contour, glyph "
                        "or line collision",
                    }
                )
    unchecked.extend({"kind": kind, "reason": "outside_rectangle_contract"} for kind in EXCLUSIONS)
    if isinstance(drawing.get("draft_entity_readback"), dict):
        unchecked.append(
            {
                "kind": "draft_native_readback",
                "reason": "does_not_prove_complete_draft_line_geometry",
                "observed": drawing["draft_entity_readback"],
            }
        )
    return {
        "scope": "frozen snapshot rectangle candidates only",
        "source": "already obtained drawing observation; no additional CAD getters",
        "drawing": drawing.get("model"),
        "snapshot_identity": {k: drawing.get(k) for k in ("model", "origin", "modified")},
        "observation_time": drawing.get("observed_at"),
        "observation_time_source": "snapshot observed_at"
        if drawing.get("observed_at")
        else "not_recorded_in_snapshot",
        "sheets": [
            {"sheet": n, "units": s.get("units"), "coordinate_system": "sheet_xy_lower_left"}
            for n, s in pages.items()
        ],
        "objects": objects,
        "checked": checked,
        "not_checked": unchecked,
        "conflicts": conflicts,
        "whole_layout_verified": False,
        "cross_time_protection_verified": False,
        "layout_coverage": {
            "complete": False,
            "meaning": "checked rectangle scopes only; not whole drawing clearance",
        },
        "empty_conflicts_means": "no candidate intersection in the usable frozen rectangles; "
        "unchecked coverage remains",
    }
