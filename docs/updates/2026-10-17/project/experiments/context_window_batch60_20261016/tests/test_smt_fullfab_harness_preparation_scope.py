"""A preparation scope must end before RPC and preserve linked source history."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil,sqlite3,tempfile,unittest
from unittest.mock import patch
from src.smt_fullfab.harness import experiment,source_revision,transport
from src.smt_fullfab.harness.contracts import ROOT,HarnessError,digest,encode,sha_bytes,strict_json
from src.smt_fullfab.harness.runtime import Runtime
import tests.test_smt_fullfab_harness_source_revision as original_tests

OUT=ROOT/'artifacts/harness_B_preparation_repair_20261015'
LIVE=ROOT/'artifacts/harness_p5_astra_TUN_B_release'
RUN=LIVE/'continuations/B3600-no-exception-quota'
BOUNDARY=strict_json((OUT/'boundary.json').read_bytes())


class PreparationScopeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='offline-preparation-scope-');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);raw=encode({'test_registration':True});(self.root/'experiment.json').write_bytes(raw)
        self.admission={'experiment_directory':str(self.root),'experiment_sha256':sha_bytes(raw)}
        self.full_checks=[];self.live_checks=[]
        self.runtime=SimpleNamespace(manifest={'admission':self.admission},head={'context_ref':'context:test'},
            config={'arm':'B'},store=SimpleNamespace(rows=lambda ns:[]),reserve_attempt=self.reserve)
    def validate(self,admission):self.full_checks.append(1);return {'immutable_proof':True}
    def network(self,*args,**kwargs):
        self.assertIsNotNone(experiment._registration_scope.get());experiment.registration(self.admission);return {'route':'test'}
    def reserve(self,text,schema):
        self.assertIsNotNone(experiment._registration_scope.get());experiment.registration(self.admission)
        self.live_checks.append(1);return 'attempt:test'
    def prepare(self):
        with patch.object(experiment,'_registration',side_effect=self.validate),patch('src.smt_fullfab.harness.network.for_admission',side_effect=self.network),patch.object(transport,'prompt',return_value='test prompt'),patch.object(transport,'response_schema',return_value={'type':'object'}):
            return transport._prepare_request(self.runtime)
    def test_T20_preparation_deduplicates_static_proof_but_next_call_and_live_reserve_are_fresh(self):
        self.assertEqual(self.prepare()[3],'attempt:test');self.assertIsNone(experiment._registration_scope.get())
        self.assertEqual(self.prepare()[3],'attempt:test');self.assertIsNone(experiment._registration_scope.get())
        self.assertEqual(len(self.full_checks),2);self.assertEqual(len(self.live_checks),2)
    def test_T20_preparation_exception_clears_scope_before_any_rpc(self):
        self.runtime.reserve_attempt=lambda *args:(_ for _ in ()).throw(HarnessError('fixture_failure','Before RPC'))
        with self.assertRaisesRegex(HarnessError,'fixture_failure'):self.prepare()
        self.assertIsNone(experiment._registration_scope.get())
        self.runtime.reserve_attempt=self.reserve;self.prepare();self.assertEqual(len(self.full_checks),2)
    def test_T20_nested_scope_preserves_owner_and_clears_outermost(self):
        with experiment.registration_validation_scope():
            owner=experiment._registration_scope.get();self.prepare()
            self.assertIs(experiment._registration_scope.get(),owner)
        self.assertIsNone(experiment._registration_scope.get())


class PreparationRevisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=original_tests.SourceRevisionTests('test_T20_revision_preserves_model_clock_and_production_sources')
        self.addCleanup(self.fixture.doCleanups);self.fixture.setUp();self.root=self.fixture.root
        self.reg=self.fixture.reg;self.base=self.fixture.base
        self.value=strict_json((OUT/'revision_draft.json').read_bytes())
        self.value.update(engineering_report=self.fixture.value['engineering_report'],active_fingerprint_sha256=self.fixture.fp['sha256'])
    def test_T20_second_revision_preserves_exact_tested_ancestry(self):
        source_revision.validate(self.value,self.reg,self.base)
        chain=source_revision.revision_chain(self.value);self.assertEqual(len(chain),2)
        self.assertEqual(chain[0],strict_json((LIVE/'source_revision.json').read_bytes()))
        bad=deepcopy(self.value);bad['base_source_sha256']=self.base['active_fingerprint_sha256']
        with self.assertRaisesRegex(HarnessError,'source_revision_chain'):source_revision.validate(bad,self.reg,self.base)
        bad=deepcopy(self.value);bad.pop('previous_source_revision')
        with self.assertRaises(HarnessError):source_revision.validate(bad,self.reg,self.base)
    def test_T23_new_boundary_cannot_reset_clock_or_hide_pending_work(self):
        for key,value in [('created_epoch',0),('deadline_epoch',1),('pending_attempts',1),('unprocessed_attempts',1),('config_sha256','0'*64)]:
            boundary={**deepcopy(BOUNDARY),key:value};path=self.root/'boundary.json';path.write_bytes(encode(boundary))
            candidate={**self.value,'boundary':self.fixture.ref(path)}
            with self.subTest(key=key),self.assertRaises(HarnessError):source_revision.validate(candidate,self.reg,self.base)
    def test_T15_T21_T23_two_markers_preserve_all_results_and_live_pending_guard(self):
        target=self.root/'run';target.mkdir();(target/'objects').mkdir();(target/'exports').mkdir()
        with sqlite3.connect(f'file:{RUN/"events.sqlite3"}?mode=ro',uri=True) as src,sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst);dst.execute('DELETE FROM records')
            for ns,rows in BOUNDARY['records'].items():dst.executemany('INSERT INTO records VALUES(?,?,?)',[(ns,k,r) for k,r in rows.items()])
            dst.execute('DELETE FROM events WHERE seq > ?',(BOUNDARY['event_count'],));dst.execute('DELETE FROM physical WHERE seq >= ?',(BOUNDARY['physical_count'],))
            dst.execute('UPDATE metadata SET value=? WHERE key=?',(encode(BOUNDARY['head']),'head'))
        for path in (RUN/'objects').iterdir():(target/'objects'/path.name).hardlink_to(path)
        shutil.copy2(RUN/'manifest.json',target/'manifest.json');(self.root/'experiment.json').write_bytes(encode(self.reg))
        original_revision=source_revision.for_amendment
        from src.smt_fullfab.harness.amendment import case_directory
        def selected(reg,base):return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original_revision(reg,base)
        def directory(root,case):return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
        with patch.object(source_revision,'for_amendment',side_effect=selected),patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory),patch.object(experiment,'experiment_lock',return_value=nullcontext()):
            before=source_revision.live_view(target);source_revision.validate_marker(before,self.reg,self.base)
            with self.assertRaises(HarnessError):source_revision.validate_marker(before,self.reg,self.base,required=True)
            first=before.rows('control_source_revisions');row=source_revision.install(self.root)
            self.assertEqual(row['new_model_calls'],0)
            after=source_revision.live_view(target);self.assertEqual(len(after.rows('control_source_revisions')),2)
            self.assertEqual({k:after.rows('control_source_revisions')[k] for k in first},first)
            source_revision.validate_marker(after,self.reg,self.base,required=True)
            del after.records['control_source_revisions']['context-and-validation']
            with self.assertRaisesRegex(HarnessError,'source_revision_marker'):source_revision.validate_marker(after,self.reg,self.base)
            with self.assertRaises(HarnessError):source_revision.install(self.root)
            runtime=Runtime.resume_run(target)
            try:
                self.assertEqual(len(runtime.store.rows('attempts')),45);self.assertEqual(len(runtime.store.rows('commits')),10)
                self.assertEqual(runtime.manifest,strict_json((RUN/'manifest.json').read_bytes()))
                self.assertEqual(runtime.head['state_ref'],BOUNDARY['head']['state_ref'])
                # The historical 45-call fixture must meter its own isolated account,
                # not the later live B directory's accumulated costs. Keep the real
                # shared-account budget and fresh pending checks enabled.
                account_records=experiment.account_records
                def captured_account(root):
                    rows=account_records(root)
                    return [(case,group,rid,str(target) if rid==runtime.manifest['run_id'] else directory,created)
                            for case,group,rid,directory,created in rows]
                with patch.object(experiment,'account_records',side_effect=captured_account), \
                     patch('src.smt_fullfab.harness.runtime.time.time',return_value=BOUNDARY['recorded_epoch']), \
                     experiment.registration_validation_scope():
                    historical=experiment.cumulative_usage(runtime.manifest['admission'])
                    prior,_,_=experiment.sealed_prior(self.reg)
                    self.assertEqual(historical['B3600']['attempts']-prior['B3600']['attempts'],45)
                    self.assertEqual(historical['B3600']['tokens']-prior['B3600']['tokens'],BOUNDARY['known_tokens'])
                    runtime.reserve_attempt('offline reservation only',{'type':'object'})
                    with self.assertRaisesRegex(HarnessError,'unknown_attempt'):
                        runtime.reserve_attempt('must not reserve twice',{'type':'object'})
                self.assertIsNone(experiment._registration_scope.get())
            finally:runtime.close()


if __name__=='__main__':unittest.main()
