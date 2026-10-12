# 7/14/28 天运行前的无损存储与独立审计审查

2026-10-10 北京时间补充：组合流式审计草案现已接通来源、机会、完整物理投影消费及指标，并通过独立小样本审查。root以预登记的只读、串行独立进程对保存的 A hybrid / C constructive 两条 1 小时轨迹比较新旧完整入口，四个组件的字段、类型和顺序一致；仅 queue 累加存在最大约5.83e-11秒的浮点差异，落在先前声明的1e-12相对/1e-7绝对容差内。A进程峰值RSS163.81→93.41MB，审计与写报告耗时3.03→23.77秒；C为163.07→103.66MB、3.14→23.60秒。这是每模式一次的保存样本量测，不能外推长期性能。原始轨迹、验收及旧报告没有改变。详见 `artifacts/smt_fullfab_diagnostics/stream_audit_existing_1h_v1/`。

另外用预登记单次600秒上限读取失败A8的269,165,632字节轨迹，组合诊断在100.70秒完成，峰值RSS134.33MB，新输出约5.47MB。来源与机会检查通过；原完整horizon物理合同仍拒绝这个非terminal前缀，保留200条封顶错误（缺terminal、尚未走完声明8小时内的日历/加工义务）。所以组合`valid=false`，没有取得完整物理前缀或八小时验收，原A8失败保持。诊断代码没有裁剪manifest horizon、伪造terminal或补执行事件。明细见 `artifacts/smt_fullfab_diagnostics/A_8h_failed_prefix_audit_v1/`。

目前已把审查通过的物理核心、绑定和组合入口安装为独立生产模块，87项组合回归通过；隔离冻结副本路径核对也通过，但尚未接入runner。新外存trace原型也尚无环境快照恢复；root独立发现append期间替换SQLite索引后旧连接可能封存错误路径，已保留原反例并交修。实际长窗口仍须完成源冻结、生产接线、恢复和容量验收。

审查日期：2026-10-09。本文记录当前代码的具体历史保留点和待实施方案，不是长窗口容量验收或官方校准结论。本次没有运行真实仿真、模型、求解，也没有重跑已有 stream metrics 基准。父任务正在串行运行的 reference pilot 使用冻结副本，不受工作区修订影响。

最小结论：只把 `audit.py` 的指标函数换成 `stream_metrics`，不能解除长窗口限制。环境 trace、快照及其哈希计算、来源/机会/物理审计、历史 job 索引和返回结果数组，都各自保留历史。应先建立可重复读取的完整事件源，再逐个替换审计消费者及快照历史依赖；原始计划事件必须完整保留。

## 1. 证据边界与源码版本

下表为此次只读代码审查时计算的 SHA-256；行号以这些版本为准。路径均相对项目根目录。工作区允许其他 agent 修改，不把 Git HEAD 当作实际运行源哈希。

| 文件 | SHA-256 |
| --- | --- |
| `src/smt_fullfab/audit.py`，修复前 | `901531e6d2722f56e7de1d25db227e8a312f1f3a85c5142633ca3247a74bf5c3` |
| `src/smt/audit.py` | `a0b96922c76950f323a5c60bf34051419fc3955bfe982973c77bf7da9aa50cf1` |
| `src/smt_fullfab/metrics.py` | `c954c83a51d3ebff7614b469086c916357ef7424d8f92bae25c9c0e533a962cc` |
| `src/smt_fullfab/stream_metrics.py` | `109919622c5b1e10b56f0340174cbb3a837da8488fd83e5ae2a9b303f63328f4` |
| `src/smt_fullfab/environment.py` | `6d6b6b235ec38c5b26a279c2df574a43d88cdf5baa1096da0dc9bcc630ba122c` |
| `src/smt/environment.py` | `04598803fd84239ec1de464505f5450e9a82dbb6ea0b73d13227a1ab55b8c5c6` |
| `src/smt_fullfab/observation.py` | `007b96fa87aca72752b2765bcfefb28e8ef9b705a24bdd5bd6579ae5c72a1512` |
| `src/smt_fullfab/runner.py` | `8ccaa458da029fcdcc0aac0a58bbc5578b34ea3f794ef26cc95382d2f6221158` |

