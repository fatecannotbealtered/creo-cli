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
| [2026-11-05-131547-doc-open.json](evidence/2026-11-05-131547-doc-open.json) | 2026-11-05T13:15:47Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-131508-session-list.json](evidence/2026-11-05-131508-session-list.json) | 2026-11-05T13:15:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131502-session-get.json](evidence/2026-11-05-131502-session-get.json) | 2026-11-05T13:15:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131501-relation-list.json](evidence/2026-11-05-131501-relation-list.json) | 2026-11-05T13:15:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131500-parameter-update.json](evidence/2026-11-05-131500-parameter-update.json) | 2026-11-05T13:15:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131458-parameter-list.json](evidence/2026-11-05-131458-parameter-list.json) | 2026-11-05T13:14:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131457-model-render.json](evidence/2026-11-05-131457-model-render.json) | 2026-11-05T13:14:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131455-model-get.json](evidence/2026-11-05-131455-model-get.json) | 2026-11-05T13:14:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131454-model-export.json](evidence/2026-11-05-131454-model-export.json) | 2026-11-05T13:14:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131452-material-list.json](evidence/2026-11-05-131452-material-list.json) | 2026-11-05T13:14:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131451-geometry-list.json](evidence/2026-11-05-131451-geometry-list.json) | 2026-11-05T13:14:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131450-feature-update.json](evidence/2026-11-05-131450-feature-update.json) | 2026-11-05T13:14:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131448-feature-list.json](evidence/2026-11-05-131448-feature-list.json) | 2026-11-05T13:14:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131447-feature-get.json](evidence/2026-11-05-131447-feature-get.json) | 2026-11-05T13:14:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131446-doc-save.json](evidence/2026-11-05-131446-doc-save.json) | 2026-11-05T13:14:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131444-doc-open.json](evidence/2026-11-05-131444-doc-open.json) | 2026-11-05T13:14:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131443-doc-get.json](evidence/2026-11-05-131443-doc-get.json) | 2026-11-05T13:14:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131442-doc-close.json](evidence/2026-11-05-131442-doc-close.json) | 2026-11-05T13:14:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131441-distance-get.json](evidence/2026-11-05-131441-distance-get.json) | 2026-11-05T13:14:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131439-dimension-update.json](evidence/2026-11-05-131439-dimension-update.json) | 2026-11-05T13:14:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131438-dimension-list.json](evidence/2026-11-05-131438-dimension-list.json) | 2026-11-05T13:14:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131437-component-list.json](evidence/2026-11-05-131437-component-list.json) | 2026-11-05T13:14:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131416-relation-list.json](evidence/2026-11-05-131416-relation-list.json) | 2026-11-05T13:14:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131415-parameter-update.json](evidence/2026-11-05-131415-parameter-update.json) | 2026-11-05T13:14:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131414-parameter-list.json](evidence/2026-11-05-131414-parameter-list.json) | 2026-11-05T13:14:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131412-model-render.json](evidence/2026-11-05-131412-model-render.json) | 2026-11-05T13:14:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131411-model-get.json](evidence/2026-11-05-131411-model-get.json) | 2026-11-05T13:14:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131410-model-export.json](evidence/2026-11-05-131410-model-export.json) | 2026-11-05T13:14:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131409-material-list.json](evidence/2026-11-05-131409-material-list.json) | 2026-11-05T13:14:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131408-geometry-list.json](evidence/2026-11-05-131408-geometry-list.json) | 2026-11-05T13:14:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131407-feature-update.json](evidence/2026-11-05-131407-feature-update.json) | 2026-11-05T13:14:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131405-feature-list.json](evidence/2026-11-05-131405-feature-list.json) | 2026-11-05T13:14:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131404-feature-get.json](evidence/2026-11-05-131404-feature-get.json) | 2026-11-05T13:14:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131403-doc-save.json](evidence/2026-11-05-131403-doc-save.json) | 2026-11-05T13:14:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131402-doc-open.json](evidence/2026-11-05-131402-doc-open.json) | 2026-11-05T13:14:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131401-doc-close.json](evidence/2026-11-05-131401-doc-close.json) | 2026-11-05T13:14:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131359-distance-get.json](evidence/2026-11-05-131359-distance-get.json) | 2026-11-05T13:13:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131358-dimension-update.json](evidence/2026-11-05-131358-dimension-update.json) | 2026-11-05T13:13:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131357-dimension-list.json](evidence/2026-11-05-131357-dimension-list.json) | 2026-11-05T13:13:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131356-component-list.json](evidence/2026-11-05-131356-component-list.json) | 2026-11-05T13:13:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131354-relation-list.json](evidence/2026-11-05-131354-relation-list.json) | 2026-11-05T13:13:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131353-parameter-update.json](evidence/2026-11-05-131353-parameter-update.json) | 2026-11-05T13:13:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131351-parameter-list.json](evidence/2026-11-05-131351-parameter-list.json) | 2026-11-05T13:13:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131350-model-render.json](evidence/2026-11-05-131350-model-render.json) | 2026-11-05T13:13:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131349-model-get.json](evidence/2026-11-05-131349-model-get.json) | 2026-11-05T13:13:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131348-model-export.json](evidence/2026-11-05-131348-model-export.json) | 2026-11-05T13:13:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131347-material-list.json](evidence/2026-11-05-131347-material-list.json) | 2026-11-05T13:13:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131346-geometry-list.json](evidence/2026-11-05-131346-geometry-list.json) | 2026-11-05T13:13:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131344-feature-update.json](evidence/2026-11-05-131344-feature-update.json) | 2026-11-05T13:13:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131343-feature-list.json](evidence/2026-11-05-131343-feature-list.json) | 2026-11-05T13:13:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131342-feature-get.json](evidence/2026-11-05-131342-feature-get.json) | 2026-11-05T13:13:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131341-doc-save.json](evidence/2026-11-05-131341-doc-save.json) | 2026-11-05T13:13:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131339-doc-open.json](evidence/2026-11-05-131339-doc-open.json) | 2026-11-05T13:13:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131338-doc-close.json](evidence/2026-11-05-131338-doc-close.json) | 2026-11-05T13:13:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131337-distance-get.json](evidence/2026-11-05-131337-distance-get.json) | 2026-11-05T13:13:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131336-dimension-update.json](evidence/2026-11-05-131336-dimension-update.json) | 2026-11-05T13:13:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131335-dimension-list.json](evidence/2026-11-05-131335-dimension-list.json) | 2026-11-05T13:13:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131334-component-list.json](evidence/2026-11-05-131334-component-list.json) | 2026-11-05T13:13:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131331-component-list.json](evidence/2026-11-05-131331-component-list.json) | 2026-11-05T13:13:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131328-dimension-update.json](evidence/2026-11-05-131328-dimension-update.json) | 2026-11-05T13:13:28Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131326-model-render.json](evidence/2026-11-05-131326-model-render.json) | 2026-11-05T13:13:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131325-model-export.json](evidence/2026-11-05-131325-model-export.json) | 2026-11-05T13:13:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131323-doc-close.json](evidence/2026-11-05-131323-doc-close.json) | 2026-11-05T13:13:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131322-doc-open.json](evidence/2026-11-05-131322-doc-open.json) | 2026-11-05T13:13:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131321-plugin-remove.json](evidence/2026-11-05-131321-plugin-remove.json) | 2026-11-05T13:13:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131319-plugin-install.json](evidence/2026-11-05-131319-plugin-install.json) | 2026-11-05T13:13:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131318-doc-save.json](evidence/2026-11-05-131318-doc-save.json) | 2026-11-05T13:13:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131317-feature-update.json](evidence/2026-11-05-131317-feature-update.json) | 2026-11-05T13:13:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131315-parameter-update.json](evidence/2026-11-05-131315-parameter-update.json) | 2026-11-05T13:13:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131313-dimension-update.json](evidence/2026-11-05-131313-dimension-update.json) | 2026-11-05T13:13:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131312-model-export.json](evidence/2026-11-05-131312-model-export.json) | 2026-11-05T13:13:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131311-doc-save.json](evidence/2026-11-05-131311-doc-save.json) | 2026-11-05T13:13:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131309-doc-save.json](evidence/2026-11-05-131309-doc-save.json) | 2026-11-05T13:13:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131308-doc-save.json](evidence/2026-11-05-131308-doc-save.json) | 2026-11-05T13:13:08Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131306-model-render.json](evidence/2026-11-05-131306-model-render.json) | 2026-11-05T13:13:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131303-model-export.json](evidence/2026-11-05-131303-model-export.json) | 2026-11-05T13:13:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131300-relation-list.json](evidence/2026-11-05-131300-relation-list.json) | 2026-11-05T13:13:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131259-parameter-update.json](evidence/2026-11-05-131259-parameter-update.json) | 2026-11-05T13:12:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131256-parameter-list.json](evidence/2026-11-05-131256-parameter-list.json) | 2026-11-05T13:12:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131254-model-get.json](evidence/2026-11-05-131254-model-get.json) | 2026-11-05T13:12:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131253-material-list.json](evidence/2026-11-05-131253-material-list.json) | 2026-11-05T13:12:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131251-geometry-list.json](evidence/2026-11-05-131251-geometry-list.json) | 2026-11-05T13:12:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131250-feature-update.json](evidence/2026-11-05-131250-feature-update.json) | 2026-11-05T13:12:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131248-feature-list.json](evidence/2026-11-05-131248-feature-list.json) | 2026-11-05T13:12:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131247-feature-get.json](evidence/2026-11-05-131247-feature-get.json) | 2026-11-05T13:12:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131245-doc-close.json](evidence/2026-11-05-131245-doc-close.json) | 2026-11-05T13:12:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131244-doc-save.json](evidence/2026-11-05-131244-doc-save.json) | 2026-11-05T13:12:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131242-doc-list.json](evidence/2026-11-05-131242-doc-list.json) | 2026-11-05T13:12:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131241-doc-get.json](evidence/2026-11-05-131241-doc-get.json) | 2026-11-05T13:12:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131239-distance-get.json](evidence/2026-11-05-131239-distance-get.json) | 2026-11-05T13:12:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131238-dimension-update.json](evidence/2026-11-05-131238-dimension-update.json) | 2026-11-05T13:12:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131236-dimension-list.json](evidence/2026-11-05-131236-dimension-list.json) | 2026-11-05T13:12:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131234-feature-update.json](evidence/2026-11-05-131234-feature-update.json) | 2026-11-05T13:12:34Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-131230-parameter-update.json](evidence/2026-11-05-131230-parameter-update.json) | 2026-11-05T13:12:30Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-131225-dimension-update.json](evidence/2026-11-05-131225-dimension-update.json) | 2026-11-05T13:12:25Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-05-131219-doc-close.json](evidence/2026-11-05-131219-doc-close.json) | 2026-11-05T13:12:19Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131214-model-render.json](evidence/2026-11-05-131214-model-render.json) | 2026-11-05T13:12:14Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131211-model-export.json](evidence/2026-11-05-131211-model-export.json) | 2026-11-05T13:12:11Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131209-doc-open.json](evidence/2026-11-05-131209-doc-open.json) | 2026-11-05T13:12:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131206-plugin-get.json](evidence/2026-11-05-131206-plugin-get.json) | 2026-11-05T13:12:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131205-plugin-remove.json](evidence/2026-11-05-131205-plugin-remove.json) | 2026-11-05T13:12:05Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-131204-plugin-install.json](evidence/2026-11-05-131204-plugin-install.json) | 2026-11-05T13:12:04Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-131202-plugin-get.json](evidence/2026-11-05-131202-plugin-get.json) | 2026-11-05T13:12:02Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-131200-doc-get.json](evidence/2026-11-05-131200-doc-get.json) | 2026-11-05T13:12:00Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131158-doc-list.json](evidence/2026-11-05-131158-doc-list.json) | 2026-11-05T13:11:58Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131156-session-get.json](evidence/2026-11-05-131156-session-get.json) | 2026-11-05T13:11:56Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131155-session-list.json](evidence/2026-11-05-131155-session-list.json) | 2026-11-05T13:11:55Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-05-131153-doc-close.json](evidence/2026-11-05-131153-doc-close.json) | 2026-11-05T13:11:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131152-relation-list.json](evidence/2026-11-05-131152-relation-list.json) | 2026-11-05T13:11:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131150-model-render.json](evidence/2026-11-05-131150-model-render.json) | 2026-11-05T13:11:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131149-component-list.json](evidence/2026-11-05-131149-component-list.json) | 2026-11-05T13:11:49Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131144-doc-open.json](evidence/2026-11-05-131144-doc-open.json) | 2026-11-05T13:11:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131141-relation-list.json](evidence/2026-11-05-131141-relation-list.json) | 2026-11-05T13:11:41Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131138-distance-get.json](evidence/2026-11-05-131138-distance-get.json) | 2026-11-05T13:11:38Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131136-feature-get.json](evidence/2026-11-05-131136-feature-get.json) | 2026-11-05T13:11:36Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131133-material-list.json](evidence/2026-11-05-131133-material-list.json) | 2026-11-05T13:11:33Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131131-parameter-list.json](evidence/2026-11-05-131131-parameter-list.json) | 2026-11-05T13:11:31Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131128-dimension-list.json](evidence/2026-11-05-131128-dimension-list.json) | 2026-11-05T13:11:28Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131125-geometry-list.json](evidence/2026-11-05-131125-geometry-list.json) | 2026-11-05T13:11:25Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131123-feature-list.json](evidence/2026-11-05-131123-feature-list.json) | 2026-11-05T13:11:23Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-05-131120-model-get.json](evidence/2026-11-05-131120-model-get.json) | 2026-11-05T13:11:20Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-05-131118-doc-open.json](evidence/2026-11-05-131118-doc-open.json) | 2026-11-05T13:11:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-05-131116-doc-list.json](evidence/2026-11-05-131116-doc-list.json) | 2026-11-05T13:11:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
<!-- driver:evidence:end -->
