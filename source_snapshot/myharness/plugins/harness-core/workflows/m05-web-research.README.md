# m05-web-research 工作流 · 归档文档

Codex 用户可用同一脚本执行调研，见 [Codex Workflow 运行器](codex-workflow.README.md)。

> 归档对象：`.claude/workflows/m05-web-research.js`（原 `deep-research.js`，本卡 `git mv` 改名 · 保历史）
> 分支：`change/feat-m05-tiered-research-20260626`
> 性质：Claude Code **Workflow**（多 Agent 编排脚本，非 plugin、非 SKILL.md），属工具/配置类（L4）资产，不进 Harness 10 阶段业务流程。

---

## 1. 这是什么

`m05-web-research` 是一个**多 Agent 深度网络调研工作流**：给定一个研究问题，自动把它拆成多个搜索角度，并行检索网络、抓取来源、抽取可证伪事实（claim），对每条事实做对抗式 N-vote 校验（含弃权 quorum），最后把存活的事实合成为一份**带引用的报告**。

它在体系中的定位 = **M0.5 外部 web 调研引擎的 L2 档**（厂商层），且按 **ADR-010** = M0.5 外部 web 调研的**主引擎**：内置 L1 `deep-research` 已**弃用**（成本高 + 模型不可控 + 与项目自建 L2 命名碰撞），三级降级链由 ADR-008 的 `L1→L2→L3` **收敛为 `L2(主)→L3(降级)`**。改名 `m05-web-research` 即为消除命名碰撞——M0.5 绑定按独立名/scriptPath 调用，**永不再路由到被遮蔽的内置 `deep-research`**（AC-1）。

> 关联：`CLAUDE.md`「M0.5 调研引擎绑定」厂商层节 + ADR-008 / ADR-009 / **本卡新增 ADR-010**。

---

## 2. 设计来源

改编自 **bughunter** 工作流的 5 阶段流水线架构，把底层取证工具从 `git`/`grep` **替换为 `WebSearch`/`WebFetch`**。骨架：

```
分解 → 并行取证 → 抽取候选 → 对抗校验 → 合成
```

本卡（feat-m05-tiered-research）以**内置 L1（349 行）架构为范本**回填了现 L2（原 152 行）缺失的五项工程改进（见 §3.1），并叠加**成本分层控制**（模型档 + 扇出旋钮 + lite profile · 见 §4）与**能力探测/中立降级**（§5）。

---

## 3. 架构：5 阶段流水线

| # | 阶段 | 做什么 | 模型档键 |
|---|---|---|---|
| 1 | **Scope** | 把问题拆成 N 个互相独立的搜索角度 | `Scope` |
| 2 | **Search** | 每角度一个 WebSearch Agent（**pipeline 无屏障**，边出边喂下游）| `Search`（机械）|
| 3 | **Fetch** | URL 规范化去重 + 预算护栏后 `WebFetch`，抽取可证伪 claim（含直接引文 + 重要度）| `Fetch`（机械）|
| 4 | **Verify** | 每条 claim 起 N 个对抗校验 Agent（"尽力 REFUTE"）；多数票杀 + **弃权 quorum** | `Verify`（推理 · floor=Sonnet）|
| 5 | **Synthesize** | 只用存活 claim 合成带引用报告（执行摘要 / 发现 / caveats / open-questions）| `Synthesize`（推理 · floor=Sonnet）|

### 3.1 五项范本移植（AC-3）

| # | 改进 | 行为 |
|---|---|---|
| 1 | **URL 规范化去重** | `normURL`（去 `www.` / 去尾斜杠 / 小写）跨角度去重，`seen` Map 随 pipeline 累积 |
| 2 | **fetch 预算护栏** | `fetchSlots = MAX_FETCH` 到上限即停，丢弃的低相关候选进 `budgetDropped` 并 `log()`——**不静默截断** |
| 3 | **对抗校验弃权 quorum** | null 票 = abstain（既不算支持也不算反驳）；**存活须 `valid ≥ QUORUM` 且 `refuted < REFUTE_TO_KILL`**——全弃权 ≠ 放行 |
| 4 | **各阶段救援返回**（salvage）| Scope 空 / 全弃权 / 全被驳 / synth 失败：均**返回已验证 claim + 部分结果**，不整盘抛丢 |
| 5 | **search→fetch pipeline 无屏障** | 用 `pipeline(angles, searchStage, fetchStage)` 而非 `parallel` 屏障；Verify 前的屏障是**有意**保留（claim 池须聚齐再排名校验）|

