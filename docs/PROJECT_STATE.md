# 项目状态（截至 2026-10-12）

## 当前结论

项目同时包含三数据集正式对照、SMT2020 全厂直接排程开发研究，以及两轮 M0.5 文献/工程调研。它们是不同范围、不同证据等级的工作，不能合并成“全厂研究已完成”。三数据集正式验收已通过，但其 SMT 八小时方案只由 2/913 台设备接受控制，其余设备沿用统一固定策略；这不等于完整全厂自主排程。[实验 README](../source_snapshot/experiment_round2_3datasets/README.md)（原文 L1-L5） [范围说明](../source_snapshot/experiment_round2_3datasets/README.md)（原文 L28-L36）

2026-10-12 的 B 一小时开发运行完成场景 1701 的 0—3600 秒窗口，覆盖 913 台设备的排程责任，95 次计划提交、1071 次派工、涉及 841 台设备；独立来源、物理、机会审计及归属检查通过，构造器/求解器调用为零。这证明该窗口内的直接排程能力和合法完成，不证明优于 A/C、经济可用、满足实时调度或复现官方长期表现。[B 一小时报告](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L5-L15）

同日 A/B/C 报告是已保存 0—3600 秒开发方案的描述性比较，三臂主交付指标相同而过程指标不同；运行内核、控制器、审计版本有差异，不能据此作因果或普遍胜负结论。现有依据支持暂以 A 作短窗口工程基线；C 与 A 接近但模型增益未证实；B 验证了直接排程职责，质量、批处理、工序推进和计算成本仍待改善。[比较报告](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L1-L7） [比较结果](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L9-L34） [总结判断](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L95-L104）

## 研究路线

第二轮 M0.5 于 2026-10-12 完成，保留直接排程 B、工具/策略选择 C、离线规则生成三条候选路线；现有证据不足以在相同条件下决定胜负，也不触发 M1、技术栈选型或工程实施。[第二轮摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L1-L5） [路线判断](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L17-L25） [研究范围声明](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/dossier.md)（原文 L25-L37）

第二轮实际使用 49 个研究会话：45 completed、4 failed。原四次超时仍计入预算；四次补充重试完成不把历史失败改成成功，因此不可表述为“49 次成功”。这也是会话数而非 API 请求数。[会话统计](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L31-L50）

## 仍有效的失败和限制

A24 的长窗口开发运行曾在约 16.15 小时失败；报告确认其候选评价开始前耗尽构造预算，不能据此称 CP 无解。C8 曾因模型通道错误在约 1.77 小时失败；旧失败前缀恢复检查没有证明可继续执行。后续一小时成功不覆盖这些记录。[B 报告中的 A/C 状态](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L59-L67） [SMT README 冻结记录](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/README.md)（原文 L1-L10）

C 的一小时运行缺少 C-fixed（相同工具和预算、固定参数且不调用模型）的消融，因此模型自适应的独立增益未知。C-fixed 是待做验证，不是已经执行的实验。[比较报告](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L57-L60） [后续验证建议](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L84-L96）

批准的内部语义记录指出 433 个初始 lot 的 CQT 历史起点未知、1311 个初始 lot 缺绑定历史；官方行为/数值校准仍与数据完整性审计分开。不能把这些边界当作已解决。[第二轮 dossier](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/dossier.md)（原文 L67-L73） [未决问题](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L49-L57）

M0.5 第二轮交付时（2026-10-12 11:44 UTC）尚未开始 harness 设计或新工厂实验；之后已在会话中提出并讨论方案：B、C 与离线规则共用状态、校验、执行和评价流程，仅替换排程决定生成部分。该方案尚未定稿，未编码，也未获最终批准。[第二轮摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L3-L5） [当前会话：用户提出先讨论方案](../conversations/notes/01a12e07-fae5-70c2-ad30-c126f1f1b178.jsonl#L173) [方案讨论及未改代码](../conversations/notes/01a12e07-fae5-70c2-ad30-c126f1f1b178.jsonl#L176)
