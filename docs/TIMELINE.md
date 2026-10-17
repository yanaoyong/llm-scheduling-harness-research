# 项目时间线

> 2026-10-17 更新：后续会话、Harness 验收与窗口实验见 [增量归档](updates/2026-10-17/README.md)。下文继续保留原历史快照及其日期。

| 日期 / 截止 | 事件 | 状态与证据边界 |
|---|---|---|
| 2026-10-08 | 首轮实验阶段记录与来源审计日期 | 首轮数据/代码语义审计标注审计日期为 2026-10-08；该日期作为首轮实验阶段的已证时间锚点，不外推具体开跑时刻。 [来源审计](../source_snapshot/experiment_round1/docs/source-audit.md)（原文 L1-L5） [首轮实验 README](../source_snapshot/experiment_round1/README.md)（原文 L1-L8） |
| 2026-10-09 07:13:34 UTC | 三数据集最终验收检查 | `artifacts/final/acceptance.json` 记录 `checked_at`、状态 passed、验收就绪；原记录有 1 个静态核心失败，恢复后 108/108 逻辑格点交付。此为验收检查时间；不能据此推断每条底层实验的执行日期。 [验收记录](../source_snapshot/experiment_round2_3datasets/artifacts/final/acceptance.json)（原文 L3-L5） [交付范围摘要](../source_snapshot/experiment_round2_3datasets/README.md)（原文 L1-L5） |
| 2026-10-10 04:19:39 UTC（12:19:39 北京时间） | SMT 全厂 A/B/C 续作 README 的冻结证据截面 | 当时正式运行 0 条，B 一小时尚未通过；A24 与 C8 失败，B v4 仍在运行。该 README 明确不自动追赶后续文件变化，故不能用它否定 10 月 12 日后来完成的 B 一小时验收。 [冻结 README](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/README.md)（原文 L1-L10） |
| 2026-10-11 07:18—07:29 UTC | B 一小时执行停止并交接恢复修复 | 收到停止/交接指令后，在安全边界停止，保留草稿、检查点和账本；仿真停在 803.25 秒，后续修复与运行交新会话。 [会话记录：停止与交接](../conversations/transcripts/01a11fc6-3c70-7380-aadd-4a88dbd97d58.md)（原 rollout L34107） [停止完成](../conversations/transcripts/01a11fc6-3c70-7380-aadd-4a88dbd97d58.md)（原 rollout L34254） |
| 2026-10-12 03:13 UTC 起 | 首轮 harness 工程机制调研会话 | 会话开始梳理调研范围与研究问题。 [会话记录](../conversations/transcripts/01a12e07-fae5-70c2-ad30-c126f1f1b178.md)（原 rollout L106） |
| 2026-10-12 05:26:06 UTC | 首轮排程 harness 主题 M0.5 交付 | completion 记录状态 complete；交付报告指出仍不足以锁定技术栈或证明本厂收益。 [完成记录](../source_snapshot/research_harness_scheduling_20261012/m0.5_research/evidence/completion.json) [摘要](../source_snapshot/research_harness_scheduling_20261012/m0.5_research/summary.md)（原文 L1-L13） |
| 2026-10-12 11:44:19 UTC | 第二轮 M0.5 调研完成 | completion 记录状态 APPROVED；研究保留 B、C、离线规则生成三路线，交付时未启动 harness 设计或新工厂实验。 [摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L1-L5） [完成记录](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/evidence/completion.json) |
| 2026-10-12 | B 一小时根验收与 A/B/C 描述性复算 | B 报告记载场景 1701 的 0—3600 秒开发窗口完成，责任范围 913 台；A/B/C 比较针对已保存运行，执行版本存在差异，不能作因果或普遍胜负结论。 [B 报告](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)（原文 L1-L15） [比较报告](../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md)（原文 L1-L8） |
| 2026-10-12 12:14 UTC 起 | harness 方案讨论 | 用户提出先讨论决策与机械职责、能力复用及 B/C/离线规则公平比较，暂不写代码；之后形成讨论稿，尚未定稿、编码或最终批准。 [用户指示](../conversations/transcripts/01a12e07-fae5-70c2-ad30-c126f1f1b178.md)（原 rollout L3918） [讨论稿](../conversations/transcripts/01a12e07-fae5-70c2-ad30-c126f1f1b178.md)（原 rollout L3969） |
| 2026-10-12 | 第二轮研究会话结账 | 共 49 个额外会话，45 completed、4 failed；4 次原超时保留在分母。 [摘要](../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/summary.md)（原文 L31-L50） |


> 行号说明：上面 transcript 链接定位到规范可读导出；括号中的 `原 rollout L...` 是 source_line（原始 JSONL 行号）。早期 notes 导出的物理行号只是摘录序号，不可与 source_line 混用。
