"""Public CLI + loopback fixture; controlled process identities, no CAD or OS queries."""

import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from creo_cli import driver, main, operations
from creo_cli import owned_exit as ex
from creo_cli.core import digest
from tests.fixture import Server, World
from tests.test_owned_exit_internal_policy import internal as _internal_fixture
from tests.test_owned_session_exit import world as _world_fixture

world, internal = _world_fixture, _internal_fixture
ALL_RUNS = operations.selected_runs


@pytest.fixture
def public_exit(internal, tmp_path, monkeypatch):
    monkeypatch.setattr(operations, "selected_runs", ALL_RUNS)
    changes, samples, plans = {}, [], []
    original_handle, original_plan = internal["handle"], ex.plan

    class Handle(original_handle):
        def observe(self):
            value = super().observe() | {
                "image_source": "QueryFullProcessImageNameW on same held handle while alive",
                "image_verified_at_utc": f"2026-10-27T01:00:{len(samples):02d}.123456Z",
                "exit_filetime": None if self.alive else "99999",
                "source": "controlled same held process observation",
                "nested": {"image_verified_at_utc": "protected nested state"},
            }
            value.update(copy.deepcopy(changes))
            samples.append(copy.deepcopy(value))
            return value

    monkeypatch.setattr(ex, "ProcessHandle", Handle)

    def record_plan(*args):
        value = original_plan(*args)
        plans.append(value)
        return value

    monkeypatch.setattr(ex, "plan", record_plan)
    http_root = tmp_path / "http-fixture"
    http_root.mkdir()

    class ExitWorld(World):
        def __init__(self):
            super().__init__(http_root)
            self.capabilities["owned_session_exit"] = 1
            self.raw_empty = copy.deepcopy(internal["client"].state)
            self.raw_empty["units"] = {"length": "mm"}
            self.exit_failure = False

        def op(self, name, request):
            if name == "session.exit-state":
                return copy.deepcopy(self.raw_empty)
            if name != "session.exit":
                return super().op(name, request)
            if self.exit_failure:
                return {"status": "incomplete_acknowledgement"}
            op = request["operation_id"]
            common = {
                "operation_id": op,
                "service_instance_id": internal["launch"]["runtime_pin"]["service_instance_id"],
                "native_pid": 321,
                "native_creation_filetime": "12345",
                "entrypoint": ex.ENTRYPOINT,
                "raw_java_empty_checked": True,
                "native_known_types_empty": True,
                "empty_models": True,
                "native_type_count": 11,
            }
            ex._new_json(
                internal["runtime"] / f"owned-exit-{op}.entered.json",
                common | {"status": "native_entered"},
            )
            ex._new_json(
                internal["runtime"] / f"owned-exit-{op}.returned.json",
                common | {"status": "native_returned", "api_called": True, "native_return_code": 0},
            )
            Handle.alive = False
            return {"status": "request_scheduled", "operation_id": op}

    fixture = ExitWorld()
    server = Server(fixture)
    token = tmp_path / "service-token"
    token.write_text(fixture.token, encoding="ascii")
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "scope_id": "controlled-owned-exit",
                "tool": "creo-cli",
                "granted_by": "test-fixture",
                "granted_at": "2026-10-07T00:00:00Z",
                "expires_at": None,
                "effects": ["observe", "session"],
                "dangerous": True,
                "roots": [str(tmp_path)],
                "outputs": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )
    for key, value in {
        "CREO_CLI_CONFIG_DIR": str(tmp_path / "isolated-history"),
        "CREO_CLI_SERVICE_URL": server.url,
        "CREO_CLI_SERVICE_TOKEN_FILE": str(token),
        "CREO_CLI_SCOPE_FILE": str(scope),
        "CREO_CLI_PERMISSION": "write",
        "CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "1",
    }.items():
        monkeypatch.setenv(key, value)

    def cli(*args, status=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            returned = main.main([str(value) for value in args] + ["--json", "--compact"])
        value = json.loads(stdout.getvalue())
        assert returned == status, value
        assert fixture.token not in stdout.getvalue() + stderr.getvalue()
        return value

    args = ("session", "exit", "--launch-record", internal["path"], "--dangerous")
    try:
        yield internal | {
            "cli": cli,
            "args": args,
            "http": fixture,
            "changes": changes,
            "samples": samples,
            "plans": plans,
        }
    finally:
        server.close()


def preview(state):
    return state["cli"](*state["args"], "--dry-run")["data"]


def test_two_fresh_timestamps_confirm_via_public_cli_and_preserve_raw_provenance(public_exit):
    state = public_exit
    proposed = preview(state)
    public = proposed["preview"]
    raw_t1 = state["plans"][0].before["process"]
    assert public["can_apply"] is True
    result = state["cli"](*state["args"], "--confirm", proposed["confirm_token"])["data"]
    raw_t2 = state["plans"][1].before["process"]
    assert raw_t1["image_verified_at_utc"] != raw_t2["image_verified_at_utc"]
    projected = copy.deepcopy(raw_t1)
    projected.pop("image_verified_at_utc")
    assert state["plans"][0].binding["process"] == projected
    assert state["plans"][0].binding == state["plans"][1].binding
    assert public["base_snapshot"]["revision"] == digest(state["plans"][0].binding)
    assert public["extensions"]["creo"]["initial_process_observation"] == raw_t1
    assert public["base_snapshot"]["extensions"]["creo"]["process_observation"] == raw_t1
    receipt = result["receipt"]
    assert receipt["snapshot_before"] == public["base_snapshot"]
    assert (
        receipt["extensions"]["creo"]["domain_result"]["pre_dispatch_process_observation"] == raw_t2
    )
    projection = receipt["snapshot_before"]["extensions"]["creo"]["state_revision_projection"]
    assert projection["excluded_fields"] == ["process.image_verified_at_utc"]
    assert receipt["outcome"]["verification"]["status"] == "passed"
    assert state["http"].ops().count("session.exit") == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", 322),
        ("creation_filetime", "12344"),
        ("image", "C:/different/xtop.exe"),
        ("image_source", "different source"),
        ("alive", False),
        ("signaled", True),
        ("exit_code", 7),
        ("exit_filetime", "99999"),
        ("source", "different observer"),
        ("future_state", {"protected": True}),
        ("nested", {"image_verified_at_utc": "changed nested state"}),
    ],
)
def test_every_other_process_field_stays_bound_and_refuses_before_dispatch(
    public_exit, field, value
):
    state = public_exit
    proposed = preview(state)
    state["changes"][field] = value
    error = state["cli"](*state["args"], "--confirm", proposed["confirm_token"], status=6)["error"]
    assert error["code"] == "E_CONFLICT"
    assert error["details"]["conflict"] == "state_drift"
    assert state["http"].ops().count("session.exit") == 0
    operation = operations.get(proposed["preview"]["operation_id"])
    assert operation["status"] == "planned" and operation["started_at"] is None
    attempt = operations.confirmation_attempts(operation["operation_id"])[-1]
    assert attempt["terminal"] is True and attempt["status"] == "rejected_before_dispatch"


