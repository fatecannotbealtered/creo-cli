# Bounded editable rectangular shells

Use the existing `feature shell` leaf for one saved, standalone, non-family part.
The profile is an axis-aligned rectangular prism in mm, one active body, one explicit
complete face at maximum model Z, and uniform inward thickness. It requires one active
editable protrusion without relations and complete standalone-part session protection.
Closed/outward shells, multiple removed faces, curved boundaries, multiple bodies,
local thickness and assembly/family dependency combinations are refused.
Shell does not join workflow composition. The candidate stays beta/FCC partial.

## Freeze the engineering task

Record actual units, signed model coordinates, opening, wall/base thickness, source
file identities, original dimensions and protected objects. Model maximum Z is a
coordinate direction, not an inferred named drawing view. Find the face through
current geometry. An example never authorizes a hardcoded face ID. Discover current
syntax and request schemas with `reference --command 'feature shell'`.

The synthetic sample is 60×40×24 mm with bounds `[-30,-20,-24]` to `[30,20,0]`.
Its opening faces +Z. A 2 mm shell has a 56×36×22 mm cavity and volume 13248 mm³.
Changing thickness to 3 mm produces a 54×34×21 mm cavity and 19044 mm³, then returns
to 2 mm. `R12_SYNTH_D7850` is a synthetic density-only material (7850 kg/m³), with
no material grade, company standard or approval. Numerical comparison tolerances
are verification tolerances, not manufacturing tolerances.

## Preview and verify

Use an authorized JSON file with the actual top surface, mm units, inward side and
positive thickness. The plan binds request bytes/file identity, target/source/instance/
dependencies, body and surface, complete geometry, original dimensions, files and
protected state. Thickness must leave a nonempty cavity and exceed the reader's
resolution. Unsupported references/topology and detected drift refuse before dispatch.

The frozen intent includes a feature-name policy. A supplied name must match the
new feature's actual name from the independent feature inventory, using Creo's
case-insensitive comparison. Omitting the name explicitly keeps the native default;
it does not authorize a later rename. An unnamed native feature may have a null or
empty name, but a missing name getter is incomplete. The creation reply cannot prove
the name, type or active state. Normal confirmation, query, registration and retained
evidence use the same independent identity checks. Old intent without this policy
remains insufficient; a query never renames or recreates a feature to repair it.

The service must expose `prismatic_shell_readback: 2`. This flag does not replace
loaded JAR/DLL/source/instance verification. The reader obtains the retained native
shell definition and the actual body's planar surfaces, orientations, closed contours
and two-face edge adjacency. Failed reads remain incomplete, never a successful empty set.
Profile 2 also preserves the requested driving thickness when native creation rounds
its initial value. The same authorized operation identifies that new dimension and uses
the existing dimension/regeneration API; it changes no configuration and never repeats
feature creation. Full independent definition and body checks still determine the result.
Old components are rejected before dispatch. A correction failure can leave a partial
shell and does not imply rollback.

Confirmation compares the exact opening, inner/outer plane regions, wall/base locations,
full boundary segments, area and volume with frozen intent. Coplanar patches may share
internal edges, but their combined exterior boundary must still match that particular
region. Counts, bounding boxes, a shell type or reduced volume alone cannot prove success.
Native contour points and intended plane identities use the same six-decimal mm
coordinate resolution. The requested thickness and analytic area/volume retain their
original numeric values for comparison. This readback resolution is not a manufacturing
tolerance and does not qualify sub-resolution geometry.
Parameters, material/tolerances, original dimensions/features, protected models/windows
and saved versions are checked separately.

`feature show` exposes `native_definition` and `native_solid_geometry` for a shell.
Read them with `dimension list`, `model show` and feature state. Discover the actual
driving thickness ID, edit and return it, regenerate, and inspect geometry at both
values. A setter echo is insufficient. Explicitly save, close all related owned clean
models, reopen the saved version and verify the editable feature and thickness again.

## Drawing and exchange files

Reserve view/annotation regions before drawing. Use the needed native views and
associated model/reference dimensions. Inspect actual boxes and known overlap feedback
during editing. Leader/contour readability still needs full-page review. Keep REF where
the dimension is a reference. The sample drawing is not manufacturing approval.

For `drawing layout apply`, discover and use each actual native view **name**; the
layout request does not select views by numeric ID. Read model dimensions and native
reference attachments separately: the driving shell thickness may appear as `O_THICK`,
whereas a drawing reference dimension measures selected model edges. A matching number
alone does not prove the attachment.

Reference-dimension previews state the expected edge/model/sense attachments. Native
default sense is `auto`, whether its option is explicit or omitted; both forms require
the same independent association check. Point senses retain their explicit meanings.
Wrong edge, source model, sense or missing attachments cannot pass because the displayed
number happens to be right. A failed check can follow a real annotation write: retain
the original receipt, read the existing object and protected resources, then use the
documented explicit observation-registration process only when evidence is sufficient.
Do not recreate the annotation or omit options to bypass its verifier.

Some reference dimensions have no readable native text box. Do not treat that as a
zero-sized box or an automatic layout pass. The bounded move command may refuse such
an object before dispatch. Keep the refusal; if changing the annotation is necessary,
use separately previewed supported add/remove operations and inspect the new native
attachments. Verify absence of the removed object and persistence of its replacement
after saving, closing and reopening. Review the complete `REF` lettering as well as the
number: arrowheads can obscure the `R` even when the value remains readable.

`artifact export` selects STEP/PDF from the `.stp`/`.pdf` output extension; the global
`--format` selects JSON/text/raw response output. Use new explicit paths. An independent
STEP consumer checks mm, one valid solid, outer bounds, inner planes, opening, clear
cavity, material in the wall/base regions, and volume. STEP does not prove native
editability or material/density; read those in Creo. Render and inspect every PDF page.

## Failure and independent registration

Keep the preallocated operation ID. Repeated confirmation never replays a completed
or unknown shell. A native failure can leave a partial feature or changed geometry.
Complete before/after evidence determines the result; missing evidence keeps unknown.
There is no automatic rollback, cancellation or resume promise.

`operation show` reads history offline. Scoped `operation query --model <part>` observes
the current body against retained intent without rerunning shell. `operation resolve`
uses the same definition/boundary/protection predicates. The status extension is
`prismatic_inspection`. Evidence integrity and current sufficiency are separate.
Final receipt storage failure retains a reliable unresolved checkpoint, readable by
a fresh CLI without a live Plan closure. Register only from adequate independent
evidence, preserve the original receipt, then explicitly plan remaining work. A new
service generation or missing intent cannot prove an old operation was unapplied.

Use the delivery index for exact source, binaries and executed cases. Development
observations, final EXE native acceptance and independent use are separate ledgers.
