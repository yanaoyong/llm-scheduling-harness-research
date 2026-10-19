# Harness v6 Mac 离线验收 — 2026-10-18

> 当前状态（2026-10-19）：[S0 阶段归档](../../../../2026-10-19/README.md)。离线 660 项及 38 子测试通过；真实 A/B 已完成，正式轨迹 0/6，已按 E1 smoke 次数上限暂停。下文保留各自日期的历史记录，旧的“零真实调用”等表述不代表当前状态。

步骤 0–2 通过；步骤 3 已执行并保留完整失败证据，**未通过**。当前不可进入步骤 4。
真实模型调用数为 **0**。下载 Python 依赖和 tokenizer、查阅 Codex 官方配置/源码仅用于准备与诊断，不是模型实验。

## 环境与输入

- 基线：main / `846dee277c4f15e3b9353db342d4c46024a0fbe9`，本报告对应其上的未提交 Mac 修复；未提交、未推送。
- 独立工作目录：`__PROJECT_ROOT__/validation/harness_v6_mac_20261018`。Python 3.12.10；pytest 9.1.1；tiktoken 0.14.0 / o200k_base。
- Codex：`codex-cli 0.147.0`；仅固定版本，未验证真实 provider 的认证或模型权限。
- 本地 mock 元数据标签：`gpt-5.4`；这是本地工具配置选择，不能视为已批准的真实模型。
- 物理环境 3 文件、SMT2020_LVHM 数据 20 文件、vendor 26 文件、公开证据 27,998 文件，共 28,047 文件逐项核对历史 SHA256。
- evidence 包 SHA256：`a518bb950e8a52dd2687ae753251a0c80fd96f5226b6b9af1e0185a11c7fb003`，对照 Git 中的发布记录；物理输入对照 2026-10-12 存档清单。未以当前文件自算 hash 冒充来源证明。
- 验收输入复制到 WORK；复核 preflight 全部通过。源码改动与可复现产物分别保留。

证据：[preflight](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/preflight-final.json>)、[输入来源](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/input-provenance.json>)、
[依赖锁定](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/requirements.freeze.txt>)、[修复源码 SHA256](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/source-sha256.json>)、
[源码差异](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/source-changes.patch>)、[机器可读汇总](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/acceptance.json>)。

## Mac 入口修复

1. preflight 默认分支改为 main。
2. 封存构建/验证用显式 `--work-root` 取代 Linux 固定目录，拒绝仓库内输出、越界、符号链接绕过及与数据/证据重叠；构建拒绝覆盖已有运行目录。
3. RUNBOOK 补全 P2、E1、一小时 P2 机制产物，题集固定四状态；修正 zsh 不兼容的 `read -p`。
4. 本地探针隔离 HOME/CODEX_HOME；使用 `web_search=disabled` 与 `features.view_image=false`；支持 namespace 工具声明；显式记录 mock 模型名。工具隔离检查仍严格拒绝额外工具。
5. 进程回归按“主进程结束后两秒内清理”计时，保留包含启动时间的五秒宿主截止；生产 runner 未改。分段诊断的清理时间为 21–23 ms。
6. `cycle.py`、执行器、plan_delta 及物理/展示语义未改。

## 步骤 0–2 的验收结果

| 项目 | 结果 |
|---|---|
| preflight | 全部 PASS |
| 公共与封存夹具 | 构建、验证通过；最终构建器新目录复建，fixture/build_summary 与首次构建逐字节一致 |
| 封存分类 | 86 个观测；G0/G1/G2 = 10/15/4；2 个已知新规则例外 |
| 封存轨迹回放 | 128 事件，终点 1603.1 s，valid=true |
| plain suite | 508 passed / 47 skipped，0 failed |
| configured suite | 543 passed / 12 skipped，0 failed |
| 物理下界 | 305 次实际开工，0 violations |
| 四状态题集 | 384 题、16 次 counterbalanced 请求；仅生成，未发送 |

