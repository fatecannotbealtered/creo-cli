"""Explicit native graphics context and bounded display-only operations."""

from __future__ import annotations

import copy
import itertools
import math

from . import appearance, engine, presentation
from .core import Error

SOURCE = (
    "Session.GetCurrentModel/GetCurrentWindow/GetModelWindow; Model.GetType; "
    "Window.GetModel/GetScreenTransform; ViewOwner.GetCurrentViewTransform/ListViews; "
    "WModelItem.IsHidden; Assembly.GetIsExploded"
)
ACTIVATION_DISPATCH = "UICreateMaxPriorityCommand/RunMacro fixed registered command"


def activation_identity(value, name):
    """Exact native identity, independent from window ownership or an intended name."""
    expected_type = "assembly" if name.endswith(".asm") else "part"
    if (
        not isinstance(value, dict)
        or set(value) != {"model", "type", "origin", "version_stamp", "relation_id"}
        or value.get("model") != name
        or value.get("type") != expected_type
        or not isinstance(value.get("origin"), str)
        or not value["origin"]
        or not isinstance(value.get("version_stamp"), str)
        or not value["version_stamp"]
        or type(value.get("relation_id")) is not int
        or value["relation_id"] < 0
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "activation requires complete native target name/type/origin/version/relation identity",
            {"dispatch_state": "not_started", "model": name},
        )
    return copy.deepcopy(value)


def state(client, name):
    value = engine.normalize(client.op("display.state", {"model": name}))
    if (
        value.get("complete") is not True
        or value.get("model") != name
        or value.get("source") != SOURCE
        or type(value.get("modified")) is not bool
        or type(value.get("target_active")) is not bool
        or type(value.get("context_complete")) is not bool
        or not all(
            key in value
            for key in ("current_model", "current_model_type", "window_model", "window_model_type")
        )
        or type(value.get("named_views_complete")) is not bool
        or not isinstance(value.get("named_views"), list)
        or any(not isinstance(view, str) or not view for view in value["named_views"])
        or not isinstance(value.get("component_visibility"), list)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete native display state is required")
    for row in value["component_visibility"]:
        if not str(row.get("id", "")).isdigit() or type(row.get("hidden")) is not bool:
            raise Error("E_VERIFY_INCOMPLETE", "component visibility identity is incomplete")
    ids = [row["id"] for row in value["component_visibility"]]
    if len(ids) != len(set(ids)):
        raise Error("E_VERIFY_INCOMPLETE", "duplicate occurrence visibility identity")
    if value["target_active"]:
        current = value.get("current_model")
        owner = value.get("window_model")
        expected_type = "assembly" if name.endswith(".asm") else "part"
        if (
            value["context_complete"] is not True
            or not isinstance(current, str)
            or current.lower() != name
            or not isinstance(owner, str)
            or owner.lower() != name
            or value.get("current_model_type") != expected_type
            or value.get("window_model_type") != expected_type
            or value.get("active_model") != owner
            or value.get("window") != value.get("active_window")
            or value["named_views_complete"] is not True
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "active target requires matching independent Session.GetCurrentModel "
                "and window model/type",
            )
        screen = value.get("screen") or {}
        matrix = value.get("view_transform")
        if (
            not presentation.numbers([screen.get(key) for key in ("pan_x", "pan_y", "zoom")], 3)
            or not isinstance(matrix, list)
            or len(matrix) != 4
            or not all(presentation.numbers(row, 4) for row in matrix)
            or screen["zoom"] <= 0
            or any(math.hypot(*row[:3]) <= 0 for row in matrix[:3])
        ):
            raise Error("E_VERIFY_INCOMPLETE", "target view and native screen are unreadable")
    return value


def snapshot(client, name):
    session = engine.session(client)
    models, colors = {}, {}
    if len(session["models"]) > 1000:
        raise Error("E_VERIFY_INCOMPLETE", "session exceeds the bounded display profile")
    for current in sorted(session["models"]):
        model = engine.show(client, current)
        if type(model.get("modified")) is not bool:
            raise Error(
                "E_VERIFY_INCOMPLETE", "related modified state is unreadable", {"model": current}
            )
        models[current] = model
        if model.get("type") == "part":
            colors[current] = appearance.color_state(client, current)
    return {"presentation": state(client, name), "models": models, "colors": colors}


def query(opts):
    name = engine.model_name(opts["model"], ("prt", "asm"))
    return engine.read(
        opts,
        lambda client: (
            state(client, name) | {"_untrusted": ["component_visibility", "active_model"]}
        ),
    )


def prepare(opts, action):
    name = engine.model_name(
        opts["model"], ("asm",) if action in ("visibility", "unexplode") else ("prt", "asm")
    )
    request = {"model": name}
    if action == "fit":
        margin = opts.get("margin", 0.1)
        if type(margin) not in (float, int) or not math.isfinite(margin) or not 0 <= margin <= 0.4:
            raise Error("E_VALIDATION", "margin is a finite 0..0.4 fraction on each image edge")
        request["margin"] = margin
        view = opts.get("view", "current")
        if view not in ("current", "isometric", "front", "back", "top", "bottom", "left", "right"):
            raise Error("E_VALIDATION", "unsupported fit view")
        request["view"] = view
    if action == "visibility":
        component = str(opts["component"])
        if not component.isdigit() or len(component) > 9:
            raise Error("E_VALIDATION", "component display uses an exact direct occurrence id")
        request |= {"component": component, "hidden": opts["state"] == "hidden"}
    return {"model": name, "action": action, "request": request}


def _box(value):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(presentation.numbers(point, 3) for point in value)
        and all(value[0][axis] <= value[1][axis] for axis in range(3))
    )


