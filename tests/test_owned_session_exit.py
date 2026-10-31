"""Controlled owned-exit lifecycle evidence. No process or CAD is terminated."""

import copy
import json

import pytest

from creo_cli import owned_exit as ex
from creo_cli.core import Error

GEN = "12345678-1234-4234-8234-123456789abc"
OP = "a" * 32


@pytest.fixture
def world(tmp_path, monkeypatch):
    runtime, install, startup = (tmp_path / s for s in ("runtime", "components", "startup"))
    for p in (runtime, install, startup):
        p.mkdir()
    pin = {
        "native_pid": 321,
        "java_pid": 654,
        "chain": [654, 321],
        "process_creations": {"321": "12345", "654": "12346"},
        "service_instance_id": GEN,
    }
    launch = {
        "status": "ready",
        "require_native": True,
        "native_load_verified": True,
        "deployment_policy_verified": True,
        "launcher_pid": 789,
        "launcher_creation_filetime": "10000",
        "process_host_pid": 987,
        "started_before_utc": "1601-01-01T00:00:00Z",
        "argument_transport": "ProcessStartInfo.ArgumentList",
        "desktop_input_count": 0,
        "cua_input_count": 0,
        "launch_arguments": ["declared-model.prt.1"],
        "runtime_pin": pin,
        "runtime": str(runtime),
        "installation": str(install),
        "startup": str(startup),
        "executable": str(tmp_path / "creo/Parametric/bin/parametric.exe"),
        "java_executable": str(tmp_path / "jdk/bin/java.exe"),
        "health": {"service_instance_id": GEN},
    }
    path = startup / "launch.json"
    path.write_text(json.dumps(launch))
    producer = {
        "launcher_pid": 789,
        "launcher_creation_filetime": "10000",
        "process_host_pid": 987,
        "executable": launch["executable"],
        "arguments": launch["launch_arguments"],
        "input_method": "ProcessStartInfo.ArgumentList",
        "desktop_inputs": 0,
        "CUA_inputs": 0,
    }
    (startup / "launcher-process.json").write_text(json.dumps(producer))
    monkeypatch.setenv("CREO_CLI_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(ex.operations, "selected_runs", lambda **kwargs: [])
    deployment = {
        "loaded_verified": True,
        "runtime_pin": pin,
        "runtime_configuration": {"state_directory": str(runtime)},
        "component_source_sha256": "b" * 64,
    }
    monkeypatch.setattr(ex.deployment, "inspect", lambda *a, **kw: copy.deepcopy(deployment))
    rows = [
        {
            "pid": 321,
            "creation_filetime": "12345",
            "actual_image": str(tmp_path / "creo/Common Files/x86e_win64/obj/xtop.exe"),
        },
        {"pid": 789, "creation_filetime": "10000", "actual_image": launch["executable"]},
    ]
    monkeypatch.setattr(ex.runtime_identity, "processes", lambda: copy.deepcopy(rows))
    monkeypatch.setattr(ex, "native_launcher_link", lambda _: {"pid": 321, "launcher_pid": 789})

    class Handle:
        alive = True
        code = 0

        def __init__(self, pid, birth, image):
            self.pid, self.birth, self.image, self.handle = pid, birth, str(image), True

        def observe(self):
            return {
                "pid": self.pid,
                "creation_filetime": self.birth,
                "image": self.image,
                "alive": self.alive,
                "signaled": not self.alive,
                "exit_code": None if self.alive else self.code,
            }

        def tick(self):
            return 1000

        def begin_termination(self):
            assert self.handle is not None and self.alive

        def close(self):
            self.handle = None

    monkeypatch.setattr(ex, "ProcessHandle", Handle)

    class Client:
        url = "http://127.0.0.1:12999"
        mode = "returned"
        calls = []
        state = {
            "raw_model_count": 0,
            "raw_models": [],
            "models_complete": True,
            "native_exit_available": True,
            "service_instance_id": GEN,
            "source_sha256": "b" * 64,
        }

        def require_capability(self, *a):
            pass

        def op(self, name, request, **kwargs):
            self.calls.append((name, copy.deepcopy(request)))
            if name == "session.exit-state":
                return copy.deepcopy(self.state)
            assert name == "session.exit"
            common = {
                "operation_id": request["operation_id"],
                "service_instance_id": GEN,
                "native_pid": 321,
                "native_creation_filetime": "12345",
                "entrypoint": "ProEngineerEnd",
                "raw_java_empty_checked": True,
                "native_known_types_empty": True,
                "empty_models": True,
                "native_type_count": 11,
            }
            ex._new_json(
                runtime / f"owned-exit-{OP}.entered.json", {**common, "status": "native_entered"}
            )
            if self.mode == "returned":
                ex._new_json(
                    runtime / f"owned-exit-{OP}.returned.json",
                    {
                        **common,
                        "status": "native_returned",
                        "api_called": True,
                        "native_return_code": 0,
                    },
                )
                Handle.alive = False
            elif self.mode in ("stop", "stop_unavailable"):
                file, _ = ex.fingerprint(runtime / f"owned-exit-{OP}.entered.json")
                ex._new_json(
                    runtime / f"owned-exit-{OP}.stop.json",
                    {
                        **common,
                        "status": "service_stop_after_owned_native_entry",
                        "entered_sha256": file["sha256"],
                    },
                )
                if self.mode == "stop_unavailable":
                    ex._new_json(
                        runtime / f"owned-exit-{OP}.unavailable.json",
                        {
                            "status": "native_return_unavailable_after_entry",
                            "operation_id": OP,
                            "service_instance_id": GEN,
                            "entered_sha256": file["sha256"],
                            "cause_type": "ControlledConnectionLoss",
                            "communication_kind": "com.ptc.pfc.pfcExceptions.XToolkitCommError",
                        },
                    )
                Handle.alive = False
            elif self.mode == "failure":
                ex._new_json(
                    runtime / f"owned-exit-{OP}.returned.json",
                    {
                        **common,
                        "status": "native_returned",
                        "api_called": False,
                        "native_return_code": -1,
                    },
                )
            return {"status": "request_scheduled", "operation_id": OP}

    client = Client()
    return {
        "path": path,
        "launch": launch,
        "runtime": runtime,
        "deployment": deployment,
        "rows": rows,
        "client": client,
        "handle": Handle,
        "opts": {"launch_record": str(path)},
    }


@pytest.mark.parametrize(
    "case",
    [
        "missing_launcher",
        "missing_producer",
        "attached",
        "wrong_ppid",
        "wrong_birth",
        "wrong_image",
        "reused_before_native",
    ],
)
def test_full_flags_are_not_owned_launch_provenance(world, monkeypatch, case):
    if case == "missing_launcher":
        del world["launch"]["launcher_pid"]
    elif case == "missing_producer":
        (world["path"].parent / "launcher-process.json").unlink()
    elif case == "attached":
        world["launch"]["ownership"] = "attached"
    elif case == "wrong_ppid":
        monkeypatch.setattr(ex, "native_launcher_link", lambda _: {"pid": 321, "launcher_pid": 999})
    elif case == "wrong_birth":
        world["rows"][0]["creation_filetime"] = "12300"
    elif case == "wrong_image":
        world["rows"][1]["actual_image"] = "different.exe"
    else:
        world["rows"][1]["creation_filetime"] = "11000"
    world["path"].write_text(json.dumps(world["launch"]))
    with pytest.raises(Error):
        ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    assert not any(name == "session.exit" for name, _ in world["client"].calls)


@pytest.mark.parametrize("case", ["gone", "reused_after_native"])
def test_original_launcher_may_naturally_exit_with_live_native_link(world, case):
    if case == "gone":
        world["rows"].pop()
    else:
        world["rows"][1]["creation_filetime"] = "20000"
        world["rows"][1]["actual_image"] = "unrelated-reused-pid.exe"
    p = ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    assert p.preview["owned_target"]["extensions"]["creo"]["ownership"] == "owned"


@pytest.mark.parametrize("mode", ["returned", "stop", "stop_unavailable"])
def test_complete_only_joint_held_process_and_correlated_native_evidence(world, mode):
    c = world["client"]
    c.mode = mode
    p = ex.plan(c, world["opts"], ex.prepare(world["opts"]))
    p.prepare_dispatch({"operation_id": OP})
    data = p.apply(c, {"operation_id": OP})
    result, verification = p.verify(c, data)
    assert all(check["passed"] for check in verification["checks"])
    assert p._verified_observation_guard(p, c)
    assert result["persistence"] == "not_applicable"
    assert [name for name, _ in c.calls] == ["session.exit-state", "session.exit"]
    p.request["expected_pid"] = 9
    assert not p._verified_observation_guard(p, c)
    with pytest.raises(Error) as unbound:
        p.observe(c)
    assert unbound.value.code == "E_VERIFY_INCOMPLETE"


@pytest.mark.parametrize(
    "key,value",
    [
        ("require_native", False),
        ("native_load_verified", False),
        ("deployment_policy_verified", False),
        ("status", "not_ready"),
    ],
)
def test_incomplete_or_java_only_launch_never_dispatches(world, key, value):
    world["launch"][key] = value
    world["path"].write_text(json.dumps(world["launch"]))
    with pytest.raises(Error) as failure:
        ex.prepare(world["opts"])
    assert failure.value.details["dispatch_state"] == "not_started"
    assert not world["client"].calls


@pytest.mark.parametrize(
    "mutation",
    [
        "nonempty",
        "bool_count",
        "incomplete",
        "missing_dll",
        "wrong_instance",
        "wrong_source",
        "changed_birth",
    ],
)
def test_nonempty_incomplete_or_identity_drift_refuses_before_exit(world, mutation):
    c = world["client"]
    if mutation == "nonempty":
        c.state = c.state | {
            "raw_model_count": 1,
            "raw_models": ["section"],
            "models_complete": False,
        }
    elif mutation == "bool_count":
        c.state = c.state | {"raw_model_count": False}
    elif mutation == "incomplete":
        c.state = c.state | {"models_complete": False}
    elif mutation == "missing_dll":
        c.state = c.state | {"native_exit_available": False}
    elif mutation == "wrong_instance":
        c.state = c.state | {"service_instance_id": "wrong"}
    elif mutation == "wrong_source":
        c.state = c.state | {"source_sha256": "wrong"}
    else:
        world["deployment"]["runtime_pin"] = {"native_pid": 321}
    with pytest.raises(Error):
        ex.plan(c, world["opts"], ex.prepare(world["opts"]))
    assert not any(name == "session.exit" for name, _ in c.calls)


def test_current_generation_unresolved_blocks_without_reading_cad(world, monkeypatch):
    monkeypatch.setattr(
        ex.operations,
        "selected_runs",
        lambda **kwargs: [{"status": "unknown", "driver_plan": {"target": {"instance_id": GEN}}}],
    )
    with pytest.raises(Error):
        ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    assert not world["client"].calls


@pytest.mark.parametrize("mode", ["ack_only", "failure"])
def test_ack_or_failed_api_is_unknown_without_any_settling_cad_call(world, monkeypatch, mode):
    c = world["client"]
    c.mode = mode
    monkeypatch.setattr(ex, "MAX_EXIT_MS", 20)
    p = ex.plan(c, world["opts"], ex.prepare(world["opts"]))
    p.prepare_dispatch({"operation_id": OP})
    with pytest.raises(Error) as failure:
        p.apply(c, {"operation_id": OP})
    assert failure.value.code == "E_OUTCOME_UNKNOWN"
    p.observe(c)
    assert [name for name, _ in c.calls] == ["session.exit-state", "session.exit"]


def test_durable_intent_is_exclusive_and_does_not_overwrite(world):
    p = ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    file = world["runtime"] / f"owned-exit-{OP}.intent.json"
    file.write_text("original")
    with pytest.raises(FileExistsError):
        p.prepare_dispatch({"operation_id": OP})
    assert file.read_text() == "original"
    assert not any(name == "session.exit" for name, _ in world["client"].calls)


def test_expired_parent_deadline_never_sends_exit(world, monkeypatch):
    p = ex.plan(world["client"], world["opts"], ex.prepare(world["opts"]))
    p.prepare_dispatch({"operation_id": OP})
    monkeypatch.setattr(ex.timing, "deadline", lambda _: 0)
    with pytest.raises(Error) as failure:
        p.apply(world["client"], {"operation_id": OP})
    assert failure.value.details["dispatch_state"] == "not_started"
    assert [name for name, _ in world["client"].calls] == ["session.exit-state"]


def test_public_entry_requires_explicit_dangerous_and_is_not_workflow_capture():
    with pytest.raises(Error) as missing:
        ex.execute({"dry_run": True})
    assert missing.value.code == "E_FORBIDDEN"
    marker = ex.engine.CAPTURE.set([])
    try:
        with pytest.raises(Error) as captured:
            ex.execute({"dangerous": True, "dry_run": True})
        assert captured.value.code == "E_UNSUPPORTED"
    finally:
        ex.engine.CAPTURE.reset(marker)


def test_public_command_declares_one_owned_launch_selector_and_native_ops():
    from creo_cli.registry import COMMANDS

    command = next(c for c in COMMANDS if c.path == "session exit")
    assert command.write and command.dangerous
    assert [p.name for p in command.params] == ["launch-record"]
    assert command.service_ops == ("session.exit-state", "session.exit")


def test_public_reference_and_parser_share_kebab_selector(tmp_path, monkeypatch, capsys):
    from creo_cli import main

    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(tmp_path))
    assert main.main(["reference", "--command", "session exit", "--json", "--compact"]) == 0
    public = json.loads(capsys.readouterr().out)
    assert public["ok"] is True
    command = public["data"]["command"]
    assert command["params"][0]["name"] == "launch-record"
    assert all(example.count("--dangerous") == 1 for example in command["examples"])
    launch = str(tmp_path / "startup" / "launch.json")
    parsed = main.parser().parse_args(
        ["session", "exit", "--launch-record", launch, "--dangerous", "--dry-run"]
    )
    assert parsed.launch_record == launch
    assert parsed.dangerous is True and parsed.dry_run is True


