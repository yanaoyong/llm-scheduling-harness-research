---
artifact: dossier
flow_instance: research-harness-scheduling-20261012
stage: M0.5
run_id: m05-20261012-deep-tiered-01
engine_tier: L2
sources_disposition:
  A:
    coverage: covered
    probe_note: 冻结项目报告并回读原文；项目wiki缺失，使用rg与源文件路径回退。
  B:
    coverage: covered
    probe_note: 六方向公开检索、12组原源提取、12条论断各三次对抗核验。
  C:
    coverage: explicit_na
    na_reason: 本轮没有新增人工策展技术资料；模型与数据传输选择是执行授权，不是经验性证据。
    corpus_write: none
created_at: 2026-10-12T05:15:29.809248+00:00
---


# 工厂排程 Harness：M0.5 调研档案

本档案形成后续需求讨论的证据输入。研究对象是现有全厂基准/开发环境中的排程工程问题；现有材料不足以称为已验证的现场部署。本轮没有重跑本厂排程实验，未实施生产 harness，未决定采用任何框架。公开源码片段的隔离微检与完整项目测试分开记录。

截至2026-10-12，已有证据足以为 M1 提供职责归属、状态一致性、约束覆盖、恢复副作用及公平评测的研究材料，尚不足以选择唯一模型职责或锁定技术栈。12条 confirmed 仅表示指定源码机制或作者限定报告获得支持，不代表生产验收。直接排程、策略选择、离线规则生成和优化模型修改四条路线均应保留。优先迁移的是可审计边界和可证伪实验：程序是否只执行模型已明确的决定，压缩后信息是否仍可取回，检查器是否揭示未覆盖语义，恢复是否识别已发生的效果，以及模型是否在同条件下带来业务增量。综合阶段只整合已有证据；此前原源检索、片段隔离验证和Owner文件整理各自留痕。本轮未启动M1。

## 结论的证据强度

12 条选定论断经 36 次独立会话检查：confirmed 12，refuted 0，unverified 0。confirmed 只表示限定命题获至少两票直接证据支持；同一模型的三票不是三份独立研究，代码、README 与同项目论文也不是独立样本。少数意见与失败保留在证据账本。

功能存在、作者报告测试、本轮亲自运行测试、作者报告部署和现场验收分开记。本轮未安装运行外部项目的完整测试套件；CL-04/v2及CL-07/v1–v3做了公开源码片段的隔离微检，使用替身数据类型或后端，只验证指定逻辑，不能升级为完整框架、真实模型或本厂测试通过。作者部署描述也不替代现场收益证明。

片段隔离验证明细：[isolated-source-checks.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/isolated-source-checks.json>)；原始命令、结果与限制均保留。

## 当前实验给出的研究入口

| ID | 报告事实与边界 | 原报告锚点 | 本轮反向核对 |
| --- | --- | --- | --- |
| A-01 | B完成0–3600秒开发窗口，承担913台生产机器的排程责任；95次提交产生1071次派工，涉及841台机器，构造器/求解器调用为0。原报告的合法性与归属审计通过，不证明最优质量、实时性或现场部署。 | [line 7](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md>) | 责任913、实际841、95提交、1071派工；通过仅对当前实现约束与归属有效，不能扩张到完整工厂语义。 |
| A-02 | B后期V14+V15共779次模型调用、80次提交；输入占tokens的96.77%，缓存输入占输入的0.48%。四类机械动作占调用43.4%、tokens 43.2%。这些是可疑开销的描述，尚非可兑现节约。 | [line 39](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md>) | 原表779调用/80提交；43.4%是四类动作调用份额，43.2%是token份额。未把可合并动作统计冒充实测节省率。 |
| A-03 | B全开发沿革共1362次尝试、44,666,702个已知输入+输出tokens，另3条用量未知。包含开发与恢复的成本不能与单次A/C运行作因果或统一速度比较。 | [line 19](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md>) | 44,666,702只有已知输入+输出；另3条未知。B沿革含恢复，不能与A/C单次时间相除作公平倍数。 |
| A-04 | A/B/C一小时均完成1个lot、窗末WIP为2176、累计迟交10 lot·小时，完成工序为336/288/334；实现版本不同，不能据此得出因果质量排名。C只用constructive，未调用CP；缺少同工具固定参数的无模型消融。 | [line 13](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/ABC_1h_plan_comparison_20261012.md>) | 工序与完成lot指标分开；第59行明确C只有constructive且缺C-fixed，因此不将C表现归因于LLM或CP。 |
| A-05 | 已有语义报告列出264个CQT起点；433个初始lot处在窗口内但历史起点时间未知，1311个初始lot缺少恢复绑定所需的历史机台信息。unknown必须保留为unknown。 | [line 55](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/semantics-20261009.md>) | 原文明确CQT在adapter-v2未实现；433条历史起点未知、1311条绑定历史未知。审计通过不能推翻明确列出的语义缺口。 |
| A-06 | B归属要求lot、机器、批次、顺序与等待由模型明确决定；机械编译、检查、存储不得暗中加入启发式排程。生产混合harness与B直接排程实验需要分别定义决策归属。 | [line 55](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md>) | 归属要求按原报告与SPECIFICATION复核；合并机械动作不能替模型补机器/批次/排序/等待决策，生产混合方案另计。 |
| A-08 | A24在约16.15小时因构造器5秒预算在首个候选前耗尽而失败；C8在约1.77小时因模型通道错误失败。既有恢复检查不能证明继续执行成功。 | [lines 63–65, 90](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/B_1h_results_efficiency_and_next_budget_20261012.md>) | 核对失败原因是构造预算/模型通道，不是数学无解；没有把静态恢复证书升级为继续派工成功。 |
| A-09 | 现有材料能支持全厂基准/开发环境的研究语境，不能据此称已验证真实工厂现场部署。原始WIP是缺少加工、setup、绑定等状态的冷启动输入；完整恢复快照与稳态各需另外证明。 | [lines 16–34, 55–63](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/semantics-20261009.md>) | 查原报告固定上游包及WIP字段限制；数据规模、现实背景和在线MES部署是不同证据，不相互替代。 |
| A-10 | 当前规范研究仿真暂停期间的决策质量，模型思考墙钟没有模拟为现场继续生产的时间。因此一小时仿真完成及其质量指标不能直接证明在线收益；后续需明确思考期间旧计划、状态过期与重排的一致处理。 | [末段：当前目标是仿真暂停期间的决策质量](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/docs/smt_fullfab/SPECIFICATION.md>) | 用规范的暂停语义核对“在线实时价值”这一可能外推；模型墙钟成本与仿真质量分别计量，不把思考时长随意追加到仿真末尾。 |

内部来源只复核冻结报告与口径，未重新审计全量原始运行账本。输入哈希与原报告快照见 [source-manifest.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/inputs/source-manifest.json>)；完整内部事实登记见 [internal-context.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/inputs/internal-context.json>)。43.4%/43.2%是调用/token份额，不是已经兑现的节约率。

## 六个研究问题

### Q-01 · 模型应该承担直接排程、策略选择、规则生成还是优化模型修改？不同职责划分有何证据与限制？

现有证据支持多种职责边界，不能据此选定赢家。直接排程方面，A-01表明B完成0–3600秒开发窗口，承担913台机器责任，实际涉及841台机器，95次提交形成1071次派工，构造器和求解器调用为0；这支持当前约束下的执行与归属结果。优化模型修改方面，OptiGuide由模型生成片段、插入数据或约束位置，再执行求解代码；文本检查可关闭，放行依据是回复不含大小写敏感的DANGER，60秒Eventlet包装不能保证任意代码强制终止。OptiMUS入口串行组织初始化、目标和约束建模、代码生成及执行调试，六份JSON保存止于代码生成阶段。工具排程方面，制造演示项目由确定性EDD工具决定安排，模型解释结果；它没有证明模型在多个策略间选择的收益。策略选择方面，MEC论文仅提供相邻模拟领域的条件性控制面结果。离线规则生成仍是覆盖缺口，LLM4Schedule初读线索没有纳入12条限定核验。因此可交给M1讨论的是四路线的共同比较条件，而非提前宣布模型应只做某一种职责。

证据：CL-01, CL-02, CL-04, CL-12。边界：B审计通过不证明最优质量、完整工厂语义或现场部署。建模流程存在不证明建模正确或调试成功；演示工具分工不证明一般排程收益。四路线尚未在同版工厂任务上受控比较。生产混合方案须单独定义实验臂，不能加入B后继续称其为模型直接排程。

### Q-02 · 如何把状态整理、候选组装、校验、提交等机械步骤交给程序，同时保持决策归属？

机械步骤的可迁移边界是：程序整理公开状态、编译完整模型delta、检查、存储及执行获授权提交，同时记录每个决定的来源。依据A-06，B中的lot、机器、批次、顺序和等待均须由模型明确决定；若候选组装补选机器、排序或等待，程序已承担排程职责，必须另计归属。建议将模型请求与delta、候选及其生成者、编译产物、检查结果、授权和提交回执关联起来，记录输入状态版本、执行者、规则或求解器版本及父事件。Deep Agents说明请求前中间件与模型选择后执行的普通工具属于不同控制位置；工具可见不代表调用获许可，内置文件权限也不自动覆盖自定义提交。制造演示的solution_id仅对策略、安排和未安排列表生成截断指纹，不能替代完整输入认证、授权身份或幂等键。A-02中的四类机械动作占调用43.4%、tokens 43.2%，适合作为合并流程的调查入口。

