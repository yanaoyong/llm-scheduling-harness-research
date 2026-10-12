# 最终独立预算与成本审计

结论：通过本次预算与成本核对。不代替主 Agent 的最终交付签署。

独立按账本事件顺序重建 1220 行，602 个唯一 reservation 与 602 个 finish；错误 0 项。审计脚本不导入运行器、BudgetLedger 或求解器，不发起模型/solver/仿真，不重跑全轨迹。

| 范围 | 运行数 | 模型外层请求 | solver 预留秒 | 活动执行墙秒 |
|---|---:|---:|---:|---:|
| 原正式矩阵（含原失败） | 180 | 239 | 3149.900000 | 11675.620527 |
| 独立恢复补充 | 1 | 1 | 0.000000 | 248.222571 |
| 正式合计 | 181 | 240 | 3149.900000 | 11923.843097 |

正式已知 input+output 为 1,907,787 token；未知用量完成请求 1 个，真实总 token 仍未知，不能称为精确总量。缓存输入、reasoning 输出不重复累加。费用字段全部 null，不把未知账单计为 $0。

开发账本独立记录：23 个模型请求、已知 input+output 183,947、未知完成请求 2 个、solver 预留 446.200000 秒。开发资源不混入正式 181 条成本；独立审查 solver 的开发 reservation 也保留。

## 核对方式

逐行检查 grant 先于请求、ID 唯一、finish 唯一、phase/prefix/resource 相符；用此前已完成 usage 重新计算每个模型请求准入时的调用数、input+output 阈值、未知用量计数及 pending；与每份 token_admission 比对。每次 solver 预留检查单 grant 与共享 phase 的累计上限，失败不退还预算。

正式 300 请求、300 万已报告 token、未知完成 3 次停止、4500 solver 预留秒和14400累计活动墙秒按冻结协议核查；授予各子预算的 max_calls 可以相加超过全局上限，但每个请求仍必须通过同一全局准入。恢复未重置账本或预算。

模型逐次比对 request/result、原始 turn.completed usage、ledger finish、运行聚合；solver 逐次比对 reservation、finish 和已保存候选。A/F 计数从账本与 solver.json/fixed_portfolio.json重建，内部solver秒与含建模wall秒分别核查，未混作同一指标。181条根记录与全部formal账本请求双向关联，无遗漏或重复归属。

按 started_at 排序重建每条运行准入前已完成活动耗时并核查串行；原通道失败仍在原180条，恢复只额外增加自身活动时间。logical_costs用于关联检查，不再次计入正式总和；恢复同时核查325秒准入余量、逻辑请求≤3、逻辑活动≤1000秒。

## 边界及保留缺口

- 11 legacy development model reserves omit token_admission; reconstructed checks pass/fail independently below, original records unchanged.
- 72 original static A/F records omit solver_calls; count reconstructed from the uniquely linked ledger and solver artifacts, original results unchanged.
- No new full trace, feasibility, Git, or model-isolation replay: saved independent audits are read and hash-recorded.
- The ledger counts outer CLI requests, not unobservable service-side HTTP requests/retries; collaboration-agent costs are unavailable.
- Input/output totals are known reported partial sums; missing usage is not zero. Cached input and reasoning output are subsets, not added again.
- Token admission is an observed-completed-usage threshold, not a hard server-side token cap; one in-flight request can overshoot.
- Solver reserved seconds, internal solve seconds, solver wall seconds, and run activity seconds are different quantities.
- Campaign wall budget is the sum of active run end-to-end durations, including original failed attempts and recovery, excluding idle waiting gaps and offline review.
- Early development calls lack stored token-admission snapshots; their historical prefix is reconstructed, not a claim that later code existed then.
- Ledger hash and event ordering certify the inspected snapshot internally; they are not an external signed billing/time-attestation service.
- Development ledger resources include independent solver review; earlier unledgered non-model SMT pilots/test CPU remain in artifacts/smt_development usage records, not this formal-request ledger.

## 复现与证据

运行 `.venv/bin/python scripts/final_budget_review.py`，只覆盖本审计的 JSON/Markdown 产物。

详细逐请求/逐运行准入、每项检查、输入哈希、未知 call ID 和全部成本见 `artifacts/final/qa/budget_audit.json`。核心原始证据为 `progress/model_ledger.jsonl`、四份 `configs/freezes/*.json`、恢复冻结与manifest、各原始run/model/solver文件及已保存离线audit。

本次离线核对 CPU 8.306490 秒，新增模型/solver/仿真均为0。
