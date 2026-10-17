# 封存证据验证（Phase G / H，2026-10-17）

最新验收修订与结果见文末 Phase H 节；以下 Phase G 结果为历史记录。

完成授权的离线验证，没有网络、下载、Codex 或模型调用。M0b、M2 通过；M1 的旧计数、机会统计、w1462 与共同终点检查通过。**两条原数值验收假设被公开封存证据否定，保留原测试失败，不调整账本或删改断言来凑数。**

## 环境、来源和哈希

沿用 Phase F 预装环境：Python 3.10，SMT2020 Dataset2 LVHM，PySCFabSim-revised 固定提交 `ae3d55e`，tiktoken 0.14.0 / `o200k_base`。物理源码、vendor、数据和 evidence 均只读。版本及数据逐文件哈希沿用公开物理验证报告；本次恢复仍强制核对 data_hashes。

来源根目录：`/workspace/v6-mac-env/evidence/project/experiments/context_window_batch60_20261016/`。以下 SHA256 是实际读取的公开文件字节，而非历史 CAS 文件名：

| 相对来源路径 | public SHA256 |
|---|---|
| `fixtures/initial/mixed_702.json.z.public.json.z` | `818791f0a510bf04603bb88c2a7a6fcc4e601ddfc25cd19ec178ed686a420b1e` |
| `live_pilots/extended_three_group_final_segment_20261017/G0/events.sqlite3.public.sql` | `fc0c85531a88cda38965d22e9423e6db17317fffc873f9e5b53707a889cb928d` |
| `live_pilots/extended_three_group_final_segment_20261017/G0/exports/trace.jsonl` | `88e10c25344403d5f70f08100f881fc2fc231ac6f6f94b5c2cbeda2fb41b3c93` |
| `live_pilots/extended_three_group_final_segment_20261017/G1/events.sqlite3.public.sql` | `acca848e55b010bb744f6a4ec8309a3f989cb4a91ca628160490f48e5d1c65e5` |
| `live_pilots/extended_three_group_final_segment_20261017/G1/exports/trace.jsonl` | `e1409d9db38642da172154455a81af7c522cc98ab430b300368cde8a6cf6841c` |
| `live_pilots/extended_three_group_final_segment_20261017/G2/events.sqlite3.public.sql` | `d700344323a22725dcd4d20166ab2c85184a76f4c20a0a720354ec862069e68d` |
| `live_pilots/extended_three_group_final_segment_20261017/G2/exports/trace.jsonl` | `64435177554820e134332fa5923e118ea4dd5cb3342375b12a9a4124583f58da` |
| `live_pilots/extended_three_group_final_segment_20261017/G0.config.json` | `7f2daaea1fa3e8a36c11717bcbb0b6f78390bed4346bcf068f139e5a1604bcfb` |
| `live_pilots/extended_three_group_final_segment_20261017/already_planned_replan_case.json` | `e217e0cf72cc9e0151716b1d25e49f075d98b1dcad83f8319f854c24facd4d97` |

完整逐对象路径/public SHA256/解码 canonical SHA256 索引保存在 `/workspace/v6-mac-env/work/sealed2/provenance.json`（292 个来源条目；索引自身 SHA256 `1e59692b191336a943d5e62db677157cdafcebf184b44369619aaff26b74c566`）。源码、报告以外的证据不写入仓库。

哈希与适配规则：

- `.public.sql` 导入 scratch SQLite；读者使用只读 SELECT。历史 ref 仅用于查找 `.z.public.json.z`，不拿历史文件名认证公开字节。
- 每次读取压缩对象重新计算 public SHA256 和解码 canonical SHA256；83 个 context 的 problem/base_plan/execution_state 三个公开锚点记录于 build_summary.json。没有伪造原 source_sha256 或重新签署私有历史链。
- mixed_702 通过 factory_v6.restore 导入，删除旧 batch_state 并采用 v6 的显式默认字段；capture/restore 用重新计算的 v6 状态哈希核对。
- 归档 commit 按 time/revision 排序，连接 candidate.compiled.plan，生产任务字段不改写；原始触发回放不重新提交旧 context 的四锚点协议。
- d34-421 只建立新 version/created_at/freeze_until 提交信封，排除已派工任务，63 个原 pending task 逐字段保留。
- G0 共同终点在已有 execution_batch 内短回放，逐条对照 sealed 物理事件；G1/G2 使用精确封存终点状态。派生观察用 measured: 引用且 trigger=None，不计作归档模型上下文。

## 逐项结果

