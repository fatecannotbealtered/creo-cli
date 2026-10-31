"""One literal free note on an observed single mm sheet; no creation or replay here."""

from __future__ import annotations

import math
import re
from copy import deepcopy

from . import engine
from .core import Error, canonical, digest

PROFILE = "single-mm-free-note-v1"
CAPABILITY = "simple_drawing_note_readback"
RESOURCES = (
    "models",
    "sheets",
    "views",
    "dimensions",
    "tables",
    "symbols",
    "datums",
    "gtols",
    "draft_entities",
    "draft_arcs",
    "draft_entity_readback",
    "projection",
)
NOT_CHECKED = [
    "full_source_solid_topology_and_hidden_feature_semantics",
    "unreported_note_font_and_glyph_style_properties",
    "dimension_cross_time_envelope_stability",
    "complete_layout_and_manufacturing_approval",
]


def native_id(value):
    if type(value) not in (str, int):
        return None
    raw = str(value)
    return raw if re.fullmatch(r"0|[1-9][0-9]*", raw, re.ASCII) else None


def point(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(type(number) in (float, int) and math.isfinite(number) for number in value)
    )


def notes_by_id(rows, name, *, require_membership=True):
    if not isinstance(rows, list) or len(rows) > 128:
        raise Error("E_VERIFY_INCOMPLETE", "complete bounded note inventory is unavailable")
    result = {}
    for row in rows:
        ident = native_id(row.get("id")) if isinstance(row, dict) else None
        membership = row.get("membership_readback") if isinstance(row, dict) else None
        if ident is None or ident in result or row.get("error") is not None:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "note identity or independent drawing membership is unavailable or ambiguous",
            )
        if require_membership and (
            not isinstance(membership, dict)
            or membership.get("complete") is not True
            or membership.get("drawing") != name
            or native_id(membership.get("note_id")) != ident
            or not membership.get("source")
        ):
            raise Error("E_VERIFY_INCOMPLETE", "independent note membership is unavailable")
        result[ident] = row
    return result


