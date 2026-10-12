"""Reproducible bounded three-arm experiment. No solver is imported in arm B."""
from __future__ import annotations
import argparse, datetime, hashlib, json, platform, sys, time, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor/FJSP-SMT2020/PADL-2023'

def dump(p, obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def read(p): return json.loads(Path(p).read_text())
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def instance_path(name):
    p=ROOT/'data'/f'{name}.lp' if name=='smoke' else VENDOR/'instances'/f'{name}.lp'
    if not p.is_file(): raise ValueError(f'Unknown instance {name}')
    return p

def compact_instance(inst):
    return {k:inst[k] for k in ('operations','machines','maintenance','setups')}

def schema_b():
    return {'type':'object','properties':{
        'reason':{'type':'string'},
        'actions':{'type':'array','items':{'type':'object','properties':{
            'id':{'type':'string'},'machine':{'type':'integer'},
            'maintenance':{'type':'array','items':{'type':'string'}}},
            'required':['id','machine','maintenance'],'additionalProperties':False}}},
        'required':['reason','actions'],'additionalProperties':False}

def schema_c():
    return {'type':'object','properties':{
        'action':{'type':'string','enum':['solve','finish']},'reason':{'type':'string'},
        'time_limit':{'type':'integer'},'seed':{'type':'integer'},
        'configuration':{'type':'string','enum':['frumpy','jumpy','tweety','handy','crafty','trendy']},
        'candidate':{'type':'integer'}},
        'required':['action','reason','time_limit','seed','configuration','candidate'],'additionalProperties':False}

def aggregate_usage(calls):
    fields=['input_tokens','cached_input_tokens','output_tokens']
    return {k:sum(c['usage'][k] for c in calls if c.get('usage',{}).get(k) is not None) if calls and all(c.get('usage',{}).get(k) is not None for c in calls) else (0 if not calls else None) for k in fields}

def run(arm, instance, repetition, phase, config, run_id=None):
    from problem import load_instance
    from validator import validate_schedule
    rid=run_id or f'{instance}_{arm}_r{repetition}'
    directory=ROOT/'runs'/phase/rid
    result_path=directory/'result.json'
    if not 1<=repetition<=len(config['seeds']): raise ValueError('Repetition outside locked seeds')
    if phase.startswith('acceptance'):
        split=read(ROOT/'configs/instance_split.json')
        if phase not in split or instance not in split[phase]:raise ValueError('Instance outside locked acceptance split')
        if rid!=f'{instance}_{arm}_r{repetition}':raise ValueError('Formal run ID must equal its unique locked grid cell')
    if result_path.exists():
        old=read(result_path)
        expected_hash=hashlib.sha256((json.dumps(config,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()
        if any(old[k]!=v for k,v in {'arm':arm,'instance':instance,'repetition':repetition,'phase':phase,'input_sha256':sha(instance_path(instance)),'config_sha256':expected_hash}.items()):
            raise ValueError('Run ID collision or changed config/input; use a new run ID, old evidence preserved')
        print(f'SKIP completed {phase}/{rid}',flush=True);return old
    if (directory/'started.json').exists():
        raise RuntimeError(f'Interrupted run preserved: {directory}; diagnose first. Development may use a new ID; formal attempts require a documented recovery protocol, never replacement.')
    if phase.startswith('acceptance') and len(list((ROOT/'runs'/phase).glob('*/started.json'))) >= config['formal_run_cap']:
        raise RuntimeError('Formal run cap reached; preserve all records')
    directory.mkdir(parents=True,exist_ok=True)
    ipath=instance_path(instance); inst=load_instance(ipath)
    dump(directory/'input.json',inst);dump(directory/'config.json',config)
    dump(directory/'started.json',{'started_at':now(),'arm':arm,'instance':instance,'input_sha256':sha(ipath)})
    begun=time.monotonic();calls=[];tool_records=[];candidates=[];schedule=None;validation=None
    status='failed';reason=None;solver_seconds=0.;first_valid=None;revisions=0
    first_candidate_feasible=None;decision_count=0;selected_candidate=None
    try:
        if arm=='A':
            from classical import solve
            s=solve(ipath,directory/'solver_1',time_limit=config['solver_total_seconds'],seed=config['seeds'][repetition-1],configuration=config['classical_configuration'])
            tool_records.append(s);solver_seconds+=s['solver_seconds']
            schedule=s.get('schedule')
            if s.get('first_schedule'):
                first_check=validate_schedule(inst,s['first_schedule'])
                dump(directory/'first_solver_validation.json',first_check)
                first_candidate_feasible=first_check['feasible']
            if schedule:
                validation=validate_schedule(inst,schedule)
                if validation['feasible']: first_valid=time.monotonic()-begun
            status='success' if validation and validation['feasible'] else 'failed'
            reason=None if status=='success' else 'solver_no_valid_schedule'
            dump(directory/'solver_result.json',s)
        else:
            from model_transport import call_model
            from dispatch import build_schedule, DispatchError
            prompt_template=(ROOT/'configs'/f'prompt_{arm}.txt').read_text()
            history=[]
            base=prompt_template+'\nINSTANCE (only this run):\n'+json.dumps(compact_instance(inst),ensure_ascii=False,separators=(',',':'))
            for turn in range(1,config['max_model_calls']+1):
                if time.monotonic()-begun>config['run_timeout_seconds']:
                    reason='run_timeout';status='timeout';break
                context={'remaining_model_calls':config['max_model_calls']-turn+1,'history':history}
                if arm=='C': context.update(remaining_solver_calls=config['max_solver_calls']-len(tool_records),remaining_solver_seconds=max(0,config['solver_total_seconds']-sum(x['requested_time_limit'] for x in tool_records)))
                prompt=base+'\nCURRENT STATE / TOOL FEEDBACK:\n'+json.dumps(context,ensure_ascii=False,separators=(',',':'))
                phase_cap=config['formal_model_call_cap'] if phase.startswith('acceptance') else config['development_model_call_cap']
                used_attempts=len(list((ROOT/'runs'/phase).rglob('request.json')))
                if used_attempts>=phase_cap:
                    reason='phase_model_call_cap';break
                c=call_model(prompt,schema_b() if arm=='B' else schema_c(),directory/f'model_{turn:02d}',config['model'])
                calls.append(c)
                if c['status']!='success':
                    reason=c['failure_reason'];status=c['status'];break
                decision=c['output'];decision_count+=1
                dump(directory/f'decision_{turn:02d}.json',decision)
                if arm=='B':
                    feedback={}; candidate=None
                    try:
                        candidate=build_schedule(inst,decision['actions'])
                        checked=validate_schedule(inst,candidate)
                        feedback={'tool':'dispatch_and_validate','validation':checked,'schedule':candidate}
                    except (DispatchError,KeyError,ValueError,TypeError) as e:
                        checked={'feasible':False,'violations':[{'code':'dispatch_error','message':str(e)}],'objective':None}
                        feedback={'tool':'dispatch_and_validate','validation':checked,'details':getattr(e,'feedback',None)}
                    if first_candidate_feasible is None: first_candidate_feasible=checked['feasible']
                    revisions=turn-1
                    dump(directory/f'feedback_{turn:02d}.json',feedback)
                    candidates.append({'turn':turn,'validation':checked,'schedule':candidate})
                    if checked['feasible']:
                        schedule=candidate;validation=checked;status='success';reason=None
                        first_valid=time.monotonic()-begun;selected_candidate=len(candidates);break
                    history.append({'decision':decision,'feedback':feedback});reason='infeasible_schedule'
                else:
                    if decision['action']=='finish':
                        idx=decision['candidate']-1
                        if 0<=idx<len(candidates) and candidates[idx]['validation']['feasible']:
                            schedule=candidates[idx]['schedule'];validation=candidates[idx]['validation']
                            status='success';reason=None;selected_candidate=idx+1;break
                        feedback={'error':'finish requires a valid candidate index (1-based)'}
                    else:
                        remaining=config['solver_total_seconds']-sum(x['requested_time_limit'] for x in tool_records)
                        limit=decision['time_limit'];seed=decision['seed'];preset=decision['configuration']
                        if len(tool_records)>=config['max_solver_calls'] or type(limit) is not int or not 1<=limit<=remaining or type(seed) is not int or not 0<=seed<=2147483647:
                            feedback={'error':'solver budget/parameter violation','remaining_seconds':remaining}
                        else:
                            from classical import solve
                            s=solve(ipath,directory/f'solver_{len(tool_records)+1}',time_limit=limit,seed=seed,configuration=preset)
                            s['requested_time_limit']=limit;tool_records.append(s);solver_seconds+=s['solver_seconds']
                            candidate=s.get('schedule');checked=validate_schedule(inst,candidate) if candidate else {'feasible':False,'violations':[{'code':'solver_no_schedule','message':s.get('solver_status','unknown')}],'objective':None}
                            candidates.append({'turn':turn,'validation':checked,'schedule':candidate})
                            if first_candidate_feasible is None:first_candidate_feasible=checked['feasible']
                            if checked['feasible'] and first_valid is None:first_valid=time.monotonic()-begun
                            feedback={'tool':'solve_and_validate','candidate':len(candidates),'solver_status':s.get('solver_status'),'solver_seconds':s['solver_seconds'],'validation':checked,'schedule':candidate}
                            revisions=max(0,len(candidates)-1)
                    dump(directory/f'feedback_{turn:02d}.json',feedback)
                    history.append({'decision':decision,'feedback':feedback});reason='agent_not_finished'
            if status!='success' and reason is None:reason='model_step_limit'
    except Exception as e:
        reason=f'{type(e).__name__}: {e}';status='failed';(directory/'exception.txt').write_text(traceback.format_exc())
    if schedule: dump(directory/'schedule.json',schedule)
    if validation:dump(directory/'validation.json',validation)
    result={'run_id':rid,'phase':phase,'arm':arm,'instance':instance,'repetition':repetition,
        'started_at':read(directory/'started.json')['started_at'],'finished_at':now(),
        'status':status,'failure_reason':reason,'failure_category':(None if status=='success' else 'environment_model' if reason and ('model_transport' in reason or 'model_launch' in reason) else 'infeasible_schedule' if reason=='infeasible_schedule' else 'agent_output_or_timeout' if arm in ('B','C') else 'solver_or_semantics'),'schedule_file':'schedule.json' if schedule else None,
        'validation':validation,'objective':validation.get('objective') if validation else None,
        'first_candidate_feasible':first_candidate_feasible,'first_valid_output_seconds':first_valid,
        'end_to_end_seconds':time.monotonic()-begun,'model_elapsed_seconds':sum(c['duration_seconds'] for c in calls),
        'pure_model_seconds':None if calls else 0,'solver_seconds':solver_seconds,
        'model_calls':len(calls),'usage':aggregate_usage(calls),'cost_usd':None if calls else 0,
        'cost_status':'unknown_subscription_billing' if calls else 'no_model_calls',
        'revision_count':revisions,'fallback':False,'decision_count':decision_count,
        'solver_calls':len(tool_records),'solver_statuses':[x.get('solver_status') for x in tool_records],
        'solver_time_limit_reached':any(x.get('timed_out',False) for x in tool_records),
        'solver_first_witness_seconds':[x.get('first_witness_seconds') for x in tool_records],
        'selected_candidate':selected_candidate,'input_sha256':sha(ipath),'config_sha256':sha(directory/'config.json'),
        'baseline_gap_pct':None}
    dump(result_path,result)
    print(json.dumps({k:result[k] for k in ['run_id','status','failure_reason','objective','end_to_end_seconds','model_calls']},ensure_ascii=False),flush=True)
    return result

def freeze(config):
    paths=[]
    for glob in ['src/*.py','src/*.lp','scripts/build_classical.py','configs/*.json','configs/*.txt','data/*.lp','requirements.lock','docs/PROTOCOL.md','docs/problem-spec.md']:
        paths.extend(ROOT.glob(glob))
    paths.extend(VENDOR.glob('*.lp'));paths.extend(VENDOR.glob('instances/*.lp'))
    paths.extend([ROOT/'docs/source-manifest.json',ROOT/'vendor/clingo-dl/app/src/main.cc',ROOT/'vendor/clingo-dl/app/lib/src/app.cc',ROOT/'vendor/clingo-dl/app/lib/clingo-dl-app/app.hh',ROOT/'vendor/clingo-dl/build/clingo-dl'])
    paths=[p for p in paths if p.name!='freeze.json']
    record={'created_at':now(),'files':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))},'python':sys.version,'platform':platform.platform(),'config':config}
    target=ROOT/'configs/freeze.json'
    if target.exists():raise FileExistsError('Frozen already; do not replace after formal results')
    dump(target,record);print(f'Frozen {len(paths)} files')

def check_freeze():
    f=read(ROOT/'configs/freeze.json')
    bad=[p for p,h in f['files'].items() if not (ROOT/p).exists() or sha(ROOT/p)!=h]
    if bad:raise RuntimeError(f'Frozen files changed: {bad}')

def main():
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='command',required=True)
    r=sp.add_parser('run');r.add_argument('--arm',choices=['A','B','C'],required=True);r.add_argument('--instance',required=True);r.add_argument('--repetition',type=int,default=1);r.add_argument('--phase',default='development');r.add_argument('--run-id')
    b=sp.add_parser('batch');b.add_argument('--phase',default='acceptance_v1');b.add_argument('--arms',default='A,B,C')
    sp.add_parser('freeze');sp.add_parser('verify-freeze')
    args=p.parse_args();config=read(ROOT/'configs/run_config.json')
    if args.command=='freeze':freeze(config)
    elif args.command=='verify-freeze':check_freeze();print('freeze verified')
    elif args.command=='run':
        if args.phase.startswith('acceptance'):check_freeze()
        run(args.arm,args.instance,args.repetition,args.phase,config,args.run_id)
    elif args.command=='batch':
        check_freeze();split=read(ROOT/'configs/instance_split.json')
        if args.phase!='acceptance_v1':raise ValueError('New acceptance version needs new locked manifest')
        for instance in split['acceptance_v1']:
            for rep in range(1,4):
                for arm in args.arms.split(','):
                    result=run(arm,instance,rep,args.phase,config)
                    if result['failure_reason'] in {'model_transport_error','model_launch_error'}:
                        raise SystemExit('External model channel failed; batch stopped, completed runs preserved')

if __name__=='__main__':main()
