# Harness B 一小时验收与成本汇总

日期：2026年10月16日。B 已从原初态推进至仿真 **3600 秒**，完成 **238 次提交**，全窗口证据已封存并独立审计。模型为 **gpt-6-astra / medium**。执行窗口、证据完整性、决定来源、物理可行性和机会检查通过；**严格 G5 未通过**。

运行开始于北京时间 2026年10月14日 22:54:26.7，首次必要审计结束于 2026年10月16日 06:19:39.1。后续汇总没有新增模型调用，也没有重新启动 B。

## 验收结论

|检查|结论|证据范围|
|---|---|---|
|完整一小时执行|通过|实际终态 3600 秒，封存状态 CLOSED，存在真实 terminal 事件，无在途请求|
|证据完整性|通过|封存边界、原始对象及完整事件轨迹已核验|
|模型决定归属|通过|独立从原始 JSON 重建 238 次提交；算法生产调用和算法代替模型的生产任务均为 0|
|物理和机会检查|通过|完整窗口物理检查及机会检查通过，未发现未报告的未覆盖合法需求|
|G0 至 G4 工程门槛|报告范围内通过|继承未变的生产、数据和提示证据，加 68 项受影响控制逻辑检查及真实断点副本验证；I01 至 I12、T01 至 T28 映射保留|
|严格 G5|未通过|当前 B 和诊断合计 17 次未知用量；运行有 10 个明确记录的控制源码版本；微基准 P95 为 6，原要求不超过 5；实际资源也超过原始额度|
|完整工厂语义和在线能力|未验收|CQT 未实现，缺失历史绑定未获认证；本次采用模型思考期间暂停仿真的开发语义|
|算法质量优势|未验收|未开展同条件配对实验，不能据本次轨迹判断优于经典算法|

用户批准的扩额、未知用量例外和同轨迹续跑保留在版本化记录中。它们允许继续完成本次运行，但不把原始严格门槛改写为通过。最终控制版本冻结后保持一致；整条轨迹不能称为单一源码版本的计分成功。

原 19 个结果与同一组 20 个片段的共 39 组封存及审计哈希已再次核对，均保留。20 个片段正确性完成，中位往返 3、P95 6；这是 gpt-6.1-sol 的微基准结果，不作为 Astra 微基准成绩。

## 总耗时与 token

|范围|实际模型调用|已报告 token|模型活动时间|墙钟时间|未知用量调用|
|---|---:|---:|---|---|---:|
|本次 B 业务|784|30,720,365|7 小时 53 分 39.7 秒|31 小时 25 分 12.4 秒|16|
|本次 B 加五次历史诊断|789|30,737,533|7 小时 55 分 52.3 秒|同一 B 墙钟，诊断不重复加时|17|
|此前保留的微基准及早期 B|352|12,045,684|3 小时 51 分 55.0 秒|7 小时 12 分 44.0 秒|25|
|全部保留实验累计|1,141|42,783,217|11 小时 47 分 47.3 秒|38 小时 37 分 56.4 秒|42|

B 业务输入为 **30,017,146 token**，输出为 **703,219 token**。其中缓存输入 **734,336 token** 已包含在输入中，未重复相加。五次诊断的已报告 token 合计 17,168。

B 墙钟沿用最初创建时间，包含初始化、模型调用、中断、恢复、冷却、宿主处理和首次必要审计；独立审计耗时约 135.5 秒。累计墙钟是各已登记实验墙钟之和，不是项目开发总工时，也不含本聊天自身的推理用量。仿真一小时不等于真实运行一小时。

所有 token 合计都是已知下界。未知用量未按零处理；缺少可验证的完整计费记录，人民币或美元金额仍为未知。

## 失败和拒绝成本

|类别|次数|已报告 token|模型活动时间|未知用量|
|---|---:|---|---|---:|
|B 通道失败|16|未回报，不能记为零|0 小时 22 分 37.0 秒|16|
|B 方案被拒绝|1|36,429|0 小时 0 分 47.8 秒|0|
|历史诊断执行失败|1|未回报，不能记为零|0 小时 0 分 16.6 秒|1|
|直接失败和拒绝合计|18|至少 36,429，另有未知用量|0 小时 23 分 41.4 秒|17|

被拒方案的原因是完整当前及基础责任范围不匹配，拒绝发生在正式提交之前。另有 **1 次诊断正常返回但未获资格认定**，消耗 **4,292 token、38.5 秒**，单独披露，不混入断流失败。

账本登记冷却累计 50 分钟，观察到 16 次符合恢复记录的后继重试。冷却已经包含在 B 墙钟中；失败、拒绝和诊断费用也已经包含在上述总数中，不再重复相加。此前实验的成功与失败成本共同保留在历史累计项中，本节直接失败小计只覆盖本次 B 和五次关联诊断。

## 生产与效率指标

|指标|结果|
|---|---:|
|正式提交|238|
|派工事件|1,193|
|工序完成事件|296|
|整批完工|1 批，共 25 片|
|初始和最终在制批数|2,177 → 2,176|
|批处理派工及平均装载率|69 次，92.92%|
|单次模型时间中位数和 P95|22.28 秒，82.91 秒|

业务动作包括 291 次读取、239 次提案和 238 次独立提交，另有 16 次通道失败。失败尝试全部计入调用数。部分轮次计时覆盖 738/784 次调用：模型耗时 26657.4 秒，其他轮次耗时 36939.2 秒。其他轮次耗时包含检查、IO、处理和冷却；缺失的 46 次轮次计时仍保留其原始调用成本，不能据此声称完整耗时分解或因果节省比例。

## 证据与复算入口

- [机器可读最终验收及全部成本](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/final_delivery.json>)
- [全窗口独立审计](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_p5_astra_TUN_B_release/continuations/B3600-no-exception-quota/audit/acceptance.json>) 与 [封存清单](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_p5_astra_TUN_B_release/continuations/B3600-no-exception-quota/evidence_manifest.json>)
- [失败成本明细](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/failure_costs.json>) 与 [失败成本复算代码](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/finalize_failure_costs.py>)
- [最终汇总执行日志](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/finalize_delivery.log>) 与 [失败成本复算执行日志](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/finalize_failure_costs.log>)
- [冻结源码和数据索引](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/frozen_source/index.json>)、[工程验收](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/engineering_acceptance.json>)、[运行入口](<__PROJECT_ROOT__/experiment_round2_3datasets/artifacts/harness_B_error_alias_runway_20261015/run_entrypoints.json>)
- [P6 和 P7 计划](<__PROJECT_ROOT__/experiment_round2_3datasets/configs/smt_fullfab/harness_v1_10/P6_P7_plan.json>)：12 个配置的哈希已核对，配对、八小时及二十四小时实验均未开展。

本次实际执行了终态汇总和失败成本复算：

```sh
PYTHONPATH=. .venv/bin/python artifacts/harness_B_error_alias_runway_20261015/finalize_delivery.py
PYTHONPATH=. .venv/bin/python artifacts/harness_B_error_alias_runway_20261015/finalize_failure_costs.py
```

这些命令只读取原始封存证据，向汇总目录写入结果，不调用模型；已存在的封存汇总采用排他写入，不应覆盖重跑。B 已关闭，无需再次启动或恢复。严格 G5 保持未通过，后续若需要新的固定版本计分结果，应另行确定实验范围。
