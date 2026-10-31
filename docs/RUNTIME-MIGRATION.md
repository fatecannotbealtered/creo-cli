# v1.0.2 公共运行时迁移

本地候选采用正式规范 v1.0.2，提交 `9607a35fe0ea33fe822e1f2ad2704eae260d4018`。
公共 schema 原样保留在 `.agent/driver/schemas`；未扩大规范。

本轮原生展示候选声明128条命令和78条写入路径。
其中65条接入候选公共运行时，12条保留旧运行时，另有`operation resolve`的记录控制与旧记录兼容分支。
机器清单由当前`driver.migration()`生成，见[runtime-migration.json](runtime-migration.json)，
也可查询`reference.runtime_migration`。这些数字统计软件声明和运行时接线，不表示原生工程已通过。

历史迁移口径继续保留58/71，表示新增命令之前的同一组路径，不把新能力塞进旧分母。
新增源零件外观和display合同不等于当前构件的原生验收通过；自动启动、完整当前模型上下文、持久化和图片内容仍按原生试用 (historical material retained outside this snapshot)分别验收。全链未通过的阻塞保留。
36组调查能力、命令和参数清单、运行时接入、行为FCC及独立工程验收分别统计。

本轮新增`assembly component redefine`的软件实现，供已有直接occurrence原位重定义约束。
v2状态读取绑定实际服务UUID、工程目录和模型origin。
原生Selection的root／leaf来源单独保留。
只允许保持当前数量的3到6条平面mate／align约束，偏移明确使用mm。
被其它已加载装配引用的owner定义拒绝编辑；任意深度实例覆盖和workflow组合未开放。
物理面的原始datum-side读数与不适用语义分开。
正式getter返回null时的零偏移，与缺失字段或读取失败分开。
v2要求服务能力版本2，旧版本1在CAD读取前拒绝。
全部internal datum保留在catalog中，且只用于保护，不能选作新约束输入。
根owner的内部构造面只有在真实归属、唯一consumer和完整索引定义成立时才允许联动。
客户端独立核对约束槽位、坐标框架和consumer实际位姿，其它plane继续严格保护。
默认fit的原始值为`-1`，不适用的读取与失败分开；dimension-driver ID检查仍明确为`not_checked`。
不能只凭offset数值相等认定构造面归属。
详见[已有实例约束说明](ASSEMBLY-CONSTRAINTS.md)。
旧C2007的原始验证失败、另行partial登记及后续保存分列，不能用新规则补签旧回执。
C3产品源码为`30ff5493bcd9ad6ba9e8c157081c7d0eb8213ee7`。
普通零件occurrence的三次原位编辑分别通过68/68、68/68和98/98项独立检查。
首轮编辑后另行保存，正常关闭全部4个模型，并从精确文件重开。
第二轮用新的选择替换合法参考并设为负偏移，再另行保存。
重复零件案例只改目标occurrence至44.25mm，另一个保持-29mm。
该案例随后保存至`.asm.4`，正常关闭全部3个模型，并观察到空会话；尚无该结果精确重开的证明。
重复确认返回`E_CONFLICT`且诊断journal字节数不变，只证明该诊断边界未重放，不证明原生请求终态。
独立执行者使用同一r26-C3最终包，在新工程副本完成另外两次原位编辑。
普通零件带动刚性子装配合法联动，通过132/132项检查；直接修改刚性实例，通过124/124项检查。
第一次保存为`.asm.3`后正常关闭全部5个模型，观察空会话，再从精确文件重开。
第二次编辑另行保存为`.asm.4`，最终5个模型都为saved-clean；未再重开`.asm.4`。
两次确认分别耗时135.476秒和194.167秒，使用各自预览中明确选择的300秒预算。
独立使用保留50条CLI记录，49条成功，最初一次`E_USAGE/not_started`自行修正。
实际观图与getter核验分列，Computer Use已释放；真实原生故障注入仍为0。
这些结果只证明实测的普通零件、刚性目标、datum参考及方向组合，不推广所有侧向或物理平面。
C2关闭问题未关闭，旧记录不由本轮成功补签。详见R38证据 (private historical record)。
后续文档提交不冒充C3构建及执行时的产品源码。
当前59条仍是软件接入数，不能据此宣称新增路径已完成全部原生资格；
r25-S12与稳定r20b继续保持原资格。

