# creo-cli

Lets an AI Agent read Creo Parametric models and change their dimensions, parameters and features, then save and export them: every change is previewed, confirmed and read back from Creo.

<!-- driver:badges:start -->
![Agent-native](https://img.shields.io/badge/🤖-Agent--native-6f42c1)
[![CI](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@fateforge/creo-cli)](https://www.npmjs.com/package/@fateforge/creo-cli)
![drives](https://img.shields.io/badge/drives-Creo_Parametric_%3E%3D13.4_%3C13.5-1f6feb)
![mode](https://img.shields.io/badge/mode-session-0e8a16)
![platform](https://img.shields.io/badge/platform-Windows-555555)
![risk](https://img.shields.io/badge/risk-T2-d29922)
![maturity](https://img.shields.io/badge/maturity-draft-8957e5)
![spec](https://img.shields.io/badge/spec-tool--driver--cli--spec_1.0.6-0969da)
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
| Maturity | draft: 14 draft, 12 verified, 3 stable |
| Specification | tool-driver-cli-spec 1.0.6 |
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
- `feature`: get, list, update, delete (dangerous)
- `model`: get, check, update, export, render
- `geometry`: list
- `distance`: get
- `dimension`: list, update
- `parameter`: list, update, create
- `relation`: list, update
- `material`: list
- `component`: list
- `extrude`: create
- `revolve`: create
- `shell`: create
- `round`: create
- `pattern`: create
- `plane`: create
- `axis`: create
- `chamfer`: create
- `draft`: create
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

**Saving in session mode.** A change is not a save. After a change, the receipt reports `persistence: unchanged` and the document stays dirty; only `creo-cli doc save` writes the document's file. Its preview lists every change since the last save, including changes a person made in Creo Parametric (`origin: external`) and writes whose outcome is still unknown. A command that Creo Parametric itself saves at once is two-step and reports `persistence: saved`.

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

The commands of creo-cli need these effects:

| Effect | Commands |
|---|---|
| `change` | `dimension update`, `parameter update`, `feature update` |
| `artifact` | `model export`, `model render` |
| `lifecycle` | `doc open`, `doc close` |
| `persist` | `doc save` |
| `configure` | `plugin install`, `plugin remove` |

`doc close --discard` throws unsaved changes away and is in the dangerous tier: it also needs `"dangerous": true`. A scope for changing and delivering models in one folder looks like this:

```json
{
  "scope_id": "bracket-rework",
  "effects": ["change", "artifact", "lifecycle", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/work/bracket/"],
  "expires_at": "2026-12-31T23:59:59Z"
}
```

## About This Tool

Creo Parametric is PTC's parametric 3D CAD system: parts, assemblies and drawings, each built from features driven by dimensions, parameters and relations. creo-cli drives a Creo Parametric session that a person started on the same Windows computer, through a small host component Creo loads when it starts.

Typical tasks:

- Answer questions about a model: its volume, mass, size and material, its features in order, its dimensions, parameters and relations, and the components of an assembly.
- Change a design: a dimension's value or tolerance, a parameter's value, or suppress, resume or rename a feature. Creo regenerates the model, and a value it cannot regenerate with is taken back.
- Deliver: save the model, export it to STEP, IGES or STL (a drawing to PDF), or take a JPEG of its window.

```bash
creo-cli doc open --doc D:/work/bracket/bracket.prt
creo-cli dimension list --doc bracket.prt
creo-cli dimension update --doc bracket.prt --id DEPTH --length 12mm
creo-cli doc save --doc bracket.prt                   # two-step: shows every change since the last save
creo-cli model export --doc bracket.prt --output D:/work/bracket/out/bracket.stp
```

Version 1.0 does not create models or features, and does not edit assemblies or drawings; it reads them and exports them.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CREO_CLI_STATE_DIR` | `~/.creo-cli` | The state directory: operation records, locks, the update cache and team knowledge registrations |
| `CREO_CLI_SCOPE_FILE` | `scope.json` in the state directory | The scope file (see Authorization) |
| `HTTPS_PROXY`, `HTTP_PROXY`, `NO_PROXY` | not set | Proxies for `update` and `doctor`, the only commands that contact the npm registry |
| `CREO_CLI_JDK` | the JDK of `PRO_JAVA_COMMAND`, else `JAVA_HOME` | The JDK 25 `plugin install` builds the host component with |
| `CREO_CLI_VCVARS` | the newest Visual Studio with the x64 C compiler | The `vcvars64.bat` `plugin install` builds the host component's C library with |
| `CREO_CLI_FAKE_HOST` | not set | For tests only: sends every call to the fake host instead of Creo Parametric and marks every result as simulated |

### Finding Creo Parametric

- Installation: creo-cli looks under `C:\Program Files\PTC`, `C:\PTC`, `D:\PTC` and `E:\PTC`, up to four folders deep, for a `Common Files` folder that holds Object TOOLKIT Java (`text\java\otk.jar`). The version comes from the installation folder's name, such as `Creo 13.4.1.0`. `creo-cli doctor` shows what it found.
- Running instances: every running `xtop.exe` is a session, with an ID made of its process ID and start time, such as `creo-9184-1d9a4c2e`. `creo-cli session list` lists them; a modal dialog open in Creo shows as `blocked`.
- The host component: a session can be driven only while its host component is loaded. creo-cli ships it as source: `creo-cli plugin install` compiles its Java part with a JDK 25 and unlocks it with PTC's `protk_unlock`, which needs the Creo Object TOOLKIT Java development license, or its extension license with a Creo TOOLKIT license, on the license server; running it needs the Object TOOLKIT Java runtime, development or extension license. `plugin install` also compiles its C library, which sketches and ending Creo need, with Visual Studio 2022's C compiler (or its Build Tools with "Desktop development with C++") against the Creo TOOLKIT component of your Creo, and unlocks it with a Creo TOOLKIT development license; without them the Java part is still installed and only the commands that need the C library are refused, with the reason. Run `creo-cli plugin install`, add one line to the `config.pro` Creo starts with, and start Creo: `toolkit_registry_file <install_path>\protk.dat`, with the `install_path` that `creo-cli plugin get` shows, a folder under `%LOCALAPPDATA%\creo-cli\host`. The line stays the same across upgrades; creo-cli never changes the `config.pro` you start Creo with. Creo loads the host component only at start, so after an upgrade a person restarts Creo.
- Creo started by creo-cli: `creo-cli session open` starts a Creo of its own from the folder `start` beside the host component, with a `config.pro` there that loads the host component and sets `open_protk_unsigned_apps always`, so that this Creo loads the unsigned C library without asking; your own Creo keeps its settings. `session close` ends such a Creo as File > Exit does, and refuses while a model has unsaved changes.
- `CREO_CLI_STATE_DIR` moves the state directory, and with it the place of `protk.dat` and of the discovery files the host component writes.

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
