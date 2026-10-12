# SMT 控制器与回放独立审查

审查范围：`src/smt_control.py`、模型与求解账本、完整 SMT2020 输入绑定、正式冻结、开发记录。审查者未调用真实模型，也未运行环境或求解器。回放实现位于 `src/smt_replay.py`，只依赖独立事件审计器 `src.smt.audit.audit_trace`；不导入控制器、仿真环境或优化器。

## 已修复的问题与优先级

| 优先级 | 问题 | 修复与核验 |
|---|---|---|
| P1 | 求解结果与统一账本没有显式调用 ID / decision，难以证明候选来自同一状态 | 主控制器新增 `solver_call_id`、`decision`。回放逐条核对参数、状态、账本 reservation/finish 与 C 的显式 apply。早期开发只能按同一 run 的账本顺序关联，并报告 legacy warning。 |
| P1 | 冻结、配置、源文件与每次运行关联不完整 | 主控制器新增 config_path、完整 started 元数据、source_snapshot、run/freeze.json 及其哈希。正式回放验证真实 Git commit、tag、冻结文件 Git blob、完整代码快照清单、配置有效哈希、27/9 矩阵和完整 source_data 清单。 |
| P1 | 失败求解的调用数和 requested seconds 可能漏计 | 主控制器异常分支也保存失败 solver_NNN 结果并累计成本。合成测试确认失败求解保留 1 次与 1 秒预算；失败 C 已求解但未 apply 仍保留模型和求解成本，不算成功。 |
| P1 | C 将 BudgetExceeded 当普通修订错误，可能继续消耗模型预算 | 主控制器单独传播 BudgetExceeded。回放使用每次 reservation 之前的账本前缀核对 grant、phase、请求次数、求解秒数、token 准入和 unknown-usage 停止阈值。 |
| P2 | 聚合成本未包含所有 token 字段 | 新控制器保留 input/output/cached/cache_write/reasoning 五字段。未知值保持 null；缓存输入是输入子集、推理输出是输出子集，阶段阈值只加 input+output。早期开发缺少后两项只警告，同时从原始事件重算。 |
| P2 | 优化器参数接受 bool/非法 seed 的风险 | 主控制器依赖优化器严格验证 time_limit、int32 seed 和整数权重。C 不能隐式 apply；F 使用一组预设参数，不跨不同权重目标挑选最大值。 |

## 回放证据链

1. `events.jsonl` 最后一个 agent_message、`final.txt`、每次模型 `result.json.output` 必须一致。核对请求 prompt/schema/config 指纹、零原生工具事件、一次 completed turn、返回码和账本成本。
2. 根据 `trace.jsonl` 中每个动作之前已经发生的事件，独立重建当前 WIP、设备可用性、资格批次、等待、换型及加工时间摘要，并与 `state_XXX.json` 和模型 prompt 精确比较。未来到达、故障或返工信息没有被批准为可观测字段。
3. B 的实际动作必须由最后一个该状态模型输出给出；B 目录和账本不得包含求解器调用。此前错误反馈必须来自本状态的此前模型输出和 root rejected_actions。
4. C 的每个求解参数必须由该状态模型输出给出。后续 prompt 中的候选必须来自同一 run 保存的求解结果，剩余预算由调用之前的统一账本重算。实际动作必须来自模型明确 apply 的候选，不能自动选取。
5. A 每状态使用 classical_parameters，F 每状态使用 fixed_auxiliary_parameters，均只调用一次优化器。F 不进入 A/B/C 核心统计。
6. root actions 的决策、时间、动作与 action_XXX 文件及事件 trace 逐条关联；附加的模型/求解调用数和决策耗时分别核对。
7. 独立 `audit_trace(..., verify_data_dir=...)` 检查完整工厂约束、源 CSV 语义与指标。source_data 单独记录完整文件数量、清单哈希及官方 conversion-manifest 对应情况，不把 manifest 自报哈希当作外部来源证明。
8. 模型和求解 ledger 的失败 reservation 也消耗预算。token 未知不会变成 0；进行中的 reservation 不误认为已完成的 unknown usage。token 阈值属于已观察累计准入，CLI 没有硬输出 token cap，串行批次可能由已经准入的一次有界调用越过阈值。

