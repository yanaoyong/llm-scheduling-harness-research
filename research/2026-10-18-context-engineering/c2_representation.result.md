# 结构化状态表示、压缩与长上下文可用性调研

调研日期：2026-10-18。本文将“来源结果”与“本项目推断／建议”分开；论文中的准确率不直接等同于晶圆厂调度质量，官方缓存规则按模型与接口版本区分。

## 一、核心判断

**对当前约 75.6 万 token 的快照，优先方案是“无损结构压缩＋完整工作目录＋按需读取＋有界当前状态”，缓存作为成本优化叠加。** 单纯换格式或启用缓存，都不足以证明能够在 22 万预算内可靠完成全量决策。

根据项目提供的数据，固定前缀约占总量的 74.6%；从 75.6 万降至 22 万，至少需要减少 70.9%，还未预留输出、推理和工具返回空间。上述比例为本报告计算；56.4 万与19万之和略低于总量，是原始近似数的差异。

以下证据支持三个判断：

- 格式会影响 token 和准确率，但不存在跨模型、跨任务通用的最佳格式。
- 缓存降低重复输入的计费与预填充开销，不能把被缓存的数据从上下文预算中扣除。
- 百万 token 的接口容量不等于模型能可靠枚举、关联并安排其中上千条工作。现有公开评测不能为本项目的全量调度提供保证。

## 二、结构化数据格式：压缩率与准确率必须一起测

### 2.1 JSON、CSV、Markdown、YAML 的直接比较

**来源结果：** Improving Agents 使用 GPT-4.1-nano，输入1,000条合成员工记录，每条8个属性，测试1,000个数据查询问题，比较11种表示。部分结果如下：

| 格式 | 输入 token | 准确率 |
|---|---:|---:|
| JSON | 66,396 | 52.3% |
| YAML | 55,395 | 54.7% |
| Markdown 键值块 | 52,104 | 60.7% |
| Markdown 表 | 25,140 | 51.9% |
| CSV | 19,524 | 44.3% |

