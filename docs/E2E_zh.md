# 真实软件验收

[English](E2E.md) | 中文

真实软件运行用真实的适配层，在真实的 Creo Parametric 上执行 creo-cli 的行为矩阵。它会做出真实的修改，所以只使用人在下面授权过的目标。

## 授权目标

真实软件运行可以使用的 Creo Parametric 实例、文件、文件夹和设备，唯一的清单在英文版 `docs/E2E.md` 的「Authorized Targets」一节；检查脚本和矩阵运行器只读那一份，本节不另列目标。只有人能往清单里加目标，编程 Agent 从不添加。每个目标占一个列表项，以反引号括起的目标开头，写法与授权范围文件里的目标相同：文件或文件夹的 `file://` URL，或者设备的 `device:<id>`；后面跟一个冒号和对目标的说明。Creo Parametric 的实例没有固定的 ID，所以真实软件运行只使用人为这次运行启动的实例，打开的文档也只来自这里列出的文件和文件夹。真实软件运行不使用任何其他目标，真实软件运行所用的授权范围文件也只授予这里列出的目标。

清单以 `docs/E2E.md` 为准。

## 步骤

真实软件运行使用这些电脑：

一台 Windows 11 x64 电脑，装有 Creo Parametric 13.4.1.0、它的 Object TOOLKIT Java 和 JDK 25，用会话模式。真实软件运行使用自己的状态目录（`CREO_CLI_STATE_DIR`）。第一次运行前，用这个状态目录运行 `creo-cli plugin install`，由人在为这次运行启动的 Creo 所用的 `config.pro` 里加一行 `toolkit_registry_file <install_path>\protk.dat`（`install_path` 见 `creo-cli plugin get` 的输出），再启动 Creo；`creo-cli session list` 必须显示 `plugin_loaded`。

在真实的 Creo Parametric 上运行行为矩阵：

1. 由人准备目标，比如专为测试复制的项目、为这次运行启动的实例，或为测试准备好的设备，并把它们列进「授权目标」。
2. 由人写一个只授予这些目标的授权范围文件，包含被测命令需要的效果，并让 `CREO_CLI_SCOPE_FILE` 指向它。把 `CREO_CLI_STATE_DIR` 设为专供真实软件运行使用的目录。
3. 运行 `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>`，矩阵用到的每个占位符各给一个 `--set`，占位符名不带花括号，如 `--set doc=<file>`：`{session}` 是授权的实例，`{doc}` 是授权的文档或文件，`{device}` 是授权的设备，`{dir}` 是授权文件夹里新建的空目录。
4. 运行器执行适用的行，把真实软件记录写进 `docs/evidence/`，并填上每一行的实际结果和 `live:` 证据引用。实际结果与预期不符的行算作失败。
5. 在真实的 Creo Parametric 上无法按需制造的行，如 `disconnect`，可以标为 `unrunnable` 并写明原因；`normal`、`dialog` 和 `read_back_mismatch` 这三行不可以。
6. 运行 `python scripts/spec.py generate` 更新支持矩阵和下面的索引，再把记录和矩阵一起提交。

要在真实的 Creo Parametric 上运行评测题，由人在「授权目标」里列出一个放评测工作目录的文件夹，以及题目的 `SCOPE` 用到的其他目标，比如设备。然后运行 `python scripts/spec.py eval --workspace-root <folder>`。运行器自己为每道题写授权范围文件，只授予这道题的文档和它的 `SCOPE` 列出的目标，并把评测报告写进 `docs/evidence/`。

真实软件记录只在它记录的工具版本与 creo-cli 的主版本和次版本都相同时才算作证据。记录里从不出现机密，带机密的参数显示为 `***`。

## 证据记录

`docs/evidence/` 里的真实软件记录，由 `python scripts/spec.py generate` 生成：