第二十一轮迁移既有`feature rib`，限定已完整证明的矩形壳体、单条水平直线筋和朝底填充。
预览保留原请求，冻结实际端点、关联壁底面及方向。只执行一次创建。
原生定义、真实投影引用身份、完整单实体边界及保护状态共同决定结果。
名称检查同时修复shell、draft与普通建模回复的独立清单验证；旧证据缺少名称策略时不自动解锁。
见[加强筋流程](RIB-WORKFLOW.md)。验收分母以本轮最终证据为准，不自动累计历史原生通过。

第二十轮完成既有 `feature shell` 与 `feature draft` 的有界公共生命周期。
抽壳限定独立矩形实心毛坯、明确顶面和均匀内向厚度；原生定义及完整内外边界共同验收，
创建时通过实际驱动尺寸保留请求精度。拔模限定同类实心毛坯的一个正X侧面、顶部+Z基准、
固定中性面／拉伸方向和整数正负角度，比较实际选面归属及完整平面多边形。
本轮未开放薄壁壳体叠加拔模、多面、复杂曲面、分割拔模或创建式workflow。
家族表迁移数量不变，补齐完整列／行／单元格／默认标记和实际泛型归属的意图检查。
回执缺失与必需读回中断分别保留unknown／已观察partial，独立证据足够后才登记；
原始回执与失败记录不改写。详见[抽壳配方](SHELL-WORKFLOW.md)、[拔模配方](DRAFT-WORKFLOW.md)
和[家族表配方](FAMILY-TABLES.md)。具体实测分母和未执行变体以第二十轮交付索引为准。

第十九轮迁移既有 `family-table apply` 和 `family-table remove-instance`，本轮原生范围为一个合成泛型、两行和一个长度尺寸列。实际表格、实例尺寸／实体、泛型及保护对象、文件版本与窗口共同决定结果。已关闭装配／图纸的已知引用不因退出会话而消失；独立登记检查项在不同 CLI 进程间保持稳定。来源读取失败、家族身份不完整和旧版不充分视图证据继续阻断相关写入。见[家族表配方](FAMILY-TABLES.md)和[最终证据](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round19-20261014/README.md)。这两条叶路径没有加入 workflow，discard 保持非家族范围。

第十八轮完成既有 `model set-common-name` 与危险 `model discard` 的独立零件会话合同，同时补齐视图删除的完整直线保护和公开登记证据。名称／modified 不可读时拒绝；已知未保存名称不能因 modified=false 被普通关闭；discard 需同实例保存基线及其他零件／窗口／磁盘保护。两条叶路径未加入 workflow。见[模型管理配方](MODEL-MANAGEMENT.md)与[第十八轮证据](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round18-20261014/README.md)。

第十七轮增加既有 `drawing view remove` 的有界公共生命周期；原生正例先限定完整可证明的单视图删除，多视图对齐读回缺口继续拒绝。公开发现现按固定 Schema 提供 full/index/command 视图，语法清单与行为 FCC 分开。见[发现合同](DISCOVERY-CONTRACT.md)和[删除配方](DRAWING-VIEW-REMOVAL.md)。

第十六轮不增加路径，收口创建首版本的保存证据、图纸尺寸移动的延迟边界读回，
并在现有构造合同内补负偏置、直边／圆柱构轴、阶梯及外部轴完整回转。
同平面肩面按实际连通区域与各自圆缘验证；原始失败、独立使用求助及动态剖视注释编辑拒绝保留。
当前范围和最终源码检查见[第十六轮证据](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round16-20261013/README.md)。
机器清单仍与当前 `reference.runtime_migration` 相同，不以重复验收增加迁移分子。

第十五轮迁移既有 `feature revolve`、`feature datum-plane` 和 `feature datum-axis`。
请求文件身份／字节、实际引用、模型及递归依赖、实例代次和 scope 进入计划，
新 getter 将原生定义／约束与当前几何共同用于验证和独立登记。最终 EXE 的合成轴套、
保存重开、关联图纸／STEP/PDF 和三条叶路径各两种实际写入故障分别留证。
支持范围见[回转配方](REVOLVED-PART.md)与[本轮证据](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round15-20261013/README.md)。
不加入创建式 workflow，不把未实机变体计成通过。

第十四轮不增加接入路径或命令：收口安装源／目标隔离、当前观察授权及公开恢复诊断，
并保持 workflow 子操作成功与父边界失败各自的事实。当时范围为 47/71，组合工程和 FCC 另按证据统计。

第十三轮候选增加既有 service install 的文件生命周期，仍不加入 workflow 叶集合。
它持久化不可覆盖的安装目录；注册、实际加载及工程结果分别检查。
源包、文件身份、目标和操作归属贯穿预览、复制与独立登记；部分目录保留，不自动重放。
适用环境与实际验收结果须按本轮交付索引核对，不能从 47/71 推断加载已验证。

