"""No-cascade deletion of an isolated general view on one single-part sheet."""

from __future__ import annotations

import math
from copy import deepcopy

from . import engine, machining, paths
from .core import Error, canonical, digest

KINDS = (
    "sheets",
    "views",
    "dimensions",
    "notes",
    "tables",
    "symbols",
    "datums",
    "gtols",
    "entities",
)
LIMIT = 256


def snapshot(client, name):
    client.require_capability("drawing_view_dependencies", 1)
    model = engine.show(client, name)
    readings = {
        kind: engine.resource_inventory(
            client, "drawing.resources", {"model": name, "kind": kind, "sheet": None}
        )
        for kind in KINDS
    }
    supported = readings["views"]["coverage"].get("view_removal_scope") or {}
    if supported.get("complete") is not True:
        raise Error("E_VERIFY_INCOMPLETE", "full native detail-item classification unavailable")
    if supported.get("unsupported"):
        raise Error(
            "E_UNSUPPORTED",
            "drawing contains unsupported detail-item classes",
            {"items": supported["unsupported"]},
        )
    resources = {kind: data["items"] for kind, data in readings.items()}
    if (
        not isinstance(model.get("draft_entities"), int)
        or model["draft_entities"] != len(resources["entities"])
        or not isinstance(model.get("draft_arcs"), list)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "draft summary and complete entity inventory disagree")
    if any(len(rows) > LIMIT for rows in resources.values()):
        raise Error(
            "E_UNSUPPORTED", "bounded view removal accepts at most 256 items per resource kind"
        )
    if len(resources["sheets"]) != 1:
        raise Error("E_UNSUPPORTED", "view removal currently requires a single-sheet drawing")
    validate_entities(resources)
    sources = model.get("models")
    if not isinstance(sources, list) or len(sources) != 1 or not sources[0].endswith(".prt"):
        raise Error("E_UNSUPPORTED", "view removal currently requires one existing part source")
    solid = machining.snapshot(client, sources[0])
    if len(solid["geometry"]["items"]) > 4096 or len(solid["features"]) > 128:
        raise Error(
            "E_UNSUPPORTED", "view removal source exceeds bounded geometry/feature inventory"
        )
    session = engine.session(client)
    files = {
        shown["model"]: paths.model_files(
            engine.store_directory(shown, session), shown["model"], identity=True
        )
        for shown in (model, solid["model"])
    }
    result = {
        "drawing": {
            k: model.get(k)
            for k in (
                "model",
                "origin",
                "modified",
                "projection",
                "models",
                "draft_entities",
                "draft_arcs",
            )
        },
        "resources": resources,
        "solid": solid,
        "files": files,
    }
    if len(canonical(result)) > 256 * 1024:
        raise Error("E_UNSUPPORTED", "view removal snapshot exceeds 256 KiB retention budget")
    return result


def validate_entities(resources):
    """A line's full native identity/owner and sheet-space XYZ endpoints; never a count proxy."""
    sheets = resources.get("sheets") or []
    entities = resources.get("entities")
    if len(sheets) != 1 or not isinstance(entities, list):
        raise Error("E_VERIFY_INCOMPLETE", "complete retained detail-entity inventory unavailable")
    views = {v.get("name"): v for v in resources.get("views", [])}
    ids = set()
    for row in entities:
        if not isinstance(row, dict) or row.get("complete") is not True or not row.get("id"):
            raise Error("E_VERIFY_INCOMPLETE", "native detail-entity identity/geometry incomplete")
        if row["id"] in ids:
            raise Error("E_VERIFY_INCOMPLETE", "duplicate native detail-entity identity")
        ids.add(row["id"])
        if row.get("type") != "line":
            raise Error(
                "E_UNSUPPORTED",
                "view removal currently protects straight draft lines only",
                {"entity": row["id"], "type": row.get("type")},
            )
        if (
            row.get("sheet") != sheets[0]["number"]
            or row.get("units") != sheets[0].get("units")
            or row.get("coordinate_space") != "sheet_lower_left_xyz"
            or not row.get("view_id")
            or not isinstance(row.get("background"), bool)
        ):
            raise Error("E_VERIFY_INCOMPLETE", "detail-entity sheet/view/units unavailable")
        if row["background"] is False:
            owner = views.get(row.get("view"))
            if owner is None or owner.get("id") != row["view_id"]:
                raise Error(
                    "E_VERIFY_INCOMPLETE", "detail entity refers to an unobserved view identity"
                )
        geometry = row.get("geometry") or {}
        for end in ("start", "end"):
            point = geometry.get(end)
            if (
                not isinstance(point, list)
                or len(point) != 3
                or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in point
                )
            ):
                raise Error("E_VERIFY_INCOMPLETE", "detail line XYZ endpoints unavailable")
        if geometry["start"] == geometry["end"]:
            raise Error("E_UNSUPPORTED", "degenerate draft lines are outside this deletion profile")


