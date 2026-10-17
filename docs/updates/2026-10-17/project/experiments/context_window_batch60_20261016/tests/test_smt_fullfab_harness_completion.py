"""Compare a fully recovered physical trajectory to an uninterrupted control."""
from pathlib import Path
from copy import deepcopy
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.smt_fullfab.harness.contracts import ROOT, default_config, digest, encode
from src.smt_fullfab.harness.runtime import Runtime
from src.smt_fullfab.harness.factory import capture
from src.smt_fullfab.harness.evaluation import seal_evidence, audit_run
from tests.test_smt_fullfab_harness import wait_delta, one_task, propose, apply


class CompletionBoundaryTests(unittest.TestCase):
    evidence = None

    def test_T18_recovered_full_window_matches_uninterrupted_trace_and_state(self):
        root = Path(tempfile.mkdtemp(prefix='harness-T18-full-window-'))
        cfg = default_config(seconds=120)
        cfg['period_seconds'] = 60
        prepared = Runtime.start_new(root / 'prepared', cfg, experiment_id='offline-T18-exact-control')
        try:
            apply(prepared, propose(prepared, wait_delta(prepared, tasks=[one_task(prepared)]))['candidate_ref'])
            committed_state = prepared.head['state_ref']
        finally:
            prepared.close()
        # The two copies are offline counterfactual fixtures, never separate
        # real-model accounts or scored experiments. They share the exact commit.
        for name in ('control', 'recovered'):
            shutil.copytree(root / 'prepared', root / name)
        control = Runtime.resume_run(root / 'control')
        recovered = None
        try:
            control.advance()
            child = '''import os,sys
from src.smt_fullfab.harness.runtime import Runtime
r=Runtime.resume_run(sys.argv[1])
def fault(point):
    if point == sys.argv[2]: os._exit(73)
r.store.fault=fault
r.advance()
raise RuntimeError('expected crash boundary not reached')
'''
            for point in ('during_physical_persist', 'during_trace_export'):
                result = subprocess.run([sys.executable, '-c', child, str(root / 'recovered'), point],
                                        cwd=ROOT, capture_output=True)
                self.assertEqual(result.returncode, 73, result.stderr.decode())
                recovered = Runtime.resume_run(root / 'recovered')
                if point == 'during_physical_persist':
                    self.assertEqual(recovered.head['state_ref'], committed_state)
                else:
                    self.assertEqual(recovered.env.t, 60)
                    self.assertEqual(capture(recovered.env), capture(control.env))
                    self.assertEqual(recovered.store.trace(), control.store.trace())
                recovered.close()
                recovered = None
            recovered = Runtime.resume_run(root / 'recovered')
            for runtime in (control, recovered):
                delta = wait_delta(runtime, version='explicit-second-window')
                apply(runtime, propose(runtime, delta, request='second-proposal')['candidate_ref'], request='second-apply')
                runtime.advance()
                self.assertEqual(runtime.env.t, 120)
                self.assertEqual(runtime.head['phase'], 'AUDITING')
            self.assertEqual(capture(recovered.env), capture(control.env))
            traces = [runtime.store.trace() for runtime in (control, recovered)]
            wall_measurements = []
            for trace in traces:
                # Original terminal telemetry deliberately measures real host
                # wall time; separate executions cannot have identical values.
                # Preserve both measurements, excluding exactly this field from
                # physical equality. No scheduling, event or state field is cut.
                self.assertEqual(trace[-1]['kind'], 'terminal')
                wall = trace[-1]['metrics'].pop('end_to_end_seconds')
                self.assertGreater(wall, 0)
                wall_measurements.append(wall)
            self.assertEqual(encode(traces[0]), encode(traces[1]))
            for runtime in (control, recovered):
                self.assertEqual((runtime.store.path / 'exports/trace.jsonl').read_bytes(),
                                 b''.join(encode(event) + b'\n' for event in runtime.store.trace()))
            reports = []
            for runtime in (control, recovered):
                self.assertEqual(runtime.usage()['actual_model_attempts'], 0)
                self.assertEqual(len(runtime.store.rows('commits')), 2)
                boundary = seal_evidence(runtime)
                report = audit_run(runtime.store.path, expected_sha256=boundary, output_dir=runtime.store.path / 'audit')
                self.assertTrue(report['valid'], report['errors'])
                reports.append(report)
            self.assertEqual(reports[0]['metrics'], reports[1]['metrics'])
            self.__class__.evidence = {
                'root': str(root), 'window_seconds': 120, 'physical_machines': 913,
                'crash_points': ['during_physical_persist', 'during_trace_export'],
                'real_process_exit_code': 73, 'actual_model_calls': 0,
                'physical_trace_sha256': digest(traces[0]),
                'terminal_state_sha256': digest(capture(control.env)),
                'physical_events': len(control.store.trace()),
                'physical_projection_byte_equality': True, 'terminal_state_equality': True,
                'excluded_telemetry_field': ['terminal', 'metrics', 'end_to_end_seconds'],
                'original_terminal_wall_measurements': wall_measurements,
                'independent_full_window_audits': [report['evidence_sha256'] for report in reports],
                'scope': 'Offline full 120-second recovery fixture, not a real B3600 result'}
            (root / 'comparison.json').write_bytes(encode(self.__class__.evidence))
        finally:
            control.close()
            if recovered is not None:
                recovered.close()


if __name__ == '__main__':
    unittest.main()