已有四份 trace 的指标等价性、输入哈希、独立进程 RSS 原值及复现脚本见 [offline-design-next.md](offline-design-next.md) 的“最小双遍流式指标”部分与 `artifacts/smt_fullfab_semantics/stream_metrics_comparison.json`。本次仅核对该已存证文件身份，SHA-256 为 `9c14d693ded645d7f1d9b6096c49b99da50b2c7a20b78213739d7c7a4213da42`，不重复其量测，不外推已实现的整体内存上限。

## 2. 仍整段读入、复制或随历史增长的位置

记 N 为事件数、P 为累计计划数、J 为历史 job 数、L 为声明的 lot 数。以下是代码结构分析，不是本轮 RSS 测量。

| 层 | 精确位置和行为 | 仍需解决的问题 |
| --- | --- | --- |
| 事件读取 | `metrics.py:17–20` 对路径 `read_text().splitlines()` 后解析成 events；列表输入使用 `list(source)` | 文件文本、分行对象、解析对象及全列表峰值；列表输入只是浅复制引用，不能夸大为重复全部 JSON 对象 |
| 全厂审计总入口 | `audit.py:444–450` 整段读取，然后分别调用来源和机会审计；两者再次 `read_events` | 原 events 始终存活；各消费者的浅列表复制是额外 O(N) 引用空间，通常依次发生，不应把所有峰值简单相加 |
| 来源审计 | `audit.py:36–38,138,145–147,174–176` 保留所有 plans、task maps、done、dispatches、virtual、gaps、opportunity_records | plans 引用原事件并另建任务索引，O(P+全部任务)；dispatch/virtual 列表并非新深复制，但仍增长。很多数组只为计数，gaps 则还直接出现在报告中 |
| 物理投影 | `audit.py:461–477` 对全部选中物理事件逐项 `deepcopy`，插入合成 action 后形成 projected 列表 | 与原 events 并存的第二套物理事件；合成 action 只是审计适配，不能成为模型动作证据 |
| 旧独立物理审计 | `src/smt/audit.py:20,28,47,90,95,117–131` 路径输入全读；当前调用收到 projected 列表。全 jobs、machine_jobs、dispatch_list、actions、completed 持续增长；结束时按机器/组再过滤和遍历 | 只改总入口为 iterator 不够：它使用索引、`len(events)`、末事件、多次回看、历史 job 遍历；须真正改为独立状态重建器 |
| 机会审计 | `audit.py:206,216–224,348,372,422–440` 全读 events；jobs 不回收，ever_ready/planned 操作身份全集、executed_tasks、completed_lots、reported_gaps 随历史增长 | `machine_jobs` 过滤已释放槽不等于删除 jobs 字典；历史全集去重和 never-in-any-plan 差集需精确磁盘索引或等价外排，不能采样 |
| 旧指标 | `metrics.py:63,84–86` events、队列区间、预留/材料/停机区间、全 dispatch/job 索引 | 区间末端仍可能被 downtime 延长；不能见到 dispatch 就结算最终占用 |
| 新双遍指标 | `stream_metrics.py:26–35,75–78,108–127,133–170` 已逐行双读，无 events/plans 数组；仍保存全部 material/job、每机 reservation/calendar、batch fill 与 lot 集合；`details` 即使未请求输出也先建立 | 不是常数内存。单条 JSON 仍完整解析；initial manifest、最大计划记录、最终 `_union_seconds` 排序的临时列表也需纳入峰值 |
| 环境写入 | `src/smt/environment.py:40,99–102` 同时保留 `self.trace` 和追加 JSONL；event seq 取 `len(trace)` | 直接删前缀会破坏全局序号和观察层索引；应分离全局事件计数与持久事件写入 |
| 环境状态 | `src/smt/environment.py:43–44,71–77,148,161,171` 所有 lot 及整个 horizon 释放队列预生成；jobs 永不删除；停机扫描历史 jobs | 已结束 job 仍可能被过期队列 token 引用，当前代码先查 job 再判断 token；不能仅按 `done` 删除。终端 `metrics():289–293` 也依赖全 jobs |
| 观察历史 | `observation.py:27–44,57–77` weak-key 缓存仍保存 trace 引用、全部 dispatch 摘要和全部停机事件；增量读取使用 trace 切片 | trace 替换或截断会重建/丢失观测前史；必须给当前/最近机器 job、运输中的 lot 与修复预测保存充分的已观测历史，不能改用私有未来实际完成时间 |
| 快照复制与哈希 | `smt_fullfab/environment.py:279–296` 深拷贝 fields/q/完整 trace；`digest():23–26` 又 JSON 序列化→解析规范化→排序序列化→encode 后求 hash | 不只是 checkpoint 文件重复历史；哈希阶段还会生成完整 JSON 文本、规范化对象和编码字节。即使 `json.dump` 分块写文件，也不能消除这些峰值 |
| 快照恢复 | `environment.py:301,309,328–332` 整个 checkpoint `read_text/json.loads`；先初始化新环境，再载入 state；完整前缀重写入新 trace | 多次恢复重复存储和审计前缀。现 prefix count 检查不能被简化为“只信 checkpoint state hash” |
| 运行结束与资源门 | `runner.py:148–152,215–238` plan 边界检查 wall/计划数/trace 256 MiB/目录量；仿真完成后全审计，然后快照；solvers 保存每次完整响应 | wall 和日志门不是整个完成阶段硬上界；单次操作、审计、checkpoint 可以追加内存/时间/字节。A 的 solver 响应与 problem 文件也不能被无声删除 |

