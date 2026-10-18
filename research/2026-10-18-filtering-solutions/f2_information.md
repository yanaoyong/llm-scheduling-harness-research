主题二：给模型的信息字段与知情范围（审计待决问题 1 中的字段投影部分、5、7；相关规则 S01、S03、S05、A04、A11、E04、C01、F02）。
重点调研：
1. 半导体派工规则（FIFO、EDD、CR、ATC/ATCS、SPT、setup-aware、batching 规则等）实际用到哪些字段：交期、优先级、加工时长、剩余工时、setup、抽检率等；LLM 调度论文里给模型哪些字段、缺字段时效果怎样。
2. ready 区现在缺 due/priority/durations 等 22 个字段：逐个评估补回的价值与 token 成本（用审计实测 ready 1,011 行估算），以及"补到快照里"vs"只能查询"的取舍。
3. 全局 setup 转换表、min_runs、未来保养/投放信息：业界排程器是否使用；给模型的最省方式（静态前缀、可查询 kind、按需）。
4. single_action（只能看快照）与 mcp_session（可分页查询）信息不对等：怎样设计实验才能公平比较，或者是否应让两者看到相同信息。
5. 查询接口缺 range/OR（F02）是否需要补。
结果写入：research/2026-10-18-filtering-solutions/f2_information.result.md
