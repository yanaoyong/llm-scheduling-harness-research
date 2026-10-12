# 真实模型通道与隔离

本实验通过现有 ChatGPT 登录运行 Codex CLI，不将交互登录当作 API Key，不读取、复制或输出 OAuth token。接口为 `src/model_transport.py:call_model(prompt, schema, run_dir, config, resume=False)`；返回值的 `output` 是模型 JSON 决策，调度器只执行预定义的白名单动作。transport 不包含求解器或排程策略。

## 已验证版本

- 可执行文件：`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex`。
- 本机版本：`codex-cli 0.162.0-alpha.2`，来自已安装的 ChatGPT 桌面应用；无全局软件升级。
- 模型：`gpt-6-astra`，推理配置：`medium`；模型具体服务端快照未返回，未知。
- 使用 `--json --ephemeral --ignore-user-config --ignore-rules --sandbox read-only --output-schema`，用户数据通过标准输入传入，无 shell 插值。
- CLI 沿用自身认证存储。代理默认 `http://127.0.0.1:7897`，可通过 `ModelConfig.proxy` 配置。该端点不是模型凭据。

`codex` 命令在 PATH 中对应旧版 0.147.0，第一次真实探测被服务端以 HTTP 400 拒绝：`gpt-6-astra` 要求新版 CLI。该失败在 `runs/development/channel_probe` 完整保留。第一次 transport 曾误把 `item.error` 提示事件归为工具事件；实际根因是 CLI 版本。此分类问题已修复，原始文件不改写，独立诊断见该目录 `diagnosis.json`。

第二次 `channel_probe_current_cli` 真实推理成功，约 35.19 秒，input 4535 / cache 0 / output 223，但其默认控制工具仍含多 Agent 能力，不能作为最终隔离配置。

第三次 `channel_probe_isolation` 通过更新隔离配置成功，约 31.63 秒，input 4418 / cache 0 / output 191，其中 reasoning output 94、cache write 0；没有任何原生工具调用事件。以上均为开发通道验证，不能计为排程验收成功。

## 隔离的实际边界

每次调用创建空的 `isolated-cwd`，模型只接收当前实例和该方案当前运行提供的提示词；不传递 A/B/C 其他结果或参考答案。项目文档读取预算为 0，禁用 host skill discovery，同时设置技能目录禁用和极小目录预算。禁用 Apps、plugins、remote plugins、MCP 配置、shell_tool、unified_exec、浏览器、计算机、图像、workspace dependencies、memory、hooks 和 web search。清除继承的 `CODEX_*` 会话环境变量（`CODEX_HOME` 除外）。

新版 GPT-6 模式仍显示 `functions.exec/wait/request_user_input(_async)` 和部分 `collaboration.*` 控制工具，**因此不声称工具清单完全为空**。真实探测的模型自报 `functions.exec` 下只描述 `tools.apply_patch` 与 `tools.clock__curr_time`，文件读取、Shell、网络、Web、MCP 能力列表为空；该枚举是模型自报，需结合以下配置与实际事件理解：

1. `code_mode_host=false`，CLI 事件明确报告 code mode unavailable / fail closed。
2. `read-only` 沙箱，`approval_policy=never`；残余 apply_patch 不具备写入许可。
3. `features.multi_agent_v2={enabled=false,max_concurrent_threads_per_session=1,wait_agent_enabled=false}`。新版模式不能仅依赖普通 `agents.max_*`，必须限定结构化字段。只读 `debug prompt-input` 的实际输出确认总并发槽为 1，包含当前根 Agent；模型也确认该限制。因此不能派生有并行运行能力的子 Agent。每次运行全新 ephemeral 会话，没有可消息联系的既有子 Agent。
4. transport 审计每条 JSON 事件，只允许 `agent_message`、`reasoning`、`error` 消息项；任何原生工具或其他执行项均使运行成为 `native_tool_isolation_violation`，不得计入成功。

`debug prompt-input` 只审计输入消息，不能直接证明完整工具 schema。其输出在 `channel_probe_current_cli/prompt-input-audit-bounded-agent2.json`。本实验的原生工具“零调用”结论以每次 `events.jsonl` 为依据，而非仅相信模型自述。

CLI 自己可能维护用户目录中的认证、全局模型缓存和临时启动状态；这些不是实验输出，且没有复制到实验目录。实验请求、事件、排程等产物全部保存在用户指定工作目录内。每次 CLI 的 `log_dir` 与 `sqlite_home` 指向当前运行 `runtime` 目录。

## 限额、计量和恢复

每次 `call_model` 只有 1 次 CLI 尝试，无自动重试，默认硬超时 240 秒；probe 用 180 秒。超时终止整个进程组，再写失败结果。关闭 CLI `unbounded_connection_retries`；底层 HTTP 尝试次数仍不能从事件可靠获取，标为未知。步骤数和总调用预算由上层实验运行器限制，transport 不独自展开循环。

逐次保存 `prompt.txt`、`schema.json`、`system-instructions.txt`、无凭据的 `command.json`、`request.json`、`events.jsonl`、`stderr.log`、`final.txt` 和 `result.json`。后续调用记录 CLI 版本、模型名、推理等级、返回码、失败类型、UTC 开始/结束时间、wall time、已尝试模型调用数、各类已报告 token。

`model_elapsed_seconds` 是整个 CLI 模型调用阶段耗时，含启动/网络，不是纯服务端推理时间。`pure_model_seconds`、实际货币账单和 HTTP 次数均为 `null`，不得将其视为 0。`cached_input_tokens` 是输入的一部分，不能再与输入相加计总输入。reasoning tokens 是输出细分项，不能与 output 再相加。没有 usage 的失败保持未知。

`resume=True` 仅回放同 prompt/schema/config 指纹下已写入的 `result.json`，不重新请求模型。默认禁止覆盖任何已完成或中断的尝试；修订/重试必须创建新目录，保留旧失败。中断但尚无 `result.json` 的目录会报错，要求先诊断再显式新建尝试。

## 命令

所有命令从 `__LOCAL_PROJECT_ROOT__` 执行。回放已完成的真实探测，不消耗模型调用：

```sh
python3 experiment_round1/scripts/probe_model.py --run-dir experiment_round1/runs/development/channel_probe_isolation --resume
```

新鲜真实探测（1 次调用，最长 180 秒；目录必须未使用）：

```sh
python3 experiment_round1/scripts/probe_model.py --run-dir experiment_round1/runs/development/channel_probe_recheck
```

在 Codex 桌面受限沙箱内，CLI 管理本地 app-server 的启动可能因 OS 权限被拒绝。本轮真实调用经外层 exec 工具 `require_escalated` 批准执行，内层模型仍使用上述只读、无 Shell 等隔离配置。普通终端运行无须使用该工具参数。

调用示例：

```python
from pathlib import Path
from model_transport import call_model, ModelConfig
r = call_model(prompt, action_schema, Path(run_dir) / 'model_call_001',
               ModelConfig(model='gpt-6-astra', reasoning_effort='medium', timeout_seconds=240))
if r['status'] == 'success':
    action = r['output']  # 上层再次检查动作 schema 和业务约束后执行
```

## 依据

[OpenAI 非交互模式文档](https://learn.chatgpt.com/docs/non-interactive-mode)说明结构化输出、JSON 事件、ephemeral 会话及忽略配置选项；[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)说明技能、沙箱等配置。具体本地版本与有效能力以此次 CLI help、真实探测和保存的事件为准。
