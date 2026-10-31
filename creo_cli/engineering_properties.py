"""Independent model properties for the bounded material and numeric-tolerance paths."""

import math
from copy import deepcopy

from . import engine, machining
from .core import Error
from .presentation import equivalent


def snapshot(client, model):
    state = machining.snapshot(client, model)
    if state["model"].get("mass_properties", {}).get("volume") is None:
        raise Error("E_VERIFY_INCOMPLETE", "model volume is unavailable")
    if any(
        not d.get("reference") and not (d.get("tolerance") or {}).get("type")
        for d in state["dimensions"]["dimensions"]
    ):
        raise Error("E_VERIFY_INCOMPLETE", "dimension tolerance state is unreadable")
    return state


def checked_plan(
    client, plan, *, target_dimension=None, expected_density=None, material_reader=None
):
    before = snapshot(client, plan.target)
    if material_reader:
        before["material_state"] = material_reader(client, plan.target)

    def observe(c):
        state = snapshot(c, plan.target)
        if material_reader:
            state["material_state"] = material_reader(c, plan.target)
        return state

    previous = plan.verify
    plan.binding |= {"engineering_properties_before": before}
    plan.before = before
    plan.observe = observe

    def verify_state(c, data):
        result, proof = previous(c, data)
        after = observe(c)
        old_dims = {d["id"]: d for d in before["dimensions"]["dimensions"]}
        new_dims = {d["id"]: d for d in after["dimensions"]["dimensions"]}
        checks = [
            engine.check(
                "all_nominal_dimension_values_unchanged",
                set(old_dims) == set(new_dims)
                and all(
                    new_dims[k].get("value") == d.get("value")
                    and new_dims[k].get("units") == d.get("units")
                    for k, d in old_dims.items()
                ),
            ),
            engine.check(
                "native_feature_rows_unchanged", equivalent(before["features"], after["features"])
            ),
            engine.check(
                "native_feature_definitions_unchanged",
                equivalent(before["native_definitions"], after["native_definitions"]),
            ),
            engine.check(
                "solid_geometry_unchanged", equivalent(before["geometry"], after["geometry"])
            ),
            engine.check("units_unchanged", before["model"]["units"] == after["model"]["units"]),
        ]
        if plan.op != "model.set-tolerance-standard":
            checks.append(
                engine.check(
                    "unrelated_dimension_tolerances_unchanged",
                    all(
                        new_dims.get(k, {}).get("tolerance") == d.get("tolerance")
                        for k, d in old_dims.items()
                        if k != target_dimension
                    ),
                )
            )
        else:
            checks.append(
                engine.check(
                    "explicit_dimension_tolerances_unchanged",
                    all(
                        new_dims.get(k, {}).get("tolerance") == d.get("tolerance")
                        for k, d in old_dims.items()
                        if (d.get("tolerance") or {}).get("type") != "nominal"
                    ),
                )
            )
            explicit_numeric = [
                k
                for k, d in old_dims.items()
                if (d.get("tolerance") or {}).get("type") in ("plus_minus", "symmetric", "limits")
            ]
            if explicit_numeric:
                checks.append(
                    engine.check(
                        "preserved_numeric_overrides_not_table_driven",
                        all(
                            (new_dims.get(k, {}).get("numeric_tolerance_table") or {}).get(
                                "complete"
                            )
                            is True
                            and (new_dims[k].get("numeric_tolerance_table") or {}).get("assigned")
                            is False
                            for k in explicit_numeric
                        ),
                    )
                )
        if material_reader:
            state = after["material_state"]
            density = state.get("density") or {}
            mass = after["model"]["mass_properties"]
            observed = density.get("value")
            old_configuration = before["material_state"].get("configuration") or {}
            new_configuration = state.get("configuration") or {}
            assigned = state.get("assigned_density") or {}
            checks += [
                engine.check(
                    "material_directory_effectively_restored",
                    bool(old_configuration)
                    and old_configuration.get("effective_library")
                    == new_configuration.get("effective_library"),
                    before=old_configuration,
                    after=new_configuration,
                ),
                engine.check(
                    "working_directory_restored",
                    bool(old_configuration)
                    and old_configuration.get("working_directory")
                    == new_configuration.get("working_directory"),
                ),
                engine.check(
                    "assigned_density_property_readable",
                    isinstance(assigned.get("value"), (int, float))
                    and isinstance(assigned.get("units"), str)
                    and bool(assigned["units"]),
                ),
                engine.check(
                    "material_density_as_frozen",
                    isinstance(observed, (int, float))
                    and expected_density is not None
                    and math.isclose(observed, expected_density, rel_tol=1e-9, abs_tol=1e-15),
                    expected=expected_density,
                    observed=density,
                ),
                engine.check(
                    "density_units_are_model_units",
                    density.get("units")
                    == after["model"]["units"]["mass"]
                    + "/"
                    + after["model"]["units"]["length"]
                    + "^3",
                ),
                engine.check(
                    "mass_matches_independent_density_and_volume",
                    isinstance(observed, (int, float))
                    and isinstance(mass.get("mass"), (int, float))
                    and math.isclose(
                        mass["mass"], observed * mass["volume"], rel_tol=1e-8, abs_tol=1e-12
                    ),
                    mass=mass.get("mass"),
                    density=observed,
                    volume=mass.get("volume"),
                ),
            ]
            result["after"] = state
        else:
            checks.append(
                engine.check(
                    "material_and_mass_unchanged",
                    before["model"].get("material") == after["model"].get("material")
                    and equivalent(
                        before["model"]["mass_properties"], after["model"]["mass_properties"]
                    ),
                )
            )
        proof["checks"].extend(checks)
        proof.setdefault("observations", []).append(
            {
                "observation": "independent_engineering_properties",
                "observed": after,
                "independent": True,
            }
        )
        if engine.verification_status(proof) == "passed":
            plan.verified_observation = deepcopy(after)
        return result, proof

    def verify(c, data):
        with c.observation():
            return verify_state(c, data)

    plan.verify = verify
    return plan
