# Harness v6：独立纯函数底座

本目录实现 Phase A（M0、M2），不导入原实验的模拟器，不调用模型或网络。
权威依据：`research/2026-10-17-codex-search/HARNESS_V6_PLAN_reviewed.md` 第二部分
及 `HARNESS_V6_LONG_RUN_ADDENDUM.md`（冲突时以后者和 COMMON 的最终决定为准）。

从本目录执行：

```bash
python3 -m pytest -q
```

Python 3.10+，生产模块仅标准库；测试使用 pytest。`pytest.ini` 把 `src` 加入路径。

- `plan_delta.py`：显式增量编译，保留原有锚点、分区、身份、资格、组批、冻结和顺序约束。
- `normalize.py`：不改写生产字段的幂等复制、时间解释、完整计划收集式校验。
- `executor.py`：纯队首开工判断；返回 `{task, reason}`，不执行物理派工。
- `facts.py`、`contracts.py`：来源顺序事实、分页、重建、版本和确定性编码。
- `prompt_rules.py`：后续快照及会话共用的规则文本。

任务字段 `start_mode` 可为 `when_ready`（省略时默认）或 `not_before`。
两种模式中的 `not_before` 都是可选硬下界；不会插入默认字段，也不会改写过去的值。
`normalize_plan` 返回分离副本。冻结比较保持规范 JSON 字节一致（整数与浮点拼写也有区别）。
没有下界的任务按原计划创建时刻判断是否属于冻结区。

`validate_plan` 接受权威 problem、execution_state 和可选 base_plan，返回有序的
`{code, detail}` 列表。`compile_plan_delta` 拒绝时保留 `.code` / `.detail` 兼容接口，
并在 `.violations` 返回所有可独立求值的生产约束违规。`validate_plan_delta` 返回同一列表。
结构无效、分区不明确或机组身份不可用时，依赖它们的编译步骤不能继续；此时返回结构错误，
不猜测一个计划来校验。缺失某任务身份数组不会阻止其他任务和 hold 的校验。

执行状态新增可选 `invalidated_task_ids`，必须由宿主提供、纳入状态锚点哈希，
只能指向待执行的原任务。只有显式取消才豁免冻结保护；改写或重排仍被拒绝。
取消后其余冻结前缀仍受保护。过期 hold 保留原值但不生效，包括已离开计划的旧锚定任务。

`decide_start` 的 readiness 映射以 operation_id 为键，值含公开身份/资格/组批字段和
`ready: bool`。机组状态含 machine、ready、down_until；可提供 available、legal 和
invalidated_task_ids。适配器负责从真实 lot 状态、运输、专用和 min-run 条件计算这些值。
队首未满足条件时不查看后续任务作为替代；条件 hold 只有锚任务已执行且队列空时生效。

来源文件及初次/最终复制哈希见 `isolation_manifest.json`。最初的 verbatim 编译器先通过
原有 29 项测试，之后才实施 M2；只反转了过时的 past-start 与 expired-hold 断言。
Mac 集成验收、物理一致性及后续阶段待办见 `MAC_VALIDATION.md`。

## Phase B：M1 账本与 M3 快照

新增 `ledger.py`、`audit_ledger.py`、`sealed_contexts.py`、`snapshot.py`，均为新写代码，
没有新增从 P 复制的文件，原 isolation manifest 的来源哈希不变。

账本直接使用 observation 的 `machines`、`operations`（包括 conditional、predecessor_ids、
release_time、eligible_machines、batch_key/min/max、setup）；机组使用 currently_busy/down、
min_left/min_setup。`available_at` 是预测，不代替已观测的忙闲状态。
已知专用通过 eligible_machines 表达；未知专用及未解析 same_machine_as 保守排除。
公开未来工序仍有行，状态为 ready_unreserved、ready=False，不算就绪工作。
缺失工序不等于完成；running/done/invalid 必须来自宿主回执。

