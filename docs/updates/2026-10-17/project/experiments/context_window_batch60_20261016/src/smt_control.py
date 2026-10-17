"""Full-factory A/B/C controller, bounded and isolated at each observable state."""
from __future__ import annotations
import argparse
import dataclasses
import json
from pathlib import Path
import shutil
import os
import socket
import time
import traceback
from src.experiment import ROOT,now,read_json,write_json,provenance,object_digest,verify_freeze,digest
from src.agents.model_transport import ModelConfig,call_model
from src.agents.budget import BudgetLedger,BudgetExceeded
from src.smt.environment import SmtEnvironment
from src.smt.optimizer import solve_action
from src.smt.audit import audit_trace

ACTION_SCHEMA={'type':'object','properties':{
    'dispatches':{'type':'array','items':{'type':'object','properties':{
        'machine':{'type':'integer'},'lot_ids':{'type':'array','items':{'type':'string'}}},
        'required':['machine','lot_ids'],'additionalProperties':False}},
    'wait_seconds':{'type':'number'},'rationale':{'type':'string'}},
    'required':['dispatches','wait_seconds','rationale'],'additionalProperties':False}
WEIGHTS=('priority_weight','waiting_weight','fill_weight','setup_weight')
C_SCHEMA={'type':'object','properties':{
    'action':{'type':'string','enum':['solve','apply']},'candidate_index':{'type':['integer','null']},
    'time_limit':{'type':['number','null']},'seed':{'type':['integer','null']},
    **{k:{'type':['integer','null']} for k in WEIGHTS},'rationale':{'type':'string'}},
    'required':['action','candidate_index','time_limit','seed',*WEIGHTS,'rationale'],
    'additionalProperties':False}
BASE_PROMPT='''You control only the two listed physical machines inside the full SMT2020 public simulation testbed.
Minimize integrated waiting queue (lot-seconds) in the controlled machine families over the fixed window;
also report tradeoffs in completed operations, full-lot throughput and tardiness. Never violate hard constraints.
Only current observations are provided. Future breakdowns, arrivals and sampled rework are not observable.
All other machines use the same fixed environment policy. Do not access native tools or reference results.
The time unit is seconds. Only exact listed current candidates can be dispatched. Compatible batches
must share batch_key and contain batch_min..batch_max lots; nonbatch machines select one lot.
Waiting is an explicit 0..1800 second action and consumes a decision. Never silently hand control to a rule.
'''
B_PROMPT=BASE_PROMPT+'''Return dispatches with exact machine and lot_ids, plus wait_seconds and concise rationale.
You decide the actual jobs and batches. The executor only validates and executes your chosen actions.
You may batch simultaneous actions across machines. Empty dispatches require positive waiting.
'''
C_PROMPT=BASE_PROMPT+'''You choose parameters for a CP-SAT immediate-dispatch optimization, then inspect its returned
action and explicitly apply a candidate. The solver does not forecast future factory events or plan multiple steps.
Its reward is sum(fill_weight + priority_weight*priority + waiting_weight*floor(wait_minutes)) over selected lots,
minus setup_weight*floor(setup_minutes) once per selected group. Batch compatibility/capacity and lot uniqueness are hard.
Choose solve with time_limit (0.05..5 seconds), seed (0..2147483647), and integer weights (0..10000).
Choose apply with candidate_index to commit that exact action; unused fields must be null. Reserve one response
for apply. No candidate is applied automatically. Limit changes to the remaining calls and seconds.
'''


