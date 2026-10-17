"""Revised same-input acceptance: cumulative cost, quota and supervised route."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from contextlib import nullcontext
import json,os,sys,tempfile,unittest,zlib,shutil,time,socket
from unittest.mock import patch
from src.smt_fullfab.harness.contracts import ROOT,HarnessError,encode,digest,sha_bytes,strict_json,fingerprint
from src.smt_fullfab.harness.model_switch import carried_costs,carried_recovery_count,validate_registration
from src.smt_fullfab.harness.network import validate_binding,apply_environment,process_identity
from src.smt_fullfab.harness.recovery import schedule_recovery,LiveEvidence
from src.smt_fullfab.harness.experiment import registration
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.p5 import admission_for
from src.smt_fullfab.harness.transport import call
from src.smt_fullfab.harness.evaluation import seal_evidence,Evidence,audit_cost


class RevisedAcceptanceTests(unittest.TestCase):
 def setUp(self):
  self.out=ROOT/'artifacts/harness_sol_revised_acceptance';self.reg=strict_json((self.out/'registration_draft.json').read_bytes())
  self.tmp=tempfile.TemporaryDirectory(prefix='offline-revised-acceptance-');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
 def ref(self,p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}
 def test_T23_all_59_runs_and_seven_recoveries_are_carried_once(self):
  u,b,ids=carried_costs(self.reg)
  self.assertEqual((len(ids),b,u['combined']['attempts'],u['combined']['tokens'],u['combined']['unknown_usage']),(59,0,245,8654350,18))
  self.assertEqual(carried_recovery_count(self.reg),7)
  self.assertEqual(validate_registration(self.reg,Path(self.reg['experiment_directory'])),self.reg)
 def test_T23_omitted_failures_quota_resets_and_clock_resets_rejected(self):
  for mode in ('count','omitted','duplicate'):
   x=strict_json(Path(self.reg['recovery_carry']['path']).read_bytes())
   if mode=='count':x['total_count']=0
   if mode=='omitted':x['recoveries'].pop()
   if mode=='duplicate':x['recoveries'].append(deepcopy(x['recoveries'][0]))
   p=self.root/(mode+'.json');p.write_bytes(encode(x));reg=deepcopy(self.reg);reg['recovery_carry']=self.ref(p)
   with self.subTest(mode=mode),self.assertRaises(HarnessError):carried_recovery_count(reg)
  x=strict_json(Path(self.reg['prior_cost_evidence']['path']).read_bytes());x['runs'][-1]['accounting_end_epoch']=x['runs'][-1]['accounting_end_epoch']-1
  p=self.root/'clock.json';p.write_bytes(encode(x));reg=deepcopy(self.reg);reg['prior_cost_evidence']=self.ref(p)
  with self.assertRaisesRegex(HarnessError,'carry_closed'):carried_costs(reg)
 def test_T22_next_exception_is_eighth_without_resubmitting_anything(self):
  source=ROOT/'artifacts/harness_p5_sol_release/runs/micro-20';v=LiveEvidence(source);aid=next(iter(v.rows('attempts')));saved={}
  fake=SimpleNamespace(path=source,transaction=lambda:nullcontext(),record=lambda ns,k,row:saved.update({k:row}),event=lambda *args:None)
  r=SimpleNamespace(config=v.manifest['config'],manifest={'admission':{'fixture':True}},store=fake)
  def registered(adm):return self.reg if adm=={'fixture':True} else registration(adm)
  # This tests the empty newly registered cohort, not later live experiment rows.
  from src.smt_fullfab.harness.recovery import cohort_recoveries
  from src.smt_fullfab.harness.amendment import amendment_for
  def fresh_cohort(reg):return {} if reg==self.reg else cohort_recoveries(reg)
  # The draft predates the later count amendment in the live output directory.
  def prerevision(reg):return None if reg==self.reg else amendment_for(reg)
  with patch('src.smt_fullfab.harness.experiment.registration',side_effect=registered),patch('src.smt_fullfab.harness.recovery.cohort_recoveries',side_effect=fresh_cohort),patch('src.smt_fullfab.harness.amendment.amendment_for',side_effect=prerevision):row=schedule_recovery(r,aid)
  self.assertEqual(row['cohort_failure_ordinal'],8);self.assertEqual(row['request_failure_ordinal'],1)
  self.assertEqual(row['not_before_epoch'],v.rows('attempts')[aid]['finished_epoch']+60)
  self.assertEqual(row['attempt_sha256'],digest(v.rows('attempts')[aid]));self.assertEqual(len(saved),1)
 def test_T20_route_auth_and_local_binding_tampering_rejected(self):
  net=self.reg['transport_proxy'];validate_binding(net)
  for url in ('http://example.com:60903','http://127.0.0.1:99999','http://user:secret@127.0.0.1:60903','http://127.0.0.1:60903/path'):
   with self.subTest(url=url),self.assertRaises(HarnessError):validate_binding({**net,'url':url})
  x=strict_json(Path(net['binding']['path']).read_bytes());x['allow_lan']=True
  p=self.root/'binding.json';p.write_bytes(encode(x))
  with self.assertRaises(HarnessError):validate_binding({'url':net['url'],'binding':self.ref(p)})
  # Test identity rejection at the recorded valid lease time, independently of expiry.
  recorded=strict_json(Path(net['binding']['path']).read_bytes())
  with patch('src.smt_fullfab.harness.network.time.time',return_value=recorded['started_epoch']+1),patch('src.smt_fullfab.harness.network.process_identity',return_value='replaced process'):
   with self.assertRaisesRegex(HarnessError,'network_unavailable'):validate_binding(net,live=True)
  env=apply_environment({'NO_PROXY':'chatgpt.com','http_proxy':'http://unregistered','ALL_PROXY':'http://unregistered','OTHER':'keep'},net)
  self.assertNotIn('NO_PROXY',env);self.assertNotIn('http_proxy',env);self.assertEqual(env['OTHER'],'keep')
  self.assertEqual({env[k] for k in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')},{net['url']})
 def test_T20_model_and_business_gate_cannot_change_with_route_revision(self):
  for field in ('model','p95','retry','route'):
   reg=deepcopy(self.reg)
   if field=='model':reg['model']['name']='gpt-6-astra'
   if field=='p95':reg['micro_metrics']['p95_max']=7
   if field=='retry':reg['recovery_policy']['max_retries_per_request']=5
   if field=='route':reg['transport_proxy']['url']='http://127.0.0.1:1'
   with self.subTest(field=field),self.assertRaises(HarnessError):validate_registration(reg,Path(reg['experiment_directory']))
 def test_T23_local_guard_captures_bound_route_and_scrubs_proxy_bypass(self):
  reg=deepcopy(self.reg);source=Path(reg['experiment_directory']);root=self.root/'cohort';root.mkdir()
  # Own a fresh loopback listener for this local child-process fixture. A historical
  # proxy lease must not determine whether today's offline transport test can run.
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(32);self.addCleanup(listener.close)
  url='http://127.0.0.1:'+str(listener.getsockname()[1])
  binding=strict_json(Path(reg['transport_proxy']['binding']['path']).read_bytes())
  binding.update(proxy_url=url,started_epoch=time.time(),lease_end_epoch=time.time()+600,
                 pid=os.getpid(),process_identity=process_identity(os.getpid()),binary=sys.executable,
                 binary_sha256=sha_bytes(Path(sys.executable).read_bytes()),offline_fixture_only=True)
  p=root/'local-binding.json';p.write_bytes(encode(binding));reg['transport_proxy']={'url':url,'binding':self.ref(p)}
  grant=strict_json(Path(reg['authorization']['path']).read_bytes());grant['transport_proxy']=reg['transport_proxy']
  p=root/'local-authorization.json';p.write_bytes(encode(grant));reg['authorization']=self.ref(p)
  validate_binding(reg['transport_proxy'],live=True)
  expired={**binding,'started_epoch':time.time()-10,'lease_end_epoch':time.time()-1}
  p=root/'expired-binding.json';p.write_bytes(encode(expired))
  with self.assertRaisesRegex(HarnessError,'network_unavailable'):validate_binding({'url':url,'binding':self.ref(p)},live=True)
  for p in source.glob('*.config.json'):shutil.copy2(p,root/p.name)
  for p in source.glob('*.initial.json.z'):shutil.copy2(p,root/p.name)
  proof=root/'test-only-gates.json';fp=fingerprint();proof.write_bytes(encode({'fingerprint_sha256':fp['sha256'],'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')},'test_only':True}))
  reg.update(experiment_directory=str(root),fingerprint_sha256=fp['sha256'],engineering_report=str(proof),engineering_report_sha256=sha_bytes(proof.read_bytes()),cli_binary=sys.executable,cli_sha256=sha_bytes(Path(sys.executable).read_bytes()))
  (root/'experiment.json').write_bytes(encode(reg));cfg=strict_json((root/'micro-20.config.json').read_bytes());initial=strict_json(zlib.decompress((root/'micro-20.initial.json.z').read_bytes()))
  r=Runtime.start_new(root/'runs/micro-20',cfg,experiment_id='offline-no-remote-model',mode='model',initial=initial,admission=admission_for(root,'micro-20'))
  try:
   action={'tool':'write_notes','context_ref':r.head['context_ref'],'request_id':'local-transport-fixture','text':'','expected_version':0}
   def command(directory,**kwargs):
    program="import os,json;from pathlib import Path;action="+repr(action)+";action['text']=json.dumps({k:os.environ.get(k) for k in ['HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','all_proxy']},sort_keys=True);Path("+repr(str(directory/'final.txt'))+").write_text(json.dumps({'action':action}));print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'output_tokens':10,'cached_input_tokens':0}}))"
    return [sys.executable,'-c',program]
   with patch('src.smt_fullfab.harness.transport.command',side_effect=command),patch.dict(os.environ,{'NO_PROXY':'chatgpt.com','all_proxy':'http://unregistered'}):result=call(r)
   self.assertEqual(result['status'],'ok');a=r.store.rows('attempts')[0][1];nref=a['transport']['original_input_files']['network.json']
   self.assertEqual(r.store.get(nref),reg['transport_proxy']);seen=json.loads(r.store.read('notes','current')['text'])
   self.assertEqual(seen['HTTPS_PROXY'],reg['transport_proxy']['url']);self.assertIsNone(seen['NO_PROXY']);self.assertIsNone(seen['all_proxy'])
   r.stop('offline_fixture_complete');sha=seal_evidence(r);ev=Evidence(r.store.path,sha)
   self.assertEqual(audit_cost(ev)['actual_attempts'],1)
   get=ev.get
   with patch.object(ev,'get',side_effect=lambda ref:{'url':'changed'} if ref==nref else get(ref)):
    with self.assertRaisesRegex(HarnessError,'network_source'):audit_cost(ev)
  finally:r.close()

if __name__=='__main__':unittest.main()
