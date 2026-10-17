# 动态排程与 LLM Agent 实验的评估方法调研

本文用 **【来源明确】** 标注文献或官方资料直接支持的内容，用 **【设计推断】** 标注针对你们 harness 的建议。检索覆盖经典重排研究及 2023—2026 年论文、工业资料和 Agent 工程文档。下文的参数扫描值均为实验起点，不是 SMT2020 标准参数。

## 一、评估应同时覆盖生产结果、计划稳定性和决策成本

**【来源明确】** 重排研究长期区分“生产效率”和“计划稳定性”。前者包括完工时间、流动时间、延误和等待；后者包括开工时间偏移、机器重新分配、任务顺序变化。重排策略还应区分周期式、事件式和混合式，以及局部修复与完整重建。[《Rescheduling Manufacturing Systems: A Framework of Strategies, Policies, and Methods》](https://cepac.cheme.cmu.edu/pasi2011/library/henning/ReschedulingFramework-VieiraHerrmannLin.pdf)；[《Multi-Objective Production Rescheduling: A Systematic Literature Review》（2024）](https://www.mdpi.com/2227-7390/12/20/3176)

**【设计推断】** 你们应建立三层指标表，避免“零缺计划等待”成为唯一成功标准：

| 层次 | 建议指标 | 主要回答的问题 |
|---|---|---|
| 生产结果 | throughput、平均及 P95 cycle time、加权 tardiness、按期完成率、时间平均 WIP | 工厂是否运行得更好 |
| 计划与执行 | 可加工未分配工序、可避免空闲、计划覆盖时长、计划变动量、重排次数 | 改善来自什么机制 |
| Agent 成本 | 调用、token、费用、真实耗时、拒绝率、重复查询率、失败轨迹比例 | 改善需要付出多少成本 |

生产指标的选取有半导体基准依据；将计划缺口与 Agent 成本联合记录，是针对你们问题的扩展。[《SMT2020—A Semiconductor Manufacturing Testbed》](https://doi.org/10.1109/TSM.2020.3001933)；[《AI Agents That Matter》（2024，后发表于 TMLR）](https://arxiv.org/abs/2407.01502)

**【设计推断】** 稳定性建议至少记录三个量：共同未执行工序的平均开工时间偏移、改机比例、删除或新增承诺数。比较时只纳入两版计划共同覆盖的时间区间；新增远期任务单独记账。否则，覆盖更深的计划会因为任务更多而被误判为更不稳定。此定义是对上述稳定性指标的工程化细化，并非文献规定的统一公式。

## 二、半导体指标与 SMT2020 基准的使用边界

**【来源明确】** SMT2020 包含四类模型：高产量低混合、低产量高混合，以及分别加入工程批的两个扩展。原论文建议：实现模型后先收集 throughput、cycle time，并对低产量高混合模型收集按期完成情况，与补充材料结果接近后，再研究新的控制算法。其工程批案例使用两年仿真、剔除一年预热，并做 **20 次独立重复**；这些是该案例的设置，不是所有实验必须遵循的规定。[《SMT2020—A Semiconductor Manufacturing Testbed》](https://doi.org/10.1109/TSM.2020.3001933)

**【来源明确】** 2023 年的 SMT2020 排程研究采用每次六个月、100 个随机 seed，按批次类型报告按期率和 cycle time 的均值、标准差，并与层次式 CR、FIFO 比较。[《Semiconductor Fab Scheduling with Self-Supervised and Reinforcement Learning》](https://arxiv.org/pdf/2302.07162)

**【设计推断】** 因此应把实验拆成两种用途：

- **短窗诊断**：保留 900 秒场景，检查触发、重复查询、规范化、队列耗尽和调用开销。
- **长期生产评估**：从相同预热快照出发，覆盖足够多的完工批次及扰动；可先试一周、一个月，再根据有效样本量扩展。

短窗中的完成工序数可以作为诊断指标，但不能替代成品 throughput。只统计短窗内完工批次的 cycle time，也可能偏向原本就快完成的批次；必须同时报告期末 WIP、在制批年龄和未完工数量。该建议由上述长周期实验及完成批口径推导。

**【来源明确】** 工业方案同样强调多目标和实时状态。Applied Materials 的实时派工方案使用规则管理瓶颈产出、批次分组和交期；高级排程方案持续使用上下游工厂数据。[《SmartFactory Real Time Scheduling & Reporting》](https://appliedsmartfactory.com/productivity-solutions/real-time-scheduling-reporting/)；[《SmartFactory Advanced Scheduling》](https://appliedsmartfactory.com/productivity-solutions/advanced-scheduling/)

**【设计推断】** 利用率应按瓶颈组、非瓶颈组报告，并同时给出“加工时间／日历时间”和“加工时间／可用时间”。等待也应拆成等料、等机、等批、等资格、主动等待和调度遗漏；高利用率本身不足以证明排程更好。

**【来源明确】** 2025 年研究指出，即便使用相同数据集，仿真引擎和随机 seed 也会造成差异；SMT2020 与真实工业数据在产品组合、设备专用资格等约束上仍有距离。[《Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs》](https://arxiv.org/html/2505.11135v1)

**【设计推断】** 对你们约 900 台机组的版本，应固定记录数据集编号、筛选规则、设备数量、加工及运输时间语义、故障和维护设置、批处理规则及仿真器版本。原论文所列 [Testbeds Data Sets 入口](http://p2schedgen.fernuni-hagen.de/index.php?id=simulation&L=1) 本次未成功访问，无法确认当前下载包版本。

## 三、随机性、重复试验与消融设计

**【来源明确】** Agent 单次成功不能代表稳定可靠。τ-bench 提出 `pass^k`，衡量同一任务重复执行时全部成功的可靠性；Anthropic 的 2026 年工程文档也明确区分任务、试验、轨迹和评分器，并建议对随机输出进行多次试验。[《τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains》（2024）](https://arxiv.org/abs/2406.12045)；[《Demystifying evals for AI agents》（2026）](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**【设计推断】** 你们至少有两层随机性：工厂的到达、故障、加工波动，以及模型的动作选择。建议先做 **5 个工厂 seed × 每个 3 次模型重复** 的试验性评估；关键比较扩至 **20 个工厂 seed × 3 次模型重复**，再依据置信区间精度决定是否增加。不能把同一轨迹中的几十次调用当成几十个独立实验。

**【来源明确】** 仿真输出分析中，共同随机数可降低方案差值的方差；配对比较应直接分析每对结果的差值及其置信区间。[《A Practical Introduction to Analysis of Simulation Output Data》](https://informs-sim.org/wsc16papers/013.pdf)

**【设计推断】** A/B 应共享初始快照和外生随机条件。仅设置同一个全局 seed 未必足够：策略改变事件顺序后，随机数可能被不同事件消费。应将故障、到达、加工等随机流分开，并尽可能按设备或批次绑定。统计时先在每个工厂 seed 内汇总模型重复，再分析 A/B 差值；采用配对区间或按工厂 seed 聚类的 bootstrap，报告 95% 区间、效应量和失败比例。

**【来源明确】** LangSmith 官方接口提供 `num_repetitions`，支持对每个样本重复运行；但重复次数不等于统计设计已经正确。[《How to evaluate with repetitions》](https://docs.langchain.com/langsmith/repetition)

**【设计推断】** 实验前固定主指标、预算、终止规则、失败处理和测试 seed。例如，先以可避免空闲为主指标，以调用数为成本指标，随后在长期实验中检验 tardiness 和 throughput。阈值及最小有意义改善幅度应在看结果前确定；本次没有找到专门针对“LLM＋SMT2020”的预注册规范。

**【来源明确】** 单因素实验不能识别变量间交互。[NIST《One variable at a time》](https://www.itl.nist.gov/div898/handbook/pri/section2/pri212.htm)

**【设计推断】** 初期用固定基线分别加入“触发修复、统一缺口、时间规范化、深覆盖、完整状态”，定位收益；再对“触发周期×覆盖深度”做 2×2 实验。累计版本 A→A+B→A+B+C 只能说明增量效果，不能完整分离主效应与交互。

## 四、调用与 token 成本应怎样记账

**【来源明确】** 《AI Agents That Matter》主张联合评估质量与成本；LangSmith 支持输入、输出及缓存 token 的成本记录，Anthropic 则建议同时跟踪延迟、token、每任务成本和错误率。[《AI Agents That Matter》](https://arxiv.org/abs/2407.01502)；[《Cost tracking》](https://docs.langchain.com/langsmith/cost-tracking)；[《Demystifying evals for AI agents》](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**【设计推断】** 每个重排回合应生成一份账本：触发原因、查询次数、提案次数、确认次数、拒绝原因、实际提交次数、新增覆盖时长、各类 token、费用和端到端耗时。区分“检测到事件”“启动规划回合”“模型调用”“有效计划提交”，四者不能统称重排次数。

按你们提供的近似值，56—69 次调用、每次重发 20 万 token，意味着仅输入量就约 **1120万—1380万 token**；这不是实际费用估计，缓存和真实 usage 必须另计。

**【设计推断】** 在“提案、确认各占一次调用”的协议下，若有 \(R\) 个成功提交回合，至少需要 \(2R\) 次调用，查询和修正另加。因此应同时比较“调用／模拟小时”“费用／模拟小时”和生产 KPI，并绘制成本—质量曲线；单看查询减少无法判断总体效率。

## 五、暂停模拟时钟与真实决策时延

**【来源明确】** 在线排程研究将“何时重排”和“分配多少计算时间”视为共同决策；2025 年半导体研究也指出，耗时较长的解可能因现场持续变化而过时。[《Reinforcement learning of adaptive online rescheduling timing and computing time allocation》](https://doi.org/10.1016/j.compchemeng.2020.106994)；[《Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs》](https://arxiv.org/html/2505.11135v1)

**【设计推断】** 暂停时钟可以隔离排程逻辑质量，但消除了等待决策期间的产能损失和状态过时。建议保留零延迟评估，并增加延迟评估：

1. 在模拟时刻 \(t\) 获取快照，决策耗时为 \(L\)。
2. 工厂继续执行旧计划或规则派工。
3. 在 \(t+L\) 产生“计划就绪”事件，重新验证并原子提交。
4. 记录失效任务、修复量、超时及计算期间的空闲。

\(L\) 应覆盖查询、推理、提案、校验和确认。先扫描 **0、10、30、60、120 秒**，再使用实测延迟分布；可另设 P95 延迟压力场景。以上是建模建议，本次未找到 LLM＋SMT2020 的标准延迟协议。比较“旧计划继续执行”和“兜底派工继续执行”时，也应固定该条件，避免混入新的实验变量。

## 六、对我们问题的可借鉴做法

以下均为**设计推断**；依据是前述重排分类、稳定性研究、SMT2020 基准及 Agent 评估方法。

**1．对应事件触发过密：实现周期滚动与异常越级。**  
先扫描重排周期 \(\Delta=\{60,180,300\}\) 秒、计划窗口 \(H=\{3\Delta,6\Delta\}\)，只执行当前滚动段。普通缺口累计到下一周期；故障使近期承诺不可行等异常才越级触发。加入事件合并及待处理回合去重。评估调用下降时，必须同时检查可避免空闲和延误。[依据：《Rescheduling Manufacturing Systems》](https://cepac.cheme.cmu.edu/pasi2011/library/henning/ReschedulingFramework-VieiraHerrmannLin.pdf)

**2．对应需求口径不一致：统一工序集合与分配关系。**  
由同一个状态函数输出“物理就绪”“已有有效承诺”“未分配就绪”集合，触发、输入和评分全部调用它。工序按唯一 ID 去重，扣除分配到任何设备的有效承诺。另用设备—工序可行匹配检测可避免空闲，避免同一工序被多台空闲设备重复计数；已分配但长期延后也须单独暴露。本次未找到此缺口指标的统一标准名称，该定义是项目指标。[方法依据：《SMT2020—A Semiconductor Manufacturing Testbed》](https://doi.org/10.1109/TSM.2020.3001933)

**3．对应过期开工下界：建立确定性规范化。**  
若字段表示最早允许开工，候选下界可规范为  
\[
s_{\mathrm{eff}}=\max(s_{\mathrm{requested}},t_{\mathrm{now}},r_{\mathrm{material}})
\]
再执行资源、前序和工艺约束检查。物料时间未知则保留等待条件；硬预约或时间窗不能静默顺延。分别记录自动规范化、真正不可行拒绝和模型修复次数，检查是否降低修复成本且未改变约束语义。[方法依据：《Demystifying evals for AI agents》](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

**4．对应计划浅、扩窗无效：按可执行时长衡量覆盖。**  
报告各设备有效队列覆盖时长的 P10、P50及瓶颈组覆盖，区分已就绪工作与依赖未来来料的预测任务。初始目标可设瓶颈组覆盖不少于 \(2\Delta\)，总窗口为 \(3—6\Delta\)；物料不足时允许低覆盖并返回原因。同时比较 LLM 全量排程与“LLM 定优先级＋确定性规则补齐”，把上下文窗口作为独立因素。[工业依据：《SmartFactory Real Time Scheduling & Reporting》](https://appliedsmartfactory.com/productivity-solutions/real-time-scheduling-reporting/)

**5．对应状态不完整、重复查询：给无状态进程完整工作快照。**  
每次直接提供当前计划、执行指针、在加工任务、有效分配、等待原因、近期变化，以及尚有效的查询结论；引用保留用于审计，关键事实进入输入。按 `state_version` 缓存查询结果，并报告重复查询率和“必要状态一次可得率”。持久化结构化笔记与上下文压缩有官方工程依据，但此快照结构由项目自行定义。[《Effective context engineering for AI agents》（2025）](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

**6．对应指标遮蔽与单轨迹：先修测量，再验证收益。**  
增加未分配就绪工序的时间积分、可避免空闲、已分配但延后工作量、计划覆盖及完整调用账本。先用 5×3 重复筛查，再对关键版本做 20×3 配对验证；保留 FIFO、CR、纯规则派工和当前 harness 基线。所有失败、超预算与超时均进入结果，不能只比较成功轨迹；最终用长期生产 KPI 检查短窗优化能否持续。[依据：《A Practical Introduction to Analysis of Simulation Output Data》](https://informs-sim.org/wsc16papers/013.pdf)；[《Semiconductor Fab Scheduling with Self-Supervised and Reinforcement Learning》](https://arxiv.org/pdf/2302.07162)