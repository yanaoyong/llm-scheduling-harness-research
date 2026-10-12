---

artifact: open-questions

flow_instance: research-harness-scheduling-20261012-round2

run_id: m05-20261012-focused-tiered-02

stage: M0.5

created_at: 2026-10-12T11:26:59.471450+00:00

---

# 第二轮未决问题与移交

列入M1表示交给后续需求讨论，当前不启动设计或实施。

## OQ-01

同工具C-fixed能否解释历史C表现，模型选权重/候选有无独立增量？

handoff_target: M1

related_claims: A-04, R2-C09

handoff_note: 保留固定参数缺口；需求讨论时明确同引擎、观察、构造预算及模型预算，列入M1不表示启动。

## OQ-02

批准B运行与当前V15/V14包内依赖、compiler及物理依赖能否逐哈希绑定？

handoff_target: M1

related_claims: R2-C09, A-01

handoff_note: 重试已补静态审查，不再等待重试；仍缺历史部署对应证据，不要求本阶段读取原始运行明细。

## OQ-03

生产计划字段与环境虚拟推进、物理就绪等待各应如何计入决定归属？

handoff_target: M1

related_claims: R2-C01, R2-C09, A-06

handoff_note: 以具体分支定义范围；信息工具、掩码和环境事件不合并记为模型决定。

## OQ-04

CQT历史起点、资格绑定与冷启动状态未知时，哪些约束未建模、哪些无法判定？

handoff_target: M1

related_claims: A-05, A-09, R2-C07

handoff_note: 继承433/1311条unknown；完整性与官方数值校准分开，不能以默认值或区域案例消除缺口。

## OQ-05

编译、公共执行与独立审计能否揭示共同错误，完整失败分母如何定义？

handoff_target: M1

related_claims: R2-C03, R2-C09

handoff_note: 区分解析失败、原始非法、检查拒绝、修复后可行及最终提交；质量只看成功输出不足以比较路线。

## OQ-06

特定V15恢复能否覆盖其他中断点，提交结果unknown时如何证明效果和预算一致？

handoff_target: M1

related_claims: R2-C08, R2-C09, A-08

handoff_note: 保留A24/C8失败和未验证续跑；myharness原生无恢复的限定结论已补齐，通用恢复仍需证据。

## OQ-07

目标是暂停仿真决策质量，还是工厂在模型思考期间继续运行的在线效果？

handoff_target: M1

related_claims: A-10, R2-C02, R2-C07

handoff_note: 先确定目标与响应期限；在线旧计划、状态过期和迟到更新的后续实施讨论可移交roadmap。

## OQ-08

冻结生成规则与测试时适应各自的持出泛化、失败及成本摊销证据是什么？

handoff_target: M1

related_claims: R2-C05, R2-C06

handoff_note: EoH排程实际生成成本、SeEvo逐样本API账本与版本仍未知；小数工时静态例子先确认输入域。

## OQ-09

公开实现与论文版本、完整评估调用链和真实分支发生率能否核定？

handoff_target: M1

related_claims: R2-C01, R2-C03, R2-C04, R2-C05, R2-C06

handoff_note: 缺Dyna论文配置、SCHEDBench完整解析验证器、SeEvo/EoH实验提交；GenAI实现未定位。旧LLM4Schedule仍为线索，未命中不等于不存在。

## OQ-10

研究会话和排程运行怎样保留失败、缓存、未知tokens与货币费用边界？

handoff_target: M1

related_claims: R2-C08, A-03, A-08

handoff_note: 研究四次失败用量与B历史三次未知分别保留；会话数不是内部往返数，缓存和reasoning不得重复累加。

## OQ-11

框架版本、许可、生成程序执行隔离与维护成本何时进入验收范围？

handoff_target: defer-roadmap

related_claims: R2-C05, R2-C06, R2-C08, CL-01, CL-09, CL-10

handoff_note: 范围和候选确定后讨论；沿用旧APPROVED边界，本轮未做完整依赖审计或正式架构设计。

## OQ-12

真实设备的效果去重、历史权威状态及现场业务验收由什么独立证据确认？

handoff_target: out-of-scope

related_claims: A-09, A-10, CL-07, CL-10

handoff_note: 本阶段仅研究全厂基准/开发环境，不接MES/PLC，不用模拟成绩或源码规模替代现场部署证据。