第九轮只修渲染的跨进程中断与记录重建，当时接入路径为 41/71。
暂存/发布归属在派发前写入，缺失最终回执时以保留证据重建 unknown；
文件观测与模型、显示状态分别表达。具体边界见 [渲染恢复](EXPLODE-RENDER.md)。

第十轮迁移既有 `feature hole` 与 `feature round`。请求文件身份/字节、模型递归依赖、
实际几何引用与单位纳入计划；新增原生定义 getter 与当前实体几何共同验证结果。
最终 EXE/JAR 在合成安装板上完成尺寸往返、保存重开及关联图纸/STEP/PDF，
并验证派发前拒绝、真实写入后丢回复和最终回执存储失败。只认证简单直通孔和恒定外边圆角，
不把高级变体或 workflow 组合计入新增验收。见[工程流程](HOLE-ROUND-WORKFLOW.md)与
[本轮证据](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round10-20261010/README.md)。

## 使用范围与计划

第十一轮修复大小写引用、无限基准定位与丢回复后的当前实体登记门禁；
既有 `material assign`、`dimension set-tolerance` 和 `model set-tolerance-standard`
接入公共生命周期。实际 MTL 的路径、物理身份、内容和密度绑定到计划，配置恢复另行读回。
尺寸公差、模型标准和无关几何独立核验，保存重开与图面表达分别记录。
具体范围见 [材料与公差配方](ENGINEERING-PROPERTIES.md)、
[孔／圆角恢复](MACHINING-RECOVERY.md)。没有新增命令，也没有加入这些叶命令的 workflow 组合支持。

用户提供范围文件，或明确授权 agent 准备。CLI 仅读取
`CREO_CLI_SCOPE_FILE`，未设置时使用 `~/.creo-cli/scope.json`。
缺失、无效、过期或撤销时，迁移路径的预览不能应用。
确认前重新核对效果、危险性、模型及依赖目录、输出/暂存目录、目标选择器、
操作次数与范围内容哈希。原有工作区、写入策略和原生实验开关继续生效。
范围文件表达任务授权，不能防御同一用户主动改写授权文件或状态存储。

每次 dry-run 将 `data.preview` 保存为公共 plan，预分配 `operation_id`。
确认沿用该 ID，并在派发之前将记录置为 running；`operation show` 可查询 planned 状态。
计划绑定命令、输入、原生基线、依赖、实例代次、范围哈希和过期时间。
导入前类型未知时，以 import-slot 及可能创建的 `.prt`/`.asm` 对象声明冲突范围；
明确类型的导入只声明该类型。已存在零件、装配、图纸按完整名称区分，端口不是对象身份。
旧导入记录从保留请求解释，不改写历史。新写入也核对模型引用的依赖，避免通过图纸或装配绕过未知操作。
输入/状态/范围漂移及重复确认均拒绝，不能以删除校验恢复执行。
领域预览移至 `preview.extensions.creo`。

## 回执与恢复

成功返回 `data.receipt`，失败返回 `error.details.receipt`。
公共回执分别报告 execution、change、persistence、delivery、verification。
模型保存与本地产物导出分开：导出 STEP/PDF 不表示原生模型已保存，也不表示对外交付。
独立消费者验证属于额外工程检查，文件头通过不会升级为几何或图纸通过。
旧领域结果保留为辅助证据；调用方以公共回执判断结果。

领域结果完成后，现代记录保持 running/finalizing，直到公共回执与最终状态在同一个 SQLite UPDATE 中可靠提交。
公共回执最终写入或记录尺寸限制失败时，磁盘仍保留此前未解决状态；不先写 completed，
也不依赖随后补写 unknown。operation show 报未知，后续冲突操作拒绝；有独立依据后可以登记。
原生错误后读到变化时报告部分应用；读不清或回复丢失时保留未知。
优先级为未知、部分、验证失败/不完整，再判成功。
同一 engine/实例/对象及递归依赖的未解决操作会阻断新计划与确认，换回环端口不能绕过。
命令实际目标与 model/of/component/with 引用共用闭包读取；组件数字 occurrence ID 从装配闭包解释。
原生 metadata、参数和关系参与依赖版本，Getter不全/未加载子件/循环/超过32层或1000模型均拒绝。
进程出生时间与租约用于识别已消失的 CLI 所有者；PID 复用不能冒充原所有者。
过期且所有者已消失的本地锁可回收，原锁证据保留。CLI 退出或租约到期不证明 Creo 操作停止。

