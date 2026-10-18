# Harness 过滤审计（2026-10-18，Phase R）

本报告区分三层：**物理事实 F**（源数据/已观察模拟器状态）、**展示/近似 P**（harness 自定的导出、摘要、可行性估计）、**校验 V**（提交/执行约束）。调度决定仅属于模型。P 层隐藏工作可能等效于调度决定，需用户明确批准。以下只记录现状及风险，不提出采用哪项规则的建议。Phase R 没有修改既有过滤/物理/提交规则，唯一批准的展示新增是 upcoming_operations。

路径约定：以下 `src/harness_v6/` 内文件缩写为文件名；`physical:src/smt/environment.py` 指 `/workspace/v6-mac-env/physical/src/smt/environment.py`，它是只读物理依赖，不在 V6 内改动。代码位置对应本报告生成时的工作树。

## 证据、计数与可发现性约定

G0 使用 sealed2/contexts.sqlite 中 G0 t=1649.82 的冻结 problem/base_plan/execution_state；运行作业来自匹配 context_ref/time 的 fixture。P2 使用 `/workspace/v6-mac-env/work/phase-m2-final-p2.json.ledger.jsonl.gz`，每个时刻取文件中**第一条**冻结 ledger observation（seq 见数值表），不是重跑轨迹，也不是从 mixed_702 无规划推进。t=0 为 `FullFabEnvironment(seed=0)`，读取同一 SMT2020 数据，不进行生产调度。H=900。脚本不访问网络、不调用模型、不写证据库。

各规则的计数键见下文总表：均为独立谓词的计数，**互相重叠，不能相加**。静态资源总量由相同源 manifest 给出；动态项仅来自对应冻结 problem。未导出后续工序的数目为已导出 lot 最后一步之后的名义物理 route step 数，不包含可能的重复返工 visit，也不等同于未来必做工序数。P2 文件没有 running_jobs/私有 lot 状态，这些缺项记 null，不编造 0。涉及假设提交的“拒绝数”、未来实际漏单数、最优匹配差额无法从一个状态计数，注明 N/A；不把候选数伪装成拒绝数。

**精确查询约定（均为实际支持的调用）**：

- Q1 单工序完整事实：`read_entities({"kind":"operations","ids":["w100:228:1"]})`。可将 ID 替换为当前已知 ID；不传 fields 时保留完整 public record。
- Q2 执行中前驱后续：`read_entities({"kind":"operations","cursor":null,"count":512,"where":[{"field":"readiness_basis","op":"eq","value":"executing_predecessor"}]})`。后续页保留 where，cursor 换为返回的 next_cursor。**没有 gt/lte/range 功能**；“release 晚于 H”只能逐页读取后由模型比较。
- Q3 其他 basis：Q2 的 value 改为 `exported_predecessor` 或 `nominal_unplanned_route` 或 `observed_ready`。
- Q4 布尔限制：`read_entities({"kind":"operations","cursor":null,"count":512,"where":[{"field":"qualification_uncertain","op":"eq","value":true}]})`；conditional 同样形式。字段须存在于当前 catalog 的某个记录，否则 query_filter。
- Q5 设备完整事实：`read_entities({"kind":"machines","ids":[1212]})`；任务用 `{"kind":"tasks","ids":["d43-g"]}`；hold 用 `{"kind":"holds","ids":["h:0"]}`。
- Q6 已知机组可加工候选：`read_entities({"kind":"operations","cursor":null,"count":512,"where":[{"field":"eligible_machines","op":"contains","value":1212}]})`。这里不自动加 readiness/qualification 条件。
- Q7 任一已存在字段的 eq 是准确的类型值比较；filter 多谓词 AND，不支持 OR 或嵌套条件。无 filter 的初始 cursor 必须使用对应上下文的 cursor；`cursor:null` 仅在带 where 时自动从首项开始，不能假造通用 null 全目录调用。

“可提交”以下均指所述过滤本身不拒绝；完整提交仍须满足 V 类所有约束。`single_action` 会话没有 read_entities 工具机会（single_action.py 的输出协议），因而“可查询”实际只在 mcp_session 可用；静态 routing 仍在两种快照里。

## 逐项规则（所有现存过滤保持不变）

