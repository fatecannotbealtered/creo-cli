"""Source-part cosmetic edits with explicit shared-occurrence authorization."""

from __future__ import annotations

import copy
import math
import re
from pathlib import PureWindowsPath

from . import engine, presentation
from .core import Error, digest, read_request
from .validation import strict, text, validate

RGB = {
    "type": "array",
    "items": {"type": "number", "minimum": 0, "maximum": 1},
    "minItems": 3,
    "maxItems": 3,
}
UNIT = {"type": "number", "minimum": 0, "maximum": 1}
APPEARANCE = strict(
    {
        "rgb": RGB,
        "ambient": UNIT,
        "diffuse": UNIT,
        "highlight": UNIT,
        "shininess": UNIT,
        "transparency": UNIT,
        "highlight_rgb": RGB,
        "reflection": {"type": "number", "minimum": 0, "maximum": 100},
        **{
            key: {"type": ["string", "null"], "maxLength": 4096}
            for key in ("name", "label", "description", "keywords")
        },
    },
    (
        "rgb",
        "ambient",
        "diffuse",
        "highlight",
        "shininess",
        "transparency",
        "highlight_rgb",
        "reflection",
        "name",
        "label",
        "description",
        "keywords",
    ),
)
OCCURRENCE = strict(
    {
        "assembly": text(maximum=40),
        "component_path": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": text(pattern=r"^[0-9]{1,9}$"),
        },
    },
    ("assembly", "component_path"),
)
COMMON = {
    "scope": text(enum=("source_part", "instance")),
    "source_file_authorized": {"type": "boolean", "const": True},
    "affected_occurrences": {"type": "array", "maxItems": 1000, "items": OCCURRENCE},
    "reference_action": text(enum=("preserve", "create_and_bind")),
    "reference_replacement_authorized": {"type": "boolean"},
}
SET_SCHEMA = strict(
    COMMON | {"rgb": RGB}, ("scope", "source_file_authorized", "affected_occurrences", "rgb")
)
RESTORE_SCHEMA = strict(
    COMMON | {"appearance": {"oneOf": [APPEARANCE, {"type": "null"}]}},
    ("scope", "source_file_authorized", "affected_occurrences", "appearance"),
)
SOURCE = (
    "pfcSelect.CreateModelSelection/WSelection.GetVisibleAppearance/"
    "WSolid.GetAllAppearancesAndTextures"
)
PHYSICAL_SOURCES = {
    "identity": "Model.GetFileName/GetType/GetOrigin/GetVersionStamp/GetRelationId",
    "modified": "Model.GetIsModified",
    "current_material": "Part.GetCurrentMaterial/Material.GetId/GetName",
    "loaded_materials": "Part.ListMaterials/Material.GetName",
    "body_materials": "Solid.ListItems(ITEM_BODY)/WSolidBody.GetMaterial/Material.GetId/GetName",
    "density": "Material.GetMassDensity",
    "assigned_density": "Material.GetPropertyValue(MTL_PROP_MASS_DENSITY)",
}
REFERENCE_TRANSITIONS = (
    "create_initial_binding",
    "create_and_bind",
    "preserve",
    "restore_native_default",
)


def _incomplete(message, **details):
    raise Error("E_VERIFY_INCOMPLETE", message, details)


def color_state(client, name):
    client.require_capability("source_part_appearance", 2)
    state = engine.normalize(client.op("appearance.get", {"model": name}))
    return validate_color_state(state, name)


def validate_color_state(state, name):
    if not isinstance(state, dict):
        _incomplete("complete native source appearance readback is required", model=name)
    if (
        state.get("complete") is not True
        or "appearance" not in state
        or state.get("model") != name
        or state.get("scope") != "source_part"
        or state.get("source") != SOURCE
        or type(state.get("modified")) is not bool
        or not isinstance(state.get("assignments"), list)
    ):
        _incomplete("complete native source appearance readback is required", model=name)
    if state.get("appearance") is not None:
        try:
            validate(state["appearance"], APPEARANCE, "native.appearance")
        except Error as exc:
            _incomplete("native appearance properties are incomplete", model=name, cause=exc.code)
    for row in state["assignments"]:
        if (
            not isinstance(row, dict)
            or row.get("item_type") is None
            or "item_id" not in row
            or "appearance" not in row
            or type(row.get("texture_count")) is not int
            or row["texture_count"] < 0
            or row.get("texture_inventory_complete") is not True
            or not isinstance(row.get("textures"), list)
            or len(row["textures"]) != row["texture_count"]
        ):
            _incomplete("appearance assignment inventory is incomplete", model=name)
        if row["appearance"] is not None:
            try:
                validate(row["appearance"], APPEARANCE, "native.assignment.appearance")
            except Error as exc:
                _incomplete(
                    "native assignment appearance is incomplete", model=name, cause=exc.code
                )
        for texture in row["textures"]:
            validate_texture(texture, name)
    return state


