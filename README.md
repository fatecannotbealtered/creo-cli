# creo-cli

{{fill: one-line pitch: what the tool lets an Agent do in Creo Parametric}}

<!-- driver:badges:start -->
![Agent-native](https://img.shields.io/badge/🤖-Agent--native-6f42c1)
[![CI](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@fateforge/creo-cli)](https://www.npmjs.com/package/@fateforge/creo-cli)
![drives](https://img.shields.io/badge/drives-Creo_Parametric_%3E%3D13.4_%3C13.5-1f6feb)
![mode](https://img.shields.io/badge/mode-session-0e8a16)
![platform](https://img.shields.io/badge/platform-Windows-555555)
![risk](https://img.shields.io/badge/risk-T2-d29922)
![maturity](https://img.shields.io/badge/maturity-draft-8957e5)
![spec](https://img.shields.io/badge/spec-tool--driver--cli--spec_1.0.0-0969da)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)
<!-- driver:badges:end -->

English | [中文](README_zh.md)

<!-- driver:info-card:start -->
| Item | Value |
|---|---|
| Application | Creo Parametric >=13.4 <13.5 |
| Modes | session |
| Systems and CPUs | Windows (x64) |
| Risk tier | T2 |
| Maturity | draft: 0 draft, 0 verified, 0 stable |
| Specification | tool-driver-cli-spec 1.0.0 |
| Host component | yes |
<!-- driver:info-card:end -->

## Install

1. Install creo-cli from npm:

   ```bash
   npm install -g @fateforge/creo-cli
   ```

2. Run `update` once. The installed version is already current, so `update` only points the command entry at the native program, so that no call has to start Node.js first:

   ```bash
   creo-cli update
   ```

3. Install the Skills from the installed package; they never come from the network. Copy them into your Agent's Skill folder. With bash:

   ```bash
   mkdir -p ~/.agents/skills
   cp -r "$(npm root -g)/@fateforge/creo-cli/skills/"* ~/.agents/skills/
   ```

   With PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
   Copy-Item -Recurse -Force "$(npm root -g)\@fateforge/creo-cli\skills\*" "$HOME\.agents\skills\"
   ```

   Other Agent Skill folders work the same way. Later runs of `creo-cli update` keep the copies in step with the tool in these folders: `~/.agents/skills/`, `~/.claude/skills/`, `~/.codex/skills/`, `~/.cursor/skills/` and `~/.gemini/skills/`. A copy anywhere else is not updated.

4. Install the host component into Creo Parametric. This is a two-step write that needs a scope file allowing `configure` (see Authorization). The first call changes nothing and returns a preview and a confirm token; the second call installs:

   ```bash
   creo-cli plugin install
   creo-cli plugin install --confirm <token>
   ```

   Start or restart Creo Parametric afterwards so that it loads the host component.

## Capabilities

Every command of creo-cli, generated from its command registration; `(dangerous)` marks a command in the dangerous tier, and `creo-cli reference --command "<path>"` describes one in full.

<!-- driver:command-map:start -->
- `reference`
- `context`
- `doctor`
- `changelog`
- `operation`: get, list, resolve
- `update`
- `session`: list, get, open, close
- `doc`: list, get, create, open, save, save-as, close, undo
- `job`: list, get, cancel
- `plugin`: get, install, remove
- `knowledge`: list, get, search, create, delete
<!-- driver:command-map:end -->

## How It Works

creo-cli prints one JSON envelope for every call. `creo-cli reference` lists every command, and `creo-cli reference --command "<path>"` describes one, with its flags, its effects and its confirmation tier in each mode.

**Instances and documents.** creo-cli drives running instances of Creo Parametric. `creo-cli session list` shows each instance with its session ID, its state and its open documents, and `creo-cli doc list` shows the documents. Name the instance with `--session <id>` and the document with `--doc <path-or-id>`. When several instances run and a command names none, it returns `E_AMBIGUOUS` with the candidates: creo-cli never picks an instance by window focus or by recent use. A `--doc` that exactly one instance has open selects that instance. A file that an instance has open is changed only through that instance; a direct write to the file is refused with `E_CONFLICT`.

**Confirmation tiers.** Every write checks the scope, builds a preview, checks the state again just before dispatch, locks its target, reads the change back and returns a receipt. Only the confirmation depends on the tier, which creo-cli derives from the effects the command declares:

| Tier | Applies to | How to call |
|---|---|---|
| direct | Changes held in memory until they are saved; starting instances; creating and opening documents; new files that overwrite nothing; stopping work | One call runs it |
| two-step | Saving and overwriting files; changes in file and device mode; settings; host components | The first call changes nothing and returns `E_CONFIRMATION_REQUIRED` with a preview and a confirm token; the same command with `--confirm <token>` runs it |
| dangerous | Physical actions; handing content to outside people or systems; irreversible changes; discarding unsaved changes; closing an instance creo-cli did not start | As two-step, and the confirming call also carries `--dangerous`; the scope must allow dangerous operations |

`--dry-run` shows the preview of any write and changes nothing. A confirm token works once, within 10 minutes, and only for the change it previewed. When the scope file sets `"confirm": "always"`, every write except stopping work is two-step, so that a person can approve each preview.

**Saving in session mode.** A change is not a save. After a change, the receipt reports `persistence: unchanged` and the document stays dirty; only `creo-cli doc save` writes the document's file. Its preview lists every change since the last save, including changes a person made in Creo Parametric (`origin: external`) and writes whose outcome is still unknown.

**Receipts.** Every write returns a receipt that reports separately whether the change ran, took effect, was delivered, was saved and was verified. When the reply to a write is lost, creo-cli returns `E_OUTCOME_UNKNOWN` with the command that settles the outcome, and the write is never sent twice.

## Authorization

creo-cli reads without asking, but it writes only what a person has granted in a scope file. The person writes this JSON file by hand; no command writes it, and an Agent never creates or changes it. creo-cli reads it from the path in `CREO_CLI_SCOPE_FILE`, or from `scope.json` in the state directory when the variable is not set, and from nowhere else.

```json
{
  "scope_id": "demo-rework",
  "effects": ["change", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/projects/demo/"],
  "expires_at": "2027-01-31T18:00:00Z"
}
```

| Field | Meaning |
|---|---|
| `scope_id` | Names the grant; operation records carry it |
| `effects` | The effects writes may have; reads need no scope |
| `dangerous` | Whether operations in the dangerous tier are allowed |
| `targets` | Target-key prefixes of the objects writes may touch: `file:///D:/projects/demo/` covers every file under that folder, `untitled:` covers new documents and `device:<id>` covers one device |
| `expires_at` | When the grant ends, in UTC |
| `confirm` | Optional; `always` makes every write except stopping work wait until a person approves its preview |

A write the scope does not cover changes nothing and returns `E_FORBIDDEN`, with what is missing and a snippet the person can paste into the file. `creo-cli context` shows the scope in force, and `SECURITY.md` describes the scope in full.

{{fill: the effects the commands of creo-cli need, and which commands need each, for example as a table of effect and commands}}

## About This Tool

{{fill: the domain of Creo Parametric, the typical tasks an Agent does with creo-cli, and screenshots or short examples}}

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CREO_CLI_STATE_DIR` | `~/.creo-cli` | The state directory: operation records, locks, the update cache and team knowledge registrations |
| `CREO_CLI_SCOPE_FILE` | `scope.json` in the state directory | The scope file (see Authorization) |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | not set | Proxies for `update` and `doctor`, the only commands that contact the npm registry |
| `CREO_CLI_FAKE_HOST` | not set | For tests only: sends every call to the fake host instead of Creo Parametric and marks every result as simulated |

### Finding Creo Parametric

{{fill: how creo-cli finds Creo Parametric: install location, version detection, running instances, and any setting the user can change}}

## Uninstall

Remove the host component first, while creo-cli is still installed. Like installing, removing is a two-step write that needs a scope allowing `configure`. A version that a running instance still has loaded stays on disk; close Creo Parametric and run the command again to remove it.

```bash
creo-cli plugin remove
creo-cli plugin remove --confirm <token>
```

Remove the installed Skills while the package still lists them. With bash:

```bash
for skill in "$(npm root -g)/@fateforge/creo-cli/skills/"*; do rm -rf ~/.agents/skills/"$(basename "$skill")"; done
```

With PowerShell:

```powershell
Get-ChildItem "$(npm root -g)\@fateforge/creo-cli\skills" | ForEach-Object { Remove-Item -Recurse -Force "$HOME\.agents\skills\$($_.Name)" -ErrorAction SilentlyContinue }
```

Do the same in every other Agent Skill folder you copied them to, such as `~/.claude/skills/`. Then remove the npm package:

```bash
npm uninstall -g @fateforge/creo-cli
```

On Windows, also delete the folder `.creo-cli-trash` in npm's global `node_modules` folder (`npm root -g`) if it exists; `update` keeps earlier program files there until its next run when the state directory is on another disk.

Last, delete the state directory: `~/.creo-cli`, or the folder that `CREO_CLI_STATE_DIR` names. It holds the operation records, the locks, the default scope file and the team knowledge registrations, so keep it if you want the records.

```bash
rm -rf ~/.creo-cli
```

```powershell
Remove-Item -Recurse -Force "$HOME\.creo-cli"
```

## Development

creo-cli is written in Python on the driver runtime in `creo_cli/_driver/`, a pinned copy that is never edited. Domain commands live in `creo_cli/commands/` and the adapter layer in `creo_cli/adapter/`.
The host component source lives in `plugin/`.

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/spec.py check
python -m unittest discover -s tests
python scripts/spec.py suites
```

The tests and the conformance suites use the fake host and never need Creo Parametric. `CONTRIBUTING.md` describes the workflow, the behavior matrices and live runs.

## Links

- Specification: [tool-driver-cli-spec 1.0.0](.agent/), pinned in `.agent/`
- [CHANGELOG.md](CHANGELOG.md): the changes in each version
- [SECURITY.md](SECURITY.md): the security model and how to report a vulnerability
- [CONTRIBUTING.md](CONTRIBUTING.md): how to contribute
- [docs/APPLICATION.md](docs/APPLICATION.md): the capability survey of Creo Parametric
- [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md): where creo-cli works
- [docs/E2E.md](docs/E2E.md): live acceptance and its records
- Issues: <https://github.com/fatecannotbealtered/creo-cli/issues>
