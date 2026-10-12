# SMT2020 离线指标与动态图

入口：`.venv/bin/python -m src.smt_report --phase development`；正式阶段把 phase 换成冻结阶段名。`--no-plots` 只导出数据。模块不调用模型、求解器或仿真环境，只读取已存结果、原始 trace 和独立回放证据。所有产物放在 `artifacts/<phase>/`，不回写原始运行。

## 认证和统计单位

调用 `src.smt_replay.audit_phase(phase)` 后，只有原始 `status=success`、逐运行 evidence audit 通过、领域事件有效，且正式运行 provenance 完整，才能标记 `certified_success=true`。开发旧记录缺少新元数据可保留审计 warning；报告不伪造字段或重写旧结果。无回放模块时输出 uncertified 诊断，不能把原结果中的 success 当成报告认证。回放审计结果原样保存为 `smt_report_evidence_audit.json`。

`scenario` 是外生仿真种子；`repeat` 是同一 scenario 下的模型/求解器重复。3 个种子各重复 3 次仍是 3 个外生场景、9 个运行，不是 9 个独立工厂场景。每行对应 scenario×arm×repeat。A/B/C 是主比较；F 是单列辅助方案。每个 scenario×arm 和每个 arm 都输出全分母、认证成功数、失败/未认证/缺失数及成功率。冻结矩阵中缺失的结果也进入分母；开发阶段若没有冻结矩阵，分母仅覆盖已发现运行，不能声称完整计划覆盖。

质量均值、中位数、最小/最大值只以认证成功记录为条件，字段附有效 `n`。成本以所有记录为总体，同时输出有观测值的总和及 unknown 数；缺失成本不按零计算，未知账单金额保留 null。该描述性统计不提供独立场景置信区间或统计显著性声明。失败运行 trace 的观测量仅作诊断，不混入成功质量均值。

相对 A 的队列面积百分比和吞吐 lot 差值只配对相同 scenario、相同 repeat，且双方均认证成功；负的队列差值表示队列面积降低。配对缺失时留空，不用其它重复的最佳结果填补。

## 文件

- `smt_results.csv`：逐 scenario×arm×repeat 的认证状态、质量、成本与冻结哈希。
- `smt_summary.json`：每 scenario×arm、每 arm 的分母、条件质量统计、全部运行的已知成本、场景数、覆盖和验收状态。
- `smt_provenance.json`：每次运行完整 `source_sha256`、config/data SHA256、commit、freeze tag/hash 和 legacy warnings；不把当前源文件版本冒充运行时版本。
- `smt_decisions.csv`：决策索引、仿真时刻、是否已提交、模型通道/求解器服务耗时、完整观察到动作耗时（未记录时为空）。
- `smt_machine_observation.csv`、`smt_group_observation.csv`：913 个物理设备及按组等权平均的观测区间比例。Delay_32 的 400 个虚拟资源排除。
- `smt_timeseries_r1.csv`：固定 r1 的逐事件时刻 WIP、累计完成 lot、两受控 family 分别及合计等待 lot 数。
- `<run_id>_smt_dynamics.png`：固定 r1，四幅共享仿真时间轴：WIP、累计吞吐、受控 family 等待队列、明确提交的控制决策/等待区间。
- `<run_id>_smt_decision_service.png`：每次决策模型通道及已归属求解器的墙钟服务耗时。它和仿真时间轴是不同时间概念。

## 质量定义

主目标 `controlled_family_queue_area_lot_seconds` 是整段窗口中两受控 family 的 ready 等待 lot 数的时间积分；包括等待这些 family 其它同资格机台的 lot，不只两台受控设备的候选子集。单位 lot·秒，越低越好。由 ready 加入、任何机台 dispatch 移出独立描述性重算，并和已认证领域审计值交叉核对。时间平均队列 = 面积 / 窗口秒数。

WIP = 已 release 且尚未完成全 route 的 lot 数；初始 WIP 在 t=0 释放。时间平均 WIP 对阶梯状态积分后除以窗口。吞吐计完成全 route 的 lot/wafer；`controlled_completed_operation_lots` 只计受控设备完成的工序 lot，不与整厂吞吐混淆。吞吐率 = 完成 lot / 窗口小时数。给定同一原始输入，初始 WIP + 新 release = 终端 WIP + 完成 lot。

