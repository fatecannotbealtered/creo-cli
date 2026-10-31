# 无人工操作与headless的资格边界

本轮采用Creo管理的同步Object TOOLKIT Java服务。允许Creo进程创建窗口，agent只调用公开CLI与原生接口。零鼠标、零键盘和零CUA输入证明流程不依赖人工CAD操作，不能证明没有图形环境。

相同C15构件的预验收seed已在允许窗口的自有会话中通过两次完整组件冷启动、手机两轮及两次正常退出；文件恢复和归档有外置配方及审阅协助，最终ZIP入口仍待独立复验。C14曾出现颜色持久化反例，其结果不自动转授C15。准确构件与场景见当前交接 (private historical record)，不能把这些结果扩大为headless资格。

## 官方支持范围

PTC文档提供非交互、无图形会话的启动方法：在异步`AsyncConnection_Start`中同时使用`-g:no_graphics`与`-i:rpc_input`。前者关闭图形显示，后者只接受异步应用输入；两者都需要。该说明针对异步启动，不是同步protk服务已通过headless的声明。[PTC非交互会话说明](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/user_guide/Setting_Up_a_Noninteractive_Session.html)。

同步应用由Creo加载并管理，同一时刻由Creo或应用掌握控制。[PTC同步应用设置](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/user_guide/Setting_Up_a_Synchronous_Creo_Object_TOOLKIT_Java_Program_2.html)。J-Link异步模式使用JNI与RPC，应用独立启动后再启动或连接Creo；PTC明确说明Creo Object TOOLKIT Java不支持异步模式，也说明同步start方法可以实现批处理控制。因此，批处理、异步和无图形是不同条件，不能互相替代。[PTC异步模式说明](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/user_guide/Running_J_Link_Applications_in_Asynchronous_Mode.html)。

## 当前架构与需证明的条件

当前服务使用otk.jar的WSession创建API，在Creo调用的TOOLKIT线程上工作。HTTP线程只排队，由原生timer处理。2026年10月24日对本机Creo13.4.1.0 SDK作只读清单检查。otk.jar含2122个wfc类，不含pfcAsyncConnection类。pfcasync.jar含8个pfcAsyncConnection类，不含wfc类。清单及SDK文件摘要在本轮`research/HEADLESS-SDK-INVENTORY.json`，未复制供应商JAR。

这些结果说明，更换为AsyncConnection需要重新验证WSession建模能力。它们不证明所有headless架构都不可行。若另立headless项目，至少要证明：

- 所需创建、装配、外观和持久化API在所选连接与许可下可用。
- 原生事件泵、deadline、取消与诊断在无图形输入模式下仍正确。
- 原生DLL加载、信任前置、会话归属与组件身份检查仍成立。
- 图片输出需要的图形上下文与驱动条件得到官方支持并实际验收。
- 保存、全关、精确重开、重复件留出案例均由最终组件执行。

本轮不把同步架构改成异步，也不传入无图形参数来试探未审查的运行方式。

## 分别登记资格

| 条件 | 本轮登记方法 |
|---|---|
| 正常有窗口，零人工CAD/CUA | C13／C14已完成的限定冷启动及探针按实际记录保留；C15完整日常路线待判定 |
| Creo窗口最小化 | 本轮未验证；只有实际最小化状态下完成的案例才授予资格 |
| Windows锁屏 | 本轮未验证；只有锁屏条件下实际完成的案例才授予资格 |
| 真正headless | 未执行、未认证；官方异步参数不是当前产品完成证据 |
| Java-only自动注册 | 已有旧C3独立诊断，仅证明Java注册与pump，不授予完整DLL或工程验收资格 |
