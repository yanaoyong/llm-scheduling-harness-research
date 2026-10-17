"""Model-switch accounting controls against retained real evidence; no inference."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, HarnessError, encode, sha_bytes, strict_json
from src.smt_fullfab.harness.model_switch import carried_costs, validate_registration


class ModelSwitchTests(unittest.TestCase):
    def setUp(self):
        self.out = ROOT / 'artifacts/harness_sol_acceptance'
        self.reg = strict_json((self.out / 'registration_draft.json').read_bytes())
        self.root = Path(self.reg['experiment_directory'])

    def test_T23_all_47_historical_runs_and_imported_response_count_once(self):
        usage, starts, ids = carried_costs(self.reg)
        self.assertEqual((len(ids), starts), (47, 0))
        self.assertEqual(usage['combined']['attempts'], 194)
        self.assertEqual(usage['combined']['tokens'], 7007840)
        self.assertEqual(usage['combined']['unknown_usage'], 11)
        self.assertEqual(usage['combined']['pending'], 0)

    def test_T23_discount_omission_duplicate_and_unknown_erasure_rejected(self):
        original = strict_json(Path(self.reg['prior_cost_evidence']['path']).read_bytes())
        for mode in ('discount', 'omit', 'duplicate', 'unknown'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                value = deepcopy(original)
                if mode == 'discount': value['cumulative_usage']['combined']['tokens'] -= 1
                if mode == 'omit': value['runs'].pop()
                if mode == 'duplicate': value['runs'].append(deepcopy(value['runs'][0]))
                if mode == 'unknown': value['additional_unknown_attempts'].pop()
                path = Path(td) / 'snapshot.json'
                path.write_bytes(encode(value))
                reg = deepcopy(self.reg)
                reg['prior_cost_evidence'] = {'path':str(path),'sha256':sha_bytes(path.read_bytes())}
                with self.assertRaises(HarnessError): carried_costs(reg)

    def test_T20_exact_new_model_and_unchanged_original_twenty_valid(self):
        self.assertEqual(validate_registration(self.reg, self.root), self.reg)

    def test_T20_model_metric_budget_and_B_quota_changes_rejected(self):
        for mode in ('model', 'metric', 'budget', 'B_quota', 'sample'):
            with self.subTest(mode=mode):
                reg = deepcopy(self.reg)
                if mode == 'model': reg['model']['name'] = 'gpt-6-astra'
                if mode == 'metric': reg['micro_metrics']['p95_max'] = 6
                if mode == 'budget': reg['caps']['micro']['model_seconds'] += 1
                if mode == 'B_quota': reg['full_B_new_run_limit'] = 2
                if mode == 'sample': reg['cases']['micro-10']['task'] += 'different task'
                with self.assertRaises(HarnessError): validate_registration(reg, self.root)

    def test_T20_duplicate_execution_order_is_rejected(self):
        reg = deepcopy(self.reg)
        reg['execution_order'][-1] = reg['execution_order'][0]
        with self.assertRaises(HarnessError): validate_registration(reg, self.root)


if __name__ == '__main__':
    unittest.main()
