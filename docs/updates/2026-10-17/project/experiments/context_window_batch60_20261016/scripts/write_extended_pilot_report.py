"""Write a result table from the sealed long-window comparison."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];RUN=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'live_pilots/extended_three_group_20261017'
def read(p):return json.loads(p.read_text())
def fmt(v):
 if v is None:return '未定义'
 if isinstance(v,float):return f'{v:,.2f}'
 return f'{v:,}' if isinstance(v,int) else str(v)
def main():
 x=read(RUN/'extended_comparison.json');s=read(RUN/'summary.json');c=read(RUN/'comparison.json');r=x['results'];groups=['G0','G1','G2'];end=x['common_window'][1]
 lines=['# G0 / G1 / G2 延长观察实际模型对比','',
  '**本次延长观察没有验证出新版规则或大窗口能减少总调用。** 同一区间 G0 / G1 / G2 分别需要 56 / 69 / 69 次调用；G2 相比 G1 少查了资料，却进行了更多轮排程。已有计划可以自动接续，局部确实省掉了后续调用，但这些收益被其他查询、调整和重排开销抵消。',
  '三组实际开工均为 60 项、完成均为 1 个批次，迟交与换型指标相同。G2 的累计队列等待少约 0.020%，本样本没有显示出实质性的整体质量提升。单条模型轨迹不能用于断言哪组普遍更优。','',
  f'共同观察区间为 702→{fmt(end)} 秒，新增观察区间为 882→{fmt(end)} 秒。原计划终点为 1800 秒。',
  ('本轮未全部达到 1800 秒。G1 第 72 次失败后，用户选择不再重试，按三组共同达到的区间比较；其余组随后停止发起新调用并收尾。共同终点之后已经发生的调用仍计入全部实际花费。' if (RUN/'comparison_boundary_decision.json').exists() else ''),
  '三组从同一 mixed_702 保存状态开始。本轮完整继承上一轮到 882 秒的模型选择、历史资料、已提交任务、提醒记录和调用成本，各自从原轨迹继续；没有重新抽样首轮模型输出。它们在 882 秒的计划已经因各组先前选择而不同。','',
  '三组都在独立副本中运行。G0采用原触发与执行规则，并与G1共用窗口和资料组织；G1、G2采用相同新版动态汇总与接续规则，仅窗口及配套输入上限不同。','',
  '| 指标 | G0 原版规则 | G1 新规则、小窗口 | G2 新规则、大窗口 |','|---|---:|---:|---:|']
 def row(label,values):lines.append('| '+label+' | '+' | '.join(fmt(v) for v in values)+' |')
 row('窗口 tokens',[272000,272000,544000]);row('输入预算 tokens',[220000,220000,440000])
 row('各组实际观察终点（秒）',[s['results'][g]['observed_end'] for g in groups])
 row('推进到共同观察终点所需调用',[r[g]['calls_to_common_endpoint'] for g in groups])
 for label,key in [('此前调用（702→882）','previous_calls'),('本轮新增调用','new_calls'),('累计实际调用','cumulative_calls'),('全观察区间重排触发次数','true_replan_count'),('新增区间重排触发次数','extension_replan_count'),('新增区间间隔不到 1 秒的触发','extension_intervals_below_1_second'),('新增区间间隔不到 10 秒的触发','extension_intervals_below_10_seconds'),('882 秒时已有待执行任务','inherited_pending_task_count'),('保留原任务编号与工序、在新增区间开工','inherited_pending_task_dispatch_count'),('其中按原安排、未再调整就开工','unchanged_inherited_task_dispatch_count'),('其中经模型再次调整后开工','rescheduled_inherited_task_dispatch_count'),]:row(label,[r[g][key] for g in groups])
 row('提交后未推进模拟时间就再次触发',[len([z for z in r[g]['zero_time_stops'] if not z['observation_cutoff'] and z['to']<=end]) for g in groups])
 row('新增区间全部触发机组仅看到已排工序的缺计划提醒',[sum(z['all_gap_machines_only_see_already_queued_work'] for z in r[g]['actual_gap_diagnosis']) for g in groups])
 row('全部实际提交的新增任务（各自终点）',[r[g]['added_tasks'] for g in groups])
 row('其中提交时机组尚在忙碌的后续任务（各自终点）',[r[g]['busy_added_tasks'] for g in groups])
 for label,key in [('共同终点已排但尚未开工任务','accepted_pending_task_count'),('共同终点未排公共工序（含未来条件工序）','unassigned_public_operations'),('其中未排非条件工序','unassigned_nonconditional_operations'),('未排需求涉及机组','pending_demand_machine_count')]:
  row(label,[(r[g]['common_backlog'] or {}).get(key) for g in groups])
 row('程序报缺计划机组中、扣除全厂已排工序后可开工工序',[r[g]['strict_ready_backlog'].get('unassigned_immediately_executable_unique_operations') for g in groups])
 row('全厂物理可加工但尚未分配工序（可能需调整已有队列或等待）',[r[g]['strict_ready_backlog'].get('unassigned_physically_ready_unique_operations') for g in groups])
 row('待执行计划中已因路线或访问次数变化失效的任务',[len(r[g]['strict_ready_backlog'].get('observed_invalid_pending_task_ids',[])) for g in groups])
 row('程序判定缺计划的机组',[r[g]['strict_ready_backlog'].get('program_reported_gap_machine_count') for g in groups])
 row('未被生产任务预留的机组时间（机组秒，含合理空闲）',[s['results'][g]['common_window_quality']['unreserved_machine_seconds'] for g in groups])
 for label,key in [('程序口径缺计划等待（机组秒）','executable_unplanned_machine_seconds'),('队列等待（批次秒）','queue_wait_lot_seconds'),('加权迟交累计（批次秒）','weighted_tardy_lot_seconds'),('换型损失（秒）','setup_loss_seconds'),('生产任务实际开工数','production_dispatches'),('开工涉及批次数（跨工序累计）','operation_lots_dispatched'),('平均批量填充率','batch_fill_mean'),('完成批次','throughput_lots')]:row(label,[r[g]['whole_window']['quality'][key] for g in groups])
 row('首个输入包直接包含的工序明细',[r[g]['packets'][0]['inline_operations'] for g in groups])
 row('最后一个输入包直接包含的工序明细（各自终点）',[r[g]['packets'][-1]['inline_operations'] for g in groups])
 row('共同区间单次最高已知服务端输入 tokens',[max((a.get('usage') or {}).get('input_tokens',0) for a in c['results'][g]['attempts'][:r[g]['calls_to_common_endpoint']]) for g in groups])
 row('推进到共同终点的已知服务端输入 tokens',[r[g]['common_usage']['input_tokens'] for g in groups])
 row('全部实际调用的已知服务端输入 tokens',[s['results'][g]['usage']['input_tokens'] for g in groups])
 row('全部实际调用耗时（真实秒）',[s['results'][g]['usage']['model_seconds'] for g in groups])
 row('已提交排程中最慢一轮的模型调用合计耗时（真实秒）',[r[g]['maximum_completed_cycle_model_seconds'] for g in groups])
 row('模型调用合计超过 135 真实秒的已提交排程轮数',[r[g]['completed_cycles_over_135_real_seconds'] for g in groups])
 lines+=['','调用包含读资料、生成提案、确认提交、修正及失败请求；一轮成功排程通常需要提案、确认两次调用。重排次数不包含首次排程，以及 882 / 1800 秒人为观察截止造成的停顿。','',
  '若各组结束时间不同，排程效果和未排需求按共同终点比较；全部实际调用及耗时仍包含共同终点之后已发生的花费，不能混作同区间效率。“推进到共同终点所需调用”截止于使模拟到达该时点的既有提交；到达后才开始的查询、修改与失败不计入这一效率数字，全部保留在实际花费中。共同终点已发生的重排提醒仍计入触发次数，即使它尚未完成新一轮提交。','',
  '未排公共工序含尚未可执行的未来条件工序；非条件工序也可能仍需等待资源。不能把这两个数量直接当作“现在就能开工却被遗漏”的数量。待执行任务数量包含已触发失效、尚未由模型修改的任务，失效数量另列。全厂物理可加工口径不执行已有队列顺序或显式等待，因此不是可以让程序自动插入生产的任务清单。','',
  '共同终点，三组各有同一项 w1703:86:1 满足物理加工条件但未分配，涉及机组 325 / 326；程序的缺计划机组数却都为零。说明“有队列或显式等待就不报缺计划”的统计口径会隐藏此类未分配工作，零缺计划等待不能解释为零遗漏。G1 / G2 的待执行任务中各有一项已因路线或访问次数变化失效；终点恰好触发了计划失效提醒，本比较保留提醒发生后、模型尚未修正的状态。','',
  '未被生产任务预留的机组时间包括正常无料、资源限制等合理空闲，不能全部归为可避免的排程等待。模型思考期间模拟时钟暂停，因此机组等待不包含模型响应的真实耗时；不能据此证明真实工厂不会等模型。整轮耗时按同一决策上下文的全部查询、提案、确认和失败调用求和，不含人工批准与离线检查时间。135 秒是当前预测提前量；两种时钟的数值对照用于说明局限，不等于本轮已实测真实工厂接续迟延。','',
  '## 共同观察区间的调用构成','', '| 调用类型 | G0 | G1 | G2 |','|---|---:|---:|---:|']
 for label,tools in [('查询资料',('read_entities','read_artifact','get_context')),('生成提案',('propose_delta','begin_proposal','begin_alternative_proposal','append_delta_chunk','seal_proposal')),('明确确认提交',('apply_candidate',)),('服务端失败',('transport_failure',))]:row(label,[sum(r[g]['common_call_types'].get(t,0) for t in tools) for g in groups])
 lines+=['','这些调用均计入推进到共同终点的总数；提案校验被拒后的修正也计入相应调用类型。G1 的 69 次包含 1 次服务端失败，扣除后是 68 次业务调用，仍高于 G0 的 56 次。','',
  'G2 的查询资料调用由 G1 的 22 次降为 8 次，但提案由 23 次升为 31 次、确认提交由 23 次升为 30 次，所以总调用没有下降。G2 首次直接带入 2491 项工序，G1 为 700 项；服务端也实际报告了超过小窗口大小的单次输入，扩容确实被使用。更多资料没有自动转化为更完整、更少修订的计划。G2 的已知累计输入约为 G1 已知下界的 2.06 倍；因 G1 有一次未知用量，不能据此给出精确费用倍数。','',
  '## 前后两段对比','', '| 指标 | G0 | G1 | G2 |','|---|---:|---:|---:|']
 row('上一轮 702→882 秒调用',[r[g]['previous_calls'] for g in groups])
 row('这次新增区间所需调用',[r[g]['calls_to_common_endpoint']-r[g]['previous_calls'] for g in groups])
 for label,segment,key in [('前 180 秒开工数','early_window','production_dispatches'),('新增区间开工数','extension_window','production_dispatches'),('前 180 秒队列等待','early_window','queue_wait_lot_seconds'),('新增区间队列等待','extension_window','queue_wait_lot_seconds')]:row(label,[r[g][segment]['quality'][key] for g in groups])
 lines+=['','前 180 秒指标与上一轮逐项一致。这是原实验的延长观察，不是又跑了一次相同实验。两个时段长度不同，不直接比较各时段的绝对等待总量。','', '## 新增区间触发时间','']
 for g in groups:
  lines.append(f"- {g}："+'、'.join(fmt(t) for t in sorted(r[g]['extension_trigger_times']))+f" 秒；原因：{r[g]['extension_trigger_reasons']}。")
 lines+=['','## 已有计划的执行证据','']
 for g in groups:
  data=r[g]['inherited_task_dispatches'];text='；'.join(f"机组 {e['machine']} 在 {fmt(e['time'])} 秒开工（原定 {fmt(e['planned_not_before'])} 秒；{'未调整' if e['unchanged_from_882'] else '模型已调整'}）" for e in data)
  lines.append(f'- {g}：{text or "共同观察区间内未见新增开工"}。')
 lines+=['','这里仅统计 882 秒前已获模型确认、保留原任务编号及工序集合、且在延长区间真正开工的任务；它是严格可追溯的旧计划执行数量。数量不能直接换算成节省的模型调用：一次调用可以处理多台机组，其他未排需求仍可触发模型。','',
  '## 一个可核对的重复补排案例','',
  'G1 在 1092.12 秒已把工序 w1462:131:1 排给机组 1299，规定最早 1289.27 秒开工。到 1161.81 秒，工序已经实际就绪。其他空闲且能加工它的机组没有自己的队列，于是被程序报为缺计划；程序在这一步没有扣掉已经分配给其他机组的工序。',
  '执行器遵守模型给出的最早开工时间，不能自行把 1289.27 改成 1161.81。模型随后通过第 9、10、11 次调用分别查询资料、修改提案、确认提交，把同一任务改给机组 1295 并提前开工。任务并未被程序清空；这三次调用用于调整一个已排任务。',
  '第 9 次输入已经包含原任务，但没有该工序的完整明细。待排资料组织会扣除全厂已分配工序，触发检查却仍把它算作另一台机组的可开工候选，两处口径不一致。第 10、11 次输入在补查后带回了工序明细。扩大窗口本身不会消除这个触发与装包口径的差异。',
  f"案例原始调用、输入对象引用及前后计划：[证据]({RUN/'already_planned_replan_case.json'})。相关逻辑：[触发与执行]({ROOT/'src/smt_fullfab/environment.py'}:237)、[已排工序过滤]({ROOT/'src/smt_fullfab/harness/batch_window.py'}:30)。",'',
  '这个案例证明机制会导致额外调用，不代表每次补查都由同一原因造成；模型自主查询、提案修正以及其他真实新需求也计入总调用。下一轮可优先验证真正缺计划与已有计划可提前执行的区别，并区分预测开工时间和必须遵守的最早开工约束。','',
  '## 提前安排有效，但可能被其他开销抵消','',
  '在 1386.18→1448.73 秒这一段，G0、G1的已提交计划都包含 w421:149:1 和 w422:149:1，最早开工条件设为 1387.18 秒。它们随后自动执行，整段没有再调用模型。G2当时没有安排这两项，先后在 1444.48 和 1447.18 秒停下，额外使用第 40—43 次共4次调用。这里确实观察到了提前排好任务能够减少后面的调用；G0同样具备这种执行能力。',
  '但G1在此之前还有额外成本：第31次调用的反馈指出，任务 d34-421 的最早开工时间 1343.0146 已早于当前 1343.6907，必须显式修改。该字段是最早允许开工的条件，任务还在等待物料；当前编译规则仍拒绝直接保留这个过去的时间。这会迫使模型在其他事件触发重新提交时，一并改写仍可等待执行的旧任务。',
  f"局部执行与改写要求的原始证据：[执行案例]({RUN/'execution_cases.json'})；相关编译规则：[plan_delta.py]({ROOT/'src/smt_fullfab/plan_delta.py'}:225)。这说明需要把局部省掉的调用与前期查询、改写的总成本一起比较，不能仅凭单个成功接续宣称总体更优。",'',
  '## 共同区间之后的额外观察','',
  '以下现象发生在 1603.10 秒之后，只用于解释额外花费与机制局限，不纳入上面的同区间效率排名。',
  'G0 在 1649.82 秒的第 68—77 次连续 10 次调用都在读资料，没有提交新计划。输入当时只直接展示 26 项任务中的 14—15 项，执行状态也不完整；最近一次查询结果完整返回，较早的结果在历史中保留引用。模型随后交替读取任务、执行状态及旧查询结果。局部资料展示和只保留最近完整结果可能促成反复查询，但不能据此断言每次查询都不可避免，也没有发现最新反馈错序。',
  f"查询顺序、输入摘要和原始引用：[G0 查询案例]({RUN/'G0_read_cycle_case.json'})。因此，G0 在选定共同区间调用较少，并不意味着原规则在更长区间始终更省。",'',
  '## 校验与限制','',f"- 原 B 源文件核对：{x['verification']['original_B_unchanged']}；上一轮 {x['verification']['previous_files_checked']} 个文件变化数：{len(x['verification']['previous_files_changed'])}。",
  f"- 新增实际调用 {x['verification']['actual_new_calls']} 次，含此前的累计调用 {x['verification']['cumulative_actual_calls']} 次，未知用量 {x['verification']['unknown_usage_calls']} 次。",
  f"- 生产任务全部来自模型的明确提案与确认：{x['verification']['all_production_choices_from_model']}。",
  f"- 计划继承、调用成本、机会覆盖、物理前缀检查：{x['verification']['all_inheritance_audits_pass']} / {x['verification']['all_cost_audits_pass']} / {x['verification']['all_opportunity_audits_pass']} / {x['verification']['all_physical_prefix_checks_pass']}。",
  '- 原模拟终点仍是 3600 秒，本轮没有伪造结束事件。物理审计仅保留预期的 missing terminal event，不把短观察冒充全程完成。',
  f"- 排程与执行、资料组织、模型和推理强度均保持上一轮设置。累计调用资源上限先设为28，后登记为64；本报告最终登记的每组累计上限为{s['per_group_call_cap']}。所有阶段的调用均保留，已完成的组不会为增加上限而重新运行。",
  '- G1 第 15 次容量失败无排程输出、用量未知，经用户明确批准重试一次后恢复。'+('第 70 次又发生连接失败，用户另行批准该次重试一次；之后第 72 次再度连接失败，用户选择不再重试。G2 第 76 次发生流连接中断，也未重试。' if (RUN/'comparison_boundary_decision.json').exists() else '')+'所有失败计入调用和耗时，tokens 只报告已知下界。存在未知用量的组，其完整成本审计标记为不完整；失败记录及获准重试的原始证据均保留。',
  '- 续跑阶段曾因绝对截止时间仍沿用旧值而停止，已在新接续记录中按“原始创建时间＋已经登记的时长上限”修正。工厂状态、候选提案、模型结果、生产规则和累计费用均继承；未重放已经成功的调用。G1 第二次重试最初的离线准备也遇到旧快照标识冲突，该准备没有调用模型，记录保留。',
  '- 单一保存状态、每组一条模型轨迹。加工与运输按批次、工序、访问次数组成的事件键抽样；相同事件键共享随机时长。模型若改变组批、机组或开工时机，仍会改变实际排程结果。',
  '- 本轮是接续排程实验，不是初始全量机组排程，也没有模拟 2000 台机组。','']
 (RUN/'结果说明.md').write_text('\n'.join(lines))
 print(RUN/'结果说明.md')
if __name__=='__main__':main()
