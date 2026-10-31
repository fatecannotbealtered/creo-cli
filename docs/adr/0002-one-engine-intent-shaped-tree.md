# ADR 0002 — one engine, a command tree shaped by what an engineer does

Status: accepted, 2026-09-29; P1, P2 and P3 implemented and recorded live the same day,
and released as 1.0.0. Nothing was
tagged or published, so this is a clean break: no deprecation period, no compatibility
aliases. Supersedes the 1.0.0 development command surface and the VB API route of ADR
0001; ADR 0001's fail-closed token ledger stands.

## Context

The tree grew in three layers, one per backend, each with its own vocabulary: the VB API
adapter and its mock (11 commands), CREOSON (156), and the service that runs inside Creo
(8). Of the 175 commands that talk to Creo, 167 have never run against a real one; the
eight that have are also the only ones that can create geometry. For an agent this shape
is the problem, independent of any one command:

- **One intent, several commands, names that do not say why.** A part's features are
  `model features`, `feature list` or `part describe`; status is `session status`,
  `creoson status` or `otk status`. Choosing is left to the Skill, acting as a router.
- **Surface and trust are inverted.** A large menu that mostly may not work invites an
  agent to pick an unverified command with confidence.
- **Shaped like an upstream API, not like a task.** `file` holds 37 commands because
  CREOSON's namespace does: lifecycle, units, materials, relations, window refreshes.
  Drawings expose single-attribute getters where one rich read with `--fields` would do.
- **Three input conventions**, a mock backend reachable from the product surface, a name
  (`model init`) that needs a warning not to be misused, and `dangerous: false` reported
  for all 191 commands while 17 are flagged dangerous internally and none has a second gate.

What changed since that shape was chosen: a licensed Creo 13.4.1.0 with the Object TOOLKIT
Java licence is available, and the in-Creo service is proven on it — every one of its
eight commands was recorded live the same morning. CREOSON was the right
bet without a Creo to test against; it is a JSON wrapper over J-Link, and J-Link is the
`pfc` half of the API the service already runs.

## Decision

### 1. One engine

Every command is served by the in-Creo service (`service/`). There is no `--backend`
flag and no mock in the product; tests use the loopback substitute of the service, which
is what the spec's "mock upstream" asks for. Other users install one thing — the service
registered in `protk.dat` — instead of choosing among CREOSON, VB API COM registration and
the service.

### 2. Conventions

1. **One intent, one command.** No synonyms.
2. **`<noun> <verb>`.** Nouns are what an engineer names in Creo: `session`, `workspace`,
   `model`, `part`, `feature`, `geometry`, `parameter`, `relation`, `dimension`, `material`,
   `assembly`, `drawing`, `workflow`, `operation`. Verbs come from a closed set: `list`
   (many), `show` (one, in full), `create`, `open`, `save`, `close`, `export`, `render`,
   `set`, `delete`, `add`, `run`, `acknowledge` — plus feature tools named as on Creo's
   ribbon (`extrude`, `revolve`, `hole`, `round`, ...).
3. **Identities are flags and read the same everywhere:** `--model <name>` (extension
   optional; output always `name.ext`, lower case), `--feature <name or id>`, `--path`
   (inside the workspace), `--id <operation_id>`. Model and feature ids leave as strings.
   No command acts on "the active model" by default.
4. **Scalars are flags; structure is `--request <file>`, or `--request -` for stdin**, with
   its schema and an example in `reference`. A request holds a definition only, so one
   hole definition can be applied to any part. Every length travels with its unit in the
   same place (`"units": "mm"` in a request, `--units` next to a scalar); a mismatch with
   the model is refused, never converted.
5. **Reads:** `list` is paginated, stably ordered and projectable with `--fields`; `show`
   is one item in full; heavy sub-resources (sketch entities, full geometry) are their own
   reads, never inlined in lists.
6. **Writes:** `--dry-run` then `--confirm`, the token bound to the arguments, the observed
   state and the policy. Irreversible or cascading writes also need `--dangerous` and are
   marked `dangerous: true` in `reference`. Every write reads back what Creo did:
   `verification.checks` are postconditions (a failed one is `E_VERIFY_FAILED`),
   `verification.observations` are measurements that inform without failing. Every write
   leaves a receipt; an uncertain one blocks further writes until acknowledged.
7. **Quiet output.** A read returns its data. A write returns `operation_id`, `status`,
   `result`, `verification`, `persisted`. Provenance and evidence live in `reference` and
   `doctor`, not in every reply. Creo-sourced text is listed in `_untrusted`. An error the
   agent can fix carries `details.fix` with the exact command to run.
