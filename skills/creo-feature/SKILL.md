---
name: creo-feature
description: >-
  Builds Creo parts feature by feature with creo-cli: sketched extrudes and cuts, shells,
  rounds, chamfers, drafts, patterns, datum planes and axes, and reading, suppressing or
  renaming features. Use it to model a new part or add features to one.
  一个特征一个特征地建 Creo 零件：草图拉伸和切除、抽壳、倒圆角、倒角、拔模、阵列、基准面和基准轴，
  以及读取、隐含、改名特征。用来建新零件或给零件加特征。
  Not for reading or changing dimensions, parameters, materials, sessions, saving or exports;
  use creo-cli for those. 不负责读改尺寸、参数、材料，会话、保存和导出；这些请用 creo-cli。
metadata:
  version: 1.1.2
  commands: [extrude create, revolve create, shell create, round create, chamfer create, draft create, pattern create, plane create, axis create, feature list, feature get, feature update, feature delete, model check]
---

Read the entry Skill `creo-cli` first: it holds the install check, the write recipe, the STOP checkpoints, saving and the report. If it is not installed, stop and ask the user to reinstall creo-cli's Skills.

## Commands

<!-- driver:command-map:start -->
- `extrude`: create
- `revolve`: create
- `shell`: create
- `round`: create
- `chamfer`: create
- `draft`: create
- `pattern`: create
- `plane`: create
- `axis`: create
- `feature`: list, get, update, delete (dangerous)
- `model`: check
<!-- driver:command-map:end -->

## Knowledge

Read before the first feature of a task: `creo-sketches` (how to write `--sketch`), `creo-geometry-references` (naming faces and edges such as `BASE/end` and `edge(A, B)`) and `creo-units`.

## Playbooks

### Model a part

1. Read the requirement and write down the features in order, each with its name, and the dimensions to name, such as `BODY_LENGTH` or `OUTLET_PITCH`. Name every dimension a later change will touch.
2. Create the part with `creo-cli doc create --session <id> --kind part --path <file>`; it comes with PART_NO and DESCRIPTION.
3. Build one feature per call, each with `--name`. For a sketch, give every position and size by a constraint or a dimension; run the call with `--dry-run` first when unsure, and fix what `blocked_by` lists.
4. After each call check `result`: the bounding box, the change of volume (positive when material was added, negative for a cut) and the faces by place. When they are not what the step meant, fix it before the next feature: `feature update --status suppressed` takes a feature out of the way.
5. Finally change one or two named dimensions with `dimension update`, check that the geometry follows, and set them back. Save with `doc save` when the person asked for it; otherwise say in the report that the part is not saved.

### Repeat a feature

Name the leader's position dimension in its sketch, then `creo-cli pattern create --feature <leader> --along <axis> --count <n> --spacing <length> --spacing-name <NAME>`. The count includes the leader.