```text
operation show --id <原操作ID>
operation query --id <原操作ID> --model <目标模型>
operation resolve --id <原操作ID> --outcome applied --evidence <实际读回和文件依据>
```

resolve 是范围内的本地记录控制，直接形式与规范 SDK 一致；不重试、不回滚、不修改模型，
不覆盖原回执。可选的 dry-run/confirm 仍可预览登记。
活跃或租约未到期的所有者不能被登记替换。旧记录仍用 decision/note 分支；迁移映射如下。

| 原调用/字段 | 本轮迁移路径 |
|---|---|
| preview 中的领域字段 | `preview.extensions.creo` |
| 确认时才分配 operation_id | dry-run 中预分配并持久保存 |
| 顶层 persisted 判断全部效果 | `receipt.outcome` 五个维度 |
| operation show 的旧 receipt/result | 新记录返回 `data.operation_status` |
| resolve decision/note | 新记录用 outcome/evidence；旧记录保留原分支 |
| 没有显式再生成命令 | `model regenerate`，独立读回全部原生特征标志 |

## 仍未迁移或未验证

全树行为 FCC 和未执行的原生变体、workflow 创建/动态目标及自动续跑、
批量操作、取消、自动续跑及迟到回执路由尚未完成。CLI 只同步执行本轮路径；原生任务
独立于 CLI 仍可能继续，未知结果必须人工或 agent 以独立证据登记。
workflow 的现有模型有界串行范围已接入，父操作聚合范围和结果，每个叶步骤保留自己的公共回执。
未支持范围直接拒绝；详见 [WORKFLOW-RUNTIME.md](WORKFLOW-RUNTIME.md)。
材料、复杂特征、图纸表格/符号等其余路径见 JSON 清单。

Scope 路径检查适配了固定规范源码 SDK 的实现；该固定 checkout 未包含 LICENSE。
本轮仅作本地开发交付，发布前需明确这段 SDK 源码的再分发许可。
未新增应用许可、修改安全设置、发布或更改版本号。

第五轮迁移 drawing table add/move/remove、drawing note remove、drawing dimension remove。
复用已有原生接口与独立资源读回，所有权和陈旧确认门禁保留；相关workflow继续使用已有模型的明确ID范围。

第六轮只修已有workflow确认/保存状态与表格移动边界，路径仍35/71；实际表格范围读取字段同步schema，未新增命令或动态workflow。

## 第七轮候选

新增接入既有 assembly component replace、drawing bom add、drawing bom balloons、drawing title-block apply，
没有新增公开命令路径。第七轮当时为 39/71；第七轮收尾对四条路径执行了限定样件的完整工程验收。
此前开发组件的观测与最终组件验收分开，历史失败证据保留；全树 FCC 仍为 partial。

替换绑定候选、generic、递归依赖与源文件版本；确认后重新读取依赖，并比较其他实例的模型、位置和约束。
BOM 绑定实际模板文件及身份，限定已核实的模板字节、mm 单页、单分段与直接零件；未知模板外形拒绝。
C getter 读取真实 repeat-region 与模型记录，气泡通过 native 引线关联 occurrence、BOM 项号和数量。
标题栏保持固定 180×32 mm，核对完整范围及图纸投影；未知人员和材料留空。
这四条路径未加入动态 workflow，也不因此扩大现有 workflow 的支持集合。
收尾修复新增气泡范围、替换失败完整状态、家族加速文件来源和投影圆弧读回。
详见 [装配 BOM 阶段操作](ASSEMBLY-BOM-WORKFLOW.md) 和 [收尾结果](https://github.com/fatecannotbealtered/creo-cli/blob/6d93cf09f74c107ae80970838e136ce69ce328a2/docs/evidence/round7-closeout-20261009/README.md)。


## 第八轮候选

本轮新增的两条既有路径为 `assembly explode apply` 和 `artifact render`。
它们使用公共生命周期，仍不属于 workflow 支持的叶命令。
限定范围、正常/展示位置区别、活动窗口要求与恢复语义见
[爆炸与渲染](EXPLODE-RENDER.md)。迁移数量不是所有工程变体的原生验收分母。

## 第十二轮组合范围

叶路径保持 46/71，不增加迁移数量。已迁移的材料赋值、模型公差标准和数字尺寸公差，
接入现有的有界 workflow：实际材料输入冻结、标准前序结果核对、步骤间及最终属性检查。
创建、动态目标、自动续跑和几何／属性混排未因此开放；组合验收与叶迁移分开统计。
参见 [workflow 属性范围](WORKFLOW-RUNTIME.md#材料与数字公差组合)。
