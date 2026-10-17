"""Pre-call control fix migration. No attempt, physical state, or budget reset."""
from pathlib import Path
import sys,time
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.context_recovery import amendment,activate,exact_retry
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.experiment import cumulative_usage,resource_status
reg=strict_json((O/'experiment.json').read_bytes());proof=strict_json((O/'recovery_verification_v2.json').read_bytes());require(proof['all_pass'] and proof['source_unchanged'] and proof['fingerprint_sha256']==fingerprint()['sha256'],'verification','Passing current control tests required')
def ref(name):p=O/name;return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
oldraw=(O/'recovery_amendment.json').read_bytes();old=strict_json(oldraw);archive=O/'recovery_amendment_v1.json';require(not archive.exists(),'immutable','Migration already started');archive.write_bytes(oldraw)
new={**old,'created_epoch':time.time(),'after_fingerprint':ref('recovery_active_fingerprint_v2.json'),'verification':ref('recovery_verification_v2.json'),'previous_control_revision':ref('recovery_amendment_v1.json'),'control_fix':'Preserve stop_reason=None, a required nullable control field; no new model calls since original interruption.'}
(O/'recovery_amendment.json').write_bytes(encode(new));amendment(reg)
migrations=[]
for case in reg['execution_order']:
 store=Store(O/'runs'/case)
 try:
  before=store.meta('head');attempt_hashes=dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'"));updates=[]
  with store.transaction():
   for ns in ('transport_recoveries','context_recovery_control'):
    for k,row in store.rows(ns):
     require(row['amendment_sha256']==digest(old),'control_revision','Unknown control predecessor')
     changed={**row,'amendment_sha256':digest(new)};store.record(ns,k,changed,replace=True)
     updates.append({'namespace':ns,'key':k,'before_ref':digest(row),'after_ref':digest(changed)})
   head=store.meta('head')
   if 'stop_reason' not in head:head['stop_reason']=None;store.set_meta('head',head)
   require(all(before[k]==head[k] for k in ('state_ref','time','revision','context_ref')),'physical_state','Control-only migration')
   store.event('context_recovery_control_fix',{'old_amendment_sha256':digest(old),'new_amendment_sha256':digest(new),'updates':updates,'head_before':before,'head_after':head,'new_model_calls':0})
  require(attempt_hashes==dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'")),'cost_retention','Attempt records changed')
  migrations.append({'case':case,'updates':updates,'attempt_records_identical':True,'physical_state_identical':True})
 finally:store.close()
rows=[];admission=None
for case in reg['execution_order']:
 r=Runtime.resume_run(O/'runs'/case)
 try:
  before=r.head;activate(r);require(before['state_ref']==r.head['state_ref'] and before['time']==r.head['time'],'state','Recovery changed physics')
  if 'filter_projection' in case:
   a=r.store.rows('attempts')[-1][1];text,schema=exact_retry(r,'fresh',{});require(sha_bytes(text.encode())==a['prompt_ref'] and sha_bytes(encode_model_schema(schema))==a['schema_ref'],'exact_retry','Payload changed');r.check_admission(actual=True,reserve=100000)
  rows.append({'case':case,'time':r.env.t,'phase':r.head['phase'],'model_calls':r.usage()['actual_model_attempts'],'physical_state_unchanged':True});admission=r.manifest['admission']
 finally:r.close()
usage=cumulative_usage(admission);status=resource_status(reg,usage);require(usage['combined']['attempts']==6 and usage['combined']['unknown_usage']==1 and status['unexempt_unknown_usage']['combined']==0,'cost_retention','Original failures must be retained and exactly authorized')
value={'all_pass':True,'new_model_calls':0,'migrations':migrations,'cases':rows,'usage':usage,'resource_status':status,'created_epoch':time.time()};(O/'recovery_activation_preflight.json').write_bytes(encode(value));print({'all_pass':True,'calls_before_resume':usage['combined']['attempts'],'unknown_usage_retained':usage['combined']['unknown_usage'],'unexempt_unknown':status['unexempt_unknown_usage']['combined'],'phases':[r['phase'] for r in rows]})
