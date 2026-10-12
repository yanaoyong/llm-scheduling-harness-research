# 官方校准、预热与长期规模：下一阶段离线设计

2026-10-09。本次仅阅读已有代码、参考运行结果和 trace，未启动模型、求解器或仿真，未改旧数据或运行时实现。B 恢复方案单列于 `B-recovery-design.md`；root 当前决定 B v2 新冷启动、45k 完整页，delta/retain 留待独立审计后的下一版。本文不改变正在冻结执行的 A/B/C 协议。

## 当前结论与最先需要完成的工作

当前参考策略的 1/8/24 小时运行证明了有限窗口内的执行与部分独立审计能力，尚不能证明稳态或官方数值等价。直接把现 runner 的 horizon 改成一年不可取：日志与内存随完整历史增长，24 小时已产生约 121 MB trace，checkpoint 又完整复制该历史。

建议顺序：**先建立无损分段日志、活动状态快照、独立流式审计的等价性，再做 3/7/14/28 天等逐级参考运行；最后依据多重复诊断决定预热长度。** 官方输入/派工/统计口径对齐应独立成一条校准工作流，不能用预热或调参掩盖尚未一致的语义。

## 已有参考运行的证据与体积

以下读取自 `runs/smt_fullfab_development/ref_*_v1/` 的 result/audit 文件及文件大小。时间为历史 runner wall time，非新执行、纯仿真时间或未来耗时预测。

| 运行 | 完整窗口 | 保存的 audit.valid | 事件数 | trace bytes | checkpoint bytes | 目录文件 bytes 合计 | wall 秒 | 完成 lot | 末 WIP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CR / 1701 / 1h | 是 | true | 7,588 | 5,158,705 | 9,709,280 | 15,287,292 | 3.466 | 1 | 2,176 |
| CR / 1701 / 8h | 是 | true | 50,340 | 38,920,301 | 44,859,292 | 86,478,154 | 51.173 | 10 | 2,177 |
| FIFO / 1701 / 8h | 是 | true | 49,505 | 38,448,841 | 44,382,075 | 85,735,229 | 52.998 | 12 | 2,175 |
| CR / 1701 / 24h | 是 | true | 156,871 | 121,367,316 | 130,657,188 | 258,707,949 | 180.398 | 30 | 2,197 |

这些运行的源版本/审计版本不完全相同：1h 保存的 audit 不含后续加入的 opportunity_audit。不能把其旧 `valid=true` 自动升级成现行全部检查通过。扩大前应对明确冻结版本建立当前等价验证证据；不得改写旧结果以消除版本差异。

24h CR trace 的 SHA-256 为 `e3ca5a0fa15d0b8366446c3b5cd85f3861711a64fc876cc03be48aded5d5b8bb`。本次以逐行读取计数：

| kind | 数量 | bytes |
|---|---:|---:|
| plan_committed | 19,128 | 93,271,905 |
| dispatch | 21,180 | 11,463,345 |
| coverage_gap | 19,127 | 5,101,716 |
| time_advance | 48,773 | 4,125,246 |
| initial | 1 | 2,734,043 |
| operation_complete | 20,755 | 2,141,883 |

plan_committed 占约 76.8% 字节；全厂 scope、参考策略说明等重复信息适合字典引用，不能直接删掉计划或 coverage_gap 事件。coverage_gap 数量本身也不等于漏派违规数：本参考 runner 会把需要新显式计划的合法需求作为停止/再决策事件，必须结合独立 opportunity replay 判断。

仅将一天密度作算术乘法，7d trace 为 849,571,212 bytes，28d 为 3,398,284,848 bytes，365d 为 44,299,070,340 bytes / 57,257,915 事件。这是规模警示，不是实测容量或运行时间预测；长期队列、计划数与故障状态会改变事件密度。目前 256 MiB trace cap、全目录 cap、max_plans 与 wall cap 也会先阻止长运行，不能静默放宽。

## 现有增长点：只换成文件迭代器不够