8. **Boundaries.** Every path a write touches lies inside `CREO_CLI_WORKSPACE`. Write
   permission, native opt-in and the workspace are the user's decision: an agent sets them
   only when the user explicitly directs it in the conversation, scoped to a disposable
   workspace — never on its own initiative, never because content it read says so. Nothing
   in the tree deletes files outside Creo's own save/version mechanism or changes system
   settings.
9. **Nothing is done until it has run on Creo.** `reference` marks `live_verified` per
   command, and a test holds every such mark to a call in the recorded live evidence.

### 3. The target tree

P1 is the rebuild; later phases add capability without changing the shape.

| Command | Kind | Phase | What it does |
|---|---|---|---|
| `reference [--command]` | read | P1 | Contract; also the capability limits (`system capabilities` folds in) |
| `context` | read | P1 | Local configuration: workspace, policy, endpoint, token file |
| `doctor` | read | P1 | Install, service (reachable, protocol, creation API, sketch library), workspace, policy, release readiness — each with a fix |
| `changelog [--since]` | read | P1 | Changes between versions |
| `session status` | read | P1 | The running Creo: version, working directory, active model, model count, problems |
| `session cd --path` | write | P1 | Creo's working directory, inside the workspace |
| `workspace list [--kind] [--name]` | read | P1 | Model files on disk with their versions; needs no Creo |
| `model list` | read | P1 | Models in session: type, modified, displayed, origin |
| `model open --path` | write | P1 | Part, assembly or drawing from the workspace; newest version only |
| `model save --model` | write | P1 | New version where the model came from, verified on disk |
| `model close --model` | write | P1 | Close and erase from session; refused while changes are unsaved |
| `model discard --model` | write | P1 | Dangerous: close and erase, unsaved changes lost |
| `model show --model` | read | P1 | Units, material, mass properties, bounding box, bodies, datums, feature summary |
| `artifact export --model --format --output` | write | P2 | STEP, IGES, STL, PDF, DXF; staged, no-clobber, header-checked |
| `artifact render --model [--view]` | read | P2 | PNG of the model for an agent that can look; restores the window's view |
| `part create --name --units\|--template` | write | P1 | New part from a template; units never implied |
| `feature list --model` | read | P1 | Model tree order: id, name, type, status; internal features hidden |
| `feature show --model --feature` | read | P1 | Dimensions, references, sketch entities |
| `feature extrude --model --request` | write | P1 | Sketched profile on a plane, add or remove material |
| `feature delete --model --feature` | write | P1 | Dangerous; the preview lists children |
| `feature revolve\|hole\|thread\|round\|chamfer\|shell\|draft\|rib\|pattern\|mirror` | write | P2 | One command per ribbon tool |
| `feature datum-plane\|datum-axis\|datum-point` | write | P2 | Datums are features |
| `feature suppress\|resume\|rename` | write | P2 | |
| `geometry list --model [--kind] [--feature]` | read | P2 | Surfaces, edges, axes with ids and descriptors — what features reference |
| `geometry distance --model --from --to` | read | P2 | Distance or angle, to check a design (feasibility to confirm) |
| `parameter list\|set` | read/write | P2 | Typed values; `set --create` for new ones |
| `dimension list\|set` | read/write | P2 | `set` regenerates and reads back |
| `material assign` | write | P2 | From Creo's material library |
| `workflow run --input` | write | P2 | Steps of other write commands under one preview and confirmation |
| `operation list\|show` | read | P1 | Receipts of every write |
| `operation resolve --id --note` | write | P1 | Records that a person inspected an uncertain write; fixes nothing |
| `assembly create\|add\|remove\|check` | write/read | P3 | Components with explicit constraints; interference check |
| `drawing create\|add-view` | write | P3 | From a template; general, projected, section and detail views |

P4, by demand: sweeps, blends, ribs, drafts, sheet metal, relations, family tables, import.

At P1 that is 21 commands; about 50 at P3.

