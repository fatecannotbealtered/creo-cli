---
id: creo-materials
title: Where Creo finds materials
kind: concept
applies_to: [material list, model get]
tags: [materials]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/ENGINEERING-PROPERTIES.md
updated_on: 2026-11-05
---
`material list` lists the materials already in the part and the `.mtl` files of Creo's material library: the folder `pro_material_dir` names in `config.pro`, else `text\materials-library` under Common Files. A part without a material, or with Creo 13's placeholder material, has no density: `model get` then reports the volume, area and centre of mass, and `mass_kg` as null.
