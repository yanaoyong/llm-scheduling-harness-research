# SMT2020 全厂 A/B/C 续作

证据截止：**2026-10-10 04:19:39 UTC（北京时间12:19:39）**。A冷启动1小时、8小时及C冷启动1小时已通过开发门槛；A24与C8失败，B完整1小时尚未通过。**正式运行0条，尚无完整配对A/B/C样本，完整目标未完成。** 本页固定此次证据截面，不自动追赶运行中的文件变化。

| 记录 | 截止时点的状态与证据边界 |
|---|---|
| A24，原会话29481 | 已退出，exit 1；推进58153.21888586596秒（约16.15小时），整次已提交1340版计划。末轮事件构造在首次proposal前触及5秒soft预算，candidate_evaluations=0、planned_operations=0、NO_PLAN，该末轮未提交。工具内部6.406438秒包含预处理及后续名义检查/目标计算，不能全部归为预处理。0模型调用，末轮未运行CP，也不是CP无解证明。[原失败封存](../../artifacts/smt_fullfab_diagnostics/A24_root_publication_v1/summary.json)、[静态诊断](../../artifacts/smt_fullfab_diagnostics/A24_no_plan_diagnosis_v1/README.md)。 |
| B v4，原会话71042 | 根代理在04:19:39 UTC通过原wait确认仍live（chunk d1cd32）。最近保存的[observation_006](../../artifacts/smt_fullfab_diagnostics/B_delta_actual_host_observation_v4/observation_006.json)截至04:14:14 UTC，仅有30条call_started、30条call_finished，0版提交计划，result尚不存在；这些计数不等于30次模型成功，也不是当前全研究账本汇总。原运行不重复启动。 |
| C8，原会话60905 | 已失败退出，推进6386.3947/28800秒、116版计划、233次请求；末次model_transport_error保留。完整失败状态准确恢复及非终末前缀独立审计通过，0次续作推进，未把原失败升级为完成8小时。[恢复收口](../../artifacts/smt_fullfab_diagnostics/C8_failed_recovery_actual_v1/root_completion.json)。 |
| 共同非空闲起点 | 参考CR恢复探测v3通过，T0=61、H=1800，验证814个继承加工任务和三个恢复分支的参考续作。它仅是工程恢复证据，不是稳态或真实A/B/C配对；实际共享A尚未运行。[参考探测收口](../../artifacts/smt_fullfab_diagnostics/shared_start_real_probe_actual_v3/root_completion.json)。 |

调用次数、token、未知用量准入及旧累计模型活动额度已由用户豁免；单次180秒与每条运行原登记的资源边界仍保留。**494次尝试、8,567,181已知输入加输出token、4次未知用量是B v4启动前的历史截面**。B v4继续追加原统一账本，本次未读取实时账本或重新汇总，当前总数/token未知，金额也未知；不把历史数字当当前总计。此前独立中性通道诊断成功（总耗时上界22.179699秒、5,107 token、模拟0秒）只证明该次通道可用，不代替C8或其他排程完成。[通道诊断](../../artifacts/smt_fullfab_diagnostics/C_channel_diagnostic_actual_v1/root_completion.json)。

相关测试证据按具体版本区分：根代理已通过的[218项检查](../../artifacts/smt_fullfab_diagnostics/shared_A_long_trace_root_checks_v2/result.json)只适用于该报告锁定的候选与输入。下列后续安装或新版本均仍待串行首测，不能继承218项的通过结论：

| 后续版本/接线 | 待首测数量 | 当前结论 |
|---|---:|---|
| 安装后的共享A worker / launcher | 35 / 10 | 实际共享A未运行 |
| 共享C控制器 / 独立归属审计 | 23 / 46 | 尚未验证真实共享C |
| 共享B控制器 / 独立归属审计 | 22 / 48 | 尚未验证真实共享B |
| 长轨迹生产候选v2 | 58 | 未首测、未安装；不证明长窗容量，也不修复原A24的NO_PLAN |

原B v1/v2/v3及更早恢复段的失败、费用和输出保持原记录。B v4控制器82项、gate70项、宿主17项及安装后的状态读回59项根代理测试已经通过，但测试通过不等于正在运行的B全窗口成功。A24原始退出与成本链已经闭合：连续根墙钟上界3650.292847834秒、完整材料11,832,182,551 bytes、峰值RSS5,190,516,736 bytes均在原登记限额内；后验只读status实耗另37.05秒（上界37.06秒），准确恢复尚未执行。窗口失败不因资源未超限而通过。

