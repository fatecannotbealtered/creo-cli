"""Reproduce the pushed review defects before repairing their consistency contracts."""

import ast
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from creo_cli import operations, owned_exit
from creo_cli.core import Error
from tests.contract_cli import ContractCliMixin, external_cli
from tests.test_commands import RECT, ROOT, Base
from tests.test_features import Built


class RenderRecoveryReview(ContractCliMixin, Built):
    def fresh(self, *args, status=0):
        result = external_cli(self.env, args, fresh=True)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_render_final_receipt_failure_is_queryable_and_resolvable_in_new_process(self):
        self.block()
        args = ("artifact", "render", "--model", "block.prt", "--output", "recover.jpg")
        plan = self.cli(*args, "--dry-run")["data"]
        ident = plan["preview"]["operation_id"]
        database = Path(self.env["CREO_CLI_CONFIG_DIR"]) / "operations.sqlite3"
        # A real storage boundary, visible to source and the separate frozen EXE.
        # Only this operation's final public receipt commit is refused.
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(
                "CREATE TRIGGER c18_final_render_failure BEFORE UPDATE OF body ON operations "
                f"WHEN NEW.id='{ident}' AND json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'controlled final public receipt failure'); END"
            )
        try:
            failed = self.cli(*args, "--confirm", plan["confirm_token"], status=6)
        finally:
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("DROP TRIGGER c18_final_render_failure")
        self.assertEqual(failed["error"]["code"], "E_OUTCOME_UNKNOWN")
        self.assertEqual(failed["error"]["details"]["record_error"], "E_IO")
        with patch.dict(os.environ, self.env, clear=True):
            durable = operations.get(ident)
        self.assertEqual(durable["status"], "running")
        self.assertEqual(durable["driver_stage"], "finalizing")
        self.assertIsNone(durable["driver_receipt"])
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "unknown")
        # This is a retained fact that the call returned, not an overall success.
        self.assertEqual(shown["receipt"]["outcome"]["execution"], "completed")
        self.assertEqual(shown["receipt"]["recovery"]["action"], "inspect")
        self.assertEqual(self.world.ops().count("model.render"), 1)
        replay = self.fresh(*args, "--confirm", plan["confirm_token"], status=6)
        self.assertEqual(replay["error"]["code"], "E_CONFLICT")
        blocked_save = self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)
        self.assertEqual(blocked_save["error"]["code"], "E_CONFLICT")
        launch_record = self.unknown_exit_record(durable)
        # Establish that the refusal reaches the unresolved guard, rather than
        # winning merely because the test supplied an invalid launch document.
        with patch.dict(os.environ, self.env, clear=True):
            owned_exit.prepare({"launch_record": str(launch_record)})
        self.world.capabilities["owned_session_exit"] = 1
        blocked_exit = self.fresh(
            "session",
            "exit",
            "--launch-record",
            launch_record,
            "--dangerous",
            "--dry-run",
            status=6,
        )
        self.assertEqual(blocked_exit["error"]["code"], "E_CONFLICT")
        self.assertIn("unresolved calls prevent termination", blocked_exit["error"]["message"])
        self.assertFalse(blocked_exit["error"]["details"]["automatic_retry"])
        self.assertEqual(self.world.ops().count("model.render"), 1)
        self.assertNotIn("model.save", self.world.ops())
        self.assertNotIn("session.exit-state", self.world.ops())
        self.assertNotIn("session.exit", self.world.ops())
        again = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(
            (again["status"], again["receipt"]["outcome"]["execution"]), ("unknown", "completed")
        )
        print(
            "F38 before explicit resolution: overall unknown; call returned; "
            "one render; replay/save/owned-exit refused; no exit-state or exit dispatch"
        )
        self.fresh(
            "operation",
            "resolve",
            "--id",
            ident,
            "--outcome",
            "partial",
            "--evidence",
            "independent fixture display and published bytes inspected",
        )
        self.fresh("model", "save", "--model", "block.prt", "--dry-run")

    def unknown_exit_record(self, durable):
        """Controlled preflight-only evidence; no process or SDK is contacted."""
        startup, runtime, installation = (
            self.ws / name for name in ("startup", "runtime", "components")
        )
        for path in (startup, runtime, installation):
            path.mkdir()
        pin = {
            "native_pid": 321,
            "java_pid": 654,
            "process_creations": {"321": "12345", "654": "12346"},
            "service_instance_id": durable["driver_plan"]["target"]["instance_id"],
        }
        executable = str(self.ws / "creo/Parametric/bin/parametric.exe")
        launch = {
            "status": "ready",
            "require_native": True,
            "native_load_verified": True,
            "deployment_policy_verified": True,
            "ownership": "owned",
            "launcher_pid": 789,
            "launcher_creation_filetime": "10000",
            "process_host_pid": 987,
            "argument_transport": "ProcessStartInfo.ArgumentList",
            "launch_arguments": [],
            "desktop_input_count": 0,
            "cua_input_count": 0,
            "started_before_utc": "1601-01-01T00:00:00Z",
            "runtime_pin": pin,
            "health": {"service_instance_id": pin["service_instance_id"]},
            "runtime": str(runtime),
            "installation": str(installation),
            "startup": str(startup),
            "executable": executable,
            "java_executable": str(self.ws / "java/bin/java.exe"),
        }
        producer = {
            "launcher_pid": 789,
            "launcher_creation_filetime": "10000",
            "process_host_pid": 987,
            "input_method": "ProcessStartInfo.ArgumentList",
            "desktop_inputs": 0,
            "CUA_inputs": 0,
            "executable": executable,
            "arguments": [],
        }
        (startup / "launcher-process.json").write_text(json.dumps(producer), encoding="utf-8")
        record = startup / "launch.json"
        record.write_text(json.dumps(launch), encoding="utf-8")
        return record

    def test_process_interruptions_before_dispatch_and_after_publication(self):
        self.block()
        for stage in ("prepared", "dispatching", "linked", "published"):
            with self.subTest(stage=stage):
                args = ("artifact", "render", "--model", "block.prt", "--output", stage + ".jpg")
                plan = self.cli(*args, "--dry-run")["data"]
                ident = plan["preview"]["operation_id"]
                marker = self.root / (stage + ".ready")
                program = """
import os, sys, time
from pathlib import Path
from creo_cli import operations, process_owner
lease=process_owner.lease
process_owner.lease=lambda seconds=60: lease(0)
marker, stage=sys.argv[1:3]
del sys.argv[1:3]
def stop():
    Path(marker).write_text('ready')
    time.sleep(30)
update=operations.update
def checkpoint(run):
    result=update(run)
    if run.get('driver_render',{}).get('phase')==stage: stop()
    return result
operations.update=checkpoint
link=os.link
def publish(*args,**kwargs):
    result=link(*args,**kwargs)
    if stage=='linked': stop()
    return result
os.link=publish
from creo_cli.main import main
sys.exit(main())
"""
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        program,
                        str(marker),
                        stage,
                        *map(str, args),
                        "--confirm",
                        plan["confirm_token"],
                    ],
                    cwd=ROOT,
                    env=self.env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    until = time.monotonic() + 15
                    while not marker.exists() and child.poll() is None and time.monotonic() < until:
                        time.sleep(0.02)
                    self.assertTrue(marker.exists(), "checkpoint not reached")
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=10)
                # All record-only operations work without any CAD connection.
                self.env["CREO_CLI_SERVICE_URL"] = "http://127.0.0.1:1"
                shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
                receipt = shown["receipt"]
                self.assertEqual(shown["status"], "unknown")
                self.assertEqual(receipt["outcome"]["change"], "unknown")
                recovery = receipt["extensions"]["creo"]["render_recovery"]
                self.assertEqual(
                    recovery["state"],
                    "published_output"
                    if stage in ("linked", "published")
                    else "no_generated_file_observed",
                )
                self.assertEqual(
                    (self.ws / (stage + ".jpg")).exists(), stage in ("linked", "published")
                )
                before = len(self.world.events)
                proof = (
                    "independent fixture unchanged model/display and exact files checked " + stage
                )
                pre = self.fresh(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "partial",
                    "--evidence",
                    proof,
                    "--dry-run",
                )["data"]
                self.fresh(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "partial",
                    "--evidence",
                    proof,
                    "--confirm",
                    pre["confirm_token"],
                )
                self.assertEqual(len(self.world.events), before)
                self.env["CREO_CLI_SERVICE_URL"] = self.server.url

    def test_render_ownership_storage_failure_is_zero_dispatch(self):
        self.block()
        args = ("artifact", "render", "--model", "block.prt", "--output", "refused.jpg")
        plan = self.cli(*args, "--dry-run")["data"]
        update = operations.update

        def refuse(run):
            if run.get("driver_render"):
                raise Error("E_IO", "ownership storage unavailable")
            return update(run)

        with patch.object(operations, "update", side_effect=refuse):
            result = self.cli(*args, "--confirm", plan["confirm_token"], status=1)
        self.assertEqual(result["error"]["code"], "E_IO")
        self.assertNotIn("model.render", self.world.ops())
        self.assertFalse((self.ws / "refused.jpg").exists())

    def test_legacy_render_without_ownership_never_guesses_files(self):
        self.block()
        args = ("artifact", "render", "--model", "block.prt", "--output", "legacy.jpg")
        plan = self.cli(*args, "--dry-run")["data"]
        ident = plan["preview"]["operation_id"]
        (self.ws / "legacy.jpg").write_bytes(b"unrelated output at the same path")
        with patch.dict(os.environ, self.env, clear=True):
            run = operations.get(ident)
            run.update(status="running", driver_stage="finalizing")
            operations.update(run)
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "unknown")
        self.assertEqual(shown["receipt"]["artifacts"], [])
        self.assertEqual(
            shown["receipt"]["extensions"]["creo"]["render_recovery"]["state"],
            "evidence_incomplete",
        )

    def test_shared_receipt_failure_new_process_save_export_workflow_and_render_size(self):
        self.block()
        cases = [
            ("save", ("model", "save", "--model", "block.prt")),
            (
                "export",
                (
                    "artifact",
                    "export",
                    "--model",
                    "block.prt",
                    "--output",
                    "shared.stp",
                ),
            ),
            (
                "workflow",
                (
                    "workflow",
                    "run",
                    "--request",
                    self.request(
                        {"steps": [{"command": "model save", "args": {"model": "block.prt"}}]},
                        "shared-workflow.json",
                    ),
                ),
            ),
            ("render", ("artifact", "render", "--model", "block.prt", "--output", "size.jpg")),
        ]
        for kind, args in cases:
            with self.subTest(kind=kind):
                plan = self.cli(*args, "--dry-run")["data"]
                ident = plan["preview"]["operation_id"]
                update = operations.update

                def fail_public(run, ident=ident, update=update):
                    if run["operation_id"] == ident and run.get("driver_receipt"):
                        with patch.object(operations, "MAX_RECORD_BYTES", 1):
                            return update(run)
                    return update(run)

                with patch.object(operations, "update", side_effect=fail_public):
                    self.cli(*args, "--confirm", plan["confirm_token"], status=6)
                shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
                self.assertEqual(shown["status"], "unknown")
                self.fresh(*args, "--confirm", plan["confirm_token"], status=6)
                self.fresh(
                    "operation",
                    "resolve",
                    "--id",
                    ident,
                    "--outcome",
                    "partial",
                    "--evidence",
                    "independent fixture domain state and saved files inspected",
                )

    def test_killed_cli_after_jpeg_keeps_exact_staging_ownership_for_new_process(self):
        self.block()
        args = ("artifact", "render", "--model", "block.prt", "--output", "killed.jpg")
        plan = self.cli(*args, "--dry-run")["data"]
        ready, release = threading.Event(), threading.Event()
        original = self.world.render
        sent = {}

        def hold(q):
            result = original(q)
            sent.update(q)
            ready.set()
            release.wait(20)
            return result

        # Only accelerate the owned test lease; the process is genuinely terminated.
        program = (
            "from creo_cli import process_owner; original=process_owner.lease; "
            "process_owner.lease=lambda seconds=60: original(0); "
            "from creo_cli.main import main; import sys; sys.exit(main())"
        )
        with patch.object(self.world, "render", side_effect=hold):
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    program,
                    *map(str, args),
                    "--confirm",
                    plan["confirm_token"],
                ],
                cwd=ROOT,
                env=self.env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                self.assertTrue(ready.wait(15), "render did not reach JPEG checkpoint")
                self.assertTrue(Path(sent["file"]).is_file())
                child.kill()
                child.communicate(timeout=10)
            finally:
                release.set()
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)
        ident = plan["preview"]["operation_id"]
        with patch.dict(os.environ, self.env, clear=True):
            durable = operations.get(ident)
        self.assertEqual(durable.get("driver_render", {}).get("staged_path"), sent["file"])
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["status"], "unknown")
        self.assertFalse((self.ws / "killed.jpg").exists())
        self.assertEqual(shown["receipt"]["artifacts"][0]["path"], sent["file"])
        self.fresh("model", "save", "--model", "block.prt", "--dry-run", status=6)

    def test_published_path_replacement_is_not_claimed_as_owned_output(self):
        self.block()
        args = ("artifact", "render", "--model", "block.prt", "--output", "replace.jpg")
        plan = self.cli(*args, "--dry-run")["data"]
        update = operations.update

        def fail(run):
            if run.get("driver_receipt"):
                raise Error("E_IO", "final receipt unavailable")
            return update(run)

        with patch.object(operations, "update", side_effect=fail):
            self.cli(*args, "--confirm", plan["confirm_token"], status=6)
        output = self.ws / "replace.jpg"
        replacement = self.ws / "replacement.jpg"
        replacement.write_bytes(output.read_bytes())
        replacement.replace(output)
        ident = plan["preview"]["operation_id"]
        with patch.dict(os.environ, self.env, clear=True):
            durable_before = operations.get(ident)
        self.env["CREO_CLI_SERVICE_URL"] = "http://127.0.0.1:1"
        shown = self.fresh("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"]["artifacts"], [])
        self.assertEqual(
            shown["receipt"]["extensions"]["creo"]["render_recovery"]["state"],
            "evidence_incomplete",
        )
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(operations.get(ident), durable_before)


