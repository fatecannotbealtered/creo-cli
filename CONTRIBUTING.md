# Contributing

Use Python 3.11+ and a clean source checkout. Portable development requires no
third-party packages. Run `python scripts/test.py`, `python scripts/version.py
--check`, and `python -m compileall -q creo_cli scripts tests`. These tests use
isolated state directories and interface-shaped native substitutes.

The proposed GitHub CI matrix covers Linux, Windows and macOS with Python 3.11
and 3.13. Creating workflow files is not evidence that this matrix has run.
A formatter/linter configuration is included; a lint/format quality gate and
dependency audit must be established before release. Do not claim them green
from a compile check. The repository has not been run through Ruff in this build.

For each public behavior, add a command-level success test plus argument, safety
and relevant failure cases. Preserve the single registry and update typed schemas.
Do not expand native feature claims based solely on mocks. Store real native
logs only after removing private paths and model data, clearly naming tested
versions, conditions and limitations. Work on disposable models only.

`package.json` is the version source. Prepare root CHANGELOG, run
`python scripts/version.py --sync`, review derived changes and check them. Do not
hand-edit the runtime changelog, lock versions or Skill version metadata.
Keep README and README_zh aligned. Commit small cohesive changes with evidence.
Never commit CAD binaries, credentials, state databases or confirmation tokens.

Do not tag or publish while scripts/release_gate.py is red. Publishing the source
repository is distinct from releasing software; no package publication is requested
by the initial repository bootstrap. Consult docs/ROADMAP.md for acceptance work.
