# 全厂 A/C 共用有限窗口优化器（开发实现）

文件：`src/smt_fullfab/optimizer.py`。本模块不修改旧 `src/smt/optimizer.py`，不导入旧即时评分器，不调用模型通道、不推进仿真，也不补齐其它方案的动作。B 不得访问此工具或其候选批生成结果。

## 当前证据与资格

这是 **需要全厂开发集性能与质量校准的经典基线实现**，不是已经证明足够强的冻结正式基线。合成测试证明它联合安排未来工序、设备、组批、开始时刻和跨族先后关系；不能凭测试通过就声称完成官方复现、全厂长窗口可运行或 A/C 正式对照。

2026-10-09 已执行 ` .venv/bin/python -m unittest tests.test_smt_fullfab_optimizer -v`，15 项通过，累计测试时间约 0.05 秒；每次限时 0.25 秒或更短、单 worker，无真实模型调用。测试覆盖下游加工差异改变上游同条件工步排序、跨族后继、运输、当前加工、组批最低数量、setup/minrun、已知停机后 setup 重置、cascading 占槽、机台绑定、冻结任务、整数保守取整、图环与错误输入拒绝，以及限模/不可行时不接管。

## 方法来源和实际模型

采用 OR-Tools CP-SAT 的整数时间作业车间建模方法：工序先后约束与机器资源互斥，参见 [官方 job-shop 教程](https://developers.google.com/optimization/scheduling/job_shop)。可选区间、累积容量和有条件线性约束构成此实现的批处理扩展。状态、可行解、限时、界的解释参见 [官方 CP-SAT 文档](https://developers.google.com/optimization/cp/cp_solver)。固定依赖沿用 `requirements.lock` 中 `ortools==9.15.6755`；没有声称本实现复现某篇完整晶圆厂算法或获得全厂最优解。

所有进入滚动窗口的工序建立 presence、start、end 变量。后继进入计划必须同时安排其尚未完成的前驱；后继开始不早于前驱加工、装卸、运输合计完成时刻。跨族依赖存在于 **同一个 CP-SAT 模型**，不靠互相独立的设备族即时评分近似协调。当前仍在加工、已经完成或未包含的工序不能用缺失 predecessor 蒙混通过，已知完成时刻须变成当前工序的 release_time。

每台机器建立有序 slot，默认最多 8 个、可配置 1..128。每个 slot 决定选哪个具体批，批同时决定 lot 集合；同一工序最多选择一次。非空 slot 连续排列，但其间允许等待，因此排序不是候选生成顺序。所有机器都记录为考虑对象，没有按族或产品永久排除；无候选机器无需创建无意义变量。每次重排重新读取全体活动 lot 的统一深度工步。slot 上限限制窗口可排的工作量，必须在开发阶段检查限制是否影响吞吐、长期覆盖和不同方案公平性，不能将未排 lot 称为完成覆盖。

每个 slot 的 setup 类型由选中的批决定。状态转移表给出上一个 setup 到本批 setup 的耗时，优先使用 route 的 setup_time，再用 old/new 矩阵和空 setup 回退。换型后最低连续运行数与批 lot 数逐 slot 递推；当前 min_left/min_setup 一并输入。已知停机跨越两个 slot 时将前一个 setup 清空，保留 minrun 计数。非 cascading 机器逐 slot 互斥；cascading 以节拍占机时间确定下次可启动时刻，加工区间另以容量 2 限制同时占槽，包含快照中仍在加工的固定区间。

历史绑定体现在 eligible_machines；窗口内的新绑定可用 `same_machine_as` 要求两工序选择同一机台。启动条件只是计划提案，实际执行仍由共同独立检查器验证。未来步骤的返工、抽检结果不可预知，不进入工具输入。

## 候选批空间与界的含义

单 lot 工步包含全部合法 lot/机器选择。需组批的工步按 family、batch_key、setup、批量界及时间参数分组，并对每台资格机器分别生成候选批。使用 EDD、最早 release、最高 priority、最早 `due - remaining_work` 四种顺序；取最低批量与可用最大批量的全部滑动窗口，去重后联合优化。每个 lot 均参与候选生成，没有按任务排名取前 K 个，也没有缺额时私自降低最小组批量。

这不是完整组合枚举，中间批量、其它成员组合可能被遗漏；未来数据变化还可能使个别 lot 暂时无法组批。输出逐工步 `unplanned_operations`，必须持续跟踪长期未覆盖与可行候选不足。工具输出候选池 hash、候选批数、变量数及全部考虑机器 ID；输入可确定性重建池。容量上限只会拒绝整个求解并报告 `MODEL_SIZE_LIMIT`，不会静默删掉困难族或 lot。

CP-SAT 的 objective/best_bound 只对应 **当前窗口、有限 slot、限定候选批、期望耗时、此代理目标**。即使 `OPTIMAL`，也只是在该受限模型内最优，绝不是 SMT2020 全厂最优值或正式研究业务指标的最优性差距。纯 CP 模式的 `UNKNOWN`、`INFEASIBLE`、`MODEL_INVALID` 不提供 CP 解。后续加入的显式经典起点可被透明保留为 FEASIBLE_HEURISTIC，须经过独立名义检查并保留原 CP 状态；详见 `incumbent.md`。这不是执行器规则接管。

## 目标函数和开发调参

最大化每个工序的优先级加权进展奖励，减去完成时刻、剩余工时投影延期及 setup：

`Σ_i priority_i × (completion_weight × presence_i − flow_weight × end_i − tardiness_weight × max(0, end_i + remaining_i − due_i)) − setup_weight × Σ_slot setup_seconds`。

任务仅要求在计划窗口内启动，允许加工/运输在窗口后结束；名义完成上界为窗口终点加最长候选任务时间（含最大 setup）。未排工序的 end 为该扩展上界，仍受延期与排队惩罚；优先级用不小于 1 的整数上取整。计划有效期限制新启动，不能删除窗口终点仍加工的 WIP。时间以窗口起点为零。默认权重 `{completion:3600, flow:1, tardiness:4, setup:1}` **只是可审阅的开发初始参数**。该目标不是研究主指标“观察窗内加权累计逾期时长”的严格等价模型；会随工序展开深度改变。因此必须在开发集比较参考派工、合理其它权重、窗口和重排频率，检验真实业务质量、候选组批偏差与饥饿风险。验证后 A 固定参数，C 可以选择同一模型白名单参数；不得为让 C 胜出而故意冻结弱 A。

## 输入契约

```python
solve_plan(problem, *, time_limit_seconds=1.0, seed=11, weights=None,
           max_slots_per_machine=8, max_assignment_variables=250000,
           plan_version=1, freeze_until=None, deterministic_limit=None,
           use_incumbent=True, incumbent_max_seconds=1.0, incumbent_rule="gain_rate")
```

problem 必填字段：

- `time`、`horizon_end`：绝对秒，有限计划窗为 1 秒至 28 天。
- `machines`：全体生产机器；每项 `machine:int, family:str`。可选 `available_at`（默认当前时刻）、`current_setup`、`min_left`、`min_setup`、`cascading`、`processing_until:[absolute_process_end,...]`、`unavailable_intervals:[[start,end],...]`。
- `operations`：全部在统一观察/展开规则下纳入的工步。每项必填 `operation_id:str, lot_id:str, step, family, eligible_machines:[int], processing_seconds`；可选 `occupation_seconds`（默认 processing）、`machine_times:{machine_id:{processing_seconds,occupation_seconds}}`、`transport_seconds`、`release_time`、`predecessor_ids`、`visit`、`batch_key`、`batch_min/max`、`setup`、`setup_time`、`priority`、`due`、`remaining_work_seconds`、`latest_start`、`same_machine_as`。
- 可选 `setup_transitions`：`[{old,new,seconds},...]` 或 `{old:{new:seconds}}`；`min_runs:{setup:count}`。
- 可选 `frozen_tasks:[{operation_ids,machine,start},...]`：必须保留的未来明确派工。指定成员组合必须仍在当前合法候选池，否则显式拒绝，调用方保留旧计划/报告冲突，不可悄悄取消冻结任务。

processing 含装卸；occupation 含所用语义的节拍/装卸；transport 是 **此工序完成到下一工序可用** 的运输。未完成前驱包含在 operations 内；已经完成或当前加工中的前驱以其已知可观测可用时刻进入 release_time，不可填未来随机结果。虚拟等待可由共同环境传播为 predecessor release/transport 延时，不把 400 个 Delay 资源当需要 Agent 派工的机器。

所有 release、加工/节拍/运输时长向上取整，due 与窗口终点向下取整，单位 1 秒；这是保守离散化，原始数值仍由输入 hash 绑定。非整数当前时刻作为绝对基准保留。当前已有的已知停机与加工结束估计应先由环境按共同语义计算。生产工序持续时间必须正数；零时物理事件由环境推进。

## 输出契约与预算

`plan` 直接包含 `version,scope,created_at,valid_until,freeze_until,reason,tasks,holds`；version 为字符串，scope 明确列出全部机器 ID。每条 task 含具体 machine、lot_ids、steps、visits、operation_ids、sequence、not_before/start、expected_end/end、process_end、occupied_until、setup_seconds、predecessor_task_ids 与再检查启动条件。每个没有任务的机器有明确 hold 原因；有任务机器以 after_task_id 声明有限序列结束后的条件等待。有候选却未排的 hold 不得当作覆盖完成。

顶层保存 status、objective、best_bound、build/solve/total wall time、deterministic time、branches/conflicts、参数、问题 hash、候选池 hash、规模、逐工步未排原因和模型边界。调用方须保存原 problem 和完整结果；只有 hash 不能还原证据。求解器总是 `num_search_workers=1`，没有内部重试或并行解。

time_limit 仅约束 CP-SAT solve，**不包括模型构造、工具通信和检查器**；全部时间分别报告并计入端到端账本。max_assignment_variables 在建模前检查，默认 250,000，不随失败私自放宽。运行器仍须设置包括构造在内的外部超时和累计预算。A/C 的累计求解预算应共享同一统计口径。采用墙钟限时不能保证跨主机二进制同解；固定输入、seed、worker、依赖与可选 deterministic_limit 有助重现，但仍须保留实际解和界。

## 尚未消除的边界

- 随机加工、故障、返工和抽检只做名义预测；计划实施必须因新事件修订，不能泄漏未来样本。
- 已知停机不允许名义加工跨越，是相对 DES 暂停/续作语义的保守优化限制；并未实现可跨多个停机段的抢占式加工区间。
- 计件维护未在候选/slot 中预测；执行器必须对其实际引起的机台延迟和 setup 清空重新检查并触发重排。不能称为全部维护关系精确优化。
- CQT 只有显式绝对 latest_start 接口，不等于已实现完整工艺 CQT 关联。输入未提供的硬约束不能宣称已验证。
- 来自初始 WIP 的未知历史 binding 不由工具编造；只有快照中真实保存的绑定或窗口内同机关系受约束。
- 默认参数、slot、有限候选池和执行耗时还需要完整数据开发验证；正式强基线资格、长窗口稳定性、官方参考校准均留待主流程，不在此文件自验收。
