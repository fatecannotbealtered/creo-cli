# Creo CLI

Creo CLI lets an agent inspect and edit mechanical projects through a service inside
licensed PTC Creo Parametric. Changes use a fresh preview, one confirmation, native
readback and a retained receipt. The source includes modeling, assemblies, drawings,
presentation and delivery commands; discover each command's current limits with `reference`.

**Windows isolated unsigned beta, 1.1.0-beta.1.** The bounded native observations are
from Creo 13.4.1.0, JDK 25.0.3 and a visible window. Other versions, platforms,
locked/minimized/headless operation and clean-machine deployment are unqualified.
Source-part RGB, bounded rigid placement and save/empty-session/reopen have native
evidence. Numeric density/material edits, instance-only color, advanced assemblies,
STEP delivery, deletion and drawing symbols remain restricted. Complex assemblies
can take minutes. `reference` reports beta/partial readiness; command presence is
not proof of native qualification.

This package rebuilds only the client with project-controlled Python 3.15.2,
patched XZ 5.8.4 and PyInstaller 6.22.3. The runtime is compiled from official
sources using the recorded build configuration. Its exact embedded runtime and old-history compatibility are checked offline;
the unchanged JAR/DLL retain their original build sources. Offline runtime checks
do not extend the historic native qualification.

## Install the complete Windows package

Download the Windows x64 ZIP and `checksums.txt` from this repository's prerelease.
Verify the SHA-256 before extracting it under a dedicated directory, for example
`D:/creo-work/package`. Keep its manifest, notices and three components together.
No Python or Node is required to use that package. Supply licensed Creo Parametric,
its required API/runtime license options, JDK 25.0.3 and PowerShell 7.4 or newer.
The package contains original unlocked JAR/DLL code, not the Creo SDK or vendor runtime.

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath ./creo-cli-1.1.0-beta.1-windows-x64.zip
New-Item -ItemType Directory -Path D:/creo-work/history
& ./cli/examples/engineering/Initialize-CreoWorkspace.ps1 `
  -WorkRoot D:/creo-work/run -HistoryDirectory D:/creo-work/history `
  -CreoRoot C:/PTC/Creo -JavaHome C:/Java/jdk-25
```

Use the existing continuing CLI history when upgrading; never replace it to clear
an unresolved operation. Explicit initialization authorizes only the isolated run,
package and exact `workspace/.creo-cli/staging` path. It does not authorize their
whole common parent. It verifies the complete package and installs components;
it does not start Creo and requires no bundled model. Copy your own authorized
project and its dependencies into `run/projects` and work on that copy.

The unsigned profile changes policy only for its new process. It allows unsigned
applications for that process, so it is not a one-DLL allowlist or a publisher
signature. Do not use it where organization policy forbids unsigned applications.
The preflight preserves global trust/licensing settings and existing CAD sessions.

```powershell
& ./cli/examples/engineering/Start-CreoWorkspace.ps1 -WorkRoot D:/creo-work/run -PreflightOnly
& ./cli/examples/engineering/Start-CreoWorkspace.ps1 -WorkRoot D:/creo-work/run
```

Read [the startup and invocation guide](docs/STARTUP-NATIVE.md) before the second
command. Verify actual loaded identities with `context`/`doctor`; a preflight alone
does not establish startup. Keep unknown/pending operations and their first receipts;
do not blindly retry, discard, close or kill a session.

## Agent Skills

```sh
npx skills add fatecannotbealtered/creo-cli -y -g
```

This optional command installs the complete Skill family; it does not install the
CLI or host dependencies. Without Node, copy the complete `cli/skills` family from
the ZIP into the agent's configured skill directory. Install `creo-cli` and use it
for Creo work, routing by the mechanical task:

| Skill | Task |
|---|---|
| creo-cli | Environment, discovery and shared safety |
| creo-modeling | Part inspection and supported feature changes |
| creo-assembly | Exact occurrence paths and assembly constraints |
| creo-drawing | Supported views, dimensions and annotations |
| creo-presentation | Source appearance, view state and native images |
| creo-delivery | Save, reopen, owned exit and engineering handoff |

Read [release notes](release/RELEASE-NOTES.md), [component dependencies and licenses](docs/RUNTIME-DEPENDENCIES.md)
and [third-party notices](NOTICE.md). The npm wrapper and self-update route are not
published for this beta; use complete, verified packages. The repository retains
the full CLI/service source and offline tests, while private projects and raw
historical receipts are kept outside this public snapshot.
