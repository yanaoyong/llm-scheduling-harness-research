#!/usr/bin/env python3
"""Read sealed pilot evidence; no model calls and no Runtime/Store creation."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.factory import restore
from src.smt_fullfab.harness.contracts import strict_json,sha_bytes

OLD=ROOT/'live_pilots/paired_20261016'
NEW=ROOT/'live_pilots/paired_20261016_cli_fix'
reg=strict_json((NEW/'registration.json').read_bytes())
assert sha_bytes((OLD/'comparison.json').read_bytes())==reg['prior_results_sha256']
old=strict_json((OLD/'comparison.json').read_bytes()); new=strict_json((NEW/'comparison.json').read_bytes())
results={}
for group,r in new['results'].items():
    ev=Evidence(NEW/group,r['evidence_sha256'])
    trace=[ev.get(ref) for ref in ev.value['physical']]
    env=restore(ev.get(ev.value['head']['state_ref']),trace)
    pending=[t for ts in env._pending().values() for t in ts]
    commits=ev.rows('commits');candidates=ev.rows('candidates');contexts=ev.rows('contexts');attempts=ev.rows('attempts')
    committed=[]
    for c in sorted(commits.values(),key=lambda c:c['trace_start']):
        candidate=candidates[c['candidate_ref']];ctx=contexts[candidate['context_ref']]
        a=strict_json(ev.raw(attempts[candidate['attempt_id']]['raw_ref']));a=a.get('action',a)
        machines={m['machine']:m for m in ctx['problem']['machines']}
        tasks=a['delta']['tasks']['add']
        busy=[t for t in tasks if machines[t['machine']].get('currently_busy')]
        committed.append({'task_count':len(candidate['compiled']['plan']['tasks']),'added_tasks':len(tasks),
                          'added_tasks_on_busy_machines':len(busy),'busy_machine_count':len({t['machine'] for t in busy}),
                          'future_start_tasks':sum(t['not_before']>ctx['time'] for t in tasks),
                          'future_start_range':[min(t['not_before'] for t in tasks),max(t['not_before'] for t in tasks)]})
    result={'total_cli_attempts_including_startup_failure':old['results'][group]['usage']['actual_model_attempts']+r['usage']['actual_model_attempts'],
            'local_startup_failures_retained':old['results'][group]['usage']['actual_model_attempts'],
            'real_transport_attempts':r['usage']['actual_model_attempts'],
            'completed_model_responses':sum(a['transport_valid'] is True for a in r['attempts']),
            'transport_failures_with_unknown_usage':r['usage']['unknown_usage'],
            'reported_input_tokens':r['usage']['input_tokens'],'reported_output_tokens':r['usage']['output_tokens'],
            'reported_tokens_are_lower_bound':r['usage']['unknown_usage']>0,
            'call_types':r['call_types'],'model_commits':r['model_commits'],'committed_plans':committed,
            'production_dispatches':r['production_dispatches'],'accepted_pending_task_count_corrected':len(pending),
            'uncovered_executable_machine_count':r['backlog']['uncovered_executable_machine_count'],
            'pending_future_or_ready_demand_machine_count':r['backlog']['pending_demand_machine_count'],
            'pending_demand_operation_count':r['backlog']['pending_demand_operation_count'],
            'simulated_seconds_advanced':r['observed_seconds'],'stop_reason':r['head']['stop_reason'],
            'machine_wait_comparison':None,'scheduling_quality_comparison':None,
            'metric_unavailable_reason':'No positive common simulated-time interval; do not interpret zero advancement as zero waiting.',
            'physical_prefix_errors':r['physical_prefix_errors'],'provenance_audit':r['provenance_audit'],
            'execution_feedback':list(ev.rows('feedback').values()),'attempts':r['attempts']}
    results[group]=result
report={'schema':'capacity-paired-live-summary-v1','results':results,'comparison_valid_for_quality':False,
        'common_observed_seconds':new['common_window'][1]-new['common_window'][0],
        'total_cli_attempts':sum(r['total_cli_attempts_including_startup_failure'] for r in results.values()),
        'total_real_transport_attempts':sum(r['real_transport_attempts'] for r in results.values()),
        'preserved_startup_evidence':str(OLD/'comparison.json'),'live_evidence':str(NEW/'comparison.json'),
        'isolation_after':new['isolation_after'],
        'measurement_correction':'Runner initial/progress accepted_pending_task_count compared string task IDs against version/id pairs. Summary recomputes exact pending tasks via the restored plan state; no simulation, prompt, action or other metric is changed.',
        'findings':['G2 service-reported first input exceeded 272000 tokens; expansion was exercised.',
                    'G1 committed a multi-task plan including busy-machine follow-ups, but capacity_limit fired at the same simulation time after dispatch.',
                    'G2 shortened plan validity below a retained future start and was rejected; its next request suffered a transport failure, not demonstrated context-capacity rejection.',
                    'Cannot compare quality, waiting or successful-demand calls because neither group advanced the simulation clock.'],
        'next_design_discussion':'Capacity should bound and page a specific unprocessed batch, with an acknowledged batch/version boundary. It should not repeatedly stop plan execution merely because the entire future-demand catalog exceeds a watermark. Keep actual-ready deadlines and genuine plan-invalidations as independent triggers; scheduling choices still remain with the model.'}
(NEW/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
lines=['小规模实际模型对比结果','', '两组使用同一 mixed_702 保存状态、同一负载，目标观察至 822 秒。',
       '窗口/输入预算：G1 272000/220000；G2 544000/440000。模型均为 gpt-6-astra，medium。',
       '此前两次本地 CLI 目录解析失败完整保留；兼容性修正后两组共用桌面端 CLI，并各剩 5 次额度。','']
for g,r in results.items():
    lines += [g, f"总启动尝试 {r['total_cli_attempts_including_startup_failure']}；其中本地启动失败 {r['local_startup_failures_retained']}、实际请求 {r['real_transport_attempts']}、完整模型响应 {r['completed_model_responses']}。",
        f"调用类型：{r['call_types']}。已确认计划 {r['model_commits']}，实际启动任务 {r['production_dispatches']}，已接受未启动任务 {r['accepted_pending_task_count_corrected']}。",
        f"可开工未覆盖机组 {r['uncovered_executable_machine_count']}；全部未覆盖后续/当前需求关联机组 {r['pending_future_or_ready_demand_machine_count']}（不是同等数量的可开工任务）。",
        f"模拟推进 {r['simulated_seconds_advanced']} 秒；停止原因 {r['stop_reason']}。",
        f"已报告输入 tokens {r['reported_input_tokens']}，输出 tokens {r['reported_output_tokens']}；失败请求用量未知 {r['transport_failures_with_unknown_usage']}。",'']
lines += ['关键发现：','1. 第二组首请求服务端输入 393402 tokens，扩容实际生效。',
          '2. 第一组已确认 13 项任务的计划（12 项新增），启动 1 项后在同一时刻被 capacity_limit 打断。',
          '   当时没有可开工未覆盖缺口，仍有 894 台机组的后续需求资料；容量估算 397452，高于第一组阈值 187000。',
          '   程序按整个未覆盖后续需求资料检查容量，没有消耗/确认本批已处理范围，因而容量满可以反复阻止计划继续执行。',
          '3. 第二组首次提案保留 958.5 秒开始的旧任务，却把计划有效期设成 822 秒，校验拒绝；第二次请求连接中断，停止调用。',
          '4. 双方都停在 702 秒。机组等待、吞吐、延误和整体质量没有有效共同观察区间，不能报成零，也不能判定大窗口优劣。',
          '', '下一步宜先讨论容量触发/批次确认边界：容量限制服务于一个待处理批次；已提交计划应继续运行。保留真实可开工等待期限、计划失效等独立触发，生产选择仍全部由模型完成。',
          '', '独立审计：已确认计划的生产选择可回溯至真实模型提案与确认；没有算法代排。物理前缀仅缺终止事件，未伪造完整运行。',
          '原来源 803 项哈希及保存状态不变；未打开原 B 运行数据库。',
          '本轮只是一对小样本，且遇到连接中断和系统时间不连续；不能给出稳定的耗时、成本或质量比较。',
          '完整逐次记录见 summary.json；原始证据与全部失败记录均保留。']
(NEW/'结果说明.txt').write_text('\n'.join(lines)+'\n')
print(json.dumps({g:{k:v for k,v in r.items() if k not in ('attempts','execution_feedback')} for g,r in results.items()},ensure_ascii=False,indent=2))
