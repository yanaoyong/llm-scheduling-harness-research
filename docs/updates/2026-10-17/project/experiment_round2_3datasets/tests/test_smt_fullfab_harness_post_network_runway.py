"""Bounded same-B time allowance and user network handoff; no RPC."""
from pathlib import Path
from copy import deepcopy
import tempfile,unittest
from unittest.mock import patch
from src.smt_fullfab.harness import source_revision,wall_budget as wb,user_managed_network as un,network
from src.smt_fullfab.harness.contracts import ROOT,encode,strict_json,digest,sha_bytes,fingerprint,HarnessError
OUT=ROOT/'artifacts/harness_B_post_network_runway_20261015';LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
def read(p):return strict_json(p.read_bytes())
def ref(p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
class PostNetworkTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.temp=Path(t.name)
  self.reg=read(LIVE/'experiment.json');self.base=read(LIVE/'exception_policy_amendment.json');self.prev=read(LIVE/'source_revision_8.json')
  self.boundary=read(OUT/'boundary.json');self.manifest=read(Path(self.boundary['manifest']['path']));self.admission=self.manifest['admission'];self.fp=fingerprint();self.grant=read(OUT/'authorization.json');self.sync()
 def sync(self):
  (self.temp/'grant.json').write_bytes(encode(self.grant));(self.temp/'test-proof.json').write_bytes(encode({'test_only':True,'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
  (self.temp/'report.json').write_bytes(encode({'test_only':True,'fingerprint':self.fp,'gates':{g:'pass' for g in ['G0','G1','G2','G3','G4']},'test_evidence':ref(self.temp/'test-proof.json')}))
  self.value={'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),'base_amendment_sha256':digest(self.base),'previous_source_revision':ref(LIVE/'source_revision_8.json'),'base_source_sha256':self.prev['active_fingerprint_sha256'],'active_fingerprint_sha256':self.fp['sha256'],'repairs':wb.POST_NETWORK_REPAIR,'boundary':ref(OUT/'boundary.json'),'engineering_report':ref(self.temp/'report.json'),'user_authorization':ref(self.temp/'grant.json')}
 def test_T20_T23_ancestry_and_exact_three_file_scope(self):
  source_revision.validate(self.value,self.reg,self.base);self.assertEqual(len(source_revision.revision_chain(self.value)),9)
  old=read(Path(self.prev['engineering_report']['path']))['fingerprint'];self.assertEqual({p for p in old['files'].keys()|self.fp['files'].keys() if old['files'].get(p)!=self.fp['files'].get(p)},wb.POST_NETWORK_FILES)
 def test_T23_no_reset_model_network_or_arbitrary_extra_allowance(self):
  for key in ['new_B_start','reset_time','reset_costs','change_model','change_production_decisions','change_network']:
   self.grant[key]=True;self.sync()
   with self.assertRaises(HarnessError):source_revision.validate(self.value,self.reg,self.base)
   self.grant[key]=False
  self.sync()
  for key in ['additional_wall_seconds','additional_model_seconds']:
   bad=deepcopy(self.grant);bad[key]+=1
   with self.assertRaises(HarnessError):wb.validate_post_network_grant(bad,self.manifest)
 def markers(self):
  from src.smt_fullfab.harness.source_revision import live_view
  return live_view(Path(self.boundary['manifest']['path']).parent).rows('control_source_revisions')
 def marker(self):return {'revision_sha256':digest(self.value),'boundary':self.value['boundary'],'head_before':self.boundary['head'],'new_model_calls':0,'source_before':self.value['base_source_sha256'],'source_after':self.value['active_fingerprint_sha256']}
 def test_T23_extension_requires_marker_and_keeps_original_clock(self):
  markers=self.markers();before=wb.effective_budget(self.manifest,markers);self.assertEqual(before['limits']['wall_seconds'],72000)
  markers['post-network-time']=self.marker()
  with patch.object(source_revision,'for_amendment',return_value=self.value):after=wb.effective_budget(self.manifest,markers)
  self.assertEqual(after['effective_deadline_epoch'],before['effective_deadline_epoch']+21600)
  self.assertEqual(after['limits'],{**before['limits'],'wall_seconds':93600,'model_seconds':36000})
  for g in ['B3600','combined']:
   self.assertEqual(wb.shared_caps(self.reg,after)[g]['model_seconds']-wb.shared_caps(self.reg,before)[g]['model_seconds'],7200)
 def test_T23_tampered_or_missing_prior_marker_rejected(self):
  markers=self.markers();markers['post-network-time']={**self.marker(),'new_model_calls':1}
  with patch.object(source_revision,'for_amendment',return_value=self.value):
   with self.assertRaises(HarnessError):wb.effective_budget(self.manifest,markers)
  markers['post-network-time']=self.marker();del markers['user-managed-network']
  with self.assertRaises(HarnessError):wb.effective_budget(self.manifest,markers)
 def test_T21_user_handoff_survives_later_revision_without_rewalking_source_or_network(self):
  with patch.object(source_revision,'for_amendment',side_effect=AssertionError('Do not repeat already validated ancestry')),patch('src.smt_fullfab.harness.network_tun.current_route',side_effect=AssertionError('No network inspection')):
   binding=un.reference(self.reg,self.admission);self.assertEqual(binding['first_actual_call'],410)
   self.assertEqual(binding['mode'],'user_managed_host_network')
   self.assertEqual(un.reference(self.reg,self.admission,attempt={'index':408},run_id=self.manifest['run_id']),self.reg['transport_proxy'])
   env={'NO_PROXY':'localhost','HTTPS_PROXY':'http://127.0.0.1:7897'};self.assertEqual(network.apply_environment(env,binding),env)
 def test_T23_preexisting_limits_unaffected_without_marker(self):
  markers=self.markers();value=wb.effective_budget(self.manifest,markers)
  self.assertEqual(value['limits'],self.grant['limits_before']);self.assertEqual(value['original_wall_seconds'],14400)
if __name__=='__main__':unittest.main()
