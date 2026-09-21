<h1 align="center">creo-cli</h1>
<p align="center"><strong>Agent-native Creo Parametric operations · JSON-first · guarded workflows · explicit verification</strong></p>
<p align="center"><a href="README.md">English</a> · <a href="README_zh.md">中文</a></p>
<p align="center">Explicit backends · HMAC-confirmed writes · Offline protocol tests · MIT</p>

**Source development build — unpublishable; no real Creo run yet.** The 1.0.0
version line matches the baseline the other CAD tools in this fleet start from; it
is not a stability claim, and the gates in `docs/SPEC_STATUS.md` still apply. This
build ships a CREOSON backend written against published interfaces, not a
replacement CAD kernel. It complements the experimental PTC VB API adapter and the explicitly
simulated `.creo.json` backend. Implemented requests and passing offline tests
are not a claim of compatibility with your installation or of engineering validity.

## Agent Install

From this checkout, Python 3.11+ runs the CLI without runtime third-party dependencies:

```bash
python -m creo_cli context --compact
python -m creo_cli doctor --compact
python -m creo_cli reference --command "dimension set" --compact
# Optional local executable:
python -m pip install -e .
```

**Before installing Creo, read [installation prerequisites](docs/CREO_SETUP.md).** The
API this CLI runs on is an optional component chosen in the Creo installer -- *Creo
Object TOOLKIT Java*, under API Toolkits. It is free with a Creo seat, and there is no
component called "J-Link" to look for; J-Link ships inside it. Missing it cannot be
fixed without re-running the installer. `creo-cli doctor` reports it as
`creo_api_toolkit`.

