# 静态实现只读审查（正式冻结前）

审查范围：`src/fjsp/solver.py`、`src/agents/static.py`、静态来源/参考分类，并补读调用层的预算边界。审查者未参与 solver/Agent 的实现；来源/validator 是本角色实现，因此其文件一致性部分属于自查，不能冒称第三方独立审查。未改共享实现，未调用评测模型，未运行任何正式实例。

结论：在已锁定 Brandimarte/Hurink 的正整数、零 release、无附加约束语义下，没有发现 A/C 的模型遗漏或 B 工具代做核心决定。两个边界问题已由实现角色修正并通过末节所记离线复测；保留原发现、指标口径和辅助对照的预定建议。四个手算小例均通过。

## 具体发现

### P2 / 已关闭：C 的单次求解时间白名单与后端不一致

`src/agents/static.py` 的 `_check_c`（审查时第197行）仅限制 `time_limit <= remaining_seconds`，总预算配置允许到600；`src/fjsp/solver.py`（第21行）却限制单次最多300。离线实测：剩余600时，C的400秒动作被检查器接受，随后后端参数检查立即抛 `ValueError: time_limit must be in (0,300]`，未真正求解。当前30秒协议不会触发，但扩大总预算后合法外观动作会消耗模型调用及预算保留项并以运行错误结束。

建议：公开的单次可选上限固定为 `min(300, remaining_solver_seconds)`，写入 prompt 的剩余额度并在 `_check_c` 拒绝超限；不要进入 ledger.reserve_solver 后才发现静态参数无效。重现证据在 `artifacts/review_static/result.json.c_boundary_mismatch`。

### P2 / 迟到输出成功已关闭，终止开销边界保留：Agent wall_seconds 不是端到端的严格截止线

`src/agents/static.py` `_invoke`（审查时第115–125行）仅在调用前算剩余时间，没有在返回后重查；B 完整输出和 C 的 finish 会直接标 success。`src/agents/model_transport.py`（第187–201行）的版本探测最多10秒，发生在传给模型的 `communicate(timeout)` 计时之前，另有文件准备/结果解析开销。最后一次模型调用即使在自己的 communicate 超时内完成，也可能越过 Agent deadline 而仍成功。

建议：把同一个绝对 deadline 传入 transport，用剩余时间覆盖版本探测与进程运行；最少也应在 `_invoke` 返回和最终接受 finish 前重查，并保留迟到输出但标超时。清理进程的有限宽限时间单列。当前审查仅确认代码路径存在该边界，没有人为制造真实通道超时，也没有花模型预算。

### 统计口径：首个输出和修订次数应分层报告

B 的 `first_output_valid` 是第一条完整 model order 解码后有效；C 是第一条 solve 动作产生的首个 solver candidate 有效，即便最终没有显式 finish，也可能为 true。现有 `first_action_valid` 和 `first_candidate_valid` 能表达这一差异，报告应直接使用清晰列名，避免把 C 的求解器首个证据等同于模型首条完整排程。

B `revisions` 计成功前发生的无效列表轮次，C 只对无效动作递增；C 从一个合法参数方案改到另一个合法方案不会计为 revision。应另报 `solver_calls`、有效参数变更次数、无效动作纠正次数；不要合并成一个无定义的“修订”平均数。

## A/C 约束核对

| 原问题要求 | 实现与审查理由 |
|---|---|
| 每工序选恰好一台合格机器 | 仅为 alternatives 创建 presence bool 与可选 interval，`add_exactly_one` 恰好选一；无外部参考答案参与 |
| 机器相关固定工时、不抢占 | 可选 interval 的固定长度为对应 alternative.duration；激活时绑定同一工序 end=start+duration；一个连续 interval |
| 作业工艺顺序 | 相邻工序加 `end(prev) <= start(next)`；完整作业是链，因此传递覆盖所有前后工序 |
| 设备单容量 | 每台机器对全部候选 interval 加 `NoOverlap`，只有被选 interval 生效；不同机器允许并行 |
| 非负整数时间 | start/end 整数变量下界0；来源duration为正整数；不引入额外日期/维护等条件 |
| makespan | 对每个作业末工序end取max；由于作业链，等于所有工序结束的最大值 |

`horizon=sum(max(duration alternatives) for every operation)` 不会切掉此类实例的所有最优解：按作业逐一串行排所有工序总能构造长度不超过该值的可行解，因此存在 makespan 不超过 horizon 的最优解。整数约束也符合原输入；给定选机与机器次序后的最早开始时间由整数路径长度决定。

A/C 调用同一个 solve，无修改资格集合、时长、precedence、目标或注入已知上界。A 单线程30秒、固定参数是一项合理基线，未发现故意弱化。当前模型限制不支持新的 release、setup、maintenance 或任意DAG；若未来输入增加这些语义，本结论不能直接沿用。

## B 权限核对

`observed_problem` 用白名单重建机器与工序，丢弃 instance_id、family、source、URL、最优/BKS等额外元数据。`decode_order` 要求每个 id 恰好一次、按本作业工艺序出现、机器合格；错误会拒绝，不补工序、排序、替机器或求解。

