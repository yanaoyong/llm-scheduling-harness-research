# Phase L 紧凑快照验证（2026-10-18）

范围：只改变快照表示，删除重复快照工具，限制工具回执，并补齐整次请求预算闸门。
没有修改提交任务 schema、派工规则、封存输入或生产字段；没有模型/网络调用。

G0 context:30872dadac0f4aaf8e3799de，t=1649.8155803370928；tiktoken 0.14.0 / o200k_base。
旧列是 Phase I/J 的原 raw JSON（原规则和四工具），Phase L 列是移除位置元数据前的紧凑格式，Phase L2 列是当前紧凑格式（三工具和格式说明）。
子部分按独立字符串计 token，边界 token 不保证简单相加；完整 prefix/current/total 按实际 payload 计。

| 部分 | 原 JSON tokens | Phase L tokens | Phase L2 tokens |
|---|---:|---:|---:|
| routes | 520,999 | 88,116 | 88,116 |
| static_machines | 42,396 | 3,374 | 2,667 |
| unreserved_ready | 95,549 | 26,377 | 22,280 |
| machine_state | 74,977 | 21,666 | 21,666 |
| running_jobs | 20,267 | 11,989 | 11,989 |
| prefix | 563,837 | 92,275 | 91,567 |
| current | 192,522 | 61,393 | 57,296 |
| total | 756,359 | 153,668 | 148,863 |

静态/动态完整对象按非浮点精确、float 相对误差 1e-9、全部类型保持进行比较。
26 项计划通过 23 pending + 3 traced running 计入；907 jobs、1011 ready rows、913 machines 均保留。
release_time 显式写出；移除全部位置元数据，就绪行按 operation_id、动态机器按 machine、静态机器按 id 排序。
完整且已排序的 eligible 族列表使用 [family,name]；其他列表使用 [set,id] 并保留原序。
Phase L2 比 Phase L 再减少 4,805 tokens（3.13%）。显式值、浮点类型和继承元数据使当前大小
高于探索性默认省略编码；没有按预期数字删字段或调参。220000 历史 cap 下快照本身已可容纳，
仍不表示整次 Codex 请求满足该预算：系统/工具开销和输出/推理预留须另行实测登记。

复现：`scripts/measure_compact_snapshot.py --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" --output /tmp/compact-snapshot-tokens.json`。
此脚本还提供相同新规则/三工具下 raw JSON 的公平表示对照；因此其 old prefix/total 比历史旧值略大。
最终测试摘要、运行时间、封存/公开比较与 diff stat 记录在 `/tmp/v6orch/PHASE_L_REPORT.md`；本次最终复验见 `/tmp/v6orch/PHASE_L2_REPORT.md`。

F6 的 Codex 请求开销与紧凑表理解准确率仍待 Mac 证据。synthetic 的 overhead/reserve=0
只是显式测试参数，不是生产建议。CQT/Q-time 仍未实现；没有开始 E1/P2 模型轨迹。
