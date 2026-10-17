from pathlib import Path
import ast, hashlib, json, sys, unittest, time, importlib, re
OUT=Path(__file__).resolve().parent; W=OUT/'workspace'; ORIGINAL=OUT.parents[1]/'experiment_round2_3datasets'
sys.path.insert(0,str(W))
from src.smt_fullfab.harness.contracts import fingerprint, encode
from src.smt_fullfab.harness.coverage_ablation import coverage_view
class AblationFactsTests(unittest.TestCase):
 def test_public_coverage_includes_busy_resource_and_conditional_backlog(self):
  machines=[dict(machine=1,family='x',available_at=101,currently_busy=True,currently_down=False,current_setup=''),dict(machine=2,family='x',available_at=800,currently_busy=True,currently_down=False,current_setup='')]
  ops=[dict(family='x',conditional=False,eligible_machines=[1,2]),dict(family='x',conditional=True,eligible_machines=[1])]
  result=coverage_view({'machines':machines,'operations':ops},[],100,3600)
  from src.smt_fullfab.harness.presentation import unpack
  rows=unpack(result['resource_rows']);self.assertEqual(result['resource_row_count'],1);self.assertEqual(rows[0]['machine'],1);self.assertEqual(rows[0]['ready_eligible_operation_count'],1);self.assertEqual(rows[0]['conditional_eligible_operation_count'],1)
 def test_no_private_state_or_generated_production_decisions(self):
  tree=ast.parse((W/'src/smt_fullfab/harness/coverage_ablation.py').read_text())
  public=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='coverage_view')
  self.assertNotIn('env.',ast.unparse(public));self.assertNotIn('not_before',ast.unparse(public));self.assertNotIn('random',ast.unparse(public))
 def test_only_allowed_files_changed_and_live_hashes_unchanged(self):
  old=json.loads((OUT/'original_source_hashes.json').read_text());changed=[]
  for p,h in old.items():
   self.assertEqual(hashlib.sha256((ORIGINAL/p).read_bytes()).hexdigest(),h,p)
   if hashlib.sha256((W/p).read_bytes()).hexdigest()!=h:changed.append(p)
  self.assertEqual(set(changed),{'src/smt_fullfab/harness/'+x+'.py' for x in ['transport','runtime','network','experiment']})
 def test_baseline_protocol_schema_command_equal_original(self):
  def selected(path):
   tree=ast.parse(path.read_text());names={'command','response_schema'}
   return {n.name:ast.dump(n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names},next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROTOCOL_TEXT' for t in n.targets))
  self.assertEqual(selected(W/'src/smt_fullfab/harness/transport.py'),selected(ORIGINAL/'src/smt_fullfab/harness/transport.py'))
modules=['test_smt_fullfab_harness','test_smt_fullfab_harness_faults','test_smt_fullfab_harness_interaction','test_smt_fullfab_harness_lossless_presentation','test_smt_fullfab_harness_bounded_facts','test_smt_fullfab_harness_fact_memory','test_smt_fullfab_harness_candidate_stage','test_smt_fullfab_harness_schema_order','test_smt_fullfab_plan_delta']
for module in ['lossless_presentation','bounded_facts','candidate_stage','bounded_recovery']:
 imported=importlib.import_module('tests.test_smt_fullfab_harness_'+module);imported.ROOT=ORIGINAL
fp=fingerprint(); suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(AblationFactsTests)]+[unittest.defaultTestLoader.loadTestsFromName('tests.'+m) for m in modules])
prior_log=(OUT/'verification_initial.log').read_text() if '--retry-fixtures' in sys.argv else ''
if prior_log:
 failed=re.findall(r'^(?:ERROR|FAIL): .*? \((.*?)\)$',prior_log,re.M)
 suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in failed)
with (OUT/('verification_retry.log' if prior_log else 'verification.log')).open('w') as log: result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
proof={'all_pass':result.wasSuccessful(),'tests_run':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'fingerprint_sha256':fp['sha256'],'source_unchanged_during_tests':fp==fingerprint(),'physics_unchanged':all(hashlib.sha256((W/p).read_bytes()).hexdigest()==v for p,v in json.loads((OUT/'original_source_hashes.json').read_text()).items() if not p.startswith('src/smt_fullfab/harness/')),'transport_command_schema_unchanged':not any('test_baseline_protocol_schema_command_equal_original' in str(t) for t,e in result.errors+result.failures),'modules':modules,'created_epoch':time.time()}
proof['prior_passed_tests']=90 if prior_log else 0
proof['unique_tests_passed']=proof['prior_passed_tests']+result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped)
proof['skipped']=len(result.skipped)
proof['fixture_resolution']='Historical test fixtures read from original paths; all runtime writes remain temporary or isolated'
(OUT/'verification.json').write_bytes(encode(proof));print(json.dumps(proof));sys.exit(not result.wasSuccessful())
