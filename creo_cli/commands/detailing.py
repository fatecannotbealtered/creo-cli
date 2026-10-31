"""drawing edit-note, move-dimension, add-dimension, add-table, add-symbol, remove: the rest
of detailing a drawing, as a person finishes one. Notes edited and moved; dimensions moved
off each other; reference dimensions for the sizes no feature carries (a total thickness);
tables (a title block, a parts list); symbols from Creo's library (surface finish, welds)
or the user's; and anything the drawing itself owns taken off again.

Every place is sheet coordinates from the sheet's lower left corner, in the sheet's units,
as model show reports sheets, notes, dimensions, tables and symbols."""

from __future__ import annotations

import datetime
import math
import re
import time
from copy import deepcopy

from .. import drawing_warnings, engine, paths
from ..core import Error, digest, read_request
from ..registry import MODEL, REQUEST, Command, Param
from ..schemas import INT, NS, WRITTEN, S, array, shape, written
from ..transport import Client
from ..validation import NUM, POS, strict, text, validate
from .drawing import (
    DIMENSION,
    DIMENSION_REF,
    GTOL,
    NOTE,
    SUMMARY,
    TABLE,
    _drawing,
    _match,
    note_text,
    on_sheet,
    own,
)

EDGE_REF = text(pattern=r"^edge:[0-9]{1,9}$", maximum=16)
# A view is named in Creo's own words, in the session's language (顶部_1); anything printable.
ITEM_REF = text(
    pattern=r"^(?:(?:note|table|symbol):[0-9]{1,9}|dimension:[A-Za-z][A-Za-z0-9_]{0,31}"
    r"|gtol:[0-9]{1,9}(?:@[A-Za-z][A-Za-z0-9_-]{0,30}\.(?:prt|asm|drw))?|datum:[A-Z]{1,2}"
    r"|view:[^\x00-\x1f]{1,80})$",
    maximum=90,
)
LIBRARY_SYMBOL = text(pattern=r"^[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64}){0,7}$", maximum=400)
VARIABLE = text(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,40}$", maximum=41)
VALUE_LIMIT = 100
CELL_LIMIT = 200
# The sheet's unit as the service names it, in the spelling requests use.
SHEET_UNITS = {"inch": "in", "foot": "ft"}
# Creo's standard sheets letter a table at 3.5 mm; measured in their PDFs, a character of its
# font -- Latin or Chinese -- takes about 0.85 of that across, and a cell keeps 2 mm clear.
TEXT_HEIGHT_MM = 3.5
CHARACTER_WIDTH = 0.85
CELL_MARGIN_MM = 2.0


def text_width(text: str, height: float = TEXT_HEIGHT_MM) -> float:
    """About how wide a line of a table's text is drawn, in millimetres."""
    return max((len(line) for line in str(text).split("\n")), default=0) * height * CHARACTER_WIDTH


def cells_too_narrow(q: dict) -> list:
    """The cells whose text, at the sheet's lettering, will not fit their column (merged cells
    are given the width they span)."""
    if q["units"] != "mm":
        return []
    spans = {}
    for r0, c0, r1, c1 in q.get("merge") or []:
        # Merged regions are row, column of one corner and of the other, from 1.
        spans[(min(r0, r1) - 1, min(c0, c1) - 1)] = sum(q["columns"][min(c0, c1) - 1 : max(c0, c1)])
    out = []
    for r, line in enumerate(q.get("cells") or []):
        for col, cell in enumerate(line):
            if not cell or col >= len(q["columns"]):
                continue
            room = spans.get((r, col), q["columns"][col]) - CELL_MARGIN_MM
            needed = text_width(cell)
            if needed > room:
                out.append(
                    {
                        "row": r,
                        "column": col,
                        "text": cell,
                        "needs": round(needed + CELL_MARGIN_MM, 1),
                        "width": spans.get((r, col), q["columns"][col]),
                    }
                )
    return out


def _close(a, b) -> bool:
    return (
        isinstance(a, list)
        and isinstance(b, list)
        and len(a) == len(b)
        and all(
            isinstance(x, int | float) and math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-6)
            for x, y in zip(a, b, strict=True)
        )
    )


def _plain(value: str, path: str, limit: int, lines: int = 1) -> str:
    if len(value) > limit or len(value.split("\n")) > lines:
        raise Error(
            "E_VALIDATION", f"at most {limit} characters on {lines} line(s)", {"path": path}
        )
    if any(ord(ch) < 32 and ch != "\n" for ch in value):
        raise Error("E_VALIDATION", "no control characters", {"path": path})
    return value


def _same_value(asked: str, shown) -> bool:
    """A symbol's variable as asked and as Creo reads it back. A numeric variable comes back
    in the drawing's number format: 3.2 as 3,200 on Creo's metric sheets (decimal comma,
    three places)."""
    if shown == asked:
        return True
    try:
        return math.isclose(
            float(asked.replace(",", ".")), float(str(shown).replace(",", ".")), rel_tol=1e-9
        )
    except ValueError:
        return False


def _place(opts: dict, required: bool = True) -> list | None:
    x, y = opts.get("x"), opts.get("y")
    if x is None and y is None and not required:
        return None
    if x is None or y is None:
        raise Error("E_VALIDATION", "give both x and y", {"path": "x" if x is None else "y"})
    for key, value in (("x", x), ("y", y)):
        if not math.isfinite(value):
            raise Error("E_VALIDATION", "x and y are sheet coordinates", {"path": key})
    return [x, y]


def _reading(client: Client, name: str) -> dict:
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    return before


# ------------------------------------------------------------------ edit-note


def _prepare_edit(opts: dict) -> dict:
    at = _place(opts, required=False)
    if opts.get("text") is None and at is None:
        raise Error(
            "E_VALIDATION",
            "give the note's new --text, a new place --x --y, or both",
            {"path": "text"},
        )
    validate(opts["note"], text(pattern=r"^[0-9]{1,9}$", maximum=9), "note")
    return {
        "name": _drawing(opts),
        "note": opts["note"],
        "text": None if opts.get("text") is None else note_text(opts["text"]),
        "at": at,
    }


def _plan_edit(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted, new_text, at = pre["name"], pre["note"], pre["text"], pre["at"]
    before = _reading(client, name)
    notes = before.get("notes") or []
    target = next((n for n in notes if str(n.get("id")) == wanted), None)
    if target is None:
        raise Error(
            "E_NOT_FOUND",
            "the drawing has no note of that id",
            {
                "note": wanted,
                "notes": [n.get("id") for n in notes],
                "fix": f"creo-cli model show --model {name} lists them under notes",
                "_untrusted": ["notes"],
            },
        )
    symbolic_section = re.search(
        r"(?<!&)&xsec_name\b", str(target.get("text", "")), re.I
    ) and target.get("displayed_text") != target.get("text")
    if target.get("read_only") is True or symbolic_section:
        raise Error(
            "E_UNSUPPORTED",
            ("native read-only or generated SECTION note cannot be edited by this path"),
            {
                "note": wanted,
                "read_only": target.get("read_only"),
                "symbolic_section": bool(symbolic_section),
                "fix": (
                    "keep the generated caption; preview a supported ordinary annotation "
                    "or dimension placement instead"
                ),
            },
        )
    if at is not None:
        on_sheet(before, at[0], at[1], "note")
        if target.get("at") is None:
            raise Error(
                "E_CONFLICT",
                "the note is attached to something on the drawing; only a free note is moved",
                {"note": wanted},
            )
    request = {"model": name, "note": int(wanted)}
    if new_text is not None:
        request["text"] = new_text
    if at is not None:
        request["at"] = at

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("notes") or []
        row = next((n for n in after if str(n.get("id")) == wanted), None)
        others = [n for n in notes if str(n.get("id")) != wanted]
        checks = [engine.check("note_still_there", row is not None)]
        if new_text is not None:
            checks.append(
                engine.check(
                    "note_says_what_was_asked",
                    row is not None and row.get("text") == new_text,
                    text=row.get("text") if row else None,
                )
            )
        if at is not None:
            checks.append(
                engine.check(
                    "note_where_asked",
                    row is not None and _close(row.get("at"), at),
                    at=row.get("at") if row else None,
                )
            )
        checks.append(
            engine.check(
                "other_notes_untouched",
                all(any(o == a for a in after) for o in others) and len(after) == len(notes),
            )
        )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": ["overlap_with_views_or_dimensions"],
        }

    return engine.Plan(
        op="drawing.edit-note",
        request=request,
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing edit-note",
            "model": name,
            "note": target,
            "text": new_text if new_text is not None else target.get("text"),
            "at": at if at is not None else target.get("at"),
            "native_editability": "not read-only"
            if target.get("read_only") is False
            else (
                "getter unavailable; native refusal is possible and must be read back, not replayed"
            ),
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("notes"),
        before=notes,
        arguments={k: opts.get(k) for k in ("model", "note", "text", "x", "y")},
    )


def edit_note(opts: dict) -> dict:
    return engine.write("drawing edit-note", opts, _prepare_edit, _plan_edit)


# ------------------------------------------------------------------ move-dimension


def _prepare_move(opts: dict) -> dict:
    validate(opts["dimension"], DIMENSION_REF, "dimension")
    return {"name": _drawing(opts), "dimension": opts["dimension"], "at": _place(opts)}


def _dimension_move_feedback(before, target, at):
    """Legacy dimension rectangles produce potential current warnings, not protection."""
    view = next((v for v in before.get("views", []) if v.get("name") == target.get("view")), {})
    sheet = target.get("sheet") if target.get("sheet") is not None else view.get("sheet")
    planned = drawing_warnings.translated("dimensions", target, at, sheet=sheet)
    coverage = drawing_warnings.feedback(before, proposals=[planned])
    target_coverage = next(o for o in coverage["objects"] if o["predicted"])
    result = {
        "sheet": sheet,
        "source": "translated frozen legacy native aggregate; prediction only",
        "conflicts": [],
        "not_checked": list(drawing_warnings.EXCLUSIONS),
        "layout_feedback": coverage,
        "available": target_coverage["candidate_available"],
        "cross_time": "unverified",
        "completeness": "completeness_not_independently_recorded",
    }
    if not result["available"]:
        return result | {
            "reason": "identified sheet, units or native text extent unavailable; "
            "no zero-size assumption"
        }
    result["predicted_text_box"] = planned["bounds"]
    for conflict in coverage["conflicts"]:
        entry = dict(conflict)
        if conflict["kind"] == "possible_paper_edge_crossing":
            entry.update(kind="predicted_text_outside_sheet", object=sheet)
        else:
            kind = conflict["object_kinds"][1]
            entry["kind"] = {
                "views": "possible_view_boundary_intersection",
                "tables": "predicted_table_overlap",
                "notes": "predicted_note_text_overlap",
                "dimensions": "predicted_text_overlap",
            }[kind]
            obj = next(
                o
                for o in coverage["objects"]
                if o["kind"] == kind and o["object"] == conflict["objects"][1]
            )
            entry["object"] = obj["name"] if kind == "dimensions" else obj["object"]
            entry["bounds"] = conflict["bounds"][1]
        result["conflicts"].append(entry)
    return result


