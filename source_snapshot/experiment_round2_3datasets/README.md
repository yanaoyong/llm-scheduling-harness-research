# 第二轮三数据集真实排程对照实验

本目录完成 Brandimarte、Hurink、完整官方 SMT2020 的 A 经典优化 / B 直接排程 Agent / C 求解器增强 Agent 对照。135条原核心记录为134成功、1通道失败；45条固定策略辅助全部成功。唯一失败经单独冻结的一次同请求恢复后，静态最终108逻辑格点全部交付并通过独立约束检查，原失败与原质量统计保留；SMT核心27及辅助9条均完成8小时闭环并通过动作/事件审计。只做本地 Git，未建远程仓库或推送。

优先阅读 [中文报告](docs/REPORT_zh.md)、[最终验收](artifacts/final/acceptance.json)、[逐格点与成本表](artifacts/final/run_rows.csv)及[恢复交付清单](artifacts/static_recovery/logical_delivery.csv)。当前进度为 [STATUS](progress/STATUS.json)，原始任务见 [TASK](docs/TASK.md)。核心结果不显示普遍Agent优势：C改善主要集中在mk05，SMT的C业务指标与A相同，模型开销另计。

仅核查最终保存证据时，运行以下两条只读命令，不必重新调用模型或重新生成报告：

```sh
.venv/bin/python scripts/inventory.py --verify
.venv/bin/python scripts/final_acceptance.py --check-only
```

## 环境与获取

已验证 macOS arm64、Python3.12、OR-Tools9.15.6755。所有命令均从本实验目录执行；已有本轮虚拟环境时跳过前两条安装命令：

```sh
cd '__LOCAL_PROJECT_ROOT__/experiment_round2_3datasets'
python3.12 -m venv .venv
.venv/bin/python -m pip install --no-cache-dir -r requirements.lock
.venv/bin/python scripts/acquire_fjsp.py --prepare
.venv/bin/python scripts/acquire_smt.py --inspect-only
```

需要本机代理时，pip加`--proxy http://127.0.0.1:7897`。数据获取脚本使用固定版本、校验和与原始下载日志；具体首次下载选项见 `--help`、[静态来源](docs/fjsp-source-audit.md)及[SMT接口/恢复](docs/smt-interface.md)。大型官方数据与vendor已完整保存在本地，不直接纳入Git；原包/规范化文件/日志清单见 `progress/evidence-manifest.json`。源码及数据许可证分别列明，未发现许可文本者不冒称开放授权。

## 实验范围

静态为标准FJSP，独立校验器检查完整性、唯一指派、资格、机器相关工时、工艺链、容量、非负整数时间，并重算makespan。B的紧凑动作`[job,machine]`仍逐道决定真实顺序/机台，解码器只算时间；C显式选择CP-SAT动作并确认候选。参考值仅进入离线评价器。

SMT使用完整官方Dataset2 LV/HM数据、明确修订的adapter-v2；8小时窗口内只控制2/913台生产设备（组批与非组批各一），其余全厂统一固定策略。支持范围和近似见[约束语义](docs/smt-semantics.md)，不宣称全厂自主排程或真实工厂上线收益。

- [静态正式协议](docs/PROTOCOL_STATIC_v1.md)
- [SMT正式协议](docs/PROTOCOL_SMT_v1.md)
- [正式完成条件](docs/ACCEPTANCE.md)
- [来源参考状态](docs/fjsp-reference-summary.md)
- [独立静态审查](docs/review-static.md) · [SMT审查](docs/review-smt.md)

## 真实模型配置与预算

复用已验证的ChatGPT登录CLI，模型`gpt-6-astra / medium`，隔离、token及失败计数见[模型通道](docs/model-channel.md)。不读取、复制或提交令牌；认证由CLI自行管理。可验证当前登录与离线探测：

```sh
'/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex' login status
.venv/bin/python scripts/probe_model.py --run-dir runs/development/channel_probe_authorized --resume
```

新鲜模型运行会消耗配额。预算在统一`progress/model_ledger.jsonl`中先grant再reserve；开发全局24尝试，正式全轮300尝试、已报告300万token。未知账单为null；超额拒绝，不删除账本重置。每条运行独立目录、无原生工具调用、无其他方案结果。相同run_id仅可复用一致的已完成结果；中断不可覆盖。已有开发示例可安全恢复：

```sh
.venv/bin/python -m src.runner run --instance mk10 --arm B --run-id dev_mk10_B_compact_v2 --config configs/development-v2.json
.venv/bin/python -m src.smt_control --arm B --run-id dev_smt701_B
```

使用新的run_id是真实新调用，必须匹配尚有余额的显式grant；不能承诺随机模型返回相同排程。预算用完后，新的复现研究必须明确另行预注册预算，不改本轮冻结或删除旧失败。

