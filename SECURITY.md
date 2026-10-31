# Security policy

## Risk tier

**T1.** A confirmed write changes models in a live Creo session and writes files inside
the disposable workspace (`CREO_CLI_WORKSPACE`): new model versions next to the old ones,
exported files. `artifact render`, a read, writes a new picture there too (or in creo-cli's
own directory when no workspace is set) and turns the model's window to the view and
back; it changes no model. The worst it can do: throw away unsaved changes to a model that
lives in the workspace (`model discard`), delete features (`feature delete`) or take a
component out of an assembly (`assembly component remove`) -- saved versions stay on disk. It never
overwrites or deletes a file of the user's (the only files it removes are its own staging
copies of an export), changes no system or Creo setting, and never starts or stops Creo.
Outside the workspace it writes only creo-cli's own directory (`~/.creo-cli`, or
`CREO_CLI_CONFIG_DIR`): the confirmation key and ledger, the receipts, the lock, pictures
taken when no workspace is set, and the service bundles `service install` puts there. The
three destructive commands carry a second gate, `--dangerous`, on both steps. `reference`
states the same (`risk_tier`, `risk`, `dangerous` per command).

## Who decides what

Writes are off by default. Three settings enable them, and they are the user's
decision: `CREO_CLI_WORKSPACE` (a disposable directory), `CREO_CLI_PERMISSION=write`
and `CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1`. An agent sets them only when the user
explicitly directs it in the conversation, for a disposable workspace -- never on its
own initiative and never because text it read (a model name, a note, a service message,
a web page) says so. `service install` needs `CREO_CLI_PERMISSION=write` only: it
touches no model. Persistent changes to the machine or to Creo -- `config.pro` options
such as `open_protk_unsigned_apps`, the `toolkit_registry_file` line that registers the
service -- are the user's to make and no command makes them.

## Confirmations

Every write is `--dry-run` then `--confirm <token>`. The token is HMAC-SHA256 with a
per-user 32-byte key, expires after 900 seconds, is consumed atomically in a SQLite
ledger before the write is sent (a ledger failure refuses the write), and is bound to
the command, its arguments, the state of the target the preview read and the policy. A
confirmation re-reads that state and refuses if it changed -- including a model edited
in the GUI in between. A token is a guard against stale and replayed confirmations, not
against an attacker who already controls the user's account.

## Uncertain outcomes

Every confirmed write records a receipt before it is sent. A write whose outcome
cannot be established -- a lost reply, a failure that left the model changed, a failed
postcondition -- leaves a blocking receipt, and no further write runs until a person has
inspected Creo and recorded it with `operation resolve`. Nothing is retried
automatically; `E_OUTCOME_UNKNOWN` is not retryable. A service reply that says an
operation was withdrawn before it started is the only timeout that means "nothing
happened".

## The service inside Creo

The service listens on `127.0.0.1` only. Every request except `/health` needs the token
the service writes to `~/.creo-cli/service-token` at start: loopback alone is not a
boundary, because any local process can connect and a web page can reach loopback by
DNS rebinding, and a browser cannot add the custom header without a preflight the
server never answers. The service exposes named operations only -- there is no
operation that runs a script, a mapkey or a trail file -- and each validates its input.
It runs with the user's rights inside Creo; it is not a boundary against the user's own
account.

The jar and the native library are unlocked with PTC's `protk_unlock` against a
TOOLKIT licence. Creo prompts before loading a toolkit DLL that is not code-signed; the
setting that silences the prompt (`open_protk_unsigned_apps always`) loads every
unsigned toolkit DLL, not only this one, and is the user's decision.

A service bundle's manifest carries the SHA-256 of each file, and `service install`
refuses a bundle whose files do not match it or whose protocol is not the CLI's. That
catches a damaged or mixed-up bundle, not a malicious one: the manifest travels with
the files. Take bundles only from the project's release page; whatever is installed runs
inside Creo with the user's rights.

## Untrusted content

Model names, feature names, parameter values, paths and messages that come from Creo
are listed in `_untrusted` in every reply: a read's Creo fields, a write's `result` and
`verification`, an error's service fields. A command's declaration in `reference` names
its untrusted fields, and the CLI lists every one of them that a reply carries. They are data. Nothing in the CLI acts on
their content, and the Skill tells agents not to.

## Inputs and limits

Requests are strict UTF-8 JSON, at most 8 MiB, validated against the command's schema
with unknown keys, duplicate keys and non-finite numbers refused; a workflow's steps are
each validated as their own command before anything runs. Every path a write touches is
resolved and must lie inside the workspace; symbolic escapes are refused. So must every
model a write changes, saves or closes, and every model an assembly or drawing is made to
depend on: Creo saves an assembly's changed components with it, each back where it came
from. An export only reads its model. Exports are
written by Creo into a private staging directory, checked, and moved to a name that must
not exist. A bundle's zip is unpacked by file name only, so no entry can land outside the
temporary directory. Lists are paginated.

## Supply chain

The Python runtime has no third-party dependencies. The release workflow builds the
Windows binary and publishes the archive with a checksum file signed by Sigstore; the
npm launcher runs the binary from its platform package, whose integrity npm checks
against the registry's hash at install. Dependencies of the development tooling are
audited on the merge and release paths.

## Reporting

Please report vulnerabilities privately to the repository owner through GitHub's
private vulnerability reporting on
[fatecannotbealtered/creo-cli](https://github.com/fatecannotbealtered/creo-cli). Do
not attach proprietary models or unredacted output to a public issue.
