# B 显式计划差量：独立开发模块

`src/smt_fullfab/plan_delta.py` 是尚未接入运行时的纯确定性编译器。它不调用模型、环境、经典构造器或 CP，也不提交计划、不推进时钟。B恢复运行已按冻结的全页输出接口结束，在模拟1628.86秒处因原运行墙钟耗尽而失败；本模块不改变那条运行的结果或归属。目标提示词第四节允许计划差量，但仍要求模型直接决定具体任务、设备、组批、顺序、时间、等待与修订。

## 只读规模证据与限制

主流程保存的 [`B_delta_state_size_plan3_v1.json`](../../artifacts/smt_fullfab_recovery/B_delta_state_size_plan3_v1.json) 对正在运行的第 4 版提交方案，在 `t=1603.1013031725258` 的完整已读 trace 前缀进行结构计数：

| 项目 | 数量 |
|---|---:|
| base plan 任务 / 已派工 / pending | 404 / 4 / 400 |
| pending 涉及的机器 | 339 |
| 当前完整 problem 工序 / 状态页 | 4349 / 20 |
| pending 工序不在当前 problem 的任务 | 1 |
| pending 的 not_before 已过去，需显式替换 | 67 |
| 未发现以上两类结构问题的 pending | 332 |
| base holds / 已发现过期或失效锚点 | 79 / 0 |

这是某个已观测截面的结构大小，不是最终运行结果。332 个任务只通过两个结构筛查，不能称为可行或默认应保留。编译器不会加载该文件、使用其中列表筛选任务或生成默认 delta；后续真实模型必须自己明确选择。也尚未测得 token、调用数、墙钟或质量收益，不能将字段少直接等同于性能提升。以往 [`repair-design.md`](repair-design.md) 的 v4 依赖闭包分析同样只说明研究动机，不授权当前模型自动取消。

## 窄 API 与四个锚

```python
compile_plan_delta(base_plan, problem, execution_state, delta, *, source_sha256)
# -> {"plan": 完整的新显式计划, "evidence": 编译来源与必要后续检查}
```

`base_plan` 必须是实际已提交的准确计划，不使用预测裁剪前方案冒充当前责任方案。`problem` 是当前完整公开观察。`execution_state` 由外层可信执行状态生成，结构固定为：

```json
{
  "schema": "smt-fullfab-plan-delta-state-v1",
  "time": 10,
  "observation_end": 100,
  "base_plan_version": "base",
  "dispatched_task_ids": ["already-started-task"]
}
```

`dispatched_task_ids` 仅包含这版 base 的已派工任务身份；包括尚在加工中的任务。它们不会重新提交，也不能出现在显式 keep/cancel/replace 中。新 task ID 不能复用 base 中任何 ID；换个新 ID 重新提交已派工的准确工序/访问元组也被拒绝。执行中物理工作仍由共同环境保留。

`anchor_hashes(...)` 只计算 base、problem、state 三份完整 JSON 和外层 `source_sha256` 的四锚。模型 delta 必须精确回显，任何失配拒绝。哈希采用 SHA256 与 `json.dumps(sort_keys=True,separators=(',',':'),allow_nan=False)`，不通过解析 operation_id 推导工步。调用方负责提供权威来源/当前状态，而不是接受模型自报的状态。问题时间必须等于当前 state 时间，base version 必须一致。

## 差量结构

顶层仅接受 `schema, anchors, plan_header, order_policy, tasks, holds, machine_orders`。

- `schema="smt-fullfab-explicit-plan-delta-v1"`。
- `plan_header` 由模型明确给出新版 `version,created_at,valid_until,freeze_until,reason,scope`。全部当前生产机台仍在 scope；没有自动延长窗口或裁剪。
- `order_policy="preserve_base_machine_order_unless_explicit"` 是模型明确选择的保留规则。
- `tasks` 与 `holds` 均包含 `keep,cancel_ids,replace,add` 四项，不能省略。

任务保留有两种表达：

```json
{"keep":{"mode":"ids","ids":["task-a","task-b"]},"cancel_ids":["task-c"],"replace":[],"add":[]}
```

或：

```json
{"keep":{"mode":"all_pending_except","ids":["task-c"]},"cancel_ids":["task-c"],"replace":[],"add":[]}
```

这两例均要求 pending 恰为 a/b/c。`ids` 是明确保留集合，不表示新的机序；机器上的相对顺序保持 base 原样。所有 pending 必须恰好分为保留、取消、替换，不能把未列出的任务默默丢掉。`all_pending_except` 的例外列表必须恰等于取消与替换 ID 的并集，不能把例外理解为自动删除许可。

