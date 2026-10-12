# 研究级调用次数与用量豁免

用户最新明确要求“记得将调用次数与额度放开”。本修订把新研究 B/C 的调用次数、已知 token、未知用量准入和全研究累计模型活动时间上限解除。调用、超时、失败、未知用量和费用未知仍完整记账；豁免不购买额度、不抹掉历史、不把估算写成账单金额，也不等同于批准未冻结的正式矩阵。

批准对象见 [research_limit_waiver.approved.json](../../configs/smt_fullfab/research_limit_waiver.approved.json)。预算模块不因文件存在自动生效，主执行者必须显式调用 `approve_research_limit_waiver` 追加授权记录。子 Agent 的实现和测试没有写入真实研究账本；根执行者的实际落账是另一步，需以账本记录为准。

新事件 `research_limit_waiver` 保存独立 amendment_id、完整批准对象、原 approval 哈希、此前记录数及全部既有账本前缀哈希。原 `approval`、C 单场景 `scoped_limit_waiver`、历史调用/失败/未知用量行均保持不变。独立审计按事件顺序解释生效范围，不追溯放宽授权之前的调用。

## 保留的边界

- B/C 仍使用 `gpt-6-astra / medium`，单次模型 timeout 不超过 180 秒，还要适配该运行的剩余时间。
- 当前登记接口仅接受开发阶段 1/8/24 小时窗口，scenario 必须明确。正式阶段与 7/14/28 天矩阵仍需单独预注册冻结，不能通过这个接口暗中启动。
- 每个新 run 运行前登记有限、正数的 wall_seconds 和 max_log_bytes；执行器继续执行总体墙钟与日志准入限制。预算层另核对该 run 累计模型活动秒及单次 timeout；前者只是总体墙钟的一个组成部分，不能代替总体耗时限制。
- 模型或求解器 pending 时必须先诊断，不自动重试。完成但 usage 未知的调用保留未知，按研究豁免可继续新登记运行；金额未知始终为 null。
- B 的 solver_seconds 必须为 0。A/C 每个新 run 明确登记累计求解请求预算，例如初始 1 小时开发运行 60 或 120 秒；两个方案的比较仍须事前登记相同或有依据的可比资源。登记器不会凭 run 名称推断哪些 A/C 应配对，也不会替代公平性协议。

## API 与记录格式

`approve_research_limit_waiver(amendment)` 只追加一次不可变修订；同一对象重复调用幂等，不返还预算。`research_limit_waiver()` 只读返回已生效修订或 None。

`register_stage_run(run_id, arm, scenario, window_seconds, solver_seconds, wall_seconds, max_log_bytes)` 追加 `stage_run_registered`。A 的路径属于 `runs/smt_fullfab_development/`，B/C 属于 `runs/smt_fullfab_stage2/`，均为一个新的直接子目录。返回对象字段为：

```text
registration_id, amendment_id, budget_id, run_id（绝对目录）, arm,
scenario, window_seconds, solver_seconds, wall_seconds, max_log_bytes,
phase="stage2_research", formal=false
```

registration_id 是其余字段 canonical JSON 的 SHA256。相同登记幂等，不允许修改额度；已发生模型/求解器预约或已有执行结果、trace/checkpoint 的旧 run，不能再注册以清零历史。恢复旧运行继续使用其旧资源证据，不能用重命名冒充一次未发生的原调用。

模型 reservation 必须匹配事前登记的 arm/scenario/window/phase；metadata 包含 model、reasoning_effort、timeout_seconds 和 authorization_context。记录追加 registration_id、amendment_id、完整全研究 account_before 与该 run 的 run_account_before。`summary()` 仍返回全研究历史；`summary(run_id=绝对目录)` 返回该 run 的模型计数、用量和活动秒，不删改全局账本。

`solver_remaining_seconds(arm, run_id=...)` 返回指定新登记 run 的余额。`reserve_solver` 为该 run 追加带 registration_id 的预约，失败照样消耗预算。无 run_id 的旧查询继续返回旧阶段累计余额，并排除新登记 run 的消耗；旧 60 秒耗尽不会变为未耗尽，也不会被混入新 run 的 60/120 秒额度。`stage_registration(run_id, arm=None)` 可只读获取登记；省略 arm 时传绝对目录。

新 controller 保存 `resource_registration.json`。C 的 LIMITS 明确展示该 run 剩余模型活动时间、剩余求解请求秒及单次求解上限；B 的 remaining_model_responses 为 null 表示未设次数上限。page_chars 只控制完整分页的页大小，不能删除可观察字段或隐藏困难任务。

## 独立审计与验证

`controller_audit.py` 不导入预算模块，按完整账本前缀自行重放授权、run 登记和预约。它验证历史锚点、登记哈希、登记是否先于调用、模型/场景/窗口、实际 trace、原始 config、每次 timeout、全局及 run 计数、C LIMITS 与累计求解预算。B 出现求解器记录仍拒绝。新授权不会改变旧 B/C 失败运行的历史分类。

测试只在临时账本和合成证据中覆盖：先授权后登记、历史未知保留、超过旧全局次数/token/2700 秒后合法新 run、B/C 适用范围、pending 停止、单次 180 秒/每 run 时间、跨 run 求解额度、旧账户不重置、重复或追溯登记、正式阶段拒绝、历史锚点篡改及完整新 B 证据审计。旧研究账本和真实模型调用均不由测试修改。

```sh
.venv/bin/python -m unittest tests.test_smt_fullfab_budget tests.test_smt_fullfab_controller_audit tests.test_smt_fullfab_controller_review -q
```

本文件描述授权实现与审计口径，不宣称后续 B/C 实验成功，也不批准正式样本矩阵。
