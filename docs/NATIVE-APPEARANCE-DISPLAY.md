# Native appearance and display candidate

These commands are a new private beta profile. Static compilation and HTTP/stub
regressions do not qualify native execution. Use the final EXE/JAR/DLL binding and
the accompanying native acceptance record for scenario qualification.

Current C15 rebuilds the client and Java service after C14's real saved-color reopen
mismatch. New reference creation supplies a fresh random name candidate, then independently
reads the actual native ID and rejects a collision with another loaded source. It requires
`source_part_appearance_unique_reference=1`; an older service must refuse creation. Source
and controlled tests passed, but C15 Native persistence is not qualified. Unloaded external
sources are not searched and no global uniqueness guarantee is claimed. C10-H1 probe results
remain historical. Select exact components and scenarios through the
current handoff (private historical record).

The explicit reference-creation contract was introduced in C4. Its owned-phone Java-only
scenario has separately bound native evidence; it does not qualify full DLL startup or
later component combinations. C3-R2 reached the requested RGB but failed
its then-required native Name identity checks; the superseded g006 Name-reuse attempt
also failed. Those receipts and stopped generations remain unchanged. The new route
requires explicit replacement authority and separate identity/binding checks; it does
not delete Name checks or reclassify earlier failures as success.

The C2 repeated-source native image preserved a dirty source part while its owner
assembly remained clean. Its original render receipt incorrectly projected persistence
as unchanged. That receipt and image remain retained. The subsequent Python repair
uses the same complete final render observation for owner and source-part modified
flags: dirty means unsaved, complete clean evidence means unchanged, and incomplete
or contradictory evidence means unknown. It adds no getter, save, replay or rollback;
view restoration and image delivery do not establish that source files were saved.

The C2 independent phone constraint edit reached the completion-record storage limit.
Its public result remains unknown, and that instance is stopped without retry, save or
rollback. C3 stores complete oversized records losslessly within the existing bounded
JSON capacity, while retaining every observation, check and public receipt field.
This storage repair does not establish the old call's final outcome or grant permission
to resume it. Final-package native trials use new model copies and new instances.

C1's independent complete startup was blocked by host trust. Its Java-only startup
reported ready, but public `context` then failed on the absent native-loaded-image
witness before establishing an independent Java source identity. The executor correctly
stopped. C2 adds component-specific missing-witness diagnostics, independent Java identity
checks and a startup-host standard-stream fix; its rebuilt artifacts require their own
execution records. C1's 38 passing EXE/HTTP regressions remain C1 evidence, not C2 or native
workflow acceptance. Those historical C1/C2 results make no complete
startup-to-edit/color/image/save/reopen claim for a later candidate.

## Source-part appearance

`appearance show --model <part.prt>` reports the complete native source appearance,
its assignment inventory, the modified flag and every affected occurrence in the
current session. RGB is three finite normalized numbers in `[0,1]`. For an 8-bit
channel value, use `value / 255`; the setter does not quantize to display decimals.
The frozen C15 product's existing RGB comparison uses absolute tolerance `1e-12` for
each channel, with relative tolerance `0`. Retain the original unrounded values and
actual differences. This statement covers `rgb` and `highlight_rgb` only and grants no
exception for other fields; a saved/reopened result
also requires the same selected source and file identity, a valid actual reference and
unique matching assignment, and independent checks of all protected non-RGB appearance,
physical, geometry, constraint and occurrence fields. Density and units keep their
separate exact-comparison requirement. This documents the existing comparator in source
`72b1219f6c5ca2f0ef817e3cd4165f92228fb25a`; it does not broaden it or attribute the
cause of a native value difference.
`appearance.name` is a native reference's scoped ID, distinct from the cosmetic `label`
and model display/common name. The query's `reference_binding` records source context,
selection model/type, native ID, full visible appearance/assignments and
`whole_source_binding_observed`. These IDs are neither user labels nor portable global
palette identities. Keep the exact observed strings; do not predict a `ref_*` value.

