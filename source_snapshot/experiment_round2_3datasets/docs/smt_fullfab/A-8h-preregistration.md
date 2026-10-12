# A hybrid：8 小时开发门槛的预登记准备

本文件对应 `configs/smt_fullfab/A_hybrid_8h_v2.protocol.json`。状态为 **reviewed_pending_frozen_launch**；本轮只核查保存证据、文件元数据及源码，未运行仿真、构造器、CP 或模型。B 真实运行结束、主流程审查并冻结执行版本之后，才可串行启动唯一一条 `A_1701_8h_hybrid_v2`。这不是正式实验，也不恢复或清零旧失败运行的预算。

## 已完成 1 小时证据

基准目录为 `runs/smt_fullfab_development/A_1701_1h_hybrid_v1/`，原始提交 `f06e3d6a28dd839232b33346336de7fdaac3bdeb`。本次只读核对 `config.json`、`result.json`、`resources.jsonl`、`audit.json`、`checkpoint_resources.json` 和 `provenance.json`；六个文件的 SHA256 已记入新协议。没有重跑审计或覆盖原结果。

| 实测项目 | 保存值 |
|---|---:|
| 完成仿真时间 | 3600 秒 |
| 计划器调用 / 已提交计划 | 47 / 47 |
| 周期优化 / 事件构造 | 2 / 45 |
| CP 累计请求 / 实际 CP | 4 / 3.853602 秒 |
| 周期计划器墙钟 | 20.159154 秒 |
| 事件计划器墙钟 | 57.806454 秒 |
| 事件纯构造（含其 nominal 检查） | 57.504791 秒 |
| 全部经典构造（还含周期优化内的 incumbent） | 59.838295 秒 |
| 全部计划器 / runner 总墙钟 | 77.965608 / 99.991094 秒 |
| 事件计划器墙钟中位 / 最大 | 1.289579 / 1.624576 秒 |
| 周期计划器墙钟最大 | 10.568683 秒 |
| 模型调用 | 0 |

`resources.jsonl` 有 47 条 reserve 和 47 条 finish，计划编号一一对应，47 份候选响应均留存；所有整体结果都是 `FEASIBLE_HEURISTIC`。2 秒周期请求是 CP 预算，不是一次完整规划的墙钟上限，也不能解释为全厂最优。

保存的独立审计 `valid=true`，物理全窗口、派工来源和机会覆盖均通过。声明责任域为全部 913 台生产设备，实际生产派工 1138 次、涉及 833 台；1048 次时钟边界检查未报告隐藏的未覆盖合法需求。冷启动初始 WIP 为 2177 lot，第一小时没有新释放 lot，终态 WIP 为 2176。这一小时的事件与文件增长率不能代表随后七小时。

仅通过文件 `stat` 分类，没有读取全部大候选或扫描生产轨迹：

| 文件类别 | 数量 | 字节 |
|---|---:|---:|
| 完整 problem | 47 | 158,133,125 |
| 完整 solver / constructor 候选 | 47 | 131,782,644 |
| trace | 1 | 17,290,170 |
| checkpoint 与资源继承点 | 2 | 22,107,741 |
| source snapshot | 26 | 430,638 |
| 其他 config、结果、审计等 | 6 | 237,800 |
| 合计 | 129 | **329,982,118** |

最大单份 problem 为 3,372,188 字节；最大单份 solver 为 11,943,028 字节。完整输入与候选占主要体积，8 小时不继续使用原 1 GiB 限额，也不通过省略候选、机器族或审计日志来节省空间。

## 外推仅用于选择资源边界

若把第一小时的事件、时间和文件增长率机械重复八次，会得到 376 次计划（16 周期 + 360 事件）、799.929 秒 runner 墙钟、2,639,856,944 字节目录（约 2.459 GiB）、138,321,360 字节 trace。**这些是预算参照，不是已经测得的 8 小时性能，也不是置信区间或成功保证。**

后续释放、WIP 分布、路由推进、采样返工、故障、设备等待、候选密度和最终 checkpoint 增长均可能非线性变化。一次 cold-start 1 小时样本不足以估计这些变化的上界。

建议新开发边界如下；任一边界先到就停止，不要求同时耗尽其他限额：

