"""Exact-row validation survives cache hits, tampering, corruption and database drift."""

import json
import sqlite3
from contextlib import closing

import pytest

from creo_cli import operation_index, operations
from creo_cli.core import Error


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setenv("CREO_CLI_CONFIG_DIR", str(tmp_path))
    run = operations.begin("model save", "part.prt", {}, "http://127.0.0.1:9057")
    return tmp_path, run


def test_cache_hit_does_not_decode_unchanged_rows_and_retains_unresolved(history, monkeypatch):
    _, run = history
    first = operations.summaries(write_cache=True)
    monkeypatch.setattr(
        operations,
        "_decode_record",
        lambda body: pytest.fail("unchanged original row decoded again"),
    )
    assert operations.summaries() == first
    assert first[0]["status"] == "running"
    assert first[0]["operation_id"] == run["operation_id"]


@pytest.mark.parametrize(
    "tamper", ["body", "header", "cache_status", "cache_signature", "cache_body"]
)
def test_tampering_never_hides_an_unresolved_record(history, tamper):
    root, run = history
    operations.summaries(write_cache=True)
    db_path = root / (operations.DATABASE if tamper in ("body", "header") else operation_index.NAME)
    with closing(sqlite3.connect(db_path)) as db:
        if tamper == "body":
            db.execute("UPDATE operations SET body=?", ('{"bad":true}',))
        elif tamper == "header":
            db.execute("UPDATE operations SET status='completed'")
        elif tamper == "cache_status":
            body = json.loads(db.execute("SELECT body FROM summaries").fetchone()[0])
            body["status"] = "completed"
            db.execute("UPDATE summaries SET body=?", (json.dumps(body),))
        elif tamper == "cache_signature":
            db.execute("UPDATE summaries SET signature='invalid'")
        else:
            db.execute("UPDATE summaries SET body='null'")
        db.commit()
    if tamper in ("body", "header"):
        with pytest.raises(Error) as caught:
            operations.summaries()
        assert caught.value.code == "E_INTEGRITY"
    else:
        assert (
            operations.selected_runs(statuses=operations.UNRESOLVED)[0]["operation_id"]
            == run["operation_id"]
        )


def test_original_row_change_invalidates_cache_and_preserves_new_state(history):
    _, run = history
    operations.summaries(write_cache=True)
    run["status"] = "unknown"
    operations.update(run)
    assert operations.summaries()[0]["status"] == "unknown"


def test_read_only_discovery_never_creates_cache_or_secret(history):
    root, _ = history
    assert operations.summaries()[0]["status"] == "running"
    assert not (root / operation_index.NAME).exists()
    assert not (root / "confirm.secret").exists()


def test_selected_records_and_usage_have_identical_scope_and_started_state(history):
    _, run = history
    run["driver_plan"] = {"authorization_scope_id": "actual-scope"}
    run["started_at"] = operations.now()
    operations.update(run)
    row = operations.summaries(write_cache=True)[0]
    assert row["scope_id"] == "actual-scope"
    assert row["started_at"] == run["started_at"]
    assert operations.selected_runs(commands=("unrelated",)) == []
    assert operations.selected_runs(commands=("model save",)) == [
        operations.get(run["operation_id"])
    ]
