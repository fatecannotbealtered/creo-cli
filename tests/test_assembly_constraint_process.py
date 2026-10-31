"""Real HTTP and fresh public CLI processes against synthetic CAD objects.

Set CREO_CONSTRAINT_TEST_EXE to run the same cases against a frozen executable.
The transport and record store are real; these fixture poses are not native evidence.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from tests.fixture import MM, Refused, Server, World
from tests.test_assembly_constraint_construction_datums import add_internal, with_frames
from tests.test_assembly_constraint_policy import native_state, state_row, transform

ROOT = Path(__file__).resolve().parents[1]
SETTER = "assembly.redefine-constraints"
GETTER = "assembly.constraint-state"


class ConstraintWorld(World):
    """Independent fixture: axis-planar translations, repeated member and follower."""

    def __init__(
        self, workspace, *, owner="transfer_cell.asm", ids=(31, 74, 118, 205), rigid=False
    ):
        super().__init__(workspace)
        # Server's public health reports this exact synthetic generation. The
        # native-state payload must bind to that observation, not the policy
        # fixture's independently named generation or a later health call.
        self.service_instance_id = "fixture-generation-1"
        self.capabilities["assembly_constraint_redefinition"] = 2
        self.state = native_state(owner=owner, ids=ids, rigid=rigid)
        self.ids = ids
        self.writes = 0
        self.reads_after_write = 0
        self.mode = None
        self.journal = []
        for name in {owner, *(r["model"] for r in self.state["components"])}:
            m = self.part(name, MM)
            if name.endswith(".asm"):
                self.make_assembly(m)
            self.write_version(workspace, name, m)
        if rigid:
            for row in self.state["components"]:
                if row["model_type"] != "assembly":
                    continue
                children = []
                for child in row["rigid_children"]:
                    if child["model"] not in self.models:
                        model = self.part(child["model"], MM)
                        self.write_version(workspace, child["model"], model)
                    children.append(deepcopy(child) | {"position": deepcopy(child["transform"])})
                self.models[row["model"]]["components"] = children
        self.active = owner
        self.bind_engineering_origin()
        self.sync()

    def bind_engineering_origin(self):
        self.state.update(
            service_instance_id=self.service_instance_id,
            working_directory=str(self.cwd) + os.sep,
            working_directory_source="Session.GetCurrentDirectory",
            model_origins={name: model["origin"] for name, model in self.models.items()},
            model_origin_readback={
                name: {
                    "source": "Model.GetOrigin",
                    "read_complete": True,
                    "result_category": "returned_string",
                }
                for name in self.models
            },
        )

    def observed_reference(self, reference, *, component_side):
        observed = deepcopy(reference)
        local = component_side and observed["component_path"] == []
        observed.update(
            reference_owner_model=self.state["model"],
            reference_owner_source="ComponentFeat.WFeature.GetSolid",
            path_present=not local,
            path_root_model=None if local else self.state["model"],
            path_root_source=(
                "Selection.GetPath.returned_null" if local else "ComponentPath.GetRoot"
            ),
            path_leaf_model=(observed["model"] if observed["component_path"] else None),
            path_leaf_source=(
                "Selection.GetPath.returned_null"
                if local
                else "ComponentPath.GetLeaf"
                if observed["component_path"]
                else "not_read_for_empty_path"
            ),
        )
        return observed

    def sync(self):
        self.models[self.state["model"]]["components"] = [
            deepcopy(row) | {"position": deepcopy(row["component_path_transform"])}
            for row in self.state["components"]
        ]

    def add_construction_datums(self):
        with_frames(self.state)
        for consumer, feature, surface in (
            (self.ids[1], 941, 942),
            (self.ids[3], 951, 952),
        ):
            ref = add_internal(self.state, consumer=consumer, feature=feature, surface=surface)
            aux = ref["auxiliary"]
            self.models[self.state["model"]]["features"].append(
                {
                    "id": feature,
                    "name": f"owned_construction_{feature}",
                    "type": "FEATTYPE_DATUM_PLANE",
                    "status": "FEAT_ACTIVE",
                    "visible": False,
                    "parents": deepcopy(aux["parents"]),
                    "children": [consumer],
                    "surfaces": 1,
                }
            )
            state_row(self.state, consumer)["parents"].append(feature)
        self.write_version(self.cwd, self.state["model"], self.models[self.state["model"]])
        self.bind_engineering_origin()
        self.sync()

    def advance_construction_datums(self):
        # Independent fixture equations: all controlled transforms are identity
        # rotations, so a local consumer plane's actual world origin is its
        # local origin plus the solved occurrence translation. Keep the full
        # frame axes, source selection, fit/flip and indexed element paths.
        for ref in self.state["reference_catalog"]:
            aux = ref.get("auxiliary")
            if not aux:
                continue
            row = state_row(self.state, aux["consumer_occurrence_id"])
            constraint = row["constraints"][aux["matched_constraint_index"]]
            local = constraint["component_reference"]["plane"]["origin"]
            actual = row["component_path_transform"]["origin"]
            origin = [a + b for a, b in zip(actual, local, strict=True)]
            ref["plane"]["origin"] = deepcopy(origin)
            ref["plane"]["frame"]["origin"] = deepcopy(origin)
            aux["definition"]["constraints"][0]["offset_raw"] = constraint["offset"]
        if self.mode == "wrong_unrelated_internal":
            ref = next(
                r
                for r in self.state["reference_catalog"]
                if r.get("auxiliary", {}).get("feature_id") == 951
            )
            ref["plane"]["origin"][0] += 1
            ref["plane"]["frame"]["origin"][0] += 1

    def handle(self, op, q):
        self.journal.append({"op": op, "at_monotonic": time.monotonic(), "request": deepcopy(q)})
        if op == GETTER and self.writes:
            self.reads_after_write += 1
            if self.mode == "pending_verify":
                self.events.append((op, deepcopy(q)))
                return {
                    "ok": False,
                    "error": {
                        "code": "E_BUSY",
                        "message": "controlled started getter has not returned",
                        "started": True,
                    },
                }, True
            if self.mode == "disconnect_verify":
                self.events.append((op, deepcopy(q)))
                return None, False
        return super().handle(op, q)

    def op(self, op, q):
        if op == GETTER:
            if q["model"] != self.state["model"]:
                raise Refused("E_NOT_FOUND", "controlled owner mismatch")
            self.bind_engineering_origin()
            result = deepcopy(self.state)
            if self.mode == "missing_getter":
                state_row(result, self.ids[1])["constraints"][0].pop("assembly_side")
            if self.mode == "postverify_empty_data_to_null" and self.writes:
                # Readback fault only: do not normalize native empty strings to null.
                state_row(result, self.ids[1])["constraints"][0]["user_data"] = None
            return result
        if op == SETTER:
            if q["expected"] != self.state:
                raise Refused("E_CONFLICT", "controlled pre-setter state drift")
            if self.mode == "solver_conflict":
                raise Refused("E_VALIDATION", "controlled incompatible constraint set")
            target = state_row(self.state, q["component"])
            if target["id"] != self.ids[1]:
                raise Refused("E_VALIDATION", "this fixture edits only the declared target")
            old_constraints = deepcopy(target["constraints"])
            if len(q["constraints"]) != len(old_constraints):
                raise Refused("E_UNSUPPORTED", "controlled edit preserves the indexed set")
            updated = []
            for index, raw in enumerate(q["constraints"]):
                native = deepcopy(raw)
                for key in ("assembly_reference", "component_reference"):
                    ref = native[key]
                    path = ref["component_path"] or [target["id"]]
                    candidates = [
                        r
                        for r in self.state["reference_catalog"]
                        if r["model"] == ref["model"]
                        and r["item_id"] == ref["item_id"]
                        and r["component_path"]
                        == (path if key == "component_reference" else ref["component_path"])
                    ]
                    if len(candidates) != 1:
                        raise Refused("E_VALIDATION", "controlled reference is missing")
                    native[key]["plane"] = deepcopy(candidates[0]["plane"])
                    native[key] = self.observed_reference(
                        native[key], component_side=key == "component_reference"
                    )
                native.update(
                    native_type="ASM_CONSTRAINT_ALIGN_OFF",
                    units="mm",
                    attributes={"raw_null_default": True, "force": None, "ignore": None},
                    user_data=deepcopy(old_constraints[index]["user_data"]),
                )
                updated.append(native)
            origin = [0, 0, 0]
            for c in updated:
                plane = c["assembly_reference"]["plane"]
                axis = next(i for i, v in enumerate(plane["normal"]) if v == 1)
                origin[axis] = plane["origin"][axis] + c["offset"]
            target["constraints"] = updated
            target["component_path_transform"] = transform(origin)
            state_row(self.state, self.ids[2])["component_path_transform"] = transform(
                [origin[0] + 3, origin[1], origin[2]]
            )
            self.advance_construction_datums()
            if self.mode == "wrong_unrelated_pose":
                state_row(self.state, self.ids[3])["component_path_transform"]["origin"][1] += 0.01
            self.writes += 1
            self.sync()
            self.models[self.state["model"]]["modified"] = True
            return {
                "model": self.state["model"],
                "component": str(target["id"]),
                "regenerated": True,
            }
        return super().op(op, q)


class ProcessHarness:
    def __init__(self, root, *, owner="transfer_cell.asm", ids=(31, 74, 118, 205), rigid=False):
        self.root = root
        self.workspace = root / "独立 约束副本"
        self.workspace.mkdir()
        self.config = root / "isolated-history"
        self.world = ConstraintWorld(self.workspace, owner=owner, ids=ids, rigid=rigid)
        self.server = Server(self.world)
        token = root / "fixture-token"
        token.write_text(self.world.token, encoding="ascii")
        self.scope_file = root / "scope.json"
        self.scope = {
            "scope_id": "controlled-constraint-process",
            "tool": "creo-cli",
            "granted_by": "isolated-test",
            "granted_at": "2026-10-22T00:00:00Z",
            "expires_at": None,
            "effects": ["observe", "session", "change", "persist", "artifact"],
            "dangerous": False,
            "roots": [str(self.workspace)],
            "outputs": [str(self.workspace)],
        }
        self.scope_file.write_text(json.dumps(self.scope), encoding="utf-8")
        self.env = os.environ | {
            "CREO_CLI_CONFIG_DIR": str(self.config),
            "CREO_CLI_WORKSPACE": str(self.workspace),
            "CREO_CLI_PERMISSION": "write",
            "CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "1",
            "CREO_CLI_SERVICE_URL": self.server.url,
            "CREO_CLI_SERVICE_TOKEN_FILE": str(token),
            "CREO_CLI_SCOPE_FILE": str(self.scope_file),
            "PYTHONIOENCODING": "utf-8",
        }
        for name in ("CREO_CLI_TEST_TRACE", "CREO_CLI_EXECUTION_PROFILE"):
            self.env.pop(name, None)
        exe = os.environ.get("CREO_CONSTRAINT_TEST_EXE")
        self.command = [exe] if exe else [sys.executable, "-m", "creo_cli"]
        self.invocations = []

    @property
    def owner(self):
        return self.world.state["model"]

    @property
    def target(self):
        return str(self.world.ids[1])

    def run(self, *args, expected=None):
        started = time.monotonic()
        result = subprocess.run(
            [*self.command, *map(str, args)],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=35,
        )
        document = json.loads(result.stdout)
        assert self.world.token not in result.stdout + result.stderr
        self.invocations.append(
            {
                "args": list(map(str, args)),
                "exit": result.returncode,
                "elapsed_seconds": time.monotonic() - started,
                "response": document,
            }
        )
        if expected is not None:
            assert result.returncode == expected, document
        return document

    def edit_request(self, *, offset=12, replacement=False):
        answer = self.run(
            "assembly",
            "component",
            "show",
            "--model",
            self.owner,
            "--item",
            self.target,
            "--editable",
            expected=0,
        )
        q = deepcopy(answer["data"]["item"]["edit_request"])
        q["constraints"][0]["offset"] = offset
        if replacement:
            q["constraints"][0]["assembly_reference"]["item_id"] = 19
        return q

    def words(self, request, *, component=None):
        path = self.root / f"约束 请求{len(self.invocations)}.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return [
            "assembly",
            "component",
            "redefine",
            "--model",
            self.owner,
            "--component",
            component or self.target,
            "--request",
            str(path),
        ]

    def preview(self, request, *, component=None):
        words = self.words(request, component=component)
        answer = self.run(*words, "--dry-run", expected=0)
        return words, answer["data"]

    def close(self):
        self.server.close()
        (self.root / "PROCESS-INVOCATIONS.json").write_text(
            json.dumps(self.invocations, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.root / "HTTP-DISPATCH-JOURNAL.json").write_text(
            json.dumps(self.world.journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )


@pytest.fixture
def harness(tmp_path):
    h = ProcessHarness(tmp_path)
    try:
        yield h
    finally:
        h.close()


@pytest.mark.parametrize(
    ("owner", "ids", "rigid"),
    [
        ("transfer_cell.asm", (31, 74, 118, 205), False),
        ("indexing_frame.asm", (7, 420, 36, 901), True),
    ],
)
def test_process_query_two_different_in_place_edits_keep_repeated_member_and_follower(
    tmp_path, owner, ids, rigid
):
    h = ProcessHarness(tmp_path, owner=owner, ids=ids, rigid=rigid)
    try:
        original = deepcopy(h.world.state)
        for offset, replacement in ((12, False), (-2.25, True)):
            words, pre = h.preview(h.edit_request(offset=offset, replacement=replacement))
            result = h.run(*words, "--confirm", pre["confirm_token"], expected=0)["data"]
            assert result["receipt"]["outcome"]["change"] == "applied"
            assert result["receipt"]["outcome"]["verification"]["status"] == "passed"
            query = h.run(
                "operation",
                "query",
                "--id",
                pre["preview"]["operation_id"],
                "--model",
                h.owner,
                expected=0,
            )["data"]["observation"]["assembly_constraints_verification"]
            assert query["accepted"] is True
            assert query["can_register"] == ["applied"]
            assert state_row(h.world.state, ids[3]) == state_row(original, ids[3])
            assert (
                state_row(h.world.state, ids[2])["constraints"]
                == state_row(original, ids[2])["constraints"]
            )
        assert h.world.writes == 2
    finally:
        h.close()


@pytest.mark.parametrize(
    "kind", ["stale", "ambiguous", "invalid_ref", "direction", "influence", "authorization"]
)
def test_process_foreseeable_errors_refuse_before_setter(harness, kind):
    h = harness
    q = h.edit_request()
    component = None
    if kind == "stale":
        q["selection"]["state_revision"] = "f" * 64
    elif kind == "ambiguous":
        component = "slider.prt"
    elif kind == "invalid_ref":
        q["constraints"][0]["assembly_reference"]["item_id"] = 9999
    elif kind == "direction":
        q["constraints"][0]["assembly_side"] = "AUTOMATIC"
    elif kind == "influence":
        q["affected_occurrences"] = [h.target]
    elif kind == "authorization":
        h.scope["effects"] = ["observe"]
        h.scope_file.write_text(json.dumps(h.scope), encoding="utf-8")
    words = h.words(q, component=component)
    answer = h.run(*words, "--dry-run")
    if kind == "authorization":
        assert answer["ok"] and answer["data"]["preview"]["can_apply"] is False
        h.run(*words, "--confirm", answer["data"]["confirm_token"], expected=4)
    else:
        assert answer["ok"] is False
        assert answer["error"]["code"] in {
            "E_CONFLICT",
            "E_NOT_FOUND",
            "E_VALIDATION",
            "E_UNSUPPORTED",
        }
    assert h.world.writes == 0
    assert not any(row["op"] == SETTER for row in h.world.journal)


@pytest.mark.parametrize("mode", ["solver_conflict", "wrong_unrelated_pose"])
def test_process_conflict_or_unauthorized_motion_cannot_be_success(harness, mode):
    h = harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = mode
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    assert h.world.writes == (0 if mode == "solver_conflict" else 1)
    count = sum(row["op"] == SETTER for row in h.world.journal)
    h.run(*words, "--confirm", pre["confirm_token"])
    assert sum(row["op"] == SETTER for row in h.world.journal) == count


def test_process_missing_getter_is_incomplete_before_mutation(harness):
    h = harness
    q = h.edit_request()
    h.world.mode = "missing_getter"
    answer = h.run(*h.words(q), "--dry-run")
    assert answer["error"]["code"] == "E_VERIFY_INCOMPLETE"
    assert h.world.writes == 0


def test_process_root_internal_datum_follows_offset_and_actual_pose_with_shared_recovery(harness):
    h = harness
    h.world.add_construction_datums()
    before = deepcopy(h.world.state)
    unrelated = next(
        r for r in before["reference_catalog"] if r.get("auxiliary", {}).get("feature_id") == 951
    )
    words, pre = h.preview(h.edit_request(offset=13.625))
    normal = h.run(*words, "--confirm", pre["confirm_token"], expected=0)["data"]
    assert normal["receipt"]["outcome"]["verification"]["status"] == "passed"
    public = h.run(
        "assembly",
        "component",
        "show",
        "--model",
        h.owner,
        "--item",
        h.target,
        "--editable",
        expected=0,
    )["data"]
    actual = next(
        r for r in public["reference_catalog"] if r.get("auxiliary", {}).get("feature_id") == 941
    )
    assert actual["reference_usage"] == "protection_only"
    assert actual["plane"]["origin"] == actual["plane"]["frame"]["origin"] == [13.625, 0, 0]
    assert actual["auxiliary"]["definition"]["constraints"][0]["offset_raw"] == 13.625
    assert public["item"]["component_path_transform"]["origin"] == [13.625, 0, 0]
    assert (
        next(
            r
            for r in public["reference_catalog"]
            if r.get("auxiliary", {}).get("feature_id") == 951
        )
        == unrelated
    )
    proof = h.run(
        "operation",
        "query",
        "--id",
        pre["preview"]["operation_id"],
        "--model",
        h.owner,
        expected=0,
    )["data"]["observation"]["assembly_constraints_verification"]
    assert proof["accepted"] is True
    words, pre = h.preview(h.edit_request(offset=9.875))
    h.world.drop = SETTER
    lost = h.run(*words, "--confirm", pre["confirm_token"])
    assert lost["ok"] is False and h.world.writes == 2
    h.world.drop = None
    ident = pre["preview"]["operation_id"]
    old_receipt = h.run("operation", "show", "--id", ident, expected=0)["data"]["operation_status"][
        "receipt"
    ]
    proof = h.run("operation", "query", "--id", ident, "--model", h.owner, expected=0)["data"][
        "observation"
    ]["assembly_constraints_verification"]
    assert proof["accepted"] is True and proof["can_register"] == ["applied"]
    resolve_args = [
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "applied",
        "--evidence",
        "Fresh complete construction definition, frame and actual occurrence pose verified",
    ]
    resolve_pre = h.run(*resolve_args, "--dry-run", expected=0)["data"]
    h.run(*resolve_args, "--confirm", resolve_pre["confirm_token"], expected=0)
    shown = h.run("operation", "show", "--id", ident, expected=0)["data"]["operation_status"]
    assert shown["receipt"] == old_receipt
    assert (
        shown["extensions"]["creo"]["assembly_constraints_inspection"]["evidence_status"]
        == "verified"
    )
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.writes == 2


def test_process_unrelated_internal_datum_frame_change_cannot_pass_or_register_applied(harness):
    h = harness
    h.world.add_construction_datums()
    words, pre = h.preview(h.edit_request(offset=8.125))
    h.world.mode = "wrong_unrelated_internal"
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False and h.world.writes == 1
    receipt = answer["error"]["details"]["receipt"]
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["verification"]["status"] != "passed"
    assert "native_read_error" not in answer["error"]["details"]
    ident = pre["preview"]["operation_id"]
    queried = h.run("operation", "query", "--id", ident, "--model", h.owner, expected=0)["data"]
    proof = queried["observation"]["assembly_constraints_verification"]
    assert proof["accepted"] is False and "applied" not in proof["can_register"]
    refused = h.run(
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "applied",
        "--evidence",
        "Controlled unrelated construction frame changed outside the authorized influence",
        "--dry-run",
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] in ("E_VERIFY_FAILED", "E_VERIFY_INCOMPLETE")
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.writes == 1


def test_process_empty_native_custom_data_is_preserved_per_constraint(harness):
    h = harness
    expected = ["", None, ""]
    for constraint, value in zip(
        state_row(h.world.state, h.target)["constraints"], expected, strict=True
    ):
        constraint["user_data"] = value
    words, pre = h.preview(h.edit_request(offset=8.125))
    result = h.run(*words, "--confirm", pre["confirm_token"], expected=0)["data"]
    assert result["receipt"]["outcome"]["verification"]["status"] == "passed"
    assert [c["user_data"] for c in state_row(h.world.state, h.target)["constraints"]] == expected
    current = h.run(
        "operation",
        "query",
        "--id",
        pre["preview"]["operation_id"],
        "--model",
        h.owner,
        expected=0,
    )["data"]["observation"]["assembly_constraints_verification"]
    assert current["accepted"] is True and current["can_register"] == ["applied"]
    assert h.world.writes == 1


def test_process_postverify_empty_custom_data_changed_to_null_cannot_pass_or_register_applied(
    harness,
):
    h = harness
    state_row(h.world.state, h.target)["constraints"][0]["user_data"] = ""
    words, pre = h.preview(h.edit_request(offset=4.375))
    h.world.mode = "postverify_empty_data_to_null"
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False
    receipt = answer["error"]["details"]["receipt"]
    assert receipt["outcome"]["execution"] == "completed"
    assert receipt["outcome"]["verification"]["status"] != "passed"
    assert h.world.writes == 1
    assert state_row(h.world.state, h.target)["constraints"][0]["user_data"] == ""
    ident = pre["preview"]["operation_id"]
    current = h.run(
        "operation",
        "query",
        "--id",
        ident,
        "--model",
        h.owner,
        expected=0,
    )["data"]["observation"]["assembly_constraints_verification"]
    assert current["accepted"] is False and "applied" not in current["can_register"]
    refused = h.run(
        "operation",
        "resolve",
        "--id",
        ident,
        "--outcome",
        "applied",
        "--evidence",
        "Controlled independent readback changed empty native custom data to null",
        "--dry-run",
    )
    assert refused["ok"] is False
    assert refused["error"]["code"] in ("E_VERIFY_FAILED", "E_VERIFY_INCOMPLETE")
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.writes == 1


def test_process_write_reply_lost_query_resolve_share_fresh_predicate_without_replay(harness):
    h = harness
    words, pre = h.preview(h.edit_request())
    h.world.drop = SETTER
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False and h.world.writes == 1
    ident = pre["preview"]["operation_id"]
    original = h.run("operation", "show", "--id", ident, expected=0)["data"]["operation_status"][
        "receipt"
    ]
    h.world.drop = None
    inspected = h.run("operation", "query", "--id", ident, "--model", h.owner, expected=0)["data"]
    assert inspected["observation"]["assembly_constraints_verification"]["accepted"] is True
    evidence = (
        "Independent controlled HTTP constraints and poses observed; " + inspected["evidence_id"]
    )
    args = ["operation", "resolve", "--id", ident, "--outcome", "applied", "--evidence", evidence]
    resolve = h.run(*args, "--dry-run", expected=0)["data"]
    h.run(*args, "--confirm", resolve["confirm_token"], expected=0)
    shown = h.run("operation", "show", "--id", ident, expected=0)["data"]["operation_status"]
    assert shown["receipt"] == original
    assert (
        shown["extensions"]["creo"]["assembly_constraints_inspection"]["evidence_status"]
        == "verified"
    )
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.writes == 1


@pytest.mark.parametrize("mode", ["pending_verify", "disconnect_verify"])
def test_process_pending_first_verification_stops_later_cad_and_preserves_context(harness, mode):
    h = harness
    words, pre = h.preview(h.edit_request())
    h.world.mode = mode
    answer = h.run(*words, "--confirm", pre["confirm_token"])
    assert answer["ok"] is False and h.world.writes == 1
    pending = answer["error"]["details"]["native_read_error"]
    assert pending["details"]["operation"] == GETTER
    assert "diagnostic_request_id" not in pending["details"]
    assert "stop further CAD dispatch" in answer["error"]["details"]["next_action"]
    first = next(i for i, r in enumerate(h.world.journal) if r["op"] == SETTER)
    assert [r["op"] for r in h.world.journal[first:]] == [SETTER, GETTER]
    assert h.world.reads_after_write == 1


def test_process_final_receipt_storage_failure_retains_operation_and_zero_replay(harness):
    h = harness
    words, pre = h.preview(h.edit_request())
    ident = pre["preview"]["operation_id"]
    database = h.config / "operations.sqlite3"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "CREATE TRIGGER controlled_receipt_failure BEFORE UPDATE OF body ON operations "
            f"WHEN NEW.id='{ident}' AND json_extract(NEW.body,'$.driver_receipt') IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT,'isolated receipt failure'); END"
        )
    try:
        answer = h.run(*words, "--confirm", pre["confirm_token"])
        assert answer["ok"] is False and h.world.writes == 1
    finally:
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DROP TRIGGER controlled_receipt_failure")
    with closing(sqlite3.connect(database)) as db:
        retained = json.loads(
            db.execute("SELECT body FROM operations WHERE id=?", (ident,)).fetchone()[0]
        )
    assert retained["driver_receipt"] is None
    inspected = h.run("operation", "query", "--id", ident, "--model", h.owner, expected=0)["data"]
    assert inspected["observation"]["assembly_constraints_verification"]["accepted"] is True
    h.run(*words, "--confirm", pre["confirm_token"])
    assert h.world.writes == 1