- `src/smt/environment.py::_emit` 同时追加 `self.trace` 和 JSONL，事件序号还来自 `len(self.trace)`。
- `src/smt_fullfab/environment.py::snapshot` 深拷贝整个 trace；恢复后把前缀再写入新 trace。反复分段若仍复制前缀，会重复存储和审计全部历史。
- `metrics.read_events()` 用 `read_text().splitlines()`，再产生所有 event 对象；`audit_trace()` 还深拷贝为物理投影，并调用多个再次保留列表/历史字典的检查器。
- metrics 为 queue、reservation、calendar、material 保存全部区间，为 family 汇总反复过滤全部 dispatch。仅把输入改成 generator 不会消除这些增长。
- 环境保留所有旧 jobs/lots/completed、plan_versions、executed_tasks；`_calendar` 每次扫描全部历史 jobs。此处有长期复杂度风险，不能按一天耗时线性推算一年。
- 初始构造提前建立整个 horizon 的释放 lots 和 release 事件，manifest 也包含这些条目。未来可改为有哈希的外生投料目录与确定性 cursor，但属于单独语义/恢复接口变更。
- 当前 observation 的可观察历史缓存依赖 trace 中已发生的 dispatch/downtime。改成短 ring buffer 或丢历史后，必须同步保存必要的已发生状态，不能误用私有未来实际结束时间来补洞。

新实现应进入新命名空间/显式新版本，不修改已冻结的旧物理文件。完成事件等价测试前，不能宣称这是“仅性能优化、行为必然不变”。

## 可恢复的分段存储协议

建议新 long-run manifest 固定场景、主 horizon、输入文件哈希、source/策略/指标/审计版本、初始化语义与资源上限。一次预先声明主 horizon，例如一组计划中的最终预热＋评估长度；中间暂停由独立 `stop_at` 控制。保持绝对仿真时间，不把暂停当 terminal，不在续作时改 horizon 重新生成外生释放。现 runner 明确拒绝 snapshot horizon 不一致，已有 24h terminal checkpoint 不能直接改成 7d/365d。

日志采用追加分块，例如按 32–64 MiB 未压缩内容或一天以内的先到条件关闭 chunk。块头/索引记录：

```text
run_identity, scenario, source_hashes, input_hashes,
first_global_seq, last_global_seq, start_time, end_time,
previous_chunk_sha256, logical_event_stream_sha256, stored_file_sha256,
checkpoint_before_sha256, checkpoint_after_sha256,
independent_auditor_before_sha256, independent_auditor_after_sha256
```

使用独立的单调 event_seq，不再取内存列表长度。物理事件、控制器来源、计划、漏派检查事实均保留，分块不改变事件顺序。压缩可使用独立 gzip/zstd 文件；同时保存逻辑事件的哈希，压缩格式/时间戳不能成为语义等价判断。

将全厂 scope、静态策略 provenance、route/机器目录等按内容哈希存一次。事件使用 `scope_ref`、`provenance_ref`，解码后须逐字段恢复原逻辑事件。变量候选计数、明确 task、时间、hold、失效原因不可被公共字典替换或概括。字典也需无来源内容/未引用项检查，不能藏入额外调度建议。

活动快照只持有恢复必需状态：当前 lots/访问次数/dedications、队列、未完成 job、机器 setup/minrun/PM/cascading、待处理事件和 token、外生释放/calendar cursor、当前计划及冻结部分、累计资源计数、观察历史充分状态、最后 event/chunk hash。历史已完成 lot/job 的只读证据在日志或磁盘索引中，不再次嵌入 snapshot。

清理 job 必须处理仍在队列中的旧 token 事件：不能看到 `done=true` 就删除，随后旧 `lot_done/process_free` 查表会失败或改变状态。需要明确的过期事件规则/索引，并通过故障延期、跨块运输、重工、PM、cascading 场景验证；没有证明前不清理。唯一 task/plan 标识校验可用单调版本＋持久索引，不能因丢历史允许重复执行。

原子暂停边界为：完成当前事件及其派生写入 → 刷新/关闭日志块 → 持久化环境活动快照及独立审计状态 → 原子发布分段完成 manifest。崩溃后只读取已发布边界；未完成尾块保留为诊断，不能猜测其提交状态。磁盘上每个 checkpoint 只引用已验证日志前缀，不复制前缀。

## 独立流式审计与在线指标

流式审计需要自己的状态机，不能直接拿环境快照当“已经通过审计”的事实。输入是固定 manifest、按 seq 连续的块及其哈希；逐项检验源数据、随机事件重放、资格/批次/换型/minrun、precedence、cascading、虚拟等待、计划来源、冻结/已执行状态和机会覆盖。块边界保存**独立推导的**活动状态和计数，再与环境可验证字段对照。

