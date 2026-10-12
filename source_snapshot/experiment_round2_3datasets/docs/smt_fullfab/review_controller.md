# B/C 控制器独立审查与证据归属

审查日期：2026-10-09。审查读取新命名空间的控制器、分页、预算、通道、执行器及其保存记录；审查本身没有调用真实模型或求解器。合成文件夹具只用于测试，不计入 A/B/C 研究运行。物理投影对照单独使用短窗口环境测试，也不作为方案性能样本。

## 已定位与修复的关键问题

1. **C 的分解动作可能实际执行全局求解。** 初始控制器从 `decomposition` 导入 `solve_plan`，该名称实际是该模块从 optimizer 导入的全局函数。现分支改为 `solve_decomposed_plan`，结果保存 `requested_method`。独立证据审计还要求模型选择、求解参数、实际模块/函数、求解结果的模型版本和显式 apply 相符，不能只依靠方法名称标签。
2. **阶段预算不应仅由每次 run 的局部参数控制。** 原入口允许覆盖窗口和调用上限，也未按同方案跨 run 累计。当前入口在创建环境前拒绝超出已批准窗口/方案次数的请求；新 ledger 的 reservation 增加用途/方案/窗口上下文，并按阶段累计分类限额。已存在的早期授权调用只按明确保存的旧 run 身份兼容，不重置或返还预算。独立审计按账本事件顺序检查全阶段、分类、未知 usage、token 和 pending 停止条件。
3. **冻结承诺可能因经过当前时刻而无法保留。** 未开工冻结任务的原 not_before 可以早于新观察时刻。现审计只对上次计划中仍未执行、仍处于冻结区、同一任务 ID/内容/相对机上顺序的精确保留例外放行；不能借此添加新的过去任务或更改已执行历史。
4. **观察窗口裁剪可能悄悄改变 B 的机上顺序。** 例如同机显式序列 `[T1:not_before=40, T2:not_before=5]`，观察窗末 20；原计划在窗内没有生产，逐任务删除 T1 却会使 T2 开工。现在按每机已提交顺序从首个窗外任务起裁掉整个后缀，并把相同等待意图投影为到窗末的 hold；有保留前缀时，hold 仅在前缀执行后激活。多个相同激活条件的 hold 取等待区间并集。原始计划、排除任务 ID、预测窗口和投影版本均保留。

三个独立短仿真测试分别核对 `[40,5]`、`[0,40,5]` 以及初始 plain hold 与尾部 conditional hold 合并的情形。原 80 秒未来计划与 20 秒观察投影在 `[0,20)` 的实际生产派工完全相同。它验证本次修复的具体反例，不声称穷举证明所有计划均等价。

## 直接排程与求解器增强的责任边界

B 的任务、批成员、机台、开始条件、sequence 和 hold 必须来自对应模型 JSON。按模型显式给出的 `(machine,sequence)` 排列属于解码，不计算质量分数、不新增任务、不替换机台。跨页同族/同机若需要之前选择的信息，可以向模型回传它自己已给出的任务和等待；这不允许由工具补齐遗漏任务。每个合法投影后的实际派工仍必须通过计划来源和物理事件审计。

C 可以选择共享求解方法与参数，随后查看结果并明确 apply。求解器生成的未排工作、显式 hold、局部失败和候选状态应保持可见；工具返回 FEASIBLE 不等于整厂全部 lot 都有未来计划。统计必须区分模型逻辑 solve 请求、分解内多个 CP-SAT 调用和实际墙钟成本。正式排名之前仍需冻结 A/C 共享的具体算法与资源配置。

分页应完整保留 problem 中所有设备族、机器和纳入滚动窗口的 operation；不通过优先级、交期或最优候选过滤。跨页前序关系仍由模型或共同优化模型负责，执行器不能替 B 优化或补排。所有未排工作和显式等待最终反映到覆盖诊断、吞吐、WIP 与累计逾期，不能把“任务未被自动接管”写成“每个任务均已服务”。

## 独立控制器证据审计

`src/smt_fullfab/controller_audit.py` 只解析文件，不导入 controller、environment、optimizer 或模型通道，也不执行冻结源码。冻结提示词通过受限 AST 字符串读取；非结构化追加建议或未声明输入段会被拒绝。对失败调用也核对实际输入是否来自保存的完整分页，不能因为没有提交计划就忽略其上下文和成本。

检查链包括：

- request 的 prompt/schema/config 指纹、模型原始事件、final JSON、result、call_id、token/墙钟字段与追加式账本对应；成功调用不得包含 native tool 事件。
- B 的完整 page 与 problem 逐字段对应、每个 operation 恰一次、模型 output 与 patch 精确相等，只有显式 sequence 排序、operation ID 展开和已声明窗口投影。
- C 的每次模型 solve 与 solver_request 参数/方法对应，共享求解模块/函数和结果版本匹配，保存候选、反馈、显式 apply，最终 raw plan 等于被明确选择的候选。失败和未被采用的 solver attempt 也检查，不能只查看成功最终计划。
- 每个 trace 中的 plan_committed 必须有模型决策、raw plan、committed plan 的准确关联；仅有 owner=plan 或 run.status=success 不足以证明模型归属。

新运行使用 `controller_decisions.jsonl`、`solver_evidence.jsonl` 与 `plan_commits.jsonl` 明确连结模型调用、分页/轮次、求解器账本身份、候选及计划 SHA256。旧记录缺少必要链接时返回 `audit_status=partial` 和具体缺件，不补写旧原始日志、不伪造认证。