| ID / 位置 | 规则、层、输入依据 | 模型看见什么 / 如何发现 | 允许提交 / 指标与触发 | 实测计数键 / 具体风险 |
|---|---|---|---|---|
| A01 observation.py:166 | F 状态 + P 导出：done/unreleased lot 不导出工序。release stream 未展开 | snapshot、facts 都没有；静态 routing 有步骤但没有这些 operation ID；Q1 返回 entity_missing | unknown_operation 拒绝；不进 idle 需求 | t0 lot_statuses；其他状态私有 lot 缺失 N/A。近期新 lot 不可提前预留 |
| A02 observation.py:170 | F lot processing 状态（含尚未结束的运输阶段）；P 从下一步起导出，当前执行步骤不导出为 operation | 当前作业仅 running_jobs 摘要；后续可 Q2 | 不能再次安排当前执行工序；receipt/已派发排除重复 | executing basis；G0 running_jobs，P2 null。模型可能不知道运行批次当前具体 step |
| A03 observation.py:177、187；env_adapter.py:421 | P lookahead_depth 默认3，计数的是物理工序；到 route 尾端不足深度 | 最后导出工序之后的 ID 不在 facts/snapshot；静态全 route 仍在 prefix | 后续未导出 ID 被 unknown_operation 拒绝；不计 ready/idle | operations_per_lot、lookahead_depth、nominal_later_physical_steps_beyond_export。G0实际深度2，2173个lot各2步、3个lot各1步；当前P2默认3（2166个lot各3步）。不是物理最多2步；深度及尾端导致截断，不能提前完整安排长链 |
| A04 observation.py:179 | F family/physical 分类 + P 虚拟步骤折叠 | 虚拟步骤不成为 operation，累积 mean processing/load/unload/transport 到 delay/virtual 列；这些列只有 Q1，route 在 prefix | 虚拟资源不允许生产 task；由 env_adapter.py:95 _outside 自动处理 Delay | virtual_predecessors、virtual_successors；静态 virtual_delay_resources。模型可能忽略抽样/返工的虚拟中间步骤 |
| A05 observation.py:189 | F 已观察 dedication 限制 eligible_machines 到 known 单机 | snapshot 的机器集已收窄；Q1 qualification_basis 告知绑定 | 非绑定机组拒绝；idle matching 也受限 | observed_binding。若只看 family 而忽略 set，可能错配 |
| A06 observation.py:217 | P 未知历史绑定：qualification_uncertain；同计划已导出的来源则 same_machine_as | ready 区保留 uncertain 标志但不显示 basis/same_machine_as；upcoming 保留 uncertain；Q1完整 | normalize 不单独拒绝这两个标志；执行时重新验证 observed binding | qualification_uncertain、same_machine_as、ready_qualification_excluded。未知不等于不可能，却从 idle 候选剔除 |
| A07 observation.py:193、208 | P 名义 no-skip/no-rework 后续 visit；conditional 不仅指 sampling<100，所有非当前 waiting 步骤均 true | 默认 ready 区完全不出现；R2 executing 子集显示 conditional/sampling；Q1/Q3/Q4完整 | 允许预留 conditional；实际 skip/revisit 会失效 | conditional、sampling_below_100。100%抽样的后续步骤也可能 conditional；不能把两者等同 |
| A08 observation.py:199 | P 第一个导出步骤 release=ready+虚拟mean delay；后续 exported_predecessor 一律 now 占位，同时 predecessor_ids 指向前序 | Q1 **原样显示 now**，Q3可找所有；不在 ready/upcoming（后者只 executing） | 公共校验不按 release/predecessor 排拓扑；执行按实际 step/visit 等待 | placeholder_now、predecessor_ids。只读取 release 可能误以为后序已经到料 |
| A09 observation.py:95 | F 已观察 start/setup/elapsed downtime + P 均值剩余：process_end、transport、PM、repair；在执行中最少 now+1 | available_at/processing_until 在机器快照/Q5；后继 release 在Q1/R2；不暴露实际未来随机样本 | 预计时间不是硬约束，不阻止 when_ready；opportunity 秒数使用 forecast | executing_within_h/beyond_h、future_release。均值被耗尽时+1会反复估早；串行PM/运输波动影响预留 |
| A10 observation.py:145 | F 全 physical 机器（非 controlled 子集）；P 动态不导出 virtual | machines 包含忙、停机机器，不因 busy/down 再隐藏；静态 prefix 包含全部资源 | scope 必须全 physical；virtual 拒绝 | machines/static_total_machines/physical/controlled/uncontrolled。913不是总资源数；静态 family 若含额外资源需用显式set |
| A11 observation.py:162、245 | P unavailable_intervals 固定空列表；未来 public release/maintenance window 未展开；随机未来事件私有 | Q5仍为空；problem forecast_limitations 有说明，但 current没有该metadata | 当前 down 影响执行/idle；未来窗口不参与预测 | nonempty_intervals、interval_blocked。模型可能将空列表误解为未来保证可用 |
| L01 ledger.py:30 | P ready 仅 not conditional、无 predecessor、release<=now，三项必须同时满足 | unreserved_ready 用此口径；not-ready 并非不存在；Q1–Q4仍可见全部已导出工序 | 本函数不是提交拒绝条件；覆盖ready计数、idle触发均依赖 | ready/not_ready、future_release、predecessor_ids、conditional。可做未来预留的工序不触发规划 |
| L02 ledger.py:72 | P ledger 状态优先 receipt，再 done/running/invalid/reserved；未就绪且无owner也叫 ready_unreserved，但 ready=False | snapshot 要求 state 与 ready 双条件；pending 全部保留 invalid | reserved 工作不再计为无主 idle 候选；独立机会指标例外 | ready_unreserved/pending_tasks/invalid_tasks/base_operations_absent。单看状态名字会错判就绪 |
| L03 ledger.py:35 | F 当前忙/停机 + P 可用标志和半开区间过滤 idle | 所有机器仍在快照/Q5 | 不禁止提交到忙机；执行等机；idle 不计它们 | busy/down/unavailable_flag/interval_blocked/idle。机组预计很快释放也不触发当前idle |
| L04 ledger.py:42 | F eligible ID + P conservative exclusion：uncertain、same_machine_as 任一个即排除 | 不是删掉 facts；Q1/Q4/Q6可取 | 校验允许符合公开family/set的预留；idle低估可能性 | ready_without_any_eligible_machine、ready_qualification_excluded、ready_same_machine_excluded。未知绑定工作可能有合法机却不触发 |
| L05 ledger.py:46 | F min_left>0且min_setup不匹配就排除当前候选 | 机器快照/Q5包含min_left/min_setup；Q1 setup | 公共编译不完整模拟 min-run；实际物理 _validate 重查 | min_left_positive、min_setup_excluded_ops（任一eligible机对受限的工序数）。可能有其他合法机；不可当成全部不可做 |
| L06 ledger.py:51 | F batch_key/min/max + P 取字典序第一足够组、只取最小批量 | idle_matches只是见证，不是完整可行批集合；Q6可查全候选 | 模型可用其他合法组/更大批次；不限制提交 | idle_with_ready_candidates_but_no_batch、avoidable_idle。最小批/首组可能占用灵活工序导致后续专机被漏计 |
| L07 ledger.py:112 | P 机号升序贪心 maximal matching，used 防重复，不是最大匹配 | 只展示匹配结果，不展示所有未匹配组合；ready行未删 | 指标/锚点有无avoidable依据此近似；不替模型派工 | avoidable_idle；与最优差额 N/A（未解优化问题）。低估多个机组同时可开工 |
| L08 normalize.py:25；ledger.py:119 | 模型hold决定 + P 生效口径：until>now；conditional 要anchor已派发且本机队列空 | 所有holds含过期项进入snapshot/Q5；只生效者阻塞matching | 有效hold计 explicit_wait_idle，不计avoidable；过期无影响；不自动取消 | holds/expired_holds/held_machines/explicit_wait_idle。尾部hold在队列未清空时不生效，误读会低估可开工 |
| L09 ledger.py:135 | P reserved_but_earlier_startable只查其他空闲机，需同组可成批且原机延迟；available_at估计秒数 | snapshot诊断；不自动搬任务，Q5看原队列 | 不触发，只报告/积分；同机提前机会不在该集合 | opportunities。原机忙却估计now时潜在秒数0；不能等同无机会损失 |
| S01 snapshot.py:51 | P ready区只取 ready_unreserved且ready；字段投影不含 lot/step/visit、due、priority、durations、basis 等 | 只保留ID、eligible、batch、setup、release、uncertain；Q1可补，single_action不可补 | 已导出但未展示工序仍可提交；指标保持ledger | omitted_operation_fields 数组与 ready_unreserved。缺 due/priority 会影响优先级判断 |
| S02 snapshot.py:60 | 已批准P新增 upcoming：executing_predecessor、not ready、release<=now+H、无pending预留；不额外剔除conditional/uncertain | 两种格式均显示74等行；字段按批准清单，不含其他route/lot属性；Q2可查H外 | when_ready可提交；此展示不改变metrics/triggers/validation | upcoming、executing_reserved、executing_beyond_h。H边界是预测筛选，实际提前完成的H外工作仍可能被忽略 |
| S03 snapshot.py:77；delta_schema.py:38 | P pending_tasks全保留，但投影删machine/lot_ids/steps/visits；machine_orders保留分配和顺序；invalid单列 | ID在任务可见，完整 task Q5；operation Q1可能已缺失 | 不自动取消invalid；冻结/重排仍由模型明确处理 | pending_tasks/invalid_tasks/base_operations_absent。G0 stale任务会让仅添加新任务的delta被拒绝 |
| S04 factory_v6.py:123；snapshot.py:83 | P running_jobs只job/machine/lot_ids/started_at/phase（旧G0 fixture无phase）；snapshot透传 | finish estimate、next operation、当前step不在job行；Q2反查后继，Q5有机组processing_until但不是job映射；无 jobs kind | 无法用read_entities读取完整job；不限制合法后继预留 | running_jobs/running_job_fields；P2源无这些字段，N/A。多批cascading机上无法可靠关联每个结束估计 |
| S05 snapshot.py:77；facts.py:30 | P problem的setup_transitions/min_runs/horizon_end/lookahead/frozen_tasks/uncertainty/unrevealed/forecast_limitations/scope不作为current字段 | facts内部metadata保留但FactReader没有metadata kind；static route含setup_time，不等于完整old→new setup表 | 执行仍受实际setup/min-run；模型不能通过read_entities获得这些metadata | problem_metadata_not_in_current。只看route setup_time可能漏掉setup转换代价 |
| S06 snapshot.py:40、111 | P 历史只有固定digest；过预算fail closed，不截断工序 | 不提供历史事件可查询kind；receipt/model_notes可提供摘要；超限返回错误计数 | 不采纳新计划，走会话失败；不会静默只保留部分工序 | history 1 digest/状态；预算失败数N/A。本轮工序变多会导致整个会话无法开始 |
| C01 compact.py:15、205、253、310 | P 编码10位有效数字、共享route definition、family/set、machine继承/constants、dense defaults/alias；没有另删canonical实体 | 解码恢复全部字段/行，唯一数值归一化是浮点10位；ID/列表顺序保留 | 原始facts/校验仍用未舍入值；prefix路由是所有源route | roundtrip测试；丢弃实体=0。rounded时间不应当作精确freeze_until（footer给原time） |
| F01 facts.py:14、17、99 | P 可读kind仅machines/operations/tasks/holds；entities=原始problem/base记录 | route只在static prefix，非read_entities kind；无lots/jobs/metadata；所有已导出op可Q1 | 未导出工序不能凭route自行猜ID；提交unknown_operation | catalog计数对应operations/machines/base tasks/holds；其他kind数=0。知道route仍无法合法排尚未导出step |
| F02 facts.py:103、116、141 | P 查询由模型显式指定；最多512 ID或1..512分页；只eq/contains、最多16 AND谓词，fields投影由模型选 | 不排序优化/排名；missing仅当前catalog缺失，非done证明；absent_fields明确 | 请求超限拒绝，不暗中截前512；metrics不受查询影响 | 全catalog适用；实际请求拒绝数N/A。漏翻页/误读missing会丢工作 |
| V01 plan_delta.py:120、164；normalize.py:131 | V current observation身份、机器family/set、scope、ID唯一/不可复用、批大小/key | validate/submit有诊断；没有新增筛选后再交模型 | 不在observation拒绝；不因conditional/release/predecessor/uncertain单独拒绝 | 全operations/machines适用；base_operations_absent显示旧任务缺失。预留成功不代表现在可执行 |
| V02 plan_delta.py:141、185、210；normalize.py:94 | V 排除已dispatch任务；新任务完整machine_orders、move双侧队列；冻结JSON/prefix不改，仅invalid可cancel | pending与orders可见；task完整Q5；receipt报告冲突 | 自动填身份/host常量，不新增调度选择；保留原序不择优 | pending_tasks；冻结拒绝数N/A。新任务插入错误队列前缀会拒绝或造成阻塞 |
| V03 normalize.py:48、126、167；submit.py:106 | V plan有效期/冻结范围、optional hard not_before、hold边界；周期valid_until>=next_anchor+Δ | prompt/footer说明；校验失败只报违规 | 过去not_before保留；release估计不是硬约束；coverage短缺不拒绝 | 所有提交适用；假设拒绝数N/A。H是展示范围不自动等于valid_until |
| V04 submit.py:13、29 | P coverage只报ready计数+前50 sorted ID，非全部未覆盖；violations最多50详情，所有错误参与判定 | receipt明示truncated/counts；可离线从plan/problem重建，工具无错误列表分页接口 | coverage不拒绝；误差不影响所有违规的acceptance | ready_unreserved；G0见实测455 token基线（Phase Q）；其他错误列表N/A。前50不是优先级推荐，漏看truncated会忽视其余 |
| V05 submit.py:73、132；mcp_server.py:55 | V 状态版本/幂等ID/每会话一次成功/工具预算/进程成功与用量已知才采纳 | accepted不是已派发；持久submission也可能因会话失败不采纳 | 保留旧plan；两连败默认停止；不会用失败会话修补计划 | state静态不能计会话失败，N/A。误以为写文件即生效会错算覆盖 |
| E01 executor.py:23；env_adapter.py:215 | V 全队列invalid阻塞；模型队首原则，不搜索后续可做任务 | invalid_tasks/receipt可见；pending顺序全展示 | 不跳头/重排；skip/revisit/breakdown走plan_invalidated | pending_tasks/invalid_tasks。头部未来task使后面ready工作等待 |
| E02 executor.py:38、62；env_adapter.py:239 | F 实际waiting/status/step/visit、机ready/down；V min/max/资格/物理_validate | public预测不代替实际执行检查；Q1仅公开状态 | when_ready等真实到料机空，不以estimated release强制开工；hold/not_before/latest_start仍约束 | not_ready/busy/down与候选量；实际起动拒绝数N/A。预估释放早不保证按时起动 |
| M01 metrics.py:27、65；factory_v6.py:133；cycle.py:76 | P 按观测区间积分ledger gauges；机号贪心定义的avoidable，不是“所有空闲” | 快照给matches，不显示未匹配理由完整表；报表按小时归一 | 空锚点跳过；no_plan必须有avoidable；opportunity不触发；计划过期/invalid另有规则 | avoidable_idle/explicit_wait_idle/opportunities。保守剔除导致低估idle并减少模型发现机会；CQT未实现 |
| E03 physical:src/smt/environment.py:185、202 | F 并行processing容量：非cascading最多1，cascading最多2；_validate通过eligible再次检查。ledger.idle只看busy/down，不检查processing_until数量 | snapshot/Q5有processing_until与cascading，但无单独capacity reason | 可提前预留；实际开工受容量约束，ledger可行见证可能与此不同 | processing_capacity_full、idle_processing_capacity_full。机器已释放占用但processing槽满时可能误报可避免idle |
| E04 physical:src/smt/environment.py:180；observation.py:205 | F setup转换用显式step.setup_time或old/new全局表；无new setup或相同时0。ledger只检查min-run，不按换型时长排除 | ready/upcoming仅setup，Q1有setup_time；完整转换表不可read_entities查询 | 换型本身不禁止提交或idle见证，执行加setup时间 | setup_change_ops为至少一个候选机需换型的工序数；不等于不可行数。可能把换型长任务误当即时加工 |

