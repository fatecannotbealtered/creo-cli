"""Creation writes its first native version; receipt facets must retain that fact."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from tests.test_commands import ROOT, Base


class CreationPersistence(Base):
    def test_first_version_drift_never_claims_saved_or_exports_old_digest(self):
        for kind, extension in (("part", "prt"), ("assembly", "asm")):
            for mutation in ("bytes", "replace", "delete"):
                with self.subTest(kind=kind, mutation=mutation):
                    name = f"{kind}_{mutation}"
                    model = name + "." + extension
                    file = self.ws / (model + ".1")
                    args = (kind, "create", "--name", name, "--units", "mmns")
                    pre = self.cli(*args, "--dry-run")["data"]
                    original = self.world.op
                    changed = False

                    def drift(
                        op, request, original=original, model=model, mutation=mutation, file=file
                    ):
                        nonlocal changed
                        result = original(op, request)
                        if op == "model.show" and request["model"] == model and not changed:
                            changed = True
                            if mutation == "delete":
                                file.unlink()
                            elif mutation == "replace":
                                other = file.with_suffix(".new")
                                other.write_bytes(file.read_bytes())
                                os.replace(other, file)
                            else:
                                file.write_bytes(file.read_bytes() + b"external change")
                        return result

                    with patch.object(self.world, "op", side_effect=drift):
                        error = self.cli(*args, "--confirm", pre["confirm_token"], status=6)[
                            "error"
                        ]
                    receipt = error["details"]["receipt"]
                    self.assertIn(receipt["outcome"]["persistence"], ("unknown", "partial"))
                    self.assertEqual(receipt["artifacts"], [])
                    self.assertIsNone(receipt["extensions"]["creo"]["domain_result"]["artifact"])
                    ident = pre["preview"]["operation_id"]
                    fresh = subprocess.run(
                        [sys.executable, "-m", "creo_cli", "operation", "show", "--id", ident],
                        cwd=ROOT,
                        env=self.env,
                        capture_output=True,
                        text=True,
                        timeout=20,
                    )
                    self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)
                    shown = json.loads(fresh.stdout)["data"]["operation_status"]["receipt"]
                    self.assertEqual(shown["outcome"], receipt["outcome"])
                    self.assertEqual(shown["artifacts"], [])
                    self.cli("model", "close", "--model", model, "--dry-run", status=6)
                    self.assertNotIn("model.save", self.world.ops())

    def test_created_part_and_assembly_first_version_is_saved(self):
        for kind in ("part", "assembly"):
            with self.subTest(kind=kind):
                data = self.gated(kind, "create", "--name", "new_" + kind, "--units", "mmns")[
                    "data"
                ]
                self.assertTrue(Path(data["result"]["artifact"]["path"]).is_file())
                self.assertFalse(data["result"]["modified"])
                self.assertTrue(data["persisted"])
                self.assertEqual(data["receipt"]["outcome"]["persistence"], "saved")
                self.assertIn("persist", data["receipt"]["effects"])

    def test_change_without_persist_scope_cannot_create_version(self):
        path = Path(self.env["CREO_CLI_SCOPE_FILE"])
        value = json.loads(path.read_text(encoding="utf8"))
        value["effects"] = ["observe", "session", "change"]
        path.write_text(json.dumps(value), encoding="utf8")
        args = ("part", "create", "--name", "not_authorized", "--units", "mmns")
        pre = self.cli(*args, "--dry-run")["data"]
        self.assertFalse(pre["preview"]["can_apply"])
        self.cli(*args, "--confirm", pre["confirm_token"], status=4)
        self.assertNotIn("part.create", self.world.ops())
        self.assertEqual(list(self.ws.glob("not_authorized.prt.*")), [])

    def test_saved_state_is_independently_read_not_setter_echo(self):
        original = self.world.op

        def dirty(op, request):
            result = original(op, request)
            if op == "model.show" and result["model"] == "dirty.prt":
                result["modified"] = True
            return result

        with patch.object(self.world, "op", side_effect=dirty):
            result = self.gated("part", "create", "--name", "dirty", "--units", "mmns")["data"]
        self.assertTrue(result["result"]["modified"])
        self.assertFalse(result["persisted"])
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertEqual(len(list(self.ws.glob("dirty.prt.*"))), 1)
        self.assertNotIn("model.save", self.world.ops())

    def test_dirty_assembly_has_first_file_but_requires_explicit_save(self):
        original = self.world.op

        def dirty(op, request):
            result = original(op, request)
            if op == "model.show" and result["model"] == "dirty_assembly.asm":
                result["modified"] = True
            return result

        with patch.object(self.world, "op", side_effect=dirty):
            result = self.gated(
                "assembly", "create", "--name", "dirty_assembly", "--units", "mmns"
            )["data"]
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "unsaved")
        self.assertFalse(result["persisted"])
        self.assertEqual(len(list(self.ws.glob("dirty_assembly.asm.*"))), 1)
        self.assertNotIn("model.save", self.world.ops())
