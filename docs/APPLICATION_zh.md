# Creo Parametric 能力调查

[English](APPLICATION.md) | 中文

本调查记录 Creo Parametric 能做什么、能怎样自动化。它在设计命令之前填写，每项能力都有处置：creo-cli 有命令提供的，处置为 `provided`。

标为“早期 creo-cli”的出处，是本仓库 git 历史里提交 `fd35893` 的早期 creo-cli 的文档和代码，记录的是在 Creo Parametric 13.4.1.0 上观察到的情况。

## 软件

- 名称：Creo Parametric
- 厂商：PTC Inc.
- 调查过的版本：Windows 11 x64 上的 Creo Parametric 13.4.1.0（build 2026163），配 Object TOOLKIT Java 和 JDK 25.0.3；creo-cli 支持 >=13.4 <13.5。其他 13.x 版本以及 Creo 12 和更早的版本从没运行过（早期 creo-cli，`docs/COMPATIBILITY.md`）。

Creo Parametric 能运行的操作系统和 CPU 架构；creo-cli 的平台包按这张表决定：

| 操作系统 | CPU 架构 |
|---|---|
| Windows | x64 |

出处：Creo Parametric 13 只发布 64 位 Windows 版本（PTC 平台支持说明，项目负责人确认）；调查用的安装在 Windows 11 x64 上。

## 自动化接口

Creo Parametric 提供的每种接口，以及调用它的代码必须在哪里运行。CLI 能直接调用的接口，由 `creo_cli/adapter/` 里的适配层调用。只能在 Creo Parametric 的进程里或主线程上调用的接口，需要放在 `plugin/` 里的宿主组件。

| 接口 | 从哪里调用 | 说明 |
|---|---|---|
| Object TOOLKIT Java（`otk.jar` 里的 `pfc` 和 `wfc` 包），在 `protk.dat` 里登记的同步应用（`startup otk_java`） | 只能在进程里、Creo 主线程上 | 建特征用的 `wfc` 元素树接口只在同步应用里有；`otk.jar` 没有异步连接，`pfcasync.jar` 没有 `wfc` 类。需要 `ObjectToolkitJava` 许可选项。13.4 的 `otk.jar` 按 Java 25 编译。从别的线程调用会卡死或崩溃；早期服务每 100 ms 由 `wfcSession.CreateTimer` 的回调取一次队列；`InvokeLater` 会死锁（早期 creo-cli，`docs/SERVICE.md`、`service/.../Service.java`）。 |
| Creo TOOLKIT C（`Pro*` 函数），在 `protk.dat` 里登记的 DLL（`startup dll`），由 Java 通过 `Dll.ExecuteFunction` 调用 | 只能在进程里、Creo 主线程上 | 用在 Java 没有接口的地方：`ProSectionEntityFromProjection`（多实体草图）、`ProDrawingDimensionMove` / `ProDimlocationTextGet`、`ProDimensionDelete`（要 TOOLKIT for 3D Drawings 许可）、`ProBomballoonCreate`、公差标准和小数位、孔的螺纹系列、元件替换、剖面面积、射线求交。构建要 TOOLKIT 的头文件和库，以及 Visual Studio 2022。除非 `open_protk_unsigned_apps` 另有设置，Creo 每次会话加载未签名的 DLL 前都会问人（早期 creo-cli，`service/native/creo_cli_sketch.c`、`docs/SERVICE.md`）。 |
| 用 `protk_unlock.bat -java` 解锁 | CLI，在 `plugin install` 时 | 让 JAR 能在没有开发许可的电脑上运行。解锁需要 Creo Object TOOLKIT Java 开发许可，或者它的扩展许可加 Creo TOOLKIT 许可；解锁后的文件不能再改（PTC《Creo Object TOOLKIT Java 用户指南》Unlocking, Running and Signing the Creo Object TOOLKIT Java Application）。creo-cli 在用户电脑上用用户自己的许可解锁，所以不发布任何解锁过的二进制。 |
| J-Link / Object TOOLKIT 异步模式（`pfcasync`）和 VB API（COM） | CLI（另一个进程） | 只有 `pfc`，没有 `wfc`，建不了特征。不使用（早期 creo-cli，ADR 0002、`docs/HEADLESS-SUPPORT.md`）。 |
| Creo 原生文件（`.prt`、`.asm`、`.drw`，带编号版本 `name.prt.N`） | CLI 能看到磁盘上的文件名和版本号 | 内容是私有二进制格式，只有 Creo 能读写。 |
| 中性格式和输出文件（STEP、IGES、STL、Parasolid、PDF、JPEG） | 由 Creo 读写；CLI 可以算哈希 | 每次导出，Creo 都在文件旁边写一个 `__out.log`（早期 creo-cli，`docs/SERVICE.md`）。 |
| 命令行（`parametric.exe`、`-g:no_graphics`、trail 文件、mapkey） | CLI | `-g:no_graphics` 只能配合异步模式；回放 trail 和 mapkey 没法读回。不使用。 |
| Windows 的进程和窗口列表（`xtop.exe`） | CLI | 找到运行中的实例、它们的启动时间和打开的模态弹窗。 |

