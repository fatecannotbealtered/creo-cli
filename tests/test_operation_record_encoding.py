"""Private lossless storage encoding; public logical receipts and old rows stay intact."""

import base64
import hashlib
import json
import os
import sqlite3
import zlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from creo_cli import driver, operations
from creo_cli.core import Error, canonical, digest, redact
from tests.test_commands import RECT, Base


def run_record(*, size=4 * 1024 * 1024 + 64):
    return {
        "operation_id": "a" * 32,
        "command": "controlled storage",
        "status": "unknown",
        "native": {
            "untrusted": "x" * size,
            "_creo_cli_operation_record": {"version": "native literal, not storage"},
        },
    }


def encoded(raw, **overrides):
    return canonical(
        {
            operations._RECORD_MARKER: "creo-cli",
            "version": 1,
            "codec": "zlib+base64",
            "logical_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "payload": base64.b64encode(zlib.compress(raw)).decode(),
            **overrides,
        }
    )


def test_small_rows_keep_exact_original_format_and_nested_native_keys_are_literals():
    run = run_record(size=20)
    raw = canonical(redact(run))
    assert operations._encode_record(run) == raw
    assert operations._decode_record(raw) == run


def test_oversized_full_record_roundtrips_losslessly_under_physical_bound():
    run = run_record()
    raw = canonical(redact(run))
    physical = operations._encode_record(run)
    assert len(raw) > operations.MAX_RECORD_BYTES
    assert len(physical) <= operations.MAX_RECORD_BYTES
    assert canonical(operations._decode_record(physical)) == raw
    assert operations.MAX_LOGICAL_RECORD_BYTES == 8 * 1024 * 1024


@pytest.mark.parametrize(
    "problem",
    (
        "version",
        "codec",
        "length",
        "sha",
        "base64",
        "truncated",
        "trailing",
        "unknown_key",
        "logical_limit",
        "illegal_json",
        "nested_root",
    ),
)
def test_corrupt_or_unsupported_encoding_fails_closed(problem):
    raw = canonical(run_record(size=20))
    value = json.loads(encoded(raw))
    if problem == "version":
        value["version"] = 2
    elif problem == "codec":
        value["codec"] = "unknown"
    elif problem == "length":
        value["logical_bytes"] += 1
    elif problem == "sha":
        value["sha256"] = "b" * 64
    elif problem == "base64":
        value["payload"] = "!invalid!"
    elif problem == "truncated":
        value["payload"] = base64.b64encode(zlib.compress(raw)[:-2]).decode()
    elif problem == "trailing":
        value["payload"] = base64.b64encode(zlib.compress(raw) + b"trailing").decode()
    elif problem == "unknown_key":
        value["unexpected"] = True
    elif problem == "logical_limit":
        value["logical_bytes"] = operations.MAX_LOGICAL_RECORD_BYTES + 1
    elif problem == "illegal_json":
        value = json.loads(encoded(b'{"unterminated":'))
    else:
        value = json.loads(encoded(encoded(raw)))
    with pytest.raises(Error) as caught:
        operations._decode_record(canonical(value))
    assert caught.value.code == "E_INTEGRITY"


def test_inflation_cannot_exceed_existing_eight_mib_even_with_false_declared_length():
    bomb = b"x" * (operations.MAX_LOGICAL_RECORD_BYTES + 4096)
    raw = encoded(bomb, logical_bytes=1)
    assert len(raw) < operations.MAX_RECORD_BYTES
    with pytest.raises(Error) as caught:
        operations._decode_record(raw)
    assert caught.value.code == "E_INTEGRITY"


def test_over_nested_or_duplicate_json_is_an_integrity_failure():
    for raw in (b"[" * 2000 + b"0" + b"]" * 2000, b'{"operation_id":"a","operation_id":"b"}'):
        with pytest.raises(Error) as caught:
            operations._decode_record(encoded(raw))
        assert caught.value.code == "E_INTEGRITY"


