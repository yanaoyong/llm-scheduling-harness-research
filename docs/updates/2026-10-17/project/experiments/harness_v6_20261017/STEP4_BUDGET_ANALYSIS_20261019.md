# 步骤 4：MCP 三轮预算归因与参数候选（2026-10-19）

> 当前状态（2026-10-19）：[S0 阶段归档](../../../../2026-10-19/README.md)。离线 660 项及 38 子测试通过；真实 A/B 已完成，正式轨迹 0/6，已按 E1 smoke 次数上限暂停。下文保留各自日期的历史记录，旧的“零真实调用”等表述不代表当前状态。

本次仅分析离线证据，并重放真实 `FactReader` 产物到固定原生 Codex 的回环 mock。
**真实模型调用 0；生产代码、登记模板、验收逻辑及既有失败结果均未修改。步骤 4 仍未完成。**

## 结论

三轮超限的主因是**完整工具结果在后续请求中反复携带**，静态系统说明和工具 schema 只占很小部分。
现有压力样本确实有保守放大，但不能把它全部视为假警报：生产合法的 512 实体完整读取，连续三次也超过 100 万。
因此，不能只把整状态压力换成较小示例、只统计最后一次输入、使用缓存折扣，或把上下文配置填得更大后宣称通过。

下一轮可直接执行的离线候选是：**context=1,000,000，reserve=10,000，3 次工具调用，样本每次 128 个实体，wall=300 s，累计 session cap=3,000,000**。
本次已跑通该候选的原生重放。这里的 128 是诊断样本规模，**不是已实施的生产限制**；不能直接把该结果填进正式登记。

## 1. 原三轮压力的精确归因

基准为 `public-1602 / explicit`，计数保持既有 `measure_request_overhead.py` 的 o200k、完整序列化请求口径。
三轮工具调用产生四个模型请求。快照在每个请求中恰好出现一次，没有被重复插入多份。

| 请求 | 已累积工具结果 | 完整输入计数 | 相比上轮增长 |
|---|---:|---:|---:|
| 1 | 0 | 254,425 | — |
| 2 | 1 | 855,695 | 601,270 |
| 3 | 2 | 1,456,961 | 601,266 |
| 4 | 3 | 2,058,231 | 601,270 |

最后一个请求按固定顺序做消融，四项相加精确等于总量（BPE 边界效应计入对应差值）：

| 来源 | token |
|---|---:|
| 完整 explicit 快照 | 218,255 |
| 首请求非快照开销，包括快照 JSON 转义增量 | 36,170 |
| 三个完整工具 output 字符串的增量 | 1,803,534 |
| function call、历史结构等其余增量 | 272 |
| 合计 | 2,058,231 |

工具 output 占最后一个请求 **87.6%**，占其非快照开销约 **98.0%**。
单独计量的 system/instructions 为 3,107、工具 schema 为 1,996；删除它们也不能解决百万级缺口。
工具 schema 还出现在完整快照内，这是既有生产展示合同，本次保留。

跨格式取共同最大 overhead=**1,843,569**，再与最大完整快照 218,255 和输出预留 10,000 相加，
现行验收要求仍为 **2,071,824**。dense 仅降低快照成本，工具回包相同，不能消除累积增长。

四请求的累计输入为 **4,625,312**；若每次都预留 10,000 输出，累计规划量为 **4,665,312**。
`session_budget.token_cap` 是累计 input+output，不能与单请求 context 或单次输出 reserve 混用。
缓存计费折扣不会释放上下文，也不降低该累计原始 token 上限。

## 2. 生产开销与压力放大分别来自哪里

现有 mock 每次把 `decode_snapshot(...)[1]` 的**整个当前状态对象**作为 `read_entities` 结果，连续返回三次。
它不是“read → validate → submit”三步工作流。调用参数仅有 `{"kind":"operations"}`，
生产 `FactReader.read` 要求 IDs 或目录 cursor，因此会拒绝该参数：`Use exact IDs or a directory cursor`。