def activation_structure(observation):
    """Require independently complete engineering data, without requiring active display.

    Current-model/window and GetIsExploded may be unknown before activation. The
    named definitions, constraints, actual poses and bounds cannot be unknown.
    This validates copies only; the complete unrounded observation stays intact.
    """
    from .assembly_constraints import _transform

    models = observation.get("models")
    if not isinstance(models, dict) or not models:
        raise Error("E_VERIFY_INCOMPLETE", "activation protected model inventory is unreadable")

    def incomplete(message, name):
        raise Error("E_VERIFY_INCOMPLETE", message, {"model": name})

    for name, model in models.items():
        mass = model.get("mass_properties") if isinstance(model, dict) else None
        if (
            not isinstance(model, dict)
            or not isinstance(name, str)
            or model.get("model") != name
            or model.get("type") not in ("part", "assembly")
            or not name.endswith(".asm" if model.get("type") == "assembly" else ".prt")
            or type(model.get("modified")) is not bool
            or not _box(model.get("bbox"))
            or "material" not in model
            or not isinstance(mass, dict)
            or "error" in mass
            or "density" not in mass
            or (mass["density"] is not None and not presentation.numbers([mass["density"]], 1))
        ):
            incomplete("complete model identity, modified state and native bounds required", name)
        if model["type"] != "assembly":
            continue
        rows = model.get("components")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict)
            or type(row.get("id")) not in (str, int)
            or not isinstance(row.get("constraints"), list)
            or any(not isinstance(item, dict) for item in row["constraints"])
            or any(key in row for key in ("constraints_error", "placement_error", "error"))
            for row in rows
        ):
            incomplete("complete component inventory required for activation protection", name)
        seen = set()
        for row in rows:
            ident, member = str(row.get("id", "")), row.get("model")
            if (
                not ident.isdigit()
                or ident in seen
                or not isinstance(member, str)
                or member not in models
                or any(
                    type(row.get(key)) is not bool
                    for key in ("placed", "packaged", "underconstrained")
                )
                or not isinstance(row.get("status"), str)
                or not row["status"]
            ):
                incomplete(
                    "component identity, placement flags or loaded constituent is unreadable", name
                )
            seen.add(ident)
            if any(
                not isinstance(row.get(key), dict) or "error" in row[key]
                for key in ("position", "component_path_transform")
            ):
                incomplete("both independently observed native component poses are required", name)
            _transform(copy.deepcopy(row.get("position")))
            _transform(copy.deepcopy(row.get("component_path_transform")))
            for constraint in row["constraints"]:
                if (
                    not isinstance(constraint, dict)
                    or not isinstance(constraint.get("type"), str)
                    or not constraint["type"]
                    or not presentation.numbers([constraint.get("offset")], 1)
                    or constraint.get("error")
                ):
                    incomplete("constraint type, offset and reference readback required", name)
                if constraint["type"] not in ("def_placement", "fix"):
                    for key in ("assembly_reference", "component_reference"):
                        reference = constraint.get(key)
                        if not isinstance(reference, dict):
                            incomplete(
                                "complete native constraint reference identity required", name
                            )
                        path = reference.get("component_path")
                        if (
                            not isinstance(path, list)
                            or any(not str(value).isdigit() for value in path)
                            or not isinstance(reference.get("model"), str)
                            or not reference["model"]
                            or not isinstance(reference.get("item_type"), str)
                            or not reference["item_type"]
                            or type(reference.get("item_id")) not in (str, int)
                            or not str(reference["item_id"]).lstrip("-").isdigit()
                        ):
                            incomplete(
                                "complete native constraint reference identity required", name
                            )
        data, inventory = model.get("explosion"), model.get("exploded_states")
        if (
            not isinstance(data, dict)
            or data.get("complete") is not True
            or "error" in data
            or not isinstance(inventory, list)
            or not isinstance(data.get("states"), list)
            or inventory != data["states"]
            or "active_state_id" not in data
        ):
            incomplete(
                "two complete matching native explosion definition inventories required", name
            )
        ids, names, active, defaults = set(), set(), [], []
        for state_row in inventory:
            if not isinstance(state_row, dict):
                incomplete("explosion state identity is unreadable", name)
            ident = state_row.get("id")
            state_name = state_row.get("name")
            if (
                type(ident) not in (str, int)
                or not str(ident).lstrip("-").isdigit()
                or str(ident) in ids
                or not isinstance(state_name, str)
                or not state_name
                or state_name.casefold() in names
                or type(state_row.get("active")) is not bool
                or type(state_row.get("is_default")) is not bool
                or not isinstance(state_row.get("moves"), list)
                or "error" in state_row
            ):
                incomplete("complete unique explosion state identity and flags required", name)
            ids.add(str(ident))
            names.add(state_name.casefold())
            if state_row["active"]:
                active.append(str(ident))
            if state_row["is_default"]:
                defaults.append(str(ident))
            for move in state_row["moves"]:
                if (
                    not isinstance(move, dict)
                    or not isinstance(move.get("type"), str)
                    or not move["type"]
                    or not isinstance(move.get("components"), list)
                    or not move["components"]
                    or not isinstance(move.get("component_paths"), list)
                    or len(move["components"]) != len(move["component_paths"])
                    or not presentation.numbers(move.get("direction"), 3)
                    or not presentation.numbers([move.get("distance")], 1)
                    or not math.isclose(
                        math.hypot(*move["direction"]), 1, rel_tol=1e-9, abs_tol=1e-9
                    )
                    or "error" in move
                ):
                    incomplete(
                        "complete native explosion move references and unit direction required",
                        name,
                    )
                paths = set()
                for component, path in zip(
                    move["components"], move["component_paths"], strict=True
                ):
                    if (
                        not isinstance(path, list)
                        or not path
                        or any(not str(value).isdigit() for value in path)
                        or str(path[-1]) != str(component)
                        or tuple(map(str, path)) in paths
                    ):
                        incomplete("unique complete explosion component paths required", name)
                    paths.add(tuple(map(str, path)))
                    owner = model
                    for value in path:
                        found = [
                            row
                            for row in owner.get("components", [])
                            if str(row["id"]) == str(value)
                        ]
                        if len(found) != 1 or found[0]["model"] not in models:
                            incomplete(
                                "explosion path is outside the complete loaded component inventory",
                                name,
                            )
                        owner = models[found[0]["model"]]
        expected_active = active[0] if len(active) == 1 else None
        if len(active) > 1 or len(defaults) > 1 or data["active_state_id"] != expected_active:
            incomplete(
                "native active/default explosion identity disagrees with its inventory", name
            )


