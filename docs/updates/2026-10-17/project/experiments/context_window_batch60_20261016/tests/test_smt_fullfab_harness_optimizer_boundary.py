"""Exercise the registered C optimizer gateway with a real bounded worker."""
from pathlib import Path
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import default_config, digest, encode
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.evaluation import seal_evidence, audit_run


class OptimizerBoundaryTests(unittest.TestCase):
    evidence = None

    def test_T26_real_optimizer_preserves_explicit_baseline_and_selection(self):
        root = Path(tempfile.mkdtemp(prefix='harness-C-optimizer-boundary-'))
        runtime = Runtime.start_new(root / 'run', default_config('C', seconds=60),
                                    experiment_id='offline-C-optimizer-boundary')
        try:
            context = runtime.head['context_ref']
            params = {'seed': 11, 'weights': {'tardiness': 100, 'completion': 10, 'flow': 1, 'setup': 1},
                      'max_slots_per_machine': 8, 'plan_version': 'explicit-constructive-baseline',
                      'valid_until': 60, 'freeze_until': 0}
            constructed = runtime.record_output({'tool': 'construct_candidate', 'request_id': 'construct',
                'context_ref': context, 'algorithm_id': 'constructive-gain-rate-v1',
                'parameters': params, 'budget_seconds': 5})
            self.assertEqual(constructed['status'], 'candidate_checked', constructed)
            baseline = runtime.store.read('candidates', constructed['candidate_ref'])
            optimized = runtime.record_output({'tool': 'optimize_candidate', 'request_id': 'optimize',
                'context_ref': context, 'algorithm_id': 'cp-global-explicit-baseline-v1',
                'candidate_ref': constructed['candidate_ref'],
                'parameters': {**params, 'max_slots_per_machine': 1, 'plan_version': 'explicit-cp-result'},
                'budget_seconds': 2})
            records = runtime.store.rows('classical_attempts')
            self.assertEqual(len(records), 2)
            record = records[-1][1]
            request = runtime.store.get(record['request_ref'])
            result = runtime.store.get(record['result_ref'])
            self.assertEqual(request['start_candidate'], baseline['compiled']['plan'])
            self.assertEqual(request['algorithm_id'], 'cp-global-explicit-baseline-v1')
            self.assertEqual(request['budget_seconds'], 2)
            self.assertEqual(request['parameters']['plan_version'], 'explicit-cp-result')
            self.assertEqual(record['automatic_retries'], 0)
            self.assertEqual(runtime.store.rows('commits'), [])
            if optimized['status'] == 'candidate_checked':
                candidate = runtime.store.read('candidates', optimized['candidate_ref'])
                self.assertEqual(candidate['compiled']['plan'], result['plan'])
                self.assertEqual(candidate['decision_owner'], 'algorithm')
                self.assertEqual(len(runtime.store.rows('candidates')), 2)
            else:
                self.assertEqual(optimized['status'], 'tool_failed', optimized)
                self.assertIn(optimized['solver_status'], ('TIMEOUT', 'UNKNOWN', 'NO_RESULT', 'INFEASIBLE'))
                self.assertEqual(len(runtime.store.rows('candidates')), 1)
            # A new output explicitly chooses the older checked baseline. The
            # optimizer result, feasible or not, has no selection side effect.
            applied = runtime.record_output({'tool': 'apply_candidate', 'request_id': 'select-baseline',
                'context_ref': context, 'candidate_ref': constructed['candidate_ref']})
            self.assertEqual(applied['status'], 'accepted', applied)
            self.assertEqual(runtime.env.plan, baseline['compiled']['plan'])
            self.assertGreater(runtime.advance()['dispatch_count_delta'], 0)
            boundary = seal_evidence(runtime)
            report = audit_run(root / 'run', expected_sha256=boundary, output_dir=root / 'run/audit')
            self.assertTrue(report['valid'], report['errors'])
            self.assertEqual(report['cost_accounting']['classical_attempts'], 2)
            self.assertEqual(report['cost_accounting']['actual_attempts'], 0)
            self.__class__.evidence = {'root': str(root), 'actual_model_calls': 0,
                'classical_attempts': 2, 'optimizer_status': optimized['status'],
                'solver_status': optimized.get('solver_status', optimized.get('summary', {}).get('solver_status')),
                'baseline_sha256': digest(baseline['compiled']['plan']), 'selected_baseline': True,
                'automatic_retries': 0, 'evidence_sha256': boundary,
                'scope': 'C gateway boundary only, not a quality or capacity benchmark'}
            (root / 'comparison.json').write_bytes(encode(self.__class__.evidence))
        finally:
            runtime.close()


if __name__ == '__main__':
    unittest.main()