## 正确性、回放与正式恢复

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m src.replay --phase development --label readme
.venv/bin/python -m src.smt_replay --phase development --label readme
.venv/bin/python -m src.batch --freeze static-v1
.venv/bin/python -m src.batch --freeze static-aux-v2
.venv/bin/python -m src.batch --freeze smt-v1
.venv/bin/python -m src.batch --freeze smt-aux-v1
.venv/bin/python -m src.replay --phase acceptance_static_v1 --label readme
.venv/bin/python -m src.replay --phase auxiliary_static_v1 --label readme
.venv/bin/python -m src.smt_replay --phase acceptance_smt_v1 --label readme
.venv/bin/python -m src.smt_replay --phase auxiliary_smt_v1 --label readme
.venv/bin/python -m src.report --phase acceptance_static_v1
.venv/bin/python -m src.report --phase auxiliary_static_v1
.venv/bin/python -m src.smt_report --phase acceptance_smt_v1
.venv/bin/python -m src.smt_report --phase auxiliary_smt_v1
.venv/bin/python scripts/analysis_tables.py
.venv/bin/python scripts/final_figures.py
.venv/bin/python scripts/final_supplementary_tables.py
.venv/bin/python scripts/final_plot_polish.py
.venv/bin/python scripts/campaign_status.py --write
.venv/bin/python scripts/inventory.py --verify
```

以上是重建流程；report/analysis命令会更新时间戳和派生文件，因而使既有最终证据哈希失效。复现重建宜在完整备份副本中进行，重新核验后按[验收步骤](docs/final-acceptance-gate.md)建立新索引和签署，不能直接覆盖已冻结审计来“修复”哈希。普通检查使用上方两条只读命令即可。

`scripts/campaign_status.py`读取记录与账本，`--write`刷新进度；原success保留原始运行状态，最终认证单独读取acceptance并核查其哈希。`scripts/analysis_tables.py`生成分数据集表、重复范围、Hurink资格统计和C参数记录，严格不混入补充恢复。`final_figures.py`产生3张条件于成功的摘要图，`final_supplementary_tables.py`保存F跨phase配对与恢复交付表，`final_plot_polish.py`只修正展示刻度/留白并绘制恢复图，不修改冻结代码或运行结果。图表统一选择r1，而非最好重复。

批次共用单一执行锁、单solver worker，按冻结矩阵串行；已完成项SKIP，不再调用模型。尚未完成的格点会继续真实运行，受全轮预算限制。正式配置/代码改变即拒绝，不把错误结果改成成功。全部事件/排程/失败留在`runs/`；CSV、图表及回放在`artifacts/<phase>/`。参考表从冻结commit读取，报告不以新参考值静默覆盖旧口径。

本轮早期少数开发记录只有源码哈希、无完整源码快照；回放明确标记provenance不完整，但原始模型/求解/排程证据保留。后续开发及所有正式记录保存完整源码快照、输入/配置/协议、Git commit与冻结清单副本。正式结果必须全部通过这些核查才验收。

## 唯一补充恢复与最终核验

[恢复协议](docs/PROTOCOL_STATIC_CHANNEL_RECOVERY_v1.md)在原180条全部结束、资格与原结果哈希冻结后，仅允许mk08_B_r1一次同请求恢复。补充记录保存在 `runs/recovery_static_channel_v1/mk08_B_r1__channel_recovery_1`，原失败仍在原目录。恢复makespan 523，新增248.22秒、1次模型请求，无求解器。已经完成，不需要再申请新调用。检查资格与重新离线审计可用：

```sh
.venv/bin/python scripts/recover_static_channel.py --inspect --freeze progress/freezes/static-channel-recovery-v1.json
.venv/bin/python scripts/audit_static_recovery.py --freeze progress/freezes/static-channel-recovery-v1.json --output artifacts/static_recovery/audit_readme.json
.venv/bin/python scripts/final_freeze_review.py
.venv/bin/python scripts/final_budget_review.py
```

后两条重写各自QA时间戳；用于重新审查时会使最终签署绑定失效，保留既有签署并另建新版本，不删除旧证据。四份原 `replay_final.json` / `smt_replay_final.json` 和恢复 `audit.json` 已绑定，不能覆盖；上文复现使用 `readme` 标签及新输出路径。原静态 `acceptance_ready=false` 是首次矩阵含失败的事实，最终108格点交付由补充审计及总验收分层认证。

实际执行记录在 [README命令核验](artifacts/final/qa/readme_commands.json)、[最终复现说明](artifacts/final/qa/readme_reproduction.json)。127项正确性测试通过，180原记录及1恢复全部离线核验；75张图已实际查看。[独立预算](docs/review-final-budget.md)、[版本核验](docs/review-final-freezes.md)和[报告审查](docs/review-report-final-signoff.md)提供具体证据。总验收的索引、签署、结果由 `scripts/final_acceptance.py` 检查，不自动新增模型或求解任务。

## 保存与恢复证据

`progress/STATUS.json`给出当前阶段、最新提交、已完成/失败/阻碍和下一条命令；`progress/iterations.jsonl`追加记录诊断。`scripts/inventory.py --verify`检查不进入Git的大型原始数据和日志。精确模型日志不能靠新鲜调用重新生成，应连同清单列出的文件按相对路径备份整个实验目录；本任务没有创建云端备份。环境可由requirements.lock重建。

首轮与历史调研只读，前后校验和在progress/history-integrity-*.json。不要修改首轮冻结配置/结果，也不要把本轮产物写入其它项目。未满足验收或遇到外部阻碍时，保留可恢复状态，goal不标完成。

本轮最终已核对3,936个历史文件哈希不变。正式含恢复共240模型尝试，已知1,907,787个input+output token、1次用量未知；费用与开发协作Agent开销未知。所有大型证据文件实际保留本地，清单校验可验证完整性；本任务未创建云备份。
