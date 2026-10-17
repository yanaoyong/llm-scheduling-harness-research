"""Finish the fixed 1800-second comparison with preserved outcomes and costs."""
from pathlib import Path
import sys,json,shutil,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from src.smt_fullfab.harness.contracts import digest,fingerprint,sha_bytes,strict_json,require,HarnessError
from src.smt_fullfab.harness.evaluation import Evidence,seal_evidence,audit_provenance,audit_cost
from src.smt_fullfab.harness.transport import call
from src.smt_fullfab.harness import capacity_pilot as pilot
from connection_retry_support import ANSWER,validate_connection_grant,audit as connection_audit
from capacity_retry_support import audit_retry
from deadline_completion_support import branch,audit
from extended_lineage_audit import verify_inheritance
from run_extended_three_group_pilot import outcome,write,isolation
BASE=ROOT/'live_pilots/extended_three_group_final_segment_20261017'
RUN=ROOT/'live_pilots/extended_three_group_deadline_completion_20261017'

def admission(group,reg,root=RUN):
 return {'schema':pilot.SCHEMA,'group':group,'experiment_directory':str(root),'experiment_sha256':digest(reg),
         **{k:reg[k] for k in ('cli_binary','cli_sha256','model_catalog','model_catalog_sha256')}}

def prepare():
 from src.smt_fullfab.harness.offline_isolation import install_guard
 install_guard();RUN.mkdir(exist_ok=False)
 reg=strict_json((BASE/'registration.json').read_bytes());failure=strict_json((BASE/'G1.second_failure_review.json').read_bytes());parents={};checks={}
 require(reg['fingerprint_sha256']==fingerprint()['sha256'],'deadline_source','Previous live source changed')
 for g in reg['groups']:
  result=strict_json((BASE/(g+'.result.json')).read_bytes());parents[g]={'directory':str(BASE/g),'evidence_sha256':result['evidence_sha256']}
  for tail in ('.config.json','.initial_backlog.json'):shutil.copyfile(BASE/(g+tail),RUN/(g+tail))
 for name in ('model-catalog.json','outbound_verification.json','already_planned_replan_case.json','zero_time_replan_case.json','G1.second_failure_review.json'):
  shutil.copyfile(BASE/name,RUN/name)
 reg.update(experiment_directory=str(RUN),model_catalog=str(RUN/'model-catalog.json'),
   connection_retry_checkpoint=parents['G1'],
   approved_connection_retry={'user_answer':ANSWER,'maximum_retries':1,'preserve_unknown_usage':True,'attempt_id':failure['attempt_id'],'attempt_sha256':failure['attempt_sha256']},
   deadline_reconciliation={'predecessors':parents,'no_config_or_source_change':True,'target_unchanged':1800},
   script_sha256=sha_bytes(Path(__file__).read_bytes()),runner_name=Path(__file__).name,
   connection_retry_support_sha256=sha_bytes((ROOT/'scripts/connection_retry_support.py').read_bytes()),
   deadline_support_sha256=sha_bytes((ROOT/'scripts/deadline_completion_support.py').read_bytes()),
   parent_final_registration_sha256=digest(strict_json((BASE/'registration.json').read_bytes())),
   execution_order='Round robin; preserve G0/G2 successful calls and proposals; one separately approved G1 connection retry; same 96-call caps',
   max_new_calls_total=75)
 write(RUN/'registration.json',reg)
 with tempfile.TemporaryDirectory(dir=RUN,prefix='offline_deadline_reconciliation_') as d:
  root=Path(d);test=dict(reg);test['experiment_directory']=str(root);write(root/'registration.json',test)
  for g in reg['groups']:
   rt=branch(root/g,g,test,admission(g,test,root))
   try:
    before=rt.usage();rt.check_admission(actual=True,reserve=rt.config['capacity_experiment']['input_token_budget']+32768)
    assert rt.usage()['actual_model_attempts']==before['actual_model_attempts']=={'G0':72,'G1':70,'G2':71}[g]
    rt.stop('offline_deadline_reconciliation');sha=seal_evidence(rt)
   finally:rt.close()
   ev=Evidence(root/g,sha);trace=[ev.get(r) for r in ev.value['physical']];cost=audit_cost(ev);production=audit_provenance(ev,trace)
   proof=audit(ev);lineage=verify_inheritance(ev)
   assert production['valid'] and production['algorithm_production_tasks']==0 and cost['unknown_usage']==(2 if g=='G1' else 0)
   checks[g]={'deadline':proof,'inheritance':lineage,'production':production,'cost':cost,'new_model_calls':0}
   if g=='G1':
    checks[g].update(connection_retry=connection_audit(ev),first_retry=audit_retry(ev))
    bad={**test,'approved_connection_retry':{**test['approved_connection_retry'],'maximum_retries':2}}
    try:validate_connection_grant(ev,bad)
    except HarnessError:pass
    else:raise AssertionError('Broader retry allowance must be rejected')
   print(json.dumps({'event':'offline_pass','group':g,'calls_retained':before['actual_model_attempts'],'new_model_calls':0}),flush=True)
 write(RUN/'offline_validation.json',{'all_pass':True,'groups':checks,'no_model_calls':True,'original_B_unchanged':isolation()['valid']})
 print(json.dumps({'event':'prepared','target':1800,'same_call_cap':96}),flush=True)

