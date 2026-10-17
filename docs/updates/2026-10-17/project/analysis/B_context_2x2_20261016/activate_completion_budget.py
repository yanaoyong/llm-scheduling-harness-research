from pathlib import Path
import sys,time
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.context_recovery import amendment,activate,cohort
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.experiment import cumulative_usage,resource_status
from src.smt_fullfab.harness.wall_budget import effective_budget,shared_caps
reg=strict_json((O/'experiment.json').read_bytes());proof=strict_json((O/'recovery_verification_v5.json').read_bytes())
require(proof['all_pass'] and proof['source_unchanged'] and proof['fingerprint_sha256']==fingerprint()['sha256'],'verification','Current passing tests required')
def ref(name):p=O/name;return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
old=strict_json((O/'recovery_amendment_v4.json').read_bytes());require(strict_json((O/'recovery_amendment.json').read_bytes())==old,'revision','Exact predecessor required')
grant={**strict_json((O/'recovery_user_authorization_uncapped.json').read_bytes()),'approved_epoch':time.time(),'increase_limits':True,'count_caps_removed':True,'changed_limit_fields':['attempts','tokens','model_seconds','wall_seconds'],'completion_limits':{'attempts':None,'tokens':None,'model_seconds':7200,'wall_seconds':57600},'original_resource_caps_unchanged_in_this_revision':False,'question':'执行用户取消限制并完成四组的授权：解除次数与token总量硬上限，累计模型时长扩为每组7200秒/共享28800秒，运行时长扩为57600秒，原始上限保留为参考。','unchanged_other_limits':False,'unchanged_per_call_timeout_and_model':True}
(O/'completion_user_authorization.json').write_bytes(encode(grant))
new={**old,'created_epoch':time.time(),'authorization':ref('completion_user_authorization.json'),'after_fingerprint':ref('recovery_active_fingerprint_v5.json'),'verification':ref('recovery_verification_v5.json'),'previous_control_revision':ref('recovery_amendment_v4.json'),'runner_sha256':sha_bytes((O/'experiment.py').read_bytes()),'count_pause_boundary':ref('completion_budget_gate.json'),'same_caps':False,'control_fix':'Uniform completion allowance on the same four accounts: uncapped attempts/tokens, 7200 model seconds per arm, 28800 shared model seconds, 57600 wall seconds. Same model, per-call timeout, treatment and every prior cost. Previous recovery rows immutable.'}
(O/'recovery_amendment.json').write_bytes(encode(new));amendment(reg)
rows=[]
for case in reg['execution_order']:
 store=Store(O/'runs'/case)
 try:
  before=store.meta('head');hashes=dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'"));recoveries=dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='transport_recoveries'"));manifest=store.read('manifest','run')
  # Store manifest is an object reference, use the established runtime's manifest structure below.
  if isinstance(manifest,str):manifest=store.get(manifest)
  require(not any(a['status'] in ('reserved','started','unknown') for _,a in store.rows('attempts')),'pending','No in-flight request at revision boundary')
  row={'run_id':manifest['run_id'],'original_manifest_sha256':digest(manifest),'original_attempt_limit':60,'effective_attempt_limit':None,'new_model_calls':0,'amendment_sha256':digest(new),'next_attempt_index':len(hashes)+1}
  old_marker=store.read('control_source_revisions','context-uncapped-counts');require(old_marker['amendment_sha256']==digest(old),'marker','Exact prior count allowance required')
  with store.transaction():
   store.record('control_source_revisions','context-uncapped-counts',row,replace=True)
   store.event('context_completion_budget_extended',{'before':old_marker,'after':row,'new_model_calls':0})
  require(hashes==dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='attempts'")) and recoveries==dict(store.db.execute("SELECT key,ref FROM records WHERE namespace='transport_recoveries'")) and before==store.meta('head'),'retention','No attempts/recoveries/head mutation')
  rows.append({'case':case,'attempts':len(hashes),'head':before,'attempt_refs':hashes,'recovery_refs':recoveries,'unchanged':True})
 finally:store.close()
checks=[]
for case in reg['execution_order']:
 r=Runtime.resume_run(O/'runs'/case)
 try:
  before=r.head;activate(r);require(before==r.head,'retention','Head unchanged');b=effective_budget(r.manifest,dict(r.store.rows('control_source_revisions')))
  r.check_admission(actual=True,reserve=100000)
  require(b['limits']=={**r.manifest['config']['limits'],'attempts':None,'tokens':None,'model_seconds':7200,'wall_seconds':57600},'limits','Exact completion allowance')
  checks.append({'case':case,'time':r.env.t,'phase':r.head['phase'],'calls':r.usage()['actual_model_attempts'],'effective_limits':b['limits']});admission=r.manifest['admission']
 finally:r.close()
usage=cumulative_usage(admission);status=resource_status(reg,usage);cohort(reg)
value={'all_pass':True,'new_model_calls':0,'rows':rows,'checks':checks,'usage':usage,'resource_status':status,'created_epoch':time.time()};(O/'completion_budget_activation.json').write_bytes(encode(value));print({'all_pass':True,'checks':checks,'unknown_preserved':usage['combined']['unknown_usage']})
