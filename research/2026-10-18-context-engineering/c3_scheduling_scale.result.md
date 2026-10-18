# LLM 大规模调度的实例表示、分解与协调调研

调研截至：2026 年 10 月 18 日。本文依据给定的 SMT2020 harness 背景，区分**来源报告的事实**与**面向本项目的设计推断**。检索覆盖 2023—2026 年 LLM 调度研究，并补充运筹分解方法和真实晶圆厂实践。

核心判断：对于约 2,200 lot、上千机组、每周期 1,000+ 可开工工序，最值得验证的方案是**全量可发现目录＋资源耦合分区＋滚动时域＋全局覆盖与可行性校验**。本次未找到能够证明“LLM 直接读取全厂状态，并可靠选择全部任务、机组、组批和队列”的同规模公开评测。下面的建议是工程假设，不是已有论文验证的结论。

## 一、LLM 直接调度：公开证据达到什么规模

### 1. JSSP：从几十道到上千道工序，但不能等同于千台设备

| 研究 | 实例及表示 | 结果与证据边界 |
|---|---|---|
| **LLMs can Schedule，2024** | 将实例转成自然语言；微调 Phi-3，输出具体排程。评测约 1,000 个实例，规模为 2×2 至 9×9；推理采样 10 个候选 | 作者因单张 A6000、FP16 与采样的显存限制，只测试少于 100 道工序。这个上限是实验条件限制，不能解释为模型能力的精确上限 |
| **Starjob，2025** | 微调量化 Llama 3.1 8B；以 job 为中心列出机器和工时，输出时间安排；测试达到 50 jobs×20 machines，即 1,000 道工序 | 使用 40k 上下文、20 个候选采样。Taillard 平均最优已知解差距为 21.69%，L2D 为 29.54%；50×20 时分别为 24.32%、26.40% |

