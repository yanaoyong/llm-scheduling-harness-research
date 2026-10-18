# F1：工作可见范围与时间标签

研究日期：2026-10-18。覆盖审计待决问题 1、3、4；只研究，不批准或实施规则变更。下文“源码事实”“来源原文”“推断”“建议”分别标明证据性质。

## 一、证据与口径

本地根目录记为 `V6=docs/updates/2026-10-17/project/experiments/harness_v6_20261017`，`P=/workspace/v6-mac-env/physical`。`src/` 均相对 V6。计数来自[《Harness 过滤审计》](../../docs/updates/2026-10-17/project/experiments/harness_v6_20261017/reports/harness_filtering_audit_20261018.md)“实测汇总”，不是本次重跑结果；各谓词重叠，不能相加。P2 缺 running_jobs，不能解释成没有作业。

源码事实：`observation.py:166–211` 排除 done/unreleased，从 processing lot 的下一步起，按物理步骤截断，生成名义无跳步、无返工后继。`facts.py:11–17,106–123` 只有 machines/operations/tasks/holds，过滤仅 eq/contains；静态 route 不是可提交 operation 目录。`snapshot.py:60–69` 只展示执行中前驱、预计在 H 内、尚未预留的后继。它们形成三个不同集合：**物理上存在的工作、当前允许提交的实体、此次输入展示的实体**。

硬约束 1 应同时审查“当前可开工”与“可提前预留”：不能以 unknown_operation 拒绝证明某工作本来不该可见。done 排除符合物理事实；未来返工结果尚未发生则不能伪造确定 visit。以下“满足约束”均指拟议实现及其必要配套，不代表现状已合规。

### G0 为何是 2，P2 为何是 3

源码事实链如下：

- `/workspace/v6-mac-env/evidence/project/experiments/context_window_batch60_20261016/live_pilots/extended_three_group_final_segment_20261017/G0.config.json:9` 显式配置 `lookahead_depth:2`；`P/src/smt_fullfab/harness/runtime.py:211` 构建会话时传入配置值。
- `V6/scripts/audit_filters.py:20–25` 直接读取 sealed G0 的冻结 problem，并未用新默认值重建；27–32 行取 P2 ledger 对应时刻第一条 observation。
- 当前 `src/harness_v6/env_adapter.py:351–353` 的 ledger 调用无参数 `self.problem()`，421–424 行默认深度 3；`observation.py:130,187,229` 接收该值、按物理步计数。`scripts/run_public_physics.py:25–26` 也走该 ledger 路径。

结论：差异来自旧会话显式配置与公共 ledger 默认路径，不是 G0 的机器物理限制，也不是两种模型模式固有区别。审计中 G0 为 2,173 个 lot 各两步、3 个各一步；P2 为 2,166 个各三步、8 个各两步、2 个各一步。route 尾部不足深度解释少量短链。代码能证明配置来源，**找不到当初选 2 而非 3 的决策理由**；不能补写为“已证明 token 最优”。

## 二、问题 1A：每个 lot 看几步，还是看多久？

### 白话解释

例如甲 lot 的下两步各一分钟，乙的下一步要数小时。“每人看两步”会漏掉甲很快到来的第三步，却保留乙很远的第二步。按 15 分钟展示似乎更直观，但排队、组批与选机尚未决定，不能准确知道甲第三步何时到达。G0 有 1,159 条执行后继，仅 90 条预测落在 H=900 秒内，其中 16 条已预留，所以新展示 74 条；另外 1,069 条只可 MCP 查询。它们可能因预测偏差提前到料。[审计：A03、A09、S02及实测汇总]

### 文献与实际系统

