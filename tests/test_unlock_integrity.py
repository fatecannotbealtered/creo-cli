"""A real observed false-zero-exit regression; no signing tool or Creo is run."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.build_native_sketch import unlock


class UnlockIntegrity(unittest.TestCase):
    def test_machine_detection_error_with_zero_exit_is_rejected(self):
        response = SimpleNamespace(
            returncode=0, stdout=b"ERROR Cannot detect what machine type you have.\n", stderr=b""
        )
        with (
            patch("scripts.build_native_sketch.subprocess.run", return_value=response),
            self.assertRaises(RuntimeError),
        ):
            unlock(Path("installed-creo"), Path("owned-candidate.dll"))

    def test_child_environment_preserves_current_directory_protection_and_parent(self):
        response = SimpleNamespace(
            returncode=0, stdout=b"Successfully unlocked application.\n", stderr=b""
        )
        with (
            patch.dict(
                os.environ,
                {"NoDefaultCurrentDirectoryInExePath": "1", "PROCESSOR_ARCHITECTURE": "AMD64"},
            ),
            patch("scripts.build_native_sketch.subprocess.run", return_value=response) as run,
        ):
            before = dict(os.environ)
            self.assertIn(
                "Successfully unlocked", unlock(Path("installed-creo"), Path("owned-candidate.dll"))
            )
            child_environment = {
                key.upper(): value for key, value in run.call_args.kwargs["env"].items()
            }
            self.assertEqual(child_environment["NODEFAULTCURRENTDIRECTORYINEXEPATH"], "1")
            self.assertEqual(dict(os.environ), before)
