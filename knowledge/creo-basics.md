---
id: creo-basics
title: Key operating points of Creo Parametric
kind: guide
applies_to: [context, session list, doc open]
tags: [basics]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md; observed on Creo Parametric 13.4.1.0
updated_on: 2026-11-05
---
- creo-cli drives a Creo Parametric that a person started, and only while its host component is loaded: `session list` shows `plugin_loaded`. A session without it accepts no command; ask the person to add the `toolkit_registry_file` line the README gives and restart Creo.
- Creo holds one model of a name at a time. A document's ID is its file name, such as `bracket.prt`; `--doc` takes that ID or the file's path. Opening a second file of the same name from another folder is refused while the first is open.
- Opening an assembly or a drawing also loads the parts it uses; they are listed as documents without a window of their own. A model that an open assembly or drawing uses cannot be closed: close the assembly or drawing first. `model render` needs a model's own window: `doc open` the part.
- Changes live in Creo's memory until `doc save`. Saving writes a new numbered version (`bracket.prt.4`); see creo-save-versions.
- Lengths go in with a unit (`12mm`, `0.5in`) and come out in millimetres, whatever units the model uses; see creo-units.
- Creo works on one request at a time. While it runs one, or while a person has a dialog open, commands answer `E_BUSY` or `E_HUMAN_REQUIRED`.
- A dimension or parameter driven by a relation cannot be set; tell the person which relation drives it (see creo-relations-and-dimensions).
