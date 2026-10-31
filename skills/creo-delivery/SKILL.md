---
name: creo-delivery
version: "1.1.0-beta.1"
description: "保存 Creo 可编辑工程，验证空会话重开、正常退出并整理交付；建模用 creo-modeling，约束用 creo-assembly，图片用 creo-presentation，环境用 creo-cli。"
license: MIT
metadata: { "requires": { "bins": ["creo-cli"], "skills": ["creo-cli"], "min_version": "1.1.0-beta.1" } }
---

# 保存、重开与工程交付

先读取 [creo-cli 入口](../creo-cli/SKILL.md)，遵守其环境核对、实际授权、预览/确认和未知调用停止规则。
STOP CHECKPOINT：入口缺失时先恢复完整 Skills 家族，不能猜测安全约束或继续写入。

明确交付目录和用户对保存的授权。先保存 dirty 源零件，再保存 owner，核对 modified 标志、
准确带版本号路径与摘要。正常关闭 clean 装配和成员、验证原始库存为空后，精确重开刚保存
的装配；CurrentModel 为空时显式激活。回读编辑、外观、绑定、非目标和可继续编辑性。
若要独立证明磁盘状态，第二个新建且身份绑定的进程必须自行重开；同进程成功不能代替。
正常退出只用 session exit，需精确 owned launch、新预览和危险动作授权。核对同一个 held
process exit 0 及关联 native-entered/Service.stop。ACK、端口或 PID 消失都不充分。
交付保留可编辑源工程、输出及准确限制，不附凭据、私有日志或供应商 SDK。STEP 等冻结
路径仍受限制。未知调用期间不得保存、discard、关闭或用新进程抹掉历史。

常见任务：保存后清空会话并重开；交付可编辑装配及图片；正常退出本任务拥有的空会话。


## Eval Scenarios

- 用 reference/context/doctor 核对资格与真实身份，不能从命令存在推定支持。
- 遵循用户已有授权；遇到拒绝不改 scope 或扩大目标。
- 回读失败或原调用未终结时保留首份回执，不自动重放。