@pytest.mark.parametrize(
    "change",
    [
        "launcher_birth",
        "registration_file",
        "raw_count",
        "raw_list",
        "raw_units",
        "source",
        "runtime",
        "policy",
        "permission",
    ],
)
def test_existing_launch_runtime_registration_inventory_source_policy_guards_stay_strict(
    public_exit,
    monkeypatch,
    change,
):
    state = public_exit
    proposed = preview(state)
    if change == "launcher_birth":
        state["launch"]["launcher_creation_filetime"] = "10001"
        state["path"].write_text(json.dumps(state["launch"]), encoding="utf-8")
    elif change == "registration_file":
        (state["path"].parent / "protk.dat").write_bytes(b"changed controlled registry")
    elif change == "raw_count":
        state["http"].raw_empty["raw_model_count"] = 1
    elif change == "raw_list":
        state["http"].raw_empty["raw_models"] = [{"model": "protected.prt"}]
    elif change == "raw_units":
        state["http"].raw_empty["units"]["length"] = "in"
    elif change == "source":
        state["http"].raw_empty["source_sha256"] = "c" * 64
    elif change == "runtime":
        state["deployment"]["runtime_configuration"]["state_directory"] = str(state["path"].parent)
    elif change == "policy":
        state["launch"]["effective_deployment_policy"]["unsigned_apps"] = "prompt"
        state["path"].write_text(json.dumps(state["launch"]), encoding="utf-8")
    else:
        monkeypatch.setenv("CREO_CLI_PERMISSION", "read")
    error = state["cli"](
        *state["args"],
        "--confirm",
        proposed["confirm_token"],
        status=6 if change in {"raw_count", "raw_list", "raw_units", "source", "runtime"} else 4,
    )["error"]
    assert error["details"]["dispatch_state"] == "not_started"
    assert state["http"].ops().count("session.exit") == 0
    assert operations.get(proposed["preview"]["operation_id"])["status"] == "planned"


def test_unknown_receipt_retains_preview_raw_time_without_late_reread(public_exit):
    state = public_exit
    proposed = preview(state)
    state["http"].exit_failure = True
    error = state["cli"](*state["args"], "--confirm", proposed["confirm_token"], status=6)["error"]
    assert error["code"] == "E_OUTCOME_UNKNOWN"
    raw = error["details"]["receipt"]["snapshot_before"]["extensions"]["creo"][
        "process_observation"
    ]
    assert raw == state["plans"][0].before["process"]
    assert (
        raw["image_verified_at_utc"] != state["plans"][1].before["process"]["image_verified_at_utc"]
    )
    assert state["http"].ops().count("session.exit") == 1


def test_source7_style_timestamp_bound_token_stays_refused_without_reclassification(
    public_exit,
    monkeypatch,
):
    state = public_exit
    current = ex.plan

    def legacy_source7(*args):
        value = current(*args)
        value.binding["process"] = copy.deepcopy(value.before["process"])
        return value

    with monkeypatch.context() as previous:
        previous.setattr(ex, "plan", legacy_source7)
        proposed = preview(state)
    operation_id = proposed["preview"]["operation_id"]
    retained_before = operations.get(operation_id)
    error = state["cli"](*state["args"], "--confirm", proposed["confirm_token"], status=6)["error"]
    assert error["code"] == "E_CONFLICT" and error["details"]["conflict"] == "state_drift"
    retained_after = operations.get(operation_id)
    assert retained_after == retained_before and retained_after["status"] == "planned"
    assert state["http"].ops().count("session.exit") == 0


def test_global_snapshot_still_binds_timestamp():
    left = {"image_verified_at_utc": "T1"}
    right = {"image_verified_at_utc": "T2"}
    assert driver.snapshot(left)["revision"] != driver.snapshot(right)["revision"]
