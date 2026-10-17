"""Quota removal cannot erase costs, replay accepted dispatches or reset B."""
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, digest, encode, fingerprint, sha_bytes, strict_json
from src.smt_fullfab.harness.B_exception_policy import SCHEMA, validate
from src.smt_fullfab.harness.amendment import continue_sealed_failure, validate_continuation, case_directory, policy_for_record
from src.smt_fullfab.harness.evaluation import Evidence, audit_cost
from src.smt_fullfab.harness.recovery import LiveEvidence, schedule_recovery
from src.smt_fullfab.harness.store import Store


class BExceptionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-B-quota-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.live = ROOT / 'artifacts/harness_p5_astra_TUN_B_release'
        self.source = self.live / 'runs/B3600'
        self.reg = strict_json((self.live / 'experiment.json').read_bytes())
        self.old = Evidence(self.source, sha_bytes((self.source / 'evidence_manifest.json').read_bytes()))
        self.fp = strict_json((ROOT / 'artifacts/harness_astra_B_quota_removed/engineering_acceptance.json').read_bytes())['fingerprint']
        self.grant = strict_json((ROOT / 'artifacts/harness_astra_TUN_B_transition/exception_quota_removal_authorization.json').read_bytes())
        self.boundary = {'registration_sha256':digest(self.reg), 'sealed_failure':self.ref(self.source/'evidence_manifest.json'),
                         'run_id':self.old.manifest['run_id'], 'created_epoch':self.old.manifest['created_epoch'],
                         'deadline_epoch':self.old.manifest['deadline_epoch'], 'head':self.old.value['head'],
                         'recoveries':self.old.rows('transport_recoveries'), 'attempts_sha256':digest(self.old.rows('attempts')),
                         'commits_sha256':digest(self.old.rows('commits')), 'physical_refs_sha256':digest(self.old.value['physical'])}
        tests = self.root / 'tests.json'
        tests.write_bytes(encode({'all_pass':True,'source_unchanged':True,'fingerprint_sha256':self.fp['sha256'],'remote_model_calls':0}))
        self.report = {'fingerprint':self.fp, 'test_evidence':self.ref(tests), 'gates':{g:'pass' for g in ('G0','G1','G2','G3','G4')}}
        self.value = {'schema':SCHEMA, 'base_registration_sha256':digest(self.reg),
                      'original_policy':self.reg['recovery_policy'], 'policy':{**self.reg['recovery_policy'],'max_failures_per_cohort':None},
                      'active_fingerprint_sha256':self.fp['sha256'], 'sealed_failure':self.boundary['sealed_failure'],
                      'continuation_directory':str(self.live/'continuations/B3600-no-exception-quota'),
                      'continue_B_on_proven_terminal_unknown':True,'strict_zero_unknown_audit_unchanged':True,
                      **{k:False for k in ('new_B_start','reset_costs','reset_time','change_model','change_production_code')}}
        self.sync()

    def ref(self,p): return {'path':str(p),'sha256':sha_bytes(p.read_bytes())}

    def sync(self):
        for name,value,key in (('grant.json',self.grant,'user_authorization'),('boundary.json',self.boundary,'recovery_boundary'),('report.json',self.report,'engineering_report')):
            p=self.root/name;p.write_bytes(encode(value));self.value[key]=self.ref(p)

    def test_T20_T23_only_explicit_quota_and_early_stop_control_changes(self):
        self.assertIsNone(validate(self.value,self.reg)['policy']['max_failures_per_cohort'])
        self.assertTrue(self.value['policy']['full_B_requires_zero_unknown'])
        for key,value in [('max_retries_per_request',3),('cooldown_seconds',[0,0]),('max_failures_per_cohort',100000),('full_B_requires_zero_unknown',False)]:
            bad=deepcopy(self.value);bad['policy'][key]=value
            with self.subTest(key=key),self.assertRaises(HarnessError):validate(bad,self.reg)
        for key in ('reset_costs','reset_time','new_B_start','change_model','change_production_code'):
            bad=deepcopy(self.value);bad[key]=True
            with self.subTest(key=key),self.assertRaises(HarnessError):validate(bad,self.reg)

    def test_T20_missing_human_authorization_rejected(self):
        self.grant['user_instruction']='Continue';self.sync()
        with self.assertRaisesRegex(HarnessError,'B_exception_grant'):validate(self.value,self.reg)

    def test_T20_production_source_change_rejected(self):
        self.fp['files']['src/smt_fullfab/harness/factory.py']='0'*64
        self.fp['sha256']=digest({k:v for k,v in self.fp.items() if k!='sha256'})
        self.value['active_fingerprint_sha256']=self.fp['sha256'];self.sync()
        with self.assertRaisesRegex(HarnessError,'amendment_source'):validate(self.value,self.reg)

    def test_T23_cost_clock_and_commit_boundary_tampering_rejected(self):
        original=deepcopy(self.boundary)
        for key,val in [('attempts_sha256','0'*64),('commits_sha256','0'*64),('created_epoch',0),('deadline_epoch',1),('recoveries',{})]:
            self.boundary={**deepcopy(original),key:val};self.sync()
            with self.subTest(key=key),self.assertRaisesRegex(HarnessError,'B_exception_boundary'):validate(self.value,self.reg)

    def test_T23_old_exception_policy_proof_cannot_be_relabelled(self):
        aid,row=next(iter(self.boundary['recoveries'].items()))
        with patch('src.smt_fullfab.harness.amendment.amendment_for',return_value=self.value):
            self.assertEqual(policy_for_record(self.reg,self.value['policy'],aid,row),self.reg['recovery_policy'])
            bad=deepcopy(row);bad['not_before_epoch']-=1
            with self.assertRaisesRegex(HarnessError,'amendment_boundary'):policy_for_record(self.reg,self.value['policy'],aid,bad)

    def test_T15_T21_committed_B_continues_without_replay_or_clock_reset(self):
        validate(self.value,self.reg)
        (self.root/'experiment.json').write_bytes(encode(self.reg))
        self.value['continuation_directory']=str(self.root/'continuations/B3600-no-exception-quota')
        m=self.old.manifest
        with sqlite3.connect(self.root/'account.sqlite3') as db:
            db.execute('CREATE TABLE runs(case_id TEXT PRIMARY KEY,group_name TEXT,run_id TEXT UNIQUE,directory TEXT,created REAL)')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',('B3600','B3600',m['run_id'],str(self.source),m['created_epoch']))
        old_seal=sha_bytes((self.source/'evidence_manifest.json').read_bytes())
        from src.smt_fullfab.harness.amendment import amendment_for
        def selected(candidate):
            return self.value if digest(candidate)==digest(self.reg) else amendment_for(candidate)
        # This is the frozen e3 quota transition, before later source revisions.
        with patch('src.smt_fullfab.harness.amendment.amendment_for',side_effect=selected),patch('src.smt_fullfab.harness.experiment.experiment_lock',return_value=nullcontext()),patch('src.smt_fullfab.harness.contracts.fingerprint',return_value=self.fp),patch('src.smt_fullfab.harness.runtime.fingerprint',return_value=self.fp),patch('src.smt_fullfab.harness.source_revision.for_amendment',return_value=None):
            target=continue_sealed_failure(self.root)
            self.assertEqual(case_directory(self.root,'B3600'),target)
            view=LiveEvidence(target)
            with sqlite3.connect(f'file:{target}/events.sqlite3?mode=ro',uri=True) as db:
                db.row_factory=sqlite3.Row
                view.value={'events':[dict(x) for x in db.execute('SELECT * FROM events ORDER BY seq')],
                            'physical':[x[0] for x in db.execute('SELECT object_ref FROM physical ORDER BY seq')]}
            validate_continuation(view)
            self.assertEqual(view.manifest,m)
            self.assertEqual(view.rows('attempts'),self.old.rows('attempts'))
            self.assertEqual(view.rows('commits'),self.old.rows('commits'))
            self.assertEqual(view.value['physical'],self.old.value['physical'])
            from src.smt_fullfab.harness.runtime import Runtime
            runtime=Runtime.resume_run(target)
            try:
                self.assertEqual(runtime.usage()['actual_model_attempts'],8)
                self.assertEqual(runtime.usage()['unknown_usage'],1)
                self.assertEqual(runtime.manifest['created_epoch'],m['created_epoch'])
                self.assertEqual(runtime.manifest['deadline_epoch'],m['deadline_epoch'])
                self.assertEqual(runtime.store.trace(),[self.old.get(r) for r in self.old.value['physical']])
                # The physical trace also contains 87 environment-owned delay
                # transitions; only the 18 plan-owned dispatches are B decisions.
                self.assertEqual(sum(e['kind']=='dispatch' and e.get('owner')=='plan' for e in runtime.store.trace()),18)
            finally:runtime.close()
            with self.assertRaises(HarnessError):continue_sealed_failure(self.root)
        self.assertEqual(sha_bytes((self.source/'evidence_manifest.json').read_bytes()),old_seal)
        self.assertFalse((target/'evidence_manifest.json').exists())

    def test_T22_31st_and_later_exception_no_longer_stop_on_quota(self):
        from tests.test_smt_fullfab_harness_amendment import AmendmentTests
        fixture=AmendmentTests('test_T22_30th_allowed_31st_refused_without_reset_or_new_call');fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for used in (30,300):
            p=fixture.clone(str(used));store=Store(p)
            try:
                m=store.read('manifest','run');runtime=SimpleNamespace(config=m['config'],manifest=m,store=store)
                aid,attempt=store.rows('attempts')[0]
                policy={**fixture.value['policy'],'max_failures_per_cohort':None}
                with patch('src.smt_fullfab.harness.recovery.policy_for',return_value=policy),patch('src.smt_fullfab.harness.recovery.cohort_recoveries',return_value={'prior':('micro',{str(i):{} for i in range(used)})}):
                    row=schedule_recovery(runtime,aid)
                self.assertEqual(row['cohort_failure_ordinal'],used+1)
                self.assertEqual(row['not_before_epoch'],attempt['finished_epoch']+60)
                self.assertEqual(store.rows('attempts'),[(aid,attempt)])
            finally:store.close()

    def test_T23_unknown_cost_remains_unknown_and_strict_audit_does_not_pass(self):
        cost=audit_cost(self.old)
        self.assertEqual((cost['actual_attempts'],cost['total_reported_tokens'],cost['unknown_usage']),(8,213207,1))
        self.assertFalse(cost['valid'])
        self.assertIsNone(cost['monetary_cost'])


if __name__=='__main__':unittest.main()
