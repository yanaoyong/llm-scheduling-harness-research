# 官方参考策略与校准状态

截至 2026-10-09，**有可核查的官方报告数值，但尚不能宣布数值复現完成**。新研究保留 21 流、2156 初始 lot 与全部 913 台生产设备；官方归档报告所用的交期文件、随机种子及运行入口尚未与新环境完全对齐。

## 官方参考策略与上游差异

官方 Dataset 2 `tool.txt.1l` 全部 106 行的排名为 `rank_HP;rank_RSETUP;rank_CR`：优先级、最小换型、Critical Ratio；103 行为 `rule_HotLotFIRST`，3 行为植入设备的 `rule_LSSU` 最小 run 约束。有换型的族还使用 `wake_LeastSetupTime`。CR 是参考规则，不是全局最优答案。

固定 PySCFabSim 的 `simulation/dispatching/dispatcher.py:60–70` 实际把换型成本放在优先级前面；`simulation/greedy.py` 的组批还有批填充率优先级。故“CR”这个名字不能保证相同派工语义。

更直接的复現阻碍是固定上游 `simulation/greedy.py:193–202` 在解析 CLI 后无条件改成 HVLM、FIFO、730 天和新抽取的随机 seed；直接运行 `reproduce_dispatcher_experiments.sh` 不能保证得到脚本请求的 LVHM/CR/seed。旧 vendor 保持不变。未来对齐试验需把修复后的调用入口置于新命名空间，并独立冻结 diff 和实参。

新 `src/smt_fullfab/reference.py` 提供只读 `reference_action(env, policy='cr'|'fifo'|'edd')`。所有生产机纳入候选，返回明确 `{dispatches:[{machine,lot_ids}],wait_seconds}` 及 provenance；同 lot 不重复分配，组批按同part/step、min/max；合法性由共同环境再次检查。它是开发参考策略，只在独立 reference 方案调用，**不得为 A/B/C 补齐计划**，不是 A 的滚动优化替身。CR 分母采用当前及后续步骤的期望加工时间，与上游 `Lot.cr` 的口径一致；不偷看未来返工、故障或加工抽样。排序明确为 HP→setup→CR/FIFO/EDD，组批采用 Demand，平局按due/lot ID/设备 ID等确定性规则。

该参考实现尚未证明与 AutoSched 的全部平局、批选择、wake 和特殊 hot 行为相同，`official_calibrated=false`。锁定周期表的 HOTLOT 全 no，因此不要求下游预留；将来换表时必须重新检查。首次测试仅证明当前动作合法且不修改输入环境，不能当成全时域可行或数值校准。

## 已取得的官方数值与可比性

官方 ZIP 的 `AutoSched/dataset 2/LVHM_Model/` 本来含 `perf.rep`、`part.rep`、`order.rep`、设备报告及运行日志。本次从锁定 ZIP **只读解析**，保存成员 SHA256 与表记录到 `artifacts/smt_fullfab_semantics/source_audit.json`。无需联网寻找一个不明来源的“最优值”。

`perf.rep` SHA256 为 `34ac950a52da1e224e8bef3cc74adcf2bfc6ef26da574b4506bb1019dd1d8b50`。摘录：

|报告行|LOTSTARTS|LOTCOMPS|CYCLEAVG（时:分:秒）|ONTIME%|WIPLOTAVG|
|---|---:|---:|---|---:|---:|
|WarmUp|23045|21019|856:30:16|89.40|2160.93|
|Period_1|20879|20716|897:25:17|90.66|2139.70|
|Period_2|41807|41631|896:05:33|92.44|2136.13|
|Period_3|62626|62369|897:48:21|91.65|2140.43|

注意 Period_2/3 是预热后累计值，不能当独立年度 throughput：`period.txt` 仅 WarmUp 行 `RESET=yes`，后续行均 no。`Period_1` 2019 年的 20716 完成 lot 与周期/准时率可作为**待对齐参考值**，不作为当前新实验的直接减法基线。

归档日志显示 AutoSched AP v11.3.0.42，运行 1460 天，到 2021-12-31 00:00:00；累计输入 85671 lot=2156+83515，输出 83388，末 WIP 2283。这个守恒与本次输入规模和 1460 天投料计数一致。然而存在以下独立不匹配：

