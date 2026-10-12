# B 后续计划/分页状态恢复设计（尚未实施）

本文件只读分析当前 B recovery 001 的代码和已保存证据，不改变正在运行的进程、注册、墙钟上限或旧验收。本轮没有模型、求解、模拟、恢复执行或大轨迹重放。运行中的文件可能继续增长；下面数字只是注明时刻的观察，不是完整运行结论。

建议顺序：先让现运行按原上限自然完成或失败并保存 checkpoint/关闭账本；再只读准备一个绑定整个祖先链的新恢复包。只有原登记资源仍有余额、没有在途请求、完整后续状态可验证，才可能实施同登记续作。资源耗尽后若继续研究，应建立另一个明确的 development 注册/结果身份，保留旧运行失败，不能修改旧上限后宣布原运行通过。

## 1. 本次读取的证据

观察时刻：2026-10-09T15:59:48.451220+00:00。运行目录为 `runs/smt_fullfab_stage2/B_1701_1h_complete_v2__recovery_001`；原始父运行是去掉 `__recovery_001` 的同级目录。

| 证据 | 读取结果 |
| --- | --- |
| 最新 `recovery_state_00108.json` | `model_attempt_pending`，`plan_index=3`，物理时间 `1543.3357692936547` 秒，`next_page=5`，`next_model_index=65`，segment wall `2489.039228416048` 秒 |
| 当前计划接受前缀 | 页 0–4，分别来自 model 059–063；累计 tasks digest `97db82bcef8a6ee803b5e8d0fd0b271292c2a9c0da6b2064f538cd53d9222421`，holds digest `335119992462c2696fed25690300d949f25cff9b55af5722e7b39eb57a0fcd48` |
| 在途请求 | 实际为 `model_064`，call ID `1e301fa6-ff63-45cb-85b5-ce3bbe1b4fdc`。`next_model_index` 在调用前已加一，不能据 65 自动跳过/重打当前页 |
| 已接受页日志 | 63 条：plan 0 的 18 页，plan 1/2 各 20 页，plan 3 的前 5 页；含父运行原有 14 页引用 |
| 已提交计划 | `plan_commits.jsonl` 3 条，对应 plan 0、1、2；每条保存全部 source page call IDs，最终 call ID 只是末页 commit 来源 |
| 物理快照 | 尚无 `checkpoint.json`；有 `restored_cold_checkpoint.json`（7,218,100 bytes）。代码只在结束路径再保存最终 checkpoint，运行中的 progress 不会保存非零状态快照 |
| 结束证据 | 此时 `result.json`、`acceptance.json`、`audit.json`、`recovery_audit.json` 均尚不存在；这是正在运行时的状态，不是据此认定运行失败 |
| 当前观察 | `problem_003.json` 物理 time 同上，lookahead `horizon_end=15943.335769293655`，`frozen_tasks=[]`；manifest `page_count=20`，源 problem canonical digest `99a4bb8f6a156547864262aca613b9a5790dd3a5ca2bf625a6acd6d40387bc10`。观察终点仍为原仿真 3600 秒，不能把 lookahead 终点当新实验窗口 |
| 原注册 | ID `9b6bf10b5c051a580150038923df2acbd1809d06075e2b0de3e86dedd0c16754`，B/seed1701/window3600，`formal=false`，累计 wall7200秒，日志1,073,741,824 bytes，B solver0 |
| 已继承成本 | 15 次原尝试，490,574 已报告 input+output tokens，unknown usage 空列表，model active `1055.5504198319977` 秒，runner wall `1058.1733287500683` 秒，日志82,589,411 bytes |
| 当前请求前 B 原登记账户 | model active `3510.1202639949042` 秒、64 次尝试、1,977,260 已报告 tokens；随后已 reserve 第65次请求。该 active 时间不包含仍在进行的 model064，不能视为最终累计值 |

