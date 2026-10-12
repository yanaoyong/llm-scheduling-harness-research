#!/usr/bin/env python3
"""Read-only evidence post-processing; never imports runners, solvers or replay.

Run from the experiment root: .venv/bin/python scripts/analysis_tables.py
Outputs JSON + compact CSV under artifacts/final. Safe to rerun while a serial
batch is in progress: only completed result.json files contribute observations.
Unknown metrics remain null/blank, and known partial sums are named explicitly.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]
TOKENS=('input_tokens','cached_input_tokens','output_tokens','cache_write_input_tokens','reasoning_output_tokens')
COSTS=('end_to_end_seconds','model_calls','model_seconds','solver_calls','solver_seconds','solver_budget_seconds',*TOKENS,'reported_input_plus_output_tokens','cost_usd')
REFERENCES={'verified_optimum':'independently_verified_optimum','reported_optimum':'reported_optimum','reported_BKS':'best_known_feasible_value_reported','reported_lower_bound':'lower_bound_reported'}
SMT_METRICS=('controlled_family_queue_area_lot_seconds','controlled_completed_operation_lots','throughput_lots','throughput_wafers','mean_cycle_seconds_completed','total_tardiness_completed_seconds','initial_wip_lots','terminal_wip_lots','wip_change','controlled_batch_fill_mean','unfinished_controlled_batches')


def number(value):return type(value) in (int,float) and math.isfinite(value)
def read(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default

def csv_read(path):
    if not path.exists():return []
    with path.open(newline='') as f:return [dict(row) for row in csv.DictReader(f)]

def cast(value):
    if value in ('',None):return None
    if value in ('True','true'):return True
    if value in ('False','false'):return False
    if isinstance(value,str):
        try:return json.loads(value)
        except (ValueError,TypeError):return value
    return value

def stats(values):
    raw=list(values);known=[v for v in raw if number(v)]
    return {'known_n':len(known),'unknown_n':len(raw)-len(known),
            'mean':sum(known)/len(known) if known else None,
            'min':min(known) if known else None,'max':max(known) if known else None,
            'range':max(known)-min(known) if known else None,
            'known_partial_sum':sum(known) if known else None,
            'total_if_complete':sum(known) if known and len(known)==len(raw) else None}

def gap(value,base):return 100*(value-base)/base if number(value) and number(base) and base>0 else None

def write_csv(path,rows,empty_fields=('phase','run_id','status')):
    fields=list(dict.fromkeys(k for row in rows for k in row)) or list(empty_fields)
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(list,dict)) else v for k,v in row.items()})

def solver_call_count(record,directory):
    """A/F legacy cost rows omit counts; count their saved, audited artifacts."""
    value=(record.get('costs') or {}).get('solver_calls')
    if type(value) is int and value>=0:return value,'record.costs.solver_calls'
    if record.get('family')!='smt2020' and record.get('arm')=='A':
        solved=read(directory/'solver.json')
        if isinstance(solved,dict) and 'solver_status' in solved:return 1,'saved solver.json'
    if record.get('family')!='smt2020' and record.get('arm')=='F':
        candidates=read(directory/'fixed_portfolio.json')
        if isinstance(candidates,list) and candidates:return len(candidates),'saved fixed_portfolio.json candidate count'
    return None,'unavailable; not zero-filled'

def instance_metadata(instance):
    p=read(ROOT/'data/fjsp/instances'/f'{instance}.json')
    if not p:return {'instance':instance,'metadata_status':'missing'}
    counts=[len(op['alternatives']) for job in p['jobs'] for op in job['operations']]
    machines=len(p['machines'])
    return {'instance':instance,'family':p['family'],'base_instance':p.get('base_instance',instance),'variant':p.get('variant'),
            'jobs':len(p['jobs']),'operations':len(counts),'machines':machines,'eligibility_edges':sum(counts),
            'eligible_machines_per_operation_mean':sum(counts)/len(counts) if counts else None,
            'eligible_machines_per_operation_min':min(counts) if counts else None,
            'eligible_machines_per_operation_max':max(counts) if counts else None,
            'eligible_machine_fraction_mean':sum(counts)/(len(counts)*machines) if counts and machines else None,'metadata_status':'available'}

def audits_for_phase(phase):
    """Use saved audit summaries only, newest per-run observation wins."""
    folder=ROOT/'artifacts'/phase;files=set(folder.glob('*replay*.json'))|set(folder.glob('*evidence_audit.json'))
    index={};sources=[]
    for path in sorted(files,key=lambda p:p.stat().st_mtime):
        data=read(path)
        if not isinstance(data,dict):continue
        sources.append(str(path.relative_to(ROOT)))
        for row in data.get('runs',[])+data.get('auxiliary_runs',[]):
            index[row['run_id']]={'row':row,'phase_errors':data.get('phase_errors',[]),'source':str(path.relative_to(ROOT)),'at':data.get('at')}
    return index,sources

def strategy(record,cfg):
    """Describe C's recorded decisions; this is not an independent re-audit."""
    family=record.get('family');solvers=record.get('solver_results',[]);groups=defaultdict(list);calls=[]
    for i,s in enumerate(solvers):
        params=s.get('parameters') or s.get('result',{}).get('parameters') or {}
        decision=s.get('decision',0 if family!='smt2020' else None);groups[decision].append(params)
        if family=='smt2020':default={**cfg.get('classical_parameters',{}),'seed':cfg.get('seed')}
        else:default={'time_limit':cfg.get('solver_budget_seconds'),'seed':cfg.get('seed'),'workers':cfg.get('workers',1),
                      'search_branching':cfg.get('search_branching_by_family',{}).get(family,cfg.get('search_branching','AUTOMATIC_SEARCH')),'randomize_search':cfg.get('randomize_search',False)}
        match=all(default.get(k) is not None for k in default) and params==default
        calls.append({'solver_index':i,'decision':decision,'parameters':params,'A_default_parameters':default,'matches_A_default_exactly':match,
                      'different_from_A':{k:{'C':params.get(k),'A':default.get(k)} for k in sorted(set(params)|set(default)) if params.get(k)!=default.get(k)},
                      'solver_status':s.get('solver_status',s.get('result',{}).get('solver_status')),
                      'status':s.get('status','success'),'requested_seconds':s.get('requested_seconds',params.get('time_limit'))})
    outputs=[m.get('output') for m in record.get('model_results',[]) if isinstance(m.get('output'),dict)]
    acts=Counter(o.get('action','direct_schedule') for o in outputs)
    if not outputs:acts=Counter(a.get('action') for a in record.get('actions',[]) if isinstance(a.get('action'),str))
    rejected=record.get('rejected_actions');revisions=(record.get('metrics') or {}).get('revisions',record.get('revisions'))
    valid_ids=all(k is not None for k in groups);per_state=list(groups.values())
    return {'phase':record['phase'],'run_id':record['run_id'],'family':family,'instance':record.get('instance_id'),'scenario':record.get('scenario'),'repeat':record.get('repeat'),'status':record.get('status'),
            'model_calls':(record.get('costs') or {}).get('model_calls'),'recorded_solver_calls':len(solvers),
            'model_action_counts':dict(acts),'revisions_reported':revisions,'rejected_actions_count':len(rejected) if isinstance(rejected,list) else None,
            'extra_solves_after_first_per_state':sum(max(0,len(x)-1) for x in per_state) if valid_ids else None,
            'single_solver_call_in_run':len(solvers)==1,'single_default_solver_call_in_run':len(calls)==1 and calls[0]['matches_A_default_exactly'],
            'all_observed_decisions_single_default_solve':all(len(x)==1 for x in per_state) and all(c['matches_A_default_exactly'] for c in calls) if calls and valid_ids else None,
            'distinct_parameter_sets':len({json.dumps(c['parameters'],sort_keys=True) for c in calls}) if calls else None,
            'solver_parameters':calls,'interpretation':'Recorded choices only; exact A defaults include time allocation and seed. SMT rolling states are not independent factory scenarios.'}