def run(arm,run_id,config_path,*,phase='development',scenario=701,repeat=1,freeze=None):
    begun=time.monotonic();started=now();cfg=read_json(config_path)
    cfg['model']['phase']='development' if phase=='development' else 'formal'
    cfg['seed']=[11,22,33][repeat-1]
    out=ROOT/'runs'/phase/run_id
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in run_id):
        raise ValueError('Unsafe run identifier')
    identity={'arm':arm,'scenario':scenario,'repeat':repeat,'config_sha256':object_digest(cfg)}
    frozen=None
    if phase!='development':
        frozen=verify_freeze(freeze)
        if [scenario,arm,repeat] not in frozen['matrix'] or run_id!=f'smt{scenario}_{arm}_r{repeat}':
            raise ValueError('SMT identity outside frozen matrix')
        if identity['config_sha256']!=frozen['effective_config_sha256'][str(repeat)] or cfg['protocol_version']!=frozen['protocol_version']:
            raise ValueError('SMT effective config/protocol not frozen')
        if str(Path(config_path).resolve().relative_to(ROOT))!=frozen['config_path']:
            raise ValueError('SMT config path not frozen')
    if out.exists():
        if (out/'result.json').exists() and read_json(out/'result.json')['identity']==identity:
            old=read_json(out/'result.json');print('SKIP',run_id,old['status'],flush=True);return old
        raise RuntimeError('Existing or interrupted SMT run cannot be overwritten')
    out.mkdir(parents=True);write_json(out/'claim.json',{'identity':identity,'started_at':started,
        'process_id':os.getpid(),'hostname':socket.gethostname()},exclusive=True)
    model_cfg=ModelConfig(**cfg['model']);ledger=BudgetLedger(model_cfg.ledger_path)
    models=[];solvers=[];actions=[];failures=[];env=None
    result={'run_id':run_id,'family':'smt2020','instance_id':f'LVHM_seed{scenario}',
        'identity':identity,'phase':phase,'scenario':scenario,'repeat':repeat,'arm':arm,
        'config_path':str(Path(config_path).resolve().relative_to(ROOT)),
        'started_at':started,'status':'failed','failure_type':None,'fallback':False}
    version=provenance({'scenario':scenario,'source_manifest':read_json(ROOT/'data/smt/source-manifest.json')},cfg,cfg['protocol_version'])
    if frozen:
        write_json(out/'freeze.json',frozen,exclusive=True)
        version.update(code_commit=frozen['code_commit'],freeze_tag=frozen['tag'],freeze_manifest_sha256=digest(out/'freeze.json'))
    result.update(version);write_json(out/'config.json',cfg,exclusive=True)
    for relative in version['source_sha256']:
        target=out/'source_snapshot'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/relative,target)
    deadline=begun+cfg['wall_seconds']

    def invoke(prompt,schema,decision,attempt):
        if len(models)>=cfg['max_model_calls'][arm]:raise RuntimeError('model_call_budget_exhausted')
        remaining=deadline-time.monotonic()
        if remaining<1:raise TimeoutError('run_wall_deadline')
        r=call_model(prompt,schema,out/f'model_{decision:02d}_{attempt:02d}',
            dataclasses.replace(model_cfg,timeout_seconds=min(remaining,model_cfg.timeout_seconds)))
        models.append(r)
        if r['status']!='success':raise RuntimeError('model_channel:'+str(r['failure_reason']))
        if time.monotonic()>deadline:raise TimeoutError('late_model_response')
        return r['output']

    def optimize(state,params,decision):
        if sum(s['parameters']['time_limit'] for s in solvers)+params['time_limit']>cfg['solver_budget_seconds']:
            raise RuntimeError('solver_run_budget_exhausted')
        sid=ledger.reserve_solver(phase=model_cfg.phase,run_id=str(out),grant_id=cfg['solver_grant_id'],
            requested_seconds=params['time_limit'],metadata={'arm':arm,'decision':decision,'parameters':params})
        solver_begun=time.monotonic()
        try:r=solve_action(state,**params)
        except Exception as exc:
            elapsed=time.monotonic()-solver_begun
            ledger.finish(sid,'failed',{'error':str(exc),'wall_seconds':elapsed})
            failed={'solver_call_id':sid,'decision':decision,'parameters':params,'solver_status':'ERROR',
                    'status':'failed','error':str(exc),'wall_seconds':elapsed,'action':None,
                    'objective':None,'best_bound':None}
            solvers.append(failed);write_json(out/f'solver_{len(solvers):03d}.json',failed,exclusive=True)
            raise
        ledger.finish(sid,'success',{'solver_status':r['solver_status'],'wall_seconds':r['wall_seconds']})
        r.update(solver_call_id=sid,decision=decision)
        solvers.append(r);write_json(out/f'solver_{len(solvers):03d}.json',r,exclusive=True);return r

    try:
        env=SmtEnvironment(seed=scenario,window_seconds=cfg['window_seconds'],
            controlled_machine_ids=cfg['controlled_machine_ids'],max_decisions=cfg['max_decisions'],trace_path=out/'trace.jsonl')
        write_json(out/'input_manifest.json',env.manifest,exclusive=True)
        result['data_sha256']=object_digest(env.manifest['data_hashes'])
        result.update(adapter_version=env.manifest['version'],window_seconds=env.manifest['horizon'],
                      controlled_machine_ids=env.manifest['controlled_machine_ids'],
                      warmup_seconds=env.manifest['warmup_seconds'],outside_policy=env.manifest['outside_policy'],
                      auxiliary=arm=='F')
        for key in ('adapter_version','window_seconds','controlled_machine_ids','warmup_seconds','outside_policy'):
            expected=sorted(cfg[key]) if key=='controlled_machine_ids' and key in cfg else cfg.get(key)
            if key in cfg and expected!=result[key]:raise ValueError('Environment/config mismatch: '+key)
        if frozen:
            actual={str((env.data_dir/name).relative_to(ROOT)):sha for name,sha in env.manifest['data_hashes'].items()}
            if actual!=frozen['source_data']:raise ValueError('Full factory source data differs from freeze')
        write_json(out/'started.json',{k:v for k,v in result.items() if k not in ('status','failure_type')},exclusive=True)
        state=env.advance();decision=0
        while not state['finished']:
            if time.monotonic()>deadline:raise TimeoutError('run_wall_deadline')
            if decision>=cfg['max_decisions']:raise RuntimeError('decision_budget_exhausted')
            decision_started=now();decision_begun=time.monotonic()
            model_count_before=len(models);solver_count_before=len(solvers)
            write_json(out/f'state_{decision:03d}.json',state,exclusive=True)
            if arm in ('A','F'):
                params={**cfg['classical_parameters' if arm=='A' else 'fixed_auxiliary_parameters'],'seed':cfg['seed']}
                chosen=optimize(state,params,decision)['action']
            elif arm=='B':
                feedback=[];chosen=None
                for attempt in range(cfg['responses_per_decision']['B']):
                    output=invoke(B_PROMPT+'\nCurrent state:\n'+json.dumps(state,separators=(',',':'))+'\nPrior rejected actions at this state:\n'+json.dumps(feedback),ACTION_SCHEMA,decision,attempt)
                    action={'dispatches':output['dispatches'],'wait_seconds':output['wait_seconds']}
                    try:
                        # Validate against independent current state before mutation; env remains authoritative executor.
                        check_action(state,action)
                        chosen=action;break
                    except ValueError as exc:
                        feedback.append({'decision':output,'error':str(exc)});failures.append({'state':decision,**feedback[-1]})
                if chosen is None:raise RuntimeError('direct_action_revisions_exhausted')
            elif arm=='C':
                history=[];candidates=[];chosen=None
                for attempt in range(cfg['responses_per_decision']['C']):
                    limits={'responses_including_this':cfg['responses_per_decision']['C']-attempt,
                            'solver_seconds':cfg['solver_budget_seconds']-sum(s['parameters']['time_limit'] for s in solvers)}
                    output=invoke(C_PROMPT+'\nCurrent state:\n'+json.dumps(state,separators=(',',':'))+'\nThis state history:\n'+json.dumps(history)+'\nRemaining:\n'+json.dumps(limits),C_SCHEMA,decision,attempt)
                    try:
                        if output['action']=='apply':
                            k=output['candidate_index']
                            if type(k) is not int or not 0<=k<len(candidates):raise ValueError('invalid candidate index')
                            if any(output[x] is not None for x in ['time_limit','seed',*WEIGHTS]):raise ValueError('apply requires null solve fields')
                            chosen=candidates[k]['action'];break
                        if output['action']!='solve' or output['candidate_index'] is not None:raise ValueError('invalid solve action')
                        params={k:output[k] for k in ['time_limit','seed',*WEIGHTS]}
                        candidate=optimize(state,params,decision);check_action(state,candidate['action']);candidates.append(candidate)
                        history.append({'decision':output,'candidate_index':len(candidates)-1,'result':candidate})
                    except BudgetExceeded:
                        raise
                    except (ValueError,RuntimeError) as exc:
                        history.append({'decision':output,'error':str(exc)});failures.append({'state':decision,**history[-1]})
                if chosen is None:raise RuntimeError('missing_explicit_candidate_apply')
            else:raise ValueError('Unknown arm')
            write_json(out/f'action_{decision:03d}.json',chosen,exclusive=True)
            actions.append({'decision':decision,'time':state['time'],'action':chosen,
                'decision_started_at':decision_started,'decision_elapsed_seconds':time.monotonic()-decision_begun,
                'model_calls':len(models)-model_count_before,'solver_calls':len(solvers)-solver_count_before})
            state=env.apply(chosen);decision+=1
        metrics=env.finish()
        audited=audit_trace(out/'trace.jsonl',verify_data_dir=env.data_dir)
        write_json(out/'audit.json',audited,exclusive=True)
        result.update(status='success' if audited['valid'] else 'failed',
            failure_type=None if audited['valid'] else 'event_audit_failed',
            validation=audited,metrics={**metrics,**audited['metrics']})
    except Exception as exc:
        result.update(status='timeout' if isinstance(exc,TimeoutError) else 'failed',
                      failure_type=str(exc),metrics=env.metrics() if env else None,
                      validation={'valid':False,'errors':['Full window and independent audit not completed']})
        (out/'exception.txt').write_text(traceback.format_exc())
    usage={k:sum(m['usage'][k] for m in models) if all(m.get('usage',{}).get(k) is not None for m in models) else None
           for k in ['input_tokens','output_tokens','cached_input_tokens','cache_write_input_tokens','reasoning_output_tokens']}
    result.update(actions=actions,model_results=models,solver_results=solvers,rejected_actions=failures,
        finished_at=now(),costs={'end_to_end_seconds':time.monotonic()-begun,'model_calls':len(models),
            'model_elapsed_seconds':sum(m['duration_seconds'] for m in models),'usage':usage,'cost_usd':None,
            'solver_calls':len(solvers),'solver_wall_seconds':sum(s['wall_seconds'] for s in solvers),
            'solver_budget_seconds':sum(s['parameters']['time_limit'] for s in solvers)})
    write_json(out/'result.json',result,exclusive=True)
    print('DONE',run_id,result['status'],len(actions),'decisions',flush=True)
    return result


