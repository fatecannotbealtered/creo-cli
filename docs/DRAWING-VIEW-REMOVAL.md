# 有界视图删除与图纸续接

本配方用于自有测试图纸上的既有 `drawing view remove`。先读取实际对象，再预览确认；
不隐式删除关联尺寸、注释、气泡或其他视图。创建式 workflow、通用自动排版和制造签核不在范围内。

## 范围和预检

输入是单页图纸、一个已加载零件来源、一个明确的非背景 general 视图。读取真实视图 ID、
名称、所属页、模型、父子关系、剖视和对齐信息，以及图纸各类资源、源零件几何和保存版本。
每类资源最多 256 项，源零件最多 128 个特征／4096 个几何项，保留快照最多 256 KiB。
这些是本路径的上限，超过后拒绝，不截断后继续删除。

预览列出已知依赖。存在投影／剖视后代、关联尺寸、注释或气泡时拒绝级联。
符号实例、基准标记、GTol 及模型引用表格的完整删除关系尚未覆盖；普通表格也只接受完整读出的
静态、未合并单元格。其他组合提前拒绝。

DETAIL_ENTITY 仅接受完整读取的普通直线：原生 ID、所属页、附件视图 ID／背景标志、
单位及经实际页变换得到的两个完整 XYZ 端点均绑定。相同数量不能证明图元保持；
端点或归属变化也算变化。弧线、其他曲线、目标视图上的图元及任一读取缺口在预览拒绝，
不将 null 摘要、读取失败或未知类型当空集。模型读回中的 `draft_entity_readback`
明确报告完整性；传统 `draft_entities` 数量和 `draft_arcs` 不再独立充当保护证据。

在本机 Creo 13.4.1.0，未对齐的通用视图可能在 `GetAlignmentInstructions` 返回
`XToolkitBadInputs`。PTC 对该错误的定义不是“无对齐”；不能据此假定没有依赖。
多视图图纸只要存在相关对齐读回缺口就拒绝。
只有完整清单中仅有一个视图时，才能独立证明不存在其他视图指向它的依赖；
其自身对齐 getter 的错误仍保留在预览中，不改记为读取成功。
本机的正向验收范围须以当轮证据为准，不能把夹具中的多视图通过当成实机覆盖。

页级自由注释可能引用原生背景视图。通过原生 `GetIsBackground` 判断，不能猜
`overlay_view` 名字或数字 ID。未放置的符号定义和已放置符号实例分别处理。
注释的 `sheet` 来自其真实 attachment view 的 `GetSheetNumber`；位置与文字框使用该页变换，
不使用当前活动页。缺少或不一致的页归属阻断删除，不能因为清单只有一页就补造成功读回。

PTC 的部分列表接口以 null 或明确的 `XToolkitNotFound` 表示空集。适配器只按已核对的
具体 API 语义处理这些返回；许可、输入、内存或其他异常仍失败，RPC 缺少 items／completed
等字段仍报验证不完整。基准标记空集还与模型项枚举交叉核对。

接口依据：[视图关系](https://support.ptc.com/help/creo_toolkit/otk_java_plus/usascii/creo_toolkit/user_guide/Drawing_Views_And_Models.html)、
[对齐读取错误](https://support.ptc.com/help/creo_toolkit/protoolkit_pma/r13/german/creo_toolkit/api/dita/911.html)、
[图元列表空集](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r11.0/usascii/creo_toolkit/api/dita/c-pfcDetail-DetailItemOwner.html)、
[基准标记遍历空集](https://support.ptc.com/help/creo_toolkit/protoolkit_pma/r13/spanish/creo_toolkit/api/dita/3822.html)。

## 执行和保存重开

1. 从合格原件复制到新的自有目录；检查实际模型 origin，确认使用的是副本。
2. 通过 `reference --command 'drawing view remove'`、`drawing view list/show` 发现语法及真实对象。
   查看图纸、源模型和相关标注；不要套用旧案例 ID。
3. 用相同模型和实际视图名称或 ID 执行 dry-run。确认 can_apply、所属页、依赖、文件状态和范围。
   保存本次 operation_id；有未完成读取或冲突时先处理原因，不自动生成新确认。
4. 确认后独立读取目标确实消失，其他受保护视图／资源、源零件几何和原保存文件保持。
   成功删除通常是 applied＋unsaved；它不包含保存。
5. 独立保存图纸；先关闭自有图纸，再关闭其自有零件，重开保存文件，再次确认删除保持。
   用单独预览的普通注释或支持的视图编辑证明可以继续编辑。
6. 从冻结状态导出 PDF，实际渲染查看所有页。绘制和放置阶段检查已有布局反馈；
   自动几何／边界检查与目视分别记录。保留 REF，不增加未知公差或签核。

历史 `drawing item remove --item view:...` 不再提供另一条删除生命周期；它会指向专用入口。
该叶命令没有因此加入 workflow 的支持集合，也没有自动恢复或撤销能力。

## 失败后仅执行明确剩余动作

陈旧预览、身份／文件／范围变化和重复确认在修改前拒绝。真实派发后丢回复或回执存储失败，
用新进程查看原 operation_id；不要再次删除。

`operation query --id ... --model ...` 独立读取当前图纸和源几何，不结清原记录。
登记会复核保留意图：只缺少目标视图不足以登记 applied；非目标变化必须保留，
读不完整或实例代次不匹配保持 unknown。证据充分后，预览／确认 `operation resolve`，
再单独执行剩余保存、关闭、打开或导出。历史原回执和失败记录不覆盖。

登记后的新进程 `operation show` 在 `view_removal_inspection` 提供保留证据的 ID、摘要、
登记结论、检查计数和来源。它只读本地历史，不观察 CAD；query 才按当前 scope 观察保留路径。
该字段位于 `operation_status.extensions.creo`，未扩展固定规范的顶层字段。
证据丢失／篡改时保留原回执和登记，标记 unavailable／invalid 并阻断冲突写入，不重新删除。
旧记录未保留完整图元时明确显示该边界，不能由两次相同的不完整读回推定 applied。

`evidence_integrity=valid` 仅表示保留文件摘要匹配。缺少完整实体、空列表与原计数矛盾、
明细字段缺失等旧观察会得到 `evidence_status=insufficient` 和
`current_requirements_satisfied=false`；原回执和登记结论继续保留，相关写入仍被阻断。
原始基线缺失时，新读回不能倒推出删除前的身份或几何，不编造补验，也不重新删除。

## 动态 SECTION 注释

原生 read_only=true，或实际符号文本中的 `&xsec_name` 已被显示文本解析，均在编辑预览时拒绝。
普通字面文本 `SECTION A-A` 不因此禁用。没有可靠 editability 读回时预览明确提示限制，
不宣称可写；原生拒绝后按完整观察记录效果，不自动重放。可另行预览受支持的尺寸／普通注释位置调整。
