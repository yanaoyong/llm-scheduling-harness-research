# SMT2020 独立只读审查

范围：`src/smt/environment.py`、`src/smt/audit.py`、`src/smt/optimizer.py`，官方 Dataset 2 LVHM 规范与数据，`artifacts/smt_development/official_pilot701/trace.jsonl`。未修改模拟器实现，真实模型调用0。以下把已证实缺陷、已查无发生的风险及待复测修复区分开；开发pilot的success只是完成了窗口，不等于已通过官方语义验收。

截至本轮复测，两个已证实P1在adapter-v2、audit-v2及锁定官方LVHM输入上已关闭。下文保留发现时证据，末节记录修复后的独立复测；旧v1结果仍不具备官方分布语义合格性。

## 原阻止正式的问题（历史证据）

### P1 / 已在v2关闭：均匀分布 offset 被除以2，独立audit同错

官方 `data/raw/smt/SMT_2020_AutoSched_AP_documentation.txt` 第123–125行明确 PTIME2 是 offset，第213–214行同样定义维护时长的 MTTR2；第235行给出运输 U(5,10) 分钟。官方 `fromto.txt` 恰为 mean=7.5、第二参数=2.5 分钟，因此正确端点是5与10。

v1 `environment.draw` 和 `audit.sampled` 都采样 `mean ± width/2`，而 width 是未翻倍的官方 offset。实际运输因此变成 U(6.25,8.75)，加工/PM波动幅度也减半。审计虽然不import模拟器，但使用同一错误公式及模拟器输出的解释后manifest，故返回valid并不能检测该语义错误。

已即时通知主 Agent；正式运行已暂停，实施角色在修复 adapter-v2。必须用官方端点的手算断言检验采样，不再只要求两个实现互相一致。保留v1轨迹，重新运行修正后的开发pilot，旧结果不能晋级正式；审计版本和语义版本也需相应标注。修复后独立复测结果将在本文追加。

### P1 / 已在v2关闭：审计漏掉声明但未执行的动作，manifest与官方输入未语义绑定

对 official_pilot701 的内存副本，在 decision=1 的 action.dispatches 追加：

```json
{"machine":790,"lot_ids":["w999999-not-a-lot"]}
```

另外将 initial.manifest.physical_machines 改为 -17，其余轨迹和原文件哈希均不变。调用 `audit_trace(events, verify_data_dir='data/smt/SMT2020_LVHM')`，实测仍返回 `valid=true, errors=[], verified_input_hashes=true`（0.431598 CPU秒）。原始轨迹未修改。

原因一：auditor仅检查每个实际dispatch有相符action，未将action中所有声明反向逐一消费，也未确认动作内所有lot存在及合格。原因二：文件hash只证明所列原文件没改变，没有证明manifest机器数/资格/工时/路由/初始lot真的来自这些文件；甚至检查完整文件名集合也尚未强制。故 verified_input_hashes 不是“官方语义已核实”。

修复要求：一个action的每个dispatch必须有且仅有一条实际记录，在同一时刻、同一设备、同一lot集合执行；校验控机范围和lot存在/资格，检查未消费动作；从锁定原始数据独立导出/验证manifest字段和文件清单。可将后者分成独立source-conformance审计，但正式验收须二者通过，不能用共享 classes.Step 解释一次后两边照抄。

可重放负例脚本：`artifacts/review_static/smt_adversarial_check.py`。它只读已有trace，在内存改变单项，模型0、solver0，不写回原轨迹。修复后执行：

```sh
.venv/bin/python artifacts/review_static/smt_adversarial_check.py <修正后pilot的trace.jsonl> --require-rejection
```

## Cascading 两槽：已检查现有数据，通用边界仍需保护

官方 AutoSched 文档第305–333行描述容量2的连续槽：当前lot的slot1间隔结束后，只有slot2空闲才能转入；slot1释放后下一lot才可进入。v1仅以cadence控制下次接受时间，没有显式两槽状态；不能因此声称对任意异速工序都是完整两槽仿真。

对官方pilot的6839条dispatch与36次downtime重建过程结束时间，检查 lot-cascading 设备是否在已有2个lot加工时又开始第3个：**0次**。进一步按官方正确offset上界检查每个cascading family：`max(process_upper + load + unload - cadence) <= min(next cadence)`，现行所有lot级family均满足，因此当前源数据的普通交接不会触发第三lot阻塞。不能将代码缺显式槽状态写成这个pilot已发生超容量。

实施角色拟增加在加工总数<=2的runtime保护、process_end唤醒和独立占槽断言。审查反馈：这对当前数据是合理加固，但若输入不满足上述边界，仅挡第三lot仍不够；第二lot等待slot2期间也必须推迟自己的process_end/lot_end。若不实现通用双阶段阻塞，应fail-closed拒绝超出已证明输入条件的数据，并用异速手例验证拒绝，而不宣称通用语义等价。PartInterval的wafer流水不是“两批lot=两片wafer”，需要单独说明lot内聚合假设；不能混淆二者。

