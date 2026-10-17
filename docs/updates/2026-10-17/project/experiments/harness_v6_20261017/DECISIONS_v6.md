# v6 决定登记

依据：审查方案第二部分、长时间运行补充第一/五节、COMMON 最终批准项。

1. 原子 `submit_plan` 取代 propose + confirm；`validate_plan` 负责校验，无 dry_run。
2. 周期重排，默认 Δ=60s、H=max(3Δ,900s)，S0..S4 每阶段可配置。
   提交要求 valid_until ≥ next_anchor + Δ；空周期零模型调用。H 是前瞻/建议跨度。
3. 过去 not_before 表示下界已满足，保留原值；过期 hold 无效果，无需显式取消。
   已失效冻结任务允许显式取消，其余冻结字节与前缀保护不变。
4. when_ready 为必做且默认模式；not_before 为两种 start_mode 下的可选硬下界。
   全部生产任务、批次、机组及队列顺序由模型决定；程序不补排、不改派、不改写。
5. 会话失败保留旧计划并推进到下一锚点。K_fail=2（可配置、登记为实验变量），
   连续失败达阈值停止；崩溃前写入 submission.json 不采纳。覆盖方案早期的可采纳建议。
6. 主要成本：未缓存等价输入 token + 请求数，按模拟小时报告，失败成本与未知用量保留。
7. 越级仅 plan_invalidated、expired_task(latest_start)、no_plan（无有效计划且可避免空闲）、terminal。
   breakdown 开关：短窗口关闭、长运行打开；受影响任务失效后走 plan_invalidated。
   无紧急批次事件；CQT/Q-time 未实现，明确列为长运行质量限制。
8. reserved_but_earlier_startable 只入快照和指标，不触发；覆盖不足只报告，不拒绝。
9. 初轮 E1/P2 各三条轨迹，本阶段不运行；预算另定。数据、vendor、tokenizer、SQLite
   证据及真实物理验收均在 Mac。本仓库仅纯函数和合成夹具。
10. 任意时长后续阶段加入检查点、按段日志和预算闸门，按 S0..S4 单独批准预算。

Phase A 接口选择：省略 start_mode 的默认仅在读取时解释，不写入 JSON。
冻结无 not_before 任务按 base.created_at 判断；失效收据由 execution_state 提供并绑定锚点。
纯校验不证明私有物理可行性；Phase D 仍须 commit_plan 预检和独立审计。
