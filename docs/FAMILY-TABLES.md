# Bounded numeric family tables

Use `family-table apply` and `family-table remove-instance` for explicitly owned
synthetic part variants. The generic stores the table; an instance is a native
derived model, not a renamed copy or a parameter pretending to be a family row.
The candidate remains beta/FCC partial. Consult `reference --command` for exact
arguments and the bundled request/result schemas.

## Before planning

Work in an owned directory with a saved, editable solid part. Record its units,
features, dimensions, full geometry, material/tolerances, actual native origin,
all version files and any protected open parts. Read actual dimension symbols
and IDs: equal numbers alone do not identify the intended driving dimension.
Use a separate source copy and retain its initial native file.

The write profile supports at most four instance rows and four positive numeric
length dimension columns. Requests use explicit JSON files with observe scope;
bytes, file identity, parsed intent and actual model state are bound to preview.
Same-content file replacement is drift. Nested families, feature/parameter
columns, expressions and assembly/drawing dependency combinations are refused.
An empty or failed family getter is not evidence that a model is standalone.

Preview freezes the complete expected table from the original table, native generic
dimensions and requested cells. It includes column identities, the exact row set,
explicit values and every inherited/default cell. A new row's omitted existing column
inherits its frozen generic value; a newly added column defaults on unselected rows.
An unrequested extra column or an altered omitted cell cannot pass by matching the
resulting instance dimensions. Post-write table data never defines intended values.
Multiple request aliases assigning the same real dimension in one row are refused.
Native verification labels and table display order are separate from these cell semantics.

Each generated member must independently identify the selected generic. A same-name
standalone part, another generic's instance or merely matching dimensions/volume is
insufficient. Normal validation, current queries and retained evidence trust use the
same full-table and membership predicates. Hash-valid old evidence is not exempt.

Instances must be absent before apply. The complete current session must contain
only parts, with no dependencies outside the selected family, and the generic's
owned directory must contain no assembly/drawing files. This is a bounded
project/session check; it does not prove there are no references anywhere on disk.
Existing rows must have verified owned lineage in this service generation and
directory. Arbitrary closed legacy rows are not silently instantiated in preview
to discover whether they contain an unsupported nested table.
Known dispatched assembly/drawing references since row creation remain blocking
after the referencing model is closed. This profile does not requalify a formerly
used row after reference removal; use a fresh, explicitly unused synthetic row.

## Apply, independently inspect, save, and reopen

1. Save the generic explicitly. Read its actual dimensions and select the intended
   positive length dimension. Put the intended row names and `dimension:<symbol>`
   values in a request file using the generic's length units.
2. Preview apply. Check generic/source identities, existing table, affected row
   names, columns, object footprint and the stated creation of in-session members.
   Confirm once with the same file and scope.
3. Read `family-table show` independently. Then read each instantiated model's
   actual dimensions, feature states, geometry and units. The public verifier
   uses separate native getters; setter text or table strings are not the whole
   engineering result. Compare task-specific geometry or an independent STEP
   consumer where appropriate.
4. Save the **generic** and require the independently verified saved receipt.
   On the tested Creo13 build, newly generated or reopened members can be
   modified=true; saving their generic clears those flags. Read all flags again.
   `model save` on an instance refuses and identifies its generic. Never use
   non-family `model discard` as a workaround.
5. Close only owned models whose current state is independently clean. Close
   members before the generic; stop if a flag is unknown or remains modified.
   Do not infer cleanliness from unchanged table numbers or an existing file.
6. Reopen the exact saved generic and use existing `model open --instance` to
   recreate each selected member. Verify native dimensions and geometry again.
   An explicit new apply task can edit a selected row after generic save and
   clean member close. Unselected rows/columns and generic geometry are protected.

Creation of the initial solid is outside workflow. Neither family leaf is added
to workflow composition. Dynamic targets, automatic continuation and cancellation
have no new support here.

Choose an explicit invocation budget for the whole command, including repeated
independent reads. In the recorded two-row/two-column synthetic task, preview took
about 76 seconds; a 120-second confirmation budget expired during verification after
Creo reported the edit complete. That trial remains incomplete. A new process then
established the result with complete table, membership and geometry evidence; only
registration, save and clean close followed. The continued acceptance task explicitly
uses `--timeout 240`, based on that measurement. This is not a speedup claim, a universal
budget guarantee or permission to replay the timed-out edit. See the current delivery
index and [budget semantics](WORKFLOW-BUDGET.md).

## Remove one unused row

Removal requires explicit dangerous authorization and confirmation. Select the
exact row using current table readback. It must have been created by a verified
public apply in the current service generation and owned directory. A public
generic save after the latest family write must match the actual latest file;
the current table must match its verified owned baseline.

Open members, unsaved generic changes, unreadable identities/dependencies,
conflicting unknowns, and assembly/drawing reference combinations refuse in
preview, including retained evidence of an already closed referencing model.
An unconfirmed reference preview alone does not establish use.
The command removes only the row: it does not close a model, erase a
loaded member, cascade through dependencies or delete an instance file on disk.
Inspect the resulting table, generic geometry, protected parts/windows and version
files. Save the generic, close and reopen it, then verify the row is still absent
and remaining instances still produce their expected dimensions/geometry.

## Failure and recovery

Keep the preview's preallocated operation ID. Input/scope/table/source drift and
used confirmations refuse before dispatch. After a native failure, the tool reads
the actual table, instances, generic, windows and files. Native cleanup is reported
as an attempt; matching row strings alone cannot establish rollback when an
instantiated model or modified state has changed.
Default inheritance is also protected: restoring a number with a different native
default flag is not a complete rollback. The service retains raw/default observations
and reports cleanup mismatches; it does not promise that every failed apply can restore
inheritance. Incomplete restoration remains partial/unknown until independently observed.

`operation show` reads history offline. `operation query --model <generic>` checks
current native state within observe authorization and does not create instances.
`operation resolve` independently rechecks the retained intent before recording
an explicitly supported outcome. The inspection summary lives under
`operation_status.extensions.creo.family_table_inspection`.
If an instance needed for geometric proof is absent or unreadable, keep the
outcome unresolved. Query does not reconstruct it by rerunning apply or opening
models. Registration preserves the original receipt, including unknown execution;
it does not save anything or replay a completed row.

Final receipt storage failure retains a reliable unresolved checkpoint. A fresh
process can inspect it; repeat confirmation remains refused. Independently known
file changes are reported as partial persistence, not merely unsaved memory.
After sufficient evidence is registered, prepare an explicit remaining task.

## Acceptance example

A synthetic 20×8×10 mm native extrusion supplies two depth-driven members:
12 mm / 1920 mm³ and 16 mm / 2560 mm³. Editing only the first depth to 14 mm
expects 2240 mm³ while the generic remains 1600 mm³ and the second member remains
unchanged. Actual IDs come from current readback. Numeric comparison tolerances
are validation tolerances, not manufacturing tolerances or approval criteria.
Development observations and final EXE/package acceptance are recorded separately
in the current delivery index. No broader family-table or full-tree FCC claim
follows from this sample.
