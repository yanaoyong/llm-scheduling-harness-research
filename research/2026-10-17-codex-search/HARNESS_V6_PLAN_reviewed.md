# Harness v6 开发方案（审查修订版，2026-10-17）

本文件是对 `HARNESS_V6_PLAN_draft.md` 的审查与修订。审查只读了代码与归档证据，没有调用模型或 codex，也没有运行实验脚本或访问网络。唯一执行的是纯函数单元测试 `tests/test_smt_fullfab_plan_delta.py`（29 项通过），另做了一次导入检查。

路径缩写：
- `P` = `docs/updates/2026-10-17/project/experiments/context_window_batch60_20261016`
- `S` = `P/src/smt_fullfab`
- `H` = `S/harness`

---

## 一、审查发现（按严重程度排序）

### 严重（会让方案做不成，或让结论失效）

**F1. “周期化”的根因判断错了：改 `max_ready_wait_seconds` 不会改变触发行为。**
- v5 的 G1/G2 走 `DEADLINE_POLICY` 分支。它的判定第一句就是 `if gaps:reason='uncovered_demand'`（`H/deadline_collection.py:36`），根本不读 `max_ready_wait_seconds`；只有旧 v4 的 `decision` 才读它（`H/batch_window.py:110`）。
- G0 用 `execution_rule='original'`，直接走 `environment.advance_plan` 的原始循环：只要 `_gaps()` 非空就停（`S/environment.py:273-277`）。它不经过 batch_window（`S/environment.py:260-262`）。
- 所以“v5 配置 `max_ready_wait_seconds=0` 导致立即触发”只描述了配置值，没有说到机制。真正要换掉的是两处停机条件：`environment.py:273-277` 和 `deadline_collection.py:36`。v5 另外三类触发也要明确去留：`plan_runway`（预测截止，提前 135 秒，`H/capacity_config.py:117`）、`plan_renewal`、`capacity_limit`。最终报告中 G1/G2 的 `plan_runway` 各有 2/3 次。
- 现有代码其实已有一套锚点机制：`runtime.advance` 按 `anchor + k·period_seconds` 计算边界（`H/runtime.py:682`），G0 也走这条路。只是 `_gaps` 会更早打断它。v6 应复用这段逻辑，不必另写一套锚点。

**F2. “规范化 `not_before`”漏了三处同口径检查，并且草案提出的公式本身不对。**
- 过去开工时间的拒绝发生在四处：`S/plan_delta.py:227`（草案写的 :225 是另一条“`not_before < valid_until`”检查）、`S/environment.py:132`、独立审计 `S/audit.py:103`，以及提示词 `H/transport.py:147-149`（明确告诉模型 “not_before is never clamped”）。现有测试 `tests/test_smt_fullfab_plan_delta.py:86` 断言必须拒绝。草案的验收写“硬约束测试结果不变”，但这条测试本来就必须反转，二者矛盾。
- 过期 hold 是同类问题，草案完全没提：`plan_delta.py:250`、`environment.py:158`、`audit.py:136` 都要求 `until > now`，过期的 hold 必须由模型显式取消。
- 草案公式 `max(now, 到料, 机器可用)` 有两个问题：
  - 到料时间和机器释放时间是随机的未来事件，规划时不可知（`src/smt/environment.py:25-30` 按事件键抽样）。执行器本来就会等料和等机（`environment.py:214-221`），改写字段等于程序替模型猜时间。
  - 改写已有任务的 JSON 会破坏冻结任务的逐字节比较（`plan_delta.py:200`、`:226`，`environment.py:167`）。
- 正确做法是语义修正，不改写字段：
  - 过去的 `not_before` 按“下界已满足”接受，原值保留。
  - 过期 hold 视为无效果，可保留也可不处理，不再要求模型显式取消。
  - 上面四处检查和提示词同步修改。