## 表格之外的关键区分

`conditional=True` 与 `sampling_percent<100` 不同；executing_predecessor 通常同时 conditional。R2 没有让它们进入 ledger.ready，也没有改变 idle。`exported_predecessor` 的 now 是带前驱依赖的占位，read_entities 原样返回；只按 release<=now 查询并不能判定就绪。后续工序未导出与已导出但未显示是两类完全不同的缺失：前者没有当前可提交ID，后者可在 MCP 会话分页查到。

“913 台”是所有物理机器；控制范围由 FullFabEnvironment 将 controlled 设为 physical，没有额外未控制物理设备。源父类支持controlled子集但此路径覆盖为全部；旧父类背景生产策略未调用。Delay_32 仍由环境自动延时路径处理。busy/down/min-run过滤只作用于可行见证/执行，不删除机器快照行。

G0提交验证先保留旧plan只新增 w100:228:1，收到 `unknown_operation: w1099:308:1`（旧任务 d43-g 已不在observation）。测试delta显式取消 d43-g 后，when_ready新任务被compiler及Submitter接受，资格/conditional/预计release不构成拒绝。取消只在离线测试构造中明确写出，没有加入生产自动修复，校验代码没有改变。这个结论是公共编译/校验接受，不是未来dispatch或真实物理时刻保证。

