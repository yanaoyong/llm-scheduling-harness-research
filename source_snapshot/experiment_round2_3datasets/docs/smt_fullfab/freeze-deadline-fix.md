# 冻结期限继承修复：已安装并验证

原执行器和两份独立来源审计都有可复现缺口：原任务在冻结至20秒的计划中，10秒修订原样保留任务却把冻结期限降到10，11秒就能删除该任务。三个实现均接受这条两次修订路径。原始反例、报告和源码已保存在 `artifacts/smt_fullfab_review_drafts/freeze_deadline_v1/`，不回写旧证据。

最小修复只增加一个规则：尚有未派发的冻结任务时，新计划不得缩短原冻结期限。执行器拒绝输入，不自动延长期限或改任务；两个来源审计各自重建冻结状态再检查。环境版本升至0.3，来源综合审计与流式来源审计升至v3。差量语言更严格的机器前缀保护不扩散到既有共同执行器。

root 已执行候选隔离测试9项，并对安装后直接调用生产接口的正式回归另做完整候选验证9项（0.023秒）。正式夹具在 `artifacts/smt_fullfab_review_drafts/test_smt_fullfab_freeze_deadline.py`，覆盖原反例、拒绝原子性、相等/延长期限、到期、全部与部分已派发、无冻结任务、旧相对顺序合同及旧快照版本拒绝。没有调用工厂构造、模型或求解。

随后 root 对以下已保存轨迹逐条运行 baseline/candidate 的普通与流式来源审计，共四种实现。除审计版本及新增来源元数据外，报告全部字段、数值类型和数组顺序精确一致，四份源原始字节哈希均保持不变：

| 保存记录 | 来源审计结果 |
| --- | --- |
| A hybrid 1小时成功记录 | 四种均通过，内容精确一致 |
| CR 1小时参考记录 | 四种均通过，内容精确一致 |
| C probe v1失败前缀 | 四种均通过，内容精确一致；不表示窗口完成 |
| B complete v2原失败前缀 | 四种均通过，内容精确一致；不表示窗口完成 |

脚本与结果分别为 `artifacts/smt_fullfab_semantics/review_freeze_deadline_saved_traces_v1.py` 和 `artifacts/smt_fullfab_semantics/freeze_deadline_saved_trace_review_v1/comparison.json`。该复核没有再次做物理或机会审计，没有新仿真、模型或求解调用。

B recovery 001 已完整退出，result、checkpoint、独立归属检查、acceptance及账本finalization均已保存；root 用其冻结源码验证快照准确恢复。随后核对三份生产源码、候选与测试夹具哈希，安装最小diff和正式回归。完整 fullfab 572项测试已通过（49.174秒）。首轮两处旧测试允许缩短冻结期限，现让合法继承样例保留原期限；新回归继续明确拒绝缩短。验证证据见 `artifacts/smt_fullfab_semantics/C_prelaunch_integration_v2.json`。随后冻结新C代码并开始真实验证。

旧v0.2快照继续使用各自保存的旧源码恢复。新版本拒绝把旧版本快照直接当作当前状态；本修复不包含迁移，也不修改旧run的预算、验收或成功标记。A8已经冻结的源码副本继续保持原样，后续新规则复核应另存证据。
