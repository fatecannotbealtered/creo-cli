"""Controlled explode observation/receipt regressions; never Native CAD evidence."""

import json
import subprocess
import sys
from copy import copy, deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from creo_cli import driver, engine
from creo_cli.core import Error, digest
from tests.fixture import MM, Refused, World
from tests.test_commands import Base
from tests.test_round7_closeout import invoke


def seeded(world, *, existing=True, nine=False):
    for name in ("block.prt", "pin.prt"):
        model = world.part(name, MM)
        model["volume"] = 1000.0
        world.write_version(world.root, name, model)
    model = world.part("gearbox.asm", MM)
    world.make_assembly(model)
    for name in ["block.prt", *(["pin.prt"] * (9 if nine else 1))]:
        world.assembly_add(
            {"model": "gearbox.asm", "component": name, "constraints": [{"type": "default"}]}
        )
    ids = [str(row["id"]) for row in model["components"] if row["model"] == "pin.prt"]
    moves = [
        {"components": [ident], "direction": [-0.642345273086627, 0.4, 0.6538], "distance": 60}
        for ident in ids
    ]
    if existing:
        World.assembly_explode(
            world,
            {"model": "gearbox.asm", "name": "OWNED", "moves": moves, "replace": False},
        )
    model["is_exploded"] = False
    world.write_version(world.root, "gearbox.asm", model)
    world.active = "gearbox.asm"
    return {"units": "mm", "name": "OWNED", "replace": existing, "moves": moves}


def direct_plan(
    tmp_path, monkeypatch, *, existing=True, nine=False, unsaved=False, before_mutator=None
):
    from creo_cli import registry
    from creo_cli.commands import assembly

    assert registry.COMMANDS
    world = World(tmp_path)
    request = seeded(world, existing=existing, nine=nine)
    if unsaved:
        world.models["gearbox.asm"]["origin"] = None
    before = engine.normalize(world.op("model.show", {"model": "gearbox.asm"}))
    if before_mutator is not None:
        before_mutator(before)
    client = SimpleNamespace(require_capability=Mock())
    monkeypatch.setattr(engine, "session", lambda c: {"models": list(world.models)})
    monkeypatch.setattr(engine, "store_directory", lambda model, session: tmp_path)
    monkeypatch.setattr(engine, "show", lambda c, name: deepcopy(before))
    plan = assembly._plan_explode(
        client,
        {"model": "gearbox.asm", "request": "fixture-request.json"},
        {"name": "gearbox.asm", "request": request, "source": {"content": deepcopy(request)}},
    )
    report = engine.normalize(World.assembly_explode(world, deepcopy(plan.request)))
    after = engine.normalize(world.op("model.show", {"model": "gearbox.asm"}))
    reads = []

    def observe(c, name):
        reads.append((c, name))
        return deepcopy(after)

    monkeypatch.setattr(engine, "show", observe)
    return client, plan, report, before, after, reads


@pytest.mark.parametrize("existing,nine", [(False, False), (True, False), (True, True)])
def test_one_complete_first_after_read_supplies_checks_and_effects(
    tmp_path, monkeypatch, existing, nine
):
    client, plan, report, _, after, reads = direct_plan(
        tmp_path, monkeypatch, existing=existing, nine=nine
    )
    result, verification = plan.verify(client, report)
    assert result == report
    assert len(verification["checks"]) == 9
    assert all(check["passed"] for check in verification["checks"])
    effects = driver._effect_observation(plan, client)
    assert effects["complete_model_observation"] == after
    assert effects["explosion"] == next(
        row["observed"] for row in verification["observations"] if row["observation"] == "states"
    )
    assert verification["observation_sha256"] == digest(effects)
    settling_copy = plan.observe(client)
    assert settling_copy == effects
    assert len(reads) == 1
    settling_copy["physical"]["modified"] = False
    assert driver._effect_observation(plan, client)["physical"]["modified"] is True


