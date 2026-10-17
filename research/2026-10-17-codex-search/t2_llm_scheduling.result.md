检索范围为 2023 年至 2026 年 10 月 17 日。以下用“**来源明确**”表示论文或官方材料报告的内容，用“**推断／建议**”表示对你们 harness 的判断。预印本、实验结果和厂商自述分别标明，不将小规模 JSSP 成绩直接外推到约 900 台机组的晶圆厂。

**总体判断：最值得优先验证的是“LLM 低频选择策略／生成规则，传统调度器高频执行”，以及“LLM 周期规划，确定性程序负责补队列、校验和局部修复”。** 这是综合下述证据的工程推断；本次未找到公开研究证明，逐次调用通用 LLM 能在 SMT2020 全厂规模下同时获得更好的质量和调用成本。

## 一、LLM 直接做 JSSP／FJSP：已有结果，规模与动态性仍需辨别

| 工作 | 来源明确说了什么 | 对本问题的意义与边界 |
|---|---|---|
| [LLMs can Schedule（2024）](https://arxiv.org/abs/2408.06993)；[Starjob: Dataset for LLM-Driven Job Shop Scheduling（2025）](https://arxiv.org/abs/2503.01877) | 前者提供约 12 万训练实例；后者提供约 13 万实例，以 LoRA 微调量化 LLaMA 8B，直接输出排程，并在标准基准上与派工规则、神经方法比较。 | **推断：**支持“专门训练的小模型直接排程”路线；不能据此证明无状态、超长上下文的通用模型适合全厂动态控制。两篇作者和研究内容高度相关，不宜当作完全独立的证据。 |
| [DScheLLM: Enabling Dynamic Scheduling through a Fine-Tuned Dual-System Large language Model（2026，预印本）](https://arxiv.org/abs/2601.09100) | 用 OR 求解器产生训练数据，微调 7B 模型；快思考生成排程，慢思考生成求解器兼容的决策输入，应对不同尺度扰动。 | **推断：**适合借鉴“扰动分级＋快慢路径”；其摘要没有证明对所有事件均调用大模型具有成本优势。 |
| [ReflecSched: Solving Dynamic Flexible Job-Shop Scheduling via LLM-Powered Hierarchical Reflection（2025，预印本）](https://arxiv.org/abs/2508.01724) | 发现直接 LLM 调度存在长上下文利用不足、专家规则利用不足和短视问题；让模型分析多个规划视野下的启发式仿真，压缩成“战略经验”指导决策。 | **推断：**可借鉴多视野 rollout 和经验摘要；它增加分析环节，不能直接作为减少调用的证据。 |
| [DynaSchedBench: Calibrated Dynamic Scheduling Benchmarks and Observability Paradox in LLM-based Scheduling Agents（2026，预印本）](https://arxiv.org/abs/2605.27566) | 构建校准难度的动态 FJSP 环境；报告完整结构信息有时反而降低表现，工具增强和 refinement 带来大量 token 却未稳定改善质量，多数 LLM Agent 未持续超过强派工基线。 | **推断：**与你们“扩大窗口减少查询、未减少总调用”的现象相容，但不能据此认定因果相同。 |

**来源明确：**[SCHEDBench: A Benchmark for Evaluating LLM Constraint Faithfulness in Natural-Language Combinatorial Scheduling（2026，预印本）](https://arxiv.org/abs/2608.00991)涵盖 1,132 个实例，包括 JSP、项目调度等，使用求解器验证参考解；语义等价的自然语言改写、特别是约束重排，会影响模型可行性。

**推断：**评估直接排程时，应同时报告硬约束通过率、目标值差距、实例规模、修复次数与模型调用数。仅报告最终排程质量，会隐藏 harness 替模型承担的成本。

## 二、LLM＋求解器：让模型处理需求，让算法处理组合搜索

**来源明确：**[OptiMUS: Scalable Optimization Modeling with (MI)LP Solvers and Large Language Models（2024）](https://arxiv.org/abs/2402.10172)让 Agent 从自然语言构建数学模型、编写和调试求解器代码，再根据执行结果改进。其模块化设计用于处理复杂描述和数据，避免所有内容塞入长提示。

**来源明确：**[ORLM: A Customizable Framework in Training Large Models for Automated Optimization Modeling（2024）](https://arxiv.org/abs/2405.17743)通过合成数据训练开放模型的优化建模和求解器代码生成能力，并提出 IndustryOR 工业问题基准。它研究的是自动建模能力，不能等同于全厂在线调度性能。

**来源明确：**[Automated Conversion of Static to Dynamic Scheduler via Natural Language，RAGDyS（2024）](https://arxiv.org/abs/2405.06697)基于现有模型与代码，将新增自然语言约束转成 OR-Tools CP-SAT 修改；执行失败时检索文档修复，并设置 `maxAttempts`。实验主要是工人／护士排班；作者明确指出，仅比较求解结果会产生约束错误的假阳性，因此还进行人工检查。

ASP 方向，本次找到的明确实例是[CLMASP: Coupling Large Language Models with Answer Set Programming for Robotic Task Planning（2024）](https://arxiv.org/abs/2406.03367)，属于机器人任务规划。**没有找到足以支撑 SMT2020 全厂 LLM＋ASP 成效的直接证据。**

**推断：**对你们更适合的是维护稳定的 CP-SAT／MILP 模板，LLM 输出目标权重、规则选择、局部约束补丁或瓶颈区域；运行时更新数据并求解。不要每轮重新生成整个调度模型。求解器保证的是已编码模型的约束满足，仍需独立检查约束是否遗漏。

## 三、生成或演化派工规则：更直接地摊薄在线调用成本

| 工作 | 来源明确说了什么 |
|---|---|
| [Mathematical discoveries from program search with large language models，FunSearch（2023 在线发表／2024 卷期）](https://www.nature.com/articles/s41586-023-06924-6) | LLM 生成程序，外部 evaluator 执行、筛选和进化；在线装箱实验搜索的是决策函数，而非每个实例的答案。原文实验并非晶圆厂排程，搜索总采样量可达百万量级。 |
| [Evolution of Heuristics: Towards Efficient Automatic Algorithm Design Using Large Language Model，EoH（ICML 2024）](https://proceedings.mlr.press/v235/liu24bs.html) | 同时进化自然语言“想法”和可执行代码，并以外部性能评价筛选。 |
| [ReEvo: Large Language Models as Hyper-Heuristics with Reflective Evolution（NeurIPS 2024）](https://papers.nips.cc/paper_files/paper/2024/hash/4ced59d480e07d290b6f29fc8798f195-Abstract-Conference.html) | 将 LLM 用作超启发式，以反思反馈辅助进化搜索，生成启发式。 |
| [NS4S: Neighborhood Search for Scheduling Problems Via Large Language Models（IJCAI 2025）](https://www.ijcai.org/proceedings/2025/966) | 生成并验证工序权重更新启发式，用于引导邻域搜索；在 JSP、FJSP、含顺序相关换型的 FJSP 共 349 个实例上评估。 |
| [LLM actor-critic based dispatching rule generation for dynamic job shop scheduling（CIRP Annals 2026）](https://doi.org/10.1016/j.cirp.2026.04.007) | actor 生成规则，critic 提供性能与结构反馈，离散事件仿真评价规则，并维护持久解档案；测试场景是动态 CNC job shop。 |

**推断：**这条路线最直接改变调用次数的增长方式：在线派工执行已生成代码，模型调用发生在规则设计、再训练或策略切换时。代价转移到离线搜索，必须分别统计“规则研发成本”和“部署运行成本”；FunSearch 本身并不是总调用便宜的证明。

对晶圆厂，建议让模型生成受限接口的评分函数，例如 `score(lot, tool, state)`，由程序预先检查资格、批处理兼容性和资源约束。模型设计优先级，程序保持可行性。该分工是对上述方法的迁移建议，尚非 SMT2020 已验证结论。

## 四、调用频率、validate–repair 与持久状态

**来源明确：**[Dynamic dispatching rule selection for the job shop scheduling problem（2025）](https://doi.org/10.1016/j.cie.2025.111471)比较周期规则选择与实时规则选择；在其测试中，两者的拖期表现均比基准规则改善超过 10%，周期方法更加稳健。**它不是 LLM 论文**，但提供了“策略选择频率可以低于派工频率”的直接调度证据。

**来源明确：**Anthropic 官方[Building Effective AI Agents（2024）](https://www.anthropic.com/engineering/building-effective-agents)建议从简单方案开始，明确区分预定义工作流和模型自主编排，并指出 Agent 常以延迟、成本换取性能。[Effective context engineering for AI agents（2025）](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)强调有限注意力预算、精选上下文、压缩和结构化笔记。两者均未给出制造场景的最佳调用周期。

**来源明确：**[Robust Planning with Compound LLM Architectures: An LLM-Modulo Approach（2024）](https://arxiv.org/abs/2411.14484)将外部验证器接入生成—反馈循环。其可靠性主张依赖验证器集合的完备性与正确性，并不保证有限轮内找到解。[LangGraph Persistence 官方文档](https://docs.langchain.com/oss/python/langgraph/persistence)则提供 checkpoint 和跨执行状态保存机制。

**推断：**应把循环拆成“自动规范化→确定性校验→局部算法修复→必要时 LLM 修复”。并非每个拒绝都值得新增模型调用。模型进程可以无状态，但 harness 必须持久保存当前计划、提案、查询结果和执行回执。

## 五、半导体工业实践：有成熟分层，缺少直接 LLM 替代证据

**来源明确，厂商自述：**Applied Materials 的[Real-Time Scheduling & Reporting](https://appliedsmartfactory.com/productivity-solutions/real-time-scheduling-reporting/)使用规则驱动的实时派工；[Advanced Scheduling](https://appliedsmartfactory.com/productivity-solutions/advanced-scheduling/)使用优化调度，并强调共同数据模型承载计划、调度与派工。

**来源明确，厂商自述：**INFICON 的[Factory Scheduler](https://www.inficon.com/en/products/intelligent-manufacturing-systems/factory-scheduler)结合启发式、线性规划和搜索，考虑未来到料、维护、换型与跨区域优先级。[Scheduling at Full-Factory Scale（2026）](https://www.inficon.com/en/news/scheduling-at-full-factory-scale)披露一项后端工厂实践：预处理将超过百万个 lot–tool 候选缩至约 2 万～5 万，约耗时 60 秒，并使用快照层与过期／不可用回退。这不是 LLM 方案。

**来源明确：**[Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs（2025）](https://arxiv.org/abs/2505.11135)涵盖 SMT2020 和真实工业数据，指出选择、组合哪些瓶颈工具交由 Agent 控制非常关键。

**推断：**这些材料支持“全厂协调＋区域优化＋本地派工”的架构。未找到可核实的公开案例证明，通用 LLM 已替代约 900 台机组晶圆厂的实时派工核心，并同时公开调用预算、质量和重复实验。

## 六、对我们问题的可借鉴做法

**以下参数全部是建议的实验起点，不是论文推荐值。** 因模型思考时模拟时钟暂停，应分别核算模拟质量与墙钟耗时；周期触发必须使用模拟时间。

1. **对应问题 1：实现周期规划与事件分级。**  
   普通完工、到料事件只执行本地补队列；LLM 周期选择策略或规划，故障、紧急订单、关键 queue-time 风险才走异常路径。可先扫重排周期 \(\Delta=\{60,180,300\}\) 模拟秒，规划视野 \(H=\{3,5\}\Delta\)，冻结已开工任务及近端承诺；普通缺口设置 30～60 秒模拟时间的冷却。严重事件保留旁路。依据是前述[周期规则选择研究](https://doi.org/10.1016/j.cie.2025.111471)，具体数值需实测。  
   900 秒内，若周期为 180 秒，含初始规划最多约 6 个周期点；每轮“提案＋确认”即约 12 次调用，查询、修复和异常另计。这是协议预算估算，不是性能承诺。

2. **对应问题 2：统一“未覆盖需求”的唯一实现。**  
   建立按工序 ID 索引的 assignment ledger，区分候选、有效预留、执行中、完成、失效。触发器、输入生成器和校验器共同调用 `uncovered_operations(snapshot)`：扣除所有机组上的有效预留与执行中工序；故障导致预留不可执行时显式失效。资格关系不能当成需求重复计数，批加工须记录成员及容量。此为结合[Applied 共同数据模型](https://appliedsmartfactory.com/productivity-solutions/advanced-scheduling/)的工程建议。

3. **对应问题 3：把过期时间戳规范化，保留真实冲突。**  
   分离 `not_before`、预测开工时间和实际开工时间。对仅表达下界的未开工任务，按当前时刻、前序完成、设备／物料就绪和日历重新计算最早可行时刻；未知到料则保持阻塞状态，不伪造确定时间。规范化不得改变机组、顺序和预留语义；若引发资源冲突、硬截止期或 queue-time 违约，再拒绝并反馈具体冲突。规范化后重新校验，最多允许一次 LLM 修复，失败走确定性回退。依据[LLM-Modulo](https://arxiv.org/abs/2411.14484)与[RAGDyS](https://arxiv.org/abs/2405.06697)作此分层建议。

4. **对应问题 4：按时间覆盖与资源竞争补计划。**  
   不只要求“每台机组若干任务”，而要求覆盖未来 \(H\) 的可预测需求，并联动工具资格、上游到料和瓶颈。可从瓶颈可执行队列覆盖不少于 \(2\Delta\) 开始；到料不确定的部分以候选池承接。LLM 输出规则／权重／瓶颈约束，程序扩展队列；本地回退规则先选仿真中最稳的基线。借鉴[NS4S](https://www.ijcai.org/proceedings/2025/966)和[规则生成研究](https://doi.org/10.1016/j.cirp.2026.04.007)，避免把覆盖深度完全交给模型逐项输出。

5. **对应问题 5：每轮提供可独立理解的状态包。**  
   输入包含 `snapshot_id`、模拟时间、当前计划版本、逐机组队列、执行中工序、有效预留、阻塞原因、近期变化及上一轮回执。查询结果按快照和参数缓存；关键字段内联，详细记录保留可检索内容，不能只有失去正文的引用。先比较“约 20 万 token 全量”与“完整关键状态＋按需详情”，而非继续只扩大窗口。依据[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)和[上下文工程文档](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)。

6. **对应问题 6：同时衡量物理机会损失、质量和调用。**  
   将“缺计划等待”扩为两项：物理就绪却无有效分配的工序时间积分；空闲机组存在可行 lot–tool 匹配却未开工的时间积分，后者用匹配避免重复计算替代机组机会。允许有依据的等待凑批或换型优化，并记录原因。同时报告吞吐、拖期、周期时间、queue-time 违约、计划扰动，以及查询／提案／确认／修复调用和 token。建议固定环境随机种子配对比较，先 5 个场景种子×3 条模型轨迹，逐项消融，再扩大重复数；这属于参考[DynaSchedBench](https://arxiv.org/abs/2605.27566)的实验设计建议。优先顺序可设为：统一缺口口径→时间规范化→状态补全→周期与本地回退→规则设计，以区分协议浪费、触发错误和调度能力不足。