---
id: creo-display-requirements
title: Creo needs a visible desktop
kind: rule
applies_to: [model render, session list]
tags: [display]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/HEADLESS-SUPPORT.md and docs/SERVICE.md
updated_on: 2026-11-05
severity: warning
check: the person keeps Creo visible and the screen unlocked during work
---
Creo Parametric runs here with its window on a visible desktop. Headless operation is not available to the host component, and a locked screen or a minimized window was never qualified: with the Intel OpenGL driver a locked screen crashed Creo. `model render` takes its picture from the model's window, which must be the active window.
