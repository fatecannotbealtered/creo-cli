# 真实软件验收

[English](E2E.md) | 中文

真实软件运行用真实的适配层，在真实的 Creo Parametric 上执行 creo-cli 的行为矩阵。它会做出真实的修改，所以只使用下面授权过的目标。

## 授权规则

真实软件运行和在真实 Creo Parametric 上的评测可以使用的文件、文件夹和设备，唯一的清单在英文版 `docs/E2E.md` 的「Authorized Targets」一节；检查脚本和运行器只读那一份。目标只由人加入，或者在人自己发的消息里授予后由编码 Agent 加入；Agent 加入后把加的那一行告诉人，目标的说明也由它自己保持更新。每个目标占一个列表项，以反引号括起的目标开头，写法与授权范围文件里的目标相同：文件或文件夹的 `file://` URL，或者设备的 `device:<id>`；后面跟一个冒号和对目标的说明。列出的文件夹就是工作目录：编码 Agent 在里面建练习副本、输出文件夹和评测工作目录，不用再问人。Creo Parametric 的实例没有固定的 ID，所以真实软件运行只使用为这次运行启动的实例，由人或编码 Agent 启动，打开的文档也只来自清单里的文件和文件夹；编码 Agent 只关闭它自己启动的实例。真实软件运行不使用任何其他目标。

真实软件运行所用的授权范围文件只授予清单里的目标，以及为这次运行启动的实例里的新文档。矩阵运行器和评测运行器各自为自己的运行写授权范围文件；其他真实软件工作，比如试一条命令或安装宿主组件，由编码 Agent 自己写，不用问人。评测题的 `SCOPE` 用到的目标也要列在清单里。

## 授权目标

清单以 `docs/E2E.md` 为准，本节不另列目标。

## 步骤

真实软件运行使用这些电脑：

一台 Windows 11 x64 电脑，装有 Creo Parametric 13.4.1.0、它的 Object TOOLKIT Java 和 JDK 25，用会话模式。真实软件运行使用自己的状态目录（`CREO_CLI_STATE_DIR`）。第一次运行前，用这个状态目录运行 `creo-cli plugin install`，在为这次运行启动的 Creo 的起始文件夹里，往 `config.pro` 加一行 `toolkit_registry_file <install_path>\protk.dat`（`install_path` 见 `creo-cli plugin get` 的输出），再启动这个 Creo；`creo-cli session list` 必须显示 `plugin_loaded`。真实软件运行时，给 creo-cli 把 `LOCALAPPDATA` 设到专用的文件夹，这样它们装的宿主组件以及 `plugin install`、`plugin remove` 那几行都不碰人自己的那份。这几行用另一个状态目录，它的宿主组件没有被任何运行中的 Creo 加载：Windows 会一直占着已加载的 JAR，删不掉。`read_back_mismatch` 行用 `--tamper` 改掉结果：一个脚本经宿主组件重新设置尺寸、参数或特征名，把模型重新关闭或打开，删掉写命令生成的文件、保存写出的版本文件，或者结束 `session open` 启动的 Creo。

在真实的 Creo Parametric 上运行行为矩阵：

1. 准备目标，比如在列出的文件夹里专为测试复制的项目、为这次运行启动的实例，或为测试准备好的设备。清单之外的目标，先按「授权规则」列进「授权目标」。
2. 把 `CREO_CLI_STATE_DIR` 设为专供真实软件运行使用的目录。
3. 运行 `python scripts/spec.py matrix --command "<path>" --set <placeholder>=<value>`，矩阵用到的每个占位符各给一个 `--set`，占位符名不带花括号，如 `--set doc=<file>`：`{session}` 是为这次运行启动的实例，`{doc}` 是授权的文档或文件，`{device}` 是授权的设备，`{dir}` 是授权文件夹里新建的空目录。`{job}` 是作业 ID；不给时，运行器先运行 `--job-from` 指定的长命令（只有一个长命令时就是它）的 `normal` 行，用它启动的作业。`{inputs}` 不用 `--set`：它就是 `tests/inputs/`，里面的文件命令只读取，所以不需要授权。
4. 运行器执行适用的行，把真实软件记录写进 `docs/evidence/`，并填上每一行的实际结果和 `live:` 证据引用。实际结果与预期不符的行算作失败。
5. 在真实的 Creo Parametric 上无法按需制造的行，如 `disconnect`，可以标为 `unrunnable` 并写明原因；`normal`、`dialog` 和 `read_back_mismatch` 这三行不可以。`read_back_mismatch` 用 `--row read_back_mismatch` 运行：工具会在读回之前等一会儿，在这段时间里，到 Creo Parametric 里改掉它刚写的内容，或删掉它生成的文件。
6. 运行 `python scripts/spec.py generate` 更新支持矩阵和下面的索引，再把记录和矩阵一起提交。

