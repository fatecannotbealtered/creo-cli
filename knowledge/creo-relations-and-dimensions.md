---
id: creo-relations-and-dimensions
title: Relations drive dimensions and parameters
kind: concept
applies_to: [dimension update, parameter update, relation list, dimension list, parameter list]
tags: [relations]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md; observed on Creo Parametric 13.4.1.0
updated_on: 2026-11-05
---
A relation such as `HEIGHT = WIDTH / 2` sets HEIGHT at every regeneration. Such a dimension or parameter is listed with `driven_by_relation: true`, and `dimension update` or `parameter update` refuses it with `E_CONFLICT`: the relation would overwrite the value. Change the value the relation reads (here WIDTH), or ask the person to change the relation. `relation list` shows the relations as Tools > Relations does.
