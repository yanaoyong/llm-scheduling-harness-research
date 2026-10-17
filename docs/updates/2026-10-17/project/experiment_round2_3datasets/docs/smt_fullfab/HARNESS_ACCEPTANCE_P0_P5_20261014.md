# Harness P0–P5 验收报告

日期：2026-10-14。**G5 未通过，目标未完成。** 当前代码为 v1.1 离线修复版；真实 P5 为已封存的 v1.0。两版结果不能合并成一次固定版本成功。

## 结论

|门槛|结论|证据与范围|
|---|---|---|
|G0 契约|修复版离线 pass|唯一协议、完整能力与拒绝规则；P5 暴露的重复读取停止缺口已另版修复|
|G1 决定/提交|修复版离线 pass|原始字段来源、新旧编译等价、独立 apply、过期候选及约束负控|
|G2 事实|修复版离线 pass|完整重建、分页、缓存/依赖失效；自身历史动作及结果跨调用/恢复可查|
|G3 恢复|修复版离线 pass|真实进程退出、持久响应、丢失回执、单写者、接管后提交及物理推进|
|G4 审计|修复版离线 pass|封存边界、原始来源、物理/机会/费用独立复算及篡改负控|
|G5 实跑|**fail**|20 个登记片段中启动 3 个，0 个接受；完整 B3600 未启动|

完整回归 197 项通过，随后补充 T18 完整窗口恢复对照与 T26 真实优化器入口两项，合计 **199 项通过**；源码指纹未变。包括 T01–T28 全部映射和 4 项 P5 循环回归。工程报告：[engineering_acceptance.json](../../artifacts/harness_v1_1_offline/engineering_acceptance.json)；[测试矩阵](../../artifacts/harness_v1_1_offline/T01_T28_matrix.md)；[原始测试日志](../../artifacts/harness_v1_1_offline/full_regression.log)。模型进程守卫测试真实创建/终止子进程；模拟用量及回放动作均明确标记，未当作真实 B 结果。

T18 补充对照从同一正式提交出发，真实子进程在物理持久化和导出时退出，恢复后继续至 120 秒终点。所有生产事件、完整终态、独立审计指标与未中断对照一致；原 trace 唯一不同的是 terminal.metrics.end_to_end_seconds 的真实宿主墙钟，两份测量原样保留，未计入物理等价。[T18 证据](../../artifacts/harness_v1_1_offline/T18_full_window_recovery/comparison.json)。T26 补充用真实有界 CP worker 验证显式基准、结果归属、无隐式选择，以及后续独立选择旧候选；不把它解释为优化器容量或质量基准。[C 优化器入口证据](../../artifacts/harness_v1_1_offline/C_optimizer_boundary/comparison.json)。

P0–P4 的实现和离线出口已交付。A/B/C/C-fixed 共用状态、提交和审计契约；A 当前为明确的固定构造策略，尚未完成强基线标定。P5 有真实失败证据而未验收。语义仍 partial：CQT 未实现、缺失历史绑定不作默认通过；质量优势、因果成本节省、官方校准和在线能力均未验收。

## 真实试点

冻结登记：[experiment.json](../../artifacts/harness_p5_v1_release/experiment.json)，源码指纹 `0ae0ef8a4f6a8d36118c2b3667adae3b1bd3a5f0111902ed74be9c637a445bf4`。初态和筛选依据在调用前固定，20 个原样保留。

|片段|实际尝试|提交|结束原因|独立审计|
|---|---:|---:|---|---|
|micro-01|10|0|片段调用上限|证据/费用闭合；片段未完成|
|micro-02|10|0|片段调用上限|证据/费用闭合；片段未完成|
|micro-03|1|0|发现协议缺陷后停止；在途调用已结算|证据/费用闭合；片段未完成|
|micro-04 至 micro-20|0|0|未启动，仍在失败分母|无模型结果，不算完成|

所有已返回动作均为相同上下文的 `get_context`。完成延迟中位数和 P95 **不可估计**；未提交不能解释为完成。原门槛投影保留的未启动 0 值不能作为零轮完成统计；最终门槛始终 fail。完整 B3600 未进入准入，唯一新 B 运行额度尚未使用。

