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

## 已知限制

- creo-cli 1.0，Creo Parametric 13.4：只在 Windows 11 x64 上的 Creo Parametric 13.4.1.0 上验证过。锁屏和 Creo 窗口最小化从没验证过。
- creo-cli 1.0：`model render` 拍的是模型自己的窗口，不论它是不是当前窗口；只作为装配或工程图的一部分加载进会话的模型没有窗口，要先用 `doc open` 打开，否则拒绝。
- creo-cli 1.0：正在执行的工具包调用不能取消；Creo 只在启动时加载宿主组件，所以升级后要重启 Creo。
- creo-cli 1.0：`feature`、`dimension`、`geometry` 和 `distance` 命令用于零件和装配；在装配上只看到装配自己的特征、尺寸和基准，看不到元件里面的。它们拒绝工程图。
- creo-cli 1.0：`doc open` 按长作业运行。`model export` 和 `doc save` 在一次最多 60 秒的调用里完成，只在小的练习模型上测过；大装配可能超过这个时间，这种情况没有测过。