The native setter may create three empty texture slots. Their count alone does not
establish absence of textures. The current contract requires every slot's native
type, asset path and complete placement readback; a nonempty asset path is refused.
Whole-model assignment is allowed, while face/body overrides remain refused. The
old first-color receipt lacked this full inventory and does not qualify the new
complete appearance-protection contract retrospectively.
The loaded source model's `GetAllAppearancesAndTextures` inventory is not a global
palette snapshot. It cannot establish that all unloaded users of an old reference were
inspected, and it does not authorize mutating an appearance shared by another object.

`appearance set` and `appearance restore` take a UTF-8 JSON request. Discover the
exact schema with `reference --command "appearance set"`. The source part must be
a standalone non-family part in the authorized workspace. Instance-independent
appearance overrides are refused. Face/body overrides and textures are also refused
by this first profile; they are neither removed nor silently hidden.

The default `reference_action` is `preserve`; its Name protection remains strict. An
actual RGB change to an existing non-null appearance, or a changed non-null restore,
is refused before dispatch with `E_UNSUPPORTED` unless the new replacement mode is
explicitly authorized. A same-value preserve request still has to satisfy all identity
and physical checks. A first RGB set from a null appearance remains the existing
default-creation route.

The bound effective change is exposed as `reference_transition`, separately from
`requested_reference_action` and its unchanged native wire policy. First creation is
`create_initial_binding`, with a null preview ID explicitly pending native allocation;
success requires the actual valid visible ID and one matching model-only target binding.
An explicit null restore is `restore_native_default`: it removes this model's override
and preserves shared reference definitions and other consumers. A recorded Name remains
historical when restoring into an initially null target; the private native request uses
an empty Name for allocation. No guessed ID or RGB-only readback qualifies these transitions.

First-null RGB example for a source actually observed twice in an owned assembly:

```json
{
  "scope": "source_part",
  "source_file_authorized": true,
  "affected_occurrences": [
    {"assembly": "holdout.asm", "component_path": ["40"]},
    {"assembly": "holdout.asm", "component_path": ["41"]}
  ],
  "rgb": [0.2, 0.4, 0.6]
}
```

For an existing non-null appearance, the separately authorized candidate adds two fields:

```json
{
  "scope": "source_part",
  "source_file_authorized": true,
  "affected_occurrences": [
    {"assembly": "holdout.asm", "component_path": ["40"]},
    {"assembly": "holdout.asm", "component_path": ["41"]}
  ],
  "rgb": [0.2, 0.4, 0.6],
  "reference_action": "create_and_bind",
  "reference_replacement_authorized": true
}
```

This mode requires `source_part_appearance_reference=1` and existing and intended
non-null appearances. Within this mode, missing/false replacement authority is
`E_FORBIDDEN`. `preserve` combined with replacement authority is `E_VALIDATION`.
`create_and_bind` with null restore is also `E_VALIDATION`; first-null creation and
null/default restore do not need or use this new mode. These fields are assertions of
the task's actual authority, not a way to grant access or bypass CLI policy.
Authority already granted for this same selected source and influence scope remains
valid; do not ask again merely to populate these fields. Each write still needs its own
fresh preview/confirmation, and additional targets cannot inherit that authority.

Copy exact occurrence IDs from the fresh query. The full set must match, including
repeated source parts and every root/path by which an assembly currently contains
the source. Omission, addition, duplication or a newly loaded referencing assembly
blocks confirmation. Both the source and affected assembly paths need the declared
task scope. `source_file_authorized` is an explicit request assertion; it cannot
grant access or override CLI policy.

The influence inventory covers the current session. It does not prove absence of
unloaded external references. Work on the owned project copy, and authorize editing
that source file itself. Saving that source may affect an external design that
subsequently retrieves it; the CLI does not claim a full-disk reference search.

Preview and confirm with identical arguments and request bytes. The new mode creates
a separate appearance and binds it only to the authorized source selection; it never
sets RGB/properties on the old/current appearance object. The factory passes an empty
Name for native allocation. It does not reuse an old Name or supply a predicted one.
Non-target objects sharing the old appearance must remain unchanged.

