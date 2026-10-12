# SMT接口 v2：主运行器集成

所有命令从实验根目录执行。依赖Python3.12与统一requirements.lock内ortools；原数据类加载无RL/torch/gym依赖。原constant cross-check测试需要pandas（ortools环境已有）。

```sh
python3 scripts/acquire_smt.py --proxy http://127.0.0.1:7897
.venv/bin/python -m unittest tests.test_smt -v
.venv/bin/python scripts/probe_smt.py --seed 701 --hours 8 --run-dir artifacts/smt_development/new_unique_name
```

acquire可断点续传，官方/Zenodo/GitHub所有归档需符合已锁定sha256。vendor内容有差异时拒绝覆盖；规范化数据由官方原包生成。`--inspect-only`不联网，用本地归档重新提取规范化数据。当前源码清单见data/smt/source-manifest.json。

```python
from src.smt.environment import SmtEnvironment
from src.smt.optimizer import solve_action  # 仅A/C，不向B开放
from src.smt.audit import audit_trace

e = SmtEnvironment(seed=701,window_seconds=28800,
                   controlled_machine_ids=[9,790],
                   trace_path=run_dir/'trace.jsonl',max_decisions=16)
state=e.advance()
while not state['finished']:
    # B:真实模型直接返回如下action，不能调用solve_action。
    # A:参数固定；C:真实模型选择白名单参数后调用相同solve_action。
    response=solve_action(state,time_limit=1.,seed=11,
                          priority_weight=100,waiting_weight=1,
                          fill_weight=1000,setup_weight=1)
    state=e.apply(response['action'])
metrics=e.finish()
audit=audit_trace(run_dir/'trace.jsonl',verify_data_dir='data/smt/SMT2020_LVHM')
```

状态：`schema_version,time,horizon,finished,decision_count,machines,current_wip,completed_lots,action_contract`。每台machine包含`machine,family,ready_now,current_setup,min_runs_left,candidates`。每个candidate包括`lot,part,step,priority,due,waiting_seconds,batch_key,batch_min,batch_max,setup,setup_seconds,expected_processing_seconds`。候选均为当前可观测/可选，未列未来故障、未来lot状态、其它方案数据。

动作：`{"dispatches":[{"machine":9,"lot_ids":["w123"]},{"machine":790,"lot_ids":["wA","wB","wC","wD","wE"]}],"wait_seconds":0}`。示例lot ID仅解释格式，不能照抄。lot集合必须来自当前状态且满足同part/step、batch min/max；一次动作不能重复同机或同lot。错误验证在修改状态之前完成。B可以省略某一机台、显式wait 1..1800秒；无dispatch且wait0报错。await完成整个窗口才能finish；决策超限报错，不接管。

`solve_action(state,time_limit,seed,priority_weight,waiting_weight,fill_weight,setup_weight)`返回action、solver_status、objective、best_bound、wall_seconds、parameters、model与global_optimality_claim=false。time_limit范围0.05..5秒；四权重为0..10000整数。C应保存每个模型参数选择、原反馈、最终action；不能将一次默认求解叫多轮自适应优化。该工具只有当前动作优化，无horizon参数，也不支持未实现的多步lookahead声明。

轨迹首行自含原数据hash及完整manifest；每个release/ready/skip/dispatch/downtime/operation_complete/rework/lot_complete/action/terminal都有单调seq和time。终止行完整列出所有lot状态，跨窗未完成批保留。`audit_trace`从记录重建，不调用simulation，可离线对全正式轨迹重算。v1旧宽度参数轨迹可回放，但已作开发淘汰，不属于v2验收。

开发pilot：`official_v2_guard_pilot701`窗口8h，仅4个决策状态、5次受控派工，约11.22 CPU秒；B每run约4次模型请求；按主运行器C每状态solve后再显式apply的协议，C每run约8次请求（等待、错误修订可增加，需主协议额外限制）。control IDs 9/790不可改成整个family而沿用此成本估计。
