# 大于上下文窗口的环境状态：主流 Agent Harness 实践及晶圆厂调度启示

调研日期：2026-10-18。本文依据官方文档、工程博客及论文；“原文”表示来源明确陈述，“推断／建议”表示结合本项目约束的分析。产品机制按引用资料所述版本理解，厂商实验不视为跨任务保证。

## 一、核心判断

主流 harness 普遍采用**少量预加载信息、外部完整状态、按需读取、历史压缩**的组合。区别主要在于谁选择上下文：框架预先检索、模型自主搜索，或二者结合。Anthropic 明确把轻量标识符与即时读取结合；LangChain 将相关策略归为 write、select、compress、isolate。[《Effective context engineering for AI agents》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[《Context Engineering》](https://www.langchain.com/blog/context-engineering-for-agents)

对本项目，存在两个独立问题：

- **首周期装不下**：75.6 万 token 快照超过原预算，历史摘要无法解决。
- **运行时间越长，历史越多**：即使缩小首个快照，也需要有界工作上下文。

**推断：优先改造状态表示与查询接口，再处理跨周期记忆。**另外，“数据仍能查询”只保证可达性；要防止模型不知道还有工作，必须增加完整目录和未处理项反馈。公开资料中的相关性检索机制，本身不提供调度工作全集的覆盖保证。

## 二、各家如何选择进入上下文的内容

下表“机制”为来源原文概括，“边界”为本次分析。

| 系统 | 公开机制 | 对本项目的边界与启示 |
|---|---|---|
| Claude Code | 预加载 `CLAUDE.md`，通过 glob、grep 等即时探索；以路径、查询等标识符代替预加载完整对象。 | 适合“规则常驻、数据按需”；仍需让模型知道有哪些对象可查。[《Effective context engineering》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) |
| Codex CLI | 官方提示指南要求先规划读取，再批量并行调用；只有下一步依赖前一步结果时才串行；支持 compaction。 | 查询粒度应支持一次取回多个有关实体，避免逐 lot 往返。[《Codex Prompting Guide》](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide) |
| Cursor | 结合语义搜索与 grep；长工具结果保存为文件，返回可读引用；压缩后保留历史文件入口；MCP 工具说明按需发现。 | “摘要＋句柄＋查询”可减少常驻输入，并允许恢复细节。[《Dynamic context discovery》](https://cursor.com/blog/dynamic-context-discovery)、[《Improving agent with semantic search》](https://cursor.com/blog/semsearch) |
| Aider | repo map 提供文件、关键符号和定义片段；依赖图排序选择预算内内容，默认预算 1k token，部分情形动态扩大。 | map 是导航层，不是完整清单；不可直接用排名裁掉可排程工作。[《Repository map》](https://aider.chat/docs/repomap.html) |
| Sourcegraph Cody | 通过关键词、Sourcegraph Search、代码关系检索相关片段；Enterprise FAQ 明确说明以 Sourcegraph Search 替代 embeddings。 | “访问整个仓库”不等于“全部仓库进入 prompt”；检索范围与实际返回集合须区分。[《Cody Context》](https://7.3.sourcegraph.com/cody/core-concepts/context)、[《Cody FAQs》](https://sourcegraph.com/docs/cody/faq) |
| OpenHands | 超过阈值后总结较旧交互，保留近期交换；摘要记录目标、进度、剩余任务、关键文件与失败测试。 | 解决轨迹增长，不能独自解决首周期巨量状态。[《OpenHands Context Condensensation for More Efficient AI Agents》](https://www.openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents) |
| SWE-agent | ACI 提供搜索摘要、最多 100 行的文件窗口，以及总行数和省略行数；搜索超过 50 项时明确要求缩小查询。 | 借鉴“明确显示未展开量”，但调度场景还需保证可枚举地取完。[《SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering》](https://arxiv.org/html/2405.15793v3) |
| Devin／Cognition | 2025 年文章介绍用专门模型压缩行动与对话中的关键决定；2026 年进一步支持多 agent 提供分析、写入保持单线程。 | 公开资料支持压缩与协调原则，未找到完整、可复现的 Devin 上下文选择算法。[《Don’t Build Multi-Agents》](https://cognition.com/blog/dont-build-multi-agents)、[《Multi-Agents: What’s Actually Working》](https://cognition.com/blog/multi-agents-working) |

**推断：最佳迁移单位是接口模式，而非整套编码 agent。**文件路径可替换为 `snapshot_id/entity_id`；repo map 可替换为工艺族、设备族和待处理工作目录；文件窗口可替换为有计数、游标和版本的实体页。

## 三、长期运行：外部记忆、压缩与缓存

### 3.1 四类策略分别解决什么

LangChain 原文分类为：

- **Write**：把信息写到上下文之外，如笔记、持久状态。
- **Select**：选择当前步骤需要的信息。
- **Compress**：摘要或裁剪已有上下文。
- **Isolate**：让不同任务在隔离上下文中执行。

LangGraph 的 checkpoint 和 store 提供持久化基础，节点决定实际向模型暴露哪些状态。[《Context Engineering》](https://www.langchain.com/blog/context-engineering-for-agents)

OpenAI Agents SDK 的官方示例展示了保留最近 N 个用户回合的 `TrimmingSession`，以及总结旧历史的做法。这里一个“回合”包含用户消息之后的全部工具交互。**推断：无人值守仿真可能一个用户回合包含数百次调用，不能只按用户回合数设预算。**[《Context Engineering — Short-Term Memory Management with Sessions》](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory)

Responses API 也支持达到 `compact_threshold` 后服务端压缩，生成携带先前关键状态的不透明 compaction item。该机制不提供业务对象逐项保真的证明。[《Compaction》](https://developers.openai.com/api/docs/guides/compaction)

### 3.2 Manus：可恢复的压缩与稳定前缀

**原文：**Manus 报告平均输入／输出 token 比约为 **100:1**，典型任务约 **50 次工具调用**；建议稳定 prompt 前缀、确定性序列化和追加历史，以提高缓存复用。其外部记忆设计强调：删除上下文中的网页正文时保留 URL，省略文件正文时保留路径；错误证据也应保留。[《Context Engineering for AI Agents: Lessons from Building Manus》](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)

需要区分两个概念：Manus 的 **“Mask, Don’t Remove”指工具可用性的解码约束**，不是遮蔽旧工具结果；后者是另一类 observation masking。

**推断：**晶圆厂状态应保留版本化快照，不能只保留指向“最新状态”的 ID，否则旧观察无法恢复。稳定前缀也不意味着无限追加：可在一个决策周期内追加，在周期边界重建上下文。缓存降低重复输入成本，却不能让超窗口输入变得可接受。

### 3.3 长时任务需要未完成清单

Anthropic 的长时 harness 示例先建立完整功能清单，示例超过 **200 项**，全部初始化为未通过；后续 agent 逐项实现、测试，并通过进度文件和 Git 历史恢复工作。文章明确约束 agent 不删除功能测试来制造完成假象。[《Effective harnesses for long-running agents》](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

**推断：**可以迁移“未完成集合独立于摘要”的原则，但不能照搬其生成方式。晶圆厂工作全集应由模拟器状态确定性生成，不能让 LLM 自己列举全集，再用这个可能漏项的清单检查自己。

## 四、子 Agent 隔离上下文：收益与协调成本

**原文：**Anthropic 的研究系统采用主 agent 分解任务、子 agent 独立搜索并汇总。其内部研究评测中，Opus 4 主 agent 配 Sonnet 4 子 agent，相比单独 Opus 4 提升 **90.2%**；文章同时报告 agent 约消耗普通聊天 **4 倍** token，多 agent 约 **15 倍**。这些是不同交互形态的经验数据，不能换算为同等质量下的固定倍率。[《How we built our multi-agent research system》](https://www.anthropic.com/engineering/multi-agent-research-system)

该系统通过明确子任务边界、输出要求和工作分工减少重复；结果汇总让探索细节留在子上下文。但摘要可能丢失跨任务依赖，协调和重复读取也会增加总成本。

Cognition 的观点有时间变化：2025 年强调分散行动会携带冲突的隐含决定；2026 年认为多个 agent 提供智能、写入保持单线程的模式已具实用性。[《Don’t Build Multi-Agents》](https://cognition.com/blog/dont-build-multi-agents)、[《Multi-Agents: What’s Actually Working》](https://cognition.com/blog/multi-agents-working)

**推断：**本项目不宜默认让多个 agent 分别提交设备计划。共享设备、批次兼容性和全局优先级会造成耦合。更适合先试验“子 agent 只读分析，主 agent 统一决策并原子提交”，同时把所有子请求计入成本；主上下文变小不等于系统总 token 下降。

## 五、量化证据：上下文大小与查询轮数如何取舍

| 研究／实验 | 原始结果与条件 | 能支持什么 |
|---|---|---|
| Cursor 动态 MCP 发现 | 在**实际调用 MCP 的运行**中，A/B 测试总 agent token 减少 **46.9%**；随安装 MCP 数量有较大方差。 | 支持工具说明按需加载；不是任意环境快照压缩比例。[《Dynamic context discovery》](https://cursor.com/blog/dynamic-context-discovery) |
| Cursor 语义搜索 | 内部 Context Bench 中，有语义搜索相对无语义搜索，问答准确性平均提高 **12.5%**，模型间范围 **6.5%–23.5%**。 | 支持改进检索工具；原文未给统一完整成本表，不能解释为节省多少请求。[《Improving agent with semantic search》](https://cursor.com/blog/semsearch) |
| OpenHands condenser | SWE-bench Verified 子集：平均解决率 **54% 对 53%**；长会话每轮 API 成本降到基线一半以下，但压缩增加部分轮次。 | 支持压缩旧轨迹；正文未充分报告子集规模等细节，不作严格复现实验结论。[《OpenHands Context Condensensation》](https://www.openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents) |
| Observation masking 对比摘要 | SWE-agent、SWE-bench Verified 500 题、最多 250 轮；Qwen3-Coder 480B：原始／遮蔽／摘要成本为 **$1.29／$0.61／$0.64**，解决率 **53.4%／54.8%／53.8%**，按表格数据。遮蔽保留最近 10 轮观察。 | 遮蔽可省 **52.7%** 成本；该论文公开代码和数据，但结果限于其 scaffold 与任务。[《The Complexity Trap》](https://arxiv.org/html/2508.21433v1) |
| RAG 与长上下文 | 九个 LongBench／∞Bench 子任务；Contriever 设置下，GPT-4o 的平均分：全量 LC **48.67**、RAG **32.60**、Self-Route **48.89**；Self-Route 输入 token 为 LC 的 **61.40%**。 | 全量上下文可能质量更高；路由可接近其质量并减少输入，不能据此证明多轮调度查询更优。[《Retrieval Augmented Generation or Long-Context LLMs?》](https://arxiv.org/html/2407.16833v1) |

Observation masking 的结论并非普适：同一论文在 OpenHands 的 50 题探索实验中，原始、遮蔽、摘要解决率分别为 **40%、30%、42%**。历史处理必须按 harness 验证。[《The Complexity Trap》](https://arxiv.org/html/2508.21433v1)

**证据缺口：**未找到直接针对 SMT2020、固定同一模型和调度权责，比较“75.6 万 token 一次输入”与“小上下文多轮 MCP 查询”的公开实验。现有研究分别评估检索、历史压缩或工具说明，不能把这些节省比例相乘。

**推断：**多轮方案的成本取决于每轮重读多少上下文、缓存命中、查询粒度及返工次数。批量查询可减少往返；过细分页会提高请求数；过大页又增加无关输入。应测完整决策周期，而非单次 prompt 长度。

## 六、对我们问题的可借鉴做法

以下均为设计建议，不是来源已验证的晶圆厂效果。依据上述即时读取、可恢复记忆、完整未完成清单及批量工具设计。

### 6.1 把完整快照拆成“常驻规则＋完整目录＋按需明细”

常驻内容保留目标、硬规则、三个 MCP 工具契约；工艺路线和机组静态表存于版本化外部状态。每周期提供按设备族、工艺族分组的工作目录，包括数量、状态范围、明细句柄；分组必须覆盖全集。

**不遗漏：**满足，前提是每个可排程工序属于可见目录，且能通过查询枚举。只返回高优先级 top-k 不满足。

**成本：**预计显著降低固定输入，增加部分查询。当前固定前缀约占总量 74.6%，但规则仍需保留、明细仍会读取，不能把该占比当节省率。依据：[《Repository map》](https://aider.chat/docs/repomap.html)、[《Effective context engineering》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)。

### 6.2 为 `read_entities` 增加完整性协议和批量投影

建议返回：

```text
snapshot_id, query_scope, total_count, returned_count,
next_cursor, complete, entity_ids, fields
```

支持多 ID、字段选择、稳定排序，以及一次读取某组候选的工序参数、兼容机组和占用状态。预算不足必须返回明确的剩余量与游标，不能静默截断。

**不遗漏：**通过服务端集合核对保证枚举完整；计数相等之外还要检测重复和缺项。**成本：**字段投影减少 token，批量查询减少请求；分页大小须实测。依据：[《SWE-agent》](https://arxiv.org/html/2405.15793v3)、[《Codex Prompting Guide》](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide)。

### 6.3 把“未处理工作”纳入 `validate_plan`

令 \(W\) 为该快照全部可排程工序，\(P\) 为模型拟排程集合，\(D\) 为模型明确决定暂缓的集合，返回：

\[
U=W\setminus(P\cup D)
\]

`validate_plan` 同时报告约束错误、未处理集合 \(U\) 的数量和查询入口，以及有兼容候选却仍空闲的设备。暂缓必须由模型表达理由；校验器只反馈，不自动添加、删除或修改任务。

**不遗漏：**满足并增强可审计性；集合覆盖不证明模型真正理解每项，也不保证排程最优。**成本：**增加少量反馈；异常时增加修订请求，但可合并进现有校验调用。依据：[《Effective harnesses for long-running agents》](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。

### 6.4 在周期边界重建上下文，限制历史长度

提交后保存完整外部审计记录；下一周期只加载当前状态目录、尚有效的模型承诺、未解决问题及有限近期错误。历史查询结果用快照句柄恢复，避免递归摘要成为事实来源。周期内仍设置硬 token 预算，为查询、校验反馈和输出预留空间。

**不遗漏：**以模拟器当前工作全集为依据，不靠摘要恢复工作。**成本：**上下文不随仿真时长增长；可能损失部分缓存，偶尔需要回查。依据：[《Compaction》](https://developers.openai.com/api/docs/guides/compaction)、[Manus 上下文工程经验](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)。

### 6.5 缓存稳定内容，并验证快照版本

规则、工具说明、静态 schema 使用稳定顺序序列化；时间和动态状态放在其后。查询、校验与提交绑定同一 `snapshot_id`；版本不一致时显式失败并重新决策。缓存失效不影响正确性。

**不遗漏：**满足，版本检查防止把过期目录当作当前全集。**成本：**提高缓存复用可能降低未缓存等效输入；重新取快照会增加异常路径请求。依据：[Manus 上下文工程经验](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)。

### 6.6 多 Agent 仅作为后续对照方案

先建立单 agent 的完整目录与批量查询基线。需要拆分时，子 agent 返回候选建议、实体 ID、依赖和未覆盖范围，主 agent 决定任务、机组、组批及队列，统一提交。

**不遗漏：**必须合并并核对各子任务覆盖集合，不能只收自然语言摘要。**成本：**主上下文可能缩小，总 token 和请求数可能增加。依据：[《Multi-Agents: What’s Actually Working》](https://cognition.com/blog/multi-agents-working)。

### 6.7 按模拟小时评测，而非只比较 prompt

建议对比：可运行的小规模全量基线、完整目录＋批量查询、再加周期重建、最后增加只读子 agent。固定模型、初态、随机种子和决策触发规则；完整规模的超窗口基线记为不可运行，禁止截断后冒充全量。

分别报告：

\[
C_{\mathrm{in}}=\frac{\sum_i(U_i+\rho_iH_i+\omega_iW_i)}{\text{模拟小时}},
\qquad
C_{\mathrm{req}}=\frac{\text{全部模型请求数}}{\text{模拟小时}}
\]

其中 \(U\) 为普通未缓存输入，\(H\) 为缓存读取，\(W\) 为单独计价的缓存写入；权重取实际价格比例，避免重复计费。摘要、重试和子 agent 请求全部计入；另报输出成本、吞吐、延期、非法计划及有可排工作时的设备空闲。

验收首先要求全集可枚举、提交覆盖可核对、长时上下文有界，再寻找成本与调度质量的可接受组合。这个实验设计来自上述证据的边界：现有文献证明了多种压缩和检索方法有价值，尚未证明哪一种在本项目中最优。