# Mac 验收清单

本阶段没有导入数据/vendor/tiktoken/SQLite，没有运行模型。以下命令均从本实验目录运行。
后续阶段应添加下列测试文件和同名测试；Phase A 尚未实现这些适配器，不能声称已通过。
这些集成测试缺依赖时须 pytest.skip 并说明缺失项；Mac 正式验收必须实际通过，不能计 skip。

| 阶段 / 精确命令 | 通过条件 |
|---|---|
| 当前底座：`python3 -m pytest -q` | 所有纯函数测试通过；隔离来源与目标 SHA256 匹配 |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k time_semantics` | 修改原 environment.commit_plan :132/:158：过去下界保留、过期 hold 无效；d34-421 原上下文保留任务即通过 |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k frozen_invalidated` | 修改原 :164–168：宿主失效冻结任务可取消，不破坏其他冻结前缀；可继续推进，无零进展死锁 |
| D / M2：`python3 -m pytest -q tests/test_mac_environment.py -k when_ready` | 默认及显式 when_ready、not_before 两种模式均按物料/机组就绪派工；硬下界不提前；严格队序；batch_min/max、专用/min-run、运输、停机受物理约束；与纯 executor 对账 |
| D / M2：`python3 -m pytest -q tests/test_mac_audit.py -k time_semantics` | 独立修改 audit :103/:136，同步过去下界和过期 hold；不调用 normalize/ledger 作为审计实现；接受合法保留并拒绝其余硬约束违规 |
| D / M0b：`python3 -m pytest -q tests/test_mac_replay.py -k equivalence` | 关闭新锚点/越级，用原时刻已提交计划验证到 1603.10s 的 dispatch/operation_complete/downtime 逐事件相同；不得外推新轨迹调用次数 |
| D / M0b：`python3 -m pytest -q tests/test_mac_factory.py -k roundtrip` | mixed_702 通过 factory.restore 导入，不伪装兼容旧实现指纹；v6 capture/restore 哈希往返一致 |
| 后续 M1：`python3 -m pytest -q tests/test_mac_ledger.py` | has_legal 对账；复现旧口径 10/15/4；静态分类逐条列例外；w1703:86:1 纳入 avoidable_idle 或 explicit_wait_idle；机会损失独立报告 |
| 后续 M3：`python3 -m pytest -q tests/test_mac_snapshot.py` | 固定版本 tiktoken；G0 1649.82s 全部任务 26/26；预算失败关闭；稳态 WIP 规模测量 |
| 后续 M5：`python3 -m pytest -q tests/test_mac_session.py` | 仅本地模拟 Responses 端点，验证 F6 的 MCP 配置、approval、schema、事件字段、超时、压缩、环境继承及大型结果截断；无真实模型调用 |

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

   通过：旧规则计数 G0/G1/G2=10/15/4；新规则 exceptions=[]（否则报告每个 context_ref
   与完整指标，不隐去例外）；输出 reserved_but_earlier_startable 数量、预测潜在空闲秒数；
   w1703:86:1 出现在 avoidable_idle 或 explicit_wait_idle 见证中。
   这是静态反事实分类，不得推断 v6 轨迹、周期数或模型调用数。

2. 在 Mac 固定安装的 tiktoken 版本，并把版本与 encoding_name 写入实验登记。

   ```bash
   python3 -c 'import importlib.metadata; print(importlib.metadata.version("tiktoken"))'
   python3 -m pytest -q tests/test_snapshot.py::test_mac_tokenizer tests/test_sealed_contexts.py::test_mac_snapshot_26_pending
   ```

   通过：cl100k_base 基础计数通过；G0 1649.82 所有 26 个待执行任务逐字段保留，所有 hold
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
