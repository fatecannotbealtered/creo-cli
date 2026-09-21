# CREOSON adapter setup and boundaries

## Contents

1. Environment
2. Connection and policy
3. Request boundary
4. Model operations
5. Workspaces and artifacts
6. Uncertain results

## Environment

Creo must have been installed with the **Creo Object TOOLKIT Java** component
selected under API Toolkits; that is what ships `pfcasync.jar`, which CREOSON loads at
startup. Without it CREOSON aborts with `NoClassDefFoundError: com/ptc/cipjava/jxthrowable`
before serving anything. There is no separate "J-Link" component to select -- see
[installation prerequisites](CREO_SETUP.md).

Run this CLI, CREOSON and licensed Creo on the same host. The integration is
implemented against CREOSON 3.0.2-oriented published interfaces and source snapshots
listed in [UPSTREAM_SOURCES.md](UPSTREAM_SOURCES.md); **no real installation has
been exercised for this release**. Use the actual CREOSON setup instructions and
matching PTC installation. This project does not distribute a license, J-Link,
Java runtime, CREOSON server or vendor native libraries.

The Python CLI transport uses only the standard library. It sends JSON over a
persistent HTTP connection, with a total command deadline, byte bounds, no proxy,
no redirects and no automatic retries. It accepts only loopback addresses and the
`/creoson` path. A loopback server is still a trusted local execution dependency,
not an authentication mechanism. Never expose CREOSON through a public proxy.

## Connection and policy

`creoson status` checks an already available service without starting Creo.
`creoson connect` performs a confirmed connection and configures the declared Creo
major via `creo.set_creo_version`. The declaration is **not version detection**.
Store the session in a protected per-user `CREO_CLI_CONFIG_DIR`; the session ID is
not exposed in ordinary JSON or audit receipts. Disconnect/kill/start operations
are intentionally absent. Reconnecting replaces the cached session, not a license.

Read-only model commands do not need a workspace or native-write opt-in.
Connection requires local write permission because it persists session state.
Native content/UI/disk writes require both `CREO_CLI_PERMISSION=write` and
`CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1`, set by a human, plus an existing disposable
`CREO_CLI_WORKSPACE`. Set Creo's working directory to that workspace before writes.
The CLI checks the directory but does not silently change it.

For version-sensitive writes use a session established with `creoson connect`.
The optional environment session override is for controlled integration/read use;
`CREO_CLI_CREO_MAJOR` only annotates it and does not prove the server is configured.

## Request boundary

No generic `call`, `eval`, `script`, `mapkey` or user-selection endpoint exists.
Each command uses a strict request schema and known safe wire defaults. Model
names are explicit ASCII basenames with `.prt`, `.asm`, `.drw` as appropriate.
Wildcards and default-active-model mutations are refused. Current naming limits
are deliberately narrow, not a claim about everything Creo supports.

`reference --command "assembly assemble"` returns both the public request schema
and the upstream mapping. Sources contain known field names, not permission to
import unsafe defaults. A full `reference` response is intentionally larger;
scoping it is the normal agent path. Lists are bounded by the 8 MiB response cap,
then sorted and paginated locally. Relation lines retain their order.

## Model operations

Scalar edits check explicit types, relation text and length units; any mention of
the edited identifier in model or post-regeneration relations conservatively
blocks the edit. This is not a complete Creo relation-language parser.
Only linear/radial/diameter model dimensions are writable here; angular, drawing
or encoded dimensions are refused. There is no silent unit conversion.

Feature suppression explicitly disables clipping and child suppression. Resume
explicitly disables children. Feature name changes preserve and verify the feature
ID; other observed feature records must not change. This is not topology proof.
Material assignment chooses an already loaded material. Mass-property output
includes actual returned length/mass units; no density override is sent.

Assembly accepts exactly one coordinate-system constraint with named active
references, or one fixed placement with explicit transform. The adapter reads
back the returned component feature ID and active status. General constraint
solution, orientation accuracy, free motion and interference remain unchecked.

Drawings require an actual template under the workspace. New drawings and view
names must not already exist. Model links, sheet counts and view-sheet/model
identity are checked, not full drawing composition or dimension completeness.
The released upstream creation code enables a modal error dialog; `drawing create`
reports this in `interaction_risks`. A deadline is not native cancellation or
proof of a headless workflow. Inspect Creo and the blocking receipt after a timeout.
Template lookup from workspace paths remains a live compatibility test.

`file roundtrip` is a guarded composition: save → close_window → erase only the
named part (`erase_children:false`) → open → compare selected observed sections.
It requires that this part is the only loaded model. A disk backup is made before
save. No production assembly or arbitrary dependent-model unload is attempted.

## Workspaces and artifacts

Writes reject paths outside the configured workspace, traversal, network paths,
symlinks and junctions. All callers of this CLI share a native-session lock even
if different loopback ports point to the same Creo. Other programs/GUI users are
not locked: exclusive ownership of the disposable Creo session is required.

Save preserves prior disk versions under `.creo-cli-backups/<run>-<step>/` before
asking Creo to save. Unsaved memory is not in those byte backups. A save with no
new/changed file evidence is conservatively rejected by verification, even if
Creo may have considered it a legitimate no-op.

Exports use `.creo-cli-staging/<run>-<step>/` as the upstream destination. The CLI
checks bytes/header then uses atomic no-clobber publication to the requested final
path. An intervening file creation fails without replacing it. A failed staging
artifact is retained for investigation; the receipt identifies the staging and
requested paths. Header checks are not parsers or geometry/visual validation.
Local same-filesystem/hard-link support is required by the no-clobber helper;
network-filesystem and unsupported-hard-link failures do not silently degrade.

## Uncertain results

A durable intent is stored before every native mutation; every accepted request
is followed by a verification stage. Lost response, timeout, interruption or
inability to establish post-state leaves a blocking receipt. A server may keep
working after the client deadline. No automatic retry, reverse-action rollback or
transactional guarantee is supplied. A process crash may also leave a cooperative
lock; do not remove it without confirming the original process is gone.

`workflow history/status/result` read local records; they do not resume or cancel
the native application. Once a human has inspected Creo and confirmed the server
is idle, `workflow reconcile` records that acknowledgement through dry-run/confirm.
The acknowledgement never modifies Creo, restores geometry or validates the user's
assertion. Old tokens remain consumed.

Timeout scope: the shared deadline bounds upstream HTTP waits and prevents starting a further request after expiry. Local hashing, filesystem calls and SQLite lock waits are not hard-preemptible by this timer; their separate size/lock bounds still apply.
