# Creo CLI

面向机械工程任务的 Creo 命令行与 Agent Skills。通过合法 Creo 内的服务读取和编辑，
写入必须经过新预览、一次确认、实际回读和留存回执。

当前为 **1.1.0-beta.1 Windows x64 隔离未签名测试版**。已观测环境为可见窗口下的
Creo 13.4.1.0/JDK 25.0.3；其他平台、版本、锁屏、最小化、无界面和干净新机未获资格。
源零件 RGB、限定刚性定位、保存后清空会话再重开有原生记录。数值密度/材料修改、实例独立
外观、高级装配、STEP 交付、删除和符号功能仍受限制。复杂装配可能等待数分钟。

仅客户端使用项目受控 Python 3.15.2、已修补 XZ 5.8.4 与 PyInstaller 6.22.3 重建；
运行时从官方源码按记录配置编译，JAR/DLL 保留原字节和来源。
内嵌依赖与旧历史库兼容性有离线检查；这些检查不扩大历史原生资格。

从本仓库 prerelease 下载完整 Windows ZIP 与 checksums.txt，核对 SHA-256 后解压。
包内同时有 EXE、JAR、DLL、PowerShell 助手、六项 Skills 和许可；无需 Python/Node。
用户需提供合法 Creo、对应 API/运行许可、JDK 25.0.3 与 PowerShell 7.4+。

按[英文入口的可复制命令](README.md)先调用 Initialize-CreoWorkspace.ps1，再预检并启动。
初始化只安装组件和建立隔离目录，不启动 CAD，不需要私有演示工程。把有权使用的工程与依赖
复制到 run/projects 后再打开。升级沿用已有 CLI 历史，遇到拒绝不自动扩大 scope。
公共父目录不会整体获权，临时出图只纳入精确 workspace/.creo-cli/staging。

未签名策略只作用于新建进程；它允许该进程加载未签名应用，并非单 DLL 白名单或发布者签名。
全局配置、许可和其他 CAD 会话保持原样。启动后必须用 context/doctor 核对真正加载的三组件。
超时不等于取消；未知或未完成调用必须保留，不能盲重试、关闭、丢弃或杀进程。

可用 `npx skills add fatecannotbealtered/creo-cli -y -g` 安装整个 Skills 家族；无 Node 时，
把包内 cli/skills 完整复制到 Agent 的技能目录。creo-cli 负责环境与安全，建模、装配、工程图、
外观出图和保存交付分别由对应任务 Skill 引导。精确参数与资格以实际 EXE 的 reference 为准。

[发布说明](release/RELEASE-NOTES.md) · [依赖与许可](docs/RUNTIME-DEPENDENCIES.md)
