主题二：LLM/Agent 用于排程与运筹优化的已有工作（2023-2026）。
检索：LLM 直接做 job shop / FJSP / 动态排程的论文与基准；LLM + 求解器（LLM 生成模型/约束，交给 CP-SAT/MILP/ASP）；LLM 生成或演化派工规则/启发式（FunSearch、EoH、ReEvo、LLM-designed dispatching rules）而非每次决策都调用模型；LLM 在动态环境中调用频率/成本控制的方法；LLM 计划的校验-修复循环(validate-repair)；在制造/半导体场景的 Agent 实践。重点关注：如何降低模型调用次数同时保持质量，模型应放在决策回路的哪一层（每次派工 vs 周期规划 vs 规则设计）。
