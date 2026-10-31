"""Actual packaged initializer/EXE, controlled HTTP only. Never starts Creo or Java."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.fixture import Server, World

FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Packaged Windows helper/EXE")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, **options):
    result = subprocess.run(command, capture_output=True, creationflags=FLAGS, **options)

    def decode(raw):
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode(
                "gb18030"
            )  # Windows PowerShell diagnostics may use the OEM code page.

    return subprocess.CompletedProcess(
        result.args, result.returncode, decode(result.stdout), decode(result.stderr)
    )


def emit(case, label, value):
    trace = os.environ.get("CREO_TRIAL_SCOPE_TRACE")
    if not trace:
        return

    def redact(item):
        if isinstance(item, dict):
            return {
                k: "<REDACTED_TOKEN>" if k in {"confirm_token", "service_token"} else redact(v)
                for k, v in item.items()
            }
        if isinstance(item, list):
            return [redact(v) for v in item]
        return item

    output = Path(trace)
    output.mkdir(parents=True, exist_ok=True)
    (output / (case + "-" + label + ".json")).write_text(
        json.dumps(redact(value), indent=2) + "\n", encoding="utf-8"
    )


@pytest.fixture
def trial(tmp_path, request):
    declared = os.environ.get("CREO_TRIAL_SCOPE_PACKAGE")
    if not declared:
        pytest.skip("Set CREO_TRIAL_SCOPE_PACKAGE to an extracted complete candidate")
    package = tmp_path / "isolated 中文 path" / "package"
    shutil.copytree(Path(declared), package)
    # Source regression only: record the override. Final package verification omits it.
    override = os.environ.get("CREO_TRIAL_SCOPE_INITIALIZER")
    helper = package / "cli/examples/engineering/Initialize-CreoWorkspace.ps1"
    if override:
        shutil.copyfile(override, helper)
        manifest_path = package / "PACKAGE-MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest["files"][helper.relative_to(package).as_posix()] = {
            "sha256": digest(helper),
            "bytes": helper.stat().st_size,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    work = package.parent / "run"
    work.mkdir()
    history = tmp_path / "controlled-history"
    history.mkdir()
    # Required path markers, deliberately not executable CAD/Java binaries.
    creo = tmp_path / "dependencies/creo"
    java = tmp_path / "dependencies/java"
    for path in [creo / "Parametric/bin/parametric.exe", java / "bin/java.exe"]:
        path.parent.mkdir(parents=True)
        path.write_bytes(b"OFFLINE PATH MARKER, MUST NEVER BE EXECUTED")
    world = World(work)
    server = Server(world)
    try:
        environment = {k: v for k, v in os.environ.items() if not k.startswith("CREO_CLI_")}
        command = [
            shutil.which("pwsh"),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(helper),
            "-PackageRoot",
            str(package),
            "-WorkRoot",
            str(work),
            "-HistoryDirectory",
            str(history),
            "-CreoRoot",
            str(creo),
            "-JavaHome",
            str(java),
            "-Port",
            server.url.rsplit(":", 1)[1],
        ]
        result = run(command, env=environment, timeout=90)
        name = request.node.name
        emit(
            name,
            "initialization",
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "initializer_sha256": digest(helper),
                "EXE_sha256": digest(package / "cli/creo-cli.exe"),
                "source_override": override,
                "package_source": declared,
                "CAD_or_Java_process_started": False,
            },
        )
        assert result.returncode == 0, result.stderr
        declaration = json.loads((work / "environment.json").read_text(encoding="utf-8-sig"))
        environment.update(declaration["environment_variables"])
        token = work / "runtime-1/service-token"
        token.parent.mkdir()
        token.write_text(world.token, encoding="ascii")
        part = world.part("block.prt")
        part["volume"] = 8000.0  # Synthetic fixture data, never a native model edit.
        world.write_version(work, "block.prt", part)
        world.active = "block.prt"
        yield {
            "package": package,
            "work": work,
            "world": world,
            "env": environment,
            "case": name,
            "init_command": command,
            "declaration": declaration,
        }
    finally:
        server.close()


def preview(trial, label, output):
    command = [
        str(trial["package"] / "cli/creo-cli.exe"),
        "artifact",
        "render",
        "--model",
        "block.prt",
        "--view",
        "current",
        "--output",
        str(output),
        "--dry-run",
        "--json",
        "--compact",
        "--timeout",
        "60",
    ]
    result = run(command, env=trial["env"], timeout=75)
    answer = json.loads(result.stdout)
    emit(
        trial["case"],
        label,
        {
            "command": command,
            "returncode": result.returncode,
            "stdout": answer,
            "stderr": result.stderr,
        },
    )
    assert result.returncode == 0 and answer["ok"] is True, answer.get("error")
    return answer["data"]["preview"]


def test_sibling_package_run_grants_exact_public_render_staging_only(trial):
    work, package = trial["work"], trial["package"]
    scope_path = work / "scope.json"
    original = scope_path.read_bytes()
    scope = json.loads(original.decode("utf-8-sig"))
    assert not (package / "PROJECTS").exists()
    assert not list((work / "projects").iterdir())
    workspace = Path(trial["env"]["CREO_CLI_WORKSPACE"])
    staging = workspace / ".creo-cli/staging"
    good = preview(trial, "authorized-preview", work / "images/allowed.jpg")
    assert good["can_apply"] is True, good["extensions"]["creo"]["scope_missing"]
    assert workspace == work.parent == package.parent
    assert list(map(Path, scope["roots"])) == [work, package, staging]
    assert list(map(Path, scope["outputs"])) == [work, staging]
    assert any(Path(item["path"]) == staging for item in good["outputs"])
    assert workspace not in map(Path, scope["roots"] + scope["outputs"])
    for name in ["unauthorized", ".creo-cli/staging-neighbor"]:
        unauthorized = workspace / name
        unauthorized.mkdir(parents=True, exist_ok=True)
        refused = preview(trial, name.replace("/", "-"), unauthorized / "no.jpg")
        assert refused["can_apply"] is False
        assert refused["extensions"]["creo"]["scope_missing"]["paths"]
        assert scope_path.read_bytes() == original
    assert not list(work.glob("images/*.jpg"))
    assert "model.render" not in trial["world"].ops()
    emit(
        trial["case"],
        "checks",
        {
            "scope": scope,
            "public_preview_staging": str(staging),
            "unauthorized_paths_refused": True,
            "scope_unchanged_after_previews": True,
            "render_dispatches": 0,
        },
    )


def test_refused_preview_does_not_repair_or_reinitialize_existing_scope(trial):
    work = trial["work"]
    path = work / "scope.json"
    scope = json.loads(path.read_text(encoding="utf-8-sig"))
    staging = Path(trial["env"]["CREO_CLI_WORKSPACE"]) / ".creo-cli/staging"
    # Controlled omission reproduces the old boundary. It never touches an engineer's scope.
    for key in ["roots", "outputs"]:
        scope[key] = [value for value in scope[key] if Path(value) != staging]
    path.write_text(json.dumps(scope), encoding="utf-8")
    omitted = path.read_bytes()
    refused = preview(trial, "omitted-staging-preview", work / "images/refused.jpg")
    assert refused["can_apply"] is False
    assert staging in map(Path, refused["extensions"]["creo"]["scope_missing"]["paths"])
    # The packaged operation helper must stop without confirmation or scope repair.
    script = """
