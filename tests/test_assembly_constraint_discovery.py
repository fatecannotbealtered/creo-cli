"""Public parser and routing tests; these do not establish native constraint editing."""

from types import SimpleNamespace

import pytest

import creo_cli
from creo_cli import registry
from creo_cli.commands import resources, workflow
from creo_cli.core import Error
from creo_cli.main import parser
from tests.test_drawing_warning_contract import cli, offline_only  # noqa: F401

pytestmark = pytest.mark.usefixtures("offline_only")


@pytest.mark.parametrize("verb", ["list", "show"])
def test_editable_component_query_uses_public_parser_and_bound_reader(monkeypatch, verb):
    calls = []
    item = {
        "id": "83",
        "model": "shoe.prt",
        "selection_binding": {"owner": "fixture.asm", "occurrence_path": [83]},
        "reference_catalog": [],
        "edit_request": {"units": "mm", "constraints": []},
    }
    result = (
        {
            "model": "fixture.asm",
            "items": [item],
            "count": 1,
            "total": 1,
            "offset": 0,
            "has_more": False,
            "next_offset": 1,
            "_untrusted": ["items"],
        }
        if verb == "list"
        else {"model": "fixture.asm", "item": item}
    )

    def read(opts):
        calls.append(opts)
        return result

    module = SimpleNamespace(component_list=read, component_show=read)
    monkeypatch.setattr(creo_cli, "assembly_constraints", module, raising=False)
    args = ["assembly", "component", verb, "--model", "fixture.asm", "--editable"]
    if verb == "show":
        args += ["--item", "83"]
    code, answer = cli(*args)
    assert code == 0, answer
    assert calls[0]["editable"] is True
    assert calls[0]["model"] == "fixture.asm"
    returned = answer["data"]["items"][0] if verb == "list" else answer["data"]["item"]
    assert returned["selection_binding"] == item["selection_binding"]
    assert returned["edit_request"] == item["edit_request"]


@pytest.mark.parametrize("public", [True, False])
def test_editable_public_query_retains_raw_catalog_classification(monkeypatch, public):
    catalog = [
        {
            "model": "fixture.asm",
            "item_id": 19,
            "item_type": "ITEM_SURFACE",
            "component_path": [],
            "classification": {"public_feature": public, "source": "Feature.GetIsVisible"},
            "reference_usage": "editable" if public else "protection_only",
        }
    ]

    def read(opts):
        assert opts["editable"] is True
        return {"model": "fixture.asm", "item": {"id": "83"}, "reference_catalog": catalog}

    monkeypatch.setattr(
        creo_cli, "assembly_constraints", SimpleNamespace(component_show=read), raising=False
    )
    status, answer = cli(
        "assembly", "component", "show", "--model", "fixture.asm", "--item", "83", "--editable"
    )
    assert status == 0, answer
    assert answer["data"]["reference_catalog"] == catalog
    assert answer["data"]["reference_catalog"][0]["classification"]["public_feature"] is public


@pytest.mark.parametrize("verb", ["list", "show"])
def test_ordinary_component_query_keeps_existing_reader(monkeypatch, verb):
    calls = []

    def existing_reader(op, kind, model_kinds):
        assert (op, kind, model_kinds) == ("assembly.components", "components", ("asm",))

        def read(opts):
            calls.append(opts)
            raise Error("E_CONFLICT", "existing resource reader sentinel")

        return read

    monkeypatch.setattr(resources, "_" + verb, existing_reader)
    args = ["assembly", "component", verb, "--model", "fixture.asm"]
    if verb == "show":
        args += ["--item", "83"]
    code, answer = cli(*args)
    assert code == 6, answer
    assert calls[0]["editable"] is False
    assert answer["error"]["message"] == "existing resource reader sentinel"


def test_redefine_discovery_and_confirm_parse_without_dispatch(monkeypatch):
    code, answer = cli("reference", "--command", "assembly component redefine")
    assert code == 0, answer
    command = answer["data"]["command"]
    assert command["type"] == "write"
    assert {p["name"] for p in command["params"] if p["required"]} == {
        "model",
        "component",
        "request",
    }
    assert command["request_schema"]["type"] == "object"
    assert "assembly.redefine-constraints" in command["service_ops"]
    calls = []

    def redefine(opts):
        calls.append(opts)
        raise Error("E_CONFLICT", "redefine routing sentinel")

    monkeypatch.setattr(
        creo_cli, "assembly_constraints", SimpleNamespace(redefine=redefine), raising=False
    )
    code, answer = cli(
        "assembly",
        "component",
        "redefine",
        "--model",
        "fixture.asm",
        "--component",
        "83",
        "--request",
        "constraint set.json",
        "--confirm",
        "opaque-token",
    )
    assert code == 6, answer
    assert calls[0]["component"] == "83"
    assert calls[0]["request"] == "constraint set.json"
    assert calls[0]["confirm"] == "opaque-token"
    assert calls[0]["_command_path"] == "assembly component redefine"


@pytest.mark.parametrize("missing", ["model", "component", "request"])
def test_redefine_required_parameters_are_enforced_by_public_parser(missing):
    values = {"model": "fixture.asm", "component": "83", "request": "constraints.json"}
    args = ["assembly", "component", "redefine", "--dry-run"]
    for name, value in values.items():
        if name != missing:
            args += ["--" + name, value]
    code, answer = cli(*args)
    assert code == 2
    assert answer["error"]["details"]["problem"] == "missing_parameter"


def test_redefine_requires_explicit_preview_or_confirmation():
    code, answer = cli(
        "assembly",
        "component",
        "redefine",
        "--model",
        "fixture.asm",
        "--component",
        "83",
        "--request",
        "constraints.json",
    )
    assert code == 5
    assert answer["error"]["code"] == "E_CONFIRMATION_REQUIRED"


def test_redefine_is_explicitly_excluded_from_workflow():
    assert "assembly component redefine" in workflow.EXCLUDED
    with pytest.raises(Error, match="not dangerous"):
        workflow._steps(
            {
                "steps": [
                    {
                        "command": "assembly component redefine",
                        "args": {
                            "model": "fixture.asm",
                            "component": "83",
                            "request": {},
                        },
                    }
                ]
            }
        )


def test_component_editable_flag_defaults_false_and_is_discoverable():
    for verb in ("list", "show"):
        path = "assembly component " + verb
        described = registry.BY_PATH[path].describe()
        editable = next(p for p in described["params"] if p["name"] == "editable")
        assert editable["type"] == "boolean" and editable["default"] is False
        args = path.split() + ["--model", "fixture.asm"]
        if verb == "show":
            args += ["--item", "83"]
        assert vars(parser().parse_args(args))["editable"] is False