`mean_cycle_seconds_completed` = 本窗口完成 lot 的完成时刻减 release 时刻的均值。初始 WIP 的历史 release 由该源订单 lead time 反推，可能早于 0；因此短窗口周期值包含历史年龄，并只覆盖完成样本，不能称稳态全体周期时间。没有完成样本时均值为空。

延期完成 lot 数和总延期 = 本窗口完成样本的 max(0,完成−due)；终端逾期 WIP 数单独列出，不能把未完成 lot 当零延期。8 小时窗口及零额外 warmup 不构成长期稳态性能证明。

批填充率沿用领域审计：每个受控、实际多 lot 的批 dispatch，其 lot 数 / 对应工序 batch_max。报告均值及已观测批次数（分母），包含窗口末尚未完成的已发起批；`unfinished_controlled_batches` 单列。非批工序不纳入；该数据受控批 min=5/max=6，因而实际多 lot 识别与该受控批模式一致。

## 设备观测比例，不宣称精确生产利用率

不把旧指标 `scheduled_occupation_fraction` 当成准确生产利用率；它只是每次 dispatch 初始计划的占用时长累计，未必覆盖后续事件修订。新表按完整 trace 重建区间，所有区间裁剪到 `[0, observed_seconds]` 后求并集，避免重叠累加。成功运行 observed_seconds 等于窗口；失败的部分 trace 使用已观察结束时刻，不能与完整窗口无条件混合。

- `reserved_observed_fraction`：dispatch 时刻至该 dispatch 声明的 machine_ready 区间并集；若停机发生时最新 reservation 尚未结束，按 downtime 事件修订的 machine_ready 延长。含 setup、load/unload、cadence 和片数 PM 的资源预约时间。
- `calendar_down_observed_fraction`：calendar breakdown/PM 实际序列化区间并集。每事件区间为 `[blocked_until-duration, blocked_until]`；若停机重叠，不把触发时刻至 blocked_until 整段重复计数。片数触发 PM 已包含在 reservation 中，不冒充 calendar downtime。
- `reserved_or_calendar_down_observed_fraction`：上两类区间的并集比例；表示显式 reservation 或 calendar down。它不额外推断两槽 guard、setup/minrun 和资格条件导致的所有不可调度时间。
- `material_present_observed_fraction`：该设备每 job 从 dispatch 到 process_end 的并集，按 affected_jobs 的停机延长更新；排除后续 transport，包含 setup、load/unload 及暂停时间。
- `material_present_excluding_calendar_down_proxy_fraction`：material_present 并集扣除与 calendar_down 的交集。仍包含 setup/load/unload 等，且多 lot/multiple slots 的重叠只按二值材料存在计数；尤其 cascading 只是观测代理，绝不称有效加工率、wafer 槽利用率或通用 AutoSched 精确生产利用率。

组比例为同组物理机台比例的等权平均，分母为机台数×观察秒数。可描述哪个组观测占用较高；这不能单独证明因果瓶颈。原始领域审计指标保持不变。

## 墙钟耗时与成本

`model_channel_seconds` 是每次调用保存的 duration_seconds，含 CLI 通道开销，不等于纯模型推理时间。`solver_seconds` 是求解接口记录的 wall_seconds。每决策两者之和叫 `model_plus_solver_service_seconds`，不含仿真推进、校验或文件 IO，也不能称完整观察到动作延迟。只有运行记录显式保存 `decision_elapsed_seconds` 时才填写后者；禁止从文件 mtime 回填。

旧 A 一次决策恰有一次求解、且次数与已提交动作一一对应时，按保存顺序归属。其它缺少 solver decision 的旧记录，逐决策 solver 归属不完整，合计服务时间为空；run 级 solver 成本仍保留。失败决策已保存的模型调用也列入决策成本。

模型调用数、input/output/cached token、solver 请求预算秒、实际 solver 墙钟秒、全运行 end-to-end 秒分别列出。预算秒不当成实际 CPU；端到端不当成模型推理。未知账单金额不采用模型价格估算。报告运行自身单独记录 `report_process_cpu_seconds`、子进程 CPU、两者合计及 source SHA256，模型/solver 调用始终为 0。
