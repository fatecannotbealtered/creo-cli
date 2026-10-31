"""Required native observations: matching failures are never preservation evidence."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from creo_cli import protected_readback as guard
from creo_cli.core import Error


def complete():
    return {
        "model": "phone.prt",
        "status": "success",
        "complete": True,
        "visible_feature_count": 1,
        "excluded_component_count": 0,
        "features": [
            {
                "id": "1",
                "type": "FEATTYPE_DATUM_PLANE",
                "definition": {
                    "status": "success",
                    "complete": True,
                    "sha256": "a" * 64,
                    "canonical_bytes": 90,
                },
            }
        ],
    }


def read(value, units=None):
    model = {
        "units": units if units is not None else {"length": "mm", "mass": "tonne"},
        "feature_count": 1,
    }
    client = SimpleNamespace(
        require_capability=lambda *args: None, op=lambda *args: deepcopy(value)
    )
    return guard.definitions(client, "phone.prt", model)


@pytest.mark.parametrize("status", ["failure", "unknown", "unsupported", "not_applicable", None])
def test_same_failed_or_unqualified_read_never_becomes_unchanged(status):
    value = complete()
    value["features"][0]["definition"] = {
        "status": status,
        "complete": False,
        "error": {"code": "E_CREO"},
    }
    for _ in range(2):
        with pytest.raises(Error, match="not successfully read"):
            read(value)


@pytest.mark.parametrize("side", ["before", "after"])
def test_one_sided_failure_and_status_change_cannot_be_compared(side):
    good, bad = complete(), complete()
    bad["features"][0]["definition"].update(status="failure", error={"code": "E_CREO"})
    read(good)
    with pytest.raises(Error):
        read(bad if side == "after" else bad)


@pytest.mark.parametrize("missing", ["sha256", "status", "complete", "canonical_bytes"])
def test_missing_required_definition_field_refuses(missing):
    value = complete()
    value["features"][0]["definition"].pop(missing)
    with pytest.raises(Error):
        read(value)


@pytest.mark.parametrize(
    "units",
    [
        {},
        {"length": None, "mass": "tonne"},
        {"length": "mm", "mass": "tonne", "error": {"code": "E_CREO"}},
    ],
)
def test_matching_units_errors_and_empty_values_refuse(units):
    with pytest.raises(Error):
        read(complete(), units)


def test_successful_full_read_can_compare_unchanged_and_detect_real_drift():
    before = read(complete())
    assert before == read(complete())
    changed = complete()
    changed["features"][0]["definition"]["sha256"] = "b" * 64
    assert before != read(changed)
    assert guard.require_units({"units": {"length": "mm", "mass": "tonne"}}) != guard.require_units(
        {"units": {"length": "inch", "mass": "tonne"}}
    )
