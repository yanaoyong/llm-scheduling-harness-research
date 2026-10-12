# 全厂指标与独立审计：开发定义 v1

本文件定义开发实现，不代表正式实验已经冻结或完成。主实现 `src/smt_fullfab/metrics.py` 仅读取轨迹的 manifest、release、lot_complete、ready、dispatch、downtime 等事件，不调用仿真器、求解器、控制器，也不读取 `result.status` 作为真实性依据。

## 主指标

统计窗口为 `[s,e]`，实际释放时刻为 `r_i`，交期为 `d_i`，全路线完成时刻为 `C_i`，未完成时令 `C_i=+∞`。累计优先级加权逾期时长为：

\[
J(s,e)=\sum_i w_i\int_s^e\mathbf1(r_i\le t<C_i)\mathbf1(d_i<t)\,dt
=\sum_i w_i[\min(e,C_i)-\max(s,r_i,d_i)]_+.
\]

单位为加权 lot·秒，越低越好。完成与未完成 lot 均贡献到其完成时刻或窗末。窗口开始前已经逾期的 lot 从 `s` 立即累计，但不会把窗口之前的历史逾期再次计入。原始 WIP 的历史 release 用于完成者周期；其本次仿真实际进入系统的 release 事件用于本观察窗口的曝光计算。这样不会将冷启动前的历史 WIP 年龄重复计入 `J`。

开发默认权重为源优先级 `10→1, 20→2, 30→3`，更大数值权重更高，输出完整映射。未知优先级、非正或非有限权重使指标计算失败，不默认归零。该线性权重尚需结合源语义与开发证据正式冻结。接口可以接受显式 `priority_weights`，不能在看到正式结果后调整。

主指标保留原始总量，并分列完成者与窗末未完成者贡献。辅助归一化为：

- `mean_tardy_seconds_per_weighted_lot`：`J / Σw_i`，分母包含窗起 WIP 和窗口新投入，排除在窗口开始时已完成的 lot。
- `tardy_fraction_of_exogenous_weighted_exposure`：`J / Σw_i[e−max(s,r_i)]_+`。分母不随窗口内完成早晚缩短，避免以少完成改变分母；同一快照和投入流下三方案分母相同。

没有 lot 或曝光时对应归一化值为 null，不填 0。禁止比较不同投入/初始化的主指标后直接归因为排程改善。由于尚未进行正式指标和资源协议冻结，输出标记 `priority_weight_status=development_proposal_requires_prefreeze`。

## 辅助指标

全厂吞吐按本窗口满足 `s<C_i≤e` 的完成 lot/wafer 计数。`initial_window_wip + released_in_window = throughput + terminal_wip` 必须成立；窗口起点同一时刻释放计入起点 WIP。终末逾期 WIP 为窗末尚未完成且 `due<e` 的 lot。完成者周期为 `C_i−历史release_i`，没有完成者则为 null。按产品和优先级同时输出完成者准时率的分母、终末 WIP 和终末逾期 WIP；完成者准时率明确是条件指标。

全部生产设备族均输出 ready→dispatch 的等待 lot·秒、派工和工序 lot 数，以及由区间并集计算的资源预约、材料在场、日历停机观测比例。含设备族全部生产设备，即使没有派工。停机修订已发生的 reservation/process_end；重叠区间不重复累加。它们不宣称精确有效加工利用率或因果瓶颈。setup 损失按 dispatch 到 `dispatch+setup_seconds` 裁剪观察窗累计，当前是声明的 setup 用时，尚不分解因停机额外造成的 setup 阶段暂停。

批填充涵盖所有 `batch_max>1` 的生产批派工，即使只有一个 lot 或窗末未完成，使用 `批lot数/batch_max`，并报告批数。不把虚拟等待当作生产派工或生产批填充。计划提交、修订、显式等待、覆盖缺口和派工来源由审计器分别计数。模型/求解器/仿真/审计墙钟、token、失败和账单由运行器新账本汇总，缺失成本不可用 0 替代。

