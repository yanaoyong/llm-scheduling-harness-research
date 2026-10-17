"""Same-checkpoint requalification, cost preservation and hostile proof checks; no RPC."""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil, sqlite3, tempfile, time, unittest
from unittest.mock import patch
from src.smt_fullfab.harness import experiment, source_revision, transport_requalification as tq, recovery
from src.smt_fullfab.harness.contracts import ROOT,HarnessError,digest,encode,fingerprint,sha_bytes,strict_json
from src.smt_fullfab.harness.evaluation import audit_cost
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.store import Store
from src.smt_fullfab.harness.wall_budget import effective_budget

OUT=ROOT/'artifacts/harness_B_transport_requalification_20261015'
LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
RUN=LIVE/'continuations/B3600-no-exception-quota'
PROBES=ROOT/'artifacts/harness_B_connection_recheck_20261015/audit.json'
BOUNDARY=strict_json((OUT/'boundary.json').read_bytes())

def ref(path):return {'path':str(path),'sha256':sha_bytes(path.read_bytes())}
def read(path):return strict_json(path.read_bytes())

class RequalificationTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory(prefix='offline-requalification-');self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
  self.reg=read(LIVE/'experiment.json');self.base=read(LIVE/'exception_policy_amendment.json');self.previous=read(LIVE/'source_revision_6.json')
  self.manifest=read(RUN/'manifest.json');self.fp=fingerprint();self.policy=recovery.policy_for(self.manifest['admission'])
  self.grant={'schema':'harness-control-repair-authorization-v1','user_instruction':'取消异常额度这些限制，你的目标是不浪费的情况下测试推进B',
   'same_run_only':True,'preserve_all_costs_and_results':True,'run_id':BOUNDARY['run_id'],
   **{k:False for k in ('new_B_start','reset_time','change_model','change_production_decisions','increase_limits')}}
  self.value={'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),'base_amendment_sha256':digest(self.base),
   'previous_source_revision':ref(LIVE/'source_revision_6.json'),'base_source_sha256':self.previous['active_fingerprint_sha256'],
   'repairs':tq.REPAIR,'boundary':ref(OUT/'boundary.json')}
  self.sync()
 def sync(self):
  (self.root/'grant.json').write_bytes(encode(self.grant))
  (self.root/'test-proof.json').write_bytes(encode({'test_only':True,'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
  (self.root/'test-report.json').write_bytes(encode({'test_only':True,'fingerprint':self.fp,'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')},'test_evidence':ref(self.root/'test-proof.json')}))
  self.value.update(active_fingerprint_sha256=self.fp['sha256'],engineering_report=ref(self.root/'test-report.json'),user_authorization=ref(self.root/'grant.json'))
 def selected(self):
  stack=ExitStack();original=source_revision.for_amendment
  def selected(reg,base):return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original(reg,base)
  stack.enter_context(patch.object(source_revision,'for_amendment',side_effect=selected))
  stack.enter_context(patch('src.smt_fullfab.harness.transport.call',side_effect=AssertionError('No paid RPC in offline tests')))
  return stack
 def clone(self):
  target=self.root/'run';target.mkdir();(target/'objects').mkdir();(target/'exports').mkdir()
  with sqlite3.connect(f'file:{RUN/"events.sqlite3"}?mode=ro',uri=True) as src,sqlite3.connect(target/'events.sqlite3') as dst:
   src.backup(dst);dst.execute('DELETE FROM records')
   for ns,rows in BOUNDARY['records'].items():dst.executemany('INSERT INTO records VALUES(?,?,?)',[(ns,k,r) for k,r in rows.items()])
   dst.execute('DELETE FROM events WHERE seq > ?',(BOUNDARY['event_count'],));dst.execute('DELETE FROM physical WHERE seq >= ?',(BOUNDARY['physical_count'],))
   dst.execute('UPDATE metadata SET value=? WHERE key=?',(encode(BOUNDARY['head']),'head'))
  for p in (RUN/'objects').iterdir():(target/'objects'/p.name).hardlink_to(p)
  shutil.copy2(RUN/'manifest.json',target/'manifest.json');(self.root/'experiment.json').write_bytes(encode(self.reg))
  return target
 def clone_context(self,target):
  stack=self.selected()
  from src.smt_fullfab.harness.amendment import case_directory
  original_records=experiment.account_records
  def directory(root,case):return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
  def accounts(root):return [('B3600','B3600',BOUNDARY['run_id'],str(target),BOUNDARY['created_epoch'])] if Path(root).resolve()==LIVE.resolve() else original_records(root)
  stack.enter_context(patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory))
  stack.enter_context(patch.object(experiment,'account_records',side_effect=accounts))
  stack.enter_context(patch.object(experiment,'experiment_lock',return_value=nullcontext()))
  from src.smt_fullfab.harness.network import validate_binding
  stack.enter_context(patch('src.smt_fullfab.harness.network.validate_binding',side_effect=lambda binding,**kw:validate_binding(binding,**{**kw,'live':False})))
  return stack
 def test_T20_T23_source_scope_ancestry_and_authorization(self):
  source_revision.validate(self.value,self.reg,self.base);self.assertEqual(len(source_revision.revision_chain(self.value)),7)
  prior=read(Path(self.previous['engineering_report']['path']))['fingerprint']
  self.assertEqual({p for p in prior['files'].keys()|self.fp['files'].keys() if prior['files'].get(p)!=self.fp['files'].get(p)},tq.FILES)
  for key in ('reset_time','new_B_start','change_model','increase_limits','change_production_decisions'):
   self.grant[key]=True;self.sync()
   with self.assertRaisesRegex(HarnessError,'source_revision_grant'):source_revision.validate(self.value,self.reg,self.base)
   self.grant[key]=False
  self.sync();bad=deepcopy(self.value);bad['previous_source_revision']=self.previous['previous_source_revision']
  with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
 def test_T23_original_probe_costs_and_route_proofs_are_recomputed(self):
  rows=tq.diagnostics(ref(PROBES),BOUNDARY,self.manifest,self.reg)
  self.assertEqual(len(rows),2);self.assertEqual(sum(r['usage']['input_tokens']+r['usage']['output_tokens'] for r in rows),8584)
  self.assertEqual(sum(r['duration_seconds'] for r in rows),49.23241616599262)
  self.assertEqual({r['route'] for r in rows},{'system_TUN','explicit_loopback'})
 def test_T21_T23_reject_diagnostic_wrong_checkpoint_model_hash_and_usage(self):
  for key in ('run_id','events_sha256','physical_sha256'):
   b=deepcopy(BOUNDARY);b[key]='other'
   with self.assertRaises(HarnessError):tq.diagnostics(ref(PROBES),b,self.manifest,self.reg)
  reg=deepcopy(self.reg);reg['model']['name']='gpt-6.1-sol'
  with self.assertRaises(HarnessError):tq.diagnostics(ref(PROBES),BOUNDARY,self.manifest,reg)
  bad=read(PROBES);bad['results'][0]['usage']['input_tokens']+=1
  p=self.root/'altered-probe.json';p.write_bytes(encode(bad))
  with self.assertRaises(HarnessError):tq.diagnostics(ref(p),BOUNDARY,self.manifest,self.reg)
  with self.assertRaises(HarnessError):tq.diagnostics({**ref(PROBES),'sha256':'0'*64},BOUNDARY,self.manifest,self.reg)
 def test_T21_closed_failure_proof_pending_and_retained_answer_guard(self):
  v=recovery.LiveEvidence(RUN);self.assertEqual(tq.stopped_boundary(v,BOUNDARY,self.policy)['index'],386)
  for key,val in [('pending_attempts',1),('unprocessed_attempts',0),('run_id','wrong'),('created_epoch',0)]:
   b=deepcopy(BOUNDARY);b[key]=val
   with self.assertRaises(HarnessError):tq.stopped_boundary(v,b,self.policy)
  original=v.get
  def changed(ref):
   a=original(ref)
   if type(a) is dict and a.get('attempt_id')==BOUNDARY['closed_terminal_failure_id']:a={**a,'usage':{'input_tokens':10,'output_tokens':10}}
   return a
  with patch.object(v,'get',side_effect=changed):
   with self.assertRaises(HarnessError):tq.stopped_boundary(v,BOUNDARY,self.policy)
 def test_T15_T20_T21_T23_same_checkpoint_install_resume_accounting_and_no_reset(self):
  target=self.clone()
  with self.clone_context(target):
   before=experiment.cumulative_usage(self.manifest['admission']);budget=effective_budget(self.manifest,source_revision.live_view(target).rows('control_source_revisions'))
   with self.assertRaises(HarnessError):tq.install(self.root,ref(OUT/'boundary.json'),[ref(PROBES)])
   source_revision.install(self.root)
   # A closed burst cannot reopen without a successful independent original-route check.
   probes=tq.diagnostics(ref(PROBES),BOUNDARY,self.manifest,self.reg)
   with patch.object(tq,'diagnostics',return_value=[p for p in probes if p['route']!='system_TUN']):
    with self.assertRaisesRegex(HarnessError,'requalification_health'):tq.install(self.root,ref(OUT/'boundary.json'),[ref(PROBES)])
   early=deepcopy(probes)
   for p in early:p['started_epoch']=0
   with patch.object(tq,'diagnostics',return_value=early):
    with self.assertRaisesRegex(HarnessError,'requalification_health'):tq.install(self.root,ref(OUT/'boundary.json'),[ref(PROBES)])
   row=tq.install(self.root,ref(OUT/'boundary.json'),[ref(PROBES)])
   view=source_revision.live_view(target);source_revision._check_prefix(view,BOUNDARY)
   self.assertEqual(len(view.rows('attempts')),387);self.assertEqual(len(view.rows('commits')),114)
   self.assertEqual(len(view.value['physical']),BOUNDARY['physical_count']);self.assertEqual(effective_budget(self.manifest,view.rows('control_source_revisions')),budget)
   with self.assertRaises(HarnessError):tq.install(self.root,ref(OUT/'boundary.json'),[ref(PROBES)])
   recovered=recovery.validate_recoveries(view);self.assertEqual(len(recovered),7)
   closed=recovered[BOUNDARY['closed_terminal_failure_id']]
   self.assertEqual((closed['request_failure_ordinal'],closed['cohort_failure_ordinal'],closed['usage']),(3,21,None))
   after=experiment.cumulative_usage(self.manifest['admission'])
   for g in ('B3600','combined'):
    self.assertEqual(after[g]['attempts']-before[g]['attempts'],2)
    self.assertEqual(after[g]['tokens']-before[g]['tokens'],8584)
    self.assertAlmostEqual(after[g]['model_seconds']-before[g]['model_seconds'],49.23241616599262)
    self.assertEqual(after[g]['unknown_usage'],before[g]['unknown_usage'])
   self.assertEqual(experiment.resource_status(self.reg,after)['unexempt_unknown_usage']['combined'],0)
   view.value['sealed_epoch']=time.time();cost=audit_cost(view)
   self.assertFalse(cost['valid']);self.assertEqual((cost['actual_attempts'],cost['unknown_usage'],cost['accounted_actual_attempts']),(387,7,389))
   self.assertEqual(cost['accounted_reported_tokens'],14938774+8584);self.assertEqual(cost['diagnostic_wall_seconds_added'],0)
   r=Runtime.resume_run(target)
   try:
    self.assertEqual(r.head['phase'],'OBSERVED');self.assertEqual(r.head['time'],2200);self.assertEqual(r.usage()['actual_model_attempts'],387)
    r.check_admission(actual=True,reserve=100000)
    # Unit exercise of the *next* burst. Existing failures keep real guarded proofs;
    # only the new synthetic failures are stubbed, and no process is launched.
    real_kind=recovery.failure_kind;synthetic=set();last=view.get(BOUNDARY['records']['attempts'][BOUNDARY['closed_terminal_failure_id']])
    def kind(e,a):return 'connection' if a['attempt_id'] in synthetic else real_kind(e,a)
    with patch.object(recovery,'failure_kind',side_effect=kind):
     for n,offset in enumerate((1,62,243),1):
      aid='test-only:next-burst-'+str(n);synthetic.add(aid)
      attempt={**last,'attempt_id':aid,'index':last['index']+n,'reserved_epoch':row['qualified_epoch']+offset,
       'started_epoch':row['qualified_epoch']+offset,'finished_epoch':row['qualified_epoch']+offset+0.1,'test_only':True}
      with r.store.transaction():r.store.record('attempts',aid,attempt)
      scheduled=recovery.schedule_recovery(r,aid)
      if n<=2:
       self.assertEqual(scheduled['request_failure_ordinal'],n)
       self.assertEqual(scheduled['cohort_failure_ordinal'],21+n)
       self.assertEqual(scheduled['not_before_epoch'],attempt['finished_epoch']+(60 if n==1 else 180))
      else:self.assertIsNone(scheduled)
   finally:r.close()
   # Mutating a qualification invalidates every dependent recovery on the next check.
   store=Store(target)
   try:
    altered={**row,'qualified_epoch':0}
    with store.transaction():store.record('transport_requalifications',row['closed_failure_id'],altered,replace=True)
   finally:store.close()
   with self.assertRaises(HarnessError):recovery.validate_recoveries(recovery.LiveEvidence(target))

if __name__=='__main__':unittest.main()
