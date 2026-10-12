---

artifact: open-questions

flow_instance: research-harness-scheduling-20261012

run_id: m05-20261012-deep-tiered-01

stage: M0.5

created_at: 2026-10-12T05:15:29.809248+00:00

---



# M0.5 未决问题与移交



这些问题保留在需求讨论入口；列入 M1 不等于现在开始 M1 或默认采用某一实现。



## OQ-01

四种模型职责如何在统一实例、目标、信息和预算下比较，离线规则生成需要补核验哪些原始研究？

handoff_target: M1

related_claims: CL-01, CL-02, CL-04, CL-12

handoff_note: 保留路线空间；LLM4Schedule仍为初读线索，不采纳其结果为本批confirmed效果，也不把未检得头对头研究解释为不存在。 Q-06中的LLM4Schedule等初读线索未纳入本轮12条三次核验，若列为设计候选需补充原源与执行边界核验。



## OQ-02

哪些操作能在模型完整delta给定后机械合并，哪些候选生成或回退动作改变B的决定来源？

handoff_target: M1

related_claims: CL-03, CL-04, CL-07

handoff_note: 交付候选操作边界与归属账本方案，先审完整delta回放；任何程序补选任务、机器、批次、顺序或等待均另计实验臂。



## OQ-03

公开状态的版本、失效事件和可读取原件是什么，CQT及绑定历史unknown如何影响检查结论？

handoff_target: M1

related_claims: CL-05, CL-06, CL-07, CL-08

handoff_note: 讨论字段与约束覆盖表、未建模和无法判定的计分方式；不得用摘要或默认值消除历史缺口。 将433条CQT历史起点未知和1311条绑定历史缺失保持为unknown，分别决定未建模、无法判定与失败的判据。



## OQ-04

恢复成功应满足哪些续跑、效果对账、授权有效性及累计预算条件，检查器如何暴露共同错误？

handoff_target: M1

related_claims: CL-05, CL-07, CL-09, CL-10

handoff_note: 以H-03和H-04作为待选反例方案，保留A24/C8失败及未验证续跑状态，不将恢复证书升级为运行成功。



## OQ-05

M1的验收目标是暂停仿真的离线决策质量，还是包含模型思考期间工厂继续运行的在线效果？

handoff_target: M1

related_claims: CL-09, CL-10, CL-12

handoff_note: 先确定目标范围；若包含在线效果，明确旧计划执行、状态过期、迟到更新与响应期限；具体在线评估实施可以在需求明确后移交roadmap。



## OQ-06

实体设备或生产系统的去重协议、历史权威性和现场验收由谁提供独立证据？

handoff_target: out-of-scope

related_claims: CL-07, CL-09, CL-10

handoff_note: 本阶段研究全厂基准与开发环境；现场部署、业务验收及硬件效果不能由源码、模拟成绩或项目规模代替。 本轮只研究，不接入或写入真实MES/PLC；现场协议和业务验收不属于本次执行范围。



## OQ-07

供应链问答、通用优化建模、MEC模拟和微型制造样例的哪些机制，可在913台设备及当前语义缺口下成立？

handoff_target: M1

related_claims: CL-01, CL-02, CL-04, CL-12

handoff_note: 逐项记录适用规模、约束映射、输入版本、最小验证及证伪条件；当前资料不证明同规模现场收益。



## OQ-08

预算账本如何分别报告会话、内部模型/工具往返、已知与未知tokens、缓存、失败和货币账单？

handoff_target: M1

related_claims: CL-09, CL-10

handoff_note: 本轮只有额外研究会话的可见usage，不含Owner主会话全部成本，也没有精确计费映射；后续预算不能把未知记为零或重启后清零。



## OQ-09

选择具体框架后，版本维护、依赖许可、生成代码执行隔离与设备重复命令防护如何验收？

handoff_target: defer-roadmap

related_claims: CL-01, CL-09, CL-10

handoff_note: 当前只核验有限源码/文档与仓库API元数据，未做完整依赖树审计或现场验证；在范围与候选技术确定后建立实施验收任务。


