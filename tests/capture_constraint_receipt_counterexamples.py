"""Capture controlled fixture stdout before/after receipt repair, never native evidence.

Run: python -m tests.capture_constraint_receipt_counterexamples --output <directory>
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from tests import test_assembly_constraint_process as process
from tests.test_assembly_constraint_policy import state_row
from tests.test_assembly_constraint_receipt_binding import ReceiptWorld


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    original_run = subprocess.run
    head = original_run(
        ["git", "rev-parse", "HEAD"], cwd=process.ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    for mode in ("second_read_pose_drift", "dirty_owner_error"):
        captured = []

        def capture(*call_args, _captured=captured, **kwargs):
            result = original_run(*call_args, **kwargs)
            if "--confirm" in call_args[0]:
                _captured.append(result)
            return result

        with tempfile.TemporaryDirectory(prefix="creo-receipt-counterexample-") as root:
            with patch.object(process, "ConstraintWorld", ReceiptWorld):
                h = process.ProcessHarness(Path(root))
            try:
                words, pre = h.preview(h.edit_request())
                h.world.mode = mode
                with patch.object(process.subprocess, "run", capture):
                    answer = h.run(*words, "--confirm", pre["confirm_token"])
                result = captured[-1]
                (args.output / f"{mode}.stdout.json").write_text(result.stdout, encoding="utf8")
                (args.output / f"{mode}.stderr.txt").write_text(result.stderr, encoding="utf8")
                receipt = (
                    answer["data"]["receipt"]
                    if answer["ok"]
                    else answer["error"]["details"]["receipt"]
                )
                effect = receipt["extensions"]["creo"].get("effects_readback", {}).get("after")
                rows.append(
                    {
                        "mode": mode,
                        "source_head": head,
                        "source_files": {
                            name: hashlib.sha256((process.ROOT / name).read_bytes()).hexdigest()
                            for name in (
                                "creo_cli/assembly_constraints.py",
                                "creo_cli/engine.py",
                                "creo_cli/driver.py",
                            )
                        },
                        "process": "fresh process per invocation: " + " ".join(h.command),
                        "executable_sha256": hashlib.sha256(
                            Path(h.command[0]).read_bytes()
                        ).hexdigest(),
                        "transport": "repository real HTTP fixture",
                        "evidence_class": "controlled synthetic; not native Creo fault",
                        "exit": result.returncode,
                        "ok": answer["ok"],
                        "receipt_status": receipt["extensions"]["creo"]["legacy_status"],
                        "outcome": receipt["outcome"],
                        "postwrite_getter_origins": [
                            state_row(s, h.world.ids[3])["component_path_transform"]["origin"]
                            for s in h.world.native_reads
                        ],
                        "effects_origin": state_row(effect["native"], h.world.ids[3])[
                            "component_path_transform"
                        ]["origin"]
                        if effect
                        else None,
                        "setter_attempts": h.world.setter_attempts,
                        "owner_modified_after": h.world.models[h.owner]["modified"],
                    }
                )
            finally:
                h.close()
    (args.output / "summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(json.dumps([{k: r[k] for k in ("mode", "exit", "ok", "receipt_status")} for r in rows]))


if __name__ == "__main__":
    main()