**F3. 精简包“只引入 environment、plan_delta、facts、store、部分 evaluation”在本仓库无法运行，在 Mac 上也不能直接复制。**
- `environment.py` 顶层依赖 `src.smt.environment`（`S/environment.py:18`）。后者在导入时要求 `vendor/PySCFabSim-revised/simulation` 和 `data/smt/SMT2020_LVHM`（`src/smt/environment.py:12-17, 37-38`）。本仓库两者都没有。实测 `import src.smt_fullfab.environment` 报 `ModuleNotFoundError: read`。
- `environment.py` 还有延迟依赖：`observation.py`（`problem()`，:348-351），以及 `harness.batch_window`（`configure_batching` :94-96、`advance_plan` :260-262）。按完整静态闭包算，batch_window 会再带进 36 个模块（capacity_prompt、transport、recovery 等）。复制时必须删掉这两个分支，不能整文件照搬。
- 快照兼容性：`from_snapshot` 校验 `snapshot_dependencies()`。这个指纹包含 `environment.py` 和 `observation.py` 的相对路径与哈希（`environment.py:37-41, 317-318`），文件一旦移动或修改，旧快照就加载不了。只有 harness 自己的 `factory.restore(state, trace)` 路径（`H/factory.py:22-42`）不校验实现指纹，可以用来读入 mixed_702 的存储状态。但它会恢复 `batch_state`，并依赖 `stream_snapshot._state_view`（`H/factory.py:8`），也要一起带走或改写。
- `store.py` 顶层只依赖 `contracts`。但它的 `offline_isolation.local_path` 要求路径必须在 `ROOT` 之内（`H/offline_isolation.py:6-15`）；`ROOT` 由 `parents[3]` 推出，`contracts.fingerprint` 也绑定 ROOT 下的 `src/`、`vendor/`、`data/`、`requirements.lock`（`H/contracts.py:12, 101-121`）。换位置后这两处都要重写。
- 评估：`evaluation.audit_physical_prefix` 依赖 `src.smt.audit` 和数据目录（`H/evaluation.py:405-419`）；`audit_provenance` 和 `raw_delta` 假定计划来自模型最终输出（`H/evaluation.py:109-141`）。改用 MCP 后，这条证据链必须重写（见 F7）。
- 结论：本仓库只能开发和测试纯函数部分，包括 plan_delta、facts、ledger、normalize、cycle 状态机、submit、MCP 服务器，全部配合合成夹具。凡是需要真实物理（environment、observation、物理审计、轨迹回放）的工作都只能在 Mac 上做。

**F4. 拿“封存轨迹的模型决策”去回放新触发机制，只在第一个分歧点之前有效。**
- 封存提交绑定了 `context_ref`、`state_revision` 和四个锚点哈希（`H/runtime.py:373-378, 536-537`，`plan_delta.py:128-129`）。触发时刻一旦改变，后续状态就不同，旧决策既不能合法提交，在反事实上也不成立。
- 因此“回放统计”只能做两件事，草案的 replay.py 需要缩小范围：
  - 对每个封存上下文做静态反事实分类：新口径在这个时刻会不会触发。
  - 按顺序重放已提交的计划，验证新实现与旧物理逐事件一致（等价性测试）。
- 用它估算 v6 的周期数或调用数没有依据。

**F5. 只看“账本未覆盖就绪工序”会让几乎每个锚点都触发，同时可能丢掉质量。**
- 共同终点时，未排的非条件工序有 1,005/997/1,006 项（最终报告表）。它们大多在等忙碌的机组。如果把“`uncovered_ready` 非空”当作周期内是否调用模型的条件，几乎每个锚点都会调用。
- 应改用基于匹配的**可避免空闲**作为调用门槛：一台机组空闲、可用，又存在满足 batch_min/max、组批键、专用和 min-run 约束的未预留可开工批次。未覆盖工序只作为指标。
- w1462 案例的反面：1092 秒时，该工序已排给 1299 号机组，`not_before`=1289.27 秒；1161.81 秒实际就绪。旧口径的“误触发”让模型把它移到 1295 号机组提前开工（`already_planned_replan_case.json`）。新口径扣除已预留工序后不再触发，这台机组会多等约 128 秒。要分清两类情况：“已预留、但另有空闲机组可以更早开工”应作为机会写进下一周期快照，不作为触发条件；这类机会损失也要计入质量指标。
- 两个案例的根源相同：`not_before` 同时承担了“预测开工时间”和“硬性下界”两种含义（RESUME 第 2 条）。见修订方案中的 normalize 一节。

**F6. MCP 方案与现有传输层的失败判定直接冲突；codex 的若干能力只是假设，没有核实。**
- 现有命令显式关闭 MCP（`mcp_servers={}`，`H/transport.py:399`），并强制 `--output-schema`（`:424-427`）。
- 判定规则：只要事件里出现 `agent_message/reasoning/error` 以外的 item，就算 `native_tool_events`（`S/model_transport.py:144-147`）。这时 `channel_valid=False` 并停机（`H/transport.py:548-555`）。MCP 工具调用必然命中这条规则，所以要白名单 MCP 调用类 item，同时继续拒绝命令执行、文件修改、联网等原生动作。
- `validate_config` 要求超时不超过 600 秒，失败策略只能是 `fallback="none"`（`H/contracts.py:151, 173`）。草案的“失败时保留旧计划并继续”属于新的失败语义，是一个实验变量，必须登记。
- 调用计数口径会变：G0 的 56 次“调用”每次是 1 个 exec、1 次模型请求、带完整约 21 万 token 输入（G0 推进到共同终点为 11,778,322 token / 56 ≈ 21 万）。一个 MCP 会话内部有多次模型请求，每次重发不断增长的上下文。`--json` 只在 `turn.completed` 汇报整轮累计用量（`model_transport.py:127-142`），不给逐请求计数。“周期数下降”不等于“请求数下降”，更不等于“token 下降”。
- 以下能力都必须在 Mac 上验证；草案和检索汇总都没有证据：
  - `--ignore-user-config` 下用 `-c mcp_servers.<n>.command/args/env` 注入 MCP 服务器。
  - `approval_policy=never` 下 MCP 调用会被放行还是被取消。
  - `--output-schema` 与 MCP 工具能否同时使用。
  - JSONL 里 MCP item 的类型名和参数字段。
  - MCP 服务器的启动和调用超时（`startup_timeout_sec`/`tool_timeout_sec`）。
  - 会话内自动压缩（`model_auto_compact_token_limit` 当前设为窗口的 90%）是否会悄悄丢弃早期工具结果，以及是否有对应事件。
  - `shell_environment_policy.inherit="none"` 与 MCP 子进程环境变量的关系。
  - 大型工具结果会不会被截断。

