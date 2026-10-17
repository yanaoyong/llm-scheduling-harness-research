# Harness v6：账本、周期与物理机制验证

本目录保存 Phase A–F 的独立实验实现；默认纯函数 suite 不需要模拟器，所有测试均不调用模型或网络。
获准的公开 SMT2020 物理机制验证与复跑入口见文末 Phase F。
权威依据：`research/2026-10-17-codex-search/HARNESS_V6_PLAN_reviewed.md` 第二部分
及 `HARNESS_V6_LONG_RUN_ADDENDUM.md`（冲突时以后者和 COMMON 的最终决定为准）。

从本目录执行：

```bash
python3 -m pytest -q
```

Python 3.10+，生产模块仅标准库；测试使用 pytest。`pytest.ini` 把 `src` 加入路径。

- `plan_delta.py`：显式增量编译，保留原有锚点、分区、身份、资格、组批、冻结和顺序约束。
- `normalize.py`：不改写生产字段的幂等复制、时间解释、完整计划收集式校验。
- `executor.py`：纯队首开工判断；返回 `{task, reason}`，不执行物理派工。
- `facts.py`、`contracts.py`：来源顺序事实、分页、重建、版本和确定性编码。
- `prompt_rules.py`：后续快照及会话共用的规则文本。

任务字段 `start_mode` 可为 `when_ready`（省略时默认）或 `not_before`。
两种模式中的 `not_before` 都是可选硬下界；不会插入默认字段，也不会改写过去的值。
`normalize_plan` 返回分离副本。冻结比较保持规范 JSON 字节一致（整数与浮点拼写也有区别）。
没有下界的任务按原计划创建时刻判断是否属于冻结区。

`validate_plan` 接受权威 problem、execution_state 和可选 base_plan，返回有序的
`{code, detail}` 列表。`compile_plan_delta` 拒绝时保留 `.code` / `.detail` 兼容接口，
并在 `.violations` 返回所有可独立求值的生产约束违规。`validate_plan_delta` 返回同一列表。
结构无效、分区不明确或机组身份不可用时，依赖它们的编译步骤不能继续；此时返回结构错误，
不猜测一个计划来校验。缺失某任务身份数组不会阻止其他任务和 hold 的校验。

执行状态新增可选 `invalidated_task_ids`，必须由宿主提供、纳入状态锚点哈希，
只能指向待执行的原任务。只有显式取消才豁免冻结保护；改写或重排仍被拒绝。
取消后其余冻结前缀仍受保护。过期 hold 保留原值但不生效，包括已离开计划的旧锚定任务。

`decide_start` 的 readiness 映射以 operation_id 为键，值含公开身份/资格/组批字段和
`ready: bool`。机组状态含 machine、ready、down_until；可提供 available、legal 和
invalidated_task_ids。适配器负责从真实 lot 状态、运输、专用和 min-run 条件计算这些值。
队首未满足条件时不查看后续任务作为替代；条件 hold 只有锚任务已执行且队列空时生效。

来源文件及初次/最终复制哈希见 `isolation_manifest.json`。最初的 verbatim 编译器先通过
原有 29 项测试，之后才实施 M2；只反转了过时的 past-start 与 expired-hold 断言。
Mac 集成验收、物理一致性及后续阶段待办见 `MAC_VALIDATION.md`。

## Phase B：M1 账本与 M3 快照

新增 `ledger.py`、`audit_ledger.py`、`sealed_contexts.py`、`snapshot.py`，均为新写代码，
没有新增从 P 复制的文件，原 isolation manifest 的来源哈希不变。

账本直接使用 observation 的 `machines`、`operations`（包括 conditional、predecessor_ids、
release_time、eligible_machines、batch_key/min/max、setup）；机组使用 currently_busy/down、
min_left/min_setup。`available_at` 是预测，不代替已观测的忙闲状态。
已知专用通过 eligible_machines 表达；未知专用及未解析 same_machine_as 保守排除。
公开未来工序仍有行，状态为 ready_unreserved、ready=False，不算就绪工作。
缺失工序不等于完成；running/done/invalid 必须来自宿主回执。

`ledger_from_scratch(problem, plan, receipts)` 的 receipts 为：
`{"operations": [{"operation_id": "a", "state": "done"}], "tasks": [{"task_id": "t", "state": "invalid"}]}`。
任务级 running/done 会移出 pending，invalid 保留并显式显示。任务 ID 必须在当前执行账本内唯一；
适配器需要对计划版本进行命名空间处理，并删除过期任务/回执，不能把同名旧版本回执带入新任务。
assigned_not_started_age 使用任务已知的 assigned_at，缺省使用 plan.created_at，表示当前预留年龄；
跨版本首次预留年龄必须由宿主保留 assigned_at 元数据，不能从无历史的观察反推。

