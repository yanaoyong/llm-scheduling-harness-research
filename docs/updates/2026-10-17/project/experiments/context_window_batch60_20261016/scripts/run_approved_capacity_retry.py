#!/usr/bin/env python3
"""Continue only the user-approved G1 capacity failure; no discarded calls."""
from pathlib import Path
import json,sys,shutil,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.contracts import digest,encode,fingerprint,sha_bytes,strict_json,HarnessError
from src.smt_fullfab.harness.evaluation import Evidence,seal_evidence,audit_provenance,audit_cost,audit_physical_prefix
from src.smt_fullfab.harness.capacity_config import audit_policy
from src.smt_fullfab.harness.transport import call
from src.smt_fullfab.harness import capacity_pilot as pilot
from capacity_retry_support import ANSWER,snapshot_stopped,retry_branch,audit_retry
from run_extended_three_group_pilot import outcome,write
from extended_lineage_audit import verify_inheritance
BASE=ROOT/'live_pilots/extended_three_group_20261017';RUN=ROOT/'live_pilots/extended_three_group_capacity_retry_20261017'

def admission(reg,root=RUN):
 return {'schema':pilot.SCHEMA,'group':'G1','experiment_directory':str(root),'experiment_sha256':digest(reg),
         **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}

def prepare():
 from src.smt_fullfab.harness.offline_isolation import install_guard
 install_guard();RUN.mkdir(exist_ok=False)
 old=strict_json((BASE/'registration.json').read_bytes());reg=dict(old)
 for g in old['groups']:shutil.copyfile(BASE/(g+'.config.json'),RUN/(g+'.config.json'))
 shutil.copyfile(BASE/'model-catalog.json',RUN/'model-catalog.json')
 failure=strict_json((BASE/'G1.capacity_failure_review.json').read_bytes())
 checkpoint=RUN/'stopped_G1_checkpoint';sha=snapshot_stopped(BASE/'G1',checkpoint)
 reg.update(experiment_directory=str(RUN),model_catalog=str(RUN/'model-catalog.json'),
            script_sha256=sha_bytes(Path(__file__).read_bytes()),retry_support_sha256=sha_bytes((ROOT/'scripts/capacity_retry_support.py').read_bytes()),
            retry_checkpoint={'directory':str(checkpoint),'evidence_sha256':sha},
            approved_capacity_retry={'user_answer':ANSWER,'maximum_retries':1,'preserve_unknown_usage':True,
                'attempt_id':failure['attempt_id'],'attempt_sha256':failure['attempt_sha256']},
            execution_order='Continue only G1 after the specifically approved closed capacity refusal; G0/G2 retain their original live run',
            parent_registration_sha256=digest(old),source_unchanged_for_retry=True)
 write(RUN/'registration.json',reg)
 validate()