<!-- driver:evidence:start -->
| 记录 | 运行时间 | 软件 | 平台 | 结果 |
|---|---|---|---|---|
| [2026-11-05-122950-doc-open.json](evidence/2026-11-05-122950-doc-open.json) | 2026-11-05T12:29:50Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-122812-session-list.json](evidence/2026-11-05-122812-session-list.json) | 2026-11-05T12:28:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122802-session-get.json](evidence/2026-11-05-122802-session-get.json) | 2026-11-05T12:28:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122756-relation-list.json](evidence/2026-11-05-122756-relation-list.json) | 2026-11-05T12:27:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122748-parameter-update.json](evidence/2026-11-05-122748-parameter-update.json) | 2026-11-05T12:27:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122740-parameter-list.json](evidence/2026-11-05-122740-parameter-list.json) | 2026-11-05T12:27:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122734-model-render.json](evidence/2026-11-05-122734-model-render.json) | 2026-11-05T12:27:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122728-model-get.json](evidence/2026-11-05-122728-model-get.json) | 2026-11-05T12:27:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122724-model-export.json](evidence/2026-11-05-122724-model-export.json) | 2026-11-05T12:27:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122719-material-list.json](evidence/2026-11-05-122719-material-list.json) | 2026-11-05T12:27:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122712-geometry-list.json](evidence/2026-11-05-122712-geometry-list.json) | 2026-11-05T12:27:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122707-feature-update.json](evidence/2026-11-05-122707-feature-update.json) | 2026-11-05T12:27:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122702-feature-list.json](evidence/2026-11-05-122702-feature-list.json) | 2026-11-05T12:27:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122658-feature-get.json](evidence/2026-11-05-122658-feature-get.json) | 2026-11-05T12:26:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122654-doc-save.json](evidence/2026-11-05-122654-doc-save.json) | 2026-11-05T12:26:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122650-doc-open.json](evidence/2026-11-05-122650-doc-open.json) | 2026-11-05T12:26:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122645-doc-get.json](evidence/2026-11-05-122645-doc-get.json) | 2026-11-05T12:26:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122639-doc-close.json](evidence/2026-11-05-122639-doc-close.json) | 2026-11-05T12:26:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122634-distance-get.json](evidence/2026-11-05-122634-distance-get.json) | 2026-11-05T12:26:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122628-dimension-update.json](evidence/2026-11-05-122628-dimension-update.json) | 2026-11-05T12:26:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122619-dimension-list.json](evidence/2026-11-05-122619-dimension-list.json) | 2026-11-05T12:26:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122611-component-list.json](evidence/2026-11-05-122611-component-list.json) | 2026-11-05T12:26:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122416-relation-list.json](evidence/2026-11-05-122416-relation-list.json) | 2026-11-05T12:24:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122357-parameter-update.json](evidence/2026-11-05-122357-parameter-update.json) | 2026-11-05T12:23:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122339-parameter-list.json](evidence/2026-11-05-122339-parameter-list.json) | 2026-11-05T12:23:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122321-model-render.json](evidence/2026-11-05-122321-model-render.json) | 2026-11-05T12:23:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122302-model-get.json](evidence/2026-11-05-122302-model-get.json) | 2026-11-05T12:23:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122245-model-export.json](evidence/2026-11-05-122245-model-export.json) | 2026-11-05T12:22:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122227-material-list.json](evidence/2026-11-05-122227-material-list.json) | 2026-11-05T12:22:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122210-geometry-list.json](evidence/2026-11-05-122210-geometry-list.json) | 2026-11-05T12:22:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122153-feature-update.json](evidence/2026-11-05-122153-feature-update.json) | 2026-11-05T12:21:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122133-feature-list.json](evidence/2026-11-05-122133-feature-list.json) | 2026-11-05T12:21:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122119-feature-get.json](evidence/2026-11-05-122119-feature-get.json) | 2026-11-05T12:21:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122107-doc-save.json](evidence/2026-11-05-122107-doc-save.json) | 2026-11-05T12:21:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122050-doc-open.json](evidence/2026-11-05-122050-doc-open.json) | 2026-11-05T12:20:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122038-doc-close.json](evidence/2026-11-05-122038-doc-close.json) | 2026-11-05T12:20:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122020-distance-get.json](evidence/2026-11-05-122020-distance-get.json) | 2026-11-05T12:20:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-122005-dimension-update.json](evidence/2026-11-05-122005-dimension-update.json) | 2026-11-05T12:20:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121947-dimension-list.json](evidence/2026-11-05-121947-dimension-list.json) | 2026-11-05T12:19:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121940-component-list.json](evidence/2026-11-05-121940-component-list.json) | 2026-11-05T12:19:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121933-relation-list.json](evidence/2026-11-05-121933-relation-list.json) | 2026-11-05T12:19:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121929-parameter-update.json](evidence/2026-11-05-121929-parameter-update.json) | 2026-11-05T12:19:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121925-parameter-list.json](evidence/2026-11-05-121925-parameter-list.json) | 2026-11-05T12:19:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121921-model-render.json](evidence/2026-11-05-121921-model-render.json) | 2026-11-05T12:19:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121916-model-get.json](evidence/2026-11-05-121916-model-get.json) | 2026-11-05T12:19:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121914-model-export.json](evidence/2026-11-05-121914-model-export.json) | 2026-11-05T12:19:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121910-material-list.json](evidence/2026-11-05-121910-material-list.json) | 2026-11-05T12:19:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121907-geometry-list.json](evidence/2026-11-05-121907-geometry-list.json) | 2026-11-05T12:19:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121904-feature-update.json](evidence/2026-11-05-121904-feature-update.json) | 2026-11-05T12:19:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121900-feature-list.json](evidence/2026-11-05-121900-feature-list.json) | 2026-11-05T12:19:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121855-feature-get.json](evidence/2026-11-05-121855-feature-get.json) | 2026-11-05T12:18:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121849-doc-save.json](evidence/2026-11-05-121849-doc-save.json) | 2026-11-05T12:18:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121844-doc-open.json](evidence/2026-11-05-121844-doc-open.json) | 2026-11-05T12:18:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121837-doc-close.json](evidence/2026-11-05-121837-doc-close.json) | 2026-11-05T12:18:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121830-distance-get.json](evidence/2026-11-05-121830-distance-get.json) | 2026-11-05T12:18:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121824-dimension-update.json](evidence/2026-11-05-121824-dimension-update.json) | 2026-11-05T12:18:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121816-dimension-list.json](evidence/2026-11-05-121816-dimension-list.json) | 2026-11-05T12:18:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121810-component-list.json](evidence/2026-11-05-121810-component-list.json) | 2026-11-05T12:18:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121804-component-list.json](evidence/2026-11-05-121804-component-list.json) | 2026-11-05T12:18:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121758-dimension-update.json](evidence/2026-11-05-121758-dimension-update.json) | 2026-11-05T12:17:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121752-model-render.json](evidence/2026-11-05-121752-model-render.json) | 2026-11-05T12:17:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121747-model-export.json](evidence/2026-11-05-121747-model-export.json) | 2026-11-05T12:17:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121743-doc-close.json](evidence/2026-11-05-121743-doc-close.json) | 2026-11-05T12:17:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121739-doc-open.json](evidence/2026-11-05-121739-doc-open.json) | 2026-11-05T12:17:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121734-plugin-remove.json](evidence/2026-11-05-121734-plugin-remove.json) | 2026-11-05T12:17:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121728-plugin-install.json](evidence/2026-11-05-121728-plugin-install.json) | 2026-11-05T12:17:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121722-doc-save.json](evidence/2026-11-05-121722-doc-save.json) | 2026-11-05T12:17:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121716-feature-update.json](evidence/2026-11-05-121716-feature-update.json) | 2026-11-05T12:17:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121712-parameter-update.json](evidence/2026-11-05-121712-parameter-update.json) | 2026-11-05T12:17:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121708-dimension-update.json](evidence/2026-11-05-121708-dimension-update.json) | 2026-11-05T12:17:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121703-model-export.json](evidence/2026-11-05-121703-model-export.json) | 2026-11-05T12:17:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121658-doc-save.json](evidence/2026-11-05-121658-doc-save.json) | 2026-11-05T12:16:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121648-doc-save.json](evidence/2026-11-05-121648-doc-save.json) | 2026-11-05T12:16:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121639-doc-save.json](evidence/2026-11-05-121639-doc-save.json) | 2026-11-05T12:16:39Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121629-model-render.json](evidence/2026-11-05-121629-model-render.json) | 2026-11-05T12:16:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121622-model-export.json](evidence/2026-11-05-121622-model-export.json) | 2026-11-05T12:16:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121609-relation-list.json](evidence/2026-11-05-121609-relation-list.json) | 2026-11-05T12:16:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121603-parameter-update.json](evidence/2026-11-05-121603-parameter-update.json) | 2026-11-05T12:16:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121553-parameter-list.json](evidence/2026-11-05-121553-parameter-list.json) | 2026-11-05T12:15:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121546-model-get.json](evidence/2026-11-05-121546-model-get.json) | 2026-11-05T12:15:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121538-material-list.json](evidence/2026-11-05-121538-material-list.json) | 2026-11-05T12:15:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121529-geometry-list.json](evidence/2026-11-05-121529-geometry-list.json) | 2026-11-05T12:15:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121522-feature-update.json](evidence/2026-11-05-121522-feature-update.json) | 2026-11-05T12:15:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121514-feature-list.json](evidence/2026-11-05-121514-feature-list.json) | 2026-11-05T12:15:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121508-feature-get.json](evidence/2026-11-05-121508-feature-get.json) | 2026-11-05T12:15:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121503-doc-close.json](evidence/2026-11-05-121503-doc-close.json) | 2026-11-05T12:15:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121454-doc-save.json](evidence/2026-11-05-121454-doc-save.json) | 2026-11-05T12:14:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121444-doc-list.json](evidence/2026-11-05-121444-doc-list.json) | 2026-11-05T12:14:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121438-doc-get.json](evidence/2026-11-05-121438-doc-get.json) | 2026-11-05T12:14:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121433-distance-get.json](evidence/2026-11-05-121433-distance-get.json) | 2026-11-05T12:14:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121427-dimension-update.json](evidence/2026-11-05-121427-dimension-update.json) | 2026-11-05T12:14:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121419-dimension-list.json](evidence/2026-11-05-121419-dimension-list.json) | 2026-11-05T12:14:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121412-feature-update.json](evidence/2026-11-05-121412-feature-update.json) | 2026-11-05T12:14:12Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-121357-parameter-update.json](evidence/2026-11-05-121357-parameter-update.json) | 2026-11-05T12:13:57Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-121334-dimension-update.json](evidence/2026-11-05-121334-dimension-update.json) | 2026-11-05T12:13:34Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-121315-doc-close.json](evidence/2026-11-05-121315-doc-close.json) | 2026-11-05T12:13:15Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121253-model-render.json](evidence/2026-11-05-121253-model-render.json) | 2026-11-05T12:12:53Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121236-model-export.json](evidence/2026-11-05-121236-model-export.json) | 2026-11-05T12:12:36Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121220-doc-open.json](evidence/2026-11-05-121220-doc-open.json) | 2026-11-05T12:12:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121205-plugin-get.json](evidence/2026-11-05-121205-plugin-get.json) | 2026-11-05T12:12:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121156-plugin-remove.json](evidence/2026-11-05-121156-plugin-remove.json) | 2026-11-05T12:11:56Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-121148-plugin-install.json](evidence/2026-11-05-121148-plugin-install.json) | 2026-11-05T12:11:48Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-121140-plugin-get.json](evidence/2026-11-05-121140-plugin-get.json) | 2026-11-05T12:11:40Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-121133-doc-get.json](evidence/2026-11-05-121133-doc-get.json) | 2026-11-05T12:11:33Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121126-doc-list.json](evidence/2026-11-05-121126-doc-list.json) | 2026-11-05T12:11:26Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121117-session-get.json](evidence/2026-11-05-121117-session-get.json) | 2026-11-05T12:11:17Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-121111-session-list.json](evidence/2026-11-05-121111-session-list.json) | 2026-11-05T12:11:11Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-121104-relation-list.json](evidence/2026-11-05-121104-relation-list.json) | 2026-11-05T12:11:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121055-model-render.json](evidence/2026-11-05-121055-model-render.json) | 2026-11-05T12:10:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-121046-component-list.json](evidence/2026-11-05-121046-component-list.json) | 2026-11-05T12:10:46Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-121011-doc-open.json](evidence/2026-11-05-121011-doc-open.json) | 2026-11-05T12:10:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-120953-relation-list.json](evidence/2026-11-05-120953-relation-list.json) | 2026-11-05T12:09:53Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-120946-distance-get.json](evidence/2026-11-05-120946-distance-get.json) | 2026-11-05T12:09:46Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-120939-feature-get.json](evidence/2026-11-05-120939-feature-get.json) | 2026-11-05T12:09:39Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-120926-material-list.json](evidence/2026-11-05-120926-material-list.json) | 2026-11-05T12:09:26Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-120914-parameter-list.json](evidence/2026-11-05-120914-parameter-list.json) | 2026-11-05T12:09:14Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-120902-dimension-list.json](evidence/2026-11-05-120902-dimension-list.json) | 2026-11-05T12:09:02Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-120844-geometry-list.json](evidence/2026-11-05-120844-geometry-list.json) | 2026-11-05T12:08:44Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-120833-feature-list.json](evidence/2026-11-05-120833-feature-list.json) | 2026-11-05T12:08:33Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-120824-model-get.json](evidence/2026-11-05-120824-model-get.json) | 2026-11-05T12:08:24Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-120805-doc-open.json](evidence/2026-11-05-120805-doc-open.json) | 2026-11-05T12:08:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-120743-doc-list.json](evidence/2026-11-05-120743-doc-list.json) | 2026-11-05T12:07:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
<!-- driver:evidence:end -->
