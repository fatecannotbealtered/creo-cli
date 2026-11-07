---
id: creo-display-requirements
title: Creo needs a visible desktop
kind: rule
applies_to: [model render, session list]
tags: [display]
severity: warning
check: the person keeps Creo visible and the screen unlocked during work
---
Creo Parametric runs here with its window on a visible desktop. Headless operation is not available to the host component, and a locked screen or a minimized window was never qualified: with the Intel OpenGL driver a locked screen crashed Creo. `model render` takes its picture from the model's own window, active or not (measured on Creo 13.4.1.0); a model in session only as part of an assembly or drawing has no window, so `doc open` it first.

`model render --view FRONT` (or TOP, RIGHT, DEFAULT, or a view saved in the model) turns the window to that view for the picture and puts the person's view back after. Creo counts keeping and deleting the person's view as a change, so a model that had no unsaved changes shows as modified afterwards (`model_marked_modified` in the result): `doc close` then needs `doc save` first, or `--discard`. Without `--view` the picture shows the window as it is and changes nothing.