`ledger_apply(ledger, delta)` 原地应用并返回账本：time 为标量，其他表为
`{"upsert": [完整记录], "delete": [ID]}`。表名包括 operations、machines、tasks、holds、
receipts、task_receipts；主键依次为 operation_id、machine、id、id、operation_id、task_id。
无 ID 的原始 hold 使用内部 `hold:<源位置>` 索引，初次加载及快照保留原 JSON；新增 hold 的
增量记录需提供 ID。任务替换保留队列位置，重排通过显式删除并按新顺序添加受影响队列后缀。
重复应用同一 delta 幂等。单步更新只访问变化记录和变化任务的工序成员，O(变化量)，
不会扫描 WIP 或复制整个账本。`rows()` / `metrics()` / 完整快照是独立的全量读取，
其成本依赖当前状态；不要在每个事件后无条件调用它们。宿主负责在锚点/审计需要时读取。

可避免空闲采用**确定性贪心极大匹配近似**：按机组 ID 遍历空闲可用机组，对可开工、未预留
工序按精确 batch_key/min/max 分桶，按规范 JSON 桶键选择首个满足下限的桶，按工序 ID
取 batch_min 个，之后消费这些工序。一个工序不会同时覆盖多个机组；这不是最大匹配，
可能低估最优可利用机组数。顺序只用于计量见证，不生成生产任务、排名建议或派工。
组批上限、已知专用、min-run 均检查；需要 Mac 与真实 has_legal 对账。

有队列/hold 不视为覆盖；hold 下未预留工作也计入 avoidable_idle。
explicit_wait_idle 单独对每个有效 hold 机组检查可行批次，包含已预留工作。
条件 hold 必须锚任务已执行且队列为空；过期 hold 无效果。
两种空闲指标有交集，不能相加；explicit_wait 的不同机组可能共享候选批次。
reserved_but_earlier_startable 只报告其他空闲合格机组上的提前机会，不参与触发。
机会秒数来自公开 available_at/not_before 预测差，不是实际空闲积分；没有可用预测时为零，
不代表没有机会。静态分类按同一上下文/工序取最大差，避免多个替代机组重复计秒。

`audit_ledger.audit_ledger` 不导入账本或 normalize 辅助函数，独立筛选兼容类并取首个
最小合法组合，复算相同贪心口径；`reconcile` 返回所有指标差异。Phase F 用独立资格
索引避免逐机组扫描整个 WIP，并与穷举 oracle 对照；仍是全量读取，不是物理增量更新。
它验证公开近似口径，不替代真实物理审计。

快照前缀由规则、工具描述、路由和机组静态表构建一次，并在各周期复用原始 bytes。
当前区包含全部 pending task/hold（包括失效和过期条目）、机组当前状态、全部调用者提供的
running jobs、全部未预留就绪工序、匹配、机会、失效任务、最近一次回执、当前模型笔记。
历史只保留固定 64 字符 SHA256 链摘要，不携带历史事件数组；完整历史留在外部证据日志。
调用者必须只传最新回执与当前笔记，不能把对话历史塞进这些字段。数值时钟/版本自身的十进制
位数可能随数值变化，历史长度不会累积到快照。测试使用 1,500 个等宽时间/版本验证恒定字节数。

默认 token counter 为 ceil(字符数/4)，只用于离线确定性估计。支持注入真实计数器，
超预算抛出 SnapshotBudgetExceeded，report 含计数、预算、字节数和完整行数，dropped_rows=0，
不返回被裁剪快照。partitioned/tiered 仅保留 mode 接口，明确抛 NotImplementedError。
Mac tiktoken 惰性适配器及封存 SQLite 只读适配器不在本地访问真实证据。

## Phase C：周期、提交、长序列机制验证

新增 `cycle.py`、`submit.py`、`checkpoint.py`、`metrics.py`、`synthetic.py`。
全部为 stdlib，不导入真实工厂；生产任务只在显式标记“非模型、仅机制测试”的
`scripted_delta` 中生成。它不是实验组或调度质量基线。

- `CycleMachine.begin/finish`：默认从 t0 锚点开始；模拟时钟在会话期间暂停。
  `begin` 返回 session=False 的空周期不调用规划器。无计划且无可避免空闲也是空周期。
  真实宿主必须按锚点或事件调用，不能跳过锚点。合并越级后的近邻锚点时，提交者可见的
  next_anchor 已反映合并，因此有效期下限仍有完整 Δ 余量。plan_horizon 记录缺陷并停止。
