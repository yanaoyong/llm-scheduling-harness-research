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

## Phase B 实现口径

- 账本增量应用与全量投影分离；更新 O(变化记录及成员)，匹配/快照读取依赖当前 WIP。
- 可避免空闲采用确定性贪心极大匹配（非最优）；独立审计复算同一贪心近似，只检查实现偏差，不证明算法最优。
- 用户批准：hold 期间只计 explicit_wait_idle，不触发；与 avoidable_idle 互斥，可相加。
- 未来非就绪工序保留 ready=False；未知资格保守排除，真实物理一致性留 Mac。
- 历史压缩为固定大小证据链摘要；不携带跨会话对话历史。超预算失败关闭。
- 静态机会秒数是公开预测差，不是 v6 反事实轨迹收益。未实施分区/分层。

## Phase C 登记参数与边界

- CycleConfig 显式保存 stage、Δ/H、breakdowns、K_fail=2、stall_cycles=4、
  unknown_usage_cap=2、segment_seconds=3600、segment_cycles=60。
  这些是合成默认值，不是授权真实试验的预算或最优配置。
- 停滞的 idle 分支仅对正空闲计数；零空闲/空周期重置，以免健康空跑被判停滞。
  模型明确说明可重置该分支，但不能免除 K_fail 会话失败阈值。
- 近邻锚点在 begin 时确定合并，submit 的 next_anchor 使用合并后的边界，
  valid_until 下限更保守，避免被跳过的锚点使计划恰在下一真实会话前失效。
- 每周期 Submitter 是事务暂存区；accepted 不等于已经改变物理状态。
  只有 process_ok 且 usage_known 且成功 submit 才采纳。无自动重试。
- 漂移采用事先登记的绝对小时上限 + 连续小时数，不事后推断“恶化”阈值。
  input_per_request 的分母当前为请求下界。预算 cost 单位由登记决定；合成使用输入 token。
- 缓存折算系数、稳态排除小时数必须登记；合成默认 0.1 / 1 小时。
- 恢复依赖宿主在启动每个会话前持久化 in-flight marker；仅保存每段检查点不足以
  知道崩溃时有无正在计费的会话。marker 包含完整当时状态，恢复不重放模型会话。
- 新文件全部为新写，未复制 P 文件，来源清单与 Phase A 哈希不变。

## Phase D 补充

- 冻结输入与输出分目录；每周期 MCP 日志独占新建，提交只暂存；宿主独占 Store。
- 生产来源通过双路参数哈希及重新编译核对；保留字段继承可信旧计划来源。
- JSONL 未知事件/原生动作/压缩/未完成 MCP 调用均失败关闭；配置名称等待 F6 验证。
- 暂无逐请求事件证明，模型请求数采用保守下界；不把工具数当成请求数。
- token 上限是会话累计验收门槛，最后一轮可能超额；不能冒充模型供应商硬预算。
- Mac 物理 trace 每步记录完整公开账本输入；事件增量优化尚未完成，登记为性能限制。
- M6 模板默认空跑、非结果；质量和预算空值阻止实际结果登记。

## Phase E：2×2 因素补齐

- 对应 reviewed plan §二「实验设计」：E1=(event,single_action)，
  P1=(periodic,single_action)，E2=(event,mcp_session)，P2=(periodic,mcp_session)。
  trigger 与 interaction 进入 CycleConfig/checkpoint；登记校验逐组映射，
  并登记 delta_min_seconds。机制允许四组，首轮实际授权范围仍只有 E1/P2。
- event 无锚点。匹配派生的正 avoidable_idle 或允许的越级事件触发；
  reserved_but_earlier_startable 只进指标/快照。失败在下一物理事件再判断，
  不在暂停的模拟时刻重试，K_fail 默认 2。terminal 可以在同一时刻终止。
  非递减空闲和无成功提交的停滞规则跨物理时间推进保持有效。
- event 有效期严格大于 now+delta_min（默认 60）；periodic 保留原下限。
  plan_horizon 防御性缺陷停止仍保留，宿主不得把它当正常决策事件。
- single_action 不允许工具，最后一条 completed agent_message 是唯一提交
  来源。共享 Submitter 校验和 CAS，失败退出不采纳；证据保存原 JSONL 并重编译
  核对 production，可信 base 的继承字段保持原来源。schema 与 MCP 参数同源。
- 两种交互都使用累计 token 与相同缓存权重。单动作每进程 1 请求，MCP
  计保守下界；真实网络重试/请求计数必须通过 Mac 本地 mock 的 F6 检查，
  不能由合成轨迹推出。无 live budget 或质量阈值的新决定。

