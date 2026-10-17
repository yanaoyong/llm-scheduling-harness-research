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
