# 兼容性

[English](COMPATIBILITY.md) | 中文

creo-cli 在哪里能用，能配合哪些版本的 Creo Parametric。

## 支持矩阵

Creo Parametric 版本、操作系统和模式的每种组合占一行，由 `python scripts/spec.py generate` 根据 `docs/evidence/` 里的真实软件记录和 `package.json` 里的平台包生成，从不手改：✅ verified 表示已在真实软件上验证，⏳ untested 表示还没测试，⛔ unsupported 表示不支持。

<!-- driver:support-matrix:start -->
| 软件版本 | 操作系统 | 模式 | 状态 |
|---|---|---|---|
| >=13.4 <13.5 | Windows | session | ⏳ untested |
| >=13.4 <13.5 | macOS | session | ⛔ unsupported |
| >=13.4 <13.5 | Linux | session | ⛔ unsupported |
<!-- driver:support-matrix:end -->

## 客户端与宿主

creo-cli 和 Creo Parametric 始终在同一台电脑上运行。CLI 通过宿主协议与 Creo Parametric 里的宿主组件通信；只有协议主版本相同，CLI 和宿主组件才能配合工作。

| creo-cli 版本 | 宿主协议版本 | 宿主组件版本 |
|---|---|---|
| {{fill: 工具版本}} | {{fill: 它们使用的宿主协议版本}} | {{fill: 能与它们配合的宿主组件版本}} |

## 宿主组件版本

| 宿主组件版本 | 协议版本 | Creo Parametric 版本 |
|---|---|---|
| {{fill: 一个宿主组件版本}} | {{fill: 它的协议版本}} | {{fill: 它能加载进的软件版本}} |

## 已知限制

{{fill: 已知的缺口和故障，每项写明受影响的工具版本和软件版本；没有时写「目前没有已知限制。」}}
