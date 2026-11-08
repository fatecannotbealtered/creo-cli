# Changelog

All notable changes to creo-cli are recorded here, in the Keep a Changelog format; versions follow Semantic Versioning.

## [Unreleased]

## [1.1.1] - 2026-11-08

### Changed

- Built on tool-driver-cli-spec 1.0.8. A long write job that a dialog stops after creo-cli sent the work ends `unknown` with `E_HUMAN_REQUIRED`, the dialog's title and the `operation resolve` command to run once the person is done; `operation resolve` run while the dialog is still open answers the same way.
- The Skills save a document only when the person asks for it; a grant to change a document is not a request to save it, and a report says when a change is left unsaved.
- Authorization is given once: a folder listed under Authorized Targets in `docs/E2E.md` is a work folder, in which the coding Agent makes practice copies, starts the Creo instances it tests on and closes only those, and writes its own scope files for live runs. In real work, when the person's own message grants a document, the Agent writes a scope file that holds only that grant and says what it wrote; a request to do a task is not a grant. `session close` needs a scope that covers every document open in the instance, and `session open --doc` one that covers the document it opens.
- The host component speaks host protocol 1.3.0. A host component of 1.1.0, which speaks 1.2.0, keeps working until `plugin install` replaces it.
- `doc create`, `doc save-as`, `session open` and `session close` passed their live tests on Creo Parametric 13.4 and are verified.

### Fixed

- `doc create --path` and `doc save-as` list the file Creo wrote, such as `cover.prt.1` for `cover.prt`, with the path the call gave as `requested_path`, so the check that the file exists passes; it failed, since Creo numbers the versions of a model file.
- A dialog that a Java application shows in the Java process Creo starts, such as one while Creo starts, counts as a dialog that holds Creo: `session open` reports it with `E_HUMAN_REQUIRED`, and `session list` shows the session blocked. Only Creo's own windows counted, so `session open` waited for the host component, which starts after such an application, until its time ran out.
- The receipt of a long write names the document as the job left it, so the next `doc save` no longer lists that write as a change made outside creo-cli. `doc undo` undoes a long job's write too.
- A result over the size limit names only the flags the command offers, and after a write that ran it says not to send the write again.

## [1.1.0] - 2026-11-07

### Added

- The host component's C library, for what only Creo TOOLKIT can do. `plugin install` compiles it with Visual Studio's x64 C compiler against the Creo TOOLKIT component of the user's Creo and unlocks it with a Creo TOOLKIT development license; without them it installs the Java part alone, records why, and the commands that need the library are refused with `E_UNSUPPORTED` naming the reason. `CREO_CLI_VCVARS` names the compiler's `vcvars64.bat`.
- `session open` starts a Creo of creo-cli's own from a start folder beside the host component, as a long job, and `session close` ends a Creo as File > Exit does, refusing while a model has unsaved changes; closing a Creo creo-cli did not start is dangerous.
- `extrude create` extrudes a sketch into one named feature, adding or removing material, blind, symmetric, through all or up to a plane, along a model axis. The sketch is JSON: a plane (a datum, a face of an earlier feature such as `BASE/end`, or a surface ID), the model axis its x runs along, projected references, rectangles, circles, lines, arcs, centerlines and points, constraints and named dimensions, which go into Creo by name. A sketch that is not fully defined is refused, by the preview for rectangles and circles; a feature that does not regenerate, or would add or remove no material, is taken back. The result reports the dimensions, the change of volume, the bounding box and the faces by place.
- `shell create` hollows a part with walls of one thickness, open at the faces named; `round create` rounds edges to one radius. Faces are named by a feature and their place (`BASE/start`, `BASE/end`, `BASE/side[+x]`) or by surface ID; edges as `edge(face, face)`, `face:edges`, `face:outer-edges`, `FEATURE:edges` or by edge ID. `--depth-name`, `--thickness-name` and `--radius-name` give the key dimension a name.
- `pattern create` repeats one feature in a row along a model axis, with a count and a spacing that `--spacing-name` names. The result lists the count's dimension, such as `p20`, which relations can drive.
- `plane create` makes a datum plane at a distance from a plane or face toward a model axis, or through an axis at an angle; `axis create` a datum axis where two planes cross or through a cylindrical face.
- `chamfer create` chamfers edges by one distance; `draft create` drafts faces by one angle about a hinge plane so that they narrow toward the pull direction, turning the angle's sign when Creo leaned them the other way.
- The domain Skill `creo-feature` for modeling parts feature by feature; the entry Skill `creo-cli` routes feature work to it.
- `feature delete` deletes a feature with the features that depend on it, dangerous, with all of them in the preview. `parameter create` creates a parameter; `relation update` replaces the relations, blocking a line Creo cannot evaluate and putting the old relations back when the model does not regenerate; `model update` assigns a material from the part or Creo's material library and sets the common name.
- `model check` runs Creo's ModelCHECK read-only, with its report beside the host component, and creo-cli's checks: failed, suppressed and default-named features.
- `model render --view` takes the picture in a named view (FRONT, TOP, RIGHT, DEFAULT or one saved in the model) and puts the person's view back; Creo then shows the model as modified, which the result reports.
- `geometry list --feature` gives each face its place in the feature (start, end, side), and `--role` and `--facing` filter by place and normal; `distance get` takes faces by place, such as `--from BASE/start --to BASE/end`.
- `revolve create` revolves a sketch about the entity of type `axis` in it, 360 degrees or less, adding or removing material.
- `doc create --kind part --path <file>` creates a part from Creo's metric part template, with the parameters PART_NO and DESCRIPTION, or from `--template`, writes it at once and shows it in a window. `doc save-as --output <file>` writes a copy under another name, or the model into another folder.
- Evaluation questions that build a four-way power strip's top housing and its switch cap from the requirement text, each in an empty part, and apply a change order to the housing through its relations; the graders read the geometry Creo built.
- The sketch knowledge says that the bounding box is Creo's outline, which around rounds on drafted walls can be a few hundredths of a millimetre larger than the part, and that `distance get` measures an exact size.

