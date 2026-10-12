# M0.5 第二轮调研完成摘要

完成时间：2026-10-12T11:44:19.795136+00:00。独立评审：APPROVED；M0.5 六项门禁通过。

本轮追加四专题，上一轮结果完整保留。本报告交付研究结论和待验证问题，尚未开始 harness 设计或新工厂实验。

## 建议阅读顺序

[完整调研报告（四专题、项目比较、27次原核验、4次补充重试与10份原源提取）](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/dossier.md>)

[尚未解决的问题及移交去向](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/open-questions.md>)

[独立评审](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/review_v1.md>)

[完成记录与会话统计](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/completion.json>)

## 本轮得到什么

截至2026-10-12，本轮增量证据支持保留直接排程B、工具/策略选择C、离线规则生成三条路线，尚不足以判定同条件胜负。原核验27次尝试产生23份有效结果、4次超时；四次重试均完成，按各角色最新有效结果，C01、C06仍为refuted，C09补充登记由unverified变为confirmed，其余六条维持confirmed。三次模型检查不是三份独立研究。C01被成功解析后程序裁决的反例推翻；C06被查询数字出处错误推翻，规则生成机制仅作收窄采纳。C09两份重试为medium，支持有条件的静态控制流，必须披露虚拟延迟节点推进、物理就绪检查和历史部署未绑定。SCHEDBench单次整表、SeEvo测试时适应、作者单厂DES结果及本地一小时开发报告均有各自边界；C-fixed、完整失败分母、版本绑定、历史状态缺口和在线时延仍未解决。最终综合会话仅综合指定产物，未新增检索、实验、文件修改或启动M1。

## 对 B / C 的条件性判断

研究阶段保留三条路线。若目标是审查模型对具体生产决定的能力，B已有可审计机制和有限开发证据；若允许算法安排具体任务，C是合理比较候选，但需证明模型超出C-fixed；若要求重复执行规则，离线生成值得继续研究，但须区分冻结与新场景适应。当前证据不足以选择唯一生产路线或锁定技术栈。

会改变判断的是同物理语义、初态、观察、候选处理、目标、模型快照和预算下的持出重复证据：分别报告原始合法率、拒绝/修复/回退、失败纳入质量、tokens、调用与壁钟。C若稳定优于C-fixed且计入模型成本，支持策略选择价值；冻结生成规则若无新增API仍保持质量且合法性独立通过，支持离线路线；B若同条件表现有增量并满足目标响应期限，支持扩大直接职责。这些都是未执行的证伪条件。

## 相对上一轮的新增与修正

旧APPROVED研究保持原报告，OptiGuide、OptiMUS、Deep Agents、Smart Manufacturing Agents、LangGraph、Temporal、PyJobShop与MEC结论未在本轮重写。新增离线生成与测试适应边界、直接整表/逐步动作的实际决定者、单厂静态/动态对照及本地复用清单；缺同条件路线比较、完整成本和历史部署绑定。本轮Search对Cambridge GenAI职责的描述由C04纠正，不是修正旧APPROVED结论。C01原充分条件、C06原数字出处明确保留refuted。相对中间综合，四次重试完成，C09只在补充登记由unverified变为静态confirmed；原27次尝试、4次失败和中间综合均保留。A-05始终属于批准内部语义报告继承，未升级为外部CQT三核验效果。

## 会话与用量

实际使用 49/49 次额外研究会话，剩余 0 次未使用。每次会话包含多轮模型及工具调用，不能把会话数视为 API 请求数。

| 阶段 | 次数 |
| --- | --- |
| Scope | 1 |
| Search | 4 |
| Fetch | 10 |
| Verify | 31 |
| Synthesize | 2 |
| Review | 1 |

核验31次由原27次和补充重试4次组成；综合2次包括保留的中间版本及重试后的最终版本。原四次超时仍计入49次预算。

模型分配：{'gpt-6-luna': 15, 'gpt-6.1-sol': 34}。会话状态：{'completed': 45, 'failed': 4}。

可见用量：输入 35,617,371，输出 500,355，合计 36,117,726 tokens；其中缓存输入 30,863,872 已包含在输入中，不再重复相加。未知用量会话 4。

该账本仅覆盖此轮额外研究会话，不含主对话与 Owner 直接工具操作；未取得完整账户账单，不换算现金费用。失败会话与未知用量若存在均保留，未按零费用处理。

[完整用量与工具审计](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/usage-and-tool-audit.json>)

## 证据与限制

核心论断 9 条，原登记 {'refuted': 2, 'confirmed': 6, 'unverified': 1}；补充重试后 {'refuted': 2, 'confirmed': 7}。同一 Sol 模型的三次独立核验尝试只是对原源的审查，不是三份独立实证；被收窄和未证实部分在采纳范围中保留。

以下为综合输入时点的历史限制与用量快照；其中47次及未完成阶段的表述不代表交付状态，最终结账以上文及completion.json为准。

预算以budget-amendment-49.json为准：总计划49，Luna15、原Sol Verify27、中间综合1、补充Sol Verify4、最终综合1、评审1。usage-summary截至2026-10-12T11:13:11Z仅记录47个已关闭会话，43完成、4失败；最终综合结账及评审尚无完成证据。已知输入30,780,259、输出465,850 tokens；缓存输入26,450,944是输入子集，reasoning输出272,765不再加到输出。四次原超时用量、账户总用量与金额未知，不能计零；Owner及直接工具成本不在此额外会话账本。600000ms超时配置不等于已证硬壁钟终止，C09原失败记录实际跨度更长且原因未定。原31次核验尝试累计27份有效结果、4次失败，不是31份判断或27项研究。原源访问事实来自已读取提取/核验记录，本次未新增在线检索；论文、README、同项目代码及同研究线材料不算独立实证。未接运行prompt草案完全不进入当前运行或协议论证。九条命题以外的WSC效果、Dyna其他表、模型/实例及算法收益数字仅保留在既有fetch/result.json作未完整对抗核验线索，未新增正文关键效果判断。访问失败、未知、未复现及中等置信限制均保留；本报告不给正式架构或实施计划，M1去向仅供研究完成后的需求讨论。

[文件、预算、模型、并发和原轮完整性检查](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/mechanical-preflight.json>)

[关键论断与全部原判决](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/claim-register.json>)

[逐条采纳范围](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/adoption-scopes.json>)

[四次补充重试与原失败对应](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012_round2/m0.5_research/evidence/retry-register.json>)
