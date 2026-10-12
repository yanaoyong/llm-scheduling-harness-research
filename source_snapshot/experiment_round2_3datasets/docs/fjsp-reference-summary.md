# 静态参考值快照（仅离线评价）

来源、证据等级和限制见 `fjsp-source-audit.md`。32项属于“维护表报告最优，证明未独立复核”；新增开发mk10仅为报告下界189、BKS193，不能称最优。没有任何项被归类为本轮独立核实最优。

| instance | split | jobs × machines | operations | 平均可选机器数 | 证据类型 | ScheduleOpt LB | ScheduleOpt UB | SchedulingLab LB/UB |
|---|---|---|---:|---:|---|---:|---:|---|
| mk01 | development | 10 × 6 | 55 | 2.091 | reported_optimal_unverified | 40 | 40 | 40/40 |
| mk02 | development | 10 × 6 | 58 | 4.103 | reported_optimal_unverified | 26 | 26 | 24/26 |
| mk10 | development | 20 × 15 | 240 | 2.983 | bks_and_lower_bound | 189 | 193 | 175/197 |
| mk03 | formal | 15 × 8 | 150 | 3.007 | reported_optimal_unverified | 204 | 204 | 204/204 |
| mk05 | formal | 15 × 4 | 106 | 1.708 | reported_optimal_unverified | 172 | 172 | 168/172 |
| mk08 | formal | 20 × 10 | 225 | 1.431 | reported_optimal_unverified | 523 | 523 | 523/523 |
| mk04 | reserve | 15 × 8 | 90 | 1.911 | reported_optimal_unverified | 60 | 60 | 60/60 |
| mk06 | reserve | 10 × 10 | 150 | 3.267 | reported_optimal_unverified | 57 | 57 | 33/58 |
| mk09 | reserve | 20 × 10 | 240 | 2.525 | reported_optimal_unverified | 307 | 307 | 307/307 |
| la01_edata | development | 10 × 5 | 50 | 1.200 | reported_optimal_unverified | 609 | 609 | 609/609 |
| la01_rdata | development | 10 × 5 | 50 | 1.920 | reported_optimal_unverified | 570 | 570 | 570/571 |
| la01_vdata | development | 10 × 5 | 50 | 2.840 | reported_optimal_unverified | 570 | 570 | 570/570 |
| ft06_edata | development | 6 × 6 | 36 | 1.167 | reported_optimal_unverified | 55 | 55 | 55/55 |
| ft06_rdata | development | 6 × 6 | 36 | 2.056 | reported_optimal_unverified | 47 | 47 | 47/47 |
| ft06_vdata | development | 6 × 6 | 36 | 2.861 | reported_optimal_unverified | 47 | 47 | 47/47 |
| la02_edata | formal | 10 × 5 | 50 | 1.200 | reported_optimal_unverified | 655 | 655 | 655/655 |
| la02_rdata | formal | 10 × 5 | 50 | 1.880 | reported_optimal_unverified | 529 | 529 | 529/529 |
| la02_vdata | formal | 10 × 5 | 50 | 2.680 | reported_optimal_unverified | 529 | 529 | 529/529 |
| la06_edata | formal | 15 × 5 | 75 | 1.147 | reported_optimal_unverified | 833 | 833 | 833/833 |
| la06_rdata | formal | 15 × 5 | 75 | 1.880 | reported_optimal_unverified | 799 | 799 | 799/799 |
| la06_vdata | formal | 15 × 5 | 75 | 2.427 | reported_optimal_unverified | 799 | 799 | 799/799 |
| la11_edata | formal | 20 × 5 | 100 | 1.130 | reported_optimal_unverified | 1103 | 1103 | 1103/1103 |
| la11_rdata | formal | 20 × 5 | 100 | 2.030 | reported_optimal_unverified | 1071 | 1071 | 1071/1071 |
| la11_vdata | formal | 20 × 5 | 100 | 2.530 | reported_optimal_unverified | 1071 | 1071 | 1071/1071 |
| la03_edata | reserve | 10 × 5 | 50 | 1.180 | reported_optimal_unverified | 550 | 550 | 550/550 |
| la03_rdata | reserve | 10 × 5 | 50 | 1.980 | reported_optimal_unverified | 477 | 477 | 477/478 |
| la03_vdata | reserve | 10 × 5 | 50 | 2.560 | reported_optimal_unverified | 477 | 477 | 477/477 |
| la07_edata | reserve | 15 × 5 | 75 | 1.147 | reported_optimal_unverified | 762 | 762 | 762/762 |
| la07_rdata | reserve | 15 × 5 | 75 | 1.960 | reported_optimal_unverified | 749 | 749 | 749/750 |
| la07_vdata | reserve | 15 × 5 | 75 | 2.427 | reported_optimal_unverified | 749 | 749 | 749/749 |
| la12_edata | reserve | 20 × 5 | 100 | 1.140 | reported_optimal_unverified | 960 | 960 | 960/960 |
| la12_rdata | reserve | 20 × 5 | 100 | 1.990 | reported_optimal_unverified | 936 | 936 | 936/936 |
| la12_vdata | reserve | 20 × 5 | 100 | 2.480 | reported_optimal_unverified | 936 | 936 | 936/936 |