1. 包内 `options.def:15` 是 `order_high_SL_92PCTL.txt`，报告关联 `options.sav` 和日志则使用旧名 `order_high_ServiceLevel`。虽然数量吻合且名称指向高服务水平，尚不能证明是同一份逐lot交期字节。
2. 包内 `runcntrl.def` 为 360 天一次 + 10 次 autorep；归档已有日志是 1460 天，不能用前者解释为同一运行历史。
3. 高 SL 逐lot表相对于周期流有约 0.8–1.2 倍交期变化；相同释放量下，CR 排序、准时率和累计逾期会改变。新研究不能把该变化悄悄忽略。
4. 归档不是匹配新适配器随机场的多个独立重复；没有足够证据把报告单值波动范围当可信区间。
5. 适配器在故障、PM、uniform、初始WIP保留等处改动语义；初始绑定、CQT、逐wafer cascading也存在边界。

原论文 [10.1109/TSM.2020.3001933](https://ieeexplore.ieee.org/document/9115710) 用来确认测试床与推荐的吞吐/周期/准时率校准方向，不能把论文长时域数据直接与 1/8/24 小时、7/14/28 天的新实验相减。Zenodo [15088815](https://zenodo.org/records/15088815) 描述仍为关联文章 draft title，未找到可核定的最终数值表，不自行补写。

## 解除阻碍的具体路径

先分别冻结两个数据身份：本研究 `periodic-21-stream` 与参考对齐用 `explicit-high-SL-92`，保持旧文件不变。对后者逐条使用官方 START/DUE，验证已保存报告的文件身份，或重新运行可访问的官方软件得到具有输入哈希、seed 和参数的新参考。若不能取得 AutoSched，仍能做透明的版本间对照，但结论仅限该对照。

接着为官方排名、batch/wake/LSSU、PM/故障、lot/wafer cascading、CQT报告和未知初始化历史分别建立微场景；先定清需要原样复現的策略和可接受的明确修订。维护两条假设，避免为了逼近某个数值反向调参而隐去差异。

对齐的长时域参考需要明确预热与统计口径。官方包的一年预热可以作为复現候选；新研究的预热应独立做 WIP、吞吐、产品周期与设备族负荷的时间序列稳定性诊断。不能因原论文采用一年，就声称新环境任何一年后都稳态。

容差尚未冻结。建议在匹配口径的多 seed 重复后，事先定义业务容差及置信区间规则；若参考仅有一条运行而无方差，应把结果当差异诊断，**不设置任意百分比容差来宣称通过**。正式 A/B/C 排名之前必须诚实给出哪些校准条件满足、哪些未知。未依赖官方数值等价的控制器开发、快照恢复和独立覆盖检查可以继续。

## 2026-10-10 入口与版本补查

本次在A24独立执行期间只读检查网页和少量本地源码，没有下载或替换锁定数据、启动校准仿真或修改vendor。[官方入口](https://p2schedgen.fernuni-hagen.de/downloads/simulation)仍列有SMT2020下载；当前网页没有提供归档中high-SL订单与已保存报告的逐文件对应证明。

[Zenodo记录15088815](https://zenodo.org/records/15088815)的检索内容标明2025-07-03发布、版本RefactoredVersion2025，说明仍使用关联文章的暂定标题。直接读取该记录曾超时，检索返回不替代归档源码核验。按暂定标题和作者组合检索，本次未取得可绑定到所用输入、seed、RESET与参考统计窗口的新数值表；这只是本次检索结果，不声称该论文或数据不存在。IEEE全文入口本次返回JavaScript访问校验，未据此填写未读数值。

本地再次静读`vendor/PySCFabSim-revised/simulation/greedy.py`，确认`parse_args()`后仍无条件替换dataset/days/dispatcher/seed，且WandB默认启用。因此原CLI不能作为已可复现的LVHM/CR固定seed入口。后续独立调用层必须显式传入配置并关闭外部插件，先验证实际入口，再运行匹配配置的校准；不能把当前研究的A24容量实验当作该项校准。`official_calibrated=false`保持不变。
