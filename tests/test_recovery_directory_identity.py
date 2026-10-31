"""Replay the complete generation04 recovery map without Creo or old runtime access."""

import copy
import json

import pytest

from tests import test_recovery_startup_isolation as fixture

pytestmark = fixture.pytestmark

# Verbatim scalar recovery map from the retained generation04 native observation.
# FIRST-COLD-START-RECOVERY-SEPARATOR-FAILURE.json SHA-256:
# 6c421b323700a9b74eaa4bbf4dafb9c87e954cfffda4d6f59eddaf71114d86a7
CAPTURED = {
    "complete": True,
    "workflow_root": (
        r"D:/creo-work"
        r"\acceptance-04\runtime-01\wfroot"
    ),
    "last_session_directory_path": (
        r"D:/creo-work"
        "\\acceptance-04\\runtime-01\\session-history\\"
    ),
    "last_session_directory_path_value_count": 1,
    "last_session_retrieval": "YES",
    "workflow_root_source": "Java process environment inherited from owned Creo launcher",
    "configuration_source": (
        "BaseSession.GetConfigOptionValues(last_session_directory_path)/"
        "GetConfigOption(last_session_retrieval)"
    ),
    "last_session_directory_path_readback": "observed",
    "last_session_retrieval_readback": "observed",
}


@pytest.mark.parametrize(
    "variant,accepted",
    [
        ("captured", True),
        ("without_ending", True),
        ("forward_separator", True),
        ("both_expected_endings", True),
        ("wrong_parent", False),
        ("quoted", False),
        ("relative", False),
        ("control", False),
    ],
)
def test_captured_native_directory_identity_preserves_raw_readback(tmp_path, variant, accepted):
    code, _, _, _, _ = fixture.base(tmp_path)
    expected_root = CAPTURED["workflow_root"]
    expected_history = CAPTURED["last_session_directory_path"].rstrip("\\")
    actual = copy.deepcopy(CAPTURED)
    field = "last_session_directory_path"
    if variant == "without_ending":
        actual[field] = expected_history
    elif variant == "forward_separator":
        actual[field] = actual[field].replace("\\", "/")
        actual["workflow_root"] = (expected_root + "\\").replace("\\", "/")
    elif variant == "both_expected_endings":
        expected_root += "\\"
        expected_history += "\\"
        actual["workflow_root"] += "\\"
    elif variant == "wrong_parent":
        actual[field] = actual[field].replace("acceptance-04", "acceptance-03")
    elif variant == "quoted":
        actual[field] = '"' + actual[field] + '"'
    elif variant == "relative":
        actual[field] = r"..\runtime-01\session-history"
    elif variant == "control":
        actual["workflow_root"] += "\n"
    code += (
        f"$workflowRootPath={fixture.ps(expected_root)};"
        f"$lastSessionPath={fixture.ps(expected_history)};"
        f"$response=ConvertFrom-Json {fixture.ps(json.dumps({'recovery_configuration': actual}))};"
        "$answer=try{$raw=Require-RecoveryReadback $response;@{accepted=$true;actual=$raw}}"
        "catch{@{accepted=$false}};$answer|ConvertTo-Json -Depth 12"
    )
    result = fixture.shell(code)
    assert result["accepted"] is accepted
    if accepted:
        assert result["actual"] == actual
