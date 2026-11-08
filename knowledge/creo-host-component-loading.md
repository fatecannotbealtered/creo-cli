---
id: creo-host-component-loading
title: How Creo loads the host component
kind: guide
applies_to: [plugin install, plugin get, session list, session open, session close]
tags: [install, host-component]
---
Creo reads registry files only when it starts: `protk.dat` or `creotk.dat` in the folder it starts in, and the file named by `toolkit_registry_file` in `config.pro`.

1. `creo-cli plugin install` (two-step, needs `configure`) builds the host component from its source with a JDK 25, unlocks it with PTC's `protk_unlock`, puts it in its own folder, `%LOCALAPPDATA%\creo-cli\host\<one folder per state directory>`, and writes `protk.dat` there; `plugin get` shows that folder as `install_path`. When it fails, read `native_message`: a missing JDK (set `CREO_CLI_JDK`), or no free license to unlock with (see creo-licenses). It also builds the C library, `creo-cli-native.dll`, with Visual Studio's x64 C compiler and the Creo TOOLKIT component of that Creo, unlocked with a Creo TOOLKIT development license. Without them the Java part is installed all the same; `creo-cli-host.json` in `install_path` records `native` with the reason, and the commands that need the library (sketches, `model render --view`, `session close`) are refused with `E_UNSUPPORTED` naming it. Install the missing piece (or set `CREO_CLI_VCVARS` to `vcvars64.bat`), run `plugin install` again and restart Creo.
2. The person adds `toolkit_registry_file <install_path>\protk.dat` to the `config.pro` Creo starts with. creo-cli never edits that `config.pro`. Instead of a person's Creo, `creo-cli session open` can start a Creo of the tool's own, which loads the host component by itself.
3. The person starts Creo. `session list` then shows `plugin_loaded`.

After an upgrade the line stays the same, but a running Creo keeps the version it loaded until the person restarts it; until then writes are refused with `restart_application`. The registry entry sets `fail_tol true`, so a host component that fails to start never shuts Creo down.