## 对象模型

从文档往下，用 Creo 界面和手册里的名称：

- 会话（session）：一个运行中的 Creo Parametric 进程（`xtop.exe`）；它有工作目录、当前模型和会话里的模型。
- 模型（model）：零件（`.prt`）、装配（`.asm`）或工程图（`.drw`），在会话里按名称和类型区分；族表的类属模型和它的实例也是模型。
- 特征（feature）：模型树里的一项，按重新生成的顺序排列，有 ID、名称、类型（拉伸、旋转、基准平面、基准轴、倒圆角、倒角、孔、修饰螺纹、抽壳、拔模、筋、扫描、阵列、镜像、元件等）和状态（正常、隐含、失败）；它的草图（截面）里有图元和草图尺寸。
- 几何（geometry）：曲面（面）、边、轴、基准平面、坐标系和点，在模型里各有 ID。
- 尺寸（`d12`，工程图自己的尺寸叫 `rdd0`）、参数、关系、族表（列和实例行）、材料、外观。
- 装配：元件（按约束放置的元件特征：配对、对齐、插入、坐标系、默认、固定）、分解状态。
- 工程图：绘图模型、图纸（大小、投影方式）、视图（一般、投影、剖面、局部放大），以及视图上的注释：尺寸、注解、表格（包括标题栏和重复区域 BOM 表）、BOM 球标、符号、基准特征符号和几何公差。

## 单位与坐标

- 模型的单位来自它的主单位制，由模板决定：例如 `mmns`（mm、N、s）或 `inlbs`（in、lbf、s）。安装的默认模板决定新零件的单位：调查用的电脑上是英制模板（早期 creo-cli，`docs/SERVICE.md`）。
- 模型坐标：零件的默认坐标系，右手系，原点在默认基准平面 FRONT、TOP、RIGHT 的交点。Java 请求里的角度用度；C 草图库的圆弧用弧度，逆时针。
- 草图坐标用草绘平面自己的两个方向，从两个草绘参考的交点量起；在默认基准平面上就是零件原点。
- 工程图坐标是图纸坐标，以图纸左下角为原点，用工程图的单位。视图轮廓和位置以屏幕坐标返回，要经图纸变换换算到图纸单位；不能再乘一次视图比例（早期 creo-cli，`docs/DRAWING-READING-CONTRACT.md`）。
- 显示设置（`default_dec_places`、`sketcher_strngthn_to_def_dec_pl`）决定 Creo 显示时的舍入，对草图还决定存下来的值：早期服务每画一个草图就关掉这个草图选项，画完再恢复。
- creo-cli 输入和输出都用毫米和度（DCLI-080），由宿主组件按模型自己的单位换算（DCLI-083）。

## 线程与阻塞

