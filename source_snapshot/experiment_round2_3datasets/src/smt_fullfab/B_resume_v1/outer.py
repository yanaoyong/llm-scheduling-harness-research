"""One explicit frozen recovery process; no model retries or implicit restarts."""
import time
BEGUN=time.monotonic()
import argparse
import json
import os
from pathlib import Path
import sys
import traceback


def main(campaign,expected):
    campaign=Path(campaign).resolve();frozen=campaign/'frozen';sys.path.insert(0,str(frozen))
    from src.smt_fullfab.B_resume_v1.host import bound,sha,new
    assert Path(__file__).resolve().is_relative_to(frozen)
    digest,ident,raw=bound(campaign/'manifest.json',keep=True);assert digest==expected
    m=json.loads(raw);assert sha(__file__)==m['runtime_files']['src/smt_fullfab/B_resume_v1/outer.py']
    from src.smt_fullfab.model_process_guard import run_guarded
    assert sha(frozen/'src/smt_fullfab/model_process_guard.py')==m['runtime_files']['src/smt_fullfab/model_process_guard.py']
    root=Path(m['root']);segment=root/m['segment'];guard=campaign/'outer';guard.mkdir()
    command=[m['python'],'-B',str(frozen/'src/smt_fullfab/B_resume_v1/host.py'),'--campaign',str(campaign),'--manifest-sha256',expected]
    available=float(m['package_static']['remaining_wall_seconds'])-m['prepare_wall_seconds']-(time.monotonic()-BEGUN)-30
    assert available>=1,'No inherited recovery time remains before launch'
    req={'schema':'smt-B-v7-recovery-outer-request-v1','command':command,'manifest_sha256':expected,
         'first_outer_monotonic':BEGUN,'timeout_seconds':available,
         'automatic_retry':False,'parent_status':'failed'}
    fp=new(guard/'request.json',req)
    io={'cwd':str(frozen),'stdin':None,'stdout':str(guard/'stdout.log'),'stderr':str(guard/'stderr.log'),
        'inputs':{'request':str(guard/'request.json'),'manifest':str(campaign/'manifest.json'),'host':command[2]},
        'outputs':{'stdout':str(guard/'stdout.log'),'stderr':str(guard/'stderr.log'),'host_result':str(campaign/'host_result.json')}}
    result={'schema':'smt-B-v7-recovery-outer-result-v1','accepted':False,'status':'failed','manifest_sha256':expected,
            'cost_usd':None,'parent_status':'failed','formal':False,'automatic_retry':False,'errors':[]}
    try:
        result['guard']=run_guarded(command,run_dir=guard,timeout_seconds=req['timeout_seconds'],env=os.environ.copy(),
            call_id=m['segment'].split('/')[-1]+':outer',request_fingerprint=fp,io_spec=io)
        host_sha,host_identity,host_raw=bound(campaign/'host_result.json',keep=True)
        assert host_sha==result['guard']['output_files_sha256']['host_result']
        host=json.loads(host_raw);result['host_result_sha256']=host_sha
        assert result['guard']['lifecycle_complete'] and result['guard']['command_returncode']==0 and not result['guard']['timed_out']
        assert host['status']=='completed_pending_outer_resource_check' and host['accepted'] is False
        assert bound(campaign/'host_result.json')[:2]==(host_sha,host_identity)
        result['status']='completed_pending_root_actual_wait'
    except BaseException as exc:
        result['errors'].append({'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
    result['elapsed_outer_seconds_before_encoding']=time.monotonic()-BEGUN
    result['prepare_wall_seconds']=m['prepare_wall_seconds']
    result['bytes_before_result']=sum(p.stat().st_size for base in (campaign,segment) if base.exists() for p in base.rglob('*') if p.is_file())
    if result['elapsed_outer_seconds_before_encoding']+m['prepare_wall_seconds']>=float(m['package_static']['remaining_wall_seconds']) or result['bytes_before_result']>=m['package_static']['remaining_log_bytes']:
        result['status']='failed';result['errors'].append({'type':'resource_limit','message':'inherited complete segment resource exceeded'})
    new(campaign/'outer_result.json',result)
    print(json.dumps({'status':result['status'],'accepted':False,'outer_result_sha256':sha(campaign/'outer_result.json')}),flush=True)
    return 0 if result['status']=='completed_pending_root_actual_wait' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--manifest-sha256',required=True)
    a=p.parse_args();raise SystemExit(main(a.campaign,a.manifest_sha256))
