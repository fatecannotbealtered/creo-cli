# Evidence index

Evidence is version- and source-fingerprint-specific. A green historical run is
not validation of later code. Times in JSON are the execution environment's UTC
clock, not a manually asserted product-release date.

## 0.2.0

- `offline-tests-0.2.0.json`: full command-level suite and actual dispatch guard;
  no real Creo, no full functional-contract certification.
- `creoson-offline-demo.json`: real CLI subprocesses and loopback HTTP against a
  stateful substitute. All CAD/PDF/image bytes in the fixture are deliberately
  invalid demonstration bytes, not user deliverables or engineering evidence.
- `upstream-interface-sources.json`: exact consulted source blob identities.
- `development-checks-0.2.0.json`: local compile/version/helper checks and
  intentionally failing spec/release gates. No lint/audit/CI claim.

The external delivery manifest additionally records Git commit, artifact SHA-256,
clean bundle-clone test results, and local-wheel installation checks. Building a
local development wheel does not override release guards or publish a package.

## Historical 0.1.0 records

`offline-tests.json`, `offline-demo.json`, `benchmark.json` (when present),
`publish-preflight.json`, `release-gate.json`, `spec-bootstrap-attempt.json` and
`source-fingerprint.json` retain their original scope/timestamps. They are not
relabelled as 0.2.0 evidence.

## Missing by design

No `live-creo.json` or `full-conformance.json` is manufactured. The project stays
`unpublishable` until reviewed, current evidence exists and normative assets and
release engineering are integrated.
