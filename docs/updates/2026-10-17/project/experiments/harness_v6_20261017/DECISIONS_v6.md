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

- 只改变快照表示：无损共享工步定义/路线序列、静态机器分组/范围、就绪工序分组/机组族引用、动态一次表头；静态前缀始终在前。所有内容可还原；就绪行按 operation_id、动态机器按 machine、静态机器按 id 规范排序，不保存位置元数据；[family,name] 仅用于完整且已排序的族列表，其余 [set,id] 保留 eligible 原序，不改变 submit/task schema。
- 唯一数值归一化：float 保留 10 位有效数字，解码相对误差 ≤1e-9；非浮点精确、int/float 类型保持。无隐式默认、无同值 `=`；缺失字段 `!` 与 None `null` 明确区分。
- 删除重复快照工具；完整快照只作为 prompt 提供。ScriptedRunner 每会话 validate/submit 两次工具调用，请求数下界由 4 变 3。
- 回执违规详情上限 50，额外报告总数、按码计数和 truncated；内部完整验证/接受语义不变。read_entities ids >512 明确拒绝。
- LiveRun 必填 context_token_budget、request_overhead_tokens、output_reserve_tokens；快照 + 系统/工具开销 + 输出/推理预留 ≤ 总上下文预算，超限失败关闭并写出每项。移除旧的仅快照预算参数。
- 无模型调用、网络、提交；配置环境验证沿用 F–K 已授权的公开/封存夹具。真实理解准确率、F6 系统提示/工具开销和生产 reserve 登记仍在 Mac 上完成。

### Phase M（用户批准：仅决策的 delta）

- 删除模型任务的 `lot_ids/steps/visits`：`operation_ids` 已唯一决定当前工序身份；
  编译器查 observation，不接受模型重复或矛盾声明。保留内部身份一致性校验。
- 删除模型 `anchors`：状态绑定使用外层 `expected_state_version`；host 仍计算并保存四项哈希。
- 删除 task/hold patch 的 `keep.mode/keep.ids`：仅取消列表和替换/新增，未提及者保留。
- 删除 `schema/order_policy`：协议常量由 host 定义；删除 header 的
  `created_at/scope/version`：分别由 now、责任范围、确定性状态/提交/输入哈希生成。
  模型 header 决策仅 `valid_until/freeze_until/reason`。
- 删除模型任务的 `machine`：新增或显式移动由 `machine_orders` 决定，同时表达队列顺序。
  Phase M2 修订：新增必须列一次；未列出的替换继承原机台与位置；取消无需队列，稳定删除。
  保留或替换任务列于另一机台即移动，源与目标均须完整队列（包括空源队列）。
  完整队列仅在新增接收机台及移动两端强制要求；可选显式重排仍须给完整队列。
- 快照任务投影同步删除这些字段，新增 `machine_orders` 保留任务分配信息；内部结构不变。
- 完整 schema 由 MCP 两工具和 single_action 共享；拒绝旧字段，不提供兼容 shim 或格式开关。
- 新旧版本字符串及依赖版本的哈希不应要求字节相同；物理、任务身份/分配/队列/时间、holds
  和恢复结果必须相同。仅生产字段等价，不能把版本元数据变化误报为物理差异。


## Phase N：explicit / dense 快照 A/B

登记表必须填写 `snapshot_format: "explicit" | "dense"`，模板为 explicit。
将登记值同时传入 `stable_prefix(..., snapshot_format=...)` 和
`LiveRun(..., snapshot_format=...)`；后者传给 `build_snapshot`，格式与前缀不符会拒绝。
检查点保存格式，恢复时拒绝格式变化。旧纯函数调用默认 explicit。
第一行分别为 SNAPSHOT_V1 / SNAPSHOT_V1_DENSE，decode_snapshot 自动识别。
生产任务、物理语义和信息覆盖不变；格式说明文字按格式不同，其余规范对象一致。

Dense 表头声明 defaults 和 equals；空单元格为声明默认值，! 为缺字段，null 为 None。
默认值取规范化后整列众数（含类型），并列按编码字典序。
逐列试算完整表（含表头）token 数，仅严格减少时采用。
cadence 的 = 引用 processing；processing_until 的 = 引用 [available_at]。
字符串仅在无歧义时裸写；嵌套对象仍是 JSON/分布编码。
release_time 等于 time 且类型相同时省略，由 $release_time_is_time 声明恢复；真正缺字段仍缺。
原有工步去重、family/set、ID 范围、10 位浮点及规范排序保留。

实测/正式 Mac 调用须向 stable_prefix 与 build_snapshot/LiveRun 传入同一个
`tiktoken_counter('o200k_base')`。纯 stdlib 合成测试使用确定性估计器，不能证明真实
模型 token 节省；相同输入和同一计数器保证字节稳定，不能跨计数器比较前缀哈希。
计数器是既有预算计量依赖，不是新增实验变量；新增变量仅 snapshot_format。
Dense 扩展 legend 仅 dense 包含。默认值只依赖所属表，静态表不依赖当前周期。

## Phase O 运行路径

- CodexRunner 仅继承登记的环境变量，独立进程组，完整 JSONL、stderr 文件、TERM/KILL 墙钟超时。
  每次 CLI 运行（含恢复）只查询一次版本；与登记字符串精确一致才继续。不处理认证。
- prompt 尾部单独给精确时间和提交约束；event 严格大于下界，避免紧凑浮点时间影响 freeze_until。
  稳定前缀不含周期数据；预算计入整个 prompt 和登记 overhead/reserve。
- 正式 CLI 必须 results=True 验证登记。机制 run 永远标记“非模型、仅机制测试”。
  CLI 完成会话 checkpoint 在清 inflight 前发布；这比普通 LiveRun 的段检查点更保守，增加磁盘成本。
- 新完成 lot 计 throughput 与 weight×tardiness（缺省 weight=1）；完整小时/稳态窗口均保留。
  汇总 spread=总体标准差；quality tolerance 是绝对量，迟交/空闲越低越好、产出越高越好。
- fixture 日历不能通过改 horizon 延长；起点之后工厂 seed 明确登记，模型随机性没有 seed 保证。
  真实 Codex 参数/JSONL 合约仍需既有 F6 探针，fake 只证明协议和失败路径机制。

## Phase P：可复现 Mac 测量

- CodexRunner 的超时只由 leader 未在 deadline 前退出触发；正常/非零退出也杀进程组，
  并以短有界窗口排空 stdout。stdin/stdout 都非阻塞，避免管道容量导致死锁。
- 探针只接受 127.0.0.1 HTTP provider，隔离认证环境；保留全部原始证据。
  当前 Responses SSE 和 Codex flags 为待真实 pin 验证的协议假设，失败明确阻止试验。
- overhead capture 广告生产 schema，用完整当前对象压力工具结果录制多轮；建议只覆盖
  测试范围。轮次至少覆盖注册工具上限；不能推断未来任意 WIP 或不可见服务端开销。
- A/B 延用 P0/P0b 题集/计分，仅加单动作 schema runner；不读 answer key，失败请求留缺失，
  不自动挑选格式、不自动重试，不把 fake usage 当模型成本。
- `--max-sessions` 按本次调用新增会话数停止，保留可恢复检查点；smoke 独立目录不进最终统计。
- preflight 只查 --version；认证由用户管理并在独立真实 smoke 验证。CQT/Q-time 未实现。

- Phase Q：提交/校验回执覆盖仅报告计数及最多 50 个排序后的未预留就绪工序 ID；复用账本就绪定义，完整未覆盖集合可由已保存计划和冻结问题离线重建，不拒绝覆盖不足。
