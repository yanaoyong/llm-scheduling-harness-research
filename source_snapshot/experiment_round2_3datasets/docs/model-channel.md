# 本轮真实模型通道、预算与静态 Agent

## 核查与真实证据

2026-10-09（中国标准时间）重核本地 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`：版本 `codex-cli 0.162.0-alpha.2`，`login status` 返回 `Logged in using ChatGPT`。没有读取、复制或输出凭据；复用 CLI 自身已有认证存储，没有将交互登录当成 API key。CLI help 确认支持本轮使用的 JSON events、ephemeral、ignore-user-config、ignore-rules、只读沙箱和 output-schema 选项。依据保存在 `runs/development/channel_probe_preflight/`。

优先读取实际本地实现与帮助后，无需通过外部网页推断此 alpha 版本行为。使用 OpenAI Docs 技能时遵循上层要求的本地核查优先级。底层复用首轮已验证配置和 transport 思路，未修改首轮文件。

| 探测 | 结果 | CLI 耗时 | 输入 / 缓存 / 输出 token | 完成模型轮次 | 原生工具事件 |
|---|---|---:|---|---:|---:|
| channel_probe_sandbox | app-server 初始化被 OS 拒绝 | 7.425 秒 | 未知 | 0 | 0 |
| channel_probe_authorized | 真实成功 | 14.991 秒 | 4321 / 0 / 21 | 1 | 0 |

首个尝试原始 stderr 为 `failed to initialize in-process app-server client: Operation not permitted (os error 1)`；本地失败也消耗统一账本的一次尝试，不假设 token 为零。第二次经外层 `require_escalated` 执行，内层模型仍在同一只读、无 Shell 隔离配置中。探测只验证通道，不算排程成功。通道共 2 次 CLI 尝试、1 次真实成功推理；成功后停止进一步探测。

## 隔离边界

每次调用有空的 `isolated-cwd`、独立日志和 runtime 目录；提示词仅接收白名单问题字段及该运行自身反馈。静态提示词不包含来源、参考值、其他方案结果或检索入口。CLI 运行全新 ephemeral 会话，忽略用户配置与执行规则；禁止读取项目文档，禁用 host skill discovery、已发现 skills、MCP、插件、Apps、浏览器、计算机、图像、Web、Shell、unified_exec、memory、hooks。禁止 approval，`code_mode_host=false`。多 Agent 总并发槽固定为 1、结构化 multi_agent_v2 禁用。清除继承的 CODEX 会话环境变量，保留 CLI 自有认证所需的 CODEX_HOME。

不声称模型工具清单绝对为空。首轮同版本审计曾观察到残余控制工具；本轮以配置和每次 JSON 事件联合审计。仅允许 `agent_message`、`reasoning`、`error` 消息项，任何原生执行项或损坏事件日志都使 transport 失败，不把模型自报“无工具”当作隔离证明。每次调用要求恰好一个 completed turn。探测成功日志实际无原生工具事件。

CLI 可能在用户目录维护认证、模型缓存和启动状态，这些不复制进实验目录。请求、提示词、schema、无凭据的 argv、原始 JSONL/stderr、最终文本、结果全部保存在本轮运行目录，log_dir 和 sqlite_home 也指向每次独立的 runtime 子目录。

## 统一预算

`src/agents/budget.py` 提供进程锁和追加式 `progress/model_ledger.jsonl`。调用前 reserve 后执行，结束再 finish。唯一 call_id、独占 attempt.claim、不可变 grant 与不可覆盖的目录防止重复调用；失败及中断预留不退款。开发全部模型 CLI 尝试的硬上限为 24。正式 grant 必须显式给 phase_limit，首次记录后固定。开发求解总 requested seconds 硬上限 600；正式求解另设显式总上限。

模型与求解器共享该账本，分别使用 reserve / solver_reserve 事件；A 在上层运行器记账，C 在调用点记账，底层 solve 不重复记账。每次记录 requested solver seconds 与实际 wall_seconds。开发代码协作 Agent 的开销无法从此 transport 获取，未知，不能混为正式评测模型开销。

```python
from src.agents.budget import BudgetLedger
ledger = BudgetLedger()
# 以下是主 Agent 在分配预算时调用的接口，不应让运行时模型自行授予预算。
ledger.grant('allocated-id', 'development', max_calls=3, run_prefix='/absolute/run/prefix')
ledger.grant_solver('allocated-solvers', 'development', max_seconds=30, run_prefix='/absolute/run/prefix')
# 正式必须给 phase_limit=预先冻结的本阶段总调用数或总solver秒数。
```

ledger 把损坏 JSONL 视为错误并停止，不吞掉历史以重置预算。崩溃留下未 finish 的 reserve，恢复时需要先审计，不自动回收。固定配置禁止自动重试；模型通道内部 HTTP 重试次数不可观测，明确为未知。

## 静态 B/C 接口

`from src.agents.static import run_b, run_c`，两者接受 `(problem, run_dir, config) -> dict`。问题与独立校验器遵循 `docs/INTERFACES.md`。B/C 固定 `gpt-6-astra / medium`，每条运行独立，默认 B 至多 2 个模型响应、C 至多 3 个模型响应，可由冻结配置缩减或在上限内预先设置。配置关键字段：

```json
{
  "model": {"model":"gpt-6-astra","reasoning_effort":"medium","timeout_seconds":240,
            "phase":"development","grant_id":"主Agent分配的模型grant"},
  "max_model_calls":3, "wall_seconds":780,
  "solver_budget_seconds":30, "max_solver_calls":2,
  "solver_grant_id":"主Agent分配的solver grant"
}
```

B 输出完整 `order:[{id,machine},...]` 和 rationale。模型决定全部工序的全局列表顺序与合格设备。解码器严格按照列表计算 `start=max(job_ready,machine_ready)` 与 `end=start+duration`，不排序、不填缺失、不改设备、不在前面的空隙中插入工序。缺失、重复、工艺逆序、非法设备和类型均拒绝；只允许有限次带错误反馈的模型修订。独立校验通过才接受。此 append-only 解码不能表达任意等待与主动插空，只支持该构造产生的半主动排程，因此限制了 B 的搜索空间。

C 动作是 `solve` 或 `finish`。solve 白名单包括 time_limit、seed、search_branching（AUTOMATIC_SEARCH/FIXED_SEARCH/PORTFOLIO_SEARCH）、randomize_search；强制 workers=1。模型收到实际候选的状态、目标、下界、耗时和独立校验反馈，决定是否再求解，最后必须 `finish(candidate_index)` 选择本运行已验证的候选。无 finish 即失败，不能由运行器自动选最好候选。A/C 共用 `src/fjsp/solver.py` 的同一约束模型；C 对每次参数和求解结果留痕。如仅一次 solve 加 finish，则报告为一次参数选择与候选确认，不夸大为多轮自适应优化。

返回字段含 status、failure_type、schedule、validation、metrics、costs、actions、model_results、solver_results、selected_candidate、started_at/finished_at。失败的 makespan 是 null。运行器在 `agent_result.json` 保存完整结果，不覆盖主运行器的 `result.json`。

first_action_valid 表示首响应动作是否合法；first_output_valid 表示首响应是否产生独立有效的排程（C 须首响应 solve 返回有效候选）。C 另记 first_candidate_valid，避免把先犯错后得到的首个求解候选误作首次响应成功。first_valid_output_seconds 是从端到端起点到首次独立有效排程的耗时；C 后续若未明确 finish，最终仍失败。revisions 计已有错误决策后的修订，revision_success 仅在有修订且最终成功时为 true；正常多次 solve 的策略迭代不是错误修订。

## 成本与恢复

每次模型硬超时 1–300 秒；probe 为 180 秒。超时终止整个进程组并保存失败。agent 还受总 wall_seconds、步骤数、求解次数和请求求解总秒数限制。model_elapsed_seconds 含 CLI 启动和网络，不代表纯服务端推理时间。纯模型时间、后端 HTTP 次数、货币费用与未报告 token 均为 null。cached_input 是 input 的子集，reasoning_output 是 output 的子集，不重复相加。

`call_model(...,resume=True)` 仅回放指纹一致且已完成的结果，零新调用。`run_b/run_c` 的 `config.resume=true` 回放已完成的 agent_result，问题/配置指纹必须一致。中断目录不允许覆盖或直接重跑；先审计账本和原始日志，再分配新目录与额度。

在实验根目录执行以下离线命令：

```sh
.venv/bin/python -m unittest tests.test_agents -v
.venv/bin/python scripts/probe_model.py --run-dir runs/development/channel_probe_authorized --resume
```

新鲜 probe 需要主 Agent 先显式分配 grant，并选择从未使用的目录；已使用的 probe grant 额度已耗尽。不要把离线单元测试中的合成 transport 输出当作真实实验数据：这些仅测试控制流，位于 tests 临时目录并清除，正式 runner 没有 mock 模式。

## 全轮调用间token准入（正式冻结补充）

开发默认400,000、正式默认3,000,000已报告input+output token；缓存输入/reasoning不重复累加。每次reserve在锁内统计已完成条目；未知用量完成尝试达到3次停止后续调用，在途单列。新鲜提示超过120,000 Unicode字符在reserve前拒绝。CLI没有已核实的服务端硬输出token限制，这是调用间停止阈值；串行可能超出最后一个已准入的有界请求，并发开发可能超出已在途请求。实际费用仍null；不删除失败账本或重置计数。14项新增预算测试验证该规则。
