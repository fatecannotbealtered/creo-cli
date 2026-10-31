---
name: creo-assembly
version: "1.1.0-beta.1"
description: "检查 Creo 装配结构和精确实例路径，修改受支持刚性定位与约束；源外观用 creo-presentation，零件特征用 creo-modeling，环境用 creo-cli。"
license: MIT
metadata: { "requires": { "bins": ["creo-cli"], "skills": ["creo-cli"], "min_version": "1.1.0-beta.1" } }
---

# 装配实例和约束

先读取 [creo-cli 入口](../creo-cli/SKILL.md)，遵守其环境核对、实际授权、预览/确认和未知调用停止规则。
STOP CHECKPOINT：入口缺失时先恢复完整 Skills 家族，不能猜测安全约束或继续写入。

读取 owner、完整组件/约束状态和精确 occurrence path。重复的源名称不能唯一标识实例。
从 reference 与实际局部/owner 参考构造请求，暴露全部共享源影响，检查单位和刚性边界。
只在已获资格的路径上预览与确认一次，再核对目标约束、pose、保护的非目标和完整实例集合。
高级装配、不可读参考或不支持模型拒绝派发。复杂装配确认可能分钟级，不能因等待重放。
保存时先保存改动源零件再保存 owner，转 creo-delivery 做空会话精确重开。

常见任务：检查重复零件的实例路径；调整一个已定位实例的偏移；验证其他实例和约束保持。


## Eval Scenarios

- 用 reference/context/doctor 核对资格与真实身份，不能从命令存在推定支持。
- 遵循用户已有授权；遇到拒绝不改 scope 或扩大目标。
- 回读失败或原调用未终结时保留首份回执，不自动重放。
