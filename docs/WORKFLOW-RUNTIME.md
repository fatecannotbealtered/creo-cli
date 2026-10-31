# 有依赖工程任务的公共运行时

版本保持 1.1.0-beta.1，固定规范 v1.0.2。workflow run 复用原编译器和顺序执行循环，
父操作和每个叶写入都使用现有公共计划、scope、漂移检查、实际读回与原子回执；没有平行执行器。

## 本轮支持

1..32 个顺序 read/select/assert/write 步骤，失败策略固定 stop。
模型已在当前实例打开；model/of/component 和文件 output/path 在执行前为明确字面值。
命令参数可引用第一步写入前的实际读取和唯一选择；后续选择与断言仍可读取变化后的模型。
选择/断言必须基于独立读取，不能使用 setter 回显。

允许的叶写入由 reference 和 workflow_tasks.SUPPORTED_WRITES 公布：参数/关系/尺寸、模型再生成与保存、
指定图纸标注/注释/视图调整、STEP/PDF 导出、特征改名和单次抑制/恢复。
每个叶计划必须能在初始状态检查参数与范围；需要尚不存在对象或模糊未来类型的步骤拒绝。
不支持创建/导入/打开/关闭对象、嵌套 workflow、危险写入、未迁移叶命令、动态目标/输出、
取消、continue_independent、自动续跑或迟到回执路由。原有创建式 workflow 示例改为准备模型后运行。

第五轮加入图纸表格增删移动、注释删除和自有参考尺寸删除。表格/注释/尺寸必须在初始状态能明确定位；
创建表格后用动态输出ID驱动后续步骤仍不支持，先独立创建、读取ID，再计划编辑任务。
模型拥有的尺寸使用hide，不能经remove删除；格式拥有的表格拒绝删除。

## 计划、范围与操作记录

workflow plan 是结构与读取前缀诊断；真正公共计划用 workflow run --dry-run。
预览绑定完整输入、所有模型及递归依赖的身份/版本、范围文件哈希。
父计划保留每个初始叶计划的binding，包括已有版本文件的字节摘要。确认前重新检查，
不能把文件名相同、内存未变但磁盘字节变化接纳为新基线。
执行期间逐步核对全部相关模型版本、声明输出及scope/权限/工作区配置。只有读回通过的保存
所证明的单一新版本、导出所证明的确切产物可推进文件账本；旧版本、其他对象或配置变化拒绝。
叶计划的随机暂存路径仍由已有导出边界归一化；目录不是模型文件或产物。
模型内存变化以授权叶步骤的读回及后续依赖快照衔接，公开保留检查与API调用之间的竞争窗口；
不声明对界面或外部写入者的原子隔离，也不检测任务依赖范围外的任意文件变化。
每个模型版本包含原生 model.show、参数和关系读回；共享子件去重，循环、超过32层/1000模型、
子件缺失、身份/读取不完整均拒绝，不能静默略过。

确认前检查全部叶效果、危险性、模型存储目录、产物/暂存目录、目标选择器和剩余次数。
次数预算为一个父操作加所有叶写入；读取、选择和断言不增加原生写入次数。
实际执行前叶操作再次生成公共计划并单次确认，其 operation_id 在派发前登记并关联父操作。
父 workflow 表列出步骤状态及结果引用，叶操作查询含 workflow_parent_id/workflow_step_id。

operation show 查询父计划/回执与 workflow；workflow show 返回保留 trace 和公共 workflow。
确认成功 data.workflow，失败 error.details.workflow，都采用固定规范 workflow Schema。
read/select/assert 的 operation_id 可为空，写步骤 ID 在叶预检时登记；不假称尚未执行的步骤有完成回执。

## 失败与恢复

全部步骤完成才成功。前面完成、后面失败保留已应用、已保存及已生成产物，报告 partial；
回复丢失或无法可靠记录最终结果保留 unknown。未尝试步骤标 skipped 并说明 stop 原因。
没有整批回滚。错误优先级与五维回执由固定规范决定，不以返回码或文件存在推断工程成功。

保存状态按对象和顺序聚合，并保留独立最终modified读回。单个对象先保存后修改报告unsaved；
一个对象saved、另一个unsaved或必要保存失败报告partial；子保存partial不会被压成unchanged。
已知无变化的保存失败保留unchanged，未知保存保留unknown，未执行保存不冒充成功。
导出只增加artifacts，不证明原生模型saved。extensions.creo.object_persistence给出对象状态和子操作证据。
全部步骤执行完成但保存维度partial时仍返回E_PARTIAL、持久父记录为partial，后续相关写入阻断。

公共回执与终态同一次可靠 UPDATE；最终写入失败时磁盘保留 running/finalizing，查询报未知，
相关写入阻断。仍能查询独立叶操作。重复提交原令牌拒绝，不重放已执行步骤。

恢复仅提供独立结果登记：读取实际模型、文件和叶记录后，以 operation resolve 登记子操作和父操作。
原回执、失败与未知证据不改写。随后另写只包含未完成目标的明确任务，重新预览；
不提供自动 resume，不根据新实例中旧模型缺失判旧操作未应用。

## 工程与公开行为覆盖

原生安装板副本任务依次读取/断言、参数驱动、再生成、独立尺寸/体积检查、关联图纸检查、
明确更新视图、编辑说明、保存零件/图纸及导出 STEP/PDF。
保存重开与再次参数编辑证明原生可编辑性；STEP 单独重新导入核 mm/体积/边界/孔面，
PDF 全部页面渲染并单独目视检查。定位 REF 保持参考含义，不改成制造检验尺寸，不补公差。

