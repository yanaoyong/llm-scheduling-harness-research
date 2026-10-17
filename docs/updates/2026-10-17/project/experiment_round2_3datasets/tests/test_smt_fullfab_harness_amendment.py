"""Limit-only control migration against real retained failures; no inference."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.amendment import validate_amendment, policy_for_record, continue_sealed_failure, validate_continuation, case_directory, validate_runtime_source
from src.smt_fullfab.harness.recovery import LiveEvidence, schedule_recovery
from src.smt_fullfab.harness.store import Store


class AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-limit30-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.live = ROOT/'artifacts/harness_p5_sol_release'
        self.reg = strict_json((self.live/'experiment.json').read_bytes())
        self.fp = strict_json((ROOT/'artifacts/harness_sol_limit30/fingerprint.json').read_bytes())
        self.tests = self.root/'tests.json'
        self.tests.write_bytes(encode({'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
        self.report = self.root/'engineering.json'
        self.report.write_bytes(encode({'fingerprint':self.fp,'test_evidence':self.ref(self.tests),'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')}}))
        self.value = {'schema':'harness-recovery-amendment-v1','base_registration_sha256':digest(self.reg),
            'user_authorization':self.ref(ROOT/'artifacts/harness_sol_acceptance/recovery_limit_30_authorization.json'),
            'original_policy':deepcopy(self.reg['recovery_policy']),
            'policy':{**self.reg['recovery_policy'],'max_failures_per_cohort':30},
            'active_fingerprint_sha256':self.fp['sha256'],'engineering_report':self.ref(self.report),
            'recovery_boundary':self.ref(ROOT/'artifacts/harness_sol_limit30/recovery_boundary.json'),
            'sealed_failure':self.ref(self.live/'runs/micro-20/evidence_manifest.json'),
            'continuation_directory':str(self.root/'continuations/micro-20-limit30')}

    def ref(self,p):return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}

    def test_T20_T23_only_limit_change_accepts_and_retains_original_policy(self):
        self.assertEqual(validate_amendment(self.value,self.reg)['policy']['max_failures_per_cohort'],30)
        boundary = strict_json(Path(self.value['recovery_boundary']['path']).read_bytes())
        with patch('src.smt_fullfab.harness.amendment.amendment_for',return_value=self.value):
            for aid,row in boundary['recoveries'].items():
                self.assertEqual(policy_for_record(self.reg,self.value['policy'],aid,row)['max_failures_per_cohort'],5)
            aid,row = next(iter(boundary['recoveries'].items()))
            bad=deepcopy(row);bad['cohort_failure_ordinal']=1 if row['cohort_failure_ordinal']!=1 else 2
            with self.assertRaises(HarnessError):policy_for_record(self.reg,self.value['policy'],aid,bad)
            with self.assertRaises(HarnessError):policy_for_record(self.reg,self.value['policy'],'new-failure',row)

    def test_T20_reject_policy_registration_and_source_tampering(self):
        for field,val in [('max_failures_per_cohort',31),('max_retries_per_request',3),('cooldown_seconds',[0,0]),('full_B_requires_zero_unknown',False)]:
            bad=deepcopy(self.value);bad['policy'][field]=val
            with self.subTest(field=field),self.assertRaises(HarnessError):validate_amendment(bad,self.reg)
        bad=deepcopy(self.value);bad['base_registration_sha256']='0'*64
        with self.assertRaises(HarnessError):validate_amendment(bad,self.reg)
        report=strict_json(self.report.read_bytes());report['fingerprint']['files']['src/smt_fullfab/harness/factory.py']='0'*64
        fp=report['fingerprint'];fp['sha256']=digest({k:v for k,v in fp.items() if k!='sha256'})
        self.report.write_bytes(encode(report));bad=deepcopy(self.value);bad['engineering_report']=self.ref(self.report);bad['active_fingerprint_sha256']=fp['sha256']
        with self.assertRaisesRegex(HarnessError,'amendment_source'):validate_amendment(bad,self.reg)

    def test_T20_reject_unverified_tests_or_source_version(self):
        x=strict_json(self.tests.read_bytes());x['all_pass']=False;self.tests.write_bytes(encode(x))
        r=strict_json(self.report.read_bytes());r['test_evidence']=self.ref(self.tests);self.report.write_bytes(encode(r))
        self.value['engineering_report']=self.ref(self.report)
        with self.assertRaisesRegex(HarnessError,'amendment_tests'):validate_amendment(self.value,self.reg)
        manifest=strict_json((self.live/'runs/micro-20/manifest.json').read_bytes())
        with patch('src.smt_fullfab.harness.amendment.amendment_for',return_value=None):
            with self.assertRaisesRegex(HarnessError,'fingerprint_changed'):validate_runtime_source(manifest,self.fp)

    def clone(self,name):
        p=self.root/name;source=self.live/'runs/micro-20'
        p.mkdir();shutil.copytree(source/'objects',p/'objects');shutil.copytree(source/'exports',p/'exports')
        shutil.copy2(source/'manifest.json',p/'manifest.json')
        with sqlite3.connect(f'file:{source}/events.sqlite3?mode=ro',uri=True) as a,sqlite3.connect(p/'events.sqlite3') as b:a.backup(b)
        return p

    def test_T22_30th_allowed_31st_refused_without_reset_or_new_call(self):
        for used in (29,30):
            p=self.clone(str(used));s=Store(p)
            try:
                m=s.read('manifest','run');r=SimpleNamespace(config=m['config'],manifest=m,store=s)
                aid,original=s.rows('attempts')[0]
                with patch('src.smt_fullfab.harness.recovery.policy_for',return_value=self.value['policy']),patch('src.smt_fullfab.harness.recovery.cohort_recoveries',return_value={'prior':('micro',{str(i):{} for i in range(used)})}):
                    row=schedule_recovery(r,aid)
                if used==29:
                    self.assertEqual(row['cohort_failure_ordinal'],30)
                    self.assertEqual(row['not_before_epoch'],original['finished_epoch']+60)
                else:self.assertIsNone(row)
                self.assertEqual(s.rows('attempts'),[(aid,original)])
            finally:s.close()

    def test_T15_T21_closed_failure_continues_in_new_segment_preserving_all_evidence(self):
        (self.root/'experiment.json').write_bytes(encode(self.reg))
        source=self.live/'runs/micro-20';m=strict_json((source/'manifest.json').read_bytes())
        with sqlite3.connect(self.root/'account.sqlite3') as db:
            db.execute('CREATE TABLE runs(case_id TEXT PRIMARY KEY,group_name TEXT,run_id TEXT UNIQUE,directory TEXT,created REAL)')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',('micro-20','micro',m['run_id'],str(source),m['created_epoch']))
        original_hash=sha_bytes((source/'evidence_manifest.json').read_bytes())
        with patch('src.smt_fullfab.harness.amendment.amendment_for',return_value=self.value),patch('src.smt_fullfab.harness.experiment.experiment_lock',return_value=nullcontext()),patch('src.smt_fullfab.harness.contracts.fingerprint',return_value=self.fp):
            target=continue_sealed_failure(self.root)
            self.assertEqual(case_directory(self.root,'micro-20'),target)
            view=LiveEvidence(target)
            with sqlite3.connect(f'file:{target}/events.sqlite3?mode=ro',uri=True) as db:
                db.row_factory=sqlite3.Row
                view.value={'events':[dict(x) for x in db.execute('SELECT * FROM events ORDER BY seq')],
                            'physical':[x[0] for x in db.execute('SELECT object_ref FROM physical ORDER BY seq')]}
            validate_continuation(view)
            old=LiveEvidence(source)
            self.assertEqual(view.manifest,old.manifest)
            self.assertEqual(view.rows('attempts'),old.rows('attempts'))
            self.assertEqual(sha_bytes((source/'evidence_manifest.json').read_bytes()),original_hash)
            self.assertFalse((target/'fragment_result.json').exists())
            self.assertFalse((target/'audit_closure.json').exists())
            self.assertFalse((target/'evidence_manifest.json').exists())
            with self.assertRaises(HarnessError):continue_sealed_failure(self.root)
            view.value['events'][0]['sha256']='0'*64
            with self.assertRaises(HarnessError):validate_continuation(view)

    def test_T22_request_limit_still_two_under_larger_cohort_allowance(self):
        from tests.test_smt_fullfab_harness_bounded_recovery import BoundedRecoveryTests
        from src.smt_fullfab.harness.recovery import policy_for
        from src.smt_fullfab.harness.amendment import effective_policy
        fixture=BoundedRecoveryTests('test_T22_two_retries_then_stop_and_shared_cohort_limit');fixture.setUp()
        def fixture_policy(admission):
            return self.value['policy'] if admission and admission['experiment_directory']==str(fixture.root) else policy_for(admission)
        def fixture_effective(reg, original):
            return self.value['policy'] if reg.get('experiment_directory')==str(fixture.root) else effective_policy(reg, original)
        try:
            # All validation entry points see the same fixture-only revision;
            # the real historical cohorts keep their own original policies.
            with patch('src.smt_fullfab.harness.recovery.policy_for',side_effect=fixture_policy),patch('src.smt_fullfab.harness.amendment.effective_policy',side_effect=fixture_effective):
                fixture.test_T22_two_retries_then_stop_and_shared_cohort_limit()
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
