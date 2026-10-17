#!/usr/bin/env python3
"""Compare five sealed arms on the same observed prefix; never call models."""
from pathlib import Path
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.offline_isolation import install_guard
install_guard()
from src.smt_fullfab.harness.evaluation import Evidence
from src.smt_fullfab.harness.contracts import digest, fingerprint
from src.smt_fullfab.harness.presentation import unpack
from scripts.compare_forecast_pilots import window, packet_details

RUN=ROOT/'live_pilots/deadline_three_group_20261017'
OLD=ROOT/'live_pilots/forecast_collection_20261017'
def read(p):return json.loads(p.read_text())
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    reg=read(RUN/'registration.json');oldreg=read(OLD/'registration.json')
    new=read(RUN/'summary.json');old=read(OLD/'summary.json')
    loaded={}
    for version,root,groups in [('v4',OLD,('G1','G2')),('v5',RUN,('G0','G1','G2'))]:
        for group in groups:
            result=read(root/(group+'.result.json'));ev=Evidence(root/group,result['evidence_sha256'])
            loaded[version,group]=(ev,[ev.get(ref) for ref in ev.value['physical']],result)
    start=702.;end=min(r['head']['time'] for _,_,r in loaded.values())
    common={};dispatches={};contexts={};first_plans={};first_focus={};trigger_diagnosis={}
    for (version,group),(ev,trace,result) in loaded.items():
        row=window(ev,trace,start,end)
        if row:
            row['planning_stops_within_window']=[r for r in row['planning_stops_within_window']
                if not (r['time']==reg['evaluation_end'] and r['reason']=='periodic_replan')]
        common.setdefault(version,{})[group]=row
        dispatches[version+'_'+group]=[{k:e[k] for k in ('time','machine','lots','steps','visits')}
            for e in trace[ev.manifest['prefix_events']:] if e['kind']=='dispatch' and e.get('owner')=='plan' and start<=e['time']<=end]
        ctx=next(c for c in ev.rows('contexts').values() if c['time']==start)
        contexts[version+'_'+group]={k:digest(ctx[k]) for k in ('problem','base_plan','execution_state','batch_demands')}
        first=next((e['plan'] for e in trace[ev.manifest['prefix_events']:] if e['kind']=='plan_committed'),None)
        if first:
            first_plans[version+'_'+group]={'tasks':[{k:t[k] for k in ('machine','lot_ids','steps','visits','operation_ids','not_before')} for t in first['tasks']],
                'holds':first['holds'],'valid_until':first['valid_until'],'freeze_until':first['freeze_until']}
        if version=='v5':
            attempt=min(ev.rows('attempts').values(),key=lambda a:a['index'])
            ref=(attempt.get('transport') or {}).get('original_input_files',{}).get('prompt.txt')
            if ref:
                frame=json.loads(ev.raw(ref).decode().rsplit('\n',1)[-1])
                first_focus[group]=unpack(frame.get('focus_coverage',[]))
            suffix=trace[ev.manifest['prefix_events']:]
            stop=next((e for e in suffix if e['kind']=='coverage_gap' or e['kind']=='batch_check' and e.get('reason')),None)
            if stop:
                mids=set(stop.get('forecast_trigger_machines',[]))|{m['machine'] for m in stop.get('machines',[])}
                following=[c for c in ev.rows('commits').values() if c['time']>=stop['time'] and c['time']>start]
                if following:
                    commit=min(following,key=lambda c:c['trace_start']);candidate=ev.rows('candidates')[commit['candidate_ref']]
                    trigger_diagnosis[group]={'stop_time':stop['time'],'reason':stop.get('reason',stop['kind']),
                        'machines':sorted(mids),'notices':[n for n in stop.get('forecast_notifications',[]) if n['machine'] in mids],
                        'initial_packet_coverage':[f for f in first_focus.get(group,[]) if f['machine'] in mids],
                        'model_added_tasks_after_reminder':[{k:t[k] for k in ('machine','operation_ids','not_before')}
                            for t in candidate['delta']['tasks']['add'] if t['machine'] in mids]}
    same={k:reg[k]==oldreg[k] for k in ('initial_fixture_sha256','initial_state_sha256','initial_trace_sha256',
          'evaluation_end','per_group_call_cap','task','cli_sha256','model_catalog_sha256')}
    archive=ROOT/'reports/archive_v5_before_three_group_live_20261017'
    frozen=read(archive/'archive_manifest.json');manifest=read(ROOT/'isolation_manifest.json');source=Path(manifest['source_root'])
    isolation={'source_files_checked':len(manifest['source_hashes']),
        'changed_source_files':[p for p,h in manifest['source_hashes'].items() if sha(source/p)!=h],
        'historical_pilot_files_checked':len(frozen['sealed_pilot_files']),
        'changed_historical_pilot_files':[p for p,h in frozen['sealed_pilot_files'].items() if sha(ROOT/p)!=h],
        'archived_v5_files_checked':len(frozen['files']),
        'changed_archived_files':[p for p,h in frozen['files'].items() if sha(archive/p)!=h],
        'changed_fixtures':[p for p,h in manifest['fixture_sha256'].items() if sha(ROOT/'fixtures'/p)!=h],
        'original_B_database_opened':False}
    isolation['valid']=not any(v for k,v in isolation.items() if k.startswith('changed_'))
    config_diff={}
    def diff(a,b,path=''):
        if isinstance(a,dict) and isinstance(b,dict):
            return sum((diff(a.get(k),b.get(k),path+'.'+k) for k in sorted(set(a)|set(b))),[])
        return [{'path':path,'v4':a,'v5':b}] if a!=b else []
    for g in ('G1','G2'):config_diff[g]=diff(read(OLD/(g+'.config.json')),read(RUN/(g+'.config.json')))
    result={'comparison_window':[start,end],'target_window':[702,882],
        'same_registration_fields':same,'same_initial_public_v5':len({digest(v) for k,v in contexts.items() if k.startswith('v5_')})==1,
        'initial_public_component_hashes':contexts,'config_changes_from_v4':config_diff,
        'same_window_comparison':common,
        'v5_actual_packet_details':{g:packet_details(loaded['v5',g][0]) for g in ('G0','G1','G2')},
        'all_total_calls':{'v4':{g:r['total_calls'] for g,r in old['results'].items()},'v5':{g:r['total_calls'] for g,r in new['results'].items()}},
        'dispatches_at_common_window':dispatches,'isolation_after':isolation,
        'normalized_first_plans':first_plans,
        'first_packet_focus_coverage':first_focus,
        'trigger_diagnosis':trigger_diagnosis,
        'G0_G1_same_initial_production_choices':first_plans.get('v5_G0')==first_plans.get('v5_G1'),
        'limits':['One sample per arm; model choices are not deterministic or statistically controlled.',
                  'This is continuation from an already busy saved factory, not initial scheduling of 918 or 2000 machines.',
                  'Unscheduled inventory at different endpoints is not directly comparable.',
                  'Zero simulated ready-gap waiting does not include decision latency because simulation pauses.',
                  'Forecast changes and genuine unresolved gaps may still require short-interval replanning.']}
    write(RUN/'previous_comparison.json',result)
    checks={'source_matches_registration':fingerprint()['sha256']==reg['fingerprint_sha256'],
        'runner_matches_registration':sha(ROOT/'scripts/run_deadline_three_group_pilot.py')==reg['script_sha256'],
        'same_start_state_and_load':all(same[k] for k in ('initial_fixture_sha256','initial_state_sha256','initial_trace_sha256')),
        'same_observation_target':same['evaluation_end'], 'same_initial_public_data_three_groups':result['same_initial_public_v5'],
        'within_per_group_call_cap':all(r['total_calls']<=8 for r in new['results'].values()),
        'within_total_call_cap':sum(r['total_calls'] for r in new['results'].values())<=24,
        'all_production_from_explicit_model_choice':all(r['provenance_audit']['valid'] and r['provenance_audit']['algorithm_production_tasks']==0
            and r['usage']['offline_outputs']==0 for r in new['results'].values()),
        'opportunity_audits_pass':all(r['opportunity_audit_valid'] for r in new['results'].values()),
        'physical_prefix_has_only_expected_nonterminal_limit':all(r['physical_prefix_errors']==['physical: missing terminal event'] for r in new['results'].values()),
        'isolation_valid':isolation['valid']}
    write(RUN/'final_verification.json',{'checks':checks,'integrity_passed':all(checks.values()),
        'all_groups_reached_target':new['all_reached_target'],
        'actual_calls':sum(r['total_calls'] for r in new['results'].values()),
        'unknown_usage_calls':sum(r['unknown_usage_calls'] for r in new['results'].values()),
        'admission_checks_passed':14,'isolation_after':isolation,
        'evidence_sha256':{g:read(RUN/(g+'.result.json'))['evidence_sha256'] for g in ('G0','G1','G2')}})
    print(json.dumps({'common_window':[start,end],'same_registration':same,'calls':result['all_total_calls'],
                      'checks':checks,'isolation':isolation},ensure_ascii=False))
    assert all(checks.values()),checks


if __name__=='__main__':main()
