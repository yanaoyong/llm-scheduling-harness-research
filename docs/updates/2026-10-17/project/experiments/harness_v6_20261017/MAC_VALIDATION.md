# Mac 验收清单

以下 A–E 记录为历史阶段说明。Phase F 已获准使用预装公开 SMT2020/vendor/tiktoken；没有读取封存证据或运行模型。最新状态见文末 Phase H 表；Phase F 表保留为历史记录。以下命令均从本实验目录运行。
后续阶段应添加下列测试文件和同名测试；Phase A 尚未实现这些适配器，不能声称已通过。
这些集成测试缺依赖时须 pytest.skip 并说明缺失项；Mac 正式验收必须实际通过，不能计 skip。

| 阶段 / 精确命令 | 通过条件 | Phase F 状态 |
|---|---|---|
| 当前底座：`python3 -m pytest -q` | 所有纯函数测试通过；隔离来源与目标 SHA256 匹配 | 通过（最终数量见 Phase F 报告） |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k time_semantics` | 修改原 environment.commit_plan :132/:158：过去下界保留、过期 hold 无效；d34-421 原上下文保留任务即通过 | 公开时间语义通过；d34-421 待封存证据 |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k frozen_invalidated` | 修改原 :164–168：宿主失效冻结任务可取消，不破坏其他冻结前缀；可继续推进，无零进展死锁 | 公开失效冻结取消通过 |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k when_ready` | 默认及显式 when_ready、not_before 两种模式均按物料/机组就绪派工；硬下界不提前；严格队序；batch_min/max、专用/min-run、运输、停机受物理约束；与纯 executor 对账 | 公开 when_ready/硬下界通过；组合覆盖范围见报告 |
| D / M2：`python3 -m pytest -q tests/test_mac_audit.py -k time_semantics` | 独立修改 audit :103/:136，同步过去下界和过期 hold；不调用 normalize/ledger 作为审计实现；接受合法保留并拒绝其余硬约束违规 | 公开来源/时间语义审计通过 |
| D / M0b：`python3 -m pytest -q tests/test_mac_replay.py -k equivalence` | 关闭新锚点/越级，用原时刻已提交计划验证到 1603.10s 的 dispatch/operation_complete/downtime 逐事件相同；不得外推新轨迹调用次数 | 待封存 G0 证据，明确跳过 |
| D / M0b：`python3 -m pytest -q tests/test_mac_factory.py -k roundtrip` | mixed_702 通过 factory.restore 导入，不伪装兼容旧实现指纹；v6 capture/restore 哈希往返一致 | 公开 round-trip 通过；mixed_702 待封存证据 |
| 后续 M1：`python3 -m pytest -q tests/test_mac_ledger.py` | has_legal 对账；复现旧口径 10/15/4；静态分类逐条列例外；w1703:86:1 纳入 avoidable_idle 或 explicit_wait_idle；机会损失独立报告 | 公开 has_legal 对账通过；M1(a–d) 待封存证据 |
| 后续 M3：`python3 -m pytest -q tests/test_mac_snapshot.py` | 固定版本 tiktoken；G0 1649.82s 全部任务 26/26；预算失败关闭；稳态 WIP 规模测量 | 真实 o200k_base 通过；G0 26/26 待封存证据 |
| 后续 M5：`python3 -m pytest -q tests/test_mac_session.py` | 仅本地模拟 Responses 端点，验证 F6 的 MCP 配置、approval、schema、事件字段、超时、压缩、环境继承及大型结果截断；无真实模型调用 | 待 Codex F6 探针证据，明确跳过 |

物理适配器与审计同步前，本阶段成功的纯校验不能当作物理或来源认证。
长时间运行须验证 breakdown 开关、检查点、预算闸门及漂移停止，CQT 仍未实现。
M6 / E1、P2 实际试验另行授权预算，不属于本次验收。

## Phase B 已实现的检查入口（M1 / M3）

从 V6 目录执行。仅在 Mac 配置环境变量；本仓库只测试合成 SQLite，未读取封存库。

1. 封存静态分类：实现 ContextReader.contexts() 返回 `{group, context}`，或使用
   SQLiteContextReader。根据真实库结构设置 `V6_SEALED_DB` 和 `V6_SEALED_SELECT`；
   SELECT 必须返回两列：G0/G1/G2 组名、完整 context JSON。若库通过引用拆表，SELECT
   或上层 ContextReader 必须先重建 problem/base_plan/execution_state，禁止猜测缺失字段。
   包含 882–1603.10 区间以及共同终点；26-task 检查另需 G0 1649.82。
   设置 `V6_CLASSIFICATION_REPORT=/tmp/v6-classification.json` 保存完整结果。

   ```bash
   python3 -m pytest -q tests/test_sealed_contexts.py::test_mac_sealed_classification
   ```

   通过：旧规则计数 G0/G1/G2=10/15/4；新规则逐条核验例外（Phase H 修订）：精确为 G0/G1 的两项已登记 context；
   独立审计确认 avoidable_idle>0，见证必须未预留且不是旧 gap 工序，预留机会不能触发；输出 reserved_but_earlier_startable 数量、预测潜在空闲秒数；
   w1703:86:1 出现在 avoidable_idle 或 explicit_wait_idle 见证中。
   这是静态反事实分类，不得推断 v6 轨迹、周期数或模型调用数。

2. 在 Mac 固定安装的 tiktoken 版本，并把版本与 encoding_name 写入实验登记。

   ```bash
   python3 -c 'import importlib.metadata; print(importlib.metadata.version("tiktoken"))'
   python3 -m pytest -q tests/test_snapshot.py::test_mac_tokenizer tests/test_sealed_contexts.py::test_mac_snapshot_26_pending
   ```

   通过：o200k_base 基础计数通过；G0 1649.82 的 26 个 base-plan 任务全部可见：23 pending 原样保留、3 dispatched
   在真实 running jobs 中由 job/lot/机组及 dispatch 工序身份对上，所有 hold
   原样保留，100% 未预留就绪工序有行。用实际规则/工具/路由静态表和生产预算再调用
   build_snapshot，记录实际 token 数；本测试大预算仅验证完整性，不代表生产预算可满足。

3. 物理口径对账仍依赖 Phase D 的真实适配器：从真实观察构造账本，把公开资格、
   min-run、batch_min/max 与 has_legal 逐机组比较；重点验证 cascading 的空闲/运行并存、
   专用绑定和运输完成。公共口径保守排除的 uncertain/same_machine_as 必须单列。
   已有纯实现回归命令：

   ```bash
   python3 -m pytest -q tests/test_ledger.py tests/test_snapshot.py tests/test_sealed_contexts.py
   ```

   该命令不等价于物理一致性验收；真实 has_legal 适配器尚属 Phase D 待办，不能宣称已通过。

## Phase C / M4–M4b 接入清单

本阶段新增模块没有 vendor/data 导入；下列现有命令可立即复跑纯机制检查：

```bash
python3 -m pytest -q tests/test_cycle_submit.py tests/test_metrics_checkpoint.py tests/test_synthetic_long_run.py
```

通过：1,200 周期完成；613 周期检查点恢复的最终全状态哈希相等；快照 <12KB，
最大最小差 <3KB；段预算停止、完整小时漂移停止、故障 invalidation 通过。
这些字节上限仅适用于四 lot 合成工厂，不能替代真实 tokenizer / WIP 测量。

后续 Phase D/M5 应提供下列真实适配测试（尚未实现，不能声称已在本仓库验收）：

| 精确命令（从 V6 运行） | 通过条件 |
|---|---|
| `python3 -m pytest -q tests/test_mac_environment.py -k advance_cycle` | 每个物理步骤更新账本/trace，缺口不提前终止，准确停在锚点或允许的越级事件；H 不裁剪模型有效期，合并锚点下限可提交 |
| `python3 -m pytest -q tests/test_mac_environment.py -k submit_precheck` | 接入只读 physical_precheck；完整独立违规列表；不变更 delta 可保留旧计划；崩溃后旧计划仍执行 |
| `python3 -m pytest -q tests/test_mac_factory.py -k segment_recovery` | 真实 state+ledger+cycle+cost 恢复；pending submission 不采纳、不重跑会话；已知部分成本保留，未知用量累加；trace/MCP/JSONL 压缩前后哈希对应 |
| `python3 -m pytest -q tests/test_mac_environment.py -k long_run_metrics` | 生产 tardiness/throughput/queue wait/setup 与独立物理审计一致；开工偏移基准和改机比例分母登记；四个小时漂移指标核对；预算只在段边界停；S2+ 故障受影响任务走 plan_invalidated |

真实输入 token / 缓存用量来自会话证据；必须登记 cached_input_weight 与未知用量上限。
真实成本/质量尚未测量；CQT/Q-time 仍未实现。S1–S4 升级与任何实时模型运行需另行授权。

## Phase D 当前入口（覆盖前文“未来文件”的状态说明）

以下测试文件现已存在。未配置 Mac 数据时明确 skip；Phase F 将 bundle 的场景/证据键改为可选。
缺封存键时明确 skip（sealed evidence not provided）；已提供场景内部缺字段、缺依赖或断言失败
仍报错，不会转换为 skip。所有命令从 V6 执行，设置 `PYTHONPATH="$PWD/src:<物理项目根>"`，
物理项目须包含已固定的 src/smt/environment.py、vendor、SMT2020 数据。
当前仓库没有执行这些验收，也没有运行 Codex 或开启 loopback 服务。

`V6_MAC_FIXTURE=/绝对路径/v6-fixture.json` 的格式：

- data_dir：真实 SMT2020 目录。
- mixed_702：`{state, trace}`；state 为原 Store factory capture（允许原 batch_state，导入时删除）。
- g0_committed_plans：按时序排列的 `{time, plan}`；g0_trace：完整封存事件。
- d34_421：`{state, trace, plan}`，原上下文及保留过去 not_before 的完整候选计划。
- frozen_invalidated：`{state, trace, plan, until}`，state 含宿主 invalidated_task_ids，
  旧计划在冻结区间，新计划显式取消失效任务。
- when_ready：`{state, trace, plan, until, expected_dispatches}`；期望事件来自独立物理核对，
  须覆盖默认/显式 when_ready、未来硬下界、批量上下限、专用、min-run、运输、停机。
- advance_cycle：`{state, trace, plan, until, expected_reason, expected_time}`，含可避免空闲
  但尚有效计划的场景，检查不因缺口提前返回，并检查 trace 每次推进前有账本。
- v6_time_semantics_trace、v6_trace：完整真实轨迹；independent_idle_integrals：独立
  avoidable_idle、explicit_wait_idle、reserved_but_earlier_startable 三项积分。
- documented_public_physical_differences：逐机组 `{machine, public, physical}` 差异清单。
  初始应为空；不允许为使测试通过而事后无说明录入。保守预测/级联差异须单列原因。

| 命令 | 验收 |
|---|---|
| `python3 -m pytest -q tests/test_mac_factory.py` | M0b mixed_702 导入、capture/restore 哈希相同，无 batch_state |
| `python3 -m pytest -q tests/test_mac_replay.py` | M0b 原触发逐事件等价，到 1603.10，事件数非零 |
| `python3 -m pytest -q tests/test_mac_environment.py` | M2 d34-421、失效冻结、when_ready、M4 advance_cycle、只读预检 |
| `python3 -m pytest -q tests/test_mac_audit.py tests/test_mac_ledger.py` | 独立时间/来源审计；公开账本与物理合法性差异逐项记录；积分核对 |
| `python3 -m pytest -q tests/test_sealed_contexts.py::test_mac_sealed_classification` | M1(a–d) 10/15/4、例外、机会数量/秒数、w1703 见证；环境变量沿用前文 |
| `python3 -m pytest -q tests/test_snapshot.py::test_mac_tokenizer tests/test_sealed_contexts.py::test_mac_snapshot_26_pending` | M3 固定 tokenizer，G0 1649.82 的 26/26、全部 holds/ready rows |
| `python3 -m pytest -q tests/test_mac_session.py` | M5(b) 下述九个能力记录全部通过且无真实模型请求 |
| `python3 -m pytest -q tests/test_registration_replay.py tests/test_mcp_session.py::test_three_cycles_fake_runner` | M6 机制空跑；模板不能标为结果；真实结果必须另填质量/预算后 load(results=True) |

M5(b) 提供本地 mock endpoint 实现：

```bash
PYTHONPATH=src python3 -m harness_v6.mac_probe --fixtures /绝对路径/responses.json --log /全新路径/requests.jsonl
```

服务只监听 127.0.0.1，stdout 给出随机端口；不发任何外部请求。responses.json 是列表，
每项 `{status: 200, content_type: "text/event-stream", body: "已固定的 Responses SSE 字节文本"}`。
用 Mac 上固定版本的协议录制/构造响应（工具调用、成功结束、压缩、错误、超时场景），
单独运行所构造的 Codex 命令，provider base_url 必须指向此服务。测试本身不启动 Codex。
脚本响应耗尽返回 409；请求日志独占创建。不要把真实凭据或真实端点写入夹具。

`V6_F6_PROBE_DIR` 下保存 manifest.json：`endpoint`、`codex_version`、
`real_model_requests: 0`、`checks`。每个检查记录 `passed`、实际 `command`、`expected`、
JSONL 相对文件名 `jsonl`，同时保留请求日志作为人工核验依据。九项键及要求：

1. config_injection：ignore-user-config 下 command/args/env 注入成功。
2. approval_never：MCP 调用完成而非取消。
3. schema_with_mcp：单独带 output-schema 的探针仍可工具调用；生产命令不强制输出 schema。
4. jsonl_fields：确认 EVENT_TYPES 中 mcp_tool_call、item.started/updated/completed、
   server/tool/arguments/id/status、turn.completed.usage 的真实拼写；与 MCP 日志逐条一致。
5. startup_timeout：故意推迟服务启动，记录启动超时及失败旧计划保留。
6. tool_timeout：故意推迟工具结果，记录工具超时及失败旧计划保留。
7. compaction_detection：小阈值诱发压缩；thread.compacted/context.compacted/compaction
   中的实际事件须被检测；若事件不同先修订集中表并重跑所有检查。
8. environment_inheritance：inherit=none 下只有显式注入 MCP 环境生效。
9. large_result_complete：大结果逐字节核对；额外保存 received_result JSON 文件，
   sent_result_sha256 为 canonical JSON 哈希；不允许静默截断。

test_mac_session 是探针证据验收入口，不会自动产生或独立认证这些能力；passed 字段不能
替代实际命令、请求记录和人工核对。真实 wire fixtures 尚未提供，F6 仍是试验阻断门槛。

仍需在 Mac 做长时性能与生产验收：完整公开观察/账本 trace 目前按步重建，不满足最终
物理增量 O(变化量) 性能目标；测量后接入物理事件增量。真实 segment_recovery、故障、
生产 tardiness/throughput/setup 与 token 漂移测试仍须扩展实际夹具，前文对应未来命令
不代表已有可执行验收。现有 checkpoint/恢复测试仅证明合成机制。

## Phase E：single_action 与事件触发补充

在 V6 执行：

    python3 -m pytest -q tests/test_groups.py
    V6_SINGLE_ACTION_PROBE_DIR=/绝对路径/single-action-probes python3 -m pytest -q tests/test_mac_single_action.py
    python3 -m pytest -q tests/test_mac_environment.py::test_event_trigger

第一项纯合成：四组各 55 次决策成功、checkpoint 恢复一致；E1 精确在首次
匹配空闲出现的物理完成时刻触发，组批不足/预留机会不触发；故障、失败、
停滞、严格有效期、最终输出来源和工具拒绝均通过。不作为 SMT2020 质量结果。

第二项只读 Mac 保存的本地 mock 证据，不启动 Codex。先用前文 mac_probe
端点及固定版本 Codex 手工产生三份独立请求日志，每个日志只有一次请求：

- single_schema_no_mcp：使用 single_action.command 构造命令，schema 用
  single_action.write_schema 写入。必须带 --ephemeral --json --output-schema
  和 mcp_servers={}，不得有 MCP server 子项；请求 tools 为空，最终消息参数
  与 expected_arguments 完全一致，共享 Submitter 可接受。
- single_tool_rejection：模拟非法工具 item，分类器必须拒绝；
  宿主保留旧计划。禁止开启真实工具执行来构造此证据。
- single_usage：最终 turn.completed 累计 input/cached/output 与请求记录一致，
  一进程一请求；禁用 provider 自动重试，失败不得生成额外请求。

目录 manifest.json 沿用 endpoint（仅 127.0.0.1）、codex_version、
real_model_requests=0、checks。每项含 passed、expected、command（argv 数组）、
schema/jsonl/requests（目录内文件名），成功项另含 expected_arguments。
requests 使用 mac_probe 输出格式，body 是 JSON 字符串。保存实际 schema、
原始 JSONL、完整请求日志；人工核对本地 provider 配置、token 及失败旧计划保留。
任何配置/事件字段不兼容先修订适配器再复验，passed 标记不能代替原始证据。

第三项使用现有 V6 Mac bundle 增加 event_trigger 夹具：
state、plan、until、expected_time；需让已有计划运行后第一次可避免空闲出现，
断言 advance_cycle(trigger="event") 恰停在 expected_time，匹配指标为正。
另人工验证 w1462 类仅已预留等待不触发，以及失败后 decision_after 阻止同刻
重试、下一物理事件再决策。未提供 Mac 夹具时这些检查明确 skip。
此前 M0b/M1/M2/M3/M5 与长运行门槛仍全部适用；CQT/Q-time 仍未实现。

## Phase F：公开物理环境最终状态（权威更新）

授权 Linux 预装环境运行公开数据测试；没有读取封存证据或执行 Codex。
详细数字与逐周期表见 [公开验证报告](reports/public_physics_validation_20261017.md)。

| MAC_VALIDATION 项 | Phase F 状态 / 证据 |
|---|---|
| 完整 plain suite | 通过：249 passed / 38 skipped / 42 subtests |
| 完整 configured suite | 通过：270 passed / 17 evidence-only skipped / 42 subtests |
| M0b factory / Store | 公开 capture/restore、只读预检、真实 SQLite CAS/陈旧版本拒绝通过；mixed_702 导入及 G0 等价回放仍待封存 |
| M1 ledger / has_legal / 独立积分 | 公开初始态及全部轨迹步骤通过；M1(a–d) 的 10/15/4、封存机会分类及共同终点见证仍待封存 |
| M2 时间 / when_ready / 冻结 | 公开过去下界、过期条件 hold、默认/显式 when_ready、未来硬下界、latest_start、冻结默认观察、失效取消、故障开关通过；d34-421 原上下文两个检查仍跳过 |
| M3 snapshot / tokenizer | tiktoken 0.14.0 / o200k_base、公开 ready 行 100%、任务/hold 完整、真实预算失败关闭和小时规模测量通过；G0 1649.82 的 26/26 仍待封存 |
| M4 周期 / 提交 | 真实 periodic/event 推进与原子 Submitter、逐步独立审计通过；窗口内无 plan_horizon 缺陷 |
| M4b segment_recovery | 三条轨迹的正常检查点恢复、状态/账本/周期/积分/token 行及压缩观察哈希通过；真实进程崩溃、完整 MCP/JSONL 轮转链仍待后续 |
| long_run_metrics / 漂移 | 完成一小时机制/规模测量；生产迟交、产出、排队、换型的独立物理口径及四小时漂移未完成 |
| M5(a) / M6 synthetic | 全 suite 中假规划器、四组机制、失败/预算、登记模板检查通过 |
| M5(b) / F6 / single_action | 九项 MCP 探针、三项 single_action 探针未提供：12 skips；没有执行 Codex |
| M6 public / live gates | 公开 E1/P2 机制完成；真实 E1/P2 ×3 预算、质量底线与 F6 仍未满足，不进入实际实验结果 |

17 个 configured skips = 5 个封存检查（G0 回放、d34-421 两项、静态分类、G0 26/26）+12 个 Codex 探针。没有数据/vendor/tokenizer 缺失导致的 skip。

复跑：README Phase F 的 fixture/driver 命令；`tests/test_mac_snapshot.py` 现已实现公开完整性/真实预算检查。
`tests/test_public_physics.py::test_public_run` 读取三条完整结果及压缩证据，负责真实正常检查点验收；不是此前计划的真实崩溃/漂移全验收。

## Phase G：封存公开衍生证据复跑

授权范围为 `/workspace/v6-mac-env/evidence` 内已有的最小公开 extract；不下载、不联网、不运行 Codex/模型。
生成的 SQLite、完整 context、fixture、trace 与逐对象公开哈希索引全部写入 scratch。
历史 CAS 文件名只用于查找；公开压缩字节及解码内容重新计算哈希，不能认证原始私有链。

从 V6 目录执行（预装 Python 3.10 / tiktoken 0.14.0）：

```bash
export PYTHONPATH="$PWD/src:/workspace/v6-mac-env/physical"
export TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache
/workspace/v6-mac-env/venv/bin/python scripts/build_sealed_fixture.py \
  --evidence-root /workspace/v6-mac-env/evidence/project/experiments/context_window_batch60_20261016 \
  --public-fixture /workspace/v6-mac-env/work/public.json \
  --output /workspace/v6-mac-env/work/sealed2
