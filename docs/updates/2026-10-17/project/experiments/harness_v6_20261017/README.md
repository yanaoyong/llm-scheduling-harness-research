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
