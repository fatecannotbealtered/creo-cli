# Creo Parametric Capability Survey

English | [中文](APPLICATION_zh.md)

This survey records what Creo Parametric can do and how it can be automated. It is filled in before commands are designed, and every capability has a disposition: `provided` when a command of creo-cli offers it.

Sources marked "earlier creo-cli" are the documents and code of the earlier creo-cli at commit `bc50267` (in this repository's git history). They record observations made on Creo Parametric 13.4.1.0.

## Application

- Name: Creo Parametric
- Vendor: PTC Inc.
- Versions surveyed: Creo Parametric 13.4.1.0 (build 2026163) on Windows 11 x64, with Object TOOLKIT Java and JDK 25.0.3; creo-cli supports >=13.4 <13.5. Other 13.x builds and Creo 12 and earlier were never run (earlier creo-cli, `docs/COMPATIBILITY.md`).

The operating systems and CPU architectures on which Creo Parametric runs; the platform packages of creo-cli follow from this table:

| Operating system | CPU architectures |
|---|---|
| Windows | x64 |

Source: Creo Parametric 13 is released for 64-bit Windows only (PTC platform support; confirmed by the project owner); the surveyed installation is Windows 11 x64.

## Automation Interfaces

Every interface Creo Parametric offers, and where code that calls it must run. An interface the CLI can call is used from the adapter layer in `creo_cli/adapter/`. An interface that works only inside the process of Creo Parametric or on its main thread needs a host component in `plugin/`.

| Interface | Called from | Notes |
|---|---|---|
| Object TOOLKIT Java (`pfc` and `wfc` packages in `otk.jar`), synchronous application registered in `protk.dat` (`startup otk_java`) | Only inside the process, on Creo's main thread | The `wfc` element-tree API that creates features exists only in a synchronous application; `otk.jar` has no async connection and `pfcasync.jar` has no `wfc` classes. Needs the `ObjectToolkitJava` license option. `otk.jar` of 13.4 is built for Java 25. Calls from any other thread hang or crash; the earlier service drained a queue from a `wfcSession.CreateTimer` callback every 100 ms; `InvokeLater` deadlocks (earlier creo-cli, `docs/SERVICE.md`, `service/.../Service.java`). |
| Creo TOOLKIT C (`Pro*` functions), a DLL registered in `protk.dat` (`startup dll`) and called from Java through `Dll.ExecuteFunction` | Only inside the process, on Creo's main thread | Needed where Java has no call: `ProSectionEntityFromProjection` (multi-entity sketches), `ProDrawingDimensionMove` / `ProDimlocationTextGet`, `ProDimensionDelete` (needs the TOOLKIT for 3D Drawings license), `ProBomballoonCreate`, tolerance standard and decimals, hole thread series, component replace, section areas, ray intersection. Building needs the TOOLKIT headers and libraries and Visual Studio 2022. Creo asks the person before loading an unsigned DLL in each session unless `open_protk_unsigned_apps` says otherwise (earlier creo-cli, `service/native/creo_cli_sketch.c`, `docs/SERVICE.md`). |
| Unlocking with `protk_unlock.bat -java` | The CLI, during `plugin install` | Lets the JAR run on a seat without a development license. Unlocking needs the Creo Object TOOLKIT Java development license, or its extension license with a Creo TOOLKIT license; the unlocked file must not change afterwards (PTC, Creo Object TOOLKIT Java User's Guide, Unlocking, Running and Signing the Creo Object TOOLKIT Java Application). creo-cli runs it on the user's computer with the user's license, so no unlocked binary is distributed. |
| J-Link / Object TOOLKIT asynchronous mode (`pfcasync`) and the VB API (COM) | The CLI (separate process) | `pfc` only, no `wfc`: cannot create features. Not used (earlier creo-cli, ADR 0002, `docs/HEADLESS-SUPPORT.md`). |
| Creo native files (`.prt`, `.asm`, `.drw` with numbered versions `name.prt.N`) | The CLI can see names and version numbers on disk | The content is a proprietary binary format; only Creo reads and writes it. |
| Neutral and output files (STEP, IGES, STL, Parasolid, PDF, JPEG) | Written or read by Creo; the CLI can hash them | Creo writes `__out.log` beside every export (earlier creo-cli, `docs/SERVICE.md`). |
| Command line (`parametric.exe`, `-g:no_graphics`, trail files, mapkeys) | The CLI | `-g:no_graphics` works only with asynchronous mode; trail and mapkey replay give no read-back. Not used. |
| Windows process and window list (`xtop.exe`) | The CLI | Finds running instances, their start times and open modal dialogs. |

## Object Model

From documents down, with the names Creo's user interface and manuals use:

- Session: one running Creo Parametric process (`xtop.exe`); it has a working directory, an active model and the models in session.
- Model: a part (`.prt`), an assembly (`.asm`) or a drawing (`.drw`), identified in session by name and type; a family table generic and its instances are models too.
- Feature: an item of the model tree, in regeneration order, with an ID, a name, a type (Extrude, Revolve, Plane, Axis, Round, Chamfer, Hole, Cosmetic Thread, Shell, Draft, Rib, Sweep, Pattern, Mirror, Component, ...) and a status (active, suppressed, failed); its sketch (section) holds entities and sketch dimensions.
- Geometry: surfaces (faces), edges, axes, datum planes, coordinate systems and points, each with an ID in the model.
- Dimension (`d12`, a drawing's own `rdd0`), parameter, relation, family table (columns and instance rows), material, appearance.
- Assembly: components (component features placed by constraints: mate, align, insert, coordinate system, default, fix), explode states.
- Drawing: drawing models, sheets (size, projection), drawing views (general, projection, section, detail), and the annotations on them: dimensions, notes, tables (including title blocks and repeat-region BOM tables), BOM balloons, symbols, datum feature symbols and geometric tolerances.

## Units and Coordinates

- A model's units come from its principal unit system, set by its template: `mmns` (mm, N, s) or `inlbs` (in, lbf, s) among others. The default template of an installation decides the units of a new part: on the surveyed machine it is an inch template (earlier creo-cli, `docs/SERVICE.md`).
- Model coordinates: the default coordinate system of the part, right-handed, origin where the default datum planes FRONT, TOP and RIGHT meet. Angles are degrees in Java requests; the C sketch library takes arcs in radians, counter-clockwise.
- Sketch coordinates are in the sketch plane's own axes, measured from where the two sketch references cross; on the default planes that is the part origin.
- Drawing coordinates are sheet coordinates from the lower-left corner of the sheet in the drawing's units. View outlines and positions come back in screen coordinates and are taken to sheet units through the sheet transform; a view's scale must not be applied again (earlier creo-cli, `docs/DRAWING-READING-CONTRACT.md`).
- Display settings (`default_dec_places`, `sketcher_strngthn_to_def_dec_pl`) round what Creo shows and, for sketches, what it stores: the earlier service switched the sketch option off for each sketch and restored it.
- creo-cli takes and returns millimetres and degrees (DCLI-080) and converts to and from the model's units in the host component (DCLI-083).

## Threading and Blocking

- `ProEngineerEnd` called within a call from the Java host crashes Creo; called from a Windows timer on Creo's main thread after the call has returned, Creo ends normally in 3 to 10 s and calls every application's stop function (measured on Creo 13.4.1.0).
- A Creo that ended by force shows a modal "not closed normally" dialog (检索) at its next start, until one ends normally (measured on Creo 13.4.1.0).
- A sketch built through TOOLKIT C in intent manager mode gets no implicit constraints: each line, arc and junction needs its constraints stated (coincident ends, tangency, horizontal, vertical, equal radii), or Creo adds a weak dimension per open freedom; stated in full, only the dimensions given remain, and changing one keeps the constraints, such as a symmetric rectangle staying symmetric (measured on Creo 13.4.1.0). Without the intent manager, Creo's automatic dimensions go to the nearest edges, not to the dimensions a design names.
- A datum axis is built from the constraints form of `ProDtmAxis.h` (`PRO_E_DTMAXIS_CONSTRAINTS`); the legacy elements (`PRO_E_DTMAXIS_TYPE`, `PRO_E_DTMAXIS_PLANE1`) are refused. A feature taken back through `Solid.ExecuteFeatureOps` with a delete operation can stay in the model; `WSolid.DeleteFeatures` removes it (measured on Creo 13.4.1.0).
- `SetRelations` keeps a relation Creo cannot evaluate and only flags it (ModelCHECK reports `RELATION_ERRS`); `EvaluateExpression` on its right-hand side throws. `Part.RetrieveMaterial` takes a name, not a path, and reads the `.mtl` file from Creo's current directory (measured on Creo 13.4.1.0).
- ModelCHECK through `ExecuteModelCheck` runs in under a second on a small part, writes an XML, HTML and JS report with images into the folder it is given, and with the default configuration neither saves nor changes the model (measured on Creo 13.4.1.0).
- Keeping the current view as a named view (`ProViewStore`) and deleting it after `ProViewRetrieve` puts the orientation back exactly, but Creo counts it as a change of the model: a model saved before shows as modified after (measured on Creo 13.4.1.0).
- A revolve built from an element tree with an external axis (`PRO_REV_AXIS_EXT_REF` and a datum axis) is refused with a general error; with `PRO_REV_AXIS_INT_REF` it turns about a geometry centerline of its sketch, a centerline made non-construction with `ProSectionEntityConstructionSet` (measured on Creo 13.4.1.0).
- `WFeature.CreatePattern` answers a member of the new pattern, not the pattern header; the header is found by the name given in the tree. Which way `PRO_E_DIR_PAT_DIR1_FLIP` steps depends on the direction reference's own orientation; creo-cli reads the step from the first copy and flips it when it went the other way (measured on Creo 13.4.1.0).
- `PRO_E_STD_DIRECTION` picks a side relative to Creo's own orientation of the sketch plane, which differs between a datum plane and a face; creo-cli reads which side a new extrude went to from its faces and turns it when it went the other way.
- Every toolkit call must run on Creo's main thread; a synchronous application gets there from a timer callback. Creo 13.4 keeps firing the timer while a modal dialog is open (measured with File > Options and a toolkit message dialog), and it leaves its main window enabled; the CLI finds the dialog by its window title and refuses every call until a person closes it.
- Dialogs seen blocking automation: the unsigned toolkit DLL prompt at load (each session), the "Retrieval"/"检索"/"恢复" recovery dialogs at startup, ORDER_DEBUG, a View States "Apply" request, license dialogs, and a crash dialog when the workstation was locked (Intel OpenGL driver) (earlier creo-cli, `docs/SERVICE.md`, `examples/engineering/RecoveryIsolation.ps1`, `docs/ASSEMBLY-INSTRUCTIONS-WORKFLOW.md`).
- Creo is busy during regeneration and long operations; measured: complex assembly constraint edits 135–194 s, a family table preview about 76 s, a BOM table confirmation 568 s (earlier creo-cli, `docs/ASSEMBLY-CONSTRAINTS.md`, `docs/FAMILY-TABLES.md`, `docs/WORKFLOW-BUDGET.md`).
- A running toolkit call cannot be cancelled; ending the client's wait does not stop it.
- Headless operation is not available to a synchronous application; minimized and locked-screen operation were never qualified (earlier creo-cli, `docs/HEADLESS-SUPPORT.md`).

## Read-back

- Features: element tree and status read again after regeneration; a feature that comes back unregenerated is reported and removed by the host.
- Dimensions, parameters, relations: values read again exactly (doubles; the earlier tool compared dimensions within 1e-9).
- Geometry: volumes through mass properties with `MP_DENSITY_USE_IF_MISSING` (exact without a density); bounding boxes of curved parts are conservative.
- Family tables: `SetCell` can keep the old value without an error, so every cell is read back.
- Drawings: dimension text positions through `ProDimlocationTextGet` land exactly ((110, 20) read (110, 20)); the deprecated `Dimension2D` getter is offset; table origins and note texts read back as written; view positions within 1e-6.
- Assemblies: solved placements read back (the earlier tool compared within 1e-7); in an exploded display positions include the explode offsets.
- Exports and renders: the produced file is checked by size and SHA-256; its content is Creo's.

## Save and Undo

- Save writes a new numbered version (`name.prt.3` after `.2`) into the directory the model came from, not the working directory, even when nothing changed. Old versions stay on disk.
- A model created from a template with `CopyAndRetrieve` is written to disk at once as `name.prt.1`, unlike File > New, into Creo's current directory (measured on Creo 13.4.1.0); creo-cli changes that directory for the moment of the copy and puts it back.
- `Copy` writes a copy under a new name into Creo's current directory and leaves the model in session as it was. `Backup` writes the model under its own name into another folder, given with a closing separator, and the model in session then belongs to that folder: its next save goes there (measured on Creo 13.4.1.0).
- Neither an older numbered version nor a path with a version number opens that version: Creo opens the newest, and a model opened that way fails to save (measured on Creo 13.4.1.0).
- Unsaved changes show as the model's modified flag; a freshly opened part already reports modified, and a common-name change can report unmodified.
- Save a Copy exists (`save_doc_as`); erasing a model from session discards its unsaved changes.
- There is no undo in the toolkit; only a failed regeneration can be undone (`SetUndoIfFail`). creo-cli therefore does not offer `doc undo` (DCLI-067).

## Instances and Concurrency

- Several Creo processes can run at once; each loads its own host component and is told apart by process ID and start time.
- A person can work in the same session while the host runs between the person's actions; while a person has a modal dialog open, the CLI sends nothing. A person's edits change the model state and show as external changes before a save.
- The tool never restarts, reloads or closes a person's Creo to load or upgrade the host component (DSEC-052).

## Licensing

- Creo Parametric needs its own license (node-locked or floating through the PTC license server).
- The host component needs the `ObjectToolkitJava` license option; without it nothing works. Deleting a drawing's own dimension (`ProDimensionDelete`) needs the TOOLKIT for 3D Drawings license.
- `plugin install` builds the host component on the user's computer: it needs a JDK 25, and to unlock it the Creo Object TOOLKIT Java development license, or its extension license with a Creo TOOLKIT license. Running the unlocked component needs one of: the Creo Object TOOLKIT Java runtime license, its development license, or its extension license with a Creo TOOLKIT license (PTC, Creo Object TOOLKIT Java User's Guide, Unlocking, Running and Signing the Creo Object TOOLKIT Java Application).
- Creo delivered by application streaming (PTC trial) has no toolkits.
- The host component's C library is compiled on the user's computer with Visual Studio's x64 C compiler against the Creo TOOLKIT component and unlocked with `protk_unlock`, which needs a Creo TOOLKIT development license; unlocked, it runs without one (PTC, Creo TOOLKIT User's Guide, Unlocking the Application).
- License dialogs at startup need a person (`activate_license`).

## Capabilities

Each capability has one row with an ID `CAP-nnn`, unique in this survey, and one disposition: `provided` (a domain command offers it), `deferred` (worth offering, left for a later version), `excluded` (will not be offered, for example because it is unsafe or cannot be automated reliably) or `unknown` (not yet known whether Creo Parametric allows it). Every row names the interface that reaches the capability; a row other than `provided` gives the reason in one line.

| ID | Capability | Interface | Disposition | Reason |
|---|---|---|---|---|
| CAP-001 | Read a model's summary: kind, units, material, mass properties, bounding box, feature count | OTK Java | provided | - |
| CAP-002 | Change a model's common name, tolerance standard and class, and material | OTK Java; TOOLKIT C for the tolerance standard | provided | Material and common name; tolerance standard later |
| CAP-003 | Export a part or assembly to STEP, IGES or STL, or a drawing to PDF | OTK Java | provided | - |
| CAP-004 | Render a JPEG image of a part or assembly | OTK Java `ExportRasterImage` | provided | - |
| CAP-005 | Set Creo's working directory, where new models are written | OTK Java `ChangeDirectory` | deferred | Later version; not in the 1.0.0 scope |
| CAP-007 | Start a Creo of the tool's own that loads the host component | `parametric.exe` from a start folder with its own `config.pro` | provided | - |
| CAP-008 | End Creo as File > Exit does, unsaved changes refused | TOOLKIT C `ProEngineerEnd` from a Windows timer | provided | - |
| CAP-009 | Create a part from a start part, written at once to a path | OTK Java `CopyAndRetrieve` | provided | - |
| CAP-047 | Write a copy of a model under another name, or the model into another folder | OTK Java `Copy`, `Backup` | provided | - |
| CAP-006 | Regenerate a model on request | OTK Java | deferred | Every write already regenerates; never run live |
| CAP-010 | List the features in regeneration order with type and status | OTK Java | provided | - |
| CAP-011 | Read one feature: dimensions, parents, children | OTK Java | provided | - |
| CAP-046 | Describe a feature's sketch entities | TOOLKIT C | deferred | Later version; needs the C library for every read |
| CAP-012 | Suppress, resume or rename a feature | OTK Java | provided | - |
| CAP-013 | Delete a feature with the features that depend on it | OTK Java `DeleteFeatures` | provided | - |
| CAP-014 | Extrude a sketched closed profile, adding or removing material | OTK Java element trees; TOOLKIT C sketch | provided | - |
| CAP-015 | Revolve a sketched closed profile through 360 degrees | OTK Java; TOOLKIT C sketch | provided | About a geometry centerline of the sketch, up to 360 degrees |
| CAP-016 | Create a datum plane offset from a plane or planar face | OTK Java | provided | - |
| CAP-017 | Create a datum axis through two planes, an edge or a cylinder | OTK Java | provided | Through two planes or a cylinder; through an edge later |
| CAP-018 | Round edges to a constant radius | OTK Java | provided | - |
| CAP-019 | Chamfer edges by an equal distance | OTK Java | provided | - |
| CAP-020 | Place a simple or standard hole on a planar face (linear, radial or coaxial) | OTK Java; TOOLKIT C for thread series | deferred | Later version; not in the 1.0.0 scope |
| CAP-021 | Add a cosmetic thread to a cylindrical surface | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-022 | Shell a part inward, removing faces | OTK Java | provided | - |
| CAP-023 | Draft faces about a hinge plane | OTK Java | provided | - |
| CAP-024 | Add a profile rib | OTK Java; TOOLKIT C sketch | deferred | Later version; not in the 1.0.0 scope |
| CAP-025 | Sweep a closed section along a sketched path | OTK Java; TOOLKIT C sketch | deferred | Later version; not in the 1.0.0 scope |
| CAP-026 | Pattern a feature along a direction or about an axis | OTK Java `CreatePattern` | provided | Along a direction; about an axis later |
| CAP-027 | Mirror the whole part about a plane | OTK Java merge feature | deferred | Later version; not in the 1.0.0 scope |
| CAP-028 | Mirror selected features | OTK Java | excluded | Element-tree mirror of features is not supported (ProMirror.h) |
| CAP-029 | Partial revolves, angled datum planes, counterbore and countersink holes, multi-face drafts | OTK Java | deferred | Never built or run; later version |
| CAP-030 | List geometry references: faces, edges, axes, datum planes, coordinate systems | OTK Java | provided | - |
| CAP-031 | Measure the distance between two geometry references | OTK Java | provided | - |
| CAP-032 | List and read dimensions | OTK Java; TOOLKIT C to describe sketches | provided | - |
| CAP-033 | Change a dimension's value and regenerate; Creo undoes a failed regeneration | OTK Java `SetUndoIfFail` | provided | - |
| CAP-034 | Set a dimension's tolerance: plus-minus, symmetric, limits, ISO fit, basic, none; its decimals | OTK Java; TOOLKIT C | provided | - |
| CAP-035 | List parameters and change a parameter's value | OTK Java | provided | - |
| CAP-043 | Create parameters | OTK Java | provided | - |
| CAP-036 | Read a model's relations | OTK Java | provided | - |
| CAP-044 | Replace a model's relations | OTK Java | provided | - |
| CAP-037 | Read a family table: columns, instances, cells | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-038 | Change family table cells | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-039 | Remove an instance row from a family table | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-040 | List the materials of the library and of a part | OTK Java; `.mtl` files | provided | - |
| CAP-041 | Read and set a part's appearance colour | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-042 | Per-occurrence colour and textures | OTK Java | deferred | Never qualified; later version |
| CAP-050 | List an assembly's top-level components with their status and position | OTK Java | provided | - |
| CAP-045 | Read each component's placement constraints | OTK Java | deferred | Later version |
| CAP-051 | Add a component placed by constraints | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-052 | Redefine a component's constraints, or replace it with another family member | OTK Java; TOOLKIT C for replace | deferred | Later version; not in the 1.0.0 scope |
| CAP-053 | Remove a component with the features that depend on it | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-054 | Check an assembly for global interference | OTK Java | deferred | Can take longer than 60 s on a large assembly, and a read command has no long-job path in the specification |
| CAP-055 | Read explode states | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-056 | Create or edit an explode state by component translations | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-057 | Window display: activate, refit, hide components, unexplode | OTK Java; TOOLKIT C macro | deferred | Never run live; display state only; later version |
| CAP-060 | Read a drawing: models, sheets, size, projection | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-061 | Read drawing views and annotations with their positions | OTK Java; TOOLKIT C for dimension positions | deferred | Later version; not in the 1.0.0 scope |
| CAP-062 | Add a general, projection, section or detail view | OTK Java; TOOLKIT C for section areas | deferred | Later version; not in the 1.0.0 scope |
| CAP-063 | Move views | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-064 | Delete a view that no other view depends on | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-065 | Check the view layout against the sheet: overlap and clipping | OTK Java reads | deferred | Later version; not in the 1.0.0 scope |
| CAP-066 | Show model annotations (dimensions, axes) on views | OTK Java `ShowAnnotations` | deferred | Later version; not in the 1.0.0 scope |
| CAP-067 | Add a reference dimension between two edges | OTK Java `CreateDrawingDimension` | deferred | Later version; not in the 1.0.0 scope |
| CAP-068 | Move a dimension's text on the sheet | TOOLKIT C `ProDrawingDimensionMove` | deferred | Later version; not in the 1.0.0 scope |
| CAP-069 | Erase a shown model dimension, or delete a drawing's own dimension | OTK Java `EraseAnnotation`; TOOLKIT C `ProDimensionDelete` | deferred | Later version; not in the 1.0.0 scope |
| CAP-070 | Add, edit, move and delete notes | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-071 | Add, move and delete tables, including a title block filled from the model | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-072 | Place and delete symbols from Creo's library or a `.sym` file | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-073 | Add a repeat-region BOM table | OTK Java; TOOLKIT C for BOM references | deferred | Later version; not in the 1.0.0 scope |
| CAP-074 | Create BOM balloons | TOOLKIT C `ProBomballoonCreate` | deferred | Later version; not in the 1.0.0 scope |
| CAP-075 | Place and delete datum feature symbols | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-076 | Add and delete geometric tolerances | OTK Java | deferred | Later version; not in the 1.0.0 scope |
| CAP-090 | Run Creo without graphics | Command line | excluded | `-g:no_graphics` needs asynchronous mode, which has no `wfc` |
| CAP-091 | Cancel a running toolkit call | OTK Java | excluded | No API; a call runs to its end |
| CAP-092 | Change Creo configuration (`config.pro`) | OTK Java `SetConfigOption` | excluded | Changes the person's environment outside a document |
| CAP-093 | Replay trail files or mapkeys | Command line | excluded | No read-back; cannot be automated reliably |
| CAP-094 | Check models in or out of Windchill | OTK Java | unknown | Not surveyed; would hand content to an outside system |

## Risks

Each risk or limit found in the survey becomes an entry in `knowledge/`, or gives here the reason it is left out.

- A model may use inch or other units; creo-cli converts to and from millimetres → `creo-units`. The default template deciding a new part's units is left out of 1.0.0, which creates no models.
- Every save writes a new numbered version in the model's origin directory, not the working directory; old versions accumulate → `creo-save-versions`.
- A freshly opened part reports unsaved changes → `creo-save-versions`. A model created from a template is written to disk at once: left out of 1.0.0, which creates no models.
- Modal dialogs (recovery dialogs at startup, license dialogs, ORDER_DEBUG, View States "Apply") block every command until a person closes them → `creo-troubleshooting`.
- Creo asks before loading an unsigned toolkit DLL in each session. Left out of 1.0.0, whose host component is a Java application and loads no DLL.
- A locked or minimized workstation can crash Creo (seen with the Intel OpenGL driver); headless is not available → `creo-display-requirements`.
- Long operations: complex assembly edits 135–194 s, BOM tables up to 568 s; they cannot be cancelled. Left out of 1.0.0: none of its commands runs these operations.
- A feature can be built but fail regeneration (wrong side, face square to the pull). Left out of 1.0.0, which creates no features.
- Signs and sides: hole offsets along the reference face normal, draft angle sign, rib side, shell direction. Left out of 1.0.0, which creates no features.
- Geometry IDs change when features change; references come from a fresh `geometry list` → `creo-geometry-references`.
- A dimension driven by a relation is reset at regeneration; two dimensions can share a value → `creo-relations-and-dimensions`.
- Family table cells can keep the old value silently; instances have no file, the generic is saved. Left out of 1.0.0, which has no family table commands.
- Materials are found only in the working and library directories; Creo 13's placeholder material has no density → `creo-materials`.
- An erased drawing dimension cannot be shown again in that drawing. Left out of 1.0.0, which does not edit drawings.
- Standard sheet fonts (ISONorm) have no Chinese, Japanese or Korean glyphs. Left out of 1.0.0, which does not edit drawings.
- Feature types, view names and explode state names come back localized → `creo-localized-names`.
- Licenses: `ObjectToolkitJava` needed; TOOLKIT for 3D Drawings for deleting a drawing's own dimension; streamed Creo has no toolkits → `creo-licenses`.
- Toolkit calls off the main thread hang or crash, and a null Java string crashes Creo: left out, a rule for the host code (`plugin/README.md`), not for an Agent.
- An unlocked JAR must not change: left out, `plugin install` unlocks it last and never touches it afterwards.
- Exports write `__out.log` beside the file: left out, the host exports into a private folder and moves only the file.
- Drawing views cannot be added in the call that creates the drawing. Left out of 1.0.0, which does not edit drawings.
