"""Static-authored tiny M2 tests; root alone may execute the first batch.

The actual private loop, M1 clocks and original runner.crop_plan are exercised.
Factory, solver, bundle and snapshot dependencies are deliberately tiny fakes;
passing this suite is not certification of real physical or shared attribution.
No model transport or BudgetLedger object is used.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab import shared_controller as context_module
from src.smt_fullfab import hybrid as original_hybrid
from src.smt_fullfab.runner import crop_plan

HERE = Path(__file__).resolve().parent
from src.smt_fullfab import runner_shared as m
ss = context_module.ss


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def put(path, value):
    Path(path).write_bytes(m.canonical(value) + b'\n')
    return sha(path)


def window():
    return {'absolute_start': 61, 'absolute_end': 3661, 'physical_episode_end': 3661,
            'period_anchor': 61, 'period_seconds': 1800, 'plan_seconds': 14400, 'lookahead_depth': 2}


class TinyContext:
    def __init__(self, fixture, directory):
        self.owner = fixture; self.directory = directory
        directory.mkdir()
        # Match restore_shared_start's existing create-new branch claim exactly.
        # Physics, trace restoration and M1 receipts remain disclosed tiny fakes.
        self.branch_claim = {'schema': ss.SCHEMA + '-branch-claim',
            'branch_identity': {'arm': fixture.binding['arm'], 'run_id': fixture.binding['run_name'],
                'registration_sha256': fixture.binding['registration_document_sha256']},
            'shared_start_id': fixture.binding['shared_start_id'],
            'manifest_sha256': fixture.manifest_sha,
            'pid': m.os.getpid(), 'automatic_retry': False}
        self.branch_claim_sha256 = ss.publish(directory / 'claim.json', self.branch_claim)
        self.branch_claim_bytes = (directory / 'claim.json').read_bytes()
        self.t = 61; self.horizon = 3661; self.finished = False
        self.clock = context_module.AnchoredPeriodClock(window())
        self.commits = 0; self.advances = 0; self.poisoned = False
        self.events = []; self.targets = []; self.plans = []
        self.stops = list(fixture.stops)
        self.trace = [{'seq': 0, 'kind': 'fixture_prehistory', 'time': 0},
                      {'seq': 1, 'kind': 'restored_marker_fixture', 'time': 61}]
        self._trace()

    def _trace(self):
        (self.directory / 'trace.jsonl').write_bytes(b''.join(m.canonical(x) + b'\n' for x in self.trace))

    def status(self):
        if self.poisoned: raise RuntimeError('fixture context poisoned')
        return {'absolute_time': self.t, 'physical_horizon': self.horizon,
                'finished': self.finished, 'physical_scope': list(range(913))}

    def problem(self):
        self.events.append(('problem', self.t))
        return {'time': self.t, 'scope': list(range(913)),
                'machines': [{'machine': i} for i in range(913)], 'operations': [],
                'horizon_end': self.t + 14400}

    def commit_exact(self, plan, *, decision_evidence_ref):
        self.events.append(('commit', self.t)); self.commits += 1
        self.plans.append(deepcopy(plan))
        self.owner.assertEqual(sha(decision_evidence_ref['path']), decision_evidence_ref['sha256'])
        self.trace.append({'seq': len(self.trace), 'kind': 'plan_committed', 'time': self.t, 'plan': deepcopy(plan)})
        self._trace()
        if self.owner.commit_error:
            self.poisoned = True
            raise RuntimeError('commit outcome unknown after fixture mutation')
        mode = self.clock.committed(self.t)
        return {'mode_at_commit': mode, 'plan_sha256': m.digest(plan),
                'trace_event_index': len(self.trace) - 1, 'clock_after': self.clock.snapshot()}

    def advance_to_boundary(self):
        self.owner.assertGreater(self.commits, 0, 'advance must never precede first explicit commit')
        start = self.t; target = self.clock.advance_target(self.t)
        self.targets.append(target); self.events.append(('advance', target))
        if self.owner.advance_error:
            self.poisoned = True
            raise RuntimeError('advance outcome unknown')
        self.t = self.stops.pop(0)
        self.owner.assertLessEqual(self.t, target)
        self.finished = self.t == self.horizon; self.advances += 1
        self.trace.append({'seq': len(self.trace), 'kind': 'time_advance', 'time': start, 'to': self.t})
        self._trace()
        return {'start_time': start, 'advance_target': target,
                'stop': {'time': self.t, 'reason': 'terminal' if self.finished else 'fixture_stop'},
                'clock': self.clock.snapshot()}

    def evidence(self):
        return {'clock': self.clock.snapshot(), 'commits_observed': self.commits,
                'advances_observed': self.advances, 'poisoned': self.poisoned,
                'arm_attribution_certified': False, 'execution_resume_authorized': False}

    def write_checkpoint(self, new_path):
        self.owner.checkpoint_calls += 1
        if self.owner.checkpoint_error: raise OSError('fixture checkpoint failed')
        value = {'fixture_only': True, 't': self.t, 'horizon': self.horizon,
                 'finished': self.finished, 'plan': self.plans[-1] if self.plans else None,
                 'original_observation_start': 0, 'clock': self.clock.snapshot()}
        put(new_path, value)
        if self.owner.after_checkpoint: self.owner.after_checkpoint()
        return {'path': str(new_path), 'sha256': sha(new_path), 'state_sha256': m.digest(value),
                'bytes': new_path.stat().st_size, 'context_poisoned': self.poisoned,
                'clock': self.clock.snapshot(), 'execution_resume_authorized': False}


class SharedLoopFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve() / 'tiny'; self.base.mkdir()
        self.out = self.base / 'A_shared_tiny'; self.package = self.base / 'package'; self.package.mkdir()
        self.registration = self.base / 'offline_A_admission.json'; self.binding_path = self.base / 'binding.json'
        self.source_sha = '4' * 64
        self.config = {'schema': m.SCHEMA + '-config', 'arm': 'A', 'run_id': self.out.name,
            'seed': 1701, 'evaluation': window(), 'window_seconds': 3600,
            'wall_seconds': 120.0, 'max_plans': 10, 'solver_budget_seconds': 4.0,
            'max_log_bytes': 8000000, 'max_trace_bytes': 2000000, **m.ALGORITHM}
        self.manifest = {'evaluation_window': window(), 'shared_cost_reference': {
            'path': 'evidence/shared_cost.json', 'sha256': '9' * 64, 'shared_once': True}}
        self.manifest_sha = put(self.package / 'manifest.json', self.manifest)
        self.context = None; self.checkpoint_calls = 0; self.open_calls = 0
        self.commit_error = False; self.advance_error = False; self.checkpoint_error = False
        self.after_checkpoint = None; self.stops = [1861, 3661]
        self.tool_calls = []; self.tool_exception = None; self.tool_transform = None
        self.bundle_calls = []; self.bundle_error = False; self.bundle_read_calls = 0
        self.bundle_value = None
        self.runtime = SimpleNamespace(ss=ss, sources={}, source_paths={},
            context=SimpleNamespace(AnchoredPeriodClock=context_module.AnchoredPeriodClock,
                SharedHybridClock=context_module.SharedHybridClock, open_shared_run=self.open_context),
            hybrid=SimpleNamespace(configuration=original_hybrid.configuration, solve_hybrid_plan=self.solve),
            crop_plan=crop_plan,
            bundle=SimpleNamespace(audit_to_bundle=self.audit, read_bundle=self.read_bundle))
        self.save_admission()

    def save_admission(self):
        self.admission = {'schema': context_module.ADMISSION_SCHEMA, 'arm': 'A',
            'run_path': str(self.out), 'run_name': self.config['run_id'], 'seed': self.config['seed'],
            'window_seconds': self.config['window_seconds'], 'source_sha256': self.source_sha,
            'config_sha256': m.digest(self.config), 'solver_budget_seconds': self.config['solver_budget_seconds'],
            'wall_seconds': self.config['wall_seconds'], 'max_log_bytes': self.config['max_log_bytes'], 'model_calls': 0}
        admission_sha = put(self.registration, self.admission)
        self.binding = {'schema': context_module.BINDING_SCHEMA, 'shared_start_id': 'tiny_shared',
            'package_path': str(self.package), 'package_manifest_sha256': self.manifest_sha,
            'snapshot_sha256': '1' * 64, 'state_sha256': '2' * 64, 'prehistory_sha256': '3' * 64,
            'arm': 'A', 'run_name': self.out.name, 'run_path': str(self.out),
            'registration_kind': 'offline_A_admission', 'registration_path': str(self.registration),
            'registration_document_sha256': admission_sha, 'registration_id': None,
            'source_sha256': self.source_sha, 'config_sha256': m.digest(self.config),
            'evaluation': window(), 'window_seconds': self.config['window_seconds']}
        self.binding_sha = put(self.binding_path, self.binding)

    def open_context(self, package, **kwargs):
        self.assertEqual(package, self.package)
        self.assertEqual(kwargs, {'expected_manifest_sha256': self.manifest_sha,
            'branch_binding_path': self.binding_path, 'expected_binding_sha256': self.binding_sha,
            'output_dir': self.out, 'expected_source_sha256': self.source_sha})
        self.open_calls += 1; self.context = TinyContext(self, self.out)
        return self.context

    def solve(self, problem, **kwargs):
        self.tool_calls.append({'problem': deepcopy(problem), **deepcopy(kwargs)})
        if self.tool_exception is not None: raise self.tool_exception
        response = {'solver_status': 'FEASIBLE_HEURISTIC', 'nominal_audit': {'valid': True},
            'hybrid_mode': kwargs['mode'], 'hybrid_configuration': deepcopy(kwargs['config']),
            'cp_requested_seconds_reserved': kwargs['time_limit_seconds'],
            'wall_seconds': 0.02, 'solve_wall_seconds': 0.01,
            'classical_construction_wall_seconds': 0.005,
            'plan': {'version': kwargs['plan_version'], 'created_at': problem['time'],
                'valid_until': problem['horizon_end'], 'freeze_until': problem['time'],
                'scope': list(range(913)), 'tasks': [], 'holds': [], 'reason': 'tiny explicit A plan'}}
        if self.tool_transform: self.tool_transform(response)
        return response

    def audit(self, trace, **kwargs):
        self.bundle_calls.append({'trace': trace, **kwargs})
        if self.bundle_error: raise ValueError('fixture physical audit rejected')
        self.assertEqual(kwargs['expected_source_sha256'], sha(trace))
        self.assertEqual(kwargs['verify_data_dir'], self.package / 'data')
        self.assertEqual(kwargs['window_start'], 61)
        self.assertTrue(kwargs['require_terminal'])
        kwargs['output_dir'].mkdir()
        summary = {'valid': True, 'verified_input_hashes': True,
            'complete_physical_window_certified': True,
            'metrics': {'window_start': 61, 'window_end': 3661, 'tardy_lot_hours': 0,
                'throughput_lots': 0, 'terminal_WIP': 1, 'terminal_tardy_WIP': 0}}
        self.bundle_value = {'storage_verified': True, 'summary': summary,
            'source_receipt': {'sha256': sha(trace)}}
        manifest_sha = put(kwargs['output_dir'] / 'bundle_fixture.json', self.bundle_value)
        self.bundle_value['report_sha256'] = manifest_sha
        return deepcopy(self.bundle_value)

    def read_bundle(self, directory, *, expected_manifest_sha256):
        self.bundle_read_calls += 1
        self.assertEqual(expected_manifest_sha256, sha(directory / 'bundle_fixture.json'))
        return deepcopy(self.bundle_value)

    def execute(self, **overrides):
        return m._run_A_shared(config=self.config, package_dir=self.package,
            expected_manifest_sha256=self.manifest_sha, branch_binding_path=self.binding_path,
            expected_binding_sha256=self.binding_sha, output_dir=self.out,
            expected_source_sha256=self.source_sha, runtime=self.runtime, **overrides)

    def failed(self, result, message):
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['acceptance_eligible'])
        self.assertFalse(result['execution_resume_authorized'])
        self.assertIn(message, result['failure']['message'])

    def test_public_is_blocked_before_runtime_load(self):
        with patch.object(m, 'load_runtime') as load:
            with self.assertRaisesRegex(ValueError, 'execution blocked'):
                m.run_A_shared(source_root=self.base, context_path=self.base / 'absent')
            load.assert_not_called()

    def test_actual_loop_keeps_original_H_and_explicit_window(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed_pending_shared_audit')
        self.assertEqual(result['simulation_seconds'], 3600)
        self.assertEqual(result['physical_horizon'], 3661)
        self.assertEqual(result['metrics']['window_start'], 61)
        self.assertFalse(result['acceptance_eligible'])
        self.assertIsNone(result['branch_scope_audit'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['shared_generation_count_in_branch_cost'], 0)
        self.assertEqual(result['shared_generation_cost_reference'], self.manifest['shared_cost_reference'])
        self.assertEqual(self.open_calls, 1); self.assertEqual(self.checkpoint_calls, 1)
        self.assertEqual(self.context.events[:3], [('problem', 61), ('commit', 61), ('advance', 1861)])
        self.assertEqual(self.context.targets, [1861, 3661])
        self.assertEqual(self.bundle_read_calls, 2)

    def test_full_loop_preserves_restored_branch_claim_and_adds_controller_claim(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed_pending_shared_audit')
        self.assertIsNone(result['failure'])
        self.assertEqual(result['resources']['commit_receipts_confirmed'], 2)
        self.assertEqual(result['resources']['advance_receipts_confirmed'], 2)
        original = self.context.branch_claim
        self.assertEqual(set(original), {'schema', 'branch_identity', 'shared_start_id',
            'manifest_sha256', 'pid', 'automatic_retry'})
        self.assertEqual(original['schema'], ss.SCHEMA + '-branch-claim')
        self.assertEqual(original['branch_identity'], {'arm': 'A', 'run_id': self.out.name,
            'registration_sha256': self.binding['registration_document_sha256']})
        self.assertEqual(original['shared_start_id'], self.binding['shared_start_id'])
        self.assertEqual(original['manifest_sha256'], self.manifest_sha)
        self.assertIs(original['automatic_retry'], False)
        self.assertEqual((self.out / 'claim.json').read_bytes(), self.context.branch_claim_bytes)
        self.assertEqual(sha(self.out / 'claim.json'), self.context.branch_claim_sha256)
        self.assertEqual(read(self.out / 'claim.json'), original)
        controller = read(self.out / 'controller_claim.json')
        self.assertEqual(set(controller), {'pid', 'identity', 'started_at', 'arm',
            'registration_kind', 'registration_document_sha256'})
        self.assertIs(type(controller['pid']), int)
        self.assertEqual(controller['pid'], m.os.getpid())
        self.assertEqual(controller['identity'], m.digest(self.config))
        self.assertEqual(controller['arm'], 'A')
        self.assertEqual(controller['registration_kind'], 'offline_A_admission')
        self.assertEqual(controller['registration_document_sha256'],
                         self.binding['registration_document_sha256'])
        started = m.datetime.datetime.fromisoformat(controller['started_at'])
        self.assertEqual(started.utcoffset(), m.datetime.timedelta(0))
        self.assertNotEqual(sha(self.out / 'controller_claim.json'), self.context.branch_claim_sha256)
        self.assertFalse(result['acceptance_eligible'])

    def test_old_claim_destination_regression_fails_before_planning_without_clobber(self):
        original_write = m._write
        def old_destination(runtime, path, value):
            if path.name == 'controller_claim.json':
                path = path.with_name('claim.json')
            return original_write(runtime, path, value)
        # Reintroduce only the v1 destination in this temporary fixture. This is
        # not a replay of any real run or a claim that the old suite ran here.
        with patch.object(m, '_write', side_effect=old_destination):
            result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure']['type'], 'FileExistsError')
        self.assertEqual(result['resources']['planner_calls'], 0)
        self.assertEqual(self.tool_calls, [])
        self.assertEqual(self.context.commits, 0)
        self.assertEqual(self.context.advances, 0)
        self.assertEqual((self.out / 'claim.json').read_bytes(), self.context.branch_claim_bytes)
        self.assertEqual(sha(self.out / 'claim.json'), self.context.branch_claim_sha256)
        self.assertFalse((self.out / 'controller_claim.json').exists())
        self.assertFalse(result['acceptance_eligible'])

    def test_events_do_not_move_T0_absolute_clock(self):
        self.stops = [1800, 1860, 1861, 3661]
        result = self.execute()
        self.assertEqual([x['mode'] for x in self.tool_calls], ['periodic_cp', 'event_classical', 'event_classical', 'periodic_cp'])
        self.assertEqual([x['time_limit_seconds'] for x in self.tool_calls], [2.0, 0.0, 0.0, 2.0])
        self.assertEqual(self.context.targets, [1861, 1861, 1861, 3661])
        self.assertEqual(result['resources']['solver_requested_seconds'], 4.0)
        self.assertEqual(result['resources']['classical_event_calls'], 2)
        self.assertEqual(result['resources']['event_constructor_requested_seconds'], 10.0)
        for call in self.tool_calls:
            self.assertEqual(call['config']['anchor_time'], 0)
            self.assertEqual(call['seed'], 11)
        self.assertEqual(result['context_evidence']['clock']['evaluation']['period_anchor'], 61)

    def test_raw_candidate_is_preserved_and_original_crop_is_explicit(self):
        self.execute()
        raw = read(self.out / 'raw_plan_00000.json'); committed = read(self.out / 'committed_plan_00000.json')
        self.assertEqual(raw['valid_until'], 14461)
        self.assertEqual(committed, crop_plan(raw, SimpleNamespace(physical=set(range(913)), horizon=3661)))
        self.assertEqual(self.context.plans[0], committed)
        response = read(self.out / 'solver_00000.json')
        self.assertNotIn('hybrid_schedule', response)
        self.assertEqual(response['plan'], raw)
        decision = read(self.out / 'decision_00000.json')
        self.assertEqual(decision['raw_plan_ref']['sha256'], sha(self.out / 'raw_plan_00000.json'))
        self.assertEqual(decision['effective_period_clock_before']['next_period_index'], 0)

    def test_CP_exhaustion_stops_due_period_without_classical_fallback(self):
        self.config['solver_budget_seconds'] = 1.0; self.save_admission()
        result = self.execute()
        self.failed(result, 'periodic CP budget exhausted')
        self.assertEqual(len(self.tool_calls), 1)
        self.assertEqual(self.tool_calls[0]['time_limit_seconds'], 1.0)
        self.assertEqual(result['resources']['solver_requested_seconds'], 1.0)
        self.assertEqual(self.context.t, 1861)

    def test_unknown_inner_cost_is_not_zero_reported_as_known(self):
        self.tool_transform = lambda r: r.update(classical_construction_wall_seconds=None)
        result = self.execute(); value = result['resources']['inner_costs']['classical_construction_wall_seconds']
        self.assertEqual(value, {'known_sum': 0.0, 'unknown_count': 2})
        self.assertIsNone(read(self.out / 'solver_00000.json')['classical_construction_wall_seconds'])

    def test_planner_exception_preserves_reservation_and_does_not_retry(self):
        self.tool_exception = RuntimeError('tiny solver failed')
        result = self.execute(); self.failed(result, 'tiny solver failed')
        self.assertEqual(result['resources']['solver_requested_seconds'], 2.0)
        self.assertEqual(result['resources']['unclosed_tool_reservations'], 0)
        self.assertEqual(result['resources']['commit_attempts'], 0)
        self.assertEqual(len(self.tool_calls), 1)
        rows = [json.loads(line) for line in (self.out / 'resources.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in rows], ['solver_reserve', 'solver_finish'])
        self.assertEqual(rows[1]['solver_status'], 'EXCEPTION')

    def test_keyboard_interrupt_is_preserved_after_forensic_snapshot(self):
        self.tool_exception = KeyboardInterrupt('tiny interrupt')
        with self.assertRaisesRegex(KeyboardInterrupt, 'tiny interrupt'): self.execute()
        result = read(self.out / 'result.json')
        self.failed(result, 'tiny interrupt')
        self.assertEqual(self.checkpoint_calls, 1)

    def test_invalid_nominal_candidate_never_commits(self):
        self.tool_transform = lambda r: r.update(nominal_audit={'valid': False})
        result = self.execute(); self.failed(result, 'no fallback')
        self.assertEqual(self.context.commits, 0); self.assertEqual(self.context.targets, [])
        self.assertTrue((self.out / 'solver_00000.json').exists())

    def test_mode_mismatch_never_commits(self):
        self.tool_transform = lambda r: r.update(hybrid_mode='event_classical')
        result = self.execute(); self.failed(result, 'reservation differs')
        self.assertEqual(self.context.commits, 0)

    def test_unknown_commit_does_not_advance_and_is_not_retried(self):
        self.commit_error = True
        result = self.execute(); self.failed(result, 'commit outcome unknown')
        self.assertTrue(result['unknown_physical_outcome']); self.assertIsNone(result['absolute_time'])
        self.assertEqual(result['resources']['commit_attempts'], 1)
        self.assertEqual(result['resources']['commit_receipts_confirmed'], 0)
        self.assertEqual(self.context.commits, 1); self.assertEqual(self.context.targets, [])
        self.assertEqual(self.checkpoint_calls, 1)

    def test_caller_commit_receipt_io_failure_keeps_confirmed_counter(self):
        original = m._write
        def fail(runtime, path, value):
            if path.name == 'commit_00000.json': raise OSError('caller commit receipt disk failed')
            return original(runtime, path, value)
        with patch.object(m, '_write', side_effect=fail): result = self.execute()
        self.failed(result, 'caller commit receipt disk failed')
        self.assertEqual(result['resources']['commit_receipts_confirmed'], 1)
        self.assertFalse(result['unknown_physical_outcome'])
        self.assertEqual(self.context.targets, [])

    def test_unknown_advance_stops_without_replay(self):
        self.advance_error = True
        result = self.execute(); self.failed(result, 'advance outcome unknown')
        self.assertTrue(result['unknown_physical_outcome'])
        self.assertEqual(result['resources']['commit_receipts_confirmed'], 1)
        self.assertEqual(len(self.context.targets), 1)

    def test_caller_advance_receipt_io_failure_retains_actual_time(self):
        original = m._write
        def fail(runtime, path, value):
            if path.name == 'advance_00000.json': raise OSError('caller advance receipt disk failed')
            return original(runtime, path, value)
        with patch.object(m, '_write', side_effect=fail): result = self.execute()
        self.failed(result, 'caller advance receipt disk failed')
        self.assertEqual(result['absolute_time'], 1861)
        self.assertEqual(result['simulation_seconds'], 1800)
        self.assertEqual(result['resources']['advance_receipts_confirmed'], 1)

    def test_snapshot_failure_cannot_produce_completed_status(self):
        self.checkpoint_error = True
        result = self.execute(); self.failed(result, 'checkpoint')
        self.assertIsNone(result['checkpoint'])
        self.assertTrue((self.out / 'checkpoint_failure.json').exists())

    def test_terminal_audit_failure_preserves_snapshot_and_raw_trace(self):
        self.bundle_error = True
        result = self.execute(); self.failed(result, 'physical audit rejected')
        self.assertFalse(result['physical_audit_valid'])
        self.assertIsNotNone(result['checkpoint'])
        self.assertTrue((self.out / 'trace.jsonl').exists())

    def test_same_A_resume_config_is_not_accepted(self):
        self.config['snapshot_path'] = '/old/A/checkpoint.json'
        with self.assertRaisesRegex(ValueError, 'same-A snapshot resume'): self.execute()
        self.assertEqual(self.open_calls, 0)

    def test_stage_ledger_admission_is_not_a_fake_A_authority(self):
        self.binding['registration_kind'] = 'stage2_research_registration'; self.binding['registration_id'] = '6' * 64
        self.binding_sha = put(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, 'real offline-A admission'): self.execute()
        self.assertEqual(self.open_calls, 0)

    def test_admission_cap_tamper_rejected_before_restore(self):
        self.admission['solver_budget_seconds'] = 100
        self.binding['registration_document_sha256'] = put(self.registration, self.admission)
        self.binding_sha = put(self.binding_path, self.binding)
        with self.assertRaisesRegex(ValueError, 'admission limits'): self.execute()
        self.assertEqual(self.open_calls, 0)

    def test_existing_run_rejected_without_clobber(self):
        self.out.mkdir(); sentinel = self.out / 'old'; sentinel.write_bytes(b'old')
        with self.assertRaisesRegex(ValueError, 'existing run preserved'): self.execute()
        self.assertEqual(sentinel.read_bytes(), b'old'); self.assertEqual(self.open_calls, 0)

    def test_maxplans_failure_is_preserved_not_silently_extended(self):
        self.config['max_plans'] = 1; self.save_admission()
        result = self.execute(); self.failed(result, 'planner call cap reached')
        self.assertEqual(result['resources']['planner_calls'], 1)
        self.assertEqual(result['absolute_time'], 1861)

    def test_wall_exhaustion_before_restore_performs_no_factory(self):
        with patch.object(m.time, 'monotonic', return_value=1000): result = self.execute(started=0)
        self.failed(result, 'wall cap exhausted')
        self.assertEqual(self.open_calls, 0); self.assertFalse(self.out.exists())

    def test_original_manifest_replacement_after_checkpoint_is_rejected(self):
        self.after_checkpoint = lambda: put(self.package / 'manifest.json', {'replacement': True})
        result = self.execute(); self.failed(result, 'final resource/input check')

    def test_original_admission_replacement_after_checkpoint_is_rejected(self):
        self.after_checkpoint = lambda: put(self.registration, {'replacement': True})
        result = self.execute(); self.failed(result, 'final resource/input check')

    def test_original_trace_replacement_after_checkpoint_is_rejected(self):
        self.after_checkpoint = lambda: (self.out / 'trace.jsonl').write_bytes(b'{}\n')
        result = self.execute(); self.failed(result, 'final resource/input check')

    def test_bundle_member_replacement_after_checkpoint_is_rejected(self):
        self.after_checkpoint = lambda: put(self.out / 'audit_bundle' / 'bundle_fixture.json', {'replacement': True})
        result = self.execute(); self.failed(result, 'final resource/input check')

    def test_immediate_runtime_source_replacement_rejected(self):
        path = self.base / 'bound_source.py'; path.write_bytes(b'original')
        self.runtime.sources = {'bound_source.py': b'original'}
        self.runtime.source_paths = {'bound_source.py': path}
        self.after_checkpoint = lambda: path.write_bytes(b'changed')
        result = self.execute(); self.failed(result, 'original runtime source changed')

    def test_log_overshoot_after_forensic_checkpoint_remains_failed(self):
        self.after_checkpoint = lambda: (self.out / 'large_fixture.bin').write_bytes(b'x' * self.config['max_log_bytes'])
        result = self.execute(); self.failed(result, 'complete run byte cap exceeded')
        self.assertTrue((self.out / 'large_fixture.bin').exists())

    def test_no_historical_candidate_array_in_result_or_checkpoint_resources(self):
        result = self.execute()
        for value in (result['resources'], read(self.out / 'shared_checkpoint_resources.json')['resources']):
            self.assertNotIn('candidates', value); self.assertNotIn('responses', value)
        self.assertEqual(result['resources']['commit_receipts_confirmed'], 2)
        self.assertEqual(result['resources']['unclosed_tool_reservations'], 0)


if __name__ == '__main__': unittest.main()