单个步骤流式化不能使现有 `audit_trace()->完整dict` 成为常数内存 API。`coverage_gap_details`、`reported_coverage_gaps_rechecked`、`batch_fill_ratios`、物理审计 batch 列表、可选 lot 明细本来就是随历史增长的输出。要保留同字段同顺序，应流式生成完整报告文件，另返回小的 summary/路径/哈希；若继续要求一次返回旧完整 Python dict，就必须承认最后仍会物化这些数组。

## 3. 必须保留的状态与可退出内存的证据

| 组件 | RAM 中保留的活动状态 | 可外存但不可删除的历史 |
| --- | --- | --- |
| 事件源 | 当前记录、读写计数、当前块摘要、最大记录所需内存 | 每个原始字节、全局事件顺序、全部 plan/hold/coverage/物理事件、原始 source/输入快照 |
| 来源重建 | 当前 plan/task map、按机 pending、当前冻结任务、条件 hold 所需执行状态、计数及已派发机器集合 | 全版本唯一性、已执行 `(version,task)` 身份、被替代计划、错误/明细事件索引。旧计划可按 offset 读取，不能替换成工具重新选出的计划 |
| 物理重建 | 每个活动 lot 的 route/visit/dedication/rework/ready；机器 setup/minrun/槽位/PM；未完成 job/transport；calendar cursor、必要累加器 | 释放/完成/job 身份去重，已关闭 lot/job 数据和报告数组。保持原输入绑定、事件键随机数及 affected_jobs 的派发顺序；不能因改用无序集合改变重放结果 |
| 机会重建 | 当前 waiting/ready、精确合法批候选、pending/holds、机器/活动槽状态、unplanned_since | ever_ready/planned 身份、历史完成和执行身份、gap 明细。使用精确 SQLite/有序外排索引，不用 Bloom filter 或抽样代替审计 |
| 指标 | 选定窗口边界、活动 ready、可被停机延长的 job/预留区间、每机可关闭的并集段和累加器 | 任意后选子窗口需要的 lot release/completion/interval 原事实，batch fill 顺序、lot 明细；写磁盘索引或重新扫描原始流，不只留全窗汇总 |
| 可恢复环境 | 时间/绝对 horizon/所有稳定 ID 计数、事件堆与 token、active jobs/lots、设备/PM/日历、当前计划/冻结、观察充分状态、资源账本位置 | 全部 trace 前缀和结束对象可只由日志/索引引用；独立审计不得信任此环境快照作为物理正确性证明 |