export V6_MAC_FIXTURE=/workspace/v6-mac-env/work/sealed2/fixture.json
export V6_SEALED_DB=/workspace/v6-mac-env/work/sealed2/contexts.sqlite
export V6_SEALED_SELECT='SELECT group_name,payload FROM contexts'
export V6_CLASSIFICATION_REPORT=/workspace/v6-mac-env/work/sealed2/classification.json
/workspace/v6-mac-env/venv/bin/python scripts/validate_sealed_fixture.py /workspace/v6-mac-env/work/sealed2
/workspace/v6-mac-env/venv/bin/python -m pytest -q
```

纯仓库复跑时不设置上述环境变量：`python3 -m pytest -q`。
新增 `tests/test_mac_sealed_details.py` 验证 mixed_702 往返、d34-421 所有 pending task 逐字段保留、w1462 非触发和共同终点见证。
共同终点 `1603.1013031725258` 与等价回放要求的 `1603.10` 分别记录；派生终点观察使用 `measured:` 引用，不冒充归档模型上下文。
最终结果与差异见 [封存验证报告](reports/sealed_evidence_validation_20261017.md)。

### Phase G 最终验收状态（取代前述“待封存”标记）

| 项目 | 状态 |
|---|---|
| M0b mixed_702 / G0 replay | 通过；128 个物理事件逐条相等，factory 往返哈希一致 |
| M1(a) | 通过；10/15/4 精确复现 |
| M1(b) 全部不触发 | 未通过；两例独立未预留 w1703:86:1 工作，原零例外断言保留 |
| M1(c) | 完成；75 个 context×operation 机会，10389.52046615674 预测秒，非轨迹积分 |
| M1(d) / w1462 | 通过；三组共同终点观察、w1703 见证、w1462 已预留非触发均由新增 Mac 测试核验 |
| M2 d34-421 | 通过；63/63 pending task 原样保留，过去 not_before 不改写 |
| M3 26/26 pending | 未通过数值假设；26 是 base_plan 总数，3 项已派工，实际 23 pending。既有 26 断言保留，完整性与预算测量按真实状态报告 |
| M3 完整性 / token / fail-closed | 23/23 实际 pending、0/0 holds、1011/1011 ready 行；756359 tokens（含 907 running jobs）；旧注册预算 220000 下失败关闭、零丢行 |
| M5(b) / single_action | 仍待 12 项 Codex 探针证据；没有执行 Codex |

完整测试数量、真实 token 数、预算失败关闭、公开 SHA256 与两个差异的因果证据见 Phase G 报告。
封存测试不再因数据缺失而跳过；两条被证据否定的断言不会被改成 skip/xfail。

Phase G 完整 plain suite：**251 passed / 41 skipped / 42 subtests passed**。完整 configured suite：**278 passed / 2 failed / 12 skipped / 42 subtests passed**（908.00s）；两条失败即上述 M1(b) 与 M3 原数值断言，12 skips 仅 Codex 探针。没有宣称 configured 全绿。

## Phase H：编排者修订，待用户确认

修订原文见 [DECISIONS_v6.md](DECISIONS_v6.md)。此节取代 Phase G 的两条失败验收，
Phase G 结果保留为历史，不改写独立证据或账本口径。

- M1(b)：旧规则仍精确 10/15/4；例外集合必须恰为 G0 `context:97eada3675ec457ca5a28750`
  和 G1 `context:61d6652b89614a3aa60bfe1e`。两者 t=1593.1323091758827、机组 325、
  w1703:86:1，独立审计给出 avoidable_idle=1；见证与全部预留工序、旧 gap 工序、
  reserved_but_earlier_startable 均不重叠。移除该未预留见证后预留机会原样存在，
  两种独立实现的 avoidable_idle 都必须归零。
- M3：26 base tasks = 23 pending 原样 + 3 dispatched 可见，全部 holds/ready 行仍完整。
  `build_sealed_fixture.py` 从公开 G0 head state 提取 907 个未完成 running jobs，
  放入 merged fixture 的 `g0_snapshot`（仅 scratch）；上下文 ref/time 必须匹配。
  独立 sealed trace 将 d32-l/d36-e/d39-g 分别连到 job 976/974/975；
  snapshot 中须按 job、lot、machine、started_at 对上，并核对 trace 的 steps/visits。
  原 context 不含 running_jobs，旧测试默认空列表；完整快照实际有三项，不需修改 snapshot.py。

精确复跑命令：沿用上方 Phase G 的全部环境变量与 build/validate/pytest 命令；
**必须重新 build merged fixture**，以加入真实 `g0_snapshot`，不能以空列表代替。
纯套件：取消上述环境变量后从 V6 执行 `python3 -m pytest -q`。
结果见 [封存验证报告的 Phase H 节](reports/sealed_evidence_validation_20261017.md)。

Phase H 最终结果：plain **251 passed / 41 skipped / 42 subtests passed**（36.61s）；
configured **280 passed / 12 skipped / 42 subtests passed**（1002.87s）。
两个修订验收均通过；12 skips 仅为 9 项 MCP/F6 与 3 项 single_action 探针。
M0b 仍为 128 事件完全相同；M1(a) 10/15/4，M1(b) 两项例外独立核验通过；
M3 26/26 accounted、907 running jobs、1011 ready rows、0 holds；756359 tokens，
历史 220000 上限失败关闭，零丢行。复跑日志在 `/workspace/v6-mac-env/work/phase-h-*.log`。

## Phase I — 宿主与代码审查验收

沿用上节 Phase H/G 的 merged fixture、venv、PYTHONPATH、TIKTOKEN_CACHE_DIR，禁止模型/Codex/网络。

- `python3 -m pytest -q`：纯仓库完整测试；新增 `tests/test_live.py`，四组各 50 次真实宿主决策，MCP 双路审计、篡改失败、提交后崩溃恢复、hold 互斥、无 id hold 往返、请求轮次和链前驱篡改。
- `/workspace/v6-mac-env/venv/bin/python -m pytest -q`：配置完整 suite；仅允许 9 个 F6/MCP 与 3 个 single_action Codex 探针跳过。
- `/workspace/v6-mac-env/venv/bin/python -m pytest -q tests/test_live.py::test_mac_live_p2_three_cycles`：mixed_702 实际物理 ≥3 个 P2 周期，通过 live.py、真实 CycleServer 和 private_state restore/prepare 预检；脚本只续订封存任务，不调用模型。
- `/workspace/v6-mac-env/venv/bin/python scripts/run_public_physics.py --fixture /workspace/v6-mac-env/work/sealed2/fixture.json --group P2 --until 1603.10 --output /workspace/v6-mac-env/work/phase-i-p2.json`：公开物理回放，检查点必须真实调用 restore_ledger，rows/metrics 与重建一致，恢复终态和积分一致。
- `/workspace/v6-mac-env/venv/bin/python scripts/validate_sealed_fixture.py /workspace/v6-mac-env/work/sealed2`：更新静态分类和完整快照测量，保留 10/15/4、两项异常与 M1(d) 的证据核验；数值变化据实报告。
- `python3 -m compileall -q src` 和 `git diff --check` 必须通过。

审计说明：audit_ledger 与 audit_v6 各自实现相同贪心政策，只检查实现差异，不证明全局最优。
有效 hold 只计 explicit_wait_idle_seconds，不触发；条件 hold 未激活时继续参与 avoidable_idle。

Phase I 已完成的独立验证：纯 suite `267 passed, 42 skipped, 42 subtests passed in 629.54s (0:10:29)`；
真实宿主三周期 `1 passed in 248.17s (0:04:08)`；会话定向回归 `38 passed, 5 deselected in 6.11s`。
公开 P2 重新运行、restore_ledger 比较和恢复均通过，分类仍为 10/15/4 与两项固定异常，
M1(d) 三组均通过，完整 token 仍为 756359。最终完整配置 suite 结果如下。

最终配置 suite：`297 passed, 12 skipped, 42 subtests passed in 1775.79s (0:29:35)`。12 个 skip 仅为 9 个 F6/MCP 与
3 个 single_action Codex 探针；没有数据、物理或 tokenizer skip。最终 RPC 改动另由
`16 passed, 1 skipped in 30.43s`（纯宿主测试，唯一 skip 为物理）及
`1 passed in 248.17s (0:04:08)`（真实物理三周期 RPC）覆盖。
日志：`work/phase-i-plain-final.log`、`work/phase-i-configured-final.log`、
`work/phase-i-live-rpc-final.log`、`work/phase-i-live-rpc-mac-final.log`。
`python3 -m compileall -q src` 与 `git diff --check` 均通过。

## Phase J

沿用上述配置运行 `python -m pytest -q tests/test_live.py::test_mac_live_p2_three_cycles`：
必须显式使用 context_token_budget=10**8、request_overhead_tokens=0、output_reserve_tokens=0（仅脚本测试）、tiktoken_counter('o200k_base')，三次提交通过私有物理预检；完成后 private.json 不存在。
纯合成 `python3 -m pytest -q tests/test_checkpoint_segments.py tests/test_synthetic_long_run.py --durations=10`：
1,200 周期不缩减；检查点最多两个、latest 仅读一个完整文件，链篡改失败；段后两周期恢复保留 abandoned 目录且终态一致。
测试以 /dev/shm 为合成 LiveRun 临时目录，缺失时回退 tmp_path；物理测试仍用磁盘，避免 64MB tmpfs 容量不足。


## Phase L / M3 紧凑表示（2026-10-18）

沿用 Phase J 的 PYTHONPATH、TIKTOKEN_CACHE_DIR、V6_MAC_FIXTURE、V6_SEALED_DB、V6_SEALED_SELECT，
V6_CLASSIFICATION_REPORT 指向新的 classification-l-final.json。最终结果见
`reports/compact_snapshot_validation_20261018.md`；前文 756359 / 563837 为历史 raw JSON 测量。

```bash
python3 -m pytest -q
python3 scripts/validate_sealed_fixture.py /workspace/v6-mac-env/work/sealed2
python3 scripts/run_public_physics.py --fixture "$V6_MAC_FIXTURE" --group P2 --until 1603.10 --output /workspace/v6-mac-env/work/phase-l-p2.json
python3 scripts/measure_compact_snapshot.py --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" --output /workspace/v6-mac-env/work/compact-l-tokens.json
```

通过标准：manifest routes/machines、G0 t=1649.82 的全部字段/类型往返一致（float 相对 1e-9）；
26 accounted = 23 pending + 3 traced running；907 jobs、1011 ready、全部机器/hold 完整；
10/15/4 旧分类、两个封存异常和 128 个物理事件回放不变。输出 o200k_base 的实际静态/动态/总 token，
不得为满足估计值省略信息。使用新格式总数减 1 的预算必须失败关闭。

### F6 新项目：whole_request_overhead（仍待 Mac 证据，不在本阶段运行 Codex）

使用现有本地模拟 Responses 服务/固定 Codex 版本录制请求，保留系统提示、三个工具 schema、
完整快照、工具结果和 token 计数；禁止借重复快照工具补取内容。使用 pinned o200k_base 分别测量
系统提示/工具协议开销（request_overhead_tokens）及完整请求。登记 context_token_budget 和覆盖
输出+推理的 output_reserve_tokens；后续轮次工具结果增长也必须纳入开销保守上界。
验收：所有录制请求的实际非快照输入 ≤登记 overhead，完整输入 + reserve ≤ context budget；
多 1 token 的边界在启动 Runner 前停止，budget_report.json 各项可核对；不发生隐式压缩。
模型理解紧凑表的准确率还需单独验证，不由解码往返替代。

已有证据检查命令：`python3 -m pytest -q tests/test_mac_session.py`。
新增预算边界命令：`python3 -m pytest -q tests/test_compact.py -k whole_request_budget`。
F6 新测量须与九项已有 probe 一起人工核验并保存报告；此阶段只执行合成边界测试，
未提供真实 Codex 请求证据，不将该项标为通过。

## Phase M：决策 delta 的离线验收

在 V6 目录，使用既有配置环境，不调用模型：

```bash
PYTHONPATH=src:/workspace/v6-mac-env/physical TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache /workspace/v6-mac-env/venv/bin/python scripts/measure_model_delta.py --database /workspace/v6-mac-env/work/sealed2/contexts.sqlite --output /workspace/v6-mac-env/work/model-m-tokens.json
PYTHONPATH=src:/workspace/v6-mac-env/physical TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache /workspace/v6-mac-env/venv/bin/python scripts/validate_sealed_fixture.py /workspace/v6-mac-env/work/sealed2
PYTHONPATH=src:/workspace/v6-mac-env/physical TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache /workspace/v6-mac-env/venv/bin/python scripts/run_public_physics.py --fixture /workspace/v6-mac-env/work/sealed2/fixture.json --group P2 --until 1603.10 --output /workspace/v6-mac-env/work/phase-m-p2.json
```

通过条件：scripted 和完整 26-task G0 base 的新旧 o200k token 可重复报告；新版更小。
G0 快照投影精确 round-trip，所有任务 ID 和 machine_orders 保留。sealed 分类和 replay 不变。
P2 16 sessions、232 steps、878 dispatches、恢复相等、全部任务生产字段及物理事件不变；
仅快照表示、host 生成的版本字符串和依赖版本的哈希允许变化，必须逐项说明。
完整 configured suite 使用 Phase J 的环境变量，分类输出改为 `classification-m-final.json`。
仍待真实 Mac/Codex 验证：模型能否读懂完整 schema/小例子、single_action 接受同一 schema；
既有 F6 12 项探针未获新的运行授权，不能把离线结果写成 live-model 成功。


## Phase N：双格式与理解准确率

离线设置沿用 Phase J（PYTHONPATH、TIKTOKEN_CACHE_DIR、V6_MAC_FIXTURE、V6_SEALED_DB）。
命令：`python -m pytest -q tests/test_mac_snapshot.py tests/test_dense.py tests/test_compact.py`。
通过标准：真实 manifest 和 G0 t=1649.82 两种格式还原相同规范生产对象，类型及覆盖一致，
两种前缀各自跨周期字节稳定；只有格式 legend 不同。
`python scripts/measure_compact_snapshot.py --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" --output /tmp/phase-n-tokens.json`
使用 o200k_base 计数；输出 explicit/dense 工艺、静态机组、ready、动态机组、运行作业、其余、legend、总数。
默认选择以同一计数器的完整表 token 严格减少为准，不能使用字符估计器宣称真实收益。

