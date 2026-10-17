"""Synthetic SMT evidence fixtures only: no real model, simulator or solver calls.
The one-file CSV source boundary is mocked; the trace auditor and chain checks run.
"""
import copy,json,hashlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import src.smt_replay as audit
from src.experiment import object_digest
from src.agents.model_transport import summarize_events

ROOT=Path(__file__).resolve().parents[1];COMMIT='a'*40

def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def sha(b):return hashlib.sha256(b).hexdigest()
def lines(p,rows):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(x)+'\n' for x in rows))

class SmtReplayTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='smt-replay-fixture-',dir=ROOT/'tests');self.root=Path(self.temp.name);self.blobs={}
  self.patches=[patch('src.smt_replay.ROOT',self.root),patch('src.smt_replay._git',side_effect=self.git),patch('src.smt.source_check.verify_source',return_value=[])]
  for p in self.patches:p.start()
  self.build()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def git(self,root,*args):
  if args==('cat-file','-t',COMMIT):return b'commit\n'
  if args==('rev-parse','fixture-freeze^{commit}'):return (COMMIT+'\n').encode()
  if len(args)==2 and args[0]=='show' and args[1].startswith(COMMIT+':'):return self.blobs[args[1].split(':',1)[1]]
  raise ValueError('unknown synthetic Git record')
 def build(self,arm='B',phase='development'):
  self.arm=arm;self.phase=phase;self.run=self.root/'runs'/phase/f'smt701_{arm}_r1';self.run.mkdir(parents=True,exist_ok=True)
  self.data=self.root/'data/smt/SMT2020_LVHM';self.data.mkdir(parents=True,exist_ok=True);(self.data/'fixture.txt').write_text('fixture only\n')
  hashes={'fixture.txt':sha((self.data/'fixture.txt').read_bytes())}
  self.action={'dispatches':[{'machine':0,'lot_ids':['x','y']}],'wait_seconds':0}
  step={'step':1,'family':'G','name':'heat','batch_min':2,'batch_max':3,'batching':True,'processing':{'type':'constant','c':10},'cadence':{'type':'constant','c':10},'cascading':False,'setup':'S','setup_time':3,'sampling_percent':100,'rework_percent':0,'rework_step':'','dedicate_for':None,'transport':{'type':'constant','c':0}}
  lot=lambda x:{'id':x,'name':x,'part':'p','route':'r','priority':10,'pieces':25,'release':0,'due':10,'step':0,'initial':False}
  self.manifest={'version':'smt-adapter-v2','seed':701,'horizon':20,'controlled_machine_ids':[0],'initial_wip':0,'physical_machines':1,'virtual_delay_resources':0,'routes':{'r':[step]},'machines':[{'id':0,'family':'G','group':'production','load':2,'unload':1,'cascading':False}],'lots':[lot('x'),lot('y')],'setups':[],'min_runs':{},'calendars':{},'piece_pm':{},'data_hashes':hashes,'warmup_seconds':0,'outside_policy':'fixture-fixed'}
  self.events=[]
  def emit(t,kind,**kw):self.events.append(dict(seq=len(self.events),time=t,kind=kind,**kw))
  emit(0,'initial',manifest=self.manifest)
  for lid in ['x','y']:emit(0,'release',lot=lid,initial=False);emit(0,'ready',lot=lid,step=1,visit=1)
  emit(0,'action',decision=0,action=self.action)
  emit(0,'dispatch',job=0,machine=0,lots=['x','y'],steps=[1,1],visits=[1,1],owner='controller',setup_before='',setup_after='S',setup_seconds=3,processing_seconds=10,cadence_seconds=10,transport_seconds=0,process_end=16,lot_end=16,machine_ready=16,piece_pm=[],min_runs_left=0,processing_key=['processing',[['x',1,1],['y',1,1]]])
  for lid in ['x','y']:emit(16,'operation_complete',job=0,lot=lid,step=1);emit(16,'lot_complete',lot=lid)
  emit(20,'terminal',metrics={},lot_statuses={'x':'done','y':'done'})
  cs=[{'lot':x,'part':'p','step':1,'priority':10,'due':10,'waiting_seconds':0,'batch_key':['p',1,'heat'],'batch_min':2,'batch_max':3,'setup':'S','setup_seconds':3,'expected_processing_seconds':13} for x in ['x','y']]
  self.state={'schema_version':'smt-state-1','time':0,'horizon':20,'finished':False,'decision_count':0,'machines':[{'machine':0,'family':'G','ready_now':True,'current_setup':'','min_runs_left':0,'candidates':cs}],'current_wip':2,'completed_lots':0,'action_contract':audit.CONTRACT}
  params={'time_limit':1,'priority_weight':100,'waiting_weight':1,'fill_weight':1000,'setup_weight':1}
  mc={'phase':'development' if phase=='development' else 'formal','grant_id':'fixture-model','model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':2}
  cfg={'model':mc,'seed':11,'protocol_version':'fixture-only-v1','window_seconds':20,'controlled_machine_ids':[0],'adapter_version':'smt-adapter-v2','warmup_seconds':0,'outside_policy':'fixture-fixed','max_decisions':1,'responses_per_decision':{'B':2,'C':3},'max_model_calls':{'B':2,'C':3},'solver_budget_seconds':3,'solver_grant_id':'fixture-solver','classical_parameters':params,'fixed_auxiliary_parameters':{**params,'priority_weight':0,'waiting_weight':10},'wall_seconds':10}
  self.cfg=cfg;self.ledger=[{'event':'grant','grant_id':mc['grant_id'],'phase':mc['phase'],'run_prefix':str(self.root/'runs'),'phase_limit':24,'max_calls':24},{'event':'solver_grant','grant_id':cfg['solver_grant_id'],'phase':mc['phase'],'run_prefix':str(self.root/'runs'),'phase_limit':600,'max_seconds':100}]
  solvers=[];models=[];output={**self.action,'rationale':'synthetic test only'}
  if arm in ('A','C','F'):
   pp={**cfg['fixed_auxiliary_parameters' if arm=='F' else 'classical_parameters'],'seed':11}
   solvers=[{'solver_call_id':'solver-fixture','decision':0,'action':self.action,'parameters':pp,'wall_seconds':.1,'solver_status':'OPTIMAL'}]
   if arm=='C':
    solve={'action':'solve','candidate_index':None,**pp,'rationale':'synthetic solve'}
    models.append(self.model(0,solve,[],remaining=3))
   self.ledger.extend([{'event':'solver_reserve','phase':mc['phase'],'grant_id':cfg['solver_grant_id'],'call_id':'solver-fixture','run_id':str(self.run),'requested_seconds':1,'metadata':{'arm':arm,'decision':0,'parameters':pp}},{'event':'finish','call_id':'solver-fixture','status':'success','details':{'wall_seconds':.1}}])
   dump(self.run/'solver_001.json',solvers[0])
   if arm=='C':
    apply={'action':'apply','candidate_index':0,**{k:None for k in audit.PARAMETERS},'rationale':'synthetic apply'}
    models.append(self.model(1,apply,[{'decision':solve,'candidate_index':0,'result':solvers[0]}],remaining=2))
  elif arm=='B':models.append(self.model(0,output,[]))
  domain=audit.audit_trace(self.events);self.assertTrue(domain['valid'],domain)
  self.blobs.update({'src/fixture.py':b'# synthetic source, not an experiment\n','configs/smt-fixture.json':(json.dumps(cfg)+'\n').encode(),'data/smt/source-manifest.json':b'{"fixture_only":true}\n','data/smt/conversion-manifest.json':(json.dumps([{'output':'data/smt/SMT2020_LVHM/fixture.txt','output_sha256':hashes['fixture.txt']}])+'\n').encode()})
  for name,b in self.blobs.items():p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
  snapshot={rel:sha(b) for rel,b in self.blobs.items() if rel.startswith(('src/','configs/'))}
  for rel in snapshot:
   p=self.run/'source_snapshot'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(self.blobs[rel])
  ident={'scenario':701,'arm':arm,'repeat':1,'config_sha256':object_digest(cfg)}
  usage={k:sum(m['usage'][k] for m in models) for k in audit.TOKEN_KEYS}
  record={'family':'smt2020','run_id':self.run.name,'phase':phase,'scenario':701,'arm':arm,'repeat':1,'identity':ident,'code_commit':COMMIT,'source_sha256':snapshot,'protocol_version':cfg['protocol_version'],'config_sha256':object_digest(cfg),'config_path':'configs/smt-fixture.json','data_sha256':object_digest(hashes),'status':'success','validation':domain,'metrics':{'completed_window':True,'simulation_seconds':20,**domain['metrics']},'actions':[{'decision':0,'time':0,'action':self.action,'decision_elapsed_seconds':2.2,'model_calls':len(models),'solver_calls':len(solvers)}],'model_results':models,'solver_results':solvers,'rejected_actions':[],'started_at':'2026-10-09T00:00:00+00:00','finished_at':'2026-10-09T00:00:03+00:00','costs':{'model_calls':len(models),'model_elapsed_seconds':len(models),'usage':usage,'solver_calls':len(solvers),'solver_wall_seconds':.1*len(solvers),'solver_budget_seconds':len(solvers),'end_to_end_seconds':3},**{k:cfg[k] for k in ('adapter_version','window_seconds','controlled_machine_ids','warmup_seconds','outside_policy')}}
  dump(self.run/'result.json',record);dump(self.run/'started.json',record);dump(self.run/'config.json',cfg);dump(self.run/'input_manifest.json',self.manifest);dump(self.run/'state_000.json',self.state);dump(self.run/'action_000.json',self.action);lines(self.run/'trace.jsonl',self.events);lines(self.root/'progress/model_ledger.jsonl',self.ledger)
  if phase!='development':
   matrix=[[s,a,r] for s in (701,702,703) for a in (['F'] if arm=='F' else ['A','B','C']) for r in (1,2,3)]
   self.freeze={'phase':phase,'tag':'fixture-freeze','code_commit':COMMIT,'protocol_version':cfg['protocol_version'],'config_path':'configs/smt-fixture.json','effective_config_sha256':{'1':object_digest(cfg)},'files':{rel:sha(b) for rel,b in self.blobs.items()},'source_data':{'data/smt/SMT2020_LVHM/fixture.txt':hashes['fixture.txt']},'matrix':matrix}
   dump(self.root/'configs/freezes/fixture.json',self.freeze);dump(self.run/'freeze.json',self.freeze)
   record.update(freeze_tag='fixture-freeze',freeze_manifest_sha256=sha((self.run/'freeze.json').read_bytes()));dump(self.run/'result.json',record);dump(self.run/'started.json',record)
 def model(self,attempt,output,history,remaining=None):
  d=self.run/f'model_00_{attempt:02d}';d.mkdir(parents=True,exist_ok=True);cfg=self.cfg['model']
  prompt='SYNTHETIC FIXTURE ONLY\nCurrent state:\n'+json.dumps(self.state)
  if self.arm=='B':prompt+='\nPrior rejected actions at this state:\n'+json.dumps(history)
  else:prompt+='\nThis state history:\n'+json.dumps(history)+'\nRemaining:\n'+json.dumps({'responses_including_this':3-attempt,'solver_seconds':remaining})
  schema='{}\n';fp=sha((prompt+'\n'+schema+'\n'+json.dumps(cfg,sort_keys=True)).encode());usage=dict(zip(audit.TOKEN_KEYS,[20,0,10,0,2]));cid=f'model-fixture-{attempt}'
  events=[{'type':'thread.started','thread_id':cid},{'type':'item.completed','item':{'type':'agent_message','text':json.dumps(output)}},{'type':'turn.completed','usage':usage}]
  saved={'call_id':cid,'config':cfg,'request_fingerprint':fp,'status':'success','returncode':0,'output':output,'duration_seconds':1,**summarize_events(events)}
  lines(d/'events.jsonl',events);dump(d/'final.txt',output);dump(d/'result.json',saved);dump(d/'request.json',{'call_id':cid,'config':cfg,'request_fingerprint':fp});(d/'prompt.txt').write_text(prompt);(d/'schema.json').write_text(schema)
  self.ledger.extend([{'event':'reserve','phase':cfg['phase'],'grant_id':cfg['grant_id'],'call_id':cid,'run_id':str(d)},{'event':'finish','call_id':cid,'status':'success','details':{'usage':usage,'duration_seconds':1}}]);return saved
 def mutate(self,name,change):
  p=self.run/name;v=json.loads(p.read_text());change(v);dump(p,v)
 def rejects(self,needle):
  r=audit.replay(self.run);self.assertFalse(r['audit_pass'],r);self.assertTrue(any(needle in e for e in r['errors']),r['errors'])
 def rewrite_prompt(self,relative,change):
  d=self.run/relative;p=d/'prompt.txt';p.write_text(change(p.read_text()));saved=json.loads((d/'result.json').read_text())
  fingerprint=sha((p.read_text()+'\n'+(d/'schema.json').read_text()+'\n'+json.dumps(saved['config'],sort_keys=True)).encode())
  saved['request_fingerprint']=fingerprint;dump(d/'result.json',saved)
  request=json.loads((d/'request.json').read_text());request['request_fingerprint']=fingerprint;dump(d/'request.json',request)
  self.mutate('result.json',lambda r:r['model_results'].__setitem__(int(relative[-2:]),saved))
 def test_valid_b(self):
  r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertTrue(r['provenance_complete'])
 def test_valid_a_and_c(self):
  for arm in ('A','C'):
   self.build(arm);r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r)
 def test_valid_auxiliary_parameters(self):
  self.build('F');r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertTrue(r['auxiliary'])
 def test_raw_model_chain_tamper(self):
  self.mutate('model_00_00/final.txt',lambda r:r.update(wait_seconds=1));self.rejects('raw model output chain')
 def test_state_tamper_even_if_prompt_rehashed(self):
  self.mutate('state_000.json',lambda r:r['machines'][0]['candidates'][0].update(priority=999))
  altered=json.loads((self.run/'state_000.json').read_text())
  self.rewrite_prompt('model_00_00',lambda text:text.replace(json.dumps(self.state),json.dumps(altered)));self.rejects('preceding trace observations')
 def test_future_observation_forbidden(self):
  self.mutate('state_000.json',lambda r:r.update(future_arrivals=[]));self.rejects('unapproved observable')
 def test_action_trace_link(self):
  self.mutate('action_000.json',lambda r:r.update(wait_seconds=1));self.rejects('action file differs')
 def test_model_tokens_and_elapsed(self):
  self.mutate('result.json',lambda r:r['costs'].update(model_elapsed_seconds=2,usage={**r['costs']['usage'],'input_tokens':0}));self.rejects('aggregate model token')
 def test_ledger_mismatch(self):
  self.ledger[-1]['details']['duration_seconds']=99;lines(self.root/'progress/model_ledger.jsonl',self.ledger);self.rejects('ledger completion')
 def test_failed_attempts_consume_admission(self):
  self.ledger[0]['max_calls']=1
  extra=[]
  for i in range(1):extra += [{'event':'reserve','call_id':'failed','phase':'development','grant_id':'fixture-model','run_id':'other'}, {'event':'finish','call_id':'failed','status':'failed','details':{'usage':None}}]
  self.ledger[2:2]=extra;lines(self.root/'progress/model_ledger.jsonl',self.ledger);self.rejects('attempt budget')
 def test_source_inventory(self):
  (self.data/'extra.txt').write_text('extra');self.rejects('source data file inventory')
 def test_scenario_window_and_repeat_seed(self):
  self.mutate('config.json',lambda r:r.update(seed=99,window_seconds=19));self.rejects('window/horizon')
 def test_missing_snapshot_development_limitation(self):
  import shutil
  shutil.rmtree(self.run/'source_snapshot');r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertFalse(r['provenance_complete']);self.assertTrue(r['warnings'])
 def test_formal_freeze_and_config(self):
  self.build('B','formal-fixture');r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r)
  self.freeze['matrix']=[];dump(self.run/'freeze.json',self.freeze);self.rejects('outside frozen SMT matrix')
 def test_27_matrix_keeps_incomplete(self):
  self.build('B','formal-fixture');dump(self.root/'runs/formal-fixture/smt701_C_r1/started.json',{})
  summary=audit.audit_phase('formal-fixture');self.assertEqual(summary['expected_records'],27);self.assertEqual(len(summary['missing']),26);self.assertEqual({x['state'] for x in summary['missing']},{'not_started','incomplete'});self.assertFalse(summary['coverage_complete'])
 def test_auxiliary_9_is_separate(self):
  self.build('F','aux-fixture');summary=audit.audit_phase('aux-fixture');self.assertEqual(summary['records'],0);self.assertEqual(summary['auxiliary_records'],1);self.assertEqual(summary['expected_records'],9);self.assertEqual(summary['matrix_scope'],'auxiliary')
 def test_damaged_result_is_counted(self):
  (self.run/'result.json').write_text('{');summary=audit.audit_phase('development');self.assertEqual(summary['records'],1);self.assertEqual(summary['passed'],0)
 def test_damaged_auxiliary_is_not_moved_to_core(self):
  self.build('F','aux-fixture');(self.run/'result.json').write_text('{')
  summary=audit.audit_phase('aux-fixture');self.assertEqual(summary['records'],0);self.assertEqual(summary['auxiliary_records'],1)
 def test_c_requires_explicit_model_apply(self):
  self.build('C');self.mutate('model_00_01/result.json',lambda r:r['output'].update(action='solve'));self.rejects('C lacks explicit apply')
 def test_c_solver_parameter_tamper(self):
  self.build('C');self.mutate('solver_001.json',lambda r:r['parameters'].update(seed=99));self.rejects('solver used parameters never selected')
 def test_c_other_candidate_history_rejected_even_after_rehash(self):
  self.build('C');self.rewrite_prompt('model_00_01',lambda text:text.replace('"wall_seconds": 0.1','"wall_seconds": 99'));self.rejects('candidate is not own recorded')
 def test_failed_c_keeps_costs_and_is_not_success(self):
  import shutil
  self.build('C');shutil.rmtree(self.run/'model_00_01');(self.run/'action_000.json').unlink()
  lines(self.run/'trace.jsonl',self.events[:5]);self.ledger=self.ledger[:-2];lines(self.root/'progress/model_ledger.jsonl',self.ledger)
  def fail(r):
   r.update(status='failed',failure_type='missing_explicit_candidate_apply',actions=[],model_results=r['model_results'][:1]);r['costs'].update(model_calls=1,model_elapsed_seconds=1,usage=r['model_results'][0]['usage'])
  self.mutate('result.json',fail)
  r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertFalse(r['domain_valid']);self.assertEqual(r['costs']['solver_calls'],1);self.assertEqual(r['costs']['model_calls'],1)
 def test_failed_solver_attempt_is_preserved(self):
  self.build('A');(self.run/'action_000.json').unlink();lines(self.run/'trace.jsonl',self.events[:5])
  self.mutate('solver_001.json',lambda r:r.update(action=None,status='failed',solver_status='ERROR',error='synthetic failure'))
  failed=json.loads((self.run/'solver_001.json').read_text())
  def fail(r):r.update(status='failed',failure_type='synthetic failure',actions=[],solver_results=[failed])
  self.mutate('result.json',fail);self.ledger[-1]['status']='failed';lines(self.root/'progress/model_ledger.jsonl',self.ledger)
  r=audit.replay(self.run);self.assertTrue(r['audit_pass'],r);self.assertFalse(r['domain_valid']);self.assertEqual(r['costs']['solver_budget_seconds'],1)

if __name__=='__main__':unittest.main()
