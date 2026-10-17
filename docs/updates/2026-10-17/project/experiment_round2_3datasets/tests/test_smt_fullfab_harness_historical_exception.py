"""One exact historical exception; every new unknown still freezes. No inference."""
from copy import deepcopy
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.smt_fullfab.harness.contracts import ROOT,HarnessError,encode,digest,fingerprint,sha_bytes,strict_json,default_config
from src.smt_fullfab.harness.experiment import sealed_prior,resource_status,continuation_authorization,registration,cumulative_usage,check_experiment_budget,UNCAPPED_MODEL_CAPS
from src.smt_fullfab.harness.evaluation import Evidence,audit_cost
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import pending_start_validation,prompt
from src.smt_fullfab.harness.p5 import prepare,validate_same_cohort,micro

class HistoricalExceptionTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(tempfile.mkdtemp(prefix='offline-historical-exception-'))
  self.grant_path=ROOT/'artifacts/harness_v1_5_offline/authorization.json'
  self.grant=strict_json(self.grant_path.read_bytes())
 def ref(self,p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
 def value(self,path=None):return {'authorization':self.ref(path or self.grant_path),'prior_cost_evidence':self.grant['prior_cost_evidence']}
 def test_T23_exact_exception_retains_all_costs_and_original_failure(self):
  value=self.value();u,starts,ids=sealed_prior(value)
  self.assertEqual((u['combined']['attempts'],u['combined']['tokens'],u['combined']['unknown_usage'],len(ids),starts),(41,1592864,1,7,0))
  disclosure=resource_status(value,u)
  self.assertEqual(disclosure['unexempt_unknown_usage']['combined'],0)
  self.assertFalse(disclosure['cumulative_cost_closed']);self.assertTrue(disclosure['reported_tokens_are_lower_bound'])
  item=self.grant['historical_unknown_exceptions'][0];boundary=item['boundary']
  e=Evidence(Path(boundary['path']).parent,boundary['sha256']);a=e.rows('attempts')[item['attempt_id']]
  self.assertIsNone(a['usage']);self.assertEqual(audit_cost(e)['unknown_usage'],1);self.assertFalse(audit_cost(e)['valid'])
 def test_T23_exception_cannot_expand_discount_omit_ancestors_or_relabel_failure(self):
  for field,val in [('attempt_id','attempt:new'),('events_sha256','0'*64),('attempt_record_sha256','0'*64),('unreported_usage',0),('retry_original',True),('preserve_failure',False),('scope','all_future')]:
   grant=deepcopy(self.grant);grant['historical_unknown_exceptions'][0][field]=val
   path=self.root/(field+'.json');path.write_bytes(encode(grant))
   with self.assertRaises(HarnessError,msg=field):sealed_prior(self.value(path))
  grant=deepcopy(self.grant);grant['historical_unknown_exceptions']*=2
  path=self.root/'duplicate.json';path.write_bytes(encode(grant))
  with self.assertRaisesRegex(HarnessError,'unknown_exception'):sealed_prior(self.value(path))
  with self.assertRaisesRegex(HarnessError,'carry_ancestor_missing'):sealed_prior({'authorization':self.ref(self.grant_path)})
  with self.assertRaisesRegex(HarnessError,'carry_unknown'):sealed_prior({'prior_cost_evidence':self.grant['prior_cost_evidence']})
  aggregate=strict_json(Path(self.grant['prior_cost_evidence']['path']).read_bytes())
  for field in ['tokens','unknown_usage']:
   changed=deepcopy(aggregate);changed['cumulative_usage']['micro'][field]-=1
   path=self.root/(field+'-aggregate.json');path.write_bytes(encode(changed))
   with self.assertRaisesRegex(HarnessError,'carry_totals'):sealed_prior({**self.value(),'prior_cost_evidence':self.ref(path)})
  grant=deepcopy(self.grant);grant['schema']='harness-user-continuation-20261014-v2';path=self.root/'oldgrant.json';path.write_bytes(encode(grant))
  with self.assertRaisesRegex(HarnessError,'unknown_exception'):continuation_authorization(self.ref(path))
 def test_T23_new_persistent_unknown_freezes_despite_historical_exception(self):
  cfg=default_config(seconds=60);cfg['limits'].update(UNCAPPED_MODEL_CAPS['micro'])
  fp=fingerprint();proof=self.root/'proof.json';proof.write_bytes(encode({'gates':{g:'pass' for g in ['G0','G1','G2','G3','G4']},'fingerprint_sha256':fp['sha256'],'test_only':True}))
  value={**self.value(),'schema':'harness-p5-registration-v5','caps':UNCAPPED_MODEL_CAPS,'full_B_new_run_limit':1,'cases':{'new':{'group':'micro','config_sha256':digest(cfg),'initial_state_sha256':None}},'fingerprint_sha256':fp['sha256'],'engineering_report':str(proof),'engineering_report_sha256':sha_bytes(proof.read_bytes()),'cli_binary':'/never/invoked','cli_sha256':'offline-only'}
  (self.root/'experiment.json').write_bytes(encode(value))
  adm={'experiment_directory':str(self.root),'experiment_sha256':digest(value),'case_id':'new','group':'micro','cli_binary':'/never/invoked','cli_sha256':'offline-only'}
  self.assertEqual(registration(adm),value)
  r=Runtime.start_new(self.root/'new',cfg,experiment_id='synthetic-no-inference',mode='model',admission=adm)
  try:
   check_experiment_budget(r,100000)
   aid=r.reserve_attempt('synthetic never sent',{});r.mark_started(aid);r.save_response(aid,b'',usage=None,duration_seconds=.01)
   u=cumulative_usage(adm);self.assertEqual(u['combined']['unknown_usage'],2)
   with self.assertRaisesRegex(HarnessError,'experiment_unknown'):check_experiment_budget(r,100000)
   r.close();r=Runtime.resume_run(self.root/'new')
   with self.assertRaises(HarnessError):r.reserve_attempt('blocked',{})
   self.assertEqual(len(r.store.rows('attempts')),1)
  finally:r.close()
 def test_T01_exception_keeps_twenty_initials_tasks_and_failed_member_on_resume(self):
  target=self.root/'twenty'
  with redirect_stdout(io.StringIO()):prep=prepare(target,authorization=self.grant_path)
  validate_same_cohort(target,prep)
  self.assertEqual(sum(x['group']=='micro' for x in prep['cases'].values()),20)
  value={**self.value(),'schema':'harness-p5-registration-v5','cases':prep['cases'],'caps':UNCAPPED_MODEL_CAPS,'full_B_new_run_limit':1,'cli_binary':'/never/invoked','cli_sha256':'offline-only','model_catalog':'/unused','model_catalog_sha256':'unused'}
  (target/'experiment.json').write_bytes(encode(value))
  fail=target/'runs/micro-01';fail.mkdir(parents=True);(fail/'fragment_result.json').write_bytes(encode({'id':'micro-01','attempts':4,'accepted':False}))
  with patch('src.smt_fullfab.harness.p5.open_case',side_effect=AssertionError('must not run after recorded failure')):
   result=micro(target)
  self.assertFalse(result['pass']);self.assertEqual(len(result['fragments']),20)
  self.assertEqual(result['cost_disclosure']['authorized_historical_unknown_usage']['micro'],1)
 def test_T12_pending_start_diagnostics_are_public_exact_bounded_and_do_not_choose(self):
  tasks=[{'id':str(i),'not_before':float(i)} for i in range(100)]
  base={'tasks':tasks,'freeze_until':0}
  original=deepcopy(base);check=pending_start_validation(base,{str(i) for i in range(100)},90,'base-ref')
  self.assertEqual(check['count'],90);self.assertEqual(check['omitted'],26);self.assertEqual(check['rows'][0],{'task_id':'0','not_before':0.,'current_time':90,'original_path':['tasks',0]})
  self.assertIsNone(check['corrections']);self.assertEqual(base,original)
  base['freeze_until']=95
  self.assertEqual(pending_start_validation(base,{str(i) for i in range(100)},90,'b')['count'],0)
  base['freeze_until']=0
  self.assertEqual(pending_start_validation(base,{'90','91'},90,'b')['count'],0)
 def test_T12_actual_saved_state_prompt_exposes_stale_start_without_plan_edit(self):
  import zlib
  initial=strict_json(zlib.decompress((ROOT/'artifacts/harness_p5_v1_3_release/micro-02.initial.json.z').read_bytes()))
  cfg=default_config(seconds=initial['state']['horizon']-initial['state']['t']);cfg['initialization']='registered_saved_state'
  r=Runtime.start_new(self.root/'saved',cfg,experiment_id='offline-read-only-diagnostics',initial=initial)
  try:
   before=deepcopy(r.env.plan);text=prompt(r);frame=strict_json(text[text.index('\n{')+1:]);check=frame['context']['pending_start_validation'] if 'context' in frame else frame['pending_start_validation']
   self.assertEqual(check['count'],1);self.assertEqual(check['rows'][0]['task_id'],'r994_w1122_270')
   self.assertEqual(r.env.plan,before);self.assertEqual(r.store.rows('commits'),[]);self.assertEqual(r.store.rows('attempts'),[])
  finally:r.close()

if __name__=='__main__':unittest.main()
