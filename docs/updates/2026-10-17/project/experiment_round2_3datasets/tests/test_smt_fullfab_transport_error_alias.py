"""Exact closed terminal error, immutable same-run allowance, and no replay."""
from pathlib import Path
from copy import deepcopy
from contextlib import contextmanager
import tempfile, unittest
from unittest.mock import patch
from src.smt_fullfab.harness import source_revision, wall_budget as wb, transport_error_alias as alias
from src.smt_fullfab.harness.recovery import LiveEvidence, failure_kind
from src.smt_fullfab.harness.contracts import ROOT, encode, strict_json, digest, sha_bytes, fingerprint, HarnessError
OUT=ROOT/'artifacts/harness_B_error_alias_runway_20261015'
LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
def read(p): return strict_json(p.read_bytes())
def ref(p): return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}

class AliasTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.temp=Path(temp.name)
  self.reg=read(LIVE/'experiment.json'); self.base=read(LIVE/'exception_policy_amendment.json')
  self.prev=read(LIVE/'source_revision_9.json'); self.boundary=read(OUT/'boundary.json')
  self.manifest=read(Path(self.boundary['manifest']['path'])); self.fp=fingerprint()
  self.grant=read(OUT/'authorization.json'); self.view=LiveEvidence(Path(self.boundary['manifest']['path']).parent)
  self.view.records=self.boundary['records']; self.attempt=self.view.rows('attempts')[self.boundary['closed_terminal_failure_id']]
  self.sync()
 def sync(self):
  (self.temp/'grant.json').write_bytes(encode(self.grant))
  (self.temp/'tests.json').write_bytes(encode({'test_only':True,'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
  (self.temp/'report.json').write_bytes(encode({'test_only':True,'fingerprint':self.fp,'gates':{g:'pass' for g in ['G0','G1','G2','G3','G4']},'test_evidence':ref(self.temp/'tests.json')}))
  self.value={'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),'base_amendment_sha256':digest(self.base),'previous_source_revision':ref(LIVE/'source_revision_9.json'),'base_source_sha256':self.prev['active_fingerprint_sha256'],'active_fingerprint_sha256':self.fp['sha256'],'repairs':alias.REPAIR,'boundary':ref(OUT/'boundary.json'),'engineering_report':ref(self.temp/'report.json'),'user_authorization':ref(self.temp/'grant.json')}
 def marker(self):
  return {'revision_sha256':digest(self.value),'boundary':self.value['boundary'],'head_before':self.boundary['head'],'new_model_calls':0,'source_before':self.value['base_source_sha256'],'source_after':self.value['active_fingerprint_sha256']}
 def markers(self): return self.view.rows('control_source_revisions')
 @contextmanager
 def substitute(self, replacements):
  original=self.view.raw
  with patch.object(self.view,'raw',side_effect=lambda key:replacements[key] if key in replacements else original(key)): yield
 def test_real_562_closed_no_answer_proof(self):
  self.assertEqual(alias.closed_alias_proof(self.view,self.attempt),'connection')
  self.assertEqual(alias.validate_boundary(self.boundary,self.manifest,self.grant),self.attempt)
 def test_alias_requires_immutable_marker(self):
  with self.assertRaises(HarnessError): failure_kind(self.view,self.attempt)
 def test_partial_answer_native_action_and_other_error_rejected(self):
  key=self.attempt['transport']['events_ref']; events=[strict_json(l) for l in self.view.raw(key).splitlines()]
  variants=[events+[{'type':'item.completed','item':{'type':'agent_message','text':'partial'}}],
            events+[{'type':'item.completed','item':{'type':'command_execution','command':'echo'}}],
            [{'type':'turn.failed','error':{'message':alias.MESSAGE+' extra'}}]]
  for value in variants:
   with self.substitute({key:b'\n'.join(encode(e) for e in value)}),self.assertRaises(HarnessError):
    alias.closed_alias_proof(self.view,self.attempt)
  with self.substitute({self.attempt['raw_ref']:b'partial answer'}),self.assertRaises(HarnessError):
   alias.closed_alias_proof(self.view,self.attempt)
 def test_usage_timeout_ownership_loss_and_incomplete_guard_rejected(self):
  for key,value in [('usage',{'total_tokens':1}),('status','started')]:
   bad=deepcopy(self.attempt);bad[key]=value
   with self.assertRaises(HarnessError):alias.closed_alias_proof(self.view,bad)
  bad=deepcopy(self.attempt);bad['transport']['timed_out']=True
  with self.assertRaises(HarnessError):alias.closed_alias_proof(self.view,bad)
  key=self.attempt['transport']['original_guard_files']['receipt.json']; receipt=strict_json(self.view.raw(key))
  for field,value in [('owner_eof',True),('stop_reason','owner_eof'),('guard_error','failed'),('launch_error','failed')]:
   with self.substitute({key:encode({**receipt,field:value})}),self.assertRaises(HarnessError):
    alias.closed_alias_proof(self.view,self.attempt)
 def test_exact_ten_revision_ancestry_and_four_file_scope(self):
  source_revision.validate(self.value,self.reg,self.base)
  self.assertEqual(len(source_revision.revision_chain(self.value)),10)
  old=read(Path(self.prev['engineering_report']['path']))['fingerprint']
  self.assertEqual({p for p in old['files'].keys()|self.fp['files'].keys() if old['files'].get(p)!=self.fp['files'].get(p)},alias.FILES)
  bad={**self.value,'previous_source_revision':ref(LIVE/'source_revision_8.json')}
  with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
 def test_grant_cannot_reset_or_expand_other_resources(self):
  for key in ['new_B_start','reset_time','reset_costs','change_model','change_production_decisions','change_network']:
   with self.assertRaises(HarnessError):alias.validate_grant({**self.grant,key:True},self.manifest)
  for key in ['additional_wall_seconds','additional_storage_bytes','additional_model_seconds','first_actual_call']:
   bad={**self.grant,key:self.grant[key]+1}
   with self.assertRaises(HarnessError):alias.validate_boundary(self.boundary,self.manifest,bad)
  bad=deepcopy(self.grant);bad['limits_after']['model_seconds']+=1
  with self.assertRaises(HarnessError):alias.validate_grant(bad,self.manifest)
 def test_missing_or_changed_failure_binding_rejected(self):
  for key,value in [('closed_terminal_failure_id','different'),('closed_terminal_failure_sha256','0'*64)]:
   with self.assertRaises(HarnessError):alias.validate_boundary(self.boundary,self.manifest,{**self.grant,key:value})
 def test_prior_budget_unchanged_without_alias_marker(self):
  with patch.object(source_revision,'for_amendment',return_value=self.value): budget=wb.effective_budget(self.manifest,self.markers())
  self.assertEqual(budget['limits'],self.grant['limits_before'])
 def test_exact_budget_keeps_original_clock_model_and_all_other_limits(self):
  markers=self.markers();markers[alias.KEY]=self.marker()
  with patch.object(source_revision,'for_amendment',return_value=self.value): after=wb.effective_budget(self.manifest,markers)
  self.assertEqual(after['limits'],self.grant['limits_after'])
  self.assertEqual(after['effective_deadline_epoch'],self.manifest['created_epoch']+115200)
  self.assertEqual(after['model_extension_seconds'],25200)
  self.assertEqual(after['storage_extension_bytes'],2147483648)
 def test_budget_tamper_and_missing_prior_marker_rejected(self):
  markers=self.markers();markers[alias.KEY]={**self.marker(),'new_model_calls':1}
  with patch.object(source_revision,'for_amendment',return_value=self.value),self.assertRaises(HarnessError):wb.effective_budget(self.manifest,markers)
  markers[alias.KEY]=self.marker();del markers['post-network-time']
  with patch.object(source_revision,'for_amendment',return_value=self.value),self.assertRaises(HarnessError):wb.effective_budget(self.manifest,markers)

if __name__=='__main__':unittest.main()
