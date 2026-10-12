# 静态运行、回放与正式冻结审查

审查日期：2026-10-09。审查角色独立阅读 `src/runner.py`、`src/replay.py`、`src/report.py`、`src/experiment.py` 与模型预算/运行模块。最初仅做只读审查；主 Agent 随后授权本角色独占修复 `src/replay.py`、新增 `tests/test_replay.py`、维护本文。未修改原始开发记录，没有调用真实模型或重新求解。

## 结论与已修复问题

原回放有三项 P1 缺口，均以原始 `dev_mk01_B` 的**内存读取变异**证实，未改磁盘证据：把根记录输入 token 改为 999999999、把逐调用 output 改为空 order、把根记录 commit 改为 40 个零，旧 replay 都给出 audit_pass=true。修复后这些变异全部被拒绝。

| 优先级 | 问题 | 已执行修复 |
|---|---|---|
| P1，已修 | 汇总动作只与排程相符，未证明来自真实模型输出 | 逐调用核对原始 JSONL 的最终 agent_message、final.txt、model result.output、根 model_results 与 actions；再对 B 原始动作重做时间解码，对 C 检查参数对应、候选独立校验及明确 finish |
| P1，已修 | 原回放重算 token 后不与汇总比较 | 核对五种已报告 token、调用数、累计模型耗时和统一账本 reserve/finish；未知值保持 null，缓存和 reasoning 子项不重复累加 |
| P1，已修 | commit/tag/config/matrix 只记录、不回放核验 | 确认 commit 对象实际存在；正式读取每次 run 的 freeze.json，核 manifest hash、tag→commit、冻结文件的 Git blob hash、源码快照、有效配置、数据和矩阵格点 |
| P1，已修 | 只发现已有结果，缺失格点不构成不完整 | 正式按预先冻结矩阵列出 not_started 与 incomplete；缺 input、坏 JSON 不再静默跳过；重复/额外格点显式报告 |
| P2，已修 | 把辅助固定组合当作默认 C 或混入主要记录数 | F 的三次预设求解、参数、原始候选、账本、取最小候选分别核验；auxiliary_records / auxiliary_runs 单列，不填充 A/B/C 核心格点 |
| P2，已修 | 大实例紧凑协议未在回放中识别 | 根据 compact_state 审查对应问题字段；两种 B 动作都按原始输出解码，未加入代排逻辑 |

主 Agent 同期修复了运行器的非 development 阶段预算映射、有效配置与冻结配置关联、根校验不覆盖既有 timeout 状态、A 求解完成账本反映独立校验结果，并为新运行保存 source_snapshot。运行器保存正式 freeze.json 和 freeze_manifest_sha256；code_files 排除 configs/freezes，避免自引用哈希。以上主 Agent 修改未由本角色直接编辑。

## 实际验证证据

执行既有离线测试：

```sh
/usr/bin/time .venv/bin/python -m unittest tests.test_agents tests.test_fjsp_validation -v
```

42 项通过；该次计时 0.55 user + 0.15 sys 秒。此处测试中的模型输出均为控制流单元夹具；不会进入实验账本，也不是实验结果。

执行新增回放变异测试：

```sh
/usr/bin/time .venv/bin/python -m unittest tests.test_replay -v
```

17 项通过；最后一次 0.07 user + 0.07 sys 秒。覆盖正常证据、两种 B 格式、错误 root token、model output、final message、actions、调用数、耗时、commit、源码快照、正式配置/矩阵、缺失快照、未启动/在途格点、缺 input、坏 JSON，以及辅助组合审计。测试只生成独立临时夹具，退出清除；没有模型或求解器调用。

执行全部已完成开发记录回放：

```sh
.venv/bin/python -m src.replay --phase development --label runtime_review
```

`artifacts/development/replay_runtime_review.json` 对应 UTC 2026-10-09 02:42:27 的检查时点：A/B/C 已完成 15 条，15 条证据审计通过，其中 14 条成功、1 条失败；辅助 F 1 条单独审计通过；另有 2 条在途记录，仅标 incomplete，不推断进程已中断。此计数是审查时点快照，后续运行持续增加时以新的回放为准。

早期 development 的 dirty 源码只有 hash，没有逐运行源码副本。这些记录可验证输入、原始动作、排程、使用量等已有证据，但 `provenance_complete=false` 且 warnings 明示“不能仅由哈希恢复未提交源码”。不得将这种 audit_pass 表述成完整源码可恢复或正式验收通过。正式缺快照直接审计失败。

## 仍需主 Agent 在正式冻结前处理

### P1：token 预算缺少执行约束

现有 BudgetLedger 对调用次数和 requested solver seconds 有锁内硬约束，尚无每次/每批 token 预算字段与超额停止机制。transport 能返回已报告 usage，但在失败/超时时可能全部未知。只有调用数上限不能被写成 token 硬上限。