def model_identity_fault(model, fault):
    if fault == "foreign_model_and_context":
        model["model"] = "foreign.asm"
        for key in ("target_model", "current_model", "window_model"):
            model["explosion"]["context"][key] = "foreign.asm"
        model["origin"] = str(Path(model["origin"]).parent / "foreign.asm.1")
        model["origin_readback"]["value"] = model["origin"]
    elif fault == "missing_model":
        model.pop("model")
    elif fault == "wrong_type":
        model["type"] = "part"
    elif fault == "missing_type":
        model.pop("type")
    elif fault == "foreign_origin_same_name":
        model["origin"] = str(Path(model["origin"]).parent / "foreign" / "gearbox.asm.1")
        model["origin_readback"]["value"] = model["origin"]
    elif fault == "missing_origin":
        model.pop("origin")
    elif fault == "missing_origin_readback":
        model.pop("origin_readback")
    elif fault == "unreadable_origin":
        model["origin_readback"].update(complete=False, state="unreadable")
    elif fault == "mismatched_origin_value":
        model["origin_readback"]["value"] = None
    elif fault == "unknown_origin_state":
        model["origin_readback"]["state"] = "unknown"
    elif fault == "missing_origin_value":
        model["origin_readback"].pop("value")
    elif fault == "missing_origin_source":
        model["origin_readback"].pop("source")
    elif fault == "origin_error":
        model["origin_readback"]["error"] = {"code": "E_CREO"}
    else:
        raise AssertionError(fault)


IDENTITY_FAULTS = [
    "foreign_model_and_context",
    "missing_model",
    "wrong_type",
    "missing_type",
    "missing_origin",
    "missing_origin_readback",
    "unreadable_origin",
    "mismatched_origin_value",
    "unknown_origin_state",
    "missing_origin_value",
    "missing_origin_source",
    "origin_error",
]


@pytest.mark.parametrize("fault", IDENTITY_FAULTS)
def test_initial_observation_requires_actual_target_type_and_readable_origin(
    tmp_path, monkeypatch, fault
):
    with pytest.raises(Error) as caught:
        direct_plan(
            tmp_path,
            monkeypatch,
            before_mutator=lambda model: model_identity_fault(model, fault),
        )
    assert caught.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize("fault", [*IDENTITY_FAULTS, "foreign_origin_same_name"])
def test_bad_first_after_identity_cannot_be_replaced_by_later_target_b(
    tmp_path, monkeypatch, fault
):
    client, plan, report, _, valid_b, _ = direct_plan(tmp_path, monkeypatch)
    bad_a, reads = deepcopy(valid_b), []
    model_identity_fault(bad_a, fault)

    def observe(c, name):
        reads.append(name)
        return deepcopy(bad_a if len(reads) == 1 else valid_b)

    monkeypatch.setattr(engine, "show", observe)
    with pytest.raises(Error) as caught:
        plan.verify(client, report)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    with pytest.raises(Error):
        plan.observe(client)
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert plan._settled_observation(plan, client) is None
    assert reads == ["gearbox.asm"]


def test_explicit_readable_no_origin_remains_supported(tmp_path, monkeypatch):
    client, plan, report, before, after, reads = direct_plan(tmp_path, monkeypatch, unsaved=True)
    assert before["origin"] is after["origin"] is None
    assert before["origin_readback"]["state"] == "no_origin"
    _, verification = plan.verify(client, report)
    assert all(check["passed"] for check in verification["checks"])
    assert driver._effect_observation(plan, client)["complete_model_observation"] == after
    assert len(reads) == 1


@pytest.mark.parametrize("missing", ["origin", "origin_readback", "value"])
def test_known_null_origin_cannot_be_replaced_by_missing_evidence(tmp_path, monkeypatch, missing):
    client, plan, report, _, after, _ = direct_plan(tmp_path, monkeypatch, unsaved=True)
    bad_a, reads = deepcopy(after), []
    if missing == "value":
        bad_a["origin_readback"].pop("value")
    else:
        bad_a.pop(missing)

    def observe(c, name):
        reads.append(name)
        return deepcopy(bad_a if len(reads) == 1 else after)

    monkeypatch.setattr(engine, "show", observe)
    with pytest.raises(Error) as caught:
        plan.verify(client, report)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    with pytest.raises(Error):
        plan.observe(client)
    assert plan._settled_observation(plan, client) is None
    assert reads == ["gearbox.asm"]


