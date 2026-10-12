"""Serial frozen batch admission and resumable progress; no run is overwritten."""
from __future__ import annotations
import argparse
import fcntl
from src.experiment import ROOT,now,verify_freeze,write_json,read_json
from src.runner import run_static


def batch(name):
    frozen=verify_freeze(name)
    phase=frozen['phase']
    log=ROOT/'progress'/f'{phase}-batch.json'
    with (ROOT/'progress/formal_execution.lock').open('a') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        records=[]
        for instance,arm,repeat in frozen['matrix']:
            smt=frozen.get('dataset')=='smt2020'
            run_id=f'smt{instance}_{arm}_r{repeat}' if smt else f'{instance}_{arm}_r{repeat}'
            elapsed=sum(read_json(p).get('costs',{}).get('end_to_end_seconds',0)
                        for folder in ROOT.joinpath('runs').glob('*') if folder.name!='development'
                        for p in folder.glob('*/result.json'))
            if elapsed>=14400 and not (ROOT/'runs'/phase/run_id/'result.json').exists():
                write_json(log,{'phase':phase,'at':now(),'stopped_reason':'formal_campaign_14400_seconds_budget',
                                'observed_execution_seconds':elapsed,'records':records})
                return 2
            write_json(log,{'phase':phase,'at':now(),'freeze':name,'active':run_id,'completed_this_invocation':records})
            if smt:
                from src.smt_control import run
                result=run(arm,run_id,ROOT/frozen['config_path'],phase=phase,scenario=instance,repeat=repeat,freeze=name)
            else:
                result=run_static(instance,arm,run_id,ROOT/frozen['config_path'],phase=phase,repeat=repeat,freeze=name)
            records.append({'run_id':run_id,'status':result['status'],'failure_type':result.get('failure_type')})
            failure=str(result.get('failure_type',''))+' '+str(result.get('reason',''))
            if any(term in failure.lower() for term in ('budget','quota','rate_limit','login','unauthorized')):
                write_json(log,{'phase':phase,'at':now(),'freeze':name,'active':None,'stopped_reason':failure,'records':records})
                return 2
        write_json(log,{'phase':phase,'at':now(),'freeze':name,'active':None,'completed':True,'records':records})
    return 0


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--freeze',required=True);args=ap.parse_args()
    raise SystemExit(batch(args.freeze))
