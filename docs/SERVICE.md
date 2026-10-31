# The Creo-side service

Creating geometry in Creo needs the Object TOOLKIT Java `wfc` API, and that API exists
only inside a synchronous application Creo itself loads. So creo-cli's engine runs
**inside Creo**: `service/` is a small Java application Creo starts from `protk.dat`,
which listens on `127.0.0.1:9057` and runs named operations on Creo's own thread. Every
CLI command that touches Creo is its client; there is no other engine.

This document records what the service does, how to run it, and -- at more length than
usual -- why it is built the way it is. Almost none of the constraints below are in
PTC's documentation, several contradict it, and each cost a live failure to find.

The current beta uses `CREO_CLI_CONFIG_DIR` in the Creo child process for the service token, log and native handshake, and `CREO_CLI_SERVICE_PORT` for a separate loopback port. This permits isolated startup/state directories without changing global registration or user environment. Health reports a build-time Java/native source fingerprint and Java process ID; it does not claim a loaded-JAR hash. Native handshake records the DLL image path Windows loaded and its host PID. Bind these observations to retained signed artifacts before a native run.

The legacy restart helper stops processes by name. Do not use it to update an attached
user window. Live loading uses Auxiliary Applications, a signed candidate with a unique
Java package and private immutable runtime profile. It preserves existing Creo and Java
processes; see native acceptance (historical material retained outside this snapshot). A PTC script exit of 0 alone
is not signing evidence: require JAR signature entries and explicit DLL unlock completion.

## Running it

```bash
python scripts/reload_service.py --restart
```