$ErrorActionPreference='Stop'
$d=Get-Content -LiteralPath $env:TEST_DECLARATION -Raw|ConvertFrom-Json -AsHashtable
. (Join-Path $d.package 'cli/examples/engineering/Invoke-CreoCli.ps1')
$runArgs=@{
  ExecutablePath=(Join-Path $d.package 'cli/creo-cli.exe')
  EvidenceDirectory=$env:TEST_EVIDENCE;Environment=$d.environment_variables;TimeoutSeconds=75
}
$run=New-CreoCliRun @runArgs
try {
  $a=@('artifact','render','--model','block.prt','--view','current')
  $a+=@('--output',$env:TEST_OUTPUT,'--timeout','60')
  $null=Invoke-CreoCliWrite -Run $run -Label denied -Arguments $a
  throw 'Unexpected authorization'
} catch {
  if(-not $run.Blocked -or $run.BlockReason -ne 'preview_not_applicable'){throw}
  $answer=@{blocked=$run.Blocked;reason=$run.BlockReason;pending=$run.PendingInvocations.Count}
  $answer|ConvertTo-Json -Compress
}
"""
    result = run(
        [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
        env=dict(
            trial["env"],
            TEST_DECLARATION=str(work / "environment.json"),
            TEST_EVIDENCE=str(work / "evidence/refusal"),
            TEST_OUTPUT=str(work / "images/helper-refused.jpg"),
        ),
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "blocked": True,
        "reason": "preview_not_applicable",
        "pending": 0,
    }
    assert not (work / "evidence/refusal/denied-confirm.stdout.json").exists()
    assert path.read_bytes() == omitted
    again = run(
        trial["init_command"],
        env=trial["env"],
        timeout=30,
    )
    assert again.returncode != 0
    assert "preserve it and choose a new trial workspace" in again.stderr
    assert path.read_bytes() == omitted
    assert "model.render" not in trial["world"].ops()
    emit(
        trial["case"],
        "no-auto-repair",
        {
            "helper_stdout": json.loads(result.stdout),
            "reinitialize_returncode": again.returncode,
            "reinitialize_stderr": again.stderr,
            "scope_unchanged": True,
            "render_dispatches": 0,
            "scope": scope,
        },
    )