def validate_drawing(drawing, name):
    if (
        not isinstance(drawing, dict)
        or drawing.get("model") != name
        or drawing.get("type") != "drawing"
    ):
        raise Error("E_VERIFY_INCOMPLETE", "actual drawing owner is unavailable")
    sheets = drawing.get("sheets")
    if not isinstance(sheets, list) or len(sheets) != 1:
        raise Error("E_UNSUPPORTED", "simple free notes require one drawing sheet")
    sheet = sheets[0]
    if (
        not isinstance(sheet, dict)
        or type(sheet.get("number")) is not int
        or sheet.get("number") != 1
        or sheet.get("units") != "mm"
    ):
        raise Error(
            "E_UNSUPPORTED", "simple free notes require an independently observed mm sheet 1"
        )
    if (
        not point([sheet.get("width"), sheet.get("height")])
        or min(sheet["width"], sheet["height"]) <= 0
    ):
        raise Error("E_VERIFY_INCOMPLETE", "actual sheet extent is unavailable")
    for key in (
        "models",
        "views",
        "dimensions",
        "tables",
        "symbols",
        "datums",
        "gtols",
        "draft_arcs",
    ):
        if not isinstance(drawing.get(key), list) or len(drawing[key]) > 256:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "drawing protection inventory is unavailable",
                {"resource": key},
            )
        if (
            any(not isinstance(row, dict) or row.get("error") is not None for row in drawing[key])
            and key != "models"
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "drawing protection contains an unreadable resource",
                {"resource": key},
            )
    models = drawing["models"]
    if (
        not models
        or len(models) > 4
        or any(
            not isinstance(model, str) or not model.endswith((".prt", ".asm")) for model in models
        )
        or len(set(models)) != len(models)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "actual drawing source identities are unavailable")
    if not isinstance(drawing.get("projection"), str):
        raise Error("E_VERIFY_INCOMPLETE", "drawing projection is unavailable")
    entities = drawing.get("draft_entity_readback")
    if (
        type(drawing.get("draft_entities")) is not int
        or not isinstance(entities, dict)
        or entities.get("completed") is not True
        or not isinstance(entities.get("items"), list)
        or entities.get("count") != len(entities["items"])
        or drawing["draft_entities"] != len(entities["items"])
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete draft-entity protection is unavailable")
    views = drawing["views"]
    view_ids = [native_id(row.get("id")) for row in views]
    if any(ident is None for ident in view_ids) or len(set(view_ids)) != len(view_ids):
        raise Error("E_VERIFY_INCOMPLETE", "existing view identities are ambiguous")
    if any(
        type(view.get("sheet")) is not int
        or view.get("sheet") != 1
        or view.get("model") not in models
        for view in views
    ):
        raise Error("E_VERIFY_INCOMPLETE", "existing view page or source identity is unavailable")
    old = notes_by_id(drawing.get("notes"), name)
    for row in old.values():
        attachment = row.get("attachment_readback")
        if (
            type(row.get("sheet")) is not int
            or row.get("sheet") != 1
            or not isinstance(row.get("text"), str)
            or not isinstance(row.get("displayed_text"), str)
            or row.get("leaders_complete") is not True
            or not isinstance(row.get("leaders"), list)
            or not isinstance(attachment, dict)
            or attachment.get("complete") is not True
            or type(attachment.get("sheet")) is not int
            or attachment.get("sheet") != 1
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "an existing note lacks required protection readback"
            )


def snapshot(client, name, *, baseline=True, source_models=None):
    # This must precede even model.show on a service with the known old 3D-envelope path.
    client.require_capability(CAPABILITY, 1)
    session = engine.session(client)
    if session.get("active_model") != name:
        raise Error(
            "E_CONFLICT",
            "the target drawing must already be active before note preview or inspection",
            {"dispatch_state": "not_started", "required_active_model": name},
        )
    drawing = engine.show(client, name)
    if baseline:
        validate_drawing(drawing, name)
    elif not isinstance(drawing, dict):
        raise Error("E_VERIFY_INCOMPLETE", "independent drawing observation is unreadable")
    references = drawing["models"] if baseline else source_models
    if not isinstance(references, list) or not references:
        raise Error("E_VERIFY_INCOMPLETE", "frozen source model identities are unavailable")
    sources = {}
    for model in references:
        observed = engine.show(client, model)
        if observed.get("model") != model or observed.get("type") not in ("part", "assembly"):
            raise Error("E_VERIFY_INCOMPLETE", "actual source model identity is unavailable")
        sources[model] = observed
    result = {"drawing": drawing, "sources": sources}
    if len(canonical(result)) > 512 * 1024:
        raise Error(
            "E_UNSUPPORTED", "note protection snapshot exceeds the bounded retention budget"
        )
    return result


def intent(before, text, at):
    if not isinstance(text, str) or not point(at):
        raise Error("E_VERIFY_INCOMPLETE", "literal note intent or finite anchor is unavailable")
    if "&" in text or "@" in text:
        raise Error(
            "E_UNSUPPORTED",
            "this simple-note policy accepts literal text without native substitutions",
        )
    return {
        "profile": PROFILE,
        "drawing": before["drawing"]["model"],
        "sheet": 1,
        "units": "mm",
        "text": text,
        "displayed_text": text,
        "at": list(at),
        "anchor_precision_digits": 9,
        "attachment": "free_background",
        "leaders": [],
        "source_models": list(before["drawing"]["models"]),
    }


def check(name, available, passed, **details):
    return {
        "check": name,
        "passed": bool(passed) if available else None,
        **(
            {"reason": "required independent native observation unavailable"}
            if not available
            else {}
        ),
        **details,
    }


def verify(before, wanted, after):
    """The identical pure predicate for confirmation, query, resolve and retained evidence."""
    previous, current = before["drawing"], after["drawing"]
    validate_drawing(previous, wanted["drawing"])
    old = notes_by_id(previous.get("notes"), wanted["drawing"])
    try:
        if not isinstance(current, dict):
            raise Error("E_VERIFY_INCOMPLETE", "independent drawing observation is unreadable")
        now = notes_by_id(current.get("notes"), wanted["drawing"], require_membership=False)
    except Error as error:
        return {
            "accepted": False,
            "checks": [check("independent_note_inventory", False, False, code=error.code)],
            "note": None,
            "not_checked": NOT_CHECKED + ["note_identity_and_requested_postconditions"],
        }
    added = [row for ident, row in now.items() if ident not in old]
    note = added[0] if len(added) == 1 else {}
    membership = note.get("membership_readback")
    membership = membership if isinstance(membership, dict) else {}
    attachment = note.get("attachment_readback")
    attachment = attachment if isinstance(attachment, dict) else {}
    at = note.get("at")
    checks = [
        engine.check(
            "drawing_owner_as_requested",
            current.get("model") == wanted["drawing"] and current.get("type") == "drawing",
        ),
        engine.check("one_note_added", len(added) == 1 and len(now) == len(old) + 1),
        check(
            "new_note_actual_drawing_membership",
            isinstance(membership, dict) and membership.get("complete") is True,
            membership.get("complete") is True
            and membership.get("drawing") == wanted["drawing"]
            and native_id(membership.get("note_id")) == native_id(note.get("id"))
            and bool(membership.get("source")),
        ),
        check(
            "note_says_what_was_asked",
            isinstance(note.get("text"), str),
            note.get("text") == wanted["text"],
        ),
        check(
            "note_displayed_text_as_requested",
            isinstance(note.get("displayed_text"), str),
            note.get("displayed_text") == wanted["displayed_text"],
        ),
        check(
            "note_on_requested_sheet",
            type(note.get("sheet")) is int,
            note.get("sheet") == wanted["sheet"],
        ),
        check(
            "note_free_background_attachment",
            attachment.get("complete") is True and type(attachment.get("sheet")) is int,
            attachment.get("kind") == "free"
            and attachment.get("background") is True
            and attachment.get("sheet") == wanted["sheet"]
            and native_id(attachment.get("view_id")) is not None
            and isinstance(attachment.get("view"), str),
        ),
        check(
            "note_position_read_back",
            point(at),
            point(at)
            and all(
                math.isclose(value, expected, rel_tol=0, abs_tol=1e-9)
                for value, expected in zip(at, wanted["at"], strict=True)
            ),
            observed=at,
            expected=wanted["at"],
            units="mm",
            coordinate_precision_digits=9,
        ),
        check(
            "note_has_no_leaders",
            note.get("leaders_complete") is True and isinstance(note.get("leaders"), list),
            note.get("leaders") == [],
        ),
        engine.check(
            "existing_notes_preserved",
            all(canonical(now.get(ident)) == canonical(row) for ident, row in old.items()),
        ),
        engine.check(
            "existing_drawing_resources_preserved",
            all(canonical(current.get(key)) == canonical(previous.get(key)) for key in RESOURCES),
        ),
        engine.check(
            "source_returned_fields_preserved_in_same_context",
            complete_sources(before)
            and complete_sources(after)
            and canonical(after.get("sources")) == canonical(before.get("sources")),
        ),
    ]
    bounds = note.get("bounds_readback")
    not_checked = list(NOT_CHECKED)
    if not isinstance(bounds, dict) or bounds.get("complete") is not True:
        not_checked.append("new_note_native_2d_bounds")
    return {
        "accepted": all(row["passed"] is True for row in checks),
        "checks": checks,
        "note": note or None,
        "not_checked": not_checked,
        "bounds_observation": {
            "bounds_readback": deepcopy(bounds),
            "box": deepcopy(note.get("box")),
            "layout_complete": False,
        },
    }


def complete_sources(value):
    drawing = value.get("drawing")
    sources = value.get("sources")
    if not isinstance(drawing, dict) or not isinstance(sources, dict):
        return False
    models = drawing.get("models")
    return (
        isinstance(models, list)
        and bool(models)
        and all(isinstance(model, str) for model in models)
        and set(sources) == set(models)
        and all(
            isinstance(sources[name], dict)
            and sources[name].get("model") == name
            and sources[name].get("type") in ("part", "assembly")
            and sources[name].get("error") is None
            for name in models
        )
    )


def retained(run):
    plan = run.get("driver_plan")
    binding = run.get("driver_binding")
    if not isinstance(plan, dict) or not isinstance(binding, dict):
        raise Error("E_VERIFY_INCOMPLETE", "retained note plan or binding is unavailable")
    stored = (
        plan.get("base_snapshot", {}).get("extensions", {}).get("creo", {}).get("observation", {})
    )
    stored = stored if isinstance(stored, dict) else {}
    before, wanted = stored.get("note_before"), stored.get("note_intent")
    if (
        not isinstance(before, dict)
        or not isinstance(wanted, dict)
        or wanted.get("profile") != PROFILE
    ):
        raise Error(
            "E_UNSUPPORTED",
            "this historical note plan has no supported frozen independent-note policy",
        )
    target = plan.get("target")
    if (
        digest(stored) != plan.get("base_snapshot", {}).get("revision")
        or digest(stored) != binding.get("revision")
        or not isinstance(target, dict)
        or binding.get("driver_target") != target
        or target.get("object_id") != wanted.get("drawing")
        or binding.get("target") != wanted.get("drawing")
        or binding.get("command") != run.get("command")
        or run.get("command") != "drawing note add"
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained note observation or target bindings do not match"
        )
    validate_drawing(before.get("drawing"), wanted.get("drawing"))
    if not complete_sources(before):
        raise Error("E_VERIFY_INCOMPLETE", "retained source protection is incomplete")
    changes = run.get("driver_plan", {}).get("changes")
    if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict):
        raise Error("E_VERIFY_INCOMPLETE", "retained note request record is unavailable")
    request = changes[0].get("after")
    bound = run.get("driver_binding", {}).get("arguments", {}).get("request")
    if (
        not isinstance(request, dict)
        or changes[0].get("action") != "drawing.add-note"
        or changes[0].get("resource") != wanted["drawing"]
        or run.get("target") != wanted["drawing"]
        or digest(request) != run.get("request_sha256")
        or bound != request
        or wanted != intent(before, request.get("text", ""), request.get("at", []))
        or request.get("model") != wanted["drawing"]
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained note intent does not match the original request"
        )
    return before, wanted


def recovery(client, run):
    before, wanted = retained(run)
    client.require_capability(CAPABILITY, 1)
    if client.health().get("service_instance_id") != run["driver_plan"]["target"].get(
        "instance_id"
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "another service instance cannot prove the retained note outcome"
        )
    current = snapshot(
        client, wanted["drawing"], baseline=False, source_models=wanted["source_models"]
    )
    proof = verify(before, wanted, current)
    return proof | {
        "intent": wanted,
        "current": current,
        "can_register": ["applied"] if proof["accepted"] else [],
        "coverage": "single literal free/background note, actual drawing membership, page, text, "
        "displayed text, anchor, empty leaders and retained returned resources/source fields; "
        "not full source geometry or complete layout",
    }


def retained_evidence_sufficient(run, proof):
    before, wanted = retained(run)
    if proof.get("intent") != wanted or not isinstance(proof.get("current"), dict):
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained note proof lacks its frozen intent/current state"
        )
    current = verify(before, wanted, proof["current"])
    if not current["accepted"] or proof.get("accepted") is not True:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "retained note evidence does not satisfy the independent note policy",
        )
