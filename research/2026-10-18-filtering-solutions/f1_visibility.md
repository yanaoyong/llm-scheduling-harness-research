主题一：工作可见范围与时间标签（审计待决问题 1、3、4；相关规则 A01、A02、A03、A07、A08、A09、S02、S04、F01）。
重点调研：
1. 实际 fab 派工/排程看多远：RTD 的 look-ahead dispatching、rolling horizon 排程常用的 WIP 前瞻步数或时间窗；"每 lot 固定步数"与"按时间窗"两种口径的利弊；G0 深度 2 与 P2 深度 3 不一致的原因（请在代码里查清楚）。
2. 未导出的后续工序（约 45 万步）与未投产 lot：业界是否让排程器预留这些工作；能否只给"计数/指针/按需展开"而不进上下文。
3. 预计到料时间的表示：exported_predecessor 用 release=now 占位的问题；文献/系统如何区分 actual vs estimated vs unknown 释放时间，给模型什么标签或字段最不易误读。
4. running_jobs 是否应补完工估计/当前 step/下一步；是否要增加 jobs/metadata 查询 kind；这些对 token 的影响。
结果写入：research/2026-10-18-filtering-solutions/f1_visibility.result.md