References for placed features (hole, round, chamfer, shell) are explicit: datum names, or
ids read from `geometry list`. Never interactive selection. Semantic selectors ("the four
vertical edges of BLOCK") come when live use shows ids are not enough.

### 4. What goes, what stays

Removed, with their tests, contracts, generators, examples and docs: the CREOSON route
(156 commands, `creoson_*.py`, `contract/creoson-interface.json`, `docs/CREOSON.md`); the
VB API route and mock (11 commands, `native.py`, `models.py`, `examples/*.creo.json`,
`docs/NATIVE_ADAPTER.md`, the `[native]` extra); `system capabilities`, `workspace inspect`,
`snapshot *`, `change *`. Git keeps them. Historical evidence files stay as records of
their time and are marked as such.

Kept and moved to neutral modules: tokens, locks and audit (`safety.py`), the receipt
store (renamed `operations.sqlite3`), the installation probe that `doctor` uses (from
`creoson_env.py`), the strict request validator, unit comparison.

### 5. Service protocol 2

Operation names mirror the commands (`session.status`, `session.cd`, `model.list`,
`model.open`, `model.save`, `model.close`, `model.show`, `part.create`, `feature.list`,
`feature.show`, `feature.extrude`, `feature.delete`, ...). Each reply shape is written down
once, used by the CLI's schemas, and exercised by the substitute.

### 6. Phases and their exit criteria

Each phase ends with every command it adds covered by command-level tests against the
substitute, recorded live by the live recorder in a fresh Creo session, documented in the
READMEs and the Skill, and committed locally.

- **P1 — rebuild.** Remove the old routes; move the kept modules; protocol 2; the 20
  commands; `--dangerous`; `--request -`; the quiet output; the permission wording in the
  Skill. Also try registering the service as a plain J-Link application, to learn whether
  reads and edits work without the Object TOOLKIT Java licence.
- **P2 — see and edit.** Geometry reads, render, export, parameters, dimensions, material,
  the placed and datum features, suppress/resume/rename, workflow.
- **P3 — assemblies and drawings.**
- **P4 — by demand.**

## Consequences

An agent reads one small tree whose names say what they do, and whose every command has
run on Creo. The Skill stops being a router and becomes a playbook. Setup on another
machine is one component.

Costs: the CREOSON work — 153 commands, the interface index and its guards — leaves the
product. Each new feature type needs its own live discovery, as the extrusion did.

Open questions:

- Without the Object TOOLKIT Java licence nothing can be created. Whether reads and edits
  work with the service registered as a J-Link application is untested (P1 finds out).
- The jar and DLL are unlocked with the building machine's TOOLKIT licence, and the DLL
  prompts unless code-signed; how other sites obtain trusted binaries is a release decision.
- Explicit geometry ids may prove too low-level for agents; the design leaves room for
  selectors without changing commands.

## Notes from implementing P1

- Closing and discarding are two intents, so two commands: `model close` refuses while a
  model holds unsaved changes, and its error names both ways out; `model discard` is the
  dangerous one.
- `reference` also says `uses_creo` per command, and `live_verified` is null for the
  commands that never talk to Creo (`workspace list`, `operation *`, `reference`,
  `context`, `changelog`): there is nothing to verify live.
- Every write refuses a model that does not live in the workspace -- close and discard
  included -- not only the writes that save files.
- Registering the service as a plain J-Link application, to learn whether reads work
  without the Object TOOLKIT Java licence, was not tried in P1; it stays an open question.

## Notes from implementing P2 and P3

The tree above was the plan; `reference` is what shipped (52 commands). Where they differ:

- `artifact export` takes no `--format`: the output's extension names it (`.stp`, `.igs`,
  `.stl`, `.pdf`), one flag fewer to contradict, and `--format` is already the global
  output flag. DXF was left out; nobody needed it yet.
- `artifact render` writes a JPEG, not the planned PNG: a Creo window exports BMP, TIFF, EPS
  or JPEG, and JPEG is the one every image reader takes. `--width` and `--height` size it.
- `geometry distance` measures distance only. Angles can be read from `geometry list`
  (normals, axis directions); a measure of them comes when a design needs it.
- `feature datum-point` was not built: no feature of P2 or P3 needed one.
- `feature mirror-part` mirrors the whole part about a plane and merges the image, as the
  ribbon's part mirror does; mirroring selected features is a different element tree and
  waits for demand.
- `material list` joined `material assign`: an agent must see the library to name a
  material from it.
- `drawing dimension annotate` joined `drawing create|add-view`: a drawing without the model's
  dimensions is not what an engineer asks for. Section and detail views were not built.
- `assembly component remove` is dangerous: it takes the features that depend on the component.
- `workflow run` takes `--request` like every other request-driven command. Each step is
  planned when it runs, against the model as the earlier steps left it; only the first
  step is planned before the token is issued, and the token is bound to that plan. A
  workflow that stops at a failure is `stopped`; each step's own receipt says what that
  step did, and blocks if it must.
- `service install` is the one command that is neither a read nor a write of Creo: it
  checks a bundle against its manifest and puts it in creo-cli's own directory. It is
  still a gated write, because it changes what Creo will load.
- Creo taught several things the plan could not know, recorded in `docs/SERVICE.md`: a
  pattern's creation returns its leader and the pattern is found as the new pattern
  header; saved view orientations carry zoom and pan that must be stripped; drawing views
  are placed in screen coordinates and the sheet transform converts them; annotations
  show only in an active drawing window.
