"""Exercise bundled examples through main's real parser, without dispatching handlers.

This is argument-contract coverage only. Model names, request files and receipt IDs in
examples are declared inputs; these tests never claim Creo behavior or submit writes.
"""

from __future__ import annotations

import importlib
import json
import shlex

import pytest

from creo_cli import registry

cli_main = importlib.import_module("creo_cli.main")


class ParsedExample(BaseException):
    """Stop only after real argparse and public flag validation have succeeded."""

    def __init__(self, command, opts):
        self.command = command
        self.opts = opts


EXAMPLES = [
    pytest.param(command.path, example, id=f"{command.path}:{index + 1}")
    for command in registry.COMMANDS
    for index, example in enumerate(command.describe()["examples"])
]


def stop_after_flag_validation(monkeypatch):
    check_flags = cli_main.check_flags

    def checked(command, opts):
        check_flags(command, opts)
        raise ParsedExample(command, opts)

    monkeypatch.setattr(cli_main, "check_flags", checked)


@pytest.mark.parametrize(("path", "example"), EXAMPLES)
def test_registered_example_reaches_public_dispatch_boundary(path, example, monkeypatch, capsys):
    """Both preview and confirm spellings parse; no command handler can run."""
    argv = shlex.split(example)
    assert argv.pop(0) == "creo-cli"
    stop_after_flag_validation(monkeypatch)
    try:
        cli_main.main(argv)
    except ParsedExample as parsed:
        assert parsed.command.path == path
        assert parsed.opts["compact"] is True
        if parsed.command.write and path != "operation resolve":
            assert parsed.opts["dry_run"] or parsed.opts["confirm"] == "<confirm_token>"
        return
    output = capsys.readouterr()
    pytest.fail(f"example did not reach dispatch: {example}\n{output.out}{output.err}")


def test_public_reference_publishes_the_examples_under_test(capsys):
    assert cli_main.main(["reference", "--compact"]) == 0
    published = json.loads(capsys.readouterr().out)
    assert published["ok"] is True
    assert [
        (row["path"], example)
        for row in published["data"]["commands"]
        for example in row["examples"]
    ] == [(case.values[0], case.values[1]) for case in EXAMPLES]


@pytest.mark.parametrize("path", ["model show", "dimension list"])
def test_required_model_is_rejected_by_the_public_parser(path, monkeypatch, capsys):
    stop_after_flag_validation(monkeypatch)
    assert cli_main.main([*path.split(), "--compact"]) == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "E_USAGE"
    assert error["details"]["problem"] == "missing_parameter"


@pytest.mark.parametrize(
    ("path", "text"),
    [("drawing note add", "4X M6"), ("drawing note edit", "4X M6 THRU")],
)
def test_multiword_note_examples_keep_one_text_argument(path, text, monkeypatch):
    example = registry.BY_PATH[path].describe()["examples"][0]
    stop_after_flag_validation(monkeypatch)
    with pytest.raises(ParsedExample) as parsed:
        cli_main.main(shlex.split(example)[1:])
    assert parsed.value.opts["text"] == text
