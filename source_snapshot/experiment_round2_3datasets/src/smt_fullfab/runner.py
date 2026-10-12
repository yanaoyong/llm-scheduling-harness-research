"""Bounded, serial development runs. No formal run is implied by success here."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import traceback

from .environment import FullFabEnvironment,plan_from_action,write_new,digest
from .reference import reference_action
from .audit import audit_trace

ROOT=Path(__file__).resolve().parents[2]


def stream_audit(path, out, *, data_dir, window_start):
    """Keep complete reports on disk; only the six primary metrics enter result."""
    from .stream_audit_bundle import audit_to_bundle, read_bundle
    sha=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
    created=audit_to_bundle(path,output_dir=out/'audit_bundle',expected_source_sha256=sha.hexdigest(),
        verify_data_dir=data_dir,window_start=window_start,require_terminal=True)
    checked=read_bundle(out/'audit_bundle',expected_manifest_sha256=created['report_sha256'])
    if (not checked['storage_verified'] or checked['source_receipt']!=created['source_receipt']
            or checked['summary']!=created['summary']):
        raise ValueError('published audit bundle differs')
    return checked['summary'],{'path':'audit_bundle','manifest_sha256':created['report_sha256']}


def planner_cost_summary(response):
    """The complete immutable response is on disk; retain only additive costs."""
    return {key:response.get(key) for key in
        ('wall_seconds','solve_wall_seconds','classical_construction_wall_seconds')}


def include_result_bytes(result, *, existing_bytes, limit):
    """Include the exact compact result encoding in the cumulative byte check.

    An overrun is evidence, not a reason to discard the result. This predicts
    final result bytes under the exclusive runner; outer acceptance measures all
    actual files and full process duration after final publication and exit.
    """
    result['resource_measurement_scope']='runner tree plus inherited logs; wall excludes final result publication/stdout/process exit; enclosing supervisor required for resource acceptance'
    result['cumulative_log_bytes_including_result']=0
    for _ in range(32):
        encoded=(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        total=existing_bytes+len(encoded)
        if total>limit and 'final log volume cap including result publication' not in (result.get('failure') or ''):
            result['status']='failed'
            result['failure']=(result['failure']+'; ' if result.get('failure') else '')+'final log volume cap including result publication'
            continue
        if total==result['cumulative_log_bytes_including_result']:return
        result['cumulative_log_bytes_including_result']=total
    raise RuntimeError('result byte accounting did not converge')


def source_snapshot(out):
    sources={}
    for base in ('src/smt_fullfab','src/smt'):
        for p in sorted((ROOT/base).glob('*.py')):
            rel=p.relative_to(ROOT)
            target=out/'source_snapshot'/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(p.read_bytes())
            sources[str(rel)]=hashlib.sha256(p.read_bytes()).hexdigest()
    root_init=out/'source_snapshot/src/__init__.py'
    root_init.write_bytes((ROOT/'src/__init__.py').read_bytes())
    return {'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_sha256':sources,'requirements_sha256':hashlib.sha256((ROOT/'requirements.lock').read_bytes()).hexdigest()}


def crop_plan(plan,env):
    """Record original plan separately; only omit starts outside observation."""
    plan=json.loads(json.dumps(plan))
    plan['version']=str(plan['version'])
    plan['scope']=sorted(env.physical)
    plan['prediction_horizon_end']=plan['valid_until']
    plan['valid_until']=min(plan['valid_until'],env.horizon)
    plan['freeze_until']=min(plan['freeze_until'],plan['valid_until'])
    excluded=[];kept=[];cut_machines=set()
    for task in plan['tasks']:
        if task['machine'] in cut_machines or task['not_before']>=plan['valid_until']:
            cut_machines.add(task['machine']);excluded.append(task)
        else:kept.append(task)
    plan['unobserved_future_task_ids']=[t['id'] for t in excluded]
    plan['tasks']=kept
    kept_ids={t['id'] for t in plan['tasks']}
    for h in plan.get('holds',[]):
        h['until']=min(h['until'],plan['valid_until'])
        if h.get('after_task_id') is not None and h['after_task_id'] not in kept_ids:
            earlier=[t for t in plan['tasks'] if t['machine']==h['machine']]
            if earlier:h['after_task_id']=earlier[-1]['id']
            else:h.pop('after_task_id')
    for mid in sorted(cut_machines):
        # The submitted first start was already later than observation_end.
        # Preserve that exact waiting intent when projecting the future plan.
        earlier=[t for t in kept if t['machine']==mid]
        after=earlier[-1]['id'] if earlier else None
        existing=next((h for h in plan['holds'] if h['machine']==mid and h.get('after_task_id')==after),None)
        if existing:existing['until']=plan['valid_until']
        else:
            hold={'machine':mid,'until':plan['valid_until'],
                  'reason':'submitted next planned start lies beyond observation endpoint'}
            if after is not None:hold['after_task_id']=after
            plan['holds'].append(hold)
    merged={}
    for hold in plan.get('holds',[]):
        key=(hold['machine'],hold.get('after_task_id'))
        if key not in merged:merged[key]=hold
        else:
            merged[key]['until']=max(merged[key]['until'],hold['until'])
            merged[key]['reason']='union of equivalent projected explicit waits'
    plan['holds']=list(merged.values())
    plan['observation_projection']='ordered-machine-prefix-and-equivalent-waits-v1'
    return plan


def run(*,arm='reference_cr',run_id,seconds=3600,seed=1701,wall_seconds=180,
        max_plans=20000,plan_seconds=14400,period_seconds=1800,lookahead_depth=2,
        solver_seconds=5,solver_budget_seconds=60,max_slots=2,snapshot_path=None,solver_method='global',
        max_log_bytes=536870912,constructor_seconds=5,max_candidate_evaluations=250000,
        max_trace_bytes=268435456,audit_mode='legacy',snapshot_mode='legacy'):
    config={k:v for k,v in locals().items()}
    if type(max_trace_bytes) is not int or max_trace_bytes<=0:raise ValueError('invalid trace byte limit')
    if audit_mode not in ('legacy','stream') or snapshot_mode not in ('legacy','stream'):
        raise ValueError('invalid audit or snapshot mode')
    # Old default identities remain readable; every nondefault resource choice
    # enters both the new run identity and the cumulative recovery limits.
    storage_options={'max_trace_bytes':max_trace_bytes,'audit_mode':audit_mode,'snapshot_mode':snapshot_mode}
    extended_storage=storage_options!={'max_trace_bytes':268435456,'audit_mode':'legacy','snapshot_mode':'legacy'}
    if not extended_storage:
        for key in storage_options:config.pop(key)
    out=ROOT/'runs/smt_fullfab_development'/run_id
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in run_id):
        raise ValueError('unsafe run id')
    identity=digest(config)
    if out.exists():
        if (out/'result.json').exists():
            result=json.loads((out/'result.json').read_text())
            if result['identity']==identity:
                print('SKIP',run_id,result['status'],flush=True);return result
        raise FileExistsError('existing/interrupted run is preserved; use recorded recovery path')
    out.mkdir(parents=True)
    start=time.monotonic()
    write_new(out/'config.json',config)
    write_new(out/'claim.json',{'pid':os.getpid(),'identity':identity,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    provenance=source_snapshot(out)
    write_new(out/'provenance.json',provenance)
    env=None;solvers=[];count=0;status='failed';failure=None;audit=None;inherited_solver_seconds=0
    audit_bundle=None;checkpoint_written=False;checkpoint_failure=None
    hybrid=None;hybrid_config=None;inherited_constructor_seconds=0
    hybrid_limits=None;inherited_planner_calls=0;inherited_wall_seconds=0;inherited_log_bytes=0
    try:
        if solver_method=='hybrid':
            if arm!='A':raise ValueError('offline hybrid method is only available to A')
            from .hybrid import HybridSchedule,configuration,solve_hybrid_plan
            hybrid_config=configuration(period_seconds=period_seconds,plan_seconds=plan_seconds,
                lookahead_depth=lookahead_depth,max_slots=max_slots,solver_seconds=solver_seconds,
                constructor_seconds=constructor_seconds,max_candidate_evaluations=max_candidate_evaluations)
            hybrid_limits={'runner_wall_seconds':wall_seconds,'max_plans':max_plans,
                           'max_log_bytes':max_log_bytes}
            if extended_storage:hybrid_limits.update(storage_options)
        env=FullFabEnvironment(seed=seed,window_seconds=seconds,trace_path=out/'trace.jsonl') if snapshot_path is None else FullFabEnvironment.from_snapshot(snapshot_path,trace_path=out/'trace.jsonl')
        if env.horizon != seconds:raise ValueError('snapshot horizon differs; never regenerate future release state')
        if env.seed != seed:raise ValueError('snapshot scenario seed differs from requested identity')
        if snapshot_path is not None and arm=='A':
            resource_path=Path(snapshot_path).with_name('checkpoint_resources.json')
            if not resource_path.exists():raise ValueError('resume lacks resource checkpoint; audit legacy evidence before migrating')
            inherited=json.loads(resource_path.read_text())
            inherited_solver_seconds=inherited['cumulative_solver_requested_seconds']
            if inherited['arm']!=arm or inherited['solver_budget_seconds']!=solver_budget_seconds:
                raise ValueError('resumed arm/budget differs; cannot silently reset allowance')
            if solver_method=='hybrid':
                if inherited.get('solver_method')!='hybrid' or not inherited.get('hybrid_state'):
                    raise ValueError('resume lacks explicit hybrid state; never infer it from a legacy checkpoint')
                inherited_constructor_seconds=inherited.get('cumulative_classical_construction_wall_seconds')
                if inherited.get('hybrid_resource_limits')!=hybrid_limits:
                    raise ValueError('resumed hybrid resource limits differ; cannot reset or enlarge them')
                inherited_planner_calls=inherited['cumulative_planner_calls']
                inherited_wall_seconds=inherited['cumulative_runner_wall_seconds']
                prior_log_bytes=inherited['log_bytes_in_earlier_runs']
                if (type(inherited_planner_calls) is not int or inherited_planner_calls<0
                    or isinstance(inherited_wall_seconds,bool) or not isinstance(inherited_wall_seconds,(int,float))
                    or not math.isfinite(inherited_wall_seconds) or inherited_wall_seconds<0
                    or type(prior_log_bytes) is not int or prior_log_bytes<0):
                    raise ValueError('invalid inherited hybrid resource counters')
                inherited_log_bytes=prior_log_bytes+sum(p.stat().st_size for p in resource_path.parent.rglob('*') if p.is_file())
                hybrid=HybridSchedule(hybrid_config,state=inherited['hybrid_state'])
            elif inherited.get('hybrid_state') is not None:
                raise ValueError('cannot silently change a resumed hybrid method')
        elif solver_method=='hybrid':
            hybrid=HybridSchedule(hybrid_config)
        observed_start=env.t
        stop=env.advance_plan(env.t)
        while not env.finished:
            if inherited_wall_seconds+time.monotonic()-start>=wall_seconds:raise TimeoutError('run wall budget reached at plan boundary')
            if (inherited_planner_calls+len(solvers) if hybrid else count)>=max_plans:raise RuntimeError('plan count cap')
            if (out/'trace.jsonl').stat().st_size>max_trace_bytes:raise RuntimeError('trace volume cap')
            if inherited_log_bytes+sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>=max_log_bytes:
                raise RuntimeError('total log admission cap reached; prior operation may overshoot')
            if arm.startswith('reference_'):
                choice=reference_action(env,arm.removeprefix('reference_'))
                plan=plan_from_action(env,choice['action'],run_id+':'+str(count),valid_seconds=period_seconds,reason=arm)
                plan['reference_provenance']=choice['provenance']
            elif arm=='A':
                if solver_method=='global':
                    from .optimizer import solve_plan
                elif solver_method=='decomposed':
                    from .decomposition import solve_decomposed_plan as solve_plan
                elif solver_method=='hybrid':
                    pass
                else:raise ValueError('unknown classical method')
                remaining=solver_budget_seconds-inherited_solver_seconds-sum(x['requested_seconds'] for x in solvers)
                if hybrid:
                    planner_mode,request=hybrid.request(env.t,remaining)
                    schedule_before=hybrid.snapshot()
                else:
                    if remaining<0.05:raise RuntimeError('solver cumulative budget exhausted')
                    planner_mode=solver_method;request=min(remaining,solver_seconds)
                problem=env.problem(plan_seconds=plan_seconds,lookahead_depth=lookahead_depth)
                write_new(out/f'problem_{count:05d}.json',problem)
                reservation={'event':'solver_reserve','arm':arm,'plan':count,'requested_seconds':request,
                    'planner_mode':planner_mode,'constructor_seconds_limit':constructor_seconds if planner_mode=='event_classical' else None,
                    'max_candidate_evaluations':max_candidate_evaluations if planner_mode=='event_classical' else None}
                with (out/'resources.jsonl').open('a') as f:f.write(json.dumps(reservation)+'\n')
                entry={'requested_seconds':request,'planner_mode':planner_mode};solvers.append(entry)
                solve_started=time.monotonic()
                try:
                    if hybrid:
                        response=solve_hybrid_plan(problem,mode=planner_mode,config=hybrid_config,
                            time_limit_seconds=request,seed=11,plan_version=run_id+':'+str(count))
                        response['hybrid_schedule_before_commit']=schedule_before
                    else:
                        response=solve_plan(problem,time_limit_seconds=request,seed=11,max_slots_per_machine=max_slots,plan_version=run_id+':'+str(count))
                except Exception as exc:
                    evidence={'event':'solver_finish','plan':count,'solver_status':'EXCEPTION',
                              'wall_seconds':time.monotonic()-solve_started,
                              'error_type':type(exc).__name__,'error':str(exc),
                              'requested_seconds_consumed':request,'partial_solver_output_available':False,
                              'planner_mode':planner_mode,
                              'solve_wall_seconds':0 if planner_mode=='event_classical' else None,
                              'classical_construction_wall_seconds':None}
                    entry.update(evidence)
                    write_new(out/f'solver_exception_{count:05d}.json',evidence)
                    with (out/'resources.jsonl').open('a') as f:f.write(json.dumps(evidence)+'\n')
                    raise
                entry.update(planner_cost_summary(response))
                write_new(out/f'solver_{count:05d}.json',response)
                with (out/'resources.jsonl').open('a') as f:f.write(json.dumps({'event':'solver_finish','plan':count,
                    'solver_status':response['solver_status'],'wall_seconds':response['wall_seconds'],
                    'planner_mode':planner_mode,'solve_wall_seconds':response.get('solve_wall_seconds'),
                    'classical_construction_wall_seconds':response.get('classical_construction_wall_seconds')})+'\n')
                if response['solver_status'] not in ('OPTIMAL','FEASIBLE','FEASIBLE_HEURISTIC'):
                    raise RuntimeError('solver_no_plan:'+response['solver_status'])
                plan=crop_plan(response['plan'],env)
            else:
                raise ValueError('unknown offline arm')
            env.commit_plan(plan)
            if hybrid:hybrid.committed(env.t,planner_mode)
            count+=1
            stop=env.advance_plan(hybrid.advance_until(env.t,env.horizon) if hybrid else min(env.horizon,env.t+period_seconds))
            if count%100==0:print(run_id,'plans',count,'sim_seconds',round(env.t,2),'wall',round(time.monotonic()-start,2),flush=True)
        if audit_mode=='stream':
            audit,audit_bundle=stream_audit(out/'trace.jsonl',out,data_dir=env.data_dir,window_start=observed_start)
        else:
            audit=audit_trace(out/'trace.jsonl',verify_data_dir=env.data_dir,window_start=observed_start)
            write_new(out/'audit.json',audit)
        status='success' if audit['valid'] else 'failed'
        if not audit['valid']:failure='independent_audit_failed'
    except Exception as exc:
        failure=f'{type(exc).__name__}: {exc}'
        (out/'exception.txt').write_text(traceback.format_exc())
    constructor_costs=[x.get('classical_construction_wall_seconds') for x in solvers]
    constructor_wall=sum(constructor_costs) if hybrid_config and all(x is not None for x in constructor_costs) else None
    cumulative_constructor_wall=(inherited_constructor_seconds+constructor_wall
        if inherited_constructor_seconds is not None and constructor_wall is not None else None)
    cp_costs=[x.get('solve_wall_seconds') for x in solvers]
    planner_costs=[x.get('wall_seconds') for x in solvers]
    if env:
        try:
            if snapshot_mode=='stream':
                from .stream_snapshot import write_snapshot
                write_snapshot(env,out/'checkpoint.json')
            else:env.snapshot(out/'checkpoint.json')
            checkpoint_written=True
        except Exception as exc:
            checkpoint_failure=f'{type(exc).__name__}: {exc}'
            (out/'checkpoint_exception.txt').write_text(traceback.format_exc())
            status='failed'
            failure=(failure+'; ' if failure else '')+'checkpoint_failed: '+checkpoint_failure
        write_new(out/'checkpoint_resources.json',{'arm':arm,'solver_budget_seconds':solver_budget_seconds,
                  'cumulative_solver_requested_seconds':inherited_solver_seconds+sum(x['requested_seconds'] for x in solvers),
                  'scenario_seed':env.seed,'model_calls':0,'parent_checkpoint':snapshot_path,
                  'solver_method':solver_method,'hybrid_state':hybrid.snapshot() if hybrid else None,
                  'hybrid_resource_limits':hybrid_limits,
                  'cumulative_planner_calls':inherited_planner_calls+len(solvers),
                  'cumulative_runner_wall_seconds':inherited_wall_seconds+time.monotonic()-start,
                  'log_bytes_in_earlier_runs':inherited_log_bytes,
                  'cumulative_classical_construction_wall_seconds':cumulative_constructor_wall})
    # Admission checks can overshoot by an operation, audit or snapshot. A
    # successful terminal observation never waives the final resource bounds.
    violations=[]
    if (out/'trace.jsonl').exists() and (out/'trace.jsonl').stat().st_size>max_trace_bytes:
        violations.append('final trace volume cap')
    if inherited_log_bytes+sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>max_log_bytes:
        violations.append('final log volume cap before result publication')
    if inherited_wall_seconds+time.monotonic()-start>wall_seconds:violations.append('final run wall budget')
    if violations:
        status='failed';failure=(failure+'; ' if failure else '')+'; '.join(violations)
    result={'status':status,'failure':failure,'identity':identity,'config':config,'provenance':provenance,
            'plans':count,'simulation_seconds':env.t if env else None,'full_window_completed':bool(env and env.finished),
            'metrics':audit['metrics'] if audit else None,'audit_valid':bool(audit and audit['valid']),
            'model_calls':0,'solver_calls':sum(x['requested_seconds']>0 for x in solvers),
            'planner_calls':len(solvers),'classical_event_calls':sum(x['planner_mode']=='event_classical' for x in solvers),
            'cumulative_planner_calls':inherited_planner_calls+len(solvers),
            'cumulative_runner_wall_seconds':inherited_wall_seconds+time.monotonic()-start,
            'solver_requested_seconds':sum(x['requested_seconds'] for x in solvers),
            'actual_cp_solve_seconds':sum(cp_costs) if all(x is not None for x in cp_costs) else None,
            'planner_wall_seconds':sum(planner_costs) if all(x is not None for x in planner_costs) else None,
            'classical_construction_wall_seconds':constructor_wall,
            'cumulative_classical_construction_wall_seconds':cumulative_constructor_wall,
            'wall_seconds':time.monotonic()-start,'cost_usd':None,'formal':False,
            'checkpoint':str((out/'checkpoint.json').relative_to(ROOT)) if checkpoint_written else None}
    if audit_bundle is not None:
        result['audit_bundle']=audit_bundle
        result['metrics_scope']='primary summary only; complete metrics are in audit_bundle/metrics.json'
    if checkpoint_failure is not None:result['checkpoint_failure']=checkpoint_failure
    include_result_bytes(result,existing_bytes=inherited_log_bytes+sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),limit=max_log_bytes)
    write_new(out/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('metrics','provenance')},ensure_ascii=False),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--arm',default='reference_cr',choices=['reference_cr','reference_fifo','reference_edd','A'])
    p.add_argument('--run-id',required=True);p.add_argument('--seconds',type=int,default=3600);p.add_argument('--seed',type=int,default=1701)
    p.add_argument('--wall-seconds',type=float,default=180);p.add_argument('--max-plans',type=int,default=20000)
    p.add_argument('--plan-seconds',type=int,default=14400);p.add_argument('--period-seconds',type=int,default=1800)
    p.add_argument('--lookahead-depth',type=int,default=2);p.add_argument('--solver-seconds',type=float,default=5)
    p.add_argument('--solver-budget-seconds',type=float,default=60);p.add_argument('--max-slots',type=int,default=2)
    p.add_argument('--snapshot-path')
    p.add_argument('--solver-method',choices=['global','decomposed','hybrid'],default='global')
    p.add_argument('--max-log-bytes',type=int,default=536870912)
    p.add_argument('--constructor-seconds',type=float,default=5)
    p.add_argument('--max-candidate-evaluations',type=int,default=250000)
    p.add_argument('--max-trace-bytes',type=int,default=268435456)
    p.add_argument('--audit-mode',choices=['legacy','stream'],default='legacy')
    p.add_argument('--snapshot-mode',choices=['legacy','stream'],default='legacy')
    result=run(**vars(p.parse_args()));raise SystemExit(0 if result['status']=='success' else 1)
