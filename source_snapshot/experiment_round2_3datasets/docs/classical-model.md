# 经典基线：FJSP CP-SAT

基于 Google OR-Tools v9.15 官方 `examples/python/flexible_job_shop_sat.py` 中的标准可选区间模型，独立重实现输入/输出适配，并非将原脚本直接用于原题。参考源快照 `docs/ortools-reference-model.py`（保留 Apache 2.0 头），SHA256 `ed9484f61c0d8064204b3aad32958a0e4e6eaeb377abe58a3b85f8681034c44f`。

每道工序必须恰选一台合资格机；各选项有固定机器相关工时、共用起点，选择生效时链接终点。所有工序有工艺先后，同机可选区间 NoOverlap，目标 max(各作业终点)。上界为每道工序最慢合资格工时之和，足以容纳任何串行可行方案；未输入参考答案。静态输入不增加维护、换型或组批。

A/C 使用同一个 `src/fjsp/solver.py:solve`。开发默认 30 秒、单 worker、AUTOMATIC_SEARCH，种子 11。开发测量后冻结最终预算。C 可选择同一模型的合法搜索模式、种子、随机化及累计限额内求解时间；固定两段参数组合另作辅助对照。

可行解返回完整排程、求解界、状态、解改进轨迹及 response_stats。OPTIMAL 与 FEASIBLE 分开；有限时可行解不是证明最优。运行后独立 validator 重算 makespan。模型采用未抢占、时间非负整数、全部作业在 0 时刻可用的经典 FJSP 语义。

参考：[官方模型](https://github.com/google/or-tools/blob/v9.15/examples/python/flexible_job_shop_sat.py)，[Google 约束排程说明](https://developers.google.com/optimization/scheduling/job_shop)。官方软件版本和本机依赖见 requirements.lock。此处预算小于公开 FJSPLib 的 10 分钟对照，不将本地结果宣称为同资源复现其榜单。
