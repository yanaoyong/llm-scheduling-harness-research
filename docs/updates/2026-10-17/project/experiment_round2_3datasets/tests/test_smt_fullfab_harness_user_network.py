"""Explicit network handoff and historical attempt binding; no remote calls."""
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch
from src.smt_fullfab.harness import source_revision,network,user_managed_network as un
from src.smt_fullfab.harness.contracts import ROOT,encode,strict_json,digest,sha_bytes,fingerprint,HarnessError
OUT=ROOT/'artifacts/harness_B_user_managed_network_20261015'
LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
def read(p):return strict_json(p.read_bytes())
def ref(p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
class UserNetworkTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.temp=Path(t.name)
  self.reg=read(LIVE/'experiment.json');self.base=read(LIVE/'exception_policy_amendment.json');self.prev=read(LIVE/'source_revision_7.json')
  self.boundary=read(OUT/'boundary.json');self.admission=read(Path(self.boundary['manifest']['path']))['admission']
  self.fp=fingerprint();self.grant=read(OUT/'authorization.json');self.sync()
 def sync(self):
  (self.temp/'grant.json').write_bytes(encode(self.grant))
  (self.temp/'test-proof.json').write_bytes(encode({'test_only':True,'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
  (self.temp/'report.json').write_bytes(encode({'test_only':True,'fingerprint':self.fp,'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')},'test_evidence':ref(self.temp/'test-proof.json')}))
  self.value={'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),'base_amendment_sha256':digest(self.base),'previous_source_revision':ref(LIVE/'source_revision_7.json'),'base_source_sha256':self.prev['active_fingerprint_sha256'],'active_fingerprint_sha256':self.fp['sha256'],'repairs':un.REPAIR,'boundary':ref(OUT/'boundary.json'),'engineering_report':ref(self.temp/'report.json'),'user_authorization':ref(self.temp/'grant.json')}
 def selection(self):
  stack=ExitStack();original_exists=Path.exists;original_read=Path.read_bytes;path=LIVE/'source_revision_8.json'
  stack.enter_context(patch.object(Path,'exists',lambda p:True if p==path else original_exists(p)))
  stack.enter_context(patch.object(Path,'read_bytes',lambda p:encode(self.value) if p==path else original_read(p)))
  stack.enter_context(patch.object(source_revision,'for_amendment',return_value=self.value))
  stack.enter_context(patch('src.smt_fullfab.harness.network_tun.current_route',side_effect=AssertionError('User manages network; no route inspection')))
  return stack
 def test_T20_T23_exact_source_scope_and_eight_immutable_predecessors(self):
  source_revision.validate(self.value,self.reg,self.base)
  self.assertEqual(len(source_revision.revision_chain(self.value)),8)
  old=read(Path(self.prev['engineering_report']['path']))['fingerprint']
  self.assertEqual({p for p in old['files'].keys()|self.fp['files'].keys() if old['files'].get(p)!=self.fp['files'].get(p)},un.FILES)
 def test_T23_authorization_cannot_change_model_clock_or_production(self):
  for key in ('new_B_start','reset_time','change_model','change_production_decisions','increase_limits','assistant_changes_network','route_continuity_claim','node_pin_enforced'):
   self.grant[key]=True;self.sync()
   with self.assertRaises(HarnessError):source_revision.validate(self.value,self.reg,self.base)
   self.grant[key]=False
  self.sync();self.grant['user_instruction']='unrelated';self.sync()
  with self.assertRaises(HarnessError):source_revision.validate(self.value,self.reg,self.base)
 def test_T21_T23_old_attempts_and_other_runs_keep_original_binding(self):
  with self.selection():
   self.assertEqual(un.reference(self.reg,self.admission,attempt={'index':408},run_id=self.boundary['run_id']),self.reg['transport_proxy'])
   self.assertEqual(un.reference(self.reg,self.admission,attempt={'index':409},run_id='other'),self.reg['transport_proxy'])
   self.assertEqual(un.reference(self.reg,{**self.admission,'case_id':'micro-01'}),self.reg['transport_proxy'])
   value=un.reference(self.reg,self.admission,attempt={'index':409},run_id=self.boundary['run_id'])
   self.assertEqual(value['first_actual_call'],410);self.assertFalse(value['route_continuity_claim'])
 def test_T21_T23_no_node_probe_or_network_mutation_and_environment_preserved(self):
  with self.selection(),patch('src.smt_fullfab.harness.experiment.registration',return_value=self.reg):
   value=network.for_admission(self.admission,live=True)
   self.assertEqual(value['mode'],'user_managed_host_network')
   env={'HTTP_PROXY':'http://127.0.0.1:7897','NO_PROXY':'localhost','TASK_SETTING':'test'}
   self.assertEqual(network.apply_environment(env,value),env)
   self.assertIsNot(network.apply_environment(env,value),env)
 def test_T21_T23_tampered_handoff_metadata_rejected(self):
  with self.selection():
   value=un.reference(self.reg,self.admission)
   for k,x in [('first_actual_call',409),('run_id','other'),('assistant_changes_network',True),('route_continuity_claim',True),('environment_policy','force_proxy')]:
    bad=deepcopy(value);bad[k]=x
    with self.assertRaises(HarnessError):network.validate_binding(bad,live=True)
 def test_T20_reject_wrong_source_ancestry(self):
  bad=deepcopy(self.value);bad['previous_source_revision']=self.prev['previous_source_revision']
  with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
if __name__=='__main__':unittest.main()