最小实施不必马上把未来所有 lot 改为惰性生成。L 与历史事件 N 是不同规模项；先保留已声明 manifest/未来 release 队列可减少语义风险。若资源量测表明 L 成为瓶颈，再独立版本化 release cursor，证明顺序、ID、horizon 边界及随机事件键完全一致。不能借“分段”在每天重新冷启动、重置 dedication/PM/seed 或重新生成订单。

## 4. 最小改造顺序

### A. 可重复读取的完整事件源，先不改物理执行

设计 `EventSource` 工厂：每次调用产生独立的新 iterator，输入可以是旧 JSONL 或冻结的 chunk manifest。统一校验 logical seq、initial、时间与末 terminal；子窗口也验证完整前后缀。分阶段顺序多遍读取最容易与旧代码对照；暂不要求同时 fan-out 四个复杂消费者。多次 I/O 可以接受，不可偷偷退回 list(iterator)。

块采用已有设计建议的 32–64 MiB 原始字节目标，但必须在完整事件行后切分。最大单行可以超过目标，不能截断计划数组。对每块记录 seq/time 首末、记录数、原始字节数/哈希、实际存储字节数/哈希、前块摘要；冻结索引再逐块读。gzip/zstd 必须可独立解压，所有原字节连结后的哈希与原流一致。保留 initial、terminal、完整 plan_committed 和全部 control 事件；不删 plan，不只存 dispatch，不把 explicit hold 折叠成静默等待。

第一版无需自创计划字典编码：压缩原始 JSONL 已能无损保留重复字段。若后来采用内容寻址的 plan/problem blob 去重，必须另有明确编码 schema、缺失/null/类型/顺序 roundtrip，保留所有引用及源 blob，任何不可解析引用即失败。不能把差量存储误作允许工具补齐或重排计划。

### B. 独立审计先消除 events/projected/plans 全历史

新增流式审计入口，不覆盖旧实现及已存报告。来源、机会和物理消费者分别从同一冻结 EventSource 重建，互相只合并结论，不把一个消费者的“valid”当另一个的输入事实。物理投影逐条生成并维护自己的 projected seq/decision 计数；继续明确它是兼容审计适配而非模型动作。物理核验保持独立的采样、源文件语义校验和状态更新，不调用环境 step/校验函数。

分离必须在线的 active 状态与精确历史索引。用 SQLite 等磁盘容器时固定主键的 JSON 类型、插入序号与读取顺序；例如版本整数 `1` 与字符串 `"1"` 不能合并。原错误上限 200 及原报告数组顺序需明确保留，不以改存储为由额外截短。当前计划置换只能在冻结继承检查完成后退休旧内存对象。

JSON 报告以临时文件流式写数组，关闭并校验后发布；另建一个小索引描述结果路径、哈希、计数、valid 及版本。完整解码后的字段值与旧报告相同；只是返回 API 需要新版本，不能伪称旧 Python dict 内存已被解决。对无效数据，必须仍输出失败原因及输入身份，不因 stream 尾部缺失而返回部分 success。

### C. 处理指标与物理历史 job 的剩余增长

先接入已对照的新双遍指标，随后单独消除其 `materials/reservations/calendar/jobs_by_machine/fills/details` 的全量 RAM 依赖。按开始时序处理不等于区间已最终确定：只有 job 不再受未来停机延期、其区间与后续段不会改变已累加并集时，才可关闭内存记录；其身份仍留精确磁盘索引以拒绝重复/失效引用。需要窗口外前史才能确定窗口内 WIP、排队、迟交和跨边界占用，不从 window_start 冷重建。

物理审计的 job 退休条件与环境 GC 条件分别证明，不能共用环境自称的 `done`。仍需检测缺失的应到完成事件、重复 completion、未满足 rework/采样、错误停机 affected_jobs 和任何终端守恒差异。多槽 cascading、机器可接新任务但旧 lot 仍在运输的状态都不能提前丢弃。

### D. 最后改环境 writer、活动快照与观察历史