关键文件原始 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| recovery 001 `config.json` | `3043d3f4f9da3c085c6fb2687234081a8a5f61d8d3c59680eba6c3dfb788a669` |
| `recovery_mapping.json` | `09ade406c0e119daddbd12d9295a076c52fccc98e1567be690ed1ad307263418` |
| `protocol.json` 的保存副本 | `dff2532efb39dc71abbfe69f6191afdff7b535ec210a7342172741b8dbd58fe2` |
| `recovery_state_00108.json` | `03c65a145c93be3cbcf528085e2a2a1b25baaccd3a9d3236e8ee984a04150a23` |
| `problem_003.json` 原始文件 | `af2e08b96937607e7cc556b4043d5dd8942cf3328cf51fa0f04a158a993a5b82` |
| `page_manifest_003.json` | `0a3cda9fb31a89c0b45b929f8314bcffec7492d830a4bc4be0bd9c258315ae19` |
| 当时 `page_accepted.jsonl` 58,236 bytes | `a876608949223a2f1fb51a1f22fd304dd34b0d1941e972a0535ceb7d5029d56f` |
| 当时 `recovery_decisions.jsonl` 32,559 bytes | `71bc8161f1d45796a65f1af6a3761b3e3236b844923f5b1ee610e03c1dfbb64c` |
| 当时 `plan_commits.jsonl` 3,264 bytes | `3a5336c027a155767b9e309a33936fb6ab12eb2448c7a8874c8d8ff065e6f299` |
| 当时 ledger 215,066 bytes / 176 条 | `0d1611de9f4b6369b87d4410b25edc42e8647a33028b4a25d07267fd8ecc169a` |

这里的日志 hash 是当时读到的前缀身份；本次没有锁定或封存正在变化的目录，不能把它们当最终 recovery package 的 inventory。原始文件 hash 与 `digest(JSON)` 是两种不同身份，不能混用。`config.protocol_sha256` 指向原 preregistration 文件；运行内重新序列化的 `protocol.json` 原始字节 hash 不同并不自动说明内容改变，应分别核对路径/原始 hash 与解析内容。

## 2. 现实现为什么不能直接继续

`controller_resume.py::verify_recovery_package` 明确要求 package plan_index0、父 result failed/t0/0 committed plans、原 checkpoint 无 plan/executed_tasks/plan_versions；`run` 只接受 `父名__recovery_001` 且目录必须不存在。`budget.py::_recovery_mappings` 和 `register_recovery_segment` 也明确拒绝已有恢复链后的新 segment。删除目录、改 package 的 t 或把 plan3 重命名 plan0 都会破坏既有身份，不能作为恢复办法。

`progress()` 保存的是观察用游标，不是恢复事务：没有关联非零物理 snapshot hash、trace prefix hash/字节数、当前 problem/manifest/page 的文件 inventory，也没有失败反馈实体与最后 reason。accepted patch、model output、decision journal 可以补证一部分字段，但不能仅信其 staged hash 就重建全部物理状态。

另一个阶段歧义必须显式修正：`plan_count += 1` 后才写 `progress("plan_committed")`，随后 `physical_execution_stopped` 仍保留刚提交计划的 accepted 列表。因此这些状态的 `plan_index` 指向下一轮，而 `accepted_pages` 仍属于上一轮。只有 `pages_ready/page_accepted/model_attempt_pending` 的 accepted 列表通常属于当前分页轮次。后续恢复包需要分别记录 `committed_plan_count`、`last_committed_plan_index`、`page_plan_index` 和 stage，不能统一把 state.plan_index 当列表所属计划。

现 `controller_resume_audit` 只认证一段冷态直接恢复：trace 前缀是原 t0 parent；model目录从原 package.next_model_index 连续；当前目录的 commit 条数与整 trace 的提交条数相等。跨 segment 后，历史提交已在 trace 中，但不应在新目录重写为“新提交”。必须扩展独立审计的链模型，不能简单删除这些断言来让新段通过。

## 3. 最小后续恢复包

建议新增版本化的只读 `prepare_later_recovery`，首先支持**已自然终止、最终 checkpoint 已成功保存、没有 pending、停止在分页状态**这一种情况。此时页处理不改变 env.t，已有非零 checkpoint、当前已存 problem 和已接受页面可以互相核验；先不处理任意物理事件中途崩溃。

