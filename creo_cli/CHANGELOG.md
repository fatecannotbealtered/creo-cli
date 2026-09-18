# Changelog

This file is the only human-maintained change source. Runtime copies are generated.

## [Unreleased]

### Added
- `contract/creoson-interface.json`, derived by `scripts/gen_creoson_interface.py` from the specifications shipped in the CREOSON 3.0.2 release: 175 published functions and 23 nested return types, each carrying a Git blob identity. `tests/test_creoson_interface.py` holds the operation catalog to it, so an operation cannot forward an unpublished field, skip a required one, promise a response key that does not exist, or type one differently from the upstream. Deliberate deviations are enumerated with reasons rather than left implicit.
- Session and environment commands, the things a person settles before touching a model: `creo pwd`, `creo list-files`, `creo list-dirs`, `creo get-config`, `server pwd`, `file exists`, `file is-active` and `file open-errors` read; `creo cd`, `creo mkdir`, `creo rmdir` (dangerous), `creo set-config`, `file refresh` and `file repaint` write under the usual preview/confirm with readback. `creo cd` makes pointing Creo at the disposable workspace an explicit confirmed step instead of something the CLI refuses to do and the user does by hand.
- `effect: "session"` for operations that change Creo session state rather than model memory, disk or display.

- Model-reading commands, so an agent can see what a person sees on screen rather than only names and numbers: `geometry bound-box`, `geometry surfaces` and `geometry edges`; `layer list`/`layer exists`; `note list`/`note get`/`note exists`; `file accuracy`, `file unit-system`, `file has-instances`, `file simp-reps`; `parameter exists`; `feature params` and `feature param-exists`; `view list-exploded`. All observations.
- `creo_cli/creoson_spec_ids.py`, generated alongside the interface index, so command groups taken straight from the release specification cite provenance per function instead of pinning a whole group to one file's hash.

- Family tables, the way variants of a part are actually shipped: `familytable list`, `exists`, `header`, `row`, `cell`, `parents` and `tree` read; `create-instance`, `add-instance`, `set-cell` and `replace` write; `delete-instance` and `delete` are gated dangerous on top of preview/confirm. `familytable tree` pins the upstream `erase` flag false, so reading a nested table can never unload the session as a side effect, and `set-cell` requires an `expected_datatype` that is checked against the column on readback rather than letting a string land in a numeric column.

### Changed
- Published CREOSON coverage rises from 42 of 175 functions to 85; the CLI now exposes 118 leaf commands.
- `surface_id` and `edge_id` join the ids normalized to strings on output, and `geometry edges` accepts `surface_ids` as strings and converts them to the published integers on the wire, matching how `assembly transform` already handles component paths.

## [1.0.0] - 2026-09-18

### Changed
- Version line moves to 1.0.0 to match the baseline the other CAD tools in this fleet start from. No command, flag, output schema or error code changed, so nothing downstream breaks.
- Release readiness is deliberately unaffected: `reference.release_readiness` stays `unpublishable`, `doctor` still fails its `release_readiness` check, `package.json` stays private and the release workflow still has no publishing job. A 1.0.0 version line is not a stability claim; the gates in `docs/SPEC_STATUS.md` are unchanged.

### Fixed
- Test fixture and demo recorder resolve their temporary workspace root, matching what the CLI itself stores. The unresolved spelling failed every path comparison on macOS (`/var` symlink) and on Windows hosts whose temp path is an 8.3 short name.
- The write-timeout test holds its response open until the call returns instead of racing a fixed sleep against the preliminary reads, and asserts `receipt_status` so a timeout that lands before the write can no longer pass for the wrong reason.
- The HTTP substitute catches `ConnectionError` rather than two of its three subclasses, so an abandoned response no longer prints a handler traceback on Windows.

## [0.2.0] - 2026-09-18

### Added
- Independent loopback CREOSON transport with persistent connection, explicit session setup, bounded requests and no automatic retries.
- 45 typed CREOSON domain operations for files, parameters, length dimensions, feature states, materials, assembly, views, drawings and staged exports.
- Guarded isolated-part save/close/erase/reopen comparison of observed design data.
- Bounded native workflows, durable partial/unknown receipts, separate hash-verified step results and human acknowledgement of unresolved state.
- Per-operation source provenance, request examples, safe defaults and nested result schemas.
- Stateful HTTP-substitute contract tests and executable subprocess workflow evidence; no real Creo evidence is claimed.

### Changed
- Public command registry expanded from 22 to 75 leaves; original VB API and explicit JSON mock routes are preserved.
- Documentation now distinguishes backend implementation, upstream acknowledgement, selected postconditions and real deployment evidence.

### Security
- Native mutation guards bind session identity, workspace, exact requests, selected observed state and input hashes.
- Exports use isolated staging plus atomic no-clobber publication, rather than trusting an upstream overwrite check.
- Unknown native write outcomes stop automatic work; feature clipping/child defaults, wildcard targets and GUI-selection fallback are refused.
- Session identifiers are redacted from CLI output and native receipts; package remains unpublishable pending spec conformance and live evidence.

### Fixed
- Match released CREOSON response shapes for coordinate-system names, unnamed features, dimension text arrays and transform rotations.
- Surface upstream drawing-creation modal-dialog risk in machine-readable reference and previews; never confuse HTTP timeout with native cancellation.

## [0.1.0] - 2026-09-17

### Added
- Registry-driven JSON CLI with self-description, bounded queries and projected fields.
- Portable snapshots, identity-based comparisons, and explicit simulation fixtures.
- Restricted parameter and linear-dimension ChangeSets with expiring HMAC confirmation.
- Durable replay prevention, cooperative resource locking, backups and redacted audit history.
- Experimental Windows PTC VB API worker with session-bound observation checks and no implicit saves.

### Security
- Native is the default backend; native failures never silently select simulation.
- Writes default to disabled; native modifications require a second human opt-in.
- Release is unpublishable pending complete conformance and recorded live Creo evidence.

### Fixed
- Separate the internal command dispatch namespace from the public reference command filter.
- Preserve structured test evidence when live capability enumeration fails.
- Refuse repository publication from a parent checkout, non-main branch, or conflicting check/apply modes.