| 参数 | 8 小时登记值 | 理由与边界 |
|---|---:|---|
| 累计 CP 请求 | **32 秒** | 绝对时刻 0、1800、…、27000 共 16 次，每次 2 秒；终点 28800 不再规划；事件消耗 0 CP |
| runner 墙钟准入 | **3600 秒** | 约为线性参考的 4.5 倍；覆盖建模、构造、检查、序列化和运行开销 |
| 外部进程硬截止 | **4200 秒** | 给当前不可中断操作及失败证据落盘余量；不是把 runner 验收预算增至 4200 秒 |
| 计划尝试数 | **1200** | 约为线性参考的 3.19 倍；失败尝试也消耗次数 |
| 总目录日志准入 | **8 GiB = 8,589,934,592 字节** | 约为线性参考的 3.25 倍；保留所有输入、候选、轨迹和终态 |
| 独立 trace 阈值 | **256 MiB = 268,435,456 字节** | runner 已有固定阈值，无 CLI 参数；不在本任务修改，约为线性 trace 参考的 1.94 倍 |
| 启动前磁盘可用量 | **至少 24 GiB** | 8 GiB 目录限额加约 16 GiB 本地余量；不购买空间、不删除已有证据 |

只读磁盘查询当时可用约 239,622,066,176 字节（223 GiB），精确时间和数值见协议。其他工作仍可能占用磁盘；这不是空间预留，启动前必须再次查询。

runner 的 wall、总日志和 trace 是 **下一计划前的准入检查**。一次候选生成、环境推进、最后审计和 checkpoint 可以跨过它们；constructor 的 5 秒也是软预算。外部 watchdog 应记录真实启动/结束时间、退出码和完整输出。最终验收同时要求 runner 自记墙钟及完整子进程（含写 result、打印和退出）的实测墙钟不超过 3600 秒，监督外层不超过 4200 秒、最终目录不超过 8 GiB、trace 不超过 256 MiB。超额证据保留，但不能因为 runner 自报 success 就视为过门槛。固定 trace 阈值可能早于 8 GiB 总量触发；届时保留失败，不自动增额或重跑。

## 同一全厂方法与冷启动

固定参数保持为：4 小时预测窗口、2 步 lookahead、绝对 1800 秒完整优化周期、每周期 CP 请求 2 秒、每波 slots=4；事件间共享全厂构造器使用总 slots=8、5 秒软预算、250000 次候选计算上限。周期优化和事件构造均保留跨族前驱、未来任务、批兼容、绑定、设备序列和 nominal 检查，执行器继续只执行显式计划。不会缩成即时评分、缩小设备集合、取消困难任务或添加后台参照策略。

`--seed 1701` 指物理场景种子；runner 固定传给经典计划器的种子是 11，CP 为单 worker。事件构造是确定性 gain-rate 算法，但墙钟截断和 CP 时间预算使不同机器负载下的候选仍可能不同。固定种子不构成跨硬件逐字节重演保证。

本次 `snapshot_path=null`，从原始 WIP 与共同 t=0 释放重新初始化 28800 秒观察窗；不是稳态暖启动。原 3600 秒 checkpoint 不能拿来延长观察窗：runner 会拒绝 snapshot horizon 与请求 seconds 不一致。若本条运行失败，恢复必须使用本条自己的物理 checkpoint 和 `checkpoint_resources.json`，继承累计 CP、构造、时间、日志与次数，不能新建身份规避原消耗；本协议不授权自动恢复。

当前共享 `constructive_tool` 提取晚于原 1 小时运行源码；已有小 fixture 检查原 A event 计划身份与动作等价，但新 8 小时仍须冻结当前完整源码，不能冒称执行的是旧 source snapshot。新协议的 `prepared_source` 只是准备时参考 hash，并非最终冻结。启动前由主流程绑定执行 Git 指针、实际源码 hash、输入数据与 vendor 文件 inventory、requirements/Python/OR-Tools 版本，以及最终协议 hash；冻结后到运行结束不修改这些依赖。

## 唯一监督入口与验收

协议 `run_config` 已通过当前 runner 关键字实参及 CLI 的 AST 核查。直接 runner argv 仅在协议内保存作身份核对；A8 应始终通过以下监督入口，不单独运行 runner。默认命令只冻结准备，`--execute` 才启动唯一子进程：

```bash
.venv/bin/python -m src.smt_fullfab.offline_A_gate

# 仅在主流程审查、冻结且串行队列空闲后执行：
.venv/bin/python -m src.smt_fullfab.offline_A_gate --execute
```