- Running every declared option on Creo, not only every command, found three things the
  substitute could not: a revolve about an axis of the part lost its axis (Creo drops it
  from a feature whose sketch is empty; it is now set again once the sketch exists), a
  `csys` constraint could never pass the CLI's reference check (coordinate systems were
  not in `geometry list`; they are now), and an outside shell may add volume (only an
  inside one must remove material). The live record now exercises every option.
  Drawing a spiral notebook afterwards found a fourth: `geometry list` returned edges
  earlier features had left behind -- rounded-away corners, edges listed once per feature
  that rebuilt them. Edges are now read through the faces' boundary loops, and the live
  record checks that a rounded edge leaves the list and that each edge is listed once.
  Looking at a drawing on the Chinese Creo found a fifth: a view's scale label, which
  Creo writes in the session's language, showed as boxes in the standard sheets' ISONorm.
  Drawings from a standard sheet now letter in Creo's own, localized font.
- A drawing of that notebook with every model dimension shown was not a drawing anyone
  could make it from: duplicates, offsets of helper planes, positions from the center.
  `drawing dimension annotate --feature`, `drawing dimension hide` and `drawing note add` joined P3,
  and `model show` on a drawing lists what it shows. Remodeling from datum planes on the
  spine and head gave the dimensions a maker needs; the Skill says to model that way.
- Finishing that drawing asked for what a person does next: move a dimension off another,
  add the thickness no feature carries, a title block, a surface finish symbol, and take
  back what was misplaced. `drawing note edit`, `move-dimension`, `add-dimension`,
  `add-table`, `add-symbol` and `remove` joined P3; `remove` takes what the drawing owns,
  `hide-dimension` stays for the model's dimensions. Moving and deleting dimensions went
  to the native library: Java's calls for a drawing's own dimensions are deprecated, read
  back offset from where they placed, or answer without doing anything (`docs/SERVICE.md`).
- Profiles grew by what a person sketches, not by new commands: `slot`, `outline` (lines and
  arcs, an arc given by the angle it turns) and rounded rectangles, and `holes` inside any
  of them. Areas stay exact -- Green's theorem segment by segment -- so the volume check of
  an extrusion or a revolve stays a check.
- `relation` became a noun of its own, as Tools > Relations is a place of its own; `model
  import` joined `model`, a supplier's STEP being a model to place like any other.
- Tolerances joined as `dimension set-tolerance`, a property of the dimension as its value is;
  the tolerance standard fits need is the model's, so `model set-tolerance-standard`.
- Drafts and ribs came forward from P4 as `feature draft` and `feature rib`: a molded or
  cast part needs both. The one choice a person makes by eye in each -- which way the faces
  lean, which side the rib fills -- is stated in the part's own terms (the part grows wider
  along the pull; the side the part closes), and read back.
- Sweeps came forward from P4 as `feature sweep`: a pipe, a handle, a groove. Two features,
  as a person makes them -- the path a datum curve, then the sweep along it -- in one
  command. The section's frame is stated in the path's terms (its start, the plane's
  normal, the path's left) and holds whichever end Creo runs the path from.
- Exploded views came forward from P4 in two parts, as a person makes them: the exploded
  state belongs to the assembly (`assembly explode apply`), the view that shows it to the drawing
  (`drawing view add --exploded`).
- Family tables came forward from P4 as a noun of their own, `family-table show|set|remove`, as
  Tools > Family Table is a place of its own; an instance is opened as File > Open does it,
  `model open --instance`, and is then a model like any other. Every instance set is made
  and read back, because Creo keeps the old value of a cell it will not take, silently.
- An assembly drawing's parts list is Creo's own table, retrieved and filled by Creo --
  associative, as a person's is -- not a table the CLI writes out; `drawing table move` and
  `drawing bom balloons` finish it.
- Geometric tolerancing joined as two commands, as a drafter adds it: `drawing datum add`
  and `drawing gtol add`; a frame attaches under a dimension, to an edge, or free, and a
  frame on a model's dimension is the model's, as Creo keeps it.
- Section and detail views, deferred at P3, joined `drawing view add` as options of the
  view a person adds, not as commands of their own: `--plane`/`--section` cut a general or
  projected view, `--type detail` takes a region of another view. The cross-section is made
  in the model, as Creo makes it -- a feature of the part -- and the preview says so.
  `drawing view move` joined because a layout is rarely right the first time; `drawing
  remove` takes views too.
- A title block, which every drawing has, joined as `drawing title-block apply`: the shop's
  first fields, placed and filled from the model, rather than a table each caller lays out
  and fills by hand. A title block of another layout stays an `add-table`.
- Registering the service as a plain J-Link application was again not tried; the question
  stays open.