def _dimension_box_consistent(before, after, at):
    """Compare actual envelopes; translation is a predicate, never returned as a reading."""
    if not after or not _close(after.get("at"), at):
        return False
    try:
        for row in (before, after):
            box = row["box"]
            if (
                len(box) != 2
                or any(len(p) != 2 for p in box)
                or not all(math.isfinite(v) for point in box for v in point)
                or any(box[0][i] >= box[1][i] for i in (0, 1))
            ):
                return False
        return all(
            math.isclose(
                after["box"][j][i] - after["at"][i],
                before["box"][j][i] - before["at"][i],
                abs_tol=1e-5,
            )
            for j in (0, 1)
            for i in (0, 1)
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def _plan_move(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, wanted, at = pre["name"], pre["dimension"], pre["at"]
    before = _reading(client, name)
    rows = before.get("dimensions") or []
    hits = _match(rows, wanted)
    if not hits:
        raise Error(
            "E_NOT_FOUND",
            "the drawing shows no dimension of that name",
            {
                "dimension": wanted,
                "shown": [r.get("name") for r in rows],
                "fix": f"creo-cli model show --model {name} lists them under dimensions",
                "_untrusted": ["dimension", "shown"],
            },
        )
    if len(hits) > 1:
        raise Error(
            "E_CONFLICT",
            "two dimensions carry that name; write it as name@model",
            {
                "dimension": wanted,
                "models": [h.get("model") for h in hits],
                "_untrusted": ["models"],
            },
        )
    target = hits[0]
    if len(before.get("sheets", [])) != 1:
        raise Error(
            "E_UNSUPPORTED", "dimension movement currently requires one explicit drawing sheet"
        )
    on_sheet(before, at[0], at[1], "dimension")
    placement_feedback = _dimension_move_feedback(before, target, at)

    def verify(c: Client, data: dict):
        started = time.monotonic()
        # Separate service calls yield back to Creo; no move retry or fixed delay.
        until = min(c.deadline, started + 12.0)
        readings, last, previous, row, error = [], None, None, None, None
        coherent = False
        for _ in range(6):
            if time.monotonic() >= until:
                error = "E_TIMEOUT"
                break
            try:
                deadline = c.deadline
                try:
                    c.deadline = min(deadline, until)
                    last = engine.show(c, name)
                finally:
                    c.deadline = deadline
            except Error as exc:
                if exc.code not in engine.READ_BACK_FAILURES:
                    raise
                error = exc.code
                break
            row = next(
                (
                    a
                    for a in last.get("dimensions", [])
                    if str(a.get("id")) == str(target.get("id"))
                    and a.get("model") == target.get("model")
                ),
                None,
            )
            readings.append(deepcopy(row))
            if _dimension_box_consistent(target, row, at):
                if previous and row == previous:
                    coherent = True
                    break
                previous = deepcopy(row)
            else:
                previous = None
        after = (last or {}).get("dimensions") or []
        moved_too = [
            a.get("name")
            for a in after
            for b in rows
            if a is not row
            and str(a.get("id")) == str(b.get("id"))
            and a.get("model") == b.get("model")
            and a.get("at") != b.get("at")
        ]
        result = deepcopy(last if last is not None else data)
        result["moved"] = data.get("moved")
        # Retain unreliable native boxes as observations, never usable layout bounds.
        if not coherent:
            for dim in result.get("dimensions", []):
                if str(dim.get("id")) == str(target.get("id")) and dim.get("model") == target.get(
                    "model"
                ):
                    dim["box"] = None
                    dim["box_status"] = "unverified_after_move"
        if last is not None:
            # Compare native effects, not the presentation sanitization (box_status/null).
            # Raw readings are retained evidence; only result.box is a layout candidate.
            p.verified_observation = deepcopy(after)
        return result, {
            "level": "selected_postconditions_verified",
            "status": "passed" if coherent else "incomplete",
            "checks": [
                {
                    "check": "dimension_where_asked",
                    "passed": _close(row.get("at"), at) if row else None,
                    "at": row.get("at") if row else None,
                },
                {
                    "check": "value_untouched",
                    "passed": row.get("value") == target.get("value") if row else None,
                    "value": row.get("value") if row else None,
                },
                {
                    "check": "dimension_envelope_consistent",
                    "passed": True if coherent else None,
                    "reason": "two matching anchor-relative observations; legacy aggregate "
                    "completeness and cross-time stability remain unverified"
                    if coherent
                    else "envelope not established; retain moved anchor and inspect without replay",
                },
            ],
            "observations": [
                {"observation": "other_dimensions_moved", "names": moved_too},
                {
                    "observation": "dimension_envelope_readings",
                    "readings": readings,
                    "calls": len(readings),
                    "elapsed_seconds": time.monotonic() - started,
                    "error_code": error,
                    "limit": "at most 6 reads, 12 seconds within invocation deadline",
                },
                {"observation": "layout_feedback", **drawing_warnings.feedback(last or {})},
            ],
            "not_checked": list(drawing_warnings.EXCLUSIONS),
        }

    p = engine.Plan(
        op="drawing.move-dimension",
        request={"model": name, "dimension": f"{target['name']}@{target['model']}", "at": at},
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing move-dimension",
            "model": name,
            "dimension": target,
            "to": at,
            "annotation_feedback": placement_feedback,
            "layout_feedback": placement_feedback["layout_feedback"],
            "effect": "the dimension's text moves on this drawing; its value and the model are "
            "not touched",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("dimensions"),
        before=rows,
        arguments={k: opts.get(k) for k in ("model", "dimension", "x", "y")},
    )
    return p


def move_dimension(opts: dict) -> dict:
    return engine.write("drawing move-dimension", opts, _prepare_move, _plan_move)


# ------------------------------------------------------------------ add-dimension


def _prepare_dimension(opts: dict) -> dict:
    for key in ("from", "to"):
        validate(opts[key], EDGE_REF, key)
    if opts["from"] == opts["to"]:
        raise Error("E_VALIDATION", "a dimension is between two different edges", {"path": "to"})
    return {"name": _drawing(opts), "at": _place(opts)}


def _parallel_distance(a: dict, b: dict) -> float | None:
    """The distance between two straight edges that run parallel, else None."""
    try:
        d = [float(v) for v in a["direction"]]
        e = [float(v) for v in b["direction"]]
        p, q = [float(v) for v in a["start"]], [float(v) for v in b["start"]]
    except (KeyError, TypeError, ValueError):
        return None
    cross = [d[1] * e[2] - d[2] * e[1], d[2] * e[0] - d[0] * e[2], d[0] * e[1] - d[1] * e[0]]
    if math.hypot(*cross) > 1e-6:
        return None
    w = [q[i] - p[i] for i in range(3)]
    c = [w[1] * d[2] - w[2] * d[1], w[2] * d[0] - w[0] * d[2], w[0] * d[1] - w[1] * d[0]]
    return round(math.hypot(*c) / math.hypot(*d), 9)


def _plan_dimension(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, at = pre["name"], pre["at"]
    before = _reading(client, name)
    views = before.get("views") or []
    view = next((v for v in views if v.get("name") == opts["view"]), None)
    if view is None:
        raise Error(
            "E_NOT_FOUND",
            "the drawing has no view of that name",
            {
                "view": opts["view"],
                "views": [v.get("name") for v in views],
                "_untrusted": ["views"],
            },
        )
    part = str(view.get("model") or "").lower()
    if not part.endswith(".prt"):
        raise Error(
            "E_UNSUPPORTED",
            "a reference dimension is measured between a part's edges; this view shows "
            + (part or "no model"),
            {"view": opts["view"], "model": part or None, "_untrusted": ["model"]},
        )
    edges = engine.normalize(client.op("geometry.list", {"model": part, "kind": "edge"}))
    by_ref = {e.get("ref"): e for e in edges.get("items") or []}
    ends = []
    for key in ("from", "to"):
        edge = by_ref.get(opts[key])
        if edge is None:
            raise Error(
                "E_NOT_FOUND",
                "the part has no edge of that id",
                {
                    "edge": opts[key],
                    "fix": f"creo-cli geometry list --model {part} --kind edge",
                    "_untrusted": ["fix"],
                },
            )
        sense = opts.get(key + "_sense") or "auto"
        if edge.get("type") != "line" and not (
            edge.get("type") in ("circle", "arc") and sense == "center"
        ):
            raise Error(
                "E_VALIDATION",
                "use a straight edge, or a circular/arc edge with explicit center sense",
                {"path": key, "edge": opts[key], "type": edge.get("type"), "_untrusted": ["type"]},
            )
        ends.append(edge)
    on_sheet(before, at[0], at[1], "dimension")
    rows = before.get("dimensions") or []
    apart = _parallel_distance(*ends)
    orientation = opts.get("orientation") or "slanted"
    expected_attachments = [
        {"ref": opts[key], "model": part, "sense": opts.get(key + "_sense") or "auto"}
        for key in ("from", "to")
    ]

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("dimensions") or []
        new = [
            a
            for a in after
            if not any(
                str(a.get("id")) == str(b.get("id")) and a.get("model") == b.get("model")
                for b in rows
            )
        ]
        made = new[0] if len(new) == 1 else {}
        attachments = made.get("attachments")
        observed_attachments = (
            [
                {
                    "ref": item.get("ref"),
                    "model": str(item.get("model") or "").lower(),
                    "sense": item.get("sense"),
                }
                for item in attachments
            ]
            if isinstance(attachments, list) and all(isinstance(a, dict) for a in attachments)
            else None
        )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("one_dimension_added", len(new) == 1),
                engine.check("a_reference_dimension", made.get("reference") is True),
                engine.check(
                    "associative_geometry_attachments",
                    made.get("associative") is True
                    and observed_attachments == expected_attachments,
                    expected=expected_attachments,
                    observed=observed_attachments,
                ),
                engine.check(
                    "in_the_named_view", made.get("view") == opts["view"], view=made.get("view")
                ),
            ],
            "observations": [
                {
                    "observation": "measured",
                    "value": made.get("value"),
                    "parallel_edges_apart": apart,
                    "at": made.get("at"),
                }
            ],
            "not_checked": ["overlap_with_views_or_other_dimensions"],
        }

    return engine.Plan(
        op="drawing.add-dimension",
        request={
            "model": name,
            "view": opts["view"],
            "from": opts["from"],
            "to": opts["to"],
            "orientation": orientation,
            "at": at,
            **{
                key + "_sense": opts[key + "_sense"]
                for key in ("from", "to")
                if opts.get(key + "_sense")
            },
        },
        target=name,
        binding={"drawing": before, "edges": ends},
        preview={
            "command": "drawing add-dimension",
            "model": name,
            "view": opts["view"],
            "between": [{k: e.get(k) for k in ("ref", "start", "end", "direction")} for e in ends],
            "orientation": orientation,
            "at": at,
            "parallel_edges_apart": apart,
            "expected_attachments": expected_attachments,
            "effect": "a reference dimension on this drawing: Creo measures it between the two "
            "edges as the view shows them; it drives nothing",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("dimensions"),
        before=rows,
        arguments={
            k: opts.get(k)
            for k in (
                "model",
                "view",
                "from",
                "to",
                "from_sense",
                "to_sense",
                "orientation",
                "x",
                "y",
            )
        },
    )


def add_dimension(opts: dict) -> dict:
    return engine.write("drawing add-dimension", opts, _prepare_dimension, _plan_dimension)


# ------------------------------------------------------------------ add-table

CELL = {"type": ["string", "null"], "maxLength": CELL_LIMIT}
TABLE_SCHEMA = strict(
    {
        "units": text(enum=("mm", "cm", "m", "in", "ft")),
        "at": {"type": "array", "items": NUM, "minItems": 2, "maxItems": 2},
        "columns": {"type": "array", "items": POS, "minItems": 1, "maxItems": 50},
        "rows": {"type": "array", "items": POS, "minItems": 1, "maxItems": 200},
        "cells": {
            "type": "array",
            "items": {"type": "array", "items": CELL, "maxItems": 50},
            "maxItems": 200,
        },
        "merge": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 200},
                "minItems": 4,
                "maxItems": 4,
            },
            "maxItems": 100,
        },
    },
    ("units", "at", "columns", "rows"),
)
TABLE_EXAMPLE = {
    "units": "mm",
    "at": [240, 50],
    "columns": [30, 60, 30],
    "rows": [8, 8],
    "cells": [["名称", "A5 线圈笔记本", "1:2"], ["材料", "纸、钢丝", "80 张"]],
    "merge": [],
}


