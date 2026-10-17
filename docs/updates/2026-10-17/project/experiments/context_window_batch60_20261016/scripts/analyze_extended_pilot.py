"""Compare inherited and added observation windows using sealed evidence only."""
from pathlib import Path
from collections import Counter
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.contracts import sha_bytes,fingerprint
from src.smt_fullfab.harness.evaluation import Evidence
from compare_forecast_pilots import window,packet_details
from extended_pilot_support import checkpoint
from measure_common_backlog import measure
RUN=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'live_pilots/extended_three_group_20261017';OLD=ROOT/'live_pilots/deadline_three_group_20261017'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')

def main():
    summary=read(RUN/'summary.json');comparison=read(RUN/'comparison.json');reg=read(RUN/'registration.json');oldsummary=read(OLD/'summary.json')
    end=summary['common_window'][1];rows={};random_samples={};closed_unknown=[]
    for g,s in summary['results'].items():
        ev=Evidence(comparison['results'][g].get('evidence_directory',RUN/g),comparison['results'][g]['evidence_sha256']);trace=[ev.get(r) for r in ev.value['physical']]
        from src.smt_fullfab.harness.recovery import failure_kind
        for attempt in ev.rows('attempts').values():
            if attempt['channel']=='codex' and attempt['status'] not in ('reserved','not_sent') and attempt.get('usage') is None:
                closed_unknown.append({'group':g,'call_number':attempt['index']+1,'attempt_id':attempt['attempt_id'],
                    'failure_kind':failure_kind(ev,attempt),'closed_process_no_output_validated':True})
        random_samples[g]={json.dumps(e['processing_key'],sort_keys=True):(e['processing_seconds'],e['cadence_seconds'],e['transport_seconds']) for e in trace if e['kind']=='dispatch' and 'processing_key' in e and 702<=e['time']<=end}
        parent=reg['predecessors'][g];old=Evidence(parent['directory'],parent['evidence_sha256']);state,_,_=checkpoint(old)
        executed={tuple(x) for x in state['executed_tasks']}
        pending={t['id']:t for t in state['plan']['tasks'] if (state['plan']['version'],t['id']) not in executed}
        inherited_dispatch=[]
        plans={e['plan']['version']:{t['id']:t for t in e['plan']['tasks']} for e in trace if e['kind']=='plan_committed'}
        for e in trace:
            if e['kind']!='dispatch' or not 882<=e['time']<=end:continue
            tid=e.get('plan_task_id')
            if tid in pending:
                t=pending[tid]
                current=plans[e['plan_version']][tid]
                if current['operation_ids']!=t['operation_ids']:continue
                inherited_dispatch.append({'id':tid,'machine':e['machine'],'time':e['time'],'planned_not_before':t['not_before'],
                                          'operation_ids':t['operation_ids'],'original_machine':t['machine'],
                                          'unchanged_from_882':current==t,'committed_task_at_dispatch':current})
        stops=[x for x in s['planning_stops'] if not x['observation_cutoff'] and 702<x['to']<=end]
        extended_stops=[x for x in stops if x['to']>882]
        total=s['calls_to_reach_common_endpoint']
        actual_attempts=sorted((a for a in ev.rows('attempts').values() if a['channel']=='codex' and a['status']!='not_sent'),key=lambda a:a['index'])
        common_attempts=actual_attempts[:total] if total is not None else []
        attempt_tools={a['attempt_id']:a['tool'] for a in comparison['results'][g]['attempts']}
        common_call_types=dict(Counter(attempt_tools[a['attempt_id']] or 'transport_failure' for a in common_attempts))
        common_usage={k:sum((a.get('usage') or {}).get(k,0) for a in common_attempts) for k in ('input_tokens','output_tokens','cached_input_tokens')}
        common_usage.update(unknown_usage=sum(a.get('usage') is None for a in common_attempts),model_seconds=sum(a.get('duration_seconds') or 0 for a in common_attempts))
        early=window(ev,trace,702,882);previous=window(old,[old.get(r) for r in old.value['physical']],702,882)
        assert early['quality']==previous['quality']
        intervals=[];last=882.
        for stop in sorted(extended_stops,key=lambda x:x['to']):
            intervals.append(stop['to']-last);last=stop['to']
        first=min((x['to'] for x in extended_stops),default=end)
        boundary_contexts=[ctx for ctx in ev.rows('contexts').values() if abs(ctx['time']-end)<1e-7]
        common_backlog=None
        if boundary_contexts:
            ctx=min(boundary_contexts,key=lambda c:c['state_revision'])
            dispatched=set(ctx['execution_state']['dispatched_task_ids'])
            queued=[t for t in ctx['base_plan']['tasks'] if t['id'] not in dispatched]
            assigned={oid for t in queued for oid in t['operation_ids']}
            unassigned=[o for o in ctx['problem']['operations'] if o['operation_id'] not in assigned]
            common_backlog={'time':end,'context_ref':ctx['context_ref'],'accepted_pending_task_count':len(queued),
                'unassigned_public_operations':len(unassigned),
                'unassigned_nonconditional_operations':sum(not o['conditional'] for o in unassigned),
                'pending_demand_machine_count':len(ctx.get('batch_demands',[])),
                'program_reported_gap_machines':len((ctx.get('trigger') or {}).get('machines',[])),
                'measurement':'first observation at the common endpoint, before planning at that endpoint'}
        strict_backlog=measure(ev,trace,end)
        if strict_backlog['available']:
            measured=strict_backlog['global_backlog']
            if common_backlog is not None:
                assert all(common_backlog[k]==measured[k] for k in ('accepted_pending_task_count','unassigned_public_operations','unassigned_nonconditional_operations'))
            else:common_backlog=measured
        gap_cases=[]
        contexts=ev.rows('contexts')
        for ctx in sorted(contexts.values(),key=lambda c:(c['time'],c['state_revision'])):
            trigger=ctx.get('trigger') or {}
            if trigger.get('reason')!='uncovered_demand' or ctx['time']<882 or ctx['time']>end:continue
            dispatched=set(ctx['execution_state']['dispatched_task_ids'])
            queued=[t for t in ctx['base_plan']['tasks'] if t['id'] not in dispatched]
            owner={oid:t for t in queued for oid in t['operation_ids']}
            checks=[]
            for gap in trigger.get('machines',[]):
                ops=[o for o in ctx['problem']['operations'] if not o['conditional'] and
                     o['release_time']<=ctx['time'] and gap['machine'] in o['eligible_machines']]
                checks.append({'machine':gap['machine'],'reported_candidate_count':gap['candidate_count'],
                    'public_ready_candidates':[o['operation_id'] for o in ops],
                    'already_queued':[{'operation_id':o['operation_id'],'task':owner[o['operation_id']]} for o in ops if o['operation_id'] in owner],
                    'all_reported_candidates_already_queued':len(ops)==gap['candidate_count'] and bool(ops) and all(o['operation_id'] in owner for o in ops)})
            gap_cases.append({'time':ctx['time'],'context_ref':ctx['context_ref'],'machines':checks,
                              'all_gap_machines_only_see_already_queued_work':bool(checks) and all(c['all_reported_candidates_already_queued'] for c in checks)})
        cycles={}
        committed_contexts={ev.rows('candidates')[c['candidate_ref']]['context_ref'] for c in ev.rows('commits').values()}
        for a in ev.rows('attempts').values():
            if a['channel']!='codex' or a['status']=='not_sent':continue
            ref=a['context_ref'];entry=cycles.setdefault(ref,{'context_ref':ref,'time':contexts[ref]['time'],'trigger':(contexts[ref].get('trigger') or {}).get('reason'),'calls':0,'model_seconds':0.,'unknown_usage':0,'committed':ref in committed_contexts})
            entry['calls']+=1;entry['model_seconds']+=a.get('duration_seconds') or 0.;entry['unknown_usage']+=a.get('usage') is None
        completed_cycles=[z for z in cycles.values() if z['committed']]
        assert abs(sum(z['model_seconds'] for z in cycles.values())-s['usage']['model_seconds'])<1e-6
        rows[g]={'planning_cycles':list(cycles.values()),
                 'maximum_completed_cycle_model_seconds':max((z['model_seconds'] for z in completed_cycles),default=0),
                 'completed_cycles_over_135_real_seconds':sum(z['model_seconds']>135 for z in completed_cycles),
                 'previous_calls':oldsummary['results'][g]['total_calls'],'cumulative_calls':s['total_calls'],
                 'calls_to_common_endpoint':total,'common_call_types':common_call_types,'common_usage':common_usage,'new_calls':s['total_calls']-4,
                 'new_calls_to_common_endpoint':total-4 if total is not None else None,
                 'previous_window_quality_unchanged':True,'early_window':early,'actual_gap_diagnosis':gap_cases,
                 'extension_window':window(ev,trace,882,end),'whole_window':window(ev,trace,702,end),
                 'true_replan_count':len(stops),'extension_replan_count':len(extended_stops),
                 'replans_per_simulated_hour':len(stops)*3600/(end-702),
                 'extension_trigger_intervals':intervals,
                 'extension_intervals_below_1_second':sum(0<=d<1 for d in intervals),
                 'extension_intervals_below_10_seconds':sum(0<=d<10 for d in intervals),'extension_trigger_times':[x['to'] for x in extended_stops],
                 'extension_trigger_reasons':dict(Counter(x['reason'] for x in extended_stops)),
                 'first_new_trigger':first,'inherited_pending_task_count':len(pending),
                 'inherited_pending_task_dispatch_count':len(inherited_dispatch),'inherited_task_dispatches':inherited_dispatch,
                 'unchanged_inherited_task_dispatch_count':sum(e['unchanged_from_882'] for e in inherited_dispatch),
                 'rescheduled_inherited_task_dispatch_count':sum(not e['unchanged_from_882'] for e in inherited_dispatch),
                 'inherited_dispatches_before_first_new_trigger':sum(e['time']<=first for e in inherited_dispatch),
                 'packets':packet_details(ev),
                 'busy_added_tasks':s['committed_added_tasks_on_busy_machines'],'added_tasks':s['committed_added_tasks'],
                 'final_unassigned_public_operations':s['final_unassigned_public_operations'],
                 'final_unassigned_nonconditional_operations':s['final_unassigned_nonconditional_operations'],
                 'final_backlog':s['final_backlog_at_own_endpoint'],'common_backlog':common_backlog,
                 'strict_ready_backlog':strict_backlog,
                 'zero_time_stops':s['zero_time_stops'],'old_capacity_retrigger':s['old_capacity_immediate_retrigger_count'],
                 'attempt_errors':s['attempt_errors'],'transport_errors':s['transport_errors']}
    shared_keys=set.intersection(*(set(v) for v in random_samples.values()))
    random_check={'mechanism':'event-keyed processing/cadence/transport draws, not a shared mutable RNG stream',
        'shared_operation_batch_keys':len(shared_keys),
        'shared_keys_with_different_random_durations':sum(len({random_samples[g][k] for g in random_samples})!=1 for k in shared_keys)}
    archive=read(ROOT/'reports/archive_before_extended_pilot_20261017/archive_manifest.json')
    changed_previous=[p for p,h in archive['prior_files'].items() if sha_bytes((OLD/p).read_bytes())!=h]
    validity={'all_groups_reached_target':summary['all_reached_target'],
        'closed_unknown_failures':closed_unknown,
        'paired_randomness':random_check,
        'previous_files_checked':len(archive['prior_files']),'previous_files_changed':changed_previous,
        'original_B_unchanged':comparison['isolation_after']['valid'],
        'source_unchanged_during_live':fingerprint()['sha256']==reg['fingerprint_sha256'],
        'runner_unchanged':sha_bytes((ROOT/'scripts'/reg.get('runner_name',('run_extended_completion.py' if reg.get('resource_continuation') else 'run_extended_three_group_pilot.py'))).read_bytes())==reg['script_sha256'],
        'support_unchanged':sha_bytes((ROOT/'scripts/extended_pilot_support.py').read_bytes())==reg['support_sha256'],
        'resource_continuation_audits':[x.get('resource_continuation_audit') for x in comparison['results'].values()],
        'final_resource_audits':[x.get('final_resource_audit') for x in comparison['results'].values()],
        'all_inheritance_audits_pass':all(x['inheritance_audit']['valid'] for x in comparison['results'].values()),
        'approved_retry_audit':comparison['results']['G1'].get('approved_retry_audit'),
        'approved_connection_retry_audit':comparison['results']['G1'].get('approved_connection_retry_audit'),
        'deadline_reconciliation_audits':[x.get('deadline_reconciliation_audit') for x in comparison['results'].values()],
        'all_cost_audits_pass':all(x['cost_audit']['valid'] for x in comparison['results'].values()),
        'all_production_choices_from_model':all(x['provenance_audit']['valid'] and x['provenance_audit']['algorithm_production_tasks']==0 for x in comparison['results'].values()),
        'all_physical_prefix_checks_pass':all(x['physical_prefix_errors'] in ([],['physical: missing terminal event']) for x in comparison['results'].values()),
        'all_opportunity_audits_pass':all(x['opportunity_audit']['valid'] for x in comparison['results'].values()),
        'actual_new_calls':sum(x['new_calls'] for x in rows.values()),
        'cumulative_actual_calls':sum(x['cumulative_calls'] for x in rows.values()),
        'unknown_usage_calls':sum(x['usage']['unknown_usage'] for x in summary['results'].values())}
    write(RUN/'extended_comparison.json',{'common_window':[702,end],'extension_window':[882,end],'results':rows,'verification':validity})
    write(RUN/'final_verification.json',validity)
    print(json.dumps({'verification':validity,'groups':{g:{k:r[k] for k in ('cumulative_calls','new_calls','true_replan_count',
          'inherited_pending_task_dispatch_count','extension_trigger_times','extension_trigger_reasons','extension_window')} for g,r in rows.items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
