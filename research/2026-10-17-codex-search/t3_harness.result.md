# Agent harness 与上下文工程调研

**核心判断：应优先修复决策边界、状态口径和执行契约，再优化上下文成本。**扩大窗口、会话恢复与提示缓存各有用途，但无法直接解决重复触发和计划过浅。

以下以 **【来源】** 标记原文明确支持的结论，以 **【推断／建议】** 标记针对你们系统的设计判断。检索截至 2026-10-17；数值建议均为实验起点，不是 SMT2020 的已验证最优参数。

## 一、把排程决策、模型请求和工具调用分开

【来源】Anthropic 区分预定义代码路径控制的 workflow 与模型自主控制流程的 agent，并建议从简单、可组合的模式开始，按收益增加复杂度。它没有要求每次进程只能执行一个动作。来源：[Building effective agents（2024）](https://www.anthropic.com/engineering/building-effective-agents)。

【来源】OpenAI 函数调用文档明确说明，一次模型响应可以包含零个、一个或多个函数调用；`parallel_tool_calls=false` 才限制为零个或一个。宿主执行工具后返回结果，模型通常还需要后续请求才能利用结果继续决策。来源：[Function calling](https://developers.openai.com/api/docs/guides/function-calling)。

因此，需要区分三种机制：

| 机制 | 能解决什么 | 限制 |
|---|---|---|
| 一个响应输出多个独立工具调用 | 减少独立查询之间的往返 | 不能提前完成依赖查询结果的动作 |
| 一次 harness 运行内部循环调用模型和工具 | 避免每个动作都重启进程、重建上下文 | 仍可能产生多个模型 API 请求 |
| 一个业务工具批量查询或处理对象 | 减少碎片化工具调用 | 需要定义清楚批处理语义 |

【推断】你们可以把“模拟时钟暂停期间，读取信息、构造计划、校验、提交”定义为一次**排程决策运行**。运行内部允许多轮交互，提交成功或预算耗尽才退出。独立只读查询可并行；提案、校验及提交有依赖，应顺序执行。依据：[Function calling](https://developers.openai.com/api/docs/guides/function-calling)、[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)。

这样可能降低进程启动和上下文组织开销，但**不能把减少进程次数直接报告为减少模型请求次数**。

## 二、会话复用、提示缓存与压缩是不同能力

【来源】OpenAI 支持使用 Conversations 持久化会话，或通过 `previous_response_id` 串联 Responses。官方特别注明：使用后者时，链中的历史输入仍作为输入 token 计费。来源：[Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)。

【来源】提示缓存复用的是匹配的提示前缀；会话复用不保证缓存命中。前缀中的内容或相关配置发生变化，会影响后续部分的复用。来源：[Prompt caching — OpenAI](https://developers.openai.com/api/docs/guides/prompt-caching)。

【来源】Anthropic 支持自动缓存或显式 `cache_control` 断点，提供 5 分钟和 1 小时 TTL。缓存寿命按真实请求时间计算，生成响应所花时间也计入。来源：[Prompt caching — Claude](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)。

【建议】将输入按变化频率组织：稳定规则、工具定义和工艺资料在前，当前状态及事件在后。固定对象排序、字段顺序和序列化方式，避免时间戳或随机排序过早打断稳定前缀。TTL 应按**墙钟请求间隔**选择；模拟时钟暂停并不会暂停缓存计时。依据为上述两份 *Prompt caching* 文档。

收益应分别记录：

- 会话复用：降低客户端历史管理和重复传输负担；
- 缓存：降低重复前缀处理成本及延迟；
- 压缩：减少有效上下文体积；
- 触发与计划设计：减少业务上需要的排程决策次数。

【来源】OpenAI 的 compaction 可通过阈值触发，也提供独立压缩端点；输出包含承接历史状态和推理的、不供人直接解读的压缩项。来源：[Compaction](https://developers.openai.com/api/docs/guides/compaction)。

【推断】压缩项适合承接会话，不应作为机组分配、队列和执行状态的唯一权威记录。调度事实仍应由模拟器的结构化状态提供。

## 三、完整决策状态与按需检索可以同时存在

【来源】Anthropic 的上下文工程指南强调高信号信息、按需加载及混合检索；同时指出，运行时探索存在延迟代价。长任务可用 compaction 和结构化笔记维持连续性。来源：[Effective context engineering for AI agents（2025）](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)。

【来源】其长任务 harness 实践发现，仅有压缩还不够：新会话需要明确的进度记录、任务状态和可验证的环境状态，避免重新猜测此前发生了什么。来源：[Effective harnesses for long-running agents（2025）](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。

【来源】LangGraph 将线程状态 checkpoint 与跨线程 store 分开；内存 checkpoint 无法跨进程重启保留，持久化需要数据库或文件后端。来源：[Persistence — LangGraph](https://docs.langchain.com/oss/python/langgraph/persistence)。

【建议】对你们更合适的是“**完整决策状态 + 历史详情按需加载**”。完整指当前决策所需字段齐全，不代表重发所有原始日志。至少包含：

- `state_version、sim_time、plan_version`；
- 机组可用性、当前执行工序、预计释放时间；
- 已接受队列、已分配工序及其归属；
- 当前可加工集合、未分配集合、等待原因；
- 预测到料信息及可信度、冻结任务；
- 上次提交回执、规范化结果、未解决异常。

稳定工艺资料和旧日志可以引用分页；当前有效分配、执行状态、上次校验结果应直接可见。这是对上述工程实践的领域化推断，**未找到官方文档规定晶圆厂应使用这一特定快照格式**。

增量 diff 必须携带 `base_version、target_version`，并包含删除记录。持久会话或宿主持有基线时可以应用 diff；真正无状态的新进程只收到 diff，不能恢复完整状态。版本不匹配应自动补全快照。

## 四、工具结果应按有效性保留，而不是统一变成引用

【来源】Anthropic 工具设计博客建议返回有意义、节省 token 的结果，明确分页及截断方式，并让校验错误提供具体、可执行的修正信息。来源：[Writing effective tools for AI agents—using AI agents（2025）](https://www.anthropic.com/engineering/writing-tools-for-agents)。

【来源】Claude 的 context editing 支持保留最近工具交互、排除指定工具不被清除，并设置最低清除量；文档也提醒清理会影响提示缓存。来源：[Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)。

【建议】采用三类保留策略：

| 结果 | 模型可见策略 | 失效条件 |
|---|---|---|
| 当前有效分配、执行状态、提交回执 | 保留结构化正文 | 被新版本替代 |
| 当前提案校验、候选工序查询 | 保留正文或充分摘要 | 相关状态变化 |
| 旧计划、旧查询、详细日志 | 摘要加可恢复引用 | 不必持续占窗口 |

每条结果附 `state_version、scope、complete、truncated、next_cursor`。引用同时提供结果概要和恢复入口，避免模型为了知道“引用里是什么”再次查询。依据为上述工具设计及 context editing 文档；分类方式是工程建议。

【来源】《Lost in the Middle》在问答和键值检索中发现，相关信息的位置会显著影响长上下文表现；MemGPT 则研究了分层记忆与外部存储。来源：[Lost in the Middle: How Language Models Use Long Contexts（2023）](https://arxiv.org/abs/2307.03172)、[MemGPT: Towards LLMs as Operating Systems（2023）](https://arxiv.org/abs/2310.08560)。

这些研究支持测试信息组织和记忆机制，但**不能直接证明你们当前模型在 544k 窗口中的排程表现**。

## 五、校验器与提交协议：明确硬约束和可规范化语义

【来源】官方工具指南支持明确数据契约、减少易错参数和返回可操作错误；没有找到“晶圆厂过期最早开工时间必须自动修正”的官方标准。来源：[Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)。

【建议】将校验分为两层：

1. **语义明确的规范化**：例如 `earliest_start` 被定义为下界，而非必须兑现的预约时刻，则过去的下界可规范化为  
   `effective_not_before = max(requested_not_before, sim_time)`。  
   实际开工还须满足到料、前序完成和资源条件。
2. **硬约束拒绝**：重复分配、设备资格不符、不可兼容批次、违反工序依赖、资源冲突，以及修正后违反最大等待时间等，仍拒绝提交。

未知到料应表示为 `waiting_material`，预测到料只能支撑暂定计划。不能把预测时间改写成已满足的物理条件。

规范化返回 `normalized_plan、changes、warnings、violations、state_version`；提交回执再返回实际接受的计划。规范化函数应幂等，同一输入重复处理不应持续改变结果。上述均为基于工具契约原则的工程推断。

【推断】“提案后再让同一个模型确认”没有天然增加独立审核能力，也不等同于数据库分布式两阶段提交。本次未找到要求离线仿真每个计划都必须由模型再次确认的官方依据。

可替代为 `submit_plan(expected_state_version, idempotency_key, plan)`：宿主规范化、完整校验，再原子提交并返回回执。保留 `dry_run` 用于诊断；重大语义修改或需要外部审核时才进入确认流程。这个设计与持久化工具工作流相容，但提交原子性必须由宿主实现。参考：[Persistence — LangGraph](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 六、事件驱动不等于每个事件都全局重排

【来源】经典重排框架区分周期、事件驱动和混合策略，同时区分右移修复、局部修复与完整重建。来源：[Rescheduling Manufacturing Systems: A Framework of Strategies, Policies, and Methods（2003）](https://cepac.cheme.cmu.edu/pasi2011/library/henning/ReschedulingFramework-VieiraHerrmannLin.pdf)。

【来源】2023 年事件触发制造排程研究强调在性能与重排计算成本之间取得平衡，通过选择性触发减少重排。但其验证对象是含能源系统的十机流水线，不能直接移植参数到晶圆厂。来源：[Event-triggered Hybrid Energy-aware Scheduling in Manufacturing Systems](https://arxiv.org/abs/2302.00812)。

【来源】2025 年半导体派工研究指出，受控瓶颈工具的选择及组合对高效优化很重要，且 SMT2020 与真实工业数据仍存在复杂度差异。来源：[Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs](https://arxiv.org/abs/2505.11135)。

工业侧，Siemens APS 明确将资源、材料和约束纳入可行排程；Applied SmartFactory 提供实时排程与 RTD 能力。不过这些公开页面没有披露适用于你们规模的事件批处理周期。来源：[Production planning and scheduling — Siemens](https://www.siemens.com/en-us/products/opcenter/production-planning-scheduling-capabilities/)、[Semiconductor Manufacturing Productivity Solutions — Applied SmartFactory](https://appliedsmartfactory.com/productivity-solutions/)。

【建议】普通完工、到料和机组释放先更新状态，由执行器继续已有队列；必要时确定性局部修复。周期边界再进行滚动优化，严重故障或关键时间约束风险可以提前触发。是否引入启发式兜底派工，应作为独立实验变量，否则无法判断改进来自模型还是执行器。

## 七、Codex CLI exec 的恢复与 MCP 接入

【来源】`codex exec` 支持非交互执行；`--json` 输出线程、回合、工具调用等 JSONL 事件；`--output-schema` 约束最终输出结构；`codex exec resume <SESSION_ID>` 可恢复指定会话，`--ephemeral` 则不保存会话 rollout。来源：[Non-interactive mode](https://developers.openai.com/codex/noninteractive/)。

【来源】Codex 支持本地 STDIO 和 Streamable HTTP MCP 服务，配置位于 `config.toml`；可通过 `codex mcp add` 添加服务。来源：[MCP — Codex](https://developers.openai.com/codex/mcp/)。

【建议】按仿真轨迹保存明确的 session ID，避免并发实验用 `--last` 恢复错误轨迹。通过 MCP 暴露 `get_decision_snapshot、query_candidates、validate_plan、submit_plan`，并用 JSONL 分别统计外层运行、内部模型请求及工具动作。

恢复会话后仍须注入当前状态版本；resume 不会自动同步模拟器。最终 JSON Schema 保证格式，也不保证资源和工序约束正确。以上是对官方能力的应用推断。

## 对我们问题的可借鉴做法

以下参数全部是**建议搜索范围**。本次没有找到 SMT2020 LLM harness 的标准周期、覆盖深度或最佳上下文预算。

### 对应问题 1：周期滚动计划与事件合并

先实现三层路径：已有队列执行 → 确定性局部修复 → LLM 滚动重排。同一模拟时间戳的事件全部处理完，再检测一次缺口；普通事件合并窗口可试 **5／15／30 模拟秒**，周期可试 **30／60／120 秒**，计划跨度先试 **3～5 个周期**。

周期边界是“检查是否需要优化”，不应强制产生无变化提案。严重故障和关键队列时间风险绕过普通冷却。模拟时钟暂停时，墙钟 debounce 不会合并未来模拟事件，应在仿真事件循环中实现。

依据：[Rescheduling Manufacturing Systems](https://cepac.cheme.cmu.edu/pasi2011/library/henning/ReschedulingFramework-VieiraHerrmannLin.pdf)、[Event-triggered Hybrid Energy-aware Scheduling](https://arxiv.org/abs/2302.00812)。

### 对应问题 2：统一需求、分配和缺口定义

建立唯一状态函数：

`unassigned_ready_ops = physically_ready_ops − valid_assigned_ops − running_ops`

触发器、输入组织和指标都调用它，并按工序 ID 管理唯一分配及有效预留。不能仅凭“某机组空队列”判断全局缺计划：同一工序可能已分配给另一台兼容机组。

同时，合法分配也可能低效。增加“已分配但超过可接受启动延迟”的独立指标，避免减掉已分配工序后再次掩盖等待。多机竞争场景用匹配计算可并行开工量，避免一个工序被计成多台机组的缺口。

依据：[Production planning and scheduling — Siemens](https://www.siemens.com/en-us/products/opcenter/production-planning-scheduling-capabilities/)；具体集合及匹配定义为工程推断。

### 对应问题 3：规范化过期下界，减少修正往返

将“排队顺序、开工下界、到料门控”分成独立字段。过去的下界按规则规范化；资源、批次、前序及最大等待时间仍完整校验。一次响应汇总全部违规工序和可修正项。

正常路径试验为一次原子 `submit_plan`；诊断路径允许 `dry_run`，初始最多 **2 次模型修正**，超过后返回明确失败并保留合法旧计划。无需每次增加空洞确认动作。

依据：[Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)；规范化及修正预算为建议。

### 对应问题 4：以时间覆盖和风险衡量计划深度

用预计队列耗尽时间衡量覆盖，避免仅要求每台机组列固定条数。瓶颈、近期有料机组优先覆盖 **3～5 个周期**；未来到料任务标为暂定。无法预测的机组注明缺口原因，不能强填不可执行任务。

当瓶颈预计覆盖低于 **1 个周期**时请求补充。可让模型输出工具组优先级和约束策略，由确定性排程器展开大量工序；将这一方案与纯模型列队列独立比较。

依据：[Scalability of Reinforcement Learning Methods for Dispatching in Semiconductor Frontend Fabs](https://arxiv.org/abs/2505.11135)；覆盖阈值为实验建议。

### 对应问题 5：建立可恢复的决策工作集

每次必须直接提供当前分配、执行状态和上次提交回执；旧详情才分页引用。持久会话用 checkpoint 加版本 diff，独立进程用完整决策快照。

工具结果初始保留最近 **3～5 组**，但当前有效计划、未解决校验结果按有效性保留，不按年龄删除。压缩阈值可从窗口的 **60%～70%**试起，并验证压缩前后是否保留关键约束。缓存命中率与重复查询率分别统计。

依据：[Context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)、[Compaction](https://developers.openai.com/api/docs/guides/compaction)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

### 对应问题 6：修复指标并做可归因实验

【来源】Anthropic 要求区分模型轨迹与环境最终结果，针对随机行为运行多次 trial，并建议从 **20～50 个真实失败案例**建立初始评估集。来源：[Demystifying evals for AI agents（2026）](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)。

【建议】除缺计划等待外，记录未分配可加工工序的等待积分、已分配启动延迟、可行匹配下的损失机时、吞吐、延期、换型、批量效率及计划变动率。诊断用可行匹配只需衡量当下机会，不必声称是全局最优排程。

分开记录重排次数、API 请求数、查询／提案／确认次数、缓存 token、真实费用和墙钟耗时。先固定状态与校验器，再分别测试触发、覆盖、会话和缓存；筛选阶段每配置可用 **至少 5 条模型轨迹**，候选配置扩至 **10～20 条**，按置信区间继续增样。外生随机事件尽量按对象和事件编号固定，减少排程改变随机数消费顺序造成的混杂。该样本量及实验顺序为工程建议，依据为上述评估指南。