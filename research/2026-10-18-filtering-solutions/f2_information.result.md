# 主题二：模型应当知道什么，以及怎样付出可控的信息成本

调研日期：2026-10-18。本文只提出选择，不批准或实施展示规则。覆盖审计问题 1 的字段投影部分、5、7，以及 F02 查询能力；不决定 lookahead、唤醒和匹配算法。

## 证据与成本口径

已先通读[《Harness 过滤审计》](../../docs/updates/2026-10-17/project/experiments/harness_v6_20261017/reports/harness_filtering_audit_20261018.md)，再核对当前源码、搜索文献。下文 `V6/` 指 `docs/updates/2026-10-17/project/experiments/harness_v6_20261017/`；源码位置相对 `V6/src/harness_v6/`，`物理/` 指 `/workspace/v6-mac-env/physical/src/smt/`。审计行号与当前源码有少量偏移，以下采用本次读取的位置。

**仓库事实：**审计第 77–136 行记录 G0 有 4,349 条公开工序、1,011 条未预留 ready、23 个 pending task、907 个 running job；第 144–167 行列出缺失字段。`snapshot.py:70–85` 的 ready 投影省略了它们，`facts.py:14–35,163–176` 则保留完整公开记录。`single_action.py:1` 明确无工具，因此“可查询”不能用来证明单动作模式信息完整。

**实测与估算分开：**审计第 420–429 行唯一可直接引用的本题 section 测量，是 74 条 upcoming 的 explicit 3,536 / dense 2,919 token，约每条 48 / 39 token，不能据此断言任一新增字段的真实成本。下文字段估算假设表头只写一次，每个普通标量连分隔符约 2–6 token：1,011 行每加一列约 2.0–6.1k token；短布尔/整数约 2.0–3.0k。JSON 重复键更贵，dense 常量更便宜。这些都是预算量级，未运行 tokenizer 或模型实验。

硬约束记为 H1：工作不能既不可见又不可查；H2：事实优先、增加信息；H3：选机、组批、排序仍由模型决定。下文“满足”只指方案覆盖的边界；不表示解决了 A01/A03 未导出工序等全局问题。固定 schema、路由和规则可以不随仿真时间增长；当前 WIP 仍可能增长，固定历史长度不等于固定快照大小。

## 一、ready 缺少 22 个字段，应补哪些？

### 白话解释

假设两批晶圆都能进同一台机器，一批马上到交期，另一批还有一天；只给 ID 和可用机号，模型无法按交期选择。G0 的 1,011 条 ready 就普遍缺少这类比较依据。给出交期不是要求模型执行 EDD，而是允许它自己决定交期和换型效率谁更重要。

还有语义陷阱：`observation.py:22,198–213` 的 `remaining_work_seconds` 是**当前步骤之后**的名义加工均值之和，不含当前加工、排队、未来换型及完整运输，也未按返工概率展开；不能直接称为预计完工时间。`processing_seconds` 包含装卸，`occupation_seconds` 对 cascading 设备表示另一种占用时长，两者不能混用。以上均为源码事实，不是文献推测。

### 文献与业界依据