def validate_table(q: dict) -> dict:
    validate(q, TABLE_SCHEMA)
    rows, columns = len(q["rows"]), len(q["columns"])
    cells = q.get("cells") or []
    if len(cells) > rows or any(len(r) > columns for r in cells):
        raise Error(
            "E_VALIDATION",
            "cells has more rows or columns than the table",
            {"path": "request.cells", "rows": rows, "columns": columns},
        )
    for r, line in enumerate(cells):
        for c, value in enumerate(line):
            if value is not None:
                _plain(value, f"request.cells[{r}][{c}]", CELL_LIMIT, 10)
    taken: set = set()
    for i, (r1, c1, r2, c2) in enumerate(q.get("merge") or []):
        where = f"request.merge[{i}]"
        if not (r1 <= r2 <= rows and c1 <= c2 <= columns) or (r1, c1) == (r2, c2):
            raise Error(
                "E_VALIDATION",
                "a merge is [first row, first column, last row, last column] spanning two or "
                "more cells of the table, counted from 1",
                {"path": where},
            )
        region = {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
        if region & taken:
            raise Error("E_VALIDATION", "merged regions overlap", {"path": where})
        taken |= region
        for r, c in region - {(r1, c1)}:
            if r <= len(cells) and c <= len(cells[r - 1]) and cells[r - 1][c - 1]:
                raise Error(
                    "E_VALIDATION",
                    "a merged region's text goes in its first cell",
                    {"path": f"request.cells[{r - 1}][{c - 1}]"},
                )
    return q


def _prepare_table(opts: dict) -> dict:
    return {"name": _drawing(opts), "request": validate_table(read_request(opts["request"]))}


def _table_sheet(drawing):
    sheets = drawing.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise Error(
            "E_VERIFY_INCOMPLETE", "table operation needs actual sheet dimensions and units"
        )
    if len(sheets) != 1:
        raise Error(
            "E_UNSUPPORTED",
            "table creation/movement supports only single-sheet drawings",
            {
                "sheet_count": len(sheets),
                "reason": "current-sheet execution cannot be bound across sheets",
            },
        )
    sheet = sheets[0]
    if (
        sheet.get("number") != 1
        or sheet.get("error")
        or any(
            not isinstance(sheet.get(k), (int, float))
            or isinstance(sheet[k], bool)
            or not math.isfinite(sheet[k])
            or sheet[k] <= 0
            for k in ("width", "height")
        )
        or not sheet.get("units")
    ):
        raise Error("E_VERIFY_INCOMPLETE", "table sheet dimensions/units were not reliably read")
    return sheet


def _table_move_region(drawing, table, at):
    sheet = _table_sheet(drawing)
    outline, origin = table.get("outline"), table.get("at")

    def point(v):
        return (
            isinstance(v, list)
            and len(v) == 2
            and all(
                isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
                for n in v
            )
        )

    if table.get("sheet") != sheet["number"] or table.get("segments") != 1:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "table bounds need an identified single segment on the target sheet",
        )
    if (
        not point(origin)
        or not isinstance(outline, list)
        or len(outline) != 2
        or not all(point(p) for p in outline)
        or any(outline[1][i] <= outline[0][i] for i in (0, 1))
        or not table.get("bounds_source")
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "actual table outline/origin unavailable; no zero-size assumption",
        )
    delta = [at[i] - origin[i] for i in (0, 1)]
    planned = [[corner[i] + delta[i] for i in (0, 1)] for corner in outline]
    result = {
        "sheet": sheet["number"],
        "units": sheet["units"],
        "sheet_bounds": [[0, 0], [sheet["width"], sheet["height"]]],
        "outline_before": outline,
        "outline_after": planned,
        "requested_anchor": at,
        "table": str(table["id"]),
        "bounds_source": table["bounds_source"],
    }
    outside = [
        name
        for name, bad in (
            ("left", planned[0][0] < 0),
            ("bottom", planned[0][1] < 0),
            ("right", planned[1][0] > sheet["width"]),
            ("top", planned[1][1] > sheet["height"]),
        )
        if bad
    ]
    if outside:
        raise Error(
            "E_VALIDATION",
            "the translated table outline crosses the sheet boundary",
            result | {"outside_edges": outside},
        )
    return result


def _plan_table(
    client: Client,
    opts: dict,
    pre: dict,
    command: str = "drawing add-table",
    preview_extra: dict | None = None,
) -> engine.Plan:
    name, q = pre["name"], pre["request"]
    before = _reading(client, name)
    sheet = _table_sheet(before)
    units = str(sheet.get("units") or "")
    if SHEET_UNITS.get(units, units) != q["units"]:
        raise Error(
            "E_VALIDATION",
            "the request's units are not the sheet's; lengths are never converted",
            {"path": "request.units", "sheet": units or None, "_untrusted": ["sheet"]},
        )
    x, y = q["at"]
    on_sheet(before, x, y, "table")
    width, height = sum(q["columns"]), sum(q["rows"])
    on_sheet(before, x + width, y - height, "table's far corner")
    tables = before.get("tables") or []
    narrow = cells_too_narrow(q)
    wanted = [
        [(v if v else None) for v in (line + [None] * (len(q["columns"]) - len(line)))]
        for line in (q.get("cells") or [])
    ]

    def verify(c: Client, data: dict):
        drawing = engine.show(c, name)
        after = drawing.get("tables") or []
        new = [t for t in after if str(t.get("id")) not in {str(o.get("id")) for o in tables}]
        made = new[0] if len(new) == 1 else {}
        read = made.get("cells") or []
        wrong = [
            [r, col]
            for r, line in enumerate(wanted)
            for col, value in enumerate(line)
            if value is not None
            and not (r < len(read) and col < len(read[r]) and read[r][col] == value)
        ]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("one_table_added", len(new) == 1),
                engine.check(
                    "size_as_asked",
                    made.get("rows") == len(q["rows"]) and made.get("columns") == len(q["columns"]),
                    rows=made.get("rows"),
                    columns=made.get("columns"),
                ),
                engine.check("cells_say_what_was_asked", bool(made) and not wrong, wrong=wrong),
            ]
            + (
                [
                    engine.check(
                        "projection_symbol_drawn",
                        drawing.get("projection") in ("first_angle", "third_angle")
                        and (data.get("projection_symbol") or {}).get("projection")
                        == drawing.get("projection")
                        and isinstance(drawing.get("draft_entities"), int)
                        and isinstance(before.get("draft_entities"), int)
                        and drawing["draft_entities"] - before["draft_entities"] == 6,
                        projection=drawing.get("projection"),
                        lines_added=(drawing.get("draft_entities") or 0)
                        - (before.get("draft_entities") or 0),
                    )
                ]
                if q.get("projection_symbol")
                else []
            ),
            "observations": [
                {"observation": "placed_at", "at": made.get("at")},
                {
                    "observation": "cells_too_narrow",
                    "cells": narrow,
                    "evaluated": q.get("units") == "mm",
                    "scope": "3.5 mm lettering/character-count heuristic; "
                    "not measured cell glyph fit",
                },
                {"observation": "layout_feedback", **drawing_warnings.feedback(drawing)},
            ],
            "not_checked": ["overlap_with_views_or_other_items"],
        }

    request = {"model": name, "at": q["at"], "columns": q["columns"], "rows": q["rows"]}
    if q.get("cells"):
        request["cells"] = q["cells"]
    if q.get("merge"):
        request["merge"] = q["merge"]
    if q.get("projection_symbol"):
        request["projection_symbol"] = q["projection_symbol"]
    return engine.Plan(
        op="drawing.add-table",
        request=request,
        target=name,
        binding={"drawing": before},
        preview={
            "command": command,
            "model": name,
            "at": q["at"],
            "size": [round(width, 9), round(height, 9)],
            "rows": len(q["rows"]),
            "columns": len(q["columns"]),
            "cells": q.get("cells") or [],
            "merge": q.get("merge") or [],
            "cells_too_narrow": narrow,
            "cells_too_narrow_evaluated": q.get("units") == "mm",
            "layout_feedback": drawing_warnings.feedback(
                before,
                proposals=[
                    drawing_warnings.proposal(
                        "tables",
                        {
                            "id": "requested_table",
                            "sheet": (before.get("sheets") or [{}])[0].get("number"),
                        },
                        [[x, y - height], [x + width, y]],
                        source="requested table rectangle; not future cell glyph extents",
                    )
                ],
            ),
            "cells_too_narrow_meaning": "text that, at the 3.5 mm lettering of Creo's sheets, is "
            "wider than its column and runs out of its cell: widen the column or merge cells",
            "effect": "a table whose top left corner is at the point; it grows right and down",
        }
        | (preview_extra or {}),
        verify=verify,
        observe=lambda c: engine.show(c, name).get("tables"),
        before=tables,
        arguments={"model": opts["model"], "request": q}
        | ({"language": opts.get("language")} if command != "drawing add-table" else {}),
    )


def add_table(opts: dict) -> dict:
    return engine.write("drawing add-table", opts, _prepare_table, _plan_table)


# ------------------------------------------------------------------ add-title-block

