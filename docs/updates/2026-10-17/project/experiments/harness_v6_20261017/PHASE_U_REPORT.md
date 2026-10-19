# Phase U：官方 Codex 离线核验报告

日期：2026-10-19；分支：`feat/harness-v6-official-codex`。未 commit/push，未读写用户 `~/.codex`。


生产改用官方 `codex-cli 0.163.0`，同时校验 registration 的 `codex_binary_sha256`；
拒绝 `-harness-v6.*`。本机已核验 Linux 二进制 SHA256：
`399ff69c431c066e40de318fba45c2b07f45a76b19939d247ee4828fc70c4215`。
`patches/`、旧 build 脚本及旧报告只保留历史，不再作为生产依赖。

接受四项放宽：MCP 额外暴露三个官方资源工具；请求限制改由宿主执行且中止 usage 为
unknown（除非已经收到完整 `turn.completed`）；没有逐请求输出上限；允许编辑客户端
`gpt-6-astra` catalog。用 `scripts/freeze_model_catalog.py --source FILE --slug gpt-6-astra
--output /tmp/v6u/catalog.json` 只保留指定模型，删除所有非 models 顶层字段，精确应用
`tool_mode=direct`、`use_responses_lite=false`、`experimental_supported_tools=[]`、
`apply_patch_tool_type=null`、`supports_search_tool=false`、`multi_agent_version=null`。
脚本输出 SHA256；model_config 仍为绝对路径/hash/reasoning_effort 三字段。

实测 MCP 工具为 namespace `mcp__harness_v6` 下的 `read_entities`、`validate_plan`、
`submit_plan`，加顶层 function `list_mcp_resources`、`list_mcp_resource_templates`、
`read_mcp_resource`，每个恰好一次；single_action 为零工具。资源 schema 纳入录制请求开销。
关闭 goals、三项 code_mode 设置及可配置的额外工具/指令入口；保留官方基础模型指令与
sandbox 权限说明。官方 `openai_models.rs::auto_compact_token_limit` 仍钳制在窗口 90%，
872000 窗口的 admission ceiling 仍为 784799（含 overhead 与 output reserve）。

第 N+1 次 Harness 调用或任意 `resources/*` RPC 写 `abort.json`（reason/method/count）
并阻塞，不返回结果；宿主每 20ms 检查并终止进程组，失败 session 永不采用。
rollout_budget 在空提醒数组时仍向首次请求插入 `<rollout_budget>` developer 输入，故生产
关闭。mock 的 limit=90、权重均为 1.0 在第一轮后退出 1，报
`shared rollout token budget exhausted`；没有完整 usage。该计数使用非缓存输入加输出，
不能等同于完整输入 token cap。请求体对照见 `/tmp/v6u/probes-u/rollout-budget.diff`。

| 情形（N=max_tool_calls，忽略网络重试） | single_action | mcp_session |
| --- | --- | --- |
| 正常、遵守工具协议 | 1 | ≤N+1 |
| 超限 Harness 调用，无其他循环 | 非广告工具，见幻觉行 | ≤N+1，标记后不再请求 |
| 合法资源调用到达 Harness RPC | 非广告工具，见幻觉行 | 已完成 k 次工具轮后 k+1，≤N+1；标记后不再请求 |
| 幻觉工具名、无效资源参数/服务器、本地拒绝后重试 | 无固定请求数上限，仅墙钟 | 无固定请求数上限，仅墙钟 |

墙钟不是确定的请求次数或费用上限；token_cap 在完整 usage 后拒绝超预算结果，output reserve
只是 admission 预留，并非 API 输出限制。mock 幻觉循环用固定响应延迟验证有界的观察次数，
不能推导真实生产的数字上限。由于 unsupported-call 拒绝在 JSONL 中不可见，
也不能仅凭 healthy completion 证明 single_action 只发了一次请求。压缩只按官方 `item.completed/error` 的固定前缀
`Heads up: Long threads and multiple compactions` 分类，其他 error 继续失败。

开放项：内置 openai provider 的 websocket 传输不可通过上述 config 覆盖；中止后的真实计费
与 usage unknown、无输出上限的实际行为，均须真实 smoke 验证。本阶段只有 loopback mock，
真实模型请求 0，不构成真实 API 或费用保证。

