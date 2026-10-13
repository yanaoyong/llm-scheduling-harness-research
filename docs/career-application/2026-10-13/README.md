# 从制造排产经验到 AI Agent 落地

鄢澳勇 · 我的职业实践与智能排程工作思路 · 2026-10-13

这份报告面向面试交流：从我的制造排产、企业知识应用和个人 Harness 实践出发，说明我理解的大模型应用工程师应怎样同时推进 Agent 的运行工程、现场规则共建和使用者培训，并以正在进行的智能排程试验作为讨论依据。

## 阅读与下载

- [PDF 阅读版（7 页）](career-scheduling-agent-report.pdf)
- [Word 可编辑版](career-scheduling-agent-report.docx)
- [归档版本与文件校验值](manifest.json)

PDF 与 Word 均保存本次报告的原始交付字节。后续内容修订应另建带日期的版本，保留这份历史快照。

## 后续写作素材

2026-10-13 补充了 [四项面试素材](../INTERVIEW_MATERIALS.md)、[写作框架](../INTERVIEW_OUTLINE.md)及 [23 项来源摘录](../evidence/2026-10-13/source-excerpts.md)。这些材料进一步区分本人要求、Codex 实现与未确认细节；未改动本页归档 PDF／Word。跨电脑继续工作请先读 [Claude Code 续作入口](../CONTINUE_WITH_CLAUDE.md)。

## 阅读顺序

| 页码 | 内容 |
|---|---|
| 1 | 我理解的大模型应用工程师：运行工程与现场协作环境两条主线 |
| 2 | 已有职业经验、实际承担的工作，以及如何连接到排程 Agent |
| 3 | 通用 Agent 协作、排程运行协议、失败恢复与调用成本带来的工程问题 |
| 4 | 上下文、任务交接、工具、状态恢复和评价怎样纳入 Harness |
| 5 | 与现场工程师共同排产，整理规则、例外和可维护案例 |
| 6 | 培训使用者提出任务、管理上下文、核对结果、纠偏与交接 |
| 7 | 分阶段推进方式，以及现有工作资料的阅读入口 |

## 当前状态与进一步查阅

排程项目仍在推进。报告中的短窗口成功不代表完整正式对照完成，也不代表已在真实工厂取得生产收益；现场规则共建、排程人员培训和专用 Harness 建设属于下一步工作思路。

- [项目当前状态](../../PROJECT_STATE.md)
- [B 一小时开发试验的效率与成本复盘](../../../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md)
- [全厂排程开发报告](../../../source_snapshot/experiment_round2_3datasets/docs/smt_fullfab/REPORT_zh.md)
- [Harness 路线调研与未决问题](../../../source_snapshot/research_harness_scheduling_20261012_round2/m0.5_research/)

本次归档新增报告及阅读说明，不扩展 2026-10-12 原始实验与会话快照的范围。职业经历的原始私人材料和本地制作过程文件不包含在本报告归档中。
