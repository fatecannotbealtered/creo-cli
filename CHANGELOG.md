# Changelog

All notable changes to creo-cli are recorded here, in the Keep a Changelog format; versions follow Semantic Versioning.

## [Unreleased]

### Added

- The host component's C library, for what only Creo TOOLKIT can do. `plugin install` compiles it with Visual Studio's x64 C compiler against the Creo TOOLKIT component of the user's Creo and unlocks it with a Creo TOOLKIT development license; without them it installs the Java part alone, records why, and the commands that need the library are refused with `E_UNSUPPORTED` naming the reason. `CREO_CLI_VCVARS` names the compiler's `vcvars64.bat`.
- `session open` starts a Creo of creo-cli's own from a start folder beside the host component, as a long job, and `session close` ends a Creo as File > Exit does, refusing while a model has unsaved changes; closing a Creo creo-cli did not start is dangerous.
- `extrude create` extrudes a sketch into one named feature, adding or removing material, blind, symmetric, through all or up to a plane, along a model axis. The sketch is JSON: a plane (a datum, a face of an earlier feature such as `BASE/end`, or a surface ID), the model axis its x runs along, projected references, rectangles, circles, lines, arcs, centerlines and points, constraints and named dimensions, which go into Creo by name. A sketch that is not fully defined is refused, by the preview for rectangles and circles; a feature that does not regenerate, or would add or remove no material, is taken back. The result reports the dimensions, the change of volume, the bounding box and the faces by place.
- `shell create` hollows a part with walls of one thickness, open at the faces named; `round create` rounds edges to one radius. Faces are named by a feature and their place (`BASE/start`, `BASE/end`, `BASE/side[+x]`) or by surface ID; edges as `edge(face, face)`, `face:edges`, `face:outer-edges`, `FEATURE:edges` or by edge ID. `--depth-name`, `--thickness-name` and `--radius-name` give the key dimension a name.
- `pattern create` repeats one feature in a row along a model axis, with a count and a spacing that `--spacing-name` names.
- `plane create` makes a datum plane at a distance from a plane or face toward a model axis, or through an axis at an angle; `axis create` a datum axis where two planes cross or through a cylindrical face.
- `chamfer create` chamfers edges by one distance; `draft create` drafts faces by one angle about a hinge plane so that they narrow toward the pull direction, turning the angle's sign when Creo leaned them the other way.
- The domain Skill `creo-feature` for modeling parts feature by feature; the entry Skill `creo-cli` routes feature work to it.
- `feature delete` deletes a feature with the features that depend on it, dangerous, with all of them in the preview. `parameter create` creates a parameter; `relation update` replaces the relations, blocking a line Creo cannot evaluate and putting the old relations back when the model does not regenerate; `model update` assigns a material from the part or Creo's material library and sets the common name.
- `model check` runs Creo's ModelCHECK read-only, with its report beside the host component, and creo-cli's checks: failed, suppressed and default-named features.
- `model render --view` takes the picture in a named view (FRONT, TOP, RIGHT, DEFAULT or one saved in the model) and puts the person's view back; Creo then shows the model as modified, which the result reports.
- `geometry list --feature` gives each face its place in the feature (start, end, side), and `--role` and `--facing` filter by place and normal; `distance get` takes faces by place, such as `--from BASE/start --to BASE/end`.
- `doc create --kind part --path <file>` creates a part from Creo's metric part template, with the parameters PART_NO and DESCRIPTION, or from `--template`, writes it at once and shows it in a window. `doc save-as --output <file>` writes a copy under another name, or the model into another folder.

### Changed

- Built on tool-driver-cli-spec 1.0.6. A long job's worker retries a busy answer from Creo for up to 10 s before it sends the work, `session list` allows 2.5 s to find the running Creo processes and their dialogs, and long jobs are verified on the same terms as calls. `docs/E2E.md` starts with the fixed Authorization Rules, and Authorized Targets holds only the list.

### Fixed

- After a change, the windows of the models that changed are repainted, not only the current window.
- Creo no longer waits to exit while a creo-cli call still holds a connection to the host component.

## [1.0.0] - 2026-11-06

### Added

- The creo-cli project, built on tool-driver-cli-spec 1.0.5.
- Read commands: `model get`, `feature list`, `feature get`, `geometry list`, `distance get`, `dimension list`, `parameter list`, `relation list`, `material list` and `component list`. Every list pages with `--limit` (at most 100) and `--offset`. The feature, dimension, geometry and distance commands take parts and assemblies, `component list` takes assemblies, and `reference` shows it; other documents are refused before Creo is asked.
- Write commands: `dimension update` (value and tolerance), `parameter update`, `feature update` (suppress, resume, rename), `model export` (STEP, IGES, STL, PDF), which runs as a long job, and `model render` (JPEG); both report the file they wrote as saved and check that it exists.
- The session and document commands `session list`, `session get`, `doc list`, `doc get`, `doc open`, `doc save` and `doc close`, and `plugin get`, `plugin install` and `plugin remove`. `session list` asks every running Creo at the same time, each within its own limit, so one that hangs does not hold up the others, and looks for a blocking dialog on every call. Documents report their kind (part, assembly or drawing). `doc open` and `doc save` run as long jobs, since a large assembly can take Creo more than a minute; `doc save` checks that the save wrote a new version file and holds the newest value of each field changed since the last save. Opening a model while another of that name is open, or closing one another open model uses, is refused with `E_CONFLICT` and the conflict `application_state`.
- The host component: an Object TOOLKIT Java application for Creo Parametric 13.4 that speaks host protocol 1.2.0 over a named pipe only the current Windows user can open. Requests from several creo-cli calls take turns on Creo's main thread; one that cannot start within 1.5 s is answered `E_BUSY`. It ships as source in `plugin/source/`; `plugin install` builds it with a JDK 25, unlocks it with the user's own license and installs it outside the state directory, under `%LOCALAPPDATA%\creo-cli\host`.
- Builtin knowledge for Creo Parametric: units, saving, relations, geometry references, materials, loading the host component, display, licenses and common dialogs.
- Live tests on round practice models (disc.prt, plate.prt, pair.asm, disc.drw), each sketch one circle, and the folder they live in as an authorized target; pair.asm has the datum names of disc.prt, so the commands that take both run the same rows on both. The read-back rows change the result from outside while the tool waits.
- Evaluation questions on the practice part: reading its size, a scoped change, a change saved as its own step, and a knowledge lookup.

### Removed

- The Skills `creo-assembly`, `creo-delivery`, `creo-drawing`, `creo-modeling` and `creo-presentation` of the earlier creo-cli 1.1.0-beta.1. This release starts again and leaves no stubs for them: delete those folders from your Skills folders, such as `~/.claude/skills`.
