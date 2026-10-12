# 半导体排程首轮真实实验

本目录独立保存三方案实现、公开题目、实验协议和完整日志。历史 `inputs/`、`m0.5_research/`、`summary.md`、`relocation.json` 不修改。

- [中文实验报告](docs/REPORT_zh.md) · [结果差异分析与最终核验](docs/RESULT_ANALYSIS_zh.md)
- [统一协议](docs/PROTOCOL.md) · [问题规范](docs/problem-spec.md) · [数据来源与语义](docs/source-audit.md)
- [正式27条对照记录](artifacts/acceptance_v1/results.csv) · [甘特图](artifacts/acceptance_v1/gantt.html)
- [模型配置与隔离证据](docs/model-channel.md) · [进度](progress/STATUS.json) · [迭代日志](progress/iterations.jsonl)

## 运行环境

已实测 macOS arm64、Python 3.12.10、Apple clang++，依赖精确版本在 `requirements.lock`。使用作者原 PADL-2023 ASP 和官方原生 clingo-dl v1.5.0；不是FIFO，也不是自行重建约束模型。构建脚本链接 Python wheel 提供的 clingo/clingo-dl 库，换目录、Python环境或平台后必须重新构建。Linux可尝试同样脚本，但本轮只验收上述Mac环境。

以下命令均在独立实验目录执行：

```sh
cd '__LOCAL_PROJECT_ROOT__/experiment_round1'
python3 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.lock
.venv/bin/python src/build_solver.py
```

网络需要本机代理时，仅在 pip 命令加 `--proxy http://127.0.0.1:7897`；不需要时不用。已附本地vendor源码快照，提交见 `docs/source-manifest.json`。重新获取题目使用 `https://github.com/prosysscience/FJSP-SMT2020` 提交 `6253f982df13886ab75d9bc639bfaff045b2829a`，求解器使用 `https://github.com/potassco/clingo-dl` 提交 `4f91f6233b441864ccc39195b6b7b515d92bd848`。题目仓库未附许可证，应保留出处并在再分发或商用前确认授权；官方clingo-dl源码有MIT许可证。

## 离线正确性与记录回放

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python src/problem.py vendor/FJSP-SMT2020/PADL-2023/instances/instance01.lp --output artifacts/parsed_instance01.json
.venv/bin/python src/validator.py vendor/FJSP-SMT2020/PADL-2023/instances/instance01.lp runs/development/dev01_B/schedule.json --output artifacts/rechecked_dev01_B.json
.venv/bin/python src/runner.py verify-freeze
.venv/bin/python src/replay.py --phase development
.venv/bin/python src/replay.py --phase acceptance_v1
.venv/bin/python src/report.py
.venv/bin/python scripts/analyze_results.py
.venv/bin/python scripts/audit_formal.py --phase acceptance_v1 --label readme_recheck
```

测试含18项关键正反例和4组与原ASP交叉验证（192个固定候选、时间边界、singleton特例、开发witness）。测试和回放不会请求模型，结果重算保存到 `artifacts/`。`replay.py` 对照原始记录并在不一致时非零退出；所有失败仍纳入汇总。重新构建二进制可能因平台、工具链改变而不匹配原冻结哈希，这是新的复现环境，不应覆盖原冻结证明。

`audit_formal.py` 是正式运行结束后的额外审计：逐条核对模型事件、B动作回放、C参数与候选选择，以及CSV/报告；把最终排程固定后交给原ASP检查可行性与setup罚值。它不会替B生成排程，也不证明全局最优。原始最终审计保存在 `artifacts/formal_source_audit/final27/`；复核用新的label保留记录。`analyze_results.py` 只生成事后差异分析和逐机时间分解，不改变正式运行配置。

## A：原经典方案新鲜运行

```sh
.venv/bin/python src/classical.py vendor/FJSP-SMT2020/PADL-2023/instances/instance01.lp runs/readme_classical_recheck --time-limit 10 --seed 11 --configuration frumpy
.venv/bin/python src/validator.py vendor/FJSP-SMT2020/PADL-2023/instances/instance01.lp runs/readme_classical_recheck/schedule.json
```

原优化器最终可能报告 `UNSATISFIABLE`，表示不能再改善makespan；已有witness仍然是解。包装器保存全部原输出，分别报告 makespan optimal 与限时 feasible，不能仅根据退出字符串丢掉已求得的解。

## B/C：真实模型新鲜运行

配置文件 `configs/run_config.json` 固定 `gpt-6-astra / medium`，使用桌面应用自带CLI `0.162.0-alpha.2`。默认路径为 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`，不同机器需显式配置等效可用CLI。先通过该CLI的 `login status` 确认已有登录；若无登录，在用户自己的终端运行其 `login` 完成官方登录。不要把认证文件或令牌写入项目。没有可用真实通道时，保留失败，不能用mock。