对于失败的部分轨迹，指标只累计到实际观察的末事件，`completed_declared_window=false`，不能和成功全窗口无条件混合。超出观察末端的指标请求会报错。暖机后窗口可以指定 `window_start`，但必须保留完整前史。snapshot 恢复事件只有在包含原始 initial 起点及完整 prefix 计数时才接受；指标本身不认证 snapshot 文件真实性。

## 独立检查分层

`src/smt_fullfab/audit.py` 的 `audit_plan_sources` 逐事件独立验证全生产设备责任域、plan scope、唯一版本和任务、lot/step/visit 明确分配、机器内顺序、冻结任务保留、开始条件、计划有效期、显式 hold，以及每个生产 dispatch 对准确 plan version/task 的关联。生产 owner 必须为 plan，虚拟等待 owner 为 environment。真实派工没有来源，即使结果写着 success 也失败。

`audit_trace` 另将物理事件投影到旧独立事件检查器：对已独立核对来源的每个生产 dispatch 插入检查器需要的等价 action，重新编号并只在投影内将 owner 改为 controller。原始文件不改变；这些合成 action 不计为模型决策。旧检查器重建加工/组批/资格/绑定/换型/维护/故障/抽样/返工/守恒，提供 data 目录时另校验源文件。此复用是修订内核的独立事件校验，不是官方模拟软件一致性证明。计划审计与物理审计任何一个失败都会使总审计失败。

独立 `audit_opportunity_coverage` 不读取执行器的候选表，而从物理事件重新建立 lot 的等待工步、产品、visit、设备绑定，以及机台 ready/down、最小连续换型次数、正在加工 job 和槽容量。在每条 `time_advance` 之前遍历全部生产机台：若有满足组批下限的合法需求，必须有该机台尚未执行的明确任务或未到期的 hold；单一合法动作也不能省略。等待特定尚未 ready 的已提交任务有明确计划归属。如果首项任务已满足全部执行条件仍直接推进，审计也会拒绝。执行器不能通过伪造较大的 `to` 跳过资源释放、hold 到期或计划到期来绕过检查；这些区间内边界同样检查。正的时钟变化必须被明确 `time_advance` 区间覆盖。

记录的 `coverage_gap` 机器清单、设备族和候选数量须与独立回放结果相等。各设备族另报告每次实际生产 dispatch 之前的立即合法组合数、单一/多种选择次数、加工时间与换型差异，以及自动时钟推进的检查次数。这些是描述性重复观察，不是独立统计样本，也不是模型决策次数。

只有计划来源、独立机会检查和完整物理事件回放同时通过，`absence_of_unreported_legal_demand_certified` 才为 true。该字段的范围是“推进时没有未计划也未 hold 的合法机台需求”，不等于所有 lot 都获得服务或等待合理。为暴露有意拖延/永久排除，另报从未出现在任何计划中的 ready 工序 visit 数、窗末未计划清单、未被当前计划覆盖的等待 lot·秒和最大未计划等待时间。显式 hold 可以合法延迟全部生产，但吞吐、终末 WIP 和累计逾期仍会揭示其后果；不能用合法性替代质量与饥饿诊断。

复现入口：

```sh
.venv/bin/python -m unittest tests.test_smt_fullfab_metrics tests.test_smt_fullfab_audit -v
.venv/bin/python -m src.smt_fullfab.audit trace runs/smt_fullfab_<phase>/<run>/trace.jsonl --verify-data-dir data/smt/SMT2020_LVHM
```

现有测试包括手算的完成/未完成联合逾期、窗起已有逾期、子窗口、零完成、未知权重、部分轨迹，以及伪造 success、无计划派工、lot/step/visit 与时间条件篡改、冻结任务删除、物理加工时间篡改、缺终止事件和 snapshot 前史缺失。机会检查另有单一合法动作被跳过、伪造 gap、未声明时钟跳变、跨越 hold 到期、可立即执行的已提交任务被遗漏，以及合法显式等待的反例测试。它们验证有意义的失败路径；正式现场校准与真实对照仍需另行完成。