@pytest.mark.parametrize(
    "mutation",
    [
        "no_entered",
        "wrong_pid",
        "wrong_birth",
        "wrong_image",
        "alive",
        "bad_code",
        "java_only",
        "wrong_stop_hash",
        "cancelled",
        "failure",
        "not_called",
    ],
)
def test_process_disappearance_or_stop_alone_never_qualifies(world, mutation):
    expected = {
        "expected_pid": 321,
        "expected_creation_filetime": "12345",
        "expected_native_image": "/declared/xtop.exe",
        "service_instance_id": GEN,
    }
    common = {
        "operation_id": OP,
        "service_instance_id": GEN,
        "native_pid": 321,
        "native_creation_filetime": "12345",
        "entrypoint": "ProEngineerEnd",
        "raw_java_empty_checked": True,
        "native_known_types_empty": True,
        "empty_models": True,
        "native_type_count": 11,
    }
    obs = {
        "operation_id": OP,
        "process": {
            "pid": 321,
            "creation_filetime": "12345",
            "image": "/declared/xtop.exe",
            "signaled": True,
            "alive": False,
            "exit_code": 0,
        },
        "entered": {"file": {"sha256": "a"}, "data": common | {"status": "native_entered"}},
        "stop": {
            "data": common
            | {"status": "service_stop_after_owned_native_entry", "entered_sha256": "a"}
        },
    }
    if mutation == "no_entered":
        obs["entered"] = None
    elif mutation == "wrong_pid":
        obs["process"]["pid"] = 654
    elif mutation == "wrong_birth":
        obs["process"]["creation_filetime"] = "reused"
    elif mutation == "wrong_image":
        obs["process"]["image"] = "/declared/java.exe"
    elif mutation == "alive":
        obs["process"]["alive"] = True
    elif mutation == "bad_code":
        obs["process"]["exit_code"] = 5
    elif mutation == "java_only":
        obs["process"]["signaled"] = False
    elif mutation == "wrong_stop_hash":
        obs["stop"]["data"]["entered_sha256"] = "different"
    elif mutation == "cancelled":
        obs["cancelled"] = {"data": {}}
    elif mutation == "failure":
        obs["failed"] = {"data": {}}
    else:
        obs["returned"] = {
            "data": common
            | {"status": "native_returned", "api_called": False, "native_return_code": 0}
        }
    assert ex.qualified(obs, expected) is False
