"""Small pure JSON sessions; no model, environment, optimizer or factory run."""
from copy import deepcopy
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from src.smt_fullfab import delta_session as module
from src.smt_fullfab.delta_session import DeltaSession, SessionError
from src.smt_fullfab.interface import compact_pages
from src.smt_fullfab.plan_delta import SCHEMA, STATE_SCHEMA, ORDER_POLICY, anchor_hashes, compile_plan_delta, json_sha256

SOURCE = 'a' * 64


def fixture():
    def task(tid, mid, start):
        return {'id': tid, 'machine': mid, 'lot_ids': ['lot-' + tid], 'steps': [1], 'visits': [1],
                'operation_ids': ['op-' + tid], 'not_before': start,
                'unknown_future_field': {'note': '原样', 'explicit_null': None}}
    base = {'version': 'base', 'created_at': 0, 'valid_until': 100, 'freeze_until': 0,
            'reason': 'exact prior model choice', 'scope': [2, 1, 913],
            'tasks': [task('done', 1, 0), task('z', 1, 12), task('a', 2, 13)],
            'holds': [{'machine': 1, 'until': 90, 'after_task_id': 'z', 'reason': 'tail'},
                      {'machine': 913, 'until': 90, 'reason': 'explicit wait', 'extra': None},
                      {'machine': 2, 'until': 90, 'after_task_id': 'a', 'reason': 'tail'}]}
    problem = {'schema': 'smt-fullfab-problem-2', 'time': 10, 'horizon_end': 100, 'scope': [2, 1, 913],
               'machines': [{'machine': 2, 'family': 'F', 'custom': ['not ranked']},
                            {'machine': 1, 'family': 'F'}, {'machine': 913, 'family': 'idle'}],
               'operations': [{'operation_id': 'op-' + tid, 'lot_id': 'lot-' + tid, 'step': 1, 'visit': 1,
                               'eligible_machines': [2, 1], 'family': 'F', 'batch_key': ['part', 1, 'recipe'],
                               'batch_min': 1, 'batch_max': 1, 'priority': priority,
                               'unknown_operation_field': {'nullable': None, '中文': ['retain', tid]}}
                              for tid, priority in [('z', 1), ('done', 900), ('a', 10), ('new', 100)]],
               'public_metadata': {'no_loss': None}}
    state = {'schema': STATE_SCHEMA, 'time': 10, 'observation_end': 100,
             'base_plan_version': 'base', 'dispatched_task_ids': ['done']}
    delta = {'schema': SCHEMA, 'anchors': anchor_hashes(base, problem, state, source_sha256=SOURCE),
             'order_policy': ORDER_POLICY,
             'plan_header': {'version': 'delta-1', 'created_at': 10, 'valid_until': 100,
                             'freeze_until': 10, 'reason': 'explicit keep', 'scope': [2, 1, 913]},
             'tasks': {'keep': {'mode': 'all_pending_except', 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []},
             'holds': {'keep': {'mode': 'all_except', 'ids': []}, 'cancel_ids': [], 'replace': [], 'add': []},
             'machine_orders': []}
    paging = compact_pages(problem)
    # Two complete pages with the exact original compact family groups.
    paging['pages'] = [[group] for page in paging['pages'] for group in page]
    paging['page_count'] = len(paging['pages'])
    return base, problem, state, paging, delta


class DeltaSessionTests(unittest.TestCase):
    def setUp(self):
        self.base, self.problem, self.state, self.paging, self.delta = fixture()
        self.session = self.new_session()
        self.index = 0

    def new_session(self, source=SOURCE):
        return DeltaSession(self.base, self.problem, self.state, source_sha256=source, paging=self.paging)

    def action(self, kind, **fields):
        catalog = self.session.describe()
        return {'action': kind, 'session_id': catalog['session_id'], 'anchors': catalog['anchors'], **fields}

    def send(self, action):
        index = self.index;self.index += 1
        return self.session.handle(action, call_id='call-' + str(index), model_index=index)

    def checked(self, delta=None):
        response = self.send(self.action('check_delta', delta=self.delta if delta is None else delta))
        self.assertEqual(response['status'], 'candidate_checked', response)
        self.assertIsNone(self.session.export_evidence()['selection'])
        return response['candidate']

    def candidate_action(self, kind, candidate):
        return self.action(kind, candidate_id=candidate['candidate_id'], candidate_sha256=candidate['candidate_sha256'])

    def assert_rejected(self, response, code):
        self.assertEqual(response['status'], 'rejected', response)
        self.assertEqual(response['error']['code'], code, response)
        self.assertFalse(response['physical_commit_performed'])

    def test_bootstrap_has_complete_source_order_catalog_and_no_recommendation(self):
        catalog = self.session.describe()
        self.assertEqual(catalog['base_task_ids'], ['done', 'z', 'a'])
        self.assertEqual(catalog['pending_base_task_ids'], ['z', 'a'])
        self.assertEqual(catalog['base_hold_refs'], ['h:0', 'h:1', 'h:2'])
        self.assertEqual(catalog['operation_ids'], ['op-z', 'op-done', 'op-a', 'op-new'])
        self.assertEqual(catalog['page_indices'], [0, 1])
        self.assertEqual(catalog['paging_metadata'], {k: v for k, v in self.paging.items() if k != 'pages'})
        self.assertFalse(catalog['model_attribution_certified'])
        self.assertFalse(catalog['physical_validation_performed'])
        self.assertEqual(self.session.export_evidence()['history'], [])
        self.assertEqual(self.session.export_evidence()['candidates'], [])

    def test_any_page_can_be_read_repeatedly_out_of_order_exactly(self):
        with patch.object(module, 'compile_plan_delta', side_effect=AssertionError('query called compiler')):
            for page_index in (1, 0, 1):
                result = self.send(self.action('read_page', page_index=page_index))
                self.assertEqual(result['status'], 'query_result')
                self.assertEqual(result['page'], self.paging['pages'][page_index])
                self.assertEqual(json_sha256(result['page']), json_sha256(self.paging['pages'][page_index]))
        self.assertEqual(len(self.session.export_evidence()['history']), 3)

    def test_reference_queries_return_complete_raw_values_in_requested_order(self):
        with patch.object(module, 'compile_plan_delta', side_effect=AssertionError('query called compiler')):
            tasks = self.send(self.action('read_base_tasks', task_ids=['a', 'done', 'z']))
            self.assertEqual(tasks['tasks'], [self.base['tasks'][2], self.base['tasks'][0], self.base['tasks'][1]])
            self.assertEqual(tasks['references'], [{'ref': 'a', 'source_index': 2, 'dispatched': False},
                                                   {'ref': 'done', 'source_index': 0, 'dispatched': True},
                                                   {'ref': 'z', 'source_index': 1, 'dispatched': False}])
            holds = self.send(self.action('read_base_holds', hold_refs=['h:2', 'h:0', 'h:1']))
            self.assertEqual(holds['holds'], [self.base['holds'][2], self.base['holds'][0], self.base['holds'][1]])
            operations = self.send(self.action('read_operations', operation_ids=['op-new', 'op-z']))
            self.assertEqual(operations['operations'], [self.problem['operations'][3], self.problem['operations'][0]])
            self.assertEqual(operations['operations'][1]['eligible_machines'], [2, 1])
        self.assertEqual(self.session.export_evidence()['candidates'], [])

    def test_stale_pending_and_hold_records_remain_visible_without_repair(self):
        self.base['tasks'][1]['not_before'] = 3
        self.base['holds'][0].update(until=5, after_task_id='done')
        self.session = self.new_session()
        tasks = self.send(self.action('read_base_tasks', task_ids=['z']))
        holds = self.send(self.action('read_base_holds', hold_refs=['h:0']))
        self.assertEqual(tasks['tasks'], [self.base['tasks'][1]])
        self.assertEqual(holds['holds'], [self.base['holds'][0]])
        self.assertEqual(self.session.describe()['pending_base_task_ids'], ['z', 'a'])

    def test_unknown_duplicate_or_noninteger_queries_are_rejected_without_partial_rows(self):
        for kind, fields, code in [
            ('read_page', {'page_index': True}, 'page_index'),
            ('read_page', {'page_index': 0.0}, 'page_index'),
            ('read_page', {'page_index': -1}, 'page_index'),
            ('read_page', {'page_index': 2}, 'page_index'),
            ('read_base_tasks', {'task_ids': ['z', 'missing']}, 'unknown_reference'),
            ('read_base_tasks', {'task_ids': ['z', 'z']}, 'duplicate_ids'),
            ('read_base_holds', {'hold_refs': ['h:01']}, 'unknown_reference'),
            ('read_operations', {'operation_ids': ['op-z', 1]}, 'ids')]:
            with self.subTest(kind=kind, fields=fields):
                response = self.send(self.action(kind, **fields))
                self.assert_rejected(response, code)
                self.assertFalse(any(k in response for k in ('tasks', 'holds', 'operations', 'page')))
        self.assertEqual(len(self.session.export_evidence()['history']), 8)

    def test_check_uses_only_pure_compiler_and_stores_complete_bound_candidate(self):
        original = deepcopy(self.delta)
        with patch.object(module, 'compile_plan_delta', wraps=compile_plan_delta) as compiler:
            summary = self.checked()
        compiler.assert_called_once()
        full = self.send(self.candidate_action('read_candidate', summary))
        candidate = full['candidate']
        self.assertEqual(candidate['compiled'], compile_plan_delta(self.base, self.problem, self.state, self.delta, source_sha256=SOURCE))
        self.assertEqual(candidate['delta'], original)
        self.assertEqual(summary['candidate_sha256'], json_sha256(candidate))
        self.assertEqual(candidate['checked_action']['call_id'], 'call-0')
        self.assertEqual(candidate['checked_action']['model_index'], 0)
        self.assertEqual(candidate['checked_action']['action_index'], 0)
        self.assertFalse(summary['selected_for_external_commit'])
        self.assertEqual(self.delta, original)

    def test_candidate_list_is_complete_creation_order_and_apply_can_choose_earlier(self):
        first = self.checked()
        other = deepcopy(self.delta);other['plan_header']['version'] = 'delta-2'
        second = self.checked(other)
        listed = self.send(self.action('read_candidates'))
        self.assertEqual([c['candidate_id'] for c in listed['candidates']], [first['candidate_id'], second['candidate_id']])
        chosen = self.send(self.candidate_action('apply', first))
        self.assertEqual(chosen['status'], 'selection_for_external_commit')
        self.assertEqual(chosen['candidate']['compiled']['plan']['version'], 'delta-1')
        self.assertFalse(chosen['physical_commit_performed'])
        self.assertFalse(chosen['model_attribution_certified'])
        self.assertTrue(chosen['external_common_validation_required'])

    def test_selection_is_terminal_and_cannot_reapply_check_or_query(self):
        candidate = self.checked()
        chosen = self.send(self.candidate_action('apply', candidate))
        for action in (self.candidate_action('apply', candidate), self.action('check_delta', delta=self.delta),
                       self.action('read_candidates'), self.action('read_page', page_index=0)):
            self.assert_rejected(self.send(action), 'session_selected')
        evidence = self.session.export_evidence()
        self.assertEqual(evidence['selection'], chosen)
        self.assertEqual(len(evidence['candidates']), 1)
        self.assertEqual(len(evidence['history']), 6)

    def test_apply_requires_existing_candidate_exact_hash_and_no_inline_changes(self):
        self.assert_rejected(self.send(self.action('apply', candidate_id='none', candidate_sha256='b' * 64)), 'unknown_candidate')
        candidate = self.checked()
        wrong = self.candidate_action('apply', candidate);wrong['candidate_sha256'] = 'b' * 64
        self.assert_rejected(self.send(wrong), 'candidate_hash')
        extra = self.candidate_action('apply', candidate);extra['delta'] = self.delta
        self.assert_rejected(self.send(extra), 'action_schema')
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_each_anchor_and_session_identity_is_checked_on_apply(self):
        candidate = self.checked()
        for key in candidate['anchors']:
            action = self.candidate_action('apply', candidate);action['anchors'][key] = 'b' * 64
            self.assert_rejected(self.send(action), 'stale_anchor')
        action = self.candidate_action('apply', candidate);action['session_id'] = 'another-session'
        self.assert_rejected(self.send(action), 'stale_session')
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_new_observation_requires_new_session_and_cannot_import_old_candidate(self):
        candidate = self.checked()
        old_action = self.candidate_action('apply', candidate)
        self.problem['time'] = 11;self.state['time'] = 11;self.paging = compact_pages(self.problem)
        self.session = self.new_session()
        self.assert_rejected(self.send(old_action), 'stale_session')
        new_action = self.candidate_action('apply', candidate)
        self.assert_rejected(self.send(new_action), 'unknown_candidate')
        self.assertEqual(self.session.export_evidence()['candidates'], [])

    def test_new_session_with_same_snapshot_still_requires_own_successful_check(self):
        candidate = self.checked()
        self.session = self.new_session()
        self.assert_rejected(self.send(self.candidate_action('apply', candidate)), 'unknown_candidate')

    def test_call_reuse_or_decreasing_index_never_reinvokes_compiler(self):
        action = self.action('check_delta', delta=self.delta)
        with patch.object(module, 'compile_plan_delta', wraps=compile_plan_delta) as compiler:
            self.assertEqual(self.session.handle(action, call_id='actual-call', model_index=7)['status'], 'candidate_checked')
            self.assert_rejected(self.session.handle(action, call_id='actual-call', model_index=8), 'call_reuse')
            self.assert_rejected(self.session.handle(action, call_id='other-call', model_index=6), 'call_reuse')
            self.assert_rejected(self.session.handle(action, call_id='other-call', model_index=9), 'call_reuse')
        compiler.assert_called_once()
        self.assertEqual(len(self.session.export_evidence()['history']), 4)

    def test_apply_cannot_share_check_model_call_or_index(self):
        candidate = self.checked()
        action = self.candidate_action('apply', candidate)
        self.assert_rejected(self.session.handle(action, call_id='call-0', model_index=1), 'call_reuse')
        self.assert_rejected(self.session.handle(action, call_id='new-call', model_index=0), 'call_reuse')
        self.assertIsNone(self.session.export_evidence()['selection'])

    def test_rejected_delta_retains_raw_action_and_compiler_diagnostic_without_repair(self):
        invalid = deepcopy(self.delta);invalid['tasks']['keep'] = {'mode': 'ids', 'ids': []}
        action = self.action('check_delta', delta=invalid)
        response = self.send(action)
        self.assert_rejected(response, 'partition')
        evidence = self.session.export_evidence()
        self.assertEqual(evidence['history'][0]['action'], action)
        self.assertEqual(evidence['history'][0]['response'], response)
        self.assertEqual(response['error']['origin'], 'compiler')
        self.assertEqual(evidence['candidates'], [])
        self.assertIsNone(evidence['selection'])

    def test_unexpected_compiler_failure_is_recorded_and_not_retried(self):
        with patch.object(module, 'compile_plan_delta', side_effect=RuntimeError('synthetic compiler failure')) as compiler:
            result = self.send(self.action('check_delta', delta=self.delta))
        compiler.assert_called_once()
        self.assert_rejected(result, 'action_exception')
        self.assertEqual(result['error']['type'], 'RuntimeError')
        self.assertEqual(result['error']['detail'], 'synthetic compiler failure')
        self.assertEqual(self.session.export_evidence()['candidates'], [])

    def test_json_schema_and_call_type_rejections_are_recorded(self):
        for action in ([], {'action': 'choose_best'}, {**self.action('read_candidates'), 'automatic_apply': True}):
            self.assert_rejected(self.send(action), 'action_schema')
        self.assert_rejected(self.session.handle(self.action('read_candidates'), call_id=True, model_index=10), 'call_identity')
        self.assert_rejected(self.session.handle(self.action('read_candidates'), call_id='typed', model_index=True), 'call_identity')
        self.assertEqual(len(self.session.export_evidence()['history']), 5)
        before = self.session.export_evidence()
        with self.assertRaisesRegex(SessionError, 'non_json_input'):
            self.session.handle({'action': float('nan')}, call_id='nan', model_index=11)
        self.assertEqual(self.session.export_evidence(), before)

    def test_input_catalog_response_and_export_mutations_do_not_change_session(self):
        expected = self.session.describe()
        self.base['tasks'][1]['not_before'] = 99
        self.problem['operations'][0]['priority'] = -99
        self.state['time'] = 90
        self.paging['pages'].clear()
        changed = self.session.describe();changed['anchors'].clear();changed['base_task_ids'].clear()
        exported = self.session.export_evidence();exported['inputs']['base_plan']['tasks'].clear()
        self.assertEqual(self.session.describe(), expected)
        response = self.send(self.action('read_base_tasks', task_ids=['z']))
        response['tasks'][0]['not_before'] = -1
        self.assertEqual(self.send(self.action('read_base_tasks', task_ids=['z']))['tasks'][0]['not_before'], 12)

    def test_candidate_and_selection_returns_are_detached(self):
        candidate = self.checked()
        full = self.send(self.candidate_action('read_candidate', candidate))
        full['candidate']['compiled']['plan']['tasks'].clear()
        chosen = self.send(self.candidate_action('apply', candidate))
        self.assertEqual(len(chosen['candidate']['compiled']['plan']['tasks']), 2)
        chosen['candidate']['compiled']['plan']['tasks'].clear()
        self.assertEqual(len(self.session.export_evidence()['selection']['candidate']['compiled']['plan']['tasks']), 2)

    def test_complete_history_hash_chain_binds_queries_rejections_checks_and_selection(self):
        self.send(self.action('read_page', page_index=1))
        self.send(self.action('read_base_tasks', task_ids=['missing']))
        candidate = self.checked()
        self.send(self.candidate_action('apply', candidate))
        history = self.session.export_evidence()['history']
        previous = None
        for index, row in enumerate(history):
            self.assertEqual(row['action_index'], index)
            self.assertEqual(row['call_id'], 'call-' + str(index))
            self.assertEqual(row['model_index'], index)
            self.assertEqual(row['previous_record_sha256'], previous)
            self.assertEqual(row['action_sha256'], json_sha256(row['action']))
            self.assertEqual(row['response_sha256'], json_sha256(row['response']))
            self.assertEqual(row['record_sha256'], json_sha256({k: v for k, v in row.items() if k != 'record_sha256'}))
            previous = row['record_sha256']

    def test_complete_v2_and_exact_problem_required_at_initialization(self):
        for mutate in (lambda p: p['pages'].pop(),
                       lambda p: p.update(schema='fullfab-compact-paging-v1'),
                       lambda p: p['pages'][0][0]['operations'].pop(),
                       lambda p: p.update(source_problem_sha256='b' * 64)):
            invalid = deepcopy(self.paging);mutate(invalid)
            with self.assertRaises(SessionError):
                DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=invalid)
        modified = deepcopy(self.problem);modified['operations'][0]['priority'] = 7
        with self.assertRaisesRegex(SessionError, 'paging_mismatch'):
            DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=compact_pages(modified))

    def test_unused_top_level_recommendations_or_changed_explanations_are_rejected(self):
        mutations = [
            {'ranked_recommendations': ['op-new', 'op-a']},
            {'preferred_candidate': 'op-new'},
            {'dictionary_semantics': 'use highest priority first'},
            {'operation_identity': 'choose the first operation only'},
            {'page_index': 0},
        ]
        for change in mutations:
            with self.subTest(change=change):
                invalid = deepcopy(self.paging);invalid.update(change)
                with self.assertRaisesRegex(SessionError, 'paging_metadata'):
                    DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=invalid)
        missing = deepcopy(self.paging);missing.pop('dictionary_semantics')
        with self.assertRaisesRegex(SessionError, 'paging_metadata'):
            DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=missing)

    def test_supported_observation_end_mirror_is_exact_and_cannot_extend_window(self):
        valid = deepcopy(self.paging);valid['observation_end'] = self.state['observation_end']
        session = DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=valid)
        self.assertEqual(session.describe()['paging_metadata']['observation_end'], 100)
        for value in (99999, True, 100.0, '100', None):
            with self.subTest(value=value):
                invalid = deepcopy(self.paging);invalid['observation_end'] = value
                with self.assertRaisesRegex(SessionError, 'paging_metadata'):
                    DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=invalid)

    def test_page_count_and_public_problem_mirrors_cannot_be_relabelled(self):
        for change in ({'page_count': 99999}, {'page_count': 2.0}, {'page_count': True},
                       {'time': 11}, {'scope': [1]}, {'horizon_end': 99999}):
            with self.subTest(change=change):
                invalid = deepcopy(self.paging);invalid.update(change)
                with self.assertRaises(SessionError):
                    DeltaSession(self.base, self.problem, self.state, source_sha256=SOURCE, paging=invalid)

    def test_logical_session_id_does_not_claim_cross_instance_call_or_selection_deduplication(self):
        other = self.new_session()
        self.assertEqual(self.session.describe()['session_id'], other.describe()['session_id'])
        self.assertIn('logical snapshot', other.describe()['session_identity_semantics'])
        self.assertIn('object only', other.describe()['call_uniqueness_scope'])
        self.assertIn('cross-instance', other.describe()['selection_once_scope'])
        check = self.action('check_delta', delta=self.delta)
        first = self.session.handle(check, call_id='same-external-call', model_index=0)['candidate']
        second = other.handle(check, call_id='same-external-call', model_index=0)['candidate']
        self.assertEqual(first, second)
        apply = self.candidate_action('apply', first)
        for session in (self.session, other):
            result = session.handle(apply, call_id='same-external-selection', model_index=1)
            self.assertEqual(result['status'], 'selection_for_external_commit')
            self.assertFalse(result['physical_commit_performed'])
            self.assertIn('prevent duplicate-instance execution', session.export_evidence()['caller_required_bindings'])

    def test_state_source_or_duplicate_reference_binding_is_rejected(self):
        with self.assertRaises(SessionError):self.new_session(source='not-a-hash')
        self.state['base_plan_version'] = 'wrong'
        with self.assertRaisesRegex(SessionError, 'state_binding'):self.new_session()
        self.state['base_plan_version'] = 'base';self.state['dispatched_task_ids'] = ['alien']
        with self.assertRaisesRegex(SessionError, 'state_binding'):self.new_session()
        self.state['dispatched_task_ids'] = ['done'];self.base['tasks'][1]['id'] = 'done'
        with self.assertRaisesRegex(SessionError, 'duplicate_ids'):self.new_session()

    def test_module_has_only_pure_declared_dependencies(self):
        tree = ast.parse(Path(module.__file__).read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):names.append(node.module)
        self.assertEqual(set(names), {'copy', 'math', 'interface', 'plan_delta'})


if __name__ == '__main__':
    unittest.main()
