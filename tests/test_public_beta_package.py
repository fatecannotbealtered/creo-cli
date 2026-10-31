"""Actual final ZIP consumer checks; no CAD/Java executable is launched."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Packaged Windows beta")


def declared_package():
    value = os.environ.get("CREO_TRIAL_SCOPE_PACKAGE")
    if not value:
        pytest.skip("Set CREO_TRIAL_SCOPE_PACKAGE to the actual extracted final ZIP")
    return Path(value)


def test_actual_packaged_reference_changelog_and_skill_family(tmp_path):
    package = declared_package()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CREO_CLI_")}
    env["CREO_CLI_CONFIG_DIR"] = str(tmp_path / "history")
    env["CREO_CLI_WORKSPACE"] = str(tmp_path)
    for args in [("reference",), ("changelog",)]:
        result = subprocess.run(
            [str(package / "cli/creo-cli.exe"), *args, "--compact"],
            env=env,
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=60,
        )
        answer = json.loads(result.stdout)
        assert result.returncode == 0 and answer["ok"]
        if args == ("reference",):
            assert answer["data"]["release_readiness"]["level"] == "beta"
            assert answer["data"]["release_readiness"]["fcc_coverage"] == "partial"
            assert len(answer["data"]["commands"]) == 129
    skills = package / "cli/skills"
    assert {p.name for p in skills.iterdir()} == {
        "creo-cli",
        "creo-modeling",
        "creo-assembly",
        "creo-drawing",
        "creo-presentation",
        "creo-delivery",
    }
    assert all((p / "SKILL.md").is_file() for p in skills.iterdir())


def test_actual_public_initializer_refuses_tampered_component_before_install(tmp_path):
    source = declared_package()
    package = tmp_path / "isolated/package"
    shutil.copytree(source, package)
    jar = package / "cli/service-bundle/creo-cli-service.jar"
    jar.write_bytes(jar.read_bytes() + b"CORRUPTED OFFLINE FIXTURE")
    history = tmp_path / "history"
    history.mkdir()
    work = package.parent / "run"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CREO_CLI_")}
    result = subprocess.run(
        [
            shutil.which("pwsh"),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(package / "cli/examples/engineering/Initialize-CreoWorkspace.ps1"),
            "-WorkRoot",
            str(work),
            "-HistoryDirectory",
            str(history),
            "-CreoRoot",
            str(tmp_path / "not-installed/creo"),
            "-JavaHome",
            str(tmp_path / "not-installed/java"),
        ],
        env=env,
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=30,
    )
    assert result.returncode != 0
    assert b"Package integrity mismatch" in result.stderr
    assert not work.exists()
    assert not list(history.iterdir())
