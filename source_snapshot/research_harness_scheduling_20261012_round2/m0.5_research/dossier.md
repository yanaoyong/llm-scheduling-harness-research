---

artifact: dossier

flow_instance: research-harness-scheduling-20261012-round2

run_id: m05-20261012-focused-tiered-02

stage: M0.5

engine_tier: L2

created_at: 2026-10-12T11:26:59.471450+00:00

sources_disposition:

  A: {coverage: covered}

  B: {coverage: covered}

  C: {coverage: explicit_na, na_reason: 本轮无新增人工策展技术资料, corpus_write: none}

---

# M0.5 第二轮：模型职责、全厂语义、工程复用与直接排程证据

本报告为追加研究实例，保留上一轮全部产物。用户批准四个专题，原45次上限经追加授权提高到49次。Luna拆题/检索/提取，Sol核验/综合/独立评审。研究结论不自动触发M1、框架选型或工程实现。

## 结论与证据范围

截至2026-10-12，本轮增量证据支持保留直接排程B、工具/策略选择C、离线规则生成三条路线，尚不足以判定同条件胜负。原核验27次尝试产生23份有效结果、4次超时；四次重试均完成，按各角色最新有效结果，C01、C06仍为refuted，C09补充登记由unverified变为confirmed，其余六条维持confirmed。三次模型检查不是三份独立研究。C01被成功解析后程序裁决的反例推翻；C06被查询数字出处错误推翻，规则生成机制仅作收窄采纳。C09两份重试为medium，支持有条件的静态控制流，必须披露虚拟延迟节点推进、物理就绪检查和历史部署未绑定。SCHEDBench单次整表、SeEvo测试时适应、作者单厂DES结果及本地一小时开发报告均有各自边界；C-fixed、完整失败分母、版本绑定、历史状态缺口和在线时延仍未解决。最终综合会话仅综合指定产物，未新增检索、实验、文件修改或启动M1。

本次交付采用补充重试后的重新综合。此前综合作为过程记录保留；原27次核验和4次超时不覆盖，另附4次重试及前后状态。

[本报告采用的综合结果](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/synthesize-v2/result.json>)；[追加预算授权](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/budget-amendment-49.json>)；[重试与原记录对应表](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-register.json>)

本轮源码阅读与作者实验报告须分别理解。未运行新的工厂排程、未安装或复现实验项目；是否执行了额外隔离检查以原始工具审计为准。同一 Sol 模型的独立核验会话票数仅作登记，不是独立实证。

## 三源处置

### A 项目内部

读取冻结脱敏报告及明确允许的工程源码/测试。wiki未覆盖的具体运行与实现细节回退rg/read原文。测试文件存在不等于本轮测试通过；历史运行报告也不替代本轮复现。

[内部背景与出处](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/internal-context.json>)；[读取白名单](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/internal-allowlist.json>)；[源码版本指纹](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/internal-code-baseline.json>)

### B 外部原源

按专题检索论文、作者代码和官方文档；本轮外部引用的访问/取证日期统一为2026-10-12。实际访问与失败保存在原始会话；同一项目的多种材料不算独立研究。公开快照若使用，须标明取得方式与内容指纹。

[调用与工具取证审计](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/usage-and-tool-audit.json>)

### C 人工策展

coverage=explicit_na；本轮没有新增人工策展技术资料。用户路线偏好与授权作为执行要求记录，不作为经验效果证据。corpus_write=none。

## 四个专题

### Q-01 离线由大模型生成规则、优先级公式或启发式程序的排程研究，模型实际职责、生成搜索成本、持出实例泛化、基线与约束保证是什么？与直接在线派工及策略选择的适用条件有何区别？