包至少包括：根 registration/原 parent ID、按顺序的 ancestor segment ID 与各 finish/finalization hash；精确停止 stage；非零 checkpoint path/file hash/state hash/implementation hashes；trace 初始前缀、各恢复标记和末前缀字节/事件数/hash；当前 problem、manifest、全部 page、frozen B prompt/schema 与 decoder/crop 源身份；当前分页所属 plan、accepted page 0..k-1 的 patch/call/model path/hash 与累积 tasks/holds；被拒页的原输出/反馈、page/plan revision 已耗次数；所有 request/reserve/finish/decision 对账；当前未执行 plan/frozen/executed 身份；累计预算快照和完整证据 inventory。

准备器逐页**重新验证已保存的原输出**，按记录顺序串接 tasks/holds，比较累积 hash，绝不重新请求已接受页、重排模型选择、补批或自动修复。当前 manifest/pages 必须原样复用，不以最新 env/problem 重新分页后继续旧 cursor。还原 env 后重新导出当前 problem 的比较只用于证明观察一致；不替换已向模型披露的观察。

正常失败后若 `checkpoint.state.trace` 与 trace 文件完全一致、恢复 roundtrip 仅多一个明确 snapshot_loaded 标记、公开 problem 一致，仍须检查物理前史和提交来源；snapshot 自报 hash 不能单独证明私有 q/jobs/PM/dedication 状态正确。旧 failed result/audit/acceptance 保留，新包只说明可恢复性，不回写旧成功标志。

如果硬中断导致最终非零 checkpoint 缺失，目前只有 t0 restored checkpoint，直接恢复到 plan3 **证据不足**。未来可另立“确定性重建候选状态”的开发验证：在冻结物理源下从原 checkpoint 按已保存 committed plans 执行，不调用模型/优化器/参考策略，逐事件比对整个保存前缀及各观察。验证通过得到的是带明确重建来源的新候选快照，不能冒称原时刻已经保存的快照。此路径本轮未运行；其运行/验证成本须单独记账，未通过前不能继续真实模型调用。

## 4. 在途请求与崩溃边界

| 停止位置 | 后续准备器应做什么 |
| --- | --- |
| progress 已写 model_attempt_pending，但没有 reserve/attempt claim | 证明请求从未开始后记录显式未启动意图；不能仅按 next_model_index 扣/跳一次。采用链级 attempt 序号并保留这种空隙的证据，不能假造 call_id |
| 有 reserve、尚无 authoritative finish | 保持 pending 阻挡；核对原请求进程和结果，不自动重复调用、不凭超时猜 usage。任何 unknown 仍为 unknown，豁免准入不等于可伪造已结束 |
| 原 model result 已成功，尚无 accepted journal | 独立核对 request fingerprint、reserve/finish、完整响应、schema/page/累计选择；若唯一可解释，可在**新段恢复证明**中登记已存在原输出的接受，不再调用模型，不修改旧缺失日志 |
| decision 说 accepted，但 patch/accepted journal 只写了一部分 | 从原模型输出逐字节/逻辑 hash 对照，证明唯一事务结果；缺少原响应或身份冲突即停止。不能用工具生成新任务填缺 |
| accepted journal 已持久化，progress 仍旧 | 以已核验 journal/patch/原输出推进派生游标，记录对账来源；不按旧 progress 重打该页 |
| 全部页接受，raw/committed 文件已写，trace 尚无 commit | 先证明末页 `commit=true` 和确定性 decoder/crop 结果；若失败原因是执行约束不满足，不能自动再提交或修复，应保留失败并走新的模型修订协议 |
| trace 已有 commit，commit journal/progress 落后 | 从原页来源核验该唯一 commit；新段引用已有提交，不能再次 env.commit_plan。无法确定已执行范围时停下，不重复派发 |
| 物理执行中途无一致快照 | 不从页游标猜状态；需要完整终止快照或上述单独确定性重建验证 |

后续新版本应在每个 `pages_ready` / 物理停止边界保存一个引用式物理状态包；分页期间物理状态不变，20 页无需重复保存相同巨型快照。调用、接受、提交各阶段使用只增事务 ID，先写意图、持久化原始证据、再原子发布游标。当前正在运行的版本不加钩子、不修改其源快照。

## 5. 跨计划的模型→任务→派发归属