## 实测汇总

以下为脚本实际输出，列按固定状态顺序排列；null=源缺项，非0。

| 计数键 | G0:1649.82 | P2:702 | P2:1182 | P2:1602 | SMT2020:0 |
|---|---:|---:|---:|---:|---:|
| avoidable_idle | 0 | 0 | 0 | 0 | 808 |
| base_operations_absent | 1 | 0 | 0 | 0 | 0 |
| busy | 753 | 812 | 773 | 754 | 0 |
| conditional | 3332 | 5452 | 5470 | 5465 | 4427 |
| controlled_physical | 913 | 913 | 913 | 913 | 913 |
| down | 5 | 4 | 5 | 5 | 0 |
| executing_beyond_h | 1069 | 1060 | 1017 | 1018 | 0 |
| executing_reserved | 16 | 0 | 0 | 0 | 0 |
| executing_within_h | 90 | 52 | 113 | 107 | 0 |
| expired_holds | 0 | 0 | 0 | 0 | 0 |
| explicit_wait_idle | 0 | 0 | 0 | 0 | 0 |
| future_release | 1159 | 1112 | 1130 | 1125 | 86 |
| held_machines | 0 | 0 | 0 | 0 | 0 |
| holds | 0 | 0 | 0 | 0 | 0 |
| idle | 160 | 101 | 140 | 159 | 913 |
| idle_processing_capacity_full | 0 | 0 | 0 | 0 | 0 |
| idle_with_ready_candidates_but_no_batch | 5 | 5 | 5 | 5 | 0 |
| interval_blocked | 0 | 0 | 0 | 0 | 0 |
| invalid_tasks | 0 | 0 | 0 | 0 | 0 |
| lookahead_depth | 2 | 3 | 3 | 3 | 3 |
| lots_with_export | 2176 | 2176 | 2176 | 2176 | 2177 |
| machines | 913 | 913 | 913 | 913 | 913 |
| min_left_positive | 25 | 25 | 25 | 25 | 0 |
| min_setup_excluded_ops | 160 | 250 | 250 | 252 | 0 |
| nominal_later_physical_steps_beyond_export | 456117 | 454067 | 454042 | 454005 | 455091 |
| nonempty_intervals | 0 | 0 | 0 | 0 | 0 |
| not_ready | 3332 | 5452 | 5470 | 5465 | 4427 |
| observed_binding | 0 | 0 | 0 | 0 | 0 |
| operations | 4349 | 6516 | 6516 | 6516 | 6518 |
| opportunities | 3 | 0 | 0 | 0 | 0 |
| pending_tasks | 23 | 0 | 0 | 0 | 0 |
| physical_machines | 913 | 913 | 913 | 913 | 913 |
| placeholder_now | 2173 | 4340 | 4340 | 4340 | 4341 |
| predecessor_ids | 2173 | 4340 | 4340 | 4340 | 4341 |
| processing_capacity_full | 559 | 569 | 565 | 559 | 0 |
| qualification_uncertain | 166 | 159 | 159 | 159 | 176 |
| ready | 1017 | 1064 | 1046 | 1051 | 2091 |
| ready_qualification_excluded | 125 | 99 | 99 | 99 | 130 |
| ready_same_machine_excluded | 0 | 0 | 0 | 0 | 0 |
| ready_unreserved | 1011 | 1064 | 1046 | 1051 | 2091 |
| ready_without_any_eligible_machine | 128 | 102 | 102 | 104 | 130 |
| running_jobs | 907 | null | null | null | 0 |
| same_machine_as | 0 | 0 | 0 | 0 | 0 |
| sampling_below_100 | 731 | 1276 | 1278 | 1275 | 1105 |
| sequence | null | 5295 | 5558 | 5948 | null |
| setup_change_ops | 330 | 494 | 499 | 504 | 518 |
| static_total_machines | 1313 | 1313 | 1313 | 1313 | 1313 |
| time | 1649.8155803370928 | 702 | 1182.0 | 1602.0 | 0 |
| unavailable_flag | 0 | 0 | 0 | 0 | 0 |
| uncontrolled_physical | 0 | 0 | 0 | 0 | 0 |
| upcoming | 74 | 52 | 113 | 107 | 0 |
| virtual_delay_resources | 400 | 400 | 400 | 400 | 400 |
| virtual_predecessors | 20 | 26 | 24 | 25 | 86 |
| virtual_successors | 37 | 90 | 87 | 88 | 88 |