- 在 Java 宿主的调用里调用 `ProEngineerEnd` 会让 Creo 崩溃；调用返回后由 Creo 主线程上的 Windows 定时器调用它，Creo 在 3 到 10 秒内正常退出，并调用每个应用的结束函数（在 Creo 13.4.1.0 上实测）。
- 被强行结束的 Creo，下次启动时会弹出模态的“未正常关闭”对话框（检索），直到有一次正常退出（在 Creo 13.4.1.0 上实测）。
- 通过 TOOLKIT C 在意图管理器模式下建的草图没有隐含约束：每条线、每段弧、每个连接点的约束都要写明（端点重合、相切、水平、竖直、等半径），否则 Creo 每留一个自由度就加一个弱尺寸；全部写明后只剩给定的尺寸，改其中一个，约束照样成立，比如对称的矩形改长度后仍然对称（在 Creo 13.4.1.0 上实测）。不用意图管理器时，Creo 自动标注的尺寸标到最近的边上，不是设计里命名的尺寸。
- 基准轴要用 `ProDtmAxis.h` 的约束写法（`PRO_E_DTMAXIS_CONSTRAINTS`）建；旧写法（`PRO_E_DTMAXIS_TYPE`、`PRO_E_DTMAXIS_PLANE1`）会被拒绝。用 `Solid.ExecuteFeatureOps` 加删除操作撤回的特征可能还留在模型里；`WSolid.DeleteFeatures` 能删掉（在 Creo 13.4.1.0 上实测）。
- `WFeature.CreatePattern` 返回的是新阵列里的一个成员，不是阵列特征本身；阵列特征按元素树里给的名字找。`PRO_E_DIR_PAT_DIR1_FLIP` 朝哪边走，取决于方向参考自己的朝向；creo-cli 从第一个副本读出步进方向，反了就翻过来（在 Creo 13.4.1.0 上实测）。
- `PRO_E_STD_DIRECTION` 选的哪一侧，是相对 Creo 自己给草绘平面定的方向，基准平面和实体面不一样；creo-cli 从新拉伸特征的面判断它朝哪边去了，反了就翻过来。
- 工具包的每次调用都必须在 Creo 主线程上执行；同步应用通过定时器回调进入主线程。Creo 13.4 打开模态弹窗时定时器照常触发，主窗口也不会被禁用（用“文件 > 选项”和工具包的消息框实测）；CLI 按窗口标题认出弹窗，人关掉弹窗之前一律拒绝调用。
- 见过的挡住自动化的弹窗：加载未签名工具包 DLL 时的提示（每次会话）、启动时的“检索”“恢复”弹窗、ORDER_DEBUG、视图状态要求“应用”、许可证弹窗，以及锁屏时出现的崩溃弹窗（Intel OpenGL 驱动）（早期 creo-cli，`docs/SERVICE.md`、`examples/engineering/RecoveryIsolation.ps1`、`docs/ASSEMBLY-INSTRUCTIONS-WORKFLOW.md`）。
- 重新生成和长操作期间 Creo 是忙的；实测：复杂装配改约束 135–194 秒，族表预览约 76 秒，BOM 表确认 568 秒（早期 creo-cli，`docs/ASSEMBLY-CONSTRAINTS.md`、`docs/FAMILY-TABLES.md`、`docs/WORKFLOW-BUDGET.md`）。
- 正在执行的工具包调用不能取消；客户端不再等待，并不会让它停下。
- 同步应用不能无界面运行；窗口最小化和锁屏下运行从没验证过（早期 creo-cli，`docs/HEADLESS-SUPPORT.md`）。

## 读回