`ledger_from_scratch(problem, plan, receipts)` 的 receipts 为：
`{"operations": [{"operation_id": "a", "state": "done"}], "tasks": [{"task_id": "t", "state": "invalid"}]}`。
任务级 running/done 会移出 pending，invalid 保留并显式显示。任务 ID 必须在当前执行账本内唯一；
适配器需要对计划版本进行命名空间处理，并删除过期任务/回执，不能把同名旧版本回执带入新任务。
assigned_not_started_age 使用任务已知的 assigned_at，缺省使用 plan.created_at，表示当前预留年龄；
跨版本首次预留年龄必须由宿主保留 assigned_at 元数据，不能从无历史的观察反推。

`ledger_apply(ledger, delta)` 原地应用并返回账本：time 为标量，其他表为
`{"upsert": [完整记录], "delete": [ID]}`。表名包括 operations、machines、tasks、holds、
receipts、task_receipts；主键依次为 operation_id、machine、id、id、operation_id、task_id。
无 ID 的原始 hold 使用内部 `hold:<源位置>` 索引，初次加载及快照保留原 JSON；新增 hold 的
增量记录需提供 ID。任务替换保留队列位置，重排通过显式删除并按新顺序添加受影响队列后缀。
重复应用同一 delta 幂等。单步更新只访问变化记录和变化任务的工序成员，O(变化量)，
不会扫描 WIP 或复制整个账本。`rows()` / `metrics()` / 完整快照是独立的全量读取，
其成本依赖当前状态；不要在每个事件后无条件调用它们。宿主负责在锚点/审计需要时读取。

可避免空闲采用**确定性贪心极大匹配近似**：按机组 ID 遍历空闲可用机组，对可开工、未预留
工序按精确 batch_key/min/max 分桶，按规范 JSON 桶键选择首个满足下限的桶，按工序 ID
取 batch_min 个，之后消费这些工序。一个工序不会同时覆盖多个机组；这不是最大匹配，
可能低估最优可利用机组数。顺序只用于计量见证，不生成生产任务、排名建议或派工。
组批上限、已知专用、min-run 均检查；需要 Mac 与真实 has_legal 对账。

有队列/hold 不视为覆盖；hold 下未预留工作也计入 avoidable_idle。
explicit_wait_idle 单独对每个有效 hold 机组检查可行批次，包含已预留工作。
条件 hold 必须锚任务已执行且队列为空；过期 hold 无效果。
两种空闲指标有交集，不能相加；explicit_wait 的不同机组可能共享候选批次。
reserved_but_earlier_startable 只报告其他空闲合格机组上的提前机会，不参与触发。
机会秒数来自公开 available_at/not_before 预测差，不是实际空闲积分；没有可用预测时为零，
不代表没有机会。静态分类按同一上下文/工序取最大差，避免多个替代机组重复计秒。

`audit_ledger.audit_ledger` 不导入账本或 normalize 辅助函数，独立枚举最小合法批次组合，
复算相同贪心口径；`reconcile` 返回所有指标差异。枚举复杂度高，仅用于小夹具/抽样审计，
不能直接当作大规模实时算法。它验证公开近似口径，不替代真实物理审计。

快照前缀由规则、工具描述、路由和机组静态表构建一次，并在各周期复用原始 bytes。
当前区包含全部 pending task/hold（包括失效和过期条目）、机组当前状态、全部调用者提供的
running jobs、全部未预留就绪工序、匹配、机会、失效任务、最近一次回执、当前模型笔记。
历史只保留固定 64 字符 SHA256 链摘要，不携带历史事件数组；完整历史留在外部证据日志。
调用者必须只传最新回执与当前笔记，不能把对话历史塞进这些字段。数值时钟/版本自身的十进制
位数可能随数值变化，历史长度不会累积到快照。测试使用 1,500 个等宽时间/版本验证恒定字节数。

默认 token counter 为 ceil(字符数/4)，只用于离线确定性估计。支持注入真实计数器，
超预算抛出 SnapshotBudgetExceeded，report 含计数、预算、字节数和完整行数，dropped_rows=0，
不返回被裁剪快照。partitioned/tiered 仅保留 mode 接口，明确抛 NotImplementedError。
Mac tiktoken 惰性适配器及封存 SQLite 只读适配器不在本地访问真实证据。
