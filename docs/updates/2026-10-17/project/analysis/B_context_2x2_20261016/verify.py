from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import ast, hashlib, json, sys, unittest, time, importlib, tempfile, zlib, re
OUT=Path(__file__).resolve().parent; W=OUT/'workspace'; ORIGINAL=OUT.parents[1]/'experiment_round2_3datasets'
sys.path.insert(0,str(W))
from src.smt_fullfab.harness.contracts import fingerprint,encode,strict_json,digest,default_config,HarnessError
from src.smt_fullfab.harness.context_ablation import *
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness import transport
from src.smt_fullfab.harness.presentation import unpack
class ContextTests(unittest.TestCase):
 def model(self,variant): return SimpleNamespace(manifest={'admission':{'experiment_kind':SCHEMA,'case_id':'singleton_2403__'+variant}})
 def test_treatment_matrix_and_baseline_schema(self):
  for v,f in zip(VARIANTS,[(False,False),(True,False),(False,True),(True,True)]):self.assertEqual(flags(self.model(v)),f)
  schema=transport.response_schema('B',comparison_context_refs=[],candidate_refs=[],has_open_draft=False)
  self.assertEqual(adapt_schema(self.model('baseline'),schema),schema)
  sys.path.insert(0,str(OUT/"test_dependencies"))
  import jsonschema
  try:
   for v in VARIANTS:jsonschema.Draft202012Validator.check_schema(adapt_schema(self.model(v),schema))
  finally:sys.path.remove(str(OUT/"test_dependencies"))
  self.assertEqual(adapt_schema(self.model('baseline'),schema),schema)
 def test_exact_extended_filters_pages_projection_types_stale_cursor(self):
  from src.smt_fullfab.harness.facts import build_facts
  rows=[{'machine':i,'n':i,'members':[i%5],'nullable':None,'flag':False} for i in range(1200)]
  rows[2].pop('nullable');rows[3]['n']=False
  facts=build_facts({'machines':rows,'operations':[]},{'tasks':[],'holds':[]});r=ExtendedFactReader('c1',facts)
  where=[{'field':'n','op':'ge','value':2},{'field':'n','op':'lt','value':1190},{'field':'members','op':'contains_any','value':[1,3]},{'field':'nullable','op':'eq','value':None}]
  expected=[x for x in rows if type(x['n']) is int and 2<=x['n']<1190 and set(x['members'])&{1,3} and 'nullable' in x]
  got=[];cursor=None;saved=None
  while True:
   result=r.read({'kind':'machines','cursor':cursor,'count':17,'where':where,'fields':['machine','nullable','missing']})
   self.assertEqual(result['catalog_total'],1200);self.assertEqual(result['matching_total'],len(expected))
   self.assertTrue(all(x['absent_fields']==['missing'] and x['value']['nullable'] is None for x in result['entities']))
   got += [x['value']['machine'] for x in result['entities']];cursor=result['next_cursor'];saved=saved or cursor
   if cursor is None:break
  self.assertEqual(got,[x['machine'] for x in expected])
  for rr,ww in [(ExtendedFactReader('c2',facts),where),(r,where[:-1])]:
   with self.assertRaisesRegex(HarnessError,'stale_cursor'):rr.read({'kind':'machines','cursor':saved,'count':17,'where':ww})
  result=r.read({'kind':'machines','cursor':None,'count':512,'where':[{'field':'n','op':'in','value':[False,2]}]})
  self.assertEqual([x['id'] for x in result['entities']],['2','3'])
  for p in [{'field':'n','op':'lt','value':True},{'field':'n','op':'rank','value':2},{'field':'private','op':'ge','value':2}]:
   with self.assertRaises(HarnessError):r.read({'kind':'machines','cursor':None,'count':10,'where':[p]})
  with self.assertRaises(HarnessError):FactReader('c1',facts).read({'kind':'machines','cursor':None,'count':10,'where':where})
 def test_projection_preserves_business_values_and_original_metadata(self):
  from src.smt_fullfab.harness.facts import build_facts
  f=build_facts({'machines':[{'machine':i,'x':None,'flag':False,'n':0} for i in range(200)],'operations':[]},{'tasks':[],'holds':[]})
  r=FactReader('c',f);q=r.read({'kind':'machines','cursor':r.cursor('machines',0),'count':200,'fields':['machine','x','flag','n','missing']})
  raw={'status':'ok','context_ref':'c','results':[q]};before=deepcopy(raw);view=projected(raw,'public:x')
  self.assertEqual(raw,before)
  for a,b in zip(raw['results'][0]['entities'],view['results'][0]['entities']):
   for k in ['kind','id','source_index','value','projection_fields','absent_fields']:self.assertEqual(a[k],b[k])
  self.assertLess(len(encode(pack(view))),len(encode(pack(raw))))
 def test_offloaded_restore_is_an_actual_tool_read_and_run_bounded(self):
  with tempfile.TemporaryDirectory() as d:
   r=Runtime.start_new(Path(d)/'run',default_config(seconds=60),experiment_id='offline-context-recovery')
   r.manifest['admission']=self.model('targeted_recovery').manifest['admission']
   try:
    raw={'status':'ok','context_ref':'old-context','results':[{'entities':[{'kind':'operations','id':str(i),'value':{'operation_id':str(i),'payload':str(i)*2500,'nullable':None,'flag':False},'entity_revision':str(i)} for i in range(80)]}]}
    with r.store.transaction():ref=r._publish(raw,'test-original')
    presented=presentation(r,raw,ref);self.assertTrue(presented['offloaded']);self.assertFalse(presented['inline_complete'])
    self.assertEqual(presentation(r,raw,ref)['locator_index_ref'],presented['locator_index_ref'])
    action={'tool':'read_artifact','artifact_ref':presented['locator_index_ref'],'path':['locators'],'format':'page','offset':70,'count':2}
    indices=r.record_output(action)['value'];self.assertEqual([x['id'] for x in indices],['70','71'])
    action={'tool':'read_artifact','artifact_ref':ref,'lookups':[{'path':x['path'],'fields':['operation_id','nullable','flag','absent']} for x in indices]}
    got=r.record_output(action);self.assertEqual(got['results'][1]['value'],{'operation_id':'71','nullable':None,'flag':False});self.assertEqual(got['results'][0]['absent_fields'],['absent'])
    self.assertEqual(r.store.rows('commits'),[]);self.assertEqual(r.store.get(r.store.read('public',ref)['object_ref']),raw)
    self.assertGreaterEqual(len(r.store.rows('attempts')),2)
    bad=deepcopy(action);bad['artifact_ref']='private:unknown';self.assertEqual(r.record_output(bad)['status'],'rejected')
    action['lookups']=[{'path':['results',-1],'fields':None},{'path':['not_here'],'fields':None}]
    got=r.record_output(action);self.assertTrue(all(x['status']=='rejected' for x in got['results']))
    r.manifest['admission']=self.model('baseline').manifest['admission'];self.assertEqual(r.record_output(action)['status'],'rejected')
   finally:r.close()
 def test_only_allowed_sources_changed_physics_and_memory_unchanged(self):
  manifest=json.loads((OUT/'source_baseline_manifest.json').read_text());allowed={'src/smt_fullfab/harness/'+x+'.py' for x in ['transport','runtime','network','experiment','contracts']}
  changes=[]
  for p,h in manifest['files'].items():
   self.assertEqual(hashlib.sha256((Path(manifest['source'])/p).read_bytes()).hexdigest(),h,p)
   if hashlib.sha256((W/p).read_bytes()).hexdigest()!=h:changes.append(p)
  self.assertEqual(set(changes),allowed)
 def test_base_protocol_schema_command_equal_previous_isolated(self):
  def selected(path):
   tree=ast.parse(path.read_text())
   return {n.name:ast.dump(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'command','response_schema'}},next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROTOCOL_TEXT' for t in n.targets))
  source=Path(json.loads((OUT/'source_baseline_manifest.json').read_text())['source'])
  self.assertEqual(selected(W/'src/smt_fullfab/harness/transport.py'),selected(source/'src/smt_fullfab/harness/transport.py'))
 def test_all_four_initial_prompts_fit_same_state_and_baseline_no_extensions(self):
  initial=strict_json(zlib.decompress((OUT/'singleton_2403__baseline.initial.json.z').read_bytes()));config=strict_json((OUT/'singleton_2403__baseline.config.json').read_bytes());expected=strict_json((OUT/'singleton_2403.public_expected.json').read_bytes())
  observations=[]
  with tempfile.TemporaryDirectory() as d:
   for v in VARIANTS:
    r=Runtime.start_new(Path(d)/v,config,experiment_id='offline-four-variant-preflight',initial=initial)
    r.manifest['admission']=self.model(v).manifest['admission']
    try:
     full=r.store.read('contexts',r.head['context_ref']);observations.append((digest(full['problem']),digest(full['base_plan']),full['trigger']))
     self.assertEqual(observations[-1],(expected['problem_sha256'],expected['base_plan_sha256'],expected['trigger']))
     text=transport.prompt(r);self.assertLessEqual(len(text),120000);frame=strict_json(text[text.index('\n{')+1:]);context=frame['context']
     self.assertEqual('query_extensions' in context,v in ('filter_projection','combined'));self.assertEqual('exact_recovery' in context,v in ('targeted_recovery','combined'))
     self.assertNotIn('factory_coverage',context);self.assertNotIn('execution_efficiency',context)
    finally:r.close()
  self.assertTrue(all(o==observations[0] for o in observations))
