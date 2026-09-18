# Native workflows

A workflow is a literal, bounded plan, not a scripting language:

```json
{
  "workflow_schema": "1.0",
  "steps": [
    {"id": "inspect", "command": "dimension list", "request": {"file": "bracket.prt"}},
    {"id": "pitch", "command": "dimension set", "request": {"file": "bracket.prt", "name": "d1", "value": 45, "expected_length_units": "mm"}},
    {"id": "regen", "command": "file regenerate", "request": {"file": "bracket.prt"}},
    {"id": "save", "command": "file save", "request": {"file": "bracket.prt"}}
  ]
}
```

Use `reference` to select operations/requests. Max 32 unique step IDs, eight
explicit models. Every step has exactly `id`, `command`, `request`. No variables,
recursive workflows, raw upstream method names, loops, expressions or generated
shell code. The schema is validated before network calls. Targets must already
be loaded or be created/opened by an earlier step; forward dependencies fail.

## Preview and execution

`workflow validate` is offline syntax validation. `workflow run --dry-run` reads
model observations and input hashes, validates what is currently knowable, and
returns one token bound to the entire plan. Checks depending on earlier mutations
are explicitly deferred. Preview does not open files, create templates, save,
regenerate, select geometry, export or predict a CAD result. Local confirmation
metadata and a temporary cooperative lock are permitted side effects.

Confirm re-reads initial observations and compares the token scope, durably consumes
the token, then processes steps sequentially using one transport session. Each
write performs just-in-time preconditions and selected readback checks. Native
request count is returned, so overhead is inspectable rather than hidden. There
is one total timeout budget, not a fresh full timeout per sub-request.

## Results, checkpoints and recovery

Each completed step has a hash-verified result file under the private state
folder, retrieved using `workflow result --operation-id ID --step-id STEP`.
History contains receipt summaries and hashes, not all full model data.
Results are redacted, but still potentially proprietary. Do not publish them.

Status vocabulary: `running`, `completed`, `failed_before_write`, `unknown`,
`partial`, `verification_failed`, `human_acknowledged`. The middle unresolved
states block new native writes. `completed` means all requested steps passed
their declared verification policies; a policy can be acknowledgement-only.
It does not mean every geometry check, design requirement or real deployment was
validated. `rollback_performed` remains false. Last accepted subphase and
completed steps survive errors. Roundtrip also records its close/erase/open phase.

Do not replay, auto-resume, run compensating edits, clear receipts or manually
remove a live lock merely to proceed. Have a human inspect the application, wait
for the actual server to become idle, and decide what state should be kept.
Reconciliation records that assertion only and keeps the original failure status
in the record; it does not implement a retry. Obtain a new preview for new work.

## Bundled recipes

`workflow-bracket.json`: read length dimensions, change one explicit dimension,
regenerate, save, export STEP. Requires an already loaded disposable part and
an existing `exports` directory. It is not an extrusion/feature-generation recipe.

`workflow-drawing.json`: create a drawing from a real local template, general
view, projected view, regenerate and export PDF. It does not author dimensions,
tolerances, title blocks or a complete manufacturing drawing automatically.

`workflow-roundtrip.json`: inspect and perform the isolated-part save/reopen
check. No other models may be loaded. This tests selected observable persistence,
not complete geometry identity.

All request examples describe intended real upstream operations, but this
repository contains **no valid native CAD files or templates**. The offline test
server writes clearly marked fixture bytes; those are never deliverable CAD files.

Timeout scope: the shared deadline bounds upstream HTTP waits and prevents starting a further request after expiry. Local hashing, filesystem calls and SQLite lock waits are not hard-preemptible by this timer; their separate size/lock bounds still apply.