- `Submitter.submit_plan`：每个周期一个实例，宿主串行调用；回执 accepted 表示周期内
  预检接受，最终是否采纳由 `finalize(process_ok=..., usage_known=...)` 决定。
  任何失败保留旧计划；一次成功后关闭该周期。重放同 ID 同参数返回原回执，
  同 ID 改参数拒绝。调用方须用 cycle ID 命名空间隔离不同周期的 submission_id。
  `{}` 显式不变更，仍校验当前待执行任务与有效期，不自动延长计划或修复任务。
  非空增量遵循 Phase A 格式，允许省略 tasks/holds 的默认保留块。
  `physical_precheck(plan, problem, execution_state)` 返回全部私有物理违规列表，
  必须只读；实际物理采纳由后续宿主在会话成功后执行。
- `CycleConfig.for_stage`：S0 默认 60/900，S1–S4 必须登记 Δ；H 默认 max(3Δ,900)，
  仅供快照前瞻与建议跨度，不能作为 valid_until 上限。S2–S4 默认启用 breakdown。
  K_fail、stall_cycles、unknown_usage_cap、segment_seconds/cycles、累计/每小时成本上限
  都在配置中；未登记预算时 cap=None，仅适用于机制测试。
- 停滞：连续非空周期无成功提交，或正的 avoidable_idle 连续不下降且无显式模型说明。
  零空闲不会造成假停滞；空周期重置 idle streak。未知用量按失败会话累计，不能清零。
- `Metrics`：integrate 按小时边界拆分计数×秒；生产与执行事件计入发生小时，
  会话成本计入开始小时。请求下界=工具轮次+1；input_per_request 使用此下界作分母，
  真实请求数可取得时应由后续会话适配层另行核对。未缓存等价输入为
  input-cached+cached_input_weight×cached，系数是登记参数（合成默认 0.1，不代表报价）。
  每模拟小时成本用实际覆盖秒数作分母；无推进时 rate=None。稳态按 exclude_first_hours
  过滤，不删除原始小时桶。开工偏移和改机比例分别保存分子/分母。
- `DriftRule`：登记四种小时指标的绝对上限；任一超标连续 N 个完整小时则停止。
  漏小时重置 streak，重复小时拒绝；不在运行后选择阈值。预算只在段边界核对累计成本，
  小时预算对应 cap×累计模拟小时；超额在边界停止，不在会话中重试。

检查点宿主协议：在段边界调用 `CheckpointStore.save`（或合成 runner.checkpoint），
传入工厂状态、cycle.capture()、capture_ledger()、累计成本与指标状态。
每次会话启动前必须 `mark_inflight` 保存最新完整恢复包；可在收到用量/提交后更新。
正常完成后先发布新检查点，再 clear_inflight。恢复用 recover()，未完成会话不重跑，
丢弃候选提交、保留已知成本并增加未知用量/失败计数。返回状态继续到下一个有效锚点。
日志文件按段关闭后用 rotate_logs(segment, {'trace': path, 'mcp': path, 'jsonl': path})
压缩；压缩文件与哈希清单持久化之后才移除原文件。检查点/marker 用 tmp+rename、fsync；
哈希不符失败关闭，不静默回退旧状态。宿主是唯一写者；本模块不实现多进程锁。

当前合成 runner 的 checkpoint/restore 验证正常段恢复；通用 recover 另测崩溃路径。
真实会话的 WAL 更新、证据核对、物理提交与日志关闭由 Phase D/M5 接入。
运行 `python3 -m pytest -q tests/test_cycle_submit.py tests/test_metrics_checkpoint.py tests/test_synthetic_long_run.py`。
长序列包含 1,200 个周期、四个循环 lot、两个机组族、两道工序、双件批次、事件键随机时长。
快照只含当前状态与固定摘要；指标小时桶和磁盘段档案可随时长增长，不进入模型快照。
真实稳态 WIP 增长、运输、返工、复杂故障/保养和 CQT 不由此小工厂证明。

## Phase D：MCP、会话证据与 Mac 接口

周期暂停后，宿主把 `cycle.json` 写入冻结输入目录。它包含 snapshot、FactReader facts、
execution_state、context_ref 和 submit_config；后者指定 state_version、next_anchor、
source_sha256 和可选 delta_seconds。真实工厂还必须提供 private_state（同目录内的私有
capture JSON），用于副本预检。输入目录只读；每周期使用全新的输出目录。

