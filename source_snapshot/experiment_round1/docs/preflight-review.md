# 正式评测前独立审查

审查时点：2026-10-08（正式运行尚未启动）。审查范围为
`src/runner.py`、`src/replay.py`、`src/report.py`、`src/model_transport.py`、
`configs/prompt_B.txt`、`configs/prompt_C.txt`、协议及 README。
本审查只读生产代码与已有记录，没有调用模型、求解正式实例或修改运行器。
下述是当时快照的发现；主 Agent 后续修复需另做复核，不应据本文假定仍未修复。

## 已确认的行为

- B 分支从真实模型响应读取 `actions`，直接传递给 `build_schedule`，随后独立
  校验。dispatch 不含排序搜索、机台选择、自动维护或求解器导入；非法决策
  返回失败与反馈，未发现隐式代排或回退。
- C 的 solver 只在真实 JSON `solve` 决策之后调用。模型选择时间、seed、preset；
  `finish` 必须引用已有可行候选，不会在模型尚未确认时自动接受默认解。
- B/C 共享同一 ModelConfig：`gpt-6-astra / medium`。固定最大 4 个模型请求；
  C 最多 2 次 solver，累计 requested limit 不超过 40 秒；A solver 上限 40 秒。
  单模型调用超时 240 秒；正式模型请求总上限 72、正式启动记录上限 27。
  代码检查的是 solver 申请秒数，进程启动/回收可能产生少量额外墙钟开销。
- 每条模型调用是新鲜上下文，只由固定 prompt、当前实例和本次运行反馈组成。
  模型原生工具事件被检测并使调用失败。检查的开发 prompt 没有其他运行路径。
- 完成的 run_id 复用前核验方案、实例、重复号、阶段、配置和输入指纹；未完成
  的 started 目录拒绝自动覆盖。正式入口检查 freeze，冻结文件拒绝重写。
- 单条 result 中未知货币费用、纯推理耗时使用 null。单条运行和按方案 token
  汇总在存在未知字段时保留 null，未将 token 乘单价当成实际账单。

## 冻结前需要修复

### R1：闭环判断缺少实验单元的唯一性和完整性

审查快照 `src/report.py` 第 10 行只判断总数 27、成功 27、每个方案 9 条。
`runner.py` 支持自定义 run_id，因而可以为同一 `(instance,arm,repetition)`
产生多条记录。现有判定不能阻止缺少正式实例、用重复单元补足计数却宣告闭环。

内存反例（没有生成或修改实验记录）：全部记录都用 instance02，对每个
方案、每个重复号复制三份，共 27 条；现有判断为 True，但只有 9 个唯一
实验单元，instance05 和 instance08 完全缺失。

建议：从冻结 split 与 repetitions 生成预期 27 个三元组；统计实际三元组
频次，明确报告 missing、duplicate、unexpected。只有完全相等且每格恰好一次
才允许最终闭环；重复尝试仍保留，不通过覆盖或丢弃来满足数量。

### R2：离线回放没有检查中断尝试和来源一致性

审查快照 `src/replay.py` 第 40–57 行只扫描 `*/result.json`，因此有
`started.json` 但没有 result 的真实中断尝试不会出现在失败分母或 issues 中。
同时其校验输入直接来自运行目录 `input.json`，未核对原 `.lp` 的 SHA、
规范化输入内容、运行配置 SHA 或正式 freeze 状态。

建议：回放列出全部 started 目录，未完成尝试作为 interrupted 明确呈现；
核验 run/input/config 身份和 hash，并将缓存输入与从固定源重新解析的输入
比较。正式回放同时核验 freeze；发现不一致时保留派生结果并非零退出。
另外建议比较 result 自报 objective 与重算目标，避免悄悄覆盖不一致值。

### R3：完整成本账本会把部分缺失的 token 当成零