modules=['test_smt_fullfab_harness','test_smt_fullfab_harness_faults','test_smt_fullfab_harness_interaction','test_smt_fullfab_harness_lossless_presentation','test_smt_fullfab_harness_bounded_facts','test_smt_fullfab_harness_fact_memory','test_smt_fullfab_harness_candidate_stage','test_smt_fullfab_harness_schema_order','test_smt_fullfab_plan_delta']
for module in ['lossless_presentation','bounded_facts','candidate_stage','bounded_recovery']:
 imported=importlib.import_module('tests.test_smt_fullfab_harness_'+module);imported.ROOT=ORIGINAL
fp=fingerprint();suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(ContextTests)]+[unittest.defaultTestLoader.loadTestsFromName('tests.'+m) for m in modules])
prior=None
if '--retry-failures' in sys.argv:
 prior=json.loads((OUT/'verification.json').read_text())
 failures=re.findall(r'^(?:ERROR|FAIL): .*? \((.*?)\)$',(OUT/'verification.log').read_text(),re.M)
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in failures)
with (OUT/('verification_retry.log' if prior else 'verification.log')).open('w') as log: result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
manifest=json.loads((OUT/'source_baseline_manifest.json').read_text())
proof={'all_pass':result.wasSuccessful(),'tests_run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),'fingerprint_sha256':fp['sha256'],'source_unchanged_during_tests':fp==fingerprint(),'physics_unchanged':all(hashlib.sha256((W/p).read_bytes()).hexdigest()==v for p,v in manifest['files'].items() if not p.startswith('src/smt_fullfab/harness/')),'base_prompt_command_schema_unchanged':not any('test_base_protocol_schema_command_equal_previous_isolated' in str(t) for t,e in result.errors+result.failures),'modules':modules,'created_epoch':time.time(),'fixture_resolution':'Read-only historical artifact fixtures; runtime writes use temporary or new isolated directories only'}
if prior:
 proof['prior_tests_run']=prior['tests_run'];proof['prior_passed']=prior['tests_run']-prior['errors']-prior['failures']-prior['skipped'];proof['unique_passed']=proof['prior_passed']+result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped)
 proof['all_pass']=proof['all_pass'] and fp['sha256']==prior['fingerprint_sha256'] and result.testsRun==prior['errors']+prior['failures']
 (OUT/'verification_initial.json').write_bytes(encode(prior))
(OUT/'verification.json').write_bytes(encode(proof));print(json.dumps(proof));sys.exit(not result.wasSuccessful())