class ReviewIntegrity(Base):
    def test_unknown_import_blocks_dimension_and_dependent_drawing_but_not_same_base_drawing(self):
        file = self.ws / "input.stp"
        file.write_bytes(b"ISO-10303-21;fixture")
        self.world.drop = "model.import"
        error = self.gated("model", "import", "--path", file, "--name", "incoming", status=6)[
            "error"
        ]
        self.world.drop = None
        # The identity guard precedes the dimension planner's required getters.
        refused = self.cli(
            "dimension",
            "set",
            "--model",
            "incoming",
            "--dimension",
            "d4",
            "--value",
            48,
            "--units",
            "mm",
            "--dry-run",
            status=6,
        )["error"]
        self.assertEqual(refused["details"]["conflict"], "unresolved_operation")
        self.gated("part", "create", "--name", "other", "--units", "mmns")
        # No model extension is stripped: an unrelated drawing with the same basename is distinct.
        unrelated = {
            "mode": "session",
            "engine_id": "creo",
            "instance_id": "fixture-generation-1",
            "object_id": "incoming.drw",
            "locator": "http://127.0.0.1:9999/models/incoming.drw",
        }
        from creo_cli import driver

        with patch.dict(os.environ, self.env, clear=True):
            driver.require_clear(unrelated)
            with self.assertRaises(Error):
                driver.require_clear(unrelated, ["incoming.prt"])
        self.assertEqual(
            error["details"]["receipt"]["target"]["extensions"]["creo"]["object_claims"],
            ["incoming.asm", "incoming.prt"],
        )

    def test_unknown_import_blocks_save_and_regenerate_of_created_part(self):
        file = self.ws / "input.stp"
        file.write_bytes(b"ISO-10303-21;fixture")
        self.world.drop = "model.import"
        error = self.gated("model", "import", "--path", file, "--name", "incoming", status=6)[
            "error"
        ]
        self.world.drop = None
        self.assertIn("incoming.prt", self.world.models)
        for action in ("save", "regenerate"):
            with self.subTest(action=action):
                refused = self.cli(
                    "model", action, "--model", "incoming.prt", "--dry-run", status=6
                )["error"]
                self.assertEqual(refused["details"]["conflict"], "unresolved_operation")
        self.gated("part", "create", "--name", "unrelated", "--units", "mmns")
        query = self.cli(
            "operation",
            "query",
            "--id",
            error["details"]["operation_id"],
            "--model",
            "incoming.prt",
        )["data"]
        self.cli(
            "operation",
            "resolve",
            "--id",
            error["details"]["operation_id"],
            "--outcome",
            "applied",
            "--evidence",
            "independent imported model getters " + query["evidence_id"],
        )
        self.gated("model", "save", "--model", "incoming.prt")

    def test_older_bare_import_records_preserve_typed_and_untyped_claims(self):
        from creo_cli import driver

        file = self.ws / "input.stp"
        file.write_bytes(b"ISO-10303-21;fixture")
        for kind in (None, "part"):
            with self.subTest(kind=kind):
                name = "old_unknown" if kind is None else "old_part"
                self.world.drop = "model.import"
                args = ("model", "import", "--path", file, "--name", name)
                if kind:
                    args += ("--type", kind)
                error = self.gated(*args, status=6)["error"]
                self.world.drop = None
                with patch.dict(os.environ, self.env, clear=True):
                    run = operations.get(error["details"]["operation_id"])
                    # A retained prior-format plan has its original request but a bare target.
                    old = run["driver_plan"]["target"]
                    old["object_id"] = name
                    old["extensions"]["creo"].pop("object_claims")
                    operations.update(run)
                    assembly = old | {"object_id": name + ".asm"}
                    if kind is None:
                        with self.assertRaises(Error):
                            driver.require_clear(assembly)
                    else:
                        driver.require_clear(assembly)
                refused = self.cli(
                    "model", "save", "--model", name + ".prt", "--dry-run", status=6
                )["error"]
                self.assertEqual(refused["details"]["conflict"], "unresolved_operation")

    def test_failed_public_receipt_commit_never_exposes_completed_on_disk(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        plan = self.cli(*args, "--dry-run")["data"]
        update = operations.update

        def fail_public(run):
            if run.get("driver_receipt") is not None:
                raise Error("E_IO", "injected public receipt storage unavailable")
            return update(run)

        with patch("creo_cli.operations.update", side_effect=fail_public):
            error = self.cli(*args, "--confirm", plan["confirm_token"], status=6)["error"]
        op_id = plan["preview"]["operation_id"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        with patch.dict(os.environ, self.env, clear=True):
            durable = operations.get(op_id)
        self.assertIn(durable["status"], operations.UNRESOLVED)
        self.assertIsNone(durable.get("driver_receipt"))
        record = self.cli("operation", "show", "--id", op_id)["data"]["operation_status"]
        self.assertEqual(record["status"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)
        self.cli(
            "operation",
            "resolve",
            "--id",
            op_id,
            "--outcome",
            "applied",
            "--evidence",
            "independent native feature and dimensional evidence checked",
        )
        self.gated("model", "save", "--model", "block")

    def test_public_receipt_record_size_failure_retains_unresolved_domain_checkpoint(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        original = operations.update

        def restricted(run):
            if run.get("driver_receipt") is not None:
                with patch("creo_cli.operations.MAX_RECORD_BYTES", 1):
                    return original(run)
            return original(run)

        with patch("creo_cli.operations.update", side_effect=restricted):
            self.cli(*args, "--confirm", preview["confirm_token"], status=6)
        shown = self.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"][
            "operation_status"
        ]
        self.assertEqual(shown["status"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)

    def test_sqlite_public_commit_io_failure_leaves_disk_and_show_unresolved(self):
        self.part()
        args = ("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        preview = self.cli(*args, "--dry-run")["data"]
        open_db = operations._db

        class Database:
            def __init__(self):
                self.db = open_db()

            def execute(self, sql, values=()):
                if (
                    sql.startswith("UPDATE")
                    and json.loads(values[1]).get("driver_receipt") is not None
                ):
                    raise sqlite3.OperationalError("injected read-only final write")
                return self.db.execute(sql, values)

            def close(self):
                self.db.close()

        with patch("creo_cli.operations._db", side_effect=Database):
            error = self.cli(*args, "--confirm", preview["confirm_token"], status=6)["error"]
        self.assertEqual(error["code"], "E_OUTCOME_UNKNOWN")
        shown = self.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"][
            "operation_status"
        ]
        self.assertEqual(shown["status"], "unknown")
        self.cli("model", "save", "--model", "block", "--dry-run", status=6)


@pytest.mark.parametrize(
    "failure", ["background_changed", "background_read_failed", "end_check_exception"]
)
def test_native_runner_success_exit_requires_tail_protection(failure):
    """Execute the actual exit expression with the state left by a late runner failure."""
    source = Path(__file__).resolve().parents[1] / "scripts/run_native_cases.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    exit_call = next(
        n.value
        for n in reversed(tree.body)
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "exit"
    )
    state = {
        "native_checked": True,
        "cases": [{"status": "passed"}, {"status": "passed"}],
        "blocker": {"error_type": "RuntimeError", "message": failure},
        "background_preservation": {"passed": False},
    }
    namespace = {"results": state}
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.Import, ast.ImportFrom)) and (
            not isinstance(n, ast.FunctionDef) or n.name == "acceptance_exit_code"
        ):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            exec(compile(ast.Module(body=[n], type_ignores=[]), str(source), "exec"), namespace)
    code = eval(compile(ast.Expression(exit_call.args[0]), str(source), "eval"), namespace)
    assert code != 0, state


@pytest.mark.parametrize("fault", ["changed", "read_failure", "late_validation_exception"])
def test_actual_protection_reader_failures_preserve_local_cases_but_fail_summary(fault):
    path = Path(__file__).resolve().parents[1] / "scripts/run_native_cases.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    namespace = {}
    functions = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef)
        and n.name in ("verify_background", "acceptance_exit_code")
    ]
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    report = {"native_checked": True, "cases": [{"status": "passed"}, {"status": "passed"}]}

    def read():
        if fault != "changed":
            raise OSError(fault)
        return {"original.prt": {"value": 49}}

    with pytest.raises((RuntimeError, OSError)) as captured:
        namespace["verify_background"](report, {"original.prt": {"value": 48}}, read)
    report["blocker"] = {
        "error_type": type(captured.value).__name__,
        "message": str(captured.value),
    }
    assert namespace["acceptance_exit_code"](report) != 0
    assert report["status"] == "failed" and report["summary"]["case_passed"] == 2
    assert report["summary"]["complete_acceptance_passed"] is False
