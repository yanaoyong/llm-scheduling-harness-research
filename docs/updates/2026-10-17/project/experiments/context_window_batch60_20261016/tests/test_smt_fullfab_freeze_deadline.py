"""Production freeze-deadline regressions using tiny state and saved events.

This file can be copied unchanged into tests/. It calls the production commit
method and both production source auditors directly. No factory is constructed,
no dispatcher/time advance/physical replay runs, and no model/solver is called.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.smt_fullfab.environment import FullFabEnvironment
from src.smt_fullfab.audit import audit_plan_sources
from src.smt_fullfab.stream_source_audit import audit_plan_sources as stream_audit_plan_sources
from tests.test_smt_fullfab_audit import trace_fixture, renumber


def initial_and_plan(*, start=12):
    initial = deepcopy(trace_fixture()[0])
    initial['manifest']['horizon'] = 100
    plan = deepcopy(trace_fixture()[3]['plan'])
    plan.update(version='base', valid_until=100, freeze_until=20)
    plan['tasks'][0].update(id='tx', not_before=start)
    return initial, plan


def revision(base, *, at=10, freeze=10, tasks=None, version='r1'):
    plan = deepcopy(base)
    plan.update(version=version, created_at=at, freeze_until=freeze)
    if tasks is not None:
        plan['tasks'] = deepcopy(tasks)
    return plan


def tiny_executor(initial):
    env = FullFabEnvironment.__new__(FullFabEnvironment)
    env.t, env.horizon, env.physical = 0, 100, {0}
    env.plan, env.plan_versions, env.executed_tasks, env.decisions = None, set(), set(), 0
    env.lots = {lot['id']: dict(lot, dedications={}) for lot in initial['manifest']['lots']}
    env.machines = {0: SimpleNamespace(family='G')}
    env.routes = {'r': SimpleNamespace(steps=[SimpleNamespace(order=1, step_name='process', family='G', batch_min=1, batch_max=1)])}
    events = [deepcopy(initial)]
    env._emit = lambda kind, **kw: events.append({'seq': len(events), 'time': env.t, 'kind': kind, **deepcopy(kw)})
    return env, events


def shortening_trace():
    initial, base = initial_and_plan()
    first = revision(base)
    second = revision(first, at=11, freeze=11, tasks=[], version='r2')
    return renumber([initial, {'kind': 'plan_committed', 'time': 0, 'plan': base},
                     {'kind': 'plan_committed', 'time': 10, 'plan': first},
                     {'kind': 'plan_committed', 'time': 11, 'plan': second}])


def record_dispatched(env, events, task):
    """Supply an observed dispatch identity, without invoking physical execution."""
    env.executed_tasks.add(('base', task['id']))
    event = deepcopy(trace_fixture()[4])
    event.update(seq=len(events), time=0, lots=list(task['lot_ids']), steps=list(task['steps']),
                 visits=list(task['visits']), plan_version='base', plan_task_id=task['id'])
    events.append(event)


class FreezeDeadlineTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(FullFabEnvironment, '__init__', side_effect=AssertionError('factory construction is forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def compare_audits(self, events, *, valid):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, report = root / 'trace.jsonl', root / 'stream.json'
            source.write_text(''.join(json.dumps(event) + '\n' for event in events))
            reference = audit_plan_sources(source)
            self.assertIs(reference['valid'], valid, reference['errors'])
            descriptor = stream_audit_plan_sources(source, report_path=report)
            streamed = json.loads(report.read_text())
            evidence = streamed.pop('_source_evidence')
            self.assertEqual(evidence['source_receipt'], descriptor['source_receipt'])
            self.assertEqual(evidence['source_receipt']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(evidence['source_receipt']['event_count'], len(events))
            self.assertEqual(descriptor['report_sha256'], hashlib.sha256(report.read_bytes()).hexdigest())
            streamed['audit_version'] = reference['audit_version']
            self.assertEqual(streamed, reference)
            return reference

    def test_pending_frozen_task_blocks_shortening_without_state_or_input_change(self):
        initial, base = initial_and_plan()
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        env.t = 10
        submitted = revision(base)
        original_submission = deepcopy(submitted)
        before = deepcopy((env.plan, env.plan_versions, env.executed_tasks, env.decisions, events))
        with self.assertRaisesRegex(ValueError, 'shorten existing frozen commitment'):
            env.commit_plan(submitted)
        self.assertEqual((env.plan, env.plan_versions, env.executed_tasks, env.decisions, events), before)
        self.assertEqual(submitted, original_submission)

    def test_both_source_audits_reject_shortening_then_dropping_frozen_task(self):
        result = self.compare_audits(shortening_trace(), valid=False)
        self.assertEqual(result['errors'], ['2: shortened prior freeze interval with pending frozen tasks'])

    def test_equal_and_extended_deadlines_preserve_exact_submitted_tasks(self):
        for deadline in (20, 25):
            with self.subTest(deadline=deadline):
                initial, base = initial_and_plan()
                env, events = tiny_executor(initial)
                env.commit_plan(base)
                env.t = 10
                submitted = revision(base, freeze=deadline)
                env.commit_plan(submitted)
                self.assertEqual(env.plan, submitted)
                self.assertEqual(env.plan['tasks'], base['tasks'])
                self.compare_audits(events, valid=True)

    def test_expired_deadline_does_not_keep_task_frozen(self):
        initial, base = initial_and_plan()
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        env.t = 20
        submitted = revision(base, at=20, freeze=20, tasks=[])
        env.commit_plan(submitted)
        self.assertEqual(env.plan['tasks'], [])
        self.compare_audits(events, valid=True)

    def test_no_frozen_tasks_allows_shorter_deadline(self):
        initial, base = initial_and_plan(start=25)
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        env.t = 10
        env.commit_plan(revision(base))
        self.assertEqual(env.plan['freeze_until'], 10)
        self.compare_audits(events, valid=True)

    def test_all_frozen_tasks_dispatched_allows_shorter_deadline(self):
        initial, base = initial_and_plan(start=0)
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        record_dispatched(env, events, base['tasks'][0])
        env.t = 10
        env.commit_plan(revision(base, tasks=[]))
        self.assertEqual(env.plan['freeze_until'], 10)
        self.assertEqual(env.plan['tasks'], [])
        self.compare_audits(events, valid=True)

    def test_partly_dispatched_plan_still_has_a_frozen_commitment(self):
        initial, base = initial_and_plan(start=0)
        initial['manifest']['lots'].append(dict(initial['manifest']['lots'][0], id='y', name='y'))
        base['tasks'].append(dict(deepcopy(base['tasks'][0]), id='ty', lot_ids=['y'], not_before=12))
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        record_dispatched(env, events, base['tasks'][0])
        env.t = 10
        submitted = revision(base, tasks=base['tasks'][1:])
        before = deepcopy((env.plan, env.plan_versions, env.executed_tasks, env.decisions, events, submitted))
        with self.assertRaisesRegex(ValueError, 'shorten existing frozen commitment'):
            env.commit_plan(submitted)
        self.assertEqual((env.plan, env.plan_versions, env.executed_tasks, env.decisions, events, submitted), before)
        events.append({'seq': len(events), 'time': 10, 'kind': 'plan_committed', 'plan': submitted})
        self.compare_audits(events, valid=False)

    def test_existing_relative_order_contract_does_not_gain_delta_prefix_rule(self):
        initial, base = initial_and_plan()
        initial['manifest']['lots'].append(dict(initial['manifest']['lots'][0], id='y', name='y'))
        env, events = tiny_executor(initial)
        env.commit_plan(base)
        env.t = 10
        added = dict(deepcopy(base['tasks'][0]), id='added', lot_ids=['y'], not_before=50)
        submitted = revision(base, freeze=20, tasks=[added] + base['tasks'])
        env.commit_plan(submitted)
        self.assertEqual([task['id'] for task in env.plan['tasks']], ['added', 'tx'])
        self.compare_audits(events, valid=True)

    def test_pre_upgrade_snapshot_version_is_rejected_before_factory_construction(self):
        # The freeze-deadline change is environment v0.3. A saved v0.2 snapshot
        # cannot be made current by reusing a matching state hash.
        state = {}
        saved = {'schema': 'smt-fullfab-snapshot-1', 'version': 'smt-fullfab-env-0.2',
                 'state': state, 'state_sha256': hashlib.sha256(b'{}').hexdigest(),
                 'implementation_sha256': {}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'old-snapshot.json'
            path.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, 'snapshot schema/version/hash mismatch'):
                FullFabEnvironment.from_snapshot(path)


if __name__ == '__main__':
    unittest.main()
