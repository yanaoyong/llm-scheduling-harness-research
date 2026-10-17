"""Offline regression against the actual 21-call B boundary; no model requests."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import ModuleType
import shutil
from itertools import count
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness import experiment, source_revision
from src.smt_fullfab.harness.recovery import LiveEvidence
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.transport import prompt, PROTOCOL_TEXT
from src.smt_fullfab.harness.presentation import unpack

OUT = ROOT / 'artifacts/harness_B_context_repair_20261015'
LIVE = ROOT / 'artifacts/harness_p5_astra_TUN_B_release'
RUN = LIVE / 'continuations/B3600-no-exception-quota'
BOUNDARY = strict_json((OUT / 'boundary.json').read_bytes())


class Projection:
    """Captured record refs, with prompt publications held only in memory."""
    def __init__(self):
        self.path = RUN
        self.evidence = LiveEvidence(RUN)
        self.records = deepcopy(BOUNDARY['records'])
        self.objects = {}
    def meta(self, key, default=None):
        return deepcopy(BOUNDARY['head'] if key == 'head' else default)
    def bytes(self, ref):
        return self.objects[ref] if ref in self.objects else self.evidence.raw(ref)
    def get(self, ref): return strict_json(self.bytes(ref))
    def read(self, ns, key, default=None):
        return self.get(self.records[ns][key]) if key in self.records.get(ns, {}) else deepcopy(default)
    def rows(self, ns):
        rows = [(k, self.get(ref)) for k, ref in self.records.get(ns, {}).items()]
        return sorted(rows, key=lambda row: row[1]['index']) if ns == 'attempts' else rows
    def put(self, value):
        raw = encode(value); ref = sha_bytes(raw); self.objects[ref] = raw; return ref
    def record(self, ns, key, value):
        assert ns in ('public', 'interaction_entries')
        assert key not in self.records.get(ns, {})
        self.records.setdefault(ns, {})[key] = self.put(value)
    def transaction(self, **kwargs): return nullcontext()


class SourceRevisionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='offline-control-revision-')
        self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        self.reg = strict_json((LIVE / 'experiment.json').read_bytes())
        self.base = strict_json((LIVE / 'exception_policy_amendment.json').read_bytes())
        self.value = strict_json((OUT / 'revision_draft.json').read_bytes())
        # This fixture exercises the original repair boundary, not later grants.
        self.fp = strict_json((ROOT / 'artifacts/harness_B_preparation_repair_20261015/engineering_acceptance.json').read_bytes())['fingerprint']
        self.report = {'fingerprint': self.fp, 'gates': {g:'pass' for g in ('G0','G1','G2','G3','G4')}}
        self.sync()
        timer = patch('src.smt_fullfab.harness.runtime.time.time', return_value=BOUNDARY['recorded_epoch'])
        timer.start(); self.addCleanup(timer.stop)
        frozen = patch('src.smt_fullfab.harness.runtime.fingerprint', return_value=self.fp)
        frozen.start(); self.addCleanup(frozen.stop)
    def ref(self, path): return {'path':str(path), 'sha256':sha_bytes(path.read_bytes())}
    def sync(self):
        p = self.root / 'tests.json'
        p.write_bytes(encode({'all_pass':True, 'source_unchanged':True, 'fingerprint_sha256':self.fp['sha256'], 'remote_model_calls':0}))
        self.report['test_evidence'] = self.ref(p)
        p = self.root / 'report.json'; p.write_bytes(encode(self.report))
        self.value.update(engineering_report=self.ref(p), active_fingerprint_sha256=self.fp['sha256'])
    def old_transport(self):
        path = 'src/smt_fullfab/harness/transport.py'
        archive = ROOT / 'artifacts/harness_astra_B_quota_removed/frozen_source/source-and-data.tar.gz'
        old = strict_json((ROOT / 'artifacts/harness_astra_B_quota_removed/engineering_acceptance.json').read_bytes())
        with tarfile.open(archive) as tar: raw = tar.extractfile(path).read()
        self.assertEqual(sha_bytes(raw), old['fingerprint']['files'][path])
        module = ModuleType('src.smt_fullfab.harness._old_transport')
        module.__package__ = 'src.smt_fullfab.harness'
        exec(compile(raw, path, 'exec'), module.__dict__)
        return module
    def runtime(self):
        store = Projection(); return Runtime(store, store.read('manifest','run'), None)
    def render(self, function, runtime):
        ids = count()
        with patch('src.smt_fullfab.harness.runtime.identity', side_effect=lambda prefix: prefix+':offline-'+str(next(ids))):
            return function(runtime)
    def test_T20_actual_overflow_fits_without_losing_any_fact(self):
        old = self.old_transport(); r = self.runtime()
        try: self.render(old.prompt,r)
        except HarnessError as error:
            self.assertEqual(error.code, 'context_capacity')
            tb = error.__traceback__
            while tb.tb_frame.f_code.co_name != 'prompt': tb = tb.tb_next
            frame = deepcopy(tb.tb_frame.f_locals['frame'])
            before = tb.tb_frame.f_locals['rendered']
        else: self.fail('The captured 21-call boundary must reproduce the original blocker')
        after = self.render(prompt,self.runtime()); decoded = strict_json(after[len(PROTOCOL_TEXT)+1:])
        self.assertGreater(len(before), 120000)
        self.assertEqual(len(before) - len(after), 27474)
        self.assertLessEqual(len(after), r.config['limits']['context_chars'])
        self.assertEqual(unpack(decoded), unpack(frame))
        self.assertEqual(len(unpack(decoded['context']['trigger'])['machines']), 746)
        latest = r.store.rows('attempts')[-1][1]
        self.assertEqual(unpack(decoded['last_tool_feedback']), r.store.get(latest['response_ref']))
    def test_T20_fitting_prompt_bytes_unchanged(self):
        # Artificial capacity only inside this offline fixture; no live limit changes.
        old = self.old_transport(); a, b = self.runtime(), self.runtime()
        a.config['limits']['context_chars'] = b.config['limits']['context_chars'] = 500000
        self.assertEqual(self.render(old.prompt,a), self.render(prompt,b))
    def test_T20_revision_preserves_model_clock_and_production_sources(self):
        source_revision.validate(self.value, self.reg, self.base)
        p = 'src/smt_fullfab/harness/factory.py'
        self.fp['files'][p] = '0' * 64
        self.fp['sha256'] = digest({k:v for k,v in self.fp.items() if k != 'sha256'}); self.sync()
        with self.assertRaisesRegex(HarnessError, 'amendment_source'):
            source_revision.validate(self.value, self.reg, self.base)
    def test_T23_boundary_clock_pending_or_grant_change_rejected(self):
        original = deepcopy(self.value)
        for key, val in [('created_epoch',0), ('deadline_epoch',1), ('pending_attempts',1), ('config_sha256','0'*64)]:
            boundary = deepcopy(BOUNDARY); boundary[key] = val
            p = self.root / 'boundary.json'; p.write_bytes(encode(boundary))
            self.value = {**original, 'boundary':self.ref(p)}
            with self.subTest(key=key), self.assertRaises(HarnessError): source_revision.validate(self.value,self.reg,self.base)
        grant = strict_json((OUT / 'authorization.json').read_bytes()); grant['reset_time'] = True
        p = self.root / 'grant.json'; p.write_bytes(encode(grant))
        with self.assertRaisesRegex(HarnessError,'source_revision_grant'):
            source_revision.validate({**original,'user_authorization':self.ref(p)},self.reg,self.base)
    def test_T15_T21_marker_install_preserves_prefix_and_resumes_without_a_call(self):
        # Snapshot only the frozen boundary, never rely on later live progress.
        target = self.root / 'run'; target.mkdir(); (target/'objects').mkdir()
        with sqlite3.connect(f'file:{RUN / "events.sqlite3"}?mode=ro',uri=True) as src, sqlite3.connect(target/'events.sqlite3') as dst:
            src.backup(dst)
            dst.execute('DELETE FROM records')
            for ns, rows in BOUNDARY['records'].items():
                dst.executemany('INSERT INTO records VALUES(?,?,?)', [(ns,k,ref) for k,ref in rows.items()])
            dst.execute('DELETE FROM events WHERE seq > ?', (BOUNDARY['event_count'],))
            dst.execute('DELETE FROM physical WHERE seq >= ?', (BOUNDARY['physical_count'],))
            dst.execute('UPDATE metadata SET value=? WHERE key=?', (encode(BOUNDARY['head']),'head'))
        # Hard links are safe: object files are immutable and content addressed.
        for p in (RUN/'objects').iterdir(): (target/'objects'/p.name).hardlink_to(p)
        shutil.copy2(RUN/'manifest.json', target/'manifest.json'); (target/'exports').mkdir()
        (self.root/'experiment.json').write_bytes(encode(self.reg))
        from src.smt_fullfab.harness.amendment import amendment_for, case_directory
        original_revision = source_revision.for_amendment
        def selected(reg): return self.base if digest(reg)==digest(self.reg) else amendment_for(reg)
        def revision(reg, base): return source_revision.validate(self.value,reg,base) if digest(reg)==digest(self.reg) else original_revision(reg,base)
        def directory(root, case): return target if Path(root).resolve() in (LIVE.resolve(),self.root.resolve()) else case_directory(root,case)
        with patch('src.smt_fullfab.harness.amendment.amendment_for',side_effect=selected), patch.object(source_revision,'for_amendment',side_effect=revision), patch('src.smt_fullfab.harness.amendment.case_directory',side_effect=directory), patch.object(experiment,'experiment_lock',return_value=nullcontext()):
            with self.assertRaises(HarnessError): source_revision.validate_marker(source_revision.live_view(target),self.reg,self.base,required=True)
            row = source_revision.install(self.root)
            self.assertEqual(row['new_model_calls'],0)
            with self.assertRaisesRegex(HarnessError,'source_revision_boundary'): source_revision.install(self.root)
            runtime = Runtime.resume_run(target)
            try:
                self.assertEqual(runtime.manifest,strict_json((RUN/'manifest.json').read_bytes()))
                self.assertEqual(len(runtime.store.rows('attempts')),21)
                self.assertEqual(len(runtime.store.rows('commits')),5)
                self.assertEqual(runtime.head['state_ref'],BOUNDARY['head']['state_ref'])
                self.assertEqual(runtime.head['time'],0)
                source_revision.validate_marker(source_revision.live_view(target),self.reg,self.base,required=True)
            finally: runtime.close()
            view = source_revision.live_view(target); key = next(iter(view.records['attempts'])); view.records['attempts'][key]='0'*64
            with self.assertRaisesRegex(HarnessError,'source_revision_prefix'): source_revision._check_prefix(view,BOUNDARY)


class RegistrationScopeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='offline-registration-scope-'); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); self.calls=[]; self.admissions={}
        for name in ('root','child'):
            p=self.root/name; p.mkdir(); raw=encode({'name':name}); (p/'experiment.json').write_bytes(raw)
            self.admissions[name]={'experiment_directory':str(p),'experiment_sha256':sha_bytes(raw)}
    def validator(self, admission):
        name=Path(admission['experiment_directory']).name; self.calls.append(name)
        if name=='child': return {'facts':['original']}
        first=experiment.registration(self.admissions['child']); first['facts'].append('caller mutation')
        second=experiment.registration(self.admissions['child'])
        self.assertEqual(second,{'facts':['original']}); return second
    def test_T20_nested_shared_dependency_checked_once_and_fresh_outer_rechecks(self):
        with patch.object(experiment,'_registration',side_effect=self.validator):
            experiment.registration(self.admissions['root']); experiment.registration(self.admissions['root'])
        self.assertEqual(self.calls,['root','child','root','child'])
        self.assertIsNone(experiment._registration_scope.get())
    def test_T20_registration_bytes_checked_even_on_scope_hit_and_error_clears(self):
        def validator(a):
            if Path(a['experiment_directory']).name=='child': return {'ok':True}
            experiment.registration(self.admissions['child'])
            (self.root/'child/experiment.json').write_bytes(b'{}')
            return experiment.registration(self.admissions['child'])
        with patch.object(experiment,'_registration',side_effect=validator), self.assertRaisesRegex(HarnessError,'registration_changed'):
            experiment.registration(self.admissions['root'])
        self.assertIsNone(experiment._registration_scope.get())
    def test_T20_changed_dependency_is_revalidated_on_next_outer_call(self):
        dep=self.root/'dependency'; dep.write_text('good')
        def validator(a):
            if Path(a['experiment_directory']).name=='child':
                if dep.read_text()!='good': raise HarnessError('changed_dependency','Changed after prior validation')
                return {'ok':True}
            return experiment.registration(self.admissions['child'])
        with patch.object(experiment,'_registration',side_effect=validator):
            experiment.registration(self.admissions['root']); dep.write_text('bad')
            with self.assertRaisesRegex(HarnessError,'changed_dependency'): experiment.registration(self.admissions['root'])
        self.assertIsNone(experiment._registration_scope.get())


if __name__ == '__main__': unittest.main()
