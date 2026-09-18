# Native acceptance plan — NOT an executed run

No live Creo E2E evidence is recorded in this version. The offline test record
contains native substitutes only. Do not fill a result cell without a real run.

## Disposable-part first acceptance

Have a human preserve a baseline copy, open a simple non-production part with a
known linear hole-pitch dimension, and ensure other automation/GUI edits are idle.
Record exact Creo build, Windows version, Python architecture, API components,
license conditions and principal unit system. Do not record secrets.

First verify read-only context/doctor, session identity, model list and snapshot.
Cross-check parameter types, dimension IDs/symbols/types, relation-driven flags,
feature states and relation text against the UI. Confirm that read commands did
not set values, save or close anything.

Have the human enable the two native write gates before the dry-run. Plan a single
linear dimension modification with expected old value and exact reported unit
system. Confirm the preview performs no setter or regeneration. Obtain approval,
confirm once, and compare the CLI read-back against the UI and real geometry.
Verify successful regeneration is not merely requested-value equality.

Exercise malformed, stale, expired and replayed tokens on a disposable baseline;
none should modify the part. Test units mismatch, relation-driven targets,
nonlinear dimensions, read-only policy and unavailable environment. Test timeout
only in a controlled fixture where the user can recover unknown live state.

Native Save is NOT implemented. A human may manually save, close and reopen a
verified disposable part and compare a new snapshot. Record this as a **manual
persistence step**, not evidence that a CLI save/reopen command exists.

| Acceptance item | Result | Evidence |
|---|---|---|
| Real COM connection/read compatibility | Not run | Missing |
| Unit-system and dimension semantics | Not run | Missing |
| Preview no native mutation | Not run | Missing |
| Confirm / regenerate / geometric check | Not run | Missing |
| Failure recovery and uncertain state | Not run | Missing |
| Manual save/reopen persistence | Not run | Missing |

Preserve failure observations as well as successes. An editable scalar result is
not proof of structural adequacy, manufacturability, drawing correctness or full
model rollback. Those require separate acceptance work.

## CREOSON offline protocol evidence (0.2.0)

`python scripts/record_creoson_demo.py --output docs/evidence/creoson-offline-demo.json`
starts a loopback HTTP **substitute** and launches the real CLI as separate
processes. It demonstrates connection, a guarded inspect/change/regenerate/
save-reopen/export workflow, a drawing-template/views/PDF workflow, and receipt
retrieval. The substitute writes deliberately invalid fixture CAD/PDF/image bytes
with plausible headers only. These are control-path evidence, never real exports.

The script records actual exit codes, stdout envelopes, timing, request counts,
source fingerprint and checks. It does not mark any real integration verified.

## First genuine CREOSON acceptance run

A human prepares compatible licensed Creo + CREOSON, one disposable parameterized
part, and an isolated working directory. Run connection/status, units/parameters/
dimensions/features reads. Verify actual type and units before previewing one
small dimension change. Confirm once, regenerate, and inspect Creo visually.
Use `file roundtrip` while that part is the only loaded model; verify reopened
values both through the CLI and in the GUI. Keep the baseline and operation receipt.

Then separately prepare a disposable assembly and matching coordinate systems;
validate one component placement and its actual constraints. Separately prepare a
real drawing template and verify views/sheets/export in Creo and a viewer. Record
software/build/license versions, actual stdout, checksums and unchecked scopes.
Until this has actually happened, do not change `live_verified:false` or the
release readiness. If a write times out, do not keep issuing operations to a busy
server; follow the receipt/inspection procedure instead.
