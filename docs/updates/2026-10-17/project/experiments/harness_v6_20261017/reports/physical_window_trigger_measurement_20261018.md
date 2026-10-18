# 物理时间窗、字段成本与周期触发测量（Phase S，2026-10-18）

本阶段仅测量。没有修改 `src/`、既有测试、提示规则或既有脚本；所有原型只在新建 scripts 文件。周期重排 + rolling horizon 保持不变；锚点之间只允许 plan_invalidated / expired_task / no_plan（无有效计划且存在可避免空闲）/ terminal。任何空闲都没有被新增为锚点间唤醒条件。以下数字不构成展示方案的采用决定。

依据：Phase S S1–S3；reviewed plan 二的 ledger / snapshot / cycle / metrics 模块、周期循环、M3–M4；long-run addendum 一.2/3/6/8、二.1/3。Phase S 明确授权本机已有 Mac 镜像数据、只读 SQLite 和 tokenizer；没有外部网络访问、模型调用或提交；既有合成 HTTP 测试仅使用 localhost。

## 输入与定义

G0：sealed2/fixture.json 与只读 contexts.sqlite，t=1649.8155803370928；P2：phase-m2-final-p2.json.ledger.jsonl.gz 的 702/1182/1602 首条 observation（seq 5295/5558/5948）；t=0：FullFabEnvironment(seed=0)。完整机器、route、release/due 来自同数据的公开 manifest。`physical/src/smt/environment.py:105–127` 从订单 START/DUE/REPEAT 构造 release/due 并放入 manifest；不是私有随机事件队列。

时间下界：uniform 用 m−offset，constant 用 c，exponential 用 0（无正下界）；均值另列 nominal_start。加工加固定 load/unload，再加**下一步的 transport**；这是 `_dispatch` (:212–218) 的真实归属。虚拟 Delay 同样计入链的时间但不成为可排生产工序。setup、排队、组批、故障、PM 下界均为 0。未观察到的 sampling<100 步骤仍列出、标 conditional，但对后序下界贡献 0；已观察 waiting 的当前步骤已通过抽样，仍计其加工时间。nominal 按不跳步、均值路径，无资源竞争保证。已有导出工序保留原 eligible set；未导出步骤用 source family 候选包络，不预测未来 dedication，不能将它当作实际资格保证。

执行中：对 G0，将公开 running_jobs 的 started_at/job/lot 与截至 now 的历史 dispatch 的 step/visit 连接；下一步界为 max(now, started_at + 当前步骤最短加工/load/unload/下一段运输)，再走虚拟及后续链。不读取未来 sampled end。P2 没有 running_jobs，首个 executing successor 用 now 弱界，nominal 使用其公开 release 预测。缺少旧 visit 历史的冻结尾部暂用名义 visit=1；未来返工重访不投影。未释放 lot 从公开 release 开始。

G0 同时重算“丢弃公开开始时间、全部用 now”对照。所有表均包含窗口内 physical ready、执行后继、后续链和新释放工作；不是只计算新增 upcoming，也不自动扣除已预留任务。beyond_export 包括深度截断以外的未来工作以及新释放 lot，不能全部解释为深度截断。

## S1：分布、窗口与成本

分布实测：`{"cadence": {"constant": 1668, "uniform": 2345}, "load_unload_extrema": {"load": [0, 60], "unload": [0, 60]}, "nonpositive_processing_minima": 0, "processing": {"uniform": 4013}, "transport": {"constant": 299, "uniform": 3714}, "virtual_processing": {"uniform": 147}}`。processing/transport 的 uniform 支持由 `dist_spec/draw` (:20–31) 核实；load/unload 是机器固定数值。calendar 的 exponential 不作为正下界，也不允许用它推导有限墙钟上界。

