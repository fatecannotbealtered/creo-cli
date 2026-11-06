# 真实软件验收

[English](E2E.md) | 中文

真实软件运行用真实的适配层，在真实的 Creo Parametric 上执行 creo-cli 的行为矩阵。它会做出真实的修改，所以只使用人在下面授权过的目标。

## 授权目标

真实软件运行可以使用的 Creo Parametric 实例、文件、文件夹和设备，唯一的清单在英文版 `docs/E2E.md` 的「Authorized Targets」一节；检查脚本和矩阵运行器只读那一份，本节不另列目标。只有人能往清单里加目标，或者由人在自己发的消息里明确委托的编码 Agent 加入：它先把目标给人看，人同意后再加。每个目标占一个列表项，以反引号括起的目标开头，写法与授权范围文件里的目标相同：文件或文件夹的 `file://` URL，或者设备的 `device:<id>`；后面跟一个冒号和对目标的说明。Creo Parametric 的实例没有固定的 ID，所以真实软件运行只使用人为这次运行启动的实例，打开的文档也只来自这里列出的文件和文件夹。真实软件运行不使用任何其他目标，真实软件运行所用的授权范围文件也只授予这里列出的目标。

清单以 `docs/E2E.md` 为准。

## 步骤

真实软件运行使用这些电脑：

一台 Windows 11 x64 电脑，装有 Creo Parametric 13.4.1.0、它的 Object TOOLKIT Java 和 JDK 25，用会话模式。真实软件运行使用自己的状态目录（`CREO_CLI_STATE_DIR`）。第一次运行前，用这个状态目录运行 `creo-cli plugin install`，由人在为这次运行启动的 Creo 所用的 `config.pro` 里加一行 `toolkit_registry_file <install_path>\protk.dat`（`install_path` 见 `creo-cli plugin get` 的输出），再启动 Creo；`creo-cli session list` 必须显示 `plugin_loaded`。真实软件运行时，给 creo-cli 把 `LOCALAPPDATA` 设到专用的文件夹，这样它们装的宿主组件以及 `plugin install`、`plugin remove` 那几行都不碰人自己的那份。这几行用另一个状态目录，它的宿主组件没有被任何运行中的 Creo 加载：Windows 会一直占着已加载的 JAR，删不掉。`read_back_mismatch` 行用 `--tamper` 改掉结果：一个脚本经宿主组件重新设置尺寸、参数或特征名，把模型重新关闭或打开，或者删掉写命令生成的文件、保存写出的版本文件。

在真实的 Creo Parametric 上运行行为矩阵：

1. 由人准备目标，比如专为测试复制的项目、为这次运行启动的实例，或为测试准备好的设备，并把它们列进「授权目标」。
2. 由人写（或明确委托编码 Agent 写）一个只授予这些目标的授权范围文件，包含被测命令需要的效果，并让 `CREO_CLI_SCOPE_FILE` 指向它。把 `CREO_CLI_STATE_DIR` 设为专供真实软件运行使用的目录。
3. 运行 `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>`，矩阵用到的每个占位符各给一个 `--set`，占位符名不带花括号，如 `--set doc=<file>`：`{session}` 是授权的实例，`{doc}` 是授权的文档或文件，`{device}` 是授权的设备，`{dir}` 是授权文件夹里新建的空目录。`{job}` 是作业 ID；不给时，运行器先运行 `--job-from` 指定的长命令（只有一个长命令时就是它）的 `normal` 行，用它启动的作业。`{inputs}` 不用 `--set`：它就是 `tests/inputs/`，里面的文件命令只读取，所以不需要授权。
4. 运行器执行适用的行，把真实软件记录写进 `docs/evidence/`，并填上每一行的实际结果和 `live:` 证据引用。实际结果与预期不符的行算作失败。
5. 在真实的 Creo Parametric 上无法按需制造的行，如 `disconnect`，可以标为 `unrunnable` 并写明原因；`normal`、`dialog` 和 `read_back_mismatch` 这三行不可以。`read_back_mismatch` 用 `--row read_back_mismatch` 运行：工具会在读回之前等一会儿，在这段时间里，到 Creo Parametric 里改掉它刚写的内容，或删掉它生成的文件。
6. 运行 `python scripts/spec.py generate` 更新支持矩阵和下面的索引，再把记录和矩阵一起提交。

