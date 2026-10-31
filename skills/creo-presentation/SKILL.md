---
name: creo-presentation
version: "1.1.0-beta.1"
description: "修改 Creo 源零件 RGB、检查视角显示并生成受支持原生图片；实例约束用 creo-assembly，工程图用 creo-drawing，保存交付用 creo-delivery，环境用 creo-cli。"
license: MIT
metadata: { "requires": { "bins": ["creo-cli"], "skills": ["creo-cli"], "min_version": "1.1.0-beta.1" } }
---

# 源外观、视图与原生图片

先读取 [creo-cli 入口](../creo-cli/SKILL.md)，遵守其环境核对、实际授权、预览/确认和未知调用停止规则。
STOP CHECKPOINT：入口缺失时先恢复完整 Skills 家族，不能猜测安全约束或继续写入。

源外观会影响该源的全部已加载实例。先读 appearance 和完整受影响路径，不能用名字匹配
把共享操作缩成一个实例。实例独立外观未获资格；物理材料与密度不随颜色授权。
从 reference 读取参考语义。新增/替换参考需要匹配授权，保持非 RGB 属性；RGB 容差为
已声明的绝对/相对 1e-12，不扩用到几何、密度或定义摘要。
视图与图片须先确认模型激活、方向和 fit。原生图片写入使用精确 staging 与输出边界，
拒绝后不得补 scope。临时显示、模型修改和保存持久化分别核对。查看实际图片内容和取景。

常见任务：按授权改一个源零件 RGB；给装配选受支持视角；输出原生图片并检查内容。


## Eval Scenarios

- 用 reference/context/doctor 核对资格与真实身份，不能从命令存在推定支持。
- 遵循用户已有授权；遇到拒绝不改 scope 或扩大目标。
- 回读失败或原调用未终结时保留首份回执，不自动重放。