def validate_texture(value, name):
    if (
        not isinstance(value, dict)
        or value.get("complete") is not True
        or value.get("type")
        not in ("NULL_TEXTURE", "BUMP_TEXTURE", "COLOR_TEXTURE", "DECAL_TEXTURE")
        or "file_path" not in value
        or value["file_path"] is not None
        and not isinstance(value["file_path"], str)
        or "placement" not in value
    ):
        _incomplete("complete native texture slot identity and asset path are required", model=name)
    placement = value["placement"]
    if placement is None:
        return
    if (
        not isinstance(placement, dict)
        or placement.get("complete") is not True
        or not isinstance(placement.get("projection_type"), str)
        or not presentation.numbers(
            [
                placement.get(key)
                for key in (
                    "horizontal_offset",
                    "vertical_offset",
                    "rotate",
                    "horizontal_scale",
                    "vertical_scale",
                    "bump_height",
                    "decal_intensity",
                )
            ],
            7,
        )
        or type(placement.get("horizontal_flip")) is not bool
        or type(placement.get("vertical_flip")) is not bool
        or "local_transform" not in placement
    ):
        _incomplete("complete native texture placement is required", model=name)
    matrix = placement["local_transform"]
    if matrix is not None and (
        not isinstance(matrix, list)
        or len(matrix) != 4
        or not all(presentation.numbers(row, 4) for row in matrix)
    ):
        _incomplete("complete native texture local transform is required", model=name)


def source_assignment_profile(state):
    """One whole-source assignment; no item overrides or actual texture assets.

    An RGB setter can create empty native BUMP/COLOR/DECAL slots. Their complete
    type/path/placement remains recorded; slot count alone never proves empty.
    """
    validate_color_state(state, state.get("model"))
    assignments = state["assignments"]
    if len(assignments) > 1:
        return False
    for row in assignments:
        if (
            row["item_type"] != "model"
            or row["item_id"] is not None
            or not appearance_equal(row["appearance"], state["appearance"])
            or any(texture["file_path"] not in (None, "") for texture in row["textures"])
        ):
            return False
    return True


def source_context(model):
    return {"model": model["model"], "origin": model.get("origin")}


def _source_selection_observed(state, model):
    return (
        state.get("selection_model") == model["model"]
        and state.get("selection_model_type") == "part"
        and all(
            row.get("selection_model") == model["model"]
            and row.get("selection_model_type") == "part"
            for row in state["assignments"]
        )
    )


def _native_default_observed(state, model):
    """No visible model override, including a native empty model-only holder."""
    return (
        model.get("type") == "part"
        and state["appearance"] is None
        and _source_selection_observed(state, model)
        and source_assignment_profile(state)
    )


def reference_binding(state, model):
    """Describe the observed reference within this source, not a portable palette ID."""
    validate_color_state(state, model["model"])
    current = state["appearance"]
    assigned = state["assignments"]
    valid = (
        current is not None
        and isinstance(current.get("name"), str)
        and bool(current["name"].strip())
        and _source_selection_observed(state, model)
        and len(assigned) == 1
        and source_assignment_profile(state)
    )
    return {
        "source_context": source_context(model),
        "scope": "source_part",
        "selection_model": state.get("selection_model"),
        "selection_model_type": state.get("selection_model_type"),
        "native_id": current.get("name") if current is not None else None,
        "native_id_scope": "current native source/model reference; not stable across reopen",
        "appearance": copy.deepcopy(current),
        "assignments": copy.deepcopy(assigned),
        "whole_source_binding_observed": valid,
    }


def other_loaded_reference_ids(snapshot, source):
    """Collect every observable other-source ID; an unnamed reference is not proof of absence."""
    identities = set()
    for model, state in snapshot["colors"].items():
        if model == source:
            continue
        values = [state["appearance"], *(row["appearance"] for row in state["assignments"])]
        for value in values:
            if value is None:
                continue
            name = value.get("name")
            if not isinstance(name, str) or not name.strip():
                _incomplete(
                    "every loaded non-target appearance reference must have an observable ID",
                    model=model,
                )
            identities.add(name.casefold())
    return identities


def _file_identity(file, context):
    if not isinstance(file, dict) or not isinstance(context, dict):
        return False
    sha = file.get("sha256")
    path, origin, model = file.get("exact_path"), context.get("origin"), context.get("model")
    if (
        file.get("source_context") != context
        or not isinstance(sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha) is None
        or not all(isinstance(value, str) and value for value in (path, origin, model))
    ):
        return False
    exact, native = PureWindowsPath(path), PureWindowsPath(origin)
    if not exact.is_absolute() or not native.is_absolute():
        return False
    version = re.escape(model) + r"\.[1-9][0-9]*"
    if re.fullmatch(version, exact.name, re.IGNORECASE) is None:
        return False
    if re.fullmatch(version, native.name, re.IGNORECASE):
        return exact == native
    if native.name.lower() == model.lower():
        return exact.parent == native.parent
    return exact.parent == native