证据：CL-03, CL-04, CL-07。边界：43.4%和43.2%是描述性份额，不能当节约率。权限效果取决于最终中间件、后端、配置和依赖版本；替换中间件可能丢失原规则。候选生成、约束检查和提交成功须分别记账，不能以一个通过标志替代决策归属。

### Q-03 · 如何管理权威工厂状态、增量上下文、按需读取与历史压缩，防止遗漏、陈旧和失真？

应在研究设计中区分权威工厂状态、模型可见公开状态、工作流检查点和摘要。A-05给出264个CQT起点，433个初始lot的历史起点时间未知，1311个初始lot缺少恢复绑定所需历史机台信息；这些unknown不能经摘要或默认值变成已知。版本化公开状态与按需读取可作为候选机制：为每个决定列出所需字段、来源、版本和失效事件，增量缺失或跨版本引用时明确失败或重新对齐。LangGraph完整逻辑快照位于super-step边界，同一步内节点writes可支持恢复，但不是每个节点完成后的完整快照；精确历史定位还需checkpoint_id，实际耐久性取决于saver及async、sync、exit配置。Deep Agents归档失败可返回空路径，在警告不阻断且后续调用成功时仍生成摘要与事件。因此摘要成功、事件建立、事件持久化和原件可取回应分别验收。

证据：CL-05, CL-06。边界：检查点不自动同步外部权威记录，复制入图的值也不自动获得外部事务语义。归档失败不证明其他检查点或业务存储中的历史已丢失。尚无本厂增量读取、断档检测或长时压缩收益验证；私有物理快照不能为降低输入成本而泄漏给模型。

### Q-04 · 如何表达与独立检查约束，验证结果来源，揭示检查器未覆盖的语义和历史状态缺口？

建议用逐条覆盖表表达约束及检查能力，列出语义、所需历史字段、输入版本、检查方法和证据，并区分通过、失败、未建模、无法判定。制造项目的OptimizationReport预检会对不可重放引用、规格不匹配或建议越界生成blocker；正常返回时，最终批准是模型批准与预检没有blocker的逻辑与。弃答跳过该预检，demo后端还可能让虚构窗口可重放，因此重放成功不能证明事实真实或语义充分。排程预检属于另一条路径，重跑求解器并比较结果可支持复现与篡改检查，但共同复用错误模型仍可能共同通过。PyJobShop直接构造Solution不检查可行性；tasks非空时在构造期间派生job数据，索引或类型异常与排程可行性检查是两回事。结合A-05，当前合法性审计必须显式披露CQT与历史绑定缺口，而不能升级为完整工厂语义认证。

证据：CL-07, CL-08, CL-11。边界：没有证据证明现成检查器与求解器实现相互独立或覆盖全部工艺规则。测试源码定义的反例不是本轮测试通过记录。对象构造成功、求解状态可行、来源可重放、业务规则完整及最优性是不同结论，须分别报告。

### Q-05 · 超时、重试、中断、重复提交、预算耗尽和回退应如何处理？工作流恢复和工厂恢复有何差异？

工作流恢复保存计算进度，工厂恢复还须核对提交目标的实际状态和已发生效果。Temporal在重试策略、超时等条件允许时安排新尝试；若代码再次执行到发送步骤，已执行但确认丢失的命令可能重发。这是设备侧条件推论，不能由持久化推出exactly-once；一次查询也可能遇到旧尝试仍执行或结果尚不可见的竞态。LangGraph动态interrupt恢复会从节点开头进入，前置普通代码可再次执行；函数式调用子图时父节点也可能重入，但已完成并持久化的task结果不必重算。幂等、后置副作用和拆节点均须结合版本与拓扑验证。候选恢复方案应关联计划版本、稳定操作身份、授权、效果状态和回执；超时后的未知结果不能直接判为未执行。A-08中的A24构造预算耗尽、C8模型通道错误分别是计算与通道失败，既有恢复检查不证明续跑成功。

证据：CL-09, CL-10, CL-05。边界：本轮没有恢复后继续派工、重复效果去重或预算耗尽处置的实测证据。重启须保留失败费用和累计预算口径。自动回退若替模型选择任务或机器，改变B归属，应放入另行定义的混合实验臂。实体设备协议及现场恢复属于后续独立验证范围。

### Q-06 · 如何公平衡量排程质量、成本、时延和恢复效果，识别模型的增量价值及同类项目的证据边界？

现有结果不能形成A/B/C因果质量排名。A-04中三者一小时均完成1个lot、窗末WIP2176、累计迟交10 lot·小时，完成工序分别336/288/334，但实现版本不同；C仅调用constructive，没有CP，也缺同工具固定参数的C-fixed无模型消融。A-03的B全开发沿革包含1362次尝试、44,666,702个已知输入输出tokens及3条未知用量，不能与A/C单次运行相除。M1候选评测应冻结物理语义、公开信息、初始状态、事件与资源口径，比较A/B/C及C-fixed，并预声明业务改善阈值、开发与保留场景、失败处理。分别报告质量、约束及unknown覆盖、模型与工具成本、失败恢复费用、墙钟时延和仿真时间；模型调用数不是独立实验样本。制造演示的TestModel接收预先由求解器及schema处理的固定报告，仅检查最终审批标志，不证明真实模型纠错或增量质量。MEC作者报告突发收益0.0053，即0.53个百分点，p=0.004；故障差异不显著。27次调用的均值3.0秒、p95 4.3秒来自单个留出实例。

证据：CL-11, CL-12。边界：MEC质量样本与调用时延样本不能混为一个总体，不显著也不表示效果为零或等效。A-10明确当前仿真在模型思考时暂停，因此一小时仿真结果不能证明在线收益。旧计划沿用、状态过期和重排一致性须先定义，不能把思考时间随意追加到仿真末尾。

## 相似项目与可借鉴内容

