# creo-cli

让 AI Agent 读取 Creo Parametric 的模型，修改尺寸、参数和特征，再保存和导出：每次修改都先预览、经确认，再从 Creo 读回核对。

<!-- driver:badges:start -->
![Agent-native](https://img.shields.io/badge/🤖-Agent--native-6f42c1)
[![CI](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fatecannotbealtered/creo-cli/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@fateforge/creo-cli)](https://www.npmjs.com/package/@fateforge/creo-cli)
![drives](https://img.shields.io/badge/drives-Creo_Parametric_%3E%3D13.4_%3C13.5-1f6feb)
![mode](https://img.shields.io/badge/mode-session-0e8a16)
![platform](https://img.shields.io/badge/platform-Windows-555555)
![risk](https://img.shields.io/badge/risk-T2-d29922)
![maturity](https://img.shields.io/badge/maturity-verified-8957e5)
![spec](https://img.shields.io/badge/spec-tool--driver--cli--spec_1.0.9-0969da)
![license](https://img.shields.io/badge/license-Apache--2.0-blue)
<!-- driver:badges:end -->

[English](README.md) | 中文

<!-- driver:info-card:start -->
| 项目 | 内容 |
|---|---|
| 软件 | Creo Parametric >=13.4 <13.5 |
| 模式 | session |
| 系统与 CPU | Windows (x64) |
| 风险等级 | T2 |
| 成熟度 | verified：draft 0 个，verified 16 个，stable 13 个 |
| 规范 | tool-driver-cli-spec 1.0.9 |
| 宿主组件 | 需要 |
<!-- driver:info-card:end -->

## 安装

1. 从 npm 安装 creo-cli：

   ```bash
   npm install -g @fateforge/creo-cli
   ```

2. 运行一次 `update`。刚装好的已经是最新版本，所以 `update` 只把命令入口指向原生程序；这样每次调用都不用先启动 Node.js：

   ```bash
   creo-cli update
   ```

3. 从已安装的包里安装 Skill，Skill 从不从网络获取。把它们复制到 Agent 的 Skill 目录。用 bash：

   ```bash
   mkdir -p ~/.agents/skills
   cp -r "$(npm root -g)/@fateforge/creo-cli/skills/"* ~/.agents/skills/
   ```

   用 PowerShell：

   ```powershell
   New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
   Copy-Item -Recurse -Force "$(npm root -g)\@fateforge/creo-cli\skills\*" "$HOME\.agents\skills\"
   ```

   其他 Agent 的 Skill 目录做法相同。以后运行 `creo-cli update` 时，这几个目录里的副本会跟着工具一起更新：`~/.agents/skills/`、`~/.claude/skills/`、`~/.codex/skills/`、`~/.cursor/skills/`、`~/.gemini/skills/`。放在别处的副本不会更新。

4. 把宿主组件装进 Creo Parametric。这是两步确认的写操作，需要允许 `configure` 的授权范围文件（见「授权」）。第一次调用什么都不改，返回预览和确认令牌；第二次调用才安装：

   ```bash
   creo-cli plugin install
   creo-cli plugin install --confirm <token>
   ```

   装好后启动或重启 Creo Parametric，让它加载宿主组件。

## 能力

下面是 creo-cli 的全部命令，由命令登记生成；`(dangerous)` 表示该命令属于危险级，`creo-cli reference --command "<path>"` 给出单个命令的完整说明。

<!-- driver:command-map:start -->
- `reference`
- `context`
- `doctor`
- `changelog`
- `operation`: get, list, resolve
- `update`
- `session`: list, get, open, close
- `doc`: list, get, create, open, save, save-as, close, undo
- `job`: list, get, cancel
- `plugin`: get, install, remove
- `knowledge`: list, get, search, create, delete
- `feature`: get, list, update, delete (dangerous)
- `model`: get, check, update, export, render
- `geometry`: list
- `distance`: get
- `dimension`: list, update
- `parameter`: list, update, create
- `relation`: list, update
- `material`: list
- `component`: list
- `extrude`: create
- `revolve`: create
- `shell`: create
- `round`: create
- `pattern`: create
- `plane`: create
- `axis`: create
- `chamfer`: create
- `draft`: create
<!-- driver:command-map:end -->

## 工作方式

creo-cli 每次调用都输出一个 JSON 信封。`creo-cli reference` 列出全部命令，`creo-cli reference --command "<path>"` 说明单个命令，包括它的参数、效果和在每种模式下的确认级别。

**实例与文档。** creo-cli 驱动正在运行的 Creo Parametric 实例。`creo-cli session list` 列出每个实例的会话 ID、状态和打开的文档，`creo-cli doc list` 列出文档。用 `--session <id>` 指定实例，用 `--doc <path-or-id>` 指定文档。有多个实例在运行而命令没有指定时，命令返回 `E_AMBIGUOUS` 和候选列表：creo-cli 从不按窗口焦点或最近使用来挑实例。`--doc` 指定的文档只有一个实例打开时，就选中这个实例。被某个实例打开的文件只经由这个实例修改，直接写这个文件会被 `E_CONFLICT` 拒绝。

**确认级别。** 每次写操作都会检查授权范围、生成预览、在派发前再检查一次状态、锁定目标、读回修改并返回回执。只有确认方式随级别不同，级别由 creo-cli 根据命令声明的效果得出：

| 级别 | 适用 | 调用方式 |
|---|---|---|
| 直接执行 | 保存之前只在内存里的修改；启动实例；新建和打开文档；不覆盖已有文件的新文件；停止工作 | 一次调用就执行 |
| 两步确认 | 保存和覆盖文件；文件模式和设备模式下的修改；设置；宿主组件 | 第一次调用什么都不改，返回 `E_CONFIRMATION_REQUIRED`，带预览和确认令牌；再带 `--confirm <token>` 运行同一条命令才执行 |
| 危险 | 物理动作；把内容交给外部的人或系统；不可撤回的修改；放弃未保存的修改；关闭不是 creo-cli 启动的实例 | 与两步确认相同，确认的那次调用还要加 `--dangerous`；授权范围必须允许危险操作 |

`--dry-run` 显示任何写操作的预览，什么都不改。确认令牌只能用一次，10 分钟内有效，而且只对它预览过的那次修改有效。授权范围文件设了 `"confirm": "always"` 时，除停止工作外的所有写操作都改为两步确认，人可以逐个批准预览。

**会话模式下的保存。** 修改不等于保存。修改之后，回执报告 `persistence: unchanged`，文档仍有未保存的修改；只有 `creo-cli doc save` 才写入文档的文件。保存的预览列出上次保存以来的所有修改，包括人在 Creo Parametric 里做的修改（`origin: external`），以及结果仍然未知的写操作。Creo Parametric 一改就自己存盘的命令按两步确认，回执报告 `persistence: saved`。

**回执。** 每次写操作都返回回执，分别报告修改是否执行、是否生效、是否送达、是否保存、是否验证。写操作的回复丢失时，creo-cli 返回 `E_OUTCOME_UNKNOWN` 和查明结果的命令，绝不会把写操作再发一遍。

## 授权

creo-cli 读取不需要许可，但只写入人在授权范围文件里允许的内容。这个 JSON 文件由人来写；或者人在自己的消息里把目标授予 Agent，由 Agent 把这份授权写成一份自己的授权范围文件，并说明写了什么。没有命令会写这个文件，Agent 也不会因为文档里的要求去写。creo-cli 从 `CREO_CLI_SCOPE_FILE` 指定的路径读取它；没有设置这个变量时，读取状态目录里的 `scope.json`，不从其他任何地方读取。

```json
{
  "scope_id": "demo-rework",
  "effects": ["change", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/projects/demo/"],
  "expires_at": "2027-01-31T18:00:00Z"
}
```

| 字段 | 含义 |
|---|---|
| `scope_id` | 这份授权的名称；操作记录会带上它 |
| `effects` | 写操作可以有的效果；读取不需要授权范围 |
| `dangerous` | 是否允许危险级的操作 |
| `targets` | 写操作可以触及的对象的目标键前缀：`file:///D:/projects/demo/` 覆盖这个文件夹下的所有文件，`untitled:` 覆盖新建的文档，`device:<id>` 覆盖一台设备 |
| `expires_at` | 授权到期的时间，用 UTC |
| `confirm` | 可选；设为 `always` 时，除停止工作外的每个写操作都要等人批准预览后才执行 |

授权范围不覆盖的写操作什么都不改，返回 `E_FORBIDDEN`，说明缺什么，并给出一段人可以直接粘贴进文件的片段。`creo-cli context` 显示当前生效的授权范围，`SECURITY_zh.md` 完整说明了授权范围。

creo-cli 的命令需要这些效果：

| 效果 | 命令 |
|---|---|
| `change` | `dimension update`、`parameter update`、`feature update` |
| `artifact` | `model export`、`model render` |
| `lifecycle` | `doc open`、`doc close` |
| `persist` | `doc save` |
| `configure` | `plugin install`、`plugin remove` |

`doc close --discard` 会丢掉没保存的修改，属于危险级，还需要 `"dangerous": true`。在一个文件夹里修改并交付模型的授权范围大致如下：

```json
{
  "scope_id": "bracket-rework",
  "effects": ["change", "artifact", "lifecycle", "persist"],
  "dangerous": false,
  "targets": ["file:///D:/work/bracket/"],
  "expires_at": "2026-12-31T23:59:59Z"
}
```

## 关于本工具

Creo Parametric 是 PTC 的参数化三维 CAD 软件：零件、装配和工程图都由特征组成，特征由尺寸、参数和关系驱动。creo-cli 驱动同一台 Windows 电脑上由人启动的 Creo Parametric 会话，经由 Creo 启动时加载的一个小宿主组件。

常见任务：

- 回答关于模型的问题：体积、质量、大小和材料，按顺序的特征，尺寸、参数和关系，以及装配里的元件。
- 修改设计：尺寸的值或公差、参数的值，或者隐含、恢复、改名特征。Creo 会重新生成模型，重新生成不了的值会被撤回。
- 交付：保存模型，导出 STEP、IGES 或 STL（工程图导出 PDF），或者把模型窗口拍成 JPEG 图片。

```bash
creo-cli doc open --doc D:/work/bracket/bracket.prt
creo-cli dimension list --doc bracket.prt
creo-cli dimension update --doc bracket.prt --id DEPTH --length 12mm
creo-cli doc save --doc bracket.prt                   # 两步确认：列出上次保存以来的全部修改
creo-cli model export --doc bracket.prt --output D:/work/bracket/out/bracket.stp
```

1.0 版不新建模型和特征，也不修改装配和工程图；它读取并导出它们。

## 配置

| 变量 | 默认值 | 含义 |
|---|---|---|
| `CREO_CLI_STATE_DIR` | `~/.creo-cli` | 状态目录：操作记录、锁、更新检查的缓存和团队知识的登记 |
| `CREO_CLI_SCOPE_FILE` | 状态目录里的 `scope.json` | 授权范围文件（见「授权」） |
| `HTTPS_PROXY`、`HTTP_PROXY`、`NO_PROXY` | 未设置 | `update` 和 `doctor` 用的代理，只有这两个命令访问 npm 仓库 |
| `CREO_CLI_JDK` | `PRO_JAVA_COMMAND` 所在的 JDK，否则 `JAVA_HOME` | `plugin install` 构建宿主组件用的 JDK 25 |
| `CREO_CLI_VCVARS` | 最新的、带 x64 C 编译器的 Visual Studio | `plugin install` 编译宿主组件 C 库用的 `vcvars64.bat` |
| `CREO_CLI_FAKE_HOST` | 未设置 | 只用于测试：把每次调用发给模拟宿主而不是 Creo Parametric，并把每个结果标为模拟结果 |

### 怎样找到 Creo Parametric

- 安装：creo-cli 在 `C:\Program Files\PTC`、`C:\PTC`、`D:\PTC` 和 `E:\PTC` 下最多往下找四层，找含有 Object TOOLKIT Java（`text\java\otk.jar`）的 `Common Files` 文件夹。版本取自安装文件夹的名字，如 `Creo 13.4.1.0`。`creo-cli doctor` 显示找到的结果。
- 运行中的实例：每个运行中的 `xtop.exe` 是一个会话，ID 由进程号和启动时间组成，如 `creo-9184-1d9a4c2e`。`creo-cli session list` 列出它们；Creo 里开着模态弹窗时显示为 `blocked`。
- 宿主组件：会话只有加载了宿主组件才能驱动。creo-cli 以源码发布它：`creo-cli plugin install` 用 JDK 25 编译它的 Java 部分，再用 PTC 的 `protk_unlock` 解锁；解锁需要许可证服务器上有 Creo Object TOOLKIT Java 开发许可，或者它的扩展许可加 Creo TOOLKIT 许可，运行需要 Object TOOLKIT Java 的运行、开发或扩展许可。`plugin install` 还会编译它的 C 库（画草图和关闭 Creo 要用）：用 Visual Studio 2022 的 C 编译器（或者装了“使用 C++ 的桌面开发”的 Build Tools），对着你的 Creo 里的 Creo TOOLKIT 组件编译，再用 Creo TOOLKIT 开发许可解锁；缺这些时照样装好 Java 部分，只有要用 C 库的命令被拒绝，并说明原因。先运行 `creo-cli plugin install`，在 Creo 启动用的 `config.pro` 里加一行，再启动 Creo：`toolkit_registry_file <install_path>\protk.dat`，`install_path` 是 `creo-cli plugin get` 显示的文件夹，在 `%LOCALAPPDATA%\creo-cli\host` 下。升级时这一行不用改；creo-cli 从不修改你启动 Creo 用的 `config.pro`。Creo 只在启动时加载宿主组件，所以升级后要由人重启 Creo。
- creo-cli 启动的 Creo：`creo-cli session open` 从宿主组件旁边的 `start` 文件夹启动一个自己的 Creo，那里的 `config.pro` 加载宿主组件，并设 `open_protk_unsigned_apps always`，让这个 Creo 不问就加载没有签名的 C 库；你自己的 Creo 设置不变。`session close` 像“文件 > 退出”那样关闭这种 Creo，有模型没保存时拒绝。
- `CREO_CLI_STATE_DIR` 改变状态目录的位置，`protk.dat` 和宿主组件写的发现文件也随之移动。

## 卸载

先在 creo-cli 还装着的时候卸载宿主组件。和安装一样，卸载也是两步确认的写操作，需要允许 `configure` 的授权范围。运行中的实例仍在使用的版本会留在磁盘上；关闭 Creo Parametric 后再运行一次命令即可删除。

```bash
creo-cli plugin remove
creo-cli plugin remove --confirm <token>
```

趁 npm 包还在、能列出 Skill 名称时，删除已安装的 Skill。用 bash：

```bash
for skill in "$(npm root -g)/@fateforge/creo-cli/skills/"*; do rm -rf ~/.agents/skills/"$(basename "$skill")"; done
```

用 PowerShell：

```powershell
Get-ChildItem "$(npm root -g)\@fateforge/creo-cli\skills" | ForEach-Object { Remove-Item -Recurse -Force "$HOME\.agents\skills\$($_.Name)" -ErrorAction SilentlyContinue }
```

复制过 Skill 的其他 Agent Skill 目录，如 `~/.claude/skills/`，也照此删除。然后卸载 npm 包：

```bash
npm uninstall -g @fateforge/creo-cli
```

在 Windows 上，如果 npm 全局 `node_modules` 文件夹（`npm root -g`）里有 `.creo-cli-trash`，也把它删掉；状态目录在另一块磁盘上时，`update` 会把旧的程序文件放在那里，等下次运行再删。

最后删除状态目录：`~/.creo-cli`，或 `CREO_CLI_STATE_DIR` 指定的文件夹。里面有操作记录、锁、默认位置的授权范围文件和团队知识的登记；想保留记录就留着它。

```bash
rm -rf ~/.creo-cli
```

```powershell
Remove-Item -Recurse -Force "$HOME\.creo-cli"
```

## 开发

creo-cli 用 Python 写成，建立在 `creo_cli/_driver/` 里的驱动运行时之上；这是固定副本，从不修改。领域命令在 `creo_cli/commands/`，适配层在 `creo_cli/adapter/`。
宿主组件的源码在 `plugin/`。

```bash
python -m pip install --require-hashes --no-deps -r requirements-dev.txt
python scripts/spec.py check
python -m unittest discover -s tests
python scripts/spec.py suites
```

测试和一致性测试都用模拟宿主，从不需要 Creo Parametric。工作流程、行为矩阵和真实软件运行见 `CONTRIBUTING_zh.md`。

## 链接

- 规范：[tool-driver-cli-spec 1.0.0](.agent/)，固定副本在 `.agent/`
- [CHANGELOG.md](CHANGELOG.md)：每个版本的改动（英文）
- [SECURITY_zh.md](SECURITY_zh.md)：安全模型，以及怎样报告漏洞
- [CONTRIBUTING_zh.md](CONTRIBUTING_zh.md)：怎样参与贡献
- [docs/APPLICATION_zh.md](docs/APPLICATION_zh.md)：Creo Parametric 的能力调查
- [docs/COMPATIBILITY_zh.md](docs/COMPATIBILITY_zh.md)：creo-cli 在哪里能用
- [docs/E2E_zh.md](docs/E2E_zh.md)：真实软件验收及其记录
- 问题跟踪：<https://github.com/fatecannotbealtered/creo-cli/issues>