| 状态 | W 秒 | 工序 | ready / executing / later / unreleased | 不在当前导出 | 原 executing >H 现显示 | tokens E / D | 相对 G0 74 行增量 E / D |
|---|---|---|---|---|---|---|---|
| G0:1649.82 | 900 | 1208 | 1017 / 151 / 40 / 0 | 3 | 61 | 34513 / 25108 | 30977 / 22189 |
| G0:1649.82 | 1800 | 1553 | 1017 / 232 / 304 / 0 | 142 | 142 | 43022 / 32802 | 39486 / 29883 |
| G0:1649.82 | 3600 | 2441 | 1017 / 495 / 929 / 0 | 372 | 405 | 70669 / 57475 | 67133 / 54556 |
| P2:702 | 900 | 2410 | 1064 / 1112 / 234 / 0 | 0 | 1060 | 62998 / 52103 | 59462 / 49184 |
| P2:702 | 1800 | 3314 | 1064 / 1112 / 1138 / 0 | 134 | 1060 | 86851 / 73186 | 83315 / 70267 |
| P2:702 | 3600 | 4265 | 1064 / 1112 / 2089 / 0 | 333 | 1060 | 112919 / 96127 | 109383 / 93208 |
| P2:1182 | 900 | 2411 | 1046 / 1130 / 235 / 0 | 0 | 1017 | 68294 / 52821 | 64758 / 49902 |
| P2:1182 | 1800 | 3309 | 1046 / 1130 / 1133 / 0 | 134 | 1017 | 92234 / 73982 | 88698 / 71063 |
| P2:1182 | 3600 | 4254 | 1046 / 1130 / 2078 / 0 | 331 | 1017 | 118219 / 96820 | 114683 / 93901 |
| P2:1602 | 900 | 2415 | 1051 / 1125 / 239 / 0 | 0 | 1018 | 68629 / 53088 | 65093 / 50169 |
| P2:1602 | 1800 | 3299 | 1051 / 1125 / 1123 / 0 | 135 | 1018 | 91787 / 73580 | 88251 / 70661 |
| P2:1602 | 3600 | 4242 | 1051 / 1125 / 2066 / 0 | 331 | 1018 | 117782 / 96438 | 114246 / 93519 |
| SMT2020:0 | 900 | 2091 | 2091 / 0 / 0 / 0 | 0 | 0 | 49395 / 38579 | 45859 / 35660 |
| SMT2020:0 | 1800 | 2500 | 2091 / 0 / 409 / 0 | 71 | 0 | 60482 / 48453 | 56946 / 45534 |
| SMT2020:0 | 3600 | 3186 | 2091 / 0 / 1095 / 0 | 171 | 0 | 79360 / 65404 | 75824 / 62485 |

E=explicit，D=dense；tiktoken 0.14.0 / o200k_base，现有 compact grouping、family/set references、数值规范及默认值编码。载荷字段为 operation_id、earliest_start、nominal_start、batch_key、batch_min/max、setup、eligible reference、sampling_percent、conditional；readiness_basis 仅用于计数。成本包含独立 eligible_sets 段。参考 G0 74 行仅为 3536 / 2919 tokens；新整段还包括 ready 等行；其中当前未导出的 ID 尚不能按现有生产事实直接提交，本阶段没有改变导出或校验。因此增量不是保持原 ready 段后的最优增量，也不是直接替换生产快照的总成本。

