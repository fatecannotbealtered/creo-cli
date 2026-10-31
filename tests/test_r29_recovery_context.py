"""R29 recovery preconditions and process-only context, using isolated observations.

No real Creo, service build, real history or OS process inventory is used.
"""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from creo_cli import deployment, operations, service_bundle
from creo_cli.core import canonical
from tests.test_commands import Base
from tests.test_driver_public_schemas import validate
from tests.test_native_read_context import (
    PARAMETER_ARGS,
    arm,
    pending_context,
    unknown_saved_operation,
)
from tests.test_pending_inspection_storage import case as case
from tests.test_pending_inspection_storage import inspection_args, storage_fault


def evidence(name, value):
    destination = os.environ.get("R29_RECOVERY_CONTEXT_EVIDENCE")
    if destination:
        root = Path(destination)
        root.mkdir(parents=True, exist_ok=True)
        (root / (name + ".json")).write_bytes(canonical(value) + b"\n")


class R29ContextProjection(Base):
    def controlled_installation(self):
        target, host, java = self.ws / "components", self.ws / "creo", self.ws / "java"
        target.mkdir()
        host_exe = host / "Common Files/x86e_win64/obj/xtop.exe"
        java_exe = java / "bin/java.exe"
        for path in (host_exe, java_exe):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"isolated executable identity fixture; never executed")
        files = {}
        for name in (service_bundle.JAR, service_bundle.DLL):
            path = target / name
            path.write_bytes(("isolated component " + name).encode())
            files[name] = {"sha256": service_bundle.sha256(path)}
        state = self.ws / "runtime"
        state.mkdir()
        (state / "native-loaded-image.txt").write_text(
            "12\n" + str(target / service_bundle.DLL) + "\n", encoding="utf-8"
        )
        # 2026-10-17T00:00:00Z and one second earlier, in Windows FILETIME.
        created = str(
            116444736000000000 + int(datetime(2026, 10, 17, tzinfo=UTC).timestamp()) * 10_000_000
        )
        rows = [
            {
                "pid": 13,
                "parent_pid": 12,
                "creation_filetime": created,
                "actual_image": str(java_exe),
                "actual_process_machine": "0x8664",
            },
            {
                "pid": 12,
                "parent_pid": 1,
                "creation_filetime": str(int(created) - 10_000_000),
                "actual_image": str(host_exe),
                "actual_process_machine": "0x8664",
            },
        ]
        health = {
            "ok": True,
            "service": "creo-cli",
            "source_sha256": "c" * 64,
            "runtime_class": "controlled.App",
            "service_instance_id": "controlled-r29-instance",
            "process_id": 13,
            "process_started_at": "2026-10-17T00:00:00Z",
            "runtime_configuration_contract": 1,
            "runtime_configuration": {"portable_profile": True, "state_directory": str(state)},
        }
        manifest = {
            "files": files,
            "java_app_class": "controlled.App",
            "component_source_sha256": health["source_sha256"],
        }
        with (
            patch.dict(os.environ, self.env, clear=True),
            patch("creo_cli.deployment.files", return_value=(target, manifest, {"files": files})),
            patch("creo_cli.deployment.Client") as client,
            patch("creo_cli.runtime_identity.processes", return_value=rows),
            patch(
                "creo_cli.runtime_identity.modules", return_value=[str(target / service_bundle.DLL)]
            ),
            patch(
                "creo_cli.runtime_identity.open_jars",
                return_value=[str(target / service_bundle.JAR)],
            ),
        ):
            client.return_value.__enter__.return_value.health.return_value = health
            observed = deployment.inspect(target, creo=host, java_home=java)
        self.assertTrue(observed["loaded_verified"], observed)
        return observed

    def context_for(self, observed):
        with (
            patch("creo_cli.deployment.inspect", return_value=observed),
            patch("creo_cli.transport.Client.op", side_effect=AssertionError("no CAD dispatch")),
        ):
            result = self.cli("context", "--installation", str(self.ws / "components"))["data"]
        validate("urn:tool-driver-cli-spec:context:2.0", result)
        self.assertFalse(self.world.ops())
        return result

    def test_connected_context_projects_actual_identity_without_offline_placeholders(self):
        observed = self.controlled_installation()
        result = self.context_for(observed)
        environment = result["environment"]
        self.assertEqual(environment["connection"]["status"], "connected")
        self.assertEqual(environment["connection"]["instance_id"], "controlled-r29-instance")
        self.assertEqual(result["extensions"]["creo"]["installation"], observed)
        components = environment["components"]
        self.assertTrue(all(row["identity_status"] == "observed" for row in components))
        self.assertFalse(any("offline" in row.get("reason", "") for row in components))
        for role in ("application", "runtime"):
            rows = [row for row in components if row["role"] == role]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["location"], "running")
        for words in ("process/component identity only", "no CAD reader", "getter completion"):
            self.assertIn(words, environment["connection"]["reason"])
        evidence("connected-process-only", result)

    def test_files_and_health_handshake_do_not_establish_loaded_connection(self):
        observed = self.controlled_installation()
        observed["loaded_verified"] = False
        observed.pop("runtime_identity")
        result = self.context_for(observed)
        self.assertEqual(result["environment"]["connection"]["status"], "unavailable")
        components = result["environment"]["components"]
        for role in ("service", "plugin"):
            self.assertTrue(
                all(
                    row["identity_status"] == "observed"
                    for row in components
                    if row["role"] == role
                )
            )
        for role in ("application", "runtime"):
            self.assertEqual(
                next(row for row in components if row["role"] == role)["identity_status"],
                "unavailable",
            )
        evidence("files-and-handshake-only", result)

    def test_missing_runtime_evidence_cannot_be_replaced_by_loaded_flag(self):
        complete = self.controlled_installation()
        for missing in (
            "observed_runtime",
            "runtime_pin",
            "runtime_identity",
            "process_identities",
            "component_files",
        ):
            with self.subTest(missing=missing):
                incomplete = deepcopy(complete)
                incomplete.pop(missing)
                result = self.context_for(incomplete)
                self.assertEqual(result["environment"]["connection"]["status"], "unavailable")
                self.assertIsNone(result["environment"]["connection"]["instance_id"])

    def test_offline_context_remains_unobserved_and_does_not_create_state(self):
        state = Path(self.env["CREO_CLI_CONFIG_DIR"])
        result = self.cli("context")["data"]
        validate("urn:tool-driver-cli-spec:context:2.0", result)
        self.assertEqual(result["environment"]["connection"]["status"], "unknown")
        for row in result["environment"]["components"]:
            if row["role"] != "cli":
                self.assertEqual(
                    (row["identity_status"], row["location"]), ("unavailable", "unknown")
                )
        self.assertFalse(state.exists())
        self.assertFalse(self.world.ops())
        evidence("offline-unobserved", result)