**F7. 状态唯一写者、提交原子性和审计证据链在 MCP 架构下没有设计。**
- `Store` 用 `flock` 独占写锁（`H/store.py:42-46`）。MCP 服务器是 codex 启动的子进程，不能直接写同一个 Store；harness 的离线守卫还禁止套接字和子进程（`H/offline_isolation.py:36-52`）。
- 现有审计把每个生产字段追溯到模型原始输出（`H/evaluation.py:109-141`，`runtime.field_sources`）。MCP 下，计划存在于工具调用参数里，需要两路来源互相核对：MCP 服务器日志和 codex JSONL 事件。
- 会话在“submit 已被接受”与“进程正常退出”之间崩溃时，提交算不算数，草案没有定义。

### 重要（不改会导致归因错误、验收无法验证或行为异常）

**F8. 实验归因：v6 相对 G0 同时改了 6 个因素，草案没有对照设计。** 六个因素是：触发、账本口径、时间语义、快照、提交协议、会话方式，再加上失败语义。G0 本身又只有一条封存轨迹。修订方案给出分阶段 2×2：先把程序缺陷修正作为所有新组的共同底座，再对“触发方式 × 交互方式”做消融；原子提交通过记账归因。

**F9. 草案对“输入只展示 14–15/26 项任务”的根因定位不准。** 原因不是历史截断，而是任务表只保留与本次所选工序相关机组上的任务（`H/capacity_prompt.py:157-162`），所以 `execution_state.complete=False`（:198）。草案引用的 `capacity_prompt.py:280-344` 是另一个问题：历史只完整保留最近一条结果，更早的条目在 10% 预算内只保留引用（:299, :322-327）。两者都要修，但修法不同。

**F10. 草案没有估计 Δ/H 与工序时长的关系，`valid_until` 和冻结语义也有冲突。**
- 工序时长：归档 JSON 中 375 条 `processing_seconds` 最小约 580 秒，中位约 1,700 秒，P90 约 3,576 秒；280 条 `occupation_seconds` 中位约 1,700 秒。H=300 秒比几乎所有工序都短，按文献“计划覆盖 H”的含义，它实际只够每台机组排“下一项”。
- 执行器对 `not_before` 只要求“小于 valid_until”（`plan_delta.py:225`、`environment.py:132`），忙碌机组的后续任务可以写成 `not_before=now` 排队。所以 H 在实现上只是计划到期时间，不限制前瞻深度。
- 计划到期会强制停机（`environment.py:266-268`，`batch_window.py:142-144`）。如果 `valid_until` 小于“下一个实际执行的周期”，被跳过的锚点会因为到期重新变成触发。因此 `valid_until ≥ 下一锚点 + Δ` 必须是提交约束，H 要和 `problem(plan_seconds=14400)` 的前瞻参数（`H/contracts.py:126`）区分开。
- 冻结有一个既有缺陷：已冻结但被判失效的任务无法删除（`environment.py:164-168`、`plan_delta.py:199-200` 都要求原样保留）。保留下来的任务一推进又会立即失效（`environment.py:197-204`），结果是零进展停机。现有轨迹基本不用冻结，所以没暴露；周期化后如果用冻结来稳定计划，就会碰到。

**F11. 越级事件定义不完整，部分事件不可观测。**
- 草案的“设备故障”：故障只产生 downtime 事件，排在故障机组上的任务会继续等待，不一定失效。在模拟暂停的语义下，提前处理最多省 Δ 秒的空闲。
- “紧急批次”：投料由 `order.txt` 预先确定，优先级字段 `PRIOR` 只有 10/20/30（`src/smt/environment.py:107`），代码里没有“紧急到达”事件。
- 草案引用的 Q-time 越级做不到：CQT 未实现（`H/contracts.py:37-39`）。
- 草案漏掉的停机原因：`expired_task`（`latest_start`，`environment.py:211-213`）、`plan_horizon`、`no_plan`、`terminal`。
- 零进展保护失效：现有判定是“`t` 没有推进”（`H/runtime.py:700-708`），周期化后时间每次都会推进到锚点，这条保护永远不会触发。需要新的停滞判定。

