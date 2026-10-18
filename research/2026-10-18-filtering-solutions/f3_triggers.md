主题三：什么时候叫醒模型、"可避免空闲"怎么判定（审计待决问题 2、6、8；相关规则 L01–L09、M01、E01、E03、V04）。
重点调研：
1. 重排程触发：周期触发、事件触发（机器空闲、故障、到料）、混合触发的文献结论（rescheduling 综述、半导体 reactive scheduling）；触发偏保守（漏叫）与偏激进（多叫、成本高）的代价如何权衡。
2. 资格不确定（qualification_uncertain，G0 有 125 条 ready 被排除）、conditional、same_machine_as：fab 如何处理 dedication/qualification 不确定；"未知按可能"与"未知按不可能"的影响。
3. 空闲机与工作的匹配：现在是按机号贪心 + 字典序第一组 + 最小批量；最大二分匹配、批次形成算法的代价与收益；只用于统计/触发时需要多精确。是否要考虑加工槽容量（E03，G0 559 台满槽）和换型时长。
4. upcoming 的 H 窗口按预测到料筛选：是否应改为物理事实口径或多级窗口。
5. 队首无效阻塞整条队列（E01）、coverage 只列前 50（V04）是否需要改。
结果写入：research/2026-10-18-filtering-solutions/f3_triggers.result.md