def _reopen_protected(value, target):
    """Validate the complete snapshot and exact dependency-file map before normalizing origins."""
    if not isinstance(value, dict):
        return None
    models, colors = value.get("models"), value.get("colors")
    geometry, affected, files = (
        value.get("geometry"),
        value.get("affected_occurrences"),
        value.get("dependency_files"),
    )
    if (
        not isinstance(models, dict)
        or target not in models
        or len(models) > 1000
        or not isinstance(colors, dict)
        or not isinstance(files, dict)
        or files.keys() != models.keys()
        or not isinstance(geometry, dict)
        or geometry.get("model") != target
        or not isinstance(geometry.get("items"), list)
        or any(not isinstance(row, dict) or "error" in row for row in geometry["items"])
        or not isinstance(affected, list)
        or not physical_complete(value, target_metadata_optional=target)
    ):
        return None
    normalized = copy.deepcopy(value)
    for name, model in models.items():
        expected_type = (
            "part"
            if isinstance(name, str) and name.lower().endswith(".prt")
            else "assembly"
            if isinstance(name, str) and name.lower().endswith(".asm")
            else None
        )
        if (
            not isinstance(model, dict)
            or model.get("model") != name
            or expected_type is None
            or model.get("type") != expected_type
            or name == target
            and expected_type != "part"
            or not {"material", "mass_properties", "bbox", "family", "units", "origin"}
            <= model.keys()
            or not isinstance(model["mass_properties"], dict)
            or not {"volume", "density"} <= model["mass_properties"].keys()
            or not isinstance(model.get("origin_readback"), dict)
            or model["origin_readback"].get("complete") is not True
            or model["origin_readback"].get("source") != "Model.GetOrigin"
            or model["origin_readback"].get("value") != model["origin"]
            or not _file_identity(files[name], source_context(model))
            or name != target
            and type(model.get("modified")) is not bool
        ):
            return None
        normalized["models"][name].pop("origin")
        normalized["models"][name].pop("origin_readback")
        if expected_type == "part":
            physical = normalized["physical_materials"][name]
            identity = physical["identity"]["value"]
            for key in ("origin", "version_stamp", "relation_id"):
                identity.pop(key, None)
            selected = physical["current_material"]["value"]
            if isinstance(selected, dict):
                selected.pop("id", None)
            for body in physical["body_materials"]["value"]:
                if isinstance(body.get("material"), dict):
                    body["material"].pop("id", None)
    try:
        if occurrences(models, target) != affected:
            return None
        expected_colors = {name for name, model in models.items() if model["type"] == "part"} - {
            target
        }
        if colors.keys() != expected_colors:
            return None
        for name, state in colors.items():
            validate_color_state(state, name)
            if state["appearance"] is not None:
                binding = reference_binding(state, models[name])
                if binding["whole_source_binding_observed"] is not True:
                    return None
                normalized["colors"][name]["appearance"].pop("name")
                normalized["colors"][name]["assignments"][0]["appearance"].pop("name")
    except (Error, KeyError, TypeError):
        return None
    normalized["dependency_files"] = {name: file["sha256"] for name, file in files.items()}
    return normalized


def reopened_binding_equal(
    saved, reopened, *, saved_file, reopened_file, saved_protected, reopened_protected
):
    """Compare complete bindings after an explicit save and exact-file reopen/copy.

    File maps contain caller-observed exact version paths, SHA-256 and native source
    contexts. This pure comparison never hashes a file or performs save/open. Every
    loaded dependency must have the same evidence; different paths require an explicit
    authorized_exact_copy_of mapping. Native-ID text alone may differ only after each
    source/assignment is independently self-consistent and all other state agrees.
    """
    if not isinstance(saved, dict) or not isinstance(reopened, dict):
        return False
    for binding, file in ((saved, saved_file), (reopened, reopened_file)):
        if (
            binding.get("scope") != "source_part"
            or binding.get("whole_source_binding_observed") is not True
            or not _file_identity(file, binding.get("source_context"))
        ):
            return False
        try:
            state = {
                "complete": True,
                "model": binding["source_context"]["model"],
                "scope": "source_part",
                "selection_model": binding.get("selection_model"),
                "selection_model_type": binding.get("selection_model_type"),
                "appearance": binding.get("appearance"),
                "assignments": binding.get("assignments"),
                "modified": False,
                "source": SOURCE,
            }
            observed = reference_binding(state, binding["source_context"])
        except (Error, KeyError, TypeError):
            return False
        if not observed["whole_source_binding_observed"] or observed["native_id"] != binding.get(
            "native_id"
        ):
            return False
    target = saved["source_context"]["model"]
    if reopened["source_context"]["model"] != target:
        return False
    left = _reopen_protected(saved_protected, target)
    right = _reopen_protected(reopened_protected, target)
    if left is None or right is None or not physical_equal(left, right):
        return False
    for primary, protected in ((saved_file, saved_protected), (reopened_file, reopened_protected)):
        if primary != protected["dependency_files"][target]:
            return False
    for name, old in saved_protected["dependency_files"].items():
        new = reopened_protected["dependency_files"][name]
        if PureWindowsPath(old["exact_path"]) != PureWindowsPath(new["exact_path"]) and (
            new.get("authorized_exact_copy_of") != old["exact_path"]
        ):
            return False
    left, right = copy.deepcopy(saved), copy.deepcopy(reopened)
    for binding in (left, right):
        binding.pop("native_id")
        binding.pop("source_context")
        binding["appearance"].pop("name")
        binding["assignments"][0]["appearance"].pop("name")
    return presentation.equivalent(left, right)


def observed_persistence(snapshot_value):
    models = snapshot_value.get("models") if isinstance(snapshot_value, dict) else None
    if not isinstance(models, dict) or not models:
        return "unknown"
    flags = [row.get("modified") if isinstance(row, dict) else None for row in models.values()]
    if any(type(flag) is not bool for flag in flags):
        return "unknown"
    return "unsaved" if any(flags) else "unchanged"


def occurrences(models, source):
    """Enumerate every path from each session assembly; names never select repeated parts."""
    rows = []

    def visit(root, name, path, stack):
        if name in stack or len(path) > 32:
            _incomplete("cyclic or excessive assembly dependency", model=name)
        current = models.get(name)
        if current is None:
            _incomplete("referenced model is absent from the complete session", model=name)
        if current.get("type") != "assembly":
            return
        components = current.get("components")
        if not isinstance(components, list):
            _incomplete("assembly component inventory is unavailable", model=name)
        ids = set()
        for component in components:
            ident, member = str(component.get("id", "")), str(component.get("model") or "").lower()
            if not ident.isdigit() or ident in ids or member not in models:
                _incomplete("component identity or source is incomplete", model=name)
            ids.add(ident)
            selected = [*path, ident]
            if member == source:
                rows.append({"assembly": root, "component_path": selected})
            if len(rows) > 1000:
                _incomplete("appearance influence inventory exceeds bounded profile")
            visit(root, member, selected, stack | {name})

    for name, model in sorted(models.items()):
        if model.get("type") == "assembly":
            visit(name, name, [], set())
    return sorted(rows, key=lambda value: (value["assembly"], value["component_path"]))