`tasks.replace` 是模型给出的完整 task 字典，沿用要替换的 ID；`tasks.add` 是全新的完整 task 字典。必须明确提供 `id,machine,lot_ids,steps,visits,operation_ids,not_before`；其余字段也原样保留或按模型完整替换，不替模型生成数值。编译器核对当前 operation identity、公开资格、族与批兼容/批量上下限，失败只报错。它不选可行的替代 lot、批成员或机台，不改输入类型。

当前公开观察也必须满足严格类型：`operation_id,lot_id,family` 是非空字符串；`step,visit,batch_min,batch_max` 是正整数，且最小批量不大于最大批量；`eligible_machines` 是非空、不重复的整数数组，每台机器必须在当前 scope 和该工序设备族中。公开 `batch_key` 保持观察导出的 `[part字符串,step整数,name字符串]`，其中 step 必须等于工序 step。当前机器、scope 与 base scope 的机器身份也必须为准确整数。`bool` 和浮点 `1.0` 都不能冒充整数 `1`；不先依赖 Python 的宽松相等判断，也不自动转型。重复的 operation ID 或 lot/step/visit 身份拒绝。这些检查覆盖整份当前观察，不只覆盖模型最终选择的工序。

新增任务或跨机移动后，所有受影响机器必须给出 `machine_orders=[{"machine":1,"task_ids":[...]}]`，完整列出该机输出中的所有任务，搬空机器也要明确空数组。其他机台也可明确给出重排，但不能漏项、重复、混入别机任务。编译只按这个显式列表排列同机任务；无声明机器做稳定保留/删除，不按 priority、任务 ID、机器 ID 或预计收益排序。跨机的全局数组交错只是序列化位置，不创建工艺优先关系。

hold 没有原生 ID，因此用准确 base hash 下的原数组索引引用 `h:0,h:1,...`。它们的 `keep.mode` 可为 `ids` 或 `all_except`；后者的例外必须同样恰等于取消与替换 refs。`holds.replace=[{"ref":"h:0","hold":完整hold}]`，`holds.add` 为完整新 hold 数组。所有 base holds 都须有明确归属，不自动过滤过期等待。

## 必须拒绝的“机械修复”

保留 task 逐字段保持准确 JSON 值；保留旧 `not_before < now` 只在与仍冻结的原 task 完全一致时可通过。其他情况需要模型显式 replace，**没有默认 `max(now,not_before)`**，也没有批量平移/归一化选择器。相同数学数值的不同 JSON 数字表示在冻结一致性哈希下也不被偷偷改写。

hold 的 `after_task_id` 必须仍指向新计划中同机任务。该锚点已执行、已删除或移到别机时，不能自动改成无条件 hold 或迁往另一任务；必须模型明确取消/替换，否则拒绝。取消一批的部分成员不会自动缩批、补批或取消后继。

冻结集合从实际 base 的 `freeze_until`、当前时间和派工身份判断：当前时间仍小于原冻结期限，且未派工任务的 `not_before` 小于原冻结期限。只要该集合非空，新计划就不能缩短原 `freeze_until`，否则报 `frozen_horizon`；不会自动执行 `max(old,new)`。这阻止先提交任务原样但把冻结期限缩到 now、再用第二次差量删除原冻结任务的绕过。原冻结期已结束，或原冻结任务均已派工时，这条期限保护不再适用；其他时间和任务检查仍须通过。

对有冻结任务的每台机器，编译器取得准确 base 的**未派工同机序列，从首项到最后一个冻结任务的完整前缀**。该前缀全部任务必须逐字段原样保留，仍在该机，并且在新计划同机序列的开头保持准确位置和顺序；前缀中即使有 `not_before` 在冻结期外的任务，也不能删除、替换其值、迁往另一机器或挪到前缀外。新增任务或原来位于前缀外的非冻结任务不能插到前缀前方或内部，即便模型给出显式 `machine_orders` 也拒绝（`frozen_prefix`）。前缀之后仍可进行显式修订。已派工任务从原序列中先排除，不重新提交。输出 `preserved_frozen_prefixes` 记录每机受保护 IDs 与原前缀任务 hash，便于外层独立核对；它不认证物理可行。