def test_unknown_write_show_lists_conditional_cad_inspection_without_claiming_recovery(case):
    ident, _ = unknown_saved_operation(case)
    case.world.events.clear()
    shown = case.cli("operation", "show", "--id", ident)["data"]
    guidance = shown["recovery_guidance"]
    assert guidance["query"] == ["operation", "query", "--id", ident, "--model", "block.prt"]
    assert guidance["resolve_preview"]
    assert "missing native-read evidence does not prove" in guidance["local_history"]
    assert (
        "independently confirm the original call has ended" in guidance["cad_readback_precondition"]
    )
    assert (
        "unknown write alone does not establish a pending read" in guidance["inspection_dispatch"]
    )
    assert case.world.ops() == []
    evidence("unknown-write-conditional-guidance", shown)


def test_retained_pending_show_omits_cad_commands_and_requires_independent_completion(case):
    preview = case.cli(*PARAMETER_ARGS, "--dry-run")["data"]
    state = arm(case, "busy_started")
    case.world.events.clear()
    error = case.cli(*PARAMETER_ARGS, "--confirm", preview["confirm_token"], status=6)["error"]
    pending = pending_context(error, "busy_started", "parameter.list")
    assert case.world.ops()[state["event_index"] :] == ["parameter.list"]
    events = list(case.world.events)
    shown = case.cli("operation", "show", "--id", preview["preview"]["operation_id"])["data"]
    assert case.world.events == events
    guidance = shown["recovery_guidance"]
    assert guidance["native_read_error"] == pending
    assert guidance["query"] is None
    assert guidance["resolve_preview"] is None
    assert "original call ended" in guidance["cad_readback_precondition"]
    assert "missing native-read evidence does not prove" in guidance["local_history"]
    assert "single Client only" in guidance["guard_scope"]
    evidence("retained-pending-local-show", shown)