| 项目 | 可借鉴内容 | 不能由此推断 | 后续验证 |
| --- | --- | --- | --- |
| OptiGuide | 参考[指定源码](https://github.com/microsoft/OptiGuide/blob/main/what-if/optiguide/optiguide.py)中生成、检查、执行、解释的职责交接，记录模型修改内容及求解结果来源。 | 文本检查可关闭；DANGER门槛和协作式超时不构成任意代码安全、强制终止或语义正确性保证。简化文件不能代表全部部署。 | 固定文件与执行环境版本，检验允许修改范围、业务语义反例和超时失败路径；这些条件不意味着采用该技术栈。 |
| OptiMUS | 参考[入口源码](https://github.com/teshnizi/OptiMUS/blob/main/main.py)的阶段状态交接，把目标、约束、数学表达及代码产物分别留证。 | 六份JSON只覆盖初始化至代码生成；执行调试调用存在不证明完成、结果回写、可恢复或业务正确。不同论文与代码版本不能拼成一次实验。 | 核对阶段失败、状态覆盖、调试前后约束变化及最终求解状态；用漏约束而仍能运行的反例检验语义复核。 |
| Deep Agents | 参考[架构说明](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)区分请求前控制、模型工具选择和调用拦截；参考摘要事件与归档路径的分离。 | 顶层权限配置必然进入最终中间件；内置文件规则不自动保护自定义工具或工厂提交。摘要成功不能证明原件可取回。 | 固定实际配置和版本，检查替换中间件后的拒绝与中断路径，并注入归档失败、读取失败和摘要后续调用失败。 |
| Smart Manufacturing Agents | 参考[作者项目](https://github.com/ulisesguras/smart-manufacturing-agents)中工具决定、模型解释、预检阻断和有限篡改自检的边界；三组深读合计仍是一个项目。 | 两产线演示EDD是一般最优算法；solution_id是完整输入认证或幂等键；OptimizationReport检查等同排程检查；TestModel证明LLM收益。 | 将输入版本与结果指纹分别绑定，构造共同错误及预检绕过反例。关键源码在线访问受限，现有结论依据SHA核对一致的指定快照。 |
| LangGraph | 参考[检查点文档](https://docs.langchain.com/oss/python/langgraph/checkpointers)及[中断文档](https://docs.langchain.com/oss/python/langgraph/interrupts)，明确逻辑快照、节点writes和恢复重入范围。 | 所有配置每步同步落盘；检查点自动同步外部状态；恢复撤销副作用；后置或拆节点保证所有版本和并行拓扑只执行一次。 | 固定saver、耐久配置和版本，在父子图、并行中断及崩溃点检查实际执行次数、持久化结果、外部效果和当前授权。 |
| PyJobShop | 参考[官方API](https://pyjobshop.org/stable/api/pyjobshop.html)区分建模表达、求解状态和解对象，建立工厂语义到约束的覆盖映射。 | 直接构造Solution等于可行性验收；丰富约束接口意味着现场全部规则已建模；不验证可行性意味着不会发生结构异常。 | 固定库及文档版本，逐条核对工艺与历史状态映射，并用独立约束反例检查外部导入计划。 |
| Temporal | 参考[Activity文档](https://docs.temporal.io/activities)的尝试、重试与幂等边界，区分单次执行失败和逻辑任务最终结果。 | 所有失败都会重试；完成记录只出现一次意味着设备效果只发生一次；查询一次即可安全重发。 | 核对实际策略、时限及目标协议，在效果发生但确认丢失、旧尝试仍在运行和结果延迟可见时检查去重与对账。 |
| MEC mixed-criticality scheduling | 参考[作者论文v1](https://arxiv.org/html/2608.19557)的同引擎比较、职责消融、扰动分组及控制面时延单独测量。 | 0.53个百分点收益可预测本厂改善；故障不显著证明等效；单实例27次调用证明端到端实时性。论文与仓库不是独立复现。 | 另验工厂任务、约束、等待和目标代价的对应性；代码统计实现及独立复现未验证，源码访问失败不能解释为不存在。 |

## 迁移候选与证伪条件

下表是供 M1 筛选的验证提议，并非已经执行的实验，也不构成本轮开始工程实现的授权。

| 候选机制 | 对应问题 | 依据 | 前提 | 最小验证 | 证伪条件 |
| --- | --- | --- | --- | --- | --- |
| H-01：合并机械调用并保留完整决策归属 | B后期779次调用、80次提交中的机械交互可能占用较多预算，但尚无可兑现节约证据。 | A-02, A-06, CL-03, CL-04 | 模型delta须明确lot、机器、批次、顺序和等待；程序仅编译、检查、存储与执行授权，不补排程选择。 | 先在同一公开状态和固定完整delta下，比较原调用序列与合并流程的编译产物、错误集合和归属账本，包含失败与拒绝路径；一致后才讨论有限模型分支的实际成本比较。 | 程序暗中补决定、漏掉错误反馈、未授权自动提交，或成本下降来自减少覆盖范围。仅减少机械调用不能直接宣称模型tokens已节省。 |
| H-02：版本化公开状态、按需读取与可核验摘要 | 输入占后期tokens的96.77%，缓存输入占输入0.48%；同时存在不能恢复的历史字段。 | A-02, A-05, A-09, CL-05, CL-06 | 压缩不改变公开信息契约；unknown保持unknown，原件可访问性与摘要质量分别检查。 | 列出决定所需字段、版本和失效事件，构造陈旧引用、跨版本查询、增量断档和归档失败，检查能否取回原件或收到明确失败；比较决策前后可达信息集合。 | 摘要被当完整事实库、未知历史被默认填充、过期版本仍可提交，或通过私有快照泄漏降低输入成本。归档失败后静默声称历史完整也否定该迁移。 |
| H-03：来源复现与独立语义检查分层 | 已有合法性通过可能掩盖CQT、历史绑定及同一实现的共同错误。 | A-05, CL-07, CL-08, CL-11 | 预声明覆盖表；分别判断来源一致、物理合法、语义完整和历史无法判定，不以总通过标志合并。 | 构造求解输出与报告共同漏约束的案例，以及伪造但可重放引用、直接构造不可行Solution和缺历史绑定案例；独立检查路径须说明与求解器共享哪些输入和代码。 | 共同错误被两条路径接受，未建模或无法判定被计作通过，或对象实例化、结果指纹一致被当作完整业务验收。 |
| H-04：恢复时核对效果身份与累计预算 | A24和C8失败后，格式及恢复检查尚未证明继续执行成功或不存在重复派工。 | A-08, CL-09, CL-10 | 先限定基准提交目标；工作流进度与目标效果分别记录，未知结果不自动等于未执行，实体协议另验。 | 在提交前、目标已执行但确认丢失、账本持久化前后设置故障点；恢复后继续执行，核对操作身份、版本、授权、在途尝试、回执、总预算及失败费用。 | 恢复格式有效却不能续跑、重复派工、查询结果尚不可见便重发，或重启重置预算和删除失败费用。静态恢复证书不能代替这些运行结果。 |
| H-05：同条件消融识别模型增量价值 | 现有A/B/C版本与成本口径不同，C缺无模型消融，难以区分工具、模型和开发投入贡献。 | A-03, A-04, A-10, CL-11, CL-12 | 冻结规则、信息、事件与资源口径；保留B归属，混合回退单独成臂；预声明业务阈值及失败统计，结论限于所测场景。 | 讨论同版A/B/C和C-fixed对照，分开开发与保留场景，配对比较质量、完整运行成本、墙钟时延及故障恢复累计损失；原始WIP、完整恢复快照和稳态分别证明。 | 以开发沿革对比单次运行、以调用数作样本、将工具贡献归于模型或只报成功样本均使增量结论失效。受控且精度足够的结果未达预声明阈值，只能否定该条件下的收益主张。 |

## 关键论断与对抗核验

公开源码快照字节核验：[integrity-audit.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/public-source-snapshots/integrity-audit.json>)。完整机器可读登记：[claim-register.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/claim-register.json>)。每项可跳转三个原始会话；其中引用的访问等级保留原样，公开源码快照读取与在线成功打开分别留痕。

### CL-01 · OptiGuide

受检原论断：在指定的简化实现中，LLM 生成的代码经可选的 LLM 文本检查后，会被插入原 Python 源码并由 exec 执行；拦截依据是检查回复是否含 DANGER。实现包含60秒超时包装，但源码没有展示独立执行隔离。此论断描述该文件的机制，不代表论文中所有部署版本都采用相同代码路径。

问题：Q-01；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：源码静态阅读不能证明运行时隔离属性；论文称检查为质量控制步骤，未在这些材料中给出形式化安全保证。论文还报告过代码可正常运行但逻辑错误的情况。

采纳时附带的限定：仅描述指定OptiGuide文件：文本安全检查可关闭；Eventlet超时是协作式包装，不能据此保证任意代码被强制终止或完整部署没有其他隔离层。

citations（访问日期 2026-10-12）：

- [原源](https://raw.githubusercontent.com/microsoft/OptiGuide/refs/heads/main/what-if/optiguide/optiguide.py) — lines 57–67、69–149、156–186、198–228、286–304；访问层级 full。

- [原源](https://arxiv.org/html/2307.03875v2) — §3.1–3.2，lines 218–237；文中说明 LLM 生成代码、检查后调用求解器；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。限定命题受直接证据支持。[作者源码](https://github.com/microsoft/OptiGuide/blob/main/what-if/optiguide/optiguide.py)明确标为简化实现。 反向/限定检索：site:github.com/microsoft/OptiGuide "optiguide.py" "sandbox"；site:github.com/microsoft/OptiGuide "DANGER" "use_safeguard" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0001/result.json>)。

  收窄建议：保留原有文件级限定；可补充“检查默认开启，可关闭，DANGER匹配区分大小写；60秒为Eventlet超时包装，不承诺任意代码都能强制终止”。引用宜同时标注快照blob SHA和函数名。

- v2：supported / high。限定命题获得直接支持。指定 raw URL 本次抓取返回 Cache miss；随后成功打开 GitHub 源码页和作者论文。 反向/限定检索：OptiGuide github safety safeguard DANGER exec timeout issue code security；OptiGuide "code" "logical" "errors" 2307.03875 [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0002/result.json>)。

  收窄建议：原命题无需进一步收窄；可补充“60秒包装采用Eventlet协作式超时，不保证终止纯CPU死循环”，继续限定于指定文件，不外推至所有部署或运行时隔离属性。

  未命中说明：未检索到直接推翻该限定源码机制的公开issue或完整系统测试反例；这不等于不存在。指定raw地址抓取失败，源码证据来自成功访问的GitHub页面及SHA核对一致的指定本地快照。

- v3：supported / high。限定命题获直接支持。指定refs/heads/main原始链接首次返回缓存未命中；随后成功打开同文件的/main原始链接及GitHub页面。 反向/限定检索：site:github.com/microsoft/OptiGuide optiguide.py sandbox subprocess exec timeout DANGER；site:arxiv.org/html/2307.03875v2 "Undetected mistakes" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0003/result.json>)。

  收窄建议：保留原有文件级限定，并注明快照blob SHA；补充DANGER匹配区分大小写、60秒为协作式超时包装。生产迁移需另验执行隔离、权威数据版本、外部副作用幂等及业务语义验收。



explicit_not_found: true。保留各验证记录的not_found_note及失败调用；未找到反例不证明反例不存在。

### CL-02 · OptiMUS

受检原论断：所读 main.py 快照包含从状态初始化、目标与约束建模、代码生成到执行/调试的串行编排，并以多个 JSON 状态文件保存阶段结果。

问题：Q-01；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这证明入口代码中存在这些调用和状态交接，不证明被调用函数的内部行为、模型正确性、求解成功率或实际运行结果。

采纳时附带的限定：六份JSON覆盖初始化至代码生成阶段；入口随后调用执行/调试，不证明调试结果已回写、全部阶段实际完成或业务语义正确。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/teshnizi/OptiMUS/blob/main/main.py) — L24-L135；本地公开快照 SHA 8adcf7e79df0579aa21a3c3839e7055f97ac9372；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。原有限定命题获得直接源码支持。已实际打开作者仓库的main.py及其Raw链接，并读取指定本地公开快照；快照长度为4443字符，按Git blob规则重算SHA，结果与给定的8adcf7e79df0579aa21a3c3839e7055f97ac9372完全一致。 反向/限定检索：site:github.com/teshnizi/OptiMUS "main.py" "debug" "state"；"teshnizi/OptiMUS" "state_6_code.json" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0004/result.json>)。

  收窄建议：原命题无需实质收窄；可补充六个JSON检查点截止代码阶段，执行/调试仅证实入口调用，并持续绑定指定快照SHA。

- v2：supported / high。原命题限定于所读入口快照，直接证据支持。已实际在线打开作者仓库的 main.py，并读取指定本地公开快照；快照为4443字节，按Git对象格式计算的blob SHA为8adcf7e79df0579aa21a3c3839e7055f97ac9372，与任务给定值一致。 反向/限定检索：repo:teshnizi/OptiMUS main.py bug debug state json；OptiMUS tes hnizi main.py limitations execution debugging issues [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0005/result.json>)。

  收窄建议：原命题已有必要限定，可保留；进一步注明六个JSON保存覆盖初始化至代码阶段，执行调试在其后调用，实际完成和正确性须另验。

  未命中说明：限定反向检索及已查看的开放issue列表中，未找到直接推翻该入口调用顺序与六个阶段JSON交接的反例；这不代表反例或运行缺陷不存在。

- v3：supported / high。限定源码命题得到直接支持。实际在线打开 main.py，并读取指定公开快照及 manifest；按 Git blob 算法重新计算快照得到 8adcf7e79df0579aa21a3c3839e7055f97ac9372，与提供的 SHA 一致。 反向/限定检索：site:github.com/teshnizi/OptiMUS main.py "debug" "state"；"teshnizi/OptiMUS" "idempotent" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0006/result.json>)。

  收窄建议：保留原限定命题，并明确：六份JSON记录的是初始化至代码生成阶段的状态；入口随后调用执行/调试函数，未证明所有阶段实际完成、调试结果回写、业务语义正确或生产运行幂等。



explicit_not_found: true。保留各验证记录的not_found_note及失败调用；未找到反例不证明反例不存在。

### CL-03 · Deep Agents

受检原论断：可证伪论断一：Deep Agents 的外层控制包括请求前调整工具/提示，以及对内置文件工具实施权限规则；但普通 `tools=` callable 是模型选择调用后才执行。架构说明还指出，文件权限可以拒绝或中断调用，工具可见性本身不等于权限许可。

问题：Q-02；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这是机制说明，不证明每个应用都启用了这些规则，也不证明给定运行实际触发了拒绝或人工中断。架构文档提示精确默认栈应以 create_deep_agent() 配置为准。

采纳时附带的限定：适用于标准模型—工具循环及所读内置文件工具机制；权限与HITL取决于实际middleware、backend、interrupt_on及依赖版本，不自动覆盖自定义工具、shell、工厂提交或幂等性。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md) — Execution L228-L235；Tool surface and filesystem access L249-L255；访问层级 full。

- [原源](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py) — create_deep_agent：middleware 栈组装与条件项说明；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。原命题在其已声明的机制与配置限定下获得支持。2026-10-12实际在线打开[架构原文](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)，执行段明确区分请求前中间件与模型选择后调用的普通工具；文件访问段明确说明可见工具仍可被拒绝或中断。 反向/限定检索：site:github.com/langchain-ai/deepagents "filesystem" "permissions" "tools"；site:docs.langchain.com deepagents filesystem middleware permissions tools callable wrap_model_call [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0007/result.json>)。

  收窄建议：保留原结论，补明：普通callable的执行顺序指标准模型—工具循环；文件拒绝规则须实际传入最终使用的中间件，中断须具备兼容依赖与检查点配置。明确审计日期、部署版本及自定义中间件替换情况，避免写成默认启用或覆盖所有工具的权限保证。

- v2：supported / high。限定命题获得直接支持。本次成功在线打开[架构文档](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)，其Execution节明确区分两类机制：中间件可以在模型请求前调整工具和提示、围绕工具执行施加控制；普通tools= callable则在模型选择调用后执行。 反向/限定检索：site:github.com/langchain-ai/deepagents filesystem permissions bypass tools callable middleware；site:github.com/langchain-ai/deepagents "FileSystemPermissionMiddleware" tests deny interrupt [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0008/result.json>)。

  收窄建议：保留原限定，并补充：权限效果取决于最终组装的中间件实例及其实际规则；替换文件中间件时须核对规则是否保留，工具可见性、顶层配置和实际授权结果应分别验证。

- v3：supported / high。原限定命题获得直接支持。实际在线打开[架构文档](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)，Execution明确区分请求前调整工具列表、提示的middleware，与模型选择后才进入调用路径的tools= callable；文件访问章节明确指出，可见工具仍可能被拒绝或中断。 反向/限定检索：site:github.com/langchain-ai/deepagents "FilesystemPermissionMiddleware" "tools"；site:github.com/langchain-ai/deepagents "tool visibility" permissions [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0009/result.json>)。

  收窄建议：保留原限定命题，复用时明确适用于常规agent调用路径及内置文件工具；权限与HITL效果取决于实际middleware、backend、interrupt_on和版本配置，不外推到自定义工具、shell、工厂提交授权或幂等保障。



explicit_not_found: false。

### CL-04 · Smart Manufacturing Agents: scheduling

受检原论断：在这份实现中，排程决策的核心边界是：工具以确定性 EDD 规则安排演示订单，并在合格产线中挑预计完成时间最早者；LLM 侧按 README 所述解释结果。代码中的 solve_schedule 将固定演示数据直接交给 _solve_edd，非 edd 策略不会执行排程。 同一快照中的 solution_id 对 strategy、assignments 与 unscheduled 作指纹，不直接涵盖完整输入状态或求解器版本。

问题：Q-02；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这是对内置两产线演示逻辑的描述，不证明该贪心规则对一般排程问题最优，也不证明已连接实时 MES/ERP 数据。 输出指纹不等于输入版本认证；不是最优性或生产收益证据。

采纳时附带的限定：先安排固定产线的在制订单，再对开放订单按EDD选择合格产线中预计完成最早者。solution_id仅是部分输出的截断指纹，不是完整输入版本认证、执行幂等键或最优性证明。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/ulisesguras/smart-manufacturing-agents/blob/main/scheduling_mcp_server.py) — 指定本地公开源码快照 SHA 46eb853de1c46748ab211cd9034cc5e33f642d74，L40–69、L104–138、L181–204；在线代码页未能打开；访问层级 partial。

- [原源](https://github.com/ulisesguras/smart-manufacturing-agents) — README 在线正文，约 L238–241；访问层级 full。

- [原源](https://github.com/ulisesguras/smart-manufacturing-agents/blob/main/scheduling_mcp_server.py) — 指定本地公开源码快照 SHA 46eb853de1c46748ab211cd9034cc5e33f642d74，L141–160；在线代码页未能打开；访问层级 partial。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。限定于指定源码快照，原论断获直接支持。已读取两份指定快照及其 manifest 条目，按 Git blob 算法重算 SHA，源码和 README 均与给定值一致；这些是文件内容标识，不是整库提交版本。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents scheduling "strategy" "_solve_edd"；"ulisesguras" "smart-manufacturing-agents" scheduling solver EDD [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0010/result.json>)。

  收窄建议：将选线表述明确为“先安排固定产线的在制订单，再对开放订单按 EDD 顺序选择合格产线中预计完工最早者”；将 README 职责引用改为正文排程代理段落，并持续限定到所给文件 blob 快照。

- v2：supported / high。限定命题得到直接支持。只读取了指定的两份公开源码/README快照，重新计算Git blob SHA，均与给定值一致；这核对的是文件内容标识，不能当作提交版本认证。 反向/限定检索："ulisesguras/smart-manufacturing-agents" scheduling issues EDD strategy solver；site:github.com/ulisesguras/smart-manufacturing-agents "scheduling" "bug" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0011/result.json>)。

  收窄建议：保留快照限定，并明确最早完成产线选择仅针对开放订单；在制订单先固定到指定产线。将solution_id称为部分输出载荷的截断哈希，继续保留非最优性、非完整输入认证及非生产收益证据的限制。

- v3：supported / high。原命题作为指定演示快照的限定描述，受到直接证据支持。已实际打开作者 README，排程条目明确区分调用确定性 EDD 工具与解释迟交、未排订单及利用率。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents "solve_schedule" "strategy"；"smart-manufacturing-agents" scheduling optimizer MES ERP [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0012/result.json>)。

  收窄建议：保留指定快照和固定演示数据范围；补充“最早完成产线选择针对开放订单，在制订单固定到指定产线”。明确 solution_id 是部分输出载荷的截断指纹，不是输入版本认证、最优性证明或执行幂等键。



explicit_not_found: false。

### CL-05 · LangGraph persistence

受检原论断：LangGraph checkpointer 的完整图状态快照按 super-step 边界保存，并以 thread_id（及 checkpoint namespace）定位；同一 super-step 中节点级 writes 可单独持久化用于失败恢复，但不能据此声称存在节点间完整状态快照。它记录的是图状态通道和节点写入，不自动包含外部数据库或工厂权威记录。

问题：Q-03；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：通道值由应用定义；应用可自行复制外部数据或另写 Store，因此不能据此断言框架禁止持久化外部数据，也未验证具体工厂数据库、事务或同步方式。

采纳时附带的限定：super-step描述逻辑快照粒度；实际耐久性取决于saver与async/sync/exit等durability配置，完整状态可通过增量重建。定位特定快照还需checkpoint_id；外部权威状态的同步和原子性另验。

citations（访问日期 2026-10-12）：

- [原源](https://docs.langchain.com/oss/python/langgraph/checkpointers) — Threads、Super-steps、Checkpoints table 与 Writes table；访问层级 full。

- [原源](https://docs.langchain.com/oss/python/langgraph/persistence) — Checkpointer 与 Store 的职责表；外部应用数据须另行存储（关于外部权威数据库的适用性为据此作出的推断）；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。支持原文对逻辑快照、节点写入和外部记录的限定区分。[官方Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)明确：完整StateSnapshot形成于super-step边界；同一步的task writes与checkpoint关联，用于恢复，不是节点间完整快照。 反向/限定检索：site.docs.langchain.com/oss/python/langgraph checkpoint "super-step" "pending" "sync"；site:github.com/langchain-ai/langgraph "_put_checkpoint" "durability" "exit" "_loop.py" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0013/result.json>)。

  收窄建议：补充配置边界：按super-step保存描述逻辑快照粒度；默认async异步持久化，sync等待快照保存，exit仅退出时保存。DeltaChannel可能通过增量重建完整状态；精确历史定位还需checkpoint_id。外部权威记录是否被复制及其一致性须按应用实现另验。

- v2：supported / high。截至2026-10-12，原限定命题得到直接支持。实际打开的官方Checkpointers文档明确区分：完整StateSnapshot对应super-step边界，同一步内各任务的writes单独保存，用于恢复成功任务输出，而非各节点完成时的完整状态快照。 反向/限定检索：site.github.com/langchain-ai/langgraph checkpoint "super-step" "pending" failure；site.docs.langchain.com langgraph checkpoint external database side effects limitations [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0014/result.json>)。

  收窄建议：可补充：特定快照由thread_id、checkpoint_ns和checkpoint_id定位；同一super-step内节点writes不构成完整快照。中间状态的耐久性取决于Saver后端与durability模式；完整逻辑状态可通过增量重建，不必每步全量存储。

- v3：supported / high。截至2026-10-12，已实际在线打开两项指定官方文档及作者源码。官方说明：完整 StateSnapshot 的执行边界是 super-step；同一步内成功节点的输出另存为 pending writes，供恢复时复用，文档明确否认这些任务写入本身是完整快照。 反向/限定检索：site.docs.langchain.com/oss/python/langgraph persistence "pending writes" "super-step"；site:github.com/langchain-ai/langgraph checkpoint "external" "transaction" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0015/result.json>)。

  收窄建议：建议补充：super-step 是逻辑快照边界，实际落盘取决于 durability 模式及 saver；完整状态可由增量重建，未必逐条全量存储。定位具体历史快照需 checkpoint_id。外部权威记录的同步、原子提交与业务幂等须由应用另行实现并验证。



explicit_not_found: false。

### CL-06 · Deep Agents summarization

受检原论断：在提供的 Deep Agents summarization.py 公开快照（Git blob 7fe9e09f6704bca9a2c816a41241107cb55fec12）的自动摘要归档失败分支，归档路径可以为 None，但摘要生成/事件建立仍可继续。因此，摘要生成成功本身不能证明归档成功或历史可完整取回。

问题：Q-03；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：该论断针对自动摘要归档失败分支。快照还显示，内联媒体上传或解码失败时，归档中会用失败占位符标出媒体，原始媒体不可恢复。 不声称底层消息必然已删除，也不声称配置完整外部checkpointer后旧状态仍必然不可恢复；模型可见、归档持久化、底层checkpoint分别核验。

采纳时附带的限定：继续生成摘要以警告不阻断、摘要及后续调用成功等路径条件为前提；摘要事件建立与持久化不同。失败归档不能推导其他checkpoint或业务存储中的历史也已丢失。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py) — 本地公开快照：_offload_to_backend 1227-1302；wrap_model_call 1568-1600；线上页面已 open。快照 SHA 如上，raw/main 行位有差异。；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。原命题的限定表述受源码直接支持。按Git blob规则重算指定快照，SHA确为7fe9e09f6704bca9a2c816a41241107cb55fec12，与manifest-2记录一致；文件为97431字节、2314行。 反向/限定检索：site:github.com/langchain-ai/deepagents "summarization.py" "_offload_to_backend" "None"；site:github.com/langchain-ai/deepagents "summarization" "offload" "raise" "failure" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0016/result.json>)。

  收窄建议：保留固定blob及自动归档写入、编辑失败的范围；可补充警告未升级为异常、摘要调用正常返回的条件。事件建立、状态持久化、归档完整性和checkpoint恢复能力须分别核验。

- v2：supported / high。限定命题得到直接源码支持。只读指定快照与相关 manifest，并按 Git blob 规则重算 SHA，结果与 7fe9e09f6704bca9a2c816a41241107cb55fec12 完全一致；也实际打开了[公开源码](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py)。 反向/限定检索：repo:langchain-ai/deepagents summarization _offload_to_backend failure archive None；site:github.com/langchain-ai/deepagents summarization offload failed checkpointer history [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0017/result.json>)。

  收窄建议：保留原限定，并明确：在警告未升级为异常且摘要生成成功时，归档返回 None 后仍可建立摘要事件；事件写回和持久化还依赖后续调用成功。归档可取回性、模型可见历史与 checkpoint 恢复能力须分别验证。

- v3：supported / high。限定命题得到直接源码支持。只读指定公开快照，计算所得 Git blob SHA 与 7fe9e09f6704bca9a2c816a41241107cb55fec12 完全一致；Git 虽输出临时缓存权限警告，仍返回该哈希。 反向/限定检索：site:github.com/langchain-ai/deepagents summarization "_offload_to_backend" "None"；site:docs.langchain.com deepagents summarization checkpoint conversation history offload failure [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0018/result.json>)。

  收窄建议：保留原命题的自动摘要失败分支限定；可加注：继续执行以警告不阻断、摘要及后续模型调用成功为条件，事件建立与状态持久化仍须区分；不可恢复仅针对失败归档路径或归档中的失败媒体，不覆盖其他 checkpoint 或业务权威存储。



explicit_not_found: false。

### CL-07 · Smart Manufacturing Agents: verifier

受检原论断：在已读 verifier.py 快照中，deterministic_prechecks 为引用不可重放或建议值违反真实规格等情况生成 blocker；最终 approved 等于 LLM 的 approved 与“没有 blocker”的逻辑与，因此 blocker 必定否决，LLM 否决也不能被代码推翻。该结论可由 merge_verdicts 与 run_verification 实现直接证伪或复核。

问题：Q-04；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这组确定性检查针对 OptimizationReport；abstained 时跳过机械预检。重放验证引用可复现性，不等同于证明引用内容足以支持语义主张，后者留给 LLM 判断。

采纳时附带的限定：blocker在此指确定性预检传入merge_verdicts的阻断项；结论限定OptimizationReport及正常返回路径。弃答跳过机械预检，实际检测范围取决于数据后端，不能声称所有虚构引用、异常或工厂约束都已覆盖。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/ulisesguras/smart-manufacturing-agents/blob/main/verifier.py) — 仅读取任务提供的本地公开快照 smart-verifier.py.txt，声明 SHA e49322a94fce58ea1e462fa0a3283fe98f73dbb0，75–93、95–161、208–235 行；在线 open 失败。；访问层级 partial。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。原命题限定于已读源码快照，获得直接支持。读取指定 verifier.py 全文，按 Git blob 算法计算得到 e49322a94fce58ea1e462fa0a3283fe98f73dbb0，与提供值及 manifest-2.json 一致。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents "merge_verdicts" "blocker"；"smart-manufacturing-agents" "deterministic_prechecks" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0019/result.json>)。

  收窄建议：保留原快照限定，并将“没有 blocker”明确为“机械预检列表没有阻断项”；补充检查能力取决于当前后端，弃答跳过机械检查，重放成功不等于语义充分或现场规格已核验。

- v2：supported / high。原有快照限定命题得到直接支持。已读取指定 verifier.py 快照，按 Git blob 格式计算的 SHA 为 e49322a94fce58ea1e462fa0a3283fe98f73dbb0，与 manifest 和任务声明一致。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents verifier merge_verdicts blocker approved bug issue；"ulisesguras/smart-manufacturing-agents" "verifier" "fabricated" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0020/result.json>)。

  收窄建议：保留原有快照与 OptimizationReport 限定，并明确“blocker”指传入 merge_verdicts 的确定性预检 blocker；结论适用于流程正常返回时，不外推为所有虚构引用均能被检测、所有异常均生成 blocker，或已经证明生产安全。

