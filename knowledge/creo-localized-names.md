---
id: creo-localized-names
title: Names Creo gives in the session language
kind: concept
applies_to: [feature list, feature get]
tags: [language]
lang: en
based_on: earlier creo-cli at commit fd35893, docs/SERVICE.md; observed on Creo Parametric 13.4.1.0
updated_on: 2026-11-05
---
Creo names new features and views in the session's language, such as 拉伸 1 on a Chinese session. creo-cli reports feature types and statuses as stable identifiers (`protrusion`, `suppressed`), never as the translated labels, but feature names stay what Creo or the person wrote. Refer to a feature by its ID when its name may be translated.