def physical_qualification(proof, model, *, target_metadata_optional=False):
    """Classify fresh native evidence; an error/null never becomes an inferred density."""
    unknown = {"complete": False, "status": "unknown", "numeric_density_qualified": False}
    if not isinstance(proof, dict) or proof.get("schema") != "part_material_physical.v1":
        return unknown | {"reason": "typed_native_material_observation_unavailable"}

    def reading(key, statuses=("value",)):
        value = proof.get(key)
        return (
            value
            if isinstance(value, dict)
            and value.get("source") == PHYSICAL_SOURCES[key]
            and value.get("status") in statuses
            and "value" in value
            else None
        )

    identity, current, loaded, bodies = (
        reading("identity"),
        reading("current_material", ("value", "unset")),
        reading("loaded_materials"),
        reading("body_materials"),
    )
    if None in (identity, current, loaded, bodies):
        return unknown | {"reason": "source_or_material_inventory_unavailable"}
    identity = identity["value"]
    expected = {"model", "type", "origin", "version_stamp", "relation_id"}
    permitted = expected - ({"version_stamp"} if target_metadata_optional else set())
    if (
        not isinstance(identity, dict)
        or not permitted <= identity.keys() <= expected
        or identity.get("model") != model.get("model")
        or identity.get("type") != "part"
        or model.get("type") != "part"
        or identity.get("origin") != model.get("origin")
        or "version_stamp" in identity
        and (not isinstance(identity["version_stamp"], str) or not identity["version_stamp"])
        or type(identity.get("relation_id")) is not int
    ):
        return unknown | {"reason": "native_source_identity_incomplete_or_inconsistent"}
    modified = reading("modified")
    if not (target_metadata_optional and "modified" not in model and "modified" not in proof) and (
        modified is None
        or type(modified["value"]) is not bool
        or modified["value"] != model.get("modified")
    ):
        return unknown | {"reason": "source_modified_observations_inconsistent"}
    names = loaded["value"]
    if (
        not isinstance(names, list)
        or len(names) > 1000
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
    ):
        return unknown | {"reason": "material_inventory_incomplete"}
    body_rows = bodies["value"]
    if (
        not isinstance(body_rows, list)
        or len(body_rows) != 1
        or not isinstance(body_rows[0], dict)
        or not isinstance(body_rows[0].get("id"), str)
        or re.fullmatch(r"-?[0-9]+", body_rows[0]["id"]) is None
    ):
        return unknown | {"reason": "single_body_material_binding_not_established"}
    model_bodies = model.get("bodies")
    if (
        not isinstance(model_bodies, list)
        or len(model_bodies) != 1
        or not isinstance(model_bodies[0], dict)
        or "error" in model_bodies[0]
        or str(model_bodies[0].get("id")) != body_rows[0]["id"]
    ):
        return unknown | {"reason": "body_identity_observations_inconsistent"}
    selected_material = current["value"]
    selected = selected_material.get("name") if isinstance(selected_material, dict) else None
    if (
        selected != model.get("material")
        or current["status"] == "value"
        and (
            not isinstance(selected, str)
            or not selected
            or selected not in names
            or selected_material.keys() != {"id", "name"}
            or not isinstance(selected_material["id"], str)
            or re.fullmatch(r"-?[0-9]+", selected_material["id"]) is None
            or body_rows[0].get("material") != selected_material
        )
        or current["status"] == "unset"
        and (selected_material is not None or names or body_rows[0].get("material") is not None)
    ):
        return unknown | {"reason": "current_material_observations_inconsistent"}
    units, observed_units = model.get("units"), proof.get("model_units")
    if (
        not isinstance(units, dict)
        or not isinstance(observed_units, dict)
        or any(
            not isinstance(units.get(key), str)
            or not units[key]
            or units[key] != observed_units.get(key)
            for key in ("length", "mass")
        )
    ):
        return unknown | {"reason": "density_model_units_unavailable_or_inconsistent"}
    density_units = units["mass"] + "/" + units["length"] + "^3"
    direct = reading("density")
    assigned = reading("assigned_density", ("value", "unset"))

    def finite_quantity(value, *, assigned_units=False):
        if not isinstance(value, dict) or value.keys() != {"value", "units"}:
            return False
        return (
            type(value["value"]) in (int, float)
            and math.isfinite(value["value"])
            and (value["units"] is None or isinstance(value["units"], str) and bool(value["units"]))
            if assigned_units
            else type(value["value"]) in (int, float)
            and math.isfinite(value["value"])
            and value["units"] == density_units
        )

    if current["status"] == "unset":
        return unknown | {"reason": "no_current_material_does_not_establish_effective_body_density"}
    if direct is not None and finite_quantity(direct["value"]):
        return {
            "complete": True,
            "status": "known_numeric",
            "numeric_density_qualified": True,
            "density_source": PHYSICAL_SOURCES["density"],
            "assigned_property_metadata_qualified": assigned is not None
            and (
                assigned["status"] == "unset"
                and assigned["value"] is None
                or assigned["status"] == "value"
                and finite_quantity(assigned["value"], assigned_units=True)
            ),
        }
    if (
        assigned is not None
        and assigned["status"] == "value"
        and finite_quantity(assigned["value"], assigned_units=True)
    ):
        return {
            "complete": True,
            "status": "known_numeric",
            "numeric_density_qualified": True,
            "density_source": PHYSICAL_SOURCES["assigned_density"],
            "native_null_units_semantics": "owning part units for this density property",
        }
    if assigned is not None and assigned["status"] == "unset" and assigned["value"] is None:
        return {
            "complete": True,
            "status": "known_unset",
            "numeric_density_qualified": False,
            "density_source": PHYSICAL_SOURCES["assigned_density"] + " returned null",
        }
    return unknown | {"reason": "no_authoritative_density_value_or_known_unset_result"}


