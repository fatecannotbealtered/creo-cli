# Bounded model management

`model set-common-name` changes Creo's native common name. It does not rename the
model file, change its session identity, or create a parameter. `model discard`
irreversibly abandons the selected part's in-memory changes; it does not delete
disk files and does not reopen anything automatically. Both use the public
scope → preview → one confirmation → independent readback lifecycle.
Native interface reference: [PTC Creo 13 Model](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/api/dita/c-pfcModel-Model.html)
(`GetCommonName`, `IsCommonNameModifiable`, `GetIsModified`, `ListDependencies`, `Erase`).
Documented interfaces alone do not establish the candidate's actual loaded behavior.

## Supported session

This profile permits standalone parts only: at most 16 models, 32 windows,
128 features and 4096 geometry items per part, and a 512 KiB protected snapshot.
Family-table members/generics, dependent parts, and sessions containing drawings
or assemblies are refused. Close only your own saved, unambiguous models before
preparing this profile. A dependency or unreadable inventory is not an empty set.
Neither command is added to the supported workflow composition set.

Readback capability 2 distinguishes a successfully returned origin from a failed
`GetOrigin`. A returned path identifies a saved source location, not equality of
current memory and disk. A successful empty origin is `no_origin`; it does not
prove the model is newly created. A real unsaved new model without a verified
version file is outside this management profile. Failed getters are `unreadable`.
Both management readers and every protected part need complete native origin and
family information plus the actual version-file identity. The current working
directory never substitutes for unreadable or absent storage provenance.

Family classification records completeness, kind, immediate generic, row and
column counts. Optional null/empty row lists are distinct from getter failure;
only the documented non-instance exception from `GetImmediateGenericInfo` means
no immediate generic. Partial rows, contradictory counts and failed family
getters refuse. A generic with columns but no rows is still outside this profile.

Plan a bounded invocation budget for the full protected inventory. In the final
two-part name fault cases, confirmation processes took up to 46.125 seconds including
EXE startup, planning, native work, verification and records. Those cases used explicit
`--timeout 120` on each call; this is not an RPC-time or speedup claim. Use an explicit
budget appropriate to the observed task. A timeout never permits replay; retain the
operation and inspect its outcome. The 16-model ceiling does not promise every such
inventory fits that budget, and required checks are not cached across writes.

The scope must authorize observing every protected part and its file directory,
and changing the selected target. Discard also requires dangerous authorization
and the explicit `--dangerous` CLI option. Preview binds the instance, native
origin/version state, model/window identities, geometry, features, dimensions,
material, tolerances, parameters, relations and every saved version's file identity
and digest. Any intervening change requires a fresh preview; never replay an
unknown operation.

## Name round trip

Read `model show` first. `common_name_readback.readable` and `modifiable` must be
known; a getter error cannot mean an empty name or permission to change it. The
current input contract is one nonempty line of at most 80 characters. An empty
original name therefore cannot be restored by this command; prepare an explicit
synthetic nonempty baseline for a reversible acceptance exercise.

Use `reference --command "model set-common-name"` for current parameters. Preview
and confirm the requested value, then inspect the receipt and `model show`.
Even a same-value request can leave `modified=true`; this means unsaved, not clean.
This Creo version can also return `modified=false` after a changed common name while
all disk bytes remain unchanged. The changed property is still reported unsaved;
the native flag is retained and is not independent proof that this property was saved.
Ordinary close refuses a known changed name until a subsequent verified public save
matches the current native file. Explicit discard remains a separate dangerous action.
Save explicitly, close the saved model, and reopen its latest native version to
prove persistence. Geometry and engineering properties have separate checks.

The supported PTC `bom_description_down.tbl` template uses
`asm.mbr.ptc_common_name` for DESCRIPTION. This does not make name editing with
an assembly open part of the bounded profile. Association/update behavior needs
its own assembly/BOM acceptance. Title-block cells are literal values sampled
when applied (the default title can use the common name); existing cells do not
automatically track later name edits. Do not substitute a parameter or claim an
automatic title/BOM update from matching displayed text.

## Explicitly discard a synthetic modification

1. Open an owned test part and verify its intended baseline. Perform a public
   `model save` and require its saved, verified receipt. The current instance's
   receipt must match the latest native file's path and digest.
2. Make only a documented, reproducible synthetic edit. Do not save unwanted
   edits merely to satisfy the discard gate. Unknown modified state, missing
   save proof, unresolved conflicting operations and unknown dependencies refuse.
3. Preview `model discard --model <part> --dangerous --dry-run`. Review exact
   model, unsaved state, disk baseline, windows and irreversible memory loss.
4. Confirm once with the same arguments. Check target absence, unchanged disk
   versions and unchanged other models/modified states/window identities.
5. Explicitly open the saved file and independently check the baseline property
   or dimension. Absence from session alone does not prove successful discard.

Closing an active target can select another existing window or leave the empty
base window. Camera restoration is outside this contract. If closing a window
succeeds but native Erase fails, the session may already have changed: report
partial/unknown, retain evidence and block conflicting writes. Do not call it
not-applied just because the model remains loaded.

## Recovery and public evidence

`operation show --id <id>` reads retained history offline; it needs neither CAD
nor task scope and never repeats the original write. `operation query --id <id>
--model <original-model>` performs current observation, requires observation
scope over the retained paths, and verifies the original instance. Discard can
be observed even when its target is already absent. Query never reopens it.

Only the outcomes listed by the independent query can be explicitly registered
with `operation resolve --id <id> --outcome <outcome> --evidence "<substantive observation text>"`,
using its preview/confirm gate. This branch independently observes again and retains
its own hashed evidence; `--evidence` is an explanation, not the query ID.
This records observation, preserving original failure/uncertainty and child
evidence; it is not replay, undo or automatic continuation. A new process's show
exposes evidence ID/digest, registration conclusion and bounded provenance.
Missing or altered evidence remains unavailable/invalid and blocks conflicting
writes. Restore only an authentic retained copy; do not invent evidence or clear
history. Unknown or incomplete native readback cannot support applied registration.
The summary is under `operation_status.extensions.creo.model_management_inspection`.
After a lost reply, a same-value request with fully identical model/window/file state
supports `not_applied`, not `applied`; matching the requested value alone is not a change.
Registration preserves the original unknown execution receipt.

Historical evidence hashes prove byte integrity only. An older registration with
insufficient origin/family observations remains visible but is marked insufficient
for current protection. Do not rewrite its baseline, replay the write, or use a
new state directory to bypass it.
