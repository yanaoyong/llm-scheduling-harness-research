"""Approved wall time must not reset history or relax model/unknown guards."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil, sqlite3, tempfile, unittest
from unittest.mock import patch

from src.smt_fullfab.harness import experiment, source_revision, wall_budget
from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.evaluation import audit_cost

OUT = ROOT / 'artifacts/harness_B_wall_extension_20261015'
LIVE = ROOT / 'artifacts/harness_p5_astra_TUN_B_release'
RUN = LIVE / 'continuations/B3600-no-exception-quota'
BOUNDARY = strict_json((OUT / 'boundary.json').read_bytes())


class WallExtensionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='offline-wall-extension-')
        self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.reg = strict_json((LIVE / 'experiment.json').read_bytes())
        self.base = strict_json((LIVE / 'exception_policy_amendment.json').read_bytes())
        self.manifest = strict_json((RUN / 'manifest.json').read_bytes())
        self.grant = strict_json((OUT / 'authorization.json').read_bytes())
        self.value = strict_json((OUT / 'revision_draft.json').read_bytes())
        fp = strict_json(Path(strict_json((LIVE / 'source_revision_3.json').read_bytes())['engineering_report']['path']).read_bytes())['fingerprint']
        frozen = patch('src.smt_fullfab.harness.runtime.fingerprint', return_value=fp)
        frozen.start(); self.addCleanup(frozen.stop)
        tests = self.root / 'tests.json'
        tests.write_bytes(encode({'all_pass': True, 'source_unchanged': True,
                                 'fingerprint_sha256': fp['sha256'], 'remote_model_calls': 0}))
        report = self.root / 'report.json'
        report.write_bytes(encode({'fingerprint': fp, 'gates': {g:'pass' for g in ('G0','G1','G2','G3','G4')},
                                  'test_evidence': self.ref(tests)}))
        self.value.update(active_fingerprint_sha256=fp['sha256'], engineering_report=self.ref(report))
        self.row = {'revision_sha256': digest(self.value), 'boundary': self.value['boundary'],
                    'head_before': BOUNDARY['head'], 'source_before': self.value['base_source_sha256'],
                    'source_after': fp['sha256'], 'new_model_calls': 0}
        self.markers = {'wall-budget': self.row}

    def ref(self, path):
        return {'path': str(path), 'sha256': sha_bytes(path.read_bytes())}

    def selected_budget(self):
        return patch.object(wall_budget, '_registered_revision', return_value=(self.value, self.reg))

    def test_T23_grant_binds_exact_limits_model_time_and_original_clock(self):
        wall_budget.validate_grant(self.grant, self.manifest, self.reg)
        for key, value in [('wall_extension_seconds', None), ('wall_extension_seconds', 14400),
                           ('run_id', 'different'), ('reset_time', True), ('change_model', True),
                           ('strict_zero_unknown_audit_unchanged', False)]:
            with self.subTest(key=key, value=value), self.assertRaises(HarnessError):
                wall_budget.validate_grant({**self.grant, key:value}, self.manifest, self.reg)
        for section, key in [('limits_after','model_seconds'), ('limits_after','cleanup_seconds')]:
            bad = deepcopy(self.grant); bad[section][key] += 1
            with self.assertRaises(HarnessError): wall_budget.validate_grant(bad, self.manifest, self.reg)
        bad = deepcopy(self.grant); bad['shared_caps_after']['combined']['model_seconds'] += 1
        with self.assertRaises(HarnessError): wall_budget.validate_grant(bad, self.manifest, self.reg)

    def test_T20_T23_third_revision_retains_both_predecessors_and_cannot_chain_more(self):
        source_revision.validate(self.value, self.reg, self.base)
        chain = source_revision.revision_chain(self.value)
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[1], strict_json((LIVE / 'source_revision_2.json').read_bytes()))
        bad = deepcopy(self.value); bad['previous_source_revision'] = chain[1]['previous_source_revision']
        with self.assertRaises(HarnessError): source_revision.validate(bad, self.reg, self.base)
        path = self.root / 'third.json'; path.write_bytes(encode(self.value))
        bad = deepcopy(self.value); bad['previous_source_revision'] = self.ref(path)
        with self.assertRaises(HarnessError): source_revision.validate(bad, self.reg, self.base)

    def test_T23_only_durable_marker_extends_once_and_old_evidence_is_unchanged(self):
        original = deepcopy(self.manifest)
        with self.selected_budget():
            old = wall_budget.effective_budget(self.manifest, {})
            a = wall_budget.effective_budget(self.manifest, self.markers)
            b = wall_budget.effective_budget(self.manifest, self.markers)
            self.assertEqual(a, b); self.assertEqual(old['limits']['wall_seconds'], 14400)
            self.assertEqual(a['limits']['wall_seconds'], 21600)
            self.assertEqual(a['effective_deadline_epoch'], self.manifest['deadline_epoch'] + 7200)
            for key, value in [('revision_sha256', 'bad'), ('new_model_calls', 1), ('head_before', {})]:
                with self.subTest(key=key), self.assertRaises(HarnessError):
                    wall_budget.effective_budget(self.manifest, {'wall-budget': {**self.row, key:value}})
        self.assertEqual(self.manifest, original)

    def test_T23_live_admission_uses_new_deadline_but_keeps_model_and_cleanup_guards(self):
        store = SimpleNamespace(path=self.root, rows=lambda ns:list(self.markers.items()),
                                meta=lambda key: {'phase':'OBSERVED','stop_reason':None})
        runtime = Runtime(store, self.manifest, None)
        usage = {'unknown_usage':0,'pending_attempts':0,'actual_model_attempts':70,
                 'input_tokens':3100000,'output_tokens':100000,'reserved_tokens':0,'model_seconds':3000}
        with self.selected_budget(), patch.object(runtime, 'usage', return_value=usage), \
             patch('src.smt_fullfab.harness.amendment.validate_runtime_source'), \
             patch('src.smt_fullfab.harness.recovery.current_recoveries', return_value={}), \
             patch.object(experiment, 'check_experiment_budget'):
            end = self.manifest['deadline_epoch'] + 7200
            with patch('src.smt_fullfab.harness.runtime.time.time', return_value=self.manifest['deadline_epoch'] + 1):
                runtime.check_admission(actual=True)
                usage['model_seconds'] = 10201
                with self.assertRaisesRegex(HarnessError, 'time_budget'): runtime.check_admission(actual=True)
                usage['model_seconds'] = 3000; usage['pending_attempts'] = 1
                with self.assertRaisesRegex(HarnessError, 'unknown_attempt'): runtime.check_admission(actual=True)
                usage['pending_attempts'] = 0
            with patch('src.smt_fullfab.harness.runtime.time.time', return_value=end - 1200):
                with self.assertRaisesRegex(HarnessError, 'time_budget'): runtime.check_admission(actual=True)
            with patch('src.smt_fullfab.harness.runtime.time.time', return_value=end - 599):
                with self.assertRaisesRegex(HarnessError, 'wall_budget'): runtime.check_admission()

    def test_T23_shared_budget_adds_same_allowance_without_resetting_usage(self):
        with self.selected_budget(): budget = wall_budget.effective_budget(self.manifest, self.markers)
        usage = {g:{'attempts':70,'tokens':3147497,'model_seconds':3000,
                    'wall_seconds':self.reg['caps'][g]['wall_seconds']-900,'pending':0} for g in ('B3600','combined')}
        runtime = SimpleNamespace(manifest=self.manifest, config=self.manifest['config'], store=SimpleNamespace(path=RUN))
        original = deepcopy(usage)
        with patch.object(experiment, 'cumulative_usage', return_value=usage), \
             patch.object(experiment, 'registration', return_value=self.reg), \
             patch.object(experiment, 'resource_status', return_value={'unexempt_unknown_usage':{'B3600':0,'combined':0}}):
            self.assertEqual(experiment.check_experiment_budget(runtime, 100000, budget=budget), original)
            with self.assertRaisesRegex(HarnessError, 'experiment_time'):
                experiment.check_experiment_budget(runtime, 100000, budget={'wall_extension_seconds':0})
            usage['combined']['wall_seconds'] = self.reg['caps']['combined']['wall_seconds'] + 7200 - 1200
            with self.assertRaisesRegex(HarnessError, 'experiment_time'):
                experiment.check_experiment_budget(runtime, 100000, budget=budget)
        self.assertEqual(wall_budget.shared_caps(self.reg,budget)['B3600']['model_seconds'], self.reg['caps']['B3600']['model_seconds'])

    def test_T23_audit_retains_unknown_costs_and_reports_original_overrun(self):
        evidence = source_revision.live_view(RUN)
        # The historical third-revision fixture must not acquire later live calls.
        evidence.records = deepcopy(BOUNDARY['records'])
        evidence.value['sealed_epoch'] = self.manifest['created_epoch'] + 14401
        original_rows = evidence.rows
        with self.selected_budget(), patch.object(evidence, 'rows', side_effect=lambda ns:self.markers if ns=='control_source_revisions' else original_rows(ns)):
            result = audit_cost(evidence)
        self.assertFalse(result['valid']); self.assertEqual(result['unknown_usage'], 2)
        self.assertTrue(result['original_wall_limit_exceeded'])
        self.assertEqual(result['effective_wall_limit_seconds'], 21600)
        self.assertEqual(result['total_reported_tokens'], BOUNDARY['known_tokens'])
        self.assertEqual(result['actual_attempts'], BOUNDARY['actual_attempts'])

    def test_T15_T21_third_marker_resume_preserves_all_commits_costs_and_original_manifest(self):
        target = self.root / 'run'; target.mkdir(); (target/'objects').mkdir(); (target/'exports').mkdir()
        with sqlite3.connect(f'file:{RUN/"events.sqlite3"}?mode=ro', uri=True) as src, sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst); dst.execute('DELETE FROM records')
            for ns,rows in BOUNDARY['records'].items(): dst.executemany('INSERT INTO records VALUES(?,?,?)', [(ns,k,r) for k,r in rows.items()])
            dst.execute('DELETE FROM events WHERE seq > ?', (BOUNDARY['event_count'],))
            dst.execute('DELETE FROM physical WHERE seq >= ?', (BOUNDARY['physical_count'],))
            dst.execute('UPDATE metadata SET value=? WHERE key=?', (encode(BOUNDARY['head']),'head'))
        for path in (RUN/'objects').iterdir(): (target/'objects'/path.name).hardlink_to(path)
        shutil.copy2(RUN/'manifest.json', target/'manifest.json')
        (self.root/'experiment.json').write_bytes(encode(self.reg))
        original_revision = source_revision.for_amendment
        from src.smt_fullfab.harness.amendment import case_directory
        def selected(reg,base):
            return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original_revision(reg,base)
        def directory(root,case):
            return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
        with self.selected_budget(), patch.object(source_revision,'for_amendment',side_effect=selected), \
             patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory), \
             patch.object(experiment,'experiment_lock',return_value=nullcontext()):
            source_revision.install(self.root)
            view = source_revision.live_view(target)
            source_revision.validate_marker(view,self.reg,self.base,required=True)
            self.assertEqual(len(view.rows('control_source_revisions')),3)
            with self.assertRaises(HarnessError): source_revision.install(self.root)
            runtime = Runtime.resume_run(target)
            try:
                self.assertEqual(runtime.manifest,self.manifest)
                self.assertEqual(len(runtime.store.rows('attempts')),BOUNDARY['actual_attempts'])
                self.assertEqual(len(runtime.store.rows('commits')),BOUNDARY['commits'])
                self.assertEqual(runtime.head['state_ref'],BOUNDARY['head']['state_ref'])
                self.assertEqual(runtime.wall_budget()['limits']['wall_seconds'],21600)
            finally: runtime.close()


if __name__ == '__main__': unittest.main()