TITLE_FIELDS = (
    "title",
    "number",
    "material",
    "scale",
    "quantity",
    "date",
    "drawn_by",
    "checked_by",
)
TITLE_SCHEMA = strict({f: {"type": ["string", "null"], "maxLength": 60} for f in TITLE_FIELDS}, ())
TITLE_EXAMPLE = {
    "title": "SYNTHETIC ASSEMBLY REV A",
    "number": "TEST-001",
    "material": "",
    "drawn_by": "",
    "checked_by": "",
}
# Four rows of the fields a shop reads first, 180 mm across -- ISO 7200's width -- in the
# sheet's bottom right corner, 5 mm in.
TITLE_LABELS = {
    "en": ("Title", "Scale", "Material", "Quantity", "Number", "Date", "Drawn", "Checked"),
    "zh": ("名称", "比例", "材料", "数量", "图号", "日期", "制图", "审核"),
}
TITLE_COLUMNS = {"en": [28, 62, 28, 62], "zh": [20, 70, 20, 70]}
TITLE_ROW = 8
TITLE_MARGIN = 5
# The projection symbol: 5.6 mm high (ISO 5456-2 for 3.5 mm lettering is 7; the row is 8),
# centred 11 mm in from the title block's right edge.
SYMBOL_HEIGHT = 5.6
SYMBOL_INSET = 11
# What Creo reports for a part given no material.
UNSET_MATERIAL = "PTC_SYSTEM_MTRL_PROPS"


def _scale_label(scale: float) -> str:
    """2 as 2:1, 0.5 as 1:2."""
    if scale >= 1:
        return f"{round(scale) if math.isclose(scale, round(scale)) else scale:g}:1"
    inverse = 1 / scale
    return (
        f"1:{round(inverse) if math.isclose(inverse, round(inverse), rel_tol=1e-6) else inverse:g}"
    )


def validate_title(q: dict) -> dict:
    validate(q, TITLE_SCHEMA)
    for key, value in q.items():
        if value is not None:
            _plain(value, f"request.{key}", 60)
    return q


def _prepare_title(opts: dict) -> dict:
    source = None
    if opts.get("request") and opts["request"] != "-":
        from ..workflow_state import request_file

        try:
            source = request_file(opts["request"])
        except OSError as exc:
            code = (
                "E_CONFLICT"
                if opts.get("confirm")
                else ("E_NOT_FOUND" if isinstance(exc, FileNotFoundError) else "E_IO")
            )
            raise Error(
                code, "title request file cannot be independently read", {"path": opts["request"]}
            ) from exc
        fields = validate_title(source["content"])
    else:
        fields = validate_title(read_request(opts["request"])) if opts.get("request") else {}
    return {
        "name": _drawing(opts),
        "fields": fields,
        "language": opts.get("language") or "en",
        "source": source,
    }


def _plan_title(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, fields, language = pre["name"], pre["fields"], pre["language"]
    before = _reading(client, name)
    if before.get("projection") not in ("first_angle", "third_angle"):
        raise Error(
            "E_CONFLICT",
            "the drawing's projection is unavailable; no title block was requested",
            {
                "projection": before.get("projection"),
                "next_action": "read the drawing's projection options and update the loaded "
                "service if it cannot report them; protect open models before a separately "
                "authorized reload, then preview again",
                "automatic_retry": False,
                "_untrusted": ["projection"],
            },
        )
    if not isinstance(before.get("draft_arcs"), list):
        raise Error("E_VERIFY_INCOMPLETE", "independent draft arc geometry is unavailable")
    old_arc_ids = {str(arc["id"]) for arc in before["draft_arcs"]}
    sheet = _table_sheet(before)
    units = str(sheet.get("units") or "")
    if SHEET_UNITS.get(units, units) != "mm" or not isinstance(sheet.get("width"), int | float):
        raise Error(
            "E_VALIDATION",
            "the title block is laid out in millimetres; this sheet is not",
            {
                "sheet": units or None,
                "fix": "add one with drawing add-table",
                "_untrusted": ["sheet"],
            },
        )
    model = next(
        (m for m in before.get("models") or [] if str(m).lower().endswith((".prt", ".asm"))), None
    )
    shown = engine.show(client, str(model).lower()) if model else {}
    base = str(model or name).rsplit(".", 1)[0]
    material = shown.get("material")
    main = next(
        (
            v
            for v in before.get("views") or []
            if v.get("type") == "general" and isinstance(v.get("scale"), int | float)
        ),
        None,
    )
    filled = {
        "title": shown.get("common_name") or base.upper(),
        "number": base.upper(),
        "material": "" if not material or material == UNSET_MATERIAL else material,
        # The main view's scale, as a title block names it -- the first general view's, which
        # may be given its own -- else the sheet's.
        "scale": _scale_label(main["scale"]) if main else sheet.get("scale_label") or "",
        "quantity": "1",
        "date": datetime.date.today().isoformat(),
        "drawn_by": "",
        "checked_by": "",
    } | {k: v for k, v in fields.items() if v is not None}
    labels, columns = TITLE_LABELS[language], TITLE_COLUMNS[language]
    width, height = sum(columns), 4 * TITLE_ROW
    x0, y0 = sheet["width"] - TITLE_MARGIN - width, TITLE_MARGIN
    x1, y1 = x0 + width, y0 + height
    from .. import bom

    title_region = bom.region(before, [[x0, y0], [x1, y1]], "fixed millimetre title block")
    crowded = [
        v.get("name")
        for v in before.get("views") or []
        if v.get("outline")
        and v["outline"][0][0] < x1
        and x0 < v["outline"][1][0]
        and v["outline"][0][1] < y1
        and y0 < v["outline"][1][1]
    ]
    if crowded:
        raise Error(
            "E_CONFLICT",
            "views lie where the title block goes, the sheet's bottom right corner",
            {
                "views": crowded,
                "corner": [[x0, y0], [x1, y1]],
                "fix": "drawing move-view the views clear of the corner, then add the title block",
                "_untrusted": ["views"],
            },
        )
    there = [
        t.get("id")
        for t in before.get("tables") or []
        if isinstance(t.get("at"), list)
        and x0 <= t["at"][0] <= x1
        and y0 <= t["at"][1] <= y1 + TITLE_ROW
    ]
    if there:
        raise Error(
            "E_CONFLICT",
            "a table already lies in the sheet's bottom right corner -- a title block?",
            {"tables": there, "fix": "drawing remove --item table:<id> to replace it"},
        )
    cells = [
        [labels[0], filled["title"], labels[1], filled["scale"]],
        [labels[2], filled["material"], labels[3], filled["quantity"]],
        [labels[4], filled["number"], labels[5], filled["date"]],
        [labels[6], filled["drawn_by"], labels[7], filled["checked_by"]],
    ]
    q = {
        "units": "mm",
        "at": [x0, y1],
        "columns": columns,
        "rows": [TITLE_ROW] * 4,
        "cells": [[c or None for c in row] for row in cells],
        # The drawing's projection, as ISO 5456-2 draws it, at the right of the scale's cell.
        "projection_symbol": {
            "at": [x1 - SYMBOL_INSET, y1 - TITLE_ROW / 2],
            "height": SYMBOL_HEIGHT,
        },
    }
    plan = _plan_table(
        client,
        opts,
        {"name": name, "request": q},
        command="drawing title-block apply",
        preview_extra={
            "layout_feedback": title_region["layout_feedback"],
            "filled": filled,
            "projection_symbol": q["projection_symbol"]
            | {"projection": before.get("projection"), "entities": 6},
            "filled_meaning": "from the model: its common name (else its name) as the title, "
            "its name as the number, its material, the sheet's scale and today's date; a "
            "request overrides any of them, and drawn_by and checked_by are left for people",
        },
    )
    verify_table = plan.verify

    def verify_title(c, data):
        data, verification = verify_table(c, data)
        native = engine.show(c, name)
        actual = next(
            (
                t
                for t in native.get("tables") or []
                if str(t.get("id")) == str((data.get("table") or {}).get("id"))
            ),
            {},
        )
        box, expected = actual.get("outline"), [[x0, y0], [x1, y1]]
        fits = bool(box) and all(
            math.isclose(box[i][j], expected[i][j], abs_tol=1e-6) for i in (0, 1) for j in (0, 1)
        )
        verification["checks"].append(
            engine.check(
                "title_full_extent_as_planned",
                fits and actual.get("sheet") == 1 and actual.get("segments") == 1,
                expected=expected,
                observed=box,
            )
        )
        arcs = native.get("draft_arcs")
        if not isinstance(arcs, list):
            raise Error("E_VERIFY_INCOMPLETE", "created projection arc geometry cannot be read")
        created = [arc for arc in arcs if str(arc["id"]) not in old_arc_ids]
        radii = sorted(arc.get("radius", -1) for arc in created)
        complete = (
            len(created) == 2
            and all(
                math.isclose(arc["end_angle"] - arc["start_angle"], 2 * math.pi, abs_tol=1e-8)
                and arc.get("sheet") == 1
                for arc in created
            )
            and all(
                math.isclose(r, expected, abs_tol=1e-6)
                for r, expected in zip(radii, [SYMBOL_HEIGHT / 4, SYMBOL_HEIGHT / 2], strict=False)
            )
        )
        verification["checks"].append(
            engine.check("two_complete_projection_circles", complete, arcs=created)
        )
        read = actual.get("cells") or []
        blank = [(1, 1, "material"), (3, 1, "drawn_by"), (3, 3, "checked_by")]
        verification["checks"].append(
            engine.check(
                "unknown_metadata_remains_blank",
                all(
                    filled[key]
                    or (
                        len(read) > row
                        and len(read[row]) > col
                        and not str(read[row][col] or "").strip()
                    )
                    for row, col, key in blank
                ),
            )
        )
        return data, verification

    plan.verify = verify_title
    plan.binding["title_request_source"] = pre["source"]
    plan.preview["region"] = {"outline": [[x0, y0], [x1, y1]], "sheet": 1, "units": "mm"}
    return plan


def add_title_block(opts: dict) -> dict:
    return engine.write("drawing add-title-block", opts, _prepare_title, _plan_title)


# ------------------------------------------------------------------ add-symbol


def _symbol(raw: str) -> str:
    """A library name, surffins/generic/standard; or a .sym file inside the workspace."""
    if raw.lower().endswith(".sym") or "\\" in raw or ":" in raw or raw.startswith("/"):
        file = paths.contained(raw, directory=False)
        if file.suffix.lower() != ".sym":
            raise Error("E_VALIDATION", "a symbol file is a *.sym file", {"path": "symbol"})
        return str(file)
    validate(raw, LIBRARY_SYMBOL, "symbol")
    return raw


def _values(raw: str | None) -> dict:
    out: dict = {}
    if raw is None:
        return out
    for pair in str(raw).split(","):
        variable, sep, value = pair.partition("=")
        variable, value = variable.strip(), value.strip()
        if not sep:
            raise Error("E_VALIDATION", "a value is name=value", {"path": "value"})
        validate(variable, VARIABLE, "value")
        if variable in out:
            raise Error("E_VALIDATION", "a variable is given twice", {"path": "value"})
        out[variable] = _plain(value, "value", VALUE_LIMIT)
    return out


def _prepare_symbol(opts: dict) -> dict:
    return {
        "name": _drawing(opts),
        "symbol": _symbol(opts["symbol"]),
        "values": _values(opts.get("value")),
        "at": _place(opts),
    }


def _plan_symbol(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, symbol, values, at = pre["name"], pre["symbol"], pre["values"], pre["at"]
    before = _reading(client, name)
    on_sheet(before, at[0], at[1], "symbol")
    found = engine.normalize(client.op("drawing.symbol", {"symbol": symbol}))
    definition = found.get("symbol")
    if not definition:
        raise Error(
            "E_NOT_FOUND",
            "no symbol definition of that name",
            {
                "symbol": symbol,
                "library": found.get("library") or [],
                "fix": "name one from library, as its path there without .sym, or a .sym file "
                "inside the workspace",
                "_untrusted": ["symbol", "library"],
            },
        )
    takes = list(definition.get("variables") or [])
    unknown = sorted(set(values) - set(takes))
    if unknown:
        raise Error(
            "E_VALIDATION",
            "the symbol takes no variable of that name",
            {"path": "value", "unknown": unknown, "takes": takes, "_untrusted": ["takes"]},
        )
    symbols = before.get("symbols") or []

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("symbols") or []
        new = [t for t in after if str(t.get("id")) not in {str(o.get("id")) for o in symbols}]
        made = new[0] if len(new) == 1 else {}
        read = made.get("values") or {}
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("one_symbol_added", len(new) == 1),
                engine.check("symbol_where_asked", _close(made.get("at"), at), at=made.get("at")),
                engine.check(
                    "values_as_asked",
                    bool(made) and all(_same_value(v, read.get(k)) for k, v in values.items()),
                    values=read,
                ),
            ],
            "observations": [{"observation": "definition", "definition": made.get("definition")}],
            "not_checked": ["overlap_with_views_or_other_items"],
        }

    request = {"model": name, "symbol": symbol, "at": at}
    if values:
        request["values"] = values
    return engine.Plan(
        op="drawing.add-symbol",
        request=request,
        target=name,
        binding={"drawing": before, "definition": definition},
        preview={
            "command": "drawing add-symbol",
            "model": name,
            "symbol": symbol,
            "definition": definition.get("path"),
            "variables": takes,
            "values": values,
            "at": at,
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("symbols"),
        before=symbols,
        arguments={k: opts.get(k) for k in ("model", "symbol", "value", "x", "y")},
    )


def add_symbol(opts: dict) -> dict:
    return engine.write("drawing add-symbol", opts, _prepare_symbol, _plan_symbol)


# ------------------------------------------------------------ add-bom, add-balloons, move-table

TABLE_LIBRARY = text(pattern=r"^[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64}){0,5}$", maximum=400)
DEFAULT_BOM = "Assembly/bom_description_down"


def _assembly(client: Client, before: dict) -> str:
    """The assembly a drawing shows, whose components a parts list lists."""
    shown = [str(m).lower() for m in before.get("models") or [] if str(m).lower().endswith(".asm")]
    if not shown:
        raise Error(
            "E_CONFLICT",
            "a parts list is of an assembly; the drawing shows none",
            {"models": before.get("models"), "_untrusted": ["models"]},
        )
    if len(before.get("models") or []) != 1:
        raise Error("E_UNSUPPORTED", "BOM delivery supports exactly one assembly drawing model")
    return shown[0]


def _prepare_bom(opts: dict) -> dict:
    table = opts.get("table") or DEFAULT_BOM
    if table.lower().endswith(".tbl") or "\\" in table or ":" in table:
        file = paths.contained(table, directory=False)
        if file.suffix.lower() != ".tbl":
            raise Error("E_VALIDATION", "a table file is a *.tbl file", {"path": "table"})
        table = str(file)
    else:
        validate(table, TABLE_LIBRARY, "table")
    return {"name": _drawing(opts), "table": table, "at": _place(opts)}


def _annotation_drawing(reading: dict, name: str, assembly: str | None = None) -> dict:
    """Bind an actual BOM/balloon reading to its requested drawing and association."""
    expected = {"model": name}
    if assembly is not None:
        expected["models"] = [assembly]
    observed = {key: reading.get(key) for key in expected} if isinstance(reading, dict) else None
    if observed != expected:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "BOM/balloon drawing identity or assembly association was not independently read",
            {"expected": expected, "observed": observed, "_untrusted": ["observed"]},
        )
    # These are required native inventories, not optional empty collections. Apply
    # the same admission to planning and the first independent post-write reading.
    # Optional attributes inside a real row retain their existing incomplete state.
    for resource in ("tables", "notes", "views"):
        rows = reading.get(resource)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("id"), (str, int))
            or isinstance(row.get("id"), bool)
            or str(row["id"]) == ""
            for row in rows
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "required BOM/balloon native inventory was not completely read",
                {"model": name, "resource": resource},
            )
        identities = [str(row["id"]) for row in rows]
        if len(set(identities)) != len(identities):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "required BOM/balloon native inventory has ambiguous identities",
                {"model": name, "resource": resource},
            )
    return reading


