---
id: creo-geometry-references
title: Geometry references change when the model changes
kind: guide
applies_to: [geometry list, distance get]
tags: [geometry, references]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md; observed on Creo Parametric 13.4.1.0
updated_on: 2026-11-05
---
Faces and edges are named by their IDs, such as `surface:41` and `edge:57`; datum planes, axes and coordinate systems by their names, such as `FRONT`. IDs belong to the model as it is now: suppressing, resuming or changing features can remove or renumber faces and edges. Take references from a `geometry list` run after the last change, and never from an earlier answer.