用独立 `event_seq` 和持久 writer 替代 `len(env.trace)`；观察充分状态在事件写入处增量维护，当前完整 observation 的每一字段应与旧 trace 缓存方法逐字段对照。保留已发生的停机时间、当前修复开始/分布、活动 job 的可观测 dispatch 信息；不能为了回收 history 引入尚未发生的处理/运输/PM 真实值。

快照仅引用关闭且校验过的事件前缀（chunk 链、最后 seq、原流 hash），保存恢复必需状态和源/输入/资源身份。从 initial 到前缀仍可独立重放。可以另存独立审计的累加器快照以加快复核，但必须绑定同一 prefix 和审计源版本，并抽定边界与从 initial 完整流式重放比对；环境 checkpoint 的 hash 不能替代审计重放。

环境 job GC 先处理 stale token：当前 `_events_to` 对过期队列项先索引 jobs，贸然删除会报错。可维护未消费队列引用计数或显式退休索引，证明所有有效/过期队列项语义一致后回收；不能把 KeyError 静默忽略当正确恢复。终端 legacy metrics、observation latest job 和执行任务去重也先改为等价累加器/外存。

写入提交顺序为：完成一个合法暂停边界的派生事件 → flush/关闭事件块 → 原子保存活动环境状态与资源计数 → 独立审计状态或待审计标记 → 原子发布 resume manifest。写失败或 kill 时保留未提交尾部供诊断，但只能从最后已验证前缀恢复，不能猜测计划已执行。区分“暂停”与主 horizon 末 terminal；不得用当前 24h terminal checkpoint 改 horizon 来冒充连续 7 天。

## 5. 同输入同输出的验证与停止门槛

1. **事件源门**：先对既有文件做不启动仿真的编码/解码与跨块读取测试。原始字节数、SHA-256、事件数、seq、数组顺序逐项相同；首末/重复块/截断行/篡改块/缺 blob/读时变化任一未被拒绝即停止。不是验证压缩率后就批准长运行。
2. **审计等价门**：用冻结旧审计和新审计对同一输入，在独立进程比较每个输出字段及拒绝行为。审计版本提升和本次明确修复的边界计数是登记的差异；不能把它们混进存储“完全等价”结论。实现流式存储时应以已修复的 batch 审计作为新 golden，保存旧 v1 报告而不覆盖。物理随机重放及来源必须全量，不做抽样 valid。
3. **指标门**：全窗、半窗、包含/不包含 detail、窗口恰在 release/completion/down/恢复处对照。沿用既有唯一数值容差：`production_family_statistics.*.queue_wait_lot_seconds` 的 `rel_tol=1e-12, abs_tol=1e-7` 秒；其余字段、整数、布尔、null、身份及列表顺序精确相等。若新算法还改变其他浮点求和，必须先登记新误差证据，不能一概放宽全部数字。
4. **负例门**：序号缺口、重复 plan/task/job、被替代计划派发、冻结任务丢失/重排、非法批/绑定、future task 假 ready、clock jump 越过 hold/机器释放/槽释放/not_before/plan expiry、缺 downtime/complete、错误 sampling/rework、缺 terminal/前缀全部仍失败。任何旧拒绝变成 valid 先停止诊断，不以“格式变化”带过。
5. **恢复门**：未来获准的小型验证在 busy、cascading 双槽、处理已完但运输未完、piece PM/日历停机、freeze/conditional hold、同时间多事件/过期 token 边界暂停。不中断与恢复后的选择、物理事件、observation/problem、计数/完整指标一致。恢复标记与墙钟耗时属于预先列明的非物理差异，不能用宽泛归一化删除其他字段。源/数据/hash/资源身份不匹配立即拒绝。
6. **资源门**：量测仿真、审计、snapshot、restore、报告编码各自 RSS 峰值及 raw/压缩/索引/临时/快照字节，而非仅指标进程。冻结每阶段 wall/RSS/磁盘/最大单记录预算及累计口径后才能试长窗；没有已登记预算即不进入 7 天。硬门超限在安全边界停止并留下机器可读失败/未运行矩阵；不能删 plan、只审计尾段、重置累计消耗或跳过失败恢复以继续。
7. **增长门**：记录 active WIP/job、queued token、retired job、累计事件/计划数及 RAM 容器大小。RAM 随已退休历史继续线性增长，或每次恢复复制整前缀，都说明工程门未通过；先查明真实 WIP 增长与历史泄漏，不能把合法物理拥塞当内存回归掩盖。数据体量本就增长的磁盘/报告须计预算，不声称总存储常数。
8. **分级门**：以上通过后，另行登记并串行做短窗双路径验证，再做 7d → 14d → 28d；每一级完整事件、审计、恢复和资源门全部通过才晋级。当前 256 MiB trace cap、目录 cap、计划数及 wall cap 均须在新版本配置明确登记，不能只改 horizon。7/14/28 天是拟验证窗口；工程门通过仍不等于预热充分、稳态成立或官方数值校准。