tests/test_dependency_workflow.py 覆盖公共 CLI 计划/执行/查询、全步骤 scope/预算、
输入依赖漂移、中途断言 partial、回复丢失 unknown、最终父回执写入失败和重复提交。
tests/test_workflow.py/test_resource_tasks.py/test_meta_contract.py 覆盖声明、示例、
类型/前向引用/不支持范围及独立读回 trace；第三轮三个修复的测试继续运行。
这些是本轮公开行为的有界覆盖，全树 FCC 仍 partial，不能从叶命令调用次数提升。

tests/test_workflow_consistency.py覆盖部分保存、对象混合状态、先保存后修改、版本字节/输出/配置漂移、
授权连续保存、未知回复、最终父记录尺寸限制及公共operation show。tests/test_drawing_edit_runtime.py
与既有资源FCC测试覆盖迁移图纸路径的scope、陈旧确认、所有权、无效果失败和读取不完整。
原生run_workflow_state_case保留自有旧版本故障注入前后哈希，登记实际partial后只执行明确尾任务；
run_drawing_edit_case核对表格/删除对象、其他资源、保存重开与PDF全部页面，视觉结果另列。

测试入口为多步workflow使用CLI已有300秒整命令预算，单个调用/读回仍有明确边界；预算耗尽不取消已派发原生操作。

## 本轮公开行为到测试的对应

| 公开行为 | 测试/原生证据 |
|---|---|
| assembly来源出图受unknown子件阻断 | DependencyClosure direct/nested/child revision；run_dependency_case 原生副本 |
| recursive完整性/共享/边界 | DependencyClosure shared/cycle/depth/count/missing identity |
| 公共计划与父子查询 | PublicWorkflow parent plan；typed task trace；workflow show |
| 全步骤scope与预算 | PublicWorkflow later effect denial/whole budget/scope drift |
| 部分完成与保留结果 | PublicWorkflow mid-assert；原生注释保护失败前15步保留 |
| 真实写后回复丢失/重复拒绝/有依据登记 | run_workflow_loss_case saved version + model读回，partial登记后新尾任务 |
| 最终公共回执失败仍未解决 | PublicWorkflow final parent commit failure +第三轮三项回归 |
| 原生可编辑到保存重开/STEP/PDF | run_workflow_case +独立导入/全页PDF消费者，目视另列 |

此表是有界行为覆盖，不是119条命令的FCC认证；reference仍声明partial。

## 第六轮收口

叶request JSON使用初始解析内容，绑定来源路径、实际解析路径、字节摘要和文件身份。
relation set、drawing layout apply、drawing table add以及带request的读取统一纳入输入清单；
每个步骤及叶确认前检查，前序授权保存只推进对应模型版本，不推进请求文件。
文件变更、同字节替换、删除/不可读均拒绝；之前完成的子回执和效果保留，下游跳过。
叶stdin请求不具备可重复读取来源，明确拒绝；使用inline JSON或普通文件，不扩动态workflow。

无净值变化不等于模型干净。父保存状态结合叶结果与最终modified，true必须unsaved（保留partial/unknown）；
独立clean且无应用变化时保持unchanged，有已验证保存时才saved。缺失读回不能降成确定状态。

表格创建/移动本轮只支持单页；移动只支持实际所属页上的一个分段。
使用原生GetOutline、GetOrigin和分段页变换得到的完整范围，平移后四边必须都在实际页内；
缺少原始范围、实际页或有效单位时E_VERIFY_INCOMPLETE，多页E_UNSUPPORTED。
预览展示请求锚点、原/新外形、页号、单位和页边界；确认重新读取，写后核对外形、位置和单元格。
此处仅为页内保护，未实现通用自动布局或制造图签核。删除注释/自有参考尺寸后，保存重开再次检查缺失和关键尺寸保留。

第七轮四条装配／BOM／标题栏路径单独预览与确认，未加入有界 workflow 叶支持集合。
需要新表格 ID 时必须先独立读回，再建立下一段操作；不把准备脚本或顺序调用解释成动态 workflow 支持。
本轮保存回复丢失和最终父回执故障仍通过现有 workflow 的明确模型／有限步骤范围执行。

## 材料与数字公差组合

既有 `material assign`、`model set-tolerance-standard`、`dimension set-tolerance` 接入同一顺序生命周期。
仍限定已有模型、明确对象及路径、最多 32 步。数字公差支持 plus_minus、symmetric、limits；
含工程属性的任务可与再生成、保存、已有图纸编辑和 STEP/PDF 导出组合。
其他几何编辑与 basic/nominal/fit 混排没有阶段转换证据时，整体预览拒绝；不影响不含属性的旧任务范围。

预览中的 `engineering_property_profile` 列出模型、前序标准步骤、限制和文字扩张提醒。
待执行标准步骤只构成明确前置条件。后续公差写入必须核对前序成功子回执、保留的数字值、
实际标准／类别和解除后的表归属，再重新执行普通叶门禁；没有执行期豁免。

MTL 输入的路径、解析路径、物理身份和字节摘要加入原文件账本，scope 观察授权同时检查。
文件不随前序合法保存推进；同内容替换、删除、内容变化或库解析改指另一文件均拒绝。
材料／公差属性账本只采用叶 verifier 已校验并保留的独立快照，不接受事后重新采样的新值。
首步前、步骤间和末尾均检查，避免全部叶 completed 掩盖最后一次外部漂移。
父回执的 `extensions.creo.final_validation` 与子回执分别保留；末尾验证失败不抹去已完成事实。

三个既有叶路径的迁移数仍计一次，workflow 组合验收单列；没有新增命令或自动续跑。
