"""Freeze and serially execute the preregistered ten offline reference pilots.

Preparation is the default. Execution requires --execute. No model/solver API is
imported; each child runs only reference_cr/reference_fifo from one frozen source.
Git HEAD is an immutable origin pointer, while file hashes are authoritative.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
PREREG='configs/smt_fullfab/offline_development_next_v1.json'
DATA='data/smt/SMT2020_LVHM'
VENDOR='vendor/PySCFabSim-revised/simulation'
SCHEMA='smt-fullfab-offline-pilot-frozen-1'


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _read(path):return json.loads(Path(path).read_text())


def _write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,separators=(',',':'));stream.write('\n')


def _runtime():
    executable=Path(sys.executable).resolve()
    return {'python_version':sys.version,'executable':str(executable),'executable_sha256':_sha(executable),
            'distributions':sorted([d.metadata['Name'],d.version] for d in importlib.metadata.distributions() if d.metadata['Name'])}


def _input_paths(root):
    paths=[]
    for relative in ('src',VENDOR,DATA):
        base=root/relative
        if not base.is_dir():raise ValueError('missing frozen input directory: '+relative)
        for path in sorted(base.rglob('*')):
            if '__pycache__' in path.parts or path.suffix in ('.pyc','.pyo'):continue
            if path.is_symlink():raise ValueError('input symbolic links are not supported: '+str(path))
            if path.is_file():paths.append(path)
    paths.extend(sorted(root.glob('requirements*')));paths.append(root/PREREG)
    if root/'requirements.lock' not in paths:raise ValueError('requirements.lock is required')
    for path in paths:
        if path.is_symlink() or not path.is_file():raise ValueError('input must be a regular file: '+str(path))
    return sorted(set(paths))


def _inventory(root):return {str(p.relative_to(root)):_sha(p) for p in _input_paths(root)}


def _configs(prereg):
    cfg=prereg['reference_discrimination_8h']
    if prereg.get('schema')!='smt-fullfab-offline-development-preregistration-1' or prereg.get('formal') is not False:
        raise ValueError('unexpected offline preregistration identity')
    expected={'seeds':[1702,1703,1704,1705,1706],'policies':['cr','fifo'],'seconds':28800,
              'wall_seconds_per_run':180,'max_plans_per_run':20000,'max_log_bytes_per_run':536870912}
    if any(type(cfg.get(k)) is not type(v) or cfg[k]!=v for k,v in expected.items()):
        raise ValueError('preregistered reference matrix/resources differ')
    return [{'arm':'reference_'+policy,'run_id':f'ref_{policy}_{seed}_8h_discrimination_v1',
             'seconds':cfg['seconds'],'seed':seed,'wall_seconds':float(cfg['wall_seconds_per_run']),
             'max_plans':cfg['max_plans_per_run'],'plan_seconds':14400,'period_seconds':1800,
             'lookahead_depth':2,'solver_seconds':5.0,'solver_budget_seconds':60.0,'max_slots':2,
             'snapshot_path':None,'solver_method':'global','max_log_bytes':cfg['max_log_bytes_per_run'],
             'constructor_seconds':5.0,'max_candidate_evaluations':250000}
            for seed in cfg['seeds'] for policy in cfg['policies']]


def _origin_git(root):
    # Metadata only: never writes or creates a Git commit.
    return subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()


def _git_pointer(frozen,head):
    git=frozen/'.git';(git/'objects').mkdir(parents=True);(git/'refs').mkdir()
    (git/'HEAD').write_text(head+'\n')
    (git/'config').write_text('[core]\nrepositoryformatversion = 0\nbare = false\n')
    if _origin_git(frozen)!=head:raise ValueError('frozen origin pointer cannot be read')


def prepare(*,root=ROOT,campaign_id='reference_discrimination_8h_v1'):
    root=Path(root).resolve()
    if not campaign_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in campaign_id):
        raise ValueError('invalid campaign identifier')
    campaign=root/'runs/smt_fullfab_offline_pilot'/campaign_id
    if campaign.exists():
        manifest=_read(campaign/'manifest.json');verify_frozen(campaign,manifest)
        if manifest['preregistration_sha256']!=_sha(root/PREREG):raise ValueError('live preregistration changed')
        return campaign,manifest
    configs=_configs(_read(root/PREREG));head=_origin_git(root)
    inputs=_inventory(root);runtime=_runtime()
    campaign.mkdir(parents=True,exist_ok=False);frozen=campaign/'frozen';frozen.mkdir()
    try:
        for relative,expected in inputs.items():
            source=root/relative;payload=source.read_bytes()
            if hashlib.sha256(payload).hexdigest()!=expected:raise ValueError('input changed during freeze: '+relative)
            target=frozen/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
            target.chmod(0o444)
        if inputs!=_inventory(root):raise ValueError('source/data inventory changed during freeze')
        if runtime!=_runtime():raise ValueError('Python dependency environment changed during freeze')
        (root/'runs').mkdir(exist_ok=True)
        (frozen/'runs').symlink_to(root/'runs',target_is_directory=True)
        _git_pointer(frozen,head)
        manifest={'schema':SCHEMA,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'campaign_id':campaign_id,'origin_root':str(root),'origin_git_head':head,
            'git_identity_note':'origin pointer only; no commit created; source/data hashes below are authoritative, including dirty source',
            'frozen_input_sha256':inputs,'preregistration_sha256':inputs[PREREG],
            'runtime':runtime,'configs':configs,'output_root':str(root/'runs/smt_fullfab_development'),
            'outer_wall_seconds_per_run':180,'model_calls_permitted':0,'solver_calls_permitted':0,
            'source_freeze_scope':'all src non-cache files, requirements*, vendor simulation, normalized SMT dataset, preregistration'}
        manifest['identity']=_digest(manifest)
        _write(campaign/'manifest.json',manifest)
        verify_frozen(campaign,manifest)
        return campaign,manifest
    except Exception as exc:
        _write(campaign/'freeze_failure.json',{'status':'failed','error':str(exc)})
        raise


def verify_frozen(campaign,manifest):
    if manifest.get('schema')!=SCHEMA or manifest.get('identity')!=_digest({k:v for k,v in manifest.items() if k!='identity'}):
        raise ValueError('invalid frozen campaign manifest')
    frozen=Path(campaign)/'frozen'
    if _inventory(frozen)!=manifest['frozen_input_sha256']:raise ValueError('frozen source/data changed')
    if _configs(_read(frozen/PREREG))!=manifest['configs']:raise ValueError('frozen matrix changed')
    if _runtime()!=manifest['runtime']:raise ValueError('Python dependency environment differs from freeze')
    if _origin_git(frozen)!=manifest['origin_git_head']:raise ValueError('origin Git pointer changed')
    if not (frozen/'runs').is_symlink() or (frozen/'runs').resolve()!=Path(manifest['origin_root'])/'runs':
        raise ValueError('output mapping changed')
    # Other working-tree modules may evolve. This orchestrator itself must match.
    own=manifest['frozen_input_sha256'].get('src/smt_fullfab/offline_pilot.py')
    if own is not None and _sha(__file__)!=own:raise ValueError('use the frozen offline_pilot entry point; live orchestrator differs')


def _command(frozen,config):
    if config['arm'] not in ('reference_cr','reference_fifo'):raise ValueError('only offline references are permitted')
    bootstrap="import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('src.smt_fullfab.runner',run_name='__main__')"
    command=[sys.executable,'-I','-B','-c',bootstrap,str(frozen)]
    for key,value in config.items():
        if value is not None:command.extend(['--'+key.replace('_','-'),str(value)])
    return command


def _active_claims(root):
    active=[]
    for area in ('smt_fullfab_development','smt_fullfab_stage2'):
        for claim in (root/'runs'/area).glob('*/claim.json'):
            if claim.with_name('result.json').exists():continue
            try:
                pid=_read(claim)['pid']
                if type(pid)is not int or pid<=0:raise ValueError('invalid claim pid')
                os.kill(pid,0)
            except ProcessLookupError:continue
            except (OSError,ValueError,KeyError,json.JSONDecodeError):
                active.append({'claim':str(claim),'reason':'claim cannot be safely classified'})
            else:active.append({'claim':str(claim),'pid':pid})
    return active


@contextmanager
def _serial_lock(root):
    path=root/'progress/smt_fullfab/offline_pilot.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise RuntimeError('another offline pilot launcher holds the serial lock') from exc
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def _validate_result(run_dir,config,manifest):
    result=_read(run_dir/'result.json');saved=_read(run_dir/'config.json');provenance=_read(run_dir/'provenance.json')
    if saved!=config or result.get('config')!=config or result.get('identity')!=_digest(config):
        raise ValueError('existing/result configuration does not match frozen matrix')
    expected={k:v for k,v in manifest['frozen_input_sha256'].items()
              if Path(k).parent.as_posix() in ('src/smt','src/smt_fullfab') and k.endswith('.py')}
    if provenance.get('source_sha256')!=expected or result.get('provenance')!=provenance:
        raise ValueError('run source provenance does not match frozen implementation')
    if provenance.get('requirements_sha256')!=manifest['frozen_input_sha256']['requirements.lock'] or provenance.get('git_commit')!=manifest['origin_git_head']:
        raise ValueError('requirements/origin provenance mismatch')
    for relative,sha in {**expected,'src/__init__.py':manifest['frozen_input_sha256']['src/__init__.py']}.items():
        if _sha(run_dir/'source_snapshot'/relative)!=sha:raise ValueError('saved run source snapshot differs: '+relative)
    if result.get('model_calls')!=0 or result.get('solver_calls')!=0:
        raise ValueError('offline reference unexpectedly reports model/solver calls')
    if result.get('status')=='success':
        audit=_read(run_dir/'audit.json')
        if not (result.get('audit_valid') is True and audit.get('valid') is True and result.get('full_window_completed') is True
                and result.get('simulation_seconds')==config['seconds']):raise ValueError('success lacks completed audited window')
        with (run_dir/'trace.jsonl').open('rb') as stream:initial=json.loads(next(stream))
        data_hashes={Path(k).name:v for k,v in manifest['frozen_input_sha256'].items() if k.startswith(DATA+'/')}
        if initial.get('kind')!='initial' or initial.get('manifest',{}).get('data_hashes')!=data_hashes:
            raise ValueError('run trace data identity differs from frozen dataset')
    return result


def _result_evidence(run_dir):
    names=('result.json','config.json','provenance.json','audit.json','trace.jsonl','checkpoint.json','checkpoint_resources.json')
    return {name:_sha(run_dir/name) for name in names if (run_dir/name).exists()}


def _launch(command,frozen,attempt_dir,timeout):
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE')}
    env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull)
    started=time.monotonic()
    with (attempt_dir/'stdout.log').open('xb') as stdout,(attempt_dir/'stderr.log').open('xb') as stderr:
        process=subprocess.Popen(command,cwd=frozen,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        try:code=process.wait(timeout=timeout);timed_out=False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);code=process.wait();timed_out=True
    return {'returncode':code,'timed_out':timed_out,'wall_seconds':time.monotonic()-started,'pid':process.pid}


def execute(campaign,manifest):
    campaign=Path(campaign);root=Path(manifest['origin_root']);frozen=campaign/'frozen';records=[]
    with _serial_lock(root):
        for index,config in enumerate(manifest['configs']):
            verify_frozen(campaign,manifest)
            remaining=[c['run_id'] for c in manifest['configs'][index:]]
            run_dir=Path(manifest['output_root'])/config['run_id'];attempt=campaign/'records'/f'{index:02d}'
            if (attempt/'outcome.json').exists():
                previous=_read(attempt/'outcome.json')
                if previous['status']!='success':
                    return {'status':'stopped_prior_failure','records':records+[previous],'not_run':remaining[1:]}
            active=_active_claims(root)
            if active:return {'status':'blocked_active_runs','active_claims':active,'records':records,'not_run':remaining}
            outcome={'run_id':config['run_id'],'matrix_index':index,'campaign_identity':manifest['identity'],
                     'source_inventory_sha256':_digest(manifest['frozen_input_sha256']),'run_dir':str(run_dir)}
            try:
                if run_dir.exists():
                    if not (run_dir/'result.json').exists():raise ValueError('existing incomplete run retained; no automatic retry')
                    result=_validate_result(run_dir,config,manifest);mode='SKIP'
                else:
                    if (attempt/'attempt.json').exists():raise ValueError('interrupted attempt retained; no automatic retry')
                    attempt.mkdir(parents=True,exist_ok=True);command=_command(frozen,config)
                    _write(attempt/'attempt.json',{**outcome,'command':command,'timeout_seconds':180,'config':config})
                    child=_launch(command,frozen,attempt,180)
                    outcome['process']=child
                    verify_frozen(campaign,manifest)
                    if child['timed_out']:raise TimeoutError('outer 180-second deadline; runner result/audit may be incomplete')
                    result=_validate_result(run_dir,config,manifest);mode='executed'
                    if child['returncode']!=0 and result['status']=='success':raise ValueError('child failed despite success result')
                outcome.update(status=result['status'],mode=mode,runner_result_sha256=_sha(run_dir/'result.json'),
                               runner_failure=result.get('failure'),audit_valid=result.get('audit_valid'),
                               full_window_completed=result.get('full_window_completed'),evidence_sha256=_result_evidence(run_dir))
                log_bytes=sum(p.stat().st_size for p in run_dir.rglob('*') if p.is_file())
                outcome['run_directory_bytes']=log_bytes
                if log_bytes>config['max_log_bytes']:raise ValueError('final run output exceeds registered log cap')
            except Exception as exc:
                outcome.update(status='failed',failure=f'{type(exc).__name__}: {exc}',audit_valid=False,
                               runner_result_present=(run_dir/'result.json').exists())
            if not (attempt/'outcome.json').exists():_write(attempt/'outcome.json',outcome)
            else:
                previous=_read(attempt/'outcome.json')
                if (outcome['status']!='success' or previous.get('runner_result_sha256')!=outcome.get('runner_result_sha256')
                        or previous.get('evidence_sha256')!=outcome.get('evidence_sha256')):
                    return {'status':'stopped_evidence_mismatch','records':records+[outcome],'not_run':remaining[1:]}
            records.append(outcome)
            if outcome['status']!='success':return {'status':'stopped_failure','records':records,'not_run':remaining[1:]}
    return {'status':'complete','records':records,'not_run':[],'formal':False,'warmup':False,'official_calibrated':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-id',default='reference_discrimination_8h_v1')
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--execute',action='store_true',help='Run frozen reference children serially; default only prepares/reviews')
    args=parser.parse_args();campaign,manifest=prepare(root=args.root,campaign_id=args.campaign_id)
    result=execute(campaign,manifest) if args.execute else {'status':'prepared','campaign':str(campaign),'identity':manifest['identity'],
        'configs':manifest['configs'],'execution_requires':'--execute','source_inventory_sha256':_digest(manifest['frozen_input_sha256'])}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.execute:
        _write(campaign/('invocation_'+str(time.time_ns())+'.json'),result)
        if result['status']!='complete':raise SystemExit(1)


if __name__=='__main__':main()