来源：[LLMs can Schedule](https://arxiv.org/html/2408.06993v1)；[Starjob: Dataset for LLM-Driven Job Shop Scheduling](https://arxiv.org/html/2503.01877v1)。

**解读：**Starjob 的平均差距改善是 **7.85 个百分点**，不能直接写成 makespan 降低 7.85%。各规模结果也并非单调恶化，因此不能据此拟合可靠的规模退化曲线。它证明了特定微调模型处理上千道静态工序的可能性，但没有证明对柔性资格、组批、重入、故障、hold 和长期连续运行的适应性。上述数值来自同一篇 Starjob 的表 1。

对本项目，更关键的差别是：标准 JSSP 的“1,000 道工序”跨越完整生产路线，而这里每周期已有 1,000+ 个候选工序，另有约 900 个在加工任务和大量资源状态；两者的信息量与约束耦合不能按节点数直接换算。

### 2. 动态 FJSP：分层反思有效，但实验主体仍小

**来源事实：**ReflecSched 的 Normal 规模为 15—20 jobs、每 job 2—4 道工序、3—5 台机器；Small 为 3—5 jobs。系统用启发式模拟未来，再将结果压缩为“战略经验”，辅助模型选择当前动作。其 GEN-Bench 平均每实例总 token：

| 规模 | LLM-Direct | ReflecSched |
|---|---:|---:|
| Normal | 146.1k | 124.0k |
| Small | 22.6k | 47.9k |

Normal 节省约 15.1%，Small 则增加约 112%。2026 年 v3 增补的半导体 JMS-Bench 是包含五个处理模块的 cluster tool 场景，不是全厂。来源：[ReflecSched: Solving Dynamic Flexible Job-Shop Scheduling via LLM-Powered Hierarchical Reflection](https://arxiv.org/html/2508.01724v3)。

**推断：**值得借鉴的是“低频战略分析＋精简执行上下文”，而非直接采用其调用流程。其总 token 统计不等于本项目的“未缓存等效输入 token/模拟小时”；小实例反而更贵，也说明分层本身不保证省成本。

### 3. 车辆路径与约束推理：可行性和优化质量必须分开

**来源事实：**2026 年 ConstraintBench 要求模型根据自然语言和输出 schema 直接生成决策，不提供求解器或纠错反馈。共 200 个问题、10 类运筹领域、6 个模型。车辆路径领域汇总得到 50 个可行输出，其最优性差距中位数为 9.85%，只有 3 个在最优值 1% 以内；达到论文 0.1% 最优阈值的为零。正文未提供足以建立客户数量—性能曲线的统一实例规模表。来源：[ConstraintBench: Benchmarking LLM Constraint Reasoning on Direct Optimization](https://arxiv.org/html/2602.22465v1)。

**推断：**“通过校验”不能代表排程质量足够好；反过来，目标值看起来不错也不能代替逐项约束校验。我们需要分别测量覆盖、可执行性和生产绩效。

### 4. 名称含 LLM 的大规模结果，常由程序完成实际求解

**来源事实：**NS4S 在 JSP、FJSP 等三类问题上评测 349 个实例；JSP 表含 100×20，GPT-4 版本在该规模的最优已知解差距为 1.50%。但模型生成的是邻域搜索权重更新启发式，测试阶段无需继续调用 LLM。来源：[NS4S: Neighborhood Search for Scheduling Problems Via Large Language Models](https://www.ijcai.org/proceedings/2025/0966.pdf)。

同样，ARS 的 RoutBench 包含 1,000 种 VRP 变体，模型负责生成约束相关启发式代码。“1,000 种变体”既不是 1,000 个客户，也不是模型直接输出 1,000 个任务的证据。来源：[ARS: Automatic Routing Solver with Large Language Models](https://arxiv.org/abs/2502.15359)。

本次还检索到晶圆批处理的 LLM 辅助强化学习研究，但未取得可核验的全文规模与输入表示，因此不采用其摘要改善百分比作核心证据，也不将其视为全厂直接调度验证。来源：[Dynamic scheduling of wafer batch processing machines via reinforcement learning enhanced by expert-guided lightweight LLM](https://doi.org/10.1080/00207543.2025.2582768)。

## 二、运筹方法如何把全厂问题拆小

### 1. 区域分解需要交换时间约束

**来源事实：**分布式 shifting bottleneck 方法采用两层结构：上层使用聚合路线，为 job 在各工作区域分配内部就绪时间和计划交期；下层在区域内运行 shifting bottleneck 类型算法。研究包含并行批处理、顺序相关换型和重入流程，动态仿真结果优于 FIFO，并接近原集中式方法的解质量。来源：[A distributed shifting bottleneck heuristic for complex job shops](https://www.sciencedirect.com/science/article/abs/pii/S0360835205000793)。

**推断：**可迁移的协调接口不是自由文本“注意下游”，而是结构化变量：

- 区域输入的预计到达时间及不确定区间；
- 区域输出的计划完成时间、内部交期；
- 瓶颈的供料需求与剩余容量；
- 跨区域共用设备、reticle 等资源的时间占用。

本项目可以由程序计算这些事实和约束，但目标取舍、具体任务选择仍交给模型。

### 2. 滚动时域需要保留窗口外影响

上述分布式研究指出，长时域使调度图急剧膨胀，短时域则增加内部交期设置的困难。真实 Seagate 案例采用三小时规划窗口，对最多 12 台计量设备进行离线排程，候选同时包括已等待晶圆和近期预计到达晶圆。来源：[A distributed shifting bottleneck heuristic](https://www.sciencedirect.com/science/article/abs/pii/S0360835205000793)；[Advanced Production Scheduling in a Seagate Technology Wafer Fab](https://www.informs-sim.org/wsc20papers/206.pdf)。

**推断：**harness 应区分“观察窗口”和“承诺窗口”：较远未来提供聚合负载、交期与到达预测，近期才生成具体队列。不能仅因为某个 ready 工序预计排不到窗口内，就把它从目录删除；窗口限制应约束规划深度，而非工作可见性。

### 3. 瓶颈详细、其他汇总，需要 WIP 协调

**来源事实：**FabTime 描述了两种协调方式：按工序 moves 目标提高落后工序优先级；按 operation、工序段或 tool 的目标 WIP 调节派工。INFICON 同时建议结合下游信息，防止关键设备断料。来源：[Scheduling and Dispatching for Wafer Fabs](https://www.inficon.com/media/11333/download/FabTimeNewsletter8.07.pdf?v=1)；[10 Recommendations for Fab Cycle Time Improvement](https://www.inficon.com/de/news/10-recommendations-for-fab-cycle-time-improvement)。

**推断：**瓶颈需要展开组批、换型、队列和到达时间；普通区域可先给容量、WIP 目标偏差和最紧迫期限。但只要进入实际决策，仍须展开相关候选。汇总可用于决定“先看哪里”，不能代替模型选择具体 lot。

### 4. 多 agent 不自动解决全局一致性

产业已有多个区域调度器协作的结构：INFICON 明确说明，高产量工厂通常部署多个 Area Scheduler，并根据光刻、扩散、注入等区域配置逻辑。来源：[Factory Scheduler](https://www.inficon.com/en/products/intelligent-manufacturing-systems/factory-scheduler)。

**推断：**这支持区域分解，却不证明多个 LLM 自由协商有效。若试验多 agent，应共享同一状态版本，设置唯一任务归属与资源占用账本；冲突由模型修正，程序只报告冲突。并行可能降低墙钟延迟，但会重复输入、增加请求，因此不宜作为成本优化的第一步。

## 三、真实 RTD 每次看多大范围

**来源事实：**Seagate 案例描述，传统 dispatcher 检查某台设备可处理的全部 WIP，再结合 recipe 分组、事件限制、耐用品资源、需求和优先级决定下一批。它不是每次重排所有 lot 的完整路线。该研究对九组历史数据进行三小时、最多 12 台计量设备的比较，相对模拟现行规则的 SimModel，高优先级晶圆周期时间下降超过 43%，总周期时间约降 9%，吞吐约增 7%。这是局部、确定性离线比较，不能当作全厂上线收益。来源：[Advanced Production Scheduling in a Seagate Technology Wafer Fab](https://www.informs-sim.org/wsc20papers/206.pdf)。

Applied Materials 的 SmartSched 则以光刻单元为详细排程对象，同时响应上游、下游和交付优先级变化。来源：[Applied Materials’ Breakthrough Predictive Scheduling System Boosts Lithography Efficiency](https://ir.appliedmaterials.com/news-releases/news-release-details/applied-materials-breakthrough-predictive-scheduling-system/)。

**解读：**工业实践支持“局部候选全集＋外部影响摘要”。本次没有找到可推广到所有晶圆厂的固定值，例如每次必看多少 lot、几跳路线或多少台设备；公开案例的范围随工艺和资源耦合变化。

## 四、生成启发式：规模优势及与本项目的冲突

| 路线 | 来源实际做法 | 对本项目的意义 |
|---|---|---|
| FunSearch | LLM 生成函数，程序执行与评分，通过迭代寻找更好算法 | 数值实例由程序处理，无需逐次输入 LLM |
| EoH | 联合演化自然语言算法思路和可执行代码 | 设计成本可跨大量实例摊销 |
| ReEvo | 在启发式演化中加入短期、长期反思 | 提高算法搜索效率；最终执行仍由程序承担 |

来源：[FunSearch: Making new discoveries in mathematical sciences using Large Language Models](https://deepmind.google/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/)；[Evolution of Heuristics](https://proceedings.mlr.press/v235/liu24bs.html)；[ReEvo](https://arxiv.org/abs/2402.01145)。

一个具体规模例子：ReEvo 早期版本在每规模 64 个随机 TSP 实例上测试生成的构造启发式。1,000 城市时，平均路径长度为 26.79，最近邻为 29.18，AEL 为 27.34；这是生成算法处理大实例的结果。来源：[ReEvo，v1，表 5](https://arxiv.org/html/2402.01145v1)。

**本项目取舍：**

- 若程序执行模型生成的打分函数，自动选择任务、机器或批次，就改变了“模型选择全部任务”的研究设定。
- 若程序仅计算特征、资格关系、可行性和显式计划的执行时间，而选择仍由模型完成，则可保留原设定。
- 模型明确列举任务、机器、批次及顺序后，由程序确定性展开短 ID 或保存草案，可以是表示压缩；“执行规则直到窗口结束”则是委托程序决策。
- 建议将启发式生成作为独立对照路线，分别计入离线生成成本和在线执行成本。

## 五、对我们问题的可借鉴做法

以下均为基于上述研究与工业实践的**设计建议，尚未在 SMT2020 验证**。

### 1. 首先建设全量可发现目录

每周期生成版本化 `ready_manifest`，包含所有 ready、未预留工序的紧凑 ID、分区归属、资格集合引用和紧迫性标记；详情通过 `read_entities` 获取。每个分区提供精确计数和分页游标，禁止无提示截断。

这延续工业 RTD 对局部候选全集的处理方式，但把完整性做成可校验接口。

**不遗漏条件：**所有候选都能从目录定位；分页返回总数和结束标记；重置上下文后仍能恢复。  
**成本影响：**减少详情输入；若逐 lot 查询，会显著增加请求，因此应按分区批量获取。

### 2. 用资源耦合分区，避免机械按区域切割

以工序—候选设备关系为基础，结合组批兼容性、共享资源、换型和 queue-time 约束形成决策包。跨区候选保留全部设备资格，设置唯一工作归属；“归属某区”不应被解释为只能选择该区设备。

**不遗漏条件：**各包归属集合的并集等于完整候选集合；跨包依赖显式列出。大连通分量允许分页，但不能截去边。  
**成本影响：**单次输入下降，包数增加请求；多个小包应合并到一次调用中。依据是分布式 shifting bottleneck 和 Area Scheduler 的分解结构。

### 3. 静态表按引用读取，活动决策保留完整约束

完整工艺路线和设备表保存在工具侧，输入只带版本、route/step/capability ID。活动工序展开加工时间、资格、批量、换型、hold、queue-time 等必要字段；远端路线提供剩余工作量、下一瓶颈及期限摘要，并保留查询入口。

按给定数据计算，56.4 万静态前缀约占 75.6 万完整快照的 **74.6%**。这是可迁出的体量上限，不是净节省承诺；移除后动态部分仍约 19 万，尚未计入查询和输出。

**不遗漏条件：**缩减的是重复描述，任务身份和约束访问路径仍完整。  
**成本影响：**预期是最大输入节省来源；净收益须计入补查及缓存命中。

### 4. 采用滚动计划和事件触发

让模型一次选择多项任务，形成短期队列；在设备释放、故障、重要到达、hold 解除或期限临近时，更新受影响决策包。未受影响计划继续有效，所有 ready 工作保持在目录中。

**不遗漏条件：**延期任务有明确复审事件或最晚复审时间，不能永久沉到摘要之外。  
**成本影响：**批量决策减少逐工序调用；窗口过短会增加请求，过长会增加输入和失效重排。三小时工业案例只能作为参考，不能直接定为本项目参数。

### 5. 增加覆盖账本，校验只拒绝、不代排

对快照中的候选集合 \(R_t\)，要求：

\[
R_t=S_t\;\dot\cup\;D_t
\]

其中 \(S_t\) 是模型明确排入计划的工序；\(D_t\) 是模型明确延期的工序，附原因和复审条件。已失效项目应通过版本变更单独对账。

`validate_plan` 除检查设备、组批和先后关系，还报告：

- 未处理候选、重复预留和未知 ID；
- 空闲设备仍有可行候选、却没有等待理由；
- 跨分区资源冲突或失效状态版本。

模型决定如何修改；`submit_plan` 原子提交，不让程序补任务、删任务或重排。

**不遗漏条件：**目录保证“可发现”，账本保证“有处置”；两者都不能保证决策最优，但能把静默遗漏变成显式错误。  
**成本影响：**增加少量账本输入及必要纠错调用；可用明确 ID 集合压缩相同延期原因，不能用模糊规则隐藏成员。

### 6. 控制上下文寿命，并按模拟小时验收

每轮从当前状态重建上下文，只保留有效计划、延期账本、区域目标和有限战略摘要。历史明细外置，不累计聊天记录。

建议以同一模型、相同仿真种子比较“紧凑全量输入”“目录＋批量查询”“资源分区＋滚动计划”；多 agent 和启发式生成另设实验组。统一记录：

\[
C_{\text{input}}=\frac{\sum(T_{\text{uncached}}+\alpha T_{\text{cached}})}
{H_{\text{sim}}},\qquad
C_{\text{request}}=\frac{N_{\text{model requests}}}{H_{\text{sim}}}
\]

其中 \(\alpha\) 使用实际缓存价格比；工具响应进入后续模型输入的 token 也必须计入。同时记录吞吐、延误、瓶颈断料、首次校验通过率，以及因不可见或未处置工作造成的空闲时间。

在当前规模下，优先实现**全量目录、批量读取、显式覆盖账本和单模型分包决策**。待这些机制证明能维持零静默遗漏、可执行提交和稳定的每小时成本后，再评估多 agent 协调是否值得其额外请求。