待独立授权的模型理解 A/B：固定同一组状态和工具、模型、预算；仅更换登记 snapshot_format。
两种格式询问同一题集：指定工序的完整合格机组集合；batch_min/max 与可组批判断；
队首任务、设备可用时刻、正在加工/待执行区分；缺字段/null/空串与默认值解释。
从规范解码对象建立标准答案，报告逐题正确率、按题型正确率、全请求 token、请求数；
顺序随机或交叉平衡，并报告重复次数。不得仅凭压缩率宣称理解能力等价。
本阶段只执行离线检查，不调用模型。CQT/Q-time 仍未实现。

## Phase O：进程边界与 CLI

```bash
python3 -m pytest -q tests/test_codex_runner.py tests/test_run_cli.py
# 配置物理环境后，独立端到端 proof：
PYTHONPATH="$PWD/src:/workspace/v6-mac-env/physical" \
TIKTOKEN_CACHE_DIR=/workspace/v6-mac-env/tiktoken_cache \
V6_MAC_FIXTURE=/workspace/v6-mac-env/work/sealed2/fixture.json \
/workspace/v6-mac-env/venv/bin/python -m pytest -q tests/test_run_cli.py::test_configured_cli_fake_crash_resume
```

通过条件：四组各≥10 个真实子进程决策，MCP 客户端实际启动 stdio server，双证据审计通过，
请求下界为工具轮次+1；非零/超时/禁用动作/坏 JSONL/未知用量/提交后崩溃均不采纳，
失败上限停止、超时后无运行中后代。真实 mixed_702 上两个机制 run 各≥3 会话，
注入第二次会话后宿主崩溃，恢复丢弃候选并计失败，达到同一终点、生成汇总。
无配置时仅物理 E2E 明确 skip。生产指标单独用新 lot_complete 事件验证，不重复历史完成量。

