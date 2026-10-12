"""Small JSON fixtures only; no model, environment, optimizer or simulation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from src.smt_fullfab import B_delta_assembly as module
from src.smt_fullfab.B_delta_assembly import DeltaAssembly, AssemblyError, AdmissionError
from src.smt_fullfab.plan_delta import anchor_hashes, compile_plan_delta, DeltaError


def fixture():
    def task(tid, machine, start):
        return {'id': tid, 'machine': machine, 'lot_ids': ['lot-' + tid], 'steps': [1],
                'visits': [1], 'operation_ids': ['op-' + tid], 'not_before': start,
                'extra': {'中文': None, 'numeric_spelling': 1.0}}
    base = {'version': 'base', 'created_at': 0, 'valid_until': 100, 'freeze_until': 0,
            'reason': 'prior explicit plan', 'scope': [2, 1, 913],
            'tasks': [task('done', 1, 0), task('z', 1, 12), task('a', 2, 13)],
            'holds': [{'machine': 1, 'until': 90, 'after_task_id': 'z', 'reason': 'tail'},
                      {'machine': 913, 'until': 90, 'reason': 'wait'},
                      {'machine': 2, 'until': 90, 'after_task_id': 'a', 'reason': 'tail'}]}
    problem = {'schema': 'smt-fullfab-problem-2', 'time': 10, 'horizon_end': 100, 'scope': [2, 1, 913],
               'machines': [{'machine': 2, 'family': 'F'}, {'machine': 1, 'family': 'F'}, {'machine': 913, 'family': 'idle'}],
               'operations': [{'operation_id': 'op-' + tid, 'lot_id': 'lot-' + tid, 'step': 1, 'visit': 1,
                               'eligible_machines': [2, 1], 'family': 'F', 'batch_key': ['part', 1, 'recipe'],
                               'batch_min': 1, 'batch_max': 1} for tid in ('z', 'done', 'a', 'new-2', 'new-1')]}
    state = {'schema': 'smt-fullfab-plan-delta-state-v1', 'time': 10, 'observation_end': 100,
             'base_plan_version': 'base', 'dispatched_task_ids': ['done']}
    anchors = anchor_hashes(base, problem, state, source_sha256='a' * 64)
    delta = {'schema': module.DELTA_SCHEMA, 'anchors': anchors,
             'plan_header': {'version': 'delta-1', 'created_at': 10, 'valid_until': 100,
                             'freeze_until': 10, 'reason': 'explicit new plan', 'scope': [2, 1, 913]},
             'order_policy': module.ORDER_POLICY,
             'tasks': {'keep': {'mode': 'ids', 'ids': ['a']}, 'cancel_ids': [],
                       'replace': [task('z', 1, 14)], 'add': [task('new-2', 2, 15), task('new-1', 1, 16)]},
             'holds': {'keep': {'mode': 'ids', 'ids': ['h:2']}, 'cancel_ids': ['h:1'],
                       'replace': [{'ref': 'h:0', 'hold': {'machine': 1, 'until': 95, 'after_task_id': 'z', 'reason': 'explicit edit'}}],
                       'add': [{'machine': 913, 'until': 100, 'reason': 'new wait', 'nullable': None}]},
             'machine_orders': [{'machine': 2, 'task_ids': ['new-2', 'a']}, {'machine': 1, 'task_ids': ['z', 'new-1']}]}
    return base, problem, state, delta


def value_at(root, path):
    for key in path:
        root = root[key]
    return root


def declarations(delta):
    return ([{'path': list(p), 'value': deepcopy(value_at(delta, p))} for p in module.SET_PATHS],
            [{'path': list(p), 'items': deepcopy(value_at(delta, p))} for p in module.ARRAY_PATHS])


def chunk(assembly, chunk_id, sets=None, arrays=None):
    snap = assembly.snapshot()
    return {'schema': module.SCHEMA, 'action': 'chunk', 'draft_id': snap['state']['draft_id'],
            'anchors': snap['state']['anchors'], 'previous_state_sha256': snap['state_sha256'],
            'sequence': snap['state']['next_sequence'], 'chunk_id': chunk_id,
            'set_fields': [] if sets is None else deepcopy(sets),
            'append_arrays': [] if arrays is None else deepcopy(arrays)}


def seal(assembly):
    snap = assembly.snapshot()
    return {'schema': module.SCHEMA, 'action': 'seal', 'draft_id': snap['state']['draft_id'],
            'anchors': snap['state']['anchors'], 'previous_state_sha256': snap['state_sha256']}


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.base, self.problem, self.state, self.delta = fixture()
        self.assembly = self.new()

    def new(self):
        return DeltaAssembly('explicit-draft-1', self.delta['anchors'])

    def full(self, assembly=None, delta=None):
        assembly = self.assembly if assembly is None else assembly
        sets, arrays = declarations(self.delta if delta is None else delta)
        response = assembly.submit(chunk(assembly, 'full', sets, arrays))
        self.assertEqual(response['status'], 'chunk_accepted', response)
        return response

    def reject(self, action, code):
        before = self.assembly.snapshot()
        result = self.assembly.submit(action)
        self.assertEqual(result['status'], 'rejected', result)
        self.assertEqual(result['error']['code'], code, result)
        self.assertEqual(before, self.assembly.snapshot())
        self.assertEqual(self.assembly.export_evidence()['history'][-1]['raw_action'], action)
        return result

    def test_two_chunks_equal_single_complete_delta_and_compiler_result(self):
        sets, arrays = declarations(self.delta)
        later = []
        for declaration in arrays:
            if declaration['path'] in (['tasks', 'add'], ['machine_orders']):
                later.append({'path': declaration['path'], 'items': declaration['items'][1:]})
                declaration['items'] = declaration['items'][:1]
        a = chunk(self.assembly, 'first', sets, arrays)
        self.assertEqual(self.assembly.submit(a)['status'], 'chunk_accepted')
        b = chunk(self.assembly, 'second', [], later)
        self.assertEqual(self.assembly.submit(b)['status'], 'chunk_accepted')
        before_seal = self.assembly.state_sha256
        sealed = self.assembly.submit(seal(self.assembly))
        other = self.new()
        self.full(other)
        single = other.submit(seal(other))
        self.assertEqual(sealed['delta'], self.delta)
        self.assertEqual(sealed['delta_sha256'], single['delta_sha256'])
        self.assertEqual(sealed['pre_seal_state_sha256'], before_seal)
        self.assertEqual(sealed['delta']['tasks']['add'][0]['id'], 'new-2')
        self.assertEqual([o['machine'] for o in sealed['delta']['machine_orders']], [2, 1])
        compiled = compile_plan_delta(self.base, self.problem, self.state, sealed['delta'], source_sha256='a' * 64)
        expected = compile_plan_delta(self.base, self.problem, self.state, self.delta, source_sha256='a' * 64)
        self.assertEqual(compiled, expected)
        self.assertEqual([t['id'] for t in compiled['plan']['tasks'] if t['machine'] == 2], ['new-2', 'a'])
        self.assertFalse(sealed['assurance']['compiler_called'])
        self.assertFalse(sealed['assurance']['selection_for_external_commit'])

    def test_original_chunks_independently_rebuild_and_every_item_has_origin(self):
        sets, arrays = declarations(self.delta)
        later = []
        for row in arrays:
            if row['path'] == ['tasks', 'add']:
                later.append({'path': row['path'], 'items': row['items'][1:]})
                row['items'] = row['items'][:1]
        self.assembly.submit(chunk(self.assembly, 'x', sets, arrays))
        self.assembly.submit(chunk(self.assembly, 'y', [], later))
        self.assembly.submit(seal(self.assembly))
        evidence = self.assembly.export_evidence()
        rebuilt = {}
        for action in evidence['accepted_chunks']:
            for row in action['set_fields']:
                target = rebuilt
                for key in row['path'][:-1]:
                    target = target.setdefault(key, {})
                target[row['path'][-1]] = deepcopy(row['value'])
            for row in action['append_arrays']:
                target = rebuilt
                for key in row['path'][:-1]:
                    target = target.setdefault(key, {})
                target.setdefault(row['path'][-1], []).extend(deepcopy(row['items']))
        self.assertEqual(rebuilt, self.delta)
        chunks = {a['chunk_id']: a for a in evidence['accepted_chunks']}
        for source in evidence['sealed']['sources']:
            expected = value_at(self.delta, source['path'])
            if source['kind'] == 'field':
                origin = source['origin']
                raw = chunks[origin['chunk_id']]
                self.assertEqual(raw['set_fields'][origin['set_fields_index']]['value'], expected)
                self.assertEqual(origin['action_sha256'], module.sha256(raw))
            else:
                origin = source['declaration_origin']
                self.assertEqual(chunks[origin['chunk_id']]['append_arrays'][origin['append_arrays_index']]['path'], source['path'])
                self.assertEqual(len(source['items']), len(expected))
                for item in source['items']:
                    origin = item['origin'];raw = chunks[origin['chunk_id']]
                    value = raw['append_arrays'][origin['append_arrays_index']]['items'][origin['items_index']]
                    self.assertEqual(value, expected[item['output_index']])
                    self.assertEqual(origin['action_sha256'], module.sha256(raw))
        previous = None
        for row in evidence['history']:
            self.assertEqual(row['previous_history_sha256'], previous)
            body = {k: v for k, v in row.items() if k != 'row_sha256'}
            self.assertEqual(module.sha256(body), row['row_sha256'])
            previous = row['row_sha256']

    def test_missing_array_is_not_defaulted_and_rejection_does_not_consume_sequence(self):
        sets, arrays = declarations(self.delta)
        omitted = arrays.pop(1)
        self.assembly.submit(chunk(self.assembly, 'partial', sets, arrays))
        self.reject(seal(self.assembly), 'missing_fields')
        self.assertEqual(self.assembly.snapshot()['state']['next_sequence'], 1)
        self.assertEqual(self.assembly.submit(chunk(self.assembly, 'finish', [], [omitted]))['status'], 'chunk_accepted')
        self.assertEqual(self.assembly.submit(seal(self.assembly))['delta'], self.delta)

    def test_each_of_fifteen_required_paths_must_be_explicit(self):
        for missing in (*module.SET_PATHS, *module.ARRAY_PATHS):
            with self.subTest(path=missing):
                a = self.new();sets, arrays = declarations(self.delta)
                sets = [r for r in sets if tuple(r['path']) != missing]
                arrays = [r for r in arrays if tuple(r['path']) != missing]
                self.assertEqual(a.submit(chunk(a, 'partial', sets, arrays))['status'], 'chunk_accepted')
                self.assertEqual(a.submit(seal(a))['error']['code'], 'missing_fields')

    def test_wrong_draft_or_each_anchor_rejected(self):
        for key in module.ANCHOR_KEYS:
            action = chunk(self.assembly, 'x', [{'path': ['schema'], 'value': module.DELTA_SCHEMA}])
            action['anchors'][key] = 'f' * 64
            self.reject(action, 'stale_anchor')
        action = chunk(self.assembly, 'x');action['draft_id'] = 'different'
        self.reject(action, 'draft_id')

    def test_wrong_delta_anchor_cannot_be_declared(self):
        wrong = deepcopy(self.delta['anchors']);wrong['source_sha256'] = 'f' * 64
        self.reject(chunk(self.assembly, 'x', [{'path': ['anchors'], 'value': wrong}]), 'stale_anchor')

    def test_stale_hash_sequence_gap_and_bool_sequence(self):
        action = chunk(self.assembly, 'x');action['previous_state_sha256'] = '0' * 64
        self.reject(action, 'stale_state')
        for sequence in (1, -1, True, 0.0):
            action = chunk(self.assembly, 'x');action['sequence'] = sequence
            self.reject(action, 'sequence')

    def test_exact_replay_and_new_hash_duplicate_chunk_id_rejected(self):
        first = chunk(self.assembly, 'x', [{'path': ['schema'], 'value': module.DELTA_SCHEMA}])
        self.assembly.submit(first)
        self.reject(first, 'stale_state')
        self.reject(chunk(self.assembly, 'x', [{'path': ['anchors'], 'value': self.delta['anchors']}]), 'duplicate_chunk')

    def test_overwrite_and_duplicate_array_path_are_atomic(self):
        self.assembly.submit(chunk(self.assembly, 'one', [{'path': ['schema'], 'value': module.DELTA_SCHEMA}]))
        action = chunk(self.assembly, 'two', [{'path': ['anchors'], 'value': self.delta['anchors']},
                                            {'path': ['schema'], 'value': module.DELTA_SCHEMA}])
        self.reject(action, 'field_overwrite')
        row = {'path': ['tasks', 'add'], 'items': []}
        self.reject(chunk(self.assembly, 'two', [], [row, row]), 'duplicate_path')
        self.assertNotIn('anchors', self.assembly.snapshot()['state']['delta'])

    def test_empty_redeclaration_is_not_an_append(self):
        row = {'path': ['tasks', 'cancel_ids'], 'items': []}
        self.assembly.submit(chunk(self.assembly, 'one', [], [row]))
        self.reject(chunk(self.assembly, 'two', [], [row]), 'empty_append')

    def test_duplicate_native_identities_rejected_within_and_across_chunks(self):
        rows = [(['tasks', 'keep', 'ids'], ['a']), (['tasks', 'cancel_ids'], ['z']),
                (['tasks', 'replace'], self.delta['tasks']['replace']),
                (['tasks', 'add'], self.delta['tasks']['add'][:1]),
                (['holds', 'keep', 'ids'], ['h:2']), (['holds', 'cancel_ids'], ['h:1']),
                (['holds', 'replace'], self.delta['holds']['replace']),
                (['machine_orders'], self.delta['machine_orders'][:1])]
        for path, items in rows:
            with self.subTest(path=path):
                a = self.new()
                bad = chunk(a, 'bad', [], [{'path': path, 'items': items + items}])
                self.assertEqual(a.submit(bad)['error']['code'], 'duplicate_identity')
                self.assertEqual(a.submit(chunk(a, 'one', [], [{'path': path, 'items': items}]))['status'], 'chunk_accepted')
                response = a.submit(chunk(a, 'two', [], [{'path': path, 'items': items}]))
                self.assertEqual(response['error']['code'], 'duplicate_identity')

    def test_no_content_dedup_for_new_holds(self):
        hold = self.delta['holds']['add'][0]
        row = {'path': ['holds', 'add'], 'items': [hold, deepcopy(hold)]}
        response = self.assembly.submit(chunk(self.assembly, 'duplicates', [], [row]))
        self.assertEqual(response['status'], 'chunk_accepted')
        self.assertEqual(self.assembly.read(['holds', 'add'])['value'], [hold, hold])

    def test_add_replace_same_task_id_rejected(self):
        t = self.delta['tasks']['replace'][0]
        self.reject(chunk(self.assembly, 'x', [], [{'path': ['tasks', 'replace'], 'items': [t]},
                                                 {'path': ['tasks', 'add'], 'items': [t]}]), 'duplicate_identity')

    def test_machine_order_cannot_be_incrementally_extended(self):
        self.assembly.submit(chunk(self.assembly, 'x', [], [{'path': ['machine_orders'], 'items': [{'machine': 2, 'task_ids': ['a']}]}]))
        self.reject(chunk(self.assembly, 'y', [], [{'path': ['machine_orders'], 'items': [{'machine': 2, 'task_ids': ['new-2']}]}]), 'duplicate_identity')

    def test_incomplete_header_or_task_is_rejected_no_defaults(self):
        h = deepcopy(self.delta['plan_header']);del h['scope']
        self.reject(chunk(self.assembly, 'x', [{'path': ['plan_header'], 'value': h}]), 'schema')
        task = deepcopy(self.delta['tasks']['add'][0]);del task['not_before']
        self.reject(chunk(self.assembly, 'x', [], [{'path': ['tasks', 'add'], 'items': [task]}]), 'task')

    def test_bool_machine_step_scope_and_slice_are_not_integer_aliases(self):
        task = deepcopy(self.delta['tasks']['add'][0]);task['machine'] = True
        self.reject(chunk(self.assembly, 'x', [], [{'path': ['tasks', 'add'], 'items': [task]}]), 'task')
        task['machine'] = 2;task['steps'] = [True]
        self.reject(chunk(self.assembly, 'x', [], [{'path': ['tasks', 'add'], 'items': [task]}]), 'task')
        header = deepcopy(self.delta['plan_header']);header['scope'] = [True, 2]
        self.reject(chunk(self.assembly, 'x', [{'path': ['plan_header'], 'value': header}]), 'header')
        self.full()
        with self.assertRaises(AssemblyError) as caught:
            self.assembly.read(['tasks', 'add'], offset=True, count=1)
        self.assertEqual(caught.exception.code, 'slice')

    def test_no_unknown_fields_or_paths(self):
        action = chunk(self.assembly, 'x');action['ranking'] = 'first'
        self.reject(action, 'schema')
        self.reject(chunk(self.assembly, 'x', [{'path': ['tasks', 'default_keep'], 'value': True}]), 'path')

    def test_seal_needs_current_hash_and_cannot_be_repeated_or_modified(self):
        old = seal(self.assembly)
        self.full()
        self.reject(old, 'stale_state')
        chosen = seal(self.assembly)
        self.assertEqual(self.assembly.submit(chosen)['status'], 'sealed_delta')
        self.reject(chosen, 'sealed')
        self.reject(seal(self.assembly), 'sealed')
        self.reject(chunk(self.assembly, 'later'), 'sealed')

    def test_seal_is_not_compile_acceptance_and_never_applies(self):
        invalid = deepcopy(self.delta);invalid['tasks']['keep']['ids'] = []
        self.full(delta=invalid)
        response = self.assembly.submit(seal(self.assembly))
        self.assertEqual(response['status'], 'sealed_delta')
        with self.assertRaises(DeltaError):
            compile_plan_delta(self.base, self.problem, self.state, response['delta'], source_sha256='a' * 64)
        self.assertTrue(response['assurance']['assembly_only'])
        self.assertFalse(response['assurance']['physical_commit_performed'])

    def test_all_except_keep_exceptions_are_not_confused_with_duplicate_cancellation(self):
        delta = deepcopy(self.delta)
        delta['tasks']['keep'] = {'mode': 'all_pending_except', 'ids': ['z']}
        delta['holds']['keep'] = {'mode': 'all_except', 'ids': ['h:1', 'h:0']}
        self.full(delta=delta)
        result = self.assembly.submit(seal(self.assembly))
        compile_plan_delta(self.base, self.problem, self.state, result['delta'], source_sha256='a' * 64)

    def test_values_and_queries_are_detached_exact_and_not_ranked(self):
        self.full()
        response = self.assembly.read(['tasks', 'add'], offset=0, count=1)
        self.assertEqual(response['value'][0], self.delta['tasks']['add'][0])
        self.assertIs(type(response['value'][0]['extra']['numeric_spelling']), float)
        before = self.assembly.export_evidence()
        response['value'][0]['machine'] = 999
        snap = self.assembly.snapshot();snap['state']['delta']['tasks']['add'].clear()
        self.assertEqual(before, self.assembly.export_evidence())
        with self.assertRaises(AssemblyError):
            self.assembly.read(['recommendations'])

    def test_raw_rejected_action_history_is_detached_and_success_retry_keeps_sequence(self):
        action = chunk(self.assembly, 'x', [{'path': ['plan_header'], 'value': {'bad': ['原样']}}])
        original = deepcopy(action)
        self.reject(action, 'schema')
        action['set_fields'][0]['value']['bad'].append('changed')
        self.assertEqual(self.assembly.export_evidence()['history'][0]['raw_action'], original)
        self.full()
        self.assertEqual(self.assembly.snapshot()['state']['next_sequence'], 1)
        self.assertEqual(len(self.assembly.export_evidence()['history']), 2)

    def test_size_admission_retains_original_in_exception_without_replacing_history(self):
        action = chunk(self.assembly, 'x')
        with patch.object(module, 'MAX_ACTION_CHARS', len(module.render(action)) - 1):
            with self.assertRaises(AdmissionError) as caught:
                self.assembly.submit(action)
        self.assertIs(caught.exception.raw_action, action)
        self.assertEqual(caught.exception.code, 'action_size')
        self.assertEqual(self.assembly.export_evidence()['history'], [])

    def test_draft_limit_is_atomic_and_query_limit_does_not_truncate(self):
        with patch.object(module, 'MAX_DRAFT_CHARS', 1):
            self.reject(chunk(self.assembly, 'x', [{'path': ['schema'], 'value': module.DELTA_SCHEMA}]), 'draft_size')
        self.full()
        before = self.assembly.snapshot()
        with patch.object(module, 'MAX_QUERY_CHARS', 1):
            with self.assertRaises(AssemblyError) as caught:
                self.assembly.read([])
        self.assertEqual(caught.exception.code, 'query_size')
        self.assertEqual(self.assembly.snapshot(), before)

    def test_history_and_chunk_limits_do_not_reset_or_evict(self):
        self.full()
        before = self.assembly.export_evidence()
        for limit, value in [('MAX_ACTIONS', 1), ('MAX_HISTORY_ACTION_CHARS', 0)]:
            with patch.object(module, limit, value):
                with self.assertRaises(AdmissionError):
                    self.assembly.submit(seal(self.assembly))
            self.assertEqual(self.assembly.export_evidence(), before)
        a = self.new()
        with patch.object(module, 'MAX_CHUNKS', 0):
            action = chunk(a, 'x', [{'path': ['schema'], 'value': module.DELTA_SCHEMA}])
            self.assertEqual(a.submit(action)['error']['code'], 'chunk_limit')

    def test_non_json_and_nonfinite_admission_error_is_not_silently_normalized(self):
        for bad in ({'tuple': (1, 2)}, {'nan': float('nan')}, {1: 'not a JSON string key'}):
            with self.assertRaises(AdmissionError) as caught:
                self.assembly.submit(bad)
            self.assertIs(caught.exception.raw_action, bad)
        self.assertEqual(self.assembly.export_evidence()['history'], [])

    def test_large_exact_integer_is_not_implicitly_cast_to_float(self):
        task = deepcopy(self.delta['tasks']['add'][0]);task['not_before'] = 10 ** 400
        response = self.assembly.submit(chunk(self.assembly, 'x', [], [{'path': ['tasks', 'add'], 'items': [task]}]))
        self.assertEqual(response['status'], 'chunk_accepted')
        self.assertEqual(self.assembly.read(['tasks', 'add'])['value'][0]['not_before'], 10 ** 400)
        # Actual temporal feasibility is intentionally the subsequent compiler's duty.

    def test_cross_instance_identity_is_explicitly_not_certified(self):
        other = self.new()
        self.full();self.full(other)
        self.assertEqual(self.assembly.state_sha256, other.state_sha256)
        one = self.assembly.submit(seal(self.assembly));two = other.submit(seal(other))
        self.assertEqual(one['delta_sha256'], two['delta_sha256'])
        self.assertFalse(one['assurance']['model_attribution_certified'])
        self.assertIn('this object only', other.export_evidence()['identity_scope'])


if __name__ == '__main__':
    unittest.main()