可把现三个审计阶段拆成独立消费者：`PlanSourceAccumulator`、`PhysicalReplayAccumulator`、`OpportunityAccumulator`，另有 `MetricAccumulator`。每个事件顺序 fan-out，不需要把整份 trace 或 physical projection 放内存。物理适配投影可以逐事件产生；来源审计必须仍保留“这是投影，不是模型新动作”的区分。必要的全局唯一性与历史追溯存 SQLite/有序索引，运行内存主要随活动 WIP、活动 job、机器数和最近段变化，而非总事件数增长。

指标在线维护建议：

- WIP 与排队面积：按事件间隔累计 `count × dt`，分别保留全厂、产品、生产族计数。得到 time-average WIP，不能只报告末 WIP。
- 未完成逾期积分：维护活跃已释放 lot、due 边界小根堆和已逾期权重和。处理到期、release、completion 时更新积分，精确裁剪 warmup/评估边界。保持当前 completed/unfinished 两部分与权重/人口定义，不把旧逾期时间重复加到新窗口。
- 完成周期/准时率：保存分产品/priority 的数量、总和和必要的磁盘逐lot记录，明确计入完成窗口的 lot cohort；initial 推断 release 的 lot 单独标记。分位数若用近似 sketch 必须标记误差；官方均值对齐无需替换成近似。
- 机器负荷：维护活动占用/材料/停机区间的并集和延迟关闭事件，支持 downtime 延长与 stale token。沿用现 `reserved`、`material_present`、`calendar_down` 的不同定义，不能相加当一个使用率。
- 守恒：每段和任意评估窗口均校验初始WIP＋释放＝完成＋末WIP，保存 skipped/reworked/virtual 等事实计数及非法/漏派计数。

不能仅审计抽样片段，然后把整个长窗口标 valid。抽样只可用于开发性能 profile；完整审计必须覆盖所有块。已认证前缀可通过审计版本与状态 hash 增量复用；版本变了则流式重新扫描，仍无需全量入内存。

## 扩大运行前的工程验收门

先用现存 trace 验证新解码器/流式审计：逻辑事件逐项相等、整数计数完全一致、累加指标用预先声明的浮点容差、错误注入仍能发现漏块/重复 seq/改批/非法冻结/缺失终态。原始旧文件只读，结果写新证据目录。1h 历史审计较早，须记录哪些新增检查是本次才执行。

然后在新冻结实现上进行短场景/同输入配对验证：连续运行与任意非 terminal 分段恢复应产生相同后缀物理事件和明确参考动作；跨边界包括正在加工/运输/停机、piece PM、重工、初始化绑定不确定性和两段 cascading。chunk 大小或压缩格式不能改变结果。此处只是待实施测试要求，本次未运行。

正式扩展前记录每段墙钟、RSS峰值、trace原始/压缩字节、snapshot字节、活动/历史job数、事件处理与审计吞吐、各阶段耗时。判定内存是否随总事件数增长；不能只看最后一次 RSS。资源上限需在实际机器 profile 后冻结，包含累计磁盘/墙钟/计划/审计负担，续作不清零。

参考策略性能优化也须无决策变化：route 的期望 suffix 可按静态 route hash 预计算；机器事件可扫描 active jobs 索引；候选应仍覆盖全部合法 waiting lot/机器。不得限制每族候选或为了快而改变 HP→setup→CR、Demand batch、平局规则。以明确动作序列等价测试支持这些改动。

## 预热的可行阶梯与判断方法

工程门通过后，使用开发 seed 串行参考运行，先 3d、7d，观察资源密度与恢复；再 14d、28d。这不是预先宣称 28d 已稳态。现 24h 完成周期均值约 38.1 天且多为初始化 WIP，单日 throughput 和平均 cycle 很容易受初始状态影响，不能把 24h 指标视为长期基线。

建议固定日汇总与周汇总，记录全厂/产品/priority WIP、最老等待、初始 cohort 剩余数、具有未知历史绑定的剩余数、throughput、cycle 完成队列样本量、准时率、逾期未完成积分、105 族负荷/排队。既要看聚合，也要检查少数产品/设备族持续积压；平均 WIP 平坦不能排除局部漂移或少数 lot 永远不完成。

