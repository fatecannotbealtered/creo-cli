# Existing occurrence constraints

This candidate adds a public path for changing an existing occurrence's assembly
constraints in place. C3 has bounded native results for ordinary-part occurrences,
repeated parts, a direct rigid-subassembly target and legitimate dependent motion.
Five confirmed edits and their separate persistence stages are listed under
[evidence](#evidence-and-coverage), including independent final-package use.
Use the actual delivery binding for the EXE, loaded Java service, retained native
library and test instance. This candidate does not replace r25-S12 or stable r20b.
Source/HTTP results and a successful setter are separate from native engineering
qualification; neither supplies a missing save/reopen or independent-use result.

Contents: [scope](#scope), [internal datums](#internal-construction-datums), [query and edit](#query-and-edit),
[verification](#verification), [save and continue](#save-and-continue),
[failure and recovery](#failure-and-recovery), [evidence](#evidence-and-coverage).

## Scope

The owner must be a loaded millimeter assembly with 1–32 direct occurrences and a
complete readable constituent inventory. Its actual current model and graphics
window must both identify that owner in normal, un-exploded assembly context.
Dynamic positioning is refused. Queries and previews do not activate a window or
change an exploded state to manufacture this context.

The target may be an ordinary part or a rigid subassembly containing one level of
ordinary part occurrences. The candidate preserves that subassembly's definition;
it does not edit a child through a nested occurrence path. All admitted occurrences
must be active, placed, fully constrained and free of unsupported placement modes.
Flexible, suppressed, packaged, substituted, bulk, unplaced and unclassified modes
are refused. A missing required getter is incomplete evidence.

This first profile requires an explicitly empty placement-set and movement inventory,
each native constraint's unassigned set index and normal attributes, and complete
no-interface references. Named placement sets and component interfaces are refused;
the setter must not silently discard their metadata. The observed raw interface type
`-1` remains distinct from PTC's official `PRO_ASM_INTFC_NONE=0`.
Each constraint slot retains its actually read empty-string or null custom data
exactly. Missing or failed reads and nonempty application data are refused.

The new constraint set is a complete replacement of the target's constraints and
must keep its current count, within 3–6 constraints. Adding or removing a constraint
is refused before writing in this profile. The bounded request supports planar
mate/align, explicit signed offsets in millimeters,
and explicit applicable sides. Datum planes require their observed yellow/red
side; physical planar surfaces use the explicitly inapplicable datum-side value
declared by reference. Do not infer a side from a name, insert an implicit offset,
or change units to make a request fit. The request must provide enough independent
planes to constrain position and orientation. Other constraint types are outside
the editable request, even when some can be preserved on unrelated occurrences.

Raw getter evidence and applicable intent are separate. An independently identified
physical plane uses `DATUM_SIDE_NONE` in the edit request. Its raw side getter may
return yellow, red or null; these values remain in the observation and do not flip
the physical surface normal. A datum plane still needs an actual known yellow/red
side. A missing getter, an error or an unknown enum is incomplete, not an
inapplicable field. The installed `ComponentConstraint.GetOffset` contract defines
a present returned null as zero for known mate/align types, including offset types.
The observation retains that null; the explicit edit request uses numeric zero.
Missing, failed or unclassified offset readings cannot supply zero.

The owner may contain placement features, datums and coordinate systems; unsupported
assembly engineering features and driving relations are refused. Parameters,
features, units, material, constituent geometry, dimensions and relations remain
protected. A reused owner definition is refused when another loaded assembly
references it. Complete current-session reverse ownership is required. External
unloaded reuse is not proved absent: this path does not claim arbitrary-depth,
instance-specific overrides, automatic cloning or complete enterprise impact analysis.

Repeated use of a component model is supported by selecting one actual direct
occurrence ID. A model name that matches multiple occurrences is ambiguous. Editing
one occurrence does not authorize changing the shared part or subassembly definition.
The command is excluded from workflow composition.

## Internal construction datums

The v2 reader keeps every catalog row. It classifies a datum using the actual
`Feature.GetIsVisible` result and its recorded source. Internal references are
`protection_only`; the edit request cannot use them as new assembly-side or
component-side references. An internal plane is not treated as fixed owner geometry
merely because its occurrence path is empty.

Only a root owner's internal datum with a complete, independently read construction
definition may follow an authorized occurrence. The required evidence includes its
actual owner, feature/surface IDs, active status, parents and sole child consumer.
Its definition must have one completely enumerated offset constraint with exact
indexed element paths, a real selected reference, raw offset, flip and default fit.
The definition reference retains `DatumFeature.WFeature.GetSolid` owner provenance
and the applicable native root/leaf/path readings. A name, matching offset, nearby
ID or unchanged feature count cannot establish that relationship.

The client independently derives the unique consumer and matching constraint slot
from those identities, dependency links and definition. It checks both the datum's
coordinate frame and the consumer's actual solved plane. Before/after comparison
allows only the frame mapping and offset change derived from that frozen reference
and the authorized constraint. It preserves all other definition fields. Unrelated
owner planes and internal references inside parts or rigid child definitions remain
strictly protected. Ambiguous slots, incomplete readings or unexplained movement do
not receive an exemption.

For the admitted default-fit definition, raw fit type `-1` has the documented default
meaning. Reference, radius and outline getters are inapplicable in that mode; the
reader reports that applicability and does not fabricate an outline or require an
unrelated pointer getter. A fit change remains outside the permitted placement edit.
The optional dimension-driver ID crosscheck remains explicitly `not_checked`.
The supported relationship uses actual dependencies, the complete datum definition,
the native constraint and independent geometry; equal offset numbers alone are
insufficient. This does not qualify an unread dimension-driver mapping.

## Query and edit

Begin at the package README and START entry. Supply the declared current environment,
legal host dependencies, authorized owned input and continuous operation history.
Verify the actual instance generation and loaded component provenance. A health reply
is process evidence; it does not recover a pending CAD call or prove normal context.
The v2 profile requires service capability `assembly_constraint_redefinition=2`.
A version-1 or missing capability is refused before CAD preflight; process-only
capability inspection is allowed. A service omitting required observation provenance
is incomplete and cannot authorize the setter.

Discover the exact flags, request schema, capability requirement and output fields:

```powershell
creo-cli reference --command "assembly component list"
creo-cli reference --command "assembly component show"
creo-cli reference --command "assembly component redefine"
```

Read the existing owner and select an occurrence from its returned inventory:

```powershell
creo-cli assembly component list --model transfer_cell.asm --editable
creo-cli assembly component show --model transfer_cell.asm --item <returned-id> --editable
```

The editable reader returns actual constraint sets, both reference identities and
their planar catalog, applicable sides, units, component paths, placement status and
component-path transforms. The selected occurrence also supplies a copyable edit
request and its current generation/state binding. Ordinary list/show remain useful
bounded readers; the editable form requests the stronger constraint snapshot.

The authenticated native payload supplies its actual service UUID. The client checks
it against process admission and uses that payload UUID for the selection; a later
health reply cannot relabel an earlier CAD observation. The state also retains
`Session.GetCurrentDirectory` and each required model's `Model.GetOrigin` result and
readback status. Missing origin evidence is refused; the working directory is not a
substitute origin. Changes to this engineering context invalidate the selection.

Actual constraint selections retain `Selection.GetPath`, `ComponentPath.GetRoot`
and applicable `GetLeaf` evidence, plus the component feature's actual owner. The
planar catalog separately labels its expected root and leaf as constructed
identities; these are not claimed as native selection getters. A model-local
component selection may have no path. A returned `[targetID]` path is converted to
local `[]` input only after its exact occurrence, owner, selected model, root and
leaf have been checked. A rigid subassembly may also supply an empty path rooted
at its own definition. Sibling references keep their occurrence-specific paths.
Foreign roots, another occurrence of the same model and arbitrary nested paths are
refused; numeric IDs or matching model names alone do not establish ownership.

Copy the returned edit request to a new workspace JSON file. Change the intended
offset or replace a reference with one actually present in the returned catalog.
Keep the target-side reference local to the selected component definition. An
assembly-side reference may be owner-local or belong to another direct occurrence;
the catalog distinguishes repeated models by occurrence path. Do not invent an item
ID, use a nested path, or substitute a reference from a different session or model.

Declare the exact possible-moving set shown by the new relationship's dependency
analysis, including the target and its affected dependents. A reference replacement
can introduce a new dependency or cycle. If the preview refuses an incomplete
declaration, inspect the actual engineering intent before preparing a new request;
do not authorize every component to bypass protection.

```powershell
creo-cli assembly component redefine --model transfer_cell.asm --component <returned-id> --request constraint-change.json --dry-run
creo-cli assembly component redefine --model transfer_cell.asm --component <returned-id> --request constraint-change.json --confirm <returned-token>
```

Inspect the old/new constraints, exact occurrence/model, reference identities,
offsets, units, influence set, protected objects and unchecked items before confirming.
The preview has no solved native prediction. Confirmation freshly checks the frozen
selection, engineering baseline, files and authorization, then calls SetConstraints
on the existing component feature and regenerates the assembly once. It does not
delete/re-add, replace a family member, edit part geometry or use an exploded pose.

## Verification

The first post-write observation is independent of the setter result. Success needs:

- The same owner, occurrence inventory, target occurrence ID/path and component model.
- The requested constraint identities, types, sides and offsets read back completely.
- Active, fully constrained regenerated state and actual component-path transforms
  satisfying the requested plane relationships.
- Unchanged constraints on non-target occurrences, permitted dependency-edge changes
  only, and unchanged poses outside the declared influence set. A dependent may move
  when its retained constraints independently justify its resulting pose.
- Protected owner attributes, constituent engineering state, rigid-child definitions,
  file origins and session model inventory remaining consistent with the frozen baseline.

Inspect the actual assembly relation visually as a separate engineering check. A
plausible image, placed flag, setter success, component count or mass does not replace
constraint and pose readback. GetPosition's initial placement is not the required
component-path transform. Drawing-context and exploded transforms cannot be compared
as if they were normal assembly positions. Global interference is a separate check
and does not prove the intended constraint relationship.

## Save and continue

A passed constraint edit establishes its checked RAM effects. Saving remains explicit.
Discover model save/close/open from reference, preview and confirm the necessary saves,
then retain the exact native file versions and hashes actually returned/observed.
Normally close the owner before its used components, verify closure, and reopen the
precise saved files and dependencies. Do not substitute an arbitrary latest file or
discard an unsaved result to make the state appear clean.

After reopening, query the editable occurrence again. Verify the same occurrence,
constraints, solved pose, unaffected objects and persistence. Prepare a second,
different offset or legal reference change from this new selection, then preview,
confirm, independently verify and save it. A request from before the first edit,
reopen or relevant topology change is not a reusable selection token.

Choose a public timeout based on the observed input and necessary reads; a larger
timeout is not recovery. Preserve the operation ID and first failure before deciding
whether only a documented remaining action is safe. This recipe requires no drawing,
BOM, balloon or geometry change to demonstrate constraint editing.

## Failure and recovery

Stale or ambiguous selections, missing references, unsupported sides, influence
ambiguity and insufficient authorization are refused before the setter. A native
solver refusal, partial setter effect, failed regeneration or failed independent
readback must retain the actual dispatched/completed stages and original operation ID.
No automatic rollback or replay is attempted. Old constraints and poses must be
independently established before claiming an unchanged failure or a restored state;
this path does not provide a cross-model atomic transaction.

If a required native read may still be running, stop all subsequent CAD dispatch to
that instance. Use only local operation show, process-only health and OS observations
until independent evidence establishes the original call and instance state. These
checks do not themselves clear the stop. New CLI processes, new Clients, a larger
timeout, storage repair or another state directory do not establish recovery. Follow
native read recovery (private historical record).

For a lost write reply without a pending-read stop, or after a formally established
recovery, discover operation query/resolve and inspect the original ID against its
actual owner. They use fresh domain observations and the same frozen constraint,
pose and protection predicates as normal confirmation. Registration does not rename,
rebuild, reapply or save anything, and it preserves the original receipt. Incomplete
evidence permits only the outcomes actually reported by the inspection; it cannot
justify applied. Retained proof is checked again for current contract sufficiency.

Keep the earlier C2007 verification failure, its separate partial registration and
the later save as distinct facts. The new v2 construction-datum rules cannot replace
that original receipt or supply a missing historical reading. A later saved file
does not turn the earlier verification into a pass. Evidence collected under the
new profile must identify its own source, generation and observation time. The C2
shutdown finding also remains open; later C3 results do not explain that event.

If the native edit completed but final receipt storage failed, preserve the record,
generated evidence and RAM effects. Missing acknowledged storage is not proof that
nothing happened. Do not repeat confirmation or manufacture a new operation to obtain
a cleaner receipt. Repair local storage separately, establish any pending-call state,
then inspect the original operation. See [operation recovery](OPERATION-RECOVERY.md).

## Evidence and coverage

The following native records bind the C3 product source
`30ff5493bcd9ad6ba9e8c157081c7d0eb8213ee7` and its actual loaded components.
They are individual checked results, not an aggregate feature-coverage score.

| Native confirmation | Checked result | Limited engineering fact |
|---|---|---|
| `C3013`, operation `3acabfdcf13e4510bd382ad3ff9be85f` | 68/68 | An existing ordinary-part occurrence changed its offset from 12.25 to 16.75 mm; independently read constraints and solved pose passed. |
| `C3022`, operation `3460c4cdcac04af69ea3509183404227` | 68/68 | After exact-file reopening and a fresh query, a legal reference replacement and -6.25 mm offset passed independently. |
| `C3027`, operation `011e5389b9874788a794ad74322cb5fa` | 98/98 | One of two occurrences of the same part moved to 44.25 mm; the other occurrence remained at -29 mm and protected state passed. |
| Independent `015`, operation `f6433f1f47e54783995192424a0cd3e0` | 132/132 | A selected repeated-part occurrence changed X offset 38 to 46.5 mm; its rigid dependent followed by 8.5 mm while unrelated occurrences stayed fixed. |
| Independent `038`, operation `e6e3960fd81f4a7ca39b3ad7793655ad` | 124/124 | After exact-file reopening, the direct rigid-subassembly occurrence changed its relative TOP offset 45 to 51 mm; its internal definition and other occurrences remained protected. |

After the first edit, a separate save produced the exact assembly version `.asm.2`.
All four loaded owned models were normally closed, an empty session was observed,
and that exact assembly was reopened before the second edit. The second edit was
separately saved to `.asm.3`. The repeated-part edit was separately saved to its
owner's `.asm.4`, followed by normal closure of all three loaded models and an
observed empty session. These later saves do not rewrite the edits' original
`completed/applied/unsaved` receipts. This evidence does not yet show an exact-file
reopen of the repeated-part result.

`C3028` refused repeated confirmation with `E_CONFLICT`; the diagnostic journal's
byte count remained unchanged. This is no-replay evidence at that diagnostic
boundary, not proof that an unrelated or earlier request has reached a terminal state.

The independent engineer used the immutable r26-C3 package in a new Chinese/spaced
directory and copied five saved native inputs into an owned engineering directory.
The first edit took 135.476 seconds; the direct rigid edit took 194.167 seconds.
Each used the explicit 300-second preview/confirm budget; these measurements do not
guarantee other input sizes. Separate fresh public queries and engineer comparisons
confirmed the constraints and actual poses. The first result was saved as `.asm.3`,
all five models were normally closed, an empty session was observed, and that exact
version was reopened before the second edit. The second result was saved as `.asm.4`;
the final public inventory showed all five models clean. A second full reopen of
`.asm.4` was not run.

The engineer retained 50 CLI records: 49 succeeded and the initial PowerShell array
invocation returned `E_USAGE/not_started`. It was corrected without developer IDs or
internal calls. Actual Computer Use inspection was separate from getter verification;
two tool screenshots were viewed, no image files were saved, and Computer Use was
released. The package bytes and all source inputs stayed unchanged. Its embedded
qualification remains the creation-time snapshot; the later
R38 qualification (private historical record) binds the same package.

These cases qualify their actual ordinary-part/rigid-target, datum-reference and
normal-context configurations only. They do not establish all side combinations or
physical-plane cases. The nonempty rigid-definition and dependent-motion witnesses
belong to the independent cases, not the earlier empty rigid comparisons. Global
interference, unloaded external owner reuse, manufacturing intent and the construction
datum dimension-ID crosscheck remain unverified.

The delivery qualification record binds the raw native evidence separately from
software counterexamples and HTTP/socket faults. No real native fault injection is
claimed by these positive cases. Later documentation commits describe these results;
they do not become the product source used to build or run C3. Keep original failures,
source-driven native experiments, final native execution and independent use separate.

The historical migration cohort remains 58/71. The candidate's added command produces
120 declared commands, 356 leaf parameters, 72 write declarations, 59 public-runtime
write paths and 36 investigation groups in the current software inventory;
these are discovery/runtime counts, not native design-task
coverage. They do not qualify STEP, deletion, symbol editing, old REF results, opaque
mass findings or cross-time drawing boxes. The candidate stays private, 1.1.0-beta.1,
FCC partial and unpublished; stable r20b and r25-S12 retain their own historical bindings.
