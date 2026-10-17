# Harness B 用户验收与目标结案

2026年10月16日，用户批准以已授权例外的运行验收结果结束目标，并明确批准 G5 通过。本次最终验收记为 **G5 经用户豁免批准通过**，当前目标按此范围结案。

B 使用 gpt-6-astra 完成仿真 3600 秒和 238 次提交，执行窗口、证据完整性、决定来源、物理与机会检查通过。原 19 个结果、同组 20 个片段及全部成本记录保留。

原始严格审计结论仍为 **未通过**：本次 B 与诊断共 17 次未知用量、10 个控制源码版本，微基准 P95 为 6，超过原门槛 5，实际资源超过最初额度。用户验收批准单独记录，未修改封存审计、失败或成本数据。

本次 B 含五次诊断，已报告 30,737,533 token，模型活动 7小时55分52秒，总墙钟 31小时25分12秒。直接失败和拒绝共 18 次，模型耗时 23分41秒，已知 36,429 token，另有 17 次未知用量。全部历史实验已报告 token 累计 42,783,217；未知费用不按零计算。

此次结案不代表完整工厂语义、算法优势或在线能力获得验收，也不启动新的模型实验。

- [用户验收记录](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/user_acceptance.json>)
- [完整运行验收与成本报告](<__PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/HARNESS_B_3600_ACCEPTANCE_20261016.md>)
- [封存终态及交付凭据](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/terminal_delivery_receipt.json>)
