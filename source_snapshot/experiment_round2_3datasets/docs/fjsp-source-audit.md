# 静态 FJSP 来源与语义审计（2026-10-09）

本文件属于研究与离线评估材料，禁止向被评测 B/C 运行上下文提供。输入与参考值物理分开；输入文件只位于 `data/fjsp/instances/`，其 `source` 仅有格式名和原始 SHA256。

## 锁定来源

| 来源 | 锁定 commit | 仓库许可证 | 用途 |
|---|---|---|---|
| [SchedulingLab/fjsp-instances](https://github.com/SchedulingLab/fjsp-instances/tree/ac4c3402312bfbeafcf4472d78be567d4e6b46ab) | `ac4c3402312bfbeafcf4472d78be567d4e6b46ab` | MIT | 实际运行输入，零基文本与同仓 JSON 交叉核对 |
| [ScheduleOpt/benchmarks](https://github.com/ScheduleOpt/benchmarks/tree/f89e5b007c90a1c1a70fa48a28d657a72da05665/flexible-jobshop) | `f89e5b007c90a1c1a70fa48a28d657a72da05665` | CC-BY-SA-4.0 | 独立表示的选项、precedence 与旧文本核对；参考上下界维护表 |

139 个源文件的下载 UTC 时间、完整 URL、Git blob SHA1、内容 SHA256 与字节数保存在 `data/fjsp/source-lock.json`。下载文件位于被 Git 忽略的 `vendor/fjsp-instances/` 与 `vendor/scheduleopt/`；恢复程序固定 commit，不跟随 main。两个 API tree 清单的内容哈希另在 `docs/fjsp-evidence-lock.json`，恢复 URL 同时给出。许可证原件随下载保存，Git 内镜像见 `docs/fjsp-LICENSE-schedulinglab.txt` 和 `docs/fjsp-LICENSE-scheduleopt.txt`。这是仓库声明的许可证；没有把它延伸为对所有原论文权利链的独立法律确认。

SchedulingLab README 明示数据可能有误，要求回溯原论文，故本轮没有只依据它的 `instances.json`。ScheduleOpt 页面是维护中的档案，所选值依据上述 commit 的 JSON 快照，不依据将来网页状态。

## 原论文与约束依据

- Brandimarte, P. (1993), *Routing and scheduling in a flexible job shop by tabu search*, Annals of Operations Research 41(3), 157–183，[DOI 10.1007/BF02023073](https://doi.org/10.1007/BF02023073)。作者所在机构的[记录](https://iris.polito.it/handle/11583/1397590)核对题名、作者、年份与页码；该页无全文附件。出版方全文在本次 web 读取中不可用，因此没有宣称逐页复核 Brandimarte 原始表格或原始文件字节。
- Hurink, J., Jurisch, B., Thole, M. (1994), *Tabu search for the job-shop scheduling problem with multi-purpose machines*, OR Spectrum 15(4), 205–215，[DOI 10.1007/BF01719451](https://doi.org/10.1007/BF01719451)。[作者机构的原文 PDF](https://ris.utwente.nl/ws/files/6479568/ORS15.pdf)第 206 页定义资格集合、固定工艺顺序、不可中断加工及机器/作业单容量；第 212 页说明从经典 JSP 增加可选机器生成 e/r/v。Hurink 的工时不依赖所选机器，Brandimarte 则允许依赖机器。

本轮仅应用这些静态版本表达的硬约束：每个工序恰好一次，选择一台合格机器，按相应工时连续加工，工艺顺序，机器单容量，所有工序从非负时间开始。无运输、换型、维护、故障、release/due-date 新增约束，目标仅 makespan。各工序一旦选择机器，不能迁移或分段。时间为正整数工时及非负整数开始时间，区间为 `[start,end)`。

## 格式与逐项交叉核对

实际运行只解析 SchedulingLab 零基文本：首行恰好 job/machine 两个整数，每个非空行一个作业，接着是工序数及每道工序的替代数量与 machine/duration 成对数据。严格拒绝缺失/额外行、未消耗 token、机器越界、重复机器选项、零工时、负数和小数等；不自动猜测机器索引或另一方言。

ScheduleOpt 旧 `fjsp` 文本使用一基机器号，并可能含第三个平均柔性 header。其 README 的一处括号模板将 duration/machine 顺序写反，而相邻实例与 JSON 均是 machine/duration；本轮以原始文件和 JSON 全量一致性核验消除歧义。ScheduleOpt 新 JSON 用零基全局工序号及显式 precedence。本轮对 33 个实例核查了全部选项三元组、每条前后序边及其 job、每作业工序数，而非只比维数。

`data/fjsp/manifest.json` 逐项保存上述交叉核对结果。33 个实例工序与选项全部一致。有两项命名/声明差异明确保留：

1. Hurink `ft06` 在 SchedulingLab 为 `mt06`；其 e/r/v 三组的全部工序、机器选项、工时和链式前后序与 ScheduleOpt 的 `ft06` 一致。本轮标准 id 为 `ft06_{variant}`。
2. 预留 `mk06` 的 SchedulingLab txt/JSON 声明 10 台机器，而其元数据及 ScheduleOpt 旧 text 声明 15 台。双方所有选项都仅使用零基 0..9，工序与工时完全一致，额外 5 台无可执行工序。本轮保留实际输入的 10 台，并在 manifest 标记 declared count 不一致；不静默改头部。此差异不改变可行排程或最小 makespan，原因是没有任何工序能选额外机器。正式集不含 mk06。

## 预选数据划分

| split | Brandimarte | Hurink 基础实例（每个完整含 e/r/v） |
|---|---|---|
| development | mk01、mk02、mk10（后续规模探测） | la01、ft06 |
| formal | mk03、mk05、mk08 | la02、la06、la11 |
| reserve | mk04、mk06、mk09 | la03、la07、la12 |

划分按主 Agent 的预先选择建立，数据角色没有因求解表现调整。mk10 在任何正式运行前按输出规模加入开发集，变更依据与原32项快照见 `fjsp-selection-change.md`；正式/预留未改。来源 Agent 未运行求解器或评测模型。机器可选数只用于描述结构，正式结果不可用于调整该划分。

Hurink 所选 8 个基础实例的 e/r/v 保持每个工序的时长和工艺链，但资格集合不是嵌套关系：逐工序检查均发现 `edata ⊄ rdata` 且 `rdata ⊄ vdata`。平均选择数递增不代表在相同机器集上单调加边。因此可以比较同一基础实例的柔性结构变化，不得将差异解释成严格嵌套扩张的因果效应，也不得把 Brandimarte/Hurink 之间所有差异归因于柔性。

## 参考值分类

完整逐项数据在独立文件 `docs/fjsp-reference-values.json`；精简表见 `docs/fjsp-reference-summary.md`。

- `independently_verified_optimum`：本轮有独立可行排程和匹配的可核查下界/证明。当前全部为 null。
- `reported_optimum`：维护表声称上下界相等，但本轮没有复核证书。所选 33 个中 32 个属于 `reported_optimal_unverified`，新增开发 mk10 为 `bks_and_lower_bound`（LB=189，BKS=193）；绝不写成已独立证实最优。
- `best_known_feasible_value_reported`：维护表的上界/BKS 声明；独立证书未检查，以 reported 标明。
- `lower_bound_reported`：维护表报告的下界，与上界分字段保存。
- unknown：缺少对应证据时为 null，不用 0 代替。

主要差异包括旧 SchedulingLab 对 mk02 报 [24,26]、mk05 报 [168,172]、mk06 报 [33,58]，新 ScheduleOpt 分别报上下界相等的 26、172、57；la01_rdata/ la03_rdata/ la07_rdata 的旧上界各高 1。保留两个来源的完整记录，选择锁定 ScheduleOpt 作为当前维护表参考。被选记录的证书字段均不能替代本轮审计；缺证书时不提升证据等级。若之后 A/C 独立证明最优，应另建运行证据并更新离线报告，不覆盖本次快照。

指标名称须明确 `gap_to_reported_optimum`、`gap_to_reported_bks`、`gap_to_reported_lower_bound`、`gap_to_paired_A`。失败的 makespan 和 gap 均为 null。所有文献、来源 URL、BKS、上下界只由离线评价器读取，不能拼入被评测 B/C 的 prompt、工具响应或工作目录可见资料。

## 复现与检查

在实验根目录执行：

```sh
python3 scripts/acquire_fjsp.py --download --prepare
python3 scripts/acquire_fjsp.py --verify
python3 -m unittest discover -s tests -p test_fjsp_validation.py -v
```

下载默认使用 `http://127.0.0.1:7897`，可用 `--proxy` 指定；网络沙箱可能需要只读联网授权。脚本检验 Git tree blob 与文件 SHA256，已有数据不同会失败而不覆盖，重复执行相同内容只验证。`--verify` 完全离线、不会求解。脚本不调用模型或优化器，参考值从不写入实例 JSON。测试临时文件只在本实验 `data/raw/fjsp/` 内创建并清理。

独立检查器不 import parser/solver/decoder，不信任输出自报 objective。手算合法例 makespan=7，换机后按机器相关工时合法例 makespan=9；逐约束故意违规覆盖遗漏、重复、无资格机器、多机器、工时、precedence、容量、时间范围及畸形数据，失败 makespan=null。默认测试入口与主项目统一使用 `src.fjsp` import。

剩余限制：Brandimarte 原论文全文未取得，参考最优证书未独立复核，数据库引用可能存在共同上游来源，双源匹配不等于独立生成。这些限制不影响当前输入解析和排程硬约束检查，但限制“原始版本逐字确认”和“独立验证最优”表述。