### Changed

- `parameter update` regenerates a part or assembly after setting the value, so relations that read the parameter take effect, and takes the value back when the model does not regenerate.
- In a sketch, mirroring one circle's or rectangle's center onto another's (`symmetric` with `a` and `b`) places and fixes the second, and `equal` circles share one diameter; the preview counts both when it checks that the sketch is fully defined.
- Built on tool-driver-cli-spec 1.0.6. A long job's worker retries a busy answer from Creo for up to 10 s before it sends the work, `session list` allows 2.5 s to find the running Creo processes and their dialogs, and long jobs are verified on the same terms as calls. `docs/E2E.md` starts with the fixed Authorization Rules, and Authorized Targets holds only the list.

### Fixed

- `geometry list` reports a planar face's `normal` pointing out of the material, as `--facing` and filters such as `BASE/side[+x]` take it; it reported the axis of the plane's coordinate system, which can point into the material.
- `draft create` checks the lean on the drafted faces alone, and turns the angle when they widen toward the pull; the faces Creo lists at the hinge made every draft pass the check.
- A face name that fits several faces is refused with `E_AMBIGUOUS` and the candidates, each with its surface ID, a point and its normal; the host component sent bare IDs, which the CLI turned into `E_PROTOCOL`.
- `relation update` no longer leaves an unknown outcome when the model does not regenerate with the old relations either; it reports the old relations back and that the model fails with any value.
- The host component reports the version `plugin install` built it as, which the build writes into its JAR; it reported 1.0.0 whatever was installed, so after an upgrade every command was refused as if Creo still had the old host component.
- A surface, edge or axis named by an ID the model does not have, such as `edge:999999`, is refused with `E_NOT_FOUND`; Creo's own error made it `E_NATIVE_FAILURE`.
- A feature, dimension or parameter a write made or set that is gone at the read-back, such as a new feature someone renamed, reads back as a mismatch (`E_VERIFY_FAILED`), not as unread.
- After a change, the windows of the models that changed are repainted, not only the current window.
- `plugin install` shows the Java compiler's errors in English and readable on a Windows set to another language. A fault of the host component itself is written to its `host.log` with where it happened, since a write whose outcome is unknown carries no message.
- Creo no longer waits to exit while a creo-cli call still holds a connection to the host component.
- The practice part of the evaluation questions no longer carries, in its history, the login and computer name of the person who made it.

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
