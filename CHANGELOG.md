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

- The drawing domain, read and write: sheets (`current-sheet`, `sheet-size`, `sheet-scale`, `sheet-format`, `select-sheet`, `regenerate-sheet`, `scale-sheet`, `set-sheet-format`, `delete-sheet`), views (`list-views`, `view-location`, `view-scale`, `view-sheet`, `view-bound-box`, `rename-view`, `move-view`, `scale-view`, `delete-view`), models (`current-model`, `set-current-model`, `delete-models`) and symbols (`list-symbols`, `symbol-loaded`, `load-symbol`, `place-symbol`, `delete-symbol-definition`, `delete-symbol-instance`). Where the upstream lets a target be omitted to mean every one of them -- `delete_models` without a model, `scale_view` without a view -- the name is required here, and view coordinates are declared in drawing units rather than assumed.
- Result schemas fall back to the response type CREOSON publishes, generated into `creo_cli/creoson_spec_ids.py` with the blob identities, so a new command no longer needs hand-written entries that are only wrong at runtime. The hand-maintained table keeps the deliberate differences: ids as strings, enriched keys, composed reads and real nested shapes.

- Model editing: renaming and erasing models, unit systems (`set-length-units`, `set-mass-units`, `set-unit-system`, `create-unit-system`), materials (`load-material`, `delete-material`, and the wildcard material reads), relations (`set-relations`, `set-postregen-relations`, `postregen-relations`), parameters (`copy`, `delete`, `set-designated`), dimensions (`list-basic`, `copy`, `set-text`, `show`), features (`delete`, `set-param`, `delete-param`, `group-features`, `pattern-features`), notes (`set`, `copy`, `delete`) and layers (`show`, `delete`).
- The unit setters require an explicit `convert`, with no default. That flag decides whether 40 mm becomes 40 in or 1.575 in, and silently reinterpreting every dimension in a model is not a decision to inherit from a wire default. The units are read back afterwards rather than trusting the setter.

- Data exchange and the last session settings: `import file` brings STEP/IGES/NEUTRAL/PV geometry in as a new model, `import program` loads a Pro/Program file, `export 3dpdf` joins the staged no-clobber exports, and `export plot`/`export program` are verified against the location Creo reports because they name their own output. `creo std-color`/`set-std-color` complete the session settings.

- `doctor` now reports on the CREOSON route, not only the VB API adapter: `creo_api_toolkit`, `creoson_service` and `creoson_workspace`. The toolkit check names the installer component that actually ships J-Link rather than J-Link itself -- there has been no separate J-Link installer since Creo 4.0 -- and when Creo is delivered by an application-streaming player it says the toolkit cannot be added at all, because such a build has no installer to re-run. Its lookup walks directory entries instead of stat-ing a composed path, since those streamed installations answer `stat` with FileNotFoundError while enumeration of the same location works; a probe written the obvious way reports a good installation as missing.

- `contract/otk-interface.json` and `scripts/gen_otk_interface.py`: an index of the Creo Object TOOLKIT Java library derived by introspecting the shipped `otk.jar` -- 5433 element ids, 314 feature types, the element-tree creation classes, and a jar digest tying it all to one library. J-Link, which CREOSON is built on, cannot create features; the licensed OTK surface can, and its element-tree API lives in a `wfc` namespace J-Link does not ship at all. The class counts record that split honestly: 981 in `pfc`, 2122 in `wfc`. `tests/test_otk_interface.py` pins the constants the modelling commands will be built on, so a Creo upgrade that renumbers one fails loudly rather than silently building the wrong feature.

- `docs/CREO_SETUP.md`: what to select when installing Creo, and why it matters. The API this CLI runs on is an optional installer component -- *Creo Object TOOLKIT Java*, under API Toolkits -- and there is no entry called "J-Link" to look for, since J-Link ships inside it. That naming gap is the single most expensive thing to discover after the fact, so it is now stated in both READMEs, in `docs/CREOSON.md` where the startup failure it causes is described, and in the Skill, which is told to stop and say so before doing anything else when `doctor` reports the toolkit missing.

- The Creo-side service is confirmed reachable on a real installation: Creo loads it, the Object TOOLKIT Java licence activates for it, and it reports the live session -- `{"ok":true,"session_reachable":true,"creo_version":"Creo 13","creo_build":"2026163"}`. No PTC unlocking request was needed; `Parametric/bin/protk_unlock.bat` signs the jar locally against the seat's own TOOLKIT licence.
- The toolkit answers only on the thread Creo drives. Creo spawns the application's JVM and talks to it over a socket serviced by the thread it calls into, so a probe issued from an HTTP handler never returns -- and with handlers on the dispatch thread it took the whole endpoint down with it. The session is now read once during `start()`, where that thread is ours, and reported from cache; handlers run on a small pool so one slow call cannot wedge the rest.
- `otk_service/`: the Creo-side half of the tool, a loopback HTTP endpoint that runs *inside* Creo. It lives there because that is the only place the geometry-creating API exists -- `otk.jar` ships no asynchronous connection at all, and the asynchronous library `pfcasync.jar` carries only the `pfc` domain, which cannot create features. `scripts/build_otk_service.py` compiles it against a real installation's `otk.jar`, never bundling one, and writes the `protk.dat` Creo registers it from. Being a guest in another process sets the rules: `start` returns promptly, nothing throws back into Creo, the listener binds loopback explicitly, and diagnostics go to a file because there is no console. `/health` touches no Creo API and `/session` makes exactly one, so a failure says which of the two questions failed rather than blurring them.

### Changed
- Published CREOSON coverage rises from 42 of 175 functions to 150; the CLI now exposes 183 leaf commands. That is every function the release publishes except twenty-five deliberate omissions, each named with its reason in `tests/test_creoson_interface.py` and enforced by a test, so the uncovered surface cannot grow silently.
- Both READMEs describe the full command surface and state plainly what is left out and why.
- `file.erase_not_displayed` is deliberately not exposed: it takes no target at all and erases whatever is not on screen, which is the wildcard mutation this adapter refuses everywhere else.
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