**F12. 验收数字有的站不住，有的在本仓库无法验证。**
- “10/15/4”是最终报告里“新增区间内触发机组仅看到已排工序的缺计划提醒”的次数，由 `P/scripts/analyze_extended_pilot.py:79-95` 从封存上下文算出。它可以作为旧口径的复现检查，但不是新机制的验收；新机制应检查这些上下文在新口径下全部不触发，并逐条列出例外。本仓库没有封存的 SQLite 证据库，只能在 Mac 上做。
- “9–11 个周期”：我用最终报告中的触发时刻复算，Δ=60、锚点 882/900 时，含触发的 60 秒桶分别是 G0 9、G1 10–11、G2 10 个（Δ=180 为 4–5，Δ=300 为 3）。这个数字的前提是轨迹不变、空周期跳过、每周期 1 个会话；它不是请求数。如果每个会话 4–6 次请求，总请求可能是 40–66 次，未必少于 56。因此不能用作验收标准。
- w1942:15:1 在最终报告里没有展开，草案没给证据位置，需要在 Mac 上从证据库补出处。
- “5 seed × 3 轨迹”：现有试验全部从同一个 mixed_702 保存状态出发，换工厂 seed 就需要新的起始状态，也就需要预热策略，这件事尚未决定。按每组每周期数次请求估算，规模在一千次请求量级，远超以往每组 96 次的上限，需要用户批准。

### 一般（建议简化或补充）

**F13. 随机数和共同随机数。** 草案没有说明现有机制，下面是现状：
- 随机数已按事件键用 SHA256 生成（`src/smt/environment.py:25-30`），抽样跳步、返工、停机日历都只与批次/工序/访问次数或日历序号有关（:133, :153, :167），天然是共同随机数。
- 加工时长的键是“本批所有批次的有序集合”（:214-215），组批一变时长就变（最终报告“限制”一节已说明）。
- 模型本身的随机性无法设种子，这是轨迹间差异的唯一来源。不需要新做“随机数流”模块，只需在登记中写明。

**F14. 过度设计。**
- `submit_plan(dry_run)` 与 `validate_plan` 重复，二者留一。
- `query_candidates` 这个名字暗示程序在筛选候选，有排序之嫌，应改为只读的实体查询（复用 `FactReader`，`H/facts.py:98-130`）。
- 快照“超预算按优先级保留”会重蹈 PublicPacket 的复杂度（`H/capacity_prompt.py:209-243`）。
- 草案的 replay 范围过大（见 F4）。
- Δ 扫描、20×3、决策时延扫描都应推迟到首轮结果之后。

**F15. hold 语义需要写进账本。**
- 无条件 hold 会挡住机组上已排的任务（`environment.py:209`）。
- 条件 hold 只在锚定任务已执行、且机组没有其他待执行任务时才生效（`environment.py:254`）。
- `_gaps` 与独立审计都把“有队列或有效 hold”当作已覆盖（`environment.py:242`，`audit.py:348/389/489/520`）。这正是 w1703:86:1 被掩盖的原因。
- 账本应单列“显式等待中但存在可开工工作”的机组时间，模型的等待决定照样尊重，但要算进成本。

---

## 二、修订后的方案正文

### 已确定的方向（用户已同意，不变）
- 先计划后下发的离线模拟，模型思考时模拟时钟暂停；周期重排加滚动计划，不再一出现缺口就立即补排。
- 用原子提交 `submit_plan` 取代“提案 + 确认”；生产任务全部由模型选择，程序不新增、不改派、不改写生产任务字段。
- 本轮做 B 方案（模型直接排程）加周期化；“模型定策略、程序展开”留给 C 方案。
- 每个周期一个 `codex exec` 会话，会话内用 MCP 工具多步完成；周期之间不恢复会话，靠完整决策快照衔接；模拟器状态是唯一权威来源。
- 原 B 和封存目录不动。

### 已知问题（已对照代码修正）
1. **缺口口径不一致。** `environment._gaps`（`S/environment.py:237-247`）用 `has_legal`，统计的是所有等待中的批次，没有扣除已预留给其他机组的批次；`batch_window.observe_demands`（`H/batch_window.py:45-50`）在工序层扣除了，但仍会把 `_gaps` 报出的机组记为需求（:58）。触发只看 `_gaps`（G0：`environment.py:273-277`；G1/G2：`deadline_collection.py:36`）。另一方面，有队列或 hold 的机组一律不算缺口（:242），这会掩盖 w1703 一类未分配工作。
2. **时间语义。** 过去的 `not_before` 在 `plan_delta.py:227`、`environment.py:132`、`audit.py:103` 三处被拒，提示词 `transport.py:147-149` 也要求模型显式改写；过期 hold 在 `plan_delta.py:250`、`environment.py:158`、`audit.py:136` 被拒。根源是 `not_before` 同时承担“预测”与“约束”两种含义。
3. **触发机制。** 没有周期：G0 只要出现缺口就停；v5 的 deadline 分支同样只要有缺口就停，另有 `plan_runway`（提前 135 秒）、`plan_renewal`、`capacity_limit` 三类触发。`max_ready_wait_seconds=0` 只是登记值，并不控制行为。
4. **单动作协议。** 每次调用只允许一个动作（`H/contracts.py:180-189`，`transport.py:110-112`）；每次都新起 `codex exec --ephemeral` 进程（`transport.py:424`），且禁用 MCP（:399），任何工具事件都会判为通道失败（`model_transport.py:144-147`，`transport.py:548-555`）。G0 平均每次约 21 万 token。
5. **快照不完整。** 任务表只展示与本次所选工序相关的机组（`capacity_prompt.py:157-162`），这是“26 项只显示 14–15 项”的直接原因。历史只完整保留最近一条结果，更早的在 10% 预算内只保留引用（`capacity_prompt.py:299, 322-327`）。
6. **评估口径。** “零缺计划等待”沿用“有队列或 hold 即视为覆盖”的规则（`audit.py:348` 等），因此掩盖了 w1703:86:1。每版同时改多个变量，每组只有一条轨迹。
7. **代码负担。** `src/smt_fullfab` 约 4 万行，多个历史版本并存。另外：冻结后失效的任务无法删除（`environment.py:164-168`、`plan_delta.py:199-200`），这是周期化后会暴露的潜在死锁。