## Phase F

公开物理夹具使用独立 public_702，不替代封存 mixed_702。默认真实 tokenizer 改为 o200k_base（本次 tiktoken 0.14.0），保持与 v5 一致；字符估算器仍仅用于离线纯函数测试。独立批次审计取每个兼容类排序后的最小批次，复算相同贪心策略；不复用 ledger 实现。

## Phase H：编排者修订，待用户确认

以下为编排者原文；本阶段按任务授权实施验收修订，不冒充用户最终确认。

1. test_mac_sealed_classification: reviewed plan M1(b) says "新口径下这些上下文全部不触发，例外逐条列出" — listed exceptions are allowed. Replace `exceptions == []` with: every exception must (a) have avoidable_idle > 0 confirmed by the independent audit, (b) be caused by an UNRESERVED legal operation that is not one of the old-gap (already reserved) operations, (c) never be triggered by reserved_but_earlier_startable. Then pin the exact observed set: G0 context:97eada3675ec457ca5a28750 and G1 context:61d6652b89614a3aa60bfe1e at t≈1593.13, operation w1703:86:1, machine 325. Keep 10/15/4 old-rule assertion unchanged.
2. test_mac_snapshot_26_pending: the plan's "26/26" conflated base-plan size with pending count. New criterion: all 26 base-plan tasks are accounted for in the snapshot — 23 pending tasks verbatim in the pending table AND the 3 dispatched tasks (ids from execution_state.dispatched_task_ids) visible in the running-jobs / execution section of the snapshot (by task id or by their lot/operation identities). Verify this against the actual snapshot. If the 3 dispatched tasks are NOT visible, that is a real snapshot gap: fix snapshot.py (with a synthetic regression test) so dispatched-but-running plan tasks are represented, then assert.

## Phase I（用户批准）

- 用户批准：hold 期间只计 explicit_wait_idle，不触发。条件 hold 必须已激活；到期无效果。
- MCP 请求下界 = 工具轮次 + 1。轮次是没有 MCP item.completed 插入的最大 MCP
  item.started 序列；并行调用同轮，结果返回后的下一调用另起一轮。零调用为 1；
  顺序 read→validate→submit 为 4；两个并行 read 后 submit 为 3。
- failures 唯一控制连续失败阈值 K_fail；停滞仅由 idle_streak 判定。
- 检查点链从 segment 0 开始，包含前驱 SHA256；latest 校验追加清单和最新一个完整文件，不能从中间片段假冒根。
- audit_ledger 是同一贪心策略的独立实现。小夹具 a 可到 1/2、b/c 只能到 1，
  贪心先把 a 放到 1 得 1，最大匹配把 b 放 1、a 放 2 得 2。

## Phase J

完整检查点仅在初始化、段边界和停止写入，保留最新两个；追加链清单不删除。
恢复中断会话由 in-flight 包保留旧计划并记失败，不重跑该会话；恢复计算不另存完整检查点。
无 in-flight 时从段检查点重放，冲突周期目录保留为 abandoned 证据。
MCP tool_calls 只取 mcp.jsonl 行数；JSONL 轮次独立记录，证据不一致时仍记失败成本。
审计复用 audit_ledger 同一贪心策略的参考实现，不再保留第三份 audit_idle。


## Phase L（2026-10-18，用户批准）

- 只改变快照表示：无损共享工步定义/路线序列、静态机器分组/范围、就绪工序分组/机组族引用、动态一次表头；静态前缀始终在前。所有内容和列表顺序可还原，不改变 submit/task schema。
- 唯一数值归一化：float 保留 10 位有效数字，解码相对误差 ≤1e-9；非浮点精确、int/float 类型保持。无隐式默认、无同值 `=`；缺失字段 `!` 与 None `null` 明确区分。
- 删除重复快照工具；完整快照只作为 prompt 提供。ScriptedRunner 每会话 validate/submit 两次工具调用，请求数下界由 4 变 3。
- 回执违规详情上限 50，额外报告总数、按码计数和 truncated；内部完整验证/接受语义不变。read_entities ids >512 明确拒绝。
- LiveRun 必填 context_token_budget、request_overhead_tokens、output_reserve_tokens；快照 + 系统/工具开销 + 输出/推理预留 ≤ 总上下文预算，超限失败关闭并写出每项。移除旧的仅快照预算参数。
- 无模型调用、网络、提交；配置环境验证沿用 F–K 已授权的公开/封存夹具。真实理解准确率、F6 系统提示/工具开销和生产 reserve 登记仍在 Mac 上完成。