def physical_qualifications(value, *, target_metadata_optional=None):
    models = value.get("models") if isinstance(value, dict) else None
    materials = value.get("physical_materials") if isinstance(value, dict) else None
    if (
        not isinstance(models, dict)
        or not isinstance(materials, dict)
        or any(not isinstance(model, dict) for model in models.values())
    ):
        return None
    parts = {name for name, model in models.items() if model.get("type") == "part"}
    if parts != materials.keys():
        return None
    return {
        name: physical_qualification(
            materials[name], models[name], target_metadata_optional=name == target_metadata_optional
        )
        for name in sorted(parts)
    }


def physical_complete(value, *, target_metadata_optional=None):
    qualifications = physical_qualifications(
        value, target_metadata_optional=target_metadata_optional
    )
    return bool(qualifications) and all(row["complete"] for row in qualifications.values())


def physical_equal(left, right):
    """Density/material evidence is exact; only the existing geometry comparison is tolerant."""
    if left.get("physical_materials") != right.get("physical_materials"):
        return False
    old_models, new_models = left.get("models", {}), right.get("models", {})
    if old_models.keys() != new_models.keys():
        return False
    for name, old in old_models.items():
        new = new_models[name]
        if old.get("material") != new.get("material") or (old.get("mass_properties") or {}).get(
            "density"
        ) != (new.get("mass_properties") or {}).get("density"):
            return False
    return presentation.equivalent(left, right)


def snapshot(client, name):
    from . import protected_readback

    client.require_capability("source_part_appearance", 2)
    session = engine.session(client)
    listed = session.get("models")
    if not isinstance(listed, list) or len(listed) > 1000:
        _incomplete("complete bounded session inventory is required")
    models, colors, materials, definitions = {}, {}, {}, {}
    for current in sorted(listed):
        model = engine.show(client, current)
        if type(model.get("modified")) is not bool:
            _incomplete("every related model modified flag is required", model=current)
        models[current] = model
        definitions[current] = protected_readback.definitions(client, current, model)
        if model.get("type") == "part":
            material = engine.normalize(client.op("material.list", {"name": "~", "model": current}))
            observed = material.get("model")
            if not isinstance(observed, dict) or observed.get("model") != current:
                _incomplete("independent material source identity is required", model=current)
            materials[current] = observed.get("physical_observation")
            qualification = physical_qualification(materials[current], model)
            if not qualification["complete"]:
                _incomplete(
                    "required physical observation is incomplete",
                    model=current,
                    qualification=qualification,
                )
            if qualification.get("numeric_density_qualified"):
                raise Error(
                    "E_UNSUPPORTED",
                    "numeric density preservation has not completed native qualification "
                    "for this internal trial",
                    {"model": current},
                )
            colors[current] = color_state(client, current)
            if colors[current]["modified"] != model["modified"]:
                _incomplete("source color and model modified observations disagree", model=current)
    if name not in colors:
        raise Error("E_VALIDATION", "appearance supports a source part only")
    geometry = engine.normalize(client.op("geometry.list", {"model": name}))
    if (
        geometry.get("model") != name
        or not isinstance(geometry.get("items"), list)
        or len(geometry["items"]) > 4096
        or any(not isinstance(row, dict) or "error" in row for row in geometry["items"])
    ):
        _incomplete("source geometry inventory is required")
    return {
        "models": models,
        "protected_definitions": definitions,
        "colors": colors,
        "physical_materials": materials,
        "geometry": geometry,
        "affected_occurrences": occurrences(models, name),
    }


def query(opts):
    name = engine.model_name(opts["model"], ("prt",))

    def read(client):
        state = snapshot(client, name)
        return {
            "model": name,
            "scope": "source_part",
            "appearance": state["colors"][name]["appearance"],
            "assignments": state["colors"][name]["assignments"],
            "modified": state["models"][name]["modified"],
            "reference_binding": reference_binding(state["colors"][name], state["models"][name]),
            "physical_protection": physical_qualifications(state),
            "affected_occurrences": state["affected_occurrences"],
            "influence_scope": "complete current session; unloaded external reuse not checked",
            "_untrusted": [
                "appearance",
                "assignments",
                "affected_occurrences",
                "reference_binding",
            ],
        }

    return engine.read(opts, read)


def prepare(opts, restore=False):
    name = engine.model_name(opts["model"], ("prt",))
    request = read_request(opts["request"])
    validate(request, RESTORE_SCHEMA if restore else SET_SCHEMA)
    if request["source_file_authorized"] is not True:
        raise Error("E_FORBIDDEN", "explicit owned source-file authorization is required")
    if request["scope"] != "source_part":
        raise Error(
            "E_UNSUPPORTED",
            "instance-independent appearance overrides are not supported; "
            "select and authorize the shared source part",
        )
    reference_action = request.get("reference_action", "preserve")
    authorized = request.get("reference_replacement_authorized", False)
    if reference_action == "create_and_bind" and authorized is not True:
        raise Error(
            "E_FORBIDDEN", "creating and rebinding a native reference needs explicit authorization"
        )
    if reference_action == "preserve" and authorized:
        raise Error(
            "E_VALIDATION", "reference authorization requires reference_action=create_and_bind"
        )
    if restore and request["appearance"] is None and reference_action == "create_and_bind":
        raise Error("E_VALIDATION", "restore to native default null does not create a reference")
    occurrences_requested = [
        {
            "assembly": engine.model_name(row["assembly"], ("asm",)),
            "component_path": row["component_path"],
        }
        for row in request["affected_occurrences"]
    ]
    if len({digest(row) for row in occurrences_requested}) != len(occurrences_requested):
        raise Error("E_VALIDATION", "duplicate affected occurrence authorization")
    request = request | {
        "affected_occurrences": sorted(
            occurrences_requested, key=lambda row: (row["assembly"], row["component_path"])
        )
    }
    return {"model": name, "request": request, "restore": restore}