configured 的 12 个 skip 均为独立的真实 Codex 证据检查。它们随后在步骤 3 中实际执行并失败，不能把 configured 通过等同于步骤 3 通过。
plain 的 skips 为未配置物理/封存输入及相应探针，逐项原因在日志中。

[plain 完整日志](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/logs/plain-final.log>)；[configured 完整日志](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/logs/configured-complete.log>)；
[封存分类](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/classification-configured-complete.json>)；
[夹具验证](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/sealed/validation.json>)；[物理时间窗](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/window-final.json>)；
[过滤审计](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/audit-final.json>)。

三份物理机制回放均由脚本规划器驱动，不代表模型质量或成本：

| 产物 | 终点 s | cycles | sessions | 审计 steps | 恢复一致 / horizon defects |
|---|---:|---:|---:|---:|---|
| p2 | 1603.1 | 16 | 16 | 232 | PASS / 0 |
| e1 | 1603.1 | 50 | 50 | 218 | PASS / 0 |
| hour | 4302.0 | 60 | 60 | 1070 | PASS / 0 |

本次 `p2.json` 及四个附属文件是先完成的 `phase-m2-final-p2.json` 产物的逐字节副本；别名记录在 [这里](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/p2-artifact-aliases.json>)，未重新解释或改写证据。
一小时回放为 t=702→4302、Δ=60、breakdowns=false 的机制验收；不是交接中待做的 Δ/锚点策略比较。

G0 快照成本复现交接数值：

| 格式 | 当前状态 tokens | 静态前缀 tokens | 完整快照 tokens |
|---|---:|---:|---:|
| explicit | 78,295 | 94,564 | 172,859 |
| dense | 54,607 | 57,826 | 112,433 |

dense 当前状态比旧 43,817 增加 10,790，小于 20,000 上限。upcoming=172；23 pending + 3 running base tasks = 26，实际 running_jobs=907。
交期映射 dense 增量仍为 10,676，大于原批准的 8,000，仍关闭。
[token 证据](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/tokens-final.json>)。

A/B 每个状态每类 12 题均有 12 个独立目标。upcoming 各状态均含 6 个 present / 6 个 absent；batch_compatible 含 same_machines_different_key 近似反例。
局限：eligible 题仅覆盖非空资格集；三个公共状态的 queue 题只有 no_pending_idle，其他三类由 G0 覆盖。
16 次请求尚未执行；不能据此选择 dense。
[题集覆盖](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/ab-kit/coverage.json>)；[请求顺序](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/ab-kit/presentation_plan.json>)。

## 步骤 3：真实 Codex 本地 mock 未通过

最终为 **0 PASS / 12 FAIL**；归档证据测试也是 **12 failed**。manifest `mechanism_only=false`，`real_model_requests=0`。
每项实际仅向 127.0.0.1 mock 发送一次请求，并被工具表检查返回 HTTP 422，未切换真实 provider。

- single_action 的请求仍包含 `apply_patch`，违反“零工具”要求。
- MCP 请求包含 `list_mcp_resources`、`list_mcp_resource_templates`、`read_mcp_resource`、`apply_patch`、通常还有 `tool_search`。read_entities 被延迟发现，未作为唯一工具直接广告。
- 这些失败发生在请求入口，所以 JSONL、超时、压缩、大结果完整传输等后续能力仍是**未验证**；不能说它们各自存在 12 个独立缺陷。
- 网页与图片工具已不再出现在最终请求中。未改验收阈值、未删除原始失败证据、未用 fake Codex 替代真实二进制。

