# 最终保存证据验收门槛

实现：[`scripts/final_acceptance.py`](__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets/scripts/final_acceptance.py)。只依赖Python标准库，只读取已有记录、审计、报告与明确签署；不import运行器、模型通道、求解器、模拟器或回放模块，不执行Git子进程，也不生成图表。它是最终一致性门槛，**不冒充一次新的独立领域回放**。主 Agent 必须先真正执行全部回放与其余人工/独立检查。

默认最终产物是 `artifacts/final/acceptance.json`。`acceptance_ready=true`只在下列自动条件与所有签署都通过时出现；脚本不更新goal状态。缺文件、缺字段、未签署、哈希改变、重复或漏格点均拒绝。`--check-only`不写最终文件；正常写入采用独占创建，已有文件不会被覆盖。

## 自动核对的范围

- 原始四phase必须与固定矩阵一致：`acceptance_static_v1` 108、`acceptance_smt_v1` 27、`auxiliary_static_v1` 36、`auxiliary_smt_v1` 9。核心135与辅助45分别保留；静态仍是mk03/05/08及la02/06/11全部e/r/v，动态仍是801/802/803，各重复1/2/3，不能用补充结果替换原矩阵。
- 原180个`result.json`逐文件绑定SHA256；检查原身份、终态、freeze副本、code commit/tag/protocol、各重复的有效配置哈希。恢复前后的原结果字节必须与索引相符；若存在恢复，其冻结manifest中的180原结果哈希必须与索引完全相同。
- 每phase必须有**分别保存**的完整离线replay审计和report evidence audit，二者都覆盖精确原矩阵、晚于运行完成，逐条`audit_pass`和`provenance_complete`为true，错误/缺失/额外/重复/不完整列表为空。静态原失败允许`valid=false`，但其失败证据必须通过审计，原`acceptance_ready=false`不得改写为true。
- SMT核心27及辅助9均须成功完成28800秒，领域审计通过；adapter-v2、受控[9,790]、预热0和范围外固定策略与冻结边界一致。CSV主要业务指标与审计重算一致，provenance表完整。
- 静态CSV、summary及每实例每臂的3重复聚合须仍来自原记录；失败makespan/gap为null，不能填入恢复值。参考哈希必须是原冻结参考表。辅助静态36份最终排程亦须合法；若其中有失败，保留失败并使最终门槛未通过，不能删掉它来凑足通过数。
- 核心静态的最终108逻辑格点：无恢复时要求原排程全合法；有恢复时只接受 `scripts/audit_static_recovery.py` **已保存**的完整认证，核对其冻结、源脚本、原180哈希、资格与恢复结果清单、成功恢复验证、原成功数、108交付来源和makespan。原失败不能被改为成功；补充记录另计，不作为第181条“原矩阵记录”。本门槛不会调用恢复审计程序，也不会启动恢复。

当前报告和回放输出并非每条都带result字节哈希。因此本脚本不能仅凭一个`audit_pass=true`文件证明它确实是对当前原始日志执行的。下面的索引冻结已保存文件的字节版本，签署者须确认这些审计针对这一批结果及未变动的完整原始证据。索引准备命令本身没有认证效力。

## 使用顺序与防止循环哈希

以下命令的工作目录均为 `__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets`，**只能在正式运行结束后执行**；本脚本开发时未执行这些命令。

1. 完成180个原始格点，保留失败；主 Agent真实运行四phase离线回放，推荐使用`--label final`，并完成对应报告。静态保存`replay_final.json`、`report_evidence_audit.json`、`summary.json`、`results.csv`；SMT文件以`smt_`前缀对应，另有`smt_provenance.json`。已有绑定文件需保持不变；若必须重生成，应使用明确的新文件版本并重新建立后续绑定，不能悄悄使恢复manifest引用失效。
2. 若执行过有界恢复，完成原始失败证据保留、恢复冻结、原请求关联和真正的`audit_static_recovery.py`认证。保留原报告；恢复交付与成本单独呈现。
3. 完成最终中文报告、固定选择规则的图表和图像QA。完成历史输入保护比对、原始日志/数据清单与恢复方法检查、Git冻结核对、README关键命令验证和最终预算审计。将实际检查日志/报告保存在本实验内，不只留下“已检查”一句话。
4. 原始证据inventory与QA记录先保存；其扫描应排除随后才会产生的`evidence-index.json`、`review-signoffs.json`、`acceptance.json`及各自临时文件，避免互相自引用。这些最终绑定文件由下一层哈希关联，不塞回原inventory。
5. 准备索引，仅收集已存在文件和180个原result哈希；此命令不回放、不作图、不认证：

```sh
.venv/bin/python scripts/final_acceptance.py --prepare-index > artifacts/final/evidence-index.json
```

若保存回放时使用其他label，补充`--replay-label LABEL`。若有恢复，必须同时添加实际路径，例如：

```sh
.venv/bin/python scripts/final_acceptance.py --prepare-index --recovery-freeze progress/freezes/static-channel-recovery-v1.json --recovery-audit artifacts/static_recovery/audit.json > artifacts/final/evidence-index.json
```

恢复freeze使用主 Agent计划的`progress/freezes/static-channel-recovery-v1.json`，示例不表示它已经存在、冻结或通过；如最终路径不同，传实际路径。放在`progress/freezes/`可避免旧报告程序把自定义恢复schema当成普通矩阵冻结。准备命令要求文件齐全；若退出码2，stdout是缺证据说明，不能把它当作有效索引。应保留诊断、补齐实际证据后重新准备。索引结构为`final-evidence-1`，含`preparation_is_certification:false`、`prepared_at`、四phase的freeze/replay/report audit/summary/CSV/source哈希引用、180项`original_results_sha256`，以及可选recovery的freeze/manifest/audit/source/result哈希。每个文件引用均为`{"path":"实验根目录相对路径","sha256":"64位摘要"}`；不接受越界路径。