## 正式元数据和覆盖要求

每次 run 的 result 与 started 至少关联：identity（scenario/arm/repeat/config_sha256）、code_commit、source_sha256、config_sha256、config_path、data_sha256、protocol_version、adapter_version、window_seconds、controlled_machine_ids、warmup_seconds、outside_policy。正式 run 另需 freeze_tag、freeze_manifest_sha256、run/freeze.json、完整 source_snapshot。

正式 freeze 必须关联真实 commit/tag、files、config_path、effective_config_sha256、protocol_version、phase、matrix 与 source_data。环境 scenario 是外生随机种子；solver repeat seed 固定为 11/22/33。机器 ID 按集合等价核对，不能把配置顺序误作语义不同。

`audit_phase(phase, freeze=None, verify_data_dir=None)` 返回 `runs` 与 `auxiliary_runs` 两套逐 run 记录，以及各自认证数量。正式核心矩阵必须是三个场景 × A/B/C × 三次，即 27 格；辅助矩阵必须是三个场景 × F × 三次，即 9 格。缺格全部列在 missing 中，状态为 not_started 或 incomplete。无结果目录只能说明 incomplete / process_state unknown，不能推断进程已中断。失败记录保留并进入分母。`coverage_complete` 只说明格点齐全，`acceptance_ready` 还要求每条成功、领域合法且正式来源关联完整。

`replay(path, verify_data_dir=None)` 的 audit_pass 表示保存证据自洽。失败/超时记录可以 audit_pass=true，但 domain_valid=false；这不表示实验成功。成功认证至少要求 status=success、audit_pass=true、domain_valid=true，正式额外要求 provenance_complete=true。

## 实际验证

- `.venv/bin/python -m unittest tests.test_smt_replay -q`：22 项通过，最后一次 0.191 秒。所有数据为明确标注的合成 fixture；未生成真实实验结果。CSV 的一文件 fixture 语义边界被 mock，完整 domain trace 审计和其余关联检查实际运行。
- 变异覆盖原始模型 JSON、最终文本、伪造状态（同时重算 prompt 指纹）、未来字段、动作文件、token/耗时、ledger、失败尝试限额、源文件清单、场景/窗口/seed、snapshot、freeze/matrix、C 跨候选反馈与参数、显式 apply、失败成本、损坏结果、27 核心和 9 辅助分离。
- `audit_phase('development')` 实际回放 dev_smt701_A/B/C：3/3 audit_pass，3/3 domain_valid，errors 均为空；最近一次 2.19 CPU 秒。每条实际核对完整 20 个源文件和 conversion manifest。
- 三条开发记录都为较早版本，provenance_complete=false：started 字段不齐；A/C 的 solver 记录没有显式 call_id；B/C 聚合 token 缺少部分细项。原始记录没有改写，详细 warning 由回放输出。它们是贯通证据，不替代正式冻结验收。
- 本子任务实际模型调用为 0；已有真实开发记录由主 Agent 运行。轻量测试与回放累计 CPU 低于分配的 20 秒。

## 解释边界与剩余核验

- 该控制器是在完整工厂内控制固定设备的动态闭环，优化器只做当前可观测状态的即时派工；不能称为全厂自主排程或全工厂最优。
- 早期开发没有完整 started 版本关联，不能宣称完全恢复历史进程。新正式版本必须通过真实 freeze 的首次运行回放；合成 Git 证据测试仅测试错误检出逻辑。
- 回放验证保存的模型输出和动作证据，不承诺重新调用随机模型得到相同文本。协作 Agent 的 token 与实验调用成本分开，未知费用保留未知。
- run wall_seconds 在控制器决策边界检查；初始化、最后一步仿真推进和独立末尾审计可能造成墙钟超出。调用/求解上限和实际总耗时均可核验，但它不是整进程级硬中断器。报告不得把它表述为绝对硬墙钟上限。