要在真实的 Creo Parametric 上运行评测题，用列出的文件夹里的一个文件夹运行 `python scripts/spec.py eval --workspace-root <folder>`。运行器为每道题写好授权范围文件，并把评测报告写进 `docs/evidence/`。

真实软件记录只在它记录的工具版本与 creo-cli 的主版本和次版本都相同时才算作证据。记录里从不出现机密，带机密的参数显示为 `***`。

## 证据记录

`docs/evidence/` 里的真实软件记录，由 `python scripts/spec.py generate` 生成：

<!-- driver:evidence:start -->
| 记录 | 运行时间 | 软件 | 平台 | 结果 |
|---|---|---|---|---|
| [2026-11-08-090423-session-close.json](evidence/2026-11-08-090423-session-close.json) | 2026-11-08T09:04:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-090405-session-close.json](evidence/2026-11-08-090405-session-close.json) | 2026-11-08T09:04:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-090403-doc-save-as.json](evidence/2026-11-08-090403-doc-save-as.json) | 2026-11-08T09:04:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-090401-doc-create.json](evidence/2026-11-08-090401-doc-create.json) | 2026-11-08T09:04:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085525-session-close.json](evidence/2026-11-08-085525-session-close.json) | 2026-11-08T08:55:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085523-doc-save-as.json](evidence/2026-11-08-085523-doc-save-as.json) | 2026-11-08T08:55:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085520-doc-create.json](evidence/2026-11-08-085520-doc-create.json) | 2026-11-08T08:55:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085515-doc-save-as.json](evidence/2026-11-08-085515-doc-save-as.json) | 2026-11-08T08:55:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085511-doc-create.json](evidence/2026-11-08-085511-doc-create.json) | 2026-11-08T08:55:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085459-session-close.json](evidence/2026-11-08-085459-session-close.json) | 2026-11-08T08:54:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-085219-session-close.json](evidence/2026-11-08-085219-session-close.json) | 2026-11-08T08:52:19Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-08-083721-session-open.json](evidence/2026-11-08-083721-session-open.json) | 2026-11-08T08:37:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083655-session-close.json](evidence/2026-11-08-083655-session-close.json) | 2026-11-08T08:36:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083644-session-open.json](evidence/2026-11-08-083644-session-open.json) | 2026-11-08T08:36:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083624-session-open.json](evidence/2026-11-08-083624-session-open.json) | 2026-11-08T08:36:24Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-08-083604-doc-save-as.json](evidence/2026-11-08-083604-doc-save-as.json) | 2026-11-08T08:36:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083557-doc-save-as.json](evidence/2026-11-08-083557-doc-save-as.json) | 2026-11-08T08:35:57Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-08-083526-doc-save-as.json](evidence/2026-11-08-083526-doc-save-as.json) | 2026-11-08T08:35:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083522-doc-save-as.json](evidence/2026-11-08-083522-doc-save-as.json) | 2026-11-08T08:35:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083511-doc-save-as.json](evidence/2026-11-08-083511-doc-save-as.json) | 2026-11-08T08:35:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083503-doc-create.json](evidence/2026-11-08-083503-doc-create.json) | 2026-11-08T08:35:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083457-doc-create.json](evidence/2026-11-08-083457-doc-create.json) | 2026-11-08T08:34:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-08-083455-doc-create.json](evidence/2026-11-08-083455-doc-create.json) | 2026-11-08T08:34:55Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-08-083444-doc-create.json](evidence/2026-11-08-083444-doc-create.json) | 2026-11-08T08:34:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-223045-feature-delete.json](evidence/2026-11-07-223045-feature-delete.json) | 2026-11-07T22:30:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-223032-model-render.json](evidence/2026-11-07-223032-model-render.json) | 2026-11-07T22:30:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-223027-feature-update.json](evidence/2026-11-07-223027-feature-update.json) | 2026-11-07T22:30:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-223025-dimension-update.json](evidence/2026-11-07-223025-dimension-update.json) | 2026-11-07T22:30:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-214007-shell-create.json](evidence/2026-11-07-214007-shell-create.json) | 2026-11-07T21:40:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-214005-session-get.json](evidence/2026-11-07-214005-session-get.json) | 2026-11-07T21:40:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-214004-round-create.json](evidence/2026-11-07-214004-round-create.json) | 2026-11-07T21:40:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-214002-revolve-create.json](evidence/2026-11-07-214002-revolve-create.json) | 2026-11-07T21:40:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-214000-relation-update.json](evidence/2026-11-07-214000-relation-update.json) | 2026-11-07T21:40:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213959-relation-list.json](evidence/2026-11-07-213959-relation-list.json) | 2026-11-07T21:39:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213958-plane-create.json](evidence/2026-11-07-213958-plane-create.json) | 2026-11-07T21:39:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213956-pattern-create.json](evidence/2026-11-07-213956-pattern-create.json) | 2026-11-07T21:39:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213955-parameter-update.json](evidence/2026-11-07-213955-parameter-update.json) | 2026-11-07T21:39:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213953-parameter-list.json](evidence/2026-11-07-213953-parameter-list.json) | 2026-11-07T21:39:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213952-parameter-create.json](evidence/2026-11-07-213952-parameter-create.json) | 2026-11-07T21:39:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213950-model-update.json](evidence/2026-11-07-213950-model-update.json) | 2026-11-07T21:39:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213949-model-render.json](evidence/2026-11-07-213949-model-render.json) | 2026-11-07T21:39:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213948-model-get.json](evidence/2026-11-07-213948-model-get.json) | 2026-11-07T21:39:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213946-model-export.json](evidence/2026-11-07-213946-model-export.json) | 2026-11-07T21:39:46Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213945-model-check.json](evidence/2026-11-07-213945-model-check.json) | 2026-11-07T21:39:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213944-material-list.json](evidence/2026-11-07-213944-material-list.json) | 2026-11-07T21:39:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213942-geometry-list.json](evidence/2026-11-07-213942-geometry-list.json) | 2026-11-07T21:39:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213941-feature-update.json](evidence/2026-11-07-213941-feature-update.json) | 2026-11-07T21:39:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213939-feature-list.json](evidence/2026-11-07-213939-feature-list.json) | 2026-11-07T21:39:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213938-feature-get.json](evidence/2026-11-07-213938-feature-get.json) | 2026-11-07T21:39:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213937-feature-delete.json](evidence/2026-11-07-213937-feature-delete.json) | 2026-11-07T21:39:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213935-extrude-create.json](evidence/2026-11-07-213935-extrude-create.json) | 2026-11-07T21:39:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213934-draft-create.json](evidence/2026-11-07-213934-draft-create.json) | 2026-11-07T21:39:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213932-doc-save.json](evidence/2026-11-07-213932-doc-save.json) | 2026-11-07T21:39:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213930-doc-open.json](evidence/2026-11-07-213930-doc-open.json) | 2026-11-07T21:39:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213929-doc-get.json](evidence/2026-11-07-213929-doc-get.json) | 2026-11-07T21:39:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213927-doc-close.json](evidence/2026-11-07-213927-doc-close.json) | 2026-11-07T21:39:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213926-distance-get.json](evidence/2026-11-07-213926-distance-get.json) | 2026-11-07T21:39:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213924-dimension-update.json](evidence/2026-11-07-213924-dimension-update.json) | 2026-11-07T21:39:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213923-dimension-list.json](evidence/2026-11-07-213923-dimension-list.json) | 2026-11-07T21:39:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213921-component-list.json](evidence/2026-11-07-213921-component-list.json) | 2026-11-07T21:39:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213920-chamfer-create.json](evidence/2026-11-07-213920-chamfer-create.json) | 2026-11-07T21:39:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213918-axis-create.json](evidence/2026-11-07-213918-axis-create.json) | 2026-11-07T21:39:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213809-session-list.json](evidence/2026-11-07-213809-session-list.json) | 2026-11-07T21:38:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213557-model-check.json](evidence/2026-11-07-213557-model-check.json) | 2026-11-07T21:35:57Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-213525-feature-delete.json](evidence/2026-11-07-213525-feature-delete.json) | 2026-11-07T21:35:25Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213510-feature-delete.json](evidence/2026-11-07-213510-feature-delete.json) | 2026-11-07T21:35:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213503-feature-delete.json](evidence/2026-11-07-213503-feature-delete.json) | 2026-11-07T21:35:03Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-213457-feature-delete.json](evidence/2026-11-07-213457-feature-delete.json) | 2026-11-07T21:34:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213426-model-update.json](evidence/2026-11-07-213426-model-update.json) | 2026-11-07T21:34:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213414-model-update.json](evidence/2026-11-07-213414-model-update.json) | 2026-11-07T21:34:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213406-model-update.json](evidence/2026-11-07-213406-model-update.json) | 2026-11-07T21:34:06Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-213401-model-update.json](evidence/2026-11-07-213401-model-update.json) | 2026-11-07T21:34:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213327-relation-update.json](evidence/2026-11-07-213327-relation-update.json) | 2026-11-07T21:33:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213316-relation-update.json](evidence/2026-11-07-213316-relation-update.json) | 2026-11-07T21:33:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213311-relation-update.json](evidence/2026-11-07-213311-relation-update.json) | 2026-11-07T21:33:11Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-07-213305-relation-update.json](evidence/2026-11-07-213305-relation-update.json) | 2026-11-07T21:33:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213231-parameter-create.json](evidence/2026-11-07-213231-parameter-create.json) | 2026-11-07T21:32:31Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213220-parameter-create.json](evidence/2026-11-07-213220-parameter-create.json) | 2026-11-07T21:32:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213214-parameter-create.json](evidence/2026-11-07-213214-parameter-create.json) | 2026-11-07T21:32:14Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-213208-parameter-create.json](evidence/2026-11-07-213208-parameter-create.json) | 2026-11-07T21:32:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213138-axis-create.json](evidence/2026-11-07-213138-axis-create.json) | 2026-11-07T21:31:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213126-axis-create.json](evidence/2026-11-07-213126-axis-create.json) | 2026-11-07T21:31:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213120-axis-create.json](evidence/2026-11-07-213120-axis-create.json) | 2026-11-07T21:31:20Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-213115-axis-create.json](evidence/2026-11-07-213115-axis-create.json) | 2026-11-07T21:31:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213044-plane-create.json](evidence/2026-11-07-213044-plane-create.json) | 2026-11-07T21:30:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213033-plane-create.json](evidence/2026-11-07-213033-plane-create.json) | 2026-11-07T21:30:33Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-213027-plane-create.json](evidence/2026-11-07-213027-plane-create.json) | 2026-11-07T21:30:27Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-213022-plane-create.json](evidence/2026-11-07-213022-plane-create.json) | 2026-11-07T21:30:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212952-pattern-create.json](evidence/2026-11-07-212952-pattern-create.json) | 2026-11-07T21:29:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212940-pattern-create.json](evidence/2026-11-07-212940-pattern-create.json) | 2026-11-07T21:29:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212934-pattern-create.json](evidence/2026-11-07-212934-pattern-create.json) | 2026-11-07T21:29:34Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212929-pattern-create.json](evidence/2026-11-07-212929-pattern-create.json) | 2026-11-07T21:29:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212859-draft-create.json](evidence/2026-11-07-212859-draft-create.json) | 2026-11-07T21:28:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212847-draft-create.json](evidence/2026-11-07-212847-draft-create.json) | 2026-11-07T21:28:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212841-draft-create.json](evidence/2026-11-07-212841-draft-create.json) | 2026-11-07T21:28:41Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212836-draft-create.json](evidence/2026-11-07-212836-draft-create.json) | 2026-11-07T21:28:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212805-chamfer-create.json](evidence/2026-11-07-212805-chamfer-create.json) | 2026-11-07T21:28:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212753-chamfer-create.json](evidence/2026-11-07-212753-chamfer-create.json) | 2026-11-07T21:27:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212746-chamfer-create.json](evidence/2026-11-07-212746-chamfer-create.json) | 2026-11-07T21:27:46Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212741-chamfer-create.json](evidence/2026-11-07-212741-chamfer-create.json) | 2026-11-07T21:27:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212710-round-create.json](evidence/2026-11-07-212710-round-create.json) | 2026-11-07T21:27:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212655-round-create.json](evidence/2026-11-07-212655-round-create.json) | 2026-11-07T21:26:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212648-round-create.json](evidence/2026-11-07-212648-round-create.json) | 2026-11-07T21:26:48Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212642-round-create.json](evidence/2026-11-07-212642-round-create.json) | 2026-11-07T21:26:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212611-shell-create.json](evidence/2026-11-07-212611-shell-create.json) | 2026-11-07T21:26:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212558-shell-create.json](evidence/2026-11-07-212558-shell-create.json) | 2026-11-07T21:25:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212551-shell-create.json](evidence/2026-11-07-212551-shell-create.json) | 2026-11-07T21:25:51Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212545-shell-create.json](evidence/2026-11-07-212545-shell-create.json) | 2026-11-07T21:25:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212516-revolve-create.json](evidence/2026-11-07-212516-revolve-create.json) | 2026-11-07T21:25:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212503-revolve-create.json](evidence/2026-11-07-212503-revolve-create.json) | 2026-11-07T21:25:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212457-revolve-create.json](evidence/2026-11-07-212457-revolve-create.json) | 2026-11-07T21:24:57Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212452-revolve-create.json](evidence/2026-11-07-212452-revolve-create.json) | 2026-11-07T21:24:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212417-extrude-create.json](evidence/2026-11-07-212417-extrude-create.json) | 2026-11-07T21:24:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212401-extrude-create.json](evidence/2026-11-07-212401-extrude-create.json) | 2026-11-07T21:24:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-212350-extrude-create.json](evidence/2026-11-07-212350-extrude-create.json) | 2026-11-07T21:23:50Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-212343-extrude-create.json](evidence/2026-11-07-212343-extrude-create.json) | 2026-11-07T21:23:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191427-model-check.json](evidence/2026-11-07-191427-model-check.json) | 2026-11-07T19:14:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191426-feature-delete.json](evidence/2026-11-07-191426-feature-delete.json) | 2026-11-07T19:14:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191424-model-update.json](evidence/2026-11-07-191424-model-update.json) | 2026-11-07T19:14:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191423-relation-update.json](evidence/2026-11-07-191423-relation-update.json) | 2026-11-07T19:14:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191421-parameter-create.json](evidence/2026-11-07-191421-parameter-create.json) | 2026-11-07T19:14:21Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191419-axis-create.json](evidence/2026-11-07-191419-axis-create.json) | 2026-11-07T19:14:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191418-plane-create.json](evidence/2026-11-07-191418-plane-create.json) | 2026-11-07T19:14:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191416-pattern-create.json](evidence/2026-11-07-191416-pattern-create.json) | 2026-11-07T19:14:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191414-draft-create.json](evidence/2026-11-07-191414-draft-create.json) | 2026-11-07T19:14:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191412-chamfer-create.json](evidence/2026-11-07-191412-chamfer-create.json) | 2026-11-07T19:14:12Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191411-round-create.json](evidence/2026-11-07-191411-round-create.json) | 2026-11-07T19:14:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191409-shell-create.json](evidence/2026-11-07-191409-shell-create.json) | 2026-11-07T19:14:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191407-revolve-create.json](evidence/2026-11-07-191407-revolve-create.json) | 2026-11-07T19:14:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191406-extrude-create.json](evidence/2026-11-07-191406-extrude-create.json) | 2026-11-07T19:14:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191404-relation-list.json](evidence/2026-11-07-191404-relation-list.json) | 2026-11-07T19:14:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191402-parameter-update.json](evidence/2026-11-07-191402-parameter-update.json) | 2026-11-07T19:14:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191401-parameter-list.json](evidence/2026-11-07-191401-parameter-list.json) | 2026-11-07T19:14:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191359-model-render.json](evidence/2026-11-07-191359-model-render.json) | 2026-11-07T19:13:59Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191358-model-get.json](evidence/2026-11-07-191358-model-get.json) | 2026-11-07T19:13:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191356-model-export.json](evidence/2026-11-07-191356-model-export.json) | 2026-11-07T19:13:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191354-material-list.json](evidence/2026-11-07-191354-material-list.json) | 2026-11-07T19:13:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191353-geometry-list.json](evidence/2026-11-07-191353-geometry-list.json) | 2026-11-07T19:13:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191352-feature-update.json](evidence/2026-11-07-191352-feature-update.json) | 2026-11-07T19:13:52Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191350-feature-list.json](evidence/2026-11-07-191350-feature-list.json) | 2026-11-07T19:13:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191348-feature-get.json](evidence/2026-11-07-191348-feature-get.json) | 2026-11-07T19:13:48Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191347-doc-save.json](evidence/2026-11-07-191347-doc-save.json) | 2026-11-07T19:13:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191345-doc-open.json](evidence/2026-11-07-191345-doc-open.json) | 2026-11-07T19:13:45Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191344-doc-close.json](evidence/2026-11-07-191344-doc-close.json) | 2026-11-07T19:13:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191342-distance-get.json](evidence/2026-11-07-191342-distance-get.json) | 2026-11-07T19:13:42Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191340-dimension-update.json](evidence/2026-11-07-191340-dimension-update.json) | 2026-11-07T19:13:40Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191339-dimension-list.json](evidence/2026-11-07-191339-dimension-list.json) | 2026-11-07T19:13:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191337-component-list.json](evidence/2026-11-07-191337-component-list.json) | 2026-11-07T19:13:37Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191335-model-check.json](evidence/2026-11-07-191335-model-check.json) | 2026-11-07T19:13:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191332-feature-delete.json](evidence/2026-11-07-191332-feature-delete.json) | 2026-11-07T19:13:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191329-model-update.json](evidence/2026-11-07-191329-model-update.json) | 2026-11-07T19:13:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191326-relation-update.json](evidence/2026-11-07-191326-relation-update.json) | 2026-11-07T19:13:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191322-parameter-create.json](evidence/2026-11-07-191322-parameter-create.json) | 2026-11-07T19:13:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191319-axis-create.json](evidence/2026-11-07-191319-axis-create.json) | 2026-11-07T19:13:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191316-plane-create.json](evidence/2026-11-07-191316-plane-create.json) | 2026-11-07T19:13:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191313-pattern-create.json](evidence/2026-11-07-191313-pattern-create.json) | 2026-11-07T19:13:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191310-draft-create.json](evidence/2026-11-07-191310-draft-create.json) | 2026-11-07T19:13:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191306-chamfer-create.json](evidence/2026-11-07-191306-chamfer-create.json) | 2026-11-07T19:13:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191303-round-create.json](evidence/2026-11-07-191303-round-create.json) | 2026-11-07T19:13:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191300-shell-create.json](evidence/2026-11-07-191300-shell-create.json) | 2026-11-07T19:13:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191257-revolve-create.json](evidence/2026-11-07-191257-revolve-create.json) | 2026-11-07T19:12:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191253-extrude-create.json](evidence/2026-11-07-191253-extrude-create.json) | 2026-11-07T19:12:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191250-relation-list.json](evidence/2026-11-07-191250-relation-list.json) | 2026-11-07T19:12:50Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191247-parameter-update.json](evidence/2026-11-07-191247-parameter-update.json) | 2026-11-07T19:12:47Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191244-parameter-list.json](evidence/2026-11-07-191244-parameter-list.json) | 2026-11-07T19:12:44Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191241-model-render.json](evidence/2026-11-07-191241-model-render.json) | 2026-11-07T19:12:41Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191238-model-get.json](evidence/2026-11-07-191238-model-get.json) | 2026-11-07T19:12:38Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191235-model-export.json](evidence/2026-11-07-191235-model-export.json) | 2026-11-07T19:12:35Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191232-material-list.json](evidence/2026-11-07-191232-material-list.json) | 2026-11-07T19:12:32Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191229-geometry-list.json](evidence/2026-11-07-191229-geometry-list.json) | 2026-11-07T19:12:29Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191226-feature-update.json](evidence/2026-11-07-191226-feature-update.json) | 2026-11-07T19:12:26Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191223-feature-list.json](evidence/2026-11-07-191223-feature-list.json) | 2026-11-07T19:12:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191220-feature-get.json](evidence/2026-11-07-191220-feature-get.json) | 2026-11-07T19:12:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191217-doc-save.json](evidence/2026-11-07-191217-doc-save.json) | 2026-11-07T19:12:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191214-doc-open.json](evidence/2026-11-07-191214-doc-open.json) | 2026-11-07T19:12:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191210-doc-close.json](evidence/2026-11-07-191210-doc-close.json) | 2026-11-07T19:12:10Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191207-distance-get.json](evidence/2026-11-07-191207-distance-get.json) | 2026-11-07T19:12:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191204-dimension-update.json](evidence/2026-11-07-191204-dimension-update.json) | 2026-11-07T19:12:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191201-dimension-list.json](evidence/2026-11-07-191201-dimension-list.json) | 2026-11-07T19:12:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191158-component-list.json](evidence/2026-11-07-191158-component-list.json) | 2026-11-07T19:11:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191143-component-list.json](evidence/2026-11-07-191143-component-list.json) | 2026-11-07T19:11:43Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191139-doc-save.json](evidence/2026-11-07-191139-doc-save.json) | 2026-11-07T19:11:39Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191127-feature-update.json](evidence/2026-11-07-191127-feature-update.json) | 2026-11-07T19:11:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191123-parameter-update.json](evidence/2026-11-07-191123-parameter-update.json) | 2026-11-07T19:11:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191119-dimension-update.json](evidence/2026-11-07-191119-dimension-update.json) | 2026-11-07T19:11:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191116-model-render.json](evidence/2026-11-07-191116-model-render.json) | 2026-11-07T19:11:16Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191114-model-export.json](evidence/2026-11-07-191114-model-export.json) | 2026-11-07T19:11:14Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191113-doc-close.json](evidence/2026-11-07-191113-doc-close.json) | 2026-11-07T19:11:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191111-doc-open.json](evidence/2026-11-07-191111-doc-open.json) | 2026-11-07T19:11:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191109-plugin-remove.json](evidence/2026-11-07-191109-plugin-remove.json) | 2026-11-07T19:11:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191108-plugin-install.json](evidence/2026-11-07-191108-plugin-install.json) | 2026-11-07T19:11:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191106-doc-save.json](evidence/2026-11-07-191106-doc-save.json) | 2026-11-07T19:11:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191104-feature-update.json](evidence/2026-11-07-191104-feature-update.json) | 2026-11-07T19:11:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191102-parameter-update.json](evidence/2026-11-07-191102-parameter-update.json) | 2026-11-07T19:11:02Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191100-dimension-update.json](evidence/2026-11-07-191100-dimension-update.json) | 2026-11-07T19:11:00Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191057-model-export.json](evidence/2026-11-07-191057-model-export.json) | 2026-11-07T19:10:57Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191055-doc-save.json](evidence/2026-11-07-191055-doc-save.json) | 2026-11-07T19:10:55Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191053-doc-save.json](evidence/2026-11-07-191053-doc-save.json) | 2026-11-07T19:10:53Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191047-doc-save.json](evidence/2026-11-07-191047-doc-save.json) | 2026-11-07T19:10:47Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-191036-doc-save.json](evidence/2026-11-07-191036-doc-save.json) | 2026-11-07T19:10:36Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191030-model-render.json](evidence/2026-11-07-191030-model-render.json) | 2026-11-07T19:10:30Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191027-model-export.json](evidence/2026-11-07-191027-model-export.json) | 2026-11-07T19:10:27Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191024-relation-list.json](evidence/2026-11-07-191024-relation-list.json) | 2026-11-07T19:10:24Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191022-parameter-update.json](evidence/2026-11-07-191022-parameter-update.json) | 2026-11-07T19:10:22Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191020-parameter-list.json](evidence/2026-11-07-191020-parameter-list.json) | 2026-11-07T19:10:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191019-model-get.json](evidence/2026-11-07-191019-model-get.json) | 2026-11-07T19:10:19Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191017-material-list.json](evidence/2026-11-07-191017-material-list.json) | 2026-11-07T19:10:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191015-geometry-list.json](evidence/2026-11-07-191015-geometry-list.json) | 2026-11-07T19:10:15Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191013-feature-update.json](evidence/2026-11-07-191013-feature-update.json) | 2026-11-07T19:10:13Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191011-feature-list.json](evidence/2026-11-07-191011-feature-list.json) | 2026-11-07T19:10:11Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191009-feature-get.json](evidence/2026-11-07-191009-feature-get.json) | 2026-11-07T19:10:09Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191008-doc-close.json](evidence/2026-11-07-191008-doc-close.json) | 2026-11-07T19:10:08Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191006-doc-list.json](evidence/2026-11-07-191006-doc-list.json) | 2026-11-07T19:10:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191005-doc-get.json](evidence/2026-11-07-191005-doc-get.json) | 2026-11-07T19:10:05Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191003-distance-get.json](evidence/2026-11-07-191003-distance-get.json) | 2026-11-07T19:10:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-191001-dimension-update.json](evidence/2026-11-07-191001-dimension-update.json) | 2026-11-07T19:10:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190958-dimension-list.json](evidence/2026-11-07-190958-dimension-list.json) | 2026-11-07T19:09:58Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190955-feature-update.json](evidence/2026-11-07-190955-feature-update.json) | 2026-11-07T19:09:55Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-07-190948-parameter-update.json](evidence/2026-11-07-190948-parameter-update.json) | 2026-11-07T19:09:48Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-07-190942-dimension-update.json](evidence/2026-11-07-190942-dimension-update.json) | 2026-11-07T19:09:42Z | Creo Parametric 13.4.1.0 | windows | 5 次运行中 5 次通过 |
| [2026-11-07-190934-doc-close.json](evidence/2026-11-07-190934-doc-close.json) | 2026-11-07T19:09:34Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190927-doc-close.json](evidence/2026-11-07-190927-doc-close.json) | 2026-11-07T19:09:27Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190920-model-render.json](evidence/2026-11-07-190920-model-render.json) | 2026-11-07T19:09:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190917-model-export.json](evidence/2026-11-07-190917-model-export.json) | 2026-11-07T19:09:17Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190912-model-render.json](evidence/2026-11-07-190912-model-render.json) | 2026-11-07T19:09:12Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190908-model-export.json](evidence/2026-11-07-190908-model-export.json) | 2026-11-07T19:09:08Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190903-doc-open.json](evidence/2026-11-07-190903-doc-open.json) | 2026-11-07T19:09:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190900-doc-open.json](evidence/2026-11-07-190900-doc-open.json) | 2026-11-07T19:09:00Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-07-190856-plugin-get.json](evidence/2026-11-07-190856-plugin-get.json) | 2026-11-07T19:08:56Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190854-plugin-remove.json](evidence/2026-11-07-190854-plugin-remove.json) | 2026-11-07T19:08:54Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190851-plugin-remove.json](evidence/2026-11-07-190851-plugin-remove.json) | 2026-11-07T19:08:51Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-07-190849-plugin-install.json](evidence/2026-11-07-190849-plugin-install.json) | 2026-11-07T19:08:49Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190846-plugin-install.json](evidence/2026-11-07-190846-plugin-install.json) | 2026-11-07T19:08:46Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-07-190832-plugin-get.json](evidence/2026-11-07-190832-plugin-get.json) | 2026-11-07T19:08:32Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-07-190831-doc-get.json](evidence/2026-11-07-190831-doc-get.json) | 2026-11-07T19:08:31Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190829-doc-list.json](evidence/2026-11-07-190829-doc-list.json) | 2026-11-07T19:08:29Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190827-session-get.json](evidence/2026-11-07-190827-session-get.json) | 2026-11-07T19:08:27Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190825-session-list.json](evidence/2026-11-07-190825-session-list.json) | 2026-11-07T19:08:25Z | Creo Parametric 13.4.1.0 | windows | 2 次运行中 2 次通过 |
| [2026-11-07-190823-doc-close.json](evidence/2026-11-07-190823-doc-close.json) | 2026-11-07T19:08:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190820-relation-list.json](evidence/2026-11-07-190820-relation-list.json) | 2026-11-07T19:08:20Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190818-model-render.json](evidence/2026-11-07-190818-model-render.json) | 2026-11-07T19:08:18Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190807-dimension-list.json](evidence/2026-11-07-190807-dimension-list.json) | 2026-11-07T19:08:07Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190806-distance-get.json](evidence/2026-11-07-190806-distance-get.json) | 2026-11-07T19:08:06Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190804-geometry-list.json](evidence/2026-11-07-190804-geometry-list.json) | 2026-11-07T19:08:04Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190803-feature-list.json](evidence/2026-11-07-190803-feature-list.json) | 2026-11-07T19:08:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190801-feature-get.json](evidence/2026-11-07-190801-feature-get.json) | 2026-11-07T19:08:01Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190759-component-list.json](evidence/2026-11-07-190759-component-list.json) | 2026-11-07T19:07:59Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190751-doc-open.json](evidence/2026-11-07-190751-doc-open.json) | 2026-11-07T19:07:51Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-190746-relation-list.json](evidence/2026-11-07-190746-relation-list.json) | 2026-11-07T19:07:46Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190744-distance-get.json](evidence/2026-11-07-190744-distance-get.json) | 2026-11-07T19:07:44Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190741-feature-get.json](evidence/2026-11-07-190741-feature-get.json) | 2026-11-07T19:07:41Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190739-material-list.json](evidence/2026-11-07-190739-material-list.json) | 2026-11-07T19:07:39Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190736-parameter-list.json](evidence/2026-11-07-190736-parameter-list.json) | 2026-11-07T19:07:36Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190734-dimension-list.json](evidence/2026-11-07-190734-dimension-list.json) | 2026-11-07T19:07:34Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190731-geometry-list.json](evidence/2026-11-07-190731-geometry-list.json) | 2026-11-07T19:07:31Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190727-feature-list.json](evidence/2026-11-07-190727-feature-list.json) | 2026-11-07T19:07:27Z | Creo Parametric 13.4.1.0 | windows | 4 次运行中 4 次通过 |
| [2026-11-07-190725-model-get.json](evidence/2026-11-07-190725-model-get.json) | 2026-11-07T19:07:25Z | Creo Parametric 13.4.1.0 | windows | 3 次运行中 3 次通过 |
| [2026-11-07-190723-doc-open.json](evidence/2026-11-07-190723-doc-open.json) | 2026-11-07T19:07:23Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
| [2026-11-07-185503-doc-list.json](evidence/2026-11-07-185503-doc-list.json) | 2026-11-07T18:55:03Z | Creo Parametric 13.4.1.0 | windows | 1 次运行中 1 次通过 |
<!-- driver:evidence:end -->