def _annotation_components(client: Client, assembly: str) -> list:
    reading = engine.show(client, assembly)
    if not isinstance(reading, dict) or reading.get("model") != assembly:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "BOM/balloon assembly identity was not independently read",
            {
                "expected": assembly,
                "observed": reading.get("model") if isinstance(reading, dict) else None,
                "_untrusted": ["observed"],
            },
        )
    return reading.get("components") or []


def _plan_bom(client: Client, opts: dict, pre: dict) -> engine.Plan:
    from .. import bom

    name, requested, at = pre["name"], pre["table"], pre["at"]
    before = _annotation_drawing(_reading(client, name), name)
    sheet = _table_sheet(before)
    assembly = _assembly(client, before)
    _annotation_drawing(before, name, assembly)
    components = _annotation_components(client, assembly)
    counts = bom.counts(components)
    expected_source = None
    if opts.get("confirm"):
        from .. import operations, safety

        prior = operations.get(safety.token_operation(opts["confirm"]))
        expected_source = prior["driver_plan"]["extensions"]["creo"]["template"]
    source, profile = bom.template(client, requested, expected_source)
    if SHEET_UNITS.get(sheet["units"], sheet["units"]) != profile["units"]:
        raise Error("E_UNSUPPORTED", "qualified BOM template requires a millimetre sheet")
    width = profile["width"]
    height = profile["header_height"] + profile["row_height"] * len(counts)
    outline = [[at[0], at[1] - height], [at[0] + width, at[1]]]
    area = bom.region(before, outline, "native BOM repeat-region table")
    tables = before.get("tables") or []

    def verify(c: Client, data: dict):
        after = _annotation_drawing(engine.show(c, name), name, assembly)
        new = [
            t
            for t in after.get("tables", [])
            if str(t.get("id")) not in {str(o.get("id")) for o in tables}
        ]
        made = new[0] if len(new) == 1 else {}
        rows, error = [], None
        actual_components = _annotation_components(c, assembly)
        try:
            rows = bom.records(made, assembly, actual_components)
        except Error as exc:
            error = {"code": exc.code, "message": exc.message, "details": exc.details}
        actual = made.get("outline")
        fits = (
            bool(actual)
            and actual[0][0] >= -1e-6
            and actual[0][1] >= -1e-6
            and actual[1][0] <= sheet["width"] + 1e-6
            and actual[1][1] <= sheet["height"] + 1e-6
            and all(
                math.isclose(actual[i][j], outline[i][j], abs_tol=0.05)
                for i in (0, 1)
                for j in (0, 1)
            )
        )
        if error is None and isinstance(after.get("tables"), list):
            p.verified_observation = deepcopy(after["tables"])
        return data | {"bom_records": rows}, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("one_table_added", len(new) == 1),
                engine.check(
                    "native_repeat_region_records_match_inventory", error is None, error=error
                ),
                engine.check(
                    "qualified_extent_and_page",
                    fits and made.get("sheet") == 1 and made.get("segments") == 1,
                    expected=outline,
                    observed=actual,
                ),
            ],
            "observations": [
                {
                    "observation": "fits_on_the_sheet",
                    "fits": fits,
                    "at": made.get("at"),
                    "size": made.get("size"),
                },
                {"observation": "layout_feedback", **drawing_warnings.feedback(after)},
            ],
            "not_checked": [
                "balloon_correspondence_before_separate_balloon_operation",
                "all_annotation_overlap",
            ],
        }

    p = engine.Plan(
        op="drawing.add-bom",
        request={
            "model": name,
            "table": source["path"],
            "at": at,
            "template_sha256": source["sha256"],
        },
        target=name,
        binding={
            "drawing": before,
            "components": components,
            "template": source,
            "profile": profile,
        },
        preview={
            "command": "drawing bom add",
            "model": name,
            "assembly": assembly,
            "table": requested,
            "template": source,
            "profile": profile,
            "region": area,
            "layout_feedback": area["layout_feedback"],
            "at": at,
            "lists": [{"model": m, "quantity": n} for m, n in sorted(counts.items())],
            "effect": "retrieve the qualified native repeat-region template "
            "and update from this assembly",
        },
        verify=verify,
        observe=lambda c: _annotation_drawing(engine.show(c, name), name, assembly).get("tables"),
        before=tables,
        arguments={k: opts.get(k) for k in ("model", "table", "x", "y")},
    )
    return p


def add_bom(opts: dict) -> dict:
    return engine.write("drawing add-bom", opts, _prepare_bom, _plan_bom)


def _prepare_balloons(opts: dict) -> dict:
    validate(opts["table"], text(pattern=r"^[0-9]{1,9}$", maximum=9), "table")
    return {"name": _drawing(opts)}