---

## 4. 成本控制（核心诉求）

### 4.1 模型分层开关（R3a · AC-5）

逐阶段 `agent({model})` 可覆盖。**默认厂商中立**：不传 `tier` 时 `agent()` **一律不传 `model`**，子 Agent **继承会话模型**（GLM 等异构环境可跑）。模型 id 字面**只集中存在于脚本里一处** `TIER_PRESETS`（可覆盖 config-data），`agent()` 调用处只引用解析后的 `MODELS[stage]` 变量，故 AC-4 中立 grep 干净。

经 args 传 `tier`：

| `tier` 取值 | 效果 |
|---|---|
| `'haiku'` / `'sonnet'` / `'opus'` | **统一档**：全阶段同档（但 Verify/Synthesize 受 floor 约束，见下）|
| `'tiered'` | **分层档**：机械阶段 Scope/Search/Fetch = haiku，推理阶段 Verify/Synthesize = sonnet |
| `{ Search:'haiku', Verify:'sonnet', ... }`（对象）| **细粒度**：按阶段键覆盖；缺省阶段继承会话模型 |
| 不传 | **默认中立**：全阶段继承会话模型 |

**R-风1 铁约束（floor）**：**Verify 与 Synthesize 绝不可降到 haiku**——对抗校验 Agent 降到最廉档会丢失证伪力（劣质 claim 蒙混过关），合成质量也崩。代码层强制：`buildTierMap` 把任何解析为 `haiku` 的 Verify/Synthesize **兜回 sonnet 并 `log()`**，即便调用方显式传 `{Verify:'haiku'}` 也兜回。故 `tier:'haiku'` 统一档下，Verify/Synthesize 实际仍跑 sonnet（这是 floor 的有意结果 · 见 §7 偏差说明）。

**成本测量法（AC-5）**：同一问题 / 同一扇出，`tier:'tiered'` vs `tier:'opus'`（或默认全 Opus 会话），对比 `stats` 与 transcript 的 token A/B，量化降幅。

### 4.2 扇出旋钮（R3b · AC-6）

`angles / votes / urls / claims` 从 args 读、即时生效。**默认（FULL 档 · OQ-4 锁定）**：`angles:3, votes:3, urls:8, claims:12`。

> **args 传参正确姿势（AC-6 · 必读）**：`args` 须传**真实 JSON 对象** `{ angles:1 }`，**不是 JSON 字符串** `"{\"angles\":1}"`。脚本侧已对字符串入参健壮兜底（leading-`{` 串尝试 `JSON.parse`、否则当裸问题串），但调用方仍应传对象。传 `{angles:1}` **真的只跑 1 角度**（修复上轮"args 当字符串导致旋钮全失效跑默认"的坑）。

### 4.3 lite profile（R3c · AC-6）

传 `profile:'lite'`：**极小扇出** `angles:2, votes:1, urls:4, claims:6` + **分层档模型**（机械 haiku + 推理 sonnet）。供 M0.5 档2 RUN_LITE 按需调用。显式旋钮入参仍可逐项覆盖 lite 基线。

> **对 spec R3c 字面的修正**：spec R3c 原写 lite = "全机械模型"，与 **R-风1**（Verify 不可降 haiku）冲突——**以 R-风1 为准**：lite 的 Verify/Synthesize 仍 = sonnet，只压扇出不压 verify 档（见 §7 偏差说明）。

---

## 5. 能力探测 / 中立降级（R2 · AC-4）

WebSearch/WebFetch 不可用、或 structured-output（schema）不可用时**优雅降级**，返回**显式 degraded 结果**（带 `reason`），**不抛崩、不假绿、不伪造引擎档/coverage**：

| 触发 | 信号 | 返回 |
|---|---|---|
| schema/模型不可用 | Scope agent 抛错或返回空 angles | `{degraded:true, reason:'…structured output…unavailable', stage:'Scope'}` |
| WebSearch 路径断 | 全角度零 URL（`seen.size===0`）| `{degraded:true, reason:'…WebSearch (or websearch-proxy…) may be unavailable'}` |
| WebFetch 路径断 | 全部抓取失败（每源 0 claim 且 unreliable）| `{degraded:true, reason:'…WebFetch may be unavailable'}` |

