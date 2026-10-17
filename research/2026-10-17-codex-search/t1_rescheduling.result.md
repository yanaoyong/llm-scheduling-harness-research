**调研判断：你们更适合采用“周期滚动排程＋重大事件例外触发＋执行层实时派工”的混合架构。** 单纯扩大上下文，难以解决触发口径、计划覆盖和执行语义带来的调用膨胀。

下文用“**来源明确**”表示文献或官方资料直接支持的结论；用“**设计推断**”表示针对你们 harness 的建议。检索覆盖经典框架及 2023—2026 年研究；数值案例均注明适用范围。

## 一、重排策略：关键在于何时值得重新决策

**来源明确：周期、事件驱动、混合是重排政策，计划修复与完整重建则是重排方法，两者应分别选择。** Vieira、Herrmann、Lin 的框架还区分：实时派工通常在资源需要作业时，根据当前信息选择任务；预测—反应式排程先建立计划，再更新计划。因此，“设备完成加工后需要下一任务”并不天然意味着必须重新生成全厂计划。来源：[《Rescheduling Manufacturing Systems: A Framework of Strategies, Policies, and Methods》](https://doi.org/10.1023/A:1022235519958)。

| 政策 | 工作方式 | 主要权衡 |
|---|---|---|
| 周期重排 | 在固定模拟时刻重新排程 | 合并普通变化、减少计划扰动；严重异常可能响应较慢 |
| 事件驱动 | 指定事件满足条件后重排 | 响应及时；低门槛可能导致频繁重排 |
| 混合重排 | 周期更新，重大异常提前打断 | 同时需要周期参数和异常影响判据 |

上述分类与权衡见 [《A survey of dynamic scheduling in manufacturing systems》](https://doi.org/10.1007/s10951-008-0090-8)。**设计推断：**你们现在的“任何机组可开工但无计划立即触发”，属于门槛很低的事件驱动；即使保留周期计时器，也可能几乎没有机会按周期运行。

**来源明确：事件驱动不等于每个事件都重排，也不存在普遍最优的重排频率。** Church 与 Uzsoy 在单机、并行机动态到达模型中发现，选择性事件驱动可以用少于连续重排的次数获得高质量计划；利用到达过程结构，也能设计有效的周期政策。这些结果不能直接当作 900 台设备晶圆厂的性能保证。来源：[《Analysis of periodic and event-driven rescheduling policies in dynamic shops》](https://doi.org/10.1080/09511929208944524)。

**来源明确：滚动时域应区分“多久重排一次”和“向前计划多远”。** 一个 2026 年、基于全球半导体制造商光刻区的案例，每小时重排，计划时域为 1.5 小时；任务通常加工 10–20 分钟，系统有 13 台设备。论文明确要求计划时域长于重排间隔，以避免机器缺少后续任务。这是区域案例，不是全厂标准。来源：[《Scheduling with constraint programming in the dynamic and stochastic environment of a semiconductor photolithography area》](https://link.springer.com/article/10.1007/s10696-026-09666-5)。

## 二、频率、计划稳定性与冻结区

**来源明确：只优化延期、产出等效率目标，可能生成与上版差异很大的计划。** 稳定性研究不仅统计重排次数，还考虑任务开工时间变化，以及变化距当前时刻的远近；临近执行的修改通常更有扰动。来源：[《Dynamic rescheduling that simultaneously considers efficiency and stability》](https://www.sciencedirect.com/science/article/abs/pii/S0360835203000950)。

因此，应区分三件事：调用次数下降、计划修改减少、生产绩效改善。它们需要分别测量，不能互相替代。**这是根据上述稳定性研究作出的评估设计推断。**

**来源明确：冻结区用于保护已经向现场承诺的近期计划，冻结区外可用偏离旧计划的惩罚项保持连续性。** 通用 APS 厂商 SmartFlow 的说明强调，冻结长度应跟随备料、人员安排等实际承诺提前量；过短不能保护执行，过长会妨碍异常响应。这是通用制造实践，不能视为晶圆厂冻结参数的证据。来源：[《Plan Stability: Frozen Horizons and Schedule Nervousness》](https://dynamicspro.ca/help/smartflow-aps/learn/frozen-horizon-and-plan-stability/)。

**设计推断：**离线仿真没有纸质派工单等全部现场成本，但仍有已经开工、开始换型、占用辅助资源等承诺。宜采用：

- 已开工及不可中断换型：硬冻结。
- 近期已分配但尚未执行：保持设备和相对顺序，可允许必要时间顺延。
- 较远任务：允许重排，并惩罚无收益的换机、换序。
- 故障或硬约束失效：只解冻受影响范围，并记录原因。

## 三、晶圆厂实践：实时派工与优化排程配合使用

**来源明确：晶圆厂问题包含批处理、并行机、重入流程和辅助资源等多类耦合约束。** Mönch 等的综述并未把全厂调度归结为单一排序问题。派工规则综述则指出，规则是该行业常用的现场控制工具，先进规则会使用上下游信息。来源：[《A survey of problems, solution techniques, and future challenges in scheduling semiconductor manufacturing operations》](https://link.springer.com/article/10.1007/s10951-010-0222-9)、[《A survey of dispatching rules for operational control in wafer fabrication》](https://doi.org/10.1080/09537287.2010.490014)。

**来源明确：工业产品同时保留实时规则派工与优化排程。** Applied SmartFactory 的实时调度产品执行规则式派工；其高级排程产品明确表示两者都需要，并使用上下游实时数据更新 lot、设备及光罩计划。这证明两种能力可以互补，但产品页没有披露 LLM 调用政策。来源：[《Real-Time Scheduling & Reporting For Semiconductor Manufacturing》](https://appliedsmartfactory.com/productivity-solutions/real-time-scheduling-reporting/)、[《Semiconductor Manufacturing Advanced Scheduling》](https://appliedsmartfactory.com/productivity-solutions/advanced-scheduling/)。

**来源明确：公开工业参数中，计划跨度可以远长于更新间隔。** Applied 的验证框架文章描述：工厂计划覆盖 **12–24 小时**，通常每 **5–10 分钟至 1 小时**刷新，取决于加工周期、产品组合及运营方式。文章还要求检查“有合格可用 WIP 的正常设备是否未获分配”，以及活跃 lot 的当前、未来步骤是否遗漏。来源：[《Using a framework to validate factory scheduling solution systems》](https://appliedsmartfactory.com/semiconductor-blog/scheduling/scheduling-solution-systems-part-1/)。

班次排程也有历史案例：Vieira 等综述记录了半导体**测试设施**每班开始生成计划的做法；不能据此推导现代前道晶圆厂通常按固定班长重排。**本次未找到可信公开证据，支持统一的全厂班次周期或冻结区长度。**来源：[《Rescheduling Manufacturing Systems》](https://doi.org/10.1023/A:1022235519958)。

## 四、哪些事件立即处理，哪些可以合并

**来源明确：动态排程综述列举的异常包括设备故障、紧急任务到达、取消任务和优先级变化；混合政策允许常规事件等待周期，异常提前触发。** 来源：[《A survey of dynamic scheduling in manufacturing systems》](https://doi.org/10.1007/s10951-008-0090-8)。

**设计推断：**应按“等待到下次周期的后果”分级，不能只按事件名称判断。

| 处理级别 | 建议判据 | 动作 |
|---|---|---|
| 立即处理 | 故障使近期承诺不可执行；紧急 lot 等到下周期会违反硬期限；Q-time 即将超限 | 先局部修复，必要时调用模型 |
| 合并处理 | 普通完工、普通到料、短暂停机且队列仍有余量、小幅优先级变化 | 更新状态，留待下周期 |
| 确定性处理 | 已承诺任务到料后可启动、完成任务移出队列、软开工下界过期 | 执行层处理 |

这里“立即处理”仍不必等于“立即调用 LLM”。判断故障影响范围、重新检查资源可用性、执行既定备用规则，都可以由代码完成。

需求去抖也应采用模拟时间：首次出现普通缺口后累计一小段时间，合并同机组、同批次相关事件；设置高低阈值形成滞回。**本次未找到 SMT2020 文献给出可直接照搬的 LLM 缺口去抖参数，这属于工程建议。**

## 五、SMT2020 与近期研究能支持什么

**来源明确：SMT2020 原始论文提供四种仿真模型，基础场景为高产量低混合、低产量高混合，另外两种加入工程批次。** 它适合研究生产与工程 lot 的联合派工；模型名称本身不规定重排周期。来源：[《SMT2020—A Semiconductor Manufacturing Testbed》](https://doi.org/10.1109/TSM.2020.3001933)。

2023 年研究分别探索了自监督＋强化学习排程，以及使用 ASP 做较大范围多目标排程。它们表明学习式派工和前瞻优化都值得比较，**不能证明无状态 LLM 应逐事件调用**。来源：[《Semiconductor Fab Scheduling with Self-Supervised and Reinforcement Learning》](https://arxiv.org/abs/2302.07162)、[《Hybrid ASP-based multi-objective scheduling of semiconductor manufacturing processes》](https://arxiv.org/abs/2307.14799)。

**来源明确：2025 年可扩展性研究同时比较开放模型与工业数据，指出随机种子和仿真实现会显著影响结果；开放模型上的收益不能直接外推工业场景。** 这支持你们增加独立轨迹、保留同条件基线。来源：[《Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs》](https://arxiv.org/html/2505.11135v1)。

## 六、对我们问题的可借鉴做法

以下具体参数均为**建议的实验起点**，不是文献给出的 SMT2020 最优值。

### 1. 对应问题①：建立真正的周期滚动机制

固定周期锚点为 `t0 + kΔ`，异常重排后也保留原周期；周期内由执行层消费已提交队列。先比较 `Δ=60、180、300` 模拟秒，计划跨度试 `H=3Δ、6Δ`，结合工序时长调整。900 秒实验只适合验证机制，应另做更长运行评估生产效果。

普通事件去抖可先试 10–30 模拟秒；重大事件绕过冷却期。若引入备用规则派工，应单独报告其贡献和使用次数。

依据是前述 [《2026 年光刻区滚动排程案例》](https://link.springer.com/article/10.1007/s10696-026-09666-5)与 [《Applied 工厂计划验证框架》](https://appliedsmartfactory.com/semiconductor-blog/scheduling/scheduling-solution-systems-part-1/)；它们支持分离周期与计划跨度，具体秒数是本报告推断。

### 2. 对应问题②：统一“缺口”，避免按设备重复统计需求

建立全局工序账本，身份至少包含 `lot_id、route_step、visit/rework_index`，避免重入工序混淆。定义：

\[
U(t)=R(t)\setminus\bigl(X(t)\cup A_{\mathrm{valid}}(t)\bigr)
\]

其中 `R` 是物理就绪且存在合格设备的工序，`X` 是执行中工序，`A_valid` 是具有有效承诺的工序。另建未来就绪集合供前瞻计划使用。

同一工序即使适配十台设备，也只能产生一份未覆盖需求。触发、输入、校验与评估必须调用同一个集合计算函数；将空闲设备与 `U` 做可行匹配，再判断可利用容量。

同时单独检查“已分配但长期不能启动”：错误预留不能永久消除缺口。该账本和匹配算法是设计推断，依据是 [《Applied 验证框架》](https://appliedsmartfactory.com/semiconductor-blog/scheduling/scheduling-solution-systems-part-1/)要求同时检查设备和 lot 的分配完整性。

### 3. 对应问题③：明确软时间语义，自动规范化

将“不得早于某时刻”与“必须按时开工”分开。软下界已过去、任务仍等料时，保留任务身份、设备和顺序；物料到达后重新计算可行开始时间：

\[
s=\max(t_{\mathrm{now}},t_{\mathrm{not\_before}},
t_{\mathrm{material}},t_{\mathrm{machine}},t_{\mathrm{aux}})
\]

未知到料时间应保留为条件守卫，不能虚构时间。顺延后仍须检查设备冲突、Q-time 和硬期限；确认提交前展示规范化后的计划及变化摘要。

这是结合 [《Vieira 重排框架》](https://doi.org/10.1023/A:1022235519958)中的顺延、局部修复方法作出的设计推断；未找到文献直接规定你们这种校验器协议。

### 4. 对应问题④：按可执行时长检查覆盖深度

提交计划时输出每个机组的覆盖终点、预计耗尽时间，以及无法覆盖的原因。检查未来 `Δ` 内是否存在“有可加工需求、设备有容量、却无有效承诺”的区间；不能仅要求每台设备排若干条任务。

先保证近期可执行队列，再规划后续工序；对批处理与辅助资源联合校验。可先试冻结长度 `F=0、0.25Δ、0.5Δ`，比较换序、换机和延期，已开工任务始终硬冻结。

覆盖时长依据 [《2026 年光刻区案例》](https://link.springer.com/article/10.1007/s10696-026-09666-5)；冻结参数是实验建议。

### 5. 对应问题⑤：跨进程保存事实与决策状态

每次调用主动附带：状态版本、当前承诺、执行中任务、有效分配、未覆盖需求、上次拒绝及修复摘要、下次周期时刻。工具结果保存“内容摘要＋引用＋适用状态版本”；静态规则可长期复用，动态结果随状态失效。

**来源明确：**LangGraph 官方文档提供 checkpoint 与持久 store，并指出内存保存器不能跨进程重启保留状态；Anthropic 建议压缩上下文、持久化结构化笔记。来源：[《LangGraph Persistence》](https://docs.langchain.com/oss/python/langgraph/persistence)、[《Effective context engineering for AI agents》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)。

具体状态字段是本报告推断。你们每次查询都额外消耗一次模型调用，因此高频必需信息适合主动注入。

### 6. 对应问题⑥：拆开指标，并控制实验变量

同时报告未覆盖就绪工序数量与等待时长、存在可行任务时的设备空闲、吞吐量、延期、Q-time 违规、计划变动，以及查询／提案／确认／拒绝调用数。保留已有“缺计划等待”，但补充独立于承诺账本的机会损失检查。

先固定策略修复缺口口径和时间语义，再比较周期，随后比较时域、冻结与上下文组织。起步可用 5 个仿真种子，每个条件重复 3 次模型轨迹；有希望的方案再扩展。使用相同初始快照和外生事件流，记录模型版本及采样配置。

依据是 [《2025 年派工可扩展性研究》](https://arxiv.org/html/2505.11135v1)揭示的种子敏感性，以及 [《2026 年光刻区案例》](https://link.springer.com/article/10.1007/s10696-026-09666-5)采用多次重复和置信区间的做法；上述重复数量是成本受限的起点。

最后，因模型思考时模拟时钟暂停，调用耗时不会直接造成生产等待。调用数、重发 token 和墙钟时间应作为计算成本单列；900 秒内 56–69 次调用也应先拆为多少次独立重排、每次用了多少查询和修正，才能确定主要收益来自触发政策还是交互协议。**这是根据你们运行机制得出的推断。**