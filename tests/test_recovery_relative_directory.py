"""Native recovery directory syntax: one unquoted relative token, no CAD calls."""

import os

import pytest

from tests import test_recovery_startup_isolation as fixture

pytestmark = fixture.pytestmark


def relative_value(code):
    return fixture.shell(
        code + "$answer=try{$v=Get-OwnedRecoveryDirectoryValue;"
        "@{accepted=$true;value=$v;resolved=[IO.Path]::GetFullPath((Join-Path $startupPath $v))}}"
        "catch{@{accepted=$false}};$answer|ConvertTo-Json"
    )


def test_common_chinese_space_parent_does_not_enter_relative_native_token(tmp_path):
    code, _, _, runtime, _ = fixture.base(tmp_path / "中文 共同目录")
    result = relative_value(code)
    assert result["accepted"] is True
    assert result["value"] == r"..\runtime\session-history"
    assert result["resolved"] == str(runtime / "session-history")
    assert " " not in result["value"]
    assert '"' not in result["value"]
    assert result["value"].isascii()


@pytest.mark.parametrize(
    "leaf",
    [
        "runtime space",
        "运行目录",
        'runtime"quote',
        "runtime:stream",
        "runtime!comment",
        "runtime#comment",
        "runtime\ncontrol",
    ],
)
def test_unsupported_relative_path_token_refuses_before_process(tmp_path, leaf):
    code, _, _, _, _ = fixture.base(tmp_path)
    code += f"$lastSessionPath={fixture.ps(tmp_path / leaf / 'session-history')};"
    assert relative_value(code)["accepted"] is False


def test_cross_drive_relative_configuration_is_refused(tmp_path):
    code, _, _, _, _ = fixture.base(tmp_path)
    current = os.path.splitdrive(str(tmp_path))[0]
    other = "D:" if current.lower() != "d:" else "C:"
    code += f"$lastSessionPath={fixture.ps(other + '/owned/runtime/session-history')};"
    assert relative_value(code)["accepted"] is False


def test_declared_relative_value_is_retained_separately_from_absolute_expected_path(tmp_path):
    code, _, _, runtime, _ = fixture.base(tmp_path)
    result = fixture.shell(code + "Read-RecoveryIsolationSources|ConvertTo-Json -Depth 12")
    assert result["configured_directory_value"] == r"..\runtime\session-history"
    assert result["last_session_directory_path"] == str(runtime / "session-history")


@pytest.mark.parametrize("kind", ["old_quoted_prefix", "quoted_absolute", "env_quoted"])
def test_original_literal_quote_native_path_remains_rejected(tmp_path, kind):
    code, _, _, runtime, _ = fixture.base(tmp_path)
    value = fixture.response(runtime)
    actual = value["recovery_configuration"]
    if kind == "old_quoted_prefix":
        actual["last_session_directory_path"] = (
            str(tmp_path / "startup") + '\\"' + str(runtime / "session-history") + '"'
        )
    elif kind == "quoted_absolute":
        actual["last_session_directory_path"] = '"' + str(runtime / "session-history") + '"'
    else:
        actual["workflow_root"] = '"' + str(runtime / "wfroot") + '"'
    assert fixture.check_readback(code, value) is False


def test_startup_writer_uses_bound_relative_value_without_quote_unwrapping():
    starter = fixture.STARTER.read_text(encoding="utf-8")
    helper = fixture.HELPER.read_text(encoding="utf-8")
    assert (
        '"last_session_directory_path $($preflightRecord.recovery_isolation.'
        'configured_directory_value)`nlast_session_retrieval yes`n"' in starter
    )
    assert "$value.Substring(1" not in helper
