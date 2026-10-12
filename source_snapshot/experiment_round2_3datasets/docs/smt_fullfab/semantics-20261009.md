# SMT2020 全厂输入与语义复核

核查日期：2026-10-09（Asia/Shanghai）。本文件属于新研究，未改写旧实验结论。结论是**锁定输入完整性通过，官方数值校准尚未通过**。旧 `smt-adapter-v2` 是修订内核；数据完整并不意味着与 AutoSched 或固定上游运行等价。

可恢复入口：

```sh
.venv/bin/python -m src.smt_fullfab.source_audit --output artifacts/smt_fullfab_semantics/source_audit.json
.venv/bin/python -m unittest tests.test_smt_fullfab_source -v
```

审计模块只使用 Python 标准库读文件；不调用模拟器或模型，不修改既有源文件和冻结清单。机器可读报告保存逐文件预期/实际哈希、原始证据行号、官方包报告表、缺失历史绑定 lot 明细。`source_integrity_passed` 与 `official_calibration_passed` 为两个独立字段，不能互相替代。

## 锁定来源与计数

在线复核了 [官方入口](https://p2schedgen.fernuni-hagen.de/downloads/simulation)、[Zenodo 固定版本](https://zenodo.org/records/15088815)、[固定 GitHub tag](https://github.com/david-dd/PySCFabSim-revised/tree/RefactoredVersion2025) 和[原论文出版记录](https://ieeexplore.ieee.org/document/9115710)。Zenodo 标注 2025-07-03、`RefactoredVersion2025`、MD5 `b98bf4093efaf705e613703701382855`。DOI 重定向的文本抓取失败；IEEE 记录可访问但未返回论文正文。数值证据以已锁定官方包内可直接检查的报告为准。

|项目|实测|
|---|---:|
|生产工艺大组|11|
|生产设备族|105|
|生产设备|913|
|虚拟设备族 / 虚拟等待资源|1 / 400|
|产品路线 / 总工步|10 / 4013|
|初始 lot / 每 lot 片数|2156 / 25|
|周期投料流|21|
|三份归档、规范化输入、vendor 源文件哈希|3 / 20 / 158 全通过|

生产大组为 Def_Met、Dielectric、Diffusion、Dry_Etch、Implant、Litho、Litho_Met、Planar、TF、TF_Met、Wet_Etch。`Delay_32` 不属于生产决策设备。原 `tool` 表 106 行、总资源 1313 与上述拆分相容。

- 官方归档 SHA256：`19c07bfb68cbc5838429531f27d51428155bb11baf58dc79f8caf84b09856872`，110359829 字节。
- Zenodo 归档 SHA256：`3bf08f4bbc62daad42934022f15546216d5bcd8a8b4e3af9c9028498d9036028`，24466742 字节。
- GitHub 固定归档 SHA256：`12dbe8e63eeff82e13d3cbb2d20a69b2b371004257f7e0c305c12ed7d485505e`，24476390 字节。
- 固定上游 commit：`ae3d55ef08cd0d6bc9cd114eb800e6c920dbede1`。20 个转换映射的原字节与官方 ZIP 对应成员一致，转换后字节与旧冻结清单一致。

## 投料版本并非完全相同

新研究按用户指定继续使用规范化 `order.txt` 的 21 条周期流，不擅自替换。其每一流相对交期固定，全部 `HOTLOT=no`；10 条优先级 10、10 条优先级 20、1 条 `SuperHotLot_3` 优先级 30。不能从名称推断该流启用了 AutoSched 的下游机台预留功能。

但是，官方 `options.def` 第 12–16 行指向 `order_high_SL_92PCTL.txt` 与 `WIP.txt`；`order.txt` 前有 `~`。官方归档旧 warning 表明带 `~` 的文件名曾被尝试读取但找不到，不能仅凭该字符断言它是通用注释语法。

高 SL 表有 **167129 个非空 lot**，21 个 ORDER 身份；物理表含 148496 个全空行，315625 不能当有效 lot 数。对全部记录按每 ORDER 的序号比对：投料时刻相对 21 条周期流的差异在约 -1 到 0 秒（文本时间舍入），高 SL 的交期 lead time 则为周期表约 0.8–1.2 倍。因此两种输入的投入量相同并不能证明准时率、CR 或逾期指标可直接对齐。

|半开窗口 [0,T)|1 小时|8 小时|24 小时|7 天|14 天|28 天|365 天|1460 天|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|周期流新增 lot|21|31|71|411|811|1612|20889|83515|
|高/中/低 SL 明细表新增 lot|21|31|71|411|811|1612|20889|83515|

这些数字不含初始 2156 lot。8 小时 31 lot 不能用于其他窗口。

## 必须保留的语义边界

|机制|来源与核查|当前明确边界 / 后续要求|
|---|---|---|
|CQT|10 条路线共有 264 个 CQT 起点。官方文档 §3.13 明确只提供字段供定制；固定上游 `instance.py:156` 标 TODO/deactivated。独立 [WSC 2020 论文](https://informs-sim.org/wsc20papers/194.pdf) 研究的是增加控制逻辑后的模型。|adapter-v2 没有 CQT 状态/违规计数/约束。不可称“完整 CQT 硬约束已验证”；也不应把基础官方包误称已有这些控制。初始 433 lot 已处在 CQT 起终步之间，但历史起点完成时间未知。未来若增加监控，应将这类窗口标 unknown，不能补零假装合规。|
|绑定|路线有 73 条 SVESTN/FORSTEP 绑定规则。初始 1311 lot 的 CURSTEP 位于某历史绑定源工步之后、目标工步之前或恰为目标工步。|WIP 没有历史机台 ID，无法唯一恢复绑定。冷启动空绑定为建模假设，必须与后续通过实际预热产生的绑定区分。不能随机补设备并叫真实历史。|
|lot cascading|401 工步、22 设备族。由源表独立计算每族 `max(工时上界+装卸−cadence) <= min(cadence)`，全部通过。|该固定数据的无停机加工区间内，不需要额外 slot 2 堵塞。并不证明通用两槽内核等价，停机、setup、重入等组合仍需场景测试。|
|wafer cascading|1267 工步。固定上游以整 lot 总工时与 cadence 表达。|没有逐 wafer 槽位轨迹；整 lot 的占用上限不能称逐晶圆精确复現。|
|时间 PM/故障|官方 PM 的 MTBPM 包含 PM 本身时长；首次 PM 同族按设备均摊。官方 TTF/TTR 指数抽样；PM 时长 uniform(mean,offset)。|adapter-v2 按日历触发/暂停续作/重叠串行/设备 setup 清空是显式修订。不得把内部独立审计通过当 AutoSched 数值等价。|
|计数 PM|片数跨阈值后 PM，占机但 lot 可转运；同族首阈值错开。|适配器不结转超量，须冻结该约定并测临界值/组批/cascading组合。|
|uniform/运输|官方文档明确 offset，Fab→Fab 为 U[5,10] 分钟。|旧固定上游用 m±l/2；adapter-v2 修为 m±offset，合理但属于实现差异。|
|抽检/返工|源表 StepPercent 与整lot返工存在。|以 lot、step、visit 键控随机，批成员变化会改变加工抽样。仍需完整轨迹独立核验。|
|快照|WIP只含 lot/产品/优先级/片数/START/CURSTEP/DUE 等，无在制加工、设备setup、绑定、维护剩余量。|原始 WIP 只能称冷启动输入；完整快照须在选定环境中实际运行后导出队列、加工剩余、slot、事件、计数、绑定、setup、随机键等，并验证恢复等价。生成快照不等于稳态。|

本次是源数据与实现边界的核查；未执行多年 AutoSched 对照，也未用短期参考结果宣称已稳态。