**来源原文：**Mönch 等的[《A survey of problems, solution techniques, and future challenges in scheduling semiconductor manufacturing operations》](https://doi.org/10.1007/s10951-010-0222-9) 将批处理、并行机、辅助资源等作为不同调度问题讨论。它支持保留不同约束的信息，不能证明某一种派工规则普遍最佳。

Pickardt 等的 WSC 论文[《Generating dispatching rules for semiconductor manufacturing to minimize weighted tardiness》](https://www.informs-sim.org/wsc10papers/230.pdf)，第 3.2–3.4 节列出规则及加工时间、剩余加工、等待时间、交期、权重、换型和同批族数量等输入。按其规则与本仓库字段作如下**工程映射**，不把公式放进 harness：

| 调度思路 | 模型需要的事实 | 本项目的注意点 |
|---|---|---|
| FIFO / priority FIFO | 入队时刻、业务优先级 | 用 waiting_since；release_time 不等于入队时刻 |
| EDD | due | 交期是 lot 交期，不是本工序承诺完成时刻 |
| CR | due、当前时间、剩余工作 | CR 常用“距交期时间/剩余加工”；本字段不含当前步骤，必须说明口径 |
| SPT / WSPT | processing_seconds、权重 | priority 是业务等级，是否转换为惩罚权重需明确，不能擅自等同 |
| ATC / ATCS | 交期、加工、权重；ATCS 再加换型时间 | 校准参数、剩余路线修正和排序都应由模型决定 |
| setup-aware / batching | 当前 setup、转换表、批兼容键、上下限、候选到料 | 不把“等满批”写成 harness 自动策略 |

**来源原文：**[《SMT2020—A Semiconductor Manufacturing Testbed》](https://doi.org/10.1109/TSM.2020.3001933) 第 II 节要求表示交期、hot lot、抽检、批处理、换型和停机；这说明它们属于该问题的组成部分，不证明每列都必须逐行重复。

**LLM 证据：**[《LLMs can Schedule》](https://www.lamsade.dauphine.fr/~cazenave/papers/LLMsCanSchedule-DSO-2025.pdf) 第 4 节把 job、operation、机器、时长、工序顺序写入输入，目标是 makespan；其小规模 JSSP 不等于包含交期、抽检、换型的 full fab。[《LLM actor-critic based dispatching rule generation for dynamic job shop scheduling》](https://doi.org/10.1016/j.cirp.2026.04.007) 的公开正文片段列出到达、交期、加工时间、故障和维修特征，但属于规则生成路线。**本次未找到**对本题 22 字段逐项删减的 LLM 对照结果；不能声称补字段必然提升某个百分比，也不能用规则生成论文授权 harness 代替模型派工。

### 逐字段评估

下表“成本”均指 G0 1,011 行**逐行显式补列**的粗估增量，单位 k token；“按需”仅适用于 MCP，单动作须提供等价可恢复信息。字段来源为 `observation.py:198–227`；价值判断是本文推断。

| 缺失字段 | 价值与风险 | 建议载体 | 粗估成本 |
|---|---|---|---:|
| due | EDD、紧迫度的基础，高 | lot 表或 ready 列 | 3–6 |
| priority | 业务等级，高；说明方向 | lot 表/常量加例外 | 2–3 |
| processing_seconds | 加工及批次占用比较，高 | 工序模板引用 | 3–6 |
| occupation_seconds | cascading 机释放判断，高 | 工序模板引用 | 3–6 |
| remaining_work_seconds | 远端紧迫度，中高；不是完工预测 | 路由后缀表，注明排除项 | 3–6 |
| waiting_since | FIFO、等待年龄，高 | 动态 ready 列 | 3–6 |
| setup_time | 显式换型覆盖值，高；null 非零 | 模板列、保留 null | 2–6 |
| transport_seconds | 后继到料和虚拟延时，中高 | 模板加例外 | 2–6 |
| lot_id | 连接交期/路线、跨任务追踪，高 | 显式关联或正式 ID 解码 | 3–5 |
| step | 定位路线、工序依赖，高 | 正式 ID 解码/列 | 2–3 |
| visit | 区分重访与原工序，中高 | 正式 ID 解码/列 | 2–3 |
| family | 阅读分组，中；eligible set 才是资格证据 | 模板继承 | 3–6 |
| conditional | 防止把名义后继当实际工作，高 | ready 区声明 false，其他区显式 | 2–3 |
| predecessor_ids | 防止越过前序，高 | ready 区声明空，其他区保留边 | 约 2；非空另计 |
| readiness_basis | 区分观察、预测、占位，高 | ready 常量，跨区显式 | 4–8 |
| qualification_basis | 解释 uncertain，中高 | 枚举字典加例外 | 5–15 |
| binding_origin_step | 查绑定来源，中；通常稀疏 | 例外表/按需 | 存在行约 2–3 token，加空位开销 |
| sampling_percent | 后继是否可能跳过，中；不是当轮随机结果 | 路由模板 | 2–3 |
| rework_percent | 后续风险，中；不能推断实际返工 | 路由模板 | 2–3 |
| terminal | 是否末步，中低；注意尾部虚拟步骤 | 模板布尔 | 2–3 |
| initial_virtual_predecessors | 解释前置折叠，中；ready 常为空 | 空默认加完整例外 | 空列表约 2；非空按长度 |
| conditional_virtual_successors | 后继抽检/返工/延时，中 | 稀疏嵌套表/按需 | 空列表约 2；非空按长度 |

表内相加不是 dense 预算。ready 判定本就要求非 conditional、无 predecessor（`ledger.py:30`），可把这些共同事实只写一次。当前 22 字段也不是完整需求清单：若扩展到其他 basis，必须保留 `same_machine_as`；不能只照 G0 缺列数组写死 schema。

**S03 的配套问题：**`delta_schema.py:38–40` 删除 task 的 machine/lot_ids/steps/visits，machine 可从 `snapshot.py:82–83` 的 orders 恢复。建议正式定义 task→operation→lot 的可逆连接，并为过期 operation 保存 task 自身事实。G0 已有 1 个 base operation 缺失，不能承诺总能反查；也不能自动取消该任务。以 23 个 task 每个增加十几至几十 token 粗估为数百至约 1k，实际随批大小变化。

### 可选方案

**A0 维持现状。**不改 S01/S03；MCP 按 ID 补查，单动作继续缺字段。H1 对已展示 ready ID 成立，但对整体单动作可预留集合不成立；H2 没新增预测、却保留缺信息风险；H3 成立。快照增量为零，全补 1,011 个 ID 至少 2 次工具查询，响应还有每实体版本等包装成本。实现零；风险是模型不知道该查、单动作无法比较交期。实验把它作为历史基线，统计缺字段造成的事实答题错误与查询数。

**A1 全量平铺补回。**改 `snapshot.py` S01/S03，并扩展 `compact.py` C01；恢复完整 ready 记录和 pending 连接。该局部边界满足 H1–H3，不能修复其他隐藏工序。前八个高价值列逐行补约 21–45k token；全部 22 列可能进入数万至十万量级，未计复杂例外。查询可减少，single_action 仍为一次请求。实现低中；主要风险是超预算会话失败。实验先离线测五状态编码与解码，再对比 A0 的信息识别，不只看最终吞吐。

**A2 分层但无损，核心信息主动提供。**改 S01/C01：动态等待时间进 ready，due/priority 放 lot 表，时长/setup/抽检放可解码模板，basis 用常量加例外；MCP 保留完整原始记录。单动作必须含所需字典，不能仅放不可点击的“可查引用”。局部满足 H1–H3。减少重复可省大量 token，但 G0 几乎每 lot 一个 ready，lot 表未必省 due；实际节省主要来自共享路线和常量。难度中高，风险是关联错误和读表负担。实验核验所有 22 字段逐值重建，并测交期比较、cascading 时长、虚拟步骤例外题。**建议 A2**，A1 作为信息充分的消融参照；不建议预计算 ATCS 排名或只保留 top-k。

## 二、全局 setup、min_runs、未来投放与保养应公开到什么程度？

### 白话解释与来源

机器当前还要连续加工几批，与切到新 setup 后要连续加工几批，是两件事。G0 有 25 台机器 `min_left>0`，330 个工序在至少一台候选机上需要换型；这不是 330 个不可加工工序，也不能与 160 个 min-setup 排除工序直接相加。

**源码事实：**`observation.py:159–163,240–249` 已有动态 min_left/min_setup、全局转换表及 min_runs，但 S05/F01 不给后两者查询入口。`物理/environment.py:181–185` 先判断无 setup/相同 setup 为零，再取工序显式 setup_time，否则查 old→new、再回退空 old、最后零。只给 route 的 setup_time 不能复原这一过程。`:228–229` 的 min-run 按 lot 数递减，不能凭名称假设按 dispatch 次数递减。

**来源原文：**[《SmartFactory Advanced Scheduling》](https://appliedsmartfactory.com/productivity-solutions/advanced-scheduling/) 说明使用上下游实时工厂数据持续更新 lot/reticle 排程；[《Simulation AutoSched》](https://appliedsmartfactory.com/productivity-solutions/simulation-autosched/) 说明可在虚拟 fab 离线试验规则和设备条件。两页没有公开本题所需的具体字段 schema，也没有证明所有客户使用同一个 min-run 规则。

[《Scheduling Maintenance》](https://help.criticalmanufacturing.com/11.0/tutorials/modules/advanced-planning-and-scheduling/scheduling/s-functionalities/sched_maintenance/) 的官方搜索摘要明确建议预生成足够维护活动以覆盖排程视野；正文抓取失败，证据仅限该摘要。SMT2020 原论文也要求建模计划和非计划停机。**推断：**公开维护计划对排程有价值，但“使用计划”不等于“泄露未来故障抽样”。本次没有找到厂商公开文档证明其通用 min_runs 与本模拟器按 lot 计数完全一致。

### 可选方案

**B0 维持现状。**S05/A11/E04 不变。H1 不直接删现有工作 ID，但 metadata 不可获取；H2 的增加信息偏好未满足，H3 满足。零新增 token/请求，实现零；风险是把空 unavailable_intervals 当作无未来停机。实验要求模型解释空表和 setup_time=null，记录误判，不能只统计计划能否被接受。

**B1 静态表进前缀，公共边界进 current。**在 `snapshot.py:29–33`、C01 增加带版本的 setup_transitions/min_runs 与执行语义；在 `facts.py` F01/S05 增加可分页 `metadata` 或独立 kind。把 forecast_limitations、unrevealed、lookahead 与导出范围写成短公共说明。H1 局部改善，H2/H3 满足。成本设转换表 S 行、min-run K 项，粗估 `10–25S + 3–8K` token 加说明；审计没有 S/K，故不给假总数。全表进前缀无额外查询，query-only 则每次取表增加工具交互且单动作仍失明。难度中；风险是规则版本与物理执行不一致。实验对显式覆盖、相同 setup、缺键回退及批量扣减逐例核对。

**B2 B1 加因果上可公开的未来信息。**改 A11/`observation.py`，提供 `public_releases`、`maintenance_rules/events` 和覆盖范围；周期投放用起点、间隔、批数、交期偏移的生成规则，避免展开到仿真终点。`物理/environment.py:71–77` 的订单规则可作为证据；`:110–124` 的日历 first_time 可能抽样，不能直接透传 manifest。只公开可由源常量和过去观察重建的计划，随机维修长度给分布/均值和标签，不给未来 draw；计件保养给规则及可观察计数，不预测模型未来会如何派工。H2/H3 满足，H1 增加未来需求知情但不创造可提交 operation ID。难度高；新增 R 个投放规则、E 个计划事件粗估 O(R+E)，若每行约 15–40 token，1,000 行即 15–40k，故需规则压缩及分页。风险是因果泄漏和把预计窗口变硬约束。实验做“同过去、不同未来随机种子”公开字段不变测试，并单测已知保养与到料任务。

**建议：先 B1，再单独批准 B2。**B2 必须区分“计划触发时刻已知、持续时间未知”和“整个事件未知”；不能把未知结束时间填成确定 unavailable_interval。未来订单可供模型考虑等批，但未导出 ID 仍不可提交，需显式说明。该建议来自上述源码及维护文档，不是已验证收益。

## 三、single_action 与 mcp_session 怎样公平比较？

### 白话解释与依据

一个人拿薄摘要直接答题，另一个人能翻完整资料并反复校验，成绩差不能全归因于“交互更聪明”。G0 的 1,069 条 H 外执行后继可在 MCP 查询，单动作看不到；4,349 个公开工序也不等于快照展示的工序全集。

**来源原文：**Anthropic [《Effective context engineering for AI agents》](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) 支持用轻量引用按需加载，也讨论预加载与检索混合。它没有证明检索一定比完整快照便宜。**推断：**要区分“同一公开事实库”“同一实际输入”“同一调用预算”；三者不是一回事。LLMs can Schedule 的完整工序输入实验也不能直接替代这里的交互对照。

### 可选方案

**C0 维持现状，只比较系统整体。**不改协议，明确标为不同信息条件。H1 对整体单动作不满足，H2 沿用现状，H3 满足；增量为零，MCP 请求随查询和校验增加。实现低；风险是报告把收益错归因于交互。实验必须列出每种模式可见字段、可达 ID、实际读取覆盖，结论只称端到端系统差异。

**C1 同信息主实验。**由 `snapshot.py`/C01 将同一批准公开集合无损提供给两种模式，MCP 可校验但不能获得额外事实；改 `single_action.py` 的输入构造及 MCP 可读边界配置。两者 ID 覆盖完整才满足 H1；H2/H3 满足。全公开 G0 4,349 行若每行 40 token 仅行体就约 174k，P2 6,516 行约 261k，这是压力估算，不是测量。难度中高，风险是同样超预算；不能为公平删掉另一方可排工作。实验在能完整容纳的冻结状态测机制差异，并把大状态不可容纳计为结果，不能静默跳过。

**C2 双轨：同信息机制实验＋自然访问系统实验。**沿用 C1 作为受控组，另设 A2+B1 的混合查询组；为单动作准备相同批准事实的完整编码。完整版本装不下时报告单动作资源限制，不宣称已实现全状态公平。H1–H3 条件同 C1。实现和实验成本较高，单次自然 MCP 输入可能减少，但请求可能增多；用成本—效果曲线比较。**建议 C2**：保留实际使用价值，同时不混淆信息与交互效应。

实验设计建议如下，尚未执行：

- 先用 G0、P2 三状态和 t0 做事实问答；比较 A0/A1/A2，检查交期、时长、绑定、setup 和虚拟前驱，不只问“是否看见 ID”。
- 冻结信息集合、模型版本、采样和推理预算、提交合同；把反馈机会作为明确变量。随后按相同初始状态、随机种子做数小时及数十小时配对仿真；策略会改变触发时刻，不强求自然轨迹会话数相同。
- 分开记录工具调用与模型请求。1,011 ID 至少两次查询，但两个工具调用可能被同一模型响应并行发出，不等于固定多两次模型请求。
- 主成本为 `Σ(未缓存输入 + α×缓存输入)/模拟小时` 与请求数/小时；α 用实际计费口径并报告，静态前缀缓存命中不能预设。工具结果、重发历史、失败和重试全部纳入。
- 同时报吞吐、延误、计划合法率、空闲、查询漏页、预算失败、峰值上下文；限制每会话历史并重建当前事实，不能累积整段仿真 transcript。固定历史也不能保证 WIP 不增长。

## 四、F02 是否应增加 range / OR？

### 白话解释与依据

模型想找“交期已过，或者优先级为某值”的工作，现在只能分别查询再合并；想找某段 release_time，只能分页取出自己比较。G0 查全 4,349 行至少 9 页，P2 6,516 行至少 13 页。查询能力不足不是直接删工序，却让完整知情更贵。

**源码事实：**`facts.py:106–139` 只支持最多 16 个 AND 的 eq/contains，`:141–162` 限 512 行并把 cursor 绑定上下文与过滤式。Anthropic 上述工程博客支持清晰、有效的检索接口；**没有找到**半导体论文或官方工程文档能证明“添加 OR 必定减少本 harness 总请求”。以下收益是基于分页语义的推断。

### 可选方案

**D0 维持现状。**F02 不改，所有目录完整可分页；对 MCP 已导出工作满足 H1，H2/H3 满足，不能补单动作。实现零；全表查询至少 9/13 次工具调用。风险是漏页和客户端合并失误。实验以人工构造结果集检查完整率、工具数和 token。

**D1 只增加比较与区间。**在 `facts.py` F02 及 `mcp_server.py` 工具 schema 加 gt/gte/lt/lte，支持同字段上下界。必须拒绝非有限数字、明确 null/absent 语义；不自动按紧迫度排序。H1–H3 满足，因为过滤完全由模型指定、原目录仍开放。结果 m 条只需 `ceil(m/512)` 页，零结果也需一次返回。比如查 G0 1,159 个执行后继需 3 页；再加模型指定 H 内范围可降到 90 条一页，但这 90 含已预留者，不能等同 74 条 upcoming。难度中；风险是误把 release<=now 当 ready。实验同时检查 basis/predecessor 条件和边界相等值。

**D2 D1 加受限 OR。**提供 `any_of` 的有限 AND 分支或等值 `in`，保留稳定源顺序、去重、matching_total、next_cursor；所有分支参与 cursor 摘要并设明确复杂度上限，超限报错。H1–H3 满足，不引入 top-k、自动阈值或“最佳候选”。难度中高。假设三个条件各 100 条且并集不足 512，可由三次查询降到一次；但并行调用原本可能仅需一轮模型推理，不能直接声称请求减少三倍。复杂 OR 的 schema 和错误恢复也耗 token。实验用穷举公共目录作为正确答案，测交集去重、空集合、缺字段、分页及跨版本 cursor。

**建议先 D1，按查询日志决定 D2。**H 外后继、交期区间是明确需求；多条件 OR 的频率暂无实测。无论采用何者，查询条件都由模型给出，不能把筛选偷偷升级为 harness 派工。

## 需要用户拍板的选择

| 问题 | 选项浓缩 | 建议与需要接受的代价 |
|---|---|---|
| ready 22 字段及 pending 连接 | A0 现状；A1 全平铺；A2 模板/常量/关联无损展开 | A2；接受解码复杂度，先测 token 和理解，A1 作对照 |
| setup/min_runs 与预测边界 | B0 现状；B1 静态表＋可查 metadata；B2 再加公共投放/保养 | 先 B1；B2 另批因果公开规则，不透传随机未来 |
| 两模式公平性 | C0 系统差异；C1 同信息；C2 双轨 | C2；接受完整单动作可能超预算，并如实报告 |
| range/OR | D0 现状；D1 区间；D2 区间＋受限 OR | 先 D1；D2 由真实查询需求决定 |

所有建议仍需用户决定；本文没有修改规则、运行长测试或调用模型 API。新增字段能否改善调度，以及压缩后能否留在预算内，均待上述实验验证。