Preview `extensions.creo` records `reference_action`,
`reference_replacement_authorized`, complete `reference_before` and the full influence
set. Its `reference_after` has `native_id=null`,
`allocation_status=pending_native_allocation` and the source context/scope. The native
server checks complete expected-before appearance/assignments and source context again
before binding. A conflicting source/reference change must refuse, not reuse stale
confirmation or guess the new allocation.

The actual leaf result contains complete `reference_before` and `reference_after`
descriptors. The new ID must be nonempty and different from the old ID within this call.
`GetVisibleAppearance` must match the intended display properties. Exactly one complete
model-only assignment must match that visible appearance and its ID. Both visible and
assignment selection model/type identities must identify the intended source part.
The new-mode checks are `authorized_native_reference_creation_and_source_binding` and
`non_reference_non_rgb_cosmetic_properties_preserved`. Preserve mode retains
`native_reference_identity_preserved` and `non_rgb_cosmetic_properties_preserved`.

An RGB set preserves label and the existing non-RGB cosmetic properties except the
expressly replaced reference ID. Model display/common name, physical material, density,
source geometry, assembly constraints, other source colors/bindings and non-target
modified flags remain independently protected. Name remains in both complete observations;
the new mode verifies an authorized identity transition instead of excluding it from an
unchanged-state comparison. The final result uses the same complete verified observation,
bound to that Plan, Client and frozen intent. An error does not authorize replay,
rollback or automatic save.

The appearance is unsaved until an explicit `model save`. Retain `appearance` from
the original query for restore. A restore request replaces `rgb` with the complete
recorded `appearance` object. In authorized `create_and_bind` non-null restore, its
Name is historical evidence: the operation restores recorded display properties onto
a newly allocated reference, not the original ID. Existing and intended appearances
must be non-null. `"appearance": null` selects native default using the separate
default route without replacement fields; it does not reconstruct an arbitrary earlier
custom appearance. Restore always needs exact source/occurrence authorization and an
explicit save for persistence. See the complete six-field set and recorded-object
restore examples (historical material retained outside this snapshot).

After save, normal close and exact reopen, query the color and binding again before
the second edit. Native ID text alone may differ across reopen only when exact saved
file/version/SHA and model/origin correspondence are proved, including an explicitly
authorized exact-version copy mapping if paths differ. Each observation must have a
complete self-consistent visible appearance, one model-only assignment and matching
source selections. All other display properties and full protected model, geometry,
material, constraint and dependency observations still have to match. A basename,
matching RGB or ID string alone does not establish this. An internal pure comparison
helper does not save/open, hash a file or supply missing file evidence. No general
Name-exclusion rule, full-DLL qualification or automatic activation follows.

## Lifecycle qualification

G1's Java-only diagnostic recorded stronger-client assembly activation, exact existing-state
precision/unexplode, visibility, fit and complementary BACK/ISO images. It explicitly saved
ASM9, then stopped on the first whole-phone close: only the unrelated-window-identity check
failed, and no complete failed after-state was retained. Its cause is unknown. The disk
checkpoint predates that close failure; it is not full-close/reopen or new-component proof.

The new close controller retains the same complete observation on failure and stages native
window close, return-to-Creo window checks, erase and later absence checks. It keeps other
window/model protection. Do not weaken those checks or synthesize a failed observation from
a later read.

Final G3 source `0fc175297e651b14079fe93daae4873bc7d21fab` and its final EXE/JAR completed
two phone cycles in one process: speaker89 offset 3.6→3.7→3.8, each 402 checks; four real
create_and_bind colors, each 7 checks; two pairs of inspected 1600×1000 BACK/ISO images;
explicit dirty-source/owner-last save and all 11 clean; all 11 normal closes, raw-empty
inventory, exact ASM10 then ASM11 reopen with every saved origin/SHA, actual activation
from null CurrentModel and independent color/binding/engineering readback. Original
engineering tolerances were unchanged. The existing 9-move state and real unexplode also
passed native precision/display checks; raw 1 ULP API normalization remains visible.

