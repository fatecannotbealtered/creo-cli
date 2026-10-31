# 公共发现与诊断

本文供使用候选包的工程师和 agent 查询命令及排查连接。语法完整、公共结构符合固定 Schema，
都不代表全部工程行为通过。工具继续为 beta；全树行为 FCC 为 partial。

## 先选发现视图

```powershell
./creo-cli.exe reference --index --compact
./creo-cli.exe reference --command 'drawing view remove' --compact
./creo-cli.exe context --compact
./creo-cli.exe doctor --compact
```

- 完整 `reference` 列出全部命令、参数、输出条目、错误及分母。
- `--index` 返回固定 v1.0.2 的简表，不附带所有 Schema。
- `--command` 使用精确命令路径时返回 `data.command`，不是旧版 `commands[0]`；
  `data.schemas` 只有该命令的输出条目，`json_schemas` 是它引用的产品结构。
- 公共驱动结构仅列 URN，例如 `urn:tool-driver-cli-spec:scope:2.0`。
  工程师包中的固定副本位于`cli/.agent/driver/schemas/`，例如
  `cli/.agent/driver/schemas/scope.schema.json`；开发检出对应`.agent/driver/schemas/`。
  请显式读取该路径；目录扫描省略隐藏目录时，不能据此认定Schema缺失。
  不再从 `schemas.driver_scope` 或 `driver_common` 读取内联公共 Schema。
- 为保留已有的分组查询，`--command drawing` 等名词前缀仍返回筛选后的完整视图。
  `--index` 与 `--command` 不能同时使用。`--fields` 是后续字段投影，结果自然不再是完整视图。

工程师直接使用`reference --index`和精确`reference --command`查看选项、类型、默认值、枚举、必需性和重复策略。
这两个入口及包内Schema和本文均不需要开发仓库。
示例中的模型名、原生ID、请求文件、operation ID及确认令牌是待提供的具体输入；必填参数仍以params为准。
内置示例经过实际公开解析入口检查；写入示例的解析检查不会执行handler或确认写入。
开发者的command-inventory是源码调查资料，不随工程师包提供，也不是发现或连接的前提。
仍需用独立Schema校验器、实际EXE正反例及选定原生任务检查行为，解析通过不代表工程能力通过。

## 分母和默认值

当前软件声明120条命令、356个叶参数和72条写入门禁入口。
其中`operation resolve`控制工具记录，其余71个入口可能修改目标。
公共`type`按效果分类，因此`operation resolve`为read，
不代表它无需核对原任务授权或独立证据；其旧记录兼容分支仍有预览／确认门禁。
当前59条路径接入公共运行时，另有12条旧路径和1条记录控制分支。
准确清单查询`runtime_migration`；36是调查能力组数。
历史58/71继续统计新增约束命令之前的同一组路径，不改用当前分母。
这些数字分别描述命令、参数、生命周期和调查范围，均不是工程或FCC覆盖率。

参数 `default` 表示解析器得到的值。null 表示未提供；依赖模板、当前模型或其他选项的有效默认值，
在参数说明及实际预览中确定。布尔开关默认 false。带单位的输入注明模型单位、图纸单位或像素，
不能把所有数字都当成 mm。根级 `--version` 不能放在命令后；`--help` 在各层输出人读文本。

所有标量选项只接受一次，包括分散在根级和命令后的重复全局参数；重复值即使相同也拒绝。
未知命令、未知参数、枚举错误、缺必需参数和冲突参数返回 JSON 错误，退出码 2，工程派发为零。
`--json` 是旧兼容别名；同时出现时仍优先于 `--format`。新调用直接用默认 JSON 即可。

## 离线与当前运行状态

默认 `context` 不联系 CAD、不建立操作库。未观测的运行组件和连接均明确为 unknown／unavailable，
不能从配置文件存在推断已经连接。`credentials.configured` 只表示凭据文件存在，不证明令牌有效。
`state.available` 描述已有记录的可读性，不是可写性保证；自定义 Windows 目录未检查 ACL 时报告 unknown。

需要比较声明安装目录与实际加载组件时，显式提供相同的三个路径参数：

```powershell
./creo-cli.exe context --installation '<组件目录>' --creo '<Creo根目录>' --java-home '<JDK目录>'
./creo-cli.exe doctor --installation '<组件目录>' --creo '<Creo根目录>' --java-home '<JDK目录>'
```

显式安装检查读取磁盘组件与本机进程，并可在 CLI 自有目录保存已证明的加载锚点。
它不打开、保存、注册或重启模型／Creo。`--creo` 或 `--java-home` 缺少 `--installation` 时拒绝。
磁盘源码身份和服务握手报告的运行身份分列；不匹配不会报告 `native_backend=pass`。
健康回复、磁盘安装、实际加载、原生工程验证是四种证据。

显式context以实际installation观察构造组件条目，文件或进程已取得观察时不再同时保留相同角色的offline占位。
完整本代加载证据才使`environment.connection.status=connected`；缺少实际证据时仍为unavailable，默认离线仍为unknown。
connected范围只是process-only进程／组件身份，不证明CAD reader、空闲、getter结束或旧操作恢复。
详细证据保留在`extensions.creo.installation`，不能用健康握手、文件存在或旧PID替代。

`doctor` 包含 `authorization`、`native_backend`、`state_store`、`release_readiness`。
退出码 0 表示诊断命令完成，不能代替逐项检查；`checks[].status=fail` 仍是失败条件，
必须读取其 fix。pass 的 fix 为 null。无服务时仍返回安装／连接指引。
`release_readiness.fcc_status=missing` 表示规范要求的完整 FCC 证明尚缺，
`fcc_coverage=partial` 描述现有覆盖；没有把固定枚举改成 partial。

## 历史记录和当前观察的区别

`operation show/list` 读取保留记录，无需 CAD、模型写权限或新的任务 scope。
`operation query` 会读取当前目标并保存查询证据；公共计划重新核对当前目标选择器和保留的观察路径。
CAD 查询提供 `--model`；安装文件查询不提供它，且不要求 CAD 启动。旧记录没有足够身份／快照时，
保留其证据边界，不能据新实例缺少模型登记“未应用”。

存在历史 unknown 不代表所有对象不可写。迁移路径按对象、依赖及文件范围判断；
旧生命周期仍有全局未决门禁。没有具体目标的诊断只报告记录情况，真正的冲突由该目标预览验证。
重复确认拒绝且不重放；独立查询不自动登记，不自动执行剩余动作。

普通缺 scope 的迁移预览不能应用，确认会拒绝；只读发现不会替用户扩大授权。
保存、验证不完整、回执 unknown、观察完成和登记完成分别表达，不能统称工程成功。

本轮 `model set-common-name`、`model discard` 和 `drawing view remove` 的支持边界由各自
`reference --command` 的 limits、实际预览和独立后置检查共同说明。名称读取失败不是空名；
modified 未知不是干净；窗口改变后的 Erase 失败不是未应用。两条模型管理入口仍是显式叶操作，
没有因此扩展 workflow。`operation show` 的 `model_management_inspection`／
`view_removal_inspection` 分开显示登记结果与保留证据完整性；query 的授权失败先于当前 CAD 观察。
完整语法清单仍独立于本轮按具体测试 ID 关联的行为证据，FCC 保持 partial。