生产接口允许完整字段的 IDs 查询或分页查询，单次最多 512 个实体；原始顺序分页、显式过滤及缺失 ID 标记均保留。
本次从同一 G0 / 三个公共态重建事实，按既有 10 位浮点快照规范逐字段核对：
**重建状态与 explicit/dense 解码结果一致**。生产 FactReader 保留自身精度和全部版本元数据，没有拿快照表格代替生产结果。

| 状态 | 整状态压力回包计数 | 最大观察到的合法 512 实体回包 | 压力 / 合法回包 |
|---|---:|---:|---:|
| G0 | 372,916 | 410,486 | 0.91 |
| public-702 | 588,543 | 422,712 | 1.39 |
| public-1182 | 599,958 | 423,687 | 1.42 |
| public-1602 | 601,179 | 420,526 | 1.43 |

这里计数是 output 字符串再次进入完整请求 JSON 后的计数，尚不包括 function call 参数。
合法回包均来自真实 FactReader，取每类实体中按序列化大小选出的最多 512 个显式 IDs，全部字段、哈希及版本信息保留；
另测了全部固定源序分页。按大小选择只用于离线压力采样，未引入生产排序或调度规则。
这不是对任意未来状态、任意查询字符串和错误详情的数学上界。

**压力放大有两层：**

1. 完整快照本来使用表格/字典等紧凑表示；mock 将当前态展开为重复键的对象，再完整回传。
   public-1602 的展开 JSON 为 414,796 tokens，主要是 upcoming_operations 214,576、unreserved_ready 127,050、machines 73,057
   （这些分项独立计数，有少量边界差异，不能当作精确加总）。
   冻结公共 ledger 缺少作业开始时间，时间下界较弱，展示约 1,350 条 upcoming，属于样本本身的保守性；本次没有删行或改变窗口。
2. 同一回包原始 JSON 414,796 → Codex output 文本 437,377 → 完整请求内字符串序列化 601,179。
   多层 JSON 转义增加了保守计数。该计数不是服务端真实 tokenizer / 计费 usage，但验收仍沿用原公式，没有扣除这些增量。

**生产本身也有显著成本：**

- 512 工序完整结果保留每实体 source/version/dependency 哈希、original_ref、投影完整性信息，以及 value 内覆盖计划 hash。
  public-1182 中，仅“实体包装元数据相对于仅保留 value 的诊断差值”就有 **137,327** 序列化 tokens。
  这只是归因消融，不是建议删除元数据。
- 同一组 512 工序重复的 eligible_machines 数组，按 value 字段独立计数约 **84,696**；coverage_plan_sha256 约 **18,944**。
- G0 的合法大查询比整状态 mock 更大，证明旧压力输入**不是生产工具返回的严格上界**。
- validate/submit 仅把 violation 详情和 coverage sample 截到 50，并不意味着完整 receipt 有固定小尺寸：
  blocked_queues、absent_operation_tasks、delta/ID 引用仍需覆盖大样本；本次没有用两个小回执替换最重读取来宣称全路径通过。

## 3. 分页规模与容量曲线

保持完整快照、三次工具调用、每请求 10,000 输出预留；同一最重合法结果重复三次。
256/512 为替换原生请求历史中的真实 FactReader 结果后，沿用原测量器的反事实计算；
128 另完成了固定原生 Codex 的实际回环录制。

| 单次实体数 | 共同 overhead | 最大快照 + overhead + reserve | 四请求累计输入 + 四次 reserve | 判断 |
|---|---:|---:|---:|---|
| 128（原生重放） | 388,192 | **616,447** | 1,751,545 | 样本容量通过 |
| 256（反事实） | 717,378 | **945,633** | 2,409,958 | 表面小于 1m，但触及自动压缩边界 |
| 512（反事实） | 1,322,535 | **1,550,790** | 3,620,272 | 超过 1m |
| 既有整状态压力（原生录制） | 1,843,569 | **2,071,824** | 4,665,312 | 保持失败 |

