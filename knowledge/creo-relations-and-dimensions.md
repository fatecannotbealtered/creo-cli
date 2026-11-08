---
id: creo-relations-and-dimensions
title: Relations drive dimensions and parameters
kind: concept
applies_to: [dimension update, parameter update, relation update, relation list, dimension list, parameter list, pattern create]
tags: [relations]
---
A relation such as `HEIGHT = WIDTH / 2` sets HEIGHT at every regeneration. Such a dimension or parameter is listed with `driven_by_relation: true`, and `dimension update` or `parameter update` refuses it with `E_CONFLICT`: the relation would overwrite the value. The refusal names the relation. Tell the person: changing the value the relation reads (here WIDTH) changes HEIGHT too, and only the person decides whether to do that or to change the relation. `relation list` shows the relations as Tools > Relations does.

Creo stores no negative length. Entering one in Creo flips the feature to the other side of its reference and keeps the positive value, so `dimension update` refuses a negative `--length` before anything is sent. To put a feature on the other side, ask the person: it changes the design.

`relation update` replaces all of a model's relations and regenerates. Relations can read parameters made with `parameter create`, such as `BODY_LENGTH = POSITIONS * PITCH + 32`, and drive a pattern's count, the dimension `pattern create` lists such as `p20` (`p20 = POSITIONS`). Creo computes them in real numbers: with POSITIONS 5, `POSITIONS / 2` is 2.5. `parameter update` regenerates, so the geometry follows a parameter at once; a value the model cannot regenerate with is taken back.
