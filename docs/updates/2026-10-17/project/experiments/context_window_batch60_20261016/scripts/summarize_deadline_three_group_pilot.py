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

RUN=ROOT/'live_pilots/deadline_three_group_20261017'


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
                'observation_cutoff':f['stop_reason']['reason'] in ('collection_limit','periodic_replan') and f['to']==comparison['target_window'][1],
                'pending_demand_count':f['stop_reason'].get('pending_demand_count'),
                'incoming_operation_count':f['stop_reason'].get('capacity',{}).get('incoming_operation_count')}
               for f in feedback]
        for stop in stops:
            observed=[c for c in contexts if c['time']==stop['to'] and (c.get('trigger') or {}).get('reason')==stop['reason']]
            if observed:
                c=observed[-1];trigger=c['trigger'];ids=set(c.get('planning_batch',{}).get('operation_ids',[]))
                deadline=trigger.get('forecast_deadline')
                due=[d for d in c.get('batch_demands',[]) if d['machine'] in trigger.get('forecast_trigger_machines',[])]
                stop['forecast_raw_deadline']=trigger.get('forecast_raw_deadline')
                stop['forecast_not_before']=trigger.get('forecast_not_before')
                stop['forecast_trigger_machines']=[d['machine'] for d in due]
                stop['forecast_machines_without_offered_operations']=[d['machine'] for d in due if not ids.intersection(d['operation_ids'])]
                opmap={o['operation_id']:o for o in c['problem']['operations']}
                stop['forecast_demands']=[{'machine':d['machine'],'forecast_available_at':d['forecast_available_at'],
                    'candidate_operations':len(d['operation_ids']),
                    'nonconditional_operations':sum(not opmap[oid]['conditional'] for oid in d['operation_ids']),
                    'forecast_due_at':d.get('forecast_due_at'), 'supported_arrival_at':d.get('supported_arrival_at'),
                    'forecast_need_at':d.get('forecast_need_at'),'forecast_latest_start':d.get('forecast_latest_start'),
                    'offered_candidates':len(ids.intersection(d['operation_ids']))} for d in due]
                stop['deadline_notices']=[n for n in trigger.get('forecast_notifications',[]) if n['machine'] in trigger.get('forecast_trigger_machines',[])]
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
            'replanning_trigger_count':sum(not x['observation_cutoff'] for x in stops),
            'zero_time_stops':zero,'old_capacity_immediate_retrigger_count':len(same_old_capacity),
            'common_window_quality':quality,'provenance_audit':result['provenance_audit'],
            'physical_prefix_errors':result['physical_prefix_errors'],
            'opportunity_audit_valid':result['opportunity_audit']['valid'],
            'service_input_tokens_per_response':[x['usage']['input_tokens'] for x in model_attempts if x['usage']],
            'attempt_errors':[{'index':x['index'],'error':x['error']} for x in model_attempts if x['error']],
            'accepted_reviews':[e for e in suffix if e['kind']=='planning_batch_accepted']}
    report={'schema':'deadline-three-group-live-summary-v1','common_window':[start,end],
        'target_window':comparison['target_window'],'per_group_call_cap':reg['per_group_call_cap'],
        'results':rows,'isolation_after':comparison['isolation_after'],
        'all_reached_target':all(r['target_reached'] for r in rows.values()),
        'limitations':comparison['limitations']+[
            'Final backlog is measured at each own endpoint; compare directly only if endpoints match.',
            'Unreserved machine time includes downtime and absence of feasible work; it is not all avoidable scheduling delay.',
            'Executable-unplanned machine seconds can count alternative machines for the same operation; it is not a count of unique orders.',
            'Pending demand ledger excludes machines already covered by queues/holds; its operation count is not the full unscheduled backlog. Global unassigned public operations are reported separately and include future conditional work.',
            'Short-window tardiness and finished-lot throughput may be insensitive; dispatch and ready-wait measures supplement them.']}
    (RUN/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    value=summarize()
    print(json.dumps({'common_window':value['common_window'],'groups':{g:{k:r[k] for k in ('total_calls','observed_seconds','model_commits','planning_stop_counts','common_window_quality')} for g,r in value['results'].items()}},ensure_ascii=False,indent=2))