- v3：supported / high。限定于提供的 verifier.py 快照及函数正常返回路径，原论断受直接实现支持。按 Git 对象规则重算三份指定快照的 blob SHA，均与任务提供值及 manifest 一致；这是本地内容一致性校验，不能证明远端当前 main 相同。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents "merge_verdicts" "blocker"；"smart-manufacturing-agents" verifier abstained scheduling blocker override [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0021/result.json>)。

  收窄建议：保留快照限定，并将“没有blocker”明确为“precheck_issues中没有blocker”，将“最终approved”限定于run_verification正常返回时；注明abstained跳过机械预检，后端引用可重放与规格检查不构成工厂权威状态、语义充分性或生产执行幂等的证明。



explicit_not_found: false。

### CL-08 · PyJobShop

受检原论断：PyJobShop 文档明确说明，直接构造 Solution(data, tasks) 不检查解是否可行；当前读取到的 Solution.__init__ 只保存输入并按需派生 job 数据，没有可行性检查调用。

问题：Q-04；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：源码链接指向可变的 main 分支，未固定到 commit SHA；结论针对本次访问的文档与源码内容。

采纳时附带的限定：限定本次访问的文档与源码；tasks非空时构造期间立即计算job数据，不是惰性计算。不验证排程可行性不表示不会发生类型/索引异常；使用前须固定库与文档版本，另验业务约束和外部状态。

