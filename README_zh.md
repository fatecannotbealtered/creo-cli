<h1 align="center">creo-cli</h1>
<p align="center"><strong>面向 AI 的 Creo Parametric 操作工具 · JSON 优先 · 受控工作流 · 明确验证边界</strong></p>
<p align="center"><a href="README.md">English</a> · <a href="README_zh.md">中文</a></p>
<p align="center">显式后端 · HMAC 确认 · 离线协议测试 · MIT</p>

**源码开发版，发布状态仍为 `unpublishable`；尚未在真实 Creo 上运行。**
1.0.0 这个版本号对齐本舰队其他 CAD 工具的起始基线，**不代表稳定性承诺**，`docs/SPEC_STATUS.md` 里的门禁依然有效。
本版提供参考已发布接口实现的 CREOSON 后端，保留原来的实验性 PTC VB API 后端和显式模拟的 `.creo.json` 后端。
它不是 CAD 内核，也不把“接口代码已实现、离线测试通过”当成实际安装兼容性或工程正确性证明。

## Agent Install

源码目录内使用 Python 3.11+，CLI 运行时不需要第三方 Python 依赖：

```bash
python -m creo_cli context --compact
python -m creo_cli doctor --compact
python -m creo_cli reference --command "dimension set" --compact
# 可选：安装本地命令入口
python -m pip install -e .
```