@pytest.mark.parametrize("unsaved", [False, True])
def test_native_origin_cannot_change_during_an_explode_setter(tmp_path, monkeypatch, unsaved):
    client, plan, report, _, after, _ = direct_plan(tmp_path, monkeypatch, unsaved=unsaved)
    bad_a, reads = deepcopy(after), []
    origin = str(tmp_path / "gearbox.asm.1") if unsaved else None
    bad_a["origin"] = origin
    bad_a["origin_readback"].update(state="saved" if unsaved else "no_origin", value=origin)

    def observe(c, name):
        reads.append(name)
        return deepcopy(bad_a if len(reads) == 1 else after)

    monkeypatch.setattr(engine, "show", observe)
    with pytest.raises(Error) as caught:
        plan.verify(client, report)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    with pytest.raises(Error):
        plan.observe(client)
    assert plan._settled_observation(plan, client) is None
    assert reads == ["gearbox.asm"]


def test_only_model_filename_is_canonicalized(tmp_path, monkeypatch):
    def uppercase_filename(model):
        model["model"] = "GEARBOX.ASM"
        for key in ("target_model", "current_model", "window_model"):
            model["explosion"]["context"][key] = "GEARBOX.ASM"

    client, plan, report, _, after, reads = direct_plan(
        tmp_path, monkeypatch, before_mutator=uppercase_filename
    )
    uppercase_filename(after)
    _, verification = plan.verify(client, report)
    assert all(check["passed"] for check in verification["checks"])
    retained = driver._effect_observation(plan, client)["complete_model_observation"]
    assert retained["model"] == "GEARBOX.ASM"
    assert retained["explosion"]["states"] == after["explosion"]["states"]
    assert len(reads) == 1


@pytest.mark.parametrize(
    "tamper",
    [
        "copy",
        "client",
        "request",
        "binding",
        "preview",
        "before",
        "arguments",
        "target",
        "op",
        "send",
        "first",
        "then",
        "apply",
        "prepare_dispatch",
        "artifacts_after",
        "persisted",
        "typed_intent",
        "observe",
        "alias",
        "checks_alias",
        "result_alias",
    ],
)
def test_observation_admission_fails_closed_for_foreign_or_mutated_authority(
    tmp_path, monkeypatch, tamper
):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    result, verification = plan.verify(client, report)
    candidate, caller = plan, client
    if tamper == "copy":
        candidate = copy(plan)
    elif tamper == "client":
        caller = Mock()
    elif tamper in {"request", "binding", "preview", "before", "arguments"}:
        getattr(plan, tamper)["controlled_mutation"] = True
    elif tamper in {"target", "op"}:
        setattr(plan, tamper, "different")
    elif tamper in {"send", "first", "then", "apply", "prepare_dispatch", "artifacts_after"}:
        setattr(plan, tamper, lambda: plan.request)
    elif tamper == "persisted":
        plan.persisted = True
    elif tamper == "typed_intent":
        plan.request["replace"] = 1
    elif tamper == "observe":
        plan.observe = lambda c: {}
    elif tamper == "alias":
        plan.verified_observation["complete_model_observation"]["modified"] = False
    elif tamper == "checks_alias":
        verification["observations"][0]["observed"]["states"][0]["moves"][0]["distance"] = 60.01
    else:
        result["normal_after"][0]["position"]["origin"][0] = 0.01
    if tamper == "op":
        # The generic driver no longer sees an explode op; its fallback reader
        # must nevertheless refuse this poisoned leaf without reading B.
        assert driver._effect_observation(candidate, caller) is None
        with pytest.raises(Error) as caught:
            candidate.observe(caller)
    else:
        with pytest.raises(Error, match="not bound") as caught:
            driver._effect_observation(candidate, caller)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert len(reads) == 1


def test_repeated_verifier_cannot_offer_a_new_after_read(tmp_path, monkeypatch):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    plan.verify(client, report)
    with pytest.raises(Error, match="cannot be replaced"):
        plan.verify(client, report)
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert len(reads) == 1