One command does the whole loop: compile against the installation's `otk.jar`, stop
Creo, sign the jar with `Parametric/bin/protk_unlock.bat` (a local operation against
this seat's TOOLKIT licence, no request to PTC), write `protk.dat` into Creo's startup
directory, start Creo with `PRO_JAVA_COMMAND` in its environment, and wait for the
service to answer.

Restarting Creo discards unsaved work, so `--restart` asks the running service which
models are open and **refuses** if any are -- or if the service cannot be asked, since
then nothing is known. `--force` overrides. Already-loaded Java classes cannot be replaced
by rewriting their JAR. A separate source-bound generation package can be registered in
the existing session. Runtime identity requires process creation times, service generation,
source marker, native module path and a JAR open-handle observation. After Java releases
that handle, hash-bound initial-load evidence from the same generation is required.

`python scripts/service_call.py '<json>'` sends one operation directly. It is a
development tool: it bypasses the CLI's preview/confirm flow and permission gate.

The reload compiles once into a scratch directory before it stops Creo, so a compile
error never costs the running session, and compiles with the JDK that
`PRO_JAVA_COMMAND` belongs to unless `--java-home` says otherwise: `otk.jar` is built
for the Java Creo requires (25 for Creo 13.4), and an older `javac` first on `PATH`
cannot read its class files.

## The CLI commands

`scripts/record_live.py` runs the commands as CLI subprocesses against a live Creo and
records the run in `docs/evidence/live-creo.json`; `registry.LIVE_VERIFIED` may name
only commands that record shows passing. Every command that talks to Creo is in it.

| Commands | Ops |
|---|---|
| `session status`, `session cd` | `session.status`, `session.cd` |
| `model list`, `show`, `open`, `save`, `close`, `discard` | `model.list`, `model.show`, `model.open`, `model.save`, `model.close`, `model.discard` |
| `artifact render`, `artifact export`, `model import` | `model.render`, `model.export`, `model.import` |
| `part create`, `assembly create` | `part.create`, `assembly.create` |
| `feature list`, `show`, `delete`, `suppress`, `resume`, `rename` | `feature.list`, `feature.show`, `feature.delete`, `feature.suppress`, `feature.resume`, `feature.rename` |
| `feature extrude`, `revolve` | `feature.extrude`, `feature.revolve` |
| `feature datum-plane`, `datum-axis`, `round`, `chamfer`, `hole`, `shell`, `draft`, `pattern`, `mirror` | `feature.datum-plane`, ... `feature.mirror`, with `geometry.list` to resolve references |
| `feature rib` | `feature.rib` |
| `feature sweep` | `feature.sweep`, with `geometry.list` to resolve a face |
| `assembly component replace` | `assembly.replace` |
| `assembly explode apply` | `assembly.explode` |
| `model set-common-name` | `model.set-common-name` |
| `family-table show`, `set`, `remove` | `family.show`, `family.set`, `family.remove`, with `dimension.list`, `parameter.list` and `feature.list` to check the keys |
| `feature cosmetic-thread` | `feature.thread`, with `hole.chart` and `dimension.list` |
| `dimension.tolerance` | One dimension's tolerance: plus-minus, symmetric, limits, an ISO fit from Creo's tables, basic or none; its decimal places set by the native library | the dimension with its tolerance read back, the one before, the places shown |
| `model.set-tolerance-standard` | Creo ANSI or ISO/DIN standard/class metadata, set by the native library; regenerated. This does not declare a drawing's general manufacturing tolerance. | the standard and class before and after, the volume |
| `dimension set-tolerance` | `dimension.list`, `dimension.tolerance` |
| `model set-tolerance-standard` | `model.show`, `model.set-tolerance-standard` |
| `geometry list`, `geometry distance` | `geometry.list`, `geometry.measure` |
| `dimension list`, `dimension set` | `dimension.list`, `dimension.set` |
| `parameter list`, `parameter set` | `parameter.list`, `parameter.set` |
| `relation list`, `relation set` | `relation.list`, `relation.set` |
| `material list`, `material assign` | `material.list`, `material.assign` |
| `assembly component add`, `remove`, `check` | `assembly.add`, `assembly.remove`, `assembly.check` |
| `drawing create`, `add-view`, `move-view`, `annotate`, `hide-dimension`, `add-note` | `drawing.create`, `drawing.add-view` (with `geometry.list` for a section's plane or a detail's edge), `drawing.move-view`, `drawing.annotate` (with `feature.list` for `--feature`), `drawing.hide-dimension`, `drawing.add-note` |
| `drawing note edit`, `move-dimension`, `add-dimension`, `add-table`, `move-table`, `add-bom`, `add-balloons`, `add-symbol`, `add-datum`, `add-gtol`, `remove` | `drawing.edit-note`, `drawing.move-dimension`, `drawing.add-dimension` (with `geometry.list` for the edges), `drawing.add-table`, `drawing.move-table`, `drawing.add-bom` (with `model.show` for the assembly's components), `drawing.add-balloons`, `drawing.add-symbol` (with `drawing.symbol` to read the definition first), `drawing.add-datum`, `drawing.add-gtol` (with `geometry.list` for a face or edge), `drawing.remove` |
| `workflow run` | the steps' own ops, one after another |
| `workspace list`, `operation *`, `service install` | none: the disk, the receipt store, the bundle |

Writes follow the CLI's contract: `--dry-run` reads the live model and session and
issues a token bound to that reading; `--confirm` needs `CREO_CLI_PERMISSION=write` and
`CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1` (`service install`, which touches no model, only
the first), reads again, and refuses if anything changed.
Every path involved -- Creo's working directory, a template, a model file, the
directory a model is stored back into, an export -- must lie inside `CREO_CLI_WORKSPACE`.
Every confirmed write leaves a receipt in `operations.sqlite3`; see
`skills/creo-cli/reference/safety.md` for the statuses. The request diagnostics
`dump_tree` and `keep_on_failure` are not exposed by the CLI.

## Installing it on another machine

The jar and the native library are unlocked with a TOOLKIT licence and must not be
modified afterwards, so they are built on a licensed machine and shipped as they are:

```bash
python scripts/reload_service.py --restart           # build and unlock, on the licensed machine
python scripts/build_bundle.py --output dist         # creo-cli-service-<version>.zip + manifest
creo-cli service install --from creo-cli-service-1.0.0.zip --dry-run   # on the other machine
```

`service install` checks every file against the bundle's manifest (SHA-256) and the
bundle's protocol against the CLI's, copies them into `~/.creo-cli/service/<version>/`,
writes the `protk.dat` that registers them there, and names the line the user adds to the
`config.pro` Creo starts with: `toolkit_registry_file <that protk.dat>`. Nothing in Creo's
configuration is touched by the CLI. Verified on Creo 13.4.1.0: started with the installed
`protk.dat`, Creo loaded the service (protocol 2, creation API) and the sketch library from
the installed directory.

## Protocol

| Endpoint | Auth | What it proves |
|---|---|---|
| `GET /health` | none | Creo loaded this code, and which `protocol` it speaks. Touches no Creo API. |
| `GET /session` | token | The toolkit answers on a live request (the same reply as `session.status`). |
| `POST /op` | token | Runs one named operation. |

`protocol` (currently 2) is raised whenever a request or reply changes shape; the CLI
refuses to talk to a service that speaks another, rather than misread its replies.

A request may carry `X-Creo-Cli-Wait-Ms`, how long its caller will wait. Ordinary
requests retain the 120 s ceiling. The explicit `drawing-complete-v1` profile permits
a ceiling of 300 s per request; it requires `X-Creo-Cli-Execution-Profile` and a
matching `drawing_execution_budget: 1` capability from process-only `/health` before
any CAD dispatch. An old or incapable service is refused; a larger timeout alone
does not select a compatible service or permit an ordinary request to wait longer.
The CLI selects this profile only for the exact eligible commands when the user
explicitly passes `--timeout` greater than 300 and no greater than 600. Discover
the list through `reference.extensions.creo.drawing_execution_budget`, or the
specific command's `extensions.creo.execution_budget` in `reference --command`.
Other commands retain the 300 s invocation limit; the default remains 30 s.

The selected invocation budget is shared across preparation, writes, the first
required independent verification and effect accounting. Each request receives only
the remaining time, capped by its profile's request ceiling. Preview binding freezes
the profile and total budget; confirmation requires the same arguments and timeout.
This profile preserves all required getters and independent readback. It does not
promise completion within 600 s, cancellation, or recovery of an unresolved request.
Process-only health, a new Client or instance, and a larger timeout do not settle
an earlier pending call or clear a retained instance stop. See
[workflow budgets](WORKFLOW-BUDGET.md) for the measured S8 BOM failure and the S9
qualification boundary: software qualification is pending, and no native long-budget
success is claimed. The stable r20b engineering result remains unchanged.

When the budget runs out before Creo's thread has picked the
operation up, the operation is **withdrawn** and the reply is `E_BUSY` with
`started: false`: nothing was done, and nothing will be done later. When it has
started, the reply is `E_BUSY` with `started: true`: it is still running and the reply
cannot say how it ends. The CLI sends its own deadline less a second, so it hears one
of the two instead of timing out on the socket.

Every request except `/health` needs `X-Creo-Cli-Token`, whose value the service writes
to `~/.creo-cli/service-token` when it starts. Loopback alone is not a boundary: any
local process can connect, and a web page can reach `127.0.0.1` by DNS rebinding. A
browser cannot add a custom header to a cross-origin request without a preflight this
server never answers, and other users cannot read this user's profile. The JVM
properties `creocli.service.port`, `creocli.service.token.file` and
`creocli.service.log` move the port, the token file and the log
(`~/.creo-cli/service.log`); the CLI follows with `CREO_CLI_SERVICE_URL` and
`CREO_CLI_SERVICE_TOKEN_FILE`.

`/op` takes `{"op": "...", ...}` and returns `{"ok": true, "op", "data", "elapsed_ms"}`
or `{"ok": false, "op", "error": {"code", "message", ...}}`. Toolkit failures carry
`toolkit_function` and `toolkit_error`; multi-step operations carry `stage`.

## Operations

Every operation reads back what it did and reports the reading, not the request.
Names mirror the commands that call them; there is no generic "run this" operation.
Feature-building ops all reply with the feature as Creo now holds it (id, name, type,
status) and the volume before and after, `change` signed; the CLI sets the change beside
the estimate the request implies.

| Op | Does | Reports |
|---|---|---|
| `session.status`, `session.cd` | Reads the session; sets the working directory | working directory, models, active model, `creation_api`, sketch library |
| `model.list`, `model.show` | Lists models; reads one | type, origin, `modified`; units, material, mass properties, bbox, bodies, datums, feature count; components of an assembly; sheets and views of a drawing |
| `model.open`, `model.save`, `model.close`, `model.discard` | A model's life in session | as `model.show`; the new version file on disk; what is left in session |
| `model.render` | Turns the model's window to a standard view, hides datums, writes a JPEG, puts the view back | the file written |
| `model.export` | STEP, IGES, STL (parts, assemblies) or PDF (drawings, datums hidden) into a directory the CLI names | every file written there |
| `model.import` | A part or assembly from a STEP, IGES or Parasolid file (`ImportNewModel`; `GetImportSourceType` says which a STEP or IGES file holds) | what `model.show` gives for it, and the file it came from |
| `part.create`, `assembly.create` | A new model from a template, as File > New does | units read back, datum planes |
| `feature.list`, `feature.show` | The tree; one feature | status, visibility; parents, children, dimensions, sections |
| `feature.extrude`, `feature.revolve` | A sketched profile, extruded or revolved (about a sketched centerline or an axis/edge of the part) | the feature, the volume, how the sketch was drawn |
| `feature.datum-plane`, `feature.datum-axis` | Offset / angled plane; axis through two planes, an edge or a cylinder | the feature and the new datum's geometry |
| `feature.round`, `feature.chamfer` | Constant radius / equal distance on a list of edges | the feature, the volume |
| `feature.hole` | A hole on a planar reference, placed by two distances, blind or through all: straight, or a Standard (tapped, clearance) or Custom one with a counterbore or countersink | the feature, the volume; for a shaped one the drill, the chart row and the hole's surfaces |
| `hole.chart` | One fastener's row of Creo's .hol chart for a series, in the part's unit | the tap drill, clearances, counterbore and countersink |
| `feature.thread` | A cosmetic thread on a cylinder from a planar face: made simple at the diameter the chart implies, then its diameter and depth set through its dimensions; MAJOR_DIAMETER and PITCH set for the note | the feature, whether it is external, its diameter and depth, its parameters and surfaces |
| `feature.shell`, `feature.pattern`, `feature.mirror` | Shell removing faces; direction or axis pattern of one feature; mirror of the whole part | the feature (the pattern's header) and its members |
| `feature.draft` | Faces tilted about a hinge plane by a constant angle from the pull direction (ProDraft.h, one side, no split) | the feature and the drafted faces, each with its new normal |
| `feature.rib` | A profile rib: an open chain of lines sketched by the native library under PRO_E_RIB_SECTION_COMP, filled on one side and thickened (ProRib.h) | the feature, the side filled and the side tried first |
| `assembly.replace` | Another member of the component's family put in its place by the native library: the component's tree with PRO_E_COMPONENT_MODEL pointed at the new model and each constraint's component reference at the item of the same id in it, redefined; any other model refused; the old one put back if Creo cannot place the new | the component before and after, the references moved, the volume |
| `model.set-common-name` | A part's or assembly's common name (Model.SetCommonName), refused where Creo keeps it unchangeable | the name before and after |
| `assembly.explode` | An exploded state made (WAssembly.CreateExplodedState, translate moves) and activated; a state of the same name replaced only when asked | the state with its moves read back, and every state |
| `family.show` | A part's family table: columns (dimension, parameter, feature, with the generic's value) and each instance's cells (FamilyMember) | the table, and the generic when the part is an instance |
| `family.set` | Columns and rows added, cells set and each read back; each instance made (FamilyTableRow.CreateInstance) or, if open, regenerated, and read back; any cell Creo keeps or instance that fails puts the table back | the columns by key, the instances made, each instance's reads and volume, the table before and after |
| `family.remove` | An instance's row taken out, the instance out of session first | the table before and after |
| `feature.sweep` | A sweep, two features: the path a sketched datum curve, then a constant-section sweep along its curves (ProSweep.h), normal to the path's projection on its plane; both sketches drawn by the native library | the feature, the path with where it starts and ends in the model and which end Creo runs it from |
| `feature.delete`, `feature.suppress`, `feature.resume`, `feature.rename` | Tree edits; delete and suppress take the dependent features along | what changed, the volume |
| `geometry.list`, `geometry.measure` | Faces, edges, axes, datum planes with reference strings; clearance between two references | normals, axes, end points, lengths, areas; distance and nearest points |
| `dimension.list`, `dimension.set` | Dimensions of the visible features; set one and regenerate, undone if it fails | name, value, kind, owner; the value read back |
| `parameter.list`, `parameter.set` | Model parameters, typed; set or create | the parameter read back |
| `relation.list`, `relation.set` | A model's relations; replaced, evaluated and regenerated, the old ones put back on failure | the relations, the dimensions after, the volume |
| `material.list`, `material.assign` | Creo's material library; retrieve and assign one | category; density, mass properties before and after |
| `assembly.add`, `assembly.remove`, `assembly.check` | Package a component then constrain it (removed again on failure); take one out; placement and global interference | the component: constraints, placement, position; interfering pairs and shared volume |
| `drawing.create`, `drawing.add-view`, `drawing.annotate` | A drawing from a sheet template; general, projection or detail view, a general or projection one optionally cut by a cross-section (made in the model through a plane when it has none of that name); Show Model Annotations per view, optionally keeping only named features' dimensions | sheets, views with outlines on the sheet, type, parent and sections, every shown dimension (name, value, owner feature, view), notes |
| `drawing.move-view` | Translates a view so its outline's middle is at a sheet point | the view as read back |
| `drawing.hide-dimension`, `drawing.add-note` | Erases shown dimensions from the drawing (the model keeps them); a free note at sheet coordinates | what was taken off; the note as read back |
| `drawing.edit-note`, `drawing.move-dimension` | A note's text and free position; a dimension's text moved on the drawing (native `ProDrawingDimensionMove`) | the note; every dimension with `at`, read by `ProDimlocationTextGet` |
| `drawing.add-dimension` | A reference dimension between two straight edges of the part a view shows | the dimension as read back: value, view, `reference`, `at` |
| `drawing.add-table`, `drawing.add-symbol`, `drawing.symbol` | A table from its top left corner, cells and merges; a symbol instance from a definition, free on the sheet, variables filled; a definition's variables, or the library's names | tables with cells, `at`, `from_format`; symbols with definition, `at`, values |
| `drawing.remove` | Deletes a note, table, symbol or a dimension made on the drawing (native `ProDimensionDelete`) | what was removed |
| `drawing.add-bom`, `drawing.add-balloons`, `drawing.move-table` | Retrieves a parts list table from Creo's library and updates it from the drawn assembly; balloons its components in a view (native `ProBomballoonCreate`); moves a table by its origin | the table with cells, `at` and `size`; how many balloons were made |
| `drawing.add-datum`, `drawing.add-gtol` | A datum feature symbol on a face of the part a view shows; a feature control frame under a dimension, led to an edge or free in a view | datums (label, face); frames (owner, type, value as printed, datums, attachment, place) |

The first vertical slice, as run live against Creo 13.4.1.0:

```json
{"op": "session.cd", "path": "D:/creo-ws"}
{"op": "part.create", "name": "slice_part", "units": "mmns"}
{"op": "feature.extrude", "model": "slice_part", "name": "BOSS", "depth": 20,
 "sketch": {"plane": "FRONT", "orient_ref": "RIGHT", "profile": {"type": "circle", "diameter": 60}}}
{"op": "feature.extrude", "model": "slice_part", "name": "BORE", "depth": 20, "material": "remove",
 "sketch": {"plane": "FRONT", "orient_ref": "RIGHT", "profile": {"type": "circle", "diameter": 20}}}
{"op": "model.save", "model": "slice_part"}
```

Creo reported +56 548.668 mm³ for the boss (π·30²·20), −6 283.185 mm³ for the bore
(π·10²·20), a bounding box of [−30, −30, −20] to [30, 30, 0], and a 104 625-byte
`slice_part.prt.2` on disk.

### Profiles, and which path draws them

| Profile | Drawn by | Why |
|---|---|---|
| `rectangle`, `polygon`, `slot`, `outline`, any profile with `holes` | native library (C) | several entities: must be dimensioned to projected references; arcs go as `A cx cy r a0 a1`, counter-clockwise from a0 to a1, as PTC's own slot example draws them |
| `circle` | native library when loaded, else Java | with references the centre is dimensioned to the datums, as a person's would be |
| `ellipse` | Java | the native library does not draw ellipses; a single closed entity needs no references |
| a revolve's sketched axis | native library (C) | a centerline entity (`K x0 y0 x1 y1`) beside the profile |

Coordinates are in the sketch's own axes, measured from where the two sketch references
cross; for a sketch on one of the template's default planes that is the part origin.

The second live slice, a 40 × 20 × 10 block with a pocket and a hole:

```json
{"op": "feature.extrude", "model": "nr_block", "name": "BLOCK", "depth": 10,
 "sketch": {"plane": "FRONT", "orient_ref": "RIGHT", "profile": {"type": "rectangle", "width": 40, "height": 20}}}
{"op": "feature.extrude", "model": "nr_block", "name": "POCKET", "depth": 5, "material": "remove",
 "sketch": {"plane": "FRONT", "orient_ref": "RIGHT",
            "profile": {"type": "rectangle", "width": 10, "height": 6, "center": [8, 2]}}}
{"op": "feature.extrude", "model": "nr_block", "name": "HOLE", "depth": 10, "material": "remove",
 "sketch": {"plane": "FRONT", "orient_ref": "RIGHT",
            "profile": {"type": "circle", "diameter": 6, "center": [-12, 0]}}}
```

Creo measured +8 000, −300 and −282.743339 mm³ (π·3²·10), 7 417.256661 in total, and a
bounding box of [−20, −10, −10] to [20, 10, 0]. A hexagon of radius 15 came back at
4 676.537180436 mm³, 3.9 × 10⁻¹⁶ from 3√3/2·15²·8, with its vertices at ±15 and
±12.990381056766.

## The native sketch library

A sketch made of several entities must be dimensioned to references projected from the
model into the sketch. A person's sketch gets them automatically — PTC's own sample
`plate.prt` shows them as two extra lines through the origin — but the section a
toolkit application receives has none, and **Object TOOLKIT Java has no call that
creates them**. Every multi-entity sketch tried from Java — clockwise, counter-clockwise,
triangle, polyline, two arcs, any epsilon, intent manager on or off, construction
centerlines, a sketch coordinate system, a standalone 2D section — solved on its own and
was then rejected by the feature with a bare general error.

The C toolkit has the call (`ProSectionEntityFromProjection`), so
`service/native/creo_cli_sketch.c` is a small DLL that does that. The Java service builds
the incomplete feature as before, then calls the library through `Dll.ExecuteFunction`;
the library projects the references, draws, dimensions, sets the direction and redefines
the feature, and reports each step. Without the library every single-entity operation
still works and multi-entity profiles are refused with the reason.

Its one other job is the drawing's, for the same reason -- Java has no call that does it:
`creo_cli_dimension_move` (`ProDrawingDimensionMove`), `creo_cli_dimension_place`
(`ProDimensionLocationGet` and `ProDimlocationTextGet`, the measure the move places by) and
`creo_cli_dimension_delete` (`ProDimensionDelete`, for a dimension made on the drawing).
Each names the dimension the same way: drawing, owner model and its type, id, and whether
it is a reference dimension. Without the library those commands are refused with the
reason, and a drawing's own dimensions list no `at`.

**How it is loaded.** Creo loads it from its own `protk.dat` entry. The Java service
cannot find files beside its jar — Creo loads applications through
`com.ptc.cipjava.CIPClassLoader`, which records no code source and serves no resource
URLs — so the path lives in the registry file, where Creo reads it. Java then asks Creo
for the library by application id. PTC documents that id only as "an identifying
string"; it turned out to be a number (`117906099362`), so the library writes it to
`~/.creo-cli/native-sketch-id` in `user_initialize` and Java reads it from there. Both
registry entries carry `fail_tol true`: without it, an application whose start fails
makes Creo shut itself down.

**The order that works**, found by trying six in one session:
`refs, entities, autodim, regenerate, direction, redefine`. Every order that kept intent
manager on was rejected at the redefine, and an explicit solve was refused as bad
inputs. Auto-dimensioning, which failed from Java, works once references exist. The
order is sent by Java (`NATIVE_STEPS`), so changing it is not a rebuild; the library runs
any sequence of named steps. It is now `refs, entities, plan, direction, redefine,
readback`: see below.

**Dimensioned as a drafter would.** Auto-dimensioning alone reads coincidences as intent.
A stepped shaft's half profile with two journals 30 long came back with one length
dimension and an equal-lengths constraint, and a corner held on the line of an edge it
merely lay level with; setting the left journal from 30 to 35 moved both shoulders
(-1 767 mm³ against -884 for the one). What did not work: `ProSectionConstraintDeny` after
auto-dimensioning -- the regenerate infers the constraints again; under intent manager,
`ProSectionConstraintDelete` does remove them, but Creo puts weak dimensions of its own in
their place (a 0 between the collinear edges, so still chained), and dimensions created
after that leave the weak ones standing, so the next change fails to regenerate. What
works is the order PTC's own `TestSect.c` uses: the dimensions first (`ProSecdimCreate`),
then auto-dimensioning and the regenerate. With every value given, there is nothing left
for auto-dimensioning to read an equality into: the shoulder set 30 to 35 changed the
volume by -883.573 mm³, its step alone, and the journal set 20 to 22 by +1 979.203, its
own. The `plan` step does that from Java's plan (`SketchPlan`): a rectangle by width and
height on two construction centre lines through its centre, which Creo holds it
symmetric about (40 set to 48 put the sides at -24 and 24); other edges parallel to a
reference by their distance from it -- in a revolve, `ProSecdimDiameterSet` on the
distance from an edge to the centerline, which it refuses for auto-dimensioning's
distances from the TOP projection; corners by their distances; arcs by radius, circles by
diameter. If they over-constrain the sketch the step deletes them and auto-dimensions
alone. `readback`, after the redefine, extracts the feature again and reads each sketch
dimension's model id (`ProSectionDimensionIdsGet`), what it references
(`ProSecdimReferencesGet`) and the constraints still tying entities together; Java turns
that into the reply's `sketch_dimensions` and `held_together`. `describe` reads the same
from a feature that already exists, with every entity of its sketch and the names of the
references projected into it (`ProSectionEntityReferenceGet`), and changes nothing; it is
how `dimension list` says what each sketch dimension measures, for a sketch a person drew
in Creo as much as for one of this service's. A revolve about an axis of the part adds one before the
redefine, `set_ref:<element>:axis|edge:<id>`, which puts back the axis Creo dropped while
the sketch was empty.

**Exact dimensions.** Creo rounds a sketch dimension to `default_dec_places` (two) when
it is strengthened, and the redefine strengthens what auto-dimensioning made; the first
live hexagon had a vertex at y = 12.99 instead of 12.990381. The service switches
`sketcher_strngthn_to_def_dec_pl` off for the length of the operation and restores the
previous value afterwards.

**Cleanup.** The library deletes a feature it failed to finish itself, with
`ProFeatureDelete`, and reports it; the reply's `cleanup` field says what happened,
including when nothing could be deleted. Java deletes with `WSolid.DeleteFeatures`:
`Solid.ExecuteFeatureOps`, the call PTC's older examples use, is deprecated and refused
with `BAD_CONTEXT` on Creo 13.4 whatever the feature.

**Creo asks before loading it.** Creo 13 prompts before loading any toolkit DLL that is
not code-signed with a certificate (PTC's licence unlock is not that kind of signature).
"Remember this decision" lasts only for the running session, so every Creo start asks
again, including when the user opens Creo themselves. The setting that governs it is
`open_protk_unsigned_apps` (`prompt` by default, `never`, `always`), defined in Creo's
`text/config.cdb`. It is a security control: `always` loads every unsigned toolkit DLL
without asking. On this machine the user set it in
`C:\Users\Public\Documents\config.pro`. For other machines the real answer is signing
the DLL with a code-signing certificate; until then each user sees the prompt once per
session, and answering "no" only disables multi-entity sketches for that session.

**Building it** needs Visual Studio 2022 or its Build Tools with the C++ workload — the
toolchain PTC names for Creo 13 — and the Creo Parametric Toolkit headers and libraries;
using it needs neither. `scripts/build_native_sketch.py` uses PTC's own flags from
`protoolkit/x86e_win64/obj/make_install`. A rebuilt DLL is new to Creo and brings the
prompt back, so a reload reuses the signed binary whenever the source and flags are
unchanged, checked by digest against a stamp.

## Constraints that shaped the code

**The toolkit is single-threaded, structurally.** Creo talks to this JVM over one
socket whose framing has no request identifiers, and the Java side keeps one static
connection (`CIPRemoteApp.comm`). A toolkit call from an HTTP thread never returns. So
HTTP threads only queue work in plain Java; a toolkit timer created during `start()`
(`wfcSession.CreateTimer`, 100 ms) drains the queue on Creo's thread.

**`wfcSession.InvokeLater` is not the answer**, although PTC documents it as callable
from a non-toolkit thread. Its bytecode sends on the shared connection and then runs
the dispatch loop on the calling thread — the deadlock it appears to avoid.

**An operation must not outlive the caller that gave up on it.** The first version
left a timed-out request in the queue, and it ran whenever Creo came free -- after its
caller had been told "busy, retry", so a retry built the feature twice. Work is now
withdrawn if its caller's budget runs out before it starts, and the reply says which
happened. Measured live: a request with a 100 ms budget queued behind a 750 ms
extrusion was withdrawn at 125 ms and reported `started: false`.

**No toolkit object may leave the toolkit thread — exceptions included.**
`XToolkitError.GetErrorCode()` is a native call over the same socket. Formatting a
toolkit exception on an HTTP thread corrupted the connection, Creo wrote "continuing
from serious error" to `std.out` at about 3 MB/s (715 MB in four minutes), and the JVM
died. Failures are reduced to plain data on the toolkit thread
(`Service.ToolkitFailure`).

**`ElementTree.GetElement(path)` returns a detached copy.** Setting its value changes
nothing in the tree. Edits are made on `ListTreeElements()` and a new tree is built
with `CreateElementTree`, as PTC's own editing example does.

**Direction must be set after the sketch.** `ProExtrude.h` note 3: direction and
material side are ignored until the section is fully defined, and the incomplete
feature comes back with direction `0`, which is not a direction.

**Solid features need body elements.** Creo 7 made parts multi-body; a solid extrusion
requires `PRO_E_BODY/PRO_E_BODY_USE`, which PTC's own extrusion examples predate. The
service adds to the default body, as the Extrude button does; cuts remove from all
bodies. A new part's default body has a negative id (−5778); that is normal.

**Units are never implied.** This Creo is configured with an inch template, so "a new
part" is an inch part, and a 40 × 20 × 10 request would silently produce a block a
metre long whose volume then checks out perfectly. `part.create` requires `units`
(`mmns`, `inlbs`, or an explicit `session_default`) or a `template` path, and reports
the units read back from the model.

On the C side, each also found by a failure or caught before one:

- `ProSectionSolve`, `ProSectionRegenerate` and `ProSectionAutodim` all "shouldn't be
  called if Intent Manager mode is used" and answer `PRO_TK_BAD_CONTEXT`.
- A tree from `ProFeatureElemtreeExtract` is released with `ProFeatureElemtreeFree`, not
  `ProElementFree`; PTC's sketched-extrusion template shows it.
- The section is changed in place inside the tree. Storing the same pointer back with
  `ProElementSpecialvalueSet` risks the tree freeing the value it is about to keep, and
  PTC's template does not do it.
- Unlike Java, an element from `ProElemtreeElementGet` is the live element, so setting
  its value changes the tree.

Smaller ones, each found by a failure:

- `template_solidpart` comes back as `$PRO_DIRECTORY\templates\...`, unexpanded.
- `RetrieveModel` ignores a descriptor's path; PTC's method index says so in a note.
  `RetrieveModelWithOpts` honours it.
- `BaseSession.GetModel` throws `XToolkitNotFound` for an absent model instead of
  returning null as documented.
- `Model.CopyAndRetrieve` writes the new part to disk at once (`name.prt.1`), unlike
  File > New, and `GetOrigin` then reports that file.
- A part is stored back where it came from, not into the working directory: one opened
  from `D:\creo-ws\sub` was saved as `sub\final_hex.prt.2` while the working
  directory was `D:\creo-ws`. `model.save` used to look only in the working directory.
- Every save writes a new version, even with nothing modified (`.prt.3` after `.prt.2`).
- A freshly opened part already reports `modified: true`.
- Datum plane surfaces report no name when listed; list datum planes as features.
- `GetMassProperty` fails on a part with no density, even though volume does not depend
  on it; `MP_DENSITY_USE_IF_MISSING` gives exact volumes.
- Feature types come back localized (`拉伸`); the service reports enum constant names.
- An incomplete extrusion creates an unnamed internal datum plane; PTC's sample parts
  have the same, so it is expected. It is not visible (`ListFeaturesByType(TRUE, ...)`
  omits it) and is listed as `no_name`, so `datum_planes` lists visible planes only.

## What the later operations taught

Found building geometry, features, assemblies and drawings on Creo 13.4.1.0, each by a
failure or a wrong answer:

- **Geometry.** `ListItems(ITEM_SURFACE)` lists only the solid's faces; datum planes are
  reached through their features. A cut carries the edges of its own caps, which bound
  nothing in the part: an edge is listed only between two faces of the solid. Edges are
  read through the faces' contours (`Surface.ListContours`, `Contour.ListElements`), as
  PTC's own traversal goes: `ListItems(ITEM_EDGE)` also returns edges earlier features
  left behind -- a corner a round replaced stays listed, and an edge a later feature
  rebuilt is listed once per feature that built it, ids that still resolve but to no edge
  of the part. A spiral notebook drawn after the release candidate showed it: 223 edges
  listed, 51 of them gone or doubled. A plane's frame Z axis is its outward normal once
  flipped where `GetOrientation` says inward. Axis geometry comes from
  `WAxis.GetAxisData`.
- **Dimensions.** A sketch keeps typeless placeholder dimensions for its references
  (value 0); the CLI does not offer them. `WRegenInstructions.SetUndoIfFail` makes Creo
  undo a regeneration that fails, dimension value included -- measured by setting a
  width to 0.
- **Materials.** `RetrieveMaterial` looks in the working directory and the library
  directory, not its subfolders, so `pro_material_dir` is pointed at the file's own folder
  for the call and put back. Creo 13's placeholder material has no density:
  `GetMassDensity` answers not found.
- **Revolve.** The axis is the sketch's centerline (`PRO_2D_CENTER_LINE`, drawn by the
  native library) with `PRO_REV_AXIS_INT_REF`, or an axis or edge with
  `PRO_REV_AXIS_EXT_REF`. A stepped shaft measured 8 545.132017764236 mm³ against Pappus's
  8 545.132017764237. An external axis is dropped from a feature whose sketch is still
  empty -- the extracted tree shows `PRO_E_REVOLVE_AXIS` blank, like the direction of
  ProExtrude.h note 3 -- so it is set again once the sketch exists: by the native
  library's `set_ref` step, or in the tree Java rebuilds. The first live run of an axis of
  the part failed at the redefine for exactly this; a torus then measured
  789.5683520871487 mm³ against 789.5683520871486.
- **Coordinate systems.** A `csys` constraint names coordinate systems, so `geometry list`
  reports them (`ITEM_COORD_SYS`, with the frame's origin and axes); before it did, the
  CLI's check that a component reference exists refused every one.
- **Rounds and chamfers.** The edges go in as a curve collection, one "add one"
  instruction per edge (`Element.SetElemCollection`), as PTC's C example builds its chain.
- **Patterns.** `WFeature.CreatePattern` hands back the leader, not the pattern; the
  pattern's header is the new `FEATTYPE_PATTERN_HEAD` feature. The first live run caught
  this as a failed postcondition -- the reply named a hole where a pattern was asked for.
- **Mirror.** Mirroring features by element tree is not supported (ProMirror.h); mirroring
  the whole part is (`PRO_FEAT_GEN_MERGE`, `PRO_SURF_TRANS_TYPE_PART_MIRROR`).
- **Export.** STEP goes through `ExportIntf3D`; IGES through it fails (`XInAMethod`) and
  goes through `IGES3DNewExportInstructions`. Every export also writes a `__out.log`,
  which is why the CLI exports into a private staging directory and moves only the file.
- **Render.** `ExportRasterImage` takes its size in inches at a DPI; 100 DPI makes the
  arithmetic pixels. Datums are switched off (`display_planes` and friends) for the
  picture and put back.
- **Assemblies.** A component is packaged with `AssembleComponent` at an identity
  transform, then constrained with `SetConstraints`; an assembly reference needs a
  component path even for the assembly's own datums, as PTC's example says.
- **Drawings.** `CreateDrawingFromTemplate` refuses a full template path (`XStringTooLong`):
  the template goes by name. View outlines and view positions are screen coordinates; the
  sheet transform takes them to sheet millimetres and back. A saved view's transform
  carries the window's zoom and pan (a scale of 11.27 and a translation, measured), and a
  general view needs a pure rotation. `ShowAnnotations` works only on the drawing on screen
  (`PRO_TK_NOT_DISPLAYED` otherwise); per-dimension `Show` fails outright
  (`ProAnnotationShow` general error), `WView2D.ShowAnnotations` per view does not. The
  drawing's reading counts the dimensions it shows (`CollectShownDimensions` per model),
  so `drawing dimension annotate` is checked by a read of its own. Creo names a projected view in
  the session's language (`顶部_1` on a Chinese Creo): view names are Creo's text.
- **Lettering.** Creo's standard sheet templates letter in ISONorm
  (`isonormlt-regular.ttf`), which has no Chinese, Japanese or Korean glyphs, and Creo
  writes a view's scale label in the session's language: on a Chinese Creo it read
  `□□ 0,500`. Creo's own font is localized with the session (`text/chinese_cn/font.ndx`
  adds `chfnt.fnt` to `ascii.fnt`), so a drawing made from a standard sheet letters in it.
  Java has no call for a drawing's detail option; importing a drawing setup file
  (`DWGSetupImportInstructions`) sets it, exporting one reads it back. A PDF of the fixed
  drawing, rasterized, shows `比例 0,500`. A template of one's own keeps its lettering.
- **Detailing.** A dimension shown in a drawing leaves it through
  `WDrawing.EraseAnnotation` (`ProDrawingAnnotationErase`); `Annotation.UndisplayInDrawing`
  answers without error and leaves it shown -- the first live run caught it as a failed
  postcondition. An erased dimension stays erased: `ShowAnnotations` does not show it
  again, so taking off is for good in that drawing (the live record checks this). Showing dimensions one by one fails (above), so `--feature` shows a view's
  dimensions all at once and erases the rest. `WDimension.GetOwnerFeature` says whose a
  dimension is. A view's scale label is itself a note, `比例 &view_scale` in the reading. A
  free note goes in through `CreateFreeNote` at screen coordinates the sheet transform
  gives, and shows only after `Show()`.
- **Placing dimensions.** `WDimension.Move` is `ProDimensionMove`, which moves a dimension in
  its owner model and answers `NOT_DISPLAYED` for a drawing. The whole `Dimension2D` API --
  a drawing's own dimensions -- is deprecated since Creo 4, and its `SetLocation` reads back
  through a getter that ProDrawing.h says is offset from where the text was put (the text
  box's centre): a reference dimension set to (180, 240) read back (177.375, 247.4375),
  and the vertical offset changed sign with the side of the dimension. So every dimension
  moves through the native `ProDrawingDimensionMove` and reads back through
  `ProDimlocationTextGet` -- the pair PTC documents together -- and lands exactly: (110, 20)
  read back (110, 20), for a model's dimension and a drawing's alike. A model's
  dimension reads the same measure in Java (`WDimension.GetDimLocation`).
- **Reference dimensions.** `CreateDrawingDimension` with two edge selections carrying the
  view (`SetSelView2D`), empty senses, an orientation hint and `SetIsRefDimension(true)`
  gives a drawing-owned reference dimension (`rdd0`); it measured a notebook's 12 mm and a
  plate's 10 mm. `Dimension2D.EraseFromModel2D` answers without error and leaves it in the
  drawing (the live run caught it: `item_removed` failed); Java has no delete for it, and
  the native `ProDimensionDelete` does delete it -- PTC lists that call under the TOOLKIT
  for 3D Drawings licence, and a session without it answers with the toolkit's status.
- **Tables and symbols.** `CreateTable` with `TABLESIZE_BY_LENGTH` takes widths and heights
  in the drawing's units and grows right and down from its origin; `GetInfo(0).GetOrigin()`
  reads that corner back ((290, 45) asked, (290, 45) read). Chinese cell text reads back as
  written. A symbol definition comes in with `RetrieveSymbolDefinition(name, directory)` and
  is placed with a free attachment. Its variables are the `\name\` texts of its file -- in
  the old text format and the newer binary one alike -- but a definition can carry a path
  too: Creo's own ISO 1302 symbol records `D:\Xtops\Parameter_tag\obj\...`, which a loose
  pattern read as the variables `Xtops` and `obj`; a variable text stands alone. A numeric
  variable (`roughness_height` in `surffins/generic/standard`, default 32) is kept as a
  number and read back in the sheet's number format: 3.2 as `3,200` on Creo's metric sheets.
- **Section and detail views.** A cross-section is a feature of the model since Creo 2.0:
  `WSolid.CreatePlanarXSectionWithOptions` cuts one through a datum plane's surface, and
  `WView2D.SetSection2DInstructions` (full area, the parent as the arrows' view) cuts a view
  by it -- hatching, arrows and `SECTION A-A` come with it. The section's `GetPlane` answers
  a plane of the section feature's own (another surface id), so the datum it was placed on
  is read as the feature's parent. `WDrawing.CreateDetailView` takes a reference point on
  the parent (an edge selection with the view and a parameter) and a closed spline in
  drawing coordinates around it, as ProDrawingView.h says -- the Java guide's "inches of the
  top model, relative to the reference" is how the spline reads back. The spline's tangents
  are derivatives in its own parameter (2 pi r for a circle): with the radius as length the
  boundary came out a polygon. Creo puts the reference point, not the circle, at the
  location, and scales about it, so the view is centred after its scale is set.
- **View names.** Creo names views in the session's language (`顶部_1`, `右侧_1`) and gave a
  second projection placed the same way the same name as the first: names are not unique,
  so a repeated one gets the next number, and the CLI refuses a shared name. `SetName` with
  a taken name answers `XToolkitFound` only after the view exists, leaving a view nobody
  asked for, so the name is checked first. `View2D.Translate` moves a view;
  `View2D.Delete(false)` removes one and is refused while views are taken from it.
- **Loops of lines and arcs.** Creo draws a sketch arc counter-clockwise from its start
  angle to its end angle, the end smaller than the start when it passes zero (PTC's
  `TestSect.c` slot: 3π/2 to π/2 for the right end). The native library needed nothing new:
  an outline, a slot, a rounded rectangle and holes inside a profile are more entities of
  the kinds it already drew, and auto-dimensioning placed them all. A rounded 60 x 40 plate
  with two holes and a slot measured 17 581.73467 mm³ against 17 581.73452 computed; an L
  bracket with a filleted corner and a shaft revolved from an outline with a rounded
  shoulder matched to 1e-10.
- **Geometric tolerances.** `WModel.CreateSetDatumTag` on the drawing takes a face (an
  edge, or a model's dimension, is refused as bad inputs), and without a pick point on the
  sheet puts the symbol on a corner: the face's middle, brought onto it and into the view, is
  the point. A drawing's own symbol shows as it is made (`Show` answers bad inputs,
  `ShowInDrawing` no change). `WModel.CreateGTol` on the drawing makes the frame, but Creo
  keeps one attached to a model's dimension with that model; every frame shows only after
  `ShowInDrawing` in its view (`Display` answers an invalid matrix for the model's), and a
  drawing's own frame is found by listing -- `GetItemById` answered none. Creo writes the
  diameter sign and material condition itself (`WSession.GetGTolSymbolString`): `0.1` with
  both reads back `⌀0.1Ⓜ`. A null Java string handed to an OTK call is not refused: Creo
  died in OTK's string conversion (utfstrmtz) when a frame's missing third datum went as
  null; it goes as an empty string.
- **Parts lists.** Creo ships an associative parts list, `text/table/Assembly/
  bom_description_down.tbl`: `RetrieveTable` with the assembly as its reference solid, then
  `UpdateTables`, and its repeat region fills -- item, part number, quantity -- a pin used
  twice counted 2. Java has no call for balloons; the native `ProBomballoonCreate` makes them,
  and Creo keeps them as notes (` 1 `), not symbols. A table's cells are notes too, so they
  are left out of a drawing's notes. A retrieved table's width is its own: `GetInfo(0).
  GetOutline()` gives the size, `MoveSegment` moves it.
- **Relations and which dimension is which.** Relations set with `SetRelations` and a
  regeneration drive what they name; a changed width carried a related depth with it, 48 x 20
  x 12 to the cubic millimetre. The first try looked as if they did not, and was a mistake of
  ours: a 40 x 20 block extruded 10 has two dimensions of 10 -- the depth, and the sketch's
  offset of the rectangle from its reference -- and the relation had tied the offset. A
  section's `GetSectionDimensions().GetSolidIds()` lists the dimensions that live in the
  sketch, so `dimension list` now says `in_sketch` for each.
- **A crash that was not ours.** Once, with the workstation locked, Creo died in the Intel
  OpenGL driver (`igxelpgicd64`, access violation) repainting a newly created drawing: the
  traceback (`C:\Users\Public\Documents\traceback.log`) had no toolkit frame, and the
  service saw only `E_BUSY` while Creo's crash dialog waited. `reload_service.py --restart`
  brought it back; the same steps ran cleanly after.
- **Drafts, and a feature Creo makes but cannot build.** A draft is one element tree: a
  surface collection of the faces, the pull direction as a direction compound, and side 1
  with a plane for its hinge and a constant angle. Creo's sign is the part's: a positive
  angle leans each face's outward normal against the pull direction by exactly the angle --
  asin(n . pull) came back -2.99999998606 for 3 on walls and on a pocket's walls alike --
  so the part grows wider along the pull, and the volumes were the frustums' to 1e-12. The
  feature lists three surfaces per face it drafts; only the tilted one belongs to the solid,
  the other two have no area. A face square to the pull did not raise anything:
  `WCreateFeature` returned a feature in `FEAT_UNREGENERATED`, which stayed in the tree while
  later features built after it. Every feature made from one tree is now read back at once,
  and one that is not active is deleted and reported as a failure at stage `regenerate`.
- **A part of two bodies.** `ListItems(ITEM_SURFACE)` refuses a part a second body was made
  in (XToolkitMultibodyUnsupported in ProSolidSurfaceVisit), which took `geometry list` down
  with it; the faces are now read body by body (`SolidBody.ListSurfaces`) when it does.
- **Sections left in session.** Reading a feature's element tree leaves its sketch behind as
  a 2D section model (s2d0001.sec, ...), modified; they were listed as models someone had
  open. They are Creo's, and are no longer listed.
- **A cosmetic thread made the way that works.** Built as ProThread.h describes, a
  standard thread ignored its series and size -- its diameter came back 0.02 whatever indexes
  it was given, the hole chart's included -- and any depth compound failed the feature
  (FEAT_UNREGENERATED) where leaving it out let Creo build one with a default depth. So the
  thread is made simple, at the diameter the chart implies (ISO 68-1: the minor diameter lies
  1.082532 pitches inside the major; a bore's thread is at the major), and its depth and
  diameter are then set through the feature's two dimensions -- which also undoes the tree's
  rounding of the diameter to the model's places (8.376202 came back 8.38). MAJOR_DIAMETER and
  PITCH are set on the feature for the note. Drawings show it dashed.
- **A standard hole's series and size are indexes.** PRO_E_HLE_THRDSERIS and
  PRO_E_HLE_SCREWSIZE hold positions in lists Creo builds from the .hol files it finds;
  only C turns "ISO" and "M6x1" into them (`ProElementHoleThreadSeriesSet`,
  `ProElementHoleScrewSizeSet`), so the native library does that on a tree of its own and
  Java builds the hole with the numbers. The drills, clearances and counterbores come from
  the same chart, read by Java from text/hole. A Custom hole (a plain one with a counterbore
  or countersink) takes its blind depth from PRO_E_HLE_DRILLDEPTH although ProHole.h's table
  leaves it out: without it Creo drilled a depth of its own. Every one of them built on the
  first try, and the volumes matched the drilled shapes -- cylinder, 118-degree point,
  counterbore ring or countersink cone -- within 2e-6; a tapped hole's cosmetic thread is a
  cylinder at the thread's major radius and removes nothing.
- **Tolerances are four things, not one.** Measured on Creo 13.4: `GetToleranceType` is how
  a tolerance is shown (none is the nominal option); `GetToleranceLimits` holds the
  deviations, +upper / -lower, for every kind -- H7 on 20 came back +0.021 / 0 and g6 as
  -0.007 / 0.020; in an ISO/DIN model the hole or shaft table label says whether it is a
  fit, and `GetTolerance` returns that label (DimTolISODIN) whatever the type, so it cannot
  be read for the kind; and basic is a flag of its own -- once set, no tolerance type clears
  it, `WDimension.SetAsBasic(false)` does. A fit set while the type is nominal is lettered
  `20 H7`; plus-minus adds (+0.021/0), limits (20.021/20.000). Going from a fit back to
  plus-minus needs the general table set first, or the label stays. Fits need the ISO/DIN
  standard (XToolkitBadContext otherwise), which only C sets
  (`ProSolidToleranceStandardSet`); a hole or shaft table must be loaded into the session
  first (`LoadToleranceClass`, else XToolkitCantAccess). A tolerance is shown to the
  dimension's own decimal places unless told -- +0.021 came out +0,02 and +-0.005 as
  +-0,01 -- and only C sets the places (`ProDimensionTolerancedecimalsSet`). Creo's standard
  sheets show tolerances already.
- **Ribs, and the arrow a person flips.** A profile rib is made as an extrusion is --
  incomplete, then its sketch drawn by the native library, then redefined -- with the
  library's `sketcher_path` pointed one level down, at PRO_E_RIB_SECTION_COMP /
  PRO_E_STD_SECTION / PRO_E_SKETCHER, and its material side set once the sketch exists
  (ProRib.h note 6). The side decides everything: a gusset whose chain ran from the wall to
  the base filled the inside corner with side one -- exactly 32 x 42 / 2 x 4 = 2688 mm³ --
  and with side two, or Creo's default, came back `FEAT_UNREGENERATED`; the chain reversed,
  the sides swapped. Side one is the right of the chain walked from its first point, in the
  sketch's axes. Unless a side is named, the service tries the right and, if Creo cannot
  build it, deletes it and tries the left -- what a person does with the arrow. A one-sided
  rib goes the way an extrusion's side one goes: against the plane's normal.
- **Sweeps, and which way a chain runs.** The sweep's section sketch sits at
  PRO_E_SWEEP_PROF_COMP / PRO_E_SWEEP_SECTION / PRO_E_SKETCHER and is drawn round the
  path's start. With the automatic frame (PRO_FRAME_MIN) an off-centre section landed on
  the path's left along a left turn and on its right along a right turn; normal to the
  projection about the path plane's normal (PRO_FRAME_PIVOT_DIR, PRO_FRAME_CONSTANT) keeps
  the section's +y on that normal. Then the start: Creo runs a sketched chain the way its
  arcs turn -- a path of a line and a clockwise arc came back as a chain from the arc's end
  -- and sets the section up there, its +x the other way round. A start-point instruction
  (PRO_CURVCOLL_START_PNT_INSTR) on a curve of the chain, with or without the point and
  parameter, left the sweep with no section at all. So the path's sketch reports where it
  lies (ProSectionLocationGet, the library's `locate` step), the service finds the chain's
  start among the curve's pieces, and a section set up at the far end is drawn mirrored:
  the same solid, and one rule for the caller. Measured: rectangles along lines and arcs
  are exactly Pappus (1e-12), circles 5e-4 to 1.3e-3 under; a sharp corner in the path
  fails at the section's dimensioning, so paths are smooth.
- **A turned part's diameters.** Measured in a drawing, a diameter Creo made from a
  distance between an edge and the centerline (`ProSecdimDiameterSet`) is drawn by the
  order of its references: edge first, it ran from the axis outward one diameter long, past
  the part; centerline first, from edge to edge across the shaft, as a drafter draws it.
  `PRO_TK_DIM_DIA_LINEAR` was refused outright. `drawing dimension annotate` then moves each over its
  step (`ProDrawingDimensionMove`, through the anchor the sketch's read-back gives: halfway
  between the axis and the edge, from the section's location in the model).
- **A rib's ends.** Creo regenerates a profile rib only when the chain's ends lie exactly
  on faces: ends 0.44 short of drafted walls failed, and ends 1.5 into them failed as well.
  `creo_cli_ray` is `ProSolidRayIntersectionCompute` (Java has none); the CLI casts from the
  middle of each end segment towards its end and carries the end to the first face ahead.
- **A view's display, and a failed feature.** A feature Creo made and the service deleted
  again leaves the part marked modified with nothing in it changed (measured on a rib that
  would not close); the CLI no longer counts that as a change to acknowledge.
- **A drawing's views follow the session's display unless told.** Left alone a view is
  drawn as the Creo window shows models: one drawing came out in lines and the next shaded.
  The service sets each view's display (`View2D.SetDisplay`: no hidden lines, no tangent
  edges) after everything else -- setting a section's edges to area resets it -- and not on
  a detail, which takes its parent's (Creo answers XToolkitBadContext).
- **Scale labels.** A standard sheet's setup labels a view's scale as a decimal, 2,000;
  `view_scale_format ratio_colon` alone changed nothing until `view_scale_denominator`, 0
  in the templates, was given a value (1000). Both are imported with the drawing's setup
  file, the drawing's own options, not the session's.
- **A cut-face section loses its label.** `ProDrawingView2DSectionAreaSet` (Java has no
  call) removes the `SECTION &xsec_name` note Creo gave the view, regenerated first or not;
  the service writes `A-A` beneath it.
- **A thread's callout.** A driving dimension's value cannot be hidden or overridden --
  `SetDisplayedValueType` and the `@O` text are for driven ones only, and plain texts are
  written after the value (17,29M20x2.5) -- so the chart's size is a second text line under
  the value.
- **Splines.** The library adds a sketch spline (`Pro2dSplinedef`, tangency free) through
  the points of an outline's `through` segment. Measured against Creo 13.4, its area is
  that of the cubic B-spline interpolating the points at chord-length parameters with
  averaged knots -- within 1e-6 for evenly spaced points, 5e-4 for unevenly spaced ones; a
  natural cubic spline was 1-2% off, and through three points Creo draws the parabola.
- **A drawing's scale, as a drafter picks it.** Creo's standard sheets bring their views at
  1:1. The service takes the largest of ISO 5455's preferred scales at which each view,
  grown about its middle, stays on the sheet 5% clear of the edge and 8% clear of the
  others -- measured exactly so on Creo 13.4. Two things learned there: RegenerateSheet
  raised XToolkitGeneralError after SetSheetScale on a sheet whose views came with Creo's
  template, though the scale had taken effect; and within the call that set it, every view
  still answered its old outline -- the new one shows in the next call, so the CLI reads the
  drawing back before checking the views on the sheet and apart (`add-view --scale` alike).
- **A parts list's description.** Creo's `bom_description_down` table fills DESCRIPTION
  from `asm.mbr.ptc_common_name`, the model's common name -- not a DESCRIPTION parameter;
  `Model.SetCommonName` sets it, for an instance too.
- **Exploded states.** `WAssembly.CreateExplodedState` takes translate moves on component
  paths (`pfcAssembly.CreateComponentPath` cast to `WComponentPath`); states are listed with
  `ListItems(ITEM_EXPLODED_STATE)`, and Creo's default one is named in the session's
  language ("默认分解"). A general view made with `SetExploded(true)` draws the active state;
  nothing reads it back, so the live evidence compares widths: a pin lifted 50 mm made its
  side view exactly 50 mm wider than the assembled one beside it.
- **Replacing a component.** `ComponentFeat.CreateReplaceOp` run by
  `Solid.ExecuteFeatureOps` answers XToolkitBadContext on Creo 13.4, as every feature
  operation does there. PTC's own TestAsm replaces a component through its tree: the
  pointer element PRO_E_COMPONENT_MODEL, which Java cannot set, and each constraint's
  component reference re-pointed -- the library does that (`creo_cli_component_replace`;
  ProElementArrayGet and ProElementChildrenGet fill arrays the caller allocates). A
  reference is moved to the item of the same id and type in the new model, which is right
  for members of one family; a 5 mm block took a pin's place without a word because its
  first extrusion's faces had the pin's ids, so only a member of the component's family is
  accepted.
- **Family tables.** `SetCell` takes a value Creo will not use -- a depth of 0 or -5 --
  without an error and keeps the old one, so the instance regenerates to the generic's
  value; every cell is read back as it is set, and one kept puts the table back (rows made
  removed, cells set back, columns added removed). An instance in session is named
  `pin_6x40<pin>.prt` by `GetFileName` -- not a name a model can be asked for by -- so every
  model name the service reports goes through `Creo.fileName`, which drops the generic;
  `GetModel("pin_6x40", MDL_PART)` finds it. An instance has no file: `model.save` refuses
  one and names the generic. Creo marks an instance verified once made, so a table read
  after a failure differs in those marks only -- the CLI compares columns and cells.
- **Shells.** An outside shell grows the walls outwards and the old solid becomes the
  hollow: 40 x 30 x 20 with its top removed and 2 mm walls measured 8 912 mm³, exactly
  44 x 34 x 22 - 40 x 30 x 20. So only an inside shell must remove material.
- **A drawing's projection.** Creo's ISO sheet templates (a0..a4) are first angle and its
  ANSI ones (a..f) third (the exported setup's `projection_type`); both lay out a projection
  above the front and one to its right -- in first angle, the part seen from below. So on
  its own sheets the service lays out the standard views instead, by the projection:
  FRONT, TOP (below the front in first angle), the side view and ISOMETRIC.
- **Views wait for the next call.** In the call that made a drawing Creo deleted its
  template views but refused to make one (`ProDrawingGeneralviewCreate`, bad inputs) or to
  move one (`ProDrawingViewMove`, general error); the same view at the same place was made
  in the next call. `drawing create` therefore runs two operations under one receipt:
  `drawing.create`, then `drawing.lay-out`.
- **Rays and their aperture.** `ProSolidRayIntersectionCompute` with its default aperture
  reported an edge 0.6 mm off a ray on a 120 mm part as hit, and the cone of a chamfer
  0.06 mm past its boundary; given an aperture (`creo_cli_ray`'s `aperture`), only what the
  ray crosses. `drawing dimension annotate` decides whether a view sees a cylinder by such rays,
  cast toward the reader from points just off it, and moves a diameter shown on a circle
  its view cannot see -- a hub behind its flange -- with `Model2D.SetViewDisplaying`.
- **Counts and chamfers on a drawing.** A diameter's prefix reads `⌀`; a patterned hole's
  count goes ahead of it (`6X ⌀`). A 45 x D chamfer's dimension came out `45° X 1` whatever
  the drawing's `default_chamfer_text`; `WDimension.SetChamferStyle(..., drawing)` writes it
  `1 X 45°` in that drawing.

## The vocabulary, derived and guarded

The service writes no element id or value as a literal. `Ptc.java` declares each under
PTC's own name, and `tests/test_feature_trees.py` holds it to two independent PTC
sources: `contract/feature-trees.json`, derived by `scripts/gen_feature_trees.py` from
the C headers in `protoolkit/includes` (5 488 element ids, 877 enumerations, 122 tree
diagrams), and `contract/otk-interface.json`, derived from `otk.jar`.

The two PTC sources **disagree on 16 element ids** in Creo 13.4.1.0 (corner chamfer,
mold inserts, lattice, design-constraint milling among them). The service may not use
any of them, and the set itself is pinned, so an upgrade that changes it is noticed.
The headers also use names that are not element ids: seven in the tree diagrams, which
the test pins as errata, and `PRO_E_BODY_SELECTED` in the extrude value table, which
means `PRO_E_BODY_SELECT`. Checking every name against the id table is what catches
these.