上述规则比只保持冻结任务子序列更严格。例如 base 的同机序列为 `[z(非冻结),a(冻结)]`，仅检查 `[a]` 会漏掉删除或迁走 z、或者插入新任务的情况；本编译器保护完整 `[z,a]`。观察里的 `problem.frozen_tasks` 带有额外投影字段，不能冒充准确 base 原字典。保留工序不在当前公开 problem 中也拒绝，不猜测未来路由或访问身份。本开发规则尚未接入共同执行器或独立运行审计，不能据此声称当前运行接口已经修复。

错误抛出 `DeltaError(code,detail)`，保留原输入与诊断。外层后续必须保存拒绝的原模型输出及错误，而不能丢弃后自动再构造一个 delta。

## 编译证据不是模型归属认证

输出 evidence 绑定四锚、原 delta hash、完整编译计划 hash、排除的已派工身份、全部取消/替换/新增引用、每个 task/hold 的来源和显式机序。`model_attribution_certified=false`，并明确标注仍需共同 commit 检查与独立物理/来源审计。

外层尚未实现。未来版本必须绑定真实模型 call ID、原 request/prompt/schema/output、四锚、编译结果、共同验证反馈及模型显式 commit；只有编译成功不构成执行授权。独立审计应从原输出与 base/state 重建差量归属，不复用本编译器作为唯一证明。还须验证 setup/minrun、在加工占槽、工艺前后、绑定、冻结、覆盖机会等完整共同约束；本模块不声称已经证明全部物理可行。

本版本不实现 COND 自动取消、不接当前 B/C 控制器、不修改执行器或物理语义。未来如开放，应以共同可审计计划语言供 A/B/C 使用；B 仍不能借此调用经典修复或获得后台补齐。重新请求模型、修订次数、日志、预算和恢复协议需另行冻结，不能套用本次单元测试结果作为真实 B 运行验收。

验证命令：`.venv/bin/python -m unittest tests.test_smt_fullfab_plan_delta -v`。当前 29 项测试仅使用小型合成字典，无模型、求解或工厂运行。冻结回归包含连续两次差量绕过、前缀首部/中间插入、前缀非冻结成员迁走/删除/改值，以及无未派工冻结任务时可正常缩短期限的边界；类型回归包含 bool 与等值浮点伪装身份、机器资格、批量及 batch key。


## 后续持久层与真实输入尺寸复核

隔离持久层草案保存在 `artifacts/smt_fullfab_review_drafts/B_delta_runtime_v1/`，root与独立审查各通过18项小测试。它记录原调用字节、session动作、同一store的唯一选择、外部commit意图及回执；读写认证只涉及结构和状态机。候选语义、真实模型归属、实际物理提交均保持未认证，尚未接入真实B。恢复的SQLite解析和文件hash现绑定同一文件描述符快照；路径被替换时拒绝，不自动重放模型或commit。

另用已结束B的真实最终快照、原problem006和20页v2观察验证纯查询尺寸，root重跑与保存报告逐字段相同。base395个任务中2个已派发，393个pending；有56个hold及4349个公开工序。完整DeltaSession目录80137字符；目录与单页反馈直接拼接时17/20页超过120000字符，目录与全部pending反馈达151206字符。按页0..19累积完整诊断query history，首个组合即超门，20页达1115064字符。该诊断不是实际模型历史，不含额外静态指令，没有测token或证明调用成本下降。原始记录见 `artifacts/smt_fullfab_diagnostics/B_delta_prompt_size_v1/report.json`。

后续应在完整数据可查询、原始反馈保留、无质量筛选的前提下设计索引分页与模型自己明确提供的记忆/查询协议，先按真实字符门验证，再做归属与预算/执行集成。当前的编译、session和持久草案均不能直接作为真实B启动入口。


后续纯prompt目录/模型记忆协议已通过root22项与独立7项检查，仍未接transport或执行器。使用同一B最终快照的完整20页与全部393个pending任务，实际build_prompt得到3039字符首目录、5372字符首请求；原页反馈加8190个ASCII字符的合成记忆占位后，最长请求70122字符；全部pending反馈为84898字符。root重跑报告逐字段相同，未缩页、过滤、生成delta或新增模型调用。原记录见 `artifacts/smt_fullfab_diagnostics/B_delta_prompt_size_v2/report.json`。合成记忆只测字节/字符容量，不是模型策略。单次完整delta输出仍需模型显式分块构建与封存；纯装配草案虽已过root28项测试，独立审查、持久记录和最终执行接线仍未完成，不能宣称真实B已具备完整运行能力。