@pytest.mark.parametrize("failure", ["getter", "modified", "direction"])
def test_first_read_failure_cannot_be_replaced_by_later_valid_b(tmp_path, monkeypatch, failure):
    client, plan, report, _, after, _ = direct_plan(tmp_path, monkeypatch)
    reads = []

    def observe(c, name):
        reads.append(name)
        if len(reads) == 1:
            if failure == "getter":
                raise Error("E_NETWORK", "controlled first read failure")
            broken = deepcopy(after)
            if failure == "modified":
                broken["modified"] = None
            else:
                broken["explosion"]["states"][0]["moves"][0]["direction"] = []
            return broken
        return deepcopy(after)

    monkeypatch.setattr(engine, "show", observe)
    with pytest.raises(Error):
        plan.verify(client, report)
    with pytest.raises(Error):
        plan.observe(client)
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert reads == ["gearbox.asm"]


def test_settling_first_does_not_authorize_later_verification(tmp_path, monkeypatch):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    observed = plan.observe(client)
    assert plan.failure_unchanged(observed) is False
    assert plan.failure_unchanged(deepcopy(observed)) is None
    with pytest.raises(Error):
        plan.verify(client, report)
    assert len(reads) == 1


def test_guard_cannot_be_removed_to_restore_unverified_readback(tmp_path, monkeypatch):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    plan.verify(client, report)
    del plan._verified_observation_guard
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert len(reads) == 1


@pytest.mark.parametrize("flag", ["_native_read_pending", "_native_diagnostic_stop"])
def test_native_stop_cannot_authorize_retained_effects(tmp_path, monkeypatch, flag):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    plan.verify(client, report)
    setattr(client, flag, {"controlled": True})
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert plan._settled_observation(plan, client) is None
    assert len(reads) == 1


def test_foreign_first_verifier_never_reads_or_subsequently_replaces_a(tmp_path, monkeypatch):
    client, plan, report, _, _, reads = direct_plan(tmp_path, monkeypatch)
    with pytest.raises(Error):
        plan.verify(SimpleNamespace(), report)
    with pytest.raises(Error):
        plan.verify(client, report)
    with pytest.raises(Error):
        driver._effect_observation(plan, client)
    assert reads == []


