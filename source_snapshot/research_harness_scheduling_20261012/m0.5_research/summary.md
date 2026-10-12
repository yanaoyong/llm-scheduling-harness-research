# M0.5 交付与评审闭环

本轮M0.5已完成，独立评审为 **APPROVED**，G1–G6全部通过，MUST FIX为0。评审后两件正式产物的SHA256与评审输入一致，无需第二轮评审。

- [调研档案：六个方向、12组原源提取、12条限定论断及36次核验](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/dossier.md>)
- [9项未决问题：7项M1、1项roadmap、1项本轮范围外](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/open-questions.md>)
- [独立出口评审](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/review_v1.md>)

12条论断均为限定命题得到支持；三份模型判断不是三份独立研究证据。现有材料可供下一步需求讨论，尚不足以锁定技术栈、证明本厂收益或现场验收。离线规则生成、独立复现、完整依赖审计与工厂迁移仍有显式缺口。

## 执行与成本

实际额外研究会话请求 **58/60**：Scope 2（含1次失败启动）、Search 6、Fetch 12、Verify 36、Synthesize 1、Review 1。57次有可见usage，1次失败启动没有usage回报，保持未知。没有为了用满预算增加重复核验。观察到最高并发为2；每次会话可含多个模型/工具往返，58不是底层HTTP请求或推理轮次数。

| 请求模型 | 会话请求数 | 已知输入tokens | 其中缓存输入 | 已知输出tokens |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-luna | 20 | 5,371,646 | 4,261,376 | 126,206 |
| gpt-6.1-sol | 38 | 11,621,559 | 9,212,800 | 189,017 |

合计已知输入 **16,993,205**、输出 **315,223**，共 **17,308,428** tokens；缓存输入 **13,474,176**，占已知输入约 **79.29%**。缓存是输入子集，推理输出是输出子集，均不重复相加。

这些数字来自额外会话的原始usage事件，不含Owner主会话及直接工具的完整成本，不是账户总用量或精确货币账单。未取得计费映射，金额保持未知。不能用本研究的缓存占比与旧B运行直接推断工程改善。

首个登记会话到独立评审结束的墙钟跨度约 **101.7分钟**，包含准备、检索、工具、等待和协调；不是纯模型推理时间，也不是单次排程运行耗时。

[最终用量与检索审计](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/usage-and-tool-audit.json>)；[调用账本](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/launch-ledger.json>)。

## 证据与范围

本轮未重跑本厂排程实验、未安装运行完整外部项目、未接现场设备。四个Verify会话做了公开源码片段的隔离微检，使用替身数据类型或后端；它们不能替代完整依赖、真实模型或工厂测试。细节见 [隔离验证明细](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/isolated-source-checks.json>)。

CL-07/v3的在线读取全部失败，但指定公开快照读取、Git blob SHA与隔离检查有原始命令证据，独立评审已核查；该项没有被标成成功在线访问。首次启动失败及未知用量完整保留；早期审批拦截已在用户明确授权脱敏汇总传输后解决。过程见 [执行决策记录](<__LOCAL_PROJECT_ROOT__/research_harness_scheduling_20261012/m0.5_research/evidence/owner-decisions.json>)。

本轮仅交付M0.5研究输入，未启动M1。