监督证据位于 `runs/smt_fullfab_offline_A_gate/A_1701_8h_hybrid_v2/`，实际 runner 输出仍在 `runs/smt_fullfab_development/A_1701_8h_hybrid_v2/`。`manifest.json` 保存固定配置、原 Git 指针、源/输入/vendor/requirements hash 和 Python 运行时清单；只读 `frozen/` 用于实际子进程。Git 仅作来源指针，不把 dirty source 包装成 clean checkout。复用现有离线监督器的哈希、运行时、互斥锁、活跃 claim 检查和 subprocess watchdog；A 允许已登记 CP，不沿用 reference 的禁 solver 规则。

`attempt.json` 在启动前保存命令、监督 PID 和冻结身份；子进程在加载 runner 前写 `child_started.json` 真实 PID。退出后保存 `process_outcome.json` 的真实 PID、退出码、超时及墙钟，然后进行冻结后检查、逐次资源/候选核对和独立审计证据核对。`verification.json`、最终 `acceptance.json` 与全部目录证据 hash 分开留存。这里检查的物理/来源/机会审计由冻结 runner 内的独立审计器完成，不另外宣称进行了第二次仿真或物理重放。

最终 8 GiB **同时计入 runner 目录、冻结目录及监督输出**，包括 stdout/stderr、审计、快照、清单和 acceptance 本身的精确序列化字节；不只计算 trace。监督计时覆盖执行前核验、子进程、执行后核验及最终证据汇总。冻结准备是独立步骤，其产物体积计入上限。活跃 claim 即使已经写 result，只要进程仍在进行末尾审计，也阻止启动。

状态汇总应对固定已登记 ID `A_1701_8h_hybrid_v2` 强制调用纯只读函数 `src.smt_fullfab.offline_A_gate.read_acceptance(root=项目根目录)`，返回 `{valid, accepted, status, errors, acceptance?, result_sha256?}`。只有 `valid=true` 且 `accepted=true` 才过 A8 门槛；不能等 sidecar 出现才识别监督关系。runner 提前写出 success 而 acceptance 尚未出现，或者任何 hash/退出码/最终资源核对失败，均不得过门。历史读取核验的是冻结自身与原执行证据，不要求将来的 live 监督源码或 Python 环境仍为旧版；新的实际执行仍要求冻结入口与运行时匹配。

完成后重复监督命令只核验原证据并回读，不启动第二次。存在目标目录或 attempt 但缺最终 acceptance 时，明确拒绝自动重启或补做成功认证；保留现场等待人工判断。watchdog 超时不伪造 checkpoint；只有 runner 实际写出的恢复点可以作为后续恢复依据。物理恢复与账本继承仍需另外审查，本监督器不提供清零重跑或猜测式恢复。

运行目录必须是新目录；只启动一条，不与 B/C、参考运行或其他全厂求解并发。禁止模型调用。完整 28800 秒、独立物理/来源/机会审计、nominal 检查、资源配对和最终资源边界全部通过，才记为 A 的 8 小时开发门槛通过。业务指标及所有失败都保留。即使通过，也仅说明该 seed/版本在给定资源内可完整执行，不证明强基线已充分调参、优于 B/C、长期稳态收益或与官方模拟器完全等价。

主流程已完成代码和资源边界审查，并实际运行监督器、状态接入与既有恢复状态三个测试模块，共42项通过（2.094秒）；其中监督器24项使用微型模拟文件链，不创建真实工厂子进程。固定ID的状态验收已接入status.py。源码SHA为`5059038bc0137919ca9864859776d9ec13b18bf8b94a30f03f4b27efefb8a3ff`。尚未进行真实freeze/prepare或8小时执行，协议状态只表示实现审查通过。

2026-10-09 16:13 UTC（北京时间10月10日00:13），主流程实际执行默认prepare并重新核验冻结源/输入/runtime：102文件、1,680,611 bytes，来源Git指针b9c7049，manifest身份`7efcc0032f1bbd556780b430decde94c083b5f7be86ec4cef7f7d67a2aaab881`。原协议保持冻结时字节，不回写历史标志。`attempt.json`及目标实际运行目录均不存在，没有启动模型、求解或仿真。证据为`artifacts/smt_fullfab_recovery/A_8h_frozen_preparation_v2.json`。