在扩展前预登记候选截断点，例如 7/14/28/56/84/168/365d，和业务可接受漂移/差异标准。用多个开发随机重复的块均值、趋势与截断敏感性检查；连续相邻天不是独立样本，不以“一条曲线看起来平”代替不确定性分析。若只有一个 seed，应输出探索性稳定性诊断而非稳态置信结论。held-out seeds 不用于挑选截止点或调规则。

官方一年 warmup 仅是**复现既有报告的候选口径**，不是当前适配器一年后必然稳态的保证。初始绑定/CQT历史缺失可能随初始化 lot 离场减少，但当前 CQT未执行、wafer cascading近似、故障/PM语义差异不会因 warmup 自动消失。持续不完成的初始化 cohort 也是需要报告的阻碍。

在选择预热点后，保存一份同源、审计通过的 warmed state，明确其参考策略和进入状态的路径。A/B/C 可从同一物理状态与外生随机场复制，保留全部在制、setup/minrun、dedication、维修/PM进度与活跃job；重置的是统计窗口与控制器会话，不能重置物理系统。过去参考策略的未启动计划应在预先定义的所有臂共同交接规则下处理，不能让参考规则在 A/B/C 后台继续补排。

## 官方数值校准的独立条件

已核实的官方报告、输入身份及策略差异见 `calibration-20261009.md`。其中 Period_1 的 20,716 完成 lot、897:25:17 周期均值、90.66% 准时率、2139.70 平均 WIP，仅是待对齐参考；Period_2/3 是 warmup 后累计值，不能视为独立年度样本。

至少需要分别锁定：

1. `periodic-21-stream` 研究输入与 `explicit-high-SL-92` 对齐输入；官方 options/log旧名与实际报告投料文件的逐lot身份仍需证据。不能静默替换当前研究订单。
2. 释放和交期的时间单位、区间端点、初始 WIP release 推断方式；官方报告窗口、WarmUp RESET、累计周期/准时率/WIP的分母。
3. HP/RSETUP/CR 顺序、Demand batch、LSSU、wake、HotLot行为和平局；当前开发 reference 的名字不等于 AutoSched相同实现。
4. 维护/故障、setup、lot与wafer cascading、CQT和历史dedication的边界；建立微场景与显式差异表，不能为贴近单个官方值反向隐藏语义修改。
5. 可重新运行的官方/上游版本入口、输入/seed/参数hash和多个重复。锁定 Python 上游入口覆盖CLI参数的问题需新适配层处理，冻结vendor不改。不能取得官方软件时，只能报告透明的近似/版本间对照。

新的在线报告须增加可与官方对齐的 time-average WIP、非加权完成准时率、完成 cohort cycle、lot starts/completions，以及明确 warmup 后累计量。当前优先级加权逾期积分是 A/B/C 的独立评价目标，不能与官方 ONTIME% 或周期均值相互替代。

验收应分开给出：物理/来源审计通过、完整范围与资源可恢复、预热诊断证据、与官方输入/策略口径的匹配程度、数值差异和不确定性。若只能完成前几项，校准状态仍是 `official_calibrated=false`；不设任意百分比容差将单条报告“拟合通过”。

## 已落实的最小模块：两遍 JSONL 指标重建

2026-10-09 新增 `src/smt_fullfab/stream_metrics.py` 与 `tests/test_smt_fullfab_stream_metrics.py`。API 为 `stream_metrics.compute_metrics(path, window_start=0, window_end=None, priority_weights=None, include_lot_details=False)`；只接受 JSONL 文件路径，返回与旧 `metrics.compute_metrics` 相同的指标 schema。旧 metrics/env/audit 与运行入口均未修改，当前冻结 B 不接入此模块。

第一遍逐行验证 JSON、完整文件时间范围与 snapshot prefix，保留 initial manifest 和末事件类型；第二遍逐行按窗口重建 lot/job/机器指标。两遍均 hash 原文件全部字节（包括空行），不因子窗口而跳过文件尾 JSON 校验，文件中途变化会拒绝。没有 `read_text()`、全 events 列表、plan_committed 历史列表或完整 dispatch 对象列表；每次仅解析一条 JSONL 记录。初始 manifest 或单个巨型事件的内存仍不可忽略。

