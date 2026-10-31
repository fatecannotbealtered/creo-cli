---
name: creo-drawing
version: "1.1.0-beta.1"
description: "处理 Creo 工程图的受支持视图、尺寸、表格和注释任务；原生模型图片用 creo-presentation，零件建模用 creo-modeling，环境用 creo-cli。"
license: MIT
metadata: { "requires": { "bins": ["creo-cli"], "skills": ["creo-cli"], "min_version": "1.1.0-beta.1" } }
---

# 工程图视图和注释

先读取 [creo-cli 入口](../creo-cli/SKILL.md)，遵守其环境核对、实际授权、预览/确认和未知调用停止规则。
STOP CHECKPOINT：入口缺失时先恢复完整 Skills 家族，不能猜测安全约束或继续写入。

读取工程图、源模型、sheet、view、dimension 或 annotation 的真实身份和关系。
从 reference 核对具体操作和资格；符号、删除与冻结导出不得因命令存在而启用。
预览范围与关联模型，确认一次后检查实际布局、关联、内容和保护的非目标。
按用户要求检查可见图面；导出成功不能代替图面和工程含义检查。
保存与重新打开由 creo-delivery 执行，不把临时显示状态混作磁盘结果。

常见任务：检查视图和尺寸；调整受支持注释位置；交付仍与原模型关联的工程图。


## Eval Scenarios

- 用 reference/context/doctor 核对资格与真实身份，不能从命令存在推定支持。
- 遵循用户已有授权；遇到拒绝不改 scope 或扩大目标。
- 回读失败或原调用未终结时保留首份回执，不自动重放。