### 开发位置与组织
- 新建独立实验目录 `docs/updates/2026-10-17/project/experiments/harness_v6_20261017/`（或用户指定位置），包结构为 `src/harness_v6/`。原 B、`context_window_batch60_20261016` 和封存目录都不动。每个复制进来的文件记录来源路径和 SHA256，写入 `isolation_manifest.json`。
- 依赖按三类处理，不再说“只引入四五个模块”：
  - **原样复制，纯函数，可在本仓库测试**：`plan_delta.py`（无依赖）、`harness/facts.py`（只依赖 contracts 的 `digest/require`）、`contracts.py` 中的编码与哈希函数子集（`encode/digest/strict_json/HarnessError`）。
  - **复制后改写，需要 Mac 和数据**：`environment.py`（删除 `configure_batching` 和 batch_window 分支，新增 `advance_cycle`，修正时间语义和冻结失效豁免，重写 `snapshot_dependencies`）、`observation.py`（原样复制）、`src/smt/environment.py` 及其 vendor 依赖（原样复制，用来源哈希锁定）、`harness/factory.py` 的 capture/restore（去掉 batch_state，内联 `_state_view` 或复制 `stream_snapshot.py`）、`harness/store.py`（重写 `local_path` 和 ROOT 规则）、`audit.py` 的 `audit_plan_sources`/`audit_opportunity_coverage`（删除 v5 batching 分支，同步时间语义，新增账本指标的**独立实现**）、`metrics.py`。
  - **舍弃，不带走**：`batch_window`、`deadline_collection`、`forecast_collection`、`planning_batches`、`capacity_prompt`、`fact_memory`、`presentation`、`transport*`、`recovery`、`amendment`、`source_revision`、`wall_budget`、`model_switch`、`network*`、所有 `B_*`/`C_*`/`controller*`/`offline_A*`/`stream_*`（stream_snapshot 视情况）。传输层只参考 `transport.command` 的隔离参数和 `model_process_guard` 的进程守护思路，在 v6 的 `session.py` 中重写。
- 主要风险：
  - 旧 `from_snapshot` 快照无法加载。v6 从 harness 存储状态（`factory.restore` 路径）导入 mixed_702 后，另存为 v6 自己的快照格式。
  - 物理语义可能随复制被改动。由 M0 的等价性测试兜底。
  - 账本与独立审计如果共用代码，错误会互相掩盖。审计必须独立实现，并与账本逐时刻对账。
- 在新分支开发，每个里程碑一次提交，最后开 PR。DECISIONS 补记以下决定：原子提交、周期重排、`not_before` 语义修正、失败语义、计数口径。
- 环境限制：本仓库没有 SMT2020 数据、PySCFabSim vendor、tiktoken、封存 SQLite 证据库，Python 是 3.10（归档说明用的是 3.13）。本地只能做纯函数单元测试和合成夹具测试。物理等价、轨迹分类、token 计量、codex 冒烟测试都在 Mac 上做。