来源原文：[《Heuristic Based Scheduling System for Diffusion in Semiconductor Manufacturing》](https://www.informs-sim.org/wsc09papers/158.pdf)，§5.1–5.3，Freescale 的 FaST 从 MES 提取 WIP、route、设备状态和预期停机信息，排程窗口 24 小时；提取的扩散区 lot 平均有 5–6 个加工步骤。论文把“未来几小时将进入扩散区的 lot”列为后续增强，不能将该增强说成已部署功能。

来源原文：[《Integrated RTS–RTD Simulation Framework for Semiconductor Manufacturing System》](https://www.informs-sim.org/wsc25papers/con144.pdf)，§5、表5，在 SMT2020/SMAT2022 实验中采用每小时生成计划、两天排程窗口。它是仿真研究，作者仍提出未来真实 fab 验证；两天不是行业推荐常数。

来源原文：[《Integer Programming-Based Real-Time Scheduler in Semiconductor Manufacturing》](https://www.informs-sim.org/wsc09papers/156.pdf)，引言区分针对给定作业/机器集合快速分派的 dispatcher，与计算一系列分配的 scheduler。[《A Survey of Problems, Solution Techniques, and Future Challenges in Scheduling Semiconductor Manufacturing Operations》作者上传稿](https://www.researchgate.net/publication/229423609_A_survey_of_problems_solution_techniques_and_future_challenges_in_scheduling_semiconductor_manufacturing_operations)也区分批处理、并行机、车间与辅助资源等问题，不能从一种子问题推出全厂统一前瞻深度。

推断：应分开保存“可发现范围、默认展示窗、计划有效期、重规划频率”。本仓库 `plan_seconds=14400` 只生成 horizon_end（`observation.py:240`），不代表已按四小时到料展开。未找到可靠来源证明实际 fab 通常统一采用每 lot 两步或三步；上述实例只能作为实验范围参考。

### 可选方案

| 方案与落点 | 约束1/2/3 | token、请求预期 | 难度、风险与验证 |
|---|---|---|---|
| A0 维持 A03/S02：深度2或3、H内展示 | 1不充分：窗外 single_action 无补查，深度外两模式均无实体；2有预测筛选风险；3未自动选机，但截断限制选择 | 增量0，保留查询成本 | 低；只能作为对照。抽查窗外提前到料与深度外引用失败 |
| A1 统一固定深度3，并加完整可发现目录/展开通道 | 配套完成后1可满足；2优先物理route；3满足，禁止排序推荐 | G0与P2分别4,349/6,516条，仅是规模参照，非同状态因果差。多约2千条若全展示，约十万token量级；只入后台不必增加输入。查询页可能增加 | 中高；多一步仍不是完整性证明。用同一物理状态生成深度2/3，比较实体覆盖与预算 |
| A2 时间窗作为展示分组，后台范围不按预测删除 | 1须有窗外及未知时间入口；2不因预测剥夺访问；3只分组不选任务 | 若将1,069条H外后继全搬入快照，按现有编码约增加4.2–5.1万token；分页全读至少3页，按eligible机器查询可能更少 | 中；未知时间不能悄悄归到窗外。测试H边界、估计耗尽和虚拟前驱 |
| A3 混合：固定小深度默认页＋按lot/route展开＋时间分组 | MCP在完整目录与可提交解析配套后满足1；single_action须另给可还原完整编码；2、3满足 | 摘要通常百至千token量级；展开按模型需求付费，无法预言请求减少 | 高；目录必须无优先级截断。对每lot验证默认页与剩余链覆盖、跨页稳定性 |

以上数量级仅为推算：74条 upcoming 实测 explicit 3,536、dense 2,919 token，即约48/39 token一条；不能把它当完整事实工具记录的单价，后者含版本封装及更多字段。A1 中约2千条的成本是假设采用相似行格式，不是预算测量。

**建议：选择 A3，先补全可发现性，再试验默认深度与 H。**固定步数控制体积比较容易，时间窗便于理解近期到料，二者都不适合成为永久访问边界。single_action 若放不下完整可还原表示，应明确记为受限观察实验或预算失败，不能宣称与 MCP 信息等价。[依据：上述源码、FaST及RTS–RTD论文；方案为本报告推断]

## 三、问题 1B：45 万未展开后续步骤与未投产 lot

### 白话解释

G0 有 456,117 个名义后续物理步骤没导出，不是当下漏掉45万件可开工任务，也不等于未来一定会做45万次：抽样跳步、返工会改变轨迹。t0 有50个 unreleased lot。若只告诉模型“以后还有很多工作”，模型既不能找某批的下一段，也不能合法预留。反过来，全部平铺会耗尽上下文。[审计 A01/A03/A07；`observation.py:167,193,208–212`]

### 业界如何处理

来源原文：[《Prediction of Lot Step Arrival Times in Semiconductor Manufacturing》](https://informs-sim.org/wsc20papers/071.pdf)，Applied Materials 的2019部署案例以 AutoSched 仿真平台为预测核心，完整运行输出厂内 lot 当前状态和预计设备到达时间，较频繁更新运行关注 hot lots 与 active WIP。它证明“当前状态与未来到达预测分层供给”有实践基础，**没有说明必须为每个远期步骤建立硬预留，也没有给出统一步数或小时数**。本任务禁止 harness 选优先级，不能照搬 hot-lot 选择机制。

来源原文：[《Heuristics for Order-Lot Pegging in Multi-Fab Settings》WSC摘要](https://www.informs-sim.org/wsc20papers/at_a_glance.html)讨论已释放 lot 配订单，并在不足时规划 wafer releases，表明未投产需求属于规划视野；这不证明本 harness 应提前锁定具体机器。来源原文：[《Effective Context Engineering for AI Agents》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)提出保留轻量标识、需要时由工具取回细节。**推断：计数＋指针可以压缩入口，但只有能实际展开的指针才构成可访问性。**

### 可选方案

| 方案与落点 | 约束1/2/3 | 成本预期 | 难度、风险与验证 |
|---|---|---|---|
| B0 维持A01/A03/F01，只给静态route | 1不满足广义可预留工作访问；2不泄露随机未来；3有范围代决策风险 | 无增量 | 低；保留unknown_operation失败对照，不能当完整目录 |
| B1 仅加计数及截断原因，`snapshot.py`/metadata注明未导出 | 1仍不满足，计数不等于通道；2、3满足 | 全局摘要约百token量级，0额外工具调用 | 低；只能缓解误读。验证模型能区分“隐藏”与“不存在” |
| B2 增加lots、route位置、public releases目录及按需物化 | MCP配套后1满足；single_action需可还原编码与相同解析器；2只使用公开投产表和名义route；3不选机、组批或排序 | 全展开456,117条按39–48 token约1,800–2,200万token；512条分页至少891页，因此不能要求全扫。按lot展开只付所读成本 | 高；要改A01/A03/F01、facts与plan_delta/normalize的实体解析边界。验证目录覆盖、可引用性、版本一致及未知未来不泄露 |
| B3 全部未来候选常驻实体并直接展示 | 1对名义链可满足；2须声明非确定结果；3无需替模型排序 | 千万token量级，现预算不可行，极易整会话失败 | 高；作离线完整性参照，不建议成为主输入。先离线量预算，无需模型调用 |

B2 的具体边界建议：已完工 lot 从活动目录移除，只留有界计数/近期引用；未投产 lot 标 `scheduled_unreleased`，公开投产时间不能标 actual；未知或尚未生成的未来需求显示 unknown。只读公开 release stream，禁止把私有事件队列、抽样结果当“事实”。物理端 `P/src/smt/environment.py:105–108,145–146` 分别建立 unreleased lot 与处理实际 release，支持两状态分离。

名义后继用 `route_ref + step + nominal_visit` 描述；明确 `conditional`、采样与返工规则，不预展开无限返工树。展开查询必须在冻结 observation 内确定、无排程副作用；同一个引用在验证和提交阶段应得到同一公开记录。当前 `facts.py:15,39–56` 以完整 problem 摘要与重构契约保证一致性，所以不能临时向 facts 塞几个实体却不更新契约。若只提供查询、仍一概拒绝新增ID提交，那只是信息修复，不是预留能力修复。

**建议：B2，但分开决定“可见”与“允许远期预留”。**先保证完整名义route和公开release可发现；是否开放长链预留由用户决定。若保持提交上限，必须如实标为动作空间限制，不能说硬约束1已在所有意义上满足。长链队首可能阻挡后来 ready 工作，排队顺序仍由模型负责，不让 executor 自动越过。[源码：`facts.py:106–162`、审计E01；外部依据见上]

## 四、问题 3：release=now 到底是事实还是占位？

### 白话解释与文献

G0有2,173条、P2有4,340条 `exported_predecessor` 把 release 写成 now；它们实际还依赖未排完的前一步。相当于“菜还没炒，却把上桌时间填成现在”。`observation.py:199–211` 同时写了前驱ID和basis，`ledger.py:29–31` 并未误判为ready，但工具原样返回数字，模型可能误读。另一个细节：observed_ready 的 release 也由 now 生成，不一定是历史上真实到料时刻；不能简单把现有值改名 actual_release_at。

来源原文：上述 AutoSched 案例明确区分 current status 与 expected arrival；2025 RTS–RTD论文§4分别建模预期 lot 到达与设备空闲时刻。未找到这些系统公开采用统一 `actual/estimated/unknown` JSON枚举的证据。以下字段是**本报告接口建议**，不是行业标准。

建议表达：`ready_now` 表示已观察状态；`observed_at` 表示观察时刻；只有真实事件支持才填 `actual_ready_at`。预测使用 `estimated_ready_at`、`estimate_basis`、`as_of`；未知用显式 null 与 `unknown_reason=predecessor_unscheduled`。`conditional` 和 `predecessor_ids` 独立保留，不把100%采样等同于确定到料。`earliest_possible_at` 仅在存在可证明下界时提供，均值不是下界。

### 可选方案

| 方案与落点 | 约束1/2/3 | 成本预期 | 难度、风险与验证 |
|---|---|---|---|
| T0 保留now与现有basis | 1不新增隐藏但继承前述缺口；2语义不可靠；3满足 | 0增量 | 低；用有前驱但release<=now的题检验误读 |
| T1 保留兼容数字，加`release_kind=placeholder`及说明 | 1同原范围；2改善但仍有双义数字；3满足 | 共享说明约百token；逐行标签若5–10 token，G0占位行约1.1–2.2万token，仅全读时发生 | 低中；适合迁移，风险是模型仍只看数字。两格式对照理解题 |
| T2 公共接口拆分observed/estimated/unknown，停止把now作为到料值 | 1不删实体；2满足，未知显式；3满足 | 可用列默认值压缩，可能与现有字段成本相近，必须实际编码测量；通常不增加工具调用 | 中高；同步A08/A09、ledger、snapshot、facts、compact及prompt消费方，避免null参与数值比较。测兼容与语义 |
| T3 为后续链递推ETA | 1须保留未知入口；2增加预测；3若暗中模拟选机排队则违反，纯加工时长只能标无排队情景 | 每行新增数值及basis，可能万token级；查询轮数不一定变 | 高；易把不含竞争的时间当承诺。与实际到料误差及预留阻塞比较 |

**建议：T2，T1只作兼容过渡，不默认T3。**不改执行器“等实际到料”的语义。`observation.py:95–127` 已区分 process_end、lot_available、machine_available，当前未完成作业均值耗尽会夹到 now+1；应额外标 `estimate_exhausted`，不能把“一秒后”说成可靠保证。历史实际值与将来估计都要带依据；没有校准数据时不给虚构置信区间。[源码及上述两篇系统论文支持状态/预测区分；字段设计为建议]

## 五、问题 4：running_jobs 与 jobs/metadata 查询

### 白话解释与来源

G0有907个running job，旧快照只有job、machine、lot_ids、started_at；当前 `factory_v6.py:123–127` 多了phase，但仍无当前step、逐job完成估计和下一步关联。cascading机器可能同时加工两批（`P/src/smt/environment.py:186–189`）；只见机器的processing_until列表，不能可靠知道每个结束时间属于哪一批。P2缺原始作业记录，不能事后靠猜测补成事实。

来源原文：FaST的MES输入、运行中lot分类和单lot流程报告支持状态关联展示；AutoSched案例提供逐lot状态与设备到达预测。**推断：本 harness 应提供job—lot—step—后继连接，而无需附加“应该先做哪个”的建议。**`facts.py:33` 保存了problem_metadata，109行却拒绝metadata kind；缺的首先是公开访问接口，不是所有信息都不存在。

### 可选方案

| 方案与落点 | 约束1/2/3 | 成本预期 | 难度、风险与验证 |
|---|---|---|---|
| J0 保持S04/F01 | 1不保证完整状态可知；2避免新预测但关联不足；3满足 | 0增量，模型可能多次反查 | 低；双job同机、transport阶段作为反例 |
| J1 快照直接补step/visit、三个时间语义及后继引用，metadata给最小说明 | 配合前文访问修复满足1；2真实字段与估计分开；3满足 | 假设每job新增20–40 token，907条约1.8–3.6万token/快照；无额外读请求 | 中；预算风险大。离线核对关联、编码与超预算率 |
| J2 增加jobs/metadata kind，快照给完整轻量目录与时间类型说明 | MCP满足访问；single_action必须同时获得必要字段；2、3满足 | jobs全读至少2页，metadata按命名记录取；少量精确ID可一批返回。不能把2次工具调用直接等同2次模型请求 | 中高；模型可能不知道该查。测目录发现率、查询成功及token/小时 |
| J3 混合：快照保留全部当前step/后继引用，估计明细及metadata按需取 | MCP满足；single_action另编码必要明细；2、3满足 | 假设引用新增10–20 token/job，约0.9–1.8万；dense共享列可能降低，尚未实测 | 中高；冗余估计易冲突。以同一forecast函数生成所有视图，检查相等 |

**建议：J3，并为single_action显式预算完整公共字段。**改动落点是 `factory_v6.py`/`observation.py`生成同源public jobs，`facts.py`扩展目录、重构与版本契约，`snapshot.py`/`compact.py`更新编码，MCP工具描述同步更新。metadata至少含lookahead、各范围计数、预测限制、unrevealed说明；setup/min_runs完整内容提供引用，具体排程规则留给其他主题。保留 `missing_from_source` 与 null，不能从模拟器私有未来process_end补“精确预测”。

## 六、实验与成本验收

外部LLM证据的适用范围有限：[《LLMs can Schedule》](https://arxiv.org/abs/2408.06993)研究JSSP监督数据与采样；[《ReflecSched》](https://arxiv.org/abs/2508.01724)报告直接LLM的长上下文利用不足与短视，并借助启发式模拟经验改善。它们没有证明本规模fab应选深度2、3或某个H；后者的策略模拟也不能未经批准塞进本harness。这里仅据此建议把“可见性正确”与“模型是否利用”分开验证。

本次未运行实验、长测试或模型API。后续建议先用冻结G0与三个P2状态做离线覆盖、解码与预算检查，再在获准实验中逐项比较，避免把时间标签、导出深度、触发器同时改掉：

1. 覆盖：当前可开工工序零遗漏；名义后继、公开未投产lot均能从入口定位；明确可提交范围。包含route尾部、虚拟前驱、返工、两个cascading作业与跨页引用。
2. 因果：不读取未来抽样值；修改隐藏随机未来时，当前公共事实不应变化。真实到料、估计、未知三类理解题分别记正确率，未知不可记成0。
3. 可比：同物理状态、相同规则与计划期限；single_action和MCP分别报告观察范围。若给单动作少字段，该结果测的是“模式＋信息差”，不能归因为工具本身。
4. 成本：按模拟小时报告 `Σ(未缓存输入token＋缓存输入token×已登记价格比)/模拟小时` 与模型请求数/模拟小时；工具调用数另列。实测缓存命中、查询结果回灌、失败重试和超预算会话都计入。未测唤醒频率前，不能从单快照增加量推算每小时净成本；更长预留可能减少会话，也可能因失效增加重试。
5. 长时：只保留当前活动目录、固定摘要、分页游标和有界模型笔记；已结束job/lot不累积进上下文。数十小时测试应检查固定WIP规模下输入不随运行时间增长。规划质量另记吞吐、到料后等待、预留失效和队首阻塞；不要只用当前保守idle计数验收可见性。

## 需要用户拍板的选择

| 待决问题 | 可选项 | 建议及必须确认的边界 |
|---|---|---|
| 1A：默认可见深度/时间窗 | A0现状；A1固定3；A2时间分组；A3混合展开 | A3；默认展示可有限，访问不可按预测截死；single_action是否接受受限实验须明示 |
| 1B：未导出链及unreleased | B0现状；B1仅提示；B2目录＋展开；B3全量 | B2；分别批准公开信息可见与远期预留能力，计数不能代替可用指针 |
| 3：release占位与未知 | T0现状；T1兼容标签；T2类型拆分；T3链式预测 | T2；actual仅来自事件，estimated不当硬约束，未知不填now |
| 4：jobs/metadata | J0现状；J1全补；J2全按需；J3混合 | J3；补job/step/后继关联，明细可查；两模式字段差异与预算独立验收 |
