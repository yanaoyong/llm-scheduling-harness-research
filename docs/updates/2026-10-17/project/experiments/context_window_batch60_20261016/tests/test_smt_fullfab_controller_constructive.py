"""Controller contracts only: fake physics, model, ledger and tool outcomes.

No factory simulation, model transport or CP model is executed here. The shared
constructor's real nominal constraints/equivalence have their own tiny fixtures.
"""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.smt_fullfab import controller


WEIGHTS = {'completion': 100, 'flow': 1, 'tardiness': 10, 'setup': 1}


def action(kind='solve', **changes):
    value = dict(action=kind, index=None, method='constructive' if kind == 'solve' else None,
                 seconds=5 if kind == 'solve' else None, seed=17 if kind == 'solve' else None,
                 slots=8 if kind == 'solve' else None, weights=deepcopy(WEIGHTS), reason='explicit fixture choice')
    value.update(changes)
    return value


def candidate(name='constructor', **changes):
    value = {'model': 'fullfab-constructive-tool-v1', 'solver_status': 'FEASIBLE_HEURISTIC',
             'plan': {'version': name, 'scope': [1, 913], 'tasks': [{'id': name}], 'holds': []},
             'nominal_audit': {'valid': True}, 'unplanned_operations': {}, 'wall_seconds': 1.5,
             'classical_construction_wall_seconds': 1.2, 'best_bound': None,
             'global_optimality_claim': False, 'cp_sat': {'calls': 0, 'requested_seconds': 0}}
    value.update(changes)
    return value


class FakeEnvironment:
    def __init__(self, *, seed, window_seconds, trace_path):
        self.t = 0
        self.horizon = window_seconds
        self.finished = False
        self.data_dir = 'never-read'
        self.commits = []
        self.advance_count = 0
        self.finish_after = 1
        Path(trace_path).write_text('')

    def problem(self, **kwargs):
        return {'time': self.t, 'horizon_end': self.t + kwargs['plan_seconds'],
                'machines': [{'machine': 1}, {'machine': 913}],
                'operations': [{'operation_id': 'a'}, {'operation_id': 'a-next'}]}

    def commit_plan(self, plan):
        self.commits.append(deepcopy(plan))

    def advance_plan(self, until):
        self.advance_count += 1
        self.finished = self.advance_count >= self.finish_after
        self.t = self.horizon if self.finished else until

    def snapshot(self, path):
        controller.write_new(path, {'fixture_only': True, 'time': self.t, 'commits': len(self.commits)})


class FakeLedger:
    def __init__(self):
        self.cp_remaining = 60
        self.model_seconds = 0
        self.constructor_seconds = 0
        self.reserves = []
        self.finishes = []
        self.cp_reserves = []
        self.finish_hook = None
        self.waiver = {'amendment_id': 'fixture', 'allowed_stage2_window_seconds': [3600]}

    def research_limit_waiver(self):
        return self.waiver

    def scoped_limit_waiver(self, arm):
        return None

    def register_stage_run(self, **kwargs):
        self.registration = kwargs
        return {'registration_id': 'fixture-registration', **kwargs}

    def solver_remaining_seconds(self, arm, run_id=None):
        return self.cp_remaining

    def constructor_remaining_seconds(self, arm, run_id):
        return max(0, self.registration['wall_seconds'] - self.model_seconds - self.constructor_seconds)

    def summary(self, **kwargs):
        return {'model_active_seconds': self.model_seconds,
                'constructor_active_seconds': self.constructor_seconds,
                'constructor_requested_seconds': sum(row['requested_seconds'] for row in self.reserves)}

    def reserve_constructor(self, **kwargs):
        self.reserves.append(deepcopy(kwargs))
        return 'constructor-' + str(len(self.reserves))

    def finish_constructor(self, cid, status, details):
        if self.finish_hook:
            self.finish_hook(cid, status, details)
        self.finishes.append((cid, status, deepcopy(details)))
        self.constructor_seconds += details['duration_seconds']

    def reserve_solver(self, **kwargs):
        self.cp_reserves.append(kwargs)
        self.cp_remaining -= kwargs['requested_seconds']
        return 'cp-' + str(len(self.cp_reserves))

    def finish_solver(self, *args):
        pass


class ControllerConstructiveTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.approval = self.root / 'approval.json'
        self.approval.write_text(json.dumps({'budget_id': 'fixture', 'model': 'fixture-no-model',
                                           'reasoning_effort': 'medium', 'per_call_timeout_seconds': 180}))
        self.ledger = FakeLedger()
        self.clock = [0.0]
        self.actions = []
        self.outcomes = []
        self.prompts = []
        self.configs = []
        self.envs = []
        self.construction_duration = 2.5
        self.audit_duration = 0
        self.finish_after = 1
        self.construct_commits = []
        def make_env(**kwargs):
            env = FakeEnvironment(**kwargs)
            env.finish_after = self.finish_after
            self.envs.append(env)
            return env
        def compact(problem, **kwargs):
            return {'problem_metadata': {'fixture': True}, 'pages': [[
                {'family': 'F', 'machines': [[1], [913]], 'operations': [['a'], ['a-next']]}]]}
        def model(prompt, schema, output, config):
            self.prompts.append(prompt)
            self.configs.append(config)
            self.clock[0] += .25
            self.ledger.model_seconds += .25
            if not self.actions:
                raise AssertionError('No additional fixture model response authorized')
            response = self.actions.pop(0)
            if isinstance(response, Exception):
                raise response
            return {'status': 'success', 'call_id': 'model-' + str(len(self.prompts)), 'output': deepcopy(response)}
        def construct(problem, **params):
            self.construct_commits.append(len(self.envs[-1].commits))
            self.clock[0] += self.construction_duration
            outcome = self.outcomes.pop(0) if self.outcomes else candidate()
            if isinstance(outcome, Exception):
                raise outcome
            return deepcopy(outcome)
        def audit(*args, **kwargs):
            self.clock[0] += self.audit_duration
            return {'valid': True, 'metrics': {'fixture_only': True}}
        patches = [patch.object(controller, 'ROOT', self.root), patch.object(controller, 'APPROVAL', self.approval),
                   patch.object(controller, 'BudgetLedger', return_value=self.ledger),
                   patch.object(controller, 'FullFabEnvironment', side_effect=make_env),
                   patch.object(controller, 'source_snapshot', return_value={'fixture_only': True}),
                   patch.object(controller, 'compact_pages', side_effect=compact),
                   patch.object(controller, 'crop_plan', side_effect=lambda plan, env: deepcopy(plan)),
                   patch.object(controller, 'audit_trace', side_effect=audit),
                   patch.object(controller, 'call_model', side_effect=model),
                   patch.object(controller.time, 'monotonic', side_effect=lambda: self.clock[0])]
        for item in patches:
            self.stack.enter_context(item)
        self.construct = self.stack.enter_context(patch('src.smt_fullfab.constructive_tool.solve_constructive_plan', side_effect=construct))
        self.cp = self.stack.enter_context(patch('src.smt_fullfab.optimizer.solve_plan', side_effect=AssertionError('No CP authorized')))
        self.decomposed = self.stack.enter_context(patch('src.smt_fullfab.decomposition.solve_decomposed_plan', side_effect=AssertionError('No CP authorized')))
        for target in ('CpModel', 'CpSolver'):
            self.stack.enter_context(patch('src.smt_fullfab.optimizer.cp_model.' + target, side_effect=AssertionError('No real CP')))

    @property
    def out(self):
        return self.root / 'runs/smt_fullfab_stage2/C_fixture'

    def run_fixture(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return controller.run('C', 'C_fixture', enable_constructive=kwargs.pop('enable_constructive', True), **kwargs)

    def read(self, name):
        return json.loads((self.out / name).read_text())

    def rows(self, name):
        return [json.loads(line) for line in (self.out / name).read_text().splitlines()]

    def test_zero_cp_still_allows_read_construct_and_explicit_apply(self):
        self.ledger.cp_remaining = 0
        self.actions = [action('read_page', index=0), action(), action('apply', index=0)]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['solver_calls'], 0)
        self.assertEqual(result['solver_requested_seconds'], 0)
        self.assertEqual(result['constructor_calls'], 1)
        self.assertEqual(result['constructor_active_seconds'], 2.5)
        self.assertEqual(result['constructor_requested_seconds'], 5)
        self.assertEqual(self.construct_commits, [0])
        self.assertEqual(len(self.envs[0].commits), 1)
        self.assertEqual(self.envs[0].commits[0], candidate()['plan'])
        self.assertIsNone(result['config']['max_calls'])
        self.assertIn('constructive', controller.C_CONSTRUCTIVE_SCHEMA['properties']['method']['enum'])
        self.cp.assert_not_called()
        self.decomposed.assert_not_called()

    def test_request_result_ledger_and_apply_identity_are_durable(self):
        self.actions = [action(), action('apply', index=0)]
        def completed_before_finish(cid, status, details):
            stored = self.read('constructor_001.json')
            self.assertEqual(stored['constructor_call_id'], cid)
            self.assertEqual(stored['invocation_duration_seconds'], details['duration_seconds'])
            self.assertEqual(controller.digest(stored), details['constructor_result_sha256'])
        self.ledger.finish_hook = completed_before_finish
        result = self.run_fixture()
        request = self.read('constructor_request_000.json')
        stored = self.read('constructor_001.json')
        self.assertEqual(request['model_call_id'], result['model_call_ids'][0])
        self.assertEqual(request['constructor_index'], 0)
        self.assertEqual(request['max_candidate_evaluations'], 250000)
        self.assertEqual(request['actual_constructor_function'], 'solve_constructive_plan')
        self.assertEqual(request['parameters'], self.construct.call_args.kwargs)
        evidence = self.rows('constructor_evidence.jsonl')[0]
        self.assertEqual(evidence['constructor_result_sha256'], controller.digest(stored))
        self.assertEqual(self.rows('plan_commits.jsonl')[0]['model_call_id'], result['model_call_ids'][1])
        self.assertEqual(self.read('raw_plan_000.json'), stored['plan'])
        self.assertEqual(len(self.rows('controller_history_events.jsonl')), 2)
        self.assertIn('"constructor_active_seconds": 2.5', self.prompts[1])
        self.assertEqual(self.read('config.json')['constructor_seconds_cap'], 5)
        self.assertEqual(result['log_bytes_including_result'], sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()))

    def test_no_apply_never_commits_a_successful_candidate(self):
        self.actions = [action()]
        result = self.run_fixture(max_calls=1)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['plans_committed'], 0)
        self.assertEqual(self.envs[0].commits, [])
        self.assertTrue((self.out / 'constructor_001.json').exists())
        self.assertTrue((self.out / 'checkpoint.json').exists())

    def test_exception_feedback_allows_only_a_new_explicit_tool_choice(self):
        self.actions = [action(), action('read_page', index=0), action(seed=18), action('apply', index=1)]
        self.outcomes = [RuntimeError('fixture constructor failed'), candidate('second')]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.construct.call_count, 2)
        self.assertEqual(self.construct_commits, [0, 0])
        self.assertEqual([entry[1] for entry in self.ledger.finishes], ['failed', 'success'])
        self.assertEqual(self.read('constructor_001.json')['error'], 'RuntimeError: fixture constructor failed')
        self.assertIn('CONSTRUCTOR_EXCEPTION', self.prompts[1])
        self.assertIn('"valid_candidate":false', self.prompts[1])
        self.assertEqual(self.envs[0].commits[0]['version'], 'second')
        self.assertEqual(result['constructor_active_seconds'], 5)

    def test_invalid_nominal_and_no_plan_cannot_apply(self):
        for bad in (candidate(nominal_audit=None), candidate(nominal_audit={'valid': False}),
                    candidate(solver_status='NO_PLAN', plan=None)):
            with self.subTest(bad=bad):
                valid, feedback = controller.candidate_feedback(bad, 0, strict_nominal=True)
                self.assertFalse(valid)
                self.assertFalse(feedback['valid_candidate'])
        self.actions = [action(), action('apply', index=0)]
        self.outcomes = [candidate(nominal_audit=None)]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('invalid explicit candidate', result['failure'])
        self.assertEqual(result['plans_committed'], 0)

    def test_cp_without_nominal_field_keeps_original_acceptance_and_mixed_indices(self):
        cp_result = candidate('global', solver_status='OPTIMAL')
        del cp_result['nominal_audit']
        self.cp.side_effect = None
        self.cp.return_value = cp_result
        self.actions = [action(method='global', seconds=1), action(), action('apply', index=0)]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['solver_requested_seconds'], 1)
        self.assertEqual(result['constructor_calls'], 1)
        self.assertEqual(self.envs[0].commits[0]['version'], 'global')
        history = self.read('controller_history_000.json')
        self.assertEqual([h['result']['candidate_index'] for h in history[:2]], [0, 1])
        self.assertTrue(history[0]['result']['valid_candidate'])

    def test_cp_exhaustion_does_not_substitute_a_constructor(self):
        self.ledger.cp_remaining = 0
        self.actions = [action(method='global', seconds=1)]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('solve budget', result['failure'])
        self.construct.assert_not_called()
        self.cp.assert_not_called()
        self.assertEqual(self.ledger.cp_reserves, [])

    def test_per_plan_candidates_reset_and_no_stale_apply(self):
        self.finish_after = 2
        self.actions = [action(), action('apply', index=0), action('apply', index=0)]
        result = self.run_fixture()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['plans_committed'], 1)
        self.assertEqual(result['simulation_seconds'], 1800)
        self.assertEqual(self.construct.call_count, 1)
        self.assertIn('OWN_HISTORY\n[]\nLIMITS', self.prompts[2])

    def test_completed_or_interrupted_identity_never_repeats_requests(self):
        self.actions = [action(), action('apply', index=0)]
        first = self.run_fixture()
        self.assertEqual(self.run_fixture(), first)
        self.assertEqual(len(self.prompts), 2)
        (self.out / 'result.json').unlink()
        with self.assertRaisesRegex(FileExistsError, 'never re-call'):
            self.run_fixture()
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(self.construct.call_count, 1)

    def test_result_to_finish_crash_preserves_duration_and_stops(self):
        self.actions = [action(), action('apply', index=0)]
        self.ledger.finish_hook = lambda *args: (_ for _ in ()).throw(RuntimeError('ledger interrupted'))
        result = self.run_fixture()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.read('constructor_001.json')['invocation_duration_seconds'], 2.5)
        self.assertEqual(self.ledger.finishes, [])
        self.assertEqual(self.envs[0].commits, [])

    def test_constructor_activity_clamps_following_model_timeout(self):
        self.actions = [action(seconds=1), action('apply', index=0)]
        result = self.run_fixture(wall_seconds=10)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.configs[0].timeout_seconds, 10)
        self.assertEqual(self.configs[1].timeout_seconds, 7.25)
        limits = json.loads(self.prompts[1].split('\nLIMITS\n')[1])
        self.assertEqual(limits['model_active_seconds_remaining'], 7.25)

    def test_soft_overrun_cannot_advance_after_exhausting_hard_wall(self):
        self.construction_duration = 11
        self.actions = [action(seconds=1), action('apply', index=0)]
        result = self.run_fixture(wall_seconds=10)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['constructor_active_seconds'], 11)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.envs[0].commits, [])

    def test_audit_wall_overrun_is_not_success(self):
        self.actions = [action(seconds=1), action('apply', index=0)]
        self.audit_duration = 20
        result = self.run_fixture(wall_seconds=10)
        self.assertTrue(result['full_window_completed'])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('wall limit', result['failure'])

    def test_terminal_checkpoint_log_overrun_is_preserved_but_not_success(self):
        self.actions = [action(seconds=1), action('apply', index=0)]
        with patch.object(FakeEnvironment, 'snapshot', side_effect=lambda path: Path(path).write_text('x' * 50000)):
            result = self.run_fixture(max_log_bytes=40000)
        self.assertTrue(result['full_window_completed'])
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['resource_overrun'])
        self.assertEqual(result['log_bytes_including_result'], sum(p.stat().st_size for p in self.out.rglob('*') if p.is_file()))

    def test_constructor_validation_rejects_caps_and_parameters(self):
        invalid = [{'seconds': value} for value in (True, 0, -1, 5.01, float('nan'), float('inf'), '1')]
        invalid += [{'seed': value} for value in (True, -1, 2**31, 1.2)]
        invalid += [{'slots': value} for value in (True, 0, 9, 1.5)]
        invalid += [{'weights': value} for value in (None, [], {}, {'setup': 1}, dict.fromkeys(WEIGHTS, 0))]
        invalid += [{'index': 0}, {'method': 'global'}]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                controller.validate_constructor_request(action(**change), 100)
        with self.assertRaises(ValueError):
            controller.validate_constructor_request(action(seconds=1), .9)
        controller.validate_constructor_request(action(seconds=.001, slots=1, seed=0), 1)
        self.construct.assert_not_called()

    def test_feature_is_explicit_C_only_and_legacy_schema_stays_unchanged(self):
        self.assertNotIn('constructive', controller.C_SCHEMA['properties']['method']['enum'])
        with self.assertRaisesRegex(ValueError, 'research C'):
            controller.run('B', 'not-created', enable_constructive=True)
        self.ledger.waiver = None
        with self.assertRaisesRegex(ValueError, 'research C'):
            self.run_fixture()
        self.assertEqual(self.envs, [])

    def test_legacy_C_does_not_gain_constructor_implicitly(self):
        self.actions = [action()]
        result = self.run_fixture(enable_constructive=False)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('enable_constructive', result['config'])
        self.assertNotIn('constructor_calls', result)
        self.assertIn('not enabled', result['failure'])
        self.construct.assert_not_called()

    def test_real_temporary_ledger_accepts_controller_source_binding(self):
        # Only the append-only local account is real. Model/physics/tools stay
        # mocked, and neither the project ledger nor any real run is touched.
        from src.smt_fullfab import budget
        from src.smt_fullfab.constructor_audit import audit_constructor_ledger
        approval = json.loads((budget.ROOT / 'configs/smt_fullfab/stage2_probe.approved.json').read_text())
        waiver = json.loads((budget.ROOT / 'configs/smt_fullfab/research_limit_waiver.approved.json').read_text())
        account = budget.BudgetLedger(self.root / 'smt_fullfab_ledger.jsonl')
        account.approve(approval)
        account.approve_research_limit_waiver(waiver)
        self.approval.write_text(json.dumps(approval))
        choices = [action(), action('apply', index=0)]
        def model(prompt, schema, output, config):
            cid = account.reserve(phase=config.phase, run_id=str(output), grant_id=config.grant_id,
                metadata={'model': config.model, 'reasoning_effort': config.reasoning_effort,
                          'timeout_seconds': config.timeout_seconds, 'authorization_context': config.authorization_context})
            self.clock[0] += .25
            account.finish(cid, 'success', {'duration_seconds': .25, 'usage': {'input_tokens': 1, 'output_tokens': 1}})
            return {'status': 'success', 'call_id': cid, 'output': choices.pop(0)}
        with patch.object(budget, 'ROOT', self.root.resolve()), \
             patch.object(controller, 'BudgetLedger', return_value=account), \
             patch.object(controller, 'call_model', side_effect=model):
            result = self.run_fixture()
            summary = account.summary(run_id=str(self.out))
            self.assertEqual(account.solver_remaining_seconds('C', run_id=str(self.out)), 60)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(summary['attempts'], 2, result)
        self.assertEqual(summary['constructor_calls'], 1)
        self.assertEqual(summary['constructor_active_seconds'], 2.5)
        self.assertEqual(summary['active_execution_seconds'], 3)
        self.assertEqual(summary['pending_constructor_calls'], [])
        rows = [json.loads(line) for line in account.path.read_text().splitlines()]
        self.assertEqual(audit_constructor_ledger(rows)['errors'], [])


if __name__ == '__main__':
    unittest.main()
