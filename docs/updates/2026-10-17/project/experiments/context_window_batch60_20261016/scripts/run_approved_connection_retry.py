"""Resume only G1 after the separately approved call-70 connection failure."""
from pathlib import Path
import sys,json,shutil,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.contracts import digest,fingerprint,sha_bytes,strict_json,require,HarnessError
from src.smt_fullfab.harness.evaluation import Evidence,seal_evidence,audit_provenance,audit_cost
from src.smt_fullfab.harness.transport import call
from src.smt_fullfab.harness import capacity_pilot as pilot
from capacity_retry_support import snapshot_stopped,audit_retry
from connection_retry_support import ANSWER,branch,audit,validate_connection_grant
from extended_lineage_audit import verify_inheritance
from run_extended_three_group_pilot import outcome,write,isolation
BASE=ROOT/'live_pilots/extended_three_group_final_segment_20261017'
RUN=ROOT/'live_pilots/extended_three_group_connection_retry_20261017'

def admission(reg,root=RUN):
 return {'schema':pilot.SCHEMA,'group':'G1','experiment_directory':str(root),'experiment_sha256':digest(reg),
         **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}

def prepare():
 from src.smt_fullfab.harness.offline_isolation import install_guard
 install_guard();RUN.mkdir(exist_ok=False)
 reg=strict_json((BASE/'registration.json').read_bytes());failure=strict_json((BASE/'G1.second_failure_review.json').read_bytes())
 for g in reg['groups']:
  shutil.copyfile(BASE/(g+'.config.json'),RUN/(g+'.config.json'));shutil.copyfile(BASE/(g+'.initial_backlog.json'),RUN/(g+'.initial_backlog.json'))
 for name in ('model-catalog.json','outbound_verification.json','already_planned_replan_case.json','zero_time_replan_case.json'):
  shutil.copyfile(BASE/name,RUN/name)
 checkpoint=RUN/'stopped_G1_checkpoint';sha=snapshot_stopped(BASE/'G1',checkpoint)
 reg.update(experiment_directory=str(RUN),model_catalog=str(RUN/'model-catalog.json'),
   connection_retry_checkpoint={'directory':str(checkpoint),'evidence_sha256':sha},
   approved_connection_retry={'user_answer':ANSWER,'maximum_retries':1,'preserve_unknown_usage':True,
     'attempt_id':failure['attempt_id'],'attempt_sha256':failure['attempt_sha256']},
   script_sha256=sha_bytes(Path(__file__).read_bytes()),runner_name=Path(__file__).name,
   connection_retry_support_sha256=sha_bytes((ROOT/'scripts/connection_retry_support.py').read_bytes()),
   parent_final_registration_sha256=digest(strict_json((BASE/'registration.json').read_bytes())),
   execution_order='Only G1 resumes after call 70; G0/G2 keep their sealed final-segment trajectories; no further failure retry granted',
   max_new_calls_total=26)
 write(RUN/'registration.json',reg)
 with tempfile.TemporaryDirectory(dir=RUN,prefix='offline_connection_retry_') as d:
  root=Path(d);test=dict(reg);test['experiment_directory']=str(root);write(root/'registration.json',test)
  rt=branch(root/'G1',test,admission(test,root))
  try:
   before=rt.usage();assert before['actual_model_attempts']==70 and before['unknown_usage']==2
   rt.check_admission(actual=True,reserve=220000+32768)
   assert rt.usage()['actual_model_attempts']==70
   rt.stop('offline_connection_retry_check');sha=seal_evidence(rt)
  finally:rt.close()
  ev=Evidence(root/'G1',sha);trace=[ev.get(r) for r in ev.value['physical']]
  proof=audit(ev);oldproof=audit_retry(ev);lineage=verify_inheritance(ev);production=audit_provenance(ev,trace);cost=audit_cost(ev)
  assert production['valid'] and production['algorithm_production_tasks']==0 and cost['unknown_usage']==2 and not cost['valid']
  bad={**test,'approved_connection_retry':{**test['approved_connection_retry'],'maximum_retries':2}}
  try:validate_connection_grant(ev,bad)
  except HarnessError:pass
  else:raise AssertionError('Broader retry permission must be rejected')
 write(RUN/'offline_validation.json',{'all_pass':True,'new_model_calls':0,'all_70_calls_retained':True,
   'new_retry_audit':proof,'first_retry_audit':oldproof,'inheritance':lineage,'production':production,'cost':cost,'original_B_unchanged':isolation()['valid']})
 print(json.dumps({'event':'prepared','calls_retained':70,'unknown_usage_retained':2,'new_model_calls':0}),flush=True)

def run():
 reg=strict_json((RUN/'registration.json').read_bytes())
 require(fingerprint()['sha256']==reg['fingerprint_sha256'] and sha_bytes(Path(__file__).read_bytes())==reg['script_sha256'],
         'connection_source','Registered source or runner changed')
 rt=branch(RUN/'G1',reg,admission(reg))
 try:
  while rt.usage()['actual_model_attempts']<96 and rt.env.t<1800 and rt.head['phase'] not in ('STOPPED','CLOSED','AUDITING'):
   print(json.dumps({'event':'call_start','group':'G1','call_number':rt.usage()['actual_model_attempts']+1,'time':rt.env.t}),flush=True)
   try:
    result=call(rt,task=reg['task']);print(json.dumps({'event':'call_end','group':'G1','status':result.get('status'),'error':result.get('error'),'usage':rt.usage()}),flush=True)
    if rt.head['phase']=='COMMITTED':
     f=rt.advance();print(json.dumps({'event':'advance','group':'G1','from':f['from'],'to':f['to'],'dispatches':f['dispatch_count_delta'],'reason':f['stop_reason']['reason']}),flush=True)
    if rt.env.t>=1800 and rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_evaluation_end')
   except Exception as exc:
    write(RUN/'G1.failure.json',{'type':type(exc).__name__,'detail':str(exc)})
    if rt.head['phase'] not in ('STOPPED','CLOSED'):rt.stop('connection_retry_exception:'+type(exc).__name__)
    print(json.dumps({'event':'stopped','error':str(exc)}),flush=True)
   write(RUN/'G1.progress.json',outcome(rt))
  if rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_attempt_cap')
  result=outcome(rt);result['evidence_sha256']=seal_evidence(rt);write(RUN/'G1.result.json',result)
 finally:rt.close()
 print(json.dumps({'event':'complete','time':result['head']['time'],'isolation':isolation()}),flush=True)

if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
