---
id: creo-troubleshooting
title: Common Creo Parametric dialogs and errors
kind: troubleshooting
applies_to: [doctor, session list, session get]
tags: [dialog, error]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md and examples/engineering/RecoveryIsolation.ps1
updated_on: 2026-11-05
---
- `E_HUMAN_REQUIRED` with `action: dismiss_dialog`: a modal dialog is open in Creo, such as File > Options, a "Retrieval" or recovery dialog at start, a license dialog, ORDER_DEBUG, or a View States request to "Apply". Ask the person to close it, then run the `resume` command.
- `E_BUSY`: Creo is regenerating or running another request. Wait `retry_after_ms` and run the command again; it was not sent.
- `session list` shows no `plugin_loaded`: the host component was not loaded at start. Check that `plugin install` ran and that `config.pro` names `<state directory>\plugin\protk.dat`; then the person restarts Creo (see creo-host-component-loading).
- `E_HUMAN_REQUIRED` with `action: restart_application`: the running Creo loaded another host component version than the one installed. Ask the person to restart Creo.
- A locked screen or a minimized window can stop or crash Creo; keep it visible during work (see creo-display-requirements).
- `E_NATIVE_FAILURE` from a change: Creo refused it and nothing durable changed; read `native_message`.