128 重放共 **8 会话、32 次 POST、48 次历史工具结果出现**；输出 text 与生产 FactReader 原始编码逐字节一致，
8 个完整快照 hash 与既有录制相同。只广告生产三个 MCP 工具；没有压缩事件、额外工具或裁剪。
重放通过三次合法 read 查询验证读取负载，不表示生产调度质量或 validate/submit 工作流通过。

这次 mock 的 usage 采用每个完整序列化请求的保守计数，cached=0，原生累计 usage 与各轮求和一致。
它仍是合成 usage；真实服务端 framing、实际 reasoning、认证及模型能力未验证。
先前整状态压力 mock 固定回报 100 input / 10 output，只验证传输和字段预算，不能以“原生进程成功”证明真实自动压缩行为。

## 4. Codex 的真实本地限制

固定二进制：`codex-cli 0.147.0-harness-v6.1`，
SHA256 `7bbee546196b7de63044c52e67982b968975ddcf18a22da2a7e3584fda61097e`。

其源树 `codex-rs/models-manager/models.json` 中，离线标签 `gpt-5.4` 的默认窗口为 272,000，max_context_window 为 1,000,000。
`models-manager/src/model_info.rs` 会将用户窗口配置 clamp 到该最大值；
`protocol/src/openai_models.rs::auto_compact_token_limit` 又将自动压缩阈值 clamp 到窗口的 90%。
默认 effective_context_window_percent=95，因此 capacity 和 compaction 都必须检查。
这些是本次固定本地版本的行为，不是当前在线服务容量或模型选型承诺。

即使指定 `model_auto_compact_token_limit=context+1`，1m 窗口仍有约 900k 的压缩阈值。
256 的末轮输入已经过于接近/超过此界限，不宜作为稳健候选。
把 `--context-token-budget` 填成 2.4m 只能使纯公式检查变绿，不能越过固定二进制的模型元数据上限。

若不改现有 512 契约，观察到的三次最大合法读取至少需要约 **1,723,100** 的有效配置窗口，
才能把上述含 reserve 的需求放在 90% 以内；保留原整状态压力还需要约 **2,302,027**，均未计更多未知内容。
当前 pin 的该模型标签不能提供这两个窗口。不得用虚构模型名或忽略 clamp 完成验收。

## 5. 可执行参数方案及进入正式登记的条件

### 立即可运行：继续离线验证 128 样本

| 参数 | 候选值 / 用途 |
|---|---|
| model | gpt-5.4，仅沿用已验证的离线标签，真实模型待定 |
| context_token_budget | 1,000,000 |
| output_reserve_tokens | 10,000，包含输出及 reasoning 预算 |
| max_tool_calls / 录制工具轮数 | 3 / 3，最多四次请求的当前测试轨迹 |
| 样本读取规模 | 128，完整实体、全部字段；实际生产上限仍为 512 |
| wall_seconds | 300 |
| session_budget.token_cap | 3,000,000，累计原始 input+output，独立于 context |
| 候选 request_overhead 目标 | 500,000：比本次 388,192 留出 111,808；**不写入登记，不替代旧压力最大值** |
| 展示 | 双格式都录制；生产暂保留 explicit，dense 等步骤 5 理解试验 |
| H / Δ / Δ_min | 900 / 60 / 60，沿用对照样本；不据此决定正式 Δ |
| 执行环境 | 固定 binary/hash，独立 HOME/CODEX_HOME，完整 HTTP 历史，禁压缩、禁额外工具 |

若最终能证明完整会话 overhead ≤500,000，则目前最大快照下每请求规划量为 728,255，
距 900,000 仍有 171,745；四请求合计规划上界 2,913,020，小于 3,000,000。
这些是条件计算，不能替代大 delta、实际 reasoning、更大状态和错误回执验证。

复跑命令（同名输出不覆盖；运行前换新的 label / 输出目录）。所有请求只发往 127.0.0.1：