各 basis / 每lot导出分布、字段缺失原样如下：

### G0:1649.82

```json
{
  "omitted_operation_fields": [
    "binding_origin_step",
    "conditional",
    "conditional_virtual_successors",
    "due",
    "family",
    "initial_virtual_predecessors",
    "lot_id",
    "occupation_seconds",
    "predecessor_ids",
    "priority",
    "processing_seconds",
    "qualification_basis",
    "readiness_basis",
    "remaining_work_seconds",
    "rework_percent",
    "sampling_percent",
    "setup_time",
    "step",
    "terminal",
    "transport_seconds",
    "visit",
    "waiting_since"
  ],
  "operations_per_lot": {
    "1": 3,
    "2": 2173
  },
  "problem_metadata_not_in_current": [
    "forecast_limitations",
    "frozen_tasks",
    "horizon_end",
    "lookahead_depth",
    "min_runs",
    "schema",
    "scope",
    "setup_transitions",
    "uncertainty",
    "unrevealed"
  ],
  "readiness_basis": {
    "executing_predecessor": 1159,
    "exported_predecessor": 2173,
    "observed_ready": 1017
  },
  "running_job_fields": [
    "job",
    "lot_ids",
    "machine",
    "started_at"
  ]
}
```

### P2:702

```json
{
  "omitted_operation_fields": [
    "binding_origin_step",
    "conditional",
    "conditional_virtual_successors",
    "due",
    "family",
    "initial_virtual_predecessors",
    "lot_id",
    "occupation_seconds",
    "predecessor_ids",
    "priority",
    "processing_seconds",
    "qualification_basis",
    "readiness_basis",
    "remaining_work_seconds",
    "rework_percent",
    "sampling_percent",
    "setup_time",
    "step",
    "terminal",
    "transport_seconds",
    "visit",
    "waiting_since"
  ],
  "operations_per_lot": {
    "1": 2,
    "2": 8,
    "3": 2166
  },
  "problem_metadata_not_in_current": [
    "forecast_limitations",
    "frozen_tasks",
    "horizon_end",
    "lookahead_depth",
    "min_runs",
    "schema",
    "scope",
    "setup_transitions",
    "uncertainty",
    "unrevealed"
  ],
  "readiness_basis": {
    "executing_predecessor": 1112,
    "exported_predecessor": 4340,
    "observed_ready": 1064
  },
  "running_job_fields": []
}
```

