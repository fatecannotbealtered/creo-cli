# Create and verify an editable revolved part

**Current qualification stop:** The C15-r2 independent run found datum-plane
`feature show` responses with an incomplete nested `native_definition`. Matching
errors or missing definitions do not prove non-target features are unchanged.
The current repair is an unbuilt, unqualified source draft; do not treat this
recipe as a complete daily-route pass. See current handoff (private historical record)
for the actual component binding, evidence and remaining gaps.

This recipe uses the existing `feature revolve`, `feature datum-plane` and
`feature datum-axis` commands. Read each command's current `reference` entry before
preparing requests. It is a bounded engineering candidate, not manufacturing approval.

## Prerequisites and supported shapes

Use the candidate EXE and a live, source-bound Creo 13.4.1.0 service that advertises
`revolved_datum_readback: 1`. The existing native sketch DLL is also required. A new
JAR must actually be loaded; its presence in an installation directory does not prove
that Creo is using it. Follow the supplied Windows environment and component manifest.
Preserve the shared operation history and historical unknown records.

Earlier bounded public evidence covers these shapes, subject to the current stop:

- A signed offset plane from a readable datum plane or planar solid face.
- An infinite axis through two nonparallel planes, one straight edge or one cylinder.
- A first added solid, one-sided full 360-degree rotation, default body, and one closed orthogonal
  polygon or rectangle with at most 16 vertices. Each axial station has one material
  interval between its inner and outer radii. This includes simple sleeves and stepped shafts.
- An explicit rotation axis in the actual sketch plane, parallel to one sketch coordinate
  and one model coordinate. A sketched centerline or a readable existing axis/straight edge
  can define it.

Angular datum planes, partial/symmetric revolutions, curved or holed profiles, cuts into existing solids,
multiple radial intervals and complex topology are refused before dispatch. These leaves
remain outside the existing-model workflow allowlist. No sweep/thread or creating workflow
support is implied.

## Freeze the construction before writing

Record model units, profile vertices in sketch coordinates, sketch-plane and orientation
references, the model-space frame, rotation axis position/direction, angle, radial/axial
dimensions and expected volume. Record which old dimensions, feature states and references
must remain unchanged. A geometric construction plane or axis is not automatically a
manufacturing datum.

`geometry list` returns actual reference identities. Names are case insensitive and native
numeric aliases resolve to observed objects; nonexistent references are refused. Never guess
an occurrence, surface, feature or dimension ID from an earlier model. Datum display extents
do not bound material. Reversed endpoints of an infinite axis describe the same geometric line.

An offset sketch normally needs two explicit perpendicular datum references to locate its
origin. Inspect the preview's frame: `[u,v]` means `origin + u*x + v*y` in model coordinates.
Check its orientation and signed offset before confirming. External rotation axes must lie
in that plane. The preview includes the resolved construction intent and all requested changes.

## Prepare, build and edit

1. Create an owned directory and empty part with explicit units. Retain the frozen intent
   and request JSON files in the authorized workspace.
   Native creation immediately writes its first version and displays the model; authorization
   therefore includes session/change/persist. Check both the new file and independently read
   modified state. The current in-memory model can already report modified after creation;
   this is reported as unsaved alongside the first file, without an extra hidden save.
   Later features are separate unsaved changes until explicitly saved.
   The first file's bytes and filesystem identity must remain stable across the model
   reading. Changed, replaced or missing evidence cannot prove saved state. Inspect the
   unresolved operation; never close based on an earlier digest or repeat creation.
2. Read the actual default datums. Preview and confirm the offset plane. Read the created
   feature/geometry, then explicitly use its actual reference for the axis construction.
3. Preview the revolve request. Keep the preallocated operation ID. Confirm the same token,
   file identity, content, model/dependencies and scope. Do not automatically regenerate a
   new plan after a drift rejection.
4. Read `feature show`, `geometry list`, `dimension list` and `model show`. Inspect native
   definitions, section placement and independent solid proof, not the setter reply alone.
5. Select a driving dimension from the current model. Change it, regenerate, independently
   measure the intended geometric change, then restore it and repeat the checks. An external
   axis may leave radial distances as linear sketch dimensions; do not call them diameters.
6. Save the part. Close every owned dependent drawing before closing the part, reopen the
   saved files, and independently verify that the driving dimensions remain editable.

