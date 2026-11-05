---
id: creo-save-versions
title: How Creo saves: numbered versions in the origin folder
kind: concept
applies_to: [doc save, doc get, doc list]
tags: [save, versions]
---
Every save writes a new numbered version into the folder the model came from, not the working directory: `bracket.prt.3` after `bracket.prt.2`, even when nothing changed. Old versions stay on disk.

A part just opened may already report unsaved changes (`dirty: true`) although nobody touched it.

When a newer version of the file appears on disk after the model was opened, `doc get` reports `disk: changed`, and writes and saves are refused with `E_CONFLICT` so that nothing overwrites another person's save.
