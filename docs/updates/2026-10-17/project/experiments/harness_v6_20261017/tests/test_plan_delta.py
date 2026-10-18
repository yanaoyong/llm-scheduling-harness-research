"""Pure synthetic delta choices. No environment, model, CP or planner imports."""
from copy import deepcopy
import unittest
from harness_v6.delta_schema import model_task

from harness_v6.plan_delta import (
    SCHEMA, STATE_SCHEMA, ORDER_POLICY, DeltaError, anchor_hashes, compile_plan_delta, json_sha256,
)

SOURCE = 'a' * 64


def task(tid, machine=1, start=12):
    return {'id': tid, 'machine': machine, 'lot_ids': ['lot-' + tid], 'steps': [1], 'visits': [1],
            'operation_ids': ['op-' + tid], 'not_before': start}


def operation(tid):
    return {'operation_id': 'op-' + tid, 'lot_id': 'lot-' + tid, 'step': 1, 'visit': 1,
            'eligible_machines': [1, 2], 'family': 'F', 'batch_key': ['product', 1, 'recipe'], 'batch_min': 1, 'batch_max': 1}


class PlanDeltaTests(unittest.TestCase):
    def setUp(self):
        self.base = {'version': 'base', 'created_at': 0, 'valid_until': 100, 'freeze_until': 0,
                     'reason': 'original model choice', 'scope': [1, 2, 913],
                     'tasks': [task('done', start=0), task('z'), task('c', 2, 16), task('a', start=18)],
                     'holds': [{'machine': 1, 'until': 90, 'reason': 'tail', 'after_task_id': 'a'},
                               {'machine': 913, 'until': 90, 'reason': 'explicit idle'},
                               {'machine': 2, 'until': 90, 'reason': 'tail', 'after_task_id': 'c'}]}
        self.problem = {'time': 10, 'horizon_end': 100, 'scope': [1, 2, 913],
                        'machines': [{'machine': 1, 'family': 'F'}, {'machine': 2, 'family': 'F'}, {'machine': 913, 'family': 'idle'}],
                        'operations': [operation(x) for x in ('done', 'z', 'c', 'a', 'new')]}
        self.state = {'schema': STATE_SCHEMA, 'time': 10, 'observation_end': 100,
                      'base_plan_version': 'base', 'dispatched_task_ids': ['done']}
        self.delta = {
                      'plan_header': {'valid_until': 100, 'freeze_until': 10,
                                      'reason': 'model explicitly retains exact pending tasks'},
                      'tasks': {'cancel_ids': [], 'replace': [], 'add': []},
                      'holds': {'cancel_ids': [], 'replace': [], 'add': []},
                      'machine_orders': []}


    def compile(self):
        return compile_plan_delta(self.base, self.problem, self.state, self.delta, source_sha256=SOURCE)

    def reject(self, code):
        before = deepcopy((self.base, self.problem, self.state, self.delta))
        with self.assertRaises(DeltaError) as error:self.compile()
        self.assertEqual(error.exception.code, code, str(error.exception))
        self.assertEqual((self.base, self.problem, self.state, self.delta), before)

    def test_exact_carry_preserves_full_values_and_machine_order_without_sorting(self):
        before = deepcopy((self.base, self.problem, self.state, self.delta))
        result = self.compile()
        self.assertEqual(result['plan']['tasks'], self.base['tasks'][1:])
        self.assertEqual([t['id'] for t in result['plan']['tasks'] if t['machine'] == 1], ['z', 'a'])
        self.assertEqual(result['plan']['holds'], self.base['holds'])
        self.assertEqual(result['evidence']['physically_dispatched_excluded_ids'], ['done'])
        self.assertFalse(result['evidence']['model_attribution_certified'])
        self.assertTrue(result['evidence']['common_commit_validation_required'])
        self.assertIn('explicit model commit', result['evidence']['caller_required_bindings'])
        self.assertEqual(result['evidence']['compiled_plan_sha256'], json_sha256(result['plan']))
        self.assertEqual((self.base, self.problem, self.state, self.delta), before)

    def test_implicit_retention_preserves_queue_order(self):
        self.assertEqual(self.compile()['plan']['tasks'], self.base['tasks'][1:])

    def test_keep_is_not_a_model_field_and_overlap_rejected(self):
        self.delta['tasks']['keep'] = {'mode': 'ids', 'ids': ['z', 'a']}
        self.reject('schema')
        del self.delta['tasks']['keep']
        self.delta['tasks']['cancel_ids'] = ['z'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}]
        self.delta['tasks']['replace'] = [model_task(self.base['tasks'][1])]
        self.reject('partition')

    def test_explicit_cancellation_stably_deletes_only_chosen_task(self):

        self.delta['tasks']['cancel_ids'] = ['z'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}]
        result = self.compile()
        self.assertEqual([t['id'] for t in result['plan']['tasks']], ['c', 'a'])
        self.assertEqual(result['plan']['holds'], self.base['holds'])

    def test_past_start_is_not_implicitly_clamped_and_explicit_replace_can_change_it(self):
        self.base['tasks'][1]['not_before'] = 4
        # v6 F2: past lower bounds are satisfied, preserved verbatim.
        self.assertEqual(self.compile()['plan']['tasks'][0]['not_before'], 4)
        replacement = model_task(self.base['tasks'][1]);replacement['not_before'] = 10

        self.delta['tasks']['replace'] = [replacement]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a']}]
        self.assertEqual(self.compile()['plan']['tasks'][0]['not_before'], 10)
        self.assertEqual(self.base['tasks'][1]['not_before'], 4)

    def test_missing_operation_and_changed_visit_are_never_repaired(self):
        self.problem['operations'] = [o for o in self.problem['operations'] if o['operation_id'] != 'op-z']
        self.reject('unknown_operation')
        self.problem['operations'].append(operation('z'));self.problem['operations'][-1]['visit'] = 2
        self.reject('task_identity')

    def test_dispatched_id_cannot_be_kept_cancelled_replaced_or_readded(self):
        self.delta['tasks']['cancel_ids'] = ['done'];self.reject('unknown_or_dispatched_id')
        self.delta['tasks']['cancel_ids'] = [];self.delta['tasks']['replace'] = [model_task(task('done'))]
        self.reject('unknown_or_dispatched_id')
        self.delta['tasks']['replace'] = [];self.delta['tasks']['add'] = [model_task(task('done'))]
        self.reject('reused_id')

    def test_new_id_cannot_resubmit_an_already_dispatched_operation(self):
        t = model_task(task('done'));t['id'] = 'new-task-id';t['not_before'] = 20
        self.delta['tasks']['add'] = [t]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a', 'new-task-id']}]
        self.reject('operation_reuse')

    def test_new_task_requires_explicit_complete_machine_order(self):
        self.delta['tasks']['add'] = [model_task(task('new', start=11))]
        self.reject('missing_machine_order')
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a', 'new', 'z']}]
        result = self.compile()
        self.assertEqual([t['id'] for t in result['plan']['tasks'] if t['machine'] == 1], ['a', 'new', 'z'])
        self.assertEqual([t['not_before'] for t in result['plan']['tasks'] if t['machine'] == 1], [18, 11, 12])
        # Nonmonotone lower bounds stay exactly chosen, with no time repair.

    def test_move_requires_both_old_and_new_machine_order(self):
        t = model_task(self.base['tasks'][1])
        self.delta['tasks']['replace'] = [t]
        self.delta['machine_orders'] = [{'machine': 2, 'task_ids': ['c', 'z']}]
        self.reject('missing_machine_order')
        self.delta['machine_orders'].append({'machine': 1, 'task_ids': ['a']})
        self.assertEqual([t['id'] for t in self.compile()['plan']['tasks'] if t['machine'] == 2], ['c', 'z'])

    def test_machine_order_cannot_drop_duplicate_or_invent_task(self):
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z']}]
        self.reject('machine_order')
        self.delta['machine_orders'][0]['task_ids'] = ['z', 'z'];self.reject('duplicate_ids')
        self.delta['machine_orders'][0]['task_ids'] = ['z', 'alien'];self.reject('machine_order')

    def test_cancelled_or_dispatched_hold_anchor_is_not_migrated(self):
        self.delta['tasks']['cancel_ids'] = ['a'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z']}]
        self.reject('hold_anchor')
        self.delta['holds']['cancel_ids'] = ['h:0']
        self.assertEqual(len(self.compile()['plan']['holds']), 2)
        self.delta['tasks']['cancel_ids'] = [];self.delta['machine_orders'] = []
        self.delta['holds']['cancel_ids'] = []
        self.state['dispatched_task_ids'].append('a');self.reject('hold_anchor')

    def test_explicit_hold_replacement_can_authorize_unconditional_wait(self):
        self.delta['tasks']['cancel_ids'] = ['a'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z']}]
        h = deepcopy(self.base['holds'][0]);h['after_task_id'] = None
        self.delta['holds']['replace'] = [{'ref': 'h:0', 'hold': h}]
        result = self.compile()
        self.assertIsNone(result['plan']['holds'][0]['after_task_id'])
        self.assertEqual(self.base['holds'][0]['after_task_id'], 'a')

    def test_expired_hold_has_no_effect_and_hold_partition_is_complete(self):
        self.base['holds'][1]['until'] = 9
        self.assertEqual(self.compile()['plan']['holds'][1]['until'], 9)
        self.base['holds'][1]['until'] = 90
        self.delta['holds']['cancel_ids'] = ['h:1']
        self.delta['holds']['replace'] = [{'ref': 'h:1', 'hold': self.base['holds'][1]}]
        self.reject('partition')

    def test_frozen_past_start_must_be_identical_and_frozen_order_preserved(self):
        self.base['freeze_until'] = 20;self.base['tasks'][1]['not_before'] = 4
        self.delta['plan_header']['freeze_until'] = 20
        result = self.compile();self.assertEqual(result['plan']['tasks'][0]['not_before'], 4)
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a', 'z']}]
        self.reject('frozen_prefix')
        self.delta['machine_orders'] = [];
        t = model_task(self.base['tasks'][1]);t['not_before'] = 4.0
        self.delta['tasks']['replace'] = [t]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a']}]
        self.reject('frozen_task')

    def test_two_delta_attempt_cannot_unfreeze_then_cancel(self):
        self.base['freeze_until'] = 20
        # Attack stage 1 used to preserve tasks but shrink the freeze to now;
        # stage 2 could then remove them from the new base before original t=20.
        self.reject('frozen_horizon')
        self.delta['plan_header']['freeze_until'] = 20
        self.base = self.compile()['plan']
        self.state.update(time=11, base_plan_version=self.base['version'], dispatched_task_ids=[])
        self.problem['time'] = 11
        self.delta['plan_header'].update(freeze_until=11)
        self.delta['tasks']['cancel_ids'] = ['z'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}]
        self.reject('frozen_horizon')
        self.delta['plan_header']['freeze_until'] = 20
        self.reject('frozen_task')

    def test_frozen_horizon_can_shrink_when_no_pending_task_is_frozen(self):
        # Only dispatched 'done' was before t=12. z starts exactly at t=12.
        self.base['freeze_until'] = 12
        self.assertEqual(self.compile()['plan']['freeze_until'], 10)

    def test_new_and_existing_nonfrozen_tasks_cannot_precede_frozen_prefix(self):
        self.base['freeze_until'] = 15
        self.delta['plan_header']['freeze_until'] = 15
        self.delta['tasks']['add'] = [model_task(task('new', start=13))]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['new', 'z', 'a']}]
        self.reject('frozen_prefix')
        self.delta['machine_orders'][0]['task_ids'] = ['z', 'new', 'a']
        result = self.compile()
        self.assertEqual([t['id'] for t in result['plan']['tasks'] if t['machine'] == 1], ['z', 'new', 'a'])
        self.assertEqual(result['evidence']['preserved_frozen_prefixes'],
                         [{'machine': 1, 'task_ids': ['z'], 'tasks_sha256': json_sha256([self.base['tasks'][1]])}])
        self.delta['tasks']['add'] = []
        self.delta['machine_orders'][0]['task_ids'] = ['a', 'z']
        self.reject('frozen_prefix')

    def test_nonfrozen_member_before_last_frozen_task_is_preserved_exactly(self):
        # Base same-machine queue is [z(nonfrozen), a(frozen)]. Preserving only
        # the frozen subsequence [a] would let z be moved/deleted or bypassed.
        self.base['freeze_until'] = 20;self.base['tasks'][1]['not_before'] = 25
        self.delta['plan_header']['freeze_until'] = 20
        self.assertEqual(self.compile()['evidence']['preserved_frozen_prefixes'][0]['task_ids'], ['z', 'a'])
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a', 'z']}]
        self.reject('frozen_prefix')
        self.delta['machine_orders'] = []
        self.delta['tasks']['cancel_ids'] = ['z'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}]
        self.reject('frozen_prefix')
        self.delta['tasks']['cancel_ids'] = [];self.delta['machine_orders'] = []
        replacement = model_task(self.base['tasks'][1])
        self.delta['tasks']['replace'] = [replacement]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a']}]
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['a']}, {'machine': 2, 'task_ids': ['c', 'z']}]
        self.reject('frozen_prefix')
        replacement['not_before'] = 26
        self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'a']}]
        self.reject('frozen_prefix')
        replacement['not_before'] = 25
        self.assertEqual(self.compile()['plan']['tasks'], self.base['tasks'][1:])

    def test_no_insertion_between_two_frozen_tasks_or_into_protected_nonfrozen_prefix(self):
        for first_start in (12, 25):
            with self.subTest(first_start=first_start):
                self.base['freeze_until'] = 20;self.base['tasks'][1]['not_before'] = first_start
                self.delta['plan_header']['freeze_until'] = 20
                self.delta['tasks']['add'] = [model_task(task('new', start=30))]
                self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z', 'new', 'a']}]
                self.reject('frozen_prefix')
                self.delta['machine_orders'][0]['task_ids'] = ['z', 'a', 'new']
                self.assertEqual([t['id'] for t in self.compile()['plan']['tasks'] if t['machine'] == 1], ['z', 'a', 'new'])

    def test_observed_operation_bool_and_equal_float_identities_are_rejected(self):
        for field in ('step', 'visit'):
            for value in (True, 1.0, 0, -1):
                with self.subTest(field=field, value=value):
                    self.problem['operations'][1][field] = value
                    self.reject('observed_identity')
                    self.problem['operations'][1][field] = 1
        for field in ('operation_id', 'lot_id', 'family'):
            for value in (True, 1, ''):
                with self.subTest(field=field, value=value):
                    old = self.problem['operations'][1][field]
                    self.problem['operations'][1][field] = value
                    self.reject('observed_identity')
                    self.problem['operations'][1][field] = old

    def test_observed_qualification_types_cannot_alias_integer_machine(self):
        for eligible in ([True, 2], [1.0, 2], [1, 1], [1, 999], [], '1', [913]):
            with self.subTest(eligible=eligible):
                self.problem['operations'][1]['eligible_machines'] = eligible
                self.reject('observed_eligibility')
        self.problem['operations'][1]['eligible_machines'] = [1, 2]
        for owner in (self.problem, self.base):
            owner['scope'][0] = True;self.reject('scope')
            owner['scope'][0] = 1
        self.problem['machines'][0]['machine'] = True;self.reject('schema')

    def test_observed_batch_integer_types_are_checked_before_batch_equality(self):
        for field in ('batch_min', 'batch_max'):
            for value in (True, 1.0, 0):
                with self.subTest(field=field, value=value):
                    self.problem['operations'][1][field] = value
                    self.reject('observed_batch')
                    self.problem['operations'][1][field] = 1
        for key in (['product', True, 'recipe'], ['product', 1.0, 'recipe'],
                    ['product', 2, 'recipe'], [True, 1, 'recipe'], ['product', 1, True], ['product', 1]):
            with self.subTest(batch_key=key):
                self.problem['operations'][1]['batch_key'] = key
                self.reject('observed_batch')

    def test_anchors_are_host_computed_and_model_cannot_supply_them(self):
        self.assertEqual(self.compile()['evidence']['anchors'], anchor_hashes(self.base, self.problem, self.state, source_sha256=SOURCE))
        self.delta['anchors'] = {'problem_sha256': 'b' * 64}
        self.reject('schema')

    def test_problem_time_and_base_state_version_cannot_be_inferred(self):
        self.problem['time'] = 9;self.reject('stale_observation')
        self.problem['time'] = 10;self.state['base_plan_version'] = 'other';self.reject('base_state')
        self.state['base_plan_version'] = 'base';self.state['dispatched_task_ids'] = ['alien'];self.reject('base_state')

    def test_no_type_coercion_for_retained_id_and_new_machine(self):
        self.base['tasks'][1]['id'] = 7;self.reject('ids')
        self.base['tasks'][1]['id'] = 'z'
        self.delta['tasks']['add'] = [model_task(task('new'))]
        self.delta['machine_orders'] = [{'machine': '1', 'task_ids': ['z', 'a', 'new']}]
        self.reject('machine_order')

    def test_batch_membership_is_explicit_and_constraints_only_reject(self):
        t = model_task(self.base['tasks'][1])
        for key in ('operation_ids',):t[key] += self.base['tasks'][2][key]
        self.delta['tasks']['replace'] = [t];self.delta['tasks']['cancel_ids'] = ['c'];self.delta['machine_orders'] = [{'machine': 1, 'task_ids': ['z','a']}, {'machine': 2, 'task_ids': []}]
        self.delta['holds']['cancel_ids'] = ['h:2']
        self.reject('batch')  # Batch max1: no shrinking, splitting or substituting.
        for op in self.problem['operations']:
            if op['operation_id'] in ('op-z', 'op-c'):op['batch_max'] = 2
        self.assertEqual(self.compile()['plan']['tasks'][0]['lot_ids'], ['lot-z', 'lot-c'])
        self.problem['operations'][2]['eligible_machines'] = [2];self.reject('eligibility')

    def test_scope_window_and_unknown_transform_selector_rejected(self):
        self.delta['plan_header']['scope'] = [1, 2];self.reject('schema')
        del self.delta['plan_header']['scope']
        self.delta['plan_header']['valid_until'] = 101;self.reject('header')
        self.delta['plan_header']['valid_until'] = 100
        self.delta['tasks']['clamp_all_starts_to_now'] = True;self.reject('schema')

    def test_outputs_are_detached_and_repeat_deterministically(self):
        first, second = self.compile(), self.compile()
        self.assertEqual(first, second)
        first['plan']['tasks'][0]['lot_ids'][0] = 'mutated returned copy'
        self.assertEqual(self.compile(), second)


if __name__ == '__main__':unittest.main()