| 项目 | 实测与判定 |
|---|---|
| M0b 702→1603.10 原触发等价 | 21 次封存提交；128 个事件完全相同：66 dispatch、61 operation_complete、1 downtime；零差异 |
| M0b mixed_702 往返 | `True`；v6 capture SHA256 `df8233d70755c0a5dc9406c15f61b4328a60bda1d7f129f76a4cff2552d042e7` |
| M1(a) 旧规则 | G0/G1/G2 = 10/15/4，精确复现 |
| M1(b) 新规则全部不触发 | **未通过**：29 个旧 reserved-only context 中 27 个不触发、2 个因独立未预留工作触发；详见下表 |
| M1(c) 机会 | 75 个 context×operation 机会，10389.520466157 预测秒；同一 context 内替代机组去重，跨 context 不去重；不是轨迹空闲积分 |
| M1(d) 共同终点 | 使用真实共同终点 1603.1013031725258，与 1603.10 回放截点相差约 0.001303 s；见下方各组指标 |
| w1462 | `context:0bbe380124204cab9822a61d`；avoidable_idle=0，已预留机会不触发 |
| M2 d34-421 | 原 G1 context:5d8f83e783d146d49c66f8ed；t=1343.6907074665332；原 not_before=1343.0145576611412；63/63 pending task 保留，commit 与 detached precheck 通过 |
| M3 pending 完整性 | **26 pending 假设未通过**；归档 base_tasks=26，dispatched=3，实际 pending=23；全部 23/23 原样进入快照，holds=0 全保留 |
| M3 真实 token / 预算 | 完整快照 756359 tokens；静态前缀 563837；running jobs=907；注册旧 G0 input budget=220000 时失败关闭，dropped_rows=0 |

完整前缀包含实际 MCP tools/list 描述和 schema、规则、真实路由和机组表；当前快照含真实运行作业。220000 来自封存 G0.config.json，仅用于该历史预算的可比性检查；v6 live 预算仍未登记。本次没有把诊断预算冒充实际试验授权。完整快照本身超出该历史输入预算，不能据此宣称已具备 live 运行可行性；分层/分区与 v6 预算仍需另行决定。

| 组 | 去重机会数 | 静态潜在秒数 |
|---|---:|---:|
| G0 | 29 | 4052.952805542 |
| G1 | 42 | 6070.137418050 |
| G2 | 4 | 266.430242564 |

## 两个新触发例外及原因

两者均在 t=1593.1323091758827，avoidable_idle=1（machine=325，operation=w1703:86:1），explicit_wait_idle=0。旧缺口的工序均已预留，但另有机组因既有未来队列被旧 _gaps 隐藏。新账本发现的是另一项未预留合法工作，不是把 reserved opportunity 当触发。

| 组 / context_ref | machine 325 的原队列任务 | reserved 机会（原始行 / 去重工序 / 秒） | 独立审计 |
|---|---|---|---|
| G0 / `context:97eada3675ec457ca5a28750` | d39-b → w2086:133:1 | 11 / 2 / 96.227938975 | {'differences': [], 'ok': True} |
| G1 / `context:61d6652b89614a3aa60bfe1e` | d40-2086 → w2086:133:1 | 11 / 2 / 153.639272916 | {'differences': [], 'ok': True} |

全部指标（含 assigned_not_started_age 与每个机会见证）保存在 scratch classification.json / validation.json；没有省略任何例外。该差异来自验收假设遗漏队列遮蔽工作，与脱敏哈希、Python 浮点差异无关。现有合成测试也明确允许 reserved-only 旧提醒与另一项未预留工作共存。

| 共同终点组 | avoidable_idle / explicit_wait_idle | w1703 见证 |
|---|---|---|
| G0 | 1 / 0 | [('avoidable_idle_matches', 325)] |
| G1 | 1 / 0 | [('avoidable_idle_matches', 325)] |
| G2 | 1 / 0 | [('avoidable_idle_matches', 325)] |

## 26 与 23 的差异

G0 context:30872dadac0f4aaf8e3799de 的 base_plan 确为 26 项，execution_state 明确列出 3 项 dispatched_task_ids；独立 trace 也逐项证实：

| 任务 | dispatch 时间 | plan_version |
|---|---:|---|
| d36-e | 1628.8623616754553 | dispatch-55 |
| d39-g | 1639.675607688566 | dispatch-55 |
| d32-l | 1647.0 | dispatch-55 |

因此 1649.8155803370928 的正确 pending 数是 23。没有删除任务来适配预算；3 项已派工任务不应伪装成 pending。原 tests/test_sealed_contexts.py 的 26-pending 断言保留。该差异是计划总数与待执行数混淆，不是公开脱敏或 Python 版本造成。

## 修复、测试及剩余门槛

修复 env_adapter 的原触发回放路径：不再生成 v6 ledger_snapshot 或触发新增 no_plan/event 分支，避免大量与原回放无关的诊断 trace；正常 advance_cycle 仍逐步记录账本。新增纯合成回归，验证原缺口停止和不调用 v6 ledger。隔离清单 copy SHA256 已更新。新增 archive reader 合成测试及 mixed_702、d34 保留、w1462/共同终点 Mac 断言；既有断言和旧测试全部保留。

- `phase-g-plain-final.log`：251 passed, 41 skipped, 42 subtests passed in 36.89s
- `phase-g-configured.log`：2 failed, 278 passed, 12 skipped, 42 subtests passed in 908.00s (0:15:08)

