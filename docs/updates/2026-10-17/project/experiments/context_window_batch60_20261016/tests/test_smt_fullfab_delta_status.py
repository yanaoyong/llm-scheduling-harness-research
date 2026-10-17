"""Small status fixtures; no actual gate, factory, model or original ledger."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_gate, status


class DeltaStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / 'runs/smt_fullfab_stage2' / B_delta_gate.RUN_ID
        self.folder.mkdir(parents=True)
        self.result = {
            'schema': 'smt-fullfab-B-delta-controller-v1-result',
            'config': {'run_id': B_delta_gate.RUN_ID, 'arm': 'B', 'seed': 1701,
                       'seconds': 3600, 'solver_budget_seconds': 0},
            'status': 'completed', 'accepted': False, 'failure': None,
            'finalization_errors': [], 'audit_valid': True,
            'delta_attribution_valid': True, 'simulation_seconds': 3600,
            'end_to_end_wall_seconds': 50.5, 'plans': 3, 'model_calls': 20,
            'solver_calls': 0, 'constructor_calls': 0,
            'metrics': {'weighted_tardy_lot_hours': 10, 'throughput_lots': 1,
                        'terminal_wip_lots': 2176, 'terminal_tardy_wip_lots': 10}}
        self.save_result()
        self.verified = {'valid': True, 'accepted': True, 'errors': [],
                         'acceptance': {'status': 'success', 'errors': [],
                                        'outer_wall_seconds': 65.25,
                                        'runner_result_sha256': status.file_hash(self.folder / 'result.json')}}

    def save_result(self):
        (self.folder / 'result.json').write_text(json.dumps(self.result))

    def read(self):
        with patch.object(B_delta_gate, 'read_acceptance', return_value=self.verified) as gate:
            result = status.delta_result_row(self.folder, self.result, root=self.root)
        gate.assert_called_once_with(root=self.root)
        return result

    def test_completed_endpoint_requires_outer_acceptance_and_uses_full_cost(self):
        row = self.read()
        self.assertEqual(row['status'], 'success')
        self.assertEqual(row['physical_status'], 'completed')
        self.assertTrue(row['full_window_completed'])
        self.assertEqual(row['wall_seconds'], 65.25)
        self.assertEqual(row['physical_result_wall_seconds'], 50.5)
        self.assertEqual(row['model_calls'], 20)
        self.assertEqual(row['solver_requested_seconds'], 0)
        self.assertFalse(self.result['accepted'])

    def test_missing_pending_or_failed_certificate_never_promotes_endpoint(self):
        for verified in ({'valid': False, 'accepted': False, 'errors': ['pending']},
                         {'valid': True, 'accepted': False, 'errors': [],
                          'acceptance': {**self.verified['acceptance'], 'status': 'failed',
                                         'errors': ['outer wall']}}):
            with self.subTest(verified=verified):
                self.verified = verified
                row = self.read()
                self.assertEqual(row['status'], 'failed')
                self.assertFalse(row['audit_valid'])
                self.assertFalse(row['full_window_completed'])
                self.assertEqual(row['model_calls'], 20)

    def test_original_result_changed_after_certificate_is_rejected(self):
        self.result['model_calls'] = 21
        self.save_result()
        self.assertFalse(self.read()['delta_supervisor_accepted'])

    def test_wrong_directory_or_schema_is_rejected(self):
        self.result['schema'] = 'foreign'
        self.save_result()
        self.verified['acceptance']['runner_result_sha256'] = status.file_hash(self.folder / 'result.json')
        self.assertFalse(self.read()['delta_supervisor_accepted'])
        other = self.root / 'elsewhere' / B_delta_gate.RUN_ID
        other.parent.mkdir()
        self.folder.rename(other)
        self.folder = other
        self.result['schema'] = 'smt-fullfab-B-delta-controller-v1-result'
        self.save_result()
        self.verified['acceptance']['runner_result_sha256'] = status.file_hash(self.folder / 'result.json')
        self.assertFalse(self.read()['delta_supervisor_accepted'])

    def test_failed_or_incomplete_endpoint_cannot_be_promoted_by_certificate(self):
        original = deepcopy(self.result)
        for change in ({'status': 'failed'}, {'simulation_seconds': 3500},
                       {'delta_attribution_valid': False}, {'audit_valid': False},
                       {'finalization_errors': ['failure']}, {'failure': 'timeout'}):
            with self.subTest(change=change):
                self.result = {**original, **change}
                self.save_result()
                self.verified['acceptance']['runner_result_sha256'] = status.file_hash(self.folder / 'result.json')
                row = self.read()
                self.assertFalse(row['full_window_completed'])
                self.assertEqual(row['status'], 'failed')

    def test_invalid_outer_timer_does_not_erase_measured_endpoint_cost(self):
        self.verified['accepted'] = False
        for value in (None, True, float('nan'), 1):
            with self.subTest(value=value):
                self.verified['acceptance']['outer_wall_seconds'] = value
                self.assertEqual(self.read()['wall_seconds'], 50.5)

    def test_early_failure_unknown_calls_and_missing_metrics_stay_unknown(self):
        self.result.update(status='failed', simulation_seconds=None, model_calls=None,
                           metrics=None, failure='registration failure')
        self.save_result()
        self.verified = {'valid': False, 'accepted': False, 'errors': ['not finalized']}
        row = self.read()
        self.assertIsNone(row['model_calls'])
        self.assertIsNone(row['throughput_lots'])
        self.assertEqual(row['failure'], 'registration failure')

    def test_separate_versions_use_their_own_certificate_without_reusing_v1(self):
        from src.smt_fullfab import B_delta_gate_v2, B_delta_gate_v3
        for version in (B_delta_gate_v2, B_delta_gate_v3):
            with self.subTest(run=version.RUN_ID):
                folder = self.folder.with_name(version.RUN_ID)
                self.folder.rename(folder)
                self.folder = folder
                self.result['config']['run_id'] = version.RUN_ID
                self.save_result()
                self.verified['acceptance']['runner_result_sha256'] = status.file_hash(folder / 'result.json')
                with patch.object(B_delta_gate, 'read_acceptance', side_effect=AssertionError('old gate must not be used')), \
                        patch.object(version, 'read_acceptance', return_value=self.verified) as gate:
                    row = status.delta_result_row(folder, self.result, root=self.root)
                gate.assert_called_once_with(root=self.root)
                self.assertEqual(row['run_id'], version.RUN_ID)
                self.assertTrue(row['delta_supervisor_accepted'])


if __name__ == '__main__':
    unittest.main()