The original uncolored five-file repeated-part holdout refused an incomplete affected-path
preview without confirmation/setter. Fresh complete authority covered both jaw occurrences;
first-source jaw green/pad orange, exact jaw41 hide/show preserving48, inspected ISO and
explicit save passed. Both physical/non-target protection and complete dirty-state readback
were retained. The holdout was not reopened. The phone's saved prototype was reopened in
place; ZIP relocation was not tested.

These are windowed Java-only diagnostics, with zero manual CAD/CUA and no DLL loaded.
They do not qualify full cold startup or native process exit. Exact hashes and raw evidence
are bound by the current handoff (private historical record), including the external
G3 final qualification record. G1's original failed after-state remains missing/unknown;
G2's public-reference failure remains stopped, without borrowing G3 success.

`session exit` is a separate dangerous command for an exact owned, full-ready, raw-empty
session; discover its actual schema. It closes no models and saves/discards nothing. Its
fixed ProEngineerEnd call, correlated native entry/normal termination evidence and held
xtop exit-code observation are distinct from HTTP acknowledgement. Java-only and old C4
components do not qualify it. See [owned startup/exit](STARTUP-NATIVE.md).

## Native model context and display

The original phone failures had a target-owned window while CurrentModel remained null.
They remain historical. The new profile uses a fixed registered maximum-priority command
for explicit activation, returns to Creo, then independently verifies current model/window
on a later toolkit tick. This is not an arbitrary macro or OS-input facility. Final G3
two-part and two phone-cycle records prove same-process switching and null-current reopen
recovery for the exact G3 EXE/JAR, without loading its DLL. C10-H1's separate full-component
probe has since passed saved reopen and actual activation, with fresh identity and independent
readback. Its full phone/lifecycle route remains pending. See
context route and evidence (historical material retained outside this snapshot).

The finite native-file InitialModel startup route retains its own qualification. It is not
a required restart workaround or proof of same-process/full-DLL behavior.

For a separately user-authorized `JavaOnlyDiagnostic` causal trial, first require fresh
process-only `context` evidence with `java_loaded_verified=true` and inspect
`java_runtime_identity`. The independent gate binds the entry class, source fingerprint
and service UUID to two OS snapshots of the Java/Creo ancestor chain, creation times,
actual executable images and AMD64 architecture. It also requires a current open handle
to the candidate JAR and its backing-file SHA-256. A retained load anchor is not accepted;
live memory pages are not hashed. Missing Java evidence requires stopping.

This gate neither supplies a DLL witness nor makes `loaded_verified` or
`native_loaded_verified` true. Doctor's native-backend/connection checks can remain
unavailable. Only after the original call is independently terminal and instance state
permits reads may that authorized causal trial attempt existing Java-only commands,
according to their actual service_ops and creation-API requirements. Do not run
DLL-dependent features or count this branch as daily full engineering acceptance.

Every operation below has the normal dry-run/confirm gate and independent readback:

1. `display activate --model phone_demo.asm` uses the deferred route when
   `model_context_activation` is available. Preview binds exact native target identity
   and discloses that the prior current-model context may be dismissed. The fixed callback
   and later independent current-model/window/type readback must finish before success.
   The new profile requires complete definitions, constraints, poses and bounds for all
   loaded assemblies. Old backends lacking the capability refuse inactive targets;
   their already-active limited no-op remains. Other display actions do not activate.
2. `display fit --model phone_demo.asm --view isometric --margin 0.1` intentionally
   retains the requested native orientation, refits it, then reduces the native zoom
   by `1 - 2 * margin`. `margin` is a fraction on each edge, from 0 through 0.4.
   `isometric` is a derived orientation: it requires the saved `FRONT`, aligns to it,
   then rotates Y by -45 degrees and X by 35.264389682754654 degrees. A saved
   `ISOMETRIC` is not required; `DEFAULT` is not an alias. No saved view is created.