| 状态 | W | 每 lot 深度→lot 数（含零） | 全部改用 now 的窗口工序数 |
|---|---|---|---|
| G0:1649.82 | 900 | {"0": 1008, "1": 1131, "2": 34, "3": 3} | 2449 |
| G0:1649.82 | 1800 | {"0": 927, "1": 1087, "2": 88, "3": 6, "4": 68} | 3363 |
| G0:1649.82 | 3600 | {"0": 664, "1": 955, "2": 343, "3": 124, "4": 22, "5": 68} | 4321 |
| P2:702 | 900 | {"1": 2011, "2": 96, "3": 69} | 2410 |
| P2:702 | 1800 | {"1": 1460, "2": 428, "3": 154, "4": 134} | 3314 |
| P2:702 | 3600 | {"1": 1009, "2": 578, "3": 359, "4": 127, "5": 103} | 4265 |
| P2:1182 | 900 | {"1": 2010, "2": 97, "3": 69} | 2411 |
| P2:1182 | 1800 | {"1": 1468, "2": 417, "3": 157, "4": 134} | 3309 |
| P2:1182 | 3600 | {"1": 1015, "2": 575, "3": 358, "4": 125, "5": 103} | 4254 |
| P2:1602 | 900 | {"1": 2008, "2": 97, "3": 71} | 2415 |
| P2:1602 | 1800 | {"1": 1478, "2": 408, "3": 155, "4": 135} | 3299 |
| P2:1602 | 3600 | {"1": 1023, "2": 571, "3": 354, "4": 125, "5": 103} | 4242 |
| SMT2020:0 | 900 | {"0": 86, "1": 2091} | 2091 |
| SMT2020:0 | 1800 | {"0": 86, "1": 1852, "2": 140, "3": 28, "4": 71} | 2500 |
| SMT2020:0 | 3600 | {"0": 86, "1": 1426, "2": 406, "3": 157, "4": 33, "5": 69} | 3186 |

深度分母为该状态已观察活跃 lot 加 release≤now+3600 的公开未释放 lot；在较短 W 尚未释放者也计深度 0。界包含 ≤ 边界。本次 15 个窗口中 unreleased first step 均为 0；公开 release 规则有合成测试，但不能把该数据上的零样本视为实测覆盖新释放场景。开始时间来源计数：`{"G0:1649.82": {"executing_lots_with_public_start_and_step": 1159}, "P2:1182": {"executing_lots_using_now": 1130}, "P2:1602": {"executing_lots_using_now": 1125}, "P2:702": {"executing_lots_using_now": 1112}, "SMT2020:0": {}}`。P2 的弱界膨胀不是实际可在窗口内完成的承诺。

### 最重要的有效性检查

从相同 seed=0、相同 86400 秒公开 manifest 的独立 **SmtEnvironment** 起步，controlled_machine_ids=()，随后把运行终点设为 3600，调用其原生 `advance()`。原生 outside policy 为 `setup-aware-priority-FIFO-demand-v1`（setup-aware、priority、FIFO、demand）。FullFab 的生产执行路径没有被改写或绕过；这是独立物理支持/覆盖验证，不是模型调度结果。所有实际 dispatch（含虚拟）记录在 `/tmp/v6orch/s-measure-final.json`；覆盖分母是 physical lot-operation starts，批次中每 lot 算一次，区间 (0,W]，t=0 的初始 dispatch 不计。

实际开工总数（含虚拟）305；可与同一 operation ID 下界比较 305；**早于下界的违反数 0**；运行中 rework 事件 0。未投影重访需单列，不能把缺失界算成通过。

| W | physical starts | virtual starts | 有可比界 | 物理窗覆盖 | 当前 visible 覆盖 | 当前 exported 覆盖 |
|---|---|---|---|---|---|---|
| 900 | 15 | 1 | 15 | 15/15 (100.00%) | 15/15 (100.00%) | 15/15 (100.00%) |
| 1800 | 83 | 9 | 83 | 83/83 (100.00%) | 45/83 (54.22%) | 83/83 (100.00%) |
| 3600 | 280 | 25 | 280 | 280/280 (100.00%) | 129/280 (46.07%) | 276/280 (98.57%) |

visible=unreserved_ready+upcoming(H=900)，exported=全部公开 problem.operations。完整 missing_from_window 列表和实际开工时刻均保存在测量 JSON，不能将支持界的覆盖率解释为准时率、吞吐或调度优劣。

## S2：字段与作业信息成本

逐行方案增加 due、priority、waiting_since、processing_seconds_min/max；processing 范围含固定 load/unload，不含 setup/transport。per_lot 把前三项放 lot 表，processing 范围仍逐工序；route_reference 用既有静态 routing 的 route/step + eligible machines 的 load/unload 恢复范围，lot 信息仍放动态表。没有删字段或改变值，explicit/dense 的 decode 后均断言与 normalize 后原值一致（沿用现有 compact 数值精度）。

