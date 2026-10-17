"""Serial, bounded static experiment driver. Invocation: python -m src.runner."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import traceback
import shutil
import os
import socket

from src.experiment import ROOT, now, read_json, write_json, provenance, verify_freeze, object_digest, digest
from src.fjsp.validator import validate
from src.fjsp.solver import solve
from src.agents.budget import BudgetLedger


def run_static(instance_id, arm, run_id, config_path, *, phase='development', repeat=1, freeze=None):
    start = time.monotonic()
    started_at = now()
    if not run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in run_id):
        raise ValueError('Unsafe run identifier')
    problem = read_json(ROOT / 'data/fjsp/instances' / (instance_id + '.json'))
    config = read_json(config_path)
    config['model']['phase'] = 'development' if phase == 'development' else 'formal'
    config['seed'] = [11, 22, 33][repeat-1]
    out = ROOT / 'runs' / phase / run_id
    identity = {'instance_id': instance_id, 'arm': arm, 'repeat': repeat,
                'config_sha256': object_digest(config), 'data_sha256': object_digest(problem)}
    if phase != 'development':
        if not freeze:
            raise ValueError('Formal runs require a verified frozen version')
        frozen = verify_freeze(freeze)
        key = [instance_id, arm, repeat]
        if key not in frozen['matrix'] or run_id != f'{instance_id}_{arm}_r{repeat}':
            raise ValueError('Formal identity is outside frozen matrix')
        if config['protocol_version'] != frozen['protocol_version']:
            raise ValueError('Protocol mismatch')
        if str(Path(config_path).resolve().relative_to(ROOT)) != frozen['config_path']:
            raise ValueError('Configuration path is not frozen for this batch')
        if identity['config_sha256'] != frozen['effective_config_sha256'][str(repeat)]:
            raise ValueError('Effective configuration does not match the freeze')
    if out.exists():
        if not (out/'result.json').exists():
            raise RuntimeError(f'Interrupted run preserved; diagnose without replacing: {out}')
        old = read_json(out/'result.json')
        if old['identity'] != identity:
            raise ValueError('Existing run identity/config/data mismatch')
        print('SKIP', run_id, old['status'], flush=True)
        return old
    out.mkdir(parents=True)
    version = provenance(problem, config, config['protocol_version'],domain='fjsp')
    if phase != 'development':
        version['code_commit'] = frozen['code_commit']
        version['freeze_tag'] = frozen['tag']
        write_json(out/'freeze.json',frozen,exclusive=True)
        version['freeze_manifest_sha256']=digest(out/'freeze.json')
    write_json(out/'started.json', {'identity': identity, **version, 'started_at': started_at,
                                  'process_id':os.getpid(),'hostname':socket.gethostname()}, exclusive=True)
    write_json(out/'input.json', problem, exclusive=True)
    write_json(out/'config.json', config, exclusive=True)
    for relative in version['source_sha256']:
        target=out/'source_snapshot'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    ledger = BudgetLedger()
    try:
        if arm == 'F':
            candidates=[]
            per_call=config['solver_budget_seconds']/3
            for offset,search in enumerate(('AUTOMATIC_SEARCH','FIXED_SEARCH','PORTFOLIO_SEARCH')):
                sid=ledger.reserve_solver(phase=config['model']['phase'],run_id=str(out),
                    grant_id=config['solver_grant_id'],requested_seconds=per_call,
                    metadata={'auxiliary':'fixed-three-searches','search':search})
                try:
                    r=solve(problem,time_limit=per_call,seed=config['seed']+offset,workers=1,
                            search_branching=search,randomize_search=False)
                    v=validate(problem,r['schedule'])
                    ledger.finish(sid,'success' if v['valid'] else 'failed',
                        {'solver_seconds':r['solver_seconds'],'status':r['solver_status'],'validation':v})
                except Exception as exc:
                    ledger.finish(sid,'failed',{'error':str(exc)});raise
                candidates.append({'result':r,'validation':v})
            write_json(out/'fixed_portfolio.json',candidates,exclusive=True)
            feasible=[(c['validation']['makespan'],k) for k,c in enumerate(candidates) if c['validation']['valid']]
            k=min(feasible)[1] if feasible else None
            schedule=candidates[k]['result']['schedule'] if k is not None else None
            validation=validate(problem,schedule)
            record={'status':'success' if feasible else 'failed','auxiliary':True,
                'failure_type':None if feasible else 'no_feasible_fixed_portfolio_candidate',
                'schedule':schedule,'validation':validation,'selected_candidate':k,
                'metrics':{'makespan':validation['makespan'],'first_output_valid':candidates[0]['validation']['valid'],'revisions':0},
                'costs':{'model_calls':0,'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,
                         'model_seconds':0,'solver_seconds':sum(c['result']['solver_seconds'] for c in candidates),
                         'solver_wall_seconds':sum(c['result']['wall_seconds'] for c in candidates),
                         'solver_budget_seconds':config['solver_budget_seconds'],'cost_usd':None}}
        elif arm == 'A':
            request_id = ledger.reserve_solver(phase=config['model']['phase'],run_id=str(out),
                grant_id=config['solver_grant_id'],requested_seconds=config['solver_budget_seconds'])
            try:
                solved = solve(problem, time_limit=config['solver_budget_seconds'],seed=config['seed'],workers=1,
                    search_branching=config.get('search_branching_by_family',{}).get(problem['family'],config.get('search_branching','AUTOMATIC_SEARCH')),
                    randomize_search=config.get('randomize_search',False))
            except Exception as exc:
                ledger.finish(request_id,'failed',{'error':str(exc)})
                raise
            write_json(out/'solver.json',solved,exclusive=True)
            validation=validate(problem,solved['schedule'])
            ledger.finish(request_id,'success' if validation['valid'] else 'failed',
                          {'solver_seconds':solved['solver_seconds'],'status':solved['solver_status'],
                           'validation':validation})
            record={'status':'success' if validation['valid'] else 'failed',
                'failure_type':None if validation['valid'] else 'schedule_infeasible',
                'schedule':solved['schedule'],'validation':validation,
                'metrics':{'makespan':validation['makespan'],'solver_status':solved['solver_status'],
                           'best_bound':solved['best_bound'],'first_output_valid':validation['valid'],'revisions':0},
                'costs':{'model_calls':0,'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,
                    'model_seconds':0,'solver_seconds':solved['solver_seconds'],
                    'solver_wall_seconds':solved['wall_seconds'],
                    'solver_budget_seconds':config['solver_budget_seconds'],'cost_usd':None}}
        elif arm in ('B','C'):
            from src.agents.static import run_b, run_c
            record=(run_b if arm=='B' else run_c)(problem,out/'agent',config)
        else:
            raise ValueError('Unknown arm')
    except Exception as exc:
        (out/'exception.txt').write_text(traceback.format_exc())
        record={'status':'failed','failure_type':type(exc).__name__,'reason':str(exc),
                'schedule':None,'validation':{'valid':False,'errors':[str(exc)],'makespan':None},
                'metrics':{'makespan':None},'costs':{'cost_usd':None}}
    # One root-independent check, even when the agent has already validated its candidate.
    independent=validate(problem,record.get('schedule'))
    record['validation']=independent
    if not independent['valid']:
        if record['status'] == 'success':
            record['status']='failed'
            record['failure_type']='independent_validation_failed'
        record['metrics']['makespan']=None
    else:
        record['metrics']['makespan']=independent['makespan']
    record.update({'run_id':run_id,'identity':identity,'instance_id':instance_id,
                   'family':problem['family'],'variant':problem.get('variant'),
                   'base_instance':problem.get('base_instance'),'arm':arm,'repeat':repeat,
                   'phase':phase,**version,'started_at':started_at,'finished_at':now(),
                   'fallback':False})
    record['costs']['end_to_end_seconds']=time.monotonic()-start
    if record.get('schedule') is not None:
        write_json(out/'schedule.json',record['schedule'],exclusive=True)
    write_json(out/'result.json',record,exclusive=True)
    print('DONE',run_id,record['status'],record['metrics'].get('makespan'),flush=True)
    return record


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    run=sub.add_parser('run')
    run.add_argument('--instance',required=True)
    run.add_argument('--arm',choices=['A','B','C','F'],required=True)
    run.add_argument('--run-id',required=True)
    run.add_argument('--phase',default='development')
    run.add_argument('--repeat',type=int,choices=[1,2,3],default=1)
    run.add_argument('--config',type=Path,default=ROOT/'configs/development.json')
    run.add_argument('--freeze')
    args=parser.parse_args()
    if args.command=='run':
        r=run_static(args.instance,args.arm,args.run_id,args.config,phase=args.phase,repeat=args.repeat,freeze=args.freeze)
        raise SystemExit(0 if r['status']=='success' else 1)


if __name__=='__main__':
    main()
