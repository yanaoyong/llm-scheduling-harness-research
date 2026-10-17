"""Audited continuation of the original four accounts; no network or live B actions."""
from pathlib import Path
import sys,time
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.context_recovery import amendment,activate,exact_retry,POLICY
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.experiment import cumulative_usage,resource_status
reg=strict_json((O/'experiment.json').read_bytes());proof=strict_json((O/'recovery_verification_v3.json').read_bytes());require(proof['all_pass'] and proof['source_unchanged'] and proof['fingerprint_sha256']==fingerprint()['sha256'],'verification','Passing current tests required')
def ref(name):p=O/name;return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
old=strict_json((O/'recovery_amendment_v2.json').read_bytes());require(strict_json((O/'recovery_amendment.json').read_bytes())==old,'control_revision','Exact prior active revision required')
grant={**strict_json((O/'recovery_user_authorization.json').read_bytes()),'schema':'context-2x2-uncapped-recovery-grant-v1','approved_epoch':time.time(),'user_reply':'允许，取消限制我们的目标是跑完完整的实验，继续完成四组，不要影响正在跑的 B。','question':'是否允许将剩余的1次全局恢复额度用于该请求的第2次重试？用户明确取消限制并要求完成四组。','policy':POLICY,'cancel_recovery_caps':True,'original_resource_caps_unchanged_in_this_revision':True,'completion_intent':'Complete the original four-arm common-window experiment; any further control revision must preserve treatment and every cost.'}
(O/'recovery_user_authorization_uncapped.json').write_bytes(encode(grant))
new={**old,'created_epoch':time.time(),'authorization':ref('recovery_user_authorization_uncapped.json'),'after_fingerprint':ref('recovery_active_fingerprint_v3.json'),'verification':ref('recovery_verification_v3.json'),'previous_control_revision':ref('recovery_amendment_v2.json'),'boundary':ref('recovery_exhaustion_audit.json'),'runner_sha256':sha_bytes((O/'experiment.py').read_bytes()),'control_fix':'User removed per-request/cohort retry caps; progressive 60/120/300-second backoff, same metered accounts and treatment. Resource stops retain resumable accounts instead of sealing incomplete results.'}
(O/'recovery_amendment.json').write_bytes(encode(new));amendment(reg)
migrations=[]
for case in reg['execution_order']:
 store=Store(O/'runs'/case)
 try:
  before=store.meta('head');hashes=dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'"));updates=[]
  with store.transaction():
   for ns in ('transport_recoveries','context_recovery_control'):
    for k,row in store.rows(ns):
     require(row['amendment_sha256']==digest(old),'control_revision','Unexpected predecessor')
     changed={**row,'amendment_sha256':digest(new)}
     if ns=='transport_recoveries':changed['policy_sha256']=digest(POLICY)
     store.record(ns,k,changed,replace=True);updates.append({'namespace':ns,'key':k,'before_ref':digest(row),'after_ref':digest(changed)})
   store.event('context_recovery_user_removed_caps',{'old_amendment_sha256':digest(old),'new_amendment_sha256':digest(new),'updates':updates,'head_before':before,'head_after':store.meta('head'),'new_model_calls':0})
  require(hashes==dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'")) and before==store.meta('head'),'retention','No attempt/head mutation')
  migrations.append({'case':case,'updates':updates,'attempts_and_head_identical':True})
 finally:store.close()
rows=[]
for case in reg['execution_order']:
 r=Runtime.resume_run(O/'runs'/case)
 try:
  before=r.head;activate(r);require(all(before[k]==r.head[k] for k in ('state_ref','time','revision','context_ref')),'state','Physical context changed')
  if 'filter_projection' in case:
   a=r.store.rows('attempts')[-1][1];text,schema=exact_retry(r,'fresh',{});require(sha_bytes(text.encode())==a['prompt_ref'] and sha_bytes(encode_model_schema(schema))==a['schema_ref'],'exact_retry','Payload changed');r.check_admission(actual=True,reserve=100000)
  rows.append({'case':case,'time':r.env.t,'phase':r.head['phase'],'model_calls':r.usage()['actual_model_attempts']});admission=r.manifest['admission']
 finally:r.close()
usage=cumulative_usage(admission);status=resource_status(reg,usage);require(usage['combined']['attempts']==7 and usage['combined']['unknown_usage']==2 and status['unexempt_unknown_usage']['combined']==0,'retention','All original usage retained and failures proven')
value={'all_pass':True,'new_model_calls':0,'migrations':migrations,'cases':rows,'usage':usage,'resource_status':status,'created_epoch':time.time()};(O/'recovery_activation_uncapped.json').write_bytes(encode(value));print({'all_pass':True,'calls':7,'unknown_usage_retained':2,'unexempt_unknown':0,'phases':[r['phase'] for r in rows]})