def validate_snapshot_entities(state):
    if not isinstance(state, dict) or not isinstance(state.get("resources"), dict):
        raise Error("E_VERIFY_INCOMPLETE", "retained drawing snapshot is unavailable")
    validate_entities(state["resources"])
    drawing = state.get("drawing") or {}
    if (
        type(drawing.get("draft_entities")) is not int
        or drawing["draft_entities"] != len(state["resources"]["entities"])
        or drawing.get("draft_arcs") != []
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "retained entity details and draft inventory do not prove the straight-line profile",
        )


def retained_evidence_sufficient(run, proof):
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, intent = retained.get("view_removal_before"), retained.get("view_removal_intent")
    current = proof.get("current")
    validate_snapshot_entities(before)
    validate_snapshot_entities(current)
    if not isinstance(intent, dict) or proof.get("intent") != intent:
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained inspection intent does not match the original deletion"
        )
    checked = verify(before, intent, current)
    if proof.get("accepted") is not all(c["passed"] for c in checked["checks"]):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "historical inspection conclusion lacks complete current-profile proof",
        )


def dependencies(state, target):
    resources = state["resources"]
    validate_entities(resources)
    views = resources["views"]
    known = {v.get("name"): v for v in views}
    if len(known) != len(views) or len({v.get("id") for v in views}) != len(views):
        raise Error("E_VERIFY_INCOMPLETE", "view names and native IDs must be unique")
    sheet = resources["sheets"][0]["number"]
    affected = []
    alignment_unreadable = []
    for row in views:
        proof = row.get("dependency_readback") or {}
        if (
            not row.get("id")
            or (proof.get("complete") is not True and proof.get("basic_complete") is not True)
            or row.get("sheet") != sheet
            or row.get("type") is None
            or not isinstance(row.get("sections"), list)
            or not isinstance(proof.get("children"), list)
            or row.get("model") != state["solid"]["model"]["model"]
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "native view identity/parent/section relationships are incomplete",
                {"view": row.get("name"), "observation": proof},
            )
        if proof.get("complete") is not True:
            alignment_unreadable.append(row["name"])
        for child in proof["children"]:
            if child not in known or known[child].get("parent") != row["name"]:
                raise Error("E_VERIFY_INCOMPLETE", "native parent/child view observations disagree")
        parent = row.get("parent")
        if parent and (
            parent not in known
            or row["name"] not in known[parent]["dependency_readback"]["children"]
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "view parent is not independently confirmed by its children"
            )
        if row["name"] != target["name"] and (
            parent == target["name"] or proof.get("alignment_view") == target["name"]
        ):
            affected.append(
                {
                    "kind": "view",
                    "id": row["id"],
                    "name": row["name"],
                    "relationship": "parent_or_alignment",
                }
            )
    for row in resources["dimensions"]:
        if row.get("view") not in known or row.get("sheet") != sheet:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "dimension view/sheet ownership is incomplete",
                {"dimension": row.get("name")},
            )
        if row["view"] == target["name"]:
            affected.append(
                {
                    "kind": "dimension",
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "model": row.get("model"),
                }
            )
    for row in resources["notes"]:
        proof = row.get("attachment_readback") or {}
        if (
            proof.get("complete") is not True
            or row.get("leaders_complete") is not True
            or not isinstance(row.get("leaders"), list)
            or row.get("sheet") != sheet
            or proof.get("sheet") != sheet
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "note/balloon attachment ownership is incomplete",
                {"note": row.get("id")},
            )
        references = [
            None if proof.get("background") is True else proof.get("view"),
            *[leader.get("view") for leader in row["leaders"]],
        ]
        if any(view is not None and view not in known for view in references):
            raise Error("E_VERIFY_INCOMPLETE", "note attachment names an unobserved view")
        if target["name"] in references:
            affected.append({"kind": "note_or_balloon", "id": row.get("id"), "views": references})
    for row in resources["entities"]:
        if row["background"] is False and row["view_id"] == target["id"]:
            affected.append(
                {
                    "kind": "draft_entity",
                    "id": row["id"],
                    "view_id": row["view_id"],
                    "relationship": "native entity attachment",
                }
            )
    if affected:
        raise Error(
            "E_CONFLICT",
            "view has dependent views or annotations; implicit cascade is refused",
            {
                "view": target["name"],
                "affected": affected,
                "alignment_unreadable": alignment_unreadable,
                "fix": "keep the view or independently plan supported edits "
                "to the listed dependent objects",
            },
        )
    if alignment_unreadable and len(views) > 1:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "incoming alignment dependencies cannot be proved for this multi-view drawing",
            {
                "views": alignment_unreadable,
                "fix": "retain these views; this native getter failure is not "
                "proof of no alignment",
            },
        )
    for kind in ("symbols", "datums", "gtols"):
        if resources[kind]:
            raise Error(
                "E_UNSUPPORTED",
                "view removal cannot yet prove all associations of this resource kind",
                {"resource": kind},
            )
    for table in resources["tables"]:
        cells = table.get("cells")
        if (
            table.get("cell_references") != []
            or not isinstance(cells, list)
            or any(not isinstance(cell, str) or "&" in cell for line in cells for cell in line)
        ):
            raise Error(
                "E_UNSUPPORTED",
                (
                    "view removal currently allows only completely read static, unmerged "
                    "tables without model references"
                ),
                {"table": table.get("id")},
            )
    if (
        target.get("type") != "general"
        or target.get("parent") is not None
        or target.get("sections")
        or target["dependency_readback"].get("section_type") != "none"
        or target["dependency_readback"].get("background") is not False
    ):
        raise Error(
            "E_UNSUPPORTED",
            ("only an isolated, unsectioned general auxiliary view can be deleted in this profile"),
            {"view": target},
        )
    return {
        "target": target,
        "sheet": sheet,
        "affected": [],
        "policy": "no implicit cascade",
        "alignment": {
            "required": len(views) > 1,
            "unreadable": alignment_unreadable,
            "reason": "other views need readable alignment; with one inventoried view "
            "there is no other view to depend on the removed view",
        },
    }