## 逐项数据与轨迹核对

| 项目 | 当前核查事实 | 限制/待验收 |
|---|---|---|
| 官方数据对应 | conversion-manifest包含官方zip条目与原始/输出哈希；10条完整route均导入，所选官方订单21行、WIP2156行。vendor副本少SuperHotLot_3的一条订单和两条初始WIP，本轮输入保留它们 | 需要独立source-conformance将这些原字段绑定到运行manifest |
| 生产/虚拟资源 | manifest中913台生产设备、400个Delay虚拟资源，2/913受控；未把虚拟等待加进生产设备数 | auditor须独立重算计数；已发现负计数也能通过 |
| 组批 | 官方10个batch family均crit_sameroutestep、单位pieces；全部投料/WIP lot为25片。每组只允许同part与同route-step，容量从wafer数换算lot数 | 固定25片对当前数据成立，变化lot-size时应拒绝或重算；负例要单独触发兼容/最小/最大批量 |
| setup/minrun | 原route所有WHEN为need或空；有401个setup步骤，其中182个route内整数时长，另219个查setup表；9种implant gas setup MINRUN=7 | PM/故障重置setup后剩余minrun如何处理须在适配器语义表明确，不能仅援引未修改上游 |
| 件数PM | 当前pilot发生11个piece-PM事件；计数与duration写入dispatch，之后机器ready包含PM时间，lot可先转出/运输 | 计数越过阈值后的重置与串行PM语义需冻结，并以不同批量的手例验证 |
| Calendar PM/故障 | 1697个calendar条目，213种件数PM附着到606台机器；pilot有36次日历down。key包含attach、machine、calendar及occurrence，独立于派工调用次序 | adapter主动串行重叠down并暂停/恢复未完成processing，与上游事件实现并非字节等价，须明确其语义依据 |
| 运输 | 原始所有生产位置Fab，Delay为另一个位置；Fab→Fab应U(5,10)，Delay前后无运输时间 | v1分布错误为P1；运输与processing_end/lot_end分离的处理使运输中lot不因原机故障延迟，逻辑方向正确 |
| 抽检/返工 | 抽检与返工按lot、step、visit分别键控；官方返工类型均lot；pilot有833个skip | pilot未发生rework，必须靠独立返工正/负手例补足，不能说pilot覆盖了返工路径 |
| 流转守恒 | 本pilot 2156初始+31新投=13完成+2174终末WIP，窗口完整到28800秒；初始WIP留在分母 | audit不能仅复用终末计数；当前逐lot状态重建有价值，但仍需修动作与源语义缺口 |
| 结束窗口 | 受控15个operation-lots发出，8个完成；有1个未结束组批保留为在制品，没有当作全完成或丢弃 | status=processing合并了运输等待，报告使用“未完成”更准确；利用率scheduled occupation包含setup/PM，不等于纯加工利用率 |
| Lot-to-lens | 已观察到的dedication设置与后续使用在环境和audit中逐lot核对 | 原始WIP不携带窗口前机器绑定；初始化为空的边界必须声明 |
| CQT | 源route有264条非空CQT数据，但官方文档413–418行明说仅提供数据供customization；上游相关执行代码也disabled | 可以在所选未启用版本中不作为硬约束，但必须列为“数据存在、当前未启用/未审计”，不能宣称全部半导体约束覆盖 |

## RNG 公平性

日历长度/重复间隔由 `[calendar,key,occurrence]` 决定；抽检/返工由lot、工序、visit决定，改变派工次序不会按共享PRNG的消费次序错配这些事件。投料是官方固定间隔，三个方案共用同一外生投料。

processing、cadence、transport的key包含排序后的完整batch lot集合，保持同一批成员时与调用次序无关；改变组批成员就改变随机变量的key。因此只能称使用同一事件键控随机场景函数，不能声称不同组批方案的每次加工/运输时长逐项相同。件数PM触发时间是策略造成的内生结果，但其第n次duration按机器/PM/n固定。模型state只含当前可观测候选、当前setup和期望工时，没有future calendar draws或未来返工信息；完整manifest留在审计trace中，运行模型不得读取该trace。

## A/C 优化器范围

`solve_action` 是当前空闲受控机器上的精确lot/batch选择模型：为候选lot置0/1，组内min/max约束，每机最多一个group，每lot最多一个机，最大化固定的fill+priority+waiting−setup分数。它与使用固定FIFO规则直接代替A不同，但也不是全厂长期排程或跨未来事件的滚动窗口优化；应按现代码名称“rolling immediate dispatch”如实报告。B必须提供具体lot_ids而非只选一个规则。

目前两个受控设备仅占913生产设备的0.219%；pilot的4次决策/5次dispatch支持测试batch与nonbatch闭环，但不能推导全厂自主优化或稳定业务收益。正式需在同一范围、同一外部策略和相同终止窗口下比较，不将不同seed的随机性与同场景模型重复混为独立工厂场景。

## 修复前验收状态（保留）