Mac 真实 Codex 验收（本阶段不运行）：先完成既有 F6/三项 single_action 原始证据探针，
核对登记版本、认证 allowlist、--ignore-user-config/--ignore-rules 等 argv、MCP 子进程权限及
JSONL 字段。然后按 README 命令运行批准的 E1/P2 ×3 登记，断言 manifest 版本与登记一致、
无未知 usage、质量口径可由物理 trace 复算，summary/results 成本按同一模拟窗口归一化。
真实 API 缓存和模型理解/质量须实际测量；fake usage 不是真实成本。CQT/Q-time 仍未实现。

## Phase P：可执行测量与统一 runbook

当前顺序入口为 [MAC_RUNBOOK.md](MAC_RUNBOOK.md)，替代前文“手工构造探针”的操作步骤，
保留全部原能力门槛。`scripts/run_codex_probes.py` 自动录制 9+3 项并生成现有测试读取的 manifest；
任何 pin/Responses SSE/JSONL 不兼容失败关闭，不能把 fake 通过当成真实能力。
`measure_request_overhead.py --capture mcp_session|single_action` 使用真实快照和生产工具 schema
录制两格式请求，多轮结果增长纳入建议；只覆盖已测轮次/负载，未知服务器 framing 仍须单独核验。
`ab_comprehension.py run` 固定 model/pin/budget，执行已有 AB/BA plan；不读取答案。
`mac_preflight.py` 核对路径/hash/版本/cache，--version 不验证认证。

