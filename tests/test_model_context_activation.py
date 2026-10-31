"""Public CLI/HTTP activation regressions; controlled fixture, never native CAD."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from creo_cli import operations
from tests import test_native_display_cli as presentation_tests
from tests.fixture_features import Refusal
from tests.fixture_presentation import appearance_properties
from tests.test_commands import RECT
from tests.test_features import Built
from tests.test_round7_closeout import invoke


class _ContextCase(Built):
    def solid(self, name):
        model = self.part(name)
        self.gated("feature", "extrude", "--model", name, "--request", self.request(RECT))
        return model

    def two_parts(self):
        first = self.block()
        second = self.solid("other.prt")
        for name, value in (("block.prt", first), ("other.prt", second)):
            value["presentation_owned"] = True
            self.gated("model", "save", "--model", name)
        self.world.active = "other.prt"
        return first, second

    def repeated_source(self):
        source, owner = presentation_tests.NativePresentationHTTP.repeated_source(self)
        # The new context profile requires complete native engineering structure.
        # Fixed placements retain the independent rigid poses at x=0 and x=50;
        # unlike the legacy fake align rows, they require no missing references.
        for row in owner["components"]:
            row["constraints"] = [{"type": "fix", "offset": 0.0}]
        owner["bbox"] = [[-20.0, -10.0, -10.0], [70.0, 10.0, 0.0]]
        return source, owner

    def args(self, name="block.prt"):
        return ("display", "activate", "--model", name)

    def failed_confirm(self, args, preview):
        code, output = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.assertNotEqual(code, 0, output)
        self.assertFalse(output["ok"])
        self.assertNotIn(preview["confirm_token"], json.dumps(output))
        return output["error"]


@pytest.fixture
def case():
    value = _ContextCase()
    value.setUp()
    value.world.capabilities["model_context_activation"] = 1
    try:
        yield value
    finally:
        value.doCleanups()


def assert_active(case, name):
    observed = case.cli("display", "show", "--model", name)["data"]
    assert observed["target_active"] is True
    assert observed["context_complete"] is True
    assert observed["current_model"] == observed["window_model"] == name
    assert observed["window"] == observed["active_window"]
    assert observed["current_model_type"] == observed["window_model_type"]
    return observed


def test_true_two_part_switches_have_separate_return_and_verification_phases(case):
    case.two_parts()
    before = copy.deepcopy(case.world.models)
    for name in ("block.prt", "other.prt", "block.prt"):
        data = case.gated(*case.args(name))["data"]
        native = data["result"]["native"]
        assert native["activation_performed"] is True
        assert native["already_active"] is False
        assert native["callback_returned"] is True
        assert native["verified_after_return_to_creo"] is True
        assert native["verified_tick"] > max(native["scheduled_tick"], native["callback_tick"])
        assert native["expected_target"] == native["observed_target"]
        assert native["expected_target"] == assert_active(case, name)["target_identity"]
        assert data["receipt"]["outcome"]["verification"]["status"] == "passed"
        assert data["receipt"]["outcome"]["persistence"] == "unchanged"
        assert case.world.models == before
    phases = [row["phase"] for row in case.world.context_activation_trace]
    assert phases == ["scheduled", "callback_returned", "verified_after_return"] * 3
    assert case.world.ops().count("display.activate") == 3


def test_same_process_all_close_exact_open_null_current_then_activate_and_fit(case):
    case.two_parts()
    saved = {name: value["origin"] for name, value in case.world.models.items()}
    server_identity = id(case.server)
    case.gated("model", "close", "--model", "other.prt")
    case.gated("model", "close", "--model", "block.prt")
    assert case.cli("model", "list")["data"]["items"] == []
    for name in ("block.prt", "other.prt"):
        case.gated("model", "open", "--path", saved[name])
        # The retained production defect: window exists, Session current is absent.
        case.world.native_current_model_override = None
        observed = case.cli("display", "show", "--model", name)["data"]
        assert observed["window_model"] == name
        assert observed["current_model"] is None
        assert observed["target_active"] is False
        result = case.gated(*case.args(name))["data"]
        assert result["result"]["native"]["activation_performed"] is True
        assert_active(case, name)
        fit = case.gated("display", "fit", "--model", name, "--margin", 0.1)["data"]
        assert fit["receipt"]["outcome"]["verification"]["status"] == "passed"
        assert case.world.models[name]["origin"] == saved[name]
        assert case.world.models[name]["modified"] is False
    assert id(case.server) == server_identity
    assert case.world.ops().count("display.activate") == 2


def test_new_capability_does_not_make_fit_or_other_display_actions_activate_implicitly(case):
    case.two_parts()
    before = copy.deepcopy(case.world.models)
    code, result = invoke(case, "display", "fit", "--model", "block.prt", "--dry-run")
    assert code != 0
    assert result["error"]["code"] == "E_VERIFY_INCOMPLETE"
    with pytest.raises(Refusal):
        case.world.display_fit({"model": "block.prt"})
    assert "display.activate" not in case.world.ops()
    assert case.world.active == "other.prt"
    assert case.world.models == before


def test_missing_capability_retains_legacy_pre_dispatch_refusal(case):
    case.two_parts()
    case.world.capabilities.pop("model_context_activation")
    code, output = invoke(case, *case.args(), "--dry-run")
    assert code == 2
    assert output["error"]["code"] == "E_UNSUPPORTED"
    assert output["error"]["details"]["reason"] == "runtime_mode"
    assert output["error"]["details"]["dispatch_state"] == "not_started"
    assert "display.activate" not in case.world.ops()


@pytest.mark.parametrize("field", ["model", "type", "origin", "version_stamp", "relation_id"])
def test_missing_native_target_identity_never_dispatches(case, field):
    case.two_parts()
    original = case.world.display_state

    def incomplete(q):
        result = original(q)
        result["target_identity"].pop(field)
        return result

    with patch.object(case.world, "display_state", side_effect=incomplete):
        code, output = invoke(case, *case.args(), "--dry-run")
    assert code != 0
    assert output["error"]["code"] == "E_VERIFY_INCOMPLETE"
    assert output["error"]["details"]["dispatch_state"] == "not_started"
    assert "display.activate" not in case.world.ops()


@pytest.mark.parametrize("field", ["model", "type", "origin", "version_stamp", "relation_id"])
def test_service_rejects_expected_target_gap_drift_before_native_callback(case, field):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    original = case.world.display_activate

    def tampered(q):
        q = copy.deepcopy(q)
        q["expected_target"][field] = 999 if field == "relation_id" else "unrelated"
        return original(q)

    with patch.object(case.world, "display_activate", side_effect=tampered):
        error = case.failed_confirm(case.args(), preview)
    assert error["code"] == "E_CONFLICT"
    assert case.world.active == "other.prt"
    assert not getattr(case.world, "context_activation_trace", [])
    assert case.world.ops().count("display.activate") == 1
    assert "model.save" not in case.world.ops()[-2:]


@pytest.mark.parametrize(
    "field,value",
    [
        ("activation_performed", False),
        ("already_active", True),
        ("setter_returned", False),
        ("activation_dispatch", "unqualified inline activation"),
        ("callback_returned", False),
        ("verified_after_return_to_creo", False),
        ("expected_target", {}),
        ("observed_target", {}),
        ("verified_tick", 0),
        ("scheduled_tick", True),
    ],
)
def test_valid_window_alone_cannot_replace_deferred_activation_provenance(case, field, value):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    original = case.world.display_activate

    def tampered(q):
        return original(q) | {field: value}

    with patch.object(case.world, "display_activate", side_effect=tampered):
        error = case.failed_confirm(case.args(), preview)
    receipt = error["details"]["receipt"]
    assert receipt["outcome"]["verification"]["status"] == "failed"
    assert "native_activation_returned_to_creo" in json.dumps(error)
    assert case.world.ops().count("display.activate") == 1
    assert_active(case, "block.prt")


def test_setter_return_with_still_missing_session_current_model_is_not_success(case):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    original = case.world.display_activate

    def owner_only(q):
        native = original(q)
        case.world.native_current_model_override = None
        return native

    with patch.object(case.world, "display_activate", side_effect=owner_only):
        error = case.failed_confirm(case.args(), preview)
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] == "failed"
    assert "explicit_target_is_active" in json.dumps(error)
    assert case.world.active == "block.prt"
    assert case.world.native_current_model_override is None
    assert case.world.ops().count("display.activate") == 1


@pytest.mark.parametrize(
    "kind", ["material", "density", "geometry", "constraints", "modified", "color"]
)
def test_activation_preserves_non_target_physical_constraints_colors_and_dirty_state(case, kind):
    _, owner = case.repeated_source()
    other = case.solid("other.prt")
    preview = case.cli(*case.args(), "--dry-run")["data"]
    original = case.world.display_activate

    def changed(q):
        native = original(q)
        if kind == "material":
            owner["material"] = "UNAUTHORIZED_MATERIAL"
        elif kind == "density":
            owner["density"] = 42.0
        elif kind == "geometry":
            owner["volume"] += 1.0
        elif kind == "constraints":
            owner["components"][0]["constraints"][0]["offset"] += 0.1
        elif kind == "modified":
            owner["modified"] = True
        else:
            other["cosmetic_appearance"] = appearance_properties([0.1, 0.2, 0.3])
        return native

    with patch.object(case.world, "display_activate", side_effect=changed):
        error = case.failed_confirm(case.args(), preview)
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] == "failed"
    assert "physical_material_geometry_constraints_and_other_colors_preserved" in json.dumps(error)
    assert case.world.ops().count("display.activate") == 1


def test_readback_failure_after_activation_retains_unknown_and_never_replays(case):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    setter = case.world.display_activate

    def activate_then_lose_all_context_reads(q):
        result = setter(q)
        case.world.fail = (
            "display.state",
            {"code": "E_CREO", "message": "controlled persistent readback loss"},
        )
        return result

    with patch.object(
        case.world, "display_activate", side_effect=activate_then_lose_all_context_reads
    ):
        error = case.failed_confirm(case.args(), preview)
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert error["details"]["receipt"]["outcome"]["persistence"] == "unknown"
    assert case.world.ops().count("display.activate") == 1


def test_transient_read_error_keeps_failed_verification_with_independent_clean_settle(case):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    case.world.then_fail = (
        "display.activate",
        "display.state",
        {"code": "E_CREO", "message": "controlled readback loss"},
    )
    error = case.failed_confirm(case.args(), preview)
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert error["details"]["receipt"]["outcome"]["persistence"] == "unchanged"
    assert case.world.ops().count("display.activate") == 1


def test_scope_changed_confirmation_is_terminal_attempt_and_preserves_original_plan(case):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    operation_id = preview["preview"]["operation_id"]
    scope = Path(case.env["CREO_CLI_SCOPE_FILE"])
    document = json.loads(scope.read_text(encoding="utf-8"))
    scope.write_text(json.dumps(document | {"revoked": True}), encoding="utf-8")
    error = case.failed_confirm(case.args(), preview)
    assert error["code"] == "E_CONFLICT"
    details = error["details"]
    assert details["conflict"] == "scope_changed"
    assert details["changed"] == ["driver_scope_sha256"]
    assert details["dispatch_state"] == "not_started"
    fields = details["binding_difference"]["fields"]
    field = next(row for row in fields if row["field"] == "driver_scope_sha256")
    assert field["expected"] != field["actual"]
    assert field["category"]
    assert "display.activate" not in case.world.ops()
    with patch.dict(os.environ, case.env, clear=True):
        attempts = operations.confirmation_attempts(operation_id)
        planned = operations.get(operation_id)
    assert len(attempts) == 1
    assert attempts[0]["terminal"] is True
    assert attempts[0]["status"] == "rejected_before_dispatch"
    assert attempts[0]["dispatch_state"] == "not_started"
    assert planned["status"] == "planned"
    assert planned["started_at"] is None
    assert planned["driver_receipt"] is None


@pytest.mark.parametrize("fault", ["window", "current_type", "window_type", "target_identity"])
def test_independent_post_activation_context_mismatch_never_passes(case, fault):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    setter = case.world.display_activate
    getter = case.world.display_state
    dispatched = False

    def activate(q):
        nonlocal dispatched
        result = setter(q)
        dispatched = True
        return result

    def contradictory(q):
        result = getter(q)
        if dispatched:
            if fault == "window":
                result["active_window"] = "unrelated-window"
            elif fault == "target_identity":
                result["target_identity"]["origin"] = str(case.ws / "other.prt.2")
            else:
                result["current_model_type" if fault == "current_type" else "window_model_type"] = (
                    "assembly"
                )
        return result

    with (
        patch.object(case.world, "display_activate", side_effect=activate),
        patch.object(case.world, "display_state", side_effect=contradictory),
    ):
        error = case.failed_confirm(case.args(), preview)
    assert error["details"]["receipt"]["outcome"]["verification"]["status"] != "passed"
    assert case.world.ops().count("display.activate") == 1


def test_target_origin_drift_after_schedule_prevents_native_callback(case):
    first, _ = case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]

    def drift(phase, q):
        if phase == "scheduled":
            first["origin"] = case.world.models["other.prt"]["origin"]

    case.world.context_activation_hook = drift
    error = case.failed_confirm(case.args(), preview)
    assert error["code"] == "E_CONFLICT"
    assert [row["phase"] for row in case.world.context_activation_trace] == ["scheduled"]
    assert case.world.active == "other.prt"
    assert case.world.ops().count("display.activate") == 1


def test_started_activation_timeout_retains_unknown_without_automatic_retry(case):
    case.two_parts()
    preview = case.cli(*case.args(), "--dry-run")["data"]
    case.world.overrun = "display.activate"
    error = case.failed_confirm(case.args(), preview)
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    assert error["details"]["operation_id"] == preview["preview"]["operation_id"]
    assert case.world.ops().count("display.activate") == 1
    with patch.dict(os.environ, case.env, clear=True):
        record = operations.get(preview["preview"]["operation_id"])
    assert record["status"] == "unknown"
    assert record["finished_at"] is not None


def test_assembly_switch_then_fit_visibility_unexplode_and_render_use_explicit_context(case):
    _, owner = case.repeated_source()
    owner["bbox"] = [[-20.0, -10.0, -10.0], [70.0, 10.0, 0.0]]
    for name in ("block.prt", "holdout.asm"):
        result = case.gated(*case.args(name))["data"]
        assert result["result"]["native"]["activation_performed"] is True
        assert_active(case, name)
    case.gated("display", "fit", "--model", "holdout.asm", "--view", "back", "--margin", 0.1)
    for state in ("hidden", "visible"):
        case.gated(
            "display",
            "component-visibility",
            "--model",
            "holdout.asm",
            "--component",
            "40",
            "--state",
            state,
        )
    unexploded = case.gated("display", "unexplode", "--model", "holdout.asm")["data"]
    assert unexploded["receipt"]["outcome"]["verification"]["status"] == "passed"
    image = case.gated(
        "artifact",
        "render",
        "--model",
        "holdout.asm",
        "--view",
        "current",
        "--output",
        "controlled-context.jpg",
    )["data"]
    assert image["result"]["published"] is True
    assert "not a native image" in image["result"]["decoded"]["source"]
    assert case.world.ops().count("display.activate") == 2
    assert_active(case, "holdout.asm")
