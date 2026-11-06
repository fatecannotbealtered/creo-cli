# Changelog

All notable changes to creo-cli are recorded here, in the Keep a Changelog format; versions follow Semantic Versioning.

## [Unreleased]

### Added

- The creo-cli project, built on tool-driver-cli-spec 1.0.5.
- Read commands: `model get`, `feature list`, `feature get`, `geometry list`, `distance get`, `dimension list`, `parameter list`, `relation list`, `material list` and `component list`. Every list pages with `--limit` (at most 100) and `--offset`. The feature, dimension, geometry and distance commands take parts and assemblies, `component list` takes assemblies, and `reference` shows it; other documents are refused before Creo is asked.
- Write commands: `dimension update` (value and tolerance), `parameter update`, `feature update` (suppress, resume, rename), `model export` (STEP, IGES, STL, PDF), which runs as a long job, and `model render` (JPEG).
- The session and document commands `session list`, `session get`, `doc list`, `doc get`, `doc open`, `doc save` and `doc close`, and `plugin get`, `plugin install` and `plugin remove`. `session list` asks every running Creo at the same time, each within its own limit, so one that hangs does not hold up the others, and looks for a blocking dialog on every call. Documents report their kind (part, assembly or drawing). `doc open` and `doc save` run as long jobs, since a large assembly can take Creo more than a minute; `doc save` checks that the save wrote a new version file. Opening a model while another of that name is open, or closing one another open model uses, is refused with `E_CONFLICT` and the conflict `application_state`.
- The host component: an Object TOOLKIT Java application for Creo Parametric 13.4 that speaks host protocol 1.2.0 over a named pipe only the current Windows user can open. It ships as source in `plugin/source/`; `plugin install` builds it with a JDK 25, unlocks it with the user's own license and installs it outside the state directory, under `%LOCALAPPDATA%\creo-cli\host`.
- Builtin knowledge for Creo Parametric: units, saving, relations, geometry references, materials, loading the host component, display, licenses and common dialogs.
- Live tests on round practice models (disc.prt, plate.prt, pair.asm, disc.drw), each sketch one circle, and the folder they live in as an authorized target; pair.asm has the datum names of disc.prt, so the commands that take both run the same rows on both. The read-back rows change the result from outside while the tool waits.
- Evaluation questions on the practice part: reading its size, a scoped change, a change saved as its own step, and a knowledge lookup.

### Removed

- The Skills `creo-assembly`, `creo-delivery`, `creo-drawing`, `creo-modeling` and `creo-presentation` of the earlier creo-cli 1.1.0-beta.1. This release starts again and leaves no stubs for them: delete those folders from your Skills folders, such as `~/.claude/skills`.