def test_encoding_refuses_unbounded_logical_or_incompressible_physical_record():
    with pytest.raises(Error) as caught:
        operations._encode_record(run_record(size=operations.MAX_LOGICAL_RECORD_BYTES))
    assert caught.value.code == "E_IO"
    noisy = run_record(size=0)
    noisy["native"]["untrusted"] = base64.b64encode(os.urandom(7 * 1024 * 1024 // 2)).decode()
    assert len(canonical(noisy)) <= operations.MAX_LOGICAL_RECORD_BYTES
    with pytest.raises(Error) as caught:
        operations._encode_record(noisy)
    assert caught.value.code == "E_IO"


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(tmp_path))
    db = operations._db()
    db.close()
    return tmp_path


@pytest.mark.parametrize("invalid", ("opid", "status", "row_id", "row_status", "row_command"))
def test_malformed_record_or_sql_identity_mismatch_blocks_reads(local_store, invalid):
    run = run_record(size=20)
    ident, command, status = run["operation_id"], run["command"], run["status"]
    if invalid == "opid":
        run["operation_id"] = "bad"
    elif invalid == "status":
        run["status"] = "fictional_success"
    elif invalid == "row_id":
        ident = "b" * 32
    elif invalid == "row_status":
        status = "completed"
    else:
        command = "other command"
    db = operations._db()
    db.execute(
        "INSERT INTO operations VALUES(?,?,?,?)",
        (ident, command, status, encoded(canonical(run)).decode()),
    )
    db.close()
    with pytest.raises(Error) as caught:
        operations.all_runs()
    assert caught.value.code == "E_INTEGRITY"


def test_failed_commit_keeps_original_unknown_and_never_fake_completes(local_store):
    original = operations.begin("controlled storage", "fixture.prt", {}, "fixture-only")
    original["status"] = "unknown"
    operations.update(original)
    wanted = deepcopy(original) | {
        "status": "completed",
        "observations": "x" * (4 * 1024 * 1024 + 64),
    }
    before = canonical(operations.get(original["operation_id"]))
    failed = Mock()
    failed.execute.side_effect = sqlite3.OperationalError("controlled store failure")
    with patch.object(operations, "_db", return_value=failed), pytest.raises(Error) as caught:
        operations.update(wanted)
    assert caught.value.code == "E_IO"
    assert operations.get(original["operation_id"])["status"] == "unknown"
    assert canonical(operations.get(original["operation_id"])) == before


class TransparentPublicStorage(Base):
    def test_get_all_runs_show_query_preserve_full_logical_record_without_rewriting_old_row(self):
        self.part()
        made = self.gated(
            "feature", "extrude", "--model", "block.prt", "--request", self.request(RECT)
        )["data"]
        ident = made["operation_id"]
        with patch.dict(os.environ, self.env, clear=True):
            small = operations.get(ident)
            db = operations._db()
            old_body = db.execute("SELECT body FROM operations WHERE id=?", (ident,)).fetchone()[0]
            db.close()
            operations.get(ident)
            operations.all_runs()
            db = operations._db()
            assert (
                db.execute("SELECT body FROM operations WHERE id=?", (ident,)).fetchone()[0]
                == old_body
            )
            db.close()
            big = deepcopy(small)
            big["driver_receipt"]["extensions"]["creo"]["lossless_test"] = "x" * (
                4 * 1024 * 1024 + 64
            )
            operations.update(big)
            db = operations._db()
            physical = db.execute("SELECT body FROM operations WHERE id=?", (ident,)).fetchone()[0]
            db.close()
            assert len(physical.encode()) <= operations.MAX_RECORD_BYTES
            assert operations.get(ident) == big
            assert operations.all_runs()[0] == big
        shown = self.cli("operation", "show", "--id", ident)["data"]["operation_status"]
        self.assertEqual(shown["receipt"], big["driver_receipt"])
        queried = self.cli("operation", "query", "--id", ident, "--model", "block.prt")["data"]
        self.assertEqual(queried["receipt_sha256"], digest(big))


def test_exact_preserved_phone_plan_and_result_can_roundtrip(monkeypatch):
    seed_path = os.environ.get("CREO_RECORD_ENCODING_PHONE_SEED")
    if not seed_path:
        pytest.skip(
            "explicit read-only native evidence seed is not installed in this source checkout"
        )
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    db = sqlite3.connect(Path(seed["database"]).as_uri() + "?mode=ro", uri=True)
    body = db.execute("SELECT body FROM operations WHERE id=?", (seed["operation_id"],)).fetchone()[
        0
    ]
    db.close()
    old = json.loads(body)
    raw = Path(seed["result_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == old["result"]["sha256"]
    output = json.loads(raw)
    after = output["result"]["independent_observation"]
    binding = old["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
    candidate = deepcopy(old) | {
        "status": output["status"],
        "driver_effect_readback": after,
        "driver_effect_observed": True,
        "driver_effect_readback_source": "independent snapshot checked by this leaf verifier",
    }
    plan = SimpleNamespace(
        op="assembly.redefine-constraints",
        target=old["target"],
        binding=binding,
        before=binding["constraints_before"],
        retained_only=True,
    )
    monkeypatch.setattr(operations, "now", lambda: "2026-10-23T00:00:00Z")
    monkeypatch.setattr(driver.uuid, "uuid4", lambda: SimpleNamespace(hex="0" * 32))
    receipt = driver.make_receipt(candidate, plan, output)
    candidate.update(
        driver_receipt=receipt, finished_at="2026-10-23T00:00:00Z", driver_stage="finished"
    )
    logical = canonical(redact(candidate))
    assert len(logical) == seed["reconstructed_bytes"]
    physical = operations._encode_record(candidate)
    assert len(physical) <= operations.MAX_RECORD_BYTES
    assert canonical(operations._decode_record(physical)) == logical
    assert candidate["driver_plan"] == old["driver_plan"]
    assert candidate["driver_effect_readback"] == after
    assert len(output["verification"]["checks"]) == 402
    assert all(check["passed"] is True for check in output["verification"]["checks"])
    assert (
        old["status"] == "running"
    )  # Nothing wrote or re-signed the historical unknown projection.