### 模块（修订）
| 模块 | 职责 | 可在本仓库测试 |
|---|---|---|
| `ledger.py` | 纯函数，输入公开观察 `problem`、当前计划和执行回执，输出工序账本：就绪且未预留 / 已预留未开工 / 执行中 / 完成 / 失效。派生指标：`avoidable_idle`（基于匹配；空闲可用机组 × 满足 batch_min/max、组批键、专用、min-run 的未预留可开工批次，近似算法须写明）、`reserved_but_earlier_startable`（已预留、另有空闲合格机组可以更早开工，这是机会指标，不触发）、`explicit_wait_idle`（hold 期间仍有可开工工作）、`assigned_not_started_age`。账本同时用于触发、快照和校验提示；评估由独立审计另行实现并对账。 | 是（合成夹具）；Mac 上与 `has_legal` 物理口径对账 |
| `normalize.py` + 校验器 | **不改写字段**：过去的 `not_before` 视为“下界已满足”；过期 hold 视为无效果，无需模型取消；冻结任务一旦失效即可取消。其余硬约束照旧，一次返回全部违规，不只报第一条（现有 `_require` 抛出首个错误即停，需改为收集式）。同一输入结果幂等。`plan_delta`、`environment.commit_plan`、`audit.py` 三处同步修改，提示词同步修改，`test_smt_fullfab_plan_delta.py:86` 显式反转并说明原因。另评估是否新增可选字段 `start_mode: "when_ready"`，把预测与约束拆开（见待决问题 5）。 | 是 |
| `snapshot.py` | 结构为“稳定前缀 + 当前状态”。稳定前缀：规则、工具说明、工艺与机组静态表。当前状态：state_version、**全部**待执行任务和 hold（不按相关机组过滤）、全部执行中作业、账本摘要（每个未预留就绪工序一行紧凑记录，不省略）、可避免空闲匹配、失效任务列表、上周期回执、模型笔记。详细资料通过工具读取。序列化确定（`sort_keys`、固定分隔符）。超出预算时**失败关闭并报告**，不按优先级丢弃内容。 | 是（字节一致、完整性）；token 计量在 Mac 上做 |
| `cycle.py` | 纯状态机。锚点为 `t0 + kΔ`（复用 `runtime.advance` 的边界公式）。锚点到达后：若 `avoidable_idle > 0`、有失效任务、计划将在下一锚点前到期，或有上周期未解决的提交失败，则启动会话；否则记为“空周期”，零调用。越级事件见下一节。停滞判定：连续 K 个非空周期无成功提交，或连续 K 个周期 `avoidable_idle` 不下降且模型没有显式说明，则停止运行。 | 是（合成事件序列） |
| `environment.advance_cycle` | 复制 `advance_plan` 原始循环：保留 `_run_planned_now`、`plan_invalidated`、`expired_task`，去掉“有缺口就停”，改为每个推进步骤把账本快照写入 trace，供审计使用；推进到下一个锚点或越级事件。 | 仅 Mac |
| `submit.py` | `submit_plan(expected_state_version, submission_id, delta)`。复用 `compile_plan_delta` 的增量格式（默认 `keep: all_pending_except`，以减少输出），编译成完整计划后调用 `commit_plan` 预检。同一 `submission_id` 重复提交返回相同结果。一个周期只接受一次成功提交，之后再提交返回 `cycle_closed`。允许空增量，表示模型显式决定“不改计划”，与“没有提交”区分。回执附覆盖报告（第一版只报告，不拒绝）。去掉 `dry_run`，由 `validate_plan` 承担同样功能。 | 是 |
| `mcp_server.py` | stdio 服务器，由 codex 启动，不开套接字。启动时只读加载 harness 冻结的周期输入（快照、公开事实、计划、私有物理状态副本，供 `validate_plan` 做 `commit_plan` 预检）。工具：`read_entities`（复用 FactReader 的过滤与分页，不排序）、`validate_plan`、`submit_plan`，另可选 `get_decision_snapshot`（快照已在提示词里，仅供压缩后重读）。**不写 Store**：每次工具调用以追加方式写入本周期日志（参数、结果、哈希链）；成功的 submit 写入独占创建的 `submission.json`。并发调用一律串行处理。 | 是（进程内直接调用） |
| `session.py` | 每周期一次 `codex exec --ephemeral --json`，通过 `-c` 注入 MCP 服务器配置。白名单 MCP 调用类 item，继续拒绝命令执行、文件修改、联网等原生动作。设本周期预算：最大工具调用数、墙钟时间、token 上限。会话内关闭或限制自动压缩并检测相关事件。会话结束后由 harness（唯一写者）做三件事：(a) 核对 MCP 日志与 JSONL 中工具调用参数的哈希；(b) 在 `expected_state_version` 上做比较后写入的提交；(c) 用量计入账本。失败语义见“失败与恢复”。 | 进程内假规划器：是；codex 加本地模拟 Responses 端点：Mac 或经用户许可 |
| `evidence.py`（新增） | 迁移审计链。生产字段的来源从“模型最终输出”改为“submit_plan 工具调用参数”，并且必须同时出现在 MCP 日志和 codex JSONL 中、哈希一致。改写 `evaluation.raw_delta`/`audit_provenance` 的对应部分。 | 是（合成） |
| `metrics.py` | 三层指标。生产：迟交、产出、队列等待、换型。计划与执行：未预留就绪工序的时间积分、可避免空闲、`reserved_but_earlier_startable` 机会、显式等待空闲、开工偏移、改机比例、失效任务。Agent 成本：会话数、工具调用数、模型请求数（下界 = 工具轮次 + 1）、输入/缓存/输出 token、模型秒数、失败与未知用量。 | 是（合成）；物理部分在 Mac 上做 |
| `replay.py`（缩小范围） | 只做两件事：(1) **等价性**：按原时刻把 G0 封存的已提交计划依次提交给 v6 环境（越级和锚点关闭，使用原始触发），物理事件必须与封存 trace 逐条一致；(2) **静态分类**：对每个封存上下文，判断新账本口径会不会触发，以及是否属于“已预留但可提前”。不估算 v6 的调用数，不把旧决策嫁接到新轨迹。 | 仅 Mac |

### 周期循环与越级事件（新增明确定义）
- 锚点：`t0 = 起始状态时刻`（mixed_702 为 702 秒），`Δ = 60` 秒。越级周期结束后，如果距下一锚点不足 Δ/2，则把那个锚点并入，避免几秒内连续两次调用。
- 越级事件（第一版，可在 trace 中观测）：
  - `plan_invalidated`（复用 `environment.py:197-204, 224-227`）
  - `expired_task`（`latest_start`，:211-213）
  - `no_plan`（无有效计划，且存在可避免空闲）
  - `terminal`