def test_nonpending_unknown_write_can_be_queried_and_registered_normally(case):
    ident, original = unknown_saved_operation(case)
    case.world.events.clear()
    query = case.cli("operation", "query", "--id", ident, "--model", "block")["data"]
    assert query["evidence_id"]
    assert query["proves_original_write_postconditions"] is False
    assert case.world.ops() == ["model.show", "feature.list", "dimension.list"]
    args = (
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "applied",
        "--evidence",
        "controlled independent saved-file inspection of the original target",
    )
    preview = case.cli(*args, "--dry-run")["data"]
    case.cli(*args, "--confirm", preview["confirm_token"])
    shown = case.cli("operation", "show", "--id", ident)["data"]["operation_status"]
    assert shown["receipt"] == original["receipt"]
    assert shown["resolution"]["outcome"] == "applied"
    evidence("nonpending-unknown-normal-recovery", {"query": query, "shown": shown})


@pytest.mark.parametrize("mode", ("query", "resolve"))
@pytest.mark.parametrize("storage", ("permission", "error"))
def test_failed_inspection_keeps_original_receipt_and_conditionally_scoped_show(
    case, mode, storage
):
    ident, original, original_bytes, args = inspection_args(case, mode)
    read = "model.management-state" if mode == "resolve" else "model.show"
    state = arm(case, "busy_started", read=read, after="not-dispatched")
    state["after"] = True
    case.world.events.clear()
    with storage_fault(case, storage):
        error = case.cli(*args, status=8)["error"]
    pending = pending_context(error, "busy_started", read)
    details = error["details"]
    assert details["parent_operation_id"] == ident
    assert details["read_failure_evidence_retained"] is False
    assert "not acknowledged" in details["read_failure_evidence_note"]
    assert "unknown storage state" in details["read_failure_evidence_note"]
    assert "read_failure_evidence_id" not in details
    assert details["storage_error"]["code"] == "E_IO"
    for key in ("cause", "cli_invocation_id", "diagnostic_request_id", "dispatch_state"):
        assert details[key] == pending["details"][key]
    assert case.world.ops() == [read]
    events = list(case.world.events)
    shown = case.cli("operation", "show", "--id", ident)["data"]
    assert case.world.events == events
    assert shown["operation_status"]["receipt"] == original["receipt"]
    assert shown["operation_status"]["resolution"] == original["resolution"]
    # Failed inspection is separate from the immutable write history. A show
    # without pending evidence must therefore warn that this absence proves nothing.
    assert shown["recovery_guidance"]["query"]
    assert (
        "missing native-read evidence does not prove" in shown["recovery_guidance"]["local_history"]
    )
    with patch.dict(os.environ, case.env, clear=True):
        assert canonical(operations.get(ident)) == original_bytes
    evidence("pending-" + mode + "-" + storage, {"error": error, "shown": shown, "events": events})


def test_operation_reference_describes_local_show_and_cad_recovery_preconditions(case):
    for name in ("operation show", "operation query", "operation resolve"):
        reference = case.cli("reference", "--command", name)["data"]["command"]
        description = reference["description"]
        if name == "operation show":
            assert "unrecorded native getter ended" in description
            assert "--id <operation_id>" in reference["examples"][0]
        else:
            assert "independently settled first" in description
    assert (
        "CAD_precondition"
        in case.cli("reference")["data"]["extensions"]["creo"]["operation_recovery"]
    )
