# 未决问题

1. **C 的模型增益是否存在？** 缺少同工具、同接口、同预算、固定参数且不调用模型的 C-fixed 消融；历史 C 的表现不能直接归因于 LLM。[一小时比较](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L57-L60） [后续条件](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L90-L96）
2. **历史部署能否逐哈希绑定？** 当前源码、包内依赖、compiler、物理依赖与已批准 B 运行的版本关联还缺证据。[未决问题 OQ-02](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L29-L37）
3. **决定归属如何界定？** 生产计划决定与环境虚拟推进、物理就绪等待的职责边界尚需明确。[未决问题 OQ-03](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L39-L47）
4. **CQT 和初始状态缺口如何补齐？** 433 个 lot 的 CQT 历史起点未知，1311 个缺绑定历史；需要判明哪些约束未建模、哪些无法判定。[未决问题 OQ-04](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L49-L57）
5. **完整失败分母是什么？** 解析失败、原始非法、检查拒绝、修复后可行及最终提交需区分；只统计成功输出会偏置质量判断。[未决问题 OQ-05](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L59-L67）
6. **失败恢复边界是什么？** A24/C8 失败保留；特定 V15 恢复不能外推成任意中断点均可安全续跑。[未决问题 OQ-06](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L69-L77）
7. **目标是否为在线调度？** 需要先确定仿真暂停决策质量还是模型思考期间工厂继续运行，以及相应响应期限。[未决问题 OQ-07](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L79-L87）
8. **三路线怎样公平比较？** 需同物理语义、初态、观察、候选处理、目标、模型快照和预算，使用持出重复证据，并报告合法率、失败质量与成本。[第二轮摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L21-L25）
9. **全厂正式研究何时成立？** 三数据集 SMT 的 2/913 台控制验收不能外推到全厂控制；全厂 B 一小时开发成功也不替代公平长窗比较、官方数值校准或真实工厂上线证据。[实验范围](../source_snapshot/experiment_round2_3datasets/README.md)（原文 L28-L36） [B 边界](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L7-L11）
10. **Harness 是否进入设计？** 当前研究明确未开始 harness 设计或实施；未接入运行的 prompt 草案不作为协议依据。M1 列项只是需求讨论移交，不是批准或启动。[第二轮摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L3-L5） [未决问题说明](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md)（原文 L15-L18）
