# 完整 SMT2020 Dataset 2：来源与执行语义（开发版）

核查日：2026-10-09，Asia/Shanghai。该数据是公开仿真测试床，不是企业生产流水。完整原包、锁定软件归档、获取失败日志均保留在 `data/raw/smt/`。本实验的 `smt-adapter-v2` 是透明的修订实现，不应称为 PySCFabSim 或 AutoSched 原样复现。

## 版本与获取

- 官方入口：[FernUniversität simulation downloads](https://p2schedgen.fernuni-hagen.de/downloads/simulation)，原包 [SMT2020.zip](https://p2schedgen.fernuni-hagen.de/fileadmin/ess/uploads_p2schedgen/SMT2020/SMT2020.zip)。110,359,829 字节；SHA256 `19c07bfb68cbc5838429531f27d51428155bb11baf58dc79f8caf84b09856872`。
- 采用包内 `AutoSched/dataset 2/LVHM_Model/LVHM_Model.asd/` 的全部官方工厂模型输入。整个四场景原包不删减；Dataset2 所有原始文件另存 `data/raw/smt/official_dataset2/`。
- [Zenodo 15088815](https://zenodo.org/records/15088815)，`RefactoredVersion2025`，2025-07-03 发布；24,466,742 字节；发布方 MD5 `b98bf4093efaf705e613703701382855` 已核对；SHA256 `3bf08f4bbc62daad42934022f15546216d5bcd8a8b4e3af9c9028498d9036028`。
- [PySCFabSim-revised](https://github.com/david-dd/PySCFabSim-revised/tree/RefactoredVersion2025) tag 对应 commit `ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1`。GitHub 和 Zenodo 压缩格式不同，但归档内158个文件内容逐项SHA256完全相同。vendor不修改。
- 原论文：D. Kopp, M. Hassoun, A. Kalir, L. Mönch, *SMT2020—A Semiconductor Manufacturing Testbed*, DOI [10.1109/TSM.2020.3001933](https://doi.org/10.1109/TSM.2020.3001933)，2020。论文身份由上游README和官方测试床文档交叉确认；未把它当成数值参考最优解。
- Zenodo 描述的关联文章标题仍标 draft：*Implementing the SMT2020 Wafer Fab Data Sets Using Different Simulation Packages*；未独立确认最终出版版本，不能自行补写。
- 许可证：本次官方包和固定源码未发现明确 LICENSE/COPYING，Zenodo网页Rights的License项未给出可读标识。记录为“公开可获取、授权条款未明确”，不擅自标为MIT/CC。当前本地研究保留出处；不自动发布第三方源码或数据。

## 数据完整性

`data/smt/conversion-manifest.json` 是每文件原字节哈希→规范化输入哈希映射。仅做UTF16→UTF8、CRLF→LF、删除全空制表行、将tool多行排名续行合并为分号；不修改数值、不删批次、不删设备、不删工序。

官方Dataset2包含10条产品工艺、4013个工艺步骤、106个设备族/表行、1313个资源实例，其中 **913台生产设备 + 400个虚拟Delay_32等待资源**。Fab-to-Fab运输以时间延迟实现，不占另一组“运输生产机器”。初始WIP为2156批，投料表21条周期流，每批25片。

重要差异：Zenodo软件自带的LVHM副本删除了一条 `SuperHotLot_3` 投料流及2条SuperHot初始WIP，只剩20投料流/2154 WIP。实验默认使用完整官方输入，不用该删减副本。数值规范化后其他18个输入文件与软件副本对应内容一致。见 `official-vendor-comparison.json`。

## 实際约束覆盖与边界

|项目|固定上游行为|本轮适配与审计|
|---|---|---|
|全厂路由、重入|FileRoute按完整route文件；反复访问同设备族|保留所有route/step、所有设备族；事件逐步流转，不转成静态FJSP|
|组批|原greedy按part+step选择，kernel.dispatch自身不验证|内核和独立审计都要求同part、同route step/name；lot数为BATCHMN/MX除25；严格min/max|
|设备资格|按family与lot-to-lens dedication|state只列当前合法lots；动作执行再次检查；独立审计按源manifest重建|
|换型|minrun只由greedy约束；get_times选route setup优先，再矩阵，再空setup默认|动作和audit强制minrun；setup耗时按同规则；空setup清空机台setup，保留上游语义；PM/故障清空setup但不清空minrun剩余计数，恢复后仍先满足原minrun所需setup，这是本版本固定约定|
|日历故障|随机全局流；对已注册lot/machine events延时，但idle机器不阻塞|按machine/calendar/occurrence键控；idle也不可派工；加工中的lot和机台均暂停/续作；在运输中的lot不被追溯延时；重叠停机串行累计|
|时间PM|dispatch提前吸收截至预估machine完成的PM，主要延迟机台但不延迟lot|按原日历时刻触发；与故障一样暂停/续作；下一PM保持scheduled-start+repeat（含PM时长的周期）；这是显式语义修订|
|计数PM|按派工片数减计数、跨阈值即在machine_time加PM|保留阶梯触发/重置（不结转超量）；PM在本次加工结束后占机，lot可转运；若cascading本次尚未全结束则等待其process end|
|运输|下一步骤transport分布加入lot完成时间；Delay location无运输|保留；独立重算lot加工/装卸/运输；不将虚拟Delay当生产机|
|cascading|processing_time与cadence分别抽样/计算；无完整slot2阻塞|保留cadence计算，加显式占槽限制与process-end释放事件，audit独立检查。在完整官方lot-cascading数据上验证各族max(process_upper+load/unload-cadence)≤min(cadence)，因此无需额外slot2阻塞；超出该不变量输入fail-closed。wafer-cascading仍按整lot的等效cadence表达，不将2lot占槽说成2wafer内部槽；不宣称通用AutoSched内部实现等价|
|抽检|StepPercent抽样决定是否跳步|以lot+step+visit独立键控；跳步事件显式记录，audit重算|
|返工|REWORK抽样回RWKSTEP|以lot+step+visit键控；显式回流，包含返工后再次采样；本轮不把单次原route完成等于lot完成|
|机台绑定|SVESTN=yes时将FORSTEP绑定当前机台|保留，所有动作/audit校验；初始快照未给此前机台绑定，初始dedication为空|
|CQT|源代码明确TODO/deactivated|**不激活、不声称已验证CQT硬约束**；与所选固定上游执行范围一致|
|hot/superhot|内置数据删SuperHot；按priority排|恢复完整官方记录，范围外固定priority规则；无临时抢占当前加工|
|Q-time/精密搬运/人员/晶圆拆批|没有完整生效实现|不宣称覆盖|

统一时间单位是秒。上游 `tools.UniformDistribution(m,l)`使用 `m±l/2`，与官方offset定义不符。独立审查后adapter-v2明确改为 `m±offset`：官方fromto 7.5/2.5分钟执行U[5,10]，与随包文档一致。开发v1轨迹保留，已标deprecated；v2不是不改源码语义的原样复现。

## 初始状态和窗口

推荐冻结为初始官方WIP快照、0额外预热、8小时窗口[0,28800]。初始各设备空闲、无setup、无历史binding，WIP在CURSTEP前等待，初始片数PM阈值和日历首次PM按attach在同族内均匀错开。WIP的历史release age按同名投料流的交期lead time从WIP due反推，用于cycle-time统计；这是上游的年龄重建约定，不是已观测真实release记录。WIP可用时刻为max(0,历史release)，投料START/REPEAT/LOTSPERRPT则按官方表。

上游FileInstance会漏掉 `CURSTEP >= len(route)-1` 的WIP；本轮保留全部官方WIP。先前软件自带数据的开发试跑单列 `preofficial_pilot701`，不能混入正式完整数据结果。

受控ID建议固定 **9=DE_BE_12 第1台（非组批）**、**790=Diffusion_FE_100 第1台（5–6 lots/batch）**；2/913=0.219058%。其余生产设备和全部虚拟资源固定使用 `setup-aware-priority-FIFO-demand-v1`。同一决策时刻先收取控制器动作，然后固定策略处理非受控机台。Agent控制当前lot集合、具体机台及组批/显式等待；不控制其余911台生产机。这不是全厂自主排程结论。

当存在可派工的受控机台时返回当前状态。B直接给出 `{dispatches:[{machine,lot_ids}],wait_seconds}`。等待0..1800秒；无动作必须显式等待。每窗口默认16个决策上限，超限抛出失败，绝无规则接管。状态含当前候选、加工期望、setup、priority、due及排队时间，不含故障/PM未来随机抽样或其它方案结果。

## 随机公平性

日历首次间隔、历次故障时长与重复间隔按seed+calendar(machine identity included)+occurrence键控，无全局可变random流。抽检/返工按seed+lot+step+visit；处理/运输/节拍按同一批的排序成员身份+step+visit。选择不同批成员会改变该批的加工抽样（策略内生），相同批成员的抽样不受其它事件执行顺序影响。固定故障日历跨方案完全可比较。模型随机性单列，场景seed重复3次不视为3个独立工厂场景。

## 优化与指标

A/C共用 `src/smt/optimizer.py` 的CP-SAT当前决策模型：每机至多一个兼容batch，lot唯一分配，资格/minrun已经在state中约束；最大化fill+priority+waiting减setup耗时的整数奖励。它是滚动的即时可行动作选择，**不是全工厂、多步lookahead最优求解器**。返回真实solver status/objective/bound/参数/时间。B从不调用此模块。

建议主指标冻结为受控两设备族的排队面积（lot·秒，越小越好），辅以受控完成工序批数、全厂吞吐、完成批周期/延期、末WIP/逾期WIP、batch填充、设备占用及决策/模型/求解成本。该短窗口不适合断言稳态工厂产能。窗末未完成batch保留且计入WIP；cycle time只对完成批统计，并明确幸存者条件。

## 已运行证据与限制

官方seed701、8h完整工厂开发pilot：6863次派工、24239条事件、4个控制决策、5次受控派工（2批处理+3非批），13批完成、末WIP2174、受控完成8个operation-lots，末窗1个batch未完成；含occupancy guard模拟CPU约11.22秒。`official_v2_guard_pilot701/audit-final-source-bound.json`独立轨迹重算通过。这是开发A pilot，没有模型请求，也不是B/C验收。

独立audit不调用环境、优化器或success标志，重建lot状态、资源准备时刻、分布抽样、资格、batch、setup、minrun、binding、PM/failure时延、抽检/返工、终端守恒和指标；正式审计必须传 `verify_data_dir`，独立CSV解析绑定全部route投影、展开设备与物理/虚拟计数、初始WIP/投料lot生成、setup/minrun、calendar及piece-PM；同时核对完整源文件hash清单。动作声明与实际派工双向逐项消费，未执行声明也使审计失败。完整AutoSched对照运行未执行，仍有以上版本语义边界。
