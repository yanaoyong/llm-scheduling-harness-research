#!/usr/bin/env python3
"""Analyze the sealed paired run. No transport, simulator advancement or B DB."""
from pathlib import Path
from collections import Counter
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence

RUN=ROOT/'live_pilots/two_strategy_20261016'


def clipped_wait(trace,start,end):
    if end <= start:return None
    seconds=0.
    for event in trace:
        if event['kind']=='time_advance' and 'deferred_gap_machines' in event:
            seconds += len(event['deferred_gap_machines'])*max(0.,min(end,event['to'])-max(start,event['time']))
    return seconds


def summarize():
    comparison=json.loads((RUN/'comparison.json').read_text())
    reg=json.loads((RUN/'registration.json').read_text())
    start,end=comparison['common_window']; rows={}
    for group,result in comparison['results'].items():
        ev=Evidence(RUN/group,result['evidence_sha256'])
        trace=[ev.get(ref) for ref in ev.value['physical']]
        suffix=trace[ev.manifest['prefix_events']:]
        feedback=list(ev.rows('feedback').values())
        commits=sorted(ev.rows('commits').values(),key=lambda c:c['trace_start']); candidates=ev.rows('candidates')
        context_by_ref=ev.rows('contexts'); contexts=list(context_by_ref.values())
        transport_errors=[]; queries=[]
        public=ev.rows('public')
        for attempt in sorted(ev.rows('attempts').values(),key=lambda a:a['index']):
            transport=attempt.get('transport') or {}
            if not transport.get('channel_valid') and transport.get('events_ref'):
                for line in ev.raw(transport['events_ref']).splitlines():
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('type')=='error':
                        transport_errors.append({'index':attempt['index'],'call_number':attempt['index']+1,'message':event.get('message')})
            if attempt.get('raw_ref'):
                try:action=json.loads(ev.raw(attempt['raw_ref']));action=action.get('action',action)
                except (ValueError,TypeError):continue
                if action.get('tool')=='read_artifact':
                    queries.append({'index':attempt['index'],'kind':public.get(action['artifact_ref'],{}).get('kind'),
                                    **{k:action[k] for k in ('path','format','offset','count')}})
                elif action.get('tool')=='read_entities':
                    queries.append({'index':attempt['index'],'queries':action['queries']})
        decisions=[]
        for receipt in commits:
            candidate=candidates[receipt['candidate_ref']]; delta=candidate['delta']
            context=context_by_ref[candidate['context_ref']]
            machines={m['machine']:m for m in context['problem']['machines']}
            added=delta['tasks']['add']
            decisions.append({'time':receipt['time'],'plan_tasks':len(candidate['compiled']['plan']['tasks']),
                'added_tasks':len(added),'added_tasks_on_busy_machines':sum(bool(machines[t['machine']].get('currently_busy')) for t in added),
                'kept_tasks':len(candidate['compiled']['plan']['tasks'])-len(added)-len(delta['tasks']['replace']),
                'cancelled_tasks':len(delta['tasks']['cancel_ids']),
                'replaced_tasks':len(delta['tasks']['replace']),
                'holds':len(candidate['compiled']['plan']['holds']),
                'batch_id':receipt.get('batch_coverage',{}).get('batch_id')})
        model_attempts=result['attempts']
        metrics=result.get('common_metrics')
        quality=None
        if metrics is not None:
            families=metrics['production_family_statistics']
            quality={k:metrics[k] for k in ('observed_seconds','weighted_tardy_lot_seconds',
                'throughput_lots','throughput_wafers','setup_loss_seconds','batch_fill_mean','terminal_wip_lots')}
            quality.update(queue_wait_lot_seconds=sum(x['queue_wait_lot_seconds'] for x in families.values()),
                production_dispatches=sum(x['dispatches'] for x in families.values()),
                operation_lots_dispatched=sum(x['operation_lots_dispatched'] for x in families.values()),
                unreserved_machine_seconds=sum(x['machine_count']*(1-x['reserved_observed_fraction'])*(end-start) for x in families.values()),
                executable_unplanned_machine_seconds=clipped_wait(trace,start,end))
        stops=[{'from':f['from'],'to':f['to'],'advanced_seconds':f['advanced_seconds'],
                'reason':f['stop_reason']['reason'],'dispatches':f['dispatch_count_delta'],
                'pending_demand_count':f['stop_reason'].get('pending_demand_count'),
                'incoming_operation_count':f['stop_reason'].get('capacity',{}).get('incoming_operation_count')}
               for f in feedback]
        for stop in stops:
            observed=[c for c in contexts if c['time']==stop['to'] and (c.get('trigger') or {}).get('reason')==stop['reason']]
            if observed:
                c=observed[-1];trigger=c['trigger'];ids=set(c.get('planning_batch',{}).get('operation_ids',[]))
                deadline=trigger.get('forecast_deadline')
                due=[d for d in c.get('batch_demands',[]) if d.get('forecast_available_at') is not None
                     and deadline is not None and abs(d['forecast_available_at']-15-deadline)<1e-6]
                stop['forecast_trigger_machines']=[d['machine'] for d in due]
                stop['forecast_machines_without_offered_operations']=[d['machine'] for d in due if not ids.intersection(d['operation_ids'])]
                opmap={o['operation_id']:o for o in c['problem']['operations']}
                stop['forecast_demands']=[{'machine':d['machine'],'forecast_available_at':d['forecast_available_at'],
                    'candidate_operations':len(d['operation_ids']),
                    'nonconditional_operations':sum(not opmap[oid]['conditional'] for oid in d['operation_ids']),
                    'offered_candidates':len(ids.intersection(d['operation_ids']))} for d in due]
                stop['next_batch']={k:v for k,v in c.get('planning_batch',{}).items() if k in
                    ('batch_id','strategy','offered_operation_count','not_yet_offered_count','cohort_operation_count')}
        calls_to_common=None
        if end>start:
            crossing=next((f for f in sorted(feedback,key=lambda x:x['event_start']) if f['to']>=end),None)
            if crossing:
                preceding=[c for c in commits if c['trace_end']<=crossing['event_start']]
                if preceding:
                    selected=max(preceding,key=lambda c:c['trace_end'])['selection_attempt_id']
                    index=ev.rows('attempts')[selected]['index']
                    calls_to_common=sum(a['index']<=index and a['channel']=='codex' for a in ev.rows('attempts').values())
        zero=[x for x in stops if x['advanced_seconds']==0]
        same_old_capacity=[x for x in zero if x['reason']=='capacity_limit' and x['incoming_operation_count']==0]
        final_context=context_by_ref[result['head']['context_ref']]
        dispatched=set(final_context['execution_state']['dispatched_task_ids'])
        pending=[t for t in final_context['base_plan']['tasks'] if t['id'] not in dispatched]
        reserved={oid for t in pending for oid in t['operation_ids']}
        unassigned=[o for o in final_context['problem']['operations'] if o['operation_id'] not in reserved]
        batches=sorted((c['planning_batch'] for c in contexts),key=lambda b:b['opened_at'])
        rows[group]={'total_calls':result['usage']['actual_model_attempts'],
            'calls_to_reach_common_endpoint':calls_to_common,
            'completed_responses':sum(x['transport_valid'] is True for x in model_attempts),
            'unknown_usage_calls':result['usage']['unknown_usage'],
            'call_types':result['call_types'],'usage':result['usage'],
            'query_details':queries,'transport_errors':transport_errors,
            'model_commits':result['model_commits'],'decisions':decisions,
            'observed_seconds':result['observed_seconds'],'observed_end':result['head']['time'],
            'target_reached':result['head']['time']>=comparison['target_window'][1],
            'final_stop_reason':result['head']['stop_reason'],
            'initial_backlog':result['initial_backlog'],'final_backlog_at_own_endpoint':result['backlog'],
            'final_unassigned_public_operations':len(unassigned),
            'final_unassigned_nonconditional_operations':sum(not o['conditional'] for o in unassigned),
            'committed_added_tasks':sum(d['added_tasks'] for d in decisions),
            'committed_added_tasks_on_busy_machines':sum(d['added_tasks_on_busy_machines'] for d in decisions),
            'first_packet':model_attempts[0]['packet'],
            'planning_batches':[{k:b[k] for k in ('batch_id','opened_at','strategy','offered_operation_count','not_yet_offered_count','cohort_operation_count')} for b in batches],
            'planning_stops':stops,'planning_stop_counts':dict(Counter(x['reason'] for x in stops)),
            'zero_time_stops':zero,'old_capacity_immediate_retrigger_count':len(same_old_capacity),
            'common_window_quality':quality,'provenance_audit':result['provenance_audit'],
            'physical_prefix_errors':result['physical_prefix_errors'],
            'opportunity_audit_valid':result['opportunity_audit']['valid'],
            'service_input_tokens_per_response':[x['usage']['input_tokens'] for x in model_attempts if x['usage']],
            'attempt_errors':[{'index':x['index'],'error':x['error']} for x in model_attempts if x['error']]}
    report={'schema':'two-strategy-live-summary-v1','common_window':[start,end],
        'target_window':comparison['target_window'],'per_group_call_cap':reg['per_group_call_cap'],
        'results':rows,'isolation_after':comparison['isolation_after'],
        'audit_compatibility':json.loads((RUN/'audit_compatibility_check.json').read_text()),
        'both_reached_target':all(r['target_reached'] for r in rows.values()),
        'limitations':comparison['limitations']+[
            'Final backlog is measured at each own endpoint; compare directly only if endpoints match.',
            'Unreserved machine time includes downtime and absence of feasible work; it is not all avoidable scheduling delay.',
            'Executable-unplanned machine seconds can count alternative machines for the same operation; it is not a count of unique orders.',
            'Pending demand ledger excludes machines already covered by queues/holds; its operation count is not the full unscheduled backlog. Global unassigned public operations are reported separately and include future conditional work.',
            'Short-window tardiness and finished-lot throughput may be insensitive; dispatch and ready-wait measures supplement them.']}
    (RUN/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 两种窗口：实际模型小规模对比','',
        '**结论：本轮消除了提交后同批旧资料立即触发容量重排；大窗口确实容纳更多资料、在共同区间少用了两次调用。但机组预测提醒仍造成 6.75 秒的短间隔续排，不能据此认为频繁重排已经解决，也不能证明长期质量改善。**','',
        '两组使用同一 mixed_702 保存状态与公共负载；生产任务均由模型选择。',
        'G1 窗口/预算 272000/220000；G2 544000/440000；模型 gpt-6-astra / medium。',
        f'每组最多 {reg["per_group_call_cap"]} 次调用，目标模拟区间 702–882 秒；实际共同区间 {start:g}–{end:g} 秒。',
        'G1 用满 8 次额度；G2 第 6 次连接失败、用量未知，按登记规则停止且不重试。两组均未到达 882 秒。该保存状态是接续场景，本轮不是冷启动 2000 台机组实测。','',
        '| 指标 | G1 | G2 |','|---|---:|---:|']
    def row(label,values):lines.append('| '+label+' | '+' | '.join(map(str,values))+' |')
    for label,key in [('总调用（含失败）','total_calls'),('抵达共同终点时累计调用','calls_to_reach_common_endpoint'),('完整响应','completed_responses'),
        ('已确认计划数','model_commits'),('推进模拟秒数','observed_seconds'),('最终模拟时刻','observed_end'),
        ('未知用量调用','unknown_usage_calls'),('同批旧资料容量立即重触发','old_capacity_immediate_retrigger_count')]:
        row(label,[rows[g][key] for g in ('G1','G2')])
    row('服务端已知输入 tokens',[f'{rows[g]["usage"]["input_tokens"]:,}'+('（下界）' if rows[g]['unknown_usage_calls'] else '') for g in ('G1','G2')])
    row('模型请求累计墙钟秒',[round(rows[g]['usage']['model_seconds'],2) for g in ('G1','G2')])
    for label,key in [('最终可开工未覆盖机组','uncovered_executable_machine_count'),
        ('需求台账内待排候选工序（含未来）','pending_demand_operation_count'),
        ('最终已接受未启动任务','accepted_pending_task_count')]:
        row(label,[rows[g]['final_backlog_at_own_endpoint'][key] for g in ('G1','G2')])
    for label,key in [('全公共目录未排工序（含未来）','final_unassigned_public_operations'),
        ('其中非条件工序（不等于现在可开工）','final_unassigned_nonconditional_operations'),
        ('两次确认累计新增任务','committed_added_tasks'),
        ('其中提前排给忙碌机组的任务','committed_added_tasks_on_busy_machines')]:
        row(label,[rows[g][key] for g in ('G1','G2')])
    lines += ['', '末端均为 768 秒，因此上述时点指标可以并列。台账只收集缺少后续计划的机组，其数量不能替代全厂未排工序总量；全公共目录计数仍含未来工序，不等于当前必须开工的订单数。',
        '两组都保留了有效未执行任务，没有取消、替换或用显式等待掩盖需求；共同区间均实际启动 5 项。G1 在第 8 次产生的第三份提案没有得到模型确认，不计入已排任务。','',
        '## 扩容是否真正用上','',
        f'首包完整工序记录：G1 {rows["G1"]["first_packet"]["inline_operations"]} 条，G2 {rows["G2"]["first_packet"]["inline_operations"]} 条。',
        f'服务端首请求输入：G1 {rows["G1"]["service_input_tokens_per_response"][0]:,} tokens，G2 {rows["G2"]["service_input_tokens_per_response"][0]:,} tokens。G2 已超过 272,000，证明实际使用了扩大的容量；未测满整个 544,000 上限。',
        '推进到相同 768 秒，G1 的两次确认之前额外查询了两次公共资料；G2 两轮均直接提案并确认。因此共同终点累计调用为 6 对 4。全轮 8 对 6 还包括到达终点后的查询、未确认提案和连接失败，不能作为完整处理目标负载的效率结论。','',
        '## 共同观察区间的等待与质量','']
    if end>start:
        lines += ['| 指标 | G1 | G2 |','|---|---:|---:|']
        for label,key in [('可开工但未排程机组秒','executable_unplanned_machine_seconds'),
            ('物料排队等待秒','queue_wait_lot_seconds'),('生产任务启动数','production_dispatches'),
            ('启动工序物料数','operation_lots_dispatched'),('整批完工数','throughput_lots'),
            ('加权延误物料秒','weighted_tardy_lot_seconds'),('换型损失秒','setup_loss_seconds')]:
            row(label,[round(rows[g]['common_window_quality'][key],3) if isinstance(rows[g]['common_window_quality'][key],float)
                       else rows[g]['common_window_quality'][key] for g in ('G1','G2')])
    else:lines += ['没有正长度共同观察区间，等待和质量不能比较，也不能记为零。']
    lines += ['', '等待差异可定位到机组 1288：G2 首轮已为它提交后续任务，于 708.75 秒开始执行；G1 首轮没有安排，直到 761.25 秒第二轮提交后才执行，多等待 52.5 秒。这说明提前给忙碌机组排后续任务在当前执行器中有效。']
    lines += ['', '## 再次排程的原因','']
    for group,r in rows.items():
        calls=r['call_types']
        lines += [f'**{group}**：提案 {calls.get("propose_delta",0)} 次、确认 {calls.get("apply_candidate",0)} 次、资料查询 {calls.get("read_artifact",0)+calls.get("read_entities",0)} 次、连接失败 {calls.get("transport_failure",0)} 次；最终停止原因 `{r["final_stop_reason"]}`。','']
        for failure in r['transport_errors']:
            lines += [f'- 第 {failure["call_number"]} 次请求：{failure["message"]}；用量未知，不重试。']
        for stop in r['planning_stops']:
            lines.append(f'- {stop["from"]:g} → {stop["to"]:g} 秒：`{stop["reason"]}`，启动 {stop["dispatches"]} 项任务。')
        lines += [f'- 零时间推进的再次决策：{len(r["zero_time_stops"])} 次。',
                  f'- 生产来源审计通过：{r["provenance_audit"]["commits"]} 次确认和对应批次回执，算法代选生产任务 {r["provenance_audit"]["algorithm_production_tasks"]} 项。',
                  f'- 物理前缀检查保留错误：{r["physical_prefix_errors"]}；部分区间没有伪造终态。','']
    lines += ['## 还会短间隔续排的因果关系','',
        '702 秒提交后，两组的既有计划都持续执行到 761.25 秒。机组 1229 的公开预计空闲时刻为 776.25 秒；提前量是 15 秒，所以此时触发续排。',
        '761.25 秒提交后，又运行 6.75 秒到 768 秒。机组 1295、1296 的公开预计空闲时刻为 783 秒，且没有已提交后续任务，因此又触发续排。两次都是不同的预测提醒，不是同批旧资料重复触发容量阈值。',
        '规则会找到全厂最早到期的一条预测提醒；即使一次新增了很多其他任务，也不能消除尚未覆盖机组的提醒。当前没有把相近预测提醒合并处理的机制，所以扩大上下文不会自动消除这种打断。',
        '而且这两次提醒所涉及的 1229、1295、1296，其候选全部是 conditional=true 的后续工序：还有前序/物料状态条件，不是当前已就绪工序。现规则只检查“机组快空闲且有候选”，没有检查这些候选是否已有可支撑的近期到料计划；因此会把潜在未来需求也变成暂停点。它们可以提前规划，但不等于已经存在必须马上排程的可执行任务。',
        '资料批次与触发原因还有错位：768 秒的 G2 批次只装 4 条新增或变化记录，1295、1296 各有 188 条待排候选，但本包包含其中 0 条。因为只要存在新资料，装包就先排除展示过的旧资料；“以前看过”并不等于“已经安排”。完整资料仍可查询，但这可能增加后续查询，削弱大窗口作用。G2 随后确实查询了公共问题，再下一次请求连接失败；不能据此断言再提交后一定会循环。',
        '建议下一步优先讨论：用“机组将空闲 + 存在近期有前序支撑的接续需求”约束提前提醒，合并临近预测；每次触发时优先装入导致触发的机组及其未安排资料。保持已有任务继续执行，60 秒可开工等待期限不变。这里只调整何时询问和提供什么资料，生产任务仍由模型选择。本轮没有修改这些运行规则或补跑。','']
    iso=report['isolation_after']
    lines += ['## 解释边界','',
        '全部查询、提案、确认、修正及失败都计入调用；失败请求用量未知时，已报告 tokens 只是下界。',
        '一次小样本不能代表稳定效果。只有完成相同观察区间、且未处理需求和质量可比时，才能讨论调用效率。',
        '模型思考时模拟时钟暂停，墙钟耗时不等于机组模拟等待。短窗口可能没有整批完工或延误变化。',
        '本轮只有 66 秒：G2 的可开工未排等待更少，但两组整批完工均为零，延误和换型指标相同，只能说明这段观察结果，不能推断长期质量。',
        '可开工未排机组秒可能涵盖同一工序的多台可选机组，不能视作同等数量订单。',
        '运行完成并封存后，仅适配汇总审计对新增 planning_batch_accepted 事件的检查。生产来源与批次回执审计通过；伪造/删除回执的反向检查被拒绝，旧版证据仍通过。模型输入、输出、计划与执行轨迹未更改。完整物理审计仍报告缺少终态事件，因为这里只观察了部分区间，不能称全程排程验证通过。',
        f'原来源 {iso["files_checked"]} 项校验，变更 {len(iso["changed_source_files"])} 项；未打开原 B 运行数据库。',
        '完整数据见 summary.json；原始逐次证据见各组 evidence_manifest.json 和 comparison.json。']
    (RUN/'结果说明.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'common_window':[start,end],'both_reached_target':report['both_reached_target'],
        'groups':{g:{k:r[k] for k in ('total_calls','observed_seconds','model_commits','planning_stop_counts','common_window_quality')} for g,r in rows.items()}},ensure_ascii=False,indent=2))


if __name__=='__main__':summarize()