- 特征：重新生成后再读一次元素树和状态；没有重新生成成功的特征会被报告，并由宿主组件删掉。
- 尺寸、参数、关系：值按原样读回（双精度；早期工具比较尺寸用 1e-9 的误差）。
- 几何：体积用质量属性读出，加 `MP_DENSITY_USE_IF_MISSING`（没有密度也准确）；曲面零件的包围盒偏大。
- 族表：`SetCell` 可能不报错却保留旧值，所以每个单元格都要读回。
- 工程图：用 `ProDimlocationTextGet` 读尺寸文字位置，落点准确（写 (110, 20)，读回 (110, 20)）；已弃用的 `Dimension2D` 读法有偏移；表格原点和注解文字按写入的值读回；视图位置误差在 1e-6 以内。
- 装配：读回求解后的位置（早期工具的误差是 1e-7）；分解显示时，位置里包含分解偏移。
- 导出和出图：按大小和 SHA-256 检查生成的文件；文件内容由 Creo 决定。

## 保存与撤销

- 保存会在模型原来所在的目录（不是工作目录）写一个新的编号版本（`.2` 之后是 `name.prt.3`），没改动也照样写。旧版本留在磁盘上。
- 用 `CopyAndRetrieve` 从模板新建的模型，会立刻以 `name.prt.1` 写到磁盘上，和“文件 > 新建”不同，写在 Creo 的当前目录里（在 Creo 13.4.1.0 上实测）；creo-cli 在复制的那一刻换到目标目录，复制完再换回来。
- `Copy` 用新名字把副本写到 Creo 的当前目录，会话里的模型不变。`Backup` 用原名把模型写到另一个文件夹（路径要以分隔符结尾），之后会话里的模型就属于那个文件夹，下次保存写到那里（在 Creo 13.4.1.0 上实测）。
- 打不开旧的编号版本：指定版本号或带版本号的路径，Creo 打开的都是最新版本，这样打开的模型还存不了盘（在 Creo 13.4.1.0 上实测）。
- 有没有保存的修改，看模型的“已修改”标记；刚打开的零件就显示已修改，改通用名称后可能又显示未修改。
- 有“保存副本”（`save_doc_as`）；把模型从会话里拭除，会丢掉它没保存的修改。
- 工具包没有撤销，只能撤销失败的重新生成（`SetUndoIfFail`）。所以 creo-cli 不提供 `doc undo`（DCLI-067）。

## 实例与并发

- 可以同时运行几个 Creo 进程；每个进程各自加载宿主组件，按进程 ID 和启动时间区分。
- 人可以在同一个会话里同时工作，宿主组件在人的两次操作之间执行；人开着模态弹窗时，CLI 什么都不发。人做的修改会改变模型状态，保存前作为外来修改显示。
- 为了加载或升级宿主组件，工具从不重启、重新加载或关闭人的 Creo（DSEC-052）。

## 许可

- Creo Parametric 本身要许可（节点锁定，或通过 PTC 许可证服务器浮动）。
- 宿主组件要 `ObjectToolkitJava` 许可选项，没有它什么都做不了。删除工程图自己的尺寸（`ProDimensionDelete`）要 TOOLKIT for 3D Drawings 许可。
- `plugin install` 在用户电脑上构建宿主组件：需要 JDK 25；解锁需要 Creo Object TOOLKIT Java 开发许可，或者它的扩展许可加 Creo TOOLKIT 许可。运行解锁后的组件需要以下之一：Creo Object TOOLKIT Java 运行许可、它的开发许可，或者它的扩展许可加 Creo TOOLKIT 许可（PTC《Creo Object TOOLKIT Java 用户指南》Unlocking, Running and Signing the Creo Object TOOLKIT Java Application）。
- 以应用流方式交付的 Creo（PTC 试用版）没有工具包。
- 宿主组件的 C 库在用户电脑上用 Visual Studio 的 x64 C 编译器对着 Creo TOOLKIT 组件编译，再用 `protk_unlock` 解锁，解锁要 Creo TOOLKIT 开发许可；解锁后运行不需要这个许可（PTC，Creo TOOLKIT User's Guide，Unlocking the Application）。
- 启动时的许可证弹窗要人处理（`activate_license`）。

## 能力

