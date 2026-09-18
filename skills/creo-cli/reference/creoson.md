# CREOSON operating notes

Use live `reference` for current command names, request types and schema; do not
copy a stale API list. CREOSON is a local execution dependency, not a CAD kernel
embedded in the CLI. See `docs/CREOSON.md` for setup and `docs/WORKFLOWS.md` for
manifest lifecycle.

Work on explicit disposable copies with exclusive session ownership. A prepared
session does not establish engineering validation. All new operation outputs keep
`live_verified:false` until genuine release evidence exists.

Observed properties, upstream acknowledgements and selected readback checks are
different evidence. Preserve those distinctions when explaining a result.
For a failed write, inspect receipt and actual application state. Human
reconciliation cannot be inferred from a successful status query or synthesized
from an old conversation; it requires an actual check of the current session.
