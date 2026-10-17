"""Read-only restoration proof using the run's exact archived source tree.

No scheduling, solver or model invocation. Temporary dependency links refer to
the unchanged locked dataset/vendor; fingerprints are checked before loading.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(run_dir, *, timeout_seconds=30.0):
    if (type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds)
            or not 1 <= timeout_seconds <= 180):
        raise ValueError('restoration subprocess timeout must be a finite number from 1 to 180 seconds')
    started=time.monotonic()
    run_dir=Path(run_dir).resolve()
    if not run_dir.is_relative_to(ROOT/'runs'):
        raise ValueError('only local study runs may be restored')
    frozen=run_dir/'source_snapshot'
    provenance=json.loads((run_dir/'provenance.json').read_text())
    checkpoint=run_dir/'checkpoint.json'
    value=json.loads(checkpoint.read_text())
    mismatches=[]
    for name,expected in provenance['source_sha256'].items():
        if not (frozen/name).is_file() or sha(frozen/name)!=expected:
            mismatches.append(name)
    for name,expected in value.get('implementation_sha256',{}).items():
        path=(ROOT if name.startswith('vendor/') else frozen)/name
        if not path.is_file() or sha(path)!=expected:mismatches.append(name)
    if mismatches:
        return {'valid':False,'reason':'frozen source or locked dependency mismatch',
                'mismatches':sorted(set(mismatches)),'checkpoint_sha256':sha(checkpoint)}
    code=r'''
import json,sys
from pathlib import Path
from src.smt_fullfab.environment import FullFabEnvironment,digest
p=Path(sys.argv[1]);v=json.loads(p.read_text())
env=FullFabEnvironment.from_snapshot(p)
env.snapshot(Path('restored.json'))
restored=json.loads(Path('restored.json').read_text())['state']
event=restored['trace'].pop()
if event['kind']!='snapshot_loaded':raise ValueError('restoration did not append its identity')
same=digest(restored)==v['state_sha256']
print(json.dumps({'valid':same,'restored_state_sha256':digest(restored),
    'expected_state_sha256':v['state_sha256'],'simulation_seconds':env.t,
    'horizon_seconds':env.horizon,'production_scope':len(env.physical),
    'jobs':len(env.jobs),'processing_jobs':sum(len(v) for v in env.processing_by_machine.values()),
    'pending_physical_events':len(env.q),'trace_prefix_events':len(restored['trace']),
    'executed_task_identities':len(env.executed_tasks),'model_calls':0,'solver_calls':0,
    'scope':'exact state restoration only; not a scheduling acceptance or fresh continuation'}))
'''
    with tempfile.TemporaryDirectory(prefix='smt_fullfab_restore_') as temp:
        work=Path(temp)
        shutil.copytree(frozen/'src',work/'src')
        for name in ('vendor','data'):(work/name).symlink_to(ROOT/name,target_is_directory=True)
        env={**os.environ,'PYTHONPATH':str(work),'PYTHONDONTWRITEBYTECODE':'1'}
        try:
            completed=subprocess.run([sys.executable,'-c',code,str(checkpoint)],cwd=work,env=env,
                                     capture_output=True,text=True,timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for the child before raising.
            # Keep a failed proof instead of losing the diagnostic at the CLI.
            result={'valid':False,'reason':'restoration subprocess timed out',
                    'timed_out':True,'model_calls':0,'solver_calls':0,
                    'scope':'failed exact-state restoration check; no scheduling or continuation'}
        else:
            if completed.returncode:
                result={'valid':False,'returncode':completed.returncode,'error':completed.stderr[-4000:]}
            else:result=json.loads(completed.stdout)
    result.update(run_path=str(run_dir.relative_to(ROOT)),checkpoint_sha256=sha(checkpoint),
                  frozen_source_files_verified=len(provenance['source_sha256']),
                  complete_snapshot_dependency_binding=bool(value.get('implementation_sha256')),
                  subprocess_timeout_seconds=timeout_seconds,
                  wall_seconds=time.monotonic()-started,cost_usd=None)
    resources=run_dir/'checkpoint_resources.json'
    if resources.exists():
        result['resource_checkpoint']=json.loads(resources.read_text())
        result['resource_checkpoint_sha256']=sha(resources)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir');p.add_argument('--output')
    p.add_argument('--timeout-seconds',type=float,default=30.0)
    a=p.parse_args();result=verify(a.run_dir,timeout_seconds=a.timeout_seconds)
    if a.output:
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['valid'] else 1)
