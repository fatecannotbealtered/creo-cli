# Changelog

All notable changes to creo-cli are recorded here, in the Keep a Changelog format; versions follow Semantic Versioning.

## [Unreleased]

### Added

- The creo-cli project, generated from tool-driver-cli-spec 1.0.0.
- Read commands: `model get`, `feature list`, `feature get`, `geometry list`, `distance get`, `dimension list`, `parameter list`, `relation list`, `material list` and `component list`.
- Write commands: `dimension update` (value and tolerance), `parameter update`, `feature update` (suppress, resume, rename), `model export` (STEP, IGES, STL, PDF) and `model render` (JPEG).
- The session and document commands `session list`, `session get`, `doc list`, `doc get`, `doc open`, `doc save` and `doc close`, and `plugin get`, `plugin install` and `plugin remove`.
- The host component: an Object TOOLKIT Java application for Creo Parametric 13.4 that speaks the host protocol over a named pipe only the current Windows user can open. It ships as source; `plugin install` builds it with a JDK 25 and unlocks it with the user's own license.
- Builtin knowledge for Creo Parametric: units, saving, relations, geometry references, materials, loading the host component, display, licenses and common dialogs.
- Live tests on round practice models (disc.prt, plate.prt, pair.asm, disc.drw), each sketch one circle, and the folder they live in as an authorized target.
