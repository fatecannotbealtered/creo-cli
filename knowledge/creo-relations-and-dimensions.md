---
id: creo-relations-and-dimensions
title: Relations drive dimensions and parameters
kind: concept
applies_to: [dimension update, parameter update, relation list, dimension list, parameter list]
tags: [relations]
---
A relation such as `HEIGHT = WIDTH / 2` sets HEIGHT at every regeneration. Such a dimension or parameter is listed with `driven_by_relation: true`, and `dimension update` or `parameter update` refuses it with `E_CONFLICT`: the relation would overwrite the value. The refusal names the relation. Tell the person: changing the value the relation reads (here WIDTH) changes HEIGHT too, and only the person decides whether to do that or to change the relation. `relation list` shows the relations as Tools > Relations does.

Creo stores no negative length. Entering one in Creo flips the feature to the other side of its reference and keeps the positive value, so `dimension update` refuses a negative `--length` before anything is sent. To put a feature on the other side, ask the person: it changes the design.