degraded 结果显式声明 `note: capability-degraded …caller must map to explicit_na, never report "covered"`——调用方（M0.5 出口门禁）据此落 B 源 `coverage=explicit_na`，**绝不谎称 covered**。

### 5.1 对 websearch-proxy 的依赖（保留 L2 既有说明）

`m05-web-research` 经 **WebSearch/WebFetch** 取外部覆盖。在**第三方中转网关**环境下，server-side `WebSearch` 需经自研 **websearch-proxy**（拦截补搜代理 · Tavily 后端）改写补搜方能非空召回（见 **ADR-009**）；**直连 Anthropic 环境** WebSearch 原生可用、**无需代理**。中转环境若未起 websearch-proxy → WebSearch 空召回 → §5 能力探测显式降级（不假绿）。本卡**不改 websearch-proxy 本体**，仅声明依赖与降级关系。

---

## 6. 入参（args）与产物

`args` 可是裸字符串问题、或对象 `{ question, angles?, votes?, urls?, claims?, profile?, tier? }`。

| 字段 | 默认 | 含义 |
|---|---|---|
| `question` | （必填）| 研究问题；裸字符串时即问题本身 |
| `angles` | `3`（lite `2`）| Scope 拆出角度数 |
| `votes` | `3`（lite `1`）| 每条 claim 的对抗校验票数 |
| `urls` | `8`（lite `4`）| Fetch 阶段最多抓取的去重 URL 数 |
| `claims` | `12`（lite `6`）| Verify 阶段最多校验的 claim 数 |
| `profile` | —（`'lite'` 触发削减档）| 预置档：lite = 极小扇出 + 分层模型 |
| `tier` | —（继承会话模型）| 模型档：`'haiku'`/`'sonnet'`/`'opus'`/`'tiered'` 或细粒度对象 |

### 调用示例

```js
// 最简：裸字符串（继承会话模型 · 全中立）
Workflow({ name: 'm05-web-research', args: 'What is WebGPU and how does it differ from WebGL?' })

// 分层档 + 经济扇出（机械 haiku + 推理 sonnet）
Workflow({ name: 'm05-web-research', args: { question: '…', tier: 'tiered', angles: 3, votes: 3 } })

// lite 档（M0.5 档2 RUN_LITE）—— 传真实对象，不是 JSON 字符串
Workflow({ name: 'm05-web-research', args: { question: '…', profile: 'lite' } })
```

产物（`return`）含 `question / engine / profile / knobs / models / summary / findings(带 confidence+sources) / refuted / sources / stats`；degraded 时返回 `{degraded:true, reason, note, …}`。

---

## 7. 偏差说明（供阶段4 评审 / Owner 确认）

| # | 偏差 | 理由 |
|---|---|---|
| D-1 | **R3c lite 修正**：spec 写 lite "全机械模型"，实现为 lite 的 Verify/Synthesize 仍 = sonnet（不降 haiku）| 与 R-风1 铁约束冲突，**以 R-风1 为准**——证伪/合成不可降最廉档 |
| D-2 | **统一档 `tier:'haiku'` 的 Verify/Synthesize 仍跑 sonnet** | R-风1 floor 在代码层恒强制（即便显式请求 haiku 也兜回），与 AC-5"全 Haiku 时全部 Haiku"字面有张力；floor 是铁约束，取 floor 优先并 `log()` 留痕 |

---

## 8. 注意事项

- **`node --check` 误报**：standalone `node --check` 会报 `Illegal return statement` / 顶层 `await` 错——**误报**。Workflow 脚本运行在 runtime 注入的 async 包裹里，顶层 `return`/`await` 与注入全局（`agent`/`parallel`/`pipeline`/`phase`/`log`/`args`）合法。本卡用"包进 async Function 再解析"做真正语法校验（已通过）。
- **不进门禁**：本工作流是旁路工具，**不进任一 Harness 阶段门禁判定式、不夺裁决权**（ADR-005）。
- **API key**：底层引擎/检索 key 走环境变量、不入库（C-8 / CODE-005 / NFR-3）。
- **落点 / C-1 边界**：作为 Claude Code 工具资产落 `.claude/workflows/`，与 `.harness/`（厂商无关抽象契约）隔离——具体引擎/后端名（`m05-web-research` / `deep-research` / `Tavily`）只许出现在厂商层（本脚本 + CLAUDE.md 厂商层节），`.harness/` 抽象契约层零硬引用（ADR-008 §3.1 / C-1）。
