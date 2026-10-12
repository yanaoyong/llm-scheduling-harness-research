# Codex Workflow 运行器

用 Codex CLI 执行与 Claude Workflow 相同形式的编排脚本。复用
`m05-web-research.js` 的五阶段流程，无需把它另写成一份 Codex 专用调研脚本。
这是一项命令行运行能力，不会给桌面会话自动注册名为 `Workflow` 的工具。

依赖：Node.js 22+、已登录且支持所选模型的 Codex CLI。
先执行 `codex login status` 检查当前登录。运行器复用 CLI 登录及用户配置，
不读取、复制或另存登录密钥，也不需要新的 OpenAI API key。

本机 PATH 的 CLI 为 0.147.0，它拒绝当前配置的 gpt-6-astra（要求更新 CLI）；
桌面应用附带的 0.162.0-alpha.2 已通过真实结构化调用测试。可以显式追加
`--codex-bin /Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`。
运行器不会自行升级 CLI 或更改全局模型配置。

## 使用

在 myharness 仓库根目录运行：

```sh
node plugins/harness-core/scripts/codex-workflow.mjs \
  --name m05-web-research \
  --args '{"question":"大模型如何辅助制造业生产排程？","tier":"inherit","angles":2,"votes":1,"urls":4,"claims":6}' \
  --concurrency 2 --max-agents 24 \
  --output /tmp/scheduling-research.json
```

`tier:"inherit"` 是明确选择使用 Codex 已配置的模型，**不保证低成本**。
M0.5 原脚本要求先作成本选择：只有 question、没有 tier/profile 时，在
启动 Agent 前返回 `needsCostDecision`，进程退出码为 3。

脚本路径也可显式指定，Agent 工作目录与脚本目录彼此独立：

```sh
node /path/to/myharness/plugins/harness-core/scripts/codex-workflow.mjs \
  --script-path /path/to/myharness/plugins/harness-core/workflows/m05-web-research.js \
  --cwd /path/to/your/project \
  --args-file /tmp/research-args.json
```

消费项目已有 `.harness` 镜像时，可以使用
`node .harness/scripts/codex-workflow.mjs --name m05-web-research ...`。
脚本、库文件和说明分别受已有 sync-manifest 的 `scripts/*`、`workflows/*`
覆盖。运行器本身不会执行 Claude 的 SessionStart hook；镜像安装/刷新仍由
项目现有流程负责。

`--args` 接受 JSON 对象、JSON 字符串或裸问题文本。`--args-file` 与之互斥，
读取相同格式。疑似 JSON 但语法错误会直接失败，不会静默当作问题。
查看完整参数：`node plugins/harness-core/scripts/codex-workflow.mjs --help`。

## 模型档位

原脚本中的 `haiku / sonnet / opus` 是 Claude 名称，不能直接传给 Codex。
使用 `profile:"lite"` 或 `tier:"tiered"` 时，应通过 `--model-map FILE`
提供 JSON 对象，把实际使用的档位映射到账号可用的 Codex 模型 ID。
映射文件中的实际模型由使用者根据自己的可用模型和成本预算填写；运行器
不内置跨厂商的价格或能力等价关系。缺少映射属于配置错误，退出码 1，
不会被伪装成网络不可用或 L3 降级。

`--model ID` 设置未指定模型的 Agent 默认值；不传时沿用 CLI 配置。
脚本原输出的 `models` 保留其档位标签；`runtime.json` 中每个 Agent 的
`model` 记录实际传入的模型，未指定时为 null，表示 CLI 配置默认值。
不推测其实际模型名。原脚本的 Verify/Synthesize 最低档规则仍保留，但
跨厂商的真实能力和成本取决于所提供的映射。

## 兼容接口

| 注入接口 | 行为 |
|---|---|
| `args` | JSON 参数或问题字符串 |
| `agent(prompt, options)` | 一个独立、临时的 `codex exec` 会话；支持 model/label/phase/schema；结构化结果直接返回对象，无 schema 时返回文本；调用失败返回 null |
| `parallel([() => ...])` | 按输入顺序返回结果；可嵌套；并发限制施加在 Agent 进程上，避免嵌套锁死 |
| `pipeline(items, ...stages)` | 每个输入独立向下游推进，快输入无需等待慢输入；最终保持输入顺序 |
| `phase(title)` | 阶段日志；Agent 自身的 phase 覆盖当前阶段 |
| `log(message)` | 运行日志 |
| `export const meta = ...` | 存入 runtime.json 的 workflow 元数据 |

支持脚本顶层 await/return。只支持这一元数据导出形式，不支持 import、
其他模块导出或整个 Claude 宿主 API。脚本必须是受信任的本地脚本；
async/VM 包装用于接口兼容，不是执行不可信 JS 的安全边界。

## 结构化输出与失败

CLI 使用 `--output-schema` 和 `--output-last-message`。适配器把原有 schema
里的可选字段转换为 strict schema 所需的“必填但可为空”，并添加对象
`additionalProperties:false`、补全 primitive enum 的类型。读取结果时，只
去除适配器为可选字段添加的 null，再校验原 schema。