- `breakdown` 作为可选开关，默认关闭。“紧急批次”和 Q-time 不纳入第一版：前者没有对应事件，后者 CQT 未实现。
- `plan_horizon` 应当不可能发生。提交约束要求 `valid_until ≥ 下一锚点 + Δ`；如果仍然发生，按缺陷记录，不当作正常触发。
- H 的定义：H 只是**快照前瞻和建议的计划跨度**，控制哪些工序和预测进入快照；`valid_until` 由模型决定，但受上面的下限约束。工序时长中位约 1,700 秒，H=300 秒对“每台机组下一项”够用，对多项排队太短。第一版建议 H = max(3Δ, 900 秒)，扫描留到后续。
- 冻结：第一版默认不使用（允许 `freeze_until = created_at`）。如果使用，必须先完成“失效冻结任务可取消”的修正，并把冻结区间定义为 `[now, 下一锚点)`。
- 周期之间不调用模型。缺口、机会、失效都写入账本并累计，在下一个非空周期的快照中完整呈现。

### 失败与恢复（新增）
- 会话失败的几种情况：进程非零退出、超时、用量未知、出现非白名单原生动作、没有调用 `submit_plan` 就结束、提交全部被拒。处理方式：本周期记为失败，**保留旧计划**推进到下一锚点；失败周期的花费和墙钟时间全部计入。连续 K_fail（建议 2）个失败周期，或累计未知用量达到上限，则停止运行。默认不自动重试。这条失败语义与 v5 的 `fallback="none"` 不同，必须登记为实验变量，见待决问题 4。
- `submission.json` 已经独占创建，但进程随后崩溃：如果 MCP 日志与 JSONL 均能核对，按有效提交处理；如果 JSONL 不完整，提交仍可采纳（由模型作出），但该周期成本标记为“未知用量”。是否采纳须在登记中事先写定，不能事后选择。
- harness 自身崩溃：以 Store 中最后一次成功的周期提交为恢复点。正在进行中的会话不重跑，以免重复计费；它的 submission 按上一条规则判定。

### 里程碑（修订顺序；全程不调用模型）
| 里程碑 | 内容 | 验收（可验证） | 地点 |
|---|---|---|---|
| M0 骨架 | 建目录、隔离清单、来源哈希、DECISIONS 草稿；复制纯函数模块 | `plan_delta` 的 29 项测试原样通过（本仓库已实测通过）；facts 的重建测试通过；隔离清单列出所有复制文件的哈希 | 本仓库 |
| M0b 物理等价 | 复制并精简 environment、observation、smt 适配器和 vendor；导入 mixed_702 | G0 封存提交按序重放，`dispatch`/`operation_complete`/`downtime` 事件逐条一致，到 1603.10 秒；`factory` 的 capture/restore 往返哈希一致 | Mac |
| M1 账本 | `ledger.py` 和独立审计中的账本对账 | 合成夹具：跨机组预留、组批下限、专用、min-run、hold、条件 hold、失效各至少 1 个用例。Mac 上：(a) 旧口径复现 10/15/4；(b) 新口径下这些上下文全部不触发，例外逐条列出；(c) 统计其中 `reserved_but_earlier_startable` 的数量和潜在空闲秒数；(d) 共同终点 w1703:86:1 计入 `avoidable_idle` 或 `explicit_wait_idle` | 合成：本仓库；分类：Mac |
| M2 时间语义 | normalize，三处校验和提示词同步，冻结失效豁免 | `past_start` 测试反转；过期 hold 用例；冻结失效可取消；其余拒绝用例的错误码不变；一次返回全部违规；幂等。Mac 上：d34-421 的原上下文能直接保留原任务通过 | 本仓库 / Mac |
| M3 快照 | `snapshot.py` | 稳定前缀在不同周期间逐字节一致；全部待执行任务和 hold 都在快照内（合成 26/26；Mac 上用 G0 1649.82 秒上下文验证 26/26）；未预留就绪工序 100% 有一行记录；超预算时失败关闭。token 计量在 Mac 上用固定版本 tokenizer | 本仓库 / Mac |
| M4 周期与提交 | `cycle.py`、`submit.py`、`advance_cycle` | 合成事件序列：会话启动次数 = 非空锚点数 + 越级数；空周期零调用；锚点合并规则；`valid_until` 下限；同一 submission_id 幂等；周期关闭后拒绝；空增量与未提交区分；停滞判定生效 | 本仓库；`advance_cycle` 在 Mac |
| M5 MCP 与会话 | `mcp_server.py`、`session.py`、`evidence.py` | (a) 进程内假规划器通过 MCP 函数接口跑完 3 个合成周期，日志哈希链完整，证据核对通过；(b) 用 codex 二进制配合本地模拟 Responses 端点（不接真实模型）完成 F6 列出的全部能力检查，全部通过才能进入实际试验 | (a) 本仓库；(b) Mac 或用户许可后在本仓库 |
| M6 登记 | 事先写定主要指标、质量底线、计数口径、失败语义、组别与预算；离线空跑 | 空跑时生产任务必须来自脚本化规划器，并标记为“非模型、仅机制测试”，不得进入结果 | Mac |