建议正式协议同时记录：单次输入规模上限、单次模型超时、每运行/每批调用数、每批已报告 token 停止阈值、未知 usage 时的停止/诊断规则。若本地 CLI 没有经过核验的输出 token 上限，应明确“不能在调用中精确执行 token 硬上限”；不得把 wall time 或字符数当作精确 token。实测 token 只能用作预算规划估计，不能伪装成实际美元账单。账本可在 finish 后累加已知 input/output，并在下次 reserve 前检查预声明阈值；这只能约束后续调用，不能消除最后一次调用可能超额的事实。

### P1：最终报告须以冻结覆盖与审计结果为入口

审查初期 report 仅扫描现存 result.json，其成功率分母不包括未开始/在途格点，也未先要求 replay audit_pass。建议 report 明确并列：预定格点数、已完成数、成功、失败、在途、未开始、证据审计失败。主要质量均值继续仅条件于成功，但完成率与成功率分母必须明确。辅助 F 应单列，不混入静态核心 108 条。

不能只因 `replay` CLI 返回 0 就宣布正式完成：development 没有冻结矩阵，coverage_complete 固定为 false；正式 CLI 在覆盖不完整时返回 2。最终需核 `coverage_complete`、`acceptance_ready`，再加 SMT 的独立闭环验收条件。

### P2：报告仍需补完整指标与统一求解耗时口径

运行时已有 first_action_valid、first_candidate_valid、first_valid_output_seconds、revision_success，报告应保留这些字段和定义，不只输出 first_output_valid/revisions。C 的首动作合法、首候选可行与最终明确 finish 是三个不同事件。

A/F 的 costs.solver_seconds 来自 CP-SAT 内部 wall time；C 的 costs.solver_wall_seconds 包含共享 solve 函数的建模/求解总时间。report 直接把两者都命名 solver_seconds 时口径不同。建议每臂均分别报告 solver_elapsed_seconds（外层）和 cp_sat_seconds（求解器），来源由保存的 solver 结果重算；端到端时间独立保留。

参考值 report 当前读取现行 `docs/fjsp-reference-values.json`。正式应冻结其版本并在汇总中记录 reference_sha256；历史重报应使用当时冻结参考表，或明确声明这是用新参考表重新评价，不能静默替换。

### P2：失败与恢复细节

transport timeout 的 failure_reason 已明确，但旧静态 `_invoke` 把 status 保留为 failed，只有外层 wall timeout 才写 timeout。报告可依 failure_type 统计；后续代码若统一 status，应保留旧记录，不能原地回填成新运行。

若进程在 reserve 与完成结果写入之间终止，账本应继续占用额度；回放会将此类尝试记为不完整而非零成本。授权恢复前须确认旧进程未继续运行。当前 replay 不用缺少 result 就猜测进程死亡；started 中的 pid/hostname 是诊断线索，不是“已退出”的证明。

## 正式冻结与预算操作建议

1. 静态核心矩阵固定为 12 个实例 × A/B/C × 3 次 = 108 条；SMT 的 27 条另用自己的冻结与轨迹验收，辅助组合另计。Hurink 必须继续按基础实例隔离开发/正式/预留。
2. 在任何正式结果可见前锁定实例、种子、模型配置、紧凑表示、步骤与超时、求解预算、token 策略、失败标准和辅助固定策略。mk10 仅作为开发规模探测，不能替换正式实例以回避失败。
3. 先提交执行代码、prompt、配置、依赖锁和数据/参考清单，再创建引用明确 code_commit 的 manifest 与 tag；manifest 本身另行提交。避免把 manifest 自身放入其 files 哈希集合。每次正式 run 保存该 manifest 的完整副本与哈希。
4. freeze.files 必须包含所有参与执行的源码、prompt、配置、依赖锁、正式输入数据及协议/参考文件。不要只锁源目录却遗漏依赖和解析后的实例。运行时源码快照应与 freeze.files 和 Git blob 三方一致。
5. 在串行正式运行前一次性分配总体预算，再分配有范围的 grant。若 B/C 各允许最多 3 次调用，108 条核心静态记录的调用上限为 36×3 + 36×3 = 216；若 A/C 每条求解预算各 30 秒，核心 requested solver seconds 上限为 2160。辅助组合与失败重试需额外预留，不能悄悄从另一阶段借款。实际采用的上限必须由主 Agent 根据开发实测冻结。
6. 运行后先做证据回放，再生成统计和图。正式 coverage 要包含全部失败，不能删除超时或重试前记录；修复后的新版本不能覆盖旧冻结与旧结果。

本次代码审查没有验证正式矩阵已完成；当时正式尚未冻结/运行。新增单元测试证明回放会拒绝相应证据变异，不能替代主 Agent 对实际正式结果、版本关联和最终报告的一次完整复核。

## 主集成关闭记录（2026-10-09）

Token停止规则已由预算模块实现并通过14项新增测试；报告现在调用完整证据回放、核心与F分列、A/C/F统一solver_wall_seconds（旧开发未记录者留空）；正式参考表从冻结commit读取。静态/SMT正式核心与辅助分别使用独立phase和freeze，避免辅助填充核心矩阵。
