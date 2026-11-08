---
id: creo-geometry-references
title: Geometry references change when the model changes
kind: guide
applies_to: [geometry list, distance get, extrude create, shell create, round create]
tags: [geometry, references]
---
Faces and edges are named by their IDs, such as `surface:41` and `edge:57`; datum planes, axes and coordinate systems by their names, such as `FRONT`. IDs belong to the model as it is now: suppressing, resuming or changing features can remove or renumber faces and edges. Take references from a `geometry list` run after the last change, and never from an earlier answer.

The commands that create features also take faces by a feature and their place, which stays right when the feature grows or shrinks: `BASE/start` (on the feature's sketch plane), `BASE/end` (the far face), `BASE/side` (the rest), and a normal filter such as `BASE/side[+x]`, where a face's normal points out of the material. A symmetric extrude has no start face: both of its caps are `end`, told apart by the filter, such as `KEY/end[+z]`. Edges are `edge(BASE/end, BASE/side[+x])` (where two faces meet), `BASE/end:edges` (all edges of a face), `BASE/end:outer-edges` (its outer loop only), `SOCKET:edges` (all edges of a feature's faces) or `edge:57`, several separated by `;`. A name that fits several faces where one is needed is refused with `E_AMBIGUOUS` and their surface IDs.