| 状态 | CURRENT E / D | prefix E / D | 每 session 未缓存等价 E / D |
|---|---|---|---|
| G0:1649.82 | 60645 / 43817 | 94017 / 57335 | 70,046.70 / 49,550.50 |
| P2:702 | 46073 / 32214 | 94017 / 57335 | 55,474.70 / 37,947.50 |
| P2:1182 | 49350 / 34560 | 94017 / 57335 | 58,751.70 / 40,293.50 |
| P2:1602 | 48867 / 34016 | 94017 / 57335 | 58,268.70 / 39,749.50 |

等价输入 = CURRENT + 0.1×prefix（metrics.py:7,55）。假定 prefix 已全部命中缓存、一次 session 仅一个这种请求；冷缓存首次请求应加 0.9×prefix，工具多轮/额外 prompt/输出 token 不在此静态载荷估算中。P2 缺失 running_jobs 的成本是**不完整公开载荷**，不能理解为真实 factory 没有运行作业。

| 状态 | 方案 | 原始 token 增量 E / D | 等价/session 增量 E / D |
|---|---|---|---|
| G0:1649.82 | per_row | 46430 / 33721 | 46430 / 33721 |
| G0:1649.82 | per_lot | 57479 / 37820 | 57479 / 37820 |
| G0:1649.82 | route_reference | 56472 / 33941 | 56472 / 33941 |
| G0:1649.82 | running_jobs | 18197 / 15331 | 18197 / 15331 |
| G0:1649.82 | setup_transitions_min_runs | 274 / 238 | 27.40 / 23.80 |
| P2:702 | per_row | 47558 / 34788 | 47558 / 34788 |
| P2:702 | per_lot | 59073 / 38988 | 59073 / 38988 |
| P2:702 | route_reference | 58025 / 34854 | 58025 / 34854 |
| P2:702 | running_jobs | N/A | N/A |
| P2:702 | setup_transitions_min_runs | 274 / 238 | 27.40 / 23.80 |
| P2:1182 | per_row | 47667 / 35037 | 47667 / 35037 |
| P2:1182 | per_lot | 58999 / 39182 | 58999 / 39182 |
| P2:1182 | route_reference | 57959 / 35130 | 57959 / 35130 |
| P2:1182 | running_jobs | N/A | N/A |
| P2:1182 | setup_transitions_min_runs | 274 / 238 | 27.40 / 23.80 |
| P2:1602 | per_row | 48055 / 35411 | 48055 / 35411 |
| P2:1602 | per_lot | 59448 / 39595 | 59448 / 39595 |
| P2:1602 | route_reference | 58401 / 35516 | 58401 / 35516 |
| P2:1602 | running_jobs | N/A | N/A |
| P2:1602 | setup_transitions_min_runs | 274 / 238 | 27.40 / 23.80 |

除 setup_transitions_min_runs 为 cached prefix 增量，其他均为 uncached CURRENT 增量；每项独立测量，不保证简单相加等于组合编码的增量。现有 compact 按整行共同字段分组，增加 due 等逐 lot 差异会拆散原 group；增量包含这种重新分组的代价，不只是字段值的 token 数。

| 状态 | 仅增加字段（逐行） | CURRENT 与等价增量 E / D |
|---|---|---|
| G0:1649.82 | only_due | 30079 / 23692 |
| G0:1649.82 | only_priority | 920 / 119 |
| G0:1649.82 | only_waiting_since | 2296 / 609 |
| G0:1649.82 | only_processing_min_max | 3792 / 3984 |
| P2:702 | only_due | 30431 / 24606 |
| P2:702 | only_priority | 1178 / 300 |
| P2:702 | only_waiting_since | 1636 / 8 |
| P2:702 | only_processing_min_max | 3954 / 4164 |
| P2:1182 | only_due | 30811 / 24896 |
| P2:1182 | only_priority | 1162 / 310 |
| P2:1182 | only_waiting_since | 1591 / 28 |
| P2:1182 | only_processing_min_max | 3832 / 4029 |
| P2:1602 | only_due | 31076 / 25088 |
| P2:1602 | only_priority | 1118 / 281 |
| P2:1602 | only_waiting_since | 2099 / 416 |
| P2:1602 | only_processing_min_max | 3824 / 4019 |