def analysis(phases=None):
    begun=time.process_time();warnings=[];sources=[];freezes=[];rows=[];strategies=[];instances={};smt_sources=[]
    reference_doc=read(ROOT/'docs/fjsp-reference-values.json',{});refs={r['instance_id']:r for r in reference_doc.get('references',[])}
    for path in sorted((ROOT/'configs/freezes').glob('*.json')):
        freeze=read(path)
        if not freeze or not freeze.get('matrix'):continue
        if phases and freeze['phase'] not in phases:continue
        freezes.append(freeze)
    selected={f['phase'] for f in freezes}
    if phases:selected.update(phases)
    selected.update(p.name for p in (ROOT/'runs').iterdir() if p.is_dir() and p.name.startswith(('acceptance_','auxiliary_')) and (not phases or p.name in phases))
    by_phase={f['phase']:f for f in freezes}
    for phase in sorted(selected):
        frozen=by_phase.get(phase,{});audit_index,audit_sources=audits_for_phase(phase);sources+=audit_sources
        smt_path=ROOT/'artifacts'/phase/'smt_results.csv';smt_csv={r['run_id']:{k:cast(v) for k,v in r.items()} for r in csv_read(smt_path)}
        is_smt=frozen.get('dataset')=='smt2020' or 'smt' in phase
        if is_smt:smt_sources.append({'phase':phase,'path':str(smt_path.relative_to(ROOT)),'status':'available' if smt_path.exists() else 'missing','rows':len(smt_csv) if smt_path.exists() else None})
        observed={}
        for path in sorted((ROOT/'runs'/phase).glob('*/result.json')):
            r=read(path)
            if not isinstance(r,dict):
                warnings.append('Unreadable completed result: '+str(path.relative_to(ROOT)));observed[path.parent.name]={'phase':phase,'run_id':path.parent.name,'status':'unreadable','completed_record':True,'auxiliary':'_F_' in path.parent.name};continue
            family=r.get('family');instance=r.get('instance_id');smt=family=='smt2020';usage=(r.get('costs') or {}).get('usage',r.get('costs') or {}) or {};cost=r.get('costs') or {};metrics=r.get('metrics') or {}
            proof=audit_index.get(r['run_id']);evidence=proof['row'] if proof else {};stored_valid=r.get('status')=='success' and (r.get('validation') or {}).get('valid') is True
            certified=(stored_valid and evidence.get('audit_pass') is True and evidence.get('provenance_complete') is True and not proof['phase_errors']) if proof else None
            if smt and certified is True:certified=evidence.get('domain_valid') is True
            solver_calls,solver_calls_source=solver_call_count(r,path.parent)
            csv_row=smt_csv.get(r['run_id']) if smt else None
            if csv_row is not None:
                csv_identity=all(csv_row.get(k)==r.get(k) for k in ('code_commit','config_sha256','data_sha256'))
                if not csv_identity:warnings.append('SMT CSV identity differs from completed result: '+phase+'/'+r['run_id'])
                certified=csv_identity and csv_row.get('certified_success') is True and (certified is True if proof else True)
            quality_ok=stored_valid and certified is not False
            row={'phase':phase,'run_id':r['run_id'],'family':family,'instance':instance,'scenario':r.get('scenario'),'base_instance':r.get('base_instance'),'variant':r.get('variant'),'arm':r.get('arm'),'repeat':r.get('repeat'),
                 'auxiliary':r.get('arm')=='F','status':r.get('status'),'failure_type':r.get('failure_type'),'completed_record':True,'stored_valid_success':stored_valid,'certified_success':certified,
                 'audit_status':'available' if proof or csv_row is not None else 'missing','audit_source':proof['source'] if proof else str(smt_path.relative_to(ROOT)) if csv_row is not None else None,
                 'quality_population':'stored-valid success; provisional until existing offline audit certifies','provisional_makespan':metrics.get('makespan') if quality_ok and not smt else None,
                 'certified_makespan':metrics.get('makespan') if certified and not smt else None,
                 'first_output_valid':metrics.get('first_output_valid',r.get('first_output_valid')),'revisions':metrics.get('revisions',r.get('revisions')),
                 'end_to_end_seconds':cost.get('end_to_end_seconds'),'model_calls':cost.get('model_calls'),'model_seconds':cost.get('model_elapsed_seconds',cost.get('model_seconds')),
                 'solver_calls':solver_calls,'solver_calls_source':solver_calls_source,'solver_seconds':cost.get('solver_wall_seconds',cost.get('solver_seconds')),'solver_budget_seconds':cost.get('solver_budget_seconds'),'cost_usd':cost.get('cost_usd'),
                 **{k:usage.get(k) for k in TOKENS},'reported_input_plus_output_tokens':usage.get('input_tokens')+usage.get('output_tokens') if number(usage.get('input_tokens')) and number(usage.get('output_tokens')) else None,'code_commit':r.get('code_commit'),'data_sha256':r.get('data_sha256'),'config_sha256':r.get('config_sha256')}
            if smt:
                row.update(smt_csv_status='available' if csv_row is not None else 'missing',**{k:csv_row.get(k) if csv_row and certified else None for k in SMT_METRICS})
            else:
                if instance not in instances:instances[instance]=instance_metadata(instance)
                ref=refs.get(instance,{})
                row['reference_status']=ref.get('reference_status')
                for label,key in REFERENCES.items():row[label]=ref.get(key);row['gap_'+label+'_pct']=gap(row['provisional_makespan'],ref.get(key))
            if r.get('arm')=='C':
                cfg=read(path.parent/'config.json',{});strategies.append(strategy(r,cfg))
            observed[r['run_id']]=row
        for cell in frozen.get('matrix',[]):
            target,arm,repeat=cell;run_id=f'smt{target}_{arm}_r{repeat}' if is_smt else f'{target}_{arm}_r{repeat}'
            if not is_smt and target not in instances:instances[target]=instance_metadata(target)
            meta=instances.get(target,{}) if not is_smt else {}
            if run_id in observed:
                observed[run_id]['planned']=True
                for key,value in {'family':'smt2020' if is_smt else meta.get('family'),'instance':f'LVHM_seed{target}' if is_smt else target,'scenario':target if is_smt else None,'base_instance':meta.get('base_instance'),'variant':meta.get('variant'),'arm':arm,'repeat':repeat}.items():observed[run_id].setdefault(key,value)
                continue
            observed[run_id]={'phase':phase,'run_id':run_id,'family':'smt2020' if is_smt else meta.get('family'),'instance':f'LVHM_seed{target}' if is_smt else target,'scenario':target if is_smt else None,
                              'base_instance':meta.get('base_instance'),'variant':meta.get('variant'),'arm':arm,'repeat':repeat,'auxiliary':arm=='F','status':'incomplete' if (ROOT/'runs'/phase/run_id).exists() else 'not_started','completed_record':False,'planned':True,'certified_success':None}
        for row in observed.values():row.setdefault('planned',False)
        rows+=observed.values()
    # Pair each instance/repeat within its formal phase and matching auxiliary phase.
    lookup={(r['phase'],r.get('instance'),r.get('repeat'),r.get('arm')):r for r in rows}
    for row in rows:
        if row.get('family')=='smt2020':continue
        core=row['phase'].replace('auxiliary_','acceptance_',1);aux=core.replace('acceptance_','auxiliary_',1)
        a=lookup.get((core,row.get('instance'),row.get('repeat'),'A'),{});f=lookup.get((aux,row.get('instance'),row.get('repeat'),'F'),{})
        row['gap_paired_A_pct']=gap(row.get('provisional_makespan'),a.get('provisional_makespan'));row['gap_paired_F_pct']=gap(row.get('provisional_makespan'),f.get('provisional_makespan'))
        row['paired_A_certified']=a.get('certified_success');row['paired_F_certified']=f.get('certified_success')
    dataset_groups=defaultdict(list);repeat_groups=defaultdict(list)
    for row in rows:dataset_groups[(row['phase'],row.get('family'),row.get('arm'))].append(row);repeat_groups[(row['phase'],row.get('instance'),row.get('arm'))].append(row)
    summaries=[]
    for (phase,family,arm),members in sorted(dataset_groups.items(),key=lambda x:str(x[0])):
        done=[r for r in members if r['completed_record']];success=sum(r.get('stored_valid_success',False) for r in done);counts=Counter(r['status'] for r in members)
        out={'phase':phase,'family':family,'arm':arm,'auxiliary':arm=='F','planned':sum(r['planned'] for r in members),'records_completed':len(done),'stored_valid_successes':success,'certified_successes':sum(r.get('certified_success') is True for r in done),
             'failed_or_timeout_or_unreadable':sum(r['status']!='success' for r in done),'success_record_with_invalid_validation':sum(r['status']=='success' and not r.get('stored_valid_success') for r in done),
             'pending_audit_successes':sum(r.get('stored_valid_success') is True and r.get('certified_success') is None for r in done),'status_counts':dict(counts),'success_rate_completed_stored_valid':success/len(done) if done else None,
             'quality_population':'means conditional on indicated success; unfinished/failed records stay in counts'}
        for metric in ('provisional_makespan','certified_makespan',*[f'gap_{k}_pct' for k in REFERENCES],'gap_paired_A_pct','gap_paired_F_pct'):
            out[metric]=stats(r.get(metric) for r in done)
        out['costs_all_completed']={k:stats(r.get(k) for r in done) for k in COSTS}
        if family=='smt2020':out['smt_quality_certified_csv_only']={k:stats(r.get(k) for r in done) for k in SMT_METRICS}
        summaries.append(out)
    ranges=[];hurink=[]
    for (phase,instance,arm),members in sorted(repeat_groups.items(),key=lambda x:str(x[0])):
        out={'phase':phase,'family':members[0].get('family'),'instance':instance,'arm':arm,'auxiliary':arm=='F','planned_repeats':sorted(r['repeat'] for r in members if r['planned']),
             'completed_repeats':sorted(r.get('repeat') for r in members if r['completed_record'] and r.get('repeat') is not None),'successful_repeats':sorted(r['repeat'] for r in members if r.get('stored_valid_success')),
             'certified_repeats':sorted(r['repeat'] for r in members if r.get('certified_success')),'makespan':stats(r.get('provisional_makespan') for r in members),'certified_makespan':stats(r.get('certified_makespan') for r in members)}
        ranges.append(out)
        if out['family']=='hurink':
            ref=refs.get(instance,{})
            hurink.append({**instances[instance],'phase':phase,'arm':arm,'reference_status':ref.get('reference_status'),
                           **{label:ref.get(key) for label,key in REFERENCES.items()},'completed_repeats':out['completed_repeats'],'successful_repeats':out['successful_repeats'],'certified_repeats':out['certified_repeats'],'makespan':out['makespan'],
                           **{'gap_'+label+'_pct':stats(r.get('gap_'+label+'_pct') for r in members) for label in REFERENCES},
                           'comparison_note':'Compare variants only within this base instance; each variant uses its own reference. No causal attribution from cross-dataset means.'})
    return {'schema_version':'analysis-tables-1','generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'cpu_seconds':time.process_time()-begun,'phases':sorted(selected),
            'scope':'Existing completed records and frozen planned cells only; no new audit, simulation, solver or model call.',
            'quality_caveat':'Provisional quality is conditional on stored success plus valid saved validation, excluding explicitly failed existing audits. Certified quality requires saved offline evidence. Missing means null, never zero.',
            'reference_source':'docs/fjsp-reference-values.json; per-variant reported/verified/BKS/lower-bound labels preserved; not newly verified here',
            'cost_caveat':'Costs include completed failures; partial sums are explicit. Input+output is the reported total, cache/reasoning are subsets. Dollar billing remains unknown unless recorded.',
            'audits_read':sources,'smt_report_sources':smt_sources,'warnings':warnings,'dataset_arm_summary':summaries,'run_rows':rows,'repeat_ranges':ranges,'hurink_base_variant':hurink,'c_strategy':strategies,
            'counts':{'core_planned':sum(r['planned'] and not r['auxiliary'] for r in rows),'auxiliary_planned':sum(r['planned'] and r['auxiliary'] for r in rows),'completed':sum(r['completed_record'] for r in rows),'not_completed':sum(not r['completed_record'] for r in rows)}}

