"""Controlled getter observations, not native material qualification."""

from copy import deepcopy

IDENTITY = "Model.GetFileName/GetType/GetOrigin/GetVersionStamp/GetRelationId"
CURRENT = "Part.GetCurrentMaterial/Material.GetId/GetName"
LOADED = "Part.ListMaterials/Material.GetName"
DENSITY = "Material.GetMassDensity"
ASSIGNED = "Material.GetPropertyValue(MTL_PROP_MASS_DENSITY)"
MODIFIED = "Model.GetIsModified"
BODIES = "Solid.ListItems(ITEM_BODY)/WSolidBody.GetMaterial/Material.GetId/GetName"


def reading(source, value, status="value"):
    return {"source": source, "status": status, "value": value}


def physical(model, *, density=2.7e-9):
    name = model["model"]
    material = model.get("material")
    return {
        "schema": "part_material_physical.v1",
        "identity": reading(
            IDENTITY,
            {
                "model": name,
                "type": "part",
                "origin": model.get("origin"),
                "version_stamp": "fixture-stamp-1",
                "relation_id": 40 if name == "shared.prt" else 41,
            },
        ),
        **({"modified": reading(MODIFIED, model["modified"])} if "modified" in model else {}),
        "current_material": reading(
            CURRENT,
            None if material is None else {"id": "10", "name": material},
            "unset" if material is None else "value",
        ),
        "loaded_materials": reading(LOADED, [] if material is None else [material]),
        "body_materials": reading(
            BODIES,
            [{"id": "1", "material": None if material is None else {"id": "10", "name": material}}],
        ),
        "model_units": deepcopy(model["units"]),
        "density": reading(DENSITY, {"value": density, "units": "tonne/mm^3"}),
        "assigned_density": reading(ASSIGNED, {"value": density, "units": "tonne / mm^3"}),
    }


def with_physical(snapshot):
    value = deepcopy(snapshot)
    value["physical_materials"] = {
        name: physical(model) for name, model in value["models"].items() if model["type"] == "part"
    }
    return value