累计输入 853,160 + 输出 1,719 = **854,879 token**；缓存输入 9,216 已包括在输入中。21 次实际尝试，模型活动 **504.521 秒**，实验及必要封存审计墙钟 **548.916 秒**，未知用量 **0**。金额未知。token 预留是保守准入检查，并非服务端精确硬上限。原授权剩余：79 次、1,145,121 token、3,095.479 秒模型活动、6,651.084 秒实验墙钟；失败成本没有清零。

每个目录均保存 manifest、`model/` 原始输入输出和进程证据、`events.sqlite3` 预算及事件、`evidence_manifest.json`、`audit/acceptance.json`：[micro-01](../../artifacts/harness_p5_v1_release/runs/micro-01/manifest.json)、[micro-02](../../artifacts/harness_p5_v1_release/runs/micro-02/manifest.json)、[micro-03](../../artifacts/harness_p5_v1_release/runs/micro-03/manifest.json)。费用已再次从封存原件复算：[诊断及精确引用](../../artifacts/harness_v1_1_offline/pilot_diagnosis.json)。部分物理前缀通过不等于完整窗口通过；没有虚构 terminal 或新增物理进展。

## 失败修复与复现

v1.0 的 G0–G4 准入证据当时通过，P5 随后揭示其协议无进展覆盖不完整；原准入报告保留，不能据此继续声称该冻结版所有工程要求完整。缺少此前动作记录是重复行为的可能促因，尚无真实对照证明唯一因果。

v1.1 增加精确自身动作/结果索引和 `same_read_limit=3`，第二次相同读取给出重复计数及原件，第三次停止。分页变化及新物理版本不误计，幂等重放不多计。未改变生产决定归属、编译器、物理语义、scope 或失败门槛。新协议与配置独立编号，真实调用数为 0。

实际 CLI 为随附 `0.162.0-alpha.17.2`；固定 `gpt-6-astra / medium`，单次上限 600 秒、自动重试 0。修复版实际 CLI 对本机确定性服务的请求包含空原生工具列表，正常响应通过；损坏响应只发 1 次请求后失败。两例均无真实推理：[通道证据](../../artifacts/harness_v1_1_offline/cli_preflight/repair/probe_result.json)、[重试负例](../../artifacts/harness_v1_1_offline/cli_preflight/repair_broken/probe_result.json)。

实际执行过修复版 start_new、resume_run、run --seal、audit；60 秒离线 C-fixed 正例及重复审计通过且成本相同。启动/恢复/运行/审计命令和旧版真实 stop 命令见 [实施记录](HARNESS_IMPLEMENTATION_v1.md)。现存目录禁止重新 start_new；新离线复现应选新目录。新配置：[harness_v1_1_offline](../../configs/smt_fullfab/harness_v1_1_offline/contract_catalog.json)。

冻结 v1.0 源码、依赖锁、配置、测试与数据：[源码包](../../artifacts/harness_p5_v1_release/frozen_source/source-and-data.tar.gz)、[文件索引](../../artifacts/harness_p5_v1_release/frozen_source/index.json)。必须解包至独立目录，不覆盖当前代码。原 823 个历史基线文件全部未变：[保存核对](../../artifacts/harness_v1_1_offline/preservation_check.json)。用户原有 progress 修改没有被覆盖。

## 后续准入

继续 G5 的具体提案是：修复版重新登记**同一 20 个初态与任务**，旧失败组永久保留；把微基准累计 token 上限从 200 万增到 300 万（合计从 800 万增到 900 万），其他次数、模型时间、实验墙钟及唯一 B3600 上限不变。所有旧费用先并入共享累计账户，再准入新请求。原提示每次约 3.4–4.3 万输入 token，20 个至少两动作片段可能超过剩余 114.5 万；上述是保守资源提案，不是成功保证。

该提案**未获授权、未执行**：[具体配置与前置条件](../../artifacts/harness_v1_1_offline/continuation_proposal.json)。申请依据是目标文件第七、八节禁止自动扩额、禁止把失败轨迹换码续接为成功。未通过新微基准前仍不得启动 B3600。若不扩大预算，当前结果保持 G5 fail。

P6 十二条配对、P7 八/二十四小时仅交付配置及计划，均未启动：[P6/P7 前置条件与资源需求](../../configs/smt_fullfab/harness_v1_1_offline/P6_P7_plan.json)。强 A 容量、C 恢复边界、共同初态和新资源授权仍是前置条件。

机器可读最终结论：[goal_acceptance.json](../../artifacts/harness_v1_1_offline/goal_acceptance.json)；STATUS 由同一对象生成，目标未标记完成。
