# 全厂经典优化的设备族分解（开发候选）

本文件解释 `src/smt_fullfab/decomposition.py`。它复用 A/C 的同一个 `optimizer.solve_plan`，在完整工序图上做前驱就绪分层、设备族子问题求解、上游完成时间传播、机台预约状态传递。它不会推进环境、调用模型或将未排任务交给背景规则。B 不得访问它。

## 触发改进的真实证据

保留的 `runs/smt_fullfab_development/A_1701_1h_v1/` 是失败记录，不得覆盖。该次完整工厂的初始 problem 含 913 台机器、4352 个当前/未来工步，规划窗口 4 小时、深度 2、每机 2 个 slot。全局 CP-SAT 建模为 4211 个候选批、159594 个分配布尔变量、214887 个总变量、459354 条约束。

模型构造耗时 3.377 秒，求解实际 4.396 秒、注册上限 5 秒；状态 UNKNOWN、branches=0、conflicts=0、无可行计划。总工具时间 7.794 秒。这说明限时内尚未进入分支搜索，不能据此声称约束不可行、基线效果差或 Agent 更好。运行在仿真时间 0 停止，原始输入、solver 输出、异常、资源记录与恢复 checkpoint 均已保留。

## 协调过程

1. 从完整 operation DAG 计算深度。第 0 层是没有未完成前驱的工步；后继所在层比其所有前驱深一层。所有可见 lot 进入图，不按分数删掉候选。
2. 每一层按设备族形成子问题。只有其所有前驱已在累计明确计划中的工步才进入该层的可计划集合。此前未排的同族工步也加入后续同族层，允许早先无法满足组批下限的 lot 与后来上游流出的 lot 组批。
3. 外部前驱以已安排的加工、装卸、运输完成时刻转换为 `release_time`；子问题保留全部该族生产机器，并交给共同 CP-SAT 做具体组批、选机、排序、未来时刻和 setup/minrun 选择。
4. 保存子问题完整输入/输出。把被选任务合并为全局唯一 ID、机上顺序与 predecessor_task_ids；将每台机器明确预约的尾部可用时刻、setup/minrun 和仍占 cascading 槽的加工区间传入下一层。
5. 下一层只基于已得到的上游安排传播。返回前再独立断言每个已选后继确有被选前驱、且 start ≥ 前驱 end。没有可行子解的族无任务，不调用 FIFO 或其它规则补排。

这不是单个当前时刻的派工评分器：同一个返回计划可包含尚未到达下游族的 lot、跨族未来处理、再次回到上游族的重入工序、明确时间与跨族依赖。每个生产启动仍必须来自返回计划。虚拟等待由共同物理环境处理，不冒充生产决策。

## 下游压力与局限

每族的名义工作压力取完整已公开 lookahead 内 `Σ(预计加工时间 / 最大批量) / 机台数`。上游工序代理目标的 `remaining_work_seconds` 增加 `load_pressure_factor × 后继不同族工作压力之和`。调整值逐工步记录在 `coordination`，默认 factor=1，属于需要开发集调参的透明经典协调项，不是未来随机信息，也不是其它方案答案。