def check_action(state,action):
    if type(action.get('wait_seconds')) not in (float,int) or not 0<=action['wait_seconds']<=1800:
        raise ValueError('wait_seconds must be 0..1800')
    ds=action.get('dispatches')
    if not isinstance(ds,list) or not ds and action['wait_seconds']<=0:raise ValueError('empty action without waiting')
    mids=set();lots=set();machines={m['machine']:m for m in state['machines']}
    for d in ds:
        mid=d['machine'];ids=d['lot_ids']
        if type(mid) is not int or mid in mids or mid not in machines:raise ValueError('unknown/duplicate machine')
        if not machines[mid]['ready_now']:raise ValueError('machine not ready')
        candidates={c['lot']:c for c in machines[mid]['candidates']}
        if not ids or any(i not in candidates or i in lots for i in ids) or len(ids)!=len(set(ids)):raise ValueError('unknown/duplicate lot')
        first=candidates[ids[0]]
        if any(candidates[i]['batch_key']!=first['batch_key'] for i in ids):raise ValueError('incompatible batch')
        if not first['batch_min']<=len(ids)<=first['batch_max']:raise ValueError('batch min/max')
        mids.add(mid);lots.update(ids)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--arm',choices=['A','B','C','F'],required=True)
    ap.add_argument('--run-id',required=True);ap.add_argument('--config',type=Path,default=ROOT/'configs/smt-development.json')
    ap.add_argument('--phase',default='development');ap.add_argument('--scenario',type=int,default=701)
    ap.add_argument('--repeat',type=int,choices=[1,2,3],default=1);ap.add_argument('--freeze')
    a=ap.parse_args();r=run(a.arm,a.run_id,a.config,phase=a.phase,scenario=a.scenario,repeat=a.repeat,freeze=a.freeze)
    raise SystemExit(0 if r['status']=='success' else 1)