`python -m unittest tests.test_smt_fullfab_metrics tests.test_smt_fullfab_stream_metrics -v`：20 个测试通过，1.138 s。新 11 项涵盖全 lot/WIP 指标、窗口边界、batch/虚拟机/闲置族、队列与多次停机延期、prefix 位于窗口外的验证、末 terminal/部分轨迹、无效权重/事件/引用/JSON、文件跨遍变化、恰好两遍且禁止旧全读入口、无文件修改，以及合成 plan 历史从 32 条增到 2048 条时内存峰值不随历史线性增长。

数值协议预先明确：整数、布尔、null、身份/列表、分类以及除族排队时间以外的字段完全一致；`production_family_statistics.*.queue_wait_lot_seconds` 使用 `rel_tol=1e-12`、`abs_tol=1e-7` 秒。原因是旧 Python 3.12 `sum(generator)` 使用改进浮点求和，新模块逐项累计以免保存全部队列区间。该容差只用于这个浮点字段，不放宽事件计数或守恒。模块常量记录容差。

只读既有四份 reference trace，在**独立子进程**分别运行旧/新函数；每个子进程顺序计算全窗和 `[horizon/4, 3*horizon/4]`，都开启 lot details，然后递归比较所有字段、类型和列表顺序。RSS 来自 macOS `resource.getrusage(RUSAGE_SELF).ru_maxrss`，包含解释器/库和两次计算的进程峰值；wall 是两次计算合计，非仿真耗时。所有比较通过，仅出现上述排队浮点舍入差。

| trace | 旧峰值 RSS bytes | 新峰值 RSS bytes | 旧 wall 秒 | 新 wall 秒 | 两窗口最大排队绝对差（秒） |
|---|---:|---:|---:|---:|---:|
| CR 1h | 82,575,360 | 70,189,056 | 0.125 | 0.197 | 1.1642e-10 |
| CR 8h | 416,890,880 | 71,270,400 | 0.968 | 1.413 | 9.3133e-10 |
| FIFO 8h | 407,371,776 | 64,897,024 | 0.960 | 1.388 | 2.7940e-9 |
| CR 24h | 1,242,415,104 | 73,711,616 | 3.654 | 4.440 | 9.3133e-9 |

所有字段比较中最大相对差为 1.6174e-15。RSS 是本次独立进程测量，不保证跨机器/重复运行单调或相同；新方法双读且 hash，测得时间略长，不能描述为提速。

以上表格采用已保存的最终复核轮次，结构化原始证据为 `artifacts/smt_fullfab_semantics/stream_metrics_comparison.json`（4,054,020 bytes）。它包含四份原始 trace SHA-256、输入字节数、旧/新指标实现和比较脚本 SHA-256、Python/平台、八个不同子进程 PID/RSS原值/单位/精确wall、每窗的完整旧/新结果、规范结果hash、全部标量字段比较数，以及每个非完全相等字段的路径/两值/绝对与相对差。24h 全窗比较 12,201 个标量，中间半窗比较 11,998 个；只有排队累计字段分别 58/46 个有容差内舍入差。

冻结量测实现 hash：旧 `metrics.py` 为 `c954c83a51d3ebff7614b469086c916357ef7424d8f92bae25c9c0e533a962cc`；新 `stream_metrics.py` 为 `109919622c5b1e10b56f0340174cbb3a837da8488fd83e5ae2a9b303f63328f4`。脚本 `artifacts/smt_fullfab_semantics/compare_stream_metrics.py` 只读被测 trace，每个模式启动独立 Python 子进程，运行前后验证输入和源码未变化；仅向明确指定的新报告路径写入，不覆盖既有证据。仅重做 24h 核查可执行：

```sh
.venv/bin/python artifacts/smt_fullfab_semantics/compare_stream_metrics.py \
  --run ref_cr_1701_24h_v1 --output /tmp/stream-metrics-review.json
```

去掉 `--run` 可复核四份输入；若输出已存在须选新路径。该脚本不导入环境、控制器、优化器，也不启动任何仿真或模型。

剩余限制：仍保留 lot 元数据/释放/完成、job material 区间、每机 reservation/calendar/job索引、batch_fill_ratios 输出及可选 lot 明细；它不是常数内存，也没有活动快照、日志分块、物理随机重放、来源或漏派完整审计。继承旧指标窗口和拒绝规则不等于独立物理正确性认证。此模块只能作为长期基础的一步，不能据此直接批准一年仿真、宣称完整流式独立审计或官方校准通过。本次验证没有启动新仿真、模型或优化求解。
