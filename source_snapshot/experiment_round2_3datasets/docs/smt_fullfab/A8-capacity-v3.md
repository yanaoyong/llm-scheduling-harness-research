# A8 容量开发 gate v3

本轮新增 `A_1701_8h_hybrid_v3`，保留 v2 的冻结协议、源码、原始失败和资源账本。2026-10-10（北京时间）已从 d69afe7 冻结116份输入并完成实际串行运行：完整8小时、635版计划、6932次生产派工；来源、机会、物理与最终外层验收全部通过。独立验收读回通过，最终681145641-byte快照由同一50份源码准确恢复，完整状态哈希相同。

端到端外层1678.206秒、子进程峰值RSS2568454144 bytes、全部原始证据5281913668 bytes。主指标87.038907 lot·小时，完成15 lot、末WIP2172、逾期WIP9。独立读回和恢复分别另耗18.404和113.003秒；这些子进程测量不包含父层哈希、报告编辑与阶段间等待。零模型调用，仍是单个冷启动开发记录。

[真实验收](../../runs/smt_fullfab_offline_A_gate/A_1701_8h_hybrid_v3/acceptance.json) · [恢复证据](../../artifacts/smt_fullfab_recovery/A_8h_hybrid_v3_final_restore_v1/result.json) · [终末报告与全设备族图](../../artifacts/smt_fullfab_diagnostics/A_8h_hybrid_v3_terminal_v1/report.json)。冻结协议的实现阶段字段保留原样，实际执行状态以已绑定的 manifest、attempt、acceptance 和上述检查为准。

## 登记的参数

| 项目 | v3 |
|---|---:|
| 仿真窗口 / seed | 28800 秒 / 1701 |
| runner 与完整 child 实测 wall | 不超过 5400 秒 |
| 外层 watchdog / 最终外层 wall | 6000 秒 |
| 冻结 bundle 存储只读复核子进程 | 独立 180 秒 timeout，全部耗时仍计入 outer wall |
| 完整 trace | 不超过 2 GiB（2147483648 bytes） |
| campaign + run 全部留存文件 | 不超过 16 GiB（17179869184 bytes） |
| 启动前可用磁盘 | 至少 40 GiB（42949672960 bytes），不等于预留空间 |
| child 实测 peak RSS | 不超过 8 GiB（8589934592 bytes） |
| 尝试的计划数 | 不超过 1200 |
| CP 累计请求秒 | 32；16 个周期边界，每次 2 秒 |
| 事件构造 | 5 秒软限额 / 250000 候选评估 |
| plan / period / lookahead / slots | 14400 / 1800 / 2 / 4 |

`solver_method='hybrid'`，单 worker、solver seed 11、event total slots per machine 8；算法参数保持 v2。变化是新运行身份、容量登记、`audit_mode='stream'` 和 `snapshot_mode='stream'`。`max_trace_bytes`、`audit_mode`、`snapshot_mode` 三项均进入新 config 与 `checkpoint_resources.hybrid_resource_limits`。旧默认 config identity 不受本 gate 更改。

## 精确留证与验收

`offline_A_gate_v3.prepare()` 冻结全部 src、原始数据、vendor、requirements 和协议文件哈希，另记录运行时与来源 Git 指针；dirty 文件的真实 SHA 是依据，Git HEAD 不冒充 clean checkout。新 campaign 为 `runs/smt_fullfab_offline_A_gate/A_1701_8h_hybrid_v3`。准备不启动 child，已存在或中断的目标不能被自动接管、重跑或补验收。

child 在导入冻结 runner 前写自身 PID。在 `try/finally` 中保存 `resource.getrusage(RUSAGE_SELF).ru_maxrss` 到 `child_usage.json`；macOS 的原始单位为 bytes，Linux 为 KiB，回执同时保存原始值、平台、单位与换算值。PID 必须与 launcher 的实际 PID 一致。缺失、非法或超出 8 GiB 都使 gate 失败。SIGKILL 无法执行 finally，因此缺失记录是失败证据。此机制是最终测量与验收，**没有运行时 RSS 硬守护，也不测父进程或整个后代进程树的累计 RSS**。

runner 保存独立 `audit_bundle`，gate 不生成旧的全量 `audit.json`。gate 在另一个 `-I -B` 子进程中导入同一 frozen 源码的 `read_bundle`，核对六个成员的完整字节 SHA/长度：source、opportunity、physical、metrics、projection manifest、projection JSONL。此步骤是已有语义报告的存储核验，不重复执行物理审计。

该只读子进程固定 180 秒 timeout，超时终止并使验收失败，保留全部报告；不自动重试，已消耗 wall 计入外层最终时间。它不延长主 child 的 5400 秒限额或外层 6000 秒验收限额。后续只读验收回放同样具有此 timeout。