审查快照 `src/replay.py` 第 94–103 行只根据 input_tokens 是否非空判断
reported_calls，再用 `usage.get(key) or 0` 累加 cached/output token。
若 input_tokens 已知而 output/cached 未知，会把未知当成 0，并可能标记
`usage_complete=true`。目前已观察成功调用均有这些字段，但实现违反“不可得
项明确未知”的约定，未来失败/不同 CLI 返回即可触发。

内存反例：`{input_tokens:120,cached_input_tokens:null,output_tokens:null}`
会得到 complete=true、cached/output=0。

建议：逐字段记录 known subtotal、missing count 和 complete 状态；任何记录
缺失该字段时，该字段完整总计为 null。进程未完成时 elapsed 也应说明只统计
可见部分，而不是声称完整墙钟总量。

## 应澄清或修正的次要项

- A 的 `first_valid_output_seconds` 在 solve 整体结束后才赋值，实际上是最终
  solver 返回/独立验收的时间，不是最早可行 witness 时间。已有 solver 记录
  含 `first_witness_seconds`；应单列两者或修正文档/字段名，避免混用。
- 全局 1100 秒检查发生在每轮模型调用前，没有把剩余墙钟传入当前模型/solver
  调用。当前有限次数仍提供有限总上限，但“单次运行≤1100秒”不是严格的
  截止期限实现；宜改成保留回收余量的剩余预算，或明确是轮次间停止阈值。
- 报告在尚无正式结果时也会写“本组正式运行没有最终失败”及“完整27行”。
  生成未完成阶段报告时应显示 missing/尚未完成，最终门禁修复后再判断措辞。
- README 已准确说明中断记录不覆盖、随机输出不承诺完全一致、未知账单不估算。
  最终正式状态、freeze 和报告链接应在交付前由主 Agent 按实际文件核验。

## 已有运行的独立证据

审查中重新调用纯 Python checker 检查以下已完成记录；均可行且目标与
原 result 一致：dev01_A、dev01_B、dev01_C、dev03_A、dev03_B。

- dev01_B、dev03_B：从最后真实 `decision_XX.json` 的 actions 再运行 dispatch，
  得到与保存 `schedule.json` 完全相同的对象。
- dev01_C：最后动作是显式 finish，其 candidate 所指原 solver schedule 与
  交付 schedule 完全相同。
- dev01 三方案 makespan 均 120；dev03_A=214。开发结果只用作接口与过程审查，
  不作为正式结论，也没有依此挑换正式实例。

本审查未发现 B 暗中使用 solver、mock 或固定启发式代排。R1–R3 属于验收和
审计边界问题，建议在正式 freeze 前完成修复并复核。

## 修复后复核

主 Agent 在正式启动前完成 R1–R3 的代码修复，本审查者重新读取并核对：

- 正式 run_id 强制对应唯一 `instance_arm_r编号`；回放验证完整笛卡尔积、
  重复与意外实验单元。上述重复 instance02 的内存反例现在被拒绝。
- 回放列出 `started` 无 result 的中断尝试并加入 issues；重新解析原 lp，
  比较规范化输入、来源 SHA、配置 SHA、started 身份，并验证正式 freeze。
  独立重查当时已完成的五条开发记录，这些哈希和输入检查全部一致。
- 成本账本逐字段记录 `unknown_by_field`，保留 `known_*` 小计。缺失字段
  完整总量为 null；上述 partial-usage 反例现在保留 cached/output=null。
- 首次输出时间明确为工具完整交付后、经过独立检查可供 Agent 使用的时间；
  另列 `solver_first_witness_seconds` 以表达 solver 内部首次 witness。
  在这两个含义分开说明后，该时间口径可接受。

复核结论：R1–R3 已关闭，未发现阻止正式运行的算法/校验/真实性问题。
正式冻结前还需同步两处操作说明：强制 canonical run_id 后，正式中断不能
按旧提示简单换 run_id 重跑；1100 秒目前是轮次间检查阈值，不能写成严格
墙钟截止。两点已通知主 Agent，未由本审查者修改运行器或协议。