EoH的进化对象是启发式描述和程序；FSSP生成函数修改加工矩阵并选择扰动作业，GLS形成最终排列。核验所读后续main中，NEH选择初始插入位置，swap/insert邻域接受改进，宿主截断扰动作业并对异常返回失败适应度。这些都是算法贡献，属于独立的规则生成路线。原C06整体仍被反驳：2,000次查询位于v3 §4.2装箱结果段，并非摘要，也不能作为FSSP生成成本；机制说明是纠正后的收窄采纳。[EoH v3](https://arxiv.org/html/2401.02051v3)。SeEvo两版论文均描述测试一代规则演化。所读main的mode==test先加载规则，随后仍执行反思、交叉、自进化和评价；生成规则给作业算分，环境argmin选作业、按名义时长选机并推进事件。因此它包含测试时适应，不能与冻结规则执行合并。这里的test是条件分支，非Git分支。[SeEvo v2](https://arxiv.org/html/2410.22657v2)。研究判断是：规则可在明确输入域内冻结执行时，离线路线适合检验生成成本能否摊销；新场景继续搜索时，应把适应成本纳入评测。两者都不自动等同本项目运行时C。

**证据范围与限制：**EoH有随机适应度实例与Taillard测试的作者报告，并有经典启发式、学习方法及同框架人工扰动对照；这些仅覆盖置换流水车间和makespan，未建立本厂重入、组批、资格绑定或等待保证。FSSP实际调用、tokens、失败重试和总壁钟未知，种群×代数不能替代账单。SeEvo部分基线来自文献，论文和仓库特征、变异设置存在差异，main未固定提交；测试时适应不自动等于泄漏，也不证明每次派工都调用模型。v2已有整解耗时和相对API费用报告，缺的是冻结规则单次派工成本及完整账本。EoH小数工时例子只是未执行静态推演，输入域适用性未知，不能新增已证实合法性缺陷结论。

关联论断：R2-C05, R2-C06

### Q-02 与半导体全厂/复杂制造排程匹配的公开模拟器、基准和研究，如何处理重入、批处理、资格/历史绑定、时间窗口、换型、故障及初始状态？有什么独立约束检查与可信评测证据，可迁移与不能迁移的边界是什么？

SMT2020/PySCFabSim较接近全厂问题的证据来自基准语义与批准内部报告，而非本轮LLM效果实验。重入/返工、批处理、setup、故障和维护等结构不能替代资格、历史绑定及时间窗的逐项语义确认。继承A-05的semantics-20261009.md：433个初始lot的CQT历史起点未知，1311个初始lot缺绑定历史；冷启动WIP不具备完整在制加工、设备setup和维护剩余状态。该报告第55行包含固定上游CQT TODO/deactivated自述，属于已批准内部报告证据，不是上一轮CL-01至CL-12外部三核验命题。[批准语义报告](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/semantics-20261009.md:55)。光刻研究提供资格、顺序相关setup、reticle/pod资源及随机执行冲突的区域案例。C07支持作者报告：48小时DES、每小时重排、1.5小时时域，匹配平方迟交时CP1/CP2效率收益约1%/2%，静态报告约6.5%/5.5%。它提示静态方案需经过动态资源执行检验。[光刻CP/DES论文](https://link.springer.com/article/10.1007/s10696-026-09666-5)。

**证据范围与限制：**本轮S-03公开标签源码读取和WSC材料均为原源提取级，未接受九条命题同等完整对抗核验。固定SHA直链访问失败，未重新确认RefactoredVersion2025到ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1的映射，也未三票确认外部CQT效果。字段、计数器和复现入口不证明约束生效；AutoSched定制控制不可写成PySCFabSim效果。批准报告将输入完整性与官方数值校准分开，后者未通过。光刻仅为作者单厂区域DES，CP2静态缓冲0、动态1200秒，动态求解预算240秒，非只改变随机性的因果比较；EDD迟交优势保留。30次动态重复不同于旧校准重复数，图像访问失败、实现未取得、独立验证器和跨厂泛化未知。

关联论断：R2-C07, A-05, A-09

### Q-03 当前排程工程和myharness哪些能力已有代码及运行证据、哪些仅有静态实现？沿状态→观察→决定→编译校验→提交→归档恢复识别可复用部分，特别核查决定归属、版本绑定、恢复副作用与预算，避免把研究编排当排程运行时。

沿指定条件路径，V15 host导入V14 Interaction，并由其按包内哈希加载组装器；模型显式提交生产任务身份、机台、批组、顺序、开始条件和hold，组装器验证后发布，compiler机械展开明确处分并拒绝非法输入。成功check仅产生候选，较晚独立apply需精确ID/hash；未见指定链自动择优或补排。C09重试补齐了这一静态命题，不能认证历史部署。公共执行还检查物理就绪；环境选择虚拟延迟组别并推进，模型并未决定每个仿真事件。[限定交互链](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py:434)。批准报告提供既有B一小时开发运行证据：责任913台机，95次提交、1071次派工，涉及841台，构造器/求解器调用为0；主结果不证明经济性、长期质量或实时部署。历史C归类继承报告与constructive源码：模型选择参数/apply，gain_rate构造器安排具体任务，未调用CP。myharness五个授权文件支持通用编排、schema、归档和预算机制，但每次新建runId、目录及阶段集合，backend新起ephemeral exec；该原生路径没有跨进程workflow resume。

**证据范围与限制：**当前已读源码与完整性基线匹配，不等于批准报告对应campaign/frozen逐文件绑定；未打开运行明细或原始工厂数据。观察预测、编译约束、物理提交及归属审计分别有边界，最终合法计划不能替代原始输出合法率。plan_from_action补字段辅助函数在指定链未命中调用，不可推广为整个工程绝无自动转换。B开发沿革已知44,666,702 tokens，另3次历史调用用量未知；后期机械动作份额只是可疑开销，未兑现节省。A/B/C版本不同、主交付指标相同，缺C-fixed。A24/C8历史失败与未验证续跑继续保留。myharness测试仅为定义、README历史smoke仅为作者记录；外层阶段续接、重连和schema字段还原均不证明原生恢复。

关联论断：R2-C08, R2-C09, A-01, A-02, A-03, A-04, A-08, A-10

### Q-04 有哪些大模型直接输出排程、优先序或逐步派工的原始研究与公开代码？逐项追踪模型、解码/修复器、启发式与求解器分别作了什么决定；对照工具驱动/策略选择，评估合法率、质量、规模、成本、延迟、失败、泛化及模型版本证据，这些能否支持本项目B或C路线选择？

本轮区分完整安排、逐步具体动作、分数/优先序经解码三种直接程度。SCHEDBench v2主实验让13个API模型对六类1,132实例各作答一次，随后解析、清理非实质文本并用CP-SAT验证；未报告语义修复。15.2%是各模型以全部1,132实例计算总体可行率后跨13模型平均，家族按实例数加权；GPT-5.5为55.9%，核验记录其2026-04-23版本。14,716份输出包含56份不可解析，分母不能缩为14,660；目标gap仅统计可行输出。JSP机器由题面固定，不能验证FJSP机台分配，更不能外推本厂多轮B。[SCHEDBench v2](https://arxiv.org/html/2608.00991v2)。Dyna固定提交存在有效ActionID直接确定工件/机台的受限逐步B分支，但C01原充分条件被反驳：有效输出平票可由环境评分裁决，缺机台的接受路径可由模拟器补选。C02仅支持70例子集表3的均值/token描述：Direct、CoT、Tool为2.0%/3.752M、1.9%/4.016M、2.0%/12.614M；质量参照最佳已观察排程，非已证最优。工具提供信息/试算不自动成为C。[Dyna论文](https://arxiv.org/html/2605.27566v1)。Cambridge GenAI案例披露词典→ETFN→MATLAB修改模型/GA→GA排程，未建立本地LLM职责，不能凭标题列为B或C。[原论文](https://doi.org/10.1017/S0890060425100152)。

**证据范围与限制：**Dyna候选过滤、随机/PDR截断、当前工序、开始时刻、空闲推进、单动作绕过和失败回退都有程序贡献；有效ID唯一落定且未经程序裁决的描述是收窄，非原C01获确认。固定代码与论文配置、分支发生率、表3基础模型和有效n未知；Tool部分分位数改善限制了普遍无益的说法。SCHEDBench完整解析验证实现未确认，未报告修复不证明未公开分支绝无修复；470/150子实验、整体费用不能混入主实验。GenAI比较对象的版本、提示、纠错轮次和计时边界不足。新增材料没有完成在线LLM仅输出优先序、解码器负责其余字段的独立项目核验；生成程序运行所得分数不能充当这种证据。

关联论断：R2-C01, R2-C02, R2-C03, R2-C04, R2-C09

## B / C 路线证据评估

### 职责分类

B要求模型明确决定lot、机台、批次、顺序与等待；机械编译和拒绝式校验可保留，补选、修复、解码裁决需另计决定者。完整整表要求一次承担大量安排；逐步动作仅证明动作字段；优先序/分数若经解码补机台、批次和等待，归属须拆开。C要求模型选择构造工具或策略参数，算法作具体安排。离线程序生成和优化模型修改均单列。[分类标准](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json)。

### 直接排程的证据

SCHEDBench支持单次整表机制及有限可行率事实；Dyna支持收窄后的具体动作分支，同时以程序破平票反驳原充分条件。本地C09支持较完整生产字段的条件性静态职责，批准报告另提供一小时开发运行证据。三个协议的候选空间、反馈次数、模型版本和验证贡献不同，不能拼成共同合法率或规模曲线。

### 工具与策略选择的证据

Dyna的inspect/simulate主要供模型选动作，不能用Tool名称代表本项目C。历史C报告和constructive源码支持模型选参数/apply、gain_rate形成任务；报告明确未用CP。现有A/B/C主指标相同但版本不同，既未隔离工具贡献，也未检验模型相对同工具固定参数C-fixed的增量。

### 离线规则生成的独立路线

EoH提供生成扰动程序后由搜索形成安排的路线证据；SeEvo还包含测试时规则适应。冻结执行能否降低运行时调用负担是待检验假设，需独立持出与生成成本摊销证据；不能从SeEvo测试结果直接推定零API，也不能把EoH装箱预算移作排程成本。

### 条件性判断

研究阶段保留三条路线。若目标是审查模型对具体生产决定的能力，B已有可审计机制和有限开发证据；若允许算法安排具体任务，C是合理比较候选，但需证明模型超出C-fixed；若要求重复执行规则，离线生成值得继续研究，但须区分冻结与新场景适应。当前证据不足以选择唯一生产路线或锁定技术栈。

### 什么证据会改变判断

会改变判断的是同物理语义、初态、观察、候选处理、目标、模型快照和预算下的持出重复证据：分别报告原始合法率、拒绝/修复/回退、失败纳入质量、tokens、调用与壁钟。C若稳定优于C-fixed且计入模型成本，支持策略选择价值；冻结生成规则若无新增API仍保持质量且合法性独立通过，支持离线路线；B若同条件表现有增量并满足目标响应期限，支持扩大直接职责。这些都是未执行的证伪条件。

### 仍未解决的问题

C-fixed尚缺；全历史原始输出分母、实际部署绑定、CQT/历史资格状态、完整独立检查和恢复效果未知。当前规范评价暂停仿真期间的决策质量，模型活动时间不等于纯推理或现场响应；在线工厂继续运行的目标尚未确定。

## 项目与可借鉴机制

| 项目 | 职责分类 | 证据强度 | 可借鉴 | 不可推定 | 仍需验证 |
| --- | --- | --- | --- | --- | --- |
| EoH | 离线生成GLS扰动程序；算法形成排列。 | C06原命题refuted；规则机制与更正出处仅收窄采纳，未复现。 | 吸收程序与搜索器的职责拆分、同框架人工扰动对照；依据[EoH v3](https://arxiv.org/html/2401.02051v3)及[后续源码](https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py)。 | 装箱2,000查询是FSSP账单；main等于2024实验版本；小数工时静态例子已证明论文合法性缺陷。 | 冻结规则和执行域，核对搜索贡献、失败分母、版本及全部生成成本；越出置换流水车间需重验语义。 |
| SeEvo | 规则生成并含测试时适应；程序和环境落定派工。 | C05三份支持，其中两份medium；论文与main对应未确认。 | 吸收规则评价与改进反馈，并单列测试适应；依据[论文v2](https://arxiv.org/html/2410.22657v2)和[演化源码](https://github.com/huangjin-collab/LHH_DFJSP_SeEvo/blob/main/seevo.py)。 | 应用训练规则即冻结零API；一代即一次请求；规则评分承担机台、批次和等待。 | 区分冻结规则与一代适应，查调用/重试账本、特征和变异差异；全无效、超时及选父失败需计入。 |
| DynaSchedBench论文与实现 | 有条件的受限逐步B；信息工具不自动归C。 | C01三角色最新判断反驳；C02仅确认作者有限描述。 | 吸收具体动作编号与候选信息查询；审计依据[固定提交policy.py](https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/policy.py)。 | 选机开关和输出接受保证模型决定机台；环境破平票即为失败回退；候选上限等于展开后行数。 | 绑定论文配置，分别计程序裁决、补机台、绕过、回退发生率；保持候选和反馈同条件。 |
| SCHEDBench | 单次完整安排；解析与求解器验证，未报告语义修复。 | C03确认作者主实验限定事实；完整评估实现未确认。 | 吸收可解析、可行、目标质量的分层计分；依据[论文v2](https://arxiv.org/html/2608.00991v2)。 | 15.2%是六家族等权；解析成功等于合法；固定机JSP证明本厂完整B。 | 补完整解析、验证、失败计分代码及不可变版本；单次整表与多轮反馈须独立比较。 |
| Cambridge GenAI FJSP案例 | 已披露的是词典解析、模型/程序定制与GA求解；LLM职责未建立。 | C04确认分类纠正，未确认作者公开实现。 | 吸收结构化需求与约束修改的可追踪表达；依据[官方论文](https://doi.org/10.1017/S0890060425100152)。 | 标题证明LLM接入；比较表具有同提示、同纠错和同计时边界。词典缺项与人工补词限制泛化。 | 需实际实现、模型身份和对话证据，才能讨论LLM职责；GA违规染色体替换属于算法贡献。 |
| SMT2020 / PySCFabSim | 全厂基准及算法模拟；没有本轮LLM B/C实证。 | A-05/A-09为批准报告继承；S-03新增为提取级且固定SHA访问受限。 | 吸收完整性、语义覆盖、数值校准的分离；依据[批准语义报告](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/semantics-20261009.md:55)。 | CQT字段即硬约束生效；冷WIP即恢复快照；标签读取重新证明SHA映射。 | 保留历史起点和绑定unknown，核对约束执行与校准；WSC控制策略只作未完整核验线索。 |
| 光刻CP与DES | CP求解器安排，dispatcher和DES检查资源并执行。 | C07确认作者单厂条件性报告；非独立复现。 | 吸收辅助资源冲突、缓冲及静态到动态差异的评测视角；依据[正式论文](https://link.springer.com/article/10.1007/s10696-026-09666-5)。 | 区域收益等于全厂收益；静态/动态只差随机性；CP全面支配EDD或已上线。 | 独立约束检查、初态及参数敏感性、失败周期和净成本仍需证据；图像和实现访问限制保留。 |
| 指定本地B/C工程链 | C09条件链中模型显式决定物理生产计划；历史C由构造器安排。 | B静态归属补充confirmed；运行事实仅继承批准报告，历史版本未逐哈希绑定。 | 吸收显式delta、拒绝式编译、独立apply和提交回放；依据[compiler](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py:118)。 | 编译通过保证全部动态物理约束；模型决定虚拟推进；一小时结果支持B/C排名。 | 部署绑定、原始输出分母、恢复副作用及C-fixed缺口保留。 |
| myharness指定CLI/runtime | 研究工作流编排；五文件不足以建立排程运行时职责。 | C08静态限定confirmed；测试和历史smoke未在本轮执行。 | 吸收调用计数、并发、schema和失败归档；依据[runtime](__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs:191)。 | 落盘即恢复；重连/schema还原即workflow resume；成功usage覆盖失败消耗。 | 仅所读原生路径缺跨进程恢复，其他模块未知；取消时限和失败用量完整性未动态验证。 |

## 本地工程复用清单

| 能力 | 已有证据 | 状态 | 限制 | 出处 |
| --- | --- | --- | --- | --- |
| 状态与历史语义边界 | 批准报告记录冷WIP、CQT未实现及历史起点/绑定缺失，可复用其unknown表达与完整性/校准区分。 | 已有批准报告证据；语义缺口仍需验证。 | 433/1311条历史缺口不能补零；审计通过不覆盖明确未建模规则，本轮未读工厂数据。 | [semantics-20261009.md](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/semantics-20261009.md:55) |
| 公开观察与预测 | S-06静态提取记录机器、工序、资格/批次、setup等公开观察，残余与后继按均值估计，并限制未来随机信息。 | 静态代码存在；预测有效性待验证。 | 默认lookahead和均值估计不是实际未来；历史未知及未扩展事件不能由观察摘要消除。 | [observation.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/observation.py:115) |
| 只读查询与交互证据 | DeltaSession有内容定义的逻辑session和证据导出；指定V14包装把session_query限制为只读。 | 静态代码存在。 | 外部持久化及模型归属另有责任；底层存在check/apply不等于V14实际通过该路径提交。 | [delta_session.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/delta_session.py:92)；[interaction.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py:434) |
| 版本身份与锚点 | C09核验记录当前已读文件匹配基线，包内依赖按字节哈希加载；草稿、候选和提交绑定观察/计划/状态/来源锚点。 | 条件性静态支持；历史部署待绑定。 | 基线匹配不证明实际campaign/frozen加载同一字节，也不认证配置模型标识的实际调用版本。 | [V15 host.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py:16)；[包内依赖加载](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py:16) |
| 显式字段组装与原子拒绝 | C09支持完整任务/hold字段、全部路径含空数组明确声明；chunk在副本验证后发布，seal拒绝缺项。 | 重试后静态confirmed；非运行保障。 | 对象容器创建不等于补排；16草稿、32候选等容量门可能中止，未测规模失败率。 | [包内B_delta_assembly.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/B_delta_assembly.py:125) |
| delta机械编译与约束拒绝 | 明确保留/取消/替换/新增；保留旧值，新增或迁机需完整机序；过期开始条件、资格、批组和hold问题拒绝。 | C09条件性静态支持。 | 未显式改序的保留项复制基准顺序，非重新排序；编译结果明确仍需公共物理校验，不证明全部动态约束。 | [plan_delta.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py:118) |
| 候选检查与独立选择 | 成功check仅登记候选，按创建次序展示；较晚独立apply要求精确候选ID/hash，未见自动质量择优。 | C09补充confirmed；原阶段unverified保留。 | schema只开放已检查候选是程序过滤贡献；最终接受不能替代所有原始尝试分母。plan_from_action未见接入限定链。 | [interaction.py候选流](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py:469) |
| 公共提交与物理派工 | C09重试支持提交复制/校验选中计划，按每机首任务与模型条件检查就绪；环境另选择虚拟延迟组别推进。 | 静态贡献已核查；运行事实继承报告。 | 物理未就绪会等待，失效会要求重排；虚拟推进归环境。两份medium重试不认证全部物理可行或历史效果。 | [environment.py虚拟推进](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/environment.py:72)；[environment.py执行](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/environment.py:172) |
| 回放、提交意图与回执归档 | host保存原输出与哈希，提交前重放选择，先写intent再commit/receipt；异常结果保留unknown并停止。 | host静态控制流存在；底层保障待证。 | journal/transport等未完整审阅；unknown不等于未发生效果，不能据源码声称通用恰好一次提交。 | [V15 host.py提交链](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py:141) |
| 特定沿革恢复与snapshot检查 | V15 restore核对沿革、哈希和特定索引重放，声明零模型调用/物理推进；recovery_check范围为精确snapshot状态。 | 静态实现存在；通用恢复与新续跑待验证。 | 特定恢复不等于任意中断恢复；A24构造预算失败、C8模型通道失败及未验证续跑保留，恢复证书不升级为成功。 | [V15 restore.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/restore.py:8)；[recovery_check.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/recovery_check.py:26) |
| 排程运行预算与停止边界 | host有600秒调用配置、软/硬/UTC截止、日志余量与身份准入；outer禁止自动重试并留收尾余量。 | 静态代码存在；费用与实际时限待证。 | 配置不是实测硬终止；货币字段未知，恢复和失败资源不能清零；局部pending不等于根验收。 | [V15 outer.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/outer.py:13)；[V15 host.py预算](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py:56) |
| C构造器及参数选择 | 源码以gain_rate、权重和软预算构造具体任务；批准报告记载历史C调用constructive并明确apply，未用CP。 | 构造机制静态存在；历史调用事实来自批准报告。 | C host与逐调用参数链未直接复审；权重变化不证明质量增量，C-fixed未执行证据仍缺。 | [constructive_tool.py](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/constructive_tool.py:19)；[ABC批准报告](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/ABC_1h_plan_comparison_20261012.md:59) |
| 既有B开发运行与效率分析 | 批准报告记载一小时完成及物理/来源/机会审计，后期779调用、80提交，机械动作占调用43.4%、tokens43.2%。 | 已有批准报告运行证据；本轮未复跑。 | 份额不是可兑现节省；单个完成lot和版本混杂不支持长期排名。全开发1362尝试、已知tokens之外另3次未知。 | [B批准结果报告](__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/B_1h_results_efficiency_and_next_budget_20261012.md:7) |
| myharness调用编排、schema与用量 | S-05静态提取记录共享Semaphore、调用数门、取消和逐调用超时；schema严格适配/复验，归档成功及失败状态。 | 静态实现及测试定义；本轮无测试通过证据。 | schema不验证排程；maxAgents非token/货币总预算。usage进入成功路径后汇总，失败/超时可能已耗资源却未知。 | [codex-workflow-runtime.mjs](__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs:191)；[workflow-schema.mjs](__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs:1)；[测试定义](__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs:67) |
| myharness跨进程恢复边界 | C08确认五文件匹配冻结指纹；新建runId/目录，runtime重新初始化，未加载旧阶段或调用集合。 | 指定原生路径缺恢复；其他范围未知。 | 重连诊断、restoreOptional和测试thread_id不是恢复；落盘与本轮外层续接不证明底层resume。README历史smoke未绑定为当前亲跑。 | [codex-workflow.mjs](__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs:86)；[恢复范围说明](__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md:117) |

## 待验证的迁移假设

### 按字段和分支追踪实际决定者

**对应问题：**接受输出、合法候选或工具名称容易掩盖程序补机台和最终裁决。

**证据：**R2-C01, R2-C03, R2-C09

**成立条件：**区分模型原输出、过滤、聚合、解码、修复、回退与执行；限定版本和配置。

**最小验证：**后续若获准，检查平票、缺机台、单候选及无效输出，核对最终字段与原输出。

**证伪条件：**声称模型决定的字段由程序补选或改变，即推翻该分支B归属；本轮未执行。

### 拒绝式组装与较晚独立apply

**对应问题：**机械合并可能悄悄形成新排程决定，候选检查可能自动择优。

**证据：**R2-C09, A-02

**成立条件：**完整字段和处分由模型明确提供，候选锚点一致，程序只复制、展开和拒绝。

**最小验证：**待验证缺顺序、过期开始条件、失效hold及候选容量满时是否拒绝且无部分发布。

**证伪条件：**发现自动补值、代选或质量排序决定最终候选，推翻纯机械支持判断；调用份额不作节省率。

### 冻结规则与测试时适应分别评测

**对应问题：**持出成绩可能包含新场景搜索，离线成本与执行成本混合。

**证据：**R2-C05, R2-C06

**成立条件：**规则、输入域和搜索器固定，适应反馈与最终计分实例边界明确。

**最小验证：**待比较同规则零新增API执行与允许一代适应，分别核对合法性、质量、失败和全部生成成本。

**证伪条件：**冻结臂仍生成/选择规则，或测试计分反馈用于冻结前选择，即不能认作冻结泛化。

### 语义、初态与动态执行分层检查

**对应问题：**字段存在、静态合法或吞吐拟合不能保证历史绑定和随机资源约束。

**证据：**R2-C07, A-05, A-09

**成立条件：**保留unknown，明确区域/全厂范围、资源身份及初始状态证据。

**最小验证：**待审查CQT起点未知、绑定缺失和辅助资源冲突是否暴露为不可判定或执行拒绝。

**证伪条件：**默认零/空值制造合规结论，或静态检查遗漏动态冲突，即否定相应完整保障。

### 恢复状态、外部效果与累计资源分别认定

**对应问题：**落盘、回放成功和静态恢复证书容易被升级为安全续跑。

**证据：**R2-C08, R2-C09, A-08

**成立条件：**区分特定沿革恢复与通用resume，提交结果unknown不自动重发。

**最小验证：**待取合法范围的证据，核对提交已发生但回执缺失、状态恢复后授权变化及预算继承。

**证伪条件：**重复提交、效果无法对账或恢复清零预算，否定安全续接；研究阶段不接设备。

## 相对上一轮的增量

旧APPROVED研究保持原报告，OptiGuide、OptiMUS、Deep Agents、Smart Manufacturing Agents、LangGraph、Temporal、PyJobShop与MEC结论未在本轮重写。新增离线生成与测试适应边界、直接整表/逐步动作的实际决定者、单厂静态/动态对照及本地复用清单；缺同条件路线比较、完整成本和历史部署绑定。本轮Search对Cambridge GenAI职责的描述由C04纠正，不是修正旧APPROVED结论。C01原充分条件、C06原数字出处明确保留refuted。相对中间综合，四次重试完成，C09只在补充登记由unverified变为静态confirmed；原27次尝试、4次失败和中间综合均保留。A-05始终属于批准内部语义报告继承，未升级为外部CQT三核验效果。

## 关键论断与对抗核验

以下保留原命题、原判决和采纳限制。confirmed不表示已证明本厂收益；对证据不足或被反例推翻的部分，不能通过改写原命题来抹去原判决。

### R2-C01 · DynaSchedBench implementation · 原登记 refuted / 重试后 refuted

在公开代码固定提交 08975bf4a0473c5dff9177393bc6743db9ddc946 中，采用 select_machine=True 且模型输出被接受的路径，会将截断后候选展开为具体机台选项，由模型通过 ActionID 选具体工件/机台，属于本项目 B 方向的一种受限逐步决策。候选截断、开始时刻计算、无动作推进和失败回退仍由程序负责；因此它不是完整覆盖本项目 B 决策字段的实现，也不能仅因使用信息工具就归为本项目 C。该提交与论文实验版本/配置的对应关系尚未确认。

**原范围限制：**B归属限于采用该配置且模型选择成功的分支；若关闭机台选择，或模型失败后走程序回退，机台/动作的实际决定者会变化。论文没有逐项报告候选截断、适配器配置或失败分支发生率。

**采纳范围：**原阶段两份有效核验反驳、一份超时，原记录保留。补充重试独立返回 refuted/high；三角色最新有效判断均反驳，保留 refuted，不采纳“开启选机台且输出被接受就由模型决定机台”的充分条件。仅可据核验实际读取的分支，条件性描述最终有效 ActionID 唯一确定含合法 machine_id 的动作且被执行器采用、未经环境平票裁决或其他程序补选的受限逐步 B 路径。单动作绕过模型、旧格式缺机台输出、多样本平票、失败回退分别标记程序职责；收窄描述不是改写原命题后重新获得三票确认。论文是否采用相同版本、配置及各分支发生率仍未知。 补充核验直接用平票后的环境评分分支证伪；该核验未取得旧格式解析器，未把缺 machine_id 路径冒称为其本人的端到端验证。其他核验实际取得的解析器证据及各自访问限制分别保留。

**原命题提供的引用：** [B_project/C_project与ownership_fields](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[encode / _select_machine_for_action；请用 actual_code_anchors 中实际源文件行号](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/feature_extractor.py>)（访问/取证日期：2026-10-12）；[encode / _select_machine_for_action；请用 actual_code_anchors 中实际源文件行号](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Sim/Simulator.py>)（访问/取证日期：2026-10-12）；[§7.1、Appendix J](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=0；refuted=2；abstained=1。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

核验1：失败或无有效结果，保留为弃权。

原因：agent timeout after 600000 ms

[失败会话的原始事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0001/events.jsonl>)

#### 核验2：refuted / high

原命题判为refuted：开启机台选择且模型输出被接受，仍不足以保证由模型通过ActionID决定具体机台；反例保留了原有两个条件。2026-10-12实际读取指定六份公开代码快照，并复算SHA256与Git blob SHA，均与manifest一致；这些是本地快照读取。另通过GitHub工具在线读取固定提交的prompts.py，论文也已在线读取，未执行模拟、求解或模型调用。

展开机制本身成立：feature_extractor.py第337—355行先截断基础候选，再按机器候选展开并写入机台字段；第420—461行将工件、当前工序、机台对应到表格编号。有效编号分支在policy.py第737—742、766—769行返回对应动作，模拟器第541—542行接受有效指定机台，确实存在受限逐步B分支。

真正的反向尝试是用rg追踪编号缺失、合法性检查、精化和机台补选。静态构造两个合法工件、每工件两台机器，开启机台选择，采用直接模式、默认贪心精化和单样本，候选上限设为1；模型仅返回合法工件与机台组。prompts.py第1000—1019行会成功解析；policy.py第771—784行接受该动作，而第274—282行对缺机台的匹配动作返回合法，未标记失败回退。第813—814行原样保留动作，Simulator.py第169—170、544—559行遂由程序选择最早可开工机台。该接受路径并未用编号选具体机台，直接推翻原命题条件的充分性。这是源码分支反例，未声称论文实际发生过。

另有有效编号投票打平后由环境评分选动作的分支（policy.py第782—790行），也需披露算法的决定权。程序还负责随机与规则截断、当前工序、开始时间及重叠调整（模拟器第163—191行），环境负责无动作推进；单动作跳过模型、解析失败回退均存在。候选上限作用于展开前，不能当作最终表格行数上限。采样调用传入9999秒并可重试三次，实际超时和壁钟未验证。

依所给分类规则，观察/试算工具并不自动构成本项目C，完整B所需批次、等待等字段也未由模型完整承担。[论文§7.1、表3和附录J](https://arxiv.org/html/2605.27566v1)报告70实例评估及工具模式约三倍token消耗；这是作者结果，不能外推本厂。对提交号、机台开关、截断、失败和超时作限定检索未命中对应说明，代码与论文版本及分支发生率仍未确认；论文与同项目代码亦非独立实证。本次未验证原始可行率、修复后可行率、线上延迟或不同规模下的调度质量；不能由合法候选和最终可执行动作反推模型自行保证全部约束，也不能把校准器的规模实验当作该决策分支的规模实证。

**反向尝试：** 公开WebSearch："large language model" "dynamic scheduling" "invalid" "latency"；对指定六份快照执行rg -n：select_machine|ActionID|fallback|illegal|invalid|except|timeout|prune|top_k|earliest|machine_id|advance_if_idle|legal_actions|tool|token|cost|wait|idle；对policy.py快照执行rg -n：def _refine|def _env_score|GREEDY|REFLECTION|ActionID|action_id|execute_tool_call|tool_name|select_machine|request_timeout|9999|machine_id|base_action；对Simulator.py及policy.py快照执行rg -n：get_ready_operations|candidate_machines|batch|wait|advance_to_next_decision_point|def _env_score；论文HTML限定find：7.1 Experimental Configuration；J.1 Information；fallback；latency；trunc；08975；select_machine；wall-clock；invalid；timeout；WebFetch固定提交prompts.py的raw及GitHub blob URL均失败；随后GitHub fetch成功读取同一不可变提交文件，并定位parse_o1与编码调用

**限定建议：** 补充条件：模型给出有效ActionID，该编号唯一决定最终返回动作，动作携带有效machine_id且由执行器采用；排除旧格式缺机台输出、投票打平后环境评分选择、单动作跳过模型及程序回退。保留受限逐步B、未覆盖完整B字段及论文版本对应关系未确认的限定。

**未命中/访问限制：** 在所读论文HTML中，fallback、latency、trunc、08975、select_machine、invalid、timeout未命中；这不证明其他材料不存在相关说明。论文实验与固定提交的对应关系、接受旧格式及环境打平选择的发生率、实际推理超时仍未知。prompts.py经原生WebFetch两次访问失败，但随后通过GitHub工具成功读取；六份既有快照未冒称在线读取。全部分支判断均为静态核查，未复现运行。

**实际引用：** [实际源文件行号：prune_candidates L176-L328；encode L337-L355、L420-L461、L705-L714；读取本地公开快照并复核两种哈希](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/feature_extractor.py>)（访问/取证日期：2026-10-12）；[实际源文件行号：decide L79-L96、L144-L199；_is_legal L223-L282；_decide_o1_cognitive L711-L796；_refine_decision L798-L819；工具最终动作采纳 L585-L599](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/policy.py>)（访问/取证日期：2026-10-12）；[GitHub工具在线读取；按返回原源计算实际行号：build_cognitive_prompt_o1编码调用 L739-L741；parse_o1 L1000-L1039，尤其L1005-L1019允许缺少action_id和machine_id](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/prompts.py>)（访问/取证日期：2026-10-12）；[实际源文件行号：step_action L163-L191；_select_machine_for_action L534-L559；_get_ready_operations L1502-L1571；读取本地公开快照并复核两种哈希](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Sim/Simulator.py>)（访问/取证日期：2026-10-12）；[在线读取：§7.1、表3、§7.2、Appendix J.1/J.2；限定检索提交、配置、截断、失败和超时字段；Appendix G规模结果的对象是校准器](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0002/result.json>)

#### 核验3：refuted / high

截至2026-10-12，原命题的限定仍过宽：select_machine=True且模型输出被接受，并不足以保证最终工件、机台均由模型决定，因此按原句判为refuted。已读取清单内六份本地公开源码快照，重算SHA256和Git blob SHA全部匹配；这证明与所给清单一致，不冒称此次在线取得代码或复现实验。
正向证据支持其核心成功子分支：feature_extractor.py:176–328用随机抽样及两种PDR优先规则形成截断集合；330–355随后逐机台复制候选，写入machine_id；420–461以ActionID展示具体工件、当前工序和机台。policy.py:725–742的CoT有效编号分支直接返回对应候选，597–599的信息工具模式也由最终编号定动作。按已读B/C规则，这些分支可属受限逐步B，信息查询本身不构成C。
但实际反向rg检索发现遗漏的成功分支：policy.py:766–790先接受并映射有效ActionID；DIRECT多输出平票时，786–790由环境评分排序选最终动作，fallback_triggered仍保持false，仅记录tie_broken。因此，即使输出有效、机台选择开启，也存在程序作最终裁决的静态反例。另在223–282及771–784，合法性检查允许省略machine_id；Simulator.py:540–559在未指定合法具体机台时自行选最早可开始者。这些程序选择不能只归入模型失败回退，也不能将其发生率写成论文事实。
原句其余边界有依据：Simulator.py:163–191固定当前工序并计算开始时刻、必要时调整防重叠；275–314负责无就绪动作的推进；policy.py:181–200、743–751负责无响应或无有效编号的回退。没有模型明确形成批次及主动等待的完整字段覆盖。[论文§7.1和附录J](https://arxiv.org/html/2605.27566v1)已在线读取，全文反查commit、select_machine、fallback、truncat未命中，提交与实验配置对应仍未知。作者报告有固定PDR对照与观察/提示消融，但这些不隔离上述程序贡献；70实例覆盖采样也不自动证明持出泛化。质量分母为每实例最佳观测排程，费用报告为总tokens，不能等同本厂约束覆盖、真实执行延迟或货币成本。
据此作方法审计推断：迁移或比较B/C须保持候选过滤、截断、机台展开、投票裁决和回退同条件，提供相同观察及无模型对照，分别报告原始合法率、修复后合法率、分支占比与失败计入方式。基准的工序先后和资源不重叠检查不能外推为本厂全部约束覆盖，多次采样也不是多项独立研究。未运行模拟、求解或模型；代码、文档和论文属于同项目来源，不能合算独立实证。

**反向尝试：** rg -n --no-filename -C 2 'if len\(legal_actions\) == 1|if self\._is_legal|if len\(best_keys\) == 1|ties_broken|env_selected_when_tie|tie_broken|fallback_triggered|if act_m is not None|return True' m0.5_research/evidence/public-source-snapshots/DynaSchedBench__src__dsbx__Agents__LLMScheduler__policy.py；rg -n --no-filename -C 2 'if select_machine|if not cands|pruned = base_pruned|random.shuffle|random.sample|selected = selected\[:L\]' m0.5_research/evidence/public-source-snapshots/DynaSchedBench__src__dsbx__Agents__LLMScheduler__feature_extractor.py；rg -n 'B_project|C_project|ownership_fields|过滤|解码器|工具仅|batch|批次|等待' inputs/route-classification-rubric.json；WebFetch https://arxiv.org/html/2605.27566v1；读取§7.1及Appendix J；全文find：commit、fallback、truncat、select_machine、ActionID、latency、held-out；WebFetch 固定提交的prompts.py：raw.githubusercontent.com返回Internal Error，github.com页面返回Cache miss；随后curl通过127.0.0.1:7897尝试读取同一公开文件，代理连接失败

**限定建议：** 将B归属明确限定为：最终接受的有效ActionID映射到包含合法具体machine_id的候选，且最终选择未经环境评分平票裁决或其他程序补选。DIRECT平票、接受未指定机台的直接动作、单动作绕过模型及失败回退须分别披露决定者；提交与论文实验的对应关系继续保留未知。

**未命中/访问限制：** 已读论文§7.1、附录J及全文关键词查找未确认固定提交与实验配置的对应关系，也未取得候选截断或程序裁决、失败回退的实验发生率；未命中不证明这些资料不存在。额外公开解析器prompts.py的在线读取及代理尝试失败，未补核其实现。反例判断来自已核验的policy.py静态分支，不代表论文实验实际进入过该分支。

**实际引用：** [L4–5：B_project/C_project；L14–25：ownership_fields；L41–46：过滤、解码器及信息工具的归属限制](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[实际源文件：prune_candidates L176–328；encode L330–355、L420–461。读取的是本地公开源码快照，哈希与清单一致](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/feature_extractor.py>)（访问/取证日期：2026-10-12）；[实际源文件：decide L79–94、L144–200；_is_legal L223–282；工具最终编号映射L585–599；_decide_o1_cognitive L711–796，尤其L766–790有效输出后的环境平票裁决](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/policy.py>)（访问/取证日期：2026-10-12）；[实际源文件：step_action L137–191；advance_to_next_decision_point L275–314；_select_machine_for_action L534–559](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Sim/Simulator.py>)（访问/取证日期：2026-10-12）；[§7.1：70实例、匹配模型比较协议、质量及token分母；§7.3：固定PDR对照；Appendix J.1–J.2：信息工具、投票及提示消融](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0003/result.json>)

**重试后登记：** refuted；{'supported': 0, 'refuted': 3, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

#### 补充重试 R2-C01/v1/retry1

[原超时事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0001/events.jsonl>)；[本次重试记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-timeouts/agents/0003/result.json>)

refuted / high

截至2026-10-12，原句的限定条件仍不足以保证最终具体动作由模型决定，存在明确的静态代码反例，故判断为refuted；这不否认合法ActionID直接接受分支可属于受限B。
读取方式：通过本地只读命令检查白名单、分类口径及指定清单，读取六份公开源码快照的入口和必要函数，重算六份文件的SHA256与Git blob SHA，均与清单一致；论文通过真实WebFetch读取。未运行测试、模型、求解器或工厂模拟。
支持部分：feature_extractor.py第337行先截断基础候选，第344—353行在select_machine=True时逐机台复制动作并写入machine_id，第448—461行将具体工件、工序、机组、机台绑定到ActionID。policy.py第737—742、766—769及594—599行确实存在按合法ID直接取展开动作的接受分支。Simulator.py第540—542行保留有效指定机台。因此，模型在这些分支决定具体工件/机台，工具使用本身不能据此归为C。
关键反例来自源码反向检索：Direct模式接受多个合法输出后，第775—790行统计投票；两个不同合法ActionID并列时，第786—790行由程序调用_env_score并排序选最终动作。第284—289行表明评分来自环境估计或短程rollout。此时模型输出已进入候选集合，fallback_triggered仍保持False，仅fallback_type记为tie_broken；GREEDY或BEST_OF_N的后续处理直接保留该程序选出的动作（第813—819行）。所以“select_machine=True且模型输出被接受”并未排除程序决定最终工件/机台的路径。原句仅披露失败回退，遗漏了这个成功解析后的程序裁决条件，不能先补上限定再支持原句。
另一个需披露的接口边界是Direct的job/group匹配通道：_is_legal在缺machine_id时可返回True，模拟器随后按最早可开始时间补机台；其解析器本体本次未取得，故不把此通道写成已验证的端到端反例。
其余限定基本符合源码：合法候选由环境提供，截断含随机抽样和PDR选择；工序取current_op_index；开始时刻由程序取最大值并处理重叠；无动作推进及失败回退也由程序负责。这不足以覆盖本项目B全部字段。
[论文v1](https://arxiv.org/html/2605.27566v1)§7.1与J介绍实验协议、投票、反思及信息/模拟工具，但本次未找到固定提交、机台配置、候选截断或失败分支发生率的对应说明。未发现本命题把实验数字写成亲跑结果或读错表格；论文与源码属于同项目材料，不能作为独立复现实证。提交与论文实验版本、实际部署及上述分支发生率继续未知。

**反向尝试：** 本地rg定位指定白名单、分类口径、版本清单及DynaSchedBench快照清单；读取指定六份快照入口并重算SHA256/Git blob SHA。；仅在指定源码快照中执行rg反向检索：select_machine、ActionID、action_id、prune_candidates、_is_legal、fallback、machine_id、advance_if_idle、_select_machine_for_action。；源码限定检索：candidates.append、len(best_keys)、scored.sort、env_selected_when_tie、tie_broken、act_m、return True、voting_n、n: int；随后读取decide、_decide_o1_cognitive、_env_score及_refine_decision必要行。；WebFetch https://arxiv.org/html/2605.27566v1；读取§7.1和Appendix J，并全文find fallback、ActionID、select_machine、commit、truncat。；WebFetch固定提交的prompts.py：先访问raw.githubusercontent.com，再访问GitHub blob页面；两次均返回Cache miss，停止重试。

**限定建议：** 增加条件：模型返回合法ActionID，最终动作直接保留该ID对应的具体工件/机台，且不经过环境评分破并列、缺机台补选、单动作免调用或失败回退；另行披露多样本聚合和反思重编码。该缩窄命题可获支持，原句不能因此改判。

**未命中/访问限制：** 在指定论文已读章节及全文词查中，未找到固定提交与实验版本/配置的对应关系及失败分支发生率；未命中不证明不存在。prompts.py两次真实抓取均失败，解析器本体未核实。未复现任何运行结果。

**实际引用：** [route_definitions.B_project/C_project；ownership_fields；limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[实际源文件行号：prune_candidates L176–328；encode L337–355、L448–461](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/feature_extractor.py>)（访问/取证日期：2026-10-12）；[实际源文件行号：_decide_o1_cognitive L718–722、L766–790；_env_score L284–289；_refine_decision L813–819；_is_legal L274–282](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Agents/LLMScheduler/policy.py>)（访问/取证日期：2026-10-12）；[实际源文件行号：step_action L163–191；_select_machine_for_action L534–559](<https://github.com/dsbx7/DynaSchedBench/blob/08975bf4a0473c5dff9177393bc6743db9ddc946/src/dsbx/Sim/Simulator.py>)（访问/取证日期：2026-10-12）；[§7.1 Experimental Configuration；Appendix J.1 Refinement and Robustness Mechanisms、Active Exploration via Tool-Use](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）

### R2-C02 · DynaSchedBench paper（ICML 2026；arXiv:2605.27566 v1） · 原登记 confirmed / 重试后 confirmed

在作者报告的70例DynaSched子集上，表3的L1 Direct、L1 CoT、L1+Tool依次为2.0%/3.752M、1.9%/4.016M、2.0%/12.614M（质量均值/总Tokens）；这一观察支持“表中CoT略低而工具版未降低表列均值、总Tokens较高”的描述性结论。

**原范围限制：**表3未明确基础模型、每配置实际有效n、失败样本处理、token统计范围及变体配对检验；均值差小且四舍五入，不能据此称CoT显著更优或工具必然无效。表4没有L1 CoT，不能借其分布数字补强此比较。

**采纳范围：**三份有效核验支持作者表 3 的有限描述：70 例选取子集中，L1 Direct、L1 CoT、L1+Tool 的表列平均 makespan 差距为 2.0%、1.9%、2.0%，总 tokens 为 3.752M、4.016M、12.614M。差距参照每实例最佳已观察排程，不是已证最优解；70 不自动等于各行有效 n。不得推成 CoT 显著优越、工具所有指标均无收益、B 优于 C 或本厂效果。表 4 部分分位数改善仍须保留；基础模型、失败处理及完整 token 口径未知。

**原命题提供的引用：** [§7.1表3；70例子集说明](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，实际在线读取了指定arXiv v1正文，未以本地快照冒充在线访问。表3列顺序为Tokens（百万）、Mean Cmax（%）、SE；三行确实对应L1 Direct：3.752、2.0；L1 CoT：4.016、1.9；L1+Tool：12.614、2.0。§7.1明确说明评估子集共70例，其中Grid 30例、Sweep 40例，并将成本指标称为总token消耗。因此，原命题对数字及表列精度下趋势的描述直接成立。质量指标是相对每例最佳已观察排程的归一化makespan差距，不能理解为原始工期或相对已证明最优解的差距。[论文v1](https://arxiv.org/html/2605.27566v1)。
反向核查实际执行了限定arxiv.org的通用技术词检索，并在v1全文查找paired、failure、token、fallback，随后逐项检查表4、表6及附录J。表4没有L1 CoT；表6检验模型与派工规则；表j-2的42个完整案例及Wilcoxon检验针对L2/L3提示机制消融，均不能补作这三种L1配置的配对检验。已读相关段落未明确表3基础模型、各配置有效n、失败样本纳入规则，以及tokens是否包含输入、输出、重试和工具往返。70是子集规模，不能直接当作每行有效n。均值仅显示一位小数，不能据此宣称CoT显著更优或工具必然无效。
归属审计还实际读取作者当前main分支代码片段：policy.py将模型action_id映射到剪枝候选；非法输出可以退回首候选或SPT；Direct多候选平票可交由环境评分选择。这些程序决策必须披露。[策略代码](https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/policy.py)。tools.py的simulate_action返回候选动作的短程评估信息，不能仅凭使用工具归为本项目C。[工具代码](https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/tools.py)。官方文档也列出候选数量、机器选择及回退选项；其模型命令示例不能补认表3模型身份。[官方文档](https://dsbx.readthedocs.io/agents.html)。当前代码与v1实验的提交及参数绑定未获确认，补机台、等待和回退实际发生比例仍未知。三个raw源码链接访问失败，改用GitHub页面读取；sampler页面仍失败。本结论仅支持作者报告的描述性比较，未运行复现，也不构成本厂效果或B/C胜负证据。

**反向尝试：** WebFetch：https://arxiv.org/html/2605.27566v1；读取表3、§7.1、表4、表6、§4.2、§5及附录J；WebSearch：dynamic flexible job shop scheduling LLM chain-of-thought tool token statistical significance paired；domains=[arxiv.org]；WebFetch/find：指定v1全文检索Table 3:、70、Table 4:、model、failure、token、paired、fallback；WebFetch：https://arxiv.org/abs/2605.27566v1；核对Submission history；WebFetch：https://dsbx7.github.io/；沿作者链接读取公开GitHub仓库和官方文档；WebFetch：https://dsbx.readthedocs.io/agents.html；WebFetch：作者main分支LLMScheduler的policy.py、sampler.py、tools.py三个raw链接；均返回Cache miss；WebFetch：改读GitHub的policy.py和tools.py页面；sampler.py页面返回Internal Error；WebFetch/find：policy.py检索fallback、select_machine、action_index；tools.py检索simulate_action

**限定建议：** 保留原命题的作者报告、70例子集和表列精度限定；质量均值宜明确为相对最佳已观察排程的makespan差距。不要扩展为统计显著性、工具普遍无效、纯模型决策或本项目B/C效果结论。

**未命中/访问限制：** 未在已读v1相关正文、表格及附录中找到三种L1配置的有效n、失败处理、完整token口径或对应配对检验，也未确认公开main代码与表3实验的提交绑定。raw源码及sampler访问失败不表示文件或相关证据不存在。

**实际引用：** [表3与§7.1（网页行433–447）；表4（450–456）；表6（477–482）；§4.2、§5；附录J.1/J.2及表j-2](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）；[当前main；CoT action_id映射、非法输出回退与Direct平票环境评分分支（网页行3414–3546）](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/policy.py>)（访问/取证日期：2026-10-12）；[当前main；SIMULATE_ACTION_TOOL、execute_tool_call、_impl_simulate_action（网页行1293–1570）](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/tools.py>)（访问/取证日期：2026-10-12）；[LLM Agents：模型命令示例、候选与机器选择选项、无API密钥时的回退说明（网页行82–117）](<https://dsbx.readthedocs.io/agents.html>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0004/result.json>)

#### 核验2：supported / high

核查日期：2026-10-12。已实际在线读取指定arXiv v1原文。表3前三行与原命题逐项一致：L1 Direct为2.0%／3.752M，L1 CoT为1.9%／4.016M，L1+Tool为2.0%／12.614M。§7.1说明评估子集含70例，其中Grid 30例、Sweep 40例，并将指标描述为相对每例最佳已观察排程的归一化完工时间及总token消耗。因此，“质量均值”应理解为该完工时间差距指标，较低较好；不能理解为通用质量评分。[原论文v1](https://arxiv.org/html/2605.27566v1)

实际反向尝试包括：使用通用技术词搜索动态柔性作业车间排程、工具增强、CoT、失败、超时与token成本；在原文查找timeout、fallback、invalid、failed和paired，并核对表4、表6及附录J。表4确实存在限制更强结论的例子：工具版相对Direct的p50为0.52对0.63，p90为2.47对2.57，部分分位数更低；但均值为2.03对1.95，且表4没有L1 CoT。这能限制“工具在所有指标上均无收益”的说法，却不能推翻本命题限定于表3均值的描述。表3两项2.0%经四舍五入相同，也不能证明未舍入均值完全相等。

对统计缺口的核查未找到这三个L1配置之间的配对检验。表6检验的是模型与启发式规则；附录J的42个完整案例属于另一组提示机制消融，均不能移用于本比较。§7.1虽列出多个模型家族，却未明确表3对应的基础模型；70是所选子集规模，不能据此确认每配置实际有效n。上述失败和超时关键词未命中，不能推断失败不存在；失败样本如何进入均值、重试如何计入token，以及输入、输出、缓存等统计边界仍未知。token总量更高也不能直接量化货币成本或实际调度延迟。

合法性贡献同样需要限定：§4.2说明环境过滤允许动作，附录J说明工具提供候选详情与模拟完成时间供后续决策。这些机制不能被写成模型独立保证合法，也不能仅凭调用工具就认定为本项目C。此次仅核查作者报告，未运行模拟或复现；没有把同项目解释当作独立实证，也没有把该子集观察外推为本厂效果。未发现推翻原限定命题的证据。

**反向尝试：** WebFetch：https://arxiv.org/html/2605.27566v1；读取表3、§7.1、表4、表6、§4.2及附录H/J；WebSearch：dynamic flexible job shop scheduling LLM tool augmentation chain of thought failed timeout token cost；domains=arxiv.org；原文find：Table 3、70、Table 4、timeout、fallback、invalid、failed、budget、paired；本地只读：cat inputs/internal-allowlist.json inputs/route-classification-rubric.json inputs/internal-code-baseline.json

**限定建议：** 保留原有限定，明确质量指标为相对最佳已观察排程的完工时间差距，并将结论限定为表列均值与总token的描述性比较。

**未命中/访问限制：** 原命题数字与70例说明均已找到。未找到的仅是已读v1中三个L1配置的配对检验、有效样本数、失败处理及详细token口径；关键词未命中不等于相关情况不存在。

**实际引用：** [表3及§7.1（网页行433—447）；表4（450—456）；表6（477—482）；§4.2（399—401）；附录J.1/J.2（1015—1062）](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0005/result.json>)

#### 核验3：supported / high

截至2026-10-12，已在线读取[论文v1原文](https://arxiv.org/html/2605.27566v1)。表3（原文行433—438）逐项报告：L1 Direct为2.0%/3.752M，L1 CoT为1.9%/4.016M，L1+Tool为2.0%/12.614M，均与命题一致。§7.1（行443—447）说明评估子集含70例，其中Grid为30例、Sweep为40例；质量指标相对于各实例最佳已观测排程归一化，成本指标为总token消耗。因此支持表列CoT均值略低、工具版均值没有降低且总Tokens较高的描述。这里的百分比不是相对理论最优解的误差，也不是本厂收益。

反向核查实际检索了该研究的配对显著性、失败处理、基础模型及token核算，并回读表4、表6与附录J。限定于论文及作者公开站点的两条搜索未返回结果，不能据此断言补充资料不存在。表4（行450—456）确实没有L1 CoT；其Direct和Tool的较精细均值不能补出CoT分布。表6检验的是模型与固定派工规则，附录J表j-2的42个完整案例检验的是L2/L3信息机制，均不能充当表3三种L1配置的配对检验或有效样本数。

统计限制仍成立：表3均值仅保留一位小数，CoT差距为表列0.1个百分点；虽有各列标准误，缺少配对差值的不确定性，不能据此判显著。§7.1列出多个模型家族，但未明确表3所用基础模型、逐配置有效n、失败样本纳入方式，以及输入、输出、重试和工具对话的token统计范围。同提示、两例示范、温度0等匹配条件明确用于表5，不能自动移用于表3。因而也不能将总Tokens直接换算成单例费用或实际响应延迟。

迁移审计方面，§5及附录J.1描述的工具提供候选信息或模拟完成时间估计，agent随后作最终决定；仅凭L1+Tool名称不能归为本项目C。§4.2明确环境过滤合法动作，必须披露这一贡献，不能把合法性全部归功于模型；论文信息也不足以确认本厂lot、机台、批次和等待的完整决策归属。附录H说明这是生成实例池的多样性子集，不能当作本厂持出泛化验证或全部工艺约束覆盖证据。本次仅核对作者报告，没有运行或复现；结论不延伸为CoT显著更优、工具必然无效或本厂B/C路线优劣。

**反向尝试：** WebFetch：https://arxiv.org/html/2605.27566v1；WebSearch："DynaSchedBench" "CoT" "Table 3"；WebSearch："DynaSchedBench" "failed" "tokens" model；WebSearch："DynaSchedBench" "L1 CoT" paired significance failure tokens；限定arxiv.org、github.com、dsbx7.github.io；WebSearch："DynaSchedBench" "Table 3" model token accounting；限定arxiv.org、github.com、dsbx7.github.io；原文定位：Table 3、70、L1 CoT、GPT、Table 4、token、failure、complete cases；回读§4—5、§7、附录H及J

**限定建议：** 无需改写原限定命题；继续保留“作者报告”“表列均值”和“总Tokens”，不得升级为显著性、普遍有效性或本厂迁移效果结论。

**未命中/访问限制：** 命题对应表格和70例子集说明均已找到。未找到表3三种L1配置的配对检验及完整核算口径；限定搜索无结果只表示本次未命中。

**实际引用：** [表3及§7.1：行433—447；表4：行450—456；表6：行477—482；§4.2—5：行399—407；附录H：行934—963；附录J.1—J.2：行999—1060](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0006/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C03 · SCHEDBench direct full schedules · 原登记 confirmed / 重试后 confirmed

SCHEDBench v2 论文主实验是在六类共 1,132 个实例上，让 13 个 API 模型零样本直接输出完整安排，随后解析并验证硬约束，原文未报告使用求解器语义修复模型输出。其主实验跨家族平均可行率为 15.2%，所列最佳模型 GPT-5.5 为 55.9%；这些是该论文的一次完整作答协议及跨家族汇总，不能外推为本厂迭代式 B 的合法率，且其中 JSP 是固定机器路线，不直接验证 FJSP 机器分配能力。

**原范围限制：**评估程序的完整解析/验证实现未在指定Datagen仓库中确认；“未报告修复”不等于证明所有未公开代码分支均不存在修复。

**采纳范围：**三份核验支持论文 v2 主实验的限定描述。15.2% 是每模型按全部 1,132 实例计算总体可行率后对 13 模型取平均，家族按实例数加权；GPT-5.5 为 55.9%。14,716 份输出含 56 份不可解析，分母不能改成 14,660；可解析不等于可行，质量 gap 另仅统计可行输出。原文未报告语义修复不等于证明未公开实现绝无修复。固定机台 JSP 不验证 FJSP 机台分配，单次整表协议不等同本厂迭代 B；470/150 子实验、整体费用及模型版本不能混用。内部未接运行的 prompt 草案不作为本厂运行证据，迭代协议依据 rubric 与已批准背景报告。

**原命题提供的引用：** [§4.1、§4.4、Appendix B.2；Table 19](<https://arxiv.org/html/2608.00991v2>)（访问/取证日期：2026-10-12）；[route_definitions.B_project/C_project](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，原限定命题获支持。本次在线读取指定v2原文。§3.4、表2列出JSP 262、RCPSP-SM 400、RCPSP-MM 300、ITC 21、INRC 69、NSPLib 80，合计1,132实例。§4.1及附录B.1说明13模型均经托管API、零样本作答，每个模型—实例对评估一次；B.2要求直接给出完整安排，禁止工具、外部求解器和可执行代码。§4.4记录移除非实质附加文字、解析候选安排、验证硬约束；B.1明确CP-SAT用于验证，§3.3另用于参考解核验，未报告求解器语义修复。[论文v2](https://arxiv.org/html/2608.00991v2)

表3及表10对应v4主实验：15.2%是13模型总体可行率的平均，每个总体率按全部1,132实例汇总；这里的跨家族汇总按实例数加权，并非六家族等权平均。GPT-5.5对应55.9%，附录B.3标明2026-04-23版本。表19为1,132×13=14,716份输出，其中14,660可解析、56不可解析。可行率使用全部实例分母，不能改用仅可解析输出；99.6%只是解析成功率。470实例的配对消融及150实例的渲染种子实验另有协议，不能拼入主实验分母或混用其结果。

实际反向搜索包含修复、求解器和提取器的技术词，并限定论文及作者代码域；另在v2全文查找repair、mask、fallback，未命中这些词。已读Datagen目录及step2_solutions.py：generate_jssp按源实例暂存输入，--bks提取参考值，--solve调用源实例求解脚本；这条链不能充当模型输出修复的证据。[作者代码](https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py) 但scoring.py、JSP求解脚本及递归树接口访问失败，完整评估解析与验证实现仍未确认；当前main也未绑定为论文实验提交。因此只能确认原文未报告语义修复，不能证明未公开分支绝无修复、补排或回退。

归属依据实际输出：JSP要求各工序开始时间，指定机器来自题面，模型没有FJSP可选机台分配任务。所述协议未报告动作掩码、构造解码器或修复器替模型决定安排，但也不能仅因完整输出就认定覆盖本项目B的全部决策维度。内部rubric行4–5、45允许B多轮delta反馈；对获准interaction.py做rg反向查找并读取_dispatch分支，见显式检查后由后续模型输出选择候选，其文件哈希与清单一致。该文件是审查草案，不是工厂执行效果证据。故这些比例属于论文直接整表作答协议的作者报告，不能外推本厂迭代B合法率。本次未复现实验；论文、README和同仓代码也不构成独立实证。

**反向尝试：** WebFetch：https://arxiv.org/html/2608.00991v2；读取§3.3–3.4、§4.1–4.4、附录B.1–B.3及表2、3、10、19；WebSearch：SCHEDBench scheduling benchmark "repair" "solver"；WebSearch：SCHEDBench zero shot feasibility 1132 13 models；WebSearch："SCHEDBench" repair solver extractor；domains=arxiv.org,github.com,huggingface.co；WebSearch："SCHEDBench" "15.2" feasibility；domains=arxiv.org,github.com,huggingface.co；原文反向查找：repair、mask、fallback，均无匹配；另查Table 19、github.com及实验设置；WebFetch：作者Datagen仓库根目录、src/domains、utils目录及step2_solutions.py；查找src.domains调用路径；访问尝试：utils/scoring.py、src/domains/jssp/solve_instances.py及GitHub递归树接口，未成功取得内容；内部rg：inputs/route-classification-rubric.json、internal-allowlist.json及internal-code-baseline.json中的B_project、C_project、多轮、delta和interaction.py路径；内部rg：B_base_evidence_v13/workflow/interaction.py及B_feedback_admission.py中的feedback、repair、fallback、check_assembly、apply和候选选择分支；随后读取interaction.py第379–511行相关片段；只读哈希核对：interaction.py的SHA-256与internal-code-baseline.json对应记录一致

**限定建议：** 保留原限定结论，并将15.2%的统计口径明确为“13个模型在全部1,132实例上的总体可行率之平均，家族按实例数加权”；继续保留“未报告修复”及“不能外推本厂迭代B”的限制。

**未命中/访问限制：** 未在已读原文中找到语义修复、动作掩码或修复回退的报告；部分公开代码链接返回Cache miss/Internal Error，递归树接口不可访问，完整评估解析与验证实现未确认。这些未命中及访问失败不证明相关实现不存在；本次也未复现作者结果。

**实际引用：** [§3.3–3.4；§4.1–4.4；Appendix B.1–B.3；Tables 2、3、10、19](<https://arxiv.org/html/2608.00991v2>)（访问/取证日期：2026-10-12）；[load_raw_targets、generate_jssp、main中的--solve/--bks分支；当前main，未确认论文实验提交](<https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py>)（访问/取证日期：2026-10-12）；[根目录文件列表；README的Compute BKS及Generate all 5 variants段，仅作代码范围说明](<https://github.com/SCHEDBench/SCHEDBench_Datagen>)（访问/取证日期：2026-10-12）；[行4–5：route_definitions.B_project/C_project；行45：允许多轮工具反馈的delta决策](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[行1–5审查草案说明；next_prompt及_dispatch的check_assembly/apply分支；SHA-256=8122fd56a6c89a44b629b0a24fe523380e63d3737b1188a183061f5648428c89，与指定清单一致](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_base_evidence_v13/workflow/interaction.py>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0007/result.json>)

#### 核验2：supported / high

截至2026-10-12，在线读取[论文v2](https://arxiv.org/html/2608.00991v2)，原限定命题获支持。表2为六个来源家族、合计1,132实例；§4.1和附录B.1/B.2说明13个模型均经托管API访问，零样本，每个模型—实例对作答一次，要求直接输出最终安排。§4.4披露去除非实质性多余文本后解析并验证硬约束，B.1明确使用CP-SAT，因此必须保留评估工具贡献，不能描述成完全没有后处理或求解器参与。
表3的All行为GPT-5.5可行率55.9%、跨模型平均15.2%。统计口径是每模型在全部1,132实例上的可行率，再跨13模型平均，家族按实例数量加权，并非六家族等权平均。表19明确14,716次主实验输出，其中14,660可解析、56不可解析；99.6%解析成功率不等于合法率。470实例消融属于另行实验，不能并入主实验分母。
实际反向搜索了SCHEDBench与repair、retry、flexible及Datagen等组合，并在论文全文查找前三词，未命中；但确实命中了文本后处理和CP-SAT验证说明。进一步读取作者[Datagen源码](https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py)：main及generate_jssp分支从源实例确定目标，提取BKS或求解参考安排，其--solve不是读取并修复模型答案的入口。已查范围未确认完整模型输出解析、验证实现，不能据此证明其他或未公开分支没有修复；README、源码与论文也不是独立效果实证。
内部用rg反查允许的B工程中repair、fallback、feedback及具体分支。interaction.py的check_assembly编译模型已封存的delta，apply要求在后续独立输出中显式选择候选；这支持“存在多轮检查反馈协议”的范围区别，未证明实际运行效果。分类标准第45行也明确本项目B允许多轮delta决策，故论文单次整表结果不能直接替代本厂合法率。JSP模板预先指定每工序机器，答案只给开始时刻，不能据此证明FJSP机器分配能力。
负面和成本限定仍须保留：参考解核验有10/20秒预算，超时实例保留BKS；目标质量只在可行输出上统计；附录给出全评估约2,371美元的估算，不能换算成本厂逐决策成本或实时延迟。本轮只做静态证据核查，未复现实验。

**反向尝试：** WebSearch: SCHEDBench scheduling benchmark repair retry iterative solver validation flexible job shop；WebSearch: "SCHEDBench" "15.2" "55.9"；WebSearch: "SCHEDBench" "repair"；WebSearch: "SCHEDBench" "Datagen"；WebSearch: "SCHEDBench" "flexible"；WebSearch: SCHEDBench Datagen code GitHub；限定github.com、huggingface.co、arxiv.org；WebSearch: SCHEDBench scheduling benchmark repair iterative retry evaluation；限定github.com、huggingface.co、arxiv.org；WebFetch: https://arxiv.org/html/2608.00991v2；读取主实验、指标、提示、成本、超时与表19；全文find repair、retry、flexible、post-processing、timeout；WebFetch: 作者Datagen根目录、README、src/domains目录及step2_solutions.py；find def main、repair、model、--solve；本地rg: 在允许的B_base_evidence_v13/workflow/B_feedback_admission.py与interaction.py中搜索def、retry、repair、fallback、admit、feedback、round，并读取check_assembly/apply分支；本地读取route-classification-rubric.json、internal-allowlist.json及internal-code-baseline.json；核对interaction.py SHA256与冻结清单一致；仅对表3舍入百分比和实例桶数量做算术回核：633/1132≈55.9%，2231/14716≈15.2%；未运行排程或求解

**限定建议：** 将“跨家族平均”显式标为“按家族实例数加权的全实例可行率，再对13个模型平均”；保留“论文未报告语义修复”，并注明完整评估实现尚未确认。

**未命中/访问限制：** 在已读论文和Datagen公开根目录、目录列表及step2源码范围内，未确认完整模型答案解析/验证实现或求解器语义修复路径。src/domains页面出现部分加载报错，但目录列表可读；未据此宣称完整仓库审计成功。关键词未命中不证明机制不存在，未公开分支、输出验证超时的具体处理及本厂效果仍未知；本轮未复现。

**实际引用：** [Table 2、Table 3 All行；§4.1、§4.2、§4.4；Appendix A.7、B.1、B.2；Table 19](<https://arxiv.org/html/2608.00991v2>)（访问/取证日期：2026-10-12）；[load_raw_targets、generate_jssp、main；--bks/--solve分支；repair与model查找未命中](<https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py>)（访问/取证日期：2026-10-12）；[公开根目录文件列表；README Compute BKS、Generate all 5 variants](<https://github.com/SCHEDBench/SCHEDBench_Datagen>)（访问/取证日期：2026-10-12）；[route_definitions.B_project/C_project；comparison_required；limits第45—46行](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[_dispatch：check_assembly第468—489行、显式候选选择与apply顺序第501—507行；反馈路径rg命中；SHA256与冻结清单一致](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_base_evidence_v13/workflow/interaction.py>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0008/result.json>)

#### 核验3：supported / high

截至2026-10-12，已在线读取指定v2原文。Table 2六族数量为262/400/300/21/69/80，共1,132；§4.1、B.1–B.3说明13个托管API模型零样本、每模型—实例一次完整作答。Table 3总体行及§5.1直接报告15.2%和GPT-5.5的55.9%。统计应明确：每模型总体率以1,132例为分母，15.2%再跨13模型取均值，并非六家族等权平均。按分桶率反算得到633/1,132=55.9187%，全部可行数2,231/14,716=15.1604%；这是表格算术核对，非复跑。Table 19的14,660可解析、56不可解析合计14,716，可解析不等于满足硬约束；主表分母未缩成14,660，失败计分的完整实现仍未知。[论文v2](https://arxiv.org/html/2608.00991v2)。
§4.4仅描述清除非实质文字、提取安排、验证硬约束；B.2禁止模型调用外部工具/求解器，B.1披露CP-SAT验证。实际反向搜索用了SCHEDBench与repair、extractor、validation等限定词，原文repair检索无命中；搜索未找到可核实的语义修复反例。作者Datagen目录/README和step2 main()的互斥--bks/--solve分支表明其求解用于基准参考解制作，不能据此称主评估由算法安排。[作者代码](https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py)。完整评估调用链尚未确认，部分代码页访问失败；未命中不证明未公开分支绝无修复。
内部实际用rg反查rubric的B/C定义、多轮delta及合法动作过滤限制，并查B_delta_prompt.py的feedback/build_prompt路径：252–288行透传反馈与模型记忆，但文件头明确只是未接运行的评审草案。它支持协议区别，不能证明本厂部署或效果。按判据，论文可作直接完整安排的机制证据；不能因使用验证器归C，也不能宣称已验证本厂lot、机台、批次、等待等全部决定权。JSP示例每道工序机器已指定，B.2仅要求开始时间，因此不验证FJSP备选机器分配；RCPSP-MM模式选择也不能替代该验证。
迁移判断还受静态公开实例、自然语言整表输出限制。470例配对变体和150例渲染种子实验不是持出新厂泛化，也不是多轮合法性反馈消融；BKS不构成本厂同预算B/C基线。目标差距仅在可行输出上统计，不能用其掩盖失败。B.1费用/token覆盖整套评估，未拆主实验单例壁钟，不能除以14,716推成本厂延迟或费用。本次未运行排程或复现，作者论文与同项目代码也不计作独立实证。

**反向尝试：** WebFetch：https://arxiv.org/html/2608.00991v2；读取§3–§5、Appendix B.1–B.3及Table 19；WebSearch：SCHEDBench direct schedule repair parser validation solver；限定arxiv.org、github.com；WebSearch：SCHEDBench Datagen evaluation extractor feasibility；限定github.com；WebSearch："SCHEDBench" "repair"；限定arxiv.org、github.com；WebSearch："SCHEDBench" "extractor"；限定github.com；论文页内检索：14,716、15.2、Table 19、repair、GitHub；WebFetch：作者Datagen仓库、step2_solutions.py、src/domains及utils目录；检索def main、add_mutually_exclusive_group、args.solve；WebFetch尝试：raw.githubusercontent.com上的step2_solutions.py、GitHub上的utils/scoring.py及src/domains/jssp目录；rg -n -C 3 'route_definitions|B_project|C_project|offline_generation|多轮|合法动作|原始可行率|tokens|持出' inputs/route-classification-rubric.json；内部rg反向检索：feedback|retry|repair|fallback|machine_id|batch_id|wait_until|compile_delta|assemble；限定获准B_base_evidence_v13/workflow下的B_delta_assembly.py、B_delta_prompt.py、B_feedback_admission.py

**限定建议：** 建议把“跨家族平均可行率”明确为“各模型以全部1,132例计算总体可行率，再对13模型取均值为15.2%”，保留仅限作者主实验协议、未报告修复及不能外推本厂迭代式B的限定。

**未命中/访问限制：** 未确认完整模型输出解析器、验证器及失败计分调用链。raw版step2访问返回Cache miss，随后成功读取GitHub代码页相关分支；utils/scoring.py和jssp目录访问失败。论文repair检索及限定搜索未提供语义修复反例；这些结果不证明未公开实现不存在修复。

**实际引用：** [Table 2、Table 3总体行；§4.1–4.4、§5.1；Appendix B.1–B.3；Table 19；Figure 2固定工序机器示例](<https://arxiv.org/html/2608.00991v2>)（访问/取证日期：2026-10-12）；[main文件列表；README的Compute BKS、Generate all 5 variants及Reproducibility](<https://github.com/SCHEDBench/SCHEDBench_Datagen>)（访问/取证日期：2026-10-12）；[main()：互斥--solve/--bks参数、load_raw_targets及generate_*参考解生成分支](<https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py>)（访问/取证日期：2026-10-12）；[route_definitions，行3–7；comparison_required，行26–38；limits，行40–46](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[行1–5评审草案/未接运行声明；行20–32请求协议；build_prompt()行252–288反馈与模型记忆透传](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_base_evidence_v13/workflow/B_delta_prompt.py>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0009/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C04 · GenAI job scheduling FJSP case · 原登记 confirmed / 重试后 confirmed

就 Cambridge DOI 10.1017/S0890060425100152 论文明确描述的本地系统而言，自然语言查询经词典/语言预处理映射为 ETFN，由 MATLAB 修改数学规划与遗传算法程序，具体排程由 GA 生成；论文这些机制描述不足以证明本地系统调用了大语言模型，因此不能凭 GenAI 标题把它算作本项目直接 B 或 LLM 调用构造器的 C 证据。文中 ChatGPT/DeepSeek 是另列比较对象。

**原范围限制：**依据论文对系统的文字说明和伪代码；没有公开实现可检查 MATLAB 控制流，也不能据此判断作者系统之外的通用 ChatGPT/DeepSeek 实际如何分配决策。

**采纳范围：**三份核验均支持限定纠正：所读论文明确描述的是词典/语言预处理→ETFN→MATLAB 修改数学模型与 GA 程序→GA 生成具体排程。仅凭 GenAI 标题或免预训练 GPT 的措辞，不能把本地系统计为已验证的 LLM 直接 B 或 LLM 驱动 C。保留“已读机制不足以证明”而非“绝对没有使用 LLM”。原限制“没有公开实现”收窄为截至核查日未定位可确认属于作者的公开实现；ChatGPT/DeepSeek 比较行既不证明本地调用 LLM，也不足以确认比较对象的具体工具/纠错分工。表 10 仍只是方法和计时边界不足的作者报告，不用于同条件 B/C 胜负。

**原命题提供的引用：** [方法 Steps 2–5、附录B](<https://doi.org/10.1017/S0890060425100152>)（访问/取证日期：2026-10-12）；[route_definitions 与 limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，原命题在其限定范围内得到支持。本次实际在线读取了 Cambridge 官方论文 HTML 和17页 PDF，并用 rg 反查指定分类规则、代码基线清单及本命题抽取快照；后者仅作为本地转述核对，没有替代原文，也不是独立实证。
方法 Step 3–1 描述分词、词干及词形处理、关键词关系识别和参数提取；Step 3–2 按系统词典查找符号及修改项，组成 ETFN。Steps 4–5 则说明 MATLAB 程序修改数据库内的 Lingo 格式数学规划模型，另一个 MATLAB 函数更新既存 GA 脚本。更直接的限定证据在讨论段：作者称词典增补使查询分析迅速收敛，因此“似乎无需”运行基于 DNN 的 LLM 分析查询。结论也将 ANN/DNN 处理关键词列为未来研究。原文确实出现免于训练或预训练 GPT 的措辞，但这些句子没有交代本地 GPT 调用，不能单独作为使用 LLM 的证据。[Cambridge原文](https://www.cambridge.org/core/journals/ai-edam/article/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem/508C2D5805370719650FC04B2F514197)
附录B的查询分析输出是适应度函数和用户指定约束；GA 随后生成种群、交叉、变异并按适应度选择染色体。可行性检查会删除违反用户约束的染色体并补入新染色体，因此具体候选生成和替换属于算法贡献。用户还可强制指定机台及工序顺序，不能把用户约束误记为模型决策。LINGO 被描述为验证默认数学模型及目标、约束改动的工具，并无证据表明它负责通用服务比较中的排程。论文没有充分展开机台和时间解码、等待推进、解析失败回退等控制流，不能据伪代码补齐这些细节。
反向检索主动寻找 ETFN、LLM、MATLAB 实现和公开源码，并复查原文 GPT 出现位置；未找到能将具体 LLM 接入该本地流程的作者实现或接口说明。正文另称尝试 ChatGPT、DeepSeek，表10也将二者与本地系统分别列行，支持其为另列比较对象。它们的实际工具、纠错和决策分工仍不足以核定，不能移植为本地系统的 LLM 证据。
按内部量规第4–7及40–46行，B要求模型决定具体安排，C要求模型调用构造工具或选择策略参数；自动修改优化模型、程序或离线生成规则不能自动满足这些条件。因此标题中的 GenAI 不足以建立本项目 B/C 归属。HTML、PDF及快照来自同一论文，不能计作多份独立研究；全部实验表现仅属作者报告，本次未运行或复现系统，也未推断本厂效果。

**反向尝试：** generative artificial intelligence job scheduling MATLAB ChatGPT DeepSeek；natural language scheduling ETFN MATLAB large language model code generation；"GenAI" "ETFN" "LLM"（域限定：cambridge.org）；"GenAI job scheduling system" "language model"（域限定：cambridge.org）；"ETFN" scheduling LLM MATLAB implementation；GenAI flexible job shop ETFN MATLAB source code（域限定：github.com）；rg -n -i 'frozen_at|purpose|cambridge|ETFN|MATLAB|S0890060425100152|genai|dictionary|formulation|offline_generation|limits|B_project|C_project' inputs/internal-code-baseline.json inputs/route-classification-rubric.json；rg -n -i 'LLM|MATLAB|ChatGPT|DeepSeek|dictionary|replic|复现|2\.81|代码|伪代码|未公开|未知' m0.5_research/evidence/fetch/agents/0004/result.json；原文限定查找：GPT、dictionary、Appendix B、there seemed、DeepSeek、Data availability、repair、replaced

**限定建议：** 保留原命题“论文明确描述的本地系统”及“机制不足以证明LLM调用”的限定；不要扩展为实现绝对未使用LLM，或据此确定ChatGPT/DeepSeek的B/C归属。

**未命中/访问限制：** 反向检索及所读原文未找到本地LLM的具体版本、调用接口或可核验作者源码；这不证明实现不存在或绝对未使用LLM。DOI跳转初次访问失败，随后官方HTML和PDF文本读取成功；PDF第17页截图返回缓存未命中，附录B依据可读文本核对。底层解码、等待、回退及比较对象的实际控制流仍未知，未做复现。

**实际引用：** [方法 Steps 3–1、3–2、4–5；讨论中词典学习与似乎无需LLM的说明；ChatGPT/DeepSeek比较段；结论及数据可用性声明](<https://www.cambridge.org/core/journals/ai-edam/article/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem/508C2D5805370719650FC04B2F514197>)（访问/取证日期：2026-10-12）；[印刷页5–7：词典、MATLAB、LINGO及可行性检查；页10：LLM限定；页13–14：比较对象与表10；页17：附录B Figure B1](<https://www.cambridge.org/core/services/aop-cambridge-core/content/view/508C2D5805370719650FC04B2F514197/S0890060425100152a.pdf/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem.pdf>)（访问/取证日期：2026-10-12）；[route_definitions 第4–7行；limits 第40–46行](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[第19–20行机制及边界转述；第63行明确为作者报告、未复现；第79行源码未知](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/fetch/agents/0004/result.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0010/result.json>)

#### 核验2：supported / high

截至2026-10-12，原限定命题直接受到支持。DOI跳转端点访问失败后，实际读取了对应的Cambridge正文和官方PDF文本；未读取其他核验者结果。[论文](https://doi.org/10.1017/S0890060425100152)
方法Step 3–1描述分词、词干处理、词形还原、关键词位置关系及参数提取；Step 3–2明确从系统词典查找符号和修改要求，插入ETFN。Step 4–5进一步说明：MATLAB程序修改数据库中的默认Lingo模型，另一个MATLAB函数更新默认GA脚本；变化主要涉及适应度与可行性检查。这里描述的是词典映射和程序自动修改，未说明由LLM生成代码或调用排程构造器。Lingo验证模型与GA形成安排的角色应分别披露。
主动反向检查了最可能推翻命题的线索：自动代码生成措辞、综述中的GPT模型，以及讨论中无需预训练GPT的表述；同时执行含LLM、代码生成的Cambridge检索和含ETFN、MATLAB、代码的GitHub限定检索。原文表1将本文推理机制列为“Decision rules”，讨论明确认为查询分析似乎无需运行LLM，结论将ANN/DNN处理关键词列为未来扩展。上述线索未形成反例；定向搜索也未定位可确认属于作者的公开实现，不能据此断言实现不存在。
官方PDF第17页附录B的文字中，query_analysis返回适应度函数和用户约束，随后GA产生种群、交叉、变异并按适应度选择。可行性分支移除违规染色体并加入新染色体，因此合法性筛选及候选替换属于算法贡献；不是语言模型自行保证合法。正文讨论与第14页表10分别列出ChatGPT、DeepSeek及本地系统，支持它们是比较对象而非已披露的内部组件。
反向检查也发现证据边界：第9页表7展示词典缺项导致查询误解及人工补词修正，不能视为持出泛化验证；主案例为六机台、十作业，不能外推全厂规模。表10报告执行时间，不能读成超时率；已读材料未定位模型版本、调用数或token成本。B1虽有代数上限T，内层可行性替换循环未明示重试上限，不能推出壁钟保证。这些均是原文观察和推断，没有亲跑或复现。
本地rg反向核查分类规则第4–7、40–46行：直接B须由模型决定具体安排，C须由模型调用构造器或选择策略参数，离线程序生成及模型 formulation均不自动等于C。因此该论文的机制描述不足以作为本项目LLM直接B或LLM调用构造器C的证据。结论仅限论文披露；query_analysis内部和实际MATLAB控制流未知，HTML附录图片及PDF第17页截图访问失败，附录依据可读文字提取，正文与PDF亦不是两份独立实证。

**反向尝试：** WebSearch："job scheduling" "ETFN" MATLAB "language model"；WebSearch："generative AI" "job scheduling" MATLAB dictionary；WebSearch，限定cambridge.org："job scheduling" "ETFN" MATLAB；WebSearch，限定cambridge.org："customizable" "GenAI" scheduling "large language model"；WebSearch，限定github.com："ETFN" scheduling MATLAB LLM code；WebSearch，限定cambridge.org："GenAI" "job scheduling" "LLM" "code generation"；WebSearch，限定cambridge.org："extended three-field notation" "LLM" "MATLAB"；WebSearch，限定github.com："job scheduling" "ETFN" "code"；原文限定查找：MATLAB、Step 3–1、ChatGPT、Appendix B、large language、Data availability、iterations、timeout；官方PDF限定查找：Figure B1、Table 10.、GPT、cost、time limit、terminate、API、token、version、Table 7.；本地：rg -n -C 3 'B_project|C_project|offline_generation|formulation|工具|解码|过滤|补|limits' inputs/route-classification-rubric.json

**限定建议：** 原命题限定已足够；其限制中的“没有公开实现”宜表述为“截至核查日未定位可供检查的作者公开实现”，以保留搜索覆盖范围的不确定性。

**未命中/访问限制：** 限定检索未定位可确认属于作者的公开MATLAB实现；已读机制说明与伪代码未提供本地系统调用LLM的明确证据。未命中不等于不存在，也不证明未披露函数绝无LLM调用。DOI跳转及HTML图片访问失败，但对应Cambridge正文与官方PDF文字读取成功；附录B页面截图失败，未冒称完成视觉核查或代码复现。

**实际引用：** [Methodology Steps 3–1、3–2、4–5；Discussion关于无需LLM与ChatGPT/DeepSeek比较；Conclusions；Data availability statement](<https://www.cambridge.org/core/journals/ai-edam/article/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem/508C2D5805370719650FC04B2F514197>)（访问/取证日期：2026-10-12）；[实际读取PDF文字：第3页表1；第9页表7；第14页表10；第17页附录B图B1，query_analysis、GA_application及feasibility_check分支；第17页截图失败](<https://www.cambridge.org/core/services/aop-cambridge-core/content/view/508C2D5805370719650FC04B2F514197/S0890060425100152a.pdf/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem.pdf>)（访问/取证日期：2026-10-12）；[route_definitions第4–7行；limits第40–46行；已通过rg反向检查离线生成、formulation及工具决策例外](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0011/result.json>)

#### 核验3：supported / high

截至2026-10-12，原限定命题得到直接支持。DOI入口首次跳转失败，随后实际在线读取了Cambridge官方HTML正文及17页PDF文本。表1（第3页）将本方法的推理机制列为“Decision rules”。Steps 2–3描述分词、词干化、词形归并及关键词组合识别，再从系统词典查取符号和修改项，形成ETFN；Steps 4–5明确由MATLAB程序修改Lingo格式的默认数学规划模型，再由另一个MATLAB函数更新默认GA脚本。附录B图B1中，query_analysis返回适应度函数和用户约束，随后由GA初始化、交叉、变异和选择染色体；违规染色体被删除并补入新染色体。因此具体安排及可行性筛选包含算法决策，不能归为LLM直接排程。[论文原文](https://doi.org/10.1017/S0890060425100152)

主动反向检索采用ETFN、LLM、code、transformer、implementation、MATLAB和github等技术词组合，并检查正文中的LLM、MATLAB、词典与附录锚点。第3页确有涉及免去调度员预处理以训练GPT软件的笼统说法，摘要也称生成定制代码；但这些表述没有交代本地LLM调用机制。更具体的第10页说明，查询分析似乎无需运行基于DNN的LLM；第14页将ANN/DNN处理关键词列为未来方向。第13–14页讨论、图13和表10把ChatGPT、DeepSeek与本地系统分别列出，支持它们是另行尝试的比较对象。检索未发现能推翻原命题的公开实现证据；这不等于实现不存在。PDF截图及官方表图读取出现缓存未命中，相关表格和附录依据官方PDF文本核对。

内部通过rg反向核对分类规则第4–7行的B、C、formulation、offline_generation以及第40–46行的限制。B要求模型承担具体安排，C要求模型调用构造器或选择策略参数；已描述的词典映射、程序改写和GA执行没有证明LLM承担任何一种角色。即便后来证实LLM参与生成程序，也须继续区分离线生成与运行时构造器调用，不能自动算C。这是依据实际决定者作出的分类判断。迁移审计中，领域词典和受约束表达是适用条件，可行性筛选属于工具贡献；作者报告的比较不能自动证明本厂约束覆盖、同条件B/C优劣、持出泛化或完整延迟费用。本次没有检查作者MATLAB实现、运行排程或复现效果，也不据此判断另列ChatGPT/DeepSeek的具体决策归属。

**反向尝试：** "10.1017/S0890060425100152"；"ETFN" MATLAB scheduling "language model"；generative artificial intelligence job scheduling MATLAB dictionary ChatGPT DeepSeek genetic algorithm；"ETFN" "scheduling" "LLM" "code"；"GenAI job scheduling system" transformer implementation；"GenAI job scheduling" MATLAB github；原文find：Step 4.、Step 5.、Appendix B、ChatGPT、DeepSeek、MATLAB、dictionary、no need to run、Supplementary、Data availability statement；rg -n -C 2 'formulation|offline_generation|C_project|B_project|不能仅因使用工具' inputs/route-classification-rubric.json

**限定建议：** 无需缩窄原命题；保留“论文明确描述的本地系统”和“机制描述不足以证明”的限定，不扩展为作者实现绝对未使用LLM。

**未命中/访问限制：** 在上述公开检索及论文方法、附录范围内，未找到本地系统实际调用LLM的可核对实现证据或作者公开代码；未命中不能证明不存在。官方全文可读，部分截图和表图访问失败。

**实际引用：** [Steps 2–5；实验讨论关于无需运行LLM的段落；ChatGPT/DeepSeek比较；结论中的ANN/DNN未来方向](<https://www.cambridge.org/core/journals/ai-edam/article/genai-job-scheduling-system-for-solving-a-flexible-job-shop-scheduling-problem/508C2D5805370719650FC04B2F514197>)（访问/取证日期：2026-10-12）；[第3页表1；第7页MATLAB修改流程；第10页LLM说明；第13–14页图13与表10；第17页附录B图B1](<https://www.cambridge.org/core/services/aop-cambridge-core/content/view/508C2D5805370719650FC04B2F514197/S0890060425100152a.pdf/genai_job_scheduling_system_for_solving_a_flexible_job_shop_scheduling_problem.pdf>)（访问/取证日期：2026-10-12）；[route_definitions第4–7行；limits第40–46行](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0012/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C05 · SeEvo · 原登记 confirmed / 重试后 confirmed

SeEvo v1/v2 论文的测试设置均描述了测试案例上进行一代，而非明确证明冻结规则且零 LLM 调用的持出评估；相关公开仓库当前 test 分支也包含单代规则演化与评价。故不能把这些报告直接当作无 API 调用的冻结规则泛化/派工延迟证据。论文未直接链接该仓库且设置存在差异，代码只能独立说明所读分支，不能用它证明论文每个测试样本的实际调用量。

**原范围限制：**当前仓库 main 分支未取得不可变提交号，且与论文设置不完全一致；测试时搜索的准确调用量及其是否覆盖论文所有报告结果仍未验证。

**采纳范围：**三份核验支持两版论文均描述测试一代规则演化，不能把其报告直接作为冻结规则且零 API 调用的持出泛化或单次派工延迟证据。“test 分支”仅指所读 main 快照中的 mode==test 控制流，不是 Git 分支。该流程加载已有规则后仍演化/评价；论文与仓库的变异、特征等设置有差异，代码未绑定不可变提交或论文版本，不能拼接证明所有论文测试样本的调用量。v2 存在整解耗时及相对 API 费用的作者报告，不得说完全没有成本证据；这些不等于冻结规则单次派工成本，也不证明每次派工都要调用模型。未核读的补充材料和逐样本失败/重试账本仍未知；不将测试时适应一概称为泄漏或无效。

**原命题提供的引用：** [§V-A：训练最多 20 代，测试案例使用一代](<https://arxiv.org/html/2410.22657v1>)（访问/取证日期：2026-10-12）；[§V-A：训练案例替换策略与单代测试设置](<https://arxiv.org/html/2410.22657v2>)（访问/取证日期：2026-10-12）；[seevo.py::evolve/_run_single_iteration，L905-L989；测试分支运行单代并生成、评估规则](<https://github.com/huangjin-collab/LHH_DFJSP_SeEvo>)（访问/取证日期：2026-10-12）。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，原限定命题得到支持。v1 §V-A 明确规定训练最多20代、每轮替换一个训练案例，测试保留交叉和变异概率但降为一代；§III 又说明应用阶段利用训练所得规则和提示，经一次框架迭代生成规则。因此这里的一代是规则种群演化轮次，不能理解为仅执行一次冻结规则，更不能换算为一次API请求。[v1原文](https://arxiv.org/html/2410.22657v1)

v2 §V-A 同样写明测试降为一代；§III 描述使用训练所得最佳规则后，再经过一次自进化框架迭代产生规则；§IV-B 的反思、交叉和变异公式明确包含LLM。其§VI所说动态案例仅使用一个HDR，也不能证明该HDR在接触测试案例前已冻结。[v2原文](https://arxiv.org/html/2410.22657v2)

所读main快照中，seevo.py::init_population 的test路径先加载并评价已有规则；evolve随后无条件调用一次_run_single_iteration。该函数执行种群反思、交叉、评价、自反思、自进化及再次评价；相关函数调用multi_chat_completion，update_iter按当前目标值保留最佳规则。值得纠正的是：注释称自进化仅训练执行，但实际条件位于自进化之后，仅挡住长期反思和变异。故测试路径确实包含规则生成和选择，而非只有加载评价。[代码](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/seevo.py) API封装最终调用chat.completions.create；这证明可达调用路径，不证明实际成功次数、重试量或论文逐样本调用量。[封装](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/utils/utils.py)

反向尝试包括公开检索冻结规则、无LLM测试，并在两版正文检索frozen、fixed、no LLM、API及仓库名称，同时检查加载规则分支。未找到明确冻结且禁用LLM的持出协议；未命中不能证明不存在。运行时归属也须分开：规则程序算分，环境argmin选作业，按名义时长选机器并推进时间，属于生成规则/程序路线，不能自动归为本项目B或C。[环境代码](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/problems/jsp_constructive/Real_Time_FJSP.py)

两版已读正文未直接链接该仓库；论文称测试保留变异设置，而此代码测试跳过变异，足以限制版本对应推断。提交API与历史页均访问失败，未取得不可变提交号。上述材料是作者报告和只读快照，不是本次复现；只能支持不足以证明冻结规则零调用泛化或现场派工延迟，不能据此断言全部结果泄漏、无效或本厂有效。

**反向尝试：** WebFetch：https://arxiv.org/html/2410.22657v1；重点读取§III、§IV、§V-A、§VI；WebFetch：https://arxiv.org/html/2410.22657v2；重点读取§III、§IV-A/B、§V-A、§V-C、§VI；WebSearch：SeEvo heuristic scheduling test frozen rules LLM calls single generation inference；WebSearch：SeEvo scheduling frozen heuristic no LLM testing pretrained single generation；限定arxiv.org、github.com；WebFind：两版正文中的frozen、fixed、no LLM、API、code、github、LHH_DFJSP；另查online application、single iteration及generations；WebFetch：https://github.com/huangjin-collab/LHH_DFJSP_SeEvo；读取README测试流程和文件入口；WebFetch：仓库main的seevo.py；核查init_population、evaluate_population、update_iter、反思与生成函数、_run_single_iteration、evolve；WebFetch：仓库main的main.py、utils/utils.py、problems/jsp_constructive/eval.py；核查入口、API封装及评价路径；WebFetch：仓库main的problems/jsp_constructive/Real_Time_FJSP.py、prompts/jsp_constructive/func_signature.txt；核查规则输出、机器选择与输入签名；WebFetch：https://api.github.com/repos/huangjin-collab/LHH_DFJSP_SeEvo/commits/main；返回Internal Error；WebFetch：https://github.com/huangjin-collab/LHH_DFJSP_SeEvo/commits/main/；返回Internal Error；本地只读：inputs/internal-allowlist.json、inputs/route-classification-rubric.json、inputs/internal-code-baseline.json及本命题指定的0005/result.json；未读取其他核验者结果，未执行排程或修改文件

**限定建议：** 将“test分支”明确标注为“所读main快照中的mode==test控制分支”，避免误解为Git分支；继续保留论文报告与代码路径不能拼接证明逐样本调用量的限定。

**未命中/访问限制：** 未在实际读取的两版正文及所读测试控制流中找到明确冻结规则且零LLM调用的持出评估协议；这不是不存在证明。提交API和历史页访问失败，当前main的不可变版本与论文实验对应关系未验证；补充材料未取得并核读，实际调用量及现场派工延迟未复现。

**实际引用：** [§III应用阶段单次框架迭代；§IV Algorithm 1与反思/交叉/变异；§V-A测试降为一代；§VI动态案例单一HDR](<https://arxiv.org/html/2410.22657v1>)（访问/取证日期：2026-10-12）；[§III应用阶段再次自进化；§IV-B公式(2)—(7)；§V-A测试一代；§V-C生成耗时；§VI单一HDR与外部API限制](<https://arxiv.org/html/2410.22657v2>)（访问/取证日期：2026-10-12）；[init_population L126—L165；update_iter L397—L437；模型调用 L653—L692、L811—L859；_run_single_iteration/evolve L905—L989。main可变快照，未取得提交号](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/seevo.py>)（访问/取证日期：2026-10-12）；[multi_chat_completion→chat_completion→client.chat.completions.create；异常重试循环。网页文本合并为长行，按函数定位](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/utils/utils.py>)（访问/取证日期：2026-10-12）；[RealTimeFJSPDual.step L192—L214：规则评分、argmin选作业、最小名义时长选机器；_forward L219起负责时间推进](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/problems/jsp_constructive/Real_Time_FJSP.py>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0013/result.json>)

#### 核验2：supported / medium

截至2026-10-12，原限定命题受支持。两版§V-A均说训练使用20个随机案例、每轮替换一个，测试仍保留交叉和变异概率，只将代数降至一：[v1](https://arxiv.org/html/2410.22657v1)、[v2](https://arxiv.org/html/2410.22657v2)。结合§III在线阶段及§IV反思、交叉、变异的定义，单代指一次规则演化流程，不能解释成仅加载规则、一次派工或一个API请求。论文的个体是指导工件选择的代码片段，并非完整排程；应按规则生成与适配路线理解，不能据名称自动归入本项目B或C。
反向检索在arXiv/GitHub限定查找SeEvo与frozen、without LLM、test generation，并查两版正文的冻结说明。最强相反线索是§III应用训练所得最佳规则，以及代码初始化确实加载旧规则；但两版同段又写在线阶段进行一次自演化，未形成明确的冻结、零LLM持出协议。未命中只限本次检索。
源码反向追踪发现，[seevo.py](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/seevo.py)初始化加载并评价规则后，evolve的test条件仍调用单轮演化。工具文本L931–953无条件执行反思、交叉、自演化及两轮评价；L955的train条件仅覆盖长期反思与变异，注释称自演化仅训练与实际条件不符。[utils.py](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/utils/utils.py)的聊天辅助函数实际调用模型接口并有重试；[main.py](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/main.py)先调用evolve，再写出最佳规则作val验证，不能由后者推导整个测试零调用。评价超时会标无效，全无效或选不到父代会抛错，实际发生率未复现。程序评价的超时阈值也不能直接视作整个模型调用流程的延迟上限，网络等待和失败重试仍须独立计量。
v2已报告100×20案例上三个模型40、42、122秒及相对API费用，因此不能称没有时间或成本证据；但这是生成整解的报告，未给冻结规则单次派工延迟、逐样本调用及重试账本。两版正文未见指向该仓库的项目链接，且论文测试保留变异、所读代码却跳过变异。代码为可变main的检索快照，未取得提交号，不能证明当日实时HEAD或论文全部结果的实际调用量；补充材料未核实，也未运行实验。规则最终能够独立执行的可能性，与报告中的测试是否继续适配，是两个不同问题；需要冻结规则、断开模型接口的独立持出评估才能直接回答前者。本结论支持证据用途限制，不推出全部结果泄漏、无效或每次派工都调用API。

**反向尝试：** SeEvo job shop scheduling frozen heuristics test no LLM calls single generation；SeEvo job shop scheduling inference time offline training online application；SeEvo scheduling "frozen" "test"；SeEvo scheduling "no LLM" OR "without LLM" OR "inference"；"SeEvo" scheduling "frozen"；限定arxiv.org、github.com；"SeEvo" scheduling "without" "LLM"；限定arxiv.org、github.com；"SeEvo" scheduling "test" "generation"；限定arxiv.org、github.com；两版论文正文查找：single、generations、frozen、github、seconds、cost、Supplementary；公开seevo.py控制流反查：init_population、evolve、_run_single_iteration、multi_chat_completion、timeout；公开main.py与utils/utils.py追踪：测试入口是否绕过evolve；聊天辅助函数是否调用模型接口

**限定建议：** 将“test分支”明确标为“所读main快照中mode==test的控制流”。保持“不足以直接证明零调用冻结泛化或派工延迟”的限定；实际调用量须另有论文对应版本、调用账本和冻结评估协议支持。

**未命中/访问限制：** 本次两版正文读取和限定反向检索未找到明确冻结规则且测试零LLM调用的持出协议。这不证明其他材料中不存在该协议。补充材料、逐样本调用账本、论文与仓库的精确对应关系及不可变提交号均未核实。

**实际引用：** [§III在线应用阶段；§IV个体编码与演化算子；§V-A单代测试设置](<https://arxiv.org/html/2410.22657v1>)（访问/取证日期：2026-10-12）；[§III单次自演化；§V-A测试保留交叉和变异概率；§V-C的100×20案例生成时间及相对API费用](<https://arxiv.org/html/2410.22657v2>)（访问/取证日期：2026-10-12）；[init_population；_run_single_iteration/evolve，工具文本L905–989；反思与生成函数L628–693、L777–867；超时处理L307–316](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/seevo.py>)（访问/取证日期：2026-10-12）；[multi_chat_completion→chat_completion→client.chat.completions.create；异常重试循环](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/utils/utils.py>)（访问/取证日期：2026-10-12）；[main：初始化客户端和算法，调用algorithm.evolve，再写出最佳规则并调用val验证](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/main/main.py>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0014/result.json>)

#### 核验3：supported / medium

截至2026-10-12，原限定命题受到支持。[v1论文](https://arxiv.org/html/2410.22657v1)§V-A明确写训练最多20代、每轮替换一个训练案例，测试保留交叉和变异概率，仅把演化代数降为一代；§III也描述利用训练所得规则与提示，经一次框架迭代生成规则。[v2论文](https://arxiv.org/html/2410.22657v2)§V-A保留同样的单代测试设置，§IV-B公式明确由LLM完成反思、交叉和规则改进。因此，单代指种群演化轮次，不能解释成一次固定规则执行，也不能等同一次API调用。v2§V-C还报告100工件、20机器测试集上的40、42、122秒生成时间及相对API费用；这是作者报告，不能转换成冻结规则每次派工的延迟。
反向核查实际搜索了冻结测试、预训练规则及无需额外LLM等技术词，并检索两版正文的frozen、pre-trained和github。最强限定证据是v2§III称在线阶段利用训练所得最佳规则，以及[README](https://github.com/huangjin-collab/LHH_DFJSP_SeEvo)称测试预训练规则；但前者紧接着描述一次自演化迭代，后者Testing Mode明确列出加载规则后在测试集进行一次演化，均未构成冻结零调用的反例。
[实际读取的main代码快照](https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/refs/heads/main/seevo.py)中，init_population的test条件分支先加载并评价旧规则（L126—165），这一步本身未见LLM生成；但evolve随后调用_run_single_iteration（L980—983），执行反思、交叉、评价以及个体自演化（L931—953），相应方法调用multi_chat_completion。个体自演化实际位于train判断之外，与注释不一致；长期反思和变异才受train判断限制。这里test指main内的运行条件分支，并非已确认的Git分支。
代码因此独立支持所读分支含规则生成与评价，却不能证明论文所有测试样本的调用量。论文测试保留变异概率，而代码test路径跳过变异，设置确有差异；两版HTML正文检索未见目标仓库直接链接。提交API及历史页访问失败，未取得不可变提交号；代码是工具返回的缓存快照，即时状态仍未知。v2 PDF超时，补充材料未读取，未复现。该工作按实际决定者属于规则程序生成路线：程序与环境形成具体派工，不能自动归为本厂B或C。现有比较也不足以提供冻结零调用对照、逐决策费用分母或本厂效果；这些限制不意味着全部结果泄漏或无效。

**反向尝试：** WebFetch：https://arxiv.org/html/2410.22657v1；WebFetch：https://arxiv.org/html/2410.22657v2；WebFetch：https://github.com/huangjin-collab/LHH_DFJSP_SeEvo；WebSearch：SeEvo dispatching rules frozen testing single generation LLM calls；WebSearch：SeEvo job shop scheduling testing pre-trained rules no additional LLM；正文反向检索：两版论文的frozen、pre-trained、github；v2的training、Supplementary；代码路径核查：seevo.py的init_population、multi_chat_completion、_run_single_iteration、evolve及test/train条件；main.py的evolve入口；WebFetch：https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/refs/heads/main/seevo.py；不可变版本尝试：https://api.github.com/repos/huangjin-collab/LHH_DFJSP_SeEvo/commits/main；https://github.com/huangjin-collab/LHH_DFJSP_SeEvo/commits/main/seevo.py；补充来源尝试：https://arxiv.org/abs/2410.22657v2；https://arxiv.org/pdf/2410.22657v2；本地只读：读取指定allowlist、分类rubric与代码基线清单；检索清单未发现SeEvo版本条目

**限定建议：** 原命题的保守结论可保留；引用时把“当前test分支”明确写为“此次读取的main快照内mode=test条件分支”，避免暗示存在名为test的Git分支或已确认即时仓库状态。

**未命中/访问限制：** 已读正文和所读代码未找到明确冻结规则且测试期零LLM调用的评估协议；未命中不代表不存在。两版HTML正文未检出该仓库直接链接。提交API与历史页返回访问错误，v2 PDF超时，补充材料未读取；论文逐样本实际调用数、tokens、费用统计分母及代码与论文完整对应关系仍未验证。

**实际引用：** [§III，L135—141；§IV及Algorithm 1；§V-A，L220：测试保留交叉、变异概率并降为一代](<https://arxiv.org/html/2410.22657v1>)（访问/取证日期：2026-10-12）；[§III，L116—117；§IV-B公式(2)—(7)；§V-A，L195；§V-C，L272：测试生成时间与相对API费用](<https://arxiv.org/html/2410.22657v2>)（访问/取证日期：2026-10-12）；[README：Key Features，L239；Testing Mode，L305—336；配置示例L404；Citation，L605—618](<https://github.com/huangjin-collab/LHH_DFJSP_SeEvo>)（访问/取证日期：2026-10-12）；[init_population L126—165；LLM方法调用L654—656、L690—692、L812—814、L858—860；_run_single_iteration/evolve L905—989。动态main缓存快照，无提交号](<https://raw.githubusercontent.com/huangjin-collab/LHH_DFJSP_SeEvo/refs/heads/main/seevo.py>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0015/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C06 · Evolution of Heuristics (EoH) · 原登记 refuted / 重试后 refuted

EoH 论文 FSSP 的模型产物是用于 GLS 的启发式扰动规则/程序，具体排程序列由算法搜索形成，属于离线生成启发式的研究路线，不能直接视为在线逐项排程 B 或本项目运行时 C。论文摘要所称 2,000 次 LLM 查询属于装箱结果，不应作为 FSSP 排程的实际生成成本。当前仓库具体 NEH/swap/insert 实现与 2024 论文实验提交的对应关系未确认。

**原范围限制：**论文未提供可核验的 2024 实验提交版本；代码控制流证据来自后续 main 快照。若某项目把模型本身放入在线决策环并让它直接选具体动作，结论不适用。

**采纳范围：**原阶段因出处位置错误得到两份反对、一份超时，原记录保留；补充重试再得反对，三角色最新有效判断均反对；保留 refuted，不改写原命题后伪称确认。“2,000 次查询”实际在 v3 §4.2 在线装箱结果段，不在摘要，也不能移作 FSSP 成本。两份核验支持的机制是：模型生成 GLS 扰动规则/程序，算法搜索形成具体排程序列；这是独立的规则生成研究路线，不自动归入在线 B 或本项目 C。采纳此机制说明与更正后的成本归属，明确其为核验后的收窄/校正而非原命题三票确认。FSSP 实际 LLM 总调用数未知，种群×代数不能替代账单；当前 main 的 NEH、swap/insert、截断与失败适应度为静态代码证据，论文提交及当前默认值与论文配置的对应关系未确认。 补充核验还提出当前 main 对小数工时的静态反例推演；这未经执行，且该输入是否属于论文/实现约定的数据域未核验，不当作论文结果无效或已复现生产缺陷。

**原命题提供的引用：** [§4.1、§4.2、Appendix D.2](<https://arxiv.org/html/2401.02051v3>)（访问/取证日期：2026-10-12）；[main 快照 prob.py 936–1046、1048–1149](<https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[route_definitions 与 ownership_fields](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=0；refuted=2；abstained=1。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：refuted / high

截至2026-10-12，原命题存在明确的来源归属错误，因此不能整体判 supported：“论文摘要所称2,000”与指定v3原文不符。实际读取的HTML摘要和PDF第1页均未出现该数字；2,000位于§4.2在线装箱结果段，PDF第6页也明确如此。因此，数字属于装箱作者报告、不能转作FSSP生成成本的判断成立，但“摘要所称”的表述被原源直接推翻。[论文v3](https://arxiv.org/html/2401.02051v3)、[v3 PDF](https://arxiv.org/pdf/2401.02051v3)。

路线判断有直接支持。§3.3的模型产物是启发式描述和Python函数；§4.1规定FSSP函数返回更新后的时间矩阵及扰动作业优先信息。Appendix C.1说明GLS交替执行局部搜索和扰动；D.2采用swap、relocate，并展示返回新矩阵与扰动作业的函数。生成程序虽能选择扰动对象，最终排程序列仍由搜索形成。结合本地rubric的offline_generation定义，应归入离线生成启发式路线，不能自动归为在线B或本项目运行时C。

实际在线读取的[main代码](https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py)进一步披露了算法贡献：neh枚举插入位置并按makespan选初始序列；local_search及local_search_perturb枚举swap/insert并接受改进；gls调用生成函数取得矩阵和作业列表，而非调用LLM选择下一具体排程动作。宿主把作业列表转为整数、超过5项时截断、不足2项或异常时返回1E10失败适应度，并每50轮恢复最佳序列。这些候选限制、失败处理和回退不能归功于模型；makespan按既定机台顺序计算完工时间，未见LLM决定批次或等待的接口。原锚点936–1149对应GitHub网页抽取行，不能当作Python文件源行号。

反向检索实际查询了FSSP的LLM查询数及2024提交映射，并以rg检索允许的本地清单。未找到可核验的FSSP实际调用总量；20代、10个体和1,000次局部搜索上限不能换算实际账单。[v0.1发布页](https://github.com/FeiLiu36/EoH/releases/tag/v0.1)只把4b2338f称为原版本，不能证明它就是2024实验提交；文件历史页及GitHub API访问失败。main含2026版权及3实例、30秒默认值，论文报告64实例、60秒，默认值差异也不能单独证明实验配置。版本对应关系仍未知，未命中不代表不存在。此次只做原文与静态代码审计，未复现作者实验；论文、代码和发布说明也不是三份独立效果证据。

**反向尝试：** 公开反向检索："Evolution of Heuristics" "FSSP" "queries"；公开限定检索：site:github.com/FeiLiu36/EoH "fssp_gls_numba" "2024" "commit"；公开反向检索："2401.02051" "2000" "scheduling"；公开限定检索：site:github.com/FeiLiu36/EoH "FSSP" "LLM queries"；公开限定检索：site:github.com/FeiLiu36/EoH "2024" "commit" "fssp"；公开限定检索：site:arxiv.org "2401.02051" "2,000" "Abstract"；WebFetch：读取arXiv v3 HTML、PDF、v1/v2/v3摘要及PMLR官方摘要；查找D.2、2,000、Algorithm 1、github并读取Appendix C.1；WebFetch：读取作者仓库main prob.py及raw内容、v0.1发布页；尝试文件提交历史、v0.1目录和公开GitHub提交/tag API；本地反向检索：rg -n -i 'EoH|fssp|snapshot|commit|route_definitions|ownership_fields|offline_generation|B_project|C_project' inputs/internal-code-baseline.json inputs/internal-allowlist.json inputs/route-classification-rubric.json；本地限定检索：rg -n 'EoH|fssp_gls_numba|2401\.02051|4b2338f' inputs/internal-code-baseline.json inputs/internal-allowlist.json inputs/route-classification-rubric.json；无匹配，退出码1

**限定建议：** 将“论文摘要所称2,000”更正为“v3 §4.2在线装箱结果段报告2,000”；保留离线生成路线判断，并继续将FSSP实际调用成本、main与2024实验提交的对应关系标为未知。

**未命中/访问限制：** 限定检索及允许清单的rg未找到FSSP实际LLM调用总量或2024论文实验提交的唯一映射。GitHub文件历史页返回Cache miss，公开提交/tag API不可访问；这些失败不证明记录不存在。此次未执行或复现排程。

**实际引用：** [Abstract；§3.3；§4.1 Implementation details；§4.2 Online bin packing；Appendix C.1、D.2](<https://arxiv.org/html/2401.02051v3>)（访问/取证日期：2026-10-12）；[第1页Abstract无2,000；第6页§4.2 Online bin packing报告2,000 LLM queries](<https://arxiv.org/pdf/2401.02051v3>)（访问/取证日期：2026-10-12）；[在线读取main，未固定SHA；makespan、local_search、local_search_perturb、neh、gls、FSSPGLS.template_program及evaluate_program；936–1149为网页抽取行](<https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[发布页指向4b2338f并称其为原版本；未说明2024论文实验提交对应关系](<https://github.com/FeiLiu36/EoH/releases/tag/v0.1>)（访问/取证日期：2026-10-12）；[route_definitions：B_project、C_project、offline_generation；ownership_fields；limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0016/result.json>)

核验2：失败或无有效结果，保留为弃权。

原因：agent timeout after 600000 ms

[失败会话的原始事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0017/events.jsonl>)

#### 核验3：refuted / high

截至2026-10-12，原命题整体判为refuted，错误集中在“论文摘要所称2,000”的出处归因。指定v3的HTML、PDF及摘要页均未在摘要写出该数字；摘要只将低查询预算的优势归于装箱。2,000明确出现在§4.2装箱结果段。因此，“属于装箱、不能作为FSSP实耗”受支持，但不能更正出处后再对原句投supported。[v3摘要](https://arxiv.org/abs/2401.02051v3)、[论文正文](https://arxiv.org/html/2401.02051v3)。

方法归属部分受支持：§4.1及D.2说明模型演化的是修改处理时间矩阵、选择扰动作业的程序；附录函数返回矩阵和作业集合，GLS用交换、移位算子形成序列。程序运行时选择扰动作业，不代表模型在线决定具体排程。本地rg复核rubric第4—6、14—24行，按项目定义属于独立的离线生成路线，不能自动计入B或运行时C；若模型被置入在线具体动作决策环，应重新分类。

此次WebFetch返回的main缓存代码共246行，头部标2026版权，不能沿用指定快照936—1149行的锚点。makespan递推机台完工时间，NEH选择插入位置，两个局部搜索函数决定交换和插入；gls调用生成规则后将扰动作业截至最多5个，每50轮回到最好序列，异常或扰动作业不足两个返回惩罚值。这些算法选择、截断及失败处理都必须披露，不能全部归功于模型。[公开代码快照](https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/prob.py)。

反向尝试包括限定检索FSSP与LLM查询、2000与摘要、作者仓库提交，并核对摘要版本；未取得FSSP实际调用总量、token费用或2024实验提交绑定。GitHub该文件提交历史访问返回Cache miss。未命中不证明不存在，也不以种群和代数换算实际账单。

迁移证据限于流水车间和makespan。D.3提供同框架人工扰动ILS2对照及Taillard测试，§4.3组件消融在装箱任务上，不能直接证明本厂再入、可选机、组批和等待约束下的B/C优劣。每实例60秒是算法搜索上限，不是模型在线延迟或实际费用；本厂持出泛化及失败分母未验证。论文、README与同仓代码属于同一研究来源，以上为作者报告和静态阅读，没有亲跑复现。

**反向尝试：** "Evolution of Heuristics" "flow shop" "2000"；"FeiLiu36/EoH" FSSP "2024" commit；site:github.com/FeiLiu36/EoH "fssp_gls_numba" "commit"；site:arxiv.org/abs/2401.02051 "2000" "bin packing"；"Evolution of Heuristics" "2000" "abstract"；site:arxiv.org/html/2401.02051v3 "FSSP" "LLM queries"；本地rg：B_project|C_project|offline_generation|ownership_fields|顺序|等待|修复|候选；限定inputs/route-classification-rubric.json；本地rg：eoh|fssp|source|snapshot|github|commit；限定inputs/internal-code-baseline.json；WebFetch：指定v3正文、v3 PDF及v1/v2/v3摘要页；WebFetch：指定GitHub文件、公开raw文件及该文件提交历史；提交历史访问失败

**限定建议：** 将“论文摘要所称2,000”更正为“v3论文§4.2装箱结果段报告2,000次查询”。其余结论限定于论文FSSP的离线生成扰动程序路线及本次未固定提交SHA的公开代码快照；FSSP实际生成成本和2024实验版本继续保留未知。

**未命中/访问限制：** 未取得FSSP实际LLM调用总量、token及费用分母，也未确认本次main代码与2024论文实验提交的对应关系；文件提交历史WebFetch失败。检索未命中不等于相关材料不存在。

**实际引用：** [摘要；§4.1实现细节；§4.2装箱结果；§4.3；Appendix D.2与D.3](<https://arxiv.org/html/2401.02051v3>)（访问/取证日期：2026-10-12）；[Abstract，第16—18行；摘要未出现2,000](<https://arxiv.org/abs/2401.02051v3>)（访问/取证日期：2026-10-12）；[本次返回246行的main缓存文本；makespan、local_search、local_search_perturb、neh、gls、FSSPGLS.evaluate_program；第41—245行](<https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[route_definitions第4—7行；ownership_fields第14—24行；comparison_required与limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0018/result.json>)

**重试后登记：** refuted；{'supported': 0, 'refuted': 3, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

#### 补充重试 R2-C06/v2/retry1

[原超时事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0017/events.jsonl>)；[本次重试记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-timeouts/agents/0004/result.json>)

refuted / high

截至2026-10-12，原句整体判为 refuted，反证针对“论文摘要所称2,000次”的出处；离线生成路线判断、不得把装箱查询数当作FSSP实际成本，以及2024实验提交对应关系未确认，均得到支持。指定[v3原文](https://arxiv.org/html/2401.02051v3)摘要只称装箱启发式使用较低查询预算，没有2,000这个数字；[正式发表版摘要](https://proceedings.mlr.press/v235/liu24bs.html)同样没有。2,000明确出现在正文§4.2的在线装箱结果段。因此不能先把“摘要”改成“正文”再支持原句。

分类方面，§4.1与D.2说明，LLM产物是更新加工时间矩阵、选择扰动作业的启发式程序，GLS通过swap与relocate形成顺序。D.2程序确实选择具体扰动作业，这是需要披露的决定贡献；但执行这些选择的是离线生成后运行的程序，不能据此认定在线LLM正在逐项安排生产。已读取本地分类规则，其offline_generation定义支持作为第三条路线；若另有部署把模型接入在线动作环，应另行审查，原命题已有这一条件。

实际读取的[作者源码](https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/prob.py)提供进一步限定：evaluate_program把生成的callable传入gls；NEH构造初始顺序，local_search及local_search_perturb比较候选makespan并接受移动。生成程序返回加工矩阵和作业列表；gls将编号转为整数、超过五个时截断，少于两个或发生异常时返回1E10。候选限制、失败处理及具体顺序形成均有框架贡献，不能只按论文标题归为B，也不能把返回惩罚值当作模型自行保证合法。

反向源码检查还发现合法性缺口：sum_and_order以max_time=1选作业；若两个作业各机器加工时间分别为[0.1,0.1]和[0.2,0.2]，两轮均选编号0，NEH初始序列重复作业。这是静态分支推演，未执行，不能冒充复现结果；原命题没有承诺任意输入合法，因此该例不推翻路线分类。

规模、超时和成本证据仍有限：论文设置包含64个评估实例、每实例最多1,000轮及60秒，这些是作者实验设置，不能换算成实际调用账单。当前读取的是可变main的网页缓存，文件标注2026，默认评估为3实例、30秒；未固定commit，也未建立与2024实验提交的映射。针对FSSP查询、失败、在线决策及超时的限定检索未取得可核验的调用流水、重试数、tokens或费用；未命中不证明不存在。论文与同项目代码不是独立实证，本次没有运行测试、模型或排程。

**反向尝试：** 本地只读：cat inputs/internal-allowlist.json inputs/route-classification-rubric.json；WebFetch：https://arxiv.org/html/2401.02051v3；WebFetch：https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py；WebFetch：https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/prob.py；WebFetch：https://arxiv.org/abs/2401.02051；WebFetch：https://proceedings.mlr.press/v235/liu24bs.html；"Evolution of Heuristics" "flow shop" "LLM queries"；"Evolution of Heuristics" FSSP "online" "2000"；"Evolution of Heuristics" "FSSP" "queries" "failure"；限定arxiv.org、proceedings.mlr.press；"fssp_gls_numba" "update_time" "timeout"；限定github.com；"Evolution of Heuristics" "2,000" abstract；限定arxiv.org、proceedings.mlr.press、openreview.net；"Evolution of Heuristics" "FSSP" "online" "decision"；限定arxiv.org、github.com

**限定建议：** 将“论文摘要所称2,000次”纠正为“论文§4.2在线装箱结果所报2,000次”；保留离线生成路线及在线部署例外，继续将FSSP实际生成成本、2024实验提交映射标为未知。

**未命中/访问限制：** 限定检索未取得FSSP实际LLM调用、重试、tokens及费用记录，也未建立所读main与2024实验提交的对应关系。两项失败/超时限定查询返回空结果；不据此断言记录或对应提交不存在。

**实际引用：** [摘要；§4.1实现细节；§4.2在线装箱结果；Appendix D.2生成程序](<https://arxiv.org/html/2401.02051v3>)（访问/取证日期：2026-10-12）；[正式发表版Abstract，网页解析L13–16](<https://proceedings.mlr.press/v235/liu24bs.html>)（访问/取证日期：2026-10-12）；[makespan、local_search、local_search_perturb、sum_and_order、neh、gls、FSSPGLS.evaluate_program；网页解析L40–245；可变main缓存，未固定提交](<https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[route_definitions.offline_generation、B_project、C_project及ownership_fields；通过cat只读](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

### R2-C07 · Photolithography CP and discrete event simulation；核查日期：2026-10-12。 · 原登记 confirmed / 重试后 confirmed

在该 Nexperia 48 小时仿真、每小时重排及 1.5 小时规划时域下，选择 α 使平方迟交与当前实践匹配时，论文报告 CP1/CP2 的 performance efficiency 分别可提高约 1%/2%；静态确定性分析的对应结果为 6.5%/5.5%，因此该案例中的静态分析高估了动态收益。

**原范围限制：**这是作者在一个 fab 的 DES 中报告的条件性结果；未在真实产线上部署，也不能据此断言其它 fab 或其它 α/重排周期有同样收益。

**采纳范围：**三份核验支持作者在单厂光刻区域 DES 中的条件性报告：48 小时、每小时重排、1.5 小时时域，按平方迟交匹配当前实践时 CP1/CP2 的 performance efficiency 收益约 1%/2%，静态报告约 6.5%/5.5%。保留作者百分比说法，不自行换算百分点，也不声称重读图像复算。须披露 CP2 静态缓冲 0、动态缓冲 1200 秒及动态求解预算 240 秒；不是仅改变随机性的单因素因果实验。动态实验30次重复不能与提取附录中另列的旧校准重复数混用。EDD 在迟交方面的优点不被抹去，当前实践对照下有收益不代表全面支配其他规则。该研究不是 LLM B/C 结果，更不是本厂全厂或现场部署收益；图像访问失败、实现代码未取得、敏感性及净成本收益未验证保留。

**原命题提供的引用：** [§§6.1–6.2，尤其动态收益、α 调参与静态/动态对比](<https://link.springer.com/article/10.1007/s10696-026-09666-5>)（访问/取证日期：2026-10-12）。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / B

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；

#### 核验1：supported / high

截至2026-10-12，原限定命题得到直接支持。实际在线读取了[出版社论文全文](https://link.springer.com/article/10.1007/s10696-026-09666-5)，未把本地提取结果冒称在线原源，也未读取其他核验者结果。§6.2明确规定48小时生产仿真、每小时重排，共48次重排，规划时域h为1.5小时。该节随后直接说明：调节α，使平方迟交表现与当前实践匹配，CP1、CP2的performance efficiency收益分别约为1%、2%，并紧接着回顾静态分析中的6.5%、5.5%。因此，数值、模型对应关系及比较条件均有正文支持。

静态结果的独立定位点是§6.1.2、图9前的解释段；动态结果定位于§6.2、图11前的解释段。这些数值不是从表4的计算时间、求解界或多目标均值误读出来的。本文所说的效率也不等于求解速度。这里保留作者使用的百分比表述，不自行改成百分点，不声称已经根据图表复算。作者报告的静态收益高于动态收益，支持该案例的静态估计偏乐观；不能由此推导所有静态研究都必然高估。

归属方面，§4.1–4.2与§6说明具体机台分配、顺序和时间由IBM CP Optimizer求解约束模型形成。§5.1的Dispatcher还检查机台适配性和辅助资源容量，资源不足时阻止派工；§4.1说明资源冲突可能导致实际等待。因此，这是求解器与仿真执行逻辑共同作用的作者报告，不能归为语言模型直接决定排程的B，也不是本项目模型选择构造器参数的C。论文未提供可供本次审计的完整算法代码，只在数据可用性声明中表示可按请求提供；没有核实代码级修复、失败回退或复现实验。

已执行以静态／动态效率高估及缓冲敏感性为方向的反向、限定检索，并回查§6.1、§6.2和§7。找到的关键限定是：CP2静态比较设缓冲为0，动态实验设为1200秒；后续求解上限为240秒。两组结果不能视为完全相同配置下仅改变随机性的因果实验。§7也承认结果依赖该案例，重排周期、规划时域和缓冲参数尚未开展系统敏感性分析。检索未发现推翻原条件性报告的证据，但未命中不证明反例不存在。

访问限制明确保留：图9、图11的独立放大页面抓取返回Cache miss，未据图像测量收益；对应正文和图注可以读取。§5将本研究界定为避免干扰运行生产的DES评估，故支持的是作者仿真报告，而非本次亲跑、独立复现或真实产线部署收益。

**反向尝试：** WebFetch：https://link.springer.com/article/10.1007/s10696-026-09666-5；WebSearch：photolithography constraint programming dynamic stochastic static performance efficiency squared tardiness overestimate scheduling；WebSearch：photolithography constraint programming static dynamic performance efficiency buffer sensitivity limitations；论文内查找：48；6.5；6.1；CP Optimizer；论文分段读取：§§3.2.2、4.1–4.2、5.1–5.2、6.1–6.2、7及Data availability；WebFetch尝试：https://link.springer.com/article/10.1007/s10696-026-09666-5/figures/9；返回Cache miss；WebFetch尝试：https://link.springer.com/article/10.1007/s10696-026-09666-5/figures/11；返回Cache miss；本地只读：rg --files -g 'AGENTS.md' -g 'internal-allowlist.json' -g 'route-classification-rubric.json' -g 'internal-code-baseline.json'；本地只读：cat inputs/internal-allowlist.json inputs/route-classification-rubric.json inputs/internal-code-baseline.json

**限定建议：** 原命题无需改写。引用时继续保留作者DES报告和单一fab的范围，并补充240秒求解上限及CP2静态零缓冲、动态1200秒缓冲的配置差异；不要把百分比自行转换为百分点或解释为单因素因果效应。

**未命中/访问限制：** 核心命题已在在线主来源中直接命中。未取得作者算法实现代码，未独立复现；图9、图11独立放大页抓取失败。限定检索未发现推翻原命题的证据，不据此断言不存在反例。

**实际引用：** [§6.1.2图9前：静态6.5%/5.5%；§6.2图11前：动态1%/2%及静态高估判断；§6.2开头：48小时、每小时重排、1.5小时规划时域；§§4.1–4.2、5.1：求解和执行归属；§7及Data availability：适用范围与代码获取限制](<https://link.springer.com/article/10.1007/s10696-026-09666-5>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0019/result.json>)

#### 核验2：supported / high

核查日期2026-10-12，已在线读取Springer正式论文正文。§6.2明确设定48小时仿真、每小时重排、1.5小时规划时域；图11讨论明确报告，选择α使平方迟交与当前实践匹配时，CP1、CP2的performance efficiency分别提高约1%、2%。§6.1.2报告对应静态收益约6.5%、5.5%，§6.2再次回指这两个数字并讨论静态分析高估潜在收益。因此，原命题的数字、模型对应关系和案例限定均获直接支持。[论文原文](https://link.springer.com/article/10.1007/s10696-026-09666-5)

实际反向检索加入limitations、conflicts、computational cost，并在原文定位EDD、资源冲突及敏感性讨论。找到两项负面证据：§6.2承认EDD的迟交表现优于CP；§4.1给出静态无冲突计划在随机执行时因reticle占用而等待的例子。这些证据限制“全面胜过派工规则”或“静态合法即可无冲突执行”的扩大解释，却没有推翻本命题限定的当前实践基准及α匹配条件。反向尝试未找到足以否定这组条件性报告的证据；未命中也不证明不存在反例。

进一步核对的规模为13台机器、321个初始任务及1371个新增任务；动态CP2缓冲为1200秒，求解预算为240秒，报告30次重复与95%置信区间。实际安排由CP Optimizer求解器决定，不能将此结果归为大模型直接排程的B效果。§7承认重排间隔、规划时域和缓冲参数的系统敏感性分析尚未展开。作者2023年博士论文第5章印刷页106还明确提醒：仿真不能完全复刻现实，实际收益可能变化，额外复杂性与成本需考虑。这是同一研究线的限定说明，不是独立实证。[作者博士论文](https://pure.tue.nl/ws/portalfiles/portal/307935073/20230922_CO_Deenen_hf.pdf)

本次只核查作者报告，没有运行仿真或求解、读取原始工厂数据，也没有独立复现。图11大图打开失败，数字依据可读取的正文，未声称重新读图计算。真实上线执行延迟、超时或不可行后的处理以及净成本收益仍未确认；这些缺口影响部署价值判断，但不否定原限定命题。结论不能外推到其他fab、其他α或其他重排周期。

**反向尝试：** WebFetch：https://link.springer.com/article/10.1007/s10696-026-09666-5；"photolithography" "constraint programming" "performance efficiency" "conflicts" "squared tardiness"；"photolithography" "CP1" "CP2" "static" "dynamic" "1.5"；"photolithography" "constraint programming" "squared tardiness" "limitations"；"photolithography" "CP1" "CP2" "computational cost" "conflicts"；Springer正文find：6.1；6.5；48；limitations；3600；pause；replication；conflict；EDD outperform；computation；sensitivity analysis；WebFetch：https://pure.tue.nl/ws/portalfiles/portal/307935073/20230922_CO_Deenen_hf.pdf；作者博士论文find：does not perfectly replicate；extra complexity；simulation is paused；By choosing

**限定建议：** 原命题已有必要限定，无需改写；引用时可补充240秒求解预算、CP2动态缓冲1200秒，并继续注明这是作者的DES条件性结果。

**未命中/访问限制：** 核心命题的正文证据已找到。图11大图打开返回内部错误；本次未独立复现，真实执行延迟、超时或不可行处理及净成本收益未确认。

**实际引用：** [§6.1.2静态收益；§6.2仿真设定、图10–11讨论与EDD限制；§4.1资源冲突示例；§4.2求解器；§7参数敏感性限制](<https://link.springer.com/article/10.1007/s10696-026-09666-5>)（访问/取证日期：2026-10-12）；[第5章§5.5.2，印刷页106（PDF第117页）：仿真与现实偏差及额外复杂性、成本限定；同一研究线，非独立验证](<https://pure.tue.nl/ws/portalfiles/portal/307935073/20230922_CO_Deenen_hf.pdf>)（访问/取证日期：2026-10-12）

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0020/result.json>)

#### 核验3：supported / high

核查日期2026-10-12。已实际在线读取[Springer原论文](https://link.springer.com/article/10.1007/s10696-026-09666-5)相关正文。§6.1.2、图9附近明确报告：调α使平方迟交与当前实践相等时，CP1/CP2的performance efficiency收益约为6.5%/5.5%；§6.2、图11附近明确给出动态条件下分别约1%/2%，并以此前静态数字说明静态分析可能高估实践收益。§6.2同时确认48小时仿真、每小时重排及1.5小时规划时域。因此原限定命题直接受作者报告支持；百分号沿用论文表述，未自行改成百分点或产量增幅。

实际反向尝试使用通用技术词搜索静态高估、资源冲突与滚动排程延迟，并回查原文限制。§6.2指出EDD在迟交指标上优于CP，原因涉及CP等待下一次重排；这限定了“优于基线”的目标范围，却不推翻匹配平方迟交时的效率收益。§7明确结果依赖该案例，并将重排周期、规划时域和缓冲参数的系统敏感性分析留作后续工作。检索未发现推翻指定数字的原源证据，但未命中不表示反例不存在。

迁移审计发现：动态实验重放实际观测的确定性到达序列；CP2静态分析缓冲为0，动态分析选1200秒。因此，我将静态高估理解为该案例报告结果的比较，不能进一步当成其他设置完全不变、仅切换随机性的因果消融。30次仿真重复和95%置信区间也不能替代跨fab持出验证。迁移到本厂时，仍需保持目标、观察集合、约束、初始状态及计算预算一致，区分参数选择数据与持出测试，不能拿候选研究收益充作本厂效果。

决策归属方面，§§3.2、4及6显示具体机台、顺序和开始时间由CP求解器形成；CP2还分配具体pod，CP1只约束pod可用容量。这里的CP模型是优化模型。按已读项目分类规则，它不能作为大模型直接决策B的证据，也不能因调用求解器便自动归入本项目C，更不是离线生成规则路线。将合法性过滤、资源约束或求解器选择记到模型名下，会混淆实际贡献。

式(6)的PE按理论最快加工时间与可用设备时间计量，不能直接改解释为全厂产量或利润收益。论文采用240秒求解预算，但这不足以证明端到端执行延迟、仿真是否计入求解等待或调用费用。相关问题保留未知。本次仅核查作者公开报告，未运行仿真、求解或复现，且没有把同项目资料当作独立实证。

**反向尝试：** WebFetch：https://link.springer.com/article/10.1007/s10696-026-09666-5；实际在线打开并读取相关章节。；WebSearch：photolithography constraint programming dynamic stochastic static analysis overestimate performance efficiency；WebSearch：photolithography constraint programming buffer conflicts rolling horizon computation delay simulation；原文查找：6.1、6.5、48、1.5、paused、computational time、6.1.2、5.1、6.5%、performance efficiency、prototype、implementation、Solving、Deploying、5.3、validation、out-of-sample、wall-clock、sensitivity、cost。；原文定位读取：行430、485、180、330附近。；本地只读：rg --files确认指定输入与提取路径；cat读取inputs/internal-allowlist.json、inputs/route-classification-rubric.json和inputs/internal-code-baseline.json。完整性清单输出有截断，未作完整逐项核验；未打开提取结果或其他核验者结果。

**限定建议：** 原限定命题可保留；可附注CP2静态与动态缓冲设置不同，结果不构成控制全部其他条件的因果消融，也不作为本厂B/C效果或跨fab收益承诺。

**未命中/访问限制：** 主命题直接证据已找到。原文查找out-of-sample、wall-clock、paused无命中；这不能证明相关机制不存在。跨fab持出泛化、端到端延迟计入方式及费用未核实，本次未复现。

**实际引用：** [§6.1.2、图9：静态6.5%/5.5%；§6.2、图11：48小时、每小时重排、1.5小时规划及动态1%/2%；§§3.2、4：求解与资源决策归属；式(6)：PE分母；§7：案例和敏感性限制。](<https://link.springer.com/article/10.1007/s10696-026-09666-5>)（访问/取证日期：2026-10-12）；[route_definitions、ownership_fields、comparison_required、limits；仅作为项目分类与审计规则，不作为效果证据。](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0021/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C08 · myharness workflow runtime · 原登记 confirmed / 重试后 confirmed

所审阅 CLI/runtime 路径没有跨进程工作流恢复：入口为每次运行创建新 runId 并要求创建新目录，未见读取旧 runtime、还原工作流状态或调用 codex resume 的路径；README 也明示本次运行不支持跨进程恢复/断点续跑。

**原范围限制：**范围仅限本任务授权阅读的入口、runtime、schema、README 与测试文件；不能据此断言 myharness 其他未读模块完全不存在独立恢复功能。Codex CLI 的 session resume 能力也不等于此适配器的 workflow resume。

**采纳范围：**三份核验支持对2026-10-12冻结指纹一致的五个授权文件的静态限定：所读 CLI/runtime 创建新 runId/新目录、重新初始化阶段与调用集合，保存 runtime 不等于读取旧状态恢复；其 backend 新起 ephemeral exec，没有该路径原生跨进程 workflow resume。重连诊断、schema 的 restoreOptional、测试中的模拟 thread_id 与 runtime 断言都不是反例。不能外推整个 myharness、Codex CLI、外层分阶段编排或用户注入脚本均无恢复；也不能用本轮阶段续接证明底层已支持。测试定义和 README 历史 smoke 不当作本轮执行证据；尚未运行恢复实验。

**原命题提供的引用：** [L74-L90; L104-L126](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs>)；[L117-L128](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md>)。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / A

**登记：** supported=3；refuted=0；abstained=0。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，原限定命题受支持。实际读取白名单中的入口、runtime、schema、README与测试源码；五文件的SHA-256和字节数均与指定冻结清单一致。本结论来自本地源码静态核查，不是在线取源或运行复现。
入口codex-workflow.mjs的L35-L62参数表没有恢复选项；L79-L81读取的是工作流脚本、调用参数和模型映射。虽然参数文件能提供JSON输入，入口并未将其解释为旧工作流状态。L86-L90在实际执行路径中生成新的时间加随机标识runId，并创建最终运行目录；最终目录创建未设置recursive，也没有处理目录已存在的分支。L107-L121调用runWorkflow，成功或失败后写出runtime.json，未见读取旧runtime的路径。
runtime的L191-L198重新编译脚本，初始化空调用数组、空待办集合和空阶段；L262从脚本入口执行，L274-L278组装当前运行状态并返回。L80-L101启动新的codex exec子进程，带--ephemeral，没有resume子命令。L175读取的是该次子进程输出的最终消息，随后解析、校验并保存结果，并非加载历史工作流。
实际反向尝试包括：对五文件用rg检索resume、recover、checkpoint、restore、readFile、runId、mkdir等，再以词边界及--resume、--from-run、--checkpoint检索明确恢复入口。后一检索无命中，退出码为1。广义检索存在两类容易误判的命中：schema的L88-L108中restoreOptional只处理结构化结果的可选字段null；runtime的L123-L130记录同次调用内的重连诊断，且仍须满足L169-L174的正常完成条件。两者都没有还原旧阶段、队列或调用状态。
README的L117-L128要求使用尚不存在的新目录，并明确写明“本次运行没有跨进程恢复/断点续跑能力”。测试L33-L64使用模拟Codex子进程，L154-L159检验同次重连；L178-L188及L215-L228读取runtime用于结果断言，未见利用旧状态启动新进程继续工作流的测试。这些是测试源码中的定义，README既往测试通过及smoke记录属于作者报告；本次未运行测试、模型调用或恢复实验。
范围仅限这五个授权文件及匹配的冻结版本。未命中不能证明myharness其他未读模块不存在独立恢复功能，也不能排除外层流程自行利用落盘材料续接。本次没有核查Codex CLI自身的session resume能力，更不能据此认定该适配器已实现workflow resume。

**反向尝试：** rg -n -i -- 'resume|recover|checkpoint|restore|readFile|runId|mkdir|codex.*exec|跨进程|断点|续跑' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs'；rg -n -i -- '\b(resume|recover|checkpoint|restore)\b|--resume|--from-run|--checkpoint' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md' '__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs'

**限定建议：** 无需改写原命题；保留其CLI/runtime路径限定，并将版本范围明确为2026-10-12冻结清单匹配的五个授权文件。

**未命中/访问限制：** 在五个授权文件内未找到读取旧runtime并还原工作流状态、显式恢复入口或调用codex resume的实现。该未命中仅适用于已读文件，不能外推到未读模块；本次未执行恢复实验。

**实际引用：** [L35-L62 参数解析；L74-L90 输入读取、新runId及目录创建；L104-L126 执行与状态写出](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs>)；[L73-L104 子进程参数；L117-L130 重连诊断；L169-L183 输出读取；L191-L198 状态初始化；L261-L278 执行与状态汇总](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs>)；[L117-L128 新目录要求与恢复能力限制；L148-L159 模拟测试说明及作者验证记录](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md>)；[L88-L108 restoreOptional仅处理可选字段](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs>)；[L33-L64 模拟子进程；L132-L159 参数及重连测试；L178-L188、L215-L228 runtime结果断言](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0022/result.json>)

#### 核验2：supported / high

截至2026-10-12，原命题在其明确限定范围内得到支持。实际全文读取了白名单中的入口、runtime、schema、README和测试五文件，重新计算的SHA-256及字节数全部匹配给定冻结清单。这是本地源码审阅与完整性核对，不是在线读取或恢复功能实跑。

入口codex-workflow.mjs的L86-L90用时间戳与随机UUID生成新runId，并对运行目录调用非递归mkdir；L38-L50的参数表没有恢复选项，未知选项直接报错。静态反例尝试是检查指定旧目录能否绕过初始化：该目录仍须经过L90的创建操作，没有读取旧状态或复用目录的分支，按目录创建语义会失败。这一判断来自源码，未实际启动CLI验证。L79-L81的读文件用途分别是工作流正文、参数和模型映射；L108-L121将runtime作为本次执行结果写出，未见反向加载。

runtime的L191-L198每次重新编译工作流，创建信号量、空调用列表、空待处理集合和初始阶段；L262执行脚本，L274-L278在结束时形成runtime，没有旧runtime输入或阶段还原接口。后端L80-L89构造的是带临时会话标志的exec命令，L101启动子进程，未见resume参数或旧session标识；L175的readFile读取的是该调用的最终消息。

真正的反向检索使用rg搜索resume、recover、checkpoint、restore、readFile、restart等词，并追加精确恢复函数与旧runtime读取模式。检索并非全无命中：runtime L125-L130处理重连诊断，schema L90-L108含restoreOptional，测试L183、L212、L226-L227读取runtime.json。逐一追踪后，重连分支只是允许同一子进程出现重连诊断后仍完成有效回合，没有重启工作流或恢复调用队列；restoreOptional只撤销schema适配添加的可选字段空值；测试读取用于检查刚产生的输出。这些候选反例均未推翻命题。

README L117-L128明确要求新取证目录，并明示本次运行没有跨进程恢复或断点续跑能力。测试L145-L168、L215-L228覆盖失败、重连、超时和取消的模拟场景，未见退出后重新启动并加载旧工作流状态的案例；这些测试本次仅阅读，未执行。源码中的超时终止和取消审计也未增加恢复分支，不能据此推算实际重跑成本。

结论仅覆盖上述五文件的适配器原生路径。未命中不是全仓不存在功能的证明；未读模块、自定义工作流、外部落盘续接与Codex自身session恢复均不在本次结论内。跨进程故障后的动态表现仍未复现，README与同项目代码也不作为两份独立运行实证。

**反向尝试：** cat：读取指定的internal-allowlist.json、internal-code-baseline.json和route-classification-rubric.json；完整性清单首次输出截断，随后解析核对五个目标条目。；nl -ba：全文读取白名单中的codex-workflow.mjs、codex-workflow-runtime.mjs、workflow-schema.mjs、codex-workflow.README.md、codex_workflow.test.mjs。；rg -n -i 'resume|recover|checkpoint|restore|readFile|runId|runtime\.json|fresh|existing|EEXIST|retry|spawn|restart|续跑|恢复|断点'：检索上述五文件。；rg -n -i '\bresume\b|\bcheckpoint\b|\brestart\b|rehydrat|loadRuntime|restoreWorkflow|resumeWorkflow|readFile[^\n]*runtime'：检索上述五文件，仅命中测试读取runtime.json。；rg -n 'readFile|JSON\.parse|runId|mkdir\(runDir|new Semaphore|const calls =|const pending =|let currentPhase|await execute|const runtime =|workflowRuntime|runtime\.json|argv.push|spawn\('：追踪入口、runtime和测试的读取、初始化与写出分支。；SHA-256核对：首次python3 here-document命令因只读沙箱无法创建临时文件而未执行；改用python3 -c只读计算后，五文件的哈希及字节数均匹配冻结清单。

**限定建议：** 保留原有限定：结论仅针对这五个授权文件中的适配器原生跨进程工作流恢复，不外推至未读模块、外部续接脚本或Codex自身session恢复。

**未命中/访问限制：** 五个授权文件中未找到适配器加载旧runtime、还原工作流阶段或调用队列、调用codex resume的路径；检索命中的重连、schema字段还原和测试输出读取已逐一核查。此未发现仅限指定文件，不证明未读模块或外部实现不存在恢复功能。

**实际引用：** [L35-L62；L74-L90；L104-L126](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs>)；[createCodexBackend：L73-L104、L117-L184；runWorkflow：L191-L198、L259-L278](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs>)；[restoreOptional：L88-L109](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs>)；[L117-L128；L148-L151](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md>)；[L132-L168；L178-L188；L206-L228；L247-L259](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0023/result.json>)

#### 核验3：supported / high

截至2026-10-12，原命题在其限定范围内得到直接支持。本次实际读取白名单内入口、runtime、schema、README及测试源码；五个文件的SHA-256和字节数均与指定完整性清单一致，属于本地源文件核查，未冒称在线读取，也未读取其他核验者结果。
入口codex-workflow.mjs的L35-L62列出并校验参数，没有恢复入口；L86-L90为工作流执行生成时间加随机UUID的runId，自定义run-dir也必须通过非递归的目录创建，已有目录会导致创建失败。L107-L111创建backend、执行runWorkflow并写入结果和runtime；失败分支L117-L121同样只写出终态记录，没有读入旧runtime的分支。入口L79-L81的读取对象是脚本、参数文件及模型映射；本次仅审查这些读取语句，没有读取其配置内容。
runtime的L191-L198每次重新编译脚本，新建metadata、calls、pending及空阶段状态，L262从脚本函数入口执行，未接收旧调用记录或持久化阶段游标。backend的L80-L89构造exec调用并加入--ephemeral，没有resume子命令或会话恢复标识；L175读取的是本次子进程的最终消息，L274-L278形成的是结束时的统计记录。因此，保存runtime.json本身并不构成读取和还原工作流的路径。README的L117-L128与代码一致，说明run-dir须为新目录，并明确写道“本次运行没有跨进程恢复/断点续跑能力”。
反向核查实际对五个文件执行rg，检索resume、recover、checkpoint、restore、readFile及runtime.json等，再限定搜索恢复选项、状态恢复函数和会话标识，并追踪读取及JSON解析位置。相关命中均逐项检查：runtime L123-L130只是允许同一子进程调用在出现重连诊断后仍以有效完成事件成功结束；schema L88-L109的restoreOptional只是处理结构化结果中适配器添加的可选字段null；测试L56的thread_id是模拟事件。测试中读取runtime.json用于检查本次运行输出，未向下一次运行注入状态，也没有旧目录重启并续接的测试。这些命中未构成跨进程工作流恢复的反例。
本次没有执行测试、CLI调用或恢复实验；README记录的历史测试和smoke属于作者记录，不能写成本次亲跑结果。README、代码和测试来自同一工程，也不作为多份独立实证。结论仅覆盖这五个文件及清单对应版本：其他未读模块、注入脚本或外部编排是否另有恢复机制仍未知；当前调研分阶段落盘续接和Codex session resume均不能据此视为该适配器原生workflow resume。反向未命中不证明整个myharness不存在独立恢复功能。

**反向尝试：** 读取inputs/internal-allowlist.json、inputs/route-classification-rubric.json及inputs/internal-code-baseline.json；rg --files -g AGENTS.md -g '!node_modules' -g '!data' -g '!runs' .；用nl -ba读取五个白名单源文件，并补读runtime L190-L279。；对五个白名单文件执行rg -n -i，模式：resume|recover|checkpoint|restore|readFile|runtime\.json|runId|runDir|codex.*exec|exec.*resume；对五个白名单文件执行rg -n -i，模式：resume|checkpoint|recover(y)?\b|restore(state|workflow|runtime)|--(resume|recover|checkpoint)|session[_-]?id|thread_id；对入口、runtime及schema执行rg -n，模式：readFile|JSON\.parse|compileWorkflow|execute\(args|const (calls|pending|metadata)|currentPhase|runtime\.json；使用python3 -c只读计算五个白名单文件的SHA-256及字节数，与指定完整性清单逐项比较，全部一致。

**限定建议：** 无需改写原命题；继续保留五个授权文件及对应版本的范围限定，不扩展为整个myharness或Codex CLI均无恢复功能。

**未命中/访问限制：** 在五个白名单文件中，未发现读取旧runtime并重建工作流状态、消费checkpoint、复用旧runId或调用codex resume的路径。恢复相关词的命中均已检查，属于重连诊断、schema字段处理或模拟测试；未命中仅适用于所读范围。

**实际引用：** [L35-L62；L74-L90；L104-L126](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs>)；[L73-L89；L117-L130；L169-L184；L191-L198；L259-L278](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs>)；[L117-L128；L148-L159](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md>)；[L88-L109：restoreOptional](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs>)；[L33-L64；L132-L159；L178-L188；L215-L228；L247-L259](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0024/result.json>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

### R2-C09 · Current B/C scheduling chains；截至2026-10-12。本次只读指定工程源码、白名单发现记录和两份已批准摘要；没有运行测试、工厂模拟、求解器或模型，也没有读取原始工厂数据、运行明细或 artifacts。 · 原登记 unverified / 重试后 confirmed

在V15 host实际导入V14 Interaction、其包内依赖哈希匹配且公共状态仍满足锚点/物理校验的条件下，这条B实现把具体lot/operation、机台、批组、每机顺序、开始条件和hold等决定留给模型；组装器与delta compiler显式校验并拒绝非法输入，之后由模型单独选择精确候选并经公共commit。若发现工具在该链上替模型补排程字段、自动选候选或改写模型输出，此结论即被证伪。

**原范围限制：**这是源码控制流的静态结论；本轮没有读取V15 campaign/frozen来源清单、原始模型请求输出或运行日志，不能证明批准报告所述具体运行与当前打开的源码逐哈希对应，也不能以最终合法计划替代原始输出合法率分母。

**采纳范围：**原阶段 unverified（一份支持、两份超时）及失败记录保留。补充重试两角色均返回 supported/medium，按各角色最后有效结果为三份支持、当前登记 confirmed。只采纳原限定的静态控制流：V15 实际导入 V14 Interaction、包内依赖哈希匹配、公共状态满足锚点及物理校验条件下，模型显式给出物理生产任务的 lot/operation、机台、批组、每机顺序、开始条件与 hold，并在较晚独立 apply 中选精确候选 ID/hash。组装器在副本验证后发布，seal 要求所有路径含空数组明确声明，delta 要求旧任务/hold完整处分；不完整或不合法的字段/顺序被拒绝，不自动补排。未改变机台的明确保留任务复制基准顺序，新增或迁移要求受影响机台完整顺序。候选按检查创建次序展示，未发现自动质量择优。plan_from_action 补字段辅助函数在指定链中未命中调用，不推成全工程绝无自动转换。环境的虚拟延迟节点由程序选择组别推进，物理生产执行仍受就绪条件限制，必须披露其贡献。两次重试仅核对当前已读源码及基线/包内哈希，不证明具体 campaign/frozen 历史部署绑定；编译通过不保证全部动态物理可行性，公共提交/执行检查仍必要。本轮没有运行测试或排程，原始模型输出合法率、实际时延费用、跨厂泛化与 B/C 相对效果仍未知。

**原命题提供的引用：** [L141-L166](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py>)；[L65-L90、L434-L510](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py>)；[L118-L270](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py>)。这是提取阶段的原引用；若位置/行号有误，保留其历史并以下方实际核验引用和采纳范围纠正。

**来源：** auto-research / A

**登记：** supported=1；refuted=0；abstained=2。

**对抗方法：** falsification；原始核验的访问失败、未找到项和弃权均保留，详见逐条记录。

#### 核验1：supported / high

截至2026-10-12，实际读取的源码直接支持原命题限定的静态决定归属。V15 host 的 L17-L28 将 frozen 加入导入路径，明确导入 V14 Interaction，并检查运行文件哈希；本轮只核对获准源码，未访问实际 campaign/frozen。当前 host、Interaction、组装器、compiler 等文件的 SHA256 均匹配指定本地基线；Interaction L16-L34 又从自身包目录读取三个依赖，核对硬编码哈希并执行同一份字节，不能拿根目录同名文件替代这条依赖链。
模型实际输出是含 request 的原始 JSON envelope，排程通过明确的 chunk 分次提交。包内 B_delta_assembly L125-L197 只创建容器、复制模型值并验证完整任务、hold 和不可分割的机台顺序；L303-L306 要求所有字段及空数组显式声明，L320-L359 在副本上完成检查后才发布，因此拒绝块不会留下部分安排。
plan_delta L148-L177 根据模型明确选择的保留、取消、替换、新增机械编译：保留任务复制原值，新增或迁移必须声明受影响机台的完整顺序，未显式改变的机台沿用基准顺序。这不是工具重新排序。L225-L253 对过期开始条件、未知或重复 operation、资格不符、批组不兼容及失效 hold 锚点报错，没有自动抬高 not_before 或迁移 hold。compiler 不保证完整物理可行性，L267-L269 明确要求后续公共校验。
工具贡献必须披露：动态 response schema 的 L124-L181 固定上下文、哈希和序号，仅开放已有草稿的适用动作以及已检查候选的 ID/哈希组合；候选集合由成功编译形成，草稿和候选容量满时拒绝，属于协议过滤与合法性检查，并非模型独立保证合法。Interaction L469-L510 要求 seal、check、apply 来自先后独立输出；候选按创建顺序列出，没有质量排序或默认候选，apply 必须精确指认候选及哈希。
host L94-L104 将原始字节严格解析并送入 handle，运输失败停止；L141-L166 要求最后动作明确为 apply，重放原始输出并比较选择摘要，再将所选 compiled plan 交给公共 commit，核对返回摘要，异常结果保留为未知而不重试。
反向实际使用 rg 搜索 setdefault、fallback、repair、排序、候选选择与 _selection 赋值，并回读命中分支；主链中的排序用于页或历史展示，选择赋值来自显式 apply。还命中会补字段的参考转换函数 plan_from_action，但限定检索未发现主链调用它，不能把同文件中存在转换器当作链上反例。未发现足以证伪原命题的自动补排、候选代选或语义改写。结论仍仅是条件成立时的源码控制流支持：没有读取原始模型请求、运行明细或批准报告，没有复现，不能证明某次运行逐哈希对应，也不能从合法最终候选推算原始输出合法率。

**反向尝试：** 读取 inputs/internal-allowlist.json、inputs/route-classification-rubric.json，并解析 inputs/internal-code-baseline.json。；nl -ba B_budget_extension_v15/host.py | sed -n '1,230p'；nl -ba B_candidate_paths_v14/workflow/interaction.py | sed -n '1,90p;417,570p'；nl -ba B_candidate_paths_v14/workflow/B_delta_assembly.py | sed -n '1,365p'；nl -ba plan_delta.py | sed -n '118,271p'；rg -n 'setdefault|fallback|repair|sort\(|sorted\(|\[0\]|\[-1\]|not_before.*=|candidate.*(min|max)|_selection\s*=' B_candidate_paths_v14/workflow/interaction.py B_candidate_paths_v14/workflow/B_delta_assembly.py plan_delta.py B_budget_extension_v15/host.py；rg -n '\b(plan_from_action|construct_plan|constructor|repair|fallback)\b|\bsolve\s*\(' B_budget_extension_v15/host.py B_budget_extension_v15/restore.py B_candidate_paths_v14/workflow/interaction.py B_candidate_paths_v14/workflow/B_delta_assembly.py B_candidate_paths_v14/policy.py B_candidate_paths_v14/prompt_schema.py plan_delta.py B_resume_v1/physical_resume.py B_incremental_v3/controller.py B_incremental_v3/transport.py environment.py；nl -ba B_candidate_paths_v14/prompt_schema.py | sed -n '124,183p'；读取 V15 restore、V14 policy、physical_resume、controller 和 environment 的相关导入、解析、commit、执行及参考转换分支。；使用 python3 -c、pathlib 和 hashlib 只读计算所选允许源码的 SHA256，与 internal-code-baseline.json 对照；未导入或执行工程模块。

**限定建议：** 维持原命题已有的导入、依赖哈希、公共状态校验和静态控制流限定；不得扩展为具体运行已验证、原始输出合法率或本厂效果结论。

**未命中/访问限制：** 主来源均可读取，限定反向检索未发现链上反例；未命中不证明不存在。最初尝试的 stream_environment.py、stream_physical.py 文件名不存在，随后沿真实导入定位 environment.py。一次哈希读取命令因只读环境禁止 here-document 临时文件而失败，改用 python3 -c 后成功。实际运行的 frozen 来源、原始模型输出及物理审计结果仍未知，且未复现。

**实际引用：** [L17-L28、L94-L104、L141-L166](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py>)；[L16-L34、L417-L423、L469-L510、L532-L549](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py>)；[L125-L197、L303-L306、L320-L359](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/B_delta_assembly.py>)；[L91-L115、L148-L177、L225-L253、L267-L269](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py>)；[L29-L40、L103-L123、L124-L181](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/prompt_schema.py>)

[原始核验记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0025/result.json>)

核验2：失败或无有效结果，保留为弃权。

原因：agent timeout after 600000 ms

[失败会话的原始事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0026/events.jsonl>)

核验3：失败或无有效结果，保留为弃权。

原因：agent timeout after 600000 ms

[失败会话的原始事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0027/events.jsonl>)

**重试后登记：** confirmed；{'supported': 3, 'refuted': 0, 'abstained': 0}。按每个角色最后一次有效结果汇总；失败原记录仍保留，模型票数不替代原源。

#### 补充重试 R2-C09/v2/retry1

[原超时事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0026/events.jsonl>)；[本次重试记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-timeouts/agents/0001/result.json>)

supported / medium

截至2026-10-12，原条件性源码命题受支持，本次反向检查未发现指定证伪情形。先读取白名单及分类准则，再沿 V15 host→restore→V14 Interaction→包内组装器→plan_delta 定向读取。host 设置 frozen 导入路径并检查自身位置、运行文件哈希；restore 实例化 V14 Interaction。Interaction 按同目录文件的字节哈希加载三项依赖。使用 Python 标准库只读解析指定完整性清单，仅筛选已打开的10个文件并计算 SHA256，均与基线匹配；三项包内依赖也与代码硬编码哈希一致。这确认的是当前源码与指定基线，实际 campaign/frozen 部署对应仍未知。

组装器从空 delta 开始，只复制模型提交的完整字段并按提交顺序追加数组；创建中间对象容器不生成排程值。seal 要求所有规定路径、包括空数组均显式声明。编译器要求每个待执行基准任务及 hold 有完整保留、取消或替换处分，新增任务必须包含机台、lot、operation、visit 和开始条件。保留任务复制原值；未显式改序时保留原每机顺序，新增或迁移任务则要求受影响机台的完整顺序。这里存在程序展开和约束检查，但未见程序自行选择机台、批组或顺序。

反向检索覆盖补字段、默认值、排序、回退、修复及 selection 赋值。静态候选反例包括缺机台、新增任务却缺完整机序、非冻结任务沿用过期开始条件、hold 锚到已删除任务；相应分支均拒绝，未见自动修补。排序命中主要用于页面、历史反馈和观测索引；候选按成功检查的创建次序展示。环境中的 plan_from_action 确有从状态生成字段的逻辑，但已查调用链没有调用它，不能据此推翻本句，也不能把整个工程概括为绝无自动转换。

检查成功只登记候选。apply 必须在另一次较晚输出中提供精确候选 ID 和完整哈希；host 再验证显式 apply、锚点和逐条原输出重放，然后把选中计划交给公共 commit。公共 commit 复制并校验计划，没有补排程字段的分支。执行器按每机首项和模型给定的开始条件、hold 检查能否启动；物理未就绪会等待，失效或覆盖缺口会停止请求重规划。另有虚拟延迟节点由环境选择组别并推进，须披露为环境贡献；该路径跳过物理生产机台，未改写选中生产计划。

组装器和编译器接受不代表全部动态物理约束已获认证，也不证明模型原始输出合法率。16草稿、32候选、1024次尝试、120000字符提示上限，以及 host 的600秒调用超时配置和停滞阈值，均留下中止与规模成本缺口；结果代码的成本字段为未知。本次没有执行测试、求解、模拟或模型，也未读取运行输出、日志及工厂数据；配置模型标识不能证明实际调用版本，具体部署、实际可行率、质量、耗时和成本均未验证。以上缺口没有推翻原句的限定控制流结论。

**反向尝试：** cat inputs/internal-allowlist.json inputs/route-classification-rubric.json；rg --files：检索白名单源根下 B_candidate_paths_v14 与 B_delta_assembly；再按 (assembly|interaction|delta|session).*\.py$ 筛选，定位实际包内组装器。；rg -n 反向检索：模式 (def _dispatch_with_progress|assembly_layer|compile_plan_delta|setdefault|sorted\(|\.sort\(|fallback|repair|auto|default|_selection\s*=|min\(|max\()；目标为 V14 workflow/interaction.py、V15 host.py。；rg -n 定向检索：函数定义、导入、setdefault、sorted、sort、fallback、repair、auto、default、not_before、machine_orders、keep、hold；目标为包内 B_delta_assembly.py 与 plan_delta.py。；rg -n 反向检索：模式 (plan_from_action|construct|repair|fallback|fill|\.sort\(|sorted\(|setdefault|not_before.*=|candidate.*(min|max)|_selection\s*=)；目标为 V15 host/restore、V14 Interaction、包内组装器、plan_delta、physical_resume。；rg -n：在 environment.py 定位 commit_plan、执行顺序、hold、not_before、修复和排序分支；随后读取对应源码行。；python3 -B -c：只读解析 inputs/internal-code-baseline.json，筛选已打开的10个源码条目，并计算当前文件字节 SHA256 作比较。

**限定建议：** 保留原句的导入、依赖哈希、锚点及物理校验条件和静态范围；具体部署一致性、原始输出合法率、规模表现与成本需另行取证。

**未命中/访问限制：** 主来源已命中；限定反向检索未找到链内自动补排程字段、默认选择候选或修复模型决定的反例，不能推断所有版本均不存在。初次目录发现中 B_delta_assembly 目录不存在，随后定位实际包内 B_delta_assembly.py。完整性清单首次 heredoc 命令因只读环境禁止临时文件而失败，改用 python3 -B -c 完成只读解析和哈希。实际冻结部署与运行对应关系未查，未复现；原超时失败记录未修改。

**实际引用：** [L16-L28、L91-L104、L136-L166、L186-L190](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py>)；[L12-L47、L417-L423、L434-L510、L512-L555](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py>)；[L125-L130、L154-L208、L254-L284、L303-L358](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/B_delta_assembly.py>)；[L91-L115、L118-L177、L196-L270](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py>)；[L72-L92、L94-L170、L199-L278、L343-L355](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/environment.py>)

#### 补充重试 R2-C09/v3/retry1

[原超时事件](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/verify/agents/0027/events.jsonl>)；[本次重试记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-timeouts/agents/0002/result.json>)

supported / medium

截至2026-10-12，原限定命题受本次静态源码审计支持，具体部署实例仍未验证。先读取白名单和分类标准，再沿V15 host→V14 Interaction→同目录B_delta_assembly→plan_delta检查实际导入语句。以只读Python解析指定internal-code-baseline.json，仅筛选当时已打开的11份源码并计算SHA256，全部匹配；Interaction固定的提示、组装、反馈三项包内依赖哈希也匹配。此清单是源码完整性基线，不是运行证据。host把frozen置于导入路径首位并检查来源，但本次没有读取campaign及其frozen清单，不能证明某次部署实际加载了这些文件。
决定归属有执行分支支持：组装器要求全部15条路径，包括空数组，明确声明后才能seal；新增或替换任务必须包含lot、step、visit、operation、machine和not_before，hold也要求完整字段。chunk在副本上验证，全部通过才发布；失败返回拒绝，不补字段。编译器要求每个旧任务及hold具有明确保留、取消或替换处分；保留项复制原值，未明确改变的机台顺序保留旧序，新增或迁移任务要求受影响机台完整顺序。模型提供开始条件与等待声明，实际派工仍受物理就绪条件限制。
候选只在模型单独请求check_assembly后产生；32个候选上限会拒绝新检查，没有淘汰后自动择优。列表按检查创建顺序返回。稍后的独立apply必须给出具体候选ID及完整哈希，并匹配当前锚点。host要求最后动作为apply，重放原始输出验证选择一致，再将该候选编译计划交给公共commit；公共commit复制并保存提交计划，没有重新挑lot、机台或批次。执行器按各机台提交顺序检查首任务；发生过期、路线变化或物理不合法时停止并要求重排。
反向检索覆盖selection赋值、排序、默认值、修复和回退。发现environment中的plan_from_action确实会生成工序、开始条件和等待字段，随后对所列链路文件检索其引用，零命中；不能把这个未见接入的辅助函数当作本链反例。已查到的排序用于哈希、查询元数据或状态表示，编译器的任务重排执行模型明确给出的顺序。未发现链上工具补出新的排程选择、自动选候选或改写模型决策值。
编译校验覆盖身份、资格、批量界限、完整处分、冻结前缀、范围及hold锚点，但不证明完整物理可行性；公共commit和执行时物理检查的贡献必须披露。本次未运行测试、模拟、求解器或模型，未读取运行明细、此前核验结果或报告。部署对应关系、同条件基线与消融、持出泛化、真实执行延迟和费用分母均未核验；最终合法候选或成功commit不能替代完整原始尝试及失败分母，也不能据此推出B优于C或跨厂可迁移。

**反向尝试：** cat inputs/internal-allowlist.json inputs/route-classification-rubric.json；本地nl -ba/sed：针对V15 host、restore，V14 Interaction及包内组装器、提示与反馈模块，plan_delta、physical_resume、environment和policy的必要函数读取源码。；本地rg模式：delta|assemble|compile|select|candidate|commit|fallback|repair|sort|hold|start；范围为V14 workflow/interaction.py。；本地rg模式：def _validate|def _dispatch_with_progress|strict_json|setdefault|sorted\(|sort\(|_selection\s*=|compile_plan_delta|fallback|repair|not_before.*max|policy\.|construct|planner|solver；限定已打开的核心链路源码。；本地rg -n 'plan_from_action'：限定V15 host/restore、V14 workflow/policy、plan_delta、physical_resume、controller、delta_session；退出码1，零命中。；只读python -c：解析指定完整性清单，仅筛选已打开文件计算SHA256；用ast.literal_eval读取Interaction的DEPENDENCIES常量，核对三项包内依赖，未导入或执行工程模块。

**限定建议：** 无需先改写原句再支持；使用结论时保留实际导入、包内依赖哈希及公共状态校验前提，并明确这是静态控制流结论，具体运行归属、物理效果及原始输出合法率仍未知。

**未命中/访问限制：** 所列链路中未检索到plan_from_action引用，定向审计未发现命题指定的反例；未命中不证明未读版本或部署中不存在。一次here-doc因只读沙箱无法创建临时文件失败，随后用python -c完成只读哈希复核。

**实际引用：** [L17-L28、L91-L104、L141-L177：导入、原始输出传递、显式选择重放及公共commit](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py>)；[L12-L34、L395-L405、L417-L510、L512-L578：包内依赖、精确校验、候选检查及独立apply](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py>)；[L15-L22、L125-L197、L269-L361：完整字段、全部路径声明、副本校验及拒绝](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/B_delta_assembly.py>)；[L91-L115、L118-L270：明确处分、完整任务、机台顺序、冻结与hold校验](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py>)；[L94-L170、L172-L248、L343-L355：公共commit、按计划执行及反向核查的字段生成辅助函数](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/environment.py>)

## 原源提取附录

下面保留阅读材料。关键论断表中的每个原命题安排了三次独立核验尝试；实际成功、失败和弃权见登记。其余细节是来源提取或待核线索，不能据此新增未经审查的路线结论。

### S-07 · Q-04 · DynaSchedBench paper（ICML 2026；arXiv:2605.27566 v1）

[全文：§4.2、§5、§7.1–7.3、表3–6及附录C、H、J](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）；[PMLR/ICML 2026元数据、作者与摘要；页面所链全文PDF本次无法读取](<https://proceedings.mlr.press/v306/cao26z.html>)（访问/取证日期：2026-10-12）；[公开仓库 README Quickstart；只读示例展示 legal_actions、advance_if_idle、agent.act 与 env.step 的接口关系](<https://github.com/dsbx7/DynaSchedBench>)（访问/取证日期：2026-10-12）；[route_definitions、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C02

**机制：** 论文研究动态柔性作业车间的在线、逐步调度。仿真器在决策时刻提供状态快照；L1含局部机器状态、可用时间和名义加工时间，L2再加入队列长度、作业松弛度及已发生事件统计，L3再加入瓶颈分数、校准目标等结构先验。模型依据观察与可行动作集合选择下一动作。L1+Tool允许模型调用 inspect_action_details 查看候选动作信息、调用 simulate_action 获取模拟子轨迹的完工时间估计，再由模型作最终选择。按rubric，这属于逐步具体动作选择的B类候选路线；工具用于探查或模拟信息，不等于调用构造器让算法生成完整排程，故不能仅因“Tool”归为C。论文没有充分展开动作对象字段，不能据此断言模型明确决定了哪些lot、机器、批次、开工时刻或等待。

**实际决策边界：** 责任边界是部分可辨的：论文称环境整理观察并过滤可行动作以确保有效性，代理根据状态和可行动作集合决策，仿真轨迹评估器检查优先关系与资源不重叠。因此，模型有逐步动作选择职责，但动作合法性集合由环境形成或过滤；这项过滤贡献应单独披露。尚未查明动作候选是否截断、动作包含哪些决定字段、模型输出解析失败如何处理，以及非法输出会被拒绝、修复还是回退。若项目B要求模型本身明确决定机台/顺序/等待等全部排程选择，则本文只支持“模型在环境给定合法动作集合内逐步选动作”的有限B类比较；不支持把环境过滤后的可行性直接算作模型合法率。作者仓库README的通用示例也有无合法动作时advance_if_idle的分支，但它不是论文LLM实验控制流的独立实证，不能据此补齐论文未报细节。

**实验条件：** LLM评测子集共70个实例：DynaSched-Grid取30个、DynaSched-Sweep取40个；作者称用基于六项驱动指标及相对难度秩的标准化特征做最远点k-center抽样，覆盖全量数据的四分位范围。Grid基础车间为10台机器、4个机器组、3类作业、平均路线4道工序；Grid改变利用率、交期紧度、到达与加工时间变异、扰动率和负载不均衡。Sweep围绕代表性配置做利用率、变异、交期紧度和扰动强度扫描。问题是随机事件驱动的动态在线仿真；但70个实例各自启用了哪些动态事件、实际任务规模分布、精确目标及逐实例约束没有在LLM实验段逐项给出。表3报告L1 Direct：总Tokens 3.752M、Mean Cmax 2.0%、SE 1.0157；L1 CoT：4.016M、1.9%、SE 1.0151；L1+Tool：12.614M、2.0%、SE 1.0271。表3均值只显示一位小数。表4是另一张分布表：Direct均值1.95、中位数0.63、P90 2.57、P95 3.27；Tool为2.03、0.52、2.47、4.27；其中没有L1 CoT，不能把表4与表3混成同一组精度或样本口径。跨模型的表5则单独采用匹配的L1 Direct协议、相同提示模板、两个few-shot示例、temperature 0和top-p 1；这些参数不能自动套用到表3变体比较。表5列出模型为Qwen3-8B 1.01%、Qwen3-14B 1.34%、Qwen3-4B 1.45%、Kimi-K2 1.46%、Claude-4.5 Haiku 1.52%、Qwen3-32B 1.65%、DeepSeek-V3.2 1.68%、Gemini-2.5 FlashLite 1.76%、Grok-4 Fast 1.88%、GPT-5 Mini 1.93%。24个组合PDR由8种工序排序规则和3种机器分配规则组成；固定最佳规则1.11%、中位规则1.94%、最差规则51.52%。作者报告Qwen3-8B与LIFO+LIT无显著差异（表6的FDR p=0.397），但该检验不能替代表3中Direct/CoT/Tool变体的配对检验。

**成本与时延：** 表3给的是各配置的总token量（单位百万）和质量均值，没有报告每个实例的token均值、输入/输出拆分、调用数、工具调用数、计费金额、壁钟耗时或真实决策延迟。按表面总量，L1+Tool约为L1 CoT的3.14倍token，但这只是作者表中总量比值，不是单位动作或单位实例成本。作者称开源模型用vLLM在Intel Xeon Platinum 8468V与H100 80GB节点运行；没有提供足以比较延迟或成本的测量。表3未明确说明模型身份、完整有效样本分母、失败任务是否计入token总量或质量均值，故不能换算部署成本或按单例外推。

**验证与泛化：** 作者称70例子集的难度、利用率、到达SCV等KS统计量分别为0.175、0.086、0.251；附录还给出更多覆盖诊断。这说明子集按作者定义覆盖生成池的指标分布，不等于独立持出测试集。论文没有说明LLM任务的训练/开发/测试拆分，也未报告这70例是否被用于调提示或模型选择；未报告表3各配置的重复次数、完整有效样本数及未完成任务处理。附录J特定提示机制消融明确是Qwen3-8B、按实例配对的42个完整案例；42不能当成表3的分母，也不能与表5的跨模型排名拼为同一对照。只有表5跨模型比较明确给出解码参数；Table 3所用模型具体版本与生成参数未在实验配置中标清。所有效果均是作者报告的合成仿真实验，不是独立复现或真实工厂验证。

**测试证据：** 存在作者报告的模拟评测证据：70例动态实例上的配置均值、标准误、分布统计及独立的跨模型/PDR比较。表5还有特定配对检验。本文没有被本任务复跑；论文、README或接口示例的存在都不能当作本地运行证据。

**部署证据：** 未见真实工厂部署、生产运行日志、在线延迟或产线收益证据。证据范围是作者构造的校准动态排程基准与事件仿真。

**迁移条件：** 若项目B的边界是模型逐步输出具体可执行动作，本文最接近B；需先核实模型输出动作字段，并把环境构造/过滤合法集合的责任分开。若项目C要求模型调用排程构造器或选参数、再由算法形成具体安排，则论文的inspect/simulate工具本身不足以归入C，因为最终下一步动作仍由代理选择。只有确认候选集合、机台分配、等待推进、解析和修复路径后，才能把合法率与质量比较迁移到项目；还需匹配实例分布、观察信息、目标、预算和失败分母。

**失败方式：** L1+Tool在表3的Cmax均值与L1 Direct相同且高于L1 CoT的表列值，token总量明显更大；论文将其解释为主动探查效率不佳。；L3 CoT均值1.7%高于L2 CoT的0.7%；更丰富的结构先验没有稳定改善该实验表现。；附录J中Reflection为1.7%、BestOfN为2.7%，均高于L2 CoT 0.7%；这是特定配置的结果，不应推演为所有模型或任务都失败。；论文的环境动作过滤可能提高轨迹可行性，但缺少原始模型输出合法率及过滤前后统计，无法判断模型本身的非法动作风险。；表3没有报告失败/解析错误/回退统计；其质量均值无法单独证明端到端可靠性。

**未知：** 表3使用的基础模型、模型权重或API快照、具体提示、温度与每配置调用/重复次数未报告；不能假定与Qwen3-8B消融相同。；表3和表4的逐项有效样本数、缺失或未完成实例如何计入，以及token总数是否包括失败请求和工具调用，未报告。；Mean Cmax相对“每实例最佳已观察排程”的精确计算式、该最佳值来自哪些候选方法，以及表3与表4的完整统计分母未充分说明。；动作schema是否明确包含lot/作业、工序、机器、批次、开工或等待推进；候选集生成/截断、输出校验、非法动作拒绝或修复、失败回退，未报告。；样本70例中动态事件的逐实例激活配置、作业规模范围、全部约束清单和各层观察的完整字段未报告。；训练/开发/持出测试拆分、提示是否经子集调优、表3变体间统计显著性检验均未报告。；会议与arXiv版本：arXiv可读版本为2026-05-26提交的v1；PMLR页面确认ICML 2026论文元数据及相同标题/摘要，但链接全文PDF本次读取失败，故表格和正文差异未知。未命中差异不表示没有差异。

### S-08 · Q-04 · DynaSchedBench implementation

[route_definitions.B_project/C_project; ownership_fields](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[legal_actions():2660-2696; advance_if_idle():2698-2734; step():2542-2658](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Env/SingleAgent.py>)（访问/取证日期：2026-10-12）；[ObservationEncoder.prune_candidates():1914-2184; encode():2186-2227](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/feature_extractor.py>)（访问/取证日期：2026-10-12）；[LLMPolicy.decide():2187-2282, 2368-2468; _is_legal():2511-2612; _decide_o1_cognitive():3389-3546](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/policy.py>)（访问/取证日期：2026-10-12）；[CognitiveConfig and ModelConfig defaults:31-60](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Agents/LLMScheduler/config.py>)（访问/取证日期：2026-10-12）；[step_action():2403-2467; _select_machine_for_action():3045-3116](<https://github.com/dsbx7/DynaSchedBench/blob/main/src/dsbx/Sim/Simulator.py>)（访问/取证日期：2026-10-12）；[LLM Agents/API-key note:262-292](<https://github.com/dsbx7/DynaSchedBench/blob/main/docs/agents.md>)（访问/取证日期：2026-10-12）；[§4.2, §5, §7.1-7.3, Appendix J](<https://arxiv.org/html/2605.27566v1>)（访问/取证日期：2026-10-12）；[Requested official documentation page](<https://dsbx.readthedocs.io/agents.html>)（访问/取证日期：2026-10-12）

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C01

**机制：** 读取到的代码是 GitHub `main` 分支快照；工具没有取得可核验的 commit SHA，因此下列控制流应视为该分支在本次读取时的实现，不可无条件回写为论文实验代码。`DynaSchedEnv.legal_actions()` 对模拟器返回的每个 ready operation 建一个动作，字段为 `job_id`、`machine_group`、`machine_candidates`；不是完整排程或开始时间。`ObservationEncoder.encode()` 先调用 `prune_candidates()`。默认 `max_candidate_actions=40`，但这是配置默认值，不代表论文采用40，也不代表CLI每次都用默认值。超过上限时，基集先随机打乱，约一半均匀抽样；其余槽位由随机抽取的两条PDR规则分别按分数取前列、不重复补足。最终顺序是随机部分、第一条规则所选、第二条规则所选。这个截断发生在机台展开之前，所以展开后的ActionID行数可能超过40。`select_machine=True` 时（配置默认值），每个保留的工件/工序组动作按 `machine_candidates` 顺序展开为各机台的独立行；提示表给行编号，模型用 `action_id` 选择。`False` 时不展开机台，模型行里只有工件/组动作。

**实际决策边界：** 按量规，当前实现只能条件性归类：在 `select_machine=True` 且LLM正常返回有效选择时，模型选具体 `job_id`（其当前工序由状态隐含）、`machine_id`，并决定下一项派工，故实际拥有逐步动作和局部顺序选择，属于B方向的在线具体动作选择；它没有选择批次形成、完整工序序列、开始时间或主动等待。若关闭机台展开，`Simulator._select_machine_for_action()` 会在未给出有效机台时替模型选能最早开工的机台；开始时间再按当前时刻、作业可用时刻、设备可用时刻、停机阻塞时间的最大值计算，时间推进由模拟器完成。此分支下机台归模拟器，不能说模型决定完整B排程。L1+Tool的 `simulate_action` 是对候选动作的短程估分；读到的代码仍让模型选最终动作，不等于模型调用构造器让算法作具体排程，因此不据此判C。平票时程序还会用环境分数选择。候选截断、无响应/非法输出回退、平票评分、机台适配和等待推进都必须作为程序贡献披露。

**实验条件：** 论文原文为 arXiv v1（2026-05-26）；作者报告的是动态柔性作业车间问题及其校准基准，不是本地工厂数据。LLM评估用70个代表实例（Grid 30、Sweep 40）；Grid说明的基础配置为10台机、4个机群、3类作业、平均路线4道工序。论文对照L1 Direct、L1 CoT、L1+Tool、L2 CoT、L2 Reflection、L2 Best-of-N、L3 CoT；跨模型比较统一L1 Direct、两条few-shot、temperature 0、top-p 1。模型表列Qwen3-4B/8B/14B/32B、Kimi-K2、Claude-4.5 Haiku、DeepSeek-V3.2、Gemini-2.5 FlashLite、Grok-4 Fast、GPT-5 Mini。开源权重作者称用vLLM在Xeon Platinum 8468V与H100 80GB节点推理。基线为24个固定组合（8条工件排序规则×3条机台分配规则）；作者报告最佳固定启发式，不是逐实例oracle。论文的动作接口/工具实验说明仍不足以核实论文运行时是否与当前 `select_machine=True`、40候选截断和同一回退代码一致。

**成本与时延：** 论文Table 3报告各配置总token数（百万）：L1 Direct 3.752、L1 CoT 4.016、L1+Tool 12.614、L2 CoT 6.883、L2 Reflection 14.470、L2 Best-of-N 7.770、L3 CoT 8.620；并报告相对最佳已观测排程的平均makespan差及标准误。论文未报告美元成本、调用延迟、每步时延或失败重试成本。当前代码默认采样 `n=1`，通常对空输出最多重试3次；Best-of-N等参数会改变样本数。不能把代码的超时配置当实测延迟，也不能把论文token汇总换算为调用次数或单次成本。

**验证与泛化：** 作者报告70实例子集由Grid/Sweep抽取，覆盖完整集四分位区间；跨模型结果用同一L1 Direct协议。Table 5中Qwen3-8B平均差1.01%，最佳固定规则1.11%；作者称两者无显著差异。论文还报告相对最佳排程的分布指标、配对检验，以及42个完整样本上的提示消融。论文未报告LLM训练/开发/持出测试拆分、每模型重复次数、合法输出率、修复前后可行率、无效/超时样本分母、失败是否计入质量均值；因此70实例不能自动说成持出测试或证明跨工厂泛化。消融与效果均为作者报告，未独立复现。

**测试证据：** 未运行测试、工厂模拟或排程。证据是公开代码、文档及论文的静态阅读；函数/回退分支存在不等于其运行频次或效果已验证。

**部署证据：** 未发现论文或指定文档提供真实工厂上线、接入生产控制系统或生产运行日志证据。论文所述本地vLLM/H100环境是实验配置，不作为生产证据。

**迁移条件：** 若将此项目路线映射到量规，需锁定论文所用commit、LLM配置、`select_machine`、候选上限与筛选随机种子，并分别记录模型ActionID选择、机台适配、无效输出修复、fallback和无动作推进。比较B/C前还要按同一规模、动态事件、约束、观察信息、基线、质量分母和成本口径对齐；论文的代表性子集与token总量不能直接外推到本项目工厂或部署延迟。

**失败方式：** 候选数量超过上限时，随机候选筛选可能移除模型本可选择的动作；PDR补集同时注入算法偏好。；机台展开在截断之后，候选上限不约束最终ActionID行数。；当前代码的默认40、select_machine=True和随机PDR候选集不能冒充论文实验参数。；CoT无有效ActionID可退到首个截断候选；无候选时SPT启发式接管。；多样本输出平票时，程序按环境评分选动作；这部分决定权不属于LLM。；遗漏machine_id时模拟器会按最早可开工规则选机；开始时刻及空闲推进也由程序控制。；文档提到无API key使用null client/回退，但具体构造与策略调用链本次未能读全。

**未知：** GitHub `main`的精确commit SHA、论文实验所用代码版本以及两者是否一致。；论文实验是否启用`select_machine`、使用何种候选上限/排序及实际ActionID字段。；论文LLM实验的每模型重复次数、失败处理、合法率及修复前后可行率分母。；各配置实际调用数、API美元成本、wall-clock延迟、超时及失败开销。；缺少API key时client工厂如何实例化、是否返回空结果，以及空结果是否必达当前首候选回退。；模型是否看到全部候选机台状态、不可用机台是否在候选表内被过滤；当前代码只确认编码会显示部分状态特征，未证实论文采用同一行为。

### S-09 · Q-04 · SCHEDBench direct full schedules

[§3–§5; Appendix A.1–A.7 and B.1–B.3; Tables 2–4, 12, 16–19](<https://arxiv.org/html/2608.00991v2>)（访问/取证日期：2026-10-12）；[main branch file listing and README sections on source layout, BKS, variant generation, and reproducibility](<https://github.com/SCHEDBench/SCHEDBench_Datagen>)（访问/取证日期：2026-10-12）；[translate_jssp() lines 180–202; translate_rcpsp() lines 204–263; DOMAIN_FUNCTIONS lines 325–331; main() lines 336–535](<https://raw.githubusercontent.com/SCHEDBench/SCHEDBench_Datagen/main/step1_translate.py>)（访问/取证日期：2026-10-12）；[main(): mutually exclusive --solve and --bks paths; domain-specific solution generation](<https://github.com/SCHEDBench/SCHEDBench_Datagen/blob/main/step2_solutions.py>)（访问/取证日期：2026-10-12）；[Dataset card: test split, 1,132 rows, fields and family composition](<https://huggingface.co/datasets/SCHEDBench/SCHEDBench>)（访问/取证日期：2026-10-12）；[route_definitions.B_project/C_project/offline_generation; ownership_fields; comparison_required](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C03

**机制：** 主实验是零样本直接排程：模型读自然语言实例和该类任务的格式规则，输出完整排程表。统一系统提示要求模型自行求解、不调用工具或外部求解器；论文称随后用解析器提取排程、做少量非实质文本清理，并以领域验证器检查硬约束。OR-Tools CP-SAT用于可行性验证，且用于核验参考BKS；原文没有说它会接手模型的排程、补齐方案或修复违规结果，因此应按“模型作安排、求解器验证”理解。数据生成另有一条离线确定性模板管线：step1把基准实例转成自然语言，step2取BKS或可选地本地求解参考解，step3合并提示、参考解与难度。这是基准制作，不是运行时模型调度，也不能据此归为项目C。

**实际决策边界：** 按给定rubric，主实验属于直接完整排程的B类证据：模型须给出各项排程决定，而非调用构造器或选择算法参数。JSP格式让模型输出每道工序的开始时间，操作顺序由排程结果体现；但基准中的JSP是固定工艺路线/机器的经典JSP，模型没有FJSP式的备选机器分配权。RCPSP-SM输出活动开始时间，RCPSP-MM还要求输出模式，模式带有各自工期和资源需求；这不是机器选择的同义词。护士排班、课程表也由模型直接列出分配。解析器负责读格式，验证器负责检验；已查材料未显示它们隐式选择机器、批次或等待。论文附录另报有限的solver-code探索实验，和主实验直接排程分开；仅凭其名称不足以映射到本项目C或确认求解器替模型做了哪些决定。

**实验条件：** 核查的是2026-08-26修订的v2论文。13个API模型为GPT-5.4 mini、GPT-5.4、GPT-5.5；Claude Haiku 4.5、Sonnet 4.6、Opus 4.6；Gemini 3 Flash Preview、3.1 Flash Lite；Qwen 3.5 27B、122B、397B；Llama 3.3 70B、4 Maverick。论文列出具体API标识及部分日期快照；Sonnet/Opus 4.6注明为固定快照，专有模型参数规模未披露。主评估集1,132例：JSP 262例，6×6至100×100作业/机器规模；RCPSP-SM 400例、32–122个活动、4种可再生资源；RCPSP-MM 300例、12–32个活动、混合多模式资源。另有ITC 21、INRC 69、NSPLib 80例。难度共406/295/431例，但难度只在各族内定义，不可跨族比较。JSP每项工序固定机器；RCPSP-MM的模式体现资源/工期选项。主要目标为JSP/RCPSP最小化工期，排班/课表最小化罚分。主v4全变体集对13模型各评一次；另在匹配的470例上做v1至v4表面变体比较。种子敏感性实验在150例子集上为v2、v3A、v3B各生成三个渲染种子，测量渲染改变的影响，不是重复随机采样模型。无模型训练或超参搜索；没有报告独立训练/开发/持出实例切分，也没有固定派工规则基线。BKS用于目标差距参照，不等于同条件调度基线。

**成本与时延：** 论文报告所有评估共约4.9亿输入token、9.2亿输出token，合计约14亿；按2026-04-23公开按量价格估算总推理费约2,371美元（OpenAI 1,271、Anthropic 971、Qwen 64、Gemini 36、Meta 29美元）。该数覆盖论文所述整套SCHEDBench评估，未单独拆出1,132例主v4直接排程、每模型费用或每实例费用。每次请求的中位上下文约13.8k token；各模型经托管API调用，CPU机器并发执行。论文未报告端到端壁钟、单请求延迟或生产排程时延，因此不能把总token量/费用换算成工厂实时成本。

**验证与泛化：** 主指标是可行率：各模型在实例上输出满足硬约束的比例，按家族、难度、变体和总体报告。表中难度格用该格实例数作分母；总体以1,132例为分母，右侧跨模型平均是模型可行率的平均。论文另报相对BKS的百分比目标差距，但只对可行输出计算均值/中位数。v4提取统计为13×1,132=14,716个模型-实例单元，其中56个输出为空/无法解析、14,660个成功提取；由固定主表分母及“可行排程”定义可推断空输出不会被算作可行，但论文没有完整写出解析失败的计分伪代码。变体配对波动分析明确排除无输出配对。CP-SAT版本9.15.6755；验证参考BKS时若超时，该BKS仍保留在评估集。论文报告v4跨六族平均可行率15.2%，GPT-5.5为55.9%；这是论文作者报告值，不是本次复跑结果，更不能代表FJSP。表面形式变化会影响可行性，约束重排是文中测得较明显的扰动之一。

**测试证据：** 这是作者报告的基准实验，不是本次复跑或工厂模拟。主v4每模型-实例一次、温度0；抽取统计覆盖14,716个单元，56个无可解析排程。作者用可行率、可行解上的目标差距、表面变体配对分析及bootstrap 95%区间报告结果。未在本任务运行代码、求解器或新模型排程。

**部署证据：** 未见真实工厂部署、在线派工、动态重排或生产SLA证据。实验使用静态公开基准和托管API；CP-SAT验证器与数据集BKS校验不构成生产运行证据。

**迁移条件：** 只有在目标流程也让模型依据完整静态实例直接输出全表安排，并由外部程序独立解析和验证时，主实验才提供有限的机制类比。若模型仅选启发式/策略参数、再由程序构造安排，应另按C类评估。迁移到柔性机台、批次形成、切换时间、设备状态变化或滚动计划前，需验证模型是否真正持有这些决策权；SCHEDBench本身没有证明这些条件。

**失败方式：** 输出无法解析或偏离格式；v4有56/14,716个单元未能提取出候选排程。；格式正确仍可能违反硬约束；主评估将可行性和目标质量分开，目标差距只在可行输出上计算。；模板、主题、约束顺序等语义等价的表面变化会改变模型表现；约束重排在多模型上表现出超过渲染噪声的变化。；没有报告对模型排程做可行性修复；不得把验证成功写成自动修复或求解器完成排程。

**未知：** 指定公开仓库是Datagen代码；完整模型调用、输出解析器及家族验证器实现未在该仓库文件列表中定位，论文笼统称代码和数据发布，但本次未确认独立评测仓库。；除少量清理非实质文本外，解析器如何处理缺项、重复项、非法时间、部分答案及解析错误的精确计分伪代码未报告。；论文未单独说明空解析的数值计分步骤；固定1,132分母暗示其不能作为有效解，但需原始评测代码确认。；总费用、token和并发统计未拆到主v4、模型、家族或单例；单例壁钟和API延迟未报告。；未报告模型训练/开发/持出切分，也未报告对公开基准实例的预训练污染审计；主评估更适合作为既有基准测试，而非严格未知实例泛化证据。；附录solver-code探索实验的代码生成、执行与求解控制流不等同主实验；本次材料不足以将其明确映射到本项目B或C。

### S-10 · Q-04 · GenAI job scheduling FJSP case

[Cambridge Core 原文及开放 PDF：方法 Steps 2–5、案例、结论、表10、附录A–B](<https://doi.org/10.1017/S0890060425100152>)（访问/取证日期：2026-10-12）；[route_definitions、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C04

**已纠正：** 不将该论文所描述的本地系统计为已证实的LLM直接排程或LLM工具调度；已读机制为词典/ETFN、模型修改与GA。

**机制：** 作者把系统称为 GenAI 排程系统，但正文描述的本地系统并非由 LLM 直接建模或生成排程：它用分词、词干/词形处理和预设词典，从自然语言查询提取关键词及参数，映射成扩展三字段表示（ETFN）；随后按 ETFN 修改数学规划模型（MP），再由 MATLAB 程序改写预先存在的 GA 代码，插入或替换目标函数、约束对应逻辑。系统数据库保存模型、GA 程序及种群信息。论文明确说查询分析不需要用 DNN，并称工程师不需预训练 GPT。GA 才执行具体搜索：创建染色体、按 MP 目标评价适应度、选择/交叉/变异，并检查重复工序、工序前序、用户指定机台和工序顺序等可行性条件，最后产出排程。附录B提供 GA 伪代码，正文称基础 GA 主步骤大体不变，按问题修改适应度及可行性检查。作者报告 LINGO 用于验证默认 MP 模型及约束/目标改动；这属于模型正确性检查的报告，不等于 LINGO 负责表10比较中的具体排程，也没有证据表明 LINGO 验证了 ChatGPT/DeepSeek 输出。

**实际决策边界：** 按本项目量规，不能只因系统名称含 GenAI，或算法由自然语言要求触发，就归为 B 或 C。作者系统的明确控制流是词典解析→MP/GA 程序更新→GA 排程；机台、顺序、开始时间等具体安排由 GA 搜索，而非论文所述 LLM 逐步决定，因此不构成已证实的直接 B。它也没有报告 LLM 调用排程构造器或选择 GA 策略参数；MATLAB 规则按 ETFN 修改程序，不能据此直接认作项目 C。较稳妥的分类是“结构化需求解析／优化模型与程序定制／GA 求解”的独立算法路线，与 C 有算法执行相似处，但不等同。对 ChatGPT 和 DeepSeek，作者只称其排程结果由通用 GenAI 系统生成；机器分配、工序排序、开始时间、等待、非法输出修复或回退究竟由模型、提示流程还是人工纠错决定，正文没有足够可核验细节，故也不能据此断定其为 B。

**实验条件：** 作者报告的工厂案例为台湾台中精密加工厂，6 台机、10 个不同产品类型的作业，每日不同时间释放，有 release time、due date，目标为 makespan，记作 FJ6/rj,dj/Cmax。查询解析实验由 5 名生产计划/控制工程师提出 100 条查询；管理员检查 ETFN 并对误读做纠正，作者报告最初 8/100 条未正确解释，之后扩充系统词典并重新运行查询。该过程没有报告独立训练、开发、持出测试集或最终分母定义。通用服务比较则被描述为 6 台机、3 种产品类型的 FJ6//Cmax；这是不同于前述带释放时间/交期的主案例的比较问题。比较段落没有明确说明通用服务问题究竟是否也是 10 个作业，不应把主案例作业数移植到比较组。表10列出的 MWR 基线、ChatGPT、DeepSeek、本地 GenAI 系统的排程性能分别为 33、29、39、25，执行时间列分别为 0.00、超过300秒、超过600秒、2.81秒。若性能值是该比较问题的 makespan，则数值越低越好：相对 33，29 约低12%，25约低24%，39则约高18%；PDF文本抽取中的箭头/符号不完整，DeepSeek 行的18%方向不宜照抄成“改善”。未报告模型/服务具体版本、提示全文、温度、调用次数、随机种子、重复次数、统一输入协议或失败样本分母。作者称通用服务过程冗长且常需反复纠正，但没有说明表10成绩是首次输出、纠正后的结果、最佳结果还是人工挑选结果，也没有交代纠正轮数及失败是否计入。

**成本与时延：** 表10统一把数值放在“执行时间（秒）”列，因此可以确认作者报告了 2.81 秒、超过300秒和超过600秒这三个表列时间；不能确认其起止边界相同。正文称通用 ChatGPT/DeepSeek 流程常需多轮纠正，而本地系统由结构化查询解析并自动改写 MP/GA；表格没有说明通用服务耗时是否包含人工阅读、重提示、纠错及等待，亦未说明本地系统 2.81 秒是否包含输入整理、模型构造、启动开销或数据库交互。没有硬件、网络/API 条件、计时方法、服务端排队、调用/token 数、货币成本或失败重试成本。故这些是作者在一个案例中的表列时间，不足以证明同口径端到端延迟或成本优势。

**验证与泛化：** LINGO 验证的范围据作者描述是默认 FJSP 数学规划模型及后续目标/约束修改，先用文献中的示例数据，再以同样方式检查改动后模型并存入数据库。未报告 LINGO 版本、具体实例、最优性容差、求解时间、逐项结果，或它是否对 GA 产出的每份排程独立验算。主案例的查询解析结果包含人工核查和词典修正，8/100 是修正前误读数；没有独立持出集，不能把它解释成未经修复的泛化准确率。论文表9还将 GA 系统结果与若干不同论文中的结果并列，作者称表现接近原研究；那不是与通用 LLM 的同条件基准复测。数据可用性声明为按请求提供，正文给出伪代码但未在所查原文中看到公开可运行实现。公开原文可读，但未独立复现，作者报告不应写成亲跑验证。

**测试证据：** 证据层级仅为论文作者报告：本地系统用于一个精密加工厂案例；另有 100 条、5 名工程师的查询解析记录及若干跨论文案例结果。比较组是作者报告的一次/若干次通用服务尝试，但没有可确认的重复统计。我们没有运行工厂模拟、模型排程、GA、LINGO 或复现实验；不能把作者报告改写成独立验证结果。

**部署证据：** 论文称系统应用于台中精密加工厂，并称敏感数据保留在组织内；这支持“工厂案例应用”的作者报告，不足以证明持续生产部署、排程实际下发、长期运行稳定性、人工审批流程或闭环收益。没有部署时长、生产记录、在线故障率或用户验收的独立证据。表10中通用云服务的数据泄露风险标记是作者的表格判断，不是此任务核验过的安全评估。

**迁移条件：** 要把表10用于 B/C 比较，至少需固定并披露同一批 6 机作业数据、release/due date 与目标定义，明确通用比较是否为10作业及为何改为 FJ6//Cmax；记录 ChatGPT/DeepSeek 的确切模型与日期、完整提示和工具权限，定义谁选机台/顺序/开始时间及谁修复；对照相同的成功标准、重复次数、种子、失败分母和纠错政策，并用共同的计时起止点分别报告系统时间与人工交互成本。要把作者系统结果迁移到本项目，还需验证词典/解析错误处理、MP 约束覆盖、GA可行性逻辑及持出实例上的表现。

**失败方式：** 作者报告 100 条查询中有 8 条初次解析错误，之后通过检查和扩充词典修正；未报告修正后独立测试集结果。；论文称 ChatGPT/DeepSeek 交互过程冗长且常需反复纠正，但纠正次数、输出选择规则及最终成绩是否修复后取得均未报告。；GA染色体可能违反重复工序、前序、指定机台或指定顺序等条件，正文描述了可行性检查；没有公开运行轨迹证明所有失败路径均被覆盖。；表10 DeepSeek 39 高于 MWR 基线33；若同为待最小化的 makespan，则表现更差，表中18%的方向标记在文本抽取中不清楚。；论文未报告跨重复 GA 波动、失败次数或质量统计分母，单个表值不能显示随机算法稳定性。

**未知：** ChatGPT、DeepSeek 的确切模型/服务版本、使用日期、系统提示、完整对话、采样参数和工具配置未报告。；通用 GenAI 比较是否确为10个作业未在比较段落明确；六机三产品类型被报告，但不能确认是否与主案例同一数据及同一约束。；2.81、>300、>600秒的计时起止、硬件/网络、是否包含人工纠错、失败和重试均未知，故不能确认为同口径。；表10数值的重复次数、随机种子、结果分布和失败计入规则未报告；DeepSeek 行18%的方向符号无法从文本抽取可靠确认。；LINGO版本、模型验证实例/结果、容差，以及是否逐个验证 GA 或通用服务生成的排程未报告。；数据按请求提供；所查原文只有 GA 伪代码，未找到可核验的作者公开源码。图13原始聊天截图资源在本次网页读取中返回缓存不可用，提示/纠错细节因此仍未知。

### S-01 · Q-01 · SeEvo

[route_definitions、direct_subtypes、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[v1（2024-10-30），§§II、III、V-A—D：问题版本、实验设置、静态基准与随机到单动态实验](<https://arxiv.org/html/2410.22657v1>)（访问/取证日期：2026-10-12）；[v2（2026-07-29），§§III、IV、V-A—F、VI：DFJSSP机制、参数、静态与动态测试、成本局限](<https://arxiv.org/html/2410.22657v2>)（访问/取证日期：2026-10-12）；[公开 main 分支快照；README 的论文引文与题名相符。核读 seevo.py、problems/jsp_constructive/Real_Time_FJSP.py、eval.py、main.py、utils/utils.py；代码访问经 GitHub 文件页及 raw 页面，未执行](<https://github.com/huangjin-collab/LHH_DFJSP_SeEvo>)（访问/取证日期：2026-10-12）

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C05

**机制：** SeEvo 是让大模型生成并迭代改进启发式派工规则（HDR）的自动算法设计框架。v1（2024）研究动态作业车间，动态实验聚焦随机到单；v2（2026）改为动态模糊作业车间，增加模糊加工时长、机器故障与维修，并报告最大完工时间和拖期目标。两版都把作业调度拆成规则演化和仿真应用：LLM 生成规则代码，环境运行规则、测量目标，再把规则及其表现交给反思、交叉和变异环节。v2 说明其教师掌握实际加工时长，学生侧可见计划时长及历史偏差；EMA 将已观测的计划—实际偏差压缩为特征，供规则使用。论文列出的 v2 特征有当前工序时长、剩余工作、后续工序、总加工时长、EMA、交期和估计拖期等。

当前公开仓库的 `RealTimeFJSPDual.step` 路径可见更具体的分工：环境从可派作业池生成特征，调用生成规则得到分数，再由 `argmin(score)` 选作业；之后代码按名义加工时长最小值选合格机台，放入队列，并由环境推进到加工完成或动态事件。环境还处理到单、机器故障、维修、工序就绪和 EMA 更新。因此作业评分规则由 LLM 生成，但机器、时间推进与事件处理不由 LLM 逐步输出。仓库 `func_signature.txt` 只有六个特征参数，仓库 README 将问题称为柔性作业车间，`eval.py` 当前按 makespan 汇总；这些与 v2 论文列出的八类特征及拖期实验并不完全对应，故仓库应看作相关的可读实现快照，不足以证明它就是论文每项实验的精确代码版本。

**实际决策边界：** 按 rubric 的实际决策者规则，最稳妥的分类是第三条“离线生成规则/程序”，附带对每个测试用例进行一代规则演化的测试时模型调用；不能仅凭论文中的“在线应用”或“实时反馈”把它归入本项目 C。LLM 输出的是可执行规则代码，不是完整排程表，也不是逐个派工时由模型接口即时返回的 lot、机台、开始时间或等待动作。运行时，规则代码给候选作业算分，仿真器通过 argmin 落定作业；仓库还由程序依据名义时长选机并推进时间。可见的候选池本身是环境形成的，因此可行候选集合和解码步骤也是调度器贡献。

这一机制和 rubric 中“优先序/分数输出后由解码器安排”有表面相似之处，但这里的分数是已生成程序运行所得，而非模型在每个动作点输出的分数。若项目把模型离线生成的规则视为模型决策策略，可记录为 B 邻近的“评分策略影响作业选择”子型；不过论文和可见代码没有显示模型直接指定整表、机台或等待，不能据此宣称完整 B。C 的判据是模型调用构造器或选择策略参数、算法据此安排；本来源没有显示该类项目工具调用，也没有显示 SeEvo 模型在生产动作点选择构造器参数。若某项目后续把这段规则生成或调度调用封装进自身工具，是否属于 C 需看那个 harness 的控制流，本来源不能代替工程侧核查。

另一个边界是“在线”。论文把仿真中的动态派工称为在线应用，但当前仓库 `evolve()` 的 test 模式仍会读取已保存规则并运行单代演化，期间交叉/自进化生成新规则并按该用例表现比较。它支持“测试流程中仍调用模型改进规则”，不支持“模型每次派工时都在线决策”。测试中的测试时搜索与部署时固定规则运行应分开记账；冻结规则是否足以复现论文报告性能、是否每个场景都要 API 调用，当前资料没有证明。

**实验条件：** 版本差异不能合并为同一任务结果。v1 的静态实验使用 Taillard（TA）和 Demirkol（DMU）公开基准；训练另用随机生成的 20—100 个作业、10—20 台机器、加工时间 50—100 的案例。动态实验使用 20 个训练案例，每批 20—50 个作业、2—3 批、到达区间 [1,500] 与 [501,1000]；测试环境固定 10 台机器、加工时间为 50—100 的整数，另生成 100 个测试案例。该版主要目标是 makespan，动态扰动描述为随机到单。LLM API 是 gpt-3.5-turbo-0125 和 GLM-3-Turbo；参数表为温度 1、人口 20、最多 20 次评估、变异率 0.5。训练最多 20 代；测试每个测试案例仍做一代。

v2 的 LLM 是 gpt-4.1-mini-2025-04-14、Qwen-Turbo、DeepSeek-V3，DeepSeek-R1 因响应慢被排除。静态测试报告 160 个 TA/DMU 基准案例、8 种规模；动态训练为 20 个随机案例，20—50 个作业/批、2—3 个子批、5—20 台机器、每例 1—2 次故障，故障持续 1—500、维修 10—50 个时间单位，并用 Gamma 噪声模拟加工时长偏差。动态测试 makespan 和 tardiness 各报告 100 个案例。拖期实验故意设较短交期以拉开差距；论文承认这和真实工厂中更动态的交期设定不同。

v2 用 L9 正交表对温度、人口数、最大迭代数和变异率调参；每种组合在 4 个训练案例（2 静态、2 动态）上独立评估 3 次，选出人口 20、迭代 20、变异率 0.9、温度 1。训练每轮 20 个随机案例、每轮替换一个；测试保持交叉/变异概率但只做一代。GP/GEP 对照说明使用 80 个训练案例、每轮 20 代、每轮替换案例、人口 20、每轮随机抽 4 例。基线包括十余种常见 HDR、GP/GEP 和端到端 DRL；论文说明部分静态基线数据取自既有论文，不能一概当作同机同代码复跑。论文报告的是作者实验，不是本次独立运行。

**成本与时延：** 成本披露为部分报告。v1 报告 50 作业、15 机器的静态测试规模下，GPT-3.5 生成方案约 19 秒、GLM-3 约 29 秒。v2 报告 100 作业、20 机器规模下，Qwen-Turbo 约 40 秒、gpt-4.1-mini 约 42 秒、DeepSeek-V3 约 122 秒，并称 DeepSeek-V3 API 成本约为 gpt-4.1-mini 的三分之一。论文没有给出具体费用金额、输入/输出 token、总 API 调用次数、逐调用耗时分布、动态场景的实际派工延迟，也没有拆分模型生成、规则评估和仿真所占时间；这些秒数不宜直接解释成每次现场动作的延迟。

仓库 `utils/utils.py` 的 API 封装会发起聊天完成请求、并行处理多段对话；没有发现读取 usage token 或汇总账单的代码。异常可重试多达 1000 次、每次间隔 1 秒，持续失败会退出。`seevo.py` 里的 `function_evals` 是演化迭代计数，不能当作 API 请求数。训练采用人口、反思、交叉和变异多个阶段，测试也保留一代规则演化，因此每个案例的真实请求成本不能从论文报告的单个“生成方案”时间反推。实际总成本、失败重试成本和动态测试中的总 API 消耗均未报告。

**验证与泛化：** 泛化证据分版本看。v1 在随机训练案例后报告 32 个 TA/DMU 基准测试案例，覆盖 8 种问题规模；动态测试 100 案例与训练使用同一生成方式，目标为 makespan。v2 报告 160 个 TA/DMU 静态案例，并在动态场景分别测试 100 个 makespan 和 100 个 tardiness 案例。v2 对动态性能使用相对 Gap Ratio，分母是该案例所有 14 种对比方法中的最好值，不是真正全局最优；作者报告 makespan 的最大 gap 不超过 5%、多数低于 1%，拖期最大 gap 不超过 6%、多数低于 1%。这些是论文自报结果，不是独立复核。

“持出测试”需要限定解释。论文明确采用单代测试；仓库 test 模式先载入训练规则，然后在单代中调用模型反思/生成新规则，并用当前案例目标表现评估。因而样本可以和初始训练实例分离，但最终测试分数包含对测试案例本身的测试时搜索，不能等同冻结策略在从未参与选择的案例上的零调用泛化。参数调优报告有重复（L9 设计下各组合在四例上三次），但论文没有为最终模型在同一测试集上报告多次独立生成、随机种子分布、置信区间或统计显著性。基线中部分结果来自既有研究；论文具体表格有注明数据来源，跨论文结果可比性有限。

合法率、原始输出合法率、修复后合法率、不可执行规则的分母及质量统计如何处理均未见论文报告。仓库实现把无法解析、超时或执行失败的个体标为无穷目标值并在选择时过滤，但没有给出总失败比例。规则程序生成能力、模拟器构造可行派工、候选池限制和机器分配算法都共同影响结果，不能仅把整体质量归因于 LLM。

**测试证据：** 证据等级：论文作者自报的仿真结果，加上只读代码快照核对；没有独立重跑。v1 报告静态基准及随机到单测试，SeEvo 在其列出的部分案例排名领先，并给出 50×15 规模下的生成耗时；v2 报告 160 个静态基准案例和两组各 100 例的动态目标测试，并报告相对 gap。v2 的动态 gap 参照每例 14 个方法中的最佳值，不是全局最优。部分 HDR/DRL 静态对照数据取自文献。代码中的 `evaluate_population`、`_run_code`、`eval.py` 显示规则会被子进程运行、失败/超时可标为无穷目标值；这证明代码具备相应评估路径，不证明论文所有实验实际使用了当前这份代码。未报告的合法率、失败占比、最终测试重复次数、方差和置信区间仍为空缺。

**部署证据：** 未找到真实工厂上线、设备对接、生产订单回放或现场运行证据。v1/v2 的动态工况均为随机生成的模拟场景，静态测试使用 TA/DMU 基准；论文关于动态复杂度或现实相似性的表述仍是仿真实验结论。公开仓库给出训练、测试和输出目录的使用说明，但说明和可读代码不等于运行记录或部署证据。本次没有运行代码，也没有读取数据文件或工厂记录；当前证据只能支持仿真研究，不支持声称已部署或已验证现场实时性。

**迁移条件：** 迁移到相似的动态作业车间任务，至少要保持可映射的候选作业特征、工序先后关系、动态到单方式、模糊时长观测、故障/维修事件与目标函数；需要重新校准特征定义、EMA 更新、规则提示与训练分布。若目标系统含可选机台，应另行定义机器分配与利用率策略，因为当前代码由算法按名义加工时长选机，论文中的规则核心是作业选择。若目标包含批次形成、lot 合并、复杂换型、人员约束或显式等待，SeEvo 当前来源没有证据表明这些选择由 LLM 规则负责。

部署设计应明确区分离线规则搜索、每个新场景的一代测试时搜索、以及固定 HDR 的在线执行。若要求现场每次决策都不调用外部模型，可先冻结经独立持出验证的规则，并单独测量规则执行与事件模拟接口；这属于需要验证的迁移条件，不是论文已证明的生产配置。若需映射到项目 B/C，须检视项目是否把生成规则作为运行时策略，是否模型直接输出候选分数/动作，以及构造器或解码器对机台、等待和顺序的实际决定权；不能只因规则由 LLM 生成就归 C。

**失败方式：** 模型回答无法抽取出函数或缺少返回语句时，代码转换返回无效个体；语法错误、运行错误和评估超时可被记为无穷目标值并过滤。当前可见路径未显示语义排程修复器；全体个体无效或选择失败会抛错。；仓库测试模式会在测试案例上进行一代规则演化并据该案例表现筛选，可能让最终测试指标包含测试时适应；不能将其直接当作冻结规则的独立泛化结果。；作业候选池由环境形成，规则只在池内打分；若目标系统的就绪判定、候选截断或状态特征与模拟器不同，评分规则迁移后会改变实际动作含义。；当前环境由程序按名义加工时长选机，计算出的机台利用率特征未参与该选择。代码 `_gen_mach_feats` 对机器号构造候选列表时未见按故障标志筛除；若故障机器必须禁止新分配，需确认该缓冲行为是否符合目标语义。；API 失败可连续重试，当前封装上限为 1000 次且间隔 1 秒；论文未给出重试、限流、超时和失败纳入总耗时/总成本的汇总，现场长尾延迟无法据报告排除。；仓库当前规则签名只含六类特征且评估输出 makespan；直接用该快照解释论文 v2 的拖期实验或完整特征集会造成版本和目标错配。

**未知：** arXiv 页面未直接给出该仓库链接；当前 `main` 分支的不可变提交号未能从公开页面取得，代码与论文实验逐项对应关系未知。；实际提示全文、每个案例的模型请求数、输入/输出 token、API 账单金额、失败重试成本及动态派工中的端到端延迟均未报告。；生成代码的原始合法率、修复后合法率、可行排程比例、失败案例数量、质量统计的精确分母及无效个体是否计入最终结果未报告。；虽然论文将训练案例和测试案例分开描述，测试仍做一代演化；逐测试案例是否使用同一案例的目标反馈来产生入选规则，代码快照显示会这样做，但是否与论文所有表图完全一致未知。；最终静态与动态结果的独立随机种子数、重复生成次数、方差、置信区间和显著性检验未知；部分静态基线取自既有论文，重新实现范围不完全清楚。；v2 论文列出的交期、估计拖期特征与当前仓库六参数签名不一致；当前快照对拖期目标、故障机器再分配和规则输出异常的实验处理是否对应论文未知。；实际工厂数据、生产部署状态、操作者确认流程、与 MES/设备接口的连接方式、在线规则更新和回滚机制均无证据。

### S-02 · Q-01 · Evolution of Heuristics (EoH)

[arXiv v3，§3.1–3.4、§4.1–4.2、Appendix D.1–D.3](<https://arxiv.org/html/2401.02051v3>)（访问/取证日期：2026-10-12）；[README：旧 v0.1 与当前 main API 说明；FSSP 示例索引](<https://github.com/FeiLiu36/EoH>)（访问/取证日期：2026-10-12）；[main 快照：prob.py 778–813、817–897、936–1046、1048–1149](<https://github.com/FeiLiu36/EoH/blob/main/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[main 快照：get_instance.py 7–44、46–104](<https://raw.githubusercontent.com/FeiLiu36/EoH/main/examples/fssp_gls_numba/get_instance.py>)（访问/取证日期：2026-10-12）；[release 页面：2026-05-22、tag commit 4b2338f，说明为 original version](<https://github.com/FeiLiu36/EoH/releases/tag/v0.1>)（访问/取证日期：2026-10-12）；[尝试读取固定 v0.1 文件时返回 Cache miss；原版文件内容未核验](<https://github.com/FeiLiu36/EoH/blob/v0.1/examples/fssp_gls_numba/prob.py>)（访问/取证日期：2026-10-12）；[purpose、route_definitions、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C06

**已纠正：** 2,000次查询在论文v3正文§4.2装箱结果段，不在摘要，不是FSSP调用账单；提取阶段的GitHub页面行号不能当源码行号。

**机制：** 论文版本为 arXiv v3（2024-06-01）。EoH 的进化个体是启发式，而非排程解：模型先写自然语言 thought，再生成对应 Python 程序；初始化及 E1/E2/M1/M2/M3 提示策略结合种群选择，程序在实例集上评估后进入下一代。FSSP 中模型被要求设计 GLS 扰动策略：输入处理时间矩阵、当前排程、机器数和作业数；输出修改后的时间矩阵及待扰动作业。论文示例策略随机选约 30% 机器，为作业计算随机加权的处理时间均值，选均值最高的约 30% 作业，并把所选作业在所选机器上的矩阵元素乘以 0.8–1.2 的随机因子。展示代码没有使用 current_sequence 参数，作业集合由处理时间指标选出；这是一个展示的进化结果，不代表每代唯一规则。公开 main 分支的后续 FSSP 实现将 NEH 作为初始排列，执行 swap/insert 局部搜索，再调用启发式返回扰动矩阵与作业索引，针对这些索引搜索；扰动矩阵用于引导搜索，最终保留的最好 makespan 按原处理时间矩阵计算。该 main 代码是较晚快照，不能据此断言每处控制流都与 2024 论文实验代码完全相同。

**实际决策边界：** 按项目 rubric，论文所研究的是离线生成启发式：LLM 在设计阶段生成规则代码；固定规则运行时由 GLS、NEH 和局部搜索程序形成具体作业排列。扰动规则确实影响哪些作业进入定向邻域，因此不是“模型完全不影响排程”；但它没有直接输出完整顺序，也没有逐步选定最终作业位置。该置换流水车间中每个作业按固定机器路线加工，未见模型选择机台、批次、开始时间或等待。故论文证据不支持归为本项目 B，也不自动等同本项目 C；依 rubric 属独立的离线规则生成路线。若项目运行时逐次调用模型并由其选择具体作业/机台/批次或等待，须按该新控制流重新分类。

**实验条件：** 论文 §4.1 报告 GPT-3.5-turbo（未给具体模型快照、API 日期或采样参数），EoH 进化 20 代，FSSP 种群规模 10，E1/E2 选取 5 个父启发式；目标为最小化 makespan。训练/适应度实例为 64 个随机实例，每个 50 个作业、2–20 台机器，处理时间从 [0,1] 均匀分布生成，适应度为平均 makespan。测试使用 Taillard 基准：正文表 3 有 6 组规模（20/50/100 作业、10/20 机器），每组 10 个实例；Appendix D.3 扩展到 11 组，作业数 20–200、机器数 5–20，每组 10 个实例。正文比较 GUPTA、CDS、NEH、NEHFF、PFSPNet、PFSPNet_NEH；附录另列 LS、ILS1、ILS2。表 3 报告的六组相对 makespan/上界差距中，EoH 为 0.30%、0.10%、0.19%、0.60%、0.14%、0.41%，作者称各组优于列出的对照；附录报告 11 组平均 gap 为 0.23%，多数测试组表现最好。论文没有报告独立重复训练次数、随机种子方差或置信区间；也没有给原始可行率、修复后可行率、解析失败数或这些失败是否进入质量分母。代码快照能说明排列搜索控制流，但不能补成论文未报告的实验统计。

**成本与时延：** FSSP 设置为 20 代、种群 10。按论文 §3.2 所述“初始化 N 个、每代五种策略各生成 N 个”推算，名义生成请求数为 10 + 20×5×10 = 1,010；这是根据流程算出的请求数，不是论文报告的实际调用、计费或 token 统计，重试/失败请求未知。摘要及正文提到的 2,000 次 LLM 查询属于在线装箱实验，不能用作 FSSP 成本。论文给 TSP/FSSP 局部搜索上限 1,000 次迭代、每个实例最多 60 秒，并称实验框架在单 CPU i7-9700 上运行；这是时间上限及硬件描述，不是实测平均延迟。FSSP 专属 token、LLM 账单、总训练壁钟、单实例实际求解时间均未报告。当前 main 代码的 FSSP 类默认 time_max=30 秒、iter_max=1000，进一步说明不可混用后续代码参数与论文设置。

**验证与泛化：** 论文把 64 个随机适应度实例与 Taillard 测试基准分别描述，因而有独立基准测试证据；但这不是报告了同分布随机留出集的完整训练/验证/测试切分。训练实例固定为 50 作业、2–20 机器和 [0,1] 均匀处理时间，测试还覆盖不同规模及 Taillard 基准，属于跨来源/规模测试。正文六组 n=20、50、100，附录扩展到 n=20–200、m=5–20；未报告对原始实例重复去重核验、自然语言约束扰动、其他车间类型或生产动态数据的验证。可支持的泛化结论限于作者所测的置换流水车间、makespan 目标和 Taillard 实例，不应外推到有可选机台、工序跳转、换型、释放时间、交期、批次或实时插单的工厂任务。

**测试证据：** 论文作者报告了随机训练实例上的启发式适应度进化，并在 Taillard 测试集上与经典启发式及 PFSPNet 系列比较；表 3 六组中 EoH 的报告差距均为该表最低。附录扩大到 11 组 Taillard 实例，作者报告平均 gap 0.23%。这是论文中的作者实验结果，不是本次复跑；本次未安装或执行项目代码，也未运行排程。

**部署证据：** 未发现论文或所读作者代码提供工厂现场、MES/APS 集成、真实订单回放、生产上线或运行 SLA 证据。论文证明范围是基准实例上的启发式质量；不构成生产可行性或端到端排程成功率证据。

**迁移条件：** 若迁移到本项目，首先需保持任务与证据范围相符：固定机器路线、所有作业共享同一机器顺序、目标为 makespan，并有可比较的处理时间矩阵和足够的局部搜索预算。作为离线路线，应把生成出的启发式冻结后在独立持出实例上评估，报告种子、合法率、失败分母及完整生成/求解成本；不可把这类静态规则生成算作运行时 C。若改为模型运行时调用并返回具体作业顺序或机器/批次/等待选择，则重新追踪模型、工具和解码器的实际决定边界。存在可选机台、批次、换型、释放/交期约束或动态插单时，需重新定义问题并验证规则与邻域，当前论文结果不能直接迁移。

**失败方式：** 扰动规则可能带随机性；论文未报告多次独立进化的方差或随机种子敏感性。；受限邻域可能排除需要移动其他作业才能到达的改进排列；搜索质量受固定 swap/insert 算子及时间上限影响。；论文未报告非法程序/异常/失效候选的数量及质量统计分母。后续 main 快照将异常或少于两个待扰作业判为 INVALID，并把超过五个的索引截为前五个；该行为不能直接归到 2024 实验版本。；示例启发式用随机机器子集、权重和扰动因子；不同调用可能产生不同邻域与结果，实际方差未报告。；后续 main API 与旧 v0.1 接口不同，当前 main 文件无法单独证明论文运行时所用代码、参数和数据完全一致。；置换流水车间结构不覆盖替代机台、批量加工、换型、等待决策及动态工厂约束。

**未知：** GPT-3.5-turbo 的精确快照、API 日期、提示参数、温度及完整 FSSP 提示/响应日志未报告。；FSSP 实际 LLM 调用数、token 数、费用、失败请求和端到端训练壁钟未报告；1,010 仅是按论文流程推算的名义请求数。；独立进化重复次数、随机种子、方差/置信区间以及 EoH 与基线是否采用完全一致运行预算未报告。；原始可行率、异常候选数、修复或回退策略及失败质量分母未报告；当前 main 快照的处理逻辑不能替代原论文版本证据。；未报告训练实例与 Taillard 实例的逐实例去重核验，也没有独立同分布开发集说明。；GitHub 当前 main 是后续 API/代码快照；v0.1 固定文件访问失败，原论文实验对应提交 SHA、依赖版本及数据文件版本仍未知。；未报告任何生产现场数据、部署延迟、约束扰动或实际工厂收益。

### S-03 · Q-02 · SMT2020 / PySCFabSim fixed upstream

[官方模拟器下载页，L56-L57 列出 SMT2020 Datasets；未读取数据归档](<https://p2schedgen.fernuni-hagen.de/downloads/simulation>)（访问/取证日期：2026-10-12）；[L0-L20、L26-L35、L39-L48：RefactoredVersion2025 软件发布及关联 GitHub 仓库](<https://zenodo.org/records/15088815>)（访问/取证日期：2026-10-12）；[L131-L160：公开分支标签、目录及 README 入口](<https://github.com/david-dd/PySCFabSim-revised/tree/RefactoredVersion2025>)（访问/取证日期：2026-10-12）；[L38-L48、L133-L153：dispatch manager、实例计数器及注释掉的 CQT 处理](<https://raw.githubusercontent.com/david-dd/PySCFabSim-revised/RefactoredVersion2025/simulation/instance.py>)（访问/取证日期：2026-10-12）；[L0-L18、L26-L33：作者列出的 FIFO/CR 复现实验入口与 SMT2020 来源](<https://raw.githubusercontent.com/david-dd/PySCFabSim-revised/RefactoredVersion2025/README.md>)（访问/取证日期：2026-10-12）；[L22-L31、L42-L47、L113-L123、L293-L323、L324-L407、L488-L513、L629-L642：CQT 控制方法、模拟设置、报告指标与结论](<https://informs-sim.org/wsc20papers/194.pdf>)（访问/取证日期：2026-10-12）；[“锁定来源与计数”“投料版本并非完全相同”“必须保留的语义边界”中 CQT、快照、校准条目](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/semantics-20261009.md>)；[route_definitions、ownership_fields、comparison_required 与 limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[按固定 SHA 打开的原始文件 URL 未能由浏览工具取回（cache miss）；此失败不代表文件不存在](<https://raw.githubusercontent.com/david-dd/PySCFabSim-revised/ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1/simulation/instance.py>)（访问/取证日期：2026-10-12）

**机制：** SMT2020 路线资料可以包含 CQT 起止步和时间窗字段，但字段存在不等于基础模拟器实际约束它们。WSC 2020 论文明确说明：数据集 2 已含 CQT 路线信息，当时没有相应生产控制逻辑；论文另外为 AutoSched AP 加入 QTCR、QTS 派工策略，并研究结合 lot stopping 的控制。QTCR 按 CQT 截止时间与剩余加工时间排序；QTS 依据长时间模拟得到的 flow factor 分配 CQT 时间窗到中间工步；stopping 达到工具组阈值时阻止新 lot 进入相关 CQT 段。论文实现是在 AutoSched AP 11.3.0 中以 C++ 定制，不是已证实包含在基础 PySCFabSim 中的控制。公开版 PySCFabSim `simulation/instance.py` 中有 CQT 违规计数器字段，但 dispatch 内相关处理被注释；实际 `dispatch(machine, lots)` 接收已选好的机台和 lot 后执行占用、计时并发出事件。因此，不能用字段或计数器存在来声称基础版执行了 CQT 硬约束。

**实际决策边界：** 此来源没有语言模型或学习模型的决策实验。WSC 的 BASE、QTCR、QTS 和 stopping 是固定程序策略，具体优先选择由派工算法作出；按本项目口径属于算法/程序安排，不能归为模型 B 或 C。若未来模型选择 QTCR/QTS 或阈值，再由派工算法形成 lot/机台/批次/顺序，则是有条件的 C；若要计为 B，必须核验模型是否亲自给出项目要求的具体排程动作及其等待选择，且解码器、机台分配、组批和回退没有暗中补排。离线编写派工规则是独立的离线生成路线，不自动算作 C。

**实验条件：** 论文使用 SMT2020 Dataset 2：低产量高混合工厂，10 种产品、每条路线 242–583 步、105 个工具组和 913 台设备；含返工路线、setup、批处理、级联、设备故障及时间/计数 PM，每 lot 25 片，按每产品每周 1,000 片投料，总计约 400 lot/周，约 2.5% hot lot。默认设定有 274 个 CQT 段；另在两个光刻工具组添加 167 段形成 441 段复杂设定。基线 BASE 按 lot 优先级、最小 setup、CR 排序；扩展策略把优先级和 setup 放在 QTCR/QTS 之前，之后再用 CR；批次以策略先选 lot 并在可行时填充，满足最小批量。首组实验为 3 种派工×2 种 CQT 设定×10 次独立重复，共 60 次；第二组针对复杂 CQT 和 stopping 阈值，共 90 次、每组合 10 次。每次仿真两年，前一年 warm-up；论文明确 ACT 和准时率排除 warm-up，但其他指标如何处理 warm-up 未逐项说明。论文报告吞吐量、ACT、准时率，以及 CQT 违例率和超过 1/2/4 小时的违例率、平均违例时长和平均提前量；CQT 违例率分母是完成 CQT 段的 lot 数，并非所有投料 lot。默认、无 stopping 时，作者报告总 CQT 违例率 BASE 17.5%、QTCR 9.4%、QTS 9.3%；对应生产 regular lots 吞吐量约 3802、3802、3799，ACT 约 37.7、37.5、37.7 天。复杂设定下同一汇总违例率为 21.1%、13.6%、13.8%。这些是论文作者报告的 AutoSched 模拟结果，不是本次复跑结果。

**成本与时延：** 论文未报告仿真总计算成本、单次模拟壁钟时间、每次派工延迟或失败次数；也没有模型调用、token 或推理成本。AutoSched AP 11.3.0 是论文注明的商业仿真引擎，CQT 策略用 C++ 定制，但不能据此推算本项目适配成本或延迟。

**验证与泛化：** 论文证据是作者在指定仿真设置上的重复实验：每因子组合 10 次独立重复、两年仿真并含一年 warm-up；未设训练/开发/持出测试集，研究对象也不是学习模型，故模型版本、训练数据、模型合法率均不适用或未报告。作者提到 Dataset 1 的初步实验，但没有给出可同 Dataset 2 直接比较的完整结果。公开 GitHub README 列出 FIFO/CR 复现实验脚本，但脚本或测试存在本身不是运行证明，本次没有执行。指定内部脱敏审计将源码/输入完整性与数值校准分开：其报告为输入完整性通过、官方数值校准未通过；这属于本地审计报告，不是 AutoSched 对照复跑，也不构成独立的官方数值等价证据。内部报告还指出规范化周期 order 与官方 options 指向的 SL/WIP 投料文件语义不同，投入量吻合不能推出准时率、CR 或逾期统计可直接对齐。

**测试证据：** 仅有论文报告的作者模拟实验：两组分别 60 次和 90 次，共 150 次作者报告的 AutoSched 实验。没有本次复现，没有读取原始运行明细，没有运行 PySCFabSim、工厂模拟、求解器或新排程。字段/代码审阅与模拟结果证据分开记录。

**部署证据：** 未见真实工厂生产、在线部署或生产控制日志证据。论文结论限于模拟研究；PySCFabSim README 描述复现实验入口不构成投产证据。

**迁移条件：** 迁移到固定上游前，至少需核对被测文件确属目标 SHA、Dataset 版本、CQT 路线和投料时间/交期语义，并明确是冷启动 WIP 还是可恢复状态。内部报告记录初始 WIP 为 2,156 个 lot、每 lot 25 片，WIP 可见字段含 lot/产品/优先级/片数/START/CURSTEP/DUE，但不含在制剩余加工、设备 setup、绑定历史和维护剩余等完整恢复信息；有 433 个初始 lot 已处于 CQT 起止步之间，而其历史 CQT 起始时刻未知，不能补零作为合规证据。若要转移 WSC 结果，还须在同一投料、初始状态、引擎、规则、随机设定、仿真时域及统计 warm-up 下对齐结果和违例分母。内部审计明确区分输入哈希完整与官方数值校准；在数值对照未通过前，不宜把数据/源码完整性表述成 AutoSched 等价或完整 CQT 硬约束验证。

**失败方式：** 把 CQT 字段、CQT 计数器或研究论文标题当成基础模拟器已实施并通过 CQT 硬约束的证据。；把 WSC 的 AutoSched C++ 控制器模拟结果转写为 PySCFabSim 或本项目模型的实证结果。；内部周期投料与官方 SL/WIP 输入在交期等方面语义有别；只对齐投料量会误读准时率、CR 或逾期指标。；冷启动 WIP 中途 lot 的历史 CQT 计时、机台绑定和完整设备状态未知；将缺失状态设为零可能制造虚假的可行性或校准结果。；高优先级规则先于 QTCR/QTS；CQT 优先级不会在所有 lot 冲突中压过 hot-lot 优先级。Stopping 阈值过严还可能牺牲产能，例如复杂设定中 BASE 的小阈值场景 ACT 明显升高。；将脚本、测试或论文作者自述误报为本次运行成功、完整快照恢复验证或真实生产验证。

**未知：** 公开标签 `RefactoredVersion2025` 到任务指定完整 SHA `ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1` 的精确映射；精确 SHA URL 访问失败不能证明文件不存在。；AutoSched 定制 C++ 源码、逐次随机种子、每次运行失败/剔除记录，以及违例统计对 warm-up 的处理细节。；PySCFabSim 与 AutoSched 在完整逐事件轨迹、批成员、机台选择、PM/故障和随机抽样方面的数值等价性；内部报告明确未通过官方数值校准。；原始 WIP 是否在项目其他环境配有完整 checkpoint/restore 实现；指定 WIP 文件本身不具备报告列出的完整恢复状态。；WSC 策略复用到目标项目时的具体工具参数、流量因子、阈值调优过程、运行成本与决策延迟；论文未逐项报告。；没有与该来源对应的语言模型版本、提示、调用策略、合法率、模型训练/开发/测试拆分或 B/C 对照实验。

### S-04 · Q-02 · Photolithography CP and discrete event simulation；核查日期：2026-10-12。

[§§3.2.1、4.1–4.4、5.1–5.3、6.1–6.2、7；开放论文 HTML](<https://link.springer.com/article/10.1007/s10696-026-09666-5>)（访问/取证日期：2026-10-12）；[§§2.1–2.3、3.1–3.4；PDF pp. 3–10，尤其是仿真重复、吞吐和 layer/reticle change 偏差](<https://informs-sim.org/wsc22papers/351.pdf>)（访问/取证日期：2026-10-12）；[仓库 landing page 与 README；只读仓库说明和目录名，未打开或导出任何实例文件](<https://github.com/paatrickd/Lithography_scheduling_problem_instances>)（访问/取证日期：2026-10-12）；[route_definitions、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C07

**机制：** 目标论文提出的是传统约束规划（CP）与离散事件仿真（DES）组合，不是语言模型排程。任务是 Nexperia 某前端晶圆厂光刻区的异构并行机调度：作业有机台资格限制、与机台和前序作业相关的 setup、独占 reticle 及按 layer 配置的 pod 资源；生产时间、setup、设备故障和停机具有随机性，作业动态到达。作者在每次重排时从仿真当前状态抽取一个有限期、确定性的静态问题 PSPRP，再由滚动时域执行其中一段并周期性重排。论文的目标是加权平衡 performance efficiency（PE，吞吐相关指标）与平方迟交总量；α 调节吞吐和交期目标权重。

CP1 以 optional interval variables 表示符合资格的作业—机器组合，sequence variables 决定机台顺序，cumul constraints 控制 reticle 的同时占用以及每个 layer 可并发作业数不超过其 pod 数。它不逐作业指定 pod，只保证容量可用。CP2 则为作业—机器—pod 组合建立区间变量，并显式为机台、reticle、pod 建立顺序约束；可以在跨机台移动的资源使用间加入缓冲时间 t_buf。目标论文假设现实中 reticle 和 pod 转移时间可忽略，但把 CP2 的缓冲作为降低随机执行冲突的手段。仿真器在机台空闲时采样 setup 和加工时间，作业完成后按设备概率抽样故障并采样停机时长。当前控制基线把人工规则确定化；其它基线包括 FIFO、EDD、LPT、SPT、ATC、ATCS、WMDD。以上是作者论文自述及方程/算法描述，并非本次运行代码所得。来源：Springer §§3–5、7；WSC 2022 §§2–3。

**实际决策边界：** 按指定 rubric 的定义，本研究没有要归为项目 B 或项目 C 的 LLM：未报告语言模型、模型版本、prompt、工具调用、模型输入输出或生成后处理。CP 求解器是具体排程的决定者。CP1/CP2 formulation 将作业机台分配、作业顺序和排程时点作为优化变量，由 IBM CP Optimizer 在约束和目标下求解；所以它不是模型直接输出 lot/机台/顺序的项目 B，也不是模型调用构造器或选策略参数而算法随后排程的项目 C。它属于 rubric 中需单列的 formulation/solver 类方法；“用了工具”或“用了算法”都不能把它改判为本项目 C。若只描述决策粒度，CP 求解器确实产生具体分配与排程，但执行者仍是求解器，不是语言模型。

每轮重排的输入边界也限制了谁在决定什么。系统快照提供当时已到达且尚未完成的作业和机台状态；未来作业到达时间未知的建模假设下，当前轮只排已在场作业。快照时停机的机台在整个规划期内排除，且假定当前可用机台在规划期内不会再停机。正在加工或 setup 的作业按中位加工/setup 时间估计结束状态；若已耗用时间长于中位数，则按本轮立即完成等规则处理。所有当前可排作业纳入求解，但只承诺部署在规划期 h 内开始的作业；之后的状态由下一轮重排更新。由此，CP 模型、CP 求解器和滚动时域控制器共同决定排程，仿真器负责状态与随机过程；没有 LLM action mask、decoder、repair 或解析失败 fallback 的证据，也不应自行假定不存在于未公开实现的细节。来源：Springer §§3.2.1、4.1–4.3；分类边界依内部 rubric。

**实验条件：** 研究任务为单一 Nexperia 前端 fab 光刻区域，不是整座 fab 的端到端生产调度。区域入口由上一制造步骤的 track-out 到达触发；光刻区内部包含等待队列、13 台在实验开始时可用的设备、资格约束、reticle/pod 资源、加工/setup、设备故障及停机；下游其他工序没有作为 DES 中的完整生产线建模。全厂 global due date 被折算成光刻工序 operational due date，采用历史总 cycle time 除以工序数并假定每道工序等时长，作者承认该假设可能过简。旧版 WSC 论文描述了四个月 MES 数据作为到达、配方资格、加工、setup 和停机等输入来源；目标论文未给出该数据的独立留出期。

计算实验分两类。静态确定性分析使用同一 fab 的五个真实月度实例，每例覆盖一个月，最大实例有 823 个 job；规划时域 h=5400 秒（1.5 小时）。CP1/CP2 的静态公平比较令 CP2 缓冲为零；求解时限报告为 60、120、240 秒，以及用于观察求解器上界/潜在质量的 3000 秒。动态随机分析模拟 48 小时，重排每小时一次，共 48 个调度事件；规划时域仍为 1.5 小时。开局队列有 321 个 job，期间另有 1371 个 job 到达，输入到达时间固定为历史实况；开始时有 13 台可用机台，论文称到达约每小时 40–50 个、队列约 200 个。动态分析每实例 30 次仿真重复，报告 95% 置信区间；α 测试值为 0、0.5、0.8、0.99。CP2 缓冲候选 t_buf 为 0、300、1200 秒，经初步冲突实验选 1200 秒用于后续实验；作者也称未对参数作更完整敏感度分析。

基线含 CP1、CP2、现场当前规则，以及 FIFO、EDD、SPT、LPT、ATC、ATCS、WMDD。ATC/ATCS/WMDD 参数按论文给出的默认值；当前规则由操作员访谈后固定化，按 24 小时生产目标、每 4 小时的 layer-to-machine 分派及 hot job/reticle/setup/EDD 优先序运行。目标论文使用 IBM ILOG CPLEX Optimization Studio 20.1.0.0 的 CP Optimizer，C# API 接入以 .NET Core 3.1 与 C# 8.0 开发的 CSSL 仿真器。无语言模型版本、训练/开发/测试拆分、prompt、token、采样温度、LLM 样本数或原始/修复后合法率；这是传统优化研究，不应将这些“不适用/未报告”补成模型实验事实。公开仓库 README 仅说明公开实例类别及其论文用途；本核查没有查看实例原始工厂明细。

**成本与时延：** 目标论文的计算平台报告为 Intel Core i5-8600K 3.60 GHz、16 GB RAM；启发式以 .NET Core 3.1/C# 8.0 实现，CP 使用 IBM ILOG CPLEX Optimization Studio 20.1.0.0。作者经与现场人员讨论，将最多 4 分钟视作可接受的计算时间，并比较 60、120、240 秒求解表现；3000 秒仅用于静态实验探索潜在质量/界限，不应误报为每小时滚动决策的实际耗时。动态系统每小时重排，论文没有给出每次 CP 调用的平均/尾部 wall-clock、超时率、全 48 小时累计求解时间，或仿真运行与数据装载合并后的端到端成本。因此 4 分钟是可接受上限陈述，不等于测得的生产延迟保证。

WSC 2022 对同一研究线的先前 DES 验证单独报告：同样的平台上，30 天模拟运行约 2 秒，300 次重复约 10 分钟，但这个数值明确不含 MES 数据整理和载入，并且对应的是校验数字孪生的工作，不是目标论文中 CP+滚动时域的完整仿真成本。两篇文章研究对象、作者线和 Nexperia 背景相连，不构成另一团队对求解/仿真延迟的独立复现。论文没有美元成本、工程接入维护成本、求解器 license 成本、容错/重跑成本或总失败成本。没有 LLM 调用，所以输入输出 token、模型 API 延迟与费用不适用；不得把 DES 的仿真秒数当成 CP 排程器的时延。来源：Springer §5.1、§6.1；WSC 2022 §3。

**验证与泛化：** 目标论文 §5.3 说作者以一段真实 30 天生产期作为参照，做 300 次独立仿真重复；每次重复采用与真实 benchmark 相同的初始条件。作者选择 300 次的理由是希望 95% 区间半宽较小。校验指标包括吞吐、layer/reticle change 次数、总平方迟交及 overall equipment efficiency，但目标论文明确把详细结果指回 Deenen 等 2022 年的 WSC 论文，没有在 2026 论文重复完整校验数据。这里的 300 次是仿真验证次数，不是 CP 解的独立实例数或模型训练样本数；随机种子、common random numbers、每次重复的确切状态轨迹和 CI 数值均未报告。

同研究线 WSC 2022 的详细历史结果显示，真实观测与模拟吞吐的日均值差约为模拟低 0.15%，标准差模拟低 6.60%；但 setup 行为的代理验证存在显著偏差：reticle change 均值低 49.28%、标准差高 13.97%；layer change 均值低 25.98%、标准差高 5.73%。作者解释模拟 dispatcher 总是遵循固定规则，而现实操作员有时按位置便利或免 setup 等原因偏离规则，因此仿真把 lot 按 reticle/layer 聚得比现实更多。论文又称 performance efficiency 接近真实值，但 operational/rate efficiency 单项略有偏差；总平方 lateness 略优于真实观测，主要与 earliness 偏差相关。故“吞吐校准接近”不等于 setup 行为完整校准；setup 时长依机器、setup 类型和月份由经验分布抽样，也不等于经过独立时期验证的政策行为。

验证器是作者自身构建的历史数据驱动 DES 与真实历史生产观测之间的比较，目标论文还提到案例利益相关者认为 performance efficiency 和平方迟交偏差可接受。这不是独立团队验证，也不是其他 fab/时间段的前瞻性 holdout，更不是新 CP 控制器在运行产线上的 A/B。WSC 2022 与 2026 论文同属 Deenen 等同一研究线且指向同一 Nexperia 背景，不能作为独立来源叠加为多次外部验证。泛化证据限于目标论文的五个月度静态实例、一个 48 小时动态仿真场景及一个历史 30 天 DES 校验期；随机重复只减少对该输入快照和假设下的仿真抽样误差，不能消除初态/单工厂/人工行为模型的外推偏差。

**测试证据：** 论文提供的是模拟与优化实验的作者报告，不是本次亲跑。静态部分把五个真实月度问题实例交给 CP1/CP2，在固定 1.5 小时排程窗口和不同求解预算下看 schedule/目标值；动态部分在 DES 中执行 48 小时滚动控制，CP 每小时重排，并以当前实践、FIFO、EDD、SPT 等为比较对象，报告 30 次仿真重复和 95% 区间。评价使用 performance efficiency 和平方迟交等目标；附加对 72/96 小时 dispatching 测试称排序趋势相近。CP2 的缓冲先在 0、300、1200 秒上按 reticle/pod 冲突数做初步选择，再把 1200 秒用于后续实验；这构成作者内部参数选择证据，不是跨 fab 外部校准。作者报告动态结果中 CP2 相对 CP1 更抗随机资源冲突，且在同等平方迟交条件下吞吐改善较高；EDD 对纯迟交可更优，因为可在机台空闲时立即派工，不必等下个整点。

分母与覆盖范围必须谨慎：目标论文未提供针对不同提示/模型的可行率；没有 LLM 原始合法率或 repair 后合法率；也没有训练/测试集意义上的 held-out 泛化。静态五实例和动态仿真是算法效果对比，不等同于独立工厂测试。论文没有报告因 CP 超时/无解而被剔除的重复数、失败输出的回退方式或对失败实例如何计入均值；不能只按成功求解的数字推断端到端可靠率。WSC 的 300 次 DES 校验是在固定真实初始状态下重复随机过程，不能当作 300 个独立工厂案例。

**部署证据：** 论文描述的用途是离线评估，以免新排程控制影响正在运行的生产。仿真模型以真实 MES 历史输入和历史 dispatching 观察作参照；目标 CP1/CP2 在仿真中部署并运行，但未报告把它们接入生产 MES、让操作员实时采用其结果、或执行真实产线 A/B 的证据。因此可说存在作者报告的真实生产历史校准和仿真内控制比较，不可说已证实 CP 提升了实际上线 throughput。WSC 2022 也只验证数字孪生对某段已发生生产的复现，非未来生产部署；同研究线内两篇文章不构成独立生产验证。

**迁移条件：** 若迁移到另一光刻区或另一 fab，需重新取得并校验该地点的作业到达、设备资格、machine-reticle 加工时间、按机器/setup 类型/时段区分的 setup、设备故障与停机数据，另需重建 reticle/pod 容量、产品 routing 与 operational due date。还要核对本地人员的实际派工习惯：原模型把操作员变化简化为固定规则，而已报告的 change-count 偏差显示这种近似会系统性影响 setup 分布。规划时域、每次重排周期、α、t_buf 与辅助资源稀缺性需按当地 WIP/随机性重新设定，不能直接复制 1200 秒缓冲或一小时重排。作者认为资源冲突风险较高（辅助资源少且生产随机）时 CP2 缓冲有用；这只是需当地确认的条件性建议。五个月度实例和一段历史校验不足以证明跨工厂、跨工艺层、跨班组或节假日/极端故障期泛化。

**失败方式：** 仿真把当前人工控制随机性去掉并固定化，会高估 lot 按 layer/reticle 聚类程度，漏掉人员便利、物理位置和免 setup 等实际选择。；快照时停机的机台整段规划期内都不排，而运行期中的 up 机台假定规划期内不再故障；真实设备状态若偏离假设，会改变可行分配与完工时间。；未来到达作业在本轮静态 CP 中不参与求解；重排周期若太长，新到达的紧急 lot 可能等待，论文明确指出 EDD 即时派工对纯迟交有优势。；CP1 只按 layer 的 pod 数做并发容量约束，不为 job 指定某个实体 pod；随机部署会发生 reticle/pod 冲突。CP2 通过实体资源顺序与缓冲减轻风险，但结果依赖所选 t_buf。；global due date 均摊至各工序的等时假设可能失真；作者称其是为了仿真贴近现场当前做法，而非经各工序真实时长全面验证。；吞吐均值贴近历史观测不能保证 setup、迟交、OEE 每个分量都校准；WSC 报告的 change-count 与 earliness 偏差可影响对不同调度器的排序。；有限求解时限下的终止、无可行解、异常/超时处理和是否存在回退未报告；不应推断生产场景下所有周期都稳定交付完整排程。

**未知：** 目标论文没有语言模型、模型版本、提示、采样参数、训练样本、token、调用数或人机交互反馈信息；因此不存在可比较的 B/C 模型实验证据。；求解器在每个动态重排事件的平均、P95、最坏 wall-clock，48 小时累计 CPU、各预算下的超时/无解数、最优性差距与求解失败计数未报告。；300 次动态仿真的随机种子、是否使用共同随机数、各replication完整初态快照/随机变量轨迹和逐项95%区间数值未在目标论文重报；WSC 详细图表只展示其中部分轨迹。；真实生产输入 MES 的准确日期跨度、分布拟合后的独立时间留出验证、数据清理细节、异常值规则和每种 setup 类型样本数未在本次可访问正文中逐项确认。；直接 setup 时长校验误差（按机器、前后产品/recipe 或 setup 类别的误差分布）未见报告；现有 WSC 定量偏差是 reticle/layer change 数量等间接代理指标。；是否由与作者无关的第三方、另一 fab 或前瞻性现场团队独立验证仿真器或 CP 策略：未发现证据；两篇指定论文为同研究线。；公开 GitHub 仓库 README 说明的是实例目录而非作者求解器实现；目标论文称算法代码可按需提供，本次未获得代码，也未读取任何公开实例原始工厂明细。；静态问题的所有实例逐项规模/约束统计虽由论文表格提供，但本次重点记录公开正文中明确写出的五个实例、每例一月及最大 823 jobs；没有查看仓库内实例文件以补充或核验规模。

### S-05 · Q-03 · myharness workflow runtime

[L35-L127](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/codex-workflow.mjs>)；[L1-L279](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/codex-workflow-runtime.mjs>)；[L1-L109](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/scripts/lib/workflow-schema.mjs>)；[L66-L128; L142-L159](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/plugins/harness-core/workflows/codex-workflow.README.md>)；[L67-L259](<__LOCAL_HOME__/Downloads/大模型训练营/myharness/tests/harness_tools/codex_workflow.test.mjs>)；[route_definitions](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)；[CLI reference: --ephemeral (around lines 2287, 2353-2361); codex resume (L3003-L3006)](<https://learn.chatgpt.com/docs/developer-commands?surface=cli>)（访问/取证日期：2026-10-12）；[codex exec --output-last-message behavior (around L981)](<https://learn.chatgpt.com/docs/non-interactive-mode>)（访问/取证日期：2026-10-12）

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C08

**机制：** 源码显示这是通用的 JavaScript 工作流适配运行器：入口按 `--name` 或本地 `--script-path` 读取脚本及参数，然后以 `compileWorkflow` 包装并运行受信任脚本。脚本通过注入的 `agent(prompt, options)` 发起模型调用；backend 使用 `spawn` 启动独立的 `codex exec --json --ephemeral` 子进程，将适配提示和任务 prompt 写入 stdin，按需传入模型、`--output-schema`、sandbox 和联网选项。默认 `-a never`、`read-only` 与开启联网可在入口和 backend 控制流中看到；实际模型若未显式选择，则沿用 CLI 配置，运行记录的模型字段可为 null。这里的“并发”是 JavaScript Semaphore 对 Agent 子进程数的限制，不是模型内部并行度：排队任务在槽位释放后启动，嵌套 `parallel` 仍共用该 Semaphore；`Promise.all` 保留输入顺序，`pipeline` 允许快输入先进入下一阶段。入口默认 concurrency=3、maxAgents=64、timeoutMs=300000，且校验三者为正整数。Agent 调用计数在并发排队前递增；超出 maxAgents 会设置不可被脚本 try/catch 消除的 fatalError，最终取消 pending 工作并使整次运行失败。每个子进程的超时触发本地 stop：向进程组发 SIGTERM，1 秒后安排 SIGKILL；退出清理时若仍有 stopReason，再杀残留进程组。workflow 的 SIGINT/SIGTERM 则通过 AbortController 传播到 backend；排队项能从队列移除，运行中的 Agent 终止，runWorkflow 等待 pending promises 收束后写出取消状态。普通 Agent 失败或单 Agent 超时会被包装为 null 弃权；配置/schema 错误、调用总预算越界、脚本异常和用户取消则进入整次运行的失败/取消路径。证据范围：入口 L35-L127，运行时 L13-L35、L49-L188、L191-L279；README L93-L128说明接口与无跨进程续跑声明。

**实际决策边界：** 这五个文件描述的是调用编排、严格输出格式检查和结果归档；没有出现工厂状态、lot、机台、批次、工序、排程构造器、候选动作生成器、求解器或物理提交接口。因此，仅凭这个运行时不能判定具体调度决策由模型还是算法完成，也不能把“用了 Agent”“输出 JSON”自动归成项目 B 或 C。适配层允许被加载的工作流脚本向模型传任意 prompt，并接收文本或符合传入 schema 的对象；schema 子集负责格式/约束校验，不包含排程合法性、优先序解码或修复逻辑。实际脚本可能要求模型明确选 lot、机台、批次、顺序和等待；若有此证据且程序只机械校验/编译，才符合 rubric 的 B 归属条件。另一种可能是脚本让模型选择构造器或策略参数、随后由算法安排，才可能符合 C；若模型离线生成规则或程序，则按 rubric 独立归类。现有适配文件没有证实这些调用链中的任何一种，也未提供实际选择字段、非法输出回退或候选截断规则。README 自称这是 M0.5 外部检索运行器且不替代排程领域调研；该描述反而说明不能将运行器名称或 Agent 调度能力直接作为本项目 B/C 的实证。实际加载脚本内容、其输出解析和是否连接真实调度执行链仍未知。

**实验条件：** 本任务是静态代码审读，不是排程实验或模型评测。未启动运行器、模型、测试、工厂模拟或求解器。指定源码没有提供模型固定版本、模型提示的具体业务内容、排程任务规模/约束、基线、实例来源、样本量、重复次数、开发/训练/持出测试划分、调度合法率、调度质量分母或失败样本统计；这些均不适用或未报告，不能从测试名补全。可核实的运行配置只有适配器层默认值和可覆盖参数：默认三并发、每次运行最多64个 Agent 调用、每次 Agent 300000ms；这些是通用执行控制，不是排程实例规模或模型任务预算。测试文件定义了若干 synthetic fixture 断言，包括并发峰值、输入顺序、失败弃权、预算、schema、超时和 SIGINT 取消，但没有显示本轮运行结果。README 记录作者称 2026-10-08 曾执行 Node/pytest 测试与 CLI smoke；这属于文档自述，不等于本轮复现，且没有在本任务中将该记录绑定到当前源码提交或哈希。OpenAI CLI 当前文档说明 `--ephemeral` 不持久化 session rollout 文件；这是 CLI 文档层面的语义，不能替代对该仓库具体版本、部署或历史运行的验证。

**成本与时延：** 调用数上限和并发上限都不是货币或 token 硬预算：maxAgents 限制本轮 Agent 调用总量，Semaphore 限制同时运行的子进程数量；代码中没有美元封顶、按价格估算后拒绝调用或整个 workflow 的总 wall-clock deadline。每个 Agent 有独立 timeout，默认 300000ms，包含其工具等待时间的说法见 README；runtime call 记录 startedAt/endedAt，但未见总体耗时汇总、分位数或成本折算。backend 从 `turn.completed` 事件提取 usage；只有 backend 成功返回且 schema 校验、可选字段恢复及原 schema 复验都成功后，runWorkflow 才将 response.usage 写入该 call 并把数值字段累加到 runtime.usage。因此失败、超时、缺 `turn.completed` 或最终 JSON/schema 不合法的调用，即使已经消耗 token，也可能没有进入 runtime 用量汇总；原始事件文件若已收到相关事件则可能留有单次记录。错误路径不会从事件日志重新核算失败调用用量。README 声称每 Agent 和总 usage 可见，但不构成完整费用账单；无调用级失败 token 的汇总审计结果、币种价格、真实请求/响应延迟及 CLI/模型版本数据。

**验证与泛化：** 结构化输出路径可静态追踪：调用前 `strictSchema` 拒绝不支持的关键字；adapter 将可选字段转成 required-but-nullable，并把对象约束设为 `additionalProperties:false`。模型返回后先解析 strict schema 输出，校验适配 schema，再仅移除由 adapter 增加的可选 null 并按原 schema 再校验；不合法 JSON 或违反 schema 不会被自动修复成合格结果。无 schema 时要求最终消息非空。backend 成功条件还包括子进程 exit code 为0、收到 `turn.completed` 且没有未恢复的错误/`turn.failed`；仅“进程成功退出”不够。Semaphore、调用预算与超时控制的静态实现可审读，但源代码存在并不证明运行正确。测试文件的断言范围包括 strict schema、并发上限及嵌套无死锁、失败弃权、预算不可由 try/catch 掩盖、CLI 事件/错误与 timeout、模型映射、SIGINT 活跃和排队 Agent 取消，以及脚本异常取消 pending 子进程。README 报告旧测试通过和一次真实 CLI smoke，仅作为作者记录。没有 CI 结果、当前提交身份、生产采样或跨模型/任务验证。本运行器通用性不能推广成排程合法性或质量保证。

**测试证据：** 未执行测试，也未声称通过。只读取测试定义：schema 测试覆盖可选 null 还原、enum/type/bounds 和 unsupported schema；runtime 测试断言嵌套 parallel 峰值不超并发值、顺序保持、失败 Agent 变为 null、调用预算超限不能被脚本吞掉；backend fixture 测试覆盖严格 schema/safe flags、非零或不完整事件、恢复中的错误事件、3秒 timeout 后进程终止、模型别名映射；入口测试定义五阶段 synthetic 执行、成本门、verifier 失败、SIGINT 取消活动与排队进程，并检查 runtime 状态；还有脚本异常时停止未等待的子进程并保留审计状态。测试代码中使用 fixture/stub 子进程的断言不是模型或生产实测。README 作者自述 2026-10-08 有20项 Node 测试、33项 pytest 契约测试通过及真实 CLI smoke；未在此轮执行，未对照 Git SHA 或 CI 记录，故仅作作者报告注明。

**部署证据：** 没有访问或读取运行产物、原始工厂数据、日志、密钥或私人数据；没有本轮生产/现场运行证据。README 自述的真实 CLI联网 smoke验证运行器的五阶段外部检索流程，并明确不等于完成排程领域调研；这是作者撰写的既往运行记录，不能等同本轮复现，也不能证明对实际工厂状态作出排程决策。源码显示默认 evidence directory 会保存 workflow events、runtime、result 与 Agent 子目录，但其存在只是实现设计，不证明某次运行成功写全或恢复成功。没有 source hash、已批准运行收据、真实运行版本和当前部署配置可将 README 报告绑定至这里审阅的精确源码。

**迁移条件：** 该适配器的并发、调用计数、逐 Agent 超时、schema 校验和失败归档机制可以作为一般 Agent 工作流编排特征描述；不能直接转移为某个排程任务的决策质量、合法率、吞吐或生产可靠性。要归入项目 B，须再看到实际加载脚本和 prompt/返回字段，证明模型明确决定 lot、机器、批次、顺序及等待，并核实 decoder、过滤、修复、解析失败回退没有暗中替其选排程。要归入项目 C，须证明模型调用构造工具或选择其策略参数，且由算法形成具体安排；仅把模型输出交给工具处理不足以满足该口径。若模型离线生成程序而运行时由规则派工，应按 rubric 单独列为 offline_generation。若出现优化模型和求解器，还须区分 formulation 路线。任何迁移比较都需补齐任务/约束、观察、版本/提示/预算、同任务基线、测试划分、合法率与质量分母，以及失败调用的成本统计。

**失败方式：** Agent 输出错误 JSON、违反 schema、返回空文本、进程失败或缺少 turn.completed 时会失败；普通 Agent 调用层将该错误记为 failed 并返回 null。；unsupported schema/model mapping 等配置错误在推理前被判为 fatal；maxAgents 超限设置全局 fatalError，即使工作流脚本捕获抛出的异常也会最终使运行失败。；Agent timeout 或 workflow 信号取消会终止子进程/进程组；SIGINT/SIGTERM 会取消排队与活动调用。若整个 Node 进程被强杀，代码没有跨进程恢复保证，可能只留部分事件文件。；token usage 仅汇总成功返回的 call.usage；失败、超时或 schema 不合格的调用可能已消耗资源却未进入 runtime 汇总。；严格 schema 只能校验声明的结构和约束，不代表调度物理可行，也不提供自动修复。

**未知：** 当前源码提交 SHA、文件内容哈希及部署运行的 Node/Codex CLI 版本未核验；README 里的日期记录不能替代版本绑定。；实际调用时载入哪个工作流脚本、实际 prompt/schema、具体模型快照、模型配置、模型映射与覆盖后的 concurrency/maxAgents/timeout 未知。；运行失败或 schema 不合格时的真实 token 用量是否可从未读的 CLI/平台账单取得未知；runtime 汇总本身不完整覆盖这些失败路径。；测试是否在当前代码版本通过、是否有独立 CI 证据未知；本轮没有运行测试。；除指定五个源码/文档/测试文件外，myharness 其他模块是否实现单独恢复机制或连接排程系统未知；发现记录只提示通用运行器与调度控制器在已读材料中未见调用关系。；没有已批准的运行摘要或源码收据来证明当前版本被生产使用；质量、效果和实际耗时均未报告。

### S-06 · Q-03 · Current B/C scheduling chains；截至2026-10-12。本次只读指定工程源码、白名单发现记录和两份已批准摘要；没有运行测试、工厂模拟、求解器或模型，也没有读取原始工厂数据、运行明细或 artifacts。

[main L16-L73、L82-L110、L141-L202](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/host.py>)；[deadline_contract L13-L27；main L30-L82](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/outer.py>)；[restore L8-L36](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_budget_extension_v15/restore.py>)；[main L16-L29、L51-L105、L164-L224](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/host.py>)；[_dependency L16-L34；TASK_TEXT L65-L90；Interaction L146-L189、_dispatch L434-L510](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/interaction.py>)；[_field/_task/_array L133-L197；DeltaAssembly L200-L361](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/B_candidate_paths_v14/workflow/B_delta_assembly.py>)；[compile_plan_delta L118-L270](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/plan_delta.py>)；[DeltaSession L92-L159、_execute/handle/export_evidence L200-L299](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/delta_session.py>)；[build_problem L115-L231](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/observation.py>)；[_solve_constructive_plan L19-L83；solve_constructive_plan L86-L103](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/constructive_tool.py>)；[verify L26-L94](<__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/src/smt_fullfab/recovery_check.py>)；[L3-L15、L17-L57、L59-L98](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/B_1h_results_efficiency_and_next_budget_20261012.md>)；[L3-L7、L9-L34、L59-L80、L84-L104](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/internal-sources/ABC_1h_plan_comparison_20261012.md>)；[sources、negative_findings、open_questions](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/scope-search/agents/0005/result.json>)；[route_definitions、ownership_fields、comparison_required、limits](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/inputs/route-classification-rubric.json>)

**后续核验提示：** 下面是提取阶段的原记录，不代表所有细节已确认。若与后续核验冲突，以关键论断段的采纳范围为准。关联：R2-C09

**机制：** 静态调用链是 V15 outer → V15 host → V14 `Interaction`，不是由路径名直接推断的旧 B assembly 路线。outer 校验冻结 manifest 与 host 指纹，计算软、硬截止时间，启动唯一 host 子进程，并将 `automatic_retry` 固定为 false；host 再核验运行源码、前序输入与可执行文件哈希、申请串行锁并创建独立续作段。它先调用 V15 `restore`：核对契约中各引用的 SHA、已认证沿革、源文件和认证退出码；以保存的 bootstrap 重建 V14 `Interaction`，绑定上次模型证据、执行停止点与提交回执，逐项重放当前计划的原始记录、prompt、schema、输出与响应，并要求重建证据摘要一致。该恢复函数明确返回零模型调用、零物理推进、协议未改变，且将可重放的当前计划索引限定为 1288、1289。随后 host 另走 `physical_resume.restore`，要求物理时钟与合同中的续接时刻、恢复停止时间相等，且物理 bootstrap 与 Interaction 输入一致。恢复成功只建立继续执行的状态，不代表排程或完整窗口验收已经完成。

每轮计划由 `controller.bootstrap` 从当前物理状态形成观察，host 将观察及模型交互上下文交给外部 transport；源码配置为 gpt-6-astra、medium、单次超时600秒。host 保存 prompt、schema、raw output、调用结果和哈希，再由 V14 `Interaction.handle` 处理。Interaction 以分页和精确查询提供公开资料；模型选择创建草稿、提交字段块、封存、请求检查、查询候选及最终 apply。V14 Interaction 的 `_dependency` 根据其自身文件目录读取同包 `B_delta_assembly.py`，校验固定 SHA 后执行；检查路径调用纯 `compile_plan_delta`，不是优化器或候选排序器。模型选择的候选还需经 host 的独立回放重建、检查锚点、`journal.verify()`，然后写入 commit intent；`physical.commit_once` 才调用公共 `commit_plan`，核对返回计划哈希和物理 trace 事件，再写 receipt、推进物理状态并记检查点。每次推进后创建新 bootstrap 和新的 Interaction，并把原交互证据、停止点和回执绑定到下一轮。跑至结束时还调用全窗物理审计。实际持久 journal 与 transport 的内部实现没有在本任务范围内逐文件细读，因此这里只报告 host 中可见的调用和控制顺序，不外推其未读实现细节。

**实际决策边界：** 依本项目 rubric，B 属直接排程：当前 V14 task text 明确由模型给出 lot/operation/visit 身份、机台、兼容批组、每台机完整顺序、`not_before`、hold、freeze/valid窗口与修订原因，并对现有待派任务和 hold 作明确保留、取消、替换或新增处理。组装器只接收模型明确提交的字段和数组；封存前要求所有路径（包括空数组）均有声明。它不填缺字段、不默认保留未提任务、不自动改开始时间、不补顺序、不排序候选、不修复或优化计划。`compile_plan_delta` 按显式任务处置形成完整计划：保留任务复制原值，新增和替换需完整字段；新增或移机要求模型给受影响机台列出完整顺序；对批次、资格、前序、冻结前缀、scope、时间窗及 hold 锚点进行拒绝式校验。编译器保留机台内明确顺序，不按优先级、机号或任务 ID 排序；其公共验证仍可拒绝模型选择，但没有替模型作可行替代。V14 包装层还把 `session_query` 限制为只读动作，虽底层 `DeltaSession` 自身保留 `check_delta/apply` 方法，当前 V14 实际装配检查路径是 `assembly_action`、显式 `check_assembly`、再由模型另一次输出精确候选 ID/hash 的 `apply`。

因此，B 的检查与组装属于机械支持，只有在实际模型输出确实包含所要求决定且调用归属可核验时，才算 B 的决定归属。V15 host 的 `policy.classify`、response admission、候选校验、回放和公共 commit 都是后置检查/留证；静态源码能支持该设计边界，不单独证明报告中某次运行的每个动作都由该版本模型产生。C 的边界相反：`constructive_tool` 将 problem、权重等参数交给 `build_incumbent`，固定采用 `gain_rate` 构造并产出具体 tasks；算法决定 lot/operation、机台、批组、顺序和计划前缀。获准摘要自述历史 C 有 46 次构造和 46 次模型明确 apply、使用过 5 组权重，因此若该报告描述准确，模型选择工具参数/候选，算法作具体安排，属于本项目 C。模型调用工具这个表象不把 C 变成 B；离线规则生成也未在此链中得到证明。

**实验条件：** 工程 prompt 将任务表述为 SMT2020 Dataset 2 全范围直接排程，规模913台生产机；优化优先级加权逾期 lot 时间，同时保留吞吐、避免 WIP 增长。观察源码输出当前机器状态与可用性预测、工序身份、路线前序、加工/占用和批次边界、setup、优先级/交期、冻结任务等公开信息；其中 residual 与后继路线按均值估算，lookahead 默认深度3，并显式标记未揭示的未来故障日历、维修时长、采样/返工结果和 RNG。未知未来事件不进入模型观察，已知未来 release/maintenance 尚未扩展，事件暴露后重观察。B host 配置 gpt-6-astra / medium、每次600秒，并在场景1701、3600仿真秒目标的续作上运行；独立比较报告所列 A 为经典混合臂，C 为模型调用经典构造工具臂。两份批准摘要是既有记录分析，并非本轮重跑；报告所述最终 B 共95次计划提交，A为47次，C为46次。摘要将三臂一小时结果归为同一开发对比，但也说明运行核、控制器和审计版本仍有差异，因此不是完全同版本的正式算法比较。

训练/开发/测试分离：这条工程记录没有报告模型微调或训练流程，不能据此填补训练数据、checkpoint、提示版本历史或训练/验证分隔。已批准报告称1701–1706已经使用，不可再标为未见测试集；1701的一小时结果是开发窗口，不是独立保留测试。样本与重复：只见单场景一小时的摘要结果，没有可用于估计模型内方差的重复设计；多次计划提交、派工数和调用数不是独立实例样本。基线：报告对 A、B、C 给出同窗口描述指标，但版本差异仍在；另建议加入固定参数 C-fixed，现有报告并未证明它已执行。合法性质量分母：获准摘要称B的完整物理、来源、机会审计通过，并称最后续作没有拒绝动作，但没有在本轮读取原始调用日志、逐调用合法率分母或审计构件，故不从最终排程成功推成所有原始响应都合法。外部对比、公开论文和公开代码没有在本任务中搜索或读取。

**成本与时延：** 所有成本数字均为批准摘要的作者统计口径，不是本轮复算。摘要称 B 整个开发沿革有1,362次模型尝试、已知输入加输出44,666,702 tokens、记录模型活动17.21小时；仍有3条历史调用用量未知，所以已知token和不能视为闭合总账。相同交互协议的V14+V15片段报告为779次调用、27,203,484 tokens和8.11小时活动；最后V15续作报告72次调用、2,282,280 tokens、46.32分钟模型活动，仿真时间从3445.778秒推进至3600秒，并新增9次计划提交。报告称此续作无调用失败、未知用量、拒绝动作或同一计划内规范化ID后的重复查询。以上是模型活动时间，不是服务端纯推理时间；累计墙钟还含准备、恢复、等待、审计和记录，不能简单相加或直接当成在线响应 SLA。报告还给出后期779次调用每次中位30.39秒、P95 78.83秒、每次提交平均9.74次调用，说明当前协议往返成本很高。

host源码设置600秒单次超时、660秒软截止前的调用准入余量、900秒收尾余量及外层30秒发布余量；每次新调用前检查硬/UTC截止、剩余日志字节及源文件身份。失败的原始 transport 不重跑同一索引，outer 明确禁止自动重试。host、outer与工具结果中货币字段为 null；报告也指出当前认证通道没有可核美元账单，不能把未知写为0或借公开API价格替代。已知调用成本、未知三条历史调用用量、累计资源和金额必须分别保留。没有可靠证据把整段24小时以上的开发沿革时间当作下一次从头运行成本，也不能由154秒续作的token强度线性外推八小时或二十四小时。

**验证与泛化：** 源码显示两层身份/校验边界：host 从 campaign manifest 对照冻结 runtime 文件、输入引用和可执行文件哈希；V14 `Interaction` 对四类观察/计划/状态/来源锚点绑定草稿和候选，装配包校验锚点、路径、序号、重复身份和字段类型；`compile_plan_delta` 再验证当前 observation、状态时钟、全scope、资格、批次、时间窗、冻结任务和机台顺序。编译结果明确标注未做物理验证、未认证模型归属、仍需公共 commit 与独立物理/来源审计。host 的 commit 前回放同一计划从起始交互重放所有原始输出，要求 prompt hash、记录 hash 和选择一致；随后公共 `commit_plan` 与物理 trace 回执被检查，advancement 后留检查点，末端执行 full-window audit。V15恢复检查的是特定已认证沿革及两个当前计划输出的忠实重建；通用 `recovery_check.py` 的用途则是精确物理 snapshot 恢复检查，源文件说明它不等于调度验收或继续运行，而且本轮没有调用它。

既有证据的强度要拆开：源码证明存在这些门禁和失败路径，不证明某历史执行确实走完、某 CI 通过或当前工作区源码哈希等于报告所述冻结树。获准摘要称B在0–3600秒窗口通过全物理、来源、机会审计，并做了token/指标复算；但其链接指向的原始 artifacts、日志、轨迹、manifest 和哈希清单按任务限制未打开，不能独立复审或绑定版本。质量泛化也受限：同一摘要说终点加权逾期10.0 lot·小时、完成1 lot、终末WIP2176；单个完成lot不足以证明长期吞吐或准时性。ABC摘要报告A/B/C的主交付指标相同而过程轨迹不同，且版本不完全一致；不能从这一小时作因果排名或长周期优越性推断。场景1701–1706已用，留出场景和多次重复需要另行登记。

**测试证据：** 本轮未运行测试或校验命令；任务明确禁止新增测试执行、仿真、求解或模型排程。源码中可见的是运行时断言、回放、哈希检查和拒绝分支，不是测试通过证明。`recovery_check.py` 定义了限时子进程精确恢复检查，但没有执行；其源码把范围限定为snapshot状态恢复，不认证调度接受或新续跑。前置发现记录说明之前只读检索了测试定义，并提醒测试函数存在不等于当前CI通过；它没有建立V15 host/restore的直接已通过测试映射。本次未打开测试文件，也未读取CI摘要，因此不能报告V15测试通过率、测试样本、覆盖率或测试版本。报告中对某次独立审计通过的陈述属于既有运行摘要，不可改写为本轮亲跑测试。

**部署证据：** 两份批准摘要自述：B在场景1701原始0–3600秒窗口完成全厂直接排程，913台机均在责任范围内，95次计划提交、1,071次生产派工、涉及841台；构造器和求解器调用为0，物理/来源/机会审计通过。摘要给出的结果为加权累计逾期10.0 lot·小时、完成1 lot、终末WIP 2,176 lot、终末逾期WIP10 lot，并说明这只证明完成开发窗口，不证明优于A/C、经济可用或实时调度。B/C比较摘要报告A/B/C三者主指标相同，但完成工序、派工、等待、换型及计划轨迹不同，且运行核、控制器、审计版本有差异。B后期同协议V14+V15报告779次调用、推进约1448.733至3600秒；最后V15续作报告72次调用、9次新提交、推进3445.778至3600秒。以上都是批准报告作者对已保存记录的归纳。本轮没有读取链接中的completion、audit、manifest、运行明细或轨迹，也没有把来源哈希与已打开源码快照逐一核对。host/outer源码本身将结果标成`accepted:false`、`formal:false`和pending后续资源/根验收，因此不能把host局部返回状态直接等同报告提到的完整根级验收。

**迁移条件：** 复用B的直接决策边界，需保持当前显式输出协议：公开观察和当前状态绑定一致；任务、机台、批组、顺序、开始条件、hold和候选apply都由模型逐项给出；组装、编译、物理commit与独立审计保留为拒绝式验证，不加自动fallback或隐式修复。还需把实际部署版本的V15 host、V14 Interaction、包内assembly、compiler、controller、transport和物理依赖冻结并绑定哈希，确保新状态上的四类锚点确实有效。恢复只能在父状态、回执、交互证据、提示/schema和物理检查点精确匹配时采用；源码中的V15 replay是特定沿革/索引边界，不是任意运行的通用resume协议。若转移到C，必须单独记录constructor实际参数、软预算、构造失败、候选质量与模型apply行为，并设置固定参数C-fixed，不能把构造器排程归成B。质量比较要用同任务、物理语义、公开信息、预算、模型版本和预先登记的保留场景；1701–1706已有使用记录，不应充作未见测试集。当前一小时、单完成lot和高模型活动时间不能外推生产现场的长周期效益、成本或实时性。

**失败方式：** 身份或状态过期：manifest、冻结runtime、输入、可执行文件、当前bootstrap或四类锚点哈希不匹配时，恢复、apply或commit会失败；不得用旧候选跨观察或跨状态。；模型输出或传输失败：V15保存原始调用并停止失败段，不自动重试原索引；拒绝、schema错误或重复查询可能触发无进展阈值，而不是由宿主替模型补出计划。；计划不完整或不可行：未显式声明所有必需字段/数组、批次、机器顺序、冻结前缀、时间窗、hold或资格约束会被装配器/compiler拒绝；没有候选自动修复路径。；提交结果不确定：host先记commit intent；若物理commit抛错，会写`reported_outcome: unknown`的receipt并停止，不能假定未提交或安全地重放。；物理进展不足：连续显式commit却无仿真推进会触发停止；未覆盖可执行需求、计划失效或真实事件也会令advance停止，仍需模型在新观察下再决策。；预算/资源中止：软/硬截止、UTC截止、日志字节、源文件身份、模型调用预留和外层收尾余量都会拒绝新调用或导致段失败；outer源码不进行自动重试，且局部pending不等于最终验收。；恢复范围错配：V15 restore要求特定父沿革证明、source hashes、交互重放完全相等和明确的[1288,1289]边界；它不能据此证明任意中断点、其他协议版本或重复执行实例都能安全续跑。

**未知：** 报告提及的具体V15运行与本轮源码哈希之间缺少逐文件可审阅的绑定；campaign manifest、冻结目录和根验收构件未读取，故版本归属与根级状态只能按摘要自述。；没有逐调用模型原始输入、输出、工具交互和来源认证，无法计算全历史原始合法率、拒绝率、修复率或模型具体决定归属分母；报告中的最终审计通过不补足这些分母。；训练/微调方法、模型checkpoint、prompt全文版本历史及训练/开发/测试拆分未报告；场景1701–1706已使用，独立留出集和重复试验未知。；全历史还有3条调用token用量未知；货币成本、缓存价格、通道账单和完整开发协作成本未报告，不能从token数自行折算。；当前V15恢复契约的完整物理snapshot来源、各记录的原始调用归档和实际根级resource check没有打开；代码定义的校验未证明实际执行时全部满足。；C具体host、tool-call参数、候选返回和apply链未在本轮直接读源码；C历史分类和5组权重来自批准摘要，需逐调用证据才能独立确认。；未查明V15实际执行时底层journal、physical_resume、controller及物理依赖的冻结版本与当前工程树是否一致；代码引用显示职责，不证明该次运行使用这些字节。；公开工厂基准的官方行为校准、数据初始化与长窗口质量，以及模型方案能否满足真实设备实时响应要求，都不由当前短窗口证据回答。

## 总体限制

以下用量及阶段状态是最终综合启动时的输入快照，保留作为历史记录；最终完成状态与结账以 summary.md 和 evidence/completion.json 为准。

预算以budget-amendment-49.json为准：总计划49，Luna15、原Sol Verify27、中间综合1、补充Sol Verify4、最终综合1、评审1。usage-summary截至2026-10-12T11:13:11Z仅记录47个已关闭会话，43完成、4失败；最终综合结账及评审尚无完成证据。已知输入30,780,259、输出465,850 tokens；缓存输入26,450,944是输入子集，reasoning输出272,765不再加到输出。四次原超时用量、账户总用量与金额未知，不能计零；Owner及直接工具成本不在此额外会话账本。600000ms超时配置不等于已证硬壁钟终止，C09原失败记录实际跨度更长且原因未定。原31次核验尝试累计27份有效结果、4次失败，不是31份判断或27项研究。原源访问事实来自已读取提取/核验记录，本次未新增在线检索；论文、README、同项目代码及同研究线材料不算独立实证。未接运行prompt草案完全不进入当前运行或协议论证。九条命题以外的WSC效果、Dyna其他表、模型/实例及算法收益数字仅保留在既有fetch/result.json作未完整对抗核验线索，未新增正文关键效果判断。访问失败、未知、未复现及中等置信限制均保留；本报告不给正式架构或实施计划，M1去向仅供研究完成后的需求讨论。

[未决问题与移交](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md>)

[独立评审（生成后生效）](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/review_v1.md>)