时间工具仅按模型给定列表递推 `start=max(job_ready,machine_ready)` 和指定机器时长，随后更新两个ready。实测保留了完整 order 与 machine 字段。B 没有导入或调用 solver，run_b 只用独立校验器检查其结果。它表达的是选定机器顺序下的最早开始排程，不表达任意主动闲置，已在 prompt 明示。该范围适用于当前静态目标；不得把这个接口描述成不受限制的通用排程语言。

C 则由模型选参数、求解预算及最终候选。候选不自动选择，缺 finish 失败；如果真实日志只有一次solve+finish，应如实标作“一次参数选择和求解”，不能描述为迭代优化。

## 来源与参考分类一致性

现行33实例全部 cross-check，139源文件校验。`docs/fjsp-reference-values.json` 里32项为 reported_optimal_unverified；新增开发mk10为BKS193/LB189、reported_optimum=null。未独立复核证书，`independently_verified_optimum` 全为null。输入JSON没有参考值/检索URL；来源和离线参考在独立文档。

mk06声明机器数差异、ft06/mt06别名已记录。Hurink e/r/v资格集合非嵌套，因此只能对同一基础实例的柔性结构变化作对照，不能宣称严格嵌套加边的因果实验。正式与预留集合未因结果修改；mk10仅按240工序规模加入开发集，原32集快照保留。

此处最优/BKS证据等级是来源维护表的状态，不会因四个手算例证明成功而提升。Brandimarte原文全文不可访问的限制仍保留。

## 正式前固定的辅助对照建议

辅助对照单独统计，不增设第四个主要方案，也不以正式 C 结果反向选择固定参数。

1. 保留 A：单次30秒、single worker、AUTOMATIC_SEARCH、randomize_search=false，repeat固定seed序列。
2. 增加预定固定组合：每次总预算30秒，固定执行两次15秒，使用预先写定的seed对（例如r1=(11,12)、r2=(22,23)、r3=(33,34)），同样AUTOMATIC_SEARCH与单线程；独立检查后取makespan最小有效候选。记录每次solve及累计实际耗时，平局取第一个。这样直接检验 C 的收益能否仅由固定多启动解释。
3. 若开发日志显示 C 稳定使用某一特定 branch preset，可在正式前另锁一个固定配置作为有针对性的辅助对照，明确开发证据与选择规则；不要看正式C参数后再将其包装成预定对照。若仅保留一个辅助对照，优先固定多启动，减少额外求解成本。
4. A/C/辅助使用相同每次总求解上限、线程数和串行资源安排；模型端到端耗时额外报告，不从C成本扣除。分别比较C对A、C对固定组合；C若没有优势亦为有效结论。

此建议尚未构成正式冻结配置，由主 Agent 在批量前选择并提交，不代表已经运行辅助方案。

## 实际执行证据与成本

执行命令（实验根目录）：

```sh
.venv/bin/python artifacts/review_static/check_static.py
```

原始问题、手算证明、solver完整结果、独立validator结果和审查文件SHA256：`artifacts/review_static/result.json`。脚本检测结果存在即停止，避免误复跑或覆盖证据；回放可读取该结果重跑validator，不需要重新求解。

| 手算例 | 证明目标 | 求解状态 | 独立重算 |
|---|---:|---|---:|
| precedence | 5 | OPTIMAL | 5 |
| capacity | 7 | OPTIMAL | 7 |
| machine_choice | 7 | OPTIMAL | 7 |
| joint_chain_capacity | 7 | OPTIMAL | 7 |

账本 grant=`static-independent-review-01`，模型调用0，实际solver调用4，累计预留0.8秒（每次0.2秒），累计solver时间0.002463秒，累计进程CPU 0.004193秒；均低于主 Agent 授权2CPU秒。参数400秒的边界测试在参数校验阶段被拒绝，未执行solver，不另记求解。这个审计角色成本独立于正式矩阵，禁止把手算例计入实验成功率。

## 修复复测

实现角色在 `_check_c` 将单次上限限制为 `min(300, remaining_seconds)`，并在 `_invoke` 返回后重新检查绝对deadline、保留迟到response后抛出TimeoutError。2026-10-09，本角色执行 `.venv/bin/python artifacts/review_static/static_fix_acceptance.py`，结果保存 `artifacts/review_static/static_fix_acceptance_result.json`：400秒动作在调用前被拒，300秒边界动作通过；模拟transport在deadline之后返回时被拒且保留响应。3/3离线检查通过，模型0、solver0。此处模拟返回仅用于测试运行器边界，绝不计作真实Agent实验。

复测时 `src/agents/static.py` SHA256：`8f797bffc43f57b691af29af94564755ddf7a2b3c9ae17a7de7b66cd3ccdb85d`。运输层版本探测及进程清理仍可能使实际端到端耗时超过名义deadline，但迟到模型输出不再算成功；报告实际耗时和timeout，不应把wall_seconds说成进程必须在同一毫秒退出的保证。模型返回后本地文件写入/解码/独立验证仍有少量开销，本轮未做系统负载下的实时终止保证。
