---
id: creo-licenses
title: Licenses creo-cli needs
kind: rule
applies_to: [doctor, plugin install]
tags: [license]
lang: en
based_on: PTC, Creo Object TOOLKIT Java User's Guide, Unlocking, Running and Signing the Creo Object TOOLKIT Java Application; earlier creo-cli at commit fd35893, docs/COMPATIBILITY.md
updated_on: 2026-11-05
severity: error
check: doctor passes its license check and session list shows plugin_loaded
---
Besides Creo Parametric's own license:

- `plugin install` unlocks the host component with `protk_unlock`, which needs the Creo Object TOOLKIT Java development license, or its extension license with a Creo TOOLKIT license, free on the license server for that moment.
- Running the unlocked host component needs one of: the Creo Object TOOLKIT Java runtime license, its development license, or its extension license with a Creo TOOLKIT license. Without one, Creo does not run it and `session list` shows no `plugin_loaded`. Creo delivered by application streaming (PTC trial) has no toolkits at all. creo-cli never reads or stores license data.