要在真实的 Creo Parametric 上运行评测题，由人在「授权目标」里列出一个放评测工作目录的文件夹，以及题目的 `SCOPE` 用到的其他目标，比如设备。然后运行 `python scripts/spec.py eval --workspace-root <folder>`。运行器自己为每道题写授权范围文件，只授予这道题的文档和它的 `SCOPE` 列出的目标，并把评测报告写进 `docs/evidence/`。

真实软件记录只在它记录的工具版本与 creo-cli 的主版本和次版本都相同时才算作证据。记录里从不出现机密，带机密的参数显示为 `***`。

## 证据记录

`docs/evidence/` 里的真实软件记录，由 `python scripts/spec.py generate` 生成：

<!-- driver:evidence:start -->
| 记录 | 运行时间 | 软件 | 平台 | 结果 |
|---|---|---|---|---|
| [2026-11-06-163428-component-list.json](evidence/2026-11-06-163428-component-list.json) | 2026-11-06T16:34:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163253-session-list.json](evidence/2026-11-06-163253-session-list.json) | 2026-11-06T16:32:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163248-session-get.json](evidence/2026-11-06-163248-session-get.json) | 2026-11-06T16:32:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163246-relation-list.json](evidence/2026-11-06-163246-relation-list.json) | 2026-11-06T16:32:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163245-parameter-update.json](evidence/2026-11-06-163245-parameter-update.json) | 2026-11-06T16:32:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163243-parameter-list.json](evidence/2026-11-06-163243-parameter-list.json) | 2026-11-06T16:32:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163242-model-render.json](evidence/2026-11-06-163242-model-render.json) | 2026-11-06T16:32:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163240-model-get.json](evidence/2026-11-06-163240-model-get.json) | 2026-11-06T16:32:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163239-model-export.json](evidence/2026-11-06-163239-model-export.json) | 2026-11-06T16:32:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163238-material-list.json](evidence/2026-11-06-163238-material-list.json) | 2026-11-06T16:32:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163237-geometry-list.json](evidence/2026-11-06-163237-geometry-list.json) | 2026-11-06T16:32:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163236-feature-update.json](evidence/2026-11-06-163236-feature-update.json) | 2026-11-06T16:32:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163235-feature-list.json](evidence/2026-11-06-163235-feature-list.json) | 2026-11-06T16:32:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163233-feature-get.json](evidence/2026-11-06-163233-feature-get.json) | 2026-11-06T16:32:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163232-doc-save.json](evidence/2026-11-06-163232-doc-save.json) | 2026-11-06T16:32:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163231-doc-open.json](evidence/2026-11-06-163231-doc-open.json) | 2026-11-06T16:32:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163230-doc-get.json](evidence/2026-11-06-163230-doc-get.json) | 2026-11-06T16:32:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163229-doc-close.json](evidence/2026-11-06-163229-doc-close.json) | 2026-11-06T16:32:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163227-distance-get.json](evidence/2026-11-06-163227-distance-get.json) | 2026-11-06T16:32:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163226-dimension-update.json](evidence/2026-11-06-163226-dimension-update.json) | 2026-11-06T16:32:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163224-dimension-list.json](evidence/2026-11-06-163224-dimension-list.json) | 2026-11-06T16:32:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163159-relation-list.json](evidence/2026-11-06-163159-relation-list.json) | 2026-11-06T16:31:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163158-parameter-update.json](evidence/2026-11-06-163158-parameter-update.json) | 2026-11-06T16:31:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163157-parameter-list.json](evidence/2026-11-06-163157-parameter-list.json) | 2026-11-06T16:31:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163156-model-render.json](evidence/2026-11-06-163156-model-render.json) | 2026-11-06T16:31:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163154-model-get.json](evidence/2026-11-06-163154-model-get.json) | 2026-11-06T16:31:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163153-model-export.json](evidence/2026-11-06-163153-model-export.json) | 2026-11-06T16:31:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163152-material-list.json](evidence/2026-11-06-163152-material-list.json) | 2026-11-06T16:31:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163151-geometry-list.json](evidence/2026-11-06-163151-geometry-list.json) | 2026-11-06T16:31:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163150-feature-update.json](evidence/2026-11-06-163150-feature-update.json) | 2026-11-06T16:31:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163148-feature-list.json](evidence/2026-11-06-163148-feature-list.json) | 2026-11-06T16:31:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163147-feature-get.json](evidence/2026-11-06-163147-feature-get.json) | 2026-11-06T16:31:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163146-doc-save.json](evidence/2026-11-06-163146-doc-save.json) | 2026-11-06T16:31:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163145-doc-open.json](evidence/2026-11-06-163145-doc-open.json) | 2026-11-06T16:31:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163144-doc-close.json](evidence/2026-11-06-163144-doc-close.json) | 2026-11-06T16:31:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163142-distance-get.json](evidence/2026-11-06-163142-distance-get.json) | 2026-11-06T16:31:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163141-dimension-update.json](evidence/2026-11-06-163141-dimension-update.json) | 2026-11-06T16:31:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163140-dimension-list.json](evidence/2026-11-06-163140-dimension-list.json) | 2026-11-06T16:31:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163139-component-list.json](evidence/2026-11-06-163139-component-list.json) | 2026-11-06T16:31:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163137-relation-list.json](evidence/2026-11-06-163137-relation-list.json) | 2026-11-06T16:31:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163135-parameter-update.json](evidence/2026-11-06-163135-parameter-update.json) | 2026-11-06T16:31:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163132-parameter-list.json](evidence/2026-11-06-163132-parameter-list.json) | 2026-11-06T16:31:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163130-model-render.json](evidence/2026-11-06-163130-model-render.json) | 2026-11-06T16:31:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163128-model-get.json](evidence/2026-11-06-163128-model-get.json) | 2026-11-06T16:31:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163125-model-export.json](evidence/2026-11-06-163125-model-export.json) | 2026-11-06T16:31:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163123-material-list.json](evidence/2026-11-06-163123-material-list.json) | 2026-11-06T16:31:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163120-geometry-list.json](evidence/2026-11-06-163120-geometry-list.json) | 2026-11-06T16:31:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163117-feature-update.json](evidence/2026-11-06-163117-feature-update.json) | 2026-11-06T16:31:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163115-feature-list.json](evidence/2026-11-06-163115-feature-list.json) | 2026-11-06T16:31:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163112-feature-get.json](evidence/2026-11-06-163112-feature-get.json) | 2026-11-06T16:31:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163109-doc-save.json](evidence/2026-11-06-163109-doc-save.json) | 2026-11-06T16:31:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163107-doc-open.json](evidence/2026-11-06-163107-doc-open.json) | 2026-11-06T16:31:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163104-doc-close.json](evidence/2026-11-06-163104-doc-close.json) | 2026-11-06T16:31:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163101-distance-get.json](evidence/2026-11-06-163101-distance-get.json) | 2026-11-06T16:31:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163059-dimension-update.json](evidence/2026-11-06-163059-dimension-update.json) | 2026-11-06T16:30:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163056-dimension-list.json](evidence/2026-11-06-163056-dimension-list.json) | 2026-11-06T16:30:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163054-component-list.json](evidence/2026-11-06-163054-component-list.json) | 2026-11-06T16:30:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163049-component-list.json](evidence/2026-11-06-163049-component-list.json) | 2026-11-06T16:30:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163047-doc-save.json](evidence/2026-11-06-163047-doc-save.json) | 2026-11-06T16:30:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163039-feature-update.json](evidence/2026-11-06-163039-feature-update.json) | 2026-11-06T16:30:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163036-parameter-update.json](evidence/2026-11-06-163036-parameter-update.json) | 2026-11-06T16:30:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163032-dimension-update.json](evidence/2026-11-06-163032-dimension-update.json) | 2026-11-06T16:30:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163029-model-render.json](evidence/2026-11-06-163029-model-render.json) | 2026-11-06T16:30:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163028-model-export.json](evidence/2026-11-06-163028-model-export.json) | 2026-11-06T16:30:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163027-doc-close.json](evidence/2026-11-06-163027-doc-close.json) | 2026-11-06T16:30:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163025-doc-open.json](evidence/2026-11-06-163025-doc-open.json) | 2026-11-06T16:30:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163024-plugin-remove.json](evidence/2026-11-06-163024-plugin-remove.json) | 2026-11-06T16:30:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163023-plugin-install.json](evidence/2026-11-06-163023-plugin-install.json) | 2026-11-06T16:30:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163022-doc-save.json](evidence/2026-11-06-163022-doc-save.json) | 2026-11-06T16:30:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163020-feature-update.json](evidence/2026-11-06-163020-feature-update.json) | 2026-11-06T16:30:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163018-parameter-update.json](evidence/2026-11-06-163018-parameter-update.json) | 2026-11-06T16:30:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163015-dimension-update.json](evidence/2026-11-06-163015-dimension-update.json) | 2026-11-06T16:30:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163012-model-export.json](evidence/2026-11-06-163012-model-export.json) | 2026-11-06T16:30:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163011-doc-save.json](evidence/2026-11-06-163011-doc-save.json) | 2026-11-06T16:30:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163009-doc-save.json](evidence/2026-11-06-163009-doc-save.json) | 2026-11-06T16:30:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-163004-doc-save.json](evidence/2026-11-06-163004-doc-save.json) | 2026-11-06T16:30:04Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162957-doc-save.json](evidence/2026-11-06-162957-doc-save.json) | 2026-11-06T16:29:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162953-model-render.json](evidence/2026-11-06-162953-model-render.json) | 2026-11-06T16:29:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162950-model-export.json](evidence/2026-11-06-162950-model-export.json) | 2026-11-06T16:29:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162947-relation-list.json](evidence/2026-11-06-162947-relation-list.json) | 2026-11-06T16:29:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162946-parameter-update.json](evidence/2026-11-06-162946-parameter-update.json) | 2026-11-06T16:29:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162943-parameter-list.json](evidence/2026-11-06-162943-parameter-list.json) | 2026-11-06T16:29:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162942-model-get.json](evidence/2026-11-06-162942-model-get.json) | 2026-11-06T16:29:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162940-material-list.json](evidence/2026-11-06-162940-material-list.json) | 2026-11-06T16:29:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162939-geometry-list.json](evidence/2026-11-06-162939-geometry-list.json) | 2026-11-06T16:29:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162938-feature-update.json](evidence/2026-11-06-162938-feature-update.json) | 2026-11-06T16:29:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162936-feature-list.json](evidence/2026-11-06-162936-feature-list.json) | 2026-11-06T16:29:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162934-feature-get.json](evidence/2026-11-06-162934-feature-get.json) | 2026-11-06T16:29:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162933-doc-close.json](evidence/2026-11-06-162933-doc-close.json) | 2026-11-06T16:29:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162932-doc-list.json](evidence/2026-11-06-162932-doc-list.json) | 2026-11-06T16:29:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162930-doc-get.json](evidence/2026-11-06-162930-doc-get.json) | 2026-11-06T16:29:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162928-distance-get.json](evidence/2026-11-06-162928-distance-get.json) | 2026-11-06T16:29:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162925-dimension-update.json](evidence/2026-11-06-162925-dimension-update.json) | 2026-11-06T16:29:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162922-dimension-list.json](evidence/2026-11-06-162922-dimension-list.json) | 2026-11-06T16:29:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162919-feature-update.json](evidence/2026-11-06-162919-feature-update.json) | 2026-11-06T16:29:19Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-06-162914-parameter-update.json](evidence/2026-11-06-162914-parameter-update.json) | 2026-11-06T16:29:14Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-06-162907-dimension-update.json](evidence/2026-11-06-162907-dimension-update.json) | 2026-11-06T16:29:07Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-06-162902-doc-close.json](evidence/2026-11-06-162902-doc-close.json) | 2026-11-06T16:29:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162856-doc-close.json](evidence/2026-11-06-162856-doc-close.json) | 2026-11-06T16:28:56Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162850-model-render.json](evidence/2026-11-06-162850-model-render.json) | 2026-11-06T16:28:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162847-model-export.json](evidence/2026-11-06-162847-model-export.json) | 2026-11-06T16:28:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162843-model-render.json](evidence/2026-11-06-162843-model-render.json) | 2026-11-06T16:28:43Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162840-model-export.json](evidence/2026-11-06-162840-model-export.json) | 2026-11-06T16:28:40Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162836-doc-open.json](evidence/2026-11-06-162836-doc-open.json) | 2026-11-06T16:28:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162834-doc-open.json](evidence/2026-11-06-162834-doc-open.json) | 2026-11-06T16:28:34Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-06-162832-plugin-get.json](evidence/2026-11-06-162832-plugin-get.json) | 2026-11-06T16:28:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162830-plugin-remove.json](evidence/2026-11-06-162830-plugin-remove.json) | 2026-11-06T16:28:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162828-plugin-remove.json](evidence/2026-11-06-162828-plugin-remove.json) | 2026-11-06T16:28:28Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-06-162826-plugin-install.json](evidence/2026-11-06-162826-plugin-install.json) | 2026-11-06T16:28:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162822-plugin-install.json](evidence/2026-11-06-162822-plugin-install.json) | 2026-11-06T16:28:22Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-06-162816-plugin-get.json](evidence/2026-11-06-162816-plugin-get.json) | 2026-11-06T16:28:16Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-06-162815-doc-get.json](evidence/2026-11-06-162815-doc-get.json) | 2026-11-06T16:28:15Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162814-doc-list.json](evidence/2026-11-06-162814-doc-list.json) | 2026-11-06T16:28:14Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162812-session-get.json](evidence/2026-11-06-162812-session-get.json) | 2026-11-06T16:28:12Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162811-session-list.json](evidence/2026-11-06-162811-session-list.json) | 2026-11-06T16:28:11Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-06-162810-doc-close.json](evidence/2026-11-06-162810-doc-close.json) | 2026-11-06T16:28:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162808-relation-list.json](evidence/2026-11-06-162808-relation-list.json) | 2026-11-06T16:28:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162806-model-render.json](evidence/2026-11-06-162806-model-render.json) | 2026-11-06T16:28:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162805-model-render.json](evidence/2026-11-06-162805-model-render.json) | 2026-11-06T16:28:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162802-feature-update.json](evidence/2026-11-06-162802-feature-update.json) | 2026-11-06T16:28:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162759-dimension-update.json](evidence/2026-11-06-162759-dimension-update.json) | 2026-11-06T16:27:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162757-dimension-list.json](evidence/2026-11-06-162757-dimension-list.json) | 2026-11-06T16:27:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162755-distance-get.json](evidence/2026-11-06-162755-distance-get.json) | 2026-11-06T16:27:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162753-geometry-list.json](evidence/2026-11-06-162753-geometry-list.json) | 2026-11-06T16:27:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162752-feature-list.json](evidence/2026-11-06-162752-feature-list.json) | 2026-11-06T16:27:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162750-feature-get.json](evidence/2026-11-06-162750-feature-get.json) | 2026-11-06T16:27:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162748-component-list.json](evidence/2026-11-06-162748-component-list.json) | 2026-11-06T16:27:48Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162742-doc-open.json](evidence/2026-11-06-162742-doc-open.json) | 2026-11-06T16:27:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162738-relation-list.json](evidence/2026-11-06-162738-relation-list.json) | 2026-11-06T16:27:38Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162735-distance-get.json](evidence/2026-11-06-162735-distance-get.json) | 2026-11-06T16:27:35Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162732-feature-get.json](evidence/2026-11-06-162732-feature-get.json) | 2026-11-06T16:27:32Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162730-material-list.json](evidence/2026-11-06-162730-material-list.json) | 2026-11-06T16:27:30Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162727-parameter-list.json](evidence/2026-11-06-162727-parameter-list.json) | 2026-11-06T16:27:27Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162725-dimension-list.json](evidence/2026-11-06-162725-dimension-list.json) | 2026-11-06T16:27:25Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162721-geometry-list.json](evidence/2026-11-06-162721-geometry-list.json) | 2026-11-06T16:27:21Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162718-feature-list.json](evidence/2026-11-06-162718-feature-list.json) | 2026-11-06T16:27:18Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-06-162715-model-get.json](evidence/2026-11-06-162715-model-get.json) | 2026-11-06T16:27:15Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-06-162713-doc-open.json](evidence/2026-11-06-162713-doc-open.json) | 2026-11-06T16:27:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-06-162710-doc-list.json](evidence/2026-11-06-162710-doc-list.json) | 2026-11-06T16:27:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
<!-- driver:evidence:end -->
