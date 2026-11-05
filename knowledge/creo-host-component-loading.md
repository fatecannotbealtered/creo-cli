---
id: creo-host-component-loading
title: How Creo loads the host component
kind: guide
applies_to: [plugin install, plugin get, session list]
tags: [install, host-component]
lang: en
based_on: PTC Creo Object TOOLKIT Java User's Guide, Registering a Creo Object TOOLKIT Java Application; earlier creo-cli at commit fd35893, docs/SERVICE.md
updated_on: 2026-11-05
---
Creo reads registry files only when it starts: `protk.dat` or `creotk.dat` in the folder it starts in, and the file named by `toolkit_registry_file` in `config.pro`.

1. `creo-cli plugin install` (two-step, needs `configure`) builds the host component from its source with a JDK 25, unlocks it with PTC's `protk_unlock`, puts it in `<state directory>\plugin\<version>\` and writes `<state directory>\plugin\protk.dat`. When it fails, read `native_message`: a missing JDK (set `CREO_CLI_JDK`), or no free license to unlock with (see creo-licenses).
2. The person adds `toolkit_registry_file <state directory>\plugin\protk.dat` to the `config.pro` Creo starts with. creo-cli never edits `config.pro`.
3. The person starts Creo. `session list` then shows `plugin_loaded`.

After an upgrade the line stays the same, but a running Creo keeps the version it loaded until the person restarts it; until then writes are refused with `restart_application`. The registry entry sets `fail_tol true`, so a host component that fails to start never shuts Creo down.
