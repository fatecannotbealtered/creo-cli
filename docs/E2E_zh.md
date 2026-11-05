# 真实软件验收

[English](E2E.md) | 中文

真实软件运行用真实的适配层，在真实的 Creo Parametric 上执行 creo-cli 的行为矩阵。它会做出真实的修改，所以只使用人在下面授权过的目标。

## 授权目标

真实软件运行可以使用的 Creo Parametric 实例、文件、文件夹和设备，唯一的清单在英文版 `docs/E2E.md` 的「Authorized Targets」一节；检查脚本和矩阵运行器只读那一份，本节不另列目标。只有人能往清单里加目标，编程 Agent 从不添加。每个目标占一个列表项，以反引号括起的目标开头，写法与授权范围文件里的目标相同：文件或文件夹的 `file://` URL，或者设备的 `device:<id>`；后面跟一个冒号和对目标的说明。Creo Parametric 的实例没有固定的 ID，所以真实软件运行只使用人为这次运行启动的实例，打开的文档也只来自这里列出的文件和文件夹。真实软件运行不使用任何其他目标，真实软件运行所用的授权范围文件也只授予这里列出的目标。

清单以 `docs/E2E.md` 为准。

## 步骤

真实软件运行使用这些电脑：

一台 Windows 11 x64 电脑，装有 Creo Parametric 13.4.1.0、它的 Object TOOLKIT Java 和 JDK 25，用会话模式。真实软件运行使用自己的状态目录（`CREO_CLI_STATE_DIR`）。第一次运行前，用这个状态目录运行 `creo-cli plugin install`，由人在为这次运行启动的 Creo 所用的 `config.pro` 里加一行 `toolkit_registry_file <状态目录>\plugin\protk.dat`，再启动 Creo；`creo-cli session list` 必须显示 `plugin_loaded`。

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
| [2026-11-05-114618-doc-save.json](evidence/2026-11-05-114618-doc-save.json) | 2026-11-05T11:46:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114612-doc-get.json](evidence/2026-11-05-114612-doc-get.json) | 2026-11-05T11:46:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114604-doc-close.json](evidence/2026-11-05-114604-doc-close.json) | 2026-11-05T11:46:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114226-session-get.json](evidence/2026-11-05-114226-session-get.json) | 2026-11-05T11:42:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114217-relation-list.json](evidence/2026-11-05-114217-relation-list.json) | 2026-11-05T11:42:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114208-parameter-update.json](evidence/2026-11-05-114208-parameter-update.json) | 2026-11-05T11:42:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114156-parameter-list.json](evidence/2026-11-05-114156-parameter-list.json) | 2026-11-05T11:41:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114145-model-render.json](evidence/2026-11-05-114145-model-render.json) | 2026-11-05T11:41:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114138-model-get.json](evidence/2026-11-05-114138-model-get.json) | 2026-11-05T11:41:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114131-model-export.json](evidence/2026-11-05-114131-model-export.json) | 2026-11-05T11:41:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114124-material-list.json](evidence/2026-11-05-114124-material-list.json) | 2026-11-05T11:41:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114117-geometry-list.json](evidence/2026-11-05-114117-geometry-list.json) | 2026-11-05T11:41:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114111-feature-update.json](evidence/2026-11-05-114111-feature-update.json) | 2026-11-05T11:41:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114105-feature-list.json](evidence/2026-11-05-114105-feature-list.json) | 2026-11-05T11:41:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114100-feature-get.json](evidence/2026-11-05-114100-feature-get.json) | 2026-11-05T11:41:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114056-doc-save.json](evidence/2026-11-05-114056-doc-save.json) | 2026-11-05T11:40:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-114052-doc-open.json](evidence/2026-11-05-114052-doc-open.json) | 2026-11-05T11:40:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114048-doc-get.json](evidence/2026-11-05-114048-doc-get.json) | 2026-11-05T11:40:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-114044-doc-close.json](evidence/2026-11-05-114044-doc-close.json) | 2026-11-05T11:40:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-114040-distance-get.json](evidence/2026-11-05-114040-distance-get.json) | 2026-11-05T11:40:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114037-dimension-update.json](evidence/2026-11-05-114037-dimension-update.json) | 2026-11-05T11:40:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114033-dimension-list.json](evidence/2026-11-05-114033-dimension-list.json) | 2026-11-05T11:40:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-114030-component-list.json](evidence/2026-11-05-114030-component-list.json) | 2026-11-05T11:40:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113936-relation-list.json](evidence/2026-11-05-113936-relation-list.json) | 2026-11-05T11:39:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113934-parameter-update.json](evidence/2026-11-05-113934-parameter-update.json) | 2026-11-05T11:39:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113933-parameter-list.json](evidence/2026-11-05-113933-parameter-list.json) | 2026-11-05T11:39:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113931-model-render.json](evidence/2026-11-05-113931-model-render.json) | 2026-11-05T11:39:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113930-model-get.json](evidence/2026-11-05-113930-model-get.json) | 2026-11-05T11:39:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113928-model-export.json](evidence/2026-11-05-113928-model-export.json) | 2026-11-05T11:39:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113926-material-list.json](evidence/2026-11-05-113926-material-list.json) | 2026-11-05T11:39:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113924-geometry-list.json](evidence/2026-11-05-113924-geometry-list.json) | 2026-11-05T11:39:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113922-feature-update.json](evidence/2026-11-05-113922-feature-update.json) | 2026-11-05T11:39:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113920-feature-list.json](evidence/2026-11-05-113920-feature-list.json) | 2026-11-05T11:39:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113917-feature-get.json](evidence/2026-11-05-113917-feature-get.json) | 2026-11-05T11:39:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113914-doc-save.json](evidence/2026-11-05-113914-doc-save.json) | 2026-11-05T11:39:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113912-doc-open.json](evidence/2026-11-05-113912-doc-open.json) | 2026-11-05T11:39:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113911-doc-close.json](evidence/2026-11-05-113911-doc-close.json) | 2026-11-05T11:39:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113909-distance-get.json](evidence/2026-11-05-113909-distance-get.json) | 2026-11-05T11:39:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113907-dimension-update.json](evidence/2026-11-05-113907-dimension-update.json) | 2026-11-05T11:39:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113905-dimension-list.json](evidence/2026-11-05-113905-dimension-list.json) | 2026-11-05T11:39:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113902-component-list.json](evidence/2026-11-05-113902-component-list.json) | 2026-11-05T11:39:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113206-relation-list.json](evidence/2026-11-05-113206-relation-list.json) | 2026-11-05T11:32:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113204-parameter-update.json](evidence/2026-11-05-113204-parameter-update.json) | 2026-11-05T11:32:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113202-parameter-list.json](evidence/2026-11-05-113202-parameter-list.json) | 2026-11-05T11:32:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113200-model-render.json](evidence/2026-11-05-113200-model-render.json) | 2026-11-05T11:32:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113158-model-export.json](evidence/2026-11-05-113158-model-export.json) | 2026-11-05T11:31:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113156-material-list.json](evidence/2026-11-05-113156-material-list.json) | 2026-11-05T11:31:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113154-geometry-list.json](evidence/2026-11-05-113154-geometry-list.json) | 2026-11-05T11:31:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113153-feature-update.json](evidence/2026-11-05-113153-feature-update.json) | 2026-11-05T11:31:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113151-feature-get.json](evidence/2026-11-05-113151-feature-get.json) | 2026-11-05T11:31:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113149-doc-save.json](evidence/2026-11-05-113149-doc-save.json) | 2026-11-05T11:31:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113147-doc-open.json](evidence/2026-11-05-113147-doc-open.json) | 2026-11-05T11:31:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113145-doc-close.json](evidence/2026-11-05-113145-doc-close.json) | 2026-11-05T11:31:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113143-distance-get.json](evidence/2026-11-05-113143-distance-get.json) | 2026-11-05T11:31:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113141-dimension-update.json](evidence/2026-11-05-113141-dimension-update.json) | 2026-11-05T11:31:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113139-dimension-list.json](evidence/2026-11-05-113139-dimension-list.json) | 2026-11-05T11:31:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113137-component-list.json](evidence/2026-11-05-113137-component-list.json) | 2026-11-05T11:31:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113108-feature-list.json](evidence/2026-11-05-113108-feature-list.json) | 2026-11-05T11:31:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113106-model-get.json](evidence/2026-11-05-113106-model-get.json) | 2026-11-05T11:31:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-113025-dimension-list.json](evidence/2026-11-05-113025-dimension-list.json) | 2026-11-05T11:30:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-113021-feature-list.json](evidence/2026-11-05-113021-feature-list.json) | 2026-11-05T11:30:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-113017-model-get.json](evidence/2026-11-05-113017-model-get.json) | 2026-11-05T11:30:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-112812-dimension-list.json](evidence/2026-11-05-112812-dimension-list.json) | 2026-11-05T11:28:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-112809-feature-list.json](evidence/2026-11-05-112809-feature-list.json) | 2026-11-05T11:28:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-112805-model-get.json](evidence/2026-11-05-112805-model-get.json) | 2026-11-05T11:28:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-112713-doc-open.json](evidence/2026-11-05-112713-doc-open.json) | 2026-11-05T11:27:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-112705-dimension-update.json](evidence/2026-11-05-112705-dimension-update.json) | 2026-11-05T11:27:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111632-plugin-remove.json](evidence/2026-11-05-111632-plugin-remove.json) | 2026-11-05T11:16:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111629-plugin-install.json](evidence/2026-11-05-111629-plugin-install.json) | 2026-11-05T11:16:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111307-model-export.json](evidence/2026-11-05-111307-model-export.json) | 2026-11-05T11:13:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111305-doc-save.json](evidence/2026-11-05-111305-doc-save.json) | 2026-11-05T11:13:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111119-plugin-get.json](evidence/2026-11-05-111119-plugin-get.json) | 2026-11-05T11:11:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111117-plugin-remove.json](evidence/2026-11-05-111117-plugin-remove.json) | 2026-11-05T11:11:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111115-plugin-install.json](evidence/2026-11-05-111115-plugin-install.json) | 2026-11-05T11:11:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111112-model-export.json](evidence/2026-11-05-111112-model-export.json) | 2026-11-05T11:11:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-111108-doc-save.json](evidence/2026-11-05-111108-doc-save.json) | 2026-11-05T11:11:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-111105-doc-save.json](evidence/2026-11-05-111105-doc-save.json) | 2026-11-05T11:11:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111102-doc-save.json](evidence/2026-11-05-111102-doc-save.json) | 2026-11-05T11:11:02Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-111042-model-render.json](evidence/2026-11-05-111042-model-render.json) | 2026-11-05T11:10:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111037-model-render.json](evidence/2026-11-05-111037-model-render.json) | 2026-11-05T11:10:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-111031-model-render.json](evidence/2026-11-05-111031-model-render.json) | 2026-11-05T11:10:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110623-component-list.json](evidence/2026-11-05-110623-component-list.json) | 2026-11-05T11:06:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110620-model-render.json](evidence/2026-11-05-110620-model-render.json) | 2026-11-05T11:06:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-110617-model-render.json](evidence/2026-11-05-110617-model-render.json) | 2026-11-05T11:06:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-110613-model-render.json](evidence/2026-11-05-110613-model-render.json) | 2026-11-05T11:06:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-110611-doc-get.json](evidence/2026-11-05-110611-doc-get.json) | 2026-11-05T11:06:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110609-doc-open.json](evidence/2026-11-05-110609-doc-open.json) | 2026-11-05T11:06:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110607-doc-open.json](evidence/2026-11-05-110607-doc-open.json) | 2026-11-05T11:06:07Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-110602-doc-close.json](evidence/2026-11-05-110602-doc-close.json) | 2026-11-05T11:06:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110127-model-export.json](evidence/2026-11-05-110127-model-export.json) | 2026-11-05T11:01:27Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-110124-model-render.json](evidence/2026-11-05-110124-model-render.json) | 2026-11-05T11:01:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-110122-model-render.json](evidence/2026-11-05-110122-model-render.json) | 2026-11-05T11:01:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-110120-model-render.json](evidence/2026-11-05-110120-model-render.json) | 2026-11-05T11:01:20Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 2 次通过 |
| [2026-11-05-110117-doc-open.json](evidence/2026-11-05-110117-doc-open.json) | 2026-11-05T11:01:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-110115-doc-open.json](evidence/2026-11-05-110115-doc-open.json) | 2026-11-05T11:01:15Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 2 次通过 |
| [2026-11-05-110113-doc-close.json](evidence/2026-11-05-110113-doc-close.json) | 2026-11-05T11:01:13Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 2 次通过 |
| [2026-11-05-110110-doc-close.json](evidence/2026-11-05-110110-doc-close.json) | 2026-11-05T11:01:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-105832-model-render.json](evidence/2026-11-05-105832-model-render.json) | 2026-11-05T10:58:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-105737-model-render.json](evidence/2026-11-05-105737-model-render.json) | 2026-11-05T10:57:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-104111-model-export.json](evidence/2026-11-05-104111-model-export.json) | 2026-11-05T10:41:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104109-doc-open.json](evidence/2026-11-05-104109-doc-open.json) | 2026-11-05T10:41:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104107-plugin-remove.json](evidence/2026-11-05-104107-plugin-remove.json) | 2026-11-05T10:41:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104104-plugin-install.json](evidence/2026-11-05-104104-plugin-install.json) | 2026-11-05T10:41:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104103-doc-save.json](evidence/2026-11-05-104103-doc-save.json) | 2026-11-05T10:41:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104101-doc-close.json](evidence/2026-11-05-104101-doc-close.json) | 2026-11-05T10:41:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 0 次通过 |
| [2026-11-05-104059-feature-update.json](evidence/2026-11-05-104059-feature-update.json) | 2026-11-05T10:40:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104056-parameter-update.json](evidence/2026-11-05-104056-parameter-update.json) | 2026-11-05T10:40:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104054-dimension-update.json](evidence/2026-11-05-104054-dimension-update.json) | 2026-11-05T10:40:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104040-model-export.json](evidence/2026-11-05-104040-model-export.json) | 2026-11-05T10:40:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104038-relation-list.json](evidence/2026-11-05-104038-relation-list.json) | 2026-11-05T10:40:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104036-parameter-update.json](evidence/2026-11-05-104036-parameter-update.json) | 2026-11-05T10:40:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104033-parameter-list.json](evidence/2026-11-05-104033-parameter-list.json) | 2026-11-05T10:40:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104031-model-get.json](evidence/2026-11-05-104031-model-get.json) | 2026-11-05T10:40:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104029-material-list.json](evidence/2026-11-05-104029-material-list.json) | 2026-11-05T10:40:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104027-geometry-list.json](evidence/2026-11-05-104027-geometry-list.json) | 2026-11-05T10:40:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104025-feature-update.json](evidence/2026-11-05-104025-feature-update.json) | 2026-11-05T10:40:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104023-feature-list.json](evidence/2026-11-05-104023-feature-list.json) | 2026-11-05T10:40:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104021-feature-get.json](evidence/2026-11-05-104021-feature-get.json) | 2026-11-05T10:40:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104019-doc-close.json](evidence/2026-11-05-104019-doc-close.json) | 2026-11-05T10:40:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104017-doc-save.json](evidence/2026-11-05-104017-doc-save.json) | 2026-11-05T10:40:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104015-doc-list.json](evidence/2026-11-05-104015-doc-list.json) | 2026-11-05T10:40:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104013-doc-get.json](evidence/2026-11-05-104013-doc-get.json) | 2026-11-05T10:40:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104011-distance-get.json](evidence/2026-11-05-104011-distance-get.json) | 2026-11-05T10:40:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104009-dimension-update.json](evidence/2026-11-05-104009-dimension-update.json) | 2026-11-05T10:40:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-104005-dimension-list.json](evidence/2026-11-05-104005-dimension-list.json) | 2026-11-05T10:40:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-103856-feature-update.json](evidence/2026-11-05-103856-feature-update.json) | 2026-11-05T10:38:56Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-103850-parameter-update.json](evidence/2026-11-05-103850-parameter-update.json) | 2026-11-05T10:38:50Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-103845-dimension-update.json](evidence/2026-11-05-103845-dimension-update.json) | 2026-11-05T10:38:45Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-103824-doc-get.json](evidence/2026-11-05-103824-doc-get.json) | 2026-11-05T10:38:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-103758-plugin-get.json](evidence/2026-11-05-103758-plugin-get.json) | 2026-11-05T10:37:58Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-103756-doc-get.json](evidence/2026-11-05-103756-doc-get.json) | 2026-11-05T10:37:56Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 2 次通过 |
| [2026-11-05-103753-doc-list.json](evidence/2026-11-05-103753-doc-list.json) | 2026-11-05T10:37:53Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-103751-session-get.json](evidence/2026-11-05-103751-session-get.json) | 2026-11-05T10:37:51Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-103749-session-list.json](evidence/2026-11-05-103749-session-list.json) | 2026-11-05T10:37:49Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-103737-component-list.json](evidence/2026-11-05-103737-component-list.json) | 2026-11-05T10:37:37Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103734-material-list.json](evidence/2026-11-05-103734-material-list.json) | 2026-11-05T10:37:34Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103731-relation-list.json](evidence/2026-11-05-103731-relation-list.json) | 2026-11-05T10:37:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-103729-relation-list.json](evidence/2026-11-05-103729-relation-list.json) | 2026-11-05T10:37:29Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-103726-parameter-list.json](evidence/2026-11-05-103726-parameter-list.json) | 2026-11-05T10:37:26Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103723-dimension-list.json](evidence/2026-11-05-103723-dimension-list.json) | 2026-11-05T10:37:23Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103719-distance-get.json](evidence/2026-11-05-103719-distance-get.json) | 2026-11-05T10:37:19Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-103716-geometry-list.json](evidence/2026-11-05-103716-geometry-list.json) | 2026-11-05T10:37:16Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103713-feature-get.json](evidence/2026-11-05-103713-feature-get.json) | 2026-11-05T10:37:13Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-103710-feature-list.json](evidence/2026-11-05-103710-feature-list.json) | 2026-11-05T10:37:10Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-103621-model-get.json](evidence/2026-11-05-103621-model-get.json) | 2026-11-05T10:36:21Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
<!-- driver:evidence:end -->
