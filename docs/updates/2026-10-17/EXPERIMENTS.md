# 实验沿革与结论

日期均为北京时间。历史报告按当时结论保留，下面说明它们之间的关系，不能把不同语义、窗口或成本范围的数字直接拼在一起。

## 10 月 12—16 日：完整 B 与统一 Harness

旧 B 开发流程完成 0→3600 秒，并留下完整续作沿革。10 月 13 日之后开展统一 Harness 的公共接口、持久化、恢复、成本与验收工作；10 月 16 日 Harness B 完成同一小时开发窗口。

Harness B 业务为 784 次模型尝试、238 次提交、已知 30,720,365 tokens，16 次通道失败用量未知。加五次历史诊断为 789 次、已知 30,737,533 tokens、17 次未知用量。全部 Harness 历史累计 1,141 次、已知 42,783,217 tokens、42 次未知用量；这不是整个项目的助手开发成本。

机器严格 G5 保持未通过。用户另行批准“G5 经用户豁免通过并结案”，没有把严格审计改写成通过。完整工厂语义、在线时钟下的接续能力和算法质量优势均未获证明。

历史比较显示，旧 B 完整沿革 1,362 次调用，Harness B 业务 784 次，记录上少 42.4%；但真实提交数由 95 增到 238，总耗时记录更长。它们的控制版本、协议、恢复和计时不同，这个差异不是严格因果降本率。

- [完整 B 验收与成本](project/experiment_round2_3datasets/docs/smt_fullfab/HARNESS_B_3600_ACCEPTANCE_20261016.md)
- [用户验收与严格审计的区别](project/experiment_round2_3datasets/docs/smt_fullfab/HARNESS_B_USER_ACCEPTANCE_20261016.md)
- [Harness 与旧 B 的同指标重算](project/experiment_round2_3datasets/docs/smt_fullfab/HARNESS_VS_LEGACY_B_COMPARISON_20261016.md)

## 10 月 15—16 日：频繁重排的归因

保存了规划诊断、覆盖消融、上下文 2×2、逐次重排归因与第 136 轮只读分析。baseline 的 2403→2703 秒窗口有 24 次需求触发：7 次已就绪任务等设备释放，4 次已知后继变为就绪，13 次涉及抽样保留或跳步。

11 次是提前覆盖的候选，不能直接声称能省 11 次模型调用。基线触发点没有剩余未执行队列，未发现丢任务；但另一个轨迹的旧任务被反复改写最早开工时间。目录可查也不等于相关字段已进入模型输入。

- [24 次重排逐次归因](project/analysis/B_replan_attribution_20261016/24次重排逐次归因.txt)
- [提前接续与队列维护证据](project/analysis/B_replan_attribution_20261016/queue_witness.json)
- 完整消融与 2×2 运行材料在公开增量证据包 `project/analysis/`；含模型调用、失败和冻结副本。

## 10 月 16—17 日：窗口与汇总机制实验

所有修改在 `experiments/context_window_batch60_20261016` 独立副本中完成；原 B 不动。最初固定 60 秒汇总，后改成有限输入预算下的动态汇总；再区分初次装不下的分批处理与接续时保留已提交计划。覆盖记录不替模型生成生产任务。

| 阶段 | 保存目录 | 已验证内容与限制 |
|---|---|---|
| 初始容量试验与 CLI 修复 | `paired_20261016`、`paired_20261016_cli_fix` | 早期实际输出和失败原样保留，不以修复后的结果覆盖 |
| 初次/接续两种策略 | `two_strategy_20261016` | 共同 702→768 秒，G1/G2 所需调用 6/4；全部实际 8/6，含 G2 一次未知用量失败，未到目标 882 秒 |
| 预测合并与重点资料优先 | `forecast_collection_20261017` | 共同 702→882 秒，G1/G2 调用 5/2；短窗口内不能证明长期收益 |
| 立即补排、提醒截止与扩大提前收集 | `deadline_three_group_20261017` | 加入 G0 原规则对照，三组 702→882 秒均为 4 次调用、11 次生产开工 |
| 延长观察 | `extended_three_group_*` | 继承前三组轨迹，最终共同到 1603.10 秒；分段、重试、用量未知、离线准备失败均保留 |

这些阶段分别改变了触发和执行规则，不能当作只调整上下文长度的同一实验重复。每个阶段内部才按其登记配置比较窗口效果。

最新离线验证为 170 项通过、0 次模型调用。2000 条合成初次需求的资料分批为 G1 三批、G2 两批；这是装包验证，不是 2000 台真实机组的生产仿真，也不是实测模型调用次数。

- [副本设计、配置和历次结果](project/experiments/context_window_batch60_20261016/README.md)
- [最新离线验证](project/experiments/context_window_batch60_20261016/reports/deadline_validation_20261017.md)
- [两种策略实际报告](project/experiments/context_window_batch60_20261016/live_pilots/two_strategy_20261016/结果说明.md)
- [预测合并实际报告](project/experiments/context_window_batch60_20261016/live_pilots/forecast_collection_20261017/结果说明.md)
- [三组短区间报告](project/experiments/context_window_batch60_20261016/live_pilots/deadline_three_group_20261017/结果说明.md)
- [延长观察最终报告](project/experiments/context_window_batch60_20261016/live_pilots/extended_three_group_deadline_completion_20261017/结果说明.md)

最终延长试验中，G2 最大单次已知服务端输入 436,460 tokens，扩容确实被使用；但少查资料被更多提案/提交抵消。已排任务能继续执行，仍有全厂分配状态与逐机缺计划检查不一致、过去最早开工时间要求改写等问题。共同终点每组还各有 1 项物理可加工但未分配的工序，不能用程序统计的零缺计划等待声称零遗漏。

模拟在模型响应期间暂停。所有等待与产出只反映这一开发仿真语义，不能证明真实生产线不会等模型。
