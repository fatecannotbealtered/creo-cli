"""Limited independent view identity and exploded-display evidence.

A view's Boolean display state is not a binding to an assembly named state. Missing
native getter evidence remains incomplete, including a getter that ordinarily returned
unsupported. Pending transport errors are handled by the Client before this predicate.
"""

from __future__ import annotations

SOURCES = {
    "id": "WView2D.GetViewId",
    "name": "View2D.GetName",
    "sheet": "View2D.GetSheetNumber",
    "model": "View2D.GetModel/Model.GetFileName",
}


def _id(value):
    return (
        str(value)
        if type(value) is int or isinstance(value, str) and value.lstrip("-").isdigit()
        else None
    )


def _field(row, field):
    report = row.get("view_identity_readback")
    report = report if isinstance(report, dict) else {}
    value = report.get(field)
    value = value if isinstance(value, dict) else {}
    complete = value.get("complete") is True and value.get("source") == SOURCES[field]
    result = value.get("value")
    if field == "id":
        complete = complete and _id(result) is not None
    elif field == "sheet":
        complete = complete and type(result) is int and result > 0
    else:
        complete = complete and isinstance(result, str) and bool(result.strip())
    return complete, result


def _flag(row):
    report = row.get("exploded_display_readback")
    report = report if isinstance(report, dict) else {}
    complete = (
        report.get("complete") is True
        and report.get("source") == "WView2D.IsExplodedState"
        and type(report.get("value")) is bool
    )
    return complete, report


def protected_view_complete(row):
    """A preserved row needs actual identity and Boolean evidence, not identical errors."""
    report = row.get("view_identity_readback")
    return (
        isinstance(report, dict)
        and report.get("complete") is True
        and all(_field(row, field)[0] for field in SOURCES)
        and all(
            _id(_field(row, field)[1]) == _id(row.get(field))
            if field == "id"
            else _field(row, field)[1] == row.get(field)
            for field in SOURCES
        )
        and _flag(row)[0]
    )


def inventory(rows):
    """Return ID coverage and duplicate facts without silently collapsing a dictionary."""
    values = [_id(row.get("id")) for row in rows]
    known = [value for value in values if value is not None]
    return {
        "complete": len(known) == len(values),
        "unique": len(set(known)) == len(known),
        "ids": known,
    }


def added_view(before, after, *, name, model, sheet, exploded):
    """Identify a uniquely new native ID, then read its own native properties."""
    old, now = inventory(before), inventory(after)
    complete = old["complete"] and now["complete"]
    old_ids = set(old["ids"])
    new = [row for row in after if _id(row.get("id")) not in old_ids]
    fresh = new[0] if complete and old["unique"] and now["unique"] and len(new) == 1 else None
    checks = [
        {"check": "view_identity_inventory_complete", "passed": True if complete else None},
        {"check": "unique_native_view_ids", "passed": old["unique"] and now["unique"]},
        {
            "check": "one_new_view_identity",
            "passed": len(new) == 1 if complete else None,
            "old_ids": old["ids"],
            "observed_ids": now["ids"],
        },
    ]
    if fresh is None:
        return None, checks
    checks.append(
        {
            "check": "new_view_name_unique",
            "passed": sum(row.get("name") == name for row in after) == 1
            and fresh.get("name") == name,
        }
    )
    identity_complete = all(_field(fresh, field)[0] for field in SOURCES)
    report = fresh.get("view_identity_readback")
    report = report if isinstance(report, dict) else {}
    consistent = all(
        _id(_field(fresh, field)[1]) == _id(fresh.get(field))
        if field == "id"
        else _field(fresh, field)[1] == fresh.get(field)
        for field in SOURCES
    )
    checks.append(
        {
            "check": "view_identity_readback_complete",
            "passed": bool(report.get("complete") is True and consistent)
            if identity_complete
            else None,
            "observed": report,
        }
    )
    for field, expected in (("model", model), ("sheet", sheet)):
        available, value = _field(fresh, field)
        checks.append(
            {
                "check": "view_" + field + "_as_requested",
                "passed": value == expected if available else None,
                "expected": expected,
                "observed": value,
            }
        )
    available, flag = _flag(fresh)
    checks.append(
        {
            "check": "exploded_display_as_requested",
            "passed": flag["value"] is exploded if available else None,
            "expected": exploded,
            "observed": flag,
        }
    )
    return fresh, checks
