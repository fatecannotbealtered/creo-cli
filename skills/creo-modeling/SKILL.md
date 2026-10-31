---
name: creo-modeling
version: "1.1.0-beta.1"
description: "处理 Creo 零件的特征、尺寸与几何检查和受支持修改；装配约束用 creo-assembly，工程图用 creo-drawing，安装与环境用 creo-cli。"
license: MIT
metadata: { "requires": { "bins": ["creo-cli"], "skills": ["creo-cli"], "min_version": "1.1.0-beta.1" } }
---

# 零件检查、特征和尺寸修改

先读取 [creo-cli 入口](../creo-cli/SKILL.md)，遵守其环境核对、实际授权、预览/确认和未知调用停止规则。
STOP CHECKPOINT：入口缺失时先恢复完整 Skills 家族，不能猜测安全约束或继续写入。

读取模型、单位、特征树、几何与物理观察；完整原生序列化定义树和独立回读共同决定可修改性。
所需字段 unsupported/failed/incomplete 时停在派发前。按 reference 选择受支持命令，
不能把同名特征或数组位置当稳定身份。建立请求后走入口规定的预览与一次确认。
核对目标变化、非目标特征、单位、原生定义和几何保护条件。材料与数值密度修改仍未获资格。
需要持久化时转 creo-delivery；不得把内存修改说成保存成功。

常见任务：检查板件尺寸与孔；按明确尺寸修改一个特征并保留其他几何；生成可编辑的受支持零件。


## Eval Scenarios

- 用 reference/context/doctor 核对资格与真实身份，不能从命令存在推定支持。
- 遵循用户已有授权；遇到拒绝不改 scope 或扩大目标。
- 回读失败或原调用未终结时保留首份回执，不自动重放。