```sh
'/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex' login status
.venv/bin/python scripts/probe_model.py --run-dir runs/development/channel_probe_isolation --resume
.venv/bin/python src/runner.py run --arm B --instance instance01 --phase development --run-id readme_fresh_B
.venv/bin/python src/runner.py run --arm C --instance instance01 --phase development --run-id readme_fresh_C
```

最后两条是真实新调用，每条有有限步骤、超时和预算。已有相同run_id会核对身份/配置/输入并复用完成记录；想再次调用请换一个新run_id。CLI runtime需要启动本地app-server，Codex外层受限沙箱可能需要已授权的exec网络/进程权限，内层模型仍只读且原生工具调用判失败。普通终端直接执行即可。

B逐工序决定顺序、机台和维护；`dispatch.py`只算时间和状态，绝不代排。C的JSON动作真实驱动原solver并检查反馈。每条模型请求保存prompt/schema/events/final/usage/耗时，查看 `runs/<phase>/<run_id>/model_XX/`；真实动作位于 `decision_XX.json`，工具反馈位于 `feedback_XX.json`。

## 正式评测与恢复

`configs/instance_split.json` 已在结果前锁定02/05/08，每方案每实例3次。原正式版本已冻结，不要重写 `configs/freeze.json`。下列批次命令仅运行缺失记录，已有完成项按指纹复用：

```sh
.venv/bin/python src/runner.py batch --phase acceptance_v1
.venv/bin/python src/report.py
```

新实验的开发结束后，才运行 `src/runner.py freeze` 生成新的实验目录自身冻结文件。查看正式结果后修改模型/工具/提示或语义必须转为开发迭代，另用预留实例和新协议，不用旧正式集继续宣称未见验收。

中断：已完成调用、排程和失败不覆盖；`started.json`存在但没有result的运行会明确拒绝自动重跑，开发阶段先诊断并保留旧尝试，再指定新run_id。正式阶段只允许规范ID，不能改ID替换中断或失败；需保留未完成格点、另行制定恢复/新验收协议，不能删除失败换成功或宣告27/27完成。`STATUS.json`和迭代日志提供恢复位置。

## 数据与指标

统一输入为 `data/instance*.json`（来自未改动的原.lp），排程为 `operations:[{id,machine,start,end,maintenance}]`，工序id是`lot:product:step:priority`。维护、时间单位、setup软约束和源码例外详见规范。

每条result保留可行/失败/超时、原因、完整独立校验、目标、首次候选可行性、修订与fallback、端到端/模型通道/求解器耗时及可得token。相对配对A的差距在离线 `summary.json/results.csv` 中计算；原始result的占位值不事后覆盖。缓存输入是输入子集；未知费用为null，不估实际账单。开发探测与排程调用单独列于 `model_usage_ledger.json`，正式成本独立统计。

本轮只覆盖所选PADL版本，没有组批/Q-time/动态Fab/人类排程对照，不宣称战胜人工或工厂上线收益。
