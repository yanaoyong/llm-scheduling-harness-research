#!/usr/bin/env python3
"""Offline cross-version comparison of sealed evidence, never fresh decisions."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.metrics import compute_metrics
from src.smt_fullfab.harness.presentation import unpack

RUN=ROOT/'live_pilots/forecast_collection_20261017'
OLD=ROOT/'live_pilots/two_strategy_20261016'


def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(root,group):
    result=read(root/(group+'.result.json'))
    ev=Evidence(root/group,result['evidence_sha256'])
    return result,ev,[ev.get(ref) for ref in ev.value['physical']]


def window(ev,trace,start,end):
    if end<=start:return None
    metrics=compute_metrics(trace,window_start=start,window_end=end,priority_weights=ev.manifest['config']['priority_weights'])
    families=metrics['production_family_statistics']
    quality={k:metrics[k] for k in ('weighted_tardy_lot_seconds','throughput_lots','throughput_wafers',
                                  'setup_loss_seconds','batch_fill_mean','terminal_wip_lots')}
    quality.update(queue_wait_lot_seconds=sum(f['queue_wait_lot_seconds'] for f in families.values()),
                   production_dispatches=sum(f['dispatches'] for f in families.values()),
                   operation_lots_dispatched=sum(f['operation_lots_dispatched'] for f in families.values()),
                   executable_unplanned_machine_seconds=sum(len(e.get('deferred_gap_machines',[]))*max(0,min(end,e['to'])-max(start,e['time'])) for e in trace if e['kind']=='time_advance'))
    feedback=sorted(ev.rows('feedback').values(),key=lambda f:f['event_start'])
    commits=list(ev.rows('commits').values())
    crossing=next((f for f in feedback if f['to']>=end),None)
    count=None
    if crossing:
        preceding=[c for c in commits if c['trace_end']<=crossing['event_start']]
        if preceding:
            attempt=ev.rows('attempts')[max(preceding,key=lambda c:c['trace_end'])['selection_attempt_id']]
            count=sum(a['index']<=attempt['index'] and a['channel']=='codex' for a in ev.rows('attempts').values())
    return {'window':[start,end],'calls_to_reach_end':count,'quality':quality,
            'planning_stops_within_window':[{'time':f['to'],'reason':f['stop_reason']['reason']} for f in feedback
                if start<f['to']<=end and f['stop_reason']['reason'] not in ('pilot_evaluation_end','collection_limit')]}


def packet_details(ev):
    rows=[]
    contexts=ev.rows('contexts')
    for a in sorted(ev.rows('attempts').values(),key=lambda a:a['index']):
        transport=a.get('transport') or {}
        ref=transport.get('original_input_files',{}).get('prompt.txt')
        if not ref:continue
        text=ev.raw(ref).decode(); frame=json.loads(text.rsplit('\n',1)[-1])
        ctx=contexts[frame['context']['context_ref']]
        trigger=ctx.get('trigger') or {}
        focus=unpack(frame.get('focus_coverage',[]))
        due=set(trigger.get('forecast_trigger_machines',[]))
        rows.append({'call_number':a['index']+1,'time':ctx['time'],'trigger':trigger.get('reason'),
            'forecast_trigger_machines':sorted(due),
            'forecast_trigger_coverage':[r for r in focus if r['machine'] in due],
            'focus_count':len(focus),'focus_information_status':dict(Counter(r['information_status'] for r in focus)),
            'inline_operations':frame['capacity_coverage']['inline_operations']})
    return rows


def main():
    new=read(RUN/'summary.json');old=read(OLD/'summary.json')
    loaded={(v,g):evidence(root,g) for v,root in (('v3',OLD),('v4',RUN)) for g in ('G1','G2')}
    end=min(r[0]['head']['time'] for r in loaded.values());start=702.
    comparison={v:{g:window(loaded[v,g][1],loaded[v,g][2],start,end) for g in ('G1','G2')} for v in ('v3','v4')}
    newreg=read(RUN/'registration.json');oldreg=read(OLD/'registration.json')
    same={key:newreg[key]==oldreg[key] for key in ('initial_fixture_sha256','initial_state_sha256',
          'initial_trace_sha256','evaluation_end','per_group_call_cap','task','cli_sha256','model_catalog_sha256')}
    config_changes={}
    for g in ('G1','G2'):
        a=read(OLD/(g+'.config.json'));b=read(RUN/(g+'.config.json'))
        def diff(x,y,path=''):
            if isinstance(x,dict) and isinstance(y,dict):
                return sum((diff(x.get(k),y.get(k),path+'.'+k) for k in sorted(set(x)|set(y))),[])
            return [{'path':path,'v3':x,'v4':y}] if x!=y else []
        config_changes[g]=diff(a,b)
    prior=read(ROOT/'reports/archive_v3_before_forecast_v4_20261017/archive_manifest.json')['sealed_pilot_files']
    manifest=read(ROOT/'isolation_manifest.json');source=Path(manifest['source_root'])
    isolation={'source_files_checked':len(manifest['source_hashes']),
        'changed_source_files':[p for p,h in manifest['source_hashes'].items() if sha(source/p)!=h],
        'sealed_pilot_files_checked':len(prior),'changed_sealed_pilot_files':[p for p,h in prior.items() if sha(ROOT/p)!=h],
        'changed_fixtures':[p for p,h in manifest['fixture_sha256'].items() if sha(ROOT/'fixtures'/p)!=h],
        'original_run_database_opened':False}
    isolation['valid']=not any(isolation[k] for k in ('changed_source_files','changed_sealed_pilot_files','changed_fixtures'))
    value={'comparison_window':[start,end],'paired_v4_window':new['common_window'],'same_registration_fields':same,
        'config_changes_from_v3':config_changes,'same_window_comparison':comparison,
        'v4_packet_details':{g:packet_details(loaded['v4',g][1]) for g in ('G1','G2')},
        'total_calls':{v:{g:report['results'][g]['total_calls'] for g in ('G1','G2')} for v,report in (('v3',old),('v4',new))},
        'isolation_after':isolation,
        'comparison_limits':['End-of-run backlogs can only be directly compared at equal simulated endpoints.',
          'V3 and V4 use different harness rules/prompts, and model outputs vary; one pair is not a causal statistical estimate.',
          'No untouched original B arm has been run under these exact conditions.',
          'The observation cutoff is not the plan validity cutoff. This saved state is continuation, not cold start.']}
    write(RUN/'previous_comparison.json',value)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