`mcp_server.py` 是逐行 JSON-RPC 2.0 stdio 服务，支持 initialize、tools/list、tools/call。
四个工具为 read_entities、validate_plan、submit_plan、get_decision_snapshot；不排序候选，
不写 Store。线程锁串行化所有调用；mcp.jsonl 逐条 fsync 并连接哈希；submission.json
独占创建。validate_plan 只修改克隆，成功 submit 也只是暂存。

`session.py` 构造命令但不启动 Codex。Runner 接口负责执行及墙钟终止；测试仅用假 runner。
宿主按 JSONL 白名单、工具预算、累计 token、退出码与用量核对；`evidence.py` 再校验
双路参数、日志链，并从冻结底座重新编译 delta 比较整个计划。保留任务来源继承自可信底座，
新增/替换字段来自此次工具参数。只在全部通过后调用原子 compare-and-commit。
checkpoint 接口先写 in-flight，完成回执持久化后才清除；崩溃前 submission 不采纳。
`store_v6.py` 默认限制写入本实验目录，也允许宿主显式指定独立 root；MCP 不导入 Store。
真实工厂使用 factory_v6.commit_physical 同事务写计划、物理状态及新增事件，返回成功后
宿主才替换内存环境。失败费用及未知用量仍进入 metrics。

JSONL 类型表集中于 EVENT_TYPES，属于待 Mac 验证的接口契约。并行工具不能按工具个数
计算请求下界；未有逐请求证据时保守记“有工具的一轮 + 最后一轮”，不把它当精确请求数。
工具数量由服务端限制，墙钟由 Runner 限制；累计 token 上限在会话退出时检查，可能有
最后一轮超额。model_max_output_tokens/压缩阈值是待 F6 验证的配置，不能宣称硬计费上限。

物理模块：env_adapter（移除 v5 批处理触发，新增 advance_cycle）、observation（原样复制）、
factory_v6（私有 capture/restore/预检）、audit_v6（独立来源、账本与机会积分）、replay
（仅等价性与静态分类）。适配器调用纯 executor 检查队首；不会添加或更改存储的生产任务。
历史计划缺 operation_ids 时只在账本/资格检查视图补身份，不改提交计划。复制来源与哈希
均在 isolation_manifest.json；snapshot 指纹按实际物理模块位置和 v6 源码重新计算。

`registration_template.json` 是未授权结果的空跑登记，生产计划标签为“非模型、仅机制测试”。
成本上限、质量底线和容差尚空；registration.load(..., results=True) 必须拒绝。
进入实际 E1/P2 三轨迹试验前须填写并重新登记；S1–S4 另行授权。

运行所有离线测试：`python3 -m pytest -q`。测试包含真实 Python stdio 子进程，但不启动
Codex、不访问网络、不读取真实封存证据。Mac 入口与夹具契约见 MAC_VALIDATION.md。
Mac-only 的 mac_probe 提供脚本化 loopback Responses 服务，不连接真实模型；当前未运行。

限制：真实物理、tokenizer、Codex 配置与 JSONL 字段仍待 Mac 验收。完整账本 trace 的
生成目前按事件重建公开观察，尚未优化成物理事件增量；大型工厂的单步成本须测量。
独立机会审计证明公开输入的匹配口径，私有物理合法性仍须单独复核。CQT/Q-time 未实现，
模型随机性不能用固定 seed 消除，组批变化会改变加工时长。空跑不能证明生产质量或成本。

### Phase E：四组共同底座

| 组 | trigger | interaction |
|---|---|---|
| E1 | event | single_action |
| P1 | periodic | single_action |
| E2 | event | mcp_session |
| P2 | periodic | mcp_session |

groups.config_for("E1", CycleConfig(...)) 选择因素；登记必须给出每个组的
group_configs，映射不一致即拒绝。模板仍只登记首轮 E1/P2，不授权其他实跑。
所有组共享账本匹配、when_ready、不改写时间字段、完整快照和原子提交。

event 模式 anchor=None，宿主每个物理事件后读取账本；正的 avoidable_idle
立即启动决策，未满足组批下限的 ready 行及已预留机会均不触发。失效、到期、
no_plan、terminal 和开启后的故障失效路径保留。同一模拟时刻不重复决策
（terminal 除外）；失败保留旧计划，推进到下一物理事件，按同一 K_fail/
无成功提交/空闲不下降规则停止。没有事件锚点，也不因“上次失败”自造定时请求。
event 提交要求 valid_until > now + delta_min（默认 60 秒，严格大于）；
periodic 仍要求 valid_until >= next_anchor + delta。