def validate():
 from src.smt_fullfab.harness.offline_isolation import install_guard
 install_guard()
 reg=strict_json((RUN/'registration.json').read_bytes())
 require_no_live=not (RUN/'G1').exists();assert require_no_live
 saved=RUN/'registration.before_audit_fix.json'
 if not saved.exists():shutil.copyfile(RUN/'registration.json',saved)
 reg.update(script_sha256=sha_bytes(Path(__file__).read_bytes()),
            retry_support_sha256=sha_bytes((ROOT/'scripts/capacity_retry_support.py').read_bytes()),
            lineage_audit_sha256=sha_bytes((ROOT/'scripts/extended_lineage_audit.py').read_bytes()))
 write(RUN/'registration.json',reg)
 # A disposable offline branch exercises the exact admission, lineage and stop
 # checks. It records no request and cannot launch a child process or network.
 with tempfile.TemporaryDirectory(dir=RUN,prefix='offline_check_') as d:
  root=Path(d);test=dict(reg);test['experiment_directory']=str(root)
  write(root/'registration.json',test);rt=retry_branch(root/'G1',test,admission(test,root))
  try:
   before=rt.usage();assert before['actual_model_attempts']==15 and before['unknown_usage']==1
   rt.check_admission(actual=True,reserve=220000+32768)
   assert rt.usage()['actual_model_attempts']==15
   rt.stop('offline_retry_check');seal=seal_evidence(rt)
  finally:rt.close()
  ev=Evidence(root/'G1',seal);trace=[ev.get(r) for r in ev.value['physical']]
  proof=audit_retry(ev);lineage=verify_inheritance(ev);production=audit_provenance(ev,trace);cost=audit_cost(ev)
  assert cost['actual_attempts']==15 and cost['unknown_usage']==1 and not cost['valid']
  assert production['valid'] and production['algorithm_production_tasks']==0
  bad=dict(test);bad['approved_capacity_retry']={**test['approved_capacity_retry'],'maximum_retries':2}
  write(root/'registration.json',bad)
  from capacity_retry_support import validate_grant
  try:validate_grant(ev,bad)
  except HarnessError:pass
  else:raise AssertionError('Unbounded retry was accepted')
 write(RUN/'offline_validation.json',{'all_pass':True,'new_model_calls':0,'admission_checked_without_reserving_call':True,
       'retry_proof':proof,'lineage':lineage,'production':production,'original_failed_call_still_unknown':True})
 print(json.dumps({'prepared':str(RUN),'new_calls':0,'retry_once_only':True,'unknown_usage_preserved':True}),flush=True)

def run():
 reg=strict_json((RUN/'registration.json').read_bytes());assert sha_bytes(Path(__file__).read_bytes())==reg['script_sha256']
 assert fingerprint()['sha256']==reg['fingerprint_sha256']
 assert sha_bytes((ROOT/'scripts/extended_lineage_audit.py').read_bytes())==reg['lineage_audit_sha256']
 rt=retry_branch(RUN/'G1',reg,admission(reg))
 try:
  while rt.usage()['actual_model_attempts']<reg['per_group_call_cap'] and rt.env.t<reg['evaluation_end'] and rt.head['phase'] not in ('STOPPED','CLOSED','AUDITING'):
   n=rt.usage()['actual_model_attempts']+1;print(json.dumps({'event':'call_start','group':'G1','call_number':n,'sim_time':rt.env.t}),flush=True)
   try:
    result=call(rt,task=reg['task']);print(json.dumps({'event':'call_end','call_number':n,'status':result.get('status'),'usage':rt.usage()}),flush=True)
    if rt.head['phase']=='COMMITTED':
     f=rt.advance();print(json.dumps({'event':'advance','from':f['from'],'to':f['to'],'dispatches':f['dispatch_count_delta'],'reason':f['stop_reason']['reason']}),flush=True)
    if rt.env.t>=reg['evaluation_end'] and rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_evaluation_end')
   except Exception as exc:
    write(RUN/'G1.failure.json',{'type':type(exc).__name__,'detail':str(exc)})
    if rt.head['phase'] not in ('STOPPED','CLOSED'):rt.stop('retry_exception:'+type(exc).__name__)
    print(json.dumps({'event':'stopped','error':str(exc)}),flush=True)
   write(RUN/'G1.progress.json',outcome(rt))
  if rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_attempt_cap')
  result=outcome(rt);result['evidence_sha256']=seal_evidence(rt);write(RUN/'G1.result.json',result)
 finally:rt.close()
 ev=Evidence(RUN/'G1',result['evidence_sha256']);trace=[ev.get(r) for r in ev.value['physical']]
 write(RUN/'retry_audit.json',{'retry':audit_retry(ev),'inheritance':verify_inheritance(ev),
       'production':audit_provenance(ev,trace),'cost':audit_cost(ev),
       'physical_prefix':audit_physical_prefix(trace,result['head']['time'],ev.manifest['config']['priority_weights'],
          batching_policy=audit_policy(ev.manifest['config']['capacity_experiment'],702))})
 print(json.dumps({'event':'complete','time':result['head']['time'],'usage':result['usage']}),flush=True)
if __name__=='__main__':{'prepare':prepare,'validate':validate,'run':run}[sys.argv[1]]()
