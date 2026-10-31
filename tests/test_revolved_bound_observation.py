"""No CAD: construction observations cannot cross their Plan, Client or intent."""

from copy import copy, deepcopy
from types import SimpleNamespace

import pytest

from creo_cli import building, driver, engine, revolved
from creo_cli.core import Error


@pytest.mark.parametrize(
    "tamper",
    [
        "other_client",
        "copied_plan",
        "request",
        "intent",
        "numeric_type",
        "observation",
        "target",
        "missing_guard",
        "repeated_verifier",
        "foreign_verifier",
    ],
)
def test_verified_construction_observation_is_bound(monkeypatch, tamper):
    old = {"id": "10", "name": "BASE", "type": "FEATTYPE_DATUM_PLANE", "status": "FEAT_ACTIVE"}
    new = {"id": "1", "name": "AUTO1", "type": "FEATTYPE_DATUM_PLANE", "status": "FEAT_ACTIVE"}
    units = {"length": "mm"}
    before = {"state": "before", "features": [old], "model": {"units": units}}
    after = {
        "state": "after",
        "nested": {"value": 7},
        "features": [old, new],
        "model": {"units": units},
    }
    observations = [deepcopy(before), deepcopy(after)]
    monkeypatch.setattr(revolved, "snapshot", lambda client, model: observations.pop(0))
    monkeypatch.setattr(
        revolved, "datum_intent", lambda op, request, state: {"distance": request["distance"]}
    )
    monkeypatch.setattr(
        revolved,
        "verify_geometry",
        lambda *args: (
            {},
            {"checks": [{"check": "controlled", "passed": True}], "observations": []},
        ),
    )
    client = SimpleNamespace(require_capability=lambda *args: None)
    request = {"distance": 4.0}
    name_intent = building.feature_name_intent({})
    earlier_checks = building.feature_readback_checks(
        [old], [old, new], "1", "FEATTYPE_DATUM_PLANE", name_intent
    )
    earlier_checks += [
        engine.check("existing_features_unchanged", True),
        engine.check("units_unchanged", True),
    ]
    plan = SimpleNamespace(
        op="feature.datum-plane",
        target="part.prt",
        request={"distance": 4.0},
        binding={"features": [old], "name_intent": name_intent},
        preview={},
        arguments={"model": "part.prt"},
        before=deepcopy(before),
        verify=lambda c, data: (
            {},
            {
                "checks": deepcopy(earlier_checks),
                "observations": [{"observation": "new_features", "features": [deepcopy(new)]}],
            },
        ),
    )
    plan = revolved.checked_plan(client, plan, request)
    plan.verify(client, {"feature": {"id": 1}})
    assert driver._effect_observation(plan, client) == after

    chosen_plan, chosen_client = plan, client
    if tamper == "other_client":
        chosen_client = SimpleNamespace()
    elif tamper == "copied_plan":
        chosen_plan = copy(plan)
    elif tamper == "request":
        request["distance"] = 5.0
    elif tamper == "intent":
        plan.binding["construction_intent"]["distance"] = 5.0
    elif tamper == "numeric_type":
        plan.binding["construction_intent"]["distance"] = 4
    elif tamper == "observation":
        plan.verified_observation["nested"]["value"] = 8
    elif tamper == "target":
        plan.target = "other.prt"
    elif tamper == "missing_guard":
        del plan._verified_observation_guard
    elif tamper in ("repeated_verifier", "foreign_verifier"):
        with pytest.raises(Error) as repeated:
            plan.verify(
                client if tamper == "repeated_verifier" else SimpleNamespace(),
                {"feature": {"id": 1}},
            )
        assert repeated.value.code == "E_VERIFY_INCOMPLETE"

    with pytest.raises(Error) as error:
        driver._effect_observation(chosen_plan, chosen_client)
    assert error.value.code == "E_VERIFY_INCOMPLETE"