## 实现文件与决策

- `src/harness_v6/codex_pin.py`、`scripts/run_live.py`、`scripts/ab_comprehension.py`：生产验证官方精确版本及 registration SHA；旧 build 脚本将历史常量留在脚本内，解除生产模块对 fork 的依赖。
- `scripts/freeze_model_catalog.py`：显式输入/输出/slug；单一行、六处覆盖、清除顶层账号元数据、拒绝仓库内输出。此次输出 `/tmp/v6u/catalog.json` 的 SHA256 为 `681754c7b7fce292c38a32444ef60e899e575d26b4815b60b8e79704353e9631`；reasoning=medium，context=872000。
- `src/harness_v6/model_config.py`：格式和计算不变，仅将 admission 注释校正为官方源码已确认行为。
- `src/harness_v6/session.py`、`single_action.py`：移除 patched-only 两参数；关闭 goals/code_mode 等默认入口；保留 output reserve 作为宿主 admission 输入；删除 fork 专用失败 usage 的可信例外，只有完整 turn.completed 可提供完整 usage；识别官方 compaction warning item。
- `src/harness_v6/tool_contract.py`：生产 interaction 检查严格限定六个工具、namespace 和唯一性；通用声明解析继续支持历史录制格式，以保留原 overhead 回归检查。single_action 严格为零工具。
- `src/harness_v6/mcp_server.py`、`codex_runner.py`：原子发布 abort marker，工具/资源调用不答复；宿主轮询并终止进程组。官方 MCP 另建进程组，阻塞端在父进程消失后退出，防止遗留服务；宿主退出竞态仍检查 marker 并判失败。
- `scripts/run_codex_probes.py`：18 项官方 mock 检查；保留全部旧检查和 mechanism_only 边界；增加实际 CycleServer 超限、资源 read/list/templates 中止及诊断 rollout stop。保存预算开关的请求体 diff。fake 的旧 13 项矩阵仍单独验证，不能满足官方 gate。
- `tests/probe_checks.py`、`test_run_cli.py`、`test_phase_p.py`、`test_native_request_budget.py`、新增 `test_official_codex.py`：验证官方 pin、未知 usage、严格工具集合、catalog 派生、阻塞标记、宿主不采用及开销计入。原 native gate 允许 ELF/Mach-O，继续拒绝脚本、fake 标记及 SHA 不符。`test_mac_factory.py` 将临时 store 放到 pytest tmp_path，避免写 sealed fixture 目录。
- `README.md`、`DECISIONS_v6.md`：短 Phase U 决策、放宽项、请求上界与真实 smoke 开放项；本报告保留详细证据。

默认入口审查使用官方 `features/src/lib.rs` 和 `core/src/tools/spec_plan.rs`：已有 shell、view_image、multi_agent、plan、request_user_input、skills、environment/apps/collaboration 指令关闭项继续保留；另显式关闭 sleep、unified_exec、hooks、apps、tool_suggest、plugins、browser_use、computer_use、image_generation、skill_search、skill_mcp_dependency_install、workspace_dependencies、current_time_reminder。模型 catalog 的基础 developer 指令与 sandbox 权限说明仍存在，均计入录制 overhead。资源工具在有 MCP server 时无 config 开关。

## 请求体与中止证据

最终 manifest：`/tmp/v6u/probes-u/manifest.json`，18/18 PASS，共 35 个 loopback 请求体，真实模型请求 0。
所有录制请求再次用最终严格 interaction contract 检查通过（压缩请求明确为零工具）。
`over_limit_harness-verified/` 是超限探针最终记录：第一轮实际 read 返回 status=ok，第二轮
写 `{"count":2,"method":"tools/call","reason":"tool_budget"}` 后宿主退出 -15，无第三请求。
resource read/list/templates 各一请求后退出 -15，无第二请求；三者均 usage_unknown。
marker 的 count 在超限时表示本次尝试的 Harness 调用序号；资源中止时表示已记录的 Harness 调用数。
single_tool_rejection 在两秒墙钟及 mock 每响应 0.1s 延迟下观测 8 次请求，exit=-15，
`missing_turn_completed`、`usage_unknown`、`invalid_final_action`；不是健康完成，也不是生产请求上限证明。

