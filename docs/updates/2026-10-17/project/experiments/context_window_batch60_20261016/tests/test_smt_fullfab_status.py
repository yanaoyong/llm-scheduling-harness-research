import json
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.status import file_hash, recovery_acceptance
from src.smt_fullfab.budget import record_sha256


class RecoveryAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = {'parent_run_id':'parent', 'segment_run_id':'segment',
                       'registration_id':'registration', 'recovery_segment_id':'recovery',
                       'status':'success', 'audit_valid':True, 'full_window_completed':True}
        self.write('result.json', self.result)
        self.write('recovery_audit.json', {'valid':True,'successful_full_window':True})
        self.accepted = {'schema':'smt-fullfab-recovery-acceptance-v1',
                         **{key:self.result[key] for key in ('parent_run_id','segment_run_id',
                                                           'registration_id','recovery_segment_id')},
                         'result_sha256':file_hash(self.root/'result.json'),
                         'recovery_audit_sha256':file_hash(self.root/'recovery_audit.json'),
                         'accepted':True, 'status':'success', 'physical_success':True,
                         'controller_evidence_valid':True, 'successful_full_window':True}
        self.write('acceptance.json', self.accepted)

    def write(self, name, content):
        (self.root/name).write_text(json.dumps(content))

    def check(self):
        final = {**{key:self.result[key] for key in ('parent_run_id','segment_run_id',
                                                    'registration_id','recovery_segment_id')},
                 'acceptance_sha256':file_hash(self.root/'acceptance.json')
                     if (self.root/'acceptance.json').exists() else None,'accepted':True}
        final['finalization_id']=record_sha256(final)
        return recovery_acceptance(self.root,self.result,[{'event':'recovery_segment_finalized','finalization':final}])

    def test_verified_recovery_can_pass(self):
        self.assertTrue(self.check()['accepted'])

    def test_physical_success_without_attribution_does_not_pass(self):
        (self.root/'acceptance.json').unlink()
        self.assertFalse(self.check()['accepted'])

    def test_modified_result_does_not_pass_old_acceptance(self):
        self.write('result.json', {**self.result, 'model_calls':99})
        self.assertFalse(self.check()['accepted'])

    def test_modified_audit_does_not_pass_old_acceptance(self):
        self.write('recovery_audit.json', {'valid':True, 'extra':'changed'})
        self.assertFalse(self.check()['accepted'])

    def test_recovery_from_other_parent_is_rejected(self):
        self.write('acceptance.json', {**self.accepted, 'parent_run_id':'different'})
        self.assertFalse(self.check()['accepted'])

    def test_failure_cannot_be_promoted_by_acceptance(self):
        self.result['full_window_completed'] = False
        self.write('result.json', self.result)
        self.accepted['result_sha256'] = file_hash(self.root/'result.json')
        self.write('acceptance.json', self.accepted)
        self.assertFalse(self.check()['accepted'])

    def test_self_consistent_failed_attribution_remains_failure(self):
        self.write('recovery_audit.json', {'valid':False})
        self.accepted['recovery_audit_sha256'] = file_hash(self.root/'recovery_audit.json')
        self.write('acceptance.json', self.accepted)
        self.assertFalse(self.check()['accepted'])

    def test_resource_overrun_cannot_pass(self):
        self.write('acceptance.json', {**self.accepted, 'resource_overrun':True})
        self.assertFalse(self.check()['accepted'])

    def test_post_execution_audit_time_is_reported(self):
        self.write('acceptance.json', {**self.accepted, 'segment_final_wall_seconds':12.5})
        self.assertEqual(self.check()['end_to_end_wall_seconds'],12.5)

    def test_missing_final_cost_event_rejects_otherwise_successful_run(self):
        self.assertFalse(recovery_acceptance(self.root,self.result)['accepted'])

    def test_finalization_error_rejects_otherwise_successful_run(self):
        self.write('resource_finalization_error.json', {'error':'failed to append'})
        self.assertFalse(self.check()['accepted'])


if __name__ == '__main__':
    unittest.main()