citations（访问日期 2026-10-12）：

- [原源](https://pyjobshop.org/stable/api/pyjobshop.html) — class Solution，行 1356–1374；访问层级 full。

- [原源](https://github.com/PyJobShop/PyJobShop/blob/main/pyjobshop/Solution.py) — Solution.__init__；main 分支源码；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。已实际打开官方 stable API 文档及 GitHub main 分支的 Solution.py。文档网页抽取行1356–1374对应原引用，其中 Note 明确写道：“This class does not validate whether the solution is feasible.” 随后说明，直接实例化时假定任务数据代表可行解；未提供任务时表示空解。 反向/限定检索：site:pyjobshop.org Solution "feasibility"；site:github.com/PyJobShop/PyJobShop "Solution" "check" feasibility [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0022/result.json>)。

  收窄建议：保留“本次读取的文档与源码”限定；将“按需派生 job 数据”明确为“tasks 非空时在构造期间立即派生 job 数据”。后续引用宜固定 commit SHA，并记录对应文档版本。

- v2：supported / high。限定论断获得直接支持。本次实际打开的[官方 stable API 文档](https://pyjobshop.org/stable/api/pyjobshop.html#pyjobshop.Solution)在 Solution 条目第1374行明确声明：“This class does not validate whether the solution is feasible.”其后说明，直接实例化时假定任务数据代表可行解，或在没有任务时表示空解。 反向/限定检索：PyJobShop "Solution" "feasible" constructor check validation；site:github.com/PyJobShop/PyJobShop "Solution" "infeasible" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0023/result.json>)。

  收窄建议：保留原限定结论，将“按需派生 job 数据”明确为“tasks 非空时在构造阶段立即计算 job 数据”；固定源码 commit SHA 和文档版本，并注明不校验排程可行性不代表不会出现索引或类型异常。

  未命中说明：本次反向检索未找到直接证明 Solution.__init__ 校验排程可行性的相反源码或测试。测试文件页面抓取失败、PR差异页返回 Cache miss；不能据此认定相关测试或反例不存在。

- v3：supported / high。本次核查支持原命题的限定范围：直接构造 Solution 不执行排程可行性验证。实际打开的[官方文档](https://pyjobshop.org/stable/api/pyjobshop.html)在 Solution 注释中明确说明，该类假定传入任务数据代表可行解；无任务时允许创建空解。 反向/限定检索：site:pyjobshop.org Solution feasibility feasible check Solution(data tasks)；site:github.com/PyJobShop/PyJobShop "Solution" "check" "feasible" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0024/result.json>)。

  收窄建议：保留“不验证排程可行性”的结论；将“按需派生”明确为“tasks非空时在初始化阶段立即派生job数据”，并限定为本次读取的文档与源码内容。生产使用前应固定版本或commit并另行验证排程与业务状态。



explicit_not_found: true。保留各验证记录的not_found_note及失败调用；未找到反例不证明反例不存在。

### CL-09 · Temporal

受检原论断：Temporal 的 Activity 失败重试会安排新的 Activity Task Execution，可能再次运行 Activity 代码。官方建议 Activity 幂等，以避免重复副作用。因此，若一次设备命令已被设备执行、但 Activity 未能确认完成，重试可能再次发命令；Temporal 的重试/持久化本身不能证明设备命令 exactly-once。该设备侧后果是基于重试机制与幂等建议的推论，需设备协议或实现另行去重、查询状态或设计幂等命令。

问题：Q-05；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：文档描述 Temporal Activity 调度和重试，不规定具体设备的命令接收、执行、确认或去重语义；不应把任务尝试可能重跑概括成所有情形下的设备命令 at-least-once 保证。

采纳时附带的限定：仅在重试策略与超时条件仍允许重试，且重跑再次走到发送步骤时，设备命令才可能重发。设备后果是工程推论；去重与查询必须考虑旧尝试仍执行、结果尚不可见的竞态，一次查询不能证明exactly-once。

citations（访问日期 2026-10-12）：

- [原源](https://docs.temporal.io/activities) — L74-L89；访问层级 full。

- [原源](https://docs.temporal.io/encyclopedia/detecting-activity-failures) — L107-L111、L168-L172；访问层级 full。

- [原源](https://docs.temporal.io/encyclopedia/retry-policies) — L121-L126、L140-L181；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。限定命题受支持。三个指定官方页面均成功在线打开；Activities 页确实建议幂等以避免重复副作用，并说明失败后的尝试通常从初始状态开始，使用心跳检查点的代码可恢复进度。 反向/限定检索：site.docs.temporal.io activity retry "exactly once" idempotent；site.docs.temporal.io activity retry "maximum attempts" "non-retryable" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0025/result.json>)。

  收窄建议：原命题可保留；可补明“在策略及超时等条件允许重试、且 Activity 重跑后仍执行发送步骤时，设备命令可能重复发送”。去重、查询状态或幂等命令的有效性须结合设备协议验证。

- v2：supported / high。限定命题获得直接支持。在线打开的[Activities](https://docs.temporal.io/activities)明确建议 Activity 幂等，以免重试产生重复副作用，并说明尝试通常从初始状态重新开始，除非代码利用心跳详情恢复进度。 反向/限定检索：site.docs.temporal.io Activity retry exactly once non idempotent MaximumAttempts 1；site.community.temporal.io activity executed completion lost retry duplicate exactly once [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0026/result.json>)。

  收窄建议：原命题的条件与限制基本充分。可将首句明确为“对于重试策略允许且未触及终止条件的普通 Activity，失败重试会安排新的 Activity Task Execution”，并保留设备后果属于推论、须另验协议及实现的说明。

- v3：supported / high。原论断作为条件命题得到支持。本次实际在线打开三篇原引官方文档。 反向/限定检索：site.docs.temporal.io Activity "exactly once" "idempotent"；site.docs.temporal.io Activity retry timeout cancellation side effects maximum attempts non retryable [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0027/result.json>)。

  收窄建议：原命题已合理限定。可补充：只有重试策略仍允许再次尝试，且代码再次执行到发送步骤时，才可能重发；查询状态必须处理旧尝试仍在执行或结果尚不可见的竞态，不能单凭一次查询宣称 exactly-once。



explicit_not_found: false。

### CL-10 · LangGraph interrupts

受检原论断：在 Graph API 中，恢复动态 interrupt 会从被打断节点开头重跑；该节点内 interrupt 之前的代码也会再次执行。因此前置副作用可能重复，官方建议使其幂等、放在 interrupt 之后，或拆到其他节点。该论断限定于中断所在节点，不能据此断言每次正常恢复都会重跑此前已完成节点。

问题：Q-05；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这是官方文档对 Graph API interrupt 恢复行为的说明；页面未给出与之绑定的 LangGraph 包版本，也未在本任务中通过运行程序独立验证。

采纳时附带的限定：限定Graph API动态中断路径；函数式调用子图时父图调用节点也可能重入。节点重入不表示已完成并持久化的task函数体必然重算。幂等、后置、拆节点不是任意版本、嵌套/并行、崩溃或历史重放条件下的exactly-once保证；执行次数、外部效果和当前业务授权分别核验。

citations（访问日期 2026-10-12）：

- [原源](https://docs.langchain.com/oss/python/langgraph/interrupts) — L86-L90、L651-L653、L818-L823；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。原命题作为限定的恢复语义受直接支持。实际打开官方页后，L87–L89、L653明确说明：使用相同thread_id和Command(resume=...)恢复时，被打断节点从头执行，节点内interrupt之前的代码再次执行；L818–L823逐项给出幂等操作、将副作用放在interrupt之后、拆分到其他节点三项建议，与原引用一致。 反向/限定检索：site:docs.langchain.com/oss/python/langgraph interrupts resume node beginning completed nodes side effects idempotent；site:docs.langchain.com/oss/python/langgraph "interrupt" "completed" "nodes" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0028/result.json>)。

  收窄建议：保留原判定，补充说明：节点内函数式调用子图时，父图调用节点也可能从头执行；该命题既不声称所有已完成节点都会重跑，也不保证它们永不重跑。三项副作用建议不构成任意版本、嵌套并行拓扑及故障条件下的只执行一次保证。

- v2：supported / high。原命题作为有范围限制的官方行为说明，受到直接支持。实际打开的[官方中断文档](https://docs.langchain.com/oss/python/langgraph/interrupts)在L86–90明确说明：使用相同线程的Command(resume=...)恢复时，中断节点从头执行，interrupt之前的代码再次运行；L818–823明确列出幂等、后置副作用、拆分节点三项建议。 反向/限定检索：site:github.com/langchain-ai/langgraph interrupt resume node restart side effects completed nodes issue；site:github.com/langchain-ai/langgraph interrupt resume does not rerun completed nodes test cached task side effects [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0029/result.json>)。

  收窄建议：保留原判定，补充函数调用子图时父节点也可能从头重入。幂等、后置和拆节点是官方建议，不构成任意嵌套、并行或历史重放场景下副作用恰好执行一次的保证；应用验证应固定版本，并检查实际副作用执行次数。

- v3：supported / high。原限定命题获官方文档直接支持。[Interrupts 文档](https://docs.langchain.com/oss/python/langgraph/interrupts) L86-L90、L651-L653 明确说明：恢复动态 interrupt 时，运行时从被中断节点开头重新执行，节点内中断之前的普通代码再次运行；L818-L823 明确建议前置副作用具备幂等性、移到 interrupt 之后，或拆到其他节点。 反向/限定检索：site.docs.langchain.com/oss/python/langgraph interrupts resume completed nodes "re-execute" "subgraph"；site:docs.langchain.com/oss/python/langgraph "resume" "successful" "nodes" "re-run" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0030/result.json>)。

  收窄建议：保留原判定，补充：函数式子图中断也会重跑父图调用节点；节点重新进入不等于已完成 checkpointed task 的函数体必然重算；移后或拆节点不构成重试、崩溃与嵌套并行恢复下外部副作用恰好一次的保证。生产迁移应固定版本，并分别检查执行次数、外部效果及当前业务授权。



explicit_not_found: false。

### CL-11 · Smart Manufacturing Agents: eval

受检原论断：源码定义了一组离线自检，用于验证 EDD 结果的若干排程不变量，并针对手改时间、移到不合格产线、解除在制订单锁线、缺失 solution_id、脏 abstention 和幽灵锁定产线构造反例；TestModel 用固定 solver 派生输出检查 agent 流程中的审批标志。

问题：Q-06；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：这是测试代码覆盖范围的证据，不是测试运行结果。用例针对仓库 demo 排程与所列篡改，不能据此推断其他工艺约束、动态重排场景或真实排程质量均已验证。TestModel 的输出来自 solver_report 固定构造，不检验 LLM 相对求解器的增量排程能力。

采纳时附带的限定：只证明源码定义这些离线用例。TestModel接收预先由solver_report构造并经schema处理的固定报告，测试检查最终审批标志；未单独证明原始假值经agent流程被纠正，也未证明工具覆盖、真实审批执行、LLM增量质量或工厂状态同步。本轮没有运行该测试。

citations（访问日期 2026-10-12）：

- [原源](https://github.com/ulisesguras/smart-manufacturing-agents/blob/main/eval_scheduling.py) — 在线页和 raw 页均 Cache miss；论断依据为任务提供的公开快照 SHA fc75fd43a022e6cc4ccbb3d8d9a245599959e4ae，main() 第 66–250 行。；访问层级 partial。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。支持原命题限定的“源码定义测试覆盖”，不认定测试已运行通过。实际打开 eval_scheduling.py 在线页失败，raw 页返回 Cache miss；因此主要依据指定公开快照。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents eval_scheduling TestModel assertion solver_report；site:github.com/ulisesguras/smart-manufacturing-agents "eval_scheduling.py" "FAILED" [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0031/result.json>)。

  收窄建议：保留原限定，并补充：确定性用例仅比较solution_id；TestModel检查求解器派生且已实例化报告的最终审批标志，不能单独证明流程内纠正假值，也未断言工具调用覆盖。

- v2：supported / high。原论断限定于测试代码的覆盖范围，受到直接支持。已只读核对指定源码快照及 manifest：重新计算的 Git blob SHA 为 fc75fd43a022e6cc4ccbb3d8d9a245599959e4ae，与提供记录一致。 反向/限定检索：repo:ulisesguras/smart-manufacturing-agents eval_scheduling TestModel approval bug issue invariant；"ulisesguras/smart-manufacturing-agents" "eval_scheduling" bug [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0032/result.json>)。

  收窄建议：保留源码定义测试这一限定，并将审批部分写为：TestModel 返回预先由 solver_report 构造并校验的固定报告，测试检查 agent 返回报告的审批标志；未单独验证原始假值经过 agent 流程被纠正。

- v3：supported / high。原论断限定为测试代码的覆盖范围，直接证据支持。eval_scheduling.py 的 GitHub 页与 raw 页本次均返回 Cache miss；读取任务指定的公开源码快照，并按 Git blob 算法重算 SHA，得到 fc75fd43a022e6cc4ccbb3d8d9a245599959e4ae，与任务信息及 manifest 一致。 反向/限定检索：site:github.com/ulisesguras/smart-manufacturing-agents "eval_scheduling.py" "TestModel"；"smart-manufacturing-agents" "eval_scheduling" bug OR failed OR approval [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0033/result.json>)。

  收窄建议：保留原命题的测试定义范围，并注明 TestModel 接收经过 schema 构造的固定求解器报告；不得扩展为真实模型纠错、真实审批执行、工厂状态同步或生产排程质量已验证。



explicit_not_found: false。

### CL-12 · MEC mixed-criticality scheduling

受检原论断：在该MEC论文作者的模拟实验中，LLM控制面相对静态启发式的收益依赖扰动条件：突发时TC完成率从0.7573到0.7626（+0.0053，作者报告p=0.004），单服务器故障时没有显著优势；单个留出实例记录的27次调用平均3.0秒、p95为4.3秒。这是相邻领域的小幅、条件性收益报告，不能推出工厂排程的普遍收益或实时可用性。

问题：Q-06；来源：auto-research / B；confidence：medium；状态：**confirmed**；投票 supported/refuted/abstained：3/0/0。

原有范围：结果限于论文所设定的模拟突发、单服务器故障与轻量模型；作者称收益幅度小，并指出响应缓存使每个报告决策是单次样本，跨种子及模型规模的输出变异尚未研究。 本轮未运行复现实验；数字是作者报告，控制面调用延迟样本与质量模拟样本不可混为一个总体。

采纳时附带的限定：仅采纳论文v1中作者报告的限定模拟结果；+0.0053是+0.53个百分点，故障场景不显著不表示效果为零或已证明等效。27次延迟调用来自单个留出实例，不能与质量实验的实例数混合，也不证明端到端实时性。代码统计实现、独立复现和工厂迁移效果本轮未验证。

citations（访问日期 2026-10-12）：

- [原源](https://arxiv.org/html/2608.19557) — §VI-C 表IV及§VI-D，行261–285；访问层级 full。



adversarial_check：method = falsification；以下为三次实际核验的结论，反向检索式和完整访问记录见各会话。

- v1：supported / high。已在线打开[作者论文全文](https://arxiv.org/html/2608.19557)，页面标识为2026年8月20日的v1。§VI-C表IV逐项支持原数字：突发条件下，静态启发式的TC完成率为0.7573，CNP-LLM为0.7626，差值0.0053，即0.53个百分点，作者报告p=0.004。 反向/限定检索："2608.19557" scheduling burst failure latency；"2608.19557" ("failure" OR "cache" OR "reproducibility" OR "latency") [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0034/result.json>)。

  收窄建议：原命题已充分限定，无需改写。可补注0.0053等于0.53个百分点，故障条件不显著并非等效性证明，源码实际行为和统计实现尚未独立核验。

- v2：supported / high。支持的是“作者模拟实验中的限定报告”，置信度不代表本轮已复现效果。实际在线打开论文v1，§VI-C表IV直接列出：突发条件下静态启发式TC完成率0.7573，CNP-LLM为0.7626，差值+0.0053，即+0.53个百分点，作者报告p=0.004。 反向/限定检索："2608.19557" limitations failure latency scheduling；"multi-agents-llm-edge-scheduling" (bug OR issue OR failure OR replication) [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0035/result.json>)。

  收窄建议：保留原命题的作者模拟报告限定；明确+0.0053为+0.53个百分点，故障不显著不等于等效，27次调用延迟不构成工厂排程或端到端实时性验证。

  未命中说明：仅指本轮反向检索未定位到独立复现或直接相反的原始实证，不表示这些资料不存在。issues页、run_disruption.py及llm_analysis.py直接访问均失败（Cache miss），不能据此判断无issues或代码无反例。

- v3：supported / high。原命题明确限定为作者模拟实验报告，直接证据支持。在线打开的论文§VI-C表IV列出：突发条件下，静态启发式TC完成率为0.7573，CNP-LLM为0.7626，差值+0.0053、p=0.004，即提高0.53个百分点；故障条件下，CNP-LLM为0.8824、p=0.313，HAS为0.8805、p=0.916，均未显示显著优势。 反向/限定检索："2608.19557" (failure OR latency OR cache OR replication)；"multi-agents-llm-edge-scheduling" (outage OR surge OR latency OR limitations) [原始判断](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/verify/agents/0036/result.json>)。

  收窄建议：无需改变原命题。可补充“+0.0053为绝对提高0.53个百分点；故障未显著不等于等效；4.3秒仅为单实例27次调用的经验p95，不构成实时期限保证”。

  未命中说明：未检索到独立复现或工厂生产验证，不表示它们不存在。源码目录、run_disruption.py及llm_analysis.py在线打开均返回Cache miss；本任务对应源码没有可用的指定本地公开快照，代码与报告的一致性未验证。主要数字已通过在线论文全文核实。



explicit_not_found: true。保留各验证记录的not_found_note及失败调用；未找到反例不证明反例不存在。

## 原源提取与选取边界

每方向保留两组 Fetch 材料，以机制与失效边界为主，不能把来源数量当证据强度。Smart Manufacturing的三组深读属于同一个演示项目，不是三份独立工程实证。离线规则生成等路线目前只做初检，未获同等深度核验。下表保留提取阶段的作者部署自述与未知项；未入CL命题的部分不单独代表三轮核验通过。

| 包 | 方向/项目 | 原源提取 | 部署/测试边界 |
| --- | --- | --- | --- |
| S-01 | Q-01 OptiGuide | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0001/result.json>) | 论文作者称其在 Microsoft Azure 服务器履约供应链的 Intelligent Fulfillment System 场景部署：前端服务、连接 Azure OpenAI 的 agent 服务，以及承载系统和应用组件的多台 VM；原文称优化输入数据约500 MB、求解器每小时运行并使用 GPT-4。作者报告规划人员和工程师反馈积极，并给出初步分布内准确率超过90%。这些是论文中的作者报告；不能由此推出当前仍在部署，或已实证降低排程成本、延误和工程工时。 |
| S-02 | Q-01 OptiMUS | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0002/result.json>) | 论文称系统提供公开 Web 应用，并以 NLP4LP 及七个真实案例问题评估；这些材料表明作者报告了研究原型和案例基准，不足以证明其已在工厂生产排程中部署、持续运行或接入生产系统。所读代码快照也未提供部署运行记录。未检索到不代表此类部署不存在。 |
| S-03 | Q-02 Deep Agents | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0003/result.json>) | 本次读取的架构文档及代码页没有给出真实部署实例、运行日志、业务指标或节约数据。源码证明能力存在，不构成生产效果证据；没有据此外推本厂节约。 |
| S-04 | Q-02 Smart Manufacturing Agents: scheduling | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0004/result.json>) | 在线 README 将项目标注为 pre-revenue、尚无外部部署；并把 SQL/OPC UA 原生连接器及审批门控执行服务器列作路线图。故目前读到的是作者披露的演示/评测状态，不是生产部署或现场效果证据。 |
| S-05 | Q-03 LangGraph persistence | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0005/result.json>) | 官方 checkpointer 文档称 PostgresSaver 用于 LangSmith，并将 Postgres/MongoDB checkpointer 描述为生产用途选项；这是项目官方文档陈述，不是独立部署验证或可靠性指标。未找到并核验本任务中工厂排程系统的真实部署证据。 |
| S-06 | Q-03 Deep Agents summarization | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0006/result.json>) | 未从本源码页或指定快照获得真实部署或生产效果证据。 |
| S-07 | Q-04 Smart Manufacturing Agents: verifier | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0007/result.json>) | 仓库 README 在线页（291–298 行）自述项目为 pre-revenue、无外部部署；approval-gated actuation server 仍列于路线图。因此没有已核实的真实产线部署证据。README 与代码属于同一项目，不视为独立来源。 |
| S-08 | Q-04 PyJobShop | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0008/result.json>) | 指定文档与仓库主页介绍的是库的建模能力和示例用途；本次材料未提供真实工厂上线、运行记录或生产排程验证证据。未查到不代表不存在，本次不据此推断项目没有生产使用。 |
| S-09 | Q-05 Temporal | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0009/result.json>) | 所读资料没有给出特定工厂、设备或生产部署的验证证据；不能据此认定设备命令已实现幂等、去重或 exactly-once。 |
| S-10 | Q-05 LangGraph interrupts | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0010/result.json>) | 官方持久化页面建议生产使用持久 checkpointer，并指出 InMemorySaver/InMemorySaver 类实现仅存 RAM、进程重启会丢 checkpoint。这是部署建议，不是某一真实工厂或硬件部署的证据；没有找到并核验真实生产部署记录。 |
| S-11 | Q-06 Smart Manufacturing Agents: eval | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0011/result.json>) | README 明确自报尚无外部部署；提到的是 demo plant 上的 live-model eval。未见公开的客户工厂数、部署持续时间、订单规模或生产指标。仓库页访问时显示 0 stars、0 forks，只能作为有限的公开互动信息。 |
| S-12 | Q-06 MEC mixed-criticality scheduling | [完整提取](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/fetch/agents/0012/result.json>) | 未见真实车辆边缘或生产部署证据。论文明确把结果限定为模拟器，并将物理车辆测试台列为未来工作。模型调用延迟测量是一次留出实例的实时调用，不构成部署验证。 |

### 未选入12条核心论断的线索

以下搜索发现保留为线索，不升级为本轮三次核验通过的结论。限制来源类型与样本覆盖可能漏掉项目；“未找到同规模成品”不等于“不存在”。

- Q-01：[Large Language Models for Supply Chain Optimization](https://arxiv.org/abs/2307.03875), [OptiGuide what-if/optiguide/optiguide.py](https://github.com/microsoft/OptiGuide/blob/main/what-if/optiguide/optiguide.py), [OptiMUS: Scalable Optimization Modeling with (MI)LP Solvers and Large Language Models](https://arxiv.org/abs/2402.10172), [Policy-Based Deep Reinforcement Learning Hyperheuristics for Job-Shop Scheduling Problems](https://arxiv.org/abs/2601.11189)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0002/result.json>)。这些初读线索不构成新增已核验经验结论。

- Q-02：[Smart Manufacturing AI Agents](https://github.com/ulisesguras/smart-manufacturing-agents), [From Agent Traces to Trust: A Survey of Evidence Tracing and Execution Provenance in LLM Agents](https://arxiv.org/html/2606.04990v5), [PeakBench: Benchmarking Resource-Aware Tool Invocation in LLM Agents](https://arxiv.org/abs/2608.24509), [Deep Agents Architecture](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0003/result.json>)。这些初读线索不构成新增已核验经验结论。

- Q-03：[Checkpointers - Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/checkpointers), [deepagents summarization middleware source](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py), [Less Context, Better Agents: Efficient Context Engineering for Long-Horizon Tool-Using LLM Agents](https://arxiv.org/abs/2606.10209), [MemOps: Benchmarking Lifecycle Memory Operations in Long-Horizon Conversations](https://arxiv.org/abs/2607.12893)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0004/result.json>)。这些初读线索不构成新增已核验经验结论。

- Q-04：[smart-manufacturing-agents/verifier.py](https://github.com/ulisesguras/smart-manufacturing-agents/blob/main/verifier.py), [PyJobShop API 文档](https://pyjobshop.org/stable/api/pyjobshop.html), [Smart Manufacturing AI Agents 项目说明](https://github.com/ulisesguras/smart-manufacturing-agents)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0005/result.json>)。这些初读线索不构成新增已核验经验结论。

- Q-05：[What is a Temporal Activity?](https://docs.temporal.io/activities), [Detecting Activity failures](https://docs.temporal.io/encyclopedia/detecting-activity-failures), [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), [OpenRouter integration](https://docs.temporal.io/develop/python/integrations/openrouter)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0006/result.json>)。这些初读线索不构成新增已核验经验结论。

- Q-06：[When Do LLM Agents Help? Deadline-Aware Mixed-Criticality Task Scheduling at the Autonomous-Vehicle Edge](https://arxiv.org/abs/2608.19557), [LLM4Schedule：代码与实验结果](https://github.com/LLM4SCHEDULE-2026/LLM4SCHEDULE-2026), [LLM-as-Scheduler: Agentic Workflow Dynamic Scheduling](https://aclanthology.org/2026.acl-long.581/), [Smart Manufacturing AI Agents](https://github.com/ulisesguras/smart-manufacturing-agents)。完整未命中说明与访问失败见 [检索记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/scope-search-retry/agents/0007/result.json>)。这些初读线索不构成新增已核验经验结论。



## 三源处置

| source_type | coverage | probe_note / na_reason | corpus_write |
| --- | --- | --- | --- |
| A | covered | 读取本项目5份冻结文件及报告锚点。项目wiki不可用，回退rg原文，未把旧dossier当独立验证。 | none |
| B | covered | 公开检索、源码/论文/官方文档阅读；36次反向检查的查询、打开与失败均留存。 | none |
| C | explicit_na | 本轮无新增人工策展技术资料；用户授权只决定执行范围与数据边界。 | none |

C 源没有写入策展 corpus。原始材料中的指令性文本不作为执行授权。

## 执行配置、成本与审计

拆题、检索、提取使用 gpt-6-luna；对抗核验、综合与独立评审使用 gpt-6.1-sol。xhigh，最多两个研究会话同时运行，单会话上限600秒。总额外会话预算60次，失败与重试计入。

可见用量快照：[usage-and-tool-audit.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/usage-and-tool-audit.json>)；全局调用账本：[launch-ledger.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/launch-ledger.json>)。独立评审完成后另在 [交付与评审闭环](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/summary.md>) 写最终用量，避免将此处的评审前数值冒充最终值。

当前已闭合阶段记录 57 次会话，可见 input 15,213,871、output 302,113 tokens；无usage回报 1 次。缓存输入是输入的子集，reasoning是输出的子集，不重复相加。

该统计不含Owner主会话及直接工具的完整成本，也不是账户总用量或精确费用；未取得货币账单。失败启动、自动审批拦截及用户明确授权后重启的经过见 [owner-decisions.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/owner-decisions.json>)，未删除失败记录。

仓库 API 元数据（访问日的默认分支、最后推送、许可标识）：[repository-metadata.json](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/repository-metadata.json>)。这只是选型线索，未完成依赖树许可与维护风险审计。

## 不确定性与移交

全部链接与访问状态继承给定核验记录，本轮未重新访问。Smart Manufacturing关键源码及MEC实验脚本存在Cache miss或其他访问失败；本地公开快照的blob SHA只标识文件内容，不是整仓提交版本，main、stable及文档与部署版本的对应关系仍须固定。源码、README、论文和测试若来自同一项目，不算独立研究证据；三次模型检查也不是三份独立实证。本批12条选中命题均为confirmed，没有提供refuted状态的选中条目，但旧M0.5的超时、未验证项、独立复现缺口及本厂迁移效果不得静默升级。未检索到不等于不存在，统计显著不等于业务有意义。所有迁移实验均为研究提案，尚未执行，不构成M1要求、架构决定或生产混合方案。

所有未决问题见 [open-questions.md](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/open-questions.md>)。M1若吸收论断需保留CL编号和引用链；本档案不自动启动M1。