def _plan_balloons(client: Client, opts: dict, pre: dict) -> engine.Plan:
    from .. import bom

    client.require_capability("bom_reference_readback", 2)
    name = pre["name"]
    before = _annotation_drawing(_reading(client, name), name)
    sheet = _table_sheet(before)
    if SHEET_UNITS.get(sheet["units"], sheet["units"]) != "mm":
        raise Error("E_UNSUPPORTED", "qualified balloon layout requires millimetres")
    assembly = _assembly(client, before)
    _annotation_drawing(before, name, assembly)
    components = _annotation_components(client, assembly)
    table = next((t for t in before.get("tables", []) if str(t.get("id")) == opts["table"]), None)
    if table is None:
        raise Error("E_NOT_FOUND", "the drawing has no table of that id", {"table": opts["table"]})
    if table.get("sheet") != 1 or table.get("segments") != 1:
        raise Error("E_UNSUPPORTED", "balloons require one table segment on the single sheet")
    if (table.get("cells") or [[]])[0] != [
        "ITEM\nNO",
        "PART NUMBER",
        "QTY",
        "DESCRIPTION",
        "NOTES",
    ]:
        raise Error("E_UNSUPPORTED", "balloon table does not have the qualified BOM columns")
    rows = bom.records(table, assembly, components)
    if len(table["cells"]) != len(rows) + 1:
        raise Error("E_VERIFY_INCOMPLETE", "BOM contains additional unverified rows")
    for other in before["tables"]:
        if str(other["id"]) != str(table["id"]):
            if other.get("cell_references") is None:
                raise Error("E_VERIFY_INCOMPLETE", "other table repeat-region inventory is unknown")
            if other["cell_references"]:
                raise Error(
                    "E_UNSUPPORTED",
                    "balloon verification supports one native BOM table per drawing",
                )
    matches = [v for v in before.get("views", []) if v.get("name") == opts.get("view")]
    if len(matches) != 1:
        raise Error(
            "E_NOT_FOUND",
            "an explicit unique existing view is required",
            {"view": opts.get("view")},
        )
    view = matches[0]
    if view.get("sheet") != 1 or str(view.get("model", "")).lower() != assembly:
        raise Error("E_VERIFY_INCOMPLETE", "balloon view must reference this assembly on sheet 1")
    if not view.get("outline"):
        raise Error("E_VERIFY_INCOMPLETE", "balloon view outline is unavailable")
    # The qualified template's native offset is 20.32 mm; reserve 30 mm, including glyphs.
    box = view["outline"]
    outline = [[box[0][0] - 30, box[0][1] - 30], [box[1][0] + 30, box[1][1] + 30]]
    area = bom.region(
        before | {"views": [v for v in before["views"] if v is not view]},
        outline,
        "balloon view reserve",
    )
    notes = bom.note_inventory(before)
    selected = bom.view_balloons(notes, view["name"])
    other_views = {leader.get("view") for note in notes for leader in note.get("leaders") or []}
    for other_view in other_views - {view["name"], None}:
        for note in bom.view_balloons(notes, other_view):
            try:
                associated = bom.balloons([note], rows, assembly, other_view, require_all=False)
            except Error as exc:
                if exc.code == "E_VERIFY_INCOMPLETE":
                    raise
                continue  # An unrelated numeric annotation, preserved but not used as coverage.
            if associated:
                raise Error(
                    "E_UNSUPPORTED",
                    "existing BOM balloons in another view require a native per-component "
                    "conversion; this profile preserves per-record quantities",
                    {"table": str(table["id"]), "view": view["name"], "existing_view": other_view},
                )
    existing_matches = bom.balloons(selected, rows, assembly, view["name"], require_all=False)
    if {m["item"] for m in existing_matches} == {r["item"] for r in rows}:
        raise Error(
            "E_CONFLICT",
            "all BOM records already have balloons in the selected view",
            {"table": str(table["id"]), "view": view["name"], "dispatch_state": "not_started"},
        )
    selected_ids = {str(n["id"]) for n in selected}
    unrelated = {str(n["id"]): n for n in notes if str(n["id"]) not in selected_ids}

    def verify(c: Client, data: dict):
        after = _annotation_drawing(engine.show(c, name), name, assembly)
        after_notes = bom.note_inventory(after)
        added = [n for n in after_notes if str(n["id"]) not in {str(o["id"]) for o in notes}]
        retained_selected = [n for n in after_notes if str(n["id"]) in selected_ids]
        matches, new_matches, error = [], [], None
        try:
            actual_table = next(
                t for t in after.get("tables", []) if str(t["id"]) == str(table["id"])
            )
            actual_rows = bom.records(actual_table, assembly, _annotation_components(c, assembly))
            # Every new note must qualify itself; existing coverage cannot excuse a bad addition.
            new_matches = bom.balloons(
                added, actual_rows, assembly, view["name"], require_all=False
            )
            matches = bom.balloons(retained_selected + added, actual_rows, assembly, view["name"])
            if actual_rows != rows:
                raise Error("E_VERIFY_FAILED", "BOM records changed during balloon creation")
        except (Error, StopIteration) as exc:
            if isinstance(exc, Error) and exc.code in (
                "E_VERIFY_INCOMPLETE",
                "E_NATIVE_READ_PENDING",
                "E_NATIVE_DIAGNOSTIC",
            ):
                raise
            error = str(exc)
        preserved = {str(n["id"]): n for n in after_notes if str(n["id"]) in unrelated}
        if error is None:
            p.verified_observation = deepcopy(after_notes)
        return data | {
            "correspondence": [m | {"table": str(table["id"])} for m in matches],
            "created_note_ids": [str(n["id"]) for n in added],
        }, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "native_balloon_component_item_quantity_correspondence",
                    error is None and bool(matches),
                    error=error,
                ),
                engine.check(
                    "new_associated_balloons",
                    bool(new_matches)
                    and {str(m["note"]) for m in new_matches} == {str(n["id"]) for n in added},
                ),
                engine.check("unrelated_existing_notes_preserved", preserved == unrelated),
                engine.check(
                    "existing_selected_balloons_retained", len(retained_selected) == len(selected)
                ),
            ],
            "observations": [
                {
                    "observation": "numbers",
                    "numbers": sorted(str(n.get("displayed_text", "")).strip() for n in added),
                }
            ],
            "not_checked": ["leader_crossings_and_glyph_collisions_require_rendered_page_review"],
        }

    p = engine.Plan(
        op="drawing.add-balloons",
        request={"model": name, "table": int(opts["table"]), "view": view["name"]},
        target=name,
        binding={"drawing": before, "components": components, "records": rows},
        preview={
            "command": "drawing bom balloons",
            "model": name,
            "table": table,
            "view": view["name"],
            "records": rows,
            "reserved_region": area,
            "effect": "native BOM balloons associated with table records "
            "and visible component occurrences",
        },
        verify=verify,
        observe=lambda c: bom.note_inventory(
            _annotation_drawing(engine.show(c, name), name, assembly)
        ),
        before=notes,
        arguments={k: opts.get(k) for k in ("model", "table", "view")},
    )
    return p


def add_balloons(opts: dict) -> dict:
    return engine.write("drawing add-balloons", opts, _prepare_balloons, _plan_balloons)


def _prepare_move_table(opts: dict) -> dict:
    validate(opts["table"], text(pattern=r"^[0-9]{1,9}$", maximum=9), "table")
    return {"name": _drawing(opts), "at": _place(opts)}


def _plan_move_table(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, at = pre["name"], pre["at"]
    before = _reading(client, name)
    tables = before.get("tables") or []
    table = next((t for t in tables if str(t.get("id")) == opts["table"]), None)
    if table is None:
        raise Error(
            "E_NOT_FOUND",
            "the drawing has no table of that id",
            {"table": opts["table"], "tables": [t.get("id") for t in tables]},
        )
    if table.get("from_format"):
        raise Error(
            "E_CONFLICT", "the table belongs to the drawing's format", {"table": opts["table"]}
        )
    region = _table_move_region(before, table, at)

    def verify(c: Client, data: dict):
        shown = engine.show(c, name)
        row = next(
            (t for t in shown.get("tables") or [] if str(t.get("id")) == opts["table"]),
            {},
        )
        observed_region = _table_move_region(shown, row, row.get("at"))
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("table_where_asked", _close(row.get("at"), at), at=row.get("at")),
                engine.check("cells_untouched", row.get("cells") == table.get("cells")),
                engine.check(
                    "outline_translated_as_planned",
                    all(
                        _close(a, b)
                        for a, b in zip(
                            observed_region["outline_after"], region["outline_after"], strict=True
                        )
                    ),
                ),
                engine.check(
                    "full_table_inside_bound_sheet",
                    observed_region["sheet"] == region["sheet"]
                    and observed_region["units"] == region["units"],
                ),
            ],
            "observations": [
                {"observation": "independent_table_outline", **observed_region},
                {"observation": "layout_feedback", **drawing_warnings.feedback(shown)},
            ],
            "not_checked": list(drawing_warnings.EXCLUSIONS),
        }

    return engine.Plan(
        op="drawing.move-table",
        request={"model": name, "table": int(opts["table"]), "at": at},
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing move-table",
            "model": name,
            "table": table,
            "to": at,
            "region": region,
            "layout_feedback": drawing_warnings.feedback(
                before, proposals=[drawing_warnings.translated("tables", table, at)]
            ),
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("tables"),
        before=tables,
        arguments={k: opts.get(k) for k in ("model", "table", "x", "y")},
    )


def move_table(opts: dict) -> dict:
    return engine.write("drawing move-table", opts, _prepare_move_table, _plan_move_table)


# ------------------------------------------------------------------ add-datum, add-gtol

# Datum letters as drawing standards allow them: I, O and Q are left out.
DATUM_LABEL = text(pattern=r"^(?![IOQ])[A-Z](?:(?![IOQ])[A-Z])?$", maximum=2)
FACE_REF = text(pattern=r"^(?:surface:[0-9]{1,9}|[A-Za-z][A-Za-z0-9_-]{0,30})$", maximum=40)
GTOL_VALUE = text(pattern=r"^[0-9]{1,6}(?:\.[0-9]{1,6})?$", maximum=13)
GTOL_TYPES = (
    "straightness",
    "flatness",
    "circularity",
    "cylindricity",
    "line-profile",
    "surface-profile",
    "angularity",
    "perpendicularity",
    "parallelism",
    "position",
    "concentricity",
    "symmetry",
    "circular-runout",
    "total-runout",
)
# What a frame reads back as: Creo writes its own symbols into the value.
DIAMETER_SIGNS = ("⌀", "Ø", "ø")
MATERIAL_SIGNS = {"mmc": "Ⓜ", "lmc": "Ⓛ"}


def _view_model(client: Client, before: dict, view_name: str) -> tuple[dict, str]:
    views = before.get("views") or []
    hits = [v for v in views if v.get("name") == view_name]
    if not hits:
        raise Error(
            "E_NOT_FOUND",
            "the drawing has no view of that name",
            {"view": view_name, "views": [v.get("name") for v in views], "_untrusted": ["views"]},
        )
    if len(hits) > 1:
        raise Error("E_CONFLICT", "two views of the drawing share that name", {"view": view_name})
    model = str(hits[0].get("model") or "").lower()
    if not model.endswith(".prt"):
        raise Error(
            "E_UNSUPPORTED",
            "datums and frames go on a part's geometry; this view shows " + (model or "no model"),
            {"view": view_name, "_untrusted": ["view"]},
        )
    return hits[0], model


def _prepare_datum(opts: dict) -> dict:
    validate(opts["label"], DATUM_LABEL, "label")
    validate(opts["on"], FACE_REF, "on")
    return {"name": _drawing(opts)}


def _plan_datum(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, label = pre["name"], opts["label"]
    before = _reading(client, name)
    _, model = _view_model(client, before, opts["view"])
    datums = before.get("datums") or []
    if any(d.get("label") == label for d in datums):
        raise Error(
            "E_CONFLICT",
            "the drawing already has a datum of that letter",
            {"label": label, "datums": [d.get("label") for d in datums], "_untrusted": ["datums"]},
        )
    items = engine.normalize(client.op("geometry.list", {"model": model}))["items"]
    faces = {
        str(i.get("ref")).upper(): i
        for i in items
        if i.get("kind") == "datum_plane"
        or (i.get("kind") == "surface" and i.get("type") == "plane")
    }
    if opts["on"].upper() not in faces:
        raise Error(
            "E_NOT_FOUND",
            "the view's part has no flat face or datum plane of that name",
            {
                "on": opts["on"],
                "fix": f"creo-cli geometry list --model {model} --kind surface",
                "_untrusted": ["on", "fix"],
            },
        )

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("datums") or []
        made = [d for d in after if d.get("label") == label]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("one_datum_added", len(after) == len(datums) + 1 and len(made) == 1),
                engine.check(
                    "on_the_face_asked",
                    len(made) == 1 and str(made[0].get("on")).upper() == opts["on"].upper(),
                    on=made[0].get("on") if made else None,
                ),
            ],
            "not_checked": ["which_side_of_the_edge_the_symbol_stands"],
        }

    return engine.Plan(
        op="drawing.add-datum",
        request={"model": name, "label": label, "view": opts["view"], "on": opts["on"]},
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing add-datum",
            "model": name,
            "label": label,
            "view": opts["view"],
            "on": faces[opts["on"].upper()],
            "effect": "a datum feature symbol on the face, drawn on the edge the view shows it as, "
            "at the face's middle",
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("datums"),
        before=datums,
        arguments={k: opts.get(k) for k in ("model", "label", "view", "on")},
    )