## 6. 本轮额外发现：not_before 审计缺口及最小修复

初始只读审查发现：修复前 `audit.py:380–387` 在 time_advance 内检查 ready/down/slot/hold/plan expiry，却没有加入机器待执行队列头任务的 `not_before`。六个合成事件 `initial, release, ready, plan(not_before=10), time_advance(0→20), terminal(waiting)` 被旧 `audit_opportunity_coverage` 和完整 `audit_trace` 同时接受为 `valid=True, errors=[]`。因此这不是存储性能问题，也不能以旧 valid 为绝对真值。

父任务随后明确授权仅改 `src/smt_fullfab/audit.py` 并新增 `tests/test_smt_fullfab_not_before_audit.py`。测试先红：6 项中只有上述负例的两个审计 subtest 失败，其他 5 个正例已通过。修复只在原边界集合加入严格满足 `t < pending[mid][0].not_before < target` 的头任务条件，仍使用既有真实就绪/资格/hold/顺序判断，不触发环境选择、不放宽约束。到达而未越过目标时刻合法；非队首任务不会被越序要求执行。

正例覆盖：到 not_before 后按时派发、显式 hold 跨过条件、条件恰在 horizon、机器正忙、目标机有其他合法候选但已提交任务的跨族前序尚未完成。旧 23 项加新 6 项，共 29 项通过（0.006 秒）；`git diff --check` 通过。全部是小型事件数组，未调用环境、模型或求解器。真实 pilot 的新版本全量只读复核由父任务随后执行，本文件不预报其结果。

修复后的 `audit.py` SHA-256：`76a6ed91858acf44f8951034a75f5b724e474591b60ebaac58d802d727e4686c`。新测试 SHA-256：`29ff8c7720414309b7046f322eed429d65fd6fc7db47e552147ec7beee1737bc`。总审计与机会审计版本分别为 `smt-fullfab-independent-plan-audit-v2`、`smt-fullfab-opportunity-audit-v2`；上表其余实现没有由本 agent 修改。本文方案尚未实现，不能称作已完成流式独立审计或已支持 28 天运行。

## 7. 已实施的最小事件读取接口

随后新增 `src/smt_fullfab/trace_source.py`，仅实现原单 JSONL 文件的检查与可重复读取，尚未接入现有消费者。`inspect_jsonl(path, expected_sha256=...)` 逐行读取完整原文件，保存原始字节哈希、字节/行/事件计数和文件身份；`open_verified(seal)` 每遍重新打开并重新验证完整内容。只有读到 EOF 且成功退出上下文才发布只读 receipt。提前停止、仅按预知事件数取完但没有确认 EOF、读时或跨遍改写、替换文件、吞掉解析错误、关闭失败均不能得到成功凭据。

空行仍参与原始字节哈希，原数组和记录不被筛选或排序；每条记录保留字节偏移和原始行。`scan_envelope` 仅检查 initial、连续序号、有限单调时间、声明窗口、快照前缀形状和末 terminal，结果明确标记没有执行物理、计划来源或机会审计，不提供可被误用为完整通过的 `valid` 字段。合法末行没有换行可读，截断 JSON 拒绝。

root 已亲自执行 `python -m unittest tests.test_smt_fullfab_trace_source -v`，16 项小型合成测试在 0.040 秒通过；最大夹具约 2050 条且小于 256 KiB，没有重跑工厂或已有大轨迹。该模块本身不积存记录，但最大单条记录和下游消费者仍占内存；当前整体长窗口限制、完整流式审计、块压缩与恢复设计均未因此通过。

