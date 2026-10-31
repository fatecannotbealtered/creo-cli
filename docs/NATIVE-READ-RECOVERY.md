# 原生读取未决时怎样停止后续CAD请求

只读请求可能已经进入Creo，却因timeout、连接中断或回复不可读而无法确认结果。
结束客户端等待或关闭HTTP连接不会取消原生调用。
出现未决读取后，保留原始错误和已有诊断记录，停止向该实例发送后续CAD请求。

本文说明通用CLI读保护。它不依赖符号原型的Java追踪、诊断DLL或新增getter。
完整错误和详情JSON Schema以当前`reference.extensions.creo.native_read_recovery`为准。
本说明不声明新的测试、字体读取、背景保护或原生工程验收通过。

## 分清已开始与开始状态未知

未决原生读取使用不可重试的`E_NATIVE_READ_PENDING`，退出码为8。
错误保留原始cause、操作名和可获得的关联信息，不把未知开始状态改写成已开始。

| 已知事实 | 读取错误详情 | 后续边界 |
|---|---|---|
| 服务的`E_BUSY`或`E_UNAVAILABLE`确认`started=true` | `dispatch_state=started`、`started=true`、`native_call_pending=true` | 原读取仍未决，停止后续CAD请求 |
| 读取请求已发送，但回复丢失、timeout或不可读 | `dispatch_state=unknown`、`native_call_may_be_pending=true`，省略`started` | 不能断言已开始，也不能断言未开始 |
| `E_BUSY`或`E_UNAVAILABLE`没有明确的开始状态 | 同样保留`dispatch_state=unknown`，省略`started` | 缺少开始确认不能作为继续CAD的依据 |
| 服务明确确认开始前已撤回，`E_BUSY started=false` | 可重试的`E_TIMEOUT`，保留`started=false` | 不将这次明确撤回误报为未决读取 |
| 服务明确返回`E_UNAVAILABLE started=false` | 服务不可用，保留未开始事实 | 这次拒绝不建立未决读取限制 |
| 请求尚未发送，例如连接建立前失败 | 保留`request_sent=false`及原错误 | 这次失败不建立未决读取限制 |
| 服务明确拒绝认证 | 保留`E_AUTH`和原始认证拒绝事实 | 不将认证拒绝改写为未决原生调用 |

非CAD接口的失败不建立这项CAD读取限制。
上述例外只描述本次请求；它们不会解除此前已经存在的未决读取。
不要仅凭退出码重试，应同时读取`retryable`与派发事实。

## 同一个Client阻止后续CAD请求

未决状态保存在同一个Client对象的内存中。
该Client拒绝后续CAD读取和写入，包括直接派发的CAD请求。
被拒请求的`request_sent=false`只描述本次尝试；原读取已发送的事实仍保留。

这项限制不跨Client或CLI进程持久保存。
新建Client、重新运行CLI或重新连接HTTP都不能证明原调用已经结束。
不能用这些操作绕过停止边界。
继续CAD之前，必须先用独立证据确认原实例和原调用的状态；证据不足就保持未决。

真实任务使用外层`CURRENT-ENVIRONMENT.json.environment_variables`声明的环境。
其中`CREO_CLI_CONFIG_DIR`指定CLI状态目录，目录内的`operations.sqlite3`是该工作环境的连续操作历史。
保留已声明的目录及另外声明的真实global历史；Java服务的runtime目录仅用于该代服务凭据和加载记录，不能替代CLI历史。
不要修改这些目录来解除阻断。

独立的合成HTTP测试可以显式设置测试专用的`CREO_CLI_CONFIG_DIR`，并把测试服务地址、测试凭据文件和临时目录一同记录为合成环境。
该环境不得连接真实Creo，不得复用真实凭据，也不能用来判断真实旧操作已恢复。
测试结束后，真实工作仍使用原外层声明的连续历史。

