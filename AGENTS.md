# AGENTS.md

English | [中文](AGENTS_zh.md)

This file is for coding Agents that work on the creo-cli project. Read it before changing anything.

## Bare minimum to obey

1. Never edit a pinned copy: `.agent/`, `contract/driver-contract.json`, `creo_cli/_driver/`, `licenses/`, and `scripts/spec.py`, `build.py`, `pack.py`, `platforms.py` and `release_gate.py`. They come unchanged from one tool-driver-cli-spec release. To move to another release, run `python scripts/spec.py sync <version>`, which replaces them all together.
2. Never edit generated content by hand: `contract/commands.json`, the command maps in the README and the Skills, the badge row, the info card, the risk block, the support matrix and the evidence index. Change their source, then run `python scripts/spec.py generate`.
3. Register every domain command in `creo_cli/commands/` with all its effects, its modes, the unit quantity of every physical parameter, and its target type. Mark a change the application cannot take back as `irreversible`. Never lower a confirmation tier.
4. Give every domain command a behavior matrix in `tests/matrix/`. The `normal` row of a write command is its sample.
5. Before every commit, run `python -m ruff check .`, `python scripts/spec.py check`, `python -m unittest discover -s tests` and `python scripts/spec.py suites`. All four must pass. Never skip, weaken or edit a conformance test.
6. Run live tests on the real application only on the targets listed under Authorized Targets in `docs/E2E.md`. Add a target or write the scope file for live runs only when the person explicitly asks you to in their own message, and only once they agree to the content you showed; otherwise propose it in chat and let them write it. The evaluation runner writes the scope file each question needs.
7. Tests set `CREO_CLI_STATE_DIR` to a new temporary directory and never touch the real state directory.
8. Never commit secrets, license files or keys, or customer and project files you are not allowed to share, not even inside evidence.
9. Scripts and tests that start subprocesses on Windows pass `CREATE_NO_WINDOW`.
10. Add an entry under `[Unreleased]` in `CHANGELOG.md` for every change.
11. Write code, code comments, commit messages, command output and error messages in English.

## This project

creo-cli drives Creo Parametric, versions >=13.4 <13.5, in these modes:

- `session`: drives running instances of Creo Parametric.

Where the code lives:

- Domain commands: `creo_cli/commands/`
- Adapter layer: `creo_cli/adapter/`
- Host component source: `plugin/`
- Driver runtime, a pinned copy: `creo_cli/_driver/`

How the adapter reaches Creo Parametric:

- Creo's toolkit (Object TOOLKIT Java) works only inside Creo and only on its main thread. So every read and write of a model runs in the host component, `plugin/source/`, which the runtime reaches over a named pipe with the host protocol. `creo_cli/adapter/` only finds the installation (`probe`), lists the running `xtop.exe` processes and the dialogs that block them (`sessions`), and installs the host component (`plugin_*`).
- In the host, toolkit calls run only in tasks handed to `MainThread`, never on a pipe thread. Never pass a null Java string to Creo: it crashes. The package `com.fateforge.creocli.host.core` must not use Creo's classes, so it compiles and is tested without Creo (`tests/test_host_protocol.py`).
- The host component ships as source only. `plugin install` compiles `plugin/source/` with the user's JDK 25 against their `otk.jar` and unlocks the JAR with their own license (`creo_cli/adapter/build.py`); never commit a JAR or any other binary to `plugin/`. After changing `plugin/source/`, run `python scripts/spec.py generate` to update `plugin/manifest.json`, then `plugin install` again for live runs.
- Creo loads the host component only at start. After `plugin install`, a person restarts Creo; the tool never does (DSEC-052).

The common commands are listed in the Commands section of `CONTRIBUTING.md`. Live tests use only the targets under Authorized Targets in `docs/E2E.md`; this file lists none.