Configured 的两条失败必须保留：test_mac_sealed_classification（两个例外）、test_mac_snapshot_26_pending（23≠26）。其余 skips 仅为 9 个 MCP/F6 与 3 个 single_action Codex 探针；没有缺失封存数据导致的 skip。故不能宣称全 configured suite 通过。要关闭数值验收门槛，需要先修订已被证据否定的验收假设；本阶段不擅自改写。

方案覆盖：审查修订版 §二 模块 replay/factory/ledger/normalize/snapshot 与里程碑 M0b/M1/M2/M3；§一 F4（不外推新轨迹）、F5/F15（预留机会和队列遮蔽）、F9（完整任务）；长运行补充 §二.3（完整快照规模与失败关闭）。

仍未运行：Codex F6/single_action 探针、真实模型 E1/P2×3、S2–S4、真实进程崩溃和完整会话日志链。预算/质量门槛仍待登记，CQT/Q-time 未实现。没有以此静态分类估计 v6 轨迹、调用数、真实成本或质量收益。复跑命令见 MAC_VALIDATION.md 的 Phase G 节。

## Phase H：修订验收与完整任务核验

编排者修订原文以“编排者修订，待用户确认”登记在 DECISIONS_v6.md。
按 reviewed plan §二 M1(b) 的“例外逐条列出”核验例外，而非要求 exceptions=[]；
M3 的 26/26 改为所有 base-plan tasks 可见，不再混淆总数与 pending 数。
旧规则 10/15/4 断言未改，未改账本、物理语义或原始封存证据。

M1(b) 测试钉住上表两个 context/ref/time/machine/operation，并以独立 audit_ledger
确认 avoidable_idle=1 与匹配完全一致。所有旧 gap 工序均已预留，w1703:86:1
不属于任何预留工序、旧 gap 工序或预留机会。额外静态反事实检查仅移除该未预留见证：
reserved_but_earlier_startable 列表保持原样，ledger 与独立 audit 的 avoidable_idle
均归零。这验证预留机会本身不会触发，不外推新轨迹。

M3 从真实 G0 head state（t=1649.8155803370928）提取全部 907 个未完成作业，
使用与 Phase G 完整 token 测量相同的 running-job 行构建实际快照，再与独立 dispatch trace 对照：

| dispatched task | operation | machine | running job |
|---|---|---:|---:|
| d32-l | w259:29:1 | 1293 | 976 |
| d36-e | w1942:15:1 | 985 | 974 |
| d39-g | w39:416:1 | 972 | 975 |

三项在快照中均按 job、lot、machine、started_at 可见；trace 的 plan_version、task id、
steps/visits 逐项核对。23 个 pending 逐字段保留，加上三项恰覆盖 26 个 base task，
0/0 holds 与 1011/1011 ready 行检查保留。原 context 不含 running_jobs，旧测试传入空列表；
现在 fixture builder 提供从真实状态提取的 g0_snapshot，测试不再使用空列表。
**完整快照没有丢失这三项，snapshot.py 无需修复，也不新增无关生产逻辑。**

修改文件：DECISIONS_v6.md、MAC_VALIDATION.md、本报告、tests/test_sealed_contexts.py、
scripts/build_sealed_fixture.py、scripts/validate_sealed_fixture.py。未删除旧测试；两条断言
仅按本阶段明确授权修订，并增加独立审计、反事实与实际运行任务身份核验。

刷新测量脚本通过（`phase-h-validation.log`）：旧计数 10/15/4、两个例外；G0 回放 128 个事件
完全相同；26/26 accounted；完整快照仍为 756359 o200k_base tokens（prefix=563837），
历史 budget=220000 时失败关闭，dropped_rows=0。运行作业 907、ready rows=1011、holds=0。
本次从零重建并测量后的 provenance 为 290 项，SHA256 为
`89e46591266dc135663ed5e38d216284dd0b666d33a4c6251f177984d82fc062`。
它取代 scratch 中 Phase G 的 292 项索引；Phase G 上文哈希仅为历史记录，不能用于当前索引。
原始 evidence 未修改，所有重新读取的来源仍按公开字节和解码 canonical 内容记录哈希。

完整复跑结果：

- `phase-h-plain.log`：**251 passed, 41 skipped, 42 subtests passed in 36.61s**。
- `phase-h-configured.log`：**280 passed, 12 skipped, 42 subtests passed in 1002.87s (0:16:42)**。
- 12 configured skips 仅为 9 项 MCP/F6 和 3 项 single_action Codex 探针；没有封存、物理或 tokenizer 缺失导致的 skip。
- 两条修订验收实际通过；未使用 skip/xfail 绕过原失败。Python 编译及 `git diff --check` 通过。

全部生成的 fixture、SQLite、逐项指标和日志留在 scratch。
未运行 Codex/model/network；原有 F6、live budgets、CQT/Q-time 与长时间验收限制仍适用。