def _rigid_axis_frame(value):
    if not isinstance(value, dict) or not presentation.numbers(value.get("origin"), 3):
        return False
    rows = [value.get(key) for key in ("x_axis", "y_axis", "z_axis")]
    if not all(presentation.numbers(row, 3) for row in rows):
        return False
    selected = []
    for row in rows:
        axis = max(range(3), key=lambda index: abs(row[index]))
        if not math.isclose(abs(row[axis]), 1.0, rel_tol=0, abs_tol=1e-12) or any(
            abs(row[index]) > 1e-12 for index in range(3) if index != axis
        ):
            return False
        selected.append(axis)
    return len(set(selected)) == 3 and math.isclose(
        rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
        - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
        + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0]),
        1.0,
        rel_tol=0,
        abs_tol=1e-12,
    )


def unexplode_boxes(snapshot_value, name, *, required=None):
    """Check raw display bounds, then derive bounded axis-aligned normal bounds.

    The actual source-part boxes and poses remain in the original observation. No
    tolerance is increased, and neither assembly bbox is discarded unchecked.
    """
    models = snapshot_value.get("models", {})
    owner = models.get(name, {})
    explosion = presentation.explosion(owner)
    if required is None:
        required = explosion["is_exploded"]
    if not required:
        return None
    components = owner.get("components")
    unit = (owner.get("units") or {}).get("length")
    if (
        not isinstance(components, list)
        or not 1 <= len(components) <= 10
        or not unit
        or not _box(owner.get("bbox"))
    ):
        raise Error(
            "E_UNSUPPORTED",
            "unexplode bbox protection requires 1..10 direct parts "
            "with complete common-unit native bounds",
        )
    normal = presentation.normal_components(components, explosion)

    def union(rows):
        points = []
        seen = set()
        for component in rows:
            member = models.get(str(component.get("model", "")).lower(), {})
            frame, path = component.get("position"), component.get("component_path_transform")
            if (
                member.get("type") != "part"
                or not _box(member.get("bbox"))
                or (member.get("units") or {}).get("length") != unit
                or not _rigid_axis_frame(frame)
                or not _rigid_axis_frame(path)
                or not presentation.equivalent(frame, path)
                or str(component.get("id")) in seen
            ):
                raise Error(
                    "E_UNSUPPORTED",
                    "unexplode bounds require complete direct-part axis-aligned rigid poses "
                    "and matching native path transforms",
                )
            seen.add(str(component["id"]))
            for corner in itertools.product(
                *zip(member["bbox"][0], member["bbox"][1], strict=True)
            ):
                points.append(
                    [
                        frame["origin"][axis]
                        + sum(
                            corner[index] * frame[key][axis]
                            for index, key in enumerate(("x_axis", "y_axis", "z_axis"))
                        )
                        for axis in range(3)
                    ]
                )
        return [
            [aggregate(point[axis] for point in points) for axis in range(3)]
            for aggregate in (min, max)
        ]

    displayed, canonical = union(components), union(normal)
    return {
        "raw_bbox": copy.deepcopy(owner["bbox"]),
        "display_union": displayed,
        "normal_union": canonical,
        "raw_bbox_matches_display_union": presentation.equivalent(owner["bbox"], displayed),
        "source": "protected part bbox corners transformed by both matching "
        "native direct-occurrence poses",
        "limits": "1..10 same-unit direct parts, axis-aligned proper rigid frames; "
        "normal-before is derived",
    }