可以使用不调用CAD API的`GET /health`或OS观察保留现场。
`/health`仍受Client原有deadline限制，deadline耗尽时也可能无法发送。
health成功只证明服务进程可响应，不证明原getter完成，也不解除Client内的限制。
`context --installation`核对加载身份后报告的connected也只覆盖当前进程和组件。
它不证明CAD reader可用、实例空闲、原getter完成或读取限制已解除。
调用新的读取、加载目标或重放操作都不属于process-only观察。

## 关联ID缺失时如实保留

CLI invocation ID由客户端生成，用于关联同一次CLI调用。
服务诊断request ID只有实际收到时才保留，两者不能互相替代。
旧正式服务没有提供诊断ID时，该ID就是不可获得；错误中省略该字段，不生成替代值。
缺少服务ID不等于请求未收到、原生调用未开始或已经完成。

正式服务已经提供protocol 2、认证、process-only health，以及上述`started`与撤回信息。
S8新增的invocation header和诊断响应ID是附加观测信息。
静态兼容性审阅没有发现通用读保护需要重建Java服务或C主DLL的依赖。
该判断不等于新的运行验证，也不让正式服务获得原型符号功能。

## 读取与已有写操作分别处理

读取失败不创建写回执或`operation_id`，不要为它伪造这些记录。
`operation query`和`operation resolve`不能取消或解决没有写记录的原生读取。
如果读取发生在已经派发写入的workflow中，保留真实父操作及已完成子写入的ID和回执；读取步骤自己的写ID和回执仍为空。
父操作可保持unknown，后续步骤跳过，不能经外层Client追加CAD采样。
写入已返回成功但必需的独立验证读取未决时，执行完成和验证不完整分别保留；这不证明实际效果、保存或完整通过。

此时父写操作仍使用自己的`operation_id`、派发事实和五维回执。
父写的顶层错误可保持`E_OUTCOME_UNKNOWN`（退出码6）；
原读取错误在`error.details.native_read_error`和`receipt.extensions.creo.native_read_error`中完整保留，
包括实际operation、dispatch_state、cause、cli_invocation_id及实际取得的diagnostic_request_id。
后续被Client拦下的请求不能取代最初那次读取，也不能把原开始未知改成未派发。

立即可用的检查只有本地`operation show`、process-only `GET /health`和OS观察。
本地show不触发CAD，恢复指引中的`query`与`resolve_preview`此时为空。
show没有保留未决读取，也不能证明原读取已经结束。
写历史可能未记录该读取；独立query或resolve的失败读取观察还可能另存，或因存储错误没有可用证据ID。
因此，不能用show未发现pending来证明本实例已恢复。
这些检查不证明原getter已结束；不得立即运行新的`model show`、`feature list`或`operation query`补读。
先独立确认原调用已结束及本代实例状态，再进入正常工程读回与显式登记。
部分`operation resolve --dry-run`和确认也会调用CAD getter，同样受这个前提约束。
这份持久警示不是新的跨进程锁，也不允许用新Client绕过停止条件。
普通unknown写回执没有已知未决读取时，仍使用针对原目标的正常恢复入口。
unknown本身不代表原getter仍在运行，也不构成永久停止所有CAD的理由。

独立query或resolve本身遇到未决读取时，会另存失败的读取观察，关联原父写ID，保留原回执。
失败观察不证明工程状态，不能作为成功登记依据；读取本身仍没有写回执或新写operation_id。
若证据目录准备、创建或写入失败，原未决读取及其关联信息和停止CAD指引仍保留。
输出会明确说明证据留存未获确认，并附结构化storage_error；不会编造evidence_id或修改原写回执。
未返回evidence_id不代表文件一定不存在；storage_error可能说明存储状态未知。
目录权限、同名普通文件等存储问题不证明原getter已结束，也不能作为追加CAD读取的理由。
普通验证失败、明确未开始和未决读取分别处理，不能把所有读取异常都解释为仍在运行。

写操作丢失回复后的`E_OUTCOME_UNKNOWN`及其原有恢复规则保持。
检查实际写回执与独立证据，保留已有unknown、partial和成功子步骤，不重放原操作。
已有`operation_id`的写操作见操作恢复说明 (historical material retained outside this snapshot)。
