# 可审计经典可行起点与 CP-SAT 改进

`src/smt_fullfab/incumbent.py` 为 A/C 共用工具提供显式经典可行起点，B 不得调用。该模块不进入执行器，不读取随机未来，也不替没有提交计划的方案派工。每个生产选择先形成可保存、检查和归属的整版未来计划。

## 改进依据

保留的 `A_1701_1h_decomposed_v1` 在一个全厂计划上请求 30 秒累计求解预算，实际 177 个族调用：88 OPTIMAL、69 FEASIBLE、20 UNKNOWN；已排 1115/4352 个工步。工具约 28.15 秒，运行约 29.98 秒，仿真仍在 0 秒因计划覆盖缺口请求再次规划而耗尽总预算。这不是“多数族 UNKNOWN”；但缺少可行起点和有限计划结束后的明确等待，使微预算试验尚不能完成 1 小时。原始失败证据不覆盖。

后续实现将“先生成明确经典候选，再由 CP-SAT 改进”作为同一个经典算法流程。限时保留的经典候选必须标为 **FEASIBLE_HEURISTIC**，不能称 CP-SAT 已找到解、不能称 OPTIMAL，更不能用 UNKNOWN 状态替候选的可行性作证。

## 构造算法

使用与 CP-SAT 完全相同的合法批候选池。每个候选包含确切工步成员及资格机器。只有所有未完成前驱已经进入累计计划，且未来同机绑定的源工序已经选机，候选才可进入全局优先队列。

对每个候选/机器组合，计算最早开始：当前机台可用时刻、所有成员 release、所有上游加工/装卸/运输完成时刻的最大值；叠加当前仍在加工的 cascading 占槽；遇已知停机则右移至停机之后，并重新计算可能被清空的 setup。名义加工不得跨已知停机，与共享模型的保守约束一致。minrun 未满足时只能使用其锁定 setup。

默认 `gain_rate` 用共享有限窗口代理目标的边际收益除以本次新增占机及等待时间；另外提供透明的 `slack`、`priority` 开发规则。选择一个明确批后更新机台尾部预约、setup/minrun、加工占槽与工步前驱可达性，继续生成当前和未来跨族工序。每机 slot、规划窗口和构建预算均有上限；未排任务逐项保存，不能称全部已规划。

这是一种确定性多步 list-scheduling 可行起点，不是通过求解获得的最优解。规则与 CP-SAT 权重、slot、窗口需要一起在开发集比较、调参后冻结，不能据此声称强基线已经验证。共同 CP-SAT 资源/先后约束来源见 [OR-Tools job-shop 教程](https://developers.google.com/optimization/scheduling/job_shop)；此处启发式为项目透明实现，并非某个完整文献算法的复现。

## 单独的名义可行检查

`validate_nominal_plan(problem, plan, max_slots_per_machine=...)` 从输入重新逐机重算下列条件，不读取构造时的状态、堆排序或 CP-SAT 状态：

- 所有机器 scope、唯一工步和连续机上序列。
- 批成员、lot/step/visit、批量上下界、资格、共享候选池成员关系。
- release、跨族前驱、未来同机绑定、latest_start 与计划开始窗口。
- setup 与装卸/加工/运输/节拍时间算术、当前及跨序列 minrun。
- 当前加工、cascading 容量、已知停机、停机后的 setup 重置。
- 冻结任务（构造器当前拒绝自行重建非空未来冻结集合）。

检查器与求解器共享输入规范化和候选池定义，但不复用构造器的调度状态或时间提案逻辑。它只证明 **已公开名义输入和此模型边界内** 的可行性；不能替代执行后的随机物理轨迹/source audit。计件 PM 未预测、CQT 仅 latest_start 等已知边界保持公开。

## 与 CP-SAT 的组合

`optimizer.solve_plan` 默认增加：

```python
use_incumbent=True
incumbent_max_seconds=1.0
incumbent_rule="gain_rate"
```

先生成并检查经典计划，再给 CP-SAT 的工步 presence/start/end、具体批/slot 分配、机台起止/setup 变量提示，并增加“不劣于这个名义代理目标值”的约束。候选使用同一批空间与同一整数时间/目标函数，因此这一代理目标下界不会删掉优于起点的解。非整数仿真时刻以整数相对秒回写 hint，避免浮点减法误截为前一秒。

CP-SAT 有可行解时 `selected_source=cp_sat`，其实际状态、objective 和 bound 如实保存。没有 CP 解但经典候选通过独立检查时，返回 `solver_status=FEASIBLE_HEURISTIC, selected_source=classical_incumbent`；顶层 best_bound=null，原 CP 状态、界、限时和统计保存在 `cp_sat`，完整经典候选与检查保存在 `classical_incumbent`。模型规模拒绝也可保留经典候选，必须同时显示 `cp_sat.status=MODEL_SIZE_LIMIT`。

没有合格经典候选时仍按原有拒绝/无解路径返回，没有其它接管。`use_incumbent=False` 保留纯 CP-SAT 开发对照。未来冻结任务不会被构造器改排，交由原 CP 路径保留或明确失败。

族分解保存每个子问题的相同来源字段，新增 `heuristic_families`；若任一族使用经典起点，整体状态为 FEASIBLE_HEURISTIC。局部 CP 最优不能覆盖这些启发式来源，也不存在可合成的全厂最优界。

## 明确的计划末尾等待

有任务机器增加 `{machine,after_task_id,until,reason}`：仅在最后一个声明任务已派发、该机没有后续 pending 任务时等待至该版有效期或下一次明确修订。这不会从初始时刻挡住已有任务。没有任务的机器单独提交普通 hold，原因和未排工步保留。

这是有限计划序列结束后的方案明确等待，不是无日志的背景补排；未排需求、条件等待和因槽数限制停工必须单独统计。长时间积压与永久等待是需要开发集检查的问题，不能因有 hold 就宣称完成需求覆盖。

## 成本与当前证据

经典候选构建不消耗 CP-SAT 秒数，但构建、独立检查、候选重建、序列归并和日志都计入端到端 wall time。默认构造循环上限 1 秒、最多 250000 次候选计算；输入规范化、候选池建立和退出后的独立检查仍需要外部总运行超时。达到构建上限时保存部分合法计划、停止原因与未排任务，不无限继续。

执行了 ` .venv/bin/python -m unittest tests.test_smt_fullfab_incumbent tests.test_smt_fullfab_optimizer tests.test_smt_fullfab_decomposition -q`：34 项合成测试通过。覆盖跨族/重入/未来绑定、未来到达组批、minrun 与已知停机、当前 cascading 占槽、独立检查器拒绝篡改、模型规模拒绝时的透明保留、CP hint 不劣于候选、条件等待和非整数当前时刻。未在该开发 Agent 中运行完整工厂求解或新增真实模型调用；正式有效性和成本仍须主流程实测。

后续另行授权的 A_v3 开发运行在非整数重排时刻暴露跨层端点浮点累积误差。修复后构造器和检查器全部以整数相对秒计算端点，最后仅加当前时刻一次；不会把链式浮点相加产生的 `1.8e-12` 秒差当成实际重叠。保留原 problem 的 CP禁用诊断验证修复，另增加“真实整数重叠仍拒绝”的回归，相关小测试现为36项。完整试跑与失败、授权边界见 `A-development.md`，原失败不重写。