def run():
 reg=strict_json((RUN/'registration.json').read_bytes());require(fingerprint()['sha256']==reg['fingerprint_sha256'],'deadline_source','Source changed')
 for name,key in [(Path(__file__).name,'script_sha256'),('deadline_completion_support.py','deadline_support_sha256'),('connection_retry_support.py','connection_retry_support_sha256'),('extended_lineage_audit.py','lineage_audit_sha256')]:
  require(sha_bytes((ROOT/'scripts'/name).read_bytes())==reg[key],'deadline_source','Registered runner or helper changed')
 runtimes={}
 try:
  for g in reg['groups']:runtimes[g]=branch(RUN/g,g,reg,admission(g,reg))
  for _ in range(26):
   for g,rt in runtimes.items():
    if rt.head['phase'] in ('STOPPED','CLOSED','AUDITING'):continue
    if rt.usage()['actual_model_attempts']>=96:rt.stop('pilot_attempt_cap');continue
    print(json.dumps({'event':'call_start','group':g,'call_number':rt.usage()['actual_model_attempts']+1,'time':rt.env.t}),flush=True)
    try:
     result=call(rt,task=reg['task']);print(json.dumps({'event':'call_end','group':g,'status':result.get('status'),'error':result.get('error'),'usage':rt.usage()}),flush=True)
     if rt.head['phase']=='COMMITTED':
      f=rt.advance();print(json.dumps({'event':'advance','group':g,'from':f['from'],'to':f['to'],'dispatches':f['dispatch_count_delta'],'reason':f['stop_reason']['reason']}),flush=True)
     if rt.env.t>=1800 and rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_evaluation_end')
    except Exception as exc:
     write(RUN/(g+'.failure.json'),{'type':type(exc).__name__,'detail':str(exc)})
     if rt.head['phase'] not in ('STOPPED','CLOSED'):rt.stop('reconciled_exception:'+type(exc).__name__)
     print(json.dumps({'event':'group_stopped','group':g,'error':str(exc)}),flush=True)
    write(RUN/(g+'.progress.json'),outcome(rt))
  for g,rt in runtimes.items():
   if rt.head['phase'] not in ('STOPPED','AUDITING'):rt.stop('pilot_attempt_cap')
   result=outcome(rt);result['evidence_sha256']=seal_evidence(rt);write(RUN/(g+'.result.json'),result)
 finally:
  for rt in runtimes.values():rt.close()
 print(json.dumps({'event':'complete','isolation':isolation()}),flush=True)

if __name__=='__main__':{'prepare':prepare,'run':run}[sys.argv[1]]()
