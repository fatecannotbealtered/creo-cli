# 命名爆炸状态与 JPEG 交付

本操作指南面向维护者和调用 CLI 的 agent。它覆盖已有简单装配的展示变更，
不覆盖嵌套装配、动画、通用视图恢复或制造签核。查 `reference` 获取当前参数及 schema。
R8历史验收记录见 `docs/evidence/round8-20261010/`；本地原始工程和失败记录留在 D 盘。
当前三零件、五实例支座的装配说明任务见[装配说明图配方](ASSEMBLY-INSTRUCTIONS-WORKFLOW.md)。
下文40到60mm是历史合成案例，不授权在当前支座上重演。

[冻结输入](#冻结输入) · [原位编辑](#原位编辑与位置判定) · [渲染](#渲染与恢复) · [失败接续](#失败与接续) · [进程中断](#cli-进程中断后的记录)

## 冻结输入

使用独立副本，先读取 `model show` 和 `assembly component list`。
记录模型与文件身份、实际 occurrence、约束引用和偏置、位置和完整变换、单位、体积，
以及 `explosion` 中的全部状态、活动状态和显示标志。已有 unknown 不能重放或用新实例消除。
`assembly explode show`只提供较弱的状态枚举，不能代替完整的`model show.explosion`。
状态库存完整不等于display适用。正式`GetIsExploded`只在assembly mode代表实际装配状态；
新组件用实际当前模型和当前窗口所属模型记录准入依据，图纸语境另列not_checked。
未知、冲突或读取异常不能当作false，也不能据此推导正常位置。
完整读回要包含状态ID、名称、default、活动标志、全部有序移动、组件路径、方向和距离。

`assembly explode apply` 只接受最多十个直接零件 occurrence。一次请求中同一 occurrence
只能出现一次；方向为装配坐标系三维平移方向，距离带明确单位。预览和确认绑定请求文件身份、
内容摘要、模型递归依赖、范围及服务代次。尚不支持的旋转、嵌套路径和不完整读回会拒绝。

先选择本次模型的实际 occurrence，再填写请求，例如沿 Y 方向移动 40 mm。
仓库的 `examples/engineering/explode-translate.json` 是请求模板；其中 occurrence 必须替换为实际读回值。

```text
creo-cli assembly component list --model <owned.asm>
creo-cli assembly explode apply --model <owned.asm> --request <owned-request.json> --dry-run
creo-cli assembly explode apply --model <owned.asm> --request <owned-request.json> --confirm <token>
creo-cli model show --model <owned.asm>
```

## 原位编辑与位置判定

同名状态默认拒绝；明确指定 `replace: true` 才在原状态上更新平移，保留状态 ID，
不先删除旧状态。确认期间会临时切换到正常显示，以原生 getter 独立读取编辑前后的正常位置与约束，
完成后激活本次命名状态。该状态处理属于确认后的写操作，dry-run 和查询不会切换状态。
编辑请求给出完整期望移动列表；它不是只修改一个distance的局部patch。
固定参照实例不出现在moves中，其余每个实例最多出现一次。重复零件按实际occurrence ID区分。
独立验证还比较原状态ID和default身份；同名、相同移动但换了原生ID不算原位编辑通过。

Creo 13.4 的 `ComponentFeat.GetPosition` 和组件路径变换在爆炸显示下包含展示位移。
因此公共读回保留原始展示坐标；验证同时比较完整约束、三维方向、距离、
正常显示下实际读到的位置，以及由展示坐标和原生移动记录推导的正常位置。
推导值与操作内的原生正常位置读回分别标注。图像不能替代这些检查。
回执中`physical_geometry_unchanged`的既有检查只比较质量属性。
它不证明全部零件实体、材料、公差和关系保持。工程任务还要独立冻结并比较这些受保护对象。

保存、关闭自有装配并从新版本文件重新打开后，重新读取状态名称、ID、完整移动和活动标志。
R8合成任务再把 40 mm 编辑为 60 mm，证明保存的状态仍可编辑。
重开时是否保持活动显示以实际读回为准；没有公开的通用 deactivate/restore 命令。
保存重开后从展示位置推导的正常位置，不是保存重开后另一次原生正常getter读取。
缺少后者时保留缺项，不能把派生值改名为实际正常读回。

图纸的爆炸显示也要另行验收。装配活动状态不证明视图自己的爆炸Boolean，
更不证明该视图引用哪个命名状态。新组件的逐视图读回及其缺项见
[图纸读取合同](DRAWING-READING-CONTRACT.md#正常视图与爆炸表达的独立读回)。

## 渲染与恢复

目标必须已经是活动零件或装配图形窗口；非活动窗口、图纸上下文均在写入前拒绝。
当前版本的原生接口不能提供本合同需要的非活动窗口状态读取。
输出为新建工作区 JPEG，尺寸每边 64～4000 像素，不覆盖既有文件。

```text
creo-cli artifact render --model <owned.asm> --view current --width 1280 --height 960 --output <new.jpg> --dry-run
creo-cli artifact render --model <owned.asm> --view current --width 1280 --height 960 --output <new.jpg> --confirm <token>
```

`current` 保留当前取景；明确标准视图通过可逆旋转临时定向。渲染不自动 Refit，
也不重复设置没有变化的屏幕变换或重新激活已经活动的窗口。
临时隐藏的 datum 显示项、旋转、缩放/平移、活动窗口、爆炸状态及 modified 标志均需读回核对。
恢复异常会传播；产生图片不能掩盖恢复失败。

Creo 的光栅导出可能先返回，再完成显示更新。CLI 最多读取三次，要求连续两次完整状态一致，
并与确认前状态比较；所有采样留在结果中。读取失败立即失败，稳定但错误的状态也失败。
此过程只读，不重放渲染、不自动修复模型、不延长无限超时。

JPEG 在私有工作区暂存，完整解码、像素尺寸、非均匀内容与恢复检查通过后，才独占发布到请求路径。
失败保留已经观察到的暂存文件及摘要。`artifact inspect` 仍只证明文件身份和头部，
独立消费者应另行完整解码，并查看全图：组件是否齐全、分离方向是否正确、是否裁切或重叠。
这些目视项目不计为 CLI 自动几何验证。

## 失败与接续

两条路径复用公共 scope、预分配操作 ID、确认、五维回执、依赖漂移和未知阻断。
请求或范围变化、错误 occurrence、重复确认均不能重新授权旧计划。
父子 workflow 不在这两条路径的本轮支持范围内；`workflow run` 会拒绝它们。

发生部分写入、失去回复或最终回执存储失败时，先用本地`operation show`检查原记录。
若有已开始或可能未结束的原生读取，停止该实例后续CAD派发；process-only health和OS观察
不证明getter结束。新Client、CLI重启或更长timeout都不是恢复方法。
独立确认原调用与实例状态后，才可在授权范围内查询实际状态和文件，
再用 `operation resolve --outcome --evidence` 登记有依据的结果。原始回执和失败证据保留。
不重放已完成步骤，不自动发布失败暂存文件，也不把旧状态已丢失报成未应用。
爆炸路径的通用query提供当前快照，不重建原确认的全部后置条件；resolve是明确的人工证据登记。
两者不会切换状态、补建移动或重放apply，不能称为自动爆炸恢复验证通过。

渲染回执的模型变化与产物记录分别阅读：模型未改变不代表没有生成 JPEG；
JPEG 已产生也不代表模型已保存，或现场已恢复。

## CLI 进程中断后的记录

确认后、原生派发前，CLI 必须可靠保留本操作的暂存路径、请求输出、实例和进程归属、
模型及显示快照。记录写入失败时零派发。验证完暂存 JPEG 后，先保留文件身份与摘要，
再独占发布；发布与最终公共回执之间中断，也不能把操作视为安全完成。

新进程可在 Creo 不可用时执行 `operation show --id <id>`。渲染恢复信息在回执的
`extensions.creo.render_recovery` 中，区分：未观察到生成文件、已观察到暂存文件、
可证实归属的已发布输出、证据不完整。这里只读取记录中明确的路径，不扫描目录猜归属。
输出位置出现同名或同字节的新文件，不会借用旧操作的归属；发布判断核对物理文件身份和摘要。

未观察到文件不证明原生操作未执行。保留的模型/显示读回是历史观测，不证明当前现场。
进程消失且租约过期后，缺少最终公共回执的操作保持 unknown，相关写入继续阻断。
独立检查模型、显示和文件后，用原操作 ID 登记结果。查询不修改原记录，不自动发布、
不重放渲染；没有新增归属字段的旧记录安全降级为证据不完整。