running_jobs：连接历史公开 dispatch 获取 current_steps/current_visits；earliest_finish=max(now, started_at+最短加工/load/unload/下一段运输)，即物料到下一步的最早完成，setup/downtime 下界取 0。`intrinsic_latest_finish=started_at+已观察 setup+上述各阶段最大值` 是**不增加暂停的固有支持上端**。真正 `latest_finish=null`：未来故障、暂停或重叠停机没有公开有限上界，不伪造保证。P2 无 start/job 身份，作业字段成本记 N/A。G0 作业连接结果：`{"current_delta": 18197, "equivalent_delta": 18197, "jobs": 907, "known_step_jobs": 907, "roundtrip": true}`。

## S3：固定轨迹上的周期锚点回放

P2 时间 702→1602.0，900.0 秒，232 条 observation、232 个不同时间。它是一条既定计划历史，不是多个独立轨迹；存在 16 个计划版本。源 run 实际终点是 1603.1，trace 最后一项是 time_advance(1602→1603.1)；本表按有 ledger 观察的 900 秒归一化，不外推末尾 1.1 秒。积分与源 summary 的 1967.553613793293 machine-s 一致。当前规则复算与记录 avoidable_idle 不一致次数：0。伴随 trace 证据：`{"events_in_ledger_span": 657, "path": "/workspace/v6-mac-env/work/phase-m2-final-p2.json.trace.json", "rework_events_all": 0, "rework_events_in_ledger_span": 0, "time_end": 1602.0, "time_start": 0.0}`。

锚点从 702 起（包含起点及落在终点的锚点）；按短区间时长归一化，sessions/h 可能高于 3600/Δ，这是端点计数效应，不是长期频率；锚点的首条 ledger 已在提交/dispatch 之后，不能作为决策输入。702 从生成该轨迹所用 fixture.public_702 恢复并只读取得提交前快照；后续使用此前最后 observation，且逐锚点断言它与新 plan_committed 之间只有 time_advance、没有任何物理事件，才将时间推进到锚点重算 hold/ready。此外，对比锚点前后公开机器事实，并扣除该锚点新 dispatch 增加的 processing job 数，排除 trace 未显式记录的 wake/process_free；缺少证据或发现静默转换会报错，不静默插值。积分使用所有观测间左矩形，同刻采用最后状态；不使用未来状态插值。a=当前账本；b=仅取消 qualification_uncertain 的候选排除（same_machine_as/min-run/hold/batch/预留等保持）；c=b+观察到的 processing_until **成员数**检查，非 cascading 1 槽、cascading 2 槽；d=c+同一机器在上个锚点也 avoidably idle 才让 idle 条件触发，其他 needed 条件不变。

qualification 证据：`environment.py:186–196` 仅在当前 step 存在已记录 dedication 且机器不一致时排除；没有记录则允许 family 中的机器（仍服从忙/停机/min-run/槽位）。t=0 实测：`{"env_eligible_accepted": 2750, "family_machine_pairs": 2750, "lots_with_any_recorded_dedication": 0, "rejected": 0, "uncertain_observed_ready": 130}`。b/c/d 运行前检查该实测无 dedication 且全部 family-machine pairs 被 env.eligible 接受。此证据不宣称任意时刻的每台 family 机器都空闲。