`rollout_budget_stop/session.jsonl` 先有官方 under-development warning item，随后 error 和 turn.failed：
`shared rollout token budget exhausted`，exit=1，未超时，一次请求，没有 turn.completed。
`rollout-budget.diff` 只规范化 message id；保留请求中随机 session/client metadata 差异，
同时明确显示新增 rollout_budget developer message。生产关闭 rollout_budget，不能用其宣称请求数硬上限。

`/tmp/v6u/request-overhead.json` 对 config_injection 两轮完整请求计数：六个工具 schema 每轮
1060 o200k_base tokens，已包含三个资源工具；该数据是 mock prompt 录制，不是完整生产 snapshot
的重新测量。`usage_unknown=true` 表示未知完整 usage，不以零费用接受 session；已有的累计指标
仅累计已知部分，并保留 unknown_usage 计数，不能将该小计解释为完整计费。

## 验证命令

统一使用 `/workspace/v6-mac-env/venv/bin/python`、`PYTHONPATH=src:/workspace/v6-mac-env/physical`、
`TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache`；最终 pytest 临时根为 `TMPDIR=/tmp/v6u`。

```bash
export PYTHONPATH=src:/workspace/v6-mac-env/physical
export TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache
export TMPDIR=/tmp/v6u
/workspace/v6-mac-env/venv/bin/python -m pytest -q
/workspace/v6-mac-env/venv/bin/python scripts/run_codex_probes.py --codex-binary /workspace/v6-mac-env/codex-official/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex --codex-version 'codex-cli 0.163.0' --model gpt-6-astra --model-config /tmp/v6u/model-config.json --context-token-budget 872000 --output /tmp/v6u/probes-u
V6_PUBLIC_LEDGER=/workspace/v6-mac-env/work/phase-m2-final-p2.json.ledger.jsonl.gz V6_MAC_FIXTURE=/workspace/v6-mac-env/work/sealed2/fixture.json V6_SEALED_DB=/workspace/v6-mac-env/work/sealed2/contexts.sqlite V6_SEALED_SELECT='SELECT group_name,payload FROM contexts' V6_CLASSIFICATION_REPORT=/tmp/v6u/classification-verified.json V6_F6_PROBE_DIR=/tmp/v6u/probes-u V6_SINGLE_ACTION_PROBE_DIR=/tmp/v6u/probes-u /workspace/v6-mac-env/venv/bin/python -m pytest -q
/workspace/v6-mac-env/venv/bin/python -m compileall -q src tests scripts
git diff --check
```

超限首轮从错误 read 参数改为成功 read 后，只定向重跑该探针，manifest 更新其路径/hash；
其余 17 项无需重复。最终严格 namespace 检查也对全部已保存请求体重新运行，无新增模型请求。

## 中间失败与修复记录

- 首次官方矩阵：15 PASS / 1 FAIL；失败项 `compaction_detection` 的原错误为
  `forbidden_item:error`。原因是官方警告位于 item.completed 内，按实测事件位置修复，后续完整矩阵 18/18 PASS。
- 初次 plain：611 passed / 1 failed / 48 skipped，38 subtests passed。
  失败为 `test_capture_overhead_real_recording_synthetic_snapshot`，`AssertionError: assert False`。
  原因是 fake 的 overhead 广告误变成一个工具；恢复三工具 fixture，保留原验收断言。
- 加强 namespace 检查时的 plain：619 passed / 6 failed / 48 skipped，38 subtests passed。
  六个旧 overhead 测试报 `ValueError: unsupported Responses request field tools: unexpected unqualified tool: validate_plan`。
  修复为生产 interaction 严格 namespace、通用历史解析保留兼容；未跳过失败或降低生产 gate。
  对应旧代码的 configured 运行在 3 passed 后主动中断（KeyboardInterrupt），随后重新完整运行。
- 修复后定向检查：42 passed；包含 overhead、官方策略与工具合同。mock 墙钟中止时日志中的
  `BrokenPipeError: [Errno 32] Broken pipe` 是宿主关闭 HTTP 流后 mock 写回导致，不是未处理的生产成功或探针 FAIL。