用链级 `(root_run, original_registration, segment, plan_index, page_index, revision, model_index, call_id)` 标识选择证据。任务来源同时保留原 patch 中的位置、`operation_id/lot_id/step/visit`、模型明确的 machine/sequence/start 与 hold 条件；数字相同的局部 task ID 不跨 plan_version 混用。

每个计划保留全部 `source_page_call_ids`，末页 call ID 只证明显式提交，不能把前19页的选择归为最后一次模型输出。生成 raw plan 时仅允许冻结 decoder 对模型明确的 machine/sequence 做既有表示转换；crop 必须与原观察窗口、scope 和冻结源一致。每个被执行 task 都应回溯到对应原页；跨段只引用祖先证据，不重新标记为新模型选择。

旧 committed plans、当前 pending、executed_tasks、freeze 和机器绑定全部由验证后的非零物理状态继承。新计划未提交前，已有计划不是重新执行一遍；新分页的未提交 staged choices 也不能提前执行。当前 problem003 的 frozen_tasks 为空只是本次观察事实，不能据此删掉通用冻结继承检查。

新审计应分别计：祖先提交数、新段提交数、全链提交数；祖先 accepted 引用数、新响应数、失败/修订数。完整重放包含整条初始物理前史，新段报告不把重复引用的 bytes/events/model tokens 再算作新工作；实际复制出的存储字节仍应计入磁盘预算。

## 6. 累计资源与新 development 的边界

同登记恢复仍使用原 registration 的 B/1701/3600秒、wall7200秒、1GiB、solver0。generic config 中 `solver_budget_seconds=60` 不能覆盖 B 实际注册 solver0。请求次数/token上限为 null，但尝试/已报告用量/unknown/失败都继续留账，不能清零。

链级模型消耗按原根与所有祖先 segment 的 reserve/finish **call_id 去重**累加；runner wall 为原 parent result 加所有已关闭段的 `segment_final_wall_seconds`（包含独立审计与acceptance开销），不能用较早 result.wall 代替 finalization。磁盘预算按约定的全部不可变证据 inventory，加上新段实际写入和临时/验证开销口径；不能因为字节被引用过就免计真实复制的副本。

新段可用时长应为 `min(原7200 - 全链runner wall - 本段已耗wall, 原7200 - 全链model active)`；每次调用再取 `min(180, remaining)`。闭合前 pending、未关闭祖先、缺失 finalization 或不可信 wall 不能被当作0。当前研究 waiver 不应被解释为自动解除本 run 的7200秒或1GiB登记。

如果余额不足或原验收已因超限失败，未来如获准扩大研究，应新建有明确上限的 development 注册，注明 `lineage_parent`、继承物理状态/接受页、祖先已耗成本和新阶段成本。它属于新的追加实验；不能回写旧 registration/result/acceptance，也不能把新预算下达到1h称作旧预算实验成功。同一原始冷态对照若需要公平比较，必须另行预登记 A/B/C 资源与来源口径，不通过续作名称规避。

## 7. 实施边界与验收（本轮仅设计）

建议下一轮拆成独立准备器、后续状态执行器、独立链审计及 budget 链映射四块；先用小型 mock 数据验证 crash matrix、旧页零重调、提交零重复、跨plan typed identity、冻结继承、revision不清零、pending拒绝、已存在目录拒绝、累计超限拒绝，再考虑真实证据的只读准备。旧冷态 recovery v1 与历史审计保持可运行；新包/协议另起版本，不能降低旧失败规则。

源码审查版本：`controller_resume.py`=`cfbaf98f85b97bb796f279552cbb6eb038a0615b7d5178354b23a81be901ad75`；`controller_recovery.py`=`7b97687c7df92468c89f67ce298cb80601e8f362c121aeca19a2b48cf4a837f1`；`controller_resume_audit.py`=`76e3c6e57c00b8bb574767a0ae859962c2bdfde6a935725c14682058f95b7eee`；`budget.py`=`276758bf311483795e317dec0a24389fd246a3e39727ab7065cb1ee79e9aac33`；`environment.py`=`6d6b6b235ec38c5b26a279c2df574a43d88cdf5baa1096da0dc9bcc630ba122c`。这些是本次工作区读取身份，不替代真实运行自己的 source_snapshot。