### P2:1182

```json
{
  "omitted_operation_fields": [
    "binding_origin_step",
    "conditional",
    "conditional_virtual_successors",
    "due",
    "family",
    "initial_virtual_predecessors",
    "lot_id",
    "occupation_seconds",
    "predecessor_ids",
    "priority",
    "processing_seconds",
    "qualification_basis",
    "readiness_basis",
    "remaining_work_seconds",
    "rework_percent",
    "sampling_percent",
    "setup_time",
    "step",
    "terminal",
    "transport_seconds",
    "visit",
    "waiting_since"
  ],
  "operations_per_lot": {
    "1": 2,
    "2": 8,
    "3": 2166
  },
  "problem_metadata_not_in_current": [
    "forecast_limitations",
    "frozen_tasks",
    "horizon_end",
    "lookahead_depth",
    "min_runs",
    "schema",
    "scope",
    "setup_transitions",
    "uncertainty",
    "unrevealed"
  ],
  "readiness_basis": {
    "executing_predecessor": 1130,
    "exported_predecessor": 4340,
    "observed_ready": 1046
  },
  "running_job_fields": []
}
```

### P2:1602

```json
{
  "omitted_operation_fields": [
    "binding_origin_step",
    "conditional",
    "conditional_virtual_successors",
    "due",
    "family",
    "initial_virtual_predecessors",
    "lot_id",
    "occupation_seconds",
    "predecessor_ids",
    "priority",
    "processing_seconds",
    "qualification_basis",
    "readiness_basis",
    "remaining_work_seconds",
    "rework_percent",
    "sampling_percent",
    "setup_time",
    "step",
    "terminal",
    "transport_seconds",
    "visit",
    "waiting_since"
  ],
  "operations_per_lot": {
    "1": 2,
    "2": 8,
    "3": 2166
  },
  "problem_metadata_not_in_current": [
    "forecast_limitations",
    "frozen_tasks",
    "horizon_end",
    "lookahead_depth",
    "min_runs",
    "schema",
    "scope",
    "setup_transitions",
    "uncertainty",
    "unrevealed"
  ],
  "readiness_basis": {
    "executing_predecessor": 1125,
    "exported_predecessor": 4340,
    "observed_ready": 1051
  },
  "running_job_fields": []
}
```

