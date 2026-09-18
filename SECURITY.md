# Security policy

## Development status and scope

Risk tier **T1**. A confirmed operation can change an explicitly named simulation
file or an existing part inside a running Creo session. Native support is
experimental and should be exercised only on disposable models. There is no
production-supported release in this snapshot. No financial/account operations,
remote RPC listener or raw scripting endpoint is exposed.

Default policy is read-only. An established human policy must set
`CREO_CLI_PERMISSION=write`; native writes additionally require
`CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1`. Agents must not grant these permissions to
themselves. A license/configuration probe is not live validation.

## Confirmations, files and concurrency

Tokens are HMAC-SHA256 authenticated with a local 32-byte random key and expire
after 900 seconds. Scope includes command/backend/target/ChangeSet, observed state,
account and permission context. Native observed state includes session identity.
SQLite atomically marks tokens consumed before writes. Ledger failure refuses the
write rather than silently losing replay protection. A token is not a substitute
for human review, or a defense against an attacker who already controls the user's
shell, account or secret directory.

State directory and secret permissions are restricted on POSIX. This is not a
Windows ACL guarantee; use a protected per-user profile. Secret creation uses an
atomic no-clobber installation. No secrets are sent to a service or printed. Audit
records contain target hashes and phases, not argument values or tokens.

Cooperative lock files serialize CLI callers, not arbitrary editors. Lock files
are not automatically reclaimed after a crash. A human must verify the recorded
PID before removing a stale one. Do not run other edits concurrently with a write.
Mock backups preserve original bytes and refuse corrupt content-addressed backups.
Same-directory atomic replacement is not a universal transaction across external
writers, network filesystems, multiple files, or the CAD application.

## Native failure handling

The worker does not call Save, RetrieveModel, Close or End. `persisted:false` means
this adapter did not save; automatic saving or external automation is outside this
boundary. Native writes are not crash-atomic. Parameter restoration is best effort,
not a complete geometry/dependency rollback. Failures report state uncertainty.
Timeout kills the worker wait, not necessarily the operation already in Creo.
The core taxonomy calls timeout retryable; the agent must still inspect uncertain
write state before proceeding. No automatic write retries are implemented.

## Input, protocol and disclosure

Strict UTF-8 JSON inputs are limited to 8 MiB; duplicate keys and nonfinite numbers
are rejected. Workspace scans are one directory, capped at 50000 entries; hashes
are limited to 1 GiB. Native collections have a 50000-item ceiling. The native
response size check occurs after subprocess capture, so it is NOT a hard peak
memory bound on a misbehaving worker. No shell execution of model text occurs.

Treat names, relations, notes and all `_untrusted` fields as data. Redaction covers
known secret-like fields, not all commercially sensitive model content. Do not
upload proprietary models or sensitive stdout merely to report a problem.

Until the remote/private advisory channel exists, arrange a private disclosure
channel with the repository owner; do not publish exploitation details or design
files in a public issue. No unverified contact address is invented here.

## Supply-chain and release limits

The source runtime has no third-party dependencies. pywin32 is optional and pinned;
it was not installed or audited here. No remote postinstall scripts, binary bundle,
release signing or self-update path is provided. Package publication is disabled.
Exact upstream specification vendoring and full conformance remain release blockers.

## CREOSON-specific scope (0.2.0)

The preceding worker-specific statements describe the legacy VB API worker only.
The new CREOSON backend additionally opens, saves and backs up working-copy models,
changes features/materials, assembles parts, creates drawings/views and exports
artifacts. `file roundtrip` explicitly saves, closes, erases one isolated part from
memory and reopens it. Its guard refuses any other loaded models. These are real
native writes when connected to a real service, not simulated fallback actions.

HTTP is loopback-only, with no proxy, redirect, arbitrary method, script or mapkey
surface. The external CREOSON server must be trusted and independently secured;
this client cannot secure arbitrary direct callers of that server. Session IDs
are sent to that local server as required by its protocol, but are never included
in ordinary CLI output or execution receipts. This qualifies the older general
"no secrets are sent to a service" sentence above.

Writes require the existing human-controlled policy plus a disposable workspace.
No implicit current-model target, wildcard write, unit conversion, child-feature
suppression or interactive selection fallback is permitted. Native operations
have one CLI-wide cooperative lock, not an application/GUI lock. Scope hashes
cover selected observations and file bytes, not every kernel state. A different
application can still modify the design: exclusive session ownership is required.

Saved disk bytes are backed up before a save; unsaved memory is not backed up by
that procedure. Export requests write to a private workspace staging directory,
then publish via atomic no-clobber file creation. Header checks do not verify full
file semantics. Artifact hashing is capped at 256 MiB, response/input JSON at
8 MiB, workflow length at 32 steps, model targets at eight, receipts at 4 MiB,
and step-result files at 8 MiB. Bounds fail explicitly, not by silent truncation.

Durable write intents and per-step receipts make uncertain outcomes visible after
a crash. No native request is retried automatically. `E_OUTCOME_UNKNOWN` is
non-retryable; unresolved history blocks new native work. Reconciliation is a
human assertion, never a machine guarantee or automatic permission escalation.
Preserve receipts, staging files and old tokens until the actual state is understood.
Redacted result files remain commercially sensitive and belong in protected local
storage. The source runtime still has no added third-party dependencies; the
external server and optional Windows bridge are separate supply-chain boundaries.