## 8. 独立流式计划来源审计及真实旧轨迹对照

新增 `stream_source_audit.py` 逐条读取已校验 JSONL，以 SQLite 保存所有计划版本、已执行任务身份和完整 coverage gap；内存保留 manifest、当前/新计划及不超过原规则的200条错误。整数和字符串身份区分、重复版本覆盖后的报错顺序、冻结携带、显式hold、所有gap原顺序均保留。它只实现 `audit.py::audit_plan_sources` 的来源合同，未接入生产消费者，也不认证物理正确性或无遗漏合法需求。

独立审查实际发现并复现了最初实现的两项发布问题：发布后重开路径算哈希可能认证被置换的无关内容；发布后异常可能留下缺少持久来源回执的报告。v2改为写入临时文件时同步计算精确UTF-8字节哈希，完整报告内嵌 `_source_evidence`，与报告一起以create-new原子发布。发布后异常可能留下完整报告，不能把“未收到返回值”当没有产物；读取者须核对返回内容地址，不能只信路径。已有文件拒绝覆盖。root及独立复核均实际通过40项来源读取/审计测试，包含这两项故障和短写/清理错误。

root随后对两份保存的真实1小时轨迹做了只读逐字段对比，不启动工厂、模型或求解。第一次使用历史综合audit内的`plan_source_audit`作为比较对象，CR一致，A的`scope`与`absence_of_unreported_legal_demand_certified`不同。原因由原源码明确确认：综合audit在物理/机会检查后会增强这两个字段；它并非独立来源审计的返回合同。该失败比较完整保留在 `artifacts/smt_fullfab_semantics/stream_plan_sources_existing_1h_v1/`，没有删除差异或放宽相等规则。

第二次使用当前旧批量实现的**独立来源入口**作为比较对象，每个实现使用单独新进程、串行读取同一不可变轨迹。除实施版本及新增来源元数据外，全部字段、数值类型、数组内容和顺序精确相同；源/报告原始哈希、运行源码、返回回执和进程输出全部保存。结果位于 `artifacts/smt_fullfab_semantics/stream_plan_sources_standalone_1h_v2/comparison.json`。

| 保存轨迹 | 计划数 / 生产派工 | 旧来源审计峰值RSS | 新来源审计峰值RSS | 旧 / 新耗时 |
| --- | ---: | ---: | ---: | ---: |
| CR 1小时 | 242 / 1095 | 68,993,024 bytes | 56,410,112 bytes | 0.065 / 0.140秒 |
| A hybrid 1小时 | 47 / 1138 | 135,282,688 bytes | 67,190,784 bytes | 0.287 / 1.422秒 |

RSS含Python解释器与导入，耗时含来源审计和报告写入；两份旧轨迹是开发样本，不构成长窗口容量上界或性能置信区间。此次新审计减少历史内存但增加读取/索引耗时，磁盘、报告及单条记录仍可增长。完整物理/机会流式审计、环境活动状态和无损长窗恢复仍待完成。

## 9. 独立流式机会审计及真实旧轨迹对照

新增 `stream_opportunity_audit.py`，以 SQLite 保存历史 job、执行身份、ever-ready/planned、完成身份及完整 gap 数组。内存保留当前 lot/ready/pending/holds 和生产机器的活动槽集合。活动槽仍使用原 Python set 对象，保留碰撞及迭代次序，以免改变停机和错误处理的顺序；不承诺畸形无限占槽输入的常数内存。报告完整保留原字段与明细，采用写时哈希、内嵌来源回执及 create-new 原子发布，未接入当前生产入口。

root 对 CR 与 A hybrid 两份保存的1小时轨迹分别启动旧、新独立机会审计进程，固定 `PYTHONHASHSEED=0` 并串行运行。除实施版本与新增来源证据外，所有字段、类型、数组顺序及浮点结果精确相等，无新容差。输入原始字节保持不变，没有工厂、模型或求解调用。证据在 `artifacts/smt_fullfab_semantics/stream_opportunities_existing_1h_v1/comparison.json`。

