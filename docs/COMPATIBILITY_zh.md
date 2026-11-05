# 兼容性

[English](COMPATIBILITY.md) | 中文

creo-cli 在哪里能用，能配合哪些版本的 Creo Parametric。

## 支持矩阵

Creo Parametric 版本、操作系统和模式的每种组合占一行，由 `python scripts/spec.py generate` 根据 `docs/evidence/` 里的真实软件记录和 `package.json` 里的平台包生成，从不手改：✅ verified 表示已在真实软件上验证，⏳ untested 表示还没测试，⛔ unsupported 表示不支持。

<!-- driver:support-matrix:start -->
| 软件版本 | 操作系统 | 模式 | 状态 |
|---|---|---|---|
| 13.4 | Windows | session | ✅ verified |
| >=13.4 <13.5 | macOS | session | ⛔ unsupported |
| >=13.4 <13.5 | Linux | session | ⛔ unsupported |
<!-- driver:support-matrix:end -->

## 客户端与宿主

creo-cli 和 Creo Parametric 始终在同一台电脑上运行。CLI 通过宿主协议与 Creo Parametric 里的宿主组件通信；只有协议主版本相同，CLI 和宿主组件才能配合工作。

| creo-cli 版本 | 宿主协议版本 | 宿主组件版本 |
|---|---|---|
| 1.0.x | 1.0.0 | 1.0.x |

## 宿主组件版本

| 宿主组件版本 | 协议版本 | Creo Parametric 版本 |
|---|---|---|
| 1.0.0 | 1.0.0 | Creo Parametric 13.4（>=13.4 <13.5），Windows x64 |

## 已知限制

- creo-cli 1.0，Creo Parametric 13.4：只在 Windows 11 x64 上的 Creo Parametric 13.4.1.0 上验证过。锁屏和 Creo 窗口最小化从没验证过。
- creo-cli 1.0：`model render` 拍的是模型自己的窗口，不论它是不是当前窗口；只作为装配或工程图的一部分加载进会话的模型没有窗口，要先用 `doc open` 打开，否则拒绝。
- creo-cli 1.0：正在执行的工具包调用不能取消；Creo 只在启动时加载宿主组件，所以升级后要重启 Creo。
