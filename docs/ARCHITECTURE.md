# Architecture

## Boundaries

`cli.py` owns parsing, global flags, error conversion and the single stdout
boundary. `registry.py` is the common source for parser and machine reference.
Output schemas include typed rows; core.py implements the deliberately limited
schema-validation subset used here. Errors and input limits are centralized.

`service.py` orchestrates use cases without importing pywin32. Filesystem commands
report metadata, not native CAD interpretations. `models.py` validates portable
observations and a small operation algebra: parameter.set and dimension.set.
A plan is computed against observed values, with explicit units and preconditions.
It does not simulate geometry or execute relation text.

`safety.py` implements local policy, authenticated tokens, atomic consumption,
cooperative resource locking and audit phases. `Mock` persists only explicitly
labeled `.creo.json` fixtures. An entire changed snapshot is staged and read back.
Backup validation occurs before replacement.

`native.py` contains both a parent subprocess boundary and a worker. The worker
loads the optional COM binding, connects to an existing session and issues only
allowlisted actions. The parent validates a whole JSON response, exit code,
retryability and size. Noise is a protocol failure, not ignored by searching for
a conveniently parseable first line.

The worker validates write authorization itself. Scope includes a digest of the
observed model and session identity. Native edits require modifiability without UI,
reject relation-driven/unsupported dimension types, regenerate and check requested
values plus newly failed features. No automatic Save occurs. Failed setters are
recorded as attempted before invocation because an API may mutate then throw.
Restoration checks requested values only; whole-model state remains uncertain.

## Performance

Portable discovery has no network or native connection. A scoped reference returns
only one command and its schema. Filtering precedes pagination, and projection
reduces output while retaining security/limitation metadata. File scans and inputs
have explicit ceilings. Native SDK collection limits bound item counts, not the
cost of every COM property call.

The current native worker is per invocation and reattaches to a running Creo;
it does not start Creo on each command. It is NOT a persistent session daemon.
Real COM latency, cache invalidation, large-assembly performance and cancellation
remain unmeasured. A future persistent worker should not be adopted without
identity, serialization, timeout and stale-state tests.

## Deliberate non-goals

This version does not reconstruct BREP, create features, infer drawing standards,
compute structural strength, handle PDM transactions, invent atomic native undo,
or present simulation objects as production geometry. Explicit unsupported domains
live in capabilities/roadmap rather than callable placeholders.

## 0.2.0: independent CREOSON operation route

`creoson_catalog.py` defines an allowlisted operation, exact request schema, safe
wire defaults, source provenance and verification policy. `creoson_schemas.py`
defines nested return types; the public registry links both to parser/dispatch.
`creoson_transport.py` uses stdlib HTTP to the already-running loopback service.
`creoson_engine.py` implements observations, scoped previews, JIT checks, staged
exports, selected readback, isolated-part persistence and sequential workflows.
`creoson_state.py` owns workspace containment and durable run/result records.

Legacy VB API and JSON fixtures are independent, never fallback routes. Only the
new explicit CREOSON commands save/export/open; old worker limits remain scoped
to that worker. No private native database rewriting is introduced.

One session/HTTP connection is reused per workflow. This does not mean one
upstream call: initial scope and per-step selected metadata are re-read to guard
state. Returned request counts make this overhead visible. The current design
favors conservative checks over minimum RPC count; no native speedup is claimed.

Writes use HMAC plus durable single-consumption, a cooperative session-wide lock,
and an operation journal. A model observation hash is not a kernel revision ID.
No app-wide lock, atomic multi-step transaction or complete rollback is available.
Uncertain state remains a first-class terminal result with a blocking receipt.
