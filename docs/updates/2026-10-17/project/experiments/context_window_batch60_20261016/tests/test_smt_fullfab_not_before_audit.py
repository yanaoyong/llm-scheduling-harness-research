"""Small event-only regression cases; no environment, solver or model runs."""
import copy
import unittest

from src.smt_fullfab.audit import audit_opportunity_coverage, audit_trace
from tests.test_smt_fullfab_audit import renumber, trace_fixture


def waiting_trace(not_before=10, hold=None):
    events = trace_fixture()[:4]
    plan = events[3]['plan']
    plan['tasks'][0]['not_before'] = not_before
    if hold is not None:
        plan['holds'] = [{'machine': 0, 'until': hold, 'reason': 'explicit wait'}]
    events += [
        {'kind': 'time_advance', 'time': 0, 'to': 20},
        {'kind': 'terminal', 'time': 20, 'lot_statuses': {'x': 'waiting'}, 'metrics': {}},
    ]
    return renumber(events)


class NotBeforeAuditTests(unittest.TestCase):
    def assert_valid(self, events):
        result = audit_trace(renumber(events))
        self.assertTrue(result['valid'], result['errors'])
        return result

    def test_clock_jump_cannot_cross_executable_not_before(self):
        # Before the boundary repair, both audits accepted these six events.
        # At 10 the singleton exact submitted task is executable; no dispatch
        # occurs before the declared jump reaches 20.
        events = waiting_trace()
        for audit in (audit_opportunity_coverage, audit_trace):
            with self.subTest(audit=audit.__name__):
                result = audit(events)
                self.assertFalse(result['valid'])
                self.assertTrue(any('executable submitted task t1' in error and
                                    'at 10' in error for error in result['errors']))

    def test_arriving_at_not_before_then_dispatching_is_valid(self):
        events = trace_fixture()
        events[3]['plan']['tasks'][0]['not_before'] = 10
        dispatch = events[4]
        dispatch.update(time=10, machine_ready=20, process_end=20, lot_end=20)
        events[5].update(time=10, to=20)
        events[6]['time'] = events[7]['time'] = 20
        del events[8]
        events.insert(4, {'kind': 'time_advance', 'time': 0, 'to': 10})
        self.assert_valid(events)

    def test_explicit_hold_can_span_not_before(self):
        self.assert_valid(waiting_trace(hold=20))

    def test_not_before_equal_to_window_endpoint_is_not_skipped(self):
        # Advances cover [time, to); reaching the endpoint is not advancing past it.
        self.assert_valid(waiting_trace(not_before=20))

    def test_busy_machine_does_not_make_future_task_executable(self):
        events = trace_fixture()
        manifest = events[0]['manifest']
        manifest['initial_wip'] = 2
        manifest['lots'].append(dict(manifest['lots'][0], id='y', name='y'))
        step = manifest['routes']['r'][0]
        step['processing']['c'] = step['cadence']['c'] = 20
        plan = events[3]['plan']
        pending = dict(plan['tasks'][0], id='tx', not_before=10)
        plan['tasks'][0].update(id='ty', lot_ids=['y'])
        plan['tasks'].append(pending)
        events[4].update(lots=['y'], plan_task_id='ty', processing_seconds=20,
                         cadence_seconds=20, machine_ready=20, process_end=20, lot_end=20)
        events[5]['to'] = 20
        events[6].update(time=20, lot='y')
        events[7].update(time=20, lot='y')
        del events[8]
        events[-1]['lot_statuses'] = {'x': 'waiting', 'y': 'done'}
        events[3:3] = [{'kind': 'release', 'time': 0, 'lot': 'y'},
                       {'kind': 'ready', 'time': 0, 'lot': 'y', 'step': 1, 'visit': 1}]
        self.assert_valid(events)

    def test_unready_predecessor_can_leave_exact_future_task_waiting(self):
        events = trace_fixture()
        manifest = events[0]['manifest']
        second = copy.deepcopy(manifest['routes']['r'][0])
        second['step'] = 2
        first = manifest['routes']['r'][0]
        first['family'] = 'H'
        first['processing']['c'] = first['cadence']['c'] = 20
        manifest['routes']['r'].append(second)
        # y supplies legal demand on idle G, while the explicit head task is
        # x's next operation and x is still processing its predecessor on H.
        manifest['routes']['ry'] = [dict(copy.deepcopy(second), step=1)]
        manifest['lots'].append(dict(manifest['lots'][0], id='y', name='y', route='ry'))
        manifest['initial_wip'] = manifest['physical_machines'] = 2
        manifest['machines'].append(dict(manifest['machines'][0], id=1, family='H'))
        manifest['controlled_machine_ids'] = [0, 1]
        plan = events[3]['plan']
        plan['scope'] = [0, 1]
        plan['tasks'][0]['machine'] = 1
        plan['tasks'].append({'id': 't2', 'machine': 0, 'lot_ids': ['x'],
                              'steps': [2], 'visits': [1], 'not_before': 10})
        events[4].update(machine=1, processing_seconds=20, cadence_seconds=20,
                         machine_ready=20, process_end=20, lot_end=20)
        events[5]['to'] = 20
        events[6]['time'] = 20
        events[7] = {'kind': 'ready', 'time': 20, 'lot': 'x', 'step': 2, 'visit': 1}
        del events[8]
        events[-1]['lot_statuses'] = {'x': 'waiting', 'y': 'waiting'}
        events[3:3] = [{'kind': 'release', 'time': 0, 'lot': 'y'},
                       {'kind': 'ready', 'time': 0, 'lot': 'y', 'step': 1, 'visit': 1}]
        result = self.assert_valid(events)
        self.assertGreater(result['opportunity_audit']['family_opportunities']['G']
                           ['legal_demand_clock_checks'], 0)


if __name__ == '__main__':
    unittest.main()