机器每一层的任务在此前累计预约尾部之后追加。实现 **没有回填早先空闲间隙，也没有重新优化已固定的上游顺序**；压力只是下游拥塞的近似。它不是标准 shifting-bottleneck 文献算法的复现，更不能把分族局部 OPTIMAL 拼成全厂 OPTIMAL。共同内层模型依据 [OR-Tools 作业车间建模](https://developers.google.com/optimization/scheduling/job_shop) 的资源和先后约束，具体批处理与状态递推见 `optimizer.md`。

该实现是对真实模型规模障碍的可审计改进候选。需要与合理参考策略、全局小规模可解对照、其它压力/slot/窗口设置比较后，才判断它能否担任正式“强经典基线”。不得因为能启动更多设备就跳过强度与辨别能力验证。

## API 和整体预算

```python
from src.smt_fullfab.decomposition import solve_decomposed_plan

response = solve_decomposed_plan(
    problem,
    time_limit_seconds=10.0,     # 全部子求解 requested seconds 之和
    seed=11,
    max_slots_per_machine=4,    # 每机、每层上限
    max_assignment_variables=250000,  # 每个子问题
    plan_version="dev-1",
    load_pressure_factor=1.0,
)
```

`time_limit_seconds` 范围 0.01..3600，是累计 CP-SAT 请求上限；与内层 `solve_plan` 的单次上限区分。预先根据所有 `(工序深度, 设备族)` 单元分配预算：每单元最低 `minimum_family_seconds=0.01`，其余预算按 `sqrt(候选资格数量 × slot数)` 分摊，单次最高 60 秒。当前驱未排而没有可用工序时，不发起该次求解，也不挪用其未用预算做无限重试。累计请求不会超过总额。

低于全部族单元最低请求之和时返回 `BUDGET_TOO_SMALL`，零次求解、全部工作仍列为未排。默认按完整 DAG 深度推进；如人为设置 max_rounds 较小，则其它工步全部明确标为 `explicit_wave_limit`。正式配置不得将这种限制当成永久排除难排工步的渠道。

所有子调用串行、单 worker。构造、归并、输入输出留存的成本包含在总 wall_seconds，不被 CP-SAT 的累计求解上限包含，运行器仍要另设整个任务外部超时。`family_solves` 保存每个协调后的 problem 与完整 response，故日志体积需要实测，不能沿用旧两机试验成本。

只读初始问题估算：深度 2 含 184 个设备族层单元（97+87）。每机 2 slot 时，累计 10 秒预算对应单元约 0.013..0.451 秒；30 秒约 0.022..1.531 秒；60 秒约 0.035..3.151 秒。最大族仍为 DE_FE_86：初层 114 工步、118 台资格机器，约 26904 个分配变量上界；下一层 137 工步，上界 32332。上述是规模/分配推导，**不是已经验证这些预算足以求出全厂计划**。

## 结果判读与失败保留

返回与共同 plan 兼容的 `version,scope,created_at,valid_until,freeze_until,reason,tasks,holds`，scope 为全部输入生产机器。顶层包含 `family_solves`、`family_failures`、`coordination`、逐工步 `unplanned_operations`、累计请求/实际求解/总时间。只有有任务或空工厂时整体 solver_status 为 FEASIBLE；没有任何生产任务时为 NO_PLAN。

**FEASIBLE 不等于全部设备需求被成功求解。** 某些族有明确计划而其它族 UNKNOWN 时，整体计划仍满足已经安排任务的约束，但 `decomposition_status=PARTIAL_SOLVER_FAILURE`，所有局部失败及受阻后继完整保留。有候选却未排的机器 hold 必须计入遗漏/等待审计，不能仅检查 success 标志。整体 objective/best_bound 为 null，局部目标与界仅在对应子记录解释。

每机无任务时的 hold 是明确的此方案等待提案。它不会向等待机器补排新任务，也不能用于声称已经完成需求覆盖。运行器应按预登记的重排/失败规则处理遗漏，研究报告展示因求解预算、组批不足和上游受阻造成的未排比例与等待。

此版本遇到未启动的 frozen_tasks 会 fail-closed：必须保留既有冻结计划直到冻结期结束，不能悄悄移动这些未来承诺。默认 freeze_until=now 支持无额外冻结的开发试验；其它冻结政策尚不能宣称全部支持。共同模型的有限候选批、名义耗时、计件 PM 未预测、CQT 边界仍然适用。

## 已执行验证

` .venv/bin/python -m unittest tests.test_smt_fullfab_decomposition -v`：9 项合成测试通过，约 0.044 秒。覆盖跨族运输/先后、重入机器预约、早先未满批 lot 与后续到达 lot 组批、无上游计划不造下游任务、跨层 setup/minrun、未来同机绑定、累计预算拒绝、下游压力证据以及冻结任务拒绝。UNKNOWN 分支仅通过单元测试注入进行故障处理验证，不是实验性能证据，也没有用 mock 冒充真实模型调用。

开发 Agent 未运行完整工厂密集求解；后续完整输入试验由主流程在隔离资源与新运行目录内执行，原 A_v1 失败保持不变。


## 后续显式经典可行起点

在保留上述失败后，加入 `incumbent.md` 说明的共享 classical incumbent/hint。每族未知时仅在该候选独立名义检查通过后保留为 FEASIBLE_HEURISTIC，原 CP 状态不变；整体新增 heuristic_families 并采用 FEASIBLE_HEURISTIC 状态。每机序列尾部声明 after_task_id 条件等待。它们属于显式 A/C 算法步骤，不是 executor 或 B 的默认接管。旧 v1 结果不回写、不改名、不算新实现结果。
