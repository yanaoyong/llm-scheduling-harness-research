"""Explicit quota removal, persistent unknowns and unchanged safety gates. No inference."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, default_config, digest, encode, fingerprint, sha_bytes, strict_json, validate_config
from src.smt_fullfab.harness.experiment import CONTINUATION_CAPS, UNCAPPED_MODEL_CAPS, continuation_authorization, registration, sealed_prior, cumulative_usage, check_experiment_budget, validate_admission
from src.smt_fullfab.harness.evaluation import Evidence, audit_cost, seal_evidence
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.p5 import prepare, validate_same_cohort
from tests import test_smt_fullfab_harness_continuation as continuation_tests


class OpenQuotaTests(unittest.TestCase):
    def setUp(self):
        self.helper = continuation_tests.ContinuationTests()
        self.helper.setUp()
        self.root = self.helper.root

    def build(self):
        value, adm, cfg = self.helper.grant_and_registration()
        grant_path = self.root / 'synthetic_grant.json'
        grant = strict_json(grant_path.read_bytes())
        grant.update(schema='harness-user-continuation-20261014-v2', caps=UNCAPPED_MODEL_CAPS,
                     unknown_usage_policy='freeze_new_calls', automatic_retries=0, max_attempts_per_fragment=None)
        grant_path.write_bytes(encode(grant))
        cfg['limits'].update(UNCAPPED_MODEL_CAPS['micro'])
        value.update(schema='harness-p5-registration-v4', caps=UNCAPPED_MODEL_CAPS, authorization=self.helper.reference(grant_path))
        value['cases']['new']['config_sha256'] = digest(cfg)
        (self.root / 'experiment.json').write_bytes(encode(value))
        adm['experiment_sha256'] = digest(value)
        return value, adm, cfg, grant_path

    def test_T23_only_explicit_token_attempt_grant_removes_limits(self):
        value, adm, cfg, grant_path = self.build()
        self.assertEqual(registration(adm), value)
        self.assertIsNone(validate_config(cfg)['limits']['tokens'])
        for group in CONTINUATION_CAPS:
            for field in ('model_seconds', 'wall_seconds'):
                self.assertEqual(value['caps'][group][field], CONTINUATION_CAPS[group][field])
        original = strict_json(grant_path.read_bytes())
        for key, val in [('unknown_usage_policy','ignore'), ('automatic_retries',1), ('full_B_new_run_limit',2), ('same_twenty_fragments',False)]:
            bad=deepcopy(original);bad[key]=val;grant_path.write_bytes(encode(bad))
            with self.assertRaisesRegex(HarnessError,'continuation_grant'):
                continuation_authorization(self.helper.reference(grant_path))
        bad=deepcopy(original);bad['caps']['micro']['wall_seconds']=None;grant_path.write_bytes(encode(bad))
        with self.assertRaisesRegex(HarnessError,'continuation_grant'):
            continuation_authorization(self.helper.reference(grant_path))
        for key in ('model_seconds','wall_seconds','same_read_limit','same_error_limit','zero_progress_limit','storage_bytes'):
            bad=deepcopy(cfg);bad['limits'][key]=None
            with self.assertRaisesRegex(HarnessError,'limits'):validate_config(bad)

    def test_T23_finite_registration_cannot_admit_null_run_ceiling(self):
        value, adm, cfg = self.helper.grant_and_registration()
        cfg['limits']['tokens']=None
        value['cases']['new']['config_sha256']=digest(cfg)
        (self.root/'experiment.json').write_bytes(encode(value));adm['experiment_sha256']=digest(value)
        with self.assertRaisesRegex(HarnessError,'case_budget'):
            validate_admission(adm,fingerprint(),cfg,None)

    def test_T23_counts_removed_but_time_and_unknown_still_fail_admission(self):
        value, adm, cfg, _ = self.build()
        runtime=Runtime.start_new(self.root/'run',cfg,experiment_id='synthetic-no-inference',mode='model',admission=adm)
        try:
            actual=cumulative_usage(adm)
            self.assertEqual(actual['combined']['tokens'],854879)  # retained real predecessor cost
            high=deepcopy(actual)
            for group in ('micro','combined'):
                high[group]['tokens']=10**12;high[group]['attempts']=10**6
            with patch('src.smt_fullfab.harness.experiment.cumulative_usage', return_value=high):
                check_experiment_budget(runtime,10**12)
                for field, val, error in [('unknown_usage',1,'experiment_unknown'),('pending',1,'experiment_unknown'),('model_seconds',3600,'experiment_time'),('wall_seconds',7200,'experiment_time')]:
                    altered=deepcopy(high);altered['micro'][field]=val
                    with patch('src.smt_fullfab.harness.experiment.cumulative_usage',return_value=altered):
                        with self.assertRaisesRegex(HarnessError,error):check_experiment_budget(runtime,100000)
            aid=runtime.reserve_attempt('synthetic request, never sent over network',{})
            runtime.mark_started(aid)  # fault injection only, no transport call
            runtime.save_response(aid,b'',usage=None,duration_seconds=.01)
            runtime.close();runtime=Runtime.resume_run(self.root/'run')
            self.assertEqual(runtime.usage()['unknown_usage'],1)
            with self.assertRaisesRegex(HarnessError,'unknown_attempt|stopped'):
                runtime.reserve_attempt('must not send',{})
            self.assertEqual(len(runtime.store.rows('attempts')),1)
            runtime.stop('synthetic-unknown-seal')
            sha=seal_evidence(runtime)
            cost=audit_cost(Evidence(runtime.store.path,sha))
            self.assertEqual(cost['unknown_usage'],1);self.assertFalse(cost['valid'])
        finally:runtime.close()

    def test_T01_new_quota_keeps_exact_twenty_tasks_states_and_other_guards(self):
        _, _, _, grant_path=self.build()
        target=self.root/'twenty'
        prep=prepare(target,authorization=grant_path)
        validate_same_cohort(target,prep)
        self.assertEqual(len([r for r in prep['cases'].values() if r['group']=='micro']),20)
        for case,row in prep['cases'].items():
            cfg=strict_json((target/(case+'.config.json')).read_bytes())
            self.assertIsNone(cfg['limits']['tokens']);self.assertIsNone(cfg['limits']['attempts'])
            self.assertEqual(cfg['limits']['same_read_limit'],3)
            self.assertEqual(cfg['limits']['zero_progress_limit'],3)
            if row['group']=='micro':self.assertIsNone(row['max_attempts_per_fragment'])
        changed=deepcopy(prep);changed['cases']['micro-02']['task']+=' hidden hint'
        with self.assertRaisesRegex(HarnessError,'same_cohort'):validate_same_cohort(target,changed)
        changed=deepcopy(prep);changed['cases']['micro-02']['max_attempts_per_fragment']=20
        with self.assertRaisesRegex(HarnessError,'case_budget'):validate_same_cohort(target,changed)

    def test_T23_actual_unknown_predecessor_cannot_be_carried_as_zero(self):
        source=ROOT/'artifacts/harness_v1_3_offline/closed_failure_snapshot.json'
        with self.assertRaisesRegex(HarnessError,'carry_unknown'):
            sealed_prior({'prior_cost_evidence':self.helper.reference(source)})
        report=strict_json((ROOT/'artifacts/harness_v1_3_offline/goal_acceptance.json').read_bytes())
        self.assertEqual(report['cumulative_usage']['combined']['attempts'],41)
        self.assertEqual(report['cumulative_usage']['combined']['tokens'],1592864)
        self.assertEqual(report['cumulative_usage']['combined']['unknown_usage'],1)
        self.assertEqual(report['full_B_starts_used'],0)
        self.assertFalse(report['goal_complete'])

if __name__=='__main__':unittest.main()
