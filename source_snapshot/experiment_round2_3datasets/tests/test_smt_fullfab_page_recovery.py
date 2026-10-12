"""Synthetic immutable recovery fixtures; no model/solver/simulation calls."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.controller_audit import digest, _record_digest
from src.smt_fullfab.controller_recovery import (ROOT, prepare_B_recovery,
    _verify_cold_checkpoint, _inventory)
from tests.test_smt_fullfab_controller_audit import fixture, paging_v2_fixture, write


def make_fixture(root, *, page_count=3, outputs=None):
    root = root.resolve()
    run, ledger = fixture(root)
    new_run = root / 'runs/smt_fullfab_stage2/B_fixture'
    new_run.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(run, new_run); run = new_run
    approval = json.loads((ROOT / 'configs/smt_fullfab/stage2_probe.approved.json').read_text())
    waiver = json.loads((ROOT / 'configs/smt_fullfab/research_limit_waiver.approved.json').read_text())
    cfg = {'arm':'B', 'run_id':'B_fixture', 'seconds':3600, 'seed':1901, 'max_calls':None,
           'budget_id':approval['budget_id'], 'amendment_id':waiver['amendment_id'],
           'wall_seconds':7200, 'max_log_bytes':1000000, 'solver_budget_seconds':0,
           'page_chars':45000, 'plan_seconds':14400, 'lookahead_depth':2, 'period_seconds':1800}
    write(run / 'config.json', cfg)
    write(run / 'claim.json', {'pid':999999999, 'identity':digest(cfg)})
    registration = {'run_id':str(run), 'arm':'B', 'scenario':1901, 'window_seconds':3600,
        'solver_seconds':0, 'wall_seconds':7200, 'max_log_bytes':1000000,
        'amendment_id':waiver['amendment_id'], 'budget_id':approval['budget_id'],
        'phase':'stage2_research', 'formal':False}
    registration['registration_id'] = _record_digest(registration)
    write(run / 'resource_registration.json', registration)
    problem = json.loads((run / 'problem_000.json').read_text())
    problem['horizon_end'] = 3600
    first = problem['operations'][0]
    problem['operations'] = [dict(copy.deepcopy(first), operation_id=f'lot{i}:1:1', lot_id=f'lot{i}') for i in range(page_count)]
    # Build the compact dictionaries independently and split one family.
    manifest, initial_pages = paging_v2_fixture(dict(problem, operations=[problem['operations'][0]]))
    manifest.update(page_count=page_count, operation_count=page_count, observation_end=3600,
                    source_problem_sha256=_record_digest(problem))
    pages = []
    for index in range(page_count):
        page = copy.deepcopy(initial_pages[0]); row = page[0]['operations'][0]
        row[0], row[8], row[9] = f'lot{index}:1:1', index, f'lot{index}'
        pages.append(page)
        write(run / f'page_000_{index:02d}.json', page)
    write(run / 'page_manifest_000.json', manifest); write(run / 'problem_000.json', problem)
    for path in list(run.glob('patch_*.json')) + list(run.glob('raw_plan_*.json')) + list(run.glob('plan_commits.jsonl')):
        path.unlink()
    for directory in run.glob('model_*'):
        if directory.is_dir(): shutil.rmtree(directory)
    source = (ROOT / 'src/smt_fullfab/controller.py').read_text()
    schema = next(ast.literal_eval(node.value) for node in ast.parse(source).body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='B_SCHEMA' for t in node.targets))
    frozen_controller = run / 'source_snapshot/src/smt_fullfab/controller.py'
    frozen_controller.write_text("B_PROMPT = 'Synthetic unit fixture, not a model call.'\nC_PROMPT = 'Synthetic C fixture; no call.'\nB_SCHEMA = " + repr(schema) + '\n')
    provenance = json.loads((run / 'provenance.json').read_text())
    provenance['source_sha256']['src/smt_fullfab/controller.py'] = hashlib.sha256(frozen_controller.read_bytes()).hexdigest()
    write(run / 'provenance.json', provenance)
    trace = [{'kind':'initial', 'time':0, 'manifest':{'seed':1901,'horizon':3600,'controlled_machine_ids':[0]}}]
    write(run / 'trace.jsonl', trace, lines=True)
    state = {'t':0, 'finished':False, 'plan':None, 'executed_tasks':[], 'plan_versions':[], 'trace':trace}
    write(run / 'checkpoint.json', {'schema':'smt-fullfab-snapshot-1','state':state,'state_sha256':digest(state)})
    rows = [{'event':'approval','approval':approval}]
    rows.append({'event':'research_limit_waiver','amendment':waiver,'original_approval_sha256':_record_digest(approval),
                 'prefix_record_count':len(rows),'prior_ledger_sha256':_record_digest(rows)})
    rows.append({'event':'stage_run_registered','registration':registration})
    if outputs is None:
        outputs = [{'tasks':[{'machine':0,'operations':['lot0:1:1'],'start':0,'sequence':0}],
                    'holds':[],'commit':False,'reason':'chosen by synthetic model'}, None]
    links, staged, call_ids = [], [], []
    context = {'purpose':'B','arm':'B','scenario':1901,'window_seconds':3600}
    for index, output in enumerate(outputs):
        directory = run / f'model_{index:03d}'; directory.mkdir()
        metadata = {**manifest,'page_index':index,'last_page':index==page_count-1,'remaining_model_responses':None}
        prompt = 'Synthetic unit fixture, not a model call.\nSCHEMA_AND_LIMITS\n' + json.dumps(metadata) + '\nPAGE\n' + json.dumps(pages[index]) + '\nYOUR_PRIOR_PREDECESSOR_CHOICES\n' + json.dumps(staged)
        (directory / 'prompt.txt').write_text(prompt); write(directory / 'schema.json', schema)
        config = {'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,
                  'grant_id':approval['budget_id'],'phase':'stage2_research','authorization_context':context}
        fingerprint = hashlib.sha256((prompt+'\n'+json.dumps(schema,ensure_ascii=False,indent=2)+'\n'+'\n'+json.dumps(config,sort_keys=True)).encode()).hexdigest()
        (directory / 'attempt.claim').write_text(fingerprint+'\n')
        cid = f'synthetic-call-{index}'; call_ids.append(cid)
        request = {'call_id':cid,'config':config,'request_fingerprint':fingerprint}
        usage = {'input_tokens':11,'output_tokens':7,'cached_input_tokens':0,'cache_write_input_tokens':None,'reasoning_output_tokens':None}
        if output is None:
            usage = {key:None for key in usage}
        status = 'success' if output is not None else 'timeout'
        model = {**request,'status':status,'output':output,'usage':usage,'duration_seconds':1,
                 'native_tool_events':[],'timed_out':output is None,'cost_usd':None,'returncode':0 if output is not None else -15,
                 'failure_reason':None if output is not None else 'model_call_timeout'}
        write(directory / 'request.json', request); write(directory / 'result.json', model)
        write(directory / 'events.jsonl', [{'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':7,'cached_input_tokens':0}}] if output is not None else [], lines=True)
        if output is not None:
            write(directory / 'final.txt', output); write(run / f'patch_000_{index:02d}.json', output)
            staged += output['tasks']
        links.append({'model_index':index,'call_id':cid,'plan_index':0,'arm':'B','stage':'B_page','page_index':index,
                      'input_problem_sha256':digest(problem),'response_sha256':digest(output),'status':status})
        account = {'attempts':index,'reported_input_output_tokens':18*index,'unknown_completed':[],
                   'pending':[],'model_active_seconds':index}
        rows += [{'event':'reserve','call_id':cid,'run_id':str(directory),'phase':'stage2_research',
                  'amendment_id':waiver['amendment_id'],'registration_id':registration['registration_id'],
                  'account_before':account,'run_account_before':account,
                  'metadata':{'model':'gpt-6-astra','reasoning_effort':'medium','timeout_seconds':180,
                              'request_fingerprint':fingerprint,'authorization_context':context}},
                 {'event':'finish','call_id':cid,'status':status,'details':{'usage':usage,'duration_seconds':1}}]
    write(ledger, rows, lines=True); write(run / 'controller_decisions.jsonl', links, lines=True)
    write(run / 'result.json', {'identity':digest(cfg),'config':cfg,'status':'failed','full_window_completed':False,
        'failure':'synthetic failed controller','simulation_seconds':0,'model_calls':len(outputs),'model_call_ids':call_ids,
        'solver_calls':0,'solver_requested_seconds':0,'plans_committed':0,'wall_seconds':10})
    return run, ledger


class PageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='smt_fullfab_page_recovery_')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.run, self.ledger = make_fixture(self.root)
        self.counter = 0

    def prepare(self):
        self.counter += 1
        with patch('src.smt_fullfab.controller_recovery._verify_cold_checkpoint', return_value={'valid':True,'synthetic_unit_stub':True}):
            return prepare_B_recovery(self.run, self.root / f'recovery_{self.counter}.json', self.ledger)

    def test_transport_failure_keeps_accepted_page_and_original_budget(self):
        before, ledger_bytes = _inventory(self.run), self.ledger.read_bytes()
        report = self.prepare()
        self.assertEqual(report['status'],'prepared',report)
        self.assertEqual(report['recovery_mode'],'resume_next_page')
        self.assertEqual((report['next_page'],report['next_model_index']),(1,2))
        self.assertEqual(report['accepted_pages'][0]['call_id'],'synthetic-call-0')
        self.assertEqual(report['consumption']['unknown_usage_call_ids'],['synthetic-call-1'])
        self.assertEqual(report['remaining']['runner_wall_seconds'],7190)
        self.assertEqual(report['remaining']['model_active_seconds'],7198)
        self.assertEqual(report['remaining']['log_bytes'],1000000-sum(v['bytes'] for v in before.values()))
        self.assertEqual(_inventory(self.run),before); self.assertEqual(self.ledger.read_bytes(),ledger_bytes)
        self.assertFalse(report['executable_now']);self.assertFalse(report['executes_recovery'])

    def test_early_commit_patch_file_is_not_accepted(self):
        shutil.rmtree(self.run); self.ledger.unlink()
        output = {'tasks':[{'machine':0,'operations':['lot0:1:1'],'start':0,'sequence':0}], 'holds':[],'commit':True,'reason':'premature'}
        self.run,self.ledger = make_fixture(self.root,outputs=[output])
        report = self.prepare()
        self.assertEqual(report['status'],'prepared',report)
        self.assertEqual(report['accepted_pages'],[])
        self.assertEqual(report['next_page'],0)
        self.assertEqual(report['recovery_mode'],'needs_explicit_model_revision')

    def test_repeated_sequence_drops_only_offending_page(self):
        shutil.rmtree(self.run); self.ledger.unlink()
        outputs = [{'tasks':[{'machine':0,'operations':[f'lot{i}:1:1'],'start':0,'sequence':0}],
                    'holds':[],'commit':False,'reason':'duplicate chosen sequence'} for i in range(2)]
        self.run,self.ledger = make_fixture(self.root,outputs=outputs)
        report = self.prepare()
        self.assertEqual(report['status'],'prepared',report)
        self.assertEqual(len(report['accepted_pages']),1)
        self.assertEqual(report['next_page'],1)
        self.assertTrue(any('sequence' in x for x in report['failed_page_feedback'][0]['violations']))

    def test_all_pages_success_commit_failure_never_auto_applies(self):
        shutil.rmtree(self.run); self.ledger.unlink()
        outputs = [{'tasks':[{'machine':0,'operations':[f'lot{i}:1:1'],'start':0,'sequence':i}],
                    'holds':[],'commit':i==1,'reason':'explicit choice'} for i in range(2)]
        self.run,self.ledger = make_fixture(self.root,page_count=2,outputs=outputs)
        report = self.prepare()
        self.assertEqual(report['status'],'prepared',report)
        self.assertEqual(len(report['accepted_pages']),2)
        self.assertEqual(report['recovery_mode'],'needs_explicit_model_revision')
        self.assertIsNone(report['next_page']);self.assertFalse(report['executable_now'])
        write(self.run/'raw_plan_000.json',{'invented_uncommitted_plan':True})
        self.assertTrue(any('raw plan differs' in e for e in self.prepare()['errors']))

    def test_pending_attempt_is_rejected(self):
        rows = [json.loads(x) for x in self.ledger.read_text().splitlines()];rows.pop()
        write(self.ledger,rows,lines=True)
        self.assertTrue(any('unresolved' in e for e in self.prepare()['errors']))

    def test_active_process_is_rejected(self):
        claim = json.loads((self.run/'claim.json').read_text());claim['pid']=os.getpid();write(self.run/'claim.json',claim)
        self.assertTrue(any('alive' in e for e in self.prepare()['errors']))

    def test_changed_patch_prompt_and_checkpoint_each_rejected(self):
        path = self.run/'patch_000_00.json';original=path.read_text();changed=json.loads(original)
        changed['tasks'][0]['sequence']=9;write(path,changed)
        self.assertEqual(self.prepare()['status'],'rejected');path.write_text(original)
        prompt=self.run/'model_000/prompt.txt';original=prompt.read_text();prompt.write_text(original+'\nexternal advice')
        self.assertEqual(self.prepare()['status'],'rejected');prompt.write_text(original)
        snap=self.run/'checkpoint.json';value=json.loads(snap.read_text());value['state']['t']=1;write(snap,value)
        self.assertTrue(any('hash mismatch' in e for e in self.prepare()['errors']))

    def test_weaker_model_schema_is_rejected_even_when_fingerprint_not_changed(self):
        write(self.run/'model_000/schema.json',{'type':'object'})
        self.assertEqual(self.prepare()['status'],'rejected')

    def test_source_provenance_mutation_is_rejected(self):
        path=self.run/'source_snapshot/src/smt_fullfab/interface.py';path.write_text('# changed')
        self.assertEqual(self.prepare()['status'],'rejected')

    def test_legacy_v1_is_rejected_without_migration(self):
        legacy, ledger = fixture(self.root/'legacy')
        cfg=json.loads((legacy/'config.json').read_text())
        write(legacy/'claim.json',{'pid':999999999,'identity':digest(cfg)})
        result=json.loads((legacy/'result.json').read_text());result.update(plans_committed=0,simulation_seconds=0)
        write(legacy/'result.json',result)
        trace=[json.loads(line) for line in (legacy/'trace.jsonl').read_text().splitlines()]
        write(legacy/'trace.jsonl',trace[:1],lines=True)
        report=prepare_B_recovery(legacy,self.root/'legacy-rejected.json',ledger)
        self.assertTrue(any('legacy v1' in e for e in report['errors']),report)

    def test_unknown_terminal_process_is_rejected(self):
        path=self.run/'model_001/result.json';model=json.loads(path.read_text());model.pop('returncode');write(path,model)
        self.assertTrue(any('terminated process' in e for e in self.prepare()['errors']))

    def test_real_cold_state_roundtrip_and_rehashed_private_queue_tamper(self):
        # Initializes t=0 only. No controller, reference action or advance call.
        from src.smt_fullfab.environment import FullFabEnvironment
        from src.smt_fullfab.runner import source_snapshot
        run=self.root/'frozen_cold';run.mkdir()
        cfg={'seed':1901,'seconds':3600,'plan_seconds':14400,'lookahead_depth':2}
        write(run/'config.json',cfg);write(run/'provenance.json',source_snapshot(run))
        env=FullFabEnvironment(seed=1901,window_seconds=3600)
        env.snapshot(run/'checkpoint.json')
        problem=env.problem(plan_seconds=14400,lookahead_depth=2);write(run/'problem_000.json',problem)
        snapshot=json.loads((run/'checkpoint.json').read_text())
        result=_verify_cold_checkpoint(run,cfg,snapshot,problem)
        self.assertTrue(result['valid']);self.assertEqual(result['clock_advances'],0)
        snapshot['state']['q'][0][0]+=1
        snapshot['state_sha256']=digest(snapshot['state']);write(run/'checkpoint.json',snapshot)
        with self.assertRaisesRegex(ValueError,'exact frozen cold initial state'):
            _verify_cold_checkpoint(run,cfg,snapshot,problem)

    def test_nonzero_physical_state_is_not_claimed_supported(self):
        path=self.run/'result.json';r=json.loads(path.read_text());r['simulation_seconds']=1;write(path,r)
        self.assertTrue(any('later physical' in e for e in self.prepare()['errors']))

    def test_output_never_overwrites_parent_or_existing_artifact(self):
        with self.assertRaises(ValueError):prepare_B_recovery(self.run,self.run/'new.json',self.ledger)
        out=self.root/'exists.json';out.write_text('{}')
        with self.assertRaises(ValueError):prepare_B_recovery(self.run,out,self.ledger)

    def test_checkpoint_verifier_requires_original_runtime_lock(self):
        with self.assertRaisesRegex(ValueError,'dependencies differ'):
            _verify_cold_checkpoint(self.run,{}, {}, {})

    def test_cold_checkpoint_verifier_rejects_dependency_mismatch_without_advancing(self):
        # Fails at dependency verification before starting the subprocess.
        snapshot={'implementation_sha256':{'src/smt_fullfab/interface.py':'wrong'}}
        with self.assertRaisesRegex(ValueError,'dependencies differ'):
            _verify_cold_checkpoint(self.run,{},snapshot,{})


if __name__=='__main__':unittest.main()
