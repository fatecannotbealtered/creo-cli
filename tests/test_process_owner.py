"""Expired locks may be recovered only for a proven dead/reused CLI identity."""

from unittest.mock import patch

import pytest

from creo_cli.process_owner import abandoned


@pytest.mark.parametrize(
    "snapshot,expires,expected",
    [
        ({123: "birth-a"}, "2000-01-01T00:00:00Z", False),
        ({123: "birth-b"}, "2000-01-01T00:00:00Z", True),
        ({}, "2000-01-01T00:00:00Z", True),
        ({123: None}, "2000-01-01T00:00:00Z", False),
        ({}, "2999-01-01T00:00:00Z", False),
        (None, "2000-01-01T00:00:00Z", False),
    ],
)
def test_birth_and_deadline_are_both_required(snapshot, expires, expected):
    with patch("creo_cli.process_owner.births", return_value=snapshot):
        assert abandoned({"pid": 123, "birth": "birth-a", "expires_at": expires}) is expected


def test_unknown_legacy_owner_never_expires_by_guess():
    assert abandoned({"pid": 123, "birth": None}) is False
