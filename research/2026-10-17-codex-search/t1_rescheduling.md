主题一：动态排程的重排策略。
检索：周期重排(periodic) vs 事件驱动(event-driven) vs 混合(hybrid)重排、滚动时域(rolling horizon)排程；重排频率与计划稳定性/神经质(nervousness)的权衡、冻结区(frozen zone)；半导体晶圆厂实际如何做（实时派工 RTD、dispatching rules、APS 周期排程、班次排程），常见周期与前瞻长度；哪些事件应立即打断（设备故障、紧急批次）而哪些合并到下个周期；需求去抖/批处理；如何定义"缺口/未覆盖需求"避免重复触发。综述如 Vieira/Herrmann/Lin 的 rescheduling framework、Ouelhadj & Petrovic 综述、Mönch 等半导体排程综述，以及 SMT2020 相关研究。
