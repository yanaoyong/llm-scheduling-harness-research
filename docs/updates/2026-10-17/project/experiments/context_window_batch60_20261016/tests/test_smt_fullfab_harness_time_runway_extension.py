"""Bounded same-run time extension; isolated prototype first, real checkpoint later."""
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil, sqlite3, tempfile, unittest
from unittest.mock import patch
from src.smt_fullfab.harness import experiment, source_revision, wall_budget
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.evaluation import audit_cost

OUT = ROOT / 'artifacts/harness_B_time_runway_extension_20261015'
OLD = ROOT / 'artifacts/harness_B_time_extension_20261015'
LIVE = ROOT / 'artifacts/harness_p5_astra_TUN_B_release'
RUN = LIVE / 'continuations/B3600-no-exception-quota'
BOUNDARY_PATH = OUT / 'boundary.json' if (OUT / 'boundary.json').exists() else OUT / 'prototype_boundary.json'
BOUNDARY = strict_json(BOUNDARY_PATH.read_bytes())


class TimeRunwayExtensionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='offline-time-extension-')
        self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.reg = strict_json((LIVE / 'experiment.json').read_bytes())
        self.base = strict_json((LIVE / 'exception_policy_amendment.json').read_bytes())
        self.manifest = strict_json((RUN / 'manifest.json').read_bytes())
        self.grant_path = OUT / 'authorization.json' if (OUT / 'authorization.json').exists() else OUT / 'budget_grant_draft.json'
        self.grant = strict_json(self.grant_path.read_bytes())
        self.previous = strict_json((LIVE / 'source_revision_4.json').read_bytes())
        self.fp = strict_json(Path(strict_json((LIVE / 'source_revision_5.json').read_bytes())['engineering_report']['path']).read_bytes())['fingerprint']
        frozen = patch('src.smt_fullfab.harness.runtime.fingerprint', return_value=self.fp)
        frozen.start(); self.addCleanup(frozen.stop)
        tests = self.root / 'tests.json'
        tests.write_bytes(encode({'all_pass':True,'source_unchanged':True,
                                 'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
        report = self.root / 'report.json'
        report.write_bytes(encode({'fingerprint':self.fp,'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')},
                                  'test_evidence':self.ref(tests)}))
        self.value = {'schema':source_revision.SCHEMA,'registration_sha256':digest(self.reg),
                      'base_amendment_sha256':digest(self.base),
                      'previous_source_revision':self.ref(LIVE/'source_revision_4.json'),
                      'base_source_sha256':self.previous['active_fingerprint_sha256'],
                      'active_fingerprint_sha256':self.fp['sha256'],
                      'repairs':wall_budget.RUNWAY_REPAIR,'user_authorization':self.ref(self.grant_path),
                      'boundary':self.ref(BOUNDARY_PATH),'engineering_report':self.ref(report)}
        previous_boundary = strict_json(Path(self.previous['boundary']['path']).read_bytes())
        self.previous_row = self.marker(self.previous, previous_boundary)
        self.row = self.marker(self.value, BOUNDARY)
        self.wall_previous = strict_json((LIVE/'source_revision_3.json').read_bytes())
        self.wall_row = self.marker(self.wall_previous, strict_json(Path(self.wall_previous['boundary']['path']).read_bytes()))
        self.markers = {'wall-budget':self.wall_row,'time-budget':self.previous_row,'time-runway-budget':self.row}

    def ref(self, path): return {'path':str(path),'sha256':sha_bytes(path.read_bytes())}
    def marker(self, value, boundary):
        return {'revision_sha256':digest(value),'boundary':value['boundary'],'head_before':boundary['head'],
                'source_before':value['base_source_sha256'],'source_after':value['active_fingerprint_sha256'],
                'new_model_calls':0}
    def selected(self):
        stack = ExitStack()
        stack.enter_context(patch.object(wall_budget,'_registered_revision',return_value=(self.wall_previous,self.reg)))
        stack.enter_context(patch.object(wall_budget,'_registered_time_revision',return_value=self.previous))
        stack.enter_context(patch.object(wall_budget,'_registered_runway_revision',return_value=self.value))
        return stack

    def test_T23_exact_grant_rejects_scope_budget_ancestry_and_clock_tampering(self):
        wall_budget.validate_runway_grant(self.grant,self.manifest,self.reg,self.previous)
        for key,val in [('additional_wall_seconds',None),('additional_model_seconds',True),('wall_extension_seconds',36000),
                        ('model_extension_seconds',7200),('previous_source_revision_sha256','bad'),
                        ('run_id','other'),('reset_time',True),('change_model',True),
                        ('change_production_decisions',True),('strict_zero_unknown_audit_unchanged',False)]:
            with self.subTest(key=key), self.assertRaises(HarnessError):
                wall_budget.validate_runway_grant({**self.grant,key:val},self.manifest,self.reg,self.previous)
        for section,key in [('limits_before','model_seconds'),('limits_after','cleanup_seconds'),
                            ('limits_original','wall_seconds')]:
            bad=deepcopy(self.grant);bad[section][key]+=1
            with self.assertRaises(HarnessError):wall_budget.validate_runway_grant(bad,self.manifest,self.reg,self.previous)
        bad=deepcopy(self.grant);bad['shared_caps_after']['micro']['model_seconds']+=1
        with self.assertRaises(HarnessError):wall_budget.validate_runway_grant(bad,self.manifest,self.reg,self.previous)
        bad=deepcopy(self.manifest);bad['created_epoch']+=1
        with self.assertRaises(HarnessError):wall_budget.validate_runway_grant(self.grant,bad,self.reg,self.previous)

    def test_T20_T23_exact_fifth_revision_retains_predecessors_and_rejects_sixth(self):
        source_revision.validate(self.value,self.reg,self.base)
        chain=source_revision.revision_chain(self.value)
        self.assertEqual(len(chain),5);self.assertEqual(chain[-2],self.previous)
        bad=deepcopy(self.value);bad['previous_source_revision']=self.previous['previous_source_revision']
        with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
        p=self.root/'fifth.json';p.write_bytes(encode(self.value))
        bad=deepcopy(self.value);bad['previous_source_revision']=self.ref(p)
        with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
        self.assertEqual(self.manifest['config']['model']['name'],'gpt-6-astra')
        changed={p for p,h in self.fp['files'].items() if strict_json(Path(self.previous['engineering_report']['path']).read_bytes())['fingerprint']['files'].get(p)!=h}
        self.assertEqual(changed,wall_budget.RUNWAY_FILES)

    def test_T23_markers_extend_once_and_old_evidence_keeps_original_limits(self):
        original=deepcopy(self.manifest)
        with self.selected():
            base=wall_budget.effective_budget(self.manifest,{})
            old=wall_budget.effective_budget(self.manifest,{'wall-budget':self.wall_row})
            fourth=wall_budget.effective_budget(self.manifest,{k:v for k,v in self.markers.items() if k!='time-runway-budget'})
            new=wall_budget.effective_budget(self.manifest,self.markers)
            self.assertEqual(base['limits']['wall_seconds'],14400)
            self.assertEqual(old['limits']['wall_seconds'],21600);self.assertEqual(old['limits']['model_seconds'],10800)
            self.assertNotIn('model_extension_seconds',old)
            self.assertEqual(fourth['limits']['wall_seconds'],36000);self.assertEqual(fourth['limits']['model_seconds'],14400)
            self.assertEqual(new['limits']['wall_seconds'],72000);self.assertEqual(new['limits']['model_seconds'],28800)
            self.assertEqual(new['effective_deadline_epoch'],self.manifest['created_epoch']+72000)
            self.assertEqual(new,wall_budget.effective_budget(self.manifest,self.markers))
            with self.assertRaises(HarnessError):wall_budget.effective_budget(self.manifest,{'time-runway-budget':self.row})
            with self.assertRaises(HarnessError):
                wall_budget.effective_budget(self.manifest,{'wall-budget':self.wall_row,'time-runway-budget':self.row})
            for key,val in [('new_model_calls',1),('revision_sha256','bad'),('head_before',{})]:
                with self.subTest(key=key),self.assertRaises(HarnessError):
                    wall_budget.effective_budget(self.manifest,{**self.markers,'time-runway-budget':{**self.row,key:val}})
        self.assertEqual(self.manifest,original)

    def test_T20_registered_fifth_requires_the_canonical_four_predecessor_paths(self):
        fifth=LIVE/'source_revision_5.json'
        original_exists,original_read=Path.exists,Path.read_bytes
        selected=deepcopy(self.value)
        with patch.object(Path,'exists',lambda p:False if p in (LIVE/'source_revision_6.json',LIVE/'source_revision_7.json') else True if p==fifth else original_exists(p)),\
             patch.object(Path,'read_bytes',lambda p:encode(selected) if p==fifth else original_read(p)):
            self.assertEqual(source_revision.for_amendment(self.reg,self.base),self.value)
            copied=self.root/'copied-fourth.json';copied.write_bytes(encode(self.previous))
            selected['previous_source_revision']=self.ref(copied)
            source_revision.validate(selected,self.reg,self.base)
            with self.assertRaisesRegex(HarnessError,'source_revision_chain'):
                source_revision.for_amendment(self.reg,self.base)

    def test_T23_admission_reserves_timeout_cleanup_and_keeps_pending_guard(self):
        store=SimpleNamespace(path=self.root,rows=lambda ns:list(self.markers.items()),meta=lambda key:{'phase':'OBSERVED','stop_reason':None})
        runtime=Runtime(store,self.manifest,None)
        usage={'unknown_usage':0,'pending_attempts':0,'actual_model_attempts':BOUNDARY['actual_attempts'],
               'input_tokens':8000000,'output_tokens':100000,'reserved_tokens':0,'model_seconds':15000}
        end=self.manifest['created_epoch']+72000
        with self.selected(),patch.object(runtime,'usage',return_value=usage),\
             patch('src.smt_fullfab.harness.amendment.validate_runtime_source'),\
             patch('src.smt_fullfab.harness.recovery.current_recoveries',return_value={}),\
             patch.object(experiment,'check_experiment_budget'):
            with patch('src.smt_fullfab.harness.runtime.time.time',return_value=self.manifest['created_epoch']+37000):
                runtime.check_admission(actual=True)
                usage['model_seconds']=28201
                with self.assertRaisesRegex(HarnessError,'time_budget'):runtime.check_admission(actual=True)
                usage['model_seconds']=15000;usage['pending_attempts']=1
                with self.assertRaisesRegex(HarnessError,'unknown_attempt'):runtime.check_admission(actual=True)
                usage['pending_attempts']=0
            with patch('src.smt_fullfab.harness.runtime.time.time',return_value=end-1200):
                with self.assertRaisesRegex(HarnessError,'time_budget'):runtime.check_admission(actual=True)
            with patch('src.smt_fullfab.harness.runtime.time.time',return_value=end-599):
                with self.assertRaisesRegex(HarnessError,'wall_budget'):runtime.check_admission()

    def test_T23_shared_account_uses_total_increment_once_and_retains_usage(self):
        with self.selected():budget=wall_budget.effective_budget(self.manifest,self.markers)
        usage={g:{'attempts':180,'tokens':8100000,'model_seconds':self.reg['caps'][g]['model_seconds']+17000,
                  'wall_seconds':self.reg['caps'][g]['wall_seconds']+56000,'pending':0} for g in ('B3600','combined')}
        original=deepcopy(usage);runtime=SimpleNamespace(manifest=self.manifest,config=self.manifest['config'],store=SimpleNamespace(path=RUN))
        with patch.object(experiment,'cumulative_usage',return_value=usage),patch.object(experiment,'registration',return_value=self.reg),\
             patch.object(experiment,'resource_status',return_value={'unexempt_unknown_usage':{'B3600':0,'combined':0}}):
            self.assertEqual(experiment.check_experiment_budget(runtime,100000,budget=budget),original)
            with self.assertRaisesRegex(HarnessError,'experiment_time'):
                experiment.check_experiment_budget(runtime,100000,budget={'wall_extension_seconds':7200})
            usage['combined']['model_seconds']=self.reg['caps']['combined']['model_seconds']+17401
            with self.assertRaisesRegex(HarnessError,'experiment_time'):experiment.check_experiment_budget(runtime,100000,budget=budget)
        self.assertEqual(wall_budget.shared_caps(self.reg,budget),self.grant['shared_caps_after'])

    def test_T23_cost_audit_retains_original_unknowns_and_reports_both_limits(self):
        evidence=source_revision.live_view(RUN);evidence.records=deepcopy(BOUNDARY['records'])
        evidence.value['sealed_epoch']=self.manifest['created_epoch']+37000
        original_rows=evidence.rows
        with self.selected(),patch.object(evidence,'rows',side_effect=lambda ns:self.markers if ns=='control_source_revisions' else original_rows(ns)):
            result=audit_cost(evidence)
        self.assertFalse(result['valid']);self.assertEqual(result['unknown_usage'],BOUNDARY['unknown_usage'])
        self.assertEqual(result['actual_attempts'],BOUNDARY['actual_attempts'])
        self.assertEqual(result['total_reported_tokens'],BOUNDARY['known_tokens'])
        self.assertTrue(result['original_wall_limit_exceeded'])
        self.assertEqual(result['original_model_limit_seconds'],10800)
        self.assertEqual(result['effective_model_limit_seconds'],28800)
        self.assertEqual(result['effective_wall_limit_seconds'],72000)

    def test_T15_T21_fifth_marker_resume_preserves_all_returned_work_and_original_clock(self):
        self.assertIn(BOUNDARY_PATH,(OUT/'boundary.json',OUT/'prototype_boundary.json'))
        self.assertEqual(len(BOUNDARY['records']['control_source_revisions']),4)
        target=self.root/'run';target.mkdir();(target/'objects').mkdir();(target/'exports').mkdir()
        with sqlite3.connect(f'file:{RUN/"events.sqlite3"}?mode=ro',uri=True) as src,sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst);dst.execute('DELETE FROM records')
            for ns,rows in BOUNDARY['records'].items():dst.executemany('INSERT INTO records VALUES(?,?,?)',[(ns,k,r) for k,r in rows.items()])
            dst.execute('DELETE FROM events WHERE seq > ?',(BOUNDARY['event_count'],))
            dst.execute('DELETE FROM physical WHERE seq >= ?',(BOUNDARY['physical_count'],))
            dst.execute('UPDATE metadata SET value=? WHERE key=?',(encode(BOUNDARY['head']),'head'))
        for p in (RUN/'objects').iterdir():(target/'objects'/p.name).hardlink_to(p)
        shutil.copy2(RUN/'manifest.json',target/'manifest.json');(self.root/'experiment.json').write_bytes(encode(self.reg))
        original=source_revision.for_amendment
        from src.smt_fullfab.harness.amendment import case_directory
        def selected(reg,base):return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original(reg,base)
        def directory(root,case):return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
        with self.selected(),patch.object(source_revision,'for_amendment',side_effect=selected),\
             patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory),\
             patch.object(experiment,'experiment_lock',return_value=nullcontext()):
            source_revision.install(self.root)
            view=source_revision.live_view(target);source_revision.validate_marker(view,self.reg,self.base,required=True)
            self.assertEqual(len(view.rows('control_source_revisions')),5)
            with self.assertRaises(HarnessError):source_revision.install(self.root)
            runtime=Runtime.resume_run(target)
            try:
                self.assertEqual(runtime.manifest,self.manifest)
                self.assertEqual(len(runtime.store.rows('attempts')),BOUNDARY['actual_attempts'])
                self.assertEqual(len(runtime.store.rows('commits')),BOUNDARY['commits'])
                self.assertEqual(runtime.head['state_ref'],BOUNDARY['head']['state_ref'])
                self.assertEqual(runtime.wall_budget()['limits']['wall_seconds'],72000)
                self.assertEqual(runtime.wall_budget()['limits']['model_seconds'],28800)
            finally:runtime.close()