```bash
WORK='__PROJECT_ROOT__/validation/harness_v6_mac_20261018'
V6='__PROJECT_ROOT__/archive/20261012_public_release/docs/updates/2026-10-17/project/experiments/harness_v6_20261017'

# 重新生成状态归因及 128/256/512 的生产结果与反事实预算。
python3 "$WORK/run_step34.py" physical step4-analysis-recheck PYTHON \
  "$WORK/analyze_step4_budget.py" --work "$WORK" --v6 "$V6" \
  --output "$WORK/step4-analysis-recheck"

# 真实 FactReader 完整产物经 mock MCP 重放到固定原生 Codex。
# --page-size 仅选择离线样本，不修改生产 FactReader 上限。
python3 "$WORK/run_step34.py" physical step4-replay-recheck PYTHON \
  "$WORK/capture_step4_reader_replay.py" --work "$WORK" --v6 "$V6" \
  --analysis "$WORK/step4-analysis-recheck" --output "$WORK/step4-replay-recheck" \
  --page-size 128 --context-token-budget 1000000 --output-reserve-tokens 10000 \
  --session-token-cap 3000000 --model gpt-5.4
```

### 正式登记前必须解决

1. **明确保留 512 还是采用更小的生产分页上限。** 如果保留 512，当前 1m / 3-call 组合没有通过证据；
   应先研究无损的元数据/eligible-set 复用编码，或换用确实支持所需窗口的已验证 pin/model。
   不靠减少字段、隐藏行、缩短 H、降低三轮验收或让验收忽略失败解决。
2. 若选择 128 生产分页，必须把上限显式参数化并绑定登记、MCP schema、IDs 和 cursor 两条入口；
   超限查询明确拒绝，合法分页提供完整 next_cursor，不能悄悄截取 128。
   这属于待确定的接口预算方案，本次未实施。完整初始快照不变，但少量分页下是否有足够工具次数须随后评估。
   若需要更多调用，必须按新 max_tool_calls 重新录制所有轮次。
3. 使用实际 CycleServer 增加 read→validate→submit、大 delta、拒绝回执、长 ID/缺失 ID、完整目录翻页和更大状态录制；
   样本最大 overhead 需覆盖全部路径。不能从本次“3 read”重放推断这些路径已经通过。
4. 原整状态三轮压力仍保留并报告失败；其目前仍是 RUNBOOK 所要求的预算门禁。
   128 样本通过不会使它失效。若要用“受已验证硬契约约束的压力集”取代它，
   需要单独明确该协议变更，并证明新集覆盖当前旧压力未覆盖的合法大查询；本次未作替换。
5. 所有必需压力集、完整性/工具隔离/零压缩门禁通过后，才能形成正式 overhead 和登记；
   实际模型名、reasoning 设置、服务容量、累计/每模拟小时预算及正式 Δ 仍待确定。步骤 5/6/8 的真实调用仍未获准。

## 6. 验证与证据

- 本轮核对上一轮封存的 **117 个既有源文件，0 改动**；8 个快照 hash 全部不变。
- 新增 8/8 原生读取重放诊断通过。上一轮 575 passed / 0 failed / 0 skipped / 38 subtests 是既有全套结果，本轮未重跑或冒充新的全套验收。
- 归因脚本最初两次在比较未规范化浮点时主动失败；改为采用已有快照 codec 的 10 位规范后，v3/v4 完整通过。
  原生重放第一次受沙箱禁止绑定 localhost 而未启动；获本地回环执行权限后的 v2 完整通过。失败日志均保留。
- 所有代码新增仅为工作目录中的离线诊断脚本和本报告；未改变生产模型入口或费用预算。

本机主要产物：

- [机器可读分析](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/step4-budget-analysis-20261019-v4/analysis.json)
- [128 原生重放 manifest](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/step4-reader-replay-128-20261019-v2/manifest.json)
- [参数候选](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/step4-parameter-proposal-20261019.json)
- [完整性核对](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/reports/step4-analysis-integrity-20261019.json)
- [分析脚本](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/analyze_step4_budget.py)
- [回环重放脚本](__PROJECT_ROOT__/validation/harness_v6_mac_20261018/capture_step4_reader_replay.py)
- 既有整状态压力：`__PROJECT_ROOT__/validation/harness_v6_mac_20261018/pressure-recordings-step34-final`（保留原失败结论）。
