"""Repository tooling: version sync, spec sync, packaging metadata, the Skill's declared fields."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from creo_cli import __version__

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def node(*args):
    return subprocess.run(
        [NODE, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


class Packaging(unittest.TestCase):
    def test_package_json_is_the_version_source(self):
        pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], __version__)
        self.assertEqual(pkg["bin"], {"creo-cli": "scripts/run.js"})
        self.assertEqual(set(pkg["optionalDependencies"].values()), {__version__})
        for name in pkg["optionalDependencies"]:
            self.assertTrue(name.startswith(pkg["name"] + "-"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(
            (lock["version"], lock["packages"][""]["version"]), (__version__, __version__)
        )

    def test_python_entry_points(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["scripts"]["creo-cli"], "creo_cli.main:main")
        self.assertEqual(project["dependencies"], [])
        out = subprocess.run(
            [sys.executable, "-m", "creo_cli.main", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(out.stdout)["data"]["version"], __version__)

    def test_skill_declares_the_version_it_needs(self):
        skill = (ROOT / "skills" / "creo-cli" / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill, r'(?m)^version: "' + re.escape(__version__) + '"$')
        self.assertIn('"min_version": "' + __version__ + '"', skill)

    def test_changelog_has_the_current_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(
            changelog, r"(?m)^## \[" + re.escape(__version__) + r"\] - \d{4}-\d{2}-\d{2}$"
        )


class DevelopmentScripts(unittest.TestCase):
    def test_every_python_script_starts(self):
        # They run against a live Creo, so no test exercises them end to end; this at least
        # catches an import of a module that no longer exists.
        for script in sorted((ROOT / "scripts").glob("*.py")):
            with self.subTest(script=script.name):
                out = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
                self.assertEqual(out.returncode, 0, out.stderr[-2000:])


@unittest.skipIf(NODE is None, "node is not installed")
class FleetScripts(unittest.TestCase):
    def test_every_derived_version_matches(self):
        result = node("scripts/check-version.js")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_spec_assets_and_generated_contract_are_in_sync(self):
        if shutil.which("ruff") is None:
            self.skipTest("ruff formats the generated contract module")
        result = node("scripts/check-spec.js", "--local-only")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_npm_launcher_parses(self):
        for script in ("scripts/run.js", "scripts/prepare-npm-platform-packages.js"):
            with self.subTest(script=script):
                self.assertEqual(node("--check", script).returncode, 0)


if __name__ == "__main__":
    unittest.main()