| 保存轨迹 | 时钟边界检查 | 旧机会审计峰值RSS | 新机会审计峰值RSS | 旧 / 新耗时 |
| --- | ---: | ---: | ---: | ---: |
| CR 1小时 | 830 | 73,203,712 bytes | 51,445,760 bytes | 2.095 / 8.301秒 |
| A hybrid 1小时 | 1048 | 139,870,208 bytes | 58,851,328 bytes | 2.446 / 9.689秒 |

这两个样本显示历史数据转存磁盘可降低 RSS，同时明显增加耗时；不能外推完整长窗资源上界。独立审查对150个轻量畸形输入变体得到新旧相同的报告或异常，未发现阻断性语义差异。另确认一个读取兼容边界：原入口使用 `str.splitlines()`，会将字符串内未转义的 U+2028 当分隔符而拒绝；新入口按 LF 读取合法 JSON。已添加明确回归记录该差异，等价声明仅针对既有运行日志，不能扩大为任意原始字节的完全兼容。机会 `valid=True` 不证明终点、快照前史、来源或物理正确性。

## 10. 物理审计的流式投影适配

新增 `stream_physical_projection.py`，逐条重现旧 `audit_trace` 的物理事件投影：保留物理事件，为受控生产派工插入兼容旧检查器的 synthetic action、设置 owner、重编号并清空 terminal metrics。这些 synthetic action 仅为审计适配，不是额外模型决策或归属证据。源必须完整读到 EOF；输出采用独立新目录，最终 `projection.json` 完成标记原子发布。目录在完成前可见，不能仅凭目录存在当作成功。

`verify_projection_bundle` 同时提供原源，逐条重建并核对完整输出、源/输出回执及 manifest；因此共同改写输出与自报 manifest 不能冒充正确投影。已有目录拒绝自动覆盖或恢复，中断残留保留诊断。此次只完成投影适配，旧物理检查器的历史状态仍在内存中。

root 实际对保存的 CR 1小时源进行生成与重新验证：7,588条源事件，保留6,275条、跳过1,313条，增加1,095条 synthetic action，得到7,370条输出；输出3,916,061 bytes，SHA256 `f56f098c9edb7b889332d1450e8449a684124642c312cce106269298921a0124`。生成0.211秒，验证0.318秒，该进程峰值RSS87,769,088 bytes。验证原源与重建内容一致，但没有再次执行完整物理审计，也没有新增仿真或模型调用。小证据位于 `artifacts/smt_fullfab_semantics/physical_projection_existing_CR_1h_v1.json`，完整转换留在本地 ignored runs 目录。

独立审查随后复现了初版消费边界缺口：验证 reader 关闭后，在最终目录检查前替换 `physical.jsonl`，旧函数仍返回成功及已变更的裸路径。返回回执自身仍绑定旧字节，但后续裸路径消费者可能读到不同内容。修复保留转换格式v1，验证标识升级v2：在返回前核对原输出文件身份，结果明确为点时诊断，裸路径不再作为可持续消费凭据；新增 `open_verified_projection` 上下文入口，绑定比较阶段得到的同一个 `TraceSeal`，读取前、读取中、退出时均检查变化，只有完整EOF和成功退出才发布消费回执。不会重新检查被替换路径后给它新认证。

root 使用新入口实际重新验证并完整消费原CR转换的7,370条事件，输出回执与初版原字节哈希完全相同；旧证据与bundle未覆盖。独立验证0.346秒，验证并绑定消费0.356秒，进程峰值RSS92,651,520 bytes；这是另一次进程的实测，不能与旧生成耗时简单相加当统一计时。新证据为 `artifacts/smt_fullfab_semantics/physical_projection_existing_CR_1h_v2_consumption.json`，仍未执行物理检查器。

root 将差量29项、机会29项、投影31项、事件源16项联合运行，105项检查在0.332秒通过。整体环境 trace、快照深拷贝、观察历史、旧物理审计和部分指标历史仍未消除增长，7/14/28天运行门槛保持未通过。
