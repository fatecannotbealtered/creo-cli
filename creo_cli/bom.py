"""Bounded native repeat-region tables and independently read balloon references."""

from pathlib import Path

from . import drawing_warnings, paths
from .core import Error

# This exact Creo installation template only. Dimensions are checked again after
# retrieval; unsupported templates must never be treated as having zero extent.
TEMPLATES = {
    "5fa5852852a3f9f21e2faeb725012e6bc12ec0c958f511a7f83546a05a1b01ee": {
        "name": "Assembly/bom_description_down",
        "units": "mm",
        "width": 217.043,
        "header_height": 7.62,
        "row_height": 7.62,
        "item_column": 0,
        "model_column": 1,
        "quantity_column": 2,
    }
}


def template(client, requested, expected=None):
    client.require_capability("bom_reference_readback", 2)
    try:
        resolved = client.op("drawing.bom-template", {"table": requested})
        file = Path(resolved["path"])
        before = file.stat()
        source = paths.artifact(file)
        after = file.stat()
    except (OSError, Error) as exc:
        if expected:
            raise Error(
                "E_CONFLICT",
                "confirmed BOM template is unavailable or changed",
                {"expected": expected},
            ) from exc
        if isinstance(exc, FileNotFoundError):
            raise Error(
                "E_NOT_FOUND", "BOM template file is missing", {"template": requested}
            ) from exc
        if isinstance(exc, OSError):
            raise Error("E_IO", "BOM template file cannot be inspected") from exc
        raise

    def stamp(s):
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]

    if stamp(before) != stamp(after):
        raise Error("E_CONFLICT", "BOM template changed during inspection")
    source["file_identity"] = stamp(after)
    if expected and expected != source:
        raise Error(
            "E_CONFLICT",
            "BOM template changed since preview",
            {"expected": expected, "observed": source},
        )
    profile = TEMPLATES.get(source["sha256"])
    if profile is None:
        raise Error(
            "E_UNSUPPORTED",
            "BOM template extent is not qualified before insertion",
            {
                "template": source,
                "supported_sha256": sorted(TEMPLATES),
                "dispatch_state": "not_started",
            },
        )
    return source, profile


def counts(components):
    if not components or any(not c.get("model") for c in components):
        raise Error("E_VERIFY_INCOMPLETE", "BOM component inventory is unavailable")
    if len(components) > 10 or any(not c["model"].endswith(".prt") for c in components):
        raise Error("E_UNSUPPORTED", "this BOM profile supports 1..10 direct part occurrences")
    result = {}
    for c in components:
        if c.get("status") != "FEAT_ACTIVE" or c.get("placed") is not True:
            raise Error(
                "E_VERIFY_INCOMPLETE", "BOM needs active, placed occurrences", {"component": c}
            )
        model = c["model"].lower()
        result[model] = result.get(model, 0) + 1
    return result


def records(table, assembly, components):
    """Match actual native cell model references, item numbers and quantities."""
    expected = counts(components)
    refs = table.get("cell_references")
    if not isinstance(refs, list) or not refs:
        raise Error("E_VERIFY_INCOMPLETE", "native repeat-region cell references are unavailable")
    rows = table.get("cells") or []
    found, items = {}, set()
    result = []
    for row_number in sorted({r["row"] for r in refs}):
        members = [r for r in refs if r["row"] == row_number]
        models = {str(r.get("model", "")).lower() for r in members}
        roots = {str(r.get("assembly", "")).lower() for r in members}
        if len(models) != 1 or roots != {assembly} or not 1 <= row_number <= len(rows):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "BOM row has ambiguous native model references",
                {"row": row_number},
            )
        model = models.pop()
        row = rows[row_number - 1]
        try:
            item, quantity = int(str(row[0]).strip()), int(str(row[2]).strip())
        except (ValueError, IndexError):
            raise Error(
                "E_VERIFY_INCOMPLETE", "BOM item or quantity cannot be read", {"row": row_number}
            ) from None
        if item <= 0 or item in items or model in found or quantity != expected.get(model):
            raise Error(
                "E_VERIFY_FAILED",
                "BOM row differs from the actual assembly",
                {"row": row_number, "model": model, "quantity": quantity, "expected": expected},
            )
        if str(row[1]).strip().lower() != model.rsplit(".", 1)[0]:
            raise Error(
                "E_VERIFY_FAILED",
                "BOM part number differs from its native reference",
                {"row": row_number},
            )
        items.add(item)
        found[model] = quantity
        result.append(
            {
                "row": row_number,
                "item": item,
                "model": model,
                "quantity": quantity,
                "occurrences": [[str(c["id"])] for c in components if c["model"].lower() == model],
            }
        )
    if found != expected:
        raise Error(
            "E_VERIFY_FAILED",
            "BOM does not cover exactly the assembly inventory",
            {"expected": expected, "observed": found},
        )
    return result


