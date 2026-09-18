# Agent 入口

先读 README_zh.md 和 docs/SPEC_STATUS.md，再进入相关源码。目标规范是
`ai-native-cli-spec@v1.6.2`，固定提交 `abbebfdf03dbfa28d1378b2fe3dd55ac34b22981`。
规范副本必须精确获取，不得用手写摘要伪装成上游正文。

保持 native 默认、mock 显式且标记为模拟；不可偷偷回退。不得伪造原生特征、保存、
导出或 E2E 证据。命令解析和 reference 共用注册表；每项公开行为都要命令级测试。
写入必须保留 HMAC 确认、持久防重放和人工策略。不得增加任意脚本、隐式模型加载、
Save 或会话终止。保留真实单位体系，仅允许既有参数及可修改的线性尺寸。
请求值恢复不等于整个模型回滚；未知现场必须明确报告。

运行 scripts/test.py、scripts/version.py --check 和 compileall。代码变化后重跑证据，
不要通过跳过发布守卫或把命令计数当成完整 FCC 来升级状态。公开行为变化同步双语
README、Skill 和根 CHANGELOG。仓库发布与软件包发行是两件事，当前包保持 private。

## 0.2.0 范围更新

CREOSON 路线已实现受控打开、保存、备份、导出、装配和图纸操作；旧版“不保存、不导出”的约束仅适用于原 VB API worker。新增操作始终标记未真实实测，不允许用模拟替代原生成功。保持请求 schema、执行白名单、测试、README 和 Skill 一致。