支持的 schema 子集见 `scripts/lib/workflow-schema.mjs`；例如 `$ref`、format、
oneOf 和开放字典未实现，会在推理前明确失败。不会忽略未知约束，也不会
把不合法的 JSON 改造成合格结果。

成功必须同时满足进程退出 0、存在 `turn.completed`、未出现 error/turn.failed、
最终结果通过校验。模型调用失败、schema 返回不合格、超时都返回 null，
原 M0.5 将其作为弃权，保留 quorum 和合成失败时的救援行为。配置错误、
Agent 总预算超限和用户取消会使整次运行失败或取消。

`--max-agents` 限制整个运行的 Agent 调用数；`--concurrency` 限制同时运行数；
`--timeout-ms` 限制单个 Agent（含工具）的时间，默认五分钟。
**原 M0.5 的 urls 参数不是绝对抓取上限**：高相关结果仍可超过该值。
需要硬预算时应同时设置 max-agents；越界会显式失败，保留已有取证日志。
本次未修改原脚本的检索或预算语义。

## 联网、权限与日志

默认通过全局 `codex --search exec` 开启原生实时联网。
适配提示把脚本中的 WebSearch/WebFetch 对应到原生 web_search 的搜索和打开
URL 操作。`--no-web` 关闭实时联网并要求 Agent 不声称做过实时检索。
是否真的检索以及打开了哪些页面，应检查每个 Agent 的 events.jsonl；
仅仅得到一个 JSON 结果不构成来源真实性证明。

默认 `--sandbox read-only`、`-a never`，权限不足会返回错误；可显式选择
`--sandbox workspace-write`。不提供绕过沙箱或忽略项目规则的开关。
工作目录仍决定 Codex 加载的项目指令。每个 Agent 是独立会话，不共享
隐藏历史；上下文通过编排脚本的显式 prompt/结果传递。

stdout 只输出工作流返回 JSON；stderr 输出进度和取证目录。
默认取证目录为 `.harness/metrics/codex-workflow/<时间-随机ID>/`，在本仓现有
metrics 忽略范围内。`--run-dir` 可指定一个尚不存在的新目录，防止覆盖旧运行。

- `result.json`：原工作流的返回值。
- `runtime.json`：状态、参数、每个 Agent 的模型/状态/用量和汇总用量。
- `events.jsonl`：运行器阶段与进程事件索引。
- `agents/0001/...`：CLI 原始事件、strict schema、最终消息、结果、stderr。

这些文件可能包含研究内容及工具输出，目录默认权限 700、文件 600。
取消使用 Ctrl-C 或 SIGTERM；会停止活动进程组及排队 Agent。
本次运行没有跨进程恢复/断点续跑能力。

| 退出码 | 含义 |
|---|---|
| 0 | completed：运行正常完成；研究本身仍可能没有可确认的结论 |
| 1 | 配置、脚本或整次执行失败 |
| 2 | partial/degraded：部分 Agent 失败或脚本明确能力降级；检查结果和日志 |
| 3 | needs_cost_decision：M0.5 需要先选择成本档 |
| 130 | 用户取消 |

这是 M0.5 的 B 类外部检索运行器，不会单独生成完整 M0.5 dossier/open-questions，
也不会替代 A 类内部源/C 类用户材料探测和独立评审；这些仍由 M0.5 Owner
按 research-discovery 技能完成。

## 验证

```sh
node --test tests/harness_tools/codex_workflow.test.mjs
```

测试使用模拟 Codex 子进程，不联网、不消耗模型额度，覆盖原版 M0.5 的
五阶段执行、嵌套并发、无屏障流水线、JSON/schema、退出状态、模型映射、
成本闸、失败弃权、超时取消，以及符号链接启动。
真实 CLI 联网验证属于另行执行的 smoke，不由这些测试假冒。

2026-10-08 验证记录：20 项 Node 运行器测试通过；新增 pytest 入口与原有
M0.5 cost/entry/sequence 契约测试共 33 项通过。真实 CLI 结构化 smoke
返回 `{"value":"ok"}`。随后通过原版 `m05-web-research.js` 完成官方
OR-Tools Job Shop 文档的五阶段联网 smoke：Scope/Search/Fetch/Verify/Synthesize
各一个 Agent，全部 completed，退出码 0；搜索、抓取和校验 Agent 的原始
事件包含真实 web_search 操作。此 smoke 只验证运行器，不等于完成智能排程
领域的 M0.5 调研。

本次本机取证目录：`/tmp/codex-workflow-live-smoke-app-20261008/` 和
`/tmp/codex-workflow-live-m05-20261008/`（临时目录，需长期保留时另行归档）。

实现依据：OpenAI 官方 [Non-interactive mode](https://developers.openai.com/codex/noninteractive/)
和 [CLI reference](https://developers.openai.com/codex/cli/reference/)。
