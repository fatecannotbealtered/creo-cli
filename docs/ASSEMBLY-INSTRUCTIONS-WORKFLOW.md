# 支座装配说明图与命名爆炸状态续编

本文供工程师和agent用公开软件包接手现有合成支座。
它是操作配方，不是本轮原生验收通过声明；实际结果以当前交付绑定的逐阶段证据为准。
命令和请求字段从包内`reference --index`及`reference --command`发现。

R33和R34的装配说明工程是保留的历史阻塞，不能用后续副本结果追改。
R34打开P1已保存诊断图时，右视图已可见分离、左参考仍装配，原生Boolean却都为false。
该批打开属性后出现ORDER_DEBUG，View States又要求先Apply；实际选No后Cancel，没有取得命名选择值或执行Apply。
R34没有继续BOM、气泡、保存重开、PDF或35→45mm续编。
历史详情见[R34证据](https://github.com/fatecannotbealtered/creo-cli/blob/880373f4a518972fc0d6a5f940b1b8e69227a8af/docs/evidence/round34-20261018/README.md)和[R33阴性结果](https://github.com/fatecannotbealtered/creo-cli/blob/c0f5b8ed60cfe7a7f6e51639c391b0f9140bfc6d/docs/evidence/round33-20261018/README.md)。
原未保存图纸、回执和停止记录保持；接续只使用外层CURRENT声明的实际范围，不在旧停止实例继续派发。

## R37受限工程收口

S12最终组合的主流程和独立工程师续编均已完成，现有BOM和气泡未重建。独立者仅改普通note文字，保存drw3、五模型正常全关/精确重开、18组零件data及正常装配保持；PDF全部1页和4局部已看。当前候选r25-S12，稳定r20b保留。具体文件、最终现场与失败记录从最终交接 (historical material retained outside this snapshot)及外层CURRENT读取，以下03:09的主流程段落是历史截点。

普通note确认即时行与随后fresh读取出现不同包络，原始角点和矩阵都保留，原因未确定。文字/身份/附着和其他notes的声明检查通过，不等于确认即时包络、跨时点保护或完整自动布局通过。独立PDF目视也不升级这些结论。

## 本轮已发生事实（S12/F3）

本轮产品source为`278a41aea04fe304630b1197940df872602d3e18`，客户端和Java服务同源，DLL仍为R5原字节。受影响源码Python40项、Java21项，共61项；Java39个subtests通过。最终EXE控测为15个case、38次启动及完成，真实native调用和S12 native故障注入均为0。S2/S3/S4等历史不混算；这些软件结果不替代本轮实际工程证据。

F2已建立普通note0、table0及view4的原生气泡18/19/20，并完成一次底板CORNER R1→R1.5。桥板10±0.15mm保持。F2保存版本prt4/asm9/drw1、五次正常关闭及完整空列表各有真实END。F2后来消失的原因未知，新F3不是恢复；旧E/S11、D、C、B、S3停止不解除。

F3使用5份独立物理副本。已实际打开asm9和从副本读取3个零件；官方Unexplode后的正常5实例约束/位置与原初始normal相符，stored state/moves保持。16组完整公开data精确相等，但geometry40/36/29行不等于完整BRep，6项density/CG比较仍incomplete。F3第一控制器正常exit只说明控制器结束，不表示CAD模型已全关。

随后F3 cont1/002保存asm10，004打开drw1，005独立读取view4true/view5false、table0 refs15及notes0/18/19/20。007用真实preview/confirm把note0改为`SYNTHETIC TEST ONLY - LEFT NORMAL / RIGHT R33_SERVICE - QTY BY BOM`，3项文字检查通过、applied/unsaved。008 fresh读回其余notes、完整table和views保持，并取得真实membership与2D box。007直接note row的box/membership范围不同，原始值分别保留；不能把3项文字检查写成边界、重叠或全图布局通过。

本稿事实截止2026年10月22日03:09:48.456259 UTC的cont1正常controller exit。010实际保存新版文字drw2，5次正常close及021空列表完成；随后精确asm10/drw2重开，fresh024正常components/stored states保持，fresh027与保存前008的15组数据精确相等、modified=false、note0 read_only=false。旧007 receipt仍是unsaved，后续保存单独列账。029最终EXE PDF导出已完成，4项文件/header/排他发布检查通过；PDF 48297B，SHA256 `1ad52bbe3b72652fe8227e0567630df926fa2922587ecc1d3f2b1ec7023624a8`，nlink2不等于独立备份。随后pypdf 6.10.0 strict和Poppler完成全部1页解码，root实际看全页及3局部，合成装配识别可读、文字未见clip/overlap。原native receipt的consumer verification仍not_checked，后续consumer和目视证据另列。selected主流程已完成；独立执行者、新包及工程升级仍null。当前F3不再调用drawing create、BOM add、balloons或dimension set；下文保留完整工作流顺序，已完成步骤不能为接续而重放。本次指定保存/全关/精确重开、文字续编和PDF文件/consumer/目视已按上述有限范围取得实际证据；不重放已成功步骤。后续独立者和新包须另行实际执行，不能由本稿预填通过。

扩展drawing-complete-v1只适用于公开eligible命令，最大1200秒，native单请求仍最大300秒；其他普通命令保持总300秒上限。preview/confirm预算必须一致，不自动续期，也不取消已进入的调用。F3文字编辑实际使用1200秒；这不是普通profile验收或性能保证。精确范围见[执行预算](WORKFLOW-BUDGET.md)及包内reference。

当前交接与证据见R37/S12 HANDOFF (historical material retained outside this snapshot)、检查点 (historical material retained outside this snapshot)和机器摘要 (historical material retained outside this snapshot)。稳定工程r20b、58/71、beta/FCC partial、npm关闭与旧STEP/删除/符号/REF/尺寸框边界保持。原S5/S7/S11历史文稿逐字节另存，不将其as-of替换成本稿时间。

[范围与接管](#范围与接管) · [冻结工程](#冻结工程) · [命名平移状态](#命名平移状态) · [说明图](#说明图) · [保存与续编](#保存与续编) · [结果与停止](#结果与停止)

## 范围与接管

沿用三种独立、非家族毫米零件和五个直接组件实例。
桥板左孔保持10±0.15mm，右孔保持6mm；plate、spacer、bridge的BOM保持2/2/1。
不新建另一套样件，不做孔径往返、嵌套或旋转爆炸、动画、删除或符号操作。
STEP仍有独立阻塞，原生装配和PDF通过不能代替交换文件通过。

1. 从包根README和START开始。先做离线完整性检查，再按声明环境连接。
2. 核对当前实例出生代次、父子链、服务身份及实际加载构件。
   环境模板、历史PID、process-only连接都不证明当前CAD读取或写入条件。
3. 确认没有已开始或可能未结束的读取，并建立唯一串行控制权。
   上轮read/0是收尾状态；本轮需要用户的具体写入授权及正常预览，不能修改旧声明冒充授权。
4. 按任务清单逐一核对精确文件、来源、摘要及已实际读取的modified状态。
   原始输入、先前保存结果和失败图纸分别列明，不能把整份清单一律称作saved-clean。
   保留原零件、装配、两张图纸及历史版本；在自有工程副本内继续，不换空历史库或别名。

爆炸状态沿已有路径操作。爆炸图纸视图则要求实际加载的服务支持
`drawing_view_exploded_readback`和`assembly_explosion_context_readback`。
旧R5的普通非爆炸路径没有因此取得新读回能力。
需要新组件时，用独立候选和自有测试实例，分别绑定源码、EXE、JAR和DLL；不覆盖旧R5现场。

## 冻结工程

先读取完整装配和每个零件，再决定分离方向。
记录五个实际occurrence ID、模型、完整路径、活动状态、正常变换及全部约束引用和偏置。
重复零件以occurrence区分，不能按同名模型猜选哪一件。

装配显示状态还有适用语境。正式`Assembly.GetIsExploded`只在assembly mode代表实际装配显示。
当前模型和当前窗口所属模型都必须实际匹配目标装配，才能用该值推导正常位置或执行状态编辑。
图纸语境的显示值不能代替装配状态；上下文缺失、冲突或getter失败也不能填成false。
图纸语境返回的组件position、path transform和bbox也不能未经依据当作原生正常放置。
R33单次视图更新后确有这些原始值变化；没有把它解释成安全显示差异或实际工程损坏。
需要切换工作窗口时，明确记录这次显示操作；dry-run和读取不会偷偷激活模型。

冻结每个零件当前可公开读取的完整列表、原始字段、质量数值、材料字段、公差、特征、尺寸和关系。
公开geometry inventory不是完整BRep；未支持或未读取的范围继续列明。
保留三种零件的已知读取缺项，不把质量属性相同当成完整几何保持。
BOM另以真实模型引用与occurrence集合核对；数量或零件名称相符不代替关联证明。
原两张图纸的资源、视图、尺寸、表格、注释和保存文件保持。

读取装配完整`model show.explosion`，保留全部状态、ID、名称、default、活动标志和有序移动。
`assembly explode show`只能做较弱枚举，不能证明完整移动或活动状态。

## 命名平移状态

选择一个固定参照，并在任务单中记录其真实occurrence ID。
请求不包含该实例的移动；其余四个实例使用明确的装配轴向平移、距离和单位。
先根据正常几何安排分离距离，避免遮挡和过远；目视可读性仍需另验。

使用明确的自有状态名称，保留授权请求文件、文件身份和内容摘要。
从`reference`取得完整请求格式，再按同一参数完成一次dry-run和一次confirm。
确认前的状态、依赖、输入或scope变化会使旧计划失效，不能强用旧token。

确认后，独立读取该名称对应的唯一状态、原生ID、全部移动、组件路径、方向、距离及活动标志。
同一组件最多出现一次；额外移动、错误目标或不完整路径不能靠图像补证。
确认内部临时取消爆炸显示后读取的正常位置，与完成后原始展示位置分开记录。
展示位置减去移动得到的normal是推导值，不是第二次原生正常getter。
正常变换、完整约束和所有未授权对象都要保持。

`ComponentFeat.GetPosition`的正式含义是约束和移动前的初始放置，不能单独证明已约束组件的实际位置。
`ComponentPath.GetTransform(true)`方向为组件坐标到root assembly坐标；比较仍须保持实际model、window和显示语境一致。
正常装配基线要在明确未爆炸的assembly语境中独立读取该路径变换、完整约束及零件几何。
命名爆炸下的显示读取、图纸语境读取和算术推导分别留存，不能互相补成正常位置证明。

已有状态的续编使用明确`replace`和完整期望移动列表；这是原位修改，不是局部patch。
只改任务授权的一个组件分离距离，其余移动原样保留。
独立核对旧状态ID和default身份保持，不能只核对名称和新距离。
该路径不加入workflow；不要隐藏激活、取消爆炸或再次apply来冒充只读观察。

## 说明图

新建独立的单页毫米A3装配说明图，保留原两张图纸。
先安排正常参考视图、爆炸表达、BOM和简短说明，为气泡与引线留空。
预览查看逐页有限布局提醒；新视图创建前的实际外框尚不可读，不能声称已预测完整投影。
每批放置后核对实际范围、文字及引线关系。

### 新图比例与模板路径

新建图时，先用`drawing create --scale`设定任务希望的sheet默认比例。
该参数使用`1:1`或`3:2`这样的比例；`drawing view add --scale`则使用数值，例如`1`或`1.5`。
新源码对空图的首个General View增加预检：显式请求的scale必须精确等于当前独立可读的sheet默认scale。
当前限定为一个drawing model、唯一页1及实际正数比例；缺值、页或模型不唯一时保持incomplete，不猜默认值或放宽数值比较。
完整view清单必须为空，不能只统计前景对象。省略scale或已有view时沿用原路径及原后置保护，不表示可以改变受保护sheet。

例如，新页默认`1:1`时首view沿用默认值或明确使用`1`。
若任务要求首view为`1.5`，应在新图创建时先声明`3:2`，不能让首次view隐式改动已冻结的sheet比例。
首视图比例预检的旧组合原生证据与S4软件结果分别保留，不转移到S5。
S4、S5记录保持各自历史归属。当前S12来源与实际资格另列；源码、编译或历史含表只读结果仍不替代新实例读取。
既有C1视图ID4的原失败与后续另行partial登记保持，只记录当次已检视事实，不能被新预检追认通过。
不为通过门禁删除失败view、改名重建图纸或重放旧确认；既有现场只按实际独立证据和明确授权继续剩余工作。

`--template`的相对路径以`CREO_CLI_WORKSPACE`根解析，不以Creo当前working directory解析。
解析后的文件还必须位于workspace内，且其父目录等于Creo当前working directory；这是另一个独立限制。
建议使用已冻结模板的完整绝对路径。`session cd`不改变本轮已声明的Workspace根，修正路径后仍要建立新预览。

先用实际视图ID、名称、页和模型核对正常与爆炸视图。
`exploded_display_readback`应分别来自原生`WView2D.IsExplodedState`，不能使用请求参数或setter回复。
装配当前活动状态是另一项观察。逐视图命名状态引用仍为`not_checked`，不能由活动名称代填。
创建指令不是完成后的显示证明。新组件在一般视图设置结束后，用正式视图状态setter设置一次
请求的爆炸显示，再由独立读取判断。若失败，已创建对象和辅助资源保持，不自动重建或删除。
即使Boolean通过，实际投影仍可能不符合已冻结的分离要求。
这种情况应停止后续制图和续编，保留原selected-check回执及另行工程失败；不倒改原回执。
源保护保留完整状态库存和实际工程字段；跨语境不适用的display字段另列未检查，原始观察仍留存。
同页表达只有在实际Boolean、投影及保存重开结果均成立时，才可报告工程可用。
若当前工程无法保持两种表达，就保留失败，采用分开的受支持图纸或输出；不隐藏状态切换。

### 命名状态的GUI辅助对照

当前没有已建立的逐视图命名状态Java/C设取路径。`--exploded`只请求Boolean显示开关，
冻结装配active状态不表示为图纸视图选择了该状态。新的预览和回执会直接列出这项未验证范围。

已明确授权的R34对照只用完整保存来源的独立副本和新实例。原R33未保存图纸、原回执和七份磁盘输入保持。
先核实副本中正常与命名爆炸的实际位置、完整约束和几何，再检查目标视图ID、页、模型及投影方向。
选择能把X和Z分离方向投影到纸面的斜视方向；沿视线的位移可能不可见。请求的方向名称不代替实际投影观察。

按[PTC Creo13官方步骤](https://support.ptc.com/help/creo/creo_pma/r13/usascii/detail/To_Create_an_Exploded_View.html)，
在目标Drawing View的View States页先观察实际Boolean及Assembly explode state选值，再启用爆炸显示并选择所需命名状态。
若实际选值不同，明确选择已有`R33_SERVICE`并Apply一次；若已选该状态，保留事实，不切换出去再切回。
不使用Customize来另造移动，不改default，不重复更新或新建图纸试到成功。
普通返回的缺项、原生未决和实际工程不符分别记录；出现未决或fatal立即停止该实例。

选择关联、独立Boolean、可见分离和正常装配保护分别验收。若仅GUI实现了选择，就明确报告GUI辅助步骤，
不称CLI自动绑定。实际分离和保护不通过时，不继续BOM、气泡、续编或工程交付。

使用一个已核实来源的原生repeat-region BOM表。
读回真实表格ID、region、每行项号、数量、模型和occurrence集合，核对2/2/1。
然后仅对一个唯一目标视图单独预览并生成原生BOM气泡。
逐项核对新增ID、项号、数量来源、引线模型、根装配、组件路径和实际视图。
当前气泡专有类型和直接note-to-table链接仍未完整读回，结果要保留这两项限制。
不能用普通数字注释代替，也不能启用已知不支持的跨视图气泡组合。

尺寸与公差继续以原关联零件图为准。新说明写明“SYNTHETIC TEST ONLY”。
不添加未经工程确认的装配扭矩、配合、紧固或制造要求。
身份重复、缺页、缺模型或页冲突的范围逐项未检查；空冲突列表不等于安全布局。
文字包络、尺寸线、引线和完整轮廓仍按[图纸读取合同](DRAWING-READING-CONTRACT.md)分别报告。

## 保存与续编

分别保存确有修改的装配和新图纸，记录精确文件版本、身份、摘要和modified状态。
正常关闭相关自有对象，从这些精确文件重开；不discard，不关闭无关现场。
逐项列出装配、三个零件和新图纸的正常关闭及精确重开。只关装配而零件仍在session，
不能写成全部相关模型已关闭；完整空清单只证明该自有实例在那个时点为空。
重新核对五实例、正常放置、约束、命名状态、移动和活动标志、BOM及图纸关联。
缺少保存重开后的原生正常位置读取时，明确标为未检查，不以展示位置推导替代。
同页Boolean、实际投影和命名状态编辑后的图纸更新分别保留证据。

由未参与实现的执行者从新目录接手。他只使用候选包、公开文档、声明环境和任务单。
本次F3有限续编只改note0的literal文字，BOM、气泡和尺寸setter不重放。
若其他任务另行授权一个组件的分离距离续编，必须保持其他移动、正常装配及BOM，并单独取得保存重开证据。
文字续编不等于距离续编通过，也不以孔径往返替代任务。
保留实际求助、首次解析失败和接续；文档修正后的离线复验不计作重演CAD成功。

用最终EXE导出新的PDF，区分文件生成、排他发布、身份与页数、独立解码和目视结论。
逐页看全图，再看重复零件对应、气泡引线、表格、标题和说明的关键局部。
必要调整先预览，只改授权位置；结果不明的移动不能重放。

## 结果与停止

分开报告：命名状态读回、正常装配保护、逐视图Boolean、实际投影、BOM与引线关联、
保存重开、PDF当前可读性、自动布局覆盖，以及独立执行者续编。
新说明图通过不解释或修复旧8条尺寸框的16坐标变化。
目标at/box、REF和旧receipt也不因此升级。

普通已返回的unsupported是缺项，真正pending则停止该实例后续CAD派发。
先用本地`operation show`保存原记录；process-only health和OS观察不证明getter完成。
新Client、重启CLI、修目录或增加timeout都不是恢复方法。
独立确认原调用和实例状态后，才可进入授权工程读取。

对本工作流的模型目标，`operation query`同时需要`--id`和`--model`，不能只给operation ID：

```powershell
creo-cli operation query --id "<原operation ID>" --model "<实际目标模型名>" --compact
```

query以及resolve的预览和确认都可能调用CAD。先独立确认原pending读取和实例状态，不能用它们证明getter已经结束。
query提供当前快照，不自动重建原确认全部后置条件；resolve是人工证据登记，不新增恢复框架。
二者不切换状态、不补建、不重放apply，也不改写原receipt。
无法证明时保持unknown、partial或incomplete，不重复操作试到成功。
R33早期组件确实新增了视图但爆炸Boolean仍为false；原失败图纸与partial登记保留。
其GUI属性预览又产生新的ORDER_DEBUG，未改值或Apply即停止并Cancel一次。
该失败不靠人工显示调整升级成CLI成功；修正组件的有限原生结果以本轮最终证据为准。
P2随后实际取得false／true Boolean，但两投影仍相同堆叠。
一次标准Update Drawing View后仍未分离，源读回另有29处原始差异，原因未定。
没有继续更换名称、重建、反复更新、修改default状态或补做未通过的工程步骤。
保持58/71、beta/FCC partial、npm关闭及原有STEP、删除、符号边界。