CSV 比该实验中的 JSON 少约70.6% token，但准确率低8个百分点；Markdown 表少约62.1%，准确率接近。百分比节省为根据原表计算。实验只覆盖一个模型和一种数据形状，而且没有定期重复表头，不能推出“CSV普遍较差”。[Which Table Format Do LLMs Understand Best?](https://www.improvingagents.com/blog/best-input-data-format-for-llms)

**本项目推断：** 表头只写一次节省重复键名，却增加远距离列对齐风险。机组、lot、候选工序适合先试“分块表头＋短行”；规则和不规则约束适合保留键值结构。不能把上述70.6%直接乘到整个快照上，因为规则、路线和嵌套关系未必具有同样冗余。

### 2.2 TOON：有收益，但须选择公平基线

**来源结果：** TOON 项目当前基准使用244个问题、4个模型，token统一按 `o200k_base` 计算。总体结果：

| 格式 | 平均 token | 准确率 |
|---|---:|---:|
| TOON | 2,474 | 72.2% |
| 紧凑 JSON | 2,892 | 69.0% |
| 格式化 JSON | 4,308 | 71.4% |
| YAML | 3,487 | 70.1% |

相对格式化JSON，TOON节省42.6%；相对紧凑JSON只约14.5%。在共同的109个平表问题上，CSV为1,851 token、62.2%，TOON为1,994 token、63.1%；准确率置信区间明显重叠。测试模型包括 Claude Haiku 4.5、Gemini 3.6 Flash、GPT-5.4-nano、Grok 4.5。这是格式项目自身提供的可复现基准，应保留利益相关和版本变化的限定。[TOON — Benchmarks](https://github.com/toon-format/toon#benchmarks)

TOON的主要价值是把规则对象数组写成“数量＋一次字段声明＋多行值”，同时支持嵌套。**本项目推断：** 它值得进入候选集，但纯平表先比较CSV；复杂稀疏结构还应比较紧凑JSON。格式说明、示例、转义规则也必须计入总token。

### 2.3 “列式”与“表头一次”不能混为一谈

CSV是共享表头的行式表示；真正列式表示是各字段分别保存数组。两者都可去掉重复键名，但列式需要依靠索引维持跨字段对应关系。

**来源结果：** 一项2026年预印本比较YAML、Markdown、JSON、TOON，在11个模型、9,649次SQL生成实验、10至10,000张表的schema上，格式对总体准确率的影响不显著，`p=0.484`；个别模型仍有格式偏好。作者还发现，紧凑文件可能因搜索返回密度和陌生格式带来运行时token开销。[Structured Context Engineering for File-Native Agentic Systems](https://arxiv.org/abs/2602.05447)

**证据边界：** 本次未找到足以证明“纯列式优于共享表头行式”的通用LLM理解基准。上述SQL实验也不是逐条调度。应把数据字节数、首次输入token、整个工具循环token分别测量。

## 三、字典编码、分组与差分

### 3.1 字典编码／ID化

**来源结果：** 2026年预印本以短符号替换重复子串，并把字典放入上下文。在LogHub 2.0、Claude 3.7 Sonnet上，模板压缩的解压精确匹配率超过0.99；算法压缩的平均Levenshtein相似度超过0.91，报告压缩率为60%—80%。[Lossless Prompt Compression via Dictionary-Encoding and In-Context Learning](https://arxiv.org/abs/2604.13066)

**限制：** 实验主要用解压作为分析能力的代理任务。编码算法可逆，不代表模型每次解释都正确；0.91相似度更不能证明机组资格、加工时间或hold状态无误。

**本项目推断：** 可将重复路线、资格集合、配方、setup族编码为稳定ID，但保留少量语义提示，例如 `etch_recipe:R17`。节省条件是：

\[
重复次数\times(原表示token-引用token)>字典与说明token
\]

字符更短不必然token更少，尤其是随机哈希；必须实测tokenizer，并测试ID关联错误。

### 3.2 “类别＋成员列表”属于结构因式分解

建议表示共同属性一次，再列出全部成员及差异，例如：

```text
class C7: recipe=R17, eligible_set=E4, process_min=42
members{lot_id,due_min,priority}:
L12,180,2
L18,240,1
```

**本项目推断：** 若有 \(n\) 个成员、共同属性耗费 \(A\) token，理想毛节省约为 \((n-1)A\)，再扣除类别引用与表头。成员ID、数量、独有属性和例外必须保留；只剩“某类有100个lot”的统计摘要不足以支持逐项选择。

本次未找到针对这种分组方式、同时测量晶圆厂调度准确率与token收益的公开研究。它应视为可验证的工程方案，不能宣称已有可靠节省比例。

### 3.3 差分节省传输，不自动解决上下文增长

**来源结果：** OpenAI说明，即使通过 `previous_response_id` 继续对话，链中的既往输入仍计为输入token。[Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)

**本项目推断：** 不断追加“上一状态＋变化”会使上下文随周期增长。差分应在harness侧按版本应用，形成新的权威当前状态；模型侧只保留有界基线与有限变化，定期重建。协议至少包含 `base_version`、`new_version`、新增、更新、删除和校验值，版本不一致时显式重读。

本次未找到可直接外推到本任务的“只发变化且准确率不降”的量化证据。

## 四、提示缓存：成本、命中与上下文容量

### 4.1 三家规则

| 提供方 | 计费与命中条件 | 对本项目的意义 |
|---|---|---|
| OpenAI | 当前文档区分代际：GPT-5.6及以后最低1,024个可见输入token，写入通常1.25倍，读取通常0.1倍，GPT-6.1 Sol为0.05倍；TTL为30分钟。较早模型采用不同自动缓存与保留规则，且无额外写入费 | 必须按所用模型配置，不能继续假定所有OpenAI缓存都“自动且写入免费” |
| Anthropic | `cache_control`支持自动或显式断点；5分钟写入1.25倍、1小时写入2倍；多数模型读取0.1倍，新模型有0.05／0.025倍例外；门槛按模型不同 | 将断点放在真正稳定前缀末尾；工具、系统消息、普通消息顺序及内容变化会影响命中 |
| Gemini | 支持隐式缓存；受支持的Gemini 2.5／3模型可通过generateContent使用显式缓存，默认TTL一小时并收存储费。Interactions接口仅支持隐式缓存 | 需同时核对模型和接口，不可假定所有Gemini均支持显式缓存 |

来源：[OpenAI — Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)、[Claude — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)、[Gemini — Context caching](https://ai.google.dev/gemini-api/docs/generate-content/caching)。

具体价格例子：Gemini 2.5 Flash标准文本输入为每百万token 0.30美元，缓存读取0.03美元，显式缓存存储每百万token每小时1美元。因此读取便宜90%，并不意味着包含存储后的总账单便宜90%。[Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)

**来源结果：** OpenAI《Prompt Caching 201》报告2,300次提示测试：1,024 token输入的TTFT改善7%，150k以上输入改善67%；Anthropic公开声明长提示延迟最多降低85%。这些不是本任务端到端调度延迟的保证。[Prompt Caching 201](https://developers.openai.com/cookbook/examples/prompt_caching_201)、[New capabilities for building agents on the Anthropic API](https://www.anthropic.com/news/agent-capabilities-api)

### 4.2 缓存是否减少上下文占用？

- **Google明确说明：** 缓存内容是提示前缀，模型不区分缓存与普通输入，token上限包含缓存token。[Context caching — Additional considerations](https://ai.google.dev/gemini-api/docs/generate-content/caching)
- **OpenAI：** 本次未在缓存指南找到同一句直接表述；其上下文指南定义单请求窗口包含输入、输出和推理token。结合缓存仍作为输入计量，可推断缓存不扩大窗口。[Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- **Anthropic：** 缓存指南描述重用前缀；上下文指南定义窗口容纳历史与新输出，没有赋予缓存内容额外容量。这里同样是结合两份文档的推断。[Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)、[Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)

**本项目计算：** 假设56.4万固定前缀全部命中、读取系数0.1，19万动态状态不命中，则稳态输入约为24.64万“未缓存等效token”；实际上下文仍约75万。冷启动、写入、失效及后续工具轮次还需另外计算。缓存无法解决22万物理预算。

## 五、长上下文：容量与实际能力的差距

### 5.1 四类互补证据

| 研究 | 来源结果 | 适用边界 |
|---|---|---|
| Lost in the Middle，2023／2024 | 多文档问答、键值检索中，相关信息位于首尾时通常优于中间 | 证明位置敏感性，不是当前所有模型的固定退化曲线 |
| RULER，2024 | 13项合成任务覆盖检索、多跳、聚合等；单针成绩好不能保证复杂任务表现 | “有效长度”依赖任务与阈值 |
| NoLiMa，2025 | 13个声称支持至少128K的模型中，11个在32K时低于短上下文基线的一半；GPT-4o从99.3%降到69.7% | 问题与目标尽量不共享字面线索，考查隐含关联 |
| Chroma Context Rot，2025 | 测试18个模型，通过语义检索、干扰项、LongMemEval、重复词任务观察长度影响；性能随长度非均匀变化 | 不提供可通用于所有任务的“安全窗口” |

来源：[Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)、[RULER: What’s the Real Context Size of Your Long-Context Language Models?](https://arxiv.org/abs/2404.06654)、[NoLiMa: Long-Context Evaluation Beyond Literal Matching](https://arxiv.org/abs/2502.05167)、[Context Rot: How Increasing Input Tokens Impacts LLM Performance](https://www.trychroma.com/research/context-rot)。

RULER公开榜单还给出具体对照：

| 模型 | 标称窗口 | 榜单有效长度 | 4K分数 | 128K分数 |
|---|---:|---:|---:|---:|
| GPT-4-1106-preview | 128K | 64K | 96.6 | 81.2 |
| Llama 3.1 70B | 128K | 64K | 96.5 | 66.6 |
| Gemini 1.5 Pro | 1M | >128K | 96.7 | 94.4 |

该榜单以Llama-2-7B在4K的85.6分作为参考阈值；“>128K”不表示已验证1M。历史模型结果也不能充当2026年模型排名。[NVIDIA/RULER — Results](https://github.com/NVIDIA/RULER)

### 5.2 “针多”为什么更接近本任务？

**本项目推断：** 找一个lot、找出所有符合条件的lot、对所有lot安排机组和队列，是三个不同难度的任务。后两者要求覆盖率、跨表关联、资源互斥、组批与顺序一致性；平均问答准确率会掩盖少量持续遗漏。

作为数学示例，若1,000项独立判断每项成功率99.9%，全部正确的概率也只有约36.8%；实际错误通常相关，因此该数值仅说明评估“整批正确”的必要性，不是模型性能预测。

**结论：** 几十万token全量输入在部分接口上可容纳，但本次未找到“75万token结构化状态＋上千项联合调度”可靠完成的公开证据。可以保留为实验基线，不宜作为唯一架构。

## 六、单次输入与工具结果的官方限制

**OpenAI：** 窗口大小按模型确定，且需容纳输出及适用的推理token。例如GPT-4.1文档列出1,047,576上下文窗口和32,768最大输出，二者不能理解为可同时填满的独立额度。[GPT-4.1 Model](https://developers.openai.com/api/docs/models/gpt-4.1)、[Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)

**Anthropic：** 当前文档中，Sonnet 4.6、Opus 4.6等支持1M窗口，部分其他模型为200K；Messages请求体另有32MB上限。字节上限和token上限是两项约束。[Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)、[Claude API errors](https://platform.claude.com/docs/en/api/errors)

**工具结果：** 本次未找到OpenAI／Anthropic基础API对所有自定义工具统一规定的独立结果token上限；不能据此认定结果无限大，它仍受整体请求和上下文限制。OpenAI函数调用指南允许应用返回工具输出，但不意味着MCP客户端不会另行截断。[Function calling](https://developers.openai.com/api/docs/guides/function-calling)

Claude Code明确规定MCP输出超过10,000 token警告，默认最大25,000，可通过环境变量调整。这是Claude Code客户端规则，不能误写成Anthropic API通用限制。[Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp)

## 七、对我们问题的可借鉴做法

以下均为结合上述证据的设计建议，收益需要在SMT2020真实快照上验证。

| 设计 | 如何满足“不静默丢弃工作” | token与请求次数预期 |
|---|---|---|
| **完整候选目录常驻** | 每个可开工工序均有稳定ID、关键调度字段、详情引用；若分页，给出总数、游标、未读数量和快照版本 | 显著减少详情输入；按需读取增加请求，用批量ID查询控制 |
| **静态路线、机组表按ID外置** | 全量数据保留在权威存储，目录明确提供查询路径；不是只保留检索top-k | 优先削减56.4万固定部分；首次详情读取增加往返，跨轮批量复用可摊薄 |
| **共享表头＋稳定字典＋共同属性分组** | 必须可确定性还原；保存全部成员、差异及例外，做往返一致性和ID集合校验 | 结构性减少重复；一般不增加请求，但可能增加模型关联难度 |
| **差分在harness侧合并，模型定期重建上下文** | 版本连续性、删除事件、校验和不一致时显式失败或重读 | 当前状态规模有界；重建会增加冷输入，但避免历史无限增长 |
| **缓存稳定核心** | 缓存内容只包含规则、schema、工具及稳定字典；时间戳和动态状态后置 | 降等效输入和TTFT；不降物理token，通常不增加模型请求 |
| **查询结果显式预算与分页** | 返回 `total_count`、`returned_count`、`next_cursor`、`truncated`，禁止伪装成完整列表 | 防止一次工具返回撑爆窗口；分页可能增加请求，支持字段投影和多组批量读取 |

按需读取的工程依据来自Anthropic的轻量引用与即时加载实践；但编码agent的相关性检索不能直接保证调度工作全集，因此必须补充完整目录与覆盖检查。[Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

建议进一步在 `validate_plan` 中报告：候选全集数量、可查询性缺口、重复工序、未知ID，以及有兼容工作时仍空闲的机组。**这些检查提供事实与遗漏提示，不替模型选择任务、组批或队列。** 模型可以有意延期，但“未排程”“未读取”“不可访问”必须分别记录。

成本按模拟小时统一计算：

\[
C_{\mathrm{eq}}/H=
\frac{\sum(T_{\mathrm{普通}}+wT_{\mathrm{写入}}+rT_{\mathrm{读取}})
+\text{存储费折算token}}{H}
\]

同时独立报告模型请求数 \(N/H\)，除非明确给出请求权重，否则不要把两项任意相加。缓存TTL按真实墙钟时间计算，不能按仿真时间判断。

最终应对同一批真实快照比较紧凑JSON、分块CSV、Markdown表、TOON和分组字典表示；除token外，测量候选枚举召回率、资格关联错误、整计划合法率、空等时间、吞吐及重试次数。长时间运行还应验证上下文峰值不随累计仿真时长增长。**先证明数据覆盖完整，再用调度质量与每模拟小时成本选择表示方案。**

> **编排者更正（2026-10-18）**：§2.2 的 TOON 数字与原文不符。原文混合结构轨道总 token 为 TOON 264,734、紧凑 JSON 260,451、格式化 JSON 393,637、YAML 314,140；TOON 比紧凑 JSON 略多 token，仅比格式化 JSON 省约 33%。见 SYNTHESIS.md。