Use an explicit invocation budget for these multi-reader writes, for example `--timeout 120`.
This is a shared deadline for that CLI invocation, not 120 seconds for each RPC. Initial local
development measurements were about 7–9 seconds for preview and 14–33 seconds for confirmation;
they are not a speed guarantee. Keep creation as explicit leaves. The material/tolerance
workflow keeps its existing step and target limits; split tasks explicitly when needed.

The [three staged request examples](../examples/engineering/revolved-sleeve/README.md)
describe the synthetic 20/8/25 mm sleeve. They are separate leaf requests, not a creating
workflow. Read actual references after each construction and discover driving dimension
IDs from the resulting model before editing it.

## Inspect geometry and engineering properties

Creo can split a complete cylinder into seam-separated faces. The proof groups actual
coaxial faces, sums their areas, checks trimmed axial extents and verifies a connected,
closed circular rim at each end with physical planar-face adjacency. It also checks the
retained revolve definition and actual section entities transformed into model coordinates.
The whole solid must have the intended analytic boundary and volume. A matching volume alone
is insufficient.
Coplanar shoulders are grouped only when native shared edges connect their patches. Each
disk or annulus must have its own complete, coaxial physical rim(s) and corresponding radial
interval. Separate rings at the same axial station cannot be summed into one expected face.
Initial template datums can lack an extractable feature-definition tree in this SDK; their
actual geometry and identity are frozen as references, without claiming a complete constructor
readback. Newly created offset planes, axes and revolves require their own readable native
definitions. Missing section status, wall geometry or edge adjacency cannot authorize recovery.

Native curved bounding boxes may be conservative. The result reports the raw outline
separately; exact bounds are derived only after the cylinder/plane/rim proof succeeds.
Numeric comparison thresholds are computational checks, not dimension manufacturing tolerances.

Use [engineering properties](ENGINEERING-PROPERTIES.md) for an explicitly synthetic material
and numeric tolerance on an actual driving dimension. Verify density units, volume and mass
independently. Record upper/lower deviations and the model tolerance standard, then save/reopen.
STEP geometry does not prove material assignment, tolerance ownership or native editability.

## Drawing and exchange files

Create a single-page associated drawing using the existing view and annotation commands.
Plan space for diameter/length text, leaders, contours and the title block before writing.
Read current drawing dimension IDs and positions. A linear radial sketch dimension must not
be relabelled as a diameter. Reference dimensions retain REF; do not fabricate general
tolerances, manufacturing standards, authors or approvals.

Dimension movement on one sheet now reads the actual anchor and envelope in separate
service calls, bounded by six samples, twelve seconds and the invocation deadline. Two
matching envelopes with consistent anchor-relative extents prove the supported translation.
The result uses those independent readings, not the earlier write reply. If native bounds
remain stale, unavailable or rerouted, verification is incomplete and the returned `box` is
null. The already moved anchor and raw observations remain recorded. Inspect without replay;
an output file or a successful location getter does not establish layout. Preview feedback
flags known page, table, text and view-boundary conflicts; leaders still need page review.
Raw observation arrays are audit evidence, including failed readings. Layout consumes the
independently verified result bounds, not a failed sample or the write reply.

The [stepped-sleeve example](../examples/engineering/stepped-sleeve/README.md) adds an explicit
external axis and negative offset while staying within the same construction contract.

After a model edit, regenerate/update the drawing and independently check the annotation's
model association and value. Save/reopen both. Export STEP and PDF from the same frozen state.
Use a separate STEP consumer to check units, solid validity, axial spans, radii and volume.
Render and actually inspect every PDF page: diameter text, leaders, length dimensions,
contours and title lettering. Keep automatic geometric checks and human visual judgments separate.

## Failure and recovery

A changed/replaced/deleted request, stale reference, changed scope or consumed token must
not be confirmed. Native failures can leave partial changes; no rollback is assumed.

After a lost reply or final receipt failure, use a new CLI process to query the original
operation. The retained request and frozen construction intent support independent inspection
even if the original request file is gone. `operation query --id ... --model ...` records
current evidence without settling the original receipt. Inspect its `construction_verification`.
Preview `operation resolve --outcome ... --evidence ...` only for an independently supported
outcome, then explicitly confirm registration. Missing evidence or a different service generation
keeps the original unknown. Never replay the original create to discover whether it applied.

Registration preserves the original report. Execute only explicitly identified remaining
save/export/close actions; there is no automatic rollback, cancellation or resume.