## 最终验证结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| Plain `python -m pytest -q` | 625 passed，48 skipped，38 subtests passed，0 failed；251.22s | `/tmp/v6u/plain-verified.log` |
| 官方 loopback probes | 18 PASS，0 FAIL；最终 manifest 35 请求，真实模型请求 0 | `/tmp/v6u/probes-u/manifest.json` |
| Configured suite | 673 passed，0 skipped，38 subtests passed，0 failed；4259.75s（1:10:59） | `/tmp/v6u/configured-verified.log` |
| 定向回归 | 42 passed，0 failed | `/tmp/v6u/focused-final2.log` |
| compileall / diff check | 均 exit=0 | `/tmp/v6u/compileall.log`、`/tmp/v6u/diff-check.log` |

Plain 的 48 skips 均沿用原证据门禁（未设置 fixture/database/probe 路径）；不代表已完成真实
模型 smoke。本阶段未验证 openai provider 的真实 websocket 行为、真实计费及无输出 cap 的
实际风险。旧归档未删除，cycle.py 未修改，未 commit/push。

Configured suite 已消费全部 48 项 plain 中缺少配置而跳过的证据检查，无新增 skip；分类报告为
`/tmp/v6u/classification-verified.json`。长耗时来自完整物理/恢复/数据与二进制证据核验；
期间仅对 sealed database 做只读预读取，没有修改 fixture/database 或减小断言范围。

## 编排者独立验收（2026-10-19）

验收不采用上文 Codex 的探针与套件结果，全部在本机重跑；真实模型请求 0。

- **模型改为 `gpt-6.1-sol`**（用户决定）。用 `scripts/freeze_model_catalog.py` 从本机 Codex 模型缓存派生
  `/workspace/v6-mac-env/work/official/catalog-gpt-6.1-sol.json`，SHA-256
  `d5ec7a2ed2ca98f8308ecbf08da289efa33e2b6861566a80b9b5d93aba8d484b`；只含 `models` 一行，六处修改均已生效；
  context_window 500000、max_context_window 872000；reasoning 取冻结规则的 `medium`。
- **官方探针 18/18 PASS**（`--model gpt-6.1-sol`，context 872000），输出 `/workspace/v6-mac-env/work/official/probes-sol`。
  逐条读原始 `requests.jsonl` 复核，不依赖 `check.json`：所有请求 model=`gpt-6.1-sol`、effort=`medium`；MCP 恰为
  `mcp__harness_v6` 下 3 个工具加 3 个顶层资源工具；single_action 零工具；没有 `additional_tools`。
  资源 read/list/templates 调用后 `abort.json` 写出、请求数为 1，之后没有请求；超限 Harness 调用（上限 1）请求数 2。
  `single_tool_rejection` 在 2 s 墙钟内发出 11 次请求，证实幻觉工具名只受墙钟约束。
  `rollout_budget` 打开时首个请求多出 `<rollout_budget>…</rollout_budget>` developer 消息，故保持关闭。
- **幻觉工具循环的处理**：用户决定保持现状，只靠墙钟 300 s 和 `unknown_usage_cap=2`，不打开 `rollout_budget`。
  被宿主中止的会话为 `process_failed` + `usage_unknown`，不采纳；每个会话的输出目录都是新建的，不会读到旧标记。
- **configured 套件**（探针目录指向 `probes-sol`）：**673 passed，38 subtests passed，0 failed，0 skipped**；
  `pytest -n 4` 用时 1540.96 s。
- `compileall`、`git diff --check` 通过。
- **为什么慢**：容器 cgroup 内存上限只有 8–10 GB（宿主显示 16 GB）。测试进程峰值约 1.2–2 GB，测试反复整表读取
  1 GB 的 `contexts.sqlite`，文件缓存也计入上限。内存一紧，数据库就被挤出缓存，变成反复读慢磁盘（单个进程实际读盘
  12.8 GB）。用 10 个进程时累计 15 次 OOM kill，xdist 报 "node down"；这不是测试之间互相冲突。4 个进程时没有新的 OOM。
  最慢的两项是 `test_ab_comprehension.py::test_configured_real_generation` 957 s（用真实封存快照生成题集，不调用模型）
  和 `test_run_cli.py::test_configured_cli_fake_crash_resume` 916 s。