def verify(before, intent, after):
    validate_snapshot_entities(before)
    validate_snapshot_entities(after)
    target = intent["target"]
    old, new = before["resources"], after["resources"]
    kept = [row for row in old["views"] if row["id"] != target["id"]]
    checks = [
        engine.check(
            "target_view_absent",
            not any(
                row.get("id") == target["id"] or row.get("name") == target["name"]
                for row in new["views"]
            ),
        ),
        engine.check(
            "non_target_views_unchanged",
            sorted(map(digest, kept)) == sorted(map(digest, new["views"])),
        ),
        engine.check(
            "source_part_geometry_and_properties_unchanged",
            digest(before["solid"]) == digest(after["solid"]),
        ),
        engine.check("saved_files_unchanged_by_view_removal", before["files"] == after["files"]),
    ]
    for kind in KINDS:
        if kind != "views":
            checks.append(
                engine.check(
                    "non_target_" + kind + "_unchanged",
                    sorted(map(digest, old[kind])) == sorted(map(digest, new[kind])),
                )
            )
    checks.append(
        engine.check(
            "drawing_identity_and_draft_summary_unchanged",
            {k: v for k, v in before["drawing"].items() if k != "modified"}
            == {k: v for k, v in after["drawing"].items() if k != "modified"},
        )
    )
    return {
        "level": "selected_postconditions_verified",
        "checks": checks,
        "not_checked": ["general drawing layout", "manufacturing completeness"],
    }


def plan(client, opts, name, key):
    session = engine.session(client)
    engine.require_in_session(session, name)
    before = snapshot(client, name)
    engine.store_directory(before["drawing"], session)
    matches = [
        row
        for row in before["resources"]["views"]
        if row.get("name") == key or row.get("id") == key
    ]
    if len(matches) != 1:
        raise Error(
            "E_NOT_FOUND" if not matches else "E_CONFLICT",
            "view selector must identify one native view",
            {"matched_count": len(matches)},
        )
    intent = dependencies(before, matches[0])
    target = intent["target"]

    def check(client, data):
        after = snapshot(client, name)
        proof = verify(before, intent, after)
        if engine.verification_status(proof) == "passed":
            planned.verified_observation = deepcopy(after)
        return data | {
            "independent_view_removal": {
                "target": target,
                "remaining_views": after["resources"]["views"],
                "current": after,
            }
        }, proof

    planned = engine.Plan(
        op="drawing.remove",
        request={
            "model": name,
            "item": "view:" + target["name"],
            "expected_view_id": target["id"],
            "expected_sheet": target["sheet"],
        },
        target=name,
        binding={"view_removal_before": before, "view_removal_intent": intent},
        preview={
            "model": name,
            "removes": target,
            "view_dependencies": intent,
            "effect": (
                "remove only the isolated general view; preserve all observed other "
                "resources and source part geometry; no save or implicit cascade"
            ),
            "limits": [
                "one sheet and one part source",
                "no symbol/datum/GTol association guessing",
                "static fully read unmerged tables only",
            ],
            "affected_models": [name],
        },
        verify=check,
        observe=lambda client: snapshot(client, name),
        before=before,
        arguments={"model": opts["model"], "item": opts["item"]},
    )
    return planned


def recovery(client, run):
    retained = (
        (run.get("driver_plan") or {})
        .get("base_snapshot", {})
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    before, intent = retained.get("view_removal_before"), retained.get("view_removal_intent")
    if not before or not intent:
        raise Error(
            "E_VERIFY_INCOMPLETE", "retained view deletion identity and baseline unavailable"
        )
    if client.health().get("service_instance_id") != run["driver_plan"]["target"].get(
        "instance_id"
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "new CAD instance cannot prove an old view deletion outcome"
        )
    after = snapshot(client, run["target"])
    proof = verify(before, intent, after)
    stable = digest(after) == digest(snapshot(client, run["target"]))
    proof["checks"].append(engine.check("independent_readback_stable", stable))
    accepted = all(row["passed"] for row in proof["checks"])
    unchanged = digest(before) == digest(after)
    return {
        "can_register": ["applied"]
        if accepted
        else ["not_applied"]
        if stable and unchanged
        else ["partial"]
        if stable
        else [],
        "accepted": accepted,
        "checks": proof["checks"],
        "current": after,
        "intent": intent,
        "coverage": (
            "retained selected view, complete supported resources and independent"
            " source geometry; no replay"
        ),
    }
