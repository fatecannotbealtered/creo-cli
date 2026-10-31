"""Offline public entry/schema tests; no service, socket, CAD or operation store.

Synthetic handlers exercise actual CLI parsing/output validation. Conditional schema
claims are additionally checked by the independent full JSON Schema validator.
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator, ValidationError

from creo_cli import drawing_warnings, driver, driver_schema, registry, schemas
from creo_cli.core import Error
from creo_cli.main import main


@pytest.fixture(autouse=True)
def offline_only(monkeypatch, tmp_path):
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(tmp_path / "uncreated-state"))
    with (
        patch("socket.socket", side_effect=AssertionError("offline test opened a socket")),
        patch(
            "creo_cli.transport.Client.op",
            side_effect=AssertionError("offline test dispatched CAD"),
        ),
    ):
        yield
    assert not (tmp_path / "uncreated-state").exists()


def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = main(list(args))
    return status, json.loads(out.getvalue())


def observed_feedback():
    return drawing_warnings.feedback(
        {
            "model": "synthetic.drw",
            "origin": None,
            "modified": False,
            "sheets": [{"number": 1, "width": 100, "height": 100, "units": "mm"}],
            "views": [
                {
                    "id": "10",
                    "name": "FRONT",
                    "model": "synthetic.prt",
                    "sheet": 1,
                    "outline": [[50, 50], [60, 60]],
                }
            ],
            "tables": [],
            "notes": [{"id": "1", "sheet": 1, "box": [[20, 20], [30, 30]]}],
            "dimensions": [
                {
                    "id": "8",
                    "name": "d8",
                    "model": "synthetic.prt",
                    "view": "FRONT",
                    "sheet": 1,
                    "box": [[20, 20], [30, 30]],
                }
            ],
        }
    )


def synthetic_preview(feedback):
    """A labelled, non-dispatched plan conforming to the unchanged pinned envelope."""
    return {
        "preview": {
            "plan_id": "synthetic-plan",
            "operation_id": "synthetic-operation",
            "capability_id": "drawing-view-move",
            "authorization_scope_id": "synthetic-scope",
            "target": {
                "mode": "file",
                "engine_id": "synthetic-engine",
                "instance_id": None,
                "object_id": "synthetic.drw",
                "locator": "synthetic.drw",
            },
            "base_snapshot": {
                "id": "synthetic-snapshot",
                "source": "disk",
                "revision": "fixture",
                "observed_at": "2026-10-18T00:00:00Z",
                "dependencies": [],
            },
            "effects": ["change"],
            "level": "plan",
            "changes": [],
            "outputs": [],
            "unknowns": ["synthetic schema fixture, no CAD observation"],
            "constraints": [],
            "trial_snapshot": None,
            "can_apply": False,
            "expires_at": "2026-10-18T00:10:00Z",
            "extensions": {"creo": {"layout_feedback": feedback}},
        },
        "confirm_token": "synthetic-nonusable-token",
        "expires_at": "2026-10-18T00:10:00Z",
    }


def declared_handler(path, value):
    return patch.object(
        registry,
        "COMMANDS",
        [
            replace(c, handler=lambda _opts: deepcopy(value)) if c.path == path else c
            for c in registry.COMMANDS
        ],
    )


def test_reference_publishes_optional_extension_and_readonly_typed_feedback():
    status, result = cli("reference")
    assert status == 0
    public = result["data"]
    preview = public["schemas"]["dry_run"]["json_schema"]["properties"]["preview"]
    assert "layout_feedback" not in preview["properties"]
    typed = preview["properties"]["extensions"]["properties"]["creo"]["properties"][
        "layout_feedback"
    ]
    Draft202012Validator.check_schema(typed)
    Draft202012Validator(typed).validate(observed_feedback())
    assert typed["properties"]["whole_layout_verified"]["enum"] == [False]
    assert public["schemas"]["dry_run"]["json_schema"]["required"] == [
        "preview",
        "confirm_token",
        "expires_at",
    ]
    readonly = public["schemas"]["drawing_layout_plan"]["json_schema"]["properties"][
        "layout_feedback"
    ]
    assert readonly == typed
    assert public["runtime_migration"]["write_paths_total"] == 72
    assert public["runtime_migration"]["migrated_write_paths_count"] == len(driver.MIGRATED)


def test_reference_limits_cover_frozen_hole_v1_and_bounded_drawing_scopes():
    status, result = cli("reference")
    assert status == 0
    capabilities = result["data"]["capabilities"]
    hole = " ".join(capabilities["bounded_machining"]["feature hole"])
    for word in (
        "retained-solid-boundary-v1",
        "two identified",
        "old physical faces",
        "edges",
        "one active body",
        "bbox",
        "non-family",
        "legacy inspection",
        "historical receipts",
    ):
        assert word in hole
    assert "missing/unsupported/incomplete v1 cannot establish new applied registration" in hole
    for command in (
        "drawing view add",
        "drawing view move",
        "drawing dimension annotate",
        "drawing dimension move",
        "drawing table add",
        "drawing table move",
        "drawing bom add",
        "drawing bom balloons",
        "drawing title-block apply",
        "drawing layout plan",
        "drawing layout apply",
    ):
        text = " ".join(capabilities["bounded_drawing_edits"][command])
        for word in (
            "legacy_native_aggregate",
            "current AABB",
            "unknown sheet/units",
            "whole_layout_verified=false",
            "cross_time_protection_verified=false",
        ):
            assert word in text
    status, command = cli("reference", "--command", "drawing dimension move")
    assert status == 0
    assert any("cross_time=unverified" in x for x in command["data"]["command"]["driver"]["limits"])
    assert not any(
        "establish translation" in x for x in command["data"]["command"]["driver"]["limits"]
    )


def test_actual_main_uses_extension_location_and_preserves_pinned_plan():
    expected = observed_feedback()
    fixture = synthetic_preview(expected)
    with declared_handler("drawing view move", fixture):
        status, result = cli(
            "drawing",
            "view",
            "move",
            "--model",
            "synthetic.drw",
            "--view",
            "FRONT",
            "--x",
            "40",
            "--y",
            "40",
            "--dry-run",
        )
    assert status == 0
    actual = result["data"]
    assert "layout_feedback" not in actual["preview"]
    assert actual["preview"]["extensions"]["creo"]["layout_feedback"] == expected
    Draft202012Validator(schemas.DRY_RUN).validate(actual)
    driver_schema.validate("plan", actual["preview"])
    illegal_alias = deepcopy(actual["preview"])
    illegal_alias["layout_feedback"] = expected
    with pytest.raises(Error) as rejected:
        driver_schema.validate("plan", illegal_alias)
    assert rejected.value.code == "E_PROTOCOL"


@pytest.mark.parametrize(
    "lie",
    [
        "whole_layout_verified",
        "cross_time_protection_verified",
        "layout_coverage",
        "checked_dimension",
    ],
)
def test_actual_main_rejects_false_complete_or_checked_dimension_claim(lie):
    feedback = observed_feedback()
    if lie == "layout_coverage":
        feedback["layout_coverage"]["complete"] = True
    elif lie == "checked_dimension":
        feedback["checked"].append(
            {
                "kind": "dimensions",
                "object": "d8",
                "sheet": 1,
                "units": "mm",
                "source": "legacy",
                "predicted": False,
            }
        )
    else:
        feedback[lie] = True
    with declared_handler("drawing view move", synthetic_preview(feedback)):
        status, result = cli(
            "drawing",
            "view",
            "move",
            "--model",
            "synthetic.drw",
            "--view",
            "FRONT",
            "--x",
            "40",
            "--y",
            "40",
            "--dry-run",
        )
    assert status == 1 and result["error"]["code"] == "E_INTEGRITY"


@pytest.mark.parametrize(
    "lie",
    [
        "legacy_reliable",
        "unavailable_reliable",
        "dimension_conflict_reliable",
        "available_without_units",
    ],
)
def test_independent_full_schema_rejects_conditional_reliability_lies(lie):
    feedback = observed_feedback()
    if lie == "legacy_reliable":
        next(o for o in feedback["objects"] if o["kind"] == "dimensions")["reliable_coverage"] = (
            True
        )
    elif lie == "unavailable_reliable":
        row = next(o for o in feedback["objects"] if o["kind"] == "notes")
        row.update(candidate_available=False, reliable_coverage=True)
    elif lie == "available_without_units":
        feedback["objects"][0]["units"] = None
    else:
        feedback["conflicts"][0]["reliable_rectangles"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schemas.DRAWING_LAYOUT_FEEDBACK).validate(feedback)


def test_readonly_actual_main_returns_typed_feedback_without_future_getters():
    feedback = drawing_warnings.feedback(
        {
            "model": "synthetic.drw",
            "sheets": [{"number": 1, "units": None}],
            "notes": [{"id": "n1", "sheet": 1, "box": [[1, 1], [1, 2]]}],
        }
    )
    fixture = {
        "model": "synthetic.drw",
        "sheet": 1,
        "moves": [],
        "issues": [],
        "layout_feedback": feedback,
    }
    with declared_handler("drawing layout plan", fixture):
        status, result = cli(
            "drawing",
            "layout",
            "plan",
            "--model",
            "synthetic.drw",
            "--request",
            "unused-synthetic.json",
        )
    assert status == 0
    actual = result["data"]["layout_feedback"]
    assert actual["objects"][0]["raw_bounds"] == [[1, 1], [1, 2]]
    assert actual["objects"][0]["candidate_available"] is False
    assert any(x.get("reason") == "sheet_units_unavailable" for x in actual["not_checked"])
    Draft202012Validator(schemas.DRAWING_LAYOUT_FEEDBACK).validate(actual)
