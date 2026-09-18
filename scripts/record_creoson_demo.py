"""Record actual CLI subprocesses against an explicitly simulated HTTP upstream.

This is a control-flow demo, not a real Creo run. Never deliver the fixture bytes
as native CAD, PDF or image artifacts. Outputs stay in a temporary directory.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.creoson_fixture import Server, World
from scripts.test import fingerprint
from creo_cli.creoson_catalog import BY_PATH


def record() -> dict:
    calls = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        world = World(root)
        world.loaded = ["bracket.prt"]
        (root / "bracket.drw").unlink()
        server = Server(world)
        env = dict(os.environ, CREO_CLI_CONFIG_DIR=str(root / "state"), CREO_CLI_WORKSPACE=str(root),
                   CREO_CLI_PERMISSION="write", CREO_CLI_EXPERIMENTAL_NATIVE_WRITES="1", CREO_CLI_CREOSON_URL=server.url)
        env.pop("CREO_CLI_CREOSON_SESSION", None)
        env.pop("CREO_CLI_TEST_TRACE", None)
        def sanitize(value):
            if isinstance(value, dict):
                return {k: "[confirmation token omitted]" if k == "confirm_token" else sanitize(v) for k, v in value.items()}
            if isinstance(value, list): return [sanitize(v) for v in value]
            return value.replace(str(root), "<temporary_workspace>") if isinstance(value, str) else value
        def run(*args):
            start = time.monotonic()
            result = subprocess.run([sys.executable, "-m", "creo_cli", *args, "--compact"], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=40)
            output = json.loads(result.stdout)
            assert result.returncode == 0 and output["ok"], output
            assert not result.stderr, result.stderr
            assert world.sid not in result.stdout
            safe_args = list(args)
            if "--confirm" in safe_args: safe_args[safe_args.index("--confirm") + 1] = "<confirm_token>"
            calls.append({"argv": sanitize(safe_args), "exit_code": result.returncode,
                          "duration_ms": round((time.monotonic() - start) * 1000), "stdout": sanitize(output)})
            return output["data"]
        def gate(*args):
            preview = run(*args, "--dry-run")
            return run(*args, "--confirm", preview["confirm_token"])
        try:
            run("context")
            run("creoson", "status")
            gate("creoson", "connect", "--creo-major", "10")
            bracket = {"workflow_schema": "1.0", "steps": [
                {"id": key, "command": path, "request": BY_PATH[path].example}
                for key, path in (("inspect", "dimension list"), ("pitch", "dimension set"), ("regen", "file regenerate"),
                                  ("persist", "file roundtrip"), ("step", "export step"))]}
            plan = root / "bracket-workflow.json"
            plan.write_text(json.dumps(bracket), encoding="utf-8")
            run("workflow", "validate", "--input", str(plan))
            first = gate("workflow", "run", "--input", str(plan))
            run("workflow", "status", "--operation-id", first["operation_id"])
            original = run("workflow", "result", "--operation-id", first["operation_id"], "--step-id", "inspect")
            persisted = run("workflow", "result", "--operation-id", first["operation_id"], "--step-id", "persist")
            assert original["result"]["result"]["items"][0]["value"] == 40
            assert world.models["bracket.prt"]["dimensions"][0]["value"] == 45
            assert persisted["result"]["result"]["roundtrip_verified"] is True
            drawing = root / "drawing-workflow.json"
            drawing.write_bytes((ROOT / "examples/workflow-drawing.json").read_bytes())
            run("workflow", "validate", "--input", str(drawing))
            second = gate("workflow", "run", "--input", str(drawing))
            run("workflow", "result", "--operation-id", second["operation_id"], "--step-id", "pdf")
            history = run("workflow", "history")
            assert all(item["status"] == "completed" for item in history["items"])
            assert len(world.models["bracket.drw"]["drawing_views"]) == 2
            checks = {"dimension_40_to_45": True, "selected_data_survived_fixture_reopen": True,
                      "two_drawing_views_created_in_substitute": True, "step_and_pdf_fixture_headers_published": True,
                      "earlier_step_result_retrieved": True, "all_receipts_completed": True}
        finally:
            server.close()
    return {"ok": True, "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "upstream_kind": "stateful_loopback_http_substitute", "real_creo_verified": False, "native_cad_files_generated": False,
            "cli_subprocess_count": len(calls), "http_request_count": len(world.events), "checks": checks,
            "source_fingerprint_sha256": fingerprint(), "calls": calls,
            "limitations": ["No PTC SDK, Creo, CREOSON server or license was used.",
                            "Fixture STEP/PDF/native-model bytes are intentionally not valid CAD artifacts.",
                            "Timings measure this local substitute, not Creo performance.",
                            "CLI provenance identifies the configured backend, while this harness explicitly identifies the substituted server."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    value = record()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in value.items() if k != "calls"}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