删掉的验收：“周期数 9–11”（见 F12，只作为参考估计保留在附录）。

### 实验设计（修订，回答“每次只改一个变量”）
- **共同修正底座**：账本口径、时间语义、完整快照属于缺陷修正，所有新组都启用，不作为比较变量。它们的效果先用 M1/M2 的离线分类量化（触发减少多少、机会损失多少）。
- **原子提交**：所有新组都启用。它的效果可以直接记账：旧协议的确认调用数在共同区间为 21/23/30。不另设对照组。
- **两个比较因素**：触发 T ∈ {事件（账本可避免空闲即触发），周期（Δ 锚点）} × 交互 S ∈ {单动作单进程，MCP 会话}，构成 2×2：E1、P1、E2、P2，其中 P2 就是 v6。
- **分阶段**：
  1. 第一轮实际试验只跑 E1 和 P2 两组，加上 G0 作为封存参照，不重跑。两组都从 mixed_702 出发，区间 702→1603.10 秒，每组 3 条轨迹，调用上限事先固定。
  2. 若 P2 与 E1 的成本差超过事先登记的阈值，第二轮补 P1，把差异拆成触发因素与交互因素。E2 视预算决定。
  3. 多 seed（5×3）和 Δ 扫描放到之后，取决于预热策略和预算。
- **主要指标须事先登记**：
  - 成本：推进到共同终点的未缓存等价输入 token，以及模型请求数下界。不再以“调用次数”为主要指标，因为会话制下它不可比。
  - 质量底线：加权迟交、产出、可避免空闲积分，均不劣于 E1 超过登记容差；`reserved_but_earlier_startable` 积分单独报告。
- **随机数**：工厂随机数按事件键生成，天然共同；组批变化会改变加工时长，这一点写入限制说明。模型随机性没有种子，靠多条轨迹覆盖。

### 待用户确认（原三条，修订后见第三部分）

---

## 三、仍需用户决定的问题

1. **在哪里跑。** M0b、M1 分类、M3 token 计量、M5(b)、M6 都需要 SMT2020 数据、vendor、tiktoken 和封存 SQLite 证据库。选项：全部在 Mac 上做；或者把数据和证据拷进本仓库的私有目录（注意许可和体积）。
2. **Δ、H 与有效期。** 初始 Δ=60 秒，H 建议 max(3Δ, 900 秒)，而不是 300 秒。是否同意 `valid_until ≥ 下一锚点 + Δ` 作为提交约束？是否同意“空周期跳过”（零调用）？
3. **越级集合。** 第一版只用计划失效、`latest_start` 到期、无计划和终止，“设备故障”作为默认关闭的开关，是否同意？“紧急批次”和 Q-time 本轮不做，是否同意？
4. **失败语义。** 会话失败时保留旧计划继续推进（连续 2 次失败才停），还是沿用 v5 的“失败即停”？前者让失败周期不付质量代价，会影响比较，需要登记。“已经独占写入 submission 但进程崩溃”的提交是否采纳？
5. **`not_before` 语义。** 只修正“过去的值视为已满足、过期 hold 无效果”（最小改动），还是再加 `start_mode: "when_ready"`，把预测与约束拆开（可以根治 w1462 类问题，但多一个提示词和执行器变量）？
6. **“已预留但可提前”的处理。** 只写进下一周期快照并计入指标（建议），还是在可提前时长超过阈值时也触发？
7. **实验规模与预算。** 第一轮只跑 E1、P2 各 3 条轨迹，是否同意？每组请求和 token 上限多少？是否授权第二轮的 P1？多 seed 需要的预热前缀由谁来排（例如固定规则策略，明确标注为非模型、不进入评估区间）？
8. **主要成本指标。** 以未缓存等价输入 token 加请求下界为主，还是以会话数或周期数为主？
9. **覆盖不足的处理。** 第一版只报告、不拒绝（沿用草案），是否维持？
10. **代码位置。** 新目录放在 `docs/updates/2026-10-17/project/experiments/harness_v6_20261017/`，还是另起独立仓库？

---

## 附录：估算（仅供参考，不作验收）
用最终报告新增区间（882→1603.10 秒）的触发时刻，按“空周期跳过、轨迹不变”统计含触发的锚点桶数：

| Δ | G0 | G1 | G2 | 区间锚点总数 |
|---|---|---|---|---|
| 60 秒 | 9 | 10–11 | 10 | 12–13 |
| 180 秒 | 4 | 4–5 | 4–5 | 4–5 |
| 300 秒 | 3 | 3 | 3 | 3 |

这些是会话数，不是请求数。如果每个会话平均 r 次请求，总请求约为桶数 × r，必须与 G0 的 56 次（1 次调用 = 1 次请求）用同一口径比较。