class ExplodeReceiptHTTP(Base):
    def arguments(self):
        request = seeded(self.world)
        self.setter_calls = 0
        self.post_reads = 0
        self.armed = False
        return (
            "assembly",
            "explode",
            "apply",
            "--model",
            "gearbox.asm",
            "--request",
            self.request(request, "explode-receipt.json"),
        )

    def hook(self, mode):
        original = self.world.op

        def op(operation, request):
            target = operation == "model.show" and request.get("model") == "gearbox.asm"
            if self.armed and target:
                self.post_reads += 1
                if mode in {"read_error", "dirty_read_error"}:
                    raise Refused("E_CREO", "controlled readback failure", stage="model_show")
                if mode == "drift" and self.post_reads >= 2:
                    state = next(
                        row
                        for row in self.world.states_of(self.world.models["gearbox.asm"])
                        if row["name"] == "OWNED"
                    )
                    state["moves"][0]["distance"] = 60.01
            if operation == "assembly.explode":
                self.setter_calls += 1
                if mode in {
                    "dirty_error",
                    "unknown_error",
                    "already_dirty_error",
                    "dirty_read_error",
                }:
                    self.armed = True
                    self.world.models["gearbox.asm"]["modified"] = (
                        None if mode == "unknown_error" else True
                    )
                    raise Refused(
                        "E_CREO",
                        "controlled returned setter failure",
                        stage="assembly_explode",
                        model_state={"model": "gearbox.asm", "modified": True},
                    )
                result = original(operation, request)
                if mode == "success_unknown":
                    self.world.models["gearbox.asm"]["modified"] = None
                self.armed = True
                return result
            return original(operation, request)

        return patch.object(self.world, "op", side_effect=op)

    def test_a_b_drift_counterexample_retains_a_without_reading_b(self):
        args = self.arguments()
        with self.hook("drift"):
            pre = self.cli(*args, "--dry-run")["data"]
            answer = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        receipt = answer["receipt"]
        effect = receipt["extensions"]["creo"]["effects_readback"]["after"]
        assert self.setter_calls == self.post_reads == 1
        assert answer["status"] == "completed"
        assert len(answer["verification"]["checks"]) == 9
        assert all(check["passed"] for check in answer["verification"]["checks"])
        assert answer["verification"]["observation_sha256"] == digest(effect)
        assert effect["explosion"]["states"][0]["moves"][0]["distance"] == 60
        assert (
            effect["complete_model_observation"]["explosion"]["states"][0]["moves"][0]["distance"]
            == 60
        )

    def test_dirty_only_returned_error_is_unsaved_not_unchanged(self):
        args = self.arguments()
        with self.hook("dirty_error"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        receipt = answer["error"]["details"]["receipt"]
        assert receipt["outcome"]["persistence"] == "unsaved"
        assert self.setter_calls == self.post_reads == 1

    def test_fresh_source_cli_process_keeps_a_not_later_fixture_b(self):
        args = self.arguments()
        root = Path(__file__).resolve().parents[1]
        environment = dict(self.env)
        for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"):
            environment.pop(key, None)

        def run(*words):
            process = subprocess.run(
                [sys.executable, str(root / "cli.py"), *map(str, words), "--json", "--compact"],
                cwd=self.ws,
                env=environment,
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert process.returncode == 0, process.stderr.decode("utf-8", "replace")
            parsed = json.loads(process.stdout)
            assert parsed["ok"] is True
            return parsed["data"]

        with self.hook("drift"):
            preview = run(*args, "--dry-run")
            result = run(*args, "--confirm", preview["confirm_token"])
        observed = result["receipt"]["extensions"]["creo"]["effects_readback"]["after"]
        assert self.setter_calls == self.post_reads == 1
        assert observed["explosion"]["states"][0]["moves"][0]["distance"] == 60
        assert result["verification"]["observation_sha256"] == digest(observed)

    def test_already_dirty_returned_error_cannot_claim_unchanged_persistence(self):
        args = self.arguments()
        self.world.models["gearbox.asm"]["modified"] = True
        with self.hook("already_dirty_error"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        assert answer["error"]["details"]["receipt"]["outcome"]["persistence"] == "unsaved"
        assert self.setter_calls == self.post_reads == 1

    def test_missing_dirty_readback_is_unknown_not_unchanged(self):
        args = self.arguments()
        with self.hook("unknown_error"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        assert answer["error"]["details"]["receipt"]["outcome"]["persistence"] == "unknown"
        assert self.setter_calls == self.post_reads == 1

    def test_first_readback_failure_is_unknown_and_not_retried(self):
        args = self.arguments()
        with self.hook("read_error"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        receipt = answer["error"]["details"]["receipt"]
        assert receipt["outcome"]["change"] == "unknown"
        assert receipt["outcome"]["persistence"] == "unknown"
        assert receipt["outcome"]["verification"]["status"] != "passed"
        assert self.setter_calls == self.post_reads == 1

    def test_success_with_unreadable_modified_does_not_invent_saved_state(self):
        args = self.arguments()
        with self.hook("success_unknown"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        receipt = answer["error"]["details"]["receipt"]
        assert receipt["outcome"]["persistence"] == "unknown"
        assert receipt["outcome"]["verification"]["status"] != "passed"
        assert self.setter_calls == self.post_reads == 1

    def test_setter_and_first_readback_failures_do_not_authorize_second_read(self):
        args = self.arguments()
        with self.hook("dirty_read_error"):
            pre = self.cli(*args, "--dry-run")["data"]
            _, answer = invoke(self, *args, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False
        receipt = answer["error"]["details"]["receipt"]
        assert receipt["outcome"]["persistence"] == "unknown"
        assert receipt["outcome"]["change"] == "unknown"
        assert self.setter_calls == self.post_reads == 1
