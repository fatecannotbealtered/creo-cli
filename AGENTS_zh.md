# AGENTS.md

[English](AGENTS.md) | 中文

本文件写给在 creo-cli 项目上干活的编程 Agent。改动任何东西之前先读它。

## 必须遵守的底线

1. 禁止修改固定副本：`.agent/`、`contract/driver-contract.json`、`creo_cli/_driver/`、`licenses/`，以及 `scripts/` 里的 `spec.py`、`build.py`、`pack.py`、`platforms.py` 和 `release_gate.py`。它们原样来自 tool-driver-cli-spec 的某一个发布。要换到另一个发布，运行 `python scripts/spec.py sync <version>`，它会把这些副本一起替换。
2. 禁止手改生成的内容：`contract/commands.json`、README 和 Skill 里的命令地图、徽章行、信息卡、风险块、支持矩阵和证据索引。改它们的来源，再运行 `python scripts/spec.py generate`。
3. 每个领域命令都在 `creo_cli/commands/` 里登记，写明它的全部效果、模式、每个物理参数的单位量和目标类型。软件无法撤回的修改要标为 `irreversible`。禁止降低确认级别。
4. 每个领域命令都要在 `tests/matrix/` 里有行为矩阵。写命令的矩阵中，`normal` 行就是它的样例。
5. 每次提交前运行 `python -m ruff check .`、`python scripts/spec.py check`、`python -m unittest discover -s tests` 和 `python scripts/spec.py suites`，四项都必须通过。禁止跳过、削弱或修改一致性测试。
6. 真实软件测试只能用 `docs/E2E.md` 里「Authorized Targets」一节列出的目标。只有人在自己发的消息里明确要你代写时，才添加目标或写真实软件测试的授权范围文件，而且要先把内容给人看、人同意后再写；否则只在对话里给出建议，由人自己写。每道评测题需要的授权范围文件由评测运行器来写。
7. 测试把 `CREO_CLI_STATE_DIR` 设为新建的临时目录，从不碰真实的状态目录。
8. 禁止提交机密、许可证文件或密钥，以及无权分享的客户文件和项目文件，证据里也不行。
9. 脚本和测试在 Windows 上启动子进程时，传入 `CREATE_NO_WINDOW`。
10. 每次改动都在 `CHANGELOG.md` 的 `[Unreleased]` 下加一条记录。
11. 代码、代码注释、提交信息、命令输出和错误信息都用英文。

## 本项目

creo-cli 驱动 Creo Parametric，支持的版本是 >=13.4 <13.5，模式如下：

- `session`：驱动正在运行的 Creo Parametric 实例。

代码的位置：

- 领域命令：`creo_cli/commands/`
- 适配层：`creo_cli/adapter/`
- 宿主组件源码：`plugin/`
- 驱动运行时，固定副本：`creo_cli/_driver/`

适配层怎样连到 Creo Parametric：

- Creo 的工具包（Object TOOLKIT Java）只能在 Creo 进程里、在它的主线程上使用。所以读写模型的工作全部在宿主组件 `plugin/source/` 里完成，运行时经命名管道用宿主协议连到它。`creo_cli/adapter/` 只负责找到安装（`probe`）、列出运行中的 `xtop.exe` 进程和挡住它们的弹窗（`sessions`），以及安装宿主组件（`plugin_*`）。
- 宿主组件里，工具包调用只能在交给 `MainThread` 的任务里执行，绝不能在管道线程上执行。不要把为 null 的 Java 字符串传给 Creo，它会崩溃。`com.fateforge.creocli.host.core` 包不能用 Creo 的类，这样它不用 Creo 也能编译和测试（`tests/test_host_protocol.py`）。
- 宿主组件只以源码发布。`plugin install` 在用户电脑上用用户的 JDK 25、对着用户的 `otk.jar` 编译 `plugin/source/`，再用用户自己的许可解锁 JAR（`creo_cli/adapter/build.py`）；不要把 JAR 或任何二进制提交进 `plugin/`。改了 `plugin/source/` 之后，运行 `python scripts/spec.py generate` 更新 `plugin/manifest.json`，真实软件运行前再执行一次 `plugin install`。
- Creo 只在启动时加载宿主组件。`plugin install` 之后由人重启 Creo，工具从不重启它（DSEC-052）。

常用命令见 `CONTRIBUTING_zh.md` 的「常用命令」一节。真实软件测试只用 `docs/E2E.md` 里「Authorized Targets」一节的目标；本文件不列任何目标。
