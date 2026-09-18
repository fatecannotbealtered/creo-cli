# ADR 0001 — constrained native surface and fail-closed replay ledger

Status: accepted for the development snapshot; revisit after live SDK evidence.

Use a Python CLI and optional out-of-process Windows VB API worker. This keeps the
portable runtime dependency-free and isolates SDK/platform loading. It trades
per-command attachment overhead for simpler lifetime/failure isolation; persistent
workers remain a measured future choice, not an assumed optimization.

Support reads and existing scalar changes before feature creation. Do not issue
RetrieveModel with an inferred path or automatically save a model whose geometry
has not been validated. Only individual-part, non-relation-driven, linear dimensions
and supported parameter types are editable. No implicit unit-system conversion.

Consume tokens atomically before writes. Upstream CLI-SPEC section 9 permits
degradation on consumed-ledger storage failure; this project intentionally takes
the stricter fail-closed choice. A storage problem must not silently enable replay
against an engineering model. This is a project policy, not an edited upstream spec.

Native restoration is not crash-atomic or whole-model undo. Report attempted-value
restoration separately from global state. Saved/reopen verification remains a
future acceptance gate and a manual test in this version.