### SMT2020:0

```json
{
  "lot_statuses": {
    "unreleased": 50,
    "waiting": 2177
  },
  "omitted_operation_fields": [
    "binding_origin_step",
    "conditional",
    "conditional_virtual_successors",
    "due",
    "family",
    "initial_virtual_predecessors",
    "lot_id",
    "occupation_seconds",
    "predecessor_ids",
    "priority",
    "processing_seconds",
    "qualification_basis",
    "readiness_basis",
    "remaining_work_seconds",
    "rework_percent",
    "sampling_percent",
    "setup_time",
    "step",
    "terminal",
    "transport_seconds",
    "visit",
    "waiting_since"
  ],
  "operations_per_lot": {
    "1": 2,
    "2": 9,
    "3": 2166
  },
  "problem_metadata_not_in_current": [
    "forecast_limitations",
    "frozen_tasks",
    "horizon_end",
    "lookahead_depth",
    "min_runs",
    "schema",
    "scope",
    "setup_transitions",
    "uncertainty",
    "unrevealed"
  ],
  "readiness_basis": {
    "exported_predecessor": 4341,
    "nominal_unplanned_route": 86,
    "observed_ready": 2091
  },
  "running_job_fields": []
}
```

G0：1,017 ready，3,332 not-ready = 1,159 executing + 2,173 exported_predecessor；执行后继中90条预计≤H，16条已预留，新增展示74条；1,069条预计>H只可查询。P2 upcoming为52/113/107。t0 的86条 nominal_unplanned_route来自当前虚拟步骤前驱，R2不展示它们。各状态尚未导出的名义后续物理step均超过45万，不能把4349/6516条public operation理解为所有未来工作。