独立审查发现初版 v3 在 read_bundle 验证后、最终 evidence 哈希采集前，可把被替换的非 source 成员纳入当前成功验收。该原版和反例保留在 `artifacts/smt_fullfab_diagnostics/A8_capacity_gate_review_v3/`。本次窄修复让 `_validate_run` 返回验证时的八项原期待 SHA（bundle manifest、六成员、raw trace receipt SHA），在最终 `_evidence` 完成后逐项相等才可通过；这些原 SHA 另存 `verified_audit_evidence_sha256`，失败也不重新锚定。`verification.json` 只描述最终绑定前的保存结果检查，最终通过与否以 `acceptance.json` 为准。成功验收回放在重新验证之后再次采集 evidence，并同时核对原验收与这八项验证哈希。此检查不承诺返回后文件永不被修改。

之后 gate 精确核查：

- bundle 来源 receipt 对应完整 raw trace 的 SHA 与长度，原始初始 manifest 数据哈希对应冻结输入；bundle 来源、九项审计依赖 SHA 均对应 frozen inventory。
- 三项独立审计有效，完整 terminal 位于 t=28800，观察起点为 0，horizon 为 28800；全部相关认证标志为 true，source/opportunity 错误数组为空。
- 完整 `source.json` 的顶层字段声明全部 913 台生产机器和完整控制域，来源 receipt 完整。该 JSON 的解析字节必须等于 bundle 成员 SHA，且读前/后文件身份一致。任意深度重复 key、截断或以嵌套字段代替顶层字段均拒绝。
- result 仅镜像六项主指标，与 bundle summary 相等：window_start、window_end、weighted_tardy_lot_hours、throughput_lots、terminal_wip_lots、terminal_tardy_wip_lots。完整指标仍在 hash-bound `audit_bundle/metrics.json`，不会声称 result 含全部指标。
- 每条 planner reserve 有对应 finish 与 problem/solver 文件，明确 nominal valid；累计时间、调用数、16 个周期边界、32 秒 CP 与 checkpoint 资源继承一致。
- checkpoint 文件实际存在，runner 保存完成的准确路径且无 checkpoint_failure；完整 checkpoint 字节进入外层 evidence SHA。新 writer 仍输出 snapshot-1，状态及动态依赖哈希合同由冻结 writer 与独立 parity 测试约束。本 gate 不把巨大 checkpoint 再次恢复或整份解析，也不声称已证明恢复等价。
- runner 成功以外仍须满足 child wall、outer wall、trace、全部证据字节及 RSS 上限，外层 `acceptance.json` 才能接受结果。

所有原始文件、stderr、exception、审计错误与失败验收均保留。达到上限或异常不会换 run ID 自动重试，不改原消耗，也不提高本次容量。已有验收只读回放必须再次验证 manifest、所有 evidence SHA、字节总量与成功所需的验收条件。

## 验证与启动入口

小型测试命令（不会运行真实 child/factory/model/CP）：

```sh
.venv/bin/python -B -m unittest tests.test_smt_fullfab_offline_A_gate_v3 -q
```

测试在独立临时目录冻结极小输入并合成报告；真实调用的 `read_bundle` 仅核对保存的字节。另有一行 dummy runner 子进程，验证正常退出和非零退出都会记录同 PID 的 RSS；不导入真实 runner。没有创建大或 sparse trace。

初版作者验证为 41 项通过，6.377 秒；其后独立审查发现上述最终绑定缺口。修复后新增五类原反例、全部八项晚替换及全部八项回放替换回归，45 项通过，10.981 秒（2026-10-10）。timeout 用 mock 注入，不实际等待 180 秒。这些启动前合成测试不是实际运行成功证据；实际运行及恢复结果见本页开头的独立原始文件。

以下为已执行阶段的入口说明；本条运行已经成功，禁止再次启动或覆盖其证据：

```sh
.venv/bin/python -B -m src.smt_fullfab.offline_A_gate_v3
.venv/bin/python -B -m src.smt_fullfab.offline_A_gate_v3 --execute
```

默认命令仅 prepare。若准备后 live supervisor/helper 改变，必须使用已冻结版本；已经失败或中断的尝试不会因再次执行命令而消耗新预算。

## 仍存在的内存边界

这是一个 8 小时容量开发门，不是 7/14/28 天就绪声明。gate 为准确读取 913 覆盖字段而完整解析 `source.json`；当前该报告规模较小，但不承诺随运行时长常量内存。初始 manifest 单行、资源行以及 evidence 哈希索引也有实际大小成本。

流式 snapshot writer 避免旧的历史 deepcopy 和整份 JSON 字符串，但 environment.trace 仍在 RAM，恢复读取器仍使用旧合同。metrics 的区间结构、physical 报告数组、现有 planner/runner 保留结构仍可能增长。disk-backed trace 原型没有接线。本轮的 RSS 仅实测此版本是否在登记的 8 GiB 上限内，不替代这些后续改造，也不证明稳态、官方校准或 A/B/C 排程质量优劣。


独立只读检查的实际命令已记录于 `artifacts/smt_fullfab_recovery/A8_v3_postrun_checks.py`：`acceptance` 与 `restore` 两个子命令均已执行并通过，已有输出目录会拒绝重跑。