6. 创建待签署模板（**八项默认全部pending**）：

```sh
.venv/bin/python scripts/final_acceptance.py --prepare-signoffs > artifacts/final/review-signoffs.json
```

模板结构为`final-signoffs-1`，其`evidence_index_sha256`绑定上一步索引字节。主 Agent或实际检查者应先核实对应任务确实完成，然后明确填写每项`status:passed`、真实`reviewer`、带时区且晚于索引准备时间的`reviewed_at`、具体`statement`和至少一份实际证据的`path/sha256`。不能用脚本批量将pending改成passed来代替检查。保存旧检查证据后，在当前索引上重新核对并签署，既可复用此前实际完成的工作，也确保这次签署对应最终版本。

|签署键|必须实际确认的内容及证据示例|
|---|---|
|`full_offline_replay`|完整180原记录及全部恢复已逐一真实回放；保存命令日志与审计清单，确认保存审计对应本索引所列result版本|
|`raw_evidence_inventory`|原始模型事件、提示词、动作、solver日志、完整SMT trace、源码快照等未在审计后改变；保存全量hash核验结果及数据/日志获取恢复说明。门槛脚本不会再次遍历这些大文件|
|`freeze_git_history`|各freeze的commit/tag确实存在且未重指，原冻结文件与相应源码/配置/数据绑定完整；保存实际Git核对日志。原失败记录和恢复版本均在历史中可追踪|
|`historical_inputs_unchanged`|inputs、m0.5_research、summary.md、relocation.json、experiment_round1等既有内容未被本轮改写；保存前后比对证据，不能假设因路径分开就自然通过|
|`report_integrity`|最终中文报告、分析表及四phase报告数值与原始/恢复分层证据一致；含费用未知、失败分母、条件质量均值和局部控制边界。证据至少包括实际最终报告及核对记录|
|`visual_qa`|实际查看全部交付图，核对标签、坐标、数量、清晰度和失败显示；保存QA记录及图表manifest，不能仅因PNG文件存在就签署|
|`readme_reproduction`|实际执行README关键命令并保存结果；无须重新花钱复跑整个模型矩阵，可区分离线回放和新鲜运行流程检查，不虚构复现完成|
|`budget_integrity`|统一账本、未知token、失败和恢复累计成本、调用/solver/活动时间上限、准入与停止规则均真实核对；无pending请求或隐藏额度重置，保存账本及最终预算检查结果|

签署证据应指向实际检查记录，不要指向本签署文件或尚未生成的acceptance文件。签署文件哈希由最终acceptance记录绑定，索引不包含签署哈希，故无循环。最终交付Git提交可以在验收后包含这几份文件；不要把该未来提交号提前写进其自身内容。

7. 先只读预检，查看全部未完成项：

```sh
.venv/bin/python scripts/final_acceptance.py --check-only
```

只有返回码0、`acceptance_ready:true`且主 Agent确认其余任务条件满足，才生成最终证据：

```sh
.venv/bin/python scripts/final_acceptance.py
```

结果保存到`artifacts/final/acceptance.json`，包括四phase原数量、核心/辅助分母、108逻辑交付、所有未完成项、索引/签署/检查器哈希，以及实际检查过的保存文件哈希。返回码2表示未通过，不代表任务完成；若已经生成过同名产物，脚本拒绝覆盖。需要保留后续版本时使用明确的新`--output artifacts/final/acceptance-VERSION.json`，保留旧证据。

## 已验证范围和限制

开发期间仅做AST解析、标准库导入检查和7项小型内存fixture：四矩阵数量、重复ID拒绝、缺全部证据拒绝、合法失败证据可通过其证据层、把该失败的acceptance标记改为true会被拒、bool不冒充数字、签署模板全pending。另做最终AST复查，并只读已有development的两份summary、两份报告审计和两个CSV表头，确认静态`records/successes/failures`、动态`records_including_missing/certified_successes/non_successes`及所有采用的字段实际存在，没有猜测字段名；没有硬编码应当存在的图片列表。以上显式计时Python检查累计约0.031 CPU秒；未读取正式result内容、未全量遍历、未跑测试套件/回放/仿真/图表，评测模型0、solver0；未写最终index、signoffs或acceptance。

该开发检查不等于已在真实180完整记录上集成通过，最终由主 Agent在规定时点实际执行。文件哈希与明确签署能约束版本关联，但不是对执行历史的密码学证明；签署真实性、完整Git/原始日志核验、图像可读性和报告文字含义仍由明确负责的检查者承担。门槛脚本只重算少量报告计数/均值和比较已重算的主要指标，不重新求解、不重演动态轨迹，也不自动宣布goal完成。

## 本轮最终实际执行记录

2026-10-09由主Agent完成全量回放、历史保护、图像QA、README复现、独立预算与冻结审查后，实际生成索引并逐项签署。未签署预检只报告8项签署缺失；明确签署后预检退出0，正式生成的[acceptance.json](../artifacts/final/acceptance.json)为passed、unfinished_items为空。原核心135/辅助45分母未改，静态逻辑108格点由107原成功+1单独恢复交付。具体证据和哈希见最终索引及签署，前文开发期fixture说明是历史开发记录。