def _physical(value, source):
    result = copy.deepcopy(value)
    result["models"][source].pop("modified", None)
    result["colors"].pop(source)
    material = result.get("physical_materials", {}).get(source)
    if isinstance(material, dict):
        material.pop("modified", None)
        identity = material.get("identity", {}).get("value")
        if isinstance(identity, dict):
            identity.pop("version_stamp", None)
    # Source appearance assignments are permitted to change; all other part colors,
    # all physical material/density/geometry/constraints and unrelated dirty flags remain protected.
    return result


def rgb_equal(left, right):
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and len(left) == len(right) == 3
        and all(
            math.isclose(a, b, rel_tol=0, abs_tol=1e-12) for a, b in zip(left, right, strict=True)
        )
    )


def appearance_equal(left, right):
    if left is None or right is None:
        return left is right
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.keys() == right.keys()
        and all(
            rgb_equal(left[key], right[key])
            if key in ("rgb", "highlight_rgb")
            else math.isclose(left[key], right[key], rel_tol=0, abs_tol=1e-12)
            if type(left[key]) in (int, float) and type(right[key]) in (int, float)
            else left[key] == right[key]
            for key in left
        )
    )


def plan(client, opts, pre):
    name, request = pre["model"], pre["request"]
    reference_action = request.get("reference_action", "preserve")
    replace_reference = reference_action == "create_and_bind"
    if replace_reference:
        if request.get("reference_replacement_authorized") is not True:
            raise Error(
                "E_FORBIDDEN", "explicit native reference creation authorization is required"
            )
        client.require_capability("source_part_appearance_reference", 1)
    before = snapshot(client, name)
    if not physical_complete(before):
        _incomplete(
            "complete independent physical material and density evidence is required "
            "before appearance mutation",
            dispatch_state="not_started",
            physical_protection=physical_qualifications(before),
        )
    family = before["models"][name].get("family") or {}
    if family.get("complete") is not True or family.get("kind") != "standalone":
        raise Error(
            "E_UNSUPPORTED", "source appearance currently requires a standalone non-family part"
        )
    session = engine.session(client)
    for current in {name, *(row["assembly"] for row in before["affected_occurrences"])}:
        engine.store_directory(before["models"][current], session)
    if request["affected_occurrences"] != before["affected_occurrences"]:
        raise Error(
            "E_FORBIDDEN",
            "source appearance affects every listed occurrence; "
            "authorization must cover the exact complete set",
            {
                "required": before["affected_occurrences"],
                "authorized": request["affected_occurrences"],
                "dispatch_state": "not_started",
            },
        )
    color_before = before["colors"][name]
    if replace_reference and (
        color_before["appearance"] is None or pre["restore"] and request["appearance"] is None
    ):
        raise Error(
            "E_UNSUPPORTED", "create_and_bind requires existing and intended non-null appearances"
        )
    if not source_assignment_profile(color_before):
        raise Error(
            "E_UNSUPPORTED", "whole-part appearance refuses face/body overrides or textures"
        )
    action = "restore" if pre["restore"] else "set"
    if (
        not replace_reference
        and color_before["appearance"] is not None
        and (
            not pre["restore"]
            and color_before["appearance"]["rgb"] != request["rgb"]
            or pre["restore"]
            and request["appearance"] is not None
            and color_before["appearance"] != request["appearance"]
        )
    ):
        raise Error(
            "E_UNSUPPORTED",
            "changing an existing appearance requires authorized reference_action=create_and_bind; "
            "preserve mode cannot guarantee native identifier preservation",
            {"dispatch_state": "not_started", "reference_action": reference_action},
        )
    old_reference = reference_binding(color_before, before["models"][name])
    restore_default = pre["restore"] and request["appearance"] is None
    initial_reference = color_before["appearance"] is None and not restore_default
    transition = (
        "create_and_bind"
        if replace_reference
        else "restore_native_default"
        if restore_default
        else "create_initial_binding"
        if initial_reference
        else "preserve"
    )
    allocates_reference = initial_reference or replace_reference
    if initial_reference or restore_default:
        client.require_capability("source_part_appearance_reference", 1)
    if allocates_reference:
        client.require_capability("source_part_appearance_unique_reference", 1)
        other_reference_ids = other_loaded_reference_ids(before, name)
    else:
        other_reference_ids = set()
    if color_before["appearance"] is None:
        if not _native_default_observed(color_before, before["models"][name]):
            _incomplete(
                "the native default must be bound to the exact source selection", model=name
            )
    elif old_reference["whole_source_binding_observed"] is not True:
        _incomplete(
            "native target selection and unique whole-source binding are required", model=name
        )
    if transition != "preserve":
        for current, state in before["colors"].items():
            if not _source_selection_observed(state, before["models"][current]):
                _incomplete(
                    "complete native selection identities for all protected sources are required",
                    model=current,
                )
    native = {
        "model": name,
        "action": action,
        "reference_action": reference_action,
        "reference_replacement_authorized": replace_reference,
        "expected_before": copy.deepcopy(color_before),
        "expected_source_context": source_context(before["models"][name]),
        **({"appearance": request["appearance"]} if pre["restore"] else {"rgb": request["rgb"]}),
    }
    if allocates_reference:
        native["reference_allocation_policy"] = "random_candidate_native_readback_v1"
    # The transition and allocation policy are part of this frozen Plan/intent;
    # the actual native ID remains unknown until independent readback.
    wire_request = copy.deepcopy(native)
    if initial_reference and pre["restore"]:
        # The recorded Name describes history, not a caller-selected future ID.
        # The Java allocation policy generates a fresh candidate instead.
        wire_request["appearance"]["name"] = ""
    native["reference_transition"] = transition

    def send_wire():
        return copy.deepcopy(wire_request)

    verified = {}
    first_verification = {"attempted": False, "reentered": False}
    first_observation = {
        "attempted": False,
        "purpose": None,
        "value": None,
        "bound": False,
        "issued": [],
    }

    def verify(c, _data):
        verified.clear()
        p.verified_observation = None
        if not same_plan(p, c):
            _incomplete("appearance verification is not bound to this Plan and Client")
        if first_verification["attempted"]:
            first_verification["reentered"] = True
            _incomplete("the first appearance verification observation cannot be replaced")
        if first_observation["attempted"] and first_observation["purpose"] != "verification":
            _incomplete(
                "a setter-failure observation cannot be promoted into successful verification"
            )
        first_verification["attempted"] = True
        after = read_first(c, "verification")
        physical_known = physical_complete(after)
        actual = after["colors"][name]["appearance"]
        actual_binding = reference_binding(after["colors"][name], after["models"][name])
        intended = request.get("appearance") if pre["restore"] else request["rgb"]
        color_ok = (
            appearance_equal(
                {k: v for k, v in actual.items() if k != "name"},
                {k: v for k, v in intended.items() if k != "name"},
            )
            if pre["restore"]
            and allocates_reference
            and actual is not None
            and intended is not None
            else appearance_equal(actual, intended)
            if pre["restore"]
            else actual is not None and rgb_equal(actual.get("rgb"), intended)
        )
        properties_ok = True
        if not pre["restore"] and color_before["appearance"] is not None and actual is not None:
            protected_properties = set(color_before["appearance"]) - {"rgb"}
            if replace_reference:
                protected_properties.remove("name")
            old = {k: color_before["appearance"][k] for k in protected_properties}
            now = {k: actual[k] for k in protected_properties}
            properties_ok = presentation.equivalent(old, now)
        same_source = (
            after["models"][name].get("type") == "part"
            and actual_binding["source_context"] == old_reference["source_context"]
        )
        reference_ok = (
            _native_default_observed(after["colors"][name], after["models"][name]) and same_source
            if restore_default
            else actual_binding["whole_source_binding_observed"]
            and same_source
            and (not replace_reference or actual_binding["native_id"] != old_reference["native_id"])
            and (allocates_reference or actual_binding["native_id"] == old_reference["native_id"])
        )
        distinct_loaded_sources = (
            not allocates_reference
            or isinstance(actual_binding["native_id"], str)
            and actual_binding["native_id"].casefold() not in other_reference_ids
        )
        checks = [
            engine.check("requested_native_appearance", color_ok),
            engine.check(
                "whole_source_assignment_without_overrides_or_texture_assets",
                source_assignment_profile(after["colors"][name]),
            ),
            engine.check(
                "non_reference_non_rgb_cosmetic_properties_preserved"
                if replace_reference
                else "initial_native_appearance_properties_observed"
                if initial_reference
                else "non_rgb_cosmetic_properties_preserved",
                properties_ok and (not initial_reference or actual is not None),
            ),
            engine.check(
                "authorized_native_reference_creation_and_source_binding"
                if replace_reference
                else "initial_native_reference_creation_and_source_binding"
                if initial_reference
                else "native_default_source_binding_restored"
                if restore_default
                else "native_reference_identity_preserved",
                reference_ok,
            ),
            engine.check(
                "complete_affected_occurrence_set_unchanged",
                before["affected_occurrences"] == after["affected_occurrences"],
            ),
            engine.check(
                "source_modified_independently_observed",
                type(after["models"][name].get("modified")) is bool,
            ),
        ]
        if allocates_reference:
            checks.append(
                engine.check(
                    "allocated_reference_distinct_from_other_loaded_sources",
                    distinct_loaded_sources,
                )
            )
        if physical_known:
            checks.insert(
                4,
                engine.check(
                    "physical_and_non_target_state_unchanged",
                    physical_equal(_physical(before, name), _physical(after, name)),
                ),
            )
        if physical_known and all(row["passed"] for row in checks):
            verified.update(copy.deepcopy(after))
            p.verified_observation = copy.deepcopy(after)
        return {
            "model": name,
            "scope": "source_part",
            "appearance": actual,
            "before_appearance": color_before["appearance"],
            "reference_action": reference_action,
            "requested_reference_action": reference_action,
            "reference_transition": transition,
            "reference_action_basis": "requested existing-reference native wire policy",
            "reference_replacement_authorized": replace_reference,
            "reference_allocation_policy": (
                "random_candidate_native_readback_v1" if allocates_reference else None
            ),
            "reference_before": old_reference,
            "reference_after": actual_binding,
            "after": after,
            "physical_protection": physical_qualifications(after),
            "affected_occurrences": after["affected_occurrences"],
            "persistence": observed_persistence(after),
            "persistence_semantics": "observed source/related-model modified flags; "
            "explicit save/reopen remains separate",
        }, {
            "level": "selected_postconditions_verified",
            **({"status": "incomplete"} if not physical_known else {}),
            "checks": checks,
            "observations": [
                {
                    "observation": "complete_independent_appearance_and_protected_state",
                    "state": after,
                }
            ],
            "not_checked": [
                *([] if physical_known else ["physical_and_non_target_state_unchanged"]),
                "unloaded_external_source_reuse",
                "visual_color_under_lighting",
                "saved_until_explicit_model_save",
            ],
        }

    p = engine.Plan(
        op="appearance." + action,
        request=native,
        target=name,
        binding=before,
        preview={
            "command": "appearance " + action,
            "model": name,
            "scope": "source_part",
            "model_footprint": sorted(
                {name, *(row["assembly"] for row in before["affected_occurrences"])}
            ),
            "affected_occurrences": before["affected_occurrences"],
            "source_file_authorized": True,
            "source_origin": before["models"][name].get("origin"),
            "reference_action": reference_action,
            "requested_reference_action": reference_action,
            "reference_transition": transition,
            "reference_action_basis": "requested existing-reference native wire policy",
            "reference_replacement_authorized": replace_reference,
            "reference_allocation_policy": (
                "random_candidate_native_readback_v1" if allocates_reference else None
            ),
            "reference_before": old_reference,
            "reference_after": {
                "native_id": None
                if allocates_reference or restore_default
                else old_reference["native_id"],
                "allocation_status": "pending_native_allocation"
                if allocates_reference
                else "no_model_override"
                if restore_default
                else "preserved",
                "source_context": source_context(before["models"][name]),
                "scope": "source_part",
            },
            "reference_semantics": (
                "create and bind the first whole-source native reference; no prior native ID "
                "exists; a random collision-resistant name candidate is generated during the "
                "setter, and the actual native ID is independently read back; "
                "any recorded restore Name is historical only and is not reused as the new ID"
                if initial_reference
                else "remove the target model override and restore native default; "
                "do not delete the shared reference object or change its other consumers"
                if restore_default
                else "restore recorded display properties; recorded Name is historical only; "
                "a fresh random name candidate is supplied and the actual native ID is read back"
                if pre["restore"] and replace_reference
                else "create and bind a new whole-source native reference using a fresh random "
                "name candidate; actual native ID is read back and the old shared object "
                "is read-only"
                if replace_reference
                else "preserve native reference identity; existing appearance changes are refused"
            ),
            "appearance_before": color_before["appearance"],
            "intent": native,
            "persistence": "source appearance becomes unsaved; explicit model save required",
            "protected": [
                "physical_material",
                "density",
                "source_geometry",
                "assembly_constraints",
                "other_part_colors",
                "non_target_modified_flags",
                "other_sources_still_using_the_old_appearance",
                "non_rgb_display_properties_except_explicitly_authorized_native_reference_identity"
                if replace_reference
                else "initial_native_reference_and_source_binding"
                if initial_reference
                else "native_default_source_binding"
                if restore_default
                else "native_reference_identity",
            ],
            "physical_protection": physical_qualifications(before),
            "not_checked": [
                "unloaded external reuse; authorization applies to owned source file "
                "and current session occurrences"
            ],
        },
        verify=verify,
        observe=lambda c: observe(c),
        before=before,
        arguments={"model": name, "request": request},
        send=send_wire,
    )
    frozen = copy.deepcopy(
        {key: getattr(p, key) for key in ("request", "binding", "preview", "arguments", "before")}
    )

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and p.target == name
            and p.op == "appearance." + action
            and p.send is send_wire
            and not getattr(c, "_native_read_pending", None)
            and not getattr(c, "_native_diagnostic_stop", None)
            and not first_verification["reentered"]
            and all(getattr(p, key) == value for key, value in frozen.items())
        )

    p._verified_observation_guard = lambda planned, c: (
        same_plan(planned, c) and bool(verified) and p.verified_observation == verified
    )

    def failure_unchanged(after):
        if (
            not same_plan(p, client)
            or not first_observation["bound"]
            or not any(after is issued for issued in first_observation["issued"])
            or after != first_observation["value"]
            or not physical_complete(first_observation["value"])
        ):
            return None
        # A failed setter has no authorized modified/version metadata changes.
        # Full exact comparison also protects density when it was already dirty.
        return before == first_observation["value"] and physical_equal(
            before, first_observation["value"]
        )

    p.failure_unchanged = failure_unchanged
    p._settled_observation = lambda planned, c: (
        copy.deepcopy(first_observation["value"])
        if same_plan(planned, c) and first_observation["bound"]
        else None
    )

    def read_first(c, purpose):
        if not same_plan(p, c):
            _incomplete("appearance observation is not bound to this Plan, Client and intent")
        if not first_observation["attempted"]:
            # Set before entering any getter: a failed first read cannot authorize B.
            first_observation["attempted"] = True
            first_observation["purpose"] = purpose
            observed = snapshot(c, name)
            first_observation["value"] = copy.deepcopy(observed)
            first_observation["bound"] = same_plan(p, c)
        if not first_observation["bound"] or first_observation["value"] is None:
            _incomplete("the first appearance observation is unavailable or unbound")
        issued = copy.deepcopy(first_observation["value"])
        first_observation["issued"].append(issued)
        return issued

    def observe(c):
        return read_first(c, "setter_failure")

    return p


def set_color(opts):
    return engine.write("appearance set", opts, prepare, plan)


def restore(opts):
    return engine.write("appearance restore", opts, lambda value: prepare(value, True), plan)
