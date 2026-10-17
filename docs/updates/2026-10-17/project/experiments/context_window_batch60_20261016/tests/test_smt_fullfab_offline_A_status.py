"""Stage gates must not certify A before the outer resource audit completes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab.offline_A_gate import RUN_ID
from src.smt_fullfab.status import apply_offline_A_gate, file_hash


class OfflineAStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'runs/smt_fullfab_development' / RUN_ID
        self.run.mkdir(parents=True)
        (self.run / 'result.json').write_text(json.dumps({'status': 'success'}))
        self.row = dict(status='success', audit_valid=True, wall_seconds=99,
                        full_window_completed=True, failure=None)
        self.verified = dict(valid=True, accepted=True, status='success', errors=[],
                             result_sha256=file_hash(self.run / 'result.json'),
                             acceptance={'outer_wall_seconds': 103, 'errors': []})

    def check(self, verified=None, folder=None, row=None):
        with patch('src.smt_fullfab.offline_A_gate.read_acceptance',
                   return_value=self.verified if verified is None else verified):
            return apply_offline_A_gate(self.row if row is None else row,
                                        self.run if folder is None else folder, root=self.root)

    def test_completed_verified_run_uses_outer_time(self):
        actual = self.check()
        self.assertEqual(actual['status'], 'success')
        self.assertTrue(actual['audit_valid'])
        self.assertEqual(actual['wall_seconds'], 103)
        self.assertEqual(actual['physical_result_wall_seconds'], 99)

    def test_result_before_acceptance_or_after_crash_cannot_pass(self):
        actual = self.check(dict(valid=False, accepted=False, status='unverified',
                                 errors=['acceptance file is missing']))
        self.assertEqual(actual['status'], 'failed')
        self.assertFalse(actual['audit_valid'])
        self.assertIn('acceptance file is missing', actual['offline_supervisor_errors'])

    def test_outer_resource_failure_cannot_be_hidden_by_runner_success(self):
        verified = copy.deepcopy(self.verified)
        verified.update(accepted=False, status='failed')
        verified['acceptance']['errors'] = ['final total evidence exceeds8GiB']
        actual = self.check(verified)
        self.assertFalse(actual['offline_supervisor_accepted'])
        self.assertEqual(actual['status'], 'failed')
        self.assertIn('final total evidence exceeds8GiB', actual['offline_supervisor_errors'])

    def test_a_modified_result_cannot_reuse_the_certificate(self):
        (self.run / 'result.json').write_text('{"status":"success","changed":true}')
        self.assertFalse(self.check()['audit_valid'])

    def test_certificate_cannot_certify_a_same_named_other_run(self):
        other = self.root / 'runs/smt_fullfab_stage2' / RUN_ID
        other.mkdir(parents=True)
        (other / 'result.json').write_bytes((self.run / 'result.json').read_bytes())
        self.assertFalse(self.check(folder=other)['audit_valid'])

    def test_raw_failed_result_is_never_promoted(self):
        actual = self.check(row={**self.row, 'status': 'failed', 'audit_valid': False, 'failure': 'physical_failure'})
        self.assertEqual(actual['status'], 'failed')
        self.assertFalse(actual['audit_valid'])
        self.assertEqual(actual['failure'], 'physical_failure')

    def test_historical_A_remains_unchanged_and_needs_no_new_certificate(self):
        with patch('src.smt_fullfab.offline_A_gate.read_acceptance', side_effect=AssertionError('unexpected read')):
            actual = apply_offline_A_gate(self.row, self.run.parent / 'A_1701_1h_hybrid_v1', root=self.root)
        self.assertEqual(actual, self.row)


if __name__ == '__main__':
    unittest.main()