- 静态来源/手算审查已完成，另见review-static.md。
- SMT v1在官方分布语义上不通过；两个审计负例目前复现通过了本应拒绝的轨迹。
- P1已即时报告且主 Agent 暂停SMT正式；修复正在进行，本文暂不标记关闭。
- 本角色新增小检查累计CPU低于2秒，真实模型0、额外求解器0；没有重跑完整仿真。

## v2修复后的独立验收

审查日期2026-10-09。正常输入为实施角色重新生成的 `artifacts/smt_development/official_v2_guard_pilot701/trace.jsonl`，SHA256 `a846a746f36e28b5a06213c4d3b153eb2e9d5832cc797369efd582db99a44c98`。本角色只读重放，没有重跑完整仿真或模型。正常轨迹24239个事件，独立重算通过：13批完成、末WIP2174，`verified_source_semantics=true`。

修复后的 `source_check.py` 用标准库CSV直接解析完整官方规范化文件，不import环境、vendor Step或共享解释函数。它独立绑定4013步工艺投影、展开设备及物理/虚拟数量、所有初始/新投lot及priority、setup/minrun、calendar、piece-PM和完整文件名/hash集合。由父运行器继续负责将数据hash对应冻结来源锁，而不是任意一个同名目录。

|独立检查|实际结果|
|---|---|
|追加声明但未执行的不存在lot|拒绝：action lot not currently waiting / previous action has unexecuted dispatch|
|manifest生产设备数改为−17|拒绝：source physical machine count|
|首步加工均值增加1秒|拒绝：source routes/processing/sampling/rework/transport|
|源hash清单删除part.txt|拒绝：source input hash inventory|
|初始lot优先级增加1|拒绝：source lot identities/initial WIP/release/deadline|
|环境与审计分别接收均值450、offset150秒|两者传给uniform的端点均为300、600秒，符合官方U(5,10)分钟|
|手工2-lot合法批、合法占用两槽|均通过|
|手工欠批、超批、异part混批|分别拒绝，命中batch min/max或batch incompatible|
|已有两件仍加工时加入第三件|拒绝，命中physical processing-slot capacity|
|官方模型中的lot-cascade时长改为极长不对称值|初始化域检查拒绝，命中slot2 blocking|
|5秒件数PM与100%返工手例|16秒lot结束/21秒机台释放通过，返工回step1/visit2通过；缺少必须的rework事件被拒绝|

执行命令（显式工作目录为实验根目录）：

```sh
.venv/bin/python artifacts/review_static/smt_adversarial_check.py artifacts/smt_development/official_v2_guard_pilot701/trace.jsonl --require-rejection
.venv/bin/python artifacts/review_static/smt_fix_acceptance.py
.venv/bin/python -m unittest tests.test_smt.SmtTests.test_hand_calculated_batch_trace tests.test_smt.SmtTests.test_piece_pm_after_processing_and_rework_runtime tests.test_smt.SmtTests.test_asymmetric_cascading_rejected -v
```

实际结果保存在 `artifacts/review_static/smt_adversarial_v2_result.json`（2/2负例拒绝，1.101525 CPU秒）、`smt_fix_acceptance_result.json`（12/12检查通过，1.232548 CPU秒）、`smt_selected_acceptance_tests.log`（3 tests，0.746秒，OK）。前两个脚本由本审查角色独立编写；最后三个测试由实施角色新增，本角色读代码并实际复跑。检查脚本模型调用0、求解器调用0；没有将开发求解结果作为正式质量记录。首次缺陷复现与结果仍保留，未覆写任何原trace。

验证时实现SHA256：

- `src/smt/environment.py`：`04598803fd84239ec1de464505f5450e9a82dbb6ea0b73d13227a1ab55b8c5c6`
- `src/smt/audit.py`：`a0b96922c76950f323a5c60bf34051419fc3955bfe982973c77bf7da9aa50cf1`
- `src/smt/source_check.py`：`973bf61ea9754101795cf6875967479ad0ca7fd65938bf2799405ceba4c4b786`

## 保留的边界与集成验收职责

两个P1已关闭，不再阻止当前锁定输入的开发贯通。当前审查不是完整AutoSched软件交叉运行证明，也不证明未声明的业务语义：lot-cascade仅在已验证时长不变量域内有效，wafer-cascade按整lot聚合；WIP之前的绑定/机台setup未知，初始化边界明确；CQT不启用；重叠down串行累计、件数PM越阈值不结转均是冻结适配语义。`docs/smt-semantics.md`已经逐项明示这些范围，没有将两lot占槽说成两wafer内部槽或称完整原样复现。

独立审计接口可回放旧v1以保存历史，但旧v1分布语义不合格，不能因为兼容回放返回valid而晋级正式。正式版本必须由主运行器核对trace的adapter版本、seed、horizon、受控机器ID、warmup/outside-policy与冻结config相同；`source_check`只绑定源数据，不替代协议配置/版本绑定。正式运行仍须完成真实B/C闭环、固定参数辅助对照和整批离线重放；本次开发审查不代表正式矩阵已验收。
