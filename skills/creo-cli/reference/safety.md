# Write safety

HMAC authorization covers command, backend, target, ChangeSet, observed revision,
account and local permission. Native observations also include session identity.
A token is marked consumed before mutation. Storage failure refuses the write.

The per-resource lock serializes cooperating CLI callers only. It does not lock
the GUI, relations, external automation or automatic saving. Never remove a stale
lock until a human has inspected its recorded owner process.

A native operation can fail after setting one value. Best-effort value restoration
does not establish whole-model restoration. `whole_model_restored:false` and
`state_unknown:true` are deliberate, even when requested values were restored.
`persisted:false` means this adapter did not call Save, not that disk state was
independently verified unchanged.

## CREOSON additions in 0.2.0

The legacy VB API route remains unsaved by default. Separate CREOSON commands can
save, export, back up, and roundtrip an isolated part; do not apply the legacy
"this tool never saves" statement to these commands. They require explicit
workspace policy and confirmation. Whole-model rollback is still not implemented.

`E_OUTCOME_UNKNOWN`, a partial receipt, or a failed postcondition stops automatic
native work. Native session locks serialize only CLI callers. Only a human who
has inspected the application and confirmed server idleness may acknowledge an
unresolved receipt. No receipt deletion, automatic acknowledgement or old-token
replay is a safe recovery shortcut.