def note_inventory(drawing):
    notes = drawing.get("notes")
    if (
        not isinstance(notes, list)
        or any(not isinstance(n, dict) or n.get("id") is None for n in notes)
        or len({str(n["id"]) for n in notes}) != len(notes)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete unique native note inventory is required")
    return notes


def view_balloons(notes, view):
    """Only existing numeric leader notes involving the selected view can provide coverage."""
    return [
        n
        for n in notes
        if str(n.get("displayed_text", "")).strip().isdigit()
        and any(leader.get("view") == view for leader in n.get("leaders") or [])
    ]


def balloons(notes, rows, assembly, view, *, require_all=True):
    matched = []
    for note in notes:
        if not note.get("leaders") or note.get("leaders_complete") is not True:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "balloon has no complete native leader references",
                {"note": note.get("id")},
            )
        try:
            number = int(str(note.get("displayed_text", "")).strip())
        except ValueError:
            raise Error(
                "E_VERIFY_FAILED", "new balloon item number is unreadable", {"note": note.get("id")}
            ) from None
        row = next((r for r in rows if r["item"] == number), None)
        for leader in note["leaders"]:
            occurrence = [str(i) for i in leader.get("component_path", [])]
            if (
                row is None
                or str(leader.get("root") or "").lower() != assembly
                or str(leader.get("model") or "").lower() != row["model"]
                or occurrence not in row["occurrences"]
                or leader.get("view") != view
            ):
                raise Error(
                    "E_VERIFY_FAILED",
                    "balloon item does not match its component and BOM record",
                    {"note": note, "record": row},
                )
            matched.append(
                {
                    "note": note["id"],
                    "item": number,
                    "quantity": row["quantity"],
                    "model": row["model"],
                    "component_path": occurrence,
                    "view": view,
                }
            )
    if require_all and {m["item"] for m in matched} != {r["item"] for r in rows}:
        raise Error(
            "E_VERIFY_FAILED",
            "not every BOM record has an associated balloon",
            {"matched": matched, "records": rows},
        )
    return matched


def region(before, outline, resource):
    """Only known rectangular conflicts; no claim of general annotation layout."""
    sheet = before["sheets"][0]
    lo, hi = outline
    detail = {
        "resource": resource,
        "requested_outline": outline,
        "sheet": sheet["number"],
        "sheet_bounds": [[0, 0], [sheet["width"], sheet["height"]]],
        "units": sheet["units"],
        "layout_feedback": drawing_warnings.feedback(
            before,
            proposals=[
                drawing_warnings.proposal(
                    "tables",
                    {"id": resource, "sheet": sheet["number"]},
                    outline,
                    source="requested bounded region; not future text or leader geometry",
                )
            ],
        ),
    }
    if lo[0] < 0 or lo[1] < 0 or hi[0] > sheet["width"] or hi[1] > sheet["height"]:
        raise Error("E_VALIDATION", "complete planned region crosses the sheet boundary", detail)
    conflicts = []
    for kind in ("views", "tables"):
        for obj in before.get(kind, []):
            box = obj.get("outline")
            if not box:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "existing drawing object outline is unavailable",
                    {"kind": kind, "object": obj.get("id", obj.get("name"))},
                )
            if lo[0] < box[1][0] and box[0][0] < hi[0] and lo[1] < box[1][1] and box[0][1] < hi[1]:
                conflicts.append(
                    {"kind": kind, "object": obj.get("id", obj.get("name")), "outline": box}
                )
    if conflicts:
        raise Error(
            "E_CONFLICT",
            "planned region overlaps existing drawing objects",
            detail
            | {
                "conflicts": conflicts,
                "views": [c["object"] for c in conflicts if c["kind"] == "views"],
                "tables": [c["object"] for c in conflicts if c["kind"] == "tables"],
                "fix": "move the listed views or tables clear of the requested region",
            },
        )
    return detail