Read [the bundled Skill](skills/creo-cli/SKILL.md). No npm package or binary is
claimed published; `@fateforge/creo-cli` remains private. The Node source launcher
is a development convenience. For the new backend, install/configure an external
[CREOSON](https://github.com/SimplifiedLogic/creoson) service and licensed Creo on
the same computer; neither is bundled or auto-started. See [setup](docs/CREOSON.md).
The independent Windows VB API route still uses `pip install -e ".[native]"`.

## What It Does

Controls named models, typed parameters and length dimensions; handles feature
states, material assignment, coordinate-system/fixed assembly, named orientations,
drawing templates/views, and export artifacts. Workflows combine operations under
one preview/confirmation with persisted results and honest partial-failure states.
Risk tier **T1**: confirmed operations may alter a disposable live model, assembly,
drawing, or local output. Read-only policy is the default. Independent of PTC.

## Capabilities

| Area | Command groups | Scope |
|---|---|---|
| Discovery and observations | `reference`, `context`, `doctor`, `changelog`, `system capabilities`; `workspace`, `snapshot` | Local preflight never connects to Creo; native filenames are not parsed as geometry |
| Existing adapter | `session`, `model`, `change` | Original VB API or explicit JSON mock; no fallback |
| CREOSON connection | `creoson connect`, `creoson status` | Existing loopback service; protected session cache; version is declared, not detected |
| Session and environment | `creo pwd|cd|list-files|list-dirs|mkdir|rmdir|get-config|set-config|std-color|set-std-color`, `server pwd` | Directories stay workspace-contained; `creo cd` is how Creo is pointed at the disposable workspace |
| Model lifecycle | `file list|active|info|exists|is-active|open-errors|open|display|refresh|repaint|regenerate|close-window|save|backup|rename|erase|roundtrip` | Explicit working-copy models; status reads do not require the model to be loaded |
| Units, materials and relations | `file units|mass-units-only|unit-system|accuracy|set-length-units|set-mass-units|set-unit-system|create-unit-system`, `material list|current|assign`, `file load-material|delete-material|materials-wildcard|current-material-wildcard`, `file relations|postregen-relations|set-relations|set-postregen-relations` | Unit setters require an explicit `convert` and are read back; relations are never evaluated by the CLI |
| Design state | `parameter list|exists|set|copy|delete|set-designated`, `dimension list|list-basic|set|copy|set-text|show`, `feature list|params|param-exists|group-features|pattern-features|suppress|resume|rename|delete|set-param|delete-param`, `note list|get|exists|set|copy|delete`, `layer list|exists|show|delete` | Typed values, explicit units, exact names, no wildcard writes |
| Geometry reads | `geometry bound-box|surfaces|edges`, `file simp-reps|has-instances` | Identities, areas and extents; not a tessellation or a BREP export |
| Family tables | `familytable list|exists|header|row|cell|parents|tree|create-instance|add-instance|set-cell|replace|delete-instance|delete` | One exact instance per call; `tree` never erases; `set-cell` checks the column's declared type |
| Assemblies and orientations | `assembly tree|transform|assemble`, `view list|list-exploded|activate|save` | One explicit csys/fixed component; no arbitrary constraint solver |
| Drawings | `drawing create|add-model|add-sheet|create-view|project-view|regenerate|models|sheets|views|current-sheet|current-model|sheet-size|sheet-scale|sheet-format|list-views|view-location|view-scale|view-sheet|view-bound-box|list-symbols|symbol-loaded|select-sheet|regenerate-sheet|scale-sheet|set-sheet-format|delete-sheet|set-current-model|delete-models|rename-view|move-view|scale-view|delete-view|load-symbol|place-symbol|delete-symbol-definition|delete-symbol-instance` | Real external template required; explicit sheets, orientation and drawing units; a named target is required where the upstream would accept "all" |
| Delivery and exchange | `export step|iges|dxf|pdf|3dpdf|image|plot|program`, `import file|program` | Named exports stage in isolation, validate bytes/header, then publish atomically without clobbering; `plot`/`program` let Creo name the file and are verified against the location it reports |
| Repeatable tasks | `workflow validate|run|status|history|result|reconcile` | Up to 32 allowlisted steps and eight model targets; no eval, mapkeys, or arbitrary RPC |

There are **183 leaf commands**, including **150 CREOSON domain operations** -- every
function the CREOSON 3.0.2 release publishes except the twenty-five left out on
purpose. `contract/creoson-interface.json` is derived from the release's own
specifications, and a test holds the catalog to it: no invented field, no missed
required field, no promised response key that does not exist, and no published
function that is neither exposed nor named with a reason.

What is left out, and why: Windchill (PLM is not this tool's job); the connection
lifecycle beyond `creoson connect`/`creoson status`, so nothing here starts, stops or
kills Creo; `mapkey` and the `user_select` family, which are the recorded-UI and
GUI-pick escape hatches this catalog exists to avoid; `creo delete_files`, which
deletes by pattern outside the workspace guarantees; and `file erase_not_displayed`,
which takes no target at all.

The registry gives each operation its request schema, example, safe wire defaults,
source provenance and nested output schema. An operation is implemented but **not
live-verified**. No from-scratch part/sketch/extrude/hole/fillet engine, arbitrary
assembly constraints, interference analysis, sheet-metal unfolding, GD&T authoring,
FEA or self-update is implemented.

## Agent Workflow

Have a human configure a **disposable local workspace**, write policy and native
opt-in. The agent may not set permissions itself. In PowerShell:

```powershell
$env:CREO_CLI_WORKSPACE = "C:\CreoCliWork"
$env:CREO_CLI_PERMISSION = "write"
$env:CREO_CLI_EXPERIMENTAL_NATIVE_WRITES = "1"
# Default endpoint is http://127.0.0.1:9056/creoson.
python -m creo_cli creoson connect --creo-major 10 --dry-run --compact
# Inspect preview, confirm once with its data.confirm_token:
python -m creo_cli creoson connect --creo-major 10 --confirm <confirm_token> --compact
```

The connection does not launch Creo and `10` is an example **human declaration**,
not an automatically detected version. Use the actual installed version.

New operations accept strict JSON request files; exact fields come from `reference`:

```bash
python -m creo_cli dimension list --request examples/requests/dimension-list.json --compact
python -m creo_cli dimension set --request examples/requests/dimension-set.json --dry-run --compact
python -m creo_cli dimension set --request examples/requests/dimension-set.json --confirm <confirm_token> --compact

python -m creo_cli workflow validate --input examples/workflow-bracket.json --compact
python -m creo_cli workflow run --input examples/workflow-bracket.json --dry-run --compact
python -m creo_cli workflow run --input examples/workflow-bracket.json --confirm <confirm_token> --compact
python -m creo_cli workflow status --operation-id <operation_id> --compact
python -m creo_cli workflow result --operation-id <operation_id> --step-id inspect --compact
```

Adapt example names to real disposable files. **Examples do not include real CAD
models, templates or a fake geometry engine.** A preview binds the entire request
plan, session identity, workspace, selected model observations and input hashes;
it does not simulate geometry. Preconditions depending on an earlier workflow
step are labeled deferred and checked immediately before execution. Native writes
are never automatically retried, even after a lost reply.

`file roundtrip` saves, closes the window, erases only the named part from memory,
reopens and compares parameters, dimensions, feature data, relations, units,
materials and view names. It refuses a session containing any other model. This
can test observed persistence but cannot prove identical BREP, fit or strength.
`file close-window` alone does not erase or save a model. Legacy VB API scalar
writes remain unsaved; CREOSON save/export/roundtrip are separate explicit writes.

## Machine Contract

JSON by default, exactly one stdout envelope (`ok`, `schema_version`, `data` or
`error`, `meta.duration_ms`); diagnostics use stderr. `--help` is explicit human
text. `text`/`raw` unwrap the payload. `--json` is a compatibility alias.

Dry-run succeeds with `data.preview`, `data.confirm_token`, `data.expires_at`.
No token means `E_CONFIRMATION_REQUIRED` (exit 5); stale/replayed tokens return
`E_CONFLICT` (6). **`E_OUTCOME_UNKNOWN` (6, not retryable)** means the server may
still be running or a write result cannot be established. `E_VERIFY_FAILED` (1,
not retryable) means a selected postcondition failed. Neither implies rollback.
Receipts in unresolved states block further native writes, including after a
process crash. `workflow reconcile` records **a human assertion**, not proof of
server idleness, rollback, geometry correctness or permission to replay the old token.

`--fields` projects read results while retaining security/provenance/limitation
metadata. CREOSON list paging is in `data.result`; source results are collected
before sorting and paging, not server-side pagination. Separate calls are not
snapshot isolated. Large step results live in separate hash-verified local files
and are retrieved using `workflow result`, not inlined into history.

Result verification distinguishes **observation**, **upstream acknowledgement
only**, and **selected postconditions verified**. None means the real integration
has been tested. Exports check signatures, not renderability or geometric fidelity.
Native observation hashes cover selected metadata, not every geometry/kernel
state or GUI change. Concurrent GUI/third-party edits are not prevented by CLI locks.

## Configuration

| Variable | Purpose |
|---|---|
| `CREO_CLI_CONFIG_DIR` | Private state directory; default `~/.creo-cli` |
| `CREO_CLI_PERMISSION` | Human policy: `read` (default) or `write` |
| `CREO_CLI_EXPERIMENTAL_NATIVE_WRITES` | Separate human opt-in, exactly `1` |
| `CREO_CLI_WORKSPACE` | Existing disposable workspace, required for CREOSON writes |
| `CREO_CLI_CREOSON_URL` | Loopback HTTP `/creoson` endpoint; no remote hosts, credentials, redirects or proxy use |
| `CREO_CLI_CREOSON_SESSION` | Optional private session via environment; reads only for operations requiring version configuration |
| `CREO_CLI_CREO_MAJOR` | Optional environment session version annotation; does not configure the server |
| `PRO_COMM_MSG_EXE` | Installed communication executable for the separate VB API route |
| `CREO_CLI_PYTHON` | Interpreter used by the optional Node source launcher |

Session IDs are kept out of ordinary output, receipts and errors. A session token
is not a license. No new account login is introduced. Timeouts share one command
budget (0.1–300 seconds), and do not prove the external application stopped.
Workspace symlinks/junctions, traversal, network paths and export overwrites are
refused. Cross-process locks are cooperative, never a whole-application lock.

## Project Structure

```text
creo_cli/          registry, safety, observations, VB API and CREOSON boundaries
  creoson_*.py    typed allowlist, HTTP transport, workflow engine, state, schemas
examples/         request files and workflows; no real native CAD templates
skills/           operating guidance, uncertainty handling, safety checkpoints
tests/            mock/VB API substitutes + stateful loopback HTTP substitute
scripts/          tests, evidence, source-version tooling, guarded repository publication
docs/             setup, protocol sources, compatibility, workflows and local evidence
contract/.agent/  bootstrap mapping and fixed spec target; exact vendoring pending
```

## Development

```bash
python scripts/test.py --evidence docs/evidence/offline-tests-1.0.0.json
python scripts/record_creoson_demo.py --output docs/evidence/creoson-offline-demo.json
python scripts/version.py --check
python -m compileall -q creo_cli scripts tests
python scripts/bootstrap_spec.py --check
python scripts/release_gate.py
```

The last two commands intentionally fail while exact spec assets, complete FCC
certification and real Creo evidence are missing. Passing simulated contract tests
and dispatch coverage never waive those gates. No GitHub CI run, Windows/Creo test,
release signing, binary build, dependency audit or package publication is claimed.
`package.json` is the version authority; update the root changelog, run
`python scripts/version.py --sync`, then `--check`. Do not edit runtime changelog
or Skill version copies independently.

## Links

[Agent entry](AGENTS.md) · [Skill](skills/creo-cli/SKILL.md) · [Security](SECURITY.md) ·
[CREOSON setup](docs/CREOSON.md) · [Workflows](docs/WORKFLOWS.md) ·
[Sources](docs/UPSTREAM_SOURCES.md) · [Compatibility](docs/COMPATIBILITY.md) ·
[VB API](docs/NATIVE_ADAPTER.md) · [Architecture](docs/ARCHITECTURE.md) ·
[E2E](docs/E2E.md) · [Spec status](docs/SPEC_STATUS.md) · [Changelog](CHANGELOG.md) ·
[Notice](NOTICE.md) · [License](LICENSE) · [中文交接](docs/HANDOFF_zh.md)

Timeout scope: the shared deadline bounds upstream HTTP waits and prevents starting a further request after expiry. Local hashing, filesystem calls and SQLite lock waits are not hard-preemptible by this timer; their separate size/lock bounds still apply.

### Upstream interaction caveat

`drawing create` can encounter an upstream modal error dialog; its `reference`
and preview expose `interaction_risks`. The CLI deadline does not cancel the
native operation or establish that the session is idle. After a timeout, inspect
Creo before the explicit reconciliation flow. Source details are recorded in
[UPSTREAM_SOURCES.md](docs/UPSTREAM_SOURCES.md).