def physical(snapshot_value, name, action, *, project_unexplode=None):
    value = copy.deepcopy(snapshot_value)
    value.pop("presentation")
    bbox_projection = (
        unexplode_boxes(snapshot_value, name, required=project_unexplode)
        if action == "unexplode"
        else None
    )
    if bbox_projection:
        value["raw_assembly_bbox_projection_verified"] = bbox_projection[
            "raw_bbox_matches_display_union"
        ]
    for current, model in value["models"].items():
        explosion = model.get("explosion")
        if action == "unexplode" and current == name and bbox_projection:
            # Both native placement getters can include the displayed translation.
            # Compare a recorded derivation of normal positions; retain constraints,
            # axes, identities and the full source observations in the receipt.
            model["components"] = presentation.normal_components(
                model.get("components", []), presentation.explosion(model)
            )
            model["bbox"] = bbox_projection["normal_union"]
        if isinstance(explosion, dict):
            for field in ("context", "display_readback", "is_exploded"):
                explosion.pop(field, None)
        if current == name:
            model.pop("modified", None)
    return value


def plan(client, opts, pre):
    name, action, request = pre["model"], pre["action"], pre["request"]
    before = snapshot(client, name)
    bbox_before = unexplode_boxes(before, name) if action == "unexplode" else None
    if bbox_before and not bbox_before["raw_bbox_matches_display_union"]:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "raw assembly bbox does not match its complete protected part display bounds",
            {"bbox_evidence": bbox_before, "dispatch_state": "not_started"},
        )
    if name not in before["models"]:
        raise Error("E_NOT_FOUND", "target model is not in session")
    engine.store_directory(before["models"][name], engine.session(client))
    needs_activation = action == "activate" and not before["presentation"].get("target_active")
    strict_activation = False
    if action == "activate":
        try:
            client.require_capability("model_context_activation", 1)
            strict_activation = True
        except Error as exc:
            if exc.code != "E_BACKEND_UNAVAILABLE":
                raise
            if needs_activation:
                raise Error(
                    "E_UNSUPPORTED",
                    "this service lacks the registered deferred model-activation capability",
                    {
                        "reason": "runtime_mode",
                        "context": before["presentation"],
                        "required_capability": "model_context_activation 1",
                        "dispatch_state": "not_started",
                        "desktop_fallback": False,
                    },
                ) from exc
    if strict_activation:
        activation_structure(before)
        request["expected_target"] = activation_identity(
            before["presentation"].get("target_identity"), name
        )
    if action in ("fit", "visibility", "unexplode") and not before["presentation"].get(
        "target_active"
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "complete matching Session.GetCurrentModel and target window context is required; "
            "no activation fallback",
            {"context": before["presentation"], "dispatch_state": "not_started"},
        )
    if action == "fit" and request["view"] != "current":
        selected = "FRONT" if request["view"] == "isometric" else request["view"].upper()
        if before["presentation"].get("named_views_complete") is not True:
            raise Error("E_VERIFY_INCOMPLETE", "complete native named view inventory is required")
        if selected not in before["presentation"].get("named_views", []):
            raise Error(
                "E_NOT_FOUND",
                "requested saved orientation is absent",
                {"requested": selected, "available": before["presentation"]["named_views"]},
            )
    if action == "visibility" and not any(
        row["id"] == request["component"] for row in before["presentation"]["component_visibility"]
    ):
        raise Error("E_NOT_FOUND", "no direct component with that occurrence id")
    verified = {}
    settled = {}

    def verify(c, data):
        verified.clear()
        p.verified_observation = None
        after = snapshot(c, name)
        if strict_activation:
            activation_structure(after)
        bbox_after = (
            unexplode_boxes(after, name, required=bbox_before is not None)
            if action == "unexplode"
            else None
        )
        observed = after["presentation"]
        checks = [
            engine.check(
                "physical_material_geometry_constraints_and_other_colors_preserved",
                presentation.equivalent(
                    physical(before, name, action, project_unexplode=bbox_before is not None),
                    physical(after, name, action, project_unexplode=bbox_before is not None),
                ),
            ),
            engine.check(
                "modified_flag_independently_observed", type(observed.get("modified")) is bool
            ),
        ]
        if strict_activation:
            checks.append(
                engine.check(
                    "complete_activation_target_identity_preserved",
                    observed.get("target_identity") == request["expected_target"],
                )
            )
        if action in ("activate", "fit", "unexplode"):
            checks.append(
                engine.check(
                    "explicit_target_is_active",
                    observed.get("target_active") is True
                    and str(observed.get("active_model", "")).lower() == name,
                )
            )
        if needs_activation:
            expected = request["expected_target"]
            ticks = [data.get(key) for key in ("scheduled_tick", "callback_tick", "verified_tick")]
            checks.append(
                engine.check(
                    "native_activation_returned_to_creo_before_independent_context_verification",
                    data.get("activation_performed") is True
                    and data.get("already_active") is False
                    and data.get("setter_returned") is True
                    and data.get("activation_dispatch") == ACTIVATION_DISPATCH
                    and data.get("callback_returned") is True
                    and data.get("verified_after_return_to_creo") is True
                    and data.get("expected_target") == expected
                    and data.get("observed_target") == expected
                    and observed.get("target_identity") == expected
                    and all(type(tick) is int and tick >= 0 for tick in ticks)
                    and ticks[2] > ticks[0]
                    and ticks[2] > ticks[1],
                )
            )
        if action == "fit":
            fit = data.get("fit") or {}
            zoom = (observed.get("screen") or {}).get("zoom")
            refit_zoom = fit.get("refit_zoom")
            expected = (
                refit_zoom * (1 - 2 * request["margin"])
                if type(refit_zoom) in (int, float) and math.isfinite(refit_zoom)
                else math.nan
            )
            checks.append(
                engine.check(
                    "native_refit_and_requested_margin_zoom",
                    fit.get("source") == "WWindow.Refit/Window.SetScreenTransform"
                    and fit.get("margin") == request["margin"]
                    and type(zoom) in (float, int)
                    and math.isclose(zoom, expected, abs_tol=1e-12, rel_tol=1e-12),
                    native_fit=fit,
                )
            )
            matrix = observed.get("view_transform", [])
            orientation = [
                [value / math.hypot(*row[:3]) for value in row[:3]] for row in matrix[:3]
            ]
            checks.append(
                engine.check(
                    "requested_fit_view_retained_in_independent_readback",
                    fit.get("view") == request["view"]
                    and presentation.equivalent(fit.get("orientation"), orientation),
                )
            )
        if action == "unexplode" and bbox_before:
            checks.append(
                engine.check(
                    "both_raw_assembly_boxes_match_protected_part_display_projection",
                    bbox_before["raw_bbox_matches_display_union"]
                    and bbox_after["raw_bbox_matches_display_union"],
                    before=bbox_before,
                    after=bbox_after,
                )
            )
        if action == "unexplode":
            checks.append(
                engine.check(
                    "normal_non_exploded_display_read_back", observed.get("is_exploded") is False
                )
            )
        if action == "visibility":
            expected_rows = copy.deepcopy(before["presentation"]["component_visibility"])
            for row in expected_rows:
                if row["id"] == request["component"]:
                    row["hidden"] = request["hidden"]
            checks.append(
                engine.check(
                    "only_requested_occurrence_visibility_changed",
                    expected_rows == observed["component_visibility"],
                )
            )
        else:
            checks.append(
                engine.check(
                    "all_component_visibility_preserved",
                    before["presentation"]["component_visibility"]
                    == observed["component_visibility"],
                )
            )
        if all(row["passed"] for row in checks):
            verified.update(copy.deepcopy(after))
            p.verified_observation = copy.deepcopy(after)
        return {
            "model": name,
            "action": action,
            "after": after,
            "native": data,
            **(
                {"bbox_evidence": {"before": bbox_before, "after": bbox_after}}
                if bbox_before
                else {}
            ),
            "persistence": appearance.observed_persistence(after),
            "persistence_semantics": "observed model dirty flags; "
            "saved display persistence unverified",
            "saved_display_persistence_verified": False,
        }, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": [
                {"observation": "native_display_and_protected_models", "state": after}
            ],
            "not_checked": [
                "saved_display_persistence",
                "pixel_content_and_exact_visual_margin",
                *(
                    ["legacy_service_activation_structure_completeness"]
                    if action == "activate" and not strict_activation
                    else []
                ),
                *(
                    ["normal_before_positions_are_derived_not_independent_native_normal_display"]
                    if action == "unexplode"
                    else []
                ),
            ],
        }

    public = {"visibility": "component-visibility"}.get(action, action)
    p = engine.Plan(
        op="display." + action,
        request=request,
        target=name,
        binding=before,
        before=before,
        arguments={"model": name, "request": request},
        preview={
            "command": "display " + public,
            "model": name,
            "model_footprint": [name, "session:presentation"],
            "intent": request,
            "display_before": before["presentation"],
            **(
                {"activation_structure_profile": "complete_loaded_model_inventory_v1"}
                if strict_activation
                else {}
            ),
            **({"bbox_protection": bbox_before} if bbox_before else {}),
            "effect": (
                "activate the exact bound target through a fixed registered native command; "
                "return control to Creo, then independently verify current model and window"
                if needs_activation
                else "verify the already complete matching native target context"
                if action == "activate"
                else "native "
                + action
                + "; require complete existing target context; no CAD mouse/keyboard actions"
            ),
            **(
                {
                    "activation": {
                        "expected_target": request["expected_target"],
                        "dispatch": ACTIVATION_DISPATCH,
                        "target_text_in_macro": False,
                        "arbitrary_macros_or_OS_input": False,
                        "current_model_context_may_be_dismissed": True,
                        "verification": "after command callback has returned to Creo; "
                        "independent current model, target window, type and protected state",
                    }
                }
                if needs_activation
                else {}
            ),
            "persistence": (
                "owner modified flag is independently observed; hidden-state save/reopen "
                "persistence requires separate qualification"
                if action == "visibility"
                else "session display; model save and reopen are separate"
            ),
            "protected": [
                "material",
                "density",
                "geometry",
                "constraints",
                "other_colors",
                "unrelated_modified_flags",
            ],
        },
        verify=verify,
        observe=lambda c: snapshot(c, name),
        effects=["session", "change"] if action == "visibility" else ["session"],
    )
    frozen = copy.deepcopy(
        {key: getattr(p, key) for key in ("request", "binding", "preview", "arguments", "before")}
    )

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and p.target == name
            and p.op == "display." + action
            and not getattr(c, "_native_read_pending", None)
            and not getattr(c, "_native_diagnostic_stop", None)
            and all(getattr(p, key) == value for key, value in frozen.items())
        )

    p._verified_observation_guard = lambda planned, c: (
        same_plan(planned, c) and bool(verified) and p.verified_observation == verified
    )

    def failure_unchanged(after):
        if same_plan(p, client):
            settled.clear()
            settled.update(copy.deepcopy(after))
        return before == after

    p.failure_unchanged = failure_unchanged
    p._settled_observation = lambda planned, c: (
        copy.deepcopy(settled) if same_plan(planned, c) and settled else None
    )
    return p


def execute(opts, action):
    return engine.write(
        "display " + {"visibility": "component-visibility"}.get(action, action),
        opts,
        lambda value: prepare(value, action),
        plan,
    )