每项能力一行，编号 `CAP-nnn` 在本调查里唯一，处置只有一种：`provided`（由领域命令提供）、`deferred`（值得提供，留到以后的版本）、`excluded`（不会提供，比如不安全或无法可靠地自动化）或 `unknown`（还不知道 Creo Parametric 是否允许）。每一行都写明能达到这项能力的接口；不是 `provided` 的行用一句话写明原因。

| 编号 | 能力 | 接口 | 处置 | 原因 |
|---|---|---|---|---|
| CAP-001 | 读模型概况：类型、单位、材料、质量属性、包围盒、特征数 | OTK Java | provided | - |
| CAP-002 | 改模型的通用名称、公差标准和公差等级、材料 | OTK Java；公差标准用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-003 | 把零件或装配导出为 STEP、IGES 或 STL，把工程图导出为 PDF | OTK Java | provided | - |
| CAP-004 | 出零件或装配的 JPEG 图片 | OTK Java `ExportRasterImage` | provided | - |
| CAP-005 | 设 Creo 的工作目录，新模型写在这里 | OTK Java `ChangeDirectory` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-007 | 启动一个工具自己的 Creo，加载宿主组件 | 从带自己 `config.pro` 的启动目录运行 `parametric.exe` | provided | - |
| CAP-008 | 像“文件 > 退出”那样关闭 Creo，有未保存的修改时拒绝 | TOOLKIT C `ProEngineerEnd`，由 Windows 定时器调用 | provided | - |
| CAP-009 | 从起始零件新建零件，立刻写到指定路径 | OTK Java `CopyAndRetrieve` | provided | - |
| CAP-047 | 用另一个名字写出模型的副本，或把模型写到另一个文件夹 | OTK Java `Copy`、`Backup` | provided | - |
| CAP-006 | 按要求重新生成模型 | OTK Java | deferred | 每次写操作都已经重新生成；从没在真机上运行过 |
| CAP-010 | 按重新生成的顺序列出特征，带类型和状态 | OTK Java | provided | - |
| CAP-011 | 读一个特征：尺寸、父特征、子特征 | OTK Java | provided | - |
| CAP-046 | 描述特征草图里的图元 | TOOLKIT C | deferred | 以后的版本；每次读都要用 C 库 |
| CAP-012 | 隐含、恢复特征，或给特征改名 | OTK Java | provided | - |
| CAP-013 | 删除特征，连同依赖它的特征 | OTK Java `DeleteFeatures` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-014 | 拉伸一个封闭的草绘轮廓，加材料或去材料 | OTK Java 元素树；TOOLKIT C 草图 | provided | - |
| CAP-015 | 把一个封闭的草绘轮廓旋转 360 度 | OTK Java；TOOLKIT C 草图 | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-016 | 从平面或平的面偏移出基准平面 | OTK Java | provided | - |
| CAP-017 | 建基准轴：两平面相交、过一条边或一个圆柱面 | OTK Java | provided | 两个平面相交，或过圆柱面；过边以后再做 |
| CAP-018 | 等半径倒圆角 | OTK Java | provided | - |
| CAP-019 | 等距倒角 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-020 | 在平面上放简单孔或标准孔（线性、径向或同轴定位） | OTK Java；螺纹系列用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-021 | 在圆柱面上加修饰螺纹 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-022 | 向内抽壳，去掉指定的面 | OTK Java | provided | - |
| CAP-023 | 绕枢轴平面拔模 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-024 | 加轮廓筋 | OTK Java；TOOLKIT C 草图 | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-025 | 封闭截面沿草绘轨迹扫描 | OTK Java；TOOLKIT C 草图 | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-026 | 沿方向或绕轴阵列一个特征 | OTK Java `CreatePattern` | provided | 沿方向阵列；绕轴阵列以后再做 |
| CAP-027 | 以一个平面镜像整个零件 | OTK Java 合并特征 | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-028 | 镜像选定的特征 | OTK Java | excluded | 元素树不支持镜像特征（ProMirror.h） |
| CAP-029 | 部分角度旋转、斜基准平面、沉孔和埋头孔、多面拔模 | OTK Java | deferred | 从没做过也没运行过；以后的版本 |
| CAP-030 | 列出几何参考：面、边、轴、基准平面、坐标系 | OTK Java | provided | - |
| CAP-031 | 量两个几何参考之间的距离 | OTK Java | provided | - |
| CAP-032 | 列出和读取尺寸 | OTK Java；描述草图用 TOOLKIT C | provided | - |
| CAP-033 | 改尺寸的值并重新生成；重新生成失败时 Creo 撤回 | OTK Java `SetUndoIfFail` | provided | - |
| CAP-034 | 设尺寸的公差：正负、对称、极限、ISO 配合、基本尺寸、无公差；以及小数位 | OTK Java；TOOLKIT C | provided | - |
| CAP-035 | 列出参数，改参数的值 | OTK Java | provided | - |
| CAP-043 | 新建参数 | OTK Java | deferred | 以后的版本；1.0.0 只改已有的参数 |
| CAP-036 | 读模型的关系 | OTK Java | provided | - |
| CAP-044 | 替换模型的关系 | OTK Java | deferred | 以后的版本；早期工具最后一次修改后没有重新验证过 |
| CAP-037 | 读族表：列、实例、单元格 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-038 | 改族表单元格 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-039 | 从族表删除一个实例行 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-040 | 列出材料库和零件里的材料 | OTK Java；`.mtl` 文件 | provided | - |
| CAP-041 | 读和设零件的外观颜色 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-042 | 按元件出现处上色和贴图 | OTK Java | deferred | 从没验证过；以后的版本 |
| CAP-050 | 列出装配的顶层元件，带状态和位置 | OTK Java | provided | - |
| CAP-045 | 读每个元件的放置约束 | OTK Java | deferred | 以后的版本 |
| CAP-051 | 按约束放入元件 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-052 | 重新定义元件的约束，或换成族表里的另一个成员 | OTK Java；替换用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-053 | 删除元件，连同依赖它的特征 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-054 | 检查装配的全局干涉 | OTK Java | deferred | 大装配上可能超过 60 秒，而规范里只读命令没有长任务的做法 |
| CAP-055 | 读分解状态 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-056 | 按元件平移新建或修改分解状态 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-057 | 窗口显示：激活、重新调整、隐藏元件、取消分解 | OTK Java；TOOLKIT C 宏 | deferred | 从没在真机上运行过；只改显示状态；以后的版本 |
| CAP-060 | 读工程图：绘图模型、图纸、大小、投影方式 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-061 | 读工程图的视图和注释，带位置 | OTK Java；尺寸位置用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-062 | 加一般、投影、剖面或局部放大视图 | OTK Java；剖面面积用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-063 | 移动视图 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-064 | 删除没有其他视图依赖的视图 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-065 | 对照图纸检查视图布局：重叠和超出图框 | OTK Java 读取 | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-066 | 在视图上显示模型注释（尺寸、轴线） | OTK Java `ShowAnnotations` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-067 | 在两条边之间加参考尺寸 | OTK Java `CreateDrawingDimension` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-068 | 移动图纸上尺寸文字的位置 | TOOLKIT C `ProDrawingDimensionMove` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-069 | 擦除显示的模型尺寸，或删除工程图自己的尺寸 | OTK Java `EraseAnnotation`；TOOLKIT C `ProDimensionDelete` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-070 | 加、改、移动和删除注解 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-071 | 加、移动和删除表格，包括按模型信息填写的标题栏 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-072 | 放置和删除来自 Creo 符号库或 `.sym` 文件的符号 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-073 | 加重复区域 BOM 表 | OTK Java；BOM 参考用 TOOLKIT C | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-074 | 建 BOM 球标 | TOOLKIT C `ProBomballoonCreate` | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-075 | 放置和删除基准特征符号 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-076 | 加和删除几何公差 | OTK Java | deferred | 以后的版本；不在 1.0.0 的范围里 |
| CAP-090 | 无图形界面运行 Creo | 命令行 | excluded | `-g:no_graphics` 要异步模式，而异步模式没有 `wfc` |
| CAP-091 | 取消正在执行的工具包调用 | OTK Java | excluded | 没有接口；调用总会执行到底 |
| CAP-092 | 改 Creo 的配置（`config.pro`） | OTK Java `SetConfigOption` | excluded | 改的是文档以外人的环境 |
| CAP-093 | 回放 trail 文件或 mapkey | 命令行 | excluded | 没法读回；无法可靠地自动化 |
| CAP-094 | 在 Windchill 里检入或检出模型 | OTK Java | unknown | 没有调查；会把内容交给外部系统 |