当前控制器的 commit 行仅保存最终模型 call_id 与两份计划哈希。审计从完整 solve→候选顺序→显式 apply 链重建 `source_candidate_index` 和 `source_solver_index`，输出到 `reconstructed_plan_attributions`；这两个冗余字段不强求写入原始行，但若存在则必须与重建结果一致。C 的 `FEASIBLE_HEURISTIC` 可以作为待明确 apply 的候选，审计要求保留名义可行性记录、原 incumbent 任务、局部 CP 结果和分解中采用启发式的族清单；不得附带全局最优或全局 bound 声明。所有回传给 C 的目标、限制、状态、任务预览与未排数也必须等于保存的求解结果。这里检验证据归属，实际可行性仍由物理与机会审计判定。

用户后续明确回复“豁免次数与用量限制”形成独立的 C 窄范围授权修订。控制器证据审计逐条重放追加式 `scoped_limit_waiver`，核对原批准哈希、批准时未知 usage 的原 finish 行哈希、批准文字及唯一 amendment_id；只有修订之后、scenario 1701、3,600 秒窗口的 C reservation 可豁免次数、已知 token 与未知 usage 的准入停止条件。B 和早于批准的 C 不受益，pending 仍停止。旧计数、未知 finish 与活动耗时不清零；C 单次 timeout 必须不超过 180 秒及全阶段剩余模型活动时间，累计模型活动时间的准入上限仍为 2,700 秒，C 逻辑求解器请求预算仍为 60 秒。`max_calls=null` 只在该运行的已发生调用都有先行有效豁免时接受。原始模型 config/timeout、reservation metadata、account_before 与实际结果同时核对。合成正反例测试不写入真实批准账本。

`audit_status=passed` 的含义是保存的控制器证据一致。一个真实失败且证据完整的运行可以得到 passed，同时 `run_status=failed`、`successful_full_window=false`。物理约束、完整窗口和合法需求覆盖需另用 `audit_trace` 检查，不能用控制器证据通过代替研究成功。

## 实际失败记录复核

已只读核查 `runs/smt_fullfab_stage2/B_1701_1h_probe_v1`：4 个真实模型 attempt 均有对应 request/result/原始事件与预算记录，B 未调用求解器，未提交任何生产计划；第 4 次模型请求超时，运行保存失败并停在仿真时刻 0，端到端耗时约 652.68 秒。该记录的控制器证据检查通过，但它不是完整 B 排程结果，更不能用来比较 B 的生产质量。模型账单金额未知仍为 null。

### compact v1 边界修正与 v2 全字段审计

后续复核发现 compact v1 并非完整无损表示：它覆盖全部设备与 operation 的核心定长字段，却省略 problem 的 `uncertainty`、`unrevealed`、`forecast_limitations`、`frozen_tasks`、`lookahead_depth` 等元信息，machine 的当前忙闲/故障与可用性说明，以及 operation 的采样、返工、资格不确定性、虚拟前后序、等待起点等信息。v1 也没有认证字段缺失与 null 的区别、实体数组的原始全局顺序。因此前文“逐字段对应”的历史含义限定为 v1 已声明的核心列和实际保存的模型输入一致，不能解释为全部 problem 字段均已传递。

旧 B 输入、输出和 v1 复核文件保持原样。新增 [B 控制器复核 v2](../../artifacts/smt_fullfab_history/B_1701_1h_probe_v1_controller_review_v2.json) 仍给出 `audit_status=passed`、`run_status=failed`、`successful_full_window=false`，同时明确 `all_saved_problem_pages_lossless_certified=false`，逐类列出未表示字段。这是证据结论边界的修正，不是给旧 B 补写新输入或将其升级成完整实验。

新 compact v2 保存完整 `problem_metadata`，机器与操作行带原始数组 `source_index`，extras 同时保留未编码字段和缺失列表；lot_id、step、visit 明确存列，资格列表只在精确等于族内完整设备列表时采用声明的字符串 sentinel。`controller_audit.py` 自行重建完整 JSON，不导入 interface 的 encoder/decoder，并与原始 problem 及 UTF-8 canonical SHA256 核对。它检查元信息镜像、缺失/null、原顺序、连续唯一源索引、跨页同族词典一致性，拒绝 extras 覆盖、未引用词典内容和未声明 metadata。C 的初始 STATE_DIRECTORY 中完整顶层 metadata 必须精确匹配；read_page 返回的 page 和 schema 也必须匹配保存的完整观察。

轻量回归覆盖未知扩展字段、缺失/null、删改采样/返工/机器状态、元信息遗漏、跨页源顺序、重复索引、词典混入建议及篡改 C 顶层信息。另只读使用已保存 A_v4 初始 problem 的 913 台机器和 4,352 个 operation，经新编码得到 8 页后，由独立 inverse 全字段核对通过；这不新增仿真、模型或求解器调用，也不替代后续真实 C 的归属与物理审计。

## 复现

```sh
.venv/bin/python -m unittest tests.test_smt_fullfab_metrics tests.test_smt_fullfab_audit tests.test_smt_fullfab_controller_audit tests.test_smt_fullfab_controller_review -v
.venv/bin/python -m src.smt_fullfab.controller_audit runs/smt_fullfab_stage2/B_1701_1h_probe_v1
```

测试覆盖模型 patch 被改写、B 出现 solver 证据、缺少 commit 链、prompt 指纹被改写、原始 token 与账本摘要不符、不完整 attempt、C 误用求解方法/权重/缺失显式 apply、冻结任务保留和观察投影反例。后续真实 C、更多预算、完整 1/8/24 小时 A/B/C 成本验证及正式协议仍需独立证据，不能由这些测试替代。
