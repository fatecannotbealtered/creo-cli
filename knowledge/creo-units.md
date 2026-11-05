---
id: creo-units
title: Model units and the millimetres creo-cli speaks
kind: concept
applies_to: [dimension list, dimension update, model get, geometry list, distance get, parameter update]
tags: [units]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md; observed on Creo Parametric 13.4.1.0
updated_on: 2026-11-05
---
A model's units come from its unit system, set by its template: mmns (mm, N, s), inlbs (in, lbf, s) and others. creo-cli converts every length to and from millimetres in the host component, so `dimension list` reports `value_mm` for an inch model too, and `--length 0.5in` sets 12.7 mm.

`model get` reports the model's own length and mass units under `units`. A real parameter with a length unit takes its value with a unit, such as `--value 12.5mm`; one without a unit takes a plain number.