| Δ | 变体 | 需要/锚点 | 比例 | sessions/h | 等价 tokens/h E / D | avoidable-idle machine-s | expiry<next | invalid |
|---|---|---|---|---|---|---|---|---|
| 60 | a | 16/16 | 100.00% | 64.00 | 4,482,988.80 / 3,171,232.00 | 1,967.55 | 0 | 0 |
| 60 | b | 16/16 | 100.00% | 64.00 | 4,482,988.80 / 3,171,232.00 | 1,967.55 | 0 | 0 |
| 60 | c | 16/16 | 100.00% | 64.00 | 4,482,988.80 / 3,171,232.00 | 1,967.55 | 0 | 0 |
| 60 | d | 0/16 | 0.00% | 0.00 | 0.00 / 0.00 | 1,967.55 | 0 | 0 |
| 300 | a | 4/4 | 100.00% | 16.00 | 1,120,747.20 / 792,808.00 | 1,967.55 | 0 | 0 |
| 300 | b | 4/4 | 100.00% | 16.00 | 1,120,747.20 / 792,808.00 | 1,967.55 | 0 | 0 |
| 300 | c | 4/4 | 100.00% | 16.00 | 1,120,747.20 / 792,808.00 | 1,967.55 | 0 | 0 |
| 300 | d | 0/4 | 0.00% | 0.00 | 0.00 / 0.00 | 1,967.55 | 0 | 0 |

观测时序陷阱：直接取锚点同刻首条 ledger，会得到所有变体 0 会话（结果保留在 `/tmp/v6orch/s-triggers-postdispatch.json`）；这不表示无需规划。trace 在 702 为 plan_committed seq5293 → dispatch5294 → ledger5295；1182 为 commit5554 → dispatch5555–5557 → ledger5558。真实机制运行 summary 记录 16 cycles / 16 sessions，输入为脚本化规划器而非模型。本文主表使用经 trace 验证的提交前状态。

anchor_decision 直接调用 `CycleMachine.begin(trigger=periodic)`：idle>0、invalid、valid_until<next_anchor、unresolved_failure；等于下一锚点不算提前到期。ledger 没有完整会话失败状态，unresolved_failure 假设 false；不虚构 finish、stall、失败重试或越级会话。expiry 与 invalid 计数是条件命中数，可能重叠，不是独立可相加的额外会话。d 不改变观察到的物理质量，故 machine-seconds 与 c 相同。尤其 d 的 0 不能解读为可行的零会话策略：固定历史中原有锚点计划已经持续清掉之前的开工机会；取消这些计划后，下一锚点的 idle 集合会不同。

tokens/h 统一用 S2 G0 的完整 job snapshot 每 session 等价成本，乘以 sessions/h；仅是假定一个请求/会话的场景算式。真实 MCP 轮次、缓存命中、后续 snapshot 大小未测量，不能当作实际费用。固定历史上的反事实会话本会改变后续状态，因此这些是**指示性计数，非因果效果或新策略质量结果**；锚点间 idle 是质量成本，不引入任何新唤醒条件。

## 验证、限制与待用户决定

新增合成测试覆盖 uniform 最小值、transport 归属、可跳步零贡献、observed waiting 不再抽样、执行 started_at+min、release、never<now、虚拟链、字段复原、同机 persistence、其他 trigger 条件不被 persistence 吞掉，以及 1/2 槽位、提交前观察 carry 必须没有物理状态转换；无真实模型调用。

测试结果与时间见下方最终核验记录。最初 sandbox plain suite 的两项 existing phase_p HTTP 测试因 socket PermissionError 失败；经自动审批开放 localhost 后重跑完整 suite，没有削弱或修改测试。

限制：冻结 P2 无公开运行作业开始时间；冻结 G0/P2 超出导出尾部的旧 visit 历史不完整；未来返工不投影；名义均值不含资源争用，不是保证；支持上界不等于墙钟完成上界；贪心 batch matching 非最优匹配；短冷启动覆盖试验不能代表长期稳态；CQT/Q-time 未实现。所有缺失信息保持 N/A/null。

待用户决定（本阶段没有采用任何选项）：W 取值及是否展示窗口；是否接受 ready/upcoming 重叠或另行定义展示拆分；额外字段采用哪种可复原表示；是否将公开运行作业 step/start/visit 正式纳入 P2 evidence；在后续获授权实验中如何比较不同 Δ 与质量成本。没有建议新增锚点间唤醒条件。