def add_datum(opts: dict) -> dict:
    return engine.write("drawing add-datum", opts, _prepare_datum, _plan_datum)


def _prepare_gtol(opts: dict) -> dict:
    validate(opts["value"], GTOL_VALUE, "value")
    datums = []
    if opts.get("datums") is not None:
        datums = [d.strip() for d in str(opts["datums"]).split(",")]
        if len(datums) > 3:
            raise Error("E_VALIDATION", "a frame names at most three datums", {"path": "datums"})
        for d in datums:
            validate(d, DATUM_LABEL, "datums")
        if len(set(datums)) != len(datums):
            raise Error("E_VALIDATION", "a datum is named twice", {"path": "datums"})
    by_dimension = opts.get("dimension") is not None
    placed = {k for k in ("view", "on", "x", "y") if opts.get(k) is not None}
    if by_dimension and placed:
        raise Error(
            "E_VALIDATION",
            "a frame goes on a dimension, or in a view at x, y -- not both",
            {"path": sorted(placed)[0]},
        )
    if not by_dimension:
        for key in ("view", "x", "y"):
            if opts.get(key) is None:
                raise Error(
                    "E_VALIDATION",
                    "give --dimension, or --view with --x --y (and --on for a leader)",
                    {"path": key},
                )
        if opts.get("on") is not None:
            validate(opts["on"], EDGE_REF, "on")
        _place(opts)
    else:
        validate(opts["dimension"], DIMENSION_REF, "dimension")
    return {"name": _drawing(opts), "datums": datums}


def _plan_gtol(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, datums = pre["name"], pre["datums"]
    before = _reading(client, name)
    attach: dict
    if opts.get("dimension") is not None:
        rows = before.get("dimensions") or []
        hits = _match(rows, opts["dimension"])
        if not hits:
            raise Error(
                "E_NOT_FOUND",
                "the drawing shows no dimension of that name",
                {
                    "dimension": opts["dimension"],
                    "fix": f"creo-cli model show --model {name} lists them under dimensions",
                    "_untrusted": ["dimension", "fix"],
                },
            )
        if len(hits) > 1:
            raise Error(
                "E_CONFLICT",
                "two dimensions carry that name; write it as name@model",
                {"dimension": opts["dimension"]},
            )
        if own(hits[0], name):
            raise Error(
                "E_CONFLICT",
                "a frame goes on a model's dimension, not on one made on the drawing",
                {"dimension": opts["dimension"]},
            )
        attach = {"dimension": f"{hits[0]['name']}@{hits[0]['model']}"}
        attached, owner = "annotation", hits[0]["model"]
    else:
        _, model = _view_model(client, before, opts["view"])
        at = [opts["x"], opts["y"]]
        on_sheet(before, at[0], at[1], "frame")
        attach = {"view": opts["view"], "at": at}
        attached, owner = "free", name
        if opts.get("on") is not None:
            edges = engine.normalize(client.op("geometry.list", {"model": model, "kind": "edge"}))
            if not any(e.get("ref") == opts["on"] for e in edges.get("items") or []):
                raise Error(
                    "E_NOT_FOUND",
                    "the view's part has no edge of that id",
                    {
                        "on": opts["on"],
                        "fix": f"creo-cli geometry list --model {model} --kind edge",
                    },
                )
            attach["on"] = opts["on"]
            attached = "leaders"
    defined = {d.get("label") for d in before.get("datums") or []}
    frames = before.get("gtols") or []
    seen = {(str(g.get("id")), g.get("model")) for g in frames}

    def verify(c: Client, data: dict):
        after = engine.show(c, name).get("gtols") or []
        new = [g for g in after if (str(g.get("id")), g.get("model")) not in seen]
        made = new[0] if len(new) == 1 else {}
        value = str(made.get("value") or "")
        checks = [
            engine.check("one_frame_added", len(new) == 1),
            engine.check("characteristic_as_asked", made.get("type") == opts["type"]),
            engine.check(
                "value_as_asked",
                opts["value"].replace(".", "") in value.replace(".", "").replace(",", "")
                and (not opts.get("diameter") or value[:1] in DIAMETER_SIGNS)
                and (not opts.get("material") or value.endswith(MATERIAL_SIGNS[opts["material"]])),
                value=value,
            ),
            engine.check(
                "datums_as_asked", made.get("datums") == datums, datums=made.get("datums")
            ),
            engine.check("attached_as_asked", made.get("attached") == attached),
        ]
        if "at" in attach:
            checks.append(
                engine.check(
                    "placed_where_asked", _close(made.get("at"), attach["at"]), at=made.get("at")
                )
            )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": [
                {
                    "observation": "datums_not_on_this_drawing",
                    "labels": [d for d in datums if d not in defined],
                }
            ],
            "not_checked": ["overlap_with_views_or_other_items"],
        }

    request = {"model": name, "type": opts["type"], "value": opts["value"], "attach": attach}
    if opts.get("diameter"):
        request["diameter"] = True
    if opts.get("material"):
        request["material"] = opts["material"]
    if datums:
        request["datums"] = datums
    return engine.Plan(
        op="drawing.add-gtol",
        request=request,
        target=name,
        binding={"drawing": before},
        preview={
            "command": "drawing add-gtol",
            "model": name,
            "frame": {k: v for k, v in request.items() if k != "model"},
            "owner": owner,
            "datums_not_on_this_drawing": [d for d in datums if d not in defined],
            "effect": (
                f"a frame under the dimension; Creo keeps it with {owner}, which owns the dimension"
                if attached == "annotation"
                else "a frame in the view" + (", led to the edge" if attached == "leaders" else "")
            ),
        },
        verify=verify,
        observe=lambda c: engine.show(c, name).get("gtols"),
        before=frames,
        arguments={
            k: opts.get(k)
            for k in (
                "model",
                "type",
                "value",
                "diameter",
                "material",
                "datums",
                "dimension",
                "view",
                "on",
                "x",
                "y",
            )
        },
    )


def add_gtol(opts: dict) -> dict:
    return engine.write("drawing add-gtol", opts, _prepare_gtol, _plan_gtol)


# ------------------------------------------------------------------ remove

NUMBERED = ("note", "table", "symbol", "gtol")
KINDS = {
    "note": "notes",
    "table": "tables",
    "symbol": "symbols",
    "dimension": "dimensions",
    "view": "views",
    "gtol": "gtols",
    "datum": "datums",
}


def _prepare_remove(opts: dict) -> dict:
    validate(opts["item"], ITEM_REF, "item")
    kind, _, key = opts["item"].partition(":")
    return {"name": _drawing(opts), "kind": kind, "key": key}


def _plan_remove(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name, kind, key = pre["name"], pre["kind"], pre["key"]
    if kind == "view":
        from .. import drawing_views

        return drawing_views.plan(client, opts, name, key)
    before = _reading(client, name)

    def inventory(c: Client) -> dict:
        return engine.resource_inventory(
            c, "drawing.resources", {"model": name, "kind": KINDS[kind], "sheet": None}
        )

    observed_before = inventory(client)
    rows = observed_before["items"]
    if kind == "dimension":
        hits = [r for r in rows if str(r.get("name")).lower() == key.lower()]
        mine = [r for r in hits if own(r, name)]
        if hits and not mine:
            raise Error(
                "E_CONFLICT",
                "that dimension is the model's; take it off the drawing instead",
                {
                    "item": opts["item"],
                    "fix": f"creo-cli drawing dimension hide --model {name} --dimension {key}",
                    "_untrusted": ["fix"],
                },
            )
        candidates = mine
    elif kind == "view":
        hits = [r for r in rows if r.get("name") == key]
        if len(hits) > 1:
            raise Error(
                "E_CONFLICT",
                "two views of the drawing share that name",
                {"item": opts["item"], "_untrusted": ["item"]},
            )
        candidates = hits
        children = [r.get("name") for r in rows if candidates and r.get("parent") == key]
        if children:
            raise Error(
                "E_CONFLICT",
                "views are taken from that view; remove them first",
                {"item": opts["item"], "children": children, "_untrusted": ["item", "children"]},
            )
    elif kind == "gtol":
        number, _, owner = key.partition("@")
        owner = owner.lower() or name
        candidates = [r for r in rows if str(r.get("id")) == number and r.get("model") == owner]
    elif kind == "datum":
        candidates = [r for r in rows if r.get("label") == key]
    else:
        candidates = [r for r in rows if str(r.get("id")) == key]
    if len(candidates) > 1:
        raise Error(
            "E_CONFLICT",
            "resource selector must identify exactly one owned item",
            {"item": opts["item"], "matched_count": len(candidates), "_untrusted": ["item"]},
        )
    target = candidates[0] if candidates else None
    if target is None:
        raise Error(
            "E_NOT_FOUND",
            f"the drawing has no {kind} of that {'id' if kind in NUMBERED else 'name'}",
            {
                "item": opts["item"],
                "fix": f"creo-cli model show --model {name} lists its {KINDS[kind]}",
                "_untrusted": ["item"],
            },
        )
    if kind == "table" and target.get("from_format"):
        raise Error(
            "E_CONFLICT",
            "the table belongs to the drawing's format, not to the drawing",
            {"item": opts["item"]},
        )
    source_owner = target.get("model") if kind == "gtol" else None
    owner_before = None
    if source_owner and source_owner != name:
        source_owner = engine.model_name(source_owner)
        session = engine.session(client)
        engine.require_in_session(session, source_owner)
        owner_before = engine.show(client, source_owner)
        if owner_before.get("model") != source_owner:
            raise Error("E_VERIFY_INCOMPLETE", "GTol source owner was not identified")
        engine.store_directory(owner_before, session)

    def same(a: dict) -> bool:
        if kind == "dimension":
            return str(a.get("id")) == str(target.get("id")) and own(a, name)
        if kind == "view":
            return a.get("name") == key
        if kind == "gtol":
            return str(a.get("id")) == str(target.get("id")) and a.get("model") == target.get(
                "model"
            )
        if kind == "datum":
            return a.get("label") == key
        return str(a.get("id")) == str(target.get("id"))

    def verify(c: Client, data: dict):
        readback = inventory(c)
        after = readback["items"]
        kept = [row for row in rows if not same(row)]
        observed_kept = [row for row in after if not same(row)]
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("item_removed", not any(same(a) for a in after)),
                engine.check(
                    f"other_{KINDS[kind]}_kept",
                    sorted(digest(row) for row in observed_kept)
                    == sorted(digest(row) for row in kept),
                    expected_count=len(kept),
                    observed_count=len(observed_kept),
                ),
            ],
            "observations": [
                {"observation": "independent_resource_inventory", "inventory": readback}
            ],
            "not_checked": ["the_models_untouched_by_design", "other_resource_kinds_untouched"],
        }

    def observe(c: Client):
        return {
            "items": inventory(c)["items"],
            "source_owner": engine.show(c, source_owner) if owner_before is not None else None,
        }

    key_out = {
        "dimension": target.get("name"),
        "gtol": f"{target.get('id')}@{target.get('model')}"
        if target.get("model") != name
        else str(target.get("id")),
    }.get(kind, key)
    return engine.Plan(
        op="drawing.remove",
        request={"model": name, "item": f"{kind}:{key_out}"},
        target=name,
        binding={
            "drawing": before,
            "resource_inventory": observed_before,
            "source_owner": owner_before,
        },
        preview={
            "command": "drawing remove",
            "model": name,
            "removes": {"kind": kind} | target,
            "affected_models": [name] + ([source_owner] if owner_before is not None else []),
            "effect": "it leaves the drawing; what it was stays in this preview and the receipt, "
            "to add again"
            + (
                "; a view takes what it shows with it: the model's dimensions shown in it leave "
                "the drawing, a cross-section it was cut by stays in the model"
                if kind == "view"
                else ""
            )
            + (
                f"; the frame is {target.get('model')}'s, which changes"
                if kind == "gtol" and target.get("model") != name
                else ""
            ),
        },
        verify=verify,
        observe=observe,
        before={"items": rows, "source_owner": owner_before},
        arguments={"model": opts["model"], "item": opts["item"]},
    )