## 风险

调查中发现的每个风险或限制，都写成 `knowledge/` 里的一个条目，或者在这里写明不写的理由。

- 模型可能用英制或别的单位；creo-cli 和毫米互相换算 → `creo-units`。默认模板决定新零件的单位，这一条不写进 1.0.0，因为它不新建模型。
- 每次保存都在模型原来的目录（不是工作目录）写一个新的编号版本，旧版本越积越多 → `creo-save-versions`。
- 刚打开的零件就显示有没保存的修改 → `creo-save-versions`。从模板新建的模型会立刻写盘：不写进 1.0.0，因为它不新建模型。
- 模态弹窗（启动时的恢复弹窗、许可证弹窗、ORDER_DEBUG、视图状态要求“应用”）在人关掉之前挡住所有命令 → `creo-troubleshooting`。
- 每次会话 Creo 加载未签名的工具包 DLL 前都会问人。1.0.0 不写成条目：它的宿主组件是 Java 应用，不加载 DLL。
- 锁屏或窗口最小化可能让 Creo 崩溃（见于 Intel OpenGL 驱动）；不能无界面运行 → `creo-display-requirements`。
- 长操作：复杂装配改约束 135–194 秒，BOM 表最长 568 秒，都不能取消。不写进 1.0.0：它的命令都不执行这些操作。
- 特征可能建出来却重新生成失败（方向错、面和拔模方向垂直）。不写进 1.0.0，因为它不建特征。
- 方向和正负号：孔沿参考面法向偏移、拔模角的正负、筋在哪一侧、抽壳方向。不写进 1.0.0，因为它不建特征。
- 改了特征后几何 ID 会变；参考要从新运行的 `geometry list` 里取 → `creo-geometry-references`。
- 被关系驱动的尺寸，重新生成时会被改回；两个尺寸可能共用一个值 → `creo-relations-and-dimensions`。
- 族表单元格可能不报错却保留旧值；实例没有单独的文件，保存的是类属模型。不写进 1.0.0，因为它没有族表命令。
- 材料只在工作目录和材料库目录里找；Creo 13 的占位材料没有密度 → `creo-materials`。
- 擦除的工程图尺寸不能在同一张工程图里再显示。不写进 1.0.0，因为它不改工程图。
- 标准图纸字体（ISONorm）没有中文、日文和韩文字形。不写进 1.0.0，因为它不改工程图。
- 特征类型、视图名和分解状态名按界面语言返回 → `creo-localized-names`。
- 许可：要 `ObjectToolkitJava`；删除工程图自己的尺寸要 TOOLKIT for 3D Drawings；以应用流方式交付的 Creo 没有工具包 → `creo-licenses`。
- 在主线程以外调用工具包会卡死或崩溃，传给 Creo 的 Java 字符串为 null 会让 Creo 崩溃：不写成条目，这是宿主代码的规则（`plugin/README.md`），不是给 Agent 的。
- 解锁后的 JAR 不能再改：不写成条目，`plugin install` 最后才解锁，之后不再动它。
- 导出时会在文件旁边写 `__out.log`：不写成条目，宿主组件导出到一个私有目录，只把文件移过去。
- 不能在新建工程图的同一次调用里加视图。不写进 1.0.0，因为它不改工程图。