single_action.write_schema(path) 写出与 MCP submit_plan 参数一致的 schema；
single_action.command(input_dir, schema_path, model=...) 仅构造
codex exec --ephemeral --json --output-schema ... -c mcp_servers={}。
宿主调用注入 Runner 的 single_action.run，每次决策只运行一次，无重试。
最终 completed agent_message 必须是参数 JSON；任何工具 item、压缩、未知
事件、失败退出、未知用量均不能采纳。原 JSONL、哈希、最终参数、编译计划和
回执组成 evidence，可用 single_action.audit_provenance 独立重编译核对。
保留字段来自可信冻结 base，新字段必须来自最终模型输出，不能补造生产选择。
宿主须持久化返回 evidence；可选 checkpoint 参数沿用 in-flight/完成后清除协议。

计数统一经 Metrics：每个单动作进程计 1 session、1 request；MCP 仍用工具轮次
加一的保守下界。缓存权重、未缓存等价输入和模拟小时分母相同；周期预算也按
缓存加权输入计费。SyntheticRun(group="E1") 等支持全部四组，始终标记
“非模型、仅机制测试”。合成 MCP 路径沿用直接调用 Submitter 的机制驱动；
真实 MCP 双通道另由 test_mcp_session 检验，不把脚本成本当模型结果。

物理适配器 advance_cycle(..., trigger="event", decision_after=上次决策时刻)
按步检查账本并返回 avoidable_idle；宿主将该原因作为普通 event-mode
begin(..., avoidable_idle=...) 输入（event 参数留空），其他越级原因照传。
decision_after 防止失败后在同一时刻重复中断。物理接入和真实 Codex 能力仍须
按 MAC_VALIDATION 在 Mac 验证；当前不是已获授权的实跑启动器。

### Phase F：公开 SMT2020 物理机制验收

本阶段获准使用预装的公开 Dataset2 LVHM 与固定 vendor，所有生成夹具、checkpoint、
轨迹均留在仓库外。`scripts/build_public_fixture.py` 从 0 运行到 702 秒：按机组 ID
升序，按 lot ID 排序的首个合法批次选 batch_min 个，避免重复占用 lot；每个物理事件
重新决策。标记为 **非模型预热，仅机制验证**，与封存 mixed_702 不可比。

```bash
export PYTHONPATH="$PWD/src:/workspace/v6-mac-env/physical"
export TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache
/workspace/v6-mac-env/venv/bin/python scripts/build_public_fixture.py \
  --data-dir /workspace/v6-mac-env/physical/data/smt/SMT2020_LVHM \
  --output /workspace/v6-mac-env/work/public.json
/workspace/v6-mac-env/venv/bin/python scripts/run_public_physics.py \
  --fixture /workspace/v6-mac-env/work/public.json --group P2 --until 1603.10 \
  --output /workspace/v6-mac-env/work/p2.json
# E1: 将 group 改为 E1；一小时 P2: --until 4302 --delta 300 --breakdowns
V6_MAC_FIXTURE=/workspace/v6-mac-env/work/public.json \
  /workspace/v6-mac-env/venv/bin/python -m pytest -q
```

公开 bundle 使用 `public_702` / `public_time_semantics`，不冒用 mixed_702 / d34_421。
缺少封存键的测试明确跳过；已有键结构损坏仍失败。真实 Codex F6 探针仍未执行。
`tiktoken_counter()` 默认 **o200k_base**，与 v5 local_tokens 一致；本次固定 tiktoken
0.14.0。未注入 tokenizer 的纯函数 build_snapshot 仍使用明确标注的字符估算器。
公开脚本使用直接 Submitter 机制接口，两组只验证触发模式，不声称验证 Codex
single_action/MCP 线协议，也不报告虚构的请求数或费用。

公开机制 driver 在每个推进步骤先独立对账，再把完整 ledger_snapshot 写到仓库外
`.ledger.jsonl.gz`；内存历史只保留同一序号/时刻及 SHA256，物理事件不删减。
检查点保存工厂、账本、周期、零模型成本、已累计积分和测量行；恢复段另写 evidence，
比较物理状态、周期状态、积分、步数及逐周期快照测量。输出路径须全新，避免拼接旧证据。

Phase F 修复：过期条件 hold 不要求已消失的锚任务；冻结 when_ready 任务缺省硬下界时
观察不再崩溃；回执排序确定。静态 route 缓存保持原浮点求和顺序，并与原观察逐字段核对。
`ledger_read_view` 只供拥有当前不可变输入的即时读取使用；持久化和可变调用者仍使用
深复制的 ledger_from_scratch。上述优化未把物理观察变成 O(变化量) 增量维护。