```bash
python -m pytest -q tests/test_phase_p.py tests/test_codex_runner.py tests/test_ab_comprehension.py tests/test_request_overhead.py
```

通过条件：fake 真实 HTTP+stdio 回路生成的 12 项 manifest 被原有两个 Mac 测试完整接受；
大小/越界/错误输入失败关闭；leader 退出留 TERM-ignoring child 不误超时，正常及超时均无运行中后代；
A/B fake 100% 与预算预检、overhead 两模式录制分析、hash 篡改、一会话停止/恢复通过。
真实 Mac 的全部 12 项仍须独立执行且无 skip，A/B 理解与正式 E1/P2 质量/成本尚未测量。

- Phase Q：配置 `V6_SEALED_DB`、`V6_SEALED_SELECT` 和缓存 `TIKTOKEN_CACHE_DIR` 后运行 `python -m pytest -q -s tests/test_mac_snapshot.py::test_g0_bounded_coverage_tokens`；G0 1649.82 基础计划回执 coverage 的 o200k token 必须 < 1,500，打印旧/新 token 数，最多 50 个就绪未预留 ID。

## Phase R：过滤审计与 upcoming_operations

```bash
export V6_PUBLIC_LEDGER="$WORK/phase-m2-final-p2.json.ledger.jsonl.gz"
PYTHONPATH=src:$PHYSICS python -m pytest -q tests/test_upcoming.py tests/test_mac_snapshot.py tests/test_ab_comprehension.py
PYTHONPATH=src:$PHYSICS python scripts/audit_filters.py --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" --public-ledger "$V6_PUBLIC_LEDGER" --horizon-seconds 900 --output "$WORK/phase-r-audit.json"
PYTHONPATH=src:$PHYSICS python scripts/measure_compact_snapshot.py --fixture "$V6_MAC_FIXTURE" --database "$V6_SEALED_DB" --output "$WORK/phase-r-tokens.json"
```

通过条件：G0 1649.82 有 74 条 upcoming；explicit/dense 精确还原 canonical 对象（沿用 10 位有效数字协议），冻结公共 P2 702/1182/1602 同样往返。when_ready 新任务 w100:228:1 被 compiler/Submitter 接受，测试显式取消旧基线已不在 observation 的 d43-g；不是自动修复。全部既有过滤/校验不变；sealed classification 与 Phase Q JSON-equal。审计输出含五个状态、各规则计数及缺失信息说明；模型/真实 Codex 不参与。A/B 题集见 MAC_RUNBOOK，真实理解准确率待另行授权。
