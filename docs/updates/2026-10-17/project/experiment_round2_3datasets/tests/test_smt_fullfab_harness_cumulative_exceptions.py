"""Cumulative exact grants retain unknown costs; no real model calls."""
from copy import deepcopy
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, encode, digest, fingerprint, sha_bytes, strict_json, default_config
from src.smt_fullfab.harness.experiment import sealed_prior, resource_status, registration, cumulative_usage, check_experiment_budget, UNCAPPED_MODEL_CAPS
from src.smt_fullfab.harness.evaluation import Evidence, audit_cost
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.p5 import prepare, validate_same_cohort, micro


class CumulativeExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='offline-cumulative-exceptions-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.grant_path = ROOT / 'artifacts/harness_v1_6_offline/authorization.json'
        self.grant = strict_json(self.grant_path.read_bytes())

    def ref(self, path):
        return {'path': str(path), 'sha256': sha_bytes(path.read_bytes())}

    def value(self, path=None):
        return {'authorization': self.ref(path or self.grant_path), 'prior_cost_evidence': self.grant['prior_cost_evidence']}

    def test_T23_two_exact_exceptions_retain_every_cost_and_failed_audit(self):
        usage, starts, ids = sealed_prior(self.value())
        self.assertEqual((usage['combined']['attempts'], usage['combined']['tokens'], usage['combined']['unknown_usage'], starts, len(ids)), (43, 1629872, 2, 0, 8))
        disclosure = resource_status(self.value(), usage)
        self.assertEqual(disclosure['authorized_historical_unknown_usage']['combined'], 2)
        self.assertEqual(disclosure['unexempt_unknown_usage']['combined'], 0)
        self.assertFalse(disclosure['cumulative_cost_closed'])
        self.assertTrue(disclosure['reported_tokens_are_lower_bound'])
        for item in self.grant['historical_unknown_exceptions']:
            boundary = item['boundary']
            evidence = Evidence(Path(boundary['path']).parent, boundary['sha256'])
            self.assertIsNone(evidence.rows('attempts')[item['attempt_id']]['usage'])
            self.assertFalse(audit_cost(evidence)['valid'])
            self.assertEqual(audit_cost(evidence)['unknown_usage'], 1)

    def test_T23_extension_cannot_replace_duplicate_discount_or_broaden_history(self):
        variants = []
        for index, key, val in [(0, 'events_sha256', '0'*64), (1, 'attempt_id', 'attempt:future'), (1, 'unreported_usage', 0), (1, 'retry_original', True), (1, 'scope', 'all_future')]:
            grant = deepcopy(self.grant)
            grant['historical_unknown_exceptions'][index][key] = val
            variants.append(grant)
        for exceptions in [self.grant['historical_unknown_exceptions'][:1], self.grant['historical_unknown_exceptions'][1:]*2, self.grant['historical_unknown_exceptions']*2]:
            grant = deepcopy(self.grant)
            grant['historical_unknown_exceptions'] = exceptions
            variants.append(grant)
        grant = deepcopy(self.grant)
        grant['schema'] = 'harness-user-continuation-20261014-v3'
        variants.append(grant)
        for i, grant in enumerate(variants):
            path = self.root / f'bad-{i}.json'
            path.write_bytes(encode(grant))
            with self.assertRaises(HarnessError, msg=str(i)):
                sealed_prior(self.value(path))
        original = strict_json(Path(self.grant['prior_cost_evidence']['path']).read_bytes())
        for key in ['tokens', 'unknown_usage']:
            changed = deepcopy(original)
            changed['cumulative_usage']['micro'][key] -= 1
            path = self.root / f'discount-{key}.json'
            path.write_bytes(encode(changed))
            with self.assertRaisesRegex(HarnessError, 'carry_totals'):
                sealed_prior({**self.value(), 'prior_cost_evidence': self.ref(path)})
        with self.assertRaisesRegex(HarnessError, 'carry_ancestor_missing'):
            sealed_prior({**self.value(), 'prior_cost_evidence': original['cohorts'][0]})

    def test_T23_third_persistent_unknown_freezes_new_calls_and_resume(self):
        cfg = default_config(seconds=60)
        cfg['limits'].update(UNCAPPED_MODEL_CAPS['micro'])
        fp = fingerprint()
        proof = self.root / 'proof.json'
        proof.write_bytes(encode({'gates': {g: 'pass' for g in ['G0', 'G1', 'G2', 'G3', 'G4']}, 'fingerprint_sha256': fp['sha256'], 'test_only': True}))
        value = {**self.value(), 'schema': 'harness-p5-registration-v6', 'caps': UNCAPPED_MODEL_CAPS, 'full_B_new_run_limit': 1, 'cases': {'new': {'group': 'micro', 'config_sha256': digest(cfg), 'initial_state_sha256': None}}, 'fingerprint_sha256': fp['sha256'], 'engineering_report': str(proof), 'engineering_report_sha256': sha_bytes(proof.read_bytes()), 'cli_binary': '/never/invoked', 'cli_sha256': 'offline-only'}
        (self.root/'experiment.json').write_bytes(encode(value))
        adm = {'experiment_directory': str(self.root), 'experiment_sha256': digest(value), 'case_id': 'new', 'group': 'micro', 'cli_binary': '/never/invoked', 'cli_sha256': 'offline-only'}
        self.assertEqual(registration(adm), value)
        r = Runtime.start_new(self.root/'new', cfg, experiment_id='synthetic-no-inference', mode='model', admission=adm)
        try:
            check_experiment_budget(r, 100000)
            aid = r.reserve_attempt('synthetic never sent', {})
            r.mark_started(aid)
            r.save_response(aid, b'', usage=None, duration_seconds=.01)
            self.assertEqual(cumulative_usage(adm)['combined']['unknown_usage'], 3)
            with self.assertRaisesRegex(HarnessError, 'experiment_unknown'):
                check_experiment_budget(r, 100000)
            r.close()
            r = Runtime.resume_run(self.root/'new')
            with self.assertRaises(HarnessError):
                r.reserve_attempt('blocked', {})
            self.assertEqual(len(r.store.rows('attempts')), 1)
        finally:
            r.close()

    def test_T01_v6_same_twenty_and_failed_member_cannot_be_skipped(self):
        target = self.root/'twenty'
        with redirect_stdout(io.StringIO()):
            prep = prepare(target, authorization=self.grant_path)
        validate_same_cohort(target, prep)
        self.assertEqual(sum(x['group'] == 'micro' for x in prep['cases'].values()), 20)
        value = {**self.value(), 'schema': 'harness-p5-registration-v6', 'cases': prep['cases'], 'caps': UNCAPPED_MODEL_CAPS, 'full_B_new_run_limit': 1, 'cli_binary': '/never/invoked', 'cli_sha256': 'offline-only', 'model_catalog': '/unused', 'model_catalog_sha256': 'unused'}
        (target/'experiment.json').write_bytes(encode(value))
        fail = target/'runs/micro-01'
        fail.mkdir(parents=True)
        (fail/'fragment_result.json').write_bytes(encode({'id': 'micro-01', 'attempts': 2, 'accepted': False}))
        with patch('src.smt_fullfab.harness.p5.open_case', side_effect=AssertionError('must not skip failure')):
            gate = micro(target)
        self.assertFalse(gate['pass'])
        self.assertEqual(len(gate['fragments']), 20)
        self.assertEqual(gate['cost_disclosure']['authorized_historical_unknown_usage']['micro'], 2)
        self.assertEqual(gate['usage']['B3600']['attempts'], 0)


if __name__ == '__main__':
    unittest.main()