G0新section token实测（tiktoken 0.14.0，o200k_base；保持完整字段及既有10位有效数字协议）：

| 项 | explicit | dense |
|---|---:|---:|
| upcoming操作数 | 74 | 74 |
| section tokens | 3536 | 2919 |
| 相同快照只移除此section的增量tokens（含eligible_sets差异） | 3536 | 2919 |

本例family/set全部复用已有引用，所以增量等于section计量。高于任务中≈1.4k的预估；此处逐组保留release、sampling、conditional、qualification等字段及协议开销，未为了符合预估删除信息。数值是payload tokenizer计量，不是模型调用费用或理解结果。

A/B四状态生成384题/16次计划请求（8题型×12×4，重复2次/格式）；每状态upcoming题12个独立目标，6 present + 6 absent。keys来自canonical decoded对象；P2 ledger无running_jobs，因此题集只有该源可提供的字段，已在runbook说明。没有运行真实模型理解实验。

复现命令（V6目录，使用已配置离线物理依赖/缓存）：

```bash
export PYTHONPATH=src:/workspace/v6-mac-env/physical
export TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache
/workspace/v6-mac-env/venv/bin/python scripts/audit_filters.py --fixture /workspace/v6-mac-env/work/sealed2/fixture.json --database /workspace/v6-mac-env/work/sealed2/contexts.sqlite --public-ledger /workspace/v6-mac-env/work/phase-m2-final-p2.json.ledger.jsonl.gz --horizon-seconds 900 --output /tmp/v6orch/r-audit-verified.json
/workspace/v6-mac-env/venv/bin/python scripts/measure_compact_snapshot.py --fixture /workspace/v6-mac-env/work/sealed2/fixture.json --database /workspace/v6-mac-env/work/sealed2/contexts.sqlite --output /tmp/v6orch/r-tokens-verified.json
date -u
```

### 风险汇总

| 边界 | 是否有当前可提交operation ID | 可发现渠道 | 本阶段处理 |
|---|---|---|---|
| ready但投影缺due/priority等字段 | 有 | MCP Q1；单动作只能现有快照 | 仅报告 |
| executing≤H且未预留 | 有 | 新upcoming + Q2 | 已批准新增 |
| executing>H / exported前驱 / nominal虚拟前驱 | 有 | MCP Q2/Q3，pending若已预留 | 仅报告原过滤 |
| lookahead以外 / unreleased lot | 无 | 静态route描述，不存在operation实体 | 仅报告 |
| conservative资格/组批/hold匹配 | 多数有 | ready/pending、Q1/Q5/Q6 | 仅报告；指标/触发不变 |
| jobs/metadata无查询kind | 不适用 | 部分快照、静态prefix；不可补查完整metadata | 仅报告 |


## 用户待决定的问题（只列问题，不替用户选择）

1. 每lot的既有lookahead上限、done/unreleased排除、名义skip/rework展开，以及metadata/operation字段投影，分别是否批准作为展示规则？是否需区分“未导出ID”与“已导出但只可查询”的显式提示？
2. qualification_uncertain、same_machine_as、conditional 的保守idle排除是否符合预期？是否接受由这些规则共同决定空周期跳过？
3. exported_predecessor 的 release_time=now 占位是否可继续作为工具事实展示？模型需要怎样的标签才不会混淆实际到料？
4. running_jobs 不含完成估计/下一步/当前step，且无 jobs/metadata 查询kind，是否为批准的展示边界？
5. 全局setup转换表、min_runs、未来公开release/maintenance信息不在当前快照/可读实体中，是否符合用户希望的知情范围？
6. 贪心最小批见证与机号顺序是否可作为“可避免空闲”的统计/触发近似？是否接受 held 工作独立计量以及仅跨机的earlier-startable口径？
7. 单动作会话不能补查已导出但未展示字段，与MCP会话可分页查询的差异是否已经纳入实验解释？
8. 新批准的H窗口以预计而非确定release筛选；未来是否需要其他展示变更，须另行明确批准。本报告未实施任何这些待决项。