阅读[内置 Skill](skills/creo-cli/SKILL.md)。npm 包和二进制未发布；`@fateforge/creo-cli` 保持私有，Node 启动器仅用于源码开发。
CREOSON 后端需要在同一台电脑上配置外部 [CREOSON 服务](https://github.com/SimplifiedLogic/creoson)和已授权的 Creo；本项目不打包、不自动启动它们。
见[安装说明](docs/CREOSON.md)。独立 VB API 路线仍通过 `pip install -e ".[native]"` 安装可选依赖。

## What It Does

围绕结构工程日常工作接入模型、参数、尺寸、特征状态、材料、装配、视图、工程图和交付文件。
工作流用一次预览与确认串联多步操作，持久记录结果并保留部分失败事实。
风险等级 **T1**：确认后可能修改明确指定的测试模型、装配、工程图或输出文件；默认只读。
这是独立项目，不是 PTC 官方产品。

## Capabilities

| 领域 | 命令组 | 实际边界 |
|---|---|---|
| 发现与观察 | `reference/context/doctor/changelog/system capabilities`、`workspace`、`snapshot` | 本地预检不连接 Creo；文件名和散列不代表几何解析 |
| 原有适配器 | `session`、`model`、`change` | VB API 或显式 JSON 模拟，禁止自动回退 |
| CREOSON 连接 | `creoson connect/status` | 使用已启动的本地服务；版本由人声明，不伪装成自动检测 |
| 会话与环境 | `creo pwd/cd/list-files/list-dirs/mkdir/rmdir/get-config/set-config/std-color/set-std-color`、`server pwd` | 目录一律限定在工作区内；`creo cd` 是把 Creo 指向可丢弃工作区的正式途径 |
| 模型生命周期 | `file list/active/info/exists/is-active/open-errors/open/display/refresh/repaint/regenerate/close-window/save/backup/rename/erase/roundtrip` | 指定工作副本；状态类读取不要求模型已加载 |
| 单位、材料与关系式 | `file units/mass-units-only/unit-system/accuracy/set-length-units/set-mass-units/set-unit-system/create-unit-system`、`material list/current/assign`、`file load-material/delete-material/materials-wildcard/current-material-wildcard`、`file relations/postregen-relations/set-relations/set-postregen-relations` | 单位设置必须显式声明 `convert` 并回读；CLI 从不求值关系式文本 |
| 设计状态 | `parameter list/exists/set/copy/delete/set-designated`、`dimension list/list-basic/set/copy/set-text/show`、`feature list/params/param-exists/group-features/pattern-features/suppress/resume/rename/delete/set-param/delete-param`、`note list/get/exists/set/copy/delete`、`layer list/exists/show/delete` | 类型与单位明确；精确名称；禁止通配符写入 |
| 几何读取 | `geometry bound-box/surfaces/edges`、`file simp-reps/has-instances` | 标识、面积与包络；不是网格化，也不是 BREP 导出 |
| 族表 | `familytable list/exists/header/row/cell/parents/tree/create-instance/add-instance/set-cell/replace/delete-instance/delete` | 每次只针对一个精确实例；`tree` 绝不擦除模型；`set-cell` 校验列的声明类型 |
| 装配与视图 | `assembly tree/transform/assemble`、`view list/list-exploded/activate/save` | 单个坐标系约束或固定放置，不是任意装配求解器 |
| 工程图 | `drawing create/add-model/add-sheet/create-view/project-view/regenerate/models/sheets/views/current-sheet/current-model/sheet-size/sheet-scale/sheet-format/list-views/view-location/view-scale/view-sheet/view-bound-box/list-symbols/symbol-loaded/select-sheet/regenerate-sheet/scale-sheet/set-sheet-format/delete-sheet/set-current-model/delete-models/rename-view/move-view/scale-view/delete-view/load-symbol/place-symbol/delete-symbol-definition/delete-symbol-instance` | 需要真实模板；明确图纸、方位和图纸单位；上游允许省略目标表示"全部"的地方，这里一律要求具名 |
| 交付与数据交换 | `export step/iges/dxf/pdf/3dpdf/image/plot/program`、`import file/program` | 具名导出先隔离暂存、校验字节与文件头，再原子发布且不覆盖；`plot`/`program` 由 Creo 决定文件名，按它回报的位置校验 |
| 重复任务 | `workflow validate/run/status/history/result/reconcile` | 最多 32 步、8 个模型目标；无任意 RPC、脚本或 mapkey 执行入口 |

当前 **183 个叶子命令，其中 150 个 CREOSON 领域操作**——CREOSON 3.0.2 发布的全部函数，
仅排除 25 个有意不实现的。`contract/creoson-interface.json` 由该发布自带的规格派生而来，
并有测试把操作目录钉在上面：不会发明字段、不会漏掉必填项、不会承诺上游不返回的响应键，
也不允许任何发布函数既未实现又没有具名理由。

**排除了什么、为什么**：Windchill（PLM 不是本工具的职责）；`creoson connect`/`status` 之外的
连接生命周期，所以这里不会启动、停止或杀掉 Creo；`mapkey` 和 `user_select` 系列，
它们正是本目录要避免的"录制 UI"和"GUI 选取"逃生口；`creo delete_files`，它按模式删除文件、
越出工作区保证；以及 `file erase_not_displayed`，它根本不接受任何目标。

每项操作都有请求 schema、示例、明确默认值、来源溯源和嵌套输出 schema。
**实现不等于实测。** 尚未实现原生零件从零创建、草绘/拉伸/孔/倒角建模、任意装配约束、
干涉分析、钣金展开、完整尺寸公差标注、有限元或自更新。

## Agent Workflow

由人配置**现有的、可丢弃的本地工作区**并授权写入。Agent 不可自行提高权限。PowerShell 示例：

```powershell
$env:CREO_CLI_WORKSPACE = "C:\CreoCliWork"
$env:CREO_CLI_PERMISSION = "write"
$env:CREO_CLI_EXPERIMENTAL_NATIVE_WRITES = "1"
python -m creo_cli creoson connect --creo-major 10 --dry-run --compact
# 检查预览后，用 data.confirm_token 确认一次：
python -m creo_cli creoson connect --creo-major 10 --confirm <confirm_token> --compact
```

默认服务地址是 `http://127.0.0.1:9056/creoson`。连接不会启动 Creo；`10` 只是版本示例，必须填实际安装版本。
新操作使用严格 JSON 请求文件，具体字段以 `reference` 为准：

```bash
python -m creo_cli dimension list --request examples/requests/dimension-list.json --compact
python -m creo_cli dimension set --request examples/requests/dimension-set.json --dry-run --compact
python -m creo_cli dimension set --request examples/requests/dimension-set.json --confirm <confirm_token> --compact
python -m creo_cli workflow validate --input examples/workflow-bracket.json --compact
python -m creo_cli workflow run --input examples/workflow-bracket.json --dry-run --compact
python -m creo_cli workflow run --input examples/workflow-bracket.json --confirm <confirm_token> --compact
python -m creo_cli workflow status --operation-id <operation_id> --compact
python -m creo_cli workflow result --operation-id <operation_id> --step-id inspect --compact
```

示例名称需替换成测试工程中的实际名称，**仓库不含真实 CAD 模型、图纸模板或伪造几何引擎**。
预览绑定整个请求计划、会话、工作区、已观察模型和输入文件散列，不假装预先算出新几何。
依赖前一步产生对象的检查会标记为延后，在真正执行该步前检查。原生写入不自动重试。

`file roundtrip` 保存、关闭窗口、只从内存移除指定零件、重新打开，并对比参数、尺寸、特征数据、关系式、单位、材料和视图名称。
只允许会话中存在一个独立零件。它可检查这些观察数据的持久性，不能证明完整边界表示、装配间隙或强度。
`file close-window` 本身不保存也不移除模型。原 VB API 标量修改仍不自动保存；CREOSON 保存、导出、重开是独立明确的写入操作。

## Machine Contract

默认单个 stdout JSON 信封：`ok/schema_version/data或error/meta.duration_ms`；诊断走 stderr。
`--help` 是显式人类文本入口，`text/raw` 不带信封，`--json` 只是兼容别名。

dry-run 成功返回 `data.preview/confirm_token/expires_at`；缺令牌为退出 5，陈旧或重复令牌为退出 6。
**`E_OUTCOME_UNKNOWN` 为退出 6、不可自动重试**：上游可能仍在运行或写后状态不能确定。
`E_VERIFY_FAILED` 为退出 1：上游接受请求，但选定回读检查失败。两者都不代表回滚成功。
未处理的运行记录会阻止后续原生写入；进程崩溃后仍保留阻塞。
`workflow reconcile` 只是**人已检查的声明**，不是软件验证服务空闲，更不是回滚、几何正确性或重放旧令牌的许可。

`--fields` 支持点路径并保留安全、来源和限制信息。CREOSON 列表分页位于 `data.result`，先获取结果再稳定排序和分页；不是服务端分页，也没有跨次调用快照隔离。
每步大结果另存为有散列校验的本地文件，通过 `workflow result` 读取，不塞进全部历史记录。

结果区分“观察”“仅收到上游确认”“选定后置条件已验证”。这些都不能替代真实 Creo 实测。
导出只检查文件字节和格式头，不保证能正确渲染或几何完全一致。模型散列覆盖选定观察字段，不覆盖内核全部状态。
CLI 锁不能阻止人或其他程序同时编辑，因此必须独占可丢弃的测试会话。

## Configuration

| 环境变量 | 用途 |
|---|---|
| `CREO_CLI_CONFIG_DIR` | 私有状态目录，默认 `~/.creo-cli` |
| `CREO_CLI_PERMISSION` | 人配置 `read`（默认）或 `write` |
| `CREO_CLI_EXPERIMENTAL_NATIVE_WRITES` | 独立实验性写入授权，值为 `1` |
| `CREO_CLI_WORKSPACE` | CREOSON 写入必须使用已存在的可丢弃工作目录 |
| `CREO_CLI_CREOSON_URL` | 仅允许本机 HTTP `/creoson`；禁止远程主机、凭据 URL、重定向和代理 |
| `CREO_CLI_CREOSON_SESSION` | 可选的环境会话 ID；需版本配置的操作应使用 connect 生成的缓存 |
| `CREO_CLI_CREO_MAJOR` | 仅标注环境会话版本，不会配置服务 |
| `PRO_COMM_MSG_EXE` | 独立 VB API 路线的 PTC 通信程序 |
| `CREO_CLI_PYTHON` | Node 源码启动器所用 Python |

普通输出、运行记录和错误不包含会话 ID。会话 ID 不是许可证。本工具不引入账号登录。
超时预算为每次命令 0.1–300 秒，不能据此认定外部 Creo 已停止。
拒绝工作区符号链接、目录联接、路径穿越、网络路径和导出覆盖；进程锁不是应用级锁。

## Project Structure

```text
creo_cli/          注册表、安全、观察数据、VB API 与 CREOSON 边界
  creoson_*.py    操作白名单、HTTP、工作流、持久状态和 schema
examples/         请求和工作流；不含真实原生模板
tests/            模拟、VB API 替身、本地 HTTP 状态替身
skills/           操作流程、异常处理与人工检查点
scripts/          测试、证据、版本同步和受控仓库发布
docs/             接入说明、来源、兼容性、工作流和测试证据
contract/.agent/  临时契约和固定规范目标，精确上游同步待完成
```

## Development

```bash
python scripts/test.py --evidence docs/evidence/offline-tests-1.0.0.json
python scripts/record_creoson_demo.py --output docs/evidence/creoson-offline-demo.json
python scripts/version.py --check
python -m compileall -q creo_cli scripts tests
python scripts/bootstrap_spec.py --check
python scripts/release_gate.py
```

最后两项在规范精确同步、完整 FCC 认证和真实 Creo 证据缺失时故意失败。
离线测试和命令分派覆盖不能豁免这些门槛。本轮不声称已运行 GitHub CI、Windows/Creo 测试、签名发布、二进制构建或依赖审计。
`package.json` 是版本唯一来源；更新根 CHANGELOG 后执行 `scripts/version.py --sync`，再 `--check`。

## Links

[Agent 入口](AGENTS.md) · [Skill](skills/creo-cli/SKILL.md) · [安全](SECURITY.md) ·
[CREOSON 配置](docs/CREOSON.md) · [工作流](docs/WORKFLOWS.md) · [接口来源](docs/UPSTREAM_SOURCES.md) ·
[兼容性](docs/COMPATIBILITY.md) · [VB API](docs/NATIVE_ADAPTER.md) · [架构](docs/ARCHITECTURE.md) ·
[E2E](docs/E2E.md) · [规范状态](docs/SPEC_STATUS.md) · [变更](CHANGELOG.md) ·
[署名](NOTICE.md) · [许可证](LICENSE) · [交接](docs/HANDOFF_zh.md)

超时范围补充：共享截止时间限制上游 HTTP 等待，并阻止超时后继续发起请求；本地散列、文件系统调用和 SQLite 锁等待不能被该计时器强制抢占，仍受各自大小或锁等待限制。