def flattened(row):
    out={}
    for key,value in row.items():
        if isinstance(value,dict) and set(value)=={'known_n','unknown_n','mean','min','max','range','known_partial_sum','total_if_complete'}:
            out.update({key+'_'+k:v for k,v in value.items()})
        elif key in ('costs_all_completed','smt_quality_certified_csv_only'):
            for metric,stat in value.items():out.update({metric+'_'+k:v for k,v in stat.items() if k in ('known_n','unknown_n','mean','known_partial_sum','total_if_complete')})
        else:out[key]=value
    return out

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--phase',action='append');ap.add_argument('--output',type=Path,default=ROOT/'artifacts/final');args=ap.parse_args()
    output=args.output.resolve()
    if ROOT not in output.parents:raise ValueError('Output must stay inside this experiment')
    result=analysis(args.phase);output.mkdir(parents=True,exist_ok=True)
    temp=output/'analysis.json.tmp';temp.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(output/'analysis.json')
    for key in ('dataset_arm_summary','run_rows','repeat_ranges','hurink_base_variant','c_strategy'):write_csv(output/(key+'.csv'),[flattened(r) for r in result[key]])
    print(json.dumps({'output':str(output),'cpu_seconds':result['cpu_seconds'],**result['counts'],'smt_report_sources':result['smt_report_sources']},ensure_ascii=False))

if __name__=='__main__':main()
