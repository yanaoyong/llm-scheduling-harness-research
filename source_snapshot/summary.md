# 大模型智能排程 · M0.5 调研

状态：**PASSED**。独立评审：APPROVED；正式评审报告原样保存，六门禁结果见下表。

主要结论：先验证“LLM理解/建模或生成候选规则 + 优化器 + 独立约束检查 + 仿真与人工发布”的分工。直接生成排程已有研究，但本次证据不能确认LLM已可靠接管完整动态Fab；GPU、RL、集群和供应链证据不能替代这项验收。

- [调研报告](m0.5_research/dossier.md)：制造排程概念、五条应用路线、Fab约束、证据边界、建议架构/评估及岗位学习项目。
- [未决问题](m0.5_research/open-questions.md)：10项带建议角色、材料、去向与验收口径的问题。
- [独立评审](m0.5_research/review/research_review_v1.md)：首次有效冷启动v1。
- [三轮证据索引](m0.5_research/evidence/claim-audit.json)与[用量账本](m0.5_research/evidence/usage-ledger.json)。

12条候选各3次对抗尝试：**11条获支持、1条未验证**。36次中32次形成有效判决，CL-02/v3原状态failed、CL-03三次超时均弃权。自动合成超时，Owner从落盘证据整理dossier；记录为partial，不冒称原引擎完整成功。独立评审第一次因本地沙箱初始化失败，没有进入模型；第二次以预留调用冷启动评审。

最终调用保守计数 **60/60**（包含取消/排队与初始化失败），没有追加。CLI可见输入 **10,509,952 token**，其中缓存输入 **8,006,528**为子集；可见输出 **112,048 token**。初始300万–600万输入粗估偏低，实际可见量已超区间；未上报进程及Owner会话/原生web用量不含在此，不是完整账号消费或人民币报价。

A源显式N/A（未指定业务KB/未提供工厂数据）；B源外部检索与真实对抗已留痕；C源为岗位截图，未写curated corpus。未启动M1、PoC实现或业务wiki摄取。

| 门禁 | 结果 | 依据 |
|---|---|---|
| G1 | PASS | 范围限定制造业排程、重点Fab；架构、评估和demo均明确为建议。未指定业务KB按explicit_na处理，未将M0.5通过解释为M1实施授权。研究请求58次，加本次Reviewer为59次，未超60次上限。 |
| G2 | PASS | A源explicit_na有路由及数据缺失理由；B源有实际检索、原源和访问限制记录；C源岗位截图已查看且SHA-256匹配，corpus_write=none。 |
| G3 | PASS | 12条候选均有引用、访问日期和provenance；实际打开7个主来源，重点核对CL-04/05/06/07/08/09/11。Owner收窄与原文相符，作者报告、工程推论、独立复现及工厂收益未混同；CL-03明确禁止作为已支持先验。 |
| G4 | PASS | 逐票核对36份原始事件及结果：每次均有web_search.action检索，32个有效支持、4个弃权，重算为11 confirmed、1 unverified。未将失败/null计为支持。查询摘要存在遗漏，但原始日志完整且无摘要查询凭空新增，记LOW。 |
| G5 | PASS | 最终12条Claim均设置explicit_not_found=true并提供未命中说明及查询路径；受限论文、CL-03超时、合成report=null、目标Fab数据和独立复现缺口均显式披露，没有把未找到写成不存在。 |
| G6 | PASS | open-questions文件非空且run_id一致；10项均含问题、合法handoff_target、建议责任角色、材料或行动及验收口径。OQ-08归入defer-roadmap，其余M1仅为移交，未自动开工。 |

运行器实跑发现的重连诊断误判已修复，23项回归通过；不追溯改变本次启动前版本的原判决。

Owner已落实两项LOW的说明修订，见[归档与闭合记录](m0.5_research/evidence/owner-review-closure.md)。Reviewer原文59次为当时快照；补计本地初始化失败1次后最终60次。独立评审不认证运行器修复，23项回归是Owner实跑记录，见evidence/runner-regression.json。