def remove(opts: dict) -> dict:
    if opts.get("_command_path") == "drawing item remove" and opts["item"].startswith("view:"):
        raise Error(
            "E_UNSUPPORTED",
            "view deletion uses the dedicated public lifecycle",
            {"fix": "use drawing view remove --model <drawing> --item <native view name or id>"},
        )
    return engine.write("drawing remove", opts, _prepare_remove, _plan_remove)


# ------------------------------------------------------------------ declarations

X = Param("x", "number", required=True, description="sheet x, in the sheet's units")
Y = Param("y", "number", required=True, description="sheet y, in the sheet's units")
COMMANDS = [
    Command(
        "drawing edit-note",
        "Change a note's text, move a free note, or both; ids as model show lists them under notes",
        edit_note,
        written(shape(SUMMARY | {"note": NOTE}, ("model", "note"))),
        (
            MODEL,
            Param("note", required=True, description="the note's id"),
            Param("text", description="the new text; \\n breaks a line"),
            Param("x", "number", description="new sheet x, with --y"),
            Param("y", "number", description="new sheet y, with --x"),
        ),
        write=True,
        untrusted=WRITTEN,
        example='--model bracket --note 3 --text "4X M6 THRU" --x 40 --y 30',
        service_ops=("drawing.edit-note",),
    ),
    Command(
        "drawing move-dimension",
        "Move a dimension's text on a drawing, off a view or another dimension; the value is "
        "not touched. Single-sheet only; verify two independent anchor/envelope readings "
        "within the invocation deadline. Unproved or rerouted text bounds stay unavailable; "
        "the move is never retried",
        move_dimension,
        written(shape(SUMMARY | {"moved": shape({"name": S, "id": S})}, ("model", "moved"))),
        (
            MODEL,
            Param(
                "dimension",
                required=True,
                description="its name as model show lists it: d12, d12@part.prt, rdd0",
            ),
            X,
            Y,
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --dimension d4 --x 120 --y 40",
        service_ops=("drawing.move-dimension",),
    ),
    Command(
        "drawing add-dimension",
        "Add a reference dimension between two straight edges of a part as a view shows them: "
        "a size no feature carries, such as a total thickness. Creo measures it; it drives "
        "nothing",
        add_dimension,
        written(shape(SUMMARY | {"dimension": DIMENSION}, ("model", "dimension"))),
        (
            MODEL,
            Param("view", required=True, description="the view, as model show names it"),
            Param("from", required=True, description="edge:<id>, from geometry list"),
            Param("to", required=True, description="edge:<id>, from geometry list"),
            Param(
                "from-sense",
                choices=("auto", "center", "end1", "end2", "midpoint"),
                description="explicit attachment sense; circle center requires center",
            ),
            Param(
                "to-sense",
                choices=("auto", "center", "end1", "end2", "midpoint"),
                description="explicit attachment sense for the second edge",
            ),
            Param(
                "orientation",
                choices=("horizontal", "vertical", "slanted"),
                description="how it measures on the sheet; slanted, the default, is square to "
                "the edges",
            ),
            X,
            Y,
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --view TOP --from edge:62 --to edge:64 "
        "--orientation vertical --x 170 --y 232",
        service_ops=("drawing.add-dimension", "geometry.list"),
    ),
    Command(
        "drawing add-table",
        "Add a table -- a title block, a parts list -- from its top left corner: column widths, "
        "row heights, the cells' text and merged regions",
        add_table,
        written(shape(SUMMARY | {"table": TABLE}, ("model", "table"))),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=TABLE_SCHEMA,
        request_example=TABLE_EXAMPLE,
        example="--model bracket --request title.json",
        service_ops=("drawing.add-table",),
    ),
    Command(
        "drawing add-title-block",
        "Add a title block in the sheet's bottom right corner, filled from the model: title, "
        "drawing number, material, the sheet's scale, today's date; a request overrides any "
        "field",
        add_title_block,
        written(shape(SUMMARY | {"table": TABLE}, ("model", "table"))),
        (
            MODEL,
            Param(
                "request",
                description="optional request file, or - for stdin: fields to fill in place of "
                "the model's -- title, number, material, scale, quantity, date, drawn_by, "
                "checked_by",
            ),
            Param(
                "language",
                choices=("en", "zh"),
                description="the labels' language: en (Title, Scale ...) or zh (名称, 比例 ...)",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        request=TITLE_SCHEMA,
        request_example=TITLE_EXAMPLE,
        example="--model bracket --language zh",
        service_ops=("drawing.add-table",),
    ),
    Command(
        "drawing add-symbol",
        "Place a symbol from Creo's library (surffins/generic/standard, weld and datum symbols) "
        "or a .sym file of your own, its variables filled; an unknown name lists the library",
        add_symbol,
        written(
            shape(
                SUMMARY | {"symbol": shape({"id": S, "definition": S, "variables": array(S)})},
                ("model", "symbol"),
            )
        ),
        (
            MODEL,
            Param(
                "symbol",
                required=True,
                description="a library name, its path there without .sym; or a .sym file in "
                "the workspace",
            ),
            X,
            Y,
            Param(
                "value",
                description="comma-separated name=value for the symbol's variables, "
                "roughness_height=3.2",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --symbol surffins/generic/standard --x 200 --y 150 "
        "--value roughness_height=3.2",
        service_ops=("drawing.symbol", "drawing.add-symbol"),
    ),
    Command(
        "drawing add-bom",
        "Add a native repeat-region BOM for one flat assembly on one millimetre sheet; "
        "qualified template bytes and complete planned bounds are checked before insertion",
        add_bom,
        written(shape(SUMMARY | {"table": TABLE}, ("model", "table"))),
        (
            MODEL,
            X,
            Y,
            Param(
                "table",
                description="a table from Creo's library, its path there without .tbl (default "
                "Assembly/bom_description_down), or a byte-identical qualified .tbl "
                "in the workspace; "
                "other template extents are unsupported",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model pump --x 10 --y 95",
        service_ops=("drawing.bom-template", "drawing.add-bom", "model.show"),
    ),
    Command(
        "drawing add-balloons",
        "Create native BOM balloons in an explicit assembly view; read back item, quantity "
        "and component occurrence references; full-page visual review remains necessary",
        add_balloons,
        written(
            shape(
                SUMMARY | {"balloons": shape({"table": INT, "view": NS, "made": INT}, ("made",))},
                ("model", "balloons"),
            )
        ),
        (
            MODEL,
            Param("table", required=True, description="the parts list's table id"),
            Param("view", required=True, description="explicit view of this assembly on sheet 1"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model pump --table 0 --view FRONT",
        service_ops=("drawing.add-balloons",),
    ),
    Command(
        "drawing move-table",
        "Move a table so its corner -- the one it was placed by -- is at x, y; a parts list to "
        "where it fits",
        move_table,
        written(shape(SUMMARY | {"table": TABLE}, ("model", "table"))),
        (MODEL, Param("table", required=True, description="the table's id"), X, Y),
        write=True,
        untrusted=WRITTEN,
        example="--model pump --table 0 --x 198 --y 120",
        service_ops=("drawing.move-table",),
    ),
    Command(
        "drawing add-datum",
        "Put a datum feature symbol (A, B, ...) on a flat face or datum plane of the part a view "
        "shows; Creo draws it on the edge the view shows the face as",
        add_datum,
        written(
            shape(
                SUMMARY | {"datum": shape({"id": S, "label": S, "on": NS}, ("label",))},
                ("model", "datum"),
            )
        ),
        (
            MODEL,
            Param(
                "label", required=True, description="one or two capitals; I, O and Q are not used"
            ),
            Param("view", required=True, description="the view that shows the face"),
            Param("on", required=True, description="surface:<id> of a flat face, or a datum plane"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --label A --view FRONT --on surface:53",
        service_ops=("drawing.add-datum", "geometry.list"),
    ),
    Command(
        "drawing add-gtol",
        "Add a geometric tolerance (feature control frame): a characteristic, a value, up to "
        "three datums -- under a shown dimension, led to an edge of a view, or free in a view",
        add_gtol,
        written(shape(SUMMARY | {"gtol": GTOL}, ("model", "gtol"))),
        (
            MODEL,
            Param("type", required=True, choices=GTOL_TYPES, description="the characteristic"),
            Param("value", required=True, description="the tolerance, in the model's units: 0.1"),
            Param(
                "diameter",
                "boolean",
                description="a cylindrical zone: the value gets a diameter sign",
            ),
            Param(
                "material",
                choices=("mmc", "lmc"),
                description="a material condition after the value",
            ),
            Param("datums", description="comma-separated datum letters, primary first: A,B,C"),
            Param("dimension", description="attach under this shown dimension: d10, d10@part.prt"),
            Param("view", description="or place it in this view, at --x --y"),
            Param("on", description="with --view, lead it to this edge:<id>"),
            Param("x", "number", description="sheet x, with --view"),
            Param("y", "number", description="sheet y, with --view"),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --type position --value 0.1 --diameter --material mmc "
        "--datums A,B --dimension d10",
        service_ops=("drawing.add-gtol", "geometry.list"),
    ),
    Command(
        "drawing remove",
        "Remove what the drawing itself owns -- a note, a table, a symbol, a dimension made on "
        "it, a view no other view is taken from, a datum -- or a geometric tolerance. A model's "
        "dimension is taken off with hide-dimension",
        remove,
        written(shape(SUMMARY | {"removed": shape({"item": S}, ("item",))}, ("model", "removed"))),
        (
            MODEL,
            Param(
                "item",
                required=True,
                description="note:<id>, table:<id>, symbol:<id>, dimension:<name>, view:<name>, "
                "datum:<letter>, gtol:<id> (a model's: gtol:<id>@part.prt)",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model bracket --item note:3",
        service_ops=("drawing.remove", "drawing.resources", "model.show", "session.status"),
    ),
]