逐条要求与未完成项见[研究验收矩阵v2](RESEARCH_ACCEPTANCE_MATRIX_v2.md)；[原矩阵](RESEARCH_ACCEPTANCE_MATRIX.md)保留06:21北京时间历史原字节。本次文档原件、读取证据及差异见[更新交接](../../artifacts/smt_fullfab_diagnostics/research_docs_update_v2/static_handoff.json)。以后状态以新的原始结果和[ACTIVE_WORK](../../progress/smt_fullfab/ACTIVE_WORK.json)记录为依据，不倒填本次截面。

本目录是独立新研究入口。原 `round2-final-accepted-v1`、旧报告与181条历史记录不属于本次全厂验收，也不改写。完整要求见[TASK.txt](TASK.txt)。C1新旧流式归属19029个可比较节点一致及2885份原材料复核，只是原C1的等价与成本证据；不改变随后C8失败。详见[原实测对照](../../artifacts/smt_fullfab_diagnostics/C8_saved_C1_parity_v2/summary.json)。

## 已落实的边界

全部 913 台生产设备由本方案的明确计划负责；400 个虚拟等待资源由共同环境推进。没有后台生产规则替 A/B/C 补排。计划表示保存任务、批成员、设备、顺序、开始下界、有效期、冻结区间与等待；遗漏需求和实际跳步失效会请求重排。合法的显式等待仍可能导致很差的质量，覆盖审计不把它等同于充分服务。

A 使用共同名义工序模型上的经典构造解与 CP-SAT，支持全局和跨设备族分解；有限候选池、受限深度与限时界均披露。`FEASIBLE_HEURISTIC` 是经典可行构造解，不是 CP 最优解。B 真实生成具体任务和等待，工具不选优、不补排。C 真实选择共享求解器参数、查看候选、明确提交；其作用以实际日志为准。实现存在不等于三个方案已完成全窗口。

原输入和锁定源码已核对。当前可运行场景使用官方包中的周期投料 `order.txt`，而官方 AutoSched options 激活了不同交期的 high_SL 明细文件；历史绑定、CQT、wafer cascading 与上游实现也有已知边界。**不能声称完成官方参考数值复现。** 详见 [校准报告](calibration-20261009.md)与[语义核对](semantics-20261009.md)。

## 证据入口

- [机器可读进度](../../progress/smt_fullfab/STATUS.json)、[追加迭代记录](../../progress/smt_fullfab/iterations.jsonl)、[模型和资源账本](../../progress/smt_fullfab/model_ledger.jsonl)。未知费用保持 `null`。
- [历史复核](historical_review.md)、[A 开发失败与修复](A-development.md)、[开发辨别能力](discrimination-development.md)。短窗口与单场景的差异不外推长期收益。
- [指标定义](metrics.md)、[环境审查](review_environment.md)、[控制器审查](review_controller.md)、[问题规范](SPECIFICATION.md)、[正式协议草案](PROTOCOL_DRAFT.md)。
- 本地原始实验在 `runs/smt_fullfab_development/`、`runs/smt_fullfab_stage2/`；每条保存运行配置、源码、问题、计划、轨迹、失败与成本。大日志不入 Git；[校验清单](../../progress/smt_fullfab/evidence-manifest.json)绑定完整本地文件。

## 开发复核入口与运行隔离

以下是已有开发组件的入口，不是最终研究复现命令，也不能据此认定后来新增的候选测试已经通过。实际性能运行与全部收尾期间，暂停其他测试、回放或全文件校验；运行中只读取轻量元数据，并通过原exec会话核实状态，不能凭文件存在判断进程结束。

在仓库根目录执行，下列检查不新增模型调用：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_smt_fullfab_*.py' -v
.venv/bin/python -m src.smt_fullfab.status --write
.venv/bin/python -m src.smt_fullfab.recovery_check runs/smt_fullfab_development/A_1701_1h_incumbent_v3
```

`status --write` 只更新新命名空间，不覆盖旧状态；它不能替代各条受监管运行的原终末状态读回。`recovery_check` 在临时目录使用该运行冻结源码与锁定输入，真实恢复完整状态并对比哈希，零模型/零求解；它不把旧失败转换为成功。运行路径及恢复命令以 STATUS 和具体 checkpoint 为准。新模型调用沿用已生效的统一研究授权，仍完整追加账本；不能删除旧 reserve 或重置计数。已完成的通道诊断不重新调用。

## 仍需完成

修复后 A/B/C 的全厂 1/8/24 小时执行及成本门槛、同版独立种子辨别实验、预热稳定性、完整共同快照分叉、窗口/频率敏感性、正式指标与矩阵/资源冻结、真实正式对照、独立回放、计划和设备族图表与中文最终报告。官方参考配置无法对齐时需准确保留阻碍。阶段检查通过不替代这些验收要求。