### 可复现命令与原始输出

在 V6 目录运行，Python 为本地镜像 venv；输出均写 /tmp/v6orch，不写封存证据。
```bash
export PYTHONPATH=src:/workspace/v6-mac-env/physical
export TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache
date -u
/workspace/v6-mac-env/venv/bin/python scripts/measure_physical_window.py --fixture /workspace/v6-mac-env/work/sealed2/fixture.json --database /workspace/v6-mac-env/work/sealed2/contexts.sqlite --public-ledger /workspace/v6-mac-env/work/phase-m2-final-p2.json.ledger.jsonl.gz --output /tmp/v6orch/s-measure-final.json
date -u
/workspace/v6-mac-env/venv/bin/python scripts/replay_triggers.py --public-ledger /workspace/v6-mac-env/work/phase-m2-final-p2.json.ledger.jsonl.gz --trace /workspace/v6-mac-env/work/phase-m2-final-p2.json.trace.json --initial-fixture /workspace/v6-mac-env/work/sealed2/fixture.json --measurement /tmp/v6orch/s-measure-final.json --output /tmp/v6orch/s-triggers-final.json
date -u
PYTHONPATH=src python3 -m pytest -q
git diff --check
git status --short
```

最终 S3 实跑读取最终 S2 文件；生成报告时再次断言每 session 成本与 S2 相同。route-reference 的静态解码信息另以 `/tmp/v6orch/s_roundtrip_verify.py` 核验，12,516 个 operation-variant rows 全部恢复一致（日志 s-roundtrip-final.log）。全部 15 个后续锚点又由 `/tmp/v6orch/s_carry_verify.py` 独立检查无静默机器转换（s-carry-final.log）；这两项只加强断言，不改变已测量的编码载荷或锚点计数。

日志：`/tmp/v6orch/s-measure-final.log`、`s-triggers-final.log`、`s-plain-final.log`。以下汇总与上表同源；date -u 为执行结束时间，非模拟时间。
```text
s-measure-final.log: Sun Oct 18 08:57:37 UTC 2026
s-triggers-final.log: Sun Oct 18 09:05:36 UTC 2026
s-plain-final.log: Sun Oct 18 09:03:27 UTC 2026
validity: 0 violations / 305 comparable starts; 305 total starts
W=900: physical=15, window=15, visible=15, exported=15
W=1800: physical=83, window=83, visible=45, exported=83
W=3600: physical=280, window=280, visible=129, exported=276
delta=60 a: 16/16 anchors need session; sessions/h=64.000000
delta=60 b: 16/16 anchors need session; sessions/h=64.000000
delta=60 c: 16/16 anchors need session; sessions/h=64.000000
delta=60 d: 0/16 anchors need session; sessions/h=0.000000
delta=300 a: 4/4 anchors need session; sessions/h=16.000000
delta=300 b: 4/4 anchors need session; sessions/h=16.000000
delta=300 c: 4/4 anchors need session; sessions/h=16.000000
delta=300 d: 0/4 anchors need session; sessions/h=0.000000
481 passed, 48 skipped, 38 subtests passed in 169.10s (0:02:49)
```

Phase R 的已有改动通过执行前后的逐文件 SHA256 对比保留。`git status --short` 原本已有 4 个修改中的 src 文件；“没有 src 修改”按 **本阶段没有新增修改**核验，而不是回滚 R 使 status 变干净。未提交 commit。

报告生成 UTC：2026-10-18T09:06:29.263722+00:00

最终收尾（2026-10-18 09:06:39 UTC）：`git diff --check` 通过；scope SHA256 检查 pre-existing changed=[]，仅新增批准的 3 个 scripts、1 个测试和本报告。最终补充 focused 验证为 14 passed（09:06:32 UTC）；编译通过。两项新增强化断言已分别在全部真实行/锚点验证，完整 suite 结果仍为 481 passed / 48 skipped / 38 subtests。原始 scope 清单：`/tmp/v6orch/s-scope-final.json`。
