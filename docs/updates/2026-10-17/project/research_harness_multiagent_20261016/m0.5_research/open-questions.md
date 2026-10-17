---
artifact: open-questions
flow_instance: research_harness_multiagent_20261016
run_id: harness-multiagent-m05-20261016
---

# 未决问题与后续去向

交接分类不自动启动工程实现或排程回放。handoff_target中的M1是后续流程阶段，与报告中“只读分析子agent路线M1”的架构标签不同。

## MA-OQ-01

oq_id: MA-OQ-01

question: S1改善后，是否仍有需要非平凡模型分析的信息瓶颈？

handoff_target: M1

related_claims: MA-C01, MA-C03, MA-C08

handoff_note: 关闭证据：同保存状态、事件与推进时长的S1基线；读取/推理/提案轨迹；约束与信息完整性检查；在预定质量门槛下确认是否仍有适合独立模型分析的瓶颈。本轮不启动。

## MA-OQ-02

oq_id: MA-OQ-02

question: 共享资源耦合达到何种程度时，M2或M3才值得增加协调？

handoff_target: defer-roadmap

related_claims: MA-C04, MA-C07

handoff_note: 关闭证据：先定义共享资源和跨区依赖的耦合指标，再取得低/高耦合分层的成对成本与质量区间，计入冲突重提、协商等待和失败；不能从外部任务成功率拟合值推成本厂阈值。暂缓到独立实验阶段。

## MA-OQ-03

oq_id: MA-OQ-03

question: 如何让单agent与所有子agent、裁决、摘要、模型评审、重试及失败的实际请求和完整成本均可观测？

handoff_target: M1

related_claims: MA-C03, MA-C06, MA-C08

handoff_note: 关闭证据：逐请求账本具有请求/父请求ID、角色、尝试、状态、输入/输出/缓存用量、时间和实际计价口径；请求日志与用量/账单按同一窗口核对，区分工具调用、模型请求、会话及重排；未返回用量和不可核对金额显式保留，未解决前只能报告成本下界。首次计划与维护、并行费用求和与关键路径延迟分别记录。原冻结实验不自动恢复。

## MA-OQ-04

oq_id: MA-OQ-04

question: 候选版本、并发提交、重复请求和超时未知结果由什么协议处理，谁拥有裁决与最终提交权？

handoff_target: M1

related_claims: MA-C02, MA-C04, MA-C05

handoff_note: 关闭证据：明确事实/计划版本、完整全局约束、原子检查与提交边界、唯一有效提交权、幂等键和载荷绑定、过期结果拒绝、未知结果核对、有限轮退出及回退决策者；在获准的隔离环境用并发竞争、重复提交、断连/超时、依赖变化案例验证协议。静态schema不能替代这些证据；协议检查不得暗中选择排程。当前不启动实现或实验。

## MA-OQ-05

oq_id: MA-OQ-05

question: 排程质量的主指标、非劣界、硬约束门槛、采样与停止规则如何预先确定？

handoff_target: M1

related_claims: MA-C05, MA-C06, MA-C07, MA-C08

handoff_note: 关闭证据：实验前冻结加权延期等主指标与权重、方向及非劣容差，硬约束/冻结承诺标准、失败和零提案计入规则、预算及停止规则；配对状态、私有RNG、事件和推进长度一致。pilot估计样本需求，按预定成对区间判断非劣，同时报告完成量、等待、响应与计划变动。暂停虚拟时钟和计入决策延迟分开。未检出差异不能作为质量未下降的证明。

## MA-OQ-06

oq_id: MA-OQ-06

question: ALAS的实际代码/模型/工具决策边界与聚合权重能否独立核验，是否值得在本厂另设算法决策对照？

handoff_target: defer-roadmap

related_claims: MA-C05

handoff_note: 论文已明确算法4改时序/换顺序及§3.5按makespan选取；未知的是运行实现主体、伪码对应实现、费用聚合权重与样本级合法性。关闭证据：可追溯代码版本、执行轨迹、逐样本结果及汇总公式，或作者明确补充；取得前仅引用作者报告，不推定固定模型或本厂收益。若引入算法修复/选取，先声明其决策能力并另列对照；当前暂缓，不阻塞借鉴已明确的信息交接原则。
