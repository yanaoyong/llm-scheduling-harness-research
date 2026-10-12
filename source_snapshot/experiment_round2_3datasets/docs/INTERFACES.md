# 共享接口 v0.1（主 Agent 管理）
所有路径基于本实验根目录。所有实验函数必须保存真实原始结果，失败不丢弃。各角色只改分配文件，不提交、不切分支。
## 静态输入
JSON: {schema_version:"fjsp-1", instance_id, family, variant?, base_instance?, machines:[0,...], jobs:[{id:int, operations:[{id:"j<job>o<step>", job:int, index:int, alternatives:[{machine:int,duration:int}]}]}], source:{...}}。零基 machine/job/index，duration 正整数，全部 release=0，无 setup/维护等新增约束。参考值仅在独立 docs/data/reference 文件，不进输入 JSON。
排程 {operations:[{id,machine,start,end}]}，时间非负整数。
src/fjsp/problem.py: parse_fjs(path, instance_id=None, family=None) -> dict； source 解析基准先确认零基格式。
src/fjsp/validator.py: validate(problem,schedule)->{valid:bool,errors:list,makespan:int|null}，独立不调用排程器。
src/fjsp/solver.py: solve(problem, time_limit=30, seed=11, workers=1, **options)->{schedule, solver_status, objective,best_bound,wall_seconds,...}。
B 动作为完整列表 [{id,machine}]，列表必须工艺拓扑有序；确定性 append-only 时间解码仅计算 max(job_ready,machine_ready)，不选择 id/机器，不插入、不排序、不代排。限制：只能表达该解码的半主动排程，须报告。
C 动作为 solve(time_limit,seed,...) 或 finish(candidate_index)；共享 A 的 CP-SAT 模型。具体白名单与 schema 开发后冻结。
## 模型与记录
src/agents/model_transport.py: call_model(prompt,schema,run_dir,config,resume=False)->dict，复用首轮无原生工具隔离；只用运行上下文无参考值。src/agents/budget.py 统一 append-only ledger + 锁。每次调用 reserve/finish，phase 区分 development/formal。调用目录唯一，禁止覆盖。初始真实探测授权 1 次，其他调用需主 Agent 分配。
每次实验独立 runs/<phase>/<run_id>；result 包括 run_id,family,instance_id,arm,repeat,protocol_version,code_commit,config_sha256,data_sha256,status,failure_type,validation,metrics,costs,started_at,finished_at。费用未知 null；失败目标 null。
## SMT2020
完整官方 Dataset 2 LV/HM 文件与锁定 PySCFabSim 版本；不得用 FJSP 子问题代替工厂环境。src/smt 独占；提供 prepare/config、当前可观测 state、执行明确 lot/machine/batch/wait 动作、事件 trace、独立 audit 接口。先核实实际数据语义，再由主 Agent 批准具体协议。开发 seed 与正式/预留严格分离；固定非受控策略。A/C 可共享局部滚动 CP-SAT 优化，B 不得调用优化器或以规则替代核心动作。至少覆盖组批和非组批。未来随机事件不可进入模型上下文；事件键控/独立随机流方案先实测。
