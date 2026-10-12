# C8 流式执行开发进度

截至 2026-10-09T21:34:43.334242+00:00，A全厂8小时与C全厂1小时已实际验收；C8尚未启动，正式运行仍为0。

已保存C1完整归属报告的新旧逐字段对照通过：除事先声明的版本/新增源证据外，无字段、类型、浮点位或数组顺序差异；原始2885文件重新核对未变。新审计峰值RSS217MB，对照旧1.35GB；耗时160.49秒，对照旧30.37秒，另保留454MB scratch。这是同一已存C1证据的审计成本，不能当作C8容量实测。

隔离C v3首轮52项小测通过。实际安装后重新跑77项（含复用52项和25项新增终末/安装检查）全部通过；这些是合成模型/工厂/工具边界，不能相加当作129项不同测试，更不等于真实C8成功。原代码、首测、安装差分与精确hash均保留。

把C1原日志和新scratch按A8的635次计划、C1的46次计划作条件算术，合计约17.79GB，高于旧16GiB未冻结提案。新提案为run+scratch+campaign共24GiB、启动空闲64GiB，child43200秒、outer46800秒、单次调用180秒、trace2GiB、事后峰值RSS8GiB、CP累计32秒。此为停止边界，并非完成保证；调用次数和累计token仍无限制。实际冻结前还须完成gate和进程守护独审/首测。

外层停止需覆盖模型CLI的独立进程组。新owner-pipe守护和supervised transport正在实现；旧transport、旧run和旧验收不改。当前公共入口仍阻止真实运行，尚未发布新C8注册或执行任何新模型调用。

证据：

- `artifacts/smt_fullfab_diagnostics/C8_saved_C1_parity_v2/summary.json`
- `artifacts/smt_fullfab_diagnostics/C8_controller_root_v3/result.json`
- `artifacts/smt_fullfab_diagnostics/C8_installation_root_v1/result.json`
- `artifacts/smt_fullfab_diagnostics/C8_installation_v1/manifest.json`
- `artifacts/smt_fullfab_diagnostics/C8_resource_envelope_v2/report.json`

共同非空闲快照、预热诊断、24小时/长窗口、辨别能力与敏感性、正式矩阵及最终报告仍在目标范围内，不能用当前阶段结果宣布研究完成。

后续验证（2026-10-09T21:56:12.521122+00:00）：owner-pipe守护21项良性进程测试通过；原始输出字节绑定修复后的supervised transport20项通过，包含真实良性Python子进程与假账本的组合检查。B新版7模块的82项合成链路测试通过，尚未执行新的真实B或完整私有物理循环。C已显式接入新transport，首次77项中76通过，仅公共入口错误文字与原固定断言不匹配；保留首测后只修一处文字，39项契约与3项安装复测通过，其余35项源及测试未变的通过证据复用。可执行对账见 `artifacts/smt_fullfab_diagnostics/C8_installation_v3/validation.json`，不能说首次全通过或一次新跑77项。独立复核通过，新的外层gate守护/验收接线仍待首测、审阅与冻结。C8与正式运行仍为0，调用次数及累计token无上限。磁盘/trace为检查点检测和最终接受上限，不是无瞬时超额的硬实时磁盘守护；超限会拒绝验收。