同版本官方源码显示：配置 MCP server 时无条件加入三个资源工具；模型元数据决定 apply_patch 与搜索工具的暴露。这解释了实测现象，单靠现有“禁用 shell”不能满足契约。
参考：[Codex 0.147.0 工具注册源码](https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/core/src/tools/spec_plan.rs)、
[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。

[最终 manifest](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/probes-final/manifest.json>)；
[MCP 请求原文](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/probes-final/config_injection/requests.jsonl>)；
[single_action 请求原文](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/probes-final/single_schema_no_mcp/requests.jsonl>)；
[12 项归档验收日志](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/logs/probe-gates-final.log>)。
`probes/`、`probes-v2/` 为前两次失败记录，原样保留。

代码检查还发现：步骤 4 的 measure_request_overhead.py 当前只接受扁平 function schema；若适配后继续使用新版 namespace 工具格式，还要补齐其计数兼容性测试。此项来自静态检查，步骤 4 未运行。

优先后续工作：建立能严格限制原生工具、直接广告 Harness 工具的执行适配，再固定二进制/配置并重跑 12 项。若需要改变工具契约或维护定制 CLI，应先单独确认方案；本次没有放宽工具范围来绕过失败。

## 失败与修复记录

- 首次 plain：505 passed / 47 skipped / 1 failed，进程总耗时超过两秒 0.019 s；入口回归复核又出现 2.25 s。已按测试原意分离启动和清理计时，保留旧日志及 [分段诊断](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/runner-timing.json>)，最终完整 plain/configured 通过。
- 首次 configured：538 passed / 12 skipped / 3 failed，缺 p2/e1/hour 机制产物。已补齐真实物理回放证据并重跑完整套件，没有删测试或增加 skip。
- 准备步骤 4 样本时，最初按完整测量快照 token 数核对 A/B 文件未通过；进一步检查确认源脚本有意省略工具前缀，原样保留题集并记录口径差异，留待步骤 4 前对齐。
- 步骤 3 仍失败，属于未解决项，不包含在“步骤 0–2 通过”的表述中。

## 步骤 4 需要确定的参数

前置条件是步骤 3 对**相同模型元数据、二进制和配置**通过。目前只列参数，未执行开销录制。

| 参数 | 要确定什么 |
|---|---|
| CODEX / PIN | 能通过 12 项检查的二进制完整版本与路径；当前 0.147.0 未通过 |
| MODEL | 后续真实实验拟用的精确模型名；本次 mock 标签 gpt-5.4 不代表选择 |
| CONTEXT | context_token_budget，按该模型实际可用容量确认 |
| RESERVE | output_reserve_tokens，覆盖输出及推理预算 |
| ROUNDS | 至少覆盖将登记的 session_budget.max_tool_calls；不能只录一轮再允许更多轮 |
| 其他影响请求的模型设置 | 若指定 reasoning effort 等，先让录制与生产入口显式一致，不能继承个人配置 |

固定录制矩阵为 single_action / mcp_session × explicit / dense，使用与生产前缀一致的两个 G0 快照（目前尚需对齐，见下文）。
完整 G0 快照为 explicit 172,859 / dense 112,433 tokens，尚不含实际系统提示、请求协议及多轮工具结果。
若采用 220,000 上下文，explicit 的 overhead + reserve 仅有 47,141 token 空间；这只是算术余量，不代表容量批准或已通过预算。

`request_overhead_tokens` 应由录制结果产生，取两种模式/格式/已覆盖轮次的最大非快照输入；逐轮检查 snapshot + overhead + reserve ≤ context，不沿用旧快照的开销值。
现有 `ab-kit/explicit-snapshot.txt` 和 `dense-snapshot.txt` 是从 A/B 提取的样本，实测为 170,769 / 111,277 tokens，tools 前缀为空。它们与上表包含完整工具 schema 的测量口径不同；run_live.py 又使用 TOOL_DESCRIPTIONS。进入步骤 4 前必须统一生产与录制的前缀口径，准备对应样本，不能直接宣称当前文件已覆盖生产预算。差异记录见 [快照复核](<__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/step4-snapshot-readiness.json>)。

模板中的 max_tool_calls=100 不是本次批准的轮数；session_budget.token_cap=100000 也低于两种 G0 完整快照，进入 smoke 前必须重新登记累计 token 预算。

Δ、锚点开会规则、交期字段和步骤 5/6/8 的真实模型费用预算仍待后续决定；它们未在本次离线验收中被默认批准。