3. `artifact render --model phone_demo.asm --view current --output <new.jpg>` exports
   that same fitted view. Choosing another render orientation requires another fit
   for that orientation; a fit in one projection does not qualify another projection.
4. `display component-visibility --model phone_demo.asm --component 40 --state hidden`
   hides the exact direct occurrence. `--state visible` unhides it. This is not
   suppression and does not alter source-part appearance or assembly constraints.
5. `display unexplode --model phone_demo.asm` exits exploded display, retaining the
   stored exploded-state definitions. The complete existing current-model/window context
   is required before preview and checked again in the native setter. It neither deletes
   moves nor resets constraints.

`display show` distinguishes a readable active-target screen transform from an inactive
target, for which context-dependent getters are explicitly not checked. Do not substitute
the active window's transform for an inactive target's transform.

Fit, current-context verification and unexplode are declared session display operations.
Visibility also changes the owner model's in-memory display property. A dirty owner is
unsaved; clean memory alone does not prove hidden-state saved persistence. The operation observes
actual modified flags;
explicit save, normal close, exact-file reopen and another independent query qualify the
specific persistence behavior. The native render state includes actual source appearance
readback, separately from physical material.

Refit/zoom readback proves the requested native operation. It does not by itself prove
the exact pixel margin, absence of occlusion or every expected color in an image. Decode
and visually inspect actual output, checking the entire model, border clearance and color
distribution. `artifact render` does not automatically weaken restoration checks or overwrite
an existing output to obtain a passing image.

Unexplode protection derives normal positions from the complete recorded translation moves
when the pre-operation display was exploded. It protects IDs, axes, geometry, materials and
constraints, but that derivation is not independent native normal-display evidence before
the operation. Both full observations and this limitation remain in the receipt.
For that display-to-normal transform, both raw assembly bounds are checked against
the complete protected part bounds and native display poses. The precise projection
profile covers at most ten same-unit direct parts with axis-aligned proper rigid frames;
its tolerance is unchanged. An already-normal no-op retains complete raw bounds/poses
and does not impose that projection limit on existing rigid children.

## SDK basis and prerequisites

The legal local Creo 13.4.1.0 SDK `otk.jar` and its installed documentation were checked,
and all new source compiled with JDK 25.0.3 targeting Java 17. Compilation does not qualify
running on Java 17. Appearance/display APIs use the installed Object TOOLKIT Java runtime
and its applicable license; the project does not bundle or relicense PTC components.

Official API basis:

- [Cosmetic properties](https://support.ptc.com/help/creo_toolkit/otk_java_plus/usascii/creo_toolkit/user_guide/Cosmetic_Properties.html):
  native appearance getters/setters, full cosmetic properties and null default restore.
- [WSelection](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r12/usascii/creo_toolkit/api/dita/c-wfcSelect-WSelection.html):
  `GetVisibleAppearance` and `SetVisibleAppearance` on a programmatic model selection.
- [WModelItem](https://support.ptc.com/help/creo_toolkit/otk_java_plus/r11.0/usascii/creo_toolkit/api/dita/c-wfcModelItem-WModelItem.html):
  `Hide`, `Unhide` and independent `IsHidden`.
- Installed 13.4 API method index and signatures: `WWindow.Refit`,
  `Window.Get/SetScreenTransform`, `ViewOwner.CurrentViewRotate`,
  `BaseSession.Get/SetCurrentWindow`, `Window.Activate`, `Model.Display`,
  `BaseSession.CreateModelWindow`, `Assembly.UnExplode` and `Assembly.GetIsExploded`.

These are supported native SDK calls, with no mapkeys, private reflection, OS input or
Computer Use fallback. The fixed highest-priority command and later-tick observation
recovered missing current-model context in the exact G3 Java-only scenarios above. Old
components without that capability still refuse inactive targets. A visible Creo process
exists; this is not headless. Lock-screen and minimized-window qualifications were not run.
