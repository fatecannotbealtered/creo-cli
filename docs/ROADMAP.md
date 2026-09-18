# Roadmap and acceptance boundaries

## Implemented in source

Portable machine contract, 22-command registry, bounded files/snapshots, restricted
ChangeSet validation/planning, explicit mock writes, HMAC gates, durable replay
prevention, cooperative locks, redacted audit, typed native-interface source,
offline tests, measured dispatch guard, development launcher and version tooling.
These claims concern the source and recorded offline run, not native completeness.

## P0 — establish trust before adding capabilities

Validate exact VB API bindings on an installed Creo, test unit semantics and
read-only behavior, record the disposable-part E2E. Complete exact spec vendoring,
canonical runtime integration, lint/audit and full functional-contract mapping.
Publish the source repository only through an authenticated owner workflow; keep
package release disabled until its independent gates are met.

## P1 — actual structural design closed loop

Design safe native template cloning and model open/save/reopen with a recoverable
baseline and accurate identity. Implement a constrained feature operation algebra
(e.g. template-defined sketch/extrude/hole), persistent selection references and
regeneration failure semantics. Acceptance: create a real editable bracket from a
template, change hole pitch, regenerate, save, reopen and verify actual geometry.
`model init` simulation is not a shortcut around that acceptance.

## P2 — assemblies and engineering deliverables

Assembly component placement and constraints, measured clearance/interference,
feature/parameter queries at scale, drawing creation/update, controlled exports
and artifact verification. Each depends on actual SDK support, license/version
matrix and recorded task-level tests. Keep unsupported commands undiscoverable.

## P3 — performance and distribution

Measure real COM round trips and large-model workloads. Evaluate a persistent
worker with explicit session identity, locks, cancellation and cache invalidation.
Then build/install test signed platform artifacts and the npm wrapper. Record
baseline timings before introducing caching or batching. No guessed speedup claims.

## 0.2.0 implementation update

Implemented (not real-Creo-verified): CREOSON transport, typed domain operations,
request-based workflows, partial/unknown receipts, staged exports, drawing
operations, limited assembly placement and an isolated-part save/reopen loop.
These supersede older roadmap items marked entirely unimplemented for those
areas, but do not establish product readiness or full-domain completeness.

Still substantive gaps: genuine native sketch/extrusion/hole/fillet construction,
assembly constraint solving/DOF, interference, GD&T, sheet-metal workflows,
visual verification, topology-stable identities, recovery after native crash,
complete pinned-spec conformance and actual platform/license validation.
