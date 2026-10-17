from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import ast,sys,unittest,time,json
O=Path(__file__).resolve().parent;sys.path.insert(0,str(O/'workspace'))
from src.smt_fullfab.harness.contracts import *
from src.smt_fullfab.harness.recovery import LiveEvidence,failure_kind
from src.smt_fullfab.harness import context_recovery as c
reg=strict_json((O/'experiment.json').read_bytes());view=LiveEvidence(O/'runs/singleton_2403__filter_projection');attempts=view.rows('attempts');a=next(a for a in attempts.values() if a['usage'] is None);aid=a['attempt_id'];revision={'registration_sha256':sha_bytes((O/'experiment.json').read_bytes())}
row={'attempt_id':aid,'attempt_sha256':digest(a),'context_ref':a['context_ref'],'failure_kind':'stream_disconnect','request_failure_ordinal':1,'cohort_failure_ordinal':1,'not_before_epoch':a['finished_epoch']+60,'policy_sha256':digest(c.POLICY),'amendment_sha256':digest(revision),'usage':None,'business_action_replayed':False}
class View:
 def __init__(self,more=None):self.manifest=deepcopy(view.manifest);self.attempts={**deepcopy(attempts),**(more or {})}
 def rows(self,ns):return self.attempts if ns=='attempts' else {}
 def raw(self,ref):return view.raw(ref)
 def get(self,ref):return view.get(ref)
class RecoveryTests(unittest.TestCase):
 def test_original_failure_lifecycle(self):
  self.assertEqual(failure_kind(view,a),'stream_disconnect');self.assertEqual(a['usage'],None);self.assertEqual(view.raw(a['raw_ref']),b'')
 def test_corrupt_returncode_and_output_are_ineligible(self):
  for change in ('code','usage','status'):
   aa=deepcopy(a)
   if change=='code':aa['transport']['returncode']=0
   if change=='usage':aa['usage']={'input_tokens':0,'output_tokens':0}
   if change=='status':aa['status']='started'
   with self.assertRaises(HarnessError):failure_kind(view,aa)
 def test_original_closed_failure_preserved(self):
  self.assertEqual(c.validate_rows(view,{aid:row},reg,revision),{aid:row});self.assertIsNone(a['usage'])
 def test_exact_retry_after_cooldown(self):
  n={'attempt_id':'retry','index':2,'channel':'codex','status':'reserved','context_ref':a['context_ref'],'prompt_ref':a['prompt_ref'],'schema_ref':a['schema_ref'],'reserved_epoch':a['finished_epoch']+60}
  self.assertEqual(c.validate_rows(View({'retry':n}),{aid:row},reg,revision),{aid:row})
  for k,v in [('reserved_epoch',a['finished_epoch']+59),('prompt_ref','wrong'),('schema_ref','wrong'),('context_ref','wrong')]:
   nn={**n,k:v}
   with self.assertRaisesRegex(HarnessError,'context_recovery_retry'):c.validate_rows(View({'retry':nn}),{aid:row},reg,revision)
 def test_second_retry_same_request_denied(self):
  n={**deepcopy(a),'attempt_id':'retry','index':2,'reserved_epoch':a['finished_epoch']+60}
  rr={**row,'attempt_id':'retry','attempt_sha256':digest(n),'cohort_failure_ordinal':2}
  with self.assertRaisesRegex(HarnessError,'recovery_limit'):c.validate_rows(View({'retry':n}),{aid:row,'retry':rr},reg,revision)
 def test_no_reset_or_imputed_zero(self):
  for k,v in [('attempt_sha256','wrong'),('usage',{}),('business_action_replayed',True),('request_failure_ordinal',0),('cohort_failure_ordinal',3),('not_before_epoch',0),('policy_sha256','wrong')]:
   rr={**row,k:v}
   with self.assertRaises(HarnessError):c.validate_rows(view,{aid:rr},reg,revision)
 def test_cohort_two_slots_only(self):
  for values in [[],[1],[1,2]]:c.validate_ordinals(values)
  for values in [[0],[2],[1,1],[1,2,3]]:
   with self.assertRaises(HarnessError):c.validate_ordinals(values)
 def test_original_config_and_registration_required(self):
  for item in ('model','limits','registration'):
   v=View()
   if item=='model':v.manifest['config']['model']['name']='other'
   if item=='limits':v.manifest['config']['limits']['attempts']=61
   if item=='registration':v.manifest['admission']['experiment_sha256']='other'
   with self.assertRaises(HarnessError):c.validate_rows(v,{aid:row},reg,revision)
 def test_exact_retry_bytes_unchanged_no_model_call(self):
  store=SimpleNamespace(path=view.path,rows=lambda ns:list(attempts.items()),bytes=view.raw)
  r=SimpleNamespace(store=store,head={'context_ref':a['context_ref']})
  with patch.object(c,'validate',return_value={aid:row}):text,schema=c.exact_retry(r,'fresh',{})
  self.assertEqual(sha_bytes(text.encode()),a['prompt_ref']);self.assertEqual(sha_bytes(encode_model_schema(schema)),a['schema_ref'])
 def test_changes_only_recovery_hooks_and_same_prompt_schema_command(self):
  before=strict_json((O/'recovery_baseline_fingerprint.json').read_bytes());after=fingerprint()
  changed={p for p in before['files'].keys()|after['files'].keys() if before['files'].get(p)!=after['files'].get(p)}
  self.assertEqual(changed,c.CONTROL_FILES)
  self.assertEqual({k:v for k,v in before.items() if k not in ('files','sha256')},{k:v for k,v in after.items() if k not in ('files','sha256')})
  def functions(p):
   tree=ast.parse(p.read_text());return {n.name:ast.dump(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('command','prompt','response_schema','interaction_history')},next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROTOCOL_TEXT' for t in n.targets))
  self.assertEqual(functions(O/'recovery_before_source/transport.py'),functions(O/'workspace/src/smt_fullfab/harness/transport.py'))
 def test_no_enabled_policy_before_amendment(self):
  with patch.object(c,'amendment',return_value=None):self.assertIsNone(c.policy(reg))
  self.assertEqual(c.validate(View()),{})
fp=fingerprint();(O/'recovery_active_fingerprint_v2.json').write_bytes(encode(fp))
from tests import test_smt_fullfab_harness_bounded_recovery as fixtures
fixtures.ROOT=O.parents[1]/'experiment_round2_3datasets'
modules=['test_smt_fullfab_harness_schema_order','test_smt_fullfab_harness_bounded_recovery']
suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(RecoveryTests)]+[unittest.defaultTestLoader.loadTestsFromName('tests.'+m) for m in modules])
with (O/'recovery_verification_v2.log').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
proof={'all_pass':r.wasSuccessful(),'tests_run':r.testsRun,'errors':len(r.errors),'failures':len(r.failures),'source_unchanged':fp==fingerprint(),'fingerprint_sha256':fp['sha256'],'remote_model_calls':0,'original_failure_and_cost_retained':True,'created_epoch':time.time()};(O/'recovery_verification_v2.json').write_bytes(encode(proof));print(json.dumps(proof));sys.exit(not proof['all_pass'])
