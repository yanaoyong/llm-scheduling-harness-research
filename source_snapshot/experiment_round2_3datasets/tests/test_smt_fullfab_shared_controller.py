"""STATIC-AUTHORED tests. No real factory/model/solver/ledger.

Uses the real Branch facade with a deliberately tiny fake environment/observer.
Package verification and restore are fixture stubs, NOT physical validity proof.
Do not run before the root grants a serial validation window.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import shared_controller as m
ss = m.ss


def raw(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def window():
    return {'absolute_start': 61, 'absolute_end': 3661, 'physical_episode_end': 3661,
            'period_anchor': 61, 'period_seconds': 1800, 'plan_seconds': 14400, 'lookahead_depth': 2}


class FakeWriter:
    @staticmethod
    def _state_view(env):
        return {'seed': env.seed, 'horizon': env.horizon, 't': env.t, 'finished': env.finished,
                'observation_start': env.observation_start, 'plan': env.plan, 'trace': env.trace,
                'jobs': env.jobs, 'queue': env.queue, 'executed': sorted(env.executed_tasks)}

    @staticmethod
    def _chunks(value):
        yield ss.canonical(value)


class FakeObservation:
    @staticmethod
    def build_problem(env, *, plan_seconds, lookahead_depth):
        return {'time': env.t, 'horizon_end': env.t + plan_seconds,
                'scope': sorted(env.physical), 'machines': [{'machine': i} for i in sorted(env.physical)],
                'operations': [{'operation_id': 'current:1:0', 'step': 1}],
                'frozen_tasks': [], 'fixture_depth': lookahead_depth}


class FakeEnv:
    def __init__(self):
        self.seed = 1701
        self.horizon = 3661.0  # Actual environment uses float even if contract used int.
        self.t = 61.0
        self.observation_start = 0.0
        self.finished = False
        self.physical = set(range(913))
        self.manifest = {'horizon': self.horizon, 'seed': self.seed}
        self.plan = {'version': 'warmup', 'created_at': 30, 'valid_until': 61, 'freeze_until': 30,
            'scope': sorted(self.physical), 'reason': 'original warmup',
            'tasks': [{'id': 'already_done', 'machine': 0, 'lot_ids': ['L0'], 'steps': [1],
                       'visits': [1], 'not_before': 30},
                      {'id': 'pending_without_operation_ids', 'machine': 1, 'lot_ids': ['L1'],
                       'steps': [1], 'visits': [1], 'not_before': 60}],
            'holds': [{'machine': 0, 'until': 61, 'after_task_id': 'already_done', 'reason': 'old'}]}
        self.executed_tasks = {('warmup', 'already_done')}
        self.jobs = {7: {'done': False, 'process_end': 90, 'lot_ids': ['L0']}}
        self.queue = [[90, 1, 'completion', 7]]
        self.trace = [{'seq': 0, 'kind': 'initial', 'time': 0}]
        self.active_task = None
        self.commit_calls = 0
        self.advance_calls = []
        self.early_stop = None
        self.fail_commit_after_mutation = False
        self.fail_advance = False

    def commit_plan(self, plan):
        self.commit_calls += 1
        self.plan = deepcopy(plan)
        self.trace.append({'seq': len(self.trace), 'time': self.t, 'kind': 'plan_committed', 'plan': deepcopy(plan)})
        if self.fail_commit_after_mutation:
            raise RuntimeError('unknown after physical fake mutation')
        return ss.digest(plan)

    def advance_plan(self, target):
        self.advance_calls.append(target)
        if self.fail_advance:
            raise RuntimeError('unknown advance')
        end = self.early_stop if self.early_stop is not None else target
        self.trace.append({'seq': len(self.trace), 'time': self.t, 'kind': 'time_advance', 'to': end})
        self.t = end
        self.finished = end == self.horizon
        reason = 'terminal' if self.finished else 'periodic_replan' if end == target else 'route/visit changed'
        return {'time': end, 'reason': reason}


class ContextFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / '场景'
        self.root.mkdir()
        self.package = self.root / 'package'
        self.package.mkdir()
        self.out = self.root / 'B_shared_test'
        self.binding_path = self.root / 'binding.json'
        self.registration_path = self.root / 'registration.json'
        self.env = FakeEnv()
        self.manifest = {'shared_start_id': 'shared_fixture', 'snapshot_sha256': '1' * 64,
            'state_sha256': '2' * 64, 'prehistory_receipt': {'sha256': '3' * 64},
            'evaluation_window': window(), 'contract': {'seed': 1701}}
        self.manifest_raw = raw(self.manifest)
        (self.package / 'manifest.json').write_bytes(self.manifest_raw)
        self.registration = {'amendment_id': 'existing', 'budget_id': 'budget', 'run_id': str(self.out),
            'arm': 'B', 'scenario': 1701, 'window_seconds': 3600, 'solver_seconds': 0,
            'wall_seconds': 100, 'max_log_bytes': 10000000, 'phase': 'stage2_research', 'formal': False}
        self.binding = {'schema': m.BINDING_SCHEMA, 'shared_start_id': 'shared_fixture',
            'package_path': str(self.package), 'package_manifest_sha256': sha(self.manifest_raw),
            'snapshot_sha256': '1' * 64, 'state_sha256': '2' * 64, 'prehistory_sha256': '3' * 64,
            'arm': 'B', 'run_name': self.out.name, 'run_path': str(self.out),
            'registration_kind': 'stage2_research_registration', 'registration_path': str(self.registration_path),
            'registration_document_sha256': '', 'registration_id': '', 'source_sha256': '4' * 64,
            'config_sha256': '5' * 64, 'evaluation': window(), 'window_seconds': 3600}
        self.save_registration()
        self.save_binding()
        self.read_mock = patch.object(ss, 'read_shared_start', side_effect=lambda *a, **k: deepcopy(self.manifest))
        self.restore_mock = patch.object(ss, 'restore_shared_start', side_effect=self.fake_restore)
        self.reader = self.read_mock.start()
        self.restorer = self.restore_mock.start()
        self.addCleanup(self.read_mock.stop)
        self.addCleanup(self.restore_mock.stop)

    def save_registration(self):
        self.registration.pop('registration_id', None)
        if self.binding['arm'] in ('B', 'C'):
            rid = sha(json.dumps(self.registration, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':'), allow_nan=False).encode())
            self.registration['registration_id'] = rid
            self.binding['registration_id'] = rid
        else:
            self.binding['registration_id'] = None
        data = raw(self.registration)
        self.registration_path.write_bytes(data)
        self.binding['registration_document_sha256'] = sha(data)

    def save_binding(self):
        data = raw(self.binding)
        self.binding_path.write_bytes(data)
        self.binding_sha = sha(data)

    def fake_restore(self, package, *, expected_manifest_sha256, branch_dir, branch_identity):
        self.assertEqual(package, self.package)
        branch_dir.mkdir(exist_ok=False)
        marker = {'seq': len(self.env.trace), 'time': 61, 'kind': 'snapshot_loaded',
                  'snapshot_sha256': self.manifest['state_sha256'], 'prefix_event_count': len(self.env.trace)}
        self.env.trace.append(marker)
        problem = FakeObservation.build_problem(self.env, plan_seconds=14400, lookahead_depth=2)
        receipt = {'shared_start_id': self.manifest['shared_start_id'],
            'package_manifest_sha256': expected_manifest_sha256,
            'snapshot_sha256': self.manifest['snapshot_sha256'],
            'original_state_sha256': self.manifest['state_sha256'],
            'restored_state_with_marker_sha256': ss.digest(FakeWriter._state_view(self.env)),
            'evaluation_window': window(), 'first_public_problem_sha256': ss.digest(problem),
            'branch_identity': deepcopy(branch_identity)}
        digest = ss.publish(branch_dir / 'start_receipt.json', receipt)
        ss.publish(branch_dir / 'claim.json', {'fixture': True, 'branch_identity': branch_identity})
        return ss.Branch(self.env, FakeWriter, FakeObservation, branch_dir, {**receipt, 'receipt_sha256': digest})

    def open_context(self):
        return m.open_shared_run(self.package, expected_manifest_sha256=sha(self.manifest_raw),
            branch_binding_path=self.binding_path, expected_binding_sha256=self.binding_sha,
            output_dir=self.out, expected_source_sha256='4' * 64)

    def decision(self, context, version='new'):
        data = b'{"synthetic_decision":true}\n'
        path = self.out / (version + '.decision.json')
        path.write_bytes(data)
        plan = {'version': version, 'created_at': self.env.t, 'valid_until': self.env.horizon,
            'freeze_until': self.env.t, 'scope': sorted(self.env.physical), 'tasks': [],
            'holds': [], 'reason': 'explicit fixture plan; no production scheduling'}
        return plan, {'path': str(path), 'sha256': sha(data)}

    def commit(self, context, version='new'):
        plan, ref = self.decision(context, version)
        return context.commit_exact(plan, decision_evidence_ref=ref)

    def test_open_preserves_horizon_observation_jobs_and_no_advance(self):
        jobs, queue = deepcopy(self.env.jobs), deepcopy(self.env.queue)
        context = self.open_context()
        self.assertEqual(context.status()['absolute_time'], 61)
        self.assertEqual(self.env.horizon, 3661.0)
        self.assertIs(type(self.env.horizon), float)
        self.assertEqual(self.env.observation_start, 0.0)
        self.assertEqual((self.env.jobs, self.env.queue), (jobs, queue))
        self.assertEqual(self.env.advance_calls, [])
        self.assertFalse(context.evidence()['ledger_admission_verified'])
        self.assertEqual(context.evidence()['restore_receipt']['branch_identity']['run_id'], self.out.name)

    def test_before_first_commit_advance_rejected_without_executor_call(self):
        context = self.open_context()
        with self.assertRaisesRegex(m.ContextError, 'first explicit'):
            context.advance_to_boundary()
        self.assertEqual(self.env.advance_calls, [])
        self.commit(context)
        context.advance_to_boundary()
        self.assertEqual(self.env.advance_calls, [1861])

    def test_original_base_incomplete_pending_and_expired_hold_are_unchanged_copies(self):
        original = deepcopy(self.env.plan)
        context = self.open_context()
        selected = context.prior_plan_state()
        self.assertEqual(selected['base_plan'], original)
        self.assertEqual(selected['dispatched_task_ids'], ['already_done'])
        self.assertNotIn('operation_ids', selected['base_plan']['tasks'][1])
        selected['base_plan']['tasks'].clear()
        self.assertEqual(context.prior_plan_state()['base_plan'], original)

    def test_first_public_problem_copy_does_not_mutate_state(self):
        context = self.open_context()
        before = ss.digest(FakeWriter._state_view(self.env))
        public = context.problem()
        public['operations'].clear()
        self.assertEqual(ss.digest(FakeWriter._state_view(self.env)), before)
        self.assertTrue(context.problem()['operations'])

    def test_exact_commit_not_crop_or_decision_authentication(self):
        context = self.open_context()
        plan, ref = self.decision(context)
        plan['tasks'] = [{'original_exact_field': ['unmodified']}]
        original = deepcopy(plan)
        receipt = context.commit_exact(plan, decision_evidence_ref=ref)
        self.assertEqual(self.env.plan, original)
        self.assertEqual(plan, original)
        self.assertEqual(receipt['mode_at_commit'], m.PERIODIC)
        self.assertFalse(receipt['arm_attribution_certified'])
        self.assertEqual(self.env.commit_calls, 1)

    def test_event_commit_does_not_postpone_period_and_terminal_adds_no_commit(self):
        context = self.open_context()
        self.commit(context)
        self.env.early_stop = 1800
        context.advance_to_boundary()
        self.assertEqual(self.commit(context, 'event')['mode_at_commit'], m.EVENT)
        self.env.early_stop = None
        self.assertEqual(context.advance_to_boundary()['advance_target'], 1861)
        with self.assertRaisesRegex(m.ContextError, 'required period'):
            context.advance_to_boundary()
        # The invalid advance request is conservatively poisoned. A separate
        # test below completes the valid chain without an invalid operation.
        self.assertTrue(context.evidence()['poisoned'])

    def test_full_two_period_fixture_stops_at_original_H(self):
        context = self.open_context()
        self.commit(context)
        context.advance_to_boundary()
        self.commit(context, 'second')
        stop = context.advance_to_boundary()
        self.assertEqual(stop['stop'], {'time': 3661, 'reason': 'terminal'})
        self.assertEqual(context.status()['physical_horizon'], 3661)
        self.assertEqual(self.env.commit_calls, 2)
        self.assertEqual(context.evidence()['clock']['next_period_index'], 2)

    def test_commit_after_mutation_failure_is_poisoned_not_replayed(self):
        context = self.open_context()
        self.env.fail_commit_after_mutation = True
        with self.assertRaisesRegex(RuntimeError, 'unknown after'):
            self.commit(context)
        self.assertTrue(context.evidence()['poisoned'])
        with self.assertRaisesRegex(m.ContextError, 'poisoned'):
            self.commit(context, 'second')
        self.assertEqual(self.env.commit_calls, 1)

    def test_receipt_io_failure_after_success_poison_preserves_primary(self):
        context = self.open_context()
        original = ss.publish
        def publish(path, value):
            if str(path).endswith('.receipt.json'):
                raise OSError('primary receipt failure')
            if Path(path).name == 'context_failure.json':
                raise RuntimeError('secondary failure')
            return original(path, value)
        with patch.object(ss, 'publish', side_effect=publish):
            with self.assertRaisesRegex(OSError, 'primary receipt') as caught:
                self.commit(context)
        self.assertTrue(any('secondary' in note for note in caught.exception.__notes__))
        self.assertEqual(self.env.commit_calls, 1)
        self.assertEqual(context.evidence()['commits_observed'], 1)
        self.assertTrue(context.evidence()['poisoned'])

    def test_intent_io_failure_does_not_call_executor(self):
        context = self.open_context()
        original = ss.publish
        def publish(path, value):
            if str(path).endswith('.intent.json'):
                raise OSError('intent failed')
            return original(path, value)
        with patch.object(ss, 'publish', side_effect=publish):
            with self.assertRaisesRegex(OSError, 'intent failed'):
                self.commit(context)
        self.assertEqual(self.env.commit_calls, 0)
        self.assertTrue(context.evidence()['poisoned'])

    def test_unknown_advance_stops_and_keeps_original_commit(self):
        context = self.open_context()
        self.commit(context)
        self.env.fail_advance = True
        with self.assertRaisesRegex(RuntimeError, 'unknown advance'):
            context.advance_to_boundary()
        with self.assertRaisesRegex(m.ContextError, 'poisoned'):
            context.advance_to_boundary()
        self.assertEqual(len(self.env.advance_calls), 1)
        self.assertEqual(self.env.commit_calls, 1)

    def test_first_state_mutation_detected_by_original_Branch(self):
        context = self.open_context()
        self.env.jobs[7]['process_end'] += 1
        with self.assertRaisesRegex(ValueError, 'inherited state changed'):
            context.prior_plan_state()
        self.assertTrue(context.evidence()['poisoned'])
        self.assertEqual(self.env.commit_calls, 0)

    def test_physical_observation_start_mutation_poison(self):
        context = self.open_context()
        self.env.observation_start = 61
        with self.assertRaisesRegex(m.ContextError, 'original physics'):
            context.problem()
        self.assertTrue(context.evidence()['poisoned'])

    def test_binding_raw_tamper_rejected_before_restore(self):
        self.binding_path.write_bytes(self.binding_path.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.open_context()
        self.restorer.assert_not_called()

    def test_external_binding_leaf_symlink_rejected(self):
        original = self.root / 'original_binding.json'
        original.write_bytes(self.binding_path.read_bytes())
        self.binding_path.unlink()
        self.binding_path.symlink_to(original)
        with self.assertRaises(ValueError):
            self.open_context()
        self.restorer.assert_not_called()

    def test_registration_raw_tamper_rejected_before_restore(self):
        self.registration_path.write_bytes(self.registration_path.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.open_context()
        self.restorer.assert_not_called()

    def test_duplicate_json_registration_keys_rejected_even_with_matching_raw_SHA(self):
        data = b'{"arm":"B","arm":"C"}\n'
        self.registration_path.write_bytes(data)
        self.binding['registration_document_sha256'] = sha(data)
        self.save_binding()
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            self.open_context()
        self.restorer.assert_not_called()

    def test_registration_semantic_identity_cannot_be_forged_by_rehashing_binding(self):
        self.registration['registration_id'] = '9' * 64
        data = raw(self.registration)
        self.registration_path.write_bytes(data)
        self.binding['registration_document_sha256'] = sha(data)
        self.binding['registration_id'] = '9' * 64
        self.save_binding()
        with self.assertRaisesRegex(m.ContextError, 'registration identity'):
            self.open_context()
        self.restorer.assert_not_called()

    def test_registration_wrong_arm_seed_delta_or_scope_rejected(self):
        original = deepcopy(self.registration)
        for field, value in [('arm', 'C'), ('scenario', True), ('scenario', 1702),
                             ('window_seconds', 3661), ('phase', 'other'), ('formal', True),
                             ('solver_seconds', True), ('solver_seconds', 1)]:
            with self.subTest(field=field, value=value):
                self.registration = deepcopy(original)
                self.registration[field] = value
                self.save_registration(); self.save_binding()
                with self.assertRaises(m.ContextError):
                    self.open_context()
        self.restorer.assert_not_called()

    def test_short_name_absolute_run_path_and_output_must_agree(self):
        original = deepcopy(self.binding)
        for field, value in [('run_name', str(self.out)), ('run_name', 'other'),
                             ('run_path', self.out.name), ('run_path', str(self.root / 'other'))]:
            with self.subTest(field=field):
                self.binding = deepcopy(original)
                self.binding[field] = value
                self.save_binding()
                with self.assertRaises(m.ContextError):
                    self.open_context()
        self.restorer.assert_not_called()

    def test_binding_extra_key_and_false_numeric_window_rejected(self):
        original = deepcopy(self.binding)
        mutations = [('extra', True), ('window_seconds', True), ('window_seconds', 3661)]
        for field, value in mutations:
            with self.subTest(field=field):
                self.binding = deepcopy(original)
                self.binding[field] = value
                self.save_binding()
                with self.assertRaises(m.ContextError):
                    self.open_context()
        self.restorer.assert_not_called()

    def test_c_registration_file_can_be_checked_but_not_certified_as_ledger(self):
        self.binding['arm'] = 'C'
        self.registration.update(arm='C', solver_seconds=4)
        self.save_registration(); self.save_binding()
        context = self.open_context()
        self.assertFalse(context.evidence()['ledger_admission_verified'])
        self.assertEqual(context.evidence()['binding']['arm'], 'C')

    def test_A_explicit_offline_admission_is_distinct(self):
        self.binding.update(arm='A', registration_kind='offline_A_admission')
        self.registration = {'schema': m.ADMISSION_SCHEMA, 'arm': 'A', 'run_path': str(self.out),
            'run_name': self.out.name, 'seed': 1701, 'window_seconds': 3600, 'source_sha256': '4' * 64,
            'config_sha256': '5' * 64, 'solver_budget_seconds': 4, 'wall_seconds': 100,
            'max_log_bytes': 10000000, 'model_calls': 0}
        self.save_registration(); self.save_binding()
        context = self.open_context()
        self.assertIsNone(context.evidence()['binding']['registration_id'])
        self.assertFalse(context.evidence()['ledger_admission_verified'])

    def test_completed_or_interrupted_output_is_never_reused(self):
        self.out.mkdir()
        (self.out / 'claim.json').write_bytes(b'original')
        with self.assertRaisesRegex(m.ContextError, 'new independent'):
            self.open_context()
        self.assertEqual((self.out / 'claim.json').read_bytes(), b'original')
        self.restorer.assert_not_called()

    def test_late_registration_or_saved_problem_replacement_blocks_commit(self):
        context = self.open_context()
        (self.out / 'first_public_problem.json').write_bytes(b'{}\n')
        with self.assertRaises(ValueError):
            self.commit(context)
        self.assertEqual(self.env.commit_calls, 0)
        self.assertTrue(context.evidence()['poisoned'])

    def test_open_publication_failure_leaves_unusable_branch_without_advance(self):
        original = ss.publish
        captured = []
        fake = self.fake_restore
        def restore(*args, **kwargs):
            branch = fake(*args, **kwargs)
            captured.append(branch)
            return branch
        def publish(path, value):
            if Path(path).name == 'context_open.json':
                raise OSError('context receipt failure')
            return original(path, value)
        with patch.object(ss, 'restore_shared_start', side_effect=restore), patch.object(ss, 'publish', side_effect=publish):
            with self.assertRaisesRegex(OSError, 'context receipt'):
                self.open_context()
        self.assertTrue(captured[0]._poisoned)
        self.assertTrue(self.out.exists())
        self.assertEqual(self.env.advance_calls, [])
        with self.assertRaisesRegex(m.ContextError, 'new independent'):
            self.open_context()

    def test_registration_replaced_after_open_blocks_commit(self):
        context = self.open_context()
        self.registration_path.write_bytes(b'{}\n')
        with self.assertRaises(ValueError):
            self.commit(context)
        self.assertEqual(self.env.commit_calls, 0)

    def test_decision_evidence_is_not_reanchored_after_commit(self):
        context = self.open_context()
        plan, ref = self.decision(context)
        original = self.env.commit_plan
        def commit(value):
            result = original(value)
            Path(ref['path']).write_bytes(b'changed')
            return result
        with patch.object(self.env, 'commit_plan', side_effect=commit):
            with self.assertRaises(ValueError):
                context.commit_exact(plan, decision_evidence_ref=ref)
        self.assertEqual(self.env.commit_calls, 1)
        self.assertTrue(context.evidence()['poisoned'])

    def test_original_snapshot_writer_called_once_without_resume_authority(self):
        context = self.open_context()
        path = self.out / 'checkpoint.json'
        before = ss.digest(FakeWriter._state_view(self.env))
        def write(env, target):
            self.assertIs(env, self.env)
            target.write_bytes(b'{"tiny_snapshot":true}\n')
            return before
        with patch.object(m.stream_snapshot, 'write_snapshot', side_effect=write) as writer:
            receipt = context.write_checkpoint(path)
        writer.assert_called_once()
        self.assertEqual(receipt['state_sha256'], before)
        self.assertFalse(receipt['execution_resume_authorized'])
        self.assertEqual(ss.digest(FakeWriter._state_view(self.env)), before)

    def test_checkpoint_failure_poison_and_partial_file_retained(self):
        context = self.open_context()
        path = self.out / 'checkpoint.json'
        def write(env, target):
            target.write_bytes(b'partial')
            raise OSError('snapshot failed')
        with patch.object(m.stream_snapshot, 'write_snapshot', side_effect=write):
            with self.assertRaisesRegex(OSError, 'snapshot failed'):
                context.write_checkpoint(path)
        self.assertEqual(path.read_bytes(), b'partial')
        self.assertTrue(context.evidence()['poisoned'])


class ClockTests(unittest.TestCase):
    def test_initial_noninteger_boundary_and_required_commit(self):
        clock = m.AnchoredPeriodClock(window())
        self.assertEqual(clock.mode(61), m.PERIODIC)
        with self.assertRaises(m.ContextError):
            clock.advance_target(61)
        clock.committed(61)
        self.assertEqual(clock.advance_target(61), 1861)

    def test_events_leave_absolute_deadline_and_mode_equal_old_kernel_names(self):
        clock = m.SharedHybridClock(window())
        self.assertEqual(clock.request(61, remaining_cp_seconds=4, periodic_request_seconds=2), ('periodic_cp', 2))
        clock.committed(61, 'periodic_cp')
        clock.committed(1800, 'event_classical')
        clock.committed(1860, 'event_classical')
        self.assertEqual(clock.advance_target(1860), 1861)
        self.assertEqual(clock.mode(1861), 'periodic_cp')

    def test_CP_exhaustion_fails_required_period_but_event_zero_CP_allowed(self):
        clock = m.SharedHybridClock(window())
        with self.assertRaisesRegex(m.ContextError, 'exhausted'):
            clock.request(61, remaining_cp_seconds=0, periodic_request_seconds=2)
        clock.committed(61)
        self.assertEqual(clock.request(100, remaining_cp_seconds=0, periodic_request_seconds=2), (m.EVENT, 0.0))

    def test_missed_period_terminal_and_backward_time_rejected(self):
        clock = m.AnchoredPeriodClock(window())
        clock.committed(61)
        clock.committed(100)
        for now in (99, 1861.001, 3661, True, float('inf')):
            with self.subTest(now=now), self.assertRaises(m.ContextError):
                clock.mode(now)

    def test_clock_state_restore_no_anchor_reset(self):
        clock = m.AnchoredPeriodClock(window())
        clock.committed(61)
        clock.committed(1800)
        saved = clock.snapshot()
        restored = m.AnchoredPeriodClock(window(), state=saved)
        self.assertEqual(restored.snapshot(), saved)
        self.assertEqual(restored.advance_target(1800), 1861)
        saved['evaluation']['period_anchor'] = 0
        with self.assertRaises(m.ContextError):
            m.AnchoredPeriodClock(window(), state=saved)

    def test_invalid_state_types_or_skipped_period_rejected(self):
        clock = m.AnchoredPeriodClock(window())
        clock.committed(61)
        original = clock.snapshot()
        for field, value in [('next_period_index', True), ('next_period_index', 2),
                             ('last_periodic_commit_time', 0), ('last_commit_time', 1861)]:
            state = deepcopy(original); state[field] = value
            with self.subTest(field=field), self.assertRaises(m.ContextError):
                m.AnchoredPeriodClock(window(), state=state)

    def test_clock_window_rejects_bool_anchor_wrong_H_and_extra_fields(self):
        for field, value in [('period_anchor', 0), ('period_seconds', True),
                             ('physical_episode_end', 9999), ('lookahead_depth', True), ('extra', 1)]:
            w = window(); w[field] = value
            with self.subTest(field=field), self.assertRaises(m.ContextError):
                m.AnchoredPeriodClock(w)


if __name__ == '__main__':
    unittest.main()